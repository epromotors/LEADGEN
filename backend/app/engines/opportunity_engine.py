"""
opportunity_engine.py — Evidence-Based Service Opportunity & Client Proposal Engine

Translates verified audit findings (from the 62 canonical factors) into credible,
traceable service proposals for TEB Solutions.

Enforces Master Plan requirements:
- Evidence-to-offer mapping (Technical SEO, Local SEO, AI-Search, Web Design, Performance).
- Clear segregation into Critical Issues and Warnings with practical recommended steps.
- Distinguishes small repairs from broader redesign opportunities.
- Selects at most 2–3 salient, high-confidence observations per proposal.
- Strict claim provenance: records contributing factor IDs for every generated claim.
- Disallows fabricated ranking, traffic, conversion, or revenue claims.
- Human review gate: drafts are preview-only and require explicit approval before sending.
"""

from typing import Any, Dict, List, Optional, Tuple
import html
import urllib.parse

from app.services.ai_search_provider import normalize_domain


# ── Canonical Factor Catalog (62 Canonical Audit Factors) ────────────────────
# Each factor maps to:
# - category: Category name
# - name: Friendly factor name
# - critical: { problem, impact, recommendation }
# - warning: { warning, potential_impact, recommendation }

CANONICAL_FACTORS: Dict[str, Dict[str, Any]] = {
    # ── 1. Technical SEO & Security (10 factors) ─────────────────────────────
    "technical.ssl": {
        "category": "Security & HTTPS",
        "name": "SSL / HTTPS Certificate",
        "critical": {
            "problem": "Website is not served securely over HTTPS or SSL certificate has expired.",
            "impact": "Browsers display security warnings ('Not Secure'), blocking prospective visitors and harming search trust.",
            "recommendation": "Install a valid TLS/SSL certificate, configure automated renewal, and enforce 301 HTTPS redirection.",
        },
        "warning": {
            "warning": "SSL certificate expires soon or certificate chain requires maintenance.",
            "potential_impact": "Risk of unexpected browser security warnings if renewal is not scheduled before expiration.",
            "recommendation": "Schedule certificate renewal or verify automated Let's Encrypt renewal.",
        },
    },
    "technical.sitemap": {
        "category": "Technical SEO & Crawlability",
        "name": "XML Sitemap",
        "critical": {
            "problem": "XML sitemap is missing, unreachable, or returning a server error.",
            "impact": "Search engine crawlers cannot systematically discover and crawl all published service pages.",
            "recommendation": "Generate an XML sitemap at /sitemap.xml, declare it in robots.txt, and verify it contains only indexable URLs.",
        },
        "warning": {
            "warning": "XML sitemap is not declared in robots.txt or contains non-canonical URLs.",
            "potential_impact": "Search engines may take longer to discover and index newly published or updated service pages.",
            "recommendation": "Reference the absolute sitemap URL directive in robots.txt and ensure all listed URLs return HTTP 200.",
        },
    },
    "technical.robots": {
        "category": "Technical SEO & Crawlability",
        "name": "robots.txt Directives",
        "critical": {
            "problem": "robots.txt is missing or incorrectly disallowing crawler access to core service pages.",
            "impact": "Search engine crawlers are blocked from crawling and indexing primary business offerings.",
            "recommendation": "Deploy a valid robots.txt file allowing crawler access to public content while disallowing private admin routes.",
        },
        "warning": {
            "warning": "robots.txt syntax contains warnings or lacks a declared sitemap directive.",
            "potential_impact": "Crawlers may operate with sub-optimal crawl efficiency without explicit crawler directives.",
            "recommendation": "Review robots.txt rules for syntax compliance and add the absolute Sitemap URL directive.",
        },
    },
    "technical.canonical": {
        "category": "Technical SEO & Crawlability",
        "name": "Canonical Link Tags",
        "critical": {
            "problem": "Canonical link tags are missing or invalid across audited pages.",
            "impact": "Search engines may index duplicate URL variations, splitting indexing authority across duplicate URLs.",
            "recommendation": "Implement self-referential <link rel='canonical'> tags on all indexable pages.",
        },
        "warning": {
            "warning": "Canonical tag protocol or host does not match the preferred HTTPS domain.",
            "potential_impact": "Search engines may ignore the canonical directive or consolidate ranking signals unpredictably.",
            "recommendation": "Align canonical URLs to strictly match the preferred secure HTTPS domain format.",
        },
    },
    "technical.favicon": {
        "category": "Branding & User Experience",
        "name": "Favicon Presence",
        "critical": {
            "problem": "Website favicon is missing or returning a 404 error.",
            "impact": "Browsers and search result snippets display a generic placeholder icon instead of your business brand.",
            "recommendation": "Upload a branded 32x32 favicon.ico and declare it in the HTML head.",
        },
        "warning": {
            "warning": "Favicon is missing modern high-resolution formats (apple-touch-icon, SVG).",
            "potential_impact": "Reduced visual brand recognition on mobile bookmark bars and mobile search result snippets.",
            "recommendation": "Add multi-resolution favicon formats including SVG and apple-touch-icon.",
        },
    },
    "technical.mobile": {
        "category": "Mobile Usability & Responsive Design",
        "name": "Mobile Viewport Meta Tag",
        "critical": {
            "problem": "Mobile viewport meta tag is missing, causing desktop layout rendering on mobile phones.",
            "impact": "Mobile users see miniature unreadable text and horizontal overflow, creating a frustrating experience.",
            "recommendation": "Add <meta name='viewport' content='width=device-width, initial-scale=1.0'> to the HTML head.",
        },
        "warning": {
            "warning": "Mobile viewport contains restrictive zoom directives (user-scalable=no).",
            "potential_impact": "May hinder accessibility for users attempting to zoom in on mobile devices.",
            "recommendation": "Allow user zooming by removing user-scalable=no from the viewport tag.",
        },
    },
    "technical.https_redirect": {
        "category": "Security & HTTPS",
        "name": "HTTP to HTTPS Redirection",
        "critical": {
            "problem": "HTTP requests do not automatically redirect to HTTPS.",
            "impact": "Visitors typing plain web addresses access an unencrypted connection without automatic security upgrade.",
            "recommendation": "Implement an automatic 301 permanent redirect from HTTP to HTTPS in server configuration.",
        },
        "warning": {
            "warning": "HTTP to HTTPS redirection involves multiple intermediate redirect hops.",
            "potential_impact": "Adds avoidable network latency before the page begins loading for visitors.",
            "recommendation": "Streamline server redirect rules to route directly to the final HTTPS URL in a single hop.",
        },
    },
    "technical.redirect_chain": {
        "category": "Technical SEO & Crawlability",
        "name": "Redirect Chain Health",
        "critical": {
            "problem": "Long redirect chain or circular redirect detected.",
            "impact": "Crawlers may abort requests and visitors experience noticeable page load delays.",
            "recommendation": "Eliminate intermediate redirect hops and point internal links directly to final destination URLs.",
        },
        "warning": {
            "warning": "Multiple redirect hops detected during page navigation.",
            "potential_impact": "Increases page load time and consumes crawler crawl budget unnecessarily.",
            "recommendation": "Consolidate redirect rules so incoming requests resolve in a single hop.",
        },
    },
    "technical.mixed_content": {
        "category": "Security & HTTPS",
        "name": "Mixed Content Security",
        "critical": {
            "problem": "Active mixed content detected (insecure scripts or styles loaded over HTTP).",
            "impact": "Modern web browsers block insecure scripts, breaking page layouts and interactive features.",
            "recommendation": "Update all asset URLs (scripts, stylesheets, fonts) to load over secure HTTPS.",
        },
        "warning": {
            "warning": "Passive mixed content detected (images loaded over plain HTTP).",
            "potential_impact": "Browsers display security warnings on the SSL padlock icon, reducing visitor trust.",
            "recommendation": "Update all image and media URLs to load over secure HTTPS connections.",
        },
    },
    "technical.www_canonicalization": {
        "category": "Technical SEO & Crawlability",
        "name": "WWW vs Non-WWW Canonicalization",
        "critical": {
            "problem": "Both www and non-www versions of the domain resolve without redirecting.",
            "impact": "Search engines index two duplicate versions of your website, diluting domain authority.",
            "recommendation": "Choose your preferred domain version and configure a permanent 301 redirect for the other.",
        },
        "warning": {
            "warning": "Inconsistent www and non-www internal links detected across pages.",
            "potential_impact": "Triggers avoidable internal redirects and diffuses internal link equity.",
            "recommendation": "Standardize all internal navigation links to use the canonical domain format.",
        },
    },

    # ── 2. On-Page SEO & Metadata (10 factors) ──────────────────────────────
    "onpage.page_title": {
        "category": "On-Page SEO & Metadata",
        "name": "Page Title Tag",
        "critical": {
            "problem": "Page title tag is missing or completely empty.",
            "impact": "Search engines cannot determine the page topic and may display an auto-generated or generic snippet in search results.",
            "recommendation": "Add a unique, descriptive <title> tag including your primary service and location.",
        },
        "warning": {
            "warning": "Page title length is outside the optimal 40-65 character range.",
            "potential_impact": "Title text may be truncated in search results or lack sufficient detail for prospective clients.",
            "recommendation": "Refine page title length to 50-60 characters incorporating primary service and location keywords.",
        },
    },
    "onpage.meta_desc": {
        "category": "On-Page SEO & Metadata",
        "name": "Meta Description Tag",
        "critical": {
            "problem": "Meta description tag is missing from the page.",
            "impact": "Search engines display arbitrary page text snippets in search results, reducing click-through rates.",
            "recommendation": "Add a compelling <meta name='description'> outlining services and a clear call to action.",
        },
        "warning": {
            "warning": "Meta description length is outside recommended 120-160 character guidelines.",
            "potential_impact": "Search snippet may truncate in search results or fail to convey key service benefits.",
            "recommendation": "Adjust meta description to 130-155 characters highlighting core value propositions and contact action.",
        },
    },
    "onpage.h1": {
        "category": "On-Page SEO & Content Structure",
        "name": "Primary H1 Heading",
        "critical": {
            "problem": "Primary H1 heading is missing from the page.",
            "impact": "Visitors and search engines lack a clear hierarchical indication of the page's core subject.",
            "recommendation": "Add a clear, descriptive <h1> heading at the top of the main content area.",
        },
        "warning": {
            "warning": "Multiple H1 headings detected or H1 does not align with the page's primary topic.",
            "potential_impact": "Diffuses topical relevance and confuses assistive heading navigation.",
            "recommendation": "Maintain a single, primary <h1> heading supported by hierarchical <h2> subheadings.",
        },
    },
    "onpage.og_tags": {
        "category": "Social Media & Rich Previews",
        "name": "Open Graph Social Metadata",
        "critical": {
            "problem": "Open Graph metadata tags are completely missing.",
            "impact": "Shared links in WhatsApp, social media, and messaging display unformatted without preview images.",
            "recommendation": "Implement standard Open Graph tags (og:title, og:description, og:image) for rich link previews.",
        },
        "warning": {
            "warning": "Open Graph tags are partially configured (missing og:image or og:description).",
            "potential_impact": "Link previews in messaging apps appear incomplete without high-resolution preview graphics.",
            "recommendation": "Add a dedicated 1200x630 og:image and complete og:description tags.",
        },
    },
    "onpage.schema": {
        "category": "Structured Data & Schema",
        "name": "Schema.org Structured Data",
        "critical": {
            "problem": "Structured data (Schema.org JSON-LD) is entirely absent from the website.",
            "impact": "Search engines cannot extract rich entity context, missing eligibility for rich snippets.",
            "recommendation": "Implement valid Schema.org JSON-LD representing your organization and primary services.",
        },
        "warning": {
            "warning": "Schema markup contains incomplete recommended fields or minor syntax warnings.",
            "potential_impact": "May limit qualification for rich search features in search engines.",
            "recommendation": "Enrich structured data with all recommended Schema.org properties and validate syntax.",
        },
    },
    "onpage.noindex": {
        "category": "Technical SEO & Indexability",
        "name": "Noindex Directive Guard",
        "critical": {
            "problem": "A 'noindex' directive was detected on your primary public landing page.",
            "impact": "Search engines are explicitly instructed to remove the page from search results, eliminating visibility.",
            "recommendation": "Remove the 'noindex' meta tag or HTTP header from all public service pages.",
        },
        "warning": {
            "warning": "Noindex directive found on an internal page that may require review.",
            "potential_impact": "May inadvertently block valuable content pages from search indexing.",
            "recommendation": "Verify whether noindexed pages are intentionally excluded from search engines.",
        },
    },
    "onpage.heading_hierarchy": {
        "category": "On-Page SEO & Content Structure",
        "name": "Heading Hierarchy Order",
        "critical": {
            "problem": "Heading hierarchy is disordered with missing primary headings.",
            "impact": "Search crawlers and screen readers cannot parse the logical outline of the document.",
            "recommendation": "Structure headings sequentially from H1 to H2 to H3 to establish a clear outline.",
        },
        "warning": {
            "warning": "Heading hierarchy skips levels (e.g. jumping from H1 directly to H3 or H4).",
            "potential_impact": "Degrades document structure readability for screen readers and semantic indexing.",
            "recommendation": "Organize headings sequentially from H1 to H2 to H3 to maintain proper semantic order.",
        },
    },
    "onpage.internal_links": {
        "category": "Crawlability & Internal Architecture",
        "name": "Internal Link Distribution",
        "critical": {
            "problem": "Page contains zero internal links to other service pages or contact points.",
            "impact": "Creates a dead-end experience for visitors and isolates the page from site architecture.",
            "recommendation": "Add contextual internal links connecting related service descriptions and contact pages.",
        },
        "warning": {
            "warning": "Limited internal links found between related service pages.",
            "potential_impact": "Visitors and crawlers find it harder to navigate between complementary services.",
            "recommendation": "Add descriptive internal links connecting related service offerings and enquiry pages.",
        },
    },
    "onpage.anchor_text_quality": {
        "category": "On-Page SEO & Accessibility",
        "name": "Anchor Text Quality",
        "critical": {
            "problem": "Links use uninformative or empty anchor text.",
            "impact": "Assistive devices and crawlers cannot understand where links lead.",
            "recommendation": "Replace generic or empty links with descriptive anchor text explaining the destination.",
        },
        "warning": {
            "warning": "Generic anchor text ('click here', 'read more') used on links.",
            "potential_impact": "Provides zero contextual information to search crawlers and screen readers about the destination.",
            "recommendation": "Replace generic anchor phrases with descriptive text stating the linked service.",
        },
    },
    "onpage.image_filenames": {
        "category": "On-Page SEO & Media",
        "name": "Image Filename Optimization",
        "critical": {
            "problem": "Image filenames contain broken characters or corrupt file paths.",
            "impact": "Risk of broken image assets and failed media downloads.",
            "recommendation": "Use clean, hyphenated filenames with standard extensions (.webp, .jpg, .png).",
        },
        "warning": {
            "warning": "Generic image filenames detected (e.g., IMG_001.jpg, screenshot.png).",
            "potential_impact": "Misses an opportunity for image search visibility and descriptive accessibility.",
            "recommendation": "Rename image files to descriptive, hyphenated keywords before publishing.",
        },
    },

    # ── 3. Images & Media (3 factors) ───────────────────────────────────────
    "images.alt_text": {
        "category": "Accessibility & Media",
        "name": "Image Alt Text Coverage",
        "critical": {
            "problem": "Primary images lack alt text attributes entirely.",
            "impact": "Screen readers cannot describe images to visually impaired users and image search crawlers cannot index them.",
            "recommendation": "Add descriptive alt attributes explaining the subject of each meaningful image.",
        },
        "warning": {
            "warning": "Several secondary images are missing alt text attributes.",
            "potential_impact": "Incomplete accessibility compliance and missed image search signals.",
            "recommendation": "Audit image tags and add concise alt descriptions or mark purely decorative icons as alt=''.",
        },
    },
    "images.webp": {
        "category": "Performance & Media",
        "name": "Modern Image Formats (WebP/AVIF)",
        "critical": {
            "problem": "Heavy legacy image formats (uncompressed PNG/JPEG) used extensively without modern formats.",
            "impact": "Bloated asset sizes cause slow rendering, high data usage, and increased bounce rates.",
            "recommendation": "Convert image assets to modern WebP or AVIF formats and compress them appropriately.",
        },
        "warning": {
            "warning": "Several images could benefit from conversion to modern WebP format.",
            "potential_impact": "Page payload could be reduced by 25-35% with modern image compression.",
            "recommendation": "Serve images in modern WebP format with responsive srcset attributes.",
        },
    },
    "images.lazy_load": {
        "category": "Performance & Media",
        "name": "Image Lazy Loading",
        "critical": {
            "problem": "All images are loaded synchronously without deferred or lazy loading.",
            "impact": "Browsers download all off-screen media during initial load, choking initial page display.",
            "recommendation": "Add native loading='lazy' attribute to off-screen images to prioritize initial viewport render.",
        },
        "warning": {
            "warning": "Below-the-fold images lack native lazy-loading attributes.",
            "potential_impact": "Wastes mobile bandwidth by downloading off-screen images before the user scrolls.",
            "recommendation": "Add loading='lazy' attribute to all images situated below the initial viewport.",
        },
    },

    # ── 4. Links & Crawlability (1 factor) ──────────────────────────────────
    "links.broken_links": {
        "category": "Broken Links & Crawlability",
        "name": "Hyperlink Health",
        "critical": {
            "problem": "Broken hyperlinks (HTTP 404/500 errors) detected on the website.",
            "impact": "Frustrates visitors, causes lost enquiries, and signals poor website maintenance to crawlers.",
            "recommendation": "Fix or remove broken link destinations and implement 301 redirects for moved content.",
        },
        "warning": {
            "warning": "Minor external broken links or unverified link destinations detected.",
            "potential_impact": "Visitors encountering broken external links experience reduced trust.",
            "recommendation": "Audit and update external link references to active, valid web destinations.",
        },
    },

    # ── 5. Conversion & Contact Channels (4 factors) ────────────────────────
    "conversion.social": {
        "category": "Conversion & Trust Signals",
        "name": "Social Profile Integration",
        "critical": {
            "problem": "No social proof or business verification channels linked from the website.",
            "impact": "Prospective clients seeking social validation cannot verify business activity.",
            "recommendation": "Add verified links to your business social profiles (LinkedIn, Facebook, Instagram) in the footer.",
        },
        "warning": {
            "warning": "Links to active business social media profiles are missing.",
            "potential_impact": "Reduces social credibility and secondary verification channels for prospective clients.",
            "recommendation": "Add verified links to your active social profiles in the website footer.",
        },
    },
    "conversion.contact": {
        "category": "Conversion & Contact Channels",
        "name": "Direct Contact Link Accessibility",
        "critical": {
            "problem": "No clickable contact links (tel: or mailto:) were found on the website.",
            "impact": "Mobile visitors cannot tap to call or email your business directly, creating high friction.",
            "recommendation": "Add clickable phone (tel:) and email (mailto:) links in the header and footer.",
        },
        "warning": {
            "warning": "Contact information is displayed as plain text without clickable hyperlinks.",
            "potential_impact": "Users must manually copy and dial numbers, reducing direct enquiry conversions.",
            "recommendation": "Wrap phone numbers in tel: links and emails in mailto: links.",
        },
    },
    "conversion.whatsapp": {
        "category": "Conversion & Contact Channels",
        "name": "WhatsApp Messaging Integration",
        "critical": {
            "problem": "No direct messaging or immediate chat channel available for mobile visitors.",
            "impact": "Mobile visitors who prefer instant messaging cannot reach your team immediately.",
            "recommendation": "Integrate a WhatsApp click-to-chat button for fast customer enquiries.",
        },
        "warning": {
            "warning": "WhatsApp direct chat integration is missing.",
            "potential_impact": "Misses an immediate, high-converting messaging channel preferred by many mobile customers.",
            "recommendation": "Add a floating or header WhatsApp click-to-chat button for fast customer enquiries.",
        },
    },
    "conversion.trust": {
        "category": "Conversion & Trust Signals",
        "name": "Trust & Compliance Pages",
        "critical": {
            "problem": "Essential legal and trust pages (Privacy Policy, Terms of Service) are missing.",
            "impact": "Weaker trust signals for search algorithms, advertising platforms, and compliance regulators.",
            "recommendation": "Publish dedicated Privacy Policy and Terms of Service pages linked in the footer.",
        },
        "warning": {
            "warning": "Trust pages (Privacy Policy, Terms of Service) are missing or incomplete.",
            "potential_impact": "Weaker trust signal for search engines, ad platforms, and security-conscious visitors.",
            "recommendation": "Publish standard Privacy Policy and Terms of Service pages linked in the footer.",
        },
    },

    # ── 6. User Experience & Usability (10 factors) ─────────────────────────
    "ux.cta": {
        "category": "Web Design & Conversion UX",
        "name": "Primary Call-to-Action (CTA)",
        "critical": {
            "problem": "No clear primary call-to-action (CTA) button was found on the page.",
            "impact": "Visitors who want to reach out lack a clear, obvious action to take, depressing lead conversion.",
            "recommendation": "Implement a prominent, contrasting CTA button (e.g., 'Request a Quote' or 'Book a Consultation').",
        },
        "warning": {
            "warning": "Call-to-action button lacks visual contrast or prominent styling.",
            "potential_impact": "Visitors may overlook the enquiry button among surrounding content.",
            "recommendation": "Increase button size, contrast, and visual prominence to guide visitor focus.",
        },
    },
    "ux.cta_above_fold": {
        "category": "Web Design & Conversion UX",
        "name": "Above-the-Fold CTA Placement",
        "critical": {
            "problem": "Enquiry options are buried at the bottom of the page requiring extensive scrolling.",
            "impact": "Visitors who bounce in the first 5 seconds never see an enquiry button.",
            "recommendation": "Position a clear contact button in the initial viewport above the fold.",
        },
        "warning": {
            "warning": "Primary call-to-action requires scrolling and is not visible above the fold.",
            "potential_impact": "Visitors who do not scroll past the hero section leave without seeing how to get in touch.",
            "recommendation": "Position a primary contact button or enquiry form in the initial viewport above the fold.",
        },
    },
    "ux.hero_headline": {
        "category": "Web Design & Conversion UX",
        "name": "Hero Section Value Proposition",
        "critical": {
            "problem": "Hero section lacks any headline or value statement.",
            "impact": "Visitors cannot tell what business service is offered upon landing.",
            "recommendation": "Add a prominent hero headline stating your primary service and service territory.",
        },
        "warning": {
            "warning": "Hero section lacks a concise, benefit-driven headline.",
            "potential_impact": "First-time visitors cannot immediately understand what services your business offers.",
            "recommendation": "Craft a clear headline stating your primary service, target audience, and key differentiator.",
        },
    },
    "ux.font_size": {
        "category": "Mobile Usability & Responsive Design",
        "name": "Typography Legibility",
        "critical": {
            "problem": "Body text font size is below 12px, making content unreadable on mobile screens.",
            "impact": "High mobile bounce rate as visitors struggle to read text without manual pinching and zooming.",
            "recommendation": "Increase baseline body text font size to at least 16px with comfortable line spacing.",
        },
        "warning": {
            "warning": "Secondary text elements are smaller than the recommended 14px threshold.",
            "potential_impact": "Reduces readability for captions, sub-text, and disclaimers on smaller devices.",
            "recommendation": "Ensure all readable text elements maintain at least 13-14px font sizing.",
        },
    },
    "ux.contrast": {
        "category": "Accessibility & Visual Design",
        "name": "Text Color Contrast",
        "critical": {
            "problem": "Color contrast ratio fails basic accessibility standards severely (below 3:1).",
            "impact": "Text is difficult or impossible to read against the background, particularly in mobile daylight.",
            "recommendation": "Adjust text or background colors to achieve at least 4.5:1 contrast for normal text.",
        },
        "warning": {
            "warning": "Subtle contrast deficiencies detected on secondary text or borders.",
            "potential_impact": "Reduces legibility for visually impaired visitors and in high-glare environments.",
            "recommendation": "Darken text or lighten backgrounds to comfortably exceed accessibility contrast standards.",
        },
    },
    "ux.nav_links": {
        "category": "Navigation & User Experience",
        "name": "Header Navigation Structure",
        "critical": {
            "problem": "Website lacks a functional header navigation menu.",
            "impact": "Visitors cannot discover secondary service offerings, about information, or contact details.",
            "recommendation": "Add an intuitive header navigation menu linking to core services, about, and contact pages.",
        },
        "warning": {
            "warning": "Header navigation contains few or non-standard navigation links.",
            "potential_impact": "Visitors cannot easily explore service categories, past work, or business credentials.",
            "recommendation": "Add an intuitive header navigation menu linking to core services, about, and contact pages.",
        },
    },
    "ux.cookie_notice": {
        "category": "Compliance & User Experience",
        "name": "Cookie Consent Notice",
        "critical": {
            "problem": "Cookie consent notification is missing on a site setting tracking cookies.",
            "impact": "Potential compliance risk under data privacy regulations.",
            "recommendation": "Implement a privacy-compliant cookie consent banner with clear opt-in controls.",
        },
        "warning": {
            "warning": "Cookie consent notice or privacy notification is absent.",
            "potential_impact": "Potential compliance gap under regional privacy standards and data protection guidelines.",
            "recommendation": "Review applicable privacy regulations and implement a lightweight consent notification.",
        },
    },
    "ux.live_chat": {
        "category": "Conversion & Contact Channels",
        "name": "Live Chat / Messaging Availability",
        "critical": {
            "problem": "No interactive messaging mechanism available for inbound leads.",
            "impact": "Higher drop-off among visitors seeking immediate service confirmation.",
            "recommendation": "Implement a live chat or WhatsApp enquiry widget.",
        },
        "warning": {
            "warning": "No instant messaging or live chat option is available on the website.",
            "potential_impact": "Visitors with quick questions may leave rather than waiting for email responses.",
            "recommendation": "Consider integrating a lightweight chat or messaging widget for rapid customer enquiries.",
        },
    },
    "ux.phone_number": {
        "category": "Conversion & Contact Channels",
        "name": "Phone Number Prominence",
        "critical": {
            "problem": "No telephone number was identified on the homepage or header.",
            "impact": "Customers needing urgent service cannot locate your phone number to call immediately.",
            "recommendation": "Add a clearly visible phone number in the website header and footer.",
        },
        "warning": {
            "warning": "Phone number is presented without an interactive tap-to-call link.",
            "potential_impact": "Mobile visitors cannot tap the number to initiate a phone call directly.",
            "recommendation": "Format phone numbers as clickable <a href='tel:...'> links.",
        },
    },
    "ux.address_presence": {
        "category": "Local SEO & Entity Presence",
        "name": "Physical Address / Service Area",
        "critical": {
            "problem": "Website provides no physical business address or operating territory.",
            "impact": "Prospective clients and search engines cannot verify geographic operating legitimacy.",
            "recommendation": "Publish verified business address, operating hours, and service territories.",
        },
        "warning": {
            "warning": "Physical business address or defined service region is not displayed on the homepage.",
            "potential_impact": "Prospective local customers cannot verify where your business is physically located.",
            "recommendation": "Display your full business address and service coverage areas prominently.",
        },
    },

    # ── 7. Indexability & Crawl Architecture (4 factors) ────────────────────
    "indexability.noindex": {
        "category": "Technical SEO & Indexability",
        "name": "Noindex Directive Audit",
        "critical": {
            "problem": "A 'noindex' directive was detected on your primary public page.",
            "impact": "Search engines are explicitly instructed to remove the page from search results, eliminating visibility.",
            "recommendation": "Remove the 'noindex' meta tag or HTTP header from all public service pages.",
        },
        "warning": {
            "warning": "Noindex directive found on an internal page that may require review.",
            "potential_impact": "May inadvertently block valuable content pages from search indexing.",
            "recommendation": "Verify whether noindexed pages are intentionally excluded from search engines.",
        },
    },
    "indexability.url_structure": {
        "category": "Technical SEO & Indexability",
        "name": "URL Structure Cleanliness",
        "critical": {
            "problem": "URLs contain malformed query strings or encoding errors.",
            "impact": "Search crawlers fail to parse destination URLs cleanly.",
            "recommendation": "Clean up URL routing to use standard semantic path segments.",
        },
        "warning": {
            "warning": "URL structure contains uppercase letters, underscores, or unnecessary query strings.",
            "potential_impact": "Sub-optimal URL readability for users and risk of duplicate URL indexing.",
            "recommendation": "Standardize on clean, lowercase, hyphenated URL slugs reflecting the page topic.",
        },
    },
    "indexability.www_vs_nonwww": {
        "category": "Technical SEO & Indexability",
        "name": "WWW vs Non-WWW Consistency",
        "critical": {
            "problem": "Domain resolves inconsistently across protocol or www variations.",
            "impact": "Splits domain authority and risks duplicate index entries in search.",
            "recommendation": "Enforce a unified 301 redirection rule to your preferred canonical domain.",
        },
        "warning": {
            "warning": "Inconsistent protocol or hostname redirects between www and non-www variants.",
            "potential_impact": "Search engines may take longer to consolidate page authority to the canonical version.",
            "recommendation": "Ensure all hostname variations redirect cleanly to a single canonical version.",
        },
    },
    "indexability.soft_404": {
        "category": "Broken Links & Crawlability",
        "name": "Soft 404 Detection",
        "critical": {
            "problem": "Non-existent URLs return a 200 OK status instead of a proper 404 error.",
            "impact": "Search engines index empty error pages as valid content, corrupting search crawl efficiency.",
            "recommendation": "Configure web server to return HTTP 404 or 410 status codes for missing URLs.",
        },
        "warning": {
            "warning": "Thin page content triggers soft-404 heuristic warnings.",
            "potential_impact": "Search crawlers may classify thin pages as unhelpful and remove them from search results.",
            "recommendation": "Expand content depth on thin pages or redirect them to relevant service hubs.",
        },
    },

    # ── 8. Content Depth & Quality (4 factors) ──────────────────────────────
    "content.word_count": {
        "category": "On-Page SEO & Content Quality",
        "name": "Content Word Count & Depth",
        "critical": {
            "problem": "Page content is extremely thin (under 100 words of descriptive text).",
            "impact": "Search engines view the page as low-value, preventing it from ranking for target services.",
            "recommendation": "Add thorough descriptions of your services, benefits, and process (aim for 300+ words).",
        },
        "warning": {
            "warning": "Content depth is below industry benchmarks for competitive service pages.",
            "potential_impact": "Competitor pages with richer service descriptions may rank higher in search results.",
            "recommendation": "Expand service descriptions with helpful details, FAQs, and client testimonials.",
        },
    },
    "content.duplicate_meta": {
        "category": "On-Page SEO & Metadata",
        "name": "Duplicate Metadata Audit",
        "critical": {
            "problem": "Identical page titles and descriptions used across multiple distinct service pages.",
            "impact": "Causes severe keyword cannibalization where pages compete against each other in search.",
            "recommendation": "Write distinct, customized titles and meta descriptions for each service page.",
        },
        "warning": {
            "warning": "Duplicate meta descriptions or title tags detected across pages.",
            "potential_impact": "Pages compete against each other in search results, diluting search visibility.",
            "recommendation": "Ensure each published page has a unique, topic-specific title and meta description.",
        },
    },
    "content.keyword_in_title": {
        "category": "On-Page SEO & Content Quality",
        "name": "Keyword in Title Tag",
        "critical": {
            "problem": "Page title lacks any mention of core business service or offerings.",
            "impact": "Search algorithms cannot establish relevance for customer search queries.",
            "recommendation": "Include your primary service name naturally in the page title.",
        },
        "warning": {
            "warning": "Primary service keywords are missing from the page title.",
            "potential_impact": "Reduces search relevance when prospective customers search for your specific services.",
            "recommendation": "Include your core service and city/area naturally in the title tag.",
        },
    },
    "content.reading_level": {
        "category": "On-Page SEO & Content Quality",
        "name": "Content Readability",
        "critical": {
            "problem": "Content is disorganized or excessively difficult to read.",
            "impact": "High bounce rates as visitors abandon difficult-to-parse paragraphs.",
            "recommendation": "Format copy into clear subheadings, short paragraphs, and bulleted lists.",
        },
        "warning": {
            "warning": "Content reading level is overly complex or uses dense jargon.",
            "potential_impact": "Visitors may find content difficult to scan, reducing time on page and engagement.",
            "recommendation": "Simplify complex phrasing using clear, accessible language and bullet points.",
        },
    },

    # ── 9. Local SEO & Entity Alignment (5 factors) ─────────────────────────
    "local_seo.nap_consistency": {
        "category": "Local SEO & Entity Presence",
        "name": "NAP Consistency (Name, Address, Phone)",
        "critical": {
            "problem": "Business Name, Address, or Phone (NAP) details are missing or contradictory.",
            "impact": "Search engines cannot verify local legitimacy, severely harming Google Maps presence.",
            "recommendation": "Standardize your exact business name, address, and phone number across all pages.",
        },
        "warning": {
            "warning": "NAP details have minor formatting discrepancies with external listings.",
            "potential_impact": "Weaker entity confidence in local search algorithms and map pack rankings.",
            "recommendation": "Align website NAP details exactly with your Google Business Profile listing.",
        },
    },
    "local_seo.local_business_schema": {
        "category": "Structured Data & Local SEO",
        "name": "LocalBusiness Schema Markup",
        "critical": {
            "problem": "LocalBusiness structured data markup is missing for a local service business.",
            "impact": "Search engines lack structured entity confirmation of your location and service area.",
            "recommendation": "Implement LocalBusiness JSON-LD markup with name, address, phone, and hours.",
        },
        "warning": {
            "warning": "LocalBusiness schema is missing recommended properties (geo coordinates, hours).",
            "potential_impact": "Incomplete structured data limits visibility in local map pack results.",
            "recommendation": "Add precise geo-coordinates, opening hours, and service categories to schema.",
        },
    },
    "local_seo.google_maps_embed": {
        "category": "Local SEO & Entity Presence",
        "name": "Google Maps Embed",
        "critical": {
            "problem": "No map or location direction mechanism available for local visitors.",
            "impact": "Local clients visiting on mobile devices cannot easily locate your premises.",
            "recommendation": "Embed an interactive Google Map with your verified business place ID.",
        },
        "warning": {
            "warning": "No interactive Google Map is embedded on the contact or location page.",
            "potential_impact": "Customers cannot quickly view directions or explore your physical location.",
            "recommendation": "Embed an interactive Google Map linked to your verified Google Business Profile.",
        },
    },
    "local_seo.city_in_title": {
        "category": "Local SEO & Entity Presence",
        "name": "City in Title Tag",
        "critical": {
            "problem": "Local business homepage title contains no geographic or service territory indicator.",
            "impact": "Fails to signal geographic service relevance to local search algorithms.",
            "recommendation": "Add your primary city or service territory to the homepage title tag.",
        },
        "warning": {
            "warning": "Target city or geographic location is missing from the homepage title.",
            "potential_impact": "Reduces relevance for local customer searches containing city or region names.",
            "recommendation": "Add your primary city or service territory to the page title tag.",
        },
    },
    "local_seo.business_hours": {
        "category": "Local SEO & Entity Presence",
        "name": "Business Operating Hours",
        "critical": {
            "problem": "Operating hours are completely absent from the website.",
            "impact": "Prospective clients cannot determine whether your business is open, driving calls to competitors.",
            "recommendation": "Publish operating hours clearly on your contact page and in footer.",
        },
        "warning": {
            "warning": "Business operating hours are not clearly stated on the website.",
            "potential_impact": "Prospective customers cannot verify when your team is available to assist them.",
            "recommendation": "Publish clear weekly operating hours on your contact page and in footer.",
        },
    },

    # ── 10. Performance & Core Web Vitals (6 factors) ────────────────────────
    "performance.response_time": {
        "category": "Performance & Core Web Vitals",
        "name": "Server Response Time (TTFB)",
        "critical": {
            "problem": "Server response time (TTFB) is slow (>1500ms).",
            "impact": "Causes significant delay before any page content renders, prompting visitors to bounce.",
            "recommendation": "Enable server-side page caching and investigate web host or database latency.",
        },
        "warning": {
            "warning": "Server response time is higher than recommended (>600ms).",
            "potential_impact": "Slows initial page delivery, especially on mobile cellular networks.",
            "recommendation": "Implement caching and consider a CDN to reduce time-to-first-byte.",
        },
    },
    "performance.page_size": {
        "category": "Performance & Core Web Vitals",
        "name": "Page Download Weight",
        "critical": {
            "problem": "Total page download size exceeds 4MB.",
            "impact": "Slow page loading speeds and high data usage for mobile visitors.",
            "recommendation": "Compress media assets, remove unneeded scripts, and optimize page resources.",
        },
        "warning": {
            "warning": "Total page size is elevated (>2MB).",
            "potential_impact": "May cause noticeable load delays on slower mobile data connections.",
            "recommendation": "Optimize assets to reduce overall page weight below 1.5MB.",
        },
    },
    "performance.render_blocking": {
        "category": "Performance & Core Web Vitals",
        "name": "Render-Blocking Resources",
        "critical": {
            "problem": "Multiple synchronous render-blocking scripts delay page paint.",
            "impact": "Visitors see a blank screen while external JavaScript and CSS are fetched and parsed.",
            "recommendation": "Add defer or async attributes to scripts and optimize critical CSS delivery.",
        },
        "warning": {
            "warning": "Candidate render-blocking resources detected in the HTML head.",
            "potential_impact": "May delay the First Contentful Paint milestone on mobile devices.",
            "recommendation": "Audit head scripts and stylesheets, preloading fonts and deferring secondary CSS.",
        },
    },
    "performance.gzip_compression": {
        "category": "Performance & Core Web Vitals",
        "name": "Text Compression (Gzip/Brotli)",
        "critical": {
            "problem": "Text compression (Gzip/Brotli) is disabled on the web server.",
            "impact": "HTML, CSS, and JS files transfer uncompressed, multiplying download times by 3-5x.",
            "recommendation": "Enable Gzip or Brotli compression on your web server or reverse proxy.",
        },
        "warning": {
            "warning": "Compression is active on HTML but missing on some static text assets.",
            "potential_impact": "Static CSS and JavaScript files take longer than necessary to transfer.",
            "recommendation": "Ensure server compression rules apply to all CSS, JavaScript, and SVG assets.",
        },
    },
    "performance.webp_images": {
        "category": "Performance & Core Web Vitals",
        "name": "WebP Image Optimization",
        "critical": {
            "problem": "Images are served in uncompressed legacy formats without modern format support.",
            "impact": "Increases page load times and mobile data consumption.",
            "recommendation": "Convert and compress images using modern WebP format.",
        },
        "warning": {
            "warning": "Some images could be optimized with modern WebP compression.",
            "potential_impact": "Missed opportunity to reduce image payload and improve Core Web Vitals.",
            "recommendation": "Implement automated WebP conversion for uploaded media assets.",
        },
    },
    "performance.minification": {
        "category": "Performance & Core Web Vitals",
        "name": "Code Minification (CSS/JS)",
        "critical": {
            "problem": "Large unminified source code scripts loaded directly in production.",
            "impact": "Increases download and parse overhead unnecessarily.",
            "recommendation": "Enable automated minification in the build or CDN pipeline.",
        },
        "warning": {
            "warning": "CSS or JavaScript files contain unminified code, whitespace, and comments.",
            "potential_impact": "Increases file sizes and parse time during page loading.",
            "recommendation": "Enable automatic minification for CSS and JS in your build or hosting pipeline.",
        },
    },

    # ── 11. Advanced Schema & Rich Results (5 factors) ───────────────────────
    "schema_advanced.faq_schema": {
        "category": "Structured Data & Schema",
        "name": "FAQPage Schema",
        "critical": {
            "problem": "FAQ markup contains malformed JSON-LD syntax.",
            "impact": "Search engines flag structured data errors and disqualify page from rich results.",
            "recommendation": "Validate and fix FAQPage JSON-LD schema syntax.",
        },
        "warning": {
            "warning": "FAQ content on the page lacks structured FAQPage schema markup.",
            "potential_impact": "Misses eligibility for prominent interactive FAQ snippets in search results.",
            "recommendation": "Add FAQPage JSON-LD markup corresponding to published questions and answers.",
        },
    },
    "schema_advanced.product_schema": {
        "category": "Structured Data & Schema",
        "name": "Product & Service Schema",
        "critical": {
            "problem": "Product/Service schema contains syntax errors or invalid fields.",
            "impact": "Rich search snippets fail to render in search results.",
            "recommendation": "Validate Product/Service JSON-LD against Schema.org standards.",
        },
        "warning": {
            "warning": "Service offerings lack structured Product or Service schema markup.",
            "potential_impact": "Search engines cannot display rich service cards or pricing context.",
            "recommendation": "Add Service or Product schema markup to key business offerings.",
        },
    },
    "schema_advanced.breadcrumb_schema": {
        "category": "Structured Data & Schema",
        "name": "Breadcrumb Schema",
        "critical": {
            "problem": "Breadcrumb schema contains broken URLs or circular hierarchy.",
            "impact": "Corrupts search snippet breadcrumb trails.",
            "recommendation": "Fix BreadcrumbList JSON-LD hierarchy to reflect site structure.",
        },
        "warning": {
            "warning": "Navigation path lacks BreadcrumbList schema markup.",
            "potential_impact": "Search results show raw URL strings rather than a clean breadcrumb trail.",
            "recommendation": "Deploy BreadcrumbList JSON-LD markup reflecting your site structure.",
        },
    },
    "schema_advanced.review_schema": {
        "category": "Structured Data & Schema",
        "name": "Review & Rating Schema",
        "critical": {
            "problem": "Review markup contains fabricated or invalid schema attributes.",
            "impact": "Triggers structured data manual action penalties from search engines.",
            "recommendation": "Ensure AggregateRating schema is backed by authentic, published customer reviews.",
        },
        "warning": {
            "warning": "Customer reviews or ratings lack AggregateRating schema markup.",
            "potential_impact": "Star ratings and review counts cannot appear directly in search results.",
            "recommendation": "Implement AggregateRating schema backed by authentic customer reviews.",
        },
    },
    "schema_advanced.graph_schema": {
        "category": "Structured Data & Schema",
        "name": "Connected Entity Schema Graph",
        "critical": {
            "problem": "Conflicting entity definitions declared across disconnected schema blocks.",
            "impact": "Search engines receive contradictory organization and entity data.",
            "recommendation": "Consolidate entity markup into a single unified JSON-LD graph.",
        },
        "warning": {
            "warning": "Schema markup items are isolated rather than connected via a @graph.",
            "potential_impact": "Search engines must guess relationships between organization and service entities.",
            "recommendation": "Unify all Schema.org entities into a cohesive @graph structure.",
        },
    },

    # ── 12. AI Search Visibility Observation (1 factor) ─────────────────────
    "ai_search.observation": {
        "category": "AI Search Readiness",
        "name": "AI Search Visibility Observation",
        "critical": {
            "problem": "Business entities are completely unrecognized in AI search engine queries.",
            "impact": "Prospective clients querying AI search tools are routed entirely to competitors.",
            "recommendation": "Deploy structured entity data and verified brand citations across trusted industry platforms.",
        },
        "warning": {
            "warning": "AI search engines (such as ChatGPT, Claude, or Perplexity) did not mention the business.",
            "potential_impact": "Prospective customers querying AI search assistants are not guided to your services.",
            "recommendation": "Establish verified digital citations, structured entity data, and AI-search monitoring.",
        },
    },
}


class OpportunityEngine:
    """Evaluates audit findings and generates service opportunities and proposal drafts."""

    @staticmethod
    def get_factor_status(factor: Any) -> str:
        """Extract uppercase status suffix (e.g. 'AuditStatus.FAIL' -> 'FAIL')."""
        if isinstance(factor, dict):
            status_val = factor.get("status")
            if status_val is not None:
                return str(status_val).upper().split(".")[-1]
        return ""

    @classmethod
    def is_confirmed_failure(cls, factor: Any) -> bool:
        """True strictly when the factor verified an explicit FAIL condition."""
        return cls.get_factor_status(factor) == "FAIL"

    @classmethod
    def is_confirmed_warning(cls, factor: Any) -> bool:
        """True strictly when the factor verified an explicit WARN condition."""
        return cls.get_factor_status(factor) == "WARN"

    @classmethod
    def get_factor_finding(
        cls,
        factor_id: str,
        factor: Optional[Dict[str, Any]],
        severity: str,
    ) -> Dict[str, Any]:
        """
        Produce a structured finding for a factor, honoring auditor recorded
        messages/fixes while providing evidence-backed problem/impact/recommendation.
        """
        meta = CANONICAL_FACTORS.get(factor_id, {})
        category = meta.get("category", "Technical SEO")
        name = meta.get("name", factor_id)

        auditor_msg = (factor.get("message") if isinstance(factor, dict) else "") or ""
        auditor_msg = auditor_msg.strip()
        auditor_fix = (factor.get("fix") if isinstance(factor, dict) else "") or ""
        auditor_fix = auditor_fix.strip()

        if severity == "critical":
            default_spec = meta.get("critical", {})
            description = auditor_msg or default_spec.get("problem", f"The {name} audit check failed.")
            impact = default_spec.get("impact", "Negative impact on search discoverability and visitor confidence.")
            recommendation = auditor_fix or default_spec.get("recommendation", f"Remediate and verify {name} configuration.")
            return {
                "factor_id": factor_id,
                "category": category,
                "title": name,
                "severity": "critical",
                "finding_type": "critical_issue",
                "problem": description,
                "impact": impact,
                "recommendation": recommendation,
            }
        else:
            default_spec = meta.get("warning", {})
            description = auditor_msg or default_spec.get("warning", f"The {name} audit check recorded an advisory warning.")
            impact = default_spec.get("potential_impact", "May reduce visitor engagement or optimal search engine crawling.")
            recommendation = auditor_fix or default_spec.get("recommendation", f"Review and optimize {name} configuration.")
            return {
                "factor_id": factor_id,
                "category": category,
                "title": name,
                "severity": "warning",
                "finding_type": "warning",
                "warning": description,
                "potential_impact": impact,
                "recommendation": recommendation,
            }

    @classmethod
    def evaluate_opportunities(
        cls,
        audit_results: Dict[str, Any],
        url_info: Optional[Dict[str, Any]] = None,
        site_summary: Optional[Dict[str, Any]] = None,
        ai_observations: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate audit results across canonical categories and combine verified
        audit findings (both Critical Issues and Warnings), performance diagnostics,
        and AI search visibility observations.
        """
        opportunities: List[Dict[str, Any]] = []
        target_url = (url_info.get("requested_url") if url_info else None) or ""
        lead_id = (url_info.get("lead_id") if url_info else None) or (site_summary or {}).get("lead_id")

        def affected_urls() -> List[str]:
            return [target_url] if target_url else []

        def get_factor(group_name: str, check_key: str) -> Optional[Dict[str, Any]]:
            if not isinstance(audit_results, dict):
                return None
            group = audit_results.get(group_name, {})
            return group.get(check_key) if isinstance(group, dict) else None

        def collected_evidence(factor: Optional[Dict[str, Any]], fallback: str) -> str:
            msg = factor.get("message") if isinstance(factor, dict) else None
            return msg.strip() if isinstance(msg, str) and msg.strip() else fallback

        # ── 1. Technical SEO & Infrastructure Remediation ────────────────────
        tech_ssl = get_factor("technical", "ssl")
        tech_robots = get_factor("technical", "robots")
        tech_canonical = get_factor("technical", "canonical")
        idx_soft_404 = get_factor("indexability", "soft_404")
        tech_https_redir = get_factor("technical", "https_redirect")
        tech_mixed = get_factor("technical", "mixed_content")
        tech_redir_chain = get_factor("technical", "redirect_chain")
        tech_www_canon = get_factor("technical", "www_canonicalization")

        tech_factors: List[str] = []
        tech_critical_fids: List[str] = []
        tech_warning_fids: List[str] = []
        tech_evidence: List[str] = []
        tech_findings: List[Dict[str, Any]] = []

        for fid, fobj, fallback in (
            ("technical.ssl", tech_ssl, "The HTTPS/TLS audit check failed."),
            ("technical.robots", tech_robots, "The robots.txt audit check failed."),
            ("technical.canonical", tech_canonical, "The canonical audit check failed."),
            ("indexability.soft_404", idx_soft_404, "The soft-404 audit check failed."),
            ("technical.https_redirect", tech_https_redir, "The HTTP to HTTPS redirect check failed."),
            ("technical.mixed_content", tech_mixed, "The mixed-content audit check failed."),
            ("technical.redirect_chain", tech_redir_chain, "The redirect-chain audit check failed."),
            ("technical.www_canonicalization", tech_www_canon, "The www-canonicalization audit check failed."),
        ):
            if cls.is_confirmed_failure(fobj):
                tech_factors.append(fid)
                tech_critical_fids.append(fid)
                tech_evidence.append(collected_evidence(fobj, fallback))
                tech_findings.append(cls.get_factor_finding(fid, fobj, "critical"))
            elif cls.is_confirmed_warning(fobj):
                tech_factors.append(fid)
                tech_warning_fids.append(fid)
                tech_evidence.append(collected_evidence(fobj, fallback))
                tech_findings.append(cls.get_factor_finding(fid, fobj, "warning"))

        if tech_factors:
            has_crit = len(tech_critical_fids) > 0
            opportunities.append({
                "service_id": "technical_seo_remediation",
                "service_name": "Technical SEO & Infrastructure Remediation",
                "service_category": "Technical SEO",
                "scope": "repair" if has_crit else "optimization",
                "relevant_factor_ids": tech_factors,
                "critical_factor_ids": tech_critical_fids,
                "warning_factor_ids": tech_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(tech_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(tech_warning_fids) > 0 else "info"),
                "confidence": 1.0 if has_crit else 0.85,
                "evidence": tech_evidence,
                "critical_findings": [f for f in tech_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in tech_findings if f["severity"] == "warning"],
                "findings": tech_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm implementation access and applicable change controls with the site owner."],
                "rationale": "Resolving fundamental HTTP, SSL, and canonical routing issues is necessary for search engines to crawl and index pages safely.",
                "proposed_next_step": "Configure automated HTTPS redirection, standard canonical link elements, and valid robots.txt rules.",
                "evidence_type": "audit_factor",
                "evidence_source": "Canonical Audit",
                "limitations": None,
            })

        # ── 2. XML Sitemap & Indexing Architecture ───────────────────────────
        tech_sitemap = get_factor("technical", "sitemap")
        idx_noindex = get_factor("indexability", "noindex") or get_factor("onpage", "noindex")
        links_broken = get_factor("links", "broken_links")
        idx_url_struct = get_factor("indexability", "url_structure")
        idx_www_v_non = get_factor("indexability", "www_vs_nonwww")

        sitemap_factors: List[str] = []
        sitemap_critical_fids: List[str] = []
        sitemap_warning_fids: List[str] = []
        sitemap_evidence: List[str] = []
        sitemap_findings: List[Dict[str, Any]] = []

        for fid, fobj, fallback in (
            ("technical.sitemap", tech_sitemap, "The XML sitemap audit check failed."),
            ("indexability.noindex", idx_noindex, "The noindex audit check failed."),
            ("links.broken_links", links_broken, "The broken-link audit check failed."),
            ("indexability.url_structure", idx_url_struct, "The URL structure audit check failed."),
            ("indexability.www_vs_nonwww", idx_www_v_non, "The www/non-www consistency check failed."),
        ):
            if cls.is_confirmed_failure(fobj):
                sitemap_factors.append(fid)
                sitemap_critical_fids.append(fid)
                sitemap_evidence.append(collected_evidence(fobj, fallback))
                sitemap_findings.append(cls.get_factor_finding(fid, fobj, "critical"))
            elif cls.is_confirmed_warning(fobj):
                sitemap_factors.append(fid)
                sitemap_warning_fids.append(fid)
                sitemap_evidence.append(collected_evidence(fobj, fallback))
                sitemap_findings.append(cls.get_factor_finding(fid, fobj, "warning"))

        if sitemap_factors:
            has_crit = len(sitemap_critical_fids) > 0
            opportunities.append({
                "service_id": "sitemap_indexing_repair",
                "service_name": "Sitemap Discovery & Indexing Architecture",
                "service_category": "Crawl & Indexing",
                "scope": "repair" if has_crit else "optimization",
                "relevant_factor_ids": sitemap_factors,
                "critical_factor_ids": sitemap_critical_fids,
                "warning_factor_ids": sitemap_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(sitemap_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(sitemap_warning_fids) > 0 else "info"),
                "confidence": 0.95 if has_crit else 0.82,
                "evidence": sitemap_evidence,
                "critical_findings": [f for f in sitemap_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in sitemap_findings if f["severity"] == "warning"],
                "findings": sitemap_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm which published URLs should remain indexable before changing directives or redirects."],
                "rationale": "A validated XML sitemap and clean internal links allow search engine crawlers to discover all published service pages without crawl waste.",
                "proposed_next_step": "Generate a clean sitemap.xml, declare it in robots.txt, and eliminate 404 internal hyperlinks.",
                "evidence_type": "audit_factor",
                "evidence_source": "Canonical Audit",
                "limitations": None,
            })

        # ── 3. Local SEO, Entity Alignment & Structured Data ─────────────────
        local_nap = get_factor("local_seo", "nap_consistency") or get_factor("local_seo", "has_nap")
        local_schema = get_factor("local_seo", "local_business_schema") or get_factor("local_seo", "has_local_business_schema")
        local_maps = get_factor("local_seo", "google_maps_embed") or get_factor("local_seo", "has_google_maps")
        local_city = get_factor("local_seo", "city_in_title")
        local_hours = get_factor("local_seo", "business_hours")
        onpage_schema = get_factor("onpage", "schema")

        # Advanced schema factors
        sch_faq = get_factor("schema_advanced", "faq_schema")
        sch_prod = get_factor("schema_advanced", "product_schema")
        sch_bc = get_factor("schema_advanced", "breadcrumb_schema")
        sch_rev = get_factor("schema_advanced", "review_schema")
        sch_graph = get_factor("schema_advanced", "graph_schema")

        local_factors: List[str] = []
        local_critical_fids: List[str] = []
        local_warning_fids: List[str] = []
        local_evidence: List[str] = []
        local_findings: List[Dict[str, Any]] = []

        schema_key = "local_seo.local_business_schema" if get_factor("local_seo", "local_business_schema") else "local_seo.has_local_business_schema"
        nap_key = "local_seo.nap_consistency" if get_factor("local_seo", "nap_consistency") else "local_seo.has_nap"
        maps_key = "local_seo.google_maps_embed" if get_factor("local_seo", "google_maps_embed") else "local_seo.has_google_maps"

        for fid, fobj, fallback in (
            (schema_key, local_schema, "The LocalBusiness schema audit check failed."),
            ("onpage.schema", onpage_schema, "The structured-data audit check failed."),
            (nap_key, local_nap, "The business NAP audit check failed."),
            (maps_key, local_maps, "The Google Maps audit check failed."),
            ("local_seo.city_in_title", local_city, "The city-in-title audit check failed."),
            ("local_seo.business_hours", local_hours, "The business-hours audit check failed."),
            ("schema_advanced.faq_schema", sch_faq, "The FAQ schema audit check failed."),
            ("schema_advanced.product_schema", sch_prod, "The Product schema audit check failed."),
            ("schema_advanced.breadcrumb_schema", sch_bc, "The Breadcrumb schema audit check failed."),
            ("schema_advanced.review_schema", sch_rev, "The Review schema audit check failed."),
            ("schema_advanced.graph_schema", sch_graph, "The Schema graph audit check failed."),
        ):
            if cls.is_confirmed_failure(fobj):
                local_factors.append(fid)
                local_critical_fids.append(fid)
                local_evidence.append(collected_evidence(fobj, fallback))
                local_findings.append(cls.get_factor_finding(fid, fobj, "critical"))
            elif cls.is_confirmed_warning(fobj):
                local_factors.append(fid)
                local_warning_fids.append(fid)
                local_evidence.append(collected_evidence(fobj, fallback))
                local_findings.append(cls.get_factor_finding(fid, fobj, "warning"))

        if local_factors:
            has_crit = len(local_critical_fids) > 0
            opportunities.append({
                "service_id": "local_seo_entity_alignment",
                "service_name": "Local SEO & Entity Structured Data",
                "service_category": "Local SEO",
                "scope": "repair" if has_crit else "optimization",
                "relevant_factor_ids": local_factors,
                "critical_factor_ids": local_critical_fids,
                "warning_factor_ids": local_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(local_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(local_warning_fids) > 0 else "info"),
                "confidence": 0.9 if has_crit else 0.80,
                "evidence": local_evidence,
                "critical_findings": [f for f in local_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in local_findings if f["severity"] == "warning"],
                "findings": local_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm the business's authoritative name, address, phone, hours, and location data before publishing entity markup."],
                "rationale": "Structured LocalBusiness schema and consistent business NAP details build trust with search engines and support visibility in local map packs.",
                "proposed_next_step": "Deploy schema.org JSON-LD matching business records and embed verified location coordinates.",
                "evidence_type": "audit_factor",
                "evidence_source": "Canonical Audit",
                "limitations": None,
            })

        # ── 4. Web Design & UI/UX Experience ────────────────────────────────
        ux_cta = get_factor("ux", "cta")
        ux_fold = get_factor("ux", "cta_above_fold")
        ux_mobile = get_factor("technical", "mobile")
        ux_contrast = get_factor("ux", "contrast")
        ux_font = get_factor("ux", "font_size")
        ux_hero = get_factor("ux", "hero_headline")
        ux_nav = get_factor("ux", "nav_links")
        ux_cookie = get_factor("ux", "cookie_notice")
        ux_chat = get_factor("ux", "live_chat")
        ux_phone = get_factor("ux", "phone_number")
        ux_addr = get_factor("ux", "address_presence")

        # Conversion channels
        conv_social = get_factor("conversion", "social")
        conv_contact = get_factor("conversion", "contact")
        conv_whatsapp = get_factor("conversion", "whatsapp")
        conv_trust = get_factor("conversion", "trust")

        ux_factors: List[str] = []
        ux_critical_fids: List[str] = []
        ux_warning_fids: List[str] = []
        ux_evidence: List[str] = []
        ux_findings: List[Dict[str, Any]] = []

        for fid, fobj, fallback in (
            ("technical.mobile", ux_mobile, "The mobile viewport audit check failed."),
            ("ux.cta", ux_cta, "Clear primary call-to-action button missing."),
            ("ux.cta_above_fold", ux_fold, "The above-the-fold CTA audit check failed."),
            ("ux.contrast", ux_contrast, "The contrast audit check failed."),
            ("ux.font_size", ux_font, "The text-size audit check failed."),
            ("ux.hero_headline", ux_hero, "The hero headline check failed."),
            ("ux.nav_links", ux_nav, "The navigation links check failed."),
            ("ux.phone_number", ux_phone, "The phone number presence check failed."),
            ("ux.address_presence", ux_addr, "The address presence check failed."),
            ("ux.cookie_notice", ux_cookie, "The cookie notice check failed."),
            ("ux.live_chat", ux_chat, "The live chat check failed."),
            ("conversion.contact", conv_contact, "Clickable contact links check failed."),
            ("conversion.social", conv_social, "Social profile links check failed."),
            ("conversion.whatsapp", conv_whatsapp, "WhatsApp integration check failed."),
            ("conversion.trust", conv_trust, "Trust pages check failed."),
        ):
            if cls.is_confirmed_failure(fobj):
                ux_factors.append(fid)
                ux_critical_fids.append(fid)
                ux_evidence.append(collected_evidence(fobj, fallback))
                ux_findings.append(cls.get_factor_finding(fid, fobj, "critical"))
            elif cls.is_confirmed_warning(fobj):
                ux_factors.append(fid)
                ux_warning_fids.append(fid)
                ux_evidence.append(collected_evidence(fobj, fallback))
                ux_findings.append(cls.get_factor_finding(fid, fobj, "warning"))

        # Domain H: Advanced Web Design & Observable Code Health from browser evidence
        bev = (site_summary or {}).get("browser_evidence")
        has_browser_overflow = False
        if isinstance(bev, dict):
            if bev.get("has_horizontal_overflow") or (isinstance(bev.get("overflow_px"), (int, float)) and bev["overflow_px"] > 0):
                has_browser_overflow = True
                overflow_px = bev.get("overflow_px", 0)
                ux_evidence.append(f"Rendered mobile browser detected horizontal scroll overflow of {overflow_px}px.")
                if "technical.mobile" not in ux_factors:
                    ux_factors.append("technical.mobile")
                    ux_critical_fids.append("technical.mobile")
                    ux_findings.append({
                        "factor_id": "technical.mobile",
                        "category": "Mobile Usability & Responsive Design",
                        "title": "Mobile Viewport & Horizontal Overflow",
                        "severity": "critical",
                        "finding_type": "critical_issue",
                        "problem": f"Rendered mobile viewport detected horizontal scroll overflow of {overflow_px}px.",
                        "impact": "Content extends beyond device boundaries, forcing awkward sideways scrolling on mobile devices.",
                        "recommendation": "Correct fixed-width CSS containers and ensure all page components fit within the 100vw viewport.",
                    })

            design_diag = bev.get("design_diagnostics")
            if isinstance(design_diag, dict):
                diag_issues = design_diag.get("issues", [])
                for issue in diag_issues:
                    code = issue.get("code")
                    msg = issue.get("message")
                    if code in ("FIXED_WIDTH_OVERFLOW_RISK", "MISSING_VIEWPORT_META") and "technical.mobile" not in ux_factors:
                        ux_factors.append("technical.mobile")
                        if code == "MISSING_VIEWPORT_META":
                            ux_critical_fids.append("technical.mobile")
                        else:
                            ux_warning_fids.append("technical.mobile")
                    if msg:
                        diag_msg = f"Web design diagnostic: {msg}"
                        if diag_msg not in ux_evidence:
                            ux_evidence.append(diag_msg)

        if ux_factors:
            is_full_redesign = ("technical.mobile" in ux_critical_fids) and (len(ux_critical_fids) >= 3 or has_browser_overflow)
            has_crit = len(ux_critical_fids) > 0
            if is_full_redesign:
                scope = "redesign"
                name = "Modern Website Redesign & Conversion Architecture"
            elif has_crit:
                scope = "repair"
                name = "Web Design & Conversion UX Repair"
            else:
                scope = "optimization"
                name = "Web Design & Conversion UX Optimization"

            opportunities.append({
                "service_id": "web_design_ux_improvement",
                "service_name": name,
                "service_category": "Web Design & UX",
                "scope": scope,
                "relevant_factor_ids": ux_factors,
                "critical_factor_ids": ux_critical_fids,
                "warning_factor_ids": ux_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(ux_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(ux_warning_fids) > 0 else "info"),
                "confidence": 0.9 if has_crit else 0.82,
                "evidence": ux_evidence,
                "critical_findings": [f for f in ux_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in ux_findings if f["severity"] == "warning"],
                "findings": ux_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Review current brand, accessibility, and conversion-path requirements with the site owner before design changes."],
                "rationale": "The verified mobile, readability, and contact-path findings support a coordinated responsive redesign review." if is_full_redesign else "The verified button, readability, and layout findings support a focused usability review.",
                "proposed_next_step": "Implement a responsive modern design system with prominent above-the-fold contact actions and verified mobile viewports." if is_full_redesign else "Refine button styling, above-the-fold placement, and typography contrast.",
                "evidence_type": "combined" if has_browser_overflow else "audit_factor",
                "evidence_source": "Browser & Audit Diagnostics" if has_browser_overflow else "Canonical Audit",
                "limitations": None,
            })

        # ── 5. Performance, Speed & Asset Optimization ───────────────────────
        perf_ttfb = get_factor("performance", "response_time")
        perf_blocking = get_factor("performance", "render_blocking")
        img_webp = get_factor("images", "webp")
        img_lazy = get_factor("images", "lazy_load")
        perf_size = get_factor("performance", "page_size")
        perf_gzip = get_factor("performance", "gzip_compression")
        perf_webp_cov = get_factor("performance", "webp_images")
        perf_minify = get_factor("performance", "minification")

        perf_factors: List[str] = []
        perf_critical_fids: List[str] = []
        perf_warning_fids: List[str] = []
        perf_evidence: List[str] = []
        perf_findings: List[Dict[str, Any]] = []

        for fid, fobj, fallback in (
            ("performance.response_time", perf_ttfb, "The response-time audit check failed."),
            ("performance.render_blocking", perf_blocking, "The render-blocking audit check failed."),
            ("images.webp", img_webp, "The modern-image-format audit check failed."),
            ("images.lazy_load", img_lazy, "The lazy-loading audit check failed."),
            ("performance.page_size", perf_size, "The page-size audit check failed."),
            ("performance.gzip_compression", perf_gzip, "The compression audit check failed."),
            ("performance.webp_images", perf_webp_cov, "The WebP coverage check failed."),
            ("performance.minification", perf_minify, "The minification check failed."),
        ):
            if cls.is_confirmed_failure(fobj):
                perf_factors.append(fid)
                perf_critical_fids.append(fid)
                perf_evidence.append(collected_evidence(fobj, fallback))
                perf_findings.append(cls.get_factor_finding(fid, fobj, "critical"))
            elif cls.is_confirmed_warning(fobj):
                perf_factors.append(fid)
                perf_warning_fids.append(fid)
                perf_evidence.append(collected_evidence(fobj, fallback))
                perf_findings.append(cls.get_factor_finding(fid, fobj, "warning"))

        # Advanced Performance Diagnostics evaluation
        perf_diag = None
        if isinstance(bev, dict):
            perf_diag = bev.get("performance_diagnostics")
        if not perf_diag and isinstance(site_summary, dict):
            perf_diag = site_summary.get("performance_diagnostics")

        has_perf_diag = isinstance(perf_diag, dict) and bool(perf_diag.get("available"))
        perf_limitation: Optional[str] = None
        diag_details = None

        if has_perf_diag:
            res_summary = perf_diag.get("resource_summary", {})
            has_sizes = bool(res_summary.get("has_transfer_size_data"))
            total_reqs = res_summary.get("total_requests", 0)
            total_kb = res_summary.get("total_transfer_kb", 0.0)
            by_type = res_summary.get("by_type", {})

            if has_sizes:
                if total_kb > 1500:
                    perf_evidence.append(f"Rendered browser observed total transfer volume of {total_kb} KB across {total_reqs} requests.")
                    if "performance.response_time" not in perf_factors:
                        perf_factors.append("performance.response_time")
                        perf_warning_fids.append("performance.response_time")
                img_data = by_type.get("image", {})
                img_kb = img_data.get("transfer_kb", 0.0)
                img_count = img_data.get("count", 0)
                if img_kb > 800 or (img_count >= 5 and img_kb > 500):
                    perf_evidence.append(f"Observed {img_count} image requests consuming {img_kb} KB transfer volume.")
                    if "images.webp" not in perf_factors:
                        perf_factors.append("images.webp")
                        perf_warning_fids.append("images.webp")

            failure_bd = perf_diag.get("failure_breakdown", {})
            http_errors_count = failure_bd.get("http_errors_count", 0)
            failed_requests_count = failure_bd.get("failed_requests_count", 0)

            if http_errors_count > 0:
                perf_evidence.append(f"Browser observed {http_errors_count} HTTP 4xx/5xx error response(s) on page subresources.")
                if "performance.render_blocking" not in perf_factors:
                    perf_factors.append("performance.render_blocking")
                    perf_critical_fids.append("performance.render_blocking")

            if failed_requests_count > 0:
                perf_evidence.append(f"Browser observed {failed_requests_count} network connection failure(s) or proxy-blocked request(s).")
                if "performance.render_blocking" not in perf_factors:
                    perf_factors.append("performance.render_blocking")
                    perf_warning_fids.append("performance.render_blocking")

            console_ev = perf_diag.get("console_evidence", {})
            actionable_errs = console_ev.get("actionable_errors", [])
            if actionable_errs:
                perf_evidence.append(f"Browser console recorded {len(actionable_errs)} runtime JavaScript error(s) during page execution.")
                if "performance.render_blocking" not in perf_factors:
                    perf_factors.append("performance.render_blocking")
                    perf_warning_fids.append("performance.render_blocking")

            rb_candidates = perf_diag.get("render_blocking_candidates", {})
            total_rb = rb_candidates.get("total_candidates", 0)
            if total_rb > 0:
                scripts_cnt = len(rb_candidates.get("scripts", []))
                styles_cnt = len(rb_candidates.get("stylesheets", []))
                parts = []
                if scripts_cnt:
                    parts.append(f"{scripts_cnt} synchronous script(s)")
                if styles_cnt:
                    parts.append(f"{styles_cnt} stylesheet(s)")
                candidate_desc = " and ".join(parts) or f"{total_rb} resource(s)"
                perf_evidence.append(
                    f"Identified {total_rb} candidate render-blocking resource(s) in HTML head ({candidate_desc}). "
                    "Note: Candidate heuristic; actual blocking impact requires network execution confirmation."
                )
                if "performance.render_blocking" not in perf_factors:
                    perf_factors.append("performance.render_blocking")
                    perf_warning_fids.append("performance.render_blocking")

            page_idx = perf_diag.get("page_index", 0) + 1
            total_pages = perf_diag.get("total_pages_captured", 1)
            perf_limitation = (
                f"Observed from captured page {page_idx} of {total_pages} (controlled crawl sample, up to 5-page crawl limit). "
                "Candidate render-blocking resources are heuristics based on DOM placement; actual rendering delay depends on network priority and caching."
            )
            diag_details = {
                "has_transfer_size_data": has_sizes,
                "total_requests": total_reqs,
                "total_transfer_kb": total_kb if has_sizes else None,
                "by_type": by_type,
                "http_errors_count": http_errors_count,
                "http_errors": failure_bd.get("http_errors", [])[:5],
                "failed_requests_count": failed_requests_count,
                "failed_requests": failure_bd.get("failed_requests", [])[:5],
                "actionable_errors": actionable_errs[:5],
                "render_blocking_candidates": {
                    "total_candidates": total_rb,
                    "scripts": rb_candidates.get("scripts", [])[:5],
                    "stylesheets": rb_candidates.get("stylesheets", [])[:5],
                },
                "page_index": page_idx,
                "total_pages_captured": total_pages,
                "crawl_limit": 5,
            }
        else:
            diag_details = None
            if isinstance(bev, dict) and bev.get("failed_requests"):
                failed_reqs = bev.get("failed_requests", [])
                if failed_reqs:
                    if "performance.render_blocking" not in perf_factors:
                        perf_factors.append("performance.render_blocking")
                        perf_critical_fids.append("performance.render_blocking")
                        perf_findings.append({
                            "factor_id": "performance.render_blocking",
                            "category": "Performance & Core Web Vitals",
                            "title": "Failed Subresource Requests",
                            "severity": "critical",
                            "finding_type": "critical_issue",
                            "problem": f"Browser observed {len(failed_reqs)} failed subresource request(s) affecting page assets.",
                            "impact": "Broken subresources prevent page components from rendering correctly.",
                            "recommendation": "Investigate and resolve failed subresource URLs to ensure all page assets load cleanly.",
                        })
                    perf_evidence.append(f"Browser observed {len(failed_reqs)} failed subresource request(s) affecting page assets.")

        if perf_factors:
            has_crit = len(perf_critical_fids) > 0
            opportunities.append({
                "service_id": "performance_speed_optimization",
                "service_name": "Performance, Speed & Asset Optimization",
                "service_category": "Performance",
                "scope": "repair" if has_crit else "optimization",
                "relevant_factor_ids": perf_factors,
                "critical_factor_ids": perf_critical_fids,
                "warning_factor_ids": perf_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(perf_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(perf_warning_fids) > 0 else "info"),
                "confidence": 0.88 if has_perf_diag else (0.85 if has_crit else 0.80),
                "evidence": perf_evidence,
                "critical_findings": [f for f in perf_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in perf_findings if f["severity"] == "warning"],
                "findings": perf_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm hosting, CDN, build-pipeline, and asset-management access before performance changes."],
                "rationale": "The audit recorded response or asset-delivery findings that support a scoped performance investigation and improvement plan.",
                "proposed_next_step": "Enable asset compression, resolve HTTP subresource errors, convert image assets to modern WebP format, and audit candidate render-blocking scripts.",
                "evidence_type": "browser_diagnostic" if (has_perf_diag and not cls.is_confirmed_failure(perf_ttfb) and not cls.is_confirmed_failure(perf_blocking)) else "combined",
                "evidence_source": "Browser Performance Diagnostics" if has_perf_diag else "Canonical Audit",
                "limitations": perf_limitation,
                "diagnostic_details": diag_details,
            })

        # ── 6. AI-Search & Entity Readiness Heuristics + Observations ────────
        raw_ai_obs = ai_observations or (site_summary or {}).get("ai_observations") or (url_info or {}).get("ai_observations") or []
        norm_target_domain = normalize_domain(target_url) if target_url else ""

        valid_matching_obs: List[Dict[str, Any]] = []
        for obs in raw_ai_obs:
            if not isinstance(obs, dict):
                continue
            obs_dom = normalize_domain(obs.get("target_domain") or "")
            if norm_target_domain and obs_dom and obs_dom != norm_target_domain:
                continue
            if lead_id and obs.get("lead_id") and str(obs["lead_id"]) != str(lead_id):
                continue
            if not obs.get("search_query") or not str(obs["search_query"]).strip():
                continue
            if obs.get("mention_status") not in ("mentioned", "not_mentioned", "unknown"):
                continue
            valid_matching_obs.append(obs)

        ai_factors: List[str] = []
        ai_critical_fids: List[str] = []
        ai_warning_fids: List[str] = []
        ai_evidence: List[str] = []
        ai_findings: List[Dict[str, Any]] = []

        onpage_title = get_factor("onpage", "page_title")
        onpage_h1 = get_factor("onpage", "h1")

        if cls.is_confirmed_failure(local_schema):
            ai_factors.append(schema_key)
            ai_critical_fids.append(schema_key)
            ai_evidence.append(collected_evidence(local_schema, "The LocalBusiness schema audit check failed."))
            ai_findings.append(cls.get_factor_finding(schema_key, local_schema, "critical"))
        elif cls.is_confirmed_warning(local_schema):
            ai_factors.append(schema_key)
            ai_warning_fids.append(schema_key)
            ai_evidence.append(collected_evidence(local_schema, "The LocalBusiness schema audit check recorded an advisory warning."))
            ai_findings.append(cls.get_factor_finding(schema_key, local_schema, "warning"))

        if cls.is_confirmed_failure(onpage_title):
            ai_factors.append("onpage.page_title")
            ai_critical_fids.append("onpage.page_title")
            ai_evidence.append(collected_evidence(onpage_title, "The page-title audit check failed."))
            ai_findings.append(cls.get_factor_finding("onpage.page_title", onpage_title, "critical"))
        elif cls.is_confirmed_warning(onpage_title):
            ai_factors.append("onpage.page_title")
            ai_warning_fids.append("onpage.page_title")
            ai_evidence.append(collected_evidence(onpage_title, "The page-title audit check recorded an advisory warning."))
            ai_findings.append(cls.get_factor_finding("onpage.page_title", onpage_title, "warning"))

        if cls.is_confirmed_failure(onpage_h1):
            ai_factors.append("onpage.h1")
            ai_critical_fids.append("onpage.h1")
            ai_evidence.append(collected_evidence(onpage_h1, "Primary H1 heading is missing."))
            ai_findings.append(cls.get_factor_finding("onpage.h1", onpage_h1, "critical"))
        elif cls.is_confirmed_warning(onpage_h1):
            ai_factors.append("onpage.h1")
            ai_warning_fids.append("onpage.h1")
            ai_evidence.append(collected_evidence(onpage_h1, "Primary H1 heading recorded an advisory warning."))
            ai_findings.append(cls.get_factor_finding("onpage.h1", onpage_h1, "warning"))

        ai_obs_meta: Optional[Dict[str, Any]] = None
        if valid_matching_obs:
            sorted_obs = sorted(valid_matching_obs, key=lambda x: str(x.get("observed_at") or ""), reverse=True)
            top_obs = sorted_obs[0]
            ai_obs_meta = top_obs

            s_type = (top_obs.get("source_type") or "manual").lower()
            if s_type == "manual":
                source_label = "manual observation recorded by operator"
                prov_name = "Manual Observation"
            elif s_type == "structured_import":
                source_label = "structured import observation"
                prov_name = top_obs.get("provider") or "Structured Import"
            else:
                prov_name = top_obs.get("provider") or "AI Provider API"
                source_label = f"verified live query observation via {prov_name}"

            q = top_obs.get("search_query", "").strip()
            m_stat = (top_obs.get("mention_status") or "unknown").lower()
            obs_date = (top_obs.get("observed_at") or "")[:10] or "recently"

            if m_stat == "not_mentioned":
                ev_str = f"Recorded {source_label} on {obs_date} for query '{q}' did not observe a mention of the business."
            elif m_stat == "mentioned":
                ev_str = f"Recorded {source_label} on {obs_date} for query '{q}' observed a brand mention of the business."
            else:
                ev_str = f"Recorded {source_label} on {obs_date} for query '{q}' recorded an indeterminate mention status."

            citations = top_obs.get("citation_urls") or []
            if citations:
                ev_str += f" The recorded observation includes a citation to {citations[0]}."

            if ev_str not in ai_evidence:
                ai_evidence.append(ev_str)

            if "ai_search.observation" not in ai_factors:
                ai_factors.append("ai_search.observation")
                ai_warning_fids.append("ai_search.observation")
                ai_findings.append({
                    "factor_id": "ai_search.observation",
                    "category": "AI Search Readiness",
                    "title": "AI Search Visibility Observation",
                    "severity": "warning",
                    "finding_type": "warning",
                    "warning": ev_str,
                    "potential_impact": "Prospective clients using conversational AI search assistants may not discover your business services.",
                    "recommendation": "Establish recurring AI search observation across target queries and refine JSON-LD entity definitions.",
                })

        if ai_factors:
            has_obs = "ai_search.observation" in ai_factors
            is_obs_only = has_obs and all(f == "ai_search.observation" for f in ai_factors)
            has_crit = len(ai_critical_fids) > 0

            service_id = "ai_search_visibility_monitoring" if is_obs_only else "ai_search_entity_readiness"
            service_name = "AI Search Visibility Monitoring & Entity Optimization" if has_obs else "AI-Search Readiness & Entity Optimization"
            service_scope = "monitoring" if is_obs_only else ("repair" if has_crit else "optimization")
            confidence = 0.85 if has_obs else (0.80 if has_crit else 0.75)

            if has_obs:
                limitation_text = (
                    "Single prompt observation; does not establish ranking, global presence, or ongoing visibility trends. "
                    "Further observation is needed because there is not enough historical evidence to establish a trend."
                )
                ev_type = "ai_search_observation" if is_obs_only else "combined"
                ev_source = prov_name if has_obs else "Canonical Audit"
            else:
                limitation_text = "Readiness heuristic evaluated from robots directives and schema markup; does not guarantee citation or ranking outcomes."
                ev_type = "audit_factor"
                ev_source = "Canonical Audit"

            ai_details = {
                "observation_id": ai_obs_meta.get("observation_id"),
                "search_query": ai_obs_meta.get("search_query"),
                "observed_at": ai_obs_meta.get("observed_at"),
                "source_type": ai_obs_meta.get("source_type", "manual"),
                "provider": prov_name,
                "mention_status": ai_obs_meta.get("mention_status"),
                "citation_found": ai_obs_meta.get("citation_found", False),
                "citation_urls": ai_obs_meta.get("citation_urls", []),
                "search_engine": ai_obs_meta.get("search_engine"),
                "notes": ai_obs_meta.get("notes"),
                "limitations": limitation_text,
            } if has_obs and ai_obs_meta else None

            opportunities.append({
                "service_id": service_id,
                "service_name": service_name,
                "service_category": "AI Search Readiness",
                "scope": service_scope,
                "relevant_factor_ids": ai_factors,
                "critical_factor_ids": ai_critical_fids,
                "warning_factor_ids": ai_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(ai_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(ai_warning_fids) > 0 else "info"),
                "confidence": confidence,
                "evidence": ai_evidence,
                "critical_findings": [f for f in ai_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in ai_findings if f["severity"] == "warning"],
                "findings": ai_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm factual business data, priority search queries, and approved structured-content sources before publishing entity changes."],
                "rationale": "The verified observations and entity-data findings support an AI-search visibility review and ongoing monitoring; they do not establish guaranteed rankings, citations, or global visibility outcomes.",
                "proposed_next_step": "Establish recurring AI search observation across target queries and refine JSON-LD entity definitions; no citation or ranking outcome is guaranteed.",
                "evidence_type": ev_type,
                "evidence_source": ev_source,
                "observation_id": ai_obs_meta.get("observation_id") if ai_obs_meta else None,
                "evidence_date": ai_obs_meta.get("observed_at") if ai_obs_meta else None,
                "limitations": limitation_text,
                "ai_observation_details": ai_details,
            })

        # ── 7. On-page SEO & Content Optimization ────────────────────────────
        onpage_factors: List[str] = []
        onpage_critical_fids: List[str] = []
        onpage_warning_fids: List[str] = []
        onpage_evidence: List[str] = []
        onpage_findings: List[Dict[str, Any]] = []

        for factor_id, factor, fallback in (
            ("onpage.page_title", onpage_title, "The page-title audit check failed."),
            ("onpage.h1", onpage_h1, "The H1 audit check failed."),
            ("onpage.meta_desc", get_factor("onpage", "meta_desc"), "The meta-description audit check failed."),
            ("onpage.og_tags", get_factor("onpage", "og_tags"), "The Open Graph tags check failed."),
            ("onpage.heading_hierarchy", get_factor("onpage", "heading_hierarchy"), "The heading hierarchy check failed."),
            ("onpage.internal_links", get_factor("onpage", "internal_links"), "The internal links check failed."),
            ("onpage.anchor_text_quality", get_factor("onpage", "anchor_text_quality"), "The anchor text check failed."),
            ("onpage.image_filenames", get_factor("onpage", "image_filenames"), "The image filenames check failed."),
            ("images.alt_text", get_factor("images", "alt_text"), "The image alt-text check failed."),
            ("content.word_count", get_factor("content", "word_count"), "The content-depth audit check failed."),
            ("content.duplicate_meta", get_factor("content", "duplicate_meta"), "The duplicate-meta audit check failed."),
            ("content.keyword_in_title", get_factor("content", "keyword_in_title"), "The keyword-in-title audit check failed."),
            ("content.reading_level", get_factor("content", "reading_level"), "The reading-level audit check failed."),
        ):
            if cls.is_confirmed_failure(factor):
                onpage_factors.append(factor_id)
                onpage_critical_fids.append(factor_id)
                onpage_evidence.append(collected_evidence(factor, fallback))
                onpage_findings.append(cls.get_factor_finding(factor_id, factor, "critical"))
            elif cls.is_confirmed_warning(factor):
                onpage_factors.append(factor_id)
                onpage_warning_fids.append(factor_id)
                onpage_evidence.append(collected_evidence(factor, fallback))
                onpage_findings.append(cls.get_factor_finding(factor_id, factor, "warning"))

        if onpage_factors:
            has_crit = len(onpage_critical_fids) > 0
            opportunities.append({
                "service_id": "onpage_content_optimization",
                "service_name": "On-Page SEO & Content Optimization",
                "service_category": "On-Page SEO",
                "scope": "repair" if has_crit else "optimization",
                "relevant_factor_ids": onpage_factors,
                "critical_factor_ids": onpage_critical_fids,
                "warning_factor_ids": onpage_warning_fids,
                "has_critical": has_crit,
                "has_warnings": len(onpage_warning_fids) > 0,
                "severity": "critical" if has_crit else ("warning" if len(onpage_warning_fids) > 0 else "info"),
                "confidence": 0.78,
                "evidence": onpage_evidence,
                "critical_findings": [f for f in onpage_findings if f["severity"] == "critical"],
                "warning_findings": [f for f in onpage_findings if f["severity"] == "warning"],
                "findings": onpage_findings,
                "affected_urls": affected_urls(),
                "prerequisites": ["Confirm target services, locations, and brand-approved copy before publishing content changes."],
                "rationale": "The completed audit recorded on-page or content findings that support a focused metadata, heading, and content-quality review.",
                "proposed_next_step": "Prepare and review page titles, headings, metadata, and service content against the verified findings before publication.",
                "evidence_type": "audit_factor",
                "evidence_source": "Canonical Audit",
                "limitations": None,
            })

        # ── 8. Website Support & Monitoring ──────────────────────────────────
        if len(opportunities) >= 2:
            monitoring_factors: List[str] = []
            monitoring_critical_fids: List[str] = []
            monitoring_warning_fids: List[str] = []
            monitoring_evidence: List[str] = []
            for opportunity in opportunities:
                for factor_id in opportunity["relevant_factor_ids"]:
                    if factor_id not in monitoring_factors:
                        monitoring_factors.append(factor_id)
                for fid in opportunity.get("critical_factor_ids", []):
                    if fid not in monitoring_critical_fids:
                        monitoring_critical_fids.append(fid)
                for fid in opportunity.get("warning_factor_ids", []):
                    if fid not in monitoring_warning_fids:
                        monitoring_warning_fids.append(fid)
                for item in opportunity["evidence"]:
                    if item not in monitoring_evidence:
                        monitoring_evidence.append(item)
            opportunities.append({
                "service_id": "support_monitoring",
                "service_name": "Website Support & Monitoring",
                "service_category": "Support & Monitoring",
                "scope": "monitoring",
                "relevant_factor_ids": monitoring_factors,
                "critical_factor_ids": monitoring_critical_fids,
                "warning_factor_ids": monitoring_warning_fids,
                "has_critical": len(monitoring_critical_fids) > 0,
                "has_warnings": len(monitoring_warning_fids) > 0,
                "severity": "info",
                "confidence": 0.65,
                "evidence": monitoring_evidence[:3],
                "critical_findings": [],
                "warning_findings": [],
                "findings": [],
                "affected_urls": affected_urls(),
                "prerequisites": ["Agree the monitored URLs, alert thresholds, ownership, and change window with the site owner."],
                "rationale": "Multiple verified findings indicate that implementation follow-through and periodic checks may be useful after repairs are approved.",
                "proposed_next_step": "Define a lightweight monitoring plan for the verified factors after agreed remediation work is completed.",
                "evidence_type": "audit_factor",
                "evidence_source": "Canonical Audit",
                "limitations": None,
            })

        return opportunities

    @classmethod
    def generate_proposal_draft(
        cls,
        business_name: str,
        website_url: str,
        opportunities: List[Dict[str, Any]],
        sender_agency: str = "TEB Solutions",
        contact_email: str = "info@tebsolutions.in",
    ) -> Dict[str, Any]:
        """
        Generate a personalized, truthful proposal email draft derived exclusively
        from verified audit opportunities.
        Implements the required structure:
        - Critical Issues (with description, actual evidence impact, recommended resolution)
        - Warnings (with description, potential evidence impact, recommended step)
        - Recommendations and Next Steps (prioritized summary)
        - HTML and plain-text parity with complete XSS protection.
        """
        # Select at most 2–3 top opportunities for focus
        selected_opps = sorted(opportunities, key=lambda item: item.get("confidence", 0), reverse=True)[:3]
        contributing_factors: List[str] = []
        observations: List[Dict[str, Any]] = []

        all_critical_findings: List[Dict[str, Any]] = []
        all_warning_findings: List[Dict[str, Any]] = []

        for opp in selected_opps:
            for fid in opp.get("relevant_factor_ids", []):
                if fid not in contributing_factors:
                    contributing_factors.append(fid)

            ev = opp.get("evidence", [])
            evidence_summary = "; ".join(ev[:2]) if ev else "Identified enhancement opportunity"
            obs_entry = {
                "service_id": opp.get("service_id", ""),
                "service_name": opp["service_name"],
                "service_category": opp["service_category"],
                "scope": opp["scope"],
                "severity": "critical" if opp.get("has_critical") else ("warning" if opp.get("has_warnings") else "info"),
                "evidence": evidence_summary,
                "rationale": opp["rationale"],
                "next_step": opp["proposed_next_step"],
                "factor_ids": list(opp.get("relevant_factor_ids", [])),
                "affected_urls": list(opp.get("affected_urls", [])),
                "confidence": opp.get("confidence"),
                "prerequisites": list(opp.get("prerequisites", [])),
                "evidence_type": opp.get("evidence_type", "audit_factor"),
                "evidence_source": opp.get("evidence_source", "Canonical Audit"),
                "observation_id": opp.get("observation_id"),
                "evidence_date": opp.get("evidence_date"),
                "limitations": opp.get("limitations"),
                "diagnostic_details": opp.get("diagnostic_details"),
                "ai_observation_details": opp.get("ai_observation_details"),
            }
            observations.append(obs_entry)

            # Collect detailed findings for critical and warning sections
            for cf in opp.get("critical_findings", []):
                if not any(x.get("factor_id") == cf.get("factor_id") for x in all_critical_findings):
                    cf_copy = dict(cf)
                    cf_copy["service_name"] = opp["service_name"]
                    cf_copy["scope"] = opp["scope"]
                    cf_copy["evidence_source"] = opp.get("evidence_source")
                    cf_copy["limitations"] = opp.get("limitations")
                    all_critical_findings.append(cf_copy)

            for wf in opp.get("warning_findings", []):
                if not any(x.get("factor_id") == wf.get("factor_id") for x in all_warning_findings):
                    wf_copy = dict(wf)
                    wf_copy["service_name"] = opp["service_name"]
                    wf_copy["scope"] = opp["scope"]
                    wf_copy["evidence_source"] = opp.get("evidence_source")
                    wf_copy["limitations"] = opp.get("limitations")
                    all_warning_findings.append(wf_copy)

        # Fallback: if opportunities were passed without granular findings, extract from observations
        if not all_critical_findings and not all_warning_findings and observations:
            for obs in observations:
                if obs["scope"] in ("repair", "redesign"):
                    all_critical_findings.append({
                        "service_name": obs["service_name"],
                        "scope": obs["scope"],
                        "title": obs["service_name"],
                        "category": obs["service_category"],
                        "problem": obs["evidence"],
                        "impact": obs["rationale"],
                        "recommendation": obs["next_step"],
                        "evidence_source": obs.get("evidence_source"),
                        "limitations": obs.get("limitations"),
                    })
                else:
                    all_warning_findings.append({
                        "service_name": obs["service_name"],
                        "scope": obs["scope"],
                        "title": obs["service_name"],
                        "category": obs["service_category"],
                        "warning": obs["evidence"],
                        "potential_impact": obs["rationale"],
                        "recommendation": obs["next_step"],
                        "evidence_source": obs.get("evidence_source"),
                        "limitations": obs.get("limitations"),
                    })

        domain = website_url.replace("https://", "").replace("http://", "").strip("/")
        subject = f"Website review and proposal for {domain}"

        has_critical = len(all_critical_findings) > 0
        has_warnings = len(all_warning_findings) > 0

        # Summary statement
        if not observations:
            summary_statement_html = "<p>Our automated audit observed that your core technical foundations are operational. We recommend structured ongoing monitoring to protect your search discoverability:</p>"
            summary_statement_text = "Our automated audit observed that your core technical foundations are operational. We recommend structured ongoing monitoring to protect your search discoverability:\n\n"
        elif has_critical and has_warnings:
            summary_statement_html = f"<p>Based on our verified audit findings, we identified {len(all_critical_findings)} critical issue(s) requiring remediation and {len(all_warning_findings)} warning(s) for optimization:</p>"
            summary_statement_text = f"Based on our verified audit findings, we identified {len(all_critical_findings)} critical issue(s) requiring remediation and {len(all_warning_findings)} warning(s) for optimization:\n\n"
        elif has_critical:
            summary_statement_html = f"<p>Based on our verified audit findings, we identified {len(all_critical_findings)} critical issue(s) requiring remediation to protect your website's performance and search presence:</p>"
            summary_statement_text = f"Based on our verified audit findings, we identified {len(all_critical_findings)} critical issue(s) requiring remediation to protect your website's performance and search presence:\n\n"
        elif has_warnings:
            summary_statement_html = f"<p>Our audit verified that your baseline infrastructure is operational, and identified {len(all_warning_findings)} warning(s) where optimization can improve your visitor experience and search discoverability:</p>"
            summary_statement_text = f"Our audit verified that your baseline infrastructure is operational, and identified {len(all_warning_findings)} warning(s) where optimization can improve your visitor experience and search discoverability:\n\n"
        else:
            summary_statement_html = "<p>Based on our verified audit findings, we identified the following areas for structured website improvements:</p>"
            summary_statement_text = "Based on our verified audit findings, we identified the following areas for structured website improvements:\n\n"

        # ── Critical Issues Section ──────────────────────────────────────────
        crit_html_cards = ""
        crit_text_blocks = ""
        if has_critical:
            for i, item in enumerate(all_critical_findings, 1):
                badge = ""
                if item.get("evidence_source") and item.get("evidence_source") != "Canonical Audit":
                    badge = f"""<span style="display: inline-block; font-size: 11px; background: #fee2e2; color: #991b1b; padding: 2px 6px; border-radius: 4px; margin-left: 6px; font-weight: 500;">Source: {html.escape(item['evidence_source'])}</span>"""
                limit_html = ""
                if item.get("limitations"):
                    limit_html = f"""<p style="margin: 0 0 6px 0; color: #7f1d1d; font-size: 11px; font-style: italic;">Limitation: {html.escape(item['limitations'])}</p>"""

                crit_html_cards += f"""
                <div style="margin-bottom: 14px; padding: 14px; background: #fef2f2; border-left: 4px solid #ef4444; border-radius: 6px;">
                  <p style="margin: 0 0 6px 0; font-weight: 700; color: #1e293b; font-size: 14px;">
                    {i}. {html.escape(item.get('service_name', item.get('title', 'Critical Issue')))} ({html.escape(item.get('scope', 'repair').title())}) {badge}
                  </p>
                  <p style="margin: 0 0 6px 0; color: #991b1b; font-size: 13px;">
                    <strong>Problem:</strong> {html.escape(item.get('problem', ''))}
                  </p>
                  <p style="margin: 0 0 6px 0; color: #475569; font-size: 12px; line-height: 1.5;">
                    <strong>Impact:</strong> {html.escape(item.get('impact', ''))}
                  </p>
                  {limit_html}
                  <p style="margin: 0; color: #b91c1c; font-size: 12px; font-weight: 600;">
                    &rarr; Recommended Action: {html.escape(item.get('recommendation', ''))}
                  </p>
                </div>
                """
                crit_text_blocks += f"{i}. {item.get('service_name', item.get('title', 'Critical Issue'))} [{item.get('scope', 'repair').upper()}]\n"
                crit_text_blocks += f"   Problem: {item.get('problem', '')}\n"
                crit_text_blocks += f"   Impact: {item.get('impact', '')}\n"
                if item.get("evidence_source") and item.get("evidence_source") != "Canonical Audit":
                    crit_text_blocks += f"   Source: {item['evidence_source']}\n"
                if item.get("limitations"):
                    crit_text_blocks += f"   Limitation: {item.get('limitations')}\n"
                crit_text_blocks += f"   Recommended Action: {item.get('recommendation', '')}\n\n"

        # ── Warnings Section ─────────────────────────────────────────────────
        warn_html_cards = ""
        warn_text_blocks = ""
        if has_warnings:
            for i, item in enumerate(all_warning_findings, 1):
                badge = ""
                if item.get("evidence_source") and item.get("evidence_source") != "Canonical Audit":
                    badge = f"""<span style="display: inline-block; font-size: 11px; background: #fef3c7; color: #92400e; padding: 2px 6px; border-radius: 4px; margin-left: 6px; font-weight: 500;">Source: {html.escape(item['evidence_source'])}</span>"""
                limit_html = ""
                if item.get("limitations"):
                    limit_html = f"""<p style="margin: 0 0 6px 0; color: #78350f; font-size: 11px; font-style: italic;">Limitation: {html.escape(item['limitations'])}</p>"""

                warn_html_cards += f"""
                <div style="margin-bottom: 14px; padding: 14px; background: #fffbeb; border-left: 4px solid #f59e0b; border-radius: 6px;">
                  <p style="margin: 0 0 6px 0; font-weight: 700; color: #1e293b; font-size: 14px;">
                    {i}. {html.escape(item.get('service_name', item.get('title', 'Advisory Warning')))} ({html.escape(item.get('scope', 'optimization').title())}) {badge}
                  </p>
                  <p style="margin: 0 0 6px 0; color: #92400e; font-size: 13px;">
                    <strong>Warning:</strong> {html.escape(item.get('warning', ''))}
                  </p>
                  <p style="margin: 0 0 6px 0; color: #475569; font-size: 12px; line-height: 1.5;">
                    <strong>Potential Impact:</strong> {html.escape(item.get('potential_impact', ''))}
                  </p>
                  {limit_html}
                  <p style="margin: 0; color: #d97706; font-size: 12px; font-weight: 600;">
                    &rarr; Recommended Action: {html.escape(item.get('recommendation', ''))}
                  </p>
                </div>
                """
                warn_text_blocks += f"{i}. {item.get('service_name', item.get('title', 'Advisory Warning'))} [{item.get('scope', 'optimization').upper()}]\n"
                warn_text_blocks += f"   Warning: {item.get('warning', '')}\n"
                warn_text_blocks += f"   Potential Impact: {item.get('potential_impact', '')}\n"
                if item.get("evidence_source") and item.get("evidence_source") != "Canonical Audit":
                    warn_text_blocks += f"   Source: {item['evidence_source']}\n"
                if item.get("limitations"):
                    warn_text_blocks += f"   Limitation: {item.get('limitations')}\n"
                warn_text_blocks += f"   Recommended Action: {item.get('recommendation', '')}\n\n"

        elif observations or has_critical:
            # Audit completed successfully with critical issues but zero warnings
            warn_html_cards = """
            <div style="margin-bottom: 14px; padding: 12px 14px; background: #f8fafc; border-left: 4px solid #94a3b8; border-radius: 6px;">
              <p style="margin: 0; color: #64748b; font-size: 13px; font-style: italic;">
                No warnings were identified in this audit.
              </p>
            </div>
            """
            warn_text_blocks = "No warnings were identified in this audit.\n\n"

        # ── Recommendations and Next Steps ───────────────────────────────────
        next_steps_list: List[str] = []
        for cf in all_critical_findings:
            rec = cf.get("recommendation", "")
            if rec and rec not in next_steps_list:
                next_steps_list.append(rec)
        for wf in all_warning_findings:
            rec = wf.get("recommendation", "")
            if rec and rec not in next_steps_list:
                next_steps_list.append(rec)
        if not next_steps_list:
            next_steps_list = ["Periodic health checks and search presence tracking to maintain baseline quality."]

        # Cap next steps to top 4 prioritized actions
        prioritized_steps = next_steps_list[:4]

        rec_html_items = "".join([f"<li style='margin-bottom: 6px;'>{html.escape(s)}</li>" for s in prioritized_steps])
        rec_html_section = f"""
        <div style="margin-top: 18px; margin-bottom: 20px; padding: 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;">
          <p style="margin: 0 0 10px 0; font-weight: 700; color: #1e293b; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
            Recommendations and Next Steps
          </p>
          <ul style="margin: 0; padding-left: 20px; color: #334155; font-size: 13px; line-height: 1.6;">
            {rec_html_items}
          </ul>
        </div>
        """

        rec_text_items = "".join([f"- {s}\n" for s in prioritized_steps])
        rec_text_section = f"Recommendations and Next Steps\n------------------------------\n{rec_text_items}\n"

        # ── Assemble Sections ────────────────────────────────────────────────
        sections_html = ""
        sections_text = ""

        if not observations and not has_critical and not has_warnings:
            # Baseline clean check
            sections_html += """
            <div style="margin-bottom: 16px; padding: 14px; background: #f8fafc; border-left: 4px solid #10b981; border-radius: 6px;">
              <p style="margin: 0 0 6px 0; font-weight: 700; color: #1e293b; font-size: 14px;">
                Baseline Foundation Check (Maintenance)
              </p>
              <p style="margin: 0 0 6px 0; color: #475569; font-size: 13px;">
                <strong>Observed Finding:</strong> Our initial automated scan did not record critical infrastructure defects.
              </p>
              <p style="margin: 0 0 6px 0; color: #64748b; font-size: 12px; line-height: 1.5;">
                Maintaining solid technical foundations and consistent mobile rendering ensures uninterrupted customer discoverability.
              </p>
              <p style="margin: 0; color: #059669; font-size: 12px; font-weight: 600;">
                &rarr; Recommended Action: Periodic health checks and search presence tracking to maintain baseline quality.
              </p>
            </div>
            """
            sections_text += "1. Baseline Foundation Check [MAINTENANCE]\n   Observed: Our initial automated scan did not record critical infrastructure defects.\n   Why it matters: Maintaining solid technical foundations ensures uninterrupted customer discoverability.\n   Recommended Action: Periodic health checks and search presence tracking to maintain baseline quality.\n\n"
            sections_html += """
            <div style="margin-top: 14px; margin-bottom: 14px;">
              <p style="margin: 0 0 6px 0; font-weight: 700; color: #9a3412; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
                Warnings
              </p>
              <p style="margin: 0 0 14px 0; color: #64748b; font-size: 13px; font-style: italic;">
                No warnings were identified in this audit.
              </p>
            </div>
            """
            sections_text += "Warnings\n---------\nNo warnings were identified in this audit.\n\n"
            sections_html += rec_html_section
            sections_text += rec_text_section
        else:
            # Render Critical Issues section if critical issues exist
            if has_critical:
                sections_html += f"""
                <div style="margin-top: 18px; margin-bottom: 8px;">
                  <p style="margin: 0 0 10px 0; font-weight: 700; color: #991b1b; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
                    Critical Issues
                  </p>
                </div>
                {crit_html_cards}
                """
                sections_text += f"Critical Issues\n----------------\n{crit_text_blocks}"

            # Render Warnings section
            sections_html += f"""
            <div style="margin-top: 18px; margin-bottom: 8px;">
              <p style="margin: 0 0 10px 0; font-weight: 700; color: #9a3412; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">
                Warnings
              </p>
            </div>
            {warn_html_cards}
            """
            sections_text += f"Warnings\n---------\n{warn_text_blocks}"

            # Conclude with Recommendations and Next Steps
            sections_html += rec_html_section
            sections_text += rec_text_section

        body_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; max-width: 600px; line-height: 1.6;">
          <p>Hi {html.escape(business_name)} Team,</p>
          <p>
            We recently conducted an objective technical audit of <strong>{html.escape(domain)}</strong> to inspect crawlability, mobile experience, and search presence.
          </p>
          {summary_statement_html}
          {sections_html}
          <p>
            Our team at <strong>{html.escape(sender_agency)}</strong> specializes in implementing these technical repairs and web enhancements cleanly without disruption.
          </p>
          <p>
            Would you be open to a brief 10-minute conversation this week to review the full technical report and discuss how we can implement these improvements for {html.escape(business_name)}?
          </p>
          <p style="margin-top: 24px;">
            Best regards,<br/>
            <strong>The {html.escape(sender_agency)} Technical Team</strong><br/>
            <span style="font-size: 12px; color: #64748b;">Contact: {html.escape(contact_email)}</span>
          </p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 12px 0;"/>
          <p style="font-size: 11px; color: #94a3b8; line-height: 1.4;">
            Note: This proposal is derived from verified automated audit checks. We do not make unsupported claims of guaranteed rankings or revenue increases. All recommendations reflect observable technical findings.
          </p>
        </div>
        """

        body_text = f"""Hi {business_name} Team,\n\nWe recently conducted an objective technical audit of {domain} to inspect crawlability, mobile experience, and search presence.\n\n{summary_statement_text}{sections_text}Our team at {sender_agency} specializes in implementing these technical repairs and web enhancements cleanly without disruption.\n\nWould you be open to a brief 10-minute conversation this week to review the full technical report and discuss how we can implement these improvements for {business_name}?\n\nBest regards,\nThe {sender_agency} Technical Team\nContact: {contact_email}\n\nNote: This proposal is derived from verified automated audit checks. All recommendations reflect observable technical findings."""

        return {
            "business_name": business_name,
            "website_url": website_url,
            "subject": subject,
            "observations": observations,
            "opportunities_count": len(opportunities),
            "selected_opportunities_count": len(observations),
            "contributing_factor_ids": contributing_factors,
            "critical_issues": all_critical_findings,
            "warnings": all_warning_findings,
            "next_steps_summary": prioritized_steps,
            "has_critical_issues": has_critical,
            "has_warnings": has_warnings,
            "body_html": body_html.strip(),
            "body_text": body_text.strip(),
            "requires_human_approval": True,
            "status": "draft_preview",
            "sent": False,
        }
