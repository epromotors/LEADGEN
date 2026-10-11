const HIDDEN_STATUSES = new Set(['DISABLED', 'UNAVAILABLE'])

function textValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function Comparison({ label, rawValue, renderedValues }) {
  const rendered = renderedValues.filter(Boolean)
  if (!rawValue && rendered.length === 0) return null

  return (
    <div style={{
      background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 9,
      padding: '10px 12px', minWidth: 0,
    }}>
      <p style={{ color: '#cbd5e1', fontSize: 11, fontWeight: 800, marginBottom: 7 }}>{label}</p>
      <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, marginBottom: 2, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Raw HTML</p>
      <p style={{ color: rawValue ? '#cbd5e1' : '#64748b', fontSize: 12, lineHeight: 1.45, margin: 0, overflowWrap: 'anywhere' }}>
        {rawValue || 'Not available'}
      </p>
      <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, margin: '9px 0 2px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Rendered browser</p>
      <p style={{ color: rendered.length ? '#dbeafe' : '#64748b', fontSize: 12, lineHeight: 1.45, margin: 0, overflowWrap: 'anywhere' }}>
        {rendered.length ? rendered.join(' | ') : 'Not available'}
      </p>
    </div>
  )
}

function Indicator({ label, value }) {
  const known = value !== null && value !== undefined
  const positive = value === true || (typeof value === 'number' && value > 0)
  const color = !known ? '#64748b' : positive ? '#4ade80' : '#fbbf24'
  const display = !known ? 'Unknown' : typeof value === 'boolean' ? (value ? 'Detected' : 'Not detected') : String(value)

  return (
    <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
      <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</p>
      <p style={{ color, fontSize: 12, fontWeight: 700, margin: 0 }}>{display}</p>
    </div>
  )
}

export default function BrowserEvidence({ evidence, status, auditResults }) {
  const providerStatus = status || evidence?.provider_status
  if (!evidence || HIDDEN_STATUSES.has(providerStatus)) return null

  const titleResult = auditResults?.onpage?.page_title
  const h1Result = auditResults?.onpage?.h1
  const titleDiff = titleResult?.browser_diff
  const h1Diff = h1Result?.browser_diff
  const renderedH1s = (
    h1Diff?.rendered_h1s
    || evidence.js_rendered_headings?.filter((heading) => heading?.level === 'h1').map((heading) => heading.text)
    || evidence.headings?.filter((heading) => heading?.level === 'h1').map((heading) => heading.text)
    || []
  ).map(textValue).filter(Boolean)

  const rawTitle = textValue(titleDiff?.raw_value) || textValue(titleResult?.value) || textValue(titleResult?.detail)
  const renderedTitle = textValue(titleDiff?.rendered_value) || textValue(evidence.js_rendered_title) || textValue(evidence.page_title)
  const rawH1 = textValue(h1Diff?.raw_value) || textValue(h1Result?.value)
  const consoleErrorCount = Array.isArray(evidence.console_errors) ? evidence.console_errors.length : 0
  const failedRequestCount = Array.isArray(evidence.failed_requests) ? evidence.failed_requests.length : 0

  return (
    <details style={{
      background: '#101a2c', border: '1px solid #1e3a5f', borderRadius: 14,
      marginTop: 20, overflow: 'hidden',
    }}>
      <summary style={{
        cursor: 'pointer', padding: '13px 16px', color: '#dbeafe', fontSize: 13,
        fontWeight: 800, listStylePosition: 'inside',
      }}>
        Browser Evidence <span style={{ color: '#60a5fa', fontSize: 10, marginLeft: 7, letterSpacing: '0.06em' }}>{providerStatus || 'RECORDED'}</span>
      </summary>
      <div style={{ borderTop: '1px solid #1e2d44', padding: '14px 16px 16px' }}>
        {evidence.provider_error && (
          <p style={{ color: '#fbbf24', fontSize: 11, lineHeight: 1.45, margin: '0 0 12px' }}>{evidence.provider_error}</p>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
          <Comparison label="Page title" rawValue={rawTitle} renderedValues={[renderedTitle]} />
          <Comparison label="H1 heading" rawValue={rawH1} renderedValues={renderedH1s} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, marginTop: 10 }}>
          <Indicator label="CTA" value={evidence.has_cta} />
          <Indicator label="Navigation" value={evidence.has_nav} />
          <Indicator label="Form" value={evidence.has_form} />
          <Indicator label="Internal links" value={evidence.internal_link_count} />
          <Indicator label="Console errors" value={consoleErrorCount} />
          <Indicator label="Failed requests" value={failedRequestCount} />
        </div>

        {/* Phase 3 WS-B: Lab Performance Metrics (Synthetic / Lab Data) */}
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #1e2d44' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <p style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, margin: 0, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Lab Web Vitals <span style={{ color: '#64748b', fontSize: 10, fontWeight: 500, textTransform: 'none' }}>(Synthetic Lab Data)</span>
            </p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8 }}>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Lab LCP</p>
              <p style={{ color: typeof evidence.lab_lcp_ms === 'number' ? (evidence.lab_lcp_ms <= 2500 ? '#4ade80' : evidence.lab_lcp_ms <= 4000 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {typeof evidence.lab_lcp_ms === 'number' ? `${evidence.lab_lcp_ms} ms` : 'Unavailable'}
              </p>
            </div>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Lab CLS</p>
              <p style={{ color: (evidence.lab_cls !== null && evidence.lab_cls !== undefined) ? (evidence.lab_cls <= 0.1 ? '#4ade80' : evidence.lab_cls <= 0.25 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {(evidence.lab_cls !== null && evidence.lab_cls !== undefined) ? evidence.lab_cls.toFixed(3) : 'Unavailable'}
              </p>
            </div>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Lab TTFB</p>
              <p style={{ color: typeof evidence.lab_ttfb_ms === 'number' ? (evidence.lab_ttfb_ms <= 800 ? '#4ade80' : evidence.lab_ttfb_ms <= 1800 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {typeof evidence.lab_ttfb_ms === 'number' ? `${evidence.lab_ttfb_ms} ms` : 'Unavailable'}
              </p>
            </div>
          </div>
          <p style={{ color: '#64748b', fontSize: 10, margin: '8px 0 0', lineHeight: 1.4 }}>
            Lab measurements captured in headless browser under lab conditions. Not real-user field data (CrUX).
          </p>
        </div>
      </div>
    </details>
  )
}
