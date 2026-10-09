# auditor/content.py — Content Quality Checks
# LeadGen OS v5.0.0 | Group D new module

import re
from auditor.core import result_pass, result_warn, result_fail

_STOPWORDS = {
    "home", "homepage", "welcome", "index", "page", "untitled", "new page",
    "website", "site", "online", "web", "default", "main", "start",
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to",
}


def audit_word_count(soup) -> dict:
    """
    Flag pages under 300 words as thin content.

    SEO Impact: High
    Source: https://developers.google.com/search/docs/fundamentals/creating-helpful-content
    """
    body = soup.find("body")
    if not body:
        return result_warn("Could not find page body to count words.", "Ensure the page returns valid HTML.")

    for tag in body.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = body.get_text(separator=" ", strip=True)
    words = [w for w in re.split(r"\s+", text) if w and len(w) > 1]
    count = len(words)

    if count < 200:
        return result_fail(
            f"Extremely thin content — only {count} words on the page.",
            "Add substantial content (aim for 500+ words). Google may exclude pages under 200 words from its index.",
            f"Word count: {count}", value=count, unit="words",
        )
    if count < 300:
        return result_warn(
            f"Thin content — only {count} words on the page.",
            "Expand to at least 300–500 words with service descriptions, benefits, FAQs.",
            f"Word count: {count}", value=count, unit="words",
        )
    return result_pass(
        f"Content length looks good — {count} words.",
        detail=f"Word count: {count}", value=count, unit="words",
    )


def audit_duplicate_meta(soup) -> dict:
    """
    Flag if title and meta description are identical.

    SEO Impact: Medium
    Source: https://developers.google.com/search/docs/appearance/title-link
    """
    title_tag = soup.find("title")
    meta_desc = soup.find("meta", attrs={"name": "description"})

    if not title_tag or not meta_desc:
        return result_pass("Duplicate meta check skipped — title or meta description missing.")

    title_text = title_tag.get_text(strip=True).lower().strip()
    desc_text  = (meta_desc.get("content") or "").lower().strip()

    if not title_text or not desc_text:
        return result_pass("Title or meta description is empty — duplicate check not applicable.")

    if title_text == desc_text:
        return result_fail(
            "Title and meta description are identical — wasted SEO opportunity.",
            "Write a unique meta description (140–160 chars) that expands on the title.",
            f"Both: '{title_text[:80]}'",
        )
    if title_text in desc_text:
        return result_warn(
            "Meta description repeats the title tag.",
            "Write a distinct description with secondary keywords and a CTA.",
            f"Title: '{title_text[:60]}'",
        )
    return result_pass("Title and meta description are distinct.", detail=f"Title: '{title_text[:60]}'")


def audit_keyword_in_title(soup) -> dict:
    """
    Flag titles consisting only of generic stop words.

    SEO Impact: Medium
    Source: https://developers.google.com/search/docs/appearance/title-link
    """
    title_tag = soup.find("title")
    if not title_tag or not title_tag.get_text(strip=True):
        return result_pass("Keyword-in-title check skipped — title tag missing.")

    title_text = title_tag.get_text(strip=True)
    words = re.findall(r"\b[a-zA-Z]{3,}\b", title_text.lower())
    meaningful = [w for w in words if w not in _STOPWORDS]

    if not meaningful:
        return result_fail(
            f"Title has no meaningful keywords: '{title_text[:80]}'",
            "Include your primary keyword. Example: 'Car Window Tinting Sydney | TEB Solutions'.",
            f"Title: '{title_text}'",
        )
    if len(meaningful) <= 2 and len(title_text) < 25:
        return result_warn(
            f"Title may be too generic — '{title_text}' with no service/location keyword.",
            "Expand: '[Service] in [City] | [Brand]'.",
            f"Title: '{title_text}'",
        )
    return result_pass(f"Title contains meaningful keywords: '{title_text[:80]}'.")


def audit_reading_level(soup) -> dict:
    """
    Detect near-empty or stuffed/machine-generated content.

    SEO Impact: Medium
    Source: https://developers.google.com/search/docs/fundamentals/creating-helpful-content
    """
    body = soup.find("body")
    if not body:
        return result_warn("Could not analyse reading level — no body element.", "Ensure valid HTML.")

    for tag in body.find_all(["script", "style"]):
        tag.decompose()

    text = body.get_text(separator=" ", strip=True)
    words = text.split()
    word_count = len(words)

    if word_count < 50:
        return result_warn(
            f"Very little readable text ({word_count} words) — content quality concern.",
            "Add meaningful, human-written content to avoid Google's helpful content penalty.",
            f"Word count: {word_count}",
        )

    # Detect keyword stuffing
    if word_count > 50:
        freq: dict[str, int] = {}
        for w in words:
            wc = re.sub(r"[^a-zA-Z]", "", w.lower())
            if len(wc) > 4:
                freq[wc] = freq.get(wc, 0) + 1
        if freq:
            top_word, top_count = max(freq.items(), key=lambda x: x[1])
            if top_count / word_count > 0.08 and top_word not in _STOPWORDS:
                return result_warn(
                    f"Possible keyword stuffing — '{top_word}' appears {top_count}x ({top_count/word_count:.0%} of content).",
                    "Reduce repetitive keyword usage. Write naturally for humans.",
                    f"'{top_word}' x{top_count} in {word_count} words.",
                )

    return result_pass(f"Content appears readable ({word_count} words).")
