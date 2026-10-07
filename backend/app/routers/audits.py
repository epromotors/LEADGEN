import uuid
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import os

from app.database import get_db
from app.models import Audit, Lead, AuditStatus, ActivityLog
from app.schemas import AuditResponse
from app.engines.audit_engine import run_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audits", tags=["audits"])


# ── Global batch-run state ────────────────────────────────────────────────────
# Lives at module level — survives across requests, reset when batch finishes.

_BATCH_RUNNING: bool = False          # True while run_batched is executing
_BATCH_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore(concurrency: int) -> asyncio.Semaphore:
    """Return (or recreate) the module-level semaphore for the given concurrency."""
    global _BATCH_SEMAPHORE
    if _BATCH_SEMAPHORE is None or _BATCH_SEMAPHORE._value != concurrency:  # type: ignore[attr-defined]
        _BATCH_SEMAPHORE = asyncio.Semaphore(concurrency)
    return _BATCH_SEMAPHORE


# ── Capacity-controlled batch runner ─────────────────────────────────────────

async def run_batched(
    lead_ids: list[str],
    concurrency: int = 3,
    delay_between: float = 1.5,
) -> None:
    """
    Background coroutine: processes lead_ids with bounded concurrency.

    At most `concurrency` audits run simultaneously — controlled by an
    asyncio.Semaphore. As soon as one audit finishes, the next one starts
    automatically. No "batch then big sleep" thundering herd.

    `delay_between` staggers task *creation* so network/DB writes are spread
    over time rather than all spiking in the same millisecond.

    Error isolation: each audit is individually try/excepted so one failure
    never cancels the rest of the queue.
    """
    global _BATCH_RUNNING
    _BATCH_RUNNING = True
    sem = _get_semaphore(concurrency)

    async def _run_one(lid: str) -> None:
        async with sem:
            try:
                logger.info(f"[batch] Starting audit for lead {lid}")
                await run_audit(lid)
                logger.info(f"[batch] Finished audit for lead {lid}")
            except Exception as exc:
                logger.error(f"[batch] Audit for {lid} failed: {exc}", exc_info=True)
            # Brief post-audit pause so DB connections are fully returned
            # before the next waiter from the semaphore queue acquires them.
            await asyncio.sleep(0.5)

    try:
        tasks: list[asyncio.Task] = []
        for i, lid in enumerate(lead_ids):
            task = asyncio.create_task(_run_one(lid))
            tasks.append(task)
            # Stagger task creation — prevents all coroutines from racing to
            # acquire the semaphore at the exact same moment.
            if i < len(lead_ids) - 1:
                await asyncio.sleep(delay_between)

        # Wait for every task (including those still queued behind the semaphore)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failures = sum(1 for r in results if isinstance(r, Exception))
        logger.info(
            f"[batch] Batch complete — "
            f"{len(lead_ids) - failures}/{len(lead_ids)} succeeded, "
            f"{failures} failed."
        )
    except Exception as exc:
        logger.error(f"[batch] Fatal batch-runner error: {exc}", exc_info=True)
    finally:
        _BATCH_RUNNING = False


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/trigger/{lead_id}", summary="Trigger SEO audit for a lead")
async def trigger_audit(
    lead_id: uuid.UUID,
    background_tasks: BackgroundTasks,
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
        existing.error_message = None
        await db.commit()
        audit = existing
    else:
        audit = Audit(lead_id=lead_id, status=AuditStatus.pending)
        db.add(audit)
        await db.commit()
        await db.refresh(audit)

    background_tasks.add_task(run_audit, str(lead_id))

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
    """Returns counts grouped by lead.status plus skipped count and batch_running flag."""
    rows = await db.execute(
        select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    )
    counts = {row[0]: row[1] for row in rows.fetchall()}
    total = sum(counts.values())

    skipped_result = await db.execute(
        select(func.count(Audit.id)).where(
            Audit.error_message.like("SITE_STATUS:%")
        )
    )
    skipped_count = skipped_result.scalar_one_or_none() or 0

    return {
        "total":         total,
        "new":           counts.get("new",      0),
        "auditing":      counts.get("auditing", 0),
        "audited":       counts.get("audited",  0),
        "emailed":       counts.get("emailed",  0),
        "replied":       counts.get("replied",  0),
        "skipped":       skipped_count,
        "batch_running": _BATCH_RUNNING,   # frontend uses this to prevent double-trigger
    }


@router.get("/batch-status", summary="Lightweight: is a batch audit currently running?")
async def get_batch_status():
    """Cheap endpoint — no DB query. Frontend polls this to know if a batch is live."""
    return {"batch_running": _BATCH_RUNNING}


@router.post("/trigger-all", summary="Trigger audits — mode: new_only | not_emailed | force_all")
async def trigger_all_audits(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    mode: str = Query("new_only", description="new_only | not_emailed | force_all"),
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
    As each one finishes, the next one starts — no thundering-herd batches.
    """
    global _BATCH_RUNNING

    if _BATCH_RUNNING:
        raise HTTPException(
            status_code=409,
            detail="A batch audit is already running. Wait for it to finish.",
        )

    from sqlalchemy import exists, and_

    if mode == "force_all":
        result = await db.execute(select(Lead))
    elif mode == "not_emailed":
        result = await db.execute(
            select(Lead).where(Lead.status.in_(["new", "audited"]))
        )
    else:  # new_only (default)
        has_done_audit = exists(
            select(Audit.id).where(
                and_(Audit.lead_id == Lead.id, Audit.status == AuditStatus.done)
            )
        )
        result = await db.execute(select(Lead).where(~has_done_audit))

    leads = result.scalars().all()

    triggered = 0
    lead_ids_to_audit: list[str] = []

    for lead in leads:
        audit_result = await db.execute(
            select(Audit).where(Audit.lead_id == lead.id)
        )
        existing = audit_result.scalar_one_or_none()

        if existing and existing.status == AuditStatus.running:
            continue  # already in progress

        if not existing:
            new_audit = Audit(lead_id=lead.id, status=AuditStatus.pending)
            db.add(new_audit)
        else:
            existing.status = AuditStatus.pending
            existing.error_message = None

        lead_ids_to_audit.append(str(lead.id))
        triggered += 1

    await db.commit()

    if lead_ids_to_audit:
        background_tasks.add_task(run_batched, lead_ids_to_audit, concurrency, delay_secs)

    log = ActivityLog(
        event_type="audit_triggered",
        message=(
            f"Bulk audit triggered for {triggered} leads "
            f"(mode={mode}, concurrency={concurrency})."
        ),
    )
    db.add(log)
    await db.commit()

    return {
        "triggered":   triggered,
        "mode":        mode,
        "concurrency": concurrency,
    }


@router.post("/trigger-skipped", summary="Re-trigger audits for all skipped sites")
async def trigger_skipped_audits(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
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
    global _BATCH_RUNNING

    if _BATCH_RUNNING:
        raise HTTPException(
            status_code=409,
            detail="A batch audit is already running. Wait for it to finish.",
        )

    skipped_result = await db.execute(
        select(Audit).where(Audit.error_message.like("SITE_STATUS:%"))
    )
    skipped_audits = skipped_result.scalars().all()

    triggered = 0
    lead_ids_to_audit: list[str] = []

    for audit in skipped_audits:
        if audit.status == AuditStatus.running:
            continue
        audit.status = AuditStatus.pending
        audit.error_message = None
        lead_ids_to_audit.append(str(audit.lead_id))
        triggered += 1

    await db.commit()

    if lead_ids_to_audit:
        background_tasks.add_task(run_batched, lead_ids_to_audit, concurrency, delay_secs)

    log = ActivityLog(
        event_type="audit_triggered",
        message=f"Re-triggered {triggered} skipped audit(s) (concurrency={concurrency}).",
    )
    db.add(log)
    await db.commit()

    return {"triggered": triggered, "mode": "skipped_only"}


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
    return audit
