import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.main import app
from app.models import Lead
from app.services.lead_discovery_service import lead_discovery_service


@pytest.fixture
def auth_headers():
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    token = jwt.encode(
        {"sub": "operator@leadgen.local", "role": "operator", "exp": expire},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(auth_headers):
    c = TestClient(app)
    c.headers.update(auth_headers)
    return c


def test_export_leads_csv_excludes_unverified_and_quarantined_leads():
    """Verify that export_leads_csv with sendable_only=True strictly excludes unverified, failed, or quarantined leads."""
    job_id = "test-job-semantics"
    leads = [
        {
            "id": "1",
            "business_name": "Valid Matched Co",
            "email": "hello@validmatched.com",
            "email_verification_status": "valid",
            "email_business_association_status": "matched",
            "is_quarantined": False,
        },
        {
            "id": "2",
            "business_name": "Unverified Co",
            "email": "info@unverified.com",
            "email_verification_status": "unverified",
            "email_business_association_status": "matched",
            "is_quarantined": False,
        },
        {
            "id": "3",
            "business_name": "None Status Co",
            "email": "contact@none.com",
            "email_verification_status": None,
            "email_business_association_status": "matched",
            "is_quarantined": False,
        },
        {
            "id": "4",
            "business_name": "Quarantined Co",
            "email": "bad@quarantined.com",
            "email_verification_status": "valid",
            "email_business_association_status": "matched",
            "is_quarantined": True,
            "quarantine_reason": "Manual hold",
        },
        {
            "id": "5",
            "business_name": "Invalid Email Co",
            "email": "invalid@bad.com",
            "email_verification_status": "invalid",
            "email_business_association_status": "matched",
            "is_quarantined": True,
        },
        {
            "id": "6",
            "business_name": "Mismatch Association Co",
            "email": "valid@mismatch.com",
            "email_verification_status": "valid",
            "email_business_association_status": "mismatch",
            "is_quarantined": False,
        },
    ]

    lead_discovery_service._jobs[job_id] = {
        "id": job_id,
        "discovered_leads": leads,
    }

    try:
        csv_data = lead_discovery_service.export_leads_csv(job_id, sendable_only=True)
        lines = [line.strip() for line in csv_data.strip().split("\n") if line.strip()]

        # Header + only Valid Matched Co
        assert len(lines) == 2, f"Expected header + 1 record, got: {lines}"
        assert "hello@validmatched.com" in lines[1]
        assert "info@unverified.com" not in csv_data
        assert "contact@none.com" not in csv_data
        assert "bad@quarantined.com" not in csv_data
        assert "invalid@bad.com" not in csv_data
        assert "valid@mismatch.com" not in csv_data
    finally:
        lead_discovery_service._jobs.pop(job_id, None)


def test_verification_leads_view_segregation(client):
    """Verify GET /email-verify/leads view parameter correctly segregates active deliverable vs unverified vs quarantined."""
    from app.database import get_db

    lead_valid = MagicMock(spec=Lead)
    lead_valid.id = uuid.uuid4()
    lead_valid.business_name = "Valid Lead"
    lead_valid.email = "valid@example.com"
    lead_valid.website = "https://example.com"
    lead_valid.email_verification_status = "valid"
    lead_valid.email_verification_details = {"is_sendable": True}
    lead_valid.is_quarantined = False
    lead_valid.quarantine_reason = None
    lead_valid.email_verified_at = datetime.now(timezone.utc)

    lead_unverified = MagicMock(spec=Lead)
    lead_unverified.id = uuid.uuid4()
    lead_unverified.business_name = "Unverified Lead"
    lead_unverified.email = "pending@example.com"
    lead_unverified.website = "https://pending.com"
    lead_unverified.email_verification_status = "unverified"
    lead_unverified.email_verification_details = None
    lead_unverified.is_quarantined = False
    lead_unverified.quarantine_reason = None
    lead_unverified.email_verified_at = None

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.scalar.return_value = 1
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [lead_unverified]
        mock_db.execute.return_value = mock_res
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/email-verify/leads?view=unverified")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["email"] == "pending@example.com"
        assert data["items"][0]["verification_status"] == "unverified"
        assert data["items"][0]["is_sendable"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
