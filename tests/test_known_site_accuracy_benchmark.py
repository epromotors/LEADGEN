"""LEADGEN — Phase 7: Known-Site Accuracy & Regression Benchmark Test Suite.

Deterministic, offline verification of the benchmark fixture corpus,
exercising real audit code paths without live website or database dependencies.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUDITOR_ROOT = _REPO_ROOT / "auditor" / "auditor"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_AUDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_AUDITOR_ROOT))

# Ensure dummy values so config loads cleanly without live database
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from auditor.benchmark import (
    run_benchmark_suite,
    DEFAULT_FIXTURES_DIR,
    _run_case_01_url_identity,
    _run_case_02_origin_robots_sitemap,
    _run_case_03_sitemap_variations,
    _run_case_04_json_ld_localbusiness,
    _run_case_05_crawl_coverage,
    _run_case_06_genuine_defects_vs_retrieval_errors,
    _run_case_07_lab_vs_field_metrics,
    _run_case_08_carmedicmotors_regression,
)
from backend.app.engines.factor_contract import (
    load_factor_registry,
    validate_factor_registry,
    compute_score,
)


class TestBenchmarkCorpusAndRegression:
    @classmethod
    def setup_class(cls):
        assert DEFAULT_FIXTURES_DIR.is_dir(), f"Fixtures directory missing: {DEFAULT_FIXTURES_DIR}"

    def test_full_benchmark_suite_execution(self):
        """Execute the full 8-case benchmark suite and verify zero false positives/negatives."""
        report = run_benchmark_suite(DEFAULT_FIXTURES_DIR)

        assert report.total_cases == 8
        assert report.passed_cases == 8
        assert report.failed_cases == 0

        # Zero false positives and zero false negatives
        assert report.false_positives == 0, f"Detected {report.false_positives} false positives"
        assert report.false_negatives == 0, f"Detected {report.false_negatives} false negatives"

        # Disclosures must be clearly present
        assert len(report.sample_size_disclosure) > 20
        assert len(report.limitations_disclosure) > 20

        # Markdown format generation
        md_summary = report.format_summary_markdown()
        assert "# LEADGEN — Known-Site Accuracy & Regression Benchmark Report" in md_summary
        assert "BM-01-URL-IDENTITY" in md_summary
        assert "BM-08-CARMEDICMOTORS-REGRESSION" in md_summary

    def test_case_01_url_identity_separation(self):
        """Case 1: requested URL, final redirect URL, and canonical URL are distinct."""
        res = _run_case_01_url_identity(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert res.actual_provenance["requested_url"] != res.actual_provenance["final_url"]
        assert res.actual_provenance["final_url"] != res.actual_provenance["canonical_url"]
        assert res.actual_provenance["is_redirected"] is True
        assert res.actual_findings["canonical_tag"] == "https://www.example.com/en/services"

    def test_case_02_origin_robots_and_sitemap_resolution(self):
        """Case 2: Origin-root robots.txt discovery and sitemap URL resolution."""
        res = _run_case_02_origin_robots_sitemap(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert res.actual_findings["robots_status"] == "PASS"
        assert res.actual_findings["sitemap_status"] == "PASS"
        # Must not probe subpath robots.txt
        for probed in res.actual_findings["probed_urls"]:
            assert "midtown/auto-repair/robots.txt" not in probed

    def test_case_03_xml_sitemap_variations(self):
        """Case 3: XML sitemap variations (valid urlset, index, malformed XML, soft 404 HTML)."""
        res = _run_case_03_sitemap_variations(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert res.actual_findings["valid_urlset_status"] == "PASS"
        assert res.actual_findings["sitemap_index_status"] == "PASS"
        assert res.actual_findings["malformed_xml_status"] in {"FAIL", "WARN"}
        assert res.actual_findings["soft_404_status"] in {"FAIL", "WARN"}
        assert res.actual_findings["soft_404_rejected_as_html"] is True

    def test_case_04_json_ld_localbusiness_consistency(self):
        """Case 4: Consistent JSON-LD extraction, AutoRepair / LocalBusiness across factors."""
        res = _run_case_04_json_ld_localbusiness(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert "AutoRepair" in res.actual_findings["extracted_types"]
        assert res.actual_findings["onpage_schema_status"] == "PASS"
        assert res.actual_findings["local_business_schema_status"] == "PASS"
        assert res.actual_findings["nap_consistency_status"] == "PASS"

    def test_case_05_crawl_coverage_and_boundaries(self):
        """Case 5: Crawl coverage, link filtering, deduplication, and max_pages bounds."""
        res = _run_case_05_crawl_coverage(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert res.actual_findings["count_crawled"] <= 3
        assert res.actual_findings["no_external_crawled"] is True
        assert res.actual_findings["no_pdf_asset_crawled"] is True
        assert res.actual_findings["no_jpg_asset_crawled"] is True
        assert res.actual_findings["duplicate_about_deduped"] is True

    def test_case_06_genuine_defects_vs_retrieval_errors(self):
        """Case 6: Genuine defects detected vs retrieval errors / timeouts honestly isolated."""
        res = _run_case_06_genuine_defects_vs_retrieval_errors(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        # Genuine defects return FAIL
        assert res.actual_findings["genuine_title_status"] == "FAIL"
        assert res.actual_findings["genuine_h1_status"] == "FAIL"
        # Network timeout returns ERROR and is excluded from opportunity proposals
        assert res.actual_findings["timeout_factor_status"] == "ERROR"
        assert res.actual_findings["timeout_error_logged"] is True
        assert res.actual_findings["timeout_excluded_from_opportunities"] is True

    def test_case_07_lab_vs_field_metrics(self):
        """Case 7: Synthetic lab metrics distinguished from unavailable field metrics."""
        res = _run_case_07_lab_vs_field_metrics(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_POSITIVE"
        assert res.actual_findings["is_synthetic_lab"] is True
        assert res.actual_findings["field_status"] == "unavailable"
        assert res.actual_findings["gsc_connected"] is False
        assert res.actual_findings["gsc_rows"] == 0

    def test_case_08_carmedicmotors_regression(self):
        """Case 8: Car Medic Motors historical defect fully verified as resolved."""
        res = _run_case_08_carmedicmotors_regression(DEFAULT_FIXTURES_DIR)
        assert res.passed is True
        assert res.classification == "TRUE_NEGATIVE"
        assert res.actual_provenance["requested_url"] == "https://carmedicmotors.in"
        assert res.actual_provenance["canonical_url"] == "https://carmedicmotors.in/lucknow"
        assert res.actual_findings["url_correct"] is True
        assert res.actual_findings["probed_lucknow_robots"] is False
        assert res.actual_findings["robots_status"] == "PASS"
        assert res.actual_findings["sitemap_status"] == "PASS"
        assert res.actual_findings["onpage_schema_status"] == "PASS"
        assert res.actual_findings["local_business_schema_status"] == "PASS"

    def test_canonical_62_factor_contract_invariants(self):
        """Verify that all 62 canonical factors remain strictly defined, unmodified and valid."""
        registry = validate_factor_registry()
        assert len(registry) == 62, f"Expected 62 factors, got {len(registry)}"

        # Check key canonical factor IDs from benchmark scenarios
        expected_sample = [
            "technical.ssl",
            "technical.sitemap",
            "technical.robots",
            "technical.canonical",
            "onpage.page_title",
            "onpage.h1",
            "onpage.meta_desc",
            "onpage.schema",
            "local_seo.local_business_schema",
            "local_seo.nap_consistency",
            "images.alt_text",
            "links.broken_links",
        ]
        for fid in expected_sample:
            assert fid in registry, f"Canonical factor missing: {fid}"
            factor = registry[fid]
            assert factor["score_weight"] > 0
            assert factor["axis"]
            assert factor["module"]
            assert factor["function"]
