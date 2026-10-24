import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
import smtplib
from unittest.mock import AsyncMock, MagicMock, patch

import concurrent.futures

from app.config import Settings
from app.models import Lead, Campaign, CampaignStatus, Audit, AuditStatus
from app.engines.outreach_engine import (
    _send_email_sync,
    classify_smtp_error,
    _run_campaign_worker,
)
from app.services.email_verifier_service import EmailVerifierService


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ─── 1. Correct Username, Authorized Sender, and Matching Configuration ─────────

def test_correct_username_and_matching_sender_config():
    """Verify clean send when authenticated mailbox matches sender identity."""
    account = {
        "email": "info@tebsolutions.in",
        "login_email": "info@tebsolutions.in",
        "smtp_host": "smtp.hostinger.com",
        "smtp_port": 465,
        "password": "correct_password",
        "sender_name": "Ashish",
    }

    mock_server = MagicMock()
    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_smtp_ssl.return_value.__enter__.return_value = mock_server

        success, err = _send_email_sync(
            account=account,
            to_email="epromotors@gmail.com",
            subject="Test subject",
            html_body="<p>Test</p>",
            plain_body="Test",
        )

        assert success is True
        assert err == ""
        mock_server.login.assert_called_once_with("info@tebsolutions.in", "correct_password")
        # sendmail must be called with sender envelope address matching account email
        args, _ = mock_server.sendmail.call_args
        assert args[0] == "info@tebsolutions.in"
        assert args[1] == "epromotors@gmail.com"


# ─── 2. Mismatched Authenticated Mailbox and Envelope Sender ─────────────────────

def test_mismatched_authenticated_mailbox_and_envelope_sender():
    """When login_email differs from sender_email and server rejects sender ownership."""
    account = {
        "email": "services@tebsolutions.in",
        "login_email": "info@tebsolutions.in",
        "smtp_host": "smtp.hostinger.com",
        "smtp_port": 465,
        "password": "dummy_password",
        "sender_name": "Ashish",
    }

    exc = smtplib.SMTPSenderRefused(
        553,
        b"5.7.1 <services@tebsolutions.in>: Sender address rejected: not owned by user info@tebsolutions.in",
        "services@tebsolutions.in",
    )

    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = exc
        mock_smtp_ssl.return_value.__enter__.return_value = mock_server

        success, err = _send_email_sync(
            account=account,
            to_email="epromotors@gmail.com",
            subject="Test",
            html_body="<p>Test</p>",
            plain_body="Test",
        )

        assert success is False
        assert "553" in err
        assert "not owned by or authorized for the authenticated mailbox" in err


# ─── 3. Unauthorized Sender Alias ─────────────────────────────────────────────

def test_unauthorized_sender_alias():
    """Verify unauthorized sender alias is categorized as sender_configuration failure."""
    raw_error = "553 5.7.1 <alias@tebsolutions.in>: Sender address rejected: not owned by user info@tebsolutions.in"
    info = classify_smtp_error(raw_error)

    assert info["category"] == "sender_configuration"
    assert info["is_permanent_sender_failure"] is True
    assert info["code"] == 553
    assert "Hostinger" in info["sanitized_message"]


# ─── 4. Incorrect or Malformed Sender Configuration ───────────────────────────

def test_incorrect_or_malformed_sender_configuration():
    """Verify malformed JSON or incomplete account entries are safely filtered without crashes."""
    s = Settings(
        DATABASE_URL="postgresql+psycopg://dummy:dummy@localhost/db",
        JWT_SECRET="x" * 32,
        SMTP_SENDERS='['
        '{"email": "valid@tebsolutions.in", "smtp_host": "smtp.hostinger.com", "password": "pass", "smtp_port": "465"},'
        '{"email": "", "smtp_host": "smtp.hostinger.com", "password": "pass"},'  # missing email
        '{"email": "nohost@tebsolutions.in", "password": "pass"},'               # missing host
        '{"email": "nopass@tebsolutions.in", "smtp_host": "smtp.hostinger.com"},'  # missing pass
        '"not_a_dict",'                                                          # invalid entry
        '{"email": "badport@tebsolutions.in", "smtp_host": "smtp.hostinger.com", "password": "pass", "smtp_port": "invalid_port"}'
        ']'
    )
    accounts = s.get_smtp_accounts()
    assert len(accounts) == 2
    assert accounts[0]["email"] == "valid@tebsolutions.in"
    assert accounts[0]["smtp_port"] == 465
    assert accounts[1]["email"] == "badport@tebsolutions.in"
    assert accounts[1]["smtp_port"] == 465  # fallback to default 465


# ─── 5. SMTP 553 Classification as Sender-Configuration Error ─────────────────

def test_smtp_553_classification_as_sender_configuration_error():
    """Verify exact Hostinger 553 rejection string is classified as sender configuration error."""
    hostinger_err = "553 5.7.1 <info@tebsolutions.in>: Sender address rejected: not owned by user info@tebsolutions.in"
    info = classify_smtp_error(hostinger_err)

    assert info["category"] == "sender_configuration"
    assert info["is_permanent_sender_failure"] is True
    assert info["code"] == 553
    assert "Hostinger" in info["sanitized_message"]


# ─── 6. Sender Failure Does Not Mark Recipient Invalid or Quarantined ─────────

def test_sender_failure_does_not_mark_recipient_invalid_or_quarantined():
    """Sender failure (553) must NOT alter recipient verification status or quarantine the lead."""
    async def _test():
        lead_id = uuid.uuid4()
        lead = MagicMock(spec=Lead)
        lead.id = lead_id
        lead.email = "epromotors@gmail.com"
        lead.business_name = "Epromotors"
        lead.website = "https://epromotors.com"
        lead.last_emailed_at = None
        lead.is_quarantined = False
        lead.quarantine_reason = None
        lead.email_verification_status = "valid"
        lead.email_business_association_status = "matched"

        campaign = MagicMock(spec=Campaign)
        campaign.id = uuid.uuid4()
        campaign.status = CampaignStatus.draft
        campaign.subject_template = None
        campaign.lead_ids = [str(lead_id)]
        campaign.pending_lead_ids = [str(lead_id)]
        campaign.sent_count = 0
        campaign.skipped_count = 0
        campaign.failed_count = 0

        mock_db = AsyncMock()
        mock_db.get.side_effect = lambda model, id_: campaign if model == Campaign else lead
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar=MagicMock(return_value=0),
            scalar_one_or_none=MagicMock(return_value=None),
        ))

        fake_account = {
            "email": "info@tebsolutions.in",
            "smtp_host": "smtp.hostinger.com",
            "smtp_port": 465,
            "password": "dummy",
            "daily_limit": 1000,
        }

        with patch("app.engines.outreach_engine.AsyncSessionLocal") as mock_session_local, \
             patch.object(Settings, "get_smtp_accounts", return_value=[fake_account]), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(False, "553 5.7.1 <info@tebsolutions.in>: Sender address rejected: not owned by user info@tebsolutions.in")):

            mock_session_local.return_value.__aenter__.return_value = mock_db

            await _run_campaign_worker(str(campaign.id))

            # 1. Recipient lead must NOT be marked invalid
            assert lead.email_verification_status == "valid"
            # 2. Recipient lead must NOT be quarantined
            assert lead.is_quarantined is False
            assert lead.quarantine_reason is None
            # 3. Campaign must record failure and pause
            assert campaign.failed_count == 1
            assert campaign.sent_count == 0
            assert campaign.status == CampaignStatus.paused

    _run_async(_test())


# ─── 7. Permanent Sender Rejections Do Not Trigger Repetitive Retries ──────────

def test_permanent_sender_rejections_do_not_trigger_repetitive_retries():
    """When a 553 permanent sender rejection happens on lead 1, campaign pauses immediately without retrying leads 2 and 3."""
    async def _test():
        lead1_id, lead2_id, lead3_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        def get_lead(model, id_):
            if model == Campaign:
                return campaign
            m = MagicMock(spec=Lead)
            m.id = id_
            m.email = f"lead_{id_}@example.com"
            m.business_name = f"Business {id_}"
            m.website = "https://example.com"
            m.last_emailed_at = None
            m.is_quarantined = False
            m.email_verification_status = "valid"
            m.email_business_association_status = "matched"
            return m

        campaign = MagicMock(spec=Campaign)
        campaign.id = uuid.uuid4()
        campaign.status = CampaignStatus.draft
        campaign.subject_template = None
        campaign.lead_ids = [str(lead1_id), str(lead2_id), str(lead3_id)]
        campaign.pending_lead_ids = [str(lead1_id), str(lead2_id), str(lead3_id)]
        campaign.sent_count = 0
        campaign.failed_count = 0
        campaign.skipped_count = 0

        mock_db = AsyncMock()
        mock_db.get.side_effect = get_lead
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar=MagicMock(return_value=0),
            scalar_one_or_none=MagicMock(return_value=None),
        ))

        fake_account = {
            "email": "info@tebsolutions.in",
            "smtp_host": "smtp.hostinger.com",
            "smtp_port": 465,
            "password": "dummy",
            "daily_limit": 1000,
        }

        send_call_count = 0

        def mock_send(*args, **kwargs):
            nonlocal send_call_count
            send_call_count += 1
            return False, "553 5.7.1 <info@tebsolutions.in>: Sender address rejected: not owned by user info@tebsolutions.in"

        with patch("app.engines.outreach_engine.AsyncSessionLocal") as mock_session_local, \
             patch.object(Settings, "get_smtp_accounts", return_value=[fake_account]), \
             patch("app.engines.outreach_engine._send_email_sync", side_effect=mock_send):

            mock_session_local.return_value.__aenter__.return_value = mock_db

            await _run_campaign_worker(str(campaign.id))

            # Crucial: Send must be called ONLY ONCE for lead 1; leads 2 and 3 must NOT be attempted!
            assert send_call_count == 1
            assert campaign.failed_count == 1
            assert campaign.status == CampaignStatus.paused
            # Remaining leads must be preserved in pending_lead_ids
            assert len(campaign.pending_lead_ids) == 2

    _run_async(_test())


# ─── 8. No Credentials in Logs or Error Output ────────────────────────────────

def test_no_credentials_appear_in_logs_or_api_responses():
    """Verify classify_smtp_error sanitizes passwords or authorization secrets."""
    leak_string = "SMTP auth rejected user=info@tebsolutions.in password='SuperSecretPassword123!' with 535"
    info = classify_smtp_error(leak_string)

    assert "SuperSecretPassword123!" not in info["sanitized_message"]
    assert "SuperSecretPassword123!" not in info["raw_sanitized"]
    assert "***" in info["raw_sanitized"]
    assert info["category"] == "authentication"


# ─── 9. Syntax/DNS Success Is Not Displayed as Guaranteed Deliverability ──────

def test_syntax_dns_success_is_not_displayed_as_guaranteed_mailbox_deliverability():
    """When SMTP probing is disabled, verify_email does NOT claim 100% deliverability or confirmed mailbox."""
    async def _test():
        service = EmailVerifierService(cache_ttl_seconds=60)

        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com"]

            res = await service.verify_email("user@example.com", smtp_probe_enabled=False)

            assert res.status == "valid"
            assert res.is_sendable is True
            assert res.mailbox_confirmed is False
            assert res.score == 85  # Capped at 85/100 without live mailbox probe
            assert res.smtp_check["status"] == "not_checked"
            assert "not confirmed" in res.smtp_check["message"].lower()
            assert "mailbox existence not confirmed" in res.diagnostic_summary.lower()

    _run_async(_test())


# ─── 10. SMTP-Disabled Operation Opens No SMTP Connection ────────────────────

def test_smtp_disabled_operation_opens_no_smtp_connection():
    """Verify that verify_email with default smtp_probe_enabled=False never invokes any socket/SMTP connection."""
    async def _test():
        service = EmailVerifierService(cache_ttl_seconds=60)

        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx, \
             patch("socket.socket") as mock_socket, \
             patch("socket.create_connection") as mock_create_conn:

            mock_mx.return_value = ["mail.example.com"]

            res = await service.verify_email("epromotors@gmail.com", smtp_probe_enabled=False)

            mock_socket.assert_not_called()
            mock_create_conn.assert_not_called()
            assert res.smtp_check["status"] == "not_checked"
            assert res.has_mx is True

    _run_async(_test())
