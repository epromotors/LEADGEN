import unittest
from pathlib import Path
from backend.app.engines.factor_contract import load_factor_registry, validate_factor_registry


class FactorParityTests(unittest.TestCase):
    def test_all_registry_factors_validate(self):
        registry = load_factor_registry()
        self.assertEqual(set(validate_factor_registry(registry)), {factor["id"] for factor in registry["factors"]})

    def test_no_score_lookup_awards_default_points(self):
        root = Path(__file__).resolve().parents[1]
        sources = list((root / "backend").rglob("*.py")) + list((root / "auditor").rglob("*.py"))
        forbidden = "TEST_SCORES.get(test_id, 5)"
        self.assertFalse(any(forbidden in source.read_text(encoding="utf-8") for source in sources))
