import unittest
from backend.app.engines.factor_contract import safe_execute_factor


FACTOR = {"id": "technical.example", "value_type": "boolean", "score_weight": 5}


class FactorExecutionTests(unittest.TestCase):
    def test_factor_exception_isolated_as_error(self):
        def broken():
            raise RuntimeError("network unavailable")

        result = safe_execute_factor(FACTOR, broken, "https://example.test")
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("RuntimeError", result["error"])


    def test_other_factor_continues_after_failure(self):
        failed = safe_execute_factor(FACTOR, lambda: (_ for _ in ()).throw(ValueError("bad")), None)
        passed = safe_execute_factor(FACTOR, lambda: {"status": "PASS", "message": "ok", "value": True}, None)
        self.assertEqual(failed["status"], "ERROR")
        self.assertEqual(passed["status"], "PASS")
