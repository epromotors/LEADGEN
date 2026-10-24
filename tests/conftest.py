import os
from pathlib import Path
import sys
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")


ROOT = Path(__file__).resolve().parents[1]

# auditor/auditor must precede backend so that bare `import config` inside the
# auditor package (e.g. reporter/pdf_report.py) resolves to
# auditor/auditor/config.py rather than the backend's app/config.py.
# Insert in reverse order: the last insert() wins position 0.
AUDITOR_PATH = str(ROOT / "auditor" / "auditor")
BACKEND_PATH = str(ROOT / "backend")

for _p in (BACKEND_PATH, AUDITOR_PATH):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

# auditor/auditor is now at index 0; backend is at index 1.
# If a prior import already cached the backend 'config' module under the bare
# key 'config', evict it so that auditor tests get the correct one.
sys.modules.pop("config", None)


@pytest.fixture(autouse=True)
def _reset_ai_search_router_singleton():
    """
    Reset the module-level AiSearchMonitoringService singleton in the AI search
    router before every test.  Without this, router endpoint tests that import
    app.routers.ai_search leave the singleton in a mutated state that makes
    subsequent unit tests in test_ai_search_service.py fail when the full 697-
    test suite is collected in one process.
    """
    try:
        import importlib
        import app.routers.ai_search as _router_mod
        from app.services.ai_search_service import AiSearchMonitoringService
        _router_mod._ai_search_service = AiSearchMonitoringService()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_campaign_schema_cache():
    """
    Ensure campaign schema cache and test overrides are cleanly reset around
    every test, preventing cross-test pollution across all test modules.
    """
    try:
        from app.services.campaign_schema_service import reset_schema_cache
        reset_schema_cache()
    except Exception:
        pass
    yield
    try:
        from app.services.campaign_schema_service import reset_schema_cache
        reset_schema_cache()
    except Exception:
        pass

