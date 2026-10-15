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
from app.models import Audit, Lead
from app.services.proposal_service import (
    ProposalService,
    HumanApprovalRequiredError,
    ProposalWorkflowError,
)

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ProposalEditRequest(BaseModel):
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    observations: Optional[List[Dict[str, Any]]] = None


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

    lead = await db.get(Lead, lead_uuid)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead record not found.")

    site_summary = audit.site_summary or {}
    url_info = site_summary.get("url_info", {})

    proposal = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit.audit_results or {},
        url_info=url_info,
    )
    return proposal


@router.put("/{lead_id}", summary="Edit proposal draft")
async def edit_proposal(
    lead_id: str,
    payload: ProposalEditRequest,
):
    try:
        updated = ProposalService.edit_proposal(
            lead_id=lead_id,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
            observations=payload.observations,
        )
        return updated
    except ProposalWorkflowError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{lead_id}/approve", summary="Record human approval for proposal")
async def approve_proposal(
    lead_id: str,
    payload: ProposalApproveRequest,
):
    try:
        approved = ProposalService.approve_proposal(
            lead_id=lead_id,
            user_email=payload.user_email,
        )
        return approved
    except ProposalWorkflowError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{lead_id}/send", summary="Dispatch proposal (strictly blocked without approval)")
async def send_proposal(
    lead_id: str,
    payload: ProposalSendRequest,
):
    try:
        res = ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email=payload.target_email,
            dry_run=payload.dry_run,
        )
        return res
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
        raise HTTPException(status_code=404, detail=str(e))
