import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "auditor" / "auditor"))

from auditor.content import audit_word_count
from auditor.performance import audit_response_time


class StructuredValueTests(unittest.TestCase):
    def test_word_count_is_numeric_without_message_parsing(self):
        soup = BeautifulSoup(f"<body>{'word ' * 320}</body>", "html.parser")
        result = audit_word_count(soup)
        self.assertEqual(result["value"], 320)
        self.assertEqual(result["unit"], "words")

    def test_response_time_is_numeric_without_message_parsing(self):
        class Response:
            elapsed = type("Elapsed", (), {"total_seconds": staticmethod(lambda: 0.123)})()

        class Session:
            @staticmethod
            def get(*_args, **_kwargs):
                return Response()

        with patch("auditor.performance.time.time", side_effect=[100.0, 100.123]):
            result = audit_response_time("https://example.test", Session())
        self.assertEqual(result["value"], 123)
        self.assertEqual(result["unit"], "ms")
