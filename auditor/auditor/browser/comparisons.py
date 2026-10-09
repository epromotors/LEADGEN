"""Pure-Python browser comparison annotation helper.

Extracted from audit_engine.py so it can be imported in tests without
triggering FastAPI / pydantic-settings / database imports.

audit_engine.py imports this module and re-exports _annotate_browser_comparisons.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def annotate_browser_comparisons(
    audit_results: dict,
    bev: object,
) -> None:
    """Attach raw-vs-rendered comparison metadata to selected factor results.

    This only ANNOTATES; it does NOT change any factor status or score.
    Consuming code (frontend, API) can read the browser_diff field.

    Factors annotated in Phase 2:
      - onpage.page_title  (JS may change the title after load)
      - onpage.h1          (JS-rendered frameworks may inject headings)
      - ux.cta             (CTAs may be injected by JavaScript)

    Rules:
      - DISABLED, BLOCKED, or FAILED browser status → no annotation.
      - A browser failure does NOT convert a PASS into a FAIL.
      - "js_only" means the content was found in the browser-rendered DOM
        but absent from raw HTTP — informational only.
    """
    if not bev or getattr(bev, "provider_status", None) not in ("SUCCESS", "PARTIAL"):
        return

    def _tag(group: str, key: str, diff: dict) -> None:
        result = audit_results.get(group, {}).get(key)
        if isinstance(result, dict):
            result["browser_diff"] = diff

    # 1. Page title: compare HTTP-extracted vs browser-rendered title
    http_title_value = audit_results.get("onpage", {}).get("page_title", {}).get("value", "")
    rendered_title   = getattr(bev, "js_rendered_title", None) or ""
    if rendered_title:
        if not (http_title_value or "").strip() and rendered_title.strip():
            _tag("onpage", "page_title", {
                "verdict": "js_only",
                "note": "Title absent in raw HTTP but present in browser-rendered DOM.",
                "rendered_value": rendered_title[:200],
            })
        else:
            _tag("onpage", "page_title", {
                "verdict": "consistent",
                "rendered_value": rendered_title[:200],
            })

    # 2. H1 heading
    http_h1_ok   = audit_results.get("onpage", {}).get("h1", {}).get("status") == "PASS"
    rendered_h1s = [
        h for h in (getattr(bev, "js_rendered_headings", None) or [])
        if h.get("level") == "h1"
    ]
    if rendered_h1s:
        verdict = "consistent" if http_h1_ok else "js_only"
        diff = {"verdict": verdict, "rendered_h1s": [h["text"][:200] for h in rendered_h1s[:3]]}
        if verdict == "js_only":
            diff["note"] = "H1 absent in raw HTTP but found in browser-rendered DOM."
        _tag("onpage", "h1", diff)

    # 3. CTA
    http_cta_ok = audit_results.get("ux", {}).get("cta", {}).get("status") == "PASS"
    if getattr(bev, "has_cta", False):
        verdict = "consistent" if http_cta_ok else "js_only"
        diff: dict = {"verdict": verdict}
        if verdict == "js_only":
            diff["note"] = (
                "CTA keywords found in browser-rendered DOM but absent from raw HTTP source."
            )
        _tag("ux", "cta", diff)
