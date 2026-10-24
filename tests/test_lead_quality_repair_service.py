import uuid
import pytest
from pydantic import ValidationError

from app.models import EmailAssociationStatus, Lead, WebsiteAssociationStatus
from app.routers.leads import BulkDeleteRequest
from app.services.lead_quality_repair_service import (
    LeadQualityRepairService,
    is_suspect_placeholder_email,
)


def make_lead(**values):
    defaults = {
        "id": uuid.uuid4(),
        "business_name": "Example Exports Pvt Ltd",
        "email": "contact@exampleexports.in",
        "website": "",
        "website_association_status": WebsiteAssociationStatus.NO_WEBSITE.value,
        "email_business_association_status": EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value,
        "email_verification_status": "unverified",
    }
    defaults.update(values)
    return Lead(**defaults)


def test_directory_website_is_demoted_to_provenance_not_promoted():
    lead = make_lead(
        website="https://www.indiamart.com/example-exports",
        email="directory@exampleexports.in",
    )
    service = LeadQualityRepairService()

    changes = service.apply_static_rules(lead)

    assert "directory_website_demoted" in changes
    assert lead.website == "https://exampleexports.in"
    assert lead.email_source_url == "https://www.indiamart.com/example-exports"
    assert lead.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value


def test_custom_email_domain_is_only_an_unverified_candidate():
    lead = make_lead(email="contact@exampleexports.in")
    service = LeadQualityRepairService()

    changes = service.apply_static_rules(lead)

    assert "email_domain_candidate_added" in changes
    assert lead.website == "https://exampleexports.in"
    assert lead.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value
    assert lead.email_business_association_status == EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value
    assert not lead.is_quarantined


def test_public_provider_gets_independent_discovery_plan_not_domain_inference():
    lead = make_lead(email="owner@gmail.com")
    plan = LeadQualityRepairService().plan_for_lead(lead)

    assert "public_provider_contact" in plan.issue_types
    assert "independent_business_name_discovery" in plan.operations
    assert "add_unverified_email_domain_candidate" not in plan.operations


def test_explicit_placeholder_email_is_held_for_review_without_deletion():
    lead = make_lead(email="demo@realextremeexport.com")
    service = LeadQualityRepairService()

    changes = service.apply_static_rules(lead)

    assert is_suspect_placeholder_email(lead.email) is True
    assert "placeholder_contact_held_for_review" in changes
    assert lead.is_quarantined is True
    assert "No verified business contact found" in lead.quarantine_reason


def test_placeholder_with_bounded_no_result_is_recommended_not_deleted():
    lead = make_lead(email="demo@realextremeexport.com")
    service = LeadQualityRepairService()
    service.add_discovery_candidates(lead, [{
        "source": "bounded_discovery",
        "status": "no_results",
        "reason": "No independently supported official website candidate was returned",
    }], [])

    plan = service.plan_for_lead(lead)

    assert plan.recommended_action == "recommend_deletion"
    assert "retain_in_review_until_operator_keep_or_delete_decision" in plan.operations


def test_unusual_email_is_not_treated_as_placeholder():
    assert is_suspect_placeholder_email("exports.team42@gmail.com") is False


def test_discovered_candidates_never_overwrite_verified_primary_site():
    lead = make_lead(
        website="https://verified.exampleexports.in",
        website_association_status=WebsiteAssociationStatus.VERIFIED_PRIMARY.value,
        email_business_association_status=EmailAssociationStatus.MATCHED.value,
    )
    service = LeadQualityRepairService()

    changes = service.add_discovery_candidates(
        lead,
        [{"url": "https://different.example", "source": "serper_organic", "status": "candidate_match"}],
        [{"email": "sales@different.example", "source_url": "https://different.example/contact"}],
    )

    assert lead.website == "https://verified.exampleexports.in"
    assert lead.website_association_status == WebsiteAssociationStatus.VERIFIED_PRIMARY.value
    assert "website_candidate_discovered" in changes
    assert "email_candidate_discovered" in changes


def test_dry_run_redacts_contacts_and_groups_issue_counts():
    lead = make_lead(email="directory@yellowpagesonline.in", website="https://yellowpagesonline.in/example")
    report = LeadQualityRepairService().dry_run_report([lead])

    assert report["mode"] == "dry_run"
    assert report["issue_counts"]["directory_email"] == 1
    assert report["issue_counts"]["directory_website"] == 1
    assert "email" not in report["plans"][0]


def test_bulk_delete_requires_a_nonempty_explicit_selection_confirmation():
    lead_id = uuid.uuid4()
    request = BulkDeleteRequest(ids=[lead_id], confirmed_count=1)
    assert request.confirmed_count == 1
    with pytest.raises(ValidationError):
        BulkDeleteRequest(ids=[], confirmed_count=0)


def test_additional_directory_marketplaces_detected():
    from app.utils.email_constants import is_third_party_directory_or_aggregator
    assert is_third_party_directory_or_aggregator("https://www.recycleinme.com/rim-agtrademart/home") is True
    assert is_third_party_directory_or_aggregator("https://www.exporttrademart.com/company/123") is True

    lead = make_lead(
        website="https://www.recycleinme.com/rim-agtrademart/home",
        email="contact@agtrademart.com",
    )
    service = LeadQualityRepairService()
    changes = service.apply_static_rules(lead)

    assert "directory_website_demoted" in changes
    assert lead.email_source_url == "https://www.recycleinme.com/rim-agtrademart/home"
    assert lead.email_source_type == "directory_listing"
    assert lead.website == "https://agtrademart.com"
    assert lead.website_association_status == WebsiteAssociationStatus.CANDIDATE_MATCH.value


def test_csv_parser_preserves_directory_provenance_and_infers_candidate():
    from app.utils.csv_parser import parse_and_clean_csv
    csv_bytes = b"business_name,email,phone,website\nScrap Traders,sales@scraptraders.in,+919876543210,https://www.recycleinme.com/scrap-traders\n"
    rows = parse_and_clean_csv(csv_bytes)

    assert len(rows) == 1
    assert rows[0]["business_name"] == "Scrap Traders"
    assert rows[0]["email"] == "sales@scraptraders.in"
    assert rows[0]["website"] == "https://scraptraders.in"
    assert rows[0]["is_inferred_website"] is True
    assert rows[0]["email_source_url"] == "https://www.recycleinme.com/"


def test_bulk_delete_enforces_exact_count_match():
    import asyncio
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.routers.leads import bulk_delete_leads

    lead_id1 = uuid.uuid4()
    lead_id2 = uuid.uuid4()
    mock_db = AsyncMock()

    async def _run():
        req = BulkDeleteRequest(ids=[lead_id1, lead_id2], confirmed_count=1)
        with pytest.raises(HTTPException) as exc_info:
            await bulk_delete_leads(req, db=mock_db)
        assert exc_info.value.status_code == 400
        assert "Bulk deletion confirmation count must match" in exc_info.value.detail

    asyncio.run(_run())


def test_bulk_delete_revalidates_and_reports_honest_partial_failure():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import bulk_delete_leads

    lead_id1 = uuid.uuid4()
    lead_id2 = uuid.uuid4()
    mock_db = AsyncMock()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [lead_id1]

    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value = mock_scalars
    mock_exec_res.rowcount = 1

    mock_campaigns = MagicMock()
    mock_campaigns.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [
        mock_exec_res,       # existing_stmt
        mock_campaigns,      # campaigns
        MagicMock(),         # delete Audit
        mock_exec_res,       # delete Lead
    ]

    async def _run():
        req = BulkDeleteRequest(ids=[lead_id1, lead_id2], confirmed_count=2)
        result = await bulk_delete_leads(req, db=mock_db)

        assert result["deleted"] == 1
        assert result["requested"] == 2
        assert str(lead_id2) in result["missing"]
        assert mock_db.commit.called

    asyncio.run(_run())


def test_keep_lead_under_review_quarantines_and_logs():
    import asyncio
    from unittest.mock import AsyncMock
    from app.routers.leads import keep_lead_under_review

    lead = make_lead(is_quarantined=False, quarantine_reason=None)
    mock_db = AsyncMock()
    mock_db.get.return_value = lead

    async def _run():
        res = await keep_lead_under_review(lead.id, db=mock_db)

        assert res["status"] == "kept_for_review"
        assert lead.is_quarantined is True
        assert lead.quarantine_reason == "Retained for operator review"
        assert mock_db.add.called
        assert mock_db.commit.called

    asyncio.run(_run())


def test_review_queue_pagination_and_provenance():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import get_lead_quality_review_queue

    lead = make_lead(
        website="https://www.indiamart.com/example",
        is_quarantined=True,
        quarantine_reason="Test quarantine",
        website_candidates=[{"url": "https://example.com", "source": "discovery", "status": "candidate_match"}],
        email_candidates=[{"email": "contact@example.com", "source_url": "https://example.com/about"}],
    )
    mock_db = AsyncMock()

    mock_leads_scalars = MagicMock()
    mock_leads_scalars.all.return_value = [lead]
    mock_leads_res = MagicMock()
    mock_leads_res.scalars.return_value = mock_leads_scalars

    mock_db.execute.return_value = mock_leads_res

    async def _run():
        res = await get_lead_quality_review_queue(page=1, page_size=25, db=mock_db)

        assert res["total"] == 1
        assert res["page"] == 1
        assert res["page_size"] == 25
        assert len(res["records"]) == 1
        record = res["records"][0]
        assert record["is_quarantined"] is True
        assert len(record["website_provenance"]) == 1
        assert record["email_provenance"]["candidate_count"] == 1
        assert len(record["email_provenance"]["candidates"]) == 1
        assert "evidence" in record
        assert "counts" in res
        assert res["counts"]["operational_queue"] == 1
        assert res["counts"]["data_repair_actionable"] == 1
        assert res["counts"]["both"] == 1
        assert record["is_operational_queue"] is True
        assert record["is_data_repair_actionable"] is True

    asyncio.run(_run())


def test_review_queue_includes_previously_omitted_data_repair_records():
    """Prove that records with directory domains, domain mismatches, or missing websites
    appear in the review queue even if legacy DB fields have verified_primary and matched."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import get_lead_quality_review_queue

    # 1 & 2: Export Trade Mart directory leads
    lead_dir1 = make_lead(
        business_name="Export Trade Mart 1",
        email="firstname@exporttrademart.com",
        website="https://www.exporttrademart.com/",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    lead_dir2 = make_lead(
        business_name="Export Trade Mart 2",
        email="info@exporttrademart.com",
        website="https://www.exporttrademart.com/",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    # 3: Conflicting domain lead
    lead_mismatch1 = make_lead(
        business_name="Siddhi Vinayak",
        email="care@gifthealth.com",
        website="https://www.grownext.in/",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    # 4: Subdomain / root mismatch lead
    lead_mismatch2 = make_lead(
        business_name="Freight Agent Indore",
        email="indore@iiiem.in",
        website="http://indore.iiiem.in/",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    # 5: Missing website with unverified_search status
    lead_search = make_lead(
        business_name="Inter Coastline Exim -ICE",
        email="icegatehelpdesk@icegate.gov.in",
        website="",
        is_quarantined=False,
        website_association_status="unverified_search",
        email_business_association_status="matched",
        website_candidates=[
            {"url": "https://in.linkedin.com/in/inter-coastline-exim", "domain": "linkedin.com"},
            {"url": "https://fieo.globallinker.com/network", "domain": "globallinker.com"},
        ],
    )

    mock_db = AsyncMock()
    mock_leads_scalars = MagicMock()
    mock_leads_scalars.all.return_value = [lead_dir1, lead_dir2, lead_mismatch1, lead_mismatch2, lead_search]
    mock_leads_res = MagicMock()
    mock_leads_res.scalars.return_value = mock_leads_scalars
    mock_db.execute.return_value = mock_leads_res

    async def _run():
        res = await get_lead_quality_review_queue(page=1, page_size=10, db=mock_db)
        assert res["total"] == 5
        assert len(res["records"]) == 5
        # All 5 have is_data_repair_actionable True
        for rec in res["records"]:
            assert rec["is_data_repair_actionable"] is True
            assert rec["is_operational_queue"] is False
        assert res["counts"]["data_repair_actionable"] == 5
        assert res["counts"]["operational_queue"] == 0
        assert res["counts"]["both"] == 0

    asyncio.run(_run())


def test_review_queue_deduplication_and_counts():
    """Verify that records in both sets appear only once and counts are distinct."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import get_lead_quality_review_queue

    # Lead in both sets (quarantined AND directory email)
    both_lead = make_lead(
        business_name="Both Lead",
        email="info@indiamart.com",
        website="https://example.com",
        is_quarantined=True,
    )
    # Lead only in operational queue (quarantined for deliverability with matching domains)
    op_only_lead = make_lead(
        business_name="Op Only Lead",
        email="contact@company.com",
        website="https://company.com",
        is_quarantined=True,
    )
    # Lead only in data repair (clean DB flags, but public provider email)
    dr_only_lead = make_lead(
        business_name="DR Only Lead",
        email="business@gmail.com",
        website="https://business.com",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    # Completely clean lead (no operational issue, no data repair issue)
    clean_lead = make_lead(
        business_name="Clean Lead",
        email="contact@validcorp.com",
        website="https://validcorp.com",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )

    mock_db = AsyncMock()
    mock_leads_scalars = MagicMock()
    mock_leads_scalars.all.return_value = [both_lead, op_only_lead, dr_only_lead, clean_lead]
    mock_leads_res = MagicMock()
    mock_leads_res.scalars.return_value = mock_leads_scalars
    mock_db.execute.return_value = mock_leads_res

    async def _run():
        res = await get_lead_quality_review_queue(page=1, page_size=10, db=mock_db)
        # Total in review queue union is 3 (clean_lead is excluded)
        assert res["total"] == 3
        assert len(res["records"]) == 3
        # Unique IDs in records
        rec_ids = [r["lead_id"] for r in res["records"]]
        assert len(rec_ids) == len(set(rec_ids))

        # Check distinct counts
        counts = res["counts"]
        assert counts["total_review_queue"] == 3
        assert counts["operational_queue"] == 2  # both_lead + op_only_lead
        assert counts["data_repair_actionable"] == 2  # both_lead + dr_only_lead
        assert counts["both"] == 1  # both_lead

    asyncio.run(_run())


def test_review_queue_pagination_and_search_over_union():
    """Verify that pagination and search operate cleanly over the final union."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import get_lead_quality_review_queue

    lead1 = make_lead(business_name="Alpha Exports", email="alpha@alpha.com", is_quarantined=True)
    lead2 = make_lead(
        business_name="Beta Trade Mart",
        email="info@exporttrademart.com",
        website="https://www.exporttrademart.com/",
        is_quarantined=False,
        website_association_status="verified_primary",
        email_business_association_status="matched",
    )
    lead3 = make_lead(business_name="Gamma Logistics", email="gamma@gamma.com", is_quarantined=True)

    mock_db = AsyncMock()
    mock_leads_scalars = MagicMock()
    mock_leads_scalars.all.return_value = [lead1, lead2, lead3]
    mock_leads_res = MagicMock()
    mock_leads_res.scalars.return_value = mock_leads_scalars
    mock_db.execute.return_value = mock_leads_res

    async def _run():
        # Search for "Trade Mart"
        search_res = await get_lead_quality_review_queue(search="Trade Mart", db=mock_db)
        assert search_res["total"] == 1
        assert search_res["records"][0]["business_name"] == "Beta Trade Mart"

        # Pagination: Page 1 with pageSize 2
        p1 = await get_lead_quality_review_queue(page=1, page_size=2, db=mock_db)
        assert p1["total"] == 3
        assert len(p1["records"]) == 2
        assert p1["records"][0]["business_name"] == "Alpha Exports"
        assert p1["records"][1]["business_name"] == "Beta Trade Mart"

        # Pagination: Page 2 with pageSize 2
        p2 = await get_lead_quality_review_queue(page=2, page_size=2, db=mock_db)
        assert p2["total"] == 3
        assert len(p2["records"]) == 1
        assert p2["records"][0]["business_name"] == "Gamma Logistics"

    asyncio.run(_run())


def test_review_queue_does_not_mutate_leads_or_alter_campaign_eligibility():
    """Verify displaying the queue does not mutate lead attributes or alter sendability."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from app.routers.leads import get_lead_quality_review_queue

    lead = make_lead(
        business_name="Immutable Corp",
        email="contact@immutable.com",
        website="https://immutable.com",
        is_quarantined=True,
        quarantine_reason="Test reason",
        website_association_status="candidate_match",
        email_business_association_status="unverified_association",
    )
    orig_dict = {
        "is_quarantined": lead.is_quarantined,
        "quarantine_reason": lead.quarantine_reason,
        "website_association_status": lead.website_association_status,
        "email_business_association_status": lead.email_business_association_status,
        "email": lead.email,
        "website": lead.website,
    }

    mock_db = AsyncMock()
    mock_leads_scalars = MagicMock()
    mock_leads_scalars.all.return_value = [lead]
    mock_leads_res = MagicMock()
    mock_leads_res.scalars.return_value = mock_leads_scalars
    mock_db.execute.return_value = mock_leads_res

    async def _run():
        await get_lead_quality_review_queue(db=mock_db)
        # Ensure lead object was not mutated
        assert lead.is_quarantined == orig_dict["is_quarantined"]
        assert lead.quarantine_reason == orig_dict["quarantine_reason"]
        assert lead.website_association_status == orig_dict["website_association_status"]
        assert lead.email_business_association_status == orig_dict["email_business_association_status"]
        assert lead.email == orig_dict["email"]
        assert lead.website == orig_dict["website"]
        # Ensure no write methods were called on mock_db
        assert not mock_db.add.called
        assert not mock_db.commit.called
        assert not mock_db.flush.called

    asyncio.run(_run())

