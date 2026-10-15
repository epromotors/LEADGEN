-- Phase 5 Domain C: Add persistent encrypted Google Search Console credentials table.
-- Stored tokens must be authenticated-encrypted (Fernet AES-128-CBC + HMAC) and never stored in plaintext.
CREATE TABLE IF NOT EXISTS gsc_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_key VARCHAR(255) NOT NULL UNIQUE,
    encrypted_tokens TEXT NOT NULL,
    scope VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_gsc_credentials_property_key ON gsc_credentials(property_key);
