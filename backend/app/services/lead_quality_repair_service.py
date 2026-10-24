"""Bounded, evidence-preserving repair planning for existing and imported leads.

This module deliberately does *not* decide that a site or mailbox is verified.
It prepares evidence-backed candidate changes, preserves the original contact, and
keeps the existing association, verification, quarantine, and campaign gates as
the authorities for sendability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.models import EmailAssociationStatus, WebsiteAssociationStatus
from app.services.lead_discovery_service import (
    extract_domain_from_url,
    reconcile_duplicate_business_records,
)
from app.utils.email_constants import (
    infer_website_candidate_from_email,
    is_directory_or_platform_email,
    is_public_email_provider,
    is_third_party_directory_or_aggregator,
    normalize_domain,
)


SUSPECT_PLACEHOLDER_LOCAL_PARTS = frozenset({
    "demo", "test", "testing", "sample", "example", "fake", "dummy",
    "placeholder", "yourname", "your-email", "email",
})


@dataclass
class RepairPlan:
    """A redaction-friendly plan for one lead; it contains no mailbox address."""

    lead_id: str
    issue_types: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    recommended_action: str = "keep_for_review"
    candidate_count: int = 0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_id": self.lead_id,
            "issue_types": self.issue_types,
            "operations": self.operations,
            "recommended_action": self.recommended_action,
            "candidate_count": self.candidate_count,
            "evidence": self.evidence,
        }


def is_suspect_placeholder_email(email: str | None) -> bool:
    """Flag only explicit placeholder patterns; unusual addresses stay untouched."""
    if not email or "@" not in email:
        return False
    local = email.split("@", 1)[0].strip().lower()
    compact = local.replace("_", "-").replace(".", "-")
    return local in SUSPECT_PLACEHOLDER_LOCAL_PARTS or any(
        token in compact.split("-") for token in SUSPECT_PLACEHOLDER_LOCAL_PARTS
    )


def _append_candidate(existing: list[dict[str, Any]] | None, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Append unique evidence without overwriting prior provenance."""
    candidates = list(existing or [])
    url = candidate.get("url")
    source = candidate.get("source")
    if not any(item.get("url") == url and item.get("source") == source for item in candidates if isinstance(item, dict)):
        candidates.append(candidate)
    return candidates


class LeadQualityRepairService:
    """Shared repair rules for CSV intake, scraped leads, and legacy records."""

    def plan_for_lead(self, lead: Any) -> RepairPlan:
        email = (getattr(lead, "email", "") or "").strip().lower()
        website = (getattr(lead, "website", "") or "").strip()
        email_domain = normalize_domain(email.rsplit("@", 1)[-1]) if "@" in email else ""
        website_domain = extract_domain_from_url(website)
        plan = RepairPlan(lead_id=str(getattr(lead, "id", "")))

        if website and is_third_party_directory_or_aggregator(website):
            plan.issue_types.append("directory_website")
            plan.operations.append("demote_directory_url_to_provenance")
            plan.evidence.append("recorded_website_is_third_party_directory")

        if email and is_directory_or_platform_email(email):
            plan.issue_types.append("directory_email")
            plan.operations.append("retain_directory_email_in_quarantine")
            plan.evidence.append("email_domain_is_directory_platform")

        if email_domain and website_domain and email_domain != website_domain and not is_public_email_provider(email_domain):
            plan.issue_types.append("conflicting_website_email_domains")
            plan.operations.append("preserve_both_as_competing_evidence")
            plan.evidence.append("custom_email_domain_differs_from_recorded_website")

        if not website and email_domain and not is_public_email_provider(email_domain) and not is_directory_or_platform_email(email):
            plan.issue_types.append("missing_website_custom_email")
            plan.operations.append("add_unverified_email_domain_candidate")
            plan.evidence.append("custom_email_domain_available_as_safe_hint")

        if email_domain and is_public_email_provider(email_domain):
            plan.issue_types.append("public_provider_contact")
            plan.operations.append("independent_business_name_discovery")
            plan.evidence.append("public_provider_does_not_establish_business_identity")

        if is_suspect_placeholder_email(email):
            plan.issue_types.append("suspected_placeholder_email")
            plan.operations.append("bounded_contact_recovery")
            plan.evidence.append("explicit_placeholder_local_part")

        candidates = list(getattr(lead, "website_candidates", None) or [])
        if getattr(lead, "website_association_status", None) in (
            WebsiteAssociationStatus.CONFLICTING.value,
            WebsiteAssociationStatus.INCONCLUSIVE.value,
        ) or len({c.get("domain") for c in candidates if isinstance(c, dict) and c.get("domain")}) > 1:
            plan.issue_types.append("ambiguous_website_identity")
            plan.operations.append("retain_competing_candidates_for_review")
            plan.evidence.append("competing_or_inconclusive_website_candidates")

        no_result_after_bounded_discovery = any(
            isinstance(candidate, dict)
            and candidate.get("source") == "bounded_discovery"
            and candidate.get("status") == "no_results"
            for candidate in candidates
        )

        if not plan.issue_types:
            plan.recommended_action = "no_change"
        elif "suspected_placeholder_email" in plan.issue_types and no_result_after_bounded_discovery:
            plan.recommended_action = "recommend_deletion"
            plan.operations.append("retain_in_review_until_operator_keep_or_delete_decision")
        elif "suspected_placeholder_email" in plan.issue_types:
            plan.recommended_action = "retry_discovery"
        elif "ambiguous_website_identity" in plan.issue_types:
            plan.recommended_action = "keep_for_review"
        elif getattr(lead, "email_verification_status", "unverified") in ("timeout", "error", "unverified"):
            plan.recommended_action = "reverify"

        plan.candidate_count = len(candidates)
        return plan

    def dry_run_report(self, leads: Iterable[Any]) -> dict[str, Any]:
        plans = [self.plan_for_lead(lead) for lead in leads]
        issue_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}
        for plan in plans:
            action_counts[plan.recommended_action] = action_counts.get(plan.recommended_action, 0) + 1
            for issue in plan.issue_types:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        return {
            "mode": "dry_run",
            "inspected": len(plans),
            "issue_counts": issue_counts,
            "recommended_action_counts": action_counts,
            "plans": [plan.to_dict() for plan in plans],
        }

    def apply_static_rules(self, lead: Any, all_leads: Iterable[Any] = ()) -> list[str]:
        """Apply only deterministic provenance/candidate corrections.

        No address is replaced, no verified website is overwritten, and this never
        clears quarantine or changes association approval.
        """
        changes: list[str] = []
        website = (getattr(lead, "website", "") or "").strip()
        email = (getattr(lead, "email", "") or "").strip().lower()

        if website and is_third_party_directory_or_aggregator(website):
            if not getattr(lead, "email_source_url", None):
                lead.email_source_url = website
                lead.email_source_type = "directory_listing"
            lead.website = ""
            lead.website_domain = ""
            lead.website_association_status = WebsiteAssociationStatus.NO_WEBSITE.value
            changes.append("directory_website_demoted")

        if email and is_directory_or_platform_email(email):
            lead.is_quarantined = True
            lead.quarantine_reason = "Directory platform email requires independent business association review"
            lead.email_business_association_status = EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value
            lead.email_association_reason = "Directory platform mailbox requires independent business ownership evidence."
            changes.append("directory_email_quarantined")

        # Preserve a custom-domain hint as a candidate only.  It remains unverified
        # until independent discovery and the established operator workflow support it.
        if not getattr(lead, "website", ""):
            inferred = infer_website_candidate_from_email(email)
            if inferred:
                lead.website = inferred
                lead.website_domain = extract_domain_from_url(inferred)
                lead.website_association_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                lead.website_candidates = _append_candidate(
                    getattr(lead, "website_candidates", None),
                    {
                        "url": inferred,
                        "domain": lead.website_domain,
                        "source": "email_domain_inferred",
                        "status": WebsiteAssociationStatus.CANDIDATE_MATCH.value,
                        "reason": "Custom email domain hint; independently unverified",
                    },
                )
                lead.email_business_association_status = EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value
                lead.email_association_reason = "Website candidate inferred from business email domain; independent association review required."
                changes.append("email_domain_candidate_added")

        # Existing duplicate reconciliation has the stricter identity checks and only
        # contributes a candidate from an independently verified matching record.
        if not getattr(lead, "website", "") or getattr(lead, "website_association_status", "") != WebsiteAssociationStatus.VERIFIED_PRIMARY.value:
            if reconcile_duplicate_business_records(lead, list(all_leads)):
                changes.append("same_business_candidate_reused")

        if is_suspect_placeholder_email(email) and not (getattr(lead, "email_candidates", None) or []):
            lead.is_quarantined = True
            lead.quarantine_reason = "No verified business contact found; bounded discovery required before deletion review"
            changes.append("placeholder_contact_held_for_review")

        return changes

    def add_discovery_candidates(self, lead: Any, website_candidates: Iterable[dict[str, Any]], email_candidates: Iterable[dict[str, Any]]) -> list[str]:
        """Store discovery evidence without silently promoting a site or contact."""
        changes: list[str] = []
        for candidate in website_candidates:
            if not isinstance(candidate, dict):
                continue
            sanitized = dict(candidate)
            sanitized["status"] = sanitized.get("status") or WebsiteAssociationStatus.UNVERIFIED_SEARCH.value
            # A no-result/inconclusive outcome is provenance, not a candidate URL.
            # Keeping it makes a later deletion recommendation auditable while
            # preventing a retry timeout from masquerading as a confirmed negative.
            if not sanitized.get("url") and sanitized.get("status") not in ("no_results", "inconclusive"):
                continue
            lead.website_candidates = _append_candidate(getattr(lead, "website_candidates", None), sanitized)
            changes.append("website_candidate_discovered")

        for candidate in email_candidates:
            if not isinstance(candidate, dict) or not candidate.get("email"):
                continue
            candidates = list(getattr(lead, "email_candidates", None) or [])
            if not any(item.get("email") == candidate.get("email") and item.get("source_url") == candidate.get("source_url") for item in candidates if isinstance(item, dict)):
                candidates.append(dict(candidate))
                lead.email_candidates = candidates
                changes.append("email_candidate_discovered")

        # A discovered site remains a candidate. Never overwrite a verified primary.
        if not getattr(lead, "website", "") and getattr(lead, "website_candidates", None):
            top = next((c for c in lead.website_candidates if isinstance(c, dict) and c.get("url")), None)
            if top:
                lead.website = top["url"]
                lead.website_domain = extract_domain_from_url(top["url"])
                lead.website_association_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                changes.append("discovered_website_retained_as_candidate")
        return changes


lead_quality_repair_service = LeadQualityRepairService()
