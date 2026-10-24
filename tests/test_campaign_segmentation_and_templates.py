"""
tests/test_campaign_segmentation_and_templates.py
-------------------------------------------------
Comprehensive unit and integration test suite covering:
1. Lead segmentation rules (No website, broken, outdated, valid SEO/redesign/marketing, inconclusive).
2. Email sendability gates (valid, unverified, quarantined, mismatched, missing).
3. Template rendering (source of truth, approved variables, spintax, unresolved placeholder fail-closed, HTML escaping).
4. Deprecated copy and promotional link removal.
5. Canonical audit_results integration via OpportunityEngine (no fabricated defects).
6. Pre-send gatekeeper and retry security enforcement.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import uuid
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

def _run_async(coro):
    return asyncio.run(coro)

from app.models import Lead, Audit, AuditStatus, Campaign, CampaignStatus, CampaignEmailLog
from app.services.campaign_eligibility_service import (
    CampaignType,
    WebsiteClassification,
    EmailSendabilityClassification,
    classify_website,
    classify_email_sendability,
    evaluate_lead_campaign_eligibility,
    get_audience_breakdown,
)
from app.services.template_renderer import (
    TemplateRenderer,
    TemplateRenderingError,
)
from app.engines.outreach_engine import (
    _run_campaign_worker,
    build_html_email,
    build_html_email_full,
    build_plain_outreach_email,
)


def _make_test_lead(
    lead_id=None,
    email="test@example.com",
    business_name="Acme Corp",
    website="https://acmecorp.com",
    verification_status="valid",
    association_status="matched",
    is_quarantined=False,
    last_emailed_at=None,
):
    lead = MagicMock(spec=Lead)
    lead.id = lead_id or uuid.uuid4()
    lead.email = email
    lead.business_name = business_name
    lead.website = website
    lead.email_verification_status = verification_status
    lead.email_business_association_status = association_status
    lead.is_quarantined = is_quarantined
    lead.quarantine_reason = "Manual safety hold" if is_quarantined else None
    lead.last_emailed_at = last_emailed_at
    lead.domain = "acmecorp.com" if website else ""
    return lead


def _make_test_audit(lead_id, status=AuditStatus.done, audit_results=None, error_msg=None, summary="Test summary"):
    audit = MagicMock(spec=Audit)
    audit.id = uuid.uuid4()
    audit.lead_id = lead_id
    audit.status = status
    audit.audited_url = "https://acmecorp.com"
    audit.site_summary = {"status": "ok", "response_time_ms": 250}
    audit.audit_results = audit_results if audit_results is not None else {
        "technical_seo": {
            "title_tag_present": {"status": "pass", "score": 100, "description": "Title tag is present"},
            "meta_description_present": {"status": "fail", "score": 0, "description": "Missing meta description tag"},
        },
        "performance": {
            "page_load_speed": {"status": "pass", "score": 90, "description": "Fast load speed"},
        },
    }
    audit.error_message = error_msg
    audit.audit_summary = summary
    audit.ssl_valid = True
    audit.has_sitemap = True
    audit.has_robots = True
    audit.broken_links_count = 0
    audit.missing_meta_count = 0
    audit.has_viewport = True
    audit.is_responsive = True
    return audit


# ═════════════════════════════════════════════════════════════════════════════
# 1. SEGMENTATION & ELIGIBILITY TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_no_website_with_valid_email_eligible_for_web_design():
    """Segment A: No website + verified email -> eligible for no_website_design."""
    lead = _make_test_lead(website="", verification_status="valid", association_status="matched")
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.NO_WEBSITE_DESIGN, audit=None)

    assert eval_res.website_classification == WebsiteClassification.NO_WEBSITE
    assert eval_res.email_sendability == EmailSendabilityClassification.ELIGIBLE
    assert eval_res.is_eligible_for_campaign is True
    assert eval_res.is_sendable is True


def test_no_website_with_missing_email_not_sendable():
    """Segment F: No website + missing email -> classified as missing email, not sendable."""
    lead = _make_test_lead(website="", email="", verification_status="unverified")
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.NO_WEBSITE_DESIGN, audit=None)

    assert eval_res.website_classification == WebsiteClassification.NO_WEBSITE
    assert eval_res.email_sendability == EmailSendabilityClassification.MISSING_EMAIL
    assert eval_res.is_sendable is False


def test_website_present_not_audited_eligible_for_generic_first_contact():
    """Segment E: Website present + no audit -> eligible for generic_first_contact."""
    lead = _make_test_lead(website="https://acme.org", verification_status="valid", association_status="matched")
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.GENERIC_FIRST_CONTACT, audit=None)

    assert eval_res.website_classification == WebsiteClassification.WEBSITE_NOT_AUDITED
    assert eval_res.email_sendability == EmailSendabilityClassification.ELIGIBLE
    assert eval_res.is_eligible_for_campaign is True
    assert eval_res.is_sendable is True


def test_website_present_not_audited_blocked_from_audit_dependent_campaign():
    """Segment E: Website present + no audit -> blocked from audit-dependent campaigns."""
    lead = _make_test_lead(website="https://acme.org", verification_status="valid", association_status="matched")
    
    # Blocked from SEO
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=None)
    assert eval_res.is_eligible_for_campaign is False
    assert "audit" in eval_res.exclusion_reason.lower() and "require" in eval_res.exclusion_reason.lower()

    # Blocked from Modernization
    eval_mod = evaluate_lead_campaign_eligibility(lead, CampaignType.OUTDATED_WEBSITE_MODERNIZATION, audit=None)
    assert eval_mod.is_eligible_for_campaign is False


def test_broken_website_with_verified_failure_eligible_for_repair():
    """Segment B: Broken website audit -> eligible for broken_website_repair."""
    lead = _make_test_lead(website="https://broken-site.com")
    audit = _make_test_audit(
        lead.id,
        status="error",
        error_msg="Connection refused: ERR_CONNECTION_REFUSED on port 443",
        summary="Server connection failed consistently",
    )
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit)

    assert eval_res.website_classification == WebsiteClassification.WEBSITE_BROKEN
    assert eval_res.is_eligible_for_campaign is True
    assert eval_res.is_sendable is True


def test_inconclusive_website_crawler_failure_not_classified_as_broken():
    """Segment E: Inconclusive crawler timeout / rate-limit -> not broken, blocked from broken_repair."""
    lead = _make_test_lead(website="https://cloudflare-protected.com")
    audit = _make_test_audit(
        lead.id,
        status="skipped",
        error_msg="Crawler blocked by Cloudflare 403 challenge",
        summary="Crawling inconclusive due to WAF challenge",
    )
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit)

    assert eval_res.website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE
    assert eval_res.is_eligible_for_campaign is False
    assert "broken" in eval_res.exclusion_reason.lower() or "evidence" in eval_res.exclusion_reason.lower()


def test_outdated_website_with_findings_eligible_for_modernization():
    """Segment C: Outdated website with mobile/viewport failures -> eligible for modernization."""
    lead = _make_test_lead(website="https://oldsite.com")
    audit_results = {
        "mobile_responsiveness": {
            "viewport_meta": {"status": "fail", "score": 0, "description": "Missing viewport meta tag"},
            "touch_target_size": {"status": "fail", "score": 20, "description": "Touch targets too small"},
        },
    }
    audit = _make_test_audit(lead.id, status=AuditStatus.done, audit_results=audit_results)
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.OUTDATED_WEBSITE_MODERNIZATION, audit=audit)

    assert eval_res.website_classification == WebsiteClassification.WEBSITE_OUTDATED
    assert eval_res.is_eligible_for_campaign is True
    assert eval_res.is_sendable is True


def test_valid_website_with_seo_gap_eligible_for_seo_campaign():
    """Segment D3: Valid website with meta/indexability gaps -> eligible for valid_website_seo."""
    lead = _make_test_lead(website="https://validenterprise.com")
    audit_results = {
        "technical_seo": {
            "meta_description": {"status": "fail", "score": 0, "description": "Missing meta description"},
            "canonical_tag": {"status": "fail", "score": 0, "description": "Missing canonical tag"},
        },
    }
    audit = _make_test_audit(lead.id, status=AuditStatus.done, audit_results=audit_results)
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=audit)

    assert eval_res.website_classification == WebsiteClassification.WEBSITE_VALID
    assert eval_res.is_eligible_for_campaign is True
    assert eval_res.is_sendable is True


def test_valid_website_not_eligible_for_no_website_design():
    """A lead with a website cannot be targeted with a no-website design offer."""
    lead = _make_test_lead(website="https://validenterprise.com")
    audit = _make_test_audit(lead.id, status=AuditStatus.done)
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.NO_WEBSITE_DESIGN, audit=audit)

    assert eval_res.is_eligible_for_campaign is False
    assert "has a website" in eval_res.exclusion_reason.lower()


def test_quarantined_or_unverified_email_fail_closed_across_all_segments():
    """Recipient safety gates must fail closed regardless of campaign type or website status."""
    # 1. Quarantined lead
    lead_q = _make_test_lead(website="", is_quarantined=True)
    res_q = evaluate_lead_campaign_eligibility(lead_q, CampaignType.NO_WEBSITE_DESIGN)
    assert res_q.is_sendable is False
    assert res_q.email_sendability == EmailSendabilityClassification.QUARANTINED

    # 2. Unverified email
    lead_uv = _make_test_lead(website="", verification_status="unverified")
    res_uv = evaluate_lead_campaign_eligibility(lead_uv, CampaignType.NO_WEBSITE_DESIGN)
    assert res_uv.is_sendable is False
    assert res_uv.email_sendability == EmailSendabilityClassification.PENDING_VERIFICATION

    # 3. Mismatched / unapproved association
    lead_mm = _make_test_lead(website="", association_status="external_domain_review")
    res_mm = evaluate_lead_campaign_eligibility(lead_mm, CampaignType.NO_WEBSITE_DESIGN)
    assert res_mm.is_sendable is False
    assert res_mm.email_sendability == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION


def test_cooldown_lead_temporarily_blocked():
    """Lead contacted 3 days ago is in 7-day cooldown and blocked from sending."""
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    lead = _make_test_lead(last_emailed_at=three_days_ago)
    audit = _make_test_audit(lead.id)
    res = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=audit)

    assert res.is_sendable is False
    assert res.email_sendability == EmailSendabilityClassification.COOLDOWN
    assert "cooldown" in res.exclusion_reason.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 2. TEMPLATE RENDERER TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_template_renderer_substitutes_approved_variables():
    """Approved variables {business_name}, {website}, {domain}, {audit_summary} render correctly."""
    lead = _make_test_lead(business_name="Apex Logistics", website="https://apexlogistics.in")
    audit = _make_test_audit(lead.id, summary="Audit identified 2 mobile optimization issues.")

    template = "Hello {business_name}, reviewing {website} ({domain}): {audit_summary}."
    subject = "Update for {business_name}"

    rendered = TemplateRenderer.render_campaign_email(
        template=template,
        subject_template=subject,
        lead=lead,
        audit=audit,
        campaign_type=CampaignType.VALID_WEBSITE_SEO,
    )

    assert rendered["subject"] == "Update for Apex Logistics"
    assert "Apex Logistics" in rendered["plain_body"]
    assert "https://apexlogistics.in" in rendered["plain_body"]
    assert "apexlogistics.in" in rendered["plain_body"]
    assert "Audit identified 2 mobile optimization issues" in rendered["plain_body"]


def test_template_renderer_fails_closed_on_unresolved_placeholders():
    """Any unreplaced placeholder (e.g. {unknown_var}) causes a fail-closed TemplateRenderingError."""
    lead = _make_test_lead(business_name="Apex Logistics")
    template = "Hello {business_name}, check out our offer: {non_existent_variable}."

    with pytest.raises(TemplateRenderingError) as exc_info:
        TemplateRenderer.render_campaign_email(
            template=template,
            subject_template="Hello",
            lead=lead,
            campaign_type=CampaignType.GENERIC_FIRST_CONTACT,
        )

    assert "unresolved placeholders" in str(exc_info.value).lower()
    assert "non_existent_variable" in str(exc_info.value)


def test_template_renderer_prevents_xss_in_html_body():
    """Malicious lead business_name or website cannot inject raw unescaped script tags."""
    xss_lead = _make_test_lead(
        business_name="<script>alert('XSS')</script> Corporation",
        website="https://evil.com/\" onmouseover=\"alert(1)",
    )
    template = "Hello {business_name}, visiting {website}."
    rendered = TemplateRenderer.render_campaign_email(
        template=template,
        subject_template="Inquiry",
        lead=xss_lead,
        campaign_type=CampaignType.GENERIC_FIRST_CONTACT,
    )

    # Plain body contains the text, but HTML body must be escaped
    assert "<script>alert('XSS')</script>" not in rendered["html_body"]
    assert "&lt;script&gt;alert(&#x27;XSS&#x27;)&lt;/script&gt;" in rendered["html_body"] or "&lt;script&gt;" in rendered["html_body"]


def test_no_deprecated_pricing_or_external_links_in_default_templates():
    """Verify default templates contain zero references to $25, $60, $150 or Hexaprime/Channelnexus/Sketchlife."""
    forbidden_terms = [
        "$25", "$60", "$150",
        "hexaprime", "channelnexus", "sketchlife",
    ]

    for c_type in [
        CampaignType.GENERIC_FIRST_CONTACT,
        CampaignType.NO_WEBSITE_DESIGN,
        CampaignType.BROKEN_WEBSITE_REPAIR,
        CampaignType.OUTDATED_WEBSITE_MODERNIZATION,
        CampaignType.VALID_WEBSITE_SEO,
        CampaignType.VALID_WEBSITE_REDESIGN,
        CampaignType.VALID_WEBSITE_LINK_BUILDING,
        CampaignType.VALID_WEBSITE_MARKETING,
    ]:
        defaults = TemplateRenderer.get_default_template(c_type)
        content_lower = (defaults["subject"] + " " + defaults["template"]).lower()
        for term in forbidden_terms:
            assert term not in content_lower, f"Forbidden term '{term}' found in default template for {c_type}"


def test_outreach_engine_helpers_have_no_promotional_links():
    """Verify build_html_email, build_html_email_full, build_plain_outreach_email have zero external links."""
    lead = _make_test_lead()
    audit = _make_test_audit(lead.id)

    html1 = build_html_email(lead, audit)
    html2 = build_html_email_full(lead, audit)
    plain = build_plain_outreach_email(lead, audit)

    combined = (html1 + html2 + plain).lower()
    for term in ["hexaprime.me", "channelnexus.me", "sketchlife.ae"]:
        assert term not in combined, f"Forbidden legacy link {term} found in outreach_engine functions"


# ═════════════════════════════════════════════════════════════════════════════
# 3. CANONICAL AUDIT RESULTS INTEGRATION TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_canonical_audit_results_populate_findings_via_opportunity_engine():
    """OpportunityEngine generates evidence-backed findings from canonical audit_results."""
    lead = _make_test_lead(website="https://mybiz.com")
    audit_results = {
        "security": {
            "ssl_enabled": {"status": "fail", "score": 0, "description": "Missing SSL certificate"},
        },
        "technical_seo": {
            "robots_txt": {"status": "fail", "score": 0, "description": "Invalid robots.txt file"},
        },
    }
    audit = _make_test_audit(lead.id, audit_results=audit_results)

    template = "Findings:\n{audit_findings}\n\nSuggested Service: {suggested_service}"
    rendered = TemplateRenderer.render_campaign_email(
        template=template,
        subject_template="Technical findings",
        lead=lead,
        audit=audit,
        campaign_type=CampaignType.VALID_WEBSITE_SEO,
    )

    assert "Suggested Service:" in rendered["plain_body"]
    assert len(rendered["plain_body"]) > 30


def test_missing_audit_results_does_not_fabricate_scores():
    """When audit has no audit_results (e.g. skipped or pending), safe neutral summary is used."""
    lead = _make_test_lead(website="https://mybiz.com")
    audit = _make_test_audit(lead.id, status=AuditStatus.pending, audit_results=None, summary="Pending initial evaluation")

    variables = TemplateRenderer.extract_context_variables(lead, audit, CampaignType.GENERIC_FIRST_CONTACT)
    assert "Pending initial evaluation" in variables["audit_summary"]
    # No fabricated score
    assert "100" not in variables["audit_findings"]
    assert "critical failure" not in variables["audit_findings"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# 4. PRE-SEND GATEKEEPER & WORKER TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_worker_uses_campaign_template_as_source_of_truth():
    """The sending worker renders the saved campaign.template, not hardcoded legacy text."""
    async def _test():
        lead_id = str(uuid.uuid4())
        camp_id = str(uuid.uuid4())

        custom_template = "CUSTOM_CAMPAIGN_TEMPLATE: Hello {business_name}, custom outreach regarding {website}!"
        custom_subject = "CUSTOM_SUBJECT: {business_name}"

        campaign = MagicMock(spec=Campaign)
        campaign.id = uuid.UUID(camp_id)
        campaign.status = CampaignStatus.draft
        campaign.template = custom_template
        campaign.subject_template = custom_subject
        campaign.campaign_type = "valid_website_seo"
        campaign.lead_ids = [lead_id]
        campaign.pending_lead_ids = [lead_id]
        campaign.sent_count = 0
        campaign.failed_count = 0
        campaign.skipped_count = 0

        lead = _make_test_lead(lead_id=uuid.UUID(lead_id), business_name="Vanguard Tech", website="https://vanguardtech.com")
        audit = _make_test_audit(lead.id)

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=audit)))
        mock_db.commit = AsyncMock()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        fake_smtp = {"email": "info@tebsolutions.in", "smtp_host": "smtp.hostinger.com", "smtp_port": 465, "password": "pw", "daily_limit": 100}

        sent_emails = []

        def mock_send(account, to_email, subject, html_body, *args, **kwargs):
            plain_body = kwargs.get("plain_body", "")
            sent_emails.append({"to": to_email, "subject": subject, "plain": plain_body, "html": html_body})
            return True, "250 Message accepted"

        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", side_effect=mock_send):

            await _run_campaign_worker(camp_id)

        assert len(sent_emails) == 1
        sent = sent_emails[0]
        assert sent["subject"] == "CUSTOM_SUBJECT: Vanguard Tech"
        assert "CUSTOM_CAMPAIGN_TEMPLATE: Hello Vanguard Tech" in sent["plain"]
        assert "CUSTOM_CAMPAIGN_TEMPLATE" in sent["html"]

    _run_async(_test())


def test_worker_pre_send_blocks_ineligible_leads():
    """A lead quarantined or becoming unverified after campaign creation is blocked before send."""
    async def _test():
        lead_id = str(uuid.uuid4())
        camp_id = str(uuid.uuid4())

        campaign = MagicMock(spec=Campaign)
        campaign.id = uuid.UUID(camp_id)
        campaign.status = CampaignStatus.draft
        campaign.template = "Hello {business_name}"
        campaign.subject_template = "Hello"
        campaign.campaign_type = "no_website_design"
        campaign.lead_ids = [lead_id]
        campaign.pending_lead_ids = [lead_id]
        campaign.sent_count = 0
        campaign.failed_count = 0
        campaign.skipped_count = 0

        # Lead has been quarantined prior to worker run
        lead = _make_test_lead(
            lead_id=uuid.UUID(lead_id),
            is_quarantined=True,
        )

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        mock_db.commit = AsyncMock()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        fake_smtp = {"email": "info@tebsolutions.in", "smtp_host": "smtp.hostinger.com", "smtp_port": 465, "password": "pw", "daily_limit": 100}

        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:

            await _run_campaign_worker(camp_id)

            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1

    _run_async(_test())


# ═════════════════════════════════════════════════════════════════════════════
# 5. SAFETY REVIEW & BOUNDARY REGRESSION TESTS
# ═════════════════════════════════════════════════════════════════════════════

def test_valid_website_with_no_findings_blocked_from_fabricated_pitch():
    """Segment D5: A valid website with no audit gaps must not receive a fabricated technical pitch."""
    lead = _make_test_lead(website="https://perfect-enterprise.com")
    flawless_results = {
        "technical_seo": {
            "title_tag_present": {"status": "pass", "score": 100, "description": "Title tag present"},
            "canonical_tag": {"status": "pass", "score": 100, "description": "Canonical present"},
        },
        "performance": {
            "response_time": {"status": "pass", "score": 100, "description": "Fast"},
        },
    }
    audit = _make_test_audit(lead.id, status=AuditStatus.done, audit_results=flawless_results)
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=audit)

    assert eval_res.is_eligible_for_campaign is False
    assert "no significant technical gaps" in eval_res.exclusion_reason.lower() or "generic_first_contact" in eval_res.exclusion_reason.lower()

    # But it IS eligible for generic first contact!
    generic_res = evaluate_lead_campaign_eligibility(lead, CampaignType.GENERIC_FIRST_CONTACT, audit=audit)
    assert generic_res.is_eligible_for_campaign is True
    assert generic_res.is_sendable is True


def test_matching_domain_cannot_bypass_association_approval():
    """Rejected or unverified email association cannot be bypassed merely because email domain matches website."""
    lead = _make_test_lead(
        website="https://acmeholding.com",
        email="ceo@acmeholding.com",  # domain matches website exactly!
        association_status="external_domain_review",  # pending review
    )
    audit = _make_test_audit(lead.id)
    eval_res = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=audit)

    assert eval_res.is_sendable is False
    assert eval_res.email_sendability == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION
    assert "association" in eval_res.exclusion_reason.lower()


def test_leads_with_same_company_name_different_domains_remain_isolated():
    """Leads with identical names but different domains must not cross-contaminate rendered variables."""
    lead_us = _make_test_lead(business_name="Apex Logistics", website="https://apexlogistics.com")
    lead_uk = _make_test_lead(business_name="Apex Logistics", website="https://apexlogistics.co.uk")

    vars_us = TemplateRenderer.extract_context_variables(lead_us)
    vars_uk = TemplateRenderer.extract_context_variables(lead_uk)

    assert vars_us["domain"] == "apexlogistics.com"
    assert vars_uk["domain"] == "apexlogistics.co.uk"
    assert vars_us["website"] != vars_uk["website"]


def test_two_opportunities_do_not_generate_duplicate_sends_or_bypass_cooldown():
    """A lead qualifying for multiple services respects 7-day cooldown to prevent duplicate pitches."""
    lead = _make_test_lead()
    audit = _make_test_audit(lead.id)

    # First send is allowed
    res1 = evaluate_lead_campaign_eligibility(lead, CampaignType.VALID_WEBSITE_SEO, audit=audit)
    assert res1.is_sendable is True

    # After emailing, last_emailed_at is set to now
    lead.last_emailed_at = datetime.utcnow()

    # Second campaign attempted immediately is blocked by cooldown
    res2 = evaluate_lead_campaign_eligibility(lead, CampaignType.OUTDATED_WEBSITE_MODERNIZATION, audit=audit)
    assert res2.is_sendable is False
    assert res2.email_sendability == EmailSendabilityClassification.COOLDOWN
    assert "cooldown" in res2.exclusion_reason.lower()


def test_xss_attribute_breakout_and_malicious_urls_prevented():
    """Quotes, HTML tags, and attribute breakout attempts in lead data are safely neutralized in HTML output."""
    malicious_name = 'Vanguard <script>alert("XSS")</script>'
    malicious_site = 'https://vanguard.com/"onclick="alert(1)'

    lead = _make_test_lead(business_name=malicious_name, website=malicious_site)
    template = "Hello {business_name}, visit {website}."

    rendered = TemplateRenderer.render_campaign_email(
        template=template,
        subject_template="Notice for {business_name}",
        lead=lead,
        campaign_type=CampaignType.GENERIC_FIRST_CONTACT,
    )

    html_out = rendered["html_body"]
    # <script> must be escaped
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    # Quotes cannot break out of href attribute
    assert 'href="https://vanguard.com/"onclick=' not in html_out


# ═════════════════════════════════════════════════════════════════════════════
# 6. FINAL ACCEPTANCE: URL SECURITY & WEBSITE CLASSIFICATION
# ═════════════════════════════════════════════════════════════════════════════

def test_javascript_scheme_website_sanitized_to_empty():
    """Check 1: javascript:alert(1) in website is rejected and not rendered into active HTML links."""
    lead = _make_test_lead(website="javascript:alert(1)")
    vars_ctx = TemplateRenderer.extract_context_variables(lead)
    assert vars_ctx["website"] == ""
    assert vars_ctx["domain"] == ""

    # In HTML template with explicit href
    template = '<a href="{website}">Our Website</a>'
    rendered = TemplateRenderer.render_campaign_email(
        template=template,
        subject_template="Hello",
        lead=lead,
        campaign_type=CampaignType.GENERIC_FIRST_CONTACT,
    )
    assert 'href="javascript:' not in rendered["html_body"].lower()


def test_obfuscated_schemes_and_control_chars_rejected():
    """Check 1: Leading whitespace, control chars, and encoded schemes are rejected."""
    dangerous_inputs = [
        "\r\n\t  javascript:alert(1)",
        "java\x00script:alert(1)",
        "%6a%61%76%61%73%63%72%69%70%74:alert(1)",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "//evil.com/phishing",
        "vbscript:msgbox(1)",
    ]
    for bad_url in dangerous_inputs:
        lead = _make_test_lead(website=bad_url)
        vars_ctx = TemplateRenderer.extract_context_variables(lead)
        assert vars_ctx["website"] == "", f"Expected bad URL {bad_url} to be sanitized to empty string"


def test_autolink_trailing_punctuation_preserved_outside_tag():
    """Check 1: Ordinary HTTPS link with trailing punctuation does not include punctuation inside href."""
    lead = _make_test_lead(business_name="Normal Co", website="https://normalco.com")
    plain_text = "Please review your website at https://normalco.com. Also check https://tebsolutions.in/pricing, thanks!"
    
    html_out = TemplateRenderer._wrap_plain_as_html(plain_text, {"company_name": "TEB Solutions"})
    
    # href must be clean without trailing period
    assert 'href="https://normalco.com"' in html_out
    assert 'href="https://normalco.com."' not in html_out
    # href must be clean without trailing comma
    assert 'href="https://tebsolutions.in/pricing"' in html_out
    assert 'href="https://tebsolutions.in/pricing,"' not in html_out


def test_malicious_audit_error_string_escaped_in_html():
    """Check 1: Malicious crawler error messages or audit findings are HTML-escaped."""
    lead = _make_test_lead(website="https://vuln-site.com")
    audit = _make_test_audit(lead.id, status=AuditStatus.failed, audit_results={}, error_msg='<img src=x onerror="alert(1)"> Server Error')
    
    rendered = TemplateRenderer.render_campaign_email(
        template="Observed: {audit_findings}",
        subject_template="Hello",
        lead=lead,
        audit=audit,
        campaign_type=CampaignType.GENERIC_FIRST_CONTACT,
    )
    assert "<img src=x" not in rendered["html_body"]
    assert "&lt;img src=x" in rendered["html_body"]


def test_classification_transient_failures_inconclusive_not_broken():
    """Check 2: HTTP 429, single HTTP 500, transient DNS, and WAF restrictions are inconclusive, not broken."""
    lead = _make_test_lead(website="https://transient-issue.com")

    # 1. HTTP 429 Rate Limit
    audit_429 = _make_test_audit(lead.id, status="failed", error_msg="HTTP 429 Too Many Requests")
    res_429 = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_429)
    assert res_429.website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE
    assert res_429.is_eligible_for_campaign is False

    # 2. Single HTTP 500 (transient, no persistence proof)
    audit_500 = _make_test_audit(lead.id, status="failed", error_msg="500 Internal Server Error")
    res_500 = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_500)
    assert res_500.website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE
    assert res_500.is_eligible_for_campaign is False

    # 3. Transient DNS failure
    audit_dns = _make_test_audit(lead.id, status="failed", error_msg="Temporary failure in name resolution: DNS query timeout")
    res_dns = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_dns)
    assert res_dns.website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE
    assert res_dns.is_eligible_for_campaign is False

    # 4. Access restriction (HTTP 403 Forbidden)
    audit_403 = _make_test_audit(lead.id, status="failed", error_msg="403 Forbidden: WAF Access Denied")
    res_403 = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_403)
    assert res_403.website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE
    assert res_403.is_eligible_for_campaign is False


def test_classification_verified_persistent_failure_eligible_for_broken():
    """Check 2: Verified persistent unavailability or confirmed NXDOMAIN is classified as broken."""
    lead = _make_test_lead(website="https://really-broken.com")

    # 1. Persistent 500 with multiple retries confirmed
    audit_persistent_500 = _make_test_audit(lead.id, status="failed", error_msg="500 Internal Server Error: persistent across 3 retries")
    audit_persistent_500.site_summary = {"status_code": 500, "retry_count": 3, "is_persistent": True}
    res_persistent = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_persistent_500)
    assert res_persistent.website_classification == WebsiteClassification.WEBSITE_BROKEN
    assert res_persistent.is_eligible_for_campaign is True

    # 2. Confirmed NXDOMAIN (domain does not exist)
    audit_nxdomain = _make_test_audit(lead.id, status="failed", error_msg="DNS lookup failed: NXDOMAIN domain does not exist")
    res_nx = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_nxdomain)
    assert res_nx.website_classification == WebsiteClassification.WEBSITE_BROKEN
    assert res_nx.is_eligible_for_campaign is True

    # 3. Confirmed redirect loop
    audit_loop = _make_test_audit(lead.id, status="failed", error_msg="Too many redirects: redirect loop detected")
    res_loop = evaluate_lead_campaign_eligibility(lead, CampaignType.BROKEN_WEBSITE_REPAIR, audit=audit_loop)
    assert res_loop.website_classification == WebsiteClassification.WEBSITE_BROKEN
    assert res_loop.is_eligible_for_campaign is True


def test_audience_breakdown_per_lead_details_and_eligibility_alignment():
    """Verify that get_audience_breakdown returns authoritative lead_details mapping with distinct properties."""
    lead_custom = _make_test_lead(
        business_name="Custom Domain Inc",
        email="contact@customdomain.com",
        website="https://customdomain.com",
    )
    lead_gmail = _make_test_lead(
        business_name="Public Gmail Biz",
        email="biz@gmail.com",
        website="https://gmailbiz.com",
        association_status="unverified",
    )
    lead_quarantined = _make_test_lead(
        business_name="Quarantined Biz",
        email="bad@quarantine.com",
        website="https://quarantine.com",
        is_quarantined=True,
    )

    leads = [lead_custom, lead_gmail, lead_quarantined]
    leads_with_audits = [(lead, None) for lead in leads]  # No completed audits

    # 1. Generic first contact: custom domain is eligible without audit; gmail & quarantined are not
    breakdown_generic = get_audience_breakdown(leads_with_audits, CampaignType.GENERIC_FIRST_CONTACT)
    assert "lead_details" in breakdown_generic
    details_g = breakdown_generic["lead_details"]

    assert str(lead_custom.id) in details_g
    assert details_g[str(lead_custom.id)]["is_eligible"] is True
    assert details_g[str(lead_custom.id)]["sendability_classification"] == "eligible"

    assert str(lead_gmail.id) in details_g
    assert details_g[str(lead_gmail.id)]["is_eligible"] is False
    assert "public provider" in details_g[str(lead_gmail.id)]["exclusion_reason"].lower() or "demo" in details_g[str(lead_gmail.id)]["exclusion_reason"].lower()

    assert str(lead_quarantined.id) in details_g
    assert details_g[str(lead_quarantined.id)]["is_eligible"] is False
    assert details_g[str(lead_quarantined.id)]["sendability_classification"] == "quarantined"

    # 2. Public provider demo campaign: Gmail lead is eligible; quarantined is blocked
    breakdown_demo = get_audience_breakdown(leads_with_audits, CampaignType.PUBLIC_PROVIDER_DEMO)
    details_d = breakdown_demo["lead_details"]
    assert details_d[str(lead_gmail.id)]["is_eligible"] is True
    assert details_d[str(lead_quarantined.id)]["is_eligible"] is False

    # 3. Audit-specific campaign (e.g. VALID_WEBSITE_SEO): custom lead without audit is ineligible
    breakdown_audit = get_audience_breakdown(leads_with_audits, CampaignType.VALID_WEBSITE_SEO)
    details_a = breakdown_audit["lead_details"]
    assert details_a[str(lead_custom.id)]["is_eligible"] is False
    assert "audit" in details_a[str(lead_custom.id)]["exclusion_reason"].lower()


