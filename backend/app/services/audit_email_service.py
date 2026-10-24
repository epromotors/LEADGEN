"""Canonical, evidence-backed audit outreach message generation.

The proposal shown in Audits and the default content for audit-dependent
Campaigns must be generated here.  This module deliberately delegates
opportunity selection to :class:`OpportunityEngine`; it never synthesizes
findings from legacy columns or from missing/failed audit checks.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.engines.opportunity_engine import OpportunityEngine
from app.models import Audit, Lead


class AuditEmailGenerationError(ValueError):
    """Raised when a defensible audit-personalized message cannot be produced."""


class AuditEmailService:
    """Single source of truth for audit evidence, copy, and audit freshness."""

    RENDERER_VERSION = "audit-outreach-v1"
    NON_AUDIT_CAMPAIGN_TYPES = {
        "generic_first_contact",
        "no_website_design",
        "public_provider_demo",
    }

    @classmethod
    def is_audit_dependent(cls, campaign_type: Optional[str]) -> bool:
        return str(campaign_type or "generic_first_contact").lower() not in cls.NON_AUDIT_CAMPAIGN_TYPES

    @staticmethod
    def _fingerprint(audit_results: Dict[str, Any]) -> str:
        payload = json.dumps(audit_results, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def generate(
        cls,
        lead: Lead,
        audit: Optional[Audit],
        campaign_type: Optional[str] = None,
        sender_account: Optional[Dict[str, Any]] = None,
        ai_observations: Optional[List[Dict[str, Any]]] = None,
        allow_clean_baseline: bool = False,
    ) -> Dict[str, Any]:
        """Generate the exact audited message for a persisted lead and audit."""
        if audit is None:
            raise AuditEmailGenerationError("A completed audit is required for audit-personalized outreach.")

        status = str(getattr(audit, "status", "")).lower()
        if status not in ("done", "auditstatus.done"):
            raise AuditEmailGenerationError("The selected audit is incomplete, failed, or stale; regenerate after a completed audit.")

        return cls.generate_from_values(
            business_name=getattr(lead, "business_name", "") or "there",
            website_url=(getattr(audit, "audited_url", None) or getattr(lead, "website", "") or "").strip(),
            audit_results=getattr(audit, "audit_results", None),
            site_summary=getattr(audit, "site_summary", None),
            audit_id=getattr(audit, "id", None),
            audit_updated_at=getattr(audit, "updated_at", None),
            campaign_type=campaign_type,
            sender_account=sender_account,
            ai_observations=ai_observations,
            allow_clean_baseline=allow_clean_baseline,
            lead_id=str(getattr(lead, "id", "")) if getattr(lead, "id", None) else None,
        )

    @classmethod
    def generate_from_values(
        cls,
        *,
        business_name: str,
        website_url: str,
        audit_results: Optional[Dict[str, Any]],
        site_summary: Optional[Dict[str, Any]] = None,
        audit_id: Any = None,
        audit_updated_at: Any = None,
        campaign_type: Optional[str] = None,
        sender_account: Optional[Dict[str, Any]] = None,
        ai_observations: Optional[List[Dict[str, Any]]] = None,
        allow_clean_baseline: bool = False,
        lead_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Value-based entry point used by ProposalService and deterministic tests."""
        if not isinstance(audit_results, dict) or not audit_results:
            raise AuditEmailGenerationError("Audit findings are unavailable; use generic first-contact outreach instead.")

        url_info: Dict[str, Any] = {"requested_url": website_url}
        if lead_id:
            url_info["lead_id"] = lead_id

        opportunities = OpportunityEngine.evaluate_opportunities(
            audit_results=audit_results,
            url_info=url_info,
            site_summary=site_summary,
            ai_observations=ai_observations,
        )
        if not opportunities and not allow_clean_baseline:
            raise AuditEmailGenerationError(
                "The completed audit has no suitable verified findings; use generic first-contact outreach instead."
            )

        sender_name = (sender_account or {}).get("sender_name") or "TEB Solutions"
        contact_email = (sender_account or {}).get("email") or "info@tebsolutions.in"
        draft = OpportunityEngine.generate_proposal_draft(
            business_name=business_name,
            website_url=website_url,
            opportunities=opportunities,
            sender_agency=sender_name,
            contact_email=contact_email,
        )
        updated_at = audit_updated_at.isoformat() if isinstance(audit_updated_at, datetime) else (
            str(audit_updated_at) if audit_updated_at else None
        )
        audit_reference = {
            "audit_id": str(audit_id) if audit_id else None,
            "fingerprint": cls._fingerprint(audit_results),
            "updated_at": updated_at,
            "renderer_version": cls.RENDERER_VERSION,
        }
        return {
            **draft,
            "lead_identity": business_name,
            "website": website_url,
            "campaign_type": campaign_type,
            "selected_findings": draft["observations"],
            "recommended_actions": [item["next_step"] for item in draft["observations"]],
            "service_classification": [item["service_name"] for item in draft["observations"]],
            "audit_reference": audit_reference,
            "renderer_version": cls.RENDERER_VERSION,
        }
