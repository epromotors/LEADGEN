"""
tests/test_gsc_service.py

Unit and mock contract test suite for GSCService (Google Search Console).
Verifies:
1. Disconnected state: when credentials/tokens are absent, returns explicit disconnected status.
2. Never fabricates clicks, impressions, CTR, or position when disconnected.
3. Read-only authorization scope enforcement (webmasters.readonly).
4. Secure token storage: zero full or partial token leakage in any response payload or log.
5. Mocked Search Analytics query parsing: computes total clicks, impressions, avg CTR, weighted position.
6. Handles HTTP 403 forbidden and API error states gracefully.
7. Redirect URI alignment with backend host and port 8001.
8. State nonce lifecycle: exact acceptance, one-time consumption (replay defense), expiry, mismatch rejection.
9. Authorization denial handling.
10. Fernet authenticated-encryption persistence across service restart / reconstruction.
11. Refresh token lifecycle and revocation handling.
12. Prohibition of insecure default secret fallbacks.
13. Dedicated GSC_ENCRYPTION_KEY priority and JWT_SECRET fallback / rotation implications.
14. Corrupted / unreadable encrypted store safe handling.
"""

import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
import pytest
from backend.app.services.gsc_service import (
    GSCService,
    GSC_READONLY_SCOPE,
    DEFAULT_GSC_REDIRECT_URI,
)


def test_gsc_unconfigured_state():
    svc = GSCService(client_id="", client_secret="", storage_path="", encryption_key="test_key_abc")
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
    assert perf["status"] == "unconfigured"
    assert perf["summary"] is None
    assert perf["rows"] == []


def test_gsc_redirect_uri_and_auth_url():
    # Verify default uses port 8001 and /gsc/oauth/callback
    svc_default = GSCService(
        client_id="test_id",
        client_secret="test_secret",
        storage_path="",
        encryption_key="test_key_abc",
    )
    assert svc_default.redirect_uri == DEFAULT_GSC_REDIRECT_URI
    assert "8001" in svc_default.redirect_uri
    assert "/gsc/oauth/callback" in svc_default.redirect_uri

    auth = svc_default.get_authorization_url(property_key="mysite.com")
    assert auth["configured"] is True
    assert "accounts.google.com" in auth["authorization_url"]
    assert "scope=" in auth["authorization_url"]
    assert "webmasters.readonly" in auth["authorization_url"]
    assert "state=" in auth["authorization_url"]
    assert auth["redirect_uri"] == DEFAULT_GSC_REDIRECT_URI


def test_gsc_state_nonce_lifecycle_and_replay_defense():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")

    # 1. Generate state
    nonce = svc.generate_state(property_key="client_domain.com", ttl_seconds=600)
    assert isinstance(nonce, str)
    assert len(nonce) >= 32

    # 2. Validate and consume valid state
    val = svc.validate_and_consume_state(nonce)
    assert val["valid"] is True
    assert val["property_key"] == "client_domain.com"

    # 3. Replay defense: second attempt must be rejected (single-use)
    replay_val = svc.validate_and_consume_state(nonce)
    assert replay_val["valid"] is False
    assert "Invalid, replayed, or unrecognized" in replay_val["reason"]

    # 4. Unknown state rejection
    unknown_val = svc.validate_and_consume_state("totally_random_forged_nonce")
    assert unknown_val["valid"] is False

    # 5. Missing / empty state rejection
    assert svc.validate_and_consume_state(None)["valid"] is False
    assert svc.validate_and_consume_state("")["valid"] is False

    # 6. Expired state rejection
    expired_nonce = svc.generate_state(property_key="exp.com", ttl_seconds=-10)
    exp_val = svc.validate_and_consume_state(expired_nonce)
    assert exp_val["valid"] is False
    assert "expired" in exp_val["reason"].lower()


def test_gsc_oauth_denial_handling():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
    denial = svc.handle_oauth_denial("access_denied", "User declined Search Console permissions")
    assert denial["success"] is False
    assert denial["status"] == "denied"
    assert "access_denied" in denial["error"]
    assert "User declined" in denial["message"]


def test_gsc_token_exchange_mocked():
    raw_secret_token = "ya29.sample_secret_access_token_12345"
    svc = GSCService(client_id="test_id", client_secret="test_secret", storage_path="", encryption_key="test_key_abc")
    state_nonce = svc.generate_state("carmedic.in")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": raw_secret_token,
        "refresh_token": "1//sample_refresh_token_67890",
        "expires_in": 3600,
        "scope": GSC_READONLY_SCOPE,
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        res = svc.exchange_code_for_tokens(
            code="test_code",
            state=state_nonce,
            validate_state=True,
        )
        assert res["success"] is True
        assert res["property_key"] == "carmedic.in"
        assert res["has_token"] is True
        assert res["token_type"] == "Bearer"
        assert res["scope"] == GSC_READONLY_SCOPE
        # Security invariant: zero partial or full token material in API response
        assert "token_masked" not in res
        assert raw_secret_token not in str(res)
        assert "ya29" not in str(res)

        # Verify POST payload
        post_kwargs = mock_post.call_args[1]
        data = post_kwargs["data"]
        assert data["code"] == "test_code"
        assert data["client_id"] == "test_id"
        assert data["client_secret"] == "test_secret"
        assert data["redirect_uri"] == svc.redirect_uri
        assert data["grant_type"] == "authorization_code"


def test_gsc_zero_token_leakage_in_connection_status():
    raw_secret_token = "ya29.sample_secret_access_token_12345"
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
    svc.store_token("prop1", raw_secret_token)

    status = svc.get_connection_status("prop1")
    assert status["connected"] is True
    assert status["status"] == "connected"
    assert status["has_token"] is True
    assert status["token_type"] == "Bearer"
    # Security invariant: NO full or partial token string in status
    assert "token_masked" not in status
    assert raw_secret_token not in str(status)
    assert "ya29" not in str(status)


def test_gsc_insecure_default_secret_prohibition():
    # If encryption key and JWT_SECRET are absent, _get_fernet must raise ValueError
    with patch.dict(os.environ, {"GSC_ENCRYPTION_KEY": "", "JWT_SECRET": ""}, clear=True):
        svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="")
        with pytest.raises(ValueError, match="GSC token encryption requires GSC_ENCRYPTION_KEY or JWT_SECRET"):
            svc._get_fernet()


def test_gsc_encryption_key_priority_and_rotation(tmp_path):
    enc_file = str(tmp_path / "gsc_tokens.enc")
    key_dedicated = "explicit_dedicated_gsc_encryption_key_123"
    key_jwt = "jwt_secret_fallback_key_456"

    # 1. Dedicated key takes precedence over JWT_SECRET
    with patch.dict(os.environ, {"GSC_ENCRYPTION_KEY": key_dedicated, "JWT_SECRET": key_jwt}):
        svc1 = GSCService(client_id="id", client_secret="secret", storage_path=enc_file)
        svc1.store_token("site_a.com", "token_a")
        # Reading with dedicated key succeeds
        svc_read = GSCService(client_id="id", client_secret="secret", storage_path=enc_file, encryption_key=key_dedicated)
        assert svc_read.get_connection_status("site_a.com")["connected"] is True

    # 2. When GSC_ENCRYPTION_KEY is unset, falls back to JWT_SECRET
    enc_file_jwt = str(tmp_path / "gsc_tokens_jwt.enc")
    with patch.dict(os.environ, {"GSC_ENCRYPTION_KEY": "", "JWT_SECRET": key_jwt}):
        svc_jwt = GSCService(client_id="id", client_secret="secret", storage_path=enc_file_jwt)
        svc_jwt.store_token("site_b.com", "token_b")
        # Rotating JWT_SECRET invalidates old ciphertext safely without crashing
        with patch.dict(os.environ, {"GSC_ENCRYPTION_KEY": "", "JWT_SECRET": "new_rotated_jwt_secret_789"}):
            svc_rotated = GSCService(client_id="id", client_secret="secret", storage_path=enc_file_jwt)
            # Store safely starts disconnected instead of leaking or crashing
            assert svc_rotated.get_connection_status("site_b.com")["connected"] is False


def test_gsc_encrypted_persistence_across_process_restart(tmp_path):
    enc_file = str(tmp_path / "gsc_tokens.enc")
    enc_key = "secure_test_encryption_key_abc_12345"

    # Process 1: save tokens
    svc1 = GSCService(
        client_id="id",
        client_secret="secret",
        storage_path=enc_file,
        encryption_key=enc_key,
    )
    svc1.store_token("site_a.com", "access_token_a_123456", "refresh_token_a_987654")
    svc1.store_token("site_b.com", "access_token_b_abcdef", "refresh_token_b_fedcba")

    # Verify on-disk file is ciphertext, not plaintext
    with open(enc_file, "rb") as f:
        file_bytes = f.read()
    assert b"access_token_a" not in file_bytes
    assert b"refresh_token_a" not in file_bytes
    assert file_bytes.startswith(b"gAAAAA")  # Fernet token header

    # Process 2 (simulated restart): create new instance reading same file
    svc2 = GSCService(
        client_id="id",
        client_secret="secret",
        storage_path=enc_file,
        encryption_key=enc_key,
    )
    status_a = svc2.get_connection_status("site_a.com")
    assert status_a["connected"] is True
    assert status_a["status"] == "connected"
    assert status_a["has_token"] is True
    assert status_a["token_type"] == "Bearer"
    assert "token_masked" not in status_a

    status_b = svc2.get_connection_status("site_b.com")
    assert status_b["connected"] is True
    assert status_b["status"] == "connected"

    # Updating site_a does not corrupt site_b
    svc2.store_token("site_a.com", "access_token_a_v2_99999", "refresh_token_a_987654")
    svc3 = GSCService(
        client_id="id",
        client_secret="secret",
        storage_path=enc_file,
        encryption_key=enc_key,
    )
    assert svc3.get_connection_status("site_b.com")["connected"] is True


def test_gsc_corrupted_file_safe_recovery(tmp_path):
    enc_file = str(tmp_path / "gsc_tokens_corrupted.enc")
    # Write garbage corrupted data
    with open(enc_file, "wb") as f:
        f.write(b"gAAAAA_this_is_not_valid_fernet_ciphertext_corrupted_payload")

    # Service must recover safely, not crash, and initialize clean disconnected store
    svc = GSCService(
        client_id="id",
        client_secret="secret",
        storage_path=enc_file,
        encryption_key="test_key_123",
    )
    status = svc.get_connection_status("any_domain.com")
    assert status["connected"] is False
    assert status["status"] == "disconnected"


def test_gsc_token_refresh_and_revocation():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
    # Set token as already expired
    svc._token_store["revoked.com"] = {
        "access_token": "expired_access",
        "refresh_token": "valid_refresh",
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        "status": "active",
    }

    # 1. Successful refresh
    mock_refresh_success = MagicMock()
    mock_refresh_success.status_code = 200
    mock_refresh_success.json.return_value = {
        "access_token": "new_refreshed_access_token",
        "expires_in": 3600,
    }
    with patch("requests.post", return_value=mock_refresh_success):
        assert svc.refresh_token_if_needed("revoked.com") is True
        assert svc._token_store["revoked.com"]["access_token"] == "new_refreshed_access_token"

    # 2. Revoked refresh token (Google returns 400 invalid_grant)
    svc._token_store["revoked.com"]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=10)
    mock_refresh_revoked = MagicMock()
    mock_refresh_revoked.status_code = 400
    with patch("requests.post", return_value=mock_refresh_revoked):
        assert svc.refresh_token_if_needed("revoked.com") is False
        assert svc._token_store["revoked.com"]["status"] == "revoked"

        # Status check reflects revocation
        status = svc.get_connection_status("revoked.com")
        assert status["connected"] is False
        assert status["status"] == "revoked"


def test_gsc_list_properties():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
    svc.store_token("default", "mock_token")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "siteEntry": [
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://example.com/", "permissionLevel": "siteFullUser"},
        ]
    }
    with patch("requests.get", return_value=mock_resp):
        res = svc.list_properties("default")
        assert res["success"] is True
        assert len(res["properties"]) == 2
        assert res["properties"][0]["site_url"] == "sc-domain:example.com"
        assert res["properties"][0]["permission_level"] == "siteOwner"


def test_gsc_search_performance_parsing_mocked():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
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
        assert summary["average_ctr"] == 0.08
        assert summary["average_position"] == 3.36
        assert len(perf["rows"]) == 2

        called_headers = mock_post.call_args[1]["headers"]
        assert called_headers["Authorization"] == "Bearer mock_token"


def test_gsc_forbidden_and_error_handling():
    svc = GSCService(client_id="id", client_secret="secret", storage_path="", encryption_key="test_key_abc")
    svc.store_token("https://forbidden.com", "mock_token")

    mock_resp = MagicMock()
    mock_resp.status_code = 403

    with patch("requests.post", return_value=mock_resp):
        perf = svc.get_search_performance("https://forbidden.com", property_key="https://forbidden.com")
        assert perf["connected"] is False
        assert perf["status"] == "forbidden"
        assert "Permission denied" in perf["reason"]
        assert perf["summary"] is None
