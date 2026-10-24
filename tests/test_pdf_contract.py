import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

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

    def test_all_11_groups_and_url_identity_pdf_rendering(self):
        groups = [
            "technical", "onpage", "images", "links", "conversion",
            "ux", "indexability", "content", "local_seo", "performance", "schema_adv"
        ]
        result = {}
        for g in groups:
            result[g] = {
                f"{g}_check": {
                    "id": f"{g}.sample", "status": "FAIL", "value": "Test Value",
                    "value_type": "string", "score": 0, "max_score": 10,
                    "severity": "critical" if g == "technical" else "high" if g == "onpage" else "medium",
                    "confidence": 1.0, "message": f"{g} sample finding observation.",
                    "evidence": [], "threshold": {}, "engine": "http_raw_dom",
                    "checked_at": "2026-10-15T00:00:00+00:00", "duration_ms": 5,
                    "fix": f"Apply fix for {g}.", "detail": "Observed in test.",
                }
            }

        url_info = {
            "requested_url": "https://carmedicmotors.in/",
            "final_url": "https://carmedicmotors.in/",
            "canonical_url": "https://carmedicmotors.in/lucknow",
            "is_redirected": False,
        }
        site_summary = {
            "total_pages": 3,
            "status_counts": {"PASS": 1, "WARN": 1, "FAIL": 1},
            "top_issues": [("Missing XML Sitemap", 1)],
            "worst_pages": [{"url": "https://carmedicmotors.in/contact", "status": "FAIL", "issue_count": 2}],
            "url_info": url_info,
        }
        page_audits = [
            {"url": "https://carmedicmotors.in/", "title": "Car Medic Motors", "issues": [{"severity": "FAIL", "check": "Missing H1"}]},
            {"url": "https://carmedicmotors.in/about", "title": "About Us", "issues": []},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "comprehensive_audit.pdf"
            build_pdf(
                "https://carmedicmotors.in/",
                result,
                65,
                str(output),
                site_summary=site_summary,
                page_audits=page_audits,
                url_info=url_info,
            )
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 10000, "Comprehensive PDF should be larger than 10KB")
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
            self.assertIn("Methodology & Limitations", extracted)
            self.assertIn("Canonical audit results", extracted)
            self.assertIn("No browser lab metrics were captured", extracted)

    def test_detailed_findings_and_crawl_diagnostics_use_recorded_evidence(self):
        result = {
            "technical": {
                "robots": {
                    "id": "technical.robots", "status": "WARN", "value": None,
                    "score": 0, "max_score": 7, "severity": "review",
                    "message": "Could not fetch robots.txt: request timed out.",
                    "detail": "URL: https://example.test/robots.txt timed out.",
                    "fix": "Ensure the server responds promptly to /robots.txt requests.",
                    "evidence": [{"url": "https://example.test/robots.txt", "timeout": True}],
                    "engine": "http_raw_dom", "checked_at": "2026-10-21T10:00:00+00:00",
                    "duration_ms": 5000, "confidence": 0.8,
                },
                "sitemap": {
                    "id": "technical.sitemap", "status": "PASS", "value": True,
                    "score": 8, "max_score": 8, "severity": "low",
                    "message": "Sitemap found: https://example.test/sitemap.xml (4 URLs)",
                    "detail": "https://example.test/sitemap.xml [HTTP 200]: Valid XML urlset (4 URLs)",
                    "fix": "", "evidence": [{"url": "https://example.test/sitemap.xml", "status_code": 200}],
                },
            }
        }
        site_summary = {
            "total_pages": 2,
            "sitemap_url_count": 4,
            "link_discovered_count": 1,
            "total_discovered_count": 5,
            "crawl_limit_hit": True,
            "discovery_explanation": "Crawl limit (2 pages) prevented full coverage.",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "evidence_report.pdf"
            build_pdf("https://example.test", result, 72, str(output), site_summary=site_summary)
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
            self.assertIn("Affected URL:", extracted)
            self.assertIn("Collected Evidence:", extracted)
            self.assertIn("source: http_raw_dom", extracted)
            self.assertIn("Technical Crawl, Robots & Sitemap Diagnostics", extracted)
            self.assertIn("robots.txt retrieval", extracted)
            self.assertIn("Crawl limit reached; coverage is intentionally bounded.", extracted)
