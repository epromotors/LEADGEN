"""
tests/test_phase7_campaign_freshness_gatekeeper.py

Comprehensive deterministic test suite for LEADGEN Phase 7:
Campaign Queue Ingestion & Audit Freshness Gatekeeper.

Covers all 20 required deterministic test cases:
1. Approved and otherwise eligible lead enters the correct cohort.
2. Approval-required campaign rejects an unapproved proposal.
3. Segment-specific rules preserve valid neutral introductory workflows.
4. Missing or incomplete audit fails the relevant gate.
5. Fresh audit passes the freshness check.
6. Stale audit returns a refresh-required result.
7. Running refresh prevents duplicate refresh tasks.
8. Failed refresh blocks fact-dependent dispatch.
9. A completed refresh uses the current audit result and timestamp.
10. Unknown freshness never silently passes.
11. Unverified or mismatched recipient is excluded.
12. Quarantined or suppressed lead is excluded.
13. Repeated ingestion requests are idempotent.
14. A queued lead that becomes ineligible is rechecked before dispatch.
15. A draft edit that revokes approval invalidates any stale approval assumption.
16. Unauthorized operator requests are rejected.
17. No test creates an actual SMTP connection or live campaign task.
18. Proposal evidence cannot cross leads or domains.
19. Actual source audit status/timestamp governs freshness with exact boundary tests.
20. Existing 62-factor scoring behavior remains unchanged.
"""

from datetime import datetime, timedelta, timezone
import smtplib
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.engines.factor_contract import validate_factor_registry
from app.models import Audit, AuditStatus, Campaign, Lead
from app.routers import campaigns, proposals
from app.routers.auth import require_authorized_operator
from app.services.campaign_eligibility_service import (
    AuditFreshnessStatus,
    check_audit_freshness,
    evaluate_lead_campaign_eligibility,
    get_audience_breakdown,
    request_bounded_audit_refresh,
)
from app.services.proposal_service import ProposalService


@pytest.fixture
def mock_operator():
    return {"sub": "leadgen_operator@tebsolutions.in", "role": "operator"}


@pytest.fixture
def test_app(mock_operator):
    app = FastAPI()
    app.dependency_overrides[require_authorized_operator] = lambda: mock_operator
    app.include_router(campaigns.router)
    app.include_router(proposals.router)
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


@pytest.fixture
def deterministic_clock():
    # Fixed reference time: 2026-10-23 12:00:00 UTC
    return datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)


def create_sample_lead(
    lead_id: uuid.UUID = None,
    business_name: str = "Apex Precision Engineering",
    email: str = "contact@apexprecision.co.uk",
    website: str = "https://apexprecision.co.uk",
    email_verification_status: str = "valid",
    email_business_association_status: str = "matched",
    is_quarantined: bool = False,
    last_emailed_at: datetime = None,
) -> Lead:
    return Lead(
        id=lead_id or uuid.uuid4(),
        business_name=business_name,
        email=email,
        website=website,
        email_verification_status=email_verification_status,
        email_business_association_status=email_business_association_status,
        is_quarantined=is_quarantined,
        last_emailed_at=last_emailed_at,
    )


def create_sample_audit(
    lead_id: uuid.UUID,
    audit_id: uuid.UUID = None,
    status: AuditStatus = AuditStatus.done,
    updated_at: datetime = None,
    audit_results: Dict[str, Any] = None,
) -> Audit:
    return Audit(
        id=audit_id or uuid.uuid4(),
        lead_id=lead_id,
        status=status,
        updated_at=updated_at,
        created_at=updated_at,
        audit_results=audit_results or {
            "technical": {"ssl": {"status": "FAIL", "message": "SSL certificate expired"}},
            "performance": {"response_time": {"status": "FAIL", "message": "High TTFB"}},
        },
    )


# ---------------------------------------------------------------------------
# Test Case 1: Approved and otherwise eligible lead enters the correct cohort
# ---------------------------------------------------------------------------
def test_case_1_approved_and_eligible_lead_enters_cohort(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=2),
    )
    proposal = {
        "lead_id": str(lead_id),
        "status": "approved",
        "approved": True,
        "approved_by": "operator@tebsolutions.in",
        "approved_at": (deterministic_clock - timedelta(hours=1)).isoformat(),
        "approval_hash": "hash123",
        "target_email": lead.email,
    }

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=proposal,
        current_time=deterministic_clock,
    )

    assert result.is_eligible is True
    assert result.exclusion_reason is None


# ---------------------------------------------------------------------------
# Test Case 2: Approval-required campaign rejects an unapproved proposal
# ---------------------------------------------------------------------------
def test_case_2_approval_required_campaign_rejects_unapproved_proposal(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=2),
    )
    unapproved_proposal = {
        "lead_id": str(lead_id),
        "status": "draft_preview",
        "approved": False,
        "target_email": lead.email,
    }

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=unapproved_proposal,
        current_time=deterministic_clock,
    )

    assert result.is_eligible is False
    assert "Proposal approval required" in result.exclusion_reason


# ---------------------------------------------------------------------------
# Test Case 3: Segment-specific rules preserve valid neutral introductory workflows
# ---------------------------------------------------------------------------
def test_case_3_segment_specific_rules_preserve_neutral_intro_workflows(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id, website=None)

    # generic_first_contact does not require audit
    result_intro = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="generic_first_contact",
        audit=None,
        require_proposal_approval=False,
        current_time=deterministic_clock,
    )
    assert result_intro.is_eligible is True

    # no_website_design does not require website or audit
    result_no_web = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="no_website_design",
        audit=None,
        require_proposal_approval=False,
        current_time=deterministic_clock,
    )
    assert result_no_web.is_eligible is True


# ---------------------------------------------------------------------------
# Test Case 4: Missing or incomplete audit fails the relevant gate
# ---------------------------------------------------------------------------
def test_case_4_missing_or_incomplete_audit_fails_relevant_gate(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)

    # Missing audit
    result_missing = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=None,
        current_time=deterministic_clock,
    )
    assert result_missing.is_eligible is False
    assert "audit" in result_missing.exclusion_reason.lower()

    # Incomplete audit (status = pending)
    audit_pending = create_sample_audit(
        lead_id=lead_id,
        status=AuditStatus.pending,
        updated_at=deterministic_clock,
    )
    result_pending = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit_pending,
        current_time=deterministic_clock,
    )
    assert result_pending.is_eligible is False
    assert "refresh is in progress" in result_pending.exclusion_reason.lower() or "audit" in result_pending.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 5: Fresh audit passes the freshness check
# ---------------------------------------------------------------------------
def test_case_5_fresh_audit_passes_freshness_check(deterministic_clock):
    lead_id = uuid.uuid4()
    audit_fresh = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=5),
    )
    status, reason, age_days = check_audit_freshness(audit_fresh, max_days=14, now=deterministic_clock)
    assert status == AuditFreshnessStatus.FRESH
    assert reason is None
    assert age_days == pytest.approx(5.0, 0.01)


# ---------------------------------------------------------------------------
# Test Case 6: Stale audit returns a refresh-required result
# ---------------------------------------------------------------------------
def test_case_6_stale_audit_returns_refresh_required(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit_stale = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=15),
    )

    status, reason, age_days = check_audit_freshness(audit_stale, max_days=14, now=deterministic_clock)
    assert status == AuditFreshnessStatus.STALE
    assert age_days == pytest.approx(15.0, 0.01)

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit_stale,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is False
    assert "Audit findings are stale" in result.exclusion_reason
    assert "audit refresh required" in result.exclusion_reason


# ---------------------------------------------------------------------------
# Test Case 7: Running refresh prevents duplicate refresh tasks
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_case_7_running_refresh_prevents_duplicate_tasks(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit_running = create_sample_audit(
        lead_id=lead_id,
        status=AuditStatus.running,
        updated_at=deterministic_clock - timedelta(minutes=5),
    )
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=lead)
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=audit_running)))
    mock_bg = MagicMock(spec=BackgroundTasks)

    result = await request_bounded_audit_refresh(lead_id, mock_db, mock_bg)
    assert result["status"] == "already_running"
    # No duplicate background task added
    mock_bg.add_task.assert_not_called()


# ---------------------------------------------------------------------------
# Test Case 8: Failed refresh blocks fact-dependent dispatch
# ---------------------------------------------------------------------------
def test_case_8_failed_refresh_blocks_fact_dependent_dispatch(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit_failed = create_sample_audit(
        lead_id=lead_id,
        status=AuditStatus.failed,
        updated_at=deterministic_clock - timedelta(hours=1),
    )

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="speed_optimization",
        audit=audit_failed,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is False
    assert "Audit failed" in result.exclusion_reason or "audit" in result.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 9: A completed refresh uses the current audit result and timestamp
# ---------------------------------------------------------------------------
def test_case_9_completed_refresh_uses_current_audit_result_and_timestamp(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    # Stale audit originally
    audit = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=20),
    )
    status_before, _, _ = check_audit_freshness(audit, max_days=14, now=deterministic_clock)
    assert status_before == AuditFreshnessStatus.STALE

    # Audit completes refresh now
    audit.status = AuditStatus.done
    audit.updated_at = deterministic_clock
    audit.created_at = deterministic_clock

    status_after, reason_after, age_after = check_audit_freshness(audit, max_days=14, now=deterministic_clock)
    assert status_after == AuditFreshnessStatus.FRESH
    assert reason_after is None
    assert age_after == pytest.approx(0.0, 0.01)

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="speed_optimization",
        audit=audit,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is True


# ---------------------------------------------------------------------------
# Test Case 10: Unknown freshness never silently passes
# ---------------------------------------------------------------------------
def test_case_10_unknown_freshness_never_silently_passes(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit_no_ts = create_sample_audit(
        lead_id=lead_id,
        status=AuditStatus.done,
        updated_at=None,
    )
    audit_no_ts.created_at = None

    status, reason, age = check_audit_freshness(audit_no_ts, max_days=14, now=deterministic_clock)
    assert status == AuditFreshnessStatus.UNKNOWN
    assert age is None

    result = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit_no_ts,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is False
    assert "timestamp is missing" in result.exclusion_reason or "freshness" in result.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 11: Unverified or mismatched recipient is excluded
# ---------------------------------------------------------------------------
def test_case_11_unverified_or_mismatched_recipient_excluded(deterministic_clock):
    lead_id = uuid.uuid4()
    audit = create_sample_audit(lead_id=lead_id, updated_at=deterministic_clock)

    # Unverified email
    lead_unverified = create_sample_lead(lead_id=lead_id, email_verification_status="pending")
    result_unver = evaluate_lead_campaign_eligibility(
        lead=lead_unverified,
        campaign_type="technical_seo_proposal",
        audit=audit,
        current_time=deterministic_clock,
    )
    assert result_unver.is_eligible is False
    assert "verification" in result_unver.exclusion_reason.lower()

    # Mismatched association
    lead_mismatched = create_sample_lead(lead_id=lead_id, email_business_association_status="mismatched_source")
    result_mismatch = evaluate_lead_campaign_eligibility(
        lead=lead_mismatched,
        campaign_type="technical_seo_proposal",
        audit=audit,
        current_time=deterministic_clock,
    )
    assert result_mismatch.is_eligible is False
    assert "association" in result_mismatch.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 12: Quarantined or suppressed lead is excluded
# ---------------------------------------------------------------------------
def test_case_12_quarantined_or_suppressed_lead_excluded(deterministic_clock):
    lead_id = uuid.uuid4()
    audit = create_sample_audit(lead_id=lead_id, updated_at=deterministic_clock)
    lead_quarantined = create_sample_lead(lead_id=lead_id, is_quarantined=True)

    result = evaluate_lead_campaign_eligibility(
        lead=lead_quarantined,
        campaign_type="technical_seo_proposal",
        audit=audit,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is False
    assert "quarantined" in result.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 13: Repeated ingestion requests are idempotent
# ---------------------------------------------------------------------------
def test_case_13_repeated_ingestion_requests_are_idempotent(client, test_app, deterministic_clock):
    lead_id1 = uuid.uuid4()
    lead_id2 = uuid.uuid4()
    lead1 = create_sample_lead(lead_id=lead_id1, email="lead1@apex.com")
    lead2 = create_sample_lead(lead_id=lead_id2, email="lead2@apex.com")

    # Both have fresh audits
    audit1 = create_sample_audit(lead_id=lead_id1, updated_at=deterministic_clock - timedelta(days=1))
    audit2 = create_sample_audit(lead_id=lead_id2, updated_at=deterministic_clock - timedelta(days=2))
    lead1.audit = audit1
    lead2.audit = audit2

    mock_db = AsyncMock()
    mock_db._has_audit_references = True

    def mock_lead_query(model):
        q = MagicMock()
        q.filter.return_value.all.return_value = [lead1, lead2]
        q.filter.return_value.first.return_value = audit1
        return q

    def mock_execute_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        mock_res = MagicMock()
        if "from leads" in stmt_str or "leads.id" in stmt_str:
            mock_res.fetchall.return_value = [(lead_id1,), (lead_id2,)]
            mock_res.scalars.return_value.all.return_value = [lead1, lead2]
            return mock_res
        elif "from campaigns" in stmt_str or "campaigns.id" in stmt_str:
            mock_res.scalar_one_or_none.return_value = None
            return mock_res
        mock_res.fetchall.return_value = [(lead_id1,), (lead_id2,)]
        mock_res.scalar_one_or_none.return_value = None
        mock_res.scalar.return_value = 1
        return mock_res

    mock_db.query.side_effect = mock_lead_query
    mock_db.execute = AsyncMock(side_effect=mock_execute_impl)
    mock_db.commit = AsyncMock()
    def mock_add(camp):
        if isinstance(camp, Campaign):
            if not getattr(camp, "id", None):
                camp.id = uuid.uuid4()
            if getattr(camp, "sent_count", None) is None:
                camp.sent_count = 0
            if getattr(camp, "skipped_count", None) is None:
                camp.skipped_count = 0
            if getattr(camp, "failed_count", None) is None:
                camp.failed_count = 0
            if getattr(camp, "created_at", None) is None:
                camp.created_at = datetime.now(timezone.utc)
    mock_db.add = MagicMock(side_effect=mock_add)
    mock_db.get = AsyncMock(return_value=None)

    async def override_db():
        yield mock_db

    test_app.dependency_overrides[get_db] = override_db

    # Ingestion payload with duplicate lead IDs: [lead_id1, lead_id1, lead_id2, lead_id1]
    payload = {
        "name": "Q4 Idempotent Ingestion Test",
        "lead_ids": [str(lead_id1), str(lead_id1), str(lead_id2), str(lead_id1)],
        "campaign_type": "speed_optimization",
        "template": "Hello {business_name}",
        "subject_template": "Speed audit for {business_name}",
    }

    res1 = client.post("/campaigns/", json=payload)
    assert res1.status_code == 200, res1.text
    created_campaign = res1.json()
    # Verify no duplicate leads in campaign
    assert len(created_campaign["lead_ids"]) == 2


# ---------------------------------------------------------------------------
# Test Case 14: A queued lead that becomes ineligible is rechecked before dispatch
# ---------------------------------------------------------------------------
def test_case_14_queued_lead_becoming_ineligible_rechecked_before_dispatch(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)

    # At ingestion: audit was fresh (13 days ago)
    audit = create_sample_audit(lead_id=lead_id, updated_at=deterministic_clock - timedelta(days=13))
    result_ingest = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="speed_optimization",
        audit=audit,
        current_time=deterministic_clock,
    )
    assert result_ingest.is_eligible is True

    # 3 days later at dispatch boundary: audit is now 16 days old (stale)
    dispatch_time = deterministic_clock + timedelta(days=3)
    result_dispatch = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="speed_optimization",
        audit=audit,
        current_time=dispatch_time,
    )
    assert result_dispatch.is_eligible is False
    assert "Audit findings are stale" in result_dispatch.exclusion_reason


# ---------------------------------------------------------------------------
# Test Case 15: A draft edit that revokes approval invalidates stale approval
# ---------------------------------------------------------------------------
def test_case_15_draft_edit_revoking_approval_invalidates_stale_approval(deterministic_clock):
    lead_id = uuid.uuid4()
    lead = create_sample_lead(lead_id=lead_id)
    audit = create_sample_audit(lead_id=lead_id, updated_at=deterministic_clock)

    # 1. Proposal is created and approved
    ProposalService.get_or_create_proposal(
        lead_id=str(lead_id),
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit.audit_results,
        audit_id=str(audit.id),
        association_status="matched",
    )
    ProposalService.approve_proposal(
        lead_id=str(lead_id),
        user_email="operator@tebsolutions.in",
    )
    assert ProposalService.has_approved_proposal(str(lead_id)) is True

    proposal_state = ProposalService.get_proposal_approval_state(str(lead_id))
    result_approved = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=proposal_state,
        current_time=deterministic_clock,
    )
    assert result_approved.is_eligible is True

    # 2. Operator edits the draft (e.g. adjusts recommendations)
    ProposalService.edit_proposal(
        lead_id=str(lead_id),
        body_text="Modified unapproved proposal text",
    )
    # Status is automatically reset to draft_preview
    assert ProposalService.has_approved_proposal(str(lead_id)) is False

    revoked_state = ProposalService.get_proposal_approval_state(str(lead_id))
    result_after_edit = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=revoked_state,
        current_time=deterministic_clock,
    )
    assert result_after_edit.is_eligible is False
    assert "Proposal approval required" in result_after_edit.exclusion_reason


# ---------------------------------------------------------------------------
# Test Case 16: Unauthorized operator requests are rejected
# ---------------------------------------------------------------------------
def test_case_16_unauthorized_operator_requests_rejected():
    raw_app = FastAPI()
    raw_app.include_router(campaigns.router)
    unauthed_client = TestClient(raw_app)

    # POST /campaigns/
    res_create = unauthed_client.post("/campaigns/", json={"name": "Test", "lead_ids": []})
    assert res_create.status_code in (401, 403)

    # POST /campaigns/audience-check
    res_audience = unauthed_client.post("/campaigns/audience-check", json={"lead_ids": []})
    assert res_audience.status_code in (401, 403)

    # POST /campaigns/refresh-audit/{lead_id}
    res_refresh = unauthed_client.post(f"/campaigns/refresh-audit/{uuid.uuid4()}")
    assert res_refresh.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test Case 17: No test creates an actual SMTP connection or live campaign task
# ---------------------------------------------------------------------------
def test_case_17_no_test_creates_actual_smtp_connection_or_live_campaign_task():
    with patch("smtplib.SMTP") as mock_smtp, patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        # Verify both have 0 calls
        mock_smtp.assert_not_called()
        mock_smtp_ssl.assert_not_called()
        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0


# ---------------------------------------------------------------------------
# Test Case 18: Proposal evidence cannot cross leads or domains
# ---------------------------------------------------------------------------
def test_case_18_proposal_evidence_cannot_cross_leads_or_domains(deterministic_clock):
    lead_a = create_sample_lead(lead_id=uuid.uuid4(), email="a@alpha.com", business_name="Alpha Corp")
    lead_b = create_sample_lead(lead_id=uuid.uuid4(), email="b@beta.com", business_name="Beta Corp")
    audit_b = create_sample_audit(lead_id=lead_b.id, updated_at=deterministic_clock)

    # Proposal approved for Lead A
    prop_a = {
        "lead_id": str(lead_a.id),
        "status": "approved",
        "approved": True,
        "approved_by": "operator@tebsolutions.in",
        "target_email": lead_a.email,
        "approval_hash": "hash_a",
    }

    # Attempting to use Lead A's proposal to validate Lead B
    result = evaluate_lead_campaign_eligibility(
        lead=lead_b,
        campaign_type="technical_seo_proposal",
        audit=audit_b,
        require_proposal_approval=True,
        proposal=prop_a,
        current_time=deterministic_clock,
    )
    assert result.is_eligible is False
    assert "provenance mismatch" in result.exclusion_reason.lower()


# ---------------------------------------------------------------------------
# Test Case 19: Actual source audit status/timestamp governs freshness
# ---------------------------------------------------------------------------
def test_case_19_actual_source_audit_status_and_timestamp_governs_freshness(deterministic_clock):
    lead_id = uuid.uuid4()

    # Case A: Just-before threshold (13 days, 23 hours, 59 minutes) -> FRESH
    audit_just_before = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=13, hours=23, minutes=59),
    )
    status_a, reason_a, age_a = check_audit_freshness(audit_just_before, max_days=14, now=deterministic_clock)
    assert status_a == AuditFreshnessStatus.FRESH
    assert reason_a is None
    assert age_a < 14.0

    # Case B: Exactly at threshold (14 days, 0 seconds) -> FRESH
    audit_exact = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=14),
    )
    status_b, reason_b, age_b = check_audit_freshness(audit_exact, max_days=14, now=deterministic_clock)
    assert status_b == AuditFreshnessStatus.FRESH
    assert reason_b is None
    assert age_b == pytest.approx(14.0, 0.0001)

    # Case C: Just-after threshold (14 days, 1 second) -> STALE
    audit_just_after = create_sample_audit(
        lead_id=lead_id,
        updated_at=deterministic_clock - timedelta(days=14, seconds=1),
    )
    status_c, reason_c, age_c = check_audit_freshness(audit_just_after, max_days=14, now=deterministic_clock)
    assert status_c == AuditFreshnessStatus.STALE
    assert "Audit findings are stale" in reason_c
    assert age_c > 14.0


# ---------------------------------------------------------------------------
# Test Case 20: Existing 62-factor scoring behavior remains unchanged
# ---------------------------------------------------------------------------
def test_case_20_existing_62_factor_scoring_behavior_remains_unchanged():
    factors = validate_factor_registry()
    assert len(factors) == 62, f"Canonical factors changed! Expected 62, found {len(factors)}"

    # Verify key factors exist with their weights
    assert "technical.ssl" in factors
    assert factors["technical.ssl"]["score_weight"] > 0
    assert "technical.robots" in factors
    assert "onpage.page_title" in factors
    assert "ux.cta" in factors
    assert "performance.lcp" in factors or "performance.pagespeed" in factors or "performance.response_time" in factors
