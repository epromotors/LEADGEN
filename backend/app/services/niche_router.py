"""
backend/app/services/niche_router.py

Niche Classification Engine — maps a lead's business name / category
to exactly one of the 26 niche IDs from templates_all.json.

Rules (from AGENT_GUIDE_all_batches.md, section 3):
- Map each scraped lead to exactly one niche_id.
- Match on business name keywords and source category.
- If no confident match → put lead in review queue, do NOT send.
- A lead has one niche for its lifetime unless a human overrides it.
- Store the matched keyword and confidence with the lead.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Niche keyword table
# Each entry: (niche_id, niche_name, keyword_patterns)
# Patterns are matched case-insensitively against the business name
# and against the scraper category/query string.
# ---------------------------------------------------------------------------

NICHE_KEYWORD_MAP = [
    # ── Batch 1 ──────────────────────────────────────────────────────────
    (1,  "Dental Clinics & Dentists",
     r"dentist|dental|orthodont|endodont|periodont|prosthodont|implant clinic|oral care|tooth|teeth"),
    (2,  "Medical Clinics & Hospitals",
     r"hospital|clinic|medical centre|health centre|polyclinic|nursing home|physician|doctor|multispeciality|maternity|\bent\b|cardio|ortho clinic|gynaecol|gynecol"),
    (3,  "Diagnostic Labs & Pathology Centres",
     r"diagnostic|patholog|lab(oratory)?|scan centre|radiology|imaging|ultrasound centre|x.?ray centre|blood test"),
    (4,  "Pharmacies & Medical Stores",
     r"pharma|chemist|medical store|drug store|medicine shop|dispensary|pharmacy"),
    (5,  "Coaching Institutes & Tuition Centres",
     r"coaching|tuition|tutorial|coaching institute|academy(?! of dance|of music|of art)|institute(?! of technology|of management)|study centre|iit coaching|neet coaching|test prep"),
    (6,  "Schools & Colleges",
     r"school|college|university|vidyalaya|gurukul|montessori|pre.?school|kindergarten|cbse|icse campus|higher secondary|secondary school"),
    (7,  "Gyms & Fitness Centres",
     r"gym|fitness|crossfit|yoga studio|pilates|zumba|aerobics|health club|body building|workout|sports centre"),

    # ── Batch 2 ──────────────────────────────────────────────────────────
    (8,  "Restaurants & Cafes",
     r"restaurant|cafe|coffee shop|diner|eatery|dhaba|bistro|canteen|food joint|tiffin|bakery|pizza|burger|sushi|biryani house|barbeque"),
    (9,  "Hotels & Guesthouses",
     r"hotel|guesthouse|guest house|resort|homestay|inn|lodge|motel|service apartment|b&b|bed and breakfast"),
    (10, "Wedding Planners & Event Managers",
     r"wedding planner|event manager|event management|event organis|event plan|wedding decor|wedding coordinator|banquet hall|event hall"),
    (11, "Travel & Tourism Agencies",
     r"travel agent|travel agenc|tour operator|tourism|holiday package|pilgrimage tour|adventure tour|trip plan|tour agenc|tours & travels|\btravels?\b"),
    (12, "Salons & Spas",
     r"salon|spa|beauty parlour|beauty parlor|hair studio|nail art|unisex salon|beauty salon|hair salon|barber"),
    (13, "Jewellery Stores",
     r"jeweller|jewellery|jewelry|goldsmith|diamond store|ornament|gem store|bangles|bridal jewel"),
    (14, "Clothing & Boutiques",
     r"boutique|clothing store|garments|fashion store|saree shop|kurta|ethnic wear|dress shop|apparel|textile shop"),
    (15, "Grocery & Retail Stores",
     r"grocery|supermarket|kirana|provisions|retail store|general store|mart|departmental store|convenience store"),

    # ── Batch 3 ──────────────────────────────────────────────────────────
    (16, "Real Estate Agents & Property Dealers",
     r"real estate|property dealer|realty|estate agent|land dealer|flat dealer|plot dealer|housing|property consultant|commercial property"),
    (17, "Interior Designers & Architects",
     r"interior design|interior decorator|architect|architecture firm|renovation|home decor studio|space design|home improvement|remodeling|\bcontractor\b|\bcontracting\b|\bconstruction\b|\bbuilders?\b"),
    (18, "Logistics & Freight Companies",
     r"logistics|freight|courier|transport(ation)?|cargo|supply chain|shipping|warehousing|fleet services"),
    (19, "Trading & Manufacturing Companies",
     r"\btrading(\s+company)?\b|\bmanufactur(er|ing)?\b|\bwholesal(er|e)?\b|\bdistributor\b|\bexports?\b|\bexporter\b|\bimporter\b|\bexim\b|\bsupplier co\b|\bfactory\b"),
    (20, "IT & Software Companies",
     r"it company|software|technology solutions|tech firm|web development company|app development|digital agenc|ites|bpo|kpo|\bai\b|artificial intelligence|automation agency"),
    (21, "CA & Tax Consultants",
     r"chartered accountant|\bca firm\b|tax consultant|tax advisor|gst consultant|accounting firm|income tax|audit firm|cpa"),
    (22, "Auto Garages & Car Service Centres",
     r"auto garage|car service|car repair|auto workshop|car mechanic|two.?wheeler service|bike service|automobile service|tyre shop|auto care"),
    (23, "HR & Staffing Agencies",
     r"hr agenc|staffing|recruitment|placement agenc|manpower|talent acquisition|hiring solution|headhunter|workforce"),
    (24, "Printing & Packaging Companies",
     r"printing|packaging|print shop|offset print|digital print|flex print|box manufacturer|label print|stationery"),
    (25, "Facility Management & Pest Control",
     r"facility management|pest control|housekeeping|cleaning service|sanitation|fumigation|disinfect|janitorial"),
    (26, "Furniture Stores",
     r"furniture|home furnish|sofa store|modular kitchen|woodwork|wardrobe store|office furniture|mattress store"),
]


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------
HIGH_CONFIDENCE_SCORE   = 3   # exact multi-word or rare keyword match
MEDIUM_CONFIDENCE_SCORE = 2   # single strong keyword
LOW_CONFIDENCE_SCORE    = 1   # weak / generic keyword match
MIN_SEND_CONFIDENCE     = MEDIUM_CONFIDENCE_SCORE   # must be >= this to send


def _score_match(text: str, pattern: str) -> Tuple[int, str]:
    """
    Returns (score, matched_keyword).
    Score is proportional to specificity of the matched keyword.
    """
    matches = [m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)]
    if not matches:
        return 0, ""
    # Longer match = more specific = higher confidence
    best = max(matches, key=len)
    score = HIGH_CONFIDENCE_SCORE if len(best) > 8 else MEDIUM_CONFIDENCE_SCORE
    return score, best


def classify_lead_niche(
    business_name: str,
    category: Optional[str] = None,
    query_keyword: Optional[str] = None,
) -> Tuple[Optional[int], Optional[str], int]:
    """
    Classify a lead into one niche.

    Parameters
    ----------
    business_name   : Raw business name from scraper (e.g. Google Maps)
    category        : Scraper category tag if available (e.g. "Dental Clinic")
    query_keyword   : Original search keyword used to find the lead

    Returns
    -------
    (niche_id, matched_keyword, confidence_score)
    niche_id is None if no confident match was found.
    """
    # Concatenate all signals into a single search text
    signals = " ".join(filter(None, [business_name, category, query_keyword])).lower()

    best_niche_id: Optional[int] = None
    best_niche_name: Optional[str] = None
    best_score: int = 0
    best_keyword: str = ""

    for niche_id, niche_name, pattern in NICHE_KEYWORD_MAP:
        score, keyword = _score_match(signals, pattern)
        if score > best_score:
            best_score = score
            best_niche_id = niche_id
            best_niche_name = niche_name
            best_keyword = keyword

    if best_score < MIN_SEND_CONFIDENCE:
        logger.info(
            "Niche classification: no confident match for '%s' (score=%d, best_keyword='%s')",
            business_name[:60], best_score, best_keyword,
        )
        return None, best_keyword or None, best_score

    logger.debug(
        "Niche classified: niche_id=%d ('%s') for '%s' via keyword='%s' score=%d",
        best_niche_id, best_niche_name, business_name[:60], best_keyword, best_score,
    )
    return best_niche_id, best_keyword, best_score


# ---------------------------------------------------------------------------
# Business-name cleaner  (section 6.4 of AGENT_GUIDE)
# ---------------------------------------------------------------------------

# Social / directory domains that mean the lead has NO real website
SOCIAL_DOMAINS = frozenset({
    "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "whatsapp.com",
    "justdial.com", "indiamart.com", "tradeindia.com", "sulekha.com",
    "practo.com", "99acres.com", "magicbricks.com", "olx.com",
    "shopclues.com", "snapdeal.com", "amazon.in", "flipkart.com",
    "google.com", "maps.google.com",
})

# Noise words / emoji-like things to strip from business names
_NOISE_WORDS_RE = re.compile(
    r"\b(best|no\.?1|number one|top|leading|premier|cheapest|affordable|"
    r"trusted|certified|licensed|official|verified|award.winning)\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"\b[\d\s\-\+\(\)]{7,}\b")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F9FF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    re.UNICODE,
)
_SEO_SUFFIX_RE = re.compile(r"\s*[\|\-:]\s*.+$")


def clean_business_name(raw_name: str) -> str:
    """
    Clean a keyword-stuffed Google Maps business name per guide section 6.4.

    Steps:
    1. Strip SEO suffix after |, -, :
    2. Remove noise words (best, no.1, etc.)
    3. Remove phone numbers
    4. Remove emoji
    5. Strip excess whitespace
    6. Convert ALL-CAPS to Title Case
    7. Truncate to 33 chars if still too long (keep whole words)
    """
    if not raw_name or not isinstance(raw_name, str):
        return "there"

    name = raw_name.strip()

    # 1. Strip SEO suffix (anything after | or ' - ' or ':')
    name = _SEO_SUFFIX_RE.sub("", name).strip()

    # 1b. Strip parenthetical content (e.g. "(Import / Export)") unless contains tags
    if "<" not in name and ">" not in name:
        name = re.sub(r"\s*\(.*?\)", "", name)
        name = re.sub(r"[\(\[\{].*$", "", name).strip()

    # 2. Remove noise words
    name = _NOISE_WORDS_RE.sub("", name)

    # 3. Remove phone numbers
    name = _PHONE_RE.sub("", name)

    # 4. Remove emoji
    name = _EMOJI_RE.sub("", name)

    # 5. Collapse whitespace / stray punctuation
    name = re.sub(r"[,\.\*]+", "", name)
    name = re.sub(r"\s{2,}", " ", name).strip()

    # 6. ALL CAPS → Title Case
    if name == name.upper() and len(name) > 3:
        name = name.title()

    # 7. If still > 33 chars, truncate at last whole word boundary
    if len(name) > 33:
        truncated = name[:33]
        last_space = truncated.rfind(" ")
        if last_space > 10:
            name = truncated[:last_space].strip()
        else:
            name = truncated.strip()

    name = re.sub(r"[\s\(\)\-—,;:\./\\]+$", "", name).strip()

    return name or "there"


def is_social_domain(domain: str) -> bool:
    """Return True if the domain is a social/directory site (treat as no website)."""
    if not domain:
        return False
    d = clean_domain(domain)
    return d in SOCIAL_DOMAINS


def clean_domain(raw_domain: str) -> str:
    """
    Normalise a domain per guide section 6.4:
    - lowercase
    - strip www.
    - strip trailing path/query
    - punycode-safe (leave as-is if already ASCII)
    """
    if not raw_domain or not isinstance(raw_domain, str):
        return ""
    d = raw_domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    return d


# ---------------------------------------------------------------------------
# Niche ID → name lookup
# ---------------------------------------------------------------------------
NICHE_ID_TO_NAME = {nid: name for nid, name, _ in NICHE_KEYWORD_MAP}


def niche_name_from_id(niche_id: Optional[int]) -> Optional[str]:
    """Return the display name for a niche_id, or None."""
    if niche_id is None:
        return None
    return NICHE_ID_TO_NAME.get(niche_id)
