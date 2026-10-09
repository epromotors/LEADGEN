"""Replace _annotate_browser_comparisons in audit_engine.py with import from comparisons.py."""
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "backend" / "app" / "engines" / "audit_engine.py"
src = ENGINE.read_bytes().decode("utf-8")

# Replace the entire _annotate_browser_comparisons function body with an import alias
OLD_FN = '''def _annotate_browser_comparisons(audit_results: dict, bev) -> None:
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
        _tag("ux", "cta", diff)'''

NEW_FN = '''# _annotate_browser_comparisons is defined in the auditor browser package so
# it can be imported in tests without pulling in FastAPI / pydantic-settings.
try:
    from browser.comparisons import annotate_browser_comparisons as _annotate_browser_comparisons
except ImportError:
    def _annotate_browser_comparisons(audit_results, bev):
        pass  # no-op fallback if browser package is unavailable'''

if OLD_FN in src:
    src = src.replace(OLD_FN, NEW_FN, 1)
    ENGINE.write_bytes(src.encode("utf-8"))
    print("Replaced _annotate_browser_comparisons with import alias")
else:
    print("ERROR: could not find the function body to replace")
    # Try a shorter unique signature
    sig = 'def _annotate_browser_comparisons(audit_results: dict, bev) -> None:'
    print("Signature present:", sig in src)
