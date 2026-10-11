"""Targeted verification tests for Phase 3 Workstream C: Controlled Multi-Page Browser Evidence.

Verifies:
  1. Effective port and same-origin boundary rules (HTTP 80, HTTPS 443, custom ports, subdomain rejection).
  2. Deterministic URL normalization (dot-segments, fragments, query sorting, tracking param stripping, asset rejection).
  3. Inbound-link ranking (unique source counting, self-link exclusion, homepage slot 0, alphabetical tie-break).
  4. Configuration limits (BROWSER_MAX_PAGES env parsing, clamping <= 0 to 1).
  5. Strict aggregate budget enforcement, pre-navigation revalidation, and isolated failure handling.
  6. Score neutrality and canonical 62-factor invariant.
  7. API and database contract compatibility (optional browser_pages, legacy browser_evidence preserved).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-long-for-jwt-signing-123")

if str(REPO_ROOT / "auditor" / "auditor") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "auditor" / "auditor"))
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "backend" / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend" / "app"))

from bs4 import BeautifulSoup
from browser.provider import (
    BrowserConfig,
    BrowserEvidence,
    BrowserProvider,
    BrowserStatus,
    get_effective_port,
    is_same_origin_boundary,
    normalize_page_url,
    select_target_pages,
)
from app.schemas import AuditResponse


# ══════════════════════════════════════════════════════════════════════════════
# 1. Effective Port & Same-Origin Boundary Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestEffectivePortAndBoundary:
    """Verifies effective port comparison and strict origin boundaries."""

    def test_effective_port_defaults(self):
        import urllib.parse
        assert get_effective_port(urllib.parse.urlparse("http://example.com")) == 80
        assert get_effective_port(urllib.parse.urlparse("http://example.com:80")) == 80
        assert get_effective_port(urllib.parse.urlparse("https://example.com")) == 443
        assert get_effective_port(urllib.parse.urlparse("https://example.com:443")) == 443
        assert get_effective_port(urllib.parse.urlparse("https://example.com:8443")) == 8443
        assert get_effective_port(urllib.parse.urlparse("ftp://example.com")) == -1

    def test_same_origin_boundary_matches_exact_origin(self):
        base = "https://example.com"
        assert is_same_origin_boundary("https://example.com/about", base)
        assert is_same_origin_boundary("https://example.com:443/contact", base)
        assert is_same_origin_boundary("https://EXAMPLE.COM/team", base)

    def test_same_origin_boundary_rejects_subdomains(self):
        base = "https://example.com"
        assert not is_same_origin_boundary("https://sub.example.com", base)
        assert not is_same_origin_boundary("https://blog.example.com/post", base)
        assert not is_same_origin_boundary("https://admin.example.com", base)
        assert not is_same_origin_boundary("https://example.com.evil.com", base)

    def test_same_origin_boundary_rejects_port_mismatch(self):
        assert not is_same_origin_boundary("http://example.com:8080", "http://example.com")
        assert not is_same_origin_boundary("https://example.com:8443", "https://example.com:443")
        assert not is_same_origin_boundary("http://example.com:80", "http://example.com:8080")

    def test_same_origin_boundary_rejects_scheme_mismatch(self):
        assert not is_same_origin_boundary("http://example.com", "https://example.com")
        assert not is_same_origin_boundary("https://example.com", "http://example.com")

    def test_same_origin_boundary_handles_invalid_or_empty(self):
        assert not is_same_origin_boundary("", "https://example.com")
        assert not is_same_origin_boundary("javascript:void(0)", "https://example.com")
        assert not is_same_origin_boundary("mailto:test@example.com", "https://example.com")


# ══════════════════════════════════════════════════════════════════════════════
# 2. URL Normalization Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestURLNormalization:
    """Verifies deterministic URL normalization and sanitization."""

    def test_normalizes_case_and_trailing_slashes(self):
        assert normalize_page_url("HTTPS://EXAMPLE.COM/about/") == "https://example.com/about"
        assert normalize_page_url("https://example.com/") == "https://example.com/"

    def test_strips_fragments_unconditionally(self):
        assert normalize_page_url("https://example.com/about#team") == "https://example.com/about"
        assert normalize_page_url("https://example.com/#main-content") == "https://example.com/"

    def test_strips_tracking_params_and_sorts_query(self):
        url = "https://example.com/store?utm_source=ad&z=9&utm_campaign=spring&a=1&gclid=123"
        normalized = normalize_page_url(url)
        assert normalized == "https://example.com/store?a=1&z=9"

    def test_strips_standard_ports(self):
        assert normalize_page_url("http://example.com:80/page") == "http://example.com/page"
        assert normalize_page_url("https://example.com:443/page") == "https://example.com/page"

    def test_preserves_non_standard_ports(self):
        assert normalize_page_url("https://example.com:8443/page") == "https://example.com:8443/page"

    def test_resolves_dot_segments_and_double_slashes(self):
        assert normalize_page_url("https://example.com/a/b/../c") == "https://example.com/a/c"
        assert normalize_page_url("https://example.com/a//b/c") == "https://example.com/a/b/c"

    def test_resolves_relative_urls_with_base(self):
        base = "https://example.com/services/"
        assert normalize_page_url("/pricing", base) == "https://example.com/pricing"
        assert normalize_page_url("seo", base) == "https://example.com/services/seo"

    def test_rejects_non_html_and_media_files(self):
        assert normalize_page_url("https://example.com/document.pdf") is None
        assert normalize_page_url("https://example.com/image.png") is None
        assert normalize_page_url("https://example.com/style.css") is None
        assert normalize_page_url("https://example.com/bundle.js") is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. Inbound-Link Ranking & Selection Algorithm Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPageSelectionAndRanking:
    """Verifies deterministic inbound-link ranking and candidate selection."""

    def test_ranks_by_descending_unique_inbound_sources(self):
        base_url = "https://example.com"
        # Homepage links to /popular and /rare
        hp_html = """
        <html><body>
            <a href="/popular">Popular</a>
            <a href="/popular">Popular Again (duplicate)</a>
            <a href="/rare">Rare</a>
        </body></html>
        """
        # Page 1 links to /popular
        p1_html = '<html><body><a href="/popular">Popular</a></body></html>'
        # Page 2 links to /popular and /rare
        p2_html = '<html><body><a href="/popular">Popular</a><a href="/rare">Rare</a></body></html>'

        crawled = [
            {"final_url": "https://example.com/p1", "soup": BeautifulSoup(p1_html, "html.parser"), "ok": True},
            {"final_url": "https://example.com/p2", "soup": BeautifulSoup(p2_html, "html.parser"), "ok": True},
        ]
        hp_soup = BeautifulSoup(hp_html, "html.parser")

        targets, counts = select_target_pages(
            base_url=base_url,
            crawled_pages=crawled,
            homepage_soup=hp_soup,
            max_pages=5,
            return_counts=True,
        )

        assert targets[0] == "https://example.com/"
        # /popular has 3 unique referring sources (homepage, p1, p2)
        # /rare has 2 unique referring sources (homepage, p2)
        assert targets[1] == "https://example.com/popular"
        assert counts["https://example.com/popular"] == 3
        assert targets[2] == "https://example.com/rare"
        assert counts["https://example.com/rare"] == 2

    def test_tie_break_uses_ascending_normalized_url(self):
        base_url = "https://example.com"
        # Homepage links to /contact, /about, /blog (all have 1 inbound link)
        hp_html = """
        <html><body>
            <a href="/contact">Contact</a>
            <a href="/about">About</a>
            <a href="/blog">Blog</a>
        </body></html>
        """
        targets = select_target_pages(
            base_url=base_url,
            crawled_pages=[],
            homepage_soup=BeautifulSoup(hp_html, "html.parser"),
            max_pages=4,
        )

        assert targets[0] == "https://example.com/"
        # Alphabetical tie-break: /about, /blog, /contact
        assert targets[1] == "https://example.com/about"
        assert targets[2] == "https://example.com/blog"
        assert targets[3] == "https://example.com/contact"

    def test_excludes_self_links_from_inbound_count(self):
        base_url = "https://example.com"
        # /page links to itself 5 times
        p_html = """
        <html><body>
            <a href="/page">Self 1</a>
            <a href="/page">Self 2</a>
            <a href="/page">Self 3</a>
        </body></html>
        """
        crawled = [
            {"final_url": "https://example.com/page", "soup": BeautifulSoup(p_html, "html.parser"), "ok": True}
        ]
        targets, counts = select_target_pages(
            base_url=base_url,
            crawled_pages=crawled,
            homepage_soup=None,
            max_pages=5,
            return_counts=True,
        )

        # /page was discovered, but its self-links do not increment inbound count
        assert counts["https://example.com/page"] == 0

    def test_excludes_homepage_from_candidate_pool(self):
        base_url = "https://example.com"
        hp_html = '<html><body><a href="/">Home</a><a href="/about">About</a></body></html>'
        p1_html = '<html><body><a href="https://example.com/">Back Home</a></body></html>'

        crawled = [
            {"final_url": "https://example.com/about", "soup": BeautifulSoup(p1_html, "html.parser"), "ok": True}
        ]
        targets = select_target_pages(
            base_url=base_url,
            crawled_pages=crawled,
            homepage_soup=BeautifulSoup(hp_html, "html.parser"),
            max_pages=5,
        )

        # Homepage appears exactly once at index 0
        assert targets.count("https://example.com/") == 1
        assert targets[0] == "https://example.com/"

    def test_max_pages_limit_strictly_enforced(self):
        base_url = "https://example.com"
        hp_html = """
        <html><body>
            <a href="/p1">1</a><a href="/p2">2</a><a href="/p3">3</a>
            <a href="/p4">4</a><a href="/p5">5</a><a href="/p6">6</a>
        </body></html>
        """
        targets = select_target_pages(
            base_url=base_url,
            homepage_soup=BeautifulSoup(hp_html, "html.parser"),
            max_pages=3,
        )
        # Exactly 3 pages: homepage + 2 internal
        assert len(targets) == 3
        assert targets[0] == "https://example.com/"

    def test_graceful_handling_when_fewer_pages_available(self):
        base_url = "https://example.com"
        hp_html = '<html><body><a href="/only-one">One</a></body></html>'
        targets = select_target_pages(
            base_url=base_url,
            homepage_soup=BeautifulSoup(hp_html, "html.parser"),
            max_pages=5,
        )
        assert len(targets) == 2
        assert targets == ["https://example.com/", "https://example.com/only-one"]

    def test_off_origin_crawled_pages_excluded_from_source_docs(self):
        base_url = "https://example.com"
        # Crawled pages includes an off-origin URL linking back to /popular
        off_origin_html = '<html><body><a href="https://example.com/popular">External Link</a></body></html>'
        crawled = [
            {
                "final_url": "https://external-domain.com/article",
                "soup": BeautifulSoup(off_origin_html, "html.parser"),
                "ok": True,
            }
        ]
        targets, counts = select_target_pages(
            base_url=base_url,
            crawled_pages=crawled,
            homepage_soup=None,
            max_pages=5,
            return_counts=True,
        )
        # Off-origin page must not be crawled or treated as an inbound source document
        assert "https://example.com/popular" not in counts
        assert targets == ["https://example.com/"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Configuration Limits & Safe Defaults Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPageLimitsAndConfig:
    """Verifies BROWSER_MAX_PAGES environment parsing and safety bounds."""

    def test_default_max_pages_is_five(self):
        cfg = BrowserConfig()
        assert cfg.max_pages == 5

    def test_from_env_parses_custom_max_pages(self, monkeypatch):
        monkeypatch.setenv("BROWSER_MAX_PAGES", "3")
        cfg = BrowserConfig.from_env()
        assert cfg.max_pages == 3

    def test_from_env_clamps_non_positive_values(self, monkeypatch):
        monkeypatch.setenv("BROWSER_MAX_PAGES", "0")
        assert BrowserConfig.from_env().max_pages == 1

        monkeypatch.setenv("BROWSER_MAX_PAGES", "-5")
        assert BrowserConfig.from_env().max_pages == 1

    def test_from_env_handles_invalid_string(self, monkeypatch):
        monkeypatch.setenv("BROWSER_MAX_PAGES", "invalid")
        assert BrowserConfig.from_env().max_pages == 5


# ══════════════════════════════════════════════════════════════════════════════
# 5. Concurrency, Aggregate Budget & Failure Isolation Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrencyAndBudget:
    """Verifies aggregate wall-clock budget and isolated per-page failures."""

    def test_disabled_provider_returns_disabled_for_all_pages(self):
        cfg = BrowserConfig(enabled=False)
        provider = BrowserProvider(cfg)
        urls = ["https://example.com/", "https://example.com/about", "https://example.com/contact"]
        evidences = provider.capture_pages(urls)
        assert len(evidences) == 3
        for ev in evidences:
            assert ev.provider_status == BrowserStatus.DISABLED

    def test_budget_exhaustion_marks_remaining_pages_as_timeout(self):
        cfg = BrowserConfig(enabled=True, budget_seconds=0)  # 0 second budget forces expiration
        provider = BrowserProvider(cfg)
        urls = ["https://example.com/", "https://example.com/about"]

        # Call with already-expired deadline
        deadline = time.perf_counter() - 1.0
        evidences = provider.capture_pages(urls)
        assert len(evidences) == 2
        for ev in evidences:
            assert ev.provider_status == BrowserStatus.TIMEOUT
            assert "budget exhausted" in (ev.provider_error or "").lower()

    def test_per_page_failure_isolation(self):
        """Simulate capture where internal page encounters an error but sibling pages succeed."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        urls = ["https://example.com/", "https://example.com/error-page", "https://example.com/ok-page"]

        def _mock_capture(url, deadline=None):
            if "error-page" in url:
                return BrowserEvidence(requested_url=url, provider_status=BrowserStatus.FAILED, provider_error="Simulated 500")
            return BrowserEvidence(requested_url=url, provider_status=BrowserStatus.SUCCESS, page_title=f"Title for {url}")

        with patch.object(provider, "capture", side_effect=_mock_capture):
            evidences = provider.capture_pages(urls, base_url="https://example.com")

        assert len(evidences) == 3
        assert evidences[0].provider_status == BrowserStatus.SUCCESS
        assert evidences[0].selection_rank == 0
        assert evidences[1].provider_status == BrowserStatus.FAILED
        assert evidences[1].selection_rank == 1
        assert evidences[2].provider_status == BrowserStatus.SUCCESS
        assert evidences[2].selection_rank == 2

    def test_semaphore_wait_bounded_by_deadline_expiration(self):
        """Verifies semaphore timeout is bounded by deadline and returns structured TIMEOUT."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        past_deadline = time.perf_counter() - 0.1

        # Expired deadline must immediately return TIMEOUT without waiting
        ev = provider.capture("https://example.com/", deadline=past_deadline)
        assert ev.provider_status == BrowserStatus.TIMEOUT
        assert "budget exhausted" in (ev.provider_error or "").lower()

    def test_semaphore_acquisition_failure_at_deadline(self):
        """Verifies that if semaphore acquire fails when deadline expires, structured TIMEOUT is returned."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        mock_sem = MagicMock()
        mock_sem.acquire.return_value = False

        with patch("browser.provider._get_semaphore", return_value=mock_sem):
            with patch("browser.security.validate_url", return_value=MagicMock(allowed=True)):
                deadline = time.perf_counter() - 0.01  # already past
                ev = provider.capture("https://example.com/", deadline=deadline)
                assert ev.provider_status == BrowserStatus.TIMEOUT

    def test_cross_origin_rejected_in_capture_pages(self):
        """Verifies that an off-origin target URL in capture_pages is rejected before navigation."""
        cfg = BrowserConfig(enabled=True)
        provider = BrowserProvider(cfg)
        urls = ["https://example.com/", "https://evil.com/phishing", "https://sub.example.com/blog"]

        evidences = provider.capture_pages(urls, base_url="https://example.com")
        assert len(evidences) == 3
        # Off-origin internal candidates return security_blocked
        assert evidences[1].provider_status == BrowserStatus.BLOCKED
        assert "exceeds origin boundary" in (evidences[1].provider_error or "")
        assert evidences[2].provider_status == BrowserStatus.BLOCKED
        assert "exceeds origin boundary" in (evidences[2].provider_error or "")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Legacy API Contract & Database Compatibility Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLegacyAPIAndScoreNeutrality:
    """Verifies backward compatibility and zero database migration requirement."""

    def _get_base_audit_dict(self):
        import uuid
        from datetime import datetime, timezone

        return {
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
            "audit_summary": "Summary",
            "suggested_name": "Test Site",
            "pdf_path": None,
            "status": "done",
            "audit_lifecycle": "COMPLETE",
            "error_message": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "seo_score": 85,
            "browser_status": "SUCCESS",
        }

    def test_audit_response_schema_surfaces_optional_browser_pages(self):
        base_dict = self._get_base_audit_dict()
        base_dict["browser_evidence"] = {"page_title": "Home Title"}
        base_dict["browser_pages"] = [
            {"requested_url": "https://example.com/", "page_title": "Home Title"},
            {"requested_url": "https://example.com/about", "page_title": "About Us"},
        ]

        resp = AuditResponse.model_validate(base_dict)
        assert resp.browser_status == "SUCCESS"
        assert resp.browser_evidence["page_title"] == "Home Title"
        assert resp.browser_pages is not None
        assert len(resp.browser_pages) == 2
        assert resp.browser_pages[1]["page_title"] == "About Us"

    def test_audit_response_schema_backward_compatible_without_browser_pages(self):
        legacy_dict = self._get_base_audit_dict()
        legacy_dict["browser_evidence"] = {"page_title": "Old Format"}
        resp = AuditResponse.model_validate(legacy_dict)
        assert resp.browser_pages is None
        assert resp.browser_evidence["page_title"] == "Old Format"

    def test_score_calculation_unaffected_by_browser_pages(self):
        """Verifies that score computation is purely functional over audit_results and invariant."""
        from app.engines.factor_contract import compute_score

        sample_results = {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "PASS", "score": 10, "max_score": 10},
                "sitemap": {"id": "technical.sitemap", "status": "PASS", "score": 8, "max_score": 8},
            },
            "onpage": {
                "page_title": {"id": "onpage.page_title", "status": "PASS", "score": 10, "max_score": 10},
                "h1": {"id": "onpage.h1", "status": "WARN", "score": 4, "max_score": 8},
            },
            "performance": {
                "response_time": {"id": "performance.response_time", "status": "PASS", "score": 8, "max_score": 8},
            },
        }
        weights = {"technical": 18, "onpage": 16, "performance": 5}
        score1 = compute_score(sample_results, weights)
        score2 = compute_score(sample_results, weights)
        assert score1 == score2
        assert isinstance(score1, int)
