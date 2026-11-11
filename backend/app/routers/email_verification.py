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

from app.database import get_db, AsyncSessionLocal
from app.models import Lead, ActivityLog, EmailCorrection, EmailAssociationStatus
from app.services.email_verifier_service import email_verifier, VerificationResult
from app.services.lead_discovery_service import LeadDiscoveryService, clean_website, extract_domain_from_url
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
    website_scrape_enabled: bool = Field(True, description="Perform bounded website scraping to verify email ownership and detect domain-matched addresses")


class BulkReverifyRequest(BaseModel):
    lead_ids: Optional[List[str]] = Field(None, description="Specific lead UUIDs to re-verify")
    filter_mismatched_only: bool = Field(False, description="If True, only target leads whose email domain does not match their website")
    filter_unverified_association_only: bool = Field(False, description="If True, only target leads with unverified association status")
    limit: Optional[int] = Field(100, ge=1, le=500, description="Max records to examine in this batch")
    dry_run: bool = Field(True, description="If True, returns a preview/dry-run report without mutating records")


class BulkApproveDomainMatchesRequest(BaseModel):
    lead_ids: List[str] = Field(..., min_length=1, max_length=100, description="Corporate review leads from the current page")


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


async def reverify_lead_ownership_and_deliverability(
    lead: Lead,
    db: AsyncSession,
    website_scrape_enabled: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Core Re-verify workflow:
    1. Scrapes the lead's official website using safe HTTP requests with SSRF protections.
    2. Inspects homepage, contact page, scripts, and links to extract email candidates and source URLs.
    3. Normalizes domains and compares candidate emails against the company's website domain.
    4. Evaluates deterministic decision rules:
       - Match found: corrects primary email (if mismatched), updates association, runs syntax/MX validation.
       - Existing matches: retains email, revalidates.
       - Only external found: retains external address as review candidate, does not falsely assign company match.
       - No usable email: marks non-sendable / excluded with clear reversible quarantine reason.
       - Scraping failure / timeout: marks attempt as inconclusive and retains lead for retry without deletion.
    5. Preserves audit trail in ActivityLog and EmailCorrection records.
    """
    initial_email = getattr(lead, "email", None)
    raw_website = getattr(lead, "website", None)
    website_url = clean_website(raw_website) if isinstance(raw_website, str) else ""
    site_domain = extract_domain_from_url(website_url)
    lead_id_str = str(lead.id)

    outcome_status = "inconclusive"
    outcome_reason = ""
    evidence_url = website_url
    corrected_email: Optional[str] = None
    scraped_candidates: list[dict[str, Any]] = []

    # Step 1: Bounded website crawl & candidate extraction
    if website_scrape_enabled and website_url:
        import aiohttp
        service = LeadDiscoveryService()
        async with aiohttp.ClientSession() as session:
            try:
                is_target, class_reason, primary_cand, candidates, final_url = await service.inspect_website_detailed(
                    session,
                    website=website_url,
                    business_name=lead.business_name,
                )
                evidence_url = final_url or website_url
                scraped_candidates = candidates or []

                if "Dead/Unreachable" in class_reason or "Blocked" in class_reason:
                    outcome_status = "scrape_inconclusive"
                    outcome_reason = f"Website temporarily unreachable or blocked ({class_reason}); retained for retry without deletion."
                elif not candidates:
                    # If existing email already matches company website domain, retain it (Rule B)
                    old_em_dom = extract_email_domain(initial_email)
                    if site_domain and old_em_dom and (old_em_dom == site_domain or old_em_dom.endswith("." + site_domain)):
                        outcome_status = "revalidated"
                        outcome_reason = f"Confirmed existing company email matches website domain '{site_domain}'."
                    else:
                        outcome_status = "no_email_found"
                        outcome_reason = "No usable business email found on official website; excluded from active outreach pool."
            except Exception as exc:
                outcome_status = "scrape_inconclusive"
                outcome_reason = f"Website scraping encountered transient error ({type(exc).__name__}); retained for retry."
    else:
        old_em_dom = extract_email_domain(initial_email)
        if site_domain and old_em_dom and (old_em_dom == site_domain or old_em_dom.endswith("." + site_domain)):
            outcome_status = "revalidated"
            outcome_reason = f"Confirmed existing company email matches website domain '{site_domain}'."
        elif getattr(lead, "email_business_association_status", None) == "matched" and not website_url:
            outcome_status = "revalidated"
            outcome_reason = "Lead association pre-matched; revalidated email syntax and DNS/MX deliverability."
        elif not website_url:
            outcome_status = "no_email_found"
            outcome_reason = "Lead does not have an official website; excluded from active outreach pool."
        else:
            outcome_status = "revalidated"

    # Step 2: Evaluate candidates against company domain (Rule C: Ranking candidates)
    # Rank candidates using direct contact-page evidence, domain match, explicit business-contact context
    def rank_candidate(c: dict[str, Any]) -> int:
        score = 0
        c_email = (c.get("email") or "").strip().lower()
        c_dom = extract_email_domain(c_email)
        local = c_email.split("@")[0] if "@" in c_email else ""
        source_type = c.get("source_type") or ""
        method = c.get("extraction_method") or ""

        # 1. Domain match gets highest priority (+100)
        if site_domain and (c_dom == site_domain or c_dom.endswith("." + site_domain) or site_domain.endswith("." + c_dom)):
            score += 100

        # 2. Source evidence (+30 for direct contact page / mailto / company profile)
        if "contact" in source_type or "mailto" in method or "company_profile" in method:
            score += 30
        elif source_type == "http_page_scrape":
            score += 10

        # 3. Business contact prefixes (+20)
        if any(local.startswith(pref) for pref in ("info", "contact", "sales", "support", "hello", "office", "enquiry", "admin", "mail")):
            score += 20

        # 4. Association status bonuses
        if c.get("association_status") == EmailAssociationStatus.MATCHED.value:
            score += 50
        elif c.get("association_status") == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value:
            score += 10

        return score

    sorted_candidates = sorted(scraped_candidates, key=rank_candidate, reverse=True)

    matched_candidate = None
    external_candidates = []

    for cand in sorted_candidates:
        cand_email = (cand.get("email") or "").strip().lower()
        cand_domain = extract_email_domain(cand_email)
        if site_domain and (cand_domain == site_domain or cand_domain.endswith("." + site_domain) or site_domain.endswith("." + cand_domain)):
            if not matched_candidate:
                matched_candidate = cand
        else:
            external_candidates.append(cand)

    old_email = lead.email
    email_to_verify = old_email

    # Decision Rules Application
    if matched_candidate:
        new_email = matched_candidate["email"]
        if new_email.lower() != (old_email or "").lower():
            outcome_status = "corrected"
            outcome_reason = f"Corrected mismatched email from official website evidence on {matched_candidate.get('source_url') or evidence_url}."
            corrected_email = new_email
            email_to_verify = new_email
        else:
            outcome_status = "revalidated"
            outcome_reason = f"Confirmed existing company email matches website domain '{site_domain}'."
            email_to_verify = old_email
    elif external_candidates and outcome_status not in ("scrape_inconclusive", "no_email_found"):
        # Website only lists an email on another domain (Rule D)
        outcome_status = "manual_review"
        outcome_reason = f"Website lists only external domain email ({external_candidates[0]['email']}); retained for operator review without falsely asserting company domain."
        email_to_verify = old_email
    elif outcome_status != "scrape_inconclusive" and site_domain and old_email and (extract_email_domain(old_email) == site_domain or extract_email_domain(old_email).endswith("." + site_domain)):
        # Rule B: Existing email matches company domain (when scrape was conclusive)
        outcome_status = "revalidated"
        outcome_reason = f"Confirmed existing company email matches website domain '{site_domain}'."
        email_to_verify = old_email
    elif outcome_status == "inconclusive":
        # Retain existing email
        email_to_verify = old_email

    # Step 3: Syntax and DNS/MX Routeability validation
    v_res = await email_verifier.verify_email(
        email=email_to_verify,
        smtp_probe_enabled=False,
        catch_all_probe_enabled=False,
    )

    # Step 4: Apply mutations if not dry_run
    if not dry_run:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        
        # Merge discovered candidates into lead.email_candidates
        existing_cands = list(lead.email_candidates or [])
        for sc in scraped_candidates:
            if not any(ec.get("email") == sc.get("email") for ec in existing_cands):
                existing_cands.append(sc)
        lead.email_candidates = existing_cands

        if outcome_status == "corrected" and corrected_email:
            # Record previous address in EmailCorrection audit record
            correction = EmailCorrection(
                lead_id=lead.id,
                old_email=old_email,
                new_email=corrected_email,
                source="website_reverify",
                status="accepted",
                detected_at=datetime.datetime.now(datetime.timezone.utc),
                reviewed_at=datetime.datetime.now(datetime.timezone.utc),
            )
            db.add(correction)

            # Update primary email
            lead.email = corrected_email
            lead.email_source_url = matched_candidate.get("source_url") or evidence_url
            lead.email_source_type = matched_candidate.get("source_type") or "http_page_scrape"
            lead.email_extraction_method = matched_candidate.get("extraction_method") or "website_reverify"
            lead.email_domain = extract_email_domain(corrected_email)
            lead.website_domain = site_domain
            lead.email_domain_match = True
            lead.email_business_association_status = EmailAssociationStatus.MATCHED.value
            lead.email_association_reason = matched_candidate.get("association_reason") or f"Direct domain match with business website '{site_domain}'"
            lead.email_verification_status = v_res.status
            lead.email_verification_details = v_res.to_dict()
            lead.email_verified_at = now_dt

            # Check sendability and quarantine
            if not v_res.is_sendable:
                lead.is_quarantined = True
                lead.quarantine_reason = v_res.exclusion_reason or f"Corrected email verification failed: {v_res.status}"
            else:
                lead.is_quarantined = False
                lead.quarantine_reason = None

            db.add(ActivityLog(
                event_type="email_reverify_corrected",
                lead_id=lead.id,
                message=f"Re-verify corrected email for {lead.business_name}: {old_email} -> {corrected_email} based on evidence from {lead.email_source_url} (deliverability: {v_res.status}).",
            ))

        elif outcome_status == "revalidated":
            lead.email_domain = extract_email_domain(old_email)
            lead.website_domain = site_domain
            lead.email_domain_match = True
            lead.email_business_association_status = EmailAssociationStatus.MATCHED.value
            lead.email_association_reason = f"Confirmed direct domain match with official website '{site_domain}'."
            lead.email_verification_status = v_res.status
            lead.email_verification_details = v_res.to_dict()
            lead.email_verified_at = now_dt

            if not v_res.is_sendable:
                lead.is_quarantined = True
                lead.quarantine_reason = v_res.exclusion_reason or f"Email verification failed: {v_res.status}"
            else:
                # Leave quarantine only if previously held for verification or domain mismatch
                lead.is_quarantined = False
                lead.quarantine_reason = None

            db.add(ActivityLog(
                event_type="email_reverify_revalidated",
                lead_id=lead.id,
                message=f"Re-verify confirmed existing email {old_email} matches website {website_url} (deliverability: {v_res.status}).",
            ))

        elif outcome_status == "no_email_found":
            # Rule E: Exclude from active outreach pool via reversible quarantine
            lead.is_quarantined = True
            lead.quarantine_reason = "No usable company email found on official website; excluded from active outreach."
            lead.email_verification_status = v_res.status
            lead.email_verification_details = v_res.to_dict()
            lead.email_verified_at = now_dt

            db.add(ActivityLog(
                event_type="email_reverify_excluded",
                lead_id=lead.id,
                message=f"Re-verify excluded {lead.business_name} ({old_email}): no verified company email found on {website_url}.",
            ))

        elif outcome_status == "scrape_inconclusive":
            # Rule F: Inconclusive attempt, NEVER delete or overwrite
            lead.email_verification_status = v_res.status
            lead.email_verification_details = v_res.to_dict()
            lead.email_verified_at = now_dt
            db.add(ActivityLog(
                event_type="email_reverify_inconclusive",
                lead_id=lead.id,
                message=f"Re-verify scrape inconclusive for {lead.business_name} ({website_url}): {outcome_reason}",
            ))

        elif outcome_status == "manual_review":
            lead.email_business_association_status = EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value
            lead.email_association_reason = outcome_reason
            lead.email_verification_status = v_res.status
            lead.email_verification_details = v_res.to_dict()
            lead.email_verified_at = now_dt
            lead.is_quarantined = True
            lead.quarantine_reason = "External domain contact requires operator review before outreach."
            db.add(ActivityLog(
                event_type="email_reverify_manual_review",
                lead_id=lead.id,
                message=f"Re-verify placed {lead.business_name} in operator review: external domain email detected.",
            ))

        await db.commit()
        await db.refresh(lead)

    return {
        "lead_id": lead_id_str,
        "business_name": lead.business_name,
        "website": website_url,
        "outcome_status": outcome_status,
        "outcome_reason": outcome_reason,
        "old_email": old_email,
        "new_email": lead.email if not dry_run else (corrected_email or old_email),
        "evidence_url": evidence_url,
        "is_quarantined": lead.is_quarantined if not dry_run else (outcome_status in ("no_email_found", "manual_review")),
        "quarantine_reason": lead.quarantine_reason,
        "verification_status": v_res.status,
        "is_sendable": (not lead.is_quarantined) if not dry_run else (outcome_status in ("corrected", "revalidated") and v_res.is_sendable),
        "candidates_found": len(scraped_candidates),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification": v_res.to_dict(),
    }


@router.post("/reverify/{lead_id}", summary="Re-verify email ownership against company website and update deliverability")
async def reverify_lead(
    lead_id: str,
    payload: Optional[ReverifyRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Re-verifies email ownership against the lead's official company website.
    Corrects mismatched addresses from freshly scraped evidence, re-runs syntax/MX
    validation, and recalculates outreach eligibility.
    """
    try:
        uid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")

    lead = await db.get(Lead, uid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    scrape_enabled = payload.website_scrape_enabled if payload else True
    return await reverify_lead_ownership_and_deliverability(
        lead=lead,
        db=db,
        website_scrape_enabled=scrape_enabled,
        dry_run=False,
    )


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
                lead.email_verified_at = datetime.datetime.now(datetime.timezone.utc)
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
        "total": total_leads,
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


@router.post("/bulk-approve-domain-matches", summary="Approve verified corporate website and email domain matches")
async def bulk_approve_domain_matches(
    payload: BulkApproveDomainMatchesRequest,
    db: AsyncSession = Depends(get_db),
    current_operator: dict = Depends(require_authorized_operator),
) -> dict[str, Any]:
    """Approve only independently verified, non-quarantined corporate domain matches."""
    unique_ids = list(dict.fromkeys(payload.lead_ids))
    try:
        lead_uuids = [uuid.UUID(lead_id) for lead_id in unique_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="All lead_ids must be valid UUIDs")

    result = await db.execute(select(Lead).where(Lead.id.in_(lead_uuids)))
    leads_by_id = {str(lead.id): lead for lead in result.scalars().all()}
    approved = []
    skipped = []
    reviewer = (current_operator.get("sub") or "authenticated operator").strip()

    for lead_id in unique_ids:
        lead = leads_by_id.get(lead_id)
        if not lead:
            skipped.append({"id": lead_id, "reason": "not_found"})
            continue

        email_domain = extract_email_domain(lead.email)
        site_domain = extract_domain_from_url(lead.website)
        domains_match = bool(
            email_domain and site_domain
            and (email_domain == site_domain
                 or email_domain.endswith("." + site_domain)
                 or site_domain.endswith("." + email_domain))
        )
        eligible = (
            lead.email_verification_status == "valid"
            and not lead.is_quarantined
            and lead.email_business_association_status in (
                "unverified_association", "external_domain_review", "pending_review", "unverified"
            )
            and lead.email_domain_match is True
            and domains_match
            and lead.website_association_status == "verified_primary"
            and not is_public_email_provider(email_domain)
            and bool(lead.email_source_url and lead.email_source_type)
        )
        if not eligible:
            skipped.append({"id": lead_id, "reason": "does_not_meet_verified_domain_match_policy"})
            continue

        lead.email_business_association_status = EmailAssociationStatus.APPROVED.value
        lead.email_association_reason = (
            f"Bulk approved by {reviewer}: verified primary website domain {site_domain} "
            f"matches corporate email domain {email_domain}."
        )
        db.add(ActivityLog(
            event_type="association_approved",
            lead_id=lead.id,
            message=(
                f"Corporate association bulk-approved for {lead.business_name} ({lead.email}): "
                f"verified primary website and email domain match ({site_domain}); quarantine unchanged."
            ),
        ))
        approved.append(lead_id)

    if approved:
        await db.commit()
    return {"approved_count": len(approved), "approved_ids": approved, "skipped": skipped}


class BulkPromoteRequest(BaseModel):
    lead_ids: list[str]
    reason: Optional[str] = "Bulk operator promotion to Active Sendable"


@router.post("/bulk-promote", summary="Bulk promote selected leads to Active Sendable segment")
async def bulk_promote_leads(
    payload: BulkPromoteRequest,
    db: AsyncSession = Depends(get_db),
    current_operator: dict = Depends(require_authorized_operator),
) -> dict[str, Any]:
    """
    Operator-initiated bulk promotion workflow.
    Validates MX and deliverability for all selected leads, sets association to 'approved',
    clears any quarantine flag, and moves them to Active Sendable.
    """
    unique_ids = list(dict.fromkeys(payload.lead_ids))
    try:
        lead_uuids = [uuid.UUID(lid) for lid in unique_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="All lead_ids must be valid UUIDs")

    result = await db.execute(select(Lead).where(Lead.id.in_(lead_uuids)))
    leads = result.scalars().all()
    reviewer = (current_operator.get("sub") or "authenticated operator").strip()
    justification = (payload.reason or "").strip() or "Bulk operator promotion to sendable"

    promoted = []
    failed = []

    for lead in leads:
        if not lead.email:
            failed.append({"id": str(lead.id), "reason": "Missing email"})
            continue

        v_res = await email_verifier.verify_email(
            email=lead.email,
            smtp_probe_enabled=False,
            catch_all_probe_enabled=False,
        )

        lead.email_verification_status = v_res.status
        lead.email_verification_details = v_res.to_dict()
        lead.email_verified_at = datetime.datetime.now(datetime.timezone.utc)

        if not v_res.is_sendable:
            lead.is_quarantined = True
            lead.quarantine_reason = v_res.exclusion_reason or f"Email verification failed: {v_res.status}"
            failed.append({"id": str(lead.id), "reason": lead.quarantine_reason})
            continue

        lead.email_business_association_status = EmailAssociationStatus.APPROVED.value
        lead.email_association_reason = f"Bulk approved by {reviewer}: {justification}"
        lead.is_quarantined = False
        lead.quarantine_reason = None
        promoted.append(str(lead.id))

    await db.commit()

    if promoted:
        db.add(ActivityLog(
            event_type="bulk_promote_to_sendable_approved",
            message=f"Bulk promoted {len(promoted)} lead(s) to Active Sendable by {reviewer} ({len(failed)} failed/held).",
        ))
        await db.commit()

    return {
        "promoted_count": len(promoted),
        "failed_count": len(failed),
        "promoted_ids": promoted,
        "failed": failed,
    }


class PromoteToSendableRequest(BaseModel):
    reason: str = Field(
        "Operator-verified: email and business association confirmed as sendable",
        description="Auditable justification for the promotion",
    )


@router.post("/promote-to-sendable/{lead_id}", summary="Verify email and promote lead to Active Sendable segment")
async def promote_lead_to_sendable(
    lead_id: str,
    payload: PromoteToSendableRequest,
    db: AsyncSession = Depends(get_db),
    current_operator: dict = Depends(require_authorized_operator),
) -> dict[str, Any]:
    """
    Operator-initiated promotion workflow.

    Runs a fresh syntax/MX verification pass on the lead's email, then — if
    verification passes — sets association_status to 'approved' so the lead
    graduates into the Active Sendable segment and is included in campaign queues.

    Safe-guards:
    - Quarantined leads are not promoted (returns 409).
    - Leads with invalid / disposable / not_found email are not promoted.
    - Activity log entry is written for every outcome.
    """
    try:
        uid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")

    lead = await db.get(Lead, uid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not lead.email:
        raise HTTPException(status_code=422, detail="Lead has no email address recorded.")

    reviewer = (current_operator.get("sub") or "authenticated operator").strip()
    justification = (payload.reason or "").strip() or "Operator-verified as sendable"

    # Fresh email syntax + MX verification
    v_res = await email_verifier.verify_email(
        email=lead.email,
        smtp_probe_enabled=False,
        catch_all_probe_enabled=False,
    )

    lead.email_verification_status = v_res.status
    lead.email_verification_details = v_res.to_dict()
    lead.email_verified_at = datetime.datetime.now(datetime.timezone.utc)

    if not v_res.is_sendable:
        # Quarantine automatically for failed verification
        lead.is_quarantined = True
        lead.quarantine_reason = v_res.exclusion_reason or f"Promote-to-sendable failed: {v_res.status}"
        await db.commit()
        db.add(ActivityLog(
            event_type="promote_to_sendable_failed",
            lead_id=lead.id,
            message=(
                f"Promote-to-sendable FAILED for {lead.business_name} ({lead.email}): "
                f"email verification returned '{v_res.status}' — lead quarantined."
            ),
        ))
        await db.commit()
        return {
            "lead_id": str(lead.id),
            "outcome": "failed",
            "reason": f"Email failed verification ({v_res.status}). Lead has been quarantined.",
            "verification_status": v_res.status,
            "is_quarantined": True,
            "is_sendable": False,
        }

    # Verification passed — approve association and clear any residual quarantine
    lead.email_business_association_status = EmailAssociationStatus.APPROVED.value
    lead.email_association_reason = (
        f"Approved by {reviewer}: {justification}"
    )
    lead.is_quarantined = False
    lead.quarantine_reason = None

    await db.commit()

    db.add(ActivityLog(
        event_type="promote_to_sendable_approved",
        lead_id=lead.id,
        message=(
            f"Lead {lead.business_name} ({lead.email}) promoted to Active Sendable by {reviewer}. "
            f"Verification: {v_res.status}. Justification: {justification}"
        ),
    ))
    await db.commit()
    await db.refresh(lead)

    return {
        "lead_id": str(lead.id),
        "outcome": "promoted",
        "reason": "Lead email verified and association approved. Now in Active Sendable segment.",
        "verification_status": v_res.status,
        "is_quarantined": False,
        "is_sendable": True,
        "association_status": lead.email_business_association_status,
    }


@router.post("/bulk-reverify", summary="Bulk re-verify email ownership and deliverability with dry-run preview")
async def bulk_reverify_leads(
    payload: BulkReverifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Resumable bulk re-verification workflow:
    - Supports dry-run report vs controlled batch execution.
    - Filters by specific lead IDs, domain mismatch, or unverified association.
    - Inspects websites, corrects mismatched emails, revalidates syntax/MX, and excludes invalid records.
    - Returns detailed summary metrics: examined, mismatches, replacements found, corrected, manual review,
      scraping failures, and excluded.
    """
    stmt = select(Lead)

    if payload.lead_ids:
        uids = []
        for lid in payload.lead_ids:
            try:
                uids.append(uuid.UUID(lid))
            except ValueError:
                continue
        stmt = stmt.where(Lead.id.in_(uids))
    else:
        # Require website
        stmt = stmt.where(and_(Lead.website.isnot(None), Lead.website != ""))
        if payload.filter_unverified_association_only:
            stmt = stmt.where(Lead.email_business_association_status.in_(["unverified_association", "unverified"]))

    limit_val = min(500, max(1, payload.limit or 100))
    stmt = stmt.order_by(Lead.created_at.desc()).limit(limit_val)

    res = await db.execute(stmt)
    leads = res.scalars().all()

    # If filter_mismatched_only is set, filter in memory
    filtered_leads = []
    for l in leads:
        if payload.filter_mismatched_only:
            em_dom = extract_email_domain(l.email)
            site_dom = extract_domain_from_url(clean_website(l.website))
            if em_dom and site_dom and (em_dom == site_dom or em_dom.endswith("." + site_dom) or site_dom.endswith("." + em_dom)):
                continue
        filtered_leads.append(l)

    results = []
    domain_mismatches_identified = 0
    website_replacements_found = 0
    emails_corrected = 0
    retained_for_manual_review = 0
    records_with_scraping_failures = 0
    records_excluded = 0
    revalidated_count = 0

    for l in filtered_leads:
        em_dom = extract_email_domain(l.email)
        site_dom = extract_domain_from_url(clean_website(l.website))
        is_mismatch = bool(em_dom and site_dom and em_dom != site_dom and not em_dom.endswith("." + site_dom) and not site_dom.endswith("." + em_dom))
        if is_mismatch:
            domain_mismatches_identified += 1

        rec_result = await reverify_lead_ownership_and_deliverability(
            lead=l,
            db=db,
            website_scrape_enabled=True,
            dry_run=payload.dry_run,
        )
        status = rec_result["outcome_status"]
        if status == "corrected":
            website_replacements_found += 1
            emails_corrected += 1
        elif status == "revalidated":
            revalidated_count += 1
        elif status == "manual_review":
            retained_for_manual_review += 1
        elif status == "scrape_inconclusive":
            records_with_scraping_failures += 1
        elif status == "no_email_found":
            records_excluded += 1

        results.append(rec_result)

    return {
        "mode": "dry_run" if payload.dry_run else "applied",
        "total_records_examined": len(filtered_leads),
        "domain_mismatches_identified": domain_mismatches_identified,
        "website_replacements_found": website_replacements_found,
        "emails_corrected_and_validated": emails_corrected,
        "emails_revalidated_and_retained": revalidated_count,
        "records_retained_for_manual_review": retained_for_manual_review,
        "records_with_scraping_failures": records_with_scraping_failures,
        "records_excluded_from_active_pool": records_excluded,
        "results": results,
    }
