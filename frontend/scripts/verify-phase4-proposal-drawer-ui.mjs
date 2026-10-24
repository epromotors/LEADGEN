/**
 * frontend/scripts/verify-phase4-proposal-drawer-ui.mjs
 *
 * Deterministic SSR verification script for Phase 4 Proposal Evidence Review Drawer.
 * Verifies:
 * 1. Drawer dialog structure, accessibility labels, and close controls
 * 2. Technical SEO factor evidence display with canonical score non-recalculation notice
 * 3. Browser performance diagnostics with unavailable size handling (never zero),
 *    HTTP error vs network block distinction, candidate render-blocking heuristics, and crawl sampling limits
 * 4. AI Search Visibility observations with manual vs live provider labeling, query display,
 *    safe citation link validation, and single-prompt limitation disclaimers
 * 5. Mismatched domain evidence detection and suppression
 * 6. URL query parameter sanitization (redacting tokens, keys, passwords)
 * 7. Dangerous citation scheme rejection (e.g., javascript: URLs rendered as safe text)
 * 8. Clean baseline foundation review state
 */

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
  console.log('Starting Phase 4 Proposal Evidence Drawer SSR Verification...')

  const { default: ProposalEvidenceDrawer, sanitizeUrl, isSafeUrl } = await vite.ssrLoadModule('/src/components/ProposalEvidenceDrawer.jsx')

  // ── 1. Unit Tests for Sanitization & URL Safety ──────────────────────────────
  console.log('Testing URL sanitization and safe scheme validators...')
  const rawSensitiveUrl = 'https://example.com/api/v1?token=supersecret123&key=privateKeyABC&user=john'
  const sanitized = sanitizeUrl(rawSensitiveUrl)
  assert.ok(!sanitized.includes('supersecret123'), 'Sanitized URL must not contain sensitive token')
  assert.ok(!sanitized.includes('privateKeyABC'), 'Sanitized URL must not contain sensitive key')
  assert.ok(sanitized.includes('token=%5BREDACTED%5D') || sanitized.includes('token=[REDACTED]'), 'Sanitized URL must contain redacted marker')

  assert.equal(isSafeUrl('https://example.com/blog'), true, 'HTTPS scheme is safe')
  assert.equal(isSafeUrl('http://example.com/page'), true, 'HTTP scheme is safe')
  assert.equal(isSafeUrl('javascript:alert(1)'), false, 'javascript: scheme must be rejected')
  assert.equal(isSafeUrl('data:text/html,<script>alert(1)</script>'), false, 'data: scheme must be rejected')
  console.log('✓ Sanitization and URL validators passed.')

  // ── 2. Technical SEO Evidence Drawer Test ────────────────────────────────────
  console.log('Testing Technical SEO factor evidence rendering...')
  const lead = { id: 'lead-1', business_name: 'Acme Dental Care', website: 'https://acmedental.example' }
  const auditResults = {
    technical: {
      ssl: { status: 'FAIL', severity: 'CRITICAL', message: 'SSL certificate expired on host.', fix: 'Renew TLS certificate.' },
      sitemap: { status: 'FAIL', severity: 'HIGH', message: 'XML sitemap missing from root.', fix: 'Generate and submit sitemap.xml.' },
    },
  }
  const seoOpportunity = {
    service_id: 'technical_seo_remediation',
    service_name: 'Technical SEO & Crawlability Repair',
    service_category: 'Technical SEO',
    scope: 'repair',
    confidence: 0.92,
    rationale: 'Multiple critical crawlability defects detected during canonical audit.',
    next_step: 'Renew TLS certificate and submit valid sitemap.xml.',
    factor_ids: ['technical.ssl', 'technical.sitemap'],
    affected_urls: ['https://acmedental.example'],
    evidence_type: 'audit_factor',
    evidence_source: 'Canonical Audit',
    evidence_date: '2026-10-23',
    limitations: null,
  }

  const seoHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: seoOpportunity,
      audit: { audit_results: auditResults },
      lead,
      onClose: () => {},
    })
  )

  assert.ok(seoHtml.includes('Technical SEO &amp; Crawlability Repair') || seoHtml.includes('Technical SEO & Crawlability Repair'), 'Renders service name')
  assert.ok(seoHtml.includes('technical.ssl'), 'Renders technical.ssl factor ID')
  assert.ok(seoHtml.includes('SSL certificate expired on host.'), 'Renders factor finding message')
  assert.ok(seoHtml.includes('Renew TLS certificate.'), 'Renders factor fix recommendation')
  assert.ok(seoHtml.includes('Canonical 62-factor audit score is preserved and was not recalculated.'), 'Renders 62-factor score non-recalculation notice')
  assert.ok(seoHtml.includes('aria-label="Proposal Evidence Inspection Drawer"'), 'Accessible role and label present')
  assert.ok(seoHtml.includes('aria-label="Close evidence drawer"'), 'Close button label present')
  console.log('✓ Technical SEO evidence assertions passed.')

  // ── 3. Browser Performance Diagnostics Drawer Test ───────────────────────────
  console.log('Testing Browser Performance Diagnostics evidence rendering...')
  const perfOpportunity = {
    service_id: 'performance_speed_optimization',
    service_name: 'Performance, Speed & Asset Optimization',
    service_category: 'Performance',
    scope: 'optimization',
    confidence: 0.88,
    rationale: 'Observed significant subresource latency and candidate render-blocking assets.',
    next_step: 'Audit synchronous head scripts and compress images.',
    factor_ids: ['performance.response_time', 'performance.render_blocking'],
    affected_urls: ['https://acmedental.example'],
    evidence_type: 'browser_diagnostic',
    evidence_source: 'Browser Performance Diagnostics',
    evidence_date: '2026-10-23T10:00:00Z',
    limitations: 'Observed from captured page 1 of 1 (controlled crawl sample, up to 5-page crawl limit). Candidate render-blocking resources are heuristics based on DOM placement.',
    diagnostic_details: {
      has_transfer_size_data: true,
      total_requests: 28,
      total_transfer_kb: 1850.5,
      by_type: {
        image: { transfer_kb: 1120.0, count: 12 },
        script: { transfer_kb: 450.0, count: 8 },
        stylesheet: { transfer_kb: 180.5, count: 4 },
      },
      http_errors_count: 2,
      http_errors: ['https://acmedental.example/broken-asset.js'],
      failed_requests_count: 1,
      failed_requests: ['https://acmedental.example/blocked-tracker.js'],
      actionable_errors: [{ message: 'Uncaught TypeError: window.analytics is not a function' }],
      render_blocking_candidates: {
        total_candidates: 3,
        scripts: ['https://acmedental.example/heavy-head-bundle.js'],
        stylesheets: ['https://acmedental.example/global-theme.css'],
      },
      page_index: 1,
      total_pages_captured: 1,
      crawl_limit: 5,
    },
  }

  const perfHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: perfOpportunity,
      audit: {},
      lead,
      onClose: () => {},
    })
  )

  assert.ok(perfHtml.includes('1850.5 KB'), 'Renders total transfer size volume')
  assert.ok(perfHtml.includes('2 error(s)'), 'Renders HTTP 4xx/5xx response count')
  assert.ok(perfHtml.includes('1 blocked'), 'Renders network connection / proxy-blocked count')
  assert.ok(perfHtml.includes('Uncaught TypeError: window.analytics is not a function'), 'Renders runtime console error message')
  assert.ok(perfHtml.includes('Candidate heuristic based on &lt;head&gt; placement') || perfHtml.includes('Candidate heuristic based on <head> placement'), 'Renders candidate render-blocking disclaimer')
  assert.ok(perfHtml.includes('Captured from page <strong>1</strong> of <strong>1</strong> (controlled crawl sample, up to 5-page crawl limit).'), 'Renders crawl sampling limit disclosure')
  console.log('✓ Performance diagnostics assertions passed.')

  // ── 3b. Missing Resource Size Honesty (Not Zero Bytes) ────────────────────────
  console.log('Testing missing resource size honesty...')
  const perfNoSizesOpp = {
    ...perfOpportunity,
    diagnostic_details: {
      ...perfOpportunity.diagnostic_details,
      has_transfer_size_data: false,
      total_transfer_kb: null,
    },
  }
  const perfNoSizesHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: perfNoSizesOpp,
      audit: {},
      lead,
      onClose: () => {},
    })
  )
  assert.ok(perfNoSizesHtml.includes('Transfer sizes unavailable (Cross-origin resources). Note: Never treated as zero bytes.'), 'Explicitly flags unavailable sizes without coercing to 0 KB')
  console.log('✓ Missing size honesty passed.')

  // ── 4. AI Search Visibility Observation Drawer Test ──────────────────────────
  console.log('Testing AI Search Visibility observation rendering...')
  const aiSearchOpp = {
    service_id: 'ai_search_visibility_monitoring',
    service_name: 'AI Search Visibility Monitoring & Entity Optimization',
    service_category: 'AI Search Readiness',
    scope: 'monitoring',
    confidence: 0.85,
    rationale: 'Recorded observation on target query did not observe business mention.',
    next_step: 'Establish recurring entity tracking and JSON-LD schema enhancements.',
    factor_ids: ['ai_search.observation'],
    affected_urls: ['https://acmedental.example'],
    evidence_type: 'ai_search_observation',
    evidence_source: 'Manual Observation',
    observation_id: 'obs-ai-9876543210',
    evidence_date: '2026-10-22T14:30:00Z',
    limitations: 'Single prompt observation; does not establish ranking, global presence, or ongoing visibility trends.',
    ai_observation_details: {
      observation_id: 'obs-ai-9876543210',
      search_query: 'best cosmetic dentists downtown',
      observed_at: '2026-10-22T14:30:00Z',
      source_type: 'manual',
      provider: 'Manual Observation',
      mention_status: 'not_mentioned',
      citation_found: true,
      citation_urls: [
        'https://healthgrades.com/dentists/best-cosmetic-downtown',
        'javascript:alert("exploit")', // Malicious scheme to verify safety filter
      ],
      search_engine: 'Perplexity AI',
    },
  }

  const aiHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: aiSearchOpp,
      audit: {},
      lead,
      onClose: () => {},
    })
  )

  assert.ok(aiHtml.includes('obs-ai-9876543210'), 'Renders unique observation ID')
  assert.ok(aiHtml.includes('Manual Observation (Recorded by Operator)'), 'Identifies manual observation source type')
  assert.ok(aiHtml.includes('best cosmetic dentists downtown'), 'Renders exact search query')
  assert.ok(aiHtml.includes('Not Mentioned in Observation'), 'Renders correct negative mention status badge')
  assert.ok(aiHtml.includes('href="https://healthgrades.com/dentists/best-cosmetic-downtown"'), 'Renders safe citation URL as link')
  assert.ok(aiHtml.includes('rel="noopener noreferrer"'), 'Safe external link attributes enforced')
  assert.ok(!aiHtml.includes('href="javascript:alert(&quot;exploit&quot;)"'), 'Dangerous javascript: link was blocked from href')
  assert.ok(aiHtml.includes('Single prompt observation; does not establish ranking, global presence, or ongoing visibility trends.'), 'Renders scope limitation notice')
  console.log('✓ AI Search visibility observations assertions passed.')

  // ── 5. Mismatched Domain Evidence Detection ──────────────────────────────────
  console.log('Testing cross-tenant / domain mismatch detection...')
  const mismatchedOpp = {
    ...seoOpportunity,
    affected_urls: ['https://unrelated-competitor.example/malicious-page'],
  }
  const mismatchHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: mismatchedOpp,
      audit: {},
      lead: { id: 'lead-1', website: 'https://acmedental.example' },
      onClose: () => {},
    })
  )
  assert.ok(mismatchHtml.includes('Mismatched Evidence Warning'), 'Displays tenant mismatch warning')
  assert.ok(mismatchHtml.includes('Associated evidence URL does not match this lead domain'), 'Explains domain mismatch')
  console.log('✓ Tenant mismatch detection passed.')

  // ── 6. Clean Baseline Foundation State ────────────────────────────────────────
  console.log('Testing Clean Baseline Foundation review state...')
  const baselineOpp = {
    service_name: 'Baseline Foundation Review',
    service_category: 'Baseline Maintenance',
    scope: 'maintenance',
    confidence: 0.95,
    factor_ids: [],
    rationale: 'Automated scan observed core technical foundations are operational; no critical infrastructure defects identified.',
    next_step: 'Periodic health checks and recurring visibility tracking to maintain baseline quality.',
    evidence_type: 'audit_factor',
    evidence_source: 'Canonical Audit',
  }
  const baselineHtml = renderToStaticMarkup(
    React.createElement(ProposalEvidenceDrawer, {
      opportunity: baselineOpp,
      audit: {},
      lead,
      onClose: () => {},
    })
  )
  assert.ok(baselineHtml.includes('No Infrastructure Defects Identified'), 'Displays zero defect notice')
  assert.ok(baselineHtml.includes('Automated scan observed core technical foundations are operational'), 'Explains baseline operational health')
  console.log('✓ Clean baseline review state assertions passed.')

  console.log('\n======================================================')
  console.log('ALL PHASE 4 PROPOSAL EVIDENCE DRAWER UI ASSERTIONS PASSED')
  console.log('======================================================')
} finally {
  await vite.close()
}
