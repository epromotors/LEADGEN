# tests/test_geo_supplement_and_crawler_benchmarks.py
#
# Comprehensive test suite for open-source SEO/GEO capability upgrade:
# 1. Benchmark 62-factor canonical contract invariance
# 2. GEO supplement: AI crawler access rules, llms.txt spec validation, content attributability
# 3. Truthful disconnected state: No API key required, citations unavailable without creds
# 4. Crawler reliability: Redirect chains, loop detection, status preservation
# 5. Remediation plan: Evidence -> Impact -> Priority (P0/P1/P2) -> Fix -> Verification step
# 6. Semantic drift: Regression detection, verified fixes requiring fresh evidence

from __future__ import annotations

import sys
from pathlib import Path

# Ensure auditor packages are importable
_AUDITOR_PATH = Path(__file__).resolve().parents[1] / "auditor" / "auditor"
if str(_AUDITOR_PATH) not in sys.path:
    sys.path.insert(0, str(_AUDITOR_PATH))

import pytest
from bs4 import BeautifulSoup
from unittest.mock import MagicMock, patch

from auditor.geo_supplement import (
    parse_robots_ai_rules,
    validate_llms_txt_content,
    audit_content_attributability,
    audit_geo_supplement,
    AI_CITATION_BOTS,
    AI_TRAINING_BOTS,
)
from auditor.remediation_plan import (
    determine_action_priority,
    generate_remediation_plan,
)
from auditor.drift import compare_audits_for_drift
from auditor.core import fetch_page, normalize_url
from auditor.crawler import audit_page_seo
from app.engines.factor_contract import validate_factor_registry, compute_score


# ── 1. Canonical 62-Factor Contract Invariance ────────────────────────────────

def test_canonical_62_factor_contract_preserved():
    """Verify registry still has exactly 62 canonical factors and valid governance."""
    index = validate_factor_registry()
    assert len(index) == 62, f"Expected 62 canonical factors, found {len(index)}"
    assert "technical.ssl" in index
    assert "onpage.page_title" in index
    assert "links.broken_links" in index


# ── 2. GEO Supplement: AI Crawler Access Rules ───────────────────────────────

def test_robots_ai_rules_allow_all_by_default():
    """When robots.txt is missing or empty, all AI bots are allowed."""
    res = parse_robots_ai_rules("")
    assert res["citation_bots_all_allowed"] is True
    assert len(res["citation_bots_blocked"]) == 0
    assert res["robots_present"] is False


def test_robots_ai_rules_wildcard_disallowed():
    """When User-agent: * Disallow: /, bots without explicit rules are blocked."""
    robots_text = """
    User-agent: *
    Disallow: /
    """
    res = parse_robots_ai_rules(robots_text)
    assert res["citation_bots_all_allowed"] is False
    assert "GPTBot" in res["citation_bots_blocked"]
    assert "ClaudeBot" in res["citation_bots_blocked"]
    assert res["citation_bots"]["GPTBot"]["via"] == "wildcard"


def test_robots_ai_rules_explicit_citation_allow():
    """Explicit Allow rules for citation bots override wildcard Disallow."""
    robots_text = """
    User-agent: *
    Disallow: /

    User-agent: GPTBot
    Allow: /

    User-agent: ClaudeBot
    Allow: /

    User-agent: PerplexityBot
    Allow: /

    User-agent: OAI-SearchBot
    Allow: /

    User-agent: Google-Extended
    Allow: /

    User-agent: Applebot-Extended
    Allow: /
    """
    res = parse_robots_ai_rules(robots_text)
    assert res["citation_bots_all_allowed"] is True
    assert len(res["citation_bots_blocked"]) == 0
    assert res["has_explicit_ai_rules"] is True
    assert res["citation_bots"]["GPTBot"]["via"] == "explicit_rule"
    assert res["citation_bots"]["GPTBot"]["status"] == "allowed"


# ── 3. GEO Supplement: llms.txt Spec Validation ──────────────────────────────

def test_llms_txt_spec_validation_success():
    """Valid llms.txt with H1, blockquote, links, and word count passes validation."""
    sample_llms = """# Example Corp Documentation
> Example Corp provides automated logistics and freight tracking APIs for global supply chain operations.

## Core API Documentation
- [Authentication Guide](https://example.com/docs/auth): Guide for issuing OAuth2 bearer tokens.
- [Shipment Endpoints](https://example.com/docs/shipments): REST endpoints for parcel tracking and webhooks.
- [SDK Reference](https://example.com/docs/sdk.md): Python and TypeScript client packages.

## Optional Resources
- [Changelog](https://example.com/changelog): Monthly platform update log and breaking change notes.
"""
    res = validate_llms_txt_content(sample_llms)
    assert res["valid"] is True
    assert res["has_h1"] is True
    assert res["has_blockquote"] is True
    assert res["has_markdown_links"] is True
    assert res["has_optional_section"] is True
    assert res["ranking_factor"] is False
    assert "not a required search engine ranking factor" in res["note"]


def test_llms_txt_spec_validation_warnings():
    """Missing H1 and blockquote generates clear spec warnings."""
    invalid_llms = "Just a raw list of words without markdown headings."
    res = validate_llms_txt_content(invalid_llms)
    assert res["valid"] is False
    assert any("H1" in w for w in res["warnings"])
    assert any("blockquote" in w for w in res["warnings"])


# ── 4. Content Attributability & Understandability ───────────────────────────

def test_content_attributability_heuristics():
    """Pages with specific metrics, entity definitions, and citations score high on attributability."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Apex Logistics - Global Freight</title></head>
    <body>
        <h1>Apex Freight Logistics</h1>
        <p>Apex Logistics is a specialized cross-border freight forwarding company established in 2012.</p>
        <p>We manage over 15,000 shipments annually with a 99.4% on-time delivery rate across 45 countries.</p>
        <h2>Frequently Asked Questions</h2>
        <p>What is your typical turnaround time? Transit takes 48 hours for express air cargo.</p>
        <a href="https://iata.org/standards">IATA Cargo Standards</a>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    res = audit_content_attributability(soup, html)
    assert res["data_density_ok"] is True
    assert res["has_clear_entity_intro"] is True
    assert res["has_faq_structure"] is True
    assert res["outbound_citations_count"] >= 1
    assert res["attributability_score"] >= 75


# ── 5. Truthful Disconnected State (No External API Keys) ────────────────────

def test_geo_supplement_truthful_disconnected_citations():
    """GEO supplement reports citations as unavailable without fabricating numbers or scores."""
    html = "<html><body><h1>Local Bakery</h1><p>Fresh bread daily.</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    supp = audit_geo_supplement(soup, html, "https://example.com")
    
    assert supp["citation_monitoring"]["status"] == "unavailable"
    assert supp["citation_monitoring"]["citations_detected"] == 0
    assert "No synthetic citations fabricated" in supp["citation_monitoring"]["reason"]
    assert "does NOT prove or guarantee that ChatGPT" in supp["disclaimer"]


# ── 6. Crawler Reliability: Redirect Chains and Loops ────────────────────────

def test_fetch_page_records_redirect_chain_and_detects_loops():
    """Mock session with redirects verifies redirect chain and loop detection."""
    session = MagicMock()
    resp = MagicMock()
    resp.url = "https://example.com/target"
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/html"}
    resp.text = "<html><body>Home</body></html>"
    resp.content = b"<html><body>Home</body></html>"
    
    # Mock history of 2 redirects
    r1 = MagicMock()
    r1.url = "https://example.com/start"
    r2 = MagicMock()
    r2.url = "https://example.com/step1"
    resp.history = [r1, r2]

    session.get.return_value.__enter__.return_value = resp

    res = fetch_page("https://example.com/start", session)
    assert res["ok"] is True
    assert res["redirect_count"] == 2
    assert res["redirect_chain"] == [
        "https://example.com/start",
        "https://example.com/step1",
        "https://example.com/target",
    ]
    assert res["is_redirect_loop"] is False


def test_crawler_detects_redirect_loop_as_failure():
    """Circular redirect loop flags a FAIL issue in audit_page_seo."""
    page_with_loop = {
        "ok": True,
        "url": "https://example.com/loop-a",
        "final_url": "https://example.com/loop-b",
        "status_code": 301,
        "is_redirect_loop": True,
        "redirect_chain": ["https://example.com/loop-a", "https://example.com/loop-b", "https://example.com/loop-a"],
        "redirect_count": 3,
        "soup": BeautifulSoup("<html><body>Loop</body></html>", "html.parser"),
    }
    audit = audit_page_seo(page_with_loop, "https://example.com/loop-a")
    assert audit["status"] == "FAIL"
    assert any(i["check"] == "Redirect Loop" and i["severity"] == "FAIL" for i in audit["issues"])


# ── 7. Actionable Remediation Plan (Evidence -> Impact -> Priority -> Fix) ───

def test_remediation_plan_prioritization_and_structure():
    """Remediation plan correctly formats findings into P0/P1/P2 with verification steps."""
    audit_results = {
        "technical": {
            "ssl": {
                "id": "technical.ssl",
                "name": "SSL / HTTPS",
                "status": "FAIL",
                "message": "Certificate expired on 2026-10-01.",
                "evidence": [{"summary": "SSL handshake failed"}],
                "fix": "Renew SSL certificate via Let's Encrypt or provider.",
            },
            "sitemap": {
                "id": "technical.sitemap",
                "name": "XML Sitemap",
                "status": "WARN",
                "message": "Sitemap returns HTTP 404.",
                "fix": "Generate and configure sitemap.xml.",
            },
        },
        "onpage": {
            "page_title": {
                "id": "onpage.page_title",
                "name": "Page Title",
                "status": "FAIL",
                "message": "No title tag found.",
                "fix": "Add an informative title tag.",
            },
        },
        "images": {
            "webp": {
                "id": "images.webp",
                "name": "WebP Format",
                "status": "WARN",
                "message": "Images use legacy JPEG.",
                "fix": "Convert JPEG images to WebP.",
            },
        },
    }

    geo_supp = {
        "robots_ai_rules": {"citation_bots_blocked": ["GPTBot", "ClaudeBot"]},
        "llms_txt": {"found": False},
    }

    plan = generate_remediation_plan(audit_results, geo_supp)
    assert len(plan) >= 5

    # Check P0 order (SSL must be P0)
    assert plan[0]["priority"] == "P0"
    assert plan[0]["factor_id"] == "technical.ssl"
    assert "curl -Iv" in plan[0]["verification_step"]
    assert "Browser security warnings" in plan[0]["impact"]

    # Check P1 items
    p1_items = [p for p in plan if p["priority"] == "P1"]
    p1_factor_ids = {p["factor_id"] for p in p1_items}
    assert "onpage.page_title" in p1_factor_ids
    assert "geo.citation_bots" in p1_factor_ids

    # Check P2 items
    p2_items = [p for p in plan if p["priority"] == "P2"]
    p2_factor_ids = {p["factor_id"] for p in p2_items}
    assert "images.webp" in p2_factor_ids
    assert "geo.llms_txt" in p2_factor_ids


# ── 8. Semantic Drift & Historical Comparison ────────────────────────────────

def test_semantic_drift_detector_requires_fresh_verification():
    """Drift detector identifies verified fixes and regressions without fabricating resolutions."""
    audit_v1 = {
        "seo_score": 50,
        "audit_results": {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "FAIL", "message": "SSL expired"},
                "robots": {"id": "technical.robots", "status": "PASS", "message": "Valid robots.txt"},
            },
            "onpage": {
                "h1": {"id": "onpage.h1", "status": "FAIL", "message": "Missing H1"},
            },
        },
    }

    audit_v2 = {
        "seo_score": 75,
        "audit_results": {
            "technical": {
                "ssl": {"id": "technical.ssl", "status": "PASS", "message": "Valid Let's Encrypt cert"},
                "robots": {"id": "technical.robots", "status": "FAIL", "message": "Robots file now 500 error"},
            },
            "onpage": {
                "h1": {"id": "onpage.h1", "status": "PASS", "message": "H1 tag present and descriptive"},
            },
        },
    }

    drift = compare_audits_for_drift(audit_v1, audit_v2)
    assert drift["score_delta"] == 25
    assert drift["crawlability_lost"] is True
    assert drift["regressions_count"] == 1
    assert drift["regressions"][0]["factor_id"] == "technical.robots"
    assert drift["verified_fixes_count"] == 2
    
    verified_ids = {f["factor_id"] for f in drift["verified_fixes"]}
    assert "technical.ssl" in verified_ids
    assert "onpage.h1" in verified_ids
    assert "fresh evidence" in drift["summary"]
