# auditor/email_finder.py — Domain-Matched Email Extractor
# Scrapes homepage + contact page to find emails belonging to the site's own domain.
# Free/generic email providers (gmail, yahoo, hotmail, etc.) are ignored.
# Used by audit_engine.py to auto-correct email addresses captured by scrapers.

from __future__ import annotations

import re
import logging
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

# ── Free / generic email providers to ignore ─────────────────────────────────
FREE_EMAIL_PROVIDERS = {
    # Big global providers
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.co.uk", "yahoo.es", "yahoo.fr", "yahoo.de",
    "yahoo.it", "yahoo.com.br", "yahoo.com.au", "yahoo.ca",
    "hotmail.com", "hotmail.co.uk", "hotmail.es", "hotmail.fr",
    "hotmail.de", "hotmail.it",
    "outlook.com", "outlook.es", "outlook.fr",
    "live.com", "live.co.uk", "live.es",
    "msn.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "protonmail.com", "proton.me",
    "tutanota.com",
    "mail.com",
    "zoho.com",
    # Site builders / hosting providers (not the business itself)
    "webador.com", "wix.com", "weebly.com", "squarespace.com",
    "godaddy.com", "hostinger.com", "bluehost.com", "siteground.com",
    "ionos.com", "1and1.com", "namecheap.com",
    "wordpress.com", "shopify.com",
}

# Regex to find all email addresses in text / HTML
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# File extensions that are NEVER valid email TLDs.
# These appear in Shopify/WordPress image CDN filenames like logo@2x.jpg
_MEDIA_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "bmp", "tiff",
    "heic", "heif", "avif",
    "mp4", "mp3", "mov", "avi", "webm", "ogg",
    "pdf", "zip", "gz", "tar", "rar",
    "css", "js", "json", "xml", "txt", "csv",
    "woff", "woff2", "ttf", "otf", "eot",
}


def _get_site_domain(website_url: str) -> str:
    """Return the registered domain without www, e.g. 'vertexindustries.es'."""
    parsed = urlparse(website_url)
    host = parsed.netloc or parsed.path
    return host.lower().lstrip("www.")


def _is_domain_email(email: str, site_domain: str) -> bool:
    """True if the email belongs to the site's own domain (not a free provider)."""
    email_lower = email.lower()
    if "@" not in email_lower:
        return False
    email_domain = email_lower.split("@", 1)[1]

    # Reject filenames like logo@2x.jpg, banner@2x.heic — the "TLD" is a media extension
    tld = email_domain.rsplit(".", 1)[-1] if "." in email_domain else ""
    if tld in _MEDIA_EXTENSIONS:
        return False

    # Reject if the local-part (before @) looks like a CDN image variant suffix
    # e.g.  "logo_150x@2x" — numeric/dimension suffix before @
    local_part = email_lower.split("@", 1)[0]
    if re.search(r"[\d]+x$|@\d+x|_\d+x\d*$", local_part):
        return False

    # Must match the site domain (or a subdomain of it)
    if not (email_domain == site_domain or email_domain.endswith("." + site_domain)):
        return False
    # Must not be a free / builder provider
    if email_domain in FREE_EMAIL_PROVIDERS:
        return False
    return True


def _extract_emails_from_html(html: str, site_domain: str) -> list[str]:
    """Find all domain-matched emails in raw HTML text."""
    candidates = _EMAIL_RE.findall(html)
    seen: set[str] = set()
    result: list[str] = []
    for email in candidates:
        el = email.lower()
        if el not in seen and _is_domain_email(el, site_domain):
            seen.add(el)
            result.append(el)
    return result


def _extract_mailto_emails(soup, site_domain: str) -> list[str]:
    """Extract emails from mailto: href attributes (highest priority — explicitly shown)."""
    result: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            raw = href[7:].split("?")[0].strip()
            el = raw.lower()
            if el not in seen and _is_domain_email(el, site_domain):
                seen.add(el)
                result.append(el)
    return result


def _find_contact_page_url(soup, base_url: str) -> str | None:
    """Try to locate a contact/about page URL from navigation links."""
    keywords = ["contact", "contacto", "kontakt", "kontakt",
                 "about", "sobre", "impressum", "reachout"]
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        text = a.get_text(strip=True).lower()
        if any(k in href or k in text for k in keywords):
            full = urljoin(base_url, a["href"])
            # Stay on same domain
            if urlparse(full).netloc == urlparse(base_url).netloc:
                return full
    return None


def find_domain_email(
    website_url: str,
    homepage_soup,
    homepage_html: str,
    session,
) -> tuple[str | None, str]:
    """
    Try to find a domain-matched email for the given website.

    Search order (highest-confidence first):
      1. mailto: links on the homepage
      2. Raw email addresses in homepage HTML
      3. mailto: links on the contact page
      4. Raw email addresses in contact page HTML

    Args:
        website_url:   The canonical URL being audited, e.g. 'https://www.vertexindustries.es'
        homepage_soup: BeautifulSoup object of the homepage
        homepage_html: Raw HTML string of the homepage
        session:       requests.Session (already configured by make_session())

    Returns:
        (email, source)  where source is one of:
            'homepage_mailto', 'homepage_text',
            'contact_mailto', 'contact_text', 'not_found'
    """
    from auditor.core import fetch_page  # import inside to avoid circular

    site_domain = _get_site_domain(website_url)
    if not site_domain:
        return None, "not_found"

    # ── Priority 1: mailto: links on homepage ─────────────────────────────────
    mailto_emails = _extract_mailto_emails(homepage_soup, site_domain)
    if mailto_emails:
        best = _rank_emails(mailto_emails)
        logger.info(f"[email_finder] Found via homepage mailto: {best}")
        return best, "homepage_mailto"

    # ── Priority 2: plain email addresses in homepage HTML ────────────────────
    text_emails = _extract_emails_from_html(homepage_html, site_domain)
    if text_emails:
        best = _rank_emails(text_emails)
        logger.info(f"[email_finder] Found via homepage text: {best}")
        return best, "homepage_text"

    # ── Priority 3 & 4: Try the contact page ─────────────────────────────────
    contact_url = _find_contact_page_url(homepage_soup, website_url)
    if contact_url and contact_url != website_url:
        try:
            contact_page = fetch_page(contact_url, session)
            if contact_page.get("ok"):
                contact_soup = contact_page["soup"]
                contact_html = contact_page["html"]

                # 3a: mailto: on contact page
                contact_mailto = _extract_mailto_emails(contact_soup, site_domain)
                if contact_mailto:
                    best = _rank_emails(contact_mailto)
                    logger.info(f"[email_finder] Found via contact page mailto: {best}")
                    return best, "contact_mailto"

                # 3b: plain text on contact page
                contact_text = _extract_emails_from_html(contact_html, site_domain)
                if contact_text:
                    best = _rank_emails(contact_text)
                    logger.info(f"[email_finder] Found via contact page text: {best}")
                    return best, "contact_text"
        except Exception as exc:
            logger.debug(f"[email_finder] Contact page fetch failed for {contact_url}: {exc}")

    logger.info(f"[email_finder] No domain-matched email found for {site_domain}")
    return None, "not_found"


def _rank_emails(emails: list[str]) -> str:
    """
    Pick the best email from a list.
    Prefer common contact prefixes: info, hello, contact, hola, etc.
    Fall back to the first found.
    """
    preferred_prefixes = [
        "info", "hello", "hola", "contact", "contacto",
        "enquiries", "enquiry", "enquire",
        "sales", "support", "help", "office",
    ]
    for prefix in preferred_prefixes:
        for email in emails:
            if email.split("@")[0] == prefix:
                return email
    return emails[0]


def should_update_email(
    current_email: str,
    found_email: str,
    site_domain: str,
) -> bool:
    """
    Return True if the found email is a better match than the current one.

    Rules:
    - found_email must belong to site_domain
    - current_email must NOT belong to site_domain (i.e. it's from a different domain)
    - If current_email already matches site_domain — no replacement needed
    """
    if not found_email or not current_email:
        return False

    current_domain = current_email.lower().split("@", 1)[-1] if "@" in current_email else ""

    # If the existing email already belongs to the site's domain — leave it alone
    if current_domain == site_domain or current_domain.endswith("." + site_domain):
        return False

    # If the found email belongs to the site domain — it's an upgrade
    found_domain = found_email.lower().split("@", 1)[-1] if "@" in found_email else ""
    return found_domain == site_domain or found_domain.endswith("." + site_domain)
