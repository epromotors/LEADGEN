import pytest
from backend.app.utils.email_constants import (
    DISPOSABLE_DOMAINS,
    POPULAR_DOMAINS,
    COMMON_TYPO_MAP,
    normalize_domain,
    is_disposable_domain,
    suggest_domain_typo,
)


def test_constants_structures():
    """Verify constants are immutable and properly structured."""
    assert isinstance(DISPOSABLE_DOMAINS, frozenset)
    assert len(DISPOSABLE_DOMAINS) > 300
    assert "mailinator.com" in DISPOSABLE_DOMAINS
    assert "10minutemail.com" in DISPOSABLE_DOMAINS
    assert "tempmail.com" in DISPOSABLE_DOMAINS
    assert "guerrillamail.com" in DISPOSABLE_DOMAINS

    assert isinstance(POPULAR_DOMAINS, (set, frozenset))
    assert "gmail.com" in POPULAR_DOMAINS
    assert "outlook.com" in POPULAR_DOMAINS
    assert "yahoo.com" in POPULAR_DOMAINS

    assert isinstance(COMMON_TYPO_MAP, dict)
    assert COMMON_TYPO_MAP.get("gmial.com") == "gmail.com"
    assert COMMON_TYPO_MAP.get("gamil.com") == "gmail.com"
    assert COMMON_TYPO_MAP.get("yaho.com") == "yahoo.com"
    assert COMMON_TYPO_MAP.get("outlok.com") == "outlook.com"


def test_normalize_domain():
    """Test domain normalization with whitespace, case, trailing dot, and IDN."""
    assert normalize_domain("  GMAIL.COM  ") == "gmail.com"
    assert normalize_domain("Yahoo.Com.") == "yahoo.com"
    assert normalize_domain("") == ""
    assert normalize_domain(None) == ""
    # Unicode / IDN handling
    assert normalize_domain("münchen.de") == "xn--mnchen-3ya.de"


def test_is_disposable_domain():
    """Test disposable domain detection including subdomains and casing."""
    assert is_disposable_domain("mailinator.com") is True
    assert is_disposable_domain("MAILINATOR.COM") is True
    assert is_disposable_domain("sub.mailinator.com") is True
    assert is_disposable_domain("deep.sub.10minutemail.com") is True
    assert is_disposable_domain("gmail.com") is False
    assert is_disposable_domain("microsoft.com") is False
    assert is_disposable_domain("") is False
    assert is_disposable_domain(None) is False
    assert is_disposable_domain("invalid..domain") is False


def test_suggest_domain_typo():
    """Test typo suggestions and avoidance of false positives."""
    # Direct dictionary match
    assert suggest_domain_typo("gmial.com") == "gmail.com"
    assert suggest_domain_typo("GMIAL.COM") == "gmail.com"
    assert suggest_domain_typo("yaho.com") == "yahoo.com"
    assert suggest_domain_typo("hotmial.com") == "hotmail.com"
    assert suggest_domain_typo("outlok.com") == "outlook.com"

    # Valid popular domains must never suggest a typo (no false positives)
    assert suggest_domain_typo("gmail.com") is None
    assert suggest_domain_typo("yahoo.com") is None
    assert suggest_domain_typo("outlook.com") is None
    assert suggest_domain_typo("icloud.com") is None

    # Unknown custom corporate domain should not suggest typo unless very close
    assert suggest_domain_typo("acmecorp.com") is None
    assert suggest_domain_typo("mycoolstartup.io") is None

    # Empty and invalid inputs
    assert suggest_domain_typo("") is None
    assert suggest_domain_typo(None) is None


def test_distance_based_typo_fallback():
    """Test distance-based fallback for typos not explicitly in dictionary."""
    # 'gmai.com' is in map, but let's test a single-letter deletion or swap that resolves
    assert suggest_domain_typo("outllok.com") == "outlook.com"
    assert suggest_domain_typo("gmeil.com") == "gmail.com"
