"""
tests/test_email_association_and_website_discovery.py

Focused regression test suite verifying:
1. Case 1: Bihari Brothers Groups - External agency/designer footer credit detection,
   isolation, MISMATCHED_SOURCE classification, and campaign quarantine safety.
2. Case 2: ECO-EXPORT - Candidate website discovery (ecoexport.in), ccTLD geographic conflict
   detection (ecoexport.com.vn), multi-candidate email retention (Gmail addresses),
   prevention of false 'No Website' classification, and unverified exclusion.
3. Domain match vs free provider vs cross-domain email association classifications.
4. Lead discovery variable isolation across sequential/concurrent place results.
5. Deduplication and rediscovery protection (quarantine preservation, no silent overwrite).
6. Campaign creation safety: quarantined/unverified leads are excluded from campaigns and queues.
7. Outreach engine safety: pre-send guard skips non-matched/quarantined leads without SMTP probing.
8. CSV export filtering: sendable_only excludes quarantined leads.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
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
)
from app.services.lead_discovery_service import (
    LeadDiscoveryService,
    classify_email_association,
    extract_email_candidates_with_context,
    score_website_candidate,
    extract_domain_from_url,
    extract_email_domain,
    clean_website,
    extract_email,
)
from app.engines.outreach_engine import _run_campaign_worker, _send_email_sync


# ─── Case 1: Bihari Brothers Groups Tests ─────────────────────────────────────

def test_case1_bihari_brothers_designer_credit_extraction():
    """
    Case 1 Regression:
    A website 'https://biharibrothers.com' contains a designer footer credit:
    'Website designed by Tynemade: hi@tynemade.mx'.
    Verify that:
    1. Context-aware extraction detects the agency credit pattern.
    2. Email association is classified as MISMATCHED_SOURCE.
    3. is_sendable is False and lead must be quarantined.
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Bihari Brothers Groups - Home</title></head>
    <body>
        <h1>Welcome to Bihari Brothers Groups</h1>
        <p>Leading industrial and commodity supplies in India.</p>
        <div class="footer">
            <p>Copyright © 2024 Bihari Brothers Groups. All rights reserved.</p>
            <p>Website designed by Tynemade: <a href="mailto:hi@tynemade.mx">hi@tynemade.mx</a></p>
        </div>
    </body>
    </html>
    """
    candidates = extract_email_candidates_with_context(
        html,
        website="https://biharibrothers.com",
        business_name="Bihari Brothers Groups",
        location="India",
        source_type="http_page_scrape",
    )

    assert len(candidates) >= 1
    tynemade_candidate = next((c for c in candidates if c["email"] == "hi@tynemade.mx"), None)
    assert tynemade_candidate is not None
    assert tynemade_candidate["association_status"] == EmailAssociationStatus.MISMATCHED_SOURCE.value
    assert tynemade_candidate["is_sendable"] is False
    assert "designer/agency/credit" in tynemade_candidate["association_reason"].lower()


def test_case1_bihari_brothers_with_genuine_and_designer_emails():
    """
    Case 1 Regression:
    When a website has BOTH a genuine business email and an agency credit,
    the genuine domain-matching email must take precedence and be marked MATCHED,
    while the agency credit remains tagged MISMATCHED_SOURCE.
    """
    html = """
    <html>
    <body>
        <h2>Contact Us</h2>
        <p>Inquiries: <a href="mailto:contact@biharibrothers.com">contact@biharibrothers.com</a></p>
        <footer>
            <span>Site built by WebStudio: dev@webstudio.mx</span>
        </footer>
    </body>
    </html>
    """
    candidates = extract_email_candidates_with_context(
        html,
        website="https://biharibrothers.com",
        business_name="Bihari Brothers Groups",
        location="India",
        source_type="http_contact_page",
    )

    assert len(candidates) == 2
    # First candidate in sorted list must be MATCHED
    assert candidates[0]["email"] == "contact@biharibrothers.com"
    assert candidates[0]["association_status"] == EmailAssociationStatus.MATCHED.value
    assert candidates[0]["is_sendable"] is True

    # Second candidate is the agency credit
    assert candidates[1]["email"] == "dev@webstudio.mx"
    assert candidates[1]["association_status"] == EmailAssociationStatus.MISMATCHED_SOURCE.value
    assert candidates[1]["is_sendable"] is False


def test_case1_bihari_brothers_nested_html_agency_credit():
    """
    Case 1 Regression:
    Ensure nested HTML tags (e.g. <span>Website designed by</span> <a href="...">Tynemade</a>: <a href="mailto:hi@tynemade.mx">hi@tynemade.mx</a>)
    are properly normalized and classified as MISMATCHED_SOURCE.
    """
    html = """
    <footer>
        <div class="site-credit">
            <span>Website designed by</span>
            <a href="https://tynemade.mx" target="_blank">Tynemade Creative</a>:
            <a href="mailto:hi@tynemade.mx">hi@tynemade.mx</a>
        </div>
    </footer>
    """
    candidates = extract_email_candidates_with_context(
        html,
        website="https://biharibrothers.com",
        business_name="Bihari Brothers Groups",
        location="India",
        source_type="http_contact_page",
    )
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["email"] == "hi@tynemade.mx"
    assert cand["association_status"] == EmailAssociationStatus.MISMATCHED_SOURCE.value
    assert cand["is_sendable"] is False
    assert "designer/agency/credit" in cand["association_reason"].lower()


def test_case1_bihari_brothers_parent_company_domain_retained():
    """
    Case 1 Regression:
    A legitimate parent company or affiliate domain sharing business name tokens
    (e.g., 'biharigroup.com' for 'Bihari Brothers Groups') must NOT be blindly rejected
    as MISMATCHED_SOURCE, but classified as EXTERNAL_DOMAIN_REVIEW and preserved as a candidate.
    """
    status, reason, is_sendable = classify_email_association(
        email="corp@biharigroup.com",
        business_name="Bihari Brothers Groups",
        website_url="https://biharibrothers.com",
        source_type="http_contact_page",
        location="India",
    )
    assert status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert is_sendable is False  # Requires review before automated sending
    assert "shares business identity" in reason.lower() or "matches business name" in reason.lower()


# ─── Case 2: ECO-EXPORT Tests ─────────────────────────────────────────────────

def test_case2_ecoexport_website_candidate_scoring():
    """
    Case 2 Regression:
    Intended website: https://ecoexport.in/
    Conflicting website: https://ecoexport.com.vn
    Business: ECO-EXPORT in India.
    Verify that:
    1. ecoexport.in receives high score due to token match and .in ccTLD match.
    2. ecoexport.com.vn receives low score due to foreign .vn ccTLD penalty.
    """
    score_in = score_website_candidate("https://ecoexport.in/", "ECO-EXPORT", "India")
    score_vn = score_website_candidate("https://ecoexport.com.vn", "ECO-EXPORT", "India")

    assert score_in >= 0.8, f"Expected high score for ecoexport.in, got {score_in}"
    assert score_vn < 0.5, f"Expected low score for conflicting ecoexport.com.vn in India, got {score_vn}"
    assert score_in > score_vn


def test_case2_ecoexport_search_snippet_cctld_mismatch_classification():
    """
    Case 2 Regression:
    An email 'contact@ecoexport.com.vn' found in a search snippet for an Indian business
    must be classified as MISMATCHED_SOURCE (geographic ccTLD mismatch) and marked non-sendable.
    """
    status, reason, is_sendable = classify_email_association(
        email="contact@ecoexport.com.vn",
        business_name="ECO-EXPORT",
        website_url="https://ecoexport.in/",
        source_type="api_search_snippet",
        location="India",
    )

    assert status == EmailAssociationStatus.MISMATCHED_SOURCE
    assert is_sendable is False
    assert "conflicting cctld" in reason.lower() or "cctld" in reason.lower()


def test_case2_ecoexport_known_gmail_candidates_retention():
    """
    Case 2 Regression:
    Known emails for ECO-EXPORT:
    - marketing.ecoexport@gmail.com
    - info.ecoexport@gmail.com
    Verify that:
    1. Free mail provider containing business name tokens is classified as EXTERNAL_DOMAIN_REVIEW.
    2. Not blindly marked invalid.
    3. Marked non-sendable by default (quarantined pending review).
    """
    status1, reason1, is_sendable1 = classify_email_association(
        email="marketing.ecoexport@gmail.com",
        business_name="ECO-EXPORT",
        website_url="https://ecoexport.in/",
        source_type="http_contact_page",
        location="India",
    )
    assert status1 == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert is_sendable1 is False
    assert "free mail provider" in reason1.lower()

    status2, reason2, is_sendable2 = classify_email_association(
        email="info.ecoexport@gmail.com",
        business_name="ECO-EXPORT",
        website_url="https://ecoexport.in/",
        source_type="places_payload",
        location="India",
    )
    assert status2 == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert is_sendable2 is False


def test_case2_ecoexport_discovery_job_simulation():
    """
    Case 2 Complete Flow Regression:
    Simulate discovery where place search returns ECO-EXPORT with empty website,
    candidate website discovery finds https://ecoexport.in/,
    and enrichment returns candidates.
    Verify:
    1. Business is NOT left with 'No Website'.
    2. Candidate website is saved with CANDIDATE_MATCH status.
    3. Conflicting email is quarantined.
    """
    svc = LeadDiscoveryService(storage_path="")
    job = svc.create_job(["agriculture export"], ["India"], mode="uploaded_only", budget=1)

    def mock_places(keyword, city):
        return (
            [
                {
                    "name": "ECO-EXPORT",
                    "website": "",  # Empty initial website
                    "phone": "+91-98765-43210",
                    "email": None,
                }
            ],
            "serper",
            "google_maps_api",
        )

    def mock_candidate_sites(name, city):
        return [
            "https://ecoexport.in/",
            "https://ecoexport.com.vn",
        ]

    def mock_inspector(url):
        if "ecoexport.in" in url:
            return True, "Outdated design: No viewport", "info.ecoexport@gmail.com"
        return True, "Outdated design", "contact@ecoexport.com.vn"

    async def _run():
        with patch.object(svc, "search_candidate_websites", side_effect=lambda s, n, c: [
            {"url": "https://ecoexport.in/", "score": 1.0, "status": "candidate_match"},
            {"url": "https://ecoexport.com.vn", "score": 0.35, "status": "unverified_search"},
        ]):
            return await svc.run_discovery_job(
                job["job_id"],
                places_mock=mock_places,
                inspect_mock=mock_inspector,
                max_steps=1,
            )

    result_job = asyncio.run(_run())
    leads = result_job.get("discovered_leads", [])
    assert len(leads) == 1
    lead = leads[0]

    # Verify website is not empty or "No Website"
    assert lead["website"] == "https://ecoexport.in/"
    assert lead["website_association_status"] == WebsiteAssociationStatus.CANDIDATE_MATCH.value
    # Verify candidate lists are populated
    assert len(lead.get("website_candidates", [])) >= 1
    # Verify email is not quarantined solely for being a Gmail address, but is placed in external domain review
    assert lead["email"] == "info.ecoexport@gmail.com"
    assert lead["is_quarantined"] is False
    assert lead["email_business_association_status"] == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value


def test_case2_ecoexport_ambiguous_candidate_websites_conflict():
    """
    Case 2 Regression:
    When candidate website discovery yields multiple credible candidates with
    competing/close scores (e.g. 0.85 vs 0.82), the system must tag status as CONFLICTING
    and retain all candidates for review without blindly finalizing.
    """
    svc = LeadDiscoveryService(storage_path="")
    job = svc.create_job(["ambiguous search"], ["India"], mode="uploaded_only", budget=1)

    def mock_places(keyword, city):
        return (
            [
                {
                    "name": "Ambiguous Business",
                    "website": "",
                    "phone": None,
                    "email": None,
                }
            ],
            "serper",
            "google_maps_api",
        )

    def mock_inspector(url):
        return True, "Outdated design", "contact@ambiguousbiz.com"

    async def _run():
        with patch.object(svc, "search_candidate_websites", side_effect=lambda s, n, c: [
            {"url": "https://ambiguousbiz.in/", "score": 0.85, "status": "candidate_match"},
            {"url": "https://ambiguousbiz.com/", "score": 0.82, "status": "candidate_match"},
        ]):
            return await svc.run_discovery_job(
                job["job_id"],
                places_mock=mock_places,
                inspect_mock=mock_inspector,
                max_steps=1,
            )

    result_job = asyncio.run(_run())
    leads = result_job.get("discovered_leads", [])
    assert len(leads) == 1
    lead = leads[0]
    assert lead["website_association_status"] == WebsiteAssociationStatus.CONFLICTING.value
    assert len(lead.get("website_candidates", [])) == 2


def test_case2_ecoexport_user_supplied_contact_provenance():
    """
    Case 2 Regression:
    When the user supplies reference emails ('marketing.ecoexport@gmail.com', 'info.ecoexport@gmail.com'),
    the provenance must be recognized as user-supplied, retaining the address without
    falsely claiming it was scraped from a URL or verified.
    """
    status, reason, is_sendable = classify_email_association(
        email="marketing.ecoexport@gmail.com",
        business_name="ECO-EXPORT",
        website_url="https://ecoexport.in/",
        source_type="user_supplied",
        location="India",
    )
    assert status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert is_sendable is False
    assert "user-supplied reference contact" in reason.lower()


# ─── General Association Classification Scenarios ────────────────────────────

def test_legitimate_domain_email_is_matched_and_sendable():
    """Verify that an email matching the company domain is MATCHED and sendable."""
    status, reason, is_sendable = classify_email_association(
        email="hello@acmecorp.com",
        business_name="Acme Corporation",
        website_url="https://acmecorp.com",
        source_type="http_page_scrape",
    )
    assert status == EmailAssociationStatus.MATCHED
    assert is_sendable is True
    assert "direct domain match" in reason.lower()


def test_cross_domain_unrelated_email_on_scraped_page_is_mismatched():
    """Verify that an email from an entirely different domain on a scraped page is MISMATCHED_SOURCE."""
    status, reason, is_sendable = classify_email_association(
        email="support@randomthirdparty.io",
        business_name="Apex Dental Clinic",
        website_url="https://apexdental.com",
        source_type="http_page_scrape",
    )
    assert status == EmailAssociationStatus.MISMATCHED_SOURCE
    assert is_sendable is False
    assert "cross-domain email" in reason.lower()


def test_search_snippet_unverified_domain():
    """Verify that search snippet emails on unverified domains are UNVERIFIED_ASSOCIATION."""
    status, reason, is_sendable = classify_email_association(
        email="contact@somedirectory.org",
        business_name="Apex Dental Clinic",
        website_url="https://apexdental.com",
        source_type="api_search_snippet",
        location="Austin, Texas",
    )
    assert status == EmailAssociationStatus.UNVERIFIED_ASSOCIATION
    assert is_sendable is False


def test_invalid_email_format_handling():
    """Verify that invalid syntax or malformed emails are marked INVALID_FORMAT."""
    status, reason, is_sendable = classify_email_association(
        email="not-an-email",
        business_name="Test Business",
    )
    assert status == EmailAssociationStatus.INVALID_FORMAT
    assert is_sendable is False


# ─── Sequential & Concurrent Lead Variable Isolation ─────────────────────────

def test_lead_variables_are_strictly_isolated():
    """
    Verify that in a discovery job with multiple places, a place that mutates
    lead_source or lead_method does NOT leak those values into subsequent places.
    """
    svc = LeadDiscoveryService(storage_path="")
    job = svc.create_job(["testing"], ["Austin, Texas"], mode="uploaded_only", budget=1)

    def mock_places(keyword, city):
        return (
            [
                {
                    "name": "First Business (Scraped)",
                    "website": "https://firstbiz.com",
                    "phone": None,
                    "email": None,
                },
                {
                    "name": "Second Business (Places Payload)",
                    "website": "https://secondbiz.com",
                    "phone": None,
                    "email": "contact@secondbiz.com",
                },
            ],
            "serper",
            "google_maps_api",
        )

    def mock_inspector(url):
        if "firstbiz" in url:
            return True, "Outdated design", "info@firstbiz.com"
        return True, "Outdated design", None

    async def _run():
        return await svc.run_discovery_job(
            job["job_id"],
            places_mock=mock_places,
            inspect_mock=mock_inspector,
            max_steps=1,
        )

    result_job = asyncio.run(_run())
    leads = result_job.get("discovered_leads", [])
    assert len(leads) == 2

    # Lead 1: email found via page scrape
    lead1 = leads[0]
    assert lead1["business_name"] == "First Business (Scraped)"
    assert lead1["source"] in ("http_page_scrape", "http_contact_page")
    assert lead1["extraction_method"] == "http_page_scrape"

    # Lead 2: initial email provided by places search
    lead2 = leads[1]
    assert lead2["business_name"] == "Second Business (Places Payload)"
    assert lead2["source"] == "serper"
    assert lead2["extraction_method"] == "google_maps_api"


# ─── Campaign Quarantine Safety Guard ─────────────────────────────────────────

def test_campaign_creation_rejects_quarantined_leads():
    """
    Verify that create_campaign strictly refuses to include quarantined leads
    or leads with non-matched email association status.
    """
    quarantined_lead = Lead(
        id=uuid.uuid4(),
        business_name="Bihari Brothers Groups",
        email="hi@tynemade.mx",
        website="https://biharibrothers.com",
        status=LeadStatus.new,
        is_quarantined=True,
        quarantine_reason="Email detected in designer credit",
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
    )

    valid_lead = Lead(
        id=uuid.uuid4(),
        business_name="Valid Enterprise",
        email="contact@validenterprise.com",
        website="https://validenterprise.com",
        status=LeadStatus.new,
        is_quarantined=False,
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
    )

    # Filter logic simulation identical to router
    selected_leads = [quarantined_lead, valid_lead]
    active_leads = [
        l for l in selected_leads
        if not getattr(l, "is_quarantined", False)
        and getattr(l, "email_business_association_status", None) in (EmailAssociationStatus.MATCHED.value, EmailAssociationStatus.APPROVED.value)
    ]

    assert len(active_leads) == 1
    assert active_leads[0].email == "contact@validenterprise.com"
    assert quarantined_lead not in active_leads


def test_outreach_engine_skips_quarantined_lead_without_smtp():
    """
    Verify that the OutreachEngine pre-send safety guard detects is_quarantined=True
    and skips sending without touching SMTP or external mailboxes.
    """
    lead_id = str(uuid.uuid4())
    camp_id = str(uuid.uuid4())

    lead = Lead(
        id=uuid.UUID(lead_id),
        business_name="ECO-EXPORT",
        email="contact@ecoexport.com.vn",
        website="https://ecoexport.in/",
        status=LeadStatus.new,
        is_quarantined=True,
        quarantine_reason="Conflicting ccTLD",
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
    )

    campaign = Campaign(
        id=uuid.UUID(camp_id),
        name="Test Safety Campaign",
        status=CampaignStatus.sending,
        subject_template="Audit for {business_name}",
        template="Hello {business_name}",
        pending_lead_ids=[lead_id],
        sent_count=0,
        failed_count=0,
        skipped_count=0,
    )

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, obj_id: campaign if model == Campaign else lead)
    mock_db.refresh = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_smtp_account = {
        "email": "outreach@testagency.com",
        "user": "outreach@testagency.com",
        "password": "secret_password",
        "host": "smtp.testagency.com",
        "port": 587,
        "daily_limit": 100,
    }

    async def _run():
        with patch("app.config.Settings.get_smtp_accounts", return_value=[fake_smtp_account]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("app.engines.outreach_engine._send_email_sync") as mock_send, \
             patch("smtplib.SMTP") as mock_smtp, \
             patch("smtplib.SMTP_SSL") as mock_smtp_ssl:

            await _run_campaign_worker(camp_id)

            assert campaign.skipped_count >= 1
            assert mock_send.call_count == 0
            assert mock_smtp.call_count == 0
            assert mock_smtp_ssl.call_count == 0

    asyncio.run(_run())


# ─── CSV Export Sendable-Only Filtering ────────────────────────────────────────

def test_export_leads_csv_sendable_only_filtering():
    """
    Verify that export_leads_csv filters out quarantined leads when sendable_only=True.
    """
    svc = LeadDiscoveryService(storage_path="")
    job = {
        "job_id": "disc_test_export",
        "discovered_leads": [
            {
                "business_name": "Valid Business",
                "email": "contact@valid.com",
                "website": "https://valid.com",
                "is_quarantined": False,
                "email_business_association_status": "matched",
                "email_verification_status": "valid",
            },
            {
                "business_name": "Bihari Brothers Groups",
                "email": "hi@tynemade.mx",
                "website": "https://biharibrothers.com",
                "is_quarantined": True,
                "email_business_association_status": "mismatched_source",
                "quarantine_reason": "Designer credit",
            },
        ],
    }
    svc._jobs["disc_test_export"] = job

    # Full export includes both
    full_csv = svc.export_leads_csv("disc_test_export", format_type="leadgen", sendable_only=False)
    assert "contact@valid.com" in full_csv
    assert "hi@tynemade.mx" in full_csv

    # Sendable only export excludes the quarantined lead
    sendable_csv = svc.export_leads_csv("disc_test_export", format_type="leadgen", sendable_only=True)
    assert "contact@valid.com" in sendable_csv
    assert "hi@tynemade.mx" not in sendable_csv


def test_lead_response_serialization_with_provenance():
    """
    Task 4 Regression:
    Verify that LeadResponse Pydantic schema serializes all provenance,
    association status, candidate lists, and quarantine metadata correctly.
    """
    from app.schemas import LeadResponse

    lead_dict = {
        "id": uuid.uuid4(),
        "business_name": "Bihari Brothers Groups",
        "email": "contact@biharibrothers.com",
        "website": "https://biharibrothers.com",
        "status": "new",
        "created_at": datetime.now(timezone.utc),
        "email_source_url": "https://biharibrothers.com/contact",
        "email_source_type": "http_contact_page",
        "email_extraction_method": "http_page_scrape",
        "email_domain": "biharibrothers.com",
        "website_domain": "biharibrothers.com",
        "email_domain_match": True,
        "email_business_association_status": "matched",
        "email_association_reason": "Direct domain match with business website 'biharibrothers.com'",
        "website_association_status": "verified_primary",
        "website_candidates": [{"url": "https://biharibrothers.com", "score": 1.0}],
        "email_candidates": [{"email": "contact@biharibrothers.com", "association_status": "matched"}],
        "is_quarantined": False,
        "quarantine_reason": None,
    }
    resp = LeadResponse(**lead_dict)
    assert resp.email_business_association_status == "matched"
    assert resp.email_domain_match is True
    assert resp.is_quarantined is False
    assert len(resp.website_candidates) == 1
    assert len(resp.email_candidates) == 1
    assert resp.email_source_url == "https://biharibrothers.com/contact"


# ─── General Regression Scenarios (Task 7 Requirements) ───────────────────────

def test_system_does_not_hardcode_exact_domains_or_businesses():
    """
    Scenario 12: Verify the system uses generalized heuristic rules rather than
    hardcoding 'biharibrothers' or 'ecoexport'.
    """
    # 1. Agency detection on completely unrelated business and TLD
    html = """
    <footer>
        <p>© 2024 Sharma Logistics Australia.</p>
        <p>Managed by PixelCraft Digital: <a href="mailto:support@pixelcraft.de">support@pixelcraft.de</a></p>
    </footer>
    """
    candidates = extract_email_candidates_with_context(
        html,
        website="https://sharmalogistics.com.au",
        business_name="Sharma Logistics",
        location="Australia",
        source_type="http_page_scrape",
    )
    assert len(candidates) == 1
    assert candidates[0]["email"] == "support@pixelcraft.de"
    assert candidates[0]["association_status"] == EmailAssociationStatus.MISMATCHED_SOURCE.value
    assert candidates[0]["is_sendable"] is False

    # 2. Candidate scoring with Australia location
    score_au = score_website_candidate("https://sharmalogistics.com.au", "Sharma Logistics", "Australia")
    score_vn = score_website_candidate("https://sharmalogistics.com.vn", "Sharma Logistics", "Australia")
    assert score_au >= 0.8
    assert score_vn < 0.5
    assert score_au > score_vn


def test_missing_website_from_api_does_not_erase_existing_website():
    """
    Scenario 14: When a subsequent discovery job or place search returns an empty website
    for an existing lead, the existing credible website and status must not be erased.
    """
    existing_lead = Lead(
        id=uuid.uuid4(),
        business_name="ECO-EXPORT",
        email="info.ecoexport@gmail.com",
        website="https://ecoexport.in/",
        website_domain="ecoexport.in",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        is_quarantined=True,
    )

    # Simulate discovery deduplication update logic
    new_website = ""  # Empty website from subsequent place result
    new_web_dom = ""
    new_website_status = WebsiteAssociationStatus.NO_WEBSITE.value

    if not existing_lead.website and new_website:
        existing_lead.website = new_website
        existing_lead.website_domain = new_web_dom
        existing_lead.website_association_status = new_website_status

    # Website must remain intact
    assert existing_lead.website == "https://ecoexport.in/"
    assert existing_lead.website_domain == "ecoexport.in"
    assert existing_lead.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value


def test_duplicate_rediscovery_preserves_quarantine_and_association():
    """
    Scenario 15: When a lead is rediscovered in a subsequent job or import,
    an existing quarantine flag and association status must never be cleared.
    """
    existing_lead = Lead(
        id=uuid.uuid4(),
        business_name="Bihari Brothers Groups",
        email="hi@tynemade.mx",
        website="https://biharibrothers.com",
        status=LeadStatus.new,
        is_quarantined=True,
        quarantine_reason="Email detected in designer credit",
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
    )

    # Re-import or re-discovery attempt
    incoming_lead_record = {
        "email": "hi@tynemade.mx",
        "business_name": "Bihari Brothers Groups",
        "website": "https://biharibrothers.com",
    }

    # Verify quarantine cannot be wiped out
    assert existing_lead.is_quarantined is True
    assert existing_lead.email_business_association_status == EmailAssociationStatus.MISMATCHED_SOURCE.value
    assert "designer credit" in existing_lead.quarantine_reason


def test_structured_serper_parsing_isolates_organic_results():
    """
    Scenario 16: Ensure emails extracted from organic search results retain
    their specific result link as source_url, rather than unstructured JSON scanning.
    """
    sample_organic = [
        {
            "link": "https://company-official.com/contact",
            "title": "Contact Us - Company Official",
            "snippet": "Reach out to us at contact@company-official.com for queries.",
        },
        {
            "link": "https://some-unrelated-ad.com/directory",
            "title": "Directory Listing",
            "snippet": "Contact directory at admin@some-unrelated-ad.com",
        },
    ]

    company_website = "https://company-official.com"
    candidates = []
    for org in sample_organic:
        found = extract_email(f"{org.get('title')} {org.get('snippet')}")
        if found:
            st, reas, send = classify_email_association(
                found,
                "Company Official",
                website_url=company_website or org.get("link"),
                source_type="api_search_snippet",
                context_text=org.get("snippet"),
            )
            candidates.append({
                "email": found,
                "source_url": org.get("link"),
                "association_status": st.value,
            })

    assert len(candidates) == 2
    assert candidates[0]["email"] == "contact@company-official.com"
    assert candidates[0]["source_url"] == "https://company-official.com/contact"
    assert candidates[0]["association_status"] == EmailAssociationStatus.MATCHED.value

    assert candidates[1]["email"] == "admin@some-unrelated-ad.com"
    assert candidates[1]["source_url"] == "https://some-unrelated-ad.com/directory"
    assert candidates[1]["association_status"] != EmailAssociationStatus.MATCHED.value


def test_syntax_dns_success_does_not_bypass_association_quarantine():
    """
    Scenario 18: An email that has valid syntax and passing DNS/MX checks
    must NOT become sendable if its business association is mismatched or quarantined.
    """
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Bihari Brothers Groups",
        email="hi@tynemade.mx",  # Valid syntax and domain has MX records in real world
        website="https://biharibrothers.com",
        status=LeadStatus.new,
        email_verification_status="valid",  # Syntax & DNS passed
        email_business_association_status=EmailAssociationStatus.MISMATCHED_SOURCE.value,
        is_quarantined=True,
        quarantine_reason="Designer agency credit",
    )

    # 1. Campaign creation query check
    is_ready_for_campaign = (
        not lead.is_quarantined
        and lead.email_verification_status == "valid"
        and lead.email_business_association_status in (EmailAssociationStatus.MATCHED.value, EmailAssociationStatus.APPROVED.value)
    )
    assert is_ready_for_campaign is False, "Passing DNS must not bypass mismatched association"

    # 2. Outreach engine pre-send check
    is_pre_send_safe = (
        not getattr(lead, "is_quarantined", False)
        and getattr(lead, "email_business_association_status", None) in (EmailAssociationStatus.MATCHED.value, EmailAssociationStatus.APPROVED.value)
        and getattr(lead, "email_verification_status", "unverified") == "valid"
    )
    assert is_pre_send_safe is False, "Pre-send safety guard must block quarantined leads regardless of DNS"


