"""
tests/test_gsc_verification_gate.py

Comprehensive verification gate test suite for Google Search Console (GSC) integration.
Verifies all backend endpoints, OAuth lifecycle, security guarantees, and score neutrality.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")
os.environ.setdefault("GSC_ENCRYPTION_KEY", "test_encryption_key_32_bytes_abcdef123456")

from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import gsc
from app.services.gsc_service import GSCService, GSC_READONLY_SCOPE, DEFAULT_GSC_REDIRECT_URI
from app.engines.factor_contract import validate_factor_registry

_test_app = FastAPI()
_test_app.include_router(gsc.router)


@pytest.fixture
def client():
    return TestClient(_test_app)


def test_gsc_status_unconfigured(client):
    from app.routers.gsc import _gsc_service
    orig_id = _gsc_service.client_id
    orig_sec = _gsc_service.client_secret
    try:
        _gsc_service.client_id = ""
        _gsc_service.client_secret = ""
        resp = client.get("/gsc/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["status"] == "unconfigured"
        assert "not configured" in data["reason"].lower() or "requires" in data["reason"].lower()
    finally:
        _gsc_service.client_id = orig_id
        _gsc_service.client_secret = orig_sec


def test_gsc_auth_url_lifecycle(client):
    from app.routers.gsc import _gsc_service
    _gsc_service.client_id = "test_client_id_123"
    _gsc_service.client_secret = "test_client_secret_456"

    # 1. Successful auth URL generation
    resp = client.get("/gsc/auth-url?property_key=mysite.com")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert "authorization_url" in data
    assert "accounts.google.com" in data["authorization_url"]
    assert "scope=" in data["authorization_url"]
    assert "webmasters.readonly" in data["authorization_url"]
    state_nonce = data["state"]
    assert len(state_nonce) >= 32

    # 2. Callback missing state parameter -> 400
    bad_cb = client.get("/gsc/oauth/callback?code=mock_code")
    assert bad_cb.status_code == 400
    assert "Missing required OAuth state parameter" in bad_cb.json()["detail"]

    # 3. Callback with forged / unknown state -> 400
    bad_cb2 = client.get("/gsc/oauth/callback?code=mock_code&state=unknown_forged_state")
    assert bad_cb2.status_code == 400
    assert "Invalid, replayed, or unrecognized" in bad_cb2.json()["detail"]

    # 4. User denial callback -> 400
    denial_cb = client.get("/gsc/oauth/callback?error=access_denied&error_description=User+denied+access")
    assert denial_cb.status_code == 400
    assert "User denied access" in denial_cb.json()["detail"]

    # 5. Successful callback with valid state & mocked token exchange
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "access_token": "ya29.test_super_secret_access_token_12345",
        "refresh_token": "1//test_refresh_token_67890",
        "expires_in": 3600,
        "scope": GSC_READONLY_SCOPE,
    }

    with patch("requests.post", return_value=mock_post_resp):
        success_cb = client.get(f"/gsc/oauth/callback?code=mock_auth_code&state={state_nonce}")
        assert success_cb.status_code == 200
        res_data = success_cb.json()
        assert res_data["success"] is True
        assert res_data["property_key"] == "mysite.com"
        assert res_data["has_token"] is True
        # Ensure zero token leakage
        assert "ya29" not in str(res_data)
        assert "67890" not in str(res_data)

    # 6. Replay attempt using same consumed state -> 400
    replay_cb = client.get(f"/gsc/oauth/callback?code=mock_auth_code&state={state_nonce}")
    assert replay_cb.status_code == 400


def test_gsc_post_oauth_exchange(client):
    from app.routers.gsc import _gsc_service
    _gsc_service.client_id = "test_client_id"
    _gsc_service.client_secret = "test_client_secret"

    state_nonce = _gsc_service.generate_state("exchange_test.com")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "ya29.exchange_token_abc",
        "refresh_token": "1//exchange_refresh_def",
        "expires_in": 3600,
        "scope": GSC_READONLY_SCOPE,
    }

    with patch("requests.post", return_value=mock_resp):
        resp = client.post(
            "/gsc/oauth/exchange",
            json={"code": "valid_exchange_code", "property_key": "exchange_test.com", "state": state_nonce},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "ya29" not in str(data)


def test_gsc_properties_endpoint(client):
    from app.routers.gsc import _gsc_service
    _gsc_service.client_id = "test_client_id"
    _gsc_service.client_secret = "test_client_secret"

    # 1. Disconnected property -> 400 error
    resp_disconn = client.get("/gsc/properties?property_key=nonexistent_prop")
    assert resp_disconn.status_code == 400
    assert "not connected" in resp_disconn.json()["detail"].lower()

    # 2. Connected property with mocked Google sites API
    _gsc_service.store_token("connected_prop", "valid_access_token")

    mock_sites_resp = MagicMock()
    mock_sites_resp.status_code = 200
    mock_sites_resp.json.return_value = {
        "siteEntry": [
            {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"},
        ]
    }

    with patch("requests.get", return_value=mock_sites_resp):
        resp_conn = client.get("/gsc/properties?property_key=connected_prop")
        assert resp_conn.status_code == 200
        data = resp_conn.json()
        assert data["success"] is True
        assert len(data["properties"]) == 2
        assert data["properties"][0]["site_url"] == "https://example.com/"


def test_gsc_performance_endpoint_and_validation(client):
    from app.routers.gsc import _gsc_service

    # 1. Validation on days parameter (must be 1 <= days <= 90)
    bad_days_low = client.get("/gsc/performance?site_url=https://example.com&days=0")
    assert bad_days_low.status_code == 422

    bad_days_high = client.get("/gsc/performance?site_url=https://example.com&days=91")
    assert bad_days_high.status_code == 422

    # 2. Performance when disconnected -> honest 200 with connected=False, never fabricated
    resp_disconn = client.get("/gsc/performance?site_url=https://example.com&days=28&property_key=not_connected")
    assert resp_disconn.status_code == 200
    data_disconn = resp_disconn.json()
    assert data_disconn["connected"] is False
    assert data_disconn["summary"] is None
    assert data_disconn["rows"] == []

    # 3. Performance with mocked Google Search Analytics API
    _gsc_service.store_token("perf_prop", "valid_access_token")

    mock_analytics_resp = MagicMock()
    mock_analytics_resp.status_code = 200
    mock_analytics_resp.json.return_value = {
        "rows": [
            {"keys": ["car repair near me", "https://example.com/repair"], "clicks": 25, "impressions": 500, "ctr": 0.05, "position": 3.2},
            {"keys": ["brake pad change", "https://example.com/brakes"], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 4.1},
        ]
    }

    with patch("requests.post", return_value=mock_analytics_resp):
        resp_perf = client.get("/gsc/performance?site_url=https://example.com&days=28&property_key=perf_prop")
        assert resp_perf.status_code == 200
        data_perf = resp_perf.json()
        assert data_perf["connected"] is True
        assert data_perf["status"] == "active"
        assert data_perf["summary"]["total_clicks"] == 35
        assert data_perf["summary"]["total_impressions"] == 700
        assert len(data_perf["rows"]) == 2
        assert data_perf["rows"][0]["query"] == "car repair near me"

    # 4. 403 Forbidden handling
    mock_forbidden = MagicMock()
    mock_forbidden.status_code = 403
    with patch("requests.post", return_value=mock_forbidden):
        resp_forbid = client.get("/gsc/performance?site_url=https://example.com&days=28&property_key=perf_prop")
        assert resp_forbid.status_code == 200
        data_forbid = resp_forbid.json()
        assert data_forbid["connected"] is False
        assert data_forbid["status"] == "forbidden"
        assert "Permission denied" in data_forbid["reason"]


def test_gsc_score_neutrality():
    """Ensure GSC integration is 100% score-neutral with zero modification to 62 canonical factors."""
    registry = validate_factor_registry()
    assert len(registry) == 62
    for factor_key in registry:
        assert not factor_key.startswith("gsc"), f"Canonical registry corrupted by non-standard factor: {factor_key}"
