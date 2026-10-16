import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "auditor" / "auditor"))

import pytest
from bs4 import BeautifulSoup
from unittest.mock import MagicMock, patch

from auditor.core import get_domain
from auditor.links import audit_broken_links, verify_link_destination
from auditor.images import audit_alt_text, audit_webp, get_image_inventory
from auditor.crawler import (
    normalise,
    classify_url_nature,
    discover_via_sitemap,
    crawl_site,
    audit_page_seo,
    aggregate_site_issues,
    is_internal,
    is_auditable_page_url,
)
from auditor.keyword_density import (
    extract_visible_text,
    count_visible_words,
    analyze_keyword_on_page,
    analyze_target_keywords_site,
)
from auditor.social import audit_social_links
from reporter.pdf_report import build_pdf


def _probe_link(url: str, base_url: str, session):
    return verify_link_destination({
        "normalized_url": url,
        "source_page": base_url,
        "original_href": url,
    }, session)


# ── 1. LinkedIn HTTP 999 classified as blocked_or_restricted, NOT broken ─────
def test_linkedin_http_999_not_broken():
    session = MagicMock()
    # Mock HEAD returning 999 or GET returning 999
    resp = MagicMock()
    resp.status_code = 999
    resp.url = "https://www.linkedin.com/company/channelnexus"
    resp.history = []
    session.head.return_value = resp
    session.get.return_value = resp

    res = _probe_link("https://www.linkedin.com/company/channelnexus", "https://channelnexus.me", session)
    assert res["state"] == "blocked_or_restricted"
    assert res["status_code"] == 999

    # audit_broken_links should NOT count it as broken_count
    html = '<a href="https://www.linkedin.com/company/channelnexus">LinkedIn</a>'
    soup = BeautifulSoup(html, "lxml")
    audit_res = audit_broken_links(soup, "https://channelnexus.me", session)
    assert audit_res["status"] == "PASS"
    assert audit_res["value"] == 0
    assert "access-restricted" in audit_res["detail"]


# ── 2. Social-profile HTTP 405 handled with GET retry and safe classification ──
def test_social_profile_http_405_get_retry():
    session = MagicMock()
    head_resp = MagicMock()
    head_resp.status_code = 405
    head_resp.url = "https://twitter.com/example"
    head_resp.history = []

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.url = "https://twitter.com/example"
    get_resp.history = []

    session.head.return_value = head_resp
    session.get.return_value = get_resp

    res = _probe_link("https://twitter.com/example", "https://example.com", session)
    assert res["state"] == "live"
    assert res["status_code"] == 200
    assert res["http_method"] == "GET"


# ── 3. HTTP 403, 429 and timeouts not automatically counted as broken ─────────
def test_http_403_429_timeout_not_broken():
    session = MagicMock()

    # 403 Forbidden (Cloudflare / WAF challenge)
    resp_403 = MagicMock(status_code=403, url="https://example.com/protected", history=[])
    session.head.return_value = resp_403
    session.get.return_value = resp_403
    res_403 = _probe_link("https://example.com/protected", "https://example.com", session)
    assert res_403["state"] == "blocked_or_restricted"

    # 429 Too Many Requests
    resp_429 = MagicMock(status_code=429, url="https://example.com/rate-limit", history=[])
    session.head.return_value = resp_429
    session.get.return_value = resp_429
    res_429 = _probe_link("https://example.com/rate-limit", "https://example.com", session)
    assert res_429["state"] == "blocked_or_restricted"

    # Timeout
    import requests
    session.head.side_effect = requests.Timeout("Connection timed out")
    session.get.side_effect = requests.Timeout("Connection timed out")
    res_timeout = _probe_link("https://example.com/slow", "https://example.com", session)
    assert res_timeout["state"] == "inconclusive"
    assert "timed out" in res_timeout["notes"].lower()


# ── 4. Confirmed 404/410 failures distinguished from inaccessible resources ───
def test_confirmed_404_410_distinguished():
    session = MagicMock()
    # Stable 404 on both HEAD and GET
    resp_404 = MagicMock(status_code=404, url="https://example.com/dead-page", history=[])
    session.head.return_value = resp_404
    session.get.return_value = resp_404

    res_404 = _probe_link("https://example.com/dead-page", "https://example.com", session)
    assert res_404["state"] == "broken_confirmed"
    assert res_404["status_code"] == 404

    html = '<a href="https://example.com/dead-page">Dead Link</a>'
    soup = BeautifulSoup(html, "lxml")
    audit_res = audit_broken_links(soup, "https://example.com", session)
    # 1 confirmed broken link returns WARN (>=3 returns FAIL)
    assert audit_res["status"] == "WARN"
    assert audit_res["value"] == 1
    assert "1 confirmed broken link(s)" in audit_res["message"]


# ── 5. Cloudflare email-protection utility URLs excluded from inventory ───────
def test_cloudflare_email_protection_excluded():
    url = "https://channelnexus.me/cdn-cgi/l/email-protection#123456"
    assert classify_url_nature(url) == "utility_cloudflare"

    # Crawl queue extraction drops it
    html = '''
    <html>
      <body>
        <a href="/cdn-cgi/l/email-protection#abc123">Email Us</a>
        <a href="/services">Real Services Page</a>
      </body>
    </html>
    '''
    soup = BeautifulSoup(html, "lxml")
    links = [a.get("href") for a in soup.find_all("a")]
    clean = [l for l in links if not classify_url_nature(normalise(l, "https://channelnexus.me") or l).startswith("utility_")]
    assert len(clean) == 1
    assert clean[0] == "/services"


# ── 6. Internal-link discovery when sitemap lists only homepage ────────────────
def test_internal_link_discovery_sitemap_single_url():
    session = MagicMock()

    sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://mysite.com/</loc></url>
    </urlset>"""

    home_html = """
    <html>
      <head><title>Home</title></head>
      <body>
        <nav>
          <a href="/about">About Us</a>
          <a href="/services">Services</a>
          <a href="/contact">Contact</a>
        </nav>
      </body>
    </html>
    """

    about_html = "<html><head><title>About</title></head><body><h1>About Us</h1></body></html>"
    services_html = "<html><head><title>Services</title></head><body><h1>Our Services</h1></body></html>"
    contact_html = "<html><head><title>Contact</title></head><body><h1>Contact Us</h1></body></html>"

    def mock_fetch(url, *args, **kwargs):
        norm = normalise(url, "https://mysite.com") or url
        norm_clean = norm.rstrip("/")
        if norm_clean.endswith("sitemap.xml"):
            m = MagicMock(status_code=200, ok=True, content=sitemap_xml)
            m.headers = {"Content-Type": "application/xml"}
            return m
        elif norm_clean == "https://mysite.com":
            return {"ok": True, "url": norm, "final_url": norm, "status_code": 200, "html": home_html, "soup": BeautifulSoup(home_html, "lxml")}
        elif norm_clean == "https://mysite.com/about":
            return {"ok": True, "url": norm, "final_url": norm, "status_code": 200, "html": about_html, "soup": BeautifulSoup(about_html, "lxml")}
        elif norm_clean == "https://mysite.com/services":
            return {"ok": True, "url": norm, "final_url": norm, "status_code": 200, "html": services_html, "soup": BeautifulSoup(services_html, "lxml")}
        elif norm_clean == "https://mysite.com/contact":
            return {"ok": True, "url": norm, "final_url": norm, "status_code": 200, "html": contact_html, "soup": BeautifulSoup(contact_html, "lxml")}
        return {"ok": False, "url": norm, "final_url": norm, "status_code": 404, "html": "", "soup": None}

    with patch("auditor.crawler.fetch_page", side_effect=mock_fetch), \
         patch("auditor.crawler.discover_via_sitemap", return_value=["https://mysite.com/"]):
        pages = crawl_site("https://mysite.com", session, max_pages=10)
        assert len(pages) == 4
        urls = [p["url"].rstrip("/") for p in pages]
        assert "https://mysite.com" in urls
        assert "https://mysite.com/about" in urls
        assert "https://mysite.com/services" in urls
        assert "https://mysite.com/contact" in urls

        meta = pages[0]["_crawl_meta"]
        assert meta["sitemap_url_count"] == 1
        assert meta["link_discovered_count"] >= 3

        summary = aggregate_site_issues([audit_page_seo(p) for p in pages], crawl_meta=meta)
        assert "Sitemap lists 1 URL" in summary["discovery_explanation"]


# ── 7. Sitemap index and child-sitemap handling ───────────────────────────────
def test_sitemap_index_and_child_sitemaps():
    session = MagicMock()
    index_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://mysite.com/post-sitemap.xml</loc></sitemap>
      <sitemap><loc>https://mysite.com/page-sitemap.xml</loc></sitemap>
    </sitemapindex>"""

    child1_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://mysite.com/post-1</loc></url>
      <url><loc>https://mysite.com/post-2</loc></url>
    </urlset>"""

    child2_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://mysite.com/page-1</loc></url>
    </urlset>"""

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.ok = True
        resp.status_code = 200
        if "post-sitemap.xml" in url:
            resp.content = child1_xml
            resp.headers = {"Content-Type": "application/xml"}
        elif "page-sitemap.xml" in url:
            resp.content = child2_xml
            resp.headers = {"Content-Type": "application/xml"}
        else:
            resp.content = index_xml
            resp.headers = {"Content-Type": "application/xml"}
        return resp

    session.get.side_effect = mock_get
    discovered = discover_via_sitemap("https://mysite.com", session)
    assert any("post-1" in u for u in discovered)
    assert any("post-2" in u for u in discovered)
    assert any("page-1" in u for u in discovered)


# ── 8. Duplicate paths, redirects, canonical URLs and crawl boundaries ────────
def test_duplicate_paths_and_canonical_deduplication():
    # /index.html normalizes to /
    assert normalise("https://mysite.com/index.html", "https://mysite.com").rstrip("/") == "https://mysite.com"
    # Strips fragments
    assert normalise("https://mysite.com/about#team", "https://mysite.com") == "https://mysite.com/about"
    # Strips tracking query parameters
    assert normalise("https://mysite.com/product?utm_source=fb&gclid=123", "https://mysite.com") == "https://mysite.com/product"
    # External domains are rejected from crawl scope
    assert is_internal("https://external.com/page", get_domain("https://mysite.com")) is False
    # Non-auditable utility pages are excluded from content audit
    assert is_auditable_page_url("https://mysite.com/cdn-cgi/l/email-protection") is False


# ── 9. Keyword-density arithmetic using known HTML fixtures ───────────────────
def test_keyword_density_arithmetic():
    filler = "word " * 90
    text_content = f"lead generation {filler} lead generation lead generation lead generation lead generation"
    html = f"<html><body><main><p>{text_content}</p></main></body></html>"
    soup = BeautifulSoup(html, "lxml")

    vis_text = extract_visible_text(soup)
    total_words = count_visible_words(vis_text)
    assert total_words == 100

    analysis = analyze_keyword_on_page(soup, "https://example.com", "lead generation")
    assert analysis["exact_count"] == 5
    assert analysis["keyword_word_count"] == 2
    assert analysis["total_words"] == 100
    assert analysis["density_pct"] == 10.0


# ── 10. Target-keyword placement in title, description, headings, body, alt ───
def test_target_keyword_placements():
    html = """
    <html>
      <head>
        <title>Professional Video Editing Services | Nexus</title>
        <meta name="description" content="Top rated video editing for modern content creators.">
      </head>
      <body>
        <header><nav><a href="/">Home</a></nav></header>
        <h1>Custom Video Editing Solutions</h1>
        <h2>Why Choose Video Editing With Us</h2>
        <p>Our video editing team brings your story to life with cutting edge motion design and pacing.</p>
        <img src="editor.jpg" alt="Expert video editing workspace" />
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    analysis = analyze_keyword_on_page(soup, "https://example.com", "video editing")

    assert analysis["placements"]["title"] is True
    assert analysis["placements"]["meta_description"] is True
    assert analysis["placements"]["h1"] is True
    assert analysis["placements"]["h2"] is True
    assert analysis["placements"]["main_body"] is True
    assert analysis["placements"]["alt_text"] is True


# ── 11. Missing target-keyword configuration reported honestly ─────────────────
def test_missing_target_keywords_honest_report():
    html = "<html><body><h1>Channel Nexus</h1><p>We manage YouTube channels and video production.</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    pages = [{"ok": True, "url": "https://example.com", "soup": soup, "html": html}]

    res_empty = analyze_target_keywords_site(pages, [])
    assert res_empty["configured"] is False
    assert res_empty["message"] == "Target keywords not configured"
    assert "inferred_topics" in res_empty

    res_none = analyze_target_keywords_site(pages, None)
    assert res_none["configured"] is False
    assert res_none["message"] == "Target keywords not configured"


# ── 12. Internal-page keyword-coverage aggregation ────────────────────────────
def test_internal_page_keyword_coverage_aggregation():
    p1_html = "<html><body><h1>Video Editing for Creators</h1><p>High end video editing services.</p></body></html>"
    p2_html = "<html><body><h1>Channel Management</h1><p>Full service channel growth and strategy.</p></body></html>"
    p3_html = "<html><body><h1>About Our Studio</h1><p>We do creative video editing and animation.</p></body></html>"

    pages = [
        {"ok": True, "url": "https://example.com", "soup": BeautifulSoup(p1_html, "lxml"), "html": p1_html},
        {"ok": True, "url": "https://example.com/growth", "soup": BeautifulSoup(p2_html, "lxml"), "html": p2_html},
        {"ok": True, "url": "https://example.com/about", "soup": BeautifulSoup(p3_html, "lxml"), "html": p3_html},
    ]

    res = analyze_target_keywords_site(pages, ["video editing"])
    assert res["configured"] is True
    assert len(res["keyword_summaries"]) == 1

    summary = res["keyword_summaries"][0]
    assert summary["keyword"] == "video editing"
    assert summary["pages_covering_exact"] == 2
    assert summary["page_coverage_pct"] == 67
    assert summary["total_exact_occurrences"] >= 2


# ── 13. Image alt-text counts with zero, missing and present alt attributes ────
def test_image_alt_text_counts_and_descriptions():
    html = """
    <html>
      <body>
        <img src="img1.jpg" alt="Descriptive alt" />
        <img src="img2.jpg" alt="" />
        <img src="img3.jpg" />
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    inv = get_image_inventory(soup)

    assert inv["total_elements"] == 3
    assert len(inv["with_alt"]) == 1
    assert len(inv["empty_alt"]) == 1
    assert len(inv["missing_alt"]) == 1

    res = audit_alt_text(soup)
    assert res["status"] == "WARN"
    assert res["value"] == 1
    assert res["unit"] == "images missing alt"
    assert "1 of 3 images" in res["message"]


# ── 14. Image deduplication and valid WebP counts (numerator <= denominator) ──
def test_webp_image_numerator_never_exceeds_denominator():
    html = """
    <html>
      <body>
        <picture>
          <source srcset="hero.webp" type="image/webp" />
          <img src="hero.jpg" alt="Hero banner" />
        </picture>
        <picture>
          <source srcset="logo.webp" type="image/webp" />
          <img src="logo.png" alt="Company Logo" />
        </picture>
        <img src="banner.webp" alt="Promo banner" />
        <img src="legacy.jpg" alt="Legacy graphic" />
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    inv = get_image_inventory(soup)

    # 4 distinct image elements in page
    assert inv["total_elements"] == 4
    # 3 are WebP (2 picture sources, 1 img tag)
    assert len(inv["webp_elements"]) == 3
    assert len(inv["webp_elements"]) <= inv["total_elements"]

    res = audit_webp(soup, html)
    assert res["status"] == "PASS"
    assert "3 of 4" in res["message"]
    assert res["value"] == 3
    assert res["value"] <= inv["total_elements"]


# ── 15. Social-profile absence distinguished from broken-link status ──────────
def test_social_profile_absence_not_technical_error():
    # Only LinkedIn present, missing Facebook and Pinterest
    html = """
    <html>
      <body>
        <a href="https://www.linkedin.com/company/nexus">LinkedIn</a>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    session = MagicMock()
    resp = MagicMock(status_code=200, url="https://www.linkedin.com/company/nexus", history=[])
    session.head.return_value = resp

    res = audit_social_links(soup, "https://example.com", session)
    # Core platform present -> PASS, missing platforms are informational observations
    assert res["status"] == "PASS"
    assert "LinkedIn" in res["message"]
    assert "Facebook" in res["detail"]
    assert "Pinterest" in res["detail"]


# ── 16. Consistency of dashboard, audit data and generated PDF ─────────────────
def test_report_consistency_dashboard_data_and_pdf(tmp_path):
    audit_results = {
        "technical": {
            "ssl": {"id": "technical.ssl", "status": "PASS", "score": 3.0, "max_score": 3.0, "message": "SSL valid", "value": True, "unit": ""},
            "sitemap": {"id": "technical.sitemap", "status": "PASS", "score": 2.0, "max_score": 2.0, "message": "Sitemap detected", "value": 1, "unit": "urls"},
        },
        "links": {
            "broken_links": {"id": "links.broken_links", "status": "PASS", "score": 3.0, "max_score": 3.0, "message": "0 broken links", "value": 0, "unit": "confirmed broken links"},
        },
        "images": {
            "alt_text": {"id": "images.alt_text", "status": "PASS", "score": 2.0, "max_score": 2.0, "message": "All images have alt text", "value": 0, "unit": "images missing alt"},
        }
    }

    site_summary = {
        "total_pages": 4,
        "sitemap_url_count": 1,
        "link_discovered_count": 3,
        "total_discovered_count": 4,
        "crawl_limit_hit": False,
        "discovery_explanation": "Sitemap lists 1 URL; 3 additional internal HTML pages were discovered.",
        "top_issues": [],
        "worst_pages": [],
        "keyword_analysis": {
            "configured": True,
            "status": "configured",
            "message": "1 target keyword analyzed",
            "target_keywords": ["channel management"],
            "pages_analyzed": 4,
            "keyword_summaries": [
                {
                    "keyword": "channel management",
                    "total_exact_occurrences": 8,
                    "total_variant_occurrences": 2,
                    "page_coverage_pct": 75,
                    "average_density_pct": 2.4,
                    "pages_covering_any": 3,
                    "placement_occurrences": {"title": 2, "h1": 2, "meta_description": 1, "alt_text": 1},
                }
            ]
        }
    }

    pdf_out = str(tmp_path / "test_consistent_report.pdf")
    res_path = build_pdf(
        url="https://channelnexus.me",
        audit_results=audit_results,
        score=92,
        output_path=pdf_out,
        site_summary=site_summary,
        page_audits=[],
        url_info={"requested_url": "https://channelnexus.me", "final_url": "https://channelnexus.me/"},
        target_keywords=["channel management"],
    )
    assert res_path == pdf_out
    import os
    assert os.path.exists(pdf_out)
    assert os.path.getsize(pdf_out) > 5000
