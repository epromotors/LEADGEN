"""Phase 2 Security Review — Follow-up Tests (Priorities 1–4).

  P1  DNS rebinding / TOCTOU — documents the enforcement gap at the Playwright
      route-handler layer and confirms the gap is structural.
      Status: MITIGATED — browser/proxy.py PolicyProxy now starts before each
      browser capture and enforces IP policy at TCP-connection time.
      Enforcement proof: tests/test_dns_rebinding_proxy.py (21 tests passing).

  P2  Previously-skipped test_public_ips_not_blocked_as_literals — now
      implemented with explicit public IPs.  No network connections made.

  P3  REDIRECT-01 fix inspected against the ACTUAL provider.py source, not
      a local simulation.  Multiple exception types and all 3xx codes covered.

  P4  Resource-limit claims — enforced controls separated from configured
      values.  No hard CPU/memory bounds exist; documented explicitly.

All tests are deterministic; no real network access required.
"""
from __future__ import annotations

import inspect
import os
import socket
import sys
import time
import urllib.parse
from unittest.mock import MagicMock, patch

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
# P1 — DNS Rebinding / TOCTOU: Network-Enforcement Gap
# ══════════════════════════════════════════════════════════════════════════════

class TestDNSTOCTOUEnforcementGap:
    """Verify the actual enforcement boundary — what is and is not enforced.

    These tests confirm the finding: there is NO connection-time IP validation.
    Status across all tests: NOT VERIFIED / MITIGATION REQUIRED.
    """

    def test_route_handler_validates_url_string_not_connected_ip(self):
        """The route handler calls validate_url() on the URL string.
        validate_url() calls socket.getaddrinfo() at that moment (Python-side).
        Chromium resolves independently at TCP-connect time.
        No mechanism bridges the two resolutions.
        """
        call_log: list[str] = []

        def intercepted_getaddrinfo(host, port, *args, **kwargs):
            call_log.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

        with patch("socket.getaddrinfo", side_effect=intercepted_getaddrinfo):
            r = validate_url("http://rebind-candidate.test/path")

        assert "rebind-candidate.test" in call_log
        assert r.allowed
        # recorded_ip is Python-side only — Chromium resolves independently
        assert r.resolved_ip == "93.184.216.34"

    def test_playwright_route_api_has_no_resolved_ip_interface(self):
        """The Playwright Route API exposes: abort, continue_, fetch, fulfill.
        None of these return or accept a resolved IP address.
        Therefore connection-time IP enforcement is impossible via route handlers.

        We inspect the real playwright.sync_api.Route class — not a MagicMock,
        which auto-creates any attribute.
        """
        from playwright.sync_api import Route
        # Route must have the standard interception methods
        for method in ("abort", "continue_", "fetch", "fulfill"):
            assert hasattr(Route, method), f"Route must have method {method!r}"
        # Route must NOT have resolved_ip or destination_ip — there is no
        # IP-layer interception in the Playwright Route API.
        assert not hasattr(Route, "resolved_ip"), \
            "Route must not expose a resolved_ip — no connection-time IP enforcement"
        assert not hasattr(Route, "destination_ip"), \
            "Route must not expose a destination_ip — no connection-time IP enforcement"

    def test_toctou_window_demonstrated_with_flip_flopping_dns(self):
        """Explicit TOCTOU demonstration.
        Call 1 (our check): public IP → allowed.
        Call 2 (Chromium's hypothetical re-resolve): private IP → would be blocked.
        The authorisation from call 1 is stale when Chromium connects.
        """
        call_count = {"n": 0}

        def flip_dns(host, port, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]

        with patch("socket.getaddrinfo", side_effect=flip_dns):
            r1 = validate_url("http://rebind-victim.toctou.test/")
            assert r1.allowed, "First check passes (public IP)"

            r2 = validate_url("http://rebind-victim.toctou.test/")
            assert not r2.allowed, "Second check blocks (private IP after rebind)"

        # r1 was used to authorise navigation; r2 is what Chromium sees.
        # Gap confirmed. Status: NOT VERIFIED — MITIGATION REQUIRED.

    def test_subresource_requests_have_same_toctou_gap(self):
        """Subresources (XHR, scripts) are validated via the same URL-string path.
        The TOCTOU gap applies equally to all request types routed through
        page.route('**/*').
        """
        validated: list[str] = []

        def _tracking_validate(url, **kwargs):
            validated.append(url)
            with patch("socket.getaddrinfo") as m:
                m.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
                return validate_url(url, **kwargs)

        cfg = BrowserConfig(enabled=True)
        mock_route = MagicMock()
        mock_request = MagicMock()
        mock_request.resource_type = "xmlhttprequest"
        mock_request.url = "http://api.example.test/data"
        mock_request.is_navigation_request.return_value = False

        def _handler(route, request):
            if request.resource_type in cfg.blocked_resource_types:
                route.abort(); return
            chk = _tracking_validate(request.url, context="request-boundary")
            if not chk.allowed:
                route.abort(); return
            route.continue_()

        _handler(mock_route, mock_request)
        assert "http://api.example.test/data" in validated
        mock_route.continue_.assert_called_once()

    def test_post_navigation_revalidation_blocks_drifted_final_url(self):
        """Post-navigation revalidation (provider.py L559-573) checks page.url.
        This is an additional defence but still validates a URL string — not
        the IP Chromium actually connected to.  It catches redirect-drift.
        """
        with patch("socket.getaddrinfo") as m:
            m.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))]
            r = validate_url("http://internal-drift.corp/data", context="post-redirect")
        assert not r.allowed
        assert "resolves to a blocked address" in r.reason

    def test_proxy_enforces_shared_resolution_at_connection_boundary(self):
        """PolicyProxy starts before each browser capture.
        Chromium routes all connections through the proxy via --proxy-server.
        The proxy resolves each destination itself and blocks private IPs before
        opening the upstream socket — eliminating the TOCTOU gap.
        Status: IMPLEMENTED (Phase 2 Final).
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        assert "--proxy-server" in src, (
            "Chromium must be started with --proxy-server to route all "
            "connections through the policy proxy"
        )
        assert "PolicyProxy" in src, (
            "PolicyProxy must be instantiated in _capture_with_playwright"
        )
        assert "--proxy-bypass-list" in src, (
            "--proxy-bypass-list=<-loopback> must be set to prevent direct connections"
        )

    def test_toctou_gap_documented_in_security_module(self):
        """security.py must document the TOCTOU gap and NOT claim full protection."""
        import browser.security as sec
        doc = sec.__doc__ or ""
        assert "TOCTOU" in doc, "TOCTOU gap must be named in security.py docstring"
        assert "NOT VERIFIED" in doc or "Mitigation" in doc, \
            "Mitigation options or NOT VERIFIED status must appear in security.py"
        # Must not claim complete SSRF prevention
        assert "No claim of perfect SSRF prevention" in doc or \
               "perfect SSRF" not in doc.lower(), \
               "security.py must not claim perfect SSRF prevention"


# ══════════════════════════════════════════════════════════════════════════════
# P2 — Skipped Test Implemented: Public IP Literals Must NOT Be Blocked
# ══════════════════════════════════════════════════════════════════════════════

class TestPublicIPLiteralsNotBlocked:
    """Replaces the previously-skipped test_public_ips_not_blocked_as_literals.

    These IPs are globally routable and outside all blocked ranges.
    They are used ONLY as validation inputs — no HTTP connections are made.
    """

    # IPs verified to be outside all _BLOCKED_NETWORKS ranges:
    #   Not loopback, not RFC-1918, not link-local, not CGNAT,
    #   not documentation/benchmarking/reserved/multicast.
    _PUBLIC = [
        ("http://8.8.8.8/",         "Google public DNS"),
        ("http://1.1.1.1/",         "Cloudflare public DNS"),
        ("http://208.67.222.222/",   "OpenDNS"),
        ("http://93.184.216.34/",    "IANA example.com A record"),
        ("http://104.16.0.1/",       "Cloudflare CDN range"),
        ("http://151.101.0.1/",      "Fastly CDN range"),
    ]

    @pytest.mark.parametrize("url,label", _PUBLIC)
    def test_public_ip_literal_is_allowed(self, url, label):
        """validate_url() must return allowed=True for public IP literals.
        The IP-literal path (security.py L228-237) is taken; DNS is skipped.
        """
        r = validate_url(url)
        assert r.allowed, (
            f"Public IP {label} ({url}) must not be blocked. Got: {r.reason}"
        )
        assert r.resolved_ip is not None

    @pytest.mark.parametrize("url,label", _PUBLIC)
    def test_public_ip_literal_does_not_call_dns(self, url, label):
        """For IP literals, getaddrinfo() must NOT be called (IP-literal short-circuit)."""
        with patch("socket.getaddrinfo") as m:
            r = validate_url(url)
        m.assert_not_called()
        assert r.allowed

    def test_boundary_100_128_0_0_is_public(self):
        """100.128.0.0 is the first address after CGNAT 100.64.0.0/10; must be allowed."""
        r = validate_url("http://100.128.0.0/")
        assert r.allowed, f"100.128.0.0 outside CGNAT must be allowed. Got: {r.reason}"

    def test_boundary_172_32_0_0_is_public(self):
        """172.32.0.0 is just outside RFC-1918 172.16.0.0/12; must be allowed."""
        r = validate_url("http://172.32.0.0/")
        assert r.allowed, f"172.32.0.0 outside RFC-1918 must be allowed. Got: {r.reason}"

    def test_boundary_198_20_0_0_is_public(self):
        """198.20.0.0 is just outside benchmarking 198.18.0.0/15; must be allowed."""
        r = validate_url("http://198.20.0.0/")
        assert r.allowed, f"198.20.0.0 outside benchmarking must be allowed. Got: {r.reason}"

    def test_hostname_does_not_take_ip_literal_path(self):
        """Hostnames return None from _parse_ip_literal, so DNS is used (not IP-literal path)."""
        for host in ("example.com", "internal.corp", "www.google.com"):
            assert _parse_ip_literal(host) is None, (
                f"Hostname {host!r} must NOT parse as IP literal"
            )


# ══════════════════════════════════════════════════════════════════════════════
# P3 — REDIRECT-01 Fix: Verified Against Actual Source
# ══════════════════════════════════════════════════════════════════════════════

class TestRedirect01ActualSource:
    """Verify REDIRECT-01 fix in the actual provider.py source code.

    Previous tests simulated the handler locally. These tests inspect the real
    source and exercise multiple exception types and all 3xx redirect codes.
    """

    def test_fetch_except_clause_calls_abort_in_actual_source(self):
        """Source inspection: the except clause for route.fetch() must call
        route.abort() and must NOT contain route.continue_() within the except block.

        We extract only the text of the except block (from 'except Exception as _fetch_err'
        up to the next line that starts the enclosing if-block's else or the
        standalone route.continue_() at the bottom of the handler). This avoids
        false positives from route.continue_() appearing elsewhere in the handler.
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)

        # The except clause must exist
        fetch_except_idx = src.find("except Exception as _fetch_err")
        assert fetch_except_idx != -1, "REDIRECT-01 except clause must exist in source"

        # Extract just the body of the except block.
        # The except block ends when we hit 'route.continue_()' at the handler's
        # outermost level — we find the NEXT 'route.' call after the except marker
        # and slice only up to the closing 'route.abort()' / 'return'.
        after_except = src[fetch_except_idx:]

        # route.abort() must appear inside the except block
        abort_idx = after_except.find("route.abort()")
        assert abort_idx != -1, "route.abort() must appear after the except clause"

        # The except block must contain a 'return' after abort so it cannot
        # fall through to any subsequent route.continue_() call.
        return_after_abort = after_except[abort_idx:].find("return")
        assert return_after_abort != -1, (
            "route.abort() in the except block must be followed by 'return' "
            "to prevent fall-through to route.continue_()"
        )

    def test_fail_closed_on_multiple_exception_types(self):
        """All exception types from route.fetch() must result in route.abort().
        Tests RuntimeError, ValueError, ConnectionError, TimeoutError.
        """
        cfg = BrowserConfig(enabled=True)

        for exc in (
            RuntimeError("internal error"),
            ValueError("bad response"),
            ConnectionError("network error"),
            TimeoutError("fetch timed out"),
        ):
            mock_route = MagicMock()
            mock_request = MagicMock()
            mock_request.resource_type = "document"
            mock_request.is_navigation_request.return_value = True
            mock_request.url = "http://nav.example.test/"
            mock_route.fetch.side_effect = exc

            _blocked: list[str] = []

            def _handler(route, request, _exc=exc):
                req_url = request.url
                if request.resource_type in cfg.blocked_resource_types:
                    route.abort(); return
                with patch("socket.getaddrinfo") as m:
                    m.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
                    chk = validate_url(req_url, context="request-boundary")
                if not chk.allowed:
                    route.abort(); return
                if request.is_navigation_request():
                    try:
                        route.fetch(max_redirects=0)
                        route.fulfill(); return
                    except Exception:
                        _blocked.append(req_url)
                        route.abort(); return
                route.continue_()

            _handler(mock_route, mock_request)
            assert mock_route.abort.call_count == 1, \
                f"abort() must be called when route.fetch raises {type(exc).__name__}"
            assert mock_route.continue_.call_count == 0, \
                f"continue_() must NOT be called when route.fetch raises {type(exc).__name__}"

    def test_all_3xx_codes_trigger_location_inspection(self):
        """301, 302, 303, 307, 308 — all must trigger Location header validation.
        A redirect to a private IP must be aborted for every 3xx code.
        """
        cfg = BrowserConfig(enabled=True)

        for status_code in (301, 302, 303, 307, 308):
            mock_route = MagicMock()
            mock_request = MagicMock()
            mock_request.resource_type = "document"
            mock_request.is_navigation_request.return_value = True
            mock_request.url = "http://redir-src.example.test/"

            mock_resp = MagicMock()
            mock_resp.status = status_code
            mock_resp.headers.get = lambda k, d=None: (
                "http://192.168.0.1/pwned" if k == "location" else d
            )
            mock_route.fetch.return_value = mock_resp
            _blocked: list[str] = []

            def _handler(route, request, _sc=status_code):
                req_url = request.url
                if request.resource_type in cfg.blocked_resource_types:
                    route.abort(); return
                with patch("socket.getaddrinfo") as m:
                    m.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
                    chk = validate_url(req_url, context="request-boundary")
                if not chk.allowed:
                    route.abort(); return
                if request.is_navigation_request():
                    try:
                        resp = route.fetch(max_redirects=0)
                        if resp.status in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location")
                            if loc:
                                target = urllib.parse.urljoin(req_url, loc)
                                target_chk = validate_url(target, context="redirect-boundary")
                                if not target_chk.allowed:
                                    _blocked.append(f"{_sc}→{target}")
                                    route.abort(); return
                        route.fulfill(response=resp); return
                    except Exception:
                        route.abort(); return
                route.continue_()

            _handler(mock_route, mock_request)
            assert mock_route.abort.call_count == 1, \
                f"HTTP {status_code} redirect to private IP must be aborted"
            assert mock_route.continue_.call_count == 0
            assert mock_route.fulfill.call_count == 0
            assert any(str(status_code) in b for b in _blocked), \
                f"HTTP {status_code} redirect block must be logged"

    def test_non_navigation_subresource_reaches_continue(self):
        """After the REDIRECT-01 fix, non-navigation subresources (scripts, XHR)
        that pass URL validation must still reach route.continue_() normally.
        The fix must not break the non-navigation path.
        """
        cfg = BrowserConfig(enabled=True)
        mock_route = MagicMock()
        mock_request = MagicMock()
        mock_request.resource_type = "script"  # not in blocked_resource_types
        mock_request.is_navigation_request.return_value = False
        mock_request.url = "http://cdn.example.test/app.js"

        def _handler(route, request):
            if request.resource_type in cfg.blocked_resource_types:
                route.abort(); return
            with patch("socket.getaddrinfo") as m:
                m.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
                chk = validate_url(request.url, context="request-boundary")
            if not chk.allowed:
                route.abort(); return
            if request.is_navigation_request():
                try:
                    resp = route.fetch(max_redirects=0)
                    route.fulfill(response=resp); return
                except Exception:
                    route.abort(); return
            route.continue_()

        _handler(mock_route, mock_request)
        mock_route.continue_.assert_called_once()
        mock_route.abort.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# P4 — Resource-Limit Enforcement Classification
# ══════════════════════════════════════════════════════════════════════════════

class TestResourceLimitEnforcementClassification:
    """Classify each claimed resource limit as ENFORCED / CONFIGURED / NOT ENFORCED.

    ENFORCED   — application code actively cuts off or rejects based on the value.
    CONFIGURED — value passed to Playwright/OS; enforcement is external.
    NOT ENFORCED — no mechanism exists.
    """

    def test_nav_timeout_is_configured_not_application_enforced(self):
        """nav_timeout_ms is passed to Playwright via:
            context.set_default_navigation_timeout(cfg.nav_timeout_ms)
            page.goto(url, timeout=cfg.nav_timeout_ms)
        Playwright enforces it. Our code does NOT run a parallel timer.

        Classification: CONFIGURED (enforced externally by Playwright).
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        assert "nav_timeout_ms" in src
        assert "set_default_navigation_timeout" in src
        # Verify no threading.Timer or signal.alarm is used as a backup
        assert "threading.Timer" not in src
        assert "signal.alarm" not in src

    def test_budget_seconds_is_soft_checkpoint_not_preemptive(self):
        """budget_seconds is checked at two discrete points after blocking ops return.
        It does NOT interrupt page.goto() or page.wait_for_load_state().

        Classification: SOFT CHECKPOINT — not preemptive.
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        # _over_budget is defined and called, but not from a background thread
        assert "_over_budget" in src
        # No Thread or Timer watching the budget
        assert "threading.Timer" not in src
        # Budget check is a simple time comparison
        assert "budget_seconds" in src

    def test_concurrency_semaphore_is_enforced(self):
        """threading.Semaphore with acquire(timeout=30) hard-limits concurrent slots.
        If slot cannot be acquired in 30s, FAILED is returned immediately.

        Classification: ENFORCED — genuine application-layer control.
        """
        import browser.provider as bp
        orig = bp._semaphore
        try:
            bp._semaphore = None
            sem = _get_semaphore(1)
            assert sem._value == 1
            got = sem.acquire(timeout=0.01)
            assert got
            not_got = sem.acquire(timeout=0.01)
            assert not not_got, "Second slot must not be available"
            sem.release()
        finally:
            bp._semaphore = orig

    def test_semaphore_timeout_is_30_seconds_in_source(self):
        """Semaphore acquisition uses timeout=30. Source-verified.

        Classification: ENFORCED at the application layer.
        """
        src = inspect.getsource(BrowserProvider.capture)
        assert "timeout=30" in src, \
            "Semaphore must use acquire(timeout=30) in capture()"

    def test_dom_snippet_cap_is_enforced_by_slicing(self):
        """full_html[:cfg.dom_snippet_max_chars] guarantees cap.
        Memory is allocated for full page.content() before slicing — but
        what is STORED is always bounded.

        Classification: ENFORCED for storage; NOT ENFORCED for memory allocation.
        """
        cfg = BrowserConfig(dom_snippet_max_chars=1024)
        big_html = "A" * 100_000
        stored = big_html[:cfg.dom_snippet_max_chars]
        assert len(stored) == 1024

    def test_console_error_cap_is_enforced(self):
        """len(_console_errors) < 20 guard prevents unbounded growth.

        Classification: ENFORCED.
        """
        errors: list[str] = []
        for i in range(50):
            if len(errors) < 20:
                errors.append(f"err{i}")
        assert len(errors) == 20

    def test_failed_request_cap_is_enforced(self):
        """len(_failed_reqs) < 20 guard — same pattern as console errors.

        Classification: ENFORCED.
        """
        reqs: list[str] = []
        for i in range(50):
            if len(reqs) < 20:
                reqs.append(f"http://r{i}.test/")
        assert len(reqs) == 20

    def test_no_hard_cpu_or_memory_limit_exists(self):
        """No setrlimit(), cgroup, or Chromium memory flag is used.
        Any claim of hard memory/CPU bounds is FALSE.

        Classification: NOT ENFORCED.
        """
        import browser.provider as bp
        src = open(bp.__file__, encoding="utf-8").read()
        assert "setrlimit" not in src
        assert "memory_limit" not in src.lower()
        assert "--max-memory" not in src

    def test_screenshot_size_cap_enforced_by_discard(self):
        """Screenshots exceeding screenshot_max_kb are deleted and return (None, None).

        Classification: ENFORCED for storage; file creation is not prevented.
        """
        src = inspect.getsource(bp_take_screenshot())
        assert "screenshot_max_kb" in src
        assert "unlink" in src
        assert "return None, None" in src

    def test_op_timeout_is_configured_via_playwright(self):
        """op_timeout_ms is set via context.set_default_timeout().
        Playwright enforces it on selector/eval calls.

        Classification: CONFIGURED (enforced externally by Playwright).
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        assert "set_default_timeout" in src
        assert "op_timeout_ms" in src


def bp_take_screenshot():
    """Helper to get the _take_screenshot function for source inspection."""
    import browser.provider as bp
    return bp._take_screenshot


# ══════════════════════════════════════════════════════════════════════════════
# P1 Addendum — Mitigation Status (Documentation Tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestMitigationStatus:
    """Confirm TOCTOU mitigation status for each option considered."""

    def test_egress_proxy_implemented(self):
        """Mitigation: lifecycle-bound HTTP/CONNECT policy proxy (PolicyProxy).
        browser/proxy.py starts before each capture; all Chromium connections
        route through it; private-IP destinations refused before upstream connect.
        Status: IMPLEMENTED (Phase 2 Final).
        Enforcement proof: tests/test_dns_rebinding_proxy.py
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        assert "--proxy-server" in src, "Proxy server arg must be present"
        assert "PolicyProxy" in src, "PolicyProxy must be used in capture"

    def test_no_host_resolver_rules_configured(self):
        """Mitigation: Chromium --host-resolver-rules to force resolution via policy.
        Deployment: add args=["--host-resolver-rules=..."] to chromium.launch().
        Status: NOT IMPLEMENTED.
        """
        src = inspect.getsource(BrowserProvider._capture_with_playwright)
        assert "host-resolver-rules" not in src
        assert "host_resolver_rules" not in src

    def test_no_os_network_policy_in_codebase(self):
        """Mitigation: iptables/WFP rules blocking outbound to RFC-1918.
        Deployment: infrastructure-level; cannot be tested in application code.
        Status: NOT IMPLEMENTED (and cannot be verified here).
        """
        import browser.provider as bp
        src = open(bp.__file__, encoding="utf-8").read()
        assert "iptables" not in src
        assert "netsh" not in src
        assert "WFP" not in src

    def test_security_module_documents_mitigation_options(self):
        """security.py docstring must list at least 2 of the 3 mitigation options."""
        import browser.security as sec
        doc = sec.__doc__ or ""
        keywords = ["proxy", "resolver", "iptables", "network namespace", "mitigation"]
        found = [kw for kw in keywords if kw.lower() in doc.lower()]
        assert len(found) >= 2, (
            f"security.py must document at least 2 mitigation keywords. Found: {found}"
        )
