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
  console.log('Testing Email Deliverability Hub & Candidate Badge UI components via Vite SSR...')

  const { default: EmailVerificationAudit } = await vite.ssrLoadModule('/src/components/EmailVerificationAudit.jsx')
  const { default: BulkImportDiscovery } = await vite.ssrLoadModule('/src/components/BulkImportDiscovery.jsx')

  // 1. Verify EmailVerificationAudit SSR render
  console.log('Testing EmailVerificationAudit component...')
  const auditHtml = renderToStaticMarkup(React.createElement(EmailVerificationAudit))

  assert.match(auditHtml, /Total Leads/, 'EmailVerificationAudit must render Total Leads KPI')
  assert.match(auditHtml, /Deliverable/, 'EmailVerificationAudit must render Deliverable KPI')
  assert.match(auditHtml, /Disposable/, 'EmailVerificationAudit must render Disposable KPI')
  assert.match(auditHtml, /Unverified/, 'EmailVerificationAudit must render Unverified KPI')
  assert.match(auditHtml, /Quarantined/, 'EmailVerificationAudit must render Quarantined KPI')
  assert.match(auditHtml, /Active Sendable Leads/, 'EmailVerificationAudit must render Active Sendable Leads tab')
  assert.match(auditHtml, /Pending Verification/, 'EmailVerificationAudit must render Pending Verification tab')
  assert.match(auditHtml, /Demo-Only Eligible/, 'EmailVerificationAudit must render Demo-Only Eligible tab')
  assert.match(auditHtml, /Excluded \/ Quarantined Leads/, 'EmailVerificationAudit must render Quarantined Leads tab')
  assert.match(auditHtml, /Ad-Hoc Single Email Diagnostics/, 'EmailVerificationAudit must render ad-hoc diagnostics section')
  assert.match(auditHtml, /SMTP diagnostics remain permanently disabled by default/, 'EmailVerificationAudit must display permanent disabled-by-default SMTP notice')

  // 2. Verify BulkImportDiscovery SSR render with provenance & candidate badge props
  console.log('Testing BulkImportDiscovery component...')
  const discoveryHtml = renderToStaticMarkup(React.createElement(BulkImportDiscovery, {
    isOpen: true,
    onClose: () => {},
    onImportComplete: () => {},
  }))

  assert.match(discoveryHtml, /Bulk Keyword &amp; Location Import/, 'BulkImportDiscovery must render header')
  assert.match(discoveryHtml, /Keywords/, 'BulkImportDiscovery must render keywords section')
  assert.match(discoveryHtml, /Locations/, 'BulkImportDiscovery must render locations section')

  console.log('ALL EMAIL DELIVERABILITY HUB & BULK DISCOVERY UI COMPONENTS PASSED SSR VERIFICATION SUCCESSFULLY!')
} finally {
  await vite.close()
}
