import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String, Boolean, Integer, Float, Text, DateTime, ForeignKey, Enum as SAEnum, JSON, event
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, Mapper
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
    draft     = "draft"
    scheduled = "scheduled"
    sending   = "sending"
    done      = "done"
    paused    = "paused"


class EmailAssociationStatus(str, enum.Enum):
    MATCHED = "matched"
    APPROVED = "approved"
    EXTERNAL_DOMAIN_REVIEW = "external_domain_review"
    UNVERIFIED_ASSOCIATION = "unverified_association"
    MISMATCHED_SOURCE = "mismatched_source"
    INVALID_FORMAT = "invalid_format"


class WebsiteAssociationStatus(str, enum.Enum):
    VERIFIED_PRIMARY = "verified_primary"
    CANDIDATE_MATCH = "candidate_match"
    UNVERIFIED_SEARCH = "unverified_search"
    NO_WEBSITE = "no_website"
    CONFLICTING = "conflicting"
    INCONCLUSIVE = "inconclusive"


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Reply tracking ──────────────────────────────────────────────────────────
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)       # first 500 chars of reply
    reply_type: Mapped[str | None] = mapped_column(String(30), nullable=True)    # positive|stop|bounce|soft_bounce
    # ── AI Reply Classifier columns (Phase 2 — v8_0_0_ai_reply_columns.sql) ─────
    reply_category: Mapped[str | None] = mapped_column(String(30), nullable=True)   # fine-grained category
    reply_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)     # 0.0-1.0
    reply_source: Mapped[str | None] = mapped_column(String(20), nullable=True)      # dsn|rules|llm_fast|...
    reply_reasoning: Mapped[str | None] = mapped_column(String(255), nullable=True)  # short explanation
    intent_score: Mapped[int | None] = mapped_column(Integer, nullable=True)         # 0-100 buying intent
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # operator review flag
    bounce_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)    # soft-bounce counter

    # ── Niche Classification (Batches 1-3) ──────────────────────────────────────
    # Assigned via niche_router.classify_lead_niche(); 1-26 per templates_all.json.
    # None means unclassified → review queue, do NOT send.
    niche_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    niche_keyword: Mapped[str | None] = mapped_column(String(120), nullable=True)  # matched keyword
    niche_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 1-3 score
    niche_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # human-set; skip re-classify

    # ── Sequence / Touch Tracking (guide section 7.5) ───────────────────────────
    sequence_touch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sequence_touch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sequence_paused_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # out-of-office pause
    has_received_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)   # Segment 10 once-only
    is_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)  # unsubscribe|complaint|bounce

    # ── Provenance & Identity Association ───────────────────────────────────────

    email_source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email_extraction_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email_domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    website_domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email_domain_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    email_business_association_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="unverified_association"
    )
    email_association_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_association_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="unverified"
    )
    website_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    email_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Email Verification Engine ───────────────────────────────────────────────
    email_verification_status: Mapped[str] = mapped_column(
        String(50), default="unverified", nullable=False, index=True
    )
    email_verification_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    # V6.1 lifecycle is additive. Legacy consumers still rely on `status=done`.
    audit_lifecycle: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # ── Geo-smart currency detection (set during audit, used for localised pricing) ──
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)   # e.g. 'GB', 'US', 'AU'
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)  # e.g. 'GBP', 'USD'
    currency_symbol: Mapped[str | None] = mapped_column(String(10), nullable=True) # e.g. '£', '$'
    detected_via: Mapped[str | None] = mapped_column(String(50), nullable=True)   # 'phone'|'address'|'tld'|'fallback'

    lead: Mapped["Lead"] = relationship("Lead", back_populates="audit")


class AuditBatchSession(Base):
    """Durable state for a batch audit, including restart-resume metadata."""
    __tablename__ = "audit_batch_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    remaining_lead_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    in_flight_lead_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    delay_secs: Mapped[float] = mapped_column(nullable=False, default=1.5)
    interruption_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    interrupted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_ids: Mapped[list] = mapped_column(JSON, default=list)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    subject_template: Mapped[str] = mapped_column(String(500), default="")
    campaign_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default="generic_first_contact")
    # Per-lead evidence snapshots for canonical audit-generated content.  Kept
    # separate from editable template text so a reviewed draft can fail closed
    # if its underlying audit changes before the worker sends it.
    audit_references: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict, deferred=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    email_logs: Mapped[list["CampaignEmailLog"]] = relationship(
        "CampaignEmailLog", back_populates="campaign",
        order_by="CampaignEmailLog.created_at.desc()", passive_deletes=True
    )


@event.listens_for(Campaign, "load")
def _receive_campaign_load(target, context):
    if "audit_references" not in target.__dict__ or target.__dict__.get("audit_references") is None:
        target.__dict__["audit_references"] = {}


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lead: Mapped["Lead"] = relationship("Lead")


class ServiceProposal(Base):
    """
    Persistent relational storage for service proposal drafts and human approval decisions.
    Created by migration v6_2_5_proposal_approval_persistence.sql.
    Serves as the single authoritative source of truth across application restarts and workers.
    """
    __tablename__ = "service_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audits.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft_preview", nullable=False, index=True
    )
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_content: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    lead: Mapped["Lead"] = relationship("Lead")
    audit: Mapped["Audit | None"] = relationship("Audit")


# ─── Global Suppression List ─────────────────────────────────────────────────
# Guide section 7.2: suppression is global and permanent across niches/campaigns.
# Check at queue time AND at send time.

class SuppressionList(Base):
    """
    Global, permanent opt-out list.
    Any email address here must never receive another campaign email.
    Sources: one-click unsubscribe, inbound opt-out reply, hard bounce, complaint.
    """
    __tablename__ = "suppression_list"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unsubscribe"
        # unsubscribe | complaint | hard_bounce | manual
    )
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. "inbound_reply", "one_click"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


# ─── NUL Character Sanitization Safeguard ──────────────────────────────────────
# PostgreSQL rejects NUL bytes (\x00 / \u0000) in text, varchar, and json columns.
# Web scrapers can pick up binary/null bytes from malformed HTML or obfuscated JS.
# This listener ensures all Lead and Audit inserts and updates are automatically sanitized.

def _sanitize_null_bytes(val):
    if isinstance(val, str):
        return val.replace("\x00", "").replace("\u0000", "")
    elif isinstance(val, dict):
        return {_sanitize_null_bytes(k): _sanitize_null_bytes(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_sanitize_null_bytes(v) for v in val]
    return val


@event.listens_for(Mapper, "before_insert")
@event.listens_for(Mapper, "before_update")
def _strip_null_bytes_listener(mapper, connection, target):
    for col in mapper.column_attrs:
        val = getattr(target, col.key, None)
        if isinstance(val, str) and ("\x00" in val or "\u0000" in val):
            setattr(target, col.key, val.replace("\x00", "").replace("\u0000", ""))
        elif isinstance(val, (dict, list)):
            setattr(target, col.key, _sanitize_null_bytes(val))


