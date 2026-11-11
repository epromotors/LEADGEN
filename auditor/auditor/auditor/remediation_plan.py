# auditor/remediation_plan.py — Actionable Evidence-Based Remediation Planner
#
# Transforms raw findings from the 62 canonical factors and GEO supplement into
# a prioritized remediation plan formatted as:
#   Evidence → Impact → Priority (P0/P1/P2) → Recommended Fix → Verification Step
#
# MIT License Attribution:
# Inspired by and benchmarked against:
# - dageno-agents/seo-geo-audit (MIT): P0/P1/P2 priority framework
# - JeffLi1993/seo-audit-skill (MIT): Evidence → Impact → Fix walkthrough
# - leopard627/fire-your-seo-agency (MIT): Verify-after-fix validation workflow
#
# Mandatory Constraints:
# 1. Additive report structure only; does NOT modify 62 canonical factor severities.
# 2. Historical scores and factor results remain unaltered.

from __future__ import annotations

from typing import Any, Dict, List, Optional


def determine_action_priority(factor_id: str, status: str, default_severity: str = "medium") -> str:
    """
    Map factor status and domain criticality to P0/P1/P2 action priorities:
      - P0: Critical blockers to search indexing, user trust, or AI accessibility.
      - P1: High-impact ranking, discovery, or conversion deficiencies.
      - P2: Quality improvements, modern asset formats, and emerging conventions.
    """
    if status == "FAIL":
        if factor_id in {
            "technical.ssl", "onpage.noindex", "indexability.noindex",
            "technical.https_redirect", "technical.mobile", "crawler.redirect_loop",
        }:
            return "P0"
        if factor_id in {
            "onpage.page_title", "onpage.h1", "onpage.meta_desc", "technical.sitemap",
            "technical.robots", "links.broken_links", "ux.cta", "geo.citation_bots",
        }:
            return "P1"
        return "P2"
    elif status == "WARN":
        if factor_id in {"technical.robots", "technical.sitemap", "links.broken_links"}:
            return "P1"
        return "P2"
    return "P2"


def generate_remediation_plan(
    audit_results: Dict[str, Any],
    geo_supplement: Optional[Dict[str, Any]] = None,
    site_summary: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate prioritized remediation items from verified audit findings.
    """
    plan: List[Dict[str, Any]] = []

    # 1. Process 62-factor findings (groups: technical, onpage, images, links, ux, etc.)
    for group_name, group_factors in audit_results.items():
        if not isinstance(group_factors, dict):
            continue
        for test_key, factor_data in group_factors.items():
            if not isinstance(factor_data, dict):
                continue
            status = factor_data.get("status")
            if status not in ("FAIL", "WARN"):
                continue

            factor_id = factor_data.get("id") or f"{group_name}.{test_key}"
            message = factor_data.get("message") or f"Issue detected in {factor_id}."
            detail = factor_data.get("detail") or ""
            fix = factor_data.get("fix") or "Review and correct the identified issue."
            evidence_items = factor_data.get("evidence") or []
            
            # Format evidence string
            if evidence_items and isinstance(evidence_items, list):
                ev_str = "; ".join(str(e.get("summary") or e) for e in evidence_items[:3] if isinstance(e, dict))
                if not ev_str:
                    ev_str = str(evidence_items[:2])
            else:
                ev_str = detail or message

            priority = determine_action_priority(factor_id, status)
            
            # Impact statement based on factor category
            impact = _generate_impact_statement(factor_id, group_name)
            verification = _generate_verification_step(factor_id)

            plan.append({
                "id": f"{priority}-{factor_id}",
                "priority": priority,
                "factor_id": factor_id,
                "title": factor_data.get("name") or factor_id,
                "status": status,
                "evidence": ev_str,
                "impact": impact,
                "recommended_fix": fix,
                "verification_step": verification,
            })

    # 2. Process GEO Supplement Findings (if present)
    if geo_supplement and isinstance(geo_supplement, dict):
        # AI Bots blocked
        robots_ai = geo_supplement.get("robots_ai_rules", {})
        blocked_bots = robots_ai.get("citation_bots_blocked", [])
        if blocked_bots:
            plan.append({
                "id": "P1-geo.citation_bots",
                "priority": "P1",
                "factor_id": "geo.citation_bots",
                "title": "AI Citation Bots Disallowed in robots.txt",
                "status": "FAIL",
                "evidence": f"Robots.txt disallows: {', '.join(blocked_bots)}",
                "impact": "Search engines powered by LLMs (ChatGPT, Claude, Perplexity) cannot browse or cite your pages in real-time answers.",
                "recommended_fix": f"Add explicit 'User-agent: <bot>' Allow rules in robots.txt for: {', '.join(blocked_bots)}.",
                "verification_step": "Fetch /robots.txt with curl or browser and verify 'Allow: /' is declared for citation user agents.",
            })

        # Missing llms.txt
        llms_info = geo_supplement.get("llms_txt", {})
        if not llms_info.get("found"):
            plan.append({
                "id": "P2-geo.llms_txt",
                "priority": "P2",
                "factor_id": "geo.llms_txt",
                "title": "llms.txt Informational Convention Missing",
                "status": "WARN",
                "evidence": "No /llms.txt file found at site root.",
                "impact": "AI tools and autonomous developer agents lack a concise markdown map of key documentation and entity boundaries.",
                "recommended_fix": "Create /llms.txt with an H1 title, blockquote description, and links to authoritative resources.",
                "verification_step": "Test that 'GET /llms.txt' returns HTTP 200 with text/plain markdown formatting.",
            })

    # Sort plan by priority (P0 first, then P1, then P2)
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    plan.sort(key=lambda item: priority_order.get(item["priority"], 3))
    return plan


def _generate_impact_statement(factor_id: str, group: str) -> str:
    """Generate business and technical impact explanations for findings."""
    impacts = {
        "technical.ssl": "Browser security warnings block visitors and Google penalizes insecure origins.",
        "technical.https_redirect": "Inconsistent HTTP/HTTPS configurations split link equity and expose visitors to downgrade attacks.",
        "onpage.noindex": "Page cannot be indexed by search engines, causing total loss of organic search visibility.",
        "onpage.page_title": "Search engines cannot display a branded, relevant title in search snippets, reducing CTR.",
        "onpage.h1": "Crawlers and users miss the primary conceptual heading of the page, diluting topic relevance.",
        "onpage.meta_desc": "Google falls back to arbitrary body snippets, decreasing click-through rate from SERP listings.",
        "technical.sitemap": "Search engine crawlers struggle to discover deep or recently updated pages efficiently.",
        "technical.robots": "Crawl budget may be misallocated, or critical content pages may be inadvertently hidden.",
        "links.broken_links": "Visitors encounter 404 dead ends, harming user experience and wasting crawl equity.",
        "technical.mobile": "Mobile visitors experience layout breakage, causing Google mobile-first indexing penalties.",
        "images.alt_text": "Visually impaired users and screen readers cannot understand image content; missing image search traffic.",
        "images.webp": "Larger legacy image files increase bandwidth usage and degrade Core Web Vitals (LCP).",
    }
    return impacts.get(factor_id, f"Weakens site performance, organic discoverability, or conversion readiness in the {group} domain.")


def _generate_verification_step(factor_id: str) -> str:
    """Generate deterministic verification instructions for engineers."""
    steps = {
        "technical.ssl": "Run 'curl -Iv https://<domain>' to verify a trusted certificate chain and valid expiration date.",
        "technical.https_redirect": "Run 'curl -IL http://<domain>' and confirm an initial 301/308 redirect to https://.",
        "onpage.noindex": "Inspect page source for '<meta name=\"robots\" content=\"noindex\">' and verify removal.",
        "onpage.page_title": "Check page source for '<title>' tag with 30-65 characters accurately describing the page.",
        "onpage.h1": "Inspect DOM for exactly one authoritative '<h1>' element matching page topic.",
        "onpage.meta_desc": "Check page source for '<meta name=\"description\">' with 70-160 characters compelling summary.",
        "technical.sitemap": "Request '/sitemap.xml' and verify XML syntax via a validator or browser inspector.",
        "technical.robots": "Request '/robots.txt' and verify rules with Google Search Console or robots tester.",
        "links.broken_links": "Re-run the link checker to verify all reported 404 links return HTTP 200 or updated destinations.",
        "technical.mobile": "Test URL in Chrome DevTools Device Mode (375px width) and verify viewport meta tag.",
        "images.alt_text": "Inspect all '<img>' tags to confirm non-empty, descriptive 'alt' attributes.",
        "images.webp": "Check network tab in DevTools to confirm images are served with Content-Type: image/webp or .webp URLs.",
    }
    return steps.get(factor_id, "Re-run audit after deployment to verify status updates from FAIL/WARN to PASS.")
