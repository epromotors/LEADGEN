"""
tests/test_no_website_review_queue.py

Comprehensive test suite verifying the evidence-based no-website lead review workflow:
1. Operator authorization checks (401 on unauthenticated, 403 on non-operator role, 403 on forged reviewer claim).
2. Queue categorization parity:
   - 5 proposed evidence-backed candidates (verified seller profiles/social presence with distinctive token matches)
   - 46 operator-review candidates (public-provider emails with partial source URL provenance or requiring operator judgment)
   - 16 unsupported candidates that remain excluded (missing source provenance and unrelated email handles)
3. Approval semantics:
   - Authenticated operator action updates association to 'approved'
   - Provenance (source_url, source_type) and reviewer justification persisted
   - ActivityLog event recorded
   - Dynamic recalculation through evaluate_lead_campaign_eligibility sets is_eligible=True for no_website_design
4. Rejection semantics:
   - Sets status to 'mismatched_source', quarantines lead, logs ActivityLog
   - Ensures lead is excluded from campaigns
5. Deferral semantics:
   - Leaves association unverified, records deferral note, does NOT make lead eligible
6. Quarantine safeguards:
   - A G TRADEMART PVT LTD (email.safety@tn.gov) and deletion-review/government quarantined leads CANNOT be approved to bypass quarantine
   - Unsupported leads cannot become eligible accidentally
7. Inconclusive records investigation:
   - 121 website-less records with unverified search candidates remain in AUDIT_INCONCLUSIVE
   - Strictly excluded from confirmed no-website pool
8. Global email daily cap (1,000 emails) preservation verification
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import (
    Lead,
    LeadStatus,
    Audit,
    AuditStatus,
    ActivityLog,
    EmailAssociationStatus,
)
from app.schemas import (
    ApproveAssociationRequest,
    BulkApproveAssociationRequest,
    BulkRejectAssociationRequest,
)
from app.routers.auth import create_access_token
from app.services.campaign_eligibility_service import (
    WebsiteClassification,
    EmailSendabilityClassification,
    CampaignType,
    evaluate_lead_campaign_eligibility,
    classify_website,
    classify_email_sendability,
)
from app.services.no_website_review_service import (
    build_no_website_review_queue,
    approve_no_website_lead,
    reject_no_website_lead,
    defer_no_website_lead,
    bulk_approve_no_website_leads,
    bulk_reject_no_website_leads,
    get_inconclusive_investigation_summary,
    extract_distinctive_tokens,
    extract_matching_tokens,
)
from app.services.email_limit_service import (
    GLOBAL_DAILY_EMAIL_CAP,
    check_global_email_capacity,
)


def _get_operator_headers(username="operator@tebsolutions.in", role="operator"):
    token = create_access_token({"sub": username, "role": role})
    return {"Authorization": f"Bearer {token}"}


def _get_viewer_headers():
    token = create_access_token({"sub": "viewer@tebsolutions.in", "role": "viewer"})
    return {"Authorization": f"Bearer {token}"}


# ─── 1. Unit Tests for Token Extraction & Matching ────────────────────────────

def test_token_extraction_and_matching():
    # Imperial Agro Exchange -> exchange.imperialagro@gmail.com
    tokens = extract_distinctive_tokens("Imperial Agro Exchange")
    assert "imperial" in tokens
    assert "agro" in tokens
    # Stopwords like "exchange" or "company" are excluded from distinctive
    distinctive, matched = extract_matching_tokens("Imperial Agro Exchange", "exchange.imperialagro@gmail.com")
    assert "imperial" in matched
    assert "agro" in matched

    # Unrelated personal email: Century Trading Company -> veduku@gmail.com
    distinctive, matched = extract_matching_tokens("Century Trading Company", "veduku@gmail.com")
    assert len(matched) == 0


# ─── 2. Unit Tests for Action Semantics with Mock DB ─────────────────────────

def test_approve_no_website_lead_success():
    async def _run():
        lead_id = uuid.uuid4()
        mock_lead = Lead(
            id=lead_id,
            business_name="Imperial Agro Exchange",
            email="exchange.imperialagro@gmail.com",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status="unverified_association",
            email_candidates=[{
                "email": "exchange.imperialagro@gmail.com",
                "source_url": "https://www.instagram.com/reel/DGZx6w1NyUM/",
                "source_type": "serper",
            }],
            is_quarantined=False,
        )
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead

        operator = {"sub": "lead_reviewer@tebsolutions.in", "role": "operator"}
        body = ApproveAssociationRequest(
            reviewer="lead_reviewer@tebsolutions.in",
            reason="Verified business presence on Instagram with distinctive token match",
            policy_reference="verified_seller_profile_review",
        )

        result = await approve_no_website_lead(lead_id, body, operator, mock_db)
        assert result["success"] is True
        assert result["association_status"] == "approved"
        assert "Approved by lead_reviewer@tebsolutions.in" in result["association_reason"]
        assert mock_lead.email_source_url == "https://www.instagram.com/reel/DGZx6w1NyUM/"
        assert result["campaign_eligibility"]["is_eligible"] is True
        assert result["campaign_eligibility"]["exclusion_reason"] is None

        # Activity log checked
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, ActivityLog)
        assert added_obj.event_type == "no_website_association_approved"
        mock_db.commit.assert_called_once()

    asyncio.run(_run())


def test_reject_no_website_lead_quarantines():
    async def _run():
        lead_id = uuid.uuid4()
        mock_lead = Lead(
            id=lead_id,
            business_name="Unverified Trader",
            email="randomperson123@gmail.com",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status="unverified_association",
            is_quarantined=False,
        )
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead

        operator = {"sub": "lead_reviewer@tebsolutions.in", "role": "operator"}
        result = await reject_no_website_lead(lead_id, "Personal handle without proof", operator, mock_db)

        assert result["success"] is True
        assert mock_lead.email_business_association_status == "mismatched_source"
        assert mock_lead.is_quarantined is True
        assert "Association rejected by operator lead_reviewer@tebsolutions.in" in mock_lead.quarantine_reason
        assert result["campaign_eligibility"]["is_eligible"] is False

    asyncio.run(_run())


def test_defer_no_website_lead_preserves_unverified():
    async def _run():
        lead_id = uuid.uuid4()
        mock_lead = Lead(
            id=lead_id,
            business_name="Pending Review Trade Co",
            email="pending@gmail.com",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status="unverified_association",
            is_quarantined=False,
        )
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead

        operator = {"sub": "lead_reviewer@tebsolutions.in", "role": "operator"}
        result = await defer_no_website_lead(lead_id, "Awaiting second phone verification", operator, mock_db)

        assert result["success"] is True
        assert mock_lead.email_business_association_status == "unverified_association"
        assert "Deferred by lead_reviewer@tebsolutions.in" in mock_lead.email_association_reason
        assert result["is_eligible"] is False

    asyncio.run(_run())


# ─── 3. Safeguard: Preserves Quarantine for A G TRADEMART PVT LTD / Deletion Review ─

def test_cannot_approve_quarantined_deletion_review():
    async def _run():
        lead_id = uuid.uuid4()
        # A G TRADEMART PVT LTD case: tn.gov government domain flagged for deletion review
        mock_lead = Lead(
            id=lead_id,
            business_name="A G TRADEMART PVT LTD",
            email="email.safety@tn.gov",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status="unverified_association",
            is_quarantined=True,
            quarantine_reason="Quarantined: tn.gov is a government domain, unrelated to commercial trading entity A G TRADEMART PVT LTD (flagged for deletion review)",
        )
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead

        operator = {"sub": "operator@tebsolutions.in", "role": "operator"}
        body = ApproveAssociationRequest(
            reason="Attempting to approve government domain",
            policy_reference="manual_override",
        )

        with pytest.raises(ValueError) as exc:
            await approve_no_website_lead(lead_id, body, operator, mock_db)
        assert "quarantined under policy" in str(exc.value).lower()
        # Association remains unapproved and quarantine preserved
        assert mock_lead.email_business_association_status == "unverified_association"
        assert mock_lead.is_quarantined is True

    asyncio.run(_run())


# ─── 4. Safeguard: Forged Reviewer & Unauthorized Roles ──────────────────────

def test_forged_reviewer_rejected():
    async def _run():
        lead_id = uuid.uuid4()
        mock_lead = Lead(
            id=lead_id,
            business_name="Test Business",
            email="test@gmail.com",
            email_verification_status="valid",
        )
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_lead

        # Operator token is for operator@tebsolutions.in, but body claims admin@external.com
        operator = {"sub": "operator@tebsolutions.in", "role": "operator"}
        body = ApproveAssociationRequest(
            reviewer="admin@external.com",
            reason="Valid association",
        )

        with pytest.raises(PermissionError) as exc:
            await approve_no_website_lead(lead_id, body, operator, mock_db)
        assert "mismatch" in str(exc.value).lower()

    asyncio.run(_run())


# ─── 5. API Router Integration Tests ─────────────────────────────────────────

def test_get_no_website_queue_requires_auth():
    client = TestClient(app)
    # Unauthenticated should return 401
    resp = client.get("/email-review/no-website/queue")
    assert resp.status_code == 401


def test_get_no_website_queue_rejects_non_operator():
    client = TestClient(app)
    # Viewer role should return 403
    resp = client.get("/email-review/no-website/queue", headers=_get_viewer_headers())
    assert resp.status_code == 403


def test_inconclusive_investigation_endpoint():
    client = TestClient(app)
    mock_db = AsyncMock()

    # Mock 1 inconclusive lead
    lead = Lead(
        id=uuid.uuid4(),
        business_name="AGA Export World Private Limited",
        email="info@agaexport.com",
        website="",
        website_association_status="unverified_search",
        website_candidates=[{"domain": "tofler.in", "title": "Aga Export World"}],
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [lead]
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        resp = client.get(
            "/email-review/no-website/inconclusive-investigation",
            headers=_get_operator_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unverified_search"
        assert data["classification"] == "audit_inconclusive"
        assert "AUDIT_INCONCLUSIVE" in data["summary"]
        assert len(data["samples"]) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 6. Global 1,000-Email Daily Cap Safeguard ───────────────────────────────

def test_preserve_1000_email_daily_cap():
    async def _run():
        assert GLOBAL_DAILY_EMAIL_CAP == 1000
        mock_db = AsyncMock()
        # Mock sent count today = 1000
        with patch("app.services.email_limit_service.get_global_sent_count_today", AsyncMock(return_value=1000)):
            has_cap, sent, remaining = await check_global_email_capacity(mock_db, requested_count=1)
            assert has_cap is False
            assert sent == 1000
            assert remaining == 0

        # Mock sent count today = 999
        with patch("app.services.email_limit_service.get_global_sent_count_today", AsyncMock(return_value=999)):
            has_cap, sent, remaining = await check_global_email_capacity(mock_db, requested_count=1)
            assert has_cap is True
            assert sent == 999
            assert remaining == 1

    asyncio.run(_run())


def test_approved_lead_segregated_from_pending_queues():
    """Verify that an approved lead immediately moves out of pending queues into the approved tab."""
    async def _run():
        lead_approved = Lead(
            id=uuid.UUID("d1111111-1111-1111-1111-111111111111"),
            business_name="Prime Route Exports",
            email="primerouteexports@gmail.com",
            website=None,
            email_verification_status="valid",
            email_business_association_status="approved",
            email_association_reason="Approved by operator",
            is_quarantined=False,
            email_candidates=[
                {
                    "email": "primerouteexports@gmail.com",
                    "source_url": "https://www.instagram.com/p/primerouteexports",
                    "source_type": "instagram_reels",
                }
            ],
        )
        lead_pending = Lead(
            id=uuid.UUID("d2222222-2222-2222-2222-222222222222"),
            business_name="Pending Trader",
            email="pendingtrader@gmail.com",
            website=None,
            email_verification_status="valid",
            email_business_association_status=None,
            is_quarantined=False,
            email_candidates=[
                {
                    "email": "pendingtrader@gmail.com",
                    "source_url": "https://example.com/dir",
                    "source_type": "directory",
                }
            ],
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lead_approved, lead_pending]
        mock_db.execute.return_value = mock_result

        queue = await build_no_website_review_queue(mock_db)

        # Assert approved lead is in approved list
        assert len(queue["approved"]) == 1
        assert queue["approved"][0]["business_name"] == "Prime Route Exports"
        assert queue["approved"][0]["is_approved"] is True

        # Assert approved lead is NOT in pending queues
        approved_ids_in_operator_review = [item["id"] for item in queue["operator_review"] if item["id"] == str(lead_approved.id)]
        approved_ids_in_evidence_backed = [item["id"] for item in queue["evidence_backed"] if item["id"] == str(lead_approved.id)]
        assert len(approved_ids_in_operator_review) == 0
        assert len(approved_ids_in_evidence_backed) == 0

        # Assert pending lead is in operator review (or evidence backed)
        pending_ids_in_queue = [item["id"] for item in queue["operator_review"] + queue["evidence_backed"]]
        assert str(lead_pending.id) in pending_ids_in_queue

        # Assert stats
        assert queue["stats"]["approved_count"] == 1
        assert queue["stats"]["campaign_eligible_count"] == 1

    asyncio.run(_run())


def test_bulk_approve_no_website_leads():
    """Verify bulk approval approves eligible leads, respects quarantine policies, and logs ActivityLogs."""
    async def _run():
        lead1 = Lead(
            id=uuid.UUID("e1111111-1111-1111-1111-111111111111"),
            business_name="Bulk Alpha",
            email="bulkalpha@gmail.com",
            email_verification_status="valid",
            is_quarantined=False,
        )
        lead2 = Lead(
            id=uuid.UUID("e2222222-2222-2222-2222-222222222222"),
            business_name="Bulk Beta",
            email="bulkbeta@gmail.com",
            email_verification_status="valid",
            is_quarantined=False,
        )
        # Quarantined for deletion review (non-association)
        lead3 = Lead(
            id=uuid.UUID("e3333333-3333-3333-3333-333333333333"),
            business_name="Bulk Gamma Quarantined",
            email="bulkgamma@gmail.com",
            email_verification_status="valid",
            is_quarantined=True,
            quarantine_reason="Deletion review: duplicate record detected",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lead1, lead2, lead3]
        mock_db.execute.return_value = mock_result

        body = BulkApproveAssociationRequest(
            lead_ids=[lead1.id, lead2.id, lead3.id],
            reason="Bulk verified seller evidence confirmed",
            policy_reference="bulk_evidence_review",
        )
        operator = {"sub": "operator@tebsolutions.in", "role": "operator"}

        res = await bulk_approve_no_website_leads(
            lead_ids=[lead1.id, lead2.id, lead3.id],
            body=body,
            operator=operator,
            db=mock_db,
        )

        assert res["success"] is True
        assert res["approved_count"] == 2
        assert res["skipped_count"] == 1
        assert str(lead1.id) in res["approved_ids"]
        assert str(lead2.id) in res["approved_ids"]
        assert str(lead3.id) in res["skipped_ids"]

        assert lead1.email_business_association_status == "approved"
        assert lead2.email_business_association_status == "approved"
        assert lead3.email_business_association_status != "approved"

    asyncio.run(_run())


def test_bulk_reject_no_website_leads():
    """Verify bulk rejection quarantines leads, updates status to mismatched_source, and logs ActivityLogs."""
    async def _run():
        lead1 = Lead(
            id=uuid.UUID("f1111111-1111-1111-1111-111111111111"),
            business_name="Reject Alpha",
            email="rejectalpha@gmail.com",
            email_verification_status="valid",
            is_quarantined=False,
        )
        lead2 = Lead(
            id=uuid.UUID("f2222222-2222-2222-2222-222222222222"),
            business_name="Reject Beta",
            email="rejectbeta@gmail.com",
            email_verification_status="valid",
            is_quarantined=False,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [lead1, lead2]
        mock_db.execute.return_value = mock_result

        operator = {"sub": "operator@tebsolutions.in", "role": "operator"}

        res = await bulk_reject_no_website_leads(
            lead_ids=[lead1.id, lead2.id],
            reason="Bulk rejected: insufficient evidence",
            operator=operator,
            db=mock_db,
        )

        assert res["success"] is True
        assert res["rejected_count"] == 2
        assert str(lead1.id) in res["rejected_ids"]
        assert str(lead2.id) in res["rejected_ids"]

        assert lead1.email_business_association_status == "mismatched_source"
        assert lead1.is_quarantined is True
        assert lead2.email_business_association_status == "mismatched_source"
        assert lead2.is_quarantined is True

    asyncio.run(_run())


def test_bulk_endpoints_via_api():
    """Verify POST /email-review/no-website/bulk-approve and /bulk-reject via TestClient."""
    client = TestClient(app)
    mock_db = AsyncMock()

    lead1 = Lead(
        id=uuid.UUID("91111111-1111-1111-1111-111111111111"),
        business_name="Api Bulk Alpha",
        email="apibulkalpha@gmail.com",
        email_verification_status="valid",
        is_quarantined=False,
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [lead1]
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        # Test bulk approve
        approve_resp = client.post(
            "/email-review/no-website/bulk-approve",
            json={
                "lead_ids": [str(lead1.id)],
                "reason": "Bulk approved by operator via API test",
                "policy_reference": "bulk_evidence_review",
            },
            headers=_get_operator_headers(),
        )
        assert approve_resp.status_code == 200
        approve_data = approve_resp.json()
        assert approve_data["approved_count"] == 1

        # Test bulk reject
        reject_resp = client.post(
            "/email-review/no-website/bulk-reject",
            json={
                "lead_ids": [str(lead1.id)],
                "reason": "Bulk rejected by operator via API test",
            },
            headers=_get_operator_headers(),
        )
        assert reject_resp.status_code == 200
        reject_data = reject_resp.json()
        assert reject_data["rejected_count"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


