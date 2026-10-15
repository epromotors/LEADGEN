"""
backend/app/services/ai_search_provider.py

Multi-Provider AI-Search Visibility Adapters.
Supports:
1. Perplexity Agent API (POST https://api.perplexity.ai/v1/agent)
2. OpenRouter API (POST https://openrouter.ai/api/v1/chat/completions)
3. Google Gemini API with Google Search Grounding (POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent)

Security & Reliability:
- Strict credential redaction: Never logs or surfaces API keys.
- Safe timeouts and conservative query caps.
- Robust handling of 401/403 (auth), 402 (credit required), 429 (rate limits with backoff), 5xx, and timeouts.
- Distinguishes generated answer text, extracted citations, and raw search results.
- Accurately tracks free-tier quotas and cost risk profiles.
"""

import os
import re
import time
import logging
import urllib.parse
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# Constants & Defaults
PERPLEXITY_AGENT_API_URL = "https://api.perplexity.ai/v1/agent"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRIES = 2

DEFAULT_PERPLEXITY_MODEL = "sonar"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


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
        clean = re.sub(r"^https?://", "", raw)
        clean = re.sub(r"^www\.", "", clean)
        return clean.split("/")[0].split(":")[0].strip()


def redact_sensitive_credentials(text: str, secrets: Optional[List[str]] = None) -> str:
    """Safely redact API keys and sensitive tokens from strings, URLs, and error messages."""
    if not text:
        return ""
    redacted = str(text)
    if secrets:
        for s in secrets:
            if s and len(s) >= 4:
                redacted = redacted.replace(s, "[REDACTED_API_KEY]")
    # Also redact generic patterns matching key=... or Bearer ...
    redacted = re.sub(r'(key=)[^\s&"\']+', r'\1[REDACTED_API_KEY]', redacted, flags=re.IGNORECASE)
    redacted = re.sub(r'(Bearer\s+)[^\s"\']+', r'\1[REDACTED_API_KEY]', redacted, flags=re.IGNORECASE)
    return redacted


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
        pattern = r"\b" + re.escape(cleaned) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def extract_urls_from_text(text: str) -> List[Dict[str, str]]:
    """
    Extract embedded markdown links [Title](https://...) and standalone URLs from text.
    """
    citations = []
    seen_urls = set()

    # Markdown links: [Title](URL)
    md_pattern = r"\[([^\]]+)\]\((https?://[^\s\)]+)\)"
    for title, url in re.findall(md_pattern, text):
        clean_url = url.strip().rstrip(".,;:)")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            citations.append({
                "url": clean_url,
                "domain": normalize_domain(clean_url),
                "title": title.strip(),
            })

    # Standalone URLs: https://...
    raw_pattern = r"(https?://[^\s\(\)\[\]<>\"]+)"
    for url in re.findall(raw_pattern, text):
        clean_url = url.strip().rstrip(".,;:)")
        if clean_url not in seen_urls:
            seen_urls.add(clean_url)
            citations.append({
                "url": clean_url,
                "domain": normalize_domain(clean_url),
                "title": normalize_domain(clean_url),
            })

    return citations


# ─── 1. Perplexity Agent API Provider ────────────────────────────────────────

class PerplexityAgentProvider:
    """
    Client adapter for the official Perplexity Agent API (POST /v1/agent).
    """

    provider_id: str = "perplexity"
    provider_name: str = "Perplexity Agent API"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = (
            api_key
            or os.environ.get("AI_SEARCH_PROVIDER_KEY", "")
            or os.environ.get("PERPLEXITY_API_KEY", "")
        ).strip()
        self.model = model or os.environ.get("AI_SEARCH_MODEL", DEFAULT_PERPLEXITY_MODEL)
        raw_timeout = timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        try:
            self.timeout_seconds = max(5, min(60, int(raw_timeout)))
        except (ValueError, TypeError):
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        self._external_client = client

    def is_configured(self) -> bool:
        """Truthful configuration check: True ONLY when an API key is present."""
        return bool(self.api_key)

    def get_tier_info(self) -> Dict[str, Any]:
        return {
            "tier": "Paid / Credit-Based",
            "free_tier_limits": "Usage-based billing on Perplexity API ($5/1000 searches)",
            "cost_risk": "Calls incur usage charges against account credit balance",
            "grounding_method": "Perplexity Live Web Search Tool",
        }

    async def execute_query(
        self,
        query: str,
        instructions: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": 0,
                "error_message": "Perplexity API key is not configured. Set AI_SEARCH_PROVIDER_KEY.",
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

                if status_code == 200:
                    break

                if status_code in (401, 403):
                    logger.error("Perplexity Agent API authentication rejected (HTTP %d)", status_code)
                    return {
                        "status": "auth_failed",
                        "query": query,
                        "engine": self.provider_name,
                        "model": self.model,
                        "answer_text": "",
                        "citations": [],
                        "cited_urls": [],
                        "search_results": [],
                        "grounding_active": False,
                        "usage": {},
                        "latency_ms": int((time.perf_counter() - start_time) * 1000),
                        "error_message": f"Provider authentication failed (HTTP {status_code}). Please verify AI_SEARCH_PROVIDER_KEY.",
                    }

                if status_code == 429 or status_code >= 500:
                    retry_after = 1.0 * (2 ** retries)
                    if response and "Retry-After" in response.headers:
                        try:
                            retry_after = max(1.0, float(response.headers["Retry-After"]))
                        except ValueError:
                            pass
                    retries += 1
                    if retries <= DEFAULT_MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue
                    else:
                        last_error_msg = f"Provider returned HTTP {status_code} after {retries} attempts."
                        break

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
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Request timed out after {self.timeout_seconds}s.",
                }
            except Exception as ex:
                return {
                    "status": "error",
                    "query": query,
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
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
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": last_error_msg or f"Request failed with HTTP {status_code}.",
            }

        try:
            data = response.json()
        except Exception:
            return {
                "status": "malformed_response",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
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
        answer_parts: List[str] = []
        raw_citations: List[Dict[str, Any]] = []
        search_results: List[Dict[str, Any]] = []

        output_blocks = data.get("output", [])
        if isinstance(output_blocks, list):
            for block in output_blocks:
                if not isinstance(block, dict):
                    continue
                contents = block.get("content", [])
                if isinstance(contents, list):
                    for item in contents:
                        if isinstance(item, dict):
                            txt = item.get("text", "")
                            if txt:
                                answer_parts.append(txt)
                            ann_list = item.get("annotations", [])
                            if isinstance(ann_list, list):
                                for ann in ann_list:
                                    if isinstance(ann, dict) and ann.get("url"):
                                        raw_citations.append(ann)

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

        root_citations = data.get("citations", [])
        if isinstance(root_citations, list):
            for item in root_citations:
                if isinstance(item, str) and item.startswith("http"):
                    raw_citations.append({"url": item})
                elif isinstance(item, dict) and item.get("url"):
                    raw_citations.append(item)

        reasoning = data.get("reasoning", {})
        if isinstance(reasoning, dict):
            sr = reasoning.get("search_results", [])
            if isinstance(sr, list):
                search_results.extend([s for s in sr if isinstance(s, dict)])
        if "search_results" in data and isinstance(data["search_results"], list):
            search_results.extend([s for s in data["search_results"] if isinstance(s, dict)])

        answer_text = "\n\n".join(answer_parts).strip()
        if len(answer_text) > 2000:
            answer_text = answer_text[:2000] + "... [truncated]"

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

        # Fallback URL extraction from markdown text if no annotations were provided
        if not normalized_citations and answer_text:
            text_links = extract_urls_from_text(answer_text)
            for tl in text_links:
                if tl["url"] not in seen_urls:
                    seen_urls.add(tl["url"])
                    normalized_citations.append(tl)

        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}

        return {
            "status": "success",
            "query": query,
            "engine": self.provider_name,
            "model": data.get("model", self.model),
            "answer_text": answer_text,
            "citations": normalized_citations,
            "cited_urls": [c["url"] for c in normalized_citations],
            "search_results": search_results,
            "grounding_active": len(normalized_citations) > 0,
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "latency_ms": latency_ms,
            "error_message": None,
        }


# ─── 2. OpenRouter API Provider ──────────────────────────────────────────────

class OpenRouterAgentProvider:
    """
    Client adapter for OpenRouter API (POST https://openrouter.ai/api/v1/chat/completions).
    Supports free-tier models (e.g. meta-llama/llama-3.3-70b-instruct:free) and web search tools.
    """

    provider_id: str = "openrouter"
    provider_name: str = "OpenRouter"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enable_web_search: bool = True,
        timeout_seconds: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = (api_key or os.environ.get("OPENROUTER_API_KEY", "")).strip()
        self.model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
        self.enable_web_search = enable_web_search
        raw_timeout = timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        try:
            self.timeout_seconds = max(5, min(60, int(raw_timeout)))
        except (ValueError, TypeError):
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        self._external_client = client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def is_free_model(self) -> bool:
        return self.model.endswith(":free")

    def get_tier_info(self) -> Dict[str, Any]:
        is_free = self.is_free_model()
        return {
            "tier": "Free Inference" if is_free else "Paid Inference",
            "model": self.model,
            "is_free_model": is_free,
            "web_search_enabled": self.enable_web_search,
            "free_tier_limits": (
                "Free token inference available on :free models"
                if is_free
                else "Standard token inference billing applies"
            ),
            "cost_risk": (
                "Web search tool incurs ~$0.007/query fee from account credits. "
                "Without credit balance, web-grounded queries may fail with HTTP 402."
                if self.enable_web_search
                else "Zero cost on :free models when web search is disabled."
            ),
            "grounding_method": "OpenRouter Web Search Tool" if self.enable_web_search else "Model Internal Knowledge",
        }

    async def execute_query(
        self,
        query: str,
        instructions: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": 0,
                "error_message": "OpenRouter API key is not configured. Set OPENROUTER_API_KEY.",
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tebsolutions.in",
            "X-Title": "LEADGEN AI Visibility",
        }

        messages = [
            {
                "role": "system",
                "content": instructions or (
                    "You are an objective search analyst. Provide a factual, accurate summary "
                    "answering the user query. Ground your response with live web citations, citing URLs and source names."
                ),
            },
            {"role": "user", "content": query},
        ]

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if self.enable_web_search:
            # Enable OpenRouter web_search server tool
            payload["tools"] = [{"type": "openrouter:web_search"}]

        start_time = time.perf_counter()
        active_client = client or self._external_client

        async def _do_request(c: httpx.AsyncClient) -> httpx.Response:
            return await c.post(
                OPENROUTER_API_URL,
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

                if status_code == 200:
                    break

                if status_code in (401, 403):
                    return {
                        "status": "auth_failed",
                        "query": query,
                        "engine": self.provider_name,
                        "model": self.model,
                        "answer_text": "",
                        "citations": [],
                        "cited_urls": [],
                        "search_results": [],
                        "grounding_active": False,
                        "usage": {},
                        "latency_ms": int((time.perf_counter() - start_time) * 1000),
                        "error_message": f"OpenRouter authentication failed (HTTP {status_code}). Verify OPENROUTER_API_KEY.",
                    }

                if status_code == 402:
                    return {
                        "status": "payment_required",
                        "query": query,
                        "engine": self.provider_name,
                        "model": self.model,
                        "answer_text": "",
                        "citations": [],
                        "cited_urls": [],
                        "search_results": [],
                        "grounding_active": False,
                        "usage": {},
                        "latency_ms": int((time.perf_counter() - start_time) * 1000),
                        "error_message": "OpenRouter payment required (HTTP 402): Account credit needed for web search or paid model.",
                    }

                if status_code == 429 or status_code >= 500:
                    retries += 1
                    if retries <= DEFAULT_MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(1.0 * (2 ** retries))
                        continue
                    last_error_msg = f"OpenRouter returned HTTP {status_code} after retries."
                    break

                last_error_msg = f"OpenRouter returned HTTP {status_code}."
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
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"OpenRouter request timed out after {self.timeout_seconds}s.",
                }
            except Exception as ex:
                return {
                    "status": "error",
                    "query": query,
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Transport failure: {str(ex)}",
                }

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if not response or response.status_code != 200:
            final_status = "rate_limited" if status_code == 429 else "error"
            return {
                "status": final_status,
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": last_error_msg or f"Request failed with HTTP {status_code}.",
            }

        try:
            data = response.json()
        except Exception:
            return {
                "status": "malformed_response",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": "OpenRouter returned invalid JSON.",
            }

        return self.parse_openrouter_response(data, query=query, latency_ms=latency_ms)

    def parse_openrouter_response(
        self,
        data: Dict[str, Any],
        query: str = "",
        latency_ms: int = 0,
    ) -> Dict[str, Any]:
        choices = data.get("choices", [])
        answer_text = ""
        annotations: List[Dict[str, Any]] = []

        if isinstance(choices, list) and choices:
            msg = choices[0].get("message", {})
            answer_text = msg.get("content", "") or ""
            # Some providers attach annotations or citations inside message
            if "annotations" in msg and isinstance(msg["annotations"], list):
                annotations.extend(msg["annotations"])

        # Also check root level citations array if returned
        if "citations" in data and isinstance(data["citations"], list):
            for c in data["citations"]:
                if isinstance(c, str):
                    annotations.append({"url": c})
                elif isinstance(c, dict):
                    annotations.append(c)

        if len(answer_text) > 2000:
            answer_text = answer_text[:2000] + "... [truncated]"

        # Deduplicate and normalize citations
        seen_urls = set()
        normalized_citations: List[Dict[str, str]] = []
        for a in annotations:
            url = str(a.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            normalized_citations.append({
                "url": url,
                "domain": normalize_domain(url),
                "title": a.get("title", "") or normalize_domain(url),
            })

        # Fallback to extracting markdown/plain URLs from generated text
        if not normalized_citations and answer_text:
            text_links = extract_urls_from_text(answer_text)
            for tl in text_links:
                if tl["url"] not in seen_urls:
                    seen_urls.add(tl["url"])
                    normalized_citations.append(tl)

        usage = data.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}

        return {
            "status": "success",
            "query": query,
            "engine": self.provider_name,
            "model": data.get("model", self.model),
            "answer_text": answer_text,
            "citations": normalized_citations,
            "cited_urls": [c["url"] for c in normalized_citations],
            "search_results": [],
            "grounding_active": len(normalized_citations) > 0,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "latency_ms": latency_ms,
            "error_message": None,
        }


# ─── 3. Google Gemini API Provider with Search Grounding ─────────────────────

class GeminiSearchProvider:
    """
    Client adapter for Google Gemini API with Google Search Grounding.
    Endpoint: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
    Extracts real answer text and source citations from groundingMetadata.groundingChunks.
    """

    provider_id: str = "gemini"
    provider_name: str = "Google Gemini API"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enable_search_grounding: bool = True,
        timeout_seconds: Optional[int] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.enable_search_grounding = enable_search_grounding
        raw_timeout = timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        try:
            self.timeout_seconds = max(5, min(60, int(raw_timeout)))
        except (ValueError, TypeError):
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        self._external_client = client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_tier_info(self) -> Dict[str, Any]:
        return {
            "tier": "Google AI Studio Free Tier",
            "model": self.model,
            "search_grounding_enabled": self.enable_search_grounding,
            "free_tier_limits": (
                "5,000 free Google Search queries/month in Google AI Studio. "
                "Flash models quota: 15 Requests/Min, 1,500 Requests/Day free of charge."
            ),
            "cost_risk": "Zero charge when within Google AI Studio monthly free allowance of 5,000 search queries.",
            "grounding_method": "Google Search Grounding (groundingMetadata.groundingChunks)",
        }

    async def execute_query(
        self,
        query: str,
        instructions: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": 0,
                "error_message": "Google Gemini API key is not configured. Set GEMINI_API_KEY.",
            }

        endpoint = f"{GEMINI_API_BASE_URL}/{self.model}:generateContent"

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        contents = [
            {
                "role": "user",
                "parts": [{"text": query}],
            }
        ]

        payload: Dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {
                "parts": [
                    {
                        "text": instructions or (
                            "You are an objective search analyst. Provide a factual summary "
                            "grounded in real-time web search and reference relevant sources."
                        )
                    }
                ]
            },
        }

        if self.enable_search_grounding:
            # Enable Google Search grounding tool
            payload["tools"] = [{"google_search": {}}]

        start_time = time.perf_counter()
        active_client = client or self._external_client

        async def _do_request(c: httpx.AsyncClient) -> httpx.Response:
            return await c.post(
                endpoint,
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

                if status_code == 200:
                    break

                if status_code in (401, 403) or (status_code == 400 and ("api key" in response.text.lower() or "invalid" in response.text.lower())):
                    return {
                        "status": "auth_failed",
                        "query": query,
                        "engine": self.provider_name,
                        "model": self.model,
                        "answer_text": "",
                        "citations": [],
                        "cited_urls": [],
                        "search_results": [],
                        "grounding_active": False,
                        "usage": {},
                        "latency_ms": int((time.perf_counter() - start_time) * 1000),
                        "error_message": f"Gemini API authentication failed (HTTP {status_code}). Verify GEMINI_API_KEY.",
                    }

                if status_code == 429:
                    retries += 1
                    if retries <= DEFAULT_MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(0.05 * (2 ** retries))
                        continue
                    last_error_msg = "Gemini quota or rate limit exceeded (HTTP 429). Free tier limit reached."
                    break

                if status_code >= 500:
                    retries += 1
                    if retries <= DEFAULT_MAX_RETRIES:
                        import asyncio
                        await asyncio.sleep(0.05 * (2 ** retries))
                        continue
                    last_error_msg = f"Gemini server error (HTTP {status_code})."
                    break

                last_error_msg = f"Gemini API returned HTTP {status_code}."
                break

            except httpx.TimeoutException as ex:
                retries += 1
                if retries <= DEFAULT_MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(0.05)
                    continue
                safe_msg = redact_sensitive_credentials(str(ex), [self.api_key])
                return {
                    "status": "timeout",
                    "query": query,
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Gemini request timed out after {self.timeout_seconds}s: {safe_msg}",
                }
            except Exception as ex:
                safe_msg = redact_sensitive_credentials(str(ex), [self.api_key])
                return {
                    "status": "error",
                    "query": query,
                    "engine": self.provider_name,
                    "model": self.model,
                    "answer_text": "",
                    "citations": [],
                    "cited_urls": [],
                    "search_results": [],
                    "grounding_active": False,
                    "usage": {},
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "error_message": f"Gemini connection error: {safe_msg}",
                }

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        if not response or response.status_code != 200:
            final_status = "rate_limited" if status_code == 429 else "error"
            return {
                "status": final_status,
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": last_error_msg or f"Request failed with HTTP {status_code}.",
            }

        try:
            data = response.json()
        except Exception:
            return {
                "status": "malformed_response",
                "query": query,
                "engine": self.provider_name,
                "model": self.model,
                "answer_text": "",
                "citations": [],
                "cited_urls": [],
                "search_results": [],
                "grounding_active": False,
                "usage": {},
                "latency_ms": latency_ms,
                "error_message": "Gemini API returned non-JSON payload.",
            }

        return self.parse_gemini_response(data, query=query, latency_ms=latency_ms)

    def parse_gemini_response(
        self,
        data: Dict[str, Any],
        query: str = "",
        latency_ms: int = 0,
    ) -> Dict[str, Any]:
        candidates = data.get("candidates", [])
        answer_text = ""
        citations: List[Dict[str, str]] = []
        search_queries: List[str] = []
        grounding_active = False

        if isinstance(candidates, list) and candidates:
            cand = candidates[0]
            # 1. Text extraction
            content = cand.get("content", {})
            parts = content.get("parts", [])
            text_blocks = []
            for p in parts:
                if isinstance(p, dict) and "text" in p:
                    text_blocks.append(p["text"])
            answer_text = "\n\n".join(text_blocks).strip()

            # 2. Google Search Grounding metadata extraction
            grounding_meta = cand.get("groundingMetadata", {})
            if isinstance(grounding_meta, dict):
                search_queries = grounding_meta.get("webSearchQueries", []) or []
                chunks = grounding_meta.get("groundingChunks", []) or []
                seen_urls = set()
                for chunk in chunks:
                    if not isinstance(chunk, dict):
                        continue
                    web = chunk.get("web", {})
                    uri = web.get("uri", "")
                    title = web.get("title", "")
                    if uri and uri not in seen_urls:
                        seen_urls.add(uri)
                        citations.append({
                            "url": uri,
                            "domain": normalize_domain(uri),
                            "title": title or normalize_domain(uri),
                        })
                if citations or search_queries:
                    grounding_active = True

        if len(answer_text) > 2000:
            answer_text = answer_text[:2000] + "... [truncated]"

        # Fallback to extracting markdown URLs from text if grounding chunks were not populated
        if not citations and answer_text:
            text_links = extract_urls_from_text(answer_text)
            for tl in text_links:
                citations.append(tl)

        usage = data.get("usageMetadata", {})
        if not isinstance(usage, dict):
            usage = {}

        return {
            "status": "success",
            "query": query,
            "engine": self.provider_name,
            "model": self.model,
            "answer_text": answer_text,
            "citations": citations,
            "cited_urls": [c["url"] for c in citations],
            "search_results": [{"query": sq} for sq in search_queries],
            "grounding_active": grounding_active,
            "usage": {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            },
            "latency_ms": latency_ms,
            "error_message": None,
        }
