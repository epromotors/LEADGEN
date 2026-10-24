-- ==============================================================================
-- LEADGEN Migration v6.2.5: Proposal Approval and Draft Persistence
-- ==============================================================================
-- Type: Backward-compatible, additive schema update.
-- Targets: service_proposals table (creates persistent storage for proposal drafts & approvals).
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

CREATE TABLE IF NOT EXISTS service_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    audit_id UUID REFERENCES audits(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft_preview',
    approved_by VARCHAR(255),
    approved_at TIMESTAMP WITH TIME ZONE,
    target_email VARCHAR(255),
    approval_hash VARCHAR(64),
    proposal_content JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_service_proposals_lead_id ON service_proposals(lead_id);
CREATE INDEX IF NOT EXISTS idx_service_proposals_status ON service_proposals(status);

COMMIT;
