"""
backend/app/services/proposal_service.py

Service Proposal Management & Approval Workflow.
Implements Phase 5 & Phase 10 of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Translates stored audit findings into personalized service proposals.
- Supports proposal preview, custom human editing, and explicit approval.
- Enforces strict human approval gate: sending is categorically prohibited until approved.
- Records contributing factor IDs for claim provenance and auditability.
- Persists proposal drafts and approval decisions durably to the service_proposals table (v6.2.5).
- Enforces cryptographic content integrity, lead provenance, and approval invalidation on edit.
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_email_service import AuditEmailService, AuditEmailGenerationError
from app.models import ServiceProposal


class ProposalWorkflowError(Exception):
    """Raised when a proposal workflow rule is violated."""
    pass


class HumanApprovalRequiredError(ProposalWorkflowError):
    """Raised when attempting to dispatch a proposal that has not received explicit human approval."""
    pass


class ProposalService:
    """Manages proposal generation, editing, approval gates, and delivery safeguards."""

    # In-memory proposal mirror cache (keyed by lead_id) for fast lookups and sync compatibility.
    # Note: In-memory cache is non-authoritative; the database service_proposals table is the single source of truth.
    _proposals: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def compute_content_hash(cls, proposal_data: Dict[str, Any]) -> str:
        """
        Computes a deterministic cryptographic SHA-256 fingerprint of the reviewed proposal draft.
        Used to prevent silent approval races and detect post-approval tampering.
        """
        lead_id = str(proposal_data.get("lead_id") or "")
        subject = str(proposal_data.get("subject") or "").strip()
        body_text = str(proposal_data.get("body_text") or "").strip()
        body_html = str(proposal_data.get("body_html") or "").strip()
        audit_fp = str((proposal_data.get("audit_reference") or {}).get("fingerprint") or "")
        obs_raw = proposal_data.get("observations") or []
        obs_json = json.dumps(obs_raw, sort_keys=True, default=str)
        canonical = f"{lead_id}|{subject}|{body_text}|{body_html}|{audit_fp}|{obs_json}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _row_to_dict(cls, row: ServiceProposal) -> Dict[str, Any]:
        """Convert a database ServiceProposal row into a standard API response dictionary."""
        content = dict(row.proposal_content or {})
        content["id"] = str(row.id)
        content["lead_id"] = str(row.lead_id)
        content["status"] = row.status
        content["approved"] = (row.status == "approved_for_delivery" and bool(row.approved_by))
        content["approved_by"] = row.approved_by
        content["approved_at"] = row.approved_at.isoformat() if row.approved_at else None
        content["approval_hash"] = row.approval_hash
        content["target_email"] = row.target_email
        if row.updated_at:
            content["updated_at"] = row.updated_at.isoformat()
        if row.created_at:
            content["created_at"] = row.created_at.isoformat()
        return content

    @classmethod
    async def aload_proposal(
        cls,
        lead_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Asynchronously loads a persisted proposal from the database if available,
        re-hydrating the process-local cache.
        """
        lead_key = str(lead_id)
        if db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                stmt = select(ServiceProposal).where(ServiceProposal.lead_id == lead_uuid).order_by(ServiceProposal.updated_at.desc())
                res = await db.execute(stmt)
                row = res.scalars().first()
                if row and isinstance(row, ServiceProposal):
                    prop_dict = cls._row_to_dict(row)
                    cls._proposals[lead_key] = prop_dict
                    return prop_dict
            except Exception:
                pass
        return cls._proposals.get(lead_key)

    @classmethod
    def get_or_create_proposal(
        cls,
        lead_id: str,
        business_name: str,
        website_url: str,
        audit_results: Dict[str, Any],
        url_info: Optional[Dict[str, Any]] = None,
        audit_id: Optional[str] = None,
        audit_updated_at: Optional[Any] = None,
        sender_agency: str = "TEB Solutions",
        contact_email: str = "info@tebsolutions.in",
        association_status: Optional[str] = None,
        ai_observations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous draft retrieval / generation (used by unit tests and sync callers).
        """
        lead_key = str(lead_id)
        current_fingerprint = AuditEmailService._fingerprint(audit_results) if isinstance(audit_results, dict) else None
        if lead_key in cls._proposals:
            existing = cls._proposals[lead_key]
            if association_status is not None:
                existing["email_business_association_status"] = association_status
            if not existing.get("edited"):
                if "contact@tebsolutions.in" in existing.get("body_html", ""):
                    existing["body_html"] = existing["body_html"].replace("contact@tebsolutions.in", contact_email)
                    existing["body_text"] = existing["body_text"].replace("contact@tebsolutions.in", contact_email)
            if existing.get("edited") or existing.get("audit_reference", {}).get("fingerprint") == current_fingerprint:
                return existing

        if ai_observations is None:
            try:
                from app.services.ai_search_service import AiSearchMonitoringService
                ai_srv = AiSearchMonitoringService()
                obs_res = ai_srv.get_observations(domain=website_url, limit=50)
                ai_observations = obs_res.get("observations", [])
            except Exception:
                ai_observations = []

        try:
            draft = AuditEmailService.generate_from_values(
                business_name=business_name,
                website_url=website_url,
                audit_results=audit_results,
                site_summary=(url_info or {}).get("site_summary"),
                audit_id=audit_id,
                audit_updated_at=audit_updated_at,
                sender_account={"sender_name": sender_agency, "email": contact_email},
                ai_observations=ai_observations,
                allow_clean_baseline=True,
                lead_id=lead_key,
            )
        except AuditEmailGenerationError as exc:
            if association_status and association_status not in ("matched", "approved"):
                draft = {
                    "business_name": business_name,
                    "website_url": website_url,
                    "subject": "Audit evidence review required",
                    "observations": [],
                    "opportunities_count": 0,
                    "selected_opportunities_count": 0,
                    "contributing_factor_ids": [],
                    "body_html": "<p>Audit evidence is unavailable. This draft cannot be delivered.</p>",
                    "body_text": "Audit evidence is unavailable. This draft cannot be delivered.",
                    "requires_human_approval": True,
                    "status": "blocked_missing_evidence",
                    "sent": False,
                    "audit_reference": {},
                    "content_blocked_reason": str(exc),
                }
            else:
                raise ProposalWorkflowError(str(exc)) from exc

        proposal_record = {
            "id": str(uuid.uuid4()),
            "lead_id": lead_key,
            **draft,
            "approved": False,
            "approved_by": None,
            "approved_at": None,
            "approval_hash": None,
            "edited": False,
            "sent_at": None,
            "email_business_association_status": association_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        cls._proposals[lead_key] = proposal_record
        return proposal_record

    @classmethod
    async def aget_or_create_proposal(
        cls,
        lead_id: str,
        business_name: str,
        website_url: str,
        audit_results: Dict[str, Any],
        url_info: Optional[Dict[str, Any]] = None,
        audit_id: Optional[str] = None,
        audit_updated_at: Optional[Any] = None,
        sender_agency: str = "TEB Solutions",
        contact_email: str = "info@tebsolutions.in",
        association_status: Optional[str] = None,
        ai_observations: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously gets an existing proposal from database or generates a new one,
        persisting it durably to the service_proposals table.
        """
        lead_key = str(lead_id)
        current_fingerprint = AuditEmailService._fingerprint(audit_results) if isinstance(audit_results, dict) else None

        # 1. Query persistent storage first
        if db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                stmt = select(ServiceProposal).where(ServiceProposal.lead_id == lead_uuid).order_by(ServiceProposal.updated_at.desc())
                res = await db.execute(stmt)
                row = res.scalars().first()
                if row and isinstance(row, ServiceProposal):
                    existing = cls._row_to_dict(row)
                    if association_status is not None:
                        existing["email_business_association_status"] = association_status
                    if not existing.get("edited"):
                        if "contact@tebsolutions.in" in existing.get("body_html", ""):
                            existing["body_html"] = existing["body_html"].replace("contact@tebsolutions.in", contact_email)
                            existing["body_text"] = existing["body_text"].replace("contact@tebsolutions.in", contact_email)
                    if existing.get("edited") or existing.get("audit_reference", {}).get("fingerprint") == current_fingerprint:
                        cls._proposals[lead_key] = existing
                        return existing
            except Exception:
                pass

        # 2. Check mirror cache if DB unapplied or empty
        if lead_key in cls._proposals:
            existing = cls._proposals[lead_key]
            if association_status is not None:
                existing["email_business_association_status"] = association_status
            if not existing.get("edited"):
                if "contact@tebsolutions.in" in existing.get("body_html", ""):
                    existing["body_html"] = existing["body_html"].replace("contact@tebsolutions.in", contact_email)
                    existing["body_text"] = existing["body_text"].replace("contact@tebsolutions.in", contact_email)
            if existing.get("edited") or existing.get("audit_reference", {}).get("fingerprint") == current_fingerprint:
                return existing

        # 3. Generate draft
        sync_result = cls.get_or_create_proposal(
            lead_id=lead_id,
            business_name=business_name,
            website_url=website_url,
            audit_results=audit_results,
            url_info=url_info,
            audit_id=audit_id,
            audit_updated_at=audit_updated_at,
            sender_agency=sender_agency,
            contact_email=contact_email,
            association_status=association_status,
            ai_observations=ai_observations,
        )

        # 4. Persist to database if db session provided
        if db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                audit_uuid = uuid.UUID(str(audit_id)) if audit_id else None
                sp_row = ServiceProposal(
                    id=uuid.UUID(sync_result["id"]),
                    lead_id=lead_uuid,
                    audit_id=audit_uuid,
                    status=sync_result.get("status", "draft_preview"),
                    approved_by=None,
                    approved_at=None,
                    target_email=None,
                    approval_hash=None,
                    proposal_content=sync_result,
                )
                db.add(sp_row)
                await db.commit()
            except Exception:
                pass

        return sync_result

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
        Synchronously edit a proposal draft. Any edit categorically invalidates prior approvals.
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
        # Any edit resets prior approval and clears cryptographic approval hash
        prop["approved"] = False
        prop["approved_by"] = None
        prop["approved_at"] = None
        prop["approval_hash"] = None
        prop["status"] = "draft_preview"
        prop["requires_human_approval"] = True
        prop["updated_at"] = datetime.now(timezone.utc).isoformat()

        return prop

    @classmethod
    async def aedit_proposal(
        cls,
        lead_id: str,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        observations: Optional[List[Dict[str, Any]]] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously edit a proposal draft and persist changes to the database.
        Strictly invalidates prior approval in both relational storage and memory cache.
        """
        lead_key = str(lead_id)

        # Hydrate from DB if missing in memory
        if lead_key not in cls._proposals and db is not None:
            await cls.aload_proposal(lead_key, db=db)

        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        updated = cls.edit_proposal(
            lead_id=lead_id,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            observations=observations,
        )

        if db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                stmt = select(ServiceProposal).where(ServiceProposal.lead_id == lead_uuid).order_by(ServiceProposal.updated_at.desc())
                res = await db.execute(stmt)
                row = res.scalars().first()
                if row and isinstance(row, ServiceProposal):
                    row.status = "draft_preview"
                    row.approved_by = None
                    row.approved_at = None
                    row.approval_hash = None
                    row.proposal_content = updated
                    row.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                pass

        return updated

    @classmethod
    def approve_proposal(
        cls,
        lead_id: str,
        user_email: str,
        expected_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synchronously record explicit human approval for a proposal draft.
        Enforces content integrity via SHA-256 fingerprinting.
        """
        lead_key = str(lead_id)
        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        prop = cls._proposals[lead_key]

        # Verify lead provenance
        if str(prop.get("lead_id")) != lead_key:
            raise ProposalWorkflowError("Proposal lead provenance mismatch.")

        # Compute content integrity hash
        content_hash = cls.compute_content_hash(prop)
        if expected_hash is not None and expected_hash != content_hash:
            raise ProposalWorkflowError(
                "Concurrent modification detected: proposal content has changed since the operator reviewed it."
            )

        prop["approved"] = True
        prop["approved_by"] = user_email
        prop["approved_at"] = datetime.now(timezone.utc).isoformat()
        prop["approval_hash"] = content_hash
        prop["requires_human_approval"] = False
        prop["status"] = "approved_for_delivery"
        prop["updated_at"] = datetime.now(timezone.utc).isoformat()

        return prop

    @classmethod
    async def aapprove_proposal(
        cls,
        lead_id: str,
        user_email: str,
        expected_hash: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously record explicit human approval and commit to persistent database storage.
        """
        lead_key = str(lead_id)

        # Hydrate from DB if missing in memory
        if lead_key not in cls._proposals and db is not None:
            await cls.aload_proposal(lead_key, db=db)

        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        approved = cls.approve_proposal(
            lead_id=lead_id,
            user_email=user_email,
            expected_hash=expected_hash,
        )

        if db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                stmt = select(ServiceProposal).where(ServiceProposal.lead_id == lead_uuid).order_by(ServiceProposal.updated_at.desc())
                res = await db.execute(stmt)
                row = res.scalars().first()
                if row and isinstance(row, ServiceProposal):
                    row.status = "approved_for_delivery"
                    row.approved_by = user_email
                    row.approved_at = datetime.now(timezone.utc)
                    row.approval_hash = approved["approval_hash"]
                    row.proposal_content = approved
                    row.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                pass

        return approved

    @classmethod
    def dispatch_proposal(
        cls,
        lead_id: str,
        target_email: str,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        Synchronously attempt to dispatch a proposal.
        Strictly enforces approval presence and association status.
        """
        lead_key = str(lead_id)
        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        prop = cls._proposals[lead_key]

        # STRICT PROVENANCE GATE
        if str(prop.get("lead_id")) != lead_key:
            raise ProposalWorkflowError("Proposal lead provenance mismatch.")

        # STRICT HUMAN APPROVAL GATE
        if not prop.get("approved"):
            raise HumanApprovalRequiredError(
                f"Proposal for lead {lead_id} requires explicit human approval before sending."
            )

        # STRICT ASSOCIATION GATE
        assoc = prop.get("email_business_association_status")
        if assoc and assoc not in ("matched", "approved"):
            raise ProposalWorkflowError(
                f"Proposal delivery blocked: Lead business association status is '{assoc}'. Proposals require a matched or approved business association."
            )

        # CONTENT INTEGRITY CHECK
        current_hash = cls.compute_content_hash(prop)
        stored_hash = prop.get("approval_hash")
        if stored_hash and stored_hash != current_hash:
            prop["approved"] = False
            prop["approval_hash"] = None
            prop["status"] = "draft_preview"
            raise HumanApprovalRequiredError(
                "Proposal approval invalidated: content was modified after operator approval."
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

        raise ProposalWorkflowError(
            "Direct proposal delivery is disabled. Use the approved campaign workflow for any live outreach."
        )

    @classmethod
    async def adispatch_proposal(
        cls,
        lead_id: str,
        target_email: str,
        dry_run: bool = True,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously dispatch/simulate proposal send, persisting state to database.
        """
        lead_key = str(lead_id)

        # Hydrate from DB if missing in memory
        if lead_key not in cls._proposals and db is not None:
            await cls.aload_proposal(lead_key, db=db)

        if lead_key not in cls._proposals:
            raise ProposalWorkflowError(f"Proposal for lead {lead_id} does not exist.")

        res = cls.dispatch_proposal(
            lead_id=lead_id,
            target_email=target_email,
            dry_run=dry_run,
        )

        if dry_run and db is not None:
            try:
                lead_uuid = uuid.UUID(lead_key)
                stmt = select(ServiceProposal).where(ServiceProposal.lead_id == lead_uuid).order_by(ServiceProposal.updated_at.desc())
                db_res = await db.execute(stmt)
                row = db_res.scalars().first()
                if row and isinstance(row, ServiceProposal):
                    row.target_email = target_email
                    row.status = "simulated_send_dry_run"
                    row.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                pass

        return res

    @classmethod
    def has_approved_proposal(cls, lead_id: str) -> bool:
        """
        Check whether an authoritative approved proposal draft exists for this lead in cache.
        """
        prop = cls._proposals.get(str(lead_id))
        return bool(prop and prop.get("approved") is True and prop.get("status") in ("approved", "approved_for_delivery"))

    @classmethod
    async def ahas_approved_proposal(cls, lead_id: str, db: Optional[AsyncSession] = None) -> bool:
        """
        Check whether an authoritative approved proposal exists in database or cache.
        """
        prop = await cls.aload_proposal(lead_id, db=db)
        return bool(prop and prop.get("approved") is True and prop.get("status") in ("approved", "approved_for_delivery"))

    @classmethod
    def get_proposal_approval_state(cls, lead_id: str) -> Dict[str, Any]:
        """
        Retrieve structured approval provenance and evidence fingerprint for a proposal draft.
        """
        prop = cls._proposals.get(str(lead_id))
        if not prop:
            return {
                "exists": False,
                "approved": False,
                "status": "missing",
                "approved_by": None,
                "approved_at": None,
                "approval_hash": None,
                "edited": False,
                "audit_reference": None,
            }
        return {
            "exists": True,
            "lead_id": str(lead_id),
            "status": prop.get("status"),
            "approved": bool(prop.get("approved")),
            "approved_by": prop.get("approved_by"),
            "approved_at": prop.get("approved_at"),
            "approval_hash": prop.get("approval_hash"),
            "edited": bool(prop.get("edited")),
            "audit_reference": prop.get("audit_reference"),
        }

    @classmethod
    async def aget_proposal_approval_state(
        cls,
        lead_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously retrieve structured approval provenance, querying database if needed.
        """
        prop = await cls.aload_proposal(lead_id, db=db)
        if not prop:
            return {
                "exists": False,
                "approved": False,
                "approved_by": None,
                "approved_at": None,
                "approval_hash": None,
                "edited": False,
                "audit_reference": None,
            }
        return {
            "exists": True,
            "lead_id": str(lead_id),
            "approved": bool(prop.get("approved")),
            "approved_by": prop.get("approved_by"),
            "approved_at": prop.get("approved_at"),
            "approval_hash": prop.get("approval_hash"),
            "edited": bool(prop.get("edited")),
            "audit_reference": prop.get("audit_reference"),
        }
