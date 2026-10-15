import { useEffect, useState } from 'react'
import {
  RefreshCw, Download, ChevronDown, ChevronUp, AlertTriangle, Search, X,
  Globe, ShieldCheck, FileCode, CheckCircle2, AlertCircle, XCircle, ArrowRight,
  ExternalLink, Layers, Cpu, Compass, LayoutGrid, ListFilter, Bot, Check, AlertOctagon,
  Send, CheckCheck, FileText, Play
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getLeads, getAudit, getPdfUrl, getProposal, approveProposal, sendProposal,
  getAiSearchStatus, getAiReadiness, runAiVisibilityCheck, getAiSearchHistory, getLatestAiSearchRun
} from '../api/client'
import BrowserEvidence from '../components/BrowserEvidence'

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
      { key: 'social', label: 'Social Profile Links', priority: 'LOW', invert: false,
        why: 'Social profiles help visitors verify business authenticity and brand presence.',
        fix: 'Link active Facebook, Instagram, LinkedIn or other business profiles from the header or footer.' },
      { key: 'has_contact', label: 'Clickable Phone / Email', priority: 'HIGH', invert: false,
        why: 'Clickable contact links allow mobile visitors to connect directly via tel: or mailto: protocols.',
        fix: 'Use <a href="tel:..."> for phone numbers and <a href="mailto:..."> for email links on key pages.' },
      { key: 'has_whatsapp', label: 'WhatsApp Integration', priority: 'LOW', invert: false,
        why: 'A direct messaging link provides an immediate, low-friction inquiry channel for customers.',
        fix: 'Add a WhatsApp chat link or floating button directing to your verified business number.' },
      { key: 'has_trust', label: 'Privacy Policy / Terms', priority: 'MEDIUM', invert: false,
        why: 'Clear privacy policy and terms pages build trust and inform visitors how their data is handled.',
        fix: 'Add accessible /privacy-policy and /terms links in the site footer.' },
    ],
  },
  {
    id: 'ux', label: 'UI/UX & Experience', icon: '🎨',
    color: '#d946ef',
    checks: [
      { key: 'has_cta', label: 'Call-to-Action Button', priority: 'HIGH', invert: false,
        why: 'A visible call to action guides visitors toward making an inquiry or taking the next step.',
        fix: 'Add a clear primary CTA button (e.g., "Request a Quote", "Book Service") with contrasting style.' },
      { key: 'cta_above_fold', label: 'CTA Above the Fold', priority: 'MEDIUM', invert: false,
        why: 'Displaying primary contact actions early in the hero area ensures visibility without extensive scrolling.',
        fix: 'Position key action buttons within the initial viewport area across screen sizes.' },
      { key: 'has_hero_headline', label: 'Hero Value Proposition', priority: 'HIGH', invert: false,
        why: 'A clear introductory headline communicates what services the business offers.',
        fix: 'Include a descriptive heading at the top of the homepage explaining your primary service.' },
      { key: 'font_size_ok', label: 'Text Readability (Font Size)', priority: 'MEDIUM', invert: false,
        why: 'Body text smaller than 14px can be difficult to read comfortably on mobile screens.',
        fix: 'Set body typography font-size to at least 15–16px in your stylesheet.' },
      { key: 'contrast_ok', label: 'Colour Contrast', priority: 'MEDIUM', invert: false,
        why: 'Adequate contrast between text and background ensures content is legible under various lighting conditions.',
        fix: 'Ensure text-to-background contrast ratio meets readability standards (minimum 4.5:1 for body text).' },
      { key: 'nav_ok', label: 'Navigation Menu', priority: 'HIGH', invert: false,
        why: 'A structured navigation menu enables visitors and crawlers to access essential service pages.',
        fix: 'Provide a clear header navigation menu linking to core service and contact pages.' },
      { key: 'has_cookie_notice', label: 'Cookie Notice / Privacy Banner', priority: 'LOW', invert: false,
        why: 'Informs visitors about site tracking and cookie usage where applicable by regional guidelines.',
        fix: 'Display a concise privacy/cookie banner if your site uses tracking scripts or non-essential cookies.' },
      { key: 'has_live_chat', label: 'Live Chat / Messaging Widget', priority: 'LOW', invert: false,
        why: 'An on-site chat interface provides real-time customer assistance.',
        fix: 'Integrate a customer messaging widget or responsive WhatsApp support link.' },
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

function structuredGroups(audit) {
  return Object.entries(audit?.audit_results || {}).map(([id, results]) => ({
    id,
    label: id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    checks: Object.entries(results || {}).map(([key, result]) => ({
      key,
      label: (result?.id || `${id}.${key}`).split('.').pop().replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      result,
      priority: result?.severity?.toUpperCase(),
    })),
  })).filter(group => group.checks.length)
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
  'N/A': { bg: '#172033', border: '#47556955', color: '#94a3b8', dot: '#64748b', label: 'N/A' },
  ERROR: { bg: '#2d0b0b', border: '#dc262655', color: '#fca5a5', dot: '#dc2626', label: 'ERROR' },
  UNKNOWN: { bg: '#172033', border: '#64748b55', color: '#cbd5e1', dot: '#94a3b8', label: 'UNKNOWN' },
}

function CheckCard({ check, audit }) {
  const raw = check.result || getRawResult(check.key, audit)
  const status = raw?.status || getCheckStatus(check.key, audit)
  const s = STATUS_STYLE[status] || STATUS_STYLE.UNKNOWN
  const message = raw?.message || check.why || 'No structured observation recorded.'
  const fix = raw?.fix || check.fix
  const priority = (raw?.severity || check.priority || 'MEDIUM').toUpperCase()
  const priClass = priority === 'CRITICAL' ? 'pri-critical' : priority === 'HIGH' ? 'pri-high' : priority === 'LOW' ? 'pri-low' : 'pri-medium'

  return (
    <div style={{
      background: 'linear-gradient(145deg, #121b2b 0%, #0d1522 100%)',
      border: `1px solid ${status === 'FAIL' ? '#7f1d1d88' : status === 'WARN' ? '#78350f88' : '#1e293b'}`,
      borderLeft: `4px solid ${s.dot}`,
      borderRadius: 10,
      padding: '14px 16px',
      marginBottom: 10,
      boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6, gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{ color: '#f8fafc', fontWeight: 700, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {check.label}
          </span>
          <span className={`badge ${priClass}`} style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.06em', flexShrink: 0 }}>
            {priority}
          </span>
        </div>
        <span style={{
          padding: '2px 9px', borderRadius: 20, fontSize: 10, fontWeight: 800,
          background: s.border, color: s.color, letterSpacing: '0.05em', flexShrink: 0,
        }}>
          {s.label}
        </span>
      </div>

      <p style={{ color: '#94a3b8', fontSize: 12, margin: '4px 0 6px', lineHeight: 1.55 }}>
        {message}
      </p>

      {raw?.value !== null && raw?.value !== undefined && (
        <div style={{ background: '#090e17', borderRadius: 6, padding: '4px 8px', margin: '6px 0', border: '1px solid #1e293b' }}>
          <span style={{ color: '#64748b', fontSize: 11, fontWeight: 600 }}>Detected Value: </span>
          <span style={{ color: '#93c5fd', fontSize: 11, fontFamily: 'monospace' }}>
            {Array.isArray(raw.value) ? raw.value.join(', ') : String(raw.value)}{raw.unit ? ` ${raw.unit}` : ''}
          </span>
        </div>
      )}

      {raw?.detail && (
        <p style={{ color: '#64748b', fontSize: 11, margin: '4px 0 0', lineHeight: 1.45, fontStyle: 'italic' }}>
          {raw.detail}
        </p>
      )}

      {status !== 'PASS' && fix && (
        <div style={{
          marginTop: 8,
          padding: '6px 10px',
          borderRadius: 6,
          background: 'rgba(59, 130, 246, 0.08)',
          border: '1px solid rgba(59, 130, 246, 0.2)',
          display: 'flex',
          gap: 6,
          alignItems: 'flex-start',
        }}>
          <ArrowRight size={13} style={{ color: '#60a5fa', flexShrink: 0, marginTop: 2 }} />
          <span style={{ color: '#93c5fd', fontSize: 11, lineHeight: 1.45 }}>
            <strong style={{ color: '#bfdbfe' }}>Recommended fix: </strong>{fix}
          </span>
        </div>
      )}
    </div>
  )
}

function AxisRing({ label, icon, score, color }) {
  const isNull = score === null || score === undefined
  const pct = isNull ? 0 : Math.min(100, Math.max(0, score))
  const r = 26
  const circ = 2 * Math.PI * r
  const dash = (pct / 100) * circ
  const ringColor = pct >= 75 ? color : pct >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 84,
      background: '#0a101d', border: '1px solid #1a2436', borderRadius: 12, padding: '10px 8px',
    }}>
      <div style={{ position: 'relative', width: 64, height: 64 }}>
        <svg width={64} height={64} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={32} cy={32} r={r} fill="none" stroke="#162032" strokeWidth={5} />
          <circle cx={32} cy={32} r={r} fill="none" stroke={ringColor} strokeWidth={5}
            strokeDasharray={`${dash} ${circ - dash}`} strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 5px ${ringColor}88)`, transition: 'stroke-dasharray 0.6s ease' }}
          />
        </svg>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          {isNull
            ? <span style={{ fontSize: 9, color: '#475569', textAlign: 'center', lineHeight: 1.2 }}>N/A</span>
            : <span style={{ fontSize: 15, fontWeight: 900, color: ringColor, lineHeight: 1 }}>{pct}%</span>
          }
        </div>
      </div>
      <span style={{ fontSize: 10, color: '#cbd5e1', textAlign: 'center', marginTop: 6, fontWeight: 700, lineHeight: 1.2 }}>
        {icon} {label}
      </span>
    </div>
  )
}

function ScoreGauge({ score }) {
  const color = score >= 75 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'
  const label = score >= 75 ? 'Good' : score >= 50 ? 'Needs Attention' : 'Critical Defects'
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(145deg, #0b111e 0%, #060a12 100%)',
      border: `2px solid ${color}44`,
      borderRadius: 16, padding: '18px 24px', minWidth: 140,
      boxShadow: `0 8px 20px -4px ${color}22`,
    }}>
      <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 800, marginBottom: 4 }}>
        Overall Score
      </span>
      <span style={{ fontSize: 44, fontWeight: 900, color, lineHeight: 1, letterSpacing: '-0.02em' }}>
        {score}
      </span>
      <span style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>out of 100</span>
      <span style={{
        marginTop: 8, padding: '3px 12px', borderRadius: 20,
        background: `${color}20`, color, fontWeight: 800, fontSize: 10,
        letterSpacing: '0.04em', border: `1px solid ${color}40`,
      }}>
        {label}
      </span>
    </div>
  )
}

function AuditRow({ lead }) {
  const [audit, setAudit] = useState(null)
  const [open, setOpen]   = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('findings')
  const [findingSearch, setFindingSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [priorityFilter, setPriorityFilter] = useState('ALL')
  const [selectedGroup, setSelectedGroup] = useState('ALL')

  const [proposal, setProposal] = useState(null)
  const [loadingProposal, setLoadingProposal] = useState(false)
  const [approving, setApproving] = useState(false)
  const [sendingSimulation, setSendingSimulation] = useState(false)

  async function loadProposal() {
    setLoadingProposal(true)
    try {
      const res = await getProposal(lead.id)
      setProposal(res.data)
    } catch {
      toast.error('Could not load proposal for this lead')
    } finally {
      setLoadingProposal(false)
    }
  }

  async function handleApproveProposal() {
    setApproving(true)
    try {
      const res = await approveProposal(lead.id)
      setProposal(res.data)
      toast.success('Proposal explicitly approved for outreach!')
    } catch {
      toast.error('Failed to record approval')
    } finally {
      setApproving(false)
    }
  }

  async function handleSendSimulation() {
    if (!proposal?.approved) {
      toast.error('Human approval is required before delivery!')
      return
    }
    setSendingSimulation(true)
    try {
      const res = await sendProposal(lead.id, lead.email, true)
      toast.success(res.data?.message || 'Simulation test successful (dry run)!')
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || 'Delivery simulation failed')
    } finally {
      setSendingSimulation(false)
    }
  }

  const [aiStatus, setAiStatus] = useState(null)
  const [aiReadiness, setAiReadiness] = useState(null)
  const [aiLatestRun, setAiLatestRun] = useState(null)
  const [aiHistory, setAiHistory] = useState([])
  const [loadingAiData, setLoadingAiData] = useState(false)
  const [runningAiCheck, setRunningAiCheck] = useState(false)
  const [expandedQueryIdx, setExpandedQueryIdx] = useState(null)

  async function loadAiData() {
    setLoadingAiData(true)
    try {
      const [statusRes, readinessRes] = await Promise.allSettled([
        getAiSearchStatus(),
        getAiReadiness(lead.id),
      ])
      if (statusRes.status === 'fulfilled') setAiStatus(statusRes.value.data)
      if (readinessRes.status === 'fulfilled') setAiReadiness(readinessRes.value.data)

      try {
        const latestRes = await getLatestAiSearchRun(lead.id)
        setAiLatestRun(latestRes.data)
      } catch {
        setAiLatestRun(null)
      }

      try {
        const histRes = await getAiSearchHistory(lead.id)
        setAiHistory(histRes.data?.runs || [])
      } catch {
        setAiHistory([])
      }
    } catch {
      // ignore
    } finally {
      setLoadingAiData(false)
    }
  }

  async function handleRunAiVisibilityCheck() {
    if (!aiStatus?.monitoring_enabled) {
      toast.error('AI-Search provider is not configured. Set AI_SEARCH_PROVIDER_KEY in server environment.')
      return
    }
    setRunningAiCheck(true)
    try {
      const res = await runAiVisibilityCheck({
        lead_id: lead.id,
        brand_name: lead.business_name,
        domain: lead.website,
        query_budget: 10,
      })
      setAiLatestRun(res.data)
      toast.success('Live AI-search visibility check completed!')
      try {
        const histRes = await getAiSearchHistory(lead.id)
        setAiHistory(histRes.data?.runs || [])
      } catch {}
    } catch (err) {
      const detail = err.response?.data?.detail || 'Visibility check execution failed.'
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    } finally {
      setRunningAiCheck(false)
    }
  }

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

  // Canonical groups and counts
  const groups = structuredGroups(audit)
  const allChecks = groups.flatMap(g => g.checks.map(c => ({ ...c, groupId: g.id, groupLabel: g.label })))
  const counts = audit ? allChecks.reduce((acc, c) => {
    const s = c.result?.status || getCheckStatus(c.key, audit); acc[s] = (acc[s] || 0) + 1; return acc
  }, {}) : {}

  const criticalCount = audit ? allChecks.filter(c => ((c.result?.severity || c.priority) === 'CRITICAL') && ((c.result?.status || getCheckStatus(c.key, audit)) === 'FAIL')).length : 0
  const highCount = audit ? allChecks.filter(c => ((c.result?.severity || c.priority) === 'HIGH') && ((c.result?.status || getCheckStatus(c.key, audit)) === 'FAIL')).length : 0

  // Filtered checks for findings tab
  const filteredChecks = allChecks.filter(c => {
    const status = c.result?.status || getCheckStatus(c.key, audit)
    const priority = (c.result?.severity || c.priority || 'MEDIUM').toUpperCase()
    if (statusFilter !== 'ALL' && status !== statusFilter) return false
    if (priorityFilter !== 'ALL' && priority !== priorityFilter) return false
    if (selectedGroup !== 'ALL' && c.groupId !== selectedGroup) return false
    if (findingSearch.trim()) {
      const q = findingSearch.toLowerCase()
      const matchLabel = c.label.toLowerCase().includes(q)
      const matchMsg = (c.result?.message || c.why || '').toLowerCase().includes(q)
      const matchFix = (c.result?.fix || c.fix || '').toLowerCase().includes(q)
      if (!matchLabel && !matchMsg && !matchFix) return false
    }
    return true
  })

  // URL identity extraction
  const requestedUrl = audit?.requested_url || audit?.audited_url || lead.website || '—'
  const finalUrl = audit?.final_url || audit?.audited_url || lead.website || '—'
  const canonicalUrl = audit?.canonical_url || audit?.audit_results?.technical?.canonical?.value || '—'
  const isRedirected = requestedUrl !== '—' && finalUrl !== '—' && requestedUrl.replace(/\/$/, '') !== finalUrl.replace(/\/$/, '')
  const hasCanonical = canonicalUrl !== '—' && canonicalUrl !== null
  const isCanonicalSame = hasCanonical && finalUrl !== '—' && canonicalUrl.replace(/\/$/, '') === finalUrl.replace(/\/$/, '')

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
              <span style={{ fontSize: 10, color: '#475569' }}>view audit</span>
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
          <td colSpan={5} style={{ background: '#080d17', padding: 0 }}>
            <div style={{ padding: '28px 32px' }} className="page-enter">
              {isSkipped ? (
                <div className="flex items-start gap-3 p-4 bg-amber-950/30 border border-amber-800/50 rounded-xl">
                  <AlertTriangle size={20} className="text-amber-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-semibold text-amber-300 mb-1">Audit Skipped</p>
                    <p className="text-sm text-slate-400 leading-relaxed">{audit.audit_summary}</p>
                    <p className="text-xs text-slate-600 mt-2">Target site did not respond as a real/active website.</p>
                  </div>
                </div>
              ) : (
                <>
                  {/* ── 1. Executive URL Identity & Overview Hero ── */}
                  <div className="card-elevated p-6 mb-6">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16, marginBottom: 20 }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                          <h2 style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.01em' }}>
                            {lead.business_name}
                          </h2>
                          <span className="badge badge-blue">Verified Audit</span>
                          {audit.browser_status === 'SUCCESS' && (
                            <span className="badge badge-green" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                              <Cpu size={11} /> Browser Rendered
                            </span>
                          )}
                        </div>
                        <p style={{ color: '#94a3b8', fontSize: 13, maxWidth: 750, lineHeight: 1.6 }}>
                          {audit.audit_summary}
                        </p>
                      </div>

                      {hasPdf && (
                        <a href={getPdfUrl(lead.id)} target="_blank" rel="noreferrer"
                          className="btn-primary" style={{ padding: '8px 16px', fontSize: 13, borderRadius: 8 }}>
                          <Download size={15} /> Download Client PDF
                        </a>
                      )}
                    </div>

                    {/* URL Identity Triple Block */}
                    <div style={{
                      background: '#090e18', border: '1px solid #1e293b', borderRadius: 10,
                      padding: '14px 18px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14,
                    }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          <Globe size={13} style={{ color: '#60a5fa' }} />
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Requested Target
                          </span>
                        </div>
                        <span className="url-badge" title={requestedUrl}>{requestedUrl}</span>
                      </div>

                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          <ArrowRight size={13} style={{ color: isRedirected ? '#f59e0b' : '#10b981' }} />
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Final Destination URL
                          </span>
                          <span style={{ fontSize: 10, fontWeight: 700, color: isRedirected ? '#f59e0b' : '#10b981', marginLeft: 'auto' }}>
                            {isRedirected ? 'Redirected' : 'Direct'}
                          </span>
                        </div>
                        <span className="url-badge" title={finalUrl}>{finalUrl}</span>
                      </div>

                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          <FileCode size={13} style={{ color: '#a855f7' }} />
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Declared Canonical
                          </span>
                          <span style={{ fontSize: 10, fontWeight: 700, color: isCanonicalSame ? '#10b981' : hasCanonical ? '#f59e0b' : '#64748b', marginLeft: 'auto' }}>
                            {isCanonicalSame ? 'Self-Canonical' : hasCanonical ? 'Canonical Alternate' : 'None'}
                          </span>
                        </div>
                        <span className="url-badge" title={canonicalUrl}>{canonicalUrl}</span>
                      </div>
                    </div>
                  </div>

                  {/* ── 2. Primary Health & Score Counters Bar ── */}
                  <div style={{ display: 'flex', gap: 16, alignItems: 'stretch', marginBottom: 24, flexWrap: 'wrap' }}>
                    <ScoreGauge score={computeScore(audit)} />

                    <div style={{
                      flex: 1, minWidth: 260, display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12,
                    }}>
                      <div style={{ background: '#0a1220', border: '1px solid #1e2c40', borderRadius: 12, padding: '14px 16px' }}>
                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600, display: 'block', marginBottom: 4 }}>Verified Passes</span>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                          <span style={{ fontSize: 28, fontWeight: 900, color: '#4ade80' }}>{counts.PASS ?? 0}</span>
                          <span style={{ fontSize: 11, color: '#64748b' }}>factors</span>
                        </div>
                      </div>

                      <div style={{ background: '#14120a', border: '1px solid #33260a', borderRadius: 12, padding: '14px 16px' }}>
                        <span style={{ fontSize: 11, color: '#facc15', fontWeight: 600, display: 'block', marginBottom: 4 }}>Warnings</span>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                          <span style={{ fontSize: 28, fontWeight: 900, color: '#facc15' }}>{counts.WARN ?? 0}</span>
                          <span style={{ fontSize: 11, color: '#64748b' }}>warnings</span>
                        </div>
                      </div>

                      <div style={{ background: '#1c0c0e', border: '1px solid #4a141b', borderRadius: 12, padding: '14px 16px' }}>
                        <span style={{ fontSize: 11, color: '#f87171', fontWeight: 600, display: 'block', marginBottom: 4 }}>Confirmed Defects</span>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                          <span style={{ fontSize: 28, fontWeight: 900, color: '#f87171' }}>{counts.FAIL ?? 0}</span>
                          <span style={{ fontSize: 11, color: '#64748b' }}>defects</span>
                        </div>
                      </div>

                      <div style={{ background: '#0e1626', border: '1px solid #1d2a42', borderRadius: 12, padding: '14px 16px' }}>
                        <span style={{ fontSize: 11, color: '#60a5fa', fontWeight: 600, display: 'block', marginBottom: 4 }}>Priority Actions</span>
                        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                          <span className="badge pri-critical" title="Critical blockers">{criticalCount} Critical</span>
                          <span className="badge pri-high" title="High priority signals">{highCount} High</span>
                        </div>
                      </div>

                      <div style={{ background: '#0a101d', border: '1px solid #1a2538', borderRadius: 12, padding: '14px 16px' }}>
                        <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600, display: 'block', marginBottom: 4 }}>Pages Crawled</span>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                          <span style={{ fontSize: 28, fontWeight: 900, color: '#e2e8f0' }}>{audit.site_summary?.total_pages || 1}</span>
                          <span style={{ fontSize: 11, color: '#64748b' }}>crawled</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* ── 3. 11 Canonical Category Performance Rings ── */}
                  <div className="card-elevated p-5 mb-6">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                      <p style={{ color: '#94a3b8', fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        Category Performance (Canonical 11-Axis Model)
                      </p>
                      <span style={{ fontSize: 11, color: '#64748b' }}>62 Factor Verified Contract</span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 10 }}>
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

                  {/* ── 4. Diagnostics Workspace Tabs Navigation ── */}
                  <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap', borderBottom: '1px solid #1e293b', paddingBottom: 12 }}>
                    <button
                      onClick={() => setActiveTab('findings')}
                      className={`tab-pill ${activeTab === 'findings' ? 'tab-pill-active' : ''}`}
                    >
                      <LayoutGrid size={15} /> All Findings & Checklist ({allChecks.length})
                    </button>
                    <button
                      onClick={() => setActiveTab('sitemap')}
                      className={`tab-pill ${activeTab === 'sitemap' ? 'tab-pill-active' : ''}`}
                    >
                      <FileCode size={15} /> Robots & Sitemap Diagnostics
                    </button>
                    <button
                      onClick={() => setActiveTab('crawl')}
                      className={`tab-pill ${activeTab === 'crawl' ? 'tab-pill-active' : ''}`}
                    >
                      <Compass size={15} /> Crawl Coverage ({audit.site_summary?.total_pages || 1} pages)
                    </button>
                    <button
                      onClick={() => setActiveTab('browser')}
                      className={`tab-pill ${activeTab === 'browser' ? 'tab-pill-active' : ''}`}
                    >
                      <Cpu size={15} /> Browser vs Raw Evidence
                    </button>
                    <button
                      onClick={() => { setActiveTab('ai_search'); if (!aiStatus) loadAiData(); }}
                      className={`tab-pill ${activeTab === 'ai_search' ? 'tab-pill-active' : ''}`}
                    >
                      <Bot size={15} /> AI Search & GSC Readiness
                    </button>
                    <button
                      onClick={() => { setActiveTab('proposal'); if (!proposal) loadProposal(); }}
                      className={`tab-pill ${activeTab === 'proposal' ? 'tab-pill-active' : ''}`}
                    >
                      <Send size={15} /> Service Proposal & Outreach Offer
                    </button>
                  </div>

                  {/* ── 5. TAB CONTENT PANELS ── */}

                  {/* Tab 1: Findings & Checklist */}
                  {activeTab === 'findings' && (
                    <div>
                      {/* Search and Filters Bar */}
                      <div style={{
                        background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10,
                        padding: '12px 16px', marginBottom: 20, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center',
                      }}>
                        <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
                          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#64748b' }} />
                          <input
                            type="text"
                            placeholder="Filter findings by keyword..."
                            value={findingSearch}
                            onChange={e => setFindingSearch(e.target.value)}
                            style={{
                              width: '100%', padding: '6px 10px 6px 30px', background: '#0e1626',
                              border: '1px solid #24344d', borderRadius: 6, color: '#f1f5f9', fontSize: 12, outline: 'none',
                            }}
                          />
                        </div>

                        {/* Status filter */}
                        <div style={{ display: 'flex', gap: 4 }}>
                          {['ALL', 'FAIL', 'WARN', 'PASS'].map(st => (
                            <button
                              key={st}
                              onClick={() => setStatusFilter(st)}
                              style={{
                                padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                                background: statusFilter === st ? '#1e3a8a' : '#0e1626',
                                color: statusFilter === st ? '#93c5fd' : '#64748b',
                                border: statusFilter === st ? '1px solid #3b82f6' : '1px solid #1e293b',
                              }}
                            >
                              {st}
                            </button>
                          ))}
                        </div>

                        {/* Priority filter */}
                        <div style={{ display: 'flex', gap: 4 }}>
                          {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(pr => (
                            <button
                              key={pr}
                              onClick={() => setPriorityFilter(pr)}
                              style={{
                                padding: '4px 8px', borderRadius: 6, fontSize: 10, fontWeight: 800, cursor: 'pointer',
                                background: priorityFilter === pr ? '#334155' : '#0e1626',
                                color: priorityFilter === pr ? '#f8fafc' : '#64748b',
                                border: priorityFilter === pr ? '1px solid #64748b' : '1px solid #1e293b',
                              }}
                            >
                              {pr}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Findings Grid */}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
                        {structuredGroups(audit).map(group => {
                          const checksInGroup = filteredChecks.filter(c => c.groupId === group.id)
                          if (!checksInGroup.length) return null

                          return (
                            <div key={group.id} className="card-elevated p-4">
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid #1e293b' }}>
                                <p style={{ fontWeight: 800, fontSize: 13, color: '#f1f5f9', display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <span>{group.label}</span>
                                </p>
                                <span style={{ fontSize: 11, color: '#64748b' }}>
                                  {checksInGroup.length} check{checksInGroup.length > 1 ? 's' : ''}
                                </span>
                              </div>

                              {checksInGroup.map(check => (
                                <CheckCard key={check.key} check={check} audit={audit} />
                              ))}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Tab 2: Robots & Sitemap Deep Diagnostics */}
                  {activeTab === 'sitemap' && (
                    <div className="card-elevated p-6">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                        <FileCode size={20} style={{ color: '#38bdf8' }} />
                        <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc' }}>
                          Robots.txt & XML Sitemap Diagnostics
                        </h3>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 20 }}>
                        {/* Robots Card */}
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Origin Robots Discovery
                          </span>
                          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span className="url-badge">{audit.robots_url || `${new URL(requestedUrl.startsWith('http') ? requestedUrl : `https://${requestedUrl}`).origin}/robots.txt`}</span>
                            <span className="badge badge-green">Checked at origin root</span>
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 10 }}>
                            Robots.txt is always resolved from the domain origin, never from subpath routes.
                          </p>
                        </div>

                        {/* Sitemap Card */}
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                            Sitemap Validation Status
                          </span>
                          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span className="url-badge">{audit.sitemap_url || 'None declared'}</span>
                            <span className={`badge ${audit.has_sitemap ? 'badge-green' : 'badge-yellow'}`}>
                              {audit.has_sitemap ? 'Verified XML' : 'Not Detected'}
                            </span>
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 10 }}>
                            Rejects HTML 200 soft responses. Validates XML structure (&lt;urlset&gt; or &lt;sitemapindex&gt;).
                          </p>
                        </div>
                      </div>

                      {/* Diagnostic Summary Table */}
                      <div style={{ background: '#090e18', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                        <h4 style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 10 }}>
                          Crawl & Parser Safeguards
                        </h4>
                        <ul style={{ color: '#94a3b8', fontSize: 12, lineHeight: 1.8, paddingLeft: 18 }}>
                          <li><strong>Origin Root Derivation:</strong> Extracted scheme and host directly from URL; never appends /robots.txt to inner paths.</li>
                          <li><strong>Structure Deciding Check:</strong> Content-Type hint verified; XML root tag validated; HTML error pages returning HTTP 200 are rejected.</li>
                          <li><strong>Sitemap Index Bounds:</strong> Child sitemaps inspected up to a maximum safety cap of 5; max 100 discovered URLs.</li>
                          <li><strong>Safe Fetching:</strong> SSRF controls, redirect depth limits, and 5MB payload caps strictly enforced.</li>
                        </ul>
                      </div>
                    </div>
                  )}

                  {/* Tab 3: Crawl Coverage */}
                  {activeTab === 'crawl' && (
                    <div className="card-elevated p-6">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                        <Compass size={20} style={{ color: '#a855f7' }} />
                        <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc' }}>
                          Crawl Coverage & Discovered Pages
                        </h3>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 20 }}>
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '14px' }}>
                          <span style={{ fontSize: 11, color: '#64748b' }}>Total Pages Visited</span>
                          <p style={{ fontSize: 24, fontWeight: 900, color: '#f1f5f9', marginTop: 4 }}>
                            {audit.site_summary?.total_pages || 1}
                          </p>
                        </div>
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '14px' }}>
                          <span style={{ fontSize: 11, color: '#64748b' }}>Crawl Depth Limit</span>
                          <p style={{ fontSize: 24, fontWeight: 900, color: '#f1f5f9', marginTop: 4 }}>
                            3 Levels Max
                          </p>
                        </div>
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '14px' }}>
                          <span style={{ fontSize: 11, color: '#64748b' }}>Max Crawl Budget</span>
                          <p style={{ fontSize: 24, fontWeight: 900, color: '#f1f5f9', marginTop: 4 }}>
                            10 Pages
                          </p>
                        </div>
                      </div>

                      <div style={{ background: '#090e18', border: '1px solid #1e293b', borderRadius: 10, overflow: 'hidden' }}>
                        <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
                          <thead style={{ background: '#0e1626', borderBottom: '1px solid #1e293b' }}>
                            <tr>
                              <th style={{ padding: '10px 14px', fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Page URL</th>
                              <th style={{ padding: '10px 14px', fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Status</th>
                              <th style={{ padding: '10px 14px', fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Scope</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td style={{ padding: '10px 14px', fontSize: 12, color: '#e2e8f0', fontFamily: 'monospace' }}>
                                {finalUrl}
                              </td>
                              <td style={{ padding: '10px 14px' }}>
                                <span className="badge badge-green">200 OK</span>
                              </td>
                              <td style={{ padding: '10px 14px', fontSize: 12, color: '#94a3b8' }}>
                                Primary Root Target
                              </td>
                            </tr>
                            {canonicalUrl && canonicalUrl !== '—' && canonicalUrl !== finalUrl && (
                              <tr style={{ borderTop: '1px solid #1e293b' }}>
                                <td style={{ padding: '10px 14px', fontSize: 12, color: '#e2e8f0', fontFamily: 'monospace' }}>
                                  {canonicalUrl}
                                </td>
                                <td style={{ padding: '10px 14px' }}>
                                  <span className="badge badge-blue">Canonical</span>
                                </td>
                                <td style={{ padding: '10px 14px', fontSize: 12, color: '#94a3b8' }}>
                                  Declared Canonical Target
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* Tab 4: Browser vs Raw Evidence */}
                  {activeTab === 'browser' && (
                    <div className="card-elevated p-6">
                      <BrowserEvidence
                        evidence={audit.browser_evidence}
                        status={audit.browser_status}
                        auditResults={audit.audit_results}
                        pages={audit.browser_pages}
                      />
                    </div>
                  )}

                  {/* Tab 5: AI-Search & GSC Readiness */}
                  {activeTab === 'ai_search' && (
                    <div className="card-elevated p-6">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <Bot size={22} style={{ color: '#10b981' }} />
                          <div>
                            <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                              AI-Search Live Visibility & Diagnostics
                            </h3>
                            <span style={{ fontSize: 12, color: '#64748b' }}>
                              Real-time citation tracking via Perplexity Agent API & indexing readiness for {lead.business_name}
                            </span>
                          </div>
                        </div>

                        <div>
                          <button
                            onClick={handleRunAiVisibilityCheck}
                            disabled={runningAiCheck || !aiStatus?.monitoring_enabled}
                            className="btn btn-primary"
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 8,
                              padding: '8px 16px',
                              fontSize: 13,
                              fontWeight: 700,
                              cursor: (runningAiCheck || !aiStatus?.monitoring_enabled) ? 'not-allowed' : 'pointer',
                              opacity: (runningAiCheck || !aiStatus?.monitoring_enabled) ? 0.6 : 1,
                            }}
                            title={!aiStatus?.monitoring_enabled ? 'Set AI_SEARCH_PROVIDER_KEY to enable live sampling' : 'Execute 10-query Perplexity check'}
                          >
                            <RefreshCw size={14} className={runningAiCheck ? 'spin' : ''} />
                            {runningAiCheck ? 'Checking Visibility...' : 'Run Visibility Check'}
                          </button>
                        </div>
                      </div>

                      {/* 1. Status Overview Grid */}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16, marginBottom: 24 }}>
                        {/* Provider Status */}
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Perplexity Agent API
                            </span>
                            {aiStatus?.monitoring_enabled ? (
                              <span className="badge badge-green" style={{ fontSize: 10 }}>Connected</span>
                            ) : (
                              <span className="badge badge-grey" style={{ fontSize: 10 }}>Unconfigured</span>
                            )}
                          </div>
                          <div style={{ marginTop: 10, fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
                            {aiStatus?.monitoring_enabled ? `Active Model: ${aiStatus.model || 'sonar'}` : 'Disconnected'}
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 8, lineHeight: 1.5, margin: 0 }}>
                            {aiStatus?.monitoring_enabled
                              ? 'Authenticated live citation discovery enabled (conservative 10-query budget cap).'
                              : 'External provider key missing. Set AI_SEARCH_PROVIDER_KEY to enable automated sampling.'}
                          </p>
                        </div>

                        {/* Robots.txt AI Crawlers */}
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              AI Crawler Access
                            </span>
                            {aiReadiness?.crawlers?.all_allowed ? (
                              <span className="badge badge-green" style={{ fontSize: 10 }}>Open Access</span>
                            ) : (
                              <span className="badge badge-yellow" style={{ fontSize: 10 }}>Restricted</span>
                            )}
                          </div>
                          <div style={{ marginTop: 10, fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
                            Robots.txt Permissions
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 8, lineHeight: 1.5, margin: 0 }}>
                            {aiReadiness?.crawlers?.blocked?.length
                              ? `Blocked bots: ${aiReadiness.crawlers.blocked.join(', ')}`
                              : 'GPTBot, ClaudeBot, PerplexityBot, and Google-Extended permitted for AI discovery.'}
                          </p>
                        </div>

                        {/* Schema & llms.txt */}
                        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Readiness Signals
                            </span>
                            <span className="badge badge-blue" style={{ fontSize: 10 }}>
                              Score: {aiReadiness?.readiness_score ?? '—'}/100
                            </span>
                          </div>
                          <div style={{ marginTop: 10, fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
                            {aiReadiness?.entity_structure?.has_schema_markup ? 'Schema Markup Detected' : 'Basic Entities'}
                          </div>
                          <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 8, lineHeight: 1.5, margin: 0 }}>
                            {aiReadiness?.llms_txt?.note || 'llms.txt is an optional emerging convention; not a required ranking factor.'}
                          </p>
                        </div>
                      </div>

                      {/* 2. Active Run Progress */}
                      {runningAiCheck && (
                        <div style={{
                          background: '#0e1626', border: '1px solid #3b82f640', borderRadius: 10,
                          padding: '24px', textAlign: 'center', marginBottom: 24,
                        }}>
                          <RefreshCw size={28} className="spin" style={{ color: '#3b82f6', margin: '0 auto 12px auto' }} />
                          <h4 style={{ fontSize: 15, fontWeight: 800, color: '#f8fafc', margin: '0 0 6px 0' }}>
                            Sampling Perplexity Agent API...
                          </h4>
                          <p style={{ color: '#94a3b8', fontSize: 13, margin: 0 }}>
                            Evaluating brand mentions, citations, and source URLs across 10 business queries.
                          </p>
                        </div>
                      )}

                      {/* 3. Latest Visibility Run Results */}
                      {aiLatestRun && (
                        <div>
                          {/* Run Execution Summary Header */}
                          <div style={{
                            background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10,
                            padding: '12px 16px', marginBottom: 16, display: 'flex', justifyContent: 'space-between',
                            alignItems: 'center', flexWrap: 'wrap', gap: 10,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b' }}>Latest Check:</span>
                              <span style={{ fontSize: 12, fontWeight: 800, color: '#f8fafc' }}>
                                {new Date(aiLatestRun.completed_at || aiLatestRun.created_at).toLocaleString()}
                              </span>
                              <span className={`badge ${aiLatestRun.status === 'completed' ? 'badge-green' : aiLatestRun.status === 'partial' ? 'badge-yellow' : 'badge-red'}`} style={{ fontSize: 10 }}>
                                {aiLatestRun.status?.toUpperCase()}
                              </span>
                            </div>
                            <div style={{ fontSize: 12, color: '#94a3b8' }}>
                              <span>Queries: <strong style={{ color: '#f8fafc' }}>{aiLatestRun.queries_succeeded}</strong> succeeded of {aiLatestRun.queries_attempted} attempted</span>
                            </div>
                          </div>

                          {/* Key Metrics Cards */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }}>
                            {/* Brand Mention Rate */}
                            <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Brand Mention Rate
                              </span>
                              <div style={{ fontSize: 28, fontWeight: 900, color: '#10b981', marginTop: 6, lineHeight: 1 }}>
                                {aiLatestRun.brand_mention_rate != null ? `${Math.round(aiLatestRun.brand_mention_rate * 100)}%` : '—'}
                              </div>
                              <span style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginTop: 8 }}>
                                {aiLatestRun.brand_mentions_count || 0} of {aiLatestRun.queries_succeeded} answers mentioned brand
                              </span>
                            </div>

                            {/* Domain Citation Rate */}
                            <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Domain Citation Rate
                              </span>
                              <div style={{ fontSize: 28, fontWeight: 900, color: '#3b82f6', marginTop: 6, lineHeight: 1 }}>
                                {aiLatestRun.citation_rate != null ? `${Math.round(aiLatestRun.citation_rate * 100)}%` : '—'}
                              </div>
                              <span style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginTop: 8 }}>
                                {aiLatestRun.domain_citations_count || 0} of {aiLatestRun.queries_succeeded} queries cited {aiLatestRun.target_domain}
                              </span>
                            </div>

                            {/* Share of Voice */}
                            <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Share of Voice
                              </span>
                              <div style={{ fontSize: 28, fontWeight: 900, color: '#a855f7', marginTop: 6, lineHeight: 1 }}>
                                {aiLatestRun.share_of_voice != null ? `${Math.round(aiLatestRun.share_of_voice * 100)}%` : '100%'}
                              </div>
                              <span style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginTop: 8 }}>
                                Brand vs detected competitor citations
                              </span>
                            </div>

                            {/* Provider & Usage */}
                            <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, padding: '16px' }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                API Tokens & Engine
                              </span>
                              <div style={{ fontSize: 24, fontWeight: 900, color: '#facc15', marginTop: 6, lineHeight: 1 }}>
                                {aiLatestRun.usage?.total_tokens ? aiLatestRun.usage.total_tokens.toLocaleString() : '—'}
                              </div>
                              <span style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginTop: 8 }}>
                                {aiLatestRun.provider} ({aiLatestRun.model})
                              </span>
                            </div>
                          </div>

                          {/* Query Evidence Table */}
                          <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10, overflow: 'hidden', marginBottom: 20 }}>
                            <div style={{ padding: '14px 16px', borderBottom: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <h4 style={{ fontSize: 13, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                                Query Evidence & Extracted Citations ({aiLatestRun.evidence?.length || 0})
                              </h4>
                              <span style={{ fontSize: 11, color: '#64748b' }}>
                                Target Domain: {aiLatestRun.target_domain}
                              </span>
                            </div>

                            <div style={{ overflowX: 'auto' }}>
                              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
                                <thead>
                                  <tr style={{ background: '#070b13', borderBottom: '1px solid #1e293b', color: '#64748b', fontSize: 11, textTransform: 'uppercase' }}>
                                    <th style={{ padding: '10px 16px' }}>Query & Intent</th>
                                    <th style={{ padding: '10px 12px' }}>Brand Mentioned</th>
                                    <th style={{ padding: '10px 12px' }}>Domain Cited</th>
                                    <th style={{ padding: '10px 16px' }}>Citations & Sources</th>
                                    <th style={{ padding: '10px 16px', textAlign: 'right' }}>Answer Excerpt</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {aiLatestRun.evidence?.map((item, idx) => (
                                    <tr key={idx} style={{ borderBottom: '1px solid #162032' }}>
                                      <td style={{ padding: '12px 16px', maxWidth: 280 }}>
                                        <div style={{ fontWeight: 700, color: '#f1f5f9' }}>{item.query}</div>
                                        <span className="badge badge-grey" style={{ fontSize: 10, marginTop: 4 }}>
                                          {item.intent}
                                        </span>
                                      </td>
                                      <td style={{ padding: '12px 12px' }}>
                                        {item.brand_mentioned ? (
                                          <span className="badge badge-green" style={{ fontSize: 10, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                            <Check size={12} /> Mentioned
                                          </span>
                                        ) : (
                                          <span className="badge badge-grey" style={{ fontSize: 10 }}>Not in text</span>
                                        )}
                                      </td>
                                      <td style={{ padding: '12px 12px' }}>
                                        {item.domain_cited ? (
                                          <span className="badge badge-blue" style={{ fontSize: 10, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                            <Check size={12} /> Cited
                                          </span>
                                        ) : (
                                          <span className="badge badge-grey" style={{ fontSize: 10 }}>Not cited</span>
                                        )}
                                      </td>
                                      <td style={{ padding: '12px 16px', maxWidth: 300 }}>
                                        {item.citations?.length ? (
                                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                            {item.citations.slice(0, 3).map((cit, cidx) => (
                                              <a
                                                key={cidx}
                                                href={cit.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                style={{ color: '#38bdf8', textDecoration: 'none', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                              >
                                                <ExternalLink size={11} /> {cit.title || cit.domain}
                                              </a>
                                            ))}
                                            {item.citations.length > 3 && (
                                              <span style={{ fontSize: 10, color: '#64748b' }}>
                                                +{item.citations.length - 3} more sources
                                              </span>
                                            )}
                                          </div>
                                        ) : (
                                          <span style={{ color: '#64748b', fontSize: 11 }}>No sources returned</span>
                                        )}
                                      </td>
                                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                                        <button
                                          onClick={() => setExpandedQueryIdx(expandedQueryIdx === idx ? null : idx)}
                                          className="btn btn-secondary"
                                          style={{ padding: '4px 8px', fontSize: 11 }}
                                        >
                                          {expandedQueryIdx === idx ? 'Hide Excerpt' : 'View Excerpt'}
                                        </button>
                                        {expandedQueryIdx === idx && (
                                          <div style={{
                                            marginTop: 8, padding: 10, background: '#070b13', border: '1px solid #1e293b',
                                            borderRadius: 6, textAlign: 'left', color: '#cbd5e1', fontSize: 11, lineHeight: 1.5,
                                            maxHeight: 180, overflowY: 'auto',
                                          }}>
                                            {item.answer_excerpt || 'No answer text recorded.'}
                                          </div>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>

                          {/* Volatility Disclaimer Alert */}
                          <div style={{
                            background: '#090e18', border: '1px solid #1e293b', borderRadius: 8,
                            padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: 10,
                          }}>
                            <AlertCircle size={16} style={{ color: '#facc15', flexShrink: 0, marginTop: 2 }} />
                            <span style={{ color: '#94a3b8', fontSize: 12, lineHeight: 1.5 }}>
                              {aiLatestRun.uncertainty_note || 'Observations recorded via Perplexity Agent API. Generative AI answers vary dynamically across users, time, and regions; citations represent point-in-time test samples.'}
                            </span>
                          </div>
                        </div>
                      )}

                      {/* 4. Empty State when No Run Has Occurred */}
                      {!aiLatestRun && !runningAiCheck && (
                        <div style={{
                          background: '#0a101d', border: '1px solid #1e293b', borderRadius: 10,
                          padding: '30px', textAlign: 'center',
                        }}>
                          <Bot size={36} style={{ color: '#64748b', margin: '0 auto 12px auto' }} />
                          <h4 style={{ fontSize: 14, fontWeight: 700, color: '#f8fafc', margin: '0 0 6px 0' }}>
                            {aiStatus?.monitoring_enabled ? 'No Visibility Checks Run Yet' : 'AI-Search Visibility Unconfigured'}
                          </h4>
                          <p style={{ color: '#94a3b8', fontSize: 12, maxWidth: 500, margin: '0 auto 16px auto', lineHeight: 1.6 }}>
                            {aiStatus?.monitoring_enabled
                              ? `Click "Run Visibility Check" above to query the Perplexity Agent API across 10 business queries and observe actual brand citations for ${lead.business_name}.`
                              : 'To track whether AI search engines cite this business, configure AI_SEARCH_PROVIDER_KEY in your environment with a valid Perplexity API key.'}
                          </p>
                          {aiStatus?.monitoring_enabled && (
                            <button
                              onClick={handleRunAiVisibilityCheck}
                              className="btn btn-primary"
                              style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 16px', fontSize: 13 }}
                            >
                              <Play size={14} /> Run Visibility Check Now
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab 6: Service Proposal & Outreach Offer */}
                  {activeTab === 'proposal' && (
                    <div className="card-elevated p-6">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <Send size={20} style={{ color: '#3b82f6' }} />
                          <div>
                            <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                              Service Proposal & Client Offer
                            </h3>
                            <span style={{ fontSize: 12, color: '#64748b' }}>
                              Derived strictly from verified audit findings for {lead.business_name}
                            </span>
                          </div>
                        </div>

                        <div>
                          {proposal?.approved ? (
                            <span className="badge badge-green" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px' }}>
                              <CheckCircle2 size={14} /> Approved by {proposal.approved_by}
                            </span>
                          ) : (
                            <span className="badge badge-yellow" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px' }}>
                              <AlertTriangle size={14} /> Requires Human Approval
                            </span>
                          )}
                        </div>
                      </div>

                      {loadingProposal ? (
                        <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                          <RefreshCw size={24} className="spin" style={{ margin: '0 auto 12px auto' }} />
                          <p>Synthesizing evidence-based proposal...</p>
                        </div>
                      ) : !proposal ? (
                        <div style={{ padding: 30, textAlign: 'center', background: '#0a101d', borderRadius: 8, border: '1px solid #1e293b' }}>
                          <p style={{ color: '#94a3b8', marginBottom: 16 }}>No proposal draft currently active for this audit.</p>
                          <button onClick={loadProposal} className="btn btn-primary">
                            Generate Evidence-Based Proposal
                          </button>
                        </div>
                      ) : (
                        <div>
                          {/* Selected Observations Section */}
                          <div style={{ marginBottom: 24 }}>
                            <h4 style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>
                              Curated Service Opportunities ({proposal.selected_opportunities_count} Salient Findings)
                            </h4>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
                              {proposal.observations?.map((obs, idx) => (
                                <div key={idx} style={{ background: '#090e18', border: '1px solid #1e293b', borderRadius: 8, padding: 14 }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: '#f8fafc' }}>{obs.service_name}</span>
                                    <span className="badge badge-grey" style={{ fontSize: 10, textTransform: 'uppercase' }}>{obs.scope}</span>
                                  </div>
                                  <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 8px 0' }}>
                                    <strong>Evidence:</strong> {obs.evidence}
                                  </p>
                                  <p style={{ fontSize: 11, color: '#60a5fa', margin: 0 }}>
                                    → Action: {obs.next_step}
                                  </p>
                                </div>
                              ))}
                            </div>
                            <div style={{ marginTop: 8, fontSize: 11, color: '#64748b' }}>
                              Contributing Factor IDs: {proposal.contributing_factor_ids?.map((fid) => (
                                <code key={fid} style={{ background: '#1e293b', padding: '2px 6px', borderRadius: 4, marginRight: 6, color: '#93c5fd' }}>{fid}</code>
                              ))}
                            </div>
                          </div>

                          {/* Email Draft Preview */}
                          <div style={{ background: '#060a12', border: '1px solid #1e293b', borderRadius: 8, padding: 16, marginBottom: 20 }}>
                            <div style={{ borderBottom: '1px solid #1e293b', paddingBottom: 10, marginBottom: 12 }}>
                              <span style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>Subject: </span>
                              <span style={{ fontSize: 13, color: '#f8fafc', fontWeight: 700 }}>{proposal.subject}</span>
                            </div>
                            <div style={{ whiteSpace: 'pre-wrap', color: '#cbd5e1', fontSize: 13, lineHeight: 1.6, maxHeight: 220, overflowY: 'auto' }}>
                              {proposal.body_text}
                            </div>
                          </div>

                          {/* Human Approval Action Gate Bar */}
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, borderTop: '1px solid #1e293b', paddingTop: 16 }}>
                            <div style={{ fontSize: 12, color: '#94a3b8' }}>
                              {proposal.approved ? (
                                <span style={{ color: '#22c55e' }}>✓ Authorized by human review. Proposal is eligible for delivery simulation.</span>
                              ) : (
                                <span style={{ color: '#f59e0b' }}>⚠️ Sending is strictly blocked until an operator reviews and authorizes the draft.</span>
                              )}
                            </div>

                            <div style={{ display: 'flex', gap: 10 }}>
                              {!proposal.approved && (
                                <button
                                  onClick={handleApproveProposal}
                                  disabled={approving}
                                  className="btn btn-primary"
                                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                                >
                                  <CheckCheck size={16} /> {approving ? 'Authorizing...' : 'Approve Proposal (Human Review)'}
                                </button>
                              )}
                              <button
                                onClick={handleSendSimulation}
                                disabled={!proposal.approved || sendingSimulation}
                                className="btn btn-secondary"
                                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, opacity: proposal.approved ? 1 : 0.5 }}
                                title={!proposal.approved ? 'Approval required before delivery' : 'Simulate delivery safely (dry run)'}
                              >
                                <Send size={16} /> {sendingSimulation ? 'Testing...' : 'Test Send Simulation (Dry Run)'}
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
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
