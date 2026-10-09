# auditor/images.py — Alt text, WebP optimization, Lazy loading

from auditor.core import result_pass, result_warn, result_fail


def audit_alt_text(soup) -> dict:
    """Check all images for missing alt attributes."""
    images = soup.find_all("img")
    if not images:
        return result_pass("No images found on this page.", value=0, unit="images")
    
    missing_alt = [
        img.get("src", "unknown")[:80]
        for img in images
        if img.get("alt") is None
    ]
    empty_alt = [
        img.get("src", "unknown")[:80]
        for img in images
        if img.get("alt") == ""
    ]
    
    total = len(images)
    missing_count = len(missing_alt)
    
    if missing_count == 0:
        if empty_alt:
            return result_warn(
                f"{len(empty_alt)} decorative images have empty alt='' (OK if intentional).",
                "Ensure empty alt is ONLY used for purely decorative images. "
                "Informational images need descriptive alt text for accessibility and Google Image search.",
                f"Empty alt images: {len(empty_alt)} of {total}",
            )
        return result_pass(f"All {total} images have alt attributes.", value=0, unit="images")
    
    pct = round(missing_count / total * 100)
    if missing_count >= total:
        return result_fail(
            f"ALL {total} images are missing alt text.",
            "Add descriptive alt='...' to every <img> tag. "
            "This is critical for: (1) Google Image search ranking, "
            "(2) Accessibility (screen readers), (3) Displaying text if image fails to load. "
            "Bad: <img src='photo.jpg'>  Good: <img src='photo.jpg' alt='Plumber fixing kitchen sink in London'>",
            f"Sample missing: {', '.join(missing_alt[:3])}", value=missing_count, unit="images",
        )
    if pct > 40:
        return result_fail(
            f"{missing_count} of {total} images ({pct}%) missing alt text.",
            "Add descriptive alt text to all content images. Use keywords naturally.",
            f"Sample missing: {', '.join(missing_alt[:3])}", value=missing_count, unit="images",
        )
    return result_warn(
        f"{missing_count} of {total} images ({pct}%) missing alt text.",
        "Add alt text to remaining images. Include your location and service where relevant.",
        f"Sample missing: {', '.join(missing_alt[:3])}", value=missing_count, unit="images",
    )


def audit_webp(soup, page_html: str) -> dict:
    """Check if site uses modern WebP image format."""
    images = soup.find_all("img")
    if not images:
        return result_pass("No images found to evaluate format.")
    
    # Check <picture> tags with WebP sources
    picture_webp = soup.find_all("source", type="image/webp")
    
    webp_count = 0
    old_count = 0
    old_examples = []
    
    for img in images:
        src = (img.get("src") or img.get("data-src") or "").lower()
        if ".webp" in src:
            webp_count += 1
        elif any(ext in src for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]):
            old_count += 1
            old_examples.append(src.split("/")[-1][:50])
    
    webp_count += len(picture_webp)
    
    total = len(images)
    if webp_count == 0 and old_count > 0:
        return result_fail(
            f"No WebP images found. All {old_count} image(s) use heavy legacy formats (JPG/PNG).",
            "Convert images to WebP format. WebP is 25–35% smaller than JPEG with equal quality. "
            "WordPress: use ShortPixel or Imagify plugin. "
            "Manual: use Squoosh.app or cwebp CLI. "
            "This directly improves Core Web Vitals (LCP) and page load speed.",
            f"Legacy images: {', '.join(old_examples[:3])}",
        )
    if old_count > webp_count:
        return result_warn(
            f"Mix of formats: {webp_count} WebP vs {old_count} legacy (JPG/PNG) images.",
            "Migrate all images to WebP. Serve WebP with <picture> tag fallback for older browsers.",
            f"Legacy examples: {', '.join(old_examples[:3])}",
        )
    if webp_count > 0:
        return result_pass(f"WebP images detected ({webp_count} of {total}). Good job!")
    
    return result_warn(
        "Could not determine image formats (dynamic/CDN sources).",
        "Ensure your CDN or CMS serves WebP images. Check with Chrome DevTools Network tab.",
    )


def audit_lazy_loading(soup) -> dict:
    """Check if images use loading='lazy' attribute."""
    images = soup.find_all("img")
    if not images:
        return result_pass("No images to check for lazy loading.")
    
    total = len(images)
    lazy = [img for img in images if img.get("loading") == "lazy"]
    eager = [img for img in images if img.get("loading") == "eager"]
    no_attr = total - len(lazy) - len(eager)
    
    lazy_pct = round(len(lazy) / total * 100)
    
    if len(lazy) == 0:
        return result_warn(
            f"None of the {total} images use loading='lazy'.",
            "Add loading='lazy' to all below-the-fold images: <img src='...' loading='lazy' alt='...'>. "
            "This defers loading of off-screen images, improving initial page load time and Core Web Vitals. "
            "Note: do NOT lazy-load the hero/above-fold image (use loading='eager' for that).",
        )
    if lazy_pct < 50:
        return result_warn(
            f"Only {len(lazy)} of {total} images ({lazy_pct}%) use lazy loading.",
            "Add loading='lazy' to remaining below-the-fold images.",
        )
    return result_pass(
        f"{len(lazy)} of {total} images ({lazy_pct}%) use lazy loading.",
        detail="Ensure the above-the-fold hero image uses loading='eager' or no attribute.",
    )
