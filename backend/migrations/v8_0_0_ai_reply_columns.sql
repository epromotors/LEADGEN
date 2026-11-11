-- Migration: v8_0_0_ai_reply_columns.sql
-- Implements: AI reply classifier support columns on leads table
-- Ref: feature/ai-reply-classifier — Phase 2
-- All new columns are nullable or have safe defaults → zero-downtime, fully reversible.
-- REPLY_AI_MODE=off (default) means zero code paths reach these columns until Phase 3+.

BEGIN;

-- ------------------------------------------------------------------------------
-- PREFLIGHT GUARD: Database Name Protection
-- Pattern identical to all prior migrations in this project.
-- To apply this migration to leadgen_release_sandbox intentionally, run:
--
--   psql "postgresql://leadgen_release_app:<pw>@localhost:5432/leadgen_release_sandbox" \
--     -v ON_ERROR_STOP=1 \
--     -c "SET session_replication_role = replica;" \
--     -f backend/migrations/v8_0_0_ai_reply_columns.sql
--
-- OR: temporarily comment-out 'leadgen_release_sandbox' from the list below,
-- apply, then restore the file (do NOT commit the modified guard).
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

-- ─── AI Reply Classifier columns on leads ─────────────────────────────────────
-- reply_category: fine-grained classifier category (hot_interest, question, etc.)
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS reply_category     VARCHAR(30)   DEFAULT NULL;

-- reply_confidence: 0.0-1.0 classifier confidence from chosen source
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS reply_confidence   FLOAT         DEFAULT NULL;

-- reply_source: which layer produced the classification (dsn|rules|llm_fast|llm_strong|fallback)
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS reply_source       VARCHAR(20)   DEFAULT NULL;

-- reply_reasoning: <=200 char human-readable reasoning from classifier
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS reply_reasoning    VARCHAR(255)  DEFAULT NULL;

-- intent_score: 0-100 buying intent (LLM only, 0 for rule/DSN sources)
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS intent_score       INTEGER       DEFAULT NULL;

-- needs_review: flagged for the "Needs Review" operator tab; blocks automated outreach
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS needs_review       BOOLEAN       NOT NULL DEFAULT FALSE;

-- bounce_count: incremented each soft-bounce; at 3 → treated as hard bounce
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS bounce_count       INTEGER       NOT NULL DEFAULT 0;

-- Index for the Needs Review tab query (WHERE needs_review = TRUE)
CREATE INDEX IF NOT EXISTS ix_leads_needs_review ON leads (needs_review)
    WHERE needs_review = TRUE;

COMMENT ON COLUMN leads.reply_category IS
    'Fine-grained AI category: hot_interest|question|referral|not_now|out_of_office|auto_reply|soft_bounce|hard_bounce|unsubscribe|not_interested|complaint|wrong_person|other';
COMMENT ON COLUMN leads.reply_confidence IS
    'Classifier confidence 0.0–1.0. Purge only allowed when >= 0.85 AND source IN (dsn, rules).';
COMMENT ON COLUMN leads.reply_source IS
    'Which pipeline layer classified: dsn|headers|rules|llm_fast|llm_strong|fallback';
COMMENT ON COLUMN leads.reply_reasoning IS
    'Short reasoning string from classifier (<=200 chars). Shown in Needs Review UI.';
COMMENT ON COLUMN leads.intent_score IS
    'Buying intent 0-100 (LLM only). NULL for DSN/rules/fallback sources.';
COMMENT ON COLUMN leads.needs_review IS
    'TRUE = operator must review before next outreach. Set by classifier or manually.';
COMMENT ON COLUMN leads.bounce_count IS
    'Soft-bounce counter. Resets to 0 on successful delivery. At 3 → escalate to hard.';

COMMIT;
