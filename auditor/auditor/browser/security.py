"""URL security validation for browser evidence provider.

This module provides pre-navigation URL checks for the browser provider:
  - Protocol allowlist (only http:// and https://)
  - IP address category blocking (loopback, private, link-local, reserved)
  - DNS resolution and resolved-address validation
  - Redirect/navigation destination revalidation

A pre-navigation check alone is insufficient because a public DNS entry can
point to a private IP (DNS rebinding) or a redirect can lead into the internal
network.  All callers must invoke validate_url() before every navigation and
revalidate after each redirect.

Residual limitations are documented in the function docstrings and in the
Phase 2 snapshot.  No claim of perfect SSRF prevention is made.

Design note: this module uses only Python stdlib to avoid a hard dependency on
third-party libraries for the security path.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Allowlisted URL schemes ────────────────────────────────────────────────────
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# ── Blocked IP network ranges ─────────────────────────────────────────────────
# These are the ranges we must block to prevent SSRF.
_BLOCKED_NETWORKS = [
    # Loopback
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    # Private (RFC 1918)
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # Link-local
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    # Unique local (IPv6)
    ipaddress.ip_network("fc00::/7"),
    # Documentation/reserved
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    # Multicast
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
    # Unspecified / "this" network
    ipaddress.ip_network("0.0.0.0/8"),
]

# Maximum redirect depth we track internally (Playwright follows its own
# redirects; we validate the final URL again after navigation).
MAX_REDIRECT_DEPTH = 10


@dataclass(frozen=True)
class URLValidationResult:
    """Outcome of a URL security check."""
    allowed: bool
    reason: str
    resolved_ip: str | None = None


def _is_blocked_ip(addr: str) -> bool:
    """Return True if the resolved IP address is in a blocked range."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        logger.warning("URL security: could not parse IP address %r", addr)
        return True  # fail-closed: treat parse errors as blocked
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def validate_url(url: str, *, context: str = "pre-navigation") -> URLValidationResult:
    """Validate a URL against the SSRF/security policy.

    Checks performed:
      1. Scheme must be http or https.
      2. Hostname must resolve via DNS.
      3. All resolved IPs must be outside blocked ranges.

    Args:
        url:     The URL to validate (may be the redirected final URL).
        context: Human-readable label for log messages (e.g. "pre-navigation",
                 "post-redirect").

    Returns:
        URLValidationResult with allowed=True if all checks pass, or
        allowed=False with a reason string if any check fails.

    Residual limitations:
        - DNS resolution is performed by Python stdlib (getaddrinfo).  A site
          with a short TTL could in theory rebind between validation and
          Playwright's actual connection.  For stronger protection, a network-
          level firewall or Playwright's network intercept should additionally
          block private-range IPs at connection time.
        - We do not deep-inspect redirect chains inside Playwright's native
          navigation (Playwright follows http 3xx transparently).  The caller
          must call validate_url() with the final URL after navigation completes.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return URLValidationResult(allowed=False, reason=f"URL parse error: {exc}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return URLValidationResult(
            allowed=False,
            reason=f"[{context}] blocked scheme: {scheme!r} — only http/https allowed",
        )

    hostname = parsed.hostname
    if not hostname:
        return URLValidationResult(
            allowed=False,
            reason=f"[{context}] URL has no hostname",
        )

    # Reject raw IP literals that look private without DNS
    try:
        ip_literal = ipaddress.ip_address(hostname)
        if _is_blocked_ip(str(ip_literal)):
            return URLValidationResult(
                allowed=False,
                reason=f"[{context}] direct IP literal {hostname} is in a blocked range",
                resolved_ip=str(ip_literal),
            )
    except ValueError:
        pass  # not a raw IP literal — proceed to DNS resolution

    # DNS resolution (may raise on network error or NXDOMAIN)
    try:
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return URLValidationResult(
            allowed=False,
            reason=f"[{context}] DNS resolution failed for {hostname!r}: {exc}",
        )

    if not addr_infos:
        return URLValidationResult(
            allowed=False,
            reason=f"[{context}] DNS returned no addresses for {hostname!r}",
        )

    first_blocked: str | None = None
    for family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            first_blocked = ip_str
            break

    if first_blocked is not None:
        return URLValidationResult(
            allowed=False,
            reason=(
                f"[{context}] {hostname!r} resolves to a blocked address "
                f"({first_blocked}); navigation blocked to prevent SSRF"
            ),
            resolved_ip=first_blocked,
        )

    # All checks passed — record one resolved IP for the evidence record
    first_ip = addr_infos[0][4][0]
    return URLValidationResult(allowed=True, reason="ok", resolved_ip=first_ip)


def is_allowed_url(url: str, *, context: str = "pre-navigation") -> bool:
    """Convenience wrapper; returns True only when validate_url() allows."""
    result = validate_url(url, context=context)
    if not result.allowed:
        logger.warning("URL security check BLOCKED: %s", result.reason)
    return result.allowed
