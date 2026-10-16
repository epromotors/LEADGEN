# auditor/crawler.py — Multi-page internal crawler
# Discovers internal pages via origin sitemaps + recursive link following.
# Implements strict utility-route exclusion (e.g. Cloudflare email protection),
# canonical duplicate detection, rich per-page SEO inspection, and site-wide reporting.

from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from auditor.core import fetch_page, get_domain, result_pass, result_warn, result_fail, read_response_text
from auditor.images import get_image_inventory
from auditor.keyword_density import extract_visible_text, count_visible_words, analyze_keyword_on_page
from auditor.architecture import classify_page_architecture
from config import TIMEOUT, REQUEST_HEADERS

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 10
HARD_MAX_PAGES = 25
MAX_PAGES = DEFAULT_MAX_PAGES
CRAWL_WORKERS = 5
SITEMAP_DEPTH_LIMIT = 3
MAX_SITEMAPS_TO_FETCH = 5
MAX_SITEMAP_URLS = 100

LOW_VALUE_PATH_RE = re.compile(
    r"/(?:wp-content|wp-json|feed|tag|author|photo|attachment|portfolio-category)/"
    r"|/(?:banner|footlogo|googlemap|supertint-logo)(?:-\d+)?/?$"
    r"|/(?:internalpagesbanner|[^/]*(?:web-image|image-file|banner-image)[^/]*)[^/]*/?$"
    r"|/[^/]*(?:img|image|banner|logo|map|inside-page)[^/]*_\d+(?:-\d+)?/?$"
    r"|[?&](?:attachment_id|replytocom)=",
    re.IGNORECASE,
)

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "mc_cid", "mc_eid", "_ga", "_gl",
}


# ── URL classification & normalization helpers ────────────────────────────────

def classify_url_nature(url: str) -> str:
    """
    Classify URL into functional category:
      - 'utility_cloudflare': /cdn-cgi/l/email-protection, challenge, rum, etc.
      - 'non_html_asset': Media, documents, archives, stylesheets, scripts
      - 'low_value_path': Feeds, internal media attachments, WordPress JSON
      - 'content_page': Legitimate user-facing content page
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "invalid"

    path = parsed.path.lower()

    # Cloudflare utility routes: email obfuscation, bot challenges, RUM, telemetry
    if path.startswith((
        "/cdn-cgi/l/email-protection",
        "/cdn-cgi/challenge-platform",
        "/cdn-cgi/rum",
        "/cdn-cgi/trace",
        "/cdn-cgi/bm",
    )):
        return "utility_cloudflare"

    # Non-HTML file extensions
    skip_ext = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif",
        ".mp4", ".mp3", ".zip", ".tar", ".gz", ".css", ".js", ".ico", ".xml",
        ".txt", ".json", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".map",
    )
    if any(path.endswith(e) for e in skip_ext):
        return "non_html_asset"

    if LOW_VALUE_PATH_RE.search(url):
        return "low_value_path"

    return "content_page"


def is_auditable_page_url(url: str) -> bool:
    """Return True only if URL is a legitimate content page for the audit inventory."""
    return classify_url_nature(url) == "content_page"


def is_internal(url: str, base_domain: str) -> bool:
    """
    Determine if URL belongs to the same apex site domain (handles www/non-www).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower().split(":")[0].lstrip("www.")
        base = base_domain.lower().split(":")[0].lstrip("www.")
        return host == base or host == ""
    except Exception:
        return False


def normalise(url: str, base_url: str) -> str | None:
    """
    Resolve relative URLs, strip fragments, clean default index filenames,
    filter tracking query parameters, and skip utility/non-HTML resources.
    """
    try:
        full = urllib.parse.urljoin(base_url, url).split("#")[0]
        parsed = urllib.parse.urlparse(full)
        if parsed.scheme.lower() not in ("http", "https"):
            return None

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path

        # Clean default directory index filenames (e.g. /index.html -> /)
        for idx in ("/index.html", "/index.htm", "/index.php", "/default.aspx", "/default.html"):
            if path.lower().endswith(idx):
                path = path[:-len(idx)]
                if not path:
                    path = "/"
                break

        # Normalize trailing slash: root is always "/", subpaths have no trailing slash for uniform matching
        if not path or path == "/":
            path = "/"
        else:
            path = path.rstrip("/")

        # Normalize query parameters: strip tracking params, sort remaining
        clean_query = ""
        if parsed.query:
            query_parts = []
            for qp in parsed.query.split("&"):
                if not qp:
                    continue
                k = qp.split("=")[0].lower()
                if k not in TRACKING_PARAMS:
                    query_parts.append(qp)
            if query_parts:
                query_parts.sort()
                clean_query = "&".join(query_parts)

        normalized = urllib.parse.urlunparse((scheme, netloc, path, "", clean_query, ""))
        if not is_auditable_page_url(normalized):
            return None
        return normalized
    except Exception:
        return None


# ── Sitemap parser ────────────────────────────────────────────────────────────

def _parse_sitemap_xml(content: str, base_url: str) -> tuple[list[str], list[str]]:
    """Parse sitemap XML content, strictly ignoring HTML error documents."""
    page_urls = []
    child_sitemaps = []
    content_stripped = (content or "").strip()
    if not content_stripped or content_stripped.lower().startswith(("<!doctype html", "<html")):
        return page_urls, child_sitemaps

    try:
        root = ET.fromstring(content_stripped)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        if root_name not in ("urlset", "sitemapindex"):
            return page_urls, child_sitemaps

        locs = [elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1].lower() == "loc"]
        for loc in locs:
            text = (loc.text or "").strip()
            if text:
                if root_name == "sitemapindex" or text.lower().endswith(".xml"):
                    child_sitemaps.append(text)
                else:
                    page_urls.append(text)
    except ET.ParseError:
        pass
    return page_urls, child_sitemaps


def discover_via_sitemap(base_url: str, session) -> list[str]:
    """
    Return all valid internal page URLs declared in sitemap.xml (or child sitemaps).
    Probes robots.txt at origin root first, then common sitemap locations.
    """
    from auditor.core import get_origin
    root_base = get_origin(base_url)

    candidates: list[str] = []

    # Check robots.txt for Sitemap directives
    try:
        r = session.get(f"{root_base}/robots.txt", timeout=min(TIMEOUT, 5), stream=True)
        try:
            if r.status_code == 200:
                ctype = r.headers.get("Content-Type", "").lower()
                r_text = read_response_text(r, max_bytes=512 * 1024, max_elapsed=min(TIMEOUT, 5))
                if "text/html" not in ctype and not r_text.strip().lower().startswith(("<!doctype html", "<html")):
                    for line in r_text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            raw_val = line.split(":", 1)[1].strip()
                            if raw_val:
                                resolved = urllib.parse.urljoin(root_base, raw_val)
                                parsed_s = urllib.parse.urlparse(resolved)
                                if parsed_s.scheme in ("http", "https") and resolved not in candidates:
                                    candidates.append(resolved)
        finally:
            if hasattr(r, "close"):
                r.close()
    except Exception:
        pass

    # Common root fallbacks
    common_fallbacks = [
        f"{root_base}/sitemap_index.xml",
        f"{root_base}/sitemap.xml",
        f"{root_base}/sitemap-index.xml",
        f"{root_base}/wp-sitemap.xml",
        f"{root_base}/post-sitemap.xml",
        f"{root_base}/page-sitemap.xml",
    ]
    for fallback in common_fallbacks:
        if fallback not in candidates:
            candidates.append(fallback)

    domain = get_domain(base_url)
    seen_sitemaps = set()
    all_urls: list[str] = []

    def crawl_sitemap(sm_url: str, depth: int = 0) -> bool:
        if depth > SITEMAP_DEPTH_LIMIT or sm_url in seen_sitemaps:
            return False
        if len(seen_sitemaps) >= MAX_SITEMAPS_TO_FETCH or len(all_urls) >= MAX_SITEMAP_URLS:
            return bool(all_urls)
        seen_sitemaps.add(sm_url)
        try:
            r = session.get(sm_url, timeout=min(TIMEOUT, 6), stream=True)
            try:
                if r.status_code != 200:
                    return False
                ctype = r.headers.get("Content-Type", "").lower()
                if "text/html" in ctype:
                    return False
                xml_text = read_response_text(r, max_bytes=2 * 1024 * 1024, max_elapsed=min(TIMEOUT, 6))
            finally:
                if hasattr(r, "close"):
                    r.close()
            if getattr(xml_text, "is_truncated", False):
                logger.warning("[crawler] Sitemap %s truncated at byte limit", sm_url)
                return bool(all_urls)
            urls, child_sitemaps = _parse_sitemap_xml(xml_text, base_url)
            if urls:
                for u in urls:
                    norm = normalise(u, root_base)
                    if norm and is_internal(norm, domain):
                        all_urls.append(norm)
                        if len(all_urls) >= MAX_SITEMAP_URLS:
                            break
            for child in child_sitemaps:
                if len(seen_sitemaps) >= MAX_SITEMAPS_TO_FETCH or len(all_urls) >= MAX_SITEMAP_URLS:
                    break
                resolved_child = urllib.parse.urljoin(root_base, child)
                if is_internal(resolved_child, domain):
                    crawl_sitemap(resolved_child, depth + 1)
            return bool(urls or child_sitemaps)
        except Exception:
            return False

    for sm_url in candidates:
        if crawl_sitemap(sm_url):
            break

    return [u for u in dict.fromkeys(all_urls) if is_internal(u, domain)]


def _prioritize_urls(urls: list[str], base_url: str) -> list[str]:
    """Prefer core business and navigation pages before archives."""
    base = normalise(base_url, base_url) or base_url.rstrip("/")
    important_terms = (
        "about", "contact", "service", "services", "product", "products",
        "pricing", "gallery", "portfolio", "faq", "location", "locations",
        "privacy", "terms", "case-studies", "solutions",
    )

    def score(url: str) -> tuple[int, int, str]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip("/").lower()
        if url == base:
            return (0, 0, url)
        if any(path == term or path.startswith(f"{term}/") for term in important_terms):
            return (1, path.count("/"), url)
        if path.count("/") <= 1:
            return (2, path.count("/"), url)
        return (3, path.count("/"), url)

    return sorted(dict.fromkeys(urls), key=score)


# ── Recursive link crawler ────────────────────────────────────────────────────

def crawl_site(
    base_url: str,
    session,
    max_pages: int = MAX_PAGES,
    progress_cb=None,
    target_keywords: list[str] | None = None,
) -> list[dict]:
    """
    Multi-source BFS crawl of internal pages.
    Discovers URLs from:
      1. Origin robots.txt & XML sitemaps
      2. In-page navigation, footer, and body anchors
    Enforces URL normalization, deduplication, and utility route exclusion.
    """
    norm_base = normalise(base_url, base_url) or base_url.rstrip("/")
    max_pages = min(max_pages, HARD_MAX_PAGES)
    t_start = time.perf_counter()
    logger.info("[crawler] Starting crawl for %s (max_pages=%d)", base_url, max_pages)
    domain = get_domain(norm_base)

    visited: set[str] = set()
    queue: list[str] = [norm_base]
    pages: list[dict] = []

    # 1. Sitemap Discovery
    sitemap_urls = discover_via_sitemap(norm_base, session)
    sitemap_set = set(sitemap_urls)

    for u in _prioritize_urls(sitemap_urls, norm_base):
        if u not in queue:
            queue.append(u)

    def fetch_one(url):
        return fetch_page(url, session)

    discovered_via_links: set[str] = set()
    canonical_targets: dict[str, str] = {}
    duplicate_records: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=CRAWL_WORKERS) as executor:
        while queue and len(pages) < max_pages:
            batch = []
            batch_limit = min(CRAWL_WORKERS, max_pages - len(pages))
            while queue and len(batch) < batch_limit:
                candidate_url = queue.pop(0)
                if candidate_url in visited:
                    continue
                visited.add(candidate_url)
                batch.append(candidate_url)

            if not batch:
                break

            futures = {executor.submit(fetch_one, u): u for u in batch}
            for future in as_completed(futures):
                req_url = futures[future]
                try:
                    page = future.result()
                except Exception as exc:
                    page = {
                        "ok": False,
                        "url": req_url,
                        "final_url": req_url,
                        "status_code": None,
                        "html": "",
                        "soup": None,
                        "headers": {},
                        "error": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
                    }

                # Check canonical relationship to prevent duplicate content inflation
                soup = page.get("soup")
                final_url = page.get("final_url") or req_url
                norm_final = normalise(final_url, norm_base) or final_url

                if soup:
                    can_tag = soup.find("link", rel=lambda x: x and "canonical" in x)
                    can_href = can_tag.get("href", "").strip() if can_tag else None
                    if can_href:
                        norm_can = normalise(can_href, norm_final)
                        if norm_can:
                            canonical_targets[norm_final] = norm_can

                pages.append(page)

                if progress_cb:
                    progress_cb(page["url"], len(pages), max_pages)

                # Link discovery on fetched page
                if page.get("ok") and soup:
                    nav_links = []
                    other_links = []
                    for tag in soup.find_all("a", href=True):
                        raw_href = tag["href"].strip()
                        norm_link = normalise(raw_href, norm_final)
                        if not norm_link or not is_internal(norm_link, domain):
                            continue

                        discovered_via_links.add(norm_link)

                        if norm_link in visited:
                            continue

                        parent_names = [p.name for p in tag.parents]
                        tag_classes = tag.get("class", [])
                        if isinstance(tag_classes, str):
                            tag_classes = [tag_classes]
                        is_nav_or_footer = (
                            any(p in ("nav", "header", "footer") for p in parent_names)
                            or any("nav" in c.lower() or "menu" in c.lower() or "footer" in c.lower() for c in tag_classes)
                        )
                        if is_nav_or_footer:
                            if norm_link not in nav_links:
                                nav_links.append(norm_link)
                        else:
                            if norm_link not in other_links:
                                other_links.append(norm_link)

                    for n in reversed(nav_links):
                        if n not in queue and n not in visited:
                            queue.insert(0, n)
                    for o in other_links:
                        if o not in queue and o not in visited:
                            queue.append(o)

                    if len(queue) > 500:
                        queue = _prioritize_urls(queue, norm_base)[:500]

                if len(pages) >= max_pages:
                    break

    elapsed_ms = round((time.perf_counter() - t_start) * 1000)
    logger.info(
        "[crawler] Completed crawl for %s in %d ms (pages_fetched=%d, sitemap_urls=%d, link_discovered=%d)",
        base_url, elapsed_ms, len(pages), len(sitemap_set), len(discovered_via_links)
    )

    # Attach crawl discovery context to first page for site summary aggregation
    if pages:
        homepage_soup = pages[0].get("soup")
        arch_data = None
        if homepage_soup:
            try:
                arch_data = classify_page_architecture(homepage_soup, norm_base, pages)
            except Exception as _arch_err:
                logger.warning("[crawler] classify_page_architecture error: %s", _arch_err)
        pages[0]["_crawl_meta"] = {
            "sitemap_url_count": len(sitemap_set),
            "link_discovered_count": len(discovered_via_links),
            "total_discovered_count": len(sitemap_set.union(discovered_via_links)),
            "crawl_limit_hit": bool(queue),
            "max_pages": max_pages,
            "canonical_targets": canonical_targets,
            "architecture": arch_data,
        }

    return pages


# ── Per-page SEO check (comprehensive, runs on every crawled page) ───────────

def audit_page_seo(page: dict, target_keywords: list[str] | None = None) -> dict:
    """
    Run comprehensive SEO checks on a single crawled page.
    Produces structured diagnostics for URL identity, metadata, headings,
    word count, keyword density, outbound links, and image alt text.
    """
    url = page.get("final_url") or page.get("url", "")
    soup = page.get("soup")
    html = page.get("html", "")
    issues: list[dict[str, str]] = []

    if not page.get("ok") or not soup:
        status_code = page.get("status_code")
        err_msg = page.get("error") or f"HTTP {status_code}"
        return {
            "url": url,
            "status_code": status_code,
            "error": err_msg,
            "title": "(unreachable)",
            "meta_description": "",
            "canonical_url": None,
            "canonical_relationship": "unreachable",
            "word_count": 0,
            "h1_count": 0,
            "h2_count": 0,
            "headings": [],
            "image_count": 0,
            "images_missing_alt": 0,
            "internal_links_outbound": 0,
            "external_links_outbound": 0,
            "indexable": False,
            "keyword_analysis": {},
            "issues": [{"severity": "FAIL", "check": "Page Unreachable", "msg": err_msg}],
            "status": "FAIL",
            "issue_count": 1,
        }

    # 1. Page Title
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""
    title_len = len(title_text)
    if not title_text:
        issues.append({"severity": "FAIL", "check": "Missing Title", "msg": "No <title> tag found on page"})
    elif title_len > 65:
        issues.append({"severity": "WARN", "check": "Title Too Long", "msg": f"{title_len} chars: '{title_text[:50]}...'"})
    elif title_len < 30:
        issues.append({"severity": "WARN", "check": "Title Too Short", "msg": f"{title_len} chars: '{title_text}'"})

    # 2. Meta Description
    meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc_text = (meta_desc.get("content") or "").strip() if meta_desc else ""
    desc_len = len(desc_text)
    if not desc_text:
        issues.append({"severity": "FAIL", "check": "Missing Meta Description", "msg": "No meta description configured"})
    elif desc_len > 165:
        issues.append({"severity": "WARN", "check": "Meta Description Too Long", "msg": f"{desc_len} chars (recommended: 150-160)"})
    elif desc_len < 70:
        issues.append({"severity": "WARN", "check": "Meta Description Too Short", "msg": f"{desc_len} chars"})

    # 3. Headings (H1 & H2)
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
    if not h1s:
        issues.append({"severity": "FAIL", "check": "Missing H1", "msg": "No H1 heading found on page"})
    elif len(h1s) > 1:
        issues.append({"severity": "WARN", "check": "Multiple H1 Tags", "msg": f"{len(h1s)} H1 tags found"})

    # 4. Canonical URL & Duplicate Relationship
    can_tag = soup.find("link", rel=lambda x: x and "canonical" in x)
    can_href = (can_tag.get("href") or "").strip() if can_tag else None
    can_relationship = "missing"
    if can_href:
        clean_can = normalise(can_href, url) or can_href.rstrip("/")
        clean_url = normalise(url, url) or url.rstrip("/")
        if clean_can == clean_url:
            can_relationship = "self"
        else:
            can_domain = get_domain(clean_can)
            url_domain = get_domain(clean_url)
            if can_domain == url_domain:
                can_relationship = "canonical_alias"
            else:
                can_relationship = "cross_domain"
    else:
        issues.append({"severity": "WARN", "check": "Missing Canonical", "msg": "No canonical tag declared"})

    # 5. Image Accounting via get_image_inventory
    inv = get_image_inventory(soup)
    total_imgs = inv["total_elements"]
    missing_alt_count = len(inv["missing_alt"])
    empty_alt_count = len(inv["empty_alt"])
    webp_count = len(inv["webp_elements"])

    if missing_alt_count > 0:
        pct = round(missing_alt_count / total_imgs * 100) if total_imgs else 0
        issues.append({
            "severity": "FAIL" if pct > 40 else "WARN",
            "check": "Images Missing Alt",
            "msg": f"{missing_alt_count}/{total_imgs} images missing alt text ({pct}%)",
        })

    # 6. Visible-Word Count
    visible_text = extract_visible_text(soup)
    word_count = count_visible_words(visible_text)
    if word_count < 100:
        issues.append({"severity": "WARN", "check": "Thin Content", "msg": f"Only {word_count} visible words on page"})

    # 7. Outbound Link Accounting
    domain = get_domain(url)
    internal_links_out = 0
    external_links_out = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full_href = urllib.parse.urljoin(url, href)
        if is_internal(full_href, domain):
            internal_links_out += 1
        else:
            external_links_out += 1

    # 8. Indexability signals
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_content = (robots_meta.get("content") or "").lower() if robots_meta else ""
    is_noindex = "noindex" in robots_content
    if is_noindex:
        issues.append({"severity": "WARN", "check": "Noindex Directive", "msg": "Page declares noindex in meta robots"})

    # 9. OG Image Check
    og_image = soup.find("meta", property="og:image")
    if not og_image:
        issues.append({"severity": "WARN", "check": "Missing og:image", "msg": "No Open Graph preview image declared"})

    # 10. Target Keyword Analysis for this Page
    page_kw_results: list[dict[str, Any]] = []
    if target_keywords:
        for kw in target_keywords:
            if kw.strip():
                kw_data = analyze_keyword_on_page(soup, url, kw.strip(), visible_text, word_count)
                page_kw_results.append(kw_data)

    status = "FAIL" if any(i["severity"] == "FAIL" for i in issues) \
        else ("WARN" if issues else "PASS")

    return {
        "url": url,
        "status_code": page.get("status_code", 200),
        "title": title_text or "(no title)",
        "title_length": title_len,
        "meta_description": desc_text,
        "meta_desc_length": desc_len,
        "canonical_url": can_href,
        "canonical_relationship": can_relationship,
        "word_count": word_count,
        "h1_count": len(h1s),
        "h2_count": len(h2s),
        "headings": {"h1": h1s[:3], "h2": h2s[:5]},
        "image_count": total_imgs,
        "images_with_alt": len(inv["with_alt"]),
        "images_empty_alt": empty_alt_count,
        "images_missing_alt": missing_alt_count,
        "webp_images": webp_count,
        "internal_links_outbound": internal_links_out,
        "external_links_outbound": external_links_out,
        "indexable": not is_noindex,
        "keyword_analysis": page_kw_results,
        "issues": issues,
        "status": status,
        "issue_count": len(issues),
    }


# ── Site-wide aggregation ─────────────────────────────────────────────────────

def aggregate_site_issues(page_audits: list[dict], crawl_meta: dict | None = None) -> dict:
    """
    Summarise site-wide patterns across all crawled pages:
      - Total pages crawled, clean pages, warnings, failures
      - Common issues ranking
      - High-issue pages
      - Sitemap count vs Link-discovered HTML pages
    """
    totals = {"FAIL": 0, "WARN": 0, "PASS": 0}
    check_counts: dict[str, int] = {}

    for audit in page_audits:
        st = audit.get("status", "FAIL")
        totals[st] = totals.get(st, 0) + 1
        for issue in audit.get("issues", []):
            ck = issue["check"]
            check_counts[ck] = check_counts.get(ck, 0) + 1

    top_issues = sorted(check_counts.items(), key=lambda x: x[1], reverse=True)

    worst_pages = sorted(
        [p for p in page_audits if p.get("issue_count", 0) > 0],
        key=lambda p: p.get("issue_count", 0),
        reverse=True,
    )[:10]

    # Meta discovery stats
    sitemap_count = crawl_meta.get("sitemap_url_count", 0) if crawl_meta else 0
    link_discovered_count = crawl_meta.get("link_discovered_count", 0) if crawl_meta else 0
    total_discovered = crawl_meta.get("total_discovered_count", len(page_audits)) if crawl_meta else len(page_audits)
    crawl_limit_hit = crawl_meta.get("crawl_limit_hit", False) if crawl_meta else False

    # Explanation if sitemap count differs from link discovered
    explanation = ""
    if sitemap_count > 0 and link_discovered_count > 0:
        if sitemap_count == 1 and link_discovered_count > 1:
            explanation = (
                f"Sitemap lists 1 URL; {link_discovered_count} additional internal HTML pages "
                "were discovered through navigation and internal anchors."
            )
        elif sitemap_count != link_discovered_count:
            explanation = (
                f"Sitemap lists {sitemap_count} URLs; {link_discovered_count} HTML pages discovered "
                f"via internal links ({total_discovered} total unique URLs discovered)."
            )
    elif sitemap_count > 0:
        explanation = f"Sitemap declared {sitemap_count} URLs."
    elif link_discovered_count > 0:
        explanation = f"{link_discovered_count} HTML pages discovered via navigation links (no sitemap URLs found)."

    if crawl_limit_hit:
        explanation += f" Crawl limit ({len(page_audits)} pages) prevented full coverage of all {total_discovered} discovered pages."

    arch_data = crawl_meta.get("architecture") if crawl_meta else None

    return {
        "total_pages": len(page_audits),
        "status_counts": totals,
        "top_issues": top_issues,
        "worst_pages": worst_pages,
        "sitemap_url_count": sitemap_count,
        "link_discovered_count": link_discovered_count,
        "total_discovered_count": total_discovered,
        "crawl_limit_hit": crawl_limit_hit,
        "discovery_explanation": explanation,
        "coverage_score": round(totals["PASS"] / max(len(page_audits), 1) * 100),
        "architecture": arch_data,
    }
