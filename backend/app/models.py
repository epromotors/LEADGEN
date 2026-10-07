import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class LeadStatus(str, enum.Enum):
    new       = "new"
    auditing  = "auditing"
    audited   = "audited"
    emailed   = "emailed"
    replied   = "replied"
    converted = "converted"   # replied positively — hot lead


class AuditStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done    = "done"
    failed  = "failed"


class CampaignStatus(str, enum.Enum):
    draft    = "draft"
    scheduled = "scheduled"
    sending  = "sending"
    paused   = "paused"
    done     = "done"


# ─── Models ───────────────────────────────────────────────────────────────────

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus, name="leadstatus"), default=LeadStatus.new
    )
    last_emailed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_email_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ── Reply tracking ──────────────────────────────────────────────────────────
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)       # first 500 chars of reply
    reply_type: Mapped[str | None] = mapped_column(String(30), nullable=True)    # positive|stop|bounce|soft_bounce

    audit: Mapped["Audit | None"] = relationship(
        "Audit", back_populates="lead", uselist=False, passive_deletes=True
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="lead", passive_deletes=True
    )


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # ── 10 Audit Factors ──────────────────────────────────────────────────────
    ssl_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_sitemap: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_robots: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    broken_links_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_h1: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing_alt_count: Mapped[int] = mapped_column(Integer, default=0)
    uses_webp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_json_ld: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mobile_friendly: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing_social: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Phase 2: 7 extra checks (added — nullable for backwards compat) ────────
    has_canonical: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_page_title: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_meta_desc: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_og_tags: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_lazy_load: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_contact: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_whatsapp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_trust: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── Phase 3: UI/UX Axis (v4.5.0 — all nullable for backwards compat) ──────
    has_cta: Mapped[bool | None] = mapped_column(Boolean, nullable=True)          # Clear CTA button present
    cta_above_fold: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # CTA visible without scrolling
    has_hero_headline: Mapped[bool | None] = mapped_column(Boolean, nullable=True) # Hero value-prop heading
    font_size_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)     # Body text >= 14px
    contrast_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)      # Text contrast passes basic check
    nav_links_count: Mapped[int | None] = mapped_column(Integer, nullable=True)   # Number of nav links found
    has_cookie_notice: Mapped[bool | None] = mapped_column(Boolean, nullable=True) # GDPR cookie banner detected
    has_live_chat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)    # Live chat widget detected
    ux_score: Mapped[int | None] = mapped_column(Integer, nullable=True)          # UI/UX axis score (0-100)

    # ── v5.0 new — Technical Extended (all nullable for backwards compat) ───────
    has_https_redirect:   Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    redirect_chain_ok:    Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_mixed_content:    Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # True = bad
    www_canonical_ok:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Onpage Extended ────────────────────────────────────────────
    has_noindex:          Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # True = bad
    heading_hierarchy_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    internal_links_count: Mapped[int | None]  = mapped_column(Integer, nullable=True)
    anchor_text_ok:       Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    image_filenames_ok:   Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — UX Extended ────────────────────────────────────────────────
    has_phone_number:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_address:          Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Indexability ───────────────────────────────────────────────
    url_structure_ok:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    www_nonwww_ok:        Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    soft_404_ok:          Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Content Quality ────────────────────────────────────────────
    word_count:           Mapped[int | None]  = mapped_column(Integer, nullable=True)
    duplicate_meta_ok:    Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    keyword_in_title_ok:  Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reading_level_ok:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Local SEO ──────────────────────────────────────────────────
    has_nap:                   Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_local_business_schema: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_google_maps:           Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    city_in_title_ok:          Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_business_hours:        Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Performance ────────────────────────────────────────────────
    response_time_ms:    Mapped[int | None]  = mapped_column(Integer, nullable=True)
    page_size_ok:        Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    render_blocking_ok:  Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gzip_enabled:        Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    webp_coverage_ok:    Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    minification_ok:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── v5.0 new — Schema Advanced ────────────────────────────────────────────
    has_faq_schema:        Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_product_schema:    Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_breadcrumb_schema: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_review_schema:     Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    schema_graph_ok:       Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Raw 55-factor audit payload (preserves PASS/WARN/FAIL + messages)

    seo_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audited_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audit_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    site_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    page_audits: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Synthesis ─────────────────────────────────────────────────────────────
    audit_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[AuditStatus] = mapped_column(
        SAEnum(AuditStatus, name="auditstatus"), default=AuditStatus.pending
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ── Geo-smart currency detection (set during audit, used for localised pricing) ──
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)   # e.g. 'GB', 'US', 'AU'
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)  # e.g. 'GBP', 'USD'
    currency_symbol: Mapped[str | None] = mapped_column(String(10), nullable=True) # e.g. '£', '$'
    detected_via: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 'phone'|'address'|'tld'|'fallback'

    lead: Mapped["Lead"] = relationship("Lead", back_populates="audit")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_ids: Mapped[list] = mapped_column(JSON, default=list)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    subject_template: Mapped[str] = mapped_column(String(500), default="")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="campaignstatus"), default=CampaignStatus.draft
    )
    # ── Progress tracking ─────────────────────────────────────────────────────
    pending_lead_ids: Mapped[list] = mapped_column(JSON, default=list)   # remaining to send
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)       # skipped (emailed within 7 days)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)        # failed sends
    next_email_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # ETA for next email
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    email_logs: Mapped[list["CampaignEmailLog"]] = relationship(
        "CampaignEmailLog", back_populates="campaign",
        order_by="CampaignEmailLog.created_at.desc()", passive_deletes=True
    )


class CampaignEmailLog(Base):
    """Per-email audit trail for a campaign — one row per email attempt."""
    __tablename__ = "campaign_email_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    business_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(30), default="sent")   # sent | failed | skipped
    message: Mapped[str | None] = mapped_column(Text, nullable=True)  # error/skip reason
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="email_logs")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped["Lead | None"] = relationship("Lead", back_populates="activity_logs")


class EmailCorrection(Base):
    """Tracks auto-detected email mismatches between the lead DB email and
    the domain-matched email found on the lead's website. Awaits user review."""
    __tablename__ = "email_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    old_email: Mapped[str] = mapped_column(String(255), nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "homepage_text"
    status: Mapped[str] = mapped_column(
        String(30), default="pending"  # pending | accepted | dismissed
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lead: Mapped["Lead"] = relationship("Lead")
