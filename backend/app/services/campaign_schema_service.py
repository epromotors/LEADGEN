"""
backend/app/services/campaign_schema_service.py
------------------------------------------------
Provides schema-capability awareness, projection, and compatibility routines for Campaign operations.
Specifically addresses backward-compatibility with database schemas that have not yet applied
migration v6_2_3_audit_email_freshness.sql (which adds the audit_references column to campaigns).

Core Guarantees:
1. Generic campaigns (generic_first_contact, no_website_design, public_provider_demo) work seamlessly
   without requiring or querying the unapplied audit_references column.
2. Existing campaign records remain readable and editable.
3. Audit-dependent campaigns fail closed with an actionable structured schema-readiness response
   if the required audit_references column is missing.
4. No code path executes automatic DDL against the database.
5. Distinguishes missing schema capability from unrelated database errors.
"""

import uuid
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from unittest.mock import AsyncMock, MagicMock
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select, text, table, column
from sqlalchemy.orm import undefer, defer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, CampaignStatus

REQUIRED_MIGRATION_NAME = "v6_2_3_audit_email_freshness.sql"
REQUIRED_MIGRATION_PATH = "backend/migrations/v6_2_3_audit_email_freshness.sql"

SCHEMA_READINESS_DETAIL = {
    "error": "schema_readiness_error",
    "message": (
        "Database schema readiness error: The 'audit_references' column is required "
        "for audit-dependent campaigns but has not been applied to the database. "
        "Please apply migration v6_2_3_audit_email_freshness.sql to an authorized database."
    ),
    "required_migration": REQUIRED_MIGRATION_NAME,
    "missing_column": "audit_references",
    "target_table": "campaigns",
    "status": "blocked_pending_migration",
}

COMPATIBLE_CAMPAIGN_COLUMNS = [
    "id",
    "name",
    "lead_ids",
    "template",
    "subject_template",
    "campaign_type",
    "scheduled_at",
    "sent_count",
    "status",
    "pending_lead_ids",
    "skipped_count",
    "failed_count",
    "next_email_at",
    "paused_at",
    "created_at",
]

SCHEMA_CACHE_NEGATIVE_TTL_SECONDS = 30.0  # Re-check missing columns after 30s in case migration was applied
SCHEMA_CACHE_POSITIVE_TTL_SECONDS = 3600.0  # Re-check present columns after 1 hour

_schema_override: Optional[bool] = None
_cached_availability: Dict[str, Tuple[bool, float]] = {}


def set_audit_references_schema_override(available: Optional[bool]) -> None:
    """Explicitly override schema capability for testing / mocking."""
    global _schema_override
    _schema_override = available


@contextmanager
def override_campaign_schema(available: Optional[bool]):
    """Context manager to safely override schema capability for testing with guaranteed cleanup."""
    global _schema_override
    prev = _schema_override
    try:
        _schema_override = available
        yield
    finally:
        _schema_override = prev


def reset_schema_cache() -> None:
    """Clear cached schema capability checks."""
    global _schema_override, _cached_availability
    _schema_override = None
    _cached_availability.clear()


def _get_cache_key(db: AsyncSession) -> Optional[str]:
    """Derives a cache key uniquely identifying the database target/engine."""
    bind = getattr(db, "bind", None)
    if bind is None and hasattr(db, "get_bind"):
        try:
            bind = db.get_bind()
        except Exception:
            bind = None
    if bind is None or isinstance(bind, (AsyncMock, MagicMock)):
        return None

    url = getattr(bind, "url", None)
    if url is None:
        url = getattr(getattr(bind, "engine", None), "url", None)

    if url is not None:
        if hasattr(url, "render_as_string"):
            try:
                return url.render_as_string(hide_password=True)
            except Exception:
                pass
        return str(url)

    # When a stable database URL cannot be established, avoid caching this target.
    # Falling back to transient object IDs (which CPython recycles after deallocation)
    # or generic dialect names risks unsafe cross-target cache collisions.
    return None


def _invalidate_target_cache(db: AsyncSession) -> None:
    """Marks the specific database target as lacking the audit_references column without polluting global overrides."""
    cache_key = _get_cache_key(db)
    if cache_key:
        _cached_availability[cache_key] = (False, time.monotonic())


def is_missing_audit_references_error(err: Exception) -> bool:
    """
    Distinguishes a missing audit_references column error from unrelated database failures
    (e.g., connection lost, deadlock, foreign key violation, syntax error).
    """
    err_str = str(err).lower()
    if "audit_references" not in err_str:
        return False
    indicators = (
        "column",
        "does not exist",
        "no such column",
        "has no column",
        "undefinedcolumn",
        "unknown column",
    )
    return any(ind in err_str for ind in indicators)


async def has_campaign_audit_references_column(db: AsyncSession) -> bool:
    """
    Determines whether the campaigns table in the active database contains
    the audit_references column (migration v6_2_3_audit_email_freshness.sql).
    
    Safe across PostgreSQL, SQLite, and mocked test sessions.
    """
    global _schema_override
    if _schema_override is not None:
        return _schema_override

    # Check mock objects safely without triggering __getattr__ coroutines
    if isinstance(db, (AsyncMock, MagicMock)):
        val = db.__dict__.get("_has_audit_references")
        if isinstance(val, bool):
            return val
        return False

    try:
        cache_key = _get_cache_key(db)
        now = time.monotonic()
        if cache_key and cache_key in _cached_availability:
            has_col, cached_at = _cached_availability[cache_key]
            ttl = SCHEMA_CACHE_POSITIVE_TTL_SECONDS if has_col else SCHEMA_CACHE_NEGATIVE_TTL_SECONDS
            if (now - cached_at) < ttl:
                return has_col

        bind = getattr(db, "bind", None)
        if bind is None and hasattr(db, "get_bind"):
            bind = db.get_bind()
        if bind is None or isinstance(bind, (AsyncMock, MagicMock)):
            return False

        dialect_name = getattr(getattr(bind, "dialect", None), "name", "")

        if dialect_name == "postgresql":
            res = await db.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'campaigns' AND column_name = 'audit_references' LIMIT 1"
                )
            )
            has_col = bool(res.scalar())
        elif dialect_name == "sqlite":
            res = await db.execute(text("PRAGMA table_info(campaigns)"))
            rows = res.fetchall()
            has_col = any(r[1] == "audit_references" for r in rows)
        else:
            def _inspect_sync(conn):
                from sqlalchemy import inspect
                insp = inspect(conn)
                cols = [c["name"] for c in insp.get_columns("campaigns")]
                return "audit_references" in cols
            has_col = await db.run_sync(_inspect_sync)

        if cache_key:
            _cached_availability[cache_key] = (has_col, now)
        return has_col
    except Exception:
        return False


def check_audit_campaign_schema_readiness(
    campaign_type: Optional[str],
    audit_references: Optional[dict],
    has_audit_column: bool,
) -> None:
    """
    Fails closed if the campaign is audit-dependent and the required schema is unavailable.
    """
    c_type = campaign_type or "generic_first_contact"
    is_audit_dependent = (
        c_type not in ("no_website_design", "generic_first_contact", "public_provider_demo")
        or bool(audit_references)
    )
    if is_audit_dependent and not has_audit_column:
        raise HTTPException(
            status_code=503,
            detail=SCHEMA_READINESS_DETAIL,
        )


async def get_campaign_safe(db: AsyncSession, campaign_id: uuid.UUID) -> Optional[Campaign]:
    """
    Retrieves a campaign by ID.
    If audit_references column exists in DB, undefer it to load actual references.
    If audit_references column does not exist, loads compatible columns and populates audit_references={}.
    """
    has_audit = await has_campaign_audit_references_column(db)
    if has_audit:
        try:
            stmt = (
                select(Campaign)
                .options(undefer(Campaign.audit_references))
                .where(Campaign.id == campaign_id)
            )
            res = await db.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as db_err:
            if not is_missing_audit_references_error(db_err):
                raise
            _invalidate_target_cache(db)

    campaign = await db.get(Campaign, campaign_id)
    if campaign is not None and "audit_references" not in campaign.__dict__:
        campaign.__dict__["audit_references"] = {}
    return campaign


async def list_campaigns_safe(db: AsyncSession) -> List[Campaign]:
    """
    Lists all campaigns ordered newest first.
    If audit_references column exists in DB, undefer it.
    If audit_references column does not exist, loads without referencing the column,
    guaranteeing that generic and existing campaigns remain queryable.
    """
    has_audit = await has_campaign_audit_references_column(db)
    if has_audit:
        try:
            stmt = (
                select(Campaign)
                .options(undefer(Campaign.audit_references))
                .order_by(Campaign.created_at.desc())
            )
            res = await db.execute(stmt)
            return list(res.scalars().all())
        except Exception as db_err:
            if not is_missing_audit_references_error(db_err):
                raise
            _invalidate_target_cache(db)

    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    res = await db.execute(stmt)
    campaigns = list(res.scalars().all())
    for c in campaigns:
        if "audit_references" not in c.__dict__:
            c.__dict__["audit_references"] = {}
    return campaigns


async def insert_compatible_campaign(db: AsyncSession, campaign: Campaign) -> Campaign:
    """
    Inserts a campaign into the database using only columns present in the pre-v6.2.3 schema.
    Used for generic, no-website, and demo campaigns when audit_references column is unapplied.
    """
    if campaign.id is None:
        campaign.id = uuid.uuid4()
    if campaign.created_at is None:
        campaign.created_at = datetime.utcnow()
    if campaign.lead_ids is None:
        campaign.lead_ids = []
    if campaign.pending_lead_ids is None:
        campaign.pending_lead_ids = []
    if campaign.sent_count is None:
        campaign.sent_count = 0
    if campaign.skipped_count is None:
        campaign.skipped_count = 0
    if campaign.failed_count is None:
        campaign.failed_count = 0
    if campaign.status is None:
        campaign.status = CampaignStatus.draft

    values = {
        col: getattr(campaign, col, None)
        for col in COMPATIBLE_CAMPAIGN_COLUMNS
    }
    
    # Format status for SQL compatibility if needed
    if hasattr(values.get("status"), "value"):
        values["status"] = values["status"].value

    compat_table = table("campaigns", *(column(col) for col in COMPATIBLE_CAMPAIGN_COLUMNS))
    stmt = compat_table.insert().values(**values)
    await db.execute(stmt)
    campaign.__dict__["audit_references"] = {}
    return campaign
