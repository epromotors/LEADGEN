# auditor/trust.py — Privacy policy, terms, GDPR compliance detection

from auditor.core import result_pass, result_warn, result_fail
from config import TRUST_KEYWORDS


def audit_trust_pages(soup, page_url: str) -> dict:
    """Detect privacy policy, terms of service, cookie notice links."""
    all_links = soup.find_all("a", href=True)
    
    found_pages = {}
    
    for link in all_links:
        text = link.get_text(strip=True).lower()
        href = link.get("href", "").lower()
        combined = text + " " + href
        
        for kw in TRUST_KEYWORDS:
            if kw in combined and kw not in found_pages:
                found_pages[kw] = link.get_text(strip=True)[:50]
    
    has_privacy = any(k in found_pages for k in ["privacy", "gdpr"])
    has_terms = any(k in found_pages for k in ["terms", "legal"])
    has_cookie = any(k in found_pages for k in ["cookie"])
    
    if has_privacy and has_terms:
        found_list = list(found_pages.keys())
        return result_pass(
            f"Trust pages found: {', '.join(found_list[:5])}.",
            detail="These pages are required to run Google Ads, Meta Ads, and comply with GDPR/CCPA.",
        )
    
    missing = []
    fixes = []
    
    if not has_privacy:
        missing.append("Privacy Policy")
        fixes.append(
            "Create a Privacy Policy page. You can generate one free at:\n"
            "  - termly.io (recommended)\n"
            "  - privacypolicygenerator.info\n"
            "Link it in your footer. REQUIRED for Google Ads approval."
        )
    if not has_terms:
        missing.append("Terms of Service")
        fixes.append(
            "Create a Terms of Service / Terms & Conditions page.\n"
            "Generator: termsofservicegenerator.net — Free.\n"
            "Link in footer. Required for Meta (Facebook/Instagram) Ads."
        )
    if not has_cookie and "gdpr" not in found_pages:
        missing.append("Cookie Policy / Notice")
        fixes.append(
            "Add a cookie consent banner if you serve EU/UK visitors.\n"
            "Free option: cookiebot.com (free tier) or CookieYes."
        )
    
    if not has_privacy and not has_terms:
        return result_fail(
            "Privacy Policy and Terms of Service pages are MISSING.",
            "\n\n".join(fixes),
        )
    
    return result_warn(
        f"Some trust/compliance pages missing: {', '.join(missing)}",
        "\n\n".join(fixes),
        f"Found: {', '.join(found_pages.keys()) or 'none'}",
    )
