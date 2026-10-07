# backend/app/engines/audit_engine.py
# LeadGen OS v5.0 — 55-Factor Deep SEO Audit Engine
# Replaces the v4.5.0 engine.
# Entry point: async def run_audit(lead_id, db) — signature unchanged.
#
# ──────────────────────────────────────────────────────────────────────
# WHAT CHANGED vs v3.x:
#   • _run_audit_sync() calls 19 new checks from auditor/ package
#   • _map_to_db_columns() maps rich results → existing DB columns
#   • build_pdf() from auditor/reporter/pdf_report.py replaces pdf_engine
#   • extract_business_name() copied verbatim — AI name feature preserved
#   • site_checker.classify_site() still awaited first — unchanged
#   • All blocking requests run via run_in_executor — event loop safe
#   • classify_site() is ASYNC (aiohttp) — must be awaited NOT run_in_executor
# ──────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from uuid import UUID

# ── Import new auditor package ────────────────────────────────────────────────
# The auditor sub-packages live at:
#   C:\Users\LENOVO\LEADGEN\auditor\auditor\auditor\*.py   (from auditor.core import ...)
#   C:\Users\LENOVO\LEADGEN\auditor\auditor\reporter\*.py  (from reporter.pdf_report import ...)
#   C:\Users\LENOVO\LEADGEN\auditor\auditor\config.py      (from config import ...)
#
# Therefore sys.path must point to: C:\Users\LENOVO\LEADGEN\auditor\auditor\
# Path is resolved relative to this file's location:
#   this file  → backend/app/engines/audit_engine.py
#   parents[3] → LEADGEN/
#   + auditor/auditor/ → LEADGEN/auditor/auditor/
_AUDITOR_PATH = Path(__file__).resolve().parents[3] / "auditor" / "auditor"
if str(_AUDITOR_PATH) not in sys.path:
    sys.path.insert(0, str(_AUDITOR_PATH))

try:
    from auditor.core import make_session, normalize_url, fetch_page
    # ── v4.5 base modules ────────────────────────────────────────────────────
    from auditor.technical import (
        audit_ssl, audit_sitemap, audit_robots,
        audit_canonical, audit_favicon, audit_mobile,
        # v5.0 new technical checks (B6-B9)
        audit_https_redirect, audit_redirect_chain,
        audit_mixed_content, audit_www_canonicalization,
    )
    from auditor.onpage import (
        audit_title, audit_meta_description, audit_h1,
        audit_og_tags, audit_schema,
        # v5.0 new onpage checks (B1-B5)
        audit_noindex, audit_heading_hierarchy, audit_internal_links,
        audit_anchor_text_quality, audit_image_filenames,
    )
    from auditor.images import audit_alt_text, audit_webp, audit_lazy_loading
    from auditor.links import audit_broken_links
    from auditor.social import audit_social_links, audit_contact_links, audit_whatsapp
    from auditor.trust import audit_trust_pages
    from auditor.ux import (
        audit_cta, audit_cta_above_fold, audit_hero_headline,
        audit_font_size, audit_contrast, audit_nav_links,
        audit_cookie_notice, audit_live_chat,
        # v5.0 new UX checks (B12-B13)
        audit_phone_number, audit_address_presence,
    )
    from auditor.crawler import crawl_site, audit_page_seo, aggregate_site_issues
    from auditor.email_finder import find_domain_email, should_update_email
    from reporter.pdf_report import build_pdf
    from config import SCORE_WEIGHTS, TEST_SCORES
    # ── v5.0 new modules ─────────────────────────────────────────────────────
    from auditor.indexability import (
        audit_noindex as audit_noindex_idx,
        audit_url_structure, audit_www_vs_nonwww, audit_soft_404_content,
    )
    from auditor.content import (
        audit_word_count, audit_duplicate_meta,
        audit_keyword_in_title, audit_reading_level,
    )
    from auditor.local_seo import (
        audit_nap_consistency, audit_local_business_schema,
        audit_google_maps_embed, audit_city_in_title, audit_business_hours,
    )
    from auditor.performance import (
        audit_response_time, audit_page_size, audit_render_blocking,
        audit_gzip_compression, audit_webp_images, audit_minification,
    )
    from auditor.schema_advanced import (
        audit_faq_schema, audit_product_schema, audit_breadcrumb_schema,
        audit_review_schema, audit_graph_schema,
    )
    _NEW_AUDITOR_AVAILABLE = True
except ImportError as e:
    logging.error(
        f"[audit_engine] CRITICAL: New auditor package not available: {e}\n"
        f"  Expected path: {_AUDITOR_PATH}\n"
        f"  Ensure auditor/auditor/ sub-packages exist and reportlab is installed."
    )
    _NEW_AUDITOR_AVAILABLE = False

# ── Existing backend imports (do not change) ──────────────────────────────────
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Audit, Lead, AuditStatus, LeadStatus, ActivityLog
from app.utils.site_checker import (
    classify_site,
    resolve_live_url,
    SiteType,
    site_status_tag,
    detect_country,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — SAFETY HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _safe(text: str) -> str:
    """Strip non-Latin-1 characters for email/DB safety."""
    if not text:
        return ""
    return text.encode("latin-1", errors="ignore").decode("latin-1")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — AI BUSINESS NAME EXTRACTOR (copied verbatim from v3.x)
# ══════════════════════════════════════════════════════════════════════════════

def extract_business_name(html: str, url: str = "") -> tuple[str | None, str | None]:
    """
    Extract a clean business name from the website HTML.
    Returns (name, source) where source is one of:
      'og:site_name', 'json-ld', 'title'
    Returns (None, None) if nothing useful found.

    Priority:
      1. og:site_name meta tag (most accurate)
      2. JSON-LD @type=Organization → name or legalName
      3. <title> first segment (splits on | - – :)
    """
    import json as _json
    soup = BeautifulSoup(html, "lxml")

    # 1. og:site_name
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content", "").strip():
        name = og["content"].strip()
        if len(name) > 3:
            return name, "og:site_name"

    # 2. JSON-LD Organization
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.get_text())
            # Handle @graph
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") in ("Organization", "LocalBusiness",
                                          "Corporation", "Store"):
                    name = item.get("legalName") or item.get("name", "")
                    if name and len(name.strip()) > 3:
                        return name.strip(), "json-ld"
        except Exception:
            continue

    # 3. <title> first segment
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Split on common separators
        for sep in ["|", "–", "-", "—", ":"]:
            if sep in title:
                part = title.split(sep)[0].strip()
                if 3 < len(part) < 80:
                    return part, "title"
        # No separator — use full title if short enough
        if 3 < len(title) < 80:
            return title, "title"

    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — NEW SYNCHRONOUS AUDIT RUNNER
# Called via run_in_executor so it doesn't block the async event loop.
# ══════════════════════════════════════════════════════════════════════════════

def _run_audit_sync(url: str) -> dict:
    """
    Run all 55+ SEO checks + multi-page crawl synchronously.
    Must be called via asyncio.get_event_loop().run_in_executor().

    Returns:
        {
          "audit_results": dict,   # nested by group
          "score": int,            # 0-100
          "site_summary": dict,    # from aggregate_site_issues()
          "page_audits": list,     # per-page results
          "html": str,             # homepage HTML (for extract_business_name)
          "response_content": bytes, # raw response bytes for page_size check
        }
    """
    if not _NEW_AUDITOR_AVAILABLE:
        raise RuntimeError("New auditor package is not available. Check imports.")

    url = normalize_url(url)
    session = make_session()

    # Fetch homepage
    page = fetch_page(url, session)
    if not page["ok"]:
        raise ConnectionError(f"Cannot fetch {url}: {page.get('error', 'unknown error')}")

    soup = page["soup"]
    html = page["html"]
    response_content = html.encode("utf-8") if html else b""

    # ── Run all v5.0 checks ───────────────────────────────────────────────────
    audit_results = {
        # ── TECHNICAL (v4.5 + v5.0 new) ──────────────────────────────────────
        "technical": {
            "ssl":                  audit_ssl(url, session),
            "sitemap":              audit_sitemap(url, session),
            "robots":               audit_robots(url, session),
            "canonical":            audit_canonical(soup, url),
            "favicon":              audit_favicon(soup, url, session),
            "mobile":               audit_mobile(soup),
            # B6-B9 new checks
            "https_redirect":       audit_https_redirect(url, session),
            "redirect_chain":       audit_redirect_chain(url, session),
            "mixed_content":        audit_mixed_content(soup, url),
            "www_canonicalization": audit_www_canonicalization(url, session),
        },
        # ── ONPAGE (v4.5 + v5.0 new) ─────────────────────────────────────────
        "onpage": {
            "page_title":           audit_title(soup),
            "meta_desc":            audit_meta_description(soup),
            "h1":                   audit_h1(soup),
            "og_tags":              audit_og_tags(soup, url),
            "schema":               audit_schema(soup),
            # B1-B5 new checks
            "noindex":              audit_noindex(soup),
            "heading_hierarchy":    audit_heading_hierarchy(soup),
            "internal_links":       audit_internal_links(soup, url),
            "anchor_text_quality":  audit_anchor_text_quality(soup),
            "image_filenames":      audit_image_filenames(soup),
        },
        # ── IMAGES ────────────────────────────────────────────────────────────
        "images": {
            "alt_text":  audit_alt_text(soup),
            "webp":      audit_webp(soup, html),
            "lazy_load": audit_lazy_loading(soup),
        },
        # ── LINKS ─────────────────────────────────────────────────────────────
        "links": {
            "broken_links": audit_broken_links(soup, url, session),
        },
        # ── CONVERSION ────────────────────────────────────────────────────────
        "conversion": {
            "social":   audit_social_links(soup, url, session),
            "contact":  audit_contact_links(soup),
            "whatsapp": audit_whatsapp(soup),
            "trust":    audit_trust_pages(soup, url),
        },
        # ── UX (v4.5 + v5.0 new) ─────────────────────────────────────────────
        "ux": {
            "cta":              audit_cta(soup),
            "cta_above_fold":   audit_cta_above_fold(soup, html),
            "hero_headline":    audit_hero_headline(soup),
            "font_size":        audit_font_size(soup, html),
            "contrast":         audit_contrast(soup),
            "nav_links":        audit_nav_links(soup),
            "cookie_notice":    audit_cookie_notice(soup, html),
            "live_chat":        audit_live_chat(soup, html),
            # B12-B13 new checks
            "phone_number":     audit_phone_number(soup),
            "address_presence": audit_address_presence(soup),
        },
        # ── INDEXABILITY (new v5.0 module) ────────────────────────────────────
        "indexability": {
            "noindex":        audit_noindex_idx(soup),
            "url_structure":  audit_url_structure(url),
            "www_vs_nonwww": audit_www_vs_nonwww(url, session),
            "soft_404":       audit_soft_404_content(soup, url),
        },
        # ── CONTENT QUALITY (new v5.0 module) ────────────────────────────────
        "content": {
            "word_count":      audit_word_count(soup),
            "duplicate_meta":  audit_duplicate_meta(soup),
            "keyword_in_title": audit_keyword_in_title(soup),
            "reading_level":   audit_reading_level(soup),
        },
        # ── LOCAL SEO (new v5.0 module) ───────────────────────────────────────
        "local_seo": {
            "nap_consistency":       audit_nap_consistency(soup),
            "local_business_schema": audit_local_business_schema(soup),
            "google_maps_embed":     audit_google_maps_embed(soup),
            "city_in_title":         audit_city_in_title(soup),
            "business_hours":        audit_business_hours(soup),
        },
        # ── PERFORMANCE (new v5.0 module) ─────────────────────────────────────
        "performance": {
            "response_time":    audit_response_time(url, session),
            "page_size":        audit_page_size(r_content=response_content),
            "render_blocking":  audit_render_blocking(soup),
            "gzip_compression": audit_gzip_compression(url, session),
            "webp_images":      audit_webp_images(soup),
            "minification":     audit_minification(soup, html),
        },
        # ── SCHEMA ADVANCED (new v5.0 module) ────────────────────────────────
        "schema_advanced": {
            "faq_schema":        audit_faq_schema(soup),
            "product_schema":    audit_product_schema(soup),
            "breadcrumb_schema": audit_breadcrumb_schema(soup),
            "review_schema":     audit_review_schema(soup),
            "graph_schema":      audit_graph_schema(soup),
        },
    }

    # ── Multi-page crawl ─────────────────────────────────────────────────────
    try:
        crawled      = crawl_site(url, session, max_pages=100)
        page_audits  = [audit_page_seo(p) for p in crawled]
        site_summary = aggregate_site_issues(page_audits)
    except Exception as e:
        logger.warning(f"[audit_engine] Crawl failed for {url}: {e}")
        page_audits  = []
        site_summary = {}

    score = _compute_score(audit_results)

    # ── Domain email detection ──────────────────────────────────────────────
    found_email  = None
    email_source = "not_found"
    try:
        found_email, email_source = find_domain_email(
            website_url=url,
            homepage_soup=soup,
            homepage_html=html,
            session=session,
        )
    except Exception as _ee:
        logger.warning(f"[audit_engine] email_finder failed for {url}: {_ee}")

    return {
        "audit_results": audit_results,
        "score": score,
        "site_summary": site_summary,
        "page_audits": page_audits,
        "html": html,
        "found_email":  found_email,
        "email_source": email_source,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SCORE COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

def _compute_score(audit_results: dict) -> int:
    """
    Weighted score 0–100 across 11 groups (v5.0).
    PASS = full points, WARN = 50%, FAIL = 0.
    Groups defined in config.SCORE_WEIGHTS (must sum to 100).
    """
    if not _NEW_AUDITOR_AVAILABLE:
        return 0

    # Use all keys from SCORE_WEIGHTS so new groups auto-register
    weight_map = dict(SCORE_WEIGHTS)
    total_weight = sum(weight_map.values())
    weighted_sum = 0.0

    for group_key, tests in audit_results.items():
        total_pts  = 0
        earned_pts = 0.0
        for test_id, result in tests.items():
            max_pts = TEST_SCORES.get(test_id, 5)
            total_pts += max_pts
            status = result.get("status", "FAIL")
            if status == "PASS":
                earned_pts += max_pts
            elif status == "WARN":
                earned_pts += max_pts * 0.5
        group_pct = (earned_pts / total_pts * 100) if total_pts else 100
        weighted_sum += group_pct * weight_map.get(group_key, 0)

    return round(weighted_sum / total_weight)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — MAP NEW RESULTS → EXISTING DB COLUMNS
# ══════════════════════════════════════════════════════════════════════════════

# ── UX Axis helpers ───────────────────────────────────────────────────────────

def _extract_nav_count(ux_group: dict) -> int | None:
    """Extract the integer nav link count from the nav_links audit message."""
    nav_result = ux_group.get("nav_links", {})
    if not nav_result:
        return None
    msg = nav_result.get("message", "")
    m = re.search(r"(\d+)\s+link", msg)
    return int(m.group(1)) if m else (0 if nav_result.get("status") == "FAIL" else None)


def _compute_ux_score(ux_group: dict) -> int | None:
    """Compute a 0-100 score for the UX axis based on TEST_SCORES weights."""
    if not _NEW_AUDITOR_AVAILABLE or not ux_group:
        return None
    total_pts = 0
    earned = 0.0
    for test_id, result in ux_group.items():
        max_pts = TEST_SCORES.get(test_id, 5)
        total_pts += max_pts
        s = result.get("status", "FAIL")
        if s == "PASS":
            earned += max_pts
        elif s == "WARN":
            earned += max_pts * 0.5
    return round((earned / total_pts * 100)) if total_pts else 0


def _map_to_db_columns(audit_results: dict, score: int) -> dict:

    """
    Maps the rich 19-factor audit_results dict to the existing audits table
    columns so the rest of the system (email engine, UI) works unchanged.

    Returns a dict of column_name → value for every audits table field.
    """
    t  = audit_results.get("technical", {})
    op = audit_results.get("onpage", {})
    im = audit_results.get("images", {})
    lk = audit_results.get("links", {})
    cv = audit_results.get("conversion", {})
    ux = audit_results.get("ux", {})

    def status(group: dict, key: str) -> str:
        return group.get(key, {}).get("status", "FAIL")

    def is_pass(group: dict, key: str) -> bool:
        return status(group, key) == "PASS"

    def is_fail(group: dict, key: str) -> bool:
        return status(group, key) == "FAIL"

    def msg(group: dict, key: str) -> str:
        return group.get(key, {}).get("message", "")

    # ── Extract broken link count from message ────────────────────────────────
    broken_count = 0
    broken_msg = msg(lk, "broken_links")
    if broken_msg:
        m = re.search(r"^(\d+)\s+broken", broken_msg)
        if m:
            broken_count = int(m.group(1))
        else:
            # Try alternate format: "Found N broken"
            m2 = re.search(r"(\d+)\s+broken", broken_msg)
            if m2:
                broken_count = int(m2.group(1))

    # ── Extract missing alt count from message ────────────────────────────────
    alt_count = 0
    alt_msg = msg(im, "alt_text")
    if alt_msg:
        # Format: "8 of 14 images (57%) missing alt text"
        m = re.search(r"^(\d+)\s+of\s+\d+", alt_msg)
        if m:
            alt_count = int(m.group(1))
        else:
            # Format: "ALL 8 images missing alt text"
            m2 = re.search(r"ALL\s+(\d+)", alt_msg)
            if m2:
                alt_count = int(m2.group(1))
            else:
                # Format: "N images missing alt"
                m3 = re.search(r"(\d+)\s+images?\s+missing", alt_msg)
                if m3:
                    alt_count = int(m3.group(1))

    # ── Extract missing social platforms ─────────────────────────────────────
    missing_social: list[str] = []
    social_result = cv.get("social", {})
    social_text = " ".join(
        str(social_result.get(k, ""))
        for k in ("message", "fix", "detail")
        if social_result.get(k)
    )
    if "missing" in social_text.lower():
        # Formats:
        #   "Some social links missing: LinkedIn, YouTube"
        #   "... Missing: Facebook, Instagram, LinkedIn"
        match = re.search(r"missing(?: social links)?\s*:\s*([^\n.]+)", social_text, re.IGNORECASE)
        if match:
            missing_social = [
                s.strip()
                for s in match.group(1).split(",")
                if s.strip() and s.strip().lower() not in {"none", "no"}
            ]

    # ── Build human-readable audit_summary ───────────────────────────────────
    # This is what outreach_engine.py uses to build the email body.
    issues = []
    if not is_pass(t, "ssl"):        issues.append("SSL certificate issue")
    if not is_pass(t, "sitemap"):    issues.append("Missing XML sitemap")
    if not is_pass(t, "robots"):     issues.append("No robots.txt found")
    if not is_pass(t, "canonical"):  issues.append("Missing canonical tag")
    if not is_pass(t, "mobile"):     issues.append("Mobile not configured")
    if not is_pass(op, "h1"):
        issues.append("Missing H1 heading" if is_fail(op, "h1") else "H1 structure needs review")
    if is_fail(op, "meta_desc"):     issues.append("No meta description")
    if is_fail(op, "schema"):        issues.append("No Schema/JSON-LD markup")
    if is_fail(op, "og_tags"):       issues.append("Missing Open Graph tags")
    if alt_count > 0:                issues.append(f"{alt_count} image(s) missing alt text")
    if not is_pass(im, "webp"):      issues.append("Images not optimised (no WebP)")
    if broken_count > 0:             issues.append(f"{broken_count} broken link(s) found")
    if not is_pass(cv, "contact"):
        issues.append("No clickable phone/email links" if is_fail(cv, "contact") else "Contact links incomplete")
    if not is_pass(cv, "whatsapp"):  issues.append("No WhatsApp integration")
    if not is_pass(cv, "trust"):     issues.append("Missing Privacy Policy / Terms")

    if issues:
        summary = (f"SEO Score: {score}/100. "
                   f"Found {len(issues)} issue(s): {', '.join(issues[:6])}.")
    else:
        summary = f"SEO Score: {score}/100. Site is well-optimised — no critical issues found."

    # ── New v5.0 groups ───────────────────────────────────────────────────────
    ix = audit_results.get("indexability", {})
    ct = audit_results.get("content", {})
    ls = audit_results.get("local_seo", {})
    pf = audit_results.get("performance", {})
    sa = audit_results.get("schema_advanced", {})

    def _perf_ms(pf_group: dict) -> int | None:
        """Extract response_time_ms from performance audit message."""
        perf = pf_group.get("response_time", {})
        msg_text = perf.get("message", "")
        m = re.search(r"([\d]+)ms", msg_text)
        return int(m.group(1)) if m else None

    def _word_count_val(ct_group: dict) -> int | None:
        """Extract word count from content audit message."""
        wc = ct_group.get("word_count", {})
        m = re.search(r"(\d+)\s+words?", wc.get("message", ""))
        return int(m.group(1)) if m else None

    def _internal_links_count(op_group: dict) -> int | None:
        il = op_group.get("internal_links", {})
        m = re.search(r"(\d+)", il.get("message", ""))
        return int(m.group(1)) if m else None

    return {
        # ── Existing boolean columns (v4.5 preserved) ─────────────────────────
        "ssl_valid":          is_pass(t, "ssl"),
        "has_sitemap":        is_pass(t, "sitemap"),
        "has_robots":         is_pass(t, "robots"),
        "broken_links_count": broken_count,
        "missing_h1":         is_fail(op, "h1"),
        "missing_alt_count":  alt_count,
        "uses_webp":          is_pass(im, "webp"),
        "has_json_ld":        is_pass(op, "schema"),
        "mobile_friendly":    is_pass(t, "mobile"),
        "missing_social":     missing_social,
        # Phase 2 Boolean columns
        "has_canonical":      is_pass(t, "canonical"),
        "has_page_title":     is_pass(op, "page_title"),
        "has_meta_desc":      is_pass(op, "meta_desc"),
        "has_og_tags":        is_pass(op, "og_tags"),
        "has_lazy_load":      is_pass(im, "lazy_load"),
        "has_contact":        is_pass(cv, "contact"),
        "has_whatsapp":       is_pass(cv, "whatsapp"),
        "has_trust":          is_pass(cv, "trust"),
        # Phase 3: UX Axis columns (v4.5.0)
        "has_cta":            is_pass(ux, "cta"),
        "cta_above_fold":     is_pass(ux, "cta_above_fold"),
        "has_hero_headline":  is_pass(ux, "hero_headline"),
        "font_size_ok":       is_pass(ux, "font_size"),
        "contrast_ok":        is_pass(ux, "contrast"),
        "nav_links_count":    _extract_nav_count(ux),
        "has_cookie_notice":  is_pass(ux, "cookie_notice"),
        "has_live_chat":      is_pass(ux, "live_chat"),
        "ux_score":           _compute_ux_score(ux),
        # ── v5.0 NEW columns ──────────────────────────────────────────────────
        # Technical extended
        "has_https_redirect":       is_pass(t, "https_redirect"),
        "redirect_chain_ok":        is_pass(t, "redirect_chain"),
        "has_mixed_content":        is_fail(t, "mixed_content"),   # True = mixed content FOUND (bad)
        "www_canonical_ok":         is_pass(t, "www_canonicalization"),
        # Onpage extended
        "has_noindex":              is_fail(op, "noindex"),         # True = noindex FOUND (bad)
        "heading_hierarchy_ok":     is_pass(op, "heading_hierarchy"),
        "internal_links_count":     _internal_links_count(op),
        "anchor_text_ok":           is_pass(op, "anchor_text_quality"),
        "image_filenames_ok":       is_pass(op, "image_filenames"),
        # UX extended
        "has_phone_number":         is_pass(ux, "phone_number"),
        "has_address":              is_pass(ux, "address_presence"),
        # Indexability
        "url_structure_ok":         is_pass(ix, "url_structure"),
        "www_nonwww_ok":            is_pass(ix, "www_vs_nonwww"),
        "soft_404_ok":              is_pass(ix, "soft_404"),
        # Content quality
        "word_count":               _word_count_val(ct),
        "duplicate_meta_ok":        is_pass(ct, "duplicate_meta"),
        "keyword_in_title_ok":      is_pass(ct, "keyword_in_title"),
        "reading_level_ok":         is_pass(ct, "reading_level"),
        # Local SEO
        "has_nap":                  is_pass(ls, "nap_consistency"),
        "has_local_business_schema": is_pass(ls, "local_business_schema"),
        "has_google_maps":          is_pass(ls, "google_maps_embed"),
        "city_in_title_ok":         is_pass(ls, "city_in_title"),
        "has_business_hours":       is_pass(ls, "business_hours"),
        # Performance
        "response_time_ms":         _perf_ms(pf),
        "page_size_ok":             is_pass(pf, "page_size"),
        "render_blocking_ok":       is_pass(pf, "render_blocking"),
        "gzip_enabled":             is_pass(pf, "gzip_compression"),
        "webp_coverage_ok":         is_pass(pf, "webp_images"),
        "minification_ok":          is_pass(pf, "minification"),
        # Schema advanced
        "has_faq_schema":           is_pass(sa, "faq_schema"),
        "has_product_schema":       is_pass(sa, "product_schema"),
        "has_breadcrumb_schema":    is_pass(sa, "breadcrumb_schema"),
        "has_review_schema":        is_pass(sa, "review_schema"),
        "schema_graph_ok":          is_pass(sa, "graph_schema"),
        # Text summary (used by email engine)
        "audit_summary":      _safe(summary),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — ACTIVITY LOG HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def _log_activity(db: AsyncSession, lead_id, message: str) -> None:
    try:
        log = ActivityLog(
            event_type="audit",
            lead_id=lead_id,
            message=_safe(message[:500]),  # cap length
        )
        db.add(log)
        await db.commit()
    except Exception as e:
        logger.warning(f"[audit_engine] _log_activity failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — MAIN ASYNC ENTRY POINT
# Called by: backend/app/routers/audits.py  (FastAPI BackgroundTask)
# Signature preserved from v3.x — do NOT change.
# ══════════════════════════════════════════════════════════════════════════════

async def _db_micro(callback):
    """
    Open a fresh DB session, run *callback(db)*, commit, and close immediately.
    Using short-lived micro-sessions ensures that pool connections are returned
    between expensive network/CPU operations (audit, PDF) instead of being held
    for the entire multi-minute audit lifecycle.
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await callback(db)
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


async def run_audit(lead_id: str) -> None:
    """
    Main audit entry point. Called as a FastAPI background task.
    Signature is identical to v3.x — the router does not need to change.

    Flow:
      1. Short DB read: load lead + audit record, mark as running, commit & CLOSE session
      2. classify_site() — async network I/O, no DB connection held
      3. If NOT REAL → short DB write: store SITE_STATUS, mark done, return
      4. _run_audit_sync(website) via run_in_executor — no DB connection held
      5. extract_business_name() — pure CPU, no DB
      6. Short DB write: write all audit columns, mark done, commit & CLOSE
      7. build_pdf() via run_in_executor — no DB connection held
      8. Short DB write: save PDF path, commit & CLOSE
      9. Short DB write: log completion, commit & CLOSE

    Each DB session is open for < 100ms; connections return to the pool between steps.
    """
    # ── PHASE 1: Load lead + prepare audit record (short DB write) ────────────
    lead_data = {}   # snapshot of lead fields we need outside DB
    audit_id  = None

    try:
        async def _phase1(db):
            lead = await db.get(Lead, lead_id)
            if not lead:
                logger.error(f"[audit_engine] Lead {lead_id} not found")
                return None

            website = (lead.website or "").strip()
            if not website:
                logger.warning(f"[audit_engine] Lead {lead_id} has no website — skipping")
                return None

            from sqlalchemy import select as _select
            audit_result = await db.execute(_select(Audit).where(Audit.lead_id == lead.id))
            audit = audit_result.scalar_one_or_none()

            if not audit:
                audit = Audit(lead_id=lead.id, status=AuditStatus.pending)
                db.add(audit)
                await db.flush()

            audit.status = AuditStatus.running
            if lead.status not in (LeadStatus.emailed, LeadStatus.replied, LeadStatus.converted):
                lead.status = LeadStatus.auditing

            # Capture what we need before session closes
            return {
                "audit_id":      audit.id,
                "lead_id":       lead.id,
                "website":       website,
                "business_name": lead.business_name,
                "lead_status":   lead.status,
            }

        lead_data = await _db_micro(_phase1)
    except Exception as e:
        logger.exception(f"[audit_engine] Phase-1 DB error for lead {lead_id}: {e}")
        return

    if not lead_data:
        return  # lead not found or no website

    website       = lead_data["website"]
    audit_id      = lead_data["audit_id"]
    lead_uuid     = lead_data["lead_id"]
    business_name = lead_data["business_name"]

    # ── PHASE 2: Site classification (async network I/O — NO DB connection) ───
    logger.info(f"[audit_engine] Starting site classification for {website}")
    try:
        site_type, site_reason = await classify_site(website)
    except Exception as e:
        logger.error(f"[audit_engine] classify_site failed for {website}: {e}")
        site_type   = SiteType.REAL
        site_reason = f"classify_site error (fallback to REAL): {e}"

    logger.info(f"[audit_engine] Site classification: {site_type} — {site_reason}")

    if site_type != SiteType.REAL:
        # ── PHASE 2b: Write skip result (short DB write) ──────────────────────
        labels = {
            SiteType.PARKED:      "parked domain / for sale",
            SiteType.DEMO:        "demo / coming-soon / placeholder page",
            SiteType.NOT_FOUND:   "page not found (404 / deleted)",
            SiteType.UNREACHABLE: "unreachable / offline",
        }
        label = labels.get(site_type, str(site_type))

        try:
            async def _skip_write(db):
                audit = await db.get(Audit, audit_id)
                lead  = await db.get(Lead, lead_uuid)
                if audit:
                    audit.error_message = site_status_tag(site_type)
                    audit.audit_summary = f"Website is a {label}. Full SEO audit skipped. {site_reason}"
                    audit.status        = AuditStatus.done
                if lead and lead.status not in (LeadStatus.emailed, LeadStatus.replied, LeadStatus.converted):
                    lead.status = LeadStatus.audited
                log = ActivityLog(
                    event_type="audit_skipped",
                    lead_id=lead_uuid,
                    message=_safe(f"Skipped audit for {business_name} ({website}): {label}. {site_reason}"),
                )
                db.add(log)

            await _db_micro(_skip_write)
        except Exception as e:
            logger.error(f"[audit_engine] skip-write DB error for {website}: {e}")

        logger.info(f"[audit_engine] Audit skipped for {website} — {label}")
        return  # no PDF, no further checks

    audit_url = website
    try:
        audit_url = await resolve_live_url(website)
    except Exception as e:
        logger.warning(f"[audit_engine] resolve_live_url failed for {website}: {e}")

    logger.info(
        f"[audit_engine] Site is live — proceeding with 19-factor audit for "
        f"{audit_url} (lead URL: {website})"
    )

    # ── PHASE 3: 19-factor audit in thread pool (NO DB connection) ───────────
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(None, _run_audit_sync, audit_url)
    except Exception as e:
        logger.error(f"[audit_engine] _run_audit_sync failed for {audit_url}: {e}")
        try:
            async def _fail_write(db):
                audit = await db.get(Audit, audit_id)
                lead  = await db.get(Lead, lead_uuid)
                if audit:
                    audit.status        = AuditStatus.failed
                    audit.error_message = str(e)
                if lead and lead.status not in (LeadStatus.emailed, LeadStatus.replied, LeadStatus.converted):
                    lead.status = LeadStatus.new
                log = ActivityLog(
                    event_type="audit",
                    lead_id=lead_uuid,
                    message=_safe(f"Audit failed: {e}"[:500]),
                )
                db.add(log)
            await _db_micro(_fail_write)
        except Exception as db_err:
            logger.error(f"[audit_engine] fail-write DB error: {db_err}")
        return

    audit_results = data["audit_results"]
    score         = data["score"]
    site_summary  = data.get("site_summary", {})
    page_audits   = data.get("page_audits", [])
    homepage_html = data.get("html", "")
    found_email   = data.get("found_email")
    email_source  = data.get("email_source", "not_found")

    # ── PHASE 4: Extract business name (pure CPU, no DB) ─────────────────────
    suggested_name = None
    try:
        suggested_name, name_source = extract_business_name(homepage_html, audit_url)
        if suggested_name:
            logger.info(f"[audit_engine] Extracted name '{suggested_name}' via {name_source}")
    except Exception as e:
        logger.warning(f"[audit_engine] extract_business_name failed: {e}")

    # ── PHASE 4b: Domain email correction (pure CPU, no DB) ──────────────────
    # If the scraper stored a third-party email (e.g. support@webador.com) but
    # the site has its own domain email (info@vertexindustries.es), update it.
    corrected_email     = None  # will be set if we decide to update
    old_email_snapshot  = None  # original email — captured in phase 5 DB write
    if found_email:
        logger.info(f"[audit_engine] Email finder result: {found_email} ({email_source})")

    # ── PHASE 5: Write all audit results to DB (short DB write) ──────────────
    db_cols = _map_to_db_columns(audit_results, score)

    # Detect country/currency from homepage HTML (non-fatal)
    geo = {"country_code": None, "currency_code": None, "currency_symbol": None, "detected_via": None}
    try:
        geo = detect_country(homepage_html, audit_url)
        logger.info(
            f"[audit_engine] Geo detection: {geo['country_code']} "
            f"({geo['currency_code']}) via {geo['detected_via']}"
        )
    except Exception as e:
        logger.warning(f"[audit_engine] detect_country failed: {e}")

    try:
        async def _results_write(db):
            nonlocal corrected_email, old_email_snapshot
            audit = await db.get(Audit, audit_id)
            lead  = await db.get(Lead, lead_uuid)
            if not audit:
                return

            audit.ssl_valid          = db_cols["ssl_valid"]
            audit.has_sitemap        = db_cols["has_sitemap"]
            audit.has_robots         = db_cols["has_robots"]
            audit.broken_links_count = db_cols["broken_links_count"]
            audit.missing_h1         = db_cols["missing_h1"]
            audit.missing_alt_count  = db_cols["missing_alt_count"]
            audit.uses_webp          = db_cols["uses_webp"]
            audit.has_json_ld        = db_cols["has_json_ld"]
            audit.mobile_friendly    = db_cols["mobile_friendly"]
            audit.missing_social     = db_cols["missing_social"]
            audit.has_canonical      = db_cols["has_canonical"]
            audit.has_page_title     = db_cols["has_page_title"]
            audit.has_meta_desc      = db_cols["has_meta_desc"]
            audit.has_og_tags        = db_cols["has_og_tags"]
            audit.has_lazy_load      = db_cols["has_lazy_load"]
            audit.has_contact        = db_cols["has_contact"]
            audit.has_whatsapp       = db_cols["has_whatsapp"]
            audit.has_trust          = db_cols["has_trust"]
            # Phase 3: UI/UX Axis (v4.5.0)
            audit.has_cta            = db_cols["has_cta"]
            audit.cta_above_fold     = db_cols["cta_above_fold"]
            audit.has_hero_headline  = db_cols["has_hero_headline"]
            audit.font_size_ok       = db_cols["font_size_ok"]
            audit.contrast_ok        = db_cols["contrast_ok"]
            audit.nav_links_count    = db_cols["nav_links_count"]
            audit.has_cookie_notice  = db_cols["has_cookie_notice"]
            audit.has_live_chat      = db_cols["has_live_chat"]
            audit.ux_score           = db_cols["ux_score"]
            # ── v5.0 NEW columns (Groups B-G) — added 2026-05-19 ────────────────────
            # Technical extended (Group B)
            audit.has_https_redirect    = db_cols.get("has_https_redirect")
            audit.redirect_chain_ok     = db_cols.get("redirect_chain_ok")
            audit.has_mixed_content     = db_cols.get("has_mixed_content")
            audit.www_canonical_ok      = db_cols.get("www_canonical_ok")
            # Onpage extended (Group B)
            audit.has_noindex           = db_cols.get("has_noindex")
            audit.heading_hierarchy_ok  = db_cols.get("heading_hierarchy_ok")
            audit.internal_links_count  = db_cols.get("internal_links_count")
            audit.anchor_text_ok        = db_cols.get("anchor_text_ok")
            audit.image_filenames_ok    = db_cols.get("image_filenames_ok")
            # UX extended (Group B)
            audit.has_phone_number      = db_cols.get("has_phone_number")
            audit.has_address           = db_cols.get("has_address")
            # Indexability (Group C)
            audit.url_structure_ok      = db_cols.get("url_structure_ok")
            audit.www_nonwww_ok         = db_cols.get("www_nonwww_ok")
            audit.soft_404_ok           = db_cols.get("soft_404_ok")
            # Content quality (Group D)
            audit.word_count            = db_cols.get("word_count")
            audit.duplicate_meta_ok     = db_cols.get("duplicate_meta_ok")
            audit.keyword_in_title_ok   = db_cols.get("keyword_in_title_ok")
            audit.reading_level_ok      = db_cols.get("reading_level_ok")
            # Local SEO (Group E)
            audit.has_nap                    = db_cols.get("has_nap")
            audit.has_local_business_schema  = db_cols.get("has_local_business_schema")
            audit.has_google_maps            = db_cols.get("has_google_maps")
            audit.city_in_title_ok           = db_cols.get("city_in_title_ok")
            audit.has_business_hours         = db_cols.get("has_business_hours")
            # Performance (Group F)
            audit.response_time_ms      = db_cols.get("response_time_ms")
            audit.page_size_ok          = db_cols.get("page_size_ok")
            audit.render_blocking_ok    = db_cols.get("render_blocking_ok")
            audit.gzip_enabled          = db_cols.get("gzip_enabled")
            audit.webp_coverage_ok      = db_cols.get("webp_coverage_ok")
            audit.minification_ok       = db_cols.get("minification_ok")
            # Schema advanced (Group G)
            audit.has_faq_schema        = db_cols.get("has_faq_schema")
            audit.has_product_schema    = db_cols.get("has_product_schema")
            audit.has_breadcrumb_schema = db_cols.get("has_breadcrumb_schema")
            audit.has_review_schema     = db_cols.get("has_review_schema")
            audit.schema_graph_ok       = db_cols.get("schema_graph_ok")
            # ── end v5.0 columns ───────────────────────────────────────────────
            audit.seo_score          = score
            audit.audited_url        = audit_url
            audit.audit_results      = audit_results
            audit.site_summary       = site_summary
            audit.page_audits        = page_audits
            audit.audit_summary      = db_cols["audit_summary"]
            audit.status             = AuditStatus.done
            # Geo-smart currency detection
            audit.country_code    = geo.get("country_code")
            audit.currency_code   = geo.get("currency_code")
            audit.currency_symbol = geo.get("currency_symbol")
            audit.detected_via    = geo.get("detected_via")
            if suggested_name:
                audit.suggested_name = suggested_name

            if lead and lead.status not in (LeadStatus.emailed, LeadStatus.replied, LeadStatus.converted):
                lead.status = LeadStatus.audited

            # ── Domain email auto-correction ──────────────────────────────────
            # Only update email if:
            #   - We found a domain-matched email on the website
            #   - The current stored email does NOT belong to the site's domain
            #   - The lead has never been emailed (don't surprise an already-sent campaign)
            if lead and found_email:
                from auditor.email_finder import should_update_email as _sue
                from urllib.parse import urlparse as _up
                host = _up(audit_url).netloc.lower().lstrip("www.")
                if _sue(lead.email or "", found_email, host):
                    old_email_snapshot  = lead.email
                    corrected_email     = found_email
                    lead.email          = found_email
                    logger.info(
                        f"[audit_engine] Email corrected: {old_email_snapshot} → "
                        f"{found_email} ({email_source})"
                    )

        await _db_micro(_results_write)
    except Exception as e:
        logger.error(f"[audit_engine] results-write DB error for {website}: {e}")
        return

    # ── PHASE 6: Generate PDF in thread pool (NO DB connection) ──────────────
    pdf_output_path = None
    try:
        from app.config import settings
        reports_dir = getattr(settings, "REPORTS_DIR", None)
        if not reports_dir or not os.path.isabs(reports_dir):
            reports_dir = str(Path(__file__).resolve().parents[2] / "reports")
        os.makedirs(reports_dir, exist_ok=True)
        pdf_output_path = os.path.join(reports_dir, f"audit_{lead_id}.pdf")

        await loop.run_in_executor(
            None,
            lambda: build_pdf(
                url=audit_url,
                audit_results=audit_results,
                score=score,
                output_path=pdf_output_path,
                site_summary=site_summary,
                page_audits=page_audits,
            )
        )
        logger.info(f"[audit_engine] PDF saved: {pdf_output_path}")
    except Exception as e:
        logger.error(f"[audit_engine] PDF generation failed for {website}: {e}")
        pdf_output_path = None  # non-fatal

    # ── PHASE 7: Save PDF path + log completion (short DB write) ─────────────
    try:
        async def _completion_write(db):
            if pdf_output_path:
                audit = await db.get(Audit, audit_id)
                if audit:
                    audit.pdf_path = pdf_output_path

            # Main completion log
            log = ActivityLog(
                event_type="audit_done",
                lead_id=lead_uuid,
                message=_safe(
                    f"Audit complete for {business_name} ({audit_url}). "
                    f"Score: {score}/100. {len(page_audits)} pages crawled."
                ),
            )
            db.add(log)

            # Email correction log (if applicable)
            if corrected_email and old_email_snapshot:
                correction_log = ActivityLog(
                    event_type="email_corrected",
                    lead_id=lead_uuid,
                    message=_safe(
                        f"Email auto-corrected during audit: "
                        f"{old_email_snapshot} → {corrected_email} "
                        f"(found via {email_source} on {audit_url})"
                    ),
                )
                db.add(correction_log)

        await _db_micro(_completion_write)
    except Exception as e:
        logger.error(f"[audit_engine] completion-write DB error for {website}: {e}")

    if corrected_email:
        logger.info(
            f"[audit_engine] Email auto-corrected for {business_name}: "
            f"{old_email_snapshot} → {corrected_email}"
        )
    logger.info(f"[audit_engine] Audit done for {website} — score {score}/100")
