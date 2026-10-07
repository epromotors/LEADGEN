"""
Generate a sample PDF audit report to test the new clean layout.
Run from the LEADGEN root: python gen_pdf_preview.py
"""
import sys, os

# Add auditor package to path
sys.path.insert(0, os.path.join("auditor", "auditor"))

from reporter.pdf_report import build_pdf

# ── Mock data — realistic audit results ────────────────────────────────────
MOCK_URL = "https://www.roblumco.com"
MOCK_SCORE = 47

MOCK_AUDIT_RESULTS = {
    "technical": {
        "ssl": {
            "status": "FAIL",
            "message": "Site is not served over HTTPS. All traffic is unencrypted.",
            "fix": "Install an SSL certificate. Free options: Let's Encrypt via your host's control panel.",
            "detail": "HTTP detected at https://www.roblumco.com",
        },
        "sitemap": {
            "status": "FAIL",
            "message": "No sitemap.xml found. Search engines cannot efficiently crawl your site.",
            "fix": "Generate a sitemap at /sitemap.xml and submit it in Google Search Console.",
            "detail": "Checked: https://www.roblumco.com/sitemap.xml",
        },
        "robots": {
            "status": "WARN",
            "message": "robots.txt exists but does not specify a Sitemap directive.",
            "fix": "Add 'Sitemap: https://www.roblumco.com/sitemap.xml' to your robots.txt.",
            "detail": "Found: https://www.roblumco.com/robots.txt",
        },
        "canonical": {
            "status": "FAIL",
            "message": "No canonical tag found on the homepage.",
            "fix": "Add <link rel='canonical' href='https://www.roblumco.com/'> to the <head>.",
            "detail": None,
        },
        "favicon": {
            "status": "WARN",
            "message": "No favicon found. Favicons improve brand recognition in browser tabs.",
            "fix": "Upload a 32x32 PNG as /favicon.ico and link it in <head>.",
            "detail": None,
        },
        "mobile": {
            "status": "PASS",
            "message": "Mobile viewport meta tag is correctly configured.",
            "fix": None,
            "detail": "Viewport: width=device-width, initial-scale=1",
        },
    },
    "onpage": {
        "page_title": {
            "status": "WARN",
            "message": "Page title is too short (18 chars). Ideal is 50–60 characters.",
            "fix": "Rewrite to: 'Roblumco Lumber | Quality Wood Products & Building Materials'",
            "detail": "Current title: 'Roblumco | Lumber'",
        },
        "meta_desc": {
            "status": "FAIL",
            "message": "No meta description found. This is used by Google in search results.",
            "fix": "Add a 140–160 character meta description summarising the page content.",
            "detail": None,
        },
        "h1": {
            "status": "FAIL",
            "message": "Multiple H1 tags found (7 total). This confuses search crawlers.",
            "fix": "Use exactly one H1 per page — the primary heading that describes the page.",
            "detail": "H1 tags found: 7",
        },
        "og_tags": {
            "status": "FAIL",
            "message": "Open Graph / Twitter Card tags are missing: og:title, og:description, og:image.",
            "fix": "Add OG meta tags in <head> for better social media sharing appearance.",
            "detail": "Missing: og:title, og:description, og:image, twitter:card",
        },
        "schema": {
            "status": "FAIL",
            "message": "No JSON-LD Schema Markup found. Structured data helps Google display rich results.",
            "fix": "Add LocalBusiness or Organization schema markup to your homepage.",
            "detail": None,
        },
    },
    "images": {
        "alt_text": {
            "status": "WARN",
            "message": "9 decorative images have empty alt='' (OK if intentional).",
            "fix": "Add descriptive alt text to all content images for accessibility and SEO.",
            "detail": "9 images missing alt text out of 24 total images",
        },
        "webp": {
            "status": "FAIL",
            "message": "No WebP images found. All 5 images use heavy legacy formats (JPG/PNG).",
            "fix": "Convert images to WebP format. Use Squoosh.app or an image CDN.",
            "detail": "5 legacy images detected",
        },
        "lazy_load": {
            "status": "PASS",
            "message": "Images use lazy loading (loading='lazy'). Good for page speed.",
            "fix": None,
            "detail": None,
        },
    },
    "links": {
        "broken_links": {
            "status": "FAIL",
            "message": "3 broken links found out of 19 checked.",
            "fix": "Fix or remove broken links. Update internal pages, set up 301 redirects.",
            "detail": "Broken: /products/old-page, /contact-old, /careers-2020",
        },
    },
    "conversion": {
        "social": {
            "status": "WARN",
            "message": "Some social media links missing: Pinterest.",
            "fix": "Add links to all active social profiles in the header or footer.",
            "detail": "Found: Facebook, Twitter. Missing: Pinterest, Instagram",
        },
        "contact": {
            "status": "WARN",
            "message": "Missing contact link types: phone (tel:), fax.",
            "fix": "Add a clickable phone number using <a href='tel:+1234567890'>.",
            "detail": None,
        },
        "whatsapp": {
            "status": "FAIL",
            "message": "No WhatsApp integration found.",
            "fix": "Add a WhatsApp chat button: wa.me/YOUR_NUMBER",
            "detail": None,
        },
        "trust": {
            "status": "FAIL",
            "message": "Privacy Policy and Terms of Service pages are MISSING.",
            "fix": "Create /privacy-policy and /terms-of-service pages. Required for GDPR.",
            "detail": None,
        },
    },
}

# ── Mock site-wide crawl data ───────────────────────────────────────────────
MOCK_SITE_SUMMARY = {
    "total_pages": 25,
    "status_counts": {"PASS": 4, "WARN": 12, "FAIL": 9},
    "top_issues": [
        ("Missing Meta Description",    22),
        ("Multiple H1 Tags",            18),
        ("Missing Canonical Tag",       20),
        ("No Open Graph Tags",          19),
        ("Missing JSON-LD Schema",      22),
        ("Legacy Image Formats (JPG)",   8),
        ("Missing Alt Text",            11),
        ("No WhatsApp Button",           9),
        ("Missing Trust Pages",         25),
        ("Title Too Short (<40 chars)", 14),
    ],
    "worst_pages": [
        {"url": "https://www.roblumco.com/products/lumber",    "issue_count": 8, "status": "FAIL"},
        {"url": "https://www.roblumco.com/news/update-2024",   "issue_count": 7, "status": "FAIL"},
        {"url": "https://www.roblumco.com/history",            "issue_count": 6, "status": "FAIL"},
        {"url": "https://www.roblumco.com/contact",            "issue_count": 5, "status": "WARN"},
        {"url": "https://www.roblumco.com/projects",           "issue_count": 5, "status": "WARN"},
        {"url": "https://www.roblumco.com/decking",            "issue_count": 4, "status": "WARN"},
        {"url": "https://www.roblumco.com/locations",          "issue_count": 4, "status": "WARN"},
        {"url": "https://www.roblumco.com/careers",            "issue_count": 3, "status": "WARN"},
        {"url": "https://www.roblumco.com/",                   "issue_count": 2, "status": "WARN"},
    ],
}

MOCK_PAGE_AUDITS = [
    {"url": "https://www.roblumco.com/",                "title": "Roblumco | Lumber",      "issues": [{"severity":"WARN","check":"Title Too Short"},{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"FAIL","check":"Multiple H1 Tags (7)"}]},
    {"url": "https://www.roblumco.com/values",          "title": "Our Values",             "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"}]},
    {"url": "https://www.roblumco.com/news/robinson",   "title": "News",                   "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"}]},
    {"url": "https://www.roblumco.com/history",         "title": "History",                "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"},{"severity":"FAIL","check":"No Schema Markup"},{"severity":"FAIL","check":"No OG Tags"},{"severity":"WARN","check":"Title Too Short"}]},
    {"url": "https://www.roblumco.com/news",            "title": "News",                   "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"}]},
    {"url": "https://www.roblumco.com/sustainability",  "title": "Sustainability Report",  "issues": []},
    {"url": "https://www.roblumco.com/",                "title": "Roblumco Family",        "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"},{"severity":"FAIL","check":"No OG Tags"}]},
    {"url": "https://www.roblumco.com/lumber",          "title": "Lumber",                 "issues": [{"severity":"WARN","check":"Title Too Short"},{"severity":"FAIL","check":"Missing Schema"},{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"FAIL","check":"No OG Social Tags"},{"severity":"FAIL","check":"No JSON-LD"},{"severity":"WARN","check":"Missing Alt Text (3 images)"},{"severity":"FAIL","check":"Legacy Image Formats"},{"severity":"WARN","check":"Broken Internal Link"}]},
    {"url": "https://www.roblumco.com/flooring",        "title": "Flooring - Roblumco",   "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"}]},
    {"url": "https://www.roblumco.com/projects",        "title": "Projects",               "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"}]},
    {"url": "https://www.roblumco.com/decking",         "title": "Decking - Roblumco",    "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"},{"severity":"WARN","check":"No alt on hero image"}]},
    {"url": "https://www.roblumco.com/locations",       "title": "Locations",              "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"},{"severity":"WARN","check":"No structured address markup"}]},
    {"url": "https://www.roblumco.com/careers",         "title": "Careers",                "issues": [{"severity":"WARN","check":"Title Too Short"},{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"}]},
    {"url": "https://www.roblumco.com/contact",         "title": "Contact",                "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"WARN","check":"No tel: link"}]},
    {"url": "https://www.roblumco.com/news/releases",   "title": "News Releases",          "issues": [{"severity":"FAIL","check":"Missing Meta Description"},{"severity":"WARN","check":"Multiple H1 Tags"},{"severity":"FAIL","check":"Missing Canonical"}]},
]

# ── Output paths ───────────────────────────────────────────────────────────
OUT_DIR = os.path.join("samples")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "roblumco_audit_report_v2.pdf")

print("Generating PDF...")
result = build_pdf(
    url=MOCK_URL,
    audit_results=MOCK_AUDIT_RESULTS,
    score=MOCK_SCORE,
    output_path=OUT_PATH,
    site_summary=MOCK_SITE_SUMMARY,
    page_audits=MOCK_PAGE_AUDITS,
)
print(f"PDF saved: {result}")
print(f"Size: {os.path.getsize(result):,} bytes")
