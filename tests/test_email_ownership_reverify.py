import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.main import app
from app.services.email_verifier_service import VerificationResult
from app.models import Lead, ActivityLog, EmailCorrection, EmailAssociationStatus
from app.services.lead_discovery_service import is_safe_external_url


@pytest.fixture
def auth_headers():
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    token = jwt.encode(
        {"sub": "operator@tebsolutions.in", "role": "operator", "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(auth_headers):
    c = TestClient(app)
    c.headers.update(auth_headers)
    return c


def create_mock_lead(
    business_name="Paradigm Logistics India",
    website="https://paradigmindia.in/",
    email="contact@myepicsoft.com",
    is_quarantined=False,
    quarantine_reason=None,
    email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
):
    lead = MagicMock(spec=Lead)
    lead.id = uuid.uuid4()
    lead.business_name = business_name
    lead.website = website
    lead.email = email
    lead.phone = "+91 9876543210"
    lead.email_candidates = []
    lead.email_source_url = None
    lead.email_source_type = None
    lead.email_extraction_method = None
    lead.email_domain = "myepicsoft.com"
    lead.website_domain = "paradigmindia.in"
    lead.email_domain_match = False
    lead.email_business_association_status = email_business_association_status
    lead.email_association_reason = "Mismatched domain"
    lead.email_verification_status = "unverified"
    lead.email_verification_details = {}
    lead.email_verified_at = None
    lead.is_quarantined = is_quarantined
    lead.quarantine_reason = quarantine_reason
    lead.created_at = datetime.now(timezone.utc)
    return lead


# ── 1. Paradigm Logistics India: Mismatch corrected to website-listed email ────
def test_reverify_endpoint_corrects_mismatched_email_from_website_evidence(client):
    """
    Paradigm Logistics India:
    Stored: contact@myepicsoft.com
    Website lists: info@paradigmindia.in
    POST /email-verify/reverify/{lead_id} replaces stored address, validates syntax/MX, records EmailCorrection audit trail.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Paradigm Logistics India",
        website="https://paradigmindia.in/",
        email="contact@myepicsoft.com",
    )
    fake_id = lead.id

    mock_candidates = [
        {
            "email": "info@paradigmindia.in",
            "email_domain": "paradigmindia.in",
            "source_type": "http_contact_page",
            "extraction_method": "company_profile_json",
            "source_url": "https://paradigmindia.in/api/SettingsApi/GetSettingsCompanyProfile",
            "context": "Found in structured company profile data: info@paradigmindia.in",
            "association_status": EmailAssociationStatus.MATCHED.value,
            "association_reason": "Direct domain match with business website 'paradigmindia.in'",
            "is_sendable": True,
        }
    ]

    mock_v_res = VerificationResult(
        email="info@paradigmindia.in",
        normalized_email="info@paradigmindia.in",
        status="valid",
        score=95,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = lead
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                True,
                "Reachable (HTTP 200)",
                "info@paradigmindia.in",
                mock_candidates,
                "https://paradigmindia.in/",
            )
            mock_verify.return_value = mock_v_res

            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["outcome_status"] == "corrected"
            assert data["old_email"] == "contact@myepicsoft.com"
            assert data["new_email"] == "info@paradigmindia.in"
            assert data["is_quarantined"] is False
            assert data["is_sendable"] is True
            assert lead.email == "info@paradigmindia.in"
            assert lead.email_domain_match is True
            assert lead.email_business_association_status == EmailAssociationStatus.MATCHED.value
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 2. Matching company-domain email is retained and revalidated ──────────────
def test_reverify_endpoint_retains_matching_company_domain_email(client):
    """
    Company-domain email matches website:
    Stored: info@paradigmindia.in
    Website lists: info@paradigmindia.in
    POST /email-verify/reverify/{lead_id} retains address and revalidates without overwriting or quarantine.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Paradigm Logistics India",
        website="https://paradigmindia.in/",
        email="info@paradigmindia.in",
    )
    fake_id = lead.id

    mock_candidates = [
        {
            "email": "info@paradigmindia.in",
            "email_domain": "paradigmindia.in",
            "source_type": "http_contact_page",
            "extraction_method": "http_page_scrape",
            "source_url": "https://paradigmindia.in/contact",
            "context": "Contact us at info@paradigmindia.in",
            "association_status": EmailAssociationStatus.MATCHED.value,
            "association_reason": "Direct domain match with business website 'paradigmindia.in'",
            "is_sendable": True,
        }
    ]

    mock_v_res = VerificationResult(
        email="info@paradigmindia.in",
        normalized_email="info@paradigmindia.in",
        status="valid",
        score=95,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = lead
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                True,
                "Reachable (HTTP 200)",
                "info@paradigmindia.in",
                mock_candidates,
                "https://paradigmindia.in/",
            )
            mock_verify.return_value = mock_v_res

            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["outcome_status"] == "revalidated"
            assert data["new_email"] == "info@paradigmindia.in"
            assert data["is_quarantined"] is False
            assert lead.email == "info@paradigmindia.in"
            assert lead.email_domain_match is True
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 3. Third-party / External email retained for review, not matched ──────────
def test_reverify_endpoint_external_domain_retained_for_operator_review(client):
    """
    Website only lists a 3rd-party email:
    Rule D: Do not automatically treat it as matching company domain.
    Retain for review with is_quarantined=True.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Acme Logistics",
        website="https://acmelogistics.com/",
        email="info@externalagency.com",
    )
    fake_id = lead.id

    mock_candidates = [
        {
            "email": "contact@externalagency.com",
            "email_domain": "externalagency.com",
            "source_type": "http_page_scrape",
            "extraction_method": "http_page_scrape",
            "source_url": "https://acmelogistics.com/",
            "context": "Designed by contact@externalagency.com",
            "association_status": EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value,
            "association_reason": "External domain requires review",
            "is_sendable": False,
        }
    ]

    mock_v_res = VerificationResult(
        email="info@externalagency.com",
        normalized_email="info@externalagency.com",
        status="valid",
        score=70,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = lead
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                True,
                "Reachable (HTTP 200)",
                "contact@externalagency.com",
                mock_candidates,
                "https://acmelogistics.com/",
            )
            mock_verify.return_value = mock_v_res

            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["outcome_status"] == "manual_review"
            assert data["is_quarantined"] is True
            assert lead.is_quarantined is True
            assert lead.email_business_association_status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 4. No usable email found excludes lead from active pool via quarantine ─────
def test_reverify_endpoint_no_usable_email_excludes_lead_via_reversible_quarantine(client):
    """
    Website has no usable email:
    Rule E: Lead excluded from active outreach pool via reversible quarantine.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Silent Logistics",
        website="https://silentlogistics.in/",
        email="bogus@oldlead.com",
    )
    fake_id = lead.id

    mock_v_res = VerificationResult(
        email="bogus@oldlead.com",
        normalized_email="bogus@oldlead.com",
        status="valid",
        score=60,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = lead
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                True,
                "Reachable (HTTP 200)",
                None,
                [],
                "https://silentlogistics.in/",
            )
            mock_verify.return_value = mock_v_res

            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["outcome_status"] == "no_email_found"
            assert data["is_quarantined"] is True
            assert "No usable company email found" in lead.quarantine_reason
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 5. Website timeout / error marked inconclusive without deletion ───────────
def test_reverify_endpoint_website_timeout_marked_inconclusive_no_deletion(client):
    """
    Website timeout, CAPTCHA, or HTTP error:
    Rule F: Inconclusive attempt, retained for retry, NEVER delete or overwrite.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Timeout Logistics",
        website="https://timeoutsite.com/",
        email="contact@timeoutsite.com",
    )
    fake_id = lead.id

    mock_v_res = VerificationResult(
        email="contact@timeoutsite.com",
        normalized_email="contact@timeoutsite.com",
        status="valid",
        score=85,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = lead
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                False,
                "Dead/Unreachable (Timeout: ClientTimeout)",
                None,
                [],
                "https://timeoutsite.com/",
            )
            mock_verify.return_value = mock_v_res

            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()

            assert data["outcome_status"] == "scrape_inconclusive"
            assert lead.email == "contact@timeoutsite.com"  # Stored email preserved
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 6. Bulk Re-verify Dry Run vs Applied Execution ────────────────────────────
def test_bulk_reverify_endpoint_dry_run_and_batch_execution(client):
    """
    Test POST /email-verify/bulk-reverify:
    Dry-run preview returns metrics without mutating lead.
    Applied run commits corrections.
    """
    from app.database import get_db

    lead = create_mock_lead(
        business_name="Paradigm Logistics India",
        website="https://paradigmindia.in/",
        email="contact@myepicsoft.com",
    )

    mock_candidates = [
        {
            "email": "info@paradigmindia.in",
            "email_domain": "paradigmindia.in",
            "source_type": "http_contact_page",
            "extraction_method": "company_profile_json",
            "source_url": "https://paradigmindia.in/api/SettingsApi/GetSettingsCompanyProfile",
            "context": "info@paradigmindia.in",
            "association_status": EmailAssociationStatus.MATCHED.value,
            "association_reason": "Domain match",
            "is_sendable": True,
        }
    ]

    mock_v_res = VerificationResult(
        email="info@paradigmindia.in",
        normalized_email="info@paradigmindia.in",
        status="valid",
        score=95,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
        is_disposable=False,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lead]
        mock_db.execute.return_value = mock_res
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.services.lead_discovery_service.LeadDiscoveryService.inspect_website_detailed", new_callable=AsyncMock) as mock_inspect, \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:

            mock_inspect.return_value = (
                True,
                "Reachable (HTTP 200)",
                "info@paradigmindia.in",
                mock_candidates,
                "https://paradigmindia.in/",
            )
            mock_verify.return_value = mock_v_res

            # 1. Dry run
            resp_dry = client.post("/email-verify/bulk-reverify", json={
                "dry_run": True,
                "limit": 10,
                "filter_mismatched_only": False,
            })
            assert resp_dry.status_code == 200
            data_dry = resp_dry.json()
            assert data_dry["mode"] == "dry_run"
            assert data_dry["total_records_examined"] == 1
            assert data_dry["domain_mismatches_identified"] == 1
            assert data_dry["website_replacements_found"] == 1
            assert data_dry["emails_corrected_and_validated"] == 1
            assert lead.email == "contact@myepicsoft.com"  # Not mutated during dry run!

            # 2. Applied run
            resp_app = client.post("/email-verify/bulk-reverify", json={
                "dry_run": False,
                "limit": 10,
                "filter_mismatched_only": False,
            })
            assert resp_app.status_code == 200
            data_app = resp_app.json()
            assert data_app["mode"] == "applied"
            assert data_app["emails_corrected_and_validated"] == 1
            assert lead.email == "info@paradigmindia.in"  # Mutated in applied run
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 7. SSRF Protection: Private and internal IPs are blocked ──────────────────
def test_ssrf_protection_blocks_internal_and_private_ips():
    """
    Ensure is_safe_external_url blocks localhost, private CIDR ranges, metadata services.
    """
    dangerous_urls = [
        "http://localhost:8000/admin",
        "http://127.0.0.1:5000/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/router",
        "http://10.0.0.5/internal",
        "http://[::1]/ipv6-loopback",
    ]

    for d_url in dangerous_urls:
        safe, reason = is_safe_external_url(d_url, allow_test_loopback=False)
        assert safe is False, f"URL {d_url} should have been blocked: {reason}"


# ── 8. Syntax and MX routeable validity does NOT imply mailbox confirmation ──
def test_syntax_mx_validity_does_not_imply_mailbox_confirmed():
    """
    Requirement 4: Syntax and DNS/MX validity must never imply mailbox confirmation.
    """
    res = VerificationResult(
        email="test@example.com",
        normalized_email="test@example.com",
        status="valid",
        score=90,
        is_sendable=True,
        syntax_ok=True,
        has_mx=True,
    )
    d = res.to_dict()
    assert d["syntax_ok"] is True
    assert d["has_mx"] is True
    assert d["mailbox_confirmed"] is False
    assert d["smtp_check"]["mailbox_confirmed"] is False
    assert "not confirmed" in d["smtp_check"]["message"].lower()
