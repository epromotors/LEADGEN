"""
tests/test_batches_implementation.py

Acceptance tests for Batches 1-3 implementation.
Covers all acceptance criteria from AGENT_GUIDE_all_batches.md section 11
and email_system_changes_for_agent.md items 1-5.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to create minimal Lead / Audit mocks
# ---------------------------------------------------------------------------

def make_lead(**kwargs):
    lead = MagicMock()
    defaults = dict(
        business_name="Sharma Dental Clinic | Best Dentist in Dehradun | Implants",
        email="info@sharmadentalcare.com",
        website="https://sharmadentalcare.com",
        website_association_status="verified_primary",
        email_business_association_status="matched",
        is_quarantined=False,
        is_suppressed=False,
        quarantine_reason=None,
        replied_at=None,
        reply_type=None,
        has_received_demo=False,
        sequence_touch_count=0,
        last_sequence_touch_at=None,
        sequence_paused_until=None,
        suppressed_at=None,
        suppression_reason=None,
        last_emailed_at=None,
        email_verification_status="valid",
        niche_id=1,
        niche_keyword="dental",
        niche_confidence=3,
        niche_locked=False,
        city="Dehradun",
        website_candidates=None,
        phone=None,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(lead, k, v)
    return lead


def make_audit(**kwargs):
    audit = MagicMock()
    defaults = dict(
        status="done",
        audit_results={"has_sitemap": False, "has_meta_desc": False},
        audit_summary="Audit complete",
        audited_url="https://sharmadentalcare.com",
        site_summary={},
        error_message=None,
        updated_at=datetime.utcnow() - timedelta(days=2),
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(audit, k, v)
    return audit


# ===========================================================================
# 1. Niche Router Tests
# ===========================================================================

class TestNicheRouter:
    """Tests for niche_router.classify_lead_niche and clean_business_name."""

    def test_dental_classification(self):
        from app.services.niche_router import classify_lead_niche
        niche_id, keyword, score = classify_lead_niche("Sharma Dental Clinic", "dental clinic")
        assert niche_id == 1, f"Expected niche 1 (Dental), got {niche_id}"
        assert score >= 2

    def test_pharmacy_classification(self):
        from app.services.niche_router import classify_lead_niche
        niche_id, _, score = classify_lead_niche("Apollo Pharmacy", "pharmacy")
        assert niche_id == 4

    def test_ca_firm_classification(self):
        from app.services.niche_router import classify_lead_niche
        niche_id, _, score = classify_lead_niche("Gupta & Associates CA Firm", "CA firm")
        assert niche_id == 21

    def test_pest_control_classification(self):
        from app.services.niche_router import classify_lead_niche
        niche_id, _, score = classify_lead_niche("HiCare Pest Control Services")
        assert niche_id == 25

    def test_real_estate_classification(self):
        from app.services.niche_router import classify_lead_niche
        niche_id, _, score = classify_lead_niche("Raheja Property Dealers & Real Estate")
        assert niche_id == 16

    def test_no_confident_match_returns_none(self):
        from app.services.niche_router import classify_lead_niche, MIN_SEND_CONFIDENCE
        niche_id, _, score = classify_lead_niche("XYZ Enterprises")
        assert niche_id is None or score < MIN_SEND_CONFIDENCE, (
            f"Generic name should not produce a sendable match "
            f"(got niche_id={niche_id}, score={score})"
        )

    def test_clean_business_name_strips_seo_suffix(self):
        from app.services.niche_router import clean_business_name
        raw = "Sharma Dental Clinic | Best Dentist in Dehradun | Implants"
        cleaned = clean_business_name(raw)
        assert "|" not in cleaned
        assert "Best Dentist" not in cleaned
        assert "Sharma Dental Clinic" in cleaned

    def test_clean_business_name_removes_noise_words(self):
        from app.services.niche_router import clean_business_name
        assert "best" not in clean_business_name("Best Pizza House").lower()
        assert "no.1" not in clean_business_name("No.1 Pharmacy").lower()

    def test_clean_business_name_converts_all_caps(self):
        from app.services.niche_router import clean_business_name
        assert clean_business_name("APOLLO CLINIC") == "Apollo Clinic"

    def test_clean_business_name_truncates_at_33(self):
        from app.services.niche_router import clean_business_name
        long_name = "A" * 40
        result = clean_business_name(long_name)
        assert len(result) <= 33

    def test_clean_business_name_30_real_messy_names(self):
        """Acceptance test 4: 30 messy names produce clean greeting lines."""
        from app.services.niche_router import clean_business_name
        messy_names = [
            "SHARMA DENTAL CLINIC | Best Dentist In Dehradun",
            "Apollo Pharmacy - No.1 Medical Store 9876543210",
            "XYZ COACHING INSTITUTE | IIT JEE | NEET | 2024",
            "💊 Wellness Pharmacy & Medical Store | Best Price",
            "RAJ HOTEL : 3 Star | Best in City | Online Booking",
            "GREEN GYM & FITNESS CENTER - Book Trial Now!",
            "Anand Jewellers | Top 1 Jewellery Store Dehradun",
            "RIYA BOUTIQUE & CLOTHING STORE | Best Fashion 2024",
            "Metro Diagnostic Lab - Pathology | Blood Test | X-Ray",
            "City Hospital & Medical Centre - 24x7 | Emergency",
            "Happy School | CBSE Affiliated | Best Results 2023",
            "Travel Wings - No.1 Travel Agency & Tour Operator",
            "ShreejI SALON & SPA | Best Haircut | Ladies & Gents",
            "Balaji Grocery Store | Supermarket | Free Home Delivery",
            "Prime Real Estate | Best Property Dealers Dehradun",
            "TechSoft IT Solutions | Best Web Dev | Mobile App",
            "GUPTA & ASSOCIATES CA FIRM | Tax | GST | Audit",
            "Speed Logistics | Best Freight & Transport Company",
            "Sun Manufacturing Co. | ISO Certified | Since 1990",
            "Mehta HR Solutions - Staffing & Recruitment Agency",
            "QuickPrint | Offset & Digital Printing | Best Rates",
            "CleanPro Facility Management & Pest Control Services",
            "WoodCraft Furniture | Modular Kitchen | Best Deals",
            "Event Magic | Wedding Planner | Best Event Manager",
            "Himalayan Hotels & Resorts | Best Stay Dehradun",
            "FITLIFE GYM | Crossfit | Zumba | Personal Training",
            "AGARWAL DIAGNOSTIC CENTER | NABL Accredited | Tests",
            "METRO RESTAURANT & CAFE | Best Food | Fast Delivery",
            "AutoPro Car Service Centre | Best Garage in Dehradun",
            "Sai Interior Designers & Architects | Best Portfolio",
        ]
        for name in messy_names:
            cleaned = clean_business_name(name)
            assert len(cleaned) <= 33, f"Name too long: {cleaned!r} from {name!r}"
            assert "|" not in cleaned, f"SEO suffix not stripped: {cleaned!r}"
            assert "best" not in cleaned.lower(), f"Noise word 'best' remains: {cleaned!r}"
            assert cleaned.strip() != "", f"Empty name produced from: {name!r}"

    def test_social_domain_is_flagged(self):
        from app.services.niche_router import is_social_domain
        assert is_social_domain("facebook.com") is True
        assert is_social_domain("justdial.com") is True
        assert is_social_domain("sharmadentalcare.com") is False

    def test_clean_domain_strips_www_and_path(self):
        from app.services.niche_router import clean_domain
        assert clean_domain("https://www.example.com/page?q=1") == "example.com"
        assert clean_domain("www.TEST.com") == "test.com"


# ===========================================================================
# 2. Niche Template Library Tests
# ===========================================================================

class TestNicheTemplateLibrary:
    """Tests for niche_template_service.NicheTemplateLibrary and render_niche_template."""

    def test_library_loads_260_templates(self):
        from app.services.niche_template_service import NicheTemplateLibrary
        lib = NicheTemplateLibrary.get_instance()
        total = sum(len(v) for v in lib._index.values())
        assert total == 260, f"Expected 260 templates, got {total}"

    def test_get_template_niche1_segment1(self):
        from app.services.niche_template_service import NicheTemplateLibrary
        lib = NicheTemplateLibrary.get_instance()
        tmpl = lib.get_template(1, 1)
        assert tmpl["niche_id"] == 1
        assert tmpl["segment_no"] == 1
        assert tmpl["segment_key"] == "NO_WEBSITE_DESIGN"

    def test_subject_rotation_cycles_through_all_three(self):
        from app.services.niche_template_service import NicheTemplateLibrary
        lib = NicheTemplateLibrary.get_instance()
        tmpl = lib.get_template(1, 4)  # niche=Dental, segment=SEO
        pool = [tmpl["subject"]] + list(tmpl.get("subject_alternatives", []))
        seen = set()
        for _ in range(len(pool) * 2):
            subj = lib.rotate_subject(1, 4, tmpl)
            seen.add(subj)
        assert len(seen) == len(pool), f"Subject rotation did not cycle all {len(pool)} subjects"

    def test_render_niche_template_segment1_no_domain(self):
        """Acceptance: Segment 1 body must not contain {domain}."""
        from app.services.niche_template_service import render_niche_template
        ctx = {
            "business_name": "Sharma Dental Clinic",
            "domain": "",
            "website": "",
            "sender_name": "Ashish",
            "company_name": "TEB Solutions",
            "company_website": "tebsolutions.in",
            "audit_findings": "",
            "audit_recommendations": "",
            "audit_summary": "",
            "city": "Dehradun",
            "niche_label": "Dental Clinics & Dentists",
            "finding_count": "0",
            "contact_name": "",
        }
        result = render_niche_template(1, 1, ctx)
        assert "{domain}" not in result["body"]
        assert result["segment_key"] == "NO_WEBSITE_DESIGN"

    def test_render_niche_template_segment4_requires_findings(self):
        """Acceptance: Segment 4 (SEO) must fail closed when audit_findings is empty."""
        from app.services.niche_template_service import render_niche_template, NicheTemplateError
        ctx = {
            "business_name": "Sharma Dental",
            "domain": "sharmadentalcare.com",
            "website": "https://sharmadentalcare.com",
            "sender_name": "Ashish",
            "company_name": "TEB Solutions",
            "company_website": "tebsolutions.in",
            "audit_findings": "",          # empty — should be blocked
            "audit_recommendations": "",
            "audit_summary": "",
            "city": "Dehradun",
            "niche_label": "Dental Clinics & Dentists",
            "finding_count": "0",
            "contact_name": "",
        }
        with pytest.raises(NicheTemplateError, match="audit_findings"):
            render_niche_template(1, 4, ctx)

    def test_render_niche_template_success_with_findings(self):
        from app.services.niche_template_service import render_niche_template
        ctx = {
            "business_name": "Apollo Pharmacy",
            "domain": "apollopharmacy.com",
            "website": "https://apollopharmacy.com",
            "sender_name": "Ashish",
            "company_name": "TEB Solutions",
            "company_website": "tebsolutions.in",
            "audit_findings": "- No sitemap found\n- Missing meta description",
            "audit_recommendations": "- Add an XML sitemap\n- Write a meta description",
            "audit_summary": "2 issues found",
            "city": "Mumbai",
            "niche_label": "Pharmacies & Medical Stores",
            "finding_count": "2",
            "contact_name": "",
        }
        result = render_niche_template(4, 4, ctx)  # niche=Pharmacy, seg=SEO
        assert result["niche_id"] == 4
        assert result["segment_no"] == 4
        assert "Apollo Pharmacy" in result["body"]
        assert "{" not in result["body"], "Unresolved tokens remain in body"


# ===========================================================================
# 3. Fail-Closed Renderer Tests (guide section 5 / P0 item 3)
# ===========================================================================

class TestFailClosedRenderer:
    """Acceptance test 3: worst-case data must block or fall back correctly."""

    def test_worst_case_business_name_33_chars(self):
        """33-char name must not break subject length limit."""
        from app.services.niche_router import clean_business_name
        name_33 = "N" * 33
        cleaned = clean_business_name(name_33)
        assert len(cleaned) <= 33

    def test_unresolved_token_blocks_render(self):
        from app.services.niche_template_service import render_niche_template, NicheTemplateError
        # Missing 'business_name' in context — {business_name} stays unresolved
        ctx = {
            "domain": "example.com",
            "website": "https://example.com",
            "sender_name": "Ashish",
            "company_name": "TEB Solutions",
            "company_website": "tebsolutions.in",
            "audit_findings": "- No sitemap",
            "audit_recommendations": "- Add sitemap",
            "audit_summary": "1 issue",
            "city": "",
            "niche_label": "",
            "finding_count": "1",
            "contact_name": "",
            # 'business_name' deliberately missing
        }
        with pytest.raises(NicheTemplateError):
            render_niche_template(1, 4, ctx)

    def test_empty_findings_for_segment7_blocks(self):
        from app.services.niche_template_service import render_niche_template, NicheTemplateError
        ctx = {
            "business_name": "Test Co",
            "domain": "testco.com",
            "website": "https://testco.com",
            "sender_name": "Ashish",
            "company_name": "TEB Solutions",
            "company_website": "tebsolutions.in",
            "audit_findings": "",  # empty → should block for segment 7
            "audit_recommendations": "",
            "audit_summary": "",
            "city": "",
            "niche_label": "",
            "finding_count": "0",
            "contact_name": "",
        }
        with pytest.raises(NicheTemplateError):
            render_niche_template(1, 7, ctx)


# ===========================================================================
# 4. Segment Routing Tests (guide section 4)
# ===========================================================================

class TestNicheSegmentRouting:

    def test_suppressed_lead_gets_no_segment(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(is_suppressed=True)
        campaign_type, reason = evaluate_niche_segment(lead)
        assert campaign_type is None
        assert "suppressed" in reason.lower()

    def test_public_email_unverified_gets_segment_10(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(
            email="owner@gmail.com",
            email_business_association_status="unverified_association",
            has_received_demo=False,
            website="",
            website_association_status="no_website",
        )
        campaign_type, reason = evaluate_niche_segment(lead)
        assert campaign_type == "public_provider_demo"
        assert reason is None

    def test_public_email_already_demo_gets_no_segment(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(
            email="owner@gmail.com",
            email_business_association_status="unverified_association",
            has_received_demo=True,
        )
        campaign_type, reason = evaluate_niche_segment(lead)
        assert campaign_type is None
        assert "already sent" in reason.lower() or "never resend" in reason.lower()

    def test_no_website_gets_segment_1(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(
            email="info@business.com",
            email_business_association_status="matched",
            website="",
            website_association_status="no_website",
        )
        campaign_type, reason = evaluate_niche_segment(lead)
        assert campaign_type == "no_website_design"

    def test_valid_audited_seo_failures_gets_segment_4(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(website_association_status="verified_primary")
        audit = make_audit(
            status="done",
            audit_results={"has_sitemap": False, "has_meta_desc": False},
        )
        campaign_type, reason = evaluate_niche_segment(lead, audit)
        assert campaign_type == "valid_website_seo"

    def test_replied_lead_gets_no_segment(self):
        from app.services.campaign_eligibility_service import evaluate_niche_segment
        lead = make_lead(replied_at=datetime.utcnow())
        campaign_type, reason = evaluate_niche_segment(lead)
        assert campaign_type is None
        assert "replied" in reason.lower()


# ===========================================================================
# 5. Sequence Gate Tests (guide section 7.5)
# ===========================================================================

class TestSequenceGate:

    def test_fresh_lead_passes(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(sequence_touch_count=0, last_sequence_touch_at=None)
        assert check_sequence_gate(lead) is None

    def test_max_3_touches_blocks(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(
            sequence_touch_count=3,
            last_sequence_touch_at=datetime.utcnow() - timedelta(days=5),
        )
        result = check_sequence_gate(lead)
        assert result is not None
        assert "3" in result

    def test_too_soon_for_second_touch(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(
            sequence_touch_count=1,
            last_sequence_touch_at=datetime.utcnow() - timedelta(days=2),  # only 2 days
        )
        result = check_sequence_gate(lead)
        assert result is not None
        assert "too soon" in result.lower()

    def test_enough_time_for_second_touch(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(
            sequence_touch_count=1,
            last_sequence_touch_at=datetime.utcnow() - timedelta(days=5),  # 5 days ≥ 4
        )
        assert check_sequence_gate(lead) is None

    def test_paused_lead_is_blocked(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(
            sequence_paused_until=datetime.utcnow() + timedelta(days=3),
        )
        result = check_sequence_gate(lead)
        assert result is not None
        assert "paused" in result.lower()

    def test_90_day_window_resets(self):
        from app.services.campaign_eligibility_service import check_sequence_gate
        lead = make_lead(
            sequence_touch_count=3,
            last_sequence_touch_at=datetime.utcnow() - timedelta(days=91),
        )
        assert check_sequence_gate(lead) is None


# ===========================================================================
# 6. Suppression Service Tests (guide section 7.2)
# ===========================================================================

class TestSuppressionDetection:

    def test_opt_out_keywords_detected(self):
        from app.services.suppression_service import is_opt_out_intent
        assert is_opt_out_intent("Please unsubscribe me from your list")
        assert is_opt_out_intent("Remove me from your emails")
        assert is_opt_out_intent("Stop sending me emails")
        assert is_opt_out_intent("Not interested, do not contact")
        assert is_opt_out_intent("Please remove my email address")

    def test_non_opt_out_not_detected(self):
        from app.services.suppression_service import is_opt_out_intent
        assert not is_opt_out_intent("I am interested, please send more info")
        assert not is_opt_out_intent("What are your pricing plans?")
        assert not is_opt_out_intent("")

    def test_reply_classifier_positive(self):
        from app.services.suppression_service import classify_reply
        assert classify_reply("Yes I am interested, please send a proposal") == "positive"

    def test_reply_classifier_unsubscribe(self):
        from app.services.suppression_service import classify_reply
        assert classify_reply("Please remove me, not interested") == "unsubscribe"

    def test_reply_classifier_out_of_office(self):
        from app.services.suppression_service import classify_reply
        assert classify_reply("I am out of office until Monday") == "out_of_office"


class TestPipelineIntegration:

    def test_lead_response_and_update_schemas(self):
        from app.schemas import LeadResponse, LeadUpdate
        from app.models import LeadStatus
        import uuid

        lead_data = {
            "id": uuid.uuid4(),
            "business_name": "Agrawal Sweets",
            "email": "info@agrawalsweets.com",
            "website": "https://agrawalsweets.com",
            "status": LeadStatus.new,
            "created_at": datetime.now(),
            "niche_id": 14,
            "niche_keyword": "sweet shop",
            "niche_confidence": 3.0,
            "niche_locked": False,
            "sequence_touch_count": 1,
            "has_received_demo": False,
            "is_suppressed": False,
            "niche_label": "Sweet Shop / Bakery",
        }
        resp = LeadResponse(**lead_data)
        assert resp.niche_id == 14
        assert resp.niche_label == "Sweet Shop / Bakery"
        assert resp.sequence_touch_count == 1

        update = LeadUpdate(niche_id=14, niche_locked=True)
        assert update.niche_id == 14
        assert update.niche_locked is True

    def test_suppression_service_integration(self):
        import asyncio
        from app.services.suppression_service import suppress_email, is_suppressed
        from unittest.mock import AsyncMock

        async def _run():
            mock_db = AsyncMock()
            mock_record = MagicMock(email="test@unsub.com")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar_one.return_value = mock_record
            mock_db.execute.return_value = mock_result

            lead = make_lead(email="test@unsub.com")
            record = await suppress_email("test@unsub.com", reason="unsubscribe", source="inbound_reply", db=mock_db, lead=lead)
            assert record.email == "test@unsub.com"
            assert lead.is_suppressed is True
            assert lead.suppression_reason == "unsubscribe"

            # Check suppression returns True when record exists
            mock_result.scalar_one_or_none.return_value = mock_record
            assert await is_suppressed("test@unsub.com", mock_db) is True

        asyncio.run(_run())

