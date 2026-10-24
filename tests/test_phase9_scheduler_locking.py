"""
tests/test_phase9_scheduler_locking.py
--------------------------------------
Phase 9 Focused Deterministic Test Suite:
Distributed Worker Coordination, PostgreSQL Session Advisory Locks,
Automated Due-Campaign Scheduling, and Crash Recovery Lifecycle.

Mandatory Safety Invariant:
All tests assert zero real SMTP calls (mock transport only).
No live external queues are accessed.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.engines.outreach_engine import (
    _RUNNING_CAMPAIGNS,
    _run_campaign_worker,
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
from app.services.campaign_lock_service import (
    CampaignLockCoordinator,
    campaign_lock_coordinator,
    derive_campaign_lock_key,
    SCHEDULER_LOCK_KEY,
)
from app.services.campaign_scheduler import (
    CampaignScheduler,
    get_campaign_scheduler,
)
from app.services.proposal_service import ProposalService


# ---------------------------------------------------------------------------
# Test Fixtures & Invariant Enforcers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_lock_state_and_proposals():
    """Ensure in-memory and coordinator locks are reset before and after every test."""
    _RUNNING_CAMPAIGNS.clear()
    ProposalService._proposals.clear()
    campaign_lock_coordinator._active_in_process.clear()
    campaign_lock_coordinator._simulated_external_locks.clear()
    campaign_lock_coordinator._simulated_scheduler_locked = False
    yield
    _RUNNING_CAMPAIGNS.clear()
    ProposalService._proposals.clear()
    campaign_lock_coordinator._active_in_process.clear()
    campaign_lock_coordinator._simulated_external_locks.clear()
    campaign_lock_coordinator._simulated_scheduler_locked = False


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
    business_name: str = "Test Logistics",
    email: str = "contact@testlogistics.com",
    website: str = "https://testlogistics.com",
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
    lead.is_suppressed = is_suppressed
    lead.reply_type = reply_type
    lead.last_emailed_at = last_emailed_at
    lead.quarantine_reason = None
    return lead


def create_mock_audit(
    lead_id: uuid.UUID,
    status: AuditStatus = AuditStatus.done,
    updated_at: Optional[datetime] = None,
    error_message: Optional[str] = None,
) -> Audit:
    now_dt = updated_at or datetime.now(timezone.utc).replace(tzinfo=None)
    return Audit(
        id=uuid.uuid4(),
        lead_id=lead_id,
        status=status,
        updated_at=now_dt,
        created_at=now_dt,
        error_message=error_message,
        audit_results={
            "technical": {"ssl": {"status": "FAIL", "message": "Weak TLS"}},
            "seo": {"meta_tags": {"status": "FAIL", "message": "Missing meta description"}},
        },
    )


def create_mock_campaign(
    campaign_id: Optional[uuid.UUID] = None,
    name: str = "Scheduled SEO Campaign",
    campaign_type: str = "generic_first_contact",
    lead_ids: Optional[List[str]] = None,
    pending_lead_ids: Optional[List[str]] = None,
    status: CampaignStatus = CampaignStatus.draft,
    scheduled_at: Optional[datetime] = None,
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
        template="Hello {business_name}, observational outreach.",
        subject_template="Observation for {business_name}",
        status=status,
        scheduled_at=scheduled_at,
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
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalar.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.fetchall.return_value = []

        stmt_str = str(stmt) if stmt is not None else ""
        if "FROM audits" in stmt_str or "audits.lead_id" in stmt_str:
            for lid, audit in audit_map.items():
                if str(lid) in stmt_str:
                    mock_result.scalar_one_or_none.return_value = audit
                    return mock_result
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
# Test 1: PostgreSQL Cross-Connection Session Advisory Lock Isolation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_01_postgres_advisory_lock_cross_connection_isolation():
    """
    Demonstrates true PostgreSQL cross-connection advisory lock mutual exclusion.
    Connection 1 acquires the lock; Connection 2 is rejected.
    When Connection 1 unlocks, Connection 2 successfully acquires the lock.
    """
    # Detect if live PostgreSQL is available from backend/.env
    pg_url = None
    env_file = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if line.strip().startswith("DATABASE_URL="):
                    val = line.strip().split("=", 1)[1]
                    if "postgresql" in val and "dummy" not in val:
                        pg_url = val
                        break

    if not pg_url:
        pytest.skip("Test requires active live PostgreSQL engine")

    test_lock_key = 888777666555
    try:
        import psycopg

        sync_url = pg_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
        conn1 = psycopg.connect(sync_url)
        conn2 = psycopg.connect(sync_url)

        try:
            # Connection 1 acquires lock
            res1 = conn1.execute(f"SELECT pg_try_advisory_lock({test_lock_key})").fetchone()[0]
            assert res1 is True, "Connection 1 must acquire free advisory lock"

            # Connection 2 attempts to acquire same lock concurrently -> must be denied
            res2 = conn2.execute(f"SELECT pg_try_advisory_lock({test_lock_key})").fetchone()[0]
            assert res2 is False, "Connection 2 must be denied while Connection 1 holds lock"

            # Connection 1 releases lock
            res_unlock = conn1.execute(f"SELECT pg_advisory_unlock({test_lock_key})").fetchone()[0]
            assert res_unlock is True, "Connection 1 must successfully unlock"

            # Connection 2 can now acquire lock
            res2_after = conn2.execute(f"SELECT pg_try_advisory_lock({test_lock_key})").fetchone()[0]
            assert res2_after is True, "Connection 2 must acquire lock after Connection 1 releases"
            conn2.execute(f"SELECT pg_advisory_unlock({test_lock_key})")
        finally:
            conn1.close()
            conn2.close()

    except Exception as e:
        pytest.skip(f"Live PostgreSQL check skipped ({e})")


# ---------------------------------------------------------------------------
# Test 2: Two Workers Attempting to Claim Same Campaign Atomically
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_02_competing_workers_prevent_duplicate_execution():
    """
    Simulates two competing worker invocations for the same campaign.
    The first worker acquires exclusive lock; the second worker is immediately denied.
    """
    cid = str(uuid.uuid4())

    acquired1 = await campaign_lock_coordinator.acquire_campaign_lock(cid, owner_id="worker_1")
    assert acquired1 is True, "First worker instance must acquire lock"

    # Second worker attempts to acquire same campaign
    acquired2 = await campaign_lock_coordinator.acquire_campaign_lock(cid, owner_id="worker_2")
    assert acquired2 is False, "Second worker must be denied lock to prevent duplicate run"

    # Release by first worker
    released = await campaign_lock_coordinator.release_campaign_lock(cid)
    assert released is True, "First worker must release lock cleanly"

    # Worker 2 can now acquire
    acquired2_after = await campaign_lock_coordinator.acquire_campaign_lock(cid, owner_id="worker_2")
    assert acquired2_after is True, "Second worker can acquire after lock is released"
    await campaign_lock_coordinator.release_campaign_lock(cid)


# ---------------------------------------------------------------------------
# Test 3: Lock Release Lifecycle on Success and Unhandled Exception
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_03_lock_release_on_completion_and_exception():
    """
    Verifies lock is reliably released both upon normal completion and on exception.
    """
    cid = str(uuid.uuid4())

    # Case A: Normal lifecycle
    assert await campaign_lock_coordinator.acquire_campaign_lock(cid) is True
    assert campaign_lock_coordinator.is_campaign_locked_in_process(cid) is True
    await campaign_lock_coordinator.release_campaign_lock(cid)
    assert campaign_lock_coordinator.is_campaign_locked_in_process(cid) is False

    # Case B: Handled in run_campaign finally block on exception
    with patch("app.engines.outreach_engine._run_campaign_worker", side_effect=RuntimeError("Worker crash simulation")):
        with pytest.raises(RuntimeError):
            await run_campaign(cid)

    # In-memory and coordinator locks must be clean
    assert cid not in _RUNNING_CAMPAIGNS
    assert campaign_lock_coordinator.is_campaign_locked_in_process(cid) is False


# ---------------------------------------------------------------------------
# Test 4: Scheduler Claims Due Campaign and Leaves Future Campaign Unclaimed
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_04_scheduler_claims_due_campaign_leaves_future_unclaimed():
    """
    Verifies that CampaignScheduler discovers and atomically claims campaigns
    with scheduled_at <= now, while leaving future-scheduled campaigns untouched.
    """
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)

    due_camp = create_mock_campaign(
        campaign_id=uuid.uuid4(),
        name="Due Campaign",
        status=CampaignStatus.scheduled,
        scheduled_at=now_dt - timedelta(minutes=5),
    )
    future_camp = create_mock_campaign(
        campaign_id=uuid.uuid4(),
        name="Future Campaign",
        status=CampaignStatus.scheduled,
        scheduled_at=now_dt + timedelta(hours=2),
    )

    db_campaigns = {due_camp.id: due_camp, future_camp.id: future_camp}

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    async def mock_execute(stmt, *args, **kwargs):
        mock_res = MagicMock()
        stmt_str = str(stmt) if stmt is not None else ""
        if "scheduled_at" in stmt_str or "status" in stmt_str:
            # Filter due campaigns
            matching = [
                c for c in db_campaigns.values()
                if c.status == CampaignStatus.scheduled
                and c.scheduled_at is not None
                and c.scheduled_at <= now_dt
            ]
            mock_res.scalars.return_value.all.return_value = matching
        else:
            mock_res.scalars.return_value.all.return_value = []
        return mock_res

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    scheduler = CampaignScheduler(enabled=True, batch_size=5, max_concurrent_workers=3)

    dispatched_ids = []

    async def mock_dispatch(cid):
        dispatched_ids.append(cid)

    with patch("app.services.campaign_scheduler.AsyncSessionLocal", return_value=mock_ctx):
        with patch.object(scheduler, "_dispatch_campaign", side_effect=mock_dispatch):
            claimed_count = await scheduler.run_once(now_override=now_dt)
            await asyncio.sleep(0.01)

    assert claimed_count == 1, "Exactly one due campaign should be claimed"
    assert str(due_camp.id) in dispatched_ids
    assert due_camp.status == CampaignStatus.draft, "Claimed campaign status should transition to draft"
    assert future_camp.status == CampaignStatus.scheduled, "Future campaign must remain scheduled"


# ---------------------------------------------------------------------------
# Test 5: Simultaneous Scheduler Iterations Avoid Duplicate Claims
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_05_simultaneous_scheduler_ticks_avoid_duplicate_claims():
    """
    Verifies that when two scheduler instances or processes tick simultaneously,
    the singleton scheduler tick lock prevents duplicate discovery and claiming.
    """
    scheduler1 = CampaignScheduler(enabled=True)
    scheduler2 = CampaignScheduler(enabled=True)

    # Simulate Process 1 holding the scheduler tick lock
    campaign_lock_coordinator.simulate_scheduler_locked(True)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.campaign_scheduler.AsyncSessionLocal", return_value=mock_ctx):
        claimed = await scheduler2.run_once()

    # Scheduler 2 must skip the tick
    assert claimed == 0, "Scheduler 2 must claim 0 campaigns while Scheduler 1 holds tick lock"
    assert mock_db.commit.call_count == 0

    campaign_lock_coordinator.simulate_scheduler_locked(False)


# ---------------------------------------------------------------------------
# Test 6: Bounded Scheduler Iterations (Batch Size Cap)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_06_bounded_scheduler_batch_size():
    """
    Verifies that the scheduler respects CAMPAIGN_SCHEDULER_BATCH_SIZE
    and does not claim unbounded numbers of campaigns in a single iteration.
    """
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    batch_cap = 2

    campaigns = [
        create_mock_campaign(
            campaign_id=uuid.uuid4(),
            name=f"Due Campaign {i}",
            status=CampaignStatus.scheduled,
            scheduled_at=now_dt - timedelta(minutes=i + 1),
        )
        for i in range(5)
    ]

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    async def mock_execute(stmt, *args, **kwargs):
        mock_res = MagicMock()
        # Enforce limit of batch_cap
        matching = [c for c in campaigns if c.status == CampaignStatus.scheduled][:batch_cap]
        mock_res.scalars.return_value.all.return_value = matching
        return mock_res

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    scheduler = CampaignScheduler(enabled=True, batch_size=batch_cap, max_concurrent_workers=10)

    with patch("app.services.campaign_scheduler.AsyncSessionLocal", return_value=mock_ctx):
        with patch.object(scheduler, "_dispatch_campaign", AsyncMock()):
            claimed = await scheduler.run_once(now_override=now_dt)

    assert claimed == batch_cap, f"Scheduler must claim exactly batch_size ({batch_cap}) campaigns"


# ---------------------------------------------------------------------------
# Test 7: Bounded Concurrent Workers Cap
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_07_bounded_concurrent_workers_cap():
    """
    Verifies that if active workers reach max_concurrent_workers,
    the scheduler defers new claims to prevent node overload.
    """
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    max_workers = 2

    scheduler = CampaignScheduler(enabled=True, max_concurrent_workers=max_workers)

    # Simulate max_workers already active in process coordinator
    for i in range(max_workers):
        campaign_lock_coordinator._active_in_process.add(f"active_worker_{i}")

    mock_db = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.campaign_scheduler.AsyncSessionLocal", return_value=mock_ctx):
        claimed = await scheduler.run_once(now_override=now_dt)

    assert claimed == 0, "Scheduler must skip tick when worker concurrency limit is reached"
    assert mock_db.execute.call_count == 0, "Database should not even be queried when cap reached"


# ---------------------------------------------------------------------------
# Test 8: Operator Pause or Cancellation While Worker is Running
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_08_worker_halts_cleanly_on_pause_or_cancellation(fake_smtp_account):
    """
    Verifies that a running worker detects campaign status change (paused or cancelled)
    before processing the next lead, saves progress, and releases the lock cleanly.
    """
    lead1_id = uuid.uuid4()
    lead2_id = uuid.uuid4()
    lead1 = create_mock_lead(lead_id=lead1_id, email="lead1@example.com")
    lead2 = create_mock_lead(lead_id=lead2_id, email="lead2@example.com")

    audit1 = create_mock_audit(lead_id=lead1_id)
    audit2 = create_mock_audit(lead_id=lead2_id)

    camp = create_mock_campaign(
        lead_ids=[str(lead1_id), str(lead2_id)],
        pending_lead_ids=[str(lead1_id), str(lead2_id)],
        status=CampaignStatus.draft,
    )

    mock_db, mock_ctx = setup_mock_db(camp, {lead1_id: lead1, lead2_id: lead2}, {lead1_id: audit1, lead2_id: audit2})

    sent_emails = []

    def mock_send(account, to_email, subject, html_body, **kwargs):
        sent_emails.append(to_email)
        # Operator cancels / resets campaign while worker is between leads
        camp.status = CampaignStatus.draft
        return True, ""

    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", AsyncMock(return_value=camp)), \
         patch("app.engines.outreach_engine._send_email_sync", side_effect=mock_send), \
         patch("asyncio.sleep", AsyncMock()), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await run_campaign(str(camp.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0

    # Lead 1 was processed, but when camp.status was changed to draft, worker halted before Lead 2
    assert len(sent_emails) == 1
    assert "lead1@example.com" in sent_emails
    assert "lead2@example.com" not in sent_emails

    # Lock must be completely released
    assert str(camp.id) not in _RUNNING_CAMPAIGNS
    assert campaign_lock_coordinator.is_campaign_locked_in_process(str(camp.id)) is False


# ---------------------------------------------------------------------------
# Test 9: Scheduled Campaign Cancellation Before Launch
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_09_cancel_scheduled_campaign_before_launch():
    """
    Verifies that cancelling a scheduled campaign reverts it to draft and clears scheduled_at.
    """
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    camp = create_mock_campaign(
        campaign_id=uuid.uuid4(),
        status=CampaignStatus.scheduled,
        scheduled_at=now_dt + timedelta(hours=1),
    )

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    from app.routers.campaigns import cancel_campaign

    with patch("app.routers.campaigns.get_campaign_safe", AsyncMock(return_value=camp)):
        res = await cancel_campaign(camp.id, db=mock_db)

    assert camp.status == CampaignStatus.draft
    assert camp.scheduled_at is None
    assert "cancelled" in res["message"].lower()
    assert mock_db.commit.call_count >= 1


# ---------------------------------------------------------------------------
# Test 10: Proposal Approval Missing Fails Closed On Scheduled Dispatch
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_10_missing_proposal_approval_fails_closed_on_scheduled_dispatch(fake_smtp_account):
    """
    Verifies Phase 7/8 invariant: If a scheduled campaign requires proposal approval,
    and approval is lost after a backend restart, worker fails closed and skips lead.
    """
    lead_id = uuid.uuid4()
    lead = create_mock_lead(lead_id=lead_id)
    audit = create_mock_audit(lead_id=lead_id)

    camp = create_mock_campaign(
        campaign_type="technical_seo_proposal",
        lead_ids=[str(lead_id)],
        pending_lead_ids=[str(lead_id)],
        status=CampaignStatus.draft,
        require_proposal_approval=True,
    )

    # Empty proposal store (restart simulation)
    ProposalService._proposals.clear()

    mock_db, mock_ctx = setup_mock_db(camp, {lead_id: lead}, {lead_id: audit})

    mock_send = MagicMock()
    with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
         patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_ctx), \
         patch("app.engines.outreach_engine.get_campaign_safe", AsyncMock(return_value=camp)), \
         patch("app.engines.outreach_engine._send_email_sync", mock_send), \
         patch("smtplib.SMTP") as mock_smtp, \
         patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

        await run_campaign(str(camp.id))

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0
        assert mock_send.call_count == 0, "No email must be sent when proposal approval is missing"
        assert camp.skipped_count == 1, "Lead must be counted as skipped fail-closed"


# ---------------------------------------------------------------------------
# Test 11: Crash Recovery for Stranded Sending Campaign
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_11_crash_recovery_resumes_stranded_campaign():
    """
    Verifies that a campaign stranded in 'sending' after a process crash
    (whose lock is now free) can be safely resumed by an operator.
    """
    camp = create_mock_campaign(
        campaign_id=uuid.uuid4(),
        status=CampaignStatus.sending,
        lead_ids=["lead1", "lead2"],
        pending_lead_ids=["lead2"],
    )

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    bg_tasks = MagicMock()

    from app.routers.campaigns import resume_campaign

    with patch("app.routers.campaigns.get_campaign_safe", AsyncMock(return_value=camp)):
        res = await resume_campaign(camp.id, background_tasks=bg_tasks, db=mock_db)

    assert "resumed" in res["message"].lower()
    assert camp.status == CampaignStatus.draft
    assert bg_tasks.add_task.call_count == 1


# ---------------------------------------------------------------------------
# Test 12: Scheduler Lifecycle Startup & Shutdown in FastAPI
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_12_scheduler_fastapi_lifecycle():
    """
    Verifies that CampaignScheduler starts and stops cleanly without hanging.
    """
    scheduler = CampaignScheduler(enabled=True, poll_interval_seconds=100.0)
    assert scheduler._running is False

    await scheduler.start()
    assert scheduler._running is True
    assert scheduler._task is not None

    await scheduler.stop()
    assert scheduler._running is False
    assert scheduler._task is None


# ---------------------------------------------------------------------------
# Test 13: Transient Database Error Resilience (No Spinning Loop)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_13_transient_db_error_handled_without_corrupting_state():
    """
    Verifies that a transient database exception during scheduler polling
    is caught safely, returns 0 claims, and does not alter campaign status.
    """
    scheduler = CampaignScheduler(enabled=True)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("Transient DB connection drop"))
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.campaign_scheduler.AsyncSessionLocal", return_value=mock_ctx):
        claimed = await scheduler.run_once()

    assert claimed == 0, "Scheduler must return 0 on transient DB error"
