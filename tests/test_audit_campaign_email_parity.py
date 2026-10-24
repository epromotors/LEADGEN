"""Regression coverage for the single audit-email source of truth.

All delivery is mocked.  The fixture represents the three verified findings
from the reported mismatch without depending on a real business or database.
"""

import asyncio
import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.engines.outreach_engine import _run_campaign_worker
from app.models import Audit, AuditStatus, Campaign, CampaignStatus, Lead
from app.services.proposal_service import ProposalService
from app.services.template_renderer import DEFAULT_SEGMENT_TEMPLATES, TemplateRenderer


def _fixture():
    lead = MagicMock(spec=Lead)
    lead.id = uuid.uuid4()
    lead.business_name = "Synthetic Dockship Export"
    lead.website = "https://synthetic-dockship.example"
    lead.email = "owner@synthetic-dockship.example"
    lead.email_verification_status = "valid"
    lead.email_business_association_status = "matched"
    lead.is_quarantined = False
    lead.quarantine_reason = None
    lead.last_emailed_at = None

    audit = MagicMock(spec=Audit)
    audit.id = uuid.uuid4()
    audit.lead_id = lead.id
    audit.status = AuditStatus.done
    audit.audited_url = lead.website
    audit.updated_at = datetime(2026, 10, 20, 8, 0, 0)
    audit.site_summary = {"status": "ok", "response_time_ms": 250}
    audit.error_message = None
    audit.audit_results = {
        "technical": {"sitemap": {"status": "FAIL", "message": "No sitemap found at any standard or declared location."}},
        "ux": {"cta": {"status": "FAIL", "message": "A clear primary call-to-action button is missing."}},
        "onpage": {"h1": {"status": "FAIL", "message": "Primary H1 heading is missing."}},
    }
    return lead, audit


def test_dashboard_campaign_preview_and_worker_share_the_dockship_fixture_message():
    lead, audit = _fixture()
    sender = {"sender_name": "TEB Solutions", "email": "info@tebsolutions.in"}
    campaign_type = "valid_website_seo"
    defaults = DEFAULT_SEGMENT_TEMPLATES[campaign_type]

    # Dashboard path: ProposalService is the API backing Audits.jsx.
    dashboard = ProposalService.get_or_create_proposal(
        lead_id=str(lead.id),
        business_name=lead.business_name,
        website_url=lead.website,
        audit_results=audit.audit_results,
        url_info={"requested_url": lead.website, "site_summary": audit.site_summary},
        audit_id=str(audit.id),
        audit_updated_at=audit.updated_at,
        sender_agency=sender["sender_name"],
        contact_email=sender["email"],
    )
    # Campaign preview path and the worker renderer both use TemplateRenderer.
    preview = TemplateRenderer.render_campaign_email(
        defaults["template"], defaults["subject"], lead, audit, campaign_type, sender
    )
    worker_payload = TemplateRenderer.render_campaign_email(
        defaults["template"], defaults["subject"], lead, audit, campaign_type, sender
    )

    assert preview["content_strategy"] == "audit_generated"
    assert dashboard["subject"] == preview["subject"] == worker_payload["subject"]
    assert dashboard["body_text"] == preview["plain_body"] == worker_payload["plain_body"]
    assert dashboard["body_html"] == preview["html_body"] == worker_payload["html_body"]
    for expected in (
        "Sitemap Discovery & Indexing Architecture",
        "Web Design & Conversion UX Repair",
        "AI-Search Readiness & Entity Optimization",
        "No sitemap found at any standard or declared location.",
        "A clear primary call-to-action button is missing.",
        "Primary H1 heading is missing.",
        "Recommended Action:",
    ):
        assert expected in preview["plain_body"]
    assert "Modern First Impression" not in preview["plain_body"]


def test_worker_sends_the_reviewed_audit_payload_and_blocks_changed_evidence():
    async def run_case(change_audit=False):
        lead, audit = _fixture()
        campaign_id = uuid.uuid4()
        defaults = DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]
        sender = {"sender_name": "TEB Solutions", "email": "info@tebsolutions.in", "smtp_host": "smtp.hostinger.com"}
        approved = TemplateRenderer.render_campaign_email(
            defaults["template"], defaults["subject"], lead, audit, "valid_website_seo", sender
        )
        expected_text = approved["plain_body"]
        if change_audit:
            audit.audit_results["onpage"]["h1"]["message"] = "Primary H1 heading still missing after a re-audit."

        campaign = MagicMock(spec=Campaign)
        campaign.id = campaign_id
        campaign.status = CampaignStatus.draft
        campaign.template = defaults["template"]
        campaign.subject_template = defaults["subject"]
        campaign.campaign_type = "valid_website_seo"
        campaign.audit_references = {str(lead.id): approved["audit_reference"]}
        campaign.lead_ids = [str(lead.id)]
        campaign.pending_lead_ids = [str(lead.id)]
        campaign.sent_count = campaign.failed_count = campaign.skipped_count = 0

        db = AsyncMock()
        db.add = MagicMock()
        db.get = AsyncMock(side_effect=lambda model, _id: campaign if model == Campaign else lead)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=audit)))
        db.commit = AsyncMock()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=db)
        session.__aexit__ = AsyncMock(return_value=None)
        sent = []

        def mocked_send(_account, _to, subject, html_body, **kwargs):
            sent.append((subject, html_body, kwargs["plain_body"]))
            return True, "250 accepted"

        with patch("app.config.Settings.get_smtp_accounts", return_value=[sender]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=session), \
             patch("app.engines.outreach_engine._send_email_sync", side_effect=mocked_send):
            await _run_campaign_worker(str(campaign_id))

        return sent, expected_text, campaign

    sent, expected_text, campaign = asyncio.run(run_case())
    assert len(sent) == 1
    assert sent[0][2] == expected_text
    assert campaign.sent_count == 1

    sent_after_change, _, stale_campaign = asyncio.run(run_case(change_audit=True))
    assert sent_after_change == []
    assert stale_campaign.skipped_count == 1
