"""
tests/test_generic_preview_regression.py
----------------------------------------
Authoritative regression test suite for email previewing, generic campaign templates,
safe error handling, and security invariants:
1. Valid default generic_first_contact previews successfully without any audit record.
2. Lead with normal business name & synthetic email (Tamanna trading / sales@tanla.com) previews cleanly.
3. Missing optional sender details follow documented safe fallback behavior.
4. Missing required variables produce a useful, structured error.
5. Unknown placeholders ({unknown_variable}) fail-closed safely with clear diagnostic.
6. Unsafe HTML and dangerous URL schemes (javascript:, data:) are sanitized / blocked.
7. Genuine rendering errors surface in API response with a safe actionable message without leaking secrets.
8. Generic rendering does not require audit_references or unapplied database migrations.
9. Preview returns subject, plain_body, and html_body synchronised.
10. A preview action NEVER invokes SMTP or triggers email delivery.
11. Manually saved legacy generic template renders with backward compatibility.
12. Audit-dependent templates missing findings fail closed and do not fall back to generic copy.
13. No-website campaigns use their own template and do not require audit records.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import Lead, Audit, AuditStatus, Campaign, CampaignStatus, CampaignEmailLog
from app.services.template_renderer import (
    TemplateRenderer,
    TemplateRenderingError,
    DEFAULT_SEGMENT_TEMPLATES,
    sanitize_url,
)
from app.routers.campaigns import CampaignPreviewRequest, preview_campaign_email
from app.routers.auth import create_access_token


def _get_auth_headers():
    token = create_access_token({"sub": "admin_test", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _make_lead(
    business_name="Tamanna trading",
    email="sales@tanla.com",
    website=None,
    verification_status="valid",
    association_status="matched",
    is_quarantined=False,
):
    lead = MagicMock(spec=Lead)
    lead.id = uuid.uuid4()
    lead.business_name = business_name
    lead.email = email
    lead.website = website
    lead.email_verification_status = verification_status
    lead.email_business_association_status = association_status
    lead.is_quarantined = is_quarantined
    lead.quarantine_reason = None
    lead.last_emailed_at = None
    return lead


# ─── 1 & 2. Valid default generic template previews cleanly without audit ──────

def test_generic_preview_succeeds_without_audit():
    """Generic first contact preview succeeds without any audit record."""
    lead = _make_lead(business_name="Tamanna trading", email="sales@tanla.com", website=None)
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
    )

    assert res["subject"]
    assert "Tamanna trading" in res["subject"] or "Tamanna trading" in res["plain_body"]
    assert res["plain_body"]
    assert res["html_body"]
    assert "<html" in res["html_body"].lower()
    assert res["content_strategy"] == "generic_first_contact"


def test_tamanna_trading_reproduction_fixture_via_endpoint():
    """Direct reproduction test for the reported Tamanna trading screenshot scenario."""
    lead = _make_lead(business_name="Tamanna trading", email="sales@tanla.com", website=None)
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    mock_db = AsyncMock()
    mock_db.get.return_value = lead
    mock_audit_res = MagicMock()
    mock_audit_res.scalar_one_or_none.return_value = None
    mock_demo_res = MagicMock()
    mock_demo_res.scalar.return_value = None
    mock_db.execute.side_effect = [mock_audit_res, mock_demo_res]

    req = CampaignPreviewRequest(
        lead_id=str(lead.id),
        template=defaults["template"],
        subject_template=defaults["subject"],
        campaign_type="generic_first_contact",
    )

    import asyncio
    resp = asyncio.run(preview_campaign_email(body=req, db=mock_db))

    assert resp["subject"].startswith("Website observation")
    assert "Tamanna trading" in resp["plain_body"]
    assert resp["is_eligible"] is True
    assert resp["exclusion_reason"] is None
    assert resp["website_classification"] == "no_website"
    assert resp["sendability_classification"] == "eligible"


# ─── 3. Missing optional sender details follow documented fallback ─────────────

def test_missing_optional_sender_details_use_documented_fallbacks():
    """Missing sender_account config falls back to default TEB Solutions / Ashish branding."""
    lead = _make_lead(business_name="Beta Retail", email="contact@betaretail.in", website="https://betaretail.in")
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
        sender_account=None,
    )

    assert "Ashish" in res["plain_body"]
    assert "TEB Solutions" in res["plain_body"]
    assert "tebsolutions.in" in res["plain_body"]


# ─── 4 & 5. Unknown placeholders and missing variables fail-closed ─────────────

def test_unknown_placeholder_fails_closed_with_structured_error():
    """Unrecognized placeholder {unknown_variable} raises TemplateRenderingError naming the variable."""
    lead = _make_lead(business_name="Gamma Supplies", email="info@gammasupplies.com")

    bad_template = "Hi {business_name}, check our discount {special_promo_discount_2026}!"
    with pytest.raises(TemplateRenderingError) as exc_info:
        TemplateRenderer.render_campaign_email(
            template=bad_template,
            subject_template="Update for {business_name}",
            lead=lead,
            audit=None,
            campaign_type="generic_first_contact",
        )

    assert "unresolved placeholders" in str(exc_info.value).lower()
    assert "special_promo_discount_2026" in str(exc_info.value)


def test_unknown_placeholder_in_subject_fails_closed():
    """Unresolved placeholder in subject line also fails closed."""
    lead = _make_lead(business_name="Delta Tech", email="ops@deltatech.co")
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    with pytest.raises(TemplateRenderingError) as exc_info:
        TemplateRenderer.render_campaign_email(
            template=defaults["template"],
            subject_template="{nonexistent_token} - review",
            lead=lead,
            audit=None,
            campaign_type="generic_first_contact",
        )

    assert "unresolved placeholders" in str(exc_info.value).lower()
    assert "nonexistent_token" in str(exc_info.value)


# ─── 6. Unsafe HTML and dangerous URL schemes remain blocked ───────────────────

def test_unsafe_javascript_and_data_schemes_are_sanitized():
    """Dangerous URL schemes like javascript: and data: are stripped by sanitize_url."""
    assert sanitize_url("javascript:alert(document.cookie)") == ""
    assert sanitize_url("data:text/html,<script>alert(1)</script>") == ""
    assert sanitize_url("vbscript:msgbox(1)") == ""
    assert sanitize_url("//malicious.com/payload") == ""
    assert sanitize_url("https://safe-domain.example/page") == "https://safe-domain.example/page"


def test_malicious_xss_in_lead_business_name_escaped_in_html():
    """XSS injection payloads in lead attributes are HTML-escaped in html_body."""
    lead = _make_lead(
        business_name="<script>alert('pwned')</script>",
        email="test@example.com",
    )
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
    )

    assert "<script>alert('pwned')</script>" not in res["html_body"]
    assert "&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt;" in res["html_body"]


# ─── 7. Safe error contract between preview API and frontend ───────────────────

def test_endpoint_returns_safe_400_for_invalid_template():
    """Preview API returns HTTP 400 with structured detail on template validation errors."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_lead(business_name="Echo Log", email="info@echolog.com")

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        mock_audit_res = MagicMock()
        mock_audit_res.scalar_one_or_none.return_value = None
        mock_demo_res = MagicMock()
        mock_demo_res.scalar.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_audit_res, mock_demo_res])
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/preview",
            json={
                "lead_id": str(lead_id),
                "template": "Hello {invalid_unknown_var_xyz}!",
                "subject_template": "Test subject",
                "campaign_type": "generic_first_contact",
            },
            headers=_get_auth_headers(),
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "Template rendering failed" in detail
        assert "invalid_unknown_var_xyz" in detail
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 8. Generic rendering does not require audit_references or migration ────────

def test_generic_rendering_does_not_require_audit_references():
    """Generic first-contact campaigns do not require or read audit_references."""
    lead = _make_lead(business_name="Zeta Corp", email="hi@zetacorp.org")
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
    )

    assert "audit_reference" not in res
    assert res["content_strategy"] == "generic_first_contact"


# ─── 9. Synchronized subject, plain_body, and html_body generation ──────────────

def test_preview_generates_all_three_content_formats():
    """A valid generic preview produces synchronized subject, plain_body, and html_body."""
    lead = _make_lead(business_name="Omega Enterprises", email="ops@omega.example", website="https://omega.example")
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
    )

    assert isinstance(res["subject"], str) and len(res["subject"]) > 5
    assert isinstance(res["plain_body"], str) and len(res["plain_body"]) > 50
    assert isinstance(res["html_body"], str) and len(res["html_body"]) > 100
    assert "omega.example" in res["plain_body"]
    assert "omega.example" in res["html_body"]


# ─── 10. Preview action NEVER dispatches emails or calls SMTP ───────────────────

def test_preview_never_calls_smtp():
    """Calling preview endpoint must never execute SMTP transport."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_lead(business_name="Safe Preview Lead", email="preview@safetest.com")
    defaults = TemplateRenderer.get_default_template("generic_first_contact")

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        mock_audit_res = MagicMock()
        mock_audit_res.scalar_one_or_none.return_value = None
        mock_demo_res = MagicMock()
        mock_demo_res.scalar.return_value = None
        mock_db.execute = AsyncMock(side_effect=[mock_audit_res, mock_demo_res])
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
             patch("smtplib.SMTP") as mock_smtp, \
             patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
            resp = client.post(
                "/campaigns/preview",
                json={
                    "lead_id": str(lead_id),
                    "template": defaults["template"],
                    "subject_template": defaults["subject"],
                    "campaign_type": "generic_first_contact",
                },
                headers=_get_auth_headers(),
            )
            assert resp.status_code == 200
            mock_send.assert_not_called()
            mock_smtp.assert_not_called()
            mock_smtp_ssl.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 11. Manually saved legacy generic template compatibility ──────────────────

def test_legacy_saved_generic_template_renders_properly():
    """Legacy generic templates with spintax and approved tokens render cleanly."""
    lead = _make_lead(business_name="Legacy Client", email="contact@legacyclient.com", website="https://legacyclient.com")
    legacy_template = (
        "{hi|hello} {business_name},\n\n"
        "We noticed {domain} and wanted to reach out regarding your online presence.\n\n"
        "Best regards,\n{sender_name}\n{company_name}"
    )
    legacy_subject = "Question regarding {business_name}"

    res = TemplateRenderer.render_campaign_email(
        template=legacy_template,
        subject_template=legacy_subject,
        lead=lead,
        audit=None,
        campaign_type="generic_first_contact",
    )

    assert "Legacy Client" in res["subject"]
    assert "legacyclient.com" in res["plain_body"]
    assert "Ashish" in res["plain_body"]
    assert "TEB Solutions" in res["plain_body"]


# ─── 12. Audit-dependent template missing findings fails closed ─────────────────

def test_audit_dependent_template_missing_findings_fails_closed():
    """An audit-dependent campaign without audit evidence raises TemplateRenderingError and does not send."""
    lead = _make_lead(business_name="No Audit Lead", email="noaudit@example.com", website="https://noaudit.example")
    defaults = TemplateRenderer.get_default_template("valid_website_seo")

    with pytest.raises(TemplateRenderingError) as exc_info:
        TemplateRenderer.render_campaign_email(
            template=defaults["template"],
            subject_template=defaults["subject"],
            lead=lead,
            audit=None,
            campaign_type="valid_website_seo",
        )

    assert "completed audit is required" in str(exc_info.value).lower()


# ─── 13. No-website campaigns use their own template without audit record ───────

def test_no_website_campaign_uses_own_template_without_audit():
    """No-website design campaign previews cleanly with no audit record."""
    lead = _make_lead(business_name="Brick & Mortar Shop", email="shop@localmail.com", website=None)
    defaults = TemplateRenderer.get_default_template("no_website_design")

    res = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="no_website_design",
    )

    assert "Brick & Mortar Shop" in res["subject"]
    assert "do not currently have an active website" in res["plain_body"]
    assert res["content_strategy"] == "no_website_design"
