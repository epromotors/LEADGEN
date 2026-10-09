# auditor/links.py — Broken link checker (parallel)

import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from auditor.core import result_pass, result_warn, result_fail, check_url_status, fetch_page, get_domain
from config import MAX_LINKS_TO_CHECK, LINK_CHECK_WORKERS, TIMEOUT


def get_nav_links(soup, base_url: str) -> list[str]:
    """Extract internal navigation links from common menu elements."""
    nav_elements = soup.find_all(["nav", "header"])
    if not nav_elements:
        nav_elements = soup.find_all(lambda tag: tag.name in ["div", "ul"] and (
            "nav" in tag.get("class", []) or "menu" in tag.get("class", []) or
            "nav" in tag.get("id", "").lower() or "menu" in tag.get("id", "").lower()
        ))
    
    domain = get_domain(base_url)
    nav_links = []
    seen = set()
    
    for el in nav_elements:
        for a in el.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:")):
                continue
            if not href:
                continue
                
            full = urllib.parse.urljoin(base_url, href).split("#")[0].rstrip("/")
            parsed = urllib.parse.urlparse(full)
            if parsed.scheme in ("http", "https"):
                # Only keep internal navigation links
                host = parsed.netloc.lstrip("www.")
                if host == domain or host == f"www.{domain}" or host == "":
                    if full not in seen:
                        seen.add(full)
                        nav_links.append(full)
    
    return nav_links


def collect_links(soup, base_url: str) -> list[str]:
    """Extract all href links from the page, resolve relative URLs."""
    links = []
    seen = set()
    
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        
        # Skip fragment-only, mailto, tel, javascript
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:")):
            continue
        if not href:
            continue
        
        # Resolve relative URLs
        full = urllib.parse.urljoin(base_url, href)
        
        # Only check http/https
        parsed = urllib.parse.urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        
        # Deduplicate
        clean = full.split("#")[0].rstrip("/")
        if clean not in seen:
            seen.add(clean)
            links.append(clean)
    
    return links


def audit_broken_links(soup, base_url: str, session: requests.Session) -> dict:
    """Check up to MAX_LINKS_TO_CHECK links for 4xx/5xx errors."""
    # 1. Start with links from the homepage
    all_links = collect_links(soup, base_url)
    seen_links = set(all_links)
    
    # 2. Discover navigation links to fetch (up to 5 pages)
    nav_urls = get_nav_links(soup, base_url)
    nav_urls = [u for u in nav_urls if u != base_url.rstrip("/")]
    sample_nav = nav_urls[:5]
    
    # 3. Fetch navigation pages to collect their links
    def fetch_nav(url):
        return fetch_page(url, session)
        
    if sample_nav:
        with ThreadPoolExecutor(max_workers=min(5, len(sample_nav))) as executor:
            futures = {executor.submit(fetch_nav, url): url for url in sample_nav}
            for future in as_completed(futures):
                try:
                    page = future.result()
                    if page["ok"] and page["soup"]:
                        page_links = collect_links(page["soup"], page["final_url"])
                        for link in page_links:
                            if link not in seen_links:
                                seen_links.add(link)
                                all_links.append(link)
                except Exception:
                    pass

    sample = all_links[:MAX_LINKS_TO_CHECK]
    
    if not sample:
        return result_warn(
            "No outbound/internal links found on the page to check.",
            "Ensure your homepage links to key internal pages.",
        )
    
    broken = []
    redirect_chains = []
    results_map = {}
    
    def check(url):
        try:
            r = session.head(url, timeout=TIMEOUT, allow_redirects=True, verify=False)
            return url, r.status_code, r.url
        except Exception:
            try:
                r = session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False, stream=True)
                return url, r.status_code, r.url
            except Exception:
                return url, None, url
    
    with ThreadPoolExecutor(max_workers=LINK_CHECK_WORKERS) as executor:
        futures = {executor.submit(check, url): url for url in sample}
        for future in as_completed(futures):
            url, status, final_url = future.result()
            results_map[url] = (status, final_url)
            if status is None or status >= 400:
                broken.append((url, status))
            elif final_url.rstrip('/') != url.rstrip('/'):
                redirect_chains.append((url, status, final_url))
    
    checked = len(sample)
    broken_count = len(broken)
    
    if broken_count == 0:
        detail = f"Checked {checked} links across homepage and nav pages. {len(redirect_chains)} redirects noted."
        if redirect_chains:
            detail += f" Redirects: {', '.join([r[0][:50] for r in redirect_chains[:2]])}"
        return result_pass(f"No broken links found in {checked} links checked.", detail=detail, value=0, unit="links")
    
    broken_list = [f"{url[:60]} (HTTP {status or 'Timeout'})" for url, status in broken[:5]]
    
    if broken_count >= 3:
        return result_fail(
            f"{broken_count} broken links found out of {checked} checked.",
            "Fix or remove broken links. Broken links hurt user experience and crawl budget. "
            "Use Screaming Frog or Ahrefs to do a full site broken link audit. "
            "WordPress: install Broken Link Checker plugin.",
            "\n".join(broken_list), value=broken_count, unit="links",
        )
    return result_warn(
        f"{broken_count} broken link(s) found out of {checked} checked.",
        "Fix or redirect the broken URLs. Even a few broken links signal poor maintenance to Google.",
        "\n".join(broken_list), value=broken_count, unit="links",
    )
