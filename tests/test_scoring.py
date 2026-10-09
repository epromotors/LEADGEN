import unittest

from backend.app.engines.factor_contract import FactorRegistryError, compute_score


class ScoringTests(unittest.TestCase):
    def test_na_is_excluded_from_score_denominator(self):
        results = {"technical": {
        "a": {"id": "technical.a", "status": "PASS", "score": 10, "max_score": 10},
        "b": {"id": "technical.b", "status": "PASS", "score": 10, "max_score": 10},
        "c": {"id": "technical.c", "status": "PASS", "score": 10, "max_score": 10},
        "d": {"id": "technical.d", "status": "N/A", "score": 0, "max_score": 10},
        "e": {"id": "technical.e", "status": "N/A", "score": 0, "max_score": 10},
    }}
        registry = {item["id"]: item for item in [
            {"id": "technical.a"}, {"id": "technical.b"}, {"id": "technical.c"},
            {"id": "technical.d"}, {"id": "technical.e"},
        ]}
        self.assertEqual(compute_score(results, {"technical": 1}, registry), 100)


    def test_unknown_status_is_rejected_not_scored(self):
        results = {"technical": {"x": {"id": "technical.x", "status": "MYSTERY", "score": 5, "max_score": 5}}}
        with self.assertRaisesRegex(FactorRegistryError, "invalid factor state"):
            compute_score(results, {"technical": 1})

    def test_unknown_factor_id_is_rejected_not_scored(self):
        results = {"technical": {"invented": {"id": "technical.invented", "status": "PASS", "score": 5, "max_score": 5}}}
        with self.assertRaisesRegex(FactorRegistryError, "unknown factor id"):
            compute_score(results, {"technical": 1})
