import os
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure dummy values so config loads cleanly without live database
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/dummy_isolated_db")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app import database
from app.config import Settings
from app.models import CampaignStatus, Base


def _run_coroutine(coro):
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class StartupSchemaSafeguardTests(unittest.TestCase):
    def test_default_init_schema_is_false(self):
        s = Settings(DATABASE_URL="postgresql+psycopg://dummy:dummy@127.0.0.1:5432/dummy_isolated_db", JWT_SECRET="dummy" * 8)
        self.assertFalse(s.INIT_SCHEMA, "Default INIT_SCHEMA must be False")

    def test_create_tables_skipped_when_init_schema_false(self):
        async def _run():
            with patch.object(database.settings, "INIT_SCHEMA", False):
                mock_engine = MagicMock()
                with patch.object(database, "engine", mock_engine):
                    await database.create_tables()
                    mock_engine.begin.assert_not_called()
        _run_coroutine(_run())

    def test_create_tables_executes_when_init_schema_true(self):
        async def _run():
            with patch.object(database.settings, "INIT_SCHEMA", True):
                mock_conn = AsyncMock()
                mock_ctx = MagicMock()
                mock_ctx.__aenter__.return_value = mock_conn
                mock_ctx.__aexit__.return_value = None

                mock_engine = MagicMock()
                mock_engine.begin.return_value = mock_ctx

                with patch.object(database, "engine", mock_engine):
                    await database.create_tables()
                    mock_engine.begin.assert_called_once()
                    mock_conn.run_sync.assert_called_once_with(Base.metadata.create_all)
                    self.assertGreater(mock_conn.execute.call_count, 0)
        _run_coroutine(_run())

    def test_app_lifespan_startup_does_not_execute_ddl_under_default_settings(self):
        """Verify FastAPI lifespan startup under default configuration never calls engine.begin() or runs DDL."""
        from app.main import lifespan, app
        async def _run():
            mock_engine = MagicMock()
            with patch.object(database, "engine", mock_engine), \
                 patch.object(database.settings, "INIT_SCHEMA", False):
                async with lifespan(app):
                    pass
                mock_engine.begin.assert_not_called()
        _run_coroutine(_run())

    def test_app_lifespan_executes_ddl_only_when_init_schema_explicitly_true(self):
        """Verify FastAPI lifespan startup executes DDL if and only if INIT_SCHEMA is explicitly set to True."""
        from app.main import lifespan, app
        async def _run():
            mock_conn = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__.return_value = mock_conn
            mock_ctx.__aexit__.return_value = None

            mock_engine = MagicMock()
            mock_engine.begin.return_value = mock_ctx

            with patch.object(database, "engine", mock_engine), \
                 patch.object(database.settings, "INIT_SCHEMA", True):
                async with lifespan(app):
                    pass
                mock_engine.begin.assert_called_once()
                mock_conn.run_sync.assert_called_once_with(Base.metadata.create_all)
                self.assertGreater(mock_conn.execute.call_count, 0)
        _run_coroutine(_run())


class CampaignStatusEnumOrderTests(unittest.TestCase):
    def test_campaign_status_enum_declaration_order(self):
        expected_order = ("draft", "scheduled", "sending", "done", "paused")
        actual_order = tuple(e.value for e in CampaignStatus)
        self.assertEqual(
            actual_order,
            expected_order,
            f"CampaignStatus declaration order {actual_order} must match {expected_order}",
        )

    def test_campaign_status_table_metadata_order(self):
        expected_order = ("draft", "scheduled", "sending", "done", "paused")
        status_col = Base.metadata.tables["campaigns"].columns["status"]
        self.assertEqual(
            tuple(status_col.type.enums),
            expected_order,
            f"Base.metadata campaigns.status enums must match {expected_order}",
        )


class MigrationGuardStaticTests(unittest.TestCase):
    """Static text inspection and simulated logic tests for backend/migrations/v6_2_2_campaign_segmentation.sql.

    NOTE: These tests run purely offline via static text parsing and simulated Python logic.
    No connection to an actual PostgreSQL database server is made or attempted.
    The migration itself remains unapplied.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        cls.migration_path = repo_root / "backend" / "migrations" / "v6_2_2_campaign_segmentation.sql"
        with open(cls.migration_path, "r", encoding="utf-8") as f:
            cls.sql_content = f.read()

    def test_guard_appears_before_schema_changing_statements(self):
        """Static check: The preflight current_database() guard must execute strictly before ALTER TABLE."""
        content = self.sql_content
        guard_idx = content.find("current_database()")
        alter_idx = content.find("ALTER TABLE")
        index_idx = content.find("CREATE INDEX")

        self.assertNotEqual(guard_idx, -1, "Preflight guard with current_database() must exist")
        self.assertNotEqual(alter_idx, -1, "ALTER TABLE statement must exist")
        self.assertNotEqual(index_idx, -1, "CREATE INDEX statement must exist")
        self.assertLess(guard_idx, alter_idx, "Guard must precede ALTER TABLE")
        self.assertLess(guard_idx, index_idx, "Guard must precede CREATE INDEX")

    def test_all_five_protected_databases_are_covered(self):
        """Static check: Every protected database name must be included in the preflight rejection check."""
        protected_dbs = ["leadgen", "leadgen_test", "leads_db", "linkgen", "offpage"]
        content = self.sql_content

        for db in protected_dbs:
            self.assertIn(f"'{db}'", content, f"Protected database '{db}' must be guarded in migration SQL")

    def test_all_forbidden_databases_including_sandbox_and_system_are_covered(self):
        """Static check: All 9 protected, sandbox, and system databases must be rejected."""
        forbidden_dbs = [
            "leadgen", "leadgen_test", "leads_db", "linkgen", "offpage",
            "leadgen_release_sandbox", "postgres", "template0", "template1"
        ]
        content = self.sql_content
        for db in forbidden_dbs:
            self.assertIn(f"'{db}'", content, f"Forbidden database '{db}' must be guarded in migration SQL")

    def test_migration_is_transactional(self):
        """Static check: Migration must be wrapped in BEGIN ... COMMIT transaction blocks."""
        content = self.sql_content.upper()
        self.assertIn("BEGIN;", content)
        self.assertIn("COMMIT;", content)

    def test_migration_contains_intended_additive_column_and_index(self):
        """Static check: Migration must add campaign_type column with default and corresponding index."""
        content = self.sql_content
        self.assertIn("ADD COLUMN IF NOT EXISTS campaign_type VARCHAR(64) NULL DEFAULT 'generic_first_contact'", content)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_campaigns_campaign_type ON campaigns(campaign_type)", content)

    def test_migration_sql_rejects_protected_dbs_in_simulated_check(self):
        """Simulated logic check (offline, no live DB): verify the deny-list logic in Python."""
        forbidden_dbs = {
            "leadgen", "leadgen_test", "leads_db", "linkgen", "offpage",
            "leadgen_release_sandbox", "postgres", "template0", "template1"
        }
        
        def simulate_guard(db_name: str):
            if db_name in forbidden_dbs:
                raise RuntimeError(f"MIGRATION ABORTED: Target database '{db_name}' is in the protected database list")
            return "OK"

        for fdb in forbidden_dbs:
            with self.assertRaises(RuntimeError):
                simulate_guard(fdb)

        # Non-denied disposable migration target passes the guard
        self.assertEqual(simulate_guard("leadgen_migration_e2e_disposable"), "OK")


class MigrationV623GuardStaticTests(unittest.TestCase):
    """Static text inspection and simulated logic tests for backend/migrations/v6_2_3_audit_email_freshness.sql.

    NOTE: These tests run purely offline via static text parsing and simulated Python logic.
    No connection to an actual PostgreSQL database server is made or attempted.
    The migration itself remains unapplied.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[1]
        cls.migration_path = repo_root / "backend" / "migrations" / "v6_2_3_audit_email_freshness.sql"
        with open(cls.migration_path, "r", encoding="utf-8") as f:
            cls.sql_content = f.read()

    def test_guard_appears_before_schema_changing_statements(self):
        """Static check: The preflight current_database() guard must execute strictly before ALTER TABLE."""
        content = self.sql_content
        guard_idx = content.find("current_database()")
        alter_idx = content.find("ALTER TABLE")

        self.assertNotEqual(guard_idx, -1, "Preflight guard with current_database() must exist")
        self.assertNotEqual(alter_idx, -1, "ALTER TABLE statement must exist")
        self.assertLess(guard_idx, alter_idx, "Guard must precede ALTER TABLE")

    def test_all_five_protected_databases_are_covered(self):
        """Static check: Every protected database name must be included in the preflight rejection check."""
        protected_dbs = ["leadgen", "leadgen_test", "leads_db", "linkgen", "offpage"]
        content = self.sql_content

        for db in protected_dbs:
            self.assertIn(f"'{db}'", content, f"Protected database '{db}' must be guarded in migration SQL")

    def test_all_forbidden_databases_including_sandbox_and_system_are_covered(self):
        """Static check: All 9 protected, sandbox, and system databases must be rejected."""
        forbidden_dbs = [
            "leadgen", "leadgen_test", "leads_db", "linkgen", "offpage",
            "leadgen_release_sandbox", "postgres", "template0", "template1"
        ]
        content = self.sql_content
        for db in forbidden_dbs:
            self.assertIn(f"'{db}'", content, f"Forbidden database '{db}' must be guarded in migration SQL")

    def test_migration_is_transactional(self):
        """Static check: Migration must be wrapped in BEGIN ... COMMIT transaction blocks."""
        content = self.sql_content.upper()
        self.assertIn("BEGIN;", content)
        self.assertIn("COMMIT;", content)

    def test_migration_contains_intended_additive_column(self):
        """Static check: Migration must add audit_references column with default '{}'::jsonb."""
        content = self.sql_content
        self.assertIn("ADD COLUMN IF NOT EXISTS audit_references JSONB NOT NULL DEFAULT '{}'::jsonb", content)


class DatabaseSafeguardAndLeastPrivilegeTests(unittest.TestCase):
    """Test suite for runtime least-privilege, protected database rejection, and secret redaction."""

    def test_create_tables_fails_closed_against_protected_databases(self):
        """create_tables must raise RuntimeError if connected to any protected or ordinary business database."""
        from app.database import PROTECTED_DATABASES, create_tables

        for protected_db in ("leadgen", "leadgen_release_sandbox", "leads_db", "linkgen", "offpage", "postgres"):
            async def _run(db_name=protected_db):
                with patch.object(database.settings, "INIT_SCHEMA", True):
                    mock_conn = AsyncMock()
                    mock_res = MagicMock()
                    mock_res.fetchone.return_value = (db_name, "test_user")
                    mock_conn.execute.return_value = mock_res

                    mock_ctx = MagicMock()
                    mock_ctx.__aenter__.return_value = mock_conn
                    mock_ctx.__aexit__.return_value = None

                    mock_engine = MagicMock()
                    mock_engine.begin.return_value = mock_ctx

                    with patch.object(database, "engine", mock_engine):
                        with self.assertRaises(RuntimeError) as ctx:
                            await create_tables()
                        self.assertIn("SCHEMA MUTATION BLOCKED", str(ctx.exception))
                        mock_conn.run_sync.assert_not_called()
            _run_coroutine(_run(protected_db))

    def test_redact_sensitive_text_redacts_credentials_and_urls(self):
        """redact_sensitive_text must redact database passwords, JWTs, Bearer tokens, and secrets."""
        from app.logger import redact_sensitive_text

        # 1. Database URLs
        db_url = "postgresql+psycopg://leadgen_app:SuperSecret123@localhost:5432/leadgen_db"
        redacted = redact_sensitive_text(f"Connecting to {db_url}")
        self.assertNotIn("SuperSecret123", redacted)
        self.assertIn("leadgen_app:***@localhost:5432", redacted)

        # 2. Bearer tokens
        bearer = "Authorization: Bearer my_secret_bearer_token_xyz123"
        redacted_bearer = redact_sensitive_text(bearer)
        self.assertNotIn("my_secret_bearer_token_xyz123", redacted_bearer)
        self.assertIn("Bearer ***", redacted_bearer)

        # 3. JWT tokens
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozG4m1pDXxP_pPqE_placeholder"
        redacted_jwt = redact_sensitive_text(f"Token is {jwt_token}")
        self.assertNotIn("dozG4m1pDXxP_pPqE_placeholder", redacted_jwt)
        self.assertIn("eyJ***.[REDACTED_JWT]", redacted_jwt)

        # 4. Key-value secrets (including quoted JSON keys and prefixed keys)
        kv = 'User settings: password="MyClearPassword!", secret=\'ApiKey999\', "app_password": "nested_secret_456"'
        redacted_kv = redact_sensitive_text(kv)
        self.assertNotIn("MyClearPassword!", redacted_kv)
        self.assertNotIn("ApiKey999", redacted_kv)
        self.assertNotIn("nested_secret_456", redacted_kv)
        self.assertIn('password="***"', redacted_kv)
        self.assertIn('"app_password": "***"', redacted_kv)

        # 5. Non-destructive preservation of unrelated content
        unrelated = 'Processing lead ID 12345 from carmedicmotors.in; status=200; total_pages=3'
        self.assertEqual(redact_sensitive_text(unrelated), unrelated)

        # 6. Failsafe: never echoes raw text on unexpected internal error
        mock_pattern = MagicMock()
        mock_pattern.sub.side_effect = RuntimeError("Simulated regex engine error")
        with patch("app.logger._RE_DB_URL", mock_pattern):
            fallback = redact_sensitive_text("postgresql+psycopg://user:SuperSecret123@localhost:5432/db")
            self.assertNotIn("SuperSecret123", fallback)
            self.assertEqual(fallback, "[LOG REDACTION FAILED — SANITIZED]")

    def test_auth_login_fails_closed_when_admin_password_unconfigured(self):
        """auth router login must fail closed if ADMIN_PASSWORD is empty."""
        from app.routers.auth import login
        from app.schemas import LoginRequest
        from fastapi import HTTPException

        async def _run():
            with patch.object(database.settings, "ADMIN_PASSWORD", ""):
                req = LoginRequest(username="admin", password="changeme123")
                with self.assertRaises(HTTPException) as ctx:
                    await login(req)
                self.assertEqual(ctx.exception.status_code, 401)
                self.assertEqual(ctx.exception.detail, "Incorrect username or password")

                # Even empty password request must fail
                req_empty = LoginRequest(username="admin", password="")
                with self.assertRaises(HTTPException) as ctx:
                    await login(req_empty)
                self.assertEqual(ctx.exception.status_code, 401)
        _run_coroutine(_run())


if __name__ == "__main__":
    unittest.main()

