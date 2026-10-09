# auditor/ux.py — UI/UX & Experience Audit Checks
# TEB Solutions | LeadGen OS v4.5.0
# 8 checks via HTML source analysis (no browser rendering required).
# Each function returns: {"status": "PASS"|"WARN"|"FAIL", "message": str, "fix": str, "detail": str}

import re
from auditor.core import result_pass, result_warn, result_fail

# ── CTA keyword sets ──────────────────────────────────────────────────────────
_CTA_KEYWORDS = {
    "get quote", "get a quote", "free quote", "request quote",
    "contact us", "contact", "get in touch", "reach out",
    "book now", "book a", "schedule", "appointment",
    "call us", "call now", "click to call",
    "buy now", "add to cart", "shop now", "order now",
    "start now", "get started", "try free", "try now", "sign up",
    "subscribe", "learn more", "view pricing", "get pricing",
    "whatsapp", "chat now", "send message",
}

_CTA_BUTTON_PATTERNS = re.compile(
    r"(get\s*(a\s*)?(free\s*)?(quote|estimate)|contact|book|schedule|appointment|"
    r"call\s*(us|now)|buy|order|shop|start|get\s*started|try|sign\s*up|"
    r"subscribe|whatsapp|chat|enquire|enquiry|request|apply)",
    re.IGNORECASE,
)

_LIVE_CHAT_PATTERNS = re.compile(
    r"(intercom|drift\.com|crisp\.chat|tawk\.to|livechat|freshchat|"
    r"zendesk|hubspot|tidio|olark|smartsupp|jivochat|chatra|"
    r"__lc|zopim|$crisp|Intercom\(|LC_API|FreshworksWidget)",
    re.IGNORECASE,
)

_COOKIE_PATTERNS = re.compile(
    r"(cookie\s*(consent|notice|banner|policy|accept)|gdpr\s*consent|"
    r"cookiebot|cookieyes|cookieconsent|onetrust|usercentrics|"
    r"accept\s*(all\s*)?cookie|we\s*use\s*cookies|this\s*site\s*uses\s*cookies)",
    re.IGNORECASE,
)


def audit_cta(soup) -> dict:
    """Detect a clear call-to-action button or link."""
    buttons = soup.find_all(["button", "a"])
    found_cta = None

    for el in buttons:
        text = el.get_text(strip=True).lower()
        classes = " ".join(el.get("class", [])).lower()
        href = el.get("href", "").lower()

        # Check text matches CTA keywords
        if any(kw in text for kw in _CTA_KEYWORDS):
            found_cta = el.get_text(strip=True)[:60]
            break

        # Check class names (btn-primary, cta-button, etc.)
        if re.search(r"\b(cta|btn.primary|btn.cta|action|hero.btn)\b", classes):
            found_cta = el.get_text(strip=True)[:60] or classes[:40]
            break

        # Check button regex on text
        if el.name == "button" and _CTA_BUTTON_PATTERNS.search(text):
            found_cta = el.get_text(strip=True)[:60]
            break

    if found_cta:
        return result_pass(
            f"Clear CTA found: \"{found_cta}\".",
            fix="",
        )

    return result_fail(
        "No clear call-to-action (CTA) button detected on the page.",
        fix=(
            "Add a prominent CTA button above the fold — e.g. 'Get a Free Quote', "
            "'Contact Us', or 'Book Now'. Use a contrasting button colour. "
            "Sites with a clear CTA convert 200% more visitors than those without one."
        ),
    )


def audit_cta_above_fold(soup, html: str = "") -> dict:
    """Check if a CTA is visible without scrolling (first ~3000 chars of body HTML)."""
    body = soup.find("body")
    if not body:
        return result_warn("Could not locate body element for above-fold analysis.", fix="")

    body_html = str(body)[:4000]  # approx above-fold on a 1366px screen

    if _CTA_BUTTON_PATTERNS.search(body_html):
        return result_pass(
            "A call-to-action appears early in the page (likely above the fold).",
            fix="",
        )

    return result_warn(
        "No CTA detected in the first section of the page (above the fold).",
        fix=(
            "Move your primary CTA button into the hero / banner section visible "
            "without scrolling. Studies show above-fold CTAs get 47% more clicks than "
            "below-fold equivalents."
        ),
    )


def audit_hero_headline(soup) -> dict:
    """Detect a clear value-proposition heading in the hero/above-fold area."""
    # Check H1 first (strongest signal)
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if len(text) > 10:
            return result_pass(
                f"Hero headline found: \"{text[:80]}\".",
                fix="",
            )

    # Check early H2 (some sites use h2 in hero)
    body = soup.find("body")
    if body:
        early_html = str(body)[:5000]
        h2_match = re.search(r"<h2[^>]*>([^<]{10,150})</h2>", early_html, re.IGNORECASE)
        if h2_match:
            return result_warn(
                f"No H1 found — early H2 used as headline: \"{h2_match.group(1)[:80]}\".",
                fix="Replace the hero H2 with an H1 tag. The H1 is the single most "
                    "important on-page SEO element. Each page should have exactly one H1.",
            )

    return result_fail(
        "No clear value-proposition headline (H1/H2) detected in the hero area.",
        fix=(
            "Add an H1 heading at the top of the page that clearly describes what "
            "the business offers. Example: 'Professional Car Window Tinting in Sydney'. "
            "Keep it under 70 characters, include your primary keyword."
        ),
    )


def audit_font_size(soup, html: str = "") -> dict:
    """
    Detect body text font-size from inline styles AND <style> blocks. Flags sizes < 14px.

    SEO Impact: Low-Medium — readability affects bounce rate and Core Web Vitals signals.
    """
    tiny_count = 0
    found_sizes = []

    # ── Scan inline styles ────────────────────────────────────────────────────
    for el in soup.find_all(["p", "span", "div", "li", "body"], limit=30):
        style = el.get("style", "")
        m = re.search(r"font-size\s*:\s*([\d.]+)(px|rem|em|pt)", style, re.IGNORECASE)
        if m:
            value = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "rem":
                value *= 16
            elif unit == "em":
                value *= 14
            elif unit == "pt":
                value *= 1.333
            found_sizes.append(round(value))
            if value < 14:
                tiny_count += 1

    # B10: Also scan <style> blocks for body/p/div font-size rules
    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text()
        for m in re.finditer(
            r"(?:body|p|div|li|span)[^{]*\{[^}]*font-size\s*:\s*([\d.]+)(px|rem|em|pt)",
            css_text, re.IGNORECASE | re.DOTALL,
        ):
            value = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "rem":
                value *= 16
            elif unit == "em":
                value *= 14
            elif unit == "pt":
                value *= 1.333
            found_sizes.append(round(value))
            if value < 14:
                tiny_count += 1

    if not found_sizes:
        return result_warn(
            "Font size not detected from inline styles or <style> blocks. "
            "Ensure body text uses at least 14-16px for readability.",
            fix=(
                "Set your base font size to 16px in CSS: body { font-size: 16px; }. "
                "Small text (< 14px) fails WCAG readability guidelines and increases bounce rate."
            ),
        )

    min_size = min(found_sizes)
    if tiny_count > 0:
        return result_fail(
            f"Small font size detected: {min_size}px (minimum recommended is 14px).",
            fix=(
                f"Increase body/paragraph font-size to at least 14px (16px preferred). "
                f"Current smallest detected: {min_size}px. "
                "Small text reduces readability, especially on mobile, and increases bounce rate."
            ),
        )

    return result_pass(
        f"Font sizes appear readable (smallest detected: {min_size}px).",
        fix="",
    )


def audit_contrast(soup) -> dict:
    """
    Check for obvious low-contrast text via inline styles AND <style> tag blocks.

    SEO Impact: Low — poor contrast increases bounce rate and fails accessibility audits.
    """
    LIGHT_COLORS = {
        "white", "#fff", "#ffffff", "rgb(255,255,255)",
        "#f0f0f0", "#fafafa", "#f5f5f5", "#eeeeee",
        "#e0e0e0", "lightyellow", "lightgray", "lightgrey",
        "lightyellow",
    }
    DARK_COLORS = {
        "#000", "#000000", "#111", "#111111", "#222", "#333",
        "#1a1a1a", "#2d2d2d", "black", "rgb(0,0,0)",
    }

    issues = []

    # ── Scan inline styles ────────────────────────────────────────────────────
    for el in soup.find_all(style=True, limit=50):
        style = el.get("style", "").lower().replace(" ", "")
        color_m = re.search(r"(?<![background-])color:(#[0-9a-f]{3,6}|[a-z]+)", style)
        bg_m    = re.search(r"background(?:-color)?:(#[0-9a-f]{3,6}|[a-z]+)", style)

        if color_m and bg_m:
            fg = color_m.group(1)
            bg = bg_m.group(1)
            if fg in LIGHT_COLORS and bg in LIGHT_COLORS:
                issues.append(f"light text ({fg}) on light background ({bg})")
            if fg in DARK_COLORS and bg in DARK_COLORS:
                issues.append(f"dark text ({fg}) on dark background ({bg})")

    # B11: Also scan <style> blocks for color+background-color rules
    if not issues:
        for style_tag in soup.find_all("style"):
            css_text = style_tag.get_text().lower().replace(" ", "")
            # Find color: and background-color: pairs in the same rule block
            for rule_m in re.finditer(r"\{([^}]+)\}", css_text):
                rule = rule_m.group(1)
                color_m = re.search(r"(?<![background-])color:(#[0-9a-f]{3,6}|[a-z]+)", rule)
                bg_m    = re.search(r"background(?:-color)?:(#[0-9a-f]{3,6}|[a-z]+)", rule)
                if color_m and bg_m:
                    fg = color_m.group(1)
                    bg = bg_m.group(1)
                    if fg in LIGHT_COLORS and bg in LIGHT_COLORS:
                        issues.append(f"CSS: light text ({fg}) on light bg ({bg})")
                    if fg in DARK_COLORS and bg in DARK_COLORS:
                        issues.append(f"CSS: dark text ({fg}) on dark bg ({bg})")
            if issues:
                break

    if issues:
        return result_fail(
            f"Potential contrast issue detected: {issues[0]}.",
            fix=(
                "Ensure text-to-background contrast ratio is at least 4.5:1 (WCAG AA). "
                "Use Google's Colour Contrast Checker or WebAIM Contrast Checker to verify. "
                "Low contrast fails accessibility standards and reduces readability for all users."
            ),
        )

    return result_pass(
        "No obvious contrast issues detected from inline styles or <style> blocks.",
        fix="",
        detail="Note: Full contrast analysis requires browser rendering. "
               "Use Chrome DevTools Accessibility Audit for complete verification.",
    )


def audit_nav_links(soup) -> dict:
    """Check that a navigation menu exists with a reasonable number of links."""
    nav = soup.find("nav")
    if nav:
        links = nav.find_all("a", href=True)
        count = len(links)
        if count >= 3:
            return result_pass(
                f"Navigation menu found with {count} links.",
                fix="", value=count, unit="links",
            )
        if count > 0:
            return result_warn(
                f"Navigation exists but has only {count} link(s) — consider expanding it.",
                fix=(
                    "Add at least 3-5 main navigation links (Home, Services, About, Contact). "
                    "Clear navigation reduces bounce rate and helps search engines understand site structure."
                ), value=count, unit="links",
            )

    # Fallback: check for header links
    header = soup.find("header")
    if header:
        links = header.find_all("a", href=True)
        if len(links) >= 3:
            return result_warn(
                f"No <nav> element found, but {len(links)} header links detected. "
                "Wrap them in a <nav> tag for accessibility and SEO.",
                fix="Add a <nav> element wrapping your main menu links. "
                    "This is required for WCAG 2.1 accessibility compliance.", value=len(links), unit="links",
            )

    return result_fail(
        "No navigation menu detected. Missing <nav> element and header links.",
        fix=(
            "Add a clear navigation menu with a <nav> element. Include links to your "
            "main pages: Home, Services, About Us, Contact. "
            "Missing navigation hurts both UX and internal link equity distribution."
        ), value=0, unit="links",
    )


def audit_cookie_notice(soup, html: str = "") -> dict:
    """Detect a GDPR/cookie consent banner."""
    full_html = str(soup) + (html or "")

    if _COOKIE_PATTERNS.search(full_html):
        return result_pass(
            "Cookie consent notice / GDPR banner detected.",
            fix="",
        )

    consent_ids = ["cookie-consent", "cookiebanner", "cookie-banner",
                   "gdpr-banner", "cookie-notice", "consent-banner",
                   "cookielaw", "CybotCookiebotDialog", "onetrust-consent"]
    for cid in consent_ids:
        if soup.find(id=cid) or soup.find(class_=cid):
            return result_pass(
                f"Cookie consent element detected (id/class: {cid}).",
                fix="",
            )

    return result_warn(
        "No cookie consent notice detected.",
        fix=(
            "If your site serves EU, UK, or California visitors, a cookie consent banner "
            "is legally required (GDPR / CCPA). Free options: CookieYes, Cookiebot (free tier). "
            "Missing consent banners can result in fines up to €20M or 4% of global revenue."
        ),
    )


def audit_live_chat(soup, html: str = "") -> dict:
    """Detect live chat widget integrations."""
    full_html = str(soup) + (html or "")

    match = _LIVE_CHAT_PATTERNS.search(full_html)
    if match:
        tool = match.group(0)[:30]
        return result_pass(
            f"Live chat widget detected ({tool}).",
            fix="",
        )

    return result_warn(
        "No live chat widget detected.",
        fix=(
            "Consider adding a live chat widget — businesses with live chat see "
            "40-50% higher conversion rates. Free options: Tawk.to (completely free), "
            "Crisp (free tier). Paid: Intercom, Drift, Freshchat. "
            "Alternatively, a floating WhatsApp button achieves a similar effect."
        ),
    )


# ── GROUP B NEW FUNCTIONS (B12–B13) ──────────────────────────────────────────

_PHONE_PATTERNS = re.compile(
    r"(\+?\d[\d\s\-\(\)\.]{7,}\d"          # international/local number patterns
    r"|tel:\s*[\d\+\-\(\)\s]+)",            # tel: link
    re.IGNORECASE,
)

_ADDRESS_KEYWORDS = re.compile(
    r"\b(street|st\.|avenue|ave\.|road|rd\.|lane|ln\.|drive|dr\.|"
    r"boulevard|blvd\.|suite|floor|zip|postal|p\.?o\.?\s*box|"
    r"address|location|directions)\b",
    re.IGNORECASE,
)


def audit_phone_number(soup) -> dict:
    """
    Detect a visible phone number or tel: link on the page.

    SEO Impact: Medium — phone numbers improve local SEO trust signals and conversions.
    Source: https://developers.google.com/search/docs/appearance/structured-data/local-business
    """
    # Check for tel: href links
    tel_links = soup.find_all("a", href=re.compile(r"^tel:", re.I))
    if tel_links:
        number = tel_links[0].get("href", "").replace("tel:", "").strip()
        return result_pass(
            f"Phone number found as clickable tel: link: {number}.",
            detail="Clickable phone links improve mobile UX and local SEO trust.",
        )

    # Check footer and header text for phone patterns
    for region in [soup.find("footer"), soup.find("header"), soup.find("body")]:
        if region:
            text = region.get_text()
            m = _PHONE_PATTERNS.search(text)
            if m:
                return result_pass(
                    f"Phone number detected in page text: {m.group(0).strip()[:40]}.",
                    detail="Consider wrapping in a <a href='tel:...'>number</a> link for mobile users.",
                )

    return result_warn(
        "No phone number detected on the page.",
        fix=(
            "Add a visible, clickable phone number. Use: <a href='tel:+1234567890'>+1 234 567 890</a>. "
            "Phone numbers are a key local SEO trust signal and improve conversion rates by 20–40%. "
            "Place it prominently in the header and footer."
        ),
    )


def audit_address_presence(soup) -> dict:
    """
    Detect a physical address in footer or contact area.

    SEO Impact: Medium — physical address improves local SEO authority and trust.
    Source: https://developers.google.com/search/docs/appearance/structured-data/local-business
    """
    # Check for schema.org address in JSON-LD
    import json as _json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("address"):
                    addr = item["address"]
                    if isinstance(addr, dict):
                        street = addr.get("streetAddress", "")
                        city   = addr.get("addressLocality", "")
                        if street or city:
                            return result_pass(
                                f"Physical address found in JSON-LD schema: {street}, {city}.",
                                detail="Structured address data improves Local Business rich results.",
                            )
                    elif isinstance(addr, str) and len(addr) > 5:
                        return result_pass(
                            f"Physical address found in JSON-LD schema.",
                            detail=addr[:80],
                        )
        except Exception:
            continue

    # Check footer for address keywords
    footer = soup.find("footer")
    if footer:
        footer_text = footer.get_text()
        if _ADDRESS_KEYWORDS.search(footer_text):
            return result_pass(
                "Physical address keywords detected in footer.",
                detail="Consider also adding LocalBusiness JSON-LD schema with your address.",
            )
        # Check for address-like patterns: number + word (e.g., "123 Main St")
        addr_m = re.search(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(?:St|Ave|Rd|Lane|Dr|Blvd|Street|Road|Drive)\b", footer_text)
        if addr_m:
            return result_pass(
                f"Street address detected in footer: {addr_m.group(0)}.",
                detail="Wrap in LocalBusiness JSON-LD schema for maximum local SEO benefit.",
            )

    return result_warn(
        "No physical address detected on the page.",
        fix=(
            "Add your physical address to the footer and wrap it in LocalBusiness JSON-LD schema. "
            "Format: <script type='application/ld+json'>{'@type':'LocalBusiness','address':{'streetAddress':'...'}}</script>. "
            "Physical address presence is a top local SEO ranking factor for Google Maps and local packs."
        ),
    )
