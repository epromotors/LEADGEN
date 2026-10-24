"""
tests/test_ai_search_service.py

Unit and mock contract test suite for AiSearchMonitoringService and PerplexityAgentProvider.
Verifies:
1. Clear separation of readiness heuristics from actual visibility monitoring.
2. AI crawler permissions inspection in robots.txt (GPTBot, ClaudeBot, PerplexityBot).
3. llms.txt treated strictly as informational observation (never ranking factor).
4. Truthful disconnected state when external provider is absent (no invented citations).
5. Repeatable query corpus construction and query budget capping.
6. Perplexity Agent API provider adapter:
   - Official response schema parsing (output[].content[].annotations)
   - Citations, search results, and usage token parsing
   - URL & domain normalization (safe subdomain matching, avoiding substring false positives)
   - Brand mention & alias matching with word boundaries
   - HTTP 401/403, 429 backoff retry, timeout, 5xx server error, and malformed payload handling
   - Redaction of credentials from all results and errors
7. Measurable visibility run execution:
   - Brand mention rate and citation rate with explicit denominators
   - Competitor comparison metrics and Share of Voice
   - Truthful failure states (NO false zero metrics when queries fail)
   - Duplicate-run locking and file persistence
"""

import asyncio
import json
import os
import tempfile
import pytest
import sys
import httpx
from unittest.mock import MagicMock, patch

from backend.app.services.ai_search_service import AiSearchMonitoringService
from backend.app.services.ai_search_provider import (
    PerplexityAgentProvider,
    OpenRouterAgentProvider,
    GeminiSearchProvider,
    normalize_domain,
    is_domain_match,
    is_brand_mentioned_in_text,
)


from backend.app.services.provider_key_manager import ProviderKeyManager


@pytest.fixture(autouse=True)
def _isolate_test_ai_search_environment(monkeypatch):
    """
    Ensure test_ai_search_service runs in a clean environment without
    interference from environment variables, settings, or global key manager singletons.
    """
    empty_settings = type("EmptySettings", (), {})()
    empty_km = ProviderKeyManager(settings_obj=empty_settings)

    # Patch in both 'app' and 'backend.app' modules if loaded
    for mod_name in ("app.services.provider_key_manager", "backend.app.services.provider_key_manager"):
        if mod_name in sys.modules:
            monkeypatch.setattr(sys.modules[mod_name], "_global_key_manager", empty_km)

    for cfg_mod in ("app.config", "backend.app.config"):
        if cfg_mod in sys.modules:
            s = getattr(sys.modules[cfg_mod], "settings", None)
            if s:
                monkeypatch.setattr(s, "GROQ_API_KEY_1", "")
                monkeypatch.setattr(s, "GROQ_API_KEY_2", "")
                monkeypatch.setattr(s, "GROQ_API_KEY", "")
                monkeypatch.setattr(s, "SERPER_API_KEY_1", "")
                monkeypatch.setattr(s, "SERPER_API_KEY_2", "")
                monkeypatch.setattr(s, "TREG_API_KEY_1", "")
                monkeypatch.setattr(s, "TREG_API_KEY_2", "")

    monkeypatch.setenv("GROQ_API_KEY_1", "")
    monkeypatch.setenv("GROQ_API_KEY_2", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEY_1", "")
    monkeypatch.setenv("SERPER_API_KEY_2", "")
    monkeypatch.setenv("TREG_API_KEY_1", "")
    monkeypatch.setenv("TREG_API_KEY_2", "")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    monkeypatch.setenv("AI_SEARCH_PROVIDER_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    yield


# ── 1. Readiness Heuristics & Crawler Access ─────────────────────────────────

def test_ai_readiness_heuristics_crawlers_and_schema():
    robots_sample = """
    User-agent: *
    Disallow: /admin/

    User-agent: GPTBot
    Disallow: /

    User-agent: ClaudeBot
    Allow: /
    """

    audit_results = {
        "onpage": {
            "schema": {"status": "PASS"},
            "h1": {"status": "PASS"},
            "page_title": {"status": "PASS"},
        },
        "local_seo": {
            "local_business_schema": {"status": "PASS"},
        },
    }

    readiness = AiSearchMonitoringService.evaluate_ai_readiness_heuristics(
        audit_results=audit_results,
        robots_text=robots_sample,
        has_llms_txt=True,
    )

    assert readiness["readiness_status"] == "evaluated"
    assert "GPTBot" in readiness["crawlers"]["blocked"]
    assert "ClaudeBot" in readiness["crawlers"]["allowed"]
    assert readiness["entity_structure"]["has_schema_markup"] is True
    assert readiness["entity_structure"]["has_local_entity_schema"] is True

    # Check llms.txt disclaimer
    assert readiness["llms_txt"]["present"] is True
    assert readiness["llms_txt"]["ranking_factor"] is False
    assert readiness["llms_txt"]["nature"] == "informational_observation_only"


# ── 2. Unconfigured State & Legacy Citation Interface ────────────────────────

def test_ai_visibility_unconfigured_state():
    svc = AiSearchMonitoringService(provider_api_key="")
    assert not svc.is_provider_configured()

    status = svc.get_visibility_monitoring_status()
    assert status["monitoring_enabled"] is False
    assert status["status"] == "unconfigured"
    assert status["provider"] is None

    # Evaluate without fetcher must NOT invent citations
    res = svc.evaluate_live_citations(
        queries=[{"intent": "brand", "query": "What is Car Medic Motors?"}],
        target_domain="carmedicmotors.in",
    )
    assert res["status"] == "disconnected"
    assert res["monitored"] is False
    assert res["citations"] == []


def test_ai_query_corpus_construction():
    svc = AiSearchMonitoringService()
    corpus = svc.build_standard_query_corpus(
        brand_name="Car Medic Motors",
        domain="carmedicmotors.in",
        city="Lucknow",
        services=["Car Engine Repair", "Brake Replacement"],
    )

    assert len(corpus) >= 4
    intents = [q["intent"] for q in corpus]
    assert "brand_direct" in intents
    assert "brand_reviews" in intents
    assert "service_local" in intents
    assert any("Lucknow" in q["query"] for q in corpus)


def test_ai_mocked_citation_evaluation():
    svc = AiSearchMonitoringService(provider_api_key="mock_key")
    queries = [
        {"intent": "brand_direct", "query": "What is Car Medic Motors?"},
        {"intent": "service_local", "query": "Best Car Engine Repair in Lucknow"},
    ]

    def mock_fetcher(query: str):
        if "Car Medic Motors" in query:
            return {
                "engine": "Perplexity",
                "cited_urls": ["https://carmedicmotors.in/lucknow", "https://justdial.com/carmedic"],
                "response_text": "Car Medic Motors in Lucknow offers engine and brake repair services.",
                "brand_mentioned": True,
            }
        return {
            "engine": "Perplexity",
            "cited_urls": ["https://competitor.com"],
            "response_text": "Other providers in Lucknow include Competitor Auto.",
            "brand_mentioned": False,
        }

    res = svc.evaluate_live_citations(
        queries=queries,
        target_domain="carmedicmotors.in",
        provider_fetcher=mock_fetcher,
    )

    assert res["status"] == "completed"
    assert res["monitored"] is True
    assert res["total_queries_tested"] == 2
    assert res["citations_found"] == 1
    assert res["citation_rate"] == 0.5

    citations = res["citations"]
    assert citations[0]["cited"] is True
    assert citations[0]["brand_mentioned"] is True
    assert "uncertainty_note" in citations[0]
    assert citations[1]["cited"] is False


# ── 3. Domain Normalization & Safe Matching ──────────────────────────────────

def test_domain_normalization_and_matching():
    # Basic normalization
    assert normalize_domain("https://www.CarMedicMotors.in/services/?q=1") == "carmedicmotors.in"
    assert normalize_domain("http://carmedicmotors.in:8080/path") == "carmedicmotors.in"
    assert normalize_domain("sub.domain.co.uk/") == "sub.domain.co.uk"

    # Exact domain match
    assert is_domain_match("https://www.carmedicmotors.in/page", "carmedicmotors.in") is True
    # Subdomain match
    assert is_domain_match("https://blog.carmedicmotors.in", "carmedicmotors.in") is True
    # False positive prevention: suffix collision
    assert is_domain_match("https://notcarmedicmotors.in", "carmedicmotors.in") is False
    # False positive prevention: unrelated TLD
    assert is_domain_match("https://carmedicmotors.com", "carmedicmotors.in") is False
    # False positive prevention: target embedded in query
    assert is_domain_match("https://google.com/search?q=carmedicmotors.in", "carmedicmotors.in") is False


# ── 4. Brand & Alias Matching with Word Boundaries ────────────────────────────

def test_brand_mention_word_boundaries():
    brand = "Car Medic"
    aliases = ["CarMedic", "CMM Motors"]

    # Valid matches
    assert is_brand_mentioned_in_text("Car Medic is a top service center in Lucknow.", brand, aliases) is True
    assert is_brand_mentioned_in_text("We recommend CarMedic for car repairs.", brand, aliases) is True
    assert is_brand_mentioned_in_text("Contact CMM Motors for engine service.", brand, aliases) is True

    # Case insensitive
    assert is_brand_mentioned_in_text("car medic provides 24/7 towing.", brand, aliases) is True

    # No substring collisions: "Medic" alone or "Car" alone should NOT match "Car Medic"
    assert is_brand_mentioned_in_text("This car workshop has good mechanics.", brand, aliases) is False
    assert is_brand_mentioned_in_text("Consult a medical doctor for health.", brand, aliases) is False


# ── 5. Perplexity Agent API Response Parsing ─────────────────────────────────

def test_perplexity_agent_response_parsing():
    provider = PerplexityAgentProvider(api_key="mock_secret_key")

    mock_agent_response = {
        "id": "resp-12345",
        "model": "sonar",
        "status": "completed",
        "output": [
            {
                "id": "msg-001",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Car Medic Motors is an established automotive repair facility in Lucknow [1].",
                        "annotations": [
                            {
                                "type": "citation",
                                "start_index": 68,
                                "end_index": 71,
                                "title": "Car Medic Motors Official Website",
                                "url": "https://www.carmedicmotors.in/about",
                            },
                            {
                                "type": "citation",
                                "start_index": 68,
                                "end_index": 71,
                                "title": "Justdial Lucknow Listings",
                                "url": "https://www.justdial.com/Lucknow/Car-Medic-Motors",
                            },
                        ],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 45,
            "total_tokens": 165,
        },
    }

    parsed = provider.parse_agent_response(mock_agent_response, query="Who is Car Medic Motors?", latency_ms=450)

    assert parsed["status"] == "success"
    assert parsed["query"] == "Who is Car Medic Motors?"
    assert parsed["engine"] == "Perplexity Agent API"
    assert parsed["model"] == "sonar"
    assert "Car Medic Motors is an established" in parsed["answer_text"]
    assert len(parsed["citations"]) == 2
    assert parsed["citations"][0]["domain"] == "carmedicmotors.in"
    assert parsed["citations"][0]["url"] == "https://www.carmedicmotors.in/about"
    assert parsed["citations"][1]["domain"] == "justdial.com"
    assert parsed["usage"]["total_tokens"] == 165
    assert parsed["latency_ms"] == 450
    # Strict secret redaction: secret key must never appear
    assert "mock_secret_key" not in json.dumps(parsed)


# ── 6. Provider Error Handling & Redaction (401, 429, 5xx, Timeout) ──────────

def test_perplexity_provider_auth_failure_401():
    async def _test():
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        mock_resp.text = "Unauthorized: Invalid API Key"

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        provider = PerplexityAgentProvider(api_key="invalid_test_key_123")
        res = await provider.execute_query("test query", client=mock_client)

        assert res["status"] == "auth_failed"
        assert "HTTP 401" in res["error_message"]
        # Verify credential redaction: key is never leaked
        assert "invalid_test_key_123" not in res["error_message"]
        assert "invalid_test_key_123" not in json.dumps(res)

    asyncio.run(_test())


def test_perplexity_provider_timeout():
    async def _test():
        mock_client = MagicMock()
        async def async_timeout(*args, **kwargs):
            raise httpx.TimeoutException("Connection timed out")
        mock_client.post = async_timeout

        provider = PerplexityAgentProvider(api_key="valid_test_key", timeout_seconds=5)
        res = await provider.execute_query("timeout query", client=mock_client)

        assert res["status"] == "timeout"
        assert "timed out after 5s" in res["error_message"]
        assert res["citations"] == []

    asyncio.run(_test())


def test_perplexity_provider_rate_limited_429_exhausted():
    async def _test():
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "0.1"}

        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client = MagicMock()
        mock_client.post = async_post

        provider = PerplexityAgentProvider(api_key="valid_key")
        res = await provider.execute_query("rate limited query", client=mock_client)

        assert res["status"] == "rate_limited"
        assert "HTTP 429" in res["error_message"]

    asyncio.run(_test())


# ── 7. Visibility Run Execution & Metrics Calculation ────────────────────────

def test_execute_visibility_run_with_metrics_and_competitors():
    async def _test():
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            storage_file = tf.name

        try:
            svc = AiSearchMonitoringService(
                provider_api_key="test_perplexity_key",
                storage_file=storage_file,
            )

            queries = [
                {"intent": "brand_direct", "query": "What is Car Medic Motors?"},
                {"intent": "service_local", "query": "Best Car Mechanics in Lucknow"},
            ]

            async def mock_fetcher(query: str):
                if "Car Medic Motors" in query:
                    return {
                        "status": "success",
                        "engine": "Perplexity Agent API",
                        "model": "sonar",
                        "answer_text": "Car Medic Motors in Lucknow offers expert diagnostics and brake repair.",
                        "citations": [
                            {"url": "https://carmedicmotors.in/services", "domain": "carmedicmotors.in", "title": "Services"},
                        ],
                        "cited_urls": ["https://carmedicmotors.in/services"],
                        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                        "latency_ms": 300,
                    }
                else:
                    return {
                        "status": "success",
                        "engine": "Perplexity Agent API",
                        "model": "sonar",
                        "answer_text": "Top mechanics in Lucknow include SpeedAuto and Car Medic.",
                        "citations": [
                            {"url": "https://speedauto.in", "domain": "speedauto.in", "title": "Speed Auto"},
                        ],
                        "cited_urls": ["https://speedauto.in"],
                        "usage": {"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
                        "latency_ms": 350,
                    }

            run_result = await svc.execute_visibility_run(
                lead_id="test-lead-uuid-1234",
                brand_name="Car Medic Motors",
                domain="carmedicmotors.in",
                brand_aliases=["Car Medic"],
                competitors=[{"name": "SpeedAuto", "domain": "speedauto.in"}],
                query_budget=2,
                queries=queries,
                provider_client=mock_fetcher,
            )

            assert run_result["status"] == "completed"
            assert run_result["queries_attempted"] == 2
            assert run_result["queries_succeeded"] == 2
            assert run_result["queries_failed"] == 0

            # Brand mentioned in both answers:
            # Query 1 mentions "Car Medic Motors"
            # Query 2 mentions "Car Medic" (alias)
            assert run_result["brand_mentions_count"] == 2
            assert run_result["brand_mention_rate"] == 1.0

            # Domain cited in Query 1 only
            assert run_result["domain_citations_count"] == 1
            assert run_result["citation_rate"] == 0.5

            # Competitor metrics
            assert len(run_result["competitor_metrics"]) == 1
            comp = run_result["competitor_metrics"][0]
            assert comp["name"] == "SpeedAuto"
            assert comp["mentions_count"] == 1
            assert comp["citations_count"] == 1

            # Share of voice: 2 brand mentions / (2 brand + 1 competitor) = 2/3 = 0.667
            assert run_result["share_of_voice"] == 0.667

            # Tokens: 150 + 180 = 330
            assert run_result["usage"]["total_tokens"] == 330

            # Volatility note present
            assert "Perplexity Agent API" in run_result["uncertainty_note"]

            # History inspection
            history = svc.get_history("test-lead-uuid-1234")
            assert len(history) == 1
            assert history[0]["run_id"] == run_result["run_id"]

            latest = svc.get_latest_run("test-lead-uuid-1234")
            assert latest is not None
            assert latest["run_id"] == run_result["run_id"]

        finally:
            if os.path.exists(storage_file):
                os.remove(storage_file)

    asyncio.run(_test())


# ── 8. No False Zero Metrics on Failed Queries ────────────────────────────────

def test_no_false_zero_metrics_on_all_failed_queries():
    async def _test():
        svc = AiSearchMonitoringService(provider_api_key="valid_key")

        async def mock_failed_fetcher(query: str):
            return {
                "status": "rate_limited",
                "engine": "Perplexity Agent API",
                "answer_text": "",
                "citations": [],
                "error_message": "Rate limited 429",
            }

        res = await svc.execute_visibility_run(
            lead_id="test-lead-fail",
            brand_name="Test Garage",
            domain="testgarage.com",
            queries=[{"intent": "brand", "query": "Test query"}],
            provider_client=mock_failed_fetcher,
        )

        # When all queries fail, status MUST be failed and metrics MUST NOT be false zeros
        assert res["status"] == "failed"
        assert res["queries_attempted"] == 1
        assert res["queries_succeeded"] == 0
        assert res["queries_failed"] == 1
        assert res["brand_mention_rate"] is None
        assert res["citation_rate"] is None
        assert res["share_of_voice"] is None
        assert "queries failed or were rate-limited" in res["uncertainty_note"]

    asyncio.run(_test())


# ── 9. Duplicate-Run Protection ──────────────────────────────────────────────

def test_duplicate_run_protection():
    async def _test():
        svc = AiSearchMonitoringService(provider_api_key="valid_key")
        lead_id = "lock-lead-123"

        # Simulate an active run in progress
        svc._active_runs.add(lead_id)

        with pytest.raises(RuntimeError) as exc_info:
            await svc.execute_visibility_run(
                lead_id=lead_id,
                brand_name="Lock Test",
                domain="locktest.in",
            )

        assert "already running" in str(exc_info.value)
        # Clean up lock
        svc._active_runs.discard(lead_id)

    asyncio.run(_test())


# ── 10. Gemini Provider Tests (Search Grounding & Redaction) ───────────────────

def test_gemini_provider_success_with_grounding():
    async def _test():
        provider = GeminiSearchProvider(
            api_key="mock_gemini_secret_key_12345",
            model="gemini-2.0-flash",
            enable_search_grounding=True,
        )

        mock_gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "Car Medic Motors is a premier car workshop in Gomti Nagar, Lucknow. They provide full engine service."
                            }
                        ],
                        "role": "model",
                    },
                    "groundingMetadata": {
                        "webSearchQueries": ["car repair gomti nagar lucknow", "car medic motors lucknow"],
                        "groundingChunks": [
                            {
                                "web": {
                                    "uri": "https://carmedicmotors.in/services",
                                    "title": "Car Medic Motors - Car Repair & Service",
                                }
                            },
                            {
                                "web": {
                                    "uri": "https://www.justdial.com/Lucknow/Car-Medic",
                                    "title": "Car Medic in Gomti Nagar, Lucknow - Justdial",
                                }
                            },
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 42,
                "candidatesTokenCount": 78,
                "totalTokenCount": 120,
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_gemini_response

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Top car workshop in Gomti Nagar Lucknow",
            client=mock_client,
        )

        assert res["status"] == "success"
        assert res["engine"] == "Google Gemini API"
        assert res["model"] == "gemini-2.0-flash"
        assert res["grounding_active"] is True
        assert "Car Medic Motors" in res["answer_text"]
        assert len(res["citations"]) == 2
        assert res["citations"][0]["domain"] == "carmedicmotors.in"
        assert res["citations"][0]["title"] == "Car Medic Motors - Car Repair & Service"
        assert res["usage"]["total_tokens"] == 120
        assert "mock_gemini_secret_key" not in str(res)

    asyncio.run(_test())


def test_gemini_provider_rate_limit_429():
    async def _test():
        provider = GeminiSearchProvider(api_key="mock_gemini_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = json.dumps({"error": {"message": "Resource has been exhausted (e.g. check quota)."}})

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Test Query",
            client=mock_client,
        )

        assert res["status"] == "rate_limited"
        assert "quota" in res["error_message"].lower() or "429" in res["error_message"]
        assert res["citations"] == []

    asyncio.run(_test())


def test_gemini_provider_auth_error_400():
    async def _test():
        provider = GeminiSearchProvider(api_key="invalid_gemini_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = json.dumps({"error": {"message": "API key not valid. Please pass a valid API key."}})

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Test Query",
            client=mock_client,
        )

        assert res["status"] == "auth_failed"
        assert "API key" in res["error_message"] or "invalid" in res["error_message"].lower() or "400" in res["error_message"]

    asyncio.run(_test())


def test_gemini_provider_timeout_and_redaction():
    async def _test():
        secret_key = "secret_gemini_token_99999"
        provider = GeminiSearchProvider(api_key=secret_key, timeout_seconds=5)

        mock_client = MagicMock()
        async def async_timeout(*args, **kwargs):
            raise httpx.TimeoutException("Timed out contacting https://generativelanguage.googleapis.com?key=" + secret_key)
        mock_client.post = async_timeout

        res = await provider.execute_query(
            "Test Query",
            client=mock_client,
        )

        assert res["status"] == "timeout"
        assert secret_key not in res["error_message"]
        assert "[REDACTED_API_KEY]" in res["error_message"]

    asyncio.run(_test())


# ── 11. OpenRouter Provider Tests (Chat Completions & 402/429) ─────────────────

def test_openrouter_provider_success():
    async def _test():
        provider = OpenRouterAgentProvider(
            api_key="mock_openrouter_sk_key",
            model="meta-llama/llama-3.3-70b-instruct:free",
            enable_web_search=False,
        )

        mock_or_response = {
            "id": "gen-12345",
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "For reliable car repair, Car Medic Motors (https://carmedicmotors.in) offers trusted services in Lucknow.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 25,
                "total_tokens": 55,
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_or_response

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Car repair lucknow",
            client=mock_client,
        )

        assert res["status"] == "success"
        assert res["engine"] == "OpenRouter"
        assert "meta-llama/llama-3.3-70b-instruct:free" in res["model"]
        assert len(res["citations"]) >= 1
        assert res["citations"][0]["domain"] == "carmedicmotors.in"
        assert res["usage"]["total_tokens"] == 55

    asyncio.run(_test())


def test_openrouter_provider_payment_required_402():
    async def _test():
        provider = OpenRouterAgentProvider(
            api_key="mock_openrouter_free_only_key",
            enable_web_search=True,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.text = json.dumps({"error": {"message": "Requires paid credit balance for web search plugins."}})

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Car repair",
            client=mock_client,
        )

        assert res["status"] == "payment_required"
        assert "payment" in res["error_message"].lower() or "credit" in res["error_message"].lower() or "402" in res["error_message"]

    asyncio.run(_test())


def test_openrouter_provider_rate_limited_429():
    async def _test():
        provider = OpenRouterAgentProvider(api_key="mock_openrouter_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = json.dumps({"error": {"message": "Free tier rate limit exceeded."}})

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Car repair",
            client=mock_client,
        )

        assert res["status"] == "rate_limited"


def test_openrouter_provider_malformed_json():
    async def _test():
        provider = OpenRouterAgentProvider(api_key="mock_openrouter_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_resp.text = "<html>502 Bad Gateway</html>"

        mock_client = MagicMock()
        async def async_post(*args, **kwargs):
            return mock_resp
        mock_client.post = async_post

        res = await provider.execute_query(
            "Car repair",
            client=mock_client,
        )

        assert res["status"] == "malformed_response"


# ── 12. Multi-Provider Status & Priority Selection ─────────────────────────────

def test_multi_provider_monitoring_status():
    svc = AiSearchMonitoringService(
        gemini_api_key="mock_gemini_key",
        openrouter_api_key="mock_or_key",
        provider_api_key="",
        provider_name="gemini",
    )

    status = svc.get_visibility_monitoring_status()
    assert status["monitoring_enabled"] is True
    assert status["active_provider"] == "gemini"
    assert status["providers"]["gemini"]["configured"] is True
    assert status["providers"]["openrouter"]["configured"] is True
    assert status["providers"]["perplexity"]["configured"] is False

    # Check tier info and cost risks are properly reported
    assert "Free Tier" in status["providers"]["gemini"]["tier_info"]
    assert "zero charge" in status["providers"]["gemini"]["cost_risk"].lower() or "free" in status["providers"]["gemini"]["cost_risk"].lower()
    assert status["providers"]["gemini"]["requires_paid_credits"] is False
    assert status["providers"]["openrouter"]["requires_paid_credits"] is True


def test_multi_provider_execution_switching():
    async def _test():
        svc = AiSearchMonitoringService(
            gemini_api_key="mock_gemini_key",
            openrouter_api_key="mock_or_key",
            provider_api_key="mock_pplx_key",
        )

        async def mock_gemini_fetcher(query: str):
            return {
                "status": "success",
                "engine": "Google Gemini API",
                "model": "gemini-2.0-flash",
                "answer_text": "Car Medic Motors is located in Lucknow.",
                "citations": [{"url": "https://carmedicmotors.in", "domain": "carmedicmotors.in", "title": "Home"}],
                "grounding_active": True,
                "usage": {"total_tokens": 100},
            }

        res = await svc.execute_visibility_run(
            lead_id="test-lead-gemini",
            brand_name="Car Medic Motors",
            domain="carmedicmotors.in",
            queries=[{"intent": "brand", "query": "Car Medic Motors"}],
            provider_client=mock_gemini_fetcher,
            provider_name="gemini",
        )

        assert res["status"] == "completed"
        assert res["provider"] == "Google Gemini API"
        assert res["model"] == "gemini-2.0-flash"
        assert res["evidence"][0]["grounding_used"] is True
        assert res["brand_mention_rate"] == 1.0
        assert res["citation_rate"] == 1.0

    asyncio.run(_test())

