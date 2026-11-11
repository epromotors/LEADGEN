import os
import uuid
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.routers import audits
from app.database import get_db
from app.models import Lead, Audit, AuditStatus
from app.routers.auth import require_authorized_operator

_test_app = FastAPI()
_test_app.dependency_overrides[require_authorized_operator] = lambda: {"sub": "test_operator"}
_test_app.include_router(audits.router)


@pytest.fixture
def client():
    return TestClient(_test_app)


@pytest.fixture(autouse=True)
def reset_batch_state():
    """Reset audits router batch state before and after each test."""
    audits._BATCH_STATUS = "idle"
    audits._BATCH_RUNNING = False
    audits._BATCH_CANCELLED = False
    audits._BATCH_QUEUE = None
    audits._BATCH_WORKER_TASKS = []
    audits._BATCH_SESSION_ID = None
    audits._BATCH_STATS = {
        "total": 0,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": 0,
    }
    event = audits._get_batch_event()
    event.set()
    yield
    audits._BATCH_STATUS = "idle"
    audits._BATCH_RUNNING = False
    audits._BATCH_CANCELLED = False
    audits._BATCH_QUEUE = None
    audits._BATCH_WORKER_TASKS = []
    audits._BATCH_SESSION_ID = None


def test_batch_status_idle(client):
    resp = client.get("/audits/batch-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch_running"] is False
    assert data["batch_status"] == "idle"
    assert data["batch_paused"] is False
    assert data["batch_progress"]["total"] == 0


def test_pause_and_resume_on_idle_fail(client):
    mock_db = AsyncMock()
    no_session = MagicMock()
    no_session.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=no_session)
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    # Pausing when idle should return 400
    try:
        p_resp = client.post("/audits/batch/pause")
        assert p_resp.status_code == 400
        assert "No active batch audit" in p_resp.json()["detail"]

        # Resuming when idle with no durable interrupted session should return 400
        r_resp = client.post("/audits/batch/resume")
        assert r_resp.status_code == 400
        assert "No paused or interrupted" in r_resp.json()["detail"]
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_pause_resume_stop_lifecycle(client):
    # Simulate a running batch
    audits._BATCH_STATUS = "running"
    audits._BATCH_RUNNING = True
    audits._BATCH_STATS = {
        "total": 10,
        "completed": 3,
        "succeeded": 3,
        "failed": 0,
        "remaining": 7,
    }

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        # 1. Pause batch
        pause_resp = client.post("/audits/batch/pause")
        assert pause_resp.status_code == 200
        p_data = pause_resp.json()
        assert p_data["status"] == "paused"
        assert audits._BATCH_STATUS == "paused"
        assert audits._BATCH_RUNNING is True
        assert not audits._get_batch_event().is_set()

        # Check /audits/batch-status shows paused
        status_resp = client.get("/audits/batch-status")
        assert status_resp.status_code == 200
        assert status_resp.json()["batch_status"] == "paused"
        assert status_resp.json()["batch_paused"] is True
        assert status_resp.json()["batch_running"] is True

        # Idempotent pause
        rep_pause = client.post("/audits/batch/pause")
        assert rep_pause.status_code == 200
        assert rep_pause.json()["message"] == "Batch audit is already paused."

        # 2. Resume batch
        resume_resp = client.post("/audits/batch/resume")
        assert resume_resp.status_code == 200
        r_data = resume_resp.json()
        assert r_data["status"] == "running"
        assert audits._BATCH_STATUS == "running"
        assert audits._get_batch_event().is_set()

        # Idempotent resume
        rep_resume = client.post("/audits/batch/resume")
        assert rep_resume.status_code == 200
        assert rep_resume.json()["message"] == "Batch audit is already running."

        # 3. Stop batch
        stop_resp = client.post("/audits/batch/stop")
        assert stop_resp.status_code == 200
        assert stop_resp.json()["status"] == "idle"
        assert audits._BATCH_STATUS == "idle"
        assert audits._BATCH_RUNNING is False
        assert audits._BATCH_CANCELLED is True
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_trigger_all_with_fixed_limit(client):
    # Generate mock leads
    leads = [
        Lead(
            id=uuid.uuid4(),
            business_name=f"Lead {i}",
            website=f"https://lead{i}.com",
            status="new",
        )
        for i in range(15)
    ]

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = leads
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value = mock_scalars
    mock_exec_res.scalar_one_or_none.return_value = None  # No existing audit
    mock_db.execute = AsyncMock(return_value=mock_exec_res)

    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch.object(audits, "run_batched", new_callable=AsyncMock) as mock_batched:
            # Trigger with limit = 5
            resp = client.post("/audits/trigger-all?mode=new_only&limit=5")
            assert resp.status_code == 200
            data = resp.json()
            assert data["triggered"] == 5
            assert data["limit"] == 5
            assert data["mode"] == "new_only"

            # Check that background task was called with exactly 5 lead IDs
            assert mock_batched.call_count == 1
            passed_ids = mock_batched.call_args[0][0]
            assert len(passed_ids) == 5
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_audit_scope_predicates_are_history_based_and_distinguish_retry_modes():
    from sqlalchemy.dialects import postgresql

    scopes = audits._audit_scope_predicates()
    never_audited_sql = str(
        select(Lead).where(scopes["never_audited"]).compile(dialect=postgresql.dialect())
    )
    retry_failed_query = select(Lead).where(scopes["retryable_failed"]).compile(dialect=postgresql.dialect())
    retry_failed_sql = str(retry_failed_query)

    assert "NOT (EXISTS" in never_audited_sql
    assert "audits.lead_id = leads.id" in never_audited_sql
    assert "auditstatus" not in never_audited_sql
    assert "audits.status" in retry_failed_sql
    assert AuditStatus.failed in retry_failed_query.params.values()


def test_retry_failed_reuses_the_existing_audit_record(client):
    lead = Lead(id=uuid.uuid4(), business_name="Retry lead", website="https://retry.example", status="new")
    failed_audit = Audit(lead_id=lead.id, status=AuditStatus.failed, audit_lifecycle="FAILED")

    no_active_session = MagicMock()
    no_active_session.scalar_one_or_none.return_value = None
    lead_result = MagicMock()
    lead_result.scalars.return_value.all.return_value = [lead]
    audit_result = MagicMock()
    audit_result.scalar_one_or_none.return_value = failed_audit

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[no_active_session, lead_result, audit_result])
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch.object(audits, "run_batched", new_callable=AsyncMock) as mock_batched:
            resp = client.post("/audits/trigger-all?mode=retry_failed")

        assert resp.status_code == 200
        assert resp.json()["triggered"] == 1
        assert failed_audit.status == AuditStatus.pending
        assert failed_audit.audit_lifecycle == "PENDING"
        assert failed_audit.error_message is None
        assert failed_audit not in [call.args[0] for call in mock_db.add.call_args_list]
        mock_batched.assert_awaited_once()
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_trigger_all_rejected_when_batch_paused(client):
    audits._BATCH_STATUS = "paused"
    audits._BATCH_RUNNING = True

    mock_db = AsyncMock()
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        resp = client.post("/audits/trigger-all?mode=new_only")
        assert resp.status_code == 409
        assert "currently paused" in resp.json()["detail"]
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_resume_interrupted_durable_batch_requeues_only_remaining_leads(client):
    session_id = uuid.uuid4()
    remaining_id = uuid.uuid4()
    in_flight_id = uuid.uuid4()
    batch = audits.AuditBatchSession(
        id=session_id,
        status="interrupted",
        mode="new_only",
        remaining_lead_ids=[str(remaining_id)],
        in_flight_lead_ids=[str(in_flight_id)],
        total=5,
        completed=3,
        succeeded=3,
        failed=0,
        concurrency=2,
        delay_secs=0.5,
    )
    batch_result = MagicMock()
    batch_result.scalar_one_or_none.return_value = batch
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[batch_result, MagicMock()])
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch.object(audits, "run_batched", new_callable=AsyncMock) as run_batched:
            resp = client.post("/audits/batch/resume")

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert batch.status == "running"
        assert batch.remaining_lead_ids == [str(remaining_id), str(in_flight_id)]
        assert batch.in_flight_lead_ids == []
        run_batched.assert_awaited_once_with(
            [str(remaining_id), str(in_flight_id)], 2, 0.5, str(session_id)
        )
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_run_batched_pause_resume_workers():
    """Verify run_batched halts worker task consumption when paused and resumes when set."""
    lead_ids = [str(uuid.uuid4()) for _ in range(6)]
    audited_leads = []

    async def fake_audit(lid, target_keywords=None):
        audited_leads.append(lid)
        await asyncio.sleep(0.01)

    with patch.object(audits, "run_audit", side_effect=fake_audit):
        task = asyncio.create_task(audits.run_batched(lead_ids, concurrency=2, delay_between=0.01))

        # Let 2 run
        await asyncio.sleep(0.05)
        # Pause
        audits._BATCH_STATUS = "paused"
        event = audits._get_batch_event()
        event.clear()

        count_at_pause = len(audited_leads)
        assert count_at_pause >= 1

        # Wait while paused - no new leads should be processed
        await asyncio.sleep(0.08)
        assert len(audited_leads) == count_at_pause

        # Resume
        audits._BATCH_STATUS = "running"
        event.set()

        # Wait for batch to finish
        await task

        assert len(audited_leads) == 6
        assert audits._BATCH_STATUS == "idle"
        assert audits._BATCH_RUNNING is False


@pytest.mark.anyio
async def test_run_batched_persists_claims_and_results_for_a_durable_session():
    lead_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    claimed = []
    recorded = []

    async def fake_claim(session_id, lead_id):
        claimed.append((session_id, lead_id))

    async def fake_audit(lead_id, target_keywords=None):
        return None

    async def fake_record(session_id, lead_id, succeeded):
        recorded.append((session_id, lead_id, succeeded))

    with patch.object(audits, "_claim_session_lead", side_effect=fake_claim), \
         patch.object(audits, "run_audit", side_effect=fake_audit), \
         patch.object(audits, "_record_session_result", side_effect=fake_record), \
         patch.object(audits, "_finish_session", new_callable=AsyncMock) as finish:
        await audits.run_batched(lead_ids, concurrency=1, delay_between=0, session_id="00000000-0000-0000-0000-000000000001")

    assert [lead_id for _, lead_id in claimed] == lead_ids
    assert [lead_id for _, lead_id, succeeded in recorded if succeeded] == lead_ids
    finish.assert_awaited_once_with("00000000-0000-0000-0000-000000000001", False)


def test_durable_batch_session_model_and_migration_are_present():
    from pathlib import Path
    from app.models import AuditBatchSession

    fields = set(AuditBatchSession.__table__.columns.keys())
    assert {"status", "remaining_lead_ids", "in_flight_lead_ids", "total", "completed", "succeeded", "failed"} <= fields

    migration = Path("backend/migrations/v7_1_0_audit_batch_sessions.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS audit_batch_sessions" in migration
    assert "ix_audit_batch_sessions_status" in migration


def test_audit_mode_modal_uses_audit_history_counts_and_explicit_retry_mode():
    from pathlib import Path

    source = Path("frontend/src/components/lead/AuditModeModal.jsx").read_text(encoding="utf-8-sig")
    assert "stats?.never_audited" in source
    assert "stats?.retryable_failed" in source
    assert "key: 'retry_failed'" in source
    assert "stats?.new ?? 0" not in source


def test_startup_recovery_marks_legacy_status_and_lifecycle_failed_together():
    from pathlib import Path

    main_source = Path("backend/app/main.py").read_text(encoding="utf-8-sig")
    assert "status=AuditStatus.failed," in main_source
    assert 'audit_lifecycle="FAILED"' in main_source


def test_stop_batch_cancels_worker_tasks_and_resets_inflight(client):
    audits._BATCH_STATUS = "running"
    audits._BATCH_RUNNING = True
    audits._BATCH_CANCELLED = False

    fake_task = MagicMock()
    fake_task.done.return_value = False
    audits._BATCH_WORKER_TASKS = [fake_task]

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock()
    _test_app.dependency_overrides[get_db] = lambda: mock_db

    try:
        resp = client.post("/audits/batch/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"
        assert audits.is_batch_cancelled() is True
        fake_task.cancel.assert_called_once()
    finally:
        _test_app.dependency_overrides.pop(get_db, None)


def test_null_byte_sanitization_for_postgres_models():
    from app.models import _sanitize_null_bytes

    raw_candidates = [
        {
            "email": "test\x00@example.com",
            "context": "Context with null \u0000 byte inside: ...)Rb{mr\"7\u0353\u00128\u000fq\u0002,y\u0012\u0000...",
        }
    ]
    cleaned = _sanitize_null_bytes(raw_candidates)
    assert "\x00" not in cleaned[0]["email"]
    assert "\u0000" not in cleaned[0]["context"]
    assert cleaned[0]["email"] == "test@example.com"


def test_lead_discovery_service_null_byte_sanitization():
    from app.services.lead_discovery_service import sanitize_null_bytes, extract_email_candidates_with_context

    html_with_nul = (
        "<html><body>Contact us: <a href='mailto:info@domain.com'>info@domain.com</a> "
        "binary gibberish \x00 \u0000 text</body></html>"
    )
    candidates = extract_email_candidates_with_context(
        html_with_nul, website="https://domain.com", business_name="Domain Co"
    )
    assert len(candidates) > 0
    for cand in candidates:
        assert "\x00" not in cand["context"]
        assert "\u0000" not in cand["context"]


