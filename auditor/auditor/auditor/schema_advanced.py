# auditor/schema_advanced.py — Advanced Schema Markup Checks
# LeadGen OS v5.0.0 | Group G new module

import json
from auditor.core import result_pass, result_warn, result_fail


def _iter_schema_items(soup):
    """Yield all JSON-LD items from the page, including @graph arrays."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            if isinstance(data, list):
                yield from data
            elif isinstance(data, dict):
                if "@graph" in data:
                    yield from data["@graph"]
                else:
                    yield data
        except Exception:
            continue


def _get_type(item: dict) -> str:
    return str(item.get("@type", "")).lower()


def audit_faq_schema(soup) -> dict:
    """
    Detect FAQPage JSON-LD schema.

    SEO Impact: High — FAQ schema enables rich results (expandable Q&A in SERP).
    Source: https://developers.google.com/search/docs/appearance/structured-data/faqpage
    """
    for item in _iter_schema_items(soup):
        if not isinstance(item, dict):
            continue
        if _get_type(item) == "faqpage":
            entries = item.get("mainEntity", [])
            count = len(entries) if isinstance(entries, list) else 0
            if count > 0:
                return result_pass(
                    f"FAQPage schema detected with {count} Q&A pair(s).",
                    detail="Validate at: https://search.google.com/test/rich-results",
                )
            return result_warn(
                "FAQPage schema found but mainEntity (Q&A list) is empty.",
                "Add at least 3–5 question/answer pairs to your FAQPage schema. "
                "Each mainEntity item needs 'name' (question) and 'acceptedAnswer.text' (answer).",
            )

    return result_warn(
        "No FAQPage schema detected.",
        fix=(
            "Add FAQPage JSON-LD schema if your page has FAQ content. "
            "FAQ rich results appear as expandable Q&A blocks in Google Search — "
            "they can double your SERP real estate and improve CTR by 20–30%. "
            "Generator: https://technicalseo.com/tools/schema-markup-generator/"
        ),
    )


def audit_product_schema(soup) -> dict:
    """
    Detect Product schema with Offer and AggregateRating.

    SEO Impact: High — enables price, rating stars in SERP for product pages.
    Source: https://developers.google.com/search/docs/appearance/structured-data/product
    """
    for item in _iter_schema_items(soup):
        if not isinstance(item, dict):
            continue
        if _get_type(item) == "product":
            has_offer  = bool(item.get("offers"))
            has_rating = bool(item.get("aggregateRating"))
            missing = []
            if not has_offer:  missing.append("offers")
            if not has_rating: missing.append("aggregateRating")
            if missing:
                return result_warn(
                    f"Product schema found but missing: {', '.join(missing)}.",
                    f"Add {', '.join(missing)} to your Product schema. "
                    "Products with 'offers' show price in search results; "
                    "'aggregateRating' adds star ratings — both significantly improve CTR.",
                    f"@type: Product | Missing: {', '.join(missing)}",
                )
            return result_pass(
                "Product schema found with offers and aggregateRating.",
                detail="Validate at: https://search.google.com/test/rich-results",
            )

    return result_warn(
        "No Product schema detected.",
        fix=(
            "If this is a product or service page, add Product JSON-LD schema. "
            "Include 'offers' (price, currency) and 'aggregateRating' (star ratings). "
            "Product schema enables rich snippets with price and rating in Google Search."
        ),
    )


def audit_breadcrumb_schema(soup) -> dict:
    """
    Detect BreadcrumbList JSON-LD schema.

    SEO Impact: Medium — breadcrumbs appear in SERP URL path, improving UX and CTR.
    Source: https://developers.google.com/search/docs/appearance/structured-data/breadcrumb
    """
    for item in _iter_schema_items(soup):
        if not isinstance(item, dict):
            continue
        if _get_type(item) == "breadcrumblist":
            items_list = item.get("itemListElement", [])
            count = len(items_list) if isinstance(items_list, list) else 0
            if count >= 2:
                return result_pass(
                    f"BreadcrumbList schema found with {count} item(s).",
                    detail="Breadcrumbs appear in Google SERP URL path, improving navigation signals.",
                )
            return result_warn(
                f"BreadcrumbList schema found but only {count} item(s) — needs at least 2.",
                "Add at least 2 breadcrumb items (e.g., Home → Services). "
                "Each item needs 'position', 'name', and 'item' (URL).",
            )

    return result_warn(
        "No BreadcrumbList schema detected.",
        fix=(
            "Add BreadcrumbList JSON-LD to inner pages (not required on homepage). "
            "Breadcrumbs replace the URL slug in Google search results with a readable path, "
            "improving click-through rates and navigation signals."
        ),
    )


def audit_review_schema(soup) -> dict:
    """
    Detect Review or AggregateRating schema markup.

    SEO Impact: High — star ratings in SERP significantly increase CTR.
    Source: https://developers.google.com/search/docs/appearance/structured-data/review-snippet
    """
    for item in _iter_schema_items(soup):
        if not isinstance(item, dict):
            continue
        item_type = _get_type(item)
        if item_type == "aggregaterating":
            rating_val = item.get("ratingValue")
            review_cnt = item.get("reviewCount") or item.get("ratingCount")
            return result_pass(
                f"AggregateRating schema found — {rating_val} stars, {review_cnt} reviews.",
                detail="Star ratings will display in Google SERP if associated with a valid entity.",
            )
        if item_type == "review":
            author = item.get("author", {})
            name   = author.get("name") if isinstance(author, dict) else str(author)
            return result_pass(
                f"Review schema found — author: {name}.",
                detail="Validate at: https://search.google.com/test/rich-results",
            )
        # Check nested aggregateRating in any entity
        nested = item.get("aggregateRating")
        if nested and isinstance(nested, dict):
            rv = nested.get("ratingValue", "?")
            rc = nested.get("reviewCount") or nested.get("ratingCount", "?")
            return result_pass(
                f"Nested AggregateRating found — {rv} stars, {rc} reviews.",
                detail=f"Associated @type: {item.get('@type')}",
            )

    return result_warn(
        "No Review or AggregateRating schema detected.",
        fix=(
            "Add AggregateRating schema to your LocalBusiness, Product, or Service entity. "
            "Star ratings in Google SERP improve CTR by 15–35%. "
            "Collect reviews on Google, then add markup: "
            "'aggregateRating': {'@type': 'AggregateRating', 'ratingValue': '4.8', 'reviewCount': '47'}."
        ),
    )


def audit_graph_schema(soup) -> dict:
    """
    Properly iterate @graph arrays in JSON-LD and report all schema types found.
    Fixes bug where @graph schemas were not reported.

    SEO Impact: Diagnostic — ensures all schema is correctly detected.
    Source: https://schema.org/docs/datamodel.html
    """
    all_types = []
    graphs_found = 0

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            if isinstance(data, dict) and "@graph" in data:
                graphs_found += 1
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type"):
                        all_types.append(str(item["@type"]))
            elif isinstance(data, dict) and data.get("@type"):
                all_types.append(str(data["@type"]))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type"):
                        all_types.append(str(item["@type"]))
        except Exception:
            continue

    if not all_types:
        return result_warn(
            "No JSON-LD schema blocks found on the page.",
            "Add JSON-LD schema markup. Start with LocalBusiness or Organization schema. "
            "Schema markup is a direct Google rich result ranking factor.",
        )

    unique_types = list(dict.fromkeys(all_types))  # Dedupe, preserve order
    graph_note = f" ({graphs_found} @graph block(s))" if graphs_found else ""

    return result_pass(
        f"Schema types found{graph_note}: {', '.join(unique_types[:8])}.",
        detail=f"Total schema items: {len(all_types)} | Validate: https://search.google.com/test/rich-results",
    )
