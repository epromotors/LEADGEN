"""
tests/test_opportunity_engine.py

Unit and contract test suite for OpportunityEngine (Phase 5).
Verifies:
1. Evidence-to-offer mapping across canonical factor categories.
2. Differentiation between targeted repair vs broad website redesign.
3. Selection limit (at most 2-3 salient findings per proposal).
4. Provenance tracking: contributing factor IDs recorded for every claim.
5. Preview-only / Human Approval gate: requires_human_approval=True, sent=False.
6. Absence of unsubstantiated revenue/ranking claims.
"""

import pytest
from backend.app.engines.opportunity_engine import OpportunityEngine


def test_evaluate_opportunities_technical_and_sitemap():
    audit_results = {
        "technical": {
            "ssl": {"status": "FAIL", "message": "SSL expired or invalid"},
            "sitemap": {"status": "FAIL", "message": "Sitemap not found"},
            "robots": {"status": "PASS", "message": "Robots OK"},
            "canonical": {"status": "PASS", "message": "Canonical OK"},
        },
        "indexability": {
            "soft_404": {"status": "PASS"},
            "noindex": {"status": "PASS"},
        },
        "links": {
            "broken_links": {"status": "PASS"},
        },
    }

    url_info = {
        "requested_url": "https://example.com",
        "final_url": "https://example.com/",
        "canonical_url": "https://example.com/",
    }

    opps = OpportunityEngine.evaluate_opportunities(audit_results, url_info=url_info)
    assert len(opps) == 2

    # Technical SEO Remediation
    tech_opp = next((o for o in opps if o["service_id"] == "technical_seo_remediation"), None)
    assert tech_opp is not None
    assert tech_opp["scope"] == "repair"
    assert "technical.ssl" in tech_opp["relevant_factor_ids"]
    assert "technical.robots" not in tech_opp["relevant_factor_ids"]

    # Sitemap repair
    sitemap_opp = next((o for o in opps if o["service_id"] == "sitemap_indexing_repair"), None)
    assert sitemap_opp is not None
    assert sitemap_opp["scope"] == "repair"
    assert "technical.sitemap" in sitemap_opp["relevant_factor_ids"]


def test_ux_scope_distinction_repair_vs_redesign():
    # Scenario A: Single minor UX issue -> "repair" scope
    audit_repair = {
        "ux": {
            "cta": {"status": "PASS"},
            "cta_above_fold": {"status": "FAIL"},
            "contrast": {"status": "PASS"},
            "font_size": {"status": "PASS"},
        },
        "technical": {
            "mobile": {"status": "PASS"},
        },
    }
    opps_repair = OpportunityEngine.evaluate_opportunities(audit_repair)
    ux_repair = next((o for o in opps_repair if o["service_id"] == "web_design_ux_improvement"), None)
    assert ux_repair is not None
    assert ux_repair["scope"] == "repair"
    assert "Web Design & Conversion UX Repair" in ux_repair["service_name"]

    # Scenario B: Multiple UX issues including mobile viewport failure -> "redesign" scope
    audit_redesign = {
        "ux": {
            "cta": {"status": "FAIL"},
            "cta_above_fold": {"status": "FAIL"},
            "contrast": {"status": "FAIL"},
            "font_size": {"status": "FAIL"},
        },
        "technical": {
            "mobile": {"status": "FAIL"},
        },
    }
    opps_redesign = OpportunityEngine.evaluate_opportunities(audit_redesign)
    ux_redesign = next((o for o in opps_redesign if o["service_id"] == "web_design_ux_improvement"), None)
    assert ux_redesign is not None
    assert ux_redesign["scope"] == "redesign"
    assert "Modern Website Redesign" in ux_redesign["service_name"]


def test_proposal_draft_provenance_and_approval_gate():
    audit_results = {
        "technical": {
            "ssl": {"status": "FAIL", "message": "Missing SSL"},
            "mobile": {"status": "FAIL"},
            "sitemap": {"status": "FAIL"},
        },
        "ux": {
            "cta": {"status": "FAIL"},
            "contrast": {"status": "FAIL"},
        },
        "local_seo": {
            "local_business_schema": {"status": "FAIL"},
            "nap_consistency": {"status": "FAIL"},
        },
        "performance": {
            "response_time": {"status": "FAIL", "value": 2400},
            "render_blocking": {"status": "FAIL"},
        },
    }

    url_info = {"requested_url": "https://examplemotors.com"}
    opportunities = OpportunityEngine.evaluate_opportunities(audit_results, url_info=url_info)
    assert len(opportunities) >= 4  # multiple opportunities generated

    proposal = OpportunityEngine.generate_proposal_draft(
        business_name="Example Motors",
        website_url="https://examplemotors.com",
        opportunities=opportunities,
    )

    # 1. Selection limit: at most 2-3 salient observations
    assert len(proposal["observations"]) <= 3
    assert proposal["selected_opportunities_count"] <= 3

    # 2. Strict provenance tracking
    assert len(proposal["contributing_factor_ids"]) > 0
    # Every contributing factor ID must be a legitimate factor that failed
    for fid in proposal["contributing_factor_ids"]:
        cat, check = fid.split(".")
        assert audit_results.get(cat, {}).get(check, {}).get("status") == "FAIL"

    # 3. Preview-only / Human Approval Gate
    assert proposal["requires_human_approval"] is True
    assert proposal["status"] == "draft_preview"
    assert proposal["sent"] is False

    # 4. No unsubstantiated claims
    prohibited_terms = [
        "guarantee #1 ranking",
        "guaranteed revenue",
        "double your sales",
        "100% guarantee",
        "guaranteed 10x traffic",
    ]
    for term in prohibited_terms:
        assert term not in proposal["body_text"].lower()
        assert term not in proposal["body_html"].lower()
