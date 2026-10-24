"""
tests/test_proposal_workflow.py

Unit test suite for ProposalService and human approval gates (Phase 5).
Verifies:
1. Generation from verified audit opportunities.
2. Proposal editing resets approval state for safety.
3. Explicit human approval records reviewer email and timestamp.
4. Sending UNAPPROVED proposal raises HumanApprovalRequiredError.
5. Sending APPROVED proposal in dry-run mode succeeds safely without sending external email.
"""

import pytest
from backend.app.services.proposal_service import (
    ProposalService,
    HumanApprovalRequiredError,
    ProposalWorkflowError,
)


def test_proposal_lifecycle_and_approval_gate():
    lead_id = "test-lead-uuid-1234"
    audit_results = {
        "technical": {
            "ssl": {"status": "FAIL", "message": "SSL expired"},
            "sitemap": {"status": "FAIL", "message": "Sitemap missing"},
        },
        "ux": {
            "cta": {"status": "FAIL"},
        },
    }

    # 1. Generate Proposal Draft
    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Acme Motors",
        website_url="https://acmemotors.com",
        audit_results=audit_results,
    )

    assert prop["business_name"] == "Acme Motors"
    assert prop["approved"] is False
    assert prop["requires_human_approval"] is True
    assert prop["sent"] is False
    assert len(prop["contributing_factor_ids"]) > 0

    # 2. Attempt to dispatch UNAPPROVED proposal -> MUST FAIL
    with pytest.raises(HumanApprovalRequiredError):
        ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email="owner@acmemotors.com",
            dry_run=True,
        )

    # 3. Human Edit Proposal
    edited = ProposalService.edit_proposal(
        lead_id=lead_id,
        subject="Customized Strategy Proposal for Acme Motors",
    )
    assert edited["subject"] == "Customized Strategy Proposal for Acme Motors"
    assert edited["edited"] is True
    assert edited["approved"] is False

    # Dispatching still fails after edit
    with pytest.raises(HumanApprovalRequiredError):
        ProposalService.dispatch_proposal(
            lead_id=lead_id,
            target_email="owner@acmemotors.com",
            dry_run=True,
        )

    # 4. Explicit Human Approval
    approved = ProposalService.approve_proposal(
        lead_id=lead_id,
        user_email="manager@tebsolutions.in",
    )
    assert approved["approved"] is True
    assert approved["approved_by"] == "manager@tebsolutions.in"
    assert approved["requires_human_approval"] is False

    # 5. Dispatch Approved Proposal (Dry Run)
    res = ProposalService.dispatch_proposal(
        lead_id=lead_id,
        target_email="owner@acmemotors.com",
        dry_run=True,
    )
    assert res["success"] is True
    assert res["mode"] == "dry_run"
    assert res["approved_by"] == "manager@tebsolutions.in"


def test_proposal_contact_email_defaults_to_info_tebsolutions():
    """Verify that generated proposal drafts use info@tebsolutions.in and never contact@tebsolutions.in."""
    lead_id = "test-lead-email-check-5678"
    audit_results = {
        "technical": {"ssl": {"status": "FAIL", "message": "SSL expired"}},
    }
    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Affhan Motors",
        website_url="https://affhanmotors.com",
        audit_results=audit_results,
    )

    assert "info@tebsolutions.in" in prop["body_html"]
    assert "info@tebsolutions.in" in prop["body_text"]
    assert "contact@tebsolutions.in" not in prop["body_html"]
    assert "contact@tebsolutions.in" not in prop["body_text"]
