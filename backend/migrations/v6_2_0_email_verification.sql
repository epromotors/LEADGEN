-- LEADGEN Migration v6.2.0: Email Verification Engine & Lead Quarantine
-- Backward-compatible, additive schema update.
-- Targets: leads table.
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

ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_verification_details JSONB NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_quarantined BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS quarantine_reason TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_email_verification_status ON leads(email_verification_status);
CREATE INDEX IF NOT EXISTS idx_leads_is_quarantined ON leads(is_quarantined);

COMMIT;
