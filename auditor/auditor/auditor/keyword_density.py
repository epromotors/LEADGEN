# auditor/keyword_density.py — Target-keyword & keyword-density diagnostics
# Provides deterministic visible-text extraction, phrase matching, placement checking,
# and site-wide keyword coverage aggregation.

from __future__ import annotations

import re
import logging
from typing import Any
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Stopwords to filter when extracting inferred topics
COMMON_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't",
    "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll",
    "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd",
    "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves", "will", "shall", "may", "might", "must", "can", "us", "our", "get", "also",
}


def extract_visible_text(soup) -> str:
    """
    Extract visible body text while stripping scripts, styles, metadata,
    navigation boilerplate, and hidden elements to produce a reproducible word count.
    """
    if not soup:
        return ""

    # Work on a clone-like copy or decomposed tags
    # Decompose non-content and structural chrome tags
    decomposed_tags = [
        "script", "style", "noscript", "svg", "canvas", "iframe",
        "nav", "header", "footer", "aside"
    ]
    
    # We find all elements to avoid mutating original soup directly
    # Make a shallow clone of the body if present, else soup
    container = soup.find("body") or soup
    
    # Collect text fragments from content-bearing tags
    fragments = []
    
    for element in container.find_all(string=True):
        parent = element.parent
        if not parent or parent.name in decomposed_tags:
            continue
        
        # Check hidden attributes or styles
        style = parent.get("style", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            continue
        if parent.has_attr("hidden") or parent.get("aria-hidden") == "true":
            continue
            
        # Skip if within any decomposed ancestor
        if any(anc.name in decomposed_tags for anc in parent.parents):
            continue
            
        t = element.strip()
        if t:
            fragments.append(t)
            
    return " ".join(fragments)


def tokenize_words(text: str) -> list[str]:
    """Tokenize visible text into alphanumeric words."""
    if not text:
        return []
    return re.findall(r"\b[a-zA-Z0-9_\-']+\b", text.lower())


def count_visible_words(visible_text: str) -> int:
    """Return reproducible visible-word count used as denominator."""
    return len(tokenize_words(visible_text))


def analyze_keyword_on_page(
    soup,
    page_url: str,
    keyword: str,
    visible_text: str | None = None,
    total_words: int | None = None,
) -> dict[str, Any]:
    """
    Calculate keyword occurrence count, density, and placement for a single page.
    """
    clean_kw = keyword.strip()
    if not clean_kw:
        return {
            "keyword": "",
            "exact_count": 0,
            "variant_count": 0,
            "total_words": 0,
            "density_pct": 0.0,
            "placements": {},
            "covered": False,
        }

    if visible_text is None:
        visible_text = extract_visible_text(soup)
    if total_words is None:
        total_words = count_visible_words(visible_text)

    # Word count of the keyword phrase itself
    kw_words = tokenize_words(clean_kw)
    kw_len = max(len(kw_words), 1)

    # Exact phrase matching (case-insensitive with word boundaries)
    escaped_kw = re.escape(clean_kw)
    exact_pattern = re.compile(r"\b" + escaped_kw + r"\b", re.IGNORECASE)
    exact_matches = len(exact_pattern.findall(visible_text))

    # Variant matching (individual word co-occurrence or plural/singular variations)
    # Distinct from exact phrase
    variant_matches = 0
    if kw_len > 1:
        # Check if all constituent words appear within a proximity window (20 words)
        words_in_text = tokenize_words(visible_text)
        kw_word_set = set(kw_words)
        window_size = kw_len + 4
        for i in range(len(words_in_text) - kw_len + 1):
            window = set(words_in_text[i:i + window_size])
            if kw_word_set.issubset(window):
                variant_matches += 1
        # Subtract exact matches so variant is non-overlapping
        variant_matches = max(0, variant_matches - exact_matches)
    elif kw_len == 1:
        # Check simple plural/singular variant (e.g. "advisor" vs "advisors")
        stem = clean_kw.rstrip("s")
        if len(stem) > 3:
            stem_pattern = re.compile(r"\b" + re.escape(stem) + r"(?:s|es|ies|ing|ed)?\b", re.IGNORECASE)
            all_stem_matches = len(stem_pattern.findall(visible_text))
            variant_matches = max(0, all_stem_matches - exact_matches)

    # Keyword density formula:
    # density_pct = (exact_matches * words_in_keyword / total_words) * 100
    density_pct = 0.0
    if total_words > 0 and exact_matches > 0:
        density_pct = round((exact_matches * kw_len / total_words) * 100, 2)

    # Placement checks
    placements: dict[str, bool] = {
        "title": False,
        "meta_description": False,
        "h1": False,
        "h2": False,
        "url": False,
        "alt_text": False,
        "opening_content": False,
        "main_body": exact_matches > 0,
    }

    if soup:
        # Title
        title_tag = soup.find("title")
        if title_tag and exact_pattern.search(title_tag.get_text()):
            placements["title"] = True

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_desc and exact_pattern.search(meta_desc.get("content", "")):
            placements["meta_description"] = True

        # H1
        for h1 in soup.find_all("h1"):
            if exact_pattern.search(h1.get_text()):
                placements["h1"] = True
                break

        # H2
        for h2 in soup.find_all("h2"):
            if exact_pattern.search(h2.get_text()):
                placements["h2"] = True
                break

        # Image alt text
        for img in soup.find_all("img"):
            alt = img.get("alt", "")
            if alt and exact_pattern.search(alt):
                placements["alt_text"] = True
                break

    # URL path check
    parsed_url = urlparse(page_url)
    url_terms = re.split(r"[/_\-\.]", parsed_url.path.lower())
    if any(all(w in parsed_url.path.lower() for w in kw_words) for _ in [1]):
        placements["url"] = True

    # Opening content (first 120 words of visible text)
    words = tokenize_words(visible_text)
    opening_text = " ".join(words[:120])
    if exact_pattern.search(opening_text):
        placements["opening_content"] = True

    return {
        "keyword": clean_kw,
        "keyword_word_count": len(kw_words),
        "exact_count": exact_matches,
        "variant_count": variant_matches,
        "total_words": total_words,
        "density_pct": density_pct,
        "placements": placements,
        "covered": exact_matches > 0 or variant_matches > 0,
    }


SERVICE_PRODUCT_HINTS = {
    "advisory", "accelerator", "consulting", "services", "solutions",
    "management", "platform", "software", "agency", "development",
    "integration", "strategy", "support", "architecture", "cybersecurity",
    "infrastructure", "engineering", "audit", "compliance", "optimization",
    "channel", "vendor", "growth", "production"
}

INDUSTRY_LOCATION_HINTS = {
    "gcc", "uae", "dubai", "mumbai", "india", "gulf", "saudi", "riyadh",
    "qatar", "middle east", "ai", "artificial intelligence", "cloud",
    "enterprise", "b2b", "saas", "tech", "technology", "global", "niche",
    "it", "information technology"
}


def _normalize_pages(pages: list[dict]) -> list[dict]:
    res = []
    for p in (pages or []):
        item = dict(p)
        if "ok" not in item:
            item["ok"] = True
        if not item.get("soup") and item.get("html"):
            item["soup"] = BeautifulSoup(item["html"], "lxml")
        res.append(item)
    return res


def discover_observed_website_terms(
    crawled_pages: list[dict],
    sections: list[dict] | None = None,
    max_terms: int = 20,
) -> list[dict[str, Any]]:
    """
    Extract observed terms directly from the audited website's actual HTML:
    - Page titles, meta descriptions, and headings (h1, h2, h3)
    - Visible body text (meaningful 1-to-3 word phrases)
    - Service, product, industry, and location terminology
    - Image alt text and internal anchor text (distinguished from body occurrences)
    Reports occurrence count, visible-word denominator, density %, and placements.
    """
    if not crawled_pages:
        return []

    crawled_pages = _normalize_pages(crawled_pages)
    eligible = [p for p in crawled_pages if p.get("ok") and p.get("soup")]
    if not eligible:
        return []

    # Aggregate total visible words across audited documents
    total_visible_words = 0
    all_body_texts: list[str] = []
    for p in eligible:
        soup = p.get("soup")
        txt = extract_visible_text(soup)
        all_body_texts.append(txt)
        total_visible_words += count_visible_words(txt)

    if total_visible_words == 0:
        total_visible_words = 1

    combined_body = " ".join(all_body_texts)

    # 1. Candidate extraction from structured page elements
    candidates: set[str] = set()

    for p in eligible:
        soup = p.get("soup")
        if not soup:
            continue

        # Title
        t = soup.find("title")
        if t and t.get_text(strip=True):
            # Split title on separators |, -, :, •
            parts = re.split(r"[|\-–—:•]", t.get_text(strip=True))
            for part in parts:
                clean_part = part.strip()
                if 3 < len(clean_part) < 50:
                    candidates.add(clean_part)
                # also add key words
                for w in tokenize_words(clean_part):
                    if len(w) > 3 and w not in COMMON_STOPWORDS:
                        candidates.add(w.title())

        # Meta description
        m = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if m and m.get("content", "").strip():
            desc_words = [w for w in tokenize_words(m.get("content", "")) if len(w) > 3 and w not in COMMON_STOPWORDS]
            for dw in desc_words[:10]:
                candidates.add(dw.title())

        # Headings (h1, h2, h3)
        for h in soup.find_all(["h1", "h2", "h3"]):
            htext = h.get_text(strip=True)
            if 3 < len(htext) < 60:
                candidates.add(htext)
            for w in tokenize_words(htext):
                if len(w) > 3 and w not in COMMON_STOPWORDS:
                    candidates.add(w.title())

        # Image alt texts
        for img in soup.find_all("img"):
            alt = img.get("alt", "").strip()
            if alt and 3 < len(alt) < 40 and alt.lower() not in ("image", "photo", "icon", "logo"):
                candidates.add(alt)

        # Anchor texts
        for a in soup.find_all("a"):
            atxt = a.get_text(strip=True)
            if atxt and 3 < len(atxt) < 30 and atxt.lower() not in ("click here", "read more", "home", "back"):
                candidates.add(atxt)

    # 2. Extract frequent multi-word phrases (bigrams, trigrams) from body
    words = [w for w in tokenize_words(combined_body) if len(w) > 2 and w not in COMMON_STOPWORDS]
    phrase_counts: dict[str, int] = {}

    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        if w1 != w2:
            pair = f"{w1} {w2}"
            phrase_counts[pair] = phrase_counts.get(pair, 0) + 1

    for i in range(len(words) - 2):
        w1, w2, w3 = words[i], words[i + 1], words[i + 2]
        if w1 != w2 and w2 != w3:
            tri = f"{w1} {w2} {w3}"
            phrase_counts[tri] = phrase_counts.get(tri, 0) + 1

    for phrase, count in phrase_counts.items():
        if count >= 2:
            candidates.add(phrase.title())

    # 3. Score and analyze candidate terms against actual HTML & body text
    observed_terms: list[dict[str, Any]] = []

    for raw_term in candidates:
        clean_term = raw_term.strip()
        if not clean_term or len(clean_term) < 3:
            continue

        kw_words = tokenize_words(clean_term)
        kw_len = max(len(kw_words), 1)
        if kw_len > 4:
            continue

        escaped = re.escape(clean_term)
        exact_pattern = re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)

        # Count occurrences across all pages
        body_count = len(exact_pattern.findall(combined_body))

        # Check placements in structured elements
        has_title = False
        has_meta = False
        h1_matches = 0
        h2_matches = 0
        h3_matches = 0
        alt_matches = 0
        anchor_matches = 0

        source_pages = []

        for p in eligible:
            soup = p.get("soup")
            if not soup:
                continue
            url = p.get("final_url") or p.get("url", "")

            # Title
            t_tag = soup.find("title")
            if t_tag and exact_pattern.search(t_tag.get_text()):
                has_title = True
                if url not in source_pages:
                    source_pages.append(url)

            # Meta description
            m_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
            if m_tag and exact_pattern.search(m_tag.get("content", "")):
                has_meta = True

            # Headings
            for h1 in soup.find_all("h1"):
                if exact_pattern.search(h1.get_text()):
                    h1_matches += 1
                    if url not in source_pages:
                        source_pages.append(url)

            for h2 in soup.find_all("h2"):
                if exact_pattern.search(h2.get_text()):
                    h2_matches += 1
                    if url not in source_pages:
                        source_pages.append(url)

            for h3 in soup.find_all("h3"):
                if exact_pattern.search(h3.get_text()):
                    h3_matches += 1

            # Image alt text
            for img in soup.find_all("img"):
                alt = img.get("alt", "")
                if alt and exact_pattern.search(alt):
                    alt_matches += 1

            # Anchor text
            for a in soup.find_all("a"):
                atxt = a.get_text(strip=True)
                if atxt and exact_pattern.search(atxt):
                    anchor_matches += 1

        # Total observed occurrences across body and structured placements
        structured_count = (1 if has_title else 0) + (1 if has_meta else 0) + h1_matches + h2_matches + h3_matches + alt_matches
        total_occurrences = body_count
        if total_occurrences == 0 and structured_count > 0:
            total_occurrences = max(structured_count, 1)

        if total_occurrences == 0:
            continue

        # Density % relative to visible word denominator
        density_pct = round((total_occurrences * kw_len / total_visible_words) * 100, 2) if total_visible_words > 0 else 0.0

        # Term classification
        term_lower = clean_term.lower()
        if any(h in term_lower for h in SERVICE_PRODUCT_HINTS):
            term_type = "service_product"
        elif any(h in term_lower for h in INDUSTRY_LOCATION_HINTS):
            term_type = "industry_location"
        elif has_title and h1_matches > 0:
            term_type = "entity_brand"
        else:
            term_type = "content_phrase"

        # Check section-level occurrences if sections provided (single-page sites)
        section_breakdown = {}
        if sections and eligible:
            h_soup = eligible[0].get("soup")
            if h_soup:
                for sec in sections:
                    sec_id = sec.get("id")
                    if not sec_id:
                        continue
                    sec_el = h_soup.find(id=sec_id) or h_soup.find(attrs={"name": sec_id})
                    if sec_el:
                        sec_txt = extract_visible_text(sec_el)
                        cnt = len(exact_pattern.findall(sec_txt))
                        if cnt > 0:
                            section_breakdown[f"#{sec_id}"] = cnt

        observed_terms.append({
            "text": clean_term,
            "term": clean_term,
            "category": "observed_website_term",
            "term_type": term_type,
            "occurrence_count": total_occurrences,
            "count": total_occurrences,
            "visible_word_denominator": total_visible_words,
            "denominator": total_visible_words,
            "density_pct": density_pct,
            "source_pages": source_pages or [eligible[0].get("final_url") or eligible[0].get("url", "")],
            "placements": {
                "title": has_title,
                "meta_description": has_meta,
                "h1": h1_matches > 0,
                "h2": h2_matches > 0,
                "h3": h3_matches > 0,
                "body": body_count > 0,
                "alt_text": alt_matches > 0,
                "anchor_text": anchor_matches > 0,
            },
            "alt_text_occurrences": alt_matches,
            "anchor_text_occurrences": anchor_matches,
            "section_breakdown": section_breakdown,
        })

    # Sort observed terms: Title/H1 placement and high frequency first
    def _rank(t):
        score = t["occurrence_count"]
        if t["placements"]["title"]: score += 15
        if t["placements"]["h1"]: score += 12
        if t["placements"]["meta_description"]: score += 8
        if t["placements"]["h2"]: score += 6
        if t["term_type"] in ("service_product", "industry_location"): score += 5
        return score

    observed_terms.sort(key=_rank, reverse=True)

    # Deduplicate terms that are sub-strings of higher ranked terms with identical frequency
    deduped = []
    for t in observed_terms:
        if len(deduped) >= max_terms:
            break
        # Skip if identical text already present
        if any(d["text"].lower() == t["text"].lower() for d in deduped):
            continue
        deduped.append(t)

    return deduped


def extract_top_topics(crawled_pages: list[dict], max_topics: int = 6) -> list[dict[str, Any]]:
    """
    Extract frequent meaningful multi-word and single-word phrases across the site
    as optional extracted topic terms. Marked explicitly as inferred, NOT target keywords.
    """
    observed = discover_observed_website_terms(crawled_pages, max_terms=max_topics * 2)
    candidates = []

    for t in observed[:max_topics]:
        candidates.append({
            "topic": t["text"].title(),
            "frequency": t["occurrence_count"],
            "type": "phrase" if " " in t["text"] else "keyword",
            "category": "inferred_topic_suggestion",
            "term_type": t["term_type"],
            "density_pct": t["density_pct"],
            "evidence_basis": f"Observed on website (frequency: {t['occurrence_count']}, density: {t['density_pct']}%)",
            "disclaimer": "Candidate topic inferred from content evidence; external search-volume and ranking evidence requires a separate connected data provider (currently unavailable).",
        })

    return candidates


def analyze_target_keywords_site(
    crawled_pages: list[dict],
    target_keywords: list[str] | str | None = None,
    sections: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Site-wide keyword analysis aggregation across all eligible crawled pages.
    Makes automatic keyword and topic discovery the default behavior.
    Distinguishes:
      1. Observed website terms: Phrases actually extracted from the audited website.
      2. Inferred topic suggestions: Candidate topics inferred from observed content.
      3. User-supplied target keywords: Optional phrases entered by the auditor.
    """
    # Normalize input keywords
    normalized_keywords: list[str] = []
    if isinstance(target_keywords, str):
        lines = target_keywords.replace(",", "\n").splitlines()
        normalized_keywords = [k.strip() for k in lines if k.strip()]
    elif isinstance(target_keywords, list):
        normalized_keywords = [str(k).strip() for k in target_keywords if str(k).strip()]

    # Deduplicate while preserving order
    unique_keywords = list(dict.fromkeys(normalized_keywords))

    crawled_pages = _normalize_pages(crawled_pages)
    eligible_pages = [p for p in crawled_pages if p.get("ok") and p.get("soup")]
    total_eligible = max(len(eligible_pages), 1)

    # 1. Automatically discover observed website terms
    observed_terms = discover_observed_website_terms(crawled_pages, sections=sections, max_terms=15)
    inferred_topics = extract_top_topics(crawled_pages, max_topics=6)
    for inf in inferred_topics:
        if "suggestion_label" not in inf:
            inf["suggestion_label"] = "Inferred Candidate Topic (from content frequency)"

    # Build section breakdown for single page if sections provided
    sec_breakdown = []
    if sections and eligible_pages:
        h_soup = eligible_pages[0].get("soup")
        for sec in sections:
            sid = sec.get("id", "")
            sname = sec.get("name", sid)
            sec_el = h_soup.find(id=sid) if h_soup and sid else None
            stxt = extract_visible_text(sec_el) if sec_el else sec.get("snippet", "")
            words = tokenize_words(stxt)
            top_kws = [
                {"keyword": t["text"], "count": t.get("section_breakdown", {}).get(f"#{sid}", 1)}
                for t in observed_terms if t.get("section_breakdown", {}).get(f"#{sid}", 0) > 0
            ][:3]
            sec_breakdown.append({
                "section_id": sid,
                "section_name": sname,
                "word_count": len(words),
                "top_keywords": top_kws,
            })

    # If user-supplied target keywords are absent:
    # Continue the audit using the website-derived terms as default!
    if not unique_keywords:
        # Build keyword_summaries from the top observed terms
        auto_summaries = []
        for t in observed_terms[:6]:
            kw = t["text"]
            exact_count = t["occurrence_count"]
            density_pct = t["density_pct"]
            total_words = t["visible_word_denominator"]
            auto_summaries.append({
                "keyword": kw,
                "term_type": t["term_type"],
                "total_exact_occurrences": exact_count,
                "total_variant_occurrences": 0,
                "pages_covering_exact": 1,
                "pages_covering_any": 1,
                "page_coverage_pct": 100,
                "average_density_pct": density_pct,
                "visible_word_denominator": total_words,
                "best_page": {
                    "url": t["source_pages"][0] if t["source_pages"] else (eligible_pages[0].get("final_url") or eligible_pages[0].get("url", "") if eligible_pages else ""),
                    "occurrences": exact_count,
                    "density_pct": density_pct,
                },
                "placement_occurrences": {
                    "title": 1 if t["placements"]["title"] else 0,
                    "meta_description": 1 if t["placements"]["meta_description"] else 0,
                    "h1": 1 if t["placements"]["h1"] else 0,
                    "h2": 1 if t["placements"]["h2"] else 0,
                    "url": 0,
                    "alt_text": t["alt_text_occurrences"],
                    "opening_content": 0,
                    "main_body": exact_count,
                },
                "section_breakdown": t.get("section_breakdown", {}),
            })

        return {
            "configured": False,
            "status": "not_configured",
            "message": "Target keywords not configured",
            "auto_discovered": True,
            "discovery_mode": "automatic",
            "target_keywords": [],
            "user_supplied_target_keywords": [],
            "observed_website_terms": observed_terms,
            "inferred_topics": inferred_topics,
            "inferred_topic_suggestions": inferred_topics,
            "pages_analyzed": len(eligible_pages),
            "keyword_summaries": auto_summaries,
            "external_search_volume_available": False,
            "search_volume_disclaimer": "Search volume and ranking evidence require a connected external data source (currently unavailable).",
            "formula_note": "Keyword Density (%) = (Exact Occurrences * Keyword Word Count / Total Visible Word Count) * 100",
            "sections": sections or [],
            "section_breakdown": sec_breakdown,
        }

    # When target keywords ARE supplied by user:
    summaries = []

    for kw in unique_keywords:
        kw_total_exact = 0
        kw_total_variant = 0
        pages_with_exact = 0
        pages_with_any = 0
        densities = []
        best_page_url = None
        best_page_count = -1
        best_page_density = 0.0

        placement_summary = {
            "title": 0,
            "meta_description": 0,
            "h1": 0,
            "h2": 0,
            "url": 0,
            "alt_text": 0,
            "opening_content": 0,
            "main_body": 0,
        }

        for page in eligible_pages:
            url = page.get("final_url") or page.get("url", "")
            page_kw = analyze_keyword_on_page(page.get("soup"), url, kw)
            exact = page_kw["exact_count"]
            variant = page_kw["variant_count"]
            density = page_kw["density_pct"]

            kw_total_exact += exact
            kw_total_variant += variant
            if exact > 0:
                pages_with_exact += 1
            if exact > 0 or variant > 0:
                pages_with_any += 1

            densities.append(density)

            if exact > best_page_count:
                best_page_count = exact
                best_page_density = density
                best_page_url = url

            for place, present in page_kw["placements"].items():
                if present:
                    placement_summary[place] += 1

        avg_density = round(sum(densities) / len(densities), 2) if densities else 0.0
        coverage_pct = round((pages_with_any / total_eligible) * 100)

        # Check section-level occurrences if single-page sections provided
        section_breakdown = {}
        if sections and eligible_pages:
            h_soup = eligible_pages[0].get("soup")
            if h_soup:
                escaped_kw = re.escape(kw.strip())
                exact_kw_pattern = re.compile(r"\b" + escaped_kw + r"\b", re.IGNORECASE)
                for sec in sections:
                    sec_id = sec.get("id")
                    if not sec_id:
                        continue
                    sec_el = h_soup.find(id=sec_id) or h_soup.find(attrs={"name": sec_id})
                    if sec_el:
                        sec_txt = extract_visible_text(sec_el)
                        cnt = len(exact_kw_pattern.findall(sec_txt))
                        if cnt > 0:
                            section_breakdown[f"#{sec_id}"] = cnt

        summaries.append({
            "keyword": kw,
            "total_exact_occurrences": kw_total_exact,
            "total_variant_occurrences": kw_total_variant,
            "pages_covering_exact": pages_with_exact,
            "pages_covering_any": pages_with_any,
            "page_coverage_pct": coverage_pct,
            "average_density_pct": avg_density,
            "best_page": {
                "url": best_page_url,
                "occurrences": best_page_count if best_page_count > 0 else 0,
                "density_pct": best_page_density,
            },
            "placement_occurrences": placement_summary,
            "section_breakdown": section_breakdown,
        })

    return {
        "configured": True,
        "status": "configured",
        "auto_discovered": False,
        "discovery_mode": "user_supplied",
        "message": f"{len(unique_keywords)} target keyword(s) analyzed across {len(eligible_pages)} crawled pages.",
        "target_keywords": unique_keywords,
        "user_supplied_target_keywords": unique_keywords,
        "observed_website_terms": observed_terms,
        "inferred_topics": inferred_topics,
        "inferred_topic_suggestions": inferred_topics,
        "pages_analyzed": len(eligible_pages),
        "keyword_summaries": summaries,
        "external_search_volume_available": False,
        "search_volume_disclaimer": "External search volume and ranking evidence requires a separate connected data provider (currently unavailable).",
        "formula_note": "Keyword Density (%) = (Exact Occurrences * Keyword Word Count / Total Visible Word Count) * 100",
        "sections": sections or [],
    }

