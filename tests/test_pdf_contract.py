import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "auditor" / "auditor"))

from reporter.pdf_report import build_pdf


class PdfContractTests(unittest.TestCase):
    def test_structured_result_generates_a_pdf(self):
        result = {
            "technical": {
                "ssl": {
                    "id": "technical.ssl", "status": "PASS", "value": True,
                    "value_type": "boolean", "score": 10, "max_score": 10,
                    "severity": "critical", "confidence": 1.0, "message": "HTTPS verified.",
                    "evidence": [], "threshold": {}, "engine": "http_raw_dom",
                    "checked_at": "2026-10-09T00:00:00+00:00", "duration_ms": 1,
                    "fix": "", "detail": "",
                }
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "audit.pdf"
            build_pdf("https://example.test", result, 100, str(output), {}, [])
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 0)
