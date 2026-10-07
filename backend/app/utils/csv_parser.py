import io
import csv
import re
from typing import List, Dict


def clean_website(url: str) -> str:
    """
    Normalise a website URL to its root (scheme + domain + trailing slash).

    Examples
    --------
    https://balanicustom.com/custom-suits-indianapolis  →  https://balanicustom.com/
    balanicustom.com/custom-suits                       →  https://balanicustom.com/
    https://www.example.com                             →  https://www.example.com/
    """
    from urllib.parse import urlparse, urlunparse

    url = url.strip()
    if not url:
        return url

    # Add scheme if missing so urlparse works correctly
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    # Rebuild with only scheme + netloc; drop path, params, query, fragment
    root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
    return root


def clean_business_name(name: str) -> str:
    """
    Strip everything from the first '-' or '|' separator onwards.

    Examples
    --------
    Bigmen Stout Men's Shop - Bigmen.com, Inc  →  Bigmen Stout Men's Shop
    Joe's Tailor | Est. 1992                   →  Joe's Tailor
    Plain Name                                 →  Plain Name
    """
    name = name.strip()
    if not name:
        return name

    # Find the earliest position of either separator
    dash_pos = name.find(" - ")
    pipe_pos = name.find(" | ")

    # Collect only the positions that exist (>= 0)
    cuts = [p for p in (dash_pos, pipe_pos) if p >= 0]
    if cuts:
        name = name[: min(cuts)]

    return name.strip()


def clean_phone(phone: str) -> str:
    """Strip non-digit chars, keep + for international."""
    if not phone:
        return ""
    cleaned = re.sub(r"[^\d+\-\s()]", "", phone.strip())
    return cleaned


def parse_and_clean_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parse CSV bytes. Expected columns (case-insensitive):
      business_name / business name / name
      email
      phone / phone_number
      website / url / site
    Returns list of cleaned row dicts ready for DB insertion.
    """
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    # Normalise header names
    column_map = {}
    for field in (reader.fieldnames or []):
        key = field.strip().lower().replace(" ", "_")
        column_map[field] = key

    rows: List[Dict[str, str]] = []
    seen_emails: set = set()

    for raw_row in reader:
        row: Dict[str, str] = {column_map[k]: (v or "").strip() for k, v in raw_row.items()}

        # Map flexible column names to canonical ones
        business_name = (
            row.get("business_name")
            or row.get("business")
            or row.get("name")
            or row.get("company")
            or row.get("company_name")
            or ""
        )
        email = (
            row.get("email")
            or row.get("email_address")
            or row.get("e-mail")
            or ""
        )
        phone = (
            row.get("phone")
            or row.get("phone_number")
            or row.get("mobile")
            or row.get("contact")
            or ""
        )
        website = (
            row.get("website")
            or row.get("url")
            or row.get("site")
            or row.get("web")
            or ""
        )

        # Skip rows without email or website
        if not email or not website:
            continue

        # Basic email validation
        email = email.lower()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            continue

        # Deduplicate by email
        if email in seen_emails:
            continue
        seen_emails.add(email)

        rows.append({
            "business_name": clean_business_name(
                business_name or email.split("@")[0].replace(".", " ").title()
            ),
            "email": email,
            "phone": clean_phone(phone),
            "website": clean_website(website),
        })

    return rows
