"""
site_checker.py — Pre-Audit Website Classifier (v5 — 4-Variant URL + SPA-aware)

Detection layers (in order):
  1. HTTP status codes (404/500 etc.)
  2. Redirect URL contains parking provider
  3. Extreme thin content (<800 chars) → parked
  4. PARKED Tier 1 — strong body signals (always flag)
  5. PARKED Tier 2 — title-only signals
  6. PARKED Tier 3 — thin-only signals (<3000 chars)
  7. DEMO  Tier 1 — strong server default / suspension signals
  8. DEMO  Tier 2 — title-only signals (coming soon, under construction…)
  9. DEMO  Tier 3 — thin-only signals  [tightened — avoids ambiguous phrases]
 10. Soft-404 detection (HTTP 200 with "page not found" title)
 11. SPA / JS-framework guard  — skip structural check if JS framework detected
 12. Structural analysis (only on very thin pages < 2000 chars)

URL Fallback Chain (fixes false UNREACHABLE on valid sites):
  For each candidate URL the order is tried:
    a) https://www.<domain>
    b) https://<domain>        ← original starting point
    c) http://www.<domain>
    d) http://<domain>

  Primary path: aiohttp async (45s timeout, ssl=False verify)
  Secondary path: requests sync (30s) via run_in_executor — triggered when
  aiohttp raises timeout or connection error on ALL variants.

SiteType:
  REAL        → live, content-rich business website  → run full audit
  PARKED      → domain-for-sale / parking page       → skip audit, send design email
  DEMO        → server default / coming-soon / suspended → same
  NOT_FOUND   → HTTP 404/410 or soft 404            → same
  UNREACHABLE → DNS failure / timeout / SSL error   → same
"""

import re
import asyncio
import aiohttp
import logging
from enum import Enum

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = aiohttp.ClientTimeout(total=45, connect=15)

PARKED_THRESHOLD     =   800   # chars — below this = parked/empty regardless
THIN_THRESHOLD       = 3_000   # chars — thin-tier signals only trigger below this
# Structural check only on VERY thin pages.  Raised from 8000→2000 because
# React/Vue/Angular SPAs deliver a tiny HTML shell; checking structure on them
# causes massive false-positive DEMO flags.
STRUCTURAL_THRESHOLD = 2_000


class SiteType(str, Enum):
    REAL        = "real"
    PARKED      = "parked"
    DEMO        = "demo"
    NOT_FOUND   = "not_found"
    UNREACHABLE = "unreachable"


# ─── PARKED SIGNALS ───────────────────────────────────────────────────────────

# Tier 1 — in body, always flag
PARKED_STRONG = [
    # Generic for-sale / parking
    "this domain is for sale",
    "domain for sale",
    "buy this domain",
    "domain is parked",
    "domain parked",
    "parked domain",
    "parked free",
    "this web page is parked",
    "this page is parked free",
    "domain may be for sale",
    "is registered but has no web",
    "domain is available for purchase",
    "acquire this domain",
    "inquire about this domain",
    "make an offer on this domain",
    # Parking provider fingerprints (URL or body)
    "sedoparking.com",
    "parkingcrew.net",
    "bodis.com/",
    "hugedomains.com",
    "afternic.com/landing",
    "dan.com/buy",
    # GoDaddy parking page
    "visit godaddy.com",
    "godaddy auction",
    "this page is parked by godaddy",
    # Namecheap parking
    "namecheap.com/domains/registration",
    "web hosting - courtesy of namecheap",
]

# Tier 2 — only flag if phrase found in <title>
PARKED_TITLE = [
    "domain for sale",
    "parked domain",
    "register this domain",
    "buy this domain",
    "domain is for sale",
]

# Tier 3 — only flag if body < THIN_THRESHOLD
PARKED_THIN = [
    "sedo.com",
    "afternic.com",
    "dan.com",
    "undeveloped.com",
    "flippa.com",
    "squadhelp.com",
    "uniregistry",
    "godaddy.com/domain",
    "namecheap.com",
    "this domain has been registered",
    "domain registration",
    "register a domain",
]


# ─── DEMO / PLACEHOLDER SIGNALS ───────────────────────────────────────────────

# Tier 1 — in body, always flag (extremely specific — won't appear on real sites)
DEMO_STRONG = [
    # WordPress factory-fresh
    "welcome to wordpress",
    "just another wordpress site",
    # Server/OS defaults
    "apache2 ubuntu default page",
    "apache2 debian default page",
    "apache http server test page",
    "test page for the apache http server",
    "test page for the nginx http server",
    "nginx default page",
    "it works! this is the default web page for this server",
    "cpanel default page",
    "plesk default page",
    "welcome to plesk",
    "iis7", "iis8",
    # Hosting suspension / disabled
    "this account has been suspended",
    "hosting account suspended",
    "this site has been disabled by the administrator",
    "this site has been temporarily disabled",
    "website is not configured",
    "this website has been temporarily disabled",
    "account has been suspended",
    "site is currently unavailable",
    "this service is temporarily unavailable",
    # Wix placeholder (only unclaimed/blank Wix sites)
    "this site was created with the wix website builder. create your own website",
    # Shopify / WooCommerce demo/unavailable
    "this is a woocommerce demo store",
    "this is a demo storefront",
    "this store is currently unavailable",
    "this shop is currently unavailable",
    "shopify-partner-site",
]

# Tier 2 — only flag if phrase found in <title>
# REMOVED: "page not found", "404 not found", "error 404" → moved to SOFT_404_TITLE only
# REMOVED: "temporarily unavailable", "site is unavailable" → too ambiguous in real titles
DEMO_TITLE = [
    "coming soon",
    "under construction",
    "maintenance mode",
    "site offline",
    "website offline",
    "launching soon",
    "we'll be back",
    "down for maintenance",
]

# Tier 3 — thin-only weak demo signals (< THIN_THRESHOLD chars)
# REMOVED: "under construction", "coming soon" — these appear in real site footers/banners
# and are far too common to reliably indicate a dead site on thin pages.
# REMOVED: "this page does not exist", "the page you requested could not be found"
# — these belong in Soft-404 detection (title only), not body detection.
DEMO_THIN = [
    "sample page",
    "this site is coming soon",
    "website coming soon",
    "we're coming soon",
    "we are coming soon",
    "site under construction",
    "this website is under construction",
    "website is under construction",
    "site is currently under maintenance",
    "temporary placeholder",
    "placeholder page",
    "this is a demo store",
]

# ─── SOFT-404 SIGNALS (HTTP 200 but content says not found) ───────────────────
# Checked in TITLE only — too dangerous in body (real sites have 404 sections)
SOFT_404_TITLE = [
    "page not found",
    "404 not found",
    "error 404",
    "404 - page not found",
    "not found - 404",
    "this page does not exist",
    "page doesn't exist",
    "oops! that page can't be found",
    "nothing found",
]

NOT_FOUND_STATUSES    = {404, 410, 451}
SERVER_ERROR_STATUSES = {500, 502, 503, 504, 520, 521, 522, 523, 524}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_title(body_lower: str) -> str:
    """Extract and return the <title> tag content, lower-cased."""
    m = re.search(r"<title[^>]*>(.*?)</title>", body_lower, re.DOTALL)
    return m.group(1).strip() if m else ""


def _scan(signals: list, text: str) -> str | None:
    """Return first matching signal, or None."""
    for sig in signals:
        if sig in text:
            return sig
    return None


def _has_js_framework(body_lower: str) -> bool:
    """
    Detect if the page uses a JavaScript SPA framework.
    SPAs deliver a near-empty HTML shell; checking structural signals on them
    produces false DEMO classifications.

    Detects: React, Vue, Angular, Svelte, Next.js, Nuxt, Remix, Gatsby,
             and generic SPA mount points.
    """
    # JS bundle file patterns
    if re.search(r'src=["\'][^"\']*(/static/js/main\.|/assets/index\.|/_next/static/|/__nuxt/|/build/static/)', body_lower):
        return True
    # React root mount
    if re.search(r'id=["\'](?:root|app|__next|__nuxt|svelte)["\']', body_lower):
        return True
    # Angular / Ionic
    if re.search(r'<app-root|ng-version=', body_lower):
        return True
    # Generic chunk/bundle hints
    if re.search(r'chunk\.[a-f0-9]{6,}\.js|main\.[a-f0-9]{6,}\.js|bundle\.js', body_lower):
        return True
    # Viewport meta + single script + no body text = likely SPA
    scripts = re.findall(r"<script", body_lower)
    if len(scripts) >= 2 and re.search(r'<meta[^>]+viewport', body_lower):
        # If there are multiple script tags it's probably a JS-rendered site
        return True
    return False


def _structural_check(body: str, body_lower: str) -> tuple[bool, str]:
    """
    Returns (is_dead, reason) based on structural analysis.
    ONLY called when body < STRUCTURAL_THRESHOLD (2000 chars).

    At < 2000 chars a real business website almost always has at least ONE of:
      - A navigation menu (<nav> or menu-classed elements)
      - Contact information (phone number or mailto link)
      - At least 3 meaningful href links
      - A JS framework sign (checked before this function is called)

    If ALL are missing on a sub-2000-char page, it's almost certainly a dead page.
    """
    # Navigation detection
    has_nav = bool(re.search(r"<nav[\s>]", body_lower))
    has_menu_class = bool(re.search(
        r'class=["\'"][^"\']*\b(?:menu|navbar|nav-bar|navigation|header-nav|main-nav)\b[^"\']*["\']',
        body_lower
    ))
    has_nav_role = bool(re.search(r'role=["\']navigation["\']', body_lower))

    # Contact info detection
    has_tel_link  = bool(re.search(r'href=["\']tel:', body_lower))
    has_mailto    = bool(re.search(r'href=["\']mailto:', body_lower))
    has_phone_num = bool(re.search(
        r'(\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}'
        r'|\b\d{3}[\-.\s]\d{3}[\-.\s]\d{4}\b)',
        body
    ))

    # Meaningful link count
    links = re.findall(r'href=["\']([^"\']{2,})["\']', body_lower)
    real_links = [
        l for l in links
        if not l.startswith(("#", "javascript:", "mailto:", "tel:"))
        and l not in ("/", "")
    ]

    no_nav     = not (has_nav or has_menu_class or has_nav_role)
    no_contact = not (has_tel_link or has_mailto or has_phone_num)
    few_links  = len(real_links) < 3   # lowered from 5

    if no_nav and no_contact and few_links:
        reasons = []
        if no_nav:     reasons.append("no navigation menu")
        if no_contact: reasons.append("no contact info")
        if few_links:  reasons.append(f"only {len(real_links)} link(s)")
        return True, f"Structurally dead: {', '.join(reasons)}"

    return False, ""


# ─── Body Content Classifier (shared by aiohttp and requests paths) ───────────

def _classify_body_content(body: str, final_url: str = "") -> tuple[SiteType, str]:
    """
    Classify a site based on its HTML body content.
    Shared by both the aiohttp path and the requests fallback.
    """
    body_lower = body.lower()
    body_len   = len(body_lower.strip())
    title      = _extract_title(body_lower)

    # ── 3. Extremely thin content ──────────────────────────────
    if body_len < PARKED_THRESHOLD:
        return SiteType.PARKED, \
            f"Extremely thin content ({body_len} chars) — likely parked or empty"

    # ── 4. PARKED Tier 1 — strong signals in body ──────────────
    hit = _scan(PARKED_STRONG, body_lower)
    if hit:
        return SiteType.PARKED, f"Parked domain detected: '{hit}'"

    # ── 5. PARKED Tier 2 — signals only in <title> ─────────────
    hit = _scan(PARKED_TITLE, title)
    if hit:
        return SiteType.PARKED, f"Parked page title: '{hit}'"

    # ── 6. PARKED Tier 3 — thin-page weak signals ──────────────
    if body_len < THIN_THRESHOLD:
        hit = _scan(PARKED_THIN, body_lower)
        if hit:
            return SiteType.PARKED, f"Thin content + parking signal: '{hit}'"

    # ── 7. DEMO Tier 1 — strong server/suspension signals ──────
    hit = _scan(DEMO_STRONG, body_lower)
    if hit:
        return SiteType.DEMO, f"Server default / placeholder: '{hit}'"

    # ── 8. DEMO Tier 2 — signals only in <title> ───────────────
    hit = _scan(DEMO_TITLE, title)
    if hit:
        return SiteType.DEMO, f"Placeholder page title: '{hit}'"

    # ── 9. DEMO Tier 3 — thin-page weak demo signals ───────────
    if body_len < THIN_THRESHOLD:
        hit = _scan(DEMO_THIN, body_lower)
        if hit:
            return SiteType.DEMO, f"Thin content + placeholder signal: '{hit}'"

    # ── 10. Soft-404 detection (HTTP 200 + 404 title) ──────────
    hit = _scan(SOFT_404_TITLE, title)
    if hit:
        return SiteType.NOT_FOUND, f"Soft 404 detected (HTTP 200 but title: '{hit}')"

    # ── 11. SPA guard — skip structural check for JS-rendered sites ──
    # React/Vue/Angular deliver an empty HTML shell; structural checks
    # on them produce massive false-positive DEMO rates.
    if body_len < STRUCTURAL_THRESHOLD:
        if _has_js_framework(body_lower):
            return SiteType.REAL, "JS framework detected — site is SPA (content rendered client-side)"

        # ── 12. Structural analysis (only very thin non-SPA pages) ──
        is_dead, reason = _structural_check(body, body_lower)
        if is_dead:
            return SiteType.DEMO, reason

    # ── Site looks real ────────────────────────────────────────
    return SiteType.REAL, "Site appears to be live and content-rich"


# ─── URL Variant Builder ──────────────────────────────────────────────────────

def _url_variants(url: str) -> list[str]:
    """
    Build a list of URL variants to try, in order of likelihood:
      1. https://www.domain.com   (most business sites prefer www)
      2. https://domain.com       (original, or bare)
      3. http://www.domain.com    (SSL not configured but www works)
      4. http://domain.com        (last resort)

    Avoids duplicate entries (e.g. if the input already has www).
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Normalise to https base + path
    if url.startswith("http://"):
        base_https = "https://" + url[7:]
        base_http  = url
    else:
        base_https = url
        base_http  = "http://" + url[8:]

    def _add_www(u: str) -> str:
        # Insert www. after scheme if not already present
        for scheme in ("https://", "http://"):
            if u.startswith(scheme):
                rest = u[len(scheme):]
                if not rest.startswith("www."):
                    return scheme + "www." + rest
        return u

    def _strip_www(u: str) -> str:
        for scheme in ("https://", "http://"):
            if u.startswith(scheme):
                rest = u[len(scheme):]
                if rest.startswith("www."):
                    return scheme + rest[4:]
        return u

    has_www = "/www." in base_https or base_https.startswith("https://www.")

    if has_www:
        # Input already has www — try www first, then bare
        variants = [
            base_https,               # https://www.domain
            _strip_www(base_https),   # https://domain
            base_http,                # http://www.domain
            _strip_www(base_http),    # http://domain
        ]
    else:
        # Input is bare domain — try www first
        variants = [
            _add_www(base_https),     # https://www.domain
            base_https,               # https://domain
            _add_www(base_http),      # http://www.domain
            base_http,                # http://domain
        ]

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


# ─── Sync Requests Fallback ───────────────────────────────────────────────────

def _classify_with_requests_sync(urls: list[str]) -> tuple[SiteType, str]:
    """
    Sync fallback classifier using the 'requests' library.
    Tries every URL variant before giving up.
    Run via asyncio.run_in_executor — does NOT block the event loop.
    """
    if not _REQUESTS_AVAILABLE:
        return SiteType.UNREACHABLE, "requests library not available for fallback"

    req_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": HEADERS["Accept"],
    }

    last_err = "Unknown error"
    for try_url in urls:
        try:
            resp = _requests.get(
                try_url,
                headers=req_headers,
                timeout=30,
                allow_redirects=True,
                verify=False,   # ignore SSL errors — we classify the content
            )
            final_url = resp.url.lower()
            status    = resp.status_code

            logger.info(f"[site_checker] requests: {try_url} → HTTP {status}")

            if status in NOT_FOUND_STATUSES:
                return SiteType.NOT_FOUND, f"HTTP {status} — page not found or deleted"
            if status in SERVER_ERROR_STATUSES:
                return SiteType.UNREACHABLE, f"HTTP {status} — server error"

            hit = _scan(PARKED_STRONG, final_url)
            if hit:
                return SiteType.PARKED, f"Redirected to parking provider: '{hit}'"

            return _classify_body_content(resp.text, final_url)

        except Exception as e:
            last_err = str(e)
            logger.debug(f"[site_checker] requests: {try_url} failed: {last_err[:120]}")
            continue

    return SiteType.UNREACHABLE, f"All URL variants failed (requests): {last_err}"


async def _fallback_classify_with_requests(urls: list[str]) -> tuple[SiteType, str]:
    """Async wrapper: run the sync requests fallback in a thread pool executor."""
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _classify_with_requests_sync, urls)
        site_type, reason = result
        logger.info(
            f"[site_checker] requests fallback → {site_type.value}: "
            f"{urls[0]} ({reason[:80]})"
        )
        return result
    except Exception as e:
        return SiteType.UNREACHABLE, f"requests fallback error: {e}"


# ─── Main Classifier ──────────────────────────────────────────────────────────

async def classify_site(url: str) -> tuple[SiteType, str]:
    """
    Classify a website URL.
    Returns (SiteType, human_readable_reason).

    Tries up to 4 URL variants in order:
      https://www.domain  →  https://domain  →  http://www.domain  →  http://domain

    Primary path: aiohttp (async, 45s timeout, ssl verification disabled).
    If aiohttp fails on ALL variants → requests fallback (sync, 30s, via executor).

    DNS failures on bare domain are NOT immediately fatal — the www variant
    is tried first because many business sites only have DNS for www.
    """
    variants = _url_variants(url)
    logger.info(f"[site_checker] Checking variants: {variants}")

    # ── aiohttp path: try each variant ────────────────────────────────────────
    connector = aiohttp.TCPConnector(ssl=False, limit_per_host=1)
    async with aiohttp.ClientSession(
        connector=connector,
        headers=HEADERS,
        timeout=TIMEOUT,
    ) as session:

        aiohttp_errors: list[str] = []
        needs_requests_fallback = False

        for try_url in variants:
            try:
                logger.debug(f"[site_checker] aiohttp GET: {try_url}")
                async with session.get(try_url, allow_redirects=True) as resp:
                    status    = resp.status
                    final_url = str(resp.url).lower()
                    logger.info(f"[site_checker] {try_url} → HTTP {status}")

                    # ── 1. HTTP error codes ────────────────────────────────────
                    if status in NOT_FOUND_STATUSES:
                        return SiteType.NOT_FOUND, f"HTTP {status} — page not found or deleted"

                    if status in SERVER_ERROR_STATUSES:
                        # Server error on one variant — try next before giving up
                        aiohttp_errors.append(f"HTTP {status} on {try_url}")
                        continue

                    # ── 2. Redirect URL contains parking provider ──────────────
                    hit = _scan(PARKED_STRONG, final_url)
                    if hit:
                        return SiteType.PARKED, f"Redirected to parking provider: '{hit}'"

                    # ── 3. Read body ───────────────────────────────────────────
                    try:
                        body = await resp.text(errors="replace")
                    except Exception:
                        aiohttp_errors.append(f"Could not read body from {try_url}")
                        continue

                    # 4–12. Content-based classification — return first successful result
                    return _classify_body_content(body, final_url)

            except aiohttp.ClientConnectorError as e:
                err_lower = str(e).lower()
                # DNS failure — try next variant (www might resolve when bare doesn't)
                if any(x in err_lower for x in ("name", "dns", "resolve", "getaddrinfo")):
                    logger.debug(f"[site_checker] DNS fail on {try_url}, trying next variant")
                    aiohttp_errors.append(f"DNS failure on {try_url}")
                    continue
                # SSL error — try next variant (http ones in the list will work)
                if any(x in err_lower for x in ("ssl", "certificate")):
                    logger.debug(f"[site_checker] SSL error on {try_url}, trying next variant")
                    aiohttp_errors.append(f"SSL error on {try_url}")
                    continue
                # Connection refused / other connector error — try next
                logger.debug(f"[site_checker] Connector error on {try_url}: {e}")
                aiohttp_errors.append(f"Connection error on {try_url}: {str(e)[:80]}")
                needs_requests_fallback = True
                continue

            except (aiohttp.ServerTimeoutError, asyncio.TimeoutError):
                logger.debug(f"[site_checker] Timeout on {try_url}")
                aiohttp_errors.append(f"Timeout on {try_url}")
                needs_requests_fallback = True
                continue

            except aiohttp.TooManyRedirects:
                # Redirect loop on this variant — try next
                aiohttp_errors.append(f"Too many redirects on {try_url}")
                continue

            except Exception as e:
                logger.debug(f"[site_checker] aiohttp error ({type(e).__name__}) on {try_url}: {e}")
                aiohttp_errors.append(f"{type(e).__name__} on {try_url}")
                needs_requests_fallback = True
                continue

        # All aiohttp variants exhausted — use requests fallback if we had timeouts/errors
        if needs_requests_fallback or aiohttp_errors:
            logger.info(
                f"[site_checker] All aiohttp variants failed for {url} "
                f"({'; '.join(aiohttp_errors[:2])}), trying requests fallback"
            )
            return await _fallback_classify_with_requests(variants)

        # If we get here all variants returned 5xx or redirects to bad URLs
        return SiteType.UNREACHABLE, f"All variants returned errors: {'; '.join(aiohttp_errors)}"


async def resolve_live_url(url: str) -> str:
    """
    Resolve the same 4 URL variants used by classify_site and return the first
    reachable final URL. This lets the deep audit run against the real HTTPS/www
    target instead of the possibly stale URL stored on the lead row.
    """
    variants = _url_variants(url)

    connector = aiohttp.TCPConnector(ssl=False, limit_per_host=1)
    async with aiohttp.ClientSession(
        connector=connector,
        headers=HEADERS,
        timeout=TIMEOUT,
    ) as session:
        for try_url in variants:
            try:
                async with session.get(try_url, allow_redirects=True) as resp:
                    if resp.status not in NOT_FOUND_STATUSES and resp.status not in SERVER_ERROR_STATUSES:
                        return str(resp.url).rstrip("/")
            except Exception:
                continue

    if _REQUESTS_AVAILABLE:
        loop = asyncio.get_running_loop()

        def _resolve_sync() -> str | None:
            for try_url in variants:
                try:
                    resp = _requests.get(
                        try_url,
                        headers={"User-Agent": HEADERS["User-Agent"], "Accept": HEADERS["Accept"]},
                        timeout=30,
                        allow_redirects=True,
                        verify=False,
                    )
                    if resp.status_code not in NOT_FOUND_STATUSES and resp.status_code not in SERVER_ERROR_STATUSES:
                        return resp.url.rstrip("/")
                except Exception:
                    continue
            return None

        resolved = await loop.run_in_executor(None, _resolve_sync)
        if resolved:
            return resolved

    return variants[0].rstrip("/")


# ─── Tag Helpers (used by audit_engine and outreach_engine) ───────────────────

def site_status_tag(site_type: SiteType) -> str:
    """Returns the error_message prefix stored in the DB."""
    return f"SITE_STATUS:{site_type.value}"


def parse_site_status(error_message: str) -> SiteType | None:
    """Extract SiteType from a stored error_message, or None if it's a real audit error."""
    if error_message and error_message.startswith("SITE_STATUS:"):
        val = error_message.replace("SITE_STATUS:", "")
        try:
            return SiteType(val)
        except ValueError:
            pass
    return None


# ─── Geo-Smart Country/Currency Detection ─────────────────────────────────────

# Maps country_code → (currency_code, currency_symbol)
_CURRENCY_MAP: dict[str, tuple[str, str]] = {
    "GB": ("GBP", "£"),
    "AU": ("AUD", "A$"),
    "CA": ("CAD", "C$"),
    "SG": ("SGD", "S$"),
    "AE": ("AED", "AED"),
    "DE": ("EUR", "€"),
    "FR": ("EUR", "€"),
    "NL": ("EUR", "€"),
    "ES": ("EUR", "€"),
    "IT": ("EUR", "€"),
    "NZ": ("NZD", "NZ$"),
    "US": ("USD", "$"),
    "IN": ("INR", "₹"),          # keep for completeness — not targeted for outreach
}

# Phone prefix → country code (order matters — longer/specific prefixes first)
# NOTE: Canada (+1) shares a prefix with the US, so +1 always maps to US.
#       Canada is reliably detected via .ca TLD or address keywords instead.
_PHONE_PREFIXES: list[tuple[str, str]] = [
    ("+971", "AE"),  # 4-char prefix first to avoid false match with shorter ones
    ("+44",  "GB"),  ("+61", "AU"),  ("+65", "SG"),
    ("+64",  "NZ"),  ("+49", "DE"),  ("+33", "FR"),
    ("+31",  "NL"),  ("+34", "ES"),  ("+39", "IT"),
    ("+1",   "US"),  # US/CA both use +1 — default to US; CA detected via TLD/address
]

# Address keyword fragments → country code
_ADDRESS_KEYWORDS: list[tuple[str, str]] = [
    ("united kingdom", "GB"), ("england", "GB"), ("scotland", "GB"),
    ("wales", "GB"),          ("london", "GB"),
    ("australia", "AU"),      ("sydney", "AU"), ("melbourne", "AU"),
    ("brisbane", "AU"),       ("perth", "AU"),
    ("singapore", "SG"),
    ("dubai", "AE"),          ("abu dhabi", "AE"), ("uae", "AE"),
    ("united arab", "AE"),
    ("new zealand", "NZ"),    ("auckland", "NZ"),
    ("canada", "CA"),         ("toronto", "CA"), ("vancouver", "CA"),
    ("germany", "DE"),        ("deutschland", "DE"), ("berlin", "DE"),
    ("france", "FR"),         ("paris", "FR"),
    ("netherlands", "NL"),    ("amsterdam", "NL"),
    ("spain", "ES"),          ("madrid", "ES"),
    ("italy", "IT"),          ("rome", "IT"),    ("milan", "IT"),
]

# TLD → country code
_TLD_MAP: dict[str, str] = {
    ".co.uk": "GB",  ".co.au": "AU",  ".com.au": "AU",
    ".sg":    "SG",  ".ae":    "AE",  ".com.sg": "SG",
    ".nz":    "NZ",  ".co.nz": "NZ",  ".ca":    "CA",
    ".de":    "DE",  ".fr":    "FR",  ".nl":    "NL",
    ".es":    "ES",  ".it":    "IT",
}


def detect_country(html: str, url: str = "") -> dict:
    """
    Detect the target country and matching currency from a website's HTML + URL.

    Detection layers (in priority order):
      1. Phone number prefix scan (+44, +61, +971, etc.)
      2. Address/city keyword scan (london, sydney, singapore…)
      3. ccTLD in the URL (.co.uk, .com.au, .sg…)
      4. Fallback: USD / US

    Returns:
        {
            "country_code":   str,   # e.g. "GB"
            "currency_code":  str,   # e.g. "GBP"
            "currency_symbol":str,   # e.g. "£"
            "detected_via":   str,   # "phone"|"address"|"tld"|"fallback"
        }
    Always safe — never raises.
    """
    try:
        text_lower = (html or "").lower()
        url_lower  = (url  or "").lower()

        # ── Layer 1: phone prefix ─────────────────────────────────────────────
        for prefix, code in _PHONE_PREFIXES:
            if prefix in text_lower:
                cur_code, cur_sym = _CURRENCY_MAP.get(code, ("USD", "$"))
                return {
                    "country_code":    code,
                    "currency_code":   cur_code,
                    "currency_symbol": cur_sym,
                    "detected_via":    "phone",
                }

        # ── Layer 2: address keyword ──────────────────────────────────────────
        for keyword, code in _ADDRESS_KEYWORDS:
            if keyword in text_lower:
                cur_code, cur_sym = _CURRENCY_MAP.get(code, ("USD", "$"))
                return {
                    "country_code":    code,
                    "currency_code":   cur_code,
                    "currency_symbol": cur_sym,
                    "detected_via":    "address",
                }

        # ── Layer 3: TLD ──────────────────────────────────────────────────────
        for tld, code in _TLD_MAP.items():
            if tld in url_lower:
                cur_code, cur_sym = _CURRENCY_MAP.get(code, ("USD", "$"))
                return {
                    "country_code":    code,
                    "currency_code":   cur_code,
                    "currency_symbol": cur_sym,
                    "detected_via":    "tld",
                }

    except Exception as e:
        logger.warning(f"[site_checker] detect_country failed: {e}")

    # ── Fallback: USD ─────────────────────────────────────────────────────────
    return {
        "country_code":    "US",
        "currency_code":   "USD",
        "currency_symbol": "$",
        "detected_via":    "fallback",
    }
