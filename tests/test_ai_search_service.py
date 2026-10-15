"""
tests/test_ai_search_service.py

Unit and mock contract test suite for AiSearchMonitoringService.
Verifies:
1. Clear separation of readiness heuristics from actual visibility monitoring.
2. AI crawler permissions inspection in robots.txt (GPTBot, ClaudeBot, PerplexityBot).
3. llms.txt treated strictly as informational observation (never ranking factor).
4. Truthful disconnected state when external provider is absent (no invented citations).
5. Repeatable query corpus construction.
6. Mocked citation evaluation and uncertainty disclosure.
"""

import pytest
from backend.app.services.ai_search_service import AiSearchMonitoringService


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
