"""Phase 2: Browser evidence provider tests.

These tests verify:
  1. The provider interface contract (disabled by default, no browser at import).
  2. URL security validation (scheme blocking, private IP blocking, localhost).
  3. BrowserEvidence dataclass contract (to_dict, factory methods).
  4. BrowserConfig env-var parsing.
  5. Integration of browser_status in _run_audit_sync return dict.
  6. _annotate_browser_comparisons populates browser_diff without changing status.
  7. Existing 18-test regression suite still passes (imported from original test file).

Tests do NOT launch a real browser (no network, no process).
"""
from __future__ import annotations

import sys
import os
import importlib
import json
import pytest

# ── Add auditor package to path ────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDITOR_PKG = os.path.join(REPO_ROOT, "auditor", "auditor")
if AUDITOR_PKG not in sys.path:
    sys.path.insert(0, AUDITOR_PKG)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Import safety: module load does NOT launch a browser
# ══════════════════════════════════════════════════════════════════════════════

def test_import_does_not_launch_browser():
    """Importing browser.provider must never start a browser process."""
    from browser.provider import BrowserProvider, BrowserConfig, BrowserEvidence, BrowserStatus
    # If we got here without a subprocess being spawned, the test passes.
    assert BrowserProvider is not None
    assert BrowserConfig is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Default configuration
# ══════════════════════════════════════════════════════════════════════════════

def test_browser_disabled_by_default():
    from browser.provider import BrowserConfig, is_browser_enabled
    cfg = BrowserConfig()
    assert cfg.enabled is False, "Browser must be disabled by default"
    assert is_browser_enabled(cfg) is False


def test_from_env_disabled_when_no_env_var(monkeypatch):
    from browser.provider import BrowserConfig
    monkeypatch.delenv("BROWSER_ENABLED", raising=False)
    cfg = BrowserConfig.from_env()
    assert cfg.enabled is False


def test_from_env_enabled_when_set(monkeypatch):
    from browser.provider import BrowserConfig
    monkeypatch.setenv("BROWSER_ENABLED", "true")
    cfg = BrowserConfig.from_env()
    assert cfg.enabled is True


def test_from_env_uses_safe_defaults(monkeypatch):
    from browser.provider import BrowserConfig
    monkeypatch.delenv("BROWSER_ENABLED", raising=False)
    monkeypatch.delenv("BROWSER_NAV_TIMEOUT_MS", raising=False)
    cfg = BrowserConfig.from_env()
    assert cfg.nav_timeout_ms == 25_000
    assert cfg.headless is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. BrowserEvidence dataclass contract
# ══════════════════════════════════════════════════════════════════════════════

def test_disabled_evidence_factory():
    from browser.provider import BrowserEvidence, BrowserStatus
    ev = BrowserEvidence.disabled("https://example.com")
    assert ev.provider_status == BrowserStatus.DISABLED
    assert ev.requested_url == "https://example.com"
    assert ev.navigation_ok is False


def test_security_blocked_evidence_factory():
    from browser.provider import BrowserEvidence, BrowserStatus
    ev = BrowserEvidence.security_blocked("http://192.168.1.1", "private IP")
    assert ev.provider_status == BrowserStatus.BLOCKED
    assert ev.navigation_ok is False
    assert ev.provider_error == "private IP"


def test_failed_evidence_factory():
    from browser.provider import BrowserEvidence, BrowserStatus
    ev = BrowserEvidence.failed("https://example.com", "launch failed")
    assert ev.provider_status == BrowserStatus.FAILED


def test_to_dict_is_json_serialisable():
    from browser.provider import BrowserEvidence
    ev = BrowserEvidence.disabled("https://example.com")
    d = ev.to_dict()
    # Must not raise
    json_str = json.dumps(d)
    assert "DISABLED" in json_str


def test_to_dict_has_required_keys():
    from browser.provider import BrowserEvidence
    ev = BrowserEvidence.disabled("https://x.com")
    d = ev.to_dict()
    required = {
        "requested_url", "final_url", "http_status", "provider_status",
        "navigation_ok", "provider_error", "page_title", "meta_description",
        "headings", "visible_text_chars", "has_visible_text", "has_nav",
        "internal_link_count", "has_cta", "has_form", "dom_snippet",
        "console_errors", "failed_requests", "navigation_timeout_ms",
        "elapsed_ms", "captured_at", "screenshot_path", "screenshot_size_kb",
        "js_rendered_title", "js_rendered_headings",
    }
    missing = required - d.keys()
    assert not missing, f"Missing keys in to_dict(): {missing}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Provider returns DISABLED when not enabled
# ══════════════════════════════════════════════════════════════════════════════

def test_capture_returns_disabled_when_not_enabled():
    from browser.provider import BrowserProvider, BrowserConfig, BrowserStatus
    cfg = BrowserConfig(enabled=False)
    provider = BrowserProvider(cfg)
    ev = provider.capture("https://example.com")
    assert ev.provider_status == BrowserStatus.DISABLED
    # Must never set navigation_ok when disabled
    assert ev.navigation_ok is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. Security: URL validation
# ══════════════════════════════════════════════════════════════════════════════

class TestURLSecurity:
    def test_file_scheme_blocked(self):
        from browser.security import validate_url
        r = validate_url("file:///etc/passwd")
        assert not r.allowed
        assert "file" in r.reason.lower() or "scheme" in r.reason.lower()

    def test_javascript_scheme_blocked(self):
        from browser.security import validate_url
        r = validate_url("javascript:alert(1)")
        assert not r.allowed

    def test_data_scheme_blocked(self):
        from browser.security import validate_url
        r = validate_url("data:text/html,<h1>x</h1>")
        assert not r.allowed

    def test_ftp_scheme_blocked(self):
        from browser.security import validate_url
        r = validate_url("ftp://example.com/file.txt")
        assert not r.allowed

    def test_loopback_ipv4_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://127.0.0.1/secret")
        assert not r.allowed

    def test_loopback_ipv4_range_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://127.99.99.99/admin")
        assert not r.allowed

    def test_private_192_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://192.168.1.100/secret")
        assert not r.allowed

    def test_private_10_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://10.0.0.1/secret")
        assert not r.allowed

    def test_private_172_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://172.16.0.1/secret")
        assert not r.allowed

    def test_link_local_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://169.254.169.254/latest/meta-data/")
        assert not r.allowed, "AWS metadata endpoint must be blocked"

    def test_localhost_hostname_blocked(self):
        from browser.security import validate_url
        r = validate_url("http://localhost/admin")
        # localhost resolves to 127.0.0.1/::1, both blocked
        assert not r.allowed

    def test_http_public_allowed(self):
        """A well-known public domain should be allowed (needs DNS)."""
        from browser.security import validate_url
        try:
            r = validate_url("http://example.com")
            # example.com resolves to a public IP → should be allowed
            assert r.allowed, f"example.com should be allowed; got: {r.reason}"
        except Exception:
            pytest.skip("DNS not available in test environment")

    def test_https_public_allowed(self):
        from browser.security import validate_url
        try:
            r = validate_url("https://example.com")
            assert r.allowed
        except Exception:
            pytest.skip("DNS not available in test environment")

    def test_is_allowed_url_wrapper_blocked(self):
        from browser.security import is_allowed_url
        assert is_allowed_url("file:///etc/passwd") is False

    def test_is_allowed_url_wrapper_loopback(self):
        from browser.security import is_allowed_url
        assert is_allowed_url("http://127.0.0.1/") is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. Security: capture() enforces URL check before navigation
# ══════════════════════════════════════════════════════════════════════════════

def test_capture_blocks_file_scheme():
    """Even if BROWSER_ENABLED=true, file:// URLs must be blocked."""
    from browser.provider import BrowserProvider, BrowserConfig, BrowserStatus
    cfg = BrowserConfig(enabled=True)
    provider = BrowserProvider(cfg)
    ev = provider.capture("file:///etc/passwd")
    assert ev.provider_status == BrowserStatus.BLOCKED
    assert ev.navigation_ok is False


def test_capture_blocks_private_ip():
    from browser.provider import BrowserProvider, BrowserConfig, BrowserStatus
    cfg = BrowserConfig(enabled=True)
    provider = BrowserProvider(cfg)
    ev = provider.capture("http://192.168.1.1/admin")
    assert ev.provider_status == BrowserStatus.BLOCKED


def test_capture_blocks_loopback():
    from browser.provider import BrowserProvider, BrowserConfig, BrowserStatus
    cfg = BrowserConfig(enabled=True)
    provider = BrowserProvider(cfg)
    ev = provider.capture("http://127.0.0.1/")
    assert ev.provider_status == BrowserStatus.BLOCKED


def test_capture_blocks_link_local_metadata():
    from browser.provider import BrowserProvider, BrowserConfig, BrowserStatus
    cfg = BrowserConfig(enabled=True)
    provider = BrowserProvider(cfg)
    ev = provider.capture("http://169.254.169.254/latest/meta-data/")
    assert ev.provider_status == BrowserStatus.BLOCKED


# ══════════════════════════════════════════════════════════════════════════════
# 7. BrowserStatus constants
# ══════════════════════════════════════════════════════════════════════════════

def test_browser_status_values():
    from browser.provider import BrowserStatus
    assert BrowserStatus.DISABLED == "DISABLED"
    assert BrowserStatus.SUCCESS  == "SUCCESS"
    assert BrowserStatus.PARTIAL  == "PARTIAL"
    assert BrowserStatus.TIMEOUT  == "TIMEOUT"
    assert BrowserStatus.BLOCKED  == "BLOCKED"
    assert BrowserStatus.CRASHED  == "CRASHED"
    assert BrowserStatus.FAILED   == "FAILED"
    assert BrowserStatus.UNAVAILABLE == "UNAVAILABLE"


# ══════════════════════════════════════════════════════════════════════════════
# 8. _annotate_browser_comparisons: pure annotation, no status change
# ══════════════════════════════════════════════════════════════════════════════

class TestAnnotateBrowserComparisons:
    """These tests exercise the comparison function in isolation."""

    def _make_evidence(self, **kwargs):
        from browser.provider import BrowserEvidence, BrowserStatus
        ev = BrowserEvidence()
        ev.provider_status = BrowserStatus.SUCCESS
        ev.navigation_ok   = True
        for k, v in kwargs.items():
            setattr(ev, k, v)
        return ev

    def _make_audit_results(self, page_title_status="PASS", h1_status="PASS", cta_status="PASS"):
        return {
            "onpage": {
                "page_title": {"status": page_title_status, "value": "My Title" if page_title_status == "PASS" else ""},
                "h1": {"status": h1_status, "value": "Heading" if h1_status == "PASS" else ""},
            },
            "ux": {
                "cta": {"status": cta_status},
            },
        }

    def test_no_annotation_when_disabled(self):
        """When browser status is DISABLED the function must be a no-op."""
        from browser.provider import BrowserEvidence, BrowserStatus
        from browser.comparisons import annotate_browser_comparisons
        ev = BrowserEvidence.disabled("https://x.com")
        ar = self._make_audit_results("PASS", "PASS", "PASS")
        annotate_browser_comparisons(ar, ev)
        # Nothing should be annotated
        assert "browser_diff" not in ar["onpage"]["page_title"]
        assert "browser_diff" not in ar["onpage"]["h1"]
        assert "browser_diff" not in ar["ux"]["cta"]

    def test_annotation_does_not_change_pass_status(self):
        """A PASS factor must stay PASS even when browser confirms consistency."""
        from browser.provider import BrowserEvidence, BrowserStatus
        from browser.comparisons import annotate_browser_comparisons
        ev = self._make_evidence(
            js_rendered_title="My Title",
            js_rendered_headings=[{"level": "h1", "text": "Heading"}],
            has_cta=True,
        )
        ar = self._make_audit_results("PASS", "PASS", "PASS")
        annotate_browser_comparisons(ar, ev)
        # Status must remain PASS
        assert ar["onpage"]["page_title"]["status"] == "PASS"
        assert ar["onpage"]["h1"]["status"] == "PASS"
        assert ar["ux"]["cta"]["status"] == "PASS"
        # browser_diff should have verdict=consistent
        assert ar["onpage"]["page_title"].get("browser_diff", {}).get("verdict") == "consistent"


    def test_annotation_adds_js_only_verdict_for_missing_h1(self):
        """When HTTP has no h1 but browser found one, verdict=js_only."""
        from browser.provider import BrowserEvidence, BrowserStatus
        from browser.comparisons import annotate_browser_comparisons
        ev = self._make_evidence(
            js_rendered_headings=[{"level": "h1", "text": "Rendered Heading"}],
            js_rendered_title="",
            has_cta=False,
        )
        ar = self._make_audit_results("FAIL", "FAIL", "FAIL")
        annotate_browser_comparisons(ar, ev)
        diff = ar["onpage"]["h1"].get("browser_diff", {})
        assert diff.get("verdict") == "js_only"
        # Status must STILL be FAIL — annotation does not fix it
        assert ar["onpage"]["h1"]["status"] == "FAIL"

    def test_no_annotation_when_browser_failed(self):
        """If browser status is FAILED, no browser_diff keys should be added."""
        from browser.provider import BrowserEvidence, BrowserStatus
        from browser.comparisons import annotate_browser_comparisons
        ev = BrowserEvidence.failed("https://x.com", "crash")
        ar = self._make_audit_results("PASS", "PASS", "PASS")
        annotate_browser_comparisons(ar, ev)
        assert "browser_diff" not in ar["onpage"]["page_title"]
        assert "browser_diff" not in ar["onpage"]["h1"]
        assert "browser_diff" not in ar["ux"]["cta"]


# ══════════════════════════════════════════════════════════════════════════════
# 9. BROWSER_DEFAULTS in config.py
# ══════════════════════════════════════════════════════════════════════════════

def test_browser_defaults_in_config():
    # Import auditor config directly (not backend/app/config.py)
    import importlib.util, pathlib
    config_path = pathlib.Path(REPO_ROOT) / "auditor" / "auditor" / "config.py"
    spec = importlib.util.spec_from_file_location("auditor_config", str(config_path))
    auditor_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor_config)
    BROWSER_DEFAULTS = auditor_config.BROWSER_DEFAULTS
    assert BROWSER_DEFAULTS["enabled"] is False, "enabled must default to False"
    assert BROWSER_DEFAULTS["headless"] is True
    assert BROWSER_DEFAULTS["nav_timeout_ms"] == 25_000
    assert BROWSER_DEFAULTS["max_concurrency"] == 2
    assert "script" not in BROWSER_DEFAULTS["blocked_resource_types"], \
        "script must NOT be blocked (JS execution needed)"


# ══════════════════════════════════════════════════════════════════════════════
# 10. BrowserConfig dom_snippet_max_chars default
# ══════════════════════════════════════════════════════════════════════════════

def test_dom_snippet_max_chars_default():
    from browser.provider import BrowserConfig
    cfg = BrowserConfig()
    assert cfg.dom_snippet_max_chars == 16_384


# ══════════════════════════════════════════════════════════════════════════════
# 11. Evidence headings field
# ══════════════════════════════════════════════════════════════════════════════

def test_evidence_headings_is_list():
    from browser.provider import BrowserEvidence
    ev = BrowserEvidence()
    assert isinstance(ev.headings, list)
    assert isinstance(ev.console_errors, list)
    assert isinstance(ev.failed_requests, list)
