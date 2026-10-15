"""
backend/app/services/ai_search_service.py

AI-Search Readiness and Visibility Monitoring Service.
Supports Multi-Provider Visibility Monitoring:
1. Google Gemini API with Google Search Grounding (free-tier eligible: 5,000 search queries/mo).
2. OpenRouter API with free models and configurable web search tool.
3. Perplexity Agent API (POST /v1/agent).

Implements Domain A of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Clearly separates AI-Search Readiness Heuristics from Actual Visibility Monitoring.
- Evaluates crawler access (GPTBot, ClaudeBot, PerplexityBot, Google-Extended).
- Evaluates llms.txt as an optional informational observation only (never a ranking guarantee).
- Truthful disconnected state: Never fabricates AI citations or appearances without an authorized provider.
- Structured query corpus definition for brand, service, and local intent.
- Measures brand mention rate, domain citation rate, competitor visibility, and share of voice.
- Records engine, query, date, response excerpt, cited URLs, and volatility disclaimer.
- Thread-safe persistence and history tracking without database mutations.
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.services.ai_search_provider import (
    PerplexityAgentProvider,
    OpenRouterAgentProvider,
    GeminiSearchProvider,
    normalize_domain,
    is_domain_match,
    is_brand_mentioned_in_text,
    DEFAULT_PERPLEXITY_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

KNOWN_AI_CRAWLERS = [
    "GPTBot",
    "ClaudeBot",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
    "CCBot",
]

DEFAULT_QUERY_BUDGET = 10
MAX_QUERY_BUDGET = 10


class AiSearchMonitoringService:
    """Evaluates readiness heuristics and tracks observed AI-search engine citations across providers."""

    def __init__(
        self,
        provider_api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        storage_file: Optional[str] = None,
        provider_adapter: Optional[Any] = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        openrouter_model: Optional[str] = None,
        provider_name: Optional[str] = None,
    ):
        raw_timeout = timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        try:
            self.timeout_seconds = max(5, min(60, int(raw_timeout)))
        except (ValueError, TypeError):
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        self.storage_file = (
            storage_file
            or os.environ.get("AI_SEARCH_STORAGE_FILE", "")
            or "reports/.ai_search_runs.json"
        )
        self.default_provider_name = provider_name or os.environ.get("AI_SEARCH_PROVIDER", "gemini")

        # 1. Perplexity Provider
        self.perplexity_provider = PerplexityAgentProvider(
            api_key=provider_api_key or os.environ.get("AI_SEARCH_PROVIDER_KEY", "") or os.environ.get("PERPLEXITY_API_KEY", ""),
            model=model or os.environ.get("AI_SEARCH_MODEL", DEFAULT_PERPLEXITY_MODEL),
            timeout_seconds=self.timeout_seconds,
        )

        # 2. OpenRouter Provider
        self.openrouter_provider = OpenRouterAgentProvider(
            api_key=openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", ""),
            model=openrouter_model or os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            enable_web_search=os.environ.get("OPENROUTER_ENABLE_WEB_SEARCH", "true").lower() in ("true", "1", "yes"),
            timeout_seconds=self.timeout_seconds,
        )

        # 3. Google Gemini Provider
        self.gemini_provider = GeminiSearchProvider(
            api_key=gemini_api_key or os.environ.get("GEMINI_API_KEY", ""),
            model=gemini_model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            enable_search_grounding=os.environ.get("GEMINI_ENABLE_SEARCH_GROUNDING", "true").lower() in ("true", "1", "yes"),
            timeout_seconds=self.timeout_seconds,
        )

        self.providers: Dict[str, Any] = {
            "gemini": self.gemini_provider,
            "openrouter": self.openrouter_provider,
            "perplexity": self.perplexity_provider,
        }

        # Backwards compatibility reference
        if provider_adapter is not None:
            self.provider = provider_adapter
            pid = getattr(provider_adapter, "provider_id", "custom")
            self.providers[pid] = provider_adapter
        else:
            self.provider = self.perplexity_provider

        # In-memory history store keyed by lead_id (or domain)
        self._runs_by_lead: Dict[str, List[Dict[str, Any]]] = {}
        # Active execution lock set to prevent concurrent runs on same lead
        self._active_runs: Set[str] = set()

        self._load_runs_from_disk()

    def get_active_provider_id(self, preferred: Optional[str] = None) -> str:
        """
        Resolve the active provider ID.
        Prioritizes user-specified provider, then configured Gemini / OpenRouter keys over Perplexity.
        """
        if preferred and preferred.lower() in self.providers:
            return preferred.lower()

        # Prioritize Google Gemini, then OpenRouter, then Perplexity
        if self.gemini_provider.is_configured():
            return "gemini"
        if self.openrouter_provider.is_configured():
            return "openrouter"
        if self.perplexity_provider.is_configured():
            return "perplexity"

        # If a custom adapter was injected
        if hasattr(self, "provider") and self.provider != self.perplexity_provider:
            return getattr(self.provider, "provider_id", "custom")

        # Fallback to configured default
        cfg = os.environ.get("AI_SEARCH_PROVIDER", "gemini").lower()
        if cfg in self.providers:
            return cfg
        return "gemini"

    def get_provider(self, provider_id: Optional[str] = None) -> Any:
        """Return the requested or active provider adapter."""
        if hasattr(self, "provider") and self.provider not in self.providers.values() and not provider_id:
            return self.provider
        pid = self.get_active_provider_id(provider_id)
        return self.providers.get(pid, self.gemini_provider)

    def is_provider_configured(self, provider_id: Optional[str] = None) -> bool:
        """
        Returns True if the specified provider (or at least one provider) is configured.
        """
        if provider_id:
            prov = self.providers.get(provider_id.lower())
            return prov.is_configured() if prov else False
        return any(p.is_configured() for p in self.providers.values())

    def _load_runs_from_disk(self) -> None:
        """Load stored historical visibility runs from persistent JSON storage."""
        if not os.path.exists(self.storage_file):
            return
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._runs_by_lead = data
        except Exception as ex:
            logger.warning("Could not read AI search runs file (%s): %s", self.storage_file, ex)

    def _save_runs_to_disk(self) -> None:
        """Atomically persist historical visibility runs to disk."""
        try:
            dir_name = os.path.dirname(self.storage_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
            temp_path = f"{self.storage_file}.tmp.{os.getpid()}"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._runs_by_lead, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.storage_file)
        except Exception as ex:
            logger.error("Failed to persist AI search runs to (%s): %s", self.storage_file, ex)

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

        has_schema = False
        onpage_schema = audit_results.get("onpage", {}).get("schema", {})
        if onpage_schema.get("status") == "PASS":
            has_schema = True

        has_local_entity = False
        local_schema = audit_results.get("local_seo", {}).get("local_business_schema", {})
        if local_schema.get("status") == "PASS":
            has_local_entity = True

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
        Return the truthful monitoring status for all providers.
        Never fabricates citation data when disconnected.
        """
        total_queries = sum(
            sum(r.get("queries_attempted", 0) for r in runs)
            for runs in self._runs_by_lead.values()
        )

        active_id = self.get_active_provider_id()
        active_prov = self.get_provider(active_id)
        any_configured = any(p.is_configured() for p in self.providers.values())

        provider_summaries: Dict[str, Any] = {}
        for pid, prov in self.providers.items():
            t_info = prov.get_tier_info() if hasattr(prov, "get_tier_info") else {}
            provider_summaries[pid] = {
                "id": pid,
                "name": getattr(prov, "provider_name", pid.capitalize()),
                "model": getattr(prov, "model", "default"),
                "configured": prov.is_configured(),
                "tier_info": f"{t_info.get('tier', 'Standard Tier')}: {t_info.get('free_tier_limits', '')}".strip(": "),
                "cost_risk": t_info.get("cost_risk", ""),
                "requires_paid_credits": pid in ("openrouter", "perplexity"),
                "details": t_info,
            }

        if not any_configured:
            return {
                "monitoring_enabled": False,
                "status": "unconfigured",
                "active_provider": active_id,
                "provider": None,
                "model": active_prov.model,
                "max_queries_budget": DEFAULT_QUERY_BUDGET,
                "timeout_seconds": self.timeout_seconds,
                "reason": (
                    "No AI-search provider configured. "
                    "Configure GEMINI_API_KEY (recommended free tier), OPENROUTER_API_KEY, or AI_SEARCH_PROVIDER_KEY."
                ),
                "providers": provider_summaries,
                "total_monitored_queries": total_queries,
                "observations": [],
            }

        return {
            "monitoring_enabled": True,
            "status": "connected",
            "active_provider": active_id,
            "provider": getattr(active_prov, "provider_name", "AI Provider"),
            "model": active_prov.model,
            "max_queries_budget": DEFAULT_QUERY_BUDGET,
            "timeout_seconds": self.timeout_seconds,
            "reason": f"Authorized for live AI search citation sampling via {getattr(active_prov, 'provider_name', active_id)} ({active_prov.model}).",
            "providers": provider_summaries,
            "total_monitored_queries": total_queries,
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
        clean_brand = brand_name.strip() if brand_name else "Business"
        clean_domain = normalize_domain(domain)

        corpus: List[Dict[str, str]] = [
            {"intent": "brand_direct", "query": f"What is {clean_brand} and what services do they offer?"},
            {"intent": "brand_reviews", "query": f"Is {clean_brand} ({clean_domain}) reliable and reputable?"},
        ]
        if services:
            for s in services[:4]:
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

        if city and len(corpus) < DEFAULT_QUERY_BUDGET:
            corpus.append({
                "intent": "local_recommendations",
                "query": f"Where to get trusted vehicle maintenance and car repairs in {city}?",
            })

        return corpus[:DEFAULT_QUERY_BUDGET]

    async def execute_visibility_run(
        self,
        lead_id: Optional[str],
        brand_name: str,
        domain: str,
        city: Optional[str] = None,
        services: Optional[List[str]] = None,
        brand_aliases: Optional[List[str]] = None,
        competitors: Optional[List[Dict[str, str]]] = None,
        query_budget: int = DEFAULT_QUERY_BUDGET,
        queries: Optional[List[Dict[str, str]]] = None,
        provider_name: Optional[str] = None,
        provider_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute an on-demand AI-search visibility check across bounded queries using
        the selected or active provider (Google Gemini, OpenRouter, or Perplexity).
        Extracts real answer text, source citations, and computes verifiable visibility metrics.
        """
        lead_key = str(lead_id) if lead_id else normalize_domain(domain)

        if lead_key in self._active_runs:
            raise RuntimeError(f"A visibility check is already running for {lead_key}.")

        active_provider = self.get_provider(provider_name)
        active_provider_id = getattr(active_provider, "provider_id", "custom")
        active_provider_name = getattr(active_provider, "provider_name", "AI Search Engine")
        active_model = getattr(active_provider, "model", "default")

        if not active_provider.is_configured() and provider_client is None:
            return {
                "status": "unconfigured",
                "lead_id": lead_id,
                "target_domain": normalize_domain(domain),
                "brand_name": brand_name,
                "provider_id": active_provider_id,
                "provider": active_provider_name,
                "model": active_model,
                "reason": f"Provider '{active_provider_name}' is not configured with an API key.",
                "queries_attempted": 0,
                "queries_succeeded": 0,
                "queries_failed": 0,
                "brand_mention_rate": None,
                "citation_rate": None,
                "share_of_voice": None,
                "evidence": [],
            }

        bounded_budget = min(MAX_QUERY_BUDGET, max(1, query_budget or DEFAULT_QUERY_BUDGET))
        if not queries:
            query_items = self.build_standard_query_corpus(
                brand_name=brand_name,
                domain=domain,
                city=city,
                services=services,
            )[:bounded_budget]
        else:
            query_items = queries[:bounded_budget]

        target_norm_domain = normalize_domain(domain)
        competitors_list = competitors or []
        evidence: List[Dict[str, Any]] = []

        total_input_tokens = 0
        total_output_tokens = 0

        self._active_runs.add(lead_key)
        start_ts = datetime.now(timezone.utc).isoformat()

        try:
            for item in query_items:
                query_text = item["query"]
                intent = item.get("intent", "general")

                if callable(provider_client):
                    import inspect
                    if inspect.iscoroutinefunction(provider_client):
                        raw_result = await provider_client(query_text)
                    else:
                        raw_result = provider_client(query_text)
                else:
                    raw_result = await active_provider.execute_query(
                        query=query_text,
                        client=provider_client,
                    )

                status = raw_result.get("status", "error")
                answer_text = raw_result.get("answer_text", "")
                citations = raw_result.get("citations", [])
                cited_urls = raw_result.get("cited_urls", [])
                grounding_active = raw_result.get("grounding_active", False)
                usage = raw_result.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)

                brand_mentioned = False
                domain_cited = False
                competitor_results = []

                if status == "success":
                    brand_mentioned = is_brand_mentioned_in_text(
                        answer_text, brand_name, brand_aliases
                    )

                    domain_cited = any(
                        is_domain_match(c.get("url", ""), target_norm_domain)
                        or is_domain_match(c.get("domain", ""), target_norm_domain)
                        for c in citations
                    )

                    for comp in competitors_list:
                        comp_name = comp.get("name", "")
                        comp_domain = comp.get("domain", "")
                        comp_mentioned = is_brand_mentioned_in_text(answer_text, comp_name)
                        comp_cited = any(
                            is_domain_match(c.get("url", ""), comp_domain)
                            or is_domain_match(c.get("domain", ""), comp_domain)
                            for c in citations
                        )
                        competitor_results.append({
                            "name": comp_name,
                            "domain": comp_domain,
                            "mentioned": comp_mentioned,
                            "cited": comp_cited,
                        })

                evidence.append({
                    "query": query_text,
                    "intent": intent,
                    "engine": raw_result.get("engine", active_provider_name),
                    "model": raw_result.get("model", active_model),
                    "status": status,
                    "error_message": raw_result.get("error_message"),
                    "latency_ms": raw_result.get("latency_ms", 0),
                    "answer_excerpt": answer_text,
                    "citations": citations,
                    "cited_urls": cited_urls,
                    "grounding_active": grounding_active,
                    "grounding_used": grounding_active,
                    "brand_mentioned": brand_mentioned,
                    "domain_cited": domain_cited,
                    "competitor_matches": competitor_results,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        finally:
            self._active_runs.discard(lead_key)

        queries_attempted = len(evidence)
        queries_succeeded = sum(1 for e in evidence if e["status"] == "success")
        queries_failed = queries_attempted - queries_succeeded

        if queries_succeeded == 0:
            return {
                "run_id": str(uuid.uuid4()),
                "lead_id": lead_id,
                "target_domain": target_norm_domain,
                "brand_name": brand_name,
                "provider_id": active_provider_id,
                "provider": active_provider_name,
                "model": active_model,
                "status": "failed",
                "created_at": start_ts,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "queries_attempted": queries_attempted,
                "queries_succeeded": 0,
                "queries_failed": queries_failed,
                "brand_mention_rate": None,
                "citation_rate": None,
                "share_of_voice": None,
                "competitor_metrics": [],
                "evidence": evidence,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
                "uncertainty_note": (
                    f"Provider '{active_provider_name}' queries failed or were rate-limited. "
                    "No visibility metrics were recorded."
                ),
            }

        brand_mentions_count = sum(1 for e in evidence if e["status"] == "success" and e["brand_mentioned"])
        domain_citations_count = sum(1 for e in evidence if e["status"] == "success" and e["domain_cited"])

        brand_mention_rate = round(brand_mentions_count / queries_succeeded, 3)
        citation_rate = round(domain_citations_count / queries_succeeded, 3)

        comp_summary = {}
        for comp in competitors_list:
            cname = comp.get("name", "")
            comp_summary[cname] = {
                "name": cname,
                "domain": comp.get("domain", ""),
                "mentions_count": 0,
                "citations_count": 0,
            }

        for e in evidence:
            if e["status"] == "success":
                for cm in e.get("competitor_matches", []):
                    cname = cm.get("name")
                    if cname in comp_summary:
                        if cm.get("mentioned"):
                            comp_summary[cname]["mentions_count"] += 1
                        if cm.get("cited"):
                            comp_summary[cname]["citations_count"] += 1

        comp_metrics = []
        total_competitor_mentions = 0
        for cname, cdata in comp_summary.items():
            m_count = cdata["mentions_count"]
            total_competitor_mentions += m_count
            comp_metrics.append({
                "name": cname,
                "domain": cdata["domain"],
                "mentions_count": m_count,
                "mention_rate": round(m_count / queries_succeeded, 3),
                "citations_count": cdata["citations_count"],
                "citation_rate": round(cdata["citations_count"] / queries_succeeded, 3),
            })

        total_voice_mentions = brand_mentions_count + total_competitor_mentions
        share_of_voice = (
            round(brand_mentions_count / total_voice_mentions, 3)
            if total_voice_mentions > 0
            else None
        )

        run_record: Dict[str, Any] = {
            "run_id": str(uuid.uuid4()),
            "lead_id": lead_id,
            "target_domain": target_norm_domain,
            "brand_name": brand_name,
            "provider_id": active_provider_id,
            "provider": active_provider_name,
            "model": active_model,
            "status": "completed" if queries_failed == 0 else "partial",
            "created_at": start_ts,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "queries_attempted": queries_attempted,
            "queries_succeeded": queries_succeeded,
            "queries_failed": queries_failed,
            "brand_mentions_count": brand_mentions_count,
            "brand_mention_rate": brand_mention_rate,
            "domain_citations_count": domain_citations_count,
            "citation_rate": citation_rate,
            "share_of_voice": share_of_voice,
            "competitor_metrics": comp_metrics,
            "evidence": evidence,
            "usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
            "uncertainty_note": (
                f"Observations recorded via {active_provider_name} ({active_model}). "
                "Generative AI answers vary across users, regions, and dates; these results represent dated point-in-time samples."
            ),
        }

        if lead_key not in self._runs_by_lead:
            self._runs_by_lead[lead_key] = []
        self._runs_by_lead[lead_key].append(run_record)
        self._runs_by_lead[lead_key] = self._runs_by_lead[lead_key][-20:]
        self._save_runs_to_disk()

        return run_record

    def get_history(self, lead_id: str) -> List[Dict[str, Any]]:
        """Return historical visibility checks for a lead."""
        key = str(lead_id)
        return self._runs_by_lead.get(key, [])

    def get_latest_run(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent visibility check for a lead."""
        history = self.get_history(lead_id)
        if history:
            return history[-1]
        return None

    def evaluate_live_citations(
        self,
        queries: List[Dict[str, str]],
        target_domain: str,
        provider_fetcher: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Legacy synchronous citation evaluation interface preserved for backwards compatibility.
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
        norm_domain = normalize_domain(target_domain)

        for q in queries:
            query_text = q["query"]
            if provider_fetcher:
                result = provider_fetcher(query_text)
            else:
                result = {"engine": "AI Search Engine", "cited_urls": [], "response_text": "", "brand_mentioned": False}

            is_cited = any(is_domain_match(u, norm_domain) for u in result.get("cited_urls", []))
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
