# reporter/pdf_report.py — Professional branded PDF report generator (ReportLab)
# Complete rewrite for clean, readable layout

import os
import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether, ListFlowable, ListItem
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.utils import simpleSplit
from config import BRANDING, SCORE_BANDS

# ── Colour palette ─────────────────────────────────────────────────────────────
def _c(r, g, b): return colors.Color(r, g, b)
def _rgb(t):     return colors.Color(*t)

C_PRIMARY   = _rgb(BRANDING["primary_color"])
C_ACCENT    = _rgb(BRANDING["accent_color"])
C_DANGER    = _rgb(BRANDING["danger_color"])
C_WARN      = _rgb(BRANDING["warn_color"])
C_PASS      = _rgb(BRANDING["pass_color"])
C_DARK      = _rgb(BRANDING["dark_color"])
C_LIGHT     = _rgb(BRANDING["light_gray"])
C_WHITE     = colors.white
C_BLACK     = colors.black
C_MUTED     = _c(0.55, 0.55, 0.62)
C_BG_PAGE   = _c(0.97, 0.97, 0.99)   # very subtle off-white page bg

STATUS_COLORS = {"PASS": C_PASS,   "WARN": C_WARN,  "FAIL": C_DANGER}
STATUS_LABEL  = {"PASS": "PASS",   "WARN": "WARN",  "FAIL": "FAIL"}
STATUS_ICONS  = {"PASS": u"\u2714", "WARN": u"\u26a0", "FAIL": u"\u2718"}
PRIORITY_LABEL = {"FAIL": "CRITICAL", "WARN": "REVIEW"}

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ── Typography ─────────────────────────────────────────────────────────────────
def _styles():
    s = {}

    def ps(name, **kw):
        s[name] = ParagraphStyle(name, **kw)

    # Cover
    ps("cov_eyebrow",   fontName="Helvetica",       fontSize=9,  textColor=_c(0.7,0.78,1.0), leading=13, spaceAfter=4)
    ps("cov_title",     fontName="Helvetica-Bold",  fontSize=32, textColor=C_WHITE,           leading=38, spaceAfter=6)
    ps("cov_url",       fontName="Helvetica-Bold",  fontSize=14, textColor=C_ACCENT,          leading=20, spaceAfter=4)
    ps("cov_meta",      fontName="Helvetica",       fontSize=10, textColor=_c(0.78,0.85,1.0), leading=15, spaceAfter=2)

    # Headings
    ps("h1",            fontName="Helvetica-Bold",  fontSize=16, textColor=C_PRIMARY,         leading=22, spaceBefore=12, spaceAfter=4, keepWithNext=True)
    ps("h2",            fontName="Helvetica-Bold",  fontSize=12, textColor=C_DARK,            leading=17, spaceBefore=10, spaceAfter=3, keepWithNext=True)
    ps("h3",            fontName="Helvetica-Bold",  fontSize=10, textColor=C_DARK,            leading=14, spaceAfter=2, keepWithNext=True)

    # Body text
    ps("body",          fontName="Helvetica",       fontSize=9.5, textColor=_c(0.18,0.18,0.22), leading=14, spaceAfter=3)
    ps("body_small",    fontName="Helvetica",       fontSize=8.5, textColor=_c(0.30,0.30,0.38), leading=13, spaceAfter=2)
    ps("body_italic",   fontName="Helvetica-Oblique", fontSize=8.5, textColor=_c(0.42,0.42,0.52), leading=12, spaceAfter=3)

    # Fix / detail inside test cards
    ps("fix",           fontName="Helvetica",       fontSize=9,  textColor=_c(0.22,0.28,0.42), leading=13, spaceAfter=2)
    ps("detail",        fontName="Helvetica-Oblique", fontSize=8.5, textColor=_c(0.45,0.45,0.55), leading=12)

    # Score display
    ps("score_num",     fontName="Helvetica-Bold",  fontSize=42, textColor=C_WHITE,           leading=48, alignment=TA_CENTER)
    ps("score_of",      fontName="Helvetica",       fontSize=11, textColor=_c(0.85,0.87,1.0), leading=15, alignment=TA_CENTER)
    ps("score_band",    fontName="Helvetica-Bold",  fontSize=13, textColor=C_WHITE,           leading=18, alignment=TA_CENTER)
    ps("score_desc",    fontName="Helvetica",       fontSize=10, textColor=_c(0.2,0.22,0.32), leading=15, alignment=TA_JUSTIFY)
    ps("badge_icon",    fontName="Helvetica-Bold",  fontSize=13, textColor=C_WHITE,           leading=15, alignment=TA_CENTER)
    ps("badge_label",   fontName="Helvetica-Bold",  fontSize=9.5, textColor=C_WHITE,          leading=12, alignment=TA_CENTER)

    # Table cells
    ps("th",            fontName="Helvetica-Bold",  fontSize=9,  textColor=C_WHITE,           leading=13, alignment=TA_LEFT)
    ps("td",            fontName="Helvetica",       fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=13)
    ps("td_center",     fontName="Helvetica",       fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=13, alignment=TA_CENTER)
    ps("td_url",        fontName="Helvetica",       fontSize=7.5, textColor=_c(0.10,0.22,0.55), leading=11)
    ps("td_issue",      fontName="Helvetica",       fontSize=8,   textColor=_c(0.18,0.18,0.24), leading=12)
    ps("td_issue_head", fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=12)

    # Priority table
    ps("pri_critical",  fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.7,0.05,0.05), leading=12, alignment=TA_CENTER)
    ps("pri_high",      fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.85,0.3,0.05), leading=12, alignment=TA_CENTER)
    ps("pri_medium",    fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.7,0.5,0.0),   leading=12, alignment=TA_CENTER)
    ps("pri_low",       fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.2,0.4,0.7),   leading=12, alignment=TA_CENTER)
    ps("pri_review",    fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.6,0.45,0.0),  leading=12, alignment=TA_CENTER)
    ps("pri_msg",       fontName="Helvetica",       fontSize=8.5, textColor=_c(0.15,0.15,0.22), leading=13)
    ps("pri_group",     fontName="Helvetica",       fontSize=8.5, textColor=_c(0.35,0.35,0.45), leading=13, alignment=TA_CENTER)

    # Misc
    ps("footer",        fontName="Helvetica",       fontSize=7.5, textColor=_c(0.55,0.55,0.65), leading=11, alignment=TA_CENTER)
    ps("caption",       fontName="Helvetica-Oblique", fontSize=8.5, textColor=C_MUTED,         leading=12)
    ps("intro",         fontName="Helvetica",       fontSize=10.5, textColor=_c(0.15,0.18,0.28), leading=16, spaceAfter=6, alignment=TA_JUSTIFY)

    return s


# ── Page header/footer ────────────────────────────────────────────────────────
def _page_chrome(url, report_date, agency):
    def _draw(canvas, doc):
        canvas.saveState()
        W, H = A4

        # Top bar
        canvas.setFillColor(C_DARK)
        canvas.rect(0, H - 16*mm, W, 16*mm, fill=1, stroke=0)
        # Accent strip
        canvas.setFillColor(C_PRIMARY)
        canvas.rect(0, H - 17.5*mm, W, 1.5*mm, fill=1, stroke=0)

        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(C_WHITE)
        canvas.drawString(MARGIN, H - 10*mm, f"SEO Audit  \u2022  {url[:70]}")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_c(0.72,0.78,0.92))
        canvas.drawRightString(W - MARGIN, H - 10*mm, f"Page {doc.page}")

        # Bottom bar
        canvas.setFillColor(_c(0.94, 0.94, 0.97))
        canvas.rect(0, 0, W, 11*mm, fill=1, stroke=0)
        canvas.setStrokeColor(_c(0.82,0.82,0.88))
        canvas.line(0, 11*mm, W, 11*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_c(0.50,0.50,0.60))
        footer = f"{BRANDING.get('report_footer', agency)}  \u00b7  Generated: {report_date}"
        canvas.drawCentredString(W/2, 3.8*mm, footer)

        canvas.restoreState()
    return _draw


# ── Utility: safe XML escaping ─────────────────────────────────────────────────
def _safe(text: str) -> str:
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>"))


def _trunc(text: str, n: int) -> str:
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= n else text[:n-1] + "\u2026"


# ── Cover page ────────────────────────────────────────────────────────────────
def _cover(url, report_date, score, agency, styles, url_info=None):
    band_label = next((l for lo,hi,l,_ in SCORE_BANDS if lo <= score < hi), "")
    score_bg = C_DANGER if score < 40 else (C_WARN if score < 65 else (C_ACCENT if score < 85 else C_PASS))

    req_url = (url_info.get("requested_url") if url_info else None) or url
    final_url = url_info.get("final_url") if url_info else None
    canonical_url = url_info.get("canonical_url") if url_info else None
    is_redirected = bool(url_info.get("is_redirected") if url_info else False)

    # Full-width dark background block
    cover_rows = [
        [Paragraph("SEO PERFORMANCE & TECHNICAL AUDIT", styles["cov_eyebrow"])],
        [Paragraph("Client Website Analysis Report", styles["cov_title"])],
        [Spacer(1, 4*mm)],
        [Paragraph(_safe(req_url), styles["cov_url"])],
    ]
    if is_redirected and final_url and final_url != req_url:
        cover_rows.append([Paragraph(f"Final Destination: {_safe(final_url)} (Redirected)", styles["cov_meta"])])
    if canonical_url and canonical_url != req_url and canonical_url != final_url:
        cover_rows.append([Paragraph(f"Declared Canonical: {_safe(canonical_url)}", styles["cov_meta"])])
    cover_rows.extend([
        [Paragraph(f"Prepared by {agency}", styles["cov_meta"])],
        [Paragraph(report_date, styles["cov_meta"])],
    ])
    bg_table = Table(cover_rows, colWidths=[CONTENT_W])
    bg_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 20),
        ("RIGHTPADDING",  (0,0), (-1,-1), 20),
    ]))

    # Score pill below
    score_rows = [
        [Paragraph(str(score), styles["score_num"])],
        [Paragraph("out of 100", styles["score_of"])],
        [Spacer(1, 2*mm)],
        [Paragraph(band_label, styles["score_band"])],
    ]
    score_table = Table(score_rows, colWidths=[50*mm])
    score_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), score_bg),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))

    # Two-column layout: score on left, intro text on right
    band_desc = next((d for lo,hi,_,d in SCORE_BANDS if lo <= score < hi), "")
    intro_col = [Paragraph(band_desc, styles["intro"])] if band_desc else []

    side_data = [[score_table, intro_col]]
    side_table = Table(side_data, colWidths=[54*mm, CONTENT_W - 58*mm])
    side_table.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",  (1,0), (1,-1), 10),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))

    # URL Identity & Audit Scope Block
    url_id_rows = [
        [Paragraph("Audit Target Scope", styles["th"]), Paragraph("Verified URL Identity & Routing", styles["th"])],
        [Paragraph("Requested URL", styles["body_small"]), Paragraph(f"<b>{_safe(req_url)}</b>", styles["body_small"])],
        [Paragraph("Final Destination URL", styles["body_small"]), Paragraph(f"{_safe(final_url or req_url)} ({'Redirected' if is_redirected else 'Direct response'})", styles["body_small"])],
        [Paragraph("Declared Canonical", styles["body_small"]), Paragraph(_safe(canonical_url or 'None declared'), styles["body_small"])],
        [Paragraph("Analysis Methodology", styles["body_small"]), Paragraph("62-Factor Canonical Contract \u00b7 Bounded Crawl Engine \u00b7 Synthetic Lab Web Vitals", styles["body_small"])],
    ]
    url_table = Table(url_id_rows, colWidths=[42*mm, CONTENT_W - 42*mm])
    url_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), _c(0.2,0.25,0.35)),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, _c(0.96,0.97,0.99)]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.85,0.85,0.9)),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))

    return [bg_table, Spacer(1, 6*mm), side_table, Spacer(1, 4*mm), url_table, Spacer(1, 5*mm)]


# ── Section header helper ─────────────────────────────────────────────────────
def _section(title, styles, color=None):
    color = color or C_PRIMARY
    return [
        Paragraph(title, styles["h1"]),
        HRFlowable(width="100%", thickness=2, color=color, spaceAfter=4*mm),
    ]


# ── Score overview bar ────────────────────────────────────────────────────────
def _overview_bar(audit_results, styles):
    """Horizontal stat strip: total tests, pass, warn, fail counts."""
    total = pass_ = warn_ = fail_ = 0
    for tests in audit_results.values():
        for r in tests.values():
            total += 1
            s = r.get("status", "FAIL")
            if s == "PASS": pass_ += 1
            elif s == "WARN": warn_ += 1
            else: fail_ += 1

    cells = [
        [Paragraph(str(total), styles["score_num"]), Paragraph("Total Checks", styles["score_of"])],
        [Paragraph(str(pass_),  styles["score_num"]), Paragraph("Passed",       styles["score_of"])],
        [Paragraph(str(warn_),  styles["score_num"]), Paragraph("Warnings",     styles["score_of"])],
        [Paragraph(str(fail_),  styles["score_num"]), Paragraph("Failed",       styles["score_of"])],
    ]

    rows = [[c[0] for c in cells], [c[1] for c in cells]]
    t = Table(rows, colWidths=[(CONTENT_W/4)] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,-1), C_PRIMARY),
        ("BACKGROUND",    (1,0), (1,-1), C_PASS),
        ("BACKGROUND",    (2,0), (2,-1), C_WARN),
        ("BACKGROUND",    (3,0), (3,-1), C_DANGER),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("FONTSIZE",      (0,0), (-1,-1), 10),
    ]))
    return [t]


# ── Group summary table ───────────────────────────────────────────────────────
def _group_table(audit_results, styles):
    header = [
        Paragraph("Category",     styles["th"]),
        Paragraph("Checks",       styles["th"]),
        Paragraph(u"\u2714 Pass", styles["th"]),
        Paragraph(u"\u26a0 Warn", styles["th"]),
        Paragraph(u"\u2718 Fail", styles["th"]),
        Paragraph("Score",        styles["th"]),
    ]
    rows = [header]
    for group, tests in audit_results.items():
        total  = len(tests)
        passes = sum(1 for t in tests.values() if t["status"] == "PASS")
        warns  = sum(1 for t in tests.values() if t["status"] == "WARN")
        fails  = sum(1 for t in tests.values() if t["status"] == "FAIL")
        pct    = int(100 * passes / max(total, 1))
        rows.append([
            Paragraph(group.title(), styles["body"]),
            Paragraph(str(total),   styles["td_center"]),
            Paragraph(str(passes),  styles["td_center"]),
            Paragraph(str(warns),   styles["td_center"]),
            Paragraph(str(fails),   styles["td_center"]),
            Paragraph(f"{pct}%",    styles["td_center"]),
        ])

    col_w = [68*mm, 18*mm, 18*mm, 18*mm, 18*mm, 18*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 9),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.4, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]
    # Colour the fail count cells red if > 0
    for i, row in enumerate(rows[1:], 1):
        fail_val = int("".join(filter(str.isdigit, rows[i][4].text if hasattr(rows[i][4], "text") else "0")) or "0")
    t.setStyle(TableStyle(style_cmds))
    return [t]


# ── Individual test card ──────────────────────────────────────────────────────
def _test_card(test_id: str, result: dict, styles) -> list:
    status  = result.get("status", "FAIL")
    icon    = STATUS_ICONS.get(status, "?")
    color   = STATUS_COLORS.get(status, C_DANGER)
    label   = STATUS_LABEL.get(status, status)
    priority = (result.get("severity") or _resolve_priority_label(test_id, status, result)).upper()

    # Status badge (left column)
    badge_rows = [
        [Paragraph(icon,    styles["badge_icon"])],
        [Paragraph(label,   styles["badge_label"])],
    ]
    badge = Table(badge_rows, colWidths=[20*mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), color),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))

    # Content (right column)
    name_text = test_id.replace("_", " ").title()
    content = [Paragraph(f"<b>{_safe(name_text)}</b> &nbsp;&nbsp;<font size=7.5 color='#555'>[{priority}]</font>", styles["h3"])]
    if result.get("message"):
        content.append(Paragraph(_safe(result["message"]), styles["body"]))
    if result.get("value") is not None and str(result.get("value")).strip() != "":
        val_str = str(result.get("value"))
        unit = str(result.get("unit") or "")
        # Clarify alt text when 0 missing
        if test_id in ("images.alt_text", "alt_text") and result.get("status") == "PASS" and val_str == "0":
            content.append(Paragraph(f"<b>Observed Value:</b> <font color='#1e3a8a'>0 missing alt text</font> (100% alt coverage)", styles["body_small"]))
        elif test_id in ("links.broken_links", "broken_links"):
            if val_str == "0":
                content.append(Paragraph(f"<b>Observed Value:</b> <font color='#1e3a8a'>0 confirmed broken links</font>", styles["body_small"]))
            else:
                content.append(Paragraph(f"<b>Observed Value:</b> <font color='#dc2626'>{_safe(val_str)} confirmed broken link(s)</font>", styles["body_small"]))
        else:
            content.append(Paragraph(f"<b>Observed Value:</b> <font color='#1e3a8a'>{_safe(_trunc(val_str, 90))}</font> {unit}".strip(), styles["body_small"]))
    if result.get("fix"):
        content.append(Paragraph(f"<b>Recommended Action:</b> {_safe(result['fix'])}", styles["fix"]))
    if result.get("detail"):
        content.append(Paragraph(_safe(result["detail"]), styles["detail"]))

    # 2-col layout: badge | content
    card_data = [[badge, content]]
    card_w    = CONTENT_W
    card = Table(card_data, colWidths=[22*mm, card_w - 22*mm])
    card.setStyle(TableStyle([
        ("BACKGROUND",    (1,0), (1,-1), _c(0.975,0.975,0.985)),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (1,0), (1,-1), 10),
        ("RIGHTPADDING",  (1,0), (1,-1), 10),
        ("TOPPADDING",    (1,0), (1,-1), 8),
        ("BOTTOMPADDING", (1,0), (1,-1), 8),
        ("TOPPADDING",    (0,0), (0,-1), 0),
        ("BOTTOMPADDING", (0,0), (0,-1), 0),
        ("LEFTPADDING",   (0,0), (0,-1), 0),
        ("RIGHTPADDING",  (0,0), (0,-1), 0),
        ("LINEBELOW",     (0,0), (-1,-1), 0.5, _c(0.88,0.88,0.92)),
    ]))
    return [KeepTogether([card, Spacer(1, 2.5*mm)])]


# ── Site-wide crawl stats strip ───────────────────────────────────────────────
def _crawl_stats(site_summary, styles):
    ss    = site_summary
    total = ss.get("total_pages", 0)
    sc    = ss.get("status_counts", {})
    sitemap_count = ss.get("sitemap_url_count", 0)
    link_discovered = ss.get("link_discovered_count", 0)
    total_discovered = ss.get("total_discovered_count", total)

    story = []

    # Multi-source discovery strip
    if sitemap_count > 0 or link_discovered > 0:
        disc_cells = [
            [Paragraph(str(sitemap_count), styles["score_num"]),
             Paragraph(str(link_discovered), styles["score_num"]),
             Paragraph(str(total_discovered), styles["score_num"]),
             Paragraph(str(total), styles["score_num"])],
            [Paragraph("Sitemap URLs", styles["score_of"]),
             Paragraph("Link Discovered", styles["score_of"]),
             Paragraph("Total Discovered", styles["score_of"]),
             Paragraph("Pages Crawled", styles["score_of"])],
        ]
        t_disc = Table(disc_cells, colWidths=[(CONTENT_W/4)]*4)
        t_disc.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), C_DARK),
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(t_disc)
        story.append(Spacer(1, 3*mm))

    data = [
        [Paragraph(str(total),          styles["score_num"]),
         Paragraph(str(sc.get("PASS",0)), styles["score_num"]),
         Paragraph(str(sc.get("WARN",0)), styles["score_num"]),
         Paragraph(str(sc.get("FAIL",0)), styles["score_num"])],
        [Paragraph("Pages Crawled",     styles["score_of"]),
         Paragraph("Clean Pages",       styles["score_of"]),
         Paragraph("Warnings",          styles["score_of"]),
         Paragraph("Issues",            styles["score_of"])],
    ]
    t = Table(data, colWidths=[CONTENT_W/4]*4)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,-1), C_PRIMARY),
        ("BACKGROUND",    (1,0), (1,-1), C_PASS),
        ("BACKGROUND",    (2,0), (2,-1), C_WARN),
        ("BACKGROUND",    (3,0), (3,-1), C_DANGER),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t)

    if ss.get("discovery_explanation"):
        story.append(Spacer(1, 2.5*mm))
        story.append(Paragraph(
            f"<b>Crawl Discovery Notes:</b> {_safe(ss['discovery_explanation'])}",
            styles["body_small"]
        ))

    arch = ss.get("architecture")
    if arch:
        story.append(Spacer(1, 2.5*mm))
        arch_type = arch.get("architecture", "").replace("_", " ").title()
        conf = arch.get("confidence", "medium").title()
        sec_count = arch.get("section_count", 0)
        doc_count = arch.get("distinct_document_count", total)
        summary = arch.get("summary", "")
        ev_list = arch.get("evidence", [])
        ev_text = ("<br/>• " + "<br/>• ".join([_safe(e) for e in ev_list])) if ev_list else ""
        
        arch_cells = [
            [Paragraph(f"<b>Site Architecture:</b> {arch_type} ({conf} Confidence) | <b>In-Page Sections Audited:</b> {sec_count} | <b>HTML Documents:</b> {doc_count}", styles["td_issue_head"])],
            [Paragraph(f"{_safe(summary)}{ev_text}", styles["body_small"])],
        ]
        t_arch = Table(arch_cells, colWidths=[CONTENT_W])
        t_arch.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), _c(0.95, 0.97, 1.0)),
            ("BOX",        (0,0), (-1,-1), 0.5, C_PRIMARY),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(t_arch)

    story.append(Spacer(1, 4*mm))
    return story


# ── Common issues table ───────────────────────────────────────────────────────
def _common_issues_table(top_issues, total_pages, styles):
    header = [
        Paragraph("Issue Found",        styles["th"]),
        Paragraph("Pages Affected",     styles["th"]),
        Paragraph("% of Site",          styles["th"]),
        Paragraph("Severity",           styles["th"]),
    ]
    rows = [header]
    for check, count in top_issues[:15]:
        pct  = round(count / max(total_pages, 1) * 100)
        sev  = "Critical" if any(k in check for k in ("Title","H1","SSL","Canonical","Sitemap","Robots")) else "Review"
        rows.append([
            Paragraph(_safe(check),             styles["td"]),
            Paragraph(f"{count} of {total_pages}", styles["td_center"]),
            Paragraph(f"{pct}%",                styles["td_center"]),
            Paragraph(sev,                      styles["td_center"]),
        ])

    # Colour severity cells
    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
    ]
    for i, row in enumerate(rows[1:], 1):
        sev_cell = row[3]
        if hasattr(sev_cell, "text"):
            pass  # can colour by checking text
    t = Table(rows, colWidths=[90*mm, 36*mm, 22*mm, 22*mm], repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return [t, Spacer(1, 5*mm)]


# ── Worst pages table ─────────────────────────────────────────────────────────
def _worst_pages_table(worst, base_url, styles):
    clean_worst = [
        p for p in worst
        if not (p.get("url") or "").lower().startswith("/cdn-cgi/")
        and "/cdn-cgi/l/email-protection" not in (p.get("url") or "").lower()
    ]
    header = [
        Paragraph("Page Path",      styles["th"]),
        Paragraph("Issues Found",   styles["th"]),
        Paragraph("Status",         styles["th"]),
    ]
    rows = [header]
    for p in clean_worst[:20]:
        short_url = p["url"].replace(base_url, "") or "/"
        short_url = _trunc(short_url, 65)
        icon  = u"\u2718" if p["status"] == "FAIL" else (u"\u26a0" if p["status"] == "WARN" else u"\u2714")
        rows.append([
            Paragraph(_safe(short_url),              styles["td_url"]),
            Paragraph(str(p.get("issue_count", 0)),  styles["td_center"]),
            Paragraph(f"{icon} {p['status']}",       styles["td_center"]),
        ])

    style_cmds = [
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("ALIGN",         (2,0), (-1,-1), "CENTER"),
    ]
    t = Table(rows, colWidths=[118*mm, 22*mm, 22*mm], repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return [t, Spacer(1, 5*mm)]


# ── Page-by-page detail (one row per page, issues as bullet list) ─────────────
def _page_detail_table(page_audits, base_url, styles):
    """
    Each crawled page gets its own row.
    Issues are listed as clean bullet points — no more cramming on one line.
    """
    clean_pages = [
        p for p in page_audits
        if not (p.get("url") or "").lower().startswith("/cdn-cgi/")
        and "/cdn-cgi/l/email-protection" not in (p.get("url") or "").lower()
    ]
    header = [
        Paragraph("#",          styles["th"]),
        Paragraph("Page Path",  styles["th"]),
        Paragraph("Page Title", styles["th"]),
        Paragraph("Issues",     styles["th"]),
    ]
    rows = [header]
    row_styles = []

    for i, p in enumerate(clean_pages, 1):
        short_url = (p["url"].replace(base_url, "") or "/")
        short_url = _trunc(short_url, 55)

        title = _trunc(p.get("title") or "", 40)

        issues = p.get("issues", [])
        if not issues:
            issue_cell = Paragraph("\u2714 No issues", styles["td"])
        else:
            bullet_lines = []
            for iss in issues[:6]:
                sev_tag = iss.get("severity", "WARN")[0]  # F or W or P
                chk     = _safe(_trunc(iss.get("check", ""), 58))
                bullet_lines.append(f"<b>[{sev_tag}]</b> {chk}")
            if len(issues) > 6:
                bullet_lines.append(f"<i>... +{len(issues)-6} more</i>")
            issue_cell = Paragraph("<br/>".join(bullet_lines), styles["td_issue"])

        rows.append([
            Paragraph(str(i),         styles["td_center"]),
            Paragraph(_safe(short_url), styles["td_url"]),
            Paragraph(_safe(title),   styles["td"]),
            issue_cell,
        ])

        has_fail = any(iss.get("severity","") == "FAIL" for iss in issues)
        has_warn = any(iss.get("severity","") == "WARN" for iss in issues)
        if has_fail:
            row_styles.append(("BACKGROUND", (0,i), (-1,i), _c(1.0, 0.94, 0.94)))
        elif has_warn:
            row_styles.append(("BACKGROUND", (0,i), (-1,i), _c(1.0, 0.97, 0.87)))

    base_style = [
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("ALIGN",         (0,0), (0,-1), "CENTER"),
    ] + row_styles

    t = Table(rows, colWidths=[9*mm, 52*mm, 44*mm, 57*mm], repeatRows=1)
    t.setStyle(TableStyle(base_style))
    return [t, Spacer(1, 5*mm)]


# ── Target keyword and density section ────────────────────────────────────────
def _keyword_analysis_section(keyword_analysis: dict, styles) -> list:
    story = []
    
    is_auto = bool((keyword_analysis or {}).get("auto_discovered"))
    is_configured = bool((keyword_analysis or {}).get("configured"))
    
    section_title = "Website Keyword & Topic Diagnostics (Auto-Discovered)" if is_auto else "Target Keyword & Content Density Diagnostics"
    story.append(Paragraph(section_title, styles["h2"]))

    # Disclaimer / Banner
    if is_auto:
        banner_text = (
            "<b>Default Behavior: Automatic Keyword & Topic Discovery.</b><br/>"
            "<font color='#475569' size=8>"
            "No manual target keywords were supplied. Keywords, entities, and topics were extracted directly "
            "from page titles, meta descriptions, headings, visible body text, and image alt text on the audited website.<br/>"
            "<i>Note: External search-volume and ranking evidence requires a separate connected data provider (currently unavailable).</i>"
            "</font>"
        )
        callout = Table([[Paragraph(banner_text, styles["body"])]], colWidths=[CONTENT_W])
        callout.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), _c(0.95, 0.98, 0.96)),
            ("BOX", (0,0), (-1,-1), 0.5, _c(0.20, 0.70, 0.40)),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ]))
        story.append(callout)
        story.append(Spacer(1, 3*mm))
    elif not is_configured:
        msg = (
            "<b>Status: Target keywords not configured.</b><br/>"
            "<font color='#555566' size=8>"
            "To evaluate exact-phrase frequency, visible-text density, and key element placement across internal pages, "
            "provide target keywords when initiating the audit. External search volume is currently unavailable."
            "</font>"
        )
        callout = Table([[Paragraph(msg, styles["body"])]], colWidths=[CONTENT_W])
        callout.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), _c(0.96, 0.97, 0.99)),
            ("BOX", (0,0), (-1,-1), 0.5, _c(0.80, 0.85, 0.95)),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ]))
        story.append(callout)
        story.append(Spacer(1, 3*mm))

    summaries = (keyword_analysis or {}).get("keyword_summaries", [])
    if summaries:
        term_label = "Observed Website Term" if is_auto else "Target Keyword"
        header = [
            Paragraph(term_label, styles["th"]),
            Paragraph("Occurrences", styles["th"]),
            Paragraph("Density", styles["th"]),
            Paragraph("Denominator", styles["th"]),
            Paragraph("Key Placements", styles["th"]),
        ]
        rows = [header]
        for s in summaries:
            kw = s.get("keyword", "")
            exact = s.get("total_exact_occurrences", 0)
            variant = s.get("total_variant_occurrences", 0)
            density = s.get("average_density_pct", 0.0)
            denom = s.get("visible_word_denominator", "—")
            
            pl = s.get("placement_occurrences", {})
            places = []
            if pl.get("title"): places.append(f"Title ({pl['title']})")
            if pl.get("h1"): places.append(f"H1 ({pl['h1']})")
            if pl.get("h2"): places.append(f"H2 ({pl['h2']})")
            if pl.get("meta_description"): places.append(f"Meta ({pl['meta_description']})")
            if pl.get("alt_text"): places.append(f"Alt ({pl['alt_text']})")
            place_str = ", ".join(places) if places else "Body text only"

            occ_str = f"{exact} exact"
            if variant > 0:
                occ_str += f" (+{variant} var)"

            rows.append([
                Paragraph(f"<b>{_safe(kw)}</b>", styles["body"]),
                Paragraph(occ_str, styles["td_center"]),
                Paragraph(f"{density}%", styles["td_center"]),
                Paragraph(f"{denom} words" if denom != "—" else "—", styles["td_center"]),
                Paragraph(_safe(place_str), styles["body_small"]),
            ])

        col_w = [48*mm, 28*mm, 22*mm, 28*mm, 44*mm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_DARK),
            ("FONTSIZE",      (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
            ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t)
        story.append(Spacer(1, 2.5*mm))

    # Inferred Topics & Suggestions
    inferred = (keyword_analysis or {}).get("inferred_topics", [])
    if inferred:
        inferred_lines = []
        for t in inferred[:6]:
            t_name = t.get("topic", "")
            t_cnt = t.get("frequency", "")
            inferred_lines.append(f"<b>{_safe(t_name)}</b> ({t_cnt}x)")
        
        inferred_html = (
            "<b>Inferred Candidate Topic Suggestions:</b> " + " • ".join(inferred_lines) + "<br/>"
            "<font size=7 color='#64748b'><i>Note: Inferred topics represent thematic entities extracted from page content, not verified Google search volume.</i></font>"
        )
        t_inf = Table([[Paragraph(inferred_html, styles["body_small"])]], colWidths=[CONTENT_W])
        t_inf.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), _c(0.97, 0.97, 0.98)),
            ("BOX",        (0,0), (-1,-1), 0.5, _c(0.85, 0.85, 0.90)),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(t_inf)
        story.append(Spacer(1, 2.5*mm))

    # Section-level keyword occurrences for single-page websites
    sections = (keyword_analysis or {}).get("sections", [])
    if sections and summaries:
        # Check if any summary has section breakdown
        has_sec_data = any(s.get("section_breakdown") for s in summaries)
        if has_sec_data:
            sec_header = [
                Paragraph("Target Section (#anchor)", styles["th"]),
                Paragraph("Section Heading", styles["th"]),
                Paragraph("Visible Words", styles["th"]),
                Paragraph("Discovered Key Terms", styles["th"]),
            ]
            sec_rows = [sec_header]
            for sec in sections[:8]:
                sid = f"#{sec.get('id', '')}"
                h_text = sec.get("heading", "")[:40]
                w_count = sec.get("word_count", 0)
                
                matched_terms = []
                for s in summaries:
                    b_down = s.get("section_breakdown", {})
                    if b_down.get(sid):
                        matched_terms.append(f"{s['keyword']} ({b_down[sid]}x)")
                
                matched_str = ", ".join(matched_terms) if matched_terms else "General content"
                sec_rows.append([
                    Paragraph(f"<b>{_safe(sid)}</b>", styles["body"]),
                    Paragraph(_safe(h_text), styles["body_small"]),
                    Paragraph(f"{w_count}w", styles["td_center"]),
                    Paragraph(_safe(matched_str), styles["body_small"]),
                ])

            t_sec = Table(sec_rows, colWidths=[40*mm, 50*mm, 24*mm, 56*mm], repeatRows=1)
            t_sec.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), C_PRIMARY),
                ("FONTSIZE",      (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
                ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("LEFTPADDING",   (0,0), (-1,-1), 6),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ]))
            story.append(Paragraph("<b>Single-Page Content Section Keyword Distribution:</b>", styles["body_small"]))
            story.append(Spacer(1, 1*mm))
            story.append(t_sec)
            story.append(Spacer(1, 2.5*mm))

    story.append(Paragraph(
        "<font size=7 color='#64748b'><b>Methodology:</b> Keyword Density (%) = (Exact Occurrences * Keyword Word Count / Visible Body Words) * 100. "
        "Measured across visible body content; navigation boilerplate, scripts, and hidden text are excluded. "
        "Single-page section anchors (#) are evaluated within the primary document and not counted as separate HTML pages.</font>",
        styles["caption"]
    ))
    story.append(Spacer(1, 4*mm))
    return story


def _client_diagnostics_section(site_summary: dict | None, styles) -> list:
    if not site_summary:
        return []

    mob = site_summary.get("mobile_usability")
    perf = site_summary.get("lighthouse_performance")
    meta = site_summary.get("onpage_metadata_diagnostics")

    if not (mob or perf or meta):
        return []

    story = []
    story.append(Paragraph("Client Target Website Diagnostics & Usability", styles["h1"]))
    story.append(Spacer(1, 2*mm))

    # 1. Mobile Usability Audit
    if mob:
        status = mob.get("overall_status", "NEEDS IMPROVEMENT")
        status_color = C_SUCCESS if status == "PASS" else (C_DANGER if status == "FAIL" else C_WARN)
        story.append(Paragraph(f"<b>Mobile Usability & Viewport Audit:</b> <font color='{status_color.hexval()}'><b>{status}</b></font>", styles["h2"]))
        story.append(Paragraph(
            f"Evaluated target client website in live browser across 4 responsive viewports (360px, 390px, 412px, 1280px). "
            f"{_safe(mob.get('summary', ''))}",
            styles["body"]
        ))
        story.append(Spacer(1, 2*mm))

        vps = mob.get("viewports_tested", [])
        if vps:
            vp_rows = [[
                Paragraph("Viewport Tested", styles["th"]),
                Paragraph("Width", styles["th"]),
                Paragraph("Horizontal Overflow", styles["th"]),
                Paragraph("Tap-Target Compliance", styles["th"]),
                Paragraph("Page Load", styles["th"]),
            ]]
            for v in vps:
                ov_str = f"{v.get('overflow_px', 0)}px" if v.get('overflow_px', 0) > 0 else "0px (None)"
                vp_rows.append([
                    Paragraph(f"<b>{_safe(v.get('name', ''))}</b>", styles["body"]),
                    Paragraph(f"{v.get('width', 0)}px", styles["td_center"]),
                    Paragraph(ov_str, styles["td_center"]),
                    Paragraph(f"{v.get('tap_compliance_pct', 100)}%", styles["td_center"]),
                    Paragraph(f"{v.get('load_time_ms', 0)} ms", styles["td_center"]),
                ])
            t_vp = Table(vp_rows, colWidths=[48*mm, 24*mm, 36*mm, 36*mm, 26*mm], repeatRows=1)
            t_vp.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0), C_DARK),
                ("FONTSIZE",      (0,0), (-1,-1), 8),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
                ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("LEFTPADDING",   (0,0), (-1,-1), 6),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ]))
            story.append(t_vp)
            story.append(Spacer(1, 3*mm))

        issues = mob.get("issues", [])
        if issues:
            iss_cells = []
            for iss in issues:
                iss_cells.append([
                    Paragraph(f"• <b>[{iss.get('severity')}] {iss.get('code')}:</b> {_safe(iss.get('observed'))}<br/>"
                              f"<font color='#047857'><b>Recommended fix:</b> {_safe(iss.get('recommendation'))}</font>", styles["body_small"])
                ])
            t_iss = Table(iss_cells, colWidths=[CONTENT_W])
            t_iss.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), _c(0.98, 0.98, 0.99)),
                ("BOX",        (0,0), (-1,-1), 0.5, _c(0.85, 0.85, 0.90)),
                ("TOPPADDING", (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING", (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ]))
            story.append(t_iss)
            story.append(Spacer(1, 4*mm))

    # 2. Performance & Core Web Vitals (Lighthouse)
    if perf:
        score = perf.get("performance_score", 0)
        score_color = C_SUCCESS if score >= 80 else (C_WARN if score >= 50 else C_DANGER)
        story.append(Paragraph(f"<b>Performance & Core Web Vitals (Lighthouse Lab):</b> <font color='{score_color.hexval()}'><b>Score {score}/100</b></font>", styles["h2"]))
        story.append(Paragraph(
            f"Measured via <b>{_safe(perf.get('tool', 'Lighthouse'))}</b> under simulated mobile network throttling.<br/>"
            f"<i>{_safe(perf.get('disclaimer', ''))}</i>",
            styles["body_small"]
        ))
        story.append(Spacer(1, 2*mm))

        cwv_rows = [
            [
                Paragraph("Metric", styles["th"]),
                Paragraph("Observed Value", styles["th"]),
                Paragraph("Google CWV Target", styles["th"]),
                Paragraph("Rating", styles["th"]),
            ],
            [
                Paragraph("<b>First Contentful Paint (FCP)</b>", styles["body"]),
                Paragraph(perf.get("fcp", {}).get("display", "—"), styles["td_center"]),
                Paragraph("< 1.8 s", styles["td_center"]),
                Paragraph("Needs Improvement" if perf.get("fcp", {}).get("value_ms", 0) > 1800 else "Good", styles["td_center"]),
            ],
            [
                Paragraph("<b>Largest Contentful Paint (LCP)</b>", styles["body"]),
                Paragraph(perf.get("lcp", {}).get("display", "—"), styles["td_center"]),
                Paragraph("< 2.5 s", styles["td_center"]),
                Paragraph("Needs Improvement" if perf.get("lcp", {}).get("value_ms", 0) > 2500 else "Good", styles["td_center"]),
            ],
            [
                Paragraph("<b>Total Blocking Time (TBT)</b>", styles["body"]),
                Paragraph(perf.get("tbt", {}).get("display", "—"), styles["td_center"]),
                Paragraph("< 200 ms", styles["td_center"]),
                Paragraph("Poor" if perf.get("tbt", {}).get("value_ms", 0) > 600 else "Needs Improvement", styles["td_center"]),
            ],
            [
                Paragraph("<b>Cumulative Layout Shift (CLS)</b>", styles["body"]),
                Paragraph(perf.get("cls", {}).get("display", "—"), styles["td_center"]),
                Paragraph("< 0.1", styles["td_center"]),
                Paragraph("Good", styles["td_center"]),
            ],
            [
                Paragraph("<b>Time to First Byte (TTFB)</b>", styles["body"]),
                Paragraph(perf.get("ttfb", {}).get("display", "—"), styles["td_center"]),
                Paragraph("< 800 ms", styles["td_center"]),
                Paragraph("Good", styles["td_center"]),
            ],
        ]
        t_cwv = Table(cwv_rows, colWidths=[55*mm, 35*mm, 40*mm, 40*mm], repeatRows=1)
        t_cwv.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_DARK),
            ("FONTSIZE",      (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
            ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t_cwv)
        story.append(Spacer(1, 3*mm))

        opps = perf.get("opportunities", [])
        if opps:
            opp_text = "<b>High-Impact Performance Opportunities:</b><br/>" + "<br/>".join([
                f"• <b>{_safe(o.get('title'))}:</b> {_safe(o.get('display'))}" for o in opps
            ])
            t_opp = Table([[Paragraph(opp_text, styles["body_small"])]], colWidths=[CONTENT_W])
            t_opp.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), _c(0.96, 0.98, 1.0)),
                ("BOX",        (0,0), (-1,-1), 0.5, C_PRIMARY),
                ("TOPPADDING", (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING", (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ]))
            story.append(t_opp)
            story.append(Spacer(1, 4*mm))

    # 3. On-Page Metadata Exact Observed Values
    if meta:
        story.append(Paragraph("<b>Metadata & On-Page SEO Diagnostics (Exact Observed Values):</b>", styles["h2"]))
        meta_rows = [[
            Paragraph("Element", styles["th"]),
            Paragraph("Exact Observed Value", styles["th"]),
            Paragraph("Condition", styles["th"]),
            Paragraph("Recommended Improvement", styles["th"]),
        ]]
        for elem_name, diag in meta.items():
            obs = str(diag.get("observed") if diag.get("observed") is not None else "<i>Missing</i>")
            if len(obs) > 60:
                obs = obs[:57] + "..."
            cond = diag.get("condition", "optimal").title()
            rec = diag.get("recommendation") or "—"
            if len(rec) > 65:
                rec = rec[:62] + "..."

            meta_rows.append([
                Paragraph(f"<b>{elem_name.replace('_', ' ').title()}</b>", styles["body"]),
                Paragraph(_safe(obs), styles["body_small"]),
                Paragraph(cond, styles["td_center"]),
                Paragraph(_safe(rec), styles["body_small"]),
            ])

        t_meta = Table(meta_rows, colWidths=[38*mm, 54*mm, 26*mm, 52*mm], repeatRows=1)
        t_meta.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_DARK),
            ("FONTSIZE",      (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
            ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(t_meta)
        story.append(Spacer(1, 4*mm))

    return story


def _resolve_priority_label(factor_id: str, status: str, result: dict) -> str:
    sev = str(result.get("severity") or "").upper()
    if sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        return sev
    fid = result.get("id") or factor_id
    if status == "FAIL":
        if fid in ("technical.ssl", "technical.robots", "onpage.noindex", "indexability.noindex", "technical.mobile"):
            return "CRITICAL"
        if fid in ("onpage.page_title", "onpage.h1", "technical.sitemap", "links.broken_links", "ux.cta", "indexability.soft_404"):
            return "HIGH"
        if fid in ("technical.favicon", "images.lazy_load", "conversion.social", "conversion.whatsapp", "content.reading_level"):
            return "LOW"
        return "MEDIUM"
    elif status == "WARN":
        if fid in ("technical.robots", "technical.sitemap"):
            return "MEDIUM"
        return "LOW"
    return "REVIEW"


# ── Priority action plan ──────────────────────────────────────────────────────
def _priority_table(audit_results, styles):
    header = [
        Paragraph("Priority",   styles["th"]),
        Paragraph("Issue",      styles["th"]),
        Paragraph("Group",      styles["th"]),
    ]
    rows  = [header]
    cmds  = []

    FRIENDLY_GROUPS = {
        "technical": "Technical",
        "onpage": "On-Page",
        "images": "Images",
        "links": "Links",
        "conversion": "Conversion",
        "ux": "UI / UX",
        "indexability": "Indexability",
        "content": "Content",
        "local_seo": "Local SEO",
        "performance": "Performance",
        "schema_adv": "Adv Schema",
    }
    weight_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "REVIEW": 4}
    items = []
    for level in ("FAIL", "WARN"):
        for group_key, tests in audit_results.items():
            for test_id, result in tests.items():
                if result.get("status") == level:
                    msg    = _safe(_trunc(result.get("message", test_id), 130))
                    grp    = FRIENDLY_GROUPS.get(group_key.lower(), group_key.replace("_", " ").title())
                    label  = _resolve_priority_label(test_id, level, result)
                    items.append((weight_map.get(label, 5), label, msg, grp))

    items.sort(key=lambda x: x[0])
    for _, label, msg, grp in items:
        style_key = f"pri_{label.lower()}"
        pri_style = styles.get(style_key, styles.get("pri_review", styles["th"]))
        rows.append([
            Paragraph(label,  pri_style),
            Paragraph(msg,    styles["pri_msg"]),
            Paragraph(grp,    styles["pri_group"]),
        ])

    # Colour priority column
    for i, row in enumerate(rows[1:], 1):
        lbl = row[0]
        txt = getattr(lbl, "text", "") or ""
        if "CRITICAL" in txt:
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(0.99,0.92,0.92)))
        elif "HIGH" in txt:
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(1.0,0.94,0.90)))
        elif "MEDIUM" in txt:
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(1.0,0.98,0.90)))
        elif "LOW" in txt:
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(0.93,0.96,1.0)))
        else:
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(1.0,0.97,0.87)))

    base = [
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 7),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("ALIGN",         (0,0), (0,-1), "CENTER"),
        ("ALIGN",         (2,0), (-1,-1), "CENTER"),
    ] + cmds

    t = Table(rows, colWidths=[24*mm, 116*mm, 34*mm], repeatRows=1)
    t.setStyle(TableStyle(base))
    return [t]


def _diagnostics_section(url, url_info, audit_results, styles):
    story = []
    story += _section("Technical & Search Diagnostics", styles)

    req_url = (url_info.get("requested_url") if url_info else None) or url
    final_url = (url_info.get("final_url") if url_info else None) or req_url

    diag_rows = [
        [Paragraph("Diagnostic Domain", styles["th"]), Paragraph("Audit Observation & System Status", styles["th"])],
        [
            Paragraph("<b>Origin Robots.txt Discovery</b>", styles["body_small"]),
            Paragraph("Resolved exclusively from the root origin host (scheme + domain). Subpath route concatenation strictly avoided.", styles["td"]),
        ],
        [
            Paragraph("<b>XML Sitemap Integrity</b>", styles["body_small"]),
            Paragraph("Verified XML structure (&lt;urlset&gt; or &lt;sitemapindex&gt;). HTTP 200 HTML soft responses rejected. Child sitemaps capped at 5.", styles["td"]),
        ],
        [
            Paragraph("<b>AI-Search Readiness</b>", styles["body_small"]),
            Paragraph("Evaluates robot crawl permissions (GPTBot, ClaudeBot, Google-Extended), NAP entity alignment, and structured Q&amp;A content.", styles["td"]),
        ],
        [
            Paragraph("<b>Synthetic Lab Web Vitals</b>", styles["body_small"]),
            Paragraph("TTFB, LCP, and CLS are lab synthetic measurements. Real-user Core Web Vitals require CrUX or field data tracking.", styles["td"]),
        ],
        [
            Paragraph("<b>Google Search Console</b>", styles["body_small"]),
            Paragraph("Read-only OAuth integration available upon property authorization. Live queries, impressions, and clicks require connected property.", styles["td"]),
        ],
    ]
    diag_table = Table(diag_rows, colWidths=[48*mm, CONTENT_W - 48*mm])
    diag_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_DARK),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, _c(0.97,0.97,0.99)]),
        ("GRID",          (0,0), (-1,-1), 0.3, _c(0.82,0.82,0.88)),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(diag_table)
    story.append(Spacer(1, 4*mm))
    return story


# ── Main builder ──────────────────────────────────────────────────────────────
def build_pdf(
    url: str,
    audit_results: dict,
    score: int,
    output_path: str,
    site_summary: dict = None,
    page_audits: list = None,
    url_info: dict = None,
    target_keywords: list = None,
    keyword_analysis: dict = None,
):
    styles = _styles()
    report_date = datetime.datetime.now().strftime("%B %d, %Y")
    agency = BRANDING.get("agency_name", "SEO Audit Engine")

    effective_url_info = url_info or (site_summary.get("url_info") if site_summary else None)
    header_url = (effective_url_info.get("requested_url") if effective_url_info else None) or url

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20*mm, bottomMargin=15*mm,
        title=f"SEO Audit — {header_url}",
        author=agency,
        subject="SEO Audit Report",
    )

    story = []
    chrome = _page_chrome(header_url, report_date, agency)

    # ─── Page 1: Cover ────────────────────────────────────────────────────────
    story += _cover(header_url, report_date, score, agency, styles, url_info=effective_url_info)
    story.append(PageBreak())

    # ─── Page 2: Executive Summary ───────────────────────────────────────────
    story += _section("Executive Summary", styles)
    story += _overview_bar(audit_results, styles)
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Results by Category", styles["h2"]))
    story += _group_table(audit_results, styles)
    story.append(Spacer(1, 4*mm))

    # ─── Page 3+: Detailed Findings ───────────────────────────────────────────
    story.append(PageBreak())

    GROUP_TITLES = {
        "technical":    "A — Technical Foundation & Crawlability",
        "onpage":       "B — On-Page SEO & Metadata",
        "images":       "C — Image & Media Optimization",
        "links":        "D — Links & Navigation",
        "conversion":   "E — Conversion & Trust Signals",
        "ux":           "F — User Experience & Web Design Diagnostics",
        "indexability": "G — Indexability & Canonical Integrity",
        "content":      "H — Content Quality & Heading Structure",
        "local_seo":    "I — Local SEO & Business Identity",
        "performance":  "J — Core Web Vitals & Server Performance",
        "schema_adv":   "K — Advanced Schema & Structured Data",
    }

    for group_key, tests in audit_results.items():
        title = GROUP_TITLES.get(group_key, group_key.title())
        story += _section(title, styles)
        for test_id, result in tests.items():
            story += _test_card(test_id, result, styles)
        story.append(Spacer(1, 4*mm))

    # ─── Priority Action Plan ──────────────────────────────────────────────────
    story.append(PageBreak())
    story += _section("Priority Action Plan", styles, color=C_DANGER)
    story.append(Paragraph(
        "All failed and warning checks are listed below, ordered by severity. "
        "Address CRITICAL items first to achieve the highest SEO improvement.",
        styles["intro"]
    ))
    story.append(Spacer(1, 3*mm))

    priority_rows = []
    for level in ("FAIL", "WARN"):
        for group_key, tests in audit_results.items():
            for test_id, result in tests.items():
                if result.get("status") == level:
                    priority_rows.append((level, group_key, test_id, result))

    if priority_rows:
        story += _priority_table(audit_results, styles)
    else:
        story.append(Paragraph(
            u"\u2714  Excellent! No critical or warning issues found on this website.",
            styles["body"]
        ))

    # ─── Technical Diagnostics Advisory ──────────────────────────────────────
    story.append(PageBreak())
    story += _diagnostics_section(header_url, effective_url_info, audit_results, styles)

    # ─── Target Keyword & Content Density Diagnostics ────────────────────────
    kw_analysis = keyword_analysis or (site_summary.get("keyword_analysis") if site_summary else None)
    if not kw_analysis:
        try:
            from auditor.keyword_density import analyze_target_keywords_site
            kw_analysis = analyze_target_keywords_site(page_audits or [], target_keywords)
        except Exception:
            kw_analysis = {"configured": False, "status": "not_configured", "message": "Target keywords not configured"}
    story += _keyword_analysis_section(kw_analysis, styles)

    # ─── Target Client Website Diagnostics (Mobile, CWV, Metadata) ───────────
    client_diag_story = _client_diagnostics_section(site_summary, styles)
    if client_diag_story:
        story.append(PageBreak())
        story += client_diag_story


    # ─── Site-Wide Crawl Section (optional) ───────────────────────────────────
    if site_summary and site_summary.get("total_pages", 0) > 0:
        ss = site_summary
        story.append(PageBreak())
        story += _section("Site-Wide Crawl Analysis", styles)

        story += _crawl_stats(ss, styles)

        if ss.get("top_issues"):
            story.append(Paragraph("Most Common Issues Across All Pages", styles["h2"]))
            story += _common_issues_table(ss["top_issues"], ss["total_pages"], styles)

        worst = (ss.get("worst_pages") or [])[:20]
        if worst:
            story.append(Paragraph("Pages With Most SEO Issues", styles["h2"]))
            story += _worst_pages_table(worst, url, styles)

        if page_audits:
            story.append(PageBreak())
            story.append(Paragraph("Full Page-by-Page Audit Detail", styles["h2"]))
            story.append(Paragraph(
                f"Showing all {len(page_audits)} crawled pages. "
                "[F] = Failed check, [W] = Warning, [P] = Passed.",
                styles["caption"]
            ))
            story.append(Spacer(1, 3*mm))
            story += _page_detail_table(page_audits, url, styles)

    # ─── Footer note ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LIGHT))
    story.append(Spacer(1, 3*mm))
    email   = BRANDING.get("email", "")
    website = BRANDING.get("website", "")
    story.append(Paragraph(
        f"This report was generated automatically by the {agency} SEO Audit Engine. "
        f"For a full manual audit, custom fix implementation, or SEO strategy consultation, "
        f"contact us at {email} or visit {website}.",
        styles["footer"],
    ))

    doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return output_path
