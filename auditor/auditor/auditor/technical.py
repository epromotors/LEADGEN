# auditor/technical.py — SSL, Sitemap, Robots, Canonical, Favicon

import ssl
import socket
import datetime
import requests
from auditor.core import result_pass, result_warn, result_fail, check_url_status, read_response_text, read_response_bytes
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
        # NOTE (Windows DNS limitation):
        # socket.create_connection enforces socket connection and read/write timeouts,
        # but the preceding OS DNS resolution (getaddrinfo / WSAGetAddrInfoW on Windows)
        # is synchronous and cannot be bounded by socket timeouts without an external
        # DNS resolver dependency (e.g. dnspython/aiodns). Once connected, the TLS
        # handshake and certificate reads are strictly bounded by TIMEOUT.
        with socket.create_connection((hostname, 443), timeout=TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as s:
                s.settimeout(TIMEOUT)
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
    Check if a sitemap exists by:
      1. Deriving site origin from base_url.
      2. Fetching origin/robots.txt and extracting all valid Sitemap: directives.
      3. Resolving relative sitemaps against origin and checking declared sitemaps first.
      4. If no usable declaration, probing root-level common candidates:
         /sitemap.xml, /sitemap_index.xml, /sitemap-index.xml, /wp-sitemap.xml,
         /post-sitemap.xml, /page-sitemap.xml.
      5. Strictly validating HTTP 200 responses as valid XML with root urlset or sitemapindex (rejecting HTML).
      6. Bounding child sitemaps, response sizes, and timeouts with full stream cleanup.
      7. Recording full URLs, status codes, and accept/reject reasons.
    """
    import urllib.parse
    import xml.etree.ElementTree as ET
    from auditor.core import get_origin

    origin = get_origin(base_url)
    sitemap_probe_timeout = min(TIMEOUT, 6)

    # ── 1. Fetch robots.txt and parse all Sitemap: directives ──────────────
    robots_url = f"{origin}/robots.txt"
    declared_sitemaps: list[str] = []
    robots_status: int | None = None
    try:
        with session.get(robots_url, timeout=min(TIMEOUT, 5), stream=True) as r:
            robots_status = r.status_code
            if r.status_code == 200:
                ctype = r.headers.get("Content-Type", "").lower()
                robots_txt = read_response_text(r, max_bytes=512 * 1024, max_elapsed=min(TIMEOUT, 5))
                # Only parse directives if not an HTML page
                if "text/html" not in ctype and not robots_txt.strip().lower().startswith(("<!doctype html", "<html")):
                    for line in robots_txt.splitlines():
                        trimmed = line.strip()
                        if trimmed.lower().startswith("sitemap:"):
                            raw_val = trimmed.split(":", 1)[1].strip()
                            if raw_val:
                                resolved = urllib.parse.urljoin(origin, raw_val)
                                parsed_s = urllib.parse.urlparse(resolved)
                                if parsed_s.scheme in ("http", "https") and resolved not in declared_sitemaps:
                                    declared_sitemaps.append(resolved)
    except Exception:
        pass

    # ── 2. Build ordered candidate list (declared first, then common root fallbacks) ──
    common_fallbacks = [
        (f"{origin}/sitemap_index.xml", "sitemap_index.xml (index)"),
        (f"{origin}/sitemap.xml",       "sitemap.xml (generic default)"),
        (f"{origin}/sitemap-index.xml", "sitemap-index.xml (index alternate)"),
        (f"{origin}/wp-sitemap.xml",    "wp-sitemap.xml (WordPress core)"),
        (f"{origin}/post-sitemap.xml",  "post-sitemap.xml (WordPress posts)"),
        (f"{origin}/page-sitemap.xml",  "page-sitemap.xml (WordPress pages)"),
    ]

    candidates: list[tuple[str, str, bool]] = []
    for d_url in declared_sitemaps:
        candidates.append((d_url, f"robots.txt declared ({d_url})", True))
    for f_url, label in common_fallbacks:
        if not any(c[0] == f_url for c in candidates):
            candidates.append((f_url, label, False))

    probes: list[dict] = []
    found_sitemaps: list[dict] = []

    def validate_sitemap_content(content: str, ctype: str) -> tuple[bool, str, int, int]:
        """
        Validate sitemap XML content. Returns (is_valid, reason, url_count, child_sitemap_count).
        Strictly rejects HTML documents.
        """
        content_stripped = content.strip()
        lower = content_stripped.lower()
        if "text/html" in ctype or lower.startswith("<!doctype html") or lower.startswith("<html"):
            return False, "returned HTML document instead of XML sitemap", 0, 0

        try:
            root = ET.fromstring(content_stripped)
        except Exception as exc:
            return False, f"malformed XML ({type(exc).__name__})", 0, 0

        root_name = root.tag.rsplit("}", 1)[-1].lower()
        if root_name not in ("urlset", "sitemapindex"):
            return False, f"invalid XML root tag '<{root_name}>' (expected <urlset> or <sitemapindex>)", 0, 0

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        url_count = 0
        child_count = 0

        if root_name == "sitemapindex":
            # Count child sitemaps
            sitemaps = root.findall(".//sm:sitemap", ns) or root.findall(".//sitemap")
            child_count = len(sitemaps) if sitemaps else len(root.findall(".//sm:loc", ns) or root.findall(".//loc"))
        else:
            urls = root.findall(".//sm:url", ns) or root.findall(".//url")
            url_count = len(urls) if urls else len(root.findall(".//sm:loc", ns) or root.findall(".//loc"))

        return True, root_name, url_count, child_count

    for cand_url, label, is_declared in candidates:
        probe_record = {"url": cand_url, "label": label, "status_code": None, "outcome": "untested", "reason": ""}
        try:
            with session.get(cand_url, timeout=sitemap_probe_timeout, stream=True) as r:
                probe_record["status_code"] = r.status_code
                if r.status_code == 200:
                    ctype = r.headers.get("Content-Type", "").lower()
                    text = read_response_text(r, max_bytes=2 * 1024 * 1024, max_elapsed=sitemap_probe_timeout)
                    is_valid, root_desc, u_count, c_count = validate_sitemap_content(text, ctype)
                    if is_valid:
                        desc = f"{u_count} URLs" if root_desc == "urlset" else f"{c_count} child sitemaps"
                        probe_record["outcome"] = "ACCEPTED"
                        probe_record["reason"] = f"Valid XML {root_desc} ({desc})"
                        found_sitemaps.append({
                            "url": cand_url,
                            "label": label,
                            "is_declared": is_declared,
                            "type": root_desc,
                            "url_count": u_count,
                            "child_count": c_count,
                            "desc": desc,
                        })
                        probes.append(probe_record)
                        # Once we find a valid primary sitemap, we record it and stop extra network probes
                        break
                    else:
                        probe_record["outcome"] = "REJECTED"
                        probe_record["reason"] = root_desc
                else:
                    probe_record["outcome"] = "REJECTED"
                    probe_record["reason"] = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            probe_record["outcome"] = "REJECTED"
            probe_record["reason"] = "timed out"
            probes.append(probe_record)
            break
        except Exception as exc:
            probe_record["outcome"] = "REJECTED"
            probe_record["reason"] = f"unreachable ({type(exc).__name__})"
        probes.append(probe_record)

    # ── Build probe summary detail ──────────────────────────────────────────
    probe_lines = [f"{p['url']} [HTTP {p['status_code'] or 'ERR'}]: {p['reason']}" for p in probes]
    robots_decl_note = (
        f"Declared in robots.txt: {', '.join(declared_sitemaps)}"
        if declared_sitemaps
        else "No Sitemap directive declared in robots.txt"
    )
    detail_str = f"{' | '.join(probe_lines)} | {robots_decl_note}"

    if found_sitemaps:
        primary = found_sitemaps[0]
        msg = f"Sitemap found: {primary['url']} ({primary['desc']})"
        if primary["is_declared"]:
            msg += " [declared in robots.txt]"
        return result_pass(
            msg,
            detail=detail_str,
            evidence=[{"found_sitemaps": found_sitemaps, "probes": probes, "origin": origin}],
        )

    if declared_sitemaps:
        return result_warn(
            f"Sitemap declared in robots.txt ({declared_sitemaps[0]}) was not usable, and no fallback sitemap was found.",
            "Verify that the sitemap URL declared in robots.txt is accessible and serves valid XML (not an HTML error page).",
            detail=detail_str,
            evidence=[{"probes": probes, "declared_sitemaps": declared_sitemaps, "origin": origin}],
        )

    return result_fail(
        "No sitemap found at any standard or declared location.",
        "Create an XML sitemap and submit it to Google Search Console. "
        "WordPress: install Yoast SEO or Rank Math. "
        "Shopify: auto-generates /sitemap.xml. "
        "Also declare 'Sitemap: https://yourdomain.com/sitemap.xml' in robots.txt.",
        detail=detail_str,
        evidence=[{"probes": probes, "origin": origin}],
    )


def audit_robots(base_url: str, session: requests.Session) -> dict:
    """
    Check if robots.txt exists at domain root and has no catastrophic directives.
    Location is strictly the site origin (origin/robots.txt), not appending to page subpaths.
    Verifies that HTTP 200 responses are plain text and not HTML error pages.
    """
    from auditor.core import get_origin

    origin = get_origin(base_url)
    url = f"{origin}/robots.txt"
    robots_timeout = min(TIMEOUT, 5)

    try:
        with session.get(url, timeout=robots_timeout, stream=True) as r:
            if r.status_code == 200:
                ctype = r.headers.get("Content-Type", "").lower()
                robots_txt = read_response_text(r, max_bytes=512 * 1024, max_elapsed=robots_timeout)
                is_trunc = getattr(robots_txt, "is_truncated", False)

                # Validate content is not HTML
                stripped = robots_txt.strip().lower()
                if "text/html" in ctype or stripped.startswith("<!doctype html") or stripped.startswith("<html"):
                    return result_warn(
                        "robots.txt endpoint returned an HTML document instead of plain text.",
                        "Ensure /robots.txt serves a plain-text file (text/plain) rather than a webpage or custom 404 page.",
                        detail=f"URL: {url} — HTTP 200 returned Content-Type '{ctype or 'unknown'}' with HTML content.",
                        evidence=[{"url": url, "status_code": 200, "content_type": ctype, "is_html": True}],
                    )

                lines = [ln.strip() for ln in robots_txt.splitlines()]

                # ── Parse into blocks: {user_agent: [rules]} ──────────────────
                blocks: dict[str, list[tuple[str, str]]] = {}
                current_agents: list[str] = []
                declared_sitemaps: list[str] = []

                for line in lines:
                    if not line or line.startswith("#"):
                        current_agents = []
                        continue
                    lower = line.lower()
                    if lower.startswith("sitemap:"):
                        sm_val = line.split(":", 1)[1].strip()
                        if sm_val:
                            declared_sitemaps.append(sm_val)
                    elif lower.startswith("user-agent:"):
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

                wildcard_rules = blocks.get("*", [])
                disallow_root = any(directive == "disallow" and path == "/" for directive, path in wildcard_rules)
                allow_root = any(directive == "allow" and path in ("/", "") for directive, path in wildcard_rules)

                if disallow_root and not allow_root:
                    return result_fail(
                        "robots.txt is BLOCKING all search engines from crawling the site!",
                        "Remove 'Disallow: /' under 'User-agent: *' immediately. "
                        "This is the #1 reason for disappearing from Google overnight.",
                        detail=f"URL: {url} — Disallow: / active for User-agent: *",
                        evidence=[{"url": url, "disallow_root": True}],
                    )

                googlebot_rules = blocks.get("googlebot", [])
                gb_disallow_root = any(directive == "disallow" and path == "/" for directive, path in googlebot_rules)
                gb_allow_root = any(directive == "allow" and path in ("/", "") for directive, path in googlebot_rules)
                if gb_disallow_root and not gb_allow_root:
                    return result_fail(
                        "robots.txt explicitly blocks Googlebot from crawling the entire site!",
                        "Remove 'Disallow: /' under 'User-agent: Googlebot' immediately.",
                        detail=f"URL: {url} — Disallow: / active for Googlebot",
                        evidence=[{"url": url, "googlebot_blocked": True}],
                    )

                star_block_count = sum(1 for line in lines if line.lower() == "user-agent: *")
                trunc_note = " (truncated at byte limit)" if is_trunc else ""
                sm_note = f" (Sitemap declared: {', '.join(declared_sitemaps)})" if declared_sitemaps else ""

                if star_block_count > 1:
                    return result_pass(
                        "robots.txt found and allows crawling (multiple User-agent: * blocks detected).",
                        detail=(
                            f"URL: {url}{trunc_note}{sm_note} — "
                            f"{star_block_count} separate User-agent: * blocks found. "
                            "Consolidate into one block for cleaner robots.txt."
                        ),
                        evidence=[{"url": url, "declared_sitemaps": declared_sitemaps}],
                    )

                return result_pass(
                    "robots.txt found and allows crawling.",
                    detail=f"URL: {url}{trunc_note}{sm_note}",
                    evidence=[{"url": url, "declared_sitemaps": declared_sitemaps}],
                )

            elif r.status_code == 404:
                return result_fail(
                    "robots.txt not found (404).",
                    "Create a robots.txt at your domain root. Minimum content:\n"
                    "User-agent: *\nDisallow:\nSitemap: https://yourdomain.com/sitemap.xml",
                    detail=f"URL: {url} returned HTTP 404.",
                    evidence=[{"url": url, "status_code": 404}],
                )
            else:
                return result_warn(
                    f"robots.txt returned status {r.status_code}.",
                    "Verify the file is accessible at the domain root.",
                    detail=f"URL: {url} returned HTTP {r.status_code}.",
                    evidence=[{"url": url, "status_code": r.status_code}],
                )
    except requests.exceptions.Timeout:
        return result_warn(
            "Could not fetch robots.txt: request timed out.",
            "Ensure the server responds promptly to /robots.txt requests.",
            detail=f"URL: {url} timed out.",
            evidence=[{"url": url, "timeout": True}],
        )
    except Exception as e:
        return result_warn(
            f"Could not fetch robots.txt: {e}",
            "Ensure the file exists at the domain root.",
            detail=f"URL: {url} error: {e}",
            evidence=[{"url": url, "error": str(e)}],
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
    favicon_probe_timeout = min(TIMEOUT, 5)
    timed_out = False
    try:
        with session.get(f"{base_url}/favicon.ico", timeout=favicon_probe_timeout, stream=True) as r:
            if r.status_code == 200:
                content = read_response_bytes(r, max_bytes=256 * 1024, max_elapsed=favicon_probe_timeout)
                if len(content) > 0:
                    return result_warn(
                        "Favicon served at /favicon.ico but not declared in <head>.",
                        "Add <link rel='icon' href='/favicon.ico'> to your <head> for maximum browser/SERP compatibility.",
                        detail=f"{base_url}/favicon.ico (HTTP 200, {len(content)} bytes)",
                    )
    except requests.exceptions.Timeout:
        timed_out = True
    except Exception:
        pass

    # ── Layer 5: Check /apple-touch-icon.png (common WordPress / modern sites) ─
    if not timed_out:
        for path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            try:
                with session.get(f"{base_url}{path}", timeout=favicon_probe_timeout, stream=True) as r:
                    if r.status_code == 200:
                        content = read_response_bytes(r, max_bytes=256 * 1024, max_elapsed=favicon_probe_timeout)
                        if len(content) > 0:
                            return result_warn(
                                f"Apple touch icon found at {path} but not declared in <head>.",
                                f"Add <link rel='apple-touch-icon' href='{path}'> to your <head>.",
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
