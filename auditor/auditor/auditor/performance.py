# auditor/performance.py — Page Performance Checks
# LeadGen OS v5.0.0 | Group F new module

import time
import re
import requests
from auditor.core import result_pass, result_warn, result_fail
from config import TIMEOUT


def audit_response_time(base_url: str, session: requests.Session) -> dict:
    """
    Measure homepage response time in ms and flag slow servers.

    SEO Impact: High — Core Web Vitals TTFB is a ranking factor.
    Source: https://web.dev/articles/ttfb
    Thresholds: Good < 800ms | Needs Improvement 800–1800ms | Poor > 1800ms
    """
    try:
        start = time.time()
        r = session.get(base_url, timeout=TIMEOUT, allow_redirects=True, verify=False)
        elapsed_ms = (time.time() - start) * 1000

        if elapsed_ms < 800:
            return result_pass(
                f"Server response time is excellent: {elapsed_ms:.0f}ms.",
                detail=f"TTFB target: < 800ms | Measured: {elapsed_ms:.0f}ms",
            )
        if elapsed_ms < 1800:
            return result_warn(
                f"Server response time needs improvement: {elapsed_ms:.0f}ms.",
                "Aim for < 800ms TTFB. Optimise with: server-side caching (Redis/Varnish), "
                "a CDN (Cloudflare), reduced database queries, or better hosting. "
                "Slow TTFB is a Core Web Vitals ranking signal.",
                f"TTFB: {elapsed_ms:.0f}ms (target: < 800ms)",
            )
        return result_fail(
            f"Server response time is poor: {elapsed_ms:.0f}ms.",
            "Critical: TTFB over 1800ms severely hurts Core Web Vitals LCP scores. "
            "Upgrade hosting, enable server-side caching, or use a CDN immediately. "
            "Google penalises slow servers in mobile-first indexing.",
            f"TTFB: {elapsed_ms:.0f}ms (target: < 800ms)",
        )
    except Exception as e:
        return result_warn(
            f"Could not measure response time: {e}",
            "Check your server is online and responding within 12 seconds.",
        )


def audit_page_size(r_content: bytes = None, html: str = "") -> dict:
    """
    Flag HTML pages over 100KB (uncompressed).

    SEO Impact: Medium — large pages slow parsing and waste crawl budget.
    Source: https://developers.google.com/search/docs/crawling-indexing/large-page-resources
    Threshold: Google recommends HTML under 100KB for fast rendering.
    """
    if r_content is not None:
        size_bytes = len(r_content)
    elif html:
        size_bytes = len(html.encode("utf-8"))
    else:
        return result_warn("Page size check skipped — no content available.", "")

    size_kb = size_bytes / 1024

    if size_kb < 60:
        return result_pass(
            f"Page HTML size is optimal: {size_kb:.1f}KB.",
            detail=f"Size: {size_kb:.1f}KB (target: < 100KB)",
        )
    if size_kb < 100:
        return result_pass(
            f"Page HTML size is acceptable: {size_kb:.1f}KB.",
            detail=f"Size: {size_kb:.1f}KB (target: < 100KB)",
        )
    if size_kb < 200:
        return result_warn(
            f"Page HTML is large: {size_kb:.1f}KB.",
            "Reduce HTML page size below 100KB by removing comments, whitespace, and inline scripts. "
            "Enable gzip/brotli compression on your server. "
            "Large pages take longer to parse — hurting First Contentful Paint.",
            f"Size: {size_kb:.1f}KB",
        )
    return result_fail(
        f"Page HTML is very large: {size_kb:.1f}KB.",
        "Critically large page size. Minify HTML, remove unused code, "
        "enable server compression (gzip/brotli). "
        "Pages over 200KB waste significant crawl budget.",
        f"Size: {size_kb:.1f}KB (target: < 100KB)",
    )


def audit_render_blocking(soup) -> dict:
    """
    Detect <script> tags in <head> without defer or async attributes.

    SEO Impact: High — render-blocking scripts delay FCP and LCP.
    Source: https://web.dev/articles/render-blocking-resources
    """
    head = soup.find("head")
    if not head:
        return result_warn("No <head> element found — cannot check render-blocking resources.", "")

    blocking = []
    for script in head.find_all("script", src=True):
        has_defer = script.has_attr("defer")
        has_async = script.has_attr("async")
        if not has_defer and not has_async:
            src = script.get("src", "")[:80]
            blocking.append(src)
        if len(blocking) >= 5:
            break

    if blocking:
        count = len(blocking)
        return result_warn(
            f"{count} render-blocking script(s) detected in <head>.",
            "Add 'defer' or 'async' attribute to <script> tags in <head>. "
            "Example: <script src='...' defer></script>. "
            "Render-blocking scripts delay page paint and hurt Core Web Vitals LCP score.",
            " | ".join(b[:60] for b in blocking[:3]),
        )

    # Also check link rel=stylesheet without media or preload
    blocking_css = head.find_all("link", rel="stylesheet")
    if len(blocking_css) > 5:
        return result_warn(
            f"{len(blocking_css)} external stylesheets detected in <head> — may cause render blocking.",
            "Combine CSS files where possible or use critical CSS / async CSS loading. "
            "Consider: <link rel='preload' as='style'> for non-critical stylesheets.",
            f"{len(blocking_css)} stylesheet links in <head>",
        )

    return result_pass(
        "No render-blocking scripts detected in <head>.",
        detail="All head scripts use defer or async attributes.",
    )


def audit_gzip_compression(base_url: str, session: requests.Session) -> dict:
    """
    Check if the server returns gzip or brotli compressed responses.

    SEO Impact: Medium — compression reduces transfer size, improving TTFB.
    Source: https://web.dev/articles/optimizing-content-efficiency-optimize-encoding-and-transfer
    """
    try:
        # Send request with Accept-Encoding header
        headers = {"Accept-Encoding": "gzip, deflate, br"}
        r = session.get(base_url, timeout=TIMEOUT, headers=headers, allow_redirects=True, verify=False)
        encoding = r.headers.get("Content-Encoding", "").lower()

        if "br" in encoding:
            return result_pass(
                "Brotli compression is enabled (Content-Encoding: br).",
                detail="Brotli provides ~20% better compression than gzip.",
            )
        if "gzip" in encoding or "deflate" in encoding:
            return result_pass(
                f"Gzip/deflate compression is enabled (Content-Encoding: {encoding}).",
                detail="Good — compression reduces transfer size significantly.",
            )

        # Check transfer-encoding chunked as fallback indicator
        transfer = r.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer:
            return result_warn(
                "No content-encoding header found — compression may not be enabled.",
                "Enable gzip or brotli compression on your server. "
                "In Apache: mod_deflate. In Nginx: gzip on; gzip_types text/html. "
                "Compression typically reduces HTML/CSS/JS size by 60–80%.",
                f"Content-Encoding: not set | Transfer-Encoding: {transfer}",
            )

        return result_warn(
            "No HTTP compression detected (gzip/brotli).",
            "Enable server-side compression. "
            "In Apache: add 'AddOutputFilterByType DEFLATE text/html text/css application/javascript'. "
            "In Nginx: add 'gzip on; gzip_types text/html application/javascript text/css;'. "
            "Compression reduces page weight by 60–80% and speeds up Time to First Byte.",
            f"Content-Encoding header: '{r.headers.get('Content-Encoding', 'not set')}'",
        )
    except Exception as e:
        return result_warn(
            f"Could not check compression: {e}",
            "Manually verify compression using https://www.giftofspeed.com/gzip-test/",
        )


def audit_webp_images(soup) -> dict:
    """
    Detect if the site uses WebP format images.

    SEO Impact: Medium — WebP reduces image weight by 25–34% vs JPEG.
    Source: https://developers.google.com/speed/webp
    """
    imgs = soup.find_all("img", src=True)
    if not imgs:
        return result_warn(
            "No images found on the page.",
            "Add images with descriptive alt text to improve engagement and SEO.",
        )

    webp_count = 0
    non_webp   = []
    for img in imgs:
        src = img.get("src", "")
        if src.lower().endswith(".webp") or "format=webp" in src.lower():
            webp_count += 1
        else:
            non_webp.append(src.split("/")[-1][:40])

    total = len(imgs)
    if webp_count == total:
        return result_pass(
            f"All {total} image(s) use WebP format — excellent image optimisation.",
            detail="WebP reduces image size by 25–34% vs JPEG/PNG.",
        )
    if webp_count > 0:
        return result_warn(
            f"{webp_count}/{total} images use WebP — convert remaining images.",
            "Convert all images to WebP format. Use Squoosh (free) or set up server-side conversion. "
            "In WordPress: use Imagify or ShortPixel plugin. "
            "WebP images load faster and improve Core Web Vitals LCP score.",
            f"Non-WebP: {', '.join(non_webp[:3])}",
        )
    return result_warn(
        f"No WebP images detected ({total} image(s) use older formats).",
        "Convert all images to WebP. Bulk convert with: cwebp command-line tool, "
        "Squoosh.app, or Cloudflare Polish (automatic WebP conversion). "
        "WebP images are 25–34% smaller — directly improving page load speed.",
        f"Non-WebP images: {', '.join(non_webp[:3])}",
    )


def audit_minification(soup, html: str = "") -> dict:
    """
    Detect unminified CSS or JS by checking for excessive whitespace/comments in inline code.

    SEO Impact: Low-Medium — minification reduces page weight.
    Source: https://web.dev/articles/minify-css
    """
    # Check inline scripts for obvious lack of minification
    inline_scripts = soup.find_all("script", src=False)
    unminified_js = []
    for script in inline_scripts:
        content = script.get_text(strip=True)
        if len(content) < 100:
            continue
        lines = content.splitlines()
        # Minified JS typically has very few lines relative to size
        if len(lines) > 10 and len(content) > 500:
            avg_line_len = len(content) / len(lines)
            if avg_line_len < 80:  # Short lines = unminified/pretty-printed
                unminified_js.append(f"inline script ({len(content)} bytes, {len(lines)} lines)")
        if len(unminified_js) >= 2:
            break

    # Check inline styles
    inline_styles = soup.find_all("style")
    unminified_css = []
    for style in inline_styles:
        content = style.get_text(strip=True)
        if len(content) < 100:
            continue
        # Count comment blocks — /* ... */
        comment_count = content.count("/*")
        if comment_count > 3:
            unminified_css.append(f"inline style ({len(content)} bytes, {comment_count} comments)")
        if len(unminified_css) >= 2:
            break

    if unminified_js or unminified_css:
        issues = unminified_js + unminified_css
        return result_warn(
            f"Unminified inline code detected: {len(issues)} resource(s).",
            "Minify inline JavaScript and CSS. Use: terser (JS), cssnano (CSS), "
            "or your build tool's minification plugin (Webpack, Vite, etc.). "
            "Minification reduces code size by 30–50% and improves parse time.",
            " | ".join(issues[:2]),
        )

    return result_pass(
        "Inline code appears minified or minimal — no obvious unminified blocks detected.",
        detail="Note: External JS/CSS files require server-side or build-tool minification checks.",
    )
