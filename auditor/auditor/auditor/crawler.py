# auditor/crawler.py — Multi-page internal crawler
# Discovers all internal pages via sitemap + recursive link following
# Then runs per-page SEO checks and aggregates findings site-wide

import urllib.parse
import xml.etree.ElementTree as ET
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from auditor.core import fetch_page, get_domain, result_pass, result_warn, result_fail
from config import TIMEOUT, REQUEST_HEADERS

MAX_PAGES   = 100   # hard cap to avoid runaway crawls
CRAWL_WORKERS = 5   # parallel page fetches
SITEMAP_DEPTH_LIMIT = 3

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
    page_urls = []
    child_sitemaps = []
    try:
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        # sitemap index → recurse (just grab locs, don't follow sub-sitemaps here)
        for loc in root.findall(".//sm:loc", ns):
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
    """Return all URLs from sitemap.xml (or sitemap index)."""
    parsed_base = urllib.parse.urlparse(base_url)
    root_base = f"{parsed_base.scheme}://{parsed_base.netloc}"
    candidates = [
        f"{root_base}/sitemap.xml",
        f"{root_base}/sitemap_index.xml",
    ]
    # Also check robots.txt for Sitemap directive
    try:
        r = session.get(f"{root_base}/robots.txt", timeout=TIMEOUT)
        for line in r.text.splitlines():
            if line.lower().startswith("sitemap:"):
                sm_url = line.split(":", 1)[1].strip()
                if sm_url not in candidates:
                    candidates.insert(0, sm_url)
    except Exception:
        pass

    domain = get_domain(base_url)
    seen_sitemaps = set()
    all_urls = []

    def crawl_sitemap(sm_url: str, depth: int = 0) -> bool:
        if depth > SITEMAP_DEPTH_LIMIT or sm_url in seen_sitemaps:
            return False
        seen_sitemaps.add(sm_url)
        try:
            r = session.get(sm_url, timeout=TIMEOUT)
            if r.status_code != 200:
                return False
            urls, child_sitemaps = _parse_sitemap_xml(r.text, base_url)
            if urls:
                for u in urls:
                    norm = normalise(u, root_base)
                    if norm and is_internal(norm, domain):
                        all_urls.append(norm)
            for child in child_sitemaps:
                if is_internal(child, domain):
                    crawl_sitemap(child, depth + 1)
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
            # Take a batch
            batch = []
            while queue and len(batch) < CRAWL_WORKERS:
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
