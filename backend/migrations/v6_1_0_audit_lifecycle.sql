-- Phase 1 V6.1: additive, backward-compatible lifecycle persistence.
-- `audits.status` remains the legacy enum for current API and campaign consumers.
ALTER TABLE audits ADD COLUMN IF NOT EXISTS audit_lifecycle VARCHAR(20) NOT NULL DEFAULT 'PENDING';

UPDATE audits
SET audit_lifecycle = CASE status::text
    WHEN 'pending' THEN 'PENDING'
    WHEN 'running' THEN 'RUNNING'
    WHEN 'done' THEN 'COMPLETE'
    WHEN 'failed' THEN 'FAILED'
    ELSE NULL
END
WHERE audit_lifecycle IS NULL;
