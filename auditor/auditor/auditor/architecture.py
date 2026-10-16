# auditor/architecture.py — Page Architecture Classifier
# Classifies websites into:
#   - single_page: primary navigation primarily targets section IDs with fragments (e.g. /#services, #about)
#   - multi_page: navigation leads to distinct HTML documents or routes
#   - hybrid: meaningful section anchors and distinct content pages both exist
# Tracks observed evidence, confidence, limitations, in-page sections, and standalone policy documents.

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup

from auditor.core import get_domain
from auditor.keyword_density import count_visible_words, extract_visible_text

logger = logging.getLogger(__name__)

POLICY_PATH_PATTERN = re.compile(
    r"(?:privacy|cookie|cookies|terms|tos|disclaimer|legal|gdpr|compliance|imprint|statut)",
    re.IGNORECASE,
)

TRACKING_PARAM_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "mc_cid", "mc_eid", "_ga", "_gl",
}

DEFAULT_INDEX_FILENAMES = (
    "/index.html", "/index.htm", "/index.php", "/default.aspx", "/default.html"
)


def is_standalone_policy_page(url_or_path: str) -> bool:
    """Return True if URL/path represents a legitimate standalone legal or policy document."""
    try:
        parsed = urllib.parse.urlparse(url_or_path)
        path = parsed.path.lower()
    except Exception:
        path = str(url_or_path).lower()
    return bool(POLICY_PATH_PATTERN.search(path))


def normalize_clean_route(url: str, base_url: str) -> str | None:
    """
    Normalize route: strip fragment, strip default index filename, strip tracking parameters.
    Returns cleaned URL or None if invalid.
    """
    try:
        joined = urllib.parse.urljoin(base_url, url)
        parsed = urllib.parse.urlparse(joined)
        if parsed.scheme.lower() not in ("http", "https"):
            return None

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"

        for idx in DEFAULT_INDEX_FILENAMES:
            if path.lower().endswith(idx):
                path = path[:-len(idx)] or "/"
                break

        if not path or path == "/":
            path = "/"
        else:
            path = path.rstrip("/")

        clean_query = ""
        if parsed.query:
            q_parts = []
            for qp in parsed.query.split("&"):
                if not qp:
                    continue
                k = qp.split("=")[0].lower()
                if k not in TRACKING_PARAM_KEYS:
                    q_parts.append(qp)
            if q_parts:
                q_parts.sort()
                clean_query = "&".join(q_parts)

        return urllib.parse.urlunparse((scheme, netloc, path, "", clean_query, ""))
    except Exception:
        return None


def extract_primary_nav_elements(soup: BeautifulSoup) -> list[Any]:
    """Find primary navigation elements in the DOM."""
    navs = soup.find_all(["nav", "header"])
    if not navs:
        navs = soup.find_all(
            lambda tag: tag.name in ["div", "ul", "section"] and any(
                term in (tag.get("class", []) if isinstance(tag.get("class", []), list) else [tag.get("class", "")])
                or term in tag.get("id", "").lower()
                for term in ("nav", "navbar", "menu", "header-menu", "site-navigation")
            )
        )
    return navs


def extract_in_page_sections(soup: BeautifulSoup, fragment_ids: list[str]) -> list[dict[str, Any]]:
    """
    Audit in-page sections of a single-page or hybrid site.
    Extracts section ID, heading, approximate word count, and visibility.
    """
    sections = []
    seen_ids = set()

    # 1. Target sections from fragment navigation targets
    for fid in fragment_ids:
        clean_id = fid.lstrip("#")
        if not clean_id or clean_id in seen_ids:
            continue
        el = soup.find(id=clean_id) or soup.find(attrs={"name": clean_id})
        if el:
            seen_ids.add(clean_id)
            h = el.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            heading_text = h.get_text(strip=True) if h else ""
            txt = extract_visible_text(el)
            w_count = count_visible_words(txt)
            sections.append({
                "id": clean_id,
                "anchor": f"#{clean_id}",
                "heading": heading_text or f"Section: {clean_id}",
                "word_count": w_count,
                "has_content": w_count > 10,
                "target_type": "nav_anchor",
            })

    # 2. Also find distinct <section id="..."> tags if not already listed
    for sec in soup.find_all("section", id=True):
        sid = sec.get("id", "").strip()
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        h = sec.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        heading_text = h.get_text(strip=True) if h else ""
        txt = extract_visible_text(sec)
        w_count = count_visible_words(txt)
        if w_count > 15 or heading_text:
            sections.append({
                "id": sid,
                "anchor": f"#{sid}",
                "heading": heading_text or f"Section: {sid}",
                "word_count": w_count,
                "has_content": w_count > 10,
                "target_type": "dom_section",
            })

    return sections


def classify_page_architecture(
    soup: BeautifulSoup | None,
    base_url: str,
    crawled_pages: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Evidence-based page architecture classifier.
    Categorizes the site as:
      - 'single_page': primary navigation primarily targets section IDs with fragments (e.g. /#services, #about).
      - 'multi_page': navigation leads to distinct HTML documents or routes.
      - 'hybrid': meaningful section anchors and distinct content pages both exist.
    """
    base_clean = normalize_clean_route(base_url, base_url) or base_url.rstrip("/")
    base_domain = get_domain(base_clean)

    if not soup:
        # Fallback if soup is unavailable
        total_crawled = len(crawled_pages or [])
        arch = "multi_page" if total_crawled > 2 else "single_page"
        return {
            "architecture": arch,
            "confidence": "low",
            "primary_navigation": {
                "total_nav_links": 0,
                "fragment_nav_links": [],
                "route_nav_links": [],
                "external_nav_links": [],
                "fragment_ratio": 0.0,
            },
            "sections": [],
            "section_count": 0,
            "distinct_content_pages": [p.get("url") for p in (crawled_pages or []) if p.get("url")],
            "distinct_document_count": total_crawled,
            "standalone_policy_pages": [],
            "evidence": [f"Evaluated purely on {total_crawled} crawled page URL(s) without DOM."],
            "limitations": ["HTML DOM unavailable; classification inferred from URL count."],
            "summary": f"Inferred {arch} architecture from crawl inventory.",
        }

    # Extract navigation elements
    nav_elements = extract_primary_nav_elements(soup)
    nav_links_raw: list[str] = []

    for nav in nav_elements:
        for a in nav.find_all("a", href=True):
            href = a["href"].strip()
            if href:
                nav_links_raw.append(href)

    # Fallback: if <nav> is empty or missing, inspect top body anchor links
    is_fallback_nav = False
    if len(nav_links_raw) < 2:
        is_fallback_nav = True
        body_anchors = soup.find_all("a", href=True)
        for a in body_anchors[:40]:  # sample top anchors
            href = a["href"].strip()
            if href:
                nav_links_raw.append(href)

    fragment_nav_links: list[str] = []
    route_nav_links: list[str] = []
    external_nav_links: list[str] = []
    standalone_policy_links: list[str] = []

    parsed_base = urllib.parse.urlparse(base_clean)
    base_path_clean = parsed_base.path or "/"

    for raw_href in nav_links_raw:
        if raw_href.startswith(("mailto:", "tel:", "javascript:", "whatsapp:")):
            continue

        # In-page fragment check
        if raw_href.startswith("#"):
            if len(raw_href) > 1 and raw_href not in fragment_nav_links:
                fragment_nav_links.append(raw_href)
            continue

        full_url = urllib.parse.urljoin(base_clean, raw_href)
        parsed = urllib.parse.urlparse(full_url)
        link_domain = get_domain(full_url)

        # External link
        if link_domain != base_domain and link_domain.replace("www.", "") != base_domain.replace("www.", ""):
            if full_url not in external_nav_links:
                external_nav_links.append(full_url)
            continue

        # Check if URL targets the base document with a fragment (e.g. /#services, /index.html#services)
        clean_path = parsed.path or "/"
        for idx in DEFAULT_INDEX_FILENAMES:
            if clean_path.lower().endswith(idx):
                clean_path = clean_path[:-len(idx)] or "/"
                break
        clean_path = clean_path.rstrip("/") or "/"

        if clean_path == base_path_clean and parsed.fragment:
            frag_val = f"#{parsed.fragment}"
            if frag_val not in fragment_nav_links:
                fragment_nav_links.append(frag_val)
            continue

        # Clean normalized internal route
        norm_route = normalize_clean_route(full_url, base_clean)
        if not norm_route:
            continue

        # Check if it is the base homepage itself
        if norm_route == base_clean or norm_route == f"{base_clean}/":
            if parsed.fragment:
                frag_val = f"#{parsed.fragment}"
                if frag_val not in fragment_nav_links:
                    fragment_nav_links.append(frag_val)
            continue

        # Check if it is a standalone policy page
        if is_standalone_policy_page(norm_route):
            if norm_route not in standalone_policy_links:
                standalone_policy_links.append(norm_route)
            continue

        # Distinct content route
        if norm_route not in route_nav_links:
            route_nav_links.append(norm_route)

    # Reconcile crawled pages inventory
    crawled_doc_urls = set()
    if crawled_pages:
        for p in crawled_pages:
            u = p.get("final_url") or p.get("url")
            if u:
                norm_u = normalize_clean_route(u, base_clean)
                if norm_u:
                    crawled_doc_urls.add(norm_u)
                    if is_standalone_policy_page(norm_u) and norm_u not in standalone_policy_links:
                        standalone_policy_links.append(norm_u)

    # Distinct content pages (excluding homepage and standalone policies)
    non_policy_crawled_routes = [
        u for u in crawled_doc_urls
        if u != base_clean and u != f"{base_clean}/" and not is_standalone_policy_page(u)
    ]

    # Combine route nav links and non-policy crawled routes
    all_content_routes = list(dict.fromkeys(route_nav_links + non_policy_crawled_routes))

    # In-page sections extraction
    sections = extract_in_page_sections(soup, fragment_nav_links)

    # Metrics calculation
    num_frags = len(fragment_nav_links)
    num_routes = len(all_content_routes)
    total_nav_actions = num_frags + len(route_nav_links)
    fragment_ratio = round(num_frags / total_nav_actions, 2) if total_nav_actions > 0 else 0.0

    # Decision Matrix
    evidence: list[str] = []
    limitations: list[str] = [
        "Static DOM evaluation: Client-side single-page applications using History API (pushState) without static anchor elements or fragments require dynamic browser emulation to verify route state changes."
    ]

    if num_frags >= 2 and (num_routes == 0 or fragment_ratio >= 0.70):
        architecture = "single_page"
        confidence = "high" if not is_fallback_nav and num_frags >= 3 else "medium"
        evidence.append(
            f"Primary navigation targets {num_frags} in-page section fragment(s) ({', '.join(fragment_nav_links[:6])})."
        )
        if sections:
            evidence.append(f"{len(sections)} distinct in-page section(s) identified with headings and content.")
        if standalone_policy_links:
            evidence.append(
                f"{len(standalone_policy_links)} standalone policy document(s) retained ({', '.join(standalone_policy_links)}) without converting site to multi-page."
            )
        else:
            evidence.append("No separate standalone content routes detected.")
        summary = (
            f"Single-page architecture: primary navigation relies on {num_frags} in-page section fragments. "
            f"{len(sections)} sections audited; {len(standalone_policy_links) + 1} actual HTML document(s) retained."
        )

    elif num_frags >= 2 and num_routes >= 1:
        architecture = "hybrid"
        confidence = "high" if not is_fallback_nav else "medium"
        evidence.append(
            f"Meaningful in-page section anchors ({num_frags} fragments: {', '.join(fragment_nav_links[:4])}) "
            f"AND {num_routes} distinct content page(s) ({', '.join(all_content_routes[:4])}) both exist."
        )
        if sections:
            evidence.append(f"{len(sections)} in-page section(s) extracted for separate inspection.")
        if standalone_policy_links:
            evidence.append(f"{len(standalone_policy_links)} standalone policy document(s) retained.")
        summary = (
            f"Hybrid architecture: contains both {num_frags} in-page section fragments and {num_routes} distinct content routes."
        )

    elif num_routes >= 1 or len(crawled_doc_urls) > 1:
        architecture = "multi_page"
        confidence = "high" if not is_fallback_nav and len(route_nav_links) >= 2 else "medium"
        evidence.append(
            f"Navigation leads to {num_routes} distinct HTML content route(s) ({', '.join(all_content_routes[:6])})."
        )
        if num_frags > 0:
            evidence.append(f"Minor fragment links ({num_frags}) detected, but primary navigation is route-based.")
        summary = (
            f"Multi-page architecture: site navigation is structured across {num_routes} distinct content routes."
        )

    else:
        # Minimal site or single document without section links
        architecture = "single_page"
        confidence = "medium"
        evidence.append("Single HTML document detected with no distinct secondary routes.")
        summary = "Single-page architecture: single standalone document."

    total_distinct_docs = max(len(crawled_doc_urls), 1 + len(standalone_policy_links) + len(all_content_routes))

    return {
        "architecture": architecture,
        "confidence": confidence,
        "primary_navigation": {
            "total_nav_links": len(nav_links_raw),
            "fragment_nav_links": fragment_nav_links,
            "route_nav_links": route_nav_links,
            "external_nav_links": external_nav_links,
            "fragment_ratio": fragment_ratio,
        },
        "sections": sections,
        "section_count": len(sections),
        "distinct_content_pages": all_content_routes,
        "distinct_document_count": total_distinct_docs,
        "standalone_policy_pages": standalone_policy_links,
        "evidence": evidence,
        "limitations": limitations,
        "summary": summary,
    }
