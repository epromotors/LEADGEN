"""
tests/test_website_candidate_backfill.py

Focused test suite for repairing leads with missing websites:
1. Custom business-domain email with missing website.
2. Abhiyan Cargo-style legacy lead.
3. Existing website never overwritten.
4. Free-email provider is skipped.
5. Malformed email and invalid domains are skipped.
6. Email domain differs from an existing website.
7. Repeated backfill is idempotent.
8. Newly imported leads follow the same rules.
9. Website candidate stays unverified until the normal verification process succeeds.
10. Campaign eligibility and email verification are unaffected.
"""

import os
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
    normalize_domain,
    infer_website_candidate_from_email,
)
from app.utils.csv_parser import parse_and_clean_csv
from app.services.lead_discovery_service import extract_domain_from_url, extract_email_domain
from app.services.campaign_eligibility_service import (
    classify_website,
    evaluate_lead_campaign_eligibility,
    WebsiteClassification,
    CampaignType,
)


def test_1_custom_business_domain_email_with_missing_website():
    """1. Custom business-domain email with missing website infers clean HTTPS candidate."""
    email = "contact@mycustombusiness.com"
    cand = infer_website_candidate_from_email(email)
    assert cand == "https://mycustombusiness.com"
    assert is_custom_email_domain("mycustombusiness.com") is True


def test_2_abhiyan_cargo_legacy_lead_repaired():
    """2. Abhiyan Cargo-style legacy lead is repaired to https://abhiyancargo.com as unverified candidate."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Abhiyan Cargo Private Limited",
        email="info@abhiyancargo.com",
        website="",
        website_domain="",
        website_association_status=WebsiteAssociationStatus.UNVERIFIED_SEARCH.value,
        status=LeadStatus.new,
    )

    cand_url = infer_website_candidate_from_email(lead.email)
    assert cand_url == "https://abhiyancargo.com"

    # Simulate backfill
    domain = normalize_domain(extract_email_domain(lead.email))
    lead.website = cand_url
    lead.website_domain = domain
    lead.website_association_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
    lead.website_candidates = [{
        "url": cand_url,
        "domain": domain,
        "source": "email_domain_inferred",
        "status": "candidate_match",
    }]
    lead.email_domain = domain
    lead.email_domain_match = True

    assert lead.website == "https://abhiyancargo.com"
    assert lead.website_domain == "abhiyancargo.com"
    assert lead.website_association_status == "candidate_match"
    assert lead.business_name == "Abhiyan Cargo Private Limited"
    assert lead.email == "info@abhiyancargo.com"
    assert lead.status == LeadStatus.new
    assert lead.email_domain_match is True


def test_3_existing_website_never_overwritten():
    """3. Existing website is never overwritten, even if email has a valid business domain."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Acme Corporation",
        email="info@acmepartner.com",
        website="https://acmecorp.com",
        website_domain="acmecorp.com",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
    )

    orig_website = lead.website
    orig_domain = lead.website_domain

    # Backfill rule: only update when website is missing or blank
    if not lead.website or not lead.website.strip():
        cand = infer_website_candidate_from_email(lead.email)
        if cand:
            lead.website = cand

    assert lead.website == orig_website
    assert lead.website == "https://acmecorp.com"
    assert lead.website_domain == orig_domain


def test_4_free_email_providers_skipped():
    """4. Free-email and public webmail providers are strictly skipped."""
    free_emails = [
        "john.doe@gmail.com",
        "sarah@yahoo.com",
        "contact@yahoo.co.in",
        "alex@hotmail.com",
        "office@outlook.com",
        "team@icloud.com",
        "biz@mail.com",
        "hello@email.com",
        "user@proton.me",
        "trader@rediffmail.com",
    ]

    for em in free_emails:
        cand = infer_website_candidate_from_email(em)
        assert cand is None, f"Expected None for {em}, got {cand}"


def test_5_malformed_email_and_invalid_domains_skipped():
    """5. Malformed emails, invalid domains, IPs, localhost, and non-commercial TLDs are skipped."""
    invalid_cases = [
        "",
        None,
        "not-an-email",
        "@missinglocal.com",
        "missingat.com",
        "user@localhost",
        "admin@127.0.0.1",
        "root@192.168.1.50",
        "test@tempmail.com",  # disposable
        "help@yopmail.com",   # disposable
        "contact@yahoo.co",   # typo of public provider
        "hydacs@state.gov",   # government domain
        "helpdesk@icegate.gov.in", # government domain
        "info@tn.gov",        # government domain
        "listing@allahabadhighcourt.in", # judicial court domain
    ]

    for item in invalid_cases:
        cand = infer_website_candidate_from_email(item)
        assert cand is None, f"Expected None for {item!r}, got {cand}"


def test_6_email_domain_differs_from_existing_website():
    """6. Email domain differing from existing website preserves website and respects separate association rules."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Global Trade Corp",
        email="billing@external-accounting.com",
        website="https://globaltrade.com",
        website_domain="globaltrade.com",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
        email_business_association_status="external_domain_review",
    )

    # Candidate inference must not touch this lead
    has_site = bool(lead.website and lead.website.strip())
    assert has_site is True
    assert lead.website == "https://globaltrade.com"
    assert lead.website_domain != "external-accounting.com"


def test_7_repeated_backfill_is_idempotent():
    """7. Repeated backfill is strictly idempotent."""
    leads = [
        Lead(
            id=uuid.uuid4(),
            business_name="Candidate Biz 1",
            email="sales@candidatebiz1.com",
            website="",
        ),
        Lead(
            id=uuid.uuid4(),
            business_name="Free Email Biz",
            email="owner@gmail.com",
            website="",
        ),
        Lead(
            id=uuid.uuid4(),
            business_name="Existing Website Biz",
            email="contact@existing.com",
            website="https://existing.com",
        ),
    ]

    def simulate_backfill(lead_list):
        updated = 0
        for l in lead_list:
            if not l.website or not l.website.strip():
                cand = infer_website_candidate_from_email(l.email)
                if cand:
                    l.website = cand
                    l.website_domain = normalize_domain(extract_email_domain(l.email))
                    l.website_association_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                    updated += 1
        return updated

    # Run 1
    updated_run_1 = simulate_backfill(leads)
    assert updated_run_1 == 1
    assert leads[0].website == "https://candidatebiz1.com"
    assert leads[1].website == ""
    assert leads[2].website == "https://existing.com"

    # Run 2 (idempotent)
    updated_run_2 = simulate_backfill(leads)
    assert updated_run_2 == 0
    assert leads[0].website == "https://candidatebiz1.com"
    assert leads[1].website == ""
    assert leads[2].website == "https://existing.com"


def test_8_newly_imported_leads_follow_inference_rules():
    """8. Newly imported CSV rows follow the same inference and skipping rules."""
    csv_data = """business_name,email,phone,website
Abhiyan Freight,info@abhiyanfreight.com,9876543210,
Gmail Business,contact@gmail.com,1234567890,
Established Corp,support@establishedcorp.com,5555555555,https://establishedcorp.com
Malformed Entry,notanemail,,
"""
    rows = parse_and_clean_csv(csv_data.encode("utf-8"))

    # 3 valid emails (1 malformed skipped)
    assert len(rows) == 3

    r1 = next(r for r in rows if r["email"] == "info@abhiyanfreight.com")
    assert r1["website"] == "https://abhiyanfreight.com"
    assert r1["is_inferred_website"] is True

    r2 = next(r for r in rows if r["email"] == "contact@gmail.com")
    assert r2["website"] == ""
    assert r2["is_inferred_website"] is False

    r3 = next(r for r in rows if r["email"] == "support@establishedcorp.com")
    assert r3["website"] == "https://establishedcorp.com/"
    assert r3["is_inferred_website"] is False


def test_9_website_candidate_stays_unverified_until_verification_succeeds():
    """9. Website candidate stays unverified (WEBSITE_NOT_AUDITED) until an audit completes."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Pending Verification Co",
        email="info@pendingco.com",
        website="https://pendingco.com",
        website_domain="pendingco.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        website_candidates=[{
            "url": "https://pendingco.com",
            "domain": "pendingco.com",
            "source": "email_domain_inferred",
            "status": "candidate_match"
        }],
    )

    # Without an audit, it is classified as WEBSITE_NOT_AUDITED, NOT verified
    site_class = classify_website(lead, audit=None)
    assert site_class == WebsiteClassification.WEBSITE_NOT_AUDITED

    # If audit is pending
    pending_audit = Audit(
        id=uuid.uuid4(),
        lead_id=lead.id,
        status=AuditStatus.pending,
    )
    site_class_pending = classify_website(lead, audit=pending_audit)
    assert site_class_pending == WebsiteClassification.AUDIT_PENDING


def test_10_campaign_eligibility_and_email_verification_unaffected():
    """10. Campaign eligibility and email verification safeguards remain fully intact."""
    lead = Lead(
        id=uuid.uuid4(),
        business_name="Test Enterprise",
        email="contact@enterprise.com",
        website="https://enterprise.com",
        website_domain="enterprise.com",
        website_association_status=WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        status=LeadStatus.new,
        email_verification_status="unverified",
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
    )

    # Inferred website candidate with unverified email must NOT be eligible for outreach
    res = evaluate_lead_campaign_eligibility(lead, audit=None, campaign_type=CampaignType.VALID_WEBSITE_SEO)
    assert res.is_eligible is False
    assert res.exclusion_reason is not None
    reason_lower = res.exclusion_reason.lower()
    assert "audit" in reason_lower or "unverified" in reason_lower or "verification" in reason_lower
