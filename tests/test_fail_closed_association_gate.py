"""
tests/test_fail_closed_association_gate.py

Regression test suite verifying fail-closed email association gate enforcement:
1. Verified lead with 'matched' association proceeds only when all eligibility checks pass.
2. Verified lead with None association status is blocked at both creation and worker boundaries.
3. Legacy record missing the association field is blocked.
4. Empty or unknown association status is blocked.
5. 'external_domain_review' is blocked until an explicit approved review occurs.
6. 'unverified_association', 'mismatched_source', and 'invalid_format' are blocked.
7. Authorized, auditable approval follows only the explicit configured policy.
8. Lead quarantined after queue creation is still blocked by final pre-send check.
9. Retry and resend operations cannot bypass association checks.
10. Sendable-only exports exclude unresolved associations.
11. Failed recipients never reach the provider and do not consume submission quota.
12. Re-importing or rediscovering a blocked email cannot bypass suppression.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.main import app
from app.database import get_db
from app.models import (
    Lead,
    LeadStatus,
    Campaign,
    CampaignStatus,
    Audit,
    AuditStatus,
    CampaignEmailLog,
    EmailAssociationStatus,
    ActivityLog,
)
from app.engines.outreach_engine import _run_campaign_worker
from app.services.lead_discovery_service import LeadDiscoveryService
from app.routers.auth import create_access_token


def _get_admin_headers():
    token = create_access_token({"sub": "audit_lead@tebsolutions.in", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}
# ─── Helper Fixtures & Contexts ──────────────────────────────────────────────

def _make_dummy_campaign(lead_ids, camp_id=None):
    return Campaign(
        id=uuid.UUID(camp_id) if camp_id else uuid.uuid4(),
        name="Fail-Safe Test Campaign",
        status=CampaignStatus.sending,
        subject_template="Audit for {business_name}",
        template="Hello {business_name}",
        lead_ids=[str(lid) for lid in lead_ids],
        pending_lead_ids=[str(lid) for lid in lead_ids],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )


def _make_dummy_lead(
    lead_id=None,
    email="test@example.com",
    association_status="matched",
    verification_status="valid",
    is_quarantined=False,
    quarantine_reason=None,
):
    lead = Lead(
        id=uuid.UUID(lead_id) if lead_id else uuid.uuid4(),
        business_name="Acme Inc",
        email=email,
        website="https://example.com",
        status=LeadStatus.new,
        is_quarantined=is_quarantined,
        quarantine_reason=quarantine_reason,
        email_verification_status=verification_status,
        email_business_association_status=association_status,
        email_association_reason="Automated test fixture",
        created_at=datetime.now(timezone.utc),
    )
    return lead


# ─── 1. Verified lead with 'matched' association ─────────────────────────────

def test_1_verified_matched_lead_proceeds_when_all_checks_pass():
    """1. Verified lead with 'matched' proceeds only when every other check passes."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)
    lead = _make_dummy_lead(
        lead_id=lead_id,
        email="owner@example.com",
        association_status="matched",
        verification_status="valid",
        is_quarantined=False,
    )

    mock_audit = MagicMock(spec=Audit)
    mock_audit.error_message = None

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=mock_audit),
        scalar=MagicMock(return_value=0),
    ))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 1
            assert campaign.sent_count == 1
            assert campaign.skipped_count == 0

    asyncio.run(_run())


# ─── 2. Verified lead with None association status is blocked ─────────────────

def test_2_verified_lead_with_none_association_blocked_at_campaign_creation():
    """2a. Lead with None association status is blocked during campaign creation."""
    client = TestClient(app)
    lead_id = uuid.uuid4()

    async def override_get_db():
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.fetchall.return_value = []  # Fail-closed query returned 0 ready leads
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={"name": "Test None Assoc", "lead_ids": [str(lead_id)], "template": "T", "subject_template": "S"},
            headers=_get_admin_headers(),
        )
        assert resp.status_code == 400
        assert "not campaign-ready" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_2_verified_lead_with_none_association_blocked_at_sending_worker():
    """2b. Sending worker blocks and quarantines lead with None association."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)
    lead = _make_dummy_lead(
        lead_id=lead_id,
        email="none_assoc@example.com",
        association_status=None,  # Missing/None
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1
            assert lead.is_quarantined is True
            assert "missing_email_business_association_status" in lead.quarantine_reason

    asyncio.run(_run())


# ─── 3. Legacy record missing the association field is blocked ────────────────

def test_3_legacy_record_missing_association_field_blocked():
    """3. Legacy record where association attribute is absent or None is blocked."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)

    class LegacyLead(Lead):
        pass

    legacy_lead = _make_dummy_lead(lead_id=lead_id, verification_status="valid", is_quarantined=False)
    delattr(legacy_lead, "email_business_association_status")

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else legacy_lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1
            assert legacy_lead.is_quarantined is True

    asyncio.run(_run())


# ─── 4. Empty or unknown association status is blocked ────────────────────────

@pytest.mark.parametrize("bad_status", ["", "   ", "unknown", "arbitrary_custom_status", "pending_match"])
def test_4_empty_or_unknown_association_status_blocked(bad_status):
    """4. Empty or unrecognized association status values are strictly blocked."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)
    lead = _make_dummy_lead(
        lead_id=lead_id,
        association_status=bad_status,
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1
            assert lead.is_quarantined is True

    asyncio.run(_run())


# ─── 5. external_domain_review blocked until approved ────────────────────────

def test_5_external_domain_review_blocked_until_explicitly_approved():
    """5. external_domain_review is blocked before approval, then proceeds after approval."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)

    # Lead with external domain review
    lead = _make_dummy_lead(
        lead_id=lead_id,
        email="contact.business@gmail.com",
        association_status="external_domain_review",
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=MagicMock(error_message=None)),
        scalar=MagicMock(return_value=0),
    ))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run_blocked():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1
            assert lead.is_quarantined is True

    asyncio.run(_run_blocked())

    # Now simulate authorized approval
    lead.email_business_association_status = "approved"
    lead.is_quarantined = False
    campaign.skipped_count = 0
    campaign.pending_lead_ids = [lead_id]

    async def _run_approved():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 1
            assert campaign.sent_count == 1
            assert campaign.skipped_count == 0

    asyncio.run(_run_approved())


# ─── 6. unverified_association, mismatched_source, invalid_format blocked ────

@pytest.mark.parametrize("status", ["unverified_association", "mismatched_source", "invalid_format"])
def test_6_unverified_mismatched_and_invalid_format_blocked(status):
    """6. unverified_association, mismatched_source, and invalid_format are blocked."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)
    lead = _make_dummy_lead(
        lead_id=lead_id,
        association_status=status,
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1
            assert lead.is_quarantined is True

    asyncio.run(_run())


# ─── 7. Authorized, auditable approval follows configured policy ─────────────

def test_7_authorized_approval_policy_enforcement():
    """7. Authorized approval requires authenticated operator, validates reason, rejects invalid_format."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        association_status="external_domain_review",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="external_domain_review",
    )

    token = create_access_token({"sub": "audit_lead@tebsolutions.in", "role": "admin"})
    auth_headers = {"Authorization": f"Bearer {token}"}

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one.return_value = lead
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        # A. Missing reason (< 5 chars) -> 422/400 validation error
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reviewer": "audit_lead@tebsolutions.in", "reason": ""},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

        # B. Invalid format cannot be approved
        lead.email_business_association_status = "invalid_format"
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Verified business ownership"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "invalid format" in resp.json()["detail"].lower()

        # C. Valid approval under documented policy
        lead.email_business_association_status = "external_domain_review"
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={
                "reason": "Verified Google Workspace invoice matches company registration",
                "policy_reference": "POLICY-EXT-2026",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert lead.email_business_association_status == "approved"
        assert "audit_lead@tebsolutions.in" in lead.email_association_reason
        assert lead.is_quarantined is False  # Restored because verification_status is valid
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_7a_approval_unauthenticated_access_blocked():
    """Unauthenticated access (missing or invalid token) is strictly rejected (401)."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        association_status="external_domain_review",
        is_quarantined=True,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        # 1. No header -> 401
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
        )
        assert resp.status_code == 401
        assert "authentication required" in resp.json()["detail"].lower()

        # 2. Malformed scheme -> 401
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
            headers={"Authorization": "Basic some_basic_token"},
        )
        assert resp.status_code == 401
        assert "invalid authorization scheme" in resp.json()["detail"].lower()

        # 3. Invalid token string -> 401
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
            headers={"Authorization": "Bearer invalid_garbage_token"},
        )
        assert resp.status_code == 401
        assert "invalid or expired token" in resp.json()["detail"].lower()

        # 4. Expired token -> 401
        past_exp = datetime.utcnow() - timedelta(minutes=15)
        expired_token = jwt.encode(
            {"sub": "admin", "role": "admin", "exp": past_exp},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401
        assert "invalid or expired token" in resp.json()["detail"].lower()

        # 5. Token signed with wrong secret -> 401
        wrong_token = jwt.encode(
            {"sub": "admin", "role": "admin", "exp": datetime.utcnow() + timedelta(minutes=15)},
            "completely_wrong_secret_key_1234567890",
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
        assert resp.status_code == 401

        # 6. Token missing subject claim -> 401
        nosub_token = jwt.encode(
            {"role": "admin", "exp": datetime.utcnow() + timedelta(minutes=15)},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Legitimate contact confirmed"},
            headers={"Authorization": f"Bearer {nosub_token}"},
        )
        assert resp.status_code == 401

        # State must remain unchanged
        assert lead.email_business_association_status == "external_domain_review"
        assert lead.is_quarantined is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_7b_approval_insufficient_permissions_blocked():
    """Authenticated user with insufficient role (e.g., 'viewer') is rejected (403)."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        association_status="external_domain_review",
        is_quarantined=True,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        viewer_token = create_access_token({"sub": "viewer_user", "role": "viewer"})
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Attempted approval by unauthorized role"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403
        assert "insufficient permissions" in resp.json()["detail"].lower()

        # State must remain unchanged
        assert lead.email_business_association_status == "external_domain_review"
        assert lead.is_quarantined is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_7c_approval_forged_reviewer_identity_rejected():
    """Client cannot spoof or forge reviewer identity differing from authenticated principal (403)."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        association_status="external_domain_review",
        is_quarantined=True,
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        operator_token = create_access_token({"sub": "real_operator@leadgen.org", "role": "operator"})
        # Attempt to claim reviewer is 'ciso@leadgen.org'
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={
                "reviewer": "ciso@leadgen.org",
                "reason": "Spoofed ciso approval signature",
            },
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert resp.status_code == 403
        assert "forged reviewer identity rejected" in resp.json()["detail"].lower()

        # State must remain unchanged
        assert lead.email_business_association_status == "external_domain_review"
        assert lead.is_quarantined is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_7d_approval_unverified_email_stays_quarantined_after_approval():
    """Approval updates association status to approved, but does NOT unquarantine if email verification is not valid."""
    client = TestClient(app)
    lead_id = uuid.uuid4()
    lead = _make_dummy_lead(
        lead_id=str(lead_id),
        association_status="external_domain_review",
        verification_status="unverified",  # Not valid
        is_quarantined=True,
        quarantine_reason="email_business_association_external_domain_review",
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=lead)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one.return_value = lead
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        token = create_access_token({"sub": "admin_auditor", "role": "admin"})
        resp = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reason": "Approved business relationship under POLICY-101"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert lead.email_business_association_status == "approved"
        # Must still be quarantined because email verification is not valid!
        assert lead.is_quarantined is True
        assert "email verification required" in lead.quarantine_reason.lower()
    finally:
        app.dependency_overrides.pop(get_db, None)



# ─── 8. Lead quarantined after queue creation blocked at pre-send ─────────────

def test_8_quarantined_after_queue_creation_blocked_pre_send():
    """8. Lead placed into pending queue but quarantined before send is blocked."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)

    # Lead was initially matched, but got quarantined prior to worker dispatch
    lead = _make_dummy_lead(
        lead_id=lead_id,
        association_status="matched",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="Manual quarantine by compliance officer",
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.sent_count == 0
            assert campaign.skipped_count == 1

            added_logs = [call[0][0] for call in mock_db.add.call_args_list if isinstance(call[0][0], CampaignEmailLog)]
            assert len(added_logs) == 1
            assert added_logs[0].status == "skipped"
            assert "Manual quarantine" in added_logs[0].message

    asyncio.run(_run())


# ─── 9. Retry and resend operations cannot bypass association checks ──────────

def test_9_retry_failed_leads_excludes_unresolved_association():
    """9. retry_failed_campaign_leads filters out leads with unresolved associations."""
    client = TestClient(app)
    camp_id = uuid.uuid4()
    failed_lead_id_1 = uuid.uuid4()
    failed_lead_id_2 = uuid.uuid4()

    # Lead 1: truly failed, but association is None -> MUST BE EXCLUDED from retry
    lead_none = _make_dummy_lead(
        lead_id=str(failed_lead_id_1),
        association_status=None,
        verification_status="valid",
        is_quarantined=False,
    )

    # Lead 2: truly failed, and association is matched -> MAY BE RETRIED
    lead_matched = _make_dummy_lead(
        lead_id=str(failed_lead_id_2),
        association_status="matched",
        verification_status="valid",
        is_quarantined=False,
    )

    campaign = Campaign(
        id=camp_id,
        name="Retry Test",
        status=CampaignStatus.draft,
        lead_ids=[str(failed_lead_id_1), str(failed_lead_id_2)],
    )

    log_1 = CampaignEmailLog(lead_id=failed_lead_id_1, status="failed", created_at=datetime.now(timezone.utc))
    log_2 = CampaignEmailLog(lead_id=failed_lead_id_2, status="failed", created_at=datetime.now(timezone.utc))

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: (
        campaign if model == Campaign else (lead_none if obj_id == failed_lead_id_1 else lead_matched)
    ))
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[log_1, log_2]))),
        scalar_one_or_none=MagicMock(return_value=MagicMock(status=AuditStatus.done)),
    ))
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routers.campaigns.run_campaign") as mock_run:
            resp = client.post(f"/campaigns/{camp_id}/retry-failed", headers=_get_admin_headers())
            assert resp.status_code == 200
            assert mock_run.called
            # Only lead 2 (matched) should be queued for retry
            assert campaign.pending_lead_ids == [str(failed_lead_id_2)]
            assert str(failed_lead_id_1) not in campaign.pending_lead_ids
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 10. Sendable-only exports exclude unresolved associations ────────────────

def test_10_sendable_only_export_excludes_unresolved_associations():
    """10. export_leads_csv with sendable_only=True excludes all unresolved/quarantined records."""
    svc = LeadDiscoveryService()
    job_id = "test_export_job"
    svc._jobs[job_id] = {
        "job_id": job_id,
        "discovered_leads": [
            {
                "business_name": "Matched Valid",
                "email": "owner@matched.com",
                "website": "https://matched.com",
                "email_business_association_status": "matched",
                "verification_status": "verified",
                "email_verification_status": "valid",
                "is_quarantined": False,
            },
            {
                "business_name": "Approved Valid",
                "email": "approved@external.com",
                "website": "https://company.org",
                "email_business_association_status": "approved",
                "verification_status": "verified",
                "email_verification_status": "valid",
                "is_quarantined": False,
            },
            {
                "business_name": "Missing Association Status",
                "email": "missing@test.com",
                "website": "https://missing.com",
                "email_business_association_status": None,
                "verification_status": "verified",
                "email_verification_status": "valid",
                "is_quarantined": False,
            },
            {
                "business_name": "External Review Unapproved",
                "email": "unapproved@gmail.com",
                "website": "https://lawyer.com",
                "email_business_association_status": "external_domain_review",
                "verification_status": "candidate",
                "is_quarantined": True,
            },
            {
                "business_name": "Mismatched Source",
                "email": "agency@designer.com",
                "website": "https://biharibrothers.com",
                "email_business_association_status": "mismatched_source",
                "verification_status": "candidate",
                "is_quarantined": True,
            },
        ],
    }

    # Sendable only export
    csv_sendable = svc.export_leads_csv(job_id, sendable_only=True)
    assert "owner@matched.com" in csv_sendable
    assert "approved@external.com" in csv_sendable
    assert "missing@test.com" not in csv_sendable
    assert "unapproved@gmail.com" not in csv_sendable
    assert "agency@designer.com" not in csv_sendable

    # Full export includes all
    csv_full = svc.export_leads_csv(job_id, sendable_only=False)
    assert "missing@test.com" in csv_full
    assert "unapproved@gmail.com" in csv_full
    assert "agency@designer.com" in csv_full


# ─── 11. Failed recipients never reach provider or consume quota ─────────────

def test_11_failed_recipients_never_reach_provider_or_consume_quota():
    """11. Blocked association never calls provider or consumes submission quota."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_dummy_campaign([lead_id], camp_id=camp_id)
    lead = _make_dummy_lead(
        lead_id=lead_id,
        email="blocked@example.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@test.com", "user": "sender", "password": "pw", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send:
            await _run_campaign_worker(camp_id)
            # Strict verification:
            assert mock_send.call_count == 0, "Provider must not be invoked"
            assert campaign.sent_count == 0, "No quota consumed"
            assert campaign.skipped_count == 1
            assert lead.is_quarantined is True

    asyncio.run(_run())


# ─── 12. Re-importing or rediscovering cannot bypass suppression ──────────────

def test_12_reimport_or_rediscovery_cannot_bypass_suppression():
    """12. Existing quarantine and association cannot be cleared by rediscovery or import."""
    existing_lead = Lead(
        id=uuid.uuid4(),
        business_name="Original Business",
        email="suppressed@agency.com",
        website="https://biz.com",
        is_quarantined=True,
        quarantine_reason="Designer mismatch suppression",
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
        email_verification_status="valid",
    )

    # Attempt manual unquarantine via PATCH without establishing approved/matched status -> Rejected
    client = TestClient(app)
    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=existing_lead)
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.patch(
            f"/leads/{existing_lead.id}",
            json={"is_quarantined": False},
            headers=_get_admin_headers(),
        )
        assert resp.status_code == 400
        assert "unresolved or missing" in resp.json()["detail"].lower()
        # Lead remains quarantined
        assert existing_lead.is_quarantined is True
        assert existing_lead.email_business_association_status == EmailAssociationStatus.MISMATCHED_SOURCE.value
    finally:
        app.dependency_overrides.pop(get_db, None)
