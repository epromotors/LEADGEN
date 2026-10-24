"""Focused Phase 6 evidence-to-service and proposal safety coverage."""

import uuid

import pytest

from app.engines.opportunity_engine import OpportunityEngine
from app.services.proposal_service import ProposalService, ProposalWorkflowError


def _results():
    return {
        "technical": {
            "sitemap": {"status": "FAIL", "message": "No sitemap was collected for the audited URL."},
            "mobile": {"status": "FAIL", "message": "Viewport meta tag is absent."},
        },
        "local_seo": {
            "has_nap": {"status": "FAIL", "message": "Business address and phone were not found."},
            "has_local_business_schema": {"status": "FAIL", "message": "LocalBusiness JSON-LD was not found."},
        },
        "performance": {
            "response_time": {"status": "FAIL", "message": "Measured response time was 1800ms."},
        },
        "ux": {
            "cta": {"status": "FAIL", "message": "A clear primary CTA was not found."},
        },
        "onpage": {
            "page_title": {"status": "FAIL", "message": "Page title is missing."},
            "h1": {"status": "FAIL", "message": "Primary H1 is missing."},
            "meta_desc": {"status": "FAIL", "message": "Meta description is missing."},
        },
        "content": {
            "word_count": {"status": "FAIL", "message": "Page has 120 words."},
        },
    }


def test_phase6_mapping_uses_collected_evidence_and_preserves_provenance():
    opportunities = OpportunityEngine.evaluate_opportunities(
        _results(), url_info={"requested_url": "https://example.test/services"}
    )

    categories = {item["service_category"] for item in opportunities}
    assert {
        "Crawl & Indexing",
        "Local SEO",
        "Web Design & UX",
        "Performance",
        "AI Search Readiness",
        "On-Page SEO",
        "Support & Monitoring",
    } <= categories

    for opportunity in opportunities:
        assert opportunity["relevant_factor_ids"]
        assert opportunity["affected_urls"] == ["https://example.test/services"]
        assert opportunity["evidence"]
        assert opportunity["prerequisites"]

    local = next(item for item in opportunities if item["service_category"] == "Local SEO")
    assert "local_seo.has_nap" in local["relevant_factor_ids"]
    assert "Business address and phone were not found." in local["evidence"]

    draft = OpportunityEngine.generate_proposal_draft(
        "Example Services", "https://example.test/services", opportunities
    )
    assert 1 <= draft["selected_opportunities_count"] <= 3
    assert all(obs["factor_ids"] and obs["affected_urls"] for obs in draft["observations"])
    assert "guaranteed rankings" not in draft["body_text"]


def test_phase6_unavailable_is_not_promoted_to_a_defect_or_offer():
    opportunities = OpportunityEngine.evaluate_opportunities(
        {"technical": {"ssl": {"status": "UNAVAILABLE", "message": "Timed out."}}},
        url_info={"requested_url": "https://example.test"},
    )
    assert opportunities == []


def test_phase6_proposal_service_cannot_mark_a_direct_live_delivery_as_sent():
    lead_id = str(uuid.uuid4())
    proposal = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Example Services",
        website_url="https://example.test",
        audit_results={"technical": {"sitemap": {"status": "FAIL", "message": "Sitemap missing."}}},
        association_status="matched",
    )
    ProposalService.approve_proposal(lead_id, "operator@example.test")

    with pytest.raises(ProposalWorkflowError, match="approved campaign workflow"):
        ProposalService.dispatch_proposal(lead_id, "owner@example.test", dry_run=False)

    assert proposal["sent"] is False
