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

Known architectural limitation — DNS rebinding TOCTOU gap
──────────────────────────────────────────────────────────
This module uses Python's socket.getaddrinfo() to resolve hostnames at check
time.  Chromium resolves hostnames independently at connection time.  If an
attacker controls a DNS server with a very short TTL, they can serve a public
IP during our check and then switch the DNS record to a private IP before
Chromium connects.  The route-handler validates URL strings (scheme + hostname)
but cannot intercept the TCP connection after Chromium resolves the hostname.

Severity: HIGH (architectural).  Practical prerequisite: attacker-controlled
DNS with TTL short enough to expire between our check and Chromium's resolution.

Mitigation options (not implemented — require infrastructure changes):
  1. Egress proxy that enforces destination-IP policy at the TCP layer.
  2. Custom DNS resolver shared between our check and Chromium (via --proxy-server
     pointing to a local policy-aware resolver).
  3. Network namespace or iptables rules that block RFC-1918/loopback at the OS
     level, removing the dependency on application-layer DNS validation.

Until one of the above mitigations is deployed, this property is NOT VERIFIED
for the DNS-rebinding TOCTOU scenario.  All other SSRF vectors (direct IP
literals, alternative numeric formats, pre-navigation hostname blocking, and
redirect-destination validation) are enforced at the application layer.

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
    # Unique local (IPv6)
    ipaddress.ip_network("fc00::/7"),
    # Carrier-grade NAT (RFC 6598)
    ipaddress.ip_network("100.64.0.0/10"),
    # Link-local
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    # Documentation/reserved
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("2001:db8::/32"),
    # Benchmarking
    ipaddress.ip_network("198.18.0.0/15"),
    # Multicast
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
    # Unspecified / "this" network
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),
    # Reserved for future use (Class E) / broadcast
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
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


def _parse_ip_literal(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse standard or alternative numeric IP representations (decimal, hex, octal)."""
    clean = hostname.strip().strip("[]")
    # 1. Standard IP string (e.g. 127.0.0.1, ::1, ::ffff:127.0.0.1)
    try:
        return ipaddress.ip_address(clean)
    except ValueError:
        pass

    # 2. Integer (decimal) representation, e.g. 2130706433
    if clean.isdigit():
        try:
            val = int(clean)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # 3. Hexadecimal single integer, e.g. 0x7f000001
    if clean.lower().startswith("0x"):
        try:
            val = int(clean, 16)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # 4. Dotted representations with octal/hex parts (e.g. 0177.0.0.1, 0x7f.0.0.1)
    parts = clean.split(".")
    if len(parts) == 4:
        try:
            octets = []
            for p in parts:
                p_lower = p.lower()
                if p_lower.startswith("0x"):
                    o = int(p_lower, 16)
                elif p.startswith("0") and len(p) > 1 and p.isdigit():
                    o = int(p, 8)
                else:
                    o = int(p)
                if not (0 <= o <= 255):
                    raise ValueError
                octets.append(o)
            return ipaddress.IPv4Address(bytes(octets))
        except (ValueError, TypeError):
            pass

    return None


def _is_blocked_ip(addr: str | ipaddress.IPv4Address | ipaddress.IPv6Address, allow_test_loopback: bool = False) -> bool:
    """Return True if the resolved IP address is in a blocked range."""
    if isinstance(addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        ip = addr
    else:
        try:
            ip = ipaddress.ip_address(str(addr).strip().strip("[]"))
        except ValueError:
            logger.warning("URL security: could not parse IP address %r", addr)
            return True  # fail-closed: treat parse errors as blocked

    # Extract mapped IPv4 if present (e.g. ::ffff:127.0.0.1 -> 127.0.0.1)
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped

    if allow_test_loopback and ip.is_loopback:
        return False

    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    for net in _BLOCKED_NETWORKS:
        try:
            if ip in net:
                return True
        except TypeError:
            continue
    return False


def validate_url(
    url: str,
    *,
    context: str = "pre-navigation",
    allow_test_loopback: bool = False,
) -> URLValidationResult:
    """Validate a URL against the SSRF/security policy.

    Checks performed:
      1. Scheme must be http or https.
      2. Hostname must resolve via DNS (or parse as a valid public IP literal).
      3. All resolved IPs must be outside blocked ranges.

    Args:
        url:                 The URL to validate (may be the redirected final URL).
        context:             Human-readable label for log messages.
        allow_test_loopback: If True, allows loopback connections (test fixtures only).

    Returns:
        URLValidationResult with allowed=True if all checks pass, or
        allowed=False with a reason string if any check fails.
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

    # Reject raw IP literals that look private / loopback without requiring DNS
    ip_literal = _parse_ip_literal(hostname)
    if ip_literal is not None:
        if _is_blocked_ip(ip_literal, allow_test_loopback=allow_test_loopback):
            return URLValidationResult(
                allowed=False,
                reason=f"[{context}] direct IP literal {hostname} is in a blocked range",
                resolved_ip=str(ip_literal),
            )
        # Safe public IP literal: no further DNS resolution needed
        return URLValidationResult(allowed=True, reason="ok", resolved_ip=str(ip_literal))

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
        if _is_blocked_ip(ip_str, allow_test_loopback=allow_test_loopback):
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


def is_allowed_url(url: str, *, context: str = "pre-navigation", allow_test_loopback: bool = False) -> bool:
    """Convenience wrapper; returns True only when validate_url() allows."""
    result = validate_url(url, context=context, allow_test_loopback=allow_test_loopback)
    if not result.allowed:
        logger.warning("URL security check BLOCKED: %s", result.reason)
    return result.allowed
