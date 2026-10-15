# auditor/schema_utils.py — Shared JSON-LD and structured data utilities
# LeadGen OS v5.0.0

from __future__ import annotations

import json
import logging
from typing import Any
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Comprehensive Schema.org types under LocalBusiness (and Organization fallbacks)
LOCAL_BUSINESS_TYPES = {
    # Root local business
    "localbusiness",
    # Automotive
    "autorepair", "autobodyshop", "autodealer", "automotivebusiness",
    "autopartsstore", "autorental", "autowash", "gasstation",
    "motorcycledealer", "motorcyclerepair",
    # Food & Dining
    "restaurant", "foodestablishment", "bakery", "barorpub", "brewery",
    "cafeorcoffeeshop", "distillery", "fastfoodrestaurant", "icecreamshop",
    "winery",
    # Store / Retail
    "store", "bikestore", "bookstore", "clothingstore", "conveniencestore",
    "departmentstore", "electronicsstore", "florist", "furniturestore",
    "gardenstore", "grocerystore", "hardwarestore", "hobbyshop",
    "homegoodsstore", "jewelrystore", "liquorstore", "mensclothingstore",
    "mobilephonestore", "movierentalstore", "musicstore", "officeequipmentstore",
    "outletstore", "pawnshop", "petstore", "shoestore", "sportinggoodsstore",
    "tireshop", "toystore", "wholesale",
    # Health & Beauty
    "healthandbeautybusiness", "beautysalon", "dayspa", "hairsalon",
    "healthclub", "nailsalon", "spaorsalonorbarbershop", "tattooparlor",
    # Medical
    "medicalbusiness", "communityhealth", "dentist", "dermatology",
    "dietnutrition", "emergencyservice", "geriatric", "gynecologic",
    "medicalclinic", "midwifery", "nursing", "obstetric", "oncologic",
    "optometric", "otolaryngologic", "pediatric", "pharmacy",
    "physician", "physiotherapy", "plasticpathology", "podiatric",
    "primarycare", "psychiatric", "publichealth",
    # Home & Construction
    "homeandconstructionbusiness", "electrician", "generalcontractor",
    "hvacbusiness", "housepainter", "locksmith", "movingcompany",
    "plumber", "roofingcontractor",
    # Professional & Legal & Financial
    "professionalservice", "accountingservice", "legalservice", "attorney",
    "notary", "financialservice", "bankorcreditunion", "insuranceagency",
    "realestateagent",
    # Lodging & Travel
    "lodgingbusiness", "bedandbreakfast", "campground", "hostel",
    "hotel", "motel", "resort", "travelagency",
    # Sports & Entertainment
    "sportsactivitylocation", "bowlingalley", "exercisefitness",
    "golfcourse", "healthclub", "publicswimmingpool", "skiresort",
    "sportsclub", "stadiumorarena", "tenniscourt", "entertainmentbusiness",
    "amusementpark", "artgallery", "casino", "comedyclub", "movietheater",
    "nightclub",
    # Other Services
    "drycleaningorlaundry", "childcare", "animalshelter", "postoffice",
    "radiostation", "televisionstation", "touristinformationcenter",
    # Organization fallbacks
    "organization", "corporation",
}


def normalize_schema_type(t: Any) -> str:
    """Normalize a schema type string by stripping Schema.org URI prefix and trimming."""
    if not isinstance(t, str):
        return ""
    val = t.strip()
    for prefix in ("https://schema.org/", "http://schema.org/", "schema:"):
        if val.startswith(prefix):
            val = val[len(prefix):]
    return val


def get_item_types(item: dict) -> list[str]:
    """
    Extract all normalized schema type names from a JSON-LD item.
    Handles string, list of strings, or URI-prefixed types.
    """
    if not isinstance(item, dict):
        return []
    raw_type = item.get("@type")
    if isinstance(raw_type, str):
        norm = normalize_schema_type(raw_type)
        return [norm] if norm else []
    elif isinstance(raw_type, list):
        types = []
        for entry in raw_type:
            if isinstance(entry, str):
                norm = normalize_schema_type(entry)
                if norm and norm not in types:
                    types.append(norm)
        return types
    return []


def _flatten_json_ld(data: Any) -> list[dict]:
    """Recursively flatten JSON-LD objects, arrays, and nested @graph structures."""
    items: list[dict] = []
    if isinstance(data, list):
        for sub in data:
            items.extend(_flatten_json_ld(sub))
    elif isinstance(data, dict):
        if "@graph" in data:
            items.extend(_flatten_json_ld(data["@graph"]))
        # Keep the dict itself if it has a @type or looks like an entity
        if "@type" in data:
            items.append(data)
        elif "@graph" not in data:
            items.append(data)
    return items


def extract_json_ld_items(soup: BeautifulSoup) -> tuple[list[dict], list[str]]:
    """
    Extract and flatten all JSON-LD items across all script tags in the page.
    Returns (valid_items, syntax_errors).
    """
    scripts = soup.find_all("script", type="application/ld+json")
    valid_items: list[dict] = []
    syntax_errors: list[str] = []

    for idx, script in enumerate(scripts, start=1):
        content = (script.string or script.get_text() or "").strip()
        if not content:
            continue
        try:
            data = json.loads(content)
            flattened = _flatten_json_ld(data)
            valid_items.extend(flattened)
        except Exception as exc:
            syntax_errors.append(f"Script tag #{idx}: {type(exc).__name__}: {exc}")

    return valid_items, syntax_errors


def is_local_business_item(item: dict) -> tuple[bool, str | None]:
    """
    Check if a JSON-LD item represents a LocalBusiness, AutomotiveBusiness, AutoRepair,
    Organization, or any supported subtype.
    Returns (is_match, matched_type_name).
    """
    types = get_item_types(item)
    for t in types:
        if t.lower() in LOCAL_BUSINESS_TYPES:
            return True, t
    return False, None


def check_local_business_fields(item: dict) -> dict[str, Any]:
    """
    Inspect a LocalBusiness JSON-LD item for key required and recommended fields.
    """
    has_address = False
    addr_val = item.get("address")
    if isinstance(addr_val, dict):
        has_address = bool(
            addr_val.get("streetAddress")
            or addr_val.get("addressLocality")
            or addr_val.get("postalCode")
            or addr_val.get("addressCountry")
        )
    elif isinstance(addr_val, str) and len(addr_val.strip()) > 3:
        has_address = True

    telephone = item.get("telephone") or item.get("phone")
    has_phone = bool(telephone and str(telephone).strip())

    name = item.get("name") or item.get("legalName")
    has_name = bool(name and str(name).strip())

    url = item.get("url")
    has_url = bool(url and str(url).strip())

    return {
        "has_address": has_address,
        "has_phone": has_phone,
        "has_name": has_name,
        "has_url": has_url,
        "name": str(name).strip() if has_name else None,
        "telephone": str(telephone).strip() if has_phone else None,
        "address": addr_val if has_address else None,
    }
