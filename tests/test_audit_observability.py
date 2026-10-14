"""Unit tests verifying audit engine performance observability, crawler page limits,
and factor contract integrity without database or internet requirements.
"""

from __future__ import annotations

import logging
import os
import time
import unittest
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup

# Ensure dummy values so config loads cleanly without live database
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://dummy:dummy@127.0.0.1:5432/leadgen")
os.environ.setdefault("JWT_SECRET", "dummy_secret_for_tests_must_be_32_characters_long_min")

from app.config import Settings, sanitize_crawl_max_pages
from app.engines.audit_engine import _run_audit_sync, _get_crawl_max_pages
from app.engines.factor_contract import load_factor_registry, safe_execute_factor
from auditor.links import audit_broken_links
from auditor.crawler import crawl_site, discover_via_sitemap, HARD_MAX_PAGES, DEFAULT_MAX_PAGES
from auditor.email_finder import find_domain_email
from auditor.technical import audit_ssl
from auditor.core import fetch_page, read_response_text, read_response_bytes
from config import TIMEOUT


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Mock Test Business - High Quality Service</title>
    <meta name="description" content="This is a test meta description that satisfies audit checks and quality guidelines.">
    <link rel="canonical" href="https://mock-test.example/">
    <link rel="icon" href="/favicon.ico">
    <meta property="og:title" content="Mock Test Business">
    <meta property="og:description" content="Mock test description">
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"LocalBusiness","name":"Mock Test Business"}</script>
</head>
<body>
    <header>
        <nav><a href="/about">About Us</a><a href="/contact">Contact</a></nav>
    </header>
    <main>
        <h1>Welcome to Mock Test Business</h1>
        <h2>Quality You Can Trust</h2>
        <p>Contact us at info@mock-test.example or call +1 555-123-4567.</p>
        <p>Our office is located at 123 Main St, Springfield.</p>
        <a href="mailto:info@mock-test.example">Email Us</a>
        <a href="https://facebook.com/mocktest">Facebook</a>
        <a href="https://wa.me/15551234567">WhatsApp</a>
        <a href="/privacy">Privacy Policy</a>
        <a href="/terms">Terms of Service</a>
        <img src="/logo.webp" alt="Company Logo" loading="lazy">
        <a href="/cta" class="btn btn-primary">Get Started</a>
    </main>
</body>
</html>"""


def _build_dummy_page(url: str = "https://mock-test.example") -> dict:
    soup = BeautifulSoup(SAMPLE_HTML, "lxml")
    return {
        "ok": True,
        "url": url,
        "final_url": url,
        "status_code": 200,
        "html": SAMPLE_HTML,
        "soup": soup,
        "headers": {"content-type": "text/html; charset=utf-8", "content-encoding": "gzip"},
        "error": None,
    }


def _build_mock_session():
    mock_s = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_HTML
    mock_resp.url = "https://mock-test.example/"
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_s.get.return_value = mock_resp
    mock_s.head.return_value = mock_resp
    mock_s.headers = {}
    return mock_s


class AuditObservabilityTests(unittest.TestCase):
    def test_sanitize_crawl_max_pages_table(self):
        """Verify centralized crawl max pages policy against exact specification boundary table."""
        cases = [
            (None, 10),
            ("", 10),
            ("invalid", 10),
            ("0", 10),
            (0, 10),
            ("-5", 10),
            (-5, 10),
            ("1", 1),
            (1, 1),
            ("10", 10),
            (10, 10),
            ("25", 25),
            (25, 25),
            ("26", 25),
            (26, 25),
            ("100000", 25),
            (100000, 25),
        ]
        for input_val, expected in cases:
            with self.subTest(input_val=input_val, expected=expected):
                self.assertEqual(sanitize_crawl_max_pages(input_val), expected)

    def test_config_crawl_max_pages_resilience_and_bounds(self):
        """Settings handles malformed/boundary values safely without crashing on startup."""
        base_env = {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "JWT_SECRET": "dummy_secret_for_tests_must_be_32_characters_long_min",
        }
        cases = [
            (None, 10),
            ("", 10),
            ("invalid", 10),
            ("0", 10),
            ("-5", 10),
            ("1", 1),
            ("10", 10),
            ("25", 25),
            ("26", 25),
            ("100000", 25),
        ]
        for env_val, expected in cases:
            env_override = dict(base_env)
            if env_val is not None:
                env_override["CRAWL_MAX_PAGES"] = env_val
            else:
                env_override.pop("CRAWL_MAX_PAGES", None)

            with patch.dict(os.environ, env_override, clear=True):
                # Ensure malformed inputs do not raise ValidationError
                s = Settings()
                self.assertEqual(s.CRAWL_MAX_PAGES, expected, f"Failed for CRAWL_MAX_PAGES={env_val!r}")

    def test_get_crawl_max_pages_resolution_table(self):
        """_get_crawl_max_pages resolves boundary and malformed values safely."""
        cases = [
            (None, 10),
            ("", 10),
            ("invalid", 10),
            ("0", 10),
            ("-5", 10),
            ("1", 1),
            ("10", 10),
            ("25", 25),
            ("26", 25),
            ("100000", 25),
        ]
        for env_val, expected in cases:
            with self.subTest(env_val=env_val, expected=expected):
                with patch.dict(os.environ, {}, clear=False):
                    if env_val is None:
                        os.environ.pop("CRAWL_MAX_PAGES", None)
                    else:
                        os.environ["CRAWL_MAX_PAGES"] = env_val
                    self.assertEqual(_get_crawl_max_pages(), expected)

    @patch("app.engines.audit_engine.make_session")
    @patch("app.engines.audit_engine.crawl_site")
    @patch("app.engines.audit_engine.fetch_page")
    def test_configured_page_limit_reaches_crawler(self, mock_fetch, mock_crawl, mock_make_session):
        """Verify the configured page limit reaches the crawler with strict bounds."""
        dummy_page = _build_dummy_page()
        mock_fetch.return_value = dummy_page
        mock_crawl.return_value = [dummy_page]
        mock_make_session.return_value = _build_mock_session()

        # Case 1: Default configuration (10)
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            os.environ.pop("CRAWL_MAX_PAGES", None)
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example")

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 10)

        # Case 2: Configured via environment within range (5)
        mock_crawl.reset_mock()
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false", "CRAWL_MAX_PAGES": "5"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example")

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 5)

        # Case 3: Excessive environment value clamped to 25
        mock_crawl.reset_mock()
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false", "CRAWL_MAX_PAGES": "100000"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example")

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 25)

        # Case 4: Explicit parameter passed to _run_audit_sync within range
        mock_crawl.reset_mock()
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example", max_pages=3)

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 3)

        # Case 5: Explicit excessive parameter passed to _run_audit_sync clamped to 25
        mock_crawl.reset_mock()
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example", max_pages=100000)

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 25)

        # Case 6: Explicit invalid/negative parameter falls back to 10
        mock_crawl.reset_mock()
        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                _run_audit_sync("https://mock-test.example", max_pages=-5)

        mock_crawl.assert_called()
        self.assertEqual(mock_crawl.call_args.kwargs.get("max_pages"), 10)

    @patch("app.engines.audit_engine.make_session")
    @patch("app.engines.audit_engine.crawl_site")
    @patch("app.engines.audit_engine.fetch_page")
    def test_logs_identify_audit_stages_and_factor_timing(self, mock_fetch, mock_crawl, mock_make_session):
        """Verify logs capture start/completion and durations for all audit stages and factors."""
        dummy_page = _build_dummy_page()
        mock_fetch.return_value = dummy_page
        mock_crawl.return_value = [dummy_page]
        mock_make_session.return_value = _build_mock_session()

        with self.assertLogs("app.engines.audit_engine", level="INFO") as captured_audit:
            with patch.dict(os.environ, {"BROWSER_ENABLED": "false", "CRAWL_MAX_PAGES": "10"}):
                with patch("socket.create_connection", side_effect=OSError("offline")), \
                     patch("ssl.create_default_context", side_effect=OSError("offline")):
                    results = _run_audit_sync("https://mock-test.example")

        log_messages = captured_audit.output

        # 1. Homepage retrieval logs
        self.assertTrue(any("Fetching homepage: https://mock-test.example" in msg for msg in log_messages))
        self.assertTrue(any("Homepage fetched successfully" in msg and "ms" in msg for msg in log_messages))

        # 2. Factor execution start/completion timing logs (name before execution, duration after completion)
        self.assertTrue(any("Starting factor execution" in msg for msg in log_messages))
        self.assertTrue(any("Starting factor: SSL / HTTPS (technical.ssl)" in msg for msg in log_messages))
        self.assertTrue(any("Completed factor: SSL / HTTPS (technical.ssl)" in msg and "ms" in msg for msg in log_messages))
        self.assertTrue(any("Completed factor execution for https://mock-test.example in" in msg for msg in log_messages))

        # 3. Multi-page crawl logs
        self.assertTrue(any("Starting multi-page crawl for https://mock-test.example (max_pages=10)" in msg for msg in log_messages))
        self.assertTrue(any("Completed multi-page crawl for https://mock-test.example in" in msg and "ms" in msg for msg in log_messages))

        # 4. Email discovery logs
        self.assertTrue(any("Starting domain email discovery for https://mock-test.example" in msg for msg in log_messages))
        self.assertTrue(any("Completed domain email discovery for https://mock-test.example in" in msg and "ms" in msg for msg in log_messages))

        # 5. Factor contract remains intact: all 62 factors across 11 groups
        self.assertIn("audit_results", results)
        total_factors = sum(len(group) for group in results["audit_results"].values())
        self.assertEqual(total_factors, 62)
        self.assertEqual(len(results["audit_results"]), 11)
        self.assertIn("score", results)
        self.assertIsInstance(results["score"], int)
        self.assertEqual(results["lifecycle"], "COMPLETE")

    @patch("app.engines.audit_engine.make_session")
    @patch("app.engines.audit_engine.crawl_site")
    @patch("app.engines.audit_engine.fetch_page")
    def test_canonical_62_factor_contract_preserved(self, mock_fetch, mock_crawl, mock_make_session):
        """Verify the canonical 62-factor contract is preserved in structure, count, and duration reporting."""
        dummy_page = _build_dummy_page()
        mock_fetch.return_value = dummy_page
        mock_crawl.return_value = [dummy_page]
        mock_make_session.return_value = _build_mock_session()

        registry = load_factor_registry()
        expected_factor_ids = {f["id"] for f in registry["factors"]}
        self.assertEqual(len(expected_factor_ids), 62)

        with patch.dict(os.environ, {"BROWSER_ENABLED": "false"}):
            with patch("socket.create_connection", side_effect=OSError("offline")), \
                 patch("ssl.create_default_context", side_effect=OSError("offline")):
                results = _run_audit_sync("https://mock-test.example")

        actual_factor_ids = set()
        for group_name, group_factors in results["audit_results"].items():
            for factor_key, factor_data in group_factors.items():
                self.assertIn("id", factor_data)
                self.assertIn("status", factor_data)
                self.assertIn("score", factor_data)
                self.assertIn("duration_ms", factor_data)
                self.assertGreaterEqual(factor_data["duration_ms"], 0)
                actual_factor_ids.add(factor_data["id"])

        self.assertEqual(actual_factor_ids, expected_factor_ids)
        self.assertEqual(len(actual_factor_ids), 62)

    def test_factor_contract_safe_execute_timing_logs(self):
        """safe_execute_factor logs factor name immediately before execution and duration after completion."""
        factor = {"id": "technical.ssl", "name": "SSL / HTTPS", "value_type": "boolean", "score_weight": 10}
        with self.assertLogs("app.engines.factor_contract", level="INFO") as captured:
            result = safe_execute_factor(factor, lambda: {"status": "PASS", "value": True, "message": "Valid SSL"}, "https://mock.example")

        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result["duration_ms"], 0)
        logs = captured.output
        self.assertTrue(any("Executing audit factor: SSL / HTTPS (technical.ssl)" in m for m in logs))
        self.assertTrue(any("Completed audit factor: SSL / HTTPS (technical.ssl) in" in m and "ms" in m for m in logs))

    def test_broken_links_checker_timing_logs(self):
        """audit_broken_links logs start and completion timing."""
        soup = BeautifulSoup("<html><body><a href='/local-page'>Local</a></body></html>", "lxml")
        session = _build_mock_session()

        with self.assertLogs("auditor.links", level="INFO") as captured:
            res = audit_broken_links(soup, "https://mock-test.example", session)

        self.assertIn("status", res)
        logs = captured.output
        self.assertTrue(any("Starting broken link check for https://mock-test.example" in m for m in logs))
        self.assertTrue(any("Completed broken link check for https://mock-test.example in" in m and "ms" in m for m in logs))

    @patch("auditor.crawler.discover_via_sitemap", return_value=[])
    @patch("auditor.crawler.fetch_page")
    def test_crawler_timing_logs(self, mock_fetch, mock_sitemap):
        """crawl_site logs start and completion timing with page count."""
        dummy_page = _build_dummy_page()
        mock_fetch.return_value = dummy_page
        session = _build_mock_session()

        with self.assertLogs("auditor.crawler", level="INFO") as captured:
            pages = crawl_site("https://mock-test.example", session, max_pages=3)

        self.assertGreaterEqual(len(pages), 1)
        logs = captured.output
        self.assertTrue(any("Starting crawl for https://mock-test.example (max_pages=3)" in m for m in logs))
        self.assertTrue(any("Completed crawl for https://mock-test.example in" in m and "ms" in m for m in logs))

    def test_email_finder_timing_logs(self):
        """find_domain_email logs start and completion timing."""
        soup = BeautifulSoup("<html><body><a href='mailto:info@mock-test.example'>Email</a></body></html>", "lxml")
        session = _build_mock_session()

        with self.assertLogs("auditor.email_finder", level="INFO") as captured:
            email, source = find_domain_email("https://mock-test.example", soup, str(soup), session)

        self.assertEqual(email, "info@mock-test.example")
        self.assertEqual(source, "homepage_mailto")
        logs = captured.output
        self.assertTrue(any("Starting email discovery for https://mock-test.example" in m for m in logs))
        self.assertTrue(any("Found via homepage mailto in" in m and "ms" in m for m in logs))

    @patch("socket.create_connection")
    def test_audit_ssl_uses_socket_timeout_on_stall(self, mock_connect):
        """audit_ssl enforces explicit timeout on socket connect and recovers cleanly when stalled."""
        mock_connect.side_effect = TimeoutError("Connection timed out")
        session = _build_mock_session()
        res = audit_ssl("https://stalled-host.example", session)
        self.assertEqual(res["status"], "WARN")
        self.assertIn("Could not verify SSL", res["message"])
        mock_connect.assert_called_once_with(("stalled-host.example", 443), timeout=TIMEOUT)

    def test_audit_broken_links_bounds_timeout_and_closes_stream(self):
        """audit_broken_links uses bounded LINK_TIMEOUT (<= 5s) and closes response streams."""
        soup = BeautifulSoup("<html><body><a href='https://link1.example'>L1</a></body></html>", "lxml")
        session = MagicMock()
        session.head.side_effect = TimeoutError("HEAD timed out")

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.url = "https://link1.example"
        mock_get_resp.__enter__.return_value = mock_get_resp
        mock_get_resp.__exit__.return_value = False
        session.get.return_value = mock_get_resp

        res = audit_broken_links(soup, "https://mock-test.example", session)
        self.assertIn("status", res)

        # Verify head check used bounded timeout <= 5
        session.head.assert_called_once()
        head_call_kwargs = session.head.call_args.kwargs
        self.assertLessEqual(head_call_kwargs.get("timeout"), 5)

        # Verify get fallback check used bounded timeout <= 5 and closed context
        session.get.assert_called_once()
        get_call_kwargs = session.get.call_args.kwargs
        self.assertLessEqual(get_call_kwargs.get("timeout"), 5)
        mock_get_resp.__enter__.assert_called_once()
        mock_get_resp.__exit__.assert_called_once()

    def test_sitemap_discovery_bounds_recursion_on_wide_index(self):
        """discover_via_sitemap stops child sitemap fetching after MAX_SITEMAPS_TO_FETCH (5)."""
        session = MagicMock()
        robots_resp = MagicMock(status_code=404, text="")

        # Build sitemapindex with 25 child sitemaps
        child_locs = "".join(f"<sitemap><loc>https://mock-test.example/child-{i}.xml</loc></sitemap>" for i in range(25))
        index_xml = f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{child_locs}</sitemapindex>'
        index_resp = MagicMock(status_code=200, text=index_xml)

        child_xml = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://mock-test.example/page-1</loc></url></urlset>'
        child_resp = MagicMock(status_code=200, text=child_xml)

        for m in (robots_resp, index_resp, child_resp):
            m.__enter__.return_value = m
            m.__exit__.return_value = False

        def get_mock(url, timeout=None, stream=False):
            if "robots.txt" in url:
                return robots_resp
            if "sitemap.xml" in url or "sitemap_index.xml" in url:
                return index_resp
            return child_resp

        session.get.side_effect = get_mock

        urls = discover_via_sitemap("https://mock-test.example", session)
        self.assertGreater(len(urls), 0)
        # Verify total sitemap calls is bounded to <= 5 children
        child_fetches = [call for call in session.get.call_args_list if "child-" in call.args[0]]
        self.assertLessEqual(len(child_fetches), 5)

    @patch("auditor.crawler.discover_via_sitemap", return_value=[])
    @patch("auditor.crawler.fetch_page")
    def test_crawler_enforces_hard_max_pages_and_bounds_batch(self, mock_fetch, mock_sitemap):
        """crawl_site enforces HARD_MAX_PAGES cap of 25 even when fixture has >25 unique internal pages."""
        def dynamic_fetch(url, session):
            # Provide >25 unique eligible internal links across crawled pages
            links = "".join(f'<a href="/page-{i}">Page {i}</a>' for i in range(1, 55))
            html = f"<html><body>{links}</body></html>"
            soup = BeautifulSoup(html, "lxml")
            return {
                "ok": True,
                "url": url,
                "final_url": url,
                "status_code": 200,
                "html": html,
                "soup": soup,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "error": None,
            }

        mock_fetch.side_effect = dynamic_fetch
        session = _build_mock_session()

        pages = crawl_site("https://mock-test.example", session, max_pages=100)
        self.assertEqual(len(pages), HARD_MAX_PAGES)
        self.assertLessEqual(len(pages), 25)

    @patch("app.engines.audit_engine.make_session")
    @patch("app.engines.audit_engine.crawl_site")
    @patch("app.engines.audit_engine.fetch_page")
    def test_factor_timeout_error_isolation_preserves_contract(self, mock_fetch, mock_crawl, mock_make_session):
        """A timeout error in an individual factor does not abort sibling factors or break 62-factor contract."""
        dummy_page = _build_dummy_page()
        mock_fetch.return_value = dummy_page
        mock_crawl.return_value = [dummy_page]
        mock_make_session.return_value = _build_mock_session()

        with patch("app.engines.audit_engine.audit_ssl", side_effect=TimeoutError("socket timed out")):
            results = _run_audit_sync("https://mock-test.example")

        # Verify SSL factor isolated as ERROR
        ssl_res = results["audit_results"]["technical"]["ssl"]
        self.assertEqual(ssl_res["status"], "ERROR")
        self.assertEqual(ssl_res["score"], 0)
        self.assertIn("TimeoutError", ssl_res["error"])

        # Verify all 62 factors remain present and lifecycle is COMPLETE
        total_factors = sum(len(group) for group in results["audit_results"].values())
        self.assertEqual(total_factors, 62)
        self.assertIsInstance(results["score"], int)
        self.assertEqual(results["lifecycle"], "COMPLETE")

    def test_read_response_text_bounds_oversized_stream(self):
        """read_response_text stops reading and strictly slices when accumulated bytes reach max_bytes."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"A" * 102400 for _ in range(10)]
        mock_resp.encoding = "utf-8"
        res = read_response_text(mock_resp, max_bytes=250000)
        self.assertEqual(len(res), 250000)
        self.assertTrue(getattr(res, "is_truncated", False))
        self.assertTrue(getattr(mock_resp, "is_truncated", False))

    def test_read_response_bytes_bounds_oversized_stream(self):
        """read_response_bytes strictly bounds accumulated bytes to max_bytes before retaining."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"B" * 10000 for _ in range(5)]
        res = read_response_bytes(mock_resp, max_bytes=25000)
        self.assertEqual(len(res), 25000)
        self.assertTrue(getattr(res, "is_truncated", False))

    def test_read_response_text_bounds_elapsed_time_on_trickle(self):
        """read_response_text breaks out of consumption loop when max_elapsed budget is reached."""
        mock_resp = MagicMock()
        def slow_generator():
            for _ in range(10):
                time.sleep(0.04)
                yield b"chunk"
        mock_resp.iter_content.return_value = slow_generator()
        mock_resp.encoding = "utf-8"
        start = time.perf_counter()
        res = read_response_text(mock_resp, max_bytes=1000000, max_elapsed=0.08)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.35)
        self.assertLess(len(res), 50)
        self.assertTrue(getattr(res, "is_timed_out", False))

    def test_fetch_page_uses_streaming_context_and_closes_stream(self):
        """fetch_page consumes response via stream context manager and guarantees close."""
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://mock-test.example"
        mock_resp.iter_content.return_value = [b"<html><body><h1>Title</h1></body></html>"]
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.encoding = "utf-8"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        session.get.return_value = mock_resp

        result = fetch_page("https://mock-test.example", session)
        self.assertTrue(result["ok"])
        self.assertIn("Title", result["html"])
        session.get.assert_called_once_with(
            "https://mock-test.example",
            timeout=TIMEOUT,
            allow_redirects=True,
            verify=False,
            stream=True,
        )
        mock_resp.__enter__.assert_called_once()
        mock_resp.__exit__.assert_called_once()

    def test_fetch_page_closes_stream_on_read_exception(self):
        """fetch_page guarantees response stream closure even when reading raises an exception."""
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://mock-test.example"
        import requests.exceptions
        mock_resp.iter_content.side_effect = requests.exceptions.ChunkedEncodingError("Stream broken")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        session.get.return_value = mock_resp

        result = fetch_page("https://mock-test.example", session)
        mock_resp.__enter__.assert_called_once()
        mock_resp.__exit__.assert_called_once()

    def test_audit_robots_streams_and_bounds_response(self):
        """audit_robots streams robots.txt with finite timeout and closes stream context."""
        session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"User-agent: *\nDisallow: /admin\n"]
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.encoding = "utf-8"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        session.get.return_value = mock_resp

        from auditor.technical import audit_robots
        res = audit_robots("https://mock-test.example", session)
        self.assertEqual(res["status"], "PASS")
        session.get.assert_called_once()
        call_kwargs = session.get.call_args.kwargs
        self.assertTrue(call_kwargs.get("stream"))
        self.assertLessEqual(call_kwargs.get("timeout"), 5)
        mock_resp.__enter__.assert_called_once()
        mock_resp.__exit__.assert_called_once()
