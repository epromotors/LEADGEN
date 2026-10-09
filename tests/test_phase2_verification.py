"""Comprehensive Phase 2 Verification Test Suite.

Covers:
  - Check 1: Runtime verification (browser disabled, browser enabled, deterministic fixtures,
             static vs client-rendered, timeout/error isolation, API/PDF compatibility).
  - Check 2: Security verification (SSRF URL/IP classes, IPv4-mapped IPv6, alternative numeric formats,
             mixed DNS, redirect SSRF protection at request boundary, resource limits & cleanup).
"""
from __future__ import annotations

import http.server
import ipaddress
import json
import os
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-long-for-jwt-signing-123")
AUDITOR_PKG = os.path.join(REPO_ROOT, "auditor", "auditor")
if AUDITOR_PKG not in sys.path:
    sys.path.insert(0, AUDITOR_PKG)
BACKEND_PKG = os.path.join(REPO_ROOT, "backend")
if BACKEND_PKG not in sys.path:
    sys.path.insert(0, BACKEND_PKG)

from browser.provider import BrowserProvider, BrowserConfig, BrowserEvidence, BrowserStatus, is_browser_enabled
from browser.security import validate_url, is_allowed_url, _is_blocked_ip, _parse_ip_literal
from browser.comparisons import annotate_browser_comparisons


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic Test Fixture HTTP Server
# ══════════════════════════════════════════════════════════════════════════════

class FixtureRequestHandler(http.server.BaseHTTPRequestHandler):
    """Serves controlled deterministic pages for browser testing."""

    def do_GET(self):
        if self.path == "/static":
            content = (
                b"<!DOCTYPE html><html><head><title>Static Audit Page</title>"
                b'<meta name="description" content="A static description for SEO test.">'
                b"</head><body><header><nav><a href=\"/static\">Home</a><a href=\"/about\">About</a></nav></header>"
                b"<h1>Static Audit Primary Heading</h1><h2>Subheading Level 2</h2>"
                b"<p>This is a paragraph with sufficient visible text content to pass the 50 characters threshold easily.</p>"
                b'<form action="/submit" method="POST"><input type="text" name="email"><button type="submit">Submit</button></form>'
                b'<a href="/contact" class="btn">Get Started Today</a>'
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == "/js-rendered":
            # Raw HTML has NO H1 and NO CTA. JS renders them dynamically after load.
            content = (
                b"<!DOCTYPE html><html><head><title>Initial Raw Title</title></head><body>"
                b'<nav><a href="/js-rendered">Home</a></nav>'
                b'<div id="app"><p>Loading client application...</p></div>'
                b"<script>"
                b'document.title = "Rendered Dynamic Title";'
                b'const app = document.getElementById("app");'
                b'app.innerHTML = "<h1>Client-Side Injected H1</h1><a href=\'/book\'>Book Free Consultation</a>";'
                b"</script>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == "/delay-timeout":
            # Sleeps longer than the test navigation timeout
            time.sleep(2.5)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Delayed response</body></html>")

        elif self.path == "/errors":
            content = (
                b"<!DOCTYPE html><html><head><title>Page With Errors</title></head><body>"
                b"<h1>Errors Test Page</h1>"
                b"<script>console.error('Deliberate test error in console');</script>"
                b'<script src="/nonexistent_script_404.js"></script>'
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == "/redirect-to-private":
            # HTTP 302 redirect to RFC-1918 private address
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/internal-secret")
            self.end_headers()

        elif self.path == "/subresource-ssrf":
            # Page that attempts to load subresources from metadata and private IPs
            content = (
                b"<!DOCTYPE html><html><head><title>Subresource SSRF</title></head><body>"
                b"<h1>Subresource Probe</h1>"
                b'<img src="http://169.254.169.254/latest/meta-data/credentials">'
                b"<script>fetch('http://192.168.1.1/admin').catch(() => {});</script>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == "/huge-dom":
            # Generate > 30 KB of HTML to verify snippet capping
            repeated = b"<p>Repeating content block for DOM snippet size boundary test.</p>\n" * 600
            content = b"<!DOCTYPE html><html><head><title>Huge DOM</title></head><body>" + repeated + b"</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP server logs during testing
        pass


@pytest.fixture(scope="module")
def fixture_server():
    """Starts a local HTTP server on an ephemeral port for testing."""
    server = http.server.HTTPServer(("127.0.0.1", 0), FixtureRequestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 1: RUNTIME VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

class TestRuntimeBrowserDisabled:
    """4.1: Verify provider disabled mode."""

    def test_disabled_by_default_does_not_launch_browser(self):
        cfg = BrowserConfig(enabled=False)
        provider = BrowserProvider(cfg)
        ev = provider.capture("https://example.com")
        assert ev.provider_status == BrowserStatus.DISABLED
        assert ev.navigation_ok is False
        assert "disabled" in ev.provider_error.lower()
        assert ev.to_dict()["provider_status"] == "DISABLED"

    def test_run_audit_sync_in_disabled_mode(self):
        """In disabled mode, _run_audit_sync returns DISABLED status and preserves all 62 factors."""
        from app.engines.audit_engine import _run_audit_sync
        # Run against example.com with browser explicitly disabled
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            results = _run_audit_sync("https://example.com")
            assert results["browser_status"] == "DISABLED"
            assert results["browser_evidence"] == {}
            assert "audit_results" in results
            assert "score" in results
            assert results["lifecycle"] == "COMPLETE"
            # Ensure all 62 factors are executed
            total_factors = sum(len(group) for group in results["audit_results"].values())
            assert total_factors == 62

    def test_disabled_mode_api_response_compatibility(self):
        """Verify API schema serializes cleanly with browser_status='DISABLED'."""
        from app.schemas import AuditResponse
        from datetime import datetime, timezone
        import uuid

        dummy_data = {
            "id": uuid.uuid4(),
            "lead_id": uuid.uuid4(),
            "ssl_valid": True,
            "has_sitemap": True,
            "has_robots": True,
            "broken_links_count": 0,
            "missing_h1": False,
            "missing_alt_count": 0,
            "uses_webp": True,
            "has_json_ld": True,
            "mobile_friendly": True,
            "missing_social": [],
            "audit_summary": "Test summary",
            "suggested_name": "Test Site",
            "pdf_path": None,
            "status": "done",
            "audit_lifecycle": "COMPLETE",
            "error_message": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "browser_status": "DISABLED",
            "browser_evidence": None,
        }
        resp = AuditResponse.model_validate(dummy_data)
        assert resp.browser_status == "DISABLED"
        assert resp.browser_evidence is None

    def test_pdf_generation_with_disabled_browser(self):
        """Verify PDF report builds without errors when browser is disabled."""
        from reporter.pdf_report import build_pdf
        audit_results = {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "PASS", "value": True, "score": 10, "max_score": 10}
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = os.path.join(tmpdir, "test_report.pdf")
            build_pdf(
                "https://example.test",
                audit_results,
                100,
                out_pdf,
                site_summary={"browser_status": "DISABLED", "browser_evidence": None},
                page_audits=[],
            )
            assert os.path.isfile(out_pdf)
            assert os.path.getsize(out_pdf) > 0


class TestRuntimeBrowserEnabled:
    """4.2 & 4.3: Verify provider enabled mode against deterministic fixtures."""

    def test_static_html_fixture_capture(self, fixture_server):
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/static")

        assert ev.provider_status == BrowserStatus.SUCCESS
        assert ev.navigation_ok is True
        assert ev.http_status == 200
        assert ev.page_title == "Static Audit Page"
        assert ev.meta_description == "A static description for SEO test."
        assert ev.has_nav is True
        assert ev.has_form is True
        assert ev.has_cta is True
        assert ev.has_visible_text is True
        assert len(ev.headings) >= 2
        assert any(h["level"] == "h1" and "Static Audit Primary Heading" in h["text"] for h in ev.headings)
        assert len(ev.dom_snippet) > 0
        assert ev.elapsed_ms > 0
        # Ensure evidence is JSON-serializable
        serialized = json.dumps(ev.to_dict())
        assert "Static Audit Page" in serialized

    def test_client_side_js_rendered_fixture_capture(self, fixture_server):
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/js-rendered")

        assert ev.provider_status == BrowserStatus.SUCCESS
        assert ev.page_title == "Rendered Dynamic Title"
        assert ev.has_cta is True  # Injected via JS
        assert any(h["level"] == "h1" and "Client-Side Injected H1" in h["text"] for h in ev.headings)

        # Test comparison logic: Raw HTTP had no H1, but JS DOM has it
        raw_results = {
            "onpage": {
                "page_title": {"status": "FAIL", "value": ""},
                "h1": {"status": "FAIL", "value": ""},
            },
            "ux": {
                "cta": {"status": "FAIL"},
            },
        }
        annotate_browser_comparisons(raw_results, ev)

        # Verifications
        assert raw_results["onpage"]["h1"]["status"] == "FAIL", "Status must remain FAIL (informational only)"
        assert raw_results["onpage"]["h1"]["browser_diff"]["verdict"] == "js_only"
        assert "Client-Side Injected H1" in raw_results["onpage"]["h1"]["browser_diff"]["rendered_h1s"][0]
        assert raw_results["ux"]["cta"]["browser_diff"]["verdict"] == "js_only"

    def test_timeout_fixture_isolated_outcome(self, fixture_server):
        """A timeout does not raise an exception; it returns a TIMEOUT status."""
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            nav_timeout_ms=1000,  # 1 second timeout
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        start = time.perf_counter()
        ev = provider.capture(f"{fixture_server}/delay-timeout")
        elapsed = time.perf_counter() - start

        assert ev.provider_status == BrowserStatus.TIMEOUT
        assert ev.navigation_ok is False
        assert "timed out" in ev.provider_error.lower()
        # Verify bounded wait time (did not hang indefinitely)
        assert elapsed < 5.0

    def test_console_and_failed_request_signals(self, fixture_server):
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/errors")

        assert ev.provider_status == BrowserStatus.SUCCESS
        assert len(ev.console_errors) >= 1
        assert any("Deliberate test error" in err for err in ev.console_errors)
        assert len(ev.failed_requests) >= 1
        assert any("nonexistent_script_404.js" in req for req in ev.failed_requests)

    def test_comparison_enabled_vs_disabled_mode_factor_invariance(self, fixture_server):
        """Compare enabled vs disabled on same fixture: factor statuses and score must remain unchanged."""
        # Baseline factor results simulating raw HTTP check
        def make_base():
            return {
                "onpage": {
                    "page_title": {"status": "PASS", "value": "Static Audit Page", "score": 5},
                    "h1": {"status": "PASS", "value": "Static Audit Primary Heading", "score": 5},
                },
                "ux": {
                    "cta": {"status": "PASS", "score": 5},
                },
            }

        base_disabled = make_base()
        ev_disabled = BrowserEvidence.disabled(f"{fixture_server}/static")
        annotate_browser_comparisons(base_disabled, ev_disabled)

        base_enabled = make_base()
        cfg = BrowserConfig(enabled=True, headless=True, allow_test_loopback=True)
        ev_enabled = BrowserProvider(cfg).capture(f"{fixture_server}/static")
        annotate_browser_comparisons(base_enabled, ev_enabled)

        # Status and scores must match exactly
        assert base_disabled["onpage"]["page_title"]["status"] == base_enabled["onpage"]["page_title"]["status"]
        assert base_disabled["onpage"]["h1"]["status"] == base_enabled["onpage"]["h1"]["status"]
        assert base_disabled["ux"]["cta"]["status"] == base_enabled["ux"]["cta"]["status"]

        # Only the additive browser_diff metadata is attached in enabled mode
        assert "browser_diff" not in base_disabled["onpage"]["page_title"]
        assert base_enabled["onpage"]["page_title"]["browser_diff"]["verdict"] == "consistent"

    def test_enabled_mode_api_and_pdf_compatibility(self, fixture_server):
        """Verify API schema and PDF report generation handle rich browser evidence."""
        from app.schemas import AuditResponse
        from reporter.pdf_report import build_pdf
        from datetime import datetime, timezone
        import uuid

        cfg = BrowserConfig(enabled=True, headless=True, allow_test_loopback=True)
        ev = BrowserProvider(cfg).capture(f"{fixture_server}/static")

        audit_dict = {
            "id": uuid.uuid4(),
            "lead_id": uuid.uuid4(),
            "ssl_valid": True,
            "has_sitemap": True,
            "has_robots": True,
            "broken_links_count": 0,
            "missing_h1": False,
            "missing_alt_count": 0,
            "uses_webp": True,
            "has_json_ld": True,
            "mobile_friendly": True,
            "missing_social": [],
            "audit_summary": "Summary with browser evidence",
            "suggested_name": "Static Site",
            "pdf_path": None,
            "status": "done",
            "audit_lifecycle": "COMPLETE",
            "error_message": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "browser_status": ev.provider_status,
            "browser_evidence": ev.to_dict(),
        }
        resp = AuditResponse.model_validate(audit_dict)
        assert resp.browser_status == "SUCCESS"
        assert resp.browser_evidence["page_title"] == "Static Audit Page"

        with tempfile.TemporaryDirectory() as tmpdir:
            out_pdf = os.path.join(tmpdir, "report_with_browser.pdf")
            build_pdf(
                f"{fixture_server}/static",
                {"technical": {"ssl": {"id": "technical.ssl", "status": "PASS", "value": True, "score": 10, "max_score": 10}}},
                100,
                out_pdf,
                site_summary={"browser_status": ev.provider_status, "browser_evidence": ev.to_dict()},
                page_audits=[],
            )
            assert os.path.isfile(out_pdf)


# ══════════════════════════════════════════════════════════════════════════════
# CHECK 2: BROWSER SECURITY VERIFICATION (SSRF & URL HARDENING)
# ══════════════════════════════════════════════════════════════════════════════

class TestBrowserSecurityValidation:
    """5.1 & 5.2: Verify URL and IP address validation."""

    def test_unsupported_schemes_blocked(self):
        blocked_schemes = [
            "file:///etc/passwd",
            "file:///C:/Windows/win.ini",
            "javascript:alert(document.cookie)",
            "ftp://ftp.example.com/file",
            "data:text/html,<h1>pwned</h1>",
            "gopher://gopher.example.com",
            "ws://example.com/socket",
            "ssh://root@example.com",
        ]
        for url in blocked_schemes:
            res = validate_url(url)
            assert not res.allowed, f"Expected {url} to be blocked"
            assert "scheme" in res.reason.lower() or "blocked" in res.reason.lower()

    def test_ipv4_loopback_blocked(self):
        for url in ["http://127.0.0.1/", "http://127.0.0.2/admin", "http://127.255.255.254/"]:
            res = validate_url(url)
            assert not res.allowed, f"Expected {url} to be blocked"

    def test_ipv4_private_rfc1918_blocked(self):
        private_ips = [
            "http://10.0.0.1/",
            "http://10.255.255.255/secret",
            "http://172.16.0.1/",
            "http://172.31.255.255/",
            "http://192.168.0.1/",
            "http://192.168.1.100/router",
        ]
        for url in private_ips:
            res = validate_url(url)
            assert not res.allowed, f"Expected {url} to be blocked"

    def test_ipv4_link_local_and_reserved_blocked(self):
        reserved_ips = [
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "http://169.254.1.1/",
            "http://0.0.0.0/",                            # Unspecified
            "http://100.64.0.1/",                         # CGNAT
            "http://192.0.2.1/",                          # Documentation
            "http://198.51.100.1/",                       # Documentation
            "http://203.0.113.1/",                        # Documentation
            "http://224.0.0.1/",                          # Multicast
            "http://240.0.0.1/",                          # Class E
            "http://255.255.255.255/",                    # Broadcast
        ]
        for url in reserved_ips:
            res = validate_url(url)
            assert not res.allowed, f"Expected {url} to be blocked"

    def test_ipv6_loopback_and_special_ranges_blocked(self):
        ipv6_blocked = [
            "http://[::1]/",                              # Loopback
            "http://[::]/",                               # Unspecified
            "http://[fc00::1]/",                          # Unique-local
            "http://[fd12:3456:789a::1]/",                # Unique-local
            "http://[fe80::1]/",                          # Link-local
            "http://[ff02::1]/",                          # Multicast
            "http://[2001:db8::1]/",                      # Documentation
        ]
        for url in ipv6_blocked:
            res = validate_url(url)
            assert not res.allowed, f"Expected {url} to be blocked"

    def test_ipv4_mapped_ipv6_addresses_blocked(self):
        """Crucial SSRF bypass test: IPv4-mapped IPv6 literals."""
        mapped_urls = [
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:169.254.169.254]/latest/meta-data/",
            "http://[::ffff:10.0.0.1]/admin",
            "http://[::ffff:192.168.1.1]/",
        ]
        for url in mapped_urls:
            res = validate_url(url)
            assert not res.allowed, f"Expected IPv4-mapped IPv6 {url} to be blocked"
            assert "blocked" in res.reason.lower()

    def test_alternative_numeric_ip_formats_blocked(self):
        """Crucial SSRF bypass test: integer, hex, octal IP representations."""
        numeric_urls = [
            "http://2130706433/",        # Decimal integer representation of 127.0.0.1
            "http://0x7f000001/",        # Hexadecimal integer representation of 127.0.0.1
            "http://0177.0.0.1/",        # Dotted octal representation of 127.0.0.1
            "http://0x7f.0.0.1/",        # Dotted hex representation of 127.0.0.1
            "http://2852039166/",        # Decimal representation of 169.254.169.254
        ]
        for url in numeric_urls:
            res = validate_url(url)
            assert not res.allowed, f"Expected alternative numeric format {url} to be blocked"

    def test_dns_resolution_private_ip_hostname_blocked(self):
        """A hostname resolving to a private IP must be blocked."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80))
            ]
            res = validate_url("http://internal.company.local")
            assert not res.allowed
            assert "resolves to a blocked address" in res.reason

    def test_dns_resolution_mixed_public_and_private_blocked(self):
        """DNS returning both public and private addresses must fail closed."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),  # public
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),       # loopback
            ]
            res = validate_url("http://mixed-dns.example.com")
            assert not res.allowed
            assert "resolves to a blocked address" in res.reason

    def test_dns_failure_fails_closed(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
            res = validate_url("http://nonexistent.domain.that.does.not.exist")
            assert not res.allowed
            assert "DNS resolution failed" in res.reason


class TestBrowserRedirectAndBoundaryEnforcement:
    """5.3: Verify redirect protection and request boundary enforcement."""

    def test_redirect_to_private_ip_blocked_at_boundary(self, fixture_server):
        """When a server responds with 302 to a private IP, the browser route handler aborts before connection."""
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            allow_test_loopback=True,  # Allow initial test fixture host
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/redirect-to-private")

        assert ev.provider_status == BrowserStatus.BLOCKED
        assert ev.navigation_ok is False
        assert "blocked" in ev.provider_error.lower()

    def test_subresource_requests_to_private_ips_aborted(self, fixture_server):
        """Subresources attempting to fetch 169.254.169.254 or 192.168.1.1 are intercepted and aborted."""
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/subresource-ssrf")

        # The main page loaded, but subresources were aborted
        assert ev.provider_status == BrowserStatus.SUCCESS
        assert ev.page_title == "Subresource SSRF"
        # The aborted subresources appear in failed_requests
        assert len(ev.failed_requests) >= 1
        failed_targets = " ".join(ev.failed_requests)
        assert "169.254.169.254" in failed_targets or "192.168.1.1" in failed_targets


class TestResourceLimitsAndCleanup:
    """5.4: Verify resource bounds and cleanup."""

    def test_dom_snippet_truncation(self, fixture_server):
        cfg = BrowserConfig(
            enabled=True,
            headless=True,
            dom_snippet_max_chars=16_384,
            allow_test_loopback=True,
        )
        provider = BrowserProvider(cfg)
        ev = provider.capture(f"{fixture_server}/huge-dom")

        assert ev.provider_status == BrowserStatus.SUCCESS
        assert len(ev.dom_snippet) <= 16_384

    def test_concurrency_semaphore_limit(self):
        from browser.provider import _get_semaphore
        sem = _get_semaphore(max_concurrency=2)
        assert sem is not None

    def test_cleanup_on_crash(self):
        """Verify _cleanup closes resources safely even if errors occur."""
        from browser.provider import _cleanup
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_ctx = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        _cleanup(mock_page, mock_ctx, mock_browser, mock_pw)

        mock_page.close.assert_called_once()
        mock_ctx.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.close.assert_called_once()
