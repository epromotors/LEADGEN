import unittest
from backend.app.engines.factor_contract import determine_lifecycle


class LifecycleTests(unittest.TestCase):
    def test_lifecycle_distinguishes_complete_partial_and_blocked(self):
        self.assertEqual(determine_lifecycle(homepage_ok=True, crawl_status="COMPLETE"), "COMPLETE")
        self.assertEqual(determine_lifecycle(homepage_ok=True, crawl_status="ERROR"), "PARTIAL")
        self.assertEqual(determine_lifecycle(homepage_ok=False, crawl_status="ERROR"), "BLOCKED")

    def test_homepage_failure_never_reports_complete(self):
        # A failed homepage fetch is the execution boundary used by run_audit.
        self.assertEqual(determine_lifecycle(homepage_ok=False, crawl_status="COMPLETE"), "BLOCKED")
