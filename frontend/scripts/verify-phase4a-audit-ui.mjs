import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))

const vite = await createServer({
  root,
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
})

try {
  // Load modular audit components
  const { default: UrlIdentityBanner } = await vite.ssrLoadModule('/src/components/audit/UrlIdentityBanner.jsx')
  const { default: AuditOverviewHeader } = await vite.ssrLoadModule('/src/components/audit/AuditOverviewHeader.jsx')
  const { default: CategoryBreakdown } = await vite.ssrLoadModule('/src/components/audit/CategoryBreakdown.jsx')
  const { default: PrioritizedFindingCard } = await vite.ssrLoadModule('/src/components/audit/PrioritizedFindingCard.jsx')
  const { default: CrawlSitemapDiagnostics } = await vite.ssrLoadModule('/src/components/audit/CrawlSitemapDiagnostics.jsx')
  const {
    AuditSkippedState,
    EmptyFindingsState,
    AuditLoadingSkeleton,
    AuditRunningState,
  } = await vite.ssrLoadModule('/src/components/audit/AuditStateView.jsx')

  // 1. Verify UrlIdentityBanner
  console.log('Testing UrlIdentityBanner...')
  const urlBannerDirect = renderToStaticMarkup(
    React.createElement(UrlIdentityBanner, {
      requestedUrl: 'https://example.com',
      finalUrl: 'https://example.com',
      canonicalUrl: 'https://example.com',
      isRedirected: false,
      hasCanonical: true,
      isCanonicalSame: true,
    })
  )
  assert.match(urlBannerDirect, /Requested Target/)
  assert.match(urlBannerDirect, /Final Destination/)
  assert.match(urlBannerDirect, /Declared Canonical/)
  assert.match(urlBannerDirect, /Direct/)
  assert.match(urlBannerDirect, /Self-Canonical/)

  const urlBannerRedirect = renderToStaticMarkup(
    React.createElement(UrlIdentityBanner, {
      requestedUrl: 'http://old.example.com',
      finalUrl: 'https://newdomain.com/landing',
      canonicalUrl: 'https://newdomain.com/primary',
      isRedirected: true,
      hasCanonical: true,
      isCanonicalSame: false,
    })
  )
  assert.match(urlBannerRedirect, /Redirected/)
  assert.match(urlBannerRedirect, /Canonical Alternate/)
  assert.match(urlBannerRedirect, /Cross-Domain Redirect/)

  // 2. Verify AuditOverviewHeader
  console.log('Testing AuditOverviewHeader...')
  const mockLead = { business_name: 'Acme SEO Co', website: 'https://acme.com' }
  const mockAudit = {
    seo_score: 82,
    audit_summary: 'Comprehensive audit completed successfully with strong performance signals.',
    browser_status: 'SUCCESS',
    site_summary: {
      total_pages: 5,
      keyword_analysis: {
        observed_website_terms: [{ keyword: 'plumber', count: 12, density_percent: 2.1 }],
      },
    },
  }
  const mockCounts = { PASS: 45, WARN: 10, FAIL: 7 }
  const overviewHtml = renderToStaticMarkup(
    React.createElement(AuditOverviewHeader, {
      lead: mockLead,
      audit: mockAudit,
      counts: mockCounts,
      criticalCount: 2,
      highCount: 5,
      onRetriggerWithKeywords: () => {},
    })
  )
  assert.match(overviewHtml, /Acme SEO Co/)
  assert.match(overviewHtml, /82/)
  assert.match(overviewHtml, /Good/)
  assert.match(overviewHtml, /Verified Passes/)
  assert.match(overviewHtml, />45</)
  assert.match(overviewHtml, /Warnings/)
  assert.match(overviewHtml, />10</)
  assert.match(overviewHtml, /Confirmed Defects/)
  assert.match(overviewHtml, />7</)
  assert.match(overviewHtml, /2 Critical/)
  assert.match(overviewHtml, /5 High/)
  assert.match(overviewHtml, /Browser Rendered/)

  // 3. Verify CategoryBreakdown
  console.log('Testing CategoryBreakdown...')
  const mockAllChecks = [
    { key: 'ssl_valid', groupId: 'technical', result: { status: 'PASS' } },
    { key: 'has_sitemap', groupId: 'technical', result: { status: 'PASS' } },
    { key: 'missing_h1', groupId: 'onpage', result: { status: 'FAIL' } },
  ]
  const breakdownHtml = renderToStaticMarkup(
    React.createElement(CategoryBreakdown, {
      audit: {
        audit_results: {
          technical: { ssl: { status: 'PASS' }, sitemap: { status: 'PASS' } },
          onpage: { h1: { status: 'FAIL' } },
        },
      },
      allChecks: mockAllChecks,
      selectedCategory: 'ALL',
      onSelectCategory: () => {},
    })
  )
  assert.match(breakdownHtml, /Category Breakdown/)
  assert.match(breakdownHtml, /11-Axis Verified Contract/)
  assert.match(breakdownHtml, /Technical/)
  assert.match(breakdownHtml, /On-Page/)
  assert.match(breakdownHtml, /All 62 Factors/)

  // 4. Verify PrioritizedFindingCard
  console.log('Testing PrioritizedFindingCard...')
  const mockFailCheck = {
    key: 'ssl_valid',
    label: 'SSL / HTTPS Security',
    priority: 'CRITICAL',
    why: 'Google penalises non-HTTPS sites.',
    fix: 'Install Let\'s Encrypt SSL via hosting control panel.',
    result: {
      status: 'FAIL',
      severity: 'CRITICAL',
      message: 'Certificate expired on 2026-10-15.',
      value: 'Expired (x509)',
      confidence: 'HIGH',
    },
  }
  const findingHtml = renderToStaticMarkup(
    React.createElement(PrioritizedFindingCard, {
      check: mockFailCheck,
      audit: mockAudit,
      finalUrl: 'https://acme.com',
    })
  )
  assert.match(findingHtml, /SSL \/ HTTPS Security/)
  assert.match(findingHtml, /CRITICAL/)
  assert.match(findingHtml, /FAIL/)
  assert.match(findingHtml, /Certificate expired on 2026-10-15/)
  assert.match(findingHtml, /Expired \(x509\)/)
  assert.match(findingHtml, /Install Let&#x27;s Encrypt SSL/)
  assert.match(findingHtml, /HIGH Confidence/)

  // 5. Verify CrawlSitemapDiagnostics
  console.log('Testing CrawlSitemapDiagnostics...')
  const mockDiagnosticsAudit = {
    requested_url: 'https://example.com/subpage',
    robots_url: 'https://example.com/robots.txt',
    sitemap_url: 'https://example.com/sitemap.xml',
    has_sitemap: true,
    has_robots: true,
    site_summary: {
      total_pages: 3,
      sitemap_url_count: 50,
      link_discovered_count: 12,
      total_discovered_count: 62,
      crawl_limit_hit: false,
      discovery_explanation: 'Discovered via sitemap and internal anchor links.',
      architecture: {
        architecture: 'single_page',
        confidence: 'HIGH',
        summary: 'Site operates as a single landing page with deep jump navigation.',
        section_count: 6,
        distinct_document_count: 1,
        sections: [
          { id: 'hero', heading: 'Transform your SEO', word_count: 140 },
          { id: 'pricing', heading: 'Transparent Agency Pricing', word_count: 220 },
        ],
        evidence: ['Internal hash-only links found (#hero, #pricing)', 'Canonical points to root'],
      },
    },
    page_audits: [
      {
        url: 'https://example.com/',
        title: 'Home | Acme',
        status_code: 200,
        word_count: 850,
        images: { total_elements: 14, missing_alt_count: 2 },
        links: { internal_outbound: 25, external_outbound: 4 },
        issues: [{ severity: 'WARN', check: 'Missing alt text on 2 images' }],
      },
    ],
  }
  const diagHtml = renderToStaticMarkup(
    React.createElement(CrawlSitemapDiagnostics, {
      audit: mockDiagnosticsAudit,
      requestedUrl: 'https://example.com/subpage',
    })
  )
  assert.match(diagHtml, /Origin Robots\.txt Resolution/)
  assert.match(diagHtml, /https:\/\/example\.com\/robots\.txt/)
  assert.match(diagHtml, /XML Sitemap Discovery &amp; Validation/)
  assert.match(diagHtml, /Verified XML/)
  assert.match(diagHtml, /Site Architecture Classification/)
  assert.match(diagHtml, /single page ARCHITECTURE/i)
  assert.match(diagHtml, /HIGH CONFIDENCE/)
  assert.match(diagHtml, /#hero/)
  assert.match(diagHtml, /#pricing/)
  assert.match(diagHtml, /Audited Pages Breakdown/)
  assert.match(diagHtml, /Home \| Acme/)
  assert.match(diagHtml, /HTTP 200/)

  // 6. Verify AuditStateView components
  console.log('Testing AuditStateView components...')
  const skippedHtml = renderToStaticMarkup(
    React.createElement(AuditSkippedState, {
      audit: {
        error_message: 'SITE_STATUS: Domain parked with registrar',
        audit_summary: 'Target domain is parked and not a real business site.',
      },
    })
  )
  assert.match(skippedHtml, /Audit Skipped \(Site Offline or Unreachable\)/)
  assert.match(skippedHtml, /Domain parked with registrar/)

  const emptyHtml = renderToStaticMarkup(
    React.createElement(EmptyFindingsState, {
      totalChecks: 62,
      onResetFilters: () => {},
    })
  )
  assert.match(emptyHtml, /No Matching Findings/)
  assert.match(emptyHtml, /Reset All Filters/)

  const skeletonHtml = renderToStaticMarkup(React.createElement(AuditLoadingSkeleton))
  assert.match(skeletonHtml, /animate-pulse/)

  const runningHtml = renderToStaticMarkup(
    React.createElement(AuditRunningState, {
      lead: { business_name: 'Acme SEO Co' },
    })
  )
  assert.match(runningHtml, /62-Factor SEO Audit in Progress/)
  assert.match(runningHtml, /Acme SEO Co/)

  console.log('ALL PHASE 4A AUDIT UI COMPONENTS PASSED SSR VERIFICATION SUCCESSFULLY!')
} finally {
  await vite.close()
}
