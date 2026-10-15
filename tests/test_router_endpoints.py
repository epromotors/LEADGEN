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
