"""
tests/test_api_usage_and_quotas.py

Authoritative Tests for API Usage, Credit Visibility & Audit Engine Provenance:
- Provider state and configuration detection (Serper, Treg, Hunter, Groq, OpenRouter, Gemini)
- Strict secret redaction (no API keys, tokens, or passwords leaked)
- Non-secret identifiers for slots and quota scopes (e.g. 'groq_account_1', 'serper_account_2')
- Providers without programmatic balance APIs (clear "Balance unavailable through API" notice + portal links)
- Programmatic balance retrieval (e.g. OpenRouter key endpoint)
- Audit engine provenance: Explicit distinction of Local HTTP crawler, Local Playwright,
  Local synthetic Lighthouse, and external audit APIs ($0 cost, 0 paid API calls)
- Router endpoint verification for GET /api/system/api-usage
"""

import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.api_usage_service import (
    ApiUsageService,
    _safe_fetch_openrouter_balance,
    _safe_fetch_serper_balance,
    _safe_fetch_serpapi_balance,
    _BALANCE_CACHE,
)
from app.models import Audit, AuditStatus, Lead


def _run_async(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_cache():
    _BALANCE_CACHE.clear()
    yield
    _BALANCE_CACHE.clear()


# ─── 1. Secret Redaction Tests ─────────────────────────────────────────────────

def test_secret_redaction_across_all_providers():
    """Ensure that raw secret strings never leak into returned overview payload."""
    async def _test():
        mock_db = AsyncMock()
        # Mock database stats queries
        mock_db.execute.return_value.fetchall.return_value = [(AuditStatus.done, 611), (AuditStatus.pending, 370)]
        mock_db.execute.return_value.scalar.return_value = 985

        service = ApiUsageService()
        overview = await service.get_overview(mock_db)

        # Convert entire payload to JSON string
        serialized = json.dumps(overview)

        # Assert no known test placeholder or pattern secrets are present
        assert "trg_live_" not in serialized
        assert "gsk_" not in serialized
        assert "sk-or-v1-" not in serialized
        assert "AIzaSy" not in serialized
        assert "Bearer " not in serialized
        assert "password" not in serialized.lower() or "sender" in serialized.lower()

        # Non-secret identifiers must be used
        assert "serper_account_1" in serialized or "serper_account_2" in serialized
        assert "groq_account_1" in serialized or "groq_account_2" in serialized

    _run_async(_test())


# ─── 2. Provider Configured/Enabled & Balance Support ─────────────────────────

def test_providers_without_programmatic_balance_display_unavailable():
    """Providers without balance APIs must explicitly state 'Balance unavailable through API'."""
    async def _test():
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.execute.return_value.scalar.return_value = 0

        service = ApiUsageService()
        overview = await service.get_overview(mock_db)

        ai_providers = {p["name"]: p for p in overview["ai_inference_providers"]}
        discovery_providers = {p["name"]: p for p in overview["scraping_discovery_providers"]}

        # Groq has no public credit balance endpoint
        groq = ai_providers["Groq"]
        assert groq["balance_api_supported"] is False
        assert any("Balance unavailable through API" in s["balance_note"] for s in groq["slots"])
        assert "console.groq.com" in groq["dashboard_url"]

        # Gemini has no credit balance endpoint
        gemini = ai_providers["Google Gemini"]
        assert gemini["balance_api_supported"] is False
        assert any("Balance unavailable through API" in s["balance_note"] for s in gemini["slots"])
        assert "aistudio.google.com" in gemini["dashboard_url"]

        # Treg policy behavior when disabled
        with patch("app.services.api_usage_service.settings.TREG_ENABLE_PAID_ENDPOINTS", False):
            overview_disabled = await service.get_overview(mock_db)
            treg_disabled = next(p for p in overview_disabled["scraping_discovery_providers"] if p["name"] == "Treg")
            assert treg_disabled["enabled"] is False
            assert "TREG_ENABLE_PAID_ENDPOINTS=False" in treg_disabled["policy_reason"]

        # Treg policy behavior when enabled
        with patch("app.services.api_usage_service.settings.TREG_API_KEY_1", "treg_test_key_12345678"):
            with patch("app.services.api_usage_service.settings.TREG_ENABLE_PAID_ENDPOINTS", True):
                overview_enabled = await service.get_overview(mock_db)
                treg_enabled = next(p for p in overview_enabled["scraping_discovery_providers"] if p["name"] == "Treg")
                assert treg_enabled["enabled"] is True
                assert treg_enabled["policy_reason"] is None
                assert "Billed against $1.00 trial" in treg_enabled["estimated_cost"]

    _run_async(_test())


def test_openrouter_authoritative_balance_fetch():
    """OpenRouter read-only key endpoint successfully parses usage and limits."""
    async def _test():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "label": "Production Key",
                "usage": 0.045,
                "limit": None,
                "is_free_tier": True,
                "rate_limit": {"requests": 20, "interval": "10s"},
            }
        }

        with patch("httpx.AsyncClient.get", return_value=mock_response):
            result = await _safe_fetch_openrouter_balance("valid_key_test_123456789")
            assert result["balance_available"] is True
            assert result["usage"] == 0.045
            assert result["is_free_tier"] is True
            assert result["rate_limit"]["requests"] == 20

    _run_async(_test())


def test_safe_error_handling_on_network_timeout():
    """Network failure or timeout on balance query must not crash the application."""
    async def _test():
        with patch("httpx.AsyncClient.get", side_effect=Exception("Connection timed out")):
            result = await _safe_fetch_openrouter_balance("valid_key_test_123456789")
            assert result["balance_available"] is False
            assert "timed out" in result["note"].lower()

    _run_async(_test())


# ─── 3. SEO Audit Engine Provenance Tests ──────────────────────────────────────

def test_audit_engine_distinguishes_local_from_external():
    """Audit engine provenance explicitly labels local execution and zero external API costs."""
    async def _test():
        mock_db = AsyncMock()
        # Mock database queries for audit counts
        mock_db.execute.return_value.fetchall.side_effect = [
            [(AuditStatus.done, 611), (AuditStatus.pending, 370), (AuditStatus.failed, 4)],
            [("COMPLETE", 611), ("PENDING", 370), ("FAILED", 4)],
        ]
        mock_db.execute.return_value.scalar.side_effect = [985, 450, 985, 0, 0, 0, 0, 0, 0, 0]

        service = ApiUsageService()
        overview = await service.get_overview(mock_db)

        audit_act = overview["audit_engine_activity"]
        assert "62-factor" in audit_act["canonical_contract"]

        comps = {c["name"]: c for c in audit_act["components"]}

        # 1. Local HTTP Crawler
        crawler = comps["Local HTTP Crawler & Parser"]
        assert crawler["type"] == "local_cpu_network"
        assert "$0.00" in crawler["cost"]
        assert "requests" in crawler["execution"]

        # 2. Local Playwright
        playwright = comps["Playwright Headless Browser"]
        assert playwright["type"] == "local_browser_check"
        assert "$0.00" in playwright["cost"]

        # 3. Local Lighthouse Synthetic
        lighthouse = comps["Lighthouse Lab Performance"]
        assert lighthouse["type"] == "local_synthetic_baseline"
        assert "$0.00" in lighthouse["cost"]

        # 4. External Audit APIs
        external = comps["PageSpeed Insights / External SEO APIs"]
        assert external["type"] == "external_third_party_api"
        assert "0 external API calls made" in external["cost"]
        assert external["status"] == "not_implemented_or_called"

    _run_async(_test())


# ─── 4. Outbound Email Global Cap Overview Verification ────────────────────────

def test_email_quota_reports_authoritative_1000_cap():
    """Overview payload includes email quota with strictly 1000 total capacity."""
    async def _test():
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.execute.return_value.scalar.return_value = 0

        service = ApiUsageService()
        overview = await service.get_overview(mock_db)

        eq = overview["email_quota"]
        assert eq["total_daily_capacity"] == 1000
        assert eq["global_daily_cap"] == 1000
        assert eq["timezone"] == "Asia/Kolkata"
        assert "IST" in eq["reset_at_ist"]

    _run_async(_test())


# ─── 5. Additional Provider & Rate-Limit Diagnostics Tests ────────────────────

def test_serper_authoritative_balance_fetch():
    """Serper account check parses credit balance accurately via POST /account."""
    async def _test():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"credits": 2450}

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            res = await _safe_fetch_serper_balance("valid_serper_key_test_123", 1)
            assert res["balance_available"] is True
            assert res["credits"] == 2450

    _run_async(_test())


def test_provider_rate_limit_and_quota_exhaustion_diagnostics():
    """ProviderKeyManager handles 429 rate limit (cooldown) and 402 quota exhaustion."""
    from app.services.provider_key_manager import ProviderKeyManager, ProviderKeyPool
    from app.config import Settings

    custom_settings = Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        JWT_SECRET="test-secret-at-least-32-chars-long!",
        SERPER_API_KEY_1="serper_test_key_slot_1_abc",
        SERPER_API_KEY_2="serper_test_key_slot_2_xyz",
    )
    mgr = ProviderKeyManager(custom_settings)
    pool = mgr.get_pool("serper")
    assert pool is not None

    key1 = pool.keys[0]
    # Record 429 rate limit with Retry-After 15s
    pool.report_result(key1, status_code=429, retry_after=15.0)
    assert key1.is_in_cooldown() is True

    # Status report reflects rate_limited
    status_diag = pool.get_status()
    s1 = next(s for s in status_diag["slots"] if s["slot_id"] == 1)
    assert s1["in_cooldown"] is True
    assert s1["status"] == "rate_limited"

    # Key 2 records 402 (quota exhausted)
    key2 = pool.keys[1]
    pool.report_result(key2, status_code=402)
    assert key2.is_exhausted is True
    status_diag2 = pool.get_status()
    s2 = next(s for s in status_diag2["slots"] if s["slot_id"] == 2)
    assert s2["status"] == "quota_exhausted"


def test_unknown_vs_authoritative_remaining_credits():
    """Distinguishes authoritative provider-reported balance from unavailable balance."""
    async def _test():
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.execute.return_value.scalar.return_value = 0

        with patch("app.config.settings.SERPER_API_KEY_1", "serper_test_key_slot_1_abc"):
            with patch("app.services.api_usage_service._safe_fetch_serper_balance", return_value={"balance_available": True, "credits": 2100}):
                service = ApiUsageService()
                overview = await service.get_overview(mock_db)

                # Serper has authoritative balance
                serper = next(p for p in overview["scraping_discovery_providers"] if p["name"] == "Serper")
                s1 = serper["slots"][0]
                assert s1["balance_available"] is True
                assert s1["remaining_credits"] == 2100

    _run_async(_test())


def test_audit_lifecycle_reconciliation_to_985():
    """Verify that database_metrics exposes authoritative 5-state lifecycle totaling 985 and explains legacy mapping."""
    async def _test():
        mock_db = AsyncMock()
        # Mock fetchall for status counts and lifecycle counts
        mock_db.execute.return_value.fetchall.side_effect = [
            [(AuditStatus.done, 611), (AuditStatus.pending, 370), (AuditStatus.failed, 4)],
            [("COMPLETE", 575), ("PARTIAL", 24), ("BLOCKED", 16), ("PENDING", 370), ("RUNNING", 0)],
        ]
        # Mock scalar for total audits, avg response time, total leads
        mock_db.execute.return_value.scalar.side_effect = [985, 342, 985, 0, 0, 0, 0]

        service = ApiUsageService()
        overview = await service.get_overview(mock_db)

        metrics = overview["audit_engine_activity"]["database_metrics"]
        assert metrics["total_leads"] == 985
        assert metrics["total_audits"] == 985
        assert metrics["lifecycle_total"] == 985

        # Authoritative 5-state contract
        lc = metrics["lifecycle_breakdown"]
        assert lc["COMPLETE"] == 575
        assert lc["PARTIAL"] == 24
        assert lc["BLOCKED"] == 16
        assert lc["PENDING"] == 370
        assert lc["RUNNING"] == 0
        assert sum(lc.values()) == 985

        # Legacy status breakdown
        sb = metrics["status_breakdown"]
        assert sb["done"] == 611
        assert sb["pending"] == 370
        assert sb["failed"] == 4
        assert sum(sb.values()) == 985

        # Cross-mapping reconciliation explanation
        assert "575 COMPLETE" in metrics["reconciliation_explanation"]
        assert "611 done" in metrics["reconciliation_explanation"]

    _run_async(_test())


def test_serper_allocation_vs_remaining_credits():
    """Verify Serper distinguishes total allocation (2500) from remaining credits and detects exhaustion."""
    async def _test():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"balance": -5, "rateLimit": 5}

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            res = await _safe_fetch_serper_balance("valid_serper_key_12345678", 1)
            assert res["balance_available"] is True
            assert res["total_allocation"] == 2500
            assert res["raw_balance"] == -5
            assert res["credits"] == 0
            assert res["is_exhausted"] is True
            assert "Quota exhausted" in res["note"]
            assert res["last_checked"] is not None

    _run_async(_test())


def test_serpapi_authoritative_balance_fetch_and_two_key_pool():
    """Verify SerpApi parses GET /account, exposes 250 searches/mo per account, and registers SERPAPI_API_KEY_1 and SERPAPI_API_KEY_2."""
    async def _test():
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "plan_name": "Free Plan",
            "searches_per_month": 250,
            "total_searches_left": 250,
            "this_month_usage": 0,
            "account_status": "Active",
        }

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            res = await _safe_fetch_serpapi_balance("valid_serpapi_key_test_1234", 1)
            assert res["balance_available"] is True
            assert res["total_allocation"] == 250
            assert res["credits"] == 250
            assert res["is_exhausted"] is False
            assert "250 / 250" in res["note"]
            assert res["last_checked"] is not None

        # Verify ProviderKeyManager creates two-key pool for SerpApi
        from app.services.provider_key_manager import ProviderKeyManager
        from app.config import Settings

        custom_settings = Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            JWT_SECRET="test-secret-at-least-32-chars-long!",
            SERPAPI_API_KEY_1="serpapi_test_key_slot_1_abc",
            SERPAPI_API_KEY_2="serpapi_test_key_slot_2_xyz",
            SERPAPI_QUOTA_SCOPE_1="serpapi_custom_scope_1",
            SERPAPI_QUOTA_SCOPE_2="serpapi_custom_scope_2",
        )
        mgr = ProviderKeyManager(custom_settings)
        pool = mgr.get_pool("serpapi")
        assert pool is not None
        assert pool.is_configured() is True
        assert len(pool.keys) == 2
        assert pool.keys[0].quota_scope.scope_id == "serpapi_custom_scope_1"
        assert pool.keys[1].quota_scope.scope_id == "serpapi_custom_scope_2"

    _run_async(_test())


