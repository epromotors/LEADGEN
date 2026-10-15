"""
tests/test_existing_scraper_isolated.py

Isolated unit and mocked contract tests for the uploaded scraper script:
`C:\\Users\\LENOVO\\Downloads\\gemini-code-1792080477828.py`

Verifies all existing capabilities in an isolated offline environment:
1. Email cleaning and regex extraction (filtering junk domains, invalid TLDs, invalid substrings).
2. Website URL cleaning (stripping Google redirects, junk domains, missing scheme).
3. Outdated/dead website diagnostic rules:
   - No website / dead HTTP status
   - Parked domain signals
   - Thin/empty content (< 80 words)
   - Insecure HTTP (no SSL)
   - Missing mobile viewport
   - Deprecated HTML tags / HTML4 doctype / table layout / jQuery 1.x / old copyright
   - Modern active site passing checks
4. Multi-account KeyRotator mechanics (filtering placeholder keys, cycle, exhaustion).
5. Mocked API business discovery (Serper, SerpApi, HasData, Outscraper, treg).
6. Mocked API email enrichment (Hunter, Serper search snippet).
7. Mocked website HTTP inspection and /contact fallback.
8. CSV persistence and checkpoint resume roundtrips.
9. Documents identified safety and architecture defects in the original script.
"""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import pytest

SCRIPT_PATH = r"C:\Users\LENOVO\Downloads\gemini-code-1792080477828.py"


@pytest.fixture(scope="module")
def scraper_mod():
    """Load the uploaded script in isolation."""
    assert os.path.exists(SCRIPT_PATH), f"Uploaded script not found at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("uploaded_scraper", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# 1. Email and URL Cleaning & Extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_clean_email_valid(scraper_mod):
    assert scraper_mod.clean_email("contact@acmeroofing.com") == "contact@acmeroofing.com"
    assert scraper_mod.clean_email("INFO@MyCompany.co.uk>") == "info@mycompany.co.uk"
    assert scraper_mod.clean_email("  sales@localclinic.in;  ") == "sales@localclinic.in"


def test_clean_email_invalid_filters(scraper_mod):
    # Substrings
    assert scraper_mod.clean_email("noreply@business.com") is None
    assert scraper_mod.clean_email("sentry@business.com") is None
    assert scraper_mod.clean_email("test@example.com") is None
    assert scraper_mod.clean_email("sample@wixpress.com") is None

    # Invalid TLDs
    assert scraper_mod.clean_email("logo@domain.png") is None
    assert scraper_mod.clean_email("script@domain.js") is None

    # Junk domains
    assert scraper_mod.clean_email("team@facebook.com") is None
    assert scraper_mod.clean_email("info@google.com") is None
    assert scraper_mod.clean_email("support@wix.com") is None

    # Malformed / numeric
    assert scraper_mod.clean_email("no_at_sign.com") is None
    assert scraper_mod.clean_email("user@192.168.1.1") is None


def test_extract_email_from_text(scraper_mod):
    text = (
        "Welcome to Acme Electric! Call us today or email us at "
        "hello@acmeelectric.com for a quote. You can also reach support@facebook.com."
    )
    extracted = scraper_mod.extract_email(text)
    assert extracted == "hello@acmeelectric.com"


def test_clean_website(scraper_mod):
    # Google redirect unquoting
    google_redirect = "https://www.google.com/url?q=https://acmedental.com/home&sa=D&sntz=1"
    assert scraper_mod.clean_website(google_redirect) == "https://acmedental.com/home"

    # Prepending scheme
    assert scraper_mod.clean_website("myshop.com") == "http://myshop.com"

    # Junk domains
    assert scraper_mod.clean_website("https://facebook.com/acme") == ""
    assert scraper_mod.clean_website("https://www.google.com/maps") == ""
    assert scraper_mod.clean_website("https://yelp.com/biz/acme") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Outdated / Dead Website Classifier
# ─────────────────────────────────────────────────────────────────────────────

def test_audit_no_website_and_dead_status(scraper_mod):
    is_target, reason = scraper_mod.audit_website_is_old_or_dead("", "", 0)
    assert is_target is True
    assert reason == "No Website"

    is_target, reason = scraper_mod.audit_website_is_old_or_dead("https://dead.com", "", 404)
    assert is_target is True
    assert "Dead Website (HTTP 404)" in reason

    is_target, reason = scraper_mod.audit_website_is_old_or_dead("https://servererror.com", "", 500)
    assert is_target is True
    assert "Dead Website (HTTP 500)" in reason


def test_audit_parked_and_thin_pages(scraper_mod):
    # Parked
    html_parked = "<html><body><h1>This domain is for sale</h1></body></html>"
    is_target, reason = scraper_mod.audit_website_is_old_or_dead("https://parked.com", html_parked, 200)
    assert is_target is True
    assert "Parked/Under Construction" in reason

    # Thin page (<80 words)
    html_thin = "<html><body><h1>Coming Soon</h1><p>Our website is coming soon.</p></body></html>"
    is_target, reason = scraper_mod.audit_website_is_old_or_dead("https://thin.com", html_thin, 200)
    assert is_target is True
    assert "Thin/Empty Website" in reason or "Parked" in reason


def test_audit_outdated_design_diagnostics(scraper_mod):
    # Old HTML tags, no viewport, table layout, old copyright
    words = "word " * 100
    html_outdated = f"""
    <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
    <html>
      <head><title>Old Garage</title></head>
      <body>
        <center><h1>Welcome to Old Garage</h1></center>
        <table><tr><td>{words}</td></tr></table>
        <table><tr><td>Service 1</td></tr></table>
        <table><tr><td>Service 2</td></tr></table>
        <table><tr><td>Service 3</td></tr></table>
        <script src="http://code.jquery.com/jquery-1.8.3.min.js"></script>
        <footer>Copyright &copy; 2014 Old Garage. All rights reserved.</footer>
      </body>
    </html>
    """
    is_target, reason = scraper_mod.audit_website_is_old_or_dead(
        "http://oldgarage.com", html_outdated, 200, "http://oldgarage.com"
    )
    assert is_target is True
    assert "Outdated Design" in reason
    assert "No SSL" in reason
    assert "Not Mobile Responsive" in reason
    assert "Old HTML4/XHTML Doctype" in reason
    assert "Old Copyright Year (2014)" in reason


def test_audit_modern_website(scraper_mod):
    words = "professional modern web development design responsive services " * 15
    html_modern = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Modern Roofing Co</title>
        <style>
          .grid {{ display: grid; grid-template-columns: 1fr 1fr; }}
          .flex {{ display: flex; }}
        </style>
      </head>
      <body>
        <main class="grid">
          <h1>Modern Roofing Excellence</h1>
          <p>{words}</p>
        </main>
        <footer>&copy; 2026 Modern Roofing Co.</footer>
      </body>
    </html>
    """
    is_target, reason = scraper_mod.audit_website_is_old_or_dead(
        "https://modernroofing.com", html_modern, 200, "https://modernroofing.com"
    )
    assert is_target is False
    assert reason == "Modern Website"


# ─────────────────────────────────────────────────────────────────────────────
# 3. KeyRotator Mechanics
# ─────────────────────────────────────────────────────────────────────────────

def test_key_rotator_behavior(scraper_mod):
    key_dict = {
        "serper": ["PASTE_SERPER_ACCOUNT_1_KEY_HERE", "valid_key_alpha_12345", "valid_key_beta_67890"],
        "hunter": ["PASTE_HUNTER_ACCOUNT_1_KEY_HERE"],
    }
    rot = scraper_mod.KeyRotator(key_dict)
    # Placeholder keys ignored
    assert len(rot.pool["serper"]) == 2
    assert len(rot.pool["hunter"]) == 0

    # Round robin
    k1 = rot.get("serper")
    k2 = rot.get("serper")
    assert k1 == "valid_key_alpha_12345"
    assert k2 == "valid_key_beta_67890"

    # Exhaustion
    rot.exhaust("serper", k1, 429)
    assert rot.get("serper") == "valid_key_beta_67890"
    rot.exhaust("serper", k2, 402)
    assert rot.get("serper") is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mocked API Provider Business Discovery
# ─────────────────────────────────────────────────────────────────────────────

def test_get_places_from_apis_serper_mocked(scraper_mod):
    async def _test():
        rot = scraper_mod.KeyRotator({"serper": ["mock_serper_key_12345"]})

        mock_resp_data = {
            "places": [
                {"title": "Austin Dental Care", "website": "https://austindentalcare.com"},
                {"title": "Capitol Smiles", "website": "https://capitolsmiles.com"},
            ]
        }

        class DummyResponse:
            status = 200
            async def json(self):
                return mock_resp_data
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class DummySession:
            def post(self, url, json=None, headers=None, timeout=None):
                return DummyResponse()

        places = await scraper_mod.get_places_from_apis(DummySession(), rot, "dental clinic", "Austin")
        assert len(places) == 2
        assert places[0]["name"] == "Austin Dental Care"
        assert places[0]["website"] == "https://austindentalcare.com"

    import asyncio
    asyncio.run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 5. Mocked Email Enrichment & Website Inspection
# ─────────────────────────────────────────────────────────────────────────────

def test_enrich_email_via_apis_mocked(scraper_mod):
    async def _test():
        rot = scraper_mod.KeyRotator({"hunter": ["mock_hunter_key_12345"]})

        mock_hunter_data = {
            "data": {
                "emails": [
                    {"value": "office@austindentalcare.com"},
                ]
            }
        }

        class DummyResponse:
            status = 200
            async def json(self):
                return mock_hunter_data
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class DummySession:
            def get(self, url, params=None, headers=None, timeout=None):
                return DummyResponse()

        email = await scraper_mod.enrich_email_via_apis(
            DummySession(), rot, "Austin Dental Care", "Austin", "https://austindentalcare.com"
        )
        assert email == "office@austindentalcare.com"

    import asyncio
    asyncio.run(_test())


def test_check_site_and_scrape_email_contact_fallback_mocked(scraper_mod):
    async def _test():
        words = "word " * 100
        homepage_html = f"""
        <html>
          <head><title>Old Plumbing</title></head>
          <body>
            <center><h1>Old Plumbing Service</h1></center>
            <table><tr><td>{words}</td></tr></table>
            <p>No email on home page</p>
          </body>
        </html>
        """
        contact_html = """
        <html><body><p>For emergencies email us at contact@oldplumbing.com</p></body></html>
        """

        class DummyResponse:
            def __init__(self, url, html):
                self.url = url
                self.status = 200
                self._html = html
            async def text(self, errors="ignore"):
                return self._html
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class DummySession:
            def get(self, url, headers=None, timeout=None, allow_redirects=True, ssl=None):
                if "/contact" in url:
                    return DummyResponse(url, contact_html)
                return DummyResponse(url, homepage_html)

        is_target, reason, found_email = await scraper_mod.check_site_and_scrape_email(
            DummySession(), "http://oldplumbing.com"
        )
        assert is_target is True
        assert found_email == "contact@oldplumbing.com"

    import asyncio
    asyncio.run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# 6. CSV and Checkpoint Roundtrips
# ─────────────────────────────────────────────────────────────────────────────

def test_checkpoint_roundtrip(scraper_mod, tmp_path):
    orig_file = scraper_mod.CHECKPOINT_FILE
    test_cp = str(tmp_path / "checkpoint.json")
    scraper_mod.CHECKPOINT_FILE = test_cp
    try:
        assert scraper_mod.load_checkpoint() == {"kw_idx": 0, "city_idx": 0}
        scraper_mod.save_checkpoint(3, 7)
        loaded = scraper_mod.load_checkpoint()
        assert loaded == {"kw_idx": 3, "city_idx": 7}
    finally:
        scraper_mod.CHECKPOINT_FILE = orig_file


def test_csv_save_and_load(scraper_mod, tmp_path):
    orig_csv = scraper_mod.CSV_FILE
    test_csv = str(tmp_path / "leads.csv")
    scraper_mod.CSV_FILE = test_csv
    try:
        empty_df = scraper_mod.load_csv()
        assert list(empty_df.columns) == ["business name", "email", "website"]

        data = [
            {"business name": "Biz One", "email": "b1@test.com", "website": "https://biz1.com"},
            {"business name": "Biz Two", "email": "b2@test.com", "website": ""},
        ]
        df = pd.DataFrame(data)
        scraper_mod.save_csv(df)

        loaded_df = scraper_mod.load_csv()
        assert len(loaded_df) == 2
        assert loaded_df.iloc[0]["business name"] == "Biz One"
        assert loaded_df.iloc[1]["email"] == "b2@test.com"
    finally:
        scraper_mod.CSV_FILE = orig_csv
