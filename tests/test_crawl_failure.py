import unittest
from backend.app.engines.factor_contract import determine_lifecycle


class CrawlFailureTests(unittest.TestCase):
    def test_crawl_failure_with_homepage_evidence_is_partial(self):
        self.assertEqual(determine_lifecycle(homepage_ok=True, crawl_status="ERROR"), "PARTIAL")
