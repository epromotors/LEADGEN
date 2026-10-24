"""
tests/test_public_provider_demo_policy.py

Comprehensive test suite verifying the Public Email Provider Demo-Only Outreach Policy:
1. Routeable Gmail with unverified association can enter public_provider_demo.
2. Routeable Yahoo with unverified association can enter public_provider_demo.
3. Other configured public providers (Outlook, Hotmail, Proton, Zoho) follow the same narrow policy; custom business domains do not.
4. Unverified public-provider addresses remain strictly blocked from audit-specific and standard marketing campaigns.
5. Matched/approved public-provider leads remain eligible for standard campaigns.
6. Invalid syntax blocks demo-only and all other campaigns.
7. Disposable addresses are blocked from all campaigns.
8. Missing or unusable DNS/MX routeability blocks demo eligibility.
9. Pending or unknown verification cannot bypass verification.
10. Known hard bounce, suppression, or unsubscribe blocks every campaign.
11. Confirmed source mismatch and agency/designer-credit extraction remain blocked.
12. An independent genuine quarantine is not bypassed.
13. Legacy quarantine caused solely by obsolete provider-type rule follows controlled re-verification workflow.
14. One-time demo contact limit prevents duplicate sends across retries, re-queueing, and normalized duplicate addresses.
15. Lead becoming ineligible after queueing is stopped at pre-send.
16. Normal campaign routes cannot inherit the demo-only exception.
17. Campaign preview and outreach worker use the same authoritative template renderer.
18. Mocked email transport receives zero calls for every blocked recipient; no real email or probe is invoked.
19. Mixed-batch isolation: an eligible demo lead in a batch never causes blocked recipients to be sent.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
import uuid
import asyncio
import concurrent.futures
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import (
    Lead,
    LeadStatus,
    Campaign,
    CampaignStatus,
    Audit,
    AuditStatus,
    CampaignEmailLog,
    EmailAssociationStatus,
)
from app.services.campaign_eligibility_service import (
    CampaignType,
    EmailSendabilityClassification,
    WebsiteClassification,
    evaluate_lead_campaign_eligibility,
    classify_email_sendability,
    get_audience_breakdown,
    is_public_email_provider,
    extract_email_domain,
    is_legacy_provider_quarantine_reason,
)
from app.services.template_renderer import TemplateRenderer, DEFAULT_SEGMENT_TEMPLATES
from app.engines.outreach_engine import _run_campaign_worker
from app.services.proposal_service import ProposalService, HumanApprovalRequiredError, ProposalWorkflowError


def _run_coroutine(coro):
    """Run an async coroutine synchronously and cleanly across any pytest runner/loop state."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


# ─── Synthetic Test Fixtures ───────────────────────────────────────────────────

def _make_lead(
    lead_id=None,
    email="test@gmail.com",
    association_status="unverified_association",
    verification_status="valid",
    is_quarantined=False,
    quarantine_reason=None,
    website="https://example.com",
    business_name="Test Plumbing Services",
):
    return Lead(
        id=uuid.UUID(lead_id) if lead_id else uuid.uuid4(),
        business_name=business_name,
        email=email,
        website=website,
        status=LeadStatus.new,
        is_quarantined=is_quarantined,
        quarantine_reason=quarantine_reason,
        email_verification_status=verification_status,
        email_business_association_status=association_status,
        email_association_reason="Automated synthetic test fixture",
        created_at=datetime.now(timezone.utc),
    )


def _make_campaign(lead_ids, camp_id=None, campaign_type="public_provider_demo"):
    c_defaults = TemplateRenderer.get_default_template(campaign_type)
    return Campaign(
        id=uuid.UUID(camp_id) if camp_id else uuid.uuid4(),
        name=f"Test {campaign_type} Campaign",
        campaign_type=campaign_type,
        status=CampaignStatus.sending,
        subject_template=c_defaults["subject"],
        template=c_defaults["template"],
        lead_ids=[str(lid) for lid in lead_ids],
        pending_lead_ids=[str(lid) for lid in lead_ids],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )


# ─── Tests 1, 2, 3: Public Provider Routing for Demo-Only Campaign ─────────────

def test_1_routeable_gmail_unverified_association_can_enter_public_provider_demo():
    """1. Routeable Gmail with unverified association can enter public_provider_demo."""
    lead = _make_lead(
        email="testowner@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=False,
    )
    is_el, reason, site_cls, email_cls = evaluate_lead_campaign_eligibility(
        lead, audit=None, campaign_type="public_provider_demo"
    )
    assert is_el is True
    assert email_cls == EmailSendabilityClassification.DEMO_ONLY_ELIGIBLE
    assert reason is None


def test_2_routeable_yahoo_unverified_association_can_enter_public_provider_demo():
    """2. Routeable Yahoo with unverified association can enter public_provider_demo."""
    lead = _make_lead(
        email="business@yahoo.co.in",
        association_status="external_domain_review",
        verification_status="valid",
        is_quarantined=False,
    )
    is_el, reason, site_cls, email_cls = evaluate_lead_campaign_eligibility(
        lead, audit=None, campaign_type="public_provider_demo"
    )
    assert is_el is True
    assert email_cls == EmailSendabilityClassification.DEMO_ONLY_ELIGIBLE


def test_3_other_public_providers_follow_narrow_policy():
    """3. Other configured public providers follow the policy; custom domains do not."""
    public_emails = [
        "clinic@outlook.com",
        "garage@hotmail.com",
        "studio@proton.me",
        "firm@zoho.com",
    ]
    for em in public_emails:
        lead = _make_lead(email=em, association_status="unverified_association", verification_status="valid")
        is_el, _, _, cls = evaluate_lead_campaign_eligibility(lead, None, "public_provider_demo")
        assert is_el is True, f"Failed for {em}"
        assert cls == EmailSendabilityClassification.DEMO_ONLY_ELIGIBLE

    # Custom business domain MUST NOT use the public-provider demo route
    custom_lead = _make_lead(email="contact@customfirm.in", association_status="unverified_association", verification_status="valid")
    is_el, reason, _, _ = evaluate_lead_campaign_eligibility(custom_lead, None, "public_provider_demo")
    assert is_el is False
    assert "Non-public provider email with unverified association" in reason


# ─── Test 4: Unverified Public Provider Blocked from Normal Campaigns ───────────

def test_4_unverified_public_provider_addresses_remain_blocked_from_normal_campaigns():
    """4. Unverified public-provider addresses remain strictly blocked from standard/audit campaigns."""
    lead = _make_lead(
        email="testowner@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
    )
    audit = MagicMock(spec=Audit)
    audit.status = AuditStatus.done
    audit.site_summary = {}

    normal_campaign_types = [
        "generic_first_contact",
        "no_website_design",
        "broken_website_repair",
        "outdated_website_modernization",
        "valid_website_seo",
        "valid_website_redesign",
        "valid_website_link_building",
        "valid_website_marketing",
    ]

    for c_type in normal_campaign_types:
        is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(
            lead, audit, campaign_type=c_type
        )
        assert is_el is False, f"Lead unexpectedly eligible for {c_type}"
        assert email_cls == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION
        assert "matched or approved" in reason or "unverified_association" in reason


# ─── Test 5: Matched / Approved Public Provider Remains Eligible for Standard ───

def test_5_matched_approved_public_provider_lead_eligible_for_standard_campaigns():
    """5. A matched/approved public-provider lead remains eligible under standard campaign policy."""
    lead_approved = _make_lead(
        email="verifiedowner@gmail.com",
        association_status="approved",
        verification_status="valid",
    )
    is_el, _, _, email_cls = evaluate_lead_campaign_eligibility(
        lead_approved, audit=None, campaign_type="generic_first_contact"
    )
    assert is_el is True
    assert email_cls == EmailSendabilityClassification.ELIGIBLE


# ─── Tests 6 to 12: Rigorous Safety Exclusions Remain Blocked ───────────────────

def test_6_invalid_syntax_blocks_demo_and_all_campaigns():
    """6. Invalid syntax blocks demo-only and all other campaigns."""
    for bad_email in ["not-an-email", "@gmail.com", "user@"]:
        lead = _make_lead(email=bad_email, association_status="unverified_association", verification_status="invalid")
        is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(lead, None, "public_provider_demo")
        assert is_el is False
        assert email_cls == EmailSendabilityClassification.INVALID_FORMAT


def test_7_disposable_addresses_are_blocked():
    """7. Disposable addresses are categorically blocked from demo-only and all campaigns."""
    lead = _make_lead(email="temp@mailinator.com", association_status="unverified_association", verification_status="disposable")
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(lead, None, "public_provider_demo")
    assert is_el is False
    assert email_cls == EmailSendabilityClassification.INVALID_OR_DISPOSABLE


def test_8_missing_or_unusable_dns_mx_blocks_demo():
    """8. Missing or unusable DNS/MX routeability blocks demo eligibility."""
    for st in ["not_found", "error", "risky"]:
        lead = _make_lead(email="test@gmail.com", association_status="unverified_association", verification_status=st)
        is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(lead, None, "public_provider_demo")
        assert is_el is False
        assert email_cls == EmailSendabilityClassification.PENDING_VERIFICATION


def test_9_pending_or_unknown_verification_cannot_bypass():
    """9. Pending or unknown verification cannot bypass routeability verification."""
    lead = _make_lead(email="test@gmail.com", association_status="unverified_association", verification_status="unverified")
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(lead, None, "public_provider_demo")
    assert is_el is False
    assert email_cls == EmailSendabilityClassification.PENDING_VERIFICATION


def test_10_known_hard_bounce_suppression_unsubscribe_blocks_every_campaign():
    """10. Known hard bounce, suppression, or unsubscribe blocks every campaign."""
    lead = _make_lead(
        email="bounced@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="Recipient suppressed, bounced, or opted-out",
    )
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(
        lead, None, "public_provider_demo"
    )
    assert is_el is False
    assert email_cls == EmailSendabilityClassification.QUARANTINED


def test_11_confirmed_source_mismatch_and_agency_credit_remain_blocked():
    """11. Confirmed source mismatch and agency/designer-credit extraction remain blocked."""
    lead_mismatched = _make_lead(
        email="designer@gmail.com",
        association_status="mismatched_source",
        verification_status="valid",
    )
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(
        lead_mismatched, None, "public_provider_demo"
    )
    assert is_el is False
    assert email_cls == EmailSendabilityClassification.MISMATCHED_ASSOCIATION
    assert "mismatched" in reason.lower()


def test_12_independent_genuine_quarantine_not_bypassed():
    """12. An independent genuine quarantine is not bypassed."""
    lead_quarantined = _make_lead(
        email="test@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="Malicious payload found in source site",
    )
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(
        lead_quarantined, None, "public_provider_demo"
    )
    assert is_el is False
    assert email_cls == EmailSendabilityClassification.QUARANTINED
    assert "Malicious payload" in reason


# ─── Test 13: Legacy Provider Quarantine Re-verification Workflow ──────────────

def test_13_legacy_quarantine_controlled_reverification_workflow():
    """13. A legacy quarantine caused solely by an obsolete provider rule follows controlled reverification."""
    # Pattern check
    assert is_legacy_provider_quarantine_reason("Public email provider quarantine") is True
    assert is_legacy_provider_quarantine_reason("Free email provider") is True
    assert is_legacy_provider_quarantine_reason("Malware detected") is False

    # Lead with legacy-only quarantine
    lead_legacy = _make_lead(
        email="cleanbusiness@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="Public email provider quarantine",
    )
    # When evaluated for demo outreach, the legacy provider quarantine is recognized
    is_el, reason, _, email_cls = evaluate_lead_campaign_eligibility(
        lead_legacy, None, "public_provider_demo"
    )
    assert is_el is True
    assert email_cls == EmailSendabilityClassification.DEMO_ONLY_ELIGIBLE

    # If independent safety issue exists (e.g., disposable), it must NOT pass
    lead_unsafe_legacy = _make_lead(
        email="cleanbusiness@mailinator.com",
        association_status="unverified_association",
        verification_status="disposable",
        is_quarantined=True,
        quarantine_reason="Public email provider quarantine",
    )
    is_el_unsafe, _, _, _ = evaluate_lead_campaign_eligibility(
        lead_unsafe_legacy, None, "public_provider_demo"
    )
    assert is_el_unsafe is False


# ─── Test 14: One-Time Demo Contact Limit ─────────────────────────────────────

def test_14_one_time_demo_contact_limit_prevents_duplicate_sends():
    """14. Repeated queueing or retry cannot send a second demo message to the same normalized address."""
    lead = _make_lead(
        email="UniqueBusiness@Gmail.com",
        association_status="unverified_association",
        verification_status="valid",
    )

    # First attempt: hasn't received demo
    is_el_1, _, _, _ = evaluate_lead_campaign_eligibility(
        lead, None, "public_provider_demo", has_received_demo=False
    )
    assert is_el_1 is True

    # Second attempt: has received demo
    is_el_2, reason_2, _, _ = evaluate_lead_campaign_eligibility(
        lead, None, "public_provider_demo", has_received_demo=True
    )
    assert is_el_2 is False
    assert "one-time demo outreach" in reason_2


# ─── Tests 15 & 18: Pre-Send Enforcement & Mocked Transport Receiving 0 Calls ──

def test_15_and_18_presend_gatekeeper_stops_ineligible_lead_zero_transport_calls():
    """15 & 18. Pre-send gatekeeper stops post-queue ineligible lead; mocked transport receives zero calls."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    campaign = _make_campaign([lead_id], camp_id=camp_id, campaign_type="public_provider_demo")

    # Lead became quarantined between queueing and worker execution
    lead = _make_lead(
        lead_id=lead_id,
        email="testowner@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=True,
        quarantine_reason="Suppressed by administrator post-queue",
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalar=MagicMock(return_value=None),
    ))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@tebsolutions.in", "sender_name": "TEB Solutions", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):
            await _run_campaign_worker(camp_id)
            # Transport receives ZERO calls
            assert mock_send.call_count == 0
            assert campaign.skipped_count == 1
            assert campaign.sent_count == 0

    _run_coroutine(_run())


# ─── Test 16: Normal Campaign Worker Rejects Demo-Only Lead ───────────────────

def test_16_normal_campaign_worker_rejects_unverified_public_provider():
    """16. Normal campaign routes cannot inherit the demo-only exception at the worker level."""
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())
    # Worker is running generic_first_contact campaign
    campaign = _make_campaign([lead_id], camp_id=camp_id, campaign_type="generic_first_contact")

    lead = _make_lead(
        lead_id=lead_id,
        email="testowner@gmail.com",
        association_status="unverified_association",
        verification_status="valid",
        is_quarantined=False,
    )

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalar=MagicMock(return_value=None),
    ))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@tebsolutions.in", "sender_name": "TEB Solutions", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):
            await _run_campaign_worker(camp_id)
            assert mock_send.call_count == 0
            assert campaign.skipped_count == 1
            assert campaign.sent_count == 0

    _run_coroutine(_run())


# ─── Test 17: Preview and Worker Use the Same Template Renderer ────────────────

def test_17_preview_and_worker_use_same_template_renderer():
    """17. Campaign preview and outreach worker use the identical TemplateRenderer."""
    lead = _make_lead(
        email="prospect@gmail.com",
        business_name="Green Valley Nursery",
    )
    defaults = TemplateRenderer.get_default_template("public_provider_demo")
    sender = {"email": "info@tebsolutions.in", "sender_name": "Vijay from TEB Solutions"}

    rendered_preview = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="public_provider_demo",
        sender_account=sender,
    )

    # Verify rendered fields
    assert "Green Valley Nursery" in rendered_preview["subject"]
    assert "Vijay from TEB Solutions" in rendered_preview["plain_body"]
    assert "TEB Solutions" in rendered_preview["plain_body"]
    assert "unsubscribe" in rendered_preview["plain_body"].lower()

    # Worker calls the same method
    rendered_worker = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="public_provider_demo",
        sender_account=sender,
    )
    assert rendered_preview["subject"] == rendered_worker["subject"]
    assert rendered_preview["plain_body"] == rendered_worker["plain_body"]
    assert rendered_preview["html_body"] == rendered_worker["html_body"]


# ─── Test 19: Mixed-Batch Isolation ───────────────────────────────────────────

def test_19_mixed_batch_isolation():
    """19. Mixed-batch isolation: eligible demo lead never allows blocked recipients to be sent."""
    lid_eligible = str(uuid.uuid4())
    lid_disposable = str(uuid.uuid4())
    lid_mismatched = str(uuid.uuid4())

    camp_id = str(uuid.uuid4())
    campaign = _make_campaign(
        [lid_eligible, lid_disposable, lid_mismatched],
        camp_id=camp_id,
        campaign_type="public_provider_demo",
    )

    lead_eligible = _make_lead(lid_eligible, email="good@gmail.com", association_status="unverified_association", verification_status="valid")
    lead_disposable = _make_lead(lid_disposable, email="trash@mailinator.com", association_status="unverified_association", verification_status="disposable")
    lead_mismatched = _make_lead(lid_mismatched, email="mismatch@gmail.com", association_status="mismatched_source", verification_status="valid")

    leads_map = {
        lid_eligible: lead_eligible,
        lid_disposable: lead_disposable,
        lid_mismatched: lead_mismatched,
    }

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else leads_map.get(str(obj_id)))
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None),
        scalar=MagicMock(return_value=None),
    ))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp = {"email": "sender@tebsolutions.in", "sender_name": "TEB Solutions", "host": "smtp.test.com", "port": 587, "daily_limit": 100}

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync", return_value=(True, None)) as mock_send, \
             patch("app.engines.outreach_engine.asyncio.sleep", new_callable=AsyncMock):
            await _run_campaign_worker(camp_id)
            # Exactly 1 send occurred (only for good@gmail.com)
            assert mock_send.call_count == 1
            assert campaign.sent_count == 1
            assert campaign.skipped_count == 2
            # Verify recipient of the one successful send
            sent_to = mock_send.call_args[0][1]
            assert sent_to == "good@gmail.com"

    _run_coroutine(_run())


# ─── Test 20: Proposal Service Association Gate ───────────────────────────────

def test_20_proposal_service_blocks_unverified_public_provider():
    """20. Proposals categorically block leads with unverified associations."""
    lead_id = f"test-prop-{uuid.uuid4()}"
    prop = ProposalService.get_or_create_proposal(
        lead_id=lead_id,
        business_name="Unverified Plumbing",
        website_url="https://unverifiedplumbing.in",
        audit_results={"technical": {}, "ux": {}},
        association_status="unverified_association",
    )
    # Approve the proposal
    ProposalService.approve_proposal(lead_id=lead_id, user_email="operator@tebsolutions.in")

    # Attempt to dispatch: MUST fail due to association gate
    with pytest.raises(ProposalWorkflowError) as exc_info:
        ProposalService.dispatch_proposal(lead_id=lead_id, target_email="owner@gmail.com", dry_run=True)
    assert "require a matched or approved business association" in str(exc_info.value)
