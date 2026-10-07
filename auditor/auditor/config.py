# config.py — SEO Audit Tool Configuration
# TEB Solutions | tebsolutions.in

BRANDING = {
    "agency_name": "TEB Solutions",
    "website": "tebsolutions.in",
    "email": "info@tebsolutions.in",
    "report_footer": "Prepared by TEB Solutions — Professional SEO & Web Design Agency",
    "primary_color": (0.06, 0.35, 0.75),      # #0F59BF
    "accent_color": (0.0, 0.78, 0.47),         # #00C778
    "danger_color": (0.87, 0.17, 0.17),        # #DE2B2B
    "warn_color": (0.95, 0.60, 0.07),          # #F2991A
    "pass_color": (0.08, 0.65, 0.32),          # #15A651
    "dark_color": (0.10, 0.11, 0.14),          # #1A1C24
    "light_gray": (0.95, 0.95, 0.97),          # #F2F2F8
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = 12          # seconds per request
MAX_LINKS_TO_CHECK = 50
LINK_CHECK_WORKERS = 8

# Social platforms to check for
SOCIAL_PLATFORMS = {
    "Facebook": ["facebook.com/", "fb.com/"],
    "Instagram": ["instagram.com/"],
    "LinkedIn": ["linkedin.com/"],
    "Twitter/X": ["twitter.com/", "x.com/"],
    "YouTube": ["youtube.com/"],
    "Pinterest": ["pinterest.com/"],
}

# Trust page keywords to detect in footer/nav links
TRUST_KEYWORDS = ["privacy", "terms", "disclaimer", "cookie", "gdpr", "refund", "legal"]

# Scoring weights per group (must sum to 100)
# v5.0.0: 5 new axes added — weights rebalanced proportionally
SCORE_WEIGHTS = {
    "technical":      18,   # was 25
    "onpage":         16,   # was 23
    "images":          7,   # was 10
    "links":           5,   # was 8
    "conversion":     12,   # was 19
    "ux":             10,   # was 15
    # v5.0 new axes
    "indexability":    8,
    "content":         8,
    "local_seo":       7,
    "performance":     5,
    "schema_advanced": 4,
}

# Per-test max scores (within each group)
# Keys MUST match the exact test_id used in audit_results in audit_engine.py
TEST_SCORES = {
    # technical group
    "ssl":          10,
    "sitemap":       8,
    "robots":        7,
    "canonical":     5,
    "favicon":       3,
    "mobile":        8,
    # technical v5.0 new
    "https_redirect":        6,
    "redirect_chain":        4,
    "mixed_content":         5,
    "www_canonicalization":  4,
    # onpage group
    "page_title":   10,
    "meta_desc":     8,
    "h1":            8,
    "og_tags":       5,
    "schema":        7,
    # onpage v5.0 new
    "noindex":              8,
    "heading_hierarchy":    4,
    "internal_links":       4,
    "anchor_text_quality":  3,
    "image_filenames":      3,
    # images group
    "alt_text":      5,
    "webp":          4,
    "lazy_load":     3,
    # links group
    "broken_links": 10,
    # conversion group
    "social":        4,
    "contact":       6,
    "whatsapp":      4,
    "trust":         6,
    # ux group (v4.5.0)
    "cta":           8,
    "cta_above_fold": 5,
    "hero_headline": 6,
    "font_size":     4,
    "contrast":      5,
    "nav_links":     5,
    "cookie_notice": 3,
    "live_chat":     4,
    # ux v5.0 new
    "phone_number":    5,
    "address_presence": 5,
    # indexability group (v5.0)
    "noindex":           8,
    "url_structure":     5,
    "www_vs_nonwww":     6,
    "soft_404":          6,
    # content group (v5.0)
    "word_count":        8,
    "duplicate_meta":    5,
    "keyword_in_title":  6,
    "reading_level":     5,
    # local_seo group (v5.0)
    "nap_consistency":        8,
    "local_business_schema":  8,
    "google_maps_embed":      5,
    "city_in_title":          5,
    "business_hours":         4,
    # performance group (v5.0)
    "response_time":     8,
    "page_size":          4,
    "render_blocking":    5,
    "gzip_compression":   5,
    "webp_images":         4,
    "minification":        3,
    # schema_advanced group (v5.0)
    "faq_schema":         5,
    "product_schema":     5,
    "breadcrumb_schema":  4,
    "review_schema":      5,
    "graph_schema":       4,
}

SCORE_BANDS = [
    (85, 101, "🟢 Excellent", "Your website is well-optimised for search engines."),
    (65, 85,  "🟡 Good — Needs Work", "Several issues need attention to reach top rankings."),
    (40, 65,  "🟠 Poor — Action Required", "Significant SEO problems are hurting your visibility."),
    (0,  40,  "🔴 Critical", "Urgent fixes required. This site will struggle to rank at all."),
]
