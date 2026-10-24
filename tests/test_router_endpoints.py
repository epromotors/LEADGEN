import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.routers import gsc, ai_search, proposals
from app.services.proposal_service import ProposalService

from app.routers.auth import require_authorized_operator

_test_app = FastAPI()
_test_app.dependency_overrides[require_authorized_operator] = lambda: {"sub": "test_operator"}
_test_app.include_router(gsc.router)
_test_app.include_router(ai_search.router)
_test_app.include_router(proposals.router)


@pytest.fixture
def client():
    return TestClient(_test_app)


def test_gsc_status_endpoint(client):
    resp = client.get("/gsc/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert data["status"] in ["unconfigured", "disconnected"]


def test_gsc_auth_url_and_callback_lifecycle(client):
    from unittest.mock import MagicMock, patch
    from app.routers.gsc import _gsc_service

    # Ensure service is configured with mock credentials for endpoint test
    _gsc_service.client_id = "test_client_id"
    _gsc_service.client_secret = "test_client_secret"

    # 1. Get auth URL
    auth_resp = client.get("/gsc/auth-url?property_key=testdomain.in")
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    assert auth_data["configured"] is True
    assert "accounts.google.com" in auth_data["authorization_url"]
    state_nonce = auth_data["state"]

    # 2. Callback missing state -> 400
    bad_cb1 = client.get("/gsc/oauth/callback?code=mock_code")
    assert bad_cb1.status_code == 400
    assert "Missing required OAuth state parameter" in bad_cb1.json()["detail"]

    # 3. Callback with invalid / unknown state -> 400
    bad_cb2 = client.get("/gsc/oauth/callback?code=mock_code&state=forged_state_nonce")
    assert bad_cb2.status_code == 400
    assert "Invalid, replayed, or unrecognized" in bad_cb2.json()["detail"]

    # 4. User denial callback -> 400
    denial_cb = client.get("/gsc/oauth/callback?error=access_denied&error_description=Consent+rejected")
    assert denial_cb.status_code == 400
    assert "Consent rejected" in denial_cb.json()["detail"]

    # 5. Successful callback with valid state & mocked Google token exchange -> 200
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "ya29.sample_secret_access_token_12345",
        "refresh_token": "1//sample_refresh_token",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
    }

    with patch("requests.post", return_value=mock_resp):
        success_cb = client.get(f"/gsc/oauth/callback?code=mock_auth_code&state={state_nonce}")
        assert success_cb.status_code == 200
        cb_data = success_cb.json()
        assert cb_data["success"] is True
        assert cb_data["property_key"] == "testdomain.in"
        assert cb_data["has_token"] is True
        assert cb_data["token_type"] == "Bearer"
        assert "token_masked" not in cb_data
        assert "ya29" not in str(cb_data)
        assert "12345" not in str(cb_data)

    # 6. Replay attack: calling callback again with same state -> 400
    replay_cb = client.get(f"/gsc/oauth/callback?code=mock_auth_code&state={state_nonce}")
    assert replay_cb.status_code == 400
    assert "Invalid, replayed, or unrecognized" in replay_cb.json()["detail"]


def test_ai_search_status_endpoint(client):
    resp = client.get("/ai-search/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["monitoring_enabled"] is False
    assert data["status"] == "unconfigured"


def test_ai_search_query_corpus_endpoint(client):
    payload = {
        "brand_name": "Car Medic Motors",
        "domain": "carmedicmotors.in",
        "city": "Lucknow",
        "services": ["Brake Service", "Engine Diagnostics"],
    }
    resp = client.post("/ai-search/query-corpus", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 4
    queries = [q["query"] for q in data["queries"]]
    assert any("Car Medic Motors" in q for q in queries)
    assert any("Lucknow" in q for q in queries)


def test_ai_search_run_endpoint_lifecycle(client):
    from unittest.mock import patch, AsyncMock
    from app.routers.ai_search import _ai_search_service

    # 1. When unconfigured, POST /ai-search/run returns 400 Bad Request
    _ai_search_service.gemini_provider.api_key = ""
    _ai_search_service.openrouter_provider.api_key = ""
    _ai_search_service.perplexity_provider.api_key = ""
    _ai_search_service.provider.api_key = ""

    bad_resp = client.post("/ai-search/run", json={"domain": "carmedicmotors.in", "brand_name": "Car Medic"})
    assert bad_resp.status_code == 400
    assert "not configured" in bad_resp.json()["detail"]

    # 1b. When requesting specific unconfigured provider, returns 400 Bad Request
    bad_prov_resp = client.post("/ai-search/run", json={
        "domain": "carmedicmotors.in",
        "brand_name": "Car Medic",
        "provider": "openrouter",
    })
    assert bad_prov_resp.status_code == 400
    assert "OPENROUTER" in bad_prov_resp.json()["detail"] or "not configured" in bad_prov_resp.json()["detail"]

    # 2. When configured, POST /ai-search/run executes and records history
    _ai_search_service.gemini_provider.api_key = "test_gemini_secret_key"
    mock_run_res = {
        "run_id": "test-run-endpoint-uuid",
        "lead_id": "lead-endpoint-123",
        "target_domain": "carmedicmotors.in",
        "brand_name": "Car Medic Motors",
        "provider": "Google Gemini API",
        "model": "gemini-2.0-flash",
        "status": "completed",
        "queries_attempted": 2,
        "queries_succeeded": 2,
        "queries_failed": 0,
        "brand_mentions_count": 2,
        "brand_mention_rate": 1.0,
        "domain_citations_count": 1,
        "citation_rate": 0.5,
        "share_of_voice": 1.0,
        "evidence": [
            {
                "query": "What is Car Medic Motors?",
                "intent": "brand_direct",
                "status": "success",
                "brand_mentioned": True,
                "domain_cited": True,
                "citations": [{"url": "https://carmedicmotors.in", "domain": "carmedicmotors.in", "title": "Home"}],
            }
        ],
        "uncertainty_note": "Observations recorded via Google Gemini API.",
    }

    with patch.object(_ai_search_service, "execute_visibility_run", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_run_res

        run_resp = client.post("/ai-search/run", json={
            "domain": "carmedicmotors.in",
            "brand_name": "Car Medic Motors",
            "query_budget": 2,
            "provider": "gemini",
        })
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["run_id"] == "test-run-endpoint-uuid"
        assert run_data["status"] == "completed"
        assert run_data["brand_mention_rate"] == 1.0
        assert run_data["citation_rate"] == 0.5
        # Redaction: secret key must never be in returned JSON
        assert "test_gemini_secret_key" not in str(run_data)

    # 3. History and Latest retrieval
    _ai_search_service._runs_by_lead["lead-endpoint-123"] = [mock_run_res]

    hist_resp = client.get("/ai-search/history/lead-endpoint-123")
    assert hist_resp.status_code == 200
    assert hist_resp.json()["total_runs"] == 1

    latest_resp = client.get("/ai-search/latest/lead-endpoint-123")
    assert latest_resp.status_code == 200
    assert latest_resp.json()["run_id"] == "test-run-endpoint-uuid"

    # Reset API keys to unconfigured
    _ai_search_service.gemini_provider.api_key = ""
    _ai_search_service.openrouter_provider.api_key = ""
    _ai_search_service.perplexity_provider.api_key = ""
    _ai_search_service.provider.api_key = ""


def test_ai_search_duplicate_run_conflict(client):
    from unittest.mock import patch, AsyncMock
    from app.routers.ai_search import _ai_search_service

    _ai_search_service.gemini_provider.api_key = "test_key"
    with patch.object(_ai_search_service, "execute_visibility_run", new_callable=AsyncMock) as mock_exec:
        mock_exec.side_effect = RuntimeError("A visibility check is already running for carmedicmotors.in.")

        conflict_resp = client.post("/ai-search/run", json={
            "domain": "carmedicmotors.in",
            "brand_name": "Car Medic Motors",
            "provider": "gemini",
        })
        assert conflict_resp.status_code == 409
        assert "already running" in conflict_resp.json()["detail"]

    _ai_search_service.gemini_provider.api_key = ""


def test_proposals_workflow_api(client):
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.database import get_db
    from app.models import Lead, Audit, AuditStatus

    lead_uuid = uuid.uuid4()
    lead_id = str(lead_uuid)

    mock_lead = Lead(
        id=lead_uuid,
        business_name="Test Garage",
        website="https://testgarage.com",
        email="client@testgarage.com",
        email_verification_status="valid",
        email_business_association_status="matched",
        is_quarantined=False,
    )
    mock_audit = Audit(
        id=uuid.uuid4(),
        lead_id=lead_uuid,
        status=AuditStatus.done,
        audit_results={
            "technical": {"ssl": {"status": "FAIL", "message": "No SSL"}},
            "ux": {"cta": {"status": "FAIL"}},
        },
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_lead)
        mock_audit_res = MagicMock()
        mock_audit_res.scalar_one_or_none.return_value = mock_audit
        mock_db.execute = AsyncMock(return_value=mock_audit_res)
        yield mock_db

    _test_app.dependency_overrides[get_db] = override_get_db

    try:
        # Setup mock proposal in service store
        ProposalService.get_or_create_proposal(
            lead_id=lead_id,
            business_name="Test Garage",
            website_url="https://testgarage.com",
            audit_results={
                "technical": {"ssl": {"status": "FAIL", "message": "No SSL"}},
                "ux": {"cta": {"status": "FAIL"}},
            },
            association_status="matched",
        )

        # 1. Attempt send without approval -> 403 Forbidden
        send_resp = client.post(
            f"/proposals/{lead_id}/send",
            json={"target_email": "client@testgarage.com", "dry_run": True},
        )
        assert send_resp.status_code == 403
        err_detail = send_resp.json()["detail"]
        assert err_detail["error"] == "approval_required"

        # 2. Edit proposal draft
        edit_resp = client.put(
            f"/proposals/{lead_id}",
            json={"subject": "Revised Subject Proposal"},
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["subject"] == "Revised Subject Proposal"

        # 3. Approve proposal
        appr_resp = client.post(
            f"/proposals/{lead_id}/approve",
            json={"user_email": "leadgen_manager@tebsolutions.in"},
        )
        assert appr_resp.status_code == 200
        assert appr_resp.json()["approved"] is True

        # 4. Attempt send after approval -> 200 OK
        send_approved = client.post(
            f"/proposals/{lead_id}/send",
            json={"target_email": "client@testgarage.com", "dry_run": True},
        )
        assert send_approved.status_code == 200
        assert send_approved.json()["success"] is True
        assert send_approved.json()["mode"] == "dry_run"
    finally:
        _test_app.dependency_overrides.pop(get_db, None)
