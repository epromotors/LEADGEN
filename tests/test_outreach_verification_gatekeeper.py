import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import (
    Lead,
    LeadStatus,
    Campaign,
    CampaignStatus,
    Audit,
    AuditStatus,
    CampaignEmailLog,
)
from app.engines.outreach_engine import _run_campaign_worker


def test_pre_send_gatekeeper_skips_quarantined_lead():
    """Verify that an already-quarantined lead is skipped immediately without calling provider."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())

    campaign = Campaign(
        id=uuid.UUID(camp_id),
        name="Test Safety Campaign",
        status=CampaignStatus.sending,
        subject_template="Audit for {business_name}",
        template="Hello {business_name}",
        pending_lead_ids=[lead_id],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )

    lead = Lead(
        id=uuid.UUID(lead_id),
        business_name="Acme Corp",
        email="info@acme.com",
        website="https://acme.com",
        status=LeadStatus.new,
        is_quarantined=True,
        quarantine_reason="Disposable email domain",
        email_verification_status="disposable",
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

    fake_smtp = {
        "email": "outreach@testagency.com",
        "user": "outreach@testagency.com",
        "password": "secret_password",
        "host": "smtp.testagency.com",
        "port": 587,
        "daily_limit": 100,
    }

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
             patch("smtplib.SMTP") as mock_smtp, \
             patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

            await _run_campaign_worker(camp_id)

            # Provider must NEVER be called
            assert mock_send.call_count == 0
            assert mock_smtp.call_count == 0
            assert mock_smtp_ssl.call_count == 0
            # Skipped count must be incremented
            assert campaign.skipped_count >= 1
            assert campaign.sent_count == 0

            # Verify CampaignEmailLog was added with skipped status
            added_logs = [call[0][0] for call in mock_db.add.call_args_list if isinstance(call[0][0], CampaignEmailLog)]
            assert len(added_logs) == 1
            assert added_logs[0].status == "skipped"
            assert "Disposable email domain" in added_logs[0].message

    asyncio.run(_run())


def test_pre_send_gatekeeper_quarantines_and_skips_unverified_lead():
    """Verify that an unverified lead is quarantined on-the-fly and skipped without calling provider."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())

    campaign = Campaign(
        id=uuid.UUID(camp_id),
        name="Test Safety Campaign",
        status=CampaignStatus.sending,
        subject_template="Audit for {business_name}",
        template="Hello {business_name}",
        pending_lead_ids=[lead_id],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )

    lead = Lead(
        id=uuid.UUID(lead_id),
        business_name="Beta Corp",
        email="contact@betacorp.org",
        website="https://betacorp.org",
        status=LeadStatus.new,
        is_quarantined=False,
        quarantine_reason=None,
        email_verification_status="unverified",
        email_business_association_status="matched",
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

    fake_smtp = {
        "email": "outreach@testagency.com",
        "user": "outreach@testagency.com",
        "password": "secret_password",
        "host": "smtp.testagency.com",
        "port": 587,
        "daily_limit": 100,
    }

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
             patch("smtplib.SMTP") as mock_smtp, \
             patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

            await _run_campaign_worker(camp_id)

            # Provider must NEVER be called
            assert mock_send.call_count == 0
            assert mock_smtp.call_count == 0
            assert mock_smtp_ssl.call_count == 0
            # Lead must be marked quarantined
            assert lead.is_quarantined is True
            assert "Email verification failed or unverified" in lead.quarantine_reason
            # Skipped count incremented, sent count 0
            assert campaign.skipped_count >= 1
            assert campaign.sent_count == 0

            added_logs = [call[0][0] for call in mock_db.add.call_args_list if isinstance(call[0][0], CampaignEmailLog)]
            assert len(added_logs) == 1
            assert added_logs[0].status == "skipped"
            assert "unverified" in added_logs[0].message

    asyncio.run(_run())


def test_pre_send_gatekeeper_allows_valid_verified_lead():
    """Verify that a valid, verified lead proceeds to provider send."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())

    campaign = Campaign(
        id=uuid.UUID(camp_id),
        name="Test Safety Campaign",
        status=CampaignStatus.sending,
        subject_template="Audit for {business_name}",
        template="Hello {business_name}",
        pending_lead_ids=[lead_id],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )

    lead = Lead(
        id=uuid.UUID(lead_id),
        business_name="Valid Corp",
        email="hello@validcorp.com",
        website="https://validcorp.com",
        status=LeadStatus.new,
        is_quarantined=False,
        quarantine_reason=None,
        email_verification_status="valid",
        email_business_association_status="matched",
    )

    mock_audit = MagicMock(spec=Audit)
    mock_audit.error_message = None

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_audit), scalar=MagicMock(return_value=0)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {
        "email": "outreach@testagency.com",
        "user": "outreach@testagency.com",
        "password": "secret_password",
        "host": "smtp.testagency.com",
        "port": 587,
        "daily_limit": 100,
    }

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):

            await _run_campaign_worker(camp_id)

            # Provider was called
            assert mock_send.call_count == 1
            # Sent count must be incremented
            assert campaign.sent_count == 1
            assert campaign.skipped_count == 0

            added_logs = [call[0][0] for call in mock_db.add.call_args_list if isinstance(call[0][0], CampaignEmailLog)]
            assert len(added_logs) == 1
            assert added_logs[0].status == "sent"

    asyncio.run(_run())


def test_create_campaign_blocks_unverified_leads():
    """Verify that create_campaign API endpoint rejects unverified or quarantined leads."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    lead_id = uuid.uuid4()
    client = TestClient(app)

    async def override_get_db():
        mock_db = AsyncMock()
        # Mock ready_result to return empty set (blocked)
        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_db.execute.return_value = mock_res
        yield mock_db

    from app.routers.auth import create_access_token
    auth_headers = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'role': 'admin'})}"}

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={
                "name": "Test Campaign",
                "lead_ids": [str(lead_id)],
                "template": "Hello",
                "subject_template": "Proposal",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "not campaign-ready" in resp.json()["detail"]
        assert "valid" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
