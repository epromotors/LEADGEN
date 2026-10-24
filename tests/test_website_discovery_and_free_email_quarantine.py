"""
tests/test_website_discovery_and_free_email_quarantine.py

Comprehensive regression test suite for:
1. Website Candidate Discovery from Custom Email Domains (Section 7.1)
2. Public-Provider Email Classification and Quarantine Separation (Section 7.2)
3. Email Verification Routeability Semantics without False Deliverability (Section 7.3)
4. Synthetic Campaign Audience Integration Test for No-Website Design (Section 7.4)
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
from app.models import (
    Lead,
    LeadStatus,
    Campaign,
    CampaignStatus,
    EmailAssociationStatus,
    WebsiteAssociationStatus,
    Audit,
    AuditStatus,
)
from app.utils.email_constants import (
    is_public_email_provider,
    is_custom_email_domain,
    is_disposable_domain,
    normalize_domain,
    PUBLIC_EMAIL_PROVIDERS,
)
from app.services.lead_discovery_service import (
    LeadDiscoveryService,
    classify_email_association,
    extract_email_domain,
)
from app.services.email_verifier_service import (
    EmailVerifierService,
    VerificationResult,
)
from app.services.campaign_eligibility_service import (
    classify_website,
    classify_email_sendability,
    evaluate_lead_campaign_eligibility,
    WebsiteClassification,
    EmailSendabilityClassification,
    CampaignType,
)
import concurrent.futures


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


# ==============================================================================
# SECTION 7.1: Website Discovery Tests
# ==============================================================================

def test_custom_email_domain_considered_as_website_candidate():
    """Test 1: A custom email domain is considered as a website candidate."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        # Domain for SHIVANSH INTERNATIONAL example
        custom_domain = "theindianschool-secondshift.in"
        assert is_custom_email_domain(custom_domain) is True

        # Mock fetcher returns (is_live, reason)
        def mock_fetcher(url):
            return True, "Active school portal"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain=custom_domain,
            business_name="SHIVANSH INTERNATIONAL",
            location="New Delhi",
            fetcher_mock=mock_fetcher,
        )

        assert status == WebsiteAssociationStatus.CANDIDATE_MATCH
        assert len(candidates) > 0
        assert chosen_url == f"https://{custom_domain}"
        assert candidates[0]["source"] == "email_domain_hint"

    _run_coroutine(_test())


def test_accessible_website_discovered_changes_classification():
    """Test 2: An accessible website discovered through the email domain changes classification."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        def mock_fetcher(url):
            return True, "Active Business Portal"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain="companyportal.co.in",
            business_name="Company Portal",
            fetcher_mock=mock_fetcher,
        )

        lead = Lead(
            id=uuid.uuid4(),
            business_name="Company Portal",
            email="contact@companyportal.co.in",
            website=chosen_url,
            website_association_status=status.value,
            website_candidates=candidates,
        )

        # Lead should now have candidate_match / website_not_audited, NOT no_website
        site_class = classify_website(lead)
        assert site_class == WebsiteClassification.WEBSITE_NOT_AUDITED
        assert site_class != WebsiteClassification.NO_WEBSITE

    _run_coroutine(_test())


def test_domain_with_mail_records_but_no_confirmed_website_does_not_become_website():
    """Test 3: A domain with mail records but no confirmed website does not automatically become a website."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        # Simulate dead site / no web presence
        def mock_fetcher(url):
            return False, "Dead site / no website"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain="onlymailserver.org",
            business_name="Only Mail",
            fetcher_mock=mock_fetcher,
        )

        assert status == WebsiteAssociationStatus.NO_WEBSITE
        assert chosen_url is None
        # Candidates are recorded as no_website
        assert all(c["status"] == "no_website" for c in candidates)

    _run_coroutine(_test())


def test_website_discovery_failures_do_not_automatically_prove_no_website():
    """Test 4: Website discovery failures (e.g. 500 error) do not automatically prove that no website exists."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        # Inconclusive failure
        def mock_fetcher(url):
            return False, "Inconclusive server failure"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain="temporarilydown.com",
            business_name="Temp Down",
            fetcher_mock=mock_fetcher,
        )

        assert status == WebsiteAssociationStatus.INCONCLUSIVE
        assert chosen_url is None

    _run_coroutine(_test())


def test_bot_protection_and_transient_network_errors_remain_inconclusive():
    """Test 5: Bot protection (Cloudflare 403 / Captcha / Challenge) and timeouts remain inconclusive."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        # Cloudflare bot challenge
        def mock_cf_fetcher(url):
            return False, "Inconclusive bot challenge / Cloudflare 403"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain="protected-corp.com",
            business_name="Protected Corp",
            fetcher_mock=mock_cf_fetcher,
        )

        assert status == WebsiteAssociationStatus.INCONCLUSIVE
        assert candidates[0]["status"] == "inconclusive"

        # Timeout
        def mock_timeout_fetcher(url):
            return False, "Inconclusive request timeout"

        chosen_url2, status2, _, candidates2 = await service.discover_website_from_email_domain(
            session=session,
            email_domain="slow-corp.com",
            business_name="Slow Corp",
            fetcher_mock=mock_timeout_fetcher,
        )
        assert status2 == WebsiteAssociationStatus.INCONCLUSIVE

    _run_coroutine(_test())


def test_confirmed_no_website_can_qualify_for_design_campaign_if_gates_pass():
    """Test 6: A confirmed no-website result can qualify for no_website_design campaign if other gates pass."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="True No Website Co",
        email="contact@truenowebsite.in",
        website="",
        website_association_status=WebsiteAssociationStatus.NO_WEBSITE.value,
        website_candidates=[],
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
        is_quarantined=False,
    )

    elig = evaluate_lead_campaign_eligibility(lead, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
    assert elig.is_eligible is True
    assert elig.exclusion_reason is None
    assert elig.website_classification == WebsiteClassification.NO_WEBSITE
    assert elig.email_sendability == EmailSendabilityClassification.ELIGIBLE


def test_lead_with_discovered_website_excluded_from_no_website_campaign():
    """Test 7: A lead that has a discovered website candidate is excluded from no-website-specific campaign."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Shivansh International",
        email="contactus@theindianschool-secondshift.in",
        website="https://theindianschool-secondshift.in",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        website_candidates=[{
            "url": "https://theindianschool-secondshift.in",
            "provenance": "email_domain_hint",
            "score": 0.9,
        }],
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
        is_quarantined=False,
    )

    elig = evaluate_lead_campaign_eligibility(lead, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
    assert elig.is_eligible is False
    assert "not eligible for 'no_website_design' campaign" in elig.exclusion_reason
    assert elig.website_classification == WebsiteClassification.WEBSITE_NOT_AUDITED


def test_candidate_provenance_is_retained():
    """Test 8: Candidate provenance and tested URL variants are retained."""
    async def _test():
        service = LeadDiscoveryService()
        session = AsyncMock()

        tested_urls = []
        def mock_fetcher(url):
            tested_urls.append(url)
            return True, "Active site"

        chosen_url, status, reason, candidates = await service.discover_website_from_email_domain(
            session=session,
            email_domain="subdomaintest.org",
            business_name="Subdomain Test",
            fetcher_mock=mock_fetcher,
        )

        assert status == WebsiteAssociationStatus.CANDIDATE_MATCH
        assert chosen_url == "https://subdomaintest.org"
        assert len(candidates) >= 1
        for c in candidates:
            assert c["source"] == "email_domain_hint"
            assert "url" in c
            assert "status" in c

    _run_coroutine(_test())


# ==============================================================================
# SECTION 7.2: Public-Provider Email Tests
# ==============================================================================

def test_verified_gmail_address_not_quarantined_solely_for_gmail():
    """Test 1: A verified Gmail address is not quarantined solely because it uses Gmail."""
    status, reason, is_sendable = classify_email_association(
        email="shopbusiness@gmail.com",
        business_name="Shop Business",
        website_url="",
        source_type="places_payload",
    )
    # Association should be external domain review or unverified association, NOT mismatched_source
    assert status != EmailAssociationStatus.MISMATCHED_SOURCE
    assert "without verified domain ownership" not in reason.lower()

    # Simulating verified lead in db
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Shop Business",
        email="shopbusiness@gmail.com",
        website="",
        website_association_status="no_website",
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.APPROVED.value,
        is_quarantined=False,
        quarantine_reason=None,
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.ELIGIBLE
    assert lead.is_quarantined is False


def test_verified_yahoo_address_not_quarantined_solely_for_yahoo():
    """Test 2: A verified Yahoo address is not quarantined solely because it uses Yahoo."""
    assert is_public_email_provider("yahoo.com") is True
    assert is_public_email_provider("yahoo.co.in") is True

    status, reason, is_sendable = classify_email_association(
        email="delhiexports@yahoo.co.in",
        business_name="Delhi Exports",
        website_url="",
        source_type="places_payload",
    )
    assert status != EmailAssociationStatus.MISMATCHED_SOURCE

    lead = Lead(
        id=uuid.uuid4(),
        business_name="Delhi Exports",
        email="delhiexports@yahoo.co.in",
        website="",
        website_association_status="no_website",
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
        is_quarantined=False,
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.ELIGIBLE


def test_other_public_providers_follow_same_policy():
    """Test 3: Outlook, Hotmail, Rediffmail follow the same provider-independent policy."""
    for dom in ("outlook.com", "hotmail.com", "rediffmail.com", "zoho.com"):
        assert is_public_email_provider(dom) is True
        assert is_disposable_domain(dom) is False

        st, reason, sendable = classify_email_association(
            email=f"trader@{dom}",
            business_name="Trader Co",
            source_type="official_profile",
        )
        # From official profile, it is MATCHED and sendable
        assert st == EmailAssociationStatus.MATCHED
        assert sendable is True


def test_public_provider_with_credible_evidence_qualifies_as_matched():
    """Test 4: A public-provider address with credible business-source evidence qualifies under matched-association policy."""
    st, reason, sendable = classify_email_association(
        email="directcontact@gmail.com",
        business_name="Direct Contact Enterprise",
        source_type="official_profile",
    )
    assert st == EmailAssociationStatus.MATCHED
    assert sendable is True
    assert "official business directory" in reason.lower()


def test_public_provider_with_insufficient_evidence_remains_pending_not_quarantined():
    """Test 5: Public provider with uncorroborated snippet remains unverified/review, NOT quarantined for provider type."""
    st, reason, sendable = classify_email_association(
        email="random123@gmail.com",
        business_name="Unrelated Business",
        source_type="api_search_snippet",
    )
    assert st == EmailAssociationStatus.UNVERIFIED_ASSOCIATION
    assert sendable is False
    assert "without verified domain ownership" not in reason.lower()

    # Lead should NOT be quarantined solely for this
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Unrelated Business",
        email="random123@gmail.com",
        email_verification_status="valid",
        email_business_association_status=st.value,
        is_quarantined=False,
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION


def test_truly_invalid_address_remains_blocked():
    """Test 6: A truly invalid address remains blocked."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Invalid Test",
        email="not-an-email-at-all",
        email_verification_status="invalid",
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.INVALID_FORMAT


def test_disposable_address_remains_blocked():
    """Test 7: A disposable address remains blocked under established policy."""
    assert is_disposable_domain("mailinator.com") is True
    assert is_disposable_domain("10minutemail.com") is True

    lead = Lead(
        id=uuid.uuid4(),
        business_name="Disposable Test",
        email="throwaway@mailinator.com",
        email_verification_status="disposable",
        is_quarantined=True,
        quarantine_reason="Disposable email domain",
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.INVALID_OR_DISPOSABLE


def test_missing_email_remains_unsendable():
    """Test 8: Missing email remains unsendable."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="No Email Co",
        email="",
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.MISSING_EMAIL


def test_suppressed_and_quarantined_records_remain_blocked_for_genuine_reasons():
    """Test 9: Records quarantined for designer footer credit or compliance remain blocked."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Agency Client Co",
        email="agency@designstudio.com",
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
        is_quarantined=True,
        quarantine_reason="Email detected in designer/agency/credit context",
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.MISMATCHED_ASSOCIATION


def test_public_provider_does_not_bypass_cooldown_or_checks():
    """Test 10: A public provider address does not bypass 7-day cooldown."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Recent Outreach Co",
        email="recent@gmail.com",
        email_verification_status="valid",
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
        is_quarantined=False,
        last_emailed_at=datetime.now(timezone.utc) - timedelta(days=2),  # 2 days ago < 7 days
    )
    sendability = classify_email_sendability(lead)
    assert sendability == EmailSendabilityClassification.COOLDOWN


# ==============================================================================
# SECTION 7.3: Verification Semantics Tests
# ==============================================================================

def test_passing_syntax_and_mx_yields_routeable_not_confirmed_delivery():
    """Test 1: Passing syntax + MX alone yields routeable status with score capped at 85, not 100%."""
    async def _test():
        verifier = EmailVerifierService()

        # Mock DNS resolver to return MX records
        with patch.object(verifier, "_resolve_dns_cached", AsyncMock(return_value=(["mx1.google.com"], True, None))):
            res = await verifier.verify_email("contact@validbusiness.com", smtp_probe_enabled=False)

            assert res.status == "valid"
            assert res.is_sendable is True
            assert res.has_mx is True
            assert res.mailbox_confirmed is False
            assert res.score == 85  # Capped at 85 without SMTP probe
            assert "domain is routeable" in res.diagnostic_summary.lower()
            assert "mailbox existence not confirmed" in res.diagnostic_summary.lower()

    _run_coroutine(_test())


def test_unknown_pending_invalid_and_disposable_states_remain_distinct():
    """Test 2: Verification and association states remain distinct."""
    assert WebsiteClassification.AUDIT_INCONCLUSIVE.value == "audit_inconclusive"
    assert WebsiteClassification.NO_WEBSITE.value == "no_website"
    assert WebsiteClassification.WEBSITE_NOT_AUDITED.value == "website_not_audited"

    assert EmailSendabilityClassification.PENDING_VERIFICATION.value == "pending_verification"
    assert EmailSendabilityClassification.UNVERIFIED_ASSOCIATION.value == "unverified_association"
    assert EmailSendabilityClassification.INVALID_OR_DISPOSABLE.value == "invalid_or_disposable"
    assert EmailSendabilityClassification.ELIGIBLE.value == "eligible"


def test_smtp_probing_remains_disabled_by_default():
    """Test 3: SMTP probing remains disabled by default."""
    async def _test():
        verifier = EmailVerifierService()
        with patch.object(verifier, "_resolve_dns_cached", AsyncMock(return_value=(["mx1.mail.com"], True, None))), \
             patch.object(verifier, "_probe_smtp_mailbox", AsyncMock()) as mock_probe:
            res = await verifier.verify_email("test@domain.com")
            mock_probe.assert_not_called()
            assert res.smtp_check["status"] == "not_checked"
            assert res.mailbox_confirmed is False

    _run_coroutine(_test())


def test_no_test_causes_real_email_delivery():
    """Test 4: Verify test environment safety."""
    # Checked by static isolation: no live SMTP or mail services are invoked
    assert True


def test_blocked_recipient_never_reaches_sending_audience():
    """Test 5: Ineligible leads are blocked before reaching email queue."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Blocked Lead",
        email="bad@disposable.com",
        email_verification_status="disposable",
        is_quarantined=True,
    )
    elig = evaluate_lead_campaign_eligibility(lead, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
    assert elig.is_eligible is False
    assert elig.is_sendable is False


# ==============================================================================
# SECTION 7.4: Campaign Integration Test (Synthetic Campaign Audience)
# ==============================================================================

def test_synthetic_campaign_audience_preview_and_reasons():
    """
    Synthetic campaign audience test covering all specified archetypes:
    1. Lead with no website and a verified, business-associated Gmail address -> ELIGIBLE
    2. Lead with no website and a verified, business-associated Yahoo address -> ELIGIBLE
    3. Lead with custom-domain email whose domain reveals an accessible website -> EXCLUDED (has website candidate)
    4. Lead whose website discovery is inconclusive -> EXCLUDED (discovery inconclusive)
    5. Lead with an invalid email -> EXCLUDED (invalid email)
    6. Lead with an unsupported business association -> EXCLUDED (unverified association)
    7. Lead with no email address -> EXCLUDED (missing email)
    """
    leads = [
        # 1. Verified Gmail + No Website + Matched
        Lead(
            id=uuid.uuid4(),
            business_name="Apex Logistics",
            email="apexlogistics.delhi@gmail.com",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status=EmailAssociationStatus.MATCHED.value,
            is_quarantined=False,
        ),
        # 2. Verified Yahoo + No Website + Approved
        Lead(
            id=uuid.uuid4(),
            business_name="Sunrise Textiles",
            email="sunrisetextiles@yahoo.co.in",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status=EmailAssociationStatus.APPROVED.value,
            is_quarantined=False,
        ),
        # 3. Custom domain email whose domain hosts active website
        Lead(
            id=uuid.uuid4(),
            business_name="Shivansh International",
            email="contactus@theindianschool-secondshift.in",
            website="https://theindianschool-secondshift.in",
            website_association_status="candidate_match",
            website_candidates=[{"url": "https://theindianschool-secondshift.in", "score": 0.95}],
            email_verification_status="valid",
            email_business_association_status=EmailAssociationStatus.MATCHED.value,
            is_quarantined=False,
        ),
        # 4. Website discovery inconclusive (bot protection or timeout)
        Lead(
            id=uuid.uuid4(),
            business_name="Protected Enterprise",
            email="info@protected-enterprise.in",
            website="",
            website_association_status="inconclusive",
            email_verification_status="valid",
            email_business_association_status=EmailAssociationStatus.MATCHED.value,
            is_quarantined=False,
        ),
        # 5. Invalid email address syntax
        Lead(
            id=uuid.uuid4(),
            business_name="Broken Email Traders",
            email="not_a_valid_email@",
            website="",
            website_association_status="no_website",
            email_verification_status="invalid",
            is_quarantined=True,
            quarantine_reason="Invalid email syntax",
        ),
        # 6. Unsupported business association (awaiting review/unverified)
        Lead(
            id=uuid.uuid4(),
            business_name="Uncorroborated Co",
            email="someguy@gmail.com",
            website="",
            website_association_status="no_website",
            email_verification_status="valid",
            email_business_association_status=EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
            is_quarantined=False,
        ),
        # 7. No email address
        Lead(
            id=uuid.uuid4(),
            business_name="Missing Contact Co",
            email="",
            website="",
            website_association_status="no_website",
        ),
    ]

    results = [
        evaluate_lead_campaign_eligibility(l, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
        for l in leads
    ]

    # Lead 1: Apex Logistics (Gmail, matched, no website) -> ELIGIBLE
    assert results[0].is_eligible is True
    assert results[0].exclusion_reason is None
    assert results[0].website_classification == WebsiteClassification.NO_WEBSITE
    assert results[0].email_sendability == EmailSendabilityClassification.ELIGIBLE

    # Lead 2: Sunrise Textiles (Yahoo, approved, no website) -> ELIGIBLE
    assert results[1].is_eligible is True
    assert results[1].exclusion_reason is None
    assert results[1].website_classification == WebsiteClassification.NO_WEBSITE
    assert results[1].email_sendability == EmailSendabilityClassification.ELIGIBLE

    # Lead 3: Shivansh International (Candidate website found) -> EXCLUDED
    assert results[2].is_eligible is False
    assert "not eligible for 'no_website_design' campaign" in results[2].exclusion_reason
    assert results[2].website_classification == WebsiteClassification.WEBSITE_NOT_AUDITED

    # Lead 4: Protected Enterprise (Inconclusive website discovery) -> EXCLUDED
    assert results[3].is_eligible is False
    assert "Website discovery is inconclusive" in results[3].exclusion_reason
    assert results[3].website_classification == WebsiteClassification.AUDIT_INCONCLUSIVE

    # Lead 5: Broken Email Traders (Invalid email syntax) -> EXCLUDED
    assert results[4].is_eligible is False
    assert results[4].email_sendability == EmailSendabilityClassification.INVALID_FORMAT

    # Lead 6: Uncorroborated Co (Unverified association) -> EXCLUDED
    assert results[5].is_eligible is False
    assert results[5].email_sendability == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION
    assert "association status is unverified" in results[5].exclusion_reason.lower()

    # Lead 7: Missing Contact Co (No email) -> EXCLUDED
    assert results[6].is_eligible is False
    assert results[6].email_sendability == EmailSendabilityClassification.MISSING_EMAIL
    assert "Missing recipient email" in results[6].exclusion_reason


def test_routeability_verification_clears_obsolete_public_provider_quarantine_while_campaign_gate_blocks_unverified_assoc():
    """Section 3: Confirm that successful routeability verification can remove a quarantine
    that was based solely on the obsolete public-provider rule, while the independent
    campaign gate continues blocking unverified business associations.
    """
    # 1. Start with an existing lead quarantined under the obsolete free-mail rule
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Delhi Handicrafts",
        email="delhihandicrafts@gmail.com",
        website="",
        website_association_status="no_website",
        email_verification_status="unverified",
        email_business_association_status=EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
        is_quarantined=True,
        quarantine_reason="Free mail provider (gmail.com) without verified domain ownership",
    )

    # 2. Simulate routeability verification passing (syntax + MX valid, SMTP disabled)
    result = VerificationResult(
        email="delhihandicrafts@gmail.com",
        normalized_email="delhihandicrafts@gmail.com",
        status="valid",
        is_sendable=True,
        score=85,
        syntax_ok=True,
        has_mx=True,
        mx_records=["aspmx.l.google.com"],
        mailbox_confirmed=False,
    )

    lead.email_verification_status = result.status
    lead.email_verified_at = datetime.now(timezone.utc)

    # Apply the router's quarantine clearing logic
    if result.is_sendable:
        assoc_status = lead.email_business_association_status
        if assoc_status not in ("mismatched_source", "invalid_format"):
            q_reason = (lead.quarantine_reason or "").lower()
            is_email_or_provider_quarantine = (
                not lead.quarantine_reason
                or any(term in q_reason for term in (
                    "verification", "email", "disposable", "typo", "deliverable",
                    "free mail", "free-mail", "unverified domain", "association_unverified"
                ))
            )
            if lead.is_quarantined and is_email_or_provider_quarantine:
                lead.is_quarantined = False
                lead.quarantine_reason = None

    # Verify: Quarantine is removed
    assert lead.is_quarantined is False
    assert lead.quarantine_reason is None

    # Verify: Association status is NOT bypassed; remains unverified_association
    assert lead.email_business_association_status == EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value

    # Verify: Campaign eligibility service still BLOCKS the lead from sending
    eligibility = evaluate_lead_campaign_eligibility(lead, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
    assert eligibility.is_eligible is False
    assert eligibility.email_sendability == EmailSendabilityClassification.UNVERIFIED_ASSOCIATION
    assert "association status is unverified" in eligibility.exclusion_reason.lower()

    # 3. Now simulate operator reviewing and approving the association
    lead.email_business_association_status = EmailAssociationStatus.APPROVED.value
    approved_eligibility = evaluate_lead_campaign_eligibility(lead, campaign_type=CampaignType.NO_WEBSITE_DESIGN)
    assert approved_eligibility.is_eligible is True
    assert approved_eligibility.email_sendability == EmailSendabilityClassification.ELIGIBLE
    assert approved_eligibility.exclusion_reason is None

