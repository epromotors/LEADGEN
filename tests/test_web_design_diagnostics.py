"""
tests/test_web_design_diagnostics.py

Unit test suite for WebDesignDiagnostics (Domain H).
Verifies:
1. Markup design evaluation: viewport meta presence, semantic landmarks, heading hierarchy.
2. Fixed-width elements triggering mobile overflow risk.
3. Runtime diagnostics: horizontal scroll overflow, JavaScript console errors, failed subresources.
4. Authoritative classification into:
   - observed_live_site_defect
   - static_asset_markup_concern
   - rendered_browser_issue
   - heuristic_design_recommendation
"""

import sys
from pathlib import Path
import pytest
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "auditor" / "auditor") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "auditor" / "auditor"))

from browser.design_diagnostics import WebDesignDiagnostics
from browser.provider import BrowserEvidence


def test_markup_design_missing_viewport_and_landmarks():
    html = """
    <html>
      <head><title>Test Page</title></head>
      <body>
        <div>Just a div, no landmarks</div>
        <h3>Skipped heading straight to h3</h3>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    res = WebDesignDiagnostics.evaluate_markup_design_health(soup, viewport_mode="mobile")

    assert res["has_viewport_meta"] is False
    assert res["landmarks"]["header"] is False
    assert res["landmarks"]["main"] is False

    issue_codes = [i["code"] for i in res["issues"]]
    assert "MISSING_VIEWPORT_META" in issue_codes
    assert "WEAK_SEMANTIC_LANDMARKS" in issue_codes
    assert "NO_H1_HEADING" in issue_codes

    # Check classifications
    viewport_issue = next(i for i in res["issues"] if i["code"] == "MISSING_VIEWPORT_META")
    assert viewport_issue["type"] == "static_asset_markup_concern"


def test_markup_design_fixed_width_overflow_detection():
    html = """
    <html>
      <head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
      <body>
        <header><h1>Title</h1></header>
        <main>
          <div style="width: 950px; background: red;">Wide container without max-width</div>
          <table width="800"><tr><td>Wide table</td></tr></table>
        </main>
        <footer>Footer</footer>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    res = WebDesignDiagnostics.evaluate_markup_design_health(soup, viewport_mode="mobile")

    assert res["has_viewport_meta"] is True
    assert res["landmarks"]["header"] is True
    assert res["landmarks"]["main"] is True

    overflow_issue = next((i for i in res["issues"] if i["code"] == "FIXED_WIDTH_OVERFLOW_RISK"), None)
    assert overflow_issue is not None
    assert overflow_issue["type"] == "observed_live_site_defect"
    assert "950px" in overflow_issue["message"] or "Found 2" in overflow_issue["message"]


def test_browser_runtime_overflow_and_errors():
    console_errors = [
        "Uncaught TypeError: Cannot read properties of undefined (reading 'initSlider')",
        "Failed to load resource: the server responded with a status of 404 (Not Found) - app.bundle.js",
    ]
    failed_requests = [
        "https://example.com/assets/banner.jpg (HTTP 404)",
        "https://example.com/assets/styles.css (HTTP 500)",
    ]

    res = WebDesignDiagnostics.evaluate_browser_runtime_diagnostics(
        console_errors=console_errors,
        failed_requests=failed_requests,
        window_width=375,
        scroll_width=440,
        viewport_name="mobile_375x667",
    )

    assert res["has_horizontal_overflow"] is True
    assert res["overflow_px"] == 65
    assert res["console_error_count"] == 2
    assert res["failed_request_count"] == 2

    # Check that overflow is categorized as rendered_browser_issue
    overflow_issue = next(i for i in res["issues"] if i["code"] == "HORIZONTAL_SCROLL_OVERFLOW")
    assert overflow_issue["type"] == "rendered_browser_issue"
    assert overflow_issue["severity"] == "critical"

    # Check failed requests categorized as observed_live_site_defect
    failed_issue = next(i for i in res["issues"] if i["code"] == "FAILED_SUBRESOURCE_REQUESTS")
    assert failed_issue["type"] == "observed_live_site_defect"


def test_browser_evidence_dataclass_includes_design_fields():
    ev = BrowserEvidence(
        requested_url="https://example.com",
        has_horizontal_overflow=True,
        overflow_px=52,
        design_diagnostics={"total_issues": 3},
    )

    ev_dict = ev.to_dict()
    assert ev_dict["has_horizontal_overflow"] is True
    assert ev_dict["overflow_px"] == 52
    assert ev_dict["design_diagnostics"]["total_issues"] == 3
