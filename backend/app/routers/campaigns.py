import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_ as sa_or
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.database import get_db
from app.models import Campaign, CampaignStatus, ActivityLog, Lead, Audit, AuditStatus, CampaignEmailLog, LeadStatus
from app.schemas import CampaignCreate, CampaignResponse, CampaignEmailLogResponse
from app.engines.outreach_engine import (
    run_campaign, build_minimal_html_email,
    _send_email_sync,
    classify_smtp_error,
)
from app.services.template_renderer import (
    TemplateRenderer,
    TemplateRenderingError,
    DEFAULT_SEGMENT_TEMPLATES,
)
from app.services.campaign_eligibility_service import (
    evaluate_lead_campaign_eligibility,
    get_audience_breakdown,
    classify_website,
    classify_email_sendability,
    CampaignType,
)
from app.config import settings
from app.routers.auth import require_authorized_operator
from app.services.campaign_schema_service import (
    has_campaign_audit_references_column,
    check_audit_campaign_schema_readiness,
    get_campaign_safe,
    list_campaigns_safe,
    insert_compatible_campaign,
    is_missing_audit_references_error,
    SCHEMA_READINESS_DETAIL,
)
from app.services.email_limit_service import (
    get_sender_daily_usage,
    claim_global_email_capacity_atomic,
    check_global_email_capacity,
    GLOBAL_DAILY_EMAIL_CAP,
)

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_authorized_operator)],
)


class TestEmailRequest(BaseModel):
    to_email: str
    lead_id: str
    campaign_type: Optional[str] = "generic_first_contact"


class CampaignPreviewRequest(BaseModel):
    lead_id: str
    template: str
    subject_template: str = "{business_name} - update"
    campaign_type: Optional[str] = "generic_first_contact"


class AudienceCheckRequest(BaseModel):
    lead_ids: List[str]
    campaign_type: Optional[str] = "generic_first_contact"
    require_proposal_approval: Optional[bool] = False


class CampaignScheduleRequest(BaseModel):
    scheduled_at: datetime


# ── Static routes first (must come before /{campaign_id}) ─────────────────────

@router.get("/segments", summary="Get available campaign segmentation presets and default templates")
async def get_campaign_segments():
    """Returns canonical campaign types with their descriptions and safe default templates."""
    return [
        {
            "id": "no_website_design",
            "name": "No Website — Full Web Design",
            "description": "Target businesses without an active website with a professional web design offer",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["no_website_design"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["no_website_design"]["template"],
            "requires_audit": False,
        },
        {
            "id": "broken_website_repair",
            "name": "Broken Website — Repair & Rebuild",
            "description": "Target businesses whose websites are unreachable, broken, or returning server errors",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["broken_website_repair"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["broken_website_repair"]["template"],
            "requires_audit": True,
        },
        {
            "id": "outdated_website_modernization",
            "name": "Outdated Website — Modernization & Mobile",
            "description": "Target websites needing mobile responsiveness, UI overhaul, and modernization",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["outdated_website_modernization"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["outdated_website_modernization"]["template"],
            "requires_audit": True,
        },
        {
            "id": "valid_website_seo",
            "name": "Valid Website — Technical SEO Opportunity",
            "description": "Target audited websites with verified indexability, meta, sitemap, or speed opportunities",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["template"],
            "requires_audit": True,
        },
        {
            "id": "valid_website_redesign",
            "name": "Valid Website — Redesign & Conversion",
            "description": "Target live websites with verified UX, contrast, navigation, and conversion opportunities",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["valid_website_redesign"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_redesign"]["template"],
            "requires_audit": True,
        },
        {
            "id": "valid_website_link_building",
            "name": "Valid Website — Authority & Citations",
            "description": "Target live websites with link profile and local authority opportunities",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["valid_website_link_building"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_link_building"]["template"],
            "requires_audit": True,
        },
        {
            "id": "valid_website_marketing",
            "name": "Valid Website — Digital Marketing",
            "description": "Target live websites with search visibility and conversion opportunities",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["valid_website_marketing"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_marketing"]["template"],
            "requires_audit": True,
        },
        {
            "id": "generic_first_contact",
            "name": "Generic First Contact — General Outreach",
            "description": "Neutral observational outreach suitable for broad prospect initial contact",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["generic_first_contact"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["generic_first_contact"]["template"],
            "requires_audit": False,
        },
        {
            "id": "public_provider_demo",
            "name": "Public Provider — Demo-Only Outreach",
            "description": "Restricted single demo outreach for verified public-provider emails (Gmail, Yahoo, etc.) pending business association review",
            "default_subject": DEFAULT_SEGMENT_TEMPLATES["public_provider_demo"]["subject"],
            "default_template": DEFAULT_SEGMENT_TEMPLATES["public_provider_demo"]["template"],
            "requires_audit": False,
        },
    ]


@router.get("/sender-status", summary="Get SMTP sender configuration status and health")
async def get_sender_status(db: AsyncSession = Depends(get_db)):
    """Returns safe, redacted sender configuration details and authoritative daily volume counters."""
    accounts = settings.get_smtp_accounts()
    return await get_sender_daily_usage(db, accounts)


@router.post("/preview", summary="Generate exact email preview using authoritative template renderer")
async def preview_campaign_email(
    body: CampaignPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Renders the exact template for a lead without dispatching email.
    Reports eligibility status, variable substitutions, and any rendering faults.
    """
    try:
        lead_id = uuid.UUID(body.lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead_id format.")

    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    audit_result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    audit = audit_result.scalar_one_or_none()

    accounts = settings.get_smtp_accounts()
    sender = accounts[0] if accounts else None

    has_received_demo = False
    if (lead.email or "").strip():
        norm_email = lead.email.strip().lower()
        demo_stmt = (
            select(CampaignEmailLog.id)
            .join(Campaign, Campaign.id == CampaignEmailLog.campaign_id)
            .where(
                Campaign.campaign_type == "public_provider_demo",
                CampaignEmailLog.status == "sent",
                func.lower(CampaignEmailLog.email) == norm_email,
            )
            .limit(1)
        )
        has_received_demo = (await db.execute(demo_stmt)).scalar() is not None

    is_el, reason, site_cls, email_cls = evaluate_lead_campaign_eligibility(
        lead, audit, body.campaign_type or "generic_first_contact", has_received_demo=has_received_demo
    )

    try:
        rendered = TemplateRenderer.render_campaign_email(
            template=body.template,
            subject_template=body.subject_template,
            lead=lead,
            audit=audit,
            campaign_type=body.campaign_type,
            sender_account=sender,
        )
    except TemplateRenderingError as e:
        raise HTTPException(status_code=400, detail=f"Template rendering failed: {str(e)}")

    return {
        **rendered,
        "is_eligible": is_el,
        "exclusion_reason": reason,
        "website_classification": site_cls.value,
        "sendability_classification": email_cls.value,
        "sender": sender.get("email") if sender else "Not configured",
    }


@router.post("/refresh-audit/{lead_id}", summary="Initiate bounded audit refresh for stale or incomplete audit")
async def refresh_campaign_lead_audit(
    lead_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers bounded audit refresh for a lead. Idempotent: returns already_running
    if an audit task is currently active, preventing duplicate tasks.
    """
    from app.services.campaign_eligibility_service import request_bounded_audit_refresh
    res = await request_bounded_audit_refresh(lead_id, db, background_tasks=background_tasks)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res["message"])
    return res


@router.post("/audience-check", summary="Get authoritative audience breakdown for selected leads")
async def check_campaign_audience(
    body: AudienceCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """Calculates eligibility and exclusion statistics for selected leads before campaign creation."""
    lead_uuids = []
    for raw_id in body.lead_ids:
        try:
            lead_uuids.append(uuid.UUID(str(raw_id)))
        except ValueError:
            continue

    if not lead_uuids:
        return get_audience_breakdown([], body.campaign_type or "generic_first_contact")

    sent_demo_emails = set()
    try:
        demo_stmt = (
            select(func.lower(CampaignEmailLog.email))
            .join(Campaign, Campaign.id == CampaignEmailLog.campaign_id)
            .where(
                Campaign.campaign_type == "public_provider_demo",
                CampaignEmailLog.status == "sent",
            )
        )
        demo_res = await db.execute(demo_stmt)
        sent_demo_emails = {r[0] for r in demo_res.fetchall() if r[0]}
    except Exception:
        pass

    leads_result = await db.execute(
        select(Lead).options(selectinload(Lead.audit)).where(Lead.id.in_(lead_uuids))
    )
    leads = leads_result.scalars().all()
    pairs = [(lead, lead.audit) for lead in leads]
    return get_audience_breakdown(
        pairs,
        body.campaign_type or "generic_first_contact",
        sent_demo_emails=sent_demo_emails,
        require_proposal_approval=bool(body.require_proposal_approval),
    )


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

    if not lead.niche_id and lead.business_name:
        from app.services.niche_router import classify_lead_niche
        nid, kw, conf = classify_lead_niche(lead.business_name, getattr(lead, "category", None))
        if nid and conf >= 2:
            lead.niche_id = nid
            lead.niche_keyword = kw
            lead.niche_confidence = conf
            await db.commit()

    c_type = body.campaign_type or "generic_first_contact"
    if c_type != "generic_first_contact":
        from app.services.audit_email_service import AuditEmailService
        if AuditEmailService.is_audit_dependent(c_type) and (not audit or not audit.audit_results):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Selected lead '{lead.business_name}' has no completed audit. "
                    f"The '{c_type}' strategy requires actual audit findings. "
                    "Please audit this lead in the Audits tab first, or select 'generic_first_contact' / an audited lead."
                ),
            )
    defaults = TemplateRenderer.get_default_template(c_type)

    accounts = settings.get_smtp_accounts()
    if not accounts:
        raise HTTPException(status_code=500, detail="No SMTP accounts configured.")
    account = accounts[0]

    try:
        rendered = TemplateRenderer.render_campaign_email(
            template=defaults["template"],
            subject_template=defaults["subject"],
            lead=lead,
            audit=audit,
            campaign_type=c_type,
            sender_account=account,
        )
    except TemplateRenderingError as e:
        raise HTTPException(status_code=400, detail=f"Rendering test email failed: {str(e)}")

    subject = f"[TEST] {rendered['subject']}"
    html_body = rendered["html_body"]
    plain_body = rendered["plain_body"]

    # Enforce global daily email limit (1,000/day in Asia/Kolkata) across all accounts
    can_send, current_sent, remaining = await claim_global_email_capacity_atomic(db, 1)
    if not can_send:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Global daily email limit ({GLOBAL_DAILY_EMAIL_CAP}/day in Asia/Kolkata) "
                f"reached across all sender accounts. Sent today: {current_sent}, remaining: 0."
            ),
        )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _send_email_sync(account, body.to_email, subject, html_body, plain_body=plain_body),
    )
    success, smtp_err = result

    if not success:
        err_info = classify_smtp_error(smtp_err)
        status_code = 400 if err_info["is_permanent_sender_failure"] else 502
        raise HTTPException(
            status_code=status_code,
            detail=f"SMTP test send failed: {err_info['sanitized_message']} (Sender: {account.get('email')})",
        )

    # Durable audit logging of test email send (counted towards global daily cap)
    test_log = ActivityLog(
        event_type="test_email_sent",
        lead_id=lead.id,
        message=f"Test email sent to {body.to_email} via {account['email']} | Subject: {subject}",
    )
    db.add(test_log)
    await db.commit()

    return {
        "message": f"Test email sent to {body.to_email}",
        "lead": lead.business_name,
        "campaign_type": c_type,
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

    # Deduplicate lead IDs while preserving insertion order for idempotent ingestion
    lead_ids = list(dict.fromkeys(lead_ids))

    if not lead_ids:
        raise HTTPException(status_code=400, detail="Select at least one lead.")

    c_type = body.campaign_type or "generic_first_contact"
    audit_required = c_type not in ("no_website_design", "generic_first_contact", "public_provider_demo")

    has_audit_col = await has_campaign_audit_references_column(db)
    if audit_required and not has_audit_col:
        raise HTTPException(
            status_code=503,
            detail=SCHEMA_READINESS_DETAIL,
        )

    # Validate template against renderer for syntax / required placeholder errors & evaluate freshness
    leads_result = await db.execute(
        select(Lead).options(selectinload(Lead.audit)).where(Lead.id.in_(lead_ids))
    )
    leads = leads_result.scalars().all() if hasattr(leads_result, "scalars") else []

    # Use the same complete eligibility decision used by audience preview and the
    # send-time worker.  A SQL-only prefilter previously omitted website segment
    # classification and one-time demo history, producing UI/creation disagreement.
    selected_ids = {str(lead_id) for lead_id in lead_ids}
    found_ids = {str(lead.id) for lead in leads}
    missing_count = len(selected_ids - found_ids)
    if missing_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{missing_count} selected lead(s) are not campaign-ready because the lead record could not be found."
            ),
        )

    sent_demo_emails = set()
    if c_type == CampaignType.PUBLIC_PROVIDER_DEMO.value:
        demo_stmt = (
            select(func.lower(CampaignEmailLog.email))
            .join(Campaign, Campaign.id == CampaignEmailLog.campaign_id)
            .where(
                Campaign.campaign_type == CampaignType.PUBLIC_PROVIDER_DEMO.value,
                CampaignEmailLog.status == "sent",
            )
        )
        demo_result = await db.execute(demo_stmt)
        sent_demo_emails = {row[0] for row in demo_result.fetchall() if row[0]}

    # Check authoritative campaign eligibility & audit freshness for each lead
    for sample_lead in leads:
        normalized_email = (sample_lead.email or "").strip().lower()
        is_el, el_reason, _, _ = evaluate_lead_campaign_eligibility(
            sample_lead,
            audit=getattr(sample_lead, "audit", None),
            campaign_type=c_type,
            has_received_demo=normalized_email in sent_demo_emails,
        )
        if not is_el:
            raise HTTPException(
                status_code=400,
                detail=f"Selected lead '{sample_lead.business_name}' is not campaign-ready: {el_reason}",
            )

    audit_references = {}
    if leads:
        accounts = settings.get_smtp_accounts()
        sender = accounts[0] if accounts else None
        for sample_lead in leads:
            try:
                rendered = TemplateRenderer.render_campaign_email(
                    template=body.template,
                    subject_template=body.subject_template,
                    lead=sample_lead,
                    audit=getattr(sample_lead, "audit", None),
                    campaign_type=c_type,
                    sender_account=sender,
                )
                if rendered.get("content_strategy") == "audit_generated":
                    audit_references[str(sample_lead.id)] = rendered["audit_reference"]
            except TemplateRenderingError as err:
                raise HTTPException(status_code=400, detail=f"Invalid campaign template: {str(err)}")

    has_audit_col = await has_campaign_audit_references_column(db)
    check_audit_campaign_schema_readiness(c_type, audit_references, has_audit_col)

    init_status = CampaignStatus.scheduled if body.scheduled_at else CampaignStatus.draft
    campaign = Campaign(
        name=body.name,
        lead_ids=[str(lid) for lid in lead_ids],
        template=body.template,
        subject_template=body.subject_template,
        campaign_type=c_type,
        audit_references=audit_references,
        scheduled_at=body.scheduled_at,
        status=init_status,
    )
    try:
        if has_audit_col:
            db.add(campaign)
            await db.commit()
            reloaded = await get_campaign_safe(db, campaign.id)
            if reloaded is not None:
                campaign = reloaded
        else:
            await insert_compatible_campaign(db, campaign)
    except Exception as db_err:
        await db.rollback()
        if is_missing_audit_references_error(db_err):
            raise HTTPException(
                status_code=503,
                detail=SCHEMA_READINESS_DETAIL,
            )
        raise

    db.add(ActivityLog(
        event_type="campaign_created",
        message=f"Campaign '{body.name}' created with {len(body.lead_ids)} leads.",
    ))
    await db.commit()
    return campaign


@router.get("/", response_model=List[CampaignResponse], summary="List all campaigns")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    return await list_campaigns_safe(db)


# ── Per-campaign routes ────────────────────────────────────────────────────────

@router.get("/{campaign_id}", response_model=CampaignResponse, summary="Get a campaign")
async def get_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


@router.delete("/{campaign_id}", summary="Delete a campaign permanently")
async def delete_campaign(campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    campaign = await get_campaign_safe(db, campaign_id)
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
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status == CampaignStatus.sending and not force:
        raise HTTPException(
            status_code=409,
            detail="Campaign is already sending. Use force=true to reset and re-launch.",
        )

    # Enforce global daily email limit (1,000/day in Asia/Kolkata) across all accounts
    can_send_global, current_global_sent, remaining_global = await check_global_email_capacity(db, 1)
    if not can_send_global or remaining_global <= 0:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Global daily email limit ({GLOBAL_DAILY_EMAIL_CAP}/day in Asia/Kolkata) "
                f"reached across all sender accounts. Sent today: {current_global_sent}, remaining: 0. "
                "Resets at IST midnight (00:00 IST)."
            ),
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
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status != CampaignStatus.sending:
        raise HTTPException(status_code=409, detail=f"Campaign is '{campaign.status}', not 'sending'.")

    # The runner checks this flag before each send and will stop itself
    campaign.status    = CampaignStatus.paused
    campaign.paused_at = datetime.now(timezone.utc)
    await db.commit()

    db.add(ActivityLog(
        event_type="campaign_paused",
        message=f"Campaign '{campaign.name}' paused. {campaign.sent_count} emails sent so far.",
    ))
    await db.commit()
    return {"message": "Campaign paused. Current email will finish, then it stops.", "campaign_id": str(campaign_id)}


@router.post("/{campaign_id}/schedule", summary="Schedule a campaign for automated launch")
async def schedule_campaign(
    campaign_id: uuid.UUID,
    body: CampaignScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if campaign.status == CampaignStatus.sending:
        raise HTTPException(
            status_code=409,
            detail="Campaign is currently sending. Pause or reset it before scheduling.",
        )

    campaign.scheduled_at = body.scheduled_at
    campaign.status = CampaignStatus.scheduled
    await db.commit()

    db.add(ActivityLog(
        event_type="campaign_scheduled",
        message=f"Campaign '{campaign.name}' scheduled for {body.scheduled_at.isoformat()}.",
    ))
    await db.commit()
    return {
        "message": "Campaign scheduled successfully.",
        "campaign_id": str(campaign_id),
        "scheduled_at": body.scheduled_at.isoformat(),
        "status": campaign.status,
    }


@router.post("/{campaign_id}/cancel", summary="Cancel a scheduled or running campaign")
async def cancel_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    old_status = campaign.status
    if campaign.status == CampaignStatus.scheduled:
        campaign.status = CampaignStatus.draft
        campaign.scheduled_at = None
        await db.commit()
        msg = f"Scheduled campaign '{campaign.name}' cancelled and reverted to draft."
    elif campaign.status == CampaignStatus.sending:
        campaign.status = CampaignStatus.paused
        campaign.paused_at = datetime.now(timezone.utc)
        await db.commit()
        msg = f"Running campaign '{campaign.name}' paused on cancellation. Worker will halt on next check."
    else:
        campaign.status = CampaignStatus.draft
        campaign.scheduled_at = None
        await db.commit()
        msg = f"Campaign '{campaign.name}' cancelled and set to draft."

    db.add(ActivityLog(
        event_type="campaign_cancelled",
        message=msg,
    ))
    await db.commit()
    return {
        "message": msg,
        "campaign_id": str(campaign_id),
        "previous_status": old_status,
        "status": campaign.status,
    }


@router.post("/{campaign_id}/resume", summary="Resume a paused campaign from where it left off")
async def resume_campaign(
    campaign_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    campaign = await get_campaign_safe(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    from app.services.campaign_lock_service import campaign_lock_coordinator
    is_locked = campaign_lock_coordinator.is_campaign_locked_in_process(campaign_id)

    # Allow resume if paused, OR if stranded in sending without active worker lock (crash recovery)
    can_resume = (campaign.status == CampaignStatus.paused) or (campaign.status == CampaignStatus.sending and not is_locked)
    if not can_resume:
        raise HTTPException(status_code=409, detail=f"Campaign is '{campaign.status}', not 'paused' or recoverable.")

    if is_locked:
        raise HTTPException(status_code=409, detail="Campaign is currently running with an active worker lock.")

    # Enforce global daily email limit (1,000/day in Asia/Kolkata) across all accounts
    can_send_global, current_global_sent, remaining_global = await check_global_email_capacity(db, 1)
    if not can_send_global or remaining_global <= 0:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Global daily email limit ({GLOBAL_DAILY_EMAIL_CAP}/day in Asia/Kolkata) "
                f"reached across all sender accounts. Sent today: {current_global_sent}, remaining: 0. "
                "Resets at IST midnight (00:00 IST)."
            ),
        )

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
    campaign = await get_campaign_safe(db, campaign_id)
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
    campaign = await get_campaign_safe(db, campaign_id)
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
    campaign = await get_campaign_safe(db, campaign_id)
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

    safe_retry_ids = []
    for lid_str in truly_failed_ids:
        try:
            lead_obj = await db.get(Lead, uuid.UUID(lid_str))
            if not lead_obj:
                continue
            norm_email = (lead_obj.email or "").strip().lower()
            if campaign.campaign_type == "public_provider_demo":
                if norm_email:
                    demo_check = await db.execute(
                        select(CampaignEmailLog.id)
                        .join(Campaign, Campaign.id == CampaignEmailLog.campaign_id)
                        .where(
                            Campaign.campaign_type == "public_provider_demo",
                            CampaignEmailLog.status == "sent",
                            func.lower(CampaignEmailLog.email) == norm_email,
                        )
                        .limit(1)
                    )
                    if demo_check.scalar() is not None:
                        continue
                is_el, _, _, _ = evaluate_lead_campaign_eligibility(
                    lead_obj, None, "public_provider_demo", has_received_demo=False
                )
                if is_el:
                    safe_retry_ids.append(lid_str)
            else:
                if (
                    not getattr(lead_obj, "is_quarantined", False)
                    and getattr(lead_obj, "email_verification_status", None) == "valid"
                    and getattr(lead_obj, "email_business_association_status", None) in ("matched", "approved")
                ):
                    safe_retry_ids.append(lid_str)
        except Exception:
            pass

    if not safe_retry_ids:
        raise HTTPException(
            status_code=404,
            detail="No sendable failed emails found for this campaign (quarantined or unverified leads excluded).",
        )

    # Reset those leads to fresh (clear last_emailed_at, restore pre-email status)
    for lead_id_str in safe_retry_ids:
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
    campaign.pending_lead_ids = safe_retry_ids
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
