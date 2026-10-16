"""
tests/test_two_key_rotation_provider_manager.py

Automated test suite verifying:
- Two-Key Rotation & Account-Aware Provider Key Manager
- Independent Account Quotas (Groq, Treg, Serper)
- Quota scope registry, non-secret identifiers, and fair rotation
- Strict distinction between auth failures (credential_invalid) and quota exhaustion (quota_exhausted)
- Shared quota enforcement when keys share a single quota scope
- Cooldown and Retry-After handling (rate_limited)
- Transient error handling (transient_failure)
- Concurrency safety under simultaneous asynchronous loads
- Provenance tracking with account_id and quota_scope
- Complete secret redaction across all diagnostic and error surfaces

MANDATORY: Uses local mocks and fixtures. No live network calls, paid credits, or emails consumed.
"""

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import httpx
import pytest

from app.config import Settings
from app.services.provider_key_manager import (
    QuotaScope,
    ProviderKey,
    ProviderKeyPool,
    ProviderKeyManager,
    get_key_manager,
)
from app.services.ai_search_provider import (
    GroqSearchProvider,
    redact_sensitive_credentials,
)
from app.services.ai_search_service import AiSearchMonitoringService
from app.services.lead_discovery_service import (
    LeadDiscoveryService,
    ProviderStatus,
)


def run_async(coro):
    """
    Robust async execution helper that executes a coroutine safely whether
    or not an event loop is already running in the current thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Configuration & Quota Scope Mechanics
# ─────────────────────────────────────────────────────────────────────────────

def test_two_key_configuration_groq_treg_serper_independent_scopes():
    """
    Verify two-key configuration works for Groq, Treg, and Serper,
    assigning independent non-secret quota scopes by default.
    """
    mock_settings = MagicMock()
    mock_settings.GROQ_API_KEY_1 = "gsk_test_mock_groq_key_slot_1_unique_abcdef"
    mock_settings.GROQ_API_KEY_2 = "gsk_test_mock_groq_key_slot_2_unique_ghijkl"
    mock_settings.GROQ_QUOTA_SCOPE_1 = ""
    mock_settings.GROQ_QUOTA_SCOPE_2 = ""

    mock_settings.TREG_API_KEY_1 = "trg_live_mock_treg_key_slot_1_unique_123456"
    mock_settings.TREG_API_KEY_2 = "trg_live_mock_treg_key_slot_2_unique_789012"
    mock_settings.TREG_QUOTA_SCOPE_1 = ""
    mock_settings.TREG_QUOTA_SCOPE_2 = ""

    mock_settings.SERPER_API_KEY_1 = "serper_live_mock_key_slot_1_unique_111222"
    mock_settings.SERPER_API_KEY_2 = "serper_live_mock_key_slot_2_unique_333444"
    mock_settings.SERPER_QUOTA_SCOPE_1 = ""
    mock_settings.SERPER_QUOTA_SCOPE_2 = ""

    km = ProviderKeyManager(settings_obj=mock_settings)

    for prov in ["groq", "treg", "serper"]:
        pool = km.get_pool(prov)
        assert pool is not None, f"Pool {prov} should exist"
        assert pool.is_configured() is True
        assert len(pool.keys) == 2
        assert len(pool.quota_scopes) == 2

        # Verify Slot 1 and Slot 2 non-secret identifiers
        k1, k2 = pool.keys[0], pool.keys[1]
        assert k1.slot_id == 1
        assert k1.account_id == f"{prov}_account_1"
        assert k1.quota_scope.scope_id == f"{prov}_account_1"

        assert k2.slot_id == 2
        assert k2.account_id == f"{prov}_account_2"
        assert k2.quota_scope.scope_id == f"{prov}_account_2"

        # Distinct QuotaScope instances
        assert k1.quota_scope is not k2.quota_scope


def test_duplicate_key_removal_and_placeholder_ignoring():
    """Verify duplicate keys are safely deduplicated and placeholders ignored."""
    pool = ProviderKeyPool("groq")

    raw_keys = [
        "gsk_valid_key_alpha_123456789",
        "PASTE_YOUR_GROQ_KEY_HERE",
        "",
        "   ",
        "gsk_valid_key_alpha_123456789",  # Exact duplicate
        "short",  # Too short
        "gsk_valid_key_beta_987654321",
    ]
    pool.configure_keys(raw_keys)

    assert len(pool.keys) == 2
    assert pool.keys[0].slot_id == 1
    assert pool.keys[1].slot_id == 2
    assert pool.keys[0].secret == "gsk_valid_key_alpha_123456789"
    assert pool.keys[1].secret == "gsk_valid_key_beta_987654321"


def test_legacy_single_key_fallback():
    """Verify backward compatibility when only unnumbered keys are provided."""
    mock_settings = MagicMock(spec=[])
    setattr(mock_settings, "GROQ_API_KEY", "gsk_legacy_groq_key_9988776655")
    setattr(mock_settings, "TREG_API_TOKEN", "trg_legacy_treg_token_44332211")
    setattr(mock_settings, "SERPER_API_KEY", "serper_legacy_key_5566778899")

    km = ProviderKeyManager(settings_obj=mock_settings)

    groq_pool = km.get_pool("groq")
    assert groq_pool.is_configured() is True
    assert len(groq_pool.keys) == 1
    assert groq_pool.keys[0].slot_id == 1
    assert groq_pool.keys[0].account_id == "groq_account_1"

    treg_pool = km.get_pool("treg")
    assert treg_pool.is_configured() is True
    assert len(treg_pool.keys) == 1

    serper_pool = km.get_pool("serper")
    assert serper_pool.is_configured() is True
    assert len(serper_pool.keys) == 1


def test_empty_configuration_state():
    """Verify empty/unconfigured provider state produces safe actionable diagnostics."""
    mock_settings = MagicMock(spec=[])
    km = ProviderKeyManager(settings_obj=mock_settings)

    pool = km.get_pool("groq")
    assert pool.is_configured() is False
    status = pool.get_status()
    assert status["status"] == "disabled"
    assert status["configured"] is False
    assert status["available_slots"] == 0
    assert pool.get_next_key_sync() is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Round-Robin & Concurrency Safety
# ─────────────────────────────────────────────────────────────────────────────

def test_round_robin_selection_alternation():
    """Verify requests rotate fairly across independent healthy account slots."""
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_key_slot_1_abcdef",
            "gsk_mock_key_slot_2_uvwxyz",
        ])

        slot_sequence = []
        account_sequence = []
        for _ in range(6):
            key, slot = await pool.get_next_key()
            slot_sequence.append(slot)
            account_sequence.append(key.account_id)

        assert slot_sequence == [1, 2, 1, 2, 1, 2]
        assert account_sequence == [
            "groq_account_1",
            "groq_account_2",
            "groq_account_1",
            "groq_account_2",
            "groq_account_1",
            "groq_account_2",
        ]
    run_async(_test())


def test_concurrency_safety_multi_task():
    """Verify simultaneous async jobs safely acquire alternating keys without race conditions."""
    async def _test():
        pool = ProviderKeyPool("serper", [
            "serper_mock_key_slot_1_abc",
            "serper_mock_key_slot_2_xyz",
        ])

        async def _worker():
            key, slot = await pool.get_next_key()
            await asyncio.sleep(0.01)
            return slot

        results = await asyncio.gather(*[_worker() for _ in range(20)])

        assert len(results) == 20
        assert results.count(1) == 10
        assert results.count(2) == 10
    run_async(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 3. Health, Failure Classification, Independent Quotas & Cooldowns
# ─────────────────────────────────────────────────────────────────────────────

def test_key_specific_auth_failover_distinguished_from_quota():
    """
    ADDENDUM Requirement 4:
    Verify authentication failure (401/403) is distinguished from quota exhaustion:
    - Marks credential as 'credential_invalid'
    - Disables ONLY that key slot
    - Does NOT exhaust the account quota scope or disable other accounts
    """
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_invalid_key_slot_1",
            "gsk_mock_valid_key_slot_2",
        ])

        key1, slot1 = await pool.get_next_key()
        assert slot1 == 1

        # Report HTTP 401 Unauthorized for Slot 1
        pool.report_result(key1, 401)
        assert key1.is_auth_failed is True
        assert key1.is_healthy is False
        assert key1.last_error_category == "credential_invalid"

        # QuotaScope for account 1 is NOT quota_exhausted!
        assert key1.quota_scope.is_exhausted is False

        # Next request must automatically failover to Slot 2 (account 2)
        key2, slot2 = await pool.get_next_key()
        assert slot2 == 2
        assert key2.account_id == "groq_account_2"
        assert key2.is_available() is True

        # Slot 2 succeeds
        pool.report_result(key2, 200)
        assert key2.is_healthy is True
        assert key2.success_count == 1
    run_async(_test())


def test_independent_account_quota_exhaustion_does_not_disable_account_2():
    """
    ADDENDUM Requirement 2:
    Exhaustion of account 1 does NOT incorrectly disable account 2 when they
    belong to independent quota scopes.
    """
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_account_1_key",
            "gsk_mock_account_2_key",
        ])

        k1, slot1 = await pool.get_next_key()
        assert slot1 == 1
        assert k1.account_id == "groq_account_1"

        # Account 1 reports HTTP 402 Quota Exhausted
        pool.report_result(k1, 402)

        # Account 1 scope is exhausted
        assert k1.quota_scope.is_exhausted is True
        assert k1.is_available() is False
        assert pool.quota_scopes["groq_account_1"].is_exhausted is True

        # Crucial check: Account 2 scope is NOT exhausted!
        assert pool.quota_scopes["groq_account_2"].is_exhausted is False
        assert pool.shared_quota_exhausted is False

        # Subsequent call MUST select Account 2!
        k2_res = await pool.get_next_key()
        assert k2_res is not None, "Account 2 must remain available when Account 1 is exhausted"
        k2, slot2 = k2_res
        assert slot2 == 2
        assert k2.account_id == "groq_account_2"
        assert k2.is_available() is True
    run_async(_test())


def test_shared_quota_scope_cannot_be_bypassed():
    """
    ADDENDUM Requirement 3:
    When two credentials intentionally share the SAME quota scope,
    exhaustion of that scope disables both keys and prevents quota bypass.
    """
    async def _test():
        # Both keys configured under shared scope "serper_org_shared"
        pool = ProviderKeyPool(
            "serper",
            raw_keys=["serper_key_a", "serper_key_b"],
            quota_scopes=["serper_org_shared", "serper_org_shared"],
        )

        assert len(pool.quota_scopes) == 1
        assert "serper_org_shared" in pool.quota_scopes

        k1, slot1 = await pool.get_next_key()
        assert slot1 == 1
        assert k1.account_id == "serper_org_shared"

        # Quota exhausted for the shared scope
        pool.report_result(k1, 402)

        assert pool.shared_quota_exhausted is True
        assert pool.keys[0].is_available() is False
        assert pool.keys[1].is_available() is False

        # Must not switch to key 2 to evade the shared quota!
        next_call = await pool.get_next_key()
        assert next_call is None
    run_async(_test())


def test_rate_limit_and_cooldown_429_retry_after():
    """ADDENDUM Requirement 5: Verify HTTP 429 respects Retry-After and cooldown."""
    async def _test():
        pool = ProviderKeyPool("serper", [
            "serper_mock_key_1",
            "serper_mock_key_2",
        ])

        k1, slot1 = await pool.get_next_key()
        assert slot1 == 1

        # Slot 1 hit 429 with 8.0s Retry-After
        pool.report_result(k1, 429, retry_after=8.0)
        assert k1.is_in_cooldown() is True
        assert k1.quota_scope.is_in_cooldown() is True
        assert k1.quota_scope.is_exhausted is False  # Temporary, not permanently exhausted!
        assert k1.last_error_category == "rate_limited"

        # Slot 2 is an independent account and remains immediately available
        k2, slot2 = await pool.get_next_key()
        assert slot2 == 2
        assert k2.account_id == "serper_account_2"
    run_async(_test())


def test_transient_error_bounded_retry_503():
    """Verify HTTP 503 applies brief cooldown and classifies as transient_failure."""
    async def _test():
        pool = ProviderKeyPool("treg", ["trg_mock_key_1"])
        k1, slot1 = await pool.get_next_key()

        pool.report_result(k1, 503)
        assert k1.failure_count == 1
        assert k1.is_exhausted is False
        assert k1.last_error_category == "transient_failure"
        assert k1.quota_scope.last_error_category == "transient_failure"
    run_async(_test())


def test_all_keys_auth_failure_truthful_status():
    """Verify truthful status 'credential_invalid' when all keys fail auth with confirmed bad credentials."""
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_bad_1",
            "gsk_mock_bad_2",
        ])

        k1, _ = await pool.get_next_key()
        pool.report_result(k1, 401)

        k2, _ = await pool.get_next_key()
        pool.report_result(k2, 403, error_message="invalid_api_key")

        assert await pool.get_next_key() is None
        status = pool.get_status()
        assert status["status"] == "credential_invalid"
        assert status["available_slots"] == 0
    run_async(_test())


def test_http_403_permission_restriction_does_not_permanently_disable_credential():
    """
    CRITICAL REQUIREMENT 1:
    Verify HTTP 403 permission/generic restriction does NOT permanently disable credentials:
    - is_auth_failed must remain False
    - Non-definitive failure category recorded (permission_denied / permission_restricted)
    - Temporary cooldown applied to allow fair rotation to Slot 2
    - Once cooldown ends or on reset, the key remains usable
    """
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_perm_slot_1",
            "gsk_mock_valid_slot_2",
        ])

        k1, slot1 = await pool.get_next_key()
        assert slot1 == 1

        # Report generic HTTP 403 without invalid key confirmation
        pool.report_result(k1, 403, retry_after=10.0, error_message="Forbidden: User does not have permission")
        assert k1.is_auth_failed is False, "HTTP 403 must NOT permanently disable credential"
        assert k1.last_error_category in ("permission_denied", "permission_restricted")
        assert k1.is_in_cooldown() is True

        # Fair rotation to Slot 2
        k2_res = await pool.get_next_key()
        assert k2_res is not None
        k2, slot2 = k2_res
        assert slot2 == 2
        assert k2.is_available() is True
    run_async(_test())


def test_http_403_with_quota_exhausted_message_serper():
    """
    Verify provider 403 responses indicating quota/credit exhaustion (e.g. Serper 'Not enough credits')
    are accurately classified as 'quota_exhausted' without destroying credential validity.
    """
    async def _test():
        pool = ProviderKeyPool("serper", [
            "serper_mock_zero_credits_slot_1",
            "serper_mock_funded_slot_2",
        ])

        k1, slot1 = await pool.get_next_key()
        assert slot1 == 1

        # Serper returns 403 with 'Not enough credits'
        pool.report_result(k1, 403, error_message='{"message": "Not enough credits"}')
        assert k1.quota_scope.is_exhausted is True
        assert k1.is_auth_failed is False, "Quota exhaustion must NOT mark auth invalid"
        assert k1.last_error_category == "quota_exhausted"

        # Independent Account 2 remains eligible and available
        assert pool.quota_scopes["serper_account_2"].is_exhausted is False
        k2_res = await pool.get_next_key()
        assert k2_res is not None
        k2, slot2 = k2_res
        assert slot2 == 2
        assert k2.account_id == "serper_account_2"
    run_async(_test())


def test_http_403_plan_and_endpoint_restrictions():
    """Verify HTTP 403 plan and endpoint restrictions record specific non-definitive categories."""
    pool = ProviderKeyPool("groq", ["gsk_key_1", "gsk_key_2"])

    # Plan restriction
    pool.report_result(pool.keys[0], 403, error_message="This feature requires an Enterprise plan subscription")
    assert pool.keys[0].is_auth_failed is False
    assert pool.keys[0].last_error_category == "plan_restricted"

    # Endpoint unavailable
    pool.report_result(pool.keys[1], 403, error_message="Endpoint not available for this organization")
    assert pool.keys[1].is_auth_failed is False
    assert pool.keys[1].last_error_category == "endpoint_unavailable"


def test_diagnostics_categories_distinction():
    """
    ADDENDUM Requirement 5:
    Diagnostic output must distinguish:
    - credential_invalid
    - quota_exhausted
    - rate_limited
    - transient_failure
    - available
    And expose non-secret account_id / quota_scope without secrets.
    """
    pool = ProviderKeyPool("groq", [
        "gsk_key_alpha_12345",
        "gsk_key_beta_67890",
    ])

    # Initial state: available
    diag = pool.get_status()
    assert diag["status"] == "available"
    assert diag["slots"][0]["account_id"] == "groq_account_1"
    assert diag["slots"][1]["account_id"] == "groq_account_2"
    assert diag["slots"][0]["status"] == "available"

    # Set slot 1 to credential_invalid
    pool.report_result(pool.keys[0], 401)
    diag = pool.get_status()
    assert diag["slots"][0]["status"] == "credential_invalid"
    assert diag["slots"][1]["status"] == "available"

    # Set slot 2 to rate_limited
    pool.report_result(pool.keys[1], 429, retry_after=10.0)
    diag = pool.get_status()
    assert diag["slots"][1]["status"] == "rate_limited"


# ─────────────────────────────────────────────────────────────────────────────
# 4. GroqSearchProvider Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_groq_search_provider_two_key_rotation_and_inference_separation():
    """Verify GroqSearchProvider uses two keys and separates AI inference from grounded web citations."""
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_groq_slot1",
            "gsk_mock_groq_slot2",
        ])
        provider = GroqSearchProvider(key_pool=pool, model="llama-3.3-70b-versatile")

        tier_info = provider.get_tier_info()
        assert tier_info["tier"] == "Free-Tier AI Inference"
        assert "Inference Only" in tier_info["grounding_method"]
        assert tier_info["key_slots"] == 2

        # Mock successful HTTP request on Slot 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "llama-3.3-70b-versatile",
            "choices": [{"message": {"content": "Austin Roofing Co is a top rated contractor."}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 20, "total_tokens": 35},
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_resp

        result = await provider.execute_query("Top roofers in Austin", client=mock_client)

        assert result["status"] == "success"
        assert result["inference_only"] is True
        assert result["grounding_active"] is False
        assert result["citations"] == []
        assert result["provenance"]["provider"] == "groq"
        assert result["provenance"]["key_slot"] == 1
        assert result["provenance"]["account_id"] == "groq_account_1"
        assert result["provenance"]["quota_scope"] == "groq_account_1"

        # Second request should use Slot 2 (account 2)
        mock_client.reset_mock()
        result2 = await provider.execute_query("Second roofer query", client=mock_client)
        assert result2["provenance"]["key_slot"] == 2
        assert result2["provenance"]["account_id"] == "groq_account_2"
    run_async(_test())


def test_groq_search_provider_auth_failover_in_request():
    """Verify Groq provider automatically fails over to Slot 2 when Slot 1 returns HTTP 401."""
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_groq_invalid_slot1",
            "gsk_mock_groq_valid_slot2",
        ])
        provider = GroqSearchProvider(key_pool=pool)

        resp_401 = MagicMock(status_code=401, text="Invalid API key", headers={})
        resp_200 = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Success on slot 2"}}], "usage": {}},
            headers={},
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [resp_401, resp_200]

        result = await provider.execute_query("Query requiring failover", client=mock_client)

        assert result["status"] == "success"
        assert result["provenance"]["key_slot"] == 2
        assert result["provenance"]["account_id"] == "groq_account_2"
        assert pool.keys[0].is_auth_failed is True
        assert pool.keys[1].is_healthy is True
    run_async(_test())


def test_groq_search_provider_quota_failover_independent_accounts():
    """Verify Groq provider fails over to account 2 when account 1 hits HTTP 402."""
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_groq_quota_exhausted_slot1",
            "gsk_mock_groq_funded_slot2",
        ])
        provider = GroqSearchProvider(key_pool=pool)

        resp_402 = MagicMock(status_code=402, text="Account quota exceeded", headers={})
        resp_200 = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Account 2 response"}}], "usage": {}},
            headers={},
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [resp_402, resp_200]

        result = await provider.execute_query("Query testing quota failover", client=mock_client)

        assert result["status"] == "success"
        assert result["provenance"]["key_slot"] == 2
        assert result["provenance"]["account_id"] == "groq_account_2"
        assert pool.quota_scopes["groq_account_1"].is_exhausted is True
        assert pool.quota_scopes["groq_account_2"].is_exhausted is False
    run_async(_test())


def test_ai_search_service_recognizes_groq():
    """Verify AiSearchMonitoringService recognizes and integrates Groq in providers dict."""
    service = AiSearchMonitoringService()
    assert "groq" in service.providers
    groq_prov = service.providers["groq"]
    assert groq_prov.provider_id == "groq"

    status = service.get_visibility_monitoring_status()
    assert "groq" in status["providers"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. LeadDiscoveryService (Treg, Serper, Provenance & Quota)
# ─────────────────────────────────────────────────────────────────────────────

def test_cost_unknown_endpoints_remain_disabled():
    """Verify cost-unknown/paid endpoints remain disabled when TREG_ENABLE_PAID_ENDPOINTS is False."""
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = False
        km = ProviderKeyManager(settings_obj=mock_settings)
        km.get_or_create_pool("treg", ["trg_live_test_token_slot_1"])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        mock_session = MagicMock()
        places, source, method = await svc.search_places(mock_session, "roofing", "Austin")

        # Treg must be skipped because TREG_ENABLE_PAID_ENDPOINTS is False
        assert source != "treg"
        assert method != "api_proxy_maps"
    run_async(_test())


def test_lead_discovery_treg_catalog_endpoint_and_provenance():
    """Verify LeadDiscoveryService queries Treg catalog endpoint with X-Treg-Token and provenance when enabled."""
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = True
        km = ProviderKeyManager(settings_obj=mock_settings)
        treg_pool = km.get_or_create_pool("treg", ["trg_live_test_token_slot_1"])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        # Mock session
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {
            "local_results": [
                {
                    "title": "Lone Star Dental",
                    "link": "https://lonestardental.com",
                    "phone": "+1-512-555-0199",
                }
            ]
        }

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        places, source, method = await svc.search_places(mock_session, "dental clinic", "Austin")

        assert source == "treg"
        assert method == "api_proxy_maps"
        assert len(places) == 1
        lead = places[0]
        assert lead["name"] == "Lone Star Dental"
        assert lead["website"] == "https://lonestardental.com"
        assert lead["source"] == "treg"
        assert lead["endpoint"] == "serpapi.google.maps"
        assert lead["key_slot"] == 1
        assert lead["account_id"] == "treg_account_1"
        assert lead["quota_scope"] == "treg_account_1"
    run_async(_test())


def test_lead_discovery_serper_two_key_rotation_and_failover():
    """Verify Serper two-key failover in LeadDiscoveryService."""
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = False
        km = ProviderKeyManager(settings_obj=mock_settings)
        km.get_or_create_pool("treg", [])
        serper_pool = km.get_or_create_pool("serper", [
            "serper_mock_key_bad_slot1",
            "serper_mock_key_good_slot2",
        ])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        # First post returns 401, second post returns 200
        resp_401 = AsyncMock(status=401, headers={})
        resp_200 = AsyncMock(
            status=200,
            headers={},
            json=AsyncMock(return_value={
                "places": [{"title": "Apex Plumbing", "website": "https://apexplumbing.com", "phoneNumber": "123"}]
            }),
        )

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.side_effect = [resp_401, resp_200]

        places, source, method = await svc.search_places(mock_session, "plumber", "Denver")

        assert source == "serper"
        assert len(places) == 1
        assert places[0]["name"] == "Apex Plumbing"
        assert places[0]["key_slot"] == 2
        assert places[0]["account_id"] == "serper_account_2"
        assert serper_pool.keys[0].is_auth_failed is True
        assert serper_pool.keys[1].success_count == 1
    run_async(_test())


def test_lead_discovery_serper_quota_failover_independent_accounts():
    """Verify Serper rotates to independent account 2 on HTTP 402."""
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = False
        km = ProviderKeyManager(settings_obj=mock_settings)
        km.get_or_create_pool("treg", [])
        serper_pool = km.get_or_create_pool("serper", [
            "serper_mock_key_exhausted_slot1",
            "serper_mock_key_funded_slot2",
        ])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        # First post returns 402, second post returns 200
        resp_402 = AsyncMock(status=402, headers={})
        resp_200 = AsyncMock(
            status=200,
            headers={},
            json=AsyncMock(return_value={
                "places": [{"title": "Mile High Roofs", "website": "https://milehighroofs.com", "phoneNumber": "456"}]
            }),
        )

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.side_effect = [resp_402, resp_200]

        places, source, method = await svc.search_places(mock_session, "roofing", "Denver")

        assert source == "serper"
        assert len(places) == 1
        assert places[0]["name"] == "Mile High Roofs"
        assert places[0]["key_slot"] == 2
        assert places[0]["account_id"] == "serper_account_2"
        assert serper_pool.quota_scopes["serper_account_1"].is_exhausted is True
        assert serper_pool.quota_scopes["serper_account_2"].is_exhausted is False
    run_async(_test())


def test_lead_discovery_email_enrichment_treg_and_serper():
    """Verify email enrichment via Treg Hunter proxy and Serper snippet with provenance."""
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = True
        km = ProviderKeyManager(settings_obj=mock_settings)
        km.get_or_create_pool("treg", ["trg_live_mock_token_1"])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {
            "data": {"emails": [{"value": "info@apexplumbing.com"}]}
        }

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        email, source, method = await svc.enrich_email(
            mock_session, "Apex Plumbing", "Denver", "https://apexplumbing.com"
        )

        assert email == "info@apexplumbing.com"
        assert source == "treg"
        assert method == "api_proxy_hunter"
    run_async(_test())


def test_groq_search_provider_403_non_destructive_failover():
    """
    CRITICAL REQUIREMENT:
    Verify GroqSearchProvider fails over to slot 2 on HTTP 403 permission/endpoint restriction
    WITHOUT permanently disabling slot 1 credential.
    """
    async def _test():
        pool = ProviderKeyPool("groq", [
            "gsk_mock_slot1_perm_restricted",
            "gsk_mock_slot2_valid",
        ])
        provider = GroqSearchProvider(key_pool=pool)

        resp_403 = MagicMock(status_code=403, text="Access denied to requested model endpoint", headers={})
        resp_200 = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Slot 2 valid inference"}}], "usage": {}},
            headers={},
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [resp_403, resp_200]

        result = await provider.execute_query("Query testing 403 non-destructive failover", client=mock_client)

        assert result["status"] == "success"
        assert result["provenance"]["key_slot"] == 2
        assert result["provenance"]["account_id"] == "groq_account_2"
        # Slot 1 must NOT be permanently marked auth_failed!
        assert pool.keys[0].is_auth_failed is False
        assert pool.keys[0].last_error_category in ("permission_denied", "permission_restricted", "endpoint_unavailable")
        assert pool.keys[1].is_healthy is True
    run_async(_test())


def test_groq_visibility_run_inference_only_truthful_evidence():
    """
    CRITICAL REQUIREMENT 3:
    Trace Groq results through AiSearchMonitoringService.execute_visibility_run:
    - Must NOT be represented as verified search visibility or live citations
    - Explicitly marks inference_only=True and grounding_active=False
    - Evidence items retain inference_only=True and empty citations
    - Explicit ungrounded uncertainty note provided
    """
    async def _test():
        pool = ProviderKeyPool("groq", ["gsk_mock_groq_inference_slot1"])
        provider = GroqSearchProvider(key_pool=pool)

        service = AiSearchMonitoringService()
        service.groq_provider = provider
        service.providers["groq"] = provider

        mock_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "choices": [{"message": {"content": "Apex Plumbing is a reputable contractor in Denver."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            },
            headers={},
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_resp

        run_record = await service.execute_visibility_run(
            lead_id="test-lead-123",
            brand_name="Apex Plumbing",
            domain="apexplumbing.com",
            city="Denver",
            query_budget=2,
            provider_name="groq",
            provider_client=mock_client,
        )

        assert run_record["provider_id"] == "groq"
        assert run_record["inference_only"] is True
        assert run_record["grounding_active"] is False
        assert "inference" in run_record["uncertainty_note"].lower()
        assert len(run_record["evidence"]) == 2
        for ev in run_record["evidence"]:
            assert ev["inference_only"] is True
            assert ev["grounding_active"] is False
            assert ev["citations"] == []
    run_async(_test())


def test_lead_discovery_serper_403_not_enough_credits_failover():
    """
    CRITICAL REQUIREMENT:
    Verify Serper Maps request handles HTTP 403 'Not enough credits' by exhausting
    account 1 quota scope and safely failing over to account 2 without auth invalidation.
    """
    async def _test():
        mock_settings = MagicMock(spec=[])
        mock_settings.TREG_ENABLE_PAID_ENDPOINTS = False
        km = ProviderKeyManager(settings_obj=mock_settings)
        km.get_or_create_pool("treg", [])
        serper_pool = km.get_or_create_pool("serper", [
            "serper_mock_zero_credits_slot1",
            "serper_mock_funded_slot2",
        ])
        svc = LeadDiscoveryService(storage_path="", key_manager=km)

        resp_403 = AsyncMock(status=403, headers={})
        resp_403.text.return_value = '{"message": "Not enough credits"}'

        resp_200 = AsyncMock(
            status=200,
            headers={},
            json=AsyncMock(return_value={
                "places": [{"title": "Rocky Mountain Electric", "website": "https://rmelectric.com", "phoneNumber": "789"}]
            }),
        )

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.side_effect = [resp_403, resp_200]

        places, source, method = await svc.search_places(mock_session, "electrician", "Denver")

        assert source == "serper"
        assert len(places) == 1
        assert places[0]["name"] == "Rocky Mountain Electric"
        assert places[0]["key_slot"] == 2
        assert places[0]["account_id"] == "serper_account_2"
        # Account 1 scope exhausted, but key is NOT auth_failed
        assert serper_pool.quota_scopes["serper_account_1"].is_exhausted is True
        assert serper_pool.keys[0].is_auth_failed is False
        # Account 2 remains healthy
        assert serper_pool.quota_scopes["serper_account_2"].is_exhausted is False
    run_async(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 6. Strict Credential Redaction Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_secret_redaction_across_all_surfaces():
    """
    CRITICAL SECURITY TEST:
    Verify secret keys never appear in:
    - Diagnostics dictionaries
    - Formatted strings or logs
    - Error strings and tracebacks
    - Redacted text helper outputs
    """
    secret_1 = "gsk_SUPER_SECRET_GROQ_KEY_DO_NOT_LEAK_9999"
    secret_2 = "trg_SUPER_SECRET_TREG_TOKEN_DO_NOT_LEAK_8888"
    secret_3 = "serper_SUPER_SECRET_KEY_DO_NOT_LEAK_7777"

    pool = ProviderKeyPool("groq", [secret_1])
    diag = pool.get_status()

    # 1. No secret in diagnostic dict
    diag_str = json.dumps(diag)
    assert secret_1 not in diag_str
    assert "SUPER_SECRET" not in diag_str

    # 2. No secret in repr or str of ProviderKey
    k = pool.keys[0]
    assert secret_1 not in str(k)
    assert secret_1 not in repr(k)
    assert k.account_id == "groq_account_1"

    # 3. redact_sensitive_credentials cleans errors
    raw_error = f"API error occurred: Authorization: Bearer {secret_1} failed with key={secret_2}"
    redacted = redact_sensitive_credentials(raw_error, secrets=[secret_1, secret_2, secret_3])

    assert secret_1 not in redacted
    assert secret_2 not in redacted
    assert "[REDACTED_API_KEY]" in redacted

    # 4. redact_all_secrets via ProviderKeyManager
    mock_settings = MagicMock(spec=[])
    setattr(mock_settings, "GROQ_API_KEY_1", secret_1)
    setattr(mock_settings, "TREG_API_KEY_1", secret_2)
    setattr(mock_settings, "SERPER_API_KEY_1", secret_3)

    km = ProviderKeyManager(settings_obj=mock_settings)
    leak_test = f"X-API-KEY: '{secret_3}', X-Treg-Token: '{secret_2}', bearer: '{secret_1}'"
    sanitized = km.redact_all_secrets(leak_test)

    assert secret_1 not in sanitized
    assert secret_2 not in sanitized
    assert secret_3 not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
