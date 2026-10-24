import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Response, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Lead, ActivityLog, EmailAssociationStatus
from app.schemas import LeadResponse, LeadListResponse, LeadUpdate, ApproveAssociationRequest
from app.utils.csv_parser import parse_and_clean_csv
from app.routers.auth import require_authorized_operator
from app.services.lead_discovery_service import (
    lead_discovery_service,
    parse_txt_upload_content,
    DEFAULT_PRESET_KEYWORDS,
    DEFAULT_PRESET_LOCATIONS,
)
from app.services.lead_quality_repair_service import lead_quality_repair_service

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(require_authorized_operator)],
)


class LeadQualityRepairPreviewRequest(BaseModel):
    lead_ids: Optional[List[uuid.UUID]] = None
    limit: int = Field(250, ge=1, le=1000)


class LeadQualityRepairRetryRequest(BaseModel):
    """An explicitly selected lead only; discovery is never bulk-unbounded."""
    reverify_email: bool = False


class BulkDeleteRequest(BaseModel):
    ids: List[uuid.UUID] = Field(min_length=1, max_length=500)
    confirmed_count: int = Field(ge=1, le=500)


def _make_lead_response(lead: Lead) -> dict:
    """
    Build a LeadResponse-compatible dict from a Lead ORM instance.
    Pulls audit_error from the eagerly-loaded .audit relationship so the
    skipped-site banner appears correctly in the frontend table.
    """
    audit = getattr(lead, 'audit', None)
    return LeadResponse.model_validate(lead).model_copy(
        update={
            "audit_error": audit.error_message if audit else None,
            "audit_status": audit.status if audit else None,
        }
    )



@router.delete("/all", summary="Delete ALL leads and their audits")
async def delete_all_leads(db: AsyncSession = Depends(get_db)):
    """Hard-delete every lead and every audit record. Irreversible."""
    from sqlalchemy import delete as sql_delete
    from app.models import Audit
    # Delete audits first (FK constraint), then all leads
    await db.execute(sql_delete(Audit))
    result = await db.execute(sql_delete(Lead))
    await db.commit()
    count = result.rowcount
    log = ActivityLog(
        event_type="leads_deleted",
        message=f"Deleted ALL {count} lead(s) and their audits.",
    )
    db.add(log)
    await db.commit()
    return {"deleted": count}


@router.post("/upload", summary="Upload leads CSV")
async def upload_leads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a CSV file. Parse, clean, deduplicate against existing DB entries,
    and bulk insert new leads.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    content = await file.read()
    rows = parse_and_clean_csv(content)

    if not rows:
        raise HTTPException(status_code=400, detail="No valid leads found in CSV.")

    # Fetch existing emails to deduplicate against DB
    existing = await db.execute(select(Lead.email))
    existing_emails = {row[0] for row in existing.fetchall()}

    new_leads = []
    skipped = 0
    for row in rows:
        if row["email"] in existing_emails:
            skipped += 1
            continue
        is_inferred = row.pop("is_inferred_website", False)
        lead = Lead(**row)

        from app.utils.email_constants import (
            is_directory_or_platform_email,
            is_third_party_directory_or_aggregator,
        )
        from app.services.lead_discovery_service import extract_domain_from_url, extract_email_domain

        # Demote third-party directory website to evidence provenance if present
        if lead.website and is_third_party_directory_or_aggregator(lead.website):
            if not lead.email_source_url:
                lead.email_source_url = lead.website
            lead.website = ""
            lead.website_domain = ""
            lead.website_association_status = "no_website"

        if is_inferred and lead.website:
            lead.website_domain = extract_domain_from_url(lead.website)
            lead.website_association_status = "candidate_match"
            lead.website_candidates = [{
                "url": lead.website,
                "domain": lead.website_domain,
                "source": "email_domain_inferred",
                "status": "candidate_match"
            }]
            lead.email_domain = lead.website_domain
            lead.email_domain_match = True
            lead.email_business_association_status = "external_domain_review"
            lead.email_association_reason = (
                "Website candidate inferred from the business email domain. "
                "The company association is not independently verified."
            )
        elif not lead.website:
            lead.website_association_status = "no_website"

        # Platform / Directory Email Safeguard
        if is_directory_or_platform_email(lead.email):
            lead.is_quarantined = True
            lead.quarantine_reason = "Directory platform email requires independent business association review"
            lead.email_business_association_status = "unverified_association"
            email_dom = extract_email_domain(lead.email)
            lead.email_association_reason = f"Directory platform email domain ({email_dom}) requires independent ownership review."
            lead.email_domain_match = False

        # The legacy repair workflow is also the final intake guard. This keeps
        # CSV imports aligned with scraped records without treating candidates as
        # verified websites or approved business contacts.
        lead_quality_repair_service.apply_static_rules(lead)

        db.add(lead)
        new_leads.append(lead)
        existing_emails.add(row["email"])

    await db.commit()

    # Log the batch
    if new_leads:
        log = ActivityLog(
            event_type="leads_imported",
            message=f"Imported {len(new_leads)} leads from '{file.filename}'. "
                    f"Skipped {skipped} duplicates.",
        )
        db.add(log)
        await db.commit()

    return {
        "imported": len(new_leads),
        "skipped_duplicates": skipped,
        "total_in_file": len(rows),
    }


# ─── Bulk Keyword & Location Lead Discovery Endpoints ─────────────────────────

class DiscoveryPreviewRequest(BaseModel):
    keywords: List[str] = []
    locations: List[str] = []
    mode: str = "uploaded_only"
    custom_budget: Optional[int] = None
    batch_offset: Optional[int] = 0


class DiscoveryJobCreateRequest(BaseModel):
    keywords: List[str] = []
    locations: List[str] = []
    mode: str = "uploaded_only"
    budget: Optional[int] = None
    batch_offset: Optional[int] = 0


@router.get("/discovery/presets", summary="Get built-in keyword and location presets")
async def get_discovery_presets():
    return {
        "keywords": DEFAULT_PRESET_KEYWORDS,
        "locations": DEFAULT_PRESET_LOCATIONS,
    }


@router.get("/discovery/providers", summary="Get provider configurations and failover status")
async def get_discovery_providers():
    return lead_discovery_service.get_provider_statuses()


@router.post("/discovery/upload-txt", summary="Upload keywords or locations .txt file")
async def upload_discovery_txt(
    file: UploadFile = File(...),
    file_type: str = Query("keywords", pattern="^(keywords|locations)$"),
):
    """
    Accept UTF-8 text file (.txt). Parse line-by-line, trim whitespace, ignore
    blank lines & comments (#), remove case-insensitive duplicates, and return stats.
    """
    filename_lower = (file.filename or "").lower()
    if not filename_lower.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only .txt text files are accepted.")

    content = await file.read()
    try:
        parsed = parse_txt_upload_content(
            content,
            file_type=file_type,
            max_file_size=getattr(settings, "DISCOVERY_MAX_FILE_SIZE_BYTES", 1_048_576),
            max_entries=getattr(settings, "DISCOVERY_MAX_ENTRIES_PER_FILE", 1000),
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    return {
        "file_type": file_type,
        "filename": file.filename,
        **parsed,
    }


@router.post("/discovery/preview", summary="Calculate search combinations and budget estimate")
async def preview_discovery_combinations(payload: DiscoveryPreviewRequest):
    return lead_discovery_service.calculate_combinations(
        keywords=payload.keywords,
        locations=payload.locations,
        mode=payload.mode,
        custom_budget=payload.custom_budget,
        batch_offset=payload.batch_offset,
    )


@router.post("/discovery/jobs", summary="Create and trigger lead discovery job")
async def create_discovery_job(
    payload: DiscoveryJobCreateRequest,
    background_tasks: BackgroundTasks,
):
    try:
        job = lead_discovery_service.create_job(
            keywords=payload.keywords,
            locations=payload.locations,
            mode=payload.mode,
            budget=payload.budget,
            batch_offset=payload.batch_offset,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    background_tasks.add_task(lead_discovery_service.run_discovery_job, job["job_id"])
    return job


@router.get("/discovery/jobs", summary="List all discovery jobs")
async def list_discovery_jobs():
    return list(lead_discovery_service._jobs.values())


@router.get("/discovery/jobs/{job_id}", summary="Get discovery job status and discovered leads")
async def get_discovery_job(job_id: str):
    job = lead_discovery_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Discovery job not found.")
    return job


@router.post("/discovery/jobs/{job_id}/pause", summary="Pause a running discovery job")
async def pause_discovery_job(job_id: str):
    try:
        return lead_discovery_service.pause_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Discovery job not found.")


@router.post("/discovery/jobs/{job_id}/resume", summary="Resume a paused discovery job")
async def resume_discovery_job(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    try:
        job = lead_discovery_service.resume_job(job_id)
        background_tasks.add_task(lead_discovery_service.run_discovery_job, job_id)
        return job
    except KeyError:
        raise HTTPException(status_code=404, detail="Discovery job not found.")
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))


@router.post("/discovery/jobs/{job_id}/cancel", summary="Cancel a discovery job")
async def cancel_discovery_job(job_id: str):
    try:
        return lead_discovery_service.cancel_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Discovery job not found.")


@router.get("/discovery/jobs/{job_id}/export", summary="Export discovered leads to CSV")
async def export_discovery_leads(
    job_id: str,
    format: str = Query("leadgen", pattern="^(leadgen|simple)$"),
    sendable_only: bool = Query(False, description="Exclude quarantined and unverified leads"),
):
    try:
        csv_content = lead_discovery_service.export_leads_csv(
            job_id, format_type=format, sendable_only=sendable_only
        )
        suffix = "_sendable" if sendable_only else ""
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=leads_{job_id}_{format}{suffix}.csv"},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Discovery job not found.")


@router.get("/", response_model=LeadListResponse, summary="List all leads")
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by business name or email"),
    db: AsyncSession = Depends(get_db),
):
    from app.models import Audit
    from sqlalchemy import or_, cast, String
    query = select(Lead).order_by(Lead.created_at.desc())
    count_q = select(func.count()).select_from(Lead)

    if status == "skipped":
        query = query.join(Audit).where(Audit.error_message.like("SITE_STATUS:%"))
        count_q = count_q.join(Audit).where(Audit.error_message.like("SITE_STATUS:%"))
    elif status == "quarantined":
        query = query.where(Lead.is_quarantined.is_(True))
        count_q = count_q.where(Lead.is_quarantined.is_(True))
    elif status:
        query = query.where(Lead.status == status)
        count_q = count_q.where(Lead.status == status)

    if q and q.strip():
        term = f"%{q.strip()}%"
        search_filter = or_(
            Lead.business_name.ilike(term),
            Lead.email.ilike(term),
            Lead.website.ilike(term),
        )
        query = query.where(search_filter)
        count_q = count_q.where(search_filter)

    total = (await db.execute(count_q)).scalar_one()

    query = query.options(selectinload(Lead.audit)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    leads = result.scalars().all()

    items = [_make_lead_response(lead) for lead in leads]
    return LeadListResponse(total=total, items=items)


def _mask_email(email: str | None) -> str:
    """Keep review-queue API payloads useful without returning a contact export."""
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:2]}{'*' * max(1, min(6, len(local) - 2))}@{domain}"


@router.post("/quality-repair/preview", summary="Dry-run evidence-driven lead quality repair")
async def preview_lead_quality_repair(
    payload: LeadQualityRepairPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Classify selected legacy records without network access or mutation.

    Operators must review this response before retrying discovery for an explicitly
    selected record.  The response intentionally omits mailbox addresses.
    """
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(payload.limit)
    if payload.lead_ids:
        stmt = select(Lead).where(Lead.id.in_(payload.lead_ids))
    leads = list((await db.execute(stmt)).scalars().all())
    return lead_quality_repair_service.dry_run_report(leads)


@router.get("/quality-repair/review-queue", summary="List unresolved lead quality records for operator review")
async def get_lead_quality_review_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    limit: Optional[int] = Query(None, ge=1, le=500),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Evidence-focused queue with pagination support; it neither releases quarantine nor deletes anything."""
    # Handle direct python calls where defaults are FastAPI Query objects
    clean_page = page if isinstance(page, int) and not isinstance(page, bool) else (getattr(page, "default", 1) if not isinstance(getattr(page, "default", 1), type(Ellipsis)) else 1)
    if not isinstance(clean_page, int) or clean_page < 1:
        clean_page = 1

    clean_page_size = page_size if isinstance(page_size, int) and not isinstance(page_size, bool) else (getattr(page_size, "default", 50) if not isinstance(getattr(page_size, "default", 50), type(Ellipsis)) else 50)
    if not isinstance(clean_page_size, int) or clean_page_size < 1:
        clean_page_size = 50

    clean_limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else None
    if clean_limit is not None and clean_limit < 1:
        clean_limit = None

    effective_limit = clean_limit if clean_limit is not None else clean_page_size
    effective_offset = 0 if clean_limit is not None else (clean_page - 1) * clean_page_size

    # Fetch leads ordered stably by (created_at DESC, id DESC)
    stmt = select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc())
    all_leads = list((await db.execute(stmt)).scalars().all())

    # Union of:
    # 1. Existing operational gatekeeper records (quarantined, unresolved website/email association)
    # 2. Leads for which the authoritative repair service returns recommended_action != "no_change"
    op_count = 0
    dr_count = 0
    both_count = 0
    queue_leads = []

    clean_search = (search or "").strip().lower() if isinstance(search, str) else ""

    for lead in all_leads:
        is_op = (
            bool(lead.is_quarantined)
            or lead.website_association_status in ("candidate_match", "conflicting", "inconclusive")
            or lead.email_business_association_status in ("external_domain_review", "unverified_association", "mismatched_source")
        )
        plan = lead_quality_repair_service.plan_for_lead(lead)
        is_dr = plan.recommended_action != "no_change"

        if is_op:
            op_count += 1
        if is_dr:
            dr_count += 1
        if is_op and is_dr:
            both_count += 1

        if is_op or is_dr:
            if clean_search:
                match_text = f"{lead.business_name or ''} {lead.email or ''} {lead.website or ''} {str(lead.id)}".lower()
                if clean_search not in match_text:
                    continue
            queue_leads.append((lead, plan, is_op, is_dr))

    total = len(queue_leads)
    paged_slice = queue_leads[effective_offset : effective_offset + effective_limit]

    records = []
    for lead, plan, is_op, is_dr in paged_slice:
        records.append({
            "lead_id": str(lead.id),
            "business_name": lead.business_name,
            "email": _mask_email(lead.email),
            "website": lead.website or None,
            "website_status": lead.website_association_status,
            "verification_status": lead.email_verification_status,
            "association_status": lead.email_business_association_status,
            "is_quarantined": bool(lead.is_quarantined),
            "quarantine_reason": lead.quarantine_reason,
            "website_provenance": lead.website_candidates or [],
            "email_provenance": {
                "source_url": lead.email_source_url,
                "source_type": lead.email_source_type,
                "candidate_count": len(lead.email_candidates or []),
                "candidates": [
                    {
                        "email": _mask_email(c.get("email")),
                        "source_url": c.get("source_url"),
                        "source_type": c.get("source_type"),
                        "association_status": c.get("association_status"),
                        "association_reason": c.get("association_reason"),
                    }
                    for c in (lead.email_candidates or [])
                    if isinstance(c, dict)
                ],
            },
            "most_recent_outcome": (lead.email_verification_details or {}).get("diagnostic_summary"),
            "recommended_action": plan.recommended_action,
            "issue_types": plan.issue_types,
            "evidence": plan.evidence,
            "is_operational_queue": is_op,
            "is_data_repair_actionable": is_dr,
        })
    return {
        "total": total,
        "page": clean_page,
        "page_size": effective_limit,
        "records": records,
        "counts": {
            "total_review_queue": total if not clean_search else (op_count + dr_count - both_count),
            "operational_queue": op_count,
            "data_repair_actionable": dr_count,
            "both": both_count,
        },
    }


@router.post("/quality-repair/{lead_id}/retry", summary="Run bounded website/contact discovery for one selected lead")
async def retry_lead_quality_discovery(
    lead_id: uuid.UUID,
    payload: LeadQualityRepairRetryRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reuses the existing safe discovery and verification services for one record.

    At most one selected website is inspected (homepage plus the discovery service's
    bounded Contact/About paths). Discovered information remains a candidate and
    cannot clear quarantine, approve an association, or dispatch a campaign.
    """
    import aiohttp
    from app.services.email_verifier_service import email_verifier

    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    all_leads = list((await db.execute(select(Lead))).scalars().all())
    changes = lead_quality_repair_service.apply_static_rules(lead, all_leads)
    discovered_sites: list[dict] = []
    discovered_emails: list[dict] = []
    try:
        timeout = aiohttp.ClientTimeout(total=35)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            discovered_sites = await lead_discovery_service.search_candidate_websites(
                session=session,
                name=lead.business_name,
                phone=lead.phone or "",
            )
            # Do not crawl every search result. The top independently discovered
            # non-directory result is inspected through the established safe path.
            top_site = next((site for site in discovered_sites if site.get("url")), None)
            if top_site:
                _, classification, _, discovered_emails, final_url = await lead_discovery_service.inspect_website_detailed(
                    session=session,
                    website=top_site["url"],
                    business_name=lead.business_name,
                )
                top_site["inspection"] = classification
                if final_url:
                    top_site["url"] = final_url
                    top_site["domain"] = extract_domain_from_url(final_url)
            else:
                discovered_sites.append({
                    "source": "bounded_discovery",
                    "status": "no_results",
                    "reason": "No independently supported official website candidate was returned",
                })
    except Exception as exc:
        # An unavailable provider or timeout is evidence of an inconclusive attempt,
        # not proof that the business lacks a website.
        discovered_sites.append({
            "source": "bounded_discovery",
            "status": "inconclusive",
            "reason": type(exc).__name__,
        })

    changes.extend(lead_quality_repair_service.add_discovery_candidates(lead, discovered_sites, discovered_emails))

    if payload.reverify_email:
        verification = await email_verifier.verify_email(lead.email, smtp_probe_enabled=False, catch_all_probe_enabled=False)
        lead.email_verification_status = verification.status
        lead.email_verification_details = verification.to_dict()
        # A positive DNS result may not release a hold. A negative result may add one.
        if not verification.is_sendable:
            lead.is_quarantined = True
            lead.quarantine_reason = verification.exclusion_reason or f"Email verification failed: {verification.status}"
        changes.append("email_reverified_without_smtp")

    db.add(ActivityLog(
        event_type="lead_quality_discovery_retry",
        lead_id=lead.id,
        message=f"Bounded lead-quality discovery retry recorded {len(changes)} change(s) for {lead.business_name}; association and campaign eligibility were not approved.",
    ))
    await db.commit()

    plan = lead_quality_repair_service.plan_for_lead(lead)
    return {
        "lead_id": str(lead.id),
        "changes": changes,
        "website_candidate_count": len(lead.website_candidates or []),
        "email_candidate_count": len(lead.email_candidates or []),
        "recommended_action": plan.recommended_action,
        "is_quarantined": lead.is_quarantined,
    }


@router.post("/quality-repair/{lead_id}/keep-under-review", summary="Acknowledge operator review and retain lead in review queue")
async def keep_lead_under_review(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Explicitly retain a lead in review queue without deleting or approving."""
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead.is_quarantined = True
    if not lead.quarantine_reason:
        lead.quarantine_reason = "Retained for operator review"

    log = ActivityLog(
        event_type="lead_quality_kept_for_review",
        lead_id=lead.id,
        message=f"Lead {lead.business_name} ({lead.id}) explicitly retained in review queue by operator.",
    )
    db.add(log)
    await db.commit()
    return {"lead_id": str(lead.id), "status": "kept_for_review"}


@router.get("/{lead_id}", response_model=LeadResponse, summary="Get a single lead")
async def get_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.audit))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return _make_lead_response(lead)


@router.delete("/{lead_id}", summary="Delete a lead")
async def delete_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    lead_name = lead.business_name
    str_lead_id = str(lead_id)

    # Clean up JSON references in campaigns to preserve referential integrity
    from app.models import Campaign
    campaigns_res = await db.execute(select(Campaign))
    for camp in campaigns_res.scalars().all():
        updated = False
        if camp.lead_ids and str_lead_id in [str(lid) for lid in camp.lead_ids]:
            camp.lead_ids = [lid for lid in camp.lead_ids if str(lid) != str_lead_id]
            updated = True
        if camp.pending_lead_ids and str_lead_id in [str(lid) for lid in camp.pending_lead_ids]:
            camp.pending_lead_ids = [lid for lid in camp.pending_lead_ids if str(lid) != str_lead_id]
            updated = True
        if updated:
            db.add(camp)

    await db.delete(lead)
    log = ActivityLog(
        event_type="leads_deleted",
        message=f"Deleted explicitly selected lead {lead_name} ({str_lead_id}) after operator confirmation.",
    )
    db.add(log)
    await db.commit()
    return {"deleted": str_lead_id}


@router.patch("/{lead_id}", response_model=LeadResponse, summary="Update lead fields")
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partially update lead fields (business_name, email, phone, website)."""
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    updated_fields = []
    if body.business_name is not None:
        lead.business_name = body.business_name.strip()
        updated_fields.append("name")
    if body.email is not None:
        lead.email = body.email.strip()
        updated_fields.append("email")
    if body.phone is not None:
        lead.phone = body.phone.strip() or None
        updated_fields.append("phone")
    if body.website is not None:
        lead.website = body.website.strip()
        updated_fields.append("website")
    if body.email_source_url is not None:
        lead.email_source_url = body.email_source_url.strip() or None
        updated_fields.append("email_source_url")
    if body.email_source_type is not None:
        lead.email_source_type = body.email_source_type.strip() or None
        updated_fields.append("email_source_type")
    if body.email_business_association_status is not None:
        lead.email_business_association_status = body.email_business_association_status.strip() or None
        updated_fields.append("association_status")
    if body.email_association_reason is not None:
        lead.email_association_reason = body.email_association_reason.strip() or None
        updated_fields.append("association_reason")
    if body.website_association_status is not None:
        lead.website_association_status = body.website_association_status.strip() or None
        updated_fields.append("website_association_status")
    if body.is_quarantined is not None:
        if body.is_quarantined is False:
            target_assoc = body.email_business_association_status.strip() if body.email_business_association_status is not None else lead.email_business_association_status
            if target_assoc not in ("matched", "approved"):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot unquarantine lead with unresolved or missing email association status.",
                )
        lead.is_quarantined = body.is_quarantined
        updated_fields.append("is_quarantined")
    if body.quarantine_reason is not None:
        lead.quarantine_reason = body.quarantine_reason.strip() or None
        updated_fields.append("quarantine_reason")

    await db.commit()

    # Re-fetch with audit relationship so audit_error is included in response
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.audit))
    )
    lead = result.scalar_one()

    log = ActivityLog(
        event_type="lead_updated",
        lead_id=lead.id,
        message=f"Updated {', '.join(updated_fields) or 'fields'} for {lead.business_name} ({lead.email}).",
    )
    db.add(log)
    await db.commit()

    return _make_lead_response(lead)


@router.post("/{lead_id}/approve-association", response_model=LeadResponse, summary="Explicitly approve lead email association following authorized review")
async def approve_lead_association(
    lead_id: uuid.UUID,
    body: ApproveAssociationRequest,
    current_operator: dict = Depends(require_authorized_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Explicitly approve an external_domain_review or unverified association under a documented policy.
    Auditable action with recorded provenance and reviewer notes.
    Requires authenticated operator or admin principal.
    """
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    trusted_reviewer = (current_operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise HTTPException(status_code=401, detail="Authenticated operator identity missing.")

    if body.reviewer and body.reviewer.strip() and body.reviewer.strip().lower() != trusted_reviewer.lower():
        raise HTTPException(
            status_code=403,
            detail=f"Forged reviewer identity rejected: supplied '{body.reviewer.strip()}' does not match authenticated principal '{trusted_reviewer}'.",
        )

    if not body.reason or not body.reason.strip():
        raise HTTPException(status_code=400, detail="Justification reason is required for auditable approval.")

    if lead.email_business_association_status == EmailAssociationStatus.INVALID_FORMAT.value:
        raise HTTPException(status_code=400, detail="Cannot approve an email with invalid format.")

    lead.email_business_association_status = EmailAssociationStatus.APPROVED.value
    lead.email_association_reason = f"Approved by {trusted_reviewer} ({body.policy_reference}): {body.reason.strip()}"

    # If quarantined for association reason, check if it can be unquarantined
    if lead.is_quarantined:
        q_reason = (lead.quarantine_reason or "").lower()
        if any(term in q_reason for term in ("association", "external_domain", "mismatched", "designer", "free mail", "free-mail", "unverified domain")):
            if lead.email_verification_status == "valid":
                lead.is_quarantined = False
                lead.quarantine_reason = None
            else:
                lead.quarantine_reason = f"Email verification required (current status: {lead.email_verification_status})"

    log = ActivityLog(
        event_type="association_approved",
        lead_id=lead.id,
        message=f"Association approved for {lead.business_name} ({lead.email}) by {trusted_reviewer} under policy '{body.policy_reference}': {body.reason.strip()}",
    )
    db.add(log)
    await db.commit()

    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.audit))
    )
    return _make_lead_response(result.scalar_one())


@router.post("/clean-names", summary="Strip taglines from business names (remove from first - or |)")
async def clean_all_names(db: AsyncSession = Depends(get_db)):
    """
    Iterate every lead and strip anything from the first ' - ' or ' | '
    separator onwards in the business name.

    Example: Bigmen Stout Men's Shop - Bigmen.com, Inc
          →  Bigmen Stout Men's Shop
    """
    from app.utils.csv_parser import clean_business_name

    result = await db.execute(select(Lead))
    leads = result.scalars().all()

    cleaned_count = 0
    for lead in leads:
        trimmed = clean_business_name(lead.business_name or "")
        if trimmed and trimmed != lead.business_name:
            lead.business_name = trimmed
            cleaned_count += 1

    if cleaned_count:
        await db.commit()
        log = ActivityLog(
            event_type="names_cleaned",
            message=f"Stripped taglines from {cleaned_count} business name(s).",
        )
        db.add(log)
        await db.commit()

    return {
        "cleaned": cleaned_count,
        "already_clean": len(leads) - cleaned_count,
        "total": len(leads),
    }


@router.post("/clean-urls", summary="Trim all website URLs to root domain")
async def clean_all_urls(db: AsyncSession = Depends(get_db)):
    """
    Iterate every lead and normalise its website to the root URL
    (scheme + domain + trailing slash), stripping any internal page paths.

    Example: https://balanicustom.com/custom-suits-indianapolis
          →  https://balanicustom.com/
    """
    from app.utils.csv_parser import clean_website

    result = await db.execute(select(Lead))
    leads = result.scalars().all()

    cleaned_count = 0
    for lead in leads:
        trimmed = clean_website(lead.website or "")
        if trimmed and trimmed != lead.website:
            lead.website = trimmed
            cleaned_count += 1

    if cleaned_count:
        await db.commit()
        log = ActivityLog(
            event_type="urls_cleaned",
            message=f"Trimmed {cleaned_count} lead website(s) to root URL.",
        )
        db.add(log)
        await db.commit()

    return {
        "cleaned": cleaned_count,
        "already_clean": len(leads) - cleaned_count,
        "total": len(leads),
    }


@router.post("/bulk-delete", summary="Bulk delete leads by ID list")
async def bulk_delete_leads(
    payload: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Delete only explicitly selected leads after count confirmation."""
    from sqlalchemy import delete as sql_delete
    uuid_list = list(dict.fromkeys(payload.ids))
    if payload.confirmed_count != len(uuid_list):
        raise HTTPException(
            status_code=400,
            detail="Bulk deletion confirmation count must match the explicitly selected lead IDs.",
        )

    # 1. Revalidate the selected records immediately before deletion
    existing_stmt = select(Lead.id).where(Lead.id.in_(uuid_list))
    existing_ids = set((await db.execute(existing_stmt)).scalars().all())
    missing_ids = [str(uid) for uid in uuid_list if uid not in existing_ids]

    if not existing_ids:
        return {
            "deleted": 0,
            "requested": len(uuid_list),
            "missing": missing_ids,
        }

    # 2. Clean up JSON references in campaigns to preserve referential integrity
    from app.models import Audit, Campaign
    str_deleted_ids = {str(uid) for uid in existing_ids}
    campaigns_res = await db.execute(select(Campaign))
    for camp in campaigns_res.scalars().all():
        updated = False
        if camp.lead_ids:
            new_lead_ids = [lid for lid in camp.lead_ids if str(lid) not in str_deleted_ids]
            if len(new_lead_ids) != len(camp.lead_ids):
                camp.lead_ids = new_lead_ids
                updated = True
        if camp.pending_lead_ids:
            new_pending = [lid for lid in camp.pending_lead_ids if str(lid) not in str_deleted_ids]
            if len(new_pending) != len(camp.pending_lead_ids):
                camp.pending_lead_ids = new_pending
                updated = True
        if updated:
            db.add(camp)

    # 3. Delete audits and leads
    await db.execute(sql_delete(Audit).where(Audit.lead_id.in_(existing_ids)))
    result = await db.execute(sql_delete(Lead).where(Lead.id.in_(existing_ids)))
    count = result.rowcount

    log = ActivityLog(
        event_type="leads_deleted",
        message=f"Bulk deleted {count} explicitly selected lead(s) out of {len(uuid_list)} requested.",
    )
    db.add(log)
    await db.commit()

    return {
        "deleted": count,
        "requested": len(uuid_list),
        "missing": missing_ids,
    }
