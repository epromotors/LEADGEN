import uuid
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import os

from app.database import get_db, AsyncSessionLocal
from app.models import Audit, AuditBatchSession, Lead, AuditStatus, LeadStatus, ActivityLog
from app.schemas import AuditResponse, AuditTriggerRequest
from app.engines.audit_engine import run_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audits", tags=["audits"])


# ── Global batch-run state ────────────────────────────────────────────────────
# Lives at module level — survives across requests, reset when batch finishes.

_BATCH_STATUS: str = "idle"           # "idle" | "running" | "paused"
_BATCH_RUNNING: bool = False          # True while run_batched is executing (compat)
_BATCH_SEMAPHORE: asyncio.Semaphore | None = None
_BATCH_EVENT: asyncio.Event | None = None
_BATCH_CANCELLED: bool = False
_BATCH_QUEUE: asyncio.Queue[str] | None = None
_BATCH_WORKER_TASKS: list[asyncio.Task] = []
_BATCH_SESSION_ID: str | None = None
_BATCH_STATS: dict[str, int] = {
    "total": 0,
    "completed": 0,
    "succeeded": 0,
    "failed": 0,
    "remaining": 0,
}


def is_batch_cancelled() -> bool:
    """Return True if the batch audit run has been cancelled/stopped."""
    return bool(_BATCH_CANCELLED)


def _get_batch_event() -> asyncio.Event:
    """Return (or create) the module-level event for pausing/resuming workers."""
    global _BATCH_EVENT
    if _BATCH_EVENT is None:
        _BATCH_EVENT = asyncio.Event()
        _BATCH_EVENT.set()
    return _BATCH_EVENT


def _get_semaphore(concurrency: int) -> asyncio.Semaphore:
    """Return (or recreate) the module-level semaphore for the given concurrency."""
    global _BATCH_SEMAPHORE
    if _BATCH_SEMAPHORE is None or _BATCH_SEMAPHORE._value != concurrency:  # type: ignore[attr-defined]
        _BATCH_SEMAPHORE = asyncio.Semaphore(concurrency)
    return _BATCH_SEMAPHORE


def _session_stats(session: AuditBatchSession) -> dict[str, int]:
    return {
        "total": session.total,
        "completed": session.completed,
        "succeeded": session.succeeded,
        "failed": session.failed,
        "remaining": len(session.remaining_lead_ids or []) + len(session.in_flight_lead_ids or []),
    }


def _audit_scope_predicates():
    """Canonical, audit-history-based predicates for counts and batch selection."""
    from sqlalchemy import and_, exists

    has_any_audit = exists(select(Audit.id).where(Audit.lead_id == Lead.id))
    has_failed_audit = exists(
        select(Audit.id).where(
            and_(Audit.lead_id == Lead.id, Audit.status == AuditStatus.failed)
        )
    )
    has_active_audit = exists(
        select(Audit.id).where(
            and_(Audit.lead_id == Lead.id, Audit.status.in_([AuditStatus.pending, AuditStatus.running]))
        )
    )
    has_restart_interrupted_audit = exists(
        select(Audit.id).where(
            and_(
                Audit.lead_id == Lead.id,
                Audit.status == AuditStatus.failed,
                Audit.error_message == "Server restarted while audit was in-flight or queued.",
            )
        )
    )
    return {
        "never_audited": ~has_any_audit,
        "retryable_failed": has_failed_audit,
        "in_progress": has_active_audit,
        "restart_interrupted": has_restart_interrupted_audit,
    }


async def _claim_session_lead(session_id: str, lead_id: str) -> None:
    """Atomically move one lead from the durable queue into in-flight state.

    Raises RuntimeError if the session is no longer running (e.g. paused) so
    the caller can requeue the lead back into the in-memory queue.
    """
    async with AsyncSessionLocal() as session:
        batch = await session.get(AuditBatchSession, uuid.UUID(session_id), with_for_update=True)
        if not batch or batch.status != "running":
            raise RuntimeError(f"Batch session {session_id} is no longer runnable (status={getattr(batch, 'status', 'missing')}); claim rejected.")
        remaining = list(batch.remaining_lead_ids or [])
        if lead_id in remaining:
            remaining.remove(lead_id)
        in_flight = list(batch.in_flight_lead_ids or [])
        if lead_id not in in_flight:
            in_flight.append(lead_id)
        batch.remaining_lead_ids = remaining
        batch.in_flight_lead_ids = in_flight
        await session.commit()


async def _record_session_result(session_id: str, lead_id: str, succeeded: bool) -> None:
    """Persist worker completion without allowing a cancelled session to revive."""
    async with AsyncSessionLocal() as session:
        batch = await session.get(AuditBatchSession, uuid.UUID(session_id), with_for_update=True)
        if not batch:
            return
        in_flight = list(batch.in_flight_lead_ids or [])
        if lead_id in in_flight:
            in_flight.remove(lead_id)
            batch.completed += 1
            if succeeded:
                batch.succeeded += 1
            else:
                batch.failed += 1
        batch.in_flight_lead_ids = in_flight
        await session.commit()


async def _finish_session(session_id: str, cancelled: bool) -> None:
    async with AsyncSessionLocal() as session:
        batch = await session.get(AuditBatchSession, uuid.UUID(session_id), with_for_update=True)
        if not batch or batch.status == "cancelled":
            return
        if cancelled:
            batch.status = "cancelled"
            batch.interruption_reason = "Cancelled by operator."
        else:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)
        await session.commit()


async def recover_interrupted_batch_sessions() -> int:
    """Make pre-restart batches resumable; audit rows are reconciled by lifespan."""
    from sqlalchemy import update

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(AuditBatchSession)
            .where(AuditBatchSession.status.in_(["running", "paused"]))
            .values(
                status="interrupted",
                interruption_reason="Server restarted before the batch completed.",
                interrupted_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result.rowcount or 0


# ── Capacity-controlled batch runner with Pause/Resume/Cancel ─────────────────

async def run_batched(
    lead_ids: list[str],
    concurrency: int = 3,
    delay_between: float = 1.5,
    session_id: str | None = None,
) -> None:
    """
    Background coroutine: processes lead_ids with bounded concurrency and
    support for pause, resume, and cancellation.

    At most `concurrency` audits run simultaneously via dedicated worker tasks.
    Pause event halts idle workers from pulling next lead.
    In-flight audits finish cleanly before pausing.
    """
    global _BATCH_STATUS, _BATCH_RUNNING, _BATCH_CANCELLED, _BATCH_QUEUE, _BATCH_WORKER_TASKS, _BATCH_STATS, _BATCH_SESSION_ID

    _BATCH_STATUS = "running"
    _BATCH_RUNNING = True
    _BATCH_CANCELLED = False
    _BATCH_SESSION_ID = session_id

    event = _get_batch_event()
    event.set()

    _BATCH_QUEUE = asyncio.Queue()
    for lid in lead_ids:
        _BATCH_QUEUE.put_nowait(lid)

    _BATCH_STATS = {
        "total": len(lead_ids),
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": len(lead_ids),
    }

    async def _worker(worker_id: int) -> None:
        # Slight initial stagger between workers
        if worker_id > 0:
            await asyncio.sleep(min(delay_between * worker_id, 3.0))

        while not _BATCH_CANCELLED:
            # 1. Wait if paused
            await event.wait()
            if _BATCH_CANCELLED:
                break

            # 2. Pull next lead
            try:
                lid = _BATCH_QUEUE.get_nowait()
            except (asyncio.QueueEmpty, AttributeError):
                break

            # 3. Claim the lead in the durable session, then audit it.
            # If the claim is rejected (session paused between dequeue and claim),
            # put the lead back into the in-memory queue so Pause → Resume is safe.
            succeeded = False
            claim_rejected = False
            try:
                if session_id:
                    await _claim_session_lead(session_id, lid)
                logger.info(f"[batch-w{worker_id}] Starting audit for lead {lid}")
                await run_audit(lid)
                succeeded = True
                _BATCH_STATS["succeeded"] += 1
                logger.info(f"[batch-w{worker_id}] Finished audit for lead {lid}")
            except RuntimeError as exc:
                # Claim rejected — session is paused or cancelled.  Requeue the
                # lead so Pause → Resume (same process) can pick it up again.
                claim_rejected = True
                logger.warning(f"[batch-w{worker_id}] Claim rejected for {lid}, requeueing: {exc}")
                if _BATCH_QUEUE is not None:
                    await _BATCH_QUEUE.put(lid)
                    _BATCH_STATS["remaining"] = max(0, _BATCH_QUEUE.qsize())
            except asyncio.CancelledError:
                logger.info(f"[batch-w{worker_id}] Audit for lead {lid} cancelled by operator.")
                try:
                    async with AsyncSessionLocal() as cdb:
                        lead_u = uuid.UUID(lid)
                        ld = await cdb.get(Lead, lead_u)
                        if ld and ld.status == LeadStatus.auditing:
                            ld.status = LeadStatus.new
                        aud_res = await cdb.execute(select(Audit).where(Audit.lead_id == lead_u))
                        aud = aud_res.scalar_one_or_none()
                        if aud and aud.status in (AuditStatus.running, AuditStatus.pending):
                            await cdb.delete(aud)
                        await cdb.commit()
                except Exception as clean_err:
                    logger.warning(f"[batch-w{worker_id}] Error cleaning up cancelled lead {lid}: {clean_err}")
                raise
            except Exception as exc:
                _BATCH_STATS["failed"] += 1
                logger.error(f"[batch-w{worker_id}] Audit for {lid} failed: {exc}", exc_info=True)
            finally:
                if not claim_rejected and not _BATCH_CANCELLED:
                    _BATCH_STATS["completed"] += 1
                    if session_id:
                        await _record_session_result(session_id, lid, succeeded)
                if _BATCH_QUEUE:
                    _BATCH_STATS["remaining"] = max(0, _BATCH_QUEUE.qsize())
                    try:
                        _BATCH_QUEUE.task_done()
                    except ValueError:
                        pass

            # 4. Spacing between tasks
            await asyncio.sleep(delay_between)

    try:
        workers = [
            asyncio.create_task(_worker(i))
            for i in range(concurrency)
        ]
        _BATCH_WORKER_TASKS = workers
        results = await asyncio.gather(*workers, return_exceptions=True)

        failures = sum(1 for r in results if isinstance(r, Exception))
        logger.info(
            f"[batch] Batch run finished — "
            f"{_BATCH_STATS['succeeded']}/{_BATCH_STATS['total']} succeeded, "
            f"{_BATCH_STATS['failed'] + failures} failed/errored."
        )
    except Exception as exc:
        logger.error(f"[batch] Fatal batch-runner error: {exc}", exc_info=True)
    finally:
        if session_id:
            await _finish_session(session_id, _BATCH_CANCELLED)
        _BATCH_STATUS = "idle"
        _BATCH_RUNNING = False
        _BATCH_CANCELLED = False
        _BATCH_SESSION_ID = None
        _BATCH_WORKER_TASKS.clear()



# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/trigger/{lead_id}", summary="Trigger SEO audit for a lead")
async def trigger_audit(
    lead_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: AuditTriggerRequest | None = None,
    keywords: str | None = Query(None, description="Optional comma-separated target keywords"),
    db: AsyncSession = Depends(get_db),
):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    existing = result.scalar_one_or_none()

    if existing and existing.status == AuditStatus.running:
        return {
            "message": "Audit already in progress for this lead.",
            "audit_id": str(existing.id),
        }

    if existing:
        existing.status = AuditStatus.pending
        existing.audit_lifecycle = "PENDING"
        existing.error_message = None
        await db.commit()
        audit = existing
    else:
        audit = Audit(lead_id=lead_id, status=AuditStatus.pending, audit_lifecycle="PENDING")
        db.add(audit)
        await db.commit()
        await db.refresh(audit)

    kw_list = None
    if payload and payload.target_keywords:
        kw_list = [str(k).strip() for k in payload.target_keywords if str(k).strip()]
    elif keywords:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]

    background_tasks.add_task(run_audit, str(lead_id), target_keywords=kw_list)

    log = ActivityLog(
        event_type="audit_triggered",
        lead_id=lead_id,
        message=f"Audit triggered for {lead.business_name} ({lead.website})",
    )
    db.add(log)
    await db.commit()

    return {"message": "Audit started in background.", "audit_id": str(audit.id)}


# ── Stats endpoint — MUST be before /{lead_id} ───────────────────────────────

@router.get("/stats", summary="Real-time lead status counts for progress bar")
async def get_audit_stats(db: AsyncSession = Depends(get_db)):
    """Returns lead-state counts plus canonical audit-history batch scope counts."""
    rows = await db.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    )
    counts = {row[0]: row[1] for row in rows.fetchall()}
    total = sum(counts.values())

    scopes = _audit_scope_predicates()
    scope_result = await db.execute(
        select(
            func.count(Lead.id).filter(scopes["never_audited"]).label("never_audited"),
            func.count(Lead.id).filter(scopes["retryable_failed"]).label("retryable_failed"),
            func.count(Lead.id).filter(scopes["restart_interrupted"]).label("restart_interrupted"),
            func.count(Lead.id).filter(scopes["in_progress"]).label("audits_in_progress"),
            func.count(Lead.id).filter(~scopes["in_progress"]).label("force_all_eligible"),
            func.count(Lead.id).filter(
                Lead.status.in_(["new", "audited"]), ~scopes["in_progress"]
            ).label("not_emailed_eligible"),
        )
    )
    scope_counts = scope_result.one()

    skipped_result = await db.execute(
        select(func.count(Audit.id)).where(
            Audit.error_message.like("SITE_STATUS:%"),
            Audit.status.notin_([AuditStatus.pending, AuditStatus.running]),
        )
    )
    skipped_count = skipped_result.scalar_one_or_none() or 0

    resumable = None
    try:
        resumable_result = await db.execute(
            select(AuditBatchSession)
            .where(AuditBatchSession.status == "interrupted")
            .order_by(AuditBatchSession.updated_at.desc())
            .limit(1)
        )
        resumable = resumable_result.scalar_one_or_none()
    except Exception:
        # audit_batch_sessions table may not yet exist (migration not applied).
        # Silently degrade: resume_available will be False.
        await db.rollback()

    return {
        "total":          total,
        "new":            counts.get("new",      0),
        "auditing":       counts.get("auditing", 0),
        "audited":        counts.get("audited",  0),
        "emailed":        counts.get("emailed",  0),
        "replied":        counts.get("replied",  0),
        "skipped":        skipped_count,
        "never_audited":  scope_counts.never_audited,
        "retryable_failed": scope_counts.retryable_failed,
        "restart_interrupted": scope_counts.restart_interrupted,
        "audits_in_progress": scope_counts.audits_in_progress,
        "force_all_eligible": scope_counts.force_all_eligible,
        "not_emailed_eligible": scope_counts.not_emailed_eligible,
        "batch_running":  _BATCH_STATUS in ("running", "paused"),
        "batch_status":   _BATCH_STATUS,   # "idle" | "running" | "paused"
        "batch_paused":   _BATCH_STATUS == "paused",
        "batch_progress": dict(_BATCH_STATS),
        "resume_available": resumable is not None,
        "resume_session": (
            {
                "id": str(resumable.id),
                "mode": resumable.mode,
                "status": resumable.status,
                "progress": _session_stats(resumable),
            }
            if resumable else None
        ),
    }


@router.get("/batch-status", summary="Lightweight: is a batch audit currently running or paused?")
async def get_batch_status():
    """Cheap endpoint — no DB query. Frontend polls this to know batch state."""
    return {
        "batch_running":  _BATCH_STATUS in ("running", "paused"),
        "batch_status":   _BATCH_STATUS,   # "idle" | "running" | "paused"
        "batch_paused":   _BATCH_STATUS == "paused",
        "batch_progress": dict(_BATCH_STATS),
    }


# ── Batch Controls: Pause / Resume / Stop ────────────────────────────────────

@router.post("/batch/pause", summary="Pause active batch audit crawling")
async def pause_batch_audit(db: AsyncSession = Depends(get_db)):
    global _BATCH_STATUS
    if _BATCH_STATUS == "idle":
        raise HTTPException(status_code=400, detail="No active batch audit is currently running.")
    if _BATCH_STATUS == "paused":
        return {
            "message": "Batch audit is already paused.",
            "status": "paused",
            "stats": dict(_BATCH_STATS),
        }

    _BATCH_STATUS = "paused"
    event = _get_batch_event()
    event.clear()
    if _BATCH_SESSION_ID:
        batch = await db.get(AuditBatchSession, uuid.UUID(_BATCH_SESSION_ID))
        if batch:
            batch.status = "paused"
            await db.commit()

    log = ActivityLog(
        event_type="audit_batch_paused",
        message=f"Batch audit paused ({_BATCH_STATS['completed']}/{_BATCH_STATS['total']} leads processed, {_BATCH_STATS['remaining']} remaining in queue).",
    )
    db.add(log)
    await db.commit()

    return {
        "message": "Batch audit paused. In-flight crawls will finish, then queue will hold.",
        "status": "paused",
        "stats": dict(_BATCH_STATS),
    }


@router.post("/batch/resume", summary="Resume paused batch audit crawling")
async def resume_batch_audit(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    global _BATCH_STATUS
    if _BATCH_STATUS == "idle":
        result = await db.execute(
            select(AuditBatchSession)
            .where(AuditBatchSession.status == "interrupted")
            .order_by(AuditBatchSession.updated_at.desc())
            .limit(1)
            .with_for_update()
        )
        batch = result.scalar_one_or_none()
        if not batch:
            raise HTTPException(status_code=400, detail="No paused or interrupted batch audit is available to resume.")

        lead_ids = list(dict.fromkeys((batch.remaining_lead_ids or []) + (batch.in_flight_lead_ids or [])))
        if not lead_ids:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return {"message": "Interrupted batch had no remaining leads.", "status": "completed", "stats": _session_stats(batch)}

        lead_uuids = [uuid.UUID(lead_id) for lead_id in lead_ids]
        from sqlalchemy import update as _update
        await db.execute(
            _update(Audit)
            .where(Audit.lead_id.in_(lead_uuids), Audit.status.in_([AuditStatus.running, AuditStatus.pending, AuditStatus.failed]))
            .values(status=AuditStatus.pending, audit_lifecycle="PENDING", error_message=None)
        )
        batch.status = "running"
        batch.interruption_reason = None
        batch.interrupted_at = None
        batch.remaining_lead_ids = lead_ids
        batch.in_flight_lead_ids = []
        await db.commit()
        background_tasks.add_task(run_batched, lead_ids, batch.concurrency, batch.delay_secs, str(batch.id))
        return {
            "message": f"Resuming interrupted batch ({len(lead_ids)} lead(s) remaining).",
            "status": "running",
            "stats": _session_stats(batch),
        }
    if _BATCH_STATUS == "running":
        return {
            "message": "Batch audit is already running.",
            "status": "running",
            "stats": dict(_BATCH_STATS),
        }

    _BATCH_STATUS = "running"
    event = _get_batch_event()
    event.set()
    if _BATCH_SESSION_ID:
        batch = await db.get(AuditBatchSession, uuid.UUID(_BATCH_SESSION_ID))
        if batch:
            batch.status = "running"
            await db.commit()

    log = ActivityLog(
        event_type="audit_batch_resumed",
        message=f"Batch audit resumed ({_BATCH_STATS['remaining']} leads remaining in queue).",
    )
    db.add(log)
    await db.commit()

    return {
        "message": "Batch audit resumed.",
        "status": "running",
        "stats": dict(_BATCH_STATS),
    }


@router.post("/batch/stop", summary="Stop/cancel active batch audit crawling")
async def stop_batch_audit(db: AsyncSession = Depends(get_db)):
    global _BATCH_STATUS, _BATCH_CANCELLED, _BATCH_RUNNING
    if _BATCH_STATUS == "idle":
        result = await db.execute(
            select(AuditBatchSession)
            .where(AuditBatchSession.status.in_(["running", "paused", "interrupted"]))
            .order_by(AuditBatchSession.updated_at.desc())
            .limit(1)
            .with_for_update()
        )
        durable_batch = result.scalar_one_or_none()
        if durable_batch:
            was_interrupted = durable_batch.status == "interrupted"
            durable_batch.status = "cancelled"
            durable_batch.interruption_reason = (
                "Interrupted batch discarded by operator."
                if was_interrupted else "Cancelled by operator before local workers were attached."
            )
            await db.commit()
            return {
                "message": (
                    "Interrupted batch discarded. Its failed audits remain available for a later manual retry."
                    if was_interrupted else "Batch cancelled before local workers started."
                ),
                "status": "cancelled",
                "cancelled_count": len(durable_batch.remaining_lead_ids or []) + len(durable_batch.in_flight_lead_ids or []),
            }
        return {
            "message": "No active batch audit is currently running.",
            "status": "idle",
            "cancelled_count": 0,
        }

    _BATCH_CANCELLED = True
    drained_ids: list[str] = []
    if _BATCH_QUEUE:
        while not _BATCH_QUEUE.empty():
            try:
                lid = _BATCH_QUEUE.get_nowait()
                drained_ids.append(lid)
                _BATCH_QUEUE.task_done()
            except (asyncio.QueueEmpty, ValueError):
                break

    # Cancel all in-flight worker tasks immediately so background crawling halts
    for task in _BATCH_WORKER_TASKS:
        if not task.done():
            task.cancel()

    event = _get_batch_event()
    event.set()  # Unblock paused workers so they exit cleanly

    _BATCH_STATUS = "idle"
    _BATCH_RUNNING = False
    in_flight_ids: list[str] = []
    if _BATCH_SESSION_ID:
        batch = await db.get(AuditBatchSession, uuid.UUID(_BATCH_SESSION_ID))
        if batch:
            batch.status = "cancelled"
            batch.interruption_reason = "Cancelled by operator."
            in_flight_ids = list(batch.in_flight_lead_ids or [])
            await db.commit()

    # Reset queued (pending) and in-flight audits so they reappear in
    # new_only scope and can be retried cleanly. Also reset leads still stuck
    # in 'auditing' status back to 'new' so the count stays accurate.
    all_abort_ids = list(dict.fromkeys(drained_ids + in_flight_ids))
    if all_abort_ids:
        try:
            from sqlalchemy import update as _update
            abort_uuids = [uuid.UUID(lid) for lid in all_abort_ids]
            for lead_uuid in abort_uuids:
                audit_res = await db.execute(select(Audit).where(Audit.lead_id == lead_uuid))
                aud = audit_res.scalar_one_or_none()
                if aud and aud.status in (AuditStatus.pending, AuditStatus.running):
                    await db.delete(aud)
            # Reset leads that were queued or in flight back to new
            await db.execute(
                _update(Lead)
                .where(Lead.id.in_(abort_uuids), Lead.status == LeadStatus.auditing)
                .values(status=LeadStatus.new)
            )
            await db.commit()
        except Exception as exc:
            logger.warning(f"[batch] Error cleaning up cancelled audits: {exc}")

    log = ActivityLog(
        event_type="audit_batch_stopped",
        message=f"Batch audit stopped by operator. {len(drained_ids)} queued leads cancelled.",
    )
    db.add(log)
    await db.commit()

    return {
        "message": f"Batch audit stopped. {len(drained_ids)} queued lead(s) cancelled.",
        "status": "idle",
        "cancelled_count": len(drained_ids),
    }


@router.post("/trigger-all", summary="Trigger audits — mode: new_only | retry_failed | not_emailed | force_all")
async def trigger_all_audits(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    mode: str = Query("new_only", description="new_only | retry_failed | not_emailed | force_all"),
    limit: int | None = Query(None, ge=1, description="Max number of leads to audit in this batch"),
    concurrency: int = Query(
        3, ge=1, le=8,
        description="Max simultaneous audits (1–8). 3 is recommended for most machines."
    ),
    delay_secs: float = Query(
        1.5, ge=0.5, le=10.0,
        description="Seconds between individual audit starts (staggers network hits)"
    ),
):
    """
    Triggers audits in a capacity-aware rolling queue.

    concurrency=3 means at most 3 sites are being crawled at any moment.
    As each one finishes, the next one starts — with pause, resume, and limit controls.
    """
    global _BATCH_STATUS, _BATCH_RUNNING

    if _BATCH_STATUS in ("running", "paused"):
        detail = (
            "A batch audit is already running. Wait for it to finish or pause/stop it."
            if _BATCH_STATUS == "running"
            else "A batch audit is currently paused. Resume or stop it before launching a new batch."
        )
        raise HTTPException(status_code=409, detail=detail)

    try:
        existing_batch = await db.execute(
            select(AuditBatchSession.id)
            .where(AuditBatchSession.status.in_(["running", "paused", "interrupted"]))
            .limit(1)
        )
        if existing_batch.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="A durable batch session is still active or interrupted. Resume or stop it before launching a new batch.",
            )
    except HTTPException:
        raise
    except Exception:
        # audit_batch_sessions table not yet present — migration not yet applied.
        # Allow the batch to start; durable session creation below will also be skipped.
        await db.rollback()

    from sqlalchemy import and_, case

    has_website = and_(Lead.website.isnot(None), func.trim(Lead.website) != "")
    scopes = _audit_scope_predicates()
    if mode == "force_all":
        query = select(Lead).where(~scopes["in_progress"])
    elif mode == "not_emailed":
        query = select(Lead).where(Lead.status.in_(["new", "audited"]), ~scopes["in_progress"])
    elif mode == "retry_failed":
        query = select(Lead).where(scopes["retryable_failed"])
    elif mode == "new_only":
        # Compatibility name: new_only is strictly a lead with no Audit row.
        query = select(Lead).where(scopes["never_audited"])
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported audit mode: {mode}")

    # Prioritize leads with actual websites first so batch audits crawl real sites
    query = query.order_by(
        case((has_website, 0), else_=1),
        Lead.created_at.desc(),
    )

    result = await db.execute(query)
    leads = result.scalars().all()

    triggered = 0
    lead_ids_to_audit: list[str] = []

    for lead in leads:
        if limit is not None and triggered >= limit:
            break

        audit_result = await db.execute(
            select(Audit).where(Audit.lead_id == lead.id)
        )
        existing = audit_result.scalar_one_or_none()

        if existing and existing.status in (AuditStatus.pending, AuditStatus.running):
            continue  # never schedule an already-active audit

        if not existing:
            new_audit = Audit(lead_id=lead.id, status=AuditStatus.pending, audit_lifecycle="PENDING")
            db.add(new_audit)
        else:
            existing.status = AuditStatus.pending
            existing.audit_lifecycle = "PENDING"
            existing.error_message = None

        lead_ids_to_audit.append(str(lead.id))
        triggered += 1

    batch_session = None
    if lead_ids_to_audit:
        try:
            batch_session = AuditBatchSession(
                mode=mode,
                remaining_lead_ids=list(lead_ids_to_audit),
                in_flight_lead_ids=[],
                total=triggered,
                concurrency=concurrency,
                delay_secs=delay_secs,
            )
            db.add(batch_session)
            await db.flush()  # obtain batch_session.id before commit
        except Exception:
            # audit_batch_sessions table not yet present.  Run without durable session.
            await db.rollback()
            batch_session = None
    await db.commit()

    if lead_ids_to_audit:
        session_id_arg = str(batch_session.id) if batch_session else None
        background_tasks.add_task(run_batched, lead_ids_to_audit, concurrency, delay_secs, session_id_arg)

    limit_desc = f", limit={limit}" if limit else ""
    log = ActivityLog(
        event_type="audit_triggered",
        message=(
            f"Bulk audit triggered for {triggered} leads "
            f"(mode={mode}{limit_desc}, concurrency={concurrency})."
        ),
    )
    db.add(log)
    await db.commit()

    return {
        "triggered":   triggered,
        "mode":        mode,
        "limit":       limit,
        "concurrency": concurrency,
        "batch_session_id": str(batch_session.id) if batch_session else None,
    }


@router.post("/trigger-skipped", summary="Re-trigger audits for all skipped sites")
async def trigger_skipped_audits(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    limit: int | None = Query(None, ge=1, description="Max number of skipped leads to audit"),
    concurrency: int = Query(
        3, ge=1, le=8,
        description="Max simultaneous audits (1–8). Default 3."
    ),
    delay_secs: float = Query(
        1.5, ge=0.5, le=10.0,
        description="Seconds between individual audit starts"
    ),
):
    """
    Find all leads whose audit was skipped (SITE_STATUS: error_message) and
    re-trigger using the capacity-controlled runner.
    """
    global _BATCH_STATUS, _BATCH_RUNNING

    if _BATCH_STATUS in ("running", "paused"):
        detail = (
            "A batch audit is already running. Wait for it to finish or pause/stop it."
            if _BATCH_STATUS == "running"
            else "A batch audit is currently paused. Resume or stop it before launching a new batch."
        )
        raise HTTPException(status_code=409, detail=detail)

    try:
        existing_batch = await db.execute(
            select(AuditBatchSession.id)
            .where(AuditBatchSession.status.in_(["running", "paused", "interrupted"]))
            .limit(1)
        )
        if existing_batch.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="A durable batch session is still active or interrupted. Resume or stop it before launching a new batch.",
            )
    except HTTPException:
        raise
    except Exception:
        # audit_batch_sessions table not yet present — migration not yet applied.
        # Allow the batch to start; durable session creation below will also be skipped.
        await db.rollback()

    skipped_result = await db.execute(
        select(Audit).where(
            Audit.error_message.like("SITE_STATUS:%"),
            Audit.status.notin_([AuditStatus.pending, AuditStatus.running]),
        )
    )
    skipped_audits = skipped_result.scalars().all()

    triggered = 0
    lead_ids_to_audit: list[str] = []

    for audit in skipped_audits:
        if limit is not None and triggered >= limit:
            break
        audit.status = AuditStatus.pending
        audit.audit_lifecycle = "PENDING"
        audit.error_message = None
        lead_ids_to_audit.append(str(audit.lead_id))
        triggered += 1

    batch_session = None
    if lead_ids_to_audit:
        try:
            batch_session = AuditBatchSession(
                mode="skipped_only",
                remaining_lead_ids=list(lead_ids_to_audit),
                in_flight_lead_ids=[],
                total=triggered,
                concurrency=concurrency,
                delay_secs=delay_secs,
            )
            db.add(batch_session)
            await db.flush()  # obtain batch_session.id before commit
        except Exception:
            # audit_batch_sessions table not yet present.  Run without durable session.
            await db.rollback()
            batch_session = None
    await db.commit()

    if lead_ids_to_audit:
        session_id_arg = str(batch_session.id) if batch_session else None
        background_tasks.add_task(run_batched, lead_ids_to_audit, concurrency, delay_secs, session_id_arg)

    limit_desc = f", limit={limit}" if limit else ""
    log = ActivityLog(
        event_type="audit_triggered",
        message=f"Re-triggered {triggered} skipped audit(s){limit_desc} (concurrency={concurrency}).",
    )
    db.add(log)
    await db.commit()

    return {"triggered": triggered, "mode": "skipped_only", "limit": limit}


# ── Static routes MUST come before /{lead_id} to avoid UUID parse errors ──────

@router.get("/pdf/{lead_id}", summary="Download audit PDF report")
async def download_pdf(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    audit = result.scalar_one_or_none()
    if not audit or not audit.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not yet generated for this lead.")
    if not os.path.exists(audit.pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")
    lead = await db.get(Lead, lead_id)
    filename = f"TEB-SEO-Audit-{lead.business_name.replace(' ', '_')}.pdf"
    return FileResponse(audit.pdf_path, media_type="application/pdf", filename=filename)


@router.get("/{lead_id}", response_model=AuditResponse, summary="Get audit results")
async def get_audit(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="No audit found for this lead.")

    # ── Phase 2: Expose browser evidence from site_summary as top-level fields ─
    # site_summary is a JSON column; browser fields are stored there and surfaced
    # as convenience fields on AuditResponse for API consumers.
    site_summary = audit.site_summary or {}
    browser_evidence = site_summary.get("browser_evidence") or None
    browser_status   = site_summary.get("browser_status") or None
    browser_pages    = site_summary.get("browser_pages") or None

    # Build response dict from ORM model attributes, then inject browser fields
    audit_data = AuditResponse.model_validate(audit)
    if browser_evidence is not None:
        audit_data.browser_evidence = browser_evidence
    if browser_status is not None:
        audit_data.browser_status = browser_status
    if browser_pages is not None:
        audit_data.browser_pages = browser_pages

    return audit_data
