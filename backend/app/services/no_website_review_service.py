"""
backend/app/services/no_website_review_service.py

Authoritative Service for Evidence-Based No-Website Lead Review.
Manages:
1. Classification of 84 confirmed no-website businesses:
   - 5 proposed evidence-backed candidates (verified seller profiles/social presence with distinctive token matches)
   - 46 operator-review candidates (public-provider emails with partial source URL provenance or needing operator judgment)
   - 16 unsupported candidates that remain excluded (missing source provenance and unrelated email handles)
   - Corporate/quarantined contacts (including A G TRADEMART PVT LTD / tn.gov deletion-review quarantine)
2. Live calculation of campaign eligibility using evaluate_lead_campaign_eligibility
3. Explicit auditable Approve, Reject, and Defer actions with ActivityLog tracking
4. Read-only investigation metadata for the 121 inconclusive website-less records
"""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Lead, Audit, ActivityLog, LeadStatus
from app.schemas import (
    ApproveAssociationRequest,
    BulkApproveAssociationRequest,
    BulkRejectAssociationRequest,
)
from app.services.campaign_eligibility_service import (
    WebsiteClassification,
    EmailSendabilityClassification,
    CampaignType,
    classify_website,
    classify_email_sendability,
    evaluate_lead_campaign_eligibility,
    extract_email_domain,
    is_valid_email_syntax,
)
from app.utils.email_constants import is_public_email_provider

logger = logging.getLogger(__name__)

# Stopwords for commercial name token extraction
BUSINESS_STOPWORDS = frozenset({
    "pvt", "ltd", "private", "limited", "company", "co", "enterprises",
    "trading", "traders", "exports", "importers", "international", "global",
    "overseas", "india", "services", "corporation", "corp", "agency",
    "agencies", "industries", "group", "llp", "inc", "house", "firm",
})

# Path to cached classified audit results if present
CLASSIFIED_JSON_PATH = Path(__file__).resolve().parents[2] / "classified_67_results.json"


def extract_distinctive_tokens(name: str) -> List[str]:
    """Extract distinctive tokens from a business name for association matching."""
    if not name:
        return []
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", name.lower())
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 3]
    distinctive = [t for t in tokens if t not in BUSINESS_STOPWORDS]
    return distinctive if distinctive else tokens


def extract_matching_tokens(name: str, email: str) -> Tuple[List[str], List[str]]:
    """Return (distinctive_tokens, matched_tokens) comparing business name to email handle."""
    if not email or "@" not in email:
        return ([], [])
    local_part = email.split("@")[0].lower()
    cleaned_local = re.sub(r"[^a-z0-9]", "", local_part)
    
    distinctive = extract_distinctive_tokens(name)
    matched = [t for t in distinctive if t in cleaned_local]
    return (distinctive, matched)


def load_cached_audit_classifications() -> Dict[str, Dict[str, Any]]:
    """Load pre-audited classifications for fast hydration if file is present."""
    if not CLASSIFIED_JSON_PATH.exists():
        return {}
    try:
        with open(CLASSIFIED_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        lookup = {}
        for item in data.get("auto_association", []):
            lookup[str(item["id"])] = {**item, "group": "evidence_backed"}
        for item in data.get("operator_approval", []):
            lookup[str(item["id"])] = {**item, "group": "operator_review"}
        for item in data.get("remain_excluded", []):
            lookup[str(item["id"])] = {**item, "group": "unsupported"}
        return lookup
    except Exception as e:
        logger.warning(f"Could not load cached classified json: {e}")
        return {}


async def build_no_website_review_queue(db: AsyncSession) -> Dict[str, Any]:
    """
    Build the complete evidence-based review queue for all confirmed no-website leads.
    Classifies leads into:
    - evidence_backed (5 proposed candidates)
    - operator_review (46 operator-review candidates)
    - unsupported (16 unsupported candidates + quarantined/unsupported records)
    """
    cached_lookup = load_cached_audit_classifications()

    # Query only candidate no-website leads with their audit attached (fast indexed lookup)
    stmt = (
        select(Lead)
        .options(selectinload(Lead.audit))
        .outerjoin(Audit, Lead.id == Audit.lead_id)
        .where(
            or_(
                Lead.website.is_(None),
                Lead.website == "",
                Lead.website.in_(["none", "n/a", "no", "null", "false", "-", "http://", "https://"]),
                Lead.website_association_status == "no_website",
                Audit.error_message.ilike("SITE_STATUS:PARKED%"),
                Audit.error_message.ilike("SITE_STATUS:DEMO%"),
            )
        )
    )
    result = await db.execute(stmt)
    candidate_leads = result.scalars().all()

    # Filter strictly to confirmed no-website businesses
    no_website_leads = []
    inconclusive_count = 0

    for lead in candidate_leads:
        site_class = classify_website(lead, lead.audit)
        if site_class == WebsiteClassification.NO_WEBSITE:
            no_website_leads.append(lead)
        elif site_class == WebsiteClassification.AUDIT_INCONCLUSIVE and (not lead.website or lead.website.strip() == ""):
            inconclusive_count += 1

    evidence_backed_items = []
    operator_review_items = []
    approved_items = []
    unsupported_items = []

    total_eligible_count = 0
    routeable_public_count = 0

    for lead in no_website_leads:
        lead_id_str = str(lead.id)
        cached_info = cached_lookup.get(lead_id_str)

        # Run authoritative campaign eligibility evaluation
        eligibility = evaluate_lead_campaign_eligibility(
            lead,
            audit=lead.audit,
            campaign_type=CampaignType.NO_WEBSITE_DESIGN.value,
        )
        if eligibility.is_eligible:
            total_eligible_count += 1

        email = lead.email or ""
        domain = extract_email_domain(email)
        is_pub = is_public_email_provider(domain)
        is_routeable = lead.email_verification_status == "valid"

        if is_pub and is_routeable:
            routeable_public_count += 1

        # Extract provenance from candidates or lead fields
        source_url = lead.email_source_url or ""
        extraction_method = lead.email_source_type or ""
        
        candidates = lead.email_candidates or []
        for cand in candidates:
            if isinstance(cand, dict) and cand.get("email") == email:
                if not source_url and cand.get("source_url"):
                    source_url = cand.get("source_url")
                if not extraction_method and cand.get("extraction_method"):
                    extraction_method = cand.get("extraction_method")
                elif not extraction_method and cand.get("source_type"):
                    extraction_method = cand.get("source_type")

        # Distinctive tokens & matches
        distinctive_tokens, matched_tokens = extract_matching_tokens(lead.business_name, email)
        
        # Override with cached audit info if available
        if cached_info:
            source_url = source_url or cached_info.get("source_url") or ""
            extraction_method = extraction_method or cached_info.get("extraction_method") or ""
            class_reason = cached_info.get("class_reason") or ""
            target_group = cached_info.get("group")
        else:
            class_reason = ""
            target_group = None

        # Build card representation
        card = {
            "id": lead_id_str,
            "business_name": lead.business_name,
            "email": email,
            "provider": domain or "unknown",
            "phone": lead.phone,
            "address": getattr(lead, "address", None),
            "source_url": source_url,
            "extraction_method": extraction_method or "unrecorded",
            "business_name_match_evidence": {
                "distinctive_tokens": distinctive_tokens,
                "matched_tokens": matched_tokens,
                "has_match": len(matched_tokens) > 0,
            },
            "routeability_status": lead.email_verification_status or "unverified",
            "mailbox_confirmed": bool((lead.email_verification_details or {}).get("mailbox_confirmed", False)),
            "association_status": lead.email_business_association_status or "unverified_association",
            "association_reason": lead.email_association_reason,
            "is_quarantined": bool(lead.is_quarantined),
            "quarantine_reason": lead.quarantine_reason,
            "campaign_eligibility": {
                "is_eligible": eligibility.is_eligible,
                "exclusion_reason": eligibility.exclusion_reason,
                "website_class": eligibility.website_classification.value,
                "email_class": eligibility.email_sendability.value,
            },
            "class_reason": class_reason,
            "verification_details": lead.email_verification_details or {},
            "candidates_count": len(candidates),
        }

        # Place into appropriate queue section:
        # 1. Approved contacts (non-quarantined) transition immediately into approved_items
        if lead.email_business_association_status == "approved" and not lead.is_quarantined:
            card["is_approved"] = True
            card["approved_review_group"] = target_group or "operator_review"
            approved_items.append(card)
        # 2. Quarantined or explicitly rejected contacts belong in unsupported
        elif lead.is_quarantined or lead.email_business_association_status in ("mismatched_source", "invalid_format"):
            unsupported_items.append(card)
        # 3. Pending review candidates categorized by audit group
        elif target_group == "evidence_backed":
            evidence_backed_items.append(card)
        elif target_group == "operator_review":
            operator_review_items.append(card)
        elif target_group == "unsupported":
            unsupported_items.append(card)
        else:
            # Fallback heuristic for any other no-website lead (e.g. corporate or unverified)
            if not is_pub or not is_routeable:
                unsupported_items.append(card)
            elif len(matched_tokens) > 0 and source_url:
                operator_review_items.append(card)
            else:
                unsupported_items.append(card)

    unsupported_public_count = sum(
        1 for item in unsupported_items
        if item.get("routeability_status") == "valid" and is_public_email_provider(item.get("provider", ""))
    )

    return {
        "stats": {
            "total_no_website": len(no_website_leads),
            "routeable_public": routeable_public_count,
            "campaign_eligible_count": total_eligible_count,
            "approved_count": len(approved_items),
            "evidence_backed_count": len(evidence_backed_items),
            "operator_review_count": len(operator_review_items),
            "unsupported_count": unsupported_public_count,
            "unsupported_total_count": len(unsupported_items),
            "unsupported_other_count": len(unsupported_items) - unsupported_public_count,
            "audit_inconclusive_count": inconclusive_count,
        },
        "evidence_backed": evidence_backed_items,
        "operator_review": operator_review_items,
        "approved": approved_items,
        "unsupported": unsupported_items,
    }


async def approve_no_website_lead(
    lead_id: uuid.UUID,
    body: ApproveAssociationRequest,
    operator: dict,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Approve email business association for a no-website lead.
    Enforces safeguards:
    - Operator authorization verified
    - Lead must exist
    - Cannot approve invalid email format
    - Quarantined records with non-association reasons (e.g. deletion review / government domain)
      remain quarantined and cannot be approved to qualify for campaigns.
    - Persists reviewer identity, timestamp, justification, and policy reference.
    - Logs ActivityLog auditable record.
    - Re-evaluates campaign eligibility using evaluate_lead_campaign_eligibility.
    """
    lead = await db.get(Lead, lead_id, options=[selectinload(Lead.audit)])
    if not lead:
        raise ValueError("Lead not found.")

    trusted_reviewer = (operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise PermissionError("Authenticated operator identity missing.")

    if body.reviewer and body.reviewer.strip() and body.reviewer.strip().lower() != trusted_reviewer.lower():
        raise PermissionError(
            f"Reviewer identity mismatch: supplied '{body.reviewer.strip()}' does not match principal '{trusted_reviewer}'."
        )

    if not body.reason or len(body.reason.strip()) < 5:
        raise ValueError("Justification reason of at least 5 characters is required for auditable approval.")

    if not is_valid_email_syntax(lead.email):
        raise ValueError("Cannot approve an email with invalid address syntax.")

    # Preserve quarantine for specific risk cases like government domains or deletion review
    if lead.is_quarantined:
        q_reason = (lead.quarantine_reason or "").lower()
        is_assoc_quarantine = any(
            term in q_reason for term in (
                "association", "external_domain", "mismatched", "free mail", "free-mail", "unverified domain"
            )
        )
        if not is_assoc_quarantine:
            raise ValueError(
                f"Cannot approve association for lead quarantined under policy: {lead.quarantine_reason}"
            )

    lead.email_business_association_status = "approved"
    lead.email_association_reason = (
        f"Approved by {trusted_reviewer} ({body.policy_reference or 'evidence_review'}): {body.reason.strip()}"
    )

    # Lift quarantine ONLY if it was quarantined for association reasons and email is routeable
    if lead.is_quarantined:
        if lead.email_verification_status == "valid":
            lead.is_quarantined = False
            lead.quarantine_reason = None

    # Populate email_source_url / email_source_type if candidates contain provenance
    if not lead.email_source_url and lead.email_candidates:
        for cand in lead.email_candidates:
            if isinstance(cand, dict) and cand.get("email") == lead.email:
                if cand.get("source_url"):
                    lead.email_source_url = cand.get("source_url")
                if cand.get("source_type"):
                    lead.email_source_type = cand.get("source_type")
                break

    # Record ActivityLog
    log = ActivityLog(
        event_type="no_website_association_approved",
        lead_id=lead.id,
        message=(
            f"No-website association approved for {lead.business_name} ({lead.email}) "
            f"by {trusted_reviewer} under policy '{body.policy_reference}': {body.reason.strip()}"
        ),
    )
    db.add(log)
    await db.commit()

    # Re-evaluate campaign eligibility using authoritative shared evaluator
    eligibility = evaluate_lead_campaign_eligibility(
        lead,
        audit=lead.audit,
        campaign_type=CampaignType.NO_WEBSITE_DESIGN.value,
    )

    return {
        "success": True,
        "lead_id": str(lead.id),
        "business_name": lead.business_name,
        "email": lead.email,
        "association_status": lead.email_business_association_status,
        "association_reason": lead.email_association_reason,
        "is_quarantined": lead.is_quarantined,
        "campaign_eligibility": {
            "is_eligible": eligibility.is_eligible,
            "exclusion_reason": eligibility.exclusion_reason,
            "website_class": eligibility.website_classification.value,
            "email_class": eligibility.email_sendability.value,
        },
    }


async def reject_no_website_lead(
    lead_id: uuid.UUID,
    reason: str,
    operator: dict,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Explicitly reject association for a no-website lead.
    Sets status to 'mismatched_source', quarantines the lead, logs ActivityLog.
    """
    lead = await db.get(Lead, lead_id, options=[selectinload(Lead.audit)])
    if not lead:
        raise ValueError("Lead not found.")

    trusted_reviewer = (operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise PermissionError("Authenticated operator identity missing.")

    if not reason or len(reason.strip()) < 3:
        raise ValueError("Rejection reason of at least 3 characters is required.")

    lead.email_business_association_status = "mismatched_source"
    lead.email_association_reason = f"Rejected by {trusted_reviewer}: {reason.strip()}"
    lead.is_quarantined = True
    lead.quarantine_reason = f"Association rejected by operator {trusted_reviewer}: {reason.strip()}"

    log = ActivityLog(
        event_type="no_website_association_rejected",
        lead_id=lead.id,
        message=(
            f"No-website association rejected for {lead.business_name} ({lead.email}) "
            f"by {trusted_reviewer}: {reason.strip()}"
        ),
    )
    db.add(log)
    await db.commit()

    eligibility = evaluate_lead_campaign_eligibility(
        lead,
        audit=lead.audit,
        campaign_type=CampaignType.NO_WEBSITE_DESIGN.value,
    )

    return {
        "success": True,
        "lead_id": str(lead.id),
        "business_name": lead.business_name,
        "association_status": lead.email_business_association_status,
        "is_quarantined": lead.is_quarantined,
        "quarantine_reason": lead.quarantine_reason,
        "campaign_eligibility": {
            "is_eligible": eligibility.is_eligible,
            "exclusion_reason": eligibility.exclusion_reason,
        },
    }


async def defer_no_website_lead(
    lead_id: uuid.UUID,
    reason: str,
    operator: dict,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Defer review of a no-website lead without changing association status or campaign eligibility.
    """
    lead = await db.get(Lead, lead_id, options=[selectinload(Lead.audit)])
    if not lead:
        raise ValueError("Lead not found.")

    trusted_reviewer = (operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise PermissionError("Authenticated operator identity missing.")

    if not reason or len(reason.strip()) < 3:
        raise ValueError("Deferral note of at least 3 characters is required.")

    lead.email_association_reason = f"Deferred by {trusted_reviewer}: {reason.strip()}"

    log = ActivityLog(
        event_type="no_website_association_deferred",
        lead_id=lead.id,
        message=(
            f"No-website association review deferred for {lead.business_name} ({lead.email}) "
            f"by {trusted_reviewer}: {reason.strip()}"
        ),
    )
    db.add(log)
    await db.commit()

    eligibility = evaluate_lead_campaign_eligibility(
        lead,
        audit=lead.audit,
        campaign_type=CampaignType.NO_WEBSITE_DESIGN.value,
    )

    return {
        "success": True,
        "lead_id": str(lead.id),
        "business_name": lead.business_name,
        "association_status": lead.email_business_association_status or "unverified_association",
        "is_eligible": eligibility.is_eligible,
        "exclusion_reason": eligibility.exclusion_reason,
    }


async def bulk_approve_no_website_leads(
    lead_ids: List[uuid.UUID],
    body: BulkApproveAssociationRequest,
    operator: dict,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Bulk approve email business association for a list of no-website leads.
    Enforces the same security and audit rules as single lead approval:
    - Operator authenticated
    - Invalid syntax rejected
    - Non-association quarantined records (e.g. government domains or deletion review) blocked
    - Association quarantine lifted if email routeable
    - ActivityLog entry created for each approved lead
    - Returns summary of approved, skipped, and errors
    """
    trusted_reviewer = (operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise PermissionError("Authenticated operator identity missing.")

    if body.reviewer and body.reviewer.strip() and body.reviewer.strip().lower() != trusted_reviewer.lower():
        raise PermissionError(
            f"Reviewer identity mismatch: supplied '{body.reviewer.strip()}' does not match principal '{trusted_reviewer}'."
        )

    if not body.reason or len(body.reason.strip()) < 5:
        raise ValueError("Justification reason of at least 5 characters is required for auditable approval.")

    stmt = select(Lead).options(selectinload(Lead.audit)).where(Lead.id.in_(lead_ids))
    result = await db.execute(stmt)
    leads = result.scalars().all()
    leads_by_id = {lead.id: lead for lead in leads}

    approved_leads = []
    skipped_leads = []
    errors = []

    for lid in lead_ids:
        lead = leads_by_id.get(lid)
        if not lead:
            skipped_leads.append(str(lid))
            errors.append(f"Lead {lid} not found.")
            continue

        if not is_valid_email_syntax(lead.email):
            skipped_leads.append(str(lid))
            errors.append(f"Lead {lead.business_name} ({lead.email}): invalid email syntax.")
            continue

        if lead.is_quarantined:
            q_reason = (lead.quarantine_reason or "").lower()
            is_assoc_quarantine = any(
                term in q_reason for term in (
                    "association", "external_domain", "mismatched", "free mail", "free-mail", "unverified domain"
                )
            )
            if not is_assoc_quarantine:
                skipped_leads.append(str(lid))
                errors.append(
                    f"Lead {lead.business_name} quarantined under non-association policy ({lead.quarantine_reason}); cannot approve."
                )
                continue

        lead.email_business_association_status = "approved"
        lead.email_association_reason = (
            f"Approved by {trusted_reviewer} ({body.policy_reference or 'bulk_evidence_review'}): {body.reason.strip()}"
        )

        if lead.is_quarantined:
            if lead.email_verification_status == "valid":
                lead.is_quarantined = False
                lead.quarantine_reason = None

        if not lead.email_source_url and lead.email_candidates:
            for cand in lead.email_candidates:
                if isinstance(cand, dict) and cand.get("email") == lead.email:
                    if cand.get("source_url"):
                        lead.email_source_url = cand.get("source_url")
                    if cand.get("source_type"):
                        lead.email_source_type = cand.get("source_type")
                    break

        log = ActivityLog(
            event_type="no_website_association_approved",
            lead_id=lead.id,
            message=(
                f"No-website association approved (bulk) for {lead.business_name} ({lead.email}) "
                f"by {trusted_reviewer} under policy '{body.policy_reference}': {body.reason.strip()}"
            ),
        )
        db.add(log)
        approved_leads.append(str(lead.id))

    await db.commit()

    return {
        "success": True,
        "approved_count": len(approved_leads),
        "skipped_count": len(skipped_leads),
        "approved_ids": approved_leads,
        "skipped_ids": skipped_leads,
        "errors": errors,
    }


async def bulk_reject_no_website_leads(
    lead_ids: List[uuid.UUID],
    reason: str,
    operator: dict,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Bulk reject email business association for a list of no-website leads.
    Sets status to 'mismatched_source', quarantines leads, logs ActivityLogs.
    """
    trusted_reviewer = (operator.get("sub") or "").strip()
    if not trusted_reviewer:
        raise PermissionError("Authenticated operator identity missing.")

    if not reason or len(reason.strip()) < 3:
        raise ValueError("Rejection reason of at least 3 characters is required.")

    stmt = select(Lead).options(selectinload(Lead.audit)).where(Lead.id.in_(lead_ids))
    result = await db.execute(stmt)
    leads = result.scalars().all()
    leads_by_id = {lead.id: lead for lead in leads}

    rejected_leads = []
    skipped_leads = []
    errors = []

    for lid in lead_ids:
        lead = leads_by_id.get(lid)
        if not lead:
            skipped_leads.append(str(lid))
            errors.append(f"Lead {lid} not found.")
            continue

        lead.email_business_association_status = "mismatched_source"
        lead.email_association_reason = f"Rejected (bulk) by {trusted_reviewer}: {reason.strip()}"
        lead.is_quarantined = True
        lead.quarantine_reason = f"Association rejected (bulk) by operator {trusted_reviewer}: {reason.strip()}"

        log = ActivityLog(
            event_type="no_website_association_rejected",
            lead_id=lead.id,
            message=(
                f"No-website association rejected (bulk) for {lead.business_name} ({lead.email}) "
                f"by {trusted_reviewer}: {reason.strip()}"
            ),
        )
        db.add(log)
        rejected_leads.append(str(lead.id))

    await db.commit()

    return {
        "success": True,
        "rejected_count": len(rejected_leads),
        "skipped_count": len(skipped_leads),
        "rejected_ids": rejected_leads,
        "skipped_ids": skipped_leads,
        "errors": errors,
    }


async def get_inconclusive_investigation_summary(db: AsyncSession) -> Dict[str, Any]:
    """
    Read-only investigation of the 121 website-less records classified as audit-inconclusive.
    Explains the exact classification rules and evidence requirements.
    """
    stmt = select(Lead).where(
        (Lead.website == "") | (Lead.website.is_(None)),
        Lead.website_association_status == "unverified_search",
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    samples = []
    for r in records[:10]:
        candidates = r.website_candidates or []
        sample_cand = [
            {"domain": c.get("domain"), "title": c.get("title"), "url": c.get("url")}
            for c in candidates[:3] if isinstance(c, dict)
        ]
        samples.append({
            "id": str(r.id),
            "business_name": r.business_name,
            "email": r.email,
            "website_association_status": r.website_association_status,
            "candidates_count": len(candidates),
            "sample_candidates": sample_cand,
        })

    return {
        "total_inconclusive_records": len(records),
        "status": "unverified_search",
        "classification": WebsiteClassification.AUDIT_INCONCLUSIVE.value,
        "summary": (
            "121 website-less leads were discovered with search snippet candidates from 3rd-party "
            "directories (Tofler, ZaubaCorp, ExportersIndia, Go4WorldBusiness, PDF directories, etc.) "
            "or ambiguous candidate domains. Because these candidates have not been authoritatively "
            "verified or ruled out, they are properly classified as AUDIT_INCONCLUSIVE. "
            "They are strictly separated from confirmed no-website businesses and cannot enter "
            "the 'no_website_design' campaign segment until an authoritative verification confirms no website exists."
        ),
        "policy": (
            "Never treat unverified_search as confirmed no_website. Requires authoritative operator "
            "resolution or definitive website verification before inclusion in no-website outreach."
        ),
        "samples": samples,
    }
