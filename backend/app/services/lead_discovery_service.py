"""
backend/app/services/lead_discovery_service.py

Integrated Lead Discovery Service with:
1. Reused & hardened extraction and classification functions from uploaded scraper:
   - clean_email, extract_email, clean_website
   - audit_website_is_old_or_dead (parked signals, thin content, old HTML/doctypes,
     missing viewport, deprecated tags, table layouts, outdated tech stack, old copyright)
2. Common provider adapter system with explicit states:
   available, rate_limited, quota_exhausted, authentication_error,
   temporarily_unavailable, disabled, no_results
3. Multi-provider search discovery (Serper, SerpApi, HasData, Outscraper)
4. Email enrichment (Hunter, Serper snippet, Permitted DuckDuckGo search fallback)
5. Secure HTTP inspection with SSRF prevention (validate_url) and TLS verification
6. Text-file upload processing (.txt) for keywords and locations with UTF-8 BOM,
   comments, blank lines, and case-insensitive deduplication
7. Search combinations budget calculator & safety limits
8. Persistent job state with checkpoint/resume, pause, and cancellation
9. Deduplication, data provenance, and lead schema CSV export
"""

import asyncio
import csv
import enum
import io
import json
import logging
import os
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

import aiohttp
from app.config import settings
from app.models import EmailAssociationStatus, WebsiteAssociationStatus
from app.services.provider_key_manager import get_key_manager, ProviderKeyManager
from app.utils.csv_parser import clean_business_name as app_clean_business_name
from app.utils.email_constants import (
    PUBLIC_EMAIL_PROVIDERS,
    is_public_email_provider,
    is_custom_email_domain,
    normalize_domain,
    infer_website_candidate_from_email,
    is_third_party_directory_or_aggregator,
    is_directory_or_platform_email,
)

logger = logging.getLogger(__name__)

# ─── Constants & Regex ────────────────────────────────────────────────────────

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

INVALID_EMAIL_SUBSTRINGS = [
    "example", "test", "demo", "sample", "noreply", "no-reply", "sentry",
    "privacy", "wixpress", "squarespace", "wordpress", "schema", "w3.org",
    "your@email", "user@", "email@domain",
]

INVALID_TLDS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "pdf",
    "zip", "js", "css", "php", "html", "htm", "xml", "txt", "json",
    "mp4", "mp3", "woff", "woff2", "ttf", "eot",
}

JUNK_DOMAINS = {
    "google.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "youtube.com", "yelp.com", "yellowpages.com",
    "yell.com", "tripadvisor.com", "wix.com", "squarespace.com", "shopify.com",
    "godaddy.com", "namecheap.com", "cloudflare.com", "sentry.io",
    "indiamart.com", "justdial.com", "tradeindia.com",
}

PARKED_SIGNALS = [
    "domain for sale", "buy this domain", "this domain is for sale",
    "domain is parked", "parked free", "sedoparking", "hugedomains",
    "godaddy.com/domain", "namecheap.com", "domain may be for sale",
    "account has been suspended", "site is currently unavailable",
    "under construction", "coming soon", "website coming soon",
    "page not found", "this store is unavailable", "defaultwebpage.cgi",
]

# ─── Free Email Providers, Agency Patterns & Country ccTLD Mappings ──────────

FREE_EMAIL_PROVIDERS: Set[str] = set(PUBLIC_EMAIL_PROVIDERS)

AGENCY_DESIGNER_PATTERNS: List[str] = [
    r"(?:designed|developed|maintained|hosted|created|powered|built|managed)\s+(?:with\s+.*?\s+)?by",
    r"web\s*design(?:er|ing)?\s*:",
    r"(?:website|site|theme|design|branding|product)\s+by",
    r"(?:digital\s+)?agency\s*:",
    r"crafted\s+(?:with\s+.*?\s+)?by",
    r"credits?\s*:",
    r"made\s+(?:with\s+.*?\s+)?by",
]

COUNTRY_CCTLD_MAP: Dict[str, List[str]] = {
    "india": [".in", ".co.in"],
    "uk": [".uk", ".co.uk", ".org.uk"],
    "united kingdom": [".uk", ".co.uk"],
    "usa": [".us"],
    "united states": [".us"],
    "australia": [".au", ".com.au"],
    "canada": [".ca"],
    "germany": [".de"],
    "vietnam": [".vn", ".com.vn"],
    "uae": [".ae"],
    "singapore": [".sg", ".com.sg"],
}

# ─── Presets ──────────────────────────────────────────────────────────────────

DEFAULT_PRESET_KEYWORDS: List[str] = [
    "web design agency", "dental clinic", "interior design company",
    "roofing contractor", "plumbing company", "hvac contractor", "electrician",
    "landscaping company", "car repair garage", "auto workshop",
    "pest control company", "cleaning company", "moving company", "locksmith",
    "painting contractor", "flooring contractor", "handyman service",
    "accounting firm", "personal injury lawyer", "chiropractor",
]

DEFAULT_PRESET_LOCATIONS: List[str] = [
    "Austin, Texas, USA", "Dallas, Texas, USA", "Houston, Texas, USA",
    "London, UK", "Manchester, UK", "Birmingham, UK",
    "Delhi, India", "Dehradun, Uttarakhand, India", "Roorkee, Uttarakhand, India", "Haridwar, Uttarakhand, India",
    "Sydney, Australia", "Melbourne, Australia", "Toronto, Canada",
]


# ─── Provider States ──────────────────────────────────────────────────────────

class ProviderStatus(str, enum.Enum):
    AVAILABLE = "available"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTHENTICATION_ERROR = "authentication_error"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DISABLED = "disabled"
    NO_RESULTS = "no_results"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ─── Reused & Hardened Text, Email, and URL Cleaning ──────────────────────────

def clean_email(raw: Any) -> Optional[str]:
    """Clean and validate an extracted email candidate."""
    if not raw:
        return None
    e = re.sub(r"[>\"');,\s]+$", "", str(raw).lower().strip())
    if "@" not in e:
        return None
    local, _, domain = e.partition("@")
    if not local or not domain or "." not in domain:
        return None
    if any(bad in e for bad in INVALID_EMAIL_SUBSTRINGS):
        return None
    tld = domain.rsplit(".", 1)[-1]
    if not tld.isalpha() or not (2 <= len(tld) <= 6) or tld in INVALID_TLDS:
        return None
    if domain in JUNK_DOMAINS:
        return None
    if domain.rsplit(".", 1)[0].replace(".", "").isdigit():
        return None
    return e


def extract_email(text: Optional[str]) -> Optional[str]:
    """Extract first valid email candidate from text or HTML."""
    if not text:
        return None
    for match in re.findall(EMAIL_REGEX, text):
        cleaned = clean_email(match)
        if cleaned:
            return cleaned
    return None


def clean_website(url: Any) -> str:
    """Normalize and sanitize a website URL."""
    if not url:
        return ""
    u = str(url).strip()
    for prefix in ("https://www.google.com/url?q=", "http://www.google.com/url?q="):
        if u.lower().startswith(prefix):
            u = unquote(u[len(prefix):].split("&")[0])
            break
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    try:
        netloc = urlparse(u).netloc.lower().lstrip("www.")
        if netloc in JUNK_DOMAINS or "google.com" in netloc or is_third_party_directory_or_aggregator(netloc):
            return ""
    except Exception:
        return ""
    return u


def extract_domain_from_url(url: Any) -> str:
    """Extract normalized base domain from a URL."""
    if not url:
        return ""
    try:
        u = str(url).strip()
        if not u.startswith(("http://", "https://")):
            u = "http://" + u
        netloc = urlparse(u).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split(":")[0].strip()
    except Exception:
        return ""


def extract_email_domain(email: Any) -> str:
    """Extract normalized domain from an email address."""
    if not email or "@" not in str(email):
        return ""
    return str(email).lower().strip().split("@")[-1].strip()


def score_website_candidate(
    candidate_url: str,
    business_name: str,
    location: str = "",
    phone: str = "",
    address: str = "",
) -> float:
    """
    Score how plausibly candidate_url represents the business name and location.
    Returns float score between 0.0 and 1.0.
    Rejects directories, registries, aggregators, social profiles, and search engines (returns 0.0).
    """
    if not candidate_url:
        return 0.0

    domain = extract_domain_from_url(candidate_url)
    if not domain or domain in JUNK_DOMAINS:
        return 0.0

    # Reject directory, registry, aggregator, marketplace, and social profile URLs
    if is_third_party_directory_or_aggregator(candidate_url) or is_third_party_directory_or_aggregator(domain):
        return 0.0

    score = 0.0
    clean_name = re.sub(r"[^a-zA-Z0-9\s]", "", business_name.lower()).strip()
    name_tokens = [
        t for t in clean_name.split()
        if len(t) >= 3 and t not in ("groups", "group", "ltd", "pvt", "inc", "corp", "llc", "company", "co", "the")
    ]

    domain_body = domain.split(".")[0]

    matched_tokens = 0
    for tok in name_tokens:
        if tok in domain_body:
            matched_tokens += 1

    if name_tokens:
        token_ratio = matched_tokens / len(name_tokens)
        score += token_ratio * 0.6
    else:
        if clean_name.replace(" ", "") in domain_body:
            score += 0.5

    loc_lower = location.lower()
    for country, tlds in COUNTRY_CCTLD_MAP.items():
        if country in loc_lower:
            if any(domain.endswith(tld) for tld in tlds):
                score += 0.3
            else:
                for other_country, other_tlds in COUNTRY_CCTLD_MAP.items():
                    if other_country != country and any(domain.endswith(otld) for otld in other_tlds):
                        score -= 0.4
                        break
            break

    compact_name = re.sub(r"[^a-zA-Z0-9]", "", business_name.lower())
    if len(compact_name) >= 4 and compact_name in domain_body:
        score += 0.2

    # Boost score if address tokens match domain
    if address:
        addr_clean = re.sub(r"[^a-zA-Z0-9\s]", "", address.lower()).strip()
        addr_tokens = [t for t in addr_clean.split() if len(t) >= 4]
        if any(t in domain_body for t in addr_tokens):
            score += 0.1

    return max(0.0, min(1.0, round(score, 2)))


def classify_email_association(
    email: Optional[str],
    business_name: str,
    website_url: str = "",
    source_type: str = "unknown",
    context_text: str = "",
    location: str = "",
    website_association_status: Optional[str] = None,
    is_website_inferred: bool = False,
) -> Tuple[EmailAssociationStatus, str, bool]:
    """
    Determine the association status between an email and a business.
    Returns: (EmailAssociationStatus, reason_str, is_sendable_bool)
    """
    if not email:
        return EmailAssociationStatus.INVALID_FORMAT, "Missing email address", False

    cleaned = clean_email(email)
    if not cleaned:
        return EmailAssociationStatus.INVALID_FORMAT, f"Invalid email format: '{email}'", False

    email_dom = extract_email_domain(cleaned)
    web_dom = extract_domain_from_url(website_url)

    # Third-party directories, company registries, search engines, or aggregators
    # must not be treated as the business's official website.
    if is_third_party_directory_or_aggregator(website_url) or (web_dom and is_third_party_directory_or_aggregator(web_dom)):
        web_dom = ""

    # Directory/platform email (e.g. info@yellowpagesonline.in, india@dnb.com)
    # Must NOT be treated as company's own email without independent evidence
    if is_directory_or_platform_email(cleaned):
        return (
            EmailAssociationStatus.UNVERIFIED_ASSOCIATION,
            f"Email domain '{email_dom}' belongs to a directory platform. Platform mailboxes require independent business ownership evidence.",
            False,
        )

    # If the website candidate was inferred from the email domain or search candidate:
    # A matching domain is expected, but the company association is not independently verified.
    # Do not auto-approve association solely based on domain matching.
    if (website_association_status in ("candidate_match", "inferred", "unverified_search") or is_website_inferred) and web_dom:
        if email_dom == web_dom or email_dom.endswith("." + web_dom) or web_dom.endswith("." + email_dom):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                "Website candidate inferred from the business email domain. The company association is not independently verified.",
                False,
            )

    # 1. Direct domain match with company website (only when website is verified or independent)
    if web_dom and (email_dom == web_dom or email_dom.endswith("." + web_dom) or web_dom.endswith("." + email_dom)):
        return (
            EmailAssociationStatus.MATCHED,
            f"Direct domain match with business website '{web_dom}'",
            True,
        )

    # 2. Agency / Designer / Footer credit mismatch (applies to external/non-matching domains)
    if context_text:
        clean_context = re.sub(r"<[^>]+>", " ", context_text).lower()
        clean_context = re.sub(r"\s+", " ", clean_context).strip()
        for pat in AGENCY_DESIGNER_PATTERNS:
            if re.search(pat, clean_context):
                return (
                    EmailAssociationStatus.MISMATCHED_SOURCE,
                    f"Email detected in designer/agency/credit context: '{clean_context[:60]}'",
                    False,
                )

    # 3. Free / Public email providers (e.g. Gmail, Outlook, Yahoo)
    if is_public_email_provider(email_dom) or email_dom in FREE_EMAIL_PROVIDERS:
        local_part = cleaned.split("@")[0].lower()
        clean_name = re.sub(r"[^a-zA-Z0-9\s]", " ", business_name.lower())
        tokens = [
            t for t in clean_name.split()
            if len(t) >= 4 and t not in ("groups", "group", "company", "limited", "pvt", "ltd")
        ]

        if source_type in ("http_page_scrape", "http_contact_page", "structured_metadata", "places_payload"):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                f"Legitimate free mail provider ({email_dom}) discovered directly on business website; pending verification review",
                False,
            )

        if source_type in ("official_profile", "verified_directory"):
            return (
                EmailAssociationStatus.MATCHED,
                f"Public free mail provider ({email_dom}) verified via official business directory listing",
                True,
            )

        if source_type in ("user_supplied", "manual_reference"):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                f"User-supplied reference contact ({email_dom}); pending sendability review",
                False,
            )

        if any(tok in local_part for tok in tokens) or (tokens and "".join(tokens) in local_part):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                f"Free mail provider ({email_dom}) contains business name tokens '{local_part}'; requires human review",
                False,
            )

        return (
            EmailAssociationStatus.UNVERIFIED_ASSOCIATION,
            f"Free mail provider ({email_dom}) extracted from search source '{source_type}'; lacks direct official business source evidence",
            False,
        )

    # 4. Cross-domain mismatch on scraped page
    if source_type in ("http_page_scrape", "http_contact_page") and web_dom and email_dom != web_dom:
        clean_name = re.sub(r"[^a-zA-Z0-9]", "", business_name.lower())
        name_tokens = [
            t for t in re.sub(r"[^a-zA-Z0-9\s]", " ", business_name.lower()).split()
            if len(t) >= 4 and t not in ("groups", "group", "company", "limited", "pvt", "ltd", "corp", "holding", "holdings")
        ]
        dom_body = email_dom.split(".")[0]
        if clean_name and (clean_name in dom_body or dom_body in clean_name or any(tok in dom_body for tok in name_tokens)):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                f"Cross-domain email '{email_dom}' closely matches business name on website '{web_dom}'; requires review",
                False,
            )
        return (
            EmailAssociationStatus.MISMATCHED_SOURCE,
            f"Cross-domain email '{email_dom}' extracted from unrelated website '{web_dom}'",
            False,
        )

    # 5. Search Snippet / Directory API
    if source_type in ("api_search_snippet", "serper", "duckduckgo_fallback", "external_directory"):
        loc_lower = location.lower()
        for country, tlds in COUNTRY_CCTLD_MAP.items():
            if country in loc_lower:
                for other_country, other_tlds in COUNTRY_CCTLD_MAP.items():
                    if other_country != country and any(email_dom.endswith(otld) for otld in other_tlds):
                        return (
                            EmailAssociationStatus.MISMATCHED_SOURCE,
                            f"Email domain '{email_dom}' has conflicting ccTLD for business located in '{location}'",
                            False,
                        )
                break

        clean_name = re.sub(r"[^a-zA-Z0-9]", "", business_name.lower())
        dom_body = email_dom.split(".")[0]
        if len(clean_name) >= 4 and (clean_name in dom_body or dom_body in clean_name):
            return (
                EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW,
                f"Search snippet domain '{email_dom}' matches business name tokens but lacks verified website link",
                False,
            )

        return (
            EmailAssociationStatus.UNVERIFIED_ASSOCIATION,
            f"Email '{cleaned}' extracted from search snippet on unverified domain '{email_dom}'",
            False,
        )

    return (
        EmailAssociationStatus.UNVERIFIED_ASSOCIATION,
        f"Unverified email-to-business association for domain '{email_dom}'",
        False,
    )


def reconcile_duplicate_business_records(
    target_lead: Any,
    candidate_leads: List[Any],
) -> Optional[Dict[str, Any]]:
    """
    Reconcile duplicate business records for the same business entity.
    Compares business name, location, address, phone, registration identifiers, and website provenance.

    Rules:
    - Never merge or delete records.
    - Never overwrite an independently verified company website on target_lead.
    - Distinguish businesses with similar names using location, phone, address, or email domain.
    - If evidence establishes they represent the same business entity:
      Reuses the verified website candidate from the matching record as candidate_match ('Inferred — unverified').
      Preserves the original email, email source, and directory URL provenance.
      Maintains quarantine and does NOT auto-approve association or deliverability for directory emails.
    """
    if not target_lead or not candidate_leads:
        return None

    # Preserve established verified values: do not overwrite a verified primary website
    existing_status = getattr(target_lead, "website_association_status", None)
    existing_site = getattr(target_lead, "website", "")
    if existing_status == WebsiteAssociationStatus.VERIFIED_PRIMARY.value and existing_site:
        if not is_third_party_directory_or_aggregator(existing_site):
            return None

    target_name = app_clean_business_name(getattr(target_lead, "business_name", "") or "")
    clean_target = re.sub(r"[^a-zA-Z0-9\s]", "", target_name.lower()).strip()
    target_tokens = [
        t for t in clean_target.split()
        if t not in ("company", "co", "ltd", "pvt", "limited", "private", "inc", "corp", "the", "group", "llp", "corporation")
    ]
    if not target_tokens:
        return None

    target_id = str(getattr(target_lead, "id", ""))
    target_phone = getattr(target_lead, "phone", "") or ""
    target_phone_digits = re.sub(r"\D", "", target_phone)

    best_match = None
    for other in candidate_leads:
        other_id = str(getattr(other, "id", ""))
        if other_id == target_id:
            continue

        other_web = getattr(other, "website", "") or ""
        other_status = getattr(other, "website_association_status", "")
        # The matched record must have an authoritative verified website
        if not other_web or other_status != WebsiteAssociationStatus.VERIFIED_PRIMARY.value:
            continue
        if is_third_party_directory_or_aggregator(other_web):
            continue

        other_name = app_clean_business_name(getattr(other, "business_name", "") or "")
        clean_other = re.sub(r"[^a-zA-Z0-9\s]", "", other_name.lower()).strip()
        other_tokens = [
            t for t in clean_other.split()
            if t not in ("company", "co", "ltd", "pvt", "limited", "private", "inc", "corp", "the", "group", "llp", "corporation")
        ]

        # 1. Exact name equality or full token overlap check
        if clean_target != clean_other:
            overlap = set(target_tokens) & set(other_tokens)
            if len(overlap) != max(len(target_tokens), len(other_tokens)):
                continue

        # 2. Check for conflicting distinct identifiers (e.g. different cities / regions)
        target_loc = str(getattr(target_lead, "location", "") or getattr(target_lead, "city", "") or "").lower().strip()
        other_loc = str(getattr(other, "location", "") or getattr(other, "city", "") or "").lower().strip()
        if target_loc and other_loc and target_loc != other_loc:
            continue

        other_phone = getattr(other, "phone", "") or ""
        other_phone_digits = re.sub(r"\D", "", other_phone)
        # If name is highly generic, require that phone does not conflict
        if len(target_tokens) <= 2 and clean_target in ("import export", "trading company", "logistics india", "exports group"):
            if target_phone_digits and other_phone_digits and target_phone_digits != other_phone_digits:
                continue

        best_match = other
        break

    if not best_match:
        return None

    matched_web = getattr(best_match, "website", "")
    web_dom = extract_domain_from_url(matched_web)
    matched_id = str(getattr(best_match, "id", ""))

    candidate_record = {
        "url": matched_web,
        "domain": web_dom,
        "source": "existing_business_record",
        "matched_lead_id": matched_id,
        "matched_business_name": getattr(best_match, "business_name", ""),
        "status": WebsiteAssociationStatus.CANDIDATE_MATCH.value,
    }

    # Demote directory URL to email_source_url if present on target_lead
    current_target_site = getattr(target_lead, "website", "")
    if current_target_site and is_third_party_directory_or_aggregator(current_target_site):
        if not getattr(target_lead, "email_source_url", ""):
            setattr(target_lead, "email_source_url", current_target_site)

    # Apply candidate to target_lead
    setattr(target_lead, "website", matched_web)
    setattr(target_lead, "website_domain", web_dom)
    setattr(target_lead, "website_association_status", WebsiteAssociationStatus.CANDIDATE_MATCH.value)

    existing_cands = getattr(target_lead, "website_candidates", None) or []
    if isinstance(existing_cands, list):
        if not any(c.get("url") == matched_web for c in existing_cands):
            existing_cands.append(candidate_record)
        setattr(target_lead, "website_candidates", existing_cands)
    else:
        setattr(target_lead, "website_candidates", [candidate_record])

    target_email = getattr(target_lead, "email", "")
    email_dom = extract_email_domain(target_email)

    if is_directory_or_platform_email(target_email):
        setattr(target_lead, "email_domain_match", False)
        setattr(target_lead, "email_business_association_status", EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value)
        setattr(
            target_lead,
            "email_association_reason",
            f"Directory platform email domain ({email_dom}) requires independent ownership review.",
        )
        setattr(target_lead, "is_quarantined", True)
        setattr(
            target_lead,
            "quarantine_reason",
            "Directory platform email requires independent business association review",
        )
    elif is_public_email_provider(email_dom):
        setattr(target_lead, "email_domain_match", False)
        setattr(target_lead, "email_business_association_status", EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value)
        setattr(
            target_lead,
            "email_association_reason",
            f"Public email provider ({email_dom}) with candidate website '{matched_web}'; requires independent ownership review.",
        )
    else:
        dom_match = (email_dom == web_dom)
        setattr(target_lead, "email_domain_match", dom_match)
        if not dom_match:
            setattr(target_lead, "email_business_association_status", EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value)

    return {
        "matched_lead_id": matched_id,
        "website_candidate": matched_web,
        "website_domain": web_dom,
        "status": WebsiteAssociationStatus.CANDIDATE_MATCH.value,
        "evidence_source": getattr(target_lead, "email_source_url", ""),
    }



def extract_email_candidates_with_context(
    html: Optional[str],
    website: str = "",
    business_name: str = "",
    location: str = "",
    source_type: str = "http_page_scrape",
) -> List[Dict[str, Any]]:
    """
    Extract email candidates from HTML while inspecting surrounding context for
    agency credits, footers, mailto links, and domain associations.
    """
    if not html:
        return []

    results: List[Dict[str, Any]] = []
    seen_emails: Set[str] = set()

    # 1. Search mailto: links first (explicit contact link)
    mailto_matches = re.finditer(r'href=[\'"]mailto:([^\'"?]+)[^"\']*[\'"]', html, flags=re.IGNORECASE)
    for m in mailto_matches:
        raw_email = m.group(1).split("?")[0].strip()
        cleaned = clean_email(raw_email)
        if cleaned and cleaned not in seen_emails:
            seen_emails.add(cleaned)
            start_pos = max(0, m.start() - 150)
            end_pos = min(len(html), m.end() + 150)
            context = html[start_pos:end_pos]
            status, reason, is_sendable = classify_email_association(
                cleaned, business_name, website, source_type=source_type, context_text=context, location=location
            )
            results.append({
                "email": cleaned,
                "email_domain": extract_email_domain(cleaned),
                "source_type": source_type,
                "extraction_method": "mailto_link",
                "source_url": website or "",
                "context": re.sub(r"<[^>]+>", " ", context).strip()[:120],
                "association_status": status.value,
                "association_reason": reason,
                "is_sendable": is_sendable,
            })

    # 2. General regex search in HTML
    for m in re.finditer(EMAIL_REGEX, html):
        cleaned = clean_email(m.group(0))
        if cleaned and cleaned not in seen_emails:
            seen_emails.add(cleaned)
            start_pos = max(0, m.start() - 150)
            end_pos = min(len(html), m.end() + 150)
            context = html[start_pos:end_pos]
            status, reason, is_sendable = classify_email_association(
                cleaned, business_name, website, source_type=source_type, context_text=context, location=location
            )
            results.append({
                "email": cleaned,
                "email_domain": extract_email_domain(cleaned),
                "source_type": source_type,
                "extraction_method": "http_page_scrape",
                "source_url": website or "",
                "context": re.sub(r"<[^>]+>", " ", context).strip()[:120],
                "association_status": status.value,
                "association_reason": reason,
                "is_sendable": is_sendable,
            })

    priority_order = {
        EmailAssociationStatus.MATCHED.value: 0,
        EmailAssociationStatus.EXTERNAL_DOMAIN_REVIEW.value: 1,
        EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value: 2,
        EmailAssociationStatus.MISMATCHED_SOURCE.value: 3,
        EmailAssociationStatus.INVALID_FORMAT.value: 4,
    }
    results.sort(key=lambda x: priority_order.get(x.get("association_status", ""), 99))
    return results


async def _extract_resp_text(resp: Any) -> str:
    """Safely extract string text from an HTTP response, including handling mocks/coroutines."""
    if resp is None:
        return ""
    try:
        raw = resp.text
        if callable(raw):
            raw = raw()
        if hasattr(raw, "__await__"):
            raw = await raw
        return raw if isinstance(raw, str) else ""
    except Exception:
        return ""



def audit_website_is_old_or_dead(
    url: str, html: str, status_code: int, final_url: str = ""
) -> Tuple[bool, str]:
    """
    Returns (True, reason) if the website is:
      - No website
      - A dead/broken/parked website
      - An old/outdated website design
    Returns (False, "Modern Website") if active and modern.
    """
    if not url:
        return True, "No Website"

    if status_code < 200 or status_code >= 400 or not html:
        return True, f"Dead Website (HTTP {status_code})"

    html_lower = html.lower()

    # 1. Parked or Under Construction
    for sig in PARKED_SIGNALS:
        if sig in html_lower:
            return True, f"Parked/Under Construction ({sig})"

    # 2. Thin / Empty page (< 80 words)
    text_only = re.sub(
        r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    if len(text_only.split()) < 80:
        return True, "Thin/Empty Website (<80 words)"

    # 3. Old / Outdated Design Checks
    reasons = []
    check_url = final_url or url

    if check_url.startswith("http://"):
        reasons.append("No SSL (Insecure HTTP)")
    if 'name="viewport"' not in html_lower and "name='viewport'" not in html_lower:
        reasons.append("Not Mobile Responsive (No viewport tag)")
    if "w3c//dtd html 4" in html_lower or "w3c//dtd xhtml 1" in html_lower:
        reasons.append("Old HTML4/XHTML Doctype")
    if "<frameset" in html_lower or "<marquee" in html_lower or "<font " in html_lower or "<center>" in html_lower:
        reasons.append("1990s/2000s Deprecated HTML tags")
    if html_lower.count("<table") >= 4 and "display: flex" not in html_lower and "display: grid" not in html_lower:
        reasons.append("Old Table-Based Layout")
    if (
        "jquery-1." in html_lower
        or "jquery/1." in html_lower
        or "frontpage" in html_lower
        or "dreamweaver" in html_lower
    ):
        reasons.append("Outdated Tech Stack (jQuery 1.x / FrontPage / Dreamweaver)")
    if any(
        free_host in check_url.lower()
        for free_host in (".business.site", "blogspot.com", "weebly.com", "wixsite.com")
    ):
        reasons.append("Free Subdomain Builder")

    years = re.findall(r"(?:©|&copy;|copyright)\s*(?:20\d{2}\s*[-–]\s*)?(20[0-2]\d)", html_lower)
    if years and max(int(y) for y in years) <= 2021:
        reasons.append(f"Old Copyright Year ({max(int(y) for y in years)})")

    if reasons:
        return True, "Outdated Design: " + ", ".join(reasons)

    return False, "Modern Website"


# ─── URL Security & SSRF Protection ───────────────────────────────────────────

def is_safe_external_url(url: str, allow_test_loopback: bool = False) -> Tuple[bool, str]:
    """
    Validate that target URL uses http/https and does not resolve to private,
    loopback, link-local, carrier-grade NAT, or cloud metadata ranges.
    """
    if not url:
        return False, "Empty URL"
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return False, f"URL parse error: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Blocked scheme: {parsed.scheme!r}"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname"

    # Reject local/internal hostnames
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
        if not allow_test_loopback:
            return False, f"Blocked local host: {hostname}"

    # Try resolving to IP and check blocked subnets
    try:
        ip_info = socket.getaddrinfo(hostname, None)
        for item in ip_info:
            ip_str = item[4][0]
            # Check basic private/loopback/link-local patterns
            if not allow_test_loopback:
                if (
                    ip_str.startswith("127.")
                    or ip_str.startswith("10.")
                    or ip_str.startswith("192.168.")
                    or ip_str.startswith("169.254.")
                    or ip_str == "::1"
                    or (ip_str.startswith("172.") and 16 <= int(ip_str.split(".")[1]) <= 31)
                ):
                    return False, f"Blocked private/reserved IP: {ip_str}"
    except socket.gaierror:
        # Host cannot be resolved
        return False, f"DNS resolution failed for {hostname}"
    except Exception as exc:
        return False, f"IP check error: {exc}"

    return True, "Allowed"


# ─── File Upload Processing (.txt) ────────────────────────────────────────────

DISCOVERY_REGION_MAP: Dict[str, str] = {
    "IN": "India",
    "US": "USA",
    "UK": "UK",
    "GB": "UK",
    "CA": "Canada",
    "AU": "Australia",
    "AE": "UAE",
    "DE": "Germany",
    "SG": "Singapore",
    "NZ": "New Zealand",
}


def parse_txt_upload_content(
    content_bytes: bytes,
    file_type: str = "keywords",
    max_file_size: int = 1_048_576,
    max_entries: int = 1000,
) -> Dict[str, Any]:
    """
    Parse uploaded .txt file for keywords or locations.
    - Handles UTF-8 and UTF-8 BOM, comments (#, //, --), empty lines and section tags.
    - Supports multiword keywords, pipe delimiters (|) across niche lines.
    - Supports location formats (REGION:City, City, Country, or City).
    - Validates minimum/maximum length constraints and records invalid items.
    - Case-insensitive deduplication preserving original readable values.
    - Enforces size limit and max entry count.
    """
    if len(content_bytes) > max_file_size:
        raise ValueError(
            f"File exceeds maximum allowed size ({len(content_bytes)} bytes > {max_file_size} bytes limit)."
        )

    try:
        text = content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1")
            except UnicodeDecodeError:
                raise ValueError("File is not a valid UTF-8 text document.")

    lines = text.splitlines()
    entries: List[str] = []
    seen_lower: Set[str] = set()
    invalid_entries: List[str] = []

    ignored_count = 0
    duplicate_count = 0
    rejected_count = 0

    for line in lines:
        raw_stripped = line.strip()
        if not raw_stripped or raw_stripped.startswith(("#", "//", "--")):
            ignored_count += 1
            continue

        # Ignore bracketed section headings like [KEYWORDS], [CITIES]
        if re.match(r"^\[.+\]$", raw_stripped):
            ignored_count += 1
            continue

        if file_type == "locations":
            if ":" in raw_stripped:
                prefix, _, city_part = raw_stripped.partition(":")
                prefix = prefix.strip()
                city = city_part.strip()
                if len(city) < 2:
                    rejected_count += 1
                    invalid_entries.append(f"{raw_stripped} (location '{city}' too short)")
                    continue

                upper_prefix = prefix.upper()
                if upper_prefix in DISCOVERY_REGION_MAP:
                    country = DISCOVERY_REGION_MAP[upper_prefix]
                    if country.lower() not in city.lower():
                        loc_val = f"{city}, {country}"
                    else:
                        loc_val = city
                elif prefix:
                    loc_val = f"{city}, {prefix}"
                else:
                    loc_val = city
            else:
                loc_val = raw_stripped

            if len(loc_val) < 2 or len(loc_val) > 200:
                rejected_count += 1
                invalid_entries.append(f"{loc_val[:30]} (length out of bounds 2-200)")
                continue

            key = loc_val.lower()
            if key in seen_lower:
                duplicate_count += 1
                continue

            if len(entries) >= max_entries:
                rejected_count += 1
                invalid_entries.append(f"{loc_val[:30]} (exceeds max {max_entries} limit)")
                continue

            seen_lower.add(key)
            entries.append(loc_val)

        else:
            # Keywords: Support pipe-separated format (Category | kw1 | kw2 | ...) or single line
            if "|" in raw_stripped:
                parts = [p.strip() for p in raw_stripped.split("|")]
            else:
                parts = [raw_stripped]

            for part in parts:
                if not part:
                    continue
                if len(part) < 2 or len(part) > 200:
                    rejected_count += 1
                    invalid_entries.append(f"{part[:30]} (length out of bounds 2-200)")
                    continue

                key = part.lower()
                if key in seen_lower:
                    duplicate_count += 1
                    continue

                if len(entries) >= max_entries:
                    rejected_count += 1
                    invalid_entries.append(f"{part[:30]} (exceeds max {max_entries} limit)")
                    continue

                seen_lower.add(key)
                entries.append(part)

    if not entries:
        raise ValueError("Uploaded file contains no usable entries after filtering blanks and comments.")

    return {
        "valid_count": len(entries),
        "ignored_count": ignored_count,
        "duplicate_count": duplicate_count,
        "rejected_count": rejected_count,
        "invalid_entries": invalid_entries,
        "entries": entries,
    }


# ─── Lead Discovery Engine ───────────────────────────────────────────────────

class LeadDiscoveryService:
    """Orchestrates API search, HTTP inspection, fallbacks, and job checkpoints."""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        allow_test_loopback: bool = False,
        key_manager: Optional[Any] = None,
    ):
        self.storage_path = storage_path or settings.DISCOVERY_STORAGE_FILE
        self.allow_test_loopback = allow_test_loopback
        self.key_manager = key_manager or get_key_manager(settings)
        self._provider_status: Dict[str, Dict[str, Any]] = {}
        self._init_providers()
        self._jobs: Dict[str, Dict[str, Any]] = self._load_jobs()

    def _init_providers(self):
        """Initialize provider statuses based on environment settings and key pools."""
        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        serper_pool = km.get_pool("serper")
        treg_pool = km.get_pool("treg")
        serpapi_pool = km.get_pool("serpapi")
        hasdata_pool = km.get_pool("hasdata")
        outscraper_pool = km.get_pool("outscraper")
        hunter_pool = km.get_pool("hunter")

        serper_conf = (serper_pool.is_configured() if serper_pool else False) or bool(getattr(settings, "SERPER_API_KEY", ""))
        treg_conf = (treg_pool.is_configured() if treg_pool else False) or bool(getattr(settings, "TREG_API_TOKEN", "") or getattr(settings, "TREG_API_KEY", ""))
        serpapi_conf = (serpapi_pool.is_configured() if serpapi_pool else False) or bool(getattr(settings, "SERPAPI_API_KEY", ""))
        hasdata_conf = (hasdata_pool.is_configured() if hasdata_pool else False) or bool(getattr(settings, "HASDATA_API_KEY", ""))
        outscraper_conf = (outscraper_pool.is_configured() if outscraper_pool else False) or bool(getattr(settings, "OUTSCRAPER_API_KEY", ""))
        hunter_conf = (hunter_pool.is_configured() if hunter_pool else False) or bool(getattr(settings, "HUNTER_API_KEY", ""))

        self._provider_status = {
            "serper": {
                "status": ProviderStatus.AVAILABLE if serper_conf else ProviderStatus.DISABLED,
                "configured": serper_conf,
                "key_masked": self._mask_key(getattr(settings, "SERPER_API_KEY", "") or (serper_pool.keys[0].secret if serper_pool and serper_pool.keys else "")),
                "last_error": None,
            },
            "serpapi": {
                "status": ProviderStatus.AVAILABLE if serpapi_conf else ProviderStatus.DISABLED,
                "configured": serpapi_conf,
                "key_masked": self._mask_key(getattr(settings, "SERPAPI_API_KEY", "")),
                "last_error": None,
            },
            "hasdata": {
                "status": ProviderStatus.AVAILABLE if hasdata_conf else ProviderStatus.DISABLED,
                "configured": hasdata_conf,
                "key_masked": self._mask_key(getattr(settings, "HASDATA_API_KEY", "")),
                "last_error": None,
            },
            "outscraper": {
                "status": ProviderStatus.AVAILABLE if outscraper_conf else ProviderStatus.DISABLED,
                "configured": outscraper_conf,
                "key_masked": self._mask_key(getattr(settings, "OUTSCRAPER_API_KEY", "")),
                "last_error": None,
            },
            "hunter": {
                "status": ProviderStatus.AVAILABLE if hunter_conf else ProviderStatus.DISABLED,
                "configured": hunter_conf,
                "key_masked": self._mask_key(getattr(settings, "HUNTER_API_KEY", "")),
                "last_error": None,
            },
            "treg": {
                "status": ProviderStatus.AVAILABLE if treg_conf else ProviderStatus.DISABLED,
                "configured": treg_conf,
                "key_masked": self._mask_key(getattr(settings, "TREG_API_TOKEN", "") or (treg_pool.keys[0].secret if treg_pool and treg_pool.keys else "")),
                "last_error": None,
            },
            "http_direct": {
                "status": ProviderStatus.AVAILABLE,
                "configured": True,
                "key_masked": "N/A",
                "last_error": None,
            },
            "duckduckgo_fallback": {
                "status": ProviderStatus.AVAILABLE,
                "configured": True,
                "key_masked": "N/A",
                "last_error": None,
            },
            "google_maps_direct": {
                "status": ProviderStatus.DISABLED,
                "configured": False,
                "key_masked": "N/A",
                "last_error": "Automated scraping prohibited by terms of service without authorized API.",
            },
        }

    @staticmethod
    def _mask_key(key: str) -> str:
        if not key:
            return ""
        if len(key) <= 6:
            return "***"
        return f"{key[:3]}...{key[-3:]}"

    def get_provider_statuses(self) -> Dict[str, Any]:
        """Return provider configuration status, health, and sanitized slot diagnostics."""
        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        pool_diags = km.get_all_diagnostics()

        result = {}
        for k, v in self._provider_status.items():
            pool_diag = pool_diags.get(k, {})
            pool_conf = pool_diag.get("configured", False)
            configured = v["configured"] or pool_conf

            status_val = v["status"]
            status_str = status_val.value if isinstance(status_val, ProviderStatus) else str(status_val)

            if k == "google_maps_direct":
                status_str = "disabled"
            elif pool_conf:
                status_str = pool_diag.get("status", status_str)

            result[k] = {
                "status": status_str,
                "configured": configured,
                "key_masked": v["key_masked"],
                "last_error": v["last_error"],
                "total_slots": pool_diag.get("total_slots", 1 if configured else 0),
                "available_slots": pool_diag.get("available_slots", 1 if (configured and status_str == "available") else 0),
                "shared_quota_exhausted": pool_diag.get("shared_quota_exhausted", False),
                "slots": pool_diag.get("slots", []),
            }
        return result

    # ─── Job Persistence ──────────────────────────────────────────────────────

    def _load_jobs(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read discovery jobs file %s: %s", self.storage_path, exc)
        return {}

    def _save_jobs(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._jobs, f, indent=2, default=str)
        except Exception as exc:
            logger.error("Failed to save discovery jobs to %s: %s", self.storage_path, exc)

    # ─── Combinations & Budget ────────────────────────────────────────────────

    def calculate_combinations(
        self,
        keywords: List[str],
        locations: List[str],
        mode: str = "uploaded_only",
        custom_budget: Optional[int] = None,
        batch_offset: Optional[int] = 0,
    ) -> Dict[str, Any]:
        """
        Calculate total search combinations and enforce configured safety limits.
        Modes: 'uploaded_only', 'presets_only', 'combine', 'replace'
        """
        active_kws = list(keywords)
        active_locs = list(locations)

        if mode == "presets_only":
            active_kws = list(DEFAULT_PRESET_KEYWORDS)
            active_locs = list(DEFAULT_PRESET_LOCATIONS)
        elif mode == "combine":
            # Merge case-insensitively
            seen_k = {k.lower() for k in active_kws}
            for pk in DEFAULT_PRESET_KEYWORDS:
                if pk.lower() not in seen_k:
                    active_kws.append(pk)
                    seen_k.add(pk.lower())
            seen_l = {l.lower() for l in active_locs}
            for pl in DEFAULT_PRESET_LOCATIONS:
                if pl.lower() not in seen_l:
                    active_locs.append(pl)
                    seen_l.add(pl.lower())

        total_combinations = len(active_kws) * len(active_locs)
        max_allowed = getattr(settings, "DISCOVERY_MAX_COMBINATIONS_LIMIT", 500)
        offset = max(0, batch_offset or 0)
        remaining = max(0, total_combinations - offset)

        budget = custom_budget if custom_budget and custom_budget > 0 else total_combinations
        exceeds_safety_limit = total_combinations > max_allowed and (budget > max_allowed)
        effective_budget = min(budget, remaining) if remaining > 0 else 0

        batch_start = (offset + 1) if (total_combinations > 0 and effective_budget > 0) else 0
        batch_end = min(total_combinations, offset + effective_budget)
        # step_size is the configured navigation budget (unclamped), so that total_batches and
        # current_batch_num are consistent across all batches including the last partial batch.
        # effective_budget is the actual run count for this batch (may be smaller on the last batch);
        # it must NOT be used as the step size or the final-batch batch-number will be wrong.
        # max_allowed is the hard per-job execution cap and is never the pagination step size.
        step_size = budget if budget > 0 else max_allowed
        total_batches = max(1, -(-total_combinations // step_size)) if total_combinations > 0 else 1
        current_batch_num = (offset // step_size) + 1 if step_size > 0 else 1

        return {
            "mode": mode,
            "keyword_count": len(active_kws),
            "location_count": len(active_locs),
            "total_combinations": total_combinations,
            "max_allowed_combinations": max_allowed,
            "batch_offset": offset,
            "batch_start": batch_start,
            "batch_end": batch_end,
            "total_batches": total_batches,
            "current_batch_num": current_batch_num,
            "effective_budget": effective_budget,
            "exceeds_safety_limit": exceeds_safety_limit,
            "keywords": active_kws,
            "locations": active_locs,
        }

    # ─── Provider Calling & Failover ──────────────────────────────────────────

    def _classify_http_status(self, status: int) -> ProviderStatus:
        if status == 401:
            return ProviderStatus.AUTHENTICATION_ERROR
        if status == 402:
            return ProviderStatus.QUOTA_EXHAUSTED
        if status == 429:
            return ProviderStatus.RATE_LIMITED
        if 500 <= status <= 599:
            return ProviderStatus.TEMPORARILY_UNAVAILABLE
        return ProviderStatus.AVAILABLE

    async def search_places(
        self,
        session: aiohttp.ClientSession,
        keyword: str,
        city: str,
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Search businesses across authorized providers with automatic fallback.
        Priority:
        1. Treg (Catalog Proxied Google Maps API)
        2. Serper Maps API (with Two-Key Rotation)
        3. SerpApi Direct
        4. HasData Google Maps
        5. Outscraper Maps
        6. Compliant fallback or honest empty/none
        Returns: (places_list, selected_source, method)
        """
        if fetcher_mock is not None:
            return fetcher_mock(keyword, city)

        query = f"{keyword} in {city}"
        km = getattr(self, "key_manager", None) or get_key_manager(settings)

        # 1. Treg Proxied Google Maps API (Catalog endpoint)
        treg_pool = km.get_pool("treg")
        treg_enabled = getattr(getattr(km, "settings", None) or settings, "TREG_ENABLE_PAID_ENDPOINTS", False)
        if treg_pool and treg_pool.is_configured() and not treg_pool.shared_quota_exhausted and treg_enabled:
            attempts = 0
            max_treg_attempts = max(1, len(treg_pool.keys))
            while attempts < max_treg_attempts:
                attempts += 1
                key_item = await treg_pool.get_next_key()
                if not key_item:
                    break
                prov_key, slot_id = key_item
                try:
                    url = "https://treg.to/call/serpapi.google.maps"
                    headers = {"X-Treg-Token": prov_key.secret, "Accept": "application/json"}
                    async with session.get(url, params={"q": query, "type": "search"}, headers=headers, timeout=20) as resp:
                        retry_after = resp.headers.get("Retry-After")
                        ra_val = float(retry_after) if retry_after and retry_after.isdigit() else None
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        treg_pool.report_result(
                            prov_key,
                            resp.status,
                            retry_after=ra_val,
                            error_message=err_text,
                            quota_exhausted=is_quota,
                        )

                        if resp.status == 200:
                            data = await resp.json()
                            items = data.get("local_results", data.get("results", data.get("places", [])))
                            if items:
                                return [
                                    {
                                        "name": (i.get("title") or i.get("name", "")).strip(),
                                        "website": clean_website(i.get("website") or i.get("link", "")),
                                        "phone": i.get("phone") or i.get("phoneNumber"),
                                        "email": extract_email(json.dumps(i)),
                                        "source": "treg",
                                        "endpoint": "serpapi.google.maps",
                                        "key_slot": slot_id,
                                        "account_id": prov_key.account_id,
                                        "quota_scope": prov_key.quota_scope.scope_id,
                                        "method": "api_proxy_maps",
                                    }
                                    for i in items
                                ], "treg", "api_proxy_maps"
                            break

                        if resp.status == 401 or (resp.status == 403 and prov_key.is_auth_failed):
                            continue
                        if resp.status == 402 or is_quota:
                            if treg_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403:
                            continue
                except Exception as exc:
                    treg_pool.report_result(prov_key, 500, error_message=str(exc))
                    break

        # 2. Serper Maps API (with Two-Key Rotation)
        serper_pool = km.get_pool("serper")
        serper_key_legacy = getattr(settings, "SERPER_API_KEY", "")
        if (serper_pool and serper_pool.is_configured() and not serper_pool.shared_quota_exhausted) or (serper_key_legacy and self._provider_status.get("serper", {}).get("status") == ProviderStatus.AVAILABLE):
            attempts = 0
            max_serper_attempts = max(1, len(serper_pool.keys)) if serper_pool and serper_pool.keys else 1
            while attempts < max_serper_attempts:
                attempts += 1
                slot_id = 1
                if serper_pool and serper_pool.is_configured():
                    key_item = await serper_pool.get_next_key()
                    if not key_item:
                        break
                    prov_key, slot_id = key_item
                    current_key = prov_key.secret
                else:
                    prov_key = None
                    current_key = serper_key_legacy

                try:
                    url = "https://google.serper.dev/maps"
                    headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
                    async with session.post(url, json={"q": query}, headers=headers, timeout=20) as resp:
                        retry_after = resp.headers.get("Retry-After")
                        ra_val = float(retry_after) if retry_after and retry_after.isdigit() else None
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        if prov_key and serper_pool:
                            serper_pool.report_result(
                                prov_key,
                                resp.status,
                                retry_after=ra_val,
                                error_message=err_text,
                                quota_exhausted=is_quota,
                            )

                        if resp.status != 200:
                            st = self._classify_http_status(resp.status)
                            if "serper" in self._provider_status:
                                self._provider_status["serper"]["status"] = st
                                self._provider_status["serper"]["last_error"] = f"HTTP {resp.status}"

                            if (resp.status == 401 or (resp.status == 403 and getattr(prov_key, "is_auth_failed", False))) and serper_pool:
                                continue
                            if (resp.status == 402 or is_quota):
                                if serper_pool and serper_pool.shared_quota_exhausted:
                                    break
                                continue
                            if resp.status == 403 and serper_pool:
                                continue
                        else:
                            data = await resp.json()
                            places = data.get("places", [])
                            if places:
                                return [
                                    {
                                        "name": p.get("title", "").strip(),
                                        "website": clean_website(p.get("website", "")),
                                        "phone": p.get("phoneNumber"),
                                        "email": None,
                                        "source": "serper",
                                        "endpoint": "maps",
                                        "key_slot": slot_id,
                                        "account_id": prov_key.account_id if prov_key else "serper_legacy",
                                        "quota_scope": prov_key.quota_scope.scope_id if prov_key else "serper_account_1",
                                        "method": "api_maps",
                                    }
                                    for p in places
                                ], "serper", "api_maps"
                            break
                except Exception as exc:
                    if prov_key and serper_pool:
                        serper_pool.report_result(prov_key, 500, error_message=str(exc))
                    if "serper" in self._provider_status:
                        self._provider_status["serper"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                        self._provider_status["serper"]["last_error"] = str(exc)
                    break

        # 3. SerpApi Direct
        serpapi_pool = km.get_pool("serpapi")
        serpapi_key = getattr(settings, "SERPAPI_API_KEY", "") or (serpapi_pool.keys[0].secret if serpapi_pool and serpapi_pool.keys else "")
        if serpapi_key and self._provider_status.get("serpapi", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://serpapi.com/search.json"
                params = {"engine": "google_maps", "q": query, "api_key": serpapi_key}
                async with session.get(url, params=params, timeout=20) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["serpapi"]["status"] = st
                        self._provider_status["serpapi"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        places = data.get("local_results", [])
                        if places:
                            return [
                                {
                                    "name": p.get("title", "").strip(),
                                    "website": clean_website(p.get("website", "")),
                                    "phone": p.get("phone"),
                                    "email": None,
                                    "source": "serpapi",
                                    "endpoint": "google_maps",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "serpapi", "api_maps"
            except Exception as exc:
                self._provider_status["serpapi"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["serpapi"]["last_error"] = str(exc)

        # 4. HasData Google Maps API
        hasdata_pool = km.get_pool("hasdata")
        hasdata_key = getattr(settings, "HASDATA_API_KEY", "") or (hasdata_pool.keys[0].secret if hasdata_pool and hasdata_pool.keys else "")
        if hasdata_key and self._provider_status.get("hasdata", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.hasdata.com/scrape/google-maps/search"
                headers = {"x-api-key": hasdata_key, "Accept": "application/json"}
                async with session.get(url, params={"q": query}, headers=headers, timeout=20) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["hasdata"]["status"] = st
                        self._provider_status["hasdata"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        places = data.get("localResults", [])
                        if places:
                            return [
                                {
                                    "name": p.get("title", "").strip(),
                                    "website": clean_website(p.get("website", "")),
                                    "phone": p.get("phone"),
                                    "email": None,
                                    "source": "hasdata",
                                    "endpoint": "scrape/google-maps/search",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "hasdata", "api_maps"
            except Exception as exc:
                self._provider_status["hasdata"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["hasdata"]["last_error"] = str(exc)

        # 5. Outscraper Maps API
        outscraper_pool = km.get_pool("outscraper")
        outscraper_key = getattr(settings, "OUTSCRAPER_API_KEY", "") or (outscraper_pool.keys[0].secret if outscraper_pool and outscraper_pool.keys else "")
        if outscraper_key and self._provider_status.get("outscraper", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.app.outscraper.com/maps/search-v3"
                headers = {"X-API-KEY": outscraper_key}
                params = {"query": query, "limit": 20, "async": "false"}
                async with session.get(url, params=params, headers=headers, timeout=25) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["outscraper"]["status"] = st
                        self._provider_status["outscraper"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        batches = data.get("data", [])
                        places = batches[0] if batches else []
                        if places:
                            return [
                                {
                                    "name": p.get("name", "").strip(),
                                    "website": clean_website(p.get("site", "")),
                                    "phone": p.get("phone"),
                                    "email": clean_email(p.get("email_1", "")),
                                    "source": "outscraper",
                                    "endpoint": "maps/search-v3",
                                    "key_slot": 1,
                                    "method": "api_maps",
                                }
                                for p in places
                            ], "outscraper", "api_maps"
            except Exception as exc:
                self._provider_status["outscraper"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["outscraper"]["last_error"] = str(exc)

        return [], "none", "no_results"

    # ─── Candidate Website Discovery & Ranking ───────────────────────────────

    async def search_candidate_websites(
        self,
        session: aiohttp.ClientSession,
        name: str,
        city: str = "",
        phone: str = "",
        address: str = "",
        registration_details: str = "",
        fetcher_mock: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for candidate websites when a business record lacks a verified website.
        Ranks candidates by token match, location relevance, and junk domain filtering.
        Rejects directory, registry, aggregator, marketplace, and social profile URLs as official company websites.
        """
        norm_name = app_clean_business_name(name)
        if fetcher_mock is not None:
            raw_candidates = fetcher_mock(norm_name, city)
            scored: List[Dict[str, Any]] = []
            for c in raw_candidates:
                url = c if isinstance(c, str) else c.get("url", "")
                if is_third_party_directory_or_aggregator(url):
                    continue
                score = score_website_candidate(url, norm_name, location=city, phone=phone, address=address)
                if score <= 0.0:
                    continue
                scored.append({
                    "url": url,
                    "domain": extract_domain_from_url(url),
                    "score": score,
                    "source": "mock_website_search",
                    "status": "candidate_match" if score >= 0.5 else "unverified_search",
                })
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored

        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        serper_pool = km.get_pool("serper")
        serper_key_legacy = getattr(settings, "SERPER_API_KEY", "")

        candidates: List[Dict[str, Any]] = []
        if (serper_pool and serper_pool.is_configured() and not serper_pool.shared_quota_exhausted) or serper_key_legacy:
            try:
                current_key = serper_key_legacy
                prov_key = None
                if serper_pool and serper_pool.is_configured():
                    key_item = await serper_pool.get_next_key()
                    if key_item:
                        prov_key, _ = key_item
                        current_key = prov_key.secret

                url = "https://google.serper.dev/search"
                query_parts = [f'"{norm_name}"']
                if city:
                    query_parts.append(city)
                if phone:
                    query_parts.append(phone)
                query_parts.append("official website")
                query_str = " ".join(query_parts)

                payload = {"q": query_str}
                headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
                async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for org in data.get("organic", []):
                            link = org.get("link", "")
                            if is_third_party_directory_or_aggregator(link):
                                continue
                            clean_url = clean_website(link)
                            if not clean_url or is_third_party_directory_or_aggregator(clean_url):
                                continue
                            score = score_website_candidate(clean_url, norm_name, location=city, phone=phone, address=address)
                            if score <= 0.0:
                                continue
                            candidates.append({
                                "url": clean_url,
                                "domain": extract_domain_from_url(clean_url),
                                "score": score,
                                "source": "serper_organic",
                                "title": org.get("title", ""),
                                "snippet": org.get("snippet", ""),
                                "status": "candidate_match" if score >= 0.5 else "unverified_search",
                            })
            except Exception as exc:
                logger.debug("Candidate website search error: %s", exc)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    async def discover_website_from_email_domain(
        self,
        session: aiohttp.ClientSession,
        email_domain: str,
        business_name: str = "",
        location: str = "",
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[Optional[str], WebsiteAssociationStatus, str, List[Dict[str, Any]]]:
        """
        Investigate whether a custom email domain also hosts an accessible business website.
        Follows safe URL discovery, SSRF protection, strict TLS verification,
        and tests https://, https://www., and http:// variants.

        Returns:
            (discovered_url, association_status, classification_reason, candidate_records)
        """
        norm_dom = normalize_domain(email_domain)
        if not norm_dom or not is_custom_email_domain(norm_dom):
            return None, WebsiteAssociationStatus.NO_WEBSITE, "Domain is public, disposable, or empty", []

        tested_candidates: List[Dict[str, Any]] = []

        if fetcher_mock is not None:
            mock_url = f"https://{norm_dom}"
            res = None
            if callable(fetcher_mock):
                try:
                    res = fetcher_mock(f"email_domain_hint:{norm_dom}")
                except Exception:
                    pass
                if res is None:
                    try:
                        res = fetcher_mock(mock_url)
                    except Exception:
                        pass

            if res is not None:
                if isinstance(res, tuple) and len(res) >= 2:
                    is_live = bool(res[0])
                    reason = str(res[1])
                    if "inconclusive" in reason.lower() or "timeout" in reason.lower() or "blocked" in reason.lower() or "challenge" in reason.lower() or "cloudflare" in reason.lower() or "bot" in reason.lower():
                        status = WebsiteAssociationStatus.INCONCLUSIVE
                        tested_candidates.append({
                            "url": mock_url,
                            "domain": norm_dom,
                            "source": "email_domain_hint",
                            "status": status.value,
                            "reason": reason,
                        })
                        return None, status, reason, tested_candidates
                    elif not is_live or "dead" in reason.lower() or "no website" in reason.lower() or "not found" in reason.lower():
                        status = WebsiteAssociationStatus.NO_WEBSITE
                        tested_candidates.append({
                            "url": mock_url,
                            "domain": norm_dom,
                            "source": "email_domain_hint",
                            "status": status.value,
                            "http_status": 404,
                            "reason": reason,
                        })
                        return None, status, reason, tested_candidates
                    else:
                        status = WebsiteAssociationStatus.CANDIDATE_MATCH
                        score = score_website_candidate(mock_url, business_name, location)
                        tested_candidates.append({
                            "url": mock_url,
                            "domain": norm_dom,
                            "score": score,
                            "source": "email_domain_hint",
                            "status": status.value,
                            "http_status": 200,
                            "reason": reason,
                        })
                        return mock_url, status, reason, tested_candidates

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        candidate_urls = [
            f"https://{norm_dom}",
            f"https://www.{norm_dom}",
            f"http://{norm_dom}",
        ]

        has_inconclusive = False
        all_conn_refused = True

        for target_url in candidate_urls:
            safe, reason = is_safe_external_url(target_url, allow_test_loopback=self.allow_test_loopback)
            if not safe:
                tested_candidates.append({
                    "url": target_url,
                    "domain": norm_dom,
                    "score": 0.0,
                    "source": "email_domain_hint",
                    "status": "blocked_ssrf",
                    "reason": reason,
                })
                all_conn_refused = False
                continue

            try:
                async with session.get(
                    target_url,
                    headers=headers,
                    timeout=10,
                    allow_redirects=True,
                    ssl=True,
                ) as resp:
                    all_conn_refused = False
                    status_code = resp.status
                    final_url = str(resp.url)
                    safe_dest, dest_reason = is_safe_external_url(
                        final_url, allow_test_loopback=self.allow_test_loopback
                    )
                    if not safe_dest:
                        tested_candidates.append({
                            "url": target_url,
                            "domain": norm_dom,
                            "source": "email_domain_hint",
                            "status": "blocked_redirect",
                            "reason": dest_reason,
                        })
                        continue

                    if status_code in (401, 403, 429) or (500 <= status_code <= 504):
                        has_inconclusive = True
                        tested_candidates.append({
                            "url": target_url,
                            "domain": norm_dom,
                            "source": "email_domain_hint",
                            "http_status": status_code,
                            "status": "inconclusive",
                            "reason": f"HTTP {status_code} challenge/server response",
                        })
                        continue

                    if 200 <= status_code < 400:
                        html = await resp.text(errors="ignore")
                        is_target, class_reason = audit_website_is_old_or_dead(target_url, html, status_code, final_url)
                        is_dead = ("dead website" in class_reason.lower() or "parked" in class_reason.lower() or "thin" in class_reason.lower())
                        score = score_website_candidate(final_url, business_name, location)
                        status_val = WebsiteAssociationStatus.CANDIDATE_MATCH if not is_dead else WebsiteAssociationStatus.UNVERIFIED_SEARCH

                        cand_record = {
                            "url": final_url,
                            "domain": extract_domain_from_url(final_url) or norm_dom,
                            "score": score,
                            "source": "email_domain_hint",
                            "http_status": status_code,
                            "status": status_val.value,
                            "classification": class_reason,
                        }
                        tested_candidates.append(cand_record)

                        if not is_dead:
                            return (
                                final_url,
                                WebsiteAssociationStatus.CANDIDATE_MATCH,
                                f"Accessible website discovered via email domain hint ({class_reason})",
                                tested_candidates,
                            )
                    else:
                        tested_candidates.append({
                            "url": target_url,
                            "domain": norm_dom,
                            "source": "email_domain_hint",
                            "http_status": status_code,
                            "status": "http_error",
                        })

            except aiohttp.ClientSSLError as ssl_err:
                tested_candidates.append({
                    "url": target_url,
                    "domain": norm_dom,
                    "source": "email_domain_hint",
                    "status": "ssl_error",
                    "reason": str(ssl_err),
                })
                all_conn_refused = False
                continue
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
                has_inconclusive = True
                all_conn_refused = False
                tested_candidates.append({
                    "url": target_url,
                    "domain": norm_dom,
                    "source": "email_domain_hint",
                    "status": "timeout",
                    "reason": "Connection timed out",
                })
                continue
            except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, ConnectionRefusedError, socket.gaierror) as conn_err:
                tested_candidates.append({
                    "url": target_url,
                    "domain": norm_dom,
                    "source": "email_domain_hint",
                    "status": "connection_failed",
                    "reason": type(conn_err).__name__,
                })
                continue
            except Exception as exc:
                has_inconclusive = True
                all_conn_refused = False
                tested_candidates.append({
                    "url": target_url,
                    "domain": norm_dom,
                    "source": "email_domain_hint",
                    "status": "error",
                    "reason": str(exc),
                })
                continue

        if has_inconclusive:
            return (
                None,
                WebsiteAssociationStatus.INCONCLUSIVE,
                "Website candidate check inconclusive (access restriction or timeout)",
                tested_candidates,
            )

        if all_conn_refused:
            return (
                None,
                WebsiteAssociationStatus.NO_WEBSITE,
                "Confirmed no accessible web server on email domain",
                tested_candidates,
            )

        return (
            None,
            WebsiteAssociationStatus.UNVERIFIED_SEARCH,
            "No active website found on email domain candidates",
            tested_candidates,
        )

    # ─── Email Enrichment with Structured Provenance ──────────────────────────

    async def enrich_email_detailed(
        self,
        session: aiohttp.ClientSession,
        name: str,
        city: str,
        website: str = "",
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[Optional[str], str, str, str, List[Dict[str, Any]]]:
        """
        Enrich email with structured candidate extraction, provenance tracking, and source URL attribution.
        Returns: (primary_email, source, method, source_url, candidates_list)
        """
        if fetcher_mock is not None:
            res = fetcher_mock(name, city, website)
            if isinstance(res, tuple):
                if len(res) == 3:
                    em, src, meth = res
                    cand: List[Dict[str, Any]] = []
                    if em:
                        st, reas, send = classify_email_association(
                            em, name, website, source_type=src, location=city
                        )
                        cand.append({
                            "email": em,
                            "email_domain": extract_email_domain(em),
                            "source_type": src,
                            "extraction_method": meth,
                            "source_url": website or "",
                            "association_status": st.value,
                            "association_reason": reas,
                            "is_sendable": send,
                        })
                    return em, src, meth, website or "", cand
                elif len(res) == 5:
                    return res
            return None, "none", "none", "", []

        domain = extract_domain_from_url(website)
        km = getattr(self, "key_manager", None) or get_key_manager(settings)
        candidates: List[Dict[str, Any]] = []

        # 1. Treg Hunter proxy
        treg_pool = km.get_pool("treg")
        treg_enabled = getattr(getattr(km, "settings", None) or settings, "TREG_ENABLE_PAID_ENDPOINTS", False)
        if domain and treg_pool and treg_pool.is_configured() and not treg_pool.shared_quota_exhausted and treg_enabled:
            attempts = 0
            max_attempts = max(1, len(treg_pool.keys))
            while attempts < max_attempts:
                attempts += 1
                key_item = await treg_pool.get_next_key()
                if not key_item:
                    break
                prov_key, slot_id = key_item
                try:
                    url = "https://treg.to/call/https://api.hunter.io/v2/domain-search"
                    headers = {"X-Treg-Token": prov_key.secret}
                    async with session.get(url, params={"domain": domain}, headers=headers, timeout=15) as resp:
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        treg_pool.report_result(
                            prov_key,
                            resp.status,
                            error_message=err_text,
                            quota_exhausted=is_quota,
                        )
                        if resp.status == 200:
                            data = await resp.json()
                            for e in data.get("data", {}).get("emails", []):
                                cleaned = clean_email(e.get("value", ""))
                                if cleaned:
                                    st, reas, send = classify_email_association(
                                        cleaned, name, website, source_type="treg_hunter", location=city
                                    )
                                    candidates.append({
                                        "email": cleaned,
                                        "email_domain": extract_email_domain(cleaned),
                                        "source_type": "treg_hunter",
                                        "extraction_method": "api_proxy_hunter",
                                        "source_url": website,
                                        "association_status": st.value,
                                        "association_reason": reas,
                                        "is_sendable": send,
                                    })
                            if candidates:
                                return candidates[0]["email"], "treg", "api_proxy_hunter", website, candidates
                            break
                        if resp.status == 401 or (resp.status == 403 and prov_key.is_auth_failed):
                            continue
                        if resp.status == 402 or is_quota:
                            if treg_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403:
                            continue
                except Exception as exc:
                    treg_pool.report_result(prov_key, 500, error_message=str(exc))
                    break

        # 2. Hunter API direct
        hunter_pool = km.get_pool("hunter")
        hunter_key = getattr(settings, "HUNTER_API_KEY", "") or (hunter_pool.keys[0].secret if hunter_pool and hunter_pool.keys else "")
        if domain and hunter_key and self._provider_status.get("hunter", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                url = "https://api.hunter.io/v2/domain-search"
                async with session.get(url, params={"domain": domain, "api_key": hunter_key}, timeout=15) as resp:
                    if resp.status != 200:
                        st = self._classify_http_status(resp.status)
                        self._provider_status["hunter"]["status"] = st
                        self._provider_status["hunter"]["last_error"] = f"HTTP {resp.status}"
                    else:
                        data = await resp.json()
                        for e in data.get("data", {}).get("emails", []):
                            cleaned = clean_email(e.get("value", ""))
                            if cleaned:
                                st, reas, send = classify_email_association(
                                    cleaned, name, website, source_type="hunter", location=city
                                )
                                candidates.append({
                                    "email": cleaned,
                                    "email_domain": extract_email_domain(cleaned),
                                    "source_type": "hunter",
                                    "extraction_method": "api_domain_search",
                                    "source_url": website,
                                    "association_status": st.value,
                                    "association_reason": reas,
                                    "is_sendable": send,
                                })
                        if candidates:
                            return candidates[0]["email"], "hunter", "api_domain_search", website, candidates
            except Exception as exc:
                self._provider_status["hunter"]["status"] = ProviderStatus.TEMPORARILY_UNAVAILABLE
                self._provider_status["hunter"]["last_error"] = str(exc)

        # 3. Serper Search snippet (with Two-Key Rotation and Structured Organic Parsing)
        serper_pool = km.get_pool("serper")
        serper_key_legacy = getattr(settings, "SERPER_API_KEY", "")
        if (serper_pool and serper_pool.is_configured() and not serper_pool.shared_quota_exhausted) or (serper_key_legacy and self._provider_status.get("serper", {}).get("status") == ProviderStatus.AVAILABLE):
            attempts = 0
            max_serper_attempts = max(1, len(serper_pool.keys)) if serper_pool and serper_pool.keys else 1
            while attempts < max_serper_attempts:
                attempts += 1
                if serper_pool and serper_pool.is_configured():
                    key_item = await serper_pool.get_next_key()
                    if not key_item:
                        break
                    prov_key, _ = key_item
                    current_key = prov_key.secret
                else:
                    prov_key = None
                    current_key = serper_key_legacy

                try:
                    url = "https://google.serper.dev/search"
                    payload = {"q": f'"{name}" {city} email OR contact'}
                    headers = {"X-API-KEY": current_key, "Content-Type": "application/json"}
                    async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                        err_text = ""
                        if resp.status != 200:
                            err_text = await _extract_resp_text(resp)
                        is_quota = (resp.status == 402) or any(
                            q in err_text.lower() for q in ("insufficient_quota", "not enough credits", "quota", "credit")
                        )
                        if prov_key and serper_pool:
                            serper_pool.report_result(
                                prov_key,
                                resp.status,
                                error_message=err_text,
                                quota_exhausted=is_quota,
                            )
                        if resp.status == 200:
                            data = await resp.json()
                            for org in data.get("organic", []):
                                org_link = org.get("link", "")
                                org_snippet = org.get("snippet", "")
                                org_title = org.get("title", "")
                                combined_text = f"{org_title} {org_snippet}"
                                found_in_org = extract_email(combined_text)
                                if found_in_org:
                                    eff_web = website if (website and not is_third_party_directory_or_aggregator(website)) else ""
                                    st, reas, send = classify_email_association(
                                        found_in_org,
                                        name,
                                        website_url=eff_web,
                                        source_type="api_search_snippet",
                                        context_text=org_snippet,
                                        location=city,
                                    )
                                    candidates.append({
                                        "email": found_in_org,
                                        "email_domain": extract_email_domain(found_in_org),
                                        "source_type": "serper",
                                        "extraction_method": "api_search_snippet",
                                        "source_url": org_link,
                                        "association_status": st.value,
                                        "association_reason": reas,
                                        "is_sendable": send,
                                    })
                            if candidates:
                                candidates.sort(
                                    key=lambda x: 0 if x["association_status"] == EmailAssociationStatus.MATCHED.value else 1
                                )
                                return (
                                    candidates[0]["email"],
                                    "serper",
                                    "api_search_snippet",
                                    candidates[0]["source_url"],
                                    candidates,
                                )
                            break
                        if (resp.status == 401 or (resp.status == 403 and getattr(prov_key, "is_auth_failed", False))) and serper_pool:
                            continue
                        if resp.status == 402 or is_quota:
                            if serper_pool and serper_pool.shared_quota_exhausted:
                                break
                            continue
                        if resp.status == 403 and serper_pool:
                            continue
                except Exception:
                    break

        # 4. DuckDuckGo public HTML search fallback (permitted)
        if self._provider_status.get("duckduckgo_fallback", {}).get("status") == ProviderStatus.AVAILABLE:
            try:
                q = f'"{name}" {city} email contact'
                url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        found = extract_email(await resp.text())
                        if found:
                            st, reas, send = classify_email_association(
                                found, name, website_url=website, source_type="duckduckgo_fallback", location=city
                            )
                            cands = [{
                                "email": found,
                                "email_domain": extract_email_domain(found),
                                "source_type": "duckduckgo_fallback",
                                "extraction_method": "public_search_fallback",
                                "source_url": "",
                                "association_status": st.value,
                                "association_reason": reas,
                                "is_sendable": send,
                            }]
                            return found, "duckduckgo_fallback", "public_search_fallback", "", cands
            except Exception:
                pass

        return None, "none", "none", "", []

    async def enrich_email(
        self,
        session: aiohttp.ClientSession,
        name: str,
        city: str,
        website: str,
        fetcher_mock: Optional[Any] = None,
    ) -> Tuple[Optional[str], str, str]:
        """
        Backward-compatible wrapper for email enrichment.
        Returns: (email, source, method)
        """
        em, src, meth, _, _ = await self.enrich_email_detailed(
            session, name, city, website=website, fetcher_mock=fetcher_mock
        )
        return em, src, meth

    # ─── Secure HTTP Inspection & Contact Page Extraction ─────────────────────

    async def inspect_website_detailed(
        self,
        session: aiohttp.ClientSession,
        website: str,
        business_name: str = "",
        location: str = "",
        html_override: Optional[str] = None,
        status_override: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[str], List[Dict[str, Any]], str]:
        """
        Safely inspect website with SSRF protection, strict TLS verification,
        outdated design diagnostics, context-aware email candidate extraction,
        and /contact page discovery.
        Returns: (is_target, classification_reason, primary_email, email_candidates, final_url)
        """
        if not website:
            return True, "No Website", None, [], ""

        safe, reason = is_safe_external_url(website, allow_test_loopback=self.allow_test_loopback)
        if not safe:
            return True, f"Blocked Target URL ({reason})", None, [], website

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        final_url = website
        if html_override is not None:
            html = html_override
            status = status_override or 200
        else:
            try:
                async with session.get(
                    website,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                    ssl=True,
                ) as resp:
                    status = resp.status
                    final_url = str(resp.url)
                    safe_dest, dest_reason = is_safe_external_url(
                        final_url, allow_test_loopback=self.allow_test_loopback
                    )
                    if not safe_dest:
                        return True, f"Blocked Redirect Target ({dest_reason})", None, [], final_url
                    html = await resp.text(errors="ignore")
            except Exception as exc:
                return True, f"Dead/Unreachable ({type(exc).__name__})", None, [], website

        is_target, class_reason = audit_website_is_old_or_dead(website, html, status, final_url)
        candidates = extract_email_candidates_with_context(
            html, website=final_url, business_name=business_name, location=location, source_type="http_page_scrape"
        )

        has_matched = any(c.get("association_status") == EmailAssociationStatus.MATCHED.value for c in candidates)
        if is_target and not has_matched and status == 200:
            for path in ("/contact", "/contact-us", "/about", "/about-us"):
                target_url = final_url.rstrip("/") + path
                safe_sub, _ = is_safe_external_url(target_url, allow_test_loopback=self.allow_test_loopback)
                if not safe_sub:
                    continue
                try:
                    async with session.get(target_url, headers=headers, timeout=10, ssl=True) as r2:
                        if r2.status < 400:
                            contact_html = await r2.text(errors="ignore")
                            contact_candidates = extract_email_candidates_with_context(
                                contact_html,
                                website=target_url,
                                business_name=business_name,
                                location=location,
                                source_type="http_contact_page",
                            )
                            for cc in contact_candidates:
                                if not any(existing["email"] == cc["email"] for existing in candidates):
                                    candidates.append(cc)
                            if any(c.get("association_status") == EmailAssociationStatus.MATCHED.value for c in candidates):
                                break
                except Exception:
                    pass

        primary_email = candidates[0]["email"] if candidates else None
        return is_target, class_reason, primary_email, candidates, final_url

    async def inspect_website(
        self,
        session: aiohttp.ClientSession,
        website: str,
        html_override: Optional[str] = None,
        status_override: Optional[int] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Safely inspect website with SSRF protection, strict TLS verification,
        outdated design diagnostics, and /contact page discovery.
        Returns: (is_target, classification_reason, extracted_email)
        """
        is_target, class_reason, primary_email, _, _ = await self.inspect_website_detailed(
            session, website, html_override=html_override, status_override=status_override
        )
        return is_target, class_reason, primary_email

    # ─── Job Management & Execution ───────────────────────────────────────────

    def create_job(
        self,
        keywords: List[str],
        locations: List[str],
        mode: str = "uploaded_only",
        budget: Optional[int] = None,
        batch_offset: Optional[int] = 0,
    ) -> Dict[str, Any]:
        """Initialize and persist a new discovery job configuration."""
        import uuid

        combo_info = self.calculate_combinations(
            keywords, locations, mode=mode, custom_budget=budget, batch_offset=batch_offset
        )
        if combo_info["exceeds_safety_limit"]:
            raise ValueError(
                f"Requested search combinations budget ({combo_info['effective_budget']}) exceed maximum safety limit ({combo_info['max_allowed_combinations']}). Adjust keywords, locations, or set a budget limit."
            )

        job_id = f"disc_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        offset = combo_info["batch_offset"]

        job = {
            "job_id": job_id,
            "status": JobStatus.PENDING.value,
            "mode": mode,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "keywords": combo_info["keywords"],
            "locations": combo_info["locations"],
            "total_combinations": combo_info["total_combinations"],
            "effective_budget": combo_info["effective_budget"],
            "batch_offset": offset,
            "batch_start": combo_info["batch_start"],
            "batch_end": combo_info["batch_end"],
            "total_batches": combo_info["total_batches"],
            "current_batch_num": combo_info["current_batch_num"],
            "current_combination_idx": offset,
            "discovered_leads": [],
            "stats": {
                "combinations_searched": 0,
                "businesses_discovered": 0,
                "outdated_or_dead_found": 0,
                "modern_skipped": 0,
                "emails_extracted": 0,
            },
            "provider_statuses": self.get_provider_statuses(),
            "errors": [],
        }

        self._jobs[job_id] = job
        self._save_jobs()
        return job

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._jobs.get(job_id)

    def pause_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        job["status"] = JobStatus.PAUSED.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        job["status"] = JobStatus.CANCELLED.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    def resume_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")
        if job["status"] not in (JobStatus.PAUSED.value, JobStatus.PENDING.value):
            raise ValueError(f"Cannot resume job in {job['status']} state.")
        job["status"] = JobStatus.RUNNING.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()
        return job

    # ─── Background Job Runner ────────────────────────────────────────────────

    async def run_discovery_job(
        self,
        job_id: str,
        places_mock: Optional[Any] = None,
        email_mock: Optional[Any] = None,
        inspect_mock: Optional[Any] = None,
        max_steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute discovery job across keyword/location combinations.
        Supports deterministic testing with mocks and isolated step limits.
        """
        from app.database import AsyncSessionLocal
        from app.models import Lead, LeadStatus, ActivityLog
        from sqlalchemy import select

        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")

        job["status"] = JobStatus.RUNNING.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_jobs()

        keywords = job.get("keywords", [])
        locations = job.get("locations", [])
        budget = job.get("effective_budget", len(keywords) * len(locations))
        batch_offset = job.get("batch_offset", 0)
        idx = job.get("current_combination_idx", batch_offset)

        combos = [(k, l) for k in keywords for l in locations]
        total_combos = min(len(combos), batch_offset + budget)

        steps_run = 0
        async with aiohttp.ClientSession() as session:
            while idx < total_combos:
                if max_steps is not None and steps_run >= max_steps:
                    break

                # Reload in case pause or cancel was requested
                cur_job = self.get_job(job_id)
                if not cur_job or cur_job["status"] in (JobStatus.PAUSED.value, JobStatus.CANCELLED.value):
                    break

                kw, loc = combos[idx]
                try:
                    places, places_src, places_method = await self.search_places(
                        session, kw, loc, fetcher_mock=places_mock
                    )
                    cur_job["stats"]["combinations_searched"] += 1
                    cur_job["stats"]["businesses_discovered"] += len(places)

                    for p in places:
                        name = p.get("name", "").strip()
                        website = p.get("website", "").strip()
                        phone = p.get("phone")
                        initial_email = p.get("email")

                        if not name:
                            continue

                        # Isolate lead-specific variables strictly per business
                        lead_source = places_src
                        lead_method = places_method
                        source_url = website or ""
                        website_status = (
                            WebsiteAssociationStatus.VERIFIED_PRIMARY.value
                            if website
                            else WebsiteAssociationStatus.NO_WEBSITE.value
                        )
                        website_candidates_list: List[Dict[str, Any]] = []
                        email_candidates_list: List[Dict[str, Any]] = []

                        # Record initial email if provided in places payload
                        if initial_email:
                            st, reas, send = classify_email_association(
                                initial_email, name, website, source_type="places_payload", location=loc
                            )
                            email_candidates_list.append({
                                "email": initial_email,
                                "email_domain": extract_email_domain(initial_email),
                                "source_type": "places_payload",
                                "extraction_method": "places_api",
                                "source_url": website or "",
                                "association_status": st.value,
                                "association_reason": reas,
                                "is_sendable": send,
                            })

                        # If website is a third-party directory, demote it to provenance evidence and clear website
                        if website and is_third_party_directory_or_aggregator(website):
                            if not source_url:
                                source_url = website
                            website = ""
                            website_status = WebsiteAssociationStatus.NO_WEBSITE.value

                        # If website is missing, discover candidates instead of immediately declaring "No Website"
                        if not website:
                            discovered_sites = await self.search_candidate_websites(session, name, loc)
                            if discovered_sites:
                                website_candidates_list = discovered_sites
                                top_site = discovered_sites[0]
                                if top_site.get("score", 0.0) >= 0.5:
                                    if (
                                        len(discovered_sites) > 1
                                        and abs(discovered_sites[0].get("score", 0.0) - discovered_sites[1].get("score", 0.0)) < 0.1
                                        and discovered_sites[1].get("score", 0.0) >= 0.5
                                    ):
                                        website_status = WebsiteAssociationStatus.CONFLICTING.value
                                        website = top_site.get("url", "")
                                    else:
                                        website = top_site.get("url", "")
                                        website_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                                else:
                                    website_status = WebsiteAssociationStatus.UNVERIFIED_SEARCH.value
                            else:
                                website_status = WebsiteAssociationStatus.NO_WEBSITE.value

                        # Inspect site
                        if inspect_mock is not None:
                            is_target, class_reason, scraped_email = inspect_mock(website)
                            site_candidates: List[Dict[str, Any]] = []
                            if scraped_email:
                                st, reas, send = classify_email_association(
                                    scraped_email, name, website, source_type="http_page_scrape", location=loc
                                )
                                site_candidates.append({
                                    "email": scraped_email,
                                    "email_domain": extract_email_domain(scraped_email),
                                    "source_type": "http_page_scrape",
                                    "extraction_method": "http_page_scrape",
                                    "source_url": website or "",
                                    "association_status": st.value,
                                    "association_reason": reas,
                                    "is_sendable": send,
                                })
                        else:
                            is_target, class_reason, scraped_email, site_candidates, final_web_url = (
                                await self.inspect_website_detailed(
                                    session, website, business_name=name, location=loc
                                )
                            )
                            if final_web_url and not website:
                                website = final_web_url

                        if not is_target:
                            cur_job["stats"]["modern_skipped"] += 1
                            continue

                        cur_job["stats"]["outdated_or_dead_found"] += 1
                        site_class = (
                            "outdated_website"
                            if "Outdated" in class_reason
                            else ("dead_website" if "Dead" in class_reason else "no_website")
                        )

                        # Accumulate site email candidates
                        for sc in site_candidates:
                            if not any(ec["email"] == sc["email"] for ec in email_candidates_list):
                                email_candidates_list.append(sc)

                        email_addr: Optional[str] = initial_email
                        if initial_email:
                            lead_source = places_src
                            lead_method = places_method

                        # Select from site candidates if no initial email (prefer matched)
                        if not email_addr and site_candidates:
                            matched_sc = next(
                                (c for c in site_candidates if c.get("association_status") == EmailAssociationStatus.MATCHED.value),
                                None
                            )
                            chosen = matched_sc or site_candidates[0]
                            email_addr = chosen["email"]
                            lead_source = chosen.get("source_type", "http_contact_page")
                            lead_method = chosen.get("extraction_method", "http_page_scrape")
                            source_url = chosen.get("source_url", website)

                        # If still no email, enrich via Hunter / Serper / DuckDuckGo
                        if not email_addr:
                            enriched_email, enrich_src, enrich_method, enrich_url, enrich_cands = (
                                await self.enrich_email_detailed(
                                    session, name, loc, website=website, fetcher_mock=email_mock
                                )
                            )
                            for ec in enrich_cands:
                                if not any(existing["email"] == ec["email"] for existing in email_candidates_list):
                                    email_candidates_list.append(ec)

                            if enriched_email:
                                email_addr = enriched_email
                                lead_source = enrich_src
                                lead_method = enrich_method
                                source_url = enrich_url

                        if email_addr:
                            cur_job["stats"]["emails_extracted"] += 1
                            email_dom = extract_email_domain(email_addr)

                            # Candidate website discovery from custom email domain:
                            # If no verified primary website is confirmed, investigate custom domain
                            if (
                                (not website or website_status in (
                                    WebsiteAssociationStatus.NO_WEBSITE.value,
                                    WebsiteAssociationStatus.UNVERIFIED_SEARCH.value,
                                    WebsiteAssociationStatus.INCONCLUSIVE.value,
                                ))
                                and is_custom_email_domain(email_dom)
                            ):
                                disc_url, disc_st, disc_reas, tested_cands = await self.discover_website_from_email_domain(
                                    session, email_dom, business_name=name, location=loc, fetcher_mock=inspect_mock
                                )
                                for tc in tested_cands:
                                    if not any(existing.get("url") == tc.get("url") for existing in website_candidates_list):
                                        website_candidates_list.append(tc)

                                if disc_url:
                                    website = disc_url
                                    website_status = disc_st.value
                                    if inspect_mock is not None:
                                        is_target, class_reason, _ = inspect_mock(website)
                                    else:
                                        is_target, class_reason, _ = await self.inspect_website(session, website)
                                    site_class = (
                                        "outdated_website"
                                        if "Outdated" in class_reason
                                        else ("dead_website" if "Dead" in class_reason else "no_website")
                                    )
                                elif disc_st == WebsiteAssociationStatus.INCONCLUSIVE:
                                    website_status = WebsiteAssociationStatus.INCONCLUSIVE.value
                                    inferred_cand = infer_website_candidate_from_email(email_addr)
                                    if inferred_cand and not website:
                                        website = inferred_cand
                                        website_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                                elif disc_st == WebsiteAssociationStatus.NO_WEBSITE:
                                    website_status = WebsiteAssociationStatus.NO_WEBSITE.value
                            elif not website:
                                inferred_cand = infer_website_candidate_from_email(email_addr)
                                if inferred_cand:
                                    website = inferred_cand
                                    website_status = WebsiteAssociationStatus.CANDIDATE_MATCH.value
                                    cand_dom = extract_domain_from_url(inferred_cand)
                                    if not any(existing.get("url") == inferred_cand for existing in website_candidates_list):
                                        website_candidates_list.append({
                                            "url": inferred_cand,
                                            "domain": cand_dom,
                                            "source": "email_domain_inferred",
                                            "status": "candidate_match",
                                        })

                            primary_candidate = next(
                                (c for c in email_candidates_list if c["email"] == email_addr),
                                None
                            )
                            if primary_candidate and not website:
                                assoc_status = primary_candidate.get(
                                    "association_status", EmailAssociationStatus.UNVERIFIED_ASSOCIATION.value
                                )
                                assoc_reason = primary_candidate.get("association_reason", "")
                                is_sendable = primary_candidate.get("is_sendable", False)
                            else:
                                st_enum, assoc_reason, is_sendable = classify_email_association(
                                    email_addr,
                                    name,
                                    website,
                                    source_type=lead_source,
                                    location=loc,
                                    website_association_status=website_status,
                                )
                                assoc_status = st_enum.value

                            # Only quarantine for authoritative safety violations (e.g. agency credit mismatch or invalid syntax)
                            # Free email providers or unverified associations are pending review, not quarantined
                            is_quarantined = assoc_status in (
                                EmailAssociationStatus.MISMATCHED_SOURCE.value,
                                EmailAssociationStatus.INVALID_FORMAT.value,
                            )
                            quarantine_reason = assoc_reason if is_quarantined else None

                            email_dom = extract_email_domain(email_addr)
                            web_dom = extract_domain_from_url(website)
                            domain_match = (email_dom == web_dom) if (email_dom and web_dom) else False

                            lead_record = {
                                "business_name": name,
                                "email": email_addr,
                                "phone": phone or "",
                                "website": website or "",
                                "source": lead_source,
                                "extraction_method": lead_method,
                                "site_classification": site_class,
                                "site_classification_reason": class_reason,
                                "observed_at": datetime.now(timezone.utc).isoformat(),
                                "verification_status": "verified" if is_sendable else "candidate",
                                "email_source_url": source_url,
                                "email_source_type": lead_source,
                                "email_extraction_method": lead_method,
                                "email_domain": email_dom,
                                "website_domain": web_dom,
                                "email_domain_match": domain_match,
                                "email_business_association_status": assoc_status,
                                "email_association_reason": assoc_reason,
                                "website_association_status": website_status,
                                "website_candidates": website_candidates_list,
                                "email_candidates": email_candidates_list,
                                "is_quarantined": is_quarantined,
                                "quarantine_reason": quarantine_reason,
                            }

                            # Deduplicate inside this job
                            existing_emails = {
                                l["email"].lower() for l in cur_job["discovered_leads"]
                            }
                            if email_addr.lower() not in existing_emails:
                                cur_job["discovered_leads"].append(lead_record)

                                # Persist to DB leads table
                                try:
                                    async with AsyncSessionLocal() as db:
                                        db_existing = await db.execute(
                                            select(Lead).where(Lead.email == email_addr)
                                        )
                                        existing_lead = db_existing.scalar_one_or_none()
                                        if not existing_lead:
                                            new_lead = Lead(
                                                business_name=name,
                                                email=email_addr,
                                                phone=phone or None,
                                                website=website or "",
                                                status=LeadStatus.new,
                                                email_source_url=source_url,
                                                email_source_type=lead_source,
                                                email_extraction_method=lead_method,
                                                email_domain=email_dom,
                                                website_domain=web_dom,
                                                email_domain_match=domain_match,
                                                email_business_association_status=assoc_status,
                                                email_association_reason=assoc_reason,
                                                website_association_status=website_status,
                                                website_candidates=website_candidates_list,
                                                email_candidates=email_candidates_list,
                                                is_quarantined=is_quarantined,
                                                quarantine_reason=quarantine_reason,
                                            )
                                            db.add(new_lead)
                                            log_entry = ActivityLog(
                                                event_type="lead_discovered",
                                                lead_id=new_lead.id,
                                                message=(
                                                    f"Discovered lead '{name}' ({email_addr}) via {lead_source} "
                                                    f"[{site_class}: {class_reason}] - Association: {assoc_status} "
                                                    f"(Quarantined: {is_quarantined})"
                                                ),
                                            )
                                            db.add(log_entry)
                                            await db.commit()
                                        else:
                                            # Update existing lead safely without overwriting verified data or clearing quarantine
                                            if not existing_lead.website and website:
                                                existing_lead.website = website
                                                existing_lead.website_domain = web_dom
                                                existing_lead.website_association_status = website_status
                                            if website_candidates_list:
                                                existing_wc = existing_lead.website_candidates or []
                                                for wc in website_candidates_list:
                                                    if not any(c.get("url") == wc.get("url") for c in existing_wc):
                                                        existing_wc.append(wc)
                                                existing_lead.website_candidates = existing_wc
                                            if email_candidates_list:
                                                existing_cands = existing_lead.email_candidates or []
                                                for ec in email_candidates_list:
                                                    if not any(c.get("email") == ec.get("email") for c in existing_cands):
                                                        existing_cands.append(ec)
                                                existing_lead.email_candidates = existing_cands
                                            await db.commit()
                                except Exception as db_exc:
                                    logger.warning("Could not persist discovered lead to DB: %s", db_exc)

                except Exception as loop_exc:
                    cur_job["errors"].append(f"Combo '{kw}' in '{loc}' failed: {loop_exc}")

                idx += 1
                steps_run += 1
                cur_job["current_combination_idx"] = idx
                cur_job["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save_jobs()
                await asyncio.sleep(0.01)

            final_job = self.get_job(job_id)
            if final_job and final_job["status"] == JobStatus.RUNNING.value and final_job["current_combination_idx"] >= total_combos:
                final_job["status"] = JobStatus.COMPLETED.value
                final_job["completed_at"] = datetime.now(timezone.utc).isoformat()
                self._save_jobs()

        return self.get_job(job_id) or {}

    # ─── Export to CSV ────────────────────────────────────────────────────────

    def export_leads_csv(
        self, job_id: str, format_type: str = "leadgen", sendable_only: bool = False
    ) -> str:
        """
        Export discovered leads for a job to CSV string.
        Format options: 'leadgen' (full schema) or 'simple' (3 columns: business name, email, website).
        If sendable_only=True, excludes quarantined and unverified leads.
        """
        job = self.get_job(job_id)
        if not job:
            raise KeyError("Job not found")

        output = io.StringIO()
        raw_leads = job.get("discovered_leads", [])
        if sendable_only:
            leads = [
                l for l in raw_leads
                if not l.get("is_quarantined", False)
                and l.get("email_business_association_status") in ("matched", "approved")
                and l.get("verification_status") != "candidate"
                and l.get("email_verification_status") == "valid"
            ]
        else:
            leads = raw_leads

        if format_type == "simple":
            fieldnames = ["business name", "email", "website"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for l in leads:
                writer.writerow({
                    "business name": l.get("business_name", ""),
                    "email": l.get("email", ""),
                    "website": l.get("website", ""),
                })
        else:
            fieldnames = [
                "business_name", "email", "phone", "website", "status",
                "source", "extraction_method", "site_classification",
                "site_classification_reason", "observed_at",
                "email_source_url", "email_source_type", "email_extraction_method",
                "email_domain", "website_domain", "email_domain_match",
                "email_business_association_status", "email_association_reason",
                "website_association_status", "is_quarantined", "quarantine_reason",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for l in leads:
                writer.writerow({
                    "business_name": l.get("business_name", ""),
                    "email": l.get("email", ""),
                    "phone": l.get("phone", ""),
                    "website": l.get("website", ""),
                    "status": "new",
                    "source": l.get("source", "lead_discovery"),
                    "extraction_method": l.get("extraction_method", "unknown"),
                    "site_classification": l.get("site_classification", ""),
                    "site_classification_reason": l.get("site_classification_reason", ""),
                    "observed_at": l.get("observed_at", ""),
                    "email_source_url": l.get("email_source_url", ""),
                    "email_source_type": l.get("email_source_type", ""),
                    "email_extraction_method": l.get("email_extraction_method", ""),
                    "email_domain": l.get("email_domain", ""),
                    "website_domain": l.get("website_domain", ""),
                    "email_domain_match": l.get("email_domain_match", ""),
                    "email_business_association_status": l.get("email_business_association_status", ""),
                    "email_association_reason": l.get("email_association_reason", ""),
                    "website_association_status": l.get("website_association_status", ""),
                    "is_quarantined": l.get("is_quarantined", False),
                    "quarantine_reason": l.get("quarantine_reason", ""),
                })

        return output.getvalue()


# Module-level singleton
lead_discovery_service = LeadDiscoveryService()
