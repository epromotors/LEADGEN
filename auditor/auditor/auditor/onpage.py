# auditor/onpage.py — H1, Meta Description, OG Tags, Schema, Title

import json
from auditor.core import result_pass, result_warn, result_fail


def audit_title(soup) -> dict:
    """Check page title presence, length, and quality."""
    title_tag = soup.find("title")
    if not title_tag or not title_tag.get_text(strip=True):
        return result_fail(
            "Page title (<title>) is missing.",
            "Add a descriptive <title> tag in <head>. Format: 'Primary Keyword | Brand Name'. "
            "This is one of the single most important on-page SEO signals.",
        )
    title_text = title_tag.get_text(strip=True)
    length = len(title_text)
    if length < 30:
        return result_warn(
            f"Title is too short ({length} chars): '{title_text}'",
            "Expand to 50–60 characters. Include your main keyword near the start.",
            f"Title: {title_text}",
        )
    if length > 65:
        return result_warn(
            f"Title is too long ({length} chars) — Google will truncate it.",
            "Shorten to 50–60 characters to avoid truncation in search results.",
            f"Title: {title_text}",
        )
    return result_pass(f"Title tag OK ({length} chars): '{title_text}'")


def audit_meta_description(soup) -> dict:
    """Check meta description presence and length."""
    meta = soup.find("meta", attrs={"name": "description"})
    if not meta or not meta.get("content", "").strip():
        return result_fail(
            "Meta description is missing.",
            "Add <meta name='description' content='Your 150-160 char description here'>. "
            "This is the text shown under your link in Google results — it directly affects click-through rate.",
        )
    content = meta["content"].strip()
    length = len(content)
    if length < 70:
        return result_warn(
            f"Meta description is too short ({length} chars).",
            "Expand to 140–160 characters. Include your primary keyword and a call-to-action.",
            f"Description: {content[:120]}...",
        )
    if length > 165:
        return result_warn(
            f"Meta description is too long ({length} chars) — Google will cut it off.",
            "Trim to 155–160 characters max.",
            f"Description: {content[:120]}...",
        )
    return result_pass(f"Meta description OK ({length} chars).", detail=content[:100] + "...")


def audit_h1(soup) -> dict:
    """Check H1: missing, multiple, or content quality."""
    h1_tags = soup.find_all("h1")
    if not h1_tags:
        return result_fail(
            "No H1 heading found on the page.",
            "Add exactly one <h1> tag containing your primary keyword. "
            "The H1 is the most important on-page heading signal for Google.",
        )
    if len(h1_tags) > 1:
        texts = [h.get_text(strip=True)[:60] for h in h1_tags]
        return result_warn(
            f"Multiple H1 tags found ({len(h1_tags)} total). This confuses search crawlers.",
            "Keep exactly one <h1> per page. Demote extras to <h2> or <h3>.",
            "H1s found: " + " | ".join(texts),
        )
    h1_text = h1_tags[0].get_text(strip=True)
    if len(h1_text) < 5:
        return result_warn(
            f"H1 tag is too short: '{h1_text}'",
            "Write a descriptive H1 that includes your target keyword (aim for 20–70 characters).",
        )
    return result_pass(f"Single H1 found: '{h1_text[:70]}'")


def audit_og_tags(soup, page_url: str) -> dict:
    """Check Open Graph and Twitter Card meta tags."""
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    og_desc = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")
    twitter_card = soup.find("meta", attrs={"name": "twitter:card"})
    twitter_image = soup.find("meta", attrs={"name": "twitter:image"})

    missing = []
    if not og_title:
        missing.append("og:title")
    if not og_desc:
        missing.append("og:description")
    if not og_image:
        missing.append("og:image")
    if not twitter_card:
        missing.append("twitter:card")

    if len(missing) >= 3:
        return result_fail(
            f"Open Graph / Twitter Card tags are missing: {', '.join(missing)}",
            "Add OG tags in your <head>:\n"
            "<meta property='og:title' content='Your Title'>\n"
            "<meta property='og:description' content='Description'>\n"
            "<meta property='og:image' content='https://yourdomain.com/og-image.jpg'>\n"
            "<meta name='twitter:card' content='summary_large_image'>\n"
            "These control how your link previews look on WhatsApp, Facebook, LinkedIn, and Twitter.",
        )
    if missing:
        present = [t for t in ['og:title', 'og:description', 'og:image', 'twitter:card'] if t not in missing]
        return result_warn(
            f"Some OG/Twitter tags missing: {', '.join(missing)}",
            f"Add the missing tags to complete your social sharing setup.",
            f"Present: {', '.join(present)}",
        )
    return result_pass("Open Graph and Twitter Card tags are fully configured.")


def audit_schema(soup) -> dict:
    """Check for JSON-LD structured data (Schema.org)."""
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    
    if not json_ld_scripts:
        # Also check for microdata
        microdata = soup.find(attrs={"itemscope": True})
        if microdata:
            return result_warn(
                "Legacy microdata schema found, but no JSON-LD.",
                "Migrate to JSON-LD format — it's Google's preferred schema format. "
                "Add <script type='application/ld+json'>{...}</script> for Organization, "
                "LocalBusiness, Product, FAQ, or Article schema as appropriate.",
            )
        return result_fail(
            "No JSON-LD Schema Markup found.",
            "Add Schema.org structured data to unlock Google Rich Snippets (star ratings, "
            "FAQs, breadcrumbs, etc.). Minimum for local business:\n"
            '<script type="application/ld+json">{"@context":"https://schema.org","@type":"LocalBusiness",'
            '"name":"Your Business","url":"https://yourdomain.com"}</script>',
        )
    
    schema_types = []
    for script in json_ld_scripts:
        try:
            data = json.loads(script.get_text())
            t = data.get("@type") or data.get("@graph", [{}])[0].get("@type", "Unknown")
            schema_types.append(str(t))
        except Exception:
            schema_types.append("Invalid JSON-LD")
    
    if "Invalid JSON-LD" in schema_types:
        return result_warn(
            "JSON-LD Schema found but contains invalid JSON.",
            "Validate your schema at schema.org/validator or Google's Rich Results Test. "
            "Invalid JSON breaks rich snippet eligibility.",
            f"Types detected: {', '.join(schema_types)}",
        )
    
    return result_pass(
        f"JSON-LD Schema Markup found: {', '.join(schema_types)}",
        detail="Validate at: https://search.google.com/test/rich-results",
    )


# ── GROUP B NEW FUNCTIONS ─────────────────────────────────────────────────────

import re as _re


def audit_noindex(soup) -> dict:
    """
    Detect meta robots noindex/nofollow directives.

    SEO Impact: Critical — noindex prevents page from appearing in Google.
    Source: https://developers.google.com/search/docs/crawling-indexing/block-indexing
    """
    robots_meta = soup.find("meta", attrs={"name": _re.compile(r"^robots$", _re.I)})
    if not robots_meta:
        return result_pass(
            "No meta robots tag found — page is indexable by default.",
            detail="Googlebot indexes pages without a meta robots tag.",
        )

    content = robots_meta.get("content", "").lower()
    if "noindex" in content:
        return result_fail(
            "Page has 'noindex' meta robots tag — Google CANNOT index this page!",
            "Remove the 'noindex' directive from the meta robots tag immediately. "
            "While 'noindex' is intentional on private pages, it is catastrophic on public pages. "
            "Check: <meta name='robots' content='noindex'> in your <head>.",
            f"Current content: '{content}'",
        )
    if "nofollow" in content:
        return result_warn(
            "Page has 'nofollow' meta robots tag — Google will not follow links on this page.",
            "Remove 'nofollow' from the meta robots tag unless you intentionally want to block link equity flow. "
            "Nofollow on a homepage prevents internal PageRank distribution.",
            f"Current content: '{content}'",
        )
    return result_pass(
        f"Meta robots tag is safe: '{content}'.",
        detail="Page is indexable and links are followable.",
    )


def audit_heading_hierarchy(soup) -> dict:
    """
    Check for skipped heading levels (e.g., H1 → H3 with no H2).

    SEO Impact: Medium — proper heading hierarchy helps crawlers understand page structure.
    Source: https://web.dev/articles/headings-and-landmarks
    """
    heading_tags = ["h1", "h2", "h3", "h4", "h5", "h6"]
    levels_found = []
    for level, tag in enumerate(heading_tags, start=1):
        if soup.find(tag):
            levels_found.append(level)

    if not levels_found:
        return result_warn(
            "No heading tags (H1–H6) found on the page.",
            "Add at least an H1 and H2 to define page structure for both users and search engines.",
        )

    skipped = []
    for i in range(len(levels_found) - 1):
        gap = levels_found[i + 1] - levels_found[i]
        if gap > 1:
            skipped.append(f"H{levels_found[i]} → H{levels_found[i+1]} (skipped H{levels_found[i]+1})")

    if skipped:
        return result_warn(
            f"Heading hierarchy has {len(skipped)} skipped level(s).",
            "Fix heading order so levels increase by 1 (H1 → H2 → H3). "
            "Skipped levels confuse screen readers and make content harder for crawlers to parse.",
            " | ".join(skipped),
        )

    return result_pass(
        f"Heading hierarchy is correct: H{' → H'.join(str(l) for l in levels_found)}.",
    )


def audit_internal_links(soup, base_url: str = "") -> dict:
    """
    Count internal links and flag if very few exist (potential orphan-page risk).

    SEO Impact: Medium — internal links distribute PageRank and aid crawlability.
    Source: https://developers.google.com/search/docs/crawling-indexing/links-crawlable
    """
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    domain = parsed.netloc.lstrip("www.")

    all_links = soup.find_all("a", href=True)
    internal = []
    for a in all_links:
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("/") or (domain and domain in href):
            internal.append(href)

    count = len(internal)
    if count == 0:
        return result_fail(
            "No internal links found on the homepage.",
            "Add internal links to your key pages (Services, About, Contact). "
            "Internal links help Googlebot discover and index all your pages.",
        )
    if count < 5:
        return result_warn(
            f"Very few internal links found ({count}). Risk of orphan pages.",
            "Add more internal links to improve crawlability. A homepage should link to at least "
            "5–10 key internal pages so Googlebot can reach them all.",
            f"Internal links found: {count}",
        )
    return result_pass(
        f"Internal links found: {count}.",
        detail=f"Healthy internal link count detected on {base_url}",
    )


def audit_anchor_text_quality(soup) -> dict:
    """
    Detect generic anchor text like 'click here', 'read more', 'learn more'.

    SEO Impact: Low-Medium — descriptive anchor text helps Google understand link context.
    Source: https://developers.google.com/search/docs/crawling-indexing/links-crawlable
    """
    _GENERIC = {
        "click here", "click", "here", "read more", "learn more",
        "more", "this", "this link", "link", "page", "website",
        "go here", "tap here", "see more", "view more",
    }
    generic_links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if text in _GENERIC:
            href = a.get("href", "")[:60]
            generic_links.append(f"'{a.get_text(strip=True)}' → {href}")
        if len(generic_links) >= 5:
            break

    if generic_links:
        return result_warn(
            f"Generic anchor text detected on {len(generic_links)} link(s).",
            "Replace generic link text ('click here', 'read more') with descriptive keywords. "
            "Example: Instead of 'Click here', use 'View our SEO packages'. "
            "Descriptive anchors help Google understand what the linked page is about.",
            " | ".join(generic_links[:3]),
        )
    return result_pass(
        "Anchor text quality looks good — no generic 'click here' links detected.",
    )


def audit_image_filenames(soup) -> dict:
    """
    Flag non-descriptive image filenames (img1.jpg, 123.png, DSC_001.jpg, etc.).

    SEO Impact: Low-Medium — descriptive filenames help Google Image Search.
    Source: https://developers.google.com/search/docs/appearance/google-images
    """
    _GENERIC_PATTERNS = _re.compile(
        r"^(img|image|photo|pic|picture|screenshot|banner|dsc|file|upload|"
        r"untitled|default|placeholder|temp|test|new|copy|background|bg|"
        r"thumbs?|thumb_|preview)[\d_\-\.]*\.(jpe?g|png|gif|webp|svg)$",
        _re.IGNORECASE,
    )
    _NUMERIC = _re.compile(r"^\d+[\d_\-]*\.(jpe?g|png|gif|webp)$", _re.IGNORECASE)

    bad_files = []
    for img in soup.find_all("img", src=True):
        src = img.get("src", "")
        # Get just the filename
        fname = src.split("?")[0].split("/")[-1]
        if _GENERIC_PATTERNS.match(fname) or _NUMERIC.match(fname):
            bad_files.append(fname[:60])
        if len(bad_files) >= 5:
            break

    if bad_files:
        return result_warn(
            f"{len(bad_files)} image(s) have generic/non-descriptive filenames.",
            "Rename image files to include descriptive keywords before uploading. "
            "Example: 'photo1.jpg' → 'car-window-tinting-sydney.jpg'. "
            "Descriptive filenames help images rank in Google Image Search and improve context.",
            " | ".join(bad_files[:3]),
        )
    return result_pass(
        "Image filenames appear descriptive — no generic names detected.",
    )
