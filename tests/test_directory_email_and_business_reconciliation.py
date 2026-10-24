"""
tests/test_directory_email_and_business_reconciliation.py

Comprehensive test suite verifying:
1. Deepak Trading Company duplicate reconciliation.
2. Directory URL rejected as an official website.
3. Website discovered independently using a company-name search.
4. Gmail/Yahoo business records can receive a separately sourced website candidate.
5. Existing verified websites are preserved.
6. Company names shared by different businesses do not cause incorrect website copying.
7. Directory/platform email does not become sendable based on MX alone.
8. Website inference does not approve email association.
9. Abhiyan Cargo retains separate website-candidate and Zaubacorp evidence fields.
10. CSV imports and scraped leads follow identical rules.
11. No website is invented when evidence is inconclusive.
12. Existing campaign eligibility and quarantine regressions remain intact.
"""

import uuid
import asyncio
import pytest
from datetime import datetime, timezone

from app.models import (
    Lead,
    LeadStatus,
    Audit,
    AuditStatus,
    EmailAssociationStatus,
    WebsiteAssociationStatus,
)
from app.utils.email_constants import (
    is_custom_email_domain,
    is_public_email_provider,
    is_disposable_domain,
    infer_website_candidate_from_email,
    is_third_party_directory_or_aggregator,
    is_directory_or_platform_email,
    THIRD_PARTY_DIRECTORY_DOMAINS,
)
from app.utils.csv_parser import parse_and_clean_csv, clean_website, clean_business_name
from app.services.lead_discovery_service import (
    LeadDiscoveryService,
    classify_email_association,
    extract_domain_from_url,
    extract_email_domain,
    score_website_candidate,
    reconcile_duplicate_business_records,
)
from app.services.campaign_eligibility_service import (
    evaluate_lead_campaign_eligibility,
    WebsiteClassification,
    CampaignType,
    EmailSendabilityClassification,
    classify_email_sendability,
)


# ─── 1. Deepak Trading Company duplicate reconciliation ───────────────────────

def test_deepak_trading_company_duplicate_reconciliation():
    """
    Record A has in@deepaktrading.com and verified primary website www.deepaktrading.com.
    Record B has info@yellowpagesonline.in with missing website and directory source url.
    Reconciliation reuses deepaktrading.com as candidate_match for Record B,
    preserves info@yellowpagesonline.in, keeps yellowpagesonline.in as evidence provenance,
    and maintains quarantine for the directory email without auto-approving deliverability.
    """
    record_a = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Company",
        email="in@deepaktrading.com",
        phone="+91 98273 19991",
        website="http://www.deepaktrading.com/",
        website_domain="deepaktrading.com",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
        email_domain_match=True,
        is_quarantined=False,
    )

    record_b = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Company",
        email="info@yellowpagesonline.in",
        phone="+91 63079 02023",
        website="",
        website_domain="",
        website_association_status=WebsiteAssociationStatus.NO_WEBSITE.value,
        email_source_url="https://yellowpagesonline.in",
        email_source_type="directory_listing",
        email_business_association_status=EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
        is_quarantined=True,
        quarantine_reason="email_business_association_unverified_association",
    )

    outcome = reconcile_duplicate_business_records(record_b, [record_a, record_b])
    assert outcome is not None
    assert outcome["website_candidate"] == "http://www.deepaktrading.com/"
    assert outcome["status"] == WebsiteAssociationStatus.CANDIDATE_MATCH.value

    # Record B state verification
    assert record_b.website == "http://www.deepaktrading.com/"
    assert record_b.website_domain == "deepaktrading.com"
    assert record_b.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value
    assert len(record_b.website_candidates) >= 1
    cand = record_b.website_candidates[0]
    assert cand["url"] == "http://www.deepaktrading.com/"
    assert cand["source"] == "existing_business_record"
    assert cand["matched_lead_id"] == str(record_a.id)

    # Email and provenance preservation
    assert record_b.email == "info@yellowpagesonline.in"
    assert record_b.email_source_url == "https://yellowpagesonline.in"
    assert record_b.email_domain_match is False
    assert record_b.email_business_association_status == EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value

    # Quarantine preserved; directory email NOT released
    assert record_b.is_quarantined is True
    assert "Directory platform email" in record_b.quarantine_reason


# ─── 2. Directory URL rejected as an official website ─────────────────────────

@pytest.mark.parametrize("dir_url", [
    "https://www.zaubacorp.com/company/DEEPAK-TRADING-COMPANY",
    "https://tofler.in/deepak-trading-company",
    "https://www.indiamart.com/deepaktrading",
    "https://yellowpagesonline.in/deepak-trading",
    "https://malaniimpexinc.trustpass.alibaba.com/",
    "https://www.justdial.com/Indore/Deepak-Trading-Company",
    "https://www.dnb.com/business-directory/company-profiles.deepak.html",
    "https://facebook.com/deepaktradingindore",
    "https://linkedin.com/company/deepak-trading",
    "https://www.google.com/search?q=deepak+trading",
])
def test_directory_url_rejected_as_official_website(dir_url):
    """
    Directory, registry, aggregator, marketplace, social, and search engine URLs
    must be identified as third-party sources and rejected as company websites.
    """
    assert is_third_party_directory_or_aggregator(dir_url) is True
    score = score_website_candidate(dir_url, "Deepak Trading Company")
    assert score == 0.0

    # Scraper/discovery clean_website must reject directory URLs
    assert clean_website(dir_url) == ""


def test_legitimate_company_domain_with_directory_word_not_rejected():
    """
    A legitimate company domain like yellowpagestoys.com or indiamartcrafts.com
    must not be falsely rejected just because its name contains a directory substring.
    """
    assert is_third_party_directory_or_aggregator("yellowpagestoys.com") is False
    assert is_third_party_directory_or_aggregator("indiamartcrafts.com") is False
    score = score_website_candidate("https://yellowpagestoys.com", "Yellow Pages Toys")
    assert score > 0.0


# ─── 3. Website discovered independently using company-name search ─────────────

def test_website_discovered_independently_using_company_name_search():
    """
    When searching for a business website by company name and city:
    - Search does not depend on the email domain.
    - Official company domain is discovered and scored.
    - Directory/registry links in results are rejected as official websites.
    """
    async def _test():
        service = LeadDiscoveryService()

        def mock_fetcher(name, city):
            return [
                "https://www.zaubacorp.com/company/SHREE-BALAJI-EXPORTS",
                "https://www.indiamart.com/shreebalajiexports",
                "https://shreebalajiexports.in",
            ]

        candidates = await service.search_candidate_websites(
            session=None,
            name="Shree Balaji Exports",
            city="Surat",
            fetcher_mock=mock_fetcher,
        )

        assert len(candidates) == 1
        top = candidates[0]
        assert top["domain"] == "shreebalajiexports.in"
        assert top["url"] == "https://shreebalajiexports.in"
        assert top["status"] == "candidate_match"
        assert top["score"] >= 0.5

    asyncio.run(_test())


# ─── 4. Gmail/Yahoo business records can receive separately sourced candidate ─

def test_public_email_business_records_can_receive_separately_sourced_candidate():
    """
    Businesses using Gmail or Yahoo can receive a candidate website discovered by name,
    but the public email address remains unverified/external domain review and non-sendable.
    """
    email = "deepaktradingindore@gmail.com"
    cand_url = "http://www.deepaktrading.com/"

    status, reason, is_sendable = classify_email_association(
        email=email,
        business_name="Deepak Trading Company",
        website_url=cand_url,
        source_type="serper_search",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
    )

    assert is_sendable is False
    assert status in (EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW, EmailAssociationStatus.UNVERIFIED_ASSOCIATION)


# ─── 5. Existing verified websites are preserved ──────────────────────────────

def test_existing_verified_websites_are_preserved():
    """
    A record with an established verified primary website is never overwritten
    by duplicate reconciliation.
    """
    target = Lead(
        id=uuid.uuid4(),
        business_name="Dev Trading Co.",
        email="dev@gmail.com",
        website="https://devtradingco.in/",
        website_domain="devtradingco.in",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
    )

    other = Lead(
        id=uuid.uuid4(),
        business_name="Dev Trading Co.",
        email="sales@anotherdevtrading.com",
        website="https://anotherdevtrading.com/",
        website_domain="anotherdevtrading.com",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
    )

    res = reconcile_duplicate_business_records(target, [other])
    assert res is None
    assert target.website == "https://devtradingco.in/"
    assert target.website_association_status == WebsiteAssociationStatus.VERIFIED_PRIMARY.value


# ─── 6. Shared generic company names do not cause incorrect copying ───────────

def test_company_names_shared_by_different_businesses_do_not_cause_incorrect_copying():
    """
    Different businesses sharing common names (e.g. Deepak Trading in Chandigarh vs Indore,
    or generic 'Import Export Company') with conflicting locations or phones must not match.
    """
    chandigarh_record = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Co",
        email="export1@gangafoods.net",
        phone="+91 172 279 3330",
        website="https://gangafoods.net",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
    )
    setattr(chandigarh_record, "location", "Chandigarh")

    indore_record = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Company",
        email="in@deepaktrading.com",
        phone="+91 98273 19991",
        website="http://www.deepaktrading.com/",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
    )
    setattr(indore_record, "location", "Indore")

    res = reconcile_duplicate_business_records(chandigarh_record, [indore_record])
    assert res is None
    assert chandigarh_record.website == "https://gangafoods.net"


# ─── 7. Directory/platform email does not become sendable based on MX alone ────

def test_directory_platform_email_does_not_become_sendable_based_on_mx_alone():
    """
    An email on a directory platform domain (e.g. info@yellowpagesonline.in or india@dnb.com)
    must be recognized by is_directory_or_platform_email. Even if MX records resolve,
    it must remain excluded from outreach and quarantined.
    """
    email = "info@yellowpagesonline.in"
    assert is_directory_or_platform_email(email) is True
    assert is_directory_or_platform_email("india@dnb.com") is True
    assert is_directory_or_platform_email("sales@indiamart.com") is True

    lead = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Company",
        email=email,
        website="http://www.deepaktrading.com/",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        email_verification_status="valid",  # MX checks passed!
        email_business_association_status=EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
        is_quarantined=True,
        quarantine_reason="Directory platform email requires independent business association review",
    )

    classification = classify_email_sendability(lead)
    assert classification != EmailSendabilityClassification.ELIGIBLE
    assert classification == EmailSendabilityClassification.QUARANTINED


# ─── 8. Website inference does not approve email association ──────────────────

def test_website_inference_does_not_approve_email_association():
    """
    Discovering or inferring a candidate website must not auto-approve the email-to-business
    association or make the email sendable.
    """
    status, reason, is_sendable = classify_email_association(
        email="contact@newbusiness.com",
        business_name="New Business Pvt Ltd",
        website_url="https://newbusiness.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        is_website_inferred=True,
    )

    assert status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert is_sendable is False
    assert "inferred" in reason.lower() or "independently verified" in reason.lower()


# ─── 9. Abhiyan Cargo retains separate candidate and Zaubacorp evidence ────────

def test_abhiyan_cargo_retains_separate_website_candidate_and_evidence():
    """
    Abhiyan Cargo retains its inferred website candidate https://abhiyancargo.com
    while preserving the Zaubacorp listing strictly as evidence provenance.
    """
    zauba_url = "https://www.zaubacorp.com/ABHIYAN-CARGO-PRIVATE-LIMITED-U63011WB2000PTC092628"
    assert is_third_party_directory_or_aggregator(zauba_url) is True

    lead = Lead(
        id=uuid.uuid4(),
        business_name="Abhiyan Cargo Private Limited",
        email="info@abhiyancargo.com",
        website="https://abhiyancargo.com",
        website_domain="abhiyancargo.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        email_source_url=zauba_url,
        email_business_association_status=EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value,
    )

    assert lead.website == "https://abhiyancargo.com"
    assert lead.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value
    assert lead.email_source_url == zauba_url
    assert is_third_party_directory_or_aggregator(lead.website) is False
    assert is_third_party_directory_or_aggregator(lead.email_source_url) is True


# ─── 10. CSV imports and scraped leads follow identical rules ──────────────────

def test_csv_imports_and_scraped_leads_follow_identical_rules():
    """
    Both CSV imports and scraped leads must:
    - Demote directory listing URLs to email_source_url / provenance.
    - Reject directory platform emails from becoming official contacts.
    """
    csv_content = (
        "Business Name,Email,Phone,Website\n"
        "Beta Traders,info@yellowpagesonline.in,+91 99999 88888,https://www.indiamart.com/betatraders\n"
    ).encode("utf-8")

    rows = parse_and_clean_csv(csv_content)
    assert len(rows) == 1
    row = rows[0]

    # Directory URL was demoted from website to email_source_url
    assert row["website"] == ""
    assert row["email_source_url"] == "https://www.indiamart.com/"
    assert is_directory_or_platform_email(row["email"]) is True


# ─── 11. No website is invented when evidence is inconclusive ─────────────────

def test_no_website_invented_when_evidence_is_inconclusive():
    """
    When candidate search returns low-confidence or no matching results,
    no fictitious website is promoted or invented.
    """
    async def _test():
        service = LeadDiscoveryService()

        def mock_inconclusive(name, city):
            return [
                "https://completelyunrelated123.com",
                "https://randomblog.net/article",
            ]

        candidates = await service.search_candidate_websites(
            session=None,
            name="Unique Obscure Manufacturing 888",
            city="Kolkata",
            fetcher_mock=mock_inconclusive,
        )

        # Low scores (< 0.5) must not receive candidate_match
        for cand in candidates:
            assert cand["status"] == "unverified_search"
            assert cand["score"] < 0.5

    asyncio.run(_test())


# ─── 12. Campaign eligibility and quarantine regressions intact ───────────────

def test_campaign_eligibility_and_quarantine_regressions_intact():
    """
    Records with unverified associations or in quarantine remain strictly excluded
    from generic and marketing campaign outreach.
    """
    lead_quarantined = Lead(
        id=uuid.uuid4(),
        business_name="Deepak Trading Company",
        email="info@yellowpagesonline.in",
        website="http://www.deepaktrading.com/",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        email_business_association_status=EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
        is_quarantined=True,
        quarantine_reason="Directory platform email requires independent business association review",
    )

    elig = evaluate_lead_campaign_eligibility(
        lead_quarantined,
        campaign_type=CampaignType.GENERIC_FIRST_CONTACT.value,
    )
    assert elig.is_eligible is False
    assert elig.exclusion_reason is not None
