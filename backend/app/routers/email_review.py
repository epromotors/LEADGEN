"""
email_review.py — Backend router for email mismatch detection and correction review.

Endpoints:
  POST /email-review/scan          — Scan ALL leads (any status) for email mismatches
  GET  /email-review/              — List pending/all corrections
  POST /email-review/{id}/accept   — Accept: update lead email + reset status to 'new'
  POST /email-review/{id}/dismiss  — Dismiss: keep old email, mark reviewed
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, AsyncSessionLocal
from app.models import (
    Lead, LeadStatus, Audit, EmailCorrection, ActivityLog
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/email-review", tags=["email-review"])


# ── Pydantic response schema ──────────────────────────────────────────────────

class EmailCorrectionResponse(BaseModel):
    id: str
    lead_id: str
    business_name: str
    website: str
    old_email: str
    new_email: str
    source: str
    status: str
    detected_at: datetime
    reviewed_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Background scan job ───────────────────────────────────────────────────────

async def _scan_all_emails_bg(only_unscanned: bool = False):
    """
    Background task: iterate every lead with a website, fetch + scrape for a
    domain-matched email, and record mismatches in email_corrections table.
    Skips leads already with a pending correction entry.
    """
    # Import here to avoid circular imports at startup
    import sys
    from pathlib import Path
    auditor_path = Path("C:/Users/LENOVO/LEADGEN/auditor/auditor")
    if str(auditor_path) not in sys.path:
        sys.path.insert(0, str(auditor_path))

    try:
        from auditor.email_finder import find_domain_email, should_update_email
        from auditor.core import make_session as make_http, normalize_url, fetch_page, get_domain
    except ImportError as e:
        logger.error(f"[email-review] Could not import auditor: {e}")
        return

    logger.info("[email-review] Starting full email scan for all leads…")
    found_count = 0
    checked = 0

    async with AsyncSessionLocal() as db:
        # Fetch leads that have a website
        q = select(Lead).where(Lead.website.isnot(None), Lead.website != "")
        if only_unscanned:
            q = q.where(Lead.last_email_scan_at.is_(None))
        result = await db.execute(q)
        leads = result.scalars().all()
        total = len(leads)
        logger.info(f"[email-review] Scanning {total} leads…")

        for lead in leads:
            try:
                checked += 1
                website = lead.website

                # Check if a pending correction already exists for this lead
                existing = await db.execute(
                    select(EmailCorrection).where(
                        EmailCorrection.lead_id == lead.id,
                        EmailCorrection.status == "pending",
                    )
                )
                if existing.scalar_one_or_none():
                    continue  # already has pending review

                # Run HTTP fetch + email finder in thread pool
                loop = asyncio.get_running_loop()

                def _find(url, db_email):
                    try:
                        http = make_http()
                        norm = normalize_url(url)
                        page = fetch_page(norm, http)
                        if not page["ok"]:
                            return None, None
                        domain = get_domain(norm)
                        em, src = find_domain_email(
                            website_url=norm,
                            homepage_soup=page["soup"],
                            homepage_html=page["html"],
                            session=http,
                        )
                        host = domain.lstrip("www.")
                        if em and should_update_email(db_email, em, host):
                            return em, src
                        return None, None
                    except Exception as ex:
                        logger.debug(f"[email-review] scan error for {url}: {ex}")
                        return None, None

                found_email, source = await loop.run_in_executor(
                    None, _find, website, lead.email
                )

                if found_email:
                    correction = EmailCorrection(
                        lead_id=lead.id,
                        old_email=lead.email,
                        new_email=found_email,
                        source=source or "website",
                        status="pending",
                    )
                    db.add(correction)
                    
                # Mark as scanned
                lead.last_email_scan_at = datetime.utcnow()
                await db.commit()
                
                if found_email:
                    found_count += 1
                    logger.info(
                        f"[email-review] Mismatch: {lead.business_name} "
                        f"{lead.email!r} → {found_email!r}"
                    )

            except Exception as e:
                logger.warning(f"[email-review] Error scanning lead {lead.id}: {e}")
                continue

    logger.info(
        f"[email-review] Scan complete. Checked: {checked}/{total}, "
        f"New corrections: {found_count}"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/scan", summary="Scan ALL leads for email mismatches (background job)")
async def scan_emails(
    background_tasks: BackgroundTasks, 
    only_unscanned: bool = Query(False),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers a background scan of every lead with a website.
    For each lead whose stored email differs from the domain-matched email on
    the site, a pending `EmailCorrection` record is created.
    Already-pending corrections are not duplicated.
    """
    background_tasks.add_task(_scan_all_emails_bg, only_unscanned)

    db.add(ActivityLog(
        event_type="email_scan_started",
        message="Full email mismatch scan started for all leads.",
    ))
    await db.commit()

    return {"message": "Email scan started in background. Check /email-review/ for results."}


@router.get("/", summary="List email corrections")
async def list_corrections(
    status: Optional[str] = Query("pending", description="Filter: pending | accepted | dismissed | all"),
    db: AsyncSession = Depends(get_db),
):
    """Return email correction records. Default: only pending ones."""
    q = select(EmailCorrection).options(selectinload(EmailCorrection.lead))

    if status and status != "all":
        q = q.where(EmailCorrection.status == status)

    q = q.order_by(EmailCorrection.detected_at.desc())
    result = await db.execute(q)
    corrections = result.scalars().all()

    items = []
    for c in corrections:
        items.append({
            "id": str(c.id),
            "lead_id": str(c.lead_id),
            "business_name": c.lead.business_name if c.lead else "Unknown",
            "website": c.lead.website if c.lead else "",
            "old_email": c.old_email,
            "new_email": c.new_email,
            "source": c.source,
            "status": c.status,
            "detected_at": c.detected_at.isoformat() if c.detected_at else None,
            "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
            "lead_status": c.lead.status.value if c.lead else None,
        })
    return {"total": len(items), "items": items}


@router.post("/{correction_id}/accept", summary="Accept a correction: update lead email + reset to NEW")
async def accept_correction(
    correction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Accept the suggested email:
      - Updates lead.email to new_email
      - Resets lead.status to 'new' so it gets re-audited / re-emailed fresh
      - Clears last_emailed_at so the outreach engine treats it as unsent
      - Marks correction as 'accepted'
      - Logs to ActivityLog
    """
    correction = await db.get(EmailCorrection, correction_id)
    if not correction:
        raise HTTPException(status_code=404, detail="Correction not found.")
    if correction.status != "pending":
        raise HTTPException(status_code=409, detail=f"Correction is already '{correction.status}'.")

    lead = await db.get(Lead, correction.lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    old_email = lead.email
    lead.email = correction.new_email
    lead.status = LeadStatus.new
    lead.last_emailed_at = None
    lead.replied_at = None
    lead.reply_snippet = None
    lead.reply_type = None

    correction.status = "accepted"
    correction.reviewed_at = datetime.utcnow()

    db.add(ActivityLog(
        event_type="email_accepted",
        lead_id=lead.id,
        message=(
            f"Email correction accepted for {lead.business_name}: "
            f"{old_email!r} → {correction.new_email!r}. "
            f"Lead reset to 'new' for fresh audit + outreach."
        ),
    ))
    await db.commit()

    return {
        "message": "Email updated. Lead reset to 'new'.",
        "lead_id": str(lead.id),
        "old_email": old_email,
        "new_email": lead.email,
        "lead_status": "new",
    }


@router.post("/{correction_id}/dismiss", summary="Dismiss: keep current email, no change to lead")
async def dismiss_correction(
    correction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark the correction as dismissed — lead email stays unchanged."""
    correction = await db.get(EmailCorrection, correction_id)
    if not correction:
        raise HTTPException(status_code=404, detail="Correction not found.")
    if correction.status != "pending":
        raise HTTPException(status_code=409, detail=f"Correction is already '{correction.status}'.")

    lead = await db.get(Lead, correction.lead_id)
    biz = lead.business_name if lead else "Unknown"

    correction.status = "dismissed"
    correction.reviewed_at = datetime.utcnow()

    db.add(ActivityLog(
        event_type="email_dismissed",
        lead_id=correction.lead_id,
        message=(
            f"Email correction dismissed for {biz}: "
            f"keeping {correction.old_email!r} (suggested: {correction.new_email!r})."
        ),
    ))
    await db.commit()

    return {
        "message": "Correction dismissed. Lead email unchanged.",
        "correction_id": str(correction_id),
    }


@router.get("/stats", summary="Count of pending corrections")
async def correction_stats(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    total_q    = select(func.count()).select_from(EmailCorrection)
    pending_q  = select(func.count()).select_from(EmailCorrection).where(EmailCorrection.status == "pending")
    accepted_q = select(func.count()).select_from(EmailCorrection).where(EmailCorrection.status == "accepted")
    dismissed_q= select(func.count()).select_from(EmailCorrection).where(EmailCorrection.status == "dismissed")

    total     = (await db.execute(total_q)).scalar_one()
    pending   = (await db.execute(pending_q)).scalar_one()
    accepted  = (await db.execute(accepted_q)).scalar_one()
    dismissed = (await db.execute(dismissed_q)).scalar_one()
    return {"total": total, "pending": pending, "accepted": accepted, "dismissed": dismissed}
