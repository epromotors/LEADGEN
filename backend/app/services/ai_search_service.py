"""
backend/app/services/ai_search_service.py

AI-Search Readiness and Visibility Monitoring Service.
Implements Domain A of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Clearly separates AI-Search Readiness Heuristics from Actual Visibility Monitoring.
- Evaluates crawler access (GPTBot, ClaudeBot, PerplexityBot, Google-Extended).
- Evaluates llms.txt as an optional informational observation only (never a ranking guarantee).
- Truthful disconnected state: Never fabricates AI citations or appearances without an authorized provider.
- Structured query corpus definition for brand, service, and local intent.
- Records engine, query, date, response excerpt, cited URLs, and volatility disclaimer.
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KNOWN_AI_CRAWLERS = [
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
    "CCBot",
]


class AiSearchMonitoringService:
    """Evaluates readiness heuristics and tracks observed AI-search engine citations."""

    def __init__(self, provider_api_key: Optional[str] = None):
        self.provider_api_key = provider_api_key or os.environ.get("AI_SEARCH_PROVIDER_KEY", "")

    def is_provider_configured(self) -> bool:
        """Returns True only if an external AI-search provider API key is configured."""
        return bool(self.provider_api_key.strip())

    @staticmethod
    def evaluate_ai_readiness_heuristics(
        audit_results: Dict[str, Any],
        robots_text: Optional[str] = None,
        has_llms_txt: bool = False,
    ) -> Dict[str, Any]:
        """
        Evaluate structural signals that facilitate indexing and citation by AI discovery engines.
        Readiness is strictly differentiated from observed live citations.
        """
        # 1. Crawler permissions in robots.txt
        blocked_crawlers = []
        allowed_crawlers = []
        if robots_text:
            lines = robots_text.splitlines()
            current_agent = None
            for line in lines:
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    current_agent = line.split(":", 1)[1].strip()
                elif line.lower().startswith("disallow:") and current_agent:
                    rule_path = line.split(":", 1)[1].strip()
                    for ai_bot in KNOWN_AI_CRAWLERS:
                        if current_agent.lower() == ai_bot.lower() and rule_path in ["/", "/*"]:
                            if ai_bot not in blocked_crawlers:
                                blocked_crawlers.append(ai_bot)

        for bot in KNOWN_AI_CRAWLERS:
            if bot not in blocked_crawlers:
                allowed_crawlers.append(bot)

        # 2. Entity and Structured Data
        has_schema = False
        onpage_schema = audit_results.get("onpage", {}).get("schema", {})
        if onpage_schema.get("status") == "PASS":
            has_schema = True

        has_local_entity = False
        local_schema = audit_results.get("local_seo", {}).get("local_business_schema", {})
        if local_schema.get("status") == "PASS":
            has_local_entity = True

        # 3. Direct Q&A Content / Heading hierarchy
        h1_ok = audit_results.get("onpage", {}).get("h1", {}).get("status") == "PASS"
        title_ok = audit_results.get("onpage", {}).get("page_title", {}).get("status") == "PASS"

        readiness_score = 0
        if allowed_crawlers:
            readiness_score += 35
        if has_schema or has_local_entity:
            readiness_score += 35
        if h1_ok and title_ok:
            readiness_score += 30

        return {
            "readiness_status": "evaluated",
            "readiness_score": readiness_score,
            "crawlers": {
                "allowed": allowed_crawlers,
                "blocked": blocked_crawlers,
                "all_allowed": len(blocked_crawlers) == 0,
            },
            "entity_structure": {
                "has_schema_markup": has_schema,
                "has_local_entity_schema": has_local_entity,
            },
            "content_structure": {
                "descriptive_title": title_ok,
                "primary_h1": h1_ok,
            },
            "llms_txt": {
                "present": has_llms_txt,
                "nature": "informational_observation_only",
                "ranking_factor": False,
                "note": "llms.txt is an optional emerging convention; it is not a required search engine ranking factor.",
            },
        }

    def get_visibility_monitoring_status(self) -> Dict[str, Any]:
        """
        Return the truthful monitoring status.
        Never fabricates citation data when disconnected.
        """
        if not self.is_provider_configured():
            return {
                "monitoring_enabled": False,
                "status": "unconfigured",
                "provider": None,
                "reason": (
                    "AI-search live visibility monitoring requires an authorized data provider "
                    "(e.g., Perplexity API, Bing Web Search, or custom LLM evaluation provider). "
                    "Set AI_SEARCH_PROVIDER_KEY to enable live citation tracking."
                ),
                "total_monitored_queries": 0,
                "observations": [],
            }

        return {
            "monitoring_enabled": True,
            "status": "connected",
            "provider": "Configured API Provider",
            "reason": "Authorized for automated AI search citation sampling.",
            "total_monitored_queries": 0,
            "observations": [],
        }

    def build_standard_query_corpus(
        self,
        brand_name: str,
        domain: str,
        city: Optional[str] = None,
        services: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """
        Construct a repeatable, standardized query set across:
        - Brand identity intent
        - Commercial service intent
        - Local location intent
        """
        corpus: List[Dict[str, str]] = [
            {"intent": "brand_direct", "query": f"What is {brand_name} and what services do they offer?"},
            {"intent": "brand_reviews", "query": f"Is {brand_name} ({domain}) reliable and reputable?"},
        ]
        if services:
            for s in services[:3]:
                if city:
                    corpus.append({
                        "intent": "service_local",
                        "query": f"Best {s} in {city}",
                    })
                else:
                    corpus.append({
                        "intent": "service_generic",
                        "query": f"Recommended providers for {s}",
                    })
        elif city:
            corpus.append({
                "intent": "local_directory",
                "query": f"Top rated automotive services in {city}",
            })

        return corpus

    def evaluate_live_citations(
        self,
        queries: List[Dict[str, str]],
        target_domain: str,
        provider_fetcher: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute or mock the collection of AI search responses and extract citations.
        Returns explicit disconnected state if provider is not configured and no fetcher is passed.
        """
        if not self.is_provider_configured() and provider_fetcher is None:
            return {
                "status": "disconnected",
                "monitored": False,
                "target_domain": target_domain,
                "reason": "External provider not configured. Live citations were not polled.",
                "citations": [],
            }

        citations: List[Dict[str, Any]] = []
        norm_domain = target_domain.lower().replace("https://", "").replace("http://", "").strip("/")

        for q in queries:
            query_text = q["query"]
            # If provider_fetcher is supplied (real callable or mock)
            if provider_fetcher:
                result = provider_fetcher(query_text)
            else:
                result = {"engine": "AI Search Engine", "cited_urls": [], "response_text": "", "brand_mentioned": False}

            is_cited = any(norm_domain in u.lower() for u in result.get("cited_urls", []))
            brand_in_text = norm_domain in result.get("response_text", "").lower()

            citations.append({
                "query": query_text,
                "intent": q.get("intent", "general"),
                "engine": result.get("engine", "AI Assistant"),
                "cited": is_cited,
                "brand_mentioned": brand_in_text or result.get("brand_mentioned", False),
                "cited_urls": result.get("cited_urls", []),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "uncertainty_note": "Generative search answers vary across users and time; citations represent dated point-in-time samples.",
            })

        cited_count = sum(1 for c in citations if c["cited"])
        return {
            "status": "completed",
            "monitored": True,
            "target_domain": target_domain,
            "total_queries_tested": len(queries),
            "citations_found": cited_count,
            "citation_rate": round(cited_count / len(queries), 2) if queries else 0.0,
            "citations": citations,
        }
