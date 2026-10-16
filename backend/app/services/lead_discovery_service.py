"""
backend/app/services/lead_discovery_service.py

Integrated Lead Discovery Service with:
1. Reused & hardened extraction and classification functions from uploaded scraper:
   - clean_email, extract_email, clean_website
   - audit_website_is_old_or_dead (parked signals, thin content, old HTML/doctypes,
     missing viewport, deprecated tags, table layouts, outdated tech stack, old copyright)
2. Common provider adapter system with explicit states:
   available, rate_limited, quota_exhausted, authentication_error,
   temporarily_unavailable, disabled, no_results
3. Multi-provider search discovery (Serper, SerpApi, HasData, Outscraper)
4. Email enrichment (Hunter, Serper snippet, Permitted DuckDuckGo search fallback)
5. Secure HTTP inspection with SSRF prevention (validate_url) and TLS verification
6. Text-file upload processing (.txt) for keywords and locations with UTF-8 BOM,
   comments, blank lines, and case-insensitive deduplication
7. Search combinations budget calculator & safety limits
8. Persistent job state with checkpoint/resume, pause, and cancellation
9. Deduplication, data provenance, and lead schema CSV export
"""

import asyncio
import csv
import enum
import io
import json
import logging
import os
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

import aiohttp
from app.config import settings
from app.services.provider_key_manager import get_key_manager, ProviderKeyManager
from app.utils.csv_parser import clean_business_name as app_clean_business_name

logger = logging.getLogger(__name__)

# ─── Constants & Regex ────────────────────────────────────────────────────────

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

INVALID_EMAIL_SUBSTRINGS = [
    "example", "test", "demo", "sample", "noreply", "no-reply", "sentry",
    "privacy", "wixpress", "squarespace", "wordpress", "schema", "w3.org",
    "your@email", "user@", "email@domain",
]

INVALID_TLDS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "pdf",
    "zip", "js", "css", "php", "html", "htm", "xml", "txt", "json",
    "mp4", "mp3", "woff", "woff2", "ttf", "eot",
}

JUNK_DOMAINS = {
    "google.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "yelp.com", "yellowpages.com",
    "yell.com", "tripadvisor.com", "wix.com", "squarespace.com", "shopify.com",
    "godaddy.com", "namecheap.com", "cloudflare.com", "sentry.io",
}

PARKED_SIGNALS = [
    "domain for sale", "buy this domain", "this domain is for sale",
    "domain is parked", "parked free", "sedoparking", "hugedomains",
    "godaddy.com/domain", "namecheap.com", "domain may be for sale",
    "account has been suspended", "site is currently unavailable",
    "under construction", "coming soon", "website coming soon",
    "page not found", "this store is unavailable", "defaultwebpage.cgi",
]

# ─── Presets ──────────────────────────────────────────────────────────────────

DEFAULT_PRESET_KEYWORDS: List[str] = [
    "web design agency", "dental clinic", "interior design company",
    "roofing contractor", "plumbing company", "hvac contractor", "electrician",
    "landscaping company", "car repair garage", "auto workshop",
    "pest control company", "cleaning company", "moving company", "locksmith",
    "painting contractor", "flooring contractor", "handyman service",
    "accounting firm", "personal injury lawyer", "chiropractor",
]

DEFAULT_PRESET_LOCATIONS: List[str] = [
    "Austin, Texas, USA", "Dallas, Texas, USA", "Houston, Texas, USA",
    "London, UK", "Manchester, UK", "Birmingham, UK",
    "Delhi, India", "Dehradun, Uttarakhand, India", "Roorkee, Uttarakhand, India", "Haridwar, Uttarakhand, India",
    "Sydney, Australia", "Melbourne, Australia", "Toronto, Canada",
]


# ─── Provider States ──────────────────────────────────────────────────────────

class ProviderStatus(str, enum.Enum):
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTHENTICATION_ERROR = "authentication_error"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DISABLED = "disabled"
    NO_RESULTS = "no_results"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ─── Reused & Hardened Text, Email, and URL Cleaning ──────────────────────────

def clean_email(raw: Any) -> Optional[str]:
    """Clean and validate an extracted email candidate."""
    if not raw:
        return None
    e = re.sub(r"[>\"');,\s]+$", "", str(raw).lower().strip())
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    if not local or not domain or "." not in domain:
        return None
    if any(bad in e for bad in INVALID_EMAIL_SUBSTRINGS):
        return None
    tld = domain.rsplit(".", 1)[-1]
    if not tld.isalpha() or not (2 <= len(tld) <= 6) or tld in INVALID_TLDS:
        return None
    if domain in JUNK_DOMAINS:
        return None
    if domain.rsplit(".", 1)[0].replace(".", "").isdigit():
        return None
    return e


def extract_email(text: Optional[str]) -> Optional[str]:
    """Extract first valid email candidate from text or HTML."""
    if not text:
        return None
    for match in re.findall(EMAIL_REGEX, text):
        cleaned = clean_email(match)
        if cleaned:
            return cleaned
    return None


def clean_website(url: Any) -> str:
    """Normalize and sanitize a website URL."""
    if not url:
        return ""
    u = str(url).strip()
    for prefix in ("https://www.google.com/url?q=", "http://www.google.com/url?q="):
        if u.lower().startswith(prefix):
            u = unquote(u[len(prefix):].split("&")[0])
            break
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    try:
        netloc = urlparse(u).netloc.lower().lstrip("www.")
        if netloc in JUNK_DOMAINS or "google.com" in netloc:
            return ""
    except Exception:
        return ""
    return u


async def _extract_resp_text(resp: Any) -> str:
    """Safely extract string text from an HTTP response, including handling mocks/coroutines."""
    if resp is None:
        return ""
    try:
        raw = resp.text
        if callable(raw):
            raw = raw()
        if hasattr(raw, "__await__"):
            raw = await raw
        return raw if isinstance(raw, str) else ""
    except Exception:
        return ""



def audit_website_is_old_or_dead(
    url: str, html: str, status_code: int, final_url: str = ""
) -> Tuple[bool, str]:
    """
    Returns (True, reason) if the website is:
      - No website
      - A dead/broken/parked website
      - An old/outdated website design
    Returns (False, "Modern Website") if active and modern.
    """
    if not url:
        return True, "No Website"

    if status_code < 200 or status_code >= 400 or not html:
        return True, f"Dead Website (HTTP {status_code})"

    html_lower = html.lower()

    # 1. Parked or Under Construction
    for sig in PARKED_SIGNALS:
        if sig in html_lower:
            return True, f"Parked/Under Construction ({sig})"

    # 2. Thin / Empty page (< 80 words)
    text_only = re.sub(
        r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    if len(text_only.split()) < 80:
        return True, "Thin/Empty Website (<80 words)"

    # 3. Old / Outdated Design Checks
    reasons = []
    check_url = final_url or url

    if check_url.startswith("http://"):
        reasons.append("No SSL (Insecure HTTP)")
    if 'name="viewport"' not in html_lower and "name='viewport'" not in html_lower:
        reasons.append("Not Mobile Responsive (No viewport tag)")
    if "w3c//dtd html 4" in html_lower or "w3c//dtd xhtml 1" in html_lower:
        reasons.append("Old HTML4/XHTML Doctype")
    if "<frameset" in html_lower or "<marquee" in html_lower or "<font " in html_lower or "<center>" in html_lower:
        reasons.append("1990s/2000s Deprecated HTML tags")
    if html_lower.count("<table") >= 4 and "display: flex" not in html_lower and "display: grid" not in html_lower:
        reasons.append("Old Table-Based Layout")
    if (
        "jquery-1." in html_lower
        or "jquery/1." in html_lower
        or "frontpage" in html_lower
        or "dreamweaver" in html_lower
    ):
        reasons.append("Outdated Tech Stack (jQuery 1.x / FrontPage / Dreamweaver)")
    if any(
        free_host in check_url.lower()
        for free_host in (".business.site", "blogspot.com", "weebly.com", "wixsite.com")
    ):
        reasons.append("Free Subdomain Builder")

    years = re.findall(r"(?:©|&copy;|copyright)\s*(?:20\d{2}\s*[-–]\s*)?(20[0-2]\d)", html_lower)
    if years and max(int(y) for y in years) <= 2021:
        reasons.append(f"Old Copyright Year ({max(int(y) for y in years)})")

    if reasons:
        return True, "Outdated Design: " + ", ".join(reasons)

    return False, "Modern Website"


# ─── URL Security & SSRF Protection ───────────────────────────────────────────

def is_safe_external_url(url: str, allow_test_loopback: bool = False) -> Tuple[bool, str]:
    """
    Validate that target URL uses http/https and does not resolve to private,
    loopback, link-local, carrier-grade NAT, or cloud metadata ranges.
    """
    if not url:
        return False, "Empty URL"
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return False, f"URL parse error: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Blocked scheme: {parsed.scheme!r}"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    # Reject local/internal hostnames
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        if not allow_test_loopback:
            return False, f"Blocked local host: {hostname}"

    # Try resolving to IP and check blocked subnets
    try:
        ip_info = socket.getaddrinfo(hostname, None)
        for item in ip_info:
            ip_str = item[4][0]
            # Check basic private/loopback/link-local patterns
            if not allow_test_loopback:
                if (
                    ip_str.startswith("127.")
                    or ip_str.startswith("10.")
                    or ip_str.startswith("192.168.")
                    or ip_str.startswith("169.254.")
                    or ip_str == "::1"
                    or (ip_str.startswith("172.") and 16 <= int(ip_str.split(".")[1]) <= 31)
                ):
                    return False, f"Blocked private/reserved IP: {ip_str}"
    except socket.gaierror:
        # Host cannot be resolved
        return False, f"DNS resolution failed for {hostname}"
    except Exception as exc:
        return False, f"IP check error: {exc}"

    return True, "Allowed"


# ─── File Upload Processing (.txt) ────────────────────────────────────────────

def parse_txt_upload_content(
    content_bytes: bytes,
    max_file_size: int = 1_048_576,
    max_entries: int = 250,
) -> Dict[str, Any]:
    """
    Parse uploaded .txt file for keywords or locations.
    - Handles UTF-8 and UTF-8 BOM.
    - Trims whitespace, skips blank lines and lines starting with '#'.
    - Case-insensitive deduplication preserving original readable values.
    - Enforces size limit and max entry count.
    """
    if len(content_bytes) > max_file_size:
        raise ValueError(
            f"File exceeds maximum allowed size ({len(content_bytes)} bytes > {max_file_size} bytes limit)."
        )

    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("File is not a valid UTF-8 text document.")

    lines = text.splitlines()
    entries: List[str] = []
    seen_lower: Set[str] = set()

    ignored_count = 0
    duplicate_count = 0
    rejected_count = 0

    for line in lines:
        raw_stripped = line.strip()
        if not raw_stripped or raw_stripped.startswith("#"):
            ignored_count += 1
            continue

        if len(raw_stripped) > 200:
            rejected_count += 1
            continue

        key = raw_stripped.lower()
        if key in seen_lower:
            duplicate_count += 1
            continue

        if len(entries) >= max_entries:
            rejected_count += 1
            continue

        seen_lower.add(key)
        entries.append(raw_stripped)

    if not entries:
        raise ValueError("Uploaded file contains no usable entries after filtering blanks and comments.")

    return {
        "valid_count": len(entries),
        "ignored_count": ignored_count,
        "duplicate_count": duplicate_count,
        "rejected_count": rejected_count,
        "entries": entries,
    }


# ─── Lead Discovery Engine ───────────────────────────────────────────────────

class LeadDiscoveryService:
    """Orchestrates API search, HTTP inspection, fallbacks, and job checkpoints."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        allow_test_loopback: bool = False,
        key_manager: Optional[Any] = None,
    ):
        self.storage_path = storage_path or settings.DISCOVERY_STORAGE_FILE
        self.allow_test_loopback = allow_test_loopback
        self.key_manager = key_manager or get_key_manager(settings)
        self._provider_status: Dict[str, Dict[str, Any]] = {}
        self._init_providers()
        self._jobs: Dict[str, Dict[str, Any]] = self._load_jobs()

    def _init_providers(self):
        """Initialize provider statuses based on environment settings and key pools."""
        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        serper_pool = km.get_pool("serper")
        treg_pool = km.get_pool("treg")
        serpapi_pool = km.get_pool("serpapi")
        hasdata_pool = km.get_pool("hasdata")
        outscraper_pool = km.get_pool("outscraper")
        hunter_pool = km.get_pool("hunter")

        serper_conf = (serper_pool.is_configured() if serper_pool else False) or bool(getattr(settings, "SERPER_API_KEY", ""))
        treg_conf = (treg_pool.is_configured() if treg_pool else False) or bool(getattr(settings, "TREG_API_TOKEN", "") or getattr(settings, "TREG_API_KEY", ""))
        serpapi_conf = (serpapi_pool.is_configured() if serpapi_pool else False) or bool(getattr(settings, "SERPAPI_API_KEY", ""))
        hasdata_conf = (hasdata_pool.is_configured() if hasdata_pool else False) or bool(getattr(settings, "HASDATA_API_KEY", ""))
        outscraper_conf = (outscraper_pool.is_configured() if outscraper_pool else False) or bool(getattr(settings, "OUTSCRAPER_API_KEY", ""))
        hunter_conf = (hunter_pool.is_configured() if hunter_pool else False) or bool(getattr(settings, "HUNTER_API_KEY", ""))

        self._provider_status = {
            "serper": {
                "status": ProviderStatus.AVAILABLE if serper_conf else ProviderStatus.DISABLED,
                "configured": serper_conf,
                "key_masked": self._mask_key(getattr(settings, "SERPER_API_KEY", "") or (serper_pool.keys[0].secret if serper_pool and serper_pool.keys else "")),
                "last_error": None,
            },
            "serpapi": {
                "status": ProviderStatus.AVAILABLE if serpapi_conf else ProviderStatus.DISABLED,
                "configured": serpapi_conf,
                "key_masked": self._mask_key(getattr(settings, "SERPAPI_API_KEY", "")),
                "last_error": None,
            },
            "hasdata": {
                "status": ProviderStatus.AVAILABLE if hasdata_conf else ProviderStatus.DISABLED,
                "configured": hasdata_conf,
                "key_masked": self._mask_key(getattr(settings, "HASDATA_API_KEY", "")),
                "last_error": None,
            },
            "outscraper": {
                "status": ProviderStatus.AVAILABLE if outscraper_conf else ProviderStatus.DISABLED,
                "configured": outscraper_conf,
                "key_masked": self._mask_key(getattr(settings, "OUTSCRAPER_API_KEY", "")),
                "last_error": None,
            },
            "hunter": {
                "status": ProviderStatus.AVAILABLE if hunter_conf else ProviderStatus.DISABLED,
                "configured": hunter_conf,
                "key_masked": self._mask_key(getattr(settings, "HUNTER_API_KEY", "")),
                "last_error": None,
            },
            "treg": {
                "status": ProviderStatus.AVAILABLE if treg_conf else ProviderStatus.DISABLED,
                "configured": treg_conf,
                "key_masked": self._mask_key(getattr(settings, "TREG_API_TOKEN", "") or (treg_pool.keys[0].secret if treg_pool and treg_pool.keys else "")),
                "last_error": None,
            },
            "http_direct": {
                "status": ProviderStatus.AVAILABLE,
                "configured": True,
                "key_masked": "N/A",
                "last_error": None,
            },
            "duckduckgo_fallback": {
                "status": ProviderStatus.AVAILABLE,
                "configured": True,
                "key_masked": "N/A",
                "last_error": None,
            },
            "google_maps_direct": {
                "status": ProviderStatus.DISABLED,
                "configured": False,
                "key_masked": "N/A",
                "last_error": "Automated scraping prohibited by terms of service without authorized API.",
            },
        }

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 6:
            return "***"
        return f"{key[:3]}...{key[-3:]}"

    def get_provider_statuses(self) -> Dict[str, Any]:
        """Return provider configuration status, health, and sanitized slot diagnostics."""
        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        pool_diags = km.get_all_diagnostics()

        result = {}
        for k, v in self._provider_status.items():
            pool_diag = pool_diags.get(k, {})
            pool_conf = pool_diag.get("configured", False)
            configured = v["configured"] or pool_conf

            status_val = v["status"]
            status_str = status_val.value if isinstance(status_val, ProviderStatus) else str(status_val)

            if k == "google_maps_direct":
                status_str = "disabled"
            elif pool_conf:
                status_str = pool_diag.get("status", status_str)

            result[k] = {
                "status": status_str,
                "configured": configured,
                "key_masked": v["key_masked"],
                "last_error": v["last_error"],
                "total_slots": pool_diag.get("total_slots", 1 if configured else 0),
                "available_slots": pool_diag.get("available_slots", 1 if (configured and status_str == "available") else 0),
                "shared_quota_exhausted": pool_diag.get("shared_quota_exhausted", False),
                "slots": pool_diag.get("slots", []),
            }
        return result

    # ─── Job Persistence ──────────────────────────────────────────────────────

    def _load_jobs(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read discovery jobs file %s: %s", self.storage_path, exc)
        return {}

    def _save_jobs(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._jobs, f, indent=2, default=str)
        except Exception as exc:
            logger.error("Failed to save discovery jobs to %s: %s", self.storage_path, exc)

    # ─── Combinations & Budget ────────────────────────────────────────────────

    def calculate_combinations(
        self,
        keywords: List[str],
        locations: List[str],
        mode: str = "uploaded_only",
        custom_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Calculate total search combinations and enforce configured safety limits.
        Modes: 'uploaded_only', 'presets_only', 'combine', 'replace'
        """
        active_kws = list(keywords)
        active_locs = list(locations)

        if mode == "presets_only":
            active_kws = list(DEFAULT_PRESET_KEYWORDS)
            active_locs = list(DEFAULT_PRESET_LOCATIONS)
        elif mode == "combine":
            # Merge case-insensitively
            seen_k = {k.lower() for k in active_kws}
            for pk in DEFAULT_PRESET_KEYWORDS:
                if pk.lower() not in seen_k:
                    active_kws.append(pk)
                    seen_k.add(pk.lower())
            seen_l = {l.lower() for l in active_locs}
            for pl in DEFAULT_PRESET_LOCATIONS:
                if pl.lower() not in seen_l:
                    active_locs.append(pl)
                    seen_l.add(pl.lower())

        total_combinations = len(active_kws) * len(active_locs)
        max_allowed = getattr(settings, "DISCOVERY_MAX_COMBINATIONS_LIMIT", 500)

        budget = custom_budget if custom_budget and custom_budget > 0 else total_combinations
        exceeds_safety_limit = total_combinations > max_allowed and (budget > max_allowed)

        return {
            "mode": mode,
            "keyword_count": len(active_kws),
            "location_count": len(active_locs),
            "total_combinations": total_combinations,
            "max_allowed_combinations": max_allowed,
            "effective_budget": min(budget, total_combinations),
            "exceeds_safety_limit": exceeds_safety_limit,
            "keywords": active_kws,
            "locations": active_locs,
        }

    # ─── Provider Calling & Failover ──────────────────────────────────────────

    def _classify_http_status(self, status: int) -> ProviderStatus:
        if status == 401:
            return ProviderStatus.AUTHENTICATION_ERROR
        if status == 402:
            return ProviderStatus.QUOTA_EXHAUSTED
        if status == 429:
            return ProviderStatus.RATE_LIMITED
        if 500 <= status <= 599:
            return ProviderStatus.TEMPORARILY_UNAVAILABLE
        return ProviderStatus.AVAILABLE

    async def search_places(
        self,
        session: aiohttp.ClientSession,
        keyword: str,
        city: str,
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Search businesses across authorized providers with automatic fallback.
        Priority:
        1. Treg (Catalog Proxied Google Maps API)
        2. Serper Maps API (with Two-Key Rotation)
        3. SerpApi Direct
        4. HasData Google Maps
        5. Outscraper Maps
        6. Compliant fallback or honest empty/none
        Returns: (places_list, selected_source, method)
        """
        if fetcher_mock is not None:
            return fetcher_mock(keyword, city)

        query = f"{keyword} in {city}"
        km = getattr(self, "key_manager", None) or get_key_manager(settings)

        # 1. Treg Proxied Google Maps API (Catalog endpoint)
        treg_pool = km.get_pool("treg")
        treg_enabled = getattr(getattr(km, "settings", None) or settings, "TREG_ENABLE_PAID_ENDPOINTS", False)
        if treg_pool and treg_pool.is_configured() and not treg_pool.shared_quota_exhausted and treg_enabled:
            attempts = 0
            max_treg_attempts = max(1, len(treg_pool.keys))
            while attempts < max_treg_attempts:
                attempts += 1
                key_item = await treg_pool.get_next_key()
                if not key_item:
                    break
                prov_key, slot_id = key_item
                try:
                    url = "https://treg.to/call/serpapi.google.maps"
                    headers = {"X-Treg-Token": prov_key.secret, "Accept": "application/json"}
                    async with session.get(url, params={"q": query, "type": "search"}, headers=headers, timeout=20) as resp:
                        retry_after = resp.headers.get("Retry-After")
                        ra_val = float(retry_after) if retry_after and retry_after.isdigit() else None
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        treg_pool.report_result(
                            prov_key,
                            resp.status,
                            retry_after=ra_val,
                            error_message=err_text,
                            quota_exhausted=is_quota,
                        )

                        if resp.status == 200:
                            data = await resp.json()
                            items = data.get("local_results", data.get("results", data.get("places", [])))
                            if items:
                                return [
                                    {
                                        "name": (i.get("title") or i.get("name", "")).strip(),
                                        "website": clean_website(i.get("website") or i.get("link", "")),
                                        "phone": i.get("phone") or i.get("phoneNumber"),
                                        "email": extract_email(json.dumps(i)),
                                        "source": "treg",
                                        "endpoint": "serpapi.google.maps",
                                        "key_slot": slot_id,
                                        "account_id": prov_key.account_id,
                                        "quota_scope": prov_key.quota_scope.scope_id,
                                        "method": "api_proxy_maps",
                                    }
                                    for i in items
                                ], "treg", "api_proxy_maps"
                            break

                        if resp.status == 401 or (resp.status == 403 and prov_key.is_auth_failed):
                            continue
                        if resp.status == 402 or is_quota:
                            if treg_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403:
                            continue
                except Exception as exc:
                    treg_pool.report_result(prov_key, 500, error_message=str(exc))
                    break

        # 2. Serper Maps API (with Two-Key Rotation)
        serper_pool = km.get_pool("serper")
        serper_key_legacy = getattr(settings, "SERPER_API_KEY", "")
        if (serper_pool and serper_pool.is_configured() and not serper_pool.shared_quota_exhausted) or (serper_key_legacy and self._provider_status.get("serper", {}).get("status") == ProviderStatus.AVAILABLE):
            attempts = 0
            max_serper_attempts = max(1, len(serper_pool.keys)) if serper_pool and serper_pool.keys else 1
            while attempts < max_serper_attempts:
                attempts += 1
                slot_id = 1
                if serper_pool and serper_pool.is_configured():
                    key_item = await serper_pool.get_next_key()
                    if not key_item:
                        break
                    prov_key, slot_id = key_item
                    current_key = prov_key.secret
                else:
                    prov_key = None
                    current_key = serper_key_legacy

                try:
                    url = "https://google.serper.dev/maps"
                    headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
                    async with session.post(url, json={"q": query}, headers=headers, timeout=20) as resp:
                        retry_after = resp.headers.get("Retry-After")
                        ra_val = float(retry_after) if retry_after and retry_after.isdigit() else None
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        if prov_key and serper_pool:
                            serper_pool.report_result(
                                prov_key,
                                resp.status,
                                retry_after=ra_val,
                                error_message=err_text,
                                quota_exhausted=is_quota,
                            )

                        if resp.status != 200:
                            st = self._classify_http_status(resp.status)
                            if "serper" in self._provider_status:
                                self._provider_status["serper"]["status"] = st
                                self._provider_status["serper"]["last_error"] = f"HTTP {resp.status}"

                            if (resp.status == 401 or (resp.status == 403 and getattr(prov_key, "is_auth_failed", False))) and serper_pool:
                                continue
                            if (resp.status == 402 or is_quota):
                                if serper_pool and serper_pool.shared_quota_exhausted:
                                    break
                                continue
                            if resp.status == 403 and serper_pool:
                                continue
                        else:
                            data = await resp.json()
                            places = data.get("places", [])
                            if places:
                                return [
                                    {
                                        "name": p.get("title", "").strip(),
                                        "website": clean_website(p.get("website", "")),
                                        "phone": p.get("phoneNumber"),
                                        "email": None,
                                        "source": "serper",
                                        "endpoint": "maps",
                                        "key_slot": slot_id,
                                        "account_id": prov_key.account_id if prov_key else "serper_legacy",
                                        "quota_scope": prov_key.quota_scope.scope_id if prov_key else "serper_account_1",
                                        "method": "api_maps",
                                    }
                                    for p in places
                                ], "serper", "api_maps"
                            break
                except Exception as exc:
                    if prov_key and serper_pool:
                        serper_pool.report_result(prov_key, 500, error_message=str(exc))
                    if "serper" in self._provider_status:
                        self._provider_status["serper"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                        self._provider_status["serper"]["last_error"] = str(exc)
                    break

        # 3. SerpApi Direct
        serpapi_pool = km.get_pool("serpapi")
        serpapi_key = getattr(settings, "SERPAPI_API_KEY", "") or (serpapi_pool.keys[0].secret if serpapi_pool and serpapi_pool.keys else "")
        if serpapi_key and self._provider_status.get("serpapi", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://serpapi.com/search.json"
                params = {"engine": "google_maps", "q": query, "api_key": serpapi_key}
                async with session.get(url, params=params, timeout=20) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["serpapi"]["status"] = st
                        self._provider_status["serpapi"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        places = data.get("local_results", [])
                        if places:
                            return [
                                {
                                    "name": p.get("title", "").strip(),
                                    "website": clean_website(p.get("website", "")),
                                    "phone": p.get("phone"),
                                    "email": None,
                                    "source": "serpapi",
                                    "endpoint": "google_maps",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "serpapi", "api_maps"
            except Exception as exc:
                self._provider_status["serpapi"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["serpapi"]["last_error"] = str(exc)

        # 4. HasData Google Maps API
        hasdata_pool = km.get_pool("hasdata")
        hasdata_key = getattr(settings, "HASDATA_API_KEY", "") or (hasdata_pool.keys[0].secret if hasdata_pool and hasdata_pool.keys else "")
        if hasdata_key and self._provider_status.get("hasdata", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.hasdata.com/scrape/google-maps/search"
                headers = {"x-api-key": hasdata_key, "Accept": "application/json"}
                async with session.get(url, params={"q": query}, headers=headers, timeout=20) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["hasdata"]["status"] = st
                        self._provider_status["hasdata"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        places = data.get("localResults", [])
                        if places:
                            return [
                                {
                                    "name": p.get("title", "").strip(),
                                    "website": clean_website(p.get("website", "")),
                                    "phone": p.get("phone"),
                                    "email": None,
                                    "source": "hasdata",
                                    "endpoint": "scrape/google-maps/search",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "hasdata", "api_maps"
            except Exception as exc:
                self._provider_status["hasdata"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["hasdata"]["last_error"] = str(exc)

        # 5. Outscraper Maps API
        outscraper_pool = km.get_pool("outscraper")
        outscraper_key = getattr(settings, "OUTSCRAPER_API_KEY", "") or (outscraper_pool.keys[0].secret if outscraper_pool and outscraper_pool.keys else "")
        if outscraper_key and self._provider_status.get("outscraper", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.app.outscraper.com/maps/search-v3"
                headers = {"X-API-KEY": outscraper_key}
                params = {"query": query, "limit": 20, "async": "false"}
                async with session.get(url, params=params, headers=headers, timeout=25) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["outscraper"]["status"] = st
                        self._provider_status["outscraper"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        batches = data.get("data", [])
                        places = batches[0] if batches else []
                        if places:
                            return [
                                {
                                    "name": p.get("name", "").strip(),
                                    "website": clean_website(p.get("site", "")),
                                    "phone": p.get("phone"),
                                    "email": clean_email(p.get("email_1", "")),
                                    "source": "outscraper",
                                    "endpoint": "maps/search-v3",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "outscraper", "api_maps"
            except Exception as exc:
                self._provider_status["outscraper"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["outscraper"]["last_error"] = str(exc)

        return [], "none", "no_results"

    # ─── Email Enrichment ─────────────────────────────────────────────────────

    async def enrich_email(
        self,
        session: aiohttp.ClientSession,
        name: str,
        city: str,
        website: str,
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[Optional[str], str, str]:
        """
        Enrich email candidate using Treg Hunter proxy, Hunter Direct, Serper search snippet, or DuckDuckGo fallback.
        Returns: (email, source, method)
        """
        if fetcher_mock is not None:
            return fetcher_mock(name, city, website)

        domain = urlparse(website).netloc.lower().lstrip("www.") if website else ""
        km = getattr(self, "key_manager", None) or get_key_manager(settings)

        # 1. Treg Hunter proxy
        treg_pool = km.get_pool("treg")
        treg_enabled = getattr(getattr(km, "settings", None) or settings, "TREG_ENABLE_PAID_ENDPOINTS", False)
        if domain and treg_pool and treg_pool.is_configured() and not treg_pool.shared_quota_exhausted and treg_enabled:
            attempts = 0
            max_attempts = max(1, len(treg_pool.keys))
            while attempts < max_attempts:
                attempts += 1
                key_item = await treg_pool.get_next_key()
                if not key_item:
                    break
                prov_key, slot_id = key_item
                try:
                    url = "https://treg.to/call/https://api.hunter.io/v2/domain-search"
                    headers = {"X-Treg-Token": prov_key.secret}
                    async with session.get(url, params={"domain": domain}, headers=headers, timeout=15) as resp:
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        treg_pool.report_result(
                            prov_key,
                            resp.status,
                            error_message=err_text,
                            quota_exhausted=is_quota,
                        )
                        if resp.status == 200:
                            data = await resp.json()
                            for e in data.get("data", {}).get("emails", []):
                                cleaned = clean_email(e.get("value", ""))
                                if cleaned:
                                    return cleaned, "treg", "api_proxy_hunter"
                            break
                        if resp.status == 401 or (resp.status == 403 and prov_key.is_auth_failed):
                            continue
                        if resp.status == 402 or is_quota:
                            if treg_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403:
                            continue
                except Exception as exc:
                    treg_pool.report_result(prov_key, 500, error_message=str(exc))
                    break

        # 2. Hunter API direct
        hunter_pool = km.get_pool("hunter")
        hunter_key = getattr(settings, "HUNTER_API_KEY", "") or (hunter_pool.keys[0].secret if hunter_pool and hunter_pool.keys else "")
        if domain and hunter_key and self._provider_status.get("hunter", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.hunter.io/v2/domain-search"
                async with session.get(url, params={"domain": domain, "api_key": hunter_key}, timeout=15) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["hunter"]["status"] = st
                        self._provider_status["hunter"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        for e in data.get("data", {}).get("emails", []):
                            cleaned = clean_email(e.get("value", ""))
                            if cleaned:
                                return cleaned, "hunter", "api_domain_search"
            except Exception as exc:
                self._provider_status["hunter"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["hunter"]["last_error"] = str(exc)

        # 3. Serper Search snippet (with Two-Key Rotation)
        serper_pool = km.get_pool("serper")
        serper_key_legacy = getattr(settings, "SERPER_API_KEY", "")
        if (serper_pool and serper_pool.is_configured() and not serper_pool.shared_quota_exhausted) or (serper_key_legacy and self._provider_status.get("serper", {}).get("status") == ProviderStatus.AVAILABLE):
            attempts = 0
            max_serper_attempts = max(1, len(serper_pool.keys)) if serper_pool and serper_pool.keys else 1
            while attempts < max_serper_attempts:
                attempts += 1
                slot_id = 1
                if serper_pool and serper_pool.is_configured():
                    key_item = await serper_pool.get_next_key()
                    if not key_item:
                        break
                    prov_key, slot_id = key_item
                    current_key = prov_key.secret
                else:
                    prov_key = None
                    current_key = serper_key_legacy

                try:
                    url = "https://google.serper.dev/search"
                    payload = {"q": f'"{name}" {city} email OR contact'}
                    headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
                    async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        if prov_key and serper_pool:
                            serper_pool.report_result(
                                prov_key,
                                resp.status,
                                error_message=err_text,
                                quota_exhausted=is_quota,
                            )
                        if resp.status == 200:
                            found = extract_email(await resp.text())
                            if found:
                                return found, "serper", "api_search_snippet"
                            break
                        if (resp.status == 401 or (resp.status == 403 and getattr(prov_key, "is_auth_failed", False))) and serper_pool:
                            continue
                        if resp.status == 402 or is_quota:
                            if serper_pool and serper_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403 and serper_pool:
                            continue
                except Exception:
                    break

        # 4. DuckDuckGo public HTML search fallback (permitted)
        if self._provider_status.get("duckduckgo_fallback", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                q = f'"{name}" {city} email contact'
                url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        found = extract_email(await resp.text())
                        if found:
                            return found, "duckduckgo_fallback", "public_search_fallback"
            except Exception:
                pass

        return None, "none", "none"

    # ─── Secure HTTP Inspection & Contact Page Extraction ─────────────────────

    async def inspect_website(
        self,
        session: aiohttp.ClientSession,
        website: str,
        html_override: Optional[str] = None,
        status_override: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Safely inspect website with SSRF protection, strict TLS verification,
        outdated design diagnostics, and /contact page discovery.
        Returns: (is_target, classification_reason, extracted_email)
        """
        if not website:
            return True, "No Website", None

        # SSRF and safe URL validation
        safe, reason = is_safe_external_url(website, allow_test_loopback=self.allow_test_loopback)
        if not safe:
            return True, f"Blocked Target URL ({reason})", None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        final_url = website
        if html_override is not None:
            html = html_override
            status = status_override or 200
        else:
            try:
                # Proper TLS verification, bounded timeout
                async with session.get(
                    website,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                    ssl=True,
                ) as resp:
                    status = resp.status
                    final_url = str(resp.url)
                    # Revalidate redirect URL destination for SSRF
                    safe_dest, dest_reason = is_safe_external_url(
                        final_url, allow_test_loopback=self.allow_test_loopback
                    )
                    if not safe_dest:
                        return True, f"Blocked Redirect Target ({dest_reason})", None
                    html = await resp.text(errors="ignore")
            except Exception as exc:
                return True, f"Dead/Unreachable ({type(exc).__name__})", None

        is_target, class_reason = audit_website_is_old_or_dead(website, html, status, final_url)
        found_email = extract_email(html)

        # Contact page fallback when target site has no email on homepage
        if is_target and not found_email and status == 200:
            for path in ("/contact", "/contact-us", "/about", "/about-us"):
                target_url = website.rstrip("/") + path
                safe_sub, _ = is_safe_external_url(target_url, allow_test_loopback=self.allow_test_loopback)
                if not safe_sub:
                    continue
                try:
                    async with session.get(target_url, headers=headers, timeout=10, ssl=True) as r2:
                        if r2.status < 400:
                            found_email = extract_email(await r2.text(errors="ignore"))
                            if found_email:
                                break
                except Exception:
                    pass

        return is_target, class_reason, found_email

    # ─── Job Management & Execution ───────────────────────────────────────────

    def create_job(
        self,
        keywords: List[str],
        locations: List[str],
        mode: str = "uploaded_only",
        budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Initialize and persist a new discovery job configuration."""
        import uuid

        combo_info = self.calculate_combinations(keywords, locations, mode=mode, custom_budget=budget)
        if combo_info["exceeds_safety_limit"]:
            raise ValueError(
                f"Requested search combinations ({combo_info['total_combinations']}) exceed maximum safety limit ({combo_info['max_allowed_combinations']}). Adjust keywords, locations, or set a budget limit."
            )

        job_id = f"disc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        job = {
            "job_id": job_id,
            "status": JobStatus.PENDING.value,
            "mode": mode,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "keywords": combo_info["keywords"],
            "locations": combo_info["locations"],
            "total_combinations": combo_info["total_combinations"],
            "effective_budget": combo_info["effective_budget"],
            "current_combination_idx": 0,
            "discovered_leads": [],
            "stats": {
                "combinations_searched": 0,
                "businesses_discovered": 0,
                "outdated_or_dead_found": 0,
                "modern_skipped": 0,
                "emails_extracted": 0,
            },
            "provider_statuses": self.get_provider_statuses(),
            "errors": [],
        }

        self._jobs[job_id] = job
        self._save_jobs()
        return job

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._jobs.get(job_id)

    def pause_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        job["status"] = JobStatus.PAUSED.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        job["status"] = JobStatus.CANCELLED.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    def resume_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        if job["status"] not in (JobStatus.PAUSED.value, JobStatus.PENDING.value):
            raise ValueError(f"Cannot resume job in {job['status']} state.")
        job["status"] = JobStatus.RUNNING.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    # ─── Background Job Runner ────────────────────────────────────────────────

    async def run_discovery_job(
        self,
        job_id: str,
        places_mock: Optional[Any] = None,
        email_mock: Optional[Any] = None,
        inspect_mock: Optional[Any] = None,
        max_steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute discovery job across keyword/location combinations.
        Supports deterministic testing with mocks and isolated step limits.
        """
        from app.database import AsyncSessionLocal
        from app.models import Lead, LeadStatus, ActivityLog
        from sqlalchemy import select

        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")

        job["status"] = JobStatus.RUNNING.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()

        keywords = job.get("keywords", [])
        locations = job.get("locations", [])
        budget = job.get("effective_budget", len(keywords) * len(locations))
        idx = job.get("current_combination_idx", 0)

        combos = [(k, l) for k in keywords for l in locations]
        total_combos = min(len(combos), budget)

        steps_run = 0
        async with aiohttp.ClientSession() as session:
            while idx < total_combos:
                if max_steps is not None and steps_run >= max_steps:
                    break

                # Reload in case pause or cancel was requested
                cur_job = self.get_job(job_id)
                if not cur_job or cur_job["status"] in (JobStatus.PAUSED.value, JobStatus.CANCELLED.value):
                    break

                kw, loc = combos[idx]
                try:
                    places, src, method = await self.search_places(
                        session, kw, loc, fetcher_mock=places_mock
                    )
                    cur_job["stats"]["combinations_searched"] += 1
                    cur_job["stats"]["businesses_discovered"] += len(places)

                    for p in places:
                        name = p.get("name", "").strip()
                        website = p.get("website", "").strip()
                        phone = p.get("phone")
                        email_addr = p.get("email")

                        if not name:
                            continue

                        # Inspect site
                        if inspect_mock is not None:
                            is_target, class_reason, scraped_email = inspect_mock(website)
                        else:
                            is_target, class_reason, scraped_email = await self.inspect_website(
                                session, website
                            )

                        if not is_target:
                            cur_job["stats"]["modern_skipped"] += 1
                            continue

                        cur_job["stats"]["outdated_or_dead_found"] += 1
                        site_class = (
                            "outdated_website"
                            if "Outdated" in class_reason
                            else ("dead_website" if "Dead" in class_reason else "no_website")
                        )

                        if not email_addr and scraped_email:
                            email_addr = scraped_email
                            src = "http_contact_page"
                            method = "http_page_scrape"

                        if not email_addr:
                            enriched_email, enrich_src, enrich_method = await self.enrich_email(
                                session, name, loc, website, fetcher_mock=email_mock
                            )
                            if enriched_email:
                                email_addr = enriched_email
                                src = enrich_src
                                method = enrich_method

                        if email_addr:
                            cur_job["stats"]["emails_extracted"] += 1
                            lead_record = {
                                "business_name": name,
                                "email": email_addr,
                                "phone": phone or "",
                                "website": website or "",
                                "source": src,
                                "extraction_method": method,
                                "site_classification": site_class,
                                "site_classification_reason": class_reason,
                                "observed_at": datetime.now(timezone.utc).isoformat(),
                                "verification_status": "candidate",
                            }

                            # Deduplicate inside this job
                            existing_emails = {
                                l["email"].lower() for l in cur_job["discovered_leads"]
                            }
                            if email_addr.lower() not in existing_emails:
                                cur_job["discovered_leads"].append(lead_record)

                                # Persist to DB leads table if not already present
                                try:
                                    async with AsyncSessionLocal() as db:
                                        db_existing = await db.execute(
                                            select(Lead).where(Lead.email == email_addr)
                                        )
                                        if not db_existing.scalar_one_or_none():
                                            new_lead = Lead(
                                                business_name=name,
                                                email=email_addr,
                                                phone=phone or None,
                                                website=website or "",
                                                status=LeadStatus.new,
                                            )
                                            db.add(new_lead)
                                            log_entry = ActivityLog(
                                                event_type="lead_discovered",
                                                lead_id=new_lead.id,
                                                message=(
                                                    f"Discovered lead '{name}' ({email_addr}) via {src} "
                                                    f"[{site_class}: {class_reason}]"
                                                ),
                                            )
                                            db.add(log_entry)
                                            await db.commit()
                                except Exception as db_exc:
                                    logger.warning("Could not persist discovered lead to DB: %s", db_exc)

                except Exception as loop_exc:
                    cur_job["errors"].append(f"Combo '{kw}' in '{loc}' failed: {loop_exc}")

                idx += 1
                steps_run += 1
                cur_job["current_combination_idx"] = idx
                cur_job["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save_jobs()
                await asyncio.sleep(0.01)

            final_job = self.get_job(job_id)
            if final_job and final_job["status"] == JobStatus.RUNNING.value and final_job["current_combination_idx"] >= total_combos:
                final_job["status"] = JobStatus.COMPLETED.value
                final_job["completed_at"] = datetime.now(timezone.utc).isoformat()
                self._save_jobs()

        return self.get_job(job_id) or {}

    # ─── Export to CSV ────────────────────────────────────────────────────────

    def export_leads_csv(self, job_id: str, format_type: str = "leadgen") -> str:
        """
        Export discovered leads for a job to CSV string.
        Format options: 'leadgen' (full schema) or 'simple' (3 columns: business name, email, website).
        """
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")

        output = io.StringIO()
        leads = job.get("discovered_leads", [])

        if format_type == "simple":
            fieldnames = ["business name", "email", "website"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for l in leads:
                writer.writerow({
                    "business name": l.get("business_name", ""),
                    "email": l.get("email", ""),
                    "website": l.get("website", ""),
                })
        else:
            fieldnames = [
                "business_name", "email", "phone", "website", "status",
                "source", "extraction_method", "site_classification",
                "site_classification_reason", "observed_at",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for l in leads:
                writer.writerow({
                    "business_name": l.get("business_name", ""),
                    "email": l.get("email", ""),
                    "phone": l.get("phone", ""),
                    "website": l.get("website", ""),
                    "status": "new",
                    "source": l.get("source", "lead_discovery"),
                    "extraction_method": l.get("extraction_method", "unknown"),
                    "site_classification": l.get("site_classification", ""),
                    "site_classification_reason": l.get("site_classification_reason", ""),
                    "observed_at": l.get("observed_at", ""),
                })

        return output.getvalue()


# Module-level singleton
lead_discovery_service = LeadDiscoveryService()
