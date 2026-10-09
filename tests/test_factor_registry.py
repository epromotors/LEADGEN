import unittest

from backend.app.engines.factor_contract import FactorRegistryError, load_factor_registry, validate_factor_registry


class FactorRegistryTests(unittest.TestCase):
    def test_registry_is_complete_and_resolves(self):
        self.assertEqual(len(validate_factor_registry()), 62)


    def test_duplicate_registry_id_is_rejected(self):
        registry = load_factor_registry()
        registry["factors"].append(dict(registry["factors"][0]))
        with self.assertRaisesRegex(FactorRegistryError, "duplicate"):
            validate_factor_registry(registry)
