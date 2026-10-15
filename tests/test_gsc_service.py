"""
tests/test_gsc_service.py

Unit and mock contract test suite for GSCService (Google Search Console).
Verifies:
1. Disconnected state: when credentials/tokens are absent, returns explicit disconnected status.
2. Never fabricates clicks, impressions, CTR, or position when disconnected.
3. Read-only authorization scope enforcement (webmasters.readonly).
4. Secure token storage: tokens are masked and not leaked.
5. Mocked Search Analytics query parsing: computes total clicks, impressions, avg CTR, weighted position.
6. Handles HTTP 403 forbidden and API error states gracefully.
"""

from unittest.mock import MagicMock, patch
import pytest
from backend.app.services.gsc_service import GSCService, GSC_READONLY_SCOPE


def test_gsc_unconfigured_state():
    # Service created without credentials
    svc = GSCService(client_id="", client_secret="")
    assert not svc.is_configured()

    auth = svc.get_authorization_url()
    assert auth["configured"] is False
    assert auth["authorization_url"] is None

    status = svc.get_connection_status()
    assert status["connected"] is False
    assert status["status"] == "unconfigured"

    # Must NOT fabricate performance data
    perf = svc.get_search_performance("https://example.com")
    assert perf["connected"] is False
    assert perf["status"] == "disconnected"
    assert perf["summary"] is None
    assert perf["rows"] == []


def test_gsc_authorization_url_generation():
    svc = GSCService(
        client_id="test_client_id.apps.googleusercontent.com",
        client_secret="test_secret",
        redirect_uri="https://app.example.com/oauth/callback",
    )
    assert svc.is_configured()

    auth = svc.get_authorization_url(state="test_state_123")
    assert auth["configured"] is True
    assert "accounts.google.com" in auth["authorization_url"]
    assert "scope=" in auth["authorization_url"]
    assert "webmasters.readonly" in auth["authorization_url"]
    assert "test_state_123" in auth["authorization_url"]


def test_gsc_secure_token_handling():
    svc = GSCService(client_id="id", client_secret="secret")
    svc.store_token("prop1", "ya29.sample_secret_token_123456789")

    status = svc.get_connection_status("prop1")
    assert status["connected"] is True
    assert status["status"] == "connected"
    # Token must be masked, not full string
    assert status["token_masked"].startswith("ya29.sam")
    assert "123456789" not in status["token_masked"]


def test_gsc_search_performance_parsing_mocked():
    svc = GSCService(client_id="id", client_secret="secret")
    svc.store_token("https://mysite.com", "mock_token")

    mock_response_data = {
        "rows": [
            {
                "keys": ["car repair near me", "https://mysite.com/services"],
                "clicks": 150,
                "impressions": 1500,
                "ctr": 0.10,
                "position": 2.4,
            },
            {
                "keys": ["brake inspection cost", "https://mysite.com/brakes"],
                "clicks": 50,
                "impressions": 1000,
                "ctr": 0.05,
                "position": 4.8,
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("requests.post", return_value=mock_resp) as mock_post:
        perf = svc.get_search_performance("https://mysite.com", property_key="https://mysite.com")

        assert perf["connected"] is True
        assert perf["status"] == "active"
        summary = perf["summary"]
        assert summary["total_clicks"] == 200
        assert summary["total_impressions"] == 2500
        assert summary["average_ctr"] == 0.08  # 200 / 2500
        # Weighted pos: (2.4*1500 + 4.8*1000)/2500 = (3600 + 4800)/2500 = 8400/2500 = 3.36
        assert summary["average_position"] == 3.36
        assert len(perf["rows"]) == 2

        # Check call headers
        called_headers = mock_post.call_args[1]["headers"]
        assert called_headers["Authorization"] == "Bearer mock_token"


def test_gsc_forbidden_and_error_handling():
    svc = GSCService(client_id="id", client_secret="secret")
    svc.store_token("https://forbidden.com", "mock_token")

    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch("requests.post", return_value=mock_resp):
        perf = svc.get_search_performance("https://forbidden.com", property_key="https://forbidden.com")
        assert perf["connected"] is False
        assert perf["status"] == "forbidden"
        assert "Permission denied" in perf["reason"]
        assert perf["summary"] is None
