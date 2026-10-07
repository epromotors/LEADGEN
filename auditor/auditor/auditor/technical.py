# auditor/technical.py — SSL, Sitemap, Robots, Canonical, Favicon

import ssl
import socket
import datetime
import requests
from auditor.core import result_pass, result_warn, result_fail, check_url_status
from config import TIMEOUT


def audit_ssl(url: str, session: requests.Session) -> dict:
    """Check SSL certificate validity, expiry, and trust chain."""
    from urllib.parse import urlparse
    hostname = urlparse(url).netloc.split(":")[0]
    
    if not url.startswith("https://"):
        return result_fail(
            "Site is not served over HTTPS.",
            "Install an SSL certificate. Use Let's Encrypt (free) or your host's SSL panel. "
            "Force HTTPS redirects via .htaccess or Nginx config.",
        )
    
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(TIMEOUT)
            s.connect((hostname, 443))
            cert = s.getpeercert()
        
        # Expiry check
        expire_str = cert.get("notAfter", "")
        if expire_str:
            expire_dt = datetime.datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            days_left = (expire_dt - now).days
            if days_left < 14:
                return result_fail(
                    f"SSL certificate expires in {days_left} day(s)!",
                    "Renew your SSL certificate immediately. If using Let's Encrypt, run: certbot renew",
                    f"Expiry: {expire_dt.strftime('%Y-%m-%d')}",
                )
            elif days_left < 45:
                return result_warn(
                    f"SSL certificate expiring soon ({days_left} days left).",
                    "Schedule renewal. Let's Encrypt certificates renew automatically via certbot.",
                    f"Expiry: {expire_dt.strftime('%Y-%m-%d')}",
                )
            return result_pass(
                f"SSL is valid and trusted. Expires in {days_left} days.",
                detail=f"Expiry: {expire_dt.strftime('%Y-%m-%d')}",
            )
        return result_pass("SSL certificate is valid and active.")
    except ssl.SSLCertVerificationError as e:
        return result_fail(
            "SSL certificate is UNTRUSTED or self-signed.",
            "Install a CA-signed certificate. Google Chrome shows a security warning — "
            "this actively scares visitors away and tanks SEO.",
            str(e),
        )
    except ssl.CertificateError as e:
        return result_fail("SSL certificate mismatch.", "Ensure the certificate covers your exact domain.", str(e))
    except Exception as e:
        return result_warn(f"Could not verify SSL: {e}", "Check your SSL configuration manually.")


def audit_sitemap(base_url: str, session: requests.Session) -> dict:
    """
    Check if a sitemap exists by probing 4 standard URL variations in priority order:
      1. /sitemap_index.xml  — Yoast SEO / Rank Math default (index of all sitemaps)
      2. /sitemap.xml        — Generic / most CMS default
      3. /post-sitemap.xml   — WordPress post type sitemap (Yoast / Rank Math)
      4. /page-sitemap.xml   — WordPress page type sitemap (Yoast / Rank Math)

    Also checks:
      - Whether the found sitemap URL is declared in robots.txt
      - Whether any variant was found even if the primary is missing
    """
    # Priority-ordered sitemap candidates
    candidates = [
        (f"{base_url}/sitemap_index.xml", "sitemap_index.xml (Yoast/Rank Math index)"),
        (f"{base_url}/sitemap.xml",       "sitemap.xml (generic default)"),
        (f"{base_url}/post-sitemap.xml",  "post-sitemap.xml (WordPress posts)"),
        (f"{base_url}/page-sitemap.xml",  "page-sitemap.xml (WordPress pages)"),
    ]

    found_urls:   list[str] = []
    missing_urls: list[str] = []

    for url, label in candidates:
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200 and (
                "xml" in r.headers.get("Content-Type", "")
                or "<sitemap" in r.text.lower()
                or "<urlset" in r.text.lower()
                or "<?xml" in r.text[:100].lower()
            ):
                # A1 fix: count both <url> entries AND child <sitemap> refs
                count_urls = r.text.lower().count("<url>")
                count_sitemaps = r.text.lower().count("<sitemap>")
                total_entries = count_urls + count_sitemaps
                if total_entries:
                    count_str = f"{count_urls} URLs" + (f", {count_sitemaps} sub-sitemaps" if count_sitemaps else "")
                else:
                    count_str = "found (no <url>/<sitemap> entries counted)"
                found_urls.append(f"✅ {label}: {count_str}")
            else:
                missing_urls.append(f"❌ {label}: not found ({r.status_code})")
        except Exception:
            missing_urls.append(f"❌ {label}: unreachable")

    # ── Check robots.txt for a Sitemap: declaration ────────────────────────
    sitemap_in_robots: str | None = None
    try:
        r = session.get(f"{base_url}/robots.txt", timeout=TIMEOUT)
        if r.status_code == 200:
            for line in r.text.splitlines():
                if line.strip().lower().startswith("sitemap:"):
                    sitemap_in_robots = line.strip()
                    break
    except Exception:
        pass

    robots_note = (
        f"Sitemap declared in robots.txt ✅ ({sitemap_in_robots})"
        if sitemap_in_robots
        else "⚠️ Sitemap NOT declared in robots.txt — add 'Sitemap: <url>' at the bottom of robots.txt"
    )

    # ── Build result ───────────────────────────────────────────────────────
    all_lines = found_urls + missing_urls
    detail = " | ".join(all_lines) + f" | {robots_note}"

    if found_urls:
        # At least one sitemap found — pass
        primary = found_urls[0]
        return result_pass(
            f"Sitemap found: {primary.split(':')[1].strip().split(' ')[0] if ':' in primary else 'sitemap'}",
            detail=detail,
        )

    # ── Nothing found — check robots.txt as last resort ───────────────────
    if sitemap_in_robots:
        return result_warn(
            "No sitemap at standard paths, but a Sitemap: directive exists in robots.txt.",
            "Verify the declared sitemap URL is accessible. "
            "Move sitemap to /sitemap_index.xml or /sitemap.xml for maximum compatibility.",
            detail,
        )

    return result_fail(
        "No sitemap found at any standard URL.",
        "Create an XML sitemap and submit it to Google Search Console. "
        "WordPress: install Yoast SEO or Rank Math (auto-generates sitemap_index.xml). "
        "Shopify: auto-generates /sitemap.xml. "
        "Custom sites: use screaming frog or xml-sitemaps.com. "
        "Also add 'Sitemap: https://yourdomain.com/sitemap_index.xml' to your robots.txt.",
        detail,
    )




def audit_robots(base_url: str, session: requests.Session) -> dict:
    """
    Check if robots.txt exists and has no catastrophic directives.

    False-positive prevention rules:
      1. Empty Disallow (path == "") under User-agent: * → means "allow all" per RFC — SAFE, never FAIL.
      2. Specific path Disallow (e.g. /wp-admin/, /search/) — normal, NEVER treated as root block.
      3. CRITICAL FAIL only when path == "/" literally under User-agent: * with no Allow: / override.
      4. Multiple User-agent: * blocks → merged before evaluating (mirrors real Googlebot behaviour).
      5. Allow: / or Allow: (empty) overrides Disallow: / → not blocked.
      6. AI training bots (GPTBot, ClaudeBot, Google-Extended, CCBot, etc.)
         blocking has ZERO SEO impact — never flag these as issues.
      7. Googlebot-specific Disallow: / → separate CRITICAL check.

    In plain English: a typical WordPress robots.txt that blocks /wp-admin/, /wp-login.php,
    /xmlrpc.php etc. will always PASS this check. Only a site that has literally:
        User-agent: *
        Disallow: /
    with no Allow: / will be flagged as CRITICAL.
    """
    # AI training bots whose blocking is irrelevant to SEO rankings
    _AI_BOTS = {
        "gptbot", "google-extended", "claudebot", "claude-web", "anthropic-ai",
        "ccbot", "cohere-ai", "omgili", "omgilibot", "diffbot", "facebookbot",
        "ia_archiver",
    }

    url = f"{base_url}/robots.txt"
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            lines = [ln.strip() for ln in r.text.splitlines()]

            # ── Parse into blocks: {user_agent: [rules]} ──────────────────
            # Each rule is ("disallow"|"allow", path)
            blocks: dict[str, list[tuple[str, str]]] = {}
            current_agents: list[str] = []

            for line in lines:
                if not line or line.startswith("#"):
                    # Blank line separates blocks
                    current_agents = []
                    continue
                lower = line.lower()
                if lower.startswith("user-agent:"):
                    ua = line.split(":", 1)[1].strip().lower()
                    current_agents.append(ua)
                    if ua not in blocks:
                        blocks[ua] = []
                elif lower.startswith("disallow:"):
                    path = line.split(":", 1)[1].strip()
                    for ua in current_agents:
                        blocks.setdefault(ua, []).append(("disallow", path))
                elif lower.startswith("allow:"):
                    path = line.split(":", 1)[1].strip()
                    for ua in current_agents:
                        blocks.setdefault(ua, []).append(("allow", path))

            # ── Collect all rules that apply to * (merge multiple * blocks) ─
            wildcard_rules = blocks.get("*", [])

            # ── Check if root is effectively blocked for * ─────────────────
            # CRITICAL RULE: We only flag as blocked when there is a LITERAL
            # "Disallow: /" (path exactly equals "/") under User-agent: *.
            #
            # "Disallow: /wp-admin/" — a specific path — is NOT a root block.
            # "Disallow:" (empty path) — means "allow everything" per RFC — NOT a block.
            # Only "Disallow: /" with no "Allow: /" override is catastrophic.
            disallow_root = any(
                directive == "disallow" and path == "/"
                for directive, path in wildcard_rules
            )
            allow_root = any(
                directive == "allow" and path in ("/", "")
                for directive, path in wildcard_rules
            )

            if disallow_root and not allow_root:
                return result_fail(
                    "robots.txt is BLOCKING all search engines from crawling the site!",
                    "Remove 'Disallow: /' under 'User-agent: *' immediately. "
                    "This is the #1 reason for disappearing from Google overnight.",
                )

            # ── Check if Googlebot is explicitly blocked ──────────────────
            googlebot_rules = blocks.get("googlebot", [])
            gb_disallow_root = any(
                directive == "disallow" and path == "/"
                for directive, path in googlebot_rules
            )
            gb_allow_root = any(
                directive == "allow" and path in ("/", "")
                for directive, path in googlebot_rules
            )
            if gb_disallow_root and not gb_allow_root:
                return result_fail(
                    "robots.txt explicitly blocks Googlebot from crawling the entire site!",
                    "Remove 'Disallow: /' under 'User-agent: Googlebot' immediately.",
                )

            # ── Multiple wildcard blocks? Warn (malformed but not critical) ─
            star_block_count = sum(
                1 for line in lines
                if line.lower() == "user-agent: *"
            )
            if star_block_count > 1:
                return result_pass(
                    "robots.txt found and allows crawling (multiple User-agent: * blocks detected).",
                    detail=(
                        f"URL: {url} — "
                        f"{star_block_count} separate User-agent: * blocks found. "
                        "Consolidate into one block for cleaner robots.txt. "
                        "Search engines merge them, but audit tools may misread this."
                    ),
                )

            return result_pass(
                "robots.txt found and allows crawling.",
                detail=f"URL: {url}",
            )

        elif r.status_code == 404:
            return result_fail(
                "robots.txt not found (404).",
                "Create a robots.txt at your domain root. Minimum content:\n"
                "User-agent: *\nDisallow:\nSitemap: https://yourdomain.com/sitemap.xml",
            )
        else:
            return result_warn(
                f"robots.txt returned status {r.status_code}.",
                "Verify the file is accessible.",
            )
    except Exception as e:
        return result_warn(
            f"Could not fetch robots.txt: {e}",
            "Ensure the file exists at the domain root.",
        )



def audit_canonical(soup, page_url: str) -> dict:
    """Check for canonical tag presence and correctness."""
    canonical = soup.find("link", rel=lambda x: x and "canonical" in x)
    if not canonical:
        return result_fail(
            "No canonical tag found.",
            "Add <link rel='canonical' href='https://yourdomain.com/page-url'/> "
            "in the <head> of every page. This prevents duplicate content penalties "
            "from Google when the same page is accessible via multiple URLs.",
        )
    href = canonical.get("href", "").strip()
    if not href:
        return result_warn(
            "Canonical tag exists but has an empty href.",
            "Set the canonical href to the definitive URL of this page.",
        )
    # Self-referencing is correct
    return result_pass(f"Canonical tag found: {href}")


def audit_favicon(soup, base_url: str, session: requests.Session) -> dict:
    """Check for favicon configuration — 5-layer detection."""

    # ── Layer 1: <link rel="icon|shortcut icon|apple-touch-icon"> in <head> ──
    favicon_tags = soup.find_all("link", rel=lambda x: x and (
        (isinstance(x, list) and any("icon" in str(r).lower() for r in x)) or
        (isinstance(x, str) and "icon" in x.lower())
    ))
    if favicon_tags:
        href = favicon_tags[0].get("href", "")
        return result_pass(
            "Favicon is configured via <link> tag.",
            detail=f"href: {href}",
        )

    # ── Layer 2: <meta name="msapplication-TileImage"> (IE / Windows tiles) ──
    ms_tile = soup.find("meta", attrs={"name": lambda v: v and "tileimage" in v.lower()})
    if ms_tile and ms_tile.get("content", "").strip():
        return result_pass(
            "Favicon configured via msapplication-TileImage meta tag.",
            detail=ms_tile["content"].strip(),
        )

    # ── Layer 3: WordPress REST API site icon ─────────────────────────────────
    # WordPress exposes site_icon_url via /wp-json/wp/v2/settings (auth required)
    # but also via the homepage HTML in a <script type="application/ld+json"> block
    import json as _json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("logo"):
                    logo = item["logo"]
                    if isinstance(logo, dict) and logo.get("url"):
                        return result_pass(
                            "Favicon/logo found via JSON-LD schema.",
                            detail=logo["url"],
                        )
                    if isinstance(logo, str):
                        return result_pass("Favicon/logo found via JSON-LD schema.", detail=logo)
        except Exception:
            continue

    # ── Layer 4: Check /favicon.ico via HTTP ──────────────────────────────────
    try:
        r = session.get(f"{base_url}/favicon.ico", timeout=TIMEOUT)
        if r.status_code == 200 and len(r.content) > 0:
            return result_warn(
                "Favicon served at /favicon.ico but not declared in <head>.",
                "Add <link rel='icon' href='/favicon.ico'> to your <head> for maximum browser/SERP compatibility.",
                detail=f"{base_url}/favicon.ico (HTTP 200, {len(r.content)} bytes)",
            )
    except Exception:
        pass

    # ── Layer 5: Check /apple-touch-icon.png (common WordPress / modern sites) ─
    for path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        try:
            r = session.get(f"{base_url}{path}", timeout=TIMEOUT)
            if r.status_code == 200 and len(r.content) > 0:
                return result_warn(
                    f"Apple touch icon found at {path} but not declared in <head>.",
                    "Add <link rel='apple-touch-icon' href='{path}'> to your <head>.",
                    detail=f"{base_url}{path} (HTTP 200)",
                )
        except Exception:
            continue

    return result_warn(
        "No favicon found.",
        "Create a 32×32 (or 512×512) PNG favicon and link it in <head>. "
        "Use realfavicongenerator.net for multi-platform icons. "
        "Google shows favicons in SERPs — this affects perceived brand trust.",
    )


def audit_mobile(soup) -> dict:
    """Check viewport meta tag and CSS media queries."""
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if not viewport:
        return result_fail(
            "No viewport meta tag found. Site is NOT mobile-responsive.",
            "Add to <head>: <meta name='viewport' content='width=device-width, initial-scale=1'>. "
            "Google uses mobile-first indexing — a non-mobile site ranks near the bottom.",
        )
    content = viewport.get("content", "")
    if "width=device-width" not in content:
        return result_warn(
            f"Viewport meta tag found but may be misconfigured: {content}",
            "Set content='width=device-width, initial-scale=1' for correct mobile rendering.",
        )
    
    return result_pass(
        "Mobile viewport meta tag is correctly configured.",
        detail=f"Viewport: {content}",
    )


# ── GROUP B NEW FUNCTIONS ─────────────────────────────────────────────────────

def audit_https_redirect(base_url: str, session: requests.Session) -> dict:
    """
    Verify that http:// version of the site 301-redirects to https://.

    SEO Impact: High
    Source: https://developers.google.com/search/docs/crawling-indexing/http-to-https
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    http_url = f"http://{parsed.netloc}/"

    try:
        r = session.get(http_url, timeout=TIMEOUT, allow_redirects=False, verify=False)
        if r.status_code in (301, 308):
            location = r.headers.get("Location", "")
            if location.startswith("https://"):
                return result_pass(
                    f"HTTP → HTTPS redirect is correctly configured ({r.status_code}).",
                    detail=f"{http_url} → {location}",
                )
            else:
                return result_warn(
                    f"HTTP redirects ({r.status_code}) but not to HTTPS.",
                    "Ensure the redirect destination uses https://. Check your server or CDN configuration.",
                    f"{http_url} → {location}",
                )
        elif r.status_code in (302, 303, 307):
            location = r.headers.get("Location", "")
            return result_warn(
                f"HTTP redirects with {r.status_code} (temporary) instead of 301 (permanent).",
                "Use a 301 (permanent) redirect from http:// to https://. Temporary redirects do not pass full link equity.",
                f"{http_url} → {location}",
            )
        elif r.status_code == 200:
            return result_fail(
                "HTTP version of site returns 200 — no redirect to HTTPS.",
                "Configure a server-level 301 redirect from http:// to https://. "
                "Without it, Google may index both versions as duplicate content.",
                f"{http_url} returned 200 directly.",
            )
        else:
            return result_warn(
                f"HTTP URL returned unexpected status {r.status_code}.",
                "Verify your server redirect configuration.",
                f"{http_url} → {r.status_code}",
            )
    except Exception as e:
        return result_warn(
            f"Could not check HTTP redirect: {e}",
            "Manually verify that http:// redirects to https://.",
        )


def audit_redirect_chain(base_url: str, session: requests.Session) -> dict:
    """
    Detect redirect chains longer than 2 hops.

    SEO Impact: Medium
    Source: https://developers.google.com/search/docs/crawling-indexing/301-redirects
    """
    try:
        r = session.get(base_url, timeout=TIMEOUT, allow_redirects=True, verify=False)
        hops = len(r.history)
        if hops == 0:
            return result_pass("No redirects — direct response.", detail=f"URL: {base_url}")
        elif hops == 1:
            return result_pass(
                f"Single redirect (1 hop) — acceptable.",
                detail=f"{base_url} → {r.url}",
            )
        elif hops == 2:
            return result_warn(
                f"Redirect chain with 2 hops detected.",
                "Reduce redirect chains to a single hop. Each hop slows crawling and dilutes PageRank.",
                f"{hops} hops ending at {r.url}",
            )
        else:
            return result_fail(
                f"Long redirect chain detected ({hops} hops).",
                "Fix redirect chains to a single direct 301. Use Screaming Frog or Redirect Checker to map chains. "
                "Chains with 3+ hops can block Googlebot from reaching your page.",
                f"{hops} hops ending at {r.url}",
            )
    except Exception as e:
        return result_warn(
            f"Could not check redirect chain: {e}",
            "Manually test your URL in Redirect Checker (https://httpstatus.io).",
        )


def audit_mixed_content(soup, base_url: str) -> dict:
    """
    Scan for http:// assets (images, scripts, stylesheets) loaded on an https:// page.

    SEO Impact: Medium — browsers block mixed content, causing security warnings.
    Source: https://web.dev/articles/fixing-mixed-content
    """
    if not base_url.startswith("https://"):
        # Only relevant for HTTPS sites
        return result_pass(
            "Site is not HTTPS — mixed content check not applicable.",
            detail="Mixed content is only an issue on HTTPS sites.",
        )

    mixed_assets: list[str] = []
    tags_attrs = [
        ("img",    "src"),
        ("script", "src"),
        ("link",   "href"),
        ("iframe", "src"),
        ("audio",  "src"),
        ("video",  "src"),
        ("source", "src"),
    ]
    for tag, attr in tags_attrs:
        for el in soup.find_all(tag, **{attr: True}):
            val = el.get(attr, "")
            if isinstance(val, str) and val.startswith("http://"):
                mixed_assets.append(f"<{tag}> {val[:80]}")
            if len(mixed_assets) >= 5:
                break
        if len(mixed_assets) >= 5:
            break

    if mixed_assets:
        return result_fail(
            f"Mixed content detected — {len(mixed_assets)} http:// asset(s) on an HTTPS page.",
            "Replace all http:// asset URLs with https:// or protocol-relative //. "
            "Browsers block mixed content — users see a security warning that hurts trust and conversions.",
            " | ".join(mixed_assets[:3]),
        )

    return result_pass(
        "No mixed content detected — all assets use HTTPS.",
        detail=f"Checked img, script, link, iframe tags on {base_url}",
    )


def audit_www_canonicalization(base_url: str, session: requests.Session) -> dict:
    """
    Check www vs non-www duplicate homepage — both returning 200 = duplicate content.

    SEO Impact: High
    Source: https://developers.google.com/search/docs/crawling-indexing/canonicalization
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    netloc = parsed.netloc

    if netloc.startswith("www."):
        # Canonical = www. — test non-www
        canonical   = base_url
        alternative = f"{parsed.scheme}://{netloc[4:]}/"
    else:
        # Canonical = non-www. — test www.
        canonical   = base_url
        alternative = f"{parsed.scheme}://www.{netloc}/"

    try:
        r = session.get(alternative, timeout=TIMEOUT, allow_redirects=True, verify=False)
        if r.status_code == 200:
            if r.url.rstrip("/") == canonical.rstrip("/"):
                # Redirected back to canonical — correct
                return result_pass(
                    "www / non-www canonicalization is correct — alternate redirects to canonical.",
                    detail=f"{alternative} → {r.url}",
                )
            else:
                return result_fail(
                    "Both www and non-www versions return 200 — Google sees these as duplicate homepages.",
                    "Add a 301 redirect so one version redirects to the other. "
                    "Declare your preferred version in Google Search Console and add a canonical tag. "
                    "Duplicate homepages split PageRank and may cause indexation issues.",
                    f"Canonical: {canonical} | Alternate also live: {alternative}",
                )
        elif r.status_code in (301, 302, 308):
            return result_pass(
                f"www / non-www alternate redirects ({r.status_code}) — no duplicate content issue.",
                detail=f"{alternative} → {r.url}",
            )
        else:
            return result_pass(
                f"Alternate www/non-www version is not reachable ({r.status_code}) — no duplication risk.",
                detail=f"{alternative} returned {r.status_code}",
            )
    except Exception as e:
        return result_pass(
            "Alternate www/non-www version is unreachable — no duplication risk.",
            detail=f"{alternative}: {e}",
        )
