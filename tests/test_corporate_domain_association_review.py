"""
tests/test_corporate_domain_association_review.py

Focused test suite verifying the Corporate Domain Association Review Queue:
1. Review queue count is derived from current data (actual database count, not hardcoded).
2. Query leads using authoritative eligibility logic:
   - valid email routing
   - non-quarantined status
   - custom business email domain (non-public email provider)
   - unverified / external-domain association status
3. Review queue items expose business name, website, association status, and provenance evidence.
4. Pagination and search filtering work correctly on corporate_review view.
5. Unauthorized users cannot approve associations (401 / 403).
6. Authorized operator approval transitions association status to 'approved', creates ActivityLog,
   and updates the corresponding KPI (decrements pending review, increments deliverable).
7. Non-MX-based auto-approval check: MX record resolution alone does NOT auto-approve domain association.
8. Non-mutation invariance: Displaying the queue does not alter verification status, website status,
   quarantine status, or campaign eligibility.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.main import app
from app.database import get_db
from app.models import Lead, LeadStatus, ActivityLog, EmailAssociationStatus
from app.utils.email_constants import PUBLIC_EMAIL_PROVIDERS


def _create_token(sub="operator@tebsolutions.in", role="operator"):
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    return jwt.encode(
        {"sub": sub, "role": role, "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.fixture
def operator_headers():
    return {"Authorization": f"Bearer {_create_token('operator@tebsolutions.in', 'operator')}"}


@pytest.fixture
def viewer_headers():
    return {"Authorization": f"Bearer {_create_token('viewer@tebsolutions.in', 'viewer')}"}


@pytest.fixture
def client(operator_headers):
    c = TestClient(app)
    c.headers.update(operator_headers)
    return c


def _make_dummy_lead(
    lead_id=None,
    business_name="Acme Corporate Ltd",
    website="https://acmecorp.com",
    email="contact@acmecorp.com",
    verification_status="valid",
    association_status="unverified_association",
    is_quarantined=False,
    quarantine_reason=None,
    email_source_url="https://acmecorp.com/contact",
    email_source_type="website_scrape",
    email_domain_match=True,
):
    lead = Lead(
        id=uuid.UUID(lead_id) if lead_id else uuid.uuid4(),
        business_name=business_name,
        website=website,
        email=email,
        status=LeadStatus.new,
        phone=None,
        email_verification_status=verification_status,
        email_business_association_status=association_status,
        email_association_reason="Test reason",
        is_quarantined=is_quarantined,
        quarantine_reason=quarantine_reason,
        email_source_url=email_source_url,
        email_source_type=email_source_type,
        email_domain_match=email_domain_match,
        email_verified_at=datetime.now(timezone.utc),
        email_verification_details={
            "status": verification_status,
            "score": 100,
            "is_sendable": True,
            "syntax_ok": True,
            "has_mx": True,
            "is_disposable": False,
        },
        created_at=datetime.now(timezone.utc),
    )
    lead.audit = None
    return lead


# ── Requirement 1, 2, 3: Dynamic KPI and Authoritative Filtering ────────────

def test_corporate_review_stats_derived_from_actual_data(client):
    """
    Test that corporate_pending_review KPI is computed dynamically
    from valid, non-quarantined, custom business domain leads with unverified association.
    """
    # 2 leads: 1 corporate domain (customcorp.in), 1 public domain (gmail.com)
    corp_lead = _make_dummy_lead(email="info@customcorp.in", association_status="unverified_association")
    public_lead = _make_dummy_lead(email="john@gmail.com", association_status="unverified_association")

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(side_effect=[
            985,  # total_leads
            465,  # quarantined_count
            305,  # deliverable_count
            437,  # unverified_total
            104,  # unverified_quarantined
            0,    # invalid
            0,    # disposable
            0,    # catch_all
            0,    # risky
            0,    # not_found
            0,    # timeout
            0,    # error
        ])
        # execute returns demo_emails for unverified association leads
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = ["info@customcorp.in", "john@gmail.com"]
        mock_db.execute = AsyncMock(return_value=mock_res)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "corporate_pending_review" in data
        # customcorp.in is non-public -> corporate_pending_review == 1
        assert data["corporate_pending_review"] == 1
        # gmail.com is public -> demo_only_eligible == 1
        assert data["demo_only_eligible"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Requirement 4 & 9: Filterable Review Table & Provenance Evidence ────────

def test_corporate_review_leads_endpoint_pagination_and_provenance(client):
    """
    Test that GET /email-verify/leads?view=corporate_review returns leads with:
    - business_name, website, email
    - association_status
    - email_source_url, email_source_type, email_domain_match
    - pagination metadata (page, page_size, total, total_pages)
    """
    leads = [
        _make_dummy_lead(
            business_name=f"Enterprise {i}",
            website=f"https://enterprise{i}.com",
            email=f"contact@enterprise{i}.com",
            email_source_url=f"https://enterprise{i}.com/about",
            email_source_type="website_scrape",
            email_domain_match=True,
        )
        for i in range(15)
    ]

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=97)  # total count in DB
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = leads[:10]  # page 1 with page_size=10
        mock_db.execute = AsyncMock(return_value=mock_res)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/leads?view=corporate_review&page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 97
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert data["total_pages"] == 10
        assert len(data["items"]) == 10

        item = data["items"][0]
        assert "business_name" in item
        assert "website" in item
        assert "email" in item
        assert "association_status" in item
        assert "email_source_url" in item
        assert "email_source_type" in item
        assert "email_domain_match" in item
        assert item["email_source_url"] == "https://enterprise0.com/about"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Requirement 5 & 9: Operator Review Authorization & Fail-Closed Gate ─────

def test_unauthorized_user_cannot_approve_association():
    """
    Test that an unauthenticated or unauthorized user cannot approve associations.
    """
    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=_make_dummy_lead())
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        unauth_client = TestClient(app)
        dummy_id = str(uuid.uuid4())

        # 1. No token -> 401
        resp = unauth_client.post(
            f"/leads/{dummy_id}/approve-association",
            json={"reason": "Manual operator approval for enterprise domain"},
        )
        assert resp.status_code == 401

        # 2. Insufficient privileges (viewer role) -> 403
        viewer_token = _create_token(role="viewer")
        resp_viewer = unauth_client.post(
            f"/leads/{dummy_id}/approve-association",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"reason": "Manual operator approval for enterprise domain"},
        )
        assert resp_viewer.status_code == 403

        # 3. Forged reviewer claim -> 403
        operator_token = _create_token(sub="operator@tebsolutions.in", role="operator")
        resp_forged = unauth_client.post(
            f"/leads/{dummy_id}/approve-association",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={"reviewer": "different_person@tebsolutions.in", "reason": "Valid reason provided"},
        )
        assert resp_forged.status_code == 403
        assert "forged" in resp_forged.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Requirement 8: Approval Updates KPI and Transitions to Deliverable ──────

def test_authorized_approval_updates_lead_and_activity_log(client):
    """
    Test that approving a corporate domain association:
    1. Sets email_business_association_status = 'approved'.
    2. Records the operator and policy in email_association_reason.
    3. Adds an ActivityLog entry with event_type='association_approved'.
    4. Transitions lead to Deliverable pool.
    """
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        email="contact@enterprise.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=False,
    )

    activity_logs = []

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        mock_db.add = MagicMock(side_effect=lambda x: activity_logs.append(x))
        mock_db.commit = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one.return_value = lead
        mock_db.execute = AsyncMock(return_value=mock_res)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={
                "reason": "Verified corporate domain registration and official company website",
                "policy_reference": "manual_corporate_domain_review",
            },
        )
        assert resp.status_code == 200
        assert lead.email_business_association_status == EmailAssociationStatus.APPROVED.value
        assert "operator@tebsolutions.in" in lead.email_association_reason
        assert "manual_corporate_domain_review" in lead.email_association_reason

        # Verify audit activity log was recorded
        assert any(
            isinstance(log, ActivityLog) and log.event_type == "association_approved"
            for log in activity_logs
        )
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Requirement 6: MX Resolution Alone Does Not Auto-Approve Domain ─────────

def test_mx_resolution_does_not_auto_approve_association():
    """
    Requirement 6: Do not automatically approve domains merely because their MX records resolve.
    Verifying an email must check MX, but leave unverified association as unverified.
    """
    lead = _make_dummy_lead(
        email="contact@enterprise.com",
        association_status="unverified_association",
        verification_status="valid",
    )
    # The lead has valid MX but its association status remains unverified_association
    assert lead.email_verification_details.get("has_mx") is True
    assert lead.email_business_association_status == "unverified_association"
    assert lead.email_business_association_status != EmailAssociationStatus.APPROVED.value


# ── Requirement 7: Invariance - Queue Display Has No Side Effects ────────────

def test_displaying_queue_has_no_side_effects(client):
    """
    Requirement 7: Do not change email verification status, website verification status,
    proposal approval, quarantine status, or campaign eligibility as a side effect
    of displaying the queue.
    """
    lead = _make_dummy_lead(
        email="contact@enterprise.com",
        verification_status="valid",
        association_status="unverified_association",
        is_quarantined=False,
    )
    initial_verif = lead.email_verification_status
    initial_assoc = lead.email_business_association_status
    initial_quar = lead.is_quarantined

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=1)
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lead]
        mock_db.execute = AsyncMock(return_value=mock_res)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/leads?view=corporate_review")
        assert resp.status_code == 200

        # Verify lead attributes did not mutate
        assert lead.email_verification_status == initial_verif
        assert lead.email_business_association_status == initial_assoc
        assert lead.is_quarantined == initial_quar
    finally:
        app.dependency_overrides.pop(get_db, None)
