import { useState } from 'react'

const HIDDEN_STATUSES = new Set(['DISABLED', 'UNAVAILABLE'])

function textValue(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function getPageLabel(p, idx) {
  if (idx === 0) return 'Homepage'
  const u = p?.requested_url || ''
  try {
    const parsed = new URL(u)
    return parsed.pathname || `Page ${idx + 1}`
  } catch {
    return u || `Page ${idx + 1}`
  }
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

export default function BrowserEvidence({ evidence, status, auditResults, pages }) {
  const [selectedIdx, setSelectedIdx] = useState(0)
  const pageList = Array.isArray(pages) && pages.length > 0 ? pages : null
  const currentEvidence = pageList ? (pageList[selectedIdx] || pageList[0]) : evidence
  const providerStatus = status || currentEvidence?.provider_status
  if (!currentEvidence || HIDDEN_STATUSES.has(providerStatus)) {
    return (
      <div style={{ textAlign: 'center', padding: '36px 20px', color: '#94a3b8' }}>
        <p style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0', marginBottom: 6 }}>
          Browser Evidence Unavailable
        </p>
        <p style={{ fontSize: 12, color: '#64748b', maxWidth: 440, margin: '0 auto', lineHeight: 1.5 }}>
          Headless browser capture was disabled or unavailable for this audit. The canonical 62-factor audit was evaluated using direct HTTP and HTML analysis.
        </p>
      </div>
    )
  }

  const isHomepage = !pageList || selectedIdx === 0
  const titleResult = auditResults?.onpage?.page_title
  const h1Result = auditResults?.onpage?.h1
  const titleDiff = titleResult?.browser_diff
  const h1Diff = h1Result?.browser_diff
  const renderedH1s = (
    (isHomepage && h1Diff?.rendered_h1s)
    || currentEvidence.js_rendered_headings?.filter((heading) => heading?.level === 'h1').map((heading) => heading.text)
    || currentEvidence.headings?.filter((heading) => heading?.level === 'h1').map((heading) => heading.text)
    || []
  ).map(textValue).filter(Boolean)

  const rawTitle = isHomepage ? (textValue(titleDiff?.raw_value) || textValue(titleResult?.value) || textValue(titleResult?.detail)) : null
  const renderedTitle = textValue(isHomepage ? titleDiff?.rendered_value : null) || textValue(currentEvidence.js_rendered_title) || textValue(currentEvidence.page_title)
  const rawH1 = isHomepage ? (textValue(h1Diff?.raw_value) || textValue(h1Result?.value)) : null
  const consoleErrorCount = Array.isArray(currentEvidence.console_errors) ? currentEvidence.console_errors.length : 0
  const failedRequestCount = Array.isArray(currentEvidence.failed_requests) ? currentEvidence.failed_requests.length : 0

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
        {pageList && pageList.length > 1 && (
          <span style={{ color: '#94a3b8', fontSize: 11, fontWeight: 500, marginLeft: 8 }}>
            ({pageList.length} pages captured)
          </span>
        )}
      </summary>
      <div style={{ borderTop: '1px solid #1e2d44', padding: '14px 16px 16px' }}>
        {pageList && pageList.length > 1 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
            {pageList.map((p, idx) => {
              const isSelected = idx === selectedIdx
              const label = getPageLabel(p, idx)
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setSelectedIdx(idx)}
                  style={{
                    background: isSelected ? '#1e3a8a' : '#0b1220',
                    color: isSelected ? '#93c5fd' : '#94a3b8',
                    border: `1px solid ${isSelected ? '#3b82f6' : '#1e2d44'}`,
                    borderRadius: 6,
                    padding: '4px 10px',
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {label}
                  {p.provider_status && p.provider_status !== 'SUCCESS' && (
                    <span style={{ color: '#fbbf24', marginLeft: 4 }}>({p.provider_status})</span>
                  )}
                </button>
              )
            })}
          </div>
        )}
        {currentEvidence.provider_error && (
          <p style={{ color: '#fbbf24', fontSize: 11, lineHeight: 1.45, margin: '0 0 12px' }}>{currentEvidence.provider_error}</p>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
          <Comparison label="Page title" rawValue={rawTitle} renderedValues={[renderedTitle]} />
          <Comparison label="H1 heading" rawValue={rawH1} renderedValues={renderedH1s} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, marginTop: 10 }}>
          <Indicator label="CTA" value={currentEvidence.has_cta} />
          <Indicator label="Navigation" value={currentEvidence.has_nav} />
          <Indicator label="Form" value={currentEvidence.has_form} />
          <Indicator label="Internal links" value={currentEvidence.internal_link_count} />
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
              <p style={{ color: typeof currentEvidence.lab_lcp_ms === 'number' ? (currentEvidence.lab_lcp_ms <= 2500 ? '#4ade80' : currentEvidence.lab_lcp_ms <= 4000 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {typeof currentEvidence.lab_lcp_ms === 'number' ? `${currentEvidence.lab_lcp_ms} ms` : 'Unavailable'}
              </p>
            </div>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Lab CLS</p>
              <p style={{ color: (currentEvidence.lab_cls !== null && currentEvidence.lab_cls !== undefined) ? (currentEvidence.lab_cls <= 0.1 ? '#4ade80' : currentEvidence.lab_cls <= 0.25 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {(currentEvidence.lab_cls !== null && currentEvidence.lab_cls !== undefined) ? currentEvidence.lab_cls.toFixed(3) : 'Unavailable'}
              </p>
            </div>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Lab TTFB</p>
              <p style={{ color: typeof currentEvidence.lab_ttfb_ms === 'number' ? (currentEvidence.lab_ttfb_ms <= 800 ? '#4ade80' : currentEvidence.lab_ttfb_ms <= 1800 ? '#fbbf24' : '#f87171') : '#64748b', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {typeof currentEvidence.lab_ttfb_ms === 'number' ? `${currentEvidence.lab_ttfb_ms} ms` : 'Unavailable'}
              </p>
            </div>
          </div>
          <p style={{ color: '#64748b', fontSize: 10, margin: '8px 0 0', lineHeight: 1.4 }}>
            Lab measurements captured in headless browser under lab conditions. Not real-user field data (CrUX).
          </p>
        </div>

        {/* Domain H: Web Design & Observable Code Health */}
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #1e2d44' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <p style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, margin: 0, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Web Design & Layout Health <span style={{ color: '#64748b', fontSize: 10, fontWeight: 500, textTransform: 'none' }}>(Domain H Diagnostics)</span>
            </p>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
            <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
              <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Horizontal Overflow</p>
              <p style={{ color: currentEvidence.has_horizontal_overflow ? '#f87171' : '#4ade80', fontSize: 12, fontWeight: 700, margin: 0 }}>
                {currentEvidence.has_horizontal_overflow ? `Detected (${currentEvidence.overflow_px || 0}px overflow)` : 'Fit to viewport (No overflow)'}
              </p>
            </div>
            {currentEvidence.design_diagnostics && (
              <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
                <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Design Issues</p>
                <p style={{ color: (currentEvidence.design_diagnostics.total_issues || currentEvidence.design_diagnostics.total_runtime_issues || (currentEvidence.design_diagnostics.issues?.length || 0)) > 0 ? '#fbbf24' : '#4ade80', fontSize: 12, fontWeight: 700, margin: 0 }}>
                  {currentEvidence.design_diagnostics.total_issues || currentEvidence.design_diagnostics.total_runtime_issues || (currentEvidence.design_diagnostics.issues?.length || 0)} issue(s) recorded
                </p>
              </div>
            )}
          </div>
          {Array.isArray(currentEvidence.design_diagnostics?.issues) && currentEvidence.design_diagnostics.issues.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {currentEvidence.design_diagnostics.issues.map((iss, i) => (
                <div key={i} style={{ background: '#070d18', border: '1px solid #1e293b', borderRadius: 6, padding: '6px 10px', fontSize: 11 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                    <span style={{
                      fontSize: 9,
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: 4,
                      background: iss.severity === 'critical' ? '#7f1d1d' : iss.severity === 'high' ? '#831843' : '#334155',
                      color: iss.severity === 'critical' ? '#fca5a5' : iss.severity === 'high' ? '#fbcfe8' : '#cbd5e1',
                      textTransform: 'uppercase',
                    }}>
                      {iss.severity || 'info'}
                    </span>
                    <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{iss.message}</span>
                  </div>
                  {iss.recommendation && (
                    <p style={{ color: '#94a3b8', fontSize: 10, margin: '2px 0 0', lineHeight: 1.35 }}>
                      Recommendation: {iss.recommendation}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

        {/* Advanced Website Performance Diagnostics */}
        {currentEvidence.performance_diagnostics && currentEvidence.performance_diagnostics.available && (
          <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #1e2d44' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <p style={{ color: '#94a3b8', fontSize: 11, fontWeight: 700, margin: 0, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Performance & Resource Diagnostics <span style={{ color: '#60a5fa', fontSize: 10, fontWeight: 500, textTransform: 'none' }}>(Lab Runtime)</span>
              </p>
              <span style={{ color: '#64748b', fontSize: 10 }}>
                Page { (currentEvidence.performance_diagnostics.page_index || 0) + 1 } of { currentEvidence.performance_diagnostics.total_pages_captured || 1 }
              </span>
            </div>

            {/* Quick summary indicators */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
              <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
                <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Resources</p>
                <p style={{ color: '#dbeafe', fontSize: 12, fontWeight: 700, margin: 0 }}>
                  {currentEvidence.performance_diagnostics.resource_summary?.total_requests || 0} requests
                </p>
              </div>

              <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
                <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Observed Transfer</p>
                <p style={{ color: currentEvidence.performance_diagnostics.resource_summary?.has_transfer_size_data ? '#4ade80' : '#94a3b8', fontSize: 12, fontWeight: 700, margin: 0 }}>
                  {currentEvidence.performance_diagnostics.resource_summary?.has_transfer_size_data
                    ? `${currentEvidence.performance_diagnostics.resource_summary.total_transfer_kb} KB`
                    : 'Size unavailable (cross-origin)'}
                </p>
              </div>

              <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
                <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Failures / Errors</p>
                <p style={{
                  color: (currentEvidence.performance_diagnostics.failure_breakdown?.total_failure_events || 0) > 0 ? '#f87171' : '#4ade80',
                  fontSize: 12, fontWeight: 700, margin: 0
                }}>
                  {(currentEvidence.performance_diagnostics.failure_breakdown?.failed_requests_count || 0)} blocked / {(currentEvidence.performance_diagnostics.failure_breakdown?.http_errors_count || 0)} HTTP err
                </p>
              </div>

              <div style={{ background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8, padding: '8px 10px' }}>
                <p style={{ color: '#64748b', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>Render-Blocking</p>
                <p style={{
                  color: (currentEvidence.performance_diagnostics.render_blocking_candidates?.total_candidates || 0) > 0 ? '#fbbf24' : '#4ade80',
                  fontSize: 12, fontWeight: 700, margin: 0
                }}>
                  {currentEvidence.performance_diagnostics.render_blocking_candidates?.total_candidates || 0} candidate(s)
                </p>
              </div>
            </div>

            {/* Detailed collapsible diagnostics breakdown */}
            <details style={{ marginTop: 10, background: '#070d18', border: '1px solid #1e293b', borderRadius: 8, padding: '8px 12px' }}>
              <summary style={{ cursor: 'pointer', color: '#93c5fd', fontSize: 11, fontWeight: 700, userSelect: 'none' }}>
                View Resource & Diagnostics Breakdown
              </summary>

              {/* Resource type distribution */}
              {currentEvidence.performance_diagnostics.resource_summary?.by_type && (
                <div style={{ marginTop: 10 }}>
                  <p style={{ color: '#94a3b8', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', marginBottom: 6 }}>
                    Resource Distribution by Type
                  </p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: 6 }}>
                    {Object.entries(currentEvidence.performance_diagnostics.resource_summary.by_type)
                      .filter(([_, data]) => data.count > 0)
                      .map(([type, data]) => (
                        <div key={type} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '4px 8px' }}>
                          <span style={{ color: '#60a5fa', fontSize: 10, fontWeight: 700, textTransform: 'capitalize' }}>{type}</span>
                          <p style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 600, margin: '2px 0 0' }}>
                            {data.count} {data.has_size_data ? `(${data.transfer_kb} KB)` : ''}
                          </p>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Failure samples */}
              {currentEvidence.performance_diagnostics.failure_breakdown?.samples?.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <p style={{ color: '#f87171', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', marginBottom: 4 }}>
                    Observed Network Failures & HTTP Errors
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {currentEvidence.performance_diagnostics.failure_breakdown.samples.map((s, idx) => (
                      <div key={idx} style={{ background: '#1c1917', border: '1px solid #442727', borderRadius: 4, padding: '4px 8px', fontSize: 10 }}>
                        <span style={{ color: '#fca5a5', fontWeight: 700 }}>
                          [{s.category === 'http_error' ? `HTTP ${s.status}` : 'BLOCKED/FAILED'}]
                        </span>{' '}
                        <span style={{ color: '#cbd5e1', wordBreak: 'break-all' }}>{s.url}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Render-blocking candidates */}
              {currentEvidence.performance_diagnostics.render_blocking_candidates?.total_candidates > 0 && (
                <div style={{ marginTop: 12 }}>
                  <p style={{ color: '#fbbf24', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', marginBottom: 4 }}>
                    Candidate Render-Blocking Resources (Heuristic)
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {[
                      ...(currentEvidence.performance_diagnostics.render_blocking_candidates.stylesheets || []).map(item => ({ ...item, type: 'CSS' })),
                      ...(currentEvidence.performance_diagnostics.render_blocking_candidates.scripts || []).map(item => ({ ...item, type: 'JS' }))
                    ].map((item, idx) => (
                      <div key={idx} style={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 4, padding: '4px 8px', fontSize: 10 }}>
                        <span style={{ color: '#fde047', fontWeight: 700 }}>[{item.type}]</span>{' '}
                        <span style={{ color: '#e2e8f0', wordBreak: 'break-all' }}>{item.url}</span>
                        <p style={{ color: '#a1a1aa', margin: '2px 0 0', fontSize: 9 }}>{item.reason}</p>
                      </div>
                    ))}
                  </div>
                  <p style={{ color: '#71717a', fontSize: 9, fontStyle: 'italic', margin: '4px 0 0' }}>
                    {currentEvidence.performance_diagnostics.render_blocking_candidates.limitation_note}
                  </p>
                </div>
              )}

              {/* Coverage limitation */}
              <p style={{ color: '#64748b', fontSize: 9, margin: '10px 0 0', lineHeight: 1.4 }}>
                {currentEvidence.performance_diagnostics.coverage_note}
              </p>
            </details>
          </div>
        )}

        </div>
      </div>
    </details>
  )
}
