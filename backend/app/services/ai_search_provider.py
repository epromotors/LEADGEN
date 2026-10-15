"""
backend/app/services/ai_search_provider.py

Official Perplexity Agent API Provider Adapter.
Communicates with POST https://api.perplexity.ai/v1/agent to perform real-time
web grounding, citation discovery, and brand visibility assessment.

Security & Reliability:
- Strict credential redaction: Never logs or surfaces API keys.
- Safe timeouts and conservative query caps.
- Robust handling of 401/403 (auth), 429 (rate limits with backoff), 5xx, and timeouts.
- Distinguishes generated answer text, extracted citations, and raw search results.
"""

import os
import re
import time
import logging
import urllib.parse
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

PERPLEXITY_AGENT_API_URL = "https://api.perplexity.ai/v1/agent"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRIES = 2
DEFAULT_MODEL = "sonar"


def normalize_domain(domain_or_url: str) -> str:
    """
    Extract and normalize host domain from URL or domain string.
    Removes protocols, www. prefixes, port numbers, paths, queries, and trailing slashes.
    Example: 'https://www.CarMedicMotors.in/services/' -> 'carmedicmotors.in'
    """
    if not domain_or_url:
        return ""
    raw = domain_or_url.strip().lower()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "http://" + raw
    try:
        parsed = urllib.parse.urlparse(raw)
        host = parsed.netloc or parsed.path
        host = host.split(":")[0]  # remove port if present
        if host.startswith("www."):
            host = host[4:]
        return host.strip("/").strip()
    except Exception:
        # Fallback regex strip
        clean = re.sub(r"^https?://", "", raw)
        clean = re.sub(r"^www\.", "", clean)
        return clean.split("/")[0].split(":")[0].strip()


def is_domain_match(citation_url_or_domain: str, target_domain: str) -> bool:
    """
    Safely determine if a cited domain/URL matches the target domain.
    Avoids naive substring false-positives (e.g., 'auto.com' matching 'competitorauto.com').
    Matches exact domain or proper subdomains (e.g., 'blog.target.com' matches 'target.com').
    """
    cited_norm = normalize_domain(citation_url_or_domain)
    target_norm = normalize_domain(target_domain)
    if not cited_norm or not target_norm:
        return False
    if cited_norm == target_norm:
        return True
    if cited_norm.endswith("." + target_norm):
        return True
    return False


def is_brand_mentioned_in_text(text: str, brand_name: str, aliases: Optional[List[str]] = None) -> bool:
    """
    Safely detect brand mentions using word boundaries to prevent substring collisions.
    (e.g., 'car' must not match 'carmedic' or 'carmakers').
    """
    if not text:
        return False
    candidates = [brand_name]
    if aliases:
        candidates.extend(aliases)

    for cand in candidates:
        if not cand or not cand.strip():
            continue
        cleaned = cand.strip()
        # Word boundary pattern; handles special characters safely
        pattern = r"\b" + re.escape(cleaned) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


class PerplexityAgentProvider:
    """
    Client adapter for the official Perplexity Agent API (POST /v1/agent).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = (api_key or os.environ.get("AI_SEARCH_PROVIDER_KEY", "")).strip()
        self.model = model or os.environ.get("AI_SEARCH_MODEL", DEFAULT_MODEL)
        raw_timeout = timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        try:
            self.timeout_seconds = max(5, min(60, int(raw_timeout)))
        except (ValueError, TypeError):
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        self._external_client = client

    def is_configured(self) -> bool:
        """Truthful configuration check: True ONLY when an API key is present."""
        return bool(self.api_key)

    async def execute_query(
        self,
        query: str,
        instructions: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Execute an authenticated query against the Perplexity Agent API.
        Enables web_search tool and parses the response structure.
        """
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "query": query,
                "engine": "Perplexity Agent API",
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "usage": {},
                "latency_ms": 0,
                "error_message": "AI-search provider key is not configured.",
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LEADGEN-AiSearch/1.0",
        }

        payload: Dict[str, Any] = {
            "input": query,
            "instructions": instructions or (
                "You are an objective research assistant. Search the web and provide "
                "a factual, well-grounded summary citing relevant reputable sources."
            ),
            "tools": [{"type": "web_search"}],
            "model": self.model,
        }

        start_time = time.perf_counter()
        active_client = client or self._external_client

        # Internal helper for single HTTP request
        async def _do_request(c: httpx.AsyncClient) -> httpx.Response:
            return await c.post(
                PERPLEXITY_AGENT_API_URL,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )

        response: Optional[httpx.Response] = None
        retries = 0
        last_error_msg = ""
        status_code = 0

        while retries <= DEFAULT_MAX_RETRIES:
            try:
                if active_client:
                    response = await _do_request(active_client)
                else:
                    async with httpx.AsyncClient() as session_client:
                        response = await _do_request(session_client)

                status_code = response.status_code

                # Success
                if status_code == 200:
                    break

                # 401 / 403: Authentication failure - do not retry
                if status_code in (401, 403):
                    logger.error("Perplexity Agent API authentication rejected (HTTP %d)", status_code)
                    return {
                        "status": "auth_failed",
                        "query": query,
                        "engine": "Perplexity Agent API",
                        "model": self.model,
                        "answer_text": "",
                        "citations": [],
                        "cited_urls": [],
                        "search_results": [],
                        "usage": {},
                        "latency_ms": int((time.perf_counter() - start_time) * 1000),
                        "error_message": f"Provider authentication failed (HTTP {status_code}). Please verify AI_SEARCH_PROVIDER_KEY.",
                    }

                # 429: Rate limited or 5xx server error -> retry with exponential backoff
                if status_code == 429 or status_code >= 500:
                    retry_after = 1.0 * (2 ** retries)
                    if response and "Retry-After" in response.headers:
                        try:
                            retry_after = max(1.0, float(response.headers["Retry-After"]))
                        except ValueError:
                            pass
                    retries += 1
                    if retries <= DEFAULT_MAX_RETRIES:
                        logger.warning(
                            "Perplexity API HTTP %d on attempt %d. Backing off for %.1fs...",
                            status_code, retries, retry_after
                        )
                        import asyncio
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue
                    else:
                        last_error_msg = f"Provider returned HTTP {status_code} after {retries} attempts."
                        break

                # Any other unexpected non-200
                last_error_msg = f"Provider returned unexpected HTTP {status_code}."
                break

            except httpx.TimeoutException:
                retries += 1
                if retries <= DEFAULT_MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(1.0)
                    continue
                return {
                    "status": "timeout",
                    "query": query,
                    "engine": "Perplexity Agent API",
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Request timed out after {self.timeout_seconds}s.",
                }
            except Exception as ex:
                logger.error("Exception during Perplexity Agent API request: %s", str(ex))
                return {
                    "status": "error",
                    "query": query,
                    "engine": "Perplexity Agent API",
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Transport or network failure: {str(ex)}",
                }

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if not response or response.status_code != 200:
            final_status = "rate_limited" if status_code == 429 else "error"
            return {
                "status": final_status,
                "query": query,
                "engine": "Perplexity Agent API",
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": last_error_msg or f"Request failed with HTTP {status_code}.",
            }

        # Parse valid JSON response
        try:
            data = response.json()
        except Exception:
            return {
                "status": "malformed_response",
                "query": query,
                "engine": "Perplexity Agent API",
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": "Provider returned invalid or non-JSON payload.",
            }

        return self.parse_agent_response(data, query=query, latency_ms=latency_ms)

    def parse_agent_response(
        self,
        data: Dict[str, Any],
        query: str = "",
        latency_ms: int = 0,
    ) -> Dict[str, Any]:
        """
        Parse and extract response components from official Agent API schema:
        - answer_text: Generated assistant response
        - citations: List of source annotations (url, domain, title)
        - search_results: Raw web search entries if present in reasoning or response
        - usage: Token consumption counts
        """
        answer_parts: List[str] = []
        raw_citations: List[Dict[str, Any]] = []
        search_results: List[Dict[str, Any]] = []

        # 1. Official Agent API schema: output[] -> content[]
        output_blocks = data.get("output", [])
        if isinstance(output_blocks, list):
            for block in output_blocks:
                if not isinstance(block, dict):
                    continue
                contents = block.get("content", [])
                if isinstance(contents, list):
                    for item in contents:
                        if isinstance(item, dict):
                            # Text extraction
                            txt = item.get("text", "")
                            if txt:
                                answer_parts.append(txt)
                            # Annotations extraction (official citation mechanism)
                            ann_list = item.get("annotations", [])
                            if isinstance(ann_list, list):
                                for ann in ann_list:
                                    if isinstance(ann, dict) and ann.get("url"):
                                        raw_citations.append(ann)

        # 2. Fallbacks for compatibility (e.g. root citations list or response_text)
        if not answer_parts:
            fallback_text = (
                data.get("output_text")
                or data.get("text")
                or data.get("response")
                or data.get("answer")
                or ""
            )
            if fallback_text:
                answer_parts.append(str(fallback_text))

        # Root-level citations array
        root_citations = data.get("citations", [])
        if isinstance(root_citations, list):
            for item in root_citations:
                if isinstance(item, str) and item.startswith("http"):
                    raw_citations.append({"url": item})
                elif isinstance(item, dict) and item.get("url"):
                    raw_citations.append(item)

        # Search results extraction (if agent reasoning includes web_search hits)
        reasoning = data.get("reasoning", {})
        if isinstance(reasoning, dict):
            sr = reasoning.get("search_results", [])
            if isinstance(sr, list):
                search_results.extend([s for s in sr if isinstance(s, dict)])
        if "search_results" in data and isinstance(data["search_results"], list):
            search_results.extend([s for s in data["search_results"] if isinstance(s, dict)])

        answer_text = "\n\n".join(answer_parts).strip()
        # Bound stored excerpt length for storage safety (2000 chars)
        if len(answer_text) > 2000:
            answer_text = answer_text[:2000] + "... [truncated]"

        # Deduplicate and normalize citations
        seen_urls = set()
        normalized_citations: List[Dict[str, str]] = []
        for c in raw_citations:
            url = str(c.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            domain = normalize_domain(url)
            title = c.get("title", "") or domain
            normalized_citations.append({
                "url": url,
                "domain": domain,
                "title": str(title),
            })

        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}

        return {
            "status": "success",
            "query": query,
            "engine": "Perplexity Agent API",
            "model": data.get("model", self.model),
            "answer_text": answer_text,
            "citations": normalized_citations,
            "cited_urls": [c["url"] for c in normalized_citations],
            "search_results": search_results,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "latency_ms": latency_ms,
            "error_message": None,
        }
