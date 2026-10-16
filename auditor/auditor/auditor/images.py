# auditor/images.py — Alt text, WebP optimization, Lazy loading
# Implements a single, unified image inventory ensuring consistent accounting,
# distinguishing decorative empty alt from missing alt, and guaranteeing
# that WebP image counts never exceed total image elements.

from __future__ import annotations

import logging
import urllib.parse
from typing import Any
from auditor.core import result_pass, result_warn, result_fail

logger = logging.getLogger(__name__)


def get_image_inventory(soup) -> dict[str, Any]:
    """
    Extract a single consistent inventory of all <img> elements and picture sources.

    Distinguishes:
      - Unique image elements (<img> tags in DOM)
      - Images with descriptive alt attributes
      - Images with empty alt attributes (decorative: alt="")
      - Images missing the alt attribute entirely (accessibility violation: alt is None)
      - Elements served via modern WebP / AVIF (via direct src, data-src, srcset, or <picture> parent)
    """
    if not soup:
        return {
            "total_elements": 0,
            "with_alt": [],
            "empty_alt": [],
            "missing_alt": [],
            "webp_elements": [],
            "legacy_elements": [],
            "unique_resource_urls": set(),
        }

    images = soup.find_all("img")
    with_alt = []
    empty_alt = []
    missing_alt = []
    webp_elements = []
    legacy_elements = []
    unique_resource_urls = set()

    for img in images:
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or ""
        ).strip()
        if src:
            unique_resource_urls.add(src)

        # ── 1. Alt attribute classification ──
        if img.get("alt") is None:
            missing_alt.append(src or "(no src)")
        elif img.get("alt") == "":
            empty_alt.append(src or "(no src)")
        else:
            with_alt.append({
                "src": src or "(no src)",
                "alt": img.get("alt", "").strip()[:100],
            })

        # ── 2. Format classification (WebP / AVIF detection) ──
        # Check direct src, data-src, srcset, or parent <picture> <source>
        is_modern = False
        src_lower = src.lower()
        if ".webp" in src_lower or ".avif" in src_lower:
            is_modern = True

        # Check img srcset
        srcset = (img.get("srcset") or "").lower()
        if ".webp" in srcset or ".avif" in srcset:
            is_modern = True

        # Check parent <picture> sources
        parent = img.parent
        if parent and parent.name == "picture":
            for source in parent.find_all("source"):
                stype = (source.get("type") or "").lower()
                ssrcset = (source.get("srcset") or "").lower()
                if "image/webp" in stype or "image/avif" in stype:
                    is_modern = True
                    break
                if ".webp" in ssrcset or ".avif" in ssrcset:
                    is_modern = True
                    break

        if is_modern:
            webp_elements.append(src or "(picture source)")
        else:
            legacy_elements.append(src or "(legacy format)")

    # Also collect picture source URLs into unique resources
    for source in soup.find_all("source"):
        srcset = source.get("srcset") or ""
        for part in srcset.split(","):
            u = part.strip().split()[0] if part.strip() else ""
            if u:
                unique_resource_urls.add(u)

    return {
        "total_elements": len(images),
        "with_alt": with_alt,
        "empty_alt": empty_alt,
        "missing_alt": missing_alt,
        "webp_elements": webp_elements,
        "legacy_elements": legacy_elements,
        "unique_resource_urls": unique_resource_urls,
    }


def audit_alt_text(soup) -> dict:
    """Check all image elements for alt attributes."""
    inv = get_image_inventory(soup)
    total = inv["total_elements"]
    missing = inv["missing_alt"]
    empty = inv["empty_alt"]
    with_alt = inv["with_alt"]

    if total == 0:
        return result_pass("No images found on this page.", value=0, unit="images missing alt")

    missing_count = len(missing)
    empty_count = len(empty)
    with_alt_count = len(with_alt)

    evidence_data = {
        "total_images": total,
        "with_descriptive_alt": with_alt_count,
        "empty_decorative_alt": empty_count,
        "missing_alt_attribute": missing_count,
        "sample_missing": missing[:5],
    }

    if missing_count == 0:
        if empty_count > 0:
            return result_warn(
                f"{empty_count} decorative image(s) have empty alt='' (OK if intentional).",
                "Ensure empty alt is ONLY used for purely decorative images. "
                "Informational images need descriptive alt text for accessibility and Google Image search.",
                f"Alt coverage: {with_alt_count} descriptive, {empty_count} decorative out of {total} images.",
                value=0,
                unit="images missing alt",
            )
        return result_pass(
            f"All {total} images have alt attributes.",
            detail=f"{total} of {total} images have descriptive alt text for search engines and screen readers.",
            value=0,
            unit="images missing alt",
        )

    pct = round(missing_count / total * 100)
    fix_msg = (
        "Add descriptive alt='...' to every <img> tag lacking alt text. "
        "This is critical for: (1) Google Image search ranking, "
        "(2) Accessibility (screen readers), (3) Displaying fallback text if image fails to load. "
        "Bad: <img src='photo.jpg'>  Good: <img src='photo.jpg' alt='Plumber fixing kitchen sink in London'>"
    )

    if missing_count >= total:
        return result_fail(
            f"ALL {total} images are missing alt text.",
            fix_msg,
            f"Sample missing: {', '.join(missing[:3])}",
            value=missing_count,
            unit="images missing alt",
        )

    if pct > 40:
        return result_fail(
            f"{missing_count} of {total} images ({pct}%) missing alt text.",
            fix_msg,
            f"Sample missing: {', '.join(missing[:3])}",
            value=missing_count,
            unit="images missing alt",
        )

    return result_warn(
        f"{missing_count} of {total} images ({pct}%) missing alt text.",
        "Add alt text to remaining images. Include relevant service and topical descriptions.",
        f"Sample missing: {', '.join(missing[:3])}",
        value=missing_count,
        unit="images missing alt",
    )


def audit_webp(soup, page_html: str = "") -> dict:
    """Check if site uses modern WebP/AVIF image formats."""
    inv = get_image_inventory(soup)
    total = inv["total_elements"]

    if total == 0:
        return result_pass("No images found to evaluate format.")

    webp_count = len(inv["webp_elements"])
    legacy_count = len(inv["legacy_elements"])
    # Numerator is guaranteed <= denominator
    webp_count = min(webp_count, total)

    pct = round(webp_count / total * 100) if total > 0 else 0

    if webp_count == 0 and legacy_count > 0:
        legacy_samples = [src.split("/")[-1][:40] for src in inv["legacy_elements"][:3]]
        return result_fail(
            f"No WebP images found. All {total} image(s) use heavy legacy formats (JPG/PNG).",
            "Convert images to WebP or AVIF format. WebP is 25–35% smaller than JPEG with equal quality. "
            "WordPress: use ShortPixel or Imagify plugin. "
            "Manual: use Squoosh.app or cwebp CLI. "
            "This directly improves Core Web Vitals (LCP) and page load speed.",
            f"Legacy images: {', '.join(legacy_samples)}",
            value=0,
            unit="WebP images",
        )

    if webp_count == total:
        return result_pass(
            f"All {total} images use modern WebP/AVIF format ({total} of {total}). Good job!",
            detail="Modern image formats reduce bandwidth and accelerate Largest Contentful Paint (LCP).",
            value=total,
            unit="WebP images",
        )

    if pct >= 50:
        return result_pass(
            f"WebP images detected ({webp_count} of {total}, {pct}%). Good job!",
            detail=f"{webp_count} of {total} image elements serve modern WebP/AVIF formats.",
            value=webp_count,
            unit="WebP images",
        )

    return result_warn(
        f"Mix of formats: {webp_count} WebP vs {total - webp_count} legacy (JPG/PNG) images ({pct}% WebP).",
        "Migrate remaining legacy images to WebP. Serve WebP with <picture> tag fallback for older browsers.",
        f"Detected {webp_count} of {total} images using WebP/AVIF.",
        value=webp_count,
        unit="WebP images",
    )


def audit_lazy_loading(soup) -> dict:
    """Check if images use loading='lazy' attribute."""
    images = soup.find_all("img")
    if not images:
        return result_pass("No images to check for lazy loading.")

    total = len(images)
    lazy = [img for img in images if img.get("loading") == "lazy"]
    eager = [img for img in images if img.get("loading") == "eager"]

    lazy_pct = round(len(lazy) / total * 100)

    if len(lazy) == 0:
        return result_warn(
            f"None of the {total} images use loading='lazy'.",
            "Add loading='lazy' to all below-the-fold images: <img src='...' loading='lazy' alt='...'>. "
            "This defers loading of off-screen images, improving initial page load time and Core Web Vitals. "
            "Note: do NOT lazy-load the hero/above-fold image (use loading='eager' for that).",
            value=0,
            unit="lazy-loaded images",
        )
    if lazy_pct < 50:
        return result_warn(
            f"Only {len(lazy)} of {total} images ({lazy_pct}%) use lazy loading.",
            "Add loading='lazy' to remaining below-the-fold images.",
            value=len(lazy),
            unit="lazy-loaded images",
        )
    return result_pass(
        f"{len(lazy)} of {total} images ({lazy_pct}%) use lazy loading.",
        detail="Ensure the above-the-fold hero image uses loading='eager' or no attribute.",
        value=len(lazy),
        unit="lazy-loaded images",
    )
