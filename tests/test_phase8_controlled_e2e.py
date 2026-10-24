"""
tests/test_phase8_controlled_e2e.py

Focused unit tests for Phase 8 controlled validation runner and safeguards.
Validates:
1. Missing Phase 8 database configuration fails closed without falling back to application DATABASE_URL.
2. Protected database names ('leadgen', 'leadgen_test', 'leads_db', 'linkgen', 'offpage') are strictly rejected.
3. Ordinary application sandbox ('leadgen_release_sandbox') is strictly rejected.
4. Naming convention 'leadgen_phase8_e2e_<suffix>' is enforced.
5. Existing databases are never overwritten or automatically dropped.
6. Unauthorized or failing admin provisioning fails closed without privilege escalation.
7. Effective live PostgreSQL identity is verified against expected target and role.
8. Blocked preflight does not execute audit mutations, send email, or report fake success.
9. Runner records partial progress and explicit stage status upon failure.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure dummy values so config loads cleanly without live database
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://leadgen_release_app:dummy@localhost:5432/leadgen_phase8_e2e_dummy")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from scripts.validate_phase8_controlled_e2e import (
    PROTECTED_DATABASES,
    DISALLOWED_DATABASES,
    validate_target_database_name,
    get_database_name,
    sanitize_url_for_logging,
    get_sanitized_target_identity,
    provision_isolated_database,
    verify_effective_database_identity,
    verify_isolated_database_has_no_business_records,
    Phase8ControlledRunner,
    run_preflight_safeguard_check,
)


class TestPhase8Safeguards(unittest.TestCase):
    """Test suite for Phase 8 database isolation, naming conventions, and fail-closed gates."""

    def test_protected_database_names_rejected(self):
        """Every protected database must be rejected with a security violation."""
        for db in PROTECTED_DATABASES:
            valid, reason = validate_target_database_name(db)
            self.assertFalse(valid, f"Database '{db}' must be rejected")
            self.assertIn("SECURITY VIOLATION", reason)

    def test_ordinary_sandbox_database_rejected(self):
        """leadgen_release_sandbox must be rejected because it contains business data."""
        valid, reason = validate_target_database_name("leadgen_release_sandbox")
        self.assertFalse(valid)
        self.assertIn("SECURITY VIOLATION", reason)
        self.assertIn("leadgen_release_sandbox", reason)

    def test_disallowed_system_databases_rejected(self):
        """System databases like postgres and template databases must be rejected."""
        for db in ["postgres", "template0", "template1"]:
            valid, reason = validate_target_database_name(db)
            self.assertFalse(valid)
            self.assertIn("SECURITY VIOLATION", reason)

    def test_naming_convention_enforcement(self):
        """Database name must strictly match 'leadgen_phase8_e2e_<suffix>'."""
        invalid_names = [
            "leadgen",
            "phase8_test",
            "test_leadgen_phase8_e2e",
            "leadgen_phase8_e2e",  # missing suffix
            "leadgen_phase8_e2e-dash",  # hyphen not allowed
            "custom_sandbox_db",
        ]
        for name in invalid_names:
            valid, reason = validate_target_database_name(name)
            self.assertFalse(valid, f"Name '{name}' should be invalid")

        valid_names = [
            "leadgen_phase8_e2e_run1",
            "leadgen_phase8_e2e_20261021_abc123",
            "leadgen_phase8_e2e_test_probe_01",
        ]
        for name in valid_names:
            valid, reason = validate_target_database_name(name)
            self.assertTrue(valid, f"Name '{name}' should be valid: {reason}")

    def test_url_sanitization_masks_credentials(self):
        """Database URLs must mask user passwords and sensitive query params."""
        raw_url = "postgresql+psycopg://myuser:SuperSecretPassword123!@localhost:5432/leadgen_phase8_e2e_01"
        sanitized = sanitize_url_for_logging(raw_url)
        self.assertNotIn("SuperSecretPassword123!", sanitized)
        self.assertIn("myuser:***@localhost:5432/leadgen_phase8_e2e_01", sanitized)

    def test_sanitized_identity_attributes(self):
        """get_sanitized_target_identity returns non-sensitive descriptors."""
        url = "postgresql+psycopg://leadgen_app:secret@localhost:5432/leadgen_phase8_e2e_test"
        ident = get_sanitized_target_identity(url)
        self.assertEqual(ident["database_name"], "leadgen_phase8_e2e_test")
        self.assertEqual(ident["host"], "localhost")
        self.assertEqual(ident["host_classification"], "local")
        self.assertEqual(ident["application_role"], "leadgen_app")
        self.assertNotIn("secret", ident["sanitized_url"])

    def test_existing_database_not_overwritten_or_dropped(self):
        """If target database already exists, provisioning must fail closed without dropping or overwriting."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Mock role check: superuser True
            mock_cur.fetchone.side_effect = [
                ("postgres", True, True),  # role info
                (1,),                      # database exists check -> returns 1 (already exists!)
            ]

            with self.assertRaises(FileExistsError) as ctx:
                provision_isolated_database(
                    admin_url="postgresql://postgres:pass@localhost:5432/postgres",
                    db_name="leadgen_phase8_e2e_existing",
                )

            self.assertIn("already exists", str(ctx.exception))
            # Verify CREATE DATABASE and DROP DATABASE were NOT called
            for call in mock_cur.execute.call_args_list:
                sql = call[0][0].upper()
                self.assertNotIn("DROP DATABASE", sql)
                self.assertNotIn("CREATE DATABASE", sql)

    def test_unauthorized_provisioning_fails_closed(self):
        """Admin connection lacking privileges must fail closed without escalating permissions."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Mock role check: not superuser, not createdb
            mock_cur.fetchone.return_value = ("restricted_user", False, False)

            with self.assertRaises(PermissionError) as ctx:
                provision_isolated_database(
                    admin_url="postgresql://restricted_user:pass@localhost:5432/postgres",
                    db_name="leadgen_phase8_e2e_new",
                )

            self.assertIn("lacks CREATE DATABASE privilege", str(ctx.exception))

    def test_effective_identity_verification_detects_mismatch(self):
        """verify_effective_database_identity detects when connected database or user does not match expected."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Return mismatch: connected to 'different_db' instead of 'leadgen_phase8_e2e_target'
            mock_cur.fetchone.return_value = ("different_db", "leadgen_release_app", "127.0.0.1", 5432)

            ok, info = verify_effective_database_identity(
                "postgresql://leadgen_release_app:pass@localhost:5432/leadgen_phase8_e2e_target",
                expected_db_name="leadgen_phase8_e2e_target",
                expected_user="leadgen_release_app",
            )
            self.assertFalse(ok)
            self.assertIn("Database mismatch", info["error"])

    def test_isolated_database_rejects_preexisting_records(self):
        """Target database containing pre-existing records must fail isolation check."""
        with patch("psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Mock table existence
            mock_cur.fetchall.return_value = [("leads",)]
            mock_cur.fetchone.return_value = (42,)  # 42 pre-existing records!

            ok, msg = verify_isolated_database_has_no_business_records(
                "postgresql://leadgen_release_app:pass@localhost:5432/leadgen_phase8_e2e_target"
            )
            self.assertFalse(ok)
            self.assertIn("42 pre-existing records", msg)


class TestPhase8RunnerStages(unittest.TestCase):
    """Test runner stages, partial progress recording, and fail-closed gatekeeping."""

    def test_missing_phase8_config_fails_closed_without_fallback(self):
        """Runner fails closed when target is missing and admin is unavailable, never falling back to DATABASE_URL."""
        runner = Phase8ControlledRunner()

        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql+psycopg://leadgen_release_app:pass@localhost:5432/leadgen_release_sandbox",
            "JWT_SECRET": "dummy_secret_for_tests_must_be_32_characters_long_min",
        }), patch("scripts.validate_phase8_controlled_e2e.provision_isolated_database") as mock_prov:
            mock_prov.side_effect = PermissionError("Admin connection refused")

            report = asyncio.run(runner.run(phase8_e2e_db_url=None, phase8_admin_db_url="postgresql://invalid:5432/postgres"))

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["stages"]["stage_1_preflight_and_identity"]["status"], "FAILED")
            self.assertIn("Fallback to normal application DATABASE_URL is strictly prohibited", report["stages"]["stage_1_preflight_and_identity"]["error"])
            # Ensure downstream stages were never executed
            self.assertEqual(report["stages"]["stage_2_schema_and_readiness"]["status"], "PENDING")
            self.assertEqual(report["stages"]["stage_3_bounded_audit_execution"]["status"], "PENDING")

    def test_ordinary_application_database_rejected_by_runner(self):
        """Runner rejects leadgen_release_sandbox even if explicitly passed."""
        runner = Phase8ControlledRunner()
        bad_url = "postgresql+psycopg://leadgen_release_app:pass@localhost:5432/leadgen_release_sandbox"

        report = asyncio.run(runner.run(phase8_e2e_db_url=bad_url))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["stages"]["stage_1_preflight_and_identity"]["status"], "FAILED")
        self.assertIn("leadgen_release_sandbox", report["stages"]["stage_1_preflight_and_identity"]["error"])

    def test_blocked_preflight_no_mutations_or_dispatch(self):
        """Preflight failure halts runner immediately; no audit or proposals are run."""
        runner = Phase8ControlledRunner()
        bad_url = "postgresql+psycopg://user:pass@localhost:5432/leadgen"  # Protected DB

        with patch("app.engines.audit_engine.run_audit") as mock_audit, \
             patch("app.services.proposal_service.ProposalService.get_or_create_proposal") as mock_proposal:

            report = asyncio.run(runner.run(phase8_e2e_db_url=bad_url))

            self.assertEqual(report["status"], "BLOCKED")
            mock_audit.assert_not_called()
            mock_proposal.assert_not_called()

    def test_missing_admin_url_fails_closed(self):
        """Provisioning without admin URL and without environment config fails closed."""
        with patch.dict(os.environ, {}, clear=True), patch("scripts.validate_phase8_controlled_e2e.get_admin_database_url", return_value=None):
            with self.assertRaises(PermissionError) as ctx:
                provision_isolated_database(admin_url=None, db_name="leadgen_phase8_e2e_test")
            self.assertIn("Administrative connection is not configured", str(ctx.exception))

    def test_preflight_blocks_when_admin_missing(self):
        """Preflight check marks execution as BLOCKED when admin URL is not configured."""
        with patch.dict(os.environ, {}, clear=True), patch("scripts.validate_phase8_controlled_e2e.get_admin_database_url", return_value=None):
            result = run_preflight_safeguard_check()
            self.assertTrue(result["verdict"].startswith("BLOCKED"))
            self.assertFalse(result["admin_connection_available"])
            self.assertFalse(result["can_provision_isolated_target"])


if __name__ == "__main__":
    unittest.main()
