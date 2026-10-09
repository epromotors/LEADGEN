"""Patch script for Phase 2: inject browser evidence provider into audit_engine.py.
Run from project root: python scripts/_phase2_patch_engine.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "backend" / "app" / "engines" / "audit_engine.py"

src = ENGINE.read_bytes().decode("utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1: Add browser module import after `from uuid import UUID`
# ─────────────────────────────────────────────────────────────────────────────
BROWSER_IMPORT = '''
# ── Phase 2: browser provider (lazy import — safe to load without a browser) ──
# Importing the module does NOT launch a browser; the browser only launches
# when BrowserConfig.enabled=True and BrowserProvider.capture() is called.
try:
    from browser.provider import BrowserProvider, BrowserConfig, BrowserEvidence, BrowserStatus
    from browser.security import validate_url as _browser_validate_url
    _BROWSER_MODULE_AVAILABLE = True
except ImportError:
    _BROWSER_MODULE_AVAILABLE = False
'''

# Insert immediately after `from uuid import UUID\n`
if "_BROWSER_MODULE_AVAILABLE" not in src:
    src = re.sub(
        r'(from uuid import UUID\r?\n)',
        lambda m: m.group(0) + BROWSER_IMPORT,
        src,
        count=1,
    )
    print("PATCH 1: browser import added")
else:
    print("PATCH 1: already present, skipped")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2: Add browser capture at the end of _run_audit_sync, before `return {`
# ─────────────────────────────────────────────────────────────────────────────
BROWSER_CAPTURE_BLOCK = '''
    # ── Phase 2: browser evidence capture ──────────────────────────────────────
    # Runs only when BROWSER_ENABLED=true is set.  A browser failure NEVER
    # aborts the HTTP audit or affects the 62 factor results.  Evidence is
    # stored in the return payload for the API and frontend to consume.
    browser_evidence: dict = {}
    browser_status: str = "DISABLED"
    try:
        if _BROWSER_MODULE_AVAILABLE:
            _bcfg = BrowserConfig.from_env()
            if _bcfg.enabled:
                _provider = BrowserProvider(_bcfg)
                _bev = _provider.capture(url)
                browser_evidence = _bev.to_dict()
                browser_status   = _bev.provider_status
                import logging as _log
                _log.getLogger(__name__).info(
                    "[audit_engine] Browser evidence status=%s elapsed=%d ms for %s",
                    browser_status, _bev.elapsed_ms, url,
                )
                # Annotate select factors with raw-vs-rendered differences.
                _annotate_browser_comparisons(audit_results, _bev)
            else:
                browser_status = "DISABLED"
        else:
            browser_status = "UNAVAILABLE"
    except Exception as _bexc:
        browser_status   = "ERROR"
        browser_evidence = {"provider_status": "ERROR", "provider_error": str(_bexc)}
        import logging as _log
        _log.getLogger(__name__).exception(
            "[audit_engine] Browser evidence capture failed for %s", url
        )
'''

RETURN_MARKER = '    return {\r\n        "audit_results": audit_results,'
RETURN_MARKER_LF = '    return {\n        "audit_results": audit_results,'

if "browser_evidence" not in src:
    # try CRLF first, then LF
    for marker in (RETURN_MARKER, RETURN_MARKER_LF):
        if marker in src:
            # Replace the marker with browser capture + original marker
            # We need to add browser_evidence to the return dict too
            OLD_RETURN = marker.rstrip() 
            break
    else:
        print("PATCH 2: return marker not found — skipping")
        OLD_RETURN = None

    if OLD_RETURN is not None:
        # We will replace the entire return dict to add browser_evidence
        old_return_block_crlf = (
            '    return {\r\n'
            '        "audit_results": audit_results,\r\n'
            '        "score": score,\r\n'
            '        "site_summary": site_summary,\r\n'
            '        "page_audits": page_audits,\r\n'
            '        "crawl_coverage": crawl_coverage,\r\n'
            '        "lifecycle": determine_lifecycle(homepage_ok=True, crawl_status=crawl_coverage["status"]),\r\n'
            '        "html": html,\r\n'
            '        "found_email":  found_email,\r\n'
            '        "email_source": email_source,\r\n'
            '    }'
        )
        old_return_block_lf = old_return_block_crlf.replace('\r\n', '\n')

        new_return_block = (
            BROWSER_CAPTURE_BLOCK +
            '\n    return {\n'
            '        "audit_results": audit_results,\n'
            '        "score": score,\n'
            '        "site_summary": site_summary,\n'
            '        "page_audits": page_audits,\n'
            '        "crawl_coverage": crawl_coverage,\n'
            '        "lifecycle": determine_lifecycle(homepage_ok=True, crawl_status=crawl_coverage["status"]),\n'
            '        "html": html,\n'
            '        "found_email":  found_email,\n'
            '        "email_source": email_source,\n'
            '        "browser_evidence": browser_evidence,\n'
            '        "browser_status":   browser_status,\n'
            '    }'
        )

        replaced = False
        for old_block in (old_return_block_crlf, old_return_block_lf):
            if old_block in src:
                src = src.replace(old_block, new_return_block, 1)
                replaced = True
                print("PATCH 2: return dict updated with browser_evidence")
                break
        if not replaced:
            print("PATCH 2: return block not matched exactly — manual edit needed")
else:
    print("PATCH 2: browser_evidence already in source, skipped")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3: Add _annotate_browser_comparisons() function after _compute_score()
# ─────────────────────────────────────────────────────────────────────────────
ANNOTATE_FUNC = '''

def _annotate_browser_comparisons(audit_results: dict, bev) -> None:
    """Attach raw-vs-rendered comparison metadata to selected factor results.

    This only ANNOTATES; it does NOT change any factor status or score.
    Consuming code (frontend, API) can read the browser_diff field.

    Factors annotated in Phase 2:
      - onpage.page_title  (JS may change the title after load)
      - onpage.h1          (JS-rendered frameworks may inject headings)
      - ux.cta             (CTAs may be injected by JavaScript)

    Rules:
      - DISABLED, BLOCKED, or FAILED browser status => no annotation.
      - A browser failure does NOT convert a PASS into a FAIL.
    """
    if not bev or bev.provider_status not in ("SUCCESS", "PARTIAL"):
        return

    def _tag(group: str, key: str, diff: dict) -> None:
        result = audit_results.get(group, {}).get(key)
        if isinstance(result, dict):
            result["browser_diff"] = diff

    # 1. Page title
    http_title_value = audit_results.get("onpage", {}).get("page_title", {}).get("value", "")
    rendered_title   = bev.js_rendered_title or ""
    if rendered_title:
        if not (http_title_value or "").strip() and rendered_title.strip():
            _tag("onpage", "page_title", {
                "verdict": "js_only",
                "note": "Title absent in raw HTTP but present in browser-rendered DOM.",
                "rendered_value": rendered_title[:200],
            })
        else:
            _tag("onpage", "page_title", {"verdict": "consistent", "rendered_value": rendered_title[:200]})

    # 2. H1 heading
    http_h1_ok   = audit_results.get("onpage", {}).get("h1", {}).get("status") == "PASS"
    rendered_h1s = [h for h in (bev.js_rendered_headings or []) if h.get("level") == "h1"]
    if rendered_h1s:
        verdict = "consistent" if http_h1_ok else "js_only"
        diff = {"verdict": verdict, "rendered_h1s": [h["text"][:200] for h in rendered_h1s[:3]]}
        if verdict == "js_only":
            diff["note"] = "H1 absent in raw HTTP but found in browser-rendered DOM."
        _tag("onpage", "h1", diff)

    # 3. CTA
    http_cta_ok  = audit_results.get("ux", {}).get("cta", {}).get("status") == "PASS"
    if bev.has_cta:
        verdict = "consistent" if http_cta_ok else "js_only"
        diff = {"verdict": verdict}
        if verdict == "js_only":
            diff["note"] = "CTA keywords found in browser-rendered DOM but absent from raw HTTP source."
        _tag("ux", "cta", diff)
'''

# Insert after _compute_score function
COMPUTE_SCORE_END = '''    if not _NEW_AUDITOR_AVAILABLE:
        raise RuntimeError("Auditor package is not available")
    return compute_structured_score(audit_results, dict(SCORE_WEIGHTS))'''
COMPUTE_SCORE_END_CRLF = COMPUTE_SCORE_END.replace('\n', '\r\n')

if "_annotate_browser_comparisons" not in src:
    replaced = False
    for old_sig in (COMPUTE_SCORE_END_CRLF, COMPUTE_SCORE_END):
        if old_sig in src:
            src = src.replace(old_sig, COMPUTE_SCORE_END + ANNOTATE_FUNC, 1)
            replaced = True
            print("PATCH 3: _annotate_browser_comparisons added")
            break
    if not replaced:
        print("PATCH 3: _compute_score end marker not found — manual edit needed")
else:
    print("PATCH 3: _annotate_browser_comparisons already present, skipped")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 4: Unpack browser_evidence/browser_status from data dict in run_audit
# ─────────────────────────────────────────────────────────────────────────────
OLD_DATA_UNPACK = '    audit_results = data["audit_results"]\r\n    score         = data["score"]\r\n    site_summary  = data.get("site_summary", {})\r\n    page_audits   = data.get("page_audits", [])\r\n    crawl_coverage = data.get("crawl_coverage", {})\r\n    lifecycle = data.get("lifecycle", "COMPLETE")\r\n    homepage_html = data.get("html", "")\r\n    found_email   = data.get("found_email")\r\n    email_source  = data.get("email_source", "not_found")'
OLD_DATA_UNPACK_LF = OLD_DATA_UNPACK.replace('\r\n', '\n')

NEW_DATA_UNPACK = (
    '    audit_results    = data["audit_results"]\n'
    '    score            = data["score"]\n'
    '    site_summary     = data.get("site_summary", {})\n'
    '    page_audits      = data.get("page_audits", [])\n'
    '    crawl_coverage   = data.get("crawl_coverage", {})\n'
    '    lifecycle        = data.get("lifecycle", "COMPLETE")\n'
    '    homepage_html    = data.get("html", "")\n'
    '    found_email      = data.get("found_email")\n'
    '    email_source     = data.get("email_source", "not_found")\n'
    '    browser_evidence = data.get("browser_evidence", {})\n'
    '    browser_status   = data.get("browser_status", "DISABLED")'
)

if "browser_evidence = data.get" not in src:
    replaced = False
    for old_block in (OLD_DATA_UNPACK, OLD_DATA_UNPACK_LF):
        if old_block in src:
            src = src.replace(old_block, NEW_DATA_UNPACK, 1)
            replaced = True
            print("PATCH 4: browser_evidence unpacked from data dict")
            break
    if not replaced:
        print("PATCH 4: data unpack block not matched exactly; doing flexible search...")
        # Try to find and insert after email_source line
        pattern = r'(    email_source\s+=\s+data\.get\("email_source"[^\n]*\n)'
        new_lines = r'\1    browser_evidence = data.get("browser_evidence", {})\n    browser_status   = data.get("browser_status", "DISABLED")\n'
        new_src = re.sub(pattern, new_lines, src, count=1)
        if new_src != src:
            src = new_src
            replaced = True
            print("PATCH 4 (regex fallback): browser_evidence inserted")
        else:
            print("PATCH 4: Could not insert browser_evidence")
else:
    print("PATCH 4: already present, skipped")

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 5: Include browser_evidence in the site_summary DB write
# ─────────────────────────────────────────────────────────────────────────────
OLD_SITE_SUMMARY = '            audit.site_summary       = {**site_summary, "crawl_coverage": crawl_coverage, "lifecycle": lifecycle}\r\n            audit.audit_lifecycle    = lifecycle'
OLD_SITE_SUMMARY_LF = OLD_SITE_SUMMARY.replace('\r\n', '\n')

NEW_SITE_SUMMARY = (
    '            audit.site_summary       = {\n'
    '                **site_summary,\n'
    '                "crawl_coverage": crawl_coverage,\n'
    '                "lifecycle": lifecycle,\n'
    '                "browser_evidence": browser_evidence,\n'
    '                "browser_status": browser_status,\n'
    '            }\n'
    '            audit.audit_lifecycle    = lifecycle'
)

if '"browser_evidence": browser_evidence' not in src:
    replaced = False
    for old_block in (OLD_SITE_SUMMARY, OLD_SITE_SUMMARY_LF):
        if old_block in src:
            src = src.replace(old_block, NEW_SITE_SUMMARY, 1)
            replaced = True
            print("PATCH 5: browser_evidence stored in site_summary")
            break
    if not replaced:
        # regex approach
        pattern = r'(audit\.site_summary\s*=\s*\{[^}]+\})\s*\n(\s*audit\.audit_lifecycle)'
        new_part = (
            'audit.site_summary       = {\n'
            '                **site_summary,\n'
            '                "crawl_coverage": crawl_coverage,\n'
            '                "lifecycle": lifecycle,\n'
            '                "browser_evidence": browser_evidence,\n'
            '                "browser_status": browser_status,\n'
            '            }\n'
            '\\2audit.audit_lifecycle'
        )
        new_src = re.sub(pattern, new_part, src, count=1)
        if new_src != src:
            src = new_src
            print("PATCH 5 (regex fallback): browser_evidence inserted")
        else:
            print("PATCH 5: Could not match site_summary block")
else:
    print("PATCH 5: already present, skipped")

# ─────────────────────────────────────────────────────────────────────────────
# Write result
# ─────────────────────────────────────────────────────────────────────────────
ENGINE.write_bytes(src.encode("utf-8"))
print(f"\nPatch complete. File written: {ENGINE}")
print("Verify with: python -m compileall backend/app/engines/audit_engine.py")
