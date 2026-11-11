-- Migration: v7_0_0_niche_classification_and_suppression.sql
-- Implements: Batches 1-3 niche routing, sequence tracking, suppression list
-- Guide reference: AGENT_GUIDE_all_batches.md sections 3, 4, 7.2, 7.5
-- All new columns are nullable / have defaults → safe to apply without downtime.

BEGIN;

-- ------------------------------------------------------------------------------
-- PREFLIGHT GUARD: Database Name Protection
-- Aborts immediately if executed against any protected, sandbox, or system databases.
-- Authorization of non-protected targets remains an operator responsibility.
-- ------------------------------------------------------------------------------
DO $$
BEGIN
    IF current_database() IN (
        'leadgen', 'leadgen_test', 'leads_db', 'linkgen', 'offpage',
        'leadgen_release_sandbox',
        'postgres', 'template0', 'template1'
    ) THEN
        RAISE EXCEPTION 'MIGRATION ABORTED: Target database "%" is in the protected database list and cannot be modified.', current_database();
    END IF;
END $$;

-- ─── 1. Niche classification columns on leads ─────────────────────────────────
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS niche_id            INTEGER        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS niche_keyword       VARCHAR(120)   DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS niche_confidence    INTEGER        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS niche_locked        BOOLEAN        NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_leads_niche_id ON leads (niche_id);

COMMENT ON COLUMN leads.niche_id IS
    'Niche ID 1-26 from templates_all.json. NULL = unclassified (review queue, do not send).';
COMMENT ON COLUMN leads.niche_keyword IS
    'Keyword that triggered the niche match (stored for audit trail).';
COMMENT ON COLUMN leads.niche_confidence IS
    'Confidence score 1-3: 3=high (long/rare keyword), 2=medium, 1=low (do not send).';
COMMENT ON COLUMN leads.niche_locked IS
    'When TRUE, human has manually set the niche; skip auto re-classification.';

-- ─── 2. Sequence / touch tracking columns on leads ───────────────────────────
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS sequence_touch_count     INTEGER   NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_sequence_touch_at   TIMESTAMP DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS sequence_paused_until    TIMESTAMP DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS has_received_demo        BOOLEAN   NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_suppressed            BOOLEAN   NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suppressed_at            TIMESTAMP DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS suppression_reason       VARCHAR(100) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS ix_leads_is_suppressed ON leads (is_suppressed);

COMMENT ON COLUMN leads.sequence_touch_count IS
    'Number of outreach touches sent in the current 90-day window (max 3).';
COMMENT ON COLUMN leads.last_sequence_touch_at IS
    'Timestamp of the last outreach email sent to this lead.';
COMMENT ON COLUMN leads.sequence_paused_until IS
    'For out-of-office replies: resume sequence after this date. Not counted as a touch.';
COMMENT ON COLUMN leads.has_received_demo IS
    'TRUE once Segment 10 (public-provider demo) has been sent. Never send Segment 10 again.';
COMMENT ON COLUMN leads.is_suppressed IS
    'TRUE = globally suppressed. Never send any email to this address.';
COMMENT ON COLUMN leads.suppressed_at IS
    'When the suppression was recorded.';
COMMENT ON COLUMN leads.suppression_reason IS
    'unsubscribe | complaint | hard_bounce | manual — why this address is suppressed.';

-- ─── 3. Global suppression list table ────────────────────────────────────────
-- Guide section 7.2: suppression is global and permanent.
-- Cross-check at queue time AND at send time.
CREATE TABLE IF NOT EXISTS suppression_list (
    id          UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    reason      VARCHAR(50)  NOT NULL DEFAULT 'unsubscribe',
    source      VARCHAR(100) DEFAULT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_suppression_list_email ON suppression_list (LOWER(email));

COMMENT ON TABLE suppression_list IS
    'Global permanent opt-out list. Checked at queue time AND at send time.';
COMMENT ON COLUMN suppression_list.reason IS
    'unsubscribe | complaint | hard_bounce | manual';
COMMENT ON COLUMN suppression_list.source IS
    'Where the suppression came from: inbound_reply | one_click | bounce_webhook | manual';

COMMIT;
