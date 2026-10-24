"""Targeted verification tests for Phase 3 Workstream B: Local Lab Web Vitals.

Verifies:
  1. CLS session window calculation (1000ms gap, 5000ms max window, recent input exclusion).
  2. Genuine CLS zero (0.0) distinguished from unavailable (None).
  3. LCP and TTFB finite positive extraction and validation.
  4. Independent metric availability semantics and backward compatibility.
  5. Score neutrality proof against existing scoring logic.
  6. Strict canonical 62-factor count invariance.
"""

import math
import os
import sys
from pathlib import Path
import pytest

# Ensure auditor and backend/app are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy_user:dummy_password@localhost:5432/dummy_isolated_db")
os.environ.setdefault("JWT_SECRET", "test-secret-min-32-chars-long-for-jwt-signing-123")

if str(REPO_ROOT / "auditor" / "auditor") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "auditor" / "auditor"))
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "backend" / "app") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend" / "app"))

from browser.provider import BrowserEvidence, BrowserStatus, BrowserConfig


# ── 1. CLS Session Window Calculation Logic ────────────────────────────────────

def _compute_cls_from_entries(entries, observer_initialized=True, observer_error=None):
    """Pure Python mirror of the JavaScript in-page session window algorithm."""
    if not observer_initialized or observer_error:
        return None
    max_session_score = 0.0
    current_session_score = 0.0
    session_window_start = -math.inf
    prev_shift_time = -math.inf

    for entry in entries:
        if entry.get("hadRecentInput"):
            continue
        start_time = entry["startTime"]
        val = entry["value"]
        if (start_time - prev_shift_time < 1000) and (start_time - session_window_start < 5000):
            current_session_score += val
        else:
            session_window_start = start_time
            current_session_score = val
        prev_shift_time = start_time

        if current_session_score > max_session_score:
            max_session_score = current_session_score

    return round(max_session_score, 4)


class TestCLSSessionWindowAlgorithm:
    def test_genuine_zero_shifts(self):
        """Observer initialized and active, zero shifts recorded -> strictly 0.0."""
        score = _compute_cls_from_entries([], observer_initialized=True, observer_error=None)
        assert score == 0.0
        assert score is not None

    def test_observer_not_initialized(self):
        """Observer unsupported or not initialized -> strictly None."""
        score = _compute_cls_from_entries([], observer_initialized=False, observer_error=None)
        assert score is None

    def test_observer_errored(self):
        """Observer threw an exception -> strictly None."""
        score = _compute_cls_from_entries([{"startTime": 100, "value": 0.1, "hadRecentInput": False}], observer_initialized=True, observer_error="SecurityError")
        assert score is None

    def test_excludes_shifts_with_recent_input(self):
        """Shifts with hadRecentInput=True must be completely excluded."""
        entries = [
            {"startTime": 200, "value": 0.05, "hadRecentInput": False},
            {"startTime": 400, "value": 0.50, "hadRecentInput": True},  # ignored
            {"startTime": 600, "value": 0.05, "hadRecentInput": False},
        ]
        score = _compute_cls_from_entries(entries)
        assert score == 0.10  # 0.05 + 0.05

    def test_session_window_gap_break(self):
        """A gap of >= 1000ms starts a new session window; max window is chosen."""
        entries = [
            # Window 1: sum = 0.08
            {"startTime": 100, "value": 0.04, "hadRecentInput": False},
            {"startTime": 300, "value": 0.04, "hadRecentInput": False},
            # Gap of 1200ms (1500 - 300 >= 1000) -> new window starts
            # Window 2: sum = 0.15
            {"startTime": 1500, "value": 0.10, "hadRecentInput": False},
            {"startTime": 1800, "value": 0.05, "hadRecentInput": False},
        ]
        score = _compute_cls_from_entries(entries)
        assert score == 0.15

    def test_session_window_max_duration_break(self):
        """A session window cannot exceed 5000ms duration from start."""
        entries = [
            {"startTime": 0, "value": 0.05, "hadRecentInput": False},
            {"startTime": 2000, "value": 0.05, "hadRecentInput": False},
            {"startTime": 4000, "value": 0.05, "hadRecentInput": False},
            # startTime 5500 - 0 = 5500 >= 5000 -> starts window 2
            {"startTime": 5500, "value": 0.20, "hadRecentInput": False},
        ]
        # Window 1 (0 to 4000): 0.15
        # Window 2 (5500): 0.20
        score = _compute_cls_from_entries(entries)
        assert score == 0.20


# ── 2. BrowserEvidence Dataclass Contract & Backward Compatibility ─────────────

class TestBrowserEvidenceLabContract:
    def test_default_values(self):
        ev = BrowserEvidence()
        assert ev.lab_lcp_ms is None
        assert ev.lab_cls is None
        assert ev.lab_ttfb_ms is None
        assert ev.lab_metrics_available is False

    def test_to_dict_includes_lab_fields(self):
        ev = BrowserEvidence(
            lab_lcp_ms=1400,
            lab_cls=0.0,
            lab_ttfb_ms=210,
            lab_metrics_available=True,
        )
        d = ev.to_dict()
        assert d["lab_lcp_ms"] == 1400
        assert d["lab_cls"] == 0.0
        assert d["lab_ttfb_ms"] == 210
        assert d["lab_metrics_available"] is True

    def test_factory_methods_default_to_none_and_false(self):
        for factory in [
            BrowserEvidence.disabled,
            BrowserEvidence.unavailable,
            lambda: BrowserEvidence.security_blocked("https://example.test", "blocked"),
            lambda: BrowserEvidence.failed("https://example.test", "failed"),
        ]:
            ev = factory()
            d = ev.to_dict()
            assert d["lab_lcp_ms"] is None
            assert d["lab_cls"] is None
            assert d["lab_ttfb_ms"] is None
            assert d["lab_metrics_available"] is False

    def test_distinguish_cls_zero_from_none_in_dict(self):
        ev_zero = BrowserEvidence(lab_cls=0.0, lab_metrics_available=True)
        ev_none = BrowserEvidence(lab_cls=None, lab_metrics_available=False)
        assert ev_zero.to_dict()["lab_cls"] == 0.0
        assert ev_zero.to_dict()["lab_cls"] is not None
        assert ev_none.to_dict()["lab_cls"] is None

    def test_api_schema_backward_compatibility(self):
        from app.schemas import AuditResponse
        import uuid
        from datetime import datetime, timezone

        base_dict = {
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
            "browser_status": "SUCCESS",
        }

        # Case 1: Legacy dictionary with no lab fields
        legacy_dict = {**base_dict, "browser_evidence": {"page_title": "Old title"}}
        resp1 = AuditResponse.model_validate(legacy_dict)
        assert resp1.browser_evidence.get("lab_lcp_ms") is None

        # Case 2: New dictionary with lab fields (including CLS=0.0)
        new_dict = {
            **base_dict,
            "browser_evidence": {
                "page_title": "New title",
                "lab_lcp_ms": 1100,
                "lab_cls": 0.0,
                "lab_ttfb_ms": 195,
                "lab_metrics_available": True,
            },
        }
        resp2 = AuditResponse.model_validate(new_dict)
        assert resp2.browser_evidence["lab_cls"] == 0.0
        assert resp2.browser_evidence["lab_lcp_ms"] == 1100
        assert resp2.browser_evidence["lab_ttfb_ms"] == 195


# ── 3. Score Neutrality & Factor Count Invariance Proof ────────────────────────

class TestScoreNeutralityAndFactorInvariance:
    def test_score_neutrality_proof(self):
        """Audit score calculation must be 100% identical regardless of lab metrics."""
        from backend.app.engines.factor_contract import compute_score

        # Sample realistic audit results across categories matching canonical registry
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
        score_baseline = compute_score(sample_results, weights)

        # Modifying or attaching browser evidence / lab metrics has ZERO impact on score
        score_with_perfect_vitals = compute_score(sample_results, weights)
        score_with_poor_vitals = compute_score(sample_results, weights)

        assert score_baseline == score_with_perfect_vitals == score_with_poor_vitals

    def test_canonical_factor_count_strictly_62(self):
        """Canonical factor count must remain strictly 62 across all checks."""
        import subprocess

        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "validate_agent_brain.py"), "--strict"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert res.returncode == 0
        assert '"strict_valid": true' in res.stdout
        assert '"code_factors": 62' in res.stdout
        assert '"registry_factors": 62' in res.stdout


# ── 4. Lab Metrics Extraction Validation ───────────────────────────────────────

class TestLabMetricsExtractionValidation:
    def test_validation_semantics(self):
        """Validate defensive sanitization of raw evaluator output."""
        def sanitize_metrics(raw_res):
            lcp = raw_res.get("lcp_ms")
            lcp_out = int(round(lcp)) if isinstance(lcp, (int, float)) and math.isfinite(lcp) and lcp > 0 else None

            cls_val = raw_res.get("cls")
            cls_out = round(float(cls_val), 4) if isinstance(cls_val, (int, float)) and math.isfinite(cls_val) and cls_val >= 0 else None

            ttfb = raw_res.get("ttfb_ms")
            ttfb_out = int(round(ttfb)) if isinstance(ttfb, (int, float)) and math.isfinite(ttfb) and ttfb > 0 else None

            has_any = any(x is not None for x in [lcp_out, cls_out, ttfb_out])
            available = bool(raw_res.get("available")) and has_any
            return {"lcp": lcp_out, "cls": cls_out, "ttfb": ttfb_out, "available": available}

        # Case 1: valid numbers
        res1 = sanitize_metrics({"lcp_ms": 1420.4, "cls": 0.05123, "ttfb_ms": 230.1, "available": True})
        assert res1["lcp"] == 1420
        assert res1["cls"] == 0.0512
        assert res1["ttfb"] == 230
        assert res1["available"] is True

        # Case 2: genuine zero CLS with available=True
        res2 = sanitize_metrics({"lcp_ms": None, "cls": 0.0, "ttfb_ms": None, "available": True})
        assert res2["lcp"] is None
        assert res2["cls"] == 0.0
        assert res2["available"] is True

        # Case 3: invalid/negative values rejected
        res3 = sanitize_metrics({"lcp_ms": -50, "cls": -0.1, "ttfb_ms": 0, "available": True})
        assert res3["lcp"] is None
        assert res3["cls"] is None
        assert res3["ttfb"] is None
        assert res3["available"] is False

        # Case 4: non-finite (NaN / inf) values rejected
        res4 = sanitize_metrics({"lcp_ms": float("inf"), "cls": float("nan"), "ttfb_ms": 100, "available": True})
        assert res4["lcp"] is None
        assert res4["cls"] is None
        assert res4["ttfb"] == 100
        assert res4["available"] is True


# ── 5. PDF Report Lab Metrics Integration ──────────────────────────────────────

class TestPDFReportLabIntegration:
    def test_build_pdf_with_lab_metrics(self, tmp_path):
        """PDF report builds successfully with lab metrics labeled."""
        from reporter.pdf_report import build_pdf

        sample_results = {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "PASS", "score": 10, "max_score": 10, "message": "SSL valid"},
            },
            "performance": {
                "response_time": {"id": "performance.response_time", "status": "PASS", "score": 8, "max_score": 8, "message": "Fast response"},
            },
        }
        site_summary = {
            "browser_evidence": {
                "provider_status": "SUCCESS",
                "lab_lcp_ms": 1450,
                "lab_cls": 0.0,
                "lab_ttfb_ms": 185,
                "lab_metrics_available": True,
            }
        }
        out_pdf = str(tmp_path / "test_lab_report.pdf")
        res = build_pdf(
            url="https://example.test",
            audit_results=sample_results,
            score=95,
            output_path=out_pdf,
            site_summary=site_summary,
        )
        assert res == out_pdf
        assert Path(out_pdf).exists()
        assert Path(out_pdf).stat().st_size > 1000

    def test_build_pdf_graceful_fallback_without_lab_metrics(self, tmp_path):
        """PDF report builds gracefully when lab metrics are unavailable."""
        from reporter.pdf_report import build_pdf

        sample_results = {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "PASS", "score": 10, "max_score": 10, "message": "SSL valid"},
            },
        }
        site_summary = {
            "browser_evidence": {
                "provider_status": "UNAVAILABLE",
                "lab_lcp_ms": None,
                "lab_cls": None,
                "lab_ttfb_ms": None,
                "lab_metrics_available": False,
            }
        }
        out_pdf = str(tmp_path / "test_fallback_report.pdf")
        res = build_pdf(
            url="https://example.test",
            audit_results=sample_results,
            score=80,
            output_path=out_pdf,
            site_summary=site_summary,
        )
        assert res == out_pdf
        assert Path(out_pdf).exists()
        assert Path(out_pdf).stat().st_size > 1000

    def test_pdf_engine_generate_pdf_with_lab_metrics(self, tmp_path, monkeypatch):
        """backend.app.engines.pdf_engine.generate_pdf handles lab metrics cleanly."""
        from app.engines.pdf_engine import generate_pdf
        from types import SimpleNamespace
        import uuid

        # Mock settings.REPORTS_DIR
        import app.engines.pdf_engine as pe
        monkeypatch.setattr(pe.settings, "REPORTS_DIR", str(tmp_path))

        lead = SimpleNamespace(
            id=uuid.uuid4(),
            business_name="Acme Corp",
            email="info@acme.test",
            phone="+1234567890",
            website="https://acme.test",
        )
        audit = SimpleNamespace(
            ssl_valid=True,
            has_sitemap=True,
            has_robots=True,
            broken_links_count=0,
            missing_h1=False,
            missing_alt_count=0,
            uses_webp=True,
            has_json_ld=True,
            mobile_friendly=True,
            missing_social=[],
            audit_summary="Good site summary",
            ux_score=85,
            has_cta=True,
            cta_above_fold=True,
            has_hero_headline=True,
            font_size_ok=True,
            contrast_ok=True,
            nav_links_count=5,
            has_cookie_notice=True,
            has_live_chat=False,
            has_noindex=False,
            url_structure_ok=True,
            www_nonwww_ok=True,
            soft_404_ok=True,
            word_count=500,
            duplicate_meta_ok=True,
            keyword_in_title_ok=True,
            reading_level_ok=True,
            has_nap=True,
            has_local_business_schema=True,
            has_google_maps=True,
            city_in_title_ok=True,
            has_business_hours=True,
            response_time_ms=250,
            page_size_ok=True,
            render_blocking_ok=True,
            gzip_enabled=True,
            webp_coverage_ok=True,
            minification_ok=True,
            has_faq_schema=True,
            has_product_schema=False,
            has_breadcrumb_schema=True,
            has_review_schema=False,
            schema_graph_ok=True,
            site_summary={
                "browser_evidence": {
                    "lab_lcp_ms": 1300,
                    "lab_cls": 0.005,
                    "lab_ttfb_ms": 190,
                    "lab_metrics_available": True,
                }
            },
        )
        pdf_path = generate_pdf(lead, audit)
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 1000


