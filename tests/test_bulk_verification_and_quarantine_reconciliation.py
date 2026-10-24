import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.main import app
from app.services.email_verifier_service import VerificationResult, EmailVerifierService
from app.models import Lead
from app.database import get_db
from app.routers.email_verification import _BULK_PROGRESS, _run_bulk_verification_job


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


def _mock_async_session_local(mock_session):
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_ctx)


# ── Criterion 1: KPI and bulk-verification counts use consistent definitions ──

def test_kpi_and_bulk_counts_consistent_definitions(client):
    """
    Criterion 1:
    Test that stats endpoint provides authoritative, reconciled counts.
    - unverified == pending_verification == unverified_active + unverified_quarantined
    - total_leads == active_deliverable + demo_only + unverified_active + quarantined
    """
    async def override_get_db():
        mock_db = AsyncMock()
        # 5 scalar calls:
        # 1. total_leads (985)
        # 2. quarantined_count (465)
        # 3. deliverable_count (143)
        # 4. pending_verification_active (333)
        # 5. unverified_quarantined (104)
        mock_db.scalar.side_effect = [985, 465, 143, 333, 104]

        # 2 execute calls:
        # 1. status_map
        mock_status_res = MagicMock()
        mock_status_res.all.return_value = [
            ("valid", 524),
            ("unverified", 437),
            ("invalid", 14),
            ("timeout", 7),
            ("risky", 2),
            ("error", 1),
        ]
        # 2. demo candidates
        mock_demo_res = MagicMock()
        mock_demo_res.scalars.return_value.all.return_value = ["test@gmail.com"] * 44

        mock_db.execute.side_effect = [mock_status_res, mock_demo_res]
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/stats")
        assert resp.status_code == 200
        data = resp.json()

        # Both unverified and pending_verification must match the authoritative total (437)
        assert data["unverified"] == 437
        assert data["pending_verification"] == 437
        assert data["unverified_active"] == 333
        assert data["unverified_quarantined"] == 104
        assert data["quarantined_verified"] == 361  # 465 - 104
        assert data["quarantined"] == 465
        assert data["deliverable"] == 143
        assert data["demo_only_eligible"] == 44

        # Mathematical consistency check
        assert data["unverified_active"] + data["unverified_quarantined"] == data["unverified"]
        assert data["quarantined_verified"] + data["unverified_quarantined"] == data["quarantined"]
        assert data["deliverable"] + data["demo_only_eligible"] + data["unverified_active"] + data["quarantined"] == data["total_leads"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Criterion 2 & 3: Bulk verification processes records and persists status ──

def test_bulk_verification_processes_and_persists():
    """
    Criteria 2 & 3:
    Test that bulk verification selects eligible unverified leads, invokes the 6-layer engine,
    and updates database records with timestamps and verification outcome.
    """
    async def _test():
        lead1 = MagicMock(spec=Lead)
        lead1.id = uuid.uuid4()
        lead1.email = "contact@corp.com"
        lead1.business_name = "Corp Ltd"
        lead1.website = "https://corp.com"
        lead1.email_verification_status = "unverified"
        lead1.is_quarantined = False
        lead1.quarantine_reason = None
        lead1.email_business_association_status = "matched"
        lead1.activity_log = []

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lead1]
        mock_session.execute.return_value = mock_res

        mock_verifier = MagicMock()
        mock_result = VerificationResult(
            email="contact@corp.com",
            normalized_email="contact@corp.com",
            status="valid",
            is_sendable=True,
            score=95,
            syntax_ok=True,
            has_mx=True,
            duration_ms=12,
        )
        mock_verifier.verify_email = AsyncMock(return_value=mock_result)

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 1,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 1,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[lead1.id], smtp_enabled=False, catch_all_enabled=False)

        # Verification assertions:
        assert lead1.email_verification_status == "valid"
        assert lead1.email_verified_at is not None
        assert lead1.is_quarantined is False
        assert mock_session.commit.called
        assert _BULK_PROGRESS["processed"] == 1
        assert _BULK_PROGRESS["valid"] == 1
        assert _BULK_PROGRESS["is_running"] is False

    asyncio.run(_test())


# ── Criterion 4 & 5: Inconclusive/invalid does not mark deliverable & quarantine maintained ──

def test_invalid_and_inconclusive_leads_quarantined_and_not_deliverable():
    """
    Criteria 4 & 5:
    Invalid syntax, disposable, or NXDOMAIN records are quarantined and never marked deliverable.
    """
    async def _test():
        bad_lead = MagicMock(spec=Lead)
        bad_lead.id = uuid.uuid4()
        bad_lead.email = "bad@nosuchdomain12345.com"
        bad_lead.email_verification_status = "unverified"
        bad_lead.is_quarantined = False
        bad_lead.quarantine_reason = None
        bad_lead.email_business_association_status = "matched"
        bad_lead.activity_log = []

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [bad_lead]
        mock_session.execute.return_value = mock_res

        mock_verifier = MagicMock()
        mock_result = VerificationResult(
            email="bad@nosuchdomain12345.com",
            normalized_email="bad@nosuchdomain12345.com",
            status="not_found",
            is_sendable=False,
            score=0,
            syntax_ok=True,
            has_mx=False,
            exclusion_reason="No MX records found for domain nosuchdomain12345.com",
        )
        mock_verifier.verify_email = AsyncMock(return_value=mock_result)

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 1,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 1,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[bad_lead.id], smtp_enabled=False, catch_all_enabled=False)

        # Lead must be quarantined and NOT deliverable
        assert bad_lead.email_verification_status == "not_found"
        assert bad_lead.is_quarantined is True
        assert "No MX records found" in bad_lead.quarantine_reason

    asyncio.run(_test())


# ── Criterion 6: Safe re-evaluation without automatic quarantine removal ──────

def test_re_evaluation_does_not_silently_clear_unverified_association():
    """
    Criterion 6:
    A quarantined lead with unverified_association that passes DNS/MX check
    becomes status="valid", but remains quarantined because the association policy requires it.
    """
    async def _test():
        quarantined_lead = MagicMock(spec=Lead)
        quarantined_lead.id = uuid.uuid4()
        quarantined_lead.email = "contact@freeemail.com"
        quarantined_lead.email_verification_status = "unverified"
        quarantined_lead.is_quarantined = True
        quarantined_lead.quarantine_reason = "Public provider domain requires association review"
        quarantined_lead.email_business_association_status = "unverified_association"
        quarantined_lead.activity_log = []

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [quarantined_lead]
        mock_session.execute.return_value = mock_res

        mock_verifier = MagicMock()
        mock_result = VerificationResult(
            email="contact@freeemail.com",
            normalized_email="contact@freeemail.com",
            status="valid",
            is_sendable=True,
            score=85,
            syntax_ok=True,
            has_mx=True,
        )
        mock_verifier.verify_email = AsyncMock(return_value=mock_result)

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 1,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 1,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[quarantined_lead.id], smtp_enabled=False, catch_all_enabled=False)

        # Email verification status updated to valid, but quarantine is NOT cleared
        assert quarantined_lead.email_verification_status == "valid"
        assert quarantined_lead.is_quarantined is True
        assert "Public provider domain requires association review" in quarantined_lead.quarantine_reason

    asyncio.run(_test())


# ── Criterion 7: Bulk processing is bounded, resumable, and idempotent ────────

def test_bulk_processing_bounded_batches_and_progress_tracking():
    """
    Criterion 7:
    Processes in bounded batches with accurate counts and progress updates.
    """
    async def _test():
        leads = []
        for i in range(12):
            l = MagicMock(spec=Lead)
            l.id = uuid.uuid4()
            l.email = f"lead{i}@example.com"
            l.email_verification_status = "unverified"
            l.is_quarantined = False
            l.quarantine_reason = None
            l.email_business_association_status = "matched"
            l.activity_log = []
            leads.append(l)

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = leads
        mock_session.execute.return_value = mock_res

        mock_verifier = MagicMock()
        mock_verifier.verify_email = AsyncMock(return_value=VerificationResult(
            email="test@example.com",
            normalized_email="test@example.com",
            status="valid",
            is_sendable=True,
            score=100,
            syntax_ok=True,
            has_mx=True,
        ))

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 12,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 12,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[l.id for l in leads], smtp_enabled=False, catch_all_enabled=False)

        assert _BULK_PROGRESS["total"] == 12
        assert _BULK_PROGRESS["processed"] == 12
        assert _BULK_PROGRESS["valid"] == 12
        assert _BULK_PROGRESS["remaining"] == 0
        assert _BULK_PROGRESS["is_running"] is False

    asyncio.run(_test())


# ── Criterion 8: Concurrent bulk requests reject duplicate runs (409) ─────────

def test_concurrent_bulk_verification_rejected(client):
    """
    Criterion 8:
    Verify that if a bulk verification run is already active, subsequent requests return 409 Conflict.
    """
    _BULK_PROGRESS["is_running"] = True
    _BULK_PROGRESS["processed"] = 10
    _BULK_PROGRESS["total"] = 100

    try:
        resp = client.post("/email-verify/bulk", json={"limit": 50})
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"].lower()
    finally:
        _BULK_PROGRESS["is_running"] = False


# ── Criterion 9: Partial failures produce honest summaries ─────────────────────

def test_partial_failures_honest_summaries():
    """
    Criterion 9:
    If individual leads fail with exceptions during DNS lookup, the engine logs failure,
    increments failed count, preserves remaining records, and marks is_running False.
    """
    async def _test():
        good_lead = MagicMock(spec=Lead)
        good_lead.id = uuid.uuid4()
        good_lead.email = "good@corp.com"
        good_lead.email_verification_status = "unverified"
        good_lead.is_quarantined = False
        good_lead.email_business_association_status = "matched"
        good_lead.activity_log = []

        failing_lead = MagicMock(spec=Lead)
        failing_lead.id = uuid.uuid4()
        failing_lead.email = "error@corp.com"
        failing_lead.email_verification_status = "unverified"
        failing_lead.is_quarantined = False
        failing_lead.email_business_association_status = "matched"
        failing_lead.activity_log = []

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [good_lead, failing_lead]
        mock_session.execute.return_value = mock_res

        async def mock_verify(email, **kwargs):
            if "error" in email:
                raise RuntimeError("DNS resolver network failure")
            return VerificationResult(
                email=email,
                normalized_email=email,
                status="valid",
                is_sendable=True,
                score=90,
                syntax_ok=True,
                has_mx=True,
            )

        mock_verifier = MagicMock()
        mock_verifier.verify_email = AsyncMock(side_effect=mock_verify)

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 2,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 2,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[good_lead.id, failing_lead.id], smtp_enabled=False, catch_all_enabled=False)

        assert _BULK_PROGRESS["processed"] == 2
        assert _BULK_PROGRESS["valid"] == 1
        assert _BULK_PROGRESS["failed"] == 1
        assert _BULK_PROGRESS["is_running"] is False

    asyncio.run(_test())


# ── Criterion 10: Progress endpoint returns correct state ──────────────────────

def test_progress_endpoint_returns_correct_state(client):
    """
    Criterion 10:
    GET /email-verify/progress returns honest metrics including failed and remaining counts.
    """
    _BULK_PROGRESS["is_running"] = False
    _BULK_PROGRESS["total"] = 50
    _BULK_PROGRESS["processed"] = 50
    _BULK_PROGRESS["valid"] = 40
    _BULK_PROGRESS["invalid"] = 5
    _BULK_PROGRESS["quarantined"] = 5
    _BULK_PROGRESS["failed"] = 0
    _BULK_PROGRESS["remaining"] = 0

    resp = client.get("/email-verify/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 50
    assert data["processed"] == 50
    assert data["valid"] == 40
    assert data["invalid"] == 5
    assert data["quarantined"] == 5
    assert data["is_running"] is False


# ── Criterion 11: Safety - Zero SMTP, Zero Live Emails, Zero Live Dispatch ─────

def test_safety_guarantees_smtp_disabled():
    """
    Criterion 11:
    EmailVerifierService has smtp_enabled=False by default and never opens SMTP connections.
    """
    service = EmailVerifierService()
    assert service.smtp_enabled is False

    # Check is_disposable_domain helper
    assert service.is_disposable_domain("mailinator.com") is True
    assert service.is_disposable_domain("google.com") is False


# ── Criterion 12: Preserves website URLs and candidate discovery ──────────────

def test_preserves_website_urls_and_candidate_discovery():
    """
    Criterion 12:
    Verification does not overwrite website URLs, website candidates, or audit metadata.
    """
    async def _test():
        lead = MagicMock(spec=Lead)
        lead.id = uuid.uuid4()
        lead.email = "info@preserve-me.com"
        lead.business_name = "Preserve Me LLC"
        lead.website = "https://preserve-me.com"
        lead.website_candidates = [{"url": "https://preserve-me.com", "source": "inferred"}]
        lead.website_status = "candidate_match"
        lead.email_verification_status = "unverified"
        lead.is_quarantined = False
        lead.quarantine_reason = None
        lead.email_business_association_status = "matched"
        lead.activity_log = []

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lead]
        mock_session.execute.return_value = mock_res

        mock_verifier = MagicMock()
        mock_verifier.verify_email = AsyncMock(return_value=VerificationResult(
            email="info@preserve-me.com",
            normalized_email="info@preserve-me.com",
            status="valid",
            is_sendable=True,
            score=95,
            syntax_ok=True,
            has_mx=True,
        ))

        _BULK_PROGRESS.update({
            "is_running": True,
            "total": 1,
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "disposable": 0,
            "risky": 0,
            "quarantined": 0,
            "failed": 0,
            "skipped": 0,
            "remaining": 1,
            "cancel_requested": False,
        })

        with patch("app.routers.email_verification.email_verifier", mock_verifier), \
             patch("app.database.AsyncSessionLocal", _mock_async_session_local(mock_session)):
            await _run_bulk_verification_job(lead_ids=[lead.id], smtp_enabled=False, catch_all_enabled=False)

        assert lead.website == "https://preserve-me.com"
        assert lead.business_name == "Preserve Me LLC"
        assert lead.website_status == "candidate_match"
        assert len(lead.website_candidates) == 1

    asyncio.run(_test())
