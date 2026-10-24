"""
backend/app/routers/proposals.py

FastAPI router for Service Proposal management and human approval gates.
"""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.config import settings
from app.models import Audit, Lead
from app.services.proposal_service import (
    ProposalService,
    HumanApprovalRequiredError,
    ProposalWorkflowError,
)
from app.routers.auth import require_authorized_operator
from app.services.campaign_eligibility_service import evaluate_lead_campaign_eligibility
from pydantic import field_validator, model_validator

router = APIRouter(
    prefix="/proposals",
    tags=["proposals"],
    dependencies=[Depends(require_authorized_operator)],
)


class ProposalEditRequest(BaseModel):
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    observations: Optional[List[Dict[str, Any]]] = None

    @field_validator("subject", "body_text", "body_html")
    @classmethod
    def validate_non_empty_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Text fields cannot be empty or whitespace only")
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> "ProposalEditRequest":
        if (
            self.subject is None
            and self.body_text is None
            and self.body_html is None
            and self.observations is None
        ):
            raise ValueError("At least one editable field must be provided in the update payload")
        return self


class ProposalApproveRequest(BaseModel):
    user_email: str = "operator@tebsolutions.in"


class ProposalSendRequest(BaseModel):
    target_email: str
    dry_run: bool = True


@router.get("/{lead_id}", summary="Get or generate proposal draft for a lead")
async def get_proposal(lead_id: str, db: AsyncSession = Depends(get_db)):
    try:
        lead_uuid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")

    result = await db.execute(select(Audit).where(Audit.lead_id == lead_uuid))
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found for this lead.")
    if str(getattr(audit, "status", "")).lower() not in ("done", "auditstatus.done"):
        raise HTTPException(
            status_code=409,
            detail="Proposal generation requires a completed audit; incomplete, failed, or unavailable checks are not treated as findings.",
        )
    if not isinstance(getattr(audit, "audit_results", None), dict) or not audit.audit_results:
        raise HTTPException(status_code=409, detail="Proposal generation requires recorded audit findings.")

    lead = await db.get(Lead, lead_uuid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead record not found.")

    site_summary = audit.site_summary or {}
    url_info = site_summary.get("url_info", {})

    smtp_accounts = settings.get_smtp_accounts()
    contact_email = smtp_accounts[0]["email"] if smtp_accounts else "info@tebsolutions.in"

    proposal = await ProposalService.aget_or_create_proposal(
        lead_id=lead_id,
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit.audit_results or {},
        url_info={**url_info, "lead_id": lead_id, "site_summary": audit.site_summary or {}},
        audit_id=str(audit.id),
        audit_updated_at=audit.updated_at,
        contact_email=contact_email,
        association_status=getattr(lead, "email_business_association_status", "unverified_association"),
        db=db,
    )
    return proposal


@router.put("/{lead_id}", summary="Edit proposal draft")
async def edit_proposal(
    lead_id: str,
    payload: ProposalEditRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")
    try:
        updated = await ProposalService.aedit_proposal(
            lead_id=lead_id,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            observations=payload.observations,
            db=db,
        )
        return updated
    except ProposalWorkflowError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{lead_id}/approve", summary="Record human approval for proposal")
async def approve_proposal(
    lead_id: str,
    payload: ProposalApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_authorized_operator),
):
    try:
        lead_uuid = uuid.UUID(lead_id)
        lead = await db.get(Lead, lead_uuid)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead record not found.")
        audit_result = await db.execute(select(Audit).where(Audit.lead_id == lead_uuid))
        audit = audit_result.scalar_one_or_none()
        eligible, reason, _, _ = evaluate_lead_campaign_eligibility(
            lead, audit=audit, campaign_type="valid_website_seo"
        )
        if not eligible:
            raise HTTPException(
                status_code=403,
                detail=f"Proposal cannot be approved for delivery: {reason}",
            )
        approved = await ProposalService.aapprove_proposal(
            lead_id=lead_id,
            user_email=current_user["sub"],
            db=db,
        )
        return approved
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")
    except ProposalWorkflowError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{lead_id}/send", summary="Dispatch proposal (strictly blocked without approval)")
async def send_proposal(
    lead_id: str,
    payload: ProposalSendRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        lead_uuid = uuid.UUID(lead_id)
        lead = await db.get(Lead, lead_uuid)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead record not found.")
        if payload.target_email and lead.email:
            if payload.target_email.strip().lower() != lead.email.strip().lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"Target email '{payload.target_email}' does not match lead record email '{lead.email}'",
                )
        audit_result = await db.execute(select(Audit).where(Audit.lead_id == lead_uuid))
        audit = audit_result.scalar_one_or_none()
        eligible, reason, _, _ = evaluate_lead_campaign_eligibility(
            lead, audit=audit, campaign_type="valid_website_seo"
        )
        if not eligible:
            raise HTTPException(status_code=403, detail=f"Proposal delivery is blocked: {reason}")
        res = await ProposalService.adispatch_proposal(
            lead_id=lead_id,
            target_email=payload.target_email,
            dry_run=payload.dry_run,
            db=db,
        )
        return res
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead UUID format")
    except HumanApprovalRequiredError as e:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "approval_required",
                "message": str(e),
                "action": "Proposal must be reviewed and approved via POST /proposals/{lead_id}/approve prior to delivery.",
            },
        )
    except ProposalWorkflowError as e:
        if "association" in str(e).lower():
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "association_unverified",
                    "message": str(e),
                },
            )
        if "direct proposal delivery is disabled" in str(e).lower():
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "direct_send_forbidden",
                    "message": str(e),
                },
            )
        raise HTTPException(status_code=404, detail=str(e))
