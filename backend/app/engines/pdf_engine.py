"""
pdf_engine.py — Branded TEB Solutions PDF Report Generator
Uses fpdf2 to create a professional audit report.
"""

import os
from datetime import datetime
from fpdf import FPDF, XPos, YPos
from app.config import settings


def _safe(text: str) -> str:
    """Replace non-Latin-1 characters with ASCII equivalents for Helvetica font."""
    return (
        str(text)
        .replace("\u2014", "-")   # em dash —
        .replace("\u2013", "-")   # en dash –
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2022", "-")
        .replace("\u2026", "...")
        .encode("latin-1", errors="replace").decode("latin-1")
    )


# ─── Brand Colors (RGB) ────────────────────────────────────────────────────────
PRIMARY = (30, 64, 175)      # Deep blue
ACCENT = (245, 158, 11)      # Amber
DARK = (15, 23, 42)          # Almost black
LIGHT_BG = (248, 250, 252)   # Off-white
PASS_GREEN = (22, 163, 74)
FAIL_RED = (220, 38, 38)
WARN_ORANGE = (234, 88, 12)
TEXT_GREY = (100, 116, 139)
WHITE = (255, 255, 255)


class AuditPDF(FPDF):
    def header(self):
        # Blue header bar across full page
        self.set_fill_color(*PRIMARY)
        self.rect(0, 0, 210, 22, "F")
        # Two cells side by side: title (145mm) + date (45mm) = 190mm within margins
        self.set_xy(10, 6)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*WHITE)
        self.cell(145, 10, "TEB Solutions - SEO Audit Report", align="L")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(200, 215, 255)
        self.cell(45, 10, datetime.now().strftime("%B %d, %Y"), align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*TEXT_GREY)
        self.cell(0, 10, f"TEB Solutions | Confidential | Page {self.page_no()}", align="C")


def _factor_row(pdf: FPDF, label: str, value, detail: str = ""):
    """Render a single audit factor row."""
    if value is True:
        icon, color = "PASS", PASS_GREEN
    elif value is False:
        icon, color = "FAIL", FAIL_RED
    elif isinstance(value, int):
        icon = f"{value} found"
        color = FAIL_RED if value > 0 else PASS_GREEN
    else:
        icon, color = _safe(str(value)), TEXT_GREY

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK)
    pdf.cell(90, 8, _safe(f"  {label}"), border="B")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*color)
    pdf.cell(40, 8, _safe(icon), border="B")

    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*TEXT_GREY)
    pdf.cell(60, 8, _safe(detail), border="B", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _section_header(pdf: FPDF, title: str):
    pdf.ln(4)
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_text_color(*PRIMARY)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 9, f"  {title}", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def generate_pdf(lead, audit) -> str:
    """
    Generate branded PDF audit report.
    Returns the file path of the saved PDF.
    """
    pdf = AuditPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(10, 10, 10)

    # ── Lead Summary Card ─────────────────────────────────────────────────────
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_draw_color(*PRIMARY)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 10, "Website Under Analysis", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*TEXT_GREY)
    info_lines = [
        ("Business", lead.business_name),
        ("Email", lead.email),
        ("Phone", lead.phone or "N/A"),
        ("Website", lead.website),
        ("Audit Date", datetime.now().strftime("%d %B %Y, %H:%M")),
    ]
    for label, value in info_lines:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*PRIMARY)
        pdf.cell(35, 7, label + ":")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*DARK)
        pdf.cell(0, 7, _safe(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)

    # ── Issues Summary Banner ─────────────────────────────────────────────────
    _section_header(pdf, "Executive Summary")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(0, 6, _safe(audit.audit_summary or "No summary available."))
    pdf.ln(3)

    # ── 10-Factor Audit Results Table ─────────────────────────────────────────
    _section_header(pdf, "Technical SEO Audit Results")

    # Table header
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    factors = [
        ("SSL Certificate", not audit.ssl_valid if audit.ssl_valid is not None else None,
         "Active & valid" if audit.ssl_valid else "Missing or expired"),
        ("XML Sitemap", not audit.has_sitemap if audit.has_sitemap is not None else None,
         "Found at /sitemap.xml" if audit.has_sitemap else "Not detected"),
        ("robots.txt", not audit.has_robots if audit.has_robots is not None else None,
         "Present" if audit.has_robots else "Missing"),
        ("Broken Links", None, None),
        ("H1 Heading Tag", audit.missing_h1, "Missing" if audit.missing_h1 else "Present"),
        ("Image Alt Text", None, None),
        ("WebP Images", not audit.uses_webp if audit.uses_webp is not None else None,
         "In use" if audit.uses_webp else "Not detected"),
        ("JSON-LD Schema", not audit.has_json_ld if audit.has_json_ld is not None else None,
         "Implemented" if audit.has_json_ld else "Not found"),
        ("Mobile Viewport", not audit.mobile_friendly if audit.mobile_friendly is not None else None,
         "Configured" if audit.mobile_friendly else "Missing"),
        ("Social Profiles", None, None),
    ]

    # Render rows directly with full values
    _factor_row(pdf, "SSL Certificate",
                audit.ssl_valid, "Valid & active" if audit.ssl_valid else "Invalid or expired")
    _factor_row(pdf, "XML Sitemap",
                audit.has_sitemap, "Found" if audit.has_sitemap else "Not found at /sitemap.xml")
    _factor_row(pdf, "robots.txt",
                audit.has_robots, "Present" if audit.has_robots else "Missing")
    _factor_row(pdf, "Broken Links",
                audit.broken_links_count,
                "All links OK" if audit.broken_links_count == 0 else f"{audit.broken_links_count} broken")
    _factor_row(pdf, "H1 Heading Tag",
                not audit.missing_h1, "Missing" if audit.missing_h1 else "Present")
    _factor_row(pdf, "Image Alt Text",
                audit.missing_alt_count,
                f"{audit.missing_alt_count} image(s) missing alt" if audit.missing_alt_count else "All images have alt")
    _factor_row(pdf, "WebP Images",
                audit.uses_webp, "Detected" if audit.uses_webp else "Not in use")
    _factor_row(pdf, "JSON-LD Schema",
                audit.has_json_ld, "Markup found" if audit.has_json_ld else "No structured data")
    _factor_row(pdf, "Mobile Responsive Design",
                audit.mobile_friendly, "Responsive & mobile-ready" if audit.mobile_friendly else "Not mobile responsive")
    missing_s = ", ".join(audit.missing_social or []) or "None"
    _factor_row(pdf, "Social Profiles",
                len(audit.missing_social or []) == 0, f"Missing: {missing_s}")

    pdf.ln(6)

    # ── Phase 3: UI/UX Audit Results ─────────────────────────────────────────
    _section_header(pdf, "UI/UX & User Experience Audit")

    # UX Score banner
    ux_score = getattr(audit, 'ux_score', None)
    if ux_score is not None:
        ux_color = PASS_GREEN if ux_score >= 75 else (WARN_ORANGE if ux_score >= 50 else FAIL_RED)
        pdf.set_fill_color(*ux_color)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 10, _safe(f"  UI/UX Score: {ux_score}/100"), fill=True,
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    # UX factor table header
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  UX Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    _factor_row(pdf, "Call-to-Action Button",
                getattr(audit, 'has_cta', None),
                "CTA button present" if getattr(audit, 'has_cta', None) else "No clear CTA found")
    _factor_row(pdf, "CTA Above the Fold",
                getattr(audit, 'cta_above_fold', None),
                "Visible without scrolling" if getattr(audit, 'cta_above_fold', None) else "CTA requires scrolling")
    _factor_row(pdf, "Hero Value Proposition",
                getattr(audit, 'has_hero_headline', None),
                "Clear H1 hero headline found" if getattr(audit, 'has_hero_headline', None) else "Missing hero headline")
    _factor_row(pdf, "Text Readability (Font Size)",
                getattr(audit, 'font_size_ok', None),
                "Font size adequate" if getattr(audit, 'font_size_ok', None) else "Body text may be too small (<14px)")
    _factor_row(pdf, "Colour Contrast",
                getattr(audit, 'contrast_ok', None),
                "Contrast appears adequate" if getattr(audit, 'contrast_ok', None) else "Low contrast text detected")
    nav_count = getattr(audit, 'nav_links_count', None)
    nav_ok = nav_count is not None and nav_count >= 3
    nav_detail = f"{nav_count} nav link(s) found" if nav_count is not None else "Navigation not detected"
    _factor_row(pdf, "Navigation Menu", nav_ok, nav_detail)
    _factor_row(pdf, "Cookie Consent Banner",
                getattr(audit, 'has_cookie_notice', None),
                "Cookie notice present" if getattr(audit, 'has_cookie_notice', None) else "No cookie consent banner")
    _factor_row(pdf, "Live Chat / WhatsApp Widget",
                getattr(audit, 'has_live_chat', None),
                "Live chat widget found" if getattr(audit, 'has_live_chat', None) else "No live chat detected")

    pdf.ln(6)

    # ── v5.0 Indexability Audit ────────────────────────────────────────────────
    _section_header(pdf, "Indexability & Crawlability")
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _factor_row(pdf, "No Noindex Tag",
                not getattr(audit, 'has_noindex', False),
                "Page is indexable" if not getattr(audit, 'has_noindex', False) else "NOINDEX detected — page blocked from Google")
    _factor_row(pdf, "Clean URL Structure",
                getattr(audit, 'url_structure_ok', None),
                "URLs are clean and keyword-friendly" if getattr(audit, 'url_structure_ok', None) else "Dynamic or messy URLs detected")
    _factor_row(pdf, "www/non-www Consistent",
                getattr(audit, 'www_nonwww_ok', None),
                "Canonical version is consistent" if getattr(audit, 'www_nonwww_ok', None) else "www and non-www both accessible — link equity split")
    _factor_row(pdf, "No Soft 404s",
                getattr(audit, 'soft_404_ok', None),
                "No soft 404s detected" if getattr(audit, 'soft_404_ok', None) else "Soft 404 content detected")
    pdf.ln(6)

    # ── v5.0 Content Quality Audit ─────────────────────────────────────────────
    _section_header(pdf, "Content Quality")
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    wc = getattr(audit, 'word_count', None)
    _factor_row(pdf, "Word Count",
                wc is not None and wc >= 300,
                f"{wc} words" if wc is not None else "Not measured")
    _factor_row(pdf, "Unique Meta Tags",
                getattr(audit, 'duplicate_meta_ok', None),
                "Unique tags detected" if getattr(audit, 'duplicate_meta_ok', None) else "Duplicate meta tags found")
    _factor_row(pdf, "Keyword in Title",
                getattr(audit, 'keyword_in_title_ok', None),
                "Keyword present in title" if getattr(audit, 'keyword_in_title_ok', None) else "Keyword missing from title")
    _factor_row(pdf, "Readable Content",
                getattr(audit, 'reading_level_ok', None),
                "Content is readable" if getattr(audit, 'reading_level_ok', None) else "Content may be too complex")
    pdf.ln(6)

    # ── v5.0 Local SEO Audit ───────────────────────────────────────────────────
    _section_header(pdf, "Local SEO")
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _factor_row(pdf, "NAP Consistency",
                getattr(audit, 'has_nap', None),
                "Name/Address/Phone found" if getattr(audit, 'has_nap', None) else "NAP data missing from site")
    _factor_row(pdf, "LocalBusiness Schema",
                getattr(audit, 'has_local_business_schema', None),
                "LocalBusiness markup found" if getattr(audit, 'has_local_business_schema', None) else "No LocalBusiness schema")
    _factor_row(pdf, "Google Maps Embed",
                getattr(audit, 'has_google_maps', None),
                "Map embed found" if getattr(audit, 'has_google_maps', None) else "No Google Maps embed")
    _factor_row(pdf, "City in Title",
                getattr(audit, 'city_in_title_ok', None),
                "City keyword in title" if getattr(audit, 'city_in_title_ok', None) else "City missing from title")
    _factor_row(pdf, "Business Hours Present",
                getattr(audit, 'has_business_hours', None),
                "Hours found on site" if getattr(audit, 'has_business_hours', None) else "No business hours detected")
    pdf.ln(6)

    # ── v5.0 Performance Audit ─────────────────────────────────────────────────
    _section_header(pdf, "Page Performance")
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    rt = getattr(audit, 'response_time_ms', None)
    rt_ok = rt is not None and rt < 600
    _factor_row(pdf, "Server Response Time (TTFB)",
                rt_ok,
                f"{rt}ms" if rt is not None else "Not measured")
    _factor_row(pdf, "Page Size",
                getattr(audit, 'page_size_ok', None),
                "Page size is acceptable" if getattr(audit, 'page_size_ok', None) else "Page is too large")
    _factor_row(pdf, "No Render-Blocking Resources",
                getattr(audit, 'render_blocking_ok', None),
                "No blocking resources" if getattr(audit, 'render_blocking_ok', None) else "Render-blocking JS/CSS found")
    _factor_row(pdf, "Gzip Compression",
                getattr(audit, 'gzip_enabled', None),
                "Gzip enabled" if getattr(audit, 'gzip_enabled', None) else "Gzip not enabled")
    _factor_row(pdf, "WebP Image Coverage",
                getattr(audit, 'webp_coverage_ok', None),
                "WebP images in use" if getattr(audit, 'webp_coverage_ok', None) else "Images not using WebP")
    _factor_row(pdf, "CSS/JS Minification",
                getattr(audit, 'minification_ok', None),
                "Assets minified" if getattr(audit, 'minification_ok', None) else "Unminified assets detected")
    pdf.ln(6)

    # ── v5.0 Advanced Schema Audit ─────────────────────────────────────────────
    _section_header(pdf, "Advanced Schema Markup")
    pdf.set_fill_color(*PRIMARY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(90, 8, "  Factor", fill=True)
    pdf.cell(40, 8, "Result", fill=True)
    pdf.cell(60, 8, "Detail", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _factor_row(pdf, "FAQ Schema",
                getattr(audit, 'has_faq_schema', None),
                "FAQPage markup found" if getattr(audit, 'has_faq_schema', None) else "No FAQ schema")
    _factor_row(pdf, "Product Schema",
                getattr(audit, 'has_product_schema', None),
                "Product markup found" if getattr(audit, 'has_product_schema', None) else "No Product schema")
    _factor_row(pdf, "Breadcrumb Schema",
                getattr(audit, 'has_breadcrumb_schema', None),
                "BreadcrumbList found" if getattr(audit, 'has_breadcrumb_schema', None) else "No breadcrumb schema")
    _factor_row(pdf, "Review Schema",
                getattr(audit, 'has_review_schema', None),
                "Review/AggregateRating found" if getattr(audit, 'has_review_schema', None) else "No review schema")
    _factor_row(pdf, "Schema @graph Connected",
                getattr(audit, 'schema_graph_ok', None),
                "@graph structure present" if getattr(audit, 'schema_graph_ok', None) else "No @graph schema")
    pdf.ln(6)

    # ── Deep Impact Analysis ──────────────────────────────────────────────────
    _section_header(pdf, "Deep Impact Analysis - What Each Issue Costs You")
    _build_impact_analysis(pdf, audit)

    pdf.ln(4)

    # ── Action Checklist ──────────────────────────────────────────────────────
    _section_header(pdf, "Priority Fix Checklist")
    recommendations = _build_recommendations(audit)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*DARK)
    for i, rec in enumerate(recommendations, 1):
        pdf.multi_cell(0, 6, _safe(f"  {i}. {rec}"))
        pdf.ln(1)

    pdf.ln(4)

    # ── Service Tiers / Pricing ────────────────────────────────────────────────
    _section_header(pdf, "How TEB Solutions Can Help")

    tiers = [
        ("$25", "Blueprint Tier",
         "Receive this detailed PDF report with exact fix specifications. "
         "Hand it to your developer to implement."),
        ("$60", "Fix & Report Tier",
         "We send you the full report AND our team patches all technical SEO "
         "issues: Schema markup, sitemaps, meta tags, alt text, and broken links."),
        ("$100", "Complete Presence Tier",
         "Everything in Tier 2, PLUS we create and optimise all missing social "
         "media profiles (Facebook, Instagram, LinkedIn, Twitter/X) on your behalf."),
    ]

    for price, name, desc in tiers:
        pdf.set_fill_color(*PRIMARY)
        pdf.set_text_color(*WHITE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(30, 8, f" {price}", fill=True)
        pdf.set_fill_color(*ACCENT)
        pdf.cell(50, 8, f" {name}", fill=True)
        pdf.set_fill_color(*LIGHT_BG)
        pdf.set_text_color(*DARK)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(110, 8, "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*TEXT_GREY)
        pdf.multi_cell(0, 6, _safe(f"   {desc}"))
        pdf.ln(2)

    # ── Footer CTA ────────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_fill_color(*PRIMARY)
    pdf.rect(10, pdf.get_y(), 190, 18, "F")
    pdf.set_xy(10, pdf.get_y() + 4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 10,
             "Reply to this email to get started - we respond within 24 hours.",
             align="C")

    # ── Save File ────────────────────────────────────────────────────────────
    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    filename = f"{settings.REPORTS_DIR}/{str(lead.id)}.pdf"
    pdf.output(filename)
    return filename


def _build_recommendations(audit) -> list:
    recs = []
    if not audit.ssl_valid:
        recs.append("Install a valid SSL certificate (Let's Encrypt is free). "
                    "HTTPS is a confirmed Google ranking factor.")
    if not audit.has_sitemap:
        recs.append("Create and submit an XML sitemap to Google Search Console. "
                    "This helps search engines discover and index all your pages.")
    if not audit.has_robots:
        recs.append("Add a robots.txt file to control crawler access and "
                    "prevent indexing of internal pages.")
    if audit.broken_links_count:
        recs.append(f"Fix or remove {audit.broken_links_count} broken link(s). "
                    "Dead links damage UX and tell Google your site is poorly maintained.")
    if audit.missing_h1:
        recs.append("Add a clear, keyword-rich H1 heading to every page. "
                    "It is the strongest on-page SEO signal for topic relevance.")
    if audit.missing_alt_count:
        recs.append(f"Add descriptive alt text to {audit.missing_alt_count} image(s). "
                    "Alt text improves accessibility and image search ranking.")
    if not audit.uses_webp:
        recs.append("Convert images to WebP format. WebP files are ~30% smaller, "
                    "improving Core Web Vitals and page speed scores.")
    if not audit.has_json_ld:
        recs.append("Implement JSON-LD structured data (Organization, LocalBusiness, FAQ). "
                    "Schema markup enables rich results in Google search.")
    if not audit.mobile_friendly:
        recs.append("Make your website mobile responsive — add a viewport meta tag AND use CSS media queries. "
                    "78%+ of Indian web traffic is mobile. Google Mobile-First Indexing uses your mobile version "
                    "for ALL rankings. A non-responsive site is invisible to the majority of your potential customers, "
                    "damages your brand credibility, and wastes every rupee spent on ads.")
    if audit.missing_social:
        platforms = ", ".join(audit.missing_social)
        recs.append(f"Create missing social profiles: {platforms}. "
                    "Social signals and brand presence strengthen domain authority.")
    # Phase 3: UI/UX recommendations
    if not getattr(audit, 'has_cta', True):
        recs.append("Add a prominent Call-to-Action button (e.g. 'Get a Free Quote', 'Book Now') "
                    "with a contrasting colour. Sites with a clear CTA convert 200% more visitors.")
    if not getattr(audit, 'cta_above_fold', True):
        recs.append("Move your primary CTA button into the hero section so visitors see it "
                    "without scrolling. Above-fold CTAs receive 47% more clicks.")
    if not getattr(audit, 'has_hero_headline', True):
        recs.append("Add a clear H1 hero headline describing what you do, e.g. "
                    "'Professional Window Tinting in Sydney'. Visitors decide in 3 seconds.")
    if not getattr(audit, 'font_size_ok', True):
        recs.append("Set body font-size to at least 16px in CSS: body { font-size: 16px; } "
                    "Small text increases bounce rate and hurts mobile readability.")
    if not getattr(audit, 'contrast_ok', True):
        recs.append("Improve text-to-background contrast ratio to at least 4.5:1 (WCAG AA). "
                    "Use WebAIM Contrast Checker (webaim.org/resources/contrastchecker) to verify.")
    nav_c = getattr(audit, 'nav_links_count', None)
    if nav_c is not None and nav_c < 3:
        recs.append("Add a clear navigation menu with at least 3 links (Home, Services, Contact). "
                    "Good navigation reduces bounce rate and distributes internal link equity.")
    if not getattr(audit, 'has_cookie_notice', True):
        recs.append("Add a GDPR cookie consent banner. Required for EU/California visitors. "
                    "Free tools: CookieYes or Cookiebot. Fines up to 20M EUR for non-compliance.")
    if not getattr(audit, 'has_live_chat', True):
        recs.append("Add a live chat widget or WhatsApp floating button. "
                    "Live chat increases conversions 40-50%. Tawk.to is free.")
    # v5.0 Indexability
    if getattr(audit, 'has_noindex', False):
        recs.append("Remove the noindex meta tag from this page immediately. "
                    "It is blocking Google from indexing your site.")
    if not getattr(audit, 'www_nonwww_ok', True):
        recs.append("Set up a 301 redirect from www to non-www (or vice versa) "
                    "and set your preferred domain in Google Search Console.")
    if not getattr(audit, 'soft_404_ok', True):
        recs.append("Fix soft 404 pages to return proper 404 HTTP status codes "
                    "to avoid wasting crawl budget.")
    # v5.0 Content
    wc = getattr(audit, 'word_count', None)
    if wc is not None and wc < 300:
        recs.append(f"Increase your homepage word count from {wc} to at least 500 words. "
                    "Thin content pages rank poorly in Google.")
    if not getattr(audit, 'keyword_in_title_ok', True):
        recs.append("Include your primary target keyword near the start of your page title tag.")
    # v5.0 Local SEO
    if not getattr(audit, 'has_nap', True):
        recs.append("Add your business Name, Address, and Phone (NAP) to the footer or contact page. "
                    "Consistent NAP is critical for local search rankings.")
    if not getattr(audit, 'has_local_business_schema', True):
        recs.append("Add LocalBusiness JSON-LD schema to your homepage with name, address, "
                    "phone, and opening hours. This improves local pack visibility.")
    if not getattr(audit, 'city_in_title_ok', True):
        recs.append("Add your city name to the page title (e.g. 'Plumber in Manchester') "
                    "to boost local keyword relevance.")
    # v5.0 Performance
    rt = getattr(audit, 'response_time_ms', None)
    if rt is not None and rt >= 600:
        recs.append(f"Reduce server response time from {rt}ms to under 600ms. "
                    "Enable caching and consider a CDN like Cloudflare.")
    if not getattr(audit, 'gzip_enabled', True):
        recs.append("Enable Gzip compression on your web server to reduce page transfer size by up to 70%.")
    if not getattr(audit, 'render_blocking_ok', True):
        recs.append("Fix render-blocking resources by adding defer/async attributes to scripts.")
    # v5.0 Schema Advanced
    if not getattr(audit, 'has_faq_schema', True):
        recs.append("Add FAQPage JSON-LD schema to unlock FAQ rich results in Google search.")
    if not getattr(audit, 'has_review_schema', True):
        recs.append("Add Review or AggregateRating schema to display star ratings in search results.")
    if not recs:
        recs.append("Site is technically healthy. Focus on content quality and "
                    "backlink building for further SEO improvement.")
    return recs


# ─── Impact Data ──────────────────────────────────────────────────────────────
IMPACT_DATA = {
    "ssl": {
        "title": "SSL Certificate (HTTPS)",
        "what": "An SSL certificate encrypts the connection between your website and visitors. "
                "Sites without SSL show a 'Not Secure' warning in Chrome and other browsers.",
        "google": "Google has used HTTPS as a direct ranking signal since 2014. Sites without SSL "
                  "are actively penalised in search rankings compared to HTTPS equivalents.",
        "business": "Visitors who see 'Not Secure' abandon sites immediately. Studies show a 64% "
                    "drop in conversions on HTTP sites vs HTTPS. It also affects Google Ads Quality "
                    "Score, raising your cost-per-click.",
        "fix": "Install a free Let's Encrypt SSL certificate via your hosting control panel (cPanel, "
               "Plesk). Redirect all HTTP traffic to HTTPS and update your Google Search Console property.",
    },
    "sitemap": {
        "title": "XML Sitemap",
        "what": "An XML sitemap is a file that lists all pages on your website and tells search engines "
                "where to find them, how often they change, and which are most important.",
        "google": "Without a sitemap, Googlebot has to crawl your site manually by following links. "
                  "New pages, blog posts, or product pages may never be discovered or indexed, "
                  "meaning they will never appear in Google search results.",
        "business": "Every un-indexed page is invisible to potential customers. If you run an "
                    "e-commerce site or blog, un-indexed content is 0% revenue. Sitemaps are "
                    "especially critical for sites with more than 10 pages.",
        "fix": "Generate a sitemap using a plugin (Yoast SEO, Rank Math) or an online tool. "
               "Submit it to Google Search Console under 'Sitemaps'. Update it whenever you add new pages.",
    },
    "robots": {
        "title": "robots.txt File",
        "what": "robots.txt is a text file that instructs search engine crawlers which pages they "
                "should or should not visit on your website.",
        "google": "Without robots.txt, crawlers waste your crawl budget on admin pages, login pages, "
                  "and duplicate content. This reduces the crawling of your important pages and "
                  "can lead to private pages appearing in search results.",
        "business": "Wasted crawl budget means your most valuable pages get crawled less frequently. "
                    "This directly delays how quickly new content appears in Google. In competitive "
                    "markets, slow indexing = lost traffic to competitors.",
        "fix": "Create a robots.txt file in your root directory. At minimum, disallow /admin/, "
               "/wp-admin/, and other internal paths. Ensure your sitemap URL is listed at the bottom.",
    },
    "broken_links": {
        "title": "Broken Links (404 Errors)",
        "what": "Broken links are hyperlinks on your website that point to pages that no longer exist, "
                "returning a 404 error. These can be internal links or links to external sites.",
        "google": "Google explicitly penalises sites with high numbers of broken links. They signal "
                  "poor site maintenance and reduce the flow of 'link equity' (PageRank) through "
                  "your site, weakening the authority of all your pages.",
        "business": "Each broken link is a dead end for a potential customer. Broken links on product "
                    "pages, contact forms, or CTAs mean direct, measurable revenue loss. They also "
                    "increase bounce rate, which further harms SEO rankings.",
        "fix": "Use a tool like Screaming Frog or Ahrefs to find all broken links. Either update "
               "the URL to the correct destination or set up a 301 redirect from the broken URL "
               "to a relevant live page.",
    },
    "h1": {
        "title": "H1 Heading Tag",
        "what": "The H1 tag is the main heading of a webpage. It is the most important on-page "
                "element that tells both users and search engines what the primary topic of a page is.",
        "google": "Google uses the H1 tag as one of the strongest signals for determining a page's "
                  "topic relevance. Pages without a clear H1 are significantly harder to rank for "
                  "target keywords. Each page should have exactly one H1.",
        "business": "Missing H1 tags mean your pages are competing in search with no declared topic. "
                    "Competitors with properly structured headings will outrank you for the same "
                    "keywords even with lower-quality content. This is one of the easiest and highest-"
                    "impact fixes available.",
        "fix": "Add one H1 tag to every page that contains your primary keyword. For a business "
               "homepage, this might be 'Professional Web Design Services in [City]'. Keep it "
               "descriptive, keyword-rich, and unique per page.",
    },
    "alt_text": {
        "title": "Image Alt Text",
        "what": "Alt text (alternative text) is a description added to image HTML tags. It describes "
                "the image content to screen readers and search engine crawlers, which cannot 'see' images.",
        "google": "Google Images drives significant search traffic. Without alt text, your images are "
                  "invisible to Google Image Search and contribute nothing to your page's keyword "
                  "relevance. It is also an accessibility requirement under WCAG guidelines.",
        "business": "Missing alt text means zero image search traffic. For product-based businesses, "
                    "this is a major missed revenue channel. It also exposes you to ADA/accessibility "
                    "lawsuit risk in markets like the USA and EU.",
        "fix": "Add descriptive alt attributes to every <img> tag. Be specific: use 'red-leather-"
               "office-chair-ergonomic' rather than 'chair' or 'image1'. Include your target "
               "keyword naturally where relevant.",
    },
    "webp": {
        "title": "WebP Image Format",
        "what": "WebP is a modern image format developed by Google that provides superior compression. "
                "WebP images are typically 25-35% smaller than equivalent JPEG or PNG files at the "
                "same visual quality.",
        "google": "Page speed is a direct Google ranking factor since 2010 (desktop) and 2018 "
                  "(mobile). Image size is the single largest contributor to slow load times. "
                  "Google's Core Web Vitals score, which directly impacts rankings, is heavily "
                  "influenced by image optimisation.",
        "business": "A 1-second delay in page load time reduces conversions by 7% (Akamai study). "
                    "On mobile, 53% of users abandon sites that take longer than 3 seconds. Switching "
                    "to WebP can reduce image payload by 30-50%, directly improving load speed, "
                    "bounce rate, and conversion rate.",
        "fix": "Convert all images to WebP format using tools like Squoosh, ImageMagick, or a CMS "
               "plugin (ShortPixel, Imagify). Serve WebP with a JPEG/PNG fallback using the HTML "
               "<picture> element for older browser compatibility.",
    },
    "json_ld": {
        "title": "JSON-LD Structured Data (Schema Markup)",
        "what": "JSON-LD is a type of code added to web pages that speaks directly to Google in "
                "machine-readable format. It describes your business: name, address, phone, hours, "
                "reviews, services, FAQs, and more.",
        "google": "Structured data enables 'Rich Results' in Google Search - star ratings, FAQs, "
                  "business hours, and review counts displayed directly in the search results. "
                  "Rich results have click-through rates 20-40% higher than standard results.",
        "business": "Without structured data, your search listing is a plain blue link. Competitors "
                    "with rich results (stars, FAQs, prices) dominate above you visually even if "
                    "you rank equally. JSON-LD also powers Google Business Profile integration, "
                    "local pack visibility, and voice search answers.",
        "fix": "Implement Organization or LocalBusiness schema on your homepage. Add FAQPage schema "
               "to your FAQ page and Product schema on product pages. Use Google's Rich Results "
               "Test tool to validate. JSON-LD is inserted in a <script> tag - no page redesign needed.",
    },
    "mobile": {
        "title": "Mobile Responsive Design",
        "what": "Mobile responsiveness means your website automatically adjusts its layout, font sizes, "
                "images, and navigation to display perfectly on smartphones and tablets. It requires "
                "both a viewport meta tag AND CSS media queries — without both, the site physically "
                "does not adapt to smaller screens.",
        "google": "Google switched to Mobile-First Indexing for ALL sites in 2021. This means Google "
                  "crawls, indexes, and ranks your website based on how it looks and performs on mobile — "
                  "not desktop. A site that fails on mobile is penalised in ALL search results, including "
                  "desktop results. Google PageSpeed Insights and Core Web Vitals also heavily factor in "
                  "mobile performance. This is the single biggest ranking factor you can fix today.",
        "business": "In India, 78%+ of web traffic comes from mobile devices. Every visitor hitting your "
                    "non-responsive site on a phone sees a broken, zoomed-out, impossible-to-use layout. "
                    "They leave within 3 seconds — and Google records that as a 'bounce', further hurting "
                    "your rankings. This directly destroys your brand credibility: a broken mobile site "
                    "signals to customers that your business is unprofessional, outdated, and not trustworthy. "
                    "If you run Google Ads or Meta Ads, a non-mobile landing page can literally double your "
                    "cost-per-lead and halve your conversion rate. Every day this is unfixed, you are "
                    "actively losing customers to competitors who are mobile-ready.",
        "fix": "Step 1: Add this line inside <head>: <meta name='viewport' content='width=device-width, initial-scale=1'>. "
               "Step 2: Add CSS media queries to make all elements responsive (@media (max-width: 768px) {...}). "
               "Step 3: Test with Google's Mobile-Friendly Test (search.google.com/test/mobile-friendly). "
               "Step 4: Check Core Web Vitals in Google Search Console under 'Page Experience'. "
               "If your site needs a full responsive rebuild, TEB Solutions can do this in 5-7 days.",
    },
    "cta": {
        "title": "Call-to-Action (CTA) Button",
        "what": "A Call-to-Action button is a prominently placed interactive element that tells visitors "
                "what to do next — 'Get a Free Quote', 'Book Now', 'Contact Us'. It is the primary "
                "conversion driver on any business website.",
        "google": "Google's Core Web Vitals and engagement metrics (bounce rate, time-on-page, "
                  "conversion rate) are indirect ranking signals. A page with no clear CTA sees high "
                  "bounce rates, which signals poor content relevance to Google.",
        "business": "Websites with a clear CTA convert 200% more visitors than those without. Without "
                    "a CTA, visitors who want to contact you have no obvious next step and leave. "
                    "Every visitor who leaves without converting is a lost potential customer.",
        "fix": "Add a prominent button in a contrasting colour (e.g. orange on dark blue) above the fold. "
               "Text: 'Get a Free Quote', 'Book a Consultation', or 'Call Now'. "
               "Link it to your contact form or phone number.",
    },
    "hero_headline": {
        "title": "Hero Value Proposition Headline",
        "what": "The hero headline is the first large H1 heading visitors see at the top of your homepage. "
                "It should immediately communicate what your business does and who it serves.",
        "google": "The H1 is one of the strongest on-page SEO signals. A page where the H1 matches the "
                  "searcher's query intent ranks higher. A missing or vague hero headline means Google "
                  "cannot clearly classify the page's topic.",
        "business": "Visitors decide to stay or leave within 3 seconds of landing on your site. "
                    "Without a clear value proposition headline, they do not understand what you offer "
                    "and leave immediately. This increases bounce rate and reduces conversions.",
        "fix": "Add an H1 at the very top of your homepage describing exactly what you do and where: "
               "e.g. 'Professional Plumbing Services in Manchester' or 'Affordable Wedding Photography "
               "in Sydney'. One sentence, keyword-rich, instantly clear.",
    },
    "nav": {
        "title": "Navigation Menu",
        "what": "The navigation menu is the primary wayfinding system of your website. It allows visitors "
                "to quickly find Services, About, Contact, and other key pages without guessing.",
        "google": "Navigation links are critical for passing 'link equity' (PageRank) from your homepage "
                  "to inner pages. A missing or sparse navigation means deep pages receive no internal "
                  "authority and may rank poorly even with good content.",
        "business": "Poor or missing navigation directly causes visitors to leave without exploring your "
                    "services or contacting you. Studies show that 38% of users will stop engaging with "
                    "a website if the layout or navigation is unattractive or confusing.",
        "fix": "Add a <nav> HTML element with at least 3-5 clear links: Home, Services, About Us, "
               "Contact. Place it at the top of every page. On mobile, use a hamburger menu that "
               "expands to show the same links.",
    },
    "social": {
        "title": "Social Media Profile Presence",
        "what": "Social media profiles on platforms like Facebook, Instagram, LinkedIn, and Twitter "
                "are part of your brand's online footprint. Google indexes these profiles and uses "
                "them as trust and authority signals.",
        "google": "Missing social profiles create an incomplete 'Knowledge Panel' when people search "
                  "your brand name. Google uses social signals as indirect trust indicators. "
                  "A brand with no social presence appears less credible and established to both "
                  "users and algorithms.",
        "business": "When a potential customer searches your business name and finds no Facebook, "
                    "Instagram, or LinkedIn, they question your legitimacy. Studies show 54% of "
                    "consumers research a business on social media before making a purchase. "
                    "Missing platforms also means zero access to billions of users on those platforms "
                    "for organic or paid marketing.",
        "fix": "Create and fully optimise profiles on Facebook (Business Page), Instagram, LinkedIn "
               "(Company Page), and Twitter/X. Use consistent branding, descriptions, and website "
               "links. Even if you do not plan to post daily, claiming your brand name on each "
               "platform is essential for brand protection.",
    },
}


def _impact_block(pdf: FPDF, data: dict):
    """Render a single impact analysis block for one SEO factor."""
    # Title bar
    pdf.set_fill_color(30, 64, 175)   # PRIMARY blue
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, _safe(f"  {data['title']}"), fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    rows = [
        ("What it is:",      data["what"]),
        ("Google impact:",   data["google"]),
        ("Business impact:", data["business"]),
        ("How to fix it:",   data["fix"]),
    ]
    for label, body in rows:
        # Label
        pdf.set_fill_color(248, 250, 252)  # LIGHT_BG
        pdf.set_text_color(30, 64, 175)    # PRIMARY
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, _safe(f"  {label}"), fill=True,
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        # Body
        pdf.set_text_color(15, 23, 42)     # DARK
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _safe(f"  {body}"))

    pdf.ln(4)


def _build_impact_analysis(pdf: FPDF, audit):
    """Render deep impact analysis only for failing factors."""
    if not audit.ssl_valid:
        _impact_block(pdf, IMPACT_DATA["ssl"])
    if not audit.has_sitemap:
        _impact_block(pdf, IMPACT_DATA["sitemap"])
    if not audit.has_robots:
        _impact_block(pdf, IMPACT_DATA["robots"])
    if audit.broken_links_count and audit.broken_links_count > 0:
        _impact_block(pdf, IMPACT_DATA["broken_links"])
    if audit.missing_h1:
        _impact_block(pdf, IMPACT_DATA["h1"])
    if audit.missing_alt_count and audit.missing_alt_count > 0:
        _impact_block(pdf, IMPACT_DATA["alt_text"])
    if not audit.uses_webp:
        _impact_block(pdf, IMPACT_DATA["webp"])
    if not audit.has_json_ld:
        _impact_block(pdf, IMPACT_DATA["json_ld"])
    if not audit.mobile_friendly:
        _impact_block(pdf, IMPACT_DATA["mobile"])
    if audit.missing_social:
        _impact_block(pdf, IMPACT_DATA["social"])
    # Phase 3: UI/UX impact blocks
    if not getattr(audit, 'has_cta', True):
        _impact_block(pdf, IMPACT_DATA["cta"])
    if not getattr(audit, 'has_hero_headline', True):
        _impact_block(pdf, IMPACT_DATA["hero_headline"])
    nav_c = getattr(audit, 'nav_links_count', None)
    if nav_c is not None and nav_c < 3:
        _impact_block(pdf, IMPACT_DATA["nav"])
