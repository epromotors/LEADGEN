# auditor/social.py - Social profiles, WhatsApp, Contact links

import re
import urllib.parse

from auditor.core import result_pass, result_warn, result_fail, fetch_page
from config import SOCIAL_PLATFORMS


def audit_social_links(soup, url=None, session=None) -> dict:
    """Detect presence of major social media profile links on homepage or contact page."""
    all_hrefs = [
        a.get("href", "").lower()
        for a in soup.find_all("a", href=True)
    ]

    # Try fetching contact page if session and url are provided
    contact_url = None
    if url and session:
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True).lower()
            href = a.get("href", "").lower()
            if "contact" in text or "contact" in href:
                contact_url = urllib.parse.urljoin(url, a["href"]).split("#")[0]
                break
                
        if contact_url and contact_url.rstrip("/") != url.rstrip("/"):
            contact_page = fetch_page(contact_url, session)
            if contact_page["ok"] and contact_page["soup"]:
                all_hrefs.extend([
                    a.get("href", "").lower()
                    for a in contact_page["soup"].find_all("a", href=True)
                ])

    found = []
    missing = []

    for platform, patterns in SOCIAL_PLATFORMS.items():
        detected = any(
            any(p in href for p in patterns)
            for href in all_hrefs
        )
        if detected:
            found.append(platform)
        else:
            missing.append(platform)

    if not missing:
        return result_pass(
            f"All major social profiles linked: {', '.join(found)}",
            detail="Social links boost E-E-A-T (Experience, Expertise, Authoritativeness, Trust).",
        )

    if len(missing) >= len(SOCIAL_PLATFORMS) - 1:
        return result_fail(
            f"Social media links are almost entirely missing. Only found: {', '.join(found) or 'none'}.",
            "Add links to your active social profiles in the header or footer. "
            "Social presence is an E-E-A-T trust signal for Google. "
            f"Missing: {', '.join(missing)}",
        )

    return result_warn(
        f"Some social links missing: {', '.join(missing)}",
        f"Add missing social profile links. Found: {', '.join(found)}",
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
        fixes.append("Wrap the visible phone number in a tel: link for mobile visitors.")

    if not has_email_channel:
        missing.append("email/contact form")
        fixes.append("<a href='mailto:info@yoursite.com'>Email Us</a> or add a contact form")
    elif not has_mailto and not has_contact_form:
        missing.append("direct email/form")
        fixes.append("Add a mailto: link or short enquiry form on the contact page.")

    if not has_phone_channel and not has_email_channel:
        return result_fail(
            "No clear phone or email/contact enquiry path found.",
            "Add tap-to-call and tap-to-email links. Mobile users cannot type numbers easily. "
            "They tap. Missing this loses you direct enquiries.\n" + "\n".join(fixes),
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
            detail="WhatsApp integration is active. Ensure it is visible on mobile.",
        )

    if has_wa_widget or has_wa_mention:
        return result_warn(
            "WhatsApp is mentioned but no direct wa.me link found.",
            "Add a direct WhatsApp link: <a href='https://wa.me/1234567890'>Chat on WhatsApp</a>. "
            "For a floating button, use: https://wa.me/yournumber?text=Hello",
        )

    return result_warn(
        "No WhatsApp integration found.",
        "Add a WhatsApp click-to-chat link or floating button. "
        "WhatsApp is a direct sales channel for local service businesses. "
        "Add: <a href='https://wa.me/YOURPHONE'>WhatsApp Us</a> in your header/footer. "
        "For a floating widget: wati.io or elfsight.com offer free plans.",
    )
