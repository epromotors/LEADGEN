# backend/app/routers/replies.py
# LeadGen OS — Reply Inbox API

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Lead, Audit, ActivityLog, LeadStatus
from app.schemas import LeadResponse, LeadListResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/replies", tags=["replies"])


# ── Background task wrapper ───────────────────────────────────────────────────

async def _run_process_replies() -> None:
    """Thin wrapper so BackgroundTasks can call it without a return value."""
    from app.engines.reply_engine import process_replies
    try:
        stats = await process_replies()
        logger.info(f"[replies] Background sync complete: {stats}")
    except Exception as e:
        logger.error(f"[replies] Background sync error: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/check", summary="Sync inbox — fetch & classify unseen replies")
async def check_replies(background_tasks: BackgroundTasks):
    """
    Triggers a background IMAP fetch of unseen emails from INBOX + Spam.
    Returns immediately; check activity log for results.
    """
    background_tasks.add_task(_run_process_replies)
    return {"triggered": True, "message": "Inbox sync started. Check back in a few seconds."}


@router.post("/check-now", summary="Sync inbox synchronously — returns stats")
async def check_replies_now():
    """
    Runs the full IMAP fetch synchronously and returns the summary stats dict.
    Useful for the frontend to show immediate feedback.

    Stats returned:
      fetched       - total unseen emails downloaded from IMAP
      positive      - emails classified as positive AND matched a lead in DB (actually converted)
      deleted       - leads deleted (bounce or STOP)
      soft_bounce   - leads flagged as OOO (not deleted)
      other         - emails with no matching lead OR unclassified
      errors        - processing errors
    """
    from app.engines.reply_engine import process_replies
    stats = await process_replies()
    return stats


@router.get(
    "/converted",
    response_model=LeadListResponse,
    summary="List converted leads (positive replies)",
)
async def list_converted(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return all leads with status='converted', newest first."""
    base = select(Lead).where(Lead.status == LeadStatus.converted)

    total = (
        await db.execute(select(func.count()).select_from(Lead).where(Lead.status == LeadStatus.converted))
    ).scalar_one()

    result = await db.execute(
        base.order_by(Lead.replied_at.desc().nulls_last())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    leads = result.scalars().all()
    return LeadListResponse(total=total, items=leads)


@router.get(
    "/all-replies",
    response_model=LeadListResponse,
    summary="List ALL replied leads (any reply type)",
)
async def list_all_replies(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return all leads that have a reply_type set (positive, soft_bounce)."""
    base = select(Lead).where(Lead.reply_type != None)

    total = (
        await db.execute(
            select(func.count()).select_from(Lead).where(Lead.reply_type != None)
        )
    ).scalar_one()

    result = await db.execute(
        base.order_by(Lead.replied_at.desc().nulls_last())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    leads = result.scalars().all()
    return LeadListResponse(total=total, items=leads)


@router.get("/stats", summary="Reply inbox statistics")
async def reply_stats(db: AsyncSession = Depends(get_db)):
    """Return counts for dashboard cards."""
    converted_count = (
        await db.execute(
            select(func.count()).select_from(Lead).where(Lead.status == LeadStatus.converted)
        )
    ).scalar_one()

    soft_bounce_count = (
        await db.execute(
            select(func.count()).select_from(Lead).where(Lead.reply_type == "soft_bounce")
        )
    ).scalar_one()

    # Leads deleted today (from activity log)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    deleted_today = (
        await db.execute(
            select(func.count()).select_from(ActivityLog).where(
                ActivityLog.event_type == "lead_deleted_reply",
                ActivityLog.created_at >= today_start,
            )
        )
    ).scalar_one()

    return {
        "converted": converted_count,
        "soft_bounce": soft_bounce_count,
        "deleted_today": deleted_today,
    }


@router.get(
    "/preview-email2/{lead_id}",
    summary="Preview Email 2 HTML for a converted lead (no send)",
)
async def preview_email2(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the rendered Email 2 HTML for a converted lead — no email is sent.
    Used by the frontend compose/preview modal.
    """
    from app.engines.outreach_engine import build_html_email_full
    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    audit_result = await db.execute(sa_select(Audit).where(Audit.lead_id == lead_id))
    audit = audit_result.scalar_one_or_none()


    html = build_html_email_full(lead, audit)
    return {"lead_id": lead_id, "business_name": lead.business_name, "email": lead.email, "html": html}


class Email2SendRequest(BaseModel):
    custom_html: Optional[str] = None    # if set, this HTML is sent instead of auto-generated
    custom_subject: Optional[str] = None # if set, overrides the default subject



@router.post(
    "/send-email2/{lead_id}",
    summary="Send Email 2 (website design proposal) to a converted lead",
)
async def send_email2(
    lead_id: uuid.UUID,
    body: Optional[Email2SendRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Generates and sends Email 2 (the website design & redesign proposal) to a
    converted lead (one who replied YES to Email 1).
    Uses the first configured SMTP account. Logs the action to ActivityLog.

    ── GUARDRAILS ──
    • NO PDF or audit report attachment — this is a design proposal email.
    • Lead must exist and have status=converted.
    • Optional body fields:
        - custom_html:    if provided, sent instead of the auto-generated email
        - custom_subject: if provided, overrides the default subject line
    """
    import asyncio
    from sqlalchemy import select as sa_select
    from app.engines.outreach_engine import build_html_email_full, _send_email_sync
    from app.config import settings

    result = await db.execute(sa_select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if lead.status != LeadStatus.converted:
        raise HTTPException(status_code=400, detail="Lead must have status=converted to send Email 2")

    audit_result = await db.execute(sa_select(Audit).where(Audit.lead_id == lead_id))
    audit = audit_result.scalar_one_or_none()

    accounts = settings.get_smtp_accounts()
    if not accounts:
        raise HTTPException(status_code=503, detail="No SMTP accounts configured")

    account = accounts[0]
    domain_str = (lead.website or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/").split("/")[0]

    # Use custom HTML/subject if provided by the frontend compose editor
    if body and body.custom_html:
        html_body = body.custom_html
    else:
        html_body = build_html_email_full(lead, audit)

    subject = (body.custom_subject if body and body.custom_subject else None) or f"Website redesign proposal for {domain_str}"

    loop = asyncio.get_running_loop()
    success, err = await loop.run_in_executor(
        None,
        lambda: _send_email_sync(
            account,
            lead.email,
            subject,
            html_body,
            is_followup=True,
            lead_name=lead.business_name or "",
            domain=domain_str,
            pdf_attachment_path=audit.pdf_path if audit else None,
        ),
    )

    if not success:
        raise HTTPException(status_code=502, detail=f"SMTP error: {err}")

    log = ActivityLog(
        event_type="email2_sent",
        lead_id=lead.id,
        message=f"Email 2 manually sent to {lead.email} ({lead.business_name}) via {account['email']}",
    )
    db.add(log)
    await db.commit()

    return {"sent": True, "to": lead.email, "subject": subject}



@router.patch(
    "/reclassify/{lead_id}",
    response_model=LeadResponse,
    summary="Move a converted lead to 'other' (generic auto-reply)",
)
async def reclassify_reply(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Demote a 'converted' lead back to 'emailed' status and set reply_type='other'.
    Use when the positive classification was a false positive (generic auto-reply, etc).
    The lead stays in the database — it is NOT deleted.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Revert
    lead.status     = LeadStatus.emailed   # back to emailed (was contacted)
    lead.reply_type = "other"

    log = ActivityLog(
        event_type="lead_reclassified",
        lead_id=lead.id,
        message=f"Reclassified {lead.business_name} <{lead.email}> from converted → other (manual review)",
    )
    db.add(log)
    await db.commit()
    await db.refresh(lead)
    logger.info(f"[replies] Reclassified lead {lead.email} → other")
    return lead
