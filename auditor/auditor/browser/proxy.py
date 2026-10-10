"""Policy-aware egress proxy for the LEADGEN browser evidence provider.

Enforces destination-IP security policy at TCP-connection time, eliminating
the DNS rebinding TOCTOU gap.  Key security properties:

  - Proxy resolves destination hostname itself; Chromium never resolves
    independently because --proxy-server forces all traffic through here and
    --proxy-bypass-list=<-loopback> disables the default loopback bypass.
  - The same resolved IP that is validated is used for socket.connect() —
    no second resolution gap.
  - Mixed public/private DNS answers fail closed: ANY blocked address -> 403.
  - CONNECT (HTTPS): destination resolved and validated before tunnel opens;
    payload is relayed without decryption.
  - If the proxy is unavailable: Chromium fails all requests (fail-closed).

Credential safeguards: no logging of bodies, Authorization, or Cookie headers.

Lifecycle: starts and stops inside BrowserProvider._capture_with_playwright()
so proxy lifetime is bounded to one browser capture session.

Design: stdlib only (socket, threading, selectors).  No new dependencies.
"""
from __future__ import annotations

import logging
import selectors
import socket
import threading
from typing import Optional

from browser.security import _is_blocked_ip

logger = logging.getLogger(__name__)

_RELAY_CHUNK = 65536       # bytes per relay read
_SELECT_TIMEOUT = 30.0     # relay idle timeout (seconds)
_MAX_CONNECTIONS = 16      # max concurrent proxy connections
_CONNECT_TIMEOUT = 10.0    # upstream TCP connect timeout (seconds)


class ProxyDenied(Exception):
    """Raised when the proxy refuses a connection due to security policy."""


class PolicyProxy:
    """Lifecycle-bound HTTP/CONNECT egress proxy with IP policy enforcement.

    Usage (context manager - preferred)::

        with PolicyProxy(allow_test_loopback=False) as proxy:
            proxy_url = f"http://127.0.0.1:{proxy.port}"
            # pass proxy_url to Chromium via --proxy-server

    Manual usage::

        proxy = PolicyProxy()
        proxy.start()
        try:
            use(proxy.port)
        finally:
            proxy.stop()
    """

    def __init__(self, allow_test_loopback: bool = False) -> None:
        self._allow_test_loopback = allow_test_loopback
        self._server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._port: int = 0
        self._stop_event = threading.Event()
        self._active_connections = threading.Semaphore(_MAX_CONNECTIONS)

    @property
    def port(self) -> int:
        """The ephemeral port the proxy is listening on."""
        return self._port

    def start(self) -> None:
        """Start the proxy listener on an ephemeral loopback port."""
        if self._server_sock is not None:
            raise RuntimeError("PolicyProxy already started")
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))   # loopback only
        srv.listen(32)
        self._port = srv.getsockname()[1]
        srv.setblocking(False)
        self._server_sock = srv
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name=f"policy-proxy-{self._port}",
            daemon=True,
        )
        self._thread.start()
        logger.debug("[policy_proxy] started on 127.0.0.1:%d", self._port)

    def stop(self) -> None:
        """Stop the proxy listener.  Safe to call multiple times."""
        self._stop_event.set()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.debug("[policy_proxy] stopped (port was %d)", self._port)

    def __enter__(self) -> "PolicyProxy":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    # -- Internal server loop -------------------------------------------------

    def _serve(self) -> None:
        sel = selectors.DefaultSelector()
        try:
            assert self._server_sock is not None
            sel.register(self._server_sock, selectors.EVENT_READ)
            while not self._stop_event.is_set():
                events = sel.select(timeout=0.5)
                for key, _ in events:
                    if key.fileobj is self._server_sock:
                        try:
                            client_sock, _ = self._server_sock.accept()
                        except OSError:
                            return
                        if self._active_connections.acquire(blocking=False):
                            threading.Thread(
                                target=self._handle_connection,
                                args=(client_sock,),
                                daemon=True,
                            ).start()
                        else:
                            logger.warning("[policy_proxy] connection limit reached, refusing")
                            try:
                                client_sock.sendall(
                                    b"HTTP/1.1 503 Service Unavailable\r\n"
                                    b"Content-Length: 0\r\n\r\n"
                                )
                            except Exception:
                                pass
                            client_sock.close()
        finally:
            sel.close()

    def _handle_connection(self, client_sock: socket.socket) -> None:
        try:
            self._process(client_sock)
        except Exception as exc:
            logger.debug("[policy_proxy] connection error: %s", exc)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            self._active_connections.release()

    def _process(self, client_sock: socket.socket) -> None:
        """Parse the incoming HTTP request and dispatch."""
        client_sock.settimeout(10.0)
        raw = b""
        while b"\r\n\r\n" not in raw and len(raw) < 16384:
            chunk = client_sock.recv(4096)
            if not chunk:
                return
            raw += chunk
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            _send_error(client_sock, 400, "Bad Request")
            return
        header_bytes = raw[:header_end]
        leftover = raw[header_end + 4:]
        lines = header_bytes.split(b"\r\n")
        if not lines:
            _send_error(client_sock, 400, "Bad Request")
            return
        request_line = lines[0].decode("latin-1", errors="replace")
        parts = request_line.split(" ")
        if len(parts) < 2:
            _send_error(client_sock, 400, "Bad Request")
            return
        method = parts[0].upper()
        if method == "CONNECT":
            self._handle_connect(client_sock, parts[1])
        else:
            self._handle_plain_http(client_sock, method, parts[1], lines[1:], leftover)

    # -- CONNECT (HTTPS tunnel) -----------------------------------------------

    def _handle_connect(self, client_sock: socket.socket, target: str) -> None:
        """Handle HTTPS CONNECT tunnel."""
        host, _, port_str = target.rpartition(":")
        if not host:
            host = target
            port_str = "443"
        try:
            port = int(port_str)
        except ValueError:
            _send_error(client_sock, 400, "Bad Request")
            return
        try:
            upstream = self._open_validated_upstream(host, port)
        except ProxyDenied as exc:
            logger.debug("[policy_proxy] CONNECT denied %s: %s", target, exc)
            _send_error(client_sock, 403, "Forbidden")
            return
        except OSError as exc:
            logger.debug("[policy_proxy] CONNECT upstream failed %s: %s", target, exc)
            _send_error(client_sock, 502, "Bad Gateway")
            return
        try:
            client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        except OSError:
            upstream.close()
            return
        _relay(client_sock, upstream)

    # -- Plain HTTP proxy ------------------------------------------------------

    def _handle_plain_http(
        self,
        client_sock: socket.socket,
        method: str,
        url: str,
        header_lines: list,
        leftover: bytes,
    ) -> None:
        """Handle plain HTTP proxy request."""
        if url.startswith("http://"):
            rest = url[7:]
        elif url.startswith("https://"):
            rest = url[8:]
        else:
            _send_error(client_sock, 400, "Bad Request")
            return
        slash = rest.find("/")
        host_port = rest[:slash] if slash != -1 else rest
        path = rest[slash:] if slash != -1 else "/"
        if ":" in host_port:
            h, _, p = host_port.rpartition(":")
            try:
                port = int(p)
            except ValueError:
                _send_error(client_sock, 400, "Bad Request")
                return
            host = h or host_port
        else:
            host = host_port
            port = 80
        try:
            upstream = self._open_validated_upstream(host, port)
        except ProxyDenied as exc:
            logger.debug("[policy_proxy] HTTP denied %s:%d: %s", host, port, exc)
            _send_error(client_sock, 403, "Forbidden")
            return
        except OSError as exc:
            logger.debug("[policy_proxy] HTTP upstream failed %s:%d: %s", host, port, exc)
            _send_error(client_sock, 502, "Bad Gateway")
            return
        try:
            clean = _clean_headers(header_lines)
            req = (
                f"{method} {path} HTTP/1.1\r\n".encode("latin-1")
                + b"\r\n".join(clean)
                + b"\r\n\r\n"
            )
            if leftover:
                req += leftover
            upstream.sendall(req)
            _relay(client_sock, upstream)
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    # -- Validation and upstream connection -----------------------------------

    def _open_validated_upstream(self, host: str, port: int) -> socket.socket:
        """Resolve *host*, validate ALL addresses, connect to the first validated IP.

        Security invariant: the addr_info entry used for socket.connect() is the
        same one that passed validation.  No second DNS resolution occurs between
        validation and connection, eliminating the TOCTOU gap.

        Raises:
            ProxyDenied: DNS fails, or any resolved address is in a blocked range.
            OSError: TCP connection to the upstream fails.
        """
        try:
            addr_infos = socket.getaddrinfo(
                host, port,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as exc:
            raise ProxyDenied(f"DNS resolution failed for {host!r}: {exc}") from exc
        if not addr_infos:
            raise ProxyDenied(f"DNS returned no addresses for {host!r}")
        # Fail-closed: reject if ANY resolved address is blocked
        for _fam, _typ, _pro, _can, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            if _is_blocked_ip(ip_str, allow_test_loopback=self._allow_test_loopback):
                raise ProxyDenied(
                    f"Destination {host!r} resolved to blocked address ({ip_str}); "
                    f"connection rejected to prevent SSRF"
                )
        # All addresses passed -- connect using first validated entry (same object)
        family, socktype, proto, _, sockaddr = addr_infos[0]
        upstream = socket.socket(family, socktype, proto)
        upstream.settimeout(_CONNECT_TIMEOUT)
        try:
            upstream.connect(sockaddr)
        except OSError:
            upstream.close()
            raise
        upstream.settimeout(None)
        logger.debug("[policy_proxy] allowed %s:%d -> %s", host, port, sockaddr[0])
        return upstream


# -- Helpers ------------------------------------------------------------------

def _send_error(sock: socket.socket, code: int, message: str) -> None:
    """Send a minimal HTTP error response.  Never raises."""
    body = f"{code} {message}".encode()
    resp = (
        f"HTTP/1.1 {code} {message}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Content-Type: text/plain\r\n"
        f"\r\n"
    ).encode() + body
    try:
        sock.sendall(resp)
    except Exception:
        pass


def _clean_headers(lines: list) -> list:
    """Strip proxy-specific and hop-by-hop headers.

    Does not log or inspect Authorization, Cookie, or other credential headers.
    """
    skip = (b"proxy-", b"connection:", b"keep-alive:", b"transfer-encoding:")
    result = []
    for line in lines:
        if not line.strip():
            continue
        if any(line.lower().startswith(p) for p in skip):
            continue
        result.append(line)
    return result


def _relay(sock_a: socket.socket, sock_b: socket.socket) -> None:
    """Relay bytes bidirectionally until either side closes or idle timeout.

    Closes both sockets on exit.
    """
    sock_a.setblocking(False)
    sock_b.setblocking(False)
    sel = selectors.DefaultSelector()
    try:
        sel.register(sock_a, selectors.EVENT_READ, data=sock_b)
        sel.register(sock_b, selectors.EVENT_READ, data=sock_a)
        while True:
            events = sel.select(timeout=_SELECT_TIMEOUT)
            if not events:
                break
            for key, _ in events:
                src: socket.socket = key.fileobj  # type: ignore[assignment]
                dst: socket.socket = key.data
                try:
                    data = src.recv(_RELAY_CHUNK)
                except OSError:
                    data = b""
                if not data:
                    return
                try:
                    dst.sendall(data)
                except OSError:
                    return
    finally:
        sel.close()
        for s in (sock_a, sock_b):
            try:
                s.close()
            except Exception:
                pass
