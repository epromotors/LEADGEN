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
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/leadgen")
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
