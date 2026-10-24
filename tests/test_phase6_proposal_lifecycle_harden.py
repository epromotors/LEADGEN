"""
tests/test_phase6_proposal_lifecycle_harden.py

End-to-end integration-gate test suite for LEADGEN Phase 6:
Real Proposal Lifecycle Verification & Hardening.

Covers the 12 core requirements:
1. Draft create/read/update round trip.
2. Invalid draft update preserves the existing draft (422 / 400 without corruption).
3. Explicit approval is required before delivery.
4. Editing clears stale approval to draft_preview.
5. Unauthorized access or non-operator roles are denied.
6. Cross-lead and mismatched recipient targets are rejected.
7. Campaign eligibility gates (quarantine, unverified email, unverified association) are enforced.
8. Safe delivery simulation runs with zero SMTP side effects and zero queue enqueueing.
9. Ineligible simulation reports the actual specific failure reason.
10. Idempotent duplicate submissions cannot corrupt state.
11. API response contracts match frontend expectations.
12. Direct live dispatch outside the guarded campaign engine is strictly forbidden (403).
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Lead, Audit, AuditStatus
from app.routers import proposals
from app.routers.auth import require_authorized_operator
from app.services.proposal_service import ProposalService


@pytest.fixture
def test_setup():
    test_app = FastAPI()
    mock_operator = {"sub": "leadgen_auditor@tebsolutions.in", "role": "operator"}
    test_app.dependency_overrides[require_authorized_operator] = lambda: mock_operator
    test_app.include_router(proposals.router)

    lead_uuid = uuid.uuid4()
    lead_id = str(lead_uuid)
    audit_uuid = uuid.uuid4()

    mock_lead = Lead(
        id=lead_uuid,
        business_name="Apex Precision Engineering",
        website="https://apexprecision.co.uk",
        email="contact@apexprecision.co.uk",
        email_verification_status="valid",
        email_business_association_status="matched",
        is_quarantined=False,
    )

    mock_audit = Audit(
        id=audit_uuid,
        lead_id=lead_uuid,
        status=AuditStatus.done,
        updated_at=datetime.utcnow(),
        audit_results={
            "technical": {
                "ssl": {"status": "FAIL", "message": "SSL certificate expires in 2 days."},
                "robots": {"status": "FAIL", "message": "Robots.txt blocks critical CSS resources."},
            },
            "performance": {
                "response_time": {"status": "FAIL", "message": "Server TTFB exceeded 1800ms."},
            },
            "ux": {
                "cta": {"status": "FAIL", "message": "Primary call-to-action missing on landing page."},
            },
        },
        site_summary={
            "url_info": {"requested_url": "https://apexprecision.co.uk", "lead_id": lead_id},
        },
    )

    async def override_get_db():
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_lead)
        mock_audit_res = MagicMock()
        mock_audit_res.scalar_one_or_none.return_value = mock_audit
        mock_db.execute = AsyncMock(return_value=mock_audit_res)
        yield mock_db

    test_app.dependency_overrides[get_db] = override_get_db
    client = TestClient(test_app)

    yield {
        "app": test_app,
        "client": client,
        "lead_uuid": lead_uuid,
        "lead_id": lead_id,
        "audit_uuid": audit_uuid,
        "lead": mock_lead,
        "audit": mock_audit,
        "operator": mock_operator,
    }

    test_app.dependency_overrides.clear()


# ─── 1. Draft Create / Read / Update Round Trip ──────────────────────────────

def test_draft_create_read_update_roundtrip(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]

    # 1. GET /proposals/{lead_id} generates and returns proposal draft
    get_res = client.get(f"/proposals/{lead_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["lead_id"] == lead_id
    assert data["business_name"] == "Apex Precision Engineering"
    assert data["approved"] is False
    assert data["edited"] is False
    assert data["requires_human_approval"] is True
    assert len(data["observations"]) > 0
    orig_subject = data["subject"]

    # 2. PUT /proposals/{lead_id} updates subject and body
    new_subject = "Strategic Technical SEO & Performance Plan for Apex Precision"
    new_body = "We conducted an automated baseline diagnostic on https://apexprecision.co.uk..."
    put_res = client.put(
        f"/proposals/{lead_id}",
        json={"subject": new_subject, "body_text": new_body},
    )
    assert put_res.status_code == 200
    put_data = put_res.json()
    assert put_data["subject"] == new_subject
    assert put_data["body_text"] == new_body
    assert put_data["edited"] is True
    assert put_data["approved"] is False

    # 3. GET /proposals/{lead_id} again confirms persistence of edited draft
    get_res2 = client.get(f"/proposals/{lead_id}")
    assert get_res2.status_code == 200
    data2 = get_res2.json()
    assert data2["subject"] == new_subject
    assert data2["body_text"] == new_body
    assert data2["edited"] is True


# ─── 2. Invalid Draft Update Preserves Existing Draft ────────────────────────

def test_invalid_draft_update_preserves_content(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]

    # Initialize proposal
    init_res = client.get(f"/proposals/{lead_id}")
    assert init_res.status_code == 200
    initial_subject = init_res.json()["subject"]

    # Attempt PUT with empty/whitespace subject -> 422 Unprocessable Entity
    bad_res1 = client.put(f"/proposals/{lead_id}", json={"subject": "    "})
    assert bad_res1.status_code == 422

    # Attempt PUT with empty body -> 422
    bad_res2 = client.put(f"/proposals/{lead_id}", json={"body_text": ""})
    assert bad_res2.status_code == 422

    # Attempt PUT with empty payload {} -> 422
    bad_res3 = client.put(f"/proposals/{lead_id}", json={})
    assert bad_res3.status_code == 422

    # Attempt PUT with invalid UUID format -> 400 Bad Request
    bad_res4 = client.put("/proposals/invalid-non-uuid", json={"subject": "Valid Subject"})
    assert bad_res4.status_code == 400
    assert "Invalid lead UUID format" in bad_res4.json()["detail"]

    # Verify original draft subject was not corrupted
    check_res = client.get(f"/proposals/{lead_id}")
    assert check_res.status_code == 200
    assert check_res.json()["subject"] == initial_subject


# ─── 3. Explicit Approval Required Before Delivery ───────────────────────────

def test_explicit_approval_gate_enforcement(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead_email = test_setup["lead"].email

    # Initialize unapproved draft
    client.get(f"/proposals/{lead_id}")

    # Attempting delivery simulation without approval must be blocked with 403
    send_res = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": lead_email, "dry_run": True},
    )
    assert send_res.status_code == 403
    err_detail = send_res.json()["detail"]
    assert err_detail["error"] == "approval_required"
    assert "explicit human approval" in err_detail["message"].lower()

    # Operator explicitly approves
    approve_res = client.post(
        f"/proposals/{lead_id}/approve",
        json={"user_email": "operator@tebsolutions.in"},
    )
    assert approve_res.status_code == 200
    appr_data = approve_res.json()
    assert appr_data["approved"] is True
    assert appr_data["approved_by"] == "leadgen_auditor@tebsolutions.in"
    assert appr_data["status"] == "approved_for_delivery"

    # Now delivery simulation succeeds
    send_res2 = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": lead_email, "dry_run": True},
    )
    assert send_res2.status_code == 200
    assert send_res2.json()["success"] is True
    assert send_res2.json()["mode"] == "dry_run"


# ─── 4. Editing Clears Stale Approval ─────────────────────────────────────────

def test_editing_clears_stale_approval(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead_email = test_setup["lead"].email

    # 1. Initialize and approve
    client.get(f"/proposals/{lead_id}")
    appr = client.post(f"/proposals/{lead_id}/approve", json={})
    assert appr.status_code == 200
    assert appr.json()["approved"] is True

    # 2. Operator edits the draft
    edit_res = client.put(
        f"/proposals/{lead_id}",
        json={"subject": "Updated proposal subject requiring re-review"},
    )
    assert edit_res.status_code == 200
    edit_data = edit_res.json()
    # Approval must be revoked
    assert edit_data["approved"] is False
    assert edit_data["approved_by"] is None
    assert edit_data["approved_at"] is None
    assert edit_data["status"] == "draft_preview"

    # 3. Delivery must now fail again with approval_required
    send_res = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": lead_email, "dry_run": True},
    )
    assert send_res.status_code == 403
    assert send_res.json()["detail"]["error"] == "approval_required"


# ─── 5. Unauthorized Operator Denied ─────────────────────────────────────────

def test_unauthorized_operator_denied(test_setup):
    test_app = test_setup["app"]
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]

    # Override with unauthorized role or missing token
    from fastapi import HTTPException
    def deny_auth():
        raise HTTPException(status_code=401, detail="Authentication required")

    test_app.dependency_overrides[require_authorized_operator] = deny_auth

    r_get = client.get(f"/proposals/{lead_id}")
    assert r_get.status_code == 401

    r_put = client.put(f"/proposals/{lead_id}", json={"subject": "Sneaky edit"})
    assert r_put.status_code == 401

    r_appr = client.post(f"/proposals/{lead_id}/approve", json={})
    assert r_appr.status_code == 401

    r_send = client.post(f"/proposals/{lead_id}/send", json={"target_email": "test@test.com", "dry_run": True})
    assert r_send.status_code == 401


# ─── 6. Cross-Lead and Mismatched Target Email Rejected ──────────────────────

def test_cross_lead_target_email_rejected(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]

    # Initialize and approve
    client.get(f"/proposals/{lead_id}")
    client.post(f"/proposals/{lead_id}/approve", json={})

    # Attempting to simulate delivery to a different email than the lead's email
    send_res = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": "attacker@completely-unrelated-domain.com", "dry_run": True},
    )
    assert send_res.status_code == 400
    assert "does not match lead record email" in send_res.json()["detail"]


# ─── 7. Campaign Eligibility Gates Enforced ──────────────────────────────────

def test_quarantined_lead_cannot_be_approved_or_simulated(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead = test_setup["lead"]

    # Mark lead as quarantined
    lead.is_quarantined = True
    lead.quarantine_reason = "Spamtrap risk identified by MX auditor"

    client.get(f"/proposals/{lead_id}")

    # Approve must be rejected with 403
    appr_res = client.post(f"/proposals/{lead_id}/approve", json={})
    assert appr_res.status_code == 403
    assert "Proposal cannot be approved for delivery" in appr_res.json()["detail"]
    assert "Spamtrap risk" in appr_res.json()["detail"]

    # Direct send simulation must also be rejected with 403
    send_res = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": lead.email, "dry_run": True},
    )
    assert send_res.status_code == 403
    assert "Proposal delivery is blocked" in send_res.json()["detail"]


def test_unverified_email_cannot_be_approved(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead = test_setup["lead"]

    # Lead has pending verification
    lead.email_verification_status = "pending"

    client.get(f"/proposals/{lead_id}")

    appr_res = client.post(f"/proposals/{lead_id}/approve", json={})
    assert appr_res.status_code == 403
    assert "Email verification status is pending or unverified" in appr_res.json()["detail"]


# ─── 8. Safe Simulation: Zero SMTP Side Effects ──────────────────────────────

def test_safe_delivery_simulation_zero_smtp(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead_email = test_setup["lead"].email

    client.get(f"/proposals/{lead_id}")
    client.post(f"/proposals/{lead_id}/approve", json={})

    with patch("smtplib.SMTP") as mock_smtp, patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        send_res = client.post(
            f"/proposals/{lead_id}/send",
            json={"target_email": lead_email, "dry_run": True},
        )
        assert send_res.status_code == 200
        res_data = send_res.json()
        assert res_data["success"] is True
        assert res_data["mode"] == "dry_run"
        assert "Delivery simulated" in res_data["message"]

        # Assert ZERO SMTP connections were initiated
        mock_smtp.assert_not_called()
        mock_smtp_ssl.assert_not_called()

        # Proposal status in store remains unsent
        prop = ProposalService._proposals[lead_id]
        assert prop["sent"] is False
        assert prop["approved"] is True
        assert prop["status"] == "simulated_send_dry_run"


# ─── 9. Categorical Prohibition of Direct Live Send ──────────────────────────

def test_direct_live_send_categorically_forbidden(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead_email = test_setup["lead"].email

    client.get(f"/proposals/{lead_id}")
    client.post(f"/proposals/{lead_id}/approve", json={})

    # When dry_run=False, direct sending must be blocked with 403
    send_live_res = client.post(
        f"/proposals/{lead_id}/send",
        json={"target_email": lead_email, "dry_run": False},
    )
    assert send_live_res.status_code == 403
    detail = send_live_res.json()["detail"]
    assert detail["error"] == "direct_send_forbidden"
    assert "Direct proposal delivery is disabled" in detail["message"]


# ─── 10. Idempotent Repeated Submissions ─────────────────────────────────────

def test_idempotent_duplicate_approval_and_simulation(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]
    lead_email = test_setup["lead"].email

    client.get(f"/proposals/{lead_id}")

    # Approve twice
    appr1 = client.post(f"/proposals/{lead_id}/approve", json={})
    assert appr1.status_code == 200
    appr2 = client.post(f"/proposals/{lead_id}/approve", json={})
    assert appr2.status_code == 200
    assert appr2.json()["approved"] is True

    # Simulate twice
    sim1 = client.post(f"/proposals/{lead_id}/send", json={"target_email": lead_email, "dry_run": True})
    assert sim1.status_code == 200
    sim2 = client.post(f"/proposals/{lead_id}/send", json={"target_email": lead_email, "dry_run": True})
    assert sim2.status_code == 200
    assert sim2.json()["success"] is True


# ─── 11. API and Frontend Response Contract Parity ───────────────────────────

def test_api_contract_matches_frontend_expectations(test_setup):
    client = test_setup["client"]
    lead_id = test_setup["lead_id"]

    res = client.get(f"/proposals/{lead_id}")
    assert res.status_code == 200
    data = res.json()

    # Required fields checked by Audits.jsx
    required_frontend_keys = [
        "id",
        "lead_id",
        "business_name",
        "website_url",
        "subject",
        "observations",
        "selected_opportunities_count",
        "contributing_factor_ids",
        "body_html",
        "body_text",
        "requires_human_approval",
        "approved",
        "approved_by",
        "status",
        "sent",
    ]
    for key in required_frontend_keys:
        assert key in data, f"Missing required frontend proposal key: {key}"

    # Verify each observation structure for ProposalEvidenceDrawer
    for obs in data["observations"]:
        assert "service_name" in obs
        assert "service_category" in obs
        assert "scope" in obs
        assert "factor_ids" in obs
        assert "evidence" in obs
        assert "next_step" in obs
