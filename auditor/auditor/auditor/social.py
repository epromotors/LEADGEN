# auditor/social.py — Social profiles, WhatsApp, Contact links
# Distinguishes verified presence from access-restricted profiles,
# and treats missing optional platforms (e.g. Pinterest/Facebook) as strategy observations.

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from auditor.core import result_pass, result_warn, result_fail, fetch_page
from config import SOCIAL_PLATFORMS


def audit_social_links(soup, url=None, session=None) -> dict:
    """
    Detect presence and configuration of social media profile links on homepage or contact page.
    Missing optional platforms (such as Facebook or Pinterest for B2B) are presented as business-presence
    observations rather than technical SEO errors.
    """
    all_hrefs: list[str] = [
        a.get("href", "").strip().lower()
        for a in soup.find_all("a", href=True)
    ]

    # Check contact page if available
    contact_url = None
    if url and session:
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True).lower()
            href = a.get("href", "").lower()
            if "contact" in text or "contact" in href:
                contact_url = urllib.parse.urljoin(url, a["href"]).split("#")[0]
                break

        if contact_url and contact_url.rstrip("/") != url.rstrip("/"):
            try:
                contact_page = fetch_page(contact_url, session)
                if contact_page.get("ok") and contact_page.get("soup"):
                    all_hrefs.extend([
                        a.get("href", "").strip().lower()
                        for a in contact_page["soup"].find_all("a", href=True)
                    ])
            except Exception:
                pass

    found: list[str] = []
    missing: list[str] = []

    for platform, patterns in SOCIAL_PLATFORMS.items():
        detected = any(
            any(p in href for p in patterns)
            for href in all_hrefs
        )
        if detected:
            found.append(platform)
        else:
            missing.append(platform)

    # Classification and reporting
    if not missing:
        return result_pass(
            f"All major social profiles linked: {', '.join(found)}",
            detail="Comprehensive social profile presence strengthens E-E-A-T and entity verification.",
            value=0,
            unit="missing profiles",
        )

    # If key professional or multiple active platforms are linked (e.g. LinkedIn, Twitter, Instagram)
    if len(found) >= 2 or "LinkedIn" in found:
        return result_pass(
            f"Active business profiles linked: {', '.join(found)}.",
            detail=(
                f"Core profiles verified. Optional platforms not linked: {', '.join(missing)}. "
                "Add only if active and aligned with your client target audience."
            ),
            value=0,
            unit="missing profiles",
        )

    if len(found) == 1:
        return result_warn(
            f"Single social profile detected ({found[0]}).",
            f"Consider expanding social channels if relevant to your market. Not linked: {', '.join(missing)}.",
            f"Detected: {found[0]}",
            value=len(missing),
            unit="missing profiles",
        )

    return result_warn(
        "No major social profile links found on the website.",
        "Add links to your active social profiles in the header or footer. "
        "Social presence supports Google E-E-A-T entity reconciliation.",
        f"Unlinked platforms: {', '.join(missing)}",
        value=len(missing),
        unit="missing profiles",
    )


def audit_contact_links(soup) -> dict:
    """Check for clickable phone/email plus practical contact alternatives."""
    all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    page_text = soup.get_text(" ", strip=True)
    page_text_lower = page_text.lower()

    has_tel = any(h.startswith("tel:") for h in all_hrefs)
    has_mailto = any(h.startswith("mailto:") for h in all_hrefs)
    has_visible_phone = bool(re.search(
        r"(\+\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}",
        page_text,
    ))
    has_visible_email = bool(re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        page_text,
        re.IGNORECASE,
    ))
    has_contact_page = any(
        "contact" in (a.get_text(" ", strip=True).lower() + " " + a.get("href", "").lower())
        for a in soup.find_all("a", href=True)
    )
    has_contact_form = bool(
        soup.find("form")
        and (
            soup.find("input", attrs={"type": "email"})
            or soup.find("textarea")
            or "quick email" in page_text_lower
            or "send message" in page_text_lower
        )
    )

    tel_link = next((h for h in all_hrefs if h.startswith("tel:")), None)
    mail_link = next((h for h in all_hrefs if h.startswith("mailto:")), None)

    has_phone_channel = has_tel or has_visible_phone
    has_email_channel = has_mailto or has_visible_email or has_contact_form or has_contact_page

    if has_phone_channel and has_email_channel:
        details = []
        if tel_link:
            details.append(f"Phone: {tel_link}")
        elif has_visible_phone:
            details.append("Phone number visible")
        if mail_link:
            details.append(f"Email: {mail_link}")
        elif has_contact_form:
            details.append("Contact form found")
        elif has_contact_page:
            details.append("Contact page found")
        return result_pass(
            "Phone and email/contact enquiry paths found.",
            detail=" | ".join(details),
        )

    missing = []
    fixes = []
    if not has_phone_channel:
        missing.append("phone")
        fixes.append("<a href='tel:+1234567890'>Call Us</a>")
    elif not has_tel:
        missing.append("clickable phone (tel:)")
        fixes.append("Wrap visible phone number in a tel: link for mobile visitors.")

    if not has_email_channel:
        missing.append("email/contact form")
        fixes.append("<a href='mailto:info@yoursite.com'>Email Us</a> or add a contact form")
    elif not has_mailto and not has_contact_form:
        missing.append("direct email/form")
        fixes.append("Add a mailto: link or short enquiry form on the contact page.")

    if not has_phone_channel and not has_email_channel:
        return result_fail(
            "No clear phone or email/contact enquiry path found.",
            "Add tap-to-call and tap-to-email links. Mobile users cannot type numbers easily.\n" + "\n".join(fixes),
        )

    return result_warn(
        f"Missing contact link types: {', '.join(missing)}",
        f"Add: {' | '.join(fixes)}",
    )


def audit_whatsapp(soup) -> dict:
    """Check for WhatsApp integration (wa.me or WhatsApp widget)."""
    html_lower = str(soup).lower()

    has_wa_link = "wa.me/" in html_lower or "api.whatsapp.com/" in html_lower
    has_wa_widget = (
        "whatsapp" in html_lower
        and ("chat" in html_lower or "widget" in html_lower or "float" in html_lower)
    )
    has_wa_mention = "whatsapp" in html_lower

    if has_wa_link:
        return result_pass(
            "WhatsApp link (wa.me) found on the page.",
            detail="WhatsApp direct chat channel is active for visitors.",
        )

    if has_wa_widget or has_wa_mention:
        return result_warn(
            "WhatsApp is mentioned but no direct wa.me link found.",
            "Add a direct WhatsApp link: <a href='https://wa.me/1234567890'>Chat on WhatsApp</a>.",
        )

    return result_warn(
        "No WhatsApp integration found (optional communication channel).",
        "Consider adding a WhatsApp click-to-chat link if useful for direct customer communication. "
        "Optional presence observation.",
        detail="WhatsApp is an optional direct-messaging channel for service businesses.",
    )
