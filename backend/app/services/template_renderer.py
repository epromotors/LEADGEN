"""
backend/app/services/template_renderer.py

Authoritative Template Rendering and Personalization Engine.
Features:
- Campaign segment default templates (no legacy fixed-pricing, no unrelated links)
- Variable substitution for approved vocabulary:
  {business_name}, {website}, {domain}, {audit_summary}, {audit_findings},
  {audit_recommendations}, {opportunity_summary}, {proposal_summary},
  {suggested_service}, {sender_name}, {company_name}, {company_website}, {reply_to}
  + Batch 1-3 new tokens: {city}, {niche_label}, {finding_count}, {contact_name}
- Business-name cleaning per guide section 6.4 (niche_router.clean_business_name)
- Integration with canonical audit_results via OpportunityEngine
- Safe HTML escaping for untrusted user inputs (XSS prevention)
- Plain-text and HTML synchronized generation
- Fail-closed validation against unresolved placeholders ({placeholder})
"""

import html
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from app.models import Lead, Audit
from app.utils.spintax import process_template
from app.engines.opportunity_engine import OpportunityEngine
from app.services.audit_email_service import AuditEmailService, AuditEmailGenerationError
from app.config import settings
from app.services.niche_router import (
    clean_business_name as _clean_business_name,
    clean_domain as _clean_domain,
    is_social_domain as _is_social_domain,
    niche_name_from_id as _niche_name_from_id,
)


def sanitize_url(url: Optional[str], default: str = "") -> str:
    """
    Validates and sanitizes a URL for use in HTML href attributes and template variables.
    Enforces:
    - Only http:// and https:// schemes allowed.
    - Rejects javascript:, data:, vbscript:, file:, about:, blob:, etc.
    - Strips leading/trailing whitespace and ASCII control characters (0x00-0x1F, 0x7F).
    - Rejects protocol-relative URLs starting with '//'.
    - Validates scheme structure and hostname presence.
    - If invalid, dangerous, or unparseable, returns default (empty string).
    """
    if not url or not isinstance(url, str):
        return default

    # Strip whitespace and control characters (including \r, \n, \t, \x00-\x1F, \x7F)
    cleaned = "".join(ch for ch in url.strip() if ord(ch) >= 32 and ord(ch) != 127)
    lower = cleaned.lower()

    # Reject dangerous schemes immediately
    if lower.startswith(("javascript:", "data:", "vbscript:", "file:", "about:", "blob:")):
        return default

    # Reject protocol-relative URLs
    if lower.startswith("//"):
        return default

    # Check for encoded dangerous schemes (e.g., %6a%61%76%61%73%63%72%69%70%74)
    try:
        unquoted = urllib.parse.unquote(cleaned).lower()
        unquoted_clean = "".join(ch for ch in unquoted if ord(ch) >= 32 and ord(ch) != 127)
        if unquoted_clean.startswith(("javascript:", "data:", "vbscript:", "file:", "about:", "blob:")):
            return default
        if unquoted_clean.startswith("//"):
            return default
    except Exception:
        return default

    # Require http:// or https://
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return default

    try:
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme.lower() not in ("http", "https"):
            return default
        if not parsed.netloc:
            return default
    except Exception:
        return default

    # Disallow unescaped quotes or whitespace inside netloc
    if any(ch in parsed.netloc for ch in ('"', "'", "<", ">", " ")):
        return default

    return cleaned


# ─── Default Templates per Campaign Segment ───────────────────────────────────

DEFAULT_SEGMENT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "no_website_design": {
        "subject": "{business_name} — website design & online presence",
        "template": (
            "Hi {business_name},\n\n"
            "I was looking for {business_name} online and noticed you do not currently have an active website.\n\n"
            "### Why an Active Website is Essential:\n"
            "Today, over 84% of customers search on Google and check a company's website before picking up the phone or hiring. Without an online presence:\n"
            "- Credibility Risk: High-intent customers often question whether the business is active or legitimate.\n"
            "- Direct Competitor Loss: Prospective clients searching for your services immediately click on competitors who have a modern website and active Google listing.\n"
            "- Lost Revenue: Qualified inquiries, phone calls, and high-value jobs are handed directly to competitors every week.\n\n"
            "At {company_name}, we build high-performing, modern websites engineered specifically to build immediate trust and convert searchers into paying customers.\n\n"
            "### What We Provide in Your New Website:\n"
            "- Custom, Conversion-Focused Design: Clean, modern layout tailored specifically to {business_name} and your services (no generic templates)\n"
            "- 100% Mobile & Tablet Optimized: Fast-loading, responsive design that looks flawless on iPhones, Android devices, and tablets\n"
            "- Instant Lead & Enquiry Capture: Direct WhatsApp chat integration, click-to-call buttons, and quote inquiry forms routed straight to your phone and email\n"
            "- Google Search & Local SEO Setup: Essential search indexing, Google Maps linking, and local visibility configuration so customers find you first\n"
            "- Turnkey Delivery & Full Ownership: Fast turnaround (live in 5–7 days), complete with domain connection, business email, and secure high-speed SSL hosting\n\n"
            "Would you be open to a quick 5-minute conversation or seeing a free, no-obligation preview mockup of what a modern website for {business_name} could look like?\n\n"
            "Just reply to this email and I would be glad to share a tailored concept for {business_name}.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "broken_website_repair": {
        "subject": "Technical observation regarding {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "While reviewing business websites in your area, I noticed that {domain} is currently encountering accessibility or technical issues:\n"
            "{audit_findings}\n\n"
            "When a website is unreachable or returning errors, potential customers cannot access your contact details or service offerings.\n\n"
            "At {company_name}, we help businesses restore, repair, and maintain stable web infrastructure. "
            "If your team is already working on this, please feel free to disregard this note. Otherwise, reply here and we can assist in diagnosing and restoring access.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "outdated_website_modernization": {
        "subject": "Mobile experience and modernization for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "I recently reviewed {domain} and noticed several opportunities to improve the visitor experience and modern mobile presentation:\n"
            "{audit_findings}\n\n"
            "Updating your site's mobile responsiveness and layout ensures visitors can easily navigate your offerings and get in touch from any device.\n\n"
            "Would you be open to a brief conversation this week to discuss a modernization plan for {domain}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "valid_website_seo": {
        "subject": "Search visibility and technical notes for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "We recently ran an objective technical audit of {domain} and identified a few specific technical factors that may be affecting your search discoverability:\n"
            "{audit_findings}\n\n"
            "Addressing these technical foundations helps search engines index your pages accurately and ensures prospective clients find your business.\n\n"
            "If you would like to review the complete findings and next steps, just let me know.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "valid_website_redesign": {
        "subject": "Design & user experience review for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "I took a close look at {domain} and put together a few observations regarding visitor navigation, presentation, and conversion pathways:\n"
            "{audit_findings}\n\n"
            "A modern, streamlined user interface helps build immediate trust with prospective clients and makes reaching out effortless.\n\n"
            "Happy to share a quick walkthrough if this is something your team is evaluating.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "valid_website_link_building": {
        "subject": "Website authority and reference profile for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "While reviewing {domain}, we examined your search footprint and identified opportunities to strengthen your technical authority and digital references:\n"
            "{audit_findings}\n\n"
            "Building verified digital citations and search visibility helps prospective customers discover {business_name} ahead of competitors.\n\n"
            "Let me know if you would like to discuss a structured authority plan.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "valid_website_marketing": {
        "subject": "Digital growth and visibility review for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "I took a look at {domain} and identified opportunities to increase inbound customer enquiries and visibility:\n"
            "{audit_findings}\n\n"
            "Aligning your website's presentation with active search intent helps convert visitors into direct phone and WhatsApp enquiries.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "audit_follow_up": {
        "subject": "Following up on technical review for {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "Following up on our earlier note regarding {domain}. We completed the technical review and summarized the key findings below:\n\n"
            "{audit_findings}\n\n"
            "Addressing these priority points will help improve visitor conversion and prevent potential clients from encountering technical issues.\n\n"
            "If you would like a quick walkthrough of the findings, just let me know.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "generic_first_contact": {
        "subject": "Website observation: {domain}",
        "template": (
            "Hi {business_name},\n\n"
            "I recently reviewed {domain} while analyzing local business websites, and put together a few specific technical observations regarding your site's presentation, mobile experience, and performance:\n\n"
            "{audit_findings}\n\n"
            "At {company_name}, we help growing businesses resolve these technical factors to improve visitor trust and turn more visits into direct customer inquiries.\n\n"
            "Sharing these notes as helpful background for your team. Would you be open to a brief conversation this week to discuss these points for {domain}?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}"
        ),
    },
    "public_provider_demo": {
        "subject": "Introduction & website demonstration for {business_name}",
        "template": (
            "Hi {business_name},\n\n"
            "My name is {sender_name} with {company_name}. We design and build modern, high-performing websites for growing businesses.\n\n"
            "While reviewing your web presence for {domain}, I noted several key areas that directly impact visitor conversion and customer inquiries:\n\n"
            "{audit_findings}\n\n"
            "I am reaching out to offer a brief, no-obligation demonstration showing how an updated website can resolve these factors and capture prospective customer enquiries directly from search and WhatsApp.\n\n"
            "If you would be open to seeing a quick demonstration for {business_name}, simply reply to this email and I will be glad to share a walkthrough with your team.\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{company_name} · {company_website}\n\n"
            "If this note is not relevant to your business, please feel free to disregard or reply 'unsubscribe'."
        ),
    },
}


class TemplateRenderingError(Exception):
    """Raised when template rendering fails or produces unresolved required variables."""
    pass


class TemplateRenderer:
    """Renders campaign templates safely into plain-text and HTML formats."""

    @staticmethod
    def get_default_template(campaign_type: str) -> Dict[str, str]:
        c_type = str(campaign_type or "generic_first_contact").lower()
        return DEFAULT_SEGMENT_TEMPLATES.get(
            c_type, DEFAULT_SEGMENT_TEMPLATES["generic_first_contact"]
        )

    @classmethod
    def extract_context_variables(
        cls,
        lead: Lead,
        audit: Optional[Audit] = None,
        campaign_type: Optional[str] = None,
        sender_account: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        Extract approved variables from lead, audit, and sender configuration.
        Derives audit findings strictly from canonical audit_results via OpportunityEngine.
        """
        if isinstance(campaign_type, dict) and sender_account is None:
            sender_account = campaign_type
            campaign_type = None

        # ── Guide section 6.4: clean business name before substitution ─────────
        raw_business_name = (getattr(lead, "business_name", "") or "").strip()
        business_name = _clean_business_name(raw_business_name) if raw_business_name else "there"

        website_raw = (getattr(lead, "website", "") or "").strip()
        safe_website = sanitize_url(website_raw)
        website = safe_website
        domain = ""
        if safe_website:
            raw_domain = (
                safe_website.replace("https://", "")
                .replace("http://", "")
                .replace("www.", "")
                .rstrip("/")
                .split("/")[0]
            )
            # Guide section 6.4: treat social/directory domains as no-website
            if _is_social_domain(raw_domain):
                website = ""
                domain = ""
            else:
                domain = _clean_domain(raw_domain)
        elif website_raw:
            # If the raw website had no scheme but is a clean domain like example.com
            clean_host = "".join(ch for ch in website_raw.strip() if ord(ch) >= 32 and ord(ch) != 127)
            if ":" not in clean_host and not clean_host.startswith(("//", "/")):
                candidate = "https://" + clean_host
                if sanitize_url(candidate):
                    website = candidate
                    domain = clean_host.replace("www.", "").rstrip("/").split("/")[0]

        # Sender context
        sender_name = "Ashish Sharma"
        company_name = "TEB Solutions"
        company_website = "tebsolutions.in"
        reply_to = "info@tebsolutions.in"

        if sender_account:
            sender_name = sender_account.get("sender_name") or sender_name
            company_name = sender_account.get("company_name") or company_name
            reply_to = sender_account.get("email") or reply_to

        # Defaults for audit-dependent variables
        audit_summary = ""
        audit_findings = ""
        audit_recommendations = ""
        opportunity_summary = ""
        proposal_summary = ""
        suggested_service = "Website Modernization & Search Optimization"

        is_audit_failed = bool(audit and (
            str(getattr(audit, "status", "")).lower() in ("failed", "auditstatus.failed", "error", "skipped")
            or not getattr(audit, "audit_results", None)
        ))

        if not website:
            suggested_service = "Full Web Design & Development"
            audit_summary = "No active business website detected."
            opportunity_summary = "Launch a professional online presence with mobile-ready web design."
            proposal_summary = "Deploy a conversion-focused website with enquiry capture and search discoverability."
        elif audit and is_audit_failed and audit.error_message:
            # Failed, skipped, or errored audit with explicit message
            err_msg = audit.error_message
            audit_summary = f"Website check reported: {err_msg}"
            audit_findings = f"• Accessibility: {err_msg}"
            audit_recommendations = ""
        elif audit and audit.audit_results:
            # Use OpportunityEngine for canonical findings
            opps = OpportunityEngine.evaluate_opportunities(
                audit_results=audit.audit_results,
                url_info={"requested_url": audit.audited_url or website},
                site_summary=audit.site_summary,
            )
            if opps:
                top_opp = opps[0]
                suggested_service = top_opp.get("service_name", suggested_service)
                opportunity_summary = top_opp.get("rationale", "")
                proposal_summary = top_opp.get("proposed_next_step", "")

                critical_opps = [o for o in opps if o.get("severity") == "critical"]
                warning_opps = [o for o in opps if o.get("severity") == "warning"]

                finding_bullets = []
                rec_bullets = []

                if critical_opps:
                    finding_bullets.append("Critical Issues:")
                    for opp in critical_opps[:3]:
                        ev = opp.get("evidence", [])
                        ev_str = "; ".join(ev[:2]) if ev else opp.get("service_name", "")
                        finding_bullets.append(f"• {opp.get('service_category', 'Technical')}: {ev_str}")
                        if opp.get("proposed_next_step"):
                            rec_bullets.append(f"• Recommended: {opp['proposed_next_step']}")

                if warning_opps:
                    finding_bullets.append("Warnings:")
                    for opp in warning_opps[:3]:
                        ev = opp.get("evidence", [])
                        ev_str = "; ".join(ev[:2]) if ev else opp.get("service_name", "")
                        finding_bullets.append(f"• {opp.get('service_category', 'Technical')}: {ev_str}")
                        if opp.get("proposed_next_step"):
                            rec = f"• Recommended: {opp['proposed_next_step']}"
                            if rec not in rec_bullets:
                                rec_bullets.append(rec)
                elif critical_opps:
                    finding_bullets.append("Warnings:\n• No warnings were identified in this audit.")

                if not finding_bullets:
                    for opp in opps[:3]:
                        ev = opp.get("evidence", [])
                        ev_str = "; ".join(ev[:2]) if ev else opp.get("service_name", "")
                        finding_bullets.append(f"• {opp.get('service_category', 'Technical')}: {ev_str}")
                        if opp.get("proposed_next_step"):
                            rec_bullets.append(f"• Recommended: {opp['proposed_next_step']}")

                audit_findings = "\n".join(finding_bullets)
                audit_recommendations = "\n".join(rec_bullets)
                audit_summary = f"Identified {len(opps)} area(s) for improvement, including {suggested_service}."
            else:
                audit_summary = audit.audit_summary or "Website audit completed with solid baseline results."
                audit_findings = "• Core technical foundations are operational."
                audit_recommendations = ""
        elif audit and audit.error_message:
            err_msg = audit.error_message
            audit_summary = f"Website check reported: {err_msg}"
            audit_findings = f"• Accessibility: {err_msg}"
            audit_recommendations = ""
        elif audit and audit.audit_summary:
            audit_summary = audit.audit_summary
        elif website:
            scheme = "HTTPS (Secure)" if website.lower().startswith("https://") else "HTTP (Unencrypted)"
            audit_summary = f"Initial technical review for {domain}."
            audit_findings = (
                f"• URL Security: Connection is configured over {scheme}.\n"
                f"• Search Discoverability: Domain {domain} requires local search and sitemap indexing review.\n"
                f"• Mobile Experience: Responsive layout and viewport verification pending."
            )

        # ── Batch 1-3 new tokens (guide sections 6.1 / 11) ─────────────────
        city = (getattr(lead, "city", "") or "").strip()
        niche_id = getattr(lead, "niche_id", None)
        niche_label = _niche_name_from_id(niche_id) or ""
        finding_count = str(len([b for b in audit_findings.split("\n") if b.strip().startswith("•")]))
        # contact_name: only use when a verified owner name exists
        contact_name = ""
        if sender_account:
            contact_name = sender_account.get("contact_name", "") or ""

        return {
            "business_name": business_name,
            "website": website,
            "domain": domain,
            "audit_summary": audit_summary,
            "audit_findings": audit_findings,
            "audit_recommendations": audit_recommendations,
            "opportunity_summary": opportunity_summary,
            "proposal_summary": proposal_summary,
            "suggested_service": suggested_service,
            "sender_name": sender_name,
            "company_name": company_name,
            "company_website": company_website,
            "reply_to": reply_to,
            # ── Batch 1-3 new tokens ──────────────────────────────────────
            "city": city,
            "niche_label": niche_label,
            "finding_count": finding_count,
            "contact_name": contact_name,
        }

    @classmethod
    def render_campaign_email(
        cls,
        template: Optional[str],
        subject_template: Optional[str],
        lead: Lead,
        audit: Optional[Audit] = None,
        campaign_type: Optional[str] = None,
        sender_account: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Renders subject, plain_body, and html_body for a lead.
        Enforces fail-closed validation: no unresolved {variable} placeholders allowed.
        """
        # Safe fallback if template is not a valid string or empty
        if not isinstance(template, str) or not template.strip() or hasattr(template, "_mock_name"):
            defaults = cls.get_default_template(campaign_type or "generic_first_contact")
            template = defaults["template"]

        if not isinstance(subject_template, str) or not subject_template.strip() or hasattr(subject_template, "_mock_name"):
            defaults = cls.get_default_template(campaign_type or "generic_first_contact")
            subject_template = defaults["subject"]

        # The untouched default for every audit-dependent campaign is a strategy
        # marker, not independent copy.  Delegate it to the same evidence-backed
        # generator used by the Audits proposal panel.  Any operator edit to
        # either the body or subject remains an explicit custom override.
        c_type = str(campaign_type or "generic_first_contact").lower()
        defaults = cls.get_default_template(c_type)
        is_default_template = (
            template.strip() == defaults["template"].strip()
            and subject_template.strip() == defaults["subject"].strip()
        )
        is_niche_campaign = c_type in ("niche_outreach", "niche_campaign")

        uses_canonical_audit_content = (
            (AuditEmailService.is_audit_dependent(c_type) or bool(audit and getattr(audit, "audit_results", None)))
            and is_default_template
            and c_type != "no_website_design"
        )
        if uses_canonical_audit_content:
            try:
                generated = AuditEmailService.generate(
                    lead=lead,
                    audit=audit,
                    campaign_type=c_type,
                    sender_account=sender_account,
                    include_recommended_actions=False,
                )
            except AuditEmailGenerationError as exc:
                raise TemplateRenderingError(str(exc)) from exc
            return {
                "subject": generated["subject"],
                "plain_body": generated["body_text"],
                "html_body": generated["body_html"],
                "variables_used": {},
                "content_strategy": "audit_generated",
                "audit_reference": generated["audit_reference"],
                "lead_identity": generated["lead_identity"],
                "website": generated["website"],
                "selected_findings": generated["selected_findings"],
                "recommended_actions": generated["recommended_actions"],
                "service_classification": generated["service_classification"],
                "renderer_version": generated["renderer_version"],
            }

        # ── Batch 1-3: Niche Template Routing ─────────────────────────────────
        # When a lead has a confirmed niche (or auto-detected with confidence >= 2)
        # and default copy is requested, route to the 260-template niche library.
        niche_id = getattr(lead, "niche_id", None)
        if hasattr(niche_id, "_mock_name") or not isinstance(niche_id, (str, int)) or not str(niche_id).strip():
            niche_id = None
        if not niche_id and getattr(lead, "business_name", None):
            try:
                from app.services.niche_router import classify_lead_niche
                detected_niche, _, conf = classify_lead_niche(lead.business_name, getattr(lead, "category", None))
                if detected_niche and conf >= 2:
                    niche_id = detected_niche
                    try:
                        lead.niche_id = detected_niche
                    except Exception:
                        pass
            except Exception:
                pass

        if niche_id and (is_niche_campaign or (is_default_template and c_type not in ("no_website_design", "generic_first_contact", "public_provider_demo"))):
            try:
                from app.services.campaign_eligibility_service import evaluate_niche_segment
                from app.services.niche_template_service import (
                    render_niche_template,
                    NicheTemplateError,
                    CAMPAIGN_TYPE_TO_SEGMENT,
                )
                seg_no = None
                if is_niche_campaign or c_type == "generic_first_contact":
                    c_type_val, _ = evaluate_niche_segment(lead, audit)
                    if c_type_val:
                        seg_no = CAMPAIGN_TYPE_TO_SEGMENT.get(c_type_val)
                else:
                    seg_no = CAMPAIGN_TYPE_TO_SEGMENT.get(c_type)
                    if seg_no is None:
                        c_type_val, _ = evaluate_niche_segment(lead, audit)
                        if c_type_val:
                            seg_no = CAMPAIGN_TYPE_TO_SEGMENT.get(c_type_val)

                if seg_no is not None:
                    variables = cls.extract_context_variables(
                        lead=lead,
                        audit=audit,
                        campaign_type=c_type,
                        sender_account=sender_account,
                    )
                    niche_res = render_niche_template(niche_id, seg_no, variables)
                    plain_body = niche_res["body"].strip()

                    # AGENT_GUIDE Section 5 Step 6: Platform appends signature at send time
                    if not re.search(r"^(best regards|regards|warm regards|sincerely)\b", plain_body, re.I | re.M):
                        sender = variables.get("sender_name") or "Ashish Sharma"
                        company = variables.get("company_name", "TEB Solutions")
                        plain_body = f"{plain_body}\n\nBest regards,\n{sender}\n{company}"

                    html_body = cls._wrap_plain_as_html(plain_body, variables)
                    return {
                        "subject": niche_res["subject"].strip(),
                        "plain_body": plain_body,
                        "html_body": html_body,
                        "variables_used": variables,
                        "content_strategy": f"niche_{niche_id}_seg_{seg_no}",
                        "segment_no": seg_no,
                        "niche_id": niche_id,
                    }
            except Exception as e:
                logger.warning("Niche template rendering fallback: %s", e)

        variables = cls.extract_context_variables(
            lead=lead,
            audit=audit,
            campaign_type=campaign_type,
            sender_account=sender_account,
        )

        # 1. Subject rendering: spintax first, then variable substitution
        subject_raw = process_template(subject_template or "{business_name} - update", variables)
        subject = cls._substitute_variables(subject_raw, variables, is_html=False)

        # 2. Body rendering: spintax first, then variable substitution
        body_raw = process_template(template, variables)
        plain_body = cls._substitute_variables(body_raw, variables, is_html=False)

        # 3. Check for unresolved placeholders
        unresolved_in_subject = cls._find_unresolved_placeholders(subject)
        if unresolved_in_subject:
            raise TemplateRenderingError(
                f"Subject contains unresolved placeholders: {', '.join(unresolved_in_subject)}"
            )

        unresolved_in_body = cls._find_unresolved_placeholders(plain_body)
        if unresolved_in_body:
            raise TemplateRenderingError(
                f"Body contains unresolved placeholders: {', '.join(unresolved_in_body)}"
            )

        # 4. Generate HTML version
        if "<html" in template.lower() or "<div" in template.lower() or "<p" in template.lower():
            # Template is already HTML formatted
            html_body = cls._substitute_variables(body_raw, variables, is_html=True)
        else:
            # Wrap plain body in clean email-safe HTML container
            html_body = cls._wrap_plain_as_html(plain_body, variables)

        return {
            "subject": subject.strip(),
            "plain_body": plain_body.strip(),
            "html_body": html_body.strip(),
            "variables_used": variables,
            "content_strategy": "custom_template" if AuditEmailService.is_audit_dependent(c_type) else c_type,
        }

    @staticmethod
    def _substitute_variables(text: str, variables: Dict[str, str], is_html: bool = False) -> str:
        if not isinstance(text, str):
            if text is None or hasattr(text, "_mock_name"):
                return ""
            text = str(text)
        # Clean up any leftover recommended action headings before substitution
        text = re.sub(r"###?\s*(?:Recommended|Actionable|Priority)[^\n]*\n+\s*\{audit_recommendations\}", "", text, flags=re.IGNORECASE)
        for k, v in variables.items():
            pattern = re.compile(rf"\{{{k}\}}", re.IGNORECASE)
            val_str = str(v) if v is not None and not isinstance(v, str) else (v or "")
            if is_html:
                val_str = html.escape(val_str, quote=True).replace("\n", "<br>")
            text = pattern.sub(lambda _: val_str, text)
        return text

    @staticmethod
    def _find_unresolved_placeholders(text: str) -> List[str]:
        if not isinstance(text, str):
            return []
        # Match anything of the pattern {word}
        # Ignore spintax remnants {a|b} which shouldn't exist after process_template
        matches = re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text)
        return list(set(matches))

    @classmethod
    def _link_urls_in_plain_text(cls, text: str) -> str:
        """
        Auto-link URLs in plain-text while:
        1. Validating that the URL is a safe http/https URL.
        2. Excluding trailing punctuation (. , ; : ! ? ) ] ' ").
        3. Escaping URL and link text for HTML context.
        """
        def _replace_link(match):
            raw_url = match.group(0)
            trailing = ""
            while raw_url and raw_url[-1] in ".,;:!?)]'\"":
                trailing = raw_url[-1] + trailing
                raw_url = raw_url[:-1]

            clean_url = sanitize_url(raw_url)
            if clean_url:
                esc_url = html.escape(clean_url, quote=True)
                return f'<a href="{esc_url}" style="color:#2563eb;text-decoration:underline;">{esc_url}</a>{trailing}'
            return html.escape(raw_url, quote=True) + trailing

        return re.sub(r'https?://[^\s<>"\'&]+', _replace_link, text)

    @classmethod
    def _wrap_plain_as_html(cls, plain_body: str, variables: Dict[str, str]) -> str:
        """Render plain-text email with clean, professional, responsive HTML styling."""
        safe_body = html.escape(plain_body, quote=True)
        linked_body = cls._link_urls_in_plain_text(safe_body)

        # 1. Bold: **text** -> <strong>text</strong>
        linked_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", linked_body)

        # 2. Italic: *text* -> <em>text</em>
        linked_body = re.sub(r"(?<!\*)\*([^\*\n]+)\*(?!\*)", r"<em>\1</em>", linked_body)

        # 3. Format structured blocks (headings, check items, bullets, paragraphs)
        blocks = linked_body.strip().split("\n\n")
        formatted_blocks = []

        contact_name = variables.get("contact_name") or variables.get("sender_name") or "Ashish Sharma"
        company_name = variables.get("company_name") or "TEB Solutions"
        contact_email = variables.get("reply_to") or "info@tebsolutions.in"

        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            # Heading (### Subheading or ## Heading or # Heading)
            first_line = lines[0]
            if first_line.startswith("### ") or first_line.startswith("## ") or first_line.startswith("# "):
                heading_text = re.sub(r"^#{1,3}\s*", "", first_line)
                # If this was an audit recommendations heading, omit it
                if any(k in heading_text.lower() for k in ("recommended", "recommendation", "next steps")):
                    continue
                h_html = f'<div style="font-size: 16px; font-weight: 700; color: #0f172a; margin: 20px 0 10px 0; letter-spacing: -0.2px;">{heading_text}</div>'
                rest = lines[1:]
                if rest:
                    b_lines = []
                    for r in rest:
                        if r.startswith("✓") or r.startswith("\u2713"):
                            b_lines.append(f'<div style="margin: 8px 0; line-height: 1.55; color: #334155; font-size: 14.5px;"><span style="color: #2563eb; font-weight: bold; margin-right: 8px;">✓</span>{r[1:].strip()}</div>')
                        elif r.startswith("- ") or r.startswith("• "):
                            b_lines.append(f'<div style="margin: 8px 0; line-height: 1.55; color: #334155; font-size: 14.5px;"><span style="color: #64748b; font-weight: bold; margin-right: 8px;">•</span>{r[2:].strip()}</div>')
                        else:
                            b_lines.append(f'<div style="margin: 6px 0; line-height: 1.55; color: #334155; font-size: 14.5px;">{r}</div>')
                    card_content = "\n".join(b_lines)
                    formatted_blocks.append(
                        f'{h_html}\n<div style="margin: 12px 0 16px 0; padding: 16px 18px; background: #f8fafc; border-left: 4px solid #2563eb; border-radius: 8px;">\n{card_content}\n</div>'
                    )
                else:
                    formatted_blocks.append(h_html)
                continue

            # Bullet list or finding blocks without ###
            is_bullet_block = any(l.startswith(("-", "•", "✓", "\u2713")) for l in lines)
            is_audit_section = any(l.startswith(("Critical Issues:", "Warnings:")) for l in lines)
            # Filter out any standalone recommendation headers
            if any(l.startswith(("Recommended:", "Recommended Actions:", "Recommended Next Steps:", "Recommended Modernisation:", "Actionable Authority Strategy:", "High-Impact Adjustments:")) for l in lines):
                continue

            if is_bullet_block or is_audit_section:
                b_lines = []
                border_color = "#2563eb"
                bg_color = "#f8fafc"
                has_crit = any(l.startswith("Critical Issues:") for l in lines)
                has_warn = any(l.startswith("Warnings:") for l in lines)

                if has_crit:
                    border_color = "#ef4444"
                    bg_color = "#fef2f2"
                elif has_warn:
                    border_color = "#f59e0b"
                    bg_color = "#fffbeb"

                for l in lines:
                    if l.startswith("Critical Issues:"):
                        b_lines.append('<div style="font-size: 14px; font-weight: 700; color: #991b1b; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Critical Issues:</div>')
                    elif l.startswith("Warnings:"):
                        b_lines.append('<div style="font-size: 14px; font-weight: 700; color: #92400e; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">Warnings:</div>')
                    elif l.startswith("✓") or l.startswith("\u2713"):
                        b_lines.append(f'<div style="margin: 8px 0; line-height: 1.55; color: #334155; font-size: 14.5px;"><span style="color: #2563eb; font-weight: bold; margin-right: 8px;">✓</span>{l[1:].strip()}</div>')
                    elif l.startswith("- ") or l.startswith("• "):
                        bullet_color = "#991b1b" if has_crit else ("#92400e" if has_warn else "#64748b")
                        b_lines.append(f'<div style="margin: 8px 0; line-height: 1.55; color: #334155; font-size: 14.5px;"><span style="color: {bullet_color}; font-weight: bold; margin-right: 8px;">•</span>{l[2:].strip()}</div>')
                    else:
                        b_lines.append(f'<div style="font-weight: 600; margin: 8px 0 4px 0; color: #0f172a; font-size: 15px;">{l}</div>')
                card_html = "\n".join(b_lines)
                formatted_blocks.append(
                    f'<div style="margin: 16px 0; padding: 16px 18px; background: {bg_color}; border-left: 4px solid {border_color}; border-radius: 8px;">\n{card_html}\n</div>'
                )
                continue

            # Signature block: detect sign-off lines
            if any(l.lower().startswith(("best regards,", "regards,", "warm regards,", "sincerely,")) for l in lines):
                formatted_blocks.append(
                    f"""<div style="margin-top: 26px; padding-top: 18px; border-top: 1px solid #e2e8f0; font-size: 15px; line-height: 1.55;">
  <div style="color: #475569; margin-bottom: 4px;">Best regards,</div>
  <div style="font-weight: 700; color: #0f172a; font-size: 16px;">{html.escape(contact_name)}</div>
  <div style="font-weight: 600; color: #334155; font-size: 14px;">{html.escape(company_name)}</div>
  <div style="font-size: 13.5px; color: #64748b; margin-top: 4px;">Contact: {html.escape(contact_email)}</div>
</div>"""
                )
                continue

            # Regular paragraph
            p_content = "<br>".join(lines)
            formatted_blocks.append(f'<p style="margin: 0 0 16px 0; line-height: 1.65; color: #1e293b; font-size: 15px;">{p_content}</p>')

        content_html = "\n".join(formatted_blocks)

        company = html.escape(company_name, quote=True)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Email</title>
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1e293b;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;">
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.04);">
        <tr><td style="height:4px;background:#2563eb;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="padding:28px 32px;font-size:15px;line-height:1.7;color:#1e293b;">
          <div style="font-size:12px;font-weight:700;letter-spacing:1px;color:#2563eb;margin-bottom:18px;text-transform:uppercase;">
            {company} · Web Solutions
          </div>
          {content_html}
        </td></tr>
        <tr><td style="padding:16px 32px;background:#f1f5f9;border-top:1px solid #e2e8f0;font-size:11.5px;color:#64748b;line-height:1.45;">
          This message was sent regarding business web presence. If this note is not relevant to your team, please feel free to disregard.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
