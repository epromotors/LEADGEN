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
    ps("h1",            fontName="Helvetica-Bold",  fontSize=16, textColor=C_PRIMARY,         leading=22, spaceBefore=12, spaceAfter=4)
    ps("h2",            fontName="Helvetica-Bold",  fontSize=12, textColor=C_DARK,            leading=17, spaceBefore=10, spaceAfter=3)
    ps("h3",            fontName="Helvetica-Bold",  fontSize=10, textColor=C_DARK,            leading=14, spaceAfter=2)

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

    # Table cells
    ps("th",            fontName="Helvetica-Bold",  fontSize=9,  textColor=C_WHITE,           leading=13, alignment=TA_LEFT)
    ps("td",            fontName="Helvetica",       fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=13)
    ps("td_center",     fontName="Helvetica",       fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=13, alignment=TA_CENTER)
    ps("td_url",        fontName="Helvetica",       fontSize=7.5, textColor=_c(0.10,0.22,0.55), leading=11)
    ps("td_issue",      fontName="Helvetica",       fontSize=8,   textColor=_c(0.18,0.18,0.24), leading=12)
    ps("td_issue_head", fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.18,0.18,0.24), leading=12)

    # Priority table
    ps("pri_critical",  fontName="Helvetica-Bold",  fontSize=8.5, textColor=_c(0.7,0.05,0.05), leading=12, alignment=TA_CENTER)
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
def _cover(url, report_date, score, agency, styles):
    band_label = next((l for lo,hi,l,_ in SCORE_BANDS if lo <= score < hi), "")
    score_bg = C_DANGER if score < 40 else (C_WARN if score < 65 else (C_ACCENT if score < 85 else C_PASS))

    # Full-width dark background block
    cover_rows = [
        [Paragraph("SEO PERFORMANCE AUDIT", styles["cov_eyebrow"])],
        [Paragraph("Website Analysis Report", styles["cov_title"])],
        [Spacer(1, 4*mm)],
        [Paragraph(_safe(url), styles["cov_url"])],
        [Paragraph(f"Prepared by {agency}", styles["cov_meta"])],
        [Paragraph(report_date, styles["cov_meta"])],
    ]
    bg_table = Table(cover_rows, colWidths=[CONTENT_W])
    bg_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_DARK),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
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

    return [bg_table, Spacer(1, 8*mm), side_table, Spacer(1, 6*mm)]


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

    # Status badge (left column)
    badge_rows = [
        [Paragraph(icon,    styles["score_band"])],
        [Paragraph(label,   styles["score_band"])],
    ]
    badge = Table(badge_rows, colWidths=[16*mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), color),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))

    # Content (right column)
    name_text = test_id.replace("_", " ").title()
    content = [Paragraph(f"<b>{_safe(name_text)}</b>", styles["h3"])]
    if result.get("message"):
        content.append(Paragraph(_safe(result["message"]), styles["body"]))
    if result.get("fix"):
        content.append(Paragraph(f"<b>How to fix:</b> {_safe(result['fix'])}", styles["fix"]))
    if result.get("detail"):
        content.append(Paragraph(_safe(result["detail"]), styles["detail"]))

    # 2-col layout: badge | content
    card_data = [[badge, content]]
    card_w    = CONTENT_W
    card = Table(card_data, colWidths=[18*mm, card_w - 18*mm])
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
    return [t, Spacer(1, 5*mm)]


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
    header = [
        Paragraph("Page Path",      styles["th"]),
        Paragraph("Issues Found",   styles["th"]),
        Paragraph("Status",         styles["th"]),
    ]
    rows = [header]
    for p in worst[:20]:
        short_url = p["url"].replace(base_url, "") or "/"
        short_url = _trunc(short_url, 65)
        icon  = u"\u2718" if p["status"] == "FAIL" else (u"\u26a0" if p["status"] == "WARN" else u"\u2714")
        color = C_DANGER if p["status"] == "FAIL" else (C_WARN if p["status"] == "WARN" else C_PASS)
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
    header = [
        Paragraph("#",          styles["th"]),
        Paragraph("Page Path",  styles["th"]),
        Paragraph("Page Title", styles["th"]),
        Paragraph("Issues",     styles["th"]),
    ]
    rows = [header]
    row_styles = []

    for i, p in enumerate(page_audits, 1):
        short_url = (p["url"].replace(base_url, "") or "/")
        short_url = _trunc(short_url, 55)

        title = _trunc(p.get("title") or "", 40)

        issues = p.get("issues", [])
        if not issues:
            issue_cell = Paragraph("\u2714 No issues", styles["td"])
        else:
            # Build bullet lines: [F] Missing Title, [W] No Alt Text...
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

        # Row background colour based on worst issue
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
        ("ALIGN",         (0,0), (0,-1), "CENTER"),    # # column centred
    ] + row_styles

    t = Table(rows, colWidths=[9*mm, 52*mm, 44*mm, 57*mm], repeatRows=1)
    t.setStyle(TableStyle(base_style))
    return [t, Spacer(1, 5*mm)]


# ── Priority action plan ──────────────────────────────────────────────────────
def _priority_table(audit_results, styles):
    header = [
        Paragraph("Priority",   styles["th"]),
        Paragraph("Issue",      styles["th"]),
        Paragraph("Group",      styles["th"]),
    ]
    rows  = [header]
    cmds  = []

    for level in ("FAIL", "WARN"):
        for group_key, tests in audit_results.items():
            for test_id, result in tests.items():
                if result.get("status") == level:
                    msg    = _safe(_trunc(result.get("message", test_id), 130))
                    grp    = group_key.title()
                    label  = PRIORITY_LABEL[level]
                    bg_pri = _c(0.99,0.92,0.92) if level == "FAIL" else _c(1.0,0.97,0.87)
                    rows.append([
                        Paragraph(label,  styles["pri_critical"] if level=="FAIL" else styles["pri_review"]),
                        Paragraph(msg,    styles["pri_msg"]),
                        Paragraph(grp,    styles["pri_group"]),
                    ])

    # Colour priority column
    for i, row in enumerate(rows[1:], 1):
        lbl = row[0]
        if "CRITICAL" in (lbl.text if hasattr(lbl,"text") else ""):
            cmds.append(("BACKGROUND", (0,i), (0,i), _c(0.99,0.93,0.93)))
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

    t = Table(rows, colWidths=[24*mm, 112*mm, 22*mm], repeatRows=1)
    t.setStyle(TableStyle(base))
    return [t]


# ── Main builder ──────────────────────────────────────────────────────────────
def build_pdf(
    url: str,
    audit_results: dict,
    score: int,
    output_path: str,
    site_summary: dict = None,
    page_audits: list = None,
):
    styles = _styles()
    report_date = datetime.datetime.now().strftime("%B %d, %Y")
    agency = BRANDING.get("agency_name", "SEO Audit Engine")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20*mm, bottomMargin=15*mm,
        title=f"SEO Audit — {url}",
        author=agency,
        subject="SEO Audit Report",
    )

    story = []
    chrome = _page_chrome(url, report_date, agency)

    # ─── Page 1: Cover ────────────────────────────────────────────────────────
    story += _cover(url, report_date, score, agency, styles)

    # ─── Page 1 cont: Executive Summary ───────────────────────────────────────
    story += _section("Executive Summary", styles)
    story += _overview_bar(audit_results, styles)
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Results by Category", styles["h2"]))
    story += _group_table(audit_results, styles)
    story.append(Spacer(1, 4*mm))

    # ─── Page 2+: Detailed Findings ───────────────────────────────────────────
    story.append(PageBreak())

    GROUP_TITLES = {
        "technical":  "A — Technical Foundation",
        "onpage":     "B — On-Page SEO",
        "images":     "C — Image & Media",
        "links":      "D — Links & Navigation",
        "conversion": "E — Conversion & Trust",
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

    # ─── Site-Wide Crawl Section (optional) ───────────────────────────────────
    if site_summary and site_summary.get("total_pages", 0) > 0:
        ss = site_summary
        story.append(PageBreak())
        story += _section("F — Site-Wide Crawl Analysis", styles)

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
