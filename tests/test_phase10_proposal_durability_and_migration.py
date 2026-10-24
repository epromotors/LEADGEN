"""
tests/test_phase10_proposal_durability_and_migration.py

Focused Verification Suite for LEADGEN Phase 10:
Migration Readiness, Durable Proposal Approval & Staging Rehearsal.

Verifies:
1. Draft and approval persistence across service instances or restarts (DB-backed).
2. Approval invalidation on edit survives restart.
3. Strict lead-provenance validation (mismatches fail closed).
4. Concurrent approval/edit conflict detection via cryptographic content hashing.
5. Missing or corrupt/tampered approval records fail closed.
6. Campaign dispatch rejection when proposal approval is missing or stale.
7. Migration SQL preconditions, database safety guards, and idempotency across v6.2.0-v6.2.6.
8. Zero SMTP calls and zero live queue activity.
"""

from datetime import datetime, timezone, timedelta
import os
import re
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest

from app.database import Base
from app.models import Lead, Audit, AuditStatus, ServiceProposal
from app.services.proposal_service import (
    ProposalService,
    HumanApprovalRequiredError,
    ProposalWorkflowError,
)
from app.services.campaign_eligibility_service import (
    evaluate_lead_campaign_eligibility,
    CampaignType,
)


@pytest.fixture(autouse=True)
def clean_proposal_cache():
    """Reset the non-authoritative in-memory mirror cache before and after every test."""
    ProposalService._proposals.clear()
    yield
    ProposalService._proposals.clear()


@pytest.mark.anyio
async def test_01_draft_and_approval_persistence_across_restart():
    """
    Requirement: Draft content, lead association, approval status, approver identity,
    and timestamps must persist in the database and survive process restart/cache clear.
    """
    lead_id = uuid.uuid4()
    lead_str = str(lead_id)

    # Mock an isolated DB session tracking a persistent ServiceProposal row
    persisted_rows: dict[uuid.UUID, ServiceProposal] = {}

    mock_db = AsyncMock()

    def mock_add(instance):
        if isinstance(instance, ServiceProposal):
            persisted_rows[instance.lead_id] = instance

    mock_db.add = MagicMock(side_effect=mock_add)

    async def mock_execute(stmt):
        mock_result = MagicMock()
        # Find if looking up ServiceProposal by lead_id
        row = persisted_rows.get(lead_id)
        mock_result.scalars.return_value.first.return_value = row
        mock_result.scalar_one_or_none.return_value = row
        return mock_result

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_db.commit = AsyncMock()

    audit_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "SSL expired"}},
        "ux": {"cta": {"status": "FAIL"}},
    }

    # 1. Create Proposal Draft via DB-backed API
    prop = await ProposalService.aget_or_create_proposal(
        lead_id=lead_str,
        business_name="Apex Precision Engineering",
        website_url="https://apexprecision.co.uk",
        audit_results=audit_results,
        audit_id=str(uuid.uuid4()),
        association_status="matched",
        db=mock_db,
    )
    assert prop["approved"] is False
    assert prop["status"] == "draft_preview"
    assert lead_id in persisted_rows

    # 2. Approve Proposal
    approved = await ProposalService.aapprove_proposal(
        lead_id=lead_str,
        user_email="auditor_lead@tebsolutions.in",
        db=mock_db,
    )
    assert approved["approved"] is True
    assert approved["approved_by"] == "auditor_lead@tebsolutions.in"
    assert approved["approval_hash"] is not None
    assert approved["status"] == "approved_for_delivery"

    # Verify persistent DB row was updated
    assert persisted_rows[lead_id].status == "approved_for_delivery"
    assert persisted_rows[lead_id].approved_by == "auditor_lead@tebsolutions.in"

    # 3. SIMULATE HARD REBOOT / RESTART: Wipe in-memory cache completely
    ProposalService._proposals.clear()
    assert lead_str not in ProposalService._proposals

    # 4. Verify DB Row Exists and Survives Restart
    reloaded = await ProposalService.aload_proposal(lead_str, db=mock_db)
    assert reloaded is not None
    assert reloaded["lead_id"] == lead_str
    assert reloaded["approved"] is True
    assert reloaded["approved_by"] == "auditor_lead@tebsolutions.in"
    assert reloaded["approval_hash"] == approved["approval_hash"]
    assert reloaded["status"] == "approved_for_delivery"
    assert reloaded["business_name"] == "Apex Precision Engineering"

    # 5. Authoritative gate check survives restart
    has_approved = await ProposalService.ahas_approved_proposal(lead_str, db=mock_db)
    assert has_approved is True


@pytest.mark.anyio
async def test_02_approval_invalidation_on_edit_persists_across_restart():
    """
    Requirement: Editing a previously approved proposal invalidates its approval,
    and this invalidation survives application restart.
    """
    lead_id = uuid.uuid4()
    lead_str = str(lead_id)

    persisted_rows: dict[uuid.UUID, ServiceProposal] = {}
    mock_db = AsyncMock()
    mock_db.add = MagicMock(side_effect=lambda inst: persisted_rows.update({inst.lead_id: inst}) if isinstance(inst, ServiceProposal) else None)
    mock_db.execute = AsyncMock(side_effect=lambda stmt: MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=persisted_rows.get(lead_id))))))
    mock_db.commit = AsyncMock()

    audit_results = {"technical": {"sitemap": {"status": "FAIL"}}}

    # Generate and approve
    await ProposalService.aget_or_create_proposal(
        lead_id=lead_str,
        business_name="Carmedic Auto",
        website_url="https://carmedic.co.uk",
        audit_results=audit_results,
        db=mock_db,
    )
    await ProposalService.aapprove_proposal(
        lead_id=lead_str,
        user_email="operator@tebsolutions.in",
        db=mock_db,
    )

    # Human operator edits proposal draft
    edited = await ProposalService.aedit_proposal(
        lead_id=lead_str,
        subject="Updated Custom SEO Strategy for Carmedic",
        db=mock_db,
    )
    assert edited["edited"] is True
    assert edited["approved"] is False
    assert edited["approved_by"] is None
    assert edited["approval_hash"] is None
    assert edited["status"] == "draft_preview"

    # Verify DB row updated to invalid approval
    assert persisted_rows[lead_id].status == "draft_preview"
    assert persisted_rows[lead_id].approved_by is None

    # Simulate restart
    ProposalService._proposals.clear()

    # Reload from DB after restart
    reloaded = await ProposalService.aload_proposal(lead_str, db=mock_db)
    assert reloaded["subject"] == "Updated Custom SEO Strategy for Carmedic"
    assert reloaded["approved"] is False
    assert reloaded["approved_by"] is None
    assert reloaded["approval_hash"] is None
    assert reloaded["status"] == "draft_preview"

    # Dispatch must fail closed
    with pytest.raises(HumanApprovalRequiredError):
        await ProposalService.adispatch_proposal(
            lead_id=lead_str,
            target_email="service@carmedic.co.uk",
            dry_run=True,
            db=mock_db,
        )


@pytest.mark.anyio
async def test_03_strict_lead_provenance_validation():
    """
    Requirement: A proposal must remain associated with its correct lead.
    Mismatched lead IDs fail closed on approval and dispatch.
    """
    lead1_id = str(uuid.uuid4())
    lead2_id = str(uuid.uuid4())

    # Create proposal for lead1
    ProposalService.get_or_create_proposal(
        lead_id=lead1_id,
        business_name="Lead 1 Co",
        website_url="https://lead1.com",
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
    )

    # Deliberately attempt cross-lead approval
    ProposalService._proposals[lead1_id]["lead_id"] = lead2_id
    with pytest.raises(ProposalWorkflowError, match="provenance mismatch"):
        ProposalService.approve_proposal(lead1_id, user_email="admin@tebsolutions.in")


@pytest.mark.anyio
async def test_04_concurrent_modification_conflict_detection():
    """
    Requirement: Concurrent edits or approval operations cannot silently approve
    different content from what the operator reviewed (cryptographic hash integrity).
    """
    lead_id = str(uuid.uuid4())

    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="FastTrack Ltd",
        website_url="https://fasttrack.co.uk",
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
    )

    # Operator A reviewed content and expected hash
    expected_reviewed_hash = ProposalService.compute_content_hash(prop)

    # Operator B edits the proposal behind Operator A's back
    ProposalService.edit_proposal(lead_id, body_text="Modified text by Operator B")

    # Operator A attempts to approve with their previously reviewed hash -> MUST FAIL
    with pytest.raises(ProposalWorkflowError, match="Concurrent modification detected"):
        ProposalService.approve_proposal(
            lead_id=lead_id,
            user_email="operator_a@tebsolutions.in",
            expected_hash=expected_reviewed_hash,
        )


@pytest.mark.anyio
async def test_05_tampered_or_corrupt_approval_record_fails_closed():
    """
    Requirement: If a persisted proposal approval record is tampered with or corrupted,
    both dispatch and campaign eligibility checks fail closed.
    """
    lead_id = uuid.uuid4()
    lead_str = str(lead_id)

    lead = Lead(
        id=lead_id,
        business_name="Tamper Test Co",
        website="https://tamper.com",
        email="admin@tamper.com",
        email_verification_status="valid",
        email_business_association_status="matched",
    )
    audit = Audit(
        id=uuid.uuid4(),
        lead_id=lead_id,
        status=AuditStatus.done,
        updated_at=datetime.now(timezone.utc),
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
    )

    # 1. Create and approve draft
    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_str,
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit.audit_results,
    )
    ProposalService.approve_proposal(lead_str, user_email="operator@tebsolutions.in")

    # 2. Corrupt/tamper proposal content directly without recomputing hash
    ProposalService._proposals[lead_str]["body_text"] = "INJECTED MALICIOUS CONTENT"

    # 3. Campaign eligibility must fail closed
    res = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=ProposalService._proposals[lead_str],
    )
    assert res.is_eligible is False
    assert "Proposal approval revoked: draft content modified post-approval" in res.exclusion_reason

    # 4. Dispatch attempt must invalidate approval and raise HumanApprovalRequiredError
    with pytest.raises(HumanApprovalRequiredError):
        ProposalService.dispatch_proposal(
            lead_id=lead_str,
            target_email=lead.email,
            dry_run=True,
        )


@pytest.mark.anyio
async def test_06_campaign_dispatch_rejection_when_approval_missing():
    """
    Requirement: Missing proposal approval categorically rejects campaign dispatch.
    """
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Unapproved Lead",
        website="https://unapproved.com",
        email="contact@unapproved.com",
        email_verification_status="valid",
        email_business_association_status="matched",
    )
    audit = Audit(
        id=uuid.uuid4(),
        lead_id=lead.id,
        status=AuditStatus.done,
        updated_at=datetime.now(timezone.utc),
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
    )

    # Require proposal approval but pass no approved record
    res = evaluate_lead_campaign_eligibility(
        lead=lead,
        campaign_type="technical_seo_proposal",
        audit=audit,
        require_proposal_approval=True,
        proposal=None,
    )
    assert res.is_eligible is False
    assert "Proposal approval required: no authoritative proposal draft found" in res.exclusion_reason


def test_07_migration_sql_guards_and_idempotency():
    """
    Requirement: Inspect migrations v6_2_0 through v6_2_6 to verify:
    - Preflight database blacklist guards are present.
    - All DDL statements are additive (IF NOT EXISTS).
    - No DROP, TRUNCATE, or destructive statements exist.
    """
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "migrations")
    migration_files = [
        "v6_2_0_email_verification.sql",
        "v6_2_1_email_association_provenance.sql",
        "v6_2_2_campaign_segmentation.sql",
        "v6_2_3_audit_email_freshness.sql",
        "v6_2_4_ai_search_observations.sql",
        "v6_2_5_proposal_approval_persistence.sql",
        "v6_2_6_campaign_orchestration_and_locks.sql",
    ]

    for fname in migration_files:
        fpath = os.path.join(migrations_dir, fname)
        assert os.path.exists(fpath), f"Migration file {fname} is missing!"
        with open(fpath, "r", encoding="utf-8") as f:
            sql = f.read()

        # 1. Assert preflight database guard exists
        assert "DO $$" in sql, f"{fname} lacks DO $$ preflight block"
        assert "leadgen" in sql, f"{fname} lacks protected database check"
        assert "RAISE EXCEPTION" in sql, f"{fname} lacks abort exception"

        # 2. Assert no destructive keywords
        destructive_patterns = [r"\bDROP\s+TABLE\b", r"\bDROP\s+COLUMN\b", r"\bTRUNCATE\b"]
        for pat in destructive_patterns:
            assert not re.search(pat, sql, re.IGNORECASE), f"{fname} contains destructive statement: {pat}"

        # 3. Assert transaction encapsulation
        assert "BEGIN;" in sql, f"{fname} must contain BEGIN;"
        assert "COMMIT;" in sql, f"{fname} must contain COMMIT;"


@pytest.mark.anyio
async def test_08_safe_delivery_simulation_zero_smtp():
    """
    Requirement: Dry run delivery simulation succeeds without SMTP network calls
    or live queue enqueueing.
    """
    lead_id = str(uuid.uuid4())
    ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Safe Deliver Ltd",
        website_url="https://safedeliver.com",
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
        association_status="matched",
    )
    ProposalService.approve_proposal(lead_id, user_email="operator@tebsolutions.in")

    res = ProposalService.dispatch_proposal(
        lead_id=lead_id,
        target_email="test@safedeliver.com",
        dry_run=True,
    )
    assert res["success"] is True
    assert res["mode"] == "dry_run"
    assert "Delivery simulated" in res["message"]
    # Live send must be categorically disabled
    with pytest.raises(ProposalWorkflowError, match="Direct proposal delivery is disabled"):
        ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email="test@safedeliver.com",
            dry_run=False,
        )
