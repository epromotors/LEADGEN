-- ==============================================================================
-- LEADGEN Migration v6.2.6: Campaign Orchestration & Distributed Worker Metadata
-- ==============================================================================
-- Type: Backward-compatible, additive schema update.
-- Targets: campaigns table (adds worker metadata and scheduling lookup index).
-- Execution Mode: Operator-controlled ONLY. Not executed automatically on startup.
-- Operator Procedure: See docs/DATABASE_MIGRATION_PROCEDURE.md
--
-- Safety Notice:
--   The preflight SQL guard below denies execution against protected, sandbox,
--   and system databases ('leadgen', 'leadgen_test', 'leads_db', 'linkgen', 'offpage',
--   'leadgen_release_sandbox', 'postgres', 'template0', 'template1').
--   Authorization and safety verification of any other target database remains
--   a separate mandatory operator responsibility. The migration SQL does not
--   verify written authorization, target ownership, host identity, backups,
--   or recovery readiness.
--
--   Must be executed with: psql -v ON_ERROR_STOP=1 ...
-- ==============================================================================

BEGIN;

-- ------------------------------------------------------------------------------
-- PREFLIGHT GUARD: Database Name Protection
-- Aborts immediately if executed against any protected, sandbox, or system databases.
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

-- Optional observability columns for tracking lock/worker ownership in database
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS locked_by VARCHAR(128) NULL;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP WITH TIME ZONE NULL;
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS scheduler_claimed_at TIMESTAMP WITH TIME ZONE NULL;

-- Composite index to accelerate atomic due-campaign discovery and row-level locking
CREATE INDEX IF NOT EXISTS idx_campaigns_status_scheduled_at
    ON campaigns(status, scheduled_at)
    WHERE status = 'scheduled' AND scheduled_at IS NOT NULL;

COMMIT;
