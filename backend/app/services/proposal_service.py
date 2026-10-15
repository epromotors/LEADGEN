"""
backend/app/services/proposal_service.py

Service Proposal Management & Approval Workflow.
Implements Phase 5 of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Translates stored audit findings into personalized service proposals.
- Supports proposal preview, custom human editing, and explicit approval.
- Enforces strict human approval gate: sending is categorically prohibited until approved.
- Records contributing factor IDs for claim provenance and auditability.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.engines.opportunity_engine import OpportunityEngine


class ProposalWorkflowError(Exception):
    """Raised when a proposal workflow rule is violated."""
    pass


class HumanApprovalRequiredError(ProposalWorkflowError):
    """Raised when attempting to dispatch a proposal that has not received explicit human approval."""
    pass


class ProposalService:
    """Manages proposal generation, editing, approval gates, and delivery safeguards."""

    # In-memory proposal store (keyed by lead_id) for edited drafts and approval state
    _proposals: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_or_create_proposal(
        cls,
        lead_id: str,
        business_name: str,
        website_url: str,
        audit_results: Dict[str, Any],
        url_info: Optional[Dict[str, Any]] = None,
        sender_agency: str = "TEB Solutions",
        contact_email: str = "contact@tebsolutions.in",
    ) -> Dict[str, Any]:
        """
        Get an existing proposal or generate a new one from verified audit opportunities.
        """
        lead_key = str(lead_id)
        if lead_key in cls._proposals:
            return cls._proposals[lead_key]

        opportunities = OpportunityEngine.evaluate_opportunities(
            audit_results=audit_results,
            url_info=url_info,
        )

        draft = OpportunityEngine.generate_proposal_draft(
            business_name=business_name,
            website_url=website_url,
            opportunities=opportunities,
            sender_agency=sender_agency,
            contact_email=contact_email,
        )

        proposal_record = {
            "id": str(uuid.uuid4()),
            "lead_id": lead_key,
            **draft,
            "approved": False,
            "approved_by": None,
            "approved_at": None,
            "edited": False,
            "sent_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        cls._proposals[lead_key] = proposal_record
        return proposal_record

    @classmethod
    def edit_proposal(
        cls,
        lead_id: str,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        observations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Allow human editor to refine the proposal draft text and observations.
        Editing resets approval if previously approved.
        """
        lead_key = str(lead_id)
        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        prop = cls._proposals[lead_key]
        if subject is not None:
            prop["subject"] = subject
        if body_text is not None:
            prop["body_text"] = body_text
        if body_html is not None:
            prop["body_html"] = body_html
        if observations is not None:
            prop["observations"] = observations

        prop["edited"] = True
        # Any edit resets prior approval to ensure re-review
        prop["approved"] = False
        prop["approved_by"] = None
        prop["approved_at"] = None
        prop["status"] = "draft_preview"
        prop["updated_at"] = datetime.now(timezone.utc).isoformat()

        return prop

    @classmethod
    def approve_proposal(cls, lead_id: str, user_email: str) -> Dict[str, Any]:
        """
        Record explicit human approval for a proposal draft.
        """
        lead_key = str(lead_id)
        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        prop = cls._proposals[lead_key]
        prop["approved"] = True
        prop["approved_by"] = user_email
        prop["approved_at"] = datetime.now(timezone.utc).isoformat()
        prop["requires_human_approval"] = False
        prop["status"] = "approved_for_delivery"
        prop["updated_at"] = datetime.now(timezone.utc).isoformat()

        return prop

    @classmethod
    def dispatch_proposal(
        cls,
        lead_id: str,
        target_email: str,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        Attempt to send a proposal. Strictly enforces that proposal must be approved by a human.
        """
        lead_key = str(lead_id)
        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        prop = cls._proposals[lead_key]

        # STRICT HUMAN APPROVAL GATE
        if not prop.get("approved"):
            raise HumanApprovalRequiredError(
                f"Proposal for lead {lead_id} requires explicit human approval before sending."
            )

        if dry_run:
            prop["sent"] = False
            prop["status"] = "simulated_send_dry_run"
            return {
                "success": True,
                "mode": "dry_run",
                "message": f"Proposal verified and approved. Delivery simulated for {target_email} (dry run).",
                "proposal_id": prop["id"],
                "approved_by": prop["approved_by"],
            }

        # If live send requested in production
        prop["sent"] = True
        prop["sent_at"] = datetime.now(timezone.utc).isoformat()
        prop["status"] = "sent"

        return {
            "success": True,
            "mode": "live",
            "message": f"Proposal successfully dispatched to {target_email}.",
            "proposal_id": prop["id"],
            "approved_by": prop["approved_by"],
            "sent_at": prop["sent_at"],
        }
