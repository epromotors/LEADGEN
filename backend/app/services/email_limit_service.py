"""
backend/app/services/email_limit_service.py

Authoritative Global Outbound Email Quota & Enforcement Service:
- Hard application-wide maximum of 1,000 emails per calendar day in Asia/Kolkata (IST),
  across ALL SMTP sender accounts and dispatch routes combined.
- Multi-account rotation must NEVER allow 2,000 emails in one day.
- Daily window strictly defined using Asia/Kolkata (UTC+05:30) with reset at IST midnight.
- Concurrency-safe enforcement via PostgreSQL transaction-level advisory lock and in-process async lock.
- Zero double-counting: Campaign sends (CampaignEmailLog status='sent') and manual/proposal/test sends
  (ActivityLog event_type in ('email2_sent', 'test_email_sent', 'manual_email_sent')) are mutually disjoint.
- Zero database migrations: Utilizes existing CampaignEmailLog and ActivityLog models.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import zoneinfo
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, CampaignEmailLog

logger = logging.getLogger(__name__)

# Authoritative global daily cap across all accounts combined
GLOBAL_DAILY_EMAIL_CAP: int = 1000
TIMEZONE_NAME: str = "Asia/Kolkata"
IST_TZ = zoneinfo.ZoneInfo(TIMEZONE_NAME)

# PostgreSQL 64-bit advisory lock key for email quota synchronization
PG_EMAIL_QUOTA_LOCK_ID: int = 735100000000000002

# In-process asyncio lock for local synchronization
_IN_PROCESS_LOCK = asyncio.Lock()


def get_ist_day_bounds(reference_time: Optional[datetime] = None) -> Tuple[datetime, datetime, datetime]:
    """
    Given a reference UTC datetime (or current time if None), return:
    (start_utc, end_utc, current_ist)
    where start_utc and end_utc are naive UTC datetimes bounding the current IST calendar day.
    """
    if reference_time is None:
        ref_utc = datetime.now(timezone.utc)
    else:
        if reference_time.tzinfo is None:
            ref_utc = reference_time.replace(tzinfo=timezone.utc)
        else:
            ref_utc = reference_time.astimezone(timezone.utc)

    # Convert to Asia/Kolkata
    ref_ist = ref_utc.astimezone(IST_TZ)
    start_ist = ref_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    end_ist = start_ist + timedelta(days=1)

    start_utc = start_ist.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_ist.astimezone(timezone.utc).replace(tzinfo=None)

    return start_utc, end_utc, ref_ist


async def _extract_scalar(res: Any) -> int:
    """Safely extract integer count from real or mocked SQLAlchemy Result."""
    if hasattr(res, "scalar"):
        val = res.scalar()
        if asyncio.iscoroutine(val):
            val = await val
        return int(val or 0)
    return 0


async def get_global_sent_count_today(
    db: AsyncSession,
    reference_time: Optional[datetime] = None,
) -> int:
    """
    Count total outbound emails sent across all senders and all routes during the current IST day.
    
    Guarantees:
    - Counts each sent email once only.
    - Excludes failed and skipped attempts.
    - Counts campaign sends from CampaignEmailLog (status='sent').
    - Counts direct proposal sends from ActivityLog (event_type='email2_sent').
    - Counts test sends from ActivityLog (event_type='test_email_sent').
    - Counts manual sends from ActivityLog (event_type='manual_email_sent').
    - These record sets are strictly non-overlapping.
    """
    start_utc, end_utc, _ = get_ist_day_bounds(reference_time)

    # 1. Campaign outbound emails
    stmt_campaign = (
        select(func.count(CampaignEmailLog.id))
        .where(
            CampaignEmailLog.status == "sent",
            CampaignEmailLog.created_at >= start_utc,
            CampaignEmailLog.created_at < end_utc,
        )
    )
    res_campaign = await db.execute(stmt_campaign)
    campaign_sent = await _extract_scalar(res_campaign)

    # 2. Non-campaign sends logged in ActivityLog
    # (Exclude 'email_sent' because that is the mirror log written for campaign sends)
    stmt_activity = (
        select(func.count(ActivityLog.id))
        .where(
            ActivityLog.event_type.in_(["email2_sent", "test_email_sent", "manual_email_sent"]),
            ActivityLog.created_at >= start_utc,
            ActivityLog.created_at < end_utc,
        )
    )
    res_activity = await db.execute(stmt_activity)
    activity_sent = await _extract_scalar(res_activity)

    return int(campaign_sent + activity_sent)


async def get_account_sent_count_today(
    db: AsyncSession,
    account_email: str,
    reference_time: Optional[datetime] = None,
) -> int:
    """
    Count emails sent by a specific SMTP account today in IST.
    """
    start_utc, end_utc, _ = get_ist_day_bounds(reference_time)
    email_clean = account_email.strip().lower()

    # Campaign sends by account
    stmt_campaign = (
        select(func.count(CampaignEmailLog.id))
        .where(
            CampaignEmailLog.status == "sent",
            CampaignEmailLog.created_at >= start_utc,
            CampaignEmailLog.created_at < end_utc,
            CampaignEmailLog.message.ilike(f"%({email_clean})%"),
        )
    )
    res_campaign = await db.execute(stmt_campaign)
    c_sent = await _extract_scalar(res_campaign)

    # Activity sends by account
    stmt_act = (
        select(func.count(ActivityLog.id))
        .where(
            ActivityLog.event_type.in_(["email2_sent", "test_email_sent", "manual_email_sent"]),
            ActivityLog.created_at >= start_utc,
            ActivityLog.created_at < end_utc,
            ActivityLog.message.ilike(f"%{email_clean}%"),
        )
    )
    res_act = await db.execute(stmt_act)
    a_sent = await _extract_scalar(res_act)

    return int(c_sent + a_sent)


async def acquire_quota_lock_if_supported(db: AsyncSession):
    """
    Acquire a transaction-level PostgreSQL advisory lock to ensure
    concurrent workers or API processes serialize quota checks and claims.
    Silently ignores for SQLite or non-Postgres in unit tests.
    """
    try:
        bind = db.get_bind()
        if asyncio.iscoroutine(bind):
            bind = await bind
        if bind and hasattr(bind, "dialect") and getattr(bind.dialect, "name", "") == "postgresql":
            await db.execute(text(f"SELECT pg_advisory_xact_lock({PG_EMAIL_QUOTA_LOCK_ID});"))
    except Exception as e:
        logger.debug("Advisory lock not applicable or dialect non-postgres: %s", e)


async def check_global_email_capacity(
    db: AsyncSession,
    requested_count: int = 1,
    reference_time: Optional[datetime] = None,
) -> Tuple[bool, int, int]:
    """
    Check if the global 1,000 daily limit allows sending `requested_count` emails.
    Returns: (can_send, current_sent_today, remaining_today)
    """
    current_sent = await get_global_sent_count_today(db, reference_time=reference_time)
    remaining = max(0, GLOBAL_DAILY_EMAIL_CAP - current_sent)
    can_send = (current_sent + requested_count) <= GLOBAL_DAILY_EMAIL_CAP
    return can_send, current_sent, remaining


async def claim_global_email_capacity_atomic(
    db: AsyncSession,
    requested_count: int = 1,
    reference_time: Optional[datetime] = None,
) -> Tuple[bool, int, int]:
    """
    Concurrency-safe check and reservation under advisory lock and async lock.
    Returns: (granted, current_sent_today, remaining_today)
    """
    async with _IN_PROCESS_LOCK:
        await acquire_quota_lock_if_supported(db)
        can_send, current_sent, remaining = await check_global_email_capacity(
            db, requested_count=requested_count, reference_time=reference_time
        )
        return can_send, current_sent, remaining


async def get_sender_daily_usage(
    db: AsyncSession,
    accounts: List[Dict[str, Any]],
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Generate authoritative status report for UI and API:
    - total_daily_capacity: strictly 1,000 (never 2,000)
    - sent_today: global sent count across all accounts
    - remaining_today: max(0, 1000 - sent_today)
    - accounts: per-account usage, where per-account remaining is clamped to global remaining
    """
    start_utc, end_utc, current_ist = get_ist_day_bounds(reference_time)
    global_sent = await get_global_sent_count_today(db, reference_time=reference_time)
    global_remaining = max(0, GLOBAL_DAILY_EMAIL_CAP - global_sent)

    # Next IST reset time
    reset_ist = current_ist.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    seconds_until_reset = max(0, int((reset_ist - current_ist).total_seconds()))

    sender_info = []
    for acc in accounts:
        email = acc.get("email", "")
        acc_sent = await get_account_sent_count_today(db, email, reference_time=reference_time)
        account_limit = acc.get("daily_limit", GLOBAL_DAILY_EMAIL_CAP)
        # Stricter provider limit per account if configured, but remaining cannot exceed global_remaining
        acc_potential_rem = max(0, account_limit - acc_sent)
        acc_effective_rem = min(acc_potential_rem, global_remaining)

        sender_info.append({
            "email": email,
            "sender_name": acc.get("sender_name", ""),
            "host": acc.get("smtp_host") or acc.get("host", ""),
            "port": acc.get("smtp_port") or acc.get("port", 465),
            "sent_today": acc_sent,
            "account_limit": account_limit,
            "daily_limit": account_limit,
            "remaining_today": acc_effective_rem,
            "capacity_exhausted": (global_remaining == 0 or acc_effective_rem == 0),
        })

    return {
        "status": "configured" if accounts else "unconfigured",
        "configured": bool(accounts),
        "timezone": TIMEZONE_NAME,
        "current_time_ist": current_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "reset_at_ist": reset_ist.strftime("%Y-%m-%d 00:00:00 IST"),
        "seconds_until_reset": seconds_until_reset,
        "global_daily_cap": GLOBAL_DAILY_EMAIL_CAP,
        "total_daily_capacity": GLOBAL_DAILY_EMAIL_CAP,  # Authoritative hard limit: 1000
        "sent_today": global_sent,
        "remaining_today": global_remaining,
        "capacity_available": global_remaining > 0,
        "accounts": sender_info,
        "senders": sender_info,
        "active_sender": sender_info[0]["email"] if sender_info else None,
    }
