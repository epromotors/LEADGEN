# tests/test_audit_correctness_url_sitemap_schema.py
# Deterministic offline unit and regression tests for:
#   1. URL Identity (requested vs final vs canonical, deterministic normalization, no subpath promotion)
#   2. Robots.txt and Sitemap Discovery (origin-based location, directives, HTML rejection, limits)
#   3. Schema Consistency (AutoRepair, array @type, nested @graph, visible vs structured NAP)
#   4. PDF Report Evidence (requested URL in header/cover, redirect & canonical notes)

import os
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
import pytest

_AUDITOR_PATH = Path(__file__).resolve().parents[1] / "auditor" / "auditor"
if str(_AUDITOR_PATH) not in sys.path:
    sys.path.insert(0, str(_AUDITOR_PATH))

from auditor.core import (
    normalize_url,
    get_origin,
    get_domain,
    fetch_page,
    make_session,
    result_pass,
    result_warn,
    result_fail,
)
from auditor.schema_utils import (
    extract_json_ld_items,
    get_item_types,
    is_local_business_item,
    check_local_business_fields,
    LOCAL_BUSINESS_TYPES,
)
from auditor.onpage import audit_schema
from auditor.local_seo import audit_local_business_schema
from auditor.ux import audit_address_presence, audit_phone_number
from auditor.technical import audit_robots, audit_sitemap
from auditor.crawler import discover_via_sitemap, _parse_sitemap_xml
from reporter.pdf_report import build_pdf
from app.utils.site_checker import _url_variants, resolve_live_url


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: URL IDENTITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestURLIdentity:
    def test_normalize_url_deterministic(self):
        """Verify scheme, host lowercasing, trailing slash, query and fragment normalization."""
        # Bare domain added https
        assert normalize_url("carmedicmotors.in") == "https://carmedicmotors.in"
        # Uppercase domain and scheme lowercased
        assert normalize_url("HTTPS://CarMedicMotors.IN/") == "https://carmedicmotors.in"
        # Subpath trailing slash stripped deterministically
        assert normalize_url("https://carmedicmotors.in/lucknow/") == "https://carmedicmotors.in/lucknow"
        # Query parameters preserved
        assert normalize_url("https://carmedicmotors.in/search?q=repair") == "https://carmedicmotors.in/search?q=repair"
        # Fragment stripped
        assert normalize_url("https://carmedicmotors.in/about#team") == "https://carmedicmotors.in/about"

    def test_get_origin(self):
        """Verify site origin is extracted from any page URL or subpath."""
        assert get_origin("https://carmedicmotors.in/lucknow") == "https://carmedicmotors.in"
        assert get_origin("http://example.com:8080/path/to/page") == "http://example.com:8080"
        assert get_origin("https://www.carmedicmotors.in/") == "https://www.carmedicmotors.in"

    def test_site_checker_url_variants_prioritizes_requested_bare_domain(self):
        """When input is a bare domain, the bare domain must be variant #0, not www."""
        variants = _url_variants("https://carmedicmotors.in/")
        assert variants[0] == "https://carmedicmotors.in/"
        assert variants[1] == "https://www.carmedicmotors.in/"

    def test_site_checker_url_variants_prioritizes_requested_www(self):
        """When input has www, the www variant must be variant #0."""
        variants = _url_variants("https://www.carmedicmotors.in/")
        assert variants[0] == "https://www.carmedicmotors.in/"
        assert variants[1] == "https://carmedicmotors.in/"

    def test_resolve_live_url_does_not_mutate_root_url_to_subpath(self):
        """A root URL must never be replaced by a subpath redirect like /lucknow."""
        import asyncio
        with patch("app.utils.site_checker.aiohttp.ClientSession.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status = 200
            # Simulating server redirecting to /lucknow
            mock_resp.url = "https://carmedicmotors.in/lucknow"
            mock_get.return_value.__aenter__.return_value = mock_resp

            resolved = asyncio.run(resolve_live_url("https://carmedicmotors.in/"))
            # Resolved target must remain the origin / root URL, not the subpath
            assert resolved == "https://carmedicmotors.in"

    def test_requested_url_stays_associated_when_canonical_points_to_subpath(self):
        """
        Lead configured with root URL stays associated with that requested URL,
        while a canonical tag pointing to /lucknow is recorded as canonical metadata only.
        """
        html = """<!doctype html>
        <html>
        <head>
            <title>Car Medic Motors - Car Repair in Lucknow</title>
            <link rel="canonical" href="https://carmedicmotors.in/lucknow" />
        </head>
        <body>
            <h1>Car Medic Motors</h1>
            <p>Welcome to our Lucknow service center.</p>
        </body>
        </html>"""

        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://carmedicmotors.in/"
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content = MagicMock(return_value=[html.encode("utf-8")])
        session.get.return_value.__enter__.return_value = mock_resp

        page = fetch_page("https://carmedicmotors.in/", session)
        assert page["ok"] is True
        assert page["url"] == "https://carmedicmotors.in/"
        assert page["final_url"] == "https://carmedicmotors.in/"
        assert page["is_redirected"] is False
        assert page["redirect_url"] is None

        # Canonical tag in HTML
        canonical_tag = page["soup"].find("link", rel=lambda x: x and "canonical" in x)
        assert canonical_tag is not None
        canonical_url = canonical_tag.get("href")
        assert canonical_url == "https://carmedicmotors.in/lucknow"

        # Requested URL remains root URL
        assert normalize_url(page["url"]) == "https://carmedicmotors.in"

    def test_real_redirect_response_recorded_accurately(self):
        """
        If the server genuinely redirects the requested root URL, record that redirect
        and report both requested and final URLs accurately.
        """
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://carmedicmotors.in/lucknow"  # Final destination after 301
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content = MagicMock(return_value=[b"<html><body>Redirected</body></html>"])
        session.get.return_value.__enter__.return_value = mock_resp

        page = fetch_page("https://carmedicmotors.in/", session)
        assert page["ok"] is True
        assert page["url"] == "https://carmedicmotors.in/"
        assert page["final_url"] == "https://carmedicmotors.in/lucknow"
        assert page["is_redirected"] is True
        assert page["redirect_url"] == "https://carmedicmotors.in/lucknow"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: ROBOTS.TXT AND SITEMAP DISCOVERY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestRobotsAndSitemapDiscovery:
    def test_subpath_lead_url_probes_robots_and_sitemap_at_domain_root(self):
        """
        Even when given a lead URL with subpath (e.g. /lucknow), robots.txt and sitemap
        must be probed at the site origin (domain root), NEVER at /lucknow/robots.txt.
        """
        session = MagicMock()
        requested_urls = []

        def mock_get(url, **kwargs):
            requested_urls.append(url)
            resp = MagicMock()
            if url.endswith("/robots.txt"):
                resp.status_code = 200
                resp.headers = {"Content-Type": "text/plain"}
                resp.iter_content = MagicMock(return_value=[b"User-agent: *\nAllow: /\nSitemap: https://carmedicmotors.in/sitemap.xml\n"])
                return resp
            elif url.endswith("/sitemap.xml"):
                resp.status_code = 200
                resp.headers = {"Content-Type": "application/xml"}
                resp.iter_content = MagicMock(return_value=[b'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://carmedicmotors.in/</loc></url></urlset>'])
                return resp
            resp.status_code = 404
            resp.headers = {}
            resp.iter_content = MagicMock(return_value=[b""])
            return resp

        session.get.side_effect = lambda u, **kw: MagicMock(__enter__=lambda self: mock_get(u, **kw), __exit__=lambda *args: None)

        # 1. Audit robots with subpath base_url
        res_robots = audit_robots("https://carmedicmotors.in/lucknow", session)
        assert res_robots["status"] == "PASS"
        # Must have probed root robots.txt
        assert "https://carmedicmotors.in/robots.txt" in requested_urls
        assert "https://carmedicmotors.in/lucknow/robots.txt" not in requested_urls

        # 2. Audit sitemap with subpath base_url
        requested_urls.clear()
        res_sitemap = audit_sitemap("https://carmedicmotors.in/lucknow", session)
        assert res_sitemap["status"] == "PASS"
        assert "https://carmedicmotors.in/sitemap.xml" in requested_urls
        assert "https://carmedicmotors.in/lucknow/sitemap.xml" not in requested_urls

    def test_sitemap_directive_in_root_robots_txt_resolved(self):
        """Valid Sitemap: directive in robots.txt (relative or absolute) resolved against origin."""
        session = MagicMock()
        robots_body = b"User-agent: *\nDisallow: /admin\nSitemap: /sitemap_relative.xml\n"
        sitemap_body = b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://carmedicmotors.in/</loc></url></urlset>'

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if url == "https://carmedicmotors.in/robots.txt":
                resp.status_code = 200
                resp.headers = {"Content-Type": "text/plain"}
                resp.iter_content = MagicMock(return_value=[robots_body])
            elif url == "https://carmedicmotors.in/sitemap_relative.xml":
                resp.status_code = 200
                resp.headers = {"Content-Type": "application/xml"}
                resp.iter_content = MagicMock(return_value=[sitemap_body])
            else:
                resp.status_code = 404
                resp.headers = {}
                resp.iter_content = MagicMock(return_value=[b""])
            return resp

        session.get.side_effect = lambda u, **kw: MagicMock(__enter__=lambda self: mock_get(u, **kw), __exit__=lambda *args: None)

        res = audit_sitemap("https://carmedicmotors.in/lucknow", session)
        assert res["status"] == "PASS"
        assert "sitemap_relative.xml" in res["message"]
        assert "declared in robots.txt" in res["message"]

    def test_sitemap_index_with_child_sitemaps(self):
        """Sitemap index returns child sitemaps count."""
        session = MagicMock()
        index_body = b'''<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://carmedicmotors.in/post-sitemap.xml</loc></sitemap>
            <sitemap><loc>https://carmedicmotors.in/page-sitemap.xml</loc></sitemap>
        </sitemapindex>'''

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if url.endswith("/sitemap_index.xml"):
                resp.status_code = 200
                resp.headers = {"Content-Type": "application/xml"}
                resp.iter_content = MagicMock(return_value=[index_body])
            else:
                resp.status_code = 404
                resp.headers = {}
                resp.iter_content = MagicMock(return_value=[b""])
            return resp

        session.get.side_effect = lambda u, **kw: MagicMock(__enter__=lambda self: mock_get(u, **kw), __exit__=lambda *args: None)

        res = audit_sitemap("https://carmedicmotors.in", session)
        assert res["status"] == "PASS"
        assert "2 child sitemaps" in res["message"]

    def test_http_200_html_response_rejected_as_sitemap(self):
        """An HTTP 200 HTML page (e.g. custom 404 or SPA catch-all) is rejected as an XML sitemap."""
        session = MagicMock()
        html_page = b'''<!DOCTYPE html>
        <html><head><title>404 Not Found</title></head><body>Page not found</body></html>'''

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "text/html; charset=UTF-8"}
            resp.iter_content = MagicMock(return_value=[html_page])
            return resp

        session.get.side_effect = lambda u, **kw: MagicMock(__enter__=lambda self: mock_get(u, **kw), __exit__=lambda *args: None)

        res = audit_sitemap("https://carmedicmotors.in", session)
        assert res["status"] == "FAIL"
        assert "No sitemap found" in res["message"]
        # Ensure probes show rejection reason
        ev = res["evidence"][0]
        assert any("returned HTML document" in p["reason"] for p in ev["probes"])

    def test_http_200_html_response_rejected_as_robots(self):
        """An HTTP 200 HTML page is rejected as robots.txt."""
        session = MagicMock()
        html_page = b'''<!DOCTYPE html>
        <html><head><title>Error</title></head><body>Cannot find robots.txt</body></html>'''

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.iter_content = MagicMock(return_value=[html_page])
        session.get.return_value.__enter__.return_value = mock_resp

        res = audit_robots("https://carmedicmotors.in", session)
        assert res["status"] == "WARN"
        assert "returned an HTML document" in res["message"]

    def test_timeout_and_malformed_xml_and_unavailable(self):
        """Timeout, malformed XML, and 404 handled gracefully without raising unhandled exceptions."""
        session = MagicMock()
        malformed_xml = b'<?xml version="1.0"?><urlset><url><loc>https://example.com'  # unclosed

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if url.endswith("/sitemap_index.xml"):
                resp.status_code = 200
                resp.headers = {"Content-Type": "application/xml"}
                resp.iter_content = MagicMock(return_value=[malformed_xml])
            else:
                resp.status_code = 404
                resp.headers = {}
                resp.iter_content = MagicMock(return_value=[b""])
            return resp

        session.get.side_effect = lambda u, **kw: MagicMock(__enter__=lambda self: mock_get(u, **kw), __exit__=lambda *args: None)

        res = audit_sitemap("https://carmedicmotors.in", session)
        assert res["status"] == "FAIL"
        ev = res["evidence"][0]
        assert any("malformed XML" in p["reason"] for p in ev["probes"])


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: SCHEMA FINDINGS CONSISTENCY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemaConsistency:
    def test_carmedicmotors_autorepair_schema_both_pass_consistently(self):
        """
        Exact regression test for the Car Medic Motors finding:
        Generic schema check reports LocalBusiness JSON-LD present, and
        dedicated LocalBusiness check must ALSO recognize AutoRepair and PASS.
        """
        html = """<!doctype html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "AutoRepair",
                        "name": "Car Medic Motors",
                        "telephone": "+91 98765 43210",
                        "url": "https://carmedicmotors.in",
                        "address": {
                            "@type": "PostalAddress",
                            "streetAddress": "Plot 12, Vibhuti Khand",
                            "addressLocality": "Lucknow",
                            "postalCode": "226010",
                            "addressCountry": "IN"
                        }
                    }
                ]
            }
            </script>
        </head>
        <body>
            <address>Plot 12, Vibhuti Khand, Lucknow</address>
            <a href="tel:+919876543210">+91 98765 43210</a>
        </body>
        </html>"""

        soup = BeautifulSoup(html, "lxml")

        # 1. Generic schema check
        res_generic = audit_schema(soup)
        assert res_generic["status"] == "PASS"
        assert "AutoRepair" in res_generic["message"]

        # 2. Dedicated LocalBusiness schema check
        res_local = audit_local_business_schema(soup)
        assert res_local["status"] == "PASS"
        assert "AutoRepair" in res_local["message"]
        # Both must pass without contradiction!

    def test_type_as_array_autorepair_localbusiness(self):
        """Handles @type as an array e.g. ['LocalBusiness', 'AutoRepair']."""
        html = """<!doctype html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": ["LocalBusiness", "AutoRepair"],
                "name": "Car Medic Motors",
                "telephone": "123-456-7890",
                "address": "123 Main St, City"
            }
            </script>
        </head>
        <body>
            <footer>123 Main St, City | Phone: 123-456-7890</footer>
        </body>
        </html>"""

        soup = BeautifulSoup(html, "lxml")
        res_generic = audit_schema(soup)
        res_local = audit_local_business_schema(soup)

        assert res_generic["status"] == "PASS"
        assert res_local["status"] == "PASS"

    def test_address_phone_visible_vs_json_ld_distinction(self):
        """
        Visible on page is reported separately from structured data:
        If address is in JSON-LD but not in visible HTML, audit_address_presence notes it.
        """
        html = """<!doctype html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "LocalBusiness",
                "name": "Ghost Shop",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "Hidden Alley 5",
                    "addressLocality": "Nowhere"
                }
            }
            </script>
        </head>
        <body>
            <h1>Welcome</h1>
            <!-- No address in body -->
        </body>
        </html>"""

        soup = BeautifulSoup(html, "lxml")
        res_addr = audit_address_presence(soup)
        # Should detect address in JSON-LD but warn that it's not visible
        assert res_addr["status"] == "WARN"
        assert "structured data" in res_addr["message"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: PDF REPORT EVIDENCE INTEGRITY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestPDFReportEvidence:
    def test_build_pdf_with_requested_and_redirect_and_canonical_urls(self):
        """
        PDF generation accepts url_info with requested_url, final_url, and canonical_url,
        generating a valid document displaying the requested audit target in the header and cover.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = os.path.join(tmpdir, "test_audit.pdf")
            results = {
                "technical": {
                    "ssl": result_pass("SSL valid"),
                    "robots": result_pass("robots.txt found at domain root"),
                    "sitemap": result_pass("sitemap.xml found at domain root"),
                },
                "onpage": {
                    "schema": result_pass("JSON-LD AutoRepair found"),
                },
                "local_seo": {
                    "local_business_schema": result_pass("LocalBusiness (AutoRepair) schema valid"),
                },
            }
            url_info = {
                "requested_url": "https://carmedicmotors.in/",
                "final_url": "https://carmedicmotors.in/lucknow",
                "canonical_url": "https://carmedicmotors.in/lucknow",
                "is_redirected": True,
                "redirect_url": "https://carmedicmotors.in/lucknow",
            }
            pdf_path = build_pdf(
                url="https://carmedicmotors.in/",
                audit_results=results,
                score=88,
                output_path=out_pdf,
                site_summary={"total_pages": 1, "url_info": url_info},
                url_info=url_info,
            )

            assert os.path.exists(pdf_path)
            assert os.path.getsize(pdf_path) > 1000
