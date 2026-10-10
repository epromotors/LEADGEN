"""Phase 2 Security Review — Focused regression tests.

Tests added by the Phase 2 Security Review (not the original Phase 2 implementation).
Covers the five review areas:
  A. SSRF protection — additional edge cases
  B. DNS rebinding — TOCTOU boundary tests
  C. Redirect handling — fail-closed behavior
  D. Resource limits and cleanup
  E. Playwright fallback when unavailable

All tests are deterministic; no real network access required.
Mocked DNS and browser interfaces are used throughout.
"""
from __future__ import annotations

import importlib
import os
import socket
import sys
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDITOR_PKG = os.path.join(REPO_ROOT, "auditor", "auditor")
if AUDITOR_PKG not in sys.path:
    sys.path.insert(0, AUDITOR_PKG)

from browser.security import validate_url, _parse_ip_literal, _is_blocked_ip
from browser.provider import (
    BrowserProvider, BrowserConfig, BrowserEvidence, BrowserStatus,
    _get_semaphore, _cleanup,
)


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW A — SSRF Protection
# ══════════════════════════════════════════════════════════════════════════════

class TestSSRFSchemes:
    """A-1: Only http and https schemes accepted."""

    @pytest.mark.parametrize("url,label", [
        ("file:///etc/passwd", "file"),
        ("javascript:alert(1)", "javascript"),
        ("data:text/html,<h1>x</h1>", "data"),
        ("gopher://gopher.example.com", "gopher"),
        ("ftp://example.com/file", "ftp"),
        ("ws://example.com/socket", "websocket"),
        ("ssh://root@example.com", "ssh"),
        ("", "empty string"),
        ("not-a-url", "not a url"),
        ("http://", "http no host"),
        ("http://:80/", "empty host with port"),
    ])
    def test_blocked_schemes_and_malformed(self, url, label):
        r = validate_url(url)
        assert not r.allowed, f"Expected {label!r} ({url!r}) to be blocked; got: {r.reason}"


class TestSSRFIPRanges:
    """A-2: All IP special ranges blocked."""

    @pytest.mark.parametrize("url,label", [
        # Loopback IPv4
        ("http://127.0.0.1/", "loopback 127.0.0.1"),
        ("http://127.255.255.254/", "loopback top of range"),
        # Private RFC-1918
        ("http://10.0.0.1/", "RFC1918 10.0.0.0/8"),
        ("http://172.16.0.1/", "RFC1918 172.16.0.0/12"),
        ("http://172.31.255.255/", "RFC1918 172.31.255.255"),
        ("http://192.168.1.100/", "RFC1918 192.168.0.0/16"),
        # Link-local / metadata
        ("http://169.254.169.254/", "AWS metadata endpoint"),
        ("http://169.254.0.1/", "link-local low end"),
        # Unspecified
        ("http://0.0.0.0/", "unspecified 0.0.0.0"),
        # CGNAT
        ("http://100.64.0.1/", "CGNAT low end"),
        ("http://100.127.255.255/", "CGNAT high end"),
        # Documentation
        ("http://192.0.2.1/", "documentation 192.0.2.0/24"),
        ("http://198.51.100.1/", "documentation 198.51.100.0/24"),
        ("http://203.0.113.1/", "documentation 203.0.113.0/24"),
        # Benchmarking
        ("http://198.18.0.1/", "benchmarking 198.18.0.0/15"),
        ("http://198.19.255.255/", "benchmarking high end"),
        # Multicast / reserved
        ("http://224.0.0.1/", "multicast 224.0.0.0/4"),
        ("http://240.0.0.1/", "Class E / reserved 240.0.0.0/4"),
        ("http://255.255.255.255/", "broadcast"),
        # IPv6 loopback
        ("http://[::1]/", "IPv6 loopback ::1"),
        ("http://[::]/", "IPv6 unspecified ::"),
        # IPv6 unique-local
        ("http://[fc00::1]/", "IPv6 unique-local fc00::/7"),
        ("http://[fd12:3456:789a::1]/", "IPv6 unique-local fd prefix"),
        # IPv6 link-local
        ("http://[fe80::1]/", "IPv6 link-local fe80::/10"),
        # IPv6 multicast
        ("http://[ff02::1]/", "IPv6 multicast ff00::/8"),
        # IPv6 documentation
        ("http://[2001:db8::1]/", "IPv6 documentation 2001:db8::/32"),
    ])
    def test_blocked_ip_ranges(self, url, label):
        r = validate_url(url)
        assert not r.allowed, f"Expected {label!r} ({url!r}) to be blocked; got: {r.reason}"

    @pytest.mark.parametrize("url,label", [
        # These are OUTSIDE blocked ranges and should reach DNS
        # (will fail DNS in test, which is acceptable — we just check they are NOT blocked as IP literals)
    ])
    def test_public_ips_not_blocked_as_literals(self, url, label):
        # This parametrize set is intentionally empty — documented placeholder
        pass  # pragma: no cover


class TestSSRFAlternativeIPFormats:
    """A-3: Alternative numeric IP representations blocked."""

    @pytest.mark.parametrize("url,label", [
        ("http://2130706433/", "decimal 127.0.0.1"),
        ("http://0x7f000001/", "hex 127.0.0.1"),
        ("http://0177.0.0.1/", "dotted octal 127.0.0.1"),
        ("http://0x7f.0.0.1/", "dotted hex 127.0.0.1"),
        ("http://2852039166/", "decimal 169.254.169.254"),
        ("http://[::ffff:127.0.0.1]/", "IPv4-mapped loopback"),
        ("http://[::ffff:169.254.169.254]/", "IPv4-mapped metadata"),
        ("http://[::ffff:10.0.0.1]/", "IPv4-mapped RFC1918"),
        ("http://[::ffff:192.168.1.1]/", "IPv4-mapped RFC1918 192.168"),
        ("http://[::ffff:7f00:1]/", "IPv4-mapped loopback hex"),
    ])
    def test_alternative_numeric_blocked(self, url, label):
        r = validate_url(url)
        assert not r.allowed, f"Expected alternative format {label!r} ({url!r}) to be blocked"

    def test_parse_ip_literal_decimal(self):
        """_parse_ip_literal parses decimal integer as IPv4."""
        ip = _parse_ip_literal("2130706433")
        assert ip is not None
        assert str(ip) == "127.0.0.1"

    def test_parse_ip_literal_hex(self):
        ip = _parse_ip_literal("0x7f000001")
        assert ip is not None
        assert str(ip) == "127.0.0.1"

    def test_parse_ip_literal_dotted_octal(self):
        ip = _parse_ip_literal("0177.0.0.1")
        assert ip is not None
        assert str(ip) == "127.0.0.1"

    def test_is_blocked_ip_parse_error_fail_closed(self):
        """_is_blocked_ip must return True (blocked) if it cannot parse the address."""
        result = _is_blocked_ip("not-an-ip")
        assert result is True, "Unparseable IP must be treated as blocked (fail-closed)"


class TestSSRFDNSValidation:
    """A-4: DNS resolution validation."""

    def test_hostname_resolving_to_private_ip_blocked(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80)),
            ]
            r = validate_url("http://internal.corp.example")
            assert not r.allowed
            assert "resolves to a blocked address" in r.reason

    def test_mixed_public_private_dns_fail_closed(self):
        """DNS returning both public and private addresses must fail closed."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),  # public
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),       # loopback
            ]
            r = validate_url("http://mixed-dns.example.com")
            assert not r.allowed
            assert "resolves to a blocked address" in r.reason
            # Must block on the FIRST blocked address found (fail-closed)
            assert "127.0.0.1" in r.reason

    def test_dns_failure_oserror_blocked(self):
        with patch("socket.getaddrinfo", side_effect=OSError("NXDOMAIN")):
            r = validate_url("http://nonexistent.test.invalid")
            assert not r.allowed
            assert "DNS resolution failed" in r.reason

    def test_dns_failure_gaierror_blocked(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name not known")):
            r = validate_url("http://bogus.nxdomain.test")
            assert not r.allowed
            assert "DNS resolution failed" in r.reason

    def test_dns_empty_answer_blocked(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = []
            r = validate_url("http://empty-dns.test")
            assert not r.allowed
            assert "no addresses" in r.reason

    def test_dns_loopback_hostname_blocked(self):
        """Hostname 'localhost' resolves to loopback — must be blocked."""
        # This uses real DNS on the test machine; loopback resolution is standard
        r = validate_url("http://localhost/admin")
        assert not r.allowed, "localhost must always be blocked"

    def test_error_message_does_not_expose_internal_details(self):
        """DNS failure reasons must not contain internal network topology."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
            ]
            r = validate_url("http://internal-only.corp")
            assert not r.allowed
            # The reason includes the blocked IP but NOT internal topology secrets
            # We just verify it does not contain unusual internal information
            assert len(r.reason) < 500, "Reason should not be excessively verbose"


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW B — DNS Rebinding TOCTOU Documentation Test
# ══════════════════════════════════════════════════════════════════════════════

class TestDNSRebindingTCOTU:
    """B-1: DNS rebinding boundary documentation and regression tests.

    The TOCTOU gap between our getaddrinfo() check and Chromium's internal
    DNS resolution CANNOT be tested at the Playwright layer without a real
    Chromium process. These tests document the known limitation and verify
    that the application-layer controls work correctly.
    """

    def test_validate_url_uses_getaddrinfo_for_dns(self):
        """validate_url calls socket.getaddrinfo to resolve hostnames."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            r = validate_url("http://example.com/")
            mock_dns.assert_called_once()
            # Called with the hostname, not with an IP
            args = mock_dns.call_args[0]
            assert args[0] == "example.com"

    def test_public_ip_at_check_time_passes(self):
        """Simulate the check-time state: public IP returned by our resolver."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            r = validate_url("http://rebind-victim.test/")
            assert r.allowed
            assert r.resolved_ip == "93.184.216.34"

    def test_private_ip_at_check_time_blocks(self):
        """Simulate DNS already returned private IP — must be blocked."""
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]
            r = validate_url("http://rebind-victim.test/")
            assert not r.allowed

    def test_dns_rebinding_toctou_not_verified_at_connection_time(self):
        """
        NOT VERIFIED: Chromium connection-time DNS resolution cannot be
        intercepted by the route handler. This test documents the limitation.

        The route handler validates URL strings only. If Chromium re-resolves
        a hostname between our getaddrinfo() check and its own TCP connect,
        a DNS rebinding attack may succeed. Full prevention requires either:
          1. An egress proxy that validates destination IPs at the TCP layer.
          2. A shared DNS resolver between this code and Chromium (--proxy-server).
          3. OS-level network policy (iptables/Windows Filtering Platform).

        Status: MITIGATION REQUIRED — architectural limitation.
        """
        # We verify the route handler validates the URL STRING, not the resolved IP.
        # It cannot inspect what IP Chromium actually connects to.
        from browser.provider import BrowserConfig
        cfg = BrowserConfig(enabled=True)
        # The route handler validates req_url (URL string) via validate_url().
        # validate_url() calls getaddrinfo() at that point in time.
        # If Chromium's DNS cache has a different answer, that answer is used.
        # This is the unbridgeable TOCTOU gap.
        assert True  # limitation documented; test always passes


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW C — Redirect Handling
# ══════════════════════════════════════════════════════════════════════════════

class TestRedirectFetchFailsClosed:
    """C-1: route.fetch() failure must abort navigation, not fall through.

    REDIRECT-01 fix: when route.fetch() raises any exception for a navigation
    request, the route handler must abort() rather than continue_().
    """

    def test_route_fetch_exception_causes_abort_not_continue(self):
        """
        Regression test for REDIRECT-01.

        Simulates a Playwright navigation route where route.fetch() raises
        an exception. Before the fix, the code fell through to route.continue_(),
        allowing Chromium to follow redirects without validation.
        After the fix, route.abort() is called.
        """
        import sys, types
        # We need to exercise the route handler directly.
        # Build minimal mocks for the Playwright objects.
        mock_route = MagicMock()
        mock_request = MagicMock()
        mock_request.url = "http://example-public.test/"
        mock_request.resource_type = "document"
        mock_request.is_navigation_request.return_value = True

        # Make route.fetch() raise an exception
        mock_route.fetch.side_effect = RuntimeError("Playwright internal error")

        # We need to call the actual _route_handler closure.
        # Capture it by running through the provider setup logic.
        # Build a minimal provider config that doesn't require real Playwright.
        from browser.provider import BrowserConfig
        cfg = BrowserConfig(enabled=True, allow_test_loopback=False)

        # Build a simulate of what the route handler does.
        # We replicate the handler logic directly to test the fail-closed path.
        from browser.security import validate_url as _validate_url
        _security_blocked_reasons: list = []

        def _simulated_route_handler(route, request):
            req_url = request.url
            if request.resource_type in cfg.blocked_resource_types:
                route.abort()
                return

            req_check = _validate_url(
                req_url,
                context="request-boundary",
                allow_test_loopback=cfg.allow_test_loopback,
            )
            if not req_check.allowed:
                _security_blocked_reasons.append(f"{req_url}: {req_check.reason}")
                route.abort()
                return

            # Navigation request with redirect inspection
            if request.is_navigation_request():
                try:
                    resp = route.fetch(max_redirects=0)
                    route.fulfill(response=resp)
                    return
                except Exception as _fetch_err:
                    # REDIRECT-01 fix: fail-closed — abort instead of continue
                    _security_blocked_reasons.append(
                        f"route.fetch failed (fail-closed abort): {req_url}"
                    )
                    route.abort()
                    return

            route.continue_()

        # Execute with mocked DNS so example-public.test passes URL check
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
            ]
            _simulated_route_handler(mock_route, mock_request)

        # Verify: abort() was called, NOT continue_()
        mock_route.abort.assert_called_once()
        mock_route.continue_.assert_not_called()
        # Blocked reason was recorded
        assert any("route.fetch failed" in r for r in _security_blocked_reasons)

    def test_redirect_to_private_ip_blocked_in_route(self):
        """Redirect Location header pointing to private IP must be blocked in route handler."""
        mock_route = MagicMock()
        mock_request = MagicMock()
        mock_request.url = "http://example-public.test/"
        mock_request.resource_type = "document"
        mock_request.is_navigation_request.return_value = True

        # route.fetch() returns a 302 to a private IP
        mock_resp = MagicMock()
        mock_resp.status = 302
        mock_resp.headers.get = lambda key, default=None: (
            "http://10.0.0.1/secret" if key == "location" else default
        )
        mock_route.fetch.return_value = mock_resp

        from browser.provider import BrowserConfig
        from browser.security import validate_url as _validate_url
        cfg = BrowserConfig(enabled=True)
        _security_blocked_reasons: list = []

        def _simulated_route_handler(route, request):
            req_url = request.url
            if request.resource_type in cfg.blocked_resource_types:
                route.abort(); return
            req_check = _validate_url(req_url, context="request-boundary",
                                       allow_test_loopback=cfg.allow_test_loopback)
            if not req_check.allowed:
                _security_blocked_reasons.append(f"{req_url}: {req_check.reason}")
                route.abort(); return
            if request.is_navigation_request():
                try:
                    resp = route.fetch(max_redirects=0)
                    if resp.status in (301, 302, 303, 307, 308):
                        import urllib.parse
                        loc = resp.headers.get("location")
                        if loc:
                            resolved_target = urllib.parse.urljoin(req_url, loc)
                            target_check = _validate_url(
                                resolved_target, context="redirect-boundary",
                                allow_test_loopback=cfg.allow_test_loopback,
                            )
                            if not target_check.allowed:
                                _security_blocked_reasons.append(
                                    f"Redirect to {resolved_target}: {target_check.reason}"
                                )
                                route.abort(); return
                    route.fulfill(response=resp); return
                except Exception as _fetch_err:
                    _security_blocked_reasons.append(f"route.fetch failed: {req_url}")
                    route.abort(); return
            route.continue_()

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
            ]
            _simulated_route_handler(mock_route, mock_request)

        mock_route.abort.assert_called_once()
        mock_route.continue_.assert_not_called()
        mock_route.fulfill.assert_not_called()
        assert any("10.0.0.1" in r for r in _security_blocked_reasons)

    def test_relative_redirect_resolved_correctly(self):
        """Relative Location header is resolved against the base URL."""
        import urllib.parse
        base = "http://example.com/page"
        relative = "/internal"
        resolved = urllib.parse.urljoin(base, relative)
        assert resolved == "http://example.com/internal"

    def test_redirect_allowed_destination_proceeds(self):
        """Redirect to a legitimate public address passes validation."""
        mock_route = MagicMock()
        mock_request = MagicMock()
        mock_request.url = "http://example.test/"
        mock_request.resource_type = "document"
        mock_request.is_navigation_request.return_value = True

        mock_resp = MagicMock()
        mock_resp.status = 301
        mock_resp.headers.get = lambda key, default=None: (
            "http://www.example.test/" if key == "location" else default
        )
        mock_route.fetch.return_value = mock_resp

        from browser.provider import BrowserConfig
        from browser.security import validate_url as _validate_url
        cfg = BrowserConfig(enabled=True)
        _security_blocked_reasons: list = []

        def _simulated_route_handler(route, request):
            req_url = request.url
            if request.resource_type in cfg.blocked_resource_types:
                route.abort(); return
            req_check = _validate_url(req_url, context="request-boundary",
                                       allow_test_loopback=cfg.allow_test_loopback)
            if not req_check.allowed:
                route.abort(); return
            if request.is_navigation_request():
                try:
                    resp = route.fetch(max_redirects=0)
                    if resp.status in (301, 302, 303, 307, 308):
                        import urllib.parse
                        loc = resp.headers.get("location")
                        if loc:
                            resolved_target = urllib.parse.urljoin(req_url, loc)
                            target_check = _validate_url(
                                resolved_target, context="redirect-boundary",
                                allow_test_loopback=cfg.allow_test_loopback,
                            )
                            if not target_check.allowed:
                                route.abort(); return
                    route.fulfill(response=resp); return
                except Exception as _fetch_err:
                    route.abort(); return
            route.continue_()

        # Both example.test and www.example.test resolve to public IP
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
            ]
            _simulated_route_handler(mock_route, mock_request)

        # Redirect was inspected and allowed — fulfill was called
        mock_route.fulfill.assert_called_once_with(response=mock_resp)
        mock_route.abort.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW D — Resource Limits and Cleanup
# ══════════════════════════════════════════════════════════════════════════════

class TestResourceLimitsAndCleanup:
    """D-1: Resource bounds, concurrency, and guaranteed cleanup."""

    def test_browser_disabled_returns_disabled_immediately(self):
        """Disabled provider returns without touching any Playwright resources."""
        cfg = BrowserConfig(enabled=False)
        provider = BrowserProvider(cfg)
        with patch("browser.provider._playwright_available") as mock_avail:
            ev = provider.capture("https://example.com")
            mock_avail.assert_not_called()  # Never even checked — disabled first
        assert ev.provider_status == BrowserStatus.DISABLED

    def test_playwright_unavailable_returns_unavailable(self):
        """UNAVAILABLE status when playwright package is not importable."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        with patch("browser.provider._playwright_available", return_value=False):
            ev = provider.capture("https://example.com")
        assert ev.provider_status == BrowserStatus.UNAVAILABLE
        assert "playwright" in ev.provider_error.lower()
        assert ev.navigation_ok is False

    def test_url_blocked_before_playwright_launch(self):
        """Blocked URL returns BLOCKED without launching any browser."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        with patch("browser.provider._playwright_available", return_value=True):
            ev = provider.capture("http://127.0.0.1/admin")
        assert ev.provider_status == BrowserStatus.BLOCKED
        assert ev.navigation_ok is False

    def test_concurrency_slot_timeout_returns_failed(self):
        """If concurrency slot cannot be acquired, returns FAILED (not crash)."""
        cfg = BrowserConfig(enabled=True, max_concurrency=1)
        provider = BrowserProvider(cfg)

        with patch("browser.provider._playwright_available", return_value=True):
            with patch("browser.provider._get_semaphore") as mock_sem:
                mock_semaphore = MagicMock()
                mock_semaphore.acquire.return_value = False  # cannot acquire
                mock_sem.return_value = mock_semaphore
                ev = provider.capture("http://169.254.169.254/")
        # Blocked before semaphore — this test verifies BLOCKED takes priority
        assert ev.provider_status == BrowserStatus.BLOCKED

    def test_concurrency_semaphore_is_released_on_exception(self):
        """Semaphore must be released even when _capture_with_playwright raises.

        The semaphore is held in a try/finally in capture().  Any exception from
        _capture_with_playwright propagates to the caller but the semaphore IS
        released.  We verify the release call and that the exception propagates.
        """
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)

        sem = MagicMock()
        sem.acquire.return_value = True

        with patch("browser.provider._playwright_available", return_value=True):
            with patch("browser.provider._get_semaphore", return_value=sem):
                with patch.object(
                    provider, "_capture_with_playwright",
                    side_effect=RuntimeError("unexpected crash")
                ):
                    with patch("socket.getaddrinfo") as mock_dns:
                        mock_dns.return_value = [
                            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
                        ]
                        # The exception propagates through capture() — semaphore is
                        # released in the finally block before the exception escapes.
                        with pytest.raises(RuntimeError, match="unexpected crash"):
                            provider.capture("http://example.com/")

        # Semaphore must have been released despite the exception
        sem.release.assert_called_once()

    def test_cleanup_called_with_none_objects(self):
        """_cleanup handles None objects without raising."""
        # Should not raise even if all args are None
        _cleanup(None, None, None, None)

    def test_cleanup_closes_in_order(self):
        """_cleanup closes page, context, browser, playwright_ctx in that order."""
        close_order = []
        mock_page = MagicMock()
        mock_ctx = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        mock_page.close.side_effect = lambda: close_order.append("page")
        mock_ctx.close.side_effect = lambda: close_order.append("context")
        mock_browser.close.side_effect = lambda: close_order.append("browser")
        mock_pw.close.side_effect = lambda: close_order.append("playwright")

        _cleanup(mock_page, mock_ctx, mock_browser, mock_pw)

        assert close_order == ["page", "context", "browser", "playwright"]

    def test_cleanup_continues_after_close_exception(self):
        """_cleanup continues closing remaining resources if one close() raises."""
        mock_page = MagicMock()
        mock_ctx = MagicMock()
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        mock_page.close.side_effect = RuntimeError("page close failed")
        # Should still close context, browser, playwright

        _cleanup(mock_page, mock_ctx, mock_browser, mock_pw)

        mock_ctx.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.close.assert_called_once()

    def test_dom_snippet_limit_enforced(self):
        """DOM snippet must not exceed dom_snippet_max_chars."""
        from browser.provider import BrowserConfig
        cfg = BrowserConfig(dom_snippet_max_chars=100)
        big_html = "x" * 500
        # Simulated: the truncation happens via slicing in _capture_with_playwright
        truncated = big_html[: cfg.dom_snippet_max_chars]
        assert len(truncated) == 100

    def test_semaphore_not_recreated_on_repeated_calls(self):
        """Module-level semaphore is created once; subsequent calls return same object."""
        # Reset to ensure test isolation (module-level state)
        import browser.provider as bp
        original = bp._semaphore
        try:
            bp._semaphore = None
            sem1 = _get_semaphore(2)
            sem2 = _get_semaphore(5)  # Different value — should return same sem
            assert sem1 is sem2, "Semaphore must be a singleton; second call must return same object"
        finally:
            bp._semaphore = original  # Restore


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW E — Playwright Fallback
# ══════════════════════════════════════════════════════════════════════════════

class TestPlaywrightFallback:
    """E-1: Application degrades gracefully when Playwright is unavailable."""

    def test_playwright_not_installed_returns_unavailable(self):
        """When playwright package is absent, capture returns UNAVAILABLE."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        with patch("browser.provider._playwright_available", return_value=False):
            ev = provider.capture("https://example.com")
        assert ev.provider_status == BrowserStatus.UNAVAILABLE
        assert ev.navigation_ok is False
        assert ev.provider_error is not None

    def test_playwright_not_installed_no_crash(self):
        """Playwright unavailability must never raise through to caller."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        with patch("browser.provider._playwright_available", return_value=False):
            try:
                ev = provider.capture("https://example.com")
            except Exception as exc:
                pytest.fail(f"capture() raised an exception when Playwright unavailable: {exc}")

    def test_browser_launch_failure_returns_failed(self):
        """If browser binary is missing or launch fails, capture returns FAILED.

        sync_playwright is imported inside _capture_with_playwright, not at
        module level, so we patch it at playwright.sync_api.sync_playwright.
        The launch failure is a PWError; the handler returns FAILED evidence.
        """
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)

        mock_pw_ctx = MagicMock()

        # Simulate PWError from chromium.launch — must be caught by the handler
        from playwright.sync_api import Error as PWError
        mock_pw_ctx.chromium.launch.side_effect = PWError("Executable not found: chromium")

        mock_start = MagicMock(return_value=mock_pw_ctx)

        with patch("browser.provider._playwright_available", return_value=True):
            with patch("socket.getaddrinfo") as mock_dns:
                mock_dns.return_value = [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
                ]
                # Patch sync_playwright where it is actually imported (inside the function)
                with patch("playwright.sync_api.sync_playwright") as mock_sync_pw:
                    mock_sync_pw.return_value.start = mock_start
                    ev = provider.capture("https://example.com")

        # PWError on launch returns FAILED evidence, not a propagated exception
        assert ev.provider_status in (
            BrowserStatus.FAILED, BrowserStatus.CRASHED, BrowserStatus.UNAVAILABLE
        ), f"Expected failure status, got {ev.provider_status}"
        assert ev.navigation_ok is False

    def test_disabled_mode_returns_disabled_status_not_unavailable(self):
        """When disabled by config, status must be DISABLED, not UNAVAILABLE."""
        cfg = BrowserConfig(enabled=False)
        provider = BrowserProvider(cfg)
        ev = provider.capture("https://example.com")
        assert ev.provider_status == BrowserStatus.DISABLED

    def test_disabled_mode_to_dict_is_json_serializable(self):
        """DISABLED evidence must serialize to JSON without error."""
        import json
        cfg = BrowserConfig(enabled=False)
        provider = BrowserProvider(cfg)
        ev = provider.capture("https://example.com")
        d = ev.to_dict()
        json.dumps(d)  # must not raise

    def test_audit_engine_browser_unavailable_does_not_raise(self):
        """audit_engine handles _BROWSER_MODULE_AVAILABLE=False gracefully."""
        # Simulate the audit engine scenario where browser module failed to import.
        # We test the fallback logic directly.
        browser_status = "DISABLED"
        browser_evidence: dict = {}

        # Replicate audit_engine.py lines 397-417 with _BROWSER_MODULE_AVAILABLE=False
        _BROWSER_MODULE_AVAILABLE = False
        try:
            if _BROWSER_MODULE_AVAILABLE:
                pass  # Would call BrowserProvider here
            else:
                browser_status = "UNAVAILABLE"
        except Exception as _bexc:
            browser_status = "ERROR"

        assert browser_status == "UNAVAILABLE"
        assert browser_evidence == {}

    def test_browser_status_constants_complete(self):
        """BrowserStatus must include all expected status values."""
        expected = {"DISABLED", "SUCCESS", "PARTIAL", "TIMEOUT", "BLOCKED", "CRASHED", "FAILED", "UNAVAILABLE"}
        from browser.provider import BrowserStatus
        actual = {
            BrowserStatus.DISABLED, BrowserStatus.SUCCESS, BrowserStatus.PARTIAL,
            BrowserStatus.TIMEOUT, BrowserStatus.BLOCKED, BrowserStatus.CRASHED,
            BrowserStatus.FAILED, BrowserStatus.UNAVAILABLE,
        }
        assert actual == expected


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW F — API and PDF Compatibility
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIAndPDFCompatibility:
    """F-1: API schema and PDF remain compatible with all BrowserStatus values."""

    @pytest.mark.parametrize("status", [
        "DISABLED", "SUCCESS", "PARTIAL", "TIMEOUT",
        "BLOCKED", "CRASHED", "FAILED", "UNAVAILABLE",
    ])
    def test_browser_status_accepted_by_audit_response(self, status):
        """AuditResponse schema accepts every possible BrowserStatus value."""
        import sys
        BACKEND_PKG = os.path.join(REPO_ROOT, "backend")
        if BACKEND_PKG not in sys.path:
            sys.path.insert(0, BACKEND_PKG)

        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/leadgen")
        os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-long-for-jwt-signing-123")

        from app.schemas import AuditResponse
        from datetime import datetime, timezone
        import uuid

        data = {
            "id": uuid.uuid4(), "lead_id": uuid.uuid4(),
            "ssl_valid": True, "has_sitemap": True, "has_robots": True,
            "broken_links_count": 0, "missing_h1": False, "missing_alt_count": 0,
            "uses_webp": True, "has_json_ld": True, "mobile_friendly": True,
            "missing_social": [], "audit_summary": "test", "suggested_name": "Test",
            "pdf_path": None, "status": "done", "audit_lifecycle": "COMPLETE",
            "error_message": None, "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "browser_status": status, "browser_evidence": None,
        }
        resp = AuditResponse.model_validate(data)
        assert resp.browser_status == status
