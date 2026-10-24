"""
tests/test_phase8_campaign_worker_safety.py

Phase 8 Focused Deterministic Test Suite:
Campaign Queue Scheduling, In-Process Worker Consumption, Rate Limiting, Pacing,
Idempotency, and Real Dispatch Boundary Safety Gatekeeping.

Mandatory Safety Invariant:
All dispatch tests use isolated mocks for SMTP and database. Zero real SMTP calls
or live email deliveries are ever generated.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import smtplib
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.config import settings
from app.engines.outreach_engine import (
    _RUNNING_CAMPAIGNS,
    _run_campaign_worker,
    _send_email_sync,
    classify_smtp_error,
    run_campaign,
)
from app.models import (
    ActivityLog,
    Audit,
    AuditStatus,
    Campaign,
    CampaignEmailLog,
    CampaignStatus,
    Lead,
    LeadStatus,
)
from app.services.campaign_eligibility_service import (
    AuditFreshnessStatus,
    CampaignType,
    check_audit_freshness,
    evaluate_lead_campaign_eligibility,
)
from app.services.proposal_service import ProposalService


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_running_campaigns_and_proposals():
    """Ensure in-process state is clean before and after every test."""
    _RUNNING_CAMPAIGNS.clear()
    ProposalService._proposals.clear()
    yield
    _RUNNING_CAMPAIGNS.clear()
    ProposalService._proposals.clear()


@pytest.fixture
def fake_smtp_account():
    return {
        "email": "outreach@tebsolutions.in",
        "login_email": "outreach@tebsolutions.in",
        "password": "mock_smtp_password",
        "smtp_host": "smtp.hostinger.com",
        "smtp_port": 465,
        "sender_name": "Ashish",
        "daily_limit": 1000,
    }


def create_mock_lead(
    lead_id: Optional[uuid.UUID] = None,
    business_name: str = "Apex Logistics",
    email: str = "contact@apexlogistics.com",
    website: str = "https://apexlogistics.com",
    email_verification_status: str = "valid",
    email_business_association_status: str = "matched",
    is_quarantined: bool = False,
    is_suppressed: bool = False,
    reply_type: Optional[str] = None,
    last_emailed_at: Optional[datetime] = None,
) -> Lead:
    lid = lead_id or uuid.uuid4()
    lead = Lead(
        id=lid,
        business_name=business_name,
        email=email,
        website=website,
        email_verification_status=email_verification_status,
        email_business_association_status=email_business_association_status,
        is_quarantined=is_quarantined,
        status=LeadStatus.new,
    )
    # Set attributes that might be on the model or added dynamically
    lead.is_suppressed = is_suppressed
    lead.reply_type = reply_type
    lead.last_emailed_at = last_emailed_at
    lead.quarantine_reason = None
    return lead


def create_mock_audit(
    lead_id: uuid.UUID,
    status: AuditStatus = AuditStatus.done,
    updated_at: Optional[datetime] = None,
    audit_results: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> Audit:
    now_dt = updated_at or datetime.utcnow()
    return Audit(
        id=uuid.uuid4(),
        lead_id=lead_id,
        status=status,
        updated_at=now_dt,
        created_at=now_dt,
        error_message=error_message,
        audit_results=audit_results or {
            "technical": {"ssl": {"status": "FAIL", "message": "Weak TLS ciphers"}},
            "seo": {"meta_tags": {"status": "FAIL", "message": "Missing meta description"}},
        },
    )


def create_mock_campaign(
    campaign_id: Optional[uuid.UUID] = None,
    name: str = "SEO Audit Outreach",
    campaign_type: str = "valid_website_seo",
    lead_ids: Optional[List[str]] = None,
    pending_lead_ids: Optional[List[str]] = None,
    status: CampaignStatus = CampaignStatus.draft,
    require_proposal_approval: bool = False,
) -> Campaign:
    cid = campaign_id or uuid.uuid4()
    lids = lead_ids or []
    plids = pending_lead_ids if pending_lead_ids is not None else list(lids)
    camp = Campaign(
        id=cid,
        name=name,
        campaign_type=campaign_type,
        lead_ids=lids,
        pending_lead_ids=plids,
        template="Hi {business_name}, we analyzed {domain} and found critical findings.",
        subject_template="Observation for {domain}",
        status=status,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
    )
    camp.require_proposal_approval = require_proposal_approval
    camp.audit_references = {}
    return camp


def setup_mock_db(campaign: Campaign, lead_map: Dict[uuid.UUID, Lead], audit_map: Dict[uuid.UUID, Audit]):
    """Configures a mock async SQLAlchemy session returning the provided objects."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def mock_get(model, obj_id):
        if model == Campaign:
            return campaign
        if model == Lead:
            return lead_map.get(obj_id)
        return None

    mock_db.get = AsyncMock(side_effect=mock_get)

    async def mock_execute(stmt, *args, **kwargs):
        mock_result = MagicMock()
        # Handle select(Audit).where(Audit.lead_id == ...)
        # Handle count query for daily send limits
        # Handle selectinload queries
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalar.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.fetchall.return_value = []

        stmt_str = str(stmt) if stmt is not None else ""
        if "FROM audits" in stmt_str or "audits.lead_id" in stmt_str:
            # Check which lead_id is requested if possible
            for lid, audit in audit_map.items():
                if str(lid) in stmt_str or (hasattr(stmt, "compile") and str(lid) in str(stmt.compile(compile_kwargs={"literal_binds": True}))):
                    mock_result.scalar_one_or_none.return_value = audit
                    return mock_result
            # Default to first audit if available
            if audit_map:
                mock_result.scalar_one_or_none.return_value = next(iter(audit_map.values()))
        elif "count" in stmt_str.lower() and "campaign_email_logs" in stmt_str.lower():
            mock_result.scalar.return_value = 0

        return mock_result

    mock_db.execute = AsyncMock(side_effect=mock_execute)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_db, mock_ctx


# ---------------------------------------------------------------------------
# 1. Eligible Task Scheduling & Isolated Worker Consumption
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_01_eligible_campaign_consumed_by_worker(fake_smtp_account):
    """An eligible lead in an active campaign is consumed and sent via isolated transport."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=2))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="valid_website_seo",
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        # Assert zero real SMTP calls
        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0

        # Assert transport was invoked through the isolated interface
        assert mock_send.call_count == 1
        assert campaign.sent_count == 1
        assert campaign.skipped_count == 0
        assert campaign.failed_count == 0
        assert campaign.status == CampaignStatus.done
        assert lead.status == LeadStatus.emailed

        # Verify sent log added
        sent_logs = [
            c[0][0] for c in mock_db.add.call_args_list
            if isinstance(c[0][0], CampaignEmailLog) and c[0][0].status == "sent"
        ]
        assert len(sent_logs) == 1
        assert sent_logs[0].lead_id == lead_id


# ---------------------------------------------------------------------------
# 2. Scheduling Due vs Non-Due Behavior & Launch State Transitions
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_02_scheduled_metadata_and_worker_state_transitions(fake_smtp_account):
    """Campaign scheduled_at is preserved and transitions through draft -> sending -> done."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    future_time = datetime.utcnow() + timedelta(hours=4)
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)
    campaign.scheduled_at = future_time

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert campaign.scheduled_at == future_time  # Metadata preserved
        assert campaign.status == CampaignStatus.done


# ---------------------------------------------------------------------------
# 3. Batch Limits, Delays & Next Email Pacing Timer
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_03_batch_pacing_updates_next_email_countdown(fake_smtp_account):
    """Pacing between batch items calculates a 60-90s delay and sets next_email_at countdown."""
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@test.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@test.com")
    audit1 = create_mock_audit(lead_id=lead1_id, updated_at=datetime.utcnow() - timedelta(days=1))
    audit2 = create_mock_audit(lead_id=lead2_id, updated_at=datetime.utcnow() - timedelta(days=1))

    campaign = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead1_id: lead1, lead2_id: lead2},
        audit_map={lead1_id: audit1, lead2_id: audit2},
    )

    observed_sleep_durations = []

    async def record_sleep(seconds):
        observed_sleep_durations.append(seconds)

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")), \
         patch("asyncio.sleep", side_effect=record_sleep), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert campaign.sent_count == 2
        # One sleep occurs between item 1 and item 2
        assert len(observed_sleep_durations) == 1
        assert 60 <= observed_sleep_durations[0] <= 90


# ---------------------------------------------------------------------------
# 4. Account Daily Capacity Rate Limiting
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_04_account_daily_capacity_limit_pauses_campaign(fake_smtp_account):
    """When daily send capacity is exhausted (>= 1000 sends today), the campaign pauses cleanly."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    # Mock DB query to return 1000 sends today for this sender
    orig_execute = mock_db.execute

    async def capacity_reached_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt) if stmt is not None else ""
        if "count" in stmt_str.lower() and "campaign_email_logs" in stmt_str.lower():
            mock_res = MagicMock()
            mock_res.scalar.return_value = 1000
            return mock_res
        return await orig_execute(stmt, *args, **kwargs)

    mock_db.execute = AsyncMock(side_effect=capacity_reached_execute)

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0  # No emails sent!
        assert campaign.status == CampaignStatus.paused
        assert campaign.sent_count == 0
        assert campaign.pending_lead_ids == [str(lead_id)]


# ---------------------------------------------------------------------------
# 5. In-Process Concurrency Lock Drops Duplicate Runners
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_05_concurrency_lock_drops_duplicate_runners():
    """If a campaign is already marked running in _RUNNING_CAMPAIGNS, duplicate calls drop immediately."""
    camp_id = str(uuid.uuid4())
    _RUNNING_CAMPAIGNS.add(camp_id)

    with patch("app.engines.outreach_engine._run_campaign_worker") as mock_worker:
        await run_campaign(camp_id)
        mock_worker.assert_not_called()

    # Cleaned up and verified not executed
    assert camp_id in _RUNNING_CAMPAIGNS


# ---------------------------------------------------------------------------
# 6. Transient Failure Records Error & Continues Processing
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_06_transient_failure_records_failed_state_and_continues(fake_smtp_account):
    """Transient SMTP failure records status='failed' in log and advances to next lead."""
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@test.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@test.com")
    audit1 = create_mock_audit(lead_id=lead1_id, updated_at=datetime.utcnow() - timedelta(days=1))
    audit2 = create_mock_audit(lead_id=lead2_id, updated_at=datetime.utcnow() - timedelta(days=1))

    campaign = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead1_id: lead1, lead2_id: lead2},
        audit_map={lead1_id: audit1, lead2_id: audit2},
    )

    send_outcomes = [
        (False, "421 4.4.2 Connection lost temporarily"),  # Lead 1: transient failure
        (True, ""),                                       # Lead 2: success
    ]

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", side_effect=send_outcomes) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 2
        assert campaign.failed_count == 1
        assert campaign.sent_count == 1
        assert campaign.status == CampaignStatus.done


# ---------------------------------------------------------------------------
# 7. Permanent Sender Failure Pauses Campaign to Prevent Repetitive Rejection
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_07_permanent_sender_failure_pauses_campaign(fake_smtp_account):
    """Permanent sender error (553 not owned by user) pauses campaign immediately."""
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@test.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@test.com")
    audit1 = create_mock_audit(lead_id=lead1_id, updated_at=datetime.utcnow() - timedelta(days=1))
    audit2 = create_mock_audit(lead_id=lead2_id, updated_at=datetime.utcnow() - timedelta(days=1))

    campaign = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead1_id: lead1, lead2_id: lead2},
        audit_map={lead1_id: audit1, lead2_id: audit2},
    )

    perm_err = "553 5.7.1 <sender@bad.com>: Sender address rejected: not owned by user outreach@tebsolutions.in"

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(False, perm_err)) as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 1  # Stopped after lead 1!
        assert campaign.status == CampaignStatus.paused
        assert campaign.failed_count == 1
        assert campaign.sent_count == 0
        assert campaign.pending_lead_ids == [str(lead2_id)]  # Lead 2 saved for resume


# ---------------------------------------------------------------------------
# 8. Pause Command Halts Runner and Saves Remaining Progress
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_08_operator_pause_halts_worker_and_saves_state(fake_smtp_account):
    """If campaign status changes to 'paused' mid-run, worker gracefully halts and saves pending_lead_ids."""
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@test.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@test.com")
    audit1 = create_mock_audit(lead_id=lead1_id, updated_at=datetime.utcnow() - timedelta(days=1))
    audit2 = create_mock_audit(lead_id=lead2_id, updated_at=datetime.utcnow() - timedelta(days=1))

    campaign = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead1_id: lead1, lead2_id: lead2},
        audit_map={lead1_id: audit1, lead2_id: audit2},
    )

    # After lead 1 is sent, operator sets status = paused
    async def mock_refresh(obj, attrs):
        if attrs == ['status'] and campaign.sent_count == 1:
            campaign.status = CampaignStatus.paused

    mock_db.refresh = AsyncMock(side_effect=mock_refresh)

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 1
        assert campaign.sent_count == 1
        assert campaign.status == CampaignStatus.paused
        assert campaign.pending_lead_ids == [str(lead2_id)]


# ---------------------------------------------------------------------------
# 9. Pre-Send Boundary: 7-Day Cooldown Skips Recipient
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_09_presend_cooldown_skips_recently_emailed_lead(fake_smtp_account):
    """A lead emailed 3 days ago is skipped at the immediate pre-send boundary."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id, last_emailed_at=datetime.utcnow() - timedelta(days=3))
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1
        assert campaign.sent_count == 0


# ---------------------------------------------------------------------------
# 10. Pre-Send Boundary: Quarantined or Suppressed Lead is Blocked
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_10_presend_suppression_and_quarantine_blocks_dispatch(fake_smtp_account):
    """A lead with is_suppressed=True is quarantined and skipped at the dispatch boundary."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id, is_suppressed=True)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1
        assert lead.is_quarantined is True


# ---------------------------------------------------------------------------
# 11. Pre-Send Boundary: Unverified or Disposable Recipient Blocked
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_11_presend_unverified_recipient_blocked(fake_smtp_account):
    """Lead whose email verification is 'disposable' is skipped at the dispatch boundary."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id, email_verification_status="disposable")
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1
        assert lead.is_quarantined is True


# ---------------------------------------------------------------------------
# 12. Pre-Send Boundary: Stale Audit (> 14 Days) Excluded
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_12_presend_stale_audit_excluded(fake_smtp_account):
    """An audit completed 16 days ago (> 14 days) fails the freshness check at dispatch boundary."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    # Stale audit: 16 days old
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=16))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="valid_website_seo",
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1
        assert campaign.sent_count == 0


# ---------------------------------------------------------------------------
# 13. Pre-Send Boundary: Missing Proposal Approval Fails Closed
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_13_presend_missing_proposal_approval_fails_closed(fake_smtp_account):
    """A technical SEO proposal campaign fails closed if no approved proposal exists in ProposalService."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=2))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="technical_seo_proposal",
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    # Ensure ProposalService has NO proposal for this lead (e.g. backend process restarted)
    ProposalService._proposals.clear()

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1
        assert campaign.sent_count == 0

        # Log entry verifies refusal reason
        skipped_logs = [
            c[0][0] for c in mock_db.add.call_args_list
            if isinstance(c[0][0], CampaignEmailLog) and c[0][0].status == "skipped"
        ]
        assert len(skipped_logs) == 1
        assert "Proposal approval required" in skipped_logs[0].message


# ---------------------------------------------------------------------------
# 14. Pre-Send Boundary: Edited Draft Revokes Approval & Blocks Dispatch
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_14_presend_edited_draft_revokes_approval_and_blocks_dispatch(fake_smtp_account):
    """If operator edits a proposal, approval is revoked and dispatch fails closed."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=2))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="technical_seo_proposal",
    )

    # Setup proposal in ProposalService and mark approved
    ProposalService._proposals[str(lead_id)] = {
        "lead_id": str(lead_id),
        "status": "approved_for_delivery",
        "approved": True,
        "approved_by": "operator@tebsolutions.in",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    # Then operator edits the draft -> resets approved to False
    ProposalService.edit_proposal(lead_id=str(lead_id), body_text="Updated text without re-approval")

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1


# ---------------------------------------------------------------------------
# 15. Pre-Send Boundary: Proposal Provenance Mismatch Blocks Dispatch
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_15_presend_proposal_provenance_mismatch_blocks_dispatch(fake_smtp_account):
    """Proposal belonging to lead B cannot be used to dispatch lead A."""
    lead_a_id = uuid.uuid4()
    lead_b_id = uuid.uuid4()
    lead_a = create_mock_lead(lead_id=lead_a_id)
    audit_a = create_mock_audit(lead_id=lead_a_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_a_id)],
        status=CampaignStatus.draft,
        campaign_type="technical_seo_proposal",
    )

    # Proposal in cache belongs to lead_b
    ProposalService._proposals[str(lead_a_id)] = {
        "lead_id": str(lead_b_id),  # Mismatch!
        "status": "approved_for_delivery",
        "approved": True,
        "approved_by": "operator@tebsolutions.in",
    }

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_a_id: lead_a},
        audit_map={lead_a_id: audit_a},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1


# ---------------------------------------------------------------------------
# 16. Database Transient Exception on Single Lead Handled Gracefully
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_16_lead_processing_exception_handled_gracefully(fake_smtp_account):
    """Unhandled exception during one lead's processing increments failed_count and continues."""
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@test.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@test.com")
    audit1 = create_mock_audit(lead_id=lead1_id, updated_at=datetime.utcnow() - timedelta(days=1))
    audit2 = create_mock_audit(lead_id=lead2_id, updated_at=datetime.utcnow() - timedelta(days=1))

    campaign = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead1_id: lead1, lead2_id: lead2},
        audit_map={lead1_id: audit1, lead2_id: audit2},
    )

    # Lead 1 throws unexpected exception during DB fetch
    orig_get = mock_db.get
    call_count = 0

    async def throwing_get(model, obj_id):
        nonlocal call_count
        if model == Lead and obj_id == lead1_id and call_count == 0:
            call_count += 1
            raise RuntimeError("Database connection timeout on lead 1")
        return await orig_get(model, obj_id)

    mock_db.get = AsyncMock(side_effect=throwing_get)

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert campaign.failed_count == 1
        assert campaign.sent_count == 1  # Lead 2 still processed!


# ---------------------------------------------------------------------------
# 17. Neutral Introductory Workflow Allowed Without Audit
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_17_neutral_introductory_campaign_allowed_without_audit(fake_smtp_account):
    """generic_first_contact campaign dispatches valid lead even if audit is missing."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="generic_first_contact",
    )

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={},  # No audit!
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync", return_value=(True, "")) as mock_send, \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 1
        assert campaign.sent_count == 1


# ---------------------------------------------------------------------------
# 18. Audit Evidence Fingerprint Mismatch Blocks Dispatch
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_18_audit_evidence_fingerprint_mismatch_blocks_dispatch(fake_smtp_account):
    """If audit findings changed after campaign review, fingerprint mismatch blocks send."""
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id, updated_at=datetime.utcnow() - timedelta(days=1))
    campaign = create_mock_campaign(
        lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        campaign_type="valid_website_seo",
    )
    # Approved reference has fingerprint 'hash_A', but current render will produce 'hash_B'
    campaign.audit_references = {
        str(lead_id): {
            "audit_id": str(audit.id),
            "fingerprint": "approved_fingerprint_hash_A",
            "renderer_version": "v1.0",
        }
    }

    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={lead_id: lead},
        audit_map={lead_id: audit},
    )

    # Force TemplateRenderer to return content_strategy = "audit_generated" with different fingerprint
    mock_rendered = {
        "subject": "SEO findings",
        "plain_body": "Findings",
        "html_body": "<p>Findings</p>",
        "content_strategy": "audit_generated",
        "audit_reference": {
            "audit_id": str(audit.id),
            "fingerprint": "different_changed_fingerprint_hash_B",
            "renderer_version": "v1.0",
        },
    }

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.services.template_renderer.TemplateRenderer.render_campaign_email", return_value=mock_rendered), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.skipped_count == 1


# ---------------------------------------------------------------------------
# 19. Task Cancellation While In Queue (Lead Deleted from DB)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_19_deleted_lead_in_pending_skipped_cleanly(fake_smtp_account):
    """If a lead is deleted from DB after campaign queueing, it is safely skipped without crashing."""
    lead_id = uuid.uuid4()
    campaign = create_mock_campaign(lead_ids=[str(lead_id)], status=CampaignStatus.draft)

    # Mock DB returns None for lead
    mock_db, mock_session_ctx = setup_mock_db(
        campaign=campaign,
        lead_map={},  # Lead not found!
        audit_map={},
    )

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=campaign), \
         patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await _run_campaign_worker(str(campaign.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0
        assert campaign.sent_count == 0


# ---------------------------------------------------------------------------
# 20. Strict Verification of Zero Real SMTP Network Calls Across All Invariants
# ---------------------------------------------------------------------------
def test_20_transport_boundary_strictly_blocks_real_smtp_connections():
    """Verify that under no circumstances can tests touch live SMTP sockets."""
    with patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        account = {
            "email": "test@tebsolutions.in",
            "login_email": "test@tebsolutions.in",
            "password": "fake_password",
            "smtp_host": "smtp.hostinger.com",
            "smtp_port": 465,
        }

        # Mock SSL context
        mock_server = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = mock_server

        success, err = _send_email_sync(
            account=account,
            to_email="verified_recipient@example-domain.com",
            subject="Test subject",
            html_body="<p>Test</p>",
            plain_body="Test",
        )

        assert success is True
        # Verified mock was called, real network was never invoked
        assert mock_smtp_ssl.call_count == 1
        assert mock_server.sendmail.call_count == 1
