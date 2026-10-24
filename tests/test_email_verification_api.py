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
from app.models import Lead


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
def admin_headers():
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    token = jwt.encode(
        {"sub": "admin", "role": "admin", "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(auth_headers):
    c = TestClient(app)
    c.headers.update(auth_headers)
    return c


@pytest.fixture
def unauthenticated_client():
    return TestClient(app)


# ── Task 1 Verification Gate Security Tests ───────────────────────────────────

def test_unauthenticated_access_rejected_401(unauthenticated_client):
    """Verify all sensitive email-verification endpoints reject requests without token with 401."""
    fake_id = uuid.uuid4()
    endpoints = [
        ("GET", "/email-verify/leads"),
        ("GET", "/email-verify/stats"),
        ("GET", "/email-verify/progress"),
        ("POST", "/email-verify/single", {"email": "test@example.com"}),
        ("POST", f"/email-verify/lead/{fake_id}", {}),
        ("POST", f"/email-verify/reverify/{fake_id}", {}),
        ("POST", "/email-verify/bulk", {"limit": 10}),
        ("POST", "/email-verify/cancel", {}),
    ]

    for method, path, *payload in endpoints:
        json_data = payload[0] if payload else None
        if method == "GET":
            resp = unauthenticated_client.get(path)
        else:
            resp = unauthenticated_client.post(path, json=json_data)
        assert resp.status_code == 401, f"Expected 401 for {method} {path}, got {resp.status_code}"
        assert "authentication required" in resp.json().get("detail", "").lower() or "not authenticated" in resp.json().get("detail", "").lower()


def test_invalid_and_expired_token_rejected_401(unauthenticated_client):
    """Verify invalid, expired, or malformed tokens are strictly rejected with 401."""
    # 1. Malformed scheme
    resp1 = unauthenticated_client.get("/email-verify/leads", headers={"Authorization": "Basic dummy"})
    assert resp1.status_code == 401
    assert "invalid authorization scheme" in resp1.json()["detail"].lower()

    # 2. Garbage token
    resp2 = unauthenticated_client.get("/email-verify/leads", headers={"Authorization": "Bearer bad.token.garbage"})
    assert resp2.status_code == 401
    assert "invalid or expired token" in resp2.json()["detail"].lower()

    # 3. Expired token
    past_exp = datetime.now(timezone.utc) - timedelta(minutes=15)
    expired_token = jwt.encode(
        {"sub": "operator", "role": "operator", "exp": past_exp},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp3 = unauthenticated_client.get("/email-verify/leads", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp3.status_code == 401
    assert "invalid or expired token" in resp3.json()["detail"].lower()

    # 4. Token signed with wrong secret
    wrong_secret_token = jwt.encode(
        {"sub": "operator", "role": "operator", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        "wrong_secret_key_that_is_at_least_32_characters_long",
        algorithm=settings.JWT_ALGORITHM,
    )
    resp4 = unauthenticated_client.get("/email-verify/leads", headers={"Authorization": f"Bearer {wrong_secret_token}"})
    assert resp4.status_code == 401

    # 5. Token missing subject claim
    no_sub_token = jwt.encode(
        {"role": "operator", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp5 = unauthenticated_client.get("/email-verify/leads", headers={"Authorization": f"Bearer {no_sub_token}"})
    assert resp5.status_code == 401
    assert "missing required subject claim" in resp5.json()["detail"].lower()


def test_unauthorized_role_rejected_403(unauthenticated_client):
    """Verify authenticated users with non-operator/non-admin roles (e.g. viewer) are rejected with 403."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    viewer_token = jwt.encode(
        {"sub": "viewer_user", "role": "viewer", "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    headers = {"Authorization": f"Bearer {viewer_token}"}
    resp = unauthenticated_client.get("/email-verify/leads", headers=headers)
    assert resp.status_code == 403
    assert "insufficient permissions" in resp.json()["detail"].lower()


def test_authorized_operator_and_admin_allowed_200(unauthenticated_client, auth_headers, admin_headers):
    """Verify both operator and admin roles are granted access."""
    from app.database import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar.return_value = 5
        mock_res = MagicMock()
        mock_res.all.return_value = [("valid", 5), ("unverified", 5)]
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp_op = unauthenticated_client.get("/email-verify/stats", headers=auth_headers)
        assert resp_op.status_code == 200

        resp_admin = unauthenticated_client.get("/email-verify/stats", headers=admin_headers)
        assert resp_admin.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Functional Tests ──────────────────────────────────────────────────────────

def test_single_verify_api_valid(client):
    """Test POST /email-verify/single with a valid email."""
    mock_res = VerificationResult(
        email="test@example.com",
        normalized_email="test@example.com",
        status="valid",
        is_sendable=True,
        score=100,
        syntax_ok=True,
        has_mx=True,
        mx_records=["mail.example.com"],
        duration_ms=12.5,
    )

    with patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_res
        resp = client.post("/email-verify/single", json={"email": "test@example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["status"] == "valid"
        assert data["is_sendable"] is True
        assert data["score"] == 100
        assert data["smtp_check"]["status"] == "not_checked"


def test_single_verify_api_disposable(client):
    """Test POST /email-verify/single with disposable email."""
    mock_res = VerificationResult(
        email="bad@mailinator.com",
        normalized_email="bad@mailinator.com",
        status="disposable",
        is_sendable=False,
        score=10,
        syntax_ok=True,
        is_disposable=True,
        exclusion_reason="Disposable email domain",
    )

    with patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = mock_res
        resp = client.post("/email-verify/single", json={"email": "bad@mailinator.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disposable"
        assert data["is_sendable"] is False
        assert data["exclusion_reason"] == "Disposable email domain"


def test_single_verify_api_invalid_syntax(client):
    """Test POST /email-verify/single with malformed email."""
    resp = client.post("/email-verify/single", json={"email": "not-an-email"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "invalid"
    assert data["is_sendable"] is False
    assert data["syntax_ok"] is False


def test_single_verify_api_empty_input(client):
    """Empty email should return 422 or invalid result."""
    resp = client.post("/email-verify/single", json={"email": ""})
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["status"] == "invalid"
        assert data["is_sendable"] is False


def test_verify_lead_by_id_and_quarantine_transition(client):
    """Test verifying a lead and automatically managing quarantine status."""
    fake_id = uuid.uuid4()
    mock_lead = MagicMock(spec=Lead)
    mock_lead.id = fake_id
    mock_lead.email = "bad@throwaway.com"
    mock_lead.is_quarantined = False
    mock_lead.quarantine_reason = None

    mock_res = VerificationResult(
        email="bad@throwaway.com",
        normalized_email="bad@throwaway.com",
        status="disposable",
        is_sendable=False,
        score=10,
        syntax_ok=True,
        is_disposable=True,
        exclusion_reason="Disposable email domain",
    )

    from app.database import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_res
            resp = client.post(f"/email-verify/lead/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_quarantined"] is True
            assert "Disposable email domain" in data["quarantine_reason"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_reverify_lead_restores_quarantined_lead(client):
    """Test that a lead quarantined for verification is restored when verification succeeds."""
    fake_id = uuid.uuid4()
    mock_lead = MagicMock(spec=Lead)
    mock_lead.id = fake_id
    mock_lead.email = "fixed@example.com"
    mock_lead.is_quarantined = True
    mock_lead.quarantine_reason = "Email verification failed: disposable"
    mock_lead.email_business_association_status = "matched"

    mock_res = VerificationResult(
        email="fixed@example.com",
        normalized_email="fixed@example.com",
        status="valid",
        is_sendable=True,
        score=100,
        syntax_ok=True,
        has_mx=True,
    )

    from app.database import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_res
            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_quarantined"] is False
            assert data["quarantine_reason"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_email_verification_stats(client):
    """Test GET /email-verify/stats endpoint."""
    from app.database import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        # mock scalar calls: total_leads (150), quarantined (25), deliverable (100), pending_verification (25)
        mock_db.scalar.side_effect = [150, 25, 100, 25]
        # mock status distribution
        mock_res = MagicMock()
        mock_res.all.return_value = [
            ("valid", 100),
            ("invalid", 20),
            ("disposable", 5),
            ("unverified", 25),
        ]
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_leads"] == 150
        assert data["deliverable"] == 100
        assert data["quarantined"] == 25
        assert data["valid"] == 100
        assert data["invalid"] == 20
        assert data["disposable"] == 5
        assert data["unverified"] == 25
        assert data["active_pool"] == 100  # Only confirmed deliverable leads, not unverified
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_email_verification_leads_endpoint(client):
    """Test GET /email-verify/leads returns leads with deliverability and quarantine metadata."""
    from app.database import get_db

    lead_id = uuid.uuid4()
    mock_lead = MagicMock(spec=Lead)
    mock_lead.id = lead_id
    mock_lead.business_name = "Acme Corp"
    mock_lead.email = "contact@acmecorp.com"
    mock_lead.website = "https://acmecorp.com"
    mock_lead.email_verification_status = "valid"
    mock_lead.email_verification_details = {"score": 95, "is_sendable": True, "has_mx": True}
    mock_lead.is_quarantined = False
    mock_lead.quarantine_reason = None
    mock_lead.email_verified_at = datetime.now(timezone.utc)

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar.return_value = 1
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_lead]
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/leads?view=active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == str(lead_id)
        assert item["email"] == "contact@acmecorp.com"
        assert item["verification_status"] == "valid"
        assert item["is_quarantined"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_bulk_verify_leads_limit_clamp(client):
    """Test POST /email-verify/bulk clamps limit and respects bounds."""
    # Test exceeding max limit > 500 should fail validation (422)
    resp = client.post("/email-verify/bulk", json={"limit": 600})
    assert resp.status_code == 422


def test_get_bulk_progress(client):
    """Test GET /email-verify/progress returns status dictionary."""
    resp = client.get("/email-verify/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data
    assert "processed" in data
    assert "total" in data


def test_reverify_lead_with_unresolved_association_does_not_unquarantine(client):
    """Test that a valid verification result CANNOT unquarantine a lead with unresolved association."""
    fake_id = uuid.uuid4()
    mock_lead = MagicMock(spec=Lead)
    mock_lead.id = fake_id
    mock_lead.email = "mismatched@example.com"
    mock_lead.is_quarantined = True
    mock_lead.quarantine_reason = "Email verification failed: disposable"
    mock_lead.email_business_association_status = "mismatched_source"

    mock_res = VerificationResult(
        email="mismatched@example.com",
        normalized_email="mismatched@example.com",
        status="valid",
        is_sendable=True,
        score=100,
        syntax_ok=True,
        has_mx=True,
    )

    from app.database import get_db

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_res
            resp = client.post(f"/email-verify/reverify/{fake_id}")
            assert resp.status_code == 200
            data = resp.json()
            # Must REMAIN quarantined because association is mismatched_source!
            assert data["is_quarantined"] is True
            assert mock_lead.is_quarantined is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_run_bulk_verification_job_worker_execution():
    """Verify _run_bulk_verification_job processes leads, bounds concurrency, and completes with is_running=False."""
    import asyncio
    from app.routers.email_verification import _run_bulk_verification_job, _BULK_PROGRESS

    test_ids = [uuid.uuid4() for _ in range(10)]
    mock_leads = {}
    for tid in test_ids:
        lead = MagicMock(spec=Lead)
        lead.id = tid
        lead.email = f"lead_{tid.hex[:6]}@example.com"
        lead.is_quarantined = False
        lead.quarantine_reason = None
        lead.email_business_association_status = "matched"
        mock_leads[tid] = lead

    mock_res = VerificationResult(
        email="test@example.com",
        normalized_email="test@example.com",
        status="valid",
        is_sendable=True,
        score=95,
        syntax_ok=True,
        has_mx=True,
    )

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, model, lead_id):
            return mock_leads.get(lead_id)
        async def commit(self):
            pass

    _BULK_PROGRESS.update({
        "is_running": True,
        "job_id": "test-job-123",
        "total": len(test_ids),
        "processed": 0,
        "valid": 0,
        "invalid": 0,
        "disposable": 0,
        "risky": 0,
        "quarantined": 0,
        "cancel_requested": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    })

    async def _run():
        with patch("app.database.AsyncSessionLocal", side_effect=FakeSession), \
             patch("app.routers.email_verification.email_verifier.verify_email", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_res
            await _run_bulk_verification_job(
                lead_ids=test_ids,
                smtp_enabled=False,
                catch_all_enabled=False,
            )

    asyncio.run(_run())

    assert _BULK_PROGRESS["is_running"] is False
    assert _BULK_PROGRESS["processed"] == 10
    assert _BULK_PROGRESS["valid"] == 10
    assert _BULK_PROGRESS["completed_at"] is not None


def test_run_bulk_verification_job_cancellation():
    """Verify _run_bulk_verification_job honors cancellation and cleans up cleanly."""
    import asyncio
    from app.routers.email_verification import _run_bulk_verification_job, _BULK_PROGRESS

    test_ids = [uuid.uuid4() for _ in range(5)]
    _BULK_PROGRESS.update({
        "is_running": True,
        "job_id": "test-job-cancel",
        "total": len(test_ids),
        "processed": 0,
        "valid": 0,
        "invalid": 0,
        "disposable": 0,
        "risky": 0,
        "quarantined": 0,
        "cancel_requested": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    })

    asyncio.run(_run_bulk_verification_job(
        lead_ids=test_ids,
        smtp_enabled=False,
        catch_all_enabled=False,
    ))

    assert _BULK_PROGRESS["is_running"] is False
    assert _BULK_PROGRESS["processed"] == 5
    assert _BULK_PROGRESS["completed_at"] is not None

