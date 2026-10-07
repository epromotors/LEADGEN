import { useEffect, useState } from 'react'
import { RefreshCw, Download, ChevronDown, ChevronUp, AlertTriangle, Search, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { getLeads, getAudit, getPdfUrl } from '../api/client'

// ── Audit check definitions: label, explanation, fix hint ─────────────────
const AXIS_COLORS = {
  technical:    '#3b82f6',
  onpage:       '#a855f7',
  images:       '#14b8a6',
  links:        '#f97316',
  conversion:   '#10b981',
  ux:           '#d946ef',
  indexability: '#06b6d4',
  content:      '#8b5cf6',
  local_seo:    '#f43f5e',
  performance:  '#facc15',
  schema_adv:   '#34d399',
}

const PRIORITY_STYLE = {
  CRITICAL: { bg: '#450a0a', color: '#f87171', border: '#7f1d1d' },
  HIGH:     { bg: '#431407', color: '#fb923c', border: '#7c2d12' },
  MEDIUM:   { bg: '#1c1407', color: '#fbbf24', border: '#78350f' },
  LOW:      { bg: '#0c1a2e', color: '#60a5fa', border: '#1e3a5f' },
}

const AUDIT_GROUPS = [
  {
    id: 'technical', label: 'Technical SEO', icon: '🔧', color: '#3b82f6',
    checks: [
      { key: 'ssl_valid', label: 'SSL / HTTPS', priority: 'CRITICAL', invert: false,
        why: 'Google penalises non-HTTPS sites. Browsers show "Not Secure" warnings that kill visitor trust.',
        fix: 'Install a free SSL certificate (Let\'s Encrypt) via your hosting panel and redirect all HTTP → HTTPS.' },
      { key: 'has_sitemap', label: 'XML Sitemap', priority: 'HIGH', invert: false,
        why: 'Without a sitemap, search engines may miss pages. It\'s the roadmap for Googlebot.',
        fix: 'Generate a sitemap.xml (free tools: xml-sitemaps.com) and submit it in Google Search Console.' },
      { key: 'has_robots', label: 'robots.txt', priority: 'MEDIUM', invert: false,
        why: 'Missing robots.txt means crawlers have no instructions.',
        fix: 'Create a /robots.txt file. Minimum: "User-agent: * Allow: /" with your sitemap URL.' },
      { key: 'has_canonical', label: 'Canonical Tag', priority: 'MEDIUM', invert: false,
        why: 'Duplicate URLs split your ranking power across versions.',
        fix: 'Add <link rel="canonical"> in the <head> of every page.' },
      { key: 'favicon', label: 'Favicon', priority: 'LOW', invert: false,
        why: 'A missing favicon makes search results look unfinished.',
        fix: 'Add <link rel="icon" href="/favicon.ico"> in the head.' },
      { key: 'mobile_friendly', label: 'Mobile Viewport', priority: 'CRITICAL', invert: false,
        why: 'Google uses mobile-first indexing. A site that breaks on phones loses rankings.',
        fix: 'Add <meta name="viewport" content="width=device-width, initial-scale=1"> to every page.' },
    ],
  },
  {
    id: 'onpage', label: 'On-Page SEO', icon: '📄', color: '#a855f7',
    checks: [
      { key: 'has_page_title', label: 'Page Title Tag', invert: false,
        why: 'The title tag is the #1 on-page SEO signal. It appears in search results as the blue clickable headline.',
        fix: 'Write a unique <title> (50–60 chars) for every page including your main keyword near the start.' },
      { key: 'has_meta_desc', label: 'Meta Description', invert: false,
        why: 'No meta description means Google writes its own — usually poorly. It directly impacts click-through rate.',
        fix: 'Add a compelling <meta name="description"> (150–160 chars) to every page.' },
      { key: 'missing_h1', label: 'H1 Heading', invert: true,
        why: 'The H1 tells search engines what the page is about. Missing it is like a book with no title.',
        fix: 'Add exactly one <h1> per page containing your primary keyword naturally.' },
      { key: 'has_json_ld', label: 'Schema / JSON-LD', invert: false,
        why: 'Schema markup unlocks rich results (stars, FAQs, prices) in Google — boosting click-through rate.',
        fix: 'Add JSON-LD schema relevant to your business type (LocalBusiness, Service, Product) using schema.org.' },
      { key: 'has_og_tags', label: 'Open Graph Tags', invert: false,
        why: 'Without OG tags, shares on Facebook/WhatsApp/LinkedIn look broken — no image, bad title.',
        fix: 'Add og:title, og:description, og:image, og:url meta tags to every page.' },
    ],
  },
  {
    id: 'images', label: 'Images', icon: '🖼️', color: '#14b8a6',
    checks: [
      { key: 'alt_text', label: 'Image Alt Text', priority: 'MEDIUM', invert: false,
        why: 'Missing alt text hurts accessibility and makes images invisible to Google Image Search.',
        fix: 'Add descriptive alt attributes to every meaningful image.' },
      { key: 'uses_webp', label: 'WebP Image Format', priority: 'MEDIUM', invert: false,
        why: 'WebP images are 30–50% smaller than JPEG/PNG. Slow sites rank lower.',
        fix: 'Convert images to WebP using Squoosh or your CMS plugin.' },
      { key: 'has_lazy_load', label: 'Lazy Loading', priority: 'LOW', invert: false,
        why: 'Loading all images on page load slows Largest Contentful Paint (LCP).',
        fix: 'Add loading="lazy" to all <img> tags below the fold.' },
    ],
  },
  {
    id: 'links', label: 'Links', icon: '🔗', color: '#f97316',
    checks: [
      { key: 'broken_links_ok', label: 'No Broken Links', priority: 'HIGH', invert: false,
        why: 'Broken links signal a poorly maintained site to Google and frustrate real visitors.',
        fix: 'Use Screaming Frog or Google Search Console to find and fix all 404 URLs.' },
    ],
  },
  {
    id: 'conversion', label: 'Conversion & Trust', icon: '💼',
    color: '#10b981',
    checks: [
      { key: 'social', label: 'Social Profile Links', priority: 'MEDIUM', invert: false,
        why: 'Social profiles help visitors verify the business and strengthen branded search trust signals.',
        fix: 'Link active Facebook, Instagram, LinkedIn and other profiles from the header or footer.' },
      { key: 'has_contact', label: 'Clickable Phone / Email', priority: 'CRITICAL', invert: false,
        why: 'If visitors can\'t click to call or email instantly on mobile, they bounce to a competitor.',
        fix: 'Use <a href="tel:+1..."> for phones and <a href="mailto:..."> for email on every page.' },
      { key: 'has_whatsapp', label: 'WhatsApp Integration', priority: 'MEDIUM', invert: false,
        why: 'WhatsApp chat buttons increase conversions by 25–40% for service businesses.',
        fix: 'Add a floating WhatsApp button linking to https://wa.me/YOURNUMBER with a pre-filled message.' },
      { key: 'has_trust', label: 'Privacy Policy / Terms', priority: 'CRITICAL', invert: false,
        why: 'Missing trust pages lose GDPR compliance and hurt Google E-E-A-T score.',
        fix: 'Add /privacy-policy and /terms pages. Free: termsfeed.com' },
    ],
  },
  {
    id: 'ux', label: 'UI/UX & Experience', icon: '🎨',
    color: '#d946ef',
    checks: [
      { key: 'has_cta', label: 'Call-to-Action Button', priority: 'CRITICAL', invert: false,
        why: 'Sites with a clear CTA convert 200% more visitors. Visitors need to know what to do next.',
        fix: 'Add a prominent CTA button (e.g. "Get a Free Quote", "Book Now") with a contrasting colour.' },
      { key: 'cta_above_fold', label: 'CTA Above the Fold', priority: 'HIGH', invert: false,
        why: 'Above-fold CTAs get 47% more clicks. Visitors should not have to scroll to find how to contact you.',
        fix: 'Move your primary CTA button into the hero section visible without scrolling.' },
      { key: 'has_hero_headline', label: 'Hero Value Proposition', priority: 'CRITICAL', invert: false,
        why: 'Visitors decide to stay or leave in 3 seconds. A clear H1 headline communicates your offer instantly.',
        fix: 'Add an H1 at the top describing what you do: e.g. "Professional Window Tinting in Sydney".' },
      { key: 'font_size_ok', label: 'Text Readability (Font Size)', priority: 'MEDIUM', invert: false,
        why: 'Text under 14px is hard to read, especially on mobile. Small text increases bounce rate.',
        fix: 'Set body font-size to at least 16px in CSS: body { font-size: 16px; }' },
      { key: 'contrast_ok', label: 'Colour Contrast', priority: 'MEDIUM', invert: false,
        why: 'Low contrast text fails WCAG AA accessibility and makes content unreadable in bright light.',
        fix: 'Ensure text-to-background contrast ratio ≥ 4.5:1. Use WebAIM Contrast Checker to verify.' },
      { key: 'nav_ok', label: 'Navigation Menu', priority: 'HIGH', invert: false,
        why: 'Missing or poor navigation hurts both UX and internal link equity distribution.',
        fix: 'Add a <nav> element with 3–5 main links: Home, Services, About, Contact.' },
      { key: 'has_cookie_notice', label: 'Cookie Consent Banner', priority: 'MEDIUM', invert: false,
        why: 'Required by GDPR/CCPA for EU & California visitors. Fines up to €20M for non-compliance.',
        fix: 'Add a cookie consent banner. Free: CookieYes or Cookiebot.' },
      { key: 'has_live_chat', label: 'Live Chat Widget', priority: 'LOW', invert: false,
        why: 'Live chat increases conversions 40-50%. Even a WhatsApp floating button achieves a similar effect.',
        fix: 'Add Tawk.to (free) or a floating WhatsApp button as a low-cost live chat alternative.' },
      { key: 'has_phone_number', label: 'Phone Number Present', priority: 'HIGH', invert: false,
        why: 'Visible phone numbers increase trust and enable one-tap calling on mobile.',
        fix: 'Add a clickable <a href="tel:+1..."> phone number to the header and footer.' },
      { key: 'has_address', label: 'Address Present', priority: 'MEDIUM', invert: false,
        why: 'A visible address signals legitimacy and supports local SEO.',
        fix: 'Add your full business address to the footer or contact page.' },
    ],
  },
  {
    id: 'indexability', label: 'Indexability', icon: '🗂️', color: '#06b6d4',
    checks: [
      { key: 'has_noindex', label: 'No Noindex Tag', priority: 'CRITICAL', invert: true,
        why: 'A noindex tag blocks Google from indexing the page — it will never appear in search results.',
        fix: 'Remove <meta name="robots" content="noindex"> from pages you want indexed.' },
      { key: 'url_structure_ok', label: 'Clean URL Structure', priority: 'MEDIUM', invert: false,
        why: 'Keyword-rich, clean URLs improve click-through rate and are easier to crawl.',
        fix: 'Use short, hyphenated URLs like /services/plumbing instead of /page?id=123.' },
      { key: 'www_nonwww_ok', label: 'www/non-www Consistent', priority: 'HIGH', invert: false,
        why: 'Mixing www and non-www versions splits link equity and confuses Google.',
        fix: 'Choose one version (www or non-www) and 301-redirect the other. Set preferred in Search Console.' },
      { key: 'soft_404_ok', label: 'No Soft 404s', priority: 'HIGH', invert: false,
        why: 'Soft 404s return 200 status for missing pages, wasting crawl budget.',
        fix: 'Return proper 404/410 HTTP codes for missing content.' },
    ],
  },
  {
    id: 'content', label: 'Content Quality', icon: '✍️', color: '#8b5cf6',
    checks: [
      { key: 'word_count_ok', label: 'Sufficient Word Count', priority: 'HIGH', invert: false,
        why: 'Pages with <300 words are considered thin content by Google and rank poorly.',
        fix: 'Expand homepage and service pages to at least 500 words of unique, relevant content.' },
      { key: 'duplicate_meta_ok', label: 'Unique Meta Tags', priority: 'MEDIUM', invert: false,
        why: 'Duplicate titles/descriptions across pages confuse Google about which page to rank.',
        fix: 'Write a unique title and meta description for every page.' },
      { key: 'keyword_in_title_ok', label: 'Keyword in Title', priority: 'HIGH', invert: false,
        why: 'Including the target keyword in the page title is a top on-page ranking factor.',
        fix: 'Place your primary keyword near the start of the <title> tag.' },
      { key: 'reading_level_ok', label: 'Readable Content', priority: 'LOW', invert: false,
        why: 'Content written above a grade-8 reading level loses most visitors.',
        fix: 'Use short sentences, simple words, and break up text with headings.' },
    ],
  },
  {
    id: 'local_seo', label: 'Local SEO', icon: '📍', color: '#f43f5e',
    checks: [
      { key: 'has_nap', label: 'NAP Consistency', priority: 'CRITICAL', invert: false,
        why: 'Name, Address, Phone must match across your site and directories for local rankings.',
        fix: 'Add consistent NAP details in your footer and contact page. Match Google Business Profile exactly.' },
      { key: 'has_local_business_schema', label: 'LocalBusiness Schema', priority: 'HIGH', invert: false,
        why: 'LocalBusiness JSON-LD tells Google your business type, location, and hours for local pack inclusion.',
        fix: 'Add LocalBusiness schema with name, address, phone, openingHours on your homepage.' },
      { key: 'has_google_maps', label: 'Google Maps Embed', priority: 'MEDIUM', invert: false,
        why: 'An embedded map strengthens local relevance signals and helps visitors find you.',
        fix: 'Embed a Google Map on your contact page via Google Maps > Share > Embed.' },
      { key: 'city_in_title_ok', label: 'City in Title', priority: 'HIGH', invert: false,
        why: 'Including your city in the page title boosts local keyword relevance.',
        fix: 'Add your city to the page title: e.g. "Plumber in Manchester | YourBusiness".' },
      { key: 'has_business_hours', label: 'Business Hours Present', priority: 'MEDIUM', invert: false,
        why: 'Displaying hours on site and in schema improves local trust and reduces phone enquiries.',
        fix: 'Add opening hours to the contact page and in your LocalBusiness schema.' },
    ],
  },
  {
    id: 'performance', label: 'Performance', icon: '⚡', color: '#facc15',
    checks: [
      { key: 'response_time_ok', label: 'Fast Server Response', priority: 'HIGH', invert: false,
        why: 'TTFB over 600ms is a Core Web Vitals failure and a direct ranking signal.',
        fix: 'Upgrade hosting, enable server-side caching, or use a CDN like Cloudflare.' },
      { key: 'page_size_ok', label: 'Page Size Optimised', priority: 'MEDIUM', invert: false,
        why: 'Pages over 3MB cause slow load on mobile — 53% of mobile users leave after 3s.',
        fix: 'Compress images, minify CSS/JS, and remove unused scripts.' },
      { key: 'render_blocking_ok', label: 'No Render-Blocking Resources', priority: 'HIGH', invert: false,
        why: 'Render-blocking JS/CSS delays First Contentful Paint, hurting Core Web Vitals.',
        fix: 'Add defer/async to scripts. Move non-critical CSS to load asynchronously.' },
      { key: 'gzip_enabled', label: 'Gzip Compression', priority: 'MEDIUM', invert: false,
        why: 'Gzip reduces HTML/CSS/JS transfer size by up to 70%.',
        fix: 'Enable Gzip in your web server config (Apache: mod_deflate, Nginx: gzip on).' },
      { key: 'webp_coverage_ok', label: 'WebP Image Coverage', priority: 'MEDIUM', invert: false,
        why: 'WebP images are 30–50% smaller, directly improving load speed and LCP.',
        fix: 'Convert all images to WebP using Squoosh or a CMS plugin.' },
      { key: 'minification_ok', label: 'CSS/JS Minified', priority: 'LOW', invert: false,
        why: 'Unminified code wastes bytes and slows page parsing.',
        fix: 'Use a build tool (Webpack, Vite) or a WordPress plugin to minify CSS/JS.' },
    ],
  },
  {
    id: 'schema_adv', label: 'Advanced Schema', icon: '🧩', color: '#34d399',
    checks: [
      { key: 'has_faq_schema', label: 'FAQ Schema', priority: 'HIGH', invert: false,
        why: 'FAQ schema unlocks FAQ rich results — expanding your search listing and boosting CTR by 20–30%.',
        fix: 'Add FAQPage JSON-LD to pages with Q&A content.' },
      { key: 'has_product_schema', label: 'Product Schema', priority: 'HIGH', invert: false,
        why: 'Product schema enables price, availability, and review stars in search results.',
        fix: 'Add Product JSON-LD with name, price, availability, and review data.' },
      { key: 'has_breadcrumb_schema', label: 'Breadcrumb Schema', priority: 'MEDIUM', invert: false,
        why: 'Breadcrumb schema shows your site hierarchy in search results, improving CTR.',
        fix: 'Add BreadcrumbList JSON-LD to inner pages.' },
      { key: 'has_review_schema', label: 'Review Schema', priority: 'HIGH', invert: false,
        why: 'Review stars in search results increase CTR by up to 35%.',
        fix: 'Add Review or AggregateRating schema with genuine customer reviews.' },
      { key: 'schema_graph_ok', label: 'Schema @graph', priority: 'LOW', invert: false,
        why: 'A connected @graph schema provides the strongest structured data signal to Google.',
        fix: 'Use a single @graph block linking Organization, WebSite, and WebPage entities.' },
    ],
  },
]

// ── Compute SEO score client-side from DB boolean fields ─────────────────────
// Prefer backend seo_score/raw PASS-WARN-FAIL data; fall back for older audits.
const RAW_CHECK_MAP = {
  ssl_valid: ['technical', 'ssl'],
  has_sitemap: ['technical', 'sitemap'],
  has_robots: ['technical', 'robots'],
  has_canonical: ['technical', 'canonical'],
  favicon: ['technical', 'favicon'],
  mobile_friendly: ['technical', 'mobile'],
  has_page_title: ['onpage', 'page_title'],
  has_meta_desc: ['onpage', 'meta_desc'],
  missing_h1: ['onpage', 'h1'],
  has_json_ld: ['onpage', 'schema'],
  has_og_tags: ['onpage', 'og_tags'],
  alt_text: ['images', 'alt_text'],
  uses_webp: ['images', 'webp'],
  has_lazy_load: ['images', 'lazy_load'],
  broken_links_ok: ['links', 'broken_links'],
  social: ['conversion', 'social'],
  has_contact: ['conversion', 'contact'],
  has_whatsapp: ['conversion', 'whatsapp'],
  has_cta: ['ux', 'cta'],
  cta_above_fold: ['ux', 'cta_above_fold'],
  has_hero_headline: ['ux', 'hero_headline'],
  font_size_ok: ['ux', 'font_size'],
  contrast_ok: ['ux', 'contrast'],
  nav_ok: ['ux', 'nav_links'],
  has_cookie_notice: ['ux', 'cookie_notice'],
  has_live_chat: ['ux', 'live_chat'],
}

function getRawResult(key, audit) {
  const path = RAW_CHECK_MAP[key]
  if (!path || !audit.audit_results) return null
  return audit.audit_results?.[path[0]]?.[path[1]] ?? null
}

function computeScore(audit) {
  if (Number.isFinite(audit.seo_score)) return audit.seo_score
  const summaryScore = String(audit.audit_summary || '').match(/SEO Score:\s*(\d+)\/100/i)
  if (summaryScore) return Number(summaryScore[1])

  const rawResults = Object.values(audit.audit_results || {}).flatMap(group => Object.values(group || {}))
  if (rawResults.length) {
    const earned = rawResults.reduce((sum, result) => (
      sum + (result.status === 'PASS' ? 1 : result.status === 'WARN' ? 0.5 : 0)
    ), 0)
    return Math.round((earned / rawResults.length) * 100)
  }

  const factors = [
    audit.ssl_valid,
    audit.has_sitemap,
    audit.has_robots,
    audit.has_canonical,
    audit.mobile_friendly,
    audit.has_page_title,
    audit.has_meta_desc,
    !audit.missing_h1,
    audit.has_json_ld,
    audit.has_og_tags,
    (audit.missing_alt_count ?? 0) === 0,
    audit.uses_webp,
    audit.has_lazy_load,
    (audit.broken_links_count ?? 0) === 0,
    (audit.missing_social?.length ?? 0) === 0,
    audit.has_contact,
    audit.has_whatsapp,
    audit.has_trust,
  ]
  const known = factors.filter(f => f !== null && f !== undefined)
  if (known.length === 0) return 0
  const passed = known.filter(Boolean).length
  return Math.round((passed / known.length) * 100)
}

// Derive audit check status from raw audit JSON first, then DB fallbacks.
function getCheckStatus(key, audit) {
  const raw = getRawResult(key, audit)
  if (raw?.status) return raw.status

  switch (key) {
    case 'has_canonical':     return audit.has_canonical === null ? 'WARN' : audit.has_canonical ? 'PASS' : 'FAIL'
    case 'favicon':           return 'WARN'
    case 'has_page_title':    return audit.has_page_title === null ? 'WARN' : audit.has_page_title ? 'PASS' : 'FAIL'
    case 'has_meta_desc':     return audit.has_meta_desc === null ? 'WARN' : audit.has_meta_desc ? 'PASS' : 'FAIL'
    case 'has_og_tags':       return audit.has_og_tags === null ? 'WARN' : audit.has_og_tags ? 'PASS' : 'FAIL'
    case 'alt_text':          return (audit.missing_alt_count ?? 0) === 0 ? 'PASS' : 'FAIL'
    case 'has_lazy_load':     return audit.has_lazy_load === null ? 'WARN' : audit.has_lazy_load ? 'PASS' : 'WARN'
    case 'social':            return (audit.missing_social?.length ?? 0) === 0 ? 'PASS' : 'FAIL'
    case 'has_contact':       return audit.has_contact === null ? 'WARN' : audit.has_contact ? 'PASS' : 'FAIL'
    case 'has_whatsapp':      return audit.has_whatsapp === null ? 'WARN' : audit.has_whatsapp ? 'PASS' : 'WARN'
    case 'has_trust':         return audit.has_trust === null ? 'WARN' : audit.has_trust ? 'PASS' : 'FAIL'
    case 'ssl_valid':         return audit.ssl_valid === null ? 'WARN' : audit.ssl_valid ? 'PASS' : 'FAIL'
    case 'has_sitemap':       return audit.has_sitemap === null ? 'WARN' : audit.has_sitemap ? 'PASS' : 'FAIL'
    case 'has_robots':        return audit.has_robots === null ? 'WARN' : audit.has_robots ? 'PASS' : 'FAIL'
    case 'has_canonical_legacy': return 'WARN'
    case 'mobile_friendly':   return audit.mobile_friendly === null ? 'WARN' : audit.mobile_friendly ? 'PASS' : 'FAIL'
    case 'has_page_title_legacy': return 'WARN'
    case 'has_meta_desc_legacy':  return 'WARN'
    case 'missing_h1':        return audit.missing_h1 === null ? 'WARN' : audit.missing_h1 ? 'FAIL' : 'PASS'
    case 'has_json_ld':       return audit.has_json_ld === null ? 'WARN' : audit.has_json_ld ? 'PASS' : 'FAIL'
    case 'has_og_tags_legacy': return 'WARN'
    case 'uses_webp':         return audit.uses_webp === null ? 'WARN' : audit.uses_webp ? 'PASS' : 'WARN'
    case 'has_lazy_load_legacy': return 'WARN'
    case 'broken_links_ok':   return (audit.broken_links_count ?? 0) === 0 ? 'PASS' : 'FAIL'
    case 'has_contact_legacy':  return 'WARN'
    case 'has_whatsapp_legacy': return 'WARN'
    case 'has_trust_legacy':    return 'WARN'
    case 'has_cta':          return audit.has_cta === null ? 'WARN' : audit.has_cta ? 'PASS' : 'FAIL'
    case 'cta_above_fold':   return audit.cta_above_fold === null ? 'WARN' : audit.cta_above_fold ? 'PASS' : 'WARN'
    case 'has_hero_headline':return audit.has_hero_headline === null ? 'WARN' : audit.has_hero_headline ? 'PASS' : 'FAIL'
    case 'font_size_ok':     return audit.font_size_ok === null ? 'WARN' : audit.font_size_ok ? 'PASS' : 'WARN'
    case 'contrast_ok':      return audit.contrast_ok === null ? 'WARN' : audit.contrast_ok ? 'PASS' : 'WARN'
    case 'nav_ok':           return (audit.nav_links_count ?? 0) >= 3 ? 'PASS' : (audit.nav_links_count ?? 0) > 0 ? 'WARN' : 'FAIL'
    case 'has_cookie_notice':return audit.has_cookie_notice === null ? 'WARN' : audit.has_cookie_notice ? 'PASS' : 'WARN'
    case 'has_live_chat':    return audit.has_live_chat === null ? 'WARN' : audit.has_live_chat ? 'PASS' : 'WARN'
    case 'has_phone_number':  return audit.has_phone_number === null ? 'WARN' : audit.has_phone_number ? 'PASS' : 'WARN'
    case 'has_address':       return audit.has_address === null ? 'WARN' : audit.has_address ? 'PASS' : 'WARN'
    // Indexability
    case 'has_noindex':       return audit.has_noindex === null ? 'WARN' : audit.has_noindex ? 'FAIL' : 'PASS'
    case 'url_structure_ok':  return audit.url_structure_ok === null ? 'WARN' : audit.url_structure_ok ? 'PASS' : 'WARN'
    case 'www_nonwww_ok':     return audit.www_nonwww_ok === null ? 'WARN' : audit.www_nonwww_ok ? 'PASS' : 'FAIL'
    case 'soft_404_ok':       return audit.soft_404_ok === null ? 'WARN' : audit.soft_404_ok ? 'PASS' : 'FAIL'
    // Content quality
    case 'word_count_ok':     return (audit.word_count ?? 0) >= 300 ? 'PASS' : (audit.word_count ?? 0) > 0 ? 'WARN' : 'FAIL'
    case 'duplicate_meta_ok': return audit.duplicate_meta_ok === null ? 'WARN' : audit.duplicate_meta_ok ? 'PASS' : 'WARN'
    case 'keyword_in_title_ok': return audit.keyword_in_title_ok === null ? 'WARN' : audit.keyword_in_title_ok ? 'PASS' : 'WARN'
    case 'reading_level_ok':  return audit.reading_level_ok === null ? 'WARN' : audit.reading_level_ok ? 'PASS' : 'WARN'
    // Local SEO
    case 'has_nap':                   return audit.has_nap === null ? 'WARN' : audit.has_nap ? 'PASS' : 'FAIL'
    case 'has_local_business_schema': return audit.has_local_business_schema === null ? 'WARN' : audit.has_local_business_schema ? 'PASS' : 'WARN'
    case 'has_google_maps':           return audit.has_google_maps === null ? 'WARN' : audit.has_google_maps ? 'PASS' : 'WARN'
    case 'city_in_title_ok':          return audit.city_in_title_ok === null ? 'WARN' : audit.city_in_title_ok ? 'PASS' : 'WARN'
    case 'has_business_hours':        return audit.has_business_hours === null ? 'WARN' : audit.has_business_hours ? 'PASS' : 'WARN'
    // Performance
    case 'response_time_ok':  return (audit.response_time_ms ?? 9999) < 600 ? 'PASS' : (audit.response_time_ms ?? 9999) < 1200 ? 'WARN' : 'FAIL'
    case 'page_size_ok':      return audit.page_size_ok === null ? 'WARN' : audit.page_size_ok ? 'PASS' : 'WARN'
    case 'render_blocking_ok':return audit.render_blocking_ok === null ? 'WARN' : audit.render_blocking_ok ? 'PASS' : 'WARN'
    case 'gzip_enabled':      return audit.gzip_enabled === null ? 'WARN' : audit.gzip_enabled ? 'PASS' : 'WARN'
    case 'webp_coverage_ok':  return audit.webp_coverage_ok === null ? 'WARN' : audit.webp_coverage_ok ? 'PASS' : 'WARN'
    case 'minification_ok':   return audit.minification_ok === null ? 'WARN' : audit.minification_ok ? 'PASS' : 'WARN'
    // Schema advanced
    case 'has_faq_schema':        return audit.has_faq_schema === null ? 'WARN' : audit.has_faq_schema ? 'PASS' : 'WARN'
    case 'has_product_schema':    return audit.has_product_schema === null ? 'WARN' : audit.has_product_schema ? 'PASS' : 'WARN'
    case 'has_breadcrumb_schema': return audit.has_breadcrumb_schema === null ? 'WARN' : audit.has_breadcrumb_schema ? 'PASS' : 'WARN'
    case 'has_review_schema':     return audit.has_review_schema === null ? 'WARN' : audit.has_review_schema ? 'PASS' : 'WARN'
    case 'schema_graph_ok':       return audit.schema_graph_ok === null ? 'WARN' : audit.schema_graph_ok ? 'PASS' : 'WARN'
    default:                  return 'WARN'
  }
}

const STATUS_STYLE = {
  PASS: { bg: '#052e16', border: '#16a34a55', color: '#4ade80', dot: '#22c55e', label: 'PASS' },
  WARN: { bg: '#1c1407', border: '#92400e55', color: '#fbbf24', dot: '#f59e0b', label: 'WARN' },
  FAIL: { bg: '#2d0b0b', border: '#991b1b55', color: '#f87171', dot: '#ef4444', label: 'FAIL' },
}

function CheckCard({ check, audit }) {
  const status = getCheckStatus(check.key, audit)
  const raw = getRawResult(check.key, audit)
  const s = STATUS_STYLE[status]
  const message = raw?.message || check.why
  const fix = raw?.fix || check.fix
  const priority = check.priority || 'MEDIUM'
  const ps = PRIORITY_STYLE[priority] || PRIORITY_STYLE.MEDIUM
  return (
    <div style={{
      background: s.bg, border: `1px solid ${s.border}`,
      borderLeft: `3px solid ${s.dot}`,
      borderRadius: 10, padding: '12px 14px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4, gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 }}>
          <span style={{ color: '#f1f5f9', fontWeight: 700, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{check.label}</span>
          <span style={{
            padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 800,
            background: ps.bg, color: ps.color, border: `1px solid ${ps.border}`,
            letterSpacing: '0.06em', flexShrink: 0,
          }}>{priority}</span>
        </div>
        <span style={{
          padding: '2px 9px', borderRadius: 20, fontSize: 10, fontWeight: 800,
          background: s.border, color: s.color, letterSpacing: '0.05em', flexShrink: 0,
        }}>{s.label}</span>
      </div>
      <p style={{ color: '#94a3b8', fontSize: 12, margin: '3px 0', lineHeight: 1.5 }}>{message}</p>
      {raw?.detail && (
        <p style={{ color: '#64748b', fontSize: 11, margin: '4px 0 0', lineHeight: 1.45, fontStyle: 'italic' }}>{raw.detail}</p>
      )}
      {status !== 'PASS' && fix && (
        <p style={{ color: s.color, fontSize: 11, marginTop: 5, display: 'flex', gap: 5, alignItems: 'flex-start' }}>
          <span style={{ flexShrink: 0 }}>→</span>
          <span>{fix}</span>
        </p>
      )}
    </div>
  )
}

function AxisRing({ label, icon, score, color }) {
  const isNull = score === null || score === undefined
  const pct = isNull ? 0 : Math.min(100, Math.max(0, score))
  const r = 28
  const circ = 2 * Math.PI * r
  const dash = (pct / 100) * circ
  const ringColor = pct >= 75 ? color : pct >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 78 }}>
      <div style={{ position: 'relative', width: 72, height: 72 }}>
        <svg width={72} height={72} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={36} cy={36} r={r} fill="none" stroke="#1e293b" strokeWidth={6} />
          <circle cx={36} cy={36} r={r} fill="none" stroke={ringColor} strokeWidth={6}
            strokeDasharray={`${dash} ${circ - dash}`} strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 4px ${ringColor}99)`, transition: 'stroke-dasharray 0.6s ease' }}
          />
        </svg>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          {isNull
            ? <span style={{ fontSize: 9, color: '#475569', textAlign: 'center', lineHeight: 1.2 }}>N/A</span>
            : <span style={{ fontSize: 16, fontWeight: 900, color: ringColor, lineHeight: 1 }}>{pct}</span>
          }
        </div>
      </div>
      <span style={{ fontSize: 9, color: '#94a3b8', textAlign: 'center', marginTop: 4, fontWeight: 600, lineHeight: 1.2 }}>{icon} {label}</span>
    </div>
  )
}

function ScoreGauge({ score }) {
  const color = score >= 75 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'
  const label = score >= 75 ? 'Good' : score >= 50 ? 'Needs Work' : 'Poor'
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      background: '#0f172a', border: `2px solid ${color}33`,
      borderRadius: 16, padding: '20px 28px', minWidth: 130,
    }}>
      <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>Overall</span>
      <span style={{ fontSize: 48, fontWeight: 900, color, lineHeight: 1 }}>{score}</span>
      <span style={{ fontSize: 12, color: '#475569', marginTop: 2 }}>/100</span>
      <span style={{
        marginTop: 10, padding: '3px 12px', borderRadius: 20,
        background: `${color}22`, color, fontWeight: 700, fontSize: 11,
      }}>{label}</span>
    </div>
  )
}

function AuditRow({ lead }) {
  const [audit, setAudit] = useState(null)
  const [open, setOpen]   = useState(false)
  const [loading, setLoading] = useState(false)

  async function loadAudit() {
    if (audit) { setOpen(o => !o); return }
    setLoading(true)
    try {
      const res = await getAudit(lead.id)
      setAudit(res.data)
      setOpen(true)
    } catch {
      toast.error('No audit data yet for this lead')
    } finally {
      setLoading(false)
    }
  }

  const isAudited  = lead.status === 'audited' || lead.status === 'emailed' || lead.status === 'replied' || lead.status === 'converted'
  const isAuditing = lead.status === 'auditing'
  const isNew      = lead.status === 'new'
  const isSkipped  = audit && audit.error_message && audit.error_message.startsWith('SITE_STATUS:')

  function getAuditBadge() {
    if (isAuditing) return { cls: 'badge-yellow', text: 'auditing…' }
    if (isNew)      return { cls: 'badge-grey',   text: 'not audited' }
    if (isAudited && audit && isSkipped) return { cls: 'badge-red',  text: 'skipped' }
    if (isAudited)  return { cls: 'badge-blue',   text: 'audited' }
    return { cls: 'badge-grey', text: lead.status }
  }

  const badge  = getAuditBadge()
  const hasPdf = audit && audit.pdf_path

  // Count pass/warn/fail from all checks
  const allChecks = AUDIT_GROUPS.flatMap(g => g.checks)
  const counts = audit ? allChecks.reduce((acc, c) => {
    const s = getCheckStatus(c.key, audit); acc[s] = (acc[s] || 0) + 1; return acc
  }, {}) : {}

  return (
    <>
      <tr className="table-row cursor-pointer" onClick={loadAudit}>
        <td className="td font-medium text-white" style={{ maxWidth: '200px' }}>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>
            {lead.business_name}
          </span>
        </td>
        <td className="td text-slate-400" style={{ fontSize: '12px' }}>
          {(lead.website || '').replace(/^https?:\/\//, '').slice(0, 40) || '—'}
        </td>
        <td className="td">
          <span className={`badge ${badge.cls}`}>{badge.text}</span>
        </td>
        <td className="td text-slate-500 text-xs">{new Date(lead.created_at).toLocaleDateString()}</td>
        <td className="td">
          <div className="flex items-center gap-2">
            {hasPdf && (
              <a href={getPdfUrl(lead.id)} target="_blank" rel="noreferrer"
                onClick={e => e.stopPropagation()} className="btn-primary py-1 px-2 text-xs">
                <Download size={13} /> PDF
              </a>
            )}
            {isAudited && !audit && !isNew && (
              <span style={{ fontSize: 10, color: '#475569' }}>click to check</span>
            )}
            {loading ? <span className="spinner w-4 h-4" /> :
              open ? <ChevronUp size={16} className="text-slate-500" />
                   : <ChevronDown size={16} className="text-slate-500" />
            }
          </div>
        </td>
      </tr>

      {open && audit && (
        <tr>
          <td colSpan={5} style={{ background: '#0d1423', padding: 0 }}>
            <div style={{ padding: '24px 28px' }}>
              {isSkipped ? (
                <div className="flex items-start gap-3">
                  <AlertTriangle size={18} className="text-amber-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-semibold text-amber-300 mb-1">Audit Skipped</p>
                    <p className="text-sm text-slate-400 leading-relaxed">{audit.audit_summary}</p>
                    <p className="text-xs text-slate-600 mt-2">No PDF generated — site is not a real/active website.</p>
                  </div>
                </div>
              ) : (
                <>
                  {/* Header: overall score + 6 axis rings (Inspeccia-style) */}
                  <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap' }}>
                    <ScoreGauge score={computeScore(audit)} />
                    <div style={{ flex: 1, minWidth: 200 }}>
                      <p style={{ color: '#f1f5f9', fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
                        {lead.business_name} — Audit Summary
                      </p>
                      <p style={{ color: '#94a3b8', fontSize: 13, lineHeight: 1.6, marginBottom: 10 }}>
                        {audit.audit_summary}
                      </p>
                      {/* Pass/Warn/Fail counters */}
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                        {[['PASS','#22c55e','#052e16'], ['WARN','#f59e0b','#1c1407'], ['FAIL','#ef4444','#2d0b0b']].map(([s, color, bg]) => (
                          <div key={s} style={{ padding: '4px 12px', borderRadius: 8, background: bg, border: `1px solid ${color}33` }}>
                            <span style={{ color, fontWeight: 800, fontSize: 18 }}>{counts[s] ?? 0}</span>
                            <span style={{ color: '#64748b', fontSize: 11, marginLeft: 5 }}>{s}</span>
                          </div>
                        ))}
                      </div>
                      {audit.site_summary?.total_pages > 0 && (
                        <p style={{ color: '#64748b', fontSize: 11, marginBottom: 6 }}>
                          Pages crawled: {audit.site_summary.total_pages}
                          {audit.audited_url ? ` | URL: ${audit.audited_url.replace(/^https?:\/\//, '')}` : ''}
                        </p>
                      )}
                      {audit.missing_social?.length > 0 && (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                          <span style={{ color: '#64748b', fontSize: 11 }}>Missing social:</span>
                          {audit.missing_social.map(p => (
                            <span key={p} style={{ padding: '2px 8px', borderRadius: 6, background: '#3f1515', color: '#f87171', fontSize: 11, fontWeight: 600 }}>{p}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 6 Axis score rings */}
                  <div style={{
                    background: '#0f172a', border: '1px solid #1e2d44', borderRadius: 14,
                    padding: '16px 20px', marginBottom: 20,
                  }}>
                    <p style={{ color: '#64748b', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
                      Performance by Axis
                    </p>
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', justifyContent: 'space-around' }}>
                      {(() => {
                        const axisScore = (key) => {
                          const grp = audit.audit_results?.[key]
                          if (!grp) return null
                          const vals = Object.values(grp)
                          if (!vals.length) return null
                          return Math.round(vals.reduce((s,r) => s + (r.status==='PASS'?1:r.status==='WARN'?0.5:0), 0) / vals.length * 100)
                        }
                        const checksScore = (keys) => {
                          const valid = keys.map(k => getCheckStatus(k, audit)).filter(Boolean)
                          if (!valid.length) return null
                          return Math.round(valid.reduce((s,st) => s + (st==='PASS'?1:st==='WARN'?0.5:0), 0) / valid.length * 100)
                        }
                        return [
                          { label: 'Technical',  icon: '🔧', score: axisScore('technical'),  color: '#3b82f6' },
                          { label: 'On-Page',    icon: '📄', score: axisScore('onpage'),      color: '#a855f7' },
                          { label: 'Images',     icon: '🖼️', score: axisScore('images'),      color: '#14b8a6' },
                          { label: 'Links',      icon: '🔗', score: axisScore('links'),       color: '#f97316' },
                          { label: 'Conversion', icon: '💼', score: axisScore('conversion'),  color: '#10b981' },
                          { label: 'UI/UX',      icon: '🎨', score: audit.ux_score ?? null,   color: '#d946ef' },
                          { label: 'Indexability',icon:'🗂️', score: checksScore(['has_noindex','url_structure_ok','www_nonwww_ok','soft_404_ok']), color: '#06b6d4' },
                          { label: 'Content',    icon: '✍️', score: checksScore(['word_count_ok','duplicate_meta_ok','keyword_in_title_ok','reading_level_ok']), color: '#8b5cf6' },
                          { label: 'Local SEO',  icon: '📍', score: checksScore(['has_nap','has_local_business_schema','has_google_maps','city_in_title_ok','has_business_hours']), color: '#f43f5e' },
                          { label: 'Perf.',      icon: '⚡', score: checksScore(['response_time_ok','page_size_ok','render_blocking_ok','gzip_enabled','webp_coverage_ok','minification_ok']), color: '#facc15' },
                          { label: 'Schema+',    icon: '🧩', score: checksScore(['has_faq_schema','has_product_schema','has_breadcrumb_schema','has_review_schema','schema_graph_ok']), color: '#34d399' },
                        ].map(ax => <AxisRing key={ax.label} {...ax} />)
                      })()}
                    </div>
                  </div>

                  {/* 6 Group Cards */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 20 }}>
                    {AUDIT_GROUPS.map(group => (
                      <div key={group.id} style={{
                        background: '#131c2e',
                        border: `1px solid ${group.color || '#1e2d44'}33`,
                        borderTop: `3px solid ${group.color || '#334155'}`,
                        borderRadius: 14, padding: '16px 16px 8px',
                      }}>
                        <p style={{
                          fontWeight: 800, fontSize: 13, marginBottom: 12,
                          display: 'flex', alignItems: 'center', gap: 7,
                          color: group.color || '#cbd5e1',
                        }}>
                          <span>{group.icon}</span> {group.label}
                        </p>
                        {group.checks.map(check => (
                          <CheckCard key={check.key} check={check} audit={audit} />
                        ))}
                        {group.id === 'links' && (audit.broken_links_count ?? 0) > 0 && (
                          <p style={{ color: '#64748b', fontSize: 11, marginTop: 4 }}>
                            {audit.broken_links_count} broken link(s) detected.
                          </p>
                        )}
                        {group.id === 'ux' && audit.nav_links_count !== null && audit.nav_links_count !== undefined && (
                          <p style={{ color: '#64748b', fontSize: 11, marginTop: 4 }}>
                            Navigation links detected: {audit.nav_links_count}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Audits() {
  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [viewFilter, setViewFilter] = useState('all')  // all | audited | not-audited | emailed
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  const pageSize = 50

  // Debounce search input — only trigger API call 400 ms after user stops typing
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchQuery), 400)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Reset to page 1 whenever search text or view-filter changes
  useEffect(() => { setPage(1) }, [debouncedSearch, viewFilter])

  async function fetchLeads() {
    setLoading(true)
    try {
      // Derive status param for server-side filtering
      let statusParam = ''
      if (viewFilter === 'audited')     statusParam = 'audited'
      else if (viewFilter === 'not-audited') statusParam = 'new'
      else if (viewFilter === 'emailed')     statusParam = 'emailed'

      // Pass q to API → searches entire DB, not just current page
      const res = await getLeads({
        page,
        page_size: pageSize,
        ...(statusParam && { status: statusParam }),
        ...(debouncedSearch.trim() && { q: debouncedSearch.trim() }),
      })
      setLeads(res.data.items)
      setTotal(res.data.total)
    } catch {
      toast.error('Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLeads() }, [page, debouncedSearch, viewFilter])

  // Server-side filtering: leads array is already filtered by API
  const filtered = leads

  const totalPages = Math.ceil(total / pageSize)

  // Stats show counts for current result set
  const stats = {
    audited: leads.filter(l => l.status === 'audited' || l.status === 'emailed' || l.status === 'replied' || l.status === 'converted').length,
    notAudited: leads.filter(l => l.status === 'new').length,
    emailed: leads.filter(l => l.status === 'emailed' || l.status === 'replied' || l.status === 'converted').length,
  }

  return (
    <div className="p-8 page-enter">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">SEO Audits</h1>
          <p className="text-slate-500 text-sm mt-1">Click a row to expand audit findings. Download PDF per lead.</p>
        </div>
        <button onClick={fetchLeads} className="btn-secondary">
          <RefreshCw size={16} />
        </button>
      </div>

      {/* Search bar */}
      <div style={{
        position: 'relative',
        marginBottom: 16,
        maxWidth: 400,
      }}>
        <Search
          size={15}
          style={{
            position: 'absolute', left: 12, top: '50%',
            transform: 'translateY(-50%)',
            color: '#475569', pointerEvents: 'none',
          }}
        />
        <input
          id="audit-search"
          type="text"
          placeholder="Search business name or website…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 36px 8px 36px',
            background: '#1e2535',
            border: '1px solid #334155',
            borderRadius: 8,
            color: '#e2e8f0',
            fontSize: 13,
            outline: 'none',
            boxSizing: 'border-box',
            transition: 'border-color 0.15s',
          }}
          onFocus={e => e.target.style.borderColor = '#3b82f6'}
          onBlur={e => e.target.style.borderColor = '#334155'}
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            style={{
              position: 'absolute', right: 10, top: '50%',
              transform: 'translateY(-50%)',
              background: 'none', border: 'none',
              cursor: 'pointer', color: '#475569', padding: 2,
              display: 'flex', alignItems: 'center',
            }}
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* Filter tabs — total counts are from API (full DB) */}
      <div className="flex gap-2 mb-4">
        {[
          { key: 'all', label: viewFilter === 'all' ? `All (${total})` : 'All' },
          { key: 'audited', label: viewFilter === 'audited' ? `Audited (${total})` : 'Audited' },
          { key: 'not-audited', label: viewFilter === 'not-audited' ? `Not Audited (${total})` : 'Not Audited' },
          { key: 'emailed', label: viewFilter === 'emailed' ? `Emailed (${total})` : 'Emailed' },
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setViewFilter(tab.key)}
            style={{
              padding: '5px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              border: viewFilter === tab.key ? '1px solid rgba(37,99,235,0.5)' : '1px solid #334155',
              background: viewFilter === tab.key ? 'rgba(37,99,235,0.15)' : 'transparent',
              color: viewFilter === tab.key ? '#60a5fa' : '#94a3b8',
              transition: 'all 0.15s',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="card p-0 overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface">
            <tr>
              <th className="th">Business</th>
              <th className="th">Website</th>
              <th className="th">Status</th>
              <th className="th">Date</th>
              <th className="th">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="td text-center py-12"><span className="spinner" /></td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} className="td text-center py-12 text-slate-500">
                {viewFilter === 'not-audited'
                  ? 'All leads on this page have been audited!'
                  : 'No leads found for this filter.'}
              </td></tr>
            ) : filtered.map(lead => <AuditRow key={lead.id} lead={lead} />)}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-3 mt-4">
          <span className="text-xs text-slate-500">Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="btn-secondary py-1.5 px-3 text-xs"
            style={{ opacity: page <= 1 ? 0.4 : 1 }}
          >
            Previous
          </button>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="btn-secondary py-1.5 px-3 text-xs"
            style={{ opacity: page >= totalPages ? 0.4 : 1 }}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
