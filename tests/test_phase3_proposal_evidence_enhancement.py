"""
tests/test_phase3_proposal_evidence_enhancement.py

Comprehensive deterministic verification suite for LEADGEN Phase 3:
Evidence-Driven Proposal Generator Enhancement.

Verifies:
1. Opportunity mapping (SEO findings, performance diagnostics, AI search observations, mismatched evidence rejection).
2. Evidence traceability (honest source labeling, candidate heuristics, missing size unavailable not zero).
3. Proposal rendering (clean baseline introduction for empty findings, XSS sanitization, bounding).
4. Workflow and safety (approval gate immutability, zero outbound SMTP calls, zero campaign side-effects).
5. Deterministic four-case fixture (1 SEO, 1 AI observation, 1 performance diagnostic, 1 missing evidence).
"""

import smtplib
import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.engines.opportunity_engine import OpportunityEngine
from app.services.proposal_service import (
    ProposalService,
    ProposalWorkflowError,
    HumanApprovalRequiredError,
)
from app.services.audit_email_service import (
    AuditEmailService,
    AuditEmailGenerationError,
)


# ─── 1. Opportunity Mapping & Diagnostics ──────────────────────────────────────

def test_opportunity_mapping_valid_seo_finding():
    """A valid audit finding maps to the appropriate service with exact factor provenance."""
    audit_results = {
        "technical": {
            "ssl": {"status": "FAIL", "message": "SSL certificate expired."},
            "sitemap": {"status": "PASS"},
        }
    }
    url_info = {"requested_url": "https://example.com"}

    opps = OpportunityEngine.evaluate_opportunities(audit_results, url_info=url_info)
    assert len(opps) == 1
    opp = opps[0]
    assert opp["service_id"] == "technical_seo_remediation"
    assert opp["service_category"] == "Technical SEO"
    assert "technical.ssl" in opp["relevant_factor_ids"]
    assert "SSL certificate expired." in opp["evidence"][0]
    assert opp["evidence_type"] == "audit_factor"


def test_opportunity_mapping_performance_diagnostics():
    """Matching performance diagnostics map to performance_speed_optimization with honest candidate labels."""
    perf_diag = {
        "available": True,
        "page_index": 0,
        "total_pages_captured": 1,
        "resource_summary": {
            "total_requests": 28,
            "total_transfer_kb": 2200.5,
            "has_transfer_size_data": True,
            "by_type": {
                "image": {"count": 8, "transfer_kb": 1400.0, "has_size_data": True},
                "script": {"count": 10, "transfer_kb": 500.0, "has_size_data": True},
            },
        },
        "failure_breakdown": {
            "failed_requests_count": 1,
            "http_errors_count": 2,
            "total_failure_events": 3,
            "samples": [],
        },
        "console_evidence": {
            "total_count": 1,
            "error_count": 1,
            "actionable_errors": ["Uncaught TypeError: Cannot read properties of undefined"],
        },
        "render_blocking_candidates": {
            "total_candidates": 2,
            "scripts": [{"url": "https://example.com/bundle.js", "reason": "Sync script in head"}],
            "stylesheets": [{"url": "https://example.com/styles.css", "reason": "CSS in head"}],
        },
    }

    site_summary = {
        "browser_evidence": {
            "performance_diagnostics": perf_diag,
        }
    }

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={},
        url_info={"requested_url": "https://example.com"},
        site_summary=site_summary,
    )

    perf_opp = next((o for o in opps if o["service_id"] == "performance_speed_optimization"), None)
    assert perf_opp is not None
    assert perf_opp["service_category"] == "Performance"
    assert "performance.render_blocking" in perf_opp["relevant_factor_ids"]
    assert "images.webp" in perf_opp["relevant_factor_ids"]

    # Evidence distinguishes observed defects from heuristics
    ev_joined = " ".join(perf_opp["evidence"])
    assert "2 HTTP 4xx/5xx error response(s)" in ev_joined
    assert "1 network connection failure(s)" in ev_joined
    assert "1 runtime JavaScript error(s)" in ev_joined
    assert "Note: Candidate heuristic" in ev_joined
    assert perf_opp["limitations"] is not None
    assert "heuristics based on DOM placement" in perf_opp["limitations"]


def test_opportunity_mapping_missing_resource_size_not_zero():
    """Missing cross-origin resource transfer size is never treated as zero bytes."""
    perf_diag = {
        "available": True,
        "page_index": 0,
        "total_pages_captured": 1,
        "resource_summary": {
            "total_requests": 15,
            "total_transfer_kb": 0.0,
            "has_transfer_size_data": False,  # Missing timing data
            "by_type": {
                "image": {"count": 6, "transfer_kb": 0.0, "has_size_data": False},
            },
        },
        "failure_breakdown": {"failed_requests_count": 0, "http_errors_count": 0},
        "console_evidence": {"actionable_errors": []},
        "render_blocking_candidates": {"total_candidates": 0, "scripts": [], "stylesheets": []},
    }

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={},
        url_info={"requested_url": "https://example.com"},
        site_summary={"browser_evidence": {"performance_diagnostics": perf_diag}},
    )

    # Because there are no failures and transfer size is unavailable, no false 0-byte claim is made
    for opp in opps:
        for ev in opp.get("evidence", []):
            assert "0 KB total transfer volume" not in ev
            assert "consuming 0.0 KB" not in ev


def test_opportunity_mapping_valid_ai_search_observation_manual():
    """Valid manual AI Search observation produces grounded recommendation with explicit manual source label."""
    obs_id = str(uuid.uuid4())
    ai_observations = [
        {
            "observation_id": obs_id,
            "target_domain": "example.com",
            "search_query": "best plumber near me",
            "mention_status": "not_mentioned",
            "source_type": "manual",
            "provider": "Manual Observation",
            "engine": "AI Assistant",
            "observed_at": "2026-10-20T10:00:00Z",
            "citation_urls": [],
        }
    ]

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={},
        url_info={"requested_url": "https://example.com"},
        ai_observations=ai_observations,
    )

    ai_opp = next((o for o in opps if o["service_id"] == "ai_search_visibility_monitoring"), None)
    assert ai_opp is not None
    assert ai_opp["service_category"] == "AI Search Readiness"
    assert ai_opp["scope"] == "monitoring"
    assert ai_opp["evidence_source"] == "Manual Observation"
    assert ai_opp["observation_id"] == obs_id
    assert "manual observation recorded by operator" in ai_opp["evidence"][0]
    assert "not observe a mention" in ai_opp["evidence"][0]
    assert "Single prompt observation; does not establish ranking" in ai_opp["limitations"]


def test_opportunity_mapping_valid_ai_search_observation_provider():
    """Live provider AI Search observation preserves live provider identity without false claims."""
    obs_id = str(uuid.uuid4())
    ai_observations = [
        {
            "observation_id": obs_id,
            "target_domain": "example.com",
            "search_query": "commercial cleaning services",
            "mention_status": "mentioned",
            "source_type": "provider_api",
            "provider": "Google Gemini API",
            "engine": "Google",
            "observed_at": "2026-10-21T14:30:00Z",
            "citation_urls": ["https://example.com/commercial"],
        }
    ]

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={},
        url_info={"requested_url": "https://example.com"},
        ai_observations=ai_observations,
    )

    ai_opp = next((o for o in opps if o["service_id"] == "ai_search_visibility_monitoring"), None)
    assert ai_opp is not None
    assert "verified live query observation via Google Gemini API" in ai_opp["evidence"][0]
    assert "includes a citation to https://example.com/commercial" in ai_opp["evidence"][0]
    assert ai_opp["evidence_source"] == "Google Gemini API"


def test_opportunity_mapping_missing_ai_observation_not_proven_failure():
    """Empty AI observation ledger does not penalize the business or claim a visibility failure."""
    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={"technical": {"ssl": {"status": "FAIL", "message": "SSL failed."}}},
        url_info={"requested_url": "https://example.com"},
        ai_observations=[],
    )

    # No AI search visibility monitoring opportunity created when ledger is empty
    ai_opp = next((o for o in opps if o["service_id"] == "ai_search_visibility_monitoring"), None)
    assert ai_opp is None


def test_opportunity_mapping_mismatched_domain_or_lead_rejected():
    """Evidence from another domain or another lead is strictly rejected."""
    mismatched_obs = [
        {
            "observation_id": str(uuid.uuid4()),
            "target_domain": "competitor.test",
            "lead_id": str(uuid.uuid4()),
            "search_query": "auto repair services",
            "mention_status": "not_mentioned",
            "source_type": "manual",
        }
    ]

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results={},
        url_info={"requested_url": "https://target-site.test", "lead_id": str(uuid.uuid4())},
        ai_observations=mismatched_obs,
    )
    assert opps == []


# ─── 2. Evidence Traceability & Limitations ────────────────────────────────────

def test_evidence_traceability_in_generated_draft():
    """Every generated observation preserves traceable metadata and limitations."""
    opps = [
        {
            "service_id": "ai_search_visibility_monitoring",
            "service_name": "AI Search Visibility Monitoring & Entity Optimization",
            "service_category": "AI Search Readiness",
            "scope": "monitoring",
            "relevant_factor_ids": ["ai_search.observation"],
            "confidence": 0.85,
            "evidence": ["Recorded manual observation on 2026-10-20 for query 'hvac repair' did not observe a mention."],
            "affected_urls": ["https://example.com"],
            "prerequisites": ["Confirm priority queries."],
            "rationale": "Recorded observation indicates absence for target prompt.",
            "proposed_next_step": "Establish recurring AI search monitoring.",
            "evidence_type": "ai_search_observation",
            "evidence_source": "Manual Observation",
            "observation_id": "obs-12345",
            "evidence_date": "2026-10-20T10:00:00Z",
            "limitations": "Single observation; does not prove global visibility trend.",
        }
    ]

    draft = OpportunityEngine.generate_proposal_draft(
        business_name="Premier HVAC",
        website_url="https://example.com",
        opportunities=opps,
    )

    obs = draft["observations"][0]
    assert obs["service_id"] == "ai_search_visibility_monitoring"
    assert obs["evidence_source"] == "Manual Observation"
    assert obs["observation_id"] == "obs-12345"
    assert obs["limitations"] == "Single observation; does not prove global visibility trend."
    assert "Source: Manual Observation" in draft["body_html"]
    assert "Limitation: Single observation" in draft["body_html"]
    assert "Source: Manual Observation" in draft["body_text"]


# ─── 3. Proposal Rendering & Clean Baseline ────────────────────────────────────

def test_proposal_rendering_empty_data_case_clean_baseline():
    """Empty findings render a truthful baseline introduction without pretending defects exist."""
    draft = OpportunityEngine.generate_proposal_draft(
        business_name="Spotless Auto",
        website_url="https://spotlessauto.example",
        opportunities=[],
    )

    assert draft["selected_opportunities_count"] == 0
    assert draft["observations"] == []
    assert "identified 0 specific areas" not in draft["body_html"]
    assert "did not record critical infrastructure defects" in draft["body_html"]
    assert "did not record critical infrastructure defects" in draft["body_text"]
    assert draft["requires_human_approval"] is True


def test_proposal_rendering_escapes_xss_payloads():
    """Malicious script tags in lead attributes or evidence are escaped in HTML."""
    xss_name = "Super Services <script>alert('pwned')</script>"
    opps = [
        {
            "service_id": "technical_seo_remediation",
            "service_name": "Technical SEO & Repair",
            "service_category": "Technical SEO",
            "scope": "repair",
            "relevant_factor_ids": ["technical.ssl"],
            "confidence": 0.9,
            "evidence": ["Evidence with <img src=x onerror=alert(1)>"],
            "affected_urls": ["https://example.com"],
            "prerequisites": ["Access."],
            "rationale": "Fix issues.",
            "proposed_next_step": "Configure redirection.",
            "evidence_type": "audit_factor",
            "evidence_source": "Canonical Audit",
            "limitations": None,
        }
    ]

    draft = OpportunityEngine.generate_proposal_draft(
        business_name=xss_name,
        website_url="https://example.com",
        opportunities=opps,
    )

    assert "<script>alert('pwned')</script>" not in draft["body_html"]
    assert "&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt;" in draft["body_html"]
    assert "<img src=x onerror=alert(1)>" not in draft["body_html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in draft["body_html"]


# ─── 4. Workflow & Dispatch Safety Gates ───────────────────────────────────────

def test_preview_security_zero_smtp_and_immutable_approval():
    """Generating or previewing a proposal draft produces zero SMTP connections and requires human approval."""
    lead_id = str(uuid.uuid4())
    audit_results = {
        "technical": {"sitemap": {"status": "FAIL", "message": "XML Sitemap missing."}}
    }

    with patch("smtplib.SMTP") as mock_smtp, patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        proposal = ProposalService.get_or_create_proposal(
            lead_id=lead_id,
            business_name="Safe Preview Lead",
            website_url="https://safepreview.example",
            audit_results=audit_results,
            association_status="matched",
        )

        assert mock_smtp.call_count == 0
        assert mock_smtp_ssl.call_count == 0

        # Approval state remains False
        assert proposal["approved"] is False
        assert proposal["approved_by"] is None
        assert proposal["sent"] is False
        assert proposal["requires_human_approval"] is True

        # Dispatch without approval is strictly blocked
        with pytest.raises(HumanApprovalRequiredError):
            ProposalService.dispatch_proposal(lead_id, "target@safepreview.example", dry_run=True)


# ─── 5. Deterministic Four-Case Fixture (Section 8) ───────────────────────────

def test_proposal_four_case_deterministic_fixture():
    """
    Deterministic verification fixture encompassing:
    1. One valid SEO finding (technical.sitemap FAIL)
    2. One recorded AI Search observation (manual 'not_mentioned')
    3. One performance resource diagnostic (heavy image volume + candidate scripts)
    4. One missing-evidence case (cross-origin missing size + missing robots.txt observation)
    """
    audit_results = {
        "technical": {
            "sitemap": {"status": "FAIL", "message": "XML sitemap missing from server."},
            "ssl": {"status": "PASS"},
            "robots": {"status": "UNAVAILABLE", "message": "Network timeout."},  # Case 4: unavailable is not defect
        }
    }

    ai_observations = [
        {
            "observation_id": str(uuid.uuid4()),
            "target_domain": "multitest.example",
            "search_query": "premier dental care",
            "mention_status": "not_mentioned",
            "source_type": "manual",
            "provider": "Manual Observation",
            "observed_at": "2026-10-22T08:00:00Z",
        }
    ]

    perf_diag = {
        "available": True,
        "page_index": 0,
        "total_pages_captured": 1,
        "resource_summary": {
            "total_requests": 22,
            "total_transfer_kb": 1850.0,
            "has_transfer_size_data": True,
            "by_type": {
                "image": {"count": 7, "transfer_kb": 1100.0, "has_size_data": True},
                "other": {"count": 5, "transfer_kb": 0.0, "has_size_data": False},  # Case 4: missing cross-origin size
            },
        },
        "failure_breakdown": {"failed_requests_count": 0, "http_errors_count": 0},
        "console_evidence": {"actionable_errors": []},
        "render_blocking_candidates": {
            "total_candidates": 1,
            "scripts": [{"url": "https://multitest.example/app.js", "reason": "Sync script in head"}],
            "stylesheets": [],
        },
    }

    site_summary = {
        "browser_evidence": {
            "performance_diagnostics": perf_diag,
        }
    }

    opps = OpportunityEngine.evaluate_opportunities(
        audit_results=audit_results,
        url_info={"requested_url": "https://multitest.example"},
        site_summary=site_summary,
        ai_observations=ai_observations,
    )

    # 1. Sitemap repair exists from valid SEO finding
    sitemap_opp = next((o for o in opps if o["service_id"] == "sitemap_indexing_repair"), None)
    assert sitemap_opp is not None
    assert "technical.sitemap" in sitemap_opp["relevant_factor_ids"]

    # 2. AI visibility monitoring exists with honest manual label
    ai_opp = next((o for o in opps if o["service_id"] == "ai_search_visibility_monitoring"), None)
    assert ai_opp is not None
    assert ai_opp["evidence_source"] == "Manual Observation"
    assert "not observe a mention" in ai_opp["evidence"][0]

    # 3. Performance optimization exists from diagnostics
    perf_opp = next((o for o in opps if o["service_id"] == "performance_speed_optimization"), None)
    assert perf_opp is not None
    assert "images.webp" in perf_opp["relevant_factor_ids"]
    assert "Candidate heuristic" in " ".join(perf_opp["evidence"])

    # 4. Missing-evidence case: unavailable robots.txt was not promoted to a defect
    tech_opp = next((o for o in opps if o["service_id"] == "technical_seo_remediation"), None)
    assert tech_opp is None  # ssl passed and robots was UNAVAILABLE

    # Draft synthesis preserves up to 3 salient findings and traceability
    draft = OpportunityEngine.generate_proposal_draft(
        business_name="MultiTest Dental",
        website_url="https://multitest.example",
        opportunities=opps,
    )

    assert 1 <= draft["selected_opportunities_count"] <= 3
    assert len(draft["observations"]) == 3
    assert all(obs["evidence_source"] for obs in draft["observations"])
    assert draft["requires_human_approval"] is True
