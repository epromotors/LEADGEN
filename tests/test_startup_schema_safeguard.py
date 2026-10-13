import os
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure dummy values so config loads cleanly without live database
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app import database
from app.config import Settings
from app.models import CampaignStatus, Base


class StartupSchemaSafeguardTests(unittest.IsolatedAsyncioTestCase):
    def test_default_init_schema_is_false(self):
        s = Settings(DATABASE_URL="postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen", JWT_SECRET="dummy" * 8)
        self.assertFalse(s.INIT_SCHEMA, "Default INIT_SCHEMA must be False")

    async def test_create_tables_skipped_when_init_schema_false(self):
        with patch.object(database.settings, "INIT_SCHEMA", False):
            mock_engine = MagicMock()
            with patch.object(database, "engine", mock_engine):
                await database.create_tables()
                mock_engine.begin.assert_not_called()

    async def test_create_tables_executes_when_init_schema_true(self):
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


if __name__ == "__main__":
    unittest.main()
