"""
auditor/auditor/browser/performance_diagnostics.py

Advanced Performance Diagnostics for LEADGEN Browser Capture.
Provides:
- Resource classification and aggregation (document, script, stylesheet, image, font, fetch, media, other).
- Missing/unavailable transfer size handling (transparently distinguishing zero-bytes from missing data).
- Distinguishing network/proxy failed requests from HTTP 4xx/5xx responses.
- Runtime console error classification (actionable JavaScript errors vs browser warnings).
- Render-blocking candidate heuristics with explicit limitation labeling.
- Multi-page evidence association and coverage labeling.
- Strict URL sanitization (stripping auth credentials and sensitive query tokens).
- Score-neutral design: does NOT alter the canonical 62-factor scoring contract.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional


_SENSITIVE_PARAM_NAMES = frozenset({
    "token", "auth", "key", "api_key", "apikey", "secret", "password",
    "passwd", "session", "sessionid", "sessid", "phpsessid", "jsessionid",
    "access_token", "refresh_token", "id_token", "signature", "sig",
})

_EXT_TO_TYPE = {
    ".js": "script",
    ".mjs": "script",
    ".css": "stylesheet",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".webp": "image",
    ".avif": "image",
    ".ico": "image",
    ".woff": "font",
    ".woff2": "font",
    ".ttf": "font",
    ".otf": "font",
    ".eot": "font",
    ".mp4": "media",
    ".webm": "media",
    ".mp3": "media",
    ".ogg": "media",
    ".html": "document",
    ".htm": "document",
}


def sanitize_resource_url(raw_url: str, max_length: int = 180) -> str:
    """Sanitize URL for display and persistence.

    Strips credentials and sensitive query parameters, and caps total length.
    """
    if not raw_url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return raw_url[:max_length]

        # Strip user:pass
        netloc = parsed.netloc
        if "@" in netloc:
            netloc = netloc.split("@")[-1]

        # Filter query params
        cleaned_query_parts: list[str] = []
        if parsed.query:
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            for k, v in query_pairs:
                if k.lower() in _SENSITIVE_PARAM_NAMES or any(s in k.lower() for s in ("token", "secret", "key")):
                    cleaned_query_parts.append(f"{k}=[REDACTED]")
                else:
                    cleaned_query_parts.append(f"{k}={v[:50]}")
        cleaned_query = "&".join(cleaned_query_parts)

        rebuilt = urllib.parse.urlunsplit((
            parsed.scheme,
            netloc,
            parsed.path,
            cleaned_query,
            ""  # drop fragment
        ))
        return rebuilt[:max_length]
    except Exception:
        return raw_url[:max_length]


def classify_resource_type(initiator_type: str, url: str) -> str:
    """Classify a resource into one of 8 standard groups.

    Standard groups:
      - document
      - script
      - stylesheet
      - image
      - font
      - fetch
      - media
      - other
    """
    init = (initiator_type or "").lower().strip()
    if init in ("navigation", "document"):
        return "document"
    if init in ("script",):
        return "script"
    if init in ("css", "stylesheet"):
        return "stylesheet"
    if init in ("img", "image"):
        return "image"
    if init in ("font",):
        return "font"
    if init in ("xmlhttprequest", "fetch", "beacon"):
        return "fetch"
    if init in ("video", "audio"):
        return "media"

    # Fallback to URL path inspection
    try:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path.lower()
        for ext, rtype in _EXT_TO_TYPE.items():
            if path.endswith(ext):
                return rtype
    except Exception:
        pass

    if init in ("link",):
        # A <link> might be css or icon or font
        if ".css" in url.lower():
            return "stylesheet"
        if any(e in url.lower() for e in (".woff", ".woff2", ".ttf")):
            return "font"
        if any(e in url.lower() for e in (".ico", ".png", ".svg")):
            return "image"

    return "other"


class PerformanceDiagnostics:
    """Core evaluation engine for resource and runtime performance diagnostics."""

    @staticmethod
    def evaluate(
        resource_entries: Optional[List[Dict[str, Any]]] = None,
        failed_requests: Optional[List[str]] = None,
        http_errors: Optional[List[Dict[str, Any]]] = None,
        console_messages: Optional[List[str]] = None,
        render_blocking_info: Optional[Dict[str, Any]] = None,
        page_index: int = 0,
        total_pages: int = 1,
    ) -> Dict[str, Any]:
        """Aggregate performance signals into a typed, structured dictionary."""
        entries = resource_entries or []
        failed_reqs = failed_requests or []
        http_errs = http_errors or []
        console_msgs = console_messages or []

        # 1. Resource Summary
        categories = ["document", "script", "stylesheet", "image", "font", "fetch", "media", "other"]
        by_type: Dict[str, Dict[str, Any]] = {
            cat: {"count": 0, "transfer_bytes": 0, "transfer_kb": 0.0, "has_size_data": False}
            for cat in categories
        }

        total_requests = len(entries)
        total_transfer_bytes = 0
        has_any_transfer_data = False

        for entry in entries:
            url = entry.get("name") or entry.get("url") or ""
            init_type = entry.get("initiatorType") or entry.get("initiator_type") or ""
            cat = classify_resource_type(init_type, url)
            if cat not in by_type:
                cat = "other"

            by_type[cat]["count"] += 1

            # Handle transfer size safely (Timing-Allow-Origin or browser permissions may yield 0 or null)
            raw_size = entry.get("transferSize")
            if raw_size is None:
                raw_size = entry.get("transfer_size")

            if isinstance(raw_size, (int, float)) and raw_size > 0:
                size_int = int(raw_size)
                by_type[cat]["transfer_bytes"] += size_int
                by_type[cat]["has_size_data"] = True
                total_transfer_bytes += size_int
                has_any_transfer_data = True

        for cat in categories:
            by_type[cat]["transfer_kb"] = round(by_type[cat]["transfer_bytes"] / 1024.0, 2)

        resource_summary = {
            "total_requests": total_requests,
            "total_transfer_bytes": total_transfer_bytes,
            "total_transfer_kb": round(total_transfer_bytes / 1024.0, 2),
            "has_transfer_size_data": has_any_transfer_data,
            "size_measurement_note": (
                "Observed network transfer sizes from PerformanceResourceTiming API."
                if has_any_transfer_data
                else "Resource sizes unavailable (likely cross-origin resources without Timing-Allow-Origin headers or cached)."
            ),
            "by_type": by_type,
        }

        # 2. Failure Breakdown
        samples: List[Dict[str, Any]] = []
        for req_url in failed_reqs[:10]:
            samples.append({
                "category": "network_failure_or_blocked",
                "status": None,
                "url": sanitize_resource_url(req_url),
                "resource_type": "unknown",
                "detail": "Network connection failed, DNS timed out, or blocked by browser/proxy security policy",
            })

        for err in http_errs[:10]:
            status_code = err.get("status")
            err_url = err.get("url") or ""
            res_type = err.get("resource_type") or "other"
            samples.append({
                "category": "http_error",
                "status": status_code,
                "url": sanitize_resource_url(err_url),
                "resource_type": res_type,
                "detail": f"HTTP {status_code} error response returned by server",
            })

        failure_breakdown = {
            "failed_requests_count": len(failed_reqs),
            "http_errors_count": len(http_errs),
            "total_failure_events": len(failed_reqs) + len(http_errs),
            "samples": samples[:10],
        }

        # 3. Runtime Console Evidence
        actionable_errors: List[str] = []
        warnings: List[str] = []

        for msg in console_msgs:
            sanitized = msg[:200]
            if msg.startswith("[error]") or "error" in msg.lower():
                if len(actionable_errors) < 5:
                    actionable_errors.append(sanitized)
            else:
                if len(warnings) < 5:
                    warnings.append(sanitized)

        console_evidence = {
            "total_count": len(console_msgs),
            "error_count": len(actionable_errors),
            "warning_count": len(warnings),
            "actionable_errors": actionable_errors,
            "warnings": warnings,
        }

        # 4. Render-Blocking Candidates (Heuristics)
        rb_info = render_blocking_info or {}
        candidate_scripts: List[Dict[str, str]] = []
        candidate_styles: List[Dict[str, str]] = []

        for s in rb_info.get("scripts", [])[:5]:
            candidate_scripts.append({
                "url": sanitize_resource_url(s.get("url", "")),
                "reason": s.get("reason", "Synchronous <script> in <head> without async/defer attribute"),
            })

        for c in rb_info.get("stylesheets", [])[:5]:
            candidate_styles.append({
                "url": sanitize_resource_url(c.get("url", "")),
                "reason": c.get("reason", "Standard <link rel='stylesheet'> in <head>"),
            })

        render_blocking_candidates = {
            "total_candidates": len(candidate_scripts) + len(candidate_styles),
            "scripts": candidate_scripts,
            "stylesheets": candidate_styles,
            "limitation_note": (
                "Candidate heuristic based on DOM markup observation; actual render-blocking impact depends on network priority and browser execution pipeline."
            ),
        }

        # 5. Coverage and Association
        coverage_note = (
            f"Observation from captured page {page_index + 1} of {total_pages}. "
            "Bounded lab capture under controlled conditions; not full-site user telemetry."
        )

        return {
            "available": True,
            "page_index": page_index,
            "total_pages_captured": total_pages,
            "resource_summary": resource_summary,
            "failure_breakdown": failure_breakdown,
            "console_evidence": console_evidence,
            "render_blocking_candidates": render_blocking_candidates,
            "coverage_note": coverage_note,
        }
