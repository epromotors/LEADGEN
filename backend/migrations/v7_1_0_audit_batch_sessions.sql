-- LEADGEN Migration v7.1.0: Durable Audit Batch Sessions
-- Backward-compatible, additive schema update.
-- Targets: new audit_batch_sessions table.
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
--   Example (illustrative only; do not run before authorization & verification):
--     psql -v ON_ERROR_STOP=1 -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -f backend/migrations/v7_1_0_audit_batch_sessions.sql
-- ==============================================================================

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
        'leadgen_release_sandbox', 'postgres', 'template0', 'template1'
    ) THEN
        RAISE EXCEPTION 'MIGRATION ABORTED: Target database "%" is in the protected database list and cannot be modified.', current_database();
    END IF;
END $$;

-- ------------------------------------------------------------------------------
-- SCHEMA STATEMENTS: Additive & Idempotent
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_batch_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    mode VARCHAR(32) NOT NULL,
    remaining_lead_ids JSON NOT NULL DEFAULT '[]'::json,
    in_flight_lead_ids JSON NOT NULL DEFAULT '[]'::json,
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    concurrency INTEGER NOT NULL DEFAULT 3,
    delay_secs DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    interruption_reason TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    interrupted_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_audit_batch_sessions_status
    ON audit_batch_sessions (status);

COMMIT;
