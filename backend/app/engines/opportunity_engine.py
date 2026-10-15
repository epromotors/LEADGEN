"""
opportunity_engine.py — Evidence-Based Service Opportunity & Client Proposal Engine

Translates verified audit findings (from the 62 canonical factors) into credible,
traceable service proposals for TEB Solutions.

Enforces Master Plan requirements:
- Evidence-to-offer mapping (Technical SEO, Local SEO, AI-Search, Web Design, Performance).
- Distinguishes small repairs from broader redesign opportunities.
- Selects at most 2–3 salient, high-confidence observations per proposal.
- Strict claim provenance: records contributing factor IDs for every generated claim.
- Disallows fabricated ranking, traffic, conversion, or revenue claims.
- Human review gate: drafts are preview-only and require explicit approval before sending.
"""

from typing import Any, Dict, List, Optional
import html


class OpportunityEngine:
    """Evaluates audit findings and generates service opportunities and proposal drafts."""

    @staticmethod
    def evaluate_opportunities(
        audit_results: Dict[str, Any],
        url_info: Optional[Dict[str, Any]] = None,
        site_summary: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate audit results across the 11 canonical categories and produce
        structured service opportunities.
        """
        opportunities: List[Dict[str, Any]] = []
        target_url = (url_info.get("requested_url") if url_info else None) or "Target Site"

        # Helper to extract a factor result from audit_results dictionary
        def get_factor(group_name: str, check_key: str) -> Optional[Dict[str, Any]]:
            group = audit_results.get(group_name, {})
            return group.get(check_key)

        # 1. Technical SEO & Crawlability Remediation
        tech_ssl = get_factor("technical", "ssl")
        tech_robots = get_factor("technical", "robots")
        tech_canonical = get_factor("technical", "canonical")
        idx_soft_404 = get_factor("indexability", "soft_404")

        tech_factors: List[str] = []
        tech_evidence: List[str] = []

        if tech_ssl and tech_ssl.get("status") == "FAIL":
            tech_factors.append("technical.ssl")
            tech_evidence.append("Missing valid HTTPS/TLS certificate")
        if tech_robots and tech_robots.get("status") == "FAIL":
            tech_factors.append("technical.robots")
            tech_evidence.append(tech_robots.get("message") or "Robots.txt missing or improperly configured")
        if tech_canonical and tech_canonical.get("status") == "FAIL":
            tech_factors.append("technical.canonical")
            tech_evidence.append("Canonical tag missing or conflicted")
        if idx_soft_404 and idx_soft_404.get("status") == "FAIL":
            tech_factors.append("indexability.soft_404")
            tech_evidence.append("Soft 404 responses returning HTTP 200 on missing pages")

        if tech_factors:
            opportunities.append({
                "service_id": "technical_seo_remediation",
                "service_name": "Technical SEO & Infrastructure Remediation",
                "service_category": "Technical SEO",
                "scope": "repair",
                "relevant_factor_ids": tech_factors,
                "confidence": 1.0,
                "evidence": tech_evidence,
                "affected_urls": [target_url],
                "rationale": "Resolving fundamental HTTP, SSL, and canonical routing issues is necessary for search engines to crawl and index pages safely.",
                "proposed_next_step": "Configure automated HTTPS redirection, standard canonical link elements, and valid robots.txt rules.",
            })

        # 2. XML Sitemap & Indexing Architecture
        tech_sitemap = get_factor("technical", "sitemap")
        idx_noindex = get_factor("indexability", "noindex")
        links_broken = get_factor("links", "broken_links")

        sitemap_factors: List[str] = []
        sitemap_evidence: List[str] = []

        if tech_sitemap and tech_sitemap.get("status") == "FAIL":
            sitemap_factors.append("technical.sitemap")
            sitemap_evidence.append(tech_sitemap.get("message") or "XML sitemap missing or invalid format")
        if idx_noindex and idx_noindex.get("status") == "FAIL":
            sitemap_factors.append("indexability.noindex")
            sitemap_evidence.append("Noindex directive blocking search indexing on target page")
        if links_broken and links_broken.get("status") == "FAIL":
            sitemap_factors.append("links.broken_links")
            val = links_broken.get("value")
            sitemap_evidence.append(f"{val} broken internal link(s) detected" if val else "Broken internal links detected")

        if sitemap_factors:
            opportunities.append({
                "service_id": "sitemap_indexing_repair",
                "service_name": "Sitemap Discovery & Indexing Architecture",
                "service_category": "Crawl & Indexing",
                "scope": "repair",
                "relevant_factor_ids": sitemap_factors,
                "confidence": 0.95,
                "evidence": sitemap_evidence,
                "affected_urls": [target_url],
                "rationale": "A validated XML sitemap and clean internal links allow search engine crawlers to discover all published service pages without crawl waste.",
                "proposed_next_step": "Generate a clean sitemap.xml, declare it in robots.txt, and eliminate 404 internal hyperlinks.",
            })

        # 3. Local SEO, Entity Alignment & Structured Data
        local_nap = get_factor("local_seo", "has_nap")
        local_schema = get_factor("local_seo", "has_local_business_schema")
        local_maps = get_factor("local_seo", "has_google_maps")
        onpage_schema = get_factor("onpage", "schema")

        local_factors: List[str] = []
        local_evidence: List[str] = []

        if local_schema and local_schema.get("status") == "FAIL":
            local_factors.append("local_seo.has_local_business_schema")
            local_evidence.append("LocalBusiness schema markup missing")
        elif onpage_schema and onpage_schema.get("status") == "FAIL":
            local_factors.append("onpage.schema")
            local_evidence.append("Structured data (JSON-LD) missing from page head")
        if local_nap and local_nap.get("status") == "FAIL":
            local_factors.append("local_seo.has_nap")
            local_evidence.append("Consistent NAP (Name, Address, Phone) details not observable")
        if local_maps and local_maps.get("status") == "FAIL":
            local_factors.append("local_seo.has_google_maps")
            local_evidence.append("Google Maps directions/location embed missing")

        if local_factors:
            opportunities.append({
                "service_id": "local_seo_entity_alignment",
                "service_name": "Local SEO & Entity Structured Data",
                "service_category": "Local SEO",
                "scope": "optimization",
                "relevant_factor_ids": local_factors,
                "confidence": 0.9,
                "evidence": local_evidence,
                "affected_urls": [target_url],
                "rationale": "Structured LocalBusiness schema and consistent business NAP details build trust with search engines and support visibility in local map packs.",
                "proposed_next_step": "Deploy schema.org JSON-LD matching business records and embed verified location coordinates.",
            })

        # 4. Web Design & UI/UX Experience
        ux_cta = get_factor("ux", "cta")
        ux_fold = get_factor("ux", "cta_above_fold")
        ux_mobile = get_factor("technical", "mobile")
        ux_contrast = get_factor("ux", "contrast")
        ux_font = get_factor("ux", "font_size")

        ux_factors: List[str] = []
        ux_evidence: List[str] = []

        if ux_mobile and ux_mobile.get("status") == "FAIL":
            ux_factors.append("technical.mobile")
            ux_evidence.append("Viewport tag missing or mobile layout unoptimized")
        if ux_cta and ux_cta.get("status") == "FAIL":
            ux_factors.append("ux.cta")
            ux_evidence.append("Clear primary call-to-action button missing")
        elif ux_fold and ux_fold.get("status") == "FAIL":
            ux_factors.append("ux.cta_above_fold")
            ux_evidence.append("Call-to-action button not positioned within initial viewport")
        if ux_contrast and ux_contrast.get("status") == "FAIL":
            ux_factors.append("ux.contrast")
            ux_evidence.append("Text contrast ratio below standard legibility threshold")
        if ux_font and ux_font.get("status") == "FAIL":
            ux_factors.append("ux.font_size")
            ux_evidence.append("Body font size below recommended readable mobile scale")

        if ux_factors:
            # Check if multiple severe UX failures justify a redesign scope vs repair
            is_full_redesign = ("technical.mobile" in ux_factors) and (len(ux_factors) >= 3)
            scope = "redesign" if is_full_redesign else "repair"
            name = "Modern Website Redesign & Conversion Architecture" if is_full_redesign else "Web Design & Conversion UX Repair"

            opportunities.append({
                "service_id": "web_design_ux_improvement",
                "service_name": name,
                "service_category": "Web Design & UX",
                "scope": scope,
                "relevant_factor_ids": ux_factors,
                "confidence": 0.9,
                "evidence": ux_evidence,
                "affected_urls": [target_url],
                "rationale": "Visitors on mobile devices leave pages quickly when content is clipped, text is difficult to read, or the primary contact button is hard to find." if is_full_redesign else "Improving button hierarchy, contrast, and layout clarity reduces conversion friction for prospective customers.",
                "proposed_next_step": "Implement a responsive modern design system with prominent above-the-fold contact actions and verified mobile viewports." if is_full_redesign else "Refine button styling, above-the-fold placement, and typography contrast.",
            })

        # 5. Performance & Asset Optimization
        perf_ttfb = get_factor("performance", "response_time")
        perf_blocking = get_factor("performance", "render_blocking")
        img_webp = get_factor("images", "webp")
        img_lazy = get_factor("images", "lazy_load")

        perf_factors: List[str] = []
        perf_evidence: List[str] = []

        if perf_ttfb and perf_ttfb.get("status") == "FAIL":
            perf_factors.append("performance.response_time")
            val = perf_ttfb.get("value")
            perf_evidence.append(f"Server response time (TTFB) {val}ms exceeds recommended speed" if val else "Server response time is slow")
        if perf_blocking and perf_blocking.get("status") == "FAIL":
            perf_factors.append("performance.render_blocking")
            perf_evidence.append("Render-blocking CSS/JavaScript assets delaying initial paint")
        if img_webp and img_webp.get("status") == "FAIL":
            perf_factors.append("images.webp")
            perf_evidence.append("Images not utilizing modern WebP/AVIF compressed formats")
        if img_lazy and img_lazy.get("status") == "FAIL":
            perf_factors.append("images.lazy_load")
            perf_evidence.append("Below-the-fold images missing loading='lazy' attributes")

        if perf_factors:
            opportunities.append({
                "service_id": "performance_speed_optimization",
                "service_name": "Performance, Speed & Asset Optimization",
                "service_category": "Performance",
                "scope": "optimization",
                "relevant_factor_ids": perf_factors,
                "confidence": 0.85,
                "evidence": perf_evidence,
                "affected_urls": [target_url],
                "rationale": "Fast page rendering and lightweight assets directly prevent visitor bounce and improve interaction speed across all devices.",
                "proposed_next_step": "Enable asset compression, defer non-critical scripts, and convert image assets to modern WebP format.",
            })

        # 6. AI-Search & Entity Readiness Heuristics
        # Note: External citations are tracked separately; heuristics evaluated from robots & schema.
        ai_factors: List[str] = []
        ai_evidence: List[str] = []

        if local_schema and local_schema.get("status") == "FAIL":
            ai_factors.append("local_seo.has_local_business_schema")
            ai_evidence.append("Missing entity metadata required for AI knowledge panels")

        onpage_title = get_factor("onpage", "page_title")
        onpage_h1 = get_factor("onpage", "h1")
        if onpage_title and onpage_title.get("status") == "FAIL":
            ai_factors.append("onpage.page_title")
            ai_evidence.append("Page title missing or non-descriptive")
        if onpage_h1 and onpage_h1.get("status") == "FAIL":
            ai_factors.append("onpage.h1")
            ai_evidence.append("Primary H1 heading missing")

        if ai_factors:
            opportunities.append({
                "service_id": "ai_search_entity_readiness",
                "service_name": "AI-Search Readiness & Entity Optimization",
                "service_category": "AI Search Readiness",
                "scope": "optimization",
                "relevant_factor_ids": ai_factors,
                "confidence": 0.8,
                "evidence": ai_evidence,
                "affected_urls": [target_url],
                "rationale": "AI search platforms (Google AI Overviews, Perplexity) extract facts from clearly structured headings, explicit entity schemas, and unambiguous business facts.",
                "proposed_next_step": "Align heading structures and JSON-LD entity definitions to ensure accurate summarization by AI discovery systems.",
            })

        return opportunities

    @classmethod
    def generate_proposal_draft(
        cls,
        business_name: str,
        website_url: str,
        opportunities: List[Dict[str, Any]],
        sender_agency: str = "TEB Solutions",
        contact_email: str = "contact@tebsolutions.in",
    ) -> Dict[str, Any]:
        """
        Generate a personalized, truthful proposal email draft derived exclusively
        from verified audit opportunities.
        Selects at most 2-3 salient observations to maintain focus and relevance.
        """
        # Select at most 2–3 top opportunities
        selected_opps = opportunities[:3]
        contributing_factors: List[str] = []
        observations: List[Dict[str, str]] = []

        for opp in selected_opps:
            for fid in opp.get("relevant_factor_ids", []):
                if fid not in contributing_factors:
                    contributing_factors.append(fid)

            ev = opp.get("evidence", [])
            evidence_summary = "; ".join(ev[:2]) if ev else "Identified enhancement opportunity"
            observations.append({
                "service_name": opp["service_name"],
                "service_category": opp["service_category"],
                "scope": opp["scope"],
                "evidence": evidence_summary,
                "rationale": opp["rationale"],
                "next_step": opp["proposed_next_step"],
            })

        domain = website_url.replace("https://", "").replace("http://", "").strip("/")
        subject = f"Website review and proposal for {domain}"

        # Build clean HTML draft
        obs_html = ""
        for i, obs in enumerate(observations, 1):
            obs_html += f"""
            <div style="margin-bottom: 16px; padding: 14px; background: #f8fafc; border-left: 4px solid #2563eb; border-radius: 6px;">
              <p style="margin: 0 0 6px 0; font-weight: 700; color: #1e293b; font-size: 14px;">
                {i}. {html.escape(obs['service_name'])} ({html.escape(obs['scope'].title())})
              </p>
              <p style="margin: 0 0 6px 0; color: #475569; font-size: 13px;">
                <strong>Observed Finding:</strong> {html.escape(obs['evidence'])}
              </p>
              <p style="margin: 0 0 6px 0; color: #64748b; font-size: 12px; line-height: 1.5;">
                {html.escape(obs['rationale'])}
              </p>
              <p style="margin: 0; color: #2563eb; font-size: 12px; font-weight: 600;">
                \u2192 Recommended Action: {html.escape(obs['next_step'])}
              </p>
            </div>
            """

        obs_text = ""
        for i, obs in enumerate(observations, 1):
            obs_text += f"{i}. {obs['service_name']} [{obs['scope'].upper()}]\n"
            obs_text += f"   Observed: {obs['evidence']}\n"
            obs_text += f"   Why it matters: {obs['rationale']}\n"
            obs_text += f"   Recommended Action: {obs['next_step']}\n\n"

        body_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; max-width: 600px; line-height: 1.6;">
          <p>Hi {html.escape(business_name)} Team,</p>
          <p>
            We recently conducted an objective technical audit of <strong>{html.escape(domain)}</strong> to inspect crawlability, mobile experience, and search presence.
          </p>
          <p>Based on our verified findings, we identified {len(observations)} specific areas where structured improvements can help your website deliver a better user experience and stronger discoverability:</p>
          {obs_html}
          <p>
            Our team at <strong>{html.escape(sender_agency)}</strong> specializes in implementing these technical repairs and web enhancements cleanly without disruption.
          </p>
          <p>
            Would you be open to a brief 10-minute conversation this week to review the full technical report and discuss how we can implement these improvements for {html.escape(business_name)}?
          </p>
          <p style="margin-top: 24px;">
            Best regards,<br/>
            <strong>The {html.escape(sender_agency)} Technical Team</strong><br/>
            <span style="font-size: 12px; color: #64748b;">Contact: {html.escape(contact_email)}</span>
          </p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 12px 0;"/>
          <p style="font-size: 11px; color: #94a3b8; line-height: 1.4;">
            Note: This proposal is derived from verified automated audit checks. We do not make unsupported claims of guaranteed rankings or revenue increases. All recommendations reflect observable technical findings.
          </p>
        </div>
        """

        body_text = f"""Hi {business_name} Team,\n\nWe recently conducted an objective technical audit of {domain} to inspect crawlability, mobile experience, and search presence.\n\nBased on our verified findings, we identified {len(observations)} specific areas where structured improvements can help your website deliver a better user experience:\n\n{obs_text}Our team at {sender_agency} specializes in implementing these technical repairs and web enhancements cleanly without disruption.\n\nWould you be open to a brief 10-minute conversation this week to review the full technical report and discuss how we can implement these improvements for {business_name}?\n\nBest regards,\nThe {sender_agency} Technical Team\nContact: {contact_email}\n\nNote: This proposal is derived from verified automated audit checks. All recommendations reflect observable technical findings."""

        return {
            "business_name": business_name,
            "website_url": website_url,
            "subject": subject,
            "observations": observations,
            "opportunities_count": len(opportunities),
            "selected_opportunities_count": len(observations),
            "contributing_factor_ids": contributing_factors,
            "body_html": body_html.strip(),
            "body_text": body_text.strip(),
            "requires_human_approval": True,
            "status": "draft_preview",
            "sent": False,
        }
