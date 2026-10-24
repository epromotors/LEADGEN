"""
backend/app/services/campaign_scheduler.py
------------------------------------------
Bounded autonomous scheduler and orchestrator for due LEADGEN campaigns.

Guarantees:
1. Discovers campaigns where status == 'scheduled' and scheduled_at <= now().
2. Uses atomic row-level claiming (FOR UPDATE SKIP LOCKED on PostgreSQL) to prevent
   duplicate claims across concurrent scheduler processes.
3. Uses singleton scheduler lock during discovery tick to avoid redundant database polling.
4. Bounded work per iteration (batch_size) and bounded concurrent worker cap.
5. Respects existing campaign lifecycle (scheduled, running, paused, done, draft).
6. Clean startup and shutdown lifecycle management via FastAPI.
7. Transient database error resilience with non-spinning backoff.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Campaign, CampaignStatus
from app.services.campaign_lock_service import campaign_lock_coordinator

logger = logging.getLogger(__name__)


class CampaignScheduler:
    """
    Autonomous background orchestrator that discovers and launches due scheduled campaigns.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        poll_interval_seconds: Optional[float] = None,
        batch_size: Optional[int] = None,
        max_concurrent_workers: Optional[int] = None,
    ):
        self.enabled: bool = (
            enabled
            if enabled is not None
            else getattr(settings, "CAMPAIGN_SCHEDULER_ENABLED", True)
        )
        self.poll_interval_seconds: float = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else getattr(settings, "CAMPAIGN_SCHEDULER_POLL_INTERVAL_SECONDS", 30.0)
        )
        self.batch_size: int = (
            batch_size
            if batch_size is not None
            else getattr(settings, "CAMPAIGN_SCHEDULER_BATCH_SIZE", 5)
        )
        self.max_concurrent_workers: int = (
            max_concurrent_workers
            if max_concurrent_workers is not None
            else getattr(settings, "CAMPAIGN_SCHEDULER_MAX_CONCURRENT_WORKERS", 3)
        )

        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._active_worker_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Starts the scheduler background loop if enabled."""
        if not self.enabled:
            logger.info("Campaign scheduler is disabled by configuration (CAMPAIGN_SCHEDULER_ENABLED=False).")
            return

        if self._running:
            logger.warning("Campaign scheduler is already running.")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop(), name="leadgen_campaign_scheduler")
        logger.info(
            "Campaign scheduler started (poll_interval=%.1fs, batch_size=%d, max_workers=%d).",
            self.poll_interval_seconds,
            self.batch_size,
            self.max_concurrent_workers,
        )

    async def stop(self) -> None:
        """Stops the scheduler loop cleanly and waits for background ticks to conclude."""
        if not self._running:
            return

        logger.info("Stopping campaign scheduler...")
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        logger.info("Campaign scheduler stopped.")

    async def _scheduler_loop(self) -> None:
        """Continuous polling loop with safe error handling and backoff."""
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in campaign scheduler tick: %s", e)
                # Avoid rapid retry loop on transient database failure
                await asyncio.sleep(min(10.0, max(2.0, self.poll_interval_seconds / 2)))

            try:
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break

    async def run_once(self, now_override: Optional[datetime] = None) -> int:
        """
        Executes a single bounded scheduling iteration.
        Returns the number of due campaigns successfully claimed and dispatched.
        """
        # Clean up finished worker tasks
        self._active_worker_tasks = {t for t in self._active_worker_tasks if not t.done()}

        # Check local concurrency cap against active workers
        active_worker_count = (
            len(self._active_worker_tasks)
            + len(campaign_lock_coordinator._active_in_process)
        )
        if active_worker_count >= self.max_concurrent_workers:
            logger.info(
                "Campaign scheduler: worker concurrency limit reached (%d/%d). Skipping tick.",
                active_worker_count,
                self.max_concurrent_workers,
            )
            return 0

        available_slots = max(0, self.max_concurrent_workers - active_worker_count)
        query_limit = min(self.batch_size, available_slots)
        if query_limit <= 0:
            return 0

        claimed_campaign_ids: List[str] = []

        now_dt = now_override or datetime.now(timezone.utc).replace(tzinfo=None)

        try:
            async with AsyncSessionLocal() as db:
                # 1. Acquire singleton scheduler lock for this discovery tick (PostgreSQL advisory xact lock)
                has_tick_lock = await campaign_lock_coordinator.try_acquire_scheduler_tick_lock(db)
                if not has_tick_lock:
                    logger.debug("Campaign scheduler: singleton tick lock denied; another process is discovering.")
                    return 0

                # 2. Query due campaigns using FOR UPDATE SKIP LOCKED on PostgreSQL
                stmt = (
                    select(Campaign)
                    .where(
                        Campaign.status == CampaignStatus.scheduled,
                        Campaign.scheduled_at.is_not(None),
                        Campaign.scheduled_at <= now_dt,
                    )
                    .order_by(Campaign.scheduled_at.asc())
                    .limit(query_limit)
                )

                bind = getattr(db, "bind", None)
                dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
                if dialect_name == "postgresql":
                    stmt = stmt.with_for_update(skip_locked=True)

                res = await db.execute(stmt)
                due_campaigns = res.scalars().all()

                if not due_campaigns:
                    return 0

                # 3. Atomically claim each campaign by transitioning status to 'draft'
                # (Worker will immediately transition 'draft' -> 'sending' upon lock acquisition)
                for camp in due_campaigns:
                    if camp.status != CampaignStatus.scheduled:
                        continue
                    camp.status = CampaignStatus.draft
                    claimed_campaign_ids.append(str(camp.id))

                await db.commit()

        except Exception as db_err:
            logger.warning("Campaign scheduler: database error during due-campaign discovery: %s", db_err)
            return 0

        # 4. Dispatch claimed campaigns as asynchronous background worker tasks
        for cid in claimed_campaign_ids:
            task = asyncio.create_task(
                self._dispatch_campaign(cid),
                name=f"campaign_worker_{cid}",
            )
            self._active_worker_tasks.add(task)
            logger.info("Campaign scheduler: claimed and dispatched due campaign %s", cid)

        return len(claimed_campaign_ids)

    async def _dispatch_campaign(self, campaign_id: str) -> None:
        """Invokes outreach engine run_campaign with error containment."""
        try:
            from app.engines.outreach_engine import run_campaign
            await run_campaign(campaign_id)
        except Exception as e:
            logger.exception("Campaign scheduler: error executing campaign %s: %e", campaign_id, e)


# Global singleton scheduler instance
campaign_scheduler = CampaignScheduler()


def get_campaign_scheduler() -> CampaignScheduler:
    """Returns the application-wide campaign scheduler singleton."""
    return campaign_scheduler
