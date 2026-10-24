"""
Email Verification & Deliverability Hub Router.

Provides endpoints for:
- Ad-hoc single email verification
- Single lead verification with database persistence & quarantine management
- Throttled bulk lead verification with concurrency throttling
- Real-time deliverability stats & KPIs
- Segregated Active vs Quarantined lead list views
- Controlled lead re-verification
"""

from __future__ import annotations
import asyncio
import datetime
import logging
import uuid
from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, update

from app.database import get_db
from app.models import Lead, ActivityLog
from app.services.email_verifier_service import email_verifier, VerificationResult
from app.services.campaign_eligibility_service import (
    is_legacy_provider_quarantine_reason,
    is_public_email_provider,
    extract_email_domain,
)
from app.utils.email_constants import (
    is_disposable_domain,
    PUBLIC_EMAIL_PROVIDERS,
    is_directory_or_platform_email,
)
from app.routers.auth import require_authorized_operator

logger = logging.getLogger("email_verification_router")

router = APIRouter(
    prefix="/email-verify",
    tags=["email-verify"],
    dependencies=[Depends(require_authorized_operator)],
)

# In-memory progress state for bulk verification
_BULK_PROGRESS = {
    "is_running": False,
    "job_id": None,
    "total": 0,
    "processed": 0,
    "valid": 0,
    "invalid": 0,
    "disposable": 0,
    "risky": 0,
    "quarantined": 0,
    "failed": 0,
    "skipped": 0,
    "remaining": 0,
    "cancel_requested": False,
    "started_at": None,
    "completed_at": None,
    "error_message": None,
}


class SingleVerifyRequest(BaseModel):
    email: str = Field(..., description="Email address to verify")
    smtp_probe_enabled: bool = Field(False, description="Explicit opt-in for SMTP probe (disabled by default)")
    catch_all_probe_enabled: bool = Field(False, description="Explicit opt-in for catch-all probe (disabled by default)")


class BulkVerifyRequest(BaseModel):
    lead_ids: Optional[List[str]] = Field(None, description="Specific lead UUIDs to verify")
    unverified_only: bool = Field(True, description="Only verify leads currently unverified")
    limit: int = Field(100, ge=1, le=500, description="Max leads to process in batch (capped at 500)")
    smtp_probe_enabled: bool = Field(False, description="Explicit opt-in for SMTP probe (disabled by default)")
    catch_all_probe_enabled: bool = Field(False, description="Explicit opt-in for catch-all probe (disabled by default)")


class ReverifyRequest(BaseModel):
    smtp_probe_enabled: bool = Field(False, description="Explicit opt-in for SMTP probe (disabled by default)")
    catch_all_probe_enabled: bool = Field(False, description="Explicit opt-in for catch-all probe (disabled by default)")


class LegacyQuarantineReverifyRequest(BaseModel):
    lead_ids: Optional[List[str]] = Field(None, description="Specific lead UUIDs to reverify")
    dry_run: bool = Field(True, description="If True, simulate action without committing changes to database")


@router.post("/single", summary="Verify single email address in real time")
async def verify_single_email(payload: SingleVerifyRequest) -> dict[str, Any]:
    """
    Validates syntax, detects domain typos, checks disposable domain blocklist,
    and resolves DNS/MX records. Optional SMTP probing remains disabled by default.
    """
    res = await email_verifier.verify_email(
        email=payload.email,
        smtp_probe_enabled=payload.smtp_probe_enabled,
        catch_all_probe_enabled=payload.catch_all_probe_enabled,
    )
    return res.to_dict()


@router.post("/lead/{lead_id}", summary="Verify a specific lead and update quarantine status")
async def verify_lead_by_id(
    lead_id: str,
    payload: Optional[ReverifyRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Verifies a lead's email, updates email_verification_status and details.
    If non-sendable, automatically quarantines the lead.
    If valid, atomically restores sendability if quarantine was due to verification.
    """
    try:
        uid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")

    lead = await db.get(Lead, uid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    smtp_enabled = payload.smtp_probe_enabled if payload else False
    catch_all_enabled = payload.catch_all_probe_enabled if payload else False

    result = await email_verifier.verify_email(
        email=lead.email,
        smtp_probe_enabled=smtp_enabled,
        catch_all_probe_enabled=catch_all_enabled,
    )

    lead.email_verification_status = result.status
    lead.email_verification_details = result.to_dict()
    lead.email_verified_at = datetime.datetime.now(datetime.timezone.utc)

    # Automatic Quarantine Management
    if not result.is_sendable:
        lead.is_quarantined = True
        lead.quarantine_reason = result.exclusion_reason or f"Email verification failed: {result.status}"
        logger.info(f"Lead {lead.id} ({lead.email}) quarantined: {lead.quarantine_reason}")
    else:
        # Email syntax and mail routing (MX) are valid
        assoc_status = getattr(lead, "email_business_association_status", None)
        if is_directory_or_platform_email(lead.email):
            lead.is_quarantined = True
            lead.quarantine_reason = "Directory platform email requires independent business association review"
        elif assoc_status in ("mismatched_source", "invalid_format"):
            lead.is_quarantined = True
            lead.quarantine_reason = (
                getattr(lead, "email_association_reason", None)
                or f"email_business_association_{assoc_status}"
            )
        elif lead.is_quarantined:
            q_reason = (lead.quarantine_reason or "").lower()
            # A record may leave quarantine ONLY when its latest verification result AND policy explicitly allow that transition:
            # 1. Association MUST be confirmed safe ("matched" or "approved")
            # 2. Previous quarantine reason was strictly related to email verification failure
            is_verif_only_quarantine = any(term in q_reason for term in (
                "verification failed", "disposable", "invalid_format", "no valid mx", "nxdomain", "timed out", "dns resolution", "typo"
            ))
            is_association_safe = assoc_status in ("matched", "approved")

            if is_verif_only_quarantine and is_association_safe:
                lead.is_quarantined = False
                lead.quarantine_reason = None
                logger.info(f"Lead {lead.id} ({lead.email}) restored following valid email verification (association: {assoc_status}).")
            else:
                logger.info(f"Lead {lead.id} ({lead.email}) retained in quarantine (reason: {lead.quarantine_reason}, assoc: {assoc_status}).")

    await db.commit()
    await db.refresh(lead)

    return {
        "lead_id": str(lead.id),
        "email": lead.email,
        "is_quarantined": lead.is_quarantined,
        "quarantine_reason": lead.quarantine_reason,
        "verification": result.to_dict(),
    }


@router.post("/reverify/{lead_id}", summary="Re-verify a quarantined or existing lead")
async def reverify_lead(
    lead_id: str,
    payload: Optional[ReverifyRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Alias for /lead/{lead_id} to support UI re-verification actions."""
    return await verify_lead_by_id(lead_id, payload, db)


async def _run_bulk_verification_job(
    lead_ids: list[uuid.UUID],
    smtp_enabled: bool,
    catch_all_enabled: bool,
):
    """
    Background worker for bulk verification with bounded concurrency and chunked commits.
    Processes leads in sequential batches of BATCH_SIZE (25), with at most 5 parallel
    DNS queries per batch. Commits results incrementally to PostgreSQL so progress is
    persisted even if cancelled or interrupted.
    """
    global _BULK_PROGRESS
    from app.database import AsyncSessionLocal

    semaphore = asyncio.Semaphore(5)  # Max 5 parallel DNS lookups
    BATCH_SIZE = 25

    async def _verify_lead_record(lead: Lead) -> tuple[Lead, VerificationResult | None]:
        async with semaphore:
            if _BULK_PROGRESS.get("cancel_requested"):
                return lead, None
            try:
                res = await email_verifier.verify_email(
                    email=lead.email,
                    smtp_probe_enabled=smtp_enabled,
                    catch_all_probe_enabled=catch_all_enabled,
                )
                return lead, res
            except Exception as ex:
                logger.error(f"Error resolving verification for lead {lead.id} ({lead.email}): {ex}")
                return lead, ex

    try:
        for i in range(0, len(lead_ids), BATCH_SIZE):
            if _BULK_PROGRESS.get("cancel_requested"):
                logger.info("Bulk verification cancellation requested. Stopping subsequent batches.")
                remaining_unprocessed = len(lead_ids) - i
                _BULK_PROGRESS["skipped"] = _BULK_PROGRESS.get("skipped", 0) + remaining_unprocessed
                _BULK_PROGRESS["processed"] = _BULK_PROGRESS.get("processed", 0) + remaining_unprocessed
                break

            chunk_ids = lead_ids[i:i + BATCH_SIZE]
            async with AsyncSessionLocal() as session:
                if hasattr(session, "execute"):
                    stmt = select(Lead).where(Lead.id.in_(chunk_ids))
                    res = await session.execute(stmt)
                    leads = list(res.scalars().all())
                else:
                    leads = [await session.get(Lead, cid) for cid in chunk_ids]
                    leads = [l for l in leads if l is not None]

                tasks = [_verify_lead_record(l) for l in leads if l and l.email]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for item in results:
                    if isinstance(item, Exception):
                        logger.error(f"Bulk verification task exception: {item}")
                        _BULK_PROGRESS["failed"] += 1
                        _BULK_PROGRESS["processed"] += 1
                        continue

                    lead, v_res = item
                    if isinstance(v_res, Exception):
                        _BULK_PROGRESS["failed"] += 1
                        _BULK_PROGRESS["processed"] += 1
                        continue
                    if v_res is None:
                        _BULK_PROGRESS["skipped"] += 1
                        _BULK_PROGRESS["processed"] += 1
                        continue

                    # Persist verification details and timestamps
                    lead.email_verification_status = v_res.status
                    lead.email_verification_details = v_res.to_dict()
                    lead.email_verified_at = datetime.datetime.now(datetime.timezone.utc)

                    if not v_res.is_sendable:
                        lead.is_quarantined = True
                        lead.quarantine_reason = v_res.exclusion_reason or f"Email verification failed: {v_res.status}"
                        _BULK_PROGRESS["quarantined"] += 1
                    else:
                        assoc_status = getattr(lead, "email_business_association_status", None)
                        if is_directory_or_platform_email(lead.email):
                            lead.is_quarantined = True
                            lead.quarantine_reason = "Directory platform email requires independent business association review"
                            _BULK_PROGRESS["quarantined"] += 1
                        elif assoc_status in ("mismatched_source", "invalid_format"):
                            lead.is_quarantined = True
                            lead.quarantine_reason = (
                                getattr(lead, "email_association_reason", None)
                                or f"email_business_association_{assoc_status}"
                            )
                            _BULK_PROGRESS["quarantined"] += 1
                        elif lead.is_quarantined:
                            q_reason = (lead.quarantine_reason or "").lower()
                            is_verif_only_quarantine = any(term in q_reason for term in (
                                "verification failed", "disposable", "invalid_format", "no valid mx", "nxdomain", "timed out", "dns resolution", "typo"
                            ))
                            is_association_safe = assoc_status in ("matched", "approved")

                            if is_verif_only_quarantine and is_association_safe:
                                lead.is_quarantined = False
                                lead.quarantine_reason = None
                            else:
                                _BULK_PROGRESS["quarantined"] += 1

                    _BULK_PROGRESS["processed"] += 1
                    if v_res.status == "valid":
                        _BULK_PROGRESS["valid"] += 1
                    elif v_res.status == "disposable":
                        _BULK_PROGRESS["disposable"] += 1
                    elif v_res.status in ("invalid", "not_found", "timeout", "error"):
                        _BULK_PROGRESS["invalid"] += 1
                    else:
                        _BULK_PROGRESS["risky"] += 1

                _BULK_PROGRESS["remaining"] = max(0, _BULK_PROGRESS["total"] - _BULK_PROGRESS["processed"])
                await session.commit()

        # Log completion event in ActivityLog
        try:
            async with AsyncSessionLocal() as session:
                log_entry = ActivityLog(
                    event_type="bulk_email_verification",
                    message=(
                        f"Bulk email verification finished: {_BULK_PROGRESS['processed']}/{_BULK_PROGRESS['total']} leads processed "
                        f"({_BULK_PROGRESS['valid']} deliverable, {_BULK_PROGRESS['invalid']} invalid, "
                        f"{_BULK_PROGRESS['disposable']} disposable, {_BULK_PROGRESS['risky']} risky, "
                        f"{_BULK_PROGRESS['quarantined']} quarantined, {_BULK_PROGRESS['failed']} errors)."
                    ),
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                )
                session.add(log_entry)
                await session.commit()
        except Exception as log_ex:
            logger.warning(f"Could not persist bulk verification activity log: {log_ex}")

    except Exception as e:
        logger.exception(f"Fatal error in bulk email verification job: {e}")
        _BULK_PROGRESS["error_message"] = str(e)
    finally:
        _BULK_PROGRESS["is_running"] = False
        _BULK_PROGRESS["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _BULK_PROGRESS["remaining"] = max(0, _BULK_PROGRESS["total"] - _BULK_PROGRESS["processed"])
        logger.info(f"Bulk email verification job {_BULK_PROGRESS.get('job_id')} finished.")


@router.post("/bulk", summary="Trigger bulk verification of leads")
async def bulk_verify_leads(
    payload: BulkVerifyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Enqueues a bounded batch of unverified leads for verification.
    Uses concurrency throttle to avoid exceeding DNS/rate limits.
    """
    global _BULK_PROGRESS
    if _BULK_PROGRESS["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="A bulk email verification job is already running",
        )

    stmt = select(Lead.id)
    if payload.lead_ids:
        uids = [uuid.UUID(lid) for lid in payload.lead_ids]
        stmt = stmt.where(Lead.id.in_(uids))
    elif payload.unverified_only:
        stmt = stmt.where(Lead.email_verification_status == "unverified")

    stmt = stmt.limit(payload.limit)
    res = await db.execute(stmt)
    target_ids = list(res.scalars().all())

    if not target_ids:
        return {
            "message": "No eligible leads found for verification",
            "enqueued_count": 0,
            "total": 0,
        }

    job_id = str(uuid.uuid4())
    _BULK_PROGRESS.update({
        "is_running": True,
        "job_id": job_id,
        "total": len(target_ids),
        "processed": 0,
        "valid": 0,
        "invalid": 0,
        "disposable": 0,
        "risky": 0,
        "quarantined": 0,
        "failed": 0,
        "skipped": 0,
        "remaining": len(target_ids),
        "cancel_requested": False,
        "error_message": None,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "completed_at": None,
    })

    background_tasks.add_task(
        _run_bulk_verification_job,
        lead_ids=target_ids,
        smtp_enabled=payload.smtp_probe_enabled,
        catch_all_enabled=payload.catch_all_probe_enabled,
    )

    return {
        "message": f"Enqueued {len(target_ids)} leads for verification",
        "job_id": job_id,
        "total": len(target_ids),
        "enqueued_count": len(target_ids),
    }


@router.get("/progress", summary="Get bulk verification progress")
async def get_bulk_progress() -> dict[str, Any]:
    return dict(_BULK_PROGRESS)


@router.post("/cancel", summary="Cancel active bulk verification job")
async def cancel_bulk_verification() -> dict[str, Any]:
    global _BULK_PROGRESS
    if _BULK_PROGRESS["is_running"]:
        _BULK_PROGRESS["cancel_requested"] = True
        return {"message": "Cancellation requested"}
    return {"message": "No job currently running"}


@router.get("/legacy-quarantine-preview", summary="Read-only preview of leads quarantined solely for legacy public-provider rules")
async def get_legacy_quarantine_preview(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Read-only inspection of existing records quarantined solely due to obsolete public/free provider rules.
    Reports the exact existing reason, proposed status, and intended demo-only eligibility.
    Never modifies database records.
    """
    stmt = select(Lead).where(Lead.is_quarantined == True)
    res = await db.execute(stmt)
    quarantined_leads = res.scalars().all()

    total_quarantined = len(quarantined_leads)
    legacy_provider_records = []

    for l in quarantined_leads:
        q_reason = l.quarantine_reason or ""
        if not is_legacy_provider_quarantine_reason(q_reason):
            continue

        email = (l.email or "").strip()
        domain = extract_email_domain(email)
        is_public = is_public_email_provider(domain)

        # Check for independent safety exclusions
        independent_exclusions = []
        if not email or "@" not in email:
            independent_exclusions.append("missing_or_invalid_email_syntax")
        if email_verifier.is_disposable_domain(domain):
            independent_exclusions.append("disposable_domain")
        if l.email_business_association_status in ("mismatched_source", "invalid_format"):
            independent_exclusions.append(f"association_safety_{l.email_business_association_status}")
        if l.email_verification_status in ("invalid", "disposable"):
            independent_exclusions.append(f"verification_status_{l.email_verification_status}")

        has_independent_exclusion = len(independent_exclusions) > 0

        # Determine proposed status and demo eligibility
        if has_independent_exclusion:
            proposed_status = "quarantined_independent_safety"
            intended_demo_eligible = False
        elif l.email_verification_status == "valid":
            proposed_status = "demo_only_eligible"
            intended_demo_eligible = True
        else:
            proposed_status = "pending_verification"
            intended_demo_eligible = False

        legacy_provider_records.append({
            "lead_id": str(l.id),
            "business_name": l.business_name,
            "email": l.email,
            "domain": domain,
            "is_public_provider": is_public,
            "existing_quarantine_reason": q_reason,
            "association_status": l.email_business_association_status,
            "current_verification_status": l.email_verification_status,
            "independent_safety_exclusions": independent_exclusions,
            "has_independent_exclusion": has_independent_exclusion,
            "proposed_status": proposed_status,
            "intended_demo_only_eligible": intended_demo_eligible,
        })

    demo_ready_count = sum(1 for r in legacy_provider_records if r["intended_demo_only_eligible"])
    pending_verif_count = sum(1 for r in legacy_provider_records if r["proposed_status"] == "pending_verification")
    blocked_safety_count = sum(1 for r in legacy_provider_records if r["has_independent_exclusion"])

    return {
        "total_quarantined_leads": total_quarantined,
        "legacy_provider_quarantined_count": len(legacy_provider_records),
        "demo_ready_upon_restoration": demo_ready_count,
        "pending_verification_count": pending_verif_count,
        "retained_under_independent_safety_count": blocked_safety_count,
        "records": legacy_provider_records,
    }


@router.post("/legacy-quarantine-reverify", summary="Controlled re-verification workflow for legacy provider-only quarantined leads")
async def reverify_legacy_quarantine_leads(
    payload: LegacyQuarantineReverifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Controlled re-verification workflow.
    Where a record's only quarantine reason is an obsolete public-provider rule,
    re-runs syntax and MX routeability checks. If routeability passes with no independent
    safety exclusion, clears obsolete quarantine to permit demo-only eligibility.
    If dry_run is True (default), simulates the action without saving.
    """
    stmt = select(Lead).where(Lead.is_quarantined == True)
    if payload.lead_ids:
        uids = []
        for x in payload.lead_ids:
            try:
                uids.append(uuid.UUID(x))
            except ValueError:
                continue
        stmt = stmt.where(Lead.id.in_(uids))

    res = await db.execute(stmt)
    leads = res.scalars().all()

    results = []
    restored_count = 0
    retained_count = 0

    for lead in leads:
        q_reason = lead.quarantine_reason or ""
        if not is_legacy_provider_quarantine_reason(q_reason):
            continue

        email = (lead.email or "").strip()
        domain = extract_email_domain(email)

        # Routeability verification (syntax and DNS/MX, no live SMTP probing)
        v_res = await email_verifier.verify_email(
            email=email,
            smtp_probe_enabled=False,
            catch_all_probe_enabled=False,
        )

        # Check for independent safety exclusions
        independent_exclusions = []
        if not v_res.is_sendable:
            independent_exclusions.append(f"verification_{v_res.status}")
        if email_verifier.is_disposable_domain(domain):
            independent_exclusions.append("disposable_domain")
        if lead.email_business_association_status in ("mismatched_source", "invalid_format"):
            independent_exclusions.append(f"association_safety_{lead.email_business_association_status}")

        if independent_exclusions:
            # Independent exclusion exists: MUST NOT CLEAR QUARANTINE
            retained_count += 1
            if not payload.dry_run:
                lead.email_verification_status = v_res.status
                lead.email_verification_details = v_res.details
                lead.quarantine_reason = "; ".join(independent_exclusions)
            results.append({
                "lead_id": str(lead.id),
                "email": lead.email,
                "action": "retained_in_quarantine",
                "reason": "; ".join(independent_exclusions),
                "demo_only_eligible": False,
            })
        else:
            # Routeability passed and no independent exclusions exist!
            restored_count += 1
            if not payload.dry_run:
                lead.email_verification_status = "valid"
                lead.email_verified_at = datetime.datetime.utcnow()
                lead.email_verification_details = v_res.details
                lead.is_quarantined = False
                lead.quarantine_reason = None
            results.append({
                "lead_id": str(lead.id),
                "email": lead.email,
                "action": "restored_for_demo_only" if not payload.dry_run else "would_restore_for_demo_only",
                "proposed_status": "demo_only_eligible",
                "demo_only_eligible": True,
            })

    if not payload.dry_run and restored_count > 0:
        await db.commit()
        db.add(ActivityLog(
            event_type="legacy_quarantine_reverification",
            message=f"Controlled reverification restored {restored_count} leads for demo-only eligibility (retained {retained_count}).",
        ))
        await db.commit()

    return {
        "mode": "dry_run" if payload.dry_run else "applied",
        "processed": len(results),
        "restored_for_demo_only": restored_count,
        "retained_under_safety": retained_count,
        "results": results,
    }


@router.get("/stats", summary="Get deliverability and verification statistics")
async def get_email_verification_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Returns authoritative counts for deliverable, invalid, disposable, catch-all, risky, unverified,
    quarantined, and demo-only eligible leads.
    """
    total_leads = await db.scalar(select(func.count(Lead.id))) or 0
    quarantined = await db.scalar(select(func.count(Lead.id)).where(Lead.is_quarantined == True)) or 0

    # Status distribution
    status_counts_res = await db.execute(
        select(Lead.email_verification_status, func.count(Lead.id))
        .group_by(Lead.email_verification_status)
    )
    status_map = dict(status_counts_res.all())

    valid_count = status_map.get("valid", 0)
    not_found_count = status_map.get("not_found", 0)
    timeout_count = status_map.get("timeout", 0)
    error_count = status_map.get("error", 0)
    invalid_raw = status_map.get("invalid", 0)
    invalid_count = invalid_raw + not_found_count + timeout_count + error_count
    disposable_count = status_map.get("disposable", 0)
    catch_all_count = status_map.get("catch_all", 0)
    risky_count = status_map.get("risky", 0)

    # Deliverable = verified valid AND not quarantined AND matched/approved association
    deliverable_count = await db.scalar(
        select(func.count(Lead.id)).where(
            and_(
                Lead.email_verification_status == "valid",
                Lead.is_quarantined == False,
                Lead.email_business_association_status.in_(["matched", "approved"]),
            )
        )
    ) or 0

    # Demo-only eligible = verified valid AND not quarantined AND public provider domain AND unverified/external_domain_review
    demo_cand_stmt = select(Lead.email).where(
        and_(
            Lead.email_verification_status == "valid",
            Lead.is_quarantined == False,
            Lead.email_business_association_status.in_(["unverified_association", "external_domain_review", "pending_review", "unverified"]),
        )
    )
    demo_cand_res = await db.execute(demo_cand_stmt)
    demo_emails = demo_cand_res.scalars().all()
    demo_only_eligible_count = sum(1 for em in demo_emails if em and is_public_email_provider(extract_email_domain(em)))
    corporate_pending_review_count = sum(1 for em in demo_emails if em and not is_public_email_provider(extract_email_domain(em)))

    pending_verification_active = await db.scalar(
        select(func.count(Lead.id)).where(
            and_(
                Lead.email_verification_status == "unverified",
                Lead.is_quarantined == False,
            )
        )
    ) or 0

    unverified_total = status_map.get("unverified", 0)
    unverified_quarantined = max(0, unverified_total - pending_verification_active)
    quarantined_verified = max(0, quarantined - unverified_quarantined)

    return {
        "total_leads": total_leads,
        "deliverable": deliverable_count,
        "valid": valid_count,
        "invalid": invalid_count,
        "disposable": disposable_count,
        "catch_all": catch_all_count,
        "risky": risky_count,
        "not_found": not_found_count,
        "timeout": timeout_count,
        "error": error_count,
        "unverified": unverified_total,             # Authoritative total requiring verification (437)
        "unverified_active": pending_verification_active, # 333
        "unverified_quarantined": unverified_quarantined, # 104
        "quarantined": quarantined,                 # 465
        "quarantined_verified": quarantined_verified, # 361
        "quarantined_unverified": unverified_quarantined, # 104
        "pending_verification": unverified_total,   # Reconciled so KPI card and action panel agree on 437
        "pending_verification_active": pending_verification_active, # 333
        "active_pool": deliverable_count,
        "demo_only_eligible": demo_only_eligible_count,
        "corporate_pending_review": corporate_pending_review_count,
    }


@router.get("/leads", summary="List leads with deliverability filters")
async def get_verification_leads(
    view: str = Query("all", pattern="^(all|active|sendable|unverified|pending|quarantined|demo_only|corporate_review|corporate_pending_review)$", description="active | sendable | unverified | pending | quarantined | demo_only | corporate_review | all"),
    scope: Optional[str] = Query("all", description="all | active | quarantined (used with unverified view)"),
    status: Optional[str] = Query(None, description="Filter by email_verification_status"),
    search: Optional[str] = Query(None, description="Search by business name, email, or website"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Returns paginated lead list with deliverability metadata.
    Segregates Confirmed Sendable Leads from Pending Unverified, Quarantined, Demo-Only, and Corporate Domain Review Leads.
    """
    stmt = select(Lead)

    if view in ("active", "sendable"):
        stmt = stmt.where(
            and_(
                Lead.is_quarantined == False,
                Lead.email_verification_status == "valid",
                Lead.email_business_association_status.in_(["matched", "approved"]),
            )
        )
    elif view in ("corporate_review", "corporate_pending_review"):
        public_domains_tuple = tuple(PUBLIC_EMAIL_PROVIDERS)
        stmt = stmt.where(
            and_(
                Lead.is_quarantined == False,
                Lead.email_verification_status == "valid",
                Lead.email_business_association_status.in_(["unverified_association", "external_domain_review", "pending_review", "unverified"]),
                func.lower(func.split_part(Lead.email, "@", 2)).notin_(public_domains_tuple),
            )
        )
    elif view == "demo_only":
        public_domains_tuple = tuple(PUBLIC_EMAIL_PROVIDERS)
        stmt = stmt.where(
            and_(
                Lead.is_quarantined == False,
                Lead.email_verification_status == "valid",
                Lead.email_business_association_status.in_(["unverified_association", "external_domain_review", "pending_review", "unverified"]),
                func.lower(func.split_part(Lead.email, "@", 2)).in_(public_domains_tuple),
            )
        )
    elif view in ("unverified", "pending"):
        stmt = stmt.where(Lead.email_verification_status == "unverified")
        if scope == "active":
            stmt = stmt.where(Lead.is_quarantined == False)
        elif scope == "quarantined":
            stmt = stmt.where(Lead.is_quarantined == True)
    elif view == "quarantined":
        stmt = stmt.where(Lead.is_quarantined == True)

    if status and status != "all":
        stmt = stmt.where(Lead.email_verification_status == status)

    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.business_name.ilike(term),
                Lead.email.ilike(term),
                Lead.website.ilike(term),
            )
        )

    # Count total matching
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0

    # Paginate
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Lead.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    leads = result.scalars().all()

    items = []
    for l in leads:
        details = l.email_verification_details or {}
        items.append({
            "id": str(l.id),
            "business_name": l.business_name,
            "email": l.email,
            "website": l.website,
            "website_domain": l.website_domain,
            "website_association_status": l.website_association_status,
            "website_candidates": l.website_candidates or [],
            "email_domain": l.email_domain,
            "verification_status": l.email_verification_status,
            "association_status": l.email_business_association_status,
            "association_reason": l.email_association_reason,
            "email_source_url": l.email_source_url,
            "email_source_type": l.email_source_type,
            "email_domain_match": l.email_domain_match,
            "deliverability_score": details.get("score", 0),
            "is_sendable": details.get("is_sendable", False),
            "is_disposable": details.get("is_disposable", False),
            "has_mx": details.get("has_mx", False),
            "is_catch_all": details.get("is_catch_all", False),
            "is_quarantined": l.is_quarantined,
            "quarantine_reason": l.quarantine_reason,
            "verified_at": l.email_verified_at.isoformat() if l.email_verified_at else None,
            "details": details,
        })

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total_count + page_size - 1) // page_size),
    }
