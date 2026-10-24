import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from backend.app.services.email_verifier_service import (
    EmailVerifierService,
    VerificationResult,
    is_safe_ip,
)


@pytest.fixture
def service():
    return EmailVerifierService(cache_ttl_seconds=60)


# ─── 1. Syntax Validation ───────────────────────────────────────────────────

def test_syntax_validation_valid(service):
    """Valid standard syntax should pass syntax check."""
    for email in ["test@example.com", "first.last@company.co.uk", "user+tag@domain.org"]:
        valid, reason = service.validate_syntax(email)
        assert valid is True
        assert reason is None


def test_syntax_validation_invalid(service):
    """Invalid emails must fail syntax check immediately."""
    invalid_cases = [
        "",
        None,
        "plainaddress",
        "@missinglocal.com",
        "missingat.com",
        "two@@signs.com",
        "space in@domain.com",
        "user@.leadingdot.com",
        "user@trailingdot.com.",
        ".leadingdot@domain.com",
        "trailingdot.@domain.com",
        "consecutive..dots@domain.com",
        "a" * 65 + "@domain.com",  # Local part > 64 chars
        "user@" + "a" * 250 + ".com",  # Total length > 254
    ]
    for email in invalid_cases:
        valid, reason = service.validate_syntax(email)
        assert valid is False
        assert reason is not None


# ─── 2. Typo Detection ───────────────────────────────────────────────────────

def test_typo_detection(service):
    """Typo suggestion identifies domain misspellings without false positives."""
    async def _test():
        res = await service.verify_email("john@gmial.com")
        assert res.typo_suggestion == "john@gmail.com"
        # Even if syntax passes, typo without verification is non-sendable
        assert res.is_sendable is False

        res_valid = await service.verify_email("john@gmail.com")
        assert res_valid.typo_suggestion is None

    asyncio.run(_test())


# ─── 3. Disposable Domain Detection ──────────────────────────────────────────

def test_disposable_domain(service):
    """Disposable email must be classified as disposable and non-sendable."""
    async def _test():
        res = await service.verify_email("fakeuser@mailinator.com")
        assert res.is_disposable is True
        assert res.status == "disposable"
        assert res.is_sendable is False
        assert res.exclusion_reason == "Disposable email domain"

    asyncio.run(_test())


# ─── 4. DNS / MX Resolution & Fallback ───────────────────────────────────────

def test_dns_mx_success(service):
    """Domain with valid MX records is marked with has_mx=True and valid status."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com", "mail2.example.com"]
            res = await service.verify_email("contact@example.com")
            assert res.has_mx is True
            assert res.mx_records == ["mail.example.com", "mail2.example.com"]
            assert res.status == "valid"
            assert res.is_sendable is True

    asyncio.run(_test())


def test_dns_mx_fallback_to_a_record(service):
    """RFC 5321: If no MX records, fallback to domain A record."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = []
            with patch.object(service, "_resolve_a", new_callable=AsyncMock) as mock_a:
                mock_a.return_value = ["93.184.216.34"]
                res = await service.verify_email("contact@example.com")
                assert res.has_mx is True  # fallback satisfied
                assert res.status == "valid"
                assert res.is_sendable is True
                assert res.mx_records == ["93.184.216.34 (A-fallback)"]

    asyncio.run(_test())


def test_dns_nxdomain(service):
    """NXDOMAIN should be classified as not_found and non-sendable."""
    async def _test():
        import dns.resolver
        with patch.object(service, "_resolve_mx", side_effect=dns.resolver.NXDOMAIN()):
            res = await service.verify_email("contact@nonexistent-domain-xyz123.org")
            assert res.has_mx is False
            assert res.status == "not_found"
            assert res.is_sendable is False
            assert "Domain does not exist" in res.exclusion_reason

    asyncio.run(_test())


def test_dns_timeout(service):
    """DNS timeout should be classified as error/timeout and non-sendable."""
    async def _test():
        import dns.exception
        with patch.object(service, "_resolve_mx", side_effect=dns.exception.Timeout()):
            res = await service.verify_email("contact@slow-domain.com")
            assert res.has_mx is False
            assert res.status == "timeout"
            assert res.is_sendable is False
            assert "DNS resolution timed out" in res.exclusion_reason

    asyncio.run(_test())


def test_dns_caching(service):
    """Second call for same domain must use cache and not invoke resolver twice."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.cached.com"]
            res1 = await service.verify_email("user1@cached.com")
            res2 = await service.verify_email("user2@cached.com")
            assert res1.has_mx is True
            assert res2.has_mx is True
            assert mock_mx.call_count == 1

    asyncio.run(_test())


# ─── 5. SSRF & Security IP Rejection ─────────────────────────────────────────

def test_is_safe_ip():
    """Verify SSRF protection filters out loopback, private, multicast, link-local, and reserved."""
    assert is_safe_ip("8.8.8.8") is True
    assert is_safe_ip("93.184.216.34") is True
    assert is_safe_ip("1.1.1.1") is True

    # Dangerous / local / private IPs
    assert is_safe_ip("127.0.0.1") is False
    assert is_safe_ip("127.0.0.2") is False
    assert is_safe_ip("10.0.0.1") is False
    assert is_safe_ip("172.16.0.1") is False
    assert is_safe_ip("192.168.1.1") is False
    assert is_safe_ip("169.254.169.254") is False  # AWS metadata service!
    assert is_safe_ip("0.0.0.0") is False
    assert is_safe_ip("255.255.255.255") is False
    assert is_safe_ip("::1") is False
    assert is_safe_ip("fe80::1") is False
    assert is_safe_ip("invalid_ip") is False


# ─── 6. Permanent Optionality: SMTP Disabled by Default ──────────────────────

def test_smtp_disabled_by_default(service):
    """SMTP checking must remain disabled by default and return not_checked without socket activity."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com"]
            with patch("socket.create_connection") as mock_conn:
                res = await service.verify_email("contact@example.com")
                # Socket connection must NEVER be attempted
                mock_conn.assert_not_called()
                assert res.smtp_check["status"] == "not_checked"
                assert res.catch_all_status == "not_checked"
                assert res.is_catch_all is False
                # Still valid and sendable based on syntax, domain, and DNS
                assert res.status == "valid"
                assert res.is_sendable is True

    asyncio.run(_test())


def test_smtp_enabled_explicitly_mocked(service):
    """When explicitly enabled with opt-in, executes diagnostic check."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com"]
            with patch.object(service, "_probe_smtp_mailbox", new_callable=AsyncMock) as mock_probe:
                mock_probe.return_value = {
                    "status": "accepted",
                    "code": 250,
                    "message": "OK Mailbox exists",
                }
                res = await service.verify_email(
                    "contact@example.com",
                    smtp_probe_enabled=True,
                    catch_all_probe_enabled=False,
                )
                mock_probe.assert_called_once()
                assert res.smtp_check["status"] == "accepted"
                assert res.smtp_check["code"] == 250
                assert res.status == "valid"
                assert res.is_sendable is True

    asyncio.run(_test())


def test_smtp_rejected_mocked(service):
    """When SMTP is explicitly enabled and rejects recipient (550), marks invalid."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com"]
            with patch.object(service, "_probe_smtp_mailbox", new_callable=AsyncMock) as mock_probe:
                mock_probe.return_value = {
                    "status": "rejected",
                    "code": 550,
                    "message": "User unknown",
                }
                res = await service.verify_email("invalid-user@example.com", smtp_probe_enabled=True)
                assert res.smtp_check["status"] == "rejected"
                assert res.status == "invalid"
                assert res.is_sendable is False
                assert "Mailbox rejected by mail server" in res.exclusion_reason

    asyncio.run(_test())


def test_catch_all_detected_mocked(service):
    """When catch-all probe is enabled and random mailbox accepted, marks catch_all."""
    async def _test():
        with patch.object(service, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = ["mail.example.com"]
            with patch.object(service, "_probe_smtp_mailbox", new_callable=AsyncMock) as mock_probe:
                # First call is target email (accepted), second call is random probe (accepted -> catch-all)
                mock_probe.side_effect = [
                    {"status": "accepted", "code": 250, "message": "OK"},
                    {"status": "accepted", "code": 250, "message": "OK Catch-All"},
                ]
                res = await service.verify_email(
                    "contact@example.com",
                    smtp_probe_enabled=True,
                    catch_all_probe_enabled=True,
                )
                assert res.is_catch_all is True
                assert res.catch_all_status == "catch_all"
                assert res.status == "catch_all"
                assert res.is_sendable is False
                assert "catch-all" in res.exclusion_reason.lower()

    asyncio.run(_test())


def test_unexpected_exception_never_sendable(service):
    """Any unexpected exception must never produce a sendable result."""
    async def _test():
        with patch.object(service, "_resolve_dns_cached", side_effect=RuntimeError("Unexpected crash")):
            with pytest.raises(RuntimeError):
                await service.verify_email("contact@example.com")

    asyncio.run(_test())
