import uuid
import asyncio
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models import Campaign, CampaignStatus, ActivityLog, Lead, Audit, AuditStatus, CampaignEmailLog, LeadStatus
from app.schemas import CampaignCreate, CampaignResponse, CampaignEmailLogResponse
from app.engines.outreach_engine import (
    run_campaign, build_minimal_html_email, build_plain_outreach_email,
    build_html_email, build_no_site_email,
    _send_email_sync, DEFAULT_SUBJECT_TEMPLATE, NO_SITE_SUBJECT_TEMPLATE,
)
from app.utils.site_checker import parse_site_status, SiteType
from app.utils.spintax import process_template
from app.config import settings

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class TestEmailRequest(BaseModel):
    to_email: str
    lead_id: str


# ── Static routes first (must come before /{campaign_id}) ─────────────────────

@router.post("/send-test", summary="Send a test email for a lead to any address")
async def send_test_email(
    body: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        lead_id = uuid.UUID(body.lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead_id format.")

    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    audit_result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    audit = audit_result.scalar_one_or_none()

    site_type = None
    if audit and audit.error_message:
        site_type = parse_site_status(audit.error_message)

    is_no_site = site_type in (SiteType.PARKED, SiteType.DEMO, SiteType.NOT_FOUND, SiteType.UNREACHABLE)
    domain_str = (lead.website or "").replace("https://","").replace("http://","").replace("www.","").rstrip("/").split("/")[0]
    variables  = {"business_name": lead.business_name, "website": lead.website, "domain": domain_str}

    if is_no_site:
        subject      = process_template(NO_SITE_SUBJECT_TEMPLATE, variables)
        template_used = f"no-site ({site_type.value if site_type else 'unreachable'})"
    else:
        subject      = process_template(DEFAULT_SUBJECT_TEMPLATE, variables)
        template_used = "website-design-proposal"

    plain_body = build_plain_outreach_email(lead, audit, site_type)
    if is_no_site:
        html_body = build_no_site_email(lead, site_type.value if site_type else "unreachable")
    else:
        html_body = build_html_email(lead, audit)

    accounts = settings.get_smtp_accounts()
    if not accounts:
        raise HTTPException(status_code=500, detail="No SMTP accounts configured.")

    account = accounts[0]
    subject = f"[TEST] {subject}"

    loop    = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _send_email_sync(account, body.to_email, subject, html_body, plain_body=plain_body),
    )
    success, smtp_err = result

    if not success:
        raise HTTPException(status_code=500, detail=f"SMTP send failed: {smtp_err[:200]}")

    return {
        "message": f"Test email sent to {body.to_email}",
        "lead": lead.business_name,
        "template_used": template_used,
        "subject": subject,
        "sender": account["email"],
    }


@router.post("/", response_model=CampaignResponse, summary="Create a draft campaign")
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_db),
):
    lead_ids = []
    for raw_id in body.lead_ids:
        try:
            lead_ids.append(uuid.UUID(str(raw_id)))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid lead_id format.")

    if not lead_ids:
        raise HTTPException(status_code=400, detail="Select at least one lead.")

    ready_result = await db.execute(
        select(Lead.id)
        .join(Audit, Audit.lead_id == Lead.id)
        .where(
            Lead.id.in_(lead_ids),
            Audit.status == AuditStatus.done,
        )
    )
    ready_ids = {row[0] for row in ready_result.fetchall()}
    blocked_count = len(set(lead_ids) - ready_ids)
    if blocked_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{blocked_count} selected lead(s) are not campaign-ready. "
                "Fresh campaign leads must have a successfully completed audit."
            ),
        )

    campaign = Campaign(
        name=body.name,
        lead_ids=[str(lid) for lid in lead_ids],
        template=body.template,
        subject_template=body.subject_template,
        scheduled_at=body.scheduled_at,
        status=CampaignStatus.draft,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    db.add(ActivityLog(
        event_type="campaign_created",
        message=f"Campaign '{body.name}' created with {len(body.lead_ids)} leads.",
    ))
    await db.commit()
    return campaign


@router.get("/", response_model=List[CampaignResponse], summary="List all campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    return result.scalars().all()


# ── Per-campaign routes ────────────────────────────────────────────────────────

@router.get("/{campaign_id}", response_model=CampaignResponse, summary="Get a campaign")
async def get_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


@router.delete("/{campaign_id}", summary="Delete a campaign permanently")
async def delete_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status == CampaignStatus.sending:
        raise HTTPException(
            status_code=409,
            detail="Campaign is currently sending. Pause it first before deleting.",
        )

    name = campaign.name
    await db.delete(campaign)
    await db.commit()

    db.add(ActivityLog(
        event_type="campaign_deleted",
        message=f"Campaign '{name}' deleted.",
    ))
    await db.commit()
    return {"deleted": str(campaign_id), "name": name}


@router.post("/{campaign_id}/send", summary="Launch campaign (with humanized delays)")
async def send_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    force: bool = Query(False, description="Reset stuck campaign and re-launch"),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status == CampaignStatus.sending and not force:
        raise HTTPException(
            status_code=409,
            detail="Campaign is already sending. Use force=true to reset and re-launch.",
        )

    # Reset counters on fresh launch (not resume)
    if campaign.status not in (CampaignStatus.paused,):
        campaign.sent_count    = 0
        campaign.skipped_count = 0
        campaign.failed_count  = 0
        campaign.pending_lead_ids = []

    campaign.status        = CampaignStatus.draft  # engine will set to 'sending'
    campaign.next_email_at = None
    await db.commit()

    background_tasks.add_task(run_campaign, str(campaign_id))

    db.add(ActivityLog(
        event_type="campaign_started",
        message=f"Campaign '{campaign.name}' send started. Targeting {len(campaign.lead_ids)} leads.",
    ))
    await db.commit()

    return {"message": "Campaign launched.", "campaign_id": str(campaign_id)}


@router.post("/{campaign_id}/pause", summary="Pause a running campaign")
async def pause_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status != CampaignStatus.sending:
        raise HTTPException(status_code=409, detail=f"Campaign is '{campaign.status}', not 'sending'.")

    # The runner checks this flag before each send and will stop itself
    campaign.status    = CampaignStatus.paused
    campaign.paused_at = datetime.utcnow()
    await db.commit()

    db.add(ActivityLog(
        event_type="campaign_paused",
        message=f"Campaign '{campaign.name}' paused. {campaign.sent_count} emails sent so far.",
    ))
    await db.commit()
    return {"message": "Campaign paused. Current email will finish, then it stops.", "campaign_id": str(campaign_id)}


@router.post("/{campaign_id}/resume", summary="Resume a paused campaign from where it left off")
async def resume_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status != CampaignStatus.paused:
        raise HTTPException(status_code=409, detail=f"Campaign is '{campaign.status}', not 'paused'.")

    # pending_lead_ids was saved when paused — runner will pick up from there
    campaign.status    = CampaignStatus.draft  # engine sets to 'sending'
    campaign.paused_at = None
    await db.commit()

    background_tasks.add_task(run_campaign, str(campaign_id))

    db.add(ActivityLog(
        event_type="campaign_resumed",
        message=f"Campaign '{campaign.name}' resumed. {len(campaign.pending_lead_ids or [])} emails remaining.",
    ))
    await db.commit()
    return {"message": "Campaign resumed.", "campaign_id": str(campaign_id)}


@router.post("/{campaign_id}/reset", summary="Reset a stuck campaign to draft")
async def reset_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    old_status = campaign.status
    campaign.status        = CampaignStatus.draft
    campaign.sent_count    = 0
    campaign.skipped_count = 0
    campaign.failed_count  = 0
    campaign.pending_lead_ids = []
    campaign.next_email_at    = None
    campaign.paused_at        = None
    await db.commit()

    return {"message": f"Campaign reset from '{old_status}' to 'draft'.", "campaign_id": str(campaign_id)}


@router.post("/{campaign_id}/recalculate", summary="Recalculate campaign counts from logs")
async def recalculate_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Fix mismatched sent/failed counts by recalculating from the deduplicated email logs."""
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    # Fetch ALL log entries ordered newest first
    all_logs_result = await db.execute(
        select(CampaignEmailLog)
        .where(CampaignEmailLog.campaign_id == campaign_id)
        .order_by(CampaignEmailLog.created_at.desc())
    )
    all_logs = all_logs_result.scalars().all()

    # Deduplicate: only the latest log per lead matters
    latest_by_lead = {}
    for log in all_logs:
        lid = str(log.lead_id) if log.lead_id else None
        if lid and lid not in latest_by_lead:
            latest_by_lead[lid] = log

    new_sent    = sum(1 for l in latest_by_lead.values() if l.status == "sent")
    new_failed  = sum(1 for l in latest_by_lead.values() if l.status == "failed")
    new_skipped = sum(1 for l in latest_by_lead.values() if l.status == "skipped")

    old = {"sent": campaign.sent_count, "failed": campaign.failed_count, "skipped": campaign.skipped_count}
    campaign.sent_count    = new_sent
    campaign.failed_count  = new_failed
    campaign.skipped_count = new_skipped
    await db.commit()

    return {
        "message": "Counts recalculated from deduplicated logs.",
        "old": old,
        "new": {"sent": new_sent, "failed": new_failed, "skipped": new_skipped},
    }

@router.post("/{campaign_id}/retry-failed", summary="Retry all failed leads in a campaign")
async def retry_failed_leads(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status == CampaignStatus.sending:
        raise HTTPException(
            status_code=409,
            detail="Campaign is currently sending. Pause it first.",
        )

    # Fetch ALL log entries for this campaign (to deduplicate properly)
    all_logs_result = await db.execute(
        select(CampaignEmailLog)
        .where(CampaignEmailLog.campaign_id == campaign_id)
        .order_by(CampaignEmailLog.created_at.desc())
    )
    all_logs = all_logs_result.scalars().all()

    # Deduplicate: for each lead_id, find only leads whose LATEST log is "failed"
    # (leads that succeeded on a later retry should NOT be retried again)
    latest_by_lead = {}
    for log in all_logs:
        lid = str(log.lead_id) if log.lead_id else None
        if lid and lid not in latest_by_lead:
            latest_by_lead[lid] = log  # first = newest (ordered desc)

    truly_failed_ids = [
        lid for lid, log in latest_by_lead.items() if log.status == "failed"
    ]

    if not truly_failed_ids:
        raise HTTPException(status_code=404, detail="No failed emails found for this campaign.")

    # Reset those leads to fresh (clear last_emailed_at, restore pre-email status)
    for lead_id_str in truly_failed_ids:
        try:
            lead = await db.get(Lead, uuid.UUID(lead_id_str))
            if lead:
                lead.last_emailed_at = None
                # Restore to 'audited' only if the audit completed successfully.
                audit_check = await db.execute(select(Audit).where(Audit.lead_id == lead.id))
                audit = audit_check.scalar_one_or_none()
                lead.status = LeadStatus.audited if audit and audit.status == AuditStatus.done else LeadStatus.new
        except Exception:
            pass

    # Recalculate correct sent_count based on unique leads that actually succeeded
    actually_sent = sum(1 for log in latest_by_lead.values() if log.status == "sent")

    # Queue only the truly-failed leads for resending
    campaign.pending_lead_ids = truly_failed_ids
    campaign.sent_count       = actually_sent    # correct baseline (no double-count)
    campaign.failed_count     = 0                # will be re-counted by engine
    campaign.skipped_count    = sum(1 for log in latest_by_lead.values() if log.status == "skipped")
    campaign.status           = CampaignStatus.draft  # engine sets to 'sending'
    campaign.next_email_at    = None
    campaign.paused_at        = None
    await db.commit()

    background_tasks.add_task(run_campaign, str(campaign_id))

    db.add(ActivityLog(
        event_type="campaign_retry",
        message=f"Campaign '{campaign.name}' retrying {len(truly_failed_ids)} failed emails.",
    ))
    await db.commit()

    return {
        "message": f"Retrying {len(truly_failed_ids)} failed emails.",
        "campaign_id": str(campaign_id),
        "retrying_count": len(truly_failed_ids),
    }


@router.get("/{campaign_id}/logs", response_model=List[CampaignEmailLogResponse], summary="Get per-email logs for a campaign")
async def get_campaign_logs(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, le=1000),
):
    result = await db.execute(
        select(CampaignEmailLog)
        .where(CampaignEmailLog.campaign_id == campaign_id)
        .order_by(CampaignEmailLog.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
