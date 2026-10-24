"""
tests/test_ai_search_visibility_gate.py

Comprehensive verification gate test suite for Development Phase 1:
AI Search Visibility Tracking.
"""

import os
import uuid
import datetime
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.routers import ai_search
from app.routers.auth import require_authorized_operator
from app.services.ai_search_service import AiSearchMonitoringService, sanitize_and_validate_citation_url
from app.engines.factor_contract import validate_factor_registry

_test_app = FastAPI()
_test_app.dependency_overrides[require_authorized_operator] = lambda: {"sub": "test_operator@tebsolutions.in"}
_test_app.include_router(ai_search.router)


@pytest.fixture
def client():
    return TestClient(_test_app)


@pytest.fixture
def isolated_ai_service(tmp_path):
    storage_file = str(tmp_path / "runs.json")
    obs_file = str(tmp_path / "observations.json")
    svc = AiSearchMonitoringService(storage_file=storage_file)
    svc.observations_storage_file = obs_file
    svc._observations = []
    return svc


# ─── 1. URL Sanitization and Security ─────────────────────────────────────────

def test_citation_url_sanitization_and_validation():
    # Valid HTTPS URL
    assert sanitize_and_validate_citation_url("https://example.com/page?ref=1") == "https://example.com/page?ref=1"

    # Strips embedded user credentials
    assert sanitize_and_validate_citation_url("https://admin:secret123@example.com/landing") == "https://example.com/landing"

    # Strips sensitive query tokens
    sanitized = sanitize_and_validate_citation_url("https://example.com/search?q=car&token=secret_xyz&api_key=12345")
    assert "token" not in sanitized
    assert "api_key" not in sanitized
    assert "q=car" in sanitized

    # Strips URL fragments
    assert sanitize_and_validate_citation_url("https://example.com/about#team") == "https://example.com/about"

    # Rejection of dangerous schemes
    with pytest.raises(ValueError, match="Only http and https URLs"):
        sanitize_and_validate_citation_url("javascript:alert(1)")

    with pytest.raises(ValueError, match="Only http and https URLs"):
        sanitize_and_validate_citation_url("data:text/html,<script>alert(1)</script>")

    with pytest.raises(ValueError, match="Only http and https URLs"):
        sanitize_and_validate_citation_url("file:///etc/passwd")

    with pytest.raises(ValueError, match="non-empty string"):
        sanitize_and_validate_citation_url("")

    with pytest.raises(ValueError, match="exceeds maximum length"):
        sanitize_and_validate_citation_url("https://example.com/" + "a" * 1005)


# ─── 2. Observation Recording & Field Validation ──────────────────────────────

def test_observation_recording_and_validation(isolated_ai_service):
    # Missing domain -> ValueError
    with pytest.raises(ValueError, match="Target domain is required"):
        isolated_ai_service.record_observation(
            target_domain="",
            search_query="car repair",
            mention_status="mentioned",
        )

    # Missing query -> ValueError
    with pytest.raises(ValueError, match="Search query is required"):
        isolated_ai_service.record_observation(
            target_domain="carmedic.in",
            search_query="",
            mention_status="mentioned",
        )

    # Query length cap (> 500 chars) -> ValueError
    with pytest.raises(ValueError, match="cannot exceed 500 characters"):
        isolated_ai_service.record_observation(
            target_domain="carmedic.in",
            search_query="q" * 505,
            mention_status="mentioned",
        )

    # Invalid mention status -> ValueError
    with pytest.raises(ValueError, match="Invalid mention_status"):
        isolated_ai_service.record_observation(
            target_domain="carmedic.in",
            search_query="car repair",
            mention_status="super_visible",
        )

    # Invalid source type -> ValueError
    with pytest.raises(ValueError, match="Invalid source_type"):
        isolated_ai_service.record_observation(
            target_domain="carmedic.in",
            search_query="car repair",
            mention_status="mentioned",
            source_type="fabricated_crawler",
        )

    # Valid manual observation recording
    record = isolated_ai_service.record_observation(
        target_domain="https://carmedicmotors.in/services",
        search_query="best car mechanic in Lucknow",
        mention_status="mentioned",
        source_type="manual",
        engine="ChatGPT (Search)",
        brand_name="Car Medic Motors",
        citation_urls=["https://carmedicmotors.in/services", "https://carmedicmotors.in/reviews"],
        evidence_snippet="Car Medic Motors is recommended for brake and engine servicing in Gomti Nagar.",
        notes="Verified via human tester",
        created_by="operator@tebsolutions.in",
    )

    assert record["observation_id"] is not None
    assert record["target_domain"] == "carmedicmotors.in"
    assert record["source_type"] == "manual"
    assert record["provider"] == "Manual Observation"
    assert record["engine"] == "ChatGPT (Search)"
    assert record["mention_status"] == "mentioned"
    assert len(record["citation_urls"]) == 2
    assert record["created_by"] == "operator@tebsolutions.in"

    # Ensure persisted in service
    obs_list = isolated_ai_service.get_observations(domain="carmedicmotors.in")
    assert obs_list["total"] == 1
    assert obs_list["observations"][0]["observation_id"] == record["observation_id"]


# ─── 3. Source Honesty & Provider Separation ──────────────────────────────────

def test_source_label_honesty(isolated_ai_service):
    # Manual observation cannot falsely masquerade as live provider without explicit provider parameter
    manual_rec = isolated_ai_service.record_observation(
        target_domain="testgarage.com",
        search_query="mechanic near me",
        mention_status="not_mentioned",
        source_type="manual",
    )
    assert manual_rec["source_type"] == "manual"
    assert "manual" in manual_rec["provider"].lower()

    # Provider observation requires provider name
    with pytest.raises(ValueError, match="Provider name is required for provider_api"):
        isolated_ai_service.record_observation(
            target_domain="testgarage.com",
            search_query="mechanic near me",
            mention_status="mentioned",
            source_type="provider_api",
            provider="",
        )


# ─── 4. Historical Comparison Logic ───────────────────────────────────────────

def test_observation_comparison_logic(isolated_ai_service):
    # Create earlier baseline observation (not mentioned)
    earlier = isolated_ai_service.record_observation(
        target_domain="carmedic.in",
        search_query="brake service in Lucknow",
        mention_status="not_mentioned",
        source_type="manual",
        engine="Google Gemini",
        observed_at="2026-10-01T10:00:00Z",
        citation_urls=[],
    )

    # Create later observation (mentioned with 2 citations)
    later = isolated_ai_service.record_observation(
        target_domain="carmedic.in",
        search_query="brake service in Lucknow",
        mention_status="mentioned",
        source_type="manual",
        engine="Google Gemini",
        observed_at="2026-10-22T10:00:00Z",
        citation_urls=["https://carmedic.in/brakes", "https://carmedic.in/pricing"],
    )

    cmp_res = isolated_ai_service.compare_observations(earlier["observation_id"], later["observation_id"])
    assert cmp_res["comparable"] is True
    assert cmp_res["status_transition"] == "gained_mention"
    assert cmp_res["days_between"] == 21.0
    assert len(cmp_res["citation_changes"]["added_citations"]) == 2
    assert cmp_res["citation_changes"]["net_citation_delta"] == 2

    # Incomparable queries test
    diff_query = isolated_ai_service.record_observation(
        target_domain="carmedic.in",
        search_query="clutch replacement cost in Delhi",
        mention_status="mentioned",
        source_type="manual",
        observed_at="2026-10-23T10:00:00Z",
    )
    incomp_res = isolated_ai_service.compare_observations(earlier["observation_id"], diff_query["observation_id"])
    assert incomp_res["comparable"] is False
    assert len(incomp_res["non_comparable_reasons"]) > 0
    assert "Search queries differ" in incomp_res["non_comparable_reasons"][0]


# ─── 5. API Router Endpoints & Authorization ──────────────────────────────────

def test_api_observations_endpoints(client):
    from app.routers.ai_search import _ai_search_service

    # 1. Create observation via POST /ai-search/observations
    payload = {
        "domain": "lucknowrepairs.in",
        "query": "best suspension repair in Lucknow",
        "mention_status": "mentioned",
        "source_type": "manual",
        "engine": "Google Gemini",
        "citation_urls": ["https://lucknowrepairs.in/suspension"],
        "notes": "Verified from real search prompt",
    }
    create_resp = client.post("/ai-search/observations", json=payload)
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["target_domain"] == "lucknowrepairs.in"
    assert created_data["created_by"] == "test_operator@tebsolutions.in"
    obs_id = created_data["observation_id"]

    # 2. Query observations via GET /ai-search/observations
    list_resp = client.get("/ai-search/observations?domain=lucknowrepairs.in")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert any(o["observation_id"] == obs_id for o in list_data["observations"])

    # 3. Query single observation by ID
    get_resp = client.get(f"/ai-search/observations/{obs_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["observation_id"] == obs_id

    # 4. Coverage summary
    cov_resp = client.get("/ai-search/coverage?domain=lucknowrepairs.in")
    assert cov_resp.status_code == 200
    cov_data = cov_resp.json()
    assert cov_data["total_observations"] >= 1
    assert cov_data["manual_count"] >= 1

    # 5. Missing / 404 observation
    bad_get = client.get(f"/ai-search/observations/{uuid.uuid4()}")
    assert bad_get.status_code == 404


# ─── 6. Unauthenticated Write Rejection (Fail-Closed) ─────────────────────────

def test_api_observations_unauthenticated_rejection():
    # Calling without dependency overrides -> 401 Unauthorized
    unauth_app = FastAPI()
    unauth_app.include_router(ai_search.router)
    unauth_client = TestClient(unauth_app)

    resp = unauth_client.post("/ai-search/observations", json={"domain": "test.com", "query": "test"})
    assert resp.status_code == 401


# ─── 7. Additive Migration Safety Verification ────────────────────────────────

def test_migration_safety_properties():
    migration_path = "backend/migrations/v6_2_4_ai_search_observations.sql"
    assert os.path.exists(migration_path), "Migration v6_2_4_ai_search_observations.sql does not exist."

    with open(migration_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Preflight guard verification
    assert "DO $$" in content
    assert "RAISE EXCEPTION 'MIGRATION ABORTED:" in content
    protected_dbs = [
        "leadgen", "leadgen_test", "leads_db", "linkgen", "offpage",
        "leadgen_release_sandbox", "postgres", "template0", "template1"
    ]
    for db_name in protected_dbs:
        assert f"'{db_name}'" in content, f"Protected DB guard missing {db_name}"

    # Additive and idempotent schema statements
    assert "CREATE TABLE IF NOT EXISTS ai_search_observations" in content
    assert "CREATE INDEX IF NOT EXISTS" in content


# ─── 8. Score Neutrality Check ────────────────────────────────────────────────

def test_ai_search_visibility_score_neutrality():
    """Verify that adding AI search visibility tracking has zero effect on 62 canonical factors."""
    registry = validate_factor_registry()
    assert len(registry) == 62
    for factor_key in registry:
        assert not factor_key.startswith("ai_search_visibility"), f"Registry polluted: {factor_key}"
