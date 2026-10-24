"""
Email Verifier Service.

A multi-layer asynchronous email verification service implementing:
1. Syntax Validation (RFC 5322 compliance, length checks, character validation)
2. Typo Detection & Suggestions (Popular domain dictionary and distance matching)
3. Disposable Domain Detection (Zero-latency immutable blocklist)
4. DNS & MX Record Resolution with RFC 5321 A-record fallback
5. SSRF / Target Network Security Protection
6. Optional, permanently disabled-by-default SMTP mailbox and catch-all probing
"""

from __future__ import annotations
import asyncio
import datetime
import ipaddress
import logging
import re
import socket
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

import dns.asyncresolver
import dns.resolver
import dns.exception

try:
    from app.utils.email_constants import (
        normalize_domain,
        is_disposable_domain,
        suggest_domain_typo,
    )
except ImportError:
    from backend.app.utils.email_constants import (
        normalize_domain,
        is_disposable_domain,
        suggest_domain_typo,
    )

logger = logging.getLogger("email_verifier_service")

# RFC 5322 compliant regex for basic syntax validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

# Private / reserved network ranges for SSRF mitigation
PROHIBITED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),     # Carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local / Cloud metadata (169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),    # Private IPv4
    ipaddress.ip_network("192.0.0.0/24"),     # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),   # Private IPv4
    ipaddress.ip_network("198.18.0.0/15"),    # Benchmark tests
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),      # Multicast
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6
    ipaddress.ip_network("::1/128"),          # Loopback
    ipaddress.ip_network("fc00::/7"),         # Unique local
    ipaddress.ip_network("fe80::/10"),        # Link-local
    ipaddress.ip_network("ff00::/8"),         # Multicast
]


def is_safe_ip(ip_str: str) -> bool:
    """
    Validates whether an IP address is a safe public routeable destination.
    Rejects loopback, private, link-local, multicast, metadata, and reserved ranges.
    """
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False

    for network in PROHIBITED_NETWORKS:
        if ip in network:
            return False

    return True


@dataclass
class VerificationResult:
    email: str
    normalized_email: str
    status: str                         # valid | invalid | disposable | catch_all | risky | not_found | error | timeout | blocked
    is_sendable: bool
    score: int                          # 0 - 100
    syntax_ok: bool
    typo_suggestion: str | None = None
    is_disposable: bool = False
    has_mx: bool = False
    mx_records: list[str] = field(default_factory=list)
    smtp_check: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "not_checked",
            "code": None,
            "message": "SMTP probe disabled. Mailbox existence and delivery are not confirmed.",
            "mailbox_confirmed": False,
        }
    )
    is_catch_all: bool = False
    catch_all_status: str = "not_checked"  # not_checked | catch_all | not_catch_all | unknown
    exclusion_reason: str | None = None
    duration_ms: float = 0.0
    verified_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    mailbox_confirmed: bool = False
    diagnostic_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmailVerifierService:
    def __init__(
        self,
        dns_timeout_seconds: float = 4.0,
        cache_ttl_seconds: int = 300,
        max_dns_concurrency: int = 5,
    ):
        self.dns_timeout = dns_timeout_seconds
        self.cache_ttl = cache_ttl_seconds
        self._semaphore = asyncio.Semaphore(max_dns_concurrency)
        self._dns_cache: dict[str, tuple[float, list[str], bool]] = {}  # domain -> (timestamp, mx_list, has_mx)

    @property
    def smtp_enabled(self) -> bool:
        """SMTP mailbox probing is permanently disabled by policy."""
        return False

    def is_disposable_domain(self, domain: str) -> bool:
        """Helper delegating to the zero-latency immutable disposable domain checker."""
        return is_disposable_domain(domain)

    def validate_syntax(self, email: str | None) -> tuple[bool, str | None]:
        """
        Validates email syntax against RFC 5322 rules and length constraints.
        Returns (is_valid, failure_reason).
        """
        if not email or not isinstance(email, str):
            return False, "Email address is missing or empty"

        cleaned = email.strip()
        if len(cleaned) > 254:
            return False, "Email address exceeds maximum length of 254 characters"

        if "@" not in cleaned:
            return False, "Email address is missing '@' symbol"

        parts = cleaned.split("@")
        if len(parts) != 2:
            return False, "Email address contains multiple '@' symbols"

        local_part, domain_part = parts[0], parts[1]

        if not local_part:
            return False, "Email address local part is empty"
        if len(local_part) > 64:
            return False, "Email local part exceeds maximum length of 64 characters"
        if local_part.startswith(".") or local_part.endswith("."):
            return False, "Email local part cannot start or end with a dot"
        if ".." in local_part:
            return False, "Email local part cannot contain consecutive dots"

        if not domain_part:
            return False, "Email domain part is empty"
        if domain_part.startswith(".") or domain_part.endswith("."):
            return False, "Email domain cannot start or end with a dot"
        if "." not in domain_part:
            return False, "Email domain must contain at least one dot"
        if ".." in domain_part:
            return False, "Email domain cannot contain consecutive dots"

        if not EMAIL_REGEX.match(cleaned):
            return False, "Email format does not conform to RFC 5322 syntax"

        return True, None

    async def _resolve_mx(self, domain: str) -> list[str]:
        """
        Asynchronously resolves MX records for a domain, sorted by preference.
        """
        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = self.dns_timeout
        resolver.lifetime = self.dns_timeout

        try:
            answers = await resolver.resolve(domain, "MX")
            # Sort by priority/preference ascending
            sorted_records = sorted(answers, key=lambda r: r.preference)
            return [str(r.exchange).rstrip(".") for r in sorted_records]
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return []

    async def _resolve_a(self, domain: str) -> list[str]:
        """
        Asynchronously resolves A/AAAA records for RFC 5321 fallback.
        """
        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = self.dns_timeout
        resolver.lifetime = self.dns_timeout

        try:
            answers = await resolver.resolve(domain, "A")
            return [str(r.address) for r in answers]
        except Exception:
            return []

    async def _resolve_dns_cached(self, domain: str) -> tuple[list[str], bool, str | None]:
        """
        Resolves MX records with caching and A-record fallback.
        Returns (records_list, has_valid_records, error_string).
        """
        now = time.time()
        if domain in self._dns_cache:
            ts, records, has_mx = self._dns_cache[domain]
            if now - ts < self.cache_ttl:
                return records, has_mx, None

        async with self._semaphore:
            try:
                mx_records = await self._resolve_mx(domain)
                if mx_records:
                    self._dns_cache[domain] = (now, mx_records, True)
                    return mx_records, True, None

                # Fallback to A record
                a_records = await self._resolve_a(domain)
                if a_records:
                    fallback = [f"{a} (A-fallback)" for a in a_records]
                    self._dns_cache[domain] = (now, fallback, True)
                    return fallback, True, None

                return [], False, "No MX or A records found for domain"

            except dns.resolver.NXDOMAIN:
                return [], False, "Domain does not exist (NXDOMAIN)"
            except dns.exception.Timeout:
                return [], False, "DNS resolution timed out"
            except Exception as e:
                return [], False, f"DNS resolution error: {str(e)}"

    async def _probe_smtp_mailbox(
        self,
        domain: str,
        mx_host: str,
        email: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """
        Optional diagnostic SMTP mailbox probe.
        STRICT RULES:
        - Must remain behind explicit opt-in only.
        - Checks destination IP against SSRF blocklist before connecting.
        - Strict 5.0 second timeout.
        - Runs in asyncio.to_thread to avoid blocking the event loop.
        - Sends NO message content (only HELO -> MAIL FROM -> RCPT TO -> RSET/QUIT).
        """
        def _sync_probe() -> dict[str, Any]:
            # Step 1: Resolve MX host IP to ensure it's not a private/loopback destination
            try:
                ip_addr = socket.gethostbyname(mx_host)
            except Exception as e:
                return {"status": "error", "code": None, "message": f"MX host resolution failed: {e}"}

            if not is_safe_ip(ip_addr):
                return {"status": "blocked", "code": None, "message": f"SSRF blocked: IP {ip_addr} is private/reserved"}

            # Step 2: Connect socket with strict timeout
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                s.connect((ip_addr, 25))
                banner = s.recv(1024).decode("latin-1", errors="ignore")
                if not banner.startswith("220"):
                    s.close()
                    return {"status": "error", "code": None, "message": f"Invalid SMTP banner: {banner[:100]}"}

                # Step 3: HELO
                s.sendall(b"EHLO leadgen.verify\r\n")
                ehlo_resp = s.recv(1024).decode("latin-1", errors="ignore")
                if not (ehlo_resp.startswith("250") or ehlo_resp.startswith("220")):
                    s.sendall(b"HELO leadgen.verify\r\n")
                    s.recv(1024)

                # Step 4: MAIL FROM
                s.sendall(b"MAIL FROM:<verify@leadgen.local>\r\n")
                mf_resp = s.recv(1024).decode("latin-1", errors="ignore")
                if not mf_resp.startswith("250"):
                    s.sendall(b"QUIT\r\n")
                    s.close()
                    return {"status": "deferred", "code": 450, "message": f"MAIL FROM rejected: {mf_resp[:100]}"}

                # Step 5: RCPT TO
                s.sendall(f"RCPT TO:<{email}>\r\n".encode("latin-1"))
                rcpt_resp = s.recv(1024).decode("latin-1", errors="ignore")

                # Parse response code
                code = None
                try:
                    code = int(rcpt_resp[:3])
                except (ValueError, IndexError):
                    pass

                # Step 6: RSET and QUIT cleanup
                try:
                    s.sendall(b"RSET\r\nQUIT\r\n")
                except Exception:
                    pass
                s.close()

                if code == 250:
                    return {"status": "accepted", "code": 250, "message": rcpt_resp.strip()}
                elif code in (550, 551, 552, 553):
                    return {"status": "rejected", "code": code, "message": rcpt_resp.strip()}
                elif code in (421, 450, 451, 452):
                    return {"status": "deferred", "code": code, "message": rcpt_resp.strip()}
                else:
                    return {"status": "error", "code": code, "message": rcpt_resp.strip()}

            except socket.timeout:
                try:
                    s.close()
                except Exception:
                    pass
                return {"status": "timeout", "code": None, "message": "SMTP connection timed out"}
            except Exception as ex:
                try:
                    s.close()
                except Exception:
                    pass
                return {"status": "error", "code": None, "message": f"SMTP handshake error: {str(ex)}"}

        return await asyncio.to_thread(_sync_probe)

    async def verify_email(
        self,
        email: str | None,
        smtp_probe_enabled: bool = False,
        catch_all_probe_enabled: bool = False,
    ) -> VerificationResult:
        """
        Executes verification across all layers.
        SMTP and catch-all probing remain DISABLED BY DEFAULT.
        """
        start_time = time.perf_counter()

        # Layer 1: Syntax Validation
        is_syntax_valid, syntax_reason = self.validate_syntax(email)
        if not is_syntax_valid:
            return VerificationResult(
                email=str(email or ""),
                normalized_email=str(email or "").strip().lower(),
                status="invalid",
                is_sendable=False,
                score=0,
                syntax_ok=False,
                exclusion_reason=syntax_reason,
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        clean_email = email.strip()
        local_part, domain_raw = clean_email.split("@", 1)
        domain = normalize_domain(domain_raw)
        normalized_email = f"{local_part.lower()}@{domain}"

        # Layer 2: Typo Detection
        typo_domain = suggest_domain_typo(domain)
        typo_suggestion = f"{local_part}@{typo_domain}" if typo_domain else None

        # Layer 3: Disposable Domain Check
        is_disposable = is_disposable_domain(domain)
        if is_disposable:
            return VerificationResult(
                email=clean_email,
                normalized_email=normalized_email,
                status="disposable",
                is_sendable=False,
                score=10,
                syntax_ok=True,
                typo_suggestion=typo_suggestion,
                is_disposable=True,
                has_mx=False,
                exclusion_reason="Disposable email domain",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        # Layer 4: DNS / MX Lookup (with A-record fallback)
        mx_records, has_mx, dns_error = await self._resolve_dns_cached(domain)

        if not has_mx:
            status = "not_found"
            if dns_error and "timed out" in dns_error.lower():
                status = "timeout"
            elif dns_error and "NXDOMAIN" in dns_error:
                status = "not_found"
            else:
                status = "error" if dns_error else "not_found"

            return VerificationResult(
                email=clean_email,
                normalized_email=normalized_email,
                status=status,
                is_sendable=False,
                score=20,
                syntax_ok=True,
                typo_suggestion=typo_suggestion,
                is_disposable=False,
                has_mx=False,
                exclusion_reason=dns_error or "Domain has no valid MX or A records",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )

        # Layer 5: Optional SMTP Handshake (Disabled by default)
        smtp_res = {
            "status": "not_checked",
            "code": None,
            "message": "SMTP probe disabled. Mailbox existence and delivery are not confirmed.",
            "mailbox_confirmed": False,
        }
        smtp_exclusion: str | None = None

        if smtp_probe_enabled and mx_records:
            primary_mx = mx_records[0].split()[0]  # strip any (A-fallback) annotation
            smtp_res = await self._probe_smtp_mailbox(domain, primary_mx, normalized_email)
            if smtp_res.get("status") == "accepted":
                smtp_res["mailbox_confirmed"] = True
            elif smtp_res.get("status") == "rejected":
                smtp_res["mailbox_confirmed"] = False
                smtp_exclusion = f"Mailbox rejected by mail server (SMTP {smtp_res.get('code')})"
            else:
                smtp_res["mailbox_confirmed"] = False

        # Layer 6: Optional Catch-All Probe (Disabled by default)
        is_catch_all = False
        catch_all_status = "not_checked"

        if catch_all_probe_enabled and smtp_probe_enabled and mx_records and smtp_res.get("status") == "accepted":
            primary_mx = mx_records[0].split()[0]
            random_local = f"probe_{uuid.uuid4().hex[:12]}"
            random_email = f"{random_local}@{domain}"
            random_res = await self._probe_smtp_mailbox(domain, primary_mx, random_email)
            if random_res.get("status") == "accepted":
                is_catch_all = True
                catch_all_status = "catch_all"
            else:
                catch_all_status = "not_catch_all"

        # Determine overall status and sendability decision
        status = "valid"
        exclusion_reason: str | None = None

        if typo_suggestion:
            status = "risky"
            exclusion_reason = f"Potential domain typo; suggested: {typo_suggestion}"
        elif smtp_exclusion:
            status = "invalid"
            exclusion_reason = smtp_exclusion
        elif is_catch_all:
            status = "catch_all"
            exclusion_reason = "Domain is configured as catch-all / accept-all"

        # Deterministic Sendability Decision:
        # A lead is sendable ONLY if status is 'valid', syntax is ok, domain has MX/A, not disposable, and no uncorrected typo
        is_sendable = (
            status == "valid"
            and not is_disposable
            and has_mx
            and typo_suggestion is None
        )

        mailbox_confirmed = bool(smtp_res.get("mailbox_confirmed", False))

        # Calculate confidence score (0 - 100)
        # Without live SMTP mailbox probing, syntax + disposable + DNS checks establish domain routing readiness
        # but do NOT prove that this specific mailbox exists or will accept delivery.
        # Score is bounded to 85 max without live mailbox probe to avoid false 100% guarantees.
        score = 0
        if is_syntax_valid:
            score += 20
        if not typo_suggestion:
            score += 10
        if not is_disposable:
            score += 20
        if has_mx:
            score += 35   # Domain DNS/MX verified: total 85 without mailbox probe
        if mailbox_confirmed:
            score += 15   # Live SMTP mailbox accepted: reaches 100
        elif smtp_res.get("status") == "rejected":
            score = 0
        elif smtp_res.get("status") == "deferred":
            score = min(score, 60)

        # Diagnostic summary
        if status == "valid":
            if mailbox_confirmed:
                diagnostic_summary = "Syntax, DNS/MX, and recipient mailbox existence confirmed via live SMTP probe."
            else:
                diagnostic_summary = "Syntax and DNS/MX verified (domain is routeable). Mailbox existence not confirmed because SMTP probe is disabled."
        elif status == "disposable":
            diagnostic_summary = "Disposable email domain detected. Non-sendable."
        elif status == "risky":
            diagnostic_summary = f"Potential domain typo. Suggested: {typo_suggestion}."
        elif status in ("not_found", "timeout", "error"):
            diagnostic_summary = f"DNS resolution failed: {exclusion_reason}."
        else:
            diagnostic_summary = exclusion_reason or "Email failed verification."

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return VerificationResult(
            email=clean_email,
            normalized_email=normalized_email,
            status=status,
            is_sendable=is_sendable,
            score=score,
            syntax_ok=True,
            typo_suggestion=typo_suggestion,
            is_disposable=False,
            has_mx=True,
            mx_records=mx_records,
            smtp_check=smtp_res,
            is_catch_all=is_catch_all,
            catch_all_status=catch_all_status,
            exclusion_reason=exclusion_reason,
            duration_ms=duration_ms,
            mailbox_confirmed=mailbox_confirmed,
            diagnostic_summary=diagnostic_summary,
        )


# Global singleton instance for use across backend
email_verifier = EmailVerifierService()
