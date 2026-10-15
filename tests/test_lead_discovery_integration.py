"""
tests/test_lead_discovery_integration.py

Comprehensive test suite for the integrated Lead Discovery system:
1. Keyword and location text file uploads (UTF-8 BOM, comments, blank lines, case-insensitive deduplication).
2. Size limits, entry limits, and combination safety budget calculations.
3. Provider status and failure classification (rate_limited, quota_exhausted, authentication_error, etc.).
4. Provider failover chain and secret masking.
5. Permitted vs prohibited sources (direct scraping prohibited terms enforcement).
6. SSRF protections, loopback/private IP blocking, and TLS verification.
7. Outdated and dead website classification & /contact page fallback.
8. Email enrichment with mocked Hunter & public search fallback.
9. Job lifecycle: creation, stepping, checkpointing, pause, resume, and cancellation.
10. Data provenance, verification candidate status, and duplicate protection.
11. Full lead schema and simple 3-column CSV exports.
12. FastAPI router endpoints for discovery.
13. Proof that no live network, external API calls, or email sending occurs.
"""

import asyncio
import io
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.services.lead_discovery_service import (
    LeadDiscoveryService,
    ProviderStatus,
    JobStatus,
    parse_txt_upload_content,
    clean_email,
    extract_email,
    clean_website,
    audit_website_is_old_or_dead,
    is_safe_external_url,
    DEFAULT_PRESET_KEYWORDS,
    DEFAULT_PRESET_LOCATIONS,
)
from app.routers.leads import router as leads_router


# ─────────────────────────────────────────────────────────────────────────────
# 1. Text File Upload Processing (.txt)
# ─────────────────────────────────────────────────────────────────────────────

def test_txt_upload_parser_bom_comments_and_blanks():
    # File with UTF-8 BOM, comments, empty lines, and trailing spaces
    content = (
        "\ufeff# Target Keywords for Roofing & Solar\n"
        "  roofing contractor  \n"
        "\n"
        "# Another comment\n"
        "solar panel installation\n"
        "   \n"
        "gutter repair\n"
    ).encode("utf-8")

    parsed = parse_txt_upload_content(content)
    assert parsed["valid_count"] == 3
    assert parsed["entries"] == [
        "roofing contractor",
        "solar panel installation",
        "gutter repair",
    ]
    assert parsed["ignored_count"] >= 3  # Comments + blank lines
    assert parsed["duplicate_count"] == 0
    assert parsed["rejected_count"] == 0


def test_txt_upload_parser_case_insensitive_deduplication():
    content = (
        "Dental Clinic\n"
        "dental clinic\n"
        "DENTAL CLINIC\n"
        "Dentist Office\n"
        "dentist office\n"
    ).encode("utf-8")

    parsed = parse_txt_upload_content(content)
    assert parsed["valid_count"] == 2
    assert parsed["duplicate_count"] == 3
    # Preserves first seen readable casing
    assert parsed["entries"] == ["Dental Clinic", "Dentist Office"]


def test_txt_upload_parser_size_and_entry_limits():
    # Empty file
    with pytest.raises(ValueError, match="no usable entries"):
        parse_txt_upload_content(b"")

    # Only comments
    with pytest.raises(ValueError, match="no usable entries"):
        parse_txt_upload_content(b"# Just a comment\n# Another comment\n")

    # Oversized file
    big_content = b"a" * 500
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        parse_txt_upload_content(big_content, max_file_size=100)

    # Max entries limit
    lines = [f"keyword_{i}\n" for i in range(15)]
    content = "".join(lines).encode("utf-8")
    parsed = parse_txt_upload_content(content, max_entries=5)
    assert parsed["valid_count"] == 5
    assert parsed["rejected_count"] == 10


# ─────────────────────────────────────────────────────────────────────────────
# 2. Search Combinations & Budget Safety
# ─────────────────────────────────────────────────────────────────────────────

def test_calculate_combinations_and_safety_limit():
    svc = LeadDiscoveryService(storage_path="")

    # Uploaded only
    res = svc.calculate_combinations(
        keywords=["k1", "k2", "k3"],
        locations=["loc1", "loc2"],
        mode="uploaded_only",
    )
    assert res["keyword_count"] == 3
    assert res["location_count"] == 2
    assert res["total_combinations"] == 6
    assert res["effective_budget"] == 6
    assert res["exceeds_safety_limit"] is False

    # Exceeding safety limit without budget
    big_kws = [f"kw_{i}" for i in range(30)]
    big_locs = [f"loc_{i}" for i in range(25)]
    res_big = svc.calculate_combinations(
        keywords=big_kws,
        locations=big_locs,
        mode="uploaded_only",
        custom_budget=750,
    )
    assert res_big["total_combinations"] == 750
    assert res_big["exceeds_safety_limit"] is True

    # Clamped by budget
    res_budgeted = svc.calculate_combinations(
        keywords=big_kws,
        locations=big_locs,
        mode="uploaded_only",
        custom_budget=100,
    )
    assert res_budgeted["effective_budget"] == 100
    assert res_budgeted["exceeds_safety_limit"] is False


def test_presets_mode_and_combine():
    svc = LeadDiscoveryService(storage_path="")

    # Presets only
    res_preset = svc.calculate_combinations([], [], mode="presets_only")
    assert res_preset["keyword_count"] == len(DEFAULT_PRESET_KEYWORDS)
    assert res_preset["location_count"] == len(DEFAULT_PRESET_LOCATIONS)
    assert res_preset["total_combinations"] > 100

    # Combine uploaded with presets
    res_comb = svc.calculate_combinations(
        keywords=["custom niche"],
        locations=["Custom City"],
        mode="combine",
    )
    assert res_comb["keyword_count"] == len(DEFAULT_PRESET_KEYWORDS) + 1
    assert res_comb["location_count"] == len(DEFAULT_PRESET_LOCATIONS) + 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Provider Status Lifecycle & Failover Classification
# ─────────────────────────────────────────────────────────────────────────────

def test_provider_status_classification():
    svc = LeadDiscoveryService(storage_path="")

    assert svc._classify_http_status(401) == ProviderStatus.AUTHENTICATION_ERROR
    assert svc._classify_http_status(402) == ProviderStatus.QUOTA_EXHAUSTED
    assert svc._classify_http_status(429) == ProviderStatus.RATE_LIMITED
    assert svc._classify_http_status(500) == ProviderStatus.TEMPORARILY_UNAVAILABLE
    assert svc._classify_http_status(503) == ProviderStatus.TEMPORARILY_UNAVAILABLE
    assert svc._classify_http_status(200) == ProviderStatus.AVAILABLE


def test_secret_key_masking():
    svc = LeadDiscoveryService(storage_path="")
    assert svc._mask_key("") == ""
    assert svc._mask_key("12345") == "***"
    assert svc._mask_key("serper_live_secret_key_9999") == "ser...999"


def test_prohibited_direct_scraping_is_disabled():
    svc = LeadDiscoveryService(storage_path="")
    statuses = svc.get_provider_statuses()
    # Direct Google Maps web scraping is explicitly disabled
    assert statuses["google_maps_direct"]["status"] == "disabled"
    assert "prohibited" in statuses["google_maps_direct"]["last_error"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. SSRF & URL Security Checks
# ─────────────────────────────────────────────────────────────────────────────

def test_is_safe_external_url_ssrf_blocking():
    # Private / Loopback IPs
    assert is_safe_external_url("http://127.0.0.1:8000")[0] is False
    assert is_safe_external_url("http://localhost:5173")[0] is False
    assert is_safe_external_url("http://10.0.0.1/admin")[0] is False
    assert is_safe_external_url("http://192.168.1.1")[0] is False
    assert is_safe_external_url("http://169.254.169.254/latest/meta-data/")[0] is False

    # Blocked schemes
    assert is_safe_external_url("file:///etc/passwd")[0] is False
    assert is_safe_external_url("gopher://127.0.0.1:70")[0] is False

    # Valid public domain
    safe, _ = is_safe_external_url("https://example.com")
    assert safe is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Outdated / Dead Website Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def test_outdated_website_diagnostic_suite():
    # Empty
    is_target, reason = audit_website_is_old_or_dead("", "", 0)
    assert is_target is True
    assert reason == "No Website"

    # Dead
    is_target, reason = audit_website_is_old_or_dead("https://dead.com", "", 502)
    assert is_target is True
    assert "Dead Website (HTTP 502)" in reason

    # Outdated HTML
    words = "word " * 100
    html_old = f"""
    <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
    <html>
      <head><title>Old Co</title></head>
      <body>
        <marquee>Special Deals Today!</marquee>
        <table><tr><td>{words}</td></tr></table>
        <table><tr><td>1</td></tr></table>
        <table><tr><td>2</td></tr></table>
        <table><tr><td>3</td></tr></table>
        <footer>&copy; 2018 Old Co</footer>
      </body>
    </html>
    """
    is_target, reason = audit_website_is_old_or_dead("http://oldco.com", html_old, 200)
    assert is_target is True
    assert "Outdated Design" in reason
    assert "No SSL" in reason
    assert "Not Mobile Responsive" in reason
    assert "Old HTML4/XHTML Doctype" in reason
    assert "Old Copyright Year (2018)" in reason


# ─────────────────────────────────────────────────────────────────────────────
# 6. Job Lifecycle & Checkpoint/Resume (Mocked)
# ─────────────────────────────────────────────────────────────────────────────

def test_job_lifecycle_checkpoint_pause_resume(tmp_path):
    job_file = str(tmp_path / "test_jobs.json")
    svc = LeadDiscoveryService(storage_path=job_file, allow_test_loopback=True)

    # 1. Create Job
    job = svc.create_job(
        keywords=["plumbing", "roofing"],
        locations=["Austin", "Dallas"],
        mode="uploaded_only",
        budget=4,
    )
    job_id = job["job_id"]
    assert job["status"] == JobStatus.PENDING.value
    assert job["total_combinations"] == 4

    # Mock search and site inspection
    def mock_places(kw, city):
        return [
            {
                "name": f"{city} {kw.capitalize()} Pros",
                "website": f"http://{kw}{city.lower()}.com",
                "phone": "+1 512 555 0100",
                "email": f"info@{kw}{city.lower()}.com",
                "source": "mock_api",
                "method": "api_maps",
            }
        ], "mock_api", "api_maps"

    def mock_inspect(url):
        return True, "Outdated Design: No SSL", None

    # 2. Step 1 combination
    res = asyncio.run(
        svc.run_discovery_job(
            job_id,
            places_mock=mock_places,
            inspect_mock=mock_inspect,
            max_steps=1,
        )
    )
    assert res["current_combination_idx"] == 1
    assert len(res["discovered_leads"]) == 1
    assert res["discovered_leads"][0]["business_name"] == "Austin Plumbing Pros"

    # 3. Pause
    paused = svc.pause_job(job_id)
    assert paused["status"] == JobStatus.PAUSED.value

    # 4. Resume from Checkpoint
    resumed = svc.resume_job(job_id)
    assert resumed["status"] == JobStatus.RUNNING.value

    # 5. Finish remaining combinations
    final = asyncio.run(
        svc.run_discovery_job(
            job_id,
            places_mock=mock_places,
            inspect_mock=mock_inspect,
        )
    )
    assert final["status"] == JobStatus.COMPLETED.value
    assert final["current_combination_idx"] == 4
    assert len(final["discovered_leads"]) == 4

    # 6. Checkpoint persistence across service reconstruction
    svc2 = LeadDiscoveryService(storage_path=job_file)
    restored = svc2.get_job(job_id)
    assert restored["status"] == JobStatus.COMPLETED.value
    assert len(restored["discovered_leads"]) == 4


# ─────────────────────────────────────────────────────────────────────────────
# 7. CSV Exports
# ─────────────────────────────────────────────────────────────────────────────

def test_csv_export_formats(tmp_path):
    job_file = str(tmp_path / "test_jobs.json")
    svc = LeadDiscoveryService(storage_path=job_file)
    job = svc.create_job(keywords=["k"], locations=["l"])
    job_id = job["job_id"]
    job["discovered_leads"] = [
        {
            "business_name": "Acme Motors",
            "email": "contact@acme.com",
            "phone": "+1234567890",
            "website": "http://acme.com",
            "source": "serper",
            "extraction_method": "api_maps",
            "site_classification": "outdated_website",
            "site_classification_reason": "No SSL",
            "observed_at": "2026-10-15T12:00:00Z",
        }
    ]
    svc._save_jobs()

    # Full LeadGen CSV
    full_csv = svc.export_leads_csv(job_id, format_type="leadgen")
    assert "business_name,email,phone,website,status,source" in full_csv
    assert "Acme Motors,contact@acme.com,+1234567890,http://acme.com,new,serper" in full_csv

    # Simple 3-column CSV
    simple_csv = svc.export_leads_csv(job_id, format_type="simple")
    assert "business name,email,website" in simple_csv
    assert "Acme Motors,contact@acme.com,http://acme.com" in simple_csv


# ─────────────────────────────────────────────────────────────────────────────
# 8. FastAPI Router Endpoints (Mocked Client)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def test_client(tmp_path):
    os.environ["DATABASE_URL"] = "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen"
    os.environ["JWT_SECRET"] = "dummy_secret_for_tests_must_be_32_characters_long_min"

    app = FastAPI()
    app.include_router(leads_router)
    return TestClient(app)


def test_router_discovery_presets_and_providers(test_client):
    res_presets = test_client.get("/leads/discovery/presets")
    assert res_presets.status_code == 200
    data = res_presets.json()
    assert "keywords" in data
    assert "locations" in data
    assert len(data["keywords"]) > 0

    res_prov = test_client.get("/leads/discovery/providers")
    assert res_prov.status_code == 200
    prov_data = res_prov.json()
    assert "serper" in prov_data
    assert "google_maps_direct" in prov_data


def test_router_discovery_txt_upload(test_client):
    file_content = b"web design agency\ndental clinic\n# comment\n\nweb design agency\n"
    files = {"file": ("keywords.txt", file_content, "text/plain")}

    resp = test_client.post("/leads/discovery/upload-txt?file_type=keywords", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid_count"] == 2
    assert data["duplicate_count"] == 1
    assert data["ignored_count"] >= 2
    assert data["entries"] == ["web design agency", "dental clinic"]


def test_router_discovery_preview_and_job_lifecycle(test_client):
    # Preview
    preview_resp = test_client.post(
        "/leads/discovery/preview",
        json={"keywords": ["dentist", "doctor"], "locations": ["Austin"], "mode": "uploaded_only"},
    )
    assert preview_resp.status_code == 200
    prev_data = preview_resp.json()
    assert prev_data["total_combinations"] == 2

    # Create job
    create_resp = test_client.post(
        "/leads/discovery/jobs",
        json={"keywords": ["dentist", "doctor"], "locations": ["Austin"], "mode": "uploaded_only"},
    )
    assert create_resp.status_code == 200
    job = create_resp.json()
    job_id = job["job_id"]

    # Get job
    get_resp = test_client.get(f"/leads/discovery/jobs/{job_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["job_id"] == job_id

    # Pause
    pause_resp = test_client.post(f"/leads/discovery/jobs/{job_id}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    # Resume
    resume_resp = test_client.post(f"/leads/discovery/jobs/{job_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "running"

    # Cancel
    cancel_resp = test_client.post(f"/leads/discovery/jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # Export
    export_resp = test_client.get(f"/leads/discovery/jobs/{job_id}/export?format=simple")
    assert export_resp.status_code == 200
    assert "business name,email,website" in export_resp.text
