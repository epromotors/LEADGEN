# auditor/local_seo.py — Local SEO Checks
# LeadGen OS v5.0.0 | Group E new module

import json
import re
import requests
from auditor.core import result_pass, result_warn, result_fail
from config import TIMEOUT

_HOURS_PATTERNS = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|wed|thu|fri|sat|sun|open|hours|am|pm|"
    r"\d{1,2}:\d{2}\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)

_PHONE_RE = re.compile(
    r"(\+?\d[\d\s\-\(\)\.]{7,}\d|tel:\s*[\d\+\-\(\)\s]+)",
    re.IGNORECASE,
)


def audit_nap_consistency(soup) -> dict:
    """
    Detect Name, Address, Phone (NAP) presence in page text.

    SEO Impact: High for local businesses.
    Source: https://developers.google.com/search/docs/appearance/structured-data/local-business
    """
    body = soup.find("body")
    if not body:
        return result_warn("Cannot check NAP — page body not found.", "Ensure valid HTML.")

    text = body.get_text()
    has_phone   = bool(_PHONE_RE.search(text))
    has_address = bool(re.search(
        r"\b(street|st\.|avenue|ave\.|road|rd\.|lane|drive|blvd|address|\d{3,5}\s+[A-Z])",
        text, re.IGNORECASE,
    ))

    # Check schema for name
    has_name_schema = False
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    has_name_schema = True
                    break
        except Exception:
            continue

    missing = []
    if not has_phone:   missing.append("Phone")
    if not has_address: missing.append("Address")

    if missing:
        return result_warn(
            f"Incomplete NAP data — missing: {', '.join(missing)}.",
            "Add your full Name, Address, and Phone number to the page (ideally in the footer). "
            "Consistent NAP across your website and directory listings is the #1 local ranking factor. "
            "Also add LocalBusiness JSON-LD schema with your NAP details.",
            f"Missing: {', '.join(missing)}",
        )

    return result_pass(
        "NAP data detected — phone and address found on the page.",
        detail="Ensure NAP matches your Google Business Profile and directory listings exactly.",
    )


def audit_local_business_schema(soup) -> dict:
    """
    Check for LocalBusiness or Organization JSON-LD with address and phone.

    SEO Impact: High
    Source: https://schema.org/LocalBusiness
    """
    _LOCAL_TYPES = {
        "localbusiness", "restaurant", "store", "medicalclinic", "dentist",
        "hotel", "gym", "spaorsalonorbarbershop", "automotivebusiness",
        "organization", "corporation", "professionalservice",
    }

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type", "")).lower()
                if item_type in _LOCAL_TYPES:
                    has_address = bool(item.get("address"))
                    has_phone   = bool(item.get("telephone"))
                    has_url     = bool(item.get("url"))
                    missing_fields = []
                    if not has_address: missing_fields.append("address")
                    if not has_phone:   missing_fields.append("telephone")
                    if missing_fields:
                        return result_warn(
                            f"LocalBusiness schema found ({item.get('@type')}) but missing: {', '.join(missing_fields)}.",
                            f"Add {', '.join(missing_fields)} to your LocalBusiness schema. "
                            "Complete schema with address+phone improves local pack visibility.",
                            f"@type: {item.get('@type')}",
                        )
                    return result_pass(
                        f"LocalBusiness schema found with address and phone: @type={item.get('@type')}.",
                        detail="Validate at: https://search.google.com/test/rich-results",
                    )
        except Exception:
            continue

    return result_fail(
        "No LocalBusiness or Organization JSON-LD schema found.",
        "Add LocalBusiness structured data with name, address, telephone, and url. "
        "This is essential for appearing in Google's local pack and maps. "
        "Use: https://technicalseo.com/tools/schema-markup-generator/",
    )


def audit_google_maps_embed(soup) -> dict:
    """
    Detect a Google Maps iframe embed on the page.

    SEO Impact: Medium — Maps embed signals physical location to Google.
    Source: https://support.google.com/maps/answer/3544418
    """
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if "google.com/maps" in src or "maps.google" in src:
            return result_pass(
                "Google Maps embed detected.",
                detail=f"iframe src: {src[:80]}",
            )

    # Also check for Google Maps API script
    full_html = str(soup)
    if "maps.googleapis.com" in full_html or "google.com/maps/embed" in full_html:
        return result_pass(
            "Google Maps API or embed detected in page source.",
            detail="Maps embed helps reinforce physical location for local SEO.",
        )

    return result_warn(
        "No Google Maps embed detected.",
        fix=(
            "Embed a Google Maps iframe on your Contact page. "
            "Go to Google Maps → Share → Embed a map. "
            "A maps embed signals your physical location to Google and builds local trust."
        ),
    )


def audit_city_in_title(soup) -> dict:
    """
    Check if a city, region, or location keyword appears in the title tag.

    SEO Impact: High for local businesses — location in title boosts local search rankings.
    Source: https://developers.google.com/search/docs/appearance/title-link
    """
    title_tag = soup.find("title")
    if not title_tag or not title_tag.get_text(strip=True):
        return result_warn(
            "City-in-title check skipped — title tag missing.",
            "Add a title tag first, then include your target city/region.",
        )

    title_text = title_tag.get_text(strip=True)

    # Look for any word that could be a proper noun (city name) — starts with capital
    # and is not a common English word
    _COMMON_WORDS = {
        "the", "and", "for", "with", "from", "our", "your", "best",
        "top", "free", "fast", "cheap", "professional", "services",
        "solutions", "company", "ltd", "inc", "llc",
    }
    proper_nouns = [
        w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", title_text)
        if w.lower() not in _COMMON_WORDS
    ]

    if proper_nouns:
        return result_pass(
            f"Location/proper noun found in title: {', '.join(proper_nouns[:3])}.",
            detail=f"Title: '{title_text[:80]}'",
        )

    # Check JSON-LD for area served / address locality
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if isinstance(item, dict):
                    area = item.get("areaServed") or item.get("addressLocality")
                    if area:
                        city = str(area)[:30]
                        if city.lower() not in title_text.lower():
                            return result_warn(
                                f"City '{city}' found in schema but NOT in title tag.",
                                f"Add '{city}' to your title tag for local ranking boost. "
                                "Example: 'SEO Services {city} | TEB Solutions'.",
                                f"Title: '{title_text[:60]}'",
                            )
                        return result_pass(
                            f"City '{city}' appears in both schema and title.",
                            detail=f"Title: '{title_text[:80]}'",
                        )
        except Exception:
            continue

    return result_warn(
        "No city or location keyword detected in the page title.",
        fix=(
            "Add your target city/region to the title tag. "
            "Example: 'Window Tinting Sydney | TEB Solutions'. "
            "Location in title is one of the top local SEO ranking signals."
        ),
        detail=f"Title: '{title_text[:80]}'",
    )


def audit_business_hours(soup) -> dict:
    """
    Detect opening hours in JSON-LD schema or visible page text.

    SEO Impact: Medium — hours in schema improve local pack display in Google.
    Source: https://schema.org/openingHoursSpecification
    """
    # Check JSON-LD first
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("openingHours") or item.get("openingHoursSpecification"):
                    hours = item.get("openingHours") or "defined in openingHoursSpecification"
                    return result_pass(
                        "Business hours found in JSON-LD schema.",
                        detail=f"openingHours: {str(hours)[:80]}",
                    )
        except Exception:
            continue

    # Check visible text
    body = soup.find("body")
    if body:
        body_text = body.get_text()
        if _HOURS_PATTERNS.search(body_text):
            # Look for a more specific hours-like pattern
            hours_pattern = re.search(
                r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*[\s\-:,to]+\d{1,2}(?::\d{2})?\s*(?:am|pm)",
                body_text, re.IGNORECASE,
            )
            if hours_pattern:
                return result_pass(
                    f"Business hours found in page text: {hours_pattern.group(0)[:60]}.",
                    detail="Consider also adding hours to LocalBusiness JSON-LD schema for rich results.",
                )

    return result_warn(
        "No business hours detected on the page.",
        fix=(
            "Add your opening hours to the page and to your LocalBusiness JSON-LD schema. "
            "Schema format: 'openingHours': ['Mo-Fr 09:00-18:00', 'Sa 10:00-16:00']. "
            "Business hours in schema can appear directly in Google Search results."
        ),
    )
