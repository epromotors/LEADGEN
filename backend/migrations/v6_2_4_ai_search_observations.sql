-- LEADGEN Migration v6.2.4: AI Search Visibility Observations
-- Backward-compatible, additive schema update for dated AI visibility tracking.
-- Targets: ai_search_observations table.
-- Execution Mode: Operator-controlled ONLY. Not executed automatically on startup.
-- Operator Procedure: See docs/DATABASE_MIGRATION_PROCEDURE.md

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
        'postgres', 'template0', 'template1'
    ) THEN
        RAISE EXCEPTION 'MIGRATION ABORTED: Target database "%" is in the protected database list and cannot be modified.', current_database();
    END IF;
END $$;

-- ------------------------------------------------------------------------------
-- SCHEMA STATEMENTS: Additive & Idempotent
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai_search_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NULL REFERENCES leads(id) ON DELETE SET NULL,
    target_domain VARCHAR(255) NOT NULL,
    brand_name VARCHAR(255) NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'manual',
    provider VARCHAR(100) NOT NULL,
    engine VARCHAR(100) NOT NULL,
    search_query TEXT NOT NULL,
    locale VARCHAR(50) NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    mention_status VARCHAR(50) NOT NULL DEFAULT 'unknown',
    citation_urls JSONB NOT NULL DEFAULT '[]',
    evidence_snippet TEXT NULL,
    notes TEXT NULL,
    created_by VARCHAR(100) NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_search_obs_lead_id ON ai_search_observations(lead_id);
CREATE INDEX IF NOT EXISTS idx_ai_search_obs_target_domain ON ai_search_observations(target_domain);
CREATE INDEX IF NOT EXISTS idx_ai_search_obs_source_type ON ai_search_observations(source_type);
CREATE INDEX IF NOT EXISTS idx_ai_search_obs_observed_at ON ai_search_observations(observed_at);

COMMIT;
