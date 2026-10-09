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

Security note
─────────────
URL safety is checked before navigation and again against the final URL after
page load.  Playwright itself may follow HTTP redirects transparently; we
validate the final URL to detect redirect-based SSRF.  See security.py for the
list of blocked address ranges and known limitations.

Configuration
─────────────
The provider reads configuration from environment variables or a BrowserConfig
instance.  All settings have safe defaults suitable for a local Windows
development environment.

Environment variables (all optional):
    BROWSER_ENABLED            "true"/"false"  — default "false"
    BROWSER_HEADLESS           "true"/"false"  — default "true"
    BROWSER_NAV_TIMEOUT_MS     int             — default 25000 (25 s)
    BROWSER_OP_TIMEOUT_MS      int             — default 15000 (15 s)
    BROWSER_MAX_CONCURRENCY    int             — default 2
    BROWSER_BUDGET_SECONDS     int             — default 60
    BROWSER_SCREENSHOT         "true"/"false"  — default "false"
    BROWSER_SCREENSHOT_DIR     path            — default "" (tempdir)
    BROWSER_SCREENSHOT_MAX_KB  int             — default 512
    BROWSER_EXECUTABLE         path            — default "" (Playwright default)
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
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

    def capture(self, url: str) -> BrowserEvidence:
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

        # Pre-navigation security check
        from browser.security import validate_url
        pre_check = validate_url(url, context="pre-navigation")
        if not pre_check.allowed:
            return BrowserEvidence.security_blocked(url, pre_check.reason)

        # Acquire concurrency slot
        sem = _get_semaphore(self._config.max_concurrency)
        acquired = sem.acquire(timeout=30)
        if not acquired:
            return BrowserEvidence.failed(url, "Concurrency limit: could not acquire browser slot within 30 s")

        try:
            return self._capture_with_playwright(url)
        finally:
            sem.release()

    def _capture_with_playwright(self, url: str) -> BrowserEvidence:
        """Internal: run Playwright capture with full cleanup guarantee."""
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError

        cfg = self._config
        started = time.perf_counter()
        evidence = BrowserEvidence(requested_url=url)

        playwright_ctx = None
        browser = None
        context = None
        page = None

        try:
            playwright_ctx = sync_playwright().start()

            # Launch options
            launch_kwargs: dict[str, Any] = {
                "headless": cfg.headless,
                "timeout": cfg.nav_timeout_ms,
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

            # Block heavy resource types to reduce bandwidth and risk
            def _route_handler(route, request):  # type: ignore[no-untyped-def]
                if request.resource_type in cfg.blocked_resource_types:
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", _route_handler)

            # Budget check helper
            def _over_budget() -> bool:
                return (time.perf_counter() - started) > cfg.budget_seconds

            # Navigate
            http_status: int | None = None
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=cfg.nav_timeout_ms)
                if resp is not None:
                    http_status = resp.status
                evidence.navigation_ok = True
            except PWTimeout:
                evidence.provider_status = BrowserStatus.TIMEOUT
                evidence.provider_error = f"Navigation timed out after {cfg.nav_timeout_ms} ms"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence
            except PWError as exc:
                evidence.provider_status = BrowserStatus.CRASHED
                evidence.provider_error = f"Navigation error: {exc}"
                evidence.elapsed_ms = _elapsed_ms(started)
                evidence.console_errors = _console_errors
                evidence.failed_requests = _failed_reqs
                return evidence

            # Post-navigation security revalidation
            final_url = page.url or url
            from browser.security import validate_url
            post_check = validate_url(final_url, context="post-redirect")
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

            # Wait briefly for dynamic content
            try:
                page.wait_for_load_state("networkidle", timeout=min(5_000, cfg.op_timeout_ms))
            except (PWTimeout, PWError):
                pass  # non-fatal; continue with whatever DOM we have

            # ── Evidence extraction ───────────────────────────────────────────

            # Page title
            try:
                evidence.page_title = (page.title() or "")[:500]
            except PWError:
                pass

            # Meta description
            try:
                desc = page.get_attribute('meta[name="description"]', "content", timeout=3_000)
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

            evidence.provider_status = BrowserStatus.SUCCESS
            evidence.navigation_timeout_ms = cfg.nav_timeout_ms

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
