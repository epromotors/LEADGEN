# auditor/geo_supplement.py — Open-Source GEO & AI Search Readiness Supplement
# Integrates observable AI-crawler access rules, llms.txt spec verification,
# structured data grounding, and content attributability heuristics.
#
# MIT License Attribution:
# Inspired by and benchmarked against Auriti-Labs/geo-optimizer-skill (MIT)
# and dageno-agents/seo-geo-audit (MIT).
#
# Mandatory Constraints:
# 1. Does not modify or replace the canonical 62-factor contract or scoring.
# 2. Additive findings only; preserves all factor IDs and scoring semantics.
# 3. Truthful disconnected state: Never fabricates AI citations or visibility.
# 4. No external/paid API calls required for local deterministic checks.
# 5. Passing content checks does NOT claim guaranteed citation by AI products.

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Set

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Key AI Crawler User-Agents
# Differentiates citation/search bots from training/data-mining bots.
AI_CITATION_BOTS = {
    "GPTBot": "OpenAI crawler for ChatGPT search & browse",
    "OAI-SearchBot": "OpenAI search crawler for SearchGPT",
    "ClaudeBot": "Anthropic crawler for Claude web browsing",
    "PerplexityBot": "Perplexity AI real-time search & citation crawler",
    "Google-Extended": "Google AI training / Gemini web data control",
    "Applebot-Extended": "Apple intelligence web crawler control",
}

AI_TRAINING_BOTS = {
    "CCBot": "Common Crawl training data scraper",
    "Bytespider": "ByteDance LLM training crawler",
    "Meta-ExternalAgent": "Meta AI training crawler",
    "Amazonbot": "Amazon Alexa & AI training crawler",
    "cohere-ai": "Cohere training data scraper",
}

ALL_AI_BOTS = {**AI_CITATION_BOTS, **AI_TRAINING_BOTS}


# ── 1. Robots.txt AI Bot Parsing ──────────────────────────────────────────────

def parse_robots_ai_rules(robots_text: str | None) -> Dict[str, Any]:
    """
    Parse robots.txt to detect access rules for AI citation and training bots.
    Evaluates:
      - Explicit Allow/Disallow directives per bot
      - Wildcard (*) fallback behavior
      - Crawl delay if configured
    """
    if not robots_text or not isinstance(robots_text, str) or not robots_text.strip():
        all_citation = list(AI_CITATION_BOTS.keys())
        return {
            "robots_present": False,
            "citation_bots": {bot: {"status": "allowed", "via": "no_robots_default"} for bot in AI_CITATION_BOTS},
            "training_bots": {bot: {"status": "allowed", "via": "no_robots_default"} for bot in AI_TRAINING_BOTS},
            "citation_bots_allowed": all_citation,
            "citation_bots_blocked": [],
            "citation_bots_all_allowed": True,
            "has_explicit_ai_rules": False,
            "allowed_count": len(ALL_AI_BOTS),
            "blocked_count": 0,
            "wildcard_disallowed": False,
            "sitemaps_declared": 0,
            "summary": "No robots.txt found; all AI bots allowed by default.",
        }

    lines = robots_text.splitlines()
    current_agents: list[str] = []
    agent_rules: dict[str, list[tuple[str, str]]] = {}
    sitemaps: list[str] = []

    for line in lines:
        cleaned = line.split("#", 1)[0].strip()
        if not cleaned:
            continue
        if ":" not in cleaned:
            continue

        key, val = cleaned.split(":", 1)
        key = key.strip().lower()
        val = val.strip()

        if key == "user-agent":
            current_agents.append(val.lower())
        elif key in ("allow", "disallow"):
            for agent in current_agents:
                agent_rules.setdefault(agent, []).append((key, val))
        elif key == "sitemap":
            sitemaps.append(val)
        else:
            # New directive block or other directive resets agent context if followed by empty line
            pass

    # Evaluate wildcard (*) default
    wildcard_rules = agent_rules.get("*", [])
    wildcard_blocked = any(
        rule == "disallow" and path in ("/", "/*") for rule, path in wildcard_rules
    )

    def evaluate_bot(bot_name: str) -> Dict[str, Any]:
        bot_lower = bot_name.lower()
        if bot_lower in agent_rules:
            rules = agent_rules[bot_lower]
            # Check most specific directive
            is_disallowed = any(
                rule == "disallow" and path in ("/", "/*") for rule, path in rules
            )
            is_allowed = any(
                rule == "allow" and path in ("/", "/*") for rule, path in rules
            )
            if is_disallowed and not is_allowed:
                return {"status": "blocked", "via": "explicit_rule"}
            if is_allowed:
                return {"status": "allowed", "via": "explicit_rule"}
            return {"status": "partial", "via": "explicit_rule"}

        # Fallback to wildcard
        if wildcard_blocked:
            return {"status": "blocked", "via": "wildcard"}
        return {"status": "allowed", "via": "wildcard"}

    citation_results = {bot: evaluate_bot(bot) for bot in AI_CITATION_BOTS}
    training_results = {bot: evaluate_bot(bot) for bot in AI_TRAINING_BOTS}

    allowed_citation = [b for b, r in citation_results.items() if r["status"] in ("allowed", "partial")]
    blocked_citation = [b for b, r in citation_results.items() if r["status"] == "blocked"]
    explicit_count = sum(1 for r in {**citation_results, **training_results}.values() if r["via"] == "explicit_rule")

    return {
        "robots_present": True,
        "citation_bots": citation_results,
        "training_bots": training_results,
        "citation_bots_allowed": allowed_citation,
        "citation_bots_blocked": blocked_citation,
        "citation_bots_all_allowed": len(blocked_citation) == 0,
        "has_explicit_ai_rules": explicit_count > 0,
        "wildcard_disallowed": wildcard_blocked,
        "sitemaps_declared": len(sitemaps),
    }


# ── 2. llms.txt Specification Verification ───────────────────────────────────

def validate_llms_txt_content(content: str) -> Dict[str, Any]:
    """
    Validate llms.txt content against the emerging llms.txt spec:
      - First non-empty line is an H1 (# Title)
      - Blockquote description (> Summary) follows H1
      - Word count assessment
      - Presence of markdown links to key site documentation/sections
      - Optional companion file links (.md)
    """
    if not content or not content.strip():
        return {
            "valid": False,
            "word_count": 0,
            "has_h1": False,
            "has_blockquote": False,
            "has_markdown_links": False,
            "has_optional_section": False,
            "warnings": ["llms.txt file is empty."],
        }

    lines = [ln.strip() for ln in content.splitlines()]
    non_empty = [ln for ln in lines if ln]
    warnings: list[str] = []

    has_h1 = False
    if non_empty and non_empty[0].startswith("# "):
        has_h1 = True
    else:
        warnings.append("First non-empty line should be a top-level H1 header ('# Site Name').")

    blockquotes = [ln for ln in non_empty if ln.startswith("> ")]
    has_blockquote = len(blockquotes) > 0
    if not has_blockquote:
        warnings.append("Missing '> ' blockquote description summarizing the project or entity.")

    md_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", content)
    has_markdown_links = len(md_links) > 0
    if not has_markdown_links:
        warnings.append("llms.txt should contain markdown links to key documentation or product pages.")

    h2_lines = [ln for ln in non_empty if ln.startswith("## ")]
    has_optional = any("optional" in h2.lower() for h2 in h2_lines)

    words = len(re.findall(r"\w+", content))
    if words < 40:
        warnings.append("llms.txt is very brief (< 40 words); provide more comprehensive context.")

    return {
        "valid": has_h1 and has_blockquote and has_markdown_links,
        "word_count": words,
        "has_h1": has_h1,
        "has_blockquote": has_blockquote,
        "has_markdown_links": has_markdown_links,
        "markdown_links_count": len(md_links),
        "has_optional_section": has_optional,
        "warnings": warnings,
        "ranking_factor": False,
        "note": "llms.txt is an optional emerging informational convention; it is not a required search engine ranking factor.",
    }


# ── 3. Content Attributability & Understandability ───────────────────────────

def audit_content_attributability(soup: BeautifulSoup | None, html_text: str) -> Dict[str, Any]:
    """
    Evaluate observable content signals that allow AI answer engines to quote,
    attribute, and extract factual claims:
      - Data density: Presence of specific numbers, percentages, currency, metrics
      - Structural hierarchy: Clear H1 + H2/H3 breakdown
      - FAQ / Q&A structure: Directly answers conversational queries
      - Entity introductory clarity: First paragraphs contain clear descriptive sentences
      - Attribution links: Outbound citations or authoritative references
    """
    if not soup:
        return {
            "data_density_ok": False,
            "numbers_found": 0,
            "has_faq_structure": False,
            "has_clear_entity_intro": False,
            "outbound_citations_count": 0,
            "reading_clarity_score": 0,
        }

    # Extract body text without script/style
    clean_soup = BeautifulSoup(html_text, "html.parser")
    for tag in clean_soup(["script", "style", "noscript", "svg", "header", "footer"]):
        tag.decompose()

    body_text = clean_soup.get_text(separator=" ", strip=True)

    # 1. Data density & numerical facts (percentages, currency, metrics, years)
    number_matches = re.findall(r"\b\d+(?:[\.,]\d+)?%|\b[£$€₹]\s*\d+|\b\d{4}\b|\b\d+(?:[\.,]\d+)?\s*(?:kg|km|mph|users|clients|years|locations)", body_text, re.IGNORECASE)
    all_numbers = re.findall(r"\b\d+(?:[\.,]\d+)?\b", body_text)
    total_metrics = len(number_matches) + len(all_numbers)
    data_density_ok = len(number_matches) >= 2 or len(all_numbers) >= 5

    # 2. Structural Q&A / FAQ patterns
    faq_keywords = ["faq", "frequently asked", "questions", "q&a", "how does", "what is"]
    text_lower = body_text.lower()
    has_faq_text = any(kw in text_lower for kw in faq_keywords)
    faq_schema = bool(soup.find("script", type="application/ld+json", string=re.compile(r"FAQPage", re.I)))
    has_faq = has_faq_text or faq_schema

    # 3. Entity definition clarity
    # Check if first 3 paragraphs contain "is a", "provides", "specializes in", "founded", etc.
    p_tags = [p.get_text(strip=True) for p in clean_soup.find_all("p") if len(p.get_text(strip=True)) > 30]
    early_text = " ".join(p_tags[:3]).lower()
    definition_signals = ["is a", "are a", "provides", "specializing", "specializes", "manufactures", "leading", "established"]
    has_clear_entity_intro = any(sig in early_text for sig in definition_signals)

    # 4. Outbound citations / references (non-social external links)
    external_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(href)
            host = parsed.netloc.lower()
            if not any(soc in host for soc in ["facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com"]):
                external_links.append(href)

    return {
        "data_density_ok": data_density_ok,
        "specific_metrics_found": len(number_matches),
        "total_numbers_found": total_metrics,
        "has_faq_structure": has_faq,
        "has_clear_entity_intro": has_clear_entity_intro,
        "outbound_citations_count": len(external_links),
        "attributability_score": (
            (25 if data_density_ok else 10)
            + (25 if has_clear_entity_intro else 0)
            + (25 if has_faq else 10)
            + (25 if len(external_links) > 0 else 10)
        ),
    }


# ── 4. Main GEO Supplement Aggregator ────────────────────────────────────────

def audit_geo_supplement(
    soup: BeautifulSoup | None,
    html: str,
    url: str,
    robots_text: str | None = None,
    llms_text: str | None = None,
) -> Dict[str, Any]:
    """
    Produce the additive GEO & AI Search Readiness supplement for an audit.
    Deterministic, transparent, and strictly preserves 62 canonical factors.
    """
    robots_eval = parse_robots_ai_rules(robots_text)
    llms_eval = validate_llms_txt_content(llms_text or "")
    attributability = audit_content_attributability(soup, html)

    # Check Structured Data Entities
    schema_types: list[str] = []
    if soup:
        for script in soup.find_all("script", type="application/ld+json"):
            content = script.string or ""
            matches = re.findall(r'"@type"\s*:\s*"([^"]+)"', content)
            for m in matches:
                if m not in schema_types:
                    schema_types.append(m)

    # Check Canonical Tag Match
    canonical_match = True
    canonical_url = None
    if soup:
        can_tag = soup.find("link", rel=lambda x: x and "canonical" in x)
        if can_tag and can_tag.get("href"):
            canonical_url = can_tag.get("href").strip()
            # Basic match check
            canonical_match = bool(canonical_url and url.split("?")[0].rstrip("/").lower() in canonical_url.rstrip("/").lower())

    # Overall GEO Readiness Category Score (0-100 Heuristic for AI-readiness only)
    # Does NOT modify canonical SEO score.
    bot_score = 40 if robots_eval["citation_bots_all_allowed"] else (20 if len(robots_eval["citation_bots_allowed"]) > 0 else 0)
    schema_score = 30 if any(t in schema_types for t in ["Organization", "LocalBusiness", "WebSite", "Article", "Product"]) else 10
    content_score = round(attributability["attributability_score"] * 0.3)
    readiness_score = min(100, bot_score + schema_score + content_score)

    return {
        "geo_readiness_score": readiness_score,
        "robots_ai_rules": robots_eval,
        "llms_txt": {
            "found": bool(llms_text and llms_text.strip()),
            "evaluation": llms_eval,
            "disclaimer": "llms.txt is an optional emerging informational convention; it is not a required search engine ranking factor and does not guarantee AI answer inclusion.",
        },
        "content_attributability": attributability,
        "entity_schema_types": schema_types,
        "canonical_signal": {
            "canonical_url": canonical_url,
            "canonical_matches_requested": canonical_match,
        },
        "citation_monitoring": {
            "status": "unavailable",
            "reason": "Live citation queries require an authorized AI search provider API key (Perplexity/Gemini/OpenRouter). No synthetic citations fabricated.",
            "citations_detected": 0,
        },
        "disclaimer": (
            "Passing local GEO/AEO content checks indicates structured readability and bot accessibility; "
            "it does NOT prove or guarantee that ChatGPT, Gemini, or other AI engines will cite this domain."
        ),
    }
