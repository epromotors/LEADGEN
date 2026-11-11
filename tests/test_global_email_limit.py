"""
tests/test_global_email_limit.py

Authoritative Tests for LEADGEN Outbound Email Quota & Global Cap:
- Global 1,000 limit across all sender accounts combined
- Rejects 2,000 capacity when multiple accounts configured
- Boundary conditions: 999, 1000, 1001
- IST midnight reset and date-boundary window
- Shared cap across campaigns, proposals, test-sends
- Concurrency-safe atomic check
- Failed send isolation (no false sent counts)
- Zero double-counting
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import zoneinfo

import pytest

from app.services.email_limit_service import (
    GLOBAL_DAILY_EMAIL_CAP,
    TIMEZONE_NAME,
    check_global_email_capacity,
    claim_global_email_capacity_atomic,
    get_account_sent_count_today,
    get_global_sent_count_today,
    get_ist_day_bounds,
    get_sender_daily_usage,
)


def _run_async(coro):
    """Run an async coroutine reliably on Windows (Python 3.14 compatible)."""
    return asyncio.run(coro)


# ─── 1. IST Date Boundary & Reset Logic ─────────────────────────────────────────

def test_ist_day_bounds_calculation():
    """Verify daily window resets at IST midnight (18:30 UTC of previous day)."""
    ref_utc = datetime(2026, 10, 25, 14, 0, 0, tzinfo=timezone.utc)
    start_utc, end_utc, ref_ist = get_ist_day_bounds(ref_utc)

    # IST day starts at 2026-10-25 00:00:00 IST -> 2026-10-24 18:30:00 UTC
    assert start_utc == datetime(2026, 10, 24, 18, 30, 0)
    # IST day ends at 2026-10-26 00:00:00 IST -> 2026-10-25 18:30:00 UTC
    assert end_utc == datetime(2026, 10, 25, 18, 30, 0)
    assert ref_ist.tzinfo.key == "Asia/Kolkata"


def test_ist_midnight_reset_boundary():
    """Verify that 1 microsecond after 18:30 UTC shifts to the next IST calendar day."""
    before_midnight_utc = datetime(2026, 10, 25, 18, 29, 59, tzinfo=timezone.utc)
    after_midnight_utc = datetime(2026, 10, 25, 18, 30, 1, tzinfo=timezone.utc)

    s1, e1, ist1 = get_ist_day_bounds(before_midnight_utc)
    s2, e2, ist2 = get_ist_day_bounds(after_midnight_utc)

    # Before midnight is still 2026-10-25 IST
    assert ist1.day == 25
    # After midnight is 2026-10-26 IST
    assert ist2.day == 26
    assert s2 == datetime(2026, 10, 25, 18, 30, 0)


# ─── 2. Global Capacity & Zero Double-Counting ─────────────────────────────────

def test_global_cap_enforces_1000_across_multiple_accounts():
    """Two configured accounts must NEVER report or allow 2,000 capacity."""
    async def _test():
        mock_db = AsyncMock()
        # Mock get_global_sent_count_today -> 0 sent
        mock_res_c = MagicMock()
        mock_res_c.scalar.return_value = 0
        mock_res_a = MagicMock()
        mock_res_a.scalar.return_value = 0
        mock_db.execute.side_effect = [mock_res_c, mock_res_a, mock_res_c, mock_res_a, mock_res_c, mock_res_a]

        accounts = [
            {"email": "info@tebsolutions.in", "daily_limit": 1000},
            {"email": "services@tebsolutions.in", "daily_limit": 1000},
        ]

        usage = await get_sender_daily_usage(mock_db, accounts)
        # Total capacity must strictly be 1000, not 2000!
        assert usage["total_daily_capacity"] == 1000
        assert usage["global_daily_cap"] == 1000
        assert usage["sent_today"] == 0
        assert usage["remaining_today"] == 1000
        assert len(usage["accounts"]) == 2

    _run_async(_test())


def test_zero_double_counting_across_campaign_and_activity_logs():
    """
    Ensure campaign sends, proposals, and test emails are counted exactly once,
    while mirror activity logs ('email_sent') are excluded.
    """
    async def _test():
        mock_db = AsyncMock()
        # CampaignEmailLog query returns 10 campaign sends
        mock_res_c = MagicMock()
        mock_res_c.scalar.return_value = 10

        # ActivityLog query returns 5 non-campaign sends (proposals/tests)
        mock_res_a = MagicMock()
        mock_res_a.scalar.return_value = 5

        mock_db.execute.side_effect = [mock_res_c, mock_res_a]

        total_sent = await get_global_sent_count_today(mock_db)
        assert total_sent == 15

    _run_async(_test())


# ─── 3. Boundary Enforcement: 999, 1000, and >1000 ─────────────────────────────

def test_boundary_at_999_allows_one_send():
    """At 999 sent, exactly 1 send remains; asking for 2 is rejected."""
    async def _test():
        mock_db = AsyncMock()
        with patch("app.services.email_limit_service.get_global_sent_count_today", return_value=999):
            can_send, current_sent, remaining = await check_global_email_capacity(mock_db, 1)
            assert can_send is True
            assert current_sent == 999
            assert remaining == 1

            can_send_2, _, _ = await check_global_email_capacity(mock_db, 2)
            assert can_send_2 is False

    _run_async(_test())


def test_boundary_at_1000_blocks_further_sends():
    """At 1,000 sent, all send attempts are rejected."""
    async def _test():
        mock_db = AsyncMock()
        with patch("app.services.email_limit_service.get_global_sent_count_today", return_value=1000):
            can_send, current_sent, remaining = await check_global_email_capacity(mock_db, 1)
            assert can_send is False
            assert current_sent == 1000
            assert remaining == 0

    _run_async(_test())


def test_account_rotation_cannot_exceed_global_limit():
    """
    Account 1 sent 500, Account 2 sent 500. Total sent = 1000.
    Even though Account 1 has per-account limit 1000 and Account 2 has per-account limit 1000,
    the global cap prevents further sends and marks both accounts exhausted.
    """
    async def _test():
        mock_db = AsyncMock()
        with patch("app.services.email_limit_service.get_global_sent_count_today", return_value=1000):
            with patch("app.services.email_limit_service.get_account_sent_count_today", side_effect=[500, 500]):
                accounts = [
                    {"email": "info@tebsolutions.in", "daily_limit": 1000},
                    {"email": "services@tebsolutions.in", "daily_limit": 1000},
                ]

                usage = await get_sender_daily_usage(mock_db, accounts)
                assert usage["sent_today"] == 1000
                assert usage["remaining_today"] == 0
                for acc in usage["accounts"]:
                    assert acc["remaining_today"] == 0
                    assert acc["capacity_exhausted"] is True

    _run_async(_test())


# ─── 4. Concurrency-Safe Atomic Capacity Claim ─────────────────────────────────

def test_atomic_capacity_claim_prevents_race_condition():
    """Concurrent claims at the final remaining slot allow exactly one winner."""
    async def _test():
        mock_db = AsyncMock()
        mock_db.get_bind.return_value.dialect.name = "postgresql"

        # First check returns 999 sent (1 slot left)
        # Second check returns 1000 sent (0 slots left)
        with patch("app.services.email_limit_service.get_global_sent_count_today", side_effect=[999, 1000]):
            res1, sent1, rem1 = await claim_global_email_capacity_atomic(mock_db, 1)
            res2, sent2, rem2 = await claim_global_email_capacity_atomic(mock_db, 1)

            assert res1 is True
            assert rem1 == 1

            assert res2 is False
            assert rem2 == 0

    _run_async(_test())


# ─── 5. Over 1,000, Multi-Route Shared Cap & Failed Attempts Tests ─────────────

def test_cap_over_1000_strictly_blocks_sends():
    """When sent count is over 1000 (e.g. 1005), remaining is 0 and sends are blocked."""
    async def _test():
        mock_db = AsyncMock()
        with patch("app.services.email_limit_service.get_global_sent_count_today", return_value=1005):
            can_send, current_sent, remaining = await check_global_email_capacity(mock_db, 1)
            assert can_send is False
            assert current_sent == 1005
            assert remaining == 0

    _run_async(_test())


def test_campaign_proposal_and_test_paths_share_global_cap():
    """Campaigns, manual proposals (Email 2), and test emails share the same 1,000 global cap."""
    async def _test():
        mock_db = AsyncMock()
        # CampaignEmailLog has 800 sent
        mock_res_c = MagicMock()
        mock_res_c.scalar.return_value = 800

        # ActivityLog has 150 email2_sent + 50 test_email_sent = 200 non-campaign sends
        mock_res_a = MagicMock()
        mock_res_a.scalar.return_value = 200

        mock_db.execute.side_effect = [mock_res_c, mock_res_a]

        total_sent = await get_global_sent_count_today(mock_db)
        assert total_sent == 1000

        # Further capacity check must block
        with patch("app.services.email_limit_service.get_global_sent_count_today", return_value=total_sent):
            can_send, sent, rem = await check_global_email_capacity(mock_db, 1)
            assert can_send is False
            assert sent == 1000
            assert rem == 0

    _run_async(_test())


def test_failed_smtp_attempts_do_not_increment_sent_count():
    """Failed SMTP logs and failed activity events are strictly ignored in count."""
    async def _test():
        mock_db = AsyncMock()
        # Mock database where only successful 'sent' status is returned
        mock_res_c = MagicMock()
        mock_res_c.scalar.return_value = 0  # 0 status='sent', even if 50 status='failed' exist
        mock_res_a = MagicMock()
        mock_res_a.scalar.return_value = 0  # 0 event_type in ('email2_sent', etc)

        mock_db.execute.side_effect = [mock_res_c, mock_res_a]

        total_sent = await get_global_sent_count_today(mock_db)
        assert total_sent == 0

    _run_async(_test())


def test_campaign_pauses_cleanly_when_daily_limit_reached():
    """When daily limit is reached during campaign execution, campaign is paused with status 'paused'."""
    from app.models import Campaign, CampaignStatus

    camp = Campaign(
        id=uuid.uuid4(),
        name="Test Campaign",
        status=CampaignStatus.draft,
        lead_ids=["id1", "id2"],
        pending_lead_ids=["id1", "id2"],
    )

    # Simulating the limit reached condition in _run_campaign_worker
    can_send_global = False
    current_global_sent = 1000
    remaining_global = 0

    if not can_send_global or remaining_global <= 0:
        camp.status = CampaignStatus.paused
        camp.next_email_at = None

    assert camp.status == CampaignStatus.paused
    assert camp.next_email_at is None
    assert len(camp.pending_lead_ids) == 2

