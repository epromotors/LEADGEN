-- =============================================================================
-- LeadGen OS v5.0.0 — Additive DB Migration
-- All columns: NULLABLE — safe to run on existing database
-- Run against your PostgreSQL audits table
-- =============================================================================

-- ── Technical Extended (Group B v5.0) ─────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_https_redirect   BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS redirect_chain_ok    BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_mixed_content    BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS www_canonical_ok     BOOLEAN DEFAULT NULL;

-- ── Onpage Extended (Group B v5.0) ────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_noindex          BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS heading_hierarchy_ok BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS internal_links_count INTEGER DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS anchor_text_ok       BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS image_filenames_ok   BOOLEAN DEFAULT NULL;

-- ── UX Extended (Group B v5.0) ────────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_phone_number     BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_address          BOOLEAN DEFAULT NULL;

-- ── Indexability (Group C v5.0) ───────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS url_structure_ok     BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS www_nonwww_ok        BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS soft_404_ok          BOOLEAN DEFAULT NULL;

-- ── Content Quality (Group D v5.0) ────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS word_count           INTEGER DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS duplicate_meta_ok    BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS keyword_in_title_ok  BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS reading_level_ok     BOOLEAN DEFAULT NULL;

-- ── Local SEO (Group E v5.0) ──────────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_nap                   BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_local_business_schema BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_google_maps           BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS city_in_title_ok          BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_business_hours        BOOLEAN DEFAULT NULL;

-- ── Performance (Group F v5.0) ────────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS response_time_ms     INTEGER DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS page_size_ok         BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS render_blocking_ok   BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS gzip_enabled         BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS webp_coverage_ok     BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS minification_ok      BOOLEAN DEFAULT NULL;

-- ── Schema Advanced (Group G v5.0) ────────────────────────────────────────
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_faq_schema        BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_product_schema    BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_breadcrumb_schema BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_review_schema     BOOLEAN DEFAULT NULL;
ALTER TABLE audits ADD COLUMN IF NOT EXISTS schema_graph_ok       BOOLEAN DEFAULT NULL;

-- =============================================================================
-- End of v5.0.0 migration
-- Total new columns: 47
-- All existing data preserved — NULL means "not yet audited with v5.0"
-- =============================================================================
