import unittest

from backend.app.utils.site_checker import SiteType, classification_error_result


class ClassifierFailureTests(unittest.TestCase):
    def test_classifier_error_is_distinct_from_real(self):
        site_type, reason = classification_error_result(RuntimeError("network unavailable"))
        self.assertEqual(site_type, SiteType.CLASSIFICATION_ERROR)
        self.assertNotEqual(site_type, SiteType.REAL)
        self.assertIn("network unavailable", reason)
