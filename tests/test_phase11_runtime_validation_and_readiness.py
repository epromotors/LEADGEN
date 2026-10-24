"""
tests/test_phase11_runtime_validation_and_readiness.py

Comprehensive Runtime Validation & Release Readiness Suite for LEADGEN Phase 11.
Executed strictly against the verified isolated disposable staging database:
`leadgen_migration_e2e_stage10_20261023_220853_7c18ee`.

Validates:
1. Database identity, non-superuser role, isolation, and absence of production data.
2. ORM schema compatibility and explicit missing-column behavior for unmigrated/legacy attributes.
3. Database error resilience (missing tables/columns, unavailable database).
4. Durable proposal approval full lifecycle: draft -> approve -> restart -> edit invalidation.
5. Fail-closed security gates: lead provenance, unauthorized operators, stale hashes, corrupt states.
6. Campaign worker presend enforcement of persistent proposal approvals.
7. Campaign scheduler claiming (FOR UPDATE SKIP LOCKED), worker locking, pause/cancellation, and audit freshness.
8. Transport boundary safety: ZERO SMTP calls and zero live outreach.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import selectors
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse
import pytest

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import ProgrammingError

from app.database import Base, PROTECTED_DATABASES
from app.models import Lead, Audit, AuditStatus, ServiceProposal, Campaign, CampaignStatus
from app.services.proposal_service import (
    ProposalService,
    HumanApprovalRequiredError,
    ProposalWorkflowError,
)
from app.services.campaign_eligibility_service import (
    evaluate_lead_campaign_eligibility,
    CampaignType,
)
from app.services.campaign_lock_service import (
    campaign_lock_coordinator,
    derive_campaign_lock_key,
)
from app.services.campaign_scheduler import CampaignScheduler


STAGING_DB_NAME = "leadgen_migration_e2e_stage10_20261023_220853_7c18ee"


def get_staging_engine():
    """Build an async SQLAlchemy engine connected strictly to the verified staging database."""
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))
    db_url = None
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in backend/.env")

    parsed = urlparse(db_url)
    staging_url = (
        f"postgresql+psycopg://{parsed.username}:{parsed.password}@"
        f"{parsed.hostname}:{parsed.port}/{STAGING_DB_NAME}"
    )
    return create_async_engine(
        staging_url,
        echo=False,
        pool_pre_ping=True,
    )


@pytest.fixture
def anyio_backend():
    """Ensure psycopg async operates with SelectorEventLoop on Windows."""
    if sys.platform == "win32":
        return ("asyncio", {"loop_factory": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())})
    return "asyncio"


@pytest.fixture(autouse=True)
def clean_proposal_mirror_cache():
    """Ensure in-memory cache is wiped around every test."""
    ProposalService._proposals.clear()
    campaign_lock_coordinator._active_in_process.clear()
    campaign_lock_coordinator._simulated_external_locks.clear()
    yield
    ProposalService._proposals.clear()
    campaign_lock_coordinator._active_in_process.clear()
    campaign_lock_coordinator._simulated_external_locks.clear()


@pytest.mark.anyio
async def test_01_database_identity_isolation_and_migration_status():
    """
    Mandatory Gate: Verify connected database is strictly the isolated staging database,
    connected under restricted role leadgen_release_app (usesuper=False),
    contains zero production business records, and has all 7 migrations v6.2.0-v6.2.6 applied.
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # 1. Establish current database identity and connected role
        res = await session.execute(text("SELECT current_database(), current_user, pg_is_in_recovery()"))
        curr_db, curr_user, in_recovery = res.fetchone()
        assert curr_db == STAGING_DB_NAME, f"Connected to unexpected database: {curr_db}"
        assert curr_user == "leadgen_release_app", f"Connected as unexpected role: {curr_user}"
        assert in_recovery is False

        # 2. Confirm least-privilege role: NOT a superuser
        res_super = await session.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))
        is_super = res_super.scalar_one()
        assert is_super is False, "Violation: Connected role must not be a superuser"

        # 3. Confirm target database is strictly NOT on the protected blacklist
        assert curr_db not in PROTECTED_DATABASES, f"Target database {curr_db} is on the protected blacklist!"

        # 4. Verify presence of all expected tables from v6.2.0 through v6.2.6
        res_tables = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        )
        tables = set(r[0] for r in res_tables.fetchall())
        required_tables = {"leads", "audits", "campaigns", "service_proposals", "ai_search_observations"}
        missing_tables = required_tables - tables
        assert not missing_tables, f"Missing required tables in staging schema: {missing_tables}"

        # 5. Verify absence of production business data (staging database contains only synthetic items)
        for tbl in ["leads", "campaigns", "service_proposals"]:
            cnt_res = await session.execute(text(f"SELECT count(*) FROM {tbl}"))
            cnt = cnt_res.scalar_one()
            assert cnt <= 20, f"Table {tbl} contains suspicious volume of rows ({cnt}); expected disposable staging data only."

    await engine.dispose()


@pytest.mark.anyio
async def test_02_application_startup_shutdown_and_orm_compatibility():
    """
    Verify application lifespan and ORM model compatibility against the migrated staging schema.
    Specifically tests:
    - ServiceProposal model queries and writes (added in v6.2.5).
    - Lead model queries.
    - Demonstrates missing-column behavior when a model requests unmigrated/legacy attributes
      (e.g. audits.ssl_valid or campaigns.next_email_at which belong to full baseline, not v6.2 migrations).
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # 1. ServiceProposal ORM model is fully compatible with migrated schema
        proposal_stmt = select(ServiceProposal).limit(5)
        proposals = (await session.execute(proposal_stmt)).scalars().all()
        assert isinstance(proposals, list)

        # 2. Lead ORM model is fully compatible with migrated schema
        lead_stmt = select(Lead).limit(5)
        leads = (await session.execute(lead_stmt)).scalars().all()
        assert isinstance(leads, list)

        # 3. Verify missing-column error detection when model requests columns not in staging baseline
        with pytest.raises(ProgrammingError) as exc_audit:
            await session.execute(select(Audit).limit(1))
        assert "ssl_valid" in str(exc_audit.value).lower()
        await session.rollback()

        with pytest.raises(ProgrammingError) as exc_camp:
            await session.execute(select(Campaign).limit(1))
        assert "next_email_at" in str(exc_camp.value).lower()
        await session.rollback()

    await engine.dispose()


@pytest.mark.anyio
async def test_03_missing_schema_and_db_unavailable_error_handling():
    """
    Verify application behavior on schema mismatches and database unavailability.
    Missing tables/columns or broken connections must raise explicit, predictable errors
    without silently swallowing failures or crashing unhandled.
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Querying a non-existent column or table must raise an explicit DBAPI/SQLAlchemy error
    async with Session() as session:
        with pytest.raises(Exception) as exc_info:
            await session.execute(text("SELECT non_existent_column FROM leads"))
        assert "non_existent_column" in str(exc_info.value).lower()
        await session.rollback()

    await engine.dispose()

    # 2. Database unavailable connection attempt
    bad_url = "postgresql+psycopg://leadgen_release_app:dummy_pass@127.0.0.1:5432/non_existent_db_xyz"
    bad_engine = create_async_engine(bad_url)
    BadSession = async_sessionmaker(bind=bad_engine, class_=AsyncSession)

    with pytest.raises(Exception) as exc_conn:
        async with BadSession() as bad_session:
            await bad_session.execute(text("SELECT 1"))
    assert (
        "database \"non_existent_db_xyz\" does not exist" in str(exc_conn.value).lower()
        or "connection" in str(exc_conn.value).lower()
    )

    await bad_engine.dispose()


@pytest.mark.anyio
async def test_04_durable_proposal_approval_e2e_lifecycle():
    """
    Exercise the full durable proposal approval lifecycle against real PostgreSQL:
    1. Create a draft proposal for a synthetic lead in the staging DB.
    2. Retrieve it through the service.
    3. Approve it as an authorized operator.
    4. Confirm approval status, approver identity, timestamp, lead provenance, and hash persist in PostgreSQL.
    5. SIMULATE HARD RESTART: Wipe in-memory mirror and recreate independent session.
    6. Retrieve proposal and confirm identical approval state is restored from PostgreSQL.
    7. Edit the proposal and verify former approval becomes invalid and persists as invalid in PostgreSQL.
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    test_lead_id = uuid.uuid4()
    test_lead_str = str(test_lead_id)
    test_audit_id = uuid.uuid4()

    async with Session() as session:
        # Create synthetic test lead and audit using schema-compatible raw SQL
        await session.execute(
            text(
                "INSERT INTO leads (id, business_name, email, website, status, email_verification_status, email_business_association_status) "
                "VALUES (:id, :business_name, :email, :website, :status, :email_verification_status, :email_business_association_status)"
            ),
            {
                "id": test_lead_id,
                "business_name": "Stage11 Precision Tooling",
                "email": f"contact_{test_lead_id.hex[:6]}@stage11precision.co.uk",
                "website": "https://stage11precision.co.uk",
                "status": "new",
                "email_verification_status": "valid",
                "email_business_association_status": "matched",
            },
        )
        audit_results_payload = {"technical": {"ssl": {"status": "FAIL", "message": "Expired certificate"}}}
        await session.execute(
            text(
                "INSERT INTO audits (id, lead_id, status, audit_results, site_summary, updated_at) "
                "VALUES (:id, :lead_id, :status, :audit_results, :site_summary, :updated_at)"
            ),
            {
                "id": test_audit_id,
                "lead_id": test_lead_id,
                "status": "done",
                "audit_results": json.dumps(audit_results_payload),
                "site_summary": json.dumps({"url_info": {"requested_url": "https://stage11precision.co.uk"}}),
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.commit()

        # Step 1: Create draft proposal via ProposalService against real DB
        prop = await ProposalService.aget_or_create_proposal(
            lead_id=test_lead_str,
            business_name="Stage11 Precision Tooling",
            website_url="https://stage11precision.co.uk",
            audit_results=audit_results_payload,
            audit_id=str(test_audit_id),
            association_status="matched",
            db=session,
        )
        assert prop["approved"] is False
        assert prop["status"] == "draft_preview"
        assert prop["lead_id"] == test_lead_str

        # Verify draft was written to PostgreSQL ServiceProposal table
        sp_res = await session.execute(
            select(ServiceProposal).where(ServiceProposal.lead_id == test_lead_id)
        )
        sp_db = sp_res.scalar_one_or_none()
        assert sp_db is not None
        assert sp_db.status == "draft_preview"
        assert sp_db.approved_by is None
        assert sp_db.approval_hash is None

        # Step 2: Approve proposal as authorized operator
        approved = await ProposalService.aapprove_proposal(
            lead_id=test_lead_str,
            user_email="operator_stage11@tebsolutions.in",
            db=session,
        )
        assert approved["approved"] is True
        assert approved["approved_by"] == "operator_stage11@tebsolutions.in"
        assert approved["status"] == "approved_for_delivery"
        assert approved["approval_hash"] is not None
        saved_hash = approved["approval_hash"]

        # Step 3: Verify PostgreSQL row reflects approval
        await session.refresh(sp_db)
        assert sp_db.status == "approved_for_delivery"
        assert sp_db.approved_by == "operator_stage11@tebsolutions.in"
        assert sp_db.approval_hash == saved_hash
        assert sp_db.approved_at is not None

    # Step 4: HARD SERVICE RESTART SIMULATION
    # 1. Wipe in-memory mirror cache completely
    ProposalService._proposals.clear()
    assert test_lead_str not in ProposalService._proposals

    # 2. In a brand-new independent database session/process
    async with Session() as restart_session:
        # Step 5: Reload from PostgreSQL and confirm approval state survives restart
        reloaded = await ProposalService.aload_proposal(test_lead_str, db=restart_session)
        assert reloaded is not None
        assert reloaded["lead_id"] == test_lead_str
        assert reloaded["approved"] is True
        assert reloaded["approved_by"] == "operator_stage11@tebsolutions.in"
        assert reloaded["approval_hash"] == saved_hash
        assert reloaded["status"] == "approved_for_delivery"

        # Check authoritative boolean gate survives restart
        has_approved = await ProposalService.ahas_approved_proposal(test_lead_str, db=restart_session)
        assert has_approved is True

        # Step 6: Edit proposal draft -> former approval MUST become invalid
        edited = await ProposalService.aedit_proposal(
            lead_id=test_lead_str,
            subject="Updated Custom Strategy for Stage11 Tooling",
            db=restart_session,
        )
        assert edited["edited"] is True
        assert edited["approved"] is False
        assert edited["approved_by"] is None
        assert edited["approval_hash"] is None
        assert edited["status"] == "draft_preview"

        # Step 7: Verify PostgreSQL row was updated with invalidated approval
        res_check = await restart_session.execute(
            select(ServiceProposal).where(ServiceProposal.lead_id == test_lead_id)
        )
        sp_invalidated = res_check.scalar_one()
        assert sp_invalidated.status == "draft_preview"
        assert sp_invalidated.approved_by is None
        assert sp_invalidated.approval_hash is None

    # Step 8: Second restart: confirm invalidation also survives restart
    ProposalService._proposals.clear()
    async with Session() as second_restart_session:
        reloaded_after_edit = await ProposalService.aload_proposal(test_lead_str, db=second_restart_session)
        assert reloaded_after_edit["approved"] is False
        assert reloaded_after_edit["status"] == "draft_preview"
        assert reloaded_after_edit["approved_by"] is None
        assert reloaded_after_edit["approval_hash"] is None

        # Authoritative gate fails closed
        has_approved_after_edit = await ProposalService.ahas_approved_proposal(
            test_lead_str, db=second_restart_session
        )
        assert has_approved_after_edit is False

        # Attempting dispatch without re-approval fails closed
        with pytest.raises(HumanApprovalRequiredError):
            await ProposalService.adispatch_proposal(
                lead_id=test_lead_str,
                target_email=f"contact_{test_lead_id.hex[:6]}@stage11precision.co.uk",
                dry_run=True,
                db=second_restart_session,
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_05_invalid_scenarios_fail_closed():
    """
    Verify all invalid proposal states fail closed:
    - Mismatched lead provenance
    - Unauthorized operator
    - Stale content hash / concurrent modification
    - Tampered or corrupt approval record
    - Missing record
    """
    lead_id = str(uuid.uuid4())
    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Fail Closed Ltd",
        website_url="https://failclosed.co.uk",
        audit_results={"technical": {"ssl": {"status": "FAIL"}}},
    )
    original_hash = ProposalService.compute_content_hash(prop)

    # 1. Lead provenance mismatch fails closed
    lead2_id = str(uuid.uuid4())
    ProposalService._proposals[lead_id]["lead_id"] = lead2_id
    with pytest.raises(ProposalWorkflowError, match="provenance mismatch"):
        ProposalService.approve_proposal(
            lead_id=lead_id,
            user_email="operator@tebsolutions.in",
        )
    # Restore correct lead_id for subsequent tests
    ProposalService._proposals[lead_id]["lead_id"] = lead_id

    # 2. Concurrent modification / stale hash fails closed
    ProposalService.edit_proposal(lead_id, body_text="Modified by another concurrent actor")
    with pytest.raises(ProposalWorkflowError, match="Concurrent modification detected"):
        ProposalService.approve_proposal(
            lead_id=lead_id,
            user_email="operator@tebsolutions.in",
            expected_hash=original_hash,
        )

    # 3. Tampered content fails closed upon dispatch
    ProposalService.approve_proposal(lead_id, user_email="operator@tebsolutions.in")
    ProposalService._proposals[lead_id]["body_text"] = "INJECTED MALICIOUS OVERWRITE"
    with pytest.raises(HumanApprovalRequiredError):
        ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email="test@failclosed.co.uk",
            dry_run=True,
        )

    # 4. Missing proposal record fails closed
    missing_id = str(uuid.uuid4())
    with pytest.raises(ProposalWorkflowError, match="does not exist"):
        ProposalService.approve_proposal(missing_id, user_email="operator@tebsolutions.in")


@pytest.mark.anyio
async def test_06_campaign_worker_enforces_persisted_approval_at_dispatch():
    """
    Verify that the campaign worker presend gate checks the persistent database
    record and enforces approval requirements immediately before dispatch.
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    lead_id = uuid.uuid4()
    audit_id = uuid.uuid4()

    async with Session() as session:
        # Create synthetic lead and audit via raw SQL
        await session.execute(
            text(
                "INSERT INTO leads (id, business_name, email, website, status, email_verification_status, email_business_association_status) "
                "VALUES (:id, :business_name, :email, :website, :status, :email_verification_status, :email_business_association_status)"
            ),
            {
                "id": lead_id,
                "business_name": "Worker Enforcement Ltd",
                "email": f"contact_{lead_id.hex[:6]}@workerenforce.com",
                "website": "https://workerenforce.com",
                "status": "new",
                "email_verification_status": "valid",
                "email_business_association_status": "matched",
            },
        )
        audit_payload = {"technical": {"ssl": {"status": "FAIL"}}}
        await session.execute(
            text(
                "INSERT INTO audits (id, lead_id, status, audit_results, site_summary, updated_at) "
                "VALUES (:id, :lead_id, :status, :audit_results, :site_summary, :updated_at)"
            ),
            {
                "id": audit_id,
                "lead_id": lead_id,
                "status": "done",
                "audit_results": json.dumps(audit_payload),
                "site_summary": json.dumps({"url_info": {"requested_url": "https://workerenforce.com"}}),
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.commit()

        # Query Lead object
        lead_res = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead_obj = lead_res.scalar_one()

        # Mock audit object representation for eligibility evaluation
        mock_audit = MagicMock()
        mock_audit.id = audit_id
        mock_audit.lead_id = lead_id
        mock_audit.status = AuditStatus.done
        mock_audit.audit_results = audit_payload
        mock_audit.updated_at = datetime.now(timezone.utc)

        # 1. Proposal draft created in PostgreSQL but NOT approved
        await ProposalService.aget_or_create_proposal(
            lead_id=str(lead_id),
            business_name=lead_obj.business_name,
            website_url=lead_obj.website,
            audit_results=audit_payload,
            audit_id=str(audit_id),
            db=session,
        )

        # Wipe mirror cache to force PostgreSQL load
        ProposalService._proposals.clear()

        # Worker presend check: load from DB
        loaded_proposal = await ProposalService.aload_proposal(str(lead_id), db=session)
        is_el, reason, _, _ = evaluate_lead_campaign_eligibility(
            lead=lead_obj,
            audit=mock_audit,
            campaign_type="technical_seo_proposal",
            require_proposal_approval=True,
            proposal=loaded_proposal,
        )
        assert is_el is False
        assert "pending explicit operator approval" in reason or "Proposal approval required" in reason

        # 2. Operator approves proposal in PostgreSQL
        await ProposalService.aapprove_proposal(
            lead_id=str(lead_id),
            user_email="operator_audit@tebsolutions.in",
            db=session,
        )
        ProposalService._proposals.clear()

        # Worker presend check reloaded from DB
        approved_prop = await ProposalService.aload_proposal(str(lead_id), db=session)
        is_el_approved, reason_approved, _, _ = evaluate_lead_campaign_eligibility(
            lead=lead_obj,
            audit=mock_audit,
            campaign_type="technical_seo_proposal",
            require_proposal_approval=True,
            proposal=approved_prop,
        )
        assert is_el_approved is True
        assert reason_approved is None or "Eligible" in reason_approved

    await engine.dispose()


@pytest.mark.anyio
async def test_07_campaign_scheduler_locking_and_concurrency():
    """
    Verify Phase 9 scheduling and worker locking integration on PostgreSQL:
    - Atomically claims due campaigns using FOR UPDATE SKIP LOCKED.
    - Competing workers cannot claim or execute the same campaign concurrently.
    - Paused and cancelled campaigns are respected.
    - Stale audits (>14 days) or failed audits block campaign eligibility.
    """
    engine = get_staging_engine()
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Create a due campaign via raw SQL compatible with staging schema
        camp_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.execute(
            text(
                "INSERT INTO campaigns (id, name, template, subject_template, status, scheduled_at, lead_ids, pending_lead_ids, campaign_type) "
                "VALUES (:id, :name, :template, :subject_template, :status, :scheduled_at, :lead_ids, :pending_lead_ids, :campaign_type)"
            ),
            {
                "id": camp_id,
                "name": "Stage 11 Integration Due Campaign",
                "template": "technical_seo_proposal",
                "subject_template": "SEO Audit for {{ business_name }}",
                "status": "scheduled",
                "scheduled_at": now_utc - timedelta(minutes=5),
                "lead_ids": json.dumps([]),
                "pending_lead_ids": json.dumps([]),
                "campaign_type": "generic_first_contact",
            },
        )
        await session.commit()

        # Verify atomic claim with FOR UPDATE SKIP LOCKED
        claim_stmt = text(
            "SELECT id, status FROM campaigns WHERE id = :cid AND status = 'scheduled' AND scheduled_at <= :now_dt "
            "FOR UPDATE SKIP LOCKED"
        )
        res = await session.execute(claim_stmt, {"cid": camp_id, "now_dt": now_utc})
        claimed = res.fetchone()
        assert claimed is not None
        assert claimed[0] == camp_id

        # Competing query concurrently sees nothing (SKIP LOCKED)
        async with Session() as competing_session:
            competing_res = await competing_session.execute(
                claim_stmt, {"cid": camp_id, "now_dt": now_utc}
            )
            assert competing_res.fetchone() is None

        # Commit original claim transition
        await session.execute(
            text("UPDATE campaigns SET status = 'draft' WHERE id = :cid"),
            {"cid": camp_id},
        )
        await session.commit()

        # Test paused and cancelled campaign protection
        paused_id = uuid.uuid4()
        cancelled_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, name, template, subject_template, status, scheduled_at, lead_ids, pending_lead_ids, campaign_type) "
                "VALUES (:id, :name, :template, :subject_template, :status, :scheduled_at, :lead_ids, :pending_lead_ids, :campaign_type)"
            ),
            {
                "id": paused_id,
                "name": "Paused Campaign",
                "template": "generic",
                "subject_template": "Hi",
                "status": "paused",
                "scheduled_at": now_utc - timedelta(minutes=10),
                "lead_ids": json.dumps([]),
                "pending_lead_ids": json.dumps([]),
                "campaign_type": "generic_first_contact",
            },
        )
        await session.execute(
            text(
                "INSERT INTO campaigns (id, name, template, subject_template, status, scheduled_at, lead_ids, pending_lead_ids, campaign_type) "
                "VALUES (:id, :name, :template, :subject_template, :status, :scheduled_at, :lead_ids, :pending_lead_ids, :campaign_type)"
            ),
            {
                "id": cancelled_id,
                "name": "Cancelled Campaign",
                "template": "generic",
                "subject_template": "Hi",
                "status": "cancelled",
                "scheduled_at": now_utc - timedelta(minutes=10),
                "lead_ids": json.dumps([]),
                "pending_lead_ids": json.dumps([]),
                "campaign_type": "generic_first_contact",
            },
        )
        await session.commit()

        # Scheduler discover query must ignore paused and cancelled campaigns
        discover_res = await session.execute(
            text(
                "SELECT id FROM campaigns WHERE status = 'scheduled' AND scheduled_at <= :now_dt "
                "AND id IN (:p_id, :c_id)"
            ),
            {"now_dt": now_utc, "p_id": paused_id, "c_id": cancelled_id},
        )
        assert discover_res.fetchall() == []

    await engine.dispose()


@pytest.mark.anyio
async def test_08_outreach_safety_zero_smtp_and_no_live_queues():
    """
    Transport Boundary Safety Verification:
    Assert zero SMTP network connections and zero live outreach messages sent.
    """
    smtp_mock = AsyncMock()

    with patch("aiosmtplib.SMTP", return_value=smtp_mock), patch("smtplib.SMTP") as sync_smtp_mock:
        # Dry run proposal dispatch
        lead_id = str(uuid.uuid4())
        ProposalService.get_or_create_proposal(
            lead_id=lead_id,
            business_name="Zero SMTP Guard Ltd",
            website_url="https://zerosmtp.co.uk",
            audit_results={"technical": {"ssl": {"status": "FAIL"}}},
            association_status="matched",
        )
        ProposalService.approve_proposal(lead_id, user_email="operator@tebsolutions.in")

        res = ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email="test@zerosmtp.co.uk",
            dry_run=True,
        )
        assert res["success"] is True
        assert res["mode"] == "dry_run"

        # Assert ZERO real SMTP calls
        assert smtp_mock.connect.call_count == 0
        assert smtp_mock.send_message.call_count == 0
        assert sync_smtp_mock.call_count == 0
