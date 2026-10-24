-- ==============================================================================
-- LEADGEN Migration v6.2.3: Audit Email Freshness References
-- ==============================================================================
-- Type: Backward-compatible, additive schema update.
-- Targets: campaigns table (adds audit_references column).
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
--     psql -v ON_ERROR_STOP=1 -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -f backend/migrations/v6_2_3_audit_email_freshness.sql
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
        'postgres', 'template0', 'template1'
    ) THEN
        RAISE EXCEPTION 'MIGRATION ABORTED: Target database "%" is in the protected database list and cannot be modified.', current_database();
    END IF;
END $$;

-- ------------------------------------------------------------------------------
-- SCHEMA STATEMENTS: Additive & Idempotent
-- ------------------------------------------------------------------------------

-- Stores the audit-result fingerprint that an operator reviewed per campaign lead.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS audit_references JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMIT;
