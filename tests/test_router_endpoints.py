import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.routers import gsc, ai_search, proposals
from app.services.proposal_service import ProposalService

_test_app = FastAPI()
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


def test_proposals_workflow_api(client):
    # Setup mock proposal in service store
    lead_id = "test-api-lead-999"
    ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Test Garage",
        website_url="https://testgarage.com",
        audit_results={
            "technical": {"ssl": {"status": "FAIL", "message": "No SSL"}},
            "ux": {"cta": {"status": "FAIL"}},
        },
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
    assert appr_resp.json()["approved_by"] == "leadgen_manager@tebsolutions.in"

    # 4. Attempt send after approval -> 200 OK
    send_approved = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": "client@testgarage.com", "dry_run": True},
    )
    assert send_approved.status_code == 200
    assert send_approved.json()["success"] is True
    assert send_approved.json()["mode"] == "dry_run"
