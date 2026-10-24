"""
tests/test_api_authorization_matrix.py

Verification gate test suite for Task 1:
Validates authorization matrix across all sensitive and public endpoints:
- No token (401)
- Invalid or expired token (401)
- Authenticated but unauthorized role (403)
- Authorized operator or administrator (200 / business logic status)
- Truly public health/login endpoints remain accessible without auth
- Unauthorized state mutations never alter the database
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
from app.models import Lead, Campaign, CampaignStatus, EmailAssociationStatus


def _token(role: str, sub: str = "testuser", expire_delta: timedelta = timedelta(minutes=15)) -> str:
    exp = datetime.now(timezone.utc) + expire_delta
    return jwt.encode({"sub": sub, "role": role, "exp": exp}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.fixture
def client():
    return TestClient(app)


# ─── 1. Truly Public Endpoints Remain Accessible Without Auth ─────────────────

def test_public_health_and_info_endpoints(client):
    """GET / and GET /health must remain public."""
    r1 = client.get("/")
    assert r1.status_code == 200
    assert r1.json()["status"] == "online"

    r2 = client.get("/health")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"


def test_public_frontend_log_sink(client):
    """POST /api/logs/frontend is an error sink and does not require auth."""
    r = client.post("/api/logs/frontend", json={"level": "info", "message": "UI mounted"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_public_auth_login(client):
    """POST /auth/login must be publicly callable to acquire tokens."""
    # Invalid credentials
    r_bad = client.post("/auth/login", json={"username": "wrong", "password": "bad"})
    assert r_bad.status_code == 401

    # Valid credentials
    with patch.object(settings, "ADMIN_PASSWORD", "test_admin_password_min_32_chars_123"):
        r_good = client.post("/auth/login", json={"username": settings.ADMIN_USERNAME, "password": "test_admin_password_min_32_chars_123"})
        assert r_good.status_code == 200
        data = r_good.json()
        assert "access_token" in data
        assert data["token_type"].lower() == "bearer"


# ─── 2. Sensitive Endpoints Reject Missing or Invalid Tokens (401) ────────────

SENSITIVE_ENDPOINTS = [
    ("GET", "/email-verify/leads"),
    ("GET", "/email-verify/stats"),
    ("POST", "/email-verify/single", {"email": "hello@example.com"}),
    ("GET", "/leads/"),
    ("POST", "/leads/upload", None),
    ("GET", "/leads/discovery/jobs/job_1/export"),
    ("GET", "/campaigns/"),
    ("POST", "/campaigns/", {"name": "c", "lead_ids": []}),
    ("GET", "/replies/converted"),
    ("GET", "/replies/all-replies"),
    ("POST", "/replies/check", None),
    ("GET", "/email-review/"),
    ("POST", "/email-review/scan", None),
    ("GET", "/activity/"),
    ("GET", "/activity/metrics"),
]


@pytest.mark.parametrize("method,path,payload", [(m, p, data if len(rest) else None) for m, p, *rest in SENSITIVE_ENDPOINTS for data in (rest if rest else [None])])
def test_sensitive_endpoints_reject_unauthenticated(client, method, path, payload):
    """Every sensitive route must return 401 when called without Authorization header."""
    if method == "GET":
        resp = client.get(path)
    else:
        resp = client.post(path, json=payload) if payload is not None else client.post(path)
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"
    assert "authentication required" in resp.json().get("detail", "").lower()


def test_sensitive_endpoints_reject_expired_and_forged_tokens(client):
    """Tokens that are expired or signed with wrong secret must return 401."""
    # Expired token
    expired = _token("admin", expire_delta=-timedelta(minutes=5))
    r_exp = client.get("/email-verify/leads", headers={"Authorization": f"Bearer {expired}"})
    assert r_exp.status_code == 401
    assert "invalid or expired token" in r_exp.json()["detail"].lower()

    # Wrong secret
    forged = jwt.encode(
        {"sub": "admin", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
        "completely_wrong_secret_key_1234567890",
        algorithm=settings.JWT_ALGORITHM,
    )
    r_forged = client.get("/email-verify/leads", headers={"Authorization": f"Bearer {forged}"})
    assert r_forged.status_code == 401


# ─── 3. Unauthorized Roles Are Rejected (403) ─────────────────────────────────

def test_unauthorized_role_rejected_403(client):
    """Users with non-operator roles (e.g., 'viewer') must receive 403 Forbidden."""
    viewer_token = _token(role="viewer", sub="read_only_user")
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # Attempt to read leads
    r_leads = client.get("/email-verify/leads", headers=headers)
    assert r_leads.status_code == 403
    assert "insufficient permissions" in r_leads.json()["detail"].lower()

    # Attempt to trigger bulk verify
    r_bulk = client.post("/email-verify/bulk", json={"limit": 50}, headers=headers)
    assert r_bulk.status_code == 403

    # Attempt to export
    r_exp = client.get("/leads/discovery/jobs/job_1/export", headers=headers)
    assert r_exp.status_code == 403

    # Attempt to list campaigns
    r_camp = client.get("/campaigns/", headers=headers)
    assert r_camp.status_code == 403


# ─── 4. Authorized Roles (Operator & Admin) Are Granted Access ────────────────

def test_authorized_operator_and_admin_access(client):
    """Principals with 'operator' and 'admin' roles successfully access protected routes."""
    op_token = _token(role="operator", sub="operator@tebsolutions.in")
    admin_token = _token(role="admin", sub="admin")

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar.return_value = 0
        mock_res = MagicMock()
        mock_res.all.return_value = []
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        # Operator access
        r_op = client.get("/email-verify/stats", headers={"Authorization": f"Bearer {op_token}"})
        assert r_op.status_code == 200

        # Admin access
        r_admin = client.get("/email-verify/stats", headers={"Authorization": f"Bearer {admin_token}"})
        assert r_admin.status_code == 200

        # Leads list
        r_leads = client.get("/leads/", headers={"Authorization": f"Bearer {op_token}"})
        assert r_leads.status_code == 200

        # Campaigns list
        r_camps = client.get("/campaigns/", headers={"Authorization": f"Bearer {op_token}"})
        assert r_camps.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 5. Unauthorized State Mutation Does Not Modify Database ─────────────────

def test_unauthorized_state_mutation_does_not_modify_database(client):
    """State-changing requests without auth fail closed without DB commits."""
    lead_id = uuid.uuid4()
    lead = Lead(
        id=lead_id,
        business_name="Sensitive Motors",
        email="owner@sensitivemotors.com",
        is_quarantined=True,
        quarantine_reason="unverified",
        email_business_association_status="unverified",
    )

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=lead)
    mock_db.commit = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        # Unauthenticated approval attempt
        r_app = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reviewer": "hacker", "reason": "unauthorized attempt"},
        )
        assert r_app.status_code == 401
        assert mock_db.commit.call_count == 0
        assert lead.is_quarantined is True
        assert lead.email_business_association_status == "unverified"

        # Unauthorized role approval attempt
        viewer_token = _token(role="viewer")
        r_viewer = client.post(
            f"/leads/{lead_id}/approve-association",
            json={"reviewer": "viewer", "reason": "unauthorized attempt"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert r_viewer.status_code == 403
        assert mock_db.commit.call_count == 0
        assert lead.is_quarantined is True
        assert lead.email_business_association_status == "unverified"
    finally:
        app.dependency_overrides.pop(get_db, None)
