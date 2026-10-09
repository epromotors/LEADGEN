import uuid
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel

from app.models import LeadStatus, AuditStatus, CampaignStatus


# ─── Shared UTC Base ──────────────────────────────────────────────────────────
# All response models inherit this so datetimes always serialize with 'Z' suffix.
# Without this, the backend returns naive datetimes like "2026-04-04T13:30:27"
# which JavaScript treats as LOCAL time — causing ~5.5 hr shift for IST users.

def _as_utc(v: datetime) -> str:
    """Emit a datetime as a UTC ISO-8601 string with 'Z' suffix.
    Naive datetimes (from SQLAlchemy) are assumed to be UTC already.
    """
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class UTCBase(BaseModel):
    """Base model: serialises all datetime fields as UTC ISO-8601 with 'Z' suffix."""
    model_config = {
        "from_attributes": True,
        "json_encoders": {datetime: _as_utc},
    }






# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Leads ────────────────────────────────────────────────────────────────────

class LeadResponse(UTCBase):
    id: uuid.UUID
    business_name: str
    email: str
    phone: Optional[str]
    website: str
    status: LeadStatus
    last_emailed_at: Optional[datetime] = None
    created_at: datetime
    # Reply tracking
    replied_at: Optional[datetime] = None
    reply_snippet: Optional[str] = None
    reply_type: Optional[str] = None
    # Carries the SITE_STATUS:... tag for skipped leads — used by the table status badge.
    # Populated at the router layer from the eagerly-loaded Lead.audit relationship.
    audit_error: Optional[str] = None
    audit_status: Optional[AuditStatus] = None


class LeadUpdate(BaseModel):
    business_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None


class LeadListResponse(BaseModel):
    total: int
    items: List[LeadResponse]


# ─── Audits ───────────────────────────────────────────────────────────────────

class AuditResponse(UTCBase):
    id: uuid.UUID
    lead_id: uuid.UUID
    ssl_valid: Optional[bool]
    has_sitemap: Optional[bool]
    has_robots: Optional[bool]
    broken_links_count: int
    missing_h1: Optional[bool]
    missing_alt_count: int
    uses_webp: Optional[bool]
    has_json_ld: Optional[bool]
    mobile_friendly: Optional[bool]
    missing_social: Optional[list]
    audit_summary: Optional[str]
    suggested_name: Optional[str]
    pdf_path: Optional[str]
    status: AuditStatus
    audit_lifecycle: Optional[str] = None
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    # Geo-smart currency detection
    country_code: Optional[str] = None
    currency_code: Optional[str] = None
    currency_symbol: Optional[str] = None
    detected_via: Optional[str] = None
    # Phase 2: extra checks
    has_canonical: Optional[bool] = None
    has_page_title: Optional[bool] = None
    has_meta_desc: Optional[bool] = None
    has_og_tags: Optional[bool] = None
    has_lazy_load: Optional[bool] = None
    has_contact: Optional[bool] = None
    has_whatsapp: Optional[bool] = None
    has_trust: Optional[bool] = None
    # Raw 19-factor payload + crawl data
    seo_score: Optional[int] = None
    audited_url: Optional[str] = None
    audit_results: Optional[dict] = None
    site_summary: Optional[dict] = None
    page_audits: Optional[list] = None
    # Phase 3: UI/UX Axis (v4.5.0)
    has_cta: Optional[bool] = None
    cta_above_fold: Optional[bool] = None
    has_hero_headline: Optional[bool] = None
    font_size_ok: Optional[bool] = None
    contrast_ok: Optional[bool] = None
    nav_links_count: Optional[int] = None
    has_cookie_notice: Optional[bool] = None
    has_live_chat: Optional[bool] = None
    ux_score: Optional[int] = None

    # ── v5.0 new — Technical Extended ────────────────────────────────────────
    has_https_redirect:   Optional[bool] = None
    redirect_chain_ok:    Optional[bool] = None
    has_mixed_content:    Optional[bool] = None
    www_canonical_ok:     Optional[bool] = None

    # ── v5.0 new — Onpage Extended ───────────────────────────────────────────
    has_noindex:          Optional[bool] = None
    heading_hierarchy_ok: Optional[bool] = None
    internal_links_count: Optional[int]  = None
    anchor_text_ok:       Optional[bool] = None
    image_filenames_ok:   Optional[bool] = None

    # ── v5.0 new — UX Extended ───────────────────────────────────────────────
    has_phone_number:     Optional[bool] = None
    has_address:          Optional[bool] = None

    # ── v5.0 new — Indexability ──────────────────────────────────────────────
    url_structure_ok:     Optional[bool] = None
    www_nonwww_ok:        Optional[bool] = None
    soft_404_ok:          Optional[bool] = None

    # ── v5.0 new — Content Quality ───────────────────────────────────────────
    word_count:           Optional[int]  = None
    duplicate_meta_ok:    Optional[bool] = None
    keyword_in_title_ok:  Optional[bool] = None
    reading_level_ok:     Optional[bool] = None

    # ── v5.0 new — Local SEO ─────────────────────────────────────────────────
    has_nap:                   Optional[bool] = None
    has_local_business_schema: Optional[bool] = None
    has_google_maps:           Optional[bool] = None
    city_in_title_ok:          Optional[bool] = None
    has_business_hours:        Optional[bool] = None

    # ── v5.0 new — Performance ───────────────────────────────────────────────
    response_time_ms:    Optional[int]  = None
    page_size_ok:        Optional[bool] = None
    render_blocking_ok:  Optional[bool] = None
    gzip_enabled:        Optional[bool] = None
    webp_coverage_ok:    Optional[bool] = None
    minification_ok:     Optional[bool] = None

    # ── v5.0 new — Schema Advanced ───────────────────────────────────────────
    has_faq_schema:        Optional[bool] = None
    has_product_schema:    Optional[bool] = None
    has_breadcrumb_schema: Optional[bool] = None
    has_review_schema:     Optional[bool] = None
    schema_graph_ok:       Optional[bool] = None

    # ── Phase 2 — Browser evidence (additive, backward-compatible) ───────────
    # browser_status: DISABLED | SUCCESS | PARTIAL | TIMEOUT | BLOCKED |
    #                 CRASHED | FAILED | UNAVAILABLE | ERROR
    # browser_evidence is stored in site_summary["browser_evidence"] and exposed
    # here as a convenience alias.  Consumers should check browser_status first.
    # A non-SUCCESS status must NOT be interpreted as a website audit finding.
    browser_status: Optional[str] = None
    browser_evidence: Optional[dict] = None


# ─── Campaigns ────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    lead_ids: List[str]
    template: str
    subject_template: str = "{business_name} - quick question"
    scheduled_at: Optional[datetime] = None


class CampaignResponse(UTCBase):
    id: uuid.UUID
    name: str
    lead_ids: list
    template: str
    subject_template: str
    scheduled_at: Optional[datetime]
    sent_count: int
    skipped_count: int
    failed_count: int
    status: CampaignStatus
    next_email_at: Optional[datetime]
    paused_at: Optional[datetime]
    created_at: datetime


class CampaignEmailLogResponse(UTCBase):
    id: uuid.UUID
    campaign_id: uuid.UUID
    lead_id: Optional[uuid.UUID]
    business_name: str
    email: str
    status: str
    message: Optional[str]
    created_at: datetime



# ─── Activity Log ─────────────────────────────────────────────────────────────

class ActivityLogResponse(UTCBase):
    id: uuid.UUID
    event_type: str
    lead_id: Optional[uuid.UUID]
    message: str
    created_at: datetime



# ─── Dashboard Metrics ────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    total_leads: int
    audits_complete: int
    emails_sent: int
    campaigns_active: int
