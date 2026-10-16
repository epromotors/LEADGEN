# auditor/keyword_density.py — Target-keyword & keyword-density diagnostics
# Provides deterministic visible-text extraction, phrase matching, placement checking,
# and site-wide keyword coverage aggregation.

from __future__ import annotations

import re
import logging
from typing import Any
from urllib.parse import urlparse

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


def extract_top_topics(crawled_pages: list[dict], max_topics: int = 5) -> list[dict[str, Any]]:
    """
    Extract frequent meaningful multi-word and single-word phrases across the site
    as optional extracted topic terms. Marked explicitly as inferred, NOT target keywords.
    """
    word_freq: dict[str, int] = {}
    bigram_freq: dict[str, int] = {}

    for page in crawled_pages:
        soup = page.get("soup")
        if not soup:
            continue
        text = extract_visible_text(soup)
        words = [w for w in tokenize_words(text) if len(w) > 3 and w not in COMMON_STOPWORDS]
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if w1 != w2:
                pair = f"{w1} {w2}"
                bigram_freq[pair] = bigram_freq.get(pair, 0) + 1

    # Prefer bigrams with frequency >= 2
    candidates = []
    for pair, count in sorted(bigram_freq.items(), key=lambda x: x[1], reverse=True)[:max_topics]:
        if count >= 2:
            candidates.append({"topic": pair.title(), "frequency": count, "type": "phrase"})

    if len(candidates) < max_topics:
        for word, count in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:max_topics - len(candidates)]:
            candidates.append({"topic": word.title(), "frequency": count, "type": "keyword"})

    return candidates


def analyze_target_keywords_site(
    crawled_pages: list[dict],
    target_keywords: list[str] | str | None = None,
) -> dict[str, Any]:
    """
    Site-wide keyword analysis aggregation across all eligible crawled pages.
    """
    # Normalize input keywords
    normalized_keywords: list[str] = []
    if isinstance(target_keywords, str):
        # Support comma or newline delimited strings
        lines = target_keywords.replace(",", "\n").splitlines()
        normalized_keywords = [k.strip() for k in lines if k.strip()]
    elif isinstance(target_keywords, list):
        normalized_keywords = [str(k).strip() for k in target_keywords if str(k).strip()]

    # Deduplicate while preserving order
    unique_keywords = list(dict.fromkeys(normalized_keywords))

    if not unique_keywords:
        inferred = extract_top_topics(crawled_pages)
        return {
            "configured": False,
            "status": "not_configured",
            "message": "Target keywords not configured",
            "target_keywords": [],
            "pages_analyzed": len(crawled_pages),
            "keyword_summaries": [],
            "inferred_topics": inferred,
            "formula_note": "Keyword Density (%) = (Exact Occurrences * Keyword Word Count / Total Visible Word Count) * 100",
        }

    eligible_pages = [p for p in crawled_pages if p.get("ok") and p.get("soup")]
    total_eligible = max(len(eligible_pages), 1)

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
        })

    return {
        "configured": True,
        "status": "configured",
        "message": f"{len(unique_keywords)} target keyword(s) analyzed across {len(eligible_pages)} crawled pages.",
        "target_keywords": unique_keywords,
        "pages_analyzed": len(eligible_pages),
        "keyword_summaries": summaries,
        "formula_note": "Keyword Density (%) = (Exact Occurrences * Keyword Word Count / Total Visible Word Count) * 100",
    }
