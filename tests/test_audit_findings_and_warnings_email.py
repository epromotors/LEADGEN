"""Comprehensive tests for Audit Findings and Recommendations in Outreach Emails.

Covers all 13 scenarios required by LEADGEN Email Content Enhancement:
1. Email content with critical issues only.
2. Email content with warnings only.
3. Email content containing both severities, in the correct order.
4. Multiple findings within one category.
5. Multiple categories in the same audit.
6. Recommendations correctly matched to their findings.
7. Every supported category receives appropriate content when applicable.
8. Missing, incomplete, and unavailable audit evidence.
9. No fabricated findings when a category has no issues.
10. HTML email and plain-text parity.
11. Proposal preview and edit workflows retain findings and recommendations.
12. Existing template and campaign compatibility.
13. Findings from unrelated leads or audits are never mixed together.

Zero real emails dispatched; zero live external queues accessed.
"""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.engines.opportunity_engine import OpportunityEngine
from app.services.audit_email_service import AuditEmailService, AuditEmailGenerationError
from app.services.proposal_service import ProposalService
from app.services.template_renderer import TemplateRenderer
from app.services.campaign_eligibility_service import CampaignType
from app.models import Audit, AuditStatus, Lead


def _make_mock_lead(business_name="Acme Corp", website="https://acmecorp.example", lead_id=None):
    lead = MagicMock(spec=Lead)
    lead.id = lead_id or uuid.uuid4()
    lead.business_name = business_name
    lead.website = website
    lead.email = f"contact@{website.replace('https://', '').replace('http://', '').rstrip('/')}"
    lead.email_verification_status = "valid"
    lead.email_business_association_status = "matched"
    lead.is_quarantined = False
    lead.quarantine_reason = None
    lead.last_emailed_at = None
    return lead


def _make_mock_audit(lead, audit_results=None, status=AuditStatus.done, site_summary=None, error_msg=None, audit_id=None):
    audit = MagicMock(spec=Audit)
    audit.id = audit_id or uuid.uuid4()
    audit.lead_id = lead.id
    audit.status = status
    audit.audited_url = lead.website
    audit.updated_at = datetime(2026, 10, 24, 0, 0, 0)
    audit.site_summary = site_summary or {"status": "ok", "response_time_ms": 250}
    audit.error_message = error_msg
    audit.audit_results = audit_results
    return audit


# ═════════════════════════════════════════════════════════════════════════════
# 1. Email content with critical issues only
# ═════════════════════════════════════════════════════════════════════════════
def test_01_critical_issues_only():
    """When only critical failures exist, Critical Issues section is populated,
    and Warnings cleanly states no warnings were identified."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {
            "sitemap": {"status": "FAIL", "message": "No XML sitemap detected"},
            "ssl": {"status": "FAIL", "message": "SSL certificate invalid or missing"},
        },
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)

    body_text = email["body_text"]
    body_html = email["body_html"]

    # Critical issues present
    assert "Critical Issues" in body_text
    assert "Critical Issues" in body_html
    assert "Sitemap" in body_text or "sitemap" in body_text
    assert "SSL" in body_text or "ssl" in body_text

    # Warnings section clearly notes no warnings
    assert "No warnings were identified in this audit" in body_text
    assert "No warnings were identified in this audit" in body_html

    # Actionable recommendations present
    assert "Recommended Action:" in body_text or "Recommended:" in body_text
    assert "Recommendations and Next Steps" in body_text
    assert "Recommendations and Next Steps" in body_html


# ═════════════════════════════════════════════════════════════════════════════
# 2. Email content with warnings only
# ═════════════════════════════════════════════════════════════════════════════
def test_02_warnings_only_no_fabricated_critical():
    """When only warnings exist, Warnings section is rendered with recommendations,
    and no critical issues are fabricated."""
    lead = _make_mock_lead()
    audit_results = {
        "performance": {"gzip_compression": {"status": "WARN", "message": "Text compression not enabled"}},
        "images": {"webp": {"status": "WARN", "message": "Legacy JPEG/PNG images not using WebP"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)

    body_text = email["body_text"]
    body_html = email["body_html"]

    # Warnings present with actionable guidance
    assert "Warnings" in body_text
    assert "Warnings" in body_html
    assert "compression" in body_text.lower() or "gzip" in body_text.lower()
    assert "webp" in body_text.lower() or "image" in body_text.lower()

    # Zero fabricated critical issues
    assert "Critical Issues" not in body_text
    assert "Critical Issues" not in body_html

    # Actionable recommendations present
    assert "Recommendations and Next Steps" in body_text
    assert "Recommendations and Next Steps" in body_html


# ═════════════════════════════════════════════════════════════════════════════
# 3. Email content containing both severities in correct order
# ═════════════════════════════════════════════════════════════════════════════
def test_03_both_severities_correct_order():
    """When both exist, Critical Issues appears first, Warnings second,
    followed by prioritized Recommendations and Next Steps."""
    lead = _make_mock_lead()
    audit_results = {
        "onpage": {
            "h1": {"status": "FAIL", "message": "Missing primary H1 tag"},
            "meta_description": {"status": "WARN", "message": "Meta description missing or non-descriptive"},
        },
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)

    body_text = email["body_text"]
    body_html = email["body_html"]

    # Order check in plain text
    crit_pos = body_text.find("Critical Issues")
    warn_pos = body_text.find("Warnings")
    rec_pos = body_text.find("Recommendations and Next Steps")

    assert crit_pos != -1, "Critical Issues must be present"
    assert warn_pos != -1, "Warnings must be present"
    assert rec_pos != -1, "Recommendations and Next Steps must be present"
    assert crit_pos < warn_pos < rec_pos, "Expected order: Critical Issues < Warnings < Recommendations and Next Steps"

    # Order check in HTML
    h_crit_pos = body_html.find("Critical Issues")
    h_warn_pos = body_html.find("Warnings")
    h_rec_pos = body_html.find("Recommendations and Next Steps")

    assert h_crit_pos != -1
    assert h_warn_pos != -1
    assert h_rec_pos != -1
    assert h_crit_pos < h_warn_pos < h_rec_pos


# ═════════════════════════════════════════════════════════════════════════════
# 4. Multiple findings within one category
# ═════════════════════════════════════════════════════════════════════════════
def test_04_multiple_findings_within_one_category():
    """Multiple findings within Technical SEO are listed individually without collapsing."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {
            "ssl": {"status": "FAIL", "message": "Missing SSL certificate"},
            "robots": {"status": "FAIL", "message": "robots.txt missing or blocking crawler"},
            "canonical": {"status": "WARN", "message": "Canonical tag missing on homepage"},
        }
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)
    body_text = email["body_text"]

    # All findings appear in plain text
    assert "SSL" in body_text or "ssl" in body_text
    assert "robots" in body_text.lower() or "crawler" in body_text.lower()
    assert "Canonical" in body_text or "canonical" in body_text


# ═════════════════════════════════════════════════════════════════════════════
# 5. Multiple categories in the same audit
# ═════════════════════════════════════════════════════════════════════════════
def test_05_multiple_categories_in_same_audit():
    """Findings across distinct technical categories are properly captured."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "No valid SSL"}},
        "ux": {"cta": {"status": "WARN", "message": "Call to action button is not prominent"}},
        "onpage": {"h1": {"status": "FAIL", "message": "Primary H1 heading missing"}},
        "performance": {"gzip_compression": {"status": "WARN", "message": "Compression not enabled"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)
    categories = {o["service_category"] for o in email["observations"]}

    assert len(categories) >= 3, f"Expected findings across >= 3 categories, got {categories}"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Recommendations correctly matched to their findings
# ═════════════════════════════════════════════════════════════════════════════
def test_06_recommendations_matched_to_findings():
    """Specific findings receive appropriately matched remediation guidance."""
    lead = _make_mock_lead()
    audit_results = {
        "onpage": {"title": {"status": "FAIL", "message": "Missing page title"}},
        "images": {"webp": {"status": "WARN", "message": "Images not using modern WebP format"}},
        "onpage": {"schema": {"status": "WARN", "message": "Missing structured data"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)
    recs = [o["next_step"] for o in email["observations"]]
    rec_text = " ".join(recs).lower()

    # Title or Schema recommendation
    assert "schema" in rec_text or "title" in rec_text or "json-ld" in rec_text


# ═════════════════════════════════════════════════════════════════════════════
# 7. Every supported category receives appropriate content
# ═════════════════════════════════════════════════════════════════════════════
def test_07_all_supported_canonical_categories():
    """Verify each canonical category generates verified findings and actionable recommendations."""
    categories_to_test = [
        # Technical SEO & Infrastructure
        ("technical", "ssl", "FAIL", "Certificate expired", "ssl"),
        # XML Sitemap & Indexing Architecture
        ("technical", "sitemap", "FAIL", "No XML sitemap", "sitemap"),
        # On-page SEO & Content
        ("onpage", "h1", "FAIL", "Primary H1 tag missing", "h1"),
        # Performance & Speed
        ("performance", "gzip_compression", "WARN", "Gzip compression disabled", "compression"),
        # Web Design & UX
        ("ux", "cta", "WARN", "CTA button missing", "action"),
        # Structured Data & Local SEO
        ("onpage", "schema", "WARN", "Schema markup missing", "schema"),
        # Mobile Usability
        ("technical", "mobile", "FAIL", "Viewport meta tag missing", "mobile"),
        # Broken Links & Crawlability
        ("links", "broken_links", "FAIL", "4 internal dead links detected", "broken"),
    ]

    for cat_key, factor_key, status, msg, keyword in categories_to_test:
        lead = _make_mock_lead(business_name=f"Test {factor_key}")
        audit_results = {cat_key: {factor_key: {"status": status, "message": msg}}}
        audit = _make_mock_audit(lead, audit_results=audit_results)

        email = AuditEmailService.generate(lead=lead, audit=audit)
        assert len(email["observations"]) > 0, f"Expected opportunity for {factor_key}"
        obs = email["observations"][0]
        assert obs["next_step"], f"Missing next_step recommendation for {factor_key}"


def test_07b_ai_search_readiness_category():
    """Verify AI search readiness category integrates seamlessly."""
    lead = _make_mock_lead(business_name="AI Search Client")
    audit_results = {
        "onpage": {"h1": {"status": "FAIL", "message": "Primary H1 heading missing"}},
    }
    ai_obs = [{
        "query": "best local services in area",
        "engine": "chatgpt",
        "position": "not_cited",
        "note": "Domain is not referenced in local recommendation clusters."
    }]
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit, ai_observations=ai_obs)
    assert any("ai" in o["service_name"].lower() for o in email["observations"])


# ═════════════════════════════════════════════════════════════════════════════
# 8. Missing, incomplete, and unavailable audit evidence
# ═════════════════════════════════════════════════════════════════════════════
def test_08_missing_or_incomplete_audit_evidence_fails_closed():
    """Incomplete, failed, or missing audits fail closed and do not fabricate clean or false failures."""
    lead = _make_mock_lead()

    # None audit
    with pytest.raises(AuditEmailGenerationError) as exc_none:
        AuditEmailService.generate(lead=lead, audit=None)
    assert "completed audit is required" in str(exc_none.value).lower()

    # Pending / Running audit
    audit_pending = _make_mock_audit(lead, status=AuditStatus.running)
    with pytest.raises(AuditEmailGenerationError) as exc_pending:
        AuditEmailService.generate(lead=lead, audit=audit_pending)
    assert "incomplete" in str(exc_pending.value).lower()

    # Failed audit
    audit_failed = _make_mock_audit(lead, status=AuditStatus.failed, error_msg="DNS lookup failed")
    with pytest.raises(AuditEmailGenerationError) as exc_err:
        AuditEmailService.generate(lead=lead, audit=audit_failed)
    assert "failed" in str(exc_err.value).lower() or "incomplete" in str(exc_err.value).lower()

    # Empty audit results
    audit_empty = _make_mock_audit(lead, status=AuditStatus.done, audit_results={})
    with pytest.raises(AuditEmailGenerationError) as exc_empty:
        AuditEmailService.generate(lead=lead, audit=audit_empty)
    assert "unavailable" in str(exc_empty.value).lower()


# ═════════════════════════════════════════════════════════════════════════════
# 9. No fabricated findings when a category has no issues
# ═════════════════════════════════════════════════════════════════════════════
def test_09_no_fabricated_findings_on_clean_audit():
    """A clean audit without findings raises error in strict mode and renders clean baseline in baseline mode."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {"sitemap": {"status": "PASS"}, "robots": {"status": "PASS"}, "ssl": {"status": "PASS"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    # In strict mode (default), clean audit blocks outreach pitch fabrication
    with pytest.raises(AuditEmailGenerationError):
        AuditEmailService.generate(lead=lead, audit=audit, allow_clean_baseline=False)

    # In baseline mode, clean audit produces reassuring baseline without fabricated issues
    email = AuditEmailService.generate(lead=lead, audit=audit, allow_clean_baseline=True)
    body_text = email["body_text"]

    assert "core technical foundations are operational" in body_text
    assert "No warnings were identified in this audit" in body_text
    assert "Baseline Foundation Check" in body_text


# ═════════════════════════════════════════════════════════════════════════════
# 10. HTML email and plain-text parity
# ═════════════════════════════════════════════════════════════════════════════
def test_10_html_and_plain_text_parity_and_escaping():
    """Plain-text and HTML versions contain materially equivalent content, and HTML escapes malicious characters."""
    import html as html_lib
    lead = _make_mock_lead(business_name="<script>alert(1)</script> Safe Cleaners")
    audit_results = {
        "technical": {"sitemap": {"status": "FAIL", "message": "Missing sitemap"}},
        "performance": {"gzip_compression": {"status": "WARN", "message": "Gzip compression missing"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    email = AuditEmailService.generate(lead=lead, audit=audit)
    body_text = email["body_text"]
    body_html = email["body_html"]

    # Security check: script tag is escaped in HTML
    assert "<script>alert(1)</script>" not in body_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body_html

    # Content parity check
    assert "Critical Issues" in body_text and "Critical Issues" in body_html
    assert "Warnings" in body_text and "Warnings" in body_html
    assert "Recommendations and Next Steps" in body_text and "Recommendations and Next Steps" in body_html

    for obs in email["observations"]:
        if obs.get("scope") != "monitoring":
            assert html_lib.escape(obs["service_name"]) in body_html
            assert obs["service_name"] in body_text

    # Actionable next steps are present in both plain-text and HTML
    assert "Generate an XML sitemap" in body_text
    assert "Generate an XML sitemap" in body_html
    assert "compression" in body_text.lower()
    assert "compression" in body_html.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 11. Proposal preview and edit workflows retain findings and recommendations
# ═════════════════════════════════════════════════════════════════════════════
def test_11_proposal_service_preview_and_edit_retention():
    """ProposalService generates draft retaining findings, and human edits retain structure."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "SSL certificate expired"}},
        "ux": {"cta": {"status": "WARN", "message": "Call to action missing"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    # 1. Preview generation via ProposalService
    proposal = ProposalService.get_or_create_proposal(
        lead_id=str(lead.id),
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit_results,
        audit_id=str(audit.id),
    )

    assert "Critical Issues" in proposal["body_text"]
    assert "Warnings" in proposal["body_text"]
    assert len(proposal["observations"]) >= 2

    # 2. Human editing workflow: custom edit preserves content
    edited_subject = f"Custom Security Review for {lead.business_name}"
    edited_text = proposal["body_text"] + "\nNote: Added by lead specialist."
    edited_html = proposal["body_html"] + "<p>Note: Added by lead specialist.</p>"

    updated = ProposalService.edit_proposal(
        lead_id=str(lead.id),
        subject=edited_subject,
        body_text=edited_text,
        body_html=edited_html,
    )

    assert updated["subject"] == edited_subject
    assert "Added by lead specialist" in updated["body_text"]
    assert "Critical Issues" in updated["body_text"]
    assert "Warnings" in updated["body_text"]
    assert updated["edited"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 12. Existing template and campaign compatibility
# ═════════════════════════════════════════════════════════════════════════════
def test_12_template_renderer_compatibility_across_campaigns():
    """TemplateRenderer formats {audit_findings} and {audit_recommendations} with Critical/Warning separation."""
    lead = _make_mock_lead()
    audit_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "SSL certificate expired"}},
        "performance": {"gzip_compression": {"status": "WARN", "message": "Compression not enabled"}},
    }
    audit = _make_mock_audit(lead, audit_results=audit_results)

    # Test with custom template using approved context variables
    custom_template = (
        "Hi {business_name},\n\n"
        "Here are our observations for {domain}:\n"
        "{audit_findings}\n\n"
        "Recommended Plan:\n"
        "{audit_recommendations}\n\n"
        "Best regards,\n{sender_name}"
    )

    rendered = TemplateRenderer.render_campaign_email(
        template=custom_template,
        subject_template="Website notes for {domain}",
        lead=lead,
        audit=audit,
        campaign_type=CampaignType.VALID_WEBSITE_SEO,
    )

    plain_body = rendered["plain_body"]
    assert "Critical Issues:" in plain_body
    assert "Warnings:" in plain_body
    assert "Recommended:" in plain_body
    assert lead.business_name in plain_body


# ═════════════════════════════════════════════════════════════════════════════
# 13. Findings from unrelated leads or audits are never mixed together
# ═════════════════════════════════════════════════════════════════════════════
def test_13_cross_lead_audit_isolation():
    """Findings and evidence from Lead A are never leaked into Lead B's proposal."""
    lead_a = _make_mock_lead(business_name="Alpha Medical", website="https://alphamedical.example", lead_id=uuid.uuid4())
    lead_b = _make_mock_lead(business_name="Beta Logistics", website="https://betalogistics.example", lead_id=uuid.uuid4())

    audit_a_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "Alpha has invalid SSL"}},
    }
    audit_b_results = {
        "technical": {"mobile": {"status": "FAIL", "message": "Beta viewport missing"}},
    }

    audit_a = _make_mock_audit(lead_a, audit_results=audit_a_results, audit_id=uuid.uuid4())
    audit_b = _make_mock_audit(lead_b, audit_results=audit_b_results, audit_id=uuid.uuid4())

    proposal_a = AuditEmailService.generate(lead=lead_a, audit=audit_a)
    proposal_b = AuditEmailService.generate(lead=lead_b, audit=audit_b)

    # Alpha's proposal has SSL, never mobile
    assert "SSL" in proposal_a["body_text"] or "ssl" in proposal_a["body_text"].lower()
    assert "viewport" not in proposal_a["body_text"].lower()
    assert "Beta" not in proposal_a["body_text"]

    # Beta's proposal has Mobile, never SSL
    assert "mobile" in proposal_b["body_text"].lower() or "viewport" in proposal_b["body_text"].lower()
    assert "SSL" not in proposal_b["body_text"]
    assert "Alpha" not in proposal_b["body_text"]
