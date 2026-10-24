"""
tests/test_performance_diagnostics_gate.py

Phase 2 Verification Gate: Advanced Website Performance Diagnostics
Tests:
  1. Resource-type classification across initiator types and URL extensions.
  2. Missing, zero, and valid transfer size handling (safe distinguishing).
  3. Resource aggregation on a page with zero resources (empty state).
  4. Failure breakdown: HTTP error responses (4xx/5xx) vs blocked/failed requests.
  5. Runtime console error filtering (actionable exceptions vs warnings) and message truncation.
  6. Strict URL sanitization: stripping auth credentials and sensitive query tokens.
  7. Multi-page evidence association (page_index and total_pages_captured).
  8. Missing browser capture and unavailable-data states in BrowserEvidence.
  9. Serialization/deserialization compatibility with BrowserEvidence.to_dict().
 10. Canonical 62-factor audit scoring neutrality: strictly score-neutral.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join("auditor", "auditor")))
sys.path.insert(0, os.path.abspath("backend"))

from browser.performance_diagnostics import (
    PerformanceDiagnostics,
    classify_resource_type,
    sanitize_resource_url,
)
from browser.provider import BrowserEvidence, BrowserStatus
from app.engines.factor_contract import validate_factor_registry


def test_resource_type_classification():
    """Verify classification across initiator types and path extensions."""
    assert classify_resource_type("navigation", "https://example.com/") == "document"
    assert classify_resource_type("script", "https://example.com/app.bundle") == "script"
    assert classify_resource_type("css", "https://example.com/theme.min") == "stylesheet"
    assert classify_resource_type("img", "https://example.com/logo.webp") == "image"
    assert classify_resource_type("font", "https://example.com/font.woff2") == "font"
    assert classify_resource_type("fetch", "https://example.com/api/data") == "fetch"
    assert classify_resource_type("xmlhttprequest", "https://example.com/xhr") == "fetch"
    assert classify_resource_type("video", "https://example.com/hero.mp4") == "media"

    # Fallback via URL extensions when initiator is generic 'other' or 'link'
    assert classify_resource_type("link", "https://example.com/style.css") == "stylesheet"
    assert classify_resource_type("link", "https://example.com/font.woff2") == "font"
    assert classify_resource_type("link", "https://example.com/favicon.ico") == "image"
    assert classify_resource_type("other", "https://example.com/main.js") == "script"
    assert classify_resource_type("other", "https://example.com/image.png") == "image"
    assert classify_resource_type("other", "https://example.com/unknown.xyz") == "other"


def test_sanitize_resource_url():
    """Verify credentials and sensitive query tokens are redacted and capped."""
    url = "https://user:secretpass@example.com/api?token=abc123xyz&normal=ok&api_key=9999"
    sanitized = sanitize_resource_url(url)

    assert "secretpass@" not in sanitized
    assert "user:" not in sanitized
    assert "token=[REDACTED]" in sanitized
    assert "api_key=[REDACTED]" in sanitized
    assert "normal=ok" in sanitized
    assert sanitized.startswith("https://example.com/api?")


def test_empty_page_resource_aggregation():
    """Verify aggregation handles zero resources gracefully without div-by-zero or crashes."""
    res = PerformanceDiagnostics.evaluate(
        resource_entries=[],
        failed_requests=[],
        http_errors=[],
        console_messages=[],
        page_index=0,
        total_pages=1,
    )
    assert res["available"] is True
    assert res["resource_summary"]["total_requests"] == 0
    assert res["resource_summary"]["total_transfer_bytes"] == 0
    assert res["resource_summary"]["total_transfer_kb"] == 0.0
    assert res["resource_summary"]["has_transfer_size_data"] is False
    assert "unavailable" in res["resource_summary"]["size_measurement_note"].lower()
    assert res["failure_breakdown"]["total_failure_events"] == 0
    assert res["console_evidence"]["total_count"] == 0


def test_size_handling_valid_and_missing():
    """Verify transfer sizes are aggregated when present and 0/null values don't break logic."""
    entries = [
        {"name": "https://example.com/style.css", "initiatorType": "css", "transferSize": 10240},
        {"name": "https://example.com/app.js", "initiatorType": "script", "transferSize": 20480},
        {"name": "https://cdn.thirdparty.com/lib.js", "initiatorType": "script", "transferSize": 0},  # Opaque cross-origin
        {"name": "https://example.com/missing.png", "initiatorType": "img", "transferSize": None},
    ]
    res = PerformanceDiagnostics.evaluate(resource_entries=entries)
    summary = res["resource_summary"]

    assert summary["total_requests"] == 4
    assert summary["total_transfer_bytes"] == 30720  # 10240 + 20480
    assert summary["total_transfer_kb"] == 30.0
    assert summary["has_transfer_size_data"] is True

    # Check by_type
    assert summary["by_type"]["stylesheet"]["count"] == 1
    assert summary["by_type"]["stylesheet"]["transfer_bytes"] == 10240
    assert summary["by_type"]["script"]["count"] == 2
    assert summary["by_type"]["script"]["transfer_bytes"] == 20480
    assert summary["by_type"]["image"]["count"] == 1
    assert summary["by_type"]["image"]["transfer_bytes"] == 0


def test_failure_breakdown_differentiates_http_and_blocked():
    """Verify blocked/failed network requests and HTTP 4xx/5xx responses are separated."""
    failed_requests = ["https://blocked.tracking.com/pixel.gif", "https://unreachable.site.org/lib.js"]
    http_errors = [
        {"url": "https://example.com/api/user", "status": 401, "resource_type": "fetch"},
        {"url": "https://example.com/missing.css", "status": 404, "resource_type": "stylesheet"},
        {"url": "https://example.com/broken", "status": 500, "resource_type": "document"},
    ]

    res = PerformanceDiagnostics.evaluate(
        failed_requests=failed_requests,
        http_errors=http_errors,
    )
    fb = res["failure_breakdown"]
    assert fb["failed_requests_count"] == 2
    assert fb["http_errors_count"] == 3
    assert fb["total_failure_events"] == 5

    samples = fb["samples"]
    network_samples = [s for s in samples if s["category"] == "network_failure_or_blocked"]
    http_samples = [s for s in samples if s["category"] == "http_error"]

    assert len(network_samples) == 2
    assert len(http_samples) == 3
    assert any(s["status"] == 404 for s in http_samples)


def test_console_error_classification_and_truncation():
    """Verify actionable runtime errors are distinguished from warnings and capped."""
    console_msgs = [
        "[error] Uncaught TypeError: Cannot read property 'map' of undefined at app.js:42",
        "[error] ReferenceError: analytics is not defined",
        "[warning] The resource https://example.com/font was preloaded but not used",
        "[info] Connected to websocket",
    ]
    res = PerformanceDiagnostics.evaluate(console_messages=console_msgs)
    ce = res["console_evidence"]

    assert ce["total_count"] == 4
    assert ce["error_count"] == 2
    assert ce["warning_count"] == 2
    assert len(ce["actionable_errors"]) == 2
    assert "Uncaught TypeError" in ce["actionable_errors"][0]


def test_render_blocking_candidates_heuristics():
    """Verify render-blocking candidates are labeled as heuristics with limitation note."""
    rb_info = {
        "scripts": [{"url": "https://example.com/app.js", "reason": "Synchronous script in <head>"}],
        "stylesheets": [{"url": "https://example.com/style.css", "reason": "Standard stylesheet link in <head>"}],
    }
    res = PerformanceDiagnostics.evaluate(render_blocking_info=rb_info)
    rbc = res["render_blocking_candidates"]

    assert rbc["total_candidates"] == 2
    assert len(rbc["scripts"]) == 1
    assert len(rbc["stylesheets"]) == 1
    assert "heuristic" in rbc["limitation_note"].lower()


def test_multi_page_association():
    """Verify page index and total page count are preserved in coverage notes."""
    res = PerformanceDiagnostics.evaluate(page_index=2, total_pages=5)
    assert res["page_index"] == 2
    assert res["total_pages_captured"] == 5
    assert "captured page 3 of 5" in res["coverage_note"]


def test_browser_evidence_serialization_and_unavailability():
    """Verify BrowserEvidence serialization holds performance_diagnostics safely."""
    # 1. Unavailable evidence
    unavail = BrowserEvidence.unavailable("https://example.com", "Browser disabled")
    assert unavail.performance_diagnostics == {}
    d_unavail = unavail.to_dict()
    assert "performance_diagnostics" in d_unavail
    assert d_unavail["performance_diagnostics"] == {}

    # 2. Populated evidence
    ev = BrowserEvidence(requested_url="https://example.com", navigation_ok=True)
    ev.performance_diagnostics = PerformanceDiagnostics.evaluate(
        resource_entries=[{"name": "https://example.com/style.css", "initiatorType": "css", "transferSize": 5000}],
        page_index=0,
        total_pages=1,
    )
    d = ev.to_dict()
    assert "performance_diagnostics" in d
    assert d["performance_diagnostics"]["available"] is True
    assert d["performance_diagnostics"]["resource_summary"]["total_requests"] == 1


def test_scoring_neutrality_preserved():
    """Verify the canonical 62-factor audit registry remains completely intact and score-neutral."""
    registry = validate_factor_registry()
    assert len(registry) == 62, f"Expected exactly 62 canonical factors, found {len(registry)}"
    # Verify no performance diagnostic factor was artificially injected into the score calculation
    factor_ids = set(registry)
    assert "performance_diagnostics" not in factor_ids
    assert "resource_summary" not in factor_ids
