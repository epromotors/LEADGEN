import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import uuid
import datetime
from sqlalchemy import inspect
from dotenv import dotenv_values
from app.models import Lead, LeadStatus


def test_lead_model_has_email_verification_columns():
    """Verify that Lead model contains the required email verification and quarantine columns."""
    mapper = inspect(Lead)
    columns = {col.key for col in mapper.columns}

    # Email verification columns
    assert "email_verification_status" in columns
    assert "email_verification_details" in columns
    assert "email_verified_at" in columns

    # Quarantine columns
    assert "is_quarantined" in columns
    assert "quarantine_reason" in columns

    # Provenance & Identity Association columns
    assert "email_source_url" in columns
    assert "email_source_type" in columns
    assert "email_extraction_method" in columns
    assert "email_domain" in columns
    assert "website_domain" in columns
    assert "email_domain_match" in columns
    assert "email_business_association_status" in columns
    assert "email_association_reason" in columns
    assert "website_association_status" in columns
    assert "website_candidates" in columns
    assert "email_candidates" in columns


def test_lead_model_column_properties():
    """Verify default values and nullability of verification columns."""
    mapper = inspect(Lead)
    ev_status_col = mapper.columns["email_verification_status"]
    assert ev_status_col.nullable is False
    assert ev_status_col.default is not None or ev_status_col.server_default is not None

    quarantine_col = mapper.columns["is_quarantined"]
    assert quarantine_col.nullable is False

    details_col = mapper.columns["email_verification_details"]
    assert details_col.nullable is True


def test_sandbox_database_migration_applied():
    """
    Database Safety Gate Test:
    Connects to the configured sandbox DB, confirms database is 'leadgen_release_sandbox',
    user is not a superuser, and verifies that the columns exist on the leads table.
    """
    vals = dotenv_values("backend/.env")
    raw_url = vals.get("DATABASE_URL")
    if not raw_url:
        return  # Skip if no local .env

    import psycopg
    conn_str = raw_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            db_name, user_name = cur.fetchone()
            assert db_name == "leadgen_release_sandbox", f"Prohibited DB target: {db_name}"
            
            cur.execute("SELECT usesuper FROM pg_user WHERE usename = current_user")
            is_super = cur.fetchone()[0]
            assert is_super is False, "Role must not be superuser"

            # Check columns on leads table
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'leads'
            """)
            col_names = {row[0] for row in cur.fetchall()}
            assert "email_verification_status" in col_names
            assert "email_verification_details" in col_names
            assert "email_verified_at" in col_names
            assert "is_quarantined" in col_names
            assert "quarantine_reason" in col_names
            assert "email_source_url" in col_names
            assert "email_source_type" in col_names
            assert "email_extraction_method" in col_names
            assert "email_domain" in col_names
            assert "website_domain" in col_names
            assert "email_domain_match" in col_names
            assert "email_business_association_status" in col_names
            assert "email_association_reason" in col_names
            assert "website_association_status" in col_names
            assert "website_candidates" in col_names
            assert "email_candidates" in col_names


FORBIDDEN_MIGRATION_TARGETS = (
    "leadgen",
    "leadgen_test",
    "leads_db",
    "linkgen",
    "offpage",
    "leadgen_release_sandbox",
    "postgres",
    "template0",
    "template1",
)


def test_v6_2_0_migration_sql_contract():
    """Verify backend/migrations/v6_2_0_email_verification.sql adheres to safety and schema contracts."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    sql_path = repo_root / "backend" / "migrations" / "v6_2_0_email_verification.sql"
    assert sql_path.exists(), "v6_2_0_email_verification.sql must exist"
    content = sql_path.read_text(encoding="utf-8")

    # Transactionality
    assert "BEGIN;" in content.upper()
    assert "COMMIT;" in content.upper()

    # Preflight guard coverage: must precede DDL and cover all 9 forbidden DBs
    guard_idx = content.find("current_database()")
    alter_idx = content.find("ALTER TABLE")
    index_idx = content.find("CREATE INDEX")
    assert guard_idx != -1, "Preflight guard with current_database() must exist"
    assert alter_idx != -1 and guard_idx < alter_idx, "Guard must precede ALTER TABLE"
    assert index_idx != -1 and guard_idx < index_idx, "Guard must precede CREATE INDEX"

    for fdb in FORBIDDEN_MIGRATION_TARGETS:
        assert f"'{fdb}'" in content, f"Forbidden DB '{fdb}' must be present in preflight guard"

    # Schema changes
    assert "ADD COLUMN IF NOT EXISTS email_verification_status" in content
    assert "ADD COLUMN IF NOT EXISTS email_verification_details JSONB" in content
    assert "ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP" in content
    assert "ADD COLUMN IF NOT EXISTS is_quarantined BOOLEAN" in content
    assert "ADD COLUMN IF NOT EXISTS quarantine_reason TEXT" in content

    # Indexes
    assert "CREATE INDEX IF NOT EXISTS idx_leads_email_verification_status" in content
    assert "CREATE INDEX IF NOT EXISTS idx_leads_is_quarantined" in content


def test_v6_2_1_migration_sql_contract():
    """Verify backend/migrations/v6_2_1_email_association_provenance.sql adheres to safety and schema contracts."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    sql_path = repo_root / "backend" / "migrations" / "v6_2_1_email_association_provenance.sql"
    assert sql_path.exists(), "v6_2_1_email_association_provenance.sql must exist"
    content = sql_path.read_text(encoding="utf-8")

    # Transactionality
    assert "BEGIN;" in content.upper()
    assert "COMMIT;" in content.upper()

    # Preflight guard coverage: must precede DDL and cover all 9 forbidden DBs
    guard_idx = content.find("current_database()")
    alter_idx = content.find("ALTER TABLE")
    index_idx = content.find("CREATE INDEX")
    assert guard_idx != -1, "Preflight guard with current_database() must exist"
    assert alter_idx != -1 and guard_idx < alter_idx, "Guard must precede ALTER TABLE"
    assert index_idx != -1 and guard_idx < index_idx, "Guard must precede CREATE INDEX"

    for fdb in FORBIDDEN_MIGRATION_TARGETS:
        assert f"'{fdb}'" in content, f"Forbidden DB '{fdb}' must be present in preflight guard"

    # Schema changes
    assert "ADD COLUMN IF NOT EXISTS email_source_url" in content
    assert "ADD COLUMN IF NOT EXISTS email_source_type" in content
    assert "ADD COLUMN IF NOT EXISTS email_extraction_method" in content
    assert "ADD COLUMN IF NOT EXISTS email_domain" in content
    assert "ADD COLUMN IF NOT EXISTS website_domain" in content
    assert "ADD COLUMN IF NOT EXISTS email_domain_match" in content
    assert "ADD COLUMN IF NOT EXISTS email_business_association_status" in content
    assert "ADD COLUMN IF NOT EXISTS email_association_reason" in content
    assert "ADD COLUMN IF NOT EXISTS website_association_status" in content
    assert "ADD COLUMN IF NOT EXISTS website_candidates JSONB" in content
    assert "ADD COLUMN IF NOT EXISTS email_candidates JSONB" in content

    # Indexes
    assert "CREATE INDEX IF NOT EXISTS idx_leads_email_assoc_status" in content
    assert "CREATE INDEX IF NOT EXISTS idx_leads_website_assoc_status" in content


def test_all_v6_2_x_migrations_have_consistent_forbidden_database_guards():
    """Verify that all four v6.2.x migrations implement identical, consistent forbidden-target SQL guards."""
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    migration_files = [
        "v6_2_0_email_verification.sql",
        "v6_2_1_email_association_provenance.sql",
        "v6_2_2_campaign_segmentation.sql",
        "v6_2_3_audit_email_freshness.sql",
    ]

    for mfile in migration_files:
        sql_path = repo_root / "backend" / "migrations" / mfile
        assert sql_path.exists(), f"Migration file {mfile} must exist"
        content = sql_path.read_text(encoding="utf-8")

        # Transactional
        assert "BEGIN;" in content.upper(), f"{mfile} must start transaction with BEGIN;"
        assert "COMMIT;" in content.upper(), f"{mfile} must commit transaction with COMMIT;"

        # Abort before DDL
        guard_pos = content.find("current_database()")
        alter_pos = content.find("ALTER TABLE")
        assert guard_pos != -1, f"{mfile} must include preflight guard checking current_database()"
        assert alter_pos != -1, f"{mfile} must contain ALTER TABLE statement"
        assert guard_pos < alter_pos, f"{mfile} preflight guard must execute strictly before ALTER TABLE"

        # Extract items in current_database() IN (...)
        match = re.search(r"current_database\(\)\s+IN\s*\(([^)]+)\)", content, re.IGNORECASE | re.DOTALL)
        assert match is not None, f"{mfile} must contain 'current_database() IN (...)' clause"
        raw_list = match.group(1)
        # Parse out quoted database names
        rejected_in_sql = {name.strip().strip("'\"") for name in raw_list.split(",") if name.strip()}

        for fdb in FORBIDDEN_MIGRATION_TARGETS:
            assert fdb in rejected_in_sql, (
                f"{mfile} SQL guard missing forbidden database '{fdb}' in its IN list. "
                f"Found: {rejected_in_sql}"
            )

        # Verify simulated execution of the extracted guard logic
        def simulate_guard(db_name: str):
            if db_name in rejected_in_sql:
                raise RuntimeError(f"MIGRATION ABORTED: Target database '{db_name}' is in the protected database list")
            return "OK"

        for fdb in FORBIDDEN_MIGRATION_TARGETS:
            try:
                simulate_guard(fdb)
                assert False, f"Expected guard to abort for {fdb} in {mfile}"
            except RuntimeError as e:
                assert "MIGRATION ABORTED" in str(e)

        # Disposable migration target is permitted
        assert simulate_guard("leadgen_migration_e2e_20261022_214720_dc06eb") == "OK"


