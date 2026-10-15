"""Isolated browser evidence provider for the LEADGEN audit engine.

This module implements the browser-side evidence capture using Python
Playwright.  It is designed to:

  - Be disabled by default (no browser is launched unless BROWSER_ENABLED=true).
  - Never launch a browser at module import time.
  - Run in a fully isolated context (no user profile, no credentials).
  - Enforce URL security before and after navigation.
  - Guarantee cleanup in all failure paths.
  - Return structured evidence regardless of success or failure.
  - Never crash or raise through to the caller — failures are captured in the
    evidence contract.

Security note — DNS rebinding TOCTOU mitigation (Phase 2 Final)
────────────────────────────────────────────────────────────────
A policy-aware HTTP/CONNECT proxy (browser.proxy.PolicyProxy) is started
before each browser capture.  Chromium is directed to use this proxy via
--proxy-server and cannot bypass it via --proxy-bypass-list=<-loopback>.

The proxy resolves each destination hostname itself and rejects connections
where any resolved address is in a blocked IP range BEFORE opening the
upstream socket.  Because the same addr_info entry that was validated is used
for socket.connect(), there is no TOCTOU gap between validation and the
actual TCP connection.  Chromium never resolves hostnames independently.

URL-level validation (validate_url() in security.py) continues to run as a
defence-in-depth layer before navigation and at the route-handler boundary.

See browser/proxy.py for the proxy implementation and security invariants.
See security.py for the blocked IP ranges and remaining limitations.

"""

from __future__ import annotations

import logging
import os
import posixpath
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Status constants ──────────────────────────────────────────────────────────
# These are string constants, not an enum, so they serialise cleanly to JSON.

class BrowserStatus:
    """Evidence provider status values."""
    DISABLED   = "DISABLED"       # browser support is off in configuration
    SUCCESS    = "SUCCESS"        # all evidence captured
    PARTIAL    = "PARTIAL"        # some evidence captured; some missing
    TIMEOUT    = "TIMEOUT"        # navigation or operation timed out
    BLOCKED    = "BLOCKED"        # URL blocked by security policy
    CRASHED    = "CRASHED"        # browser process crashed
    FAILED     = "FAILED"         # launch or other unrecoverable failure
    UNAVAILABLE = "UNAVAILABLE"   # Playwright not installed


# ── Evidence contract ─────────────────────────────────────────────────────────

@dataclass
class BrowserEvidence:
    """Typed, machine-readable browser evidence record.

    All fields are optional or have safe defaults so that partial evidence is
    still useful.  The 'provider_status' field is always set; it is the first
    thing the consumer should read.

    Field limits:
        dom_snippet:       max 16 KB of rendered HTML (if captured)
        console_errors:    max 20 entries
        failed_requests:   max 20 entries
        headings:          all headings found on page (h1–h6 only)
    """
    # Identification
    requested_url: str = ""
    final_url: str = ""
    http_status: int | None = None

    # Outcome
    provider_status: str = BrowserStatus.DISABLED
    navigation_ok: bool = False
    provider_error: str | None = None

    # Content evidence
    page_title: str = ""
    meta_description: str = ""
    headings: list[dict[str, str]] = field(default_factory=list)
    visible_text_chars: int = 0
    has_visible_text: bool = False

    # Structure indicators
    has_nav: bool = False
    internal_link_count: int = 0
    has_cta: bool = False
    has_form: bool = False

    # Rendered DOM (bounded)
    dom_snippet: str = ""

    # Error signals
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)

    # Timing
    navigation_timeout_ms: int = 0
    elapsed_ms: int = 0
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Screenshot (only if enabled)
    screenshot_path: str | None = None
    screenshot_size_kb: float | None = None

    # Difference signals (populated by audit_engine when comparing HTTP vs rendered)
    js_rendered_title: str | None = None
    js_rendered_headings: list[dict[str, str]] | None = None

    # Lab performance metrics (Phase 3 WS-B — score-neutral synthetic measurements)
    # Note: These are lab/synthetic values, not real-user field data.
    lab_lcp_ms: int | None = None
    lab_cls: float | None = None
    lab_ttfb_ms: int | None = None
    lab_metrics_available: bool = False

    # Multi-page selection signals (Phase 3 WS-C)
    selection_rank: int = 0
    inbound_links_count: int = 0

    # Advanced Web-Design Diagnostics (Domain H)
    has_horizontal_overflow: bool = False
    overflow_px: int = 0
    design_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict compatible with the factor evidence list."""
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "http_status": self.http_status,
            "provider_status": self.provider_status,
            "navigation_ok": self.navigation_ok,
            "provider_error": self.provider_error,
            "page_title": self.page_title,
            "meta_description": self.meta_description,
            "headings": self.headings,
            "visible_text_chars": self.visible_text_chars,
            "has_visible_text": self.has_visible_text,
            "has_nav": self.has_nav,
            "internal_link_count": self.internal_link_count,
            "has_cta": self.has_cta,
            "has_form": self.has_form,
            "dom_snippet": self.dom_snippet,
            "console_errors": self.console_errors,
            "failed_requests": self.failed_requests,
            "navigation_timeout_ms": self.navigation_timeout_ms,
            "elapsed_ms": self.elapsed_ms,
            "captured_at": self.captured_at,
            "screenshot_path": self.screenshot_path,
            "screenshot_size_kb": self.screenshot_size_kb,
            "js_rendered_title": self.js_rendered_title,
            "js_rendered_headings": self.js_rendered_headings,
            "lab_lcp_ms": self.lab_lcp_ms,
            "lab_cls": self.lab_cls,
            "lab_ttfb_ms": self.lab_ttfb_ms,
            "lab_metrics_available": self.lab_metrics_available,
            "selection_rank": self.selection_rank,
            "inbound_links_count": self.inbound_links_count,
            "has_horizontal_overflow": self.has_horizontal_overflow,
            "overflow_px": self.overflow_px,
            "design_diagnostics": self.design_diagnostics,
        }

    @staticmethod
    def disabled(url: str = "") -> "BrowserEvidence":
        """Return a safe DISABLED evidence record."""
        return BrowserEvidence(
            requested_url=url,
            provider_status=BrowserStatus.DISABLED,
            provider_error="Browser evidence is disabled in configuration.",
        )

    @staticmethod
    def unavailable(url: str = "", reason: str = "") -> "BrowserEvidence":
        """Return an UNAVAILABLE record when Playwright is not installed."""
        return BrowserEvidence(
            requested_url=url,
            provider_status=BrowserStatus.UNAVAILABLE,
            provider_error=reason or "Playwright is not installed.",
        )

    @staticmethod
    def security_blocked(url: str, reason: str) -> "BrowserEvidence":
        """Return a BLOCKED evidence record for URL security rejections."""
        return BrowserEvidence(
            requested_url=url,
            provider_status=BrowserStatus.BLOCKED,
            provider_error=reason,
        )

    @staticmethod
    def failed(url: str, reason: str) -> "BrowserEvidence":
        """Return a FAILED evidence record."""
        return BrowserEvidence(
            requested_url=url,
            provider_status=BrowserStatus.FAILED,
            provider_error=reason,
        )


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class BrowserConfig:
    """Browser provider configuration.

    All fields have safe defaults; override selectively.

    The enabled field is False by default so the application starts safely
    without requiring browser support.
    """
    enabled: bool = False
    headless: bool = True
    nav_timeout_ms: int = 25_000        # navigation timeout
    op_timeout_ms: int = 15_000         # per-operation timeout (e.g. waitForSelector)
    max_concurrency: int = 2            # simultaneous browser contexts
    budget_seconds: int = 60            # per-site wall-clock budget
    screenshot: bool = False            # capture screenshots?
    screenshot_dir: str = ""            # "" → system tempdir
    screenshot_max_kb: int = 512        # reject screenshots larger than this
    executable: str = ""               # "" → Playwright default (bundled Chromium)

    # DOM snippet limit: we never store more than this many characters of
    # rendered HTML to prevent memory/disk abuse.
    dom_snippet_max_chars: int = 16_384

    # Resource blocking: block heavy assets to reduce bandwidth and risk.
    # "image" and "font" are blocked by default; "script" is NOT blocked
    # because we need JS execution for rendered evidence.
    blocked_resource_types: tuple[str, ...] = ("image", "font", "stylesheet")

    # Loopback allowance: strictly False in production. Only set to True
    # in explicit local fixture tests.
    allow_test_loopback: bool = False

    # Multi-page limit: max pages to capture (homepage + internal pages)
    max_pages: int = 5

    @classmethod
    def from_env(cls) -> "BrowserConfig":
        """Build a config from environment variables with safe defaults."""
        def _bool(key: str, default: bool) -> bool:
            val = os.environ.get(key, "").strip().lower()
            if val in ("1", "true", "yes"):
                return True
            if val in ("0", "false", "no"):
                return False
            return default

        def _int(key: str, default: int) -> int:
            try:
                return int(os.environ.get(key, ""))
            except (ValueError, TypeError):
                return default

        return cls(
            enabled=_bool("BROWSER_ENABLED", False),
            headless=_bool("BROWSER_HEADLESS", True),
            nav_timeout_ms=_int("BROWSER_NAV_TIMEOUT_MS", 25_000),
            op_timeout_ms=_int("BROWSER_OP_TIMEOUT_MS", 15_000),
            max_concurrency=_int("BROWSER_MAX_CONCURRENCY", 2),
            budget_seconds=_int("BROWSER_BUDGET_SECONDS", 60),
            screenshot=_bool("BROWSER_SCREENSHOT", False),
            screenshot_dir=os.environ.get("BROWSER_SCREENSHOT_DIR", ""),
            screenshot_max_kb=_int("BROWSER_SCREENSHOT_MAX_KB", 512),
            executable=os.environ.get("BROWSER_EXECUTABLE", ""),
            allow_test_loopback=_bool("ALLOW_TEST_LOOPBACK", False),
            max_pages=max(1, _int("BROWSER_MAX_PAGES", 5)),
        )


def is_browser_enabled(config: BrowserConfig | None = None) -> bool:
    """Return True only when browser support is enabled in the given config.

    If no config is provided, reads from environment variables.
    """
    cfg = config or BrowserConfig.from_env()
    return cfg.enabled


# ── Playwright availability check (import-time safe) ─────────────────────────

def _playwright_available() -> bool:
    """Return True if the playwright package can be imported without error."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ── Semaphore for concurrency control ─────────────────────────────────────────
# Module-level semaphore: limits simultaneous browser contexts across all
# provider instances.  Initialised lazily so importing this module is safe.
_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()


def _get_semaphore(max_concurrency: int) -> threading.Semaphore:
    global _semaphore
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.Semaphore(max(1, max_concurrency))
    return _semaphore


# ── CTA keywords used during rendered DOM analysis ────────────────────────────
_CTA_KEYWORDS = frozenset({
    "contact", "get started", "book", "schedule", "call", "quote",
    "enquire", "enquiry", "inquiry", "request", "buy", "order",
    "sign up", "subscribe", "register", "demo", "free trial", "download",
    "learn more", "get quote", "get a quote", "talk to us",
})


# ── Multi-page URL normalization and ranking (Phase 3 WS-C) ───────────────────

_TRACKING_QUERY_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid",
    "sessionid", "phpsessid", "jsessionid", "token", "ref", "affiliate",
})


def get_effective_port(parsed: urllib.parse.ParseResult) -> int:
    """Return the effective port for a parsed URL (80 for http, 443 for https)."""
    if parsed.port is not None:
        return parsed.port
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return -1


def is_same_origin_boundary(target_url: str, base_url: str) -> bool:
    """Check if target_url belongs to the same origin boundary as base_url.

    Enforces:
      1. Both schemes must be http or https.
      2. Both schemes must match (no http vs https mixing).
      3. Exact hostname match (case-insensitive, no subdomains).
      4. Exact effective port match (e.g. 80 vs 80, 443 vs 443, 8080 vs 8080).
    """
    if not target_url or not base_url:
        return False
    try:
        t_parsed = urllib.parse.urlparse(target_url.strip())
        b_parsed = urllib.parse.urlparse(base_url.strip())
    except Exception:
        return False

    t_scheme = (t_parsed.scheme or "").lower()
    b_scheme = (b_parsed.scheme or "").lower()
    if t_scheme not in ("http", "https") or b_scheme not in ("http", "https"):
        return False
    if t_scheme != b_scheme:
        return False

    t_host = (t_parsed.hostname or "").lower()
    b_host = (b_parsed.hostname or "").lower()
    if not t_host or not b_host or t_host != b_host:
        return False

    t_port = get_effective_port(t_parsed)
    b_port = get_effective_port(b_parsed)
    return t_port == b_port


def normalize_page_url(url: str, base_url: str = "") -> str | None:
    """Deterministically normalize an auditable HTML page URL.

    Rules:
      1. Scheme and host lowercased.
      2. If base_url is provided, resolves relative URLs against base_url.
      3. Scheme must be http or https.
      4. Fragments (#...) unconditionally removed.
      5. Standard ports removed (80 for http, 443 for https); non-standard retained.
      6. Path dot segments resolved, duplicate slashes collapsed.
      7. Trailing slashes stripped on non-root paths (e.g. /about/ -> /about; / stays /).
      8. Tracking parameters removed, remaining query parameters sorted alphabetically.
      9. Non-HTML auditable resources filtered via is_auditable_page_url.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        resolved = urllib.parse.urljoin(base_url, url.strip()) if base_url else url.strip()
        parsed = urllib.parse.urlparse(resolved)
    except Exception:
        return None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None

    port = parsed.port
    # Effective port check for netloc representation
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443) or port is None:
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    # Path normalization
    raw_path = parsed.path or "/"
    normalized_path = posixpath.normpath(raw_path)
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    # Query normalization
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_params = [
        (k, v) for k, v in query_params
        if k.lower() not in _TRACKING_QUERY_PARAMS and not k.lower().startswith("utm_")
    ]
    if filtered_params:
        filtered_params.sort(key=lambda kv: (kv[0], kv[1]))
        cleaned_query = urllib.parse.urlencode(filtered_params)
    else:
        cleaned_query = ""

    normalized_url = urllib.parse.urlunparse((
        scheme,
        netloc,
        normalized_path,
        "",  # params
        cleaned_query,
        "",  # fragment stripped
    ))

    # Reject non-auditable assets (media, pdfs, low-value paths)
    try:
        from auditor.crawler import is_auditable_page_url
        if not is_auditable_page_url(normalized_url):
            return None
    except Exception:
        try:
            from crawler import is_auditable_page_url
            if not is_auditable_page_url(normalized_url):
                return None
        except Exception:
            path_lower = normalized_path.lower()
            skip_ext = (
                ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
                ".mp4", ".mp3", ".zip", ".css", ".js", ".ico", ".xml",
                ".txt", ".json", ".woff", ".woff2",
            )
            if any(path_lower.endswith(e) for e in skip_ext):
                return None

    return normalized_url


def select_target_pages(
    base_url: str,
    crawled_pages: list[dict] | None = None,
    homepage_soup: Any = None,
    max_pages: int = 5,
    return_counts: bool = False,
) -> list[str] | tuple[list[str], dict[str, int]]:
    """Select up to max_pages target URLs for browser capture.

    Ranking:
      1. Homepage is always selected first at index 0.
      2. Up to max_pages - 1 internal pages are ranked by:
         - Descending count of UNIQUE referring source pages (excluding self-links).
         - Tie-break: Ascending normalized URL string.
      3. Candidate pages are strictly limited to same origin boundary and auditable HTML.
    """
    if max_pages <= 0:
        max_pages = 1

    norm_base = normalize_page_url(base_url, base_url)
    if not norm_base:
        norm_base = base_url.strip()

    source_docs: list[tuple[str, Any]] = []
    candidate_pool: set[str] = set()
    inbound_sources: dict[str, set[str]] = {}

    if homepage_soup is not None:
        source_docs.append((norm_base, homepage_soup))

    if crawled_pages:
        for p in crawled_pages:
            if not isinstance(p, dict):
                continue
            p_url = p.get("final_url") or p.get("url") or ""
            norm_p = normalize_page_url(p_url, norm_base)
            p_soup = p.get("soup")
            if not p_soup and p.get("html"):
                try:
                    from bs4 import BeautifulSoup
                    p_soup = BeautifulSoup(p["html"], "html.parser")
                except Exception:
                    p_soup = None

            if norm_p and is_same_origin_boundary(norm_p, norm_base):
                if norm_p != norm_base:
                    candidate_pool.add(norm_p)
                if p_soup is not None:
                    source_docs.append((norm_p, p_soup))

    # Discover links from all source documents
    for source_url, soup in source_docs:
        if soup is None:
            continue
        try:
            anchors = soup.find_all("a", href=True)
        except Exception:
            continue

        for a in anchors:
            raw_href = (a.get("href") or "").strip()
            if not raw_href or raw_href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                continue
            try:
                target_raw = urllib.parse.urljoin(source_url, raw_href)
            except Exception:
                continue
            target_norm = normalize_page_url(target_raw, norm_base)
            if not target_norm:
                continue
            if not is_same_origin_boundary(target_norm, norm_base):
                continue
            if target_norm == norm_base:
                continue

            candidate_pool.add(target_norm)

            # Self-links do not increase inbound count
            if target_norm == source_url:
                continue

            if target_norm not in inbound_sources:
                inbound_sources[target_norm] = set()
            inbound_sources[target_norm].add(source_url)

    # Sort candidates by (-unique_inbound_count, normalized_url)
    sorted_candidates = sorted(
        candidate_pool,
        key=lambda cand: (-len(inbound_sources.get(cand, set())), cand)
    )

    limit = max(0, max_pages - 1)
    selected_internal = sorted_candidates[:limit]
    final_urls = [norm_base] + selected_internal

    counts = {norm_base: 0}
    for cand in selected_internal:
        counts[cand] = len(inbound_sources.get(cand, set()))

    if return_counts:
        return final_urls, counts
    return final_urls


# ── Browser provider ──────────────────────────────────────────────────────────

class BrowserProvider:
    """Captures browser-rendered evidence for a given URL.

    Usage
    ─────
        config = BrowserConfig(enabled=True, headless=True)
        provider = BrowserProvider(config)
        evidence = provider.capture("https://example.com")
        # evidence.provider_status is always set; check it first.
        # evidence.to_dict() gives a serialisable plain dict.

    Thread safety
    ─────────────
    A single BrowserProvider instance is NOT thread-safe internally, but each
    call to capture() uses its own browser context and cleans up on exit.
    Concurrent callers are bounded by the module-level semaphore.

    Error handling
    ──────────────
    capture() never raises.  All errors are captured in the returned
    BrowserEvidence record.  Callers must not interpret a FAILED or CRASHED
    status as a finding about the audited website.
    """

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig.from_env()

    def capture(self, url: str, deadline: float | None = None) -> BrowserEvidence:
        """Capture browser-rendered evidence for *url*.

        Returns a BrowserEvidence record in all cases; never raises.

        The capture performs:
          1. Configuration and security checks.
          2. Browser launch (using the module-level semaphore).
          3. Navigation to the URL.
          4. Post-navigation security revalidation of the final URL.
          5. Evidence extraction.
          6. Guaranteed browser/context/page cleanup in all paths.
        """
        if not self._config.enabled:
            return BrowserEvidence.disabled(url)

        if not _playwright_available():
            return BrowserEvidence.unavailable(
                url, "Playwright package is not installed. "
                     "Run: pip install playwright && python -m playwright install chromium"
            )

        if deadline is not None and time.perf_counter() >= deadline - 1.0:
            return BrowserEvidence(
                requested_url=url,
                provider_status=BrowserStatus.TIMEOUT,
                provider_error="Site audit budget exhausted before page execution",
            )

        # Pre-navigation security check
        from browser.security import validate_url
        pre_check = validate_url(
            url,
            context="pre-navigation",
            allow_test_loopback=self._config.allow_test_loopback,
        )
        if not pre_check.allowed:
            return BrowserEvidence.security_blocked(url, pre_check.reason)

        # Acquire concurrency slot bounded by deadline
        sem = _get_semaphore(self._config.max_concurrency)
        if deadline is not None:
            rem_budget = deadline - time.perf_counter()
            if rem_budget <= 0.0:
                return BrowserEvidence(
                    requested_url=url,
                    provider_status=BrowserStatus.TIMEOUT,
                    provider_error="Site audit budget exhausted before page execution",
                )
            sem_timeout = min(30, rem_budget)
            acquired = sem.acquire(timeout=sem_timeout)
        else:
            sem_timeout = 30
            acquired = sem.acquire(timeout=30)

        if not acquired:
            if deadline is not None and time.perf_counter() >= deadline:
                return BrowserEvidence(
                    requested_url=url,
                    provider_status=BrowserStatus.TIMEOUT,
                    provider_error="Site audit budget exhausted while waiting for concurrency slot",
                )
            return BrowserEvidence.failed(url, f"Concurrency limit: could not acquire browser slot within {round(sem_timeout, 1)} s")

        try:
            if deadline is not None and time.perf_counter() >= deadline - 0.5:
                return BrowserEvidence(
                    requested_url=url,
                    provider_status=BrowserStatus.TIMEOUT,
                    provider_error="Site audit budget exhausted before page execution",
                )

            # If current thread has an active asyncio event loop (e.g. pytest-anyio or async route),
            # Playwright sync API raises Error. Isolate in a clean worker thread.
            has_loop = False
            try:
                import asyncio
                asyncio.get_running_loop()
                has_loop = True
            except RuntimeError:
                has_loop = False

            if has_loop:
                ev_holder: list[BrowserEvidence] = []
                def _worker() -> None:
                    ev_holder.append(self._capture_with_playwright(url, deadline=deadline))
                t = threading.Thread(target=_worker)
                t.start()
                t.join()
                return ev_holder[0] if ev_holder else BrowserEvidence.failed(url, "Worker thread returned no evidence")
            else:
                return self._capture_with_playwright(url, deadline=deadline)
        finally:
            sem.release()

    def capture_pages(
        self,
        urls: list[str],
        base_url: str = "",
        inbound_counts: dict[str, int] | None = None,
    ) -> list[BrowserEvidence]:
        """Capture browser evidence for a list of URLs within an aggregate budget.

        The first URL is the homepage and is captured first. Remaining internal
        pages are captured respecting the aggregate time budget and concurrency limit.
        """
        if not urls:
            return []

        if not self._config.enabled:
            return [BrowserEvidence.disabled(u) for u in urls]

        if not _playwright_available():
            return [
                BrowserEvidence.unavailable(
                    u,
                    "Playwright package is not installed. "
                    "Run: pip install playwright && python -m playwright install chromium"
                )
                for u in urls
            ]

        # Overall site deadline
        start_time = time.perf_counter()
        site_deadline = start_time + self._config.budget_seconds

        effective_base = base_url or urls[0]
        evidences: list[BrowserEvidence] = []

        # 1. Capture homepage (urls[0])
        now = time.perf_counter()
        if now >= site_deadline - 1.0:
            ev0 = BrowserEvidence(
                requested_url=urls[0],
                provider_status=BrowserStatus.TIMEOUT,
                provider_error="Site audit budget exhausted before page execution",
                selection_rank=0,
                inbound_links_count=inbound_counts.get(urls[0], 0) if inbound_counts else 0,
            )
            return [ev0] + [
                BrowserEvidence(
                    requested_url=u,
                    provider_status=BrowserStatus.TIMEOUT,
                    provider_error="Site audit budget exhausted before page execution",
                    selection_rank=idx,
                    inbound_links_count=inbound_counts.get(u, 0) if inbound_counts else 0,
                )
                for idx, u in enumerate(urls[1:], start=1)
            ]

        # Origin boundary check on homepage
        if effective_base and not is_same_origin_boundary(urls[0], effective_base):
            ev0 = BrowserEvidence.security_blocked(
                urls[0],
                f"URL {urls[0]} exceeds origin boundary for {effective_base}",
            )
        else:
            ev0 = self.capture(urls[0], deadline=site_deadline)

        ev0.selection_rank = 0
        if inbound_counts:
            ev0.inbound_links_count = inbound_counts.get(urls[0], 0)
        evidences.append(ev0)

        if len(urls) == 1:
            return evidences

        # 2. Capture remaining internal pages (urls[1:])
        concurrency = min(2, max(1, self._config.max_concurrency))

        def _capture_page_worker(idx: int, target_url: str) -> BrowserEvidence:
            now_w = time.perf_counter()
            if now_w >= site_deadline - 1.0:
                return BrowserEvidence(
                    requested_url=target_url,
                    provider_status=BrowserStatus.TIMEOUT,
                    provider_error="Site audit budget exhausted before page execution",
                    selection_rank=idx,
                    inbound_links_count=inbound_counts.get(target_url, 0) if inbound_counts else 0,
                )

            if effective_base and not is_same_origin_boundary(target_url, effective_base):
                ev_w = BrowserEvidence.security_blocked(
                    target_url,
                    f"URL {target_url} exceeds origin boundary for {effective_base}",
                )
            else:
                ev_w = self.capture(target_url, deadline=site_deadline)

            ev_w.selection_rank = idx
            if inbound_counts:
                ev_w.inbound_links_count = inbound_counts.get(target_url, 0)
            return ev_w

        remaining_urls = list(enumerate(urls[1:], start=1))

        if concurrency == 1:
            for idx, target_url in remaining_urls:
                ev_p = _capture_page_worker(idx, target_url)
                evidences.append(ev_p)
        else:
            from concurrent.futures import ThreadPoolExecutor
            results_dict: dict[int, BrowserEvidence] = {}
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {}
                for idx, target_url in remaining_urls:
                    if time.perf_counter() >= site_deadline - 1.0:
                        results_dict[idx] = BrowserEvidence(
                            requested_url=target_url,
                            provider_status=BrowserStatus.TIMEOUT,
                            provider_error="Site audit budget exhausted before page execution",
                            selection_rank=idx,
                            inbound_links_count=inbound_counts.get(target_url, 0) if inbound_counts else 0,
                        )
                    else:
                        fut = executor.submit(_capture_page_worker, idx, target_url)
                        futures[fut] = idx

                for fut, idx in futures.items():
                    remaining_wait = max(0.1, site_deadline - time.perf_counter() + 2.0)
                    try:
                        results_dict[idx] = fut.result(timeout=remaining_wait)
                    except Exception as exc:
                        u = urls[idx]
                        results_dict[idx] = BrowserEvidence(
                            requested_url=u,
                            provider_status=BrowserStatus.TIMEOUT,
                            provider_error=f"Page execution timed out or failed: {exc}",
                            selection_rank=idx,
                            inbound_links_count=inbound_counts.get(u, 0) if inbound_counts else 0,
                        )

            for idx, _ in remaining_urls:
                evidences.append(results_dict.get(idx, BrowserEvidence.failed(urls[idx], "No evidence recorded")))

        return evidences

    def _capture_with_playwright(self, url: str, deadline: float | None = None) -> BrowserEvidence:
        """Internal: run Playwright capture with full cleanup guarantee.

        DNS-rebinding TOCTOU mitigation
        --------------------------------
        A PolicyProxy is started before the browser launches.  Chromium is
        directed to this proxy via --proxy-server and is prevented from making
        any direct connection via --proxy-bypass-list=<-loopback>.  The proxy
        resolves each destination itself and rejects connections where any
        resolved address is in a blocked IP range BEFORE opening the upstream
        socket.  Because the same addr_info entry that was validated is used
        for socket.connect(), there is no TOCTOU gap between validation and
        connection.  If the proxy fails to start, the capture is aborted.
        """
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError
        from browser.proxy import PolicyProxy

        cfg = self._config
        started = time.perf_counter()
        evidence = BrowserEvidence(requested_url=url)

        proxy: PolicyProxy | None = None
        playwright_ctx = None
        browser = None
        context = None
        page = None

        try:
            # Start the policy proxy before the browser so the proxy_url is
            # available when building launch_kwargs.
            proxy = PolicyProxy(allow_test_loopback=cfg.allow_test_loopback)
            try:
                proxy.start()
            except Exception as exc:
                evidence.provider_status = BrowserStatus.FAILED
                evidence.provider_error = f"Policy proxy failed to start: {exc}"
                evidence.elapsed_ms = _elapsed_ms(started)
                return evidence

            proxy_url = f"http://127.0.0.1:{proxy.port}"

            playwright_ctx = sync_playwright().start()

            # Launch options
            # --proxy-server: all Chromium connections go through the policy proxy.
            # --proxy-bypass-list=<-loopback>: disables the default loopback bypass
            #   so Chromium cannot make direct (non-proxied) connections, including
            #   to 127.0.0.1, localhost, or any other address.
            launch_kwargs: dict[str, Any] = {
                "headless": cfg.headless,
                "timeout": cfg.nav_timeout_ms,
                "proxy": {"server": proxy_url},
                "args": ["--proxy-bypass-list=<-loopback>"],
            }
            if cfg.executable:
                launch_kwargs["executable_path"] = cfg.executable

            try:
                browser = playwright_ctx.chromium.launch(**launch_kwargs)
            except PWError as exc:
                evidence.provider_status = BrowserStatus.FAILED
                evidence.provider_error = f"Browser launch failed: {exc}"
                evidence.elapsed_ms = _elapsed_ms(started)
                return evidence

            # Isolated context — no user data dir, no cookies, no credentials
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                accept_downloads=False,
                ignore_https_errors=False,
            )
            context.set_default_timeout(cfg.op_timeout_ms)
            context.set_default_navigation_timeout(cfg.nav_timeout_ms)

            page = context.new_page()

            # Install Web Vitals observers before navigation (Phase 3 WS-B)
            # Buffers LCP and layout-shift events emitted during initial parse and render.
            _WEB_VITALS_INIT_SCRIPT = """
            window.__leadgen_vitals = {
                lcp: null,
                lcp_observed: false,
                lcp_error: null,
                cls_entries: [],
                cls_observer_initialized: false,
                cls_error: null
            };
            try {
                if (typeof PerformanceObserver !== 'undefined') {
                    // 1. Largest Contentful Paint (LCP)
                    try {
                        const poLcp = new PerformanceObserver((entryList) => {
                            const entries = entryList.getEntries();
                            if (entries && entries.length > 0) {
                                window.__leadgen_vitals.lcp = entries[entries.length - 1].startTime;
                                window.__leadgen_vitals.lcp_observed = true;
                            }
                        });
                        poLcp.observe({ type: 'largest-contentful-paint', buffered: true });
                    } catch (lcpErr) {
                        window.__leadgen_vitals.lcp_error = String(lcpErr);
                    }

                    // 2. Cumulative Layout Shift (CLS)
                    try {
                        const poCls = new PerformanceObserver((entryList) => {
                            for (const entry of entryList.getEntries()) {
                                window.__leadgen_vitals.cls_entries.push({
                                    startTime: entry.startTime,
                                    value: entry.value,
                                    hadRecentInput: Boolean(entry.hadRecentInput)
                                });
                            }
                        });
                        poCls.observe({ type: 'layout-shift', buffered: true });
                        window.__leadgen_vitals.cls_observer_initialized = true;
                    } catch (clsErr) {
                        window.__leadgen_vitals.cls_error = String(clsErr);
                    }
                }
            } catch (err) {
                // Top-level observer setup fallback
            }
            """
            try:
                page.add_init_script(_WEB_VITALS_INIT_SCRIPT)
            except Exception as _init_err:
                logger.debug("add_init_script failed: %s", _init_err)

            # Capture console errors (bounded)
            _console_errors: list[str] = []
            def _on_console(msg):  # type: ignore[no-untyped-def]
                if msg.type in ("error", "warning") and len(_console_errors) < 20:
                    _console_errors.append(f"[{msg.type}] {msg.text[:300]}")
            page.on("console", _on_console)

            # Capture failed network requests (bounded)
            _failed_reqs: list[str] = []
            def _on_req_failed(req):  # type: ignore[no-untyped-def]
                if len(_failed_reqs) < 20:
                    _failed_reqs.append(req.url[:300])
            page.on("requestfailed", _on_req_failed)

            # Track request-boundary security blocks
            _security_blocked_reasons: list[str] = []

            # Block heavy resource types AND enforce request-boundary SSRF policy
            def _route_handler(route, request):  # type: ignore[no-untyped-def]
                req_url = request.url
                if request.resource_type in cfg.blocked_resource_types:
                    route.abort()
                    return

                from browser.security import validate_url
                req_check = validate_url(
                    req_url,
                    context="request-boundary",
                    allow_test_loopback=cfg.allow_test_loopback,
                )
                if not req_check.allowed:
                    logger.warning("[browser_security] Aborted request to %s: %s", req_url, req_check.reason)
                    _security_blocked_reasons.append(f"{req_url}: {req_check.reason}")
                    route.abort()
                    return
                # 3. For navigation requests, inspect redirect Location headers before following
                if request.is_navigation_request():
                    try:
                        resp = route.fetch(max_redirects=0)
                        if resp.status in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location")
                            if loc:
                                import urllib.parse
                                resolved_target = urllib.parse.urljoin(req_url, loc)
                                target_check = validate_url(
                                    resolved_target,
                                    context="redirect-boundary",
                                    allow_test_loopback=cfg.allow_test_loopback,
                                )
                                if not target_check.allowed:
                                    logger.warning(
                                        "[browser_security] Aborted redirect to %s: %s",
                                        resolved_target,
                                        target_check.reason,
                                    )
                                    _security_blocked_reasons.append(
                                        f"Redirect to {resolved_target}: {target_check.reason}"
                                    )
                                    route.abort()
                                    return
                        route.fulfill(response=resp)
                        return
                    except Exception as _fetch_err:
                        # Fail-closed: if route.fetch() itself fails for a navigation
                        # request, we cannot inspect redirect destinations, so we abort
                        # rather than fall through to route.continue_() which would let
                        # Chromium follow redirects without our hop-by-hop validation.
                        logger.warning(
                            "[browser_security] route.fetch() failed for navigation request to %s;"
                            " aborting to prevent unvalidated redirect-following: %s",
                            req_url,
                            _fetch_err,
                        )
                        _security_blocked_reasons.append(
                            f"route.fetch failed (fail-closed abort): {req_url}"
                        )
                        route.abort()
                        return

                route.continue_()
            page.route("**/*", _route_handler)

            # Budget check helper
            def _over_budget() -> bool:
                if deadline is not None:
                    return time.perf_counter() > deadline
                return (time.perf_counter() - started) > cfg.budget_seconds

            # Navigate
            http_status: int | None = None
            effective_nav_timeout_ms = cfg.nav_timeout_ms
            if deadline is not None:
                rem_ms = int((deadline - time.perf_counter()) * 1000)
                if rem_ms <= 0:
                    evidence.provider_status = BrowserStatus.TIMEOUT
                    evidence.provider_error = "Site audit budget exhausted before navigation"
                    evidence.elapsed_ms = _elapsed_ms(started)
                    return evidence
                effective_nav_timeout_ms = max(1, min(cfg.nav_timeout_ms, rem_ms))
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=effective_nav_timeout_ms)
                if resp is not None:
                    http_status = resp.status
                evidence.navigation_ok = True
            except PWTimeout:
                evidence.provider_status = BrowserStatus.TIMEOUT
                evidence.provider_error = f"Navigation timed out after {effective_nav_timeout_ms} ms"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence
            except PWError as exc:
                if _security_blocked_reasons:
                    evidence.provider_status = BrowserStatus.BLOCKED
                    evidence.provider_error = f"Security block at request boundary: {'; '.join(_security_blocked_reasons[:3])}"
                else:
                    evidence.provider_status = BrowserStatus.CRASHED
                    evidence.provider_error = f"Navigation error: {exc}"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence

            # Post-navigation security revalidation
            final_url = page.url or url
            from browser.security import validate_url
            post_check = validate_url(
                final_url,
                context="post-redirect",
                allow_test_loopback=cfg.allow_test_loopback,
            )
            if not post_check.allowed:
                evidence.provider_status = BrowserStatus.BLOCKED
                evidence.provider_error = (
                    f"Post-redirect security block: {post_check.reason}"
                )
                evidence.elapsed_ms = _elapsed_ms(started)
                return evidence

            evidence.final_url = final_url
            evidence.http_status = http_status

            if _over_budget():
                evidence.provider_status = BrowserStatus.PARTIAL
                evidence.provider_error = "Budget exceeded before evidence extraction"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence

            # Helper to calculate remaining budget for post-navigation operations
            def _remaining_op_ms(cap_ms: int) -> int:
                max_allowed = min(cap_ms, cfg.op_timeout_ms)
                if deadline is not None:
                    rem_ms = int((deadline - time.perf_counter()) * 1000)
                    return max(0, min(max_allowed, rem_ms))
                rem_budget_ms = int((cfg.budget_seconds - (time.perf_counter() - started)) * 1000)
                return max(0, min(max_allowed, rem_budget_ms))

            # Wait briefly for dynamic content if budget remains
            networkidle_timeout = _remaining_op_ms(5_000)
            if networkidle_timeout > 50:
                try:
                    page.wait_for_load_state("networkidle", timeout=networkidle_timeout)
                except (PWTimeout, PWError):
                    pass  # non-fatal; continue with whatever DOM we have

            if _over_budget():
                evidence.provider_status = BrowserStatus.PARTIAL
                evidence.provider_error = "Budget exceeded during post-navigation wait"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence

            # ── Evidence extraction ───────────────────────────────────────────

            # Page title
            try:
                evidence.page_title = (page.title() or "")[:500]
            except PWError:
                pass

            # Meta description
            try:
                desc_to = max(1, _remaining_op_ms(3_000))
                desc = page.get_attribute('meta[name="description"]', "content", timeout=desc_to)
                evidence.meta_description = (desc or "")[:500]
            except (PWError, PWTimeout):
                pass

            # Headings (h1–h6)
            try:
                headings: list[dict[str, str]] = []
                for level in range(1, 7):
                    selector = f"h{level}"
                    try:
                        els = page.query_selector_all(selector)
                        for el in els[:20]:
                            text = (el.inner_text() or "").strip()[:300]
                            if text:
                                headings.append({"level": f"h{level}", "text": text})
                    except PWError:
                        break
                evidence.headings = headings
            except PWError:
                pass

            # Visible text (estimate)
            try:
                body_text = page.inner_text("body") or ""
                evidence.visible_text_chars = len(body_text)
                evidence.has_visible_text = len(body_text.strip()) > 50
            except (PWError, PWTimeout):
                pass

            # Navigation presence
            try:
                nav = page.query_selector("nav, header, [role='navigation']")
                evidence.has_nav = nav is not None
            except PWError:
                pass

            # Internal links (count only — no URLs stored to limit size)
            try:
                page_domain = _domain(final_url)
                links = page.query_selector_all("a[href]")
                internal = 0
                for lnk in links[:200]:
                    try:
                        href = lnk.get_attribute("href") or ""
                        if href.startswith("/") or page_domain in href:
                            internal += 1
                    except PWError:
                        continue
                evidence.internal_link_count = internal
            except PWError:
                pass

            # CTA detection
            try:
                page_text_lower = (page.inner_text("body") or "").lower()
                evidence.has_cta = any(kw in page_text_lower for kw in _CTA_KEYWORDS)
            except (PWError, PWTimeout):
                pass

            # Form detection
            try:
                form = page.query_selector("form")
                evidence.has_form = form is not None
            except PWError:
                pass

            # DOM snippet (bounded)
            try:
                full_html = page.content()
                evidence.dom_snippet = full_html[:cfg.dom_snippet_max_chars]
            except (PWError, PWTimeout):
                pass

            # Screenshot (optional, only if explicitly enabled)
            if cfg.screenshot and not _over_budget():
                evidence.screenshot_path, evidence.screenshot_size_kb = (
                    _take_screenshot(page, url, cfg)
                )

            # Attach console and network signals
            evidence.console_errors = _console_errors
            evidence.failed_requests = _failed_reqs

            # JS-rendered comparison fields (populated from extracted data)
            evidence.js_rendered_title = evidence.page_title or None
            evidence.js_rendered_headings = evidence.headings or None

            # ── Lab Web Vitals Extraction (Phase 3 WS-B) ──────────────────────
            # Synthetic / lab measurements from Performance APIs.
            # Evaluated after settle; networkidle timeout does not invalidate measurements.
            _EXTRACT_METRICS_JS = """
            (() => {
                const result = {
                    lcp_ms: null,
                    cls: null,
                    ttfb_ms: null,
                    available: false
                };
                try {
                    const vitals = window.__leadgen_vitals || {};

                    // 1. TTFB (Time to First Byte)
                    if (typeof performance !== 'undefined' && typeof performance.getEntriesByType === 'function') {
                        const navEntries = performance.getEntriesByType('navigation');
                        if (navEntries && navEntries.length > 0) {
                            const nav = navEntries[0];
                            if (typeof nav.responseStart === 'number' && Number.isFinite(nav.responseStart) && nav.responseStart > 0) {
                                result.ttfb_ms = Math.round(nav.responseStart);
                            }
                        }
                    }

                    // 2. LCP (Largest Contentful Paint)
                    if (vitals.lcp_observed && typeof vitals.lcp === 'number' && Number.isFinite(vitals.lcp) && vitals.lcp > 0) {
                        result.lcp_ms = Math.round(vitals.lcp);
                    }

                    // 3. CLS (Cumulative Layout Shift) with Session Windowing
                    // Report 0.0 only when CLS observer initialized successfully and
                    // completed without qualifying shifts. Observer failure yields null.
                    if (vitals.cls_observer_initialized && !vitals.cls_error) {
                        const entries = vitals.cls_entries || [];
                        let maxSessionScore = 0.0;
                        let currentSessionScore = 0.0;
                        let sessionWindowStart = -Infinity;
                        let prevShiftTime = -Infinity;

                        for (const entry of entries) {
                            // Exclude layout shifts with recent user input
                            if (entry.hadRecentInput) continue;

                            // Session window rules: gap < 1000ms AND total window duration < 5000ms
                            if (entry.startTime - prevShiftTime < 1000 && entry.startTime - sessionWindowStart < 5000) {
                                currentSessionScore += entry.value;
                            } else {
                                sessionWindowStart = entry.startTime;
                                currentSessionScore = entry.value;
                            }
                            prevShiftTime = entry.startTime;

                            if (currentSessionScore > maxSessionScore) {
                                maxSessionScore = currentSessionScore;
                            }
                        }
                        result.cls = Number(maxSessionScore.toFixed(4));
                    } else {
                        result.cls = null;
                    }

                    result.available = true;
                } catch (e) {
                    result.available = false;
                }
                return result;
            })()
            """
            try:
                metrics_res = page.evaluate(_EXTRACT_METRICS_JS)
                if isinstance(metrics_res, dict):
                    evidence.lab_lcp_ms = metrics_res.get("lcp_ms")
                    evidence.lab_cls = metrics_res.get("cls")
                    evidence.lab_ttfb_ms = metrics_res.get("ttfb_ms")
                    evidence.lab_metrics_available = bool(metrics_res.get("available"))
            except (PWError, Exception) as _eval_err:
                logger.debug("Lab vitals extraction failed: %s", _eval_err)
                evidence.lab_metrics_available = False

            if _over_budget():
                evidence.provider_status = BrowserStatus.PARTIAL
                evidence.provider_error = "Budget exceeded before evidence extraction completed"
                evidence.navigation_timeout_ms = effective_nav_timeout_ms
                return evidence

            evidence.provider_status = BrowserStatus.SUCCESS
            evidence.navigation_timeout_ms = effective_nav_timeout_ms

        except PWError as exc:
            # Playwright crash or unexpected protocol error
            logger.exception("Browser provider CRASHED for %s", url)
            evidence.provider_status = BrowserStatus.CRASHED
            evidence.provider_error = f"Playwright error: {exc}"

        except Exception as exc:
            # Any other unexpected failure — never propagate
            logger.exception("Browser provider unexpected failure for %s", url)
            evidence.provider_status = BrowserStatus.FAILED
            evidence.provider_error = f"Unexpected failure: {type(exc).__name__}: {exc}"

        finally:
            # Guaranteed cleanup regardless of success or exception
            evidence.elapsed_ms = _elapsed_ms(started)
            _cleanup(page, context, browser, playwright_ctx)
            # Stop the policy proxy after the browser is closed so no
            # in-flight connection can slip through during teardown.
            if proxy is not None:
                try:
                    proxy.stop()
                except Exception as _proxy_stop_err:
                    logger.debug("Policy proxy stop error: %s", _proxy_stop_err)

        return evidence


# ── Helper functions ──────────────────────────────────────────────────────────

def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _domain(url: str) -> str:
    """Extract the hostname from a URL for internal-link detection."""
    import urllib.parse
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""


def _take_screenshot(page: Any, url: str, cfg: BrowserConfig) -> tuple[str | None, float | None]:
    """Capture a screenshot; return (path, size_kb) or (None, None) on error."""
    try:
        from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout
        shot_dir = cfg.screenshot_dir or tempfile.gettempdir()
        Path(shot_dir).mkdir(parents=True, exist_ok=True)
        # Safe filename from URL
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in url)[:80]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = str(Path(shot_dir) / f"audit_{safe}_{ts}.png")
        page.screenshot(path=path, full_page=False, timeout=10_000)
        size_bytes = Path(path).stat().st_size
        size_kb = round(size_bytes / 1024, 1)
        if size_kb > cfg.screenshot_max_kb:
            Path(path).unlink(missing_ok=True)
            logger.warning(
                "Screenshot for %s exceeded %d KB limit (%.1f KB); discarded.",
                url, cfg.screenshot_max_kb, size_kb
            )
            return None, None
        return path, size_kb
    except Exception as exc:
        logger.warning("Screenshot failed for %s: %s", url, exc)
        return None, None


def _cleanup(page: Any, context: Any, browser: Any, playwright_ctx: Any) -> None:
    """Close all Playwright resources in reverse order; never raise."""
    for obj, label in ((page, "page"), (context, "context"), (browser, "browser"), (playwright_ctx, "playwright")):
        if obj is None:
            continue
        try:
            obj.close()
        except Exception as exc:
            logger.debug("Cleanup error closing %s: %s", label, exc)
