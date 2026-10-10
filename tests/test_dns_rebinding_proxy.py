"""DNS rebinding SSRF mitigation — enforcement boundary tests.

These tests verify that the PolicyProxy (browser/proxy.py) blocks connections
to private/reserved IP addresses at TCP-connection time.

    "Do not count a test that only checks a validation function's return value
    as proof of connection-time enforcement."

Every test in TestProxyEnforcementBoundary sends an actual HTTP or CONNECT
request to the running PolicyProxy instance and asserts that the proxy returns
403 Forbidden before opening any upstream socket.  The proxy IS running; the
upstream connection is what is (correctly) refused.
"""

from __future__ import annotations

import http.server
import socket
import threading
import time
from typing import Generator

import pytest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "auditor", "auditor"))

from browser.proxy import PolicyProxy, _send_error, _clean_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _http_proxy_request(proxy_port: int, host: str, port: int, path: str = "/") -> tuple[int, bytes]:
    """Send a plain HTTP proxy GET through the proxy, return (status_code, raw_response)."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5) as s:
        req = (
            f"GET http://{host}:{port}{path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("latin-1")
        s.sendall(req)
        s.settimeout(5.0)
        raw = b""
        while True:
            try:
                chunk = s.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            raw += chunk
    if not raw:
        return 0, b""
    status_line = raw.split(b"\r\n")[0]
    parts = status_line.split(b" ", 2)
    try:
        return int(parts[1]), raw
    except (IndexError, ValueError):
        return 0, raw


def _connect_request(proxy_port: int, host: str, port: int) -> int:
    """Send HTTP CONNECT through the proxy, return the proxy's status code."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5) as s:
        req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("latin-1")
        s.sendall(req)
        s.settimeout(5.0)
        raw = b""
        while b"\r\n\r\n" not in raw and len(raw) < 1024:
            try:
                chunk = s.recv(256)
            except OSError:
                break
            if not chunk:
                break
            raw += chunk
    if not raw:
        return 0
    parts = raw.split(b"\r\n")[0].split(b" ", 2)
    try:
        return int(parts[1])
    except (IndexError, ValueError):
        return 0


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"OK from fixture"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def proxy_strict() -> Generator[PolicyProxy, None, None]:
    with PolicyProxy(allow_test_loopback=False) as p:
        yield p


@pytest.fixture()
def proxy_loopback() -> Generator[PolicyProxy, None, None]:
    with PolicyProxy(allow_test_loopback=True) as p:
        yield p


@pytest.fixture()
def fixture_server() -> Generator[int, None, None]:
    srv = http.server.HTTPServer(("127.0.0.1", 0), _FixtureHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port
    srv.shutdown()


# ---------------------------------------------------------------------------
# TestProxyEnforcementBoundary
# Proves blocking at the NETWORK CONNECTION boundary, not URL-string level.
# The proxy is running; what is refused is the upstream TCP connection.
# ---------------------------------------------------------------------------

class TestProxyEnforcementBoundary:

    def test_http_proxy_blocks_10_0_0_0(self, proxy_strict):
        """HTTP proxy request to 10.x must be blocked with 403."""
        code, _ = _http_proxy_request(proxy_strict.port, "10.0.0.1", 80)
        assert code == 403, f"Expected 403 for RFC-1918 10.x, got {code}"

    def test_http_proxy_blocks_192_168(self, proxy_strict):
        code, _ = _http_proxy_request(proxy_strict.port, "192.168.1.1", 80)
        assert code == 403, f"Expected 403 for 192.168.x.x, got {code}"

    def test_http_proxy_blocks_172_16(self, proxy_strict):
        code, _ = _http_proxy_request(proxy_strict.port, "172.16.0.1", 80)
        assert code == 403, f"Expected 403 for 172.16.x.x, got {code}"

    def test_http_proxy_blocks_loopback_strict(self, proxy_strict):
        """127.0.0.1 must be blocked in strict (production) mode."""
        code, _ = _http_proxy_request(proxy_strict.port, "127.0.0.1", 8080)
        assert code == 403, f"Expected 403 for loopback in strict mode, got {code}"

    def test_http_proxy_blocks_link_local_metadata(self, proxy_strict):
        """169.254.169.254 is the cloud IMDS endpoint — must be blocked."""
        code, _ = _http_proxy_request(proxy_strict.port, "169.254.169.254", 80)
        assert code == 403, f"Expected 403 for 169.254.169.254, got {code}"

    def test_http_proxy_blocks_multicast(self, proxy_strict):
        code, _ = _http_proxy_request(proxy_strict.port, "224.0.0.1", 80)
        assert code == 403, f"Expected 403 for multicast, got {code}"

    def test_connect_blocks_10_0_0_0(self, proxy_strict):
        """CONNECT to 10.x must be refused before upstream TCP is opened."""
        code = _connect_request(proxy_strict.port, "10.0.0.1", 443)
        assert code == 403, f"Expected 403 CONNECT to 10.0.0.1:443, got {code}"

    def test_connect_blocks_192_168(self, proxy_strict):
        code = _connect_request(proxy_strict.port, "192.168.0.1", 443)
        assert code == 403, f"Expected 403 CONNECT to 192.168.0.1:443, got {code}"

    def test_connect_blocks_cloud_metadata(self, proxy_strict):
        """Cloud metadata IMDS must be unreachable via HTTPS CONNECT too."""
        code = _connect_request(proxy_strict.port, "169.254.169.254", 443)
        assert code == 403, f"Expected 403 CONNECT to 169.254.169.254:443, got {code}"

    def test_connect_blocks_loopback_strict(self, proxy_strict):
        code = _connect_request(proxy_strict.port, "127.0.0.1", 443)
        assert code == 403, f"Expected 403 CONNECT to 127.0.0.1:443 in strict mode, got {code}"

    def test_403_body_says_forbidden(self, proxy_strict):
        """The 403 response body must identify the block reason."""
        code, body = _http_proxy_request(proxy_strict.port, "10.0.0.1", 80)
        assert code == 403
        assert b"Forbidden" in body or b"forbidden" in body.lower(), (
            f"Response body should say Forbidden: {body[:200]!r}"
        )

    def test_block_does_not_require_upstream_to_be_listening(self, proxy_strict):
        """Proxy must return 403 for 10.x even when nothing is listening there.

        Proves enforcement happens before any upstream connection attempt.
        Port 19 (chargen) is almost certainly not open on 10.0.0.1.
        """
        code, _ = _http_proxy_request(proxy_strict.port, "10.0.0.1", 19)
        assert code == 403, (
            f"Expected 403 (policy block before connection attempt), got {code}. "
            f"Got 502 would mean proxy tried to connect — that would be wrong."
        )


# ---------------------------------------------------------------------------
# TestProxyPassthrough
# ---------------------------------------------------------------------------

class TestProxyPassthrough:

    def test_loopback_allowed_with_test_flag(self, proxy_loopback, fixture_server):
        """With allow_test_loopback=True, loopback fixture server is reachable."""
        code, body = _http_proxy_request(proxy_loopback.port, "127.0.0.1", fixture_server)
        assert code == 200, f"Expected 200 from fixture via proxy, got {code}"
        assert b"OK from fixture" in body

    def test_loopback_blocked_without_test_flag(self, proxy_strict, fixture_server):
        """With strict policy, loopback is always blocked even for fixture."""
        code, _ = _http_proxy_request(proxy_strict.port, "127.0.0.1", fixture_server)
        assert code == 403, f"Expected 403 for loopback in strict mode, got {code}"


# ---------------------------------------------------------------------------
# TestProxyLifecycle
# ---------------------------------------------------------------------------

class TestProxyLifecycle:

    def test_proxy_starts_and_accepts_connections(self):
        proxy = PolicyProxy(allow_test_loopback=True)
        proxy.start()
        try:
            assert proxy.port > 0
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=2):
                pass
        finally:
            proxy.stop()

    def test_context_manager_starts_and_stops(self):
        with PolicyProxy(allow_test_loopback=True) as proxy:
            port = proxy.port
            assert port > 0
        time.sleep(0.1)
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()

    def test_stop_is_idempotent(self):
        p = PolicyProxy()
        p.start()
        p.stop()
        p.stop()  # must not raise

    def test_double_start_raises(self):
        with PolicyProxy() as p:
            with pytest.raises(RuntimeError, match="already started"):
                p.start()


# ---------------------------------------------------------------------------
# TestProxyHelpers
# ---------------------------------------------------------------------------

class TestProxyHelpers:

    def test_send_error_format(self):
        a, b = socket.socketpair()
        try:
            _send_error(a, 403, "Forbidden")
            a.close()
            b.settimeout(1.0)
            data = b""
            while True:
                try:
                    chunk = b.recv(256)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
        finally:
            try:
                a.close()
            except Exception:
                pass
            b.close()
        assert data.startswith(b"HTTP/1.1 403"), f"Bad error format: {data[:80]!r}"
        assert b"Forbidden" in data

    def test_clean_headers_strips_proxy_headers(self):
        lines = [
            b"Host: example.com",
            b"Proxy-Authorization: Basic abc",
            b"Connection: keep-alive",
            b"Keep-Alive: timeout=5",
            b"Transfer-Encoding: chunked",
            b"Accept: text/html",
            b"proxy-connection: keep-alive",
        ]
        result = _clean_headers(lines)
        lowered = [l.lower() for l in result]
        assert b"host: example.com" in lowered
        assert b"accept: text/html" in lowered
        for stripped in (
            b"proxy-authorization: basic abc",
            b"connection: keep-alive",
            b"keep-alive: timeout=5",
            b"transfer-encoding: chunked",
            b"proxy-connection: keep-alive",
        ):
            assert stripped not in lowered, f"Should have been stripped: {stripped}"

    def test_clean_headers_keeps_credentials_untouched(self):
        """Authorization and Cookie must be forwarded (not stripped), just not logged."""
        lines = [b"Authorization: Bearer token123", b"Cookie: session=abc"]
        result = _clean_headers(lines)
        lowered = [l.lower() for l in result]
        assert b"authorization: bearer token123" in lowered
        assert b"cookie: session=abc" in lowered
