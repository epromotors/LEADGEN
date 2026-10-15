# auditor/crawler.py — Multi-page internal crawler
# Discovers all internal pages via sitemap + recursive link following
# Then runs per-page SEO checks and aggregates findings site-wide

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from auditor.core import fetch_page, get_domain, result_pass, result_warn, result_fail, read_response_text
from config import TIMEOUT, REQUEST_HEADERS

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 10
HARD_MAX_PAGES = 25
MAX_PAGES   = DEFAULT_MAX_PAGES   # default cap to avoid runaway crawls
CRAWL_WORKERS = 5   # parallel page fetches
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


# ── URL helpers ───────────────────────────────────────────────────────────────

def is_internal(url: str, base_domain: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lstrip("www.")
    return host == base_domain or host == f"www.{base_domain}" or host == ""


def is_auditable_page_url(url: str) -> bool:
    """Skip low-value technical/media URLs so page budget covers real pages."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    skip_ext = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".mp4", ".mp3", ".zip", ".css", ".js", ".ico", ".xml",
        ".txt", ".json", ".woff", ".woff2",
    )
    if any(path.endswith(e) for e in skip_ext):
        return False
    if LOW_VALUE_PATH_RE.search(url):
        return False
    return True


def normalise(url: str, base_url: str) -> str | None:
    """Resolve relative URLs, strip fragments, skip non-HTML resources."""
    try:
        full = urllib.parse.urljoin(base_url, url).split("#")[0].rstrip("/")
        parsed = urllib.parse.urlparse(full)
        if parsed.scheme not in ("http", "https"):
            return None
        if not is_auditable_page_url(full):
            return None
        return full
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

        for loc in root.findall(".//sm:loc", ns) or root.findall(".//loc"):
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
    Return all URLs from sitemap.xml (or sitemap index).
    Site origin is derived from base_url so robots.txt and sitemaps are probed at domain root.
    Site-wide crawl policy: Traverses same-origin paths across the domain, not constrained to subpaths.
    """
    from auditor.core import get_origin
    root_base = get_origin(base_url)

    candidates: list[str] = []

    # Check robots.txt for Sitemap directives first
    try:
        with session.get(f"{root_base}/robots.txt", timeout=min(TIMEOUT, 5), stream=True) as r:
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
    all_urls = []

    def crawl_sitemap(sm_url: str, depth: int = 0) -> bool:
        if depth > SITEMAP_DEPTH_LIMIT or sm_url in seen_sitemaps:
            return False
        if len(seen_sitemaps) >= MAX_SITEMAPS_TO_FETCH or len(all_urls) >= MAX_SITEMAP_URLS:
            return bool(all_urls)
        seen_sitemaps.add(sm_url)
        try:
            with session.get(sm_url, timeout=min(TIMEOUT, 6), stream=True) as r:
                if r.status_code != 200:
                    return False
                ctype = r.headers.get("Content-Type", "").lower()
                if "text/html" in ctype:
                    return False
                xml_text = read_response_text(r, max_bytes=2 * 1024 * 1024, max_elapsed=min(TIMEOUT, 6))
            if getattr(xml_text, "is_truncated", False):
                logger.warning("[crawler] Sitemap %s truncated at byte limit; ignoring partial entries", sm_url)
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
    """Prefer core business pages before long-tail archives or media pages."""
    base = base_url.rstrip("/")
    important_terms = (
        "about", "contact", "service", "services", "product", "products",
        "pricing", "gallery", "portfolio", "faq", "location", "locations",
        "privacy", "terms",
    )

    def score(url: str) -> tuple[int, int, str]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip("/").lower()
        if url.rstrip("/") == base:
            return (0, 0, url)
        if any(path == term or path.startswith(f"{term}/") for term in important_terms):
            return (1, path.count("/"), url)
        if path.count("/") <= 1:
            return (2, path.count("/"), url)
        return (3, path.count("/"), url)

    return sorted(dict.fromkeys(urls), key=score)


# ── Recursive link crawler ────────────────────────────────────────────────────

def crawl_site(base_url: str, session, max_pages: int = MAX_PAGES,
               progress_cb=None) -> list[dict]:
    """
    BFS crawl of internal pages.
    Returns list of page dicts: {url, status_code, soup, html, error}
    """
    base_url = base_url.rstrip("/")
    max_pages = min(max_pages, HARD_MAX_PAGES)
    t_start = time.perf_counter()
    logger.info("[crawler] Starting crawl for %s (max_pages=%d)", base_url, max_pages)
    domain = get_domain(base_url)
    visited = set()
    queue   = [base_url]
    pages   = []

    # Seed from sitemap first (higher-quality URL list)
    sitemap_urls = discover_via_sitemap(base_url, session)
    for u in _prioritize_urls(sitemap_urls, base_url):
        if u not in queue:
            queue.append(u)

    def fetch_one(url):
        return fetch_page(url, session)

    # Single executor for the full crawl (not recreated per batch)
    with ThreadPoolExecutor(max_workers=CRAWL_WORKERS) as executor:
        while queue and len(pages) < max_pages:
            # Take a batch bounded by remaining pages needed
            batch = []
            batch_limit = min(CRAWL_WORKERS, max_pages - len(pages))
            while queue and len(batch) < batch_limit:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                batch.append(url)

            if not batch:
                break

            futures = {executor.submit(fetch_one, u): u for u in batch}
            for future in as_completed(futures):
                try:
                    page = future.result()
                except Exception as exc:
                    url = futures[future]
                    page = {
                        "ok": False,
                        "url": url,
                        "final_url": url,
                        "status_code": None,
                        "html": "",
                        "soup": None,
                        "headers": {},
                        "error": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
                    }
                pages.append(page)

                if progress_cb:
                    progress_cb(page["url"], len(pages), max_pages)

                # Discover new links from this page
                if page["ok"] and page["soup"]:
                    nav_links = []
                    other_links = []
                    for tag in page["soup"].find_all("a", href=True):
                        href = tag["href"].strip()
                        norm = normalise(href, page["final_url"])
                        if norm and is_internal(norm, domain) and norm not in visited:
                            parent_names = [p.name for p in tag.parents]
                            tag_classes = tag.get("class", [])
                            if isinstance(tag_classes, str):
                                tag_classes = [tag_classes]
                            is_nav_or_footer = (
                                any(p in ("nav", "header", "footer") for p in parent_names) or
                                any("nav" in c.lower() or "menu" in c.lower() or "footer" in c.lower() for c in tag_classes)
                            )
                            if is_nav_or_footer:
                                if norm not in nav_links:
                                    nav_links.append(norm)
                            else:
                                if norm not in other_links:
                                    other_links.append(norm)

                    # Insert nav/footer links at the front so they are crawled first
                    for n in reversed(nav_links):
                        if n not in queue:
                            queue.insert(0, n)
                    # Append other links to the end
                    for o in other_links:
                        if o not in queue:
                            queue.append(o)

                    # Cap queue size to avoid memory exhaustion on large sites
                    if len(queue) > 500:
                        queue = _prioritize_urls(queue, base_url)[:500]

                if len(pages) >= max_pages:
                    break

    elapsed_ms = round((time.perf_counter() - t_start) * 1000)
    logger.info("[crawler] Completed crawl for %s in %d ms (pages_fetched=%d)", base_url, elapsed_ms, len(pages))
    return pages


# ── Per-page SEO check (lightweight, runs on every page) ─────────────────────

def audit_page_seo(page: dict) -> dict:
    """
    Run lightweight SEO checks on a single page.
    Returns a dict of findings for that page.
    """
    url  = page.get("final_url") or page.get("url", "")
    soup = page.get("soup")
    html = page.get("html", "")
    issues = []

    if not page.get("ok") or not soup:
        return {
            "url": url,
            "status": page.get("status_code"),
            "error": page.get("error"),
            "issues": [{"severity": "FAIL", "check": "Page Unreachable",
                        "msg": page.get("error", f"HTTP {page.get('status_code')}")}],
        }

    # Title
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""
    if not title_text:
        issues.append({"severity": "FAIL", "check": "Missing Title", "msg": "No <title> tag"})
    elif len(title_text) > 65:
        issues.append({"severity": "WARN", "check": "Title Too Long",
                       "msg": f"{len(title_text)} chars: '{title_text[:55]}...'"})
    elif len(title_text) < 30:
        issues.append({"severity": "WARN", "check": "Title Too Short",
                       "msg": f"{len(title_text)} chars: '{title_text}'"})

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if not meta_desc or not meta_desc.get("content", "").strip():
        issues.append({"severity": "FAIL", "check": "Missing Meta Description", "msg": "No meta description"})

    # H1
    h1s = soup.find_all("h1")
    if not h1s:
        issues.append({"severity": "FAIL", "check": "Missing H1", "msg": "No H1 tag on page"})
    elif len(h1s) > 1:
        issues.append({"severity": "WARN", "check": "Multiple H1 Tags",
                       "msg": f"{len(h1s)} H1 tags found"})

    # Canonical
    canonical = soup.find("link", rel=lambda x: x and "canonical" in x)
    if not canonical:
        issues.append({"severity": "WARN", "check": "Missing Canonical",
                       "msg": "No canonical tag — risk of duplicate content"})

    # Images without alt
    imgs = soup.find_all("img")
    no_alt = [i for i in imgs if i.get("alt") is None]
    if no_alt:
        issues.append({"severity": "WARN" if len(no_alt) < len(imgs) else "FAIL",
                       "check": "Images Missing Alt",
                       "msg": f"{len(no_alt)}/{len(imgs)} images lack alt text"})

    # OG image
    og_image = soup.find("meta", property="og:image")
    if not og_image:
        issues.append({"severity": "WARN", "check": "Missing og:image",
                       "msg": "No Open Graph image — links won't preview on social/WhatsApp"})

    status = "FAIL" if any(i["severity"] == "FAIL" for i in issues) \
        else ("WARN" if issues else "PASS")

    return {
        "url": url,
        "status_code": page.get("status_code"),
        "title": title_text or "(no title)",
        "issues": issues,
        "status": status,
        "issue_count": len(issues),
    }


# ── Site-wide aggregation ─────────────────────────────────────────────────────

def aggregate_site_issues(page_audits: list[dict]) -> dict:
    """
    Summarise site-wide patterns:
    - pages missing title / desc / h1 / canonical
    - total issues by severity
    - pages with most problems
    """
    totals = {"FAIL": 0, "WARN": 0, "PASS": 0}
    check_counts = {}   # check_name → count of pages affected

    for audit in page_audits:
        totals[audit.get("status", "FAIL")] += 1
        for issue in audit.get("issues", []):
            ck = issue["check"]
            check_counts[ck] = check_counts.get(ck, 0) + 1

    # Sort by most-affected
    top_issues = sorted(check_counts.items(), key=lambda x: x[1], reverse=True)

    # Pages with most issues
    worst_pages = sorted(
        [p for p in page_audits if p.get("issue_count", 0) > 0],
        key=lambda p: p.get("issue_count", 0),
        reverse=True
    )[:10]

    return {
        "total_pages": len(page_audits),
        "status_counts": totals,
        "top_issues": top_issues,
        "worst_pages": worst_pages,
        "coverage_score": round(totals["PASS"] / max(len(page_audits), 1) * 100),
    }
