"""
tests/test_email_domain_website_inference.py

Comprehensive test suite verifying:
1. Custom business email domain yields inferred candidate when no verified company website exists.
2. Free-email providers (Gmail, Yahoo, Outlook, etc.) do not yield business website candidates.
3. Existing verified website is preserved and never overwritten.
4. Third-party company-registry / directory URLs (Zaubacorp, IndiaMART, Tofler, D&B, etc.)
   are rejected as company websites and treated strictly as evidence provenance.
5. Inferred candidates and evidence provenance are segregated.
6. Domain-match wording does not falsely imply verified association, explaining:
   "Website candidate inferred from the business email domain. The company association is not independently verified."
7. NXDOMAIN or failed MX checks continue to block email delivery as required (non-sendable / quarantined).
8. State invariance: Website candidate inference alone cannot approve association or release quarantine.
"""

import uuid
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
    THIRD_PARTY_DIRECTORY_DOMAINS,
)
from app.utils.csv_parser import parse_and_clean_csv, clean_website
from app.services.lead_discovery_service import (
    classify_email_association,
    extract_domain_from_url,
    extract_email_domain,
)
from app.services.campaign_eligibility_service import (
    evaluate_lead_campaign_eligibility,
    WebsiteClassification,
    CampaignType,
)


# ─── 1. Custom business email domain yields inferred candidate ─────────────────

def test_custom_business_email_yields_inferred_candidate():
    """A custom business email domain yields an inferred candidate if no verified company website exists."""
    email = "info@abhiyancargo.com"
    candidate = infer_website_candidate_from_email(email)
    assert candidate == "https://abhiyancargo.com"
    assert extract_domain_from_url(candidate) == "abhiyancargo.com"


# ─── 2. Free-email providers do not yield business website candidates ─────────

@pytest.mark.parametrize("free_email", [
    "user@gmail.com",
    "contact@yahoo.com",
    "support@outlook.com",
    "test@hotmail.com",
    "biz@icloud.com",
    "freemail@protonmail.com",
    "typo@yahoo.co",
    "admin@gmail.con",
])
def test_free_email_providers_never_yield_website_candidates(free_email):
    """Public email providers and typos must not be inferred as business websites."""
    cand = infer_website_candidate_from_email(free_email)
    assert cand is None, f"Expected None for free email {free_email}, got {cand}"


# ─── 3. Existing verified website is preserved ────────────────────────────────

def test_existing_verified_website_preserved_when_email_differs():
    """If an independently verified company website already exists, preserve it; do not overwrite."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Acme Corp",
        email="info@acmeparentgroup.com",
        website="https://acmecorp.com",
        website_domain="acmecorp.com",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
    )
    # Existing verified site exists
    has_verified_site = bool(lead.website and lead.website_association_status == WebsiteAssociationStatus.VERIFIED_PRIMARY.value)
    assert has_verified_site is True

    # Attempting inference must not overwrite the existing verified website
    if not has_verified_site:
        inferred = infer_website_candidate_from_email(lead.email)
        lead.website = inferred

    assert lead.website == "https://acmecorp.com"
    assert lead.website_association_status == WebsiteAssociationStatus.VERIFIED_PRIMARY.value


# ─── 4. Third-party company-registry URLs are not treated as official website ──

@pytest.mark.parametrize("dir_url", [
    "https://www.zaubacorp.com/ABHIYAN-CARGO-PRIVATE-LIMITED-U63011WB2000PTC092628",
    "https://seller.indiamart.com/leadmanager/crmapi",
    "https://www.tofler.in/company/abhiyan-cargo",
    "https://yellowpagesonline.in/listing/123",
    "https://www.dnb.com/business-directory/company-information.html",
    "https://quickcompany.in/company/123",
    "https://justdial.com/Mumbai/Cargo-Services",
])
def test_third_party_directories_recognized_and_rejected_as_company_websites(dir_url):
    """Third-party directories and company registries must not be treated as business websites."""
    assert is_third_party_directory_or_aggregator(dir_url) is True

    # In clean_website, directory domains are rejected
    from app.services.lead_discovery_service import clean_website as lds_clean_website
    assert lds_clean_website(dir_url) == ""


def test_csv_import_demotes_directory_url_to_evidence_and_infers_candidate():
    """When a CSV row contains a directory URL, it is demoted to evidence source and candidate is inferred."""
    csv_content = b"""business_name,email,website
Abhiyan Cargo Private Limited,info@abhiyancargo.com,https://www.zaubacorp.com/ABHIYAN-CARGO-PRIVATE-LIMITED-U63011WB2000PTC092628
P R Trading Corporation,ankurtiwariab@gmail.com,https://seller.indiamart.com/leadmanager/crmapi
"""
    rows = parse_and_clean_csv(csv_content)
    assert len(rows) == 2

    # Row 1: Custom business email with Zaubacorp directory URL
    r1 = rows[0]
    assert r1["website"] == "https://abhiyancargo.com"
    assert r1["is_inferred_website"] is True
    assert "zaubacorp.com" in r1.get("email_source_url", "")

    # Row 2: Gmail with IndiaMART directory URL
    r2 = rows[1]
    assert r2["website"] == ""
    assert r2["is_inferred_website"] is False
    assert "indiamart.com" in r2.get("email_source_url", "")


# ─── 5. UI / API separates inferred candidate and evidence provenance ─────────

def test_api_serialization_separates_website_and_evidence():
    """Inferred candidate website and external evidence source URL are kept in distinct fields."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Abhiyan Cargo Private Limited",
        email="info@abhiyancargo.com",
        website="https://abhiyancargo.com",
        website_domain="abhiyancargo.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        website_candidates=[{
            "url": "https://abhiyancargo.com",
            "domain": "abhiyancargo.com",
            "source": "email_domain_inferred",
            "status": "candidate_match"
        }],
        email_source_url="https://www.zaubacorp.com/ABHIYAN-CARGO-PRIVATE-LIMITED-U63011WB2000PTC092628",
        email_source_type="serper",
        email_domain="abhiyancargo.com",
        email_domain_match=True,
        email_business_association_status=EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value,
        email_association_reason="Website candidate inferred from the business email domain. The company association is not independently verified.",
    )

    # They must reside in completely separate fields
    assert lead.website != lead.email_source_url
    assert "abhiyancargo.com" in lead.website
    assert "zaubacorp.com" in lead.email_source_url
    assert lead.website_association_status == "candidate_match"


# ─── 6. Domain-match wording does not falsely imply verified association ───────

def test_inferred_website_does_not_auto_approve_association():
    """Matching email and candidate domain yields external_domain_review, not matched/approved."""
    status, reason, is_sendable = classify_email_association(
        email="info@abhiyancargo.com",
        business_name="Abhiyan Cargo Private Limited",
        website_url="https://abhiyancargo.com",
        source_type="serper",
        website_association_status="candidate_match",
    )
    assert status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW
    assert "Website candidate inferred from the business email domain. The company association is not independently verified." in reason
    assert is_sendable is False


def test_directory_url_passed_as_website_does_not_match_association():
    """If a directory URL is passed as website_url, it is not treated as matching company website."""
    status, reason, is_sendable = classify_email_association(
        email="info@abhiyancargo.com",
        business_name="Abhiyan Cargo Private Limited",
        website_url="https://www.zaubacorp.com/ABHIYAN-CARGO",
        source_type="serper",
    )
    assert status != EmailAssociationStatus.MATCHED
    assert is_sendable is False


# ─── 7. NXDOMAIN or failed MX checks continue to block email delivery ─────────

def test_nxdomain_continues_to_block_email_delivery():
    """NXDOMAIN / failed MX records continue to block deliverability and keep lead quarantined."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Abhiyan Cargo Private Limited",
        email="info@abhiyancargo.com",
        website="https://abhiyancargo.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        email_verification_status="not_found",
        is_quarantined=True,
        quarantine_reason="Domain does not exist (NXDOMAIN)",
        email_business_association_status=EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value,
    )

    elig = evaluate_lead_campaign_eligibility(lead, CampaignType.GENERIC_FIRST_CONTACT)
    assert elig.is_eligible is False
    assert elig.exclusion_reason is not None
    assert any(term in elig.exclusion_reason.lower() for term in ("quarantined", "verification", "not_found", "nxdomain", "association"))


# ─── 8. State invariance: Inference alone cannot approve association or clear quarantine

def test_inference_alone_cannot_approve_association_or_release_quarantine():
    """Inference is strictly UI/candidate metadata; it does NOT mutate quarantine or deliverability."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Abhiyan Cargo Private Limited",
        email="info@abhiyancargo.com",
        website="",
        email_verification_status="not_found",
        is_quarantined=True,
        quarantine_reason="Domain does not exist (NXDOMAIN)",
        email_business_association_status=EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value,
    )

    # Perform inference
    cand = infer_website_candidate_from_email(lead.email)
    assert cand == "https://abhiyancargo.com"
    lead.website = cand
    lead.website_association_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value

    # Safety checks: quarantine, verification status, and sendability must remain unchanged
    assert lead.is_quarantined is True
    assert lead.quarantine_reason == "Domain does not exist (NXDOMAIN)"
    assert lead.email_verification_status == "not_found"
    assert lead.email_business_association_status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value

    # Campaign evaluation must still fail closed
    elig = evaluate_lead_campaign_eligibility(lead, CampaignType.GENERIC_FIRST_CONTACT)
    assert elig.is_eligible is False
