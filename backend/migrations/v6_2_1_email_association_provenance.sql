-- LEADGEN Migration v6.2.1: Email & Website Provenance and Association Status
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

ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source_url VARCHAR(500) NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source_type VARCHAR(50) NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_extraction_method VARCHAR(50) NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_domain VARCHAR(100) NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_domain VARCHAR(100) NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_domain_match BOOLEAN NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_business_association_status VARCHAR(50) NULL DEFAULT 'unverified_association';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_association_reason TEXT NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_association_status VARCHAR(50) NULL DEFAULT 'unverified';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_candidates JSONB NULL;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_candidates JSONB NULL;

CREATE INDEX IF NOT EXISTS idx_leads_email_assoc_status ON leads(email_business_association_status);
CREATE INDEX IF NOT EXISTS idx_leads_website_assoc_status ON leads(website_association_status);

COMMIT;
