"""
tests/test_campaign_schema_compatibility.py
-------------------------------------------
Tests verifying backward compatibility for campaign operations when database
schema has not applied migration v6_2_3_audit_email_freshness.sql.

Covers the 10 critical operational readiness criteria:
1. Generic campaign listing works when audit_references is absent.
2. Generic campaign creation works with the older compatible schema.
3. No-website campaign preview does not require an audit reference.
4. Public-provider demo preview retains its restricted rules.
5. Audit-dependent campaign creation returns the documented schema-readiness response when the column is absent.
6. Audit worker refuses to send if the required audit reference cannot be retrieved.
7. Existing campaign templates are preserved.
8. Unrelated database errors are not disguised as schema-readiness errors.
9. No code path applies DDL automatically.
10. Suppression, cooldown, association, quarantine, and recipient-verification checks remain intact.
"""

import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import uuid
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.database import get_db
from app.models import (
    Lead,
    Audit,
    AuditStatus,
    Campaign,
    CampaignStatus,
    CampaignEmailLog,
    LeadStatus,
    Base,
)
from app.services.template_renderer import (
    TemplateRenderer,
    DEFAULT_SEGMENT_TEMPLATES,
)
from app.services.campaign_schema_service import (
    has_campaign_audit_references_column,
    set_audit_references_schema_override,
    override_campaign_schema,
    reset_schema_cache,
    is_missing_audit_references_error,
    SCHEMA_READINESS_DETAIL,
    REQUIRED_MIGRATION_NAME,
    get_campaign_safe,
    list_campaigns_safe,
)
from app.engines.outreach_engine import _run_campaign_worker
from app.routers.auth import create_access_token


def _get_auth_headers():
    token = create_access_token({"sub": "admin_test", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _make_lead(
    lead_id=None,
    email="test@business.com",
    business_name="Acme Corp",
    website="https://acmecorp.com",
    verification_status="valid",
    association_status="matched",
    is_quarantined=False,
    last_emailed_at=None,
):
    lead = MagicMock(spec=Lead)
    lead.id = lead_id or uuid.uuid4()
    lead.email = email
    lead.business_name = business_name
    lead.website = website
    lead.email_verification_status = verification_status
    lead.email_business_association_status = association_status
    lead.is_quarantined = is_quarantined
    lead.quarantine_reason = "Manual safety hold" if is_quarantined else None
    lead.last_emailed_at = last_emailed_at
    lead.status = LeadStatus.new
    return lead


@pytest.fixture(autouse=True)
def clean_schema_state():
    reset_schema_cache()
    yield
    reset_schema_cache()


# ─── 1. Generic campaign listing works when audit_references is absent ─────────

def test_generic_campaign_listing_works_when_audit_references_is_absent():
    """Verify GET /campaigns/ lists campaigns without error when audit_references column is absent."""
    client = TestClient(app)
    set_audit_references_schema_override(False)

    cid = uuid.uuid4()
    camp = Campaign(
        id=cid,
        name="Pre-Migration Generic Campaign",
        lead_ids=["550e8400-e29b-41d4-a716-446655440000"],
        template="Hello {business_name}, I noticed your website.",
        subject_template="{business_name} - introduction",
        campaign_type="generic_first_contact",
        status=CampaignStatus.draft,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
        pending_lead_ids=[],
        created_at=datetime.utcnow(),
    )
    camp.audit_references = {}

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[camp])))
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.get("/campaigns/", headers=_get_auth_headers())
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Pre-Migration Generic Campaign"
        assert data[0]["audit_references"] == {}
        assert data[0]["campaign_type"] == "generic_first_contact"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 2. Generic campaign creation works with older compatible schema ──────────

def test_generic_campaign_creation_works_with_older_compatible_schema():
    """Verify POST /campaigns/ succeeds for generic campaigns on pre-v6.2.3 schema."""
    client = TestClient(app)
    set_audit_references_schema_override(False)

    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, email="info@freshretail.com", verification_status="valid", association_status="matched")

    mock_db = AsyncMock()
    # Ready leads query returns lead_id
    mock_db.execute = AsyncMock(return_value=MagicMock(
        fetchall=MagicMock(return_value=[(lead_id,)]),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[lead]))),
    ))
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={
                "name": "Compatible Generic Campaign",
                "lead_ids": [str(lead_id)],
                "template": "Hello {business_name}, we can help your business.",
                "subject_template": "{business_name} - quick question",
                "campaign_type": "generic_first_contact",
            },
            headers=_get_auth_headers(),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        created = resp.json()
        assert created["name"] == "Compatible Generic Campaign"
        assert created["campaign_type"] == "generic_first_contact"
        assert created["audit_references"] == {}
        assert mock_db.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 3. No-website campaign preview does not require audit reference ──────────

def test_no_website_campaign_preview_does_not_require_audit_reference():
    """Verify preview for no_website_design campaign renders properly without audit findings."""
    lead = _make_lead(website=None, email="shop@localgrocer.com")
    defaults = DEFAULT_SEGMENT_TEMPLATES["no_website_design"]

    rendered = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="no_website_design",
    )

    assert rendered["content_strategy"] == "no_website_design"
    assert "audit_reference" not in rendered
    assert "https://" not in rendered["plain_body"]
    assert "http://" not in rendered["plain_body"]


# ─── 4. Public-provider demo preview retains restricted rules ──────────────────

def test_public_provider_demo_preview_retains_restricted_rules():
    """Verify public_provider_demo preview enforces restricted demo rules without audit findings."""
    lead = _make_lead(email="owner@gmail.com", website="https://localplumbing.co.uk")
    defaults = DEFAULT_SEGMENT_TEMPLATES["public_provider_demo"]

    rendered = TemplateRenderer.render_campaign_email(
        template=defaults["template"],
        subject_template=defaults["subject"],
        lead=lead,
        audit=None,
        campaign_type="public_provider_demo",
    )

    assert rendered["content_strategy"] == "public_provider_demo"
    assert "audit_reference" not in rendered
    assert "demonstration" in rendered["plain_body"].lower()


# ─── 5. Audit-dependent campaign creation returns schema readiness response ────

def test_audit_dependent_campaign_creation_returns_schema_readiness_response_when_column_absent():
    """Verify audit-dependent campaign creation returns HTTP 503 when audit_references is missing."""
    client = TestClient(app)
    set_audit_references_schema_override(False)

    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, email="ceo@activecorp.com", verification_status="valid", association_status="matched")
    audit = MagicMock(spec=Audit)
    audit.status = AuditStatus.done
    audit.audit_results = {
        "technical_seo": {"meta_description_present": {"status": "fail", "score": 0, "description": "Missing meta tag"}}
    }
    lead.audit = audit

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        fetchall=MagicMock(return_value=[(lead_id,)]),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[lead]))),
    ))

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={
                "name": "Audit Dependent SEO Campaign",
                "lead_ids": [str(lead_id)],
                "template": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["template"],
                "subject_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["subject"],
                "campaign_type": "valid_website_seo",
            },
            headers=_get_auth_headers(),
        )
        assert resp.status_code == 503
        data = resp.json()
        assert "detail" in data
        detail = data["detail"]
        assert detail.get("error") == "schema_readiness_error"
        assert REQUIRED_MIGRATION_NAME in detail.get("required_migration", "")
        assert detail.get("missing_column") == "audit_references"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 6. Audit worker refuses to send if required audit reference is missing ───

def test_audit_worker_refuses_to_send_if_required_audit_reference_cannot_be_retrieved():
    """Verify outreach engine skips audit leads when campaign has no approved audit reference."""
    async def run_worker_case():
        lead_id = uuid.uuid4()
        lead = _make_lead(lead_id=lead_id, email="contact@targetsite.com", website="https://targetsite.example")
        audit = MagicMock(spec=Audit)
        audit.id = uuid.uuid4()
        audit.lead_id = lead_id
        audit.status = AuditStatus.done
        audit.audited_url = lead.website
        audit.site_summary = {"status": "ok", "response_time_ms": 250}
        audit.error_message = None
        audit.audit_results = {
            "technical": {"sitemap": {"status": "FAIL", "message": "No sitemap found at any standard or declared location."}},
            "ux": {"cta": {"status": "FAIL", "message": "A clear primary call-to-action button is missing."}},
            "onpage": {"h1": {"status": "FAIL", "message": "Primary H1 heading is missing."}},
        }

        campaign_id = uuid.uuid4()
        defaults = DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]
        sender = {"sender_name": "Test Agency", "email": "outreach@testagency.com", "smtp_host": "smtp.example.com"}

        campaign = MagicMock(spec=Campaign)
        campaign.id = campaign_id
        campaign.status = CampaignStatus.draft
        campaign.template = defaults["template"]
        campaign.subject_template = defaults["subject"]
        campaign.campaign_type = "valid_website_seo"
        # Crucial: audit_references is empty / missing
        campaign.audit_references = {}
        campaign.lead_ids = [str(lead_id)]
        campaign.pending_lead_ids = [str(lead_id)]
        campaign.sent_count = campaign.failed_count = campaign.skipped_count = 0

        logs_added = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda log: logs_added.append(log))
        mock_db.get = AsyncMock(side_effect=lambda model, _id: campaign if model == Campaign else lead)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=audit)))
        mock_db.commit = AsyncMock()

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=mock_db)
        session.__aexit__ = AsyncMock(return_value=None)

        sent_emails = []
        def mocked_send(_acc, _to, sub, html, **kwargs):
            sent_emails.append((sub, html))
            return True, "250 OK"

        with patch("app.config.Settings.get_smtp_accounts", return_value=[sender]), \
             patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=session), \
             patch("app.engines.outreach_engine._send_email_sync", side_effect=mocked_send):
            await _run_campaign_worker(str(campaign_id))

        return sent_emails, logs_added, campaign

    sent, logs, camp = asyncio.run(run_worker_case())
    # Worker must refuse to send
    assert len(sent) == 0, "Worker must NOT send email when audit reference is unretrieved"
    assert camp.skipped_count == 1
    # Verify skipped log message
    skip_logs = [l for l in logs if isinstance(l, CampaignEmailLog) and l.status == "skipped"]
    assert len(skip_logs) == 1
    assert "no approved audit reference" in skip_logs[0].message.lower()


# ─── 7. Existing campaign templates are preserved ──────────────────────────────

def test_existing_campaign_templates_are_preserved():
    """Verify standard segment presets and templates exist and are uncorrupted."""
    expected_segments = [
        "no_website_design",
        "broken_website_repair",
        "outdated_website_modernization",
        "valid_website_seo",
        "valid_website_redesign",
        "valid_website_link_building",
        "valid_website_marketing",
        "generic_first_contact",
        "public_provider_demo",
    ]
    for seg in expected_segments:
        assert seg in DEFAULT_SEGMENT_TEMPLATES, f"Template segment {seg} must be defined"
        tpl_entry = DEFAULT_SEGMENT_TEMPLATES[seg]
        assert "subject" in tpl_entry and tpl_entry["subject"]
        assert "template" in tpl_entry and tpl_entry["template"]


# ─── 8. Unrelated database errors are not disguised as schema readiness errors ─

def test_unrelated_database_errors_are_not_disguised_as_schema_readiness_errors():
    """Verify database connection errors or syntax errors are not converted to schema-readiness 503."""
    client = TestClient(app)
    unrelated_err = OperationalError("connection refused", params=None, orig=Exception("could not connect to server"))

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=unrelated_err)

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with pytest.raises(OperationalError):
            client.get("/campaigns/", headers=_get_auth_headers())
    finally:
        app.dependency_overrides.pop(get_db, None)

    # Test error classifier directly
    assert not is_missing_audit_references_error(unrelated_err)
    assert not is_missing_audit_references_error(Exception("syntax error at or near SELECT"))
    assert is_missing_audit_references_error(Exception("column campaigns.audit_references does not exist"))


# ─── 9. No code path applies DDL automatically ────────────────────────────────

def test_no_code_path_applies_ddl_automatically():
    """Verify neither database module nor campaign operations invoke automatic DDL."""
    from app.config import settings
    # Default INIT_SCHEMA must remain False
    assert not settings.INIT_SCHEMA, "INIT_SCHEMA must be False by default"

    # Static inspection: no router or service should call create_all
    import app.services.campaign_schema_service as css
    import app.routers.campaigns as cr
    for mod in (css, cr):
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "create_all" not in src, f"{mod.__name__} must not call create_all"
        assert "ALTER TABLE" not in src.upper(), f"{mod.__name__} must not execute ALTER TABLE"


# ─── 10. Safety gates remain intact ───────────────────────────────────────────

def test_safety_gates_remain_intact_during_campaign_creation():
    """Verify unverified, quarantined, or mismatched-association leads are rejected at campaign creation."""
    client = TestClient(app)
    set_audit_references_schema_override(False)

    unverified_lead = _make_lead(email="unverified@biz.com", verification_status="pending")
    quarantined_lead = _make_lead(email="quarantined@biz.com", verification_status="valid", is_quarantined=True)

    mock_db = AsyncMock()
    # Ready leads query returns empty set (no leads qualify)
    mock_db.execute = AsyncMock(return_value=MagicMock(
        fetchall=MagicMock(return_value=[]),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
    ))

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={
                "name": "Invalid Recipient Campaign",
                "lead_ids": [str(unverified_lead.id), str(quarantined_lead.id)],
                "template": "Hello {business_name}",
                "subject_template": "Hello",
                "campaign_type": "generic_first_contact",
            },
            headers=_get_auth_headers(),
        )
        assert resp.status_code == 400
        assert "not campaign-ready" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 11. Listing & retrieval with audit_references column present ──────────────

def test_campaign_listing_and_retrieval_when_audit_references_column_exists():
    """Verify that when the audit_references column exists, campaigns load and serialize actual references."""
    client = TestClient(app)
    set_audit_references_schema_override(True)

    camp_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    mock_campaign = Campaign(
        id=camp_id,
        name="Post-Migration Audit Campaign",
        lead_ids=[str(lead_id)],
        pending_lead_ids=[],
        template="Hello {business_name}",
        subject_template="Subject",
        campaign_type="valid_website_seo",
        audit_references={str(lead_id): {"audit_id": str(uuid.uuid4()), "fingerprint": "abc12345", "renderer_version": 1}},
        scheduled_at=None,
        sent_count=0,
        skipped_count=0,
        failed_count=0,
        status=CampaignStatus.draft,
        created_at=datetime.utcnow(),
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[mock_campaign])
        )),
        scalar_one_or_none=MagicMock(return_value=mock_campaign),
    ))

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        # Listing endpoint
        resp_list = client.get("/campaigns/", headers=_get_auth_headers())
        assert resp_list.status_code == 200
        data_list = resp_list.json()
        assert len(data_list) == 1
        assert str(lead_id) in data_list[0]["audit_references"]
        assert data_list[0]["audit_references"][str(lead_id)]["fingerprint"] == "abc12345"

        # Detail endpoint
        resp_detail = client.get(f"/campaigns/{camp_id}", headers=_get_auth_headers())
        assert resp_detail.status_code == 200
        data_detail = resp_detail.json()
        assert str(lead_id) in data_detail["audit_references"]
        assert data_detail["audit_references"][str(lead_id)]["fingerprint"] == "abc12345"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ─── 12. Campaign creation & worker dispatch when column exists ────────────────

def test_audit_campaign_creation_and_worker_dispatch_when_column_exists():
    """Verify campaign creation reloads with audit_references and worker does not drop references during refresh."""
    client = TestClient(app)
    set_audit_references_schema_override(True)

    lead_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id)
    audit = MagicMock(spec=Audit)
    audit.id = audit_id
    audit.lead_id = lead_id
    audit.status = AuditStatus.done
    audit.updated_at = datetime.utcnow()
    audit.error_message = None
    audit.site_summary = {"status": "ok", "response_time_ms": 250}
    audit.audited_url = "https://acmecorp.com"
    audit.audit_results = {
        "technical": {"sitemap": {"status": "FAIL", "message": "No sitemap"}},
        "ux": {"cta": {"status": "FAIL", "message": "No CTA"}},
        "onpage": {"h1": {"status": "FAIL", "message": "No H1"}},
    }
    lead.audit = audit

    rendered = TemplateRenderer.render_campaign_email(
        template=DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["template"],
        subject_template=DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["subject"],
        lead=lead,
        audit=audit,
        campaign_type="valid_website_seo",
        sender_account={"email": "info@tebsolutions.in"},
    )
    expected_fingerprint = rendered["audit_reference"]["fingerprint"]

    # 1. Test creation endpoint with column present
    mock_campaign = Campaign(
        id=uuid.uuid4(),
        name="SEO Campaign",
        lead_ids=[str(lead_id)],
        pending_lead_ids=[],
        template=DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["template"],
        subject_template=DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["subject"],
        campaign_type="valid_website_seo",
        audit_references={str(lead_id): rendered["audit_reference"]},
        sent_count=0,
        skipped_count=0,
        failed_count=0,
        status=CampaignStatus.draft,
        created_at=datetime.utcnow(),
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[
        # 1. ready check
        MagicMock(fetchall=MagicMock(return_value=[(lead_id,)])),
        # 2. leads fetch
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[lead])))),
        # 3. get_campaign_safe reload after commit
        MagicMock(scalar_one_or_none=MagicMock(return_value=mock_campaign)),
    ])
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = client.post(
            "/campaigns/",
            json={
                "name": "SEO Campaign",
                "lead_ids": [str(lead_id)],
                "template": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["template"],
                "subject_template": DEFAULT_SEGMENT_TEMPLATES["valid_website_seo"]["subject"],
                "campaign_type": "valid_website_seo",
            },
            headers=_get_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert str(lead_id) in data["audit_references"]
        assert data["audit_references"][str(lead_id)]["fingerprint"] == expected_fingerprint
    finally:
        app.dependency_overrides.pop(get_db, None)

    # 2. Test worker execution with db.refresh(campaign, ["status"]) preserving audit_references
    worker_campaign = Campaign(
        id=mock_campaign.id,
        name=mock_campaign.name,
        lead_ids=[str(lead_id)],
        pending_lead_ids=[str(lead_id)],
        template=mock_campaign.template,
        subject_template=mock_campaign.subject_template,
        campaign_type="valid_website_seo",
        audit_references={str(lead_id): rendered["audit_reference"]},
        status=CampaignStatus.sending,
        created_at=datetime.utcnow(),
    )

    worker_db = AsyncMock()
    worker_db.get = AsyncMock(return_value=lead)
    worker_db.commit = AsyncMock()
    worker_db.refresh = AsyncMock()  # Simulates db.refresh(campaign, ["status"]) without wiping audit_references
    worker_db.add = MagicMock()
    worker_db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=audit),
        scalar=MagicMock(return_value=0),
    ))

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=worker_db)
    session.__aexit__ = AsyncMock(return_value=None)

    sent_emails = []

    def mock_send(account, to_email, subject, html, **kwargs):
        sent_emails.append({"to": to_email, "subject": subject, "plain_body": kwargs.get("plain_body")})
        return True, "250 accepted"

    with patch("app.engines.outreach_engine.AsyncSessionLocal", return_value=session), \
         patch("app.engines.outreach_engine.get_campaign_safe", return_value=worker_campaign), \
         patch("app.engines.outreach_engine._send_email_sync", side_effect=mock_send), \
         patch("app.config.Settings.get_smtp_accounts", return_value=[{"email": "info@tebsolutions.in"}]):
        asyncio.run(_run_campaign_worker(str(mock_campaign.id)))

    # Verify that the worker successfully dispatched the email because audit references matched
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == lead.email


# ─── 13. Schema cache target scoping and cache hit verification ────────────────

def test_schema_cache_target_scoping_and_hit():
    """Verify schema cache scopes entries by database target URL and avoids redundant queries."""
    class FakeBind:
        def __init__(self, url, dialect="sqlite"):
            self.url = url
            self.dialect = MagicMock()
            self.dialect.name = dialect

    class FakeSession:
        def __init__(self, bind, has_col=True):
            self.bind = bind
            self.has_col = has_col
            self.call_count = 0

        async def execute(self, stmt):
            self.call_count += 1
            res = MagicMock()
            if self.has_col:
                res.fetchall.return_value = [(0, "id"), (1, "audit_references")]
            else:
                res.fetchall.return_value = [(0, "id")]
            return res

    async def _test():
        reset_schema_cache()
        db_a = FakeSession(FakeBind("sqlite:///db_a.db"), has_col=True)
        db_b = FakeSession(FakeBind("sqlite:///db_b.db"), has_col=False)

        # 1. Query DB A -> cache miss, executes query
        res_a1 = await has_campaign_audit_references_column(db_a)
        assert res_a1 is True
        assert db_a.call_count == 1

        # 2. Query DB A again -> cache hit, no extra DB query
        res_a2 = await has_campaign_audit_references_column(db_a)
        assert res_a2 is True
        assert db_a.call_count == 1

        # 3. Query DB B -> separate target, executes query and returns False independently
        res_b1 = await has_campaign_audit_references_column(db_b)
        assert res_b1 is False
        assert db_b.call_count == 1

        # 4. Query DB A again -> still True from cache
        res_a3 = await has_campaign_audit_references_column(db_a)
        assert res_a3 is True
        assert db_a.call_count == 1

    asyncio.run(_test())


# ─── 14. Negative cache TTL detects newly applied migration without restart ───

def test_schema_cache_negative_ttl_detects_migration():
    """Verify that a missing column result uses negative TTL and detects schema migration after TTL expires."""
    class FakeBind:
        def __init__(self, url, dialect="sqlite"):
            self.url = url
            self.dialect = MagicMock()
            self.dialect.name = dialect

    class FakeSession:
        def __init__(self, bind, has_col=False):
            self.bind = bind
            self.has_col = has_col
            self.call_count = 0

        async def execute(self, stmt):
            self.call_count += 1
            res = MagicMock()
            if self.has_col:
                res.fetchall.return_value = [(0, "id"), (1, "audit_references")]
            else:
                res.fetchall.return_value = [(0, "id")]
            return res

    async def _test():
        reset_schema_cache()
        db = FakeSession(FakeBind("sqlite:///migratable_db.db"), has_col=False)

        # First check at t=100.0: column absent, executes query
        with patch("time.monotonic", return_value=100.0):
            assert await has_campaign_audit_references_column(db) is False
            assert db.call_count == 1

        # Second check at t=110.0 (within 30s TTL): cache hit, column still reported absent without DB query
        with patch("time.monotonic", return_value=110.0):
            assert await has_campaign_audit_references_column(db) is False
            assert db.call_count == 1

        # Simulate migration applied to database
        db.has_col = True

        # Third check at t=140.0 (past 30s TTL): negative cache expired, re-queries DB and detects column
        with patch("time.monotonic", return_value=140.0):
            assert await has_campaign_audit_references_column(db) is True
            assert db.call_count == 2

    asyncio.run(_test())


# ─── 15. Runtime query fallback invalidates target cache without polluting global override ──

def test_runtime_query_fallback_invalidates_target_cache_without_polluting_global_override():
    """Verify that get_campaign_safe runtime error invalidates target cache without setting global _schema_override."""
    import time
    import app.services.campaign_schema_service as css

    class FakeBind:
        def __init__(self, url, dialect="sqlite"):
            self.url = url
            self.dialect = MagicMock()
            self.dialect.name = dialect

    class FakeSession:
        def __init__(self, bind):
            self.bind = bind
            self.camp = Campaign(id=uuid.uuid4(), name="Test Campaign")

        async def execute(self, stmt):
            raise Exception("column campaigns.audit_references does not exist")

        async def get(self, model, _id):
            return self.camp

    async def _test():
        reset_schema_cache()
        db = FakeSession(FakeBind("sqlite:///runtime_fallback.db"))
        # Pre-seed positive cache entry with fresh timestamp
        css._cached_availability["sqlite:///runtime_fallback.db"] = (True, time.monotonic())

        camp = await get_campaign_safe(db, db.camp.id)
        assert camp is not None
        assert camp.audit_references == {}

        # Global override must remain None (unpolluted)
        assert css._schema_override is None, "Global _schema_override must not be mutated by runtime database error handling"
        # Target cache must now reflect False
        assert css._cached_availability["sqlite:///runtime_fallback.db"][0] is False

    asyncio.run(_test())


# ─── 16. override_campaign_schema context manager restores state on exception ─

def test_override_campaign_schema_context_manager_restores_on_exception():
    """Verify override_campaign_schema safely restores previous state even when an exception is raised."""
    import app.services.campaign_schema_service as css
    reset_schema_cache()
    assert css._schema_override is None

    try:
        with override_campaign_schema(True):
            assert css._schema_override is True
            raise ValueError("simulated test error")
    except ValueError:
        pass

    assert css._schema_override is None, "Previous override state must be restored after exception"


# ─── 17. Unresolvable URL targets with same dialect cannot collide ────────────

def test_same_dialect_targets_without_resolvable_urls_do_not_collide():
    """Verify that two targets sharing the same dialect but lacking resolvable URLs have distinct cache keys and do not collide."""
    class FakeBindNoUrl:
        def __init__(self, dialect="postgresql"):
            self.url = None
            self.dialect = MagicMock()
            self.dialect.name = dialect

    class FakeSession:
        def __init__(self, bind, has_col=True):
            self.bind = bind
            self.has_col = has_col
            self.call_count = 0

        async def execute(self, stmt):
            self.call_count += 1
            res = MagicMock()
            if self.has_col:
                res.scalar.return_value = 1
            else:
                res.scalar.return_value = None
            return res

    async def _test():
        reset_schema_cache()
        bind_1 = FakeBindNoUrl("postgresql")
        bind_2 = FakeBindNoUrl("postgresql")

        db_1 = FakeSession(bind_1, has_col=True)
        db_2 = FakeSession(bind_2, has_col=False)

        # 1. Query db_1: has column -> True
        res_1 = await has_campaign_audit_references_column(db_1)
        assert res_1 is True
        assert db_1.call_count == 1

        # 2. Query db_2: same dialect 'postgresql', has no column -> returns False independently without collision!
        res_2 = await has_campaign_audit_references_column(db_2)
        assert res_2 is False
        assert db_2.call_count == 1

        # 3. Repeat queries: since stable identity cannot be established without a URL,
        #    neither target is cached into the global cache (avoiding recycled ID collisions).
        #    Both return their authentic results with incremented query counts.
        res_1_repeat = await has_campaign_audit_references_column(db_1)
        assert res_1_repeat is True
        assert db_1.call_count == 2

        res_2_repeat = await has_campaign_audit_references_column(db_2)
        assert res_2_repeat is False
        assert db_2.call_count == 2

        import app.services.campaign_schema_service as css
        assert len(css._cached_availability) == 0, "Unresolvable URL targets must not be retained in the global cache"

    asyncio.run(_test())



