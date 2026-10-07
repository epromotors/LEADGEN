# auditor/indexability.py — Indexability Checks
# LeadGen OS v5.0.0 | Group C new module
# Checks: noindex, URL structure, www canonicalization, soft 404

import re
import requests
from auditor.core import result_pass, result_warn, result_fail
from config import TIMEOUT


def audit_noindex(soup) -> dict:
    """
    Detect meta robots noindex/nofollow directives.

    SEO Impact: Critical — noindex prevents page from appearing in Google.
    Source: https://developers.google.com/search/docs/crawling-indexing/block-indexing
    """
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if not robots_meta:
        return result_pass(
            "No meta robots tag found — page is indexable by default.",
            detail="Googlebot indexes pages without a meta robots tag.",
        )

    content = robots_meta.get("content", "").lower()
    if "noindex" in content:
        return result_fail(
            "Page has 'noindex' meta robots tag — Google CANNOT index this page!",
            "Remove the 'noindex' directive from the meta robots tag immediately. "
            "While 'noindex' is intentional on private pages, it is catastrophic on public pages. "
            "Check: <meta name='robots' content='noindex'> in your <head>.",
            f"Current content: '{content}'",
        )
    if "nofollow" in content:
        return result_warn(
            "Page has 'nofollow' meta robots tag — Google will not follow links on this page.",
            "Remove 'nofollow' from the meta robots tag unless you intentionally want to block link equity. "
            "Nofollow on a homepage prevents internal PageRank distribution.",
            f"Current content: '{content}'",
        )
    return result_pass(
        f"Meta robots tag is safe: '{content}'.",
        detail="Page is indexable and links are followable.",
    )


def audit_url_structure(url: str) -> dict:
    """
    Check URL for SEO-friendly structure: no double slashes, no bare query params,
    reasonable length, no uppercase characters.

    SEO Impact: Medium — clean URLs improve crawlability and CTR.
    Source: https://developers.google.com/search/docs/crawling-indexing/url-structure
    """
    from urllib.parse import urlparse, parse_qs

    if not url:
        return result_warn(
            "No URL provided for structure check.",
            "Ensure the audit URL is set correctly.",
        )

    parsed = urlparse(url)
    path = parsed.path
    query = parsed.query
    issues = []

    # Check URL length (path + query)
    url_len = len(url)
    if url_len > 115:
        issues.append(f"URL is too long ({url_len} chars — recommended max 115)")

    # Double slashes in path (excluding protocol //)
    if "//" in path:
        issues.append("Double slashes in URL path (e.g., /page//slug)")

    # Bare query parameters on homepage (e.g., ?utm_source without content)
    if query:
        params = parse_qs(query)
        non_tracking = {k: v for k, v in params.items() if not k.startswith("utm_")}
        if non_tracking:
            issues.append(f"URL has query parameters: {list(non_tracking.keys())[:3]}")

    # Uppercase in path
    if any(c.isupper() for c in path):
        issues.append("URL path contains uppercase letters (may cause duplicate content)")

    # Underscores instead of hyphens
    if "_" in path:
        issues.append("URL uses underscores instead of hyphens (Google prefers hyphens as word separators)")

    if issues:
        return result_warn(
            f"URL structure has {len(issues)} issue(s).",
            "Fix URL structure: use lowercase, hyphens, no double slashes, keep under 115 chars. "
            "Clean URLs improve CTR in search results and are easier for Googlebot to crawl.",
            " | ".join(issues),
        )

    return result_pass(
        f"URL structure is clean and SEO-friendly.",
        detail=f"URL: {url} ({len(url)} chars)",
    )


def audit_www_vs_nonwww(base_url: str, session: requests.Session) -> dict:
    """
    Check that www and non-www versions don't both return HTTP 200 independently
    (which would create a duplicate homepage for Google).

    SEO Impact: High
    Source: https://developers.google.com/search/docs/crawling-indexing/canonicalization
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    netloc = parsed.netloc

    if netloc.startswith("www."):
        canonical   = base_url
        alternative = f"{parsed.scheme}://{netloc[4:]}/"
    else:
        canonical   = base_url
        alternative = f"{parsed.scheme}://www.{netloc}/"

    try:
        r = session.get(alternative, timeout=TIMEOUT, allow_redirects=True, verify=False)
        if r.status_code == 200:
            if r.url.rstrip("/") == canonical.rstrip("/"):
                return result_pass(
                    "www / non-www alternate redirects to canonical — no duplicate issue.",
                    detail=f"{alternative} → {r.url}",
                )
            else:
                return result_fail(
                    "Both www and non-www versions return HTTP 200 independently — duplicate homepage detected!",
                    "Set up a 301 redirect so one version redirects to the other. "
                    "Declare your preferred version in Google Search Console. "
                    "Duplicate homepages split PageRank and confuse Googlebot.",
                    f"Canonical: {canonical} | Duplicate: {alternative}",
                )
        elif r.status_code in (301, 302, 308):
            return result_pass(
                f"Alternate www/non-www redirects ({r.status_code}) — no duplication.",
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


def audit_soft_404_content(soup, url: str = "") -> dict:
    """
    Deep content-based soft 404 detection — look for typical 404 page content
    even if the server returned HTTP 200.

    SEO Impact: High — soft 404s waste crawl budget and confuse indexing.
    Source: https://developers.google.com/search/docs/crawling-indexing/http-network-errors
    """
    if not soup:
        return result_warn(
            "Could not parse page content for soft 404 check.",
            "Ensure the page returns valid HTML.",
        )

    _SOFT_404_PATTERNS = re.compile(
        r"\b(page\s+not\s+found|404|not\s+found|error\s+404|oops|"
        r"doesn'?t?\s+exist|no\s+longer\s+available|moved\s+permanently|"
        r"this\s+page\s+has\s+been\s+removed|the\s+page\s+you\s+requested)"
        r"\b",
        re.IGNORECASE,
    )

    # Check title first
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""
    if _SOFT_404_PATTERNS.search(title_text):
        return result_fail(
            f"Soft 404 detected — page title suggests 'not found': '{title_text[:80]}'",
            "Ensure this page is a real content page, not an error page returning HTTP 200. "
            "Soft 404s waste crawl budget. Return proper HTTP 404 status for missing pages.",
            f"Title: {title_text}",
        )

    # Check h1
    h1 = soup.find("h1")
    h1_text = h1.get_text(strip=True) if h1 else ""
    if _SOFT_404_PATTERNS.search(h1_text):
        return result_fail(
            f"Soft 404 detected — H1 suggests error page: '{h1_text[:80]}'",
            "Ensure this page serves real content. Return HTTP 404 for pages that don't exist.",
            f"H1: {h1_text}",
        )

    # Check body text length — extremely short pages may be soft 404
    body = soup.find("body")
    body_text = body.get_text(strip=True) if body else ""
    word_count = len(body_text.split())
    if word_count < 30 and _SOFT_404_PATTERNS.search(body_text):
        return result_warn(
            "Very thin content with error-like text — possible soft 404.",
            "Ensure the page has meaningful content (300+ words). If it's an error page, return HTTP 404.",
            f"Word count: {word_count}",
        )

    return result_pass(
        "No soft 404 signals detected — page appears to have real content.",
        detail=f"Title: {title_text[:60]} | Body words: {word_count}",
    )
