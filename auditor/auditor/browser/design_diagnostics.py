"""
auditor/auditor/browser/design_diagnostics.py

Advanced Web-Design, Layout, and Observable Code Health Diagnostics.
Implements Domain H of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Bounded mobile and desktop layout inspection.
- Detection of horizontal overflow and layout clipping.
- Identification of failed assets, missing CSS/JS, and console runtime errors.
- Hierarchy & semantic analysis (header, main/hero, footer, heading progression).
- Strictly classifies findings into authoritative categories:
  - observed_live_site_defect
  - static_asset_markup_concern
  - rendered_browser_issue
  - heuristic_design_recommendation
"""

import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup


class WebDesignDiagnostics:
    """Evaluates observable web design, responsiveness, and code health signals."""

    @staticmethod
    def evaluate_markup_design_health(
        soup: BeautifulSoup,
        viewport_mode: str = "mobile",
    ) -> Dict[str, Any]:
        """
        Inspect HTML DOM for layout structure, heading hierarchy, viewport rules,
        and responsive design risks without requiring a live browser.
        """
        issues: List[Dict[str, Any]] = []

        # 1. Responsive Viewport Meta
        viewport_meta = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        has_viewport_meta = False
        viewport_content = ""
        if viewport_meta:
            viewport_content = viewport_meta.get("content", "")
            if "width=device-width" in viewport_content:
                has_viewport_meta = True

        if not has_viewport_meta:
            issues.append({
                "type": "static_asset_markup_concern",
                "severity": "high",
                "code": "MISSING_VIEWPORT_META",
                "message": "Missing standard responsive meta viewport tag ('width=device-width').",
                "recommendation": "Add <meta name='viewport' content='width=device-width, initial-scale=1.0'> to <head>.",
            })

        # 2. Semantic Landmark Hierarchy (header, main, footer, nav)
        has_header = bool(soup.find("header") or soup.find(attrs={"role": "banner"}))
        has_main = bool(soup.find("main") or soup.find(attrs={"role": "main"}))
        has_footer = bool(soup.find("footer") or soup.find(attrs={"role": "contentinfo"}))
        has_nav = bool(soup.find("nav") or soup.find(attrs={"role": "navigation"}))

        landmarks_present = sum([has_header, has_main, has_footer, has_nav])
        if landmarks_present < 3:
            issues.append({
                "type": "heuristic_design_recommendation",
                "severity": "medium",
                "code": "WEAK_SEMANTIC_LANDMARKS",
                "message": f"Incomplete HTML5 semantic landmarks (found {landmarks_present}/4: header, nav, main, footer).",
                "recommendation": "Use semantic landmark tags (<header>, <nav>, <main>, <footer>) for accessible structure.",
            })

        # 3. Heading Progression & Hierarchy
        headings = [h.name.lower() for h in soup.find_all(re.compile(r"^h[1-6]$"))]
        h1_count = headings.count("h1")

        if h1_count == 0:
            issues.append({
                "type": "static_asset_markup_concern",
                "severity": "high",
                "code": "NO_H1_HEADING",
                "message": "Page has no primary <h1> heading for document hierarchy.",
                "recommendation": "Add a single descriptive <h1> representing the core value proposition.",
            })
        elif h1_count > 1:
            issues.append({
                "type": "heuristic_design_recommendation",
                "severity": "low",
                "code": "MULTIPLE_H1_HEADINGS",
                "message": f"Multiple <h1> headings found ({h1_count}).",
                "recommendation": "Consolidate to a single primary <h1> per page; use <h2> for subsections.",
            })

        # Heading level skipping (e.g., h1 followed directly by h3 without h2)
        has_skipped_levels = False
        prev_level = 0
        for h in headings:
            lvl = int(h[1])
            if prev_level > 0 and lvl > prev_level + 1:
                has_skipped_levels = True
                break
            prev_level = lvl

        if has_skipped_levels:
            issues.append({
                "type": "heuristic_design_recommendation",
                "severity": "low",
                "code": "SKIPPED_HEADING_LEVEL",
                "message": "Heading hierarchy skips levels (e.g. h1 directly to h3).",
                "recommendation": "Maintain sequential heading levels (h1 -> h2 -> h3) for clear visual and screen-reader hierarchy.",
            })

        # 4. Fixed-width tables and oversized inline styles prone to horizontal overflow
        fixed_width_elements = 0
        for tag in soup.find_all(style=True):
            style = tag.get("style", "").lower()
            # Match fixed pixel widths > 600px without max-width
            match = re.search(r"\bwidth:\s*(\d{3,4})px", style)
            if match:
                px = int(match.group(1))
                if px > 600 and "max-width" not in style:
                    fixed_width_elements += 1

        for table in soup.find_all("table", width=True):
            w = table.get("width", "")
            if w.isdigit() and int(w) > 600:
                fixed_width_elements += 1

        if fixed_width_elements > 0:
            issues.append({
                "type": "observed_live_site_defect",
                "severity": "high",
                "code": "FIXED_WIDTH_OVERFLOW_RISK",
                "message": f"Found {fixed_width_elements} element(s) with fixed width > 600px creating mobile overflow risks.",
                "recommendation": "Replace fixed pixel widths with fluid percentages and 'max-width: 100%'.",
            })

        # 5. Missing or Broken Image Assets
        img_tags = soup.find_all("img")
        images_missing_src = sum(1 for img in img_tags if not img.get("src") and not img.get("data-src"))
        images_missing_alt = sum(1 for img in img_tags if img.get("alt") is None)

        if images_missing_src > 0:
            issues.append({
                "type": "observed_live_site_defect",
                "severity": "high",
                "code": "EMPTY_IMAGE_SRC",
                "message": f"Detected {images_missing_src} <img> element(s) with empty or missing src attribute.",
                "recommendation": "Provide valid image URLs or remove empty image placeholders.",
            })

        return {
            "viewport_mode": viewport_mode,
            "has_viewport_meta": has_viewport_meta,
            "viewport_content": viewport_content,
            "landmarks": {
                "header": has_header,
                "nav": has_nav,
                "main": has_main,
                "footer": has_footer,
            },
            "heading_counts": {h: headings.count(h) for h in ["h1", "h2", "h3", "h4", "h5", "h6"]},
            "total_issues": len(issues),
            "issues": issues,
        }

    @staticmethod
    def evaluate_browser_runtime_diagnostics(
        console_errors: List[str],
        failed_requests: List[str],
        window_width: int = 375,
        scroll_width: int = 375,
        viewport_name: str = "mobile_375",
    ) -> Dict[str, Any]:
        """
        Evaluate rendered runtime evidence from browser capture:
        - Horizontal scroll overflow (scrollWidth > windowWidth)
        - Console JavaScript runtime exceptions
        - Failed subresources (404/500 scripts, styles, images)
        """
        issues: List[Dict[str, Any]] = []

        # 1. Overflow check
        has_horizontal_overflow = scroll_width > (window_width + 2)
        overflow_px = max(0, scroll_width - window_width) if has_horizontal_overflow else 0

        if has_horizontal_overflow:
            issues.append({
                "type": "rendered_browser_issue",
                "severity": "critical" if overflow_px > 40 else "high",
                "code": "HORIZONTAL_SCROLL_OVERFLOW",
                "message": f"Horizontal scroll overflow of {overflow_px}px detected at {viewport_name} (scrollWidth={scroll_width}px, viewport={window_width}px).",
                "recommendation": "Inspect wide children, unconstrained pre/table blocks, and set 'overflow-x: hidden' on container or max-width: 100%.",
            })

        # 2. Console errors
        if console_errors:
            issues.append({
                "type": "rendered_browser_issue",
                "severity": "high",
                "code": "JAVASCRIPT_RUNTIME_ERRORS",
                "message": f"{len(console_errors)} JavaScript console error(s) observed during page lifecycle.",
                "details": console_errors[:5],
                "recommendation": "Fix uncaught JavaScript exceptions preventing user interaction or dynamic UI elements from executing.",
            })

        # 3. Failed subresource requests
        if failed_requests:
            issues.append({
                "type": "observed_live_site_defect",
                "severity": "high",
                "code": "FAILED_SUBRESOURCE_REQUESTS",
                "message": f"{len(failed_requests)} failed network request(s) for page subresources (CSS/JS/images).",
                "details": failed_requests[:5],
                "recommendation": "Resolve 404/500 network assets to prevent broken stylesheets, missing icons, or unrendered modules.",
            })

        return {
            "viewport_name": viewport_name,
            "window_width": window_width,
            "scroll_width": scroll_width,
            "has_horizontal_overflow": has_horizontal_overflow,
            "overflow_px": overflow_px,
            "console_error_count": len(console_errors),
            "failed_request_count": len(failed_requests),
            "total_runtime_issues": len(issues),
            "issues": issues,
        }
