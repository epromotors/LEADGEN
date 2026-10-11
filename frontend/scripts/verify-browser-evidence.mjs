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
  const { default: BrowserEvidence } = await vite.ssrLoadModule('/src/components/BrowserEvidence.jsx')
  const render = (props) => renderToStaticMarkup(React.createElement(BrowserEvidence, props))

  const complete = render({
    status: 'SUCCESS',
    evidence: {
      provider_status: 'SUCCESS', page_title: 'Rendered title', has_cta: true,
      has_nav: true, has_form: false, internal_link_count: 4,
      headings: [{ level: 'h1', text: 'Rendered H1' }],
      console_errors: ['[error] example'], failed_requests: ['https://example.test/app.js'],
      lab_lcp_ms: 1250, lab_cls: 0.0, lab_ttfb_ms: 180, lab_metrics_available: true,
    },
    auditResults: {
      onpage: {
        page_title: { value: 'Raw title', browser_diff: { rendered_value: 'Rendered title' } },
        h1: { browser_diff: { rendered_h1s: ['Rendered H1'] } },
      },
    },
  })
  assert.match(complete, /Browser Evidence/)
  assert.match(complete, /Raw title/)
  assert.match(complete, /Rendered H1/)
  assert.match(complete, /Console errors/)
  assert.match(complete, /Failed requests/)
  assert.match(complete, /Lab Web Vitals/)
  assert.match(complete, /1250 ms/)
  assert.match(complete, /0\.000/)
  assert.match(complete, /180 ms/)
  assert.match(complete, /Synthetic Lab Data/)

  const partial = render({
    status: 'PARTIAL',
    evidence: { provider_status: 'PARTIAL', provider_error: 'Budget exceeded', has_cta: false },
    auditResults: {},
  })
  assert.match(partial, /PARTIAL/)
  assert.match(partial, /Budget exceeded/)
  assert.match(partial, /Unknown/)

  assert.equal(render({ status: 'SUCCESS', evidence: null, auditResults: {} }), '')
  assert.equal(render({ status: 'DISABLED', evidence: { provider_status: 'DISABLED' }, auditResults: {} }), '')
  assert.equal(render({ status: 'UNAVAILABLE', evidence: { provider_status: 'UNAVAILABLE' }, auditResults: {} }), '')
} finally {
  await vite.close()
}

console.log('BrowserEvidence SSR scenarios passed: complete, partial, null, disabled, unavailable.')
