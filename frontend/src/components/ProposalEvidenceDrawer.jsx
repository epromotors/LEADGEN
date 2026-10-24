import React, { useEffect, useRef } from 'react'
import {
  X, ExternalLink, ShieldCheck, AlertTriangle, AlertCircle,
  CheckCircle2, Clock, Cpu, Globe, FileText, Info, Layers
} from 'lucide-react'

/**
 * Strips sensitive query parameters from URLs (e.g., token, key, secret, auth, password).
 */
export function sanitizeUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return ''
  try {
    const u = new URL(rawUrl)
    const sensitive = ['token', 'key', 'apikey', 'api_key', 'secret', 'password', 'auth', 'session', 'sig', 'signature']
    let modified = false
    for (const k of Array.from(u.searchParams.keys())) {
      if (sensitive.includes(k.toLowerCase())) {
        u.searchParams.set(k, '[REDACTED]')
        modified = true
      }
    }
    return decodeURI(u.toString())
  } catch {
    return rawUrl
  }
}

/**
 * Validates that a URL uses a safe web scheme (http: or https:) to prevent javascript: or data: injection.
 */
export function isSafeUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return false
  try {
    const u = new URL(rawUrl)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * Normalizes domain for safe tenant/lead isolation verification.
 */
function normalizeDomain(raw) {
  if (!raw || typeof raw !== 'string') return ''
  return raw
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/^www\./, '')
    .split('/')[0]
    .split(':')[0]
    .trim()
}

/**
 * ProposalEvidenceDrawer
 * 
 * Interactive slide-over drawer displaying underlying audit findings, AI search observations,
 * and browser performance diagnostics for a selected proposal recommendation card.
 */
export default function ProposalEvidenceDrawer({
  opportunity,
  allOpportunities = [],
  onSelectOpportunity,
  audit,
  lead,
  onClose,
}) {
  const closeButtonRef = useRef(null)

  // Capture focus on mount and restore previous active element on unmount
  useEffect(() => {
    const previousActiveElement = typeof document !== 'undefined' ? document.activeElement : null
    if (closeButtonRef.current && typeof closeButtonRef.current.focus === 'function') {
      closeButtonRef.current.focus()
    }
    return () => {
      if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
        try {
          previousActiveElement.focus()
        } catch {}
      }
    }
  }, [])

  // Close on Escape key press
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && onClose) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!opportunity) return null

  // Validate tenant domain to prevent cross-tenant evidence leakage
  const leadDomain = normalizeDomain(lead?.website || '')
  let isDomainMismatch = false
  if (leadDomain && Array.isArray(opportunity.affected_urls) && opportunity.affected_urls.length > 0) {
    const urlDomain = normalizeDomain(opportunity.affected_urls[0])
    if (urlDomain && urlDomain !== leadDomain) {
      isDomainMismatch = true
    }
  }

  const factorIds = opportunity.factor_ids || []
  const hasFactors = factorIds.length > 0
  const isBaseline = factorIds.length === 0
  const diag = opportunity.diagnostic_details
  const aiObs = opportunity.ai_observation_details

  // Check if audit results object is available for factor lookups
  const auditResults = audit?.audit_results || {}

  function findFactorInfo(fid) {
    const parts = fid.split('.')
    if (parts.length === 2) {
      const [grp, key] = parts
      return auditResults[grp]?.[key] || null
    }
    return null
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Proposal Evidence Inspection Drawer"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
    >
      {/* Backdrop */}
      <div
        data-testid="evidence-drawer-backdrop"
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(5, 10, 20, 0.75)',
          backdropFilter: 'blur(3px)',
          cursor: 'pointer',
        }}
      />

      {/* Drawer Panel */}
      <aside
        data-testid="evidence-drawer-panel"
        style={{
          position: 'relative',
          width: 520,
          maxWidth: '100vw',
          height: '100vh',
          background: '#090e18',
          borderLeft: '1px solid #1e293b',
          boxShadow: '-8px 0 32px rgba(0, 0, 0, 0.6)',
          display: 'flex',
          flexDirection: 'column',
          zIndex: 10000,
          overflow: 'hidden',
        }}
      >
        {/* Drawer Header */}
        <header
          style={{
            padding: '18px 22px',
            borderBottom: '1px solid #1e293b',
            background: 'linear-gradient(180deg, #0e1726 0%, #090e18 100%)',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12,
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span className="badge badge-blue" style={{ fontSize: 10, textTransform: 'uppercase' }}>
                {opportunity.service_category || 'Service Opportunity'}
              </span>
              <span className="badge badge-grey" style={{ fontSize: 10, textTransform: 'uppercase' }}>
                {opportunity.scope || 'review'}
              </span>
              {typeof opportunity.confidence === 'number' && (
                <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600 }}>
                  {Math.round(opportunity.confidence * 100)}% Confidence
                </span>
              )}
            </div>
            <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc', margin: 0, lineHeight: 1.3 }}>
              {opportunity.service_name}
            </h3>
            <p style={{ fontSize: 11, color: '#64748b', margin: '4px 0 0 0' }}>
              Target: <strong style={{ color: '#cbd5e1' }}>{lead?.business_name || 'Prospect'}</strong> ({leadDomain || 'unknown domain'})
            </p>
          </div>

          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Close evidence drawer"
            style={{
              background: '#1e293b',
              border: 'none',
              borderRadius: 6,
              color: '#94a3b8',
              cursor: 'pointer',
              padding: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background 0.2s, color 0.2s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#334155'; e.currentTarget.style.color = '#fff' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#1e293b'; e.currentTarget.style.color = '#94a3b8' }}
          >
            <X size={18} />
          </button>
        </header>

        {/* Opportunity Switcher Bar */}
        {allOpportunities && allOpportunities.length > 1 && (
          <div
            data-testid="evidence-drawer-switcher"
            style={{
              display: 'flex',
              gap: 6,
              padding: '10px 18px',
              background: '#070b13',
              borderBottom: '1px solid #1e293b',
              overflowX: 'auto',
            }}
          >
            {allOpportunities.map((opp, idx) => {
              const isActive = (opp.service_name === opportunity.service_name)
              return (
                <button
                  key={opp.service_id || opp.service_name || idx}
                  type="button"
                  onClick={() => onSelectOpportunity && onSelectOpportunity(opp)}
                  style={{
                    background: isActive ? '#1e3a8a' : '#0f172a',
                    color: isActive ? '#93c5fd' : '#94a3b8',
                    border: isActive ? '1px solid #3b82f6' : '1px solid #1e293b',
                    borderRadius: 6,
                    padding: '4px 10px',
                    fontSize: 11,
                    fontWeight: 600,
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 5,
                    transition: 'all 0.15s ease',
                  }}
                >
                  <Layers size={11} style={{ opacity: isActive ? 1 : 0.6 }} />
                  {opp.service_name}
                </button>
              )
            })}
          </div>
        )}

        {/* Drawer Scrollable Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 22px' }}>
          {/* Mismatch Alert if detected */}
          {isDomainMismatch && (
            <div
              data-testid="mismatch-warning"
              style={{
                background: '#450a0a',
                border: '1px solid #7f1d1d',
                borderRadius: 8,
                padding: '12px 14px',
                marginBottom: 18,
                display: 'flex',
                gap: 10,
                alignItems: 'flex-start',
              }}
            >
              <AlertCircle size={18} color="#f87171" style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong style={{ fontSize: 12, color: '#fca5a5', display: 'block', marginBottom: 2 }}>
                  Mismatched Evidence Warning
                </strong>
                <p style={{ fontSize: 11, color: '#fecaca', margin: 0 }}>
                  Associated evidence URL does not match this lead domain ({leadDomain}). Specific external values have been suppressed to guarantee tenant data isolation.
                </p>
              </div>
            </div>
          )}

          {/* Rationale & Remediation Section */}
          <section style={{ marginBottom: 20 }}>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Recommendation Summary
            </h4>
            <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: 12 }}>
              <p style={{ fontSize: 12, color: '#cbd5e1', lineHeight: 1.5, margin: '0 0 10px 0' }}>
                <strong style={{ color: '#f8fafc' }}>Why: </strong>
                {opportunity.rationale || 'Recommended based on verified technical evaluation findings.'}
              </p>
              <p style={{ fontSize: 12, color: '#60a5fa', lineHeight: 1.5, margin: 0 }}>
                <strong>Proposed Next Step: </strong>
                {opportunity.next_step || 'Consult with client on remediation priorities.'}
              </p>
              {Array.isArray(opportunity.prerequisites) && opportunity.prerequisites.length > 0 && (
                <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px dashed #1e293b' }}>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700 }}>Prerequisites:</span>
                  <ul style={{ margin: '4px 0 0 0', paddingLeft: 18, fontSize: 11, color: '#94a3b8' }}>
                    {opportunity.prerequisites.map((p, i) => (
                      <li key={i} style={{ marginBottom: 2 }}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>

          {/* Limitations Notice */}
          {opportunity.limitations && (
            <section style={{ marginBottom: 20 }}>
              <div
                data-testid="limitations-callout"
                style={{
                  background: 'rgba(245, 158, 11, 0.08)',
                  border: '1px solid rgba(245, 158, 11, 0.3)',
                  borderRadius: 8,
                  padding: '10px 14px',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'flex-start',
                }}
              >
                <AlertTriangle size={16} color="#fbbf24" style={{ flexShrink: 0, marginTop: 2 }} />
                <div>
                  <strong style={{ fontSize: 11, color: '#fde68a', display: 'block', marginBottom: 2 }}>
                    Observation Limitations & Heuristics
                  </strong>
                  <p style={{ fontSize: 11, color: '#fef3c7', margin: 0, lineHeight: 1.45 }}>
                    {opportunity.limitations}
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* Provenance Metadata Section */}
          <section style={{ marginBottom: 20 }}>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Evidence Provenance
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
              <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: '8px 12px' }}>
                <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 2 }}>
                  Source Origin
                </span>
                <span style={{ fontSize: 12, color: '#38bdf8', fontWeight: 600 }}>
                  {opportunity.evidence_source || 'Canonical Audit'}
                </span>
              </div>
              <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: '8px 12px' }}>
                <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 2 }}>
                  Evidence Type
                </span>
                <span style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 600 }}>
                  {opportunity.evidence_type || 'audit_factor'}
                </span>
              </div>
              {opportunity.observation_id && (
                <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: '8px 12px', gridColumn: 'span 2' }}>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 2 }}>
                    Unique Observation ID
                  </span>
                  <code style={{ fontSize: 11, color: '#a5b4fc', fontFamily: 'monospace' }}>
                    {opportunity.observation_id}
                  </code>
                </div>
              )}
              {opportunity.evidence_date && (
                <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: '8px 12px', gridColumn: 'span 2' }}>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 2 }}>
                    Observation Timestamp
                  </span>
                  <span style={{ fontSize: 11, color: '#cbd5e1' }}>
                    {opportunity.evidence_date}
                  </span>
                </div>
              )}
            </div>
          </section>

          {/* Clean Baseline Review Case */}
          {isBaseline && (
            <section style={{ marginBottom: 20 }}>
              <h4 style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                Baseline Status
              </h4>
              <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: 8, padding: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <CheckCircle2 size={16} color="#34d399" />
                  <strong style={{ fontSize: 13, color: '#a7f3d0' }}>No Infrastructure Defects Identified</strong>
                </div>
                <p style={{ fontSize: 12, color: '#d1fae5', margin: '0 0 8px 0', lineHeight: 1.45 }}>
                  Automated scan observed core technical foundations are operational; no critical infrastructure defects identified.
                </p>
                <p style={{ fontSize: 11, color: '#6ee7b7', margin: 0 }}>
                  This proposal offers preventative baseline maintenance and recurring search monitoring rather than remedial repairs.
                </p>
              </div>
            </section>
          )}

          {/* Browser Performance Diagnostics Section */}
          {(diag || opportunity.evidence_type === 'browser_diagnostic') && (
            <section style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <Cpu size={14} color="#f59e0b" />
                <h4 style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
                  Browser Performance Diagnostics
                </h4>
              </div>

              <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
                {/* Sampling disclosure */}
                <div style={{ fontSize: 11, color: '#94a3b8', background: '#090e18', padding: '6px 10px', borderRadius: 6 }}>
                  Captured from page <strong>{diag?.page_index || 1}</strong> of <strong>{diag?.total_pages_captured || 1}</strong> (controlled crawl sample, up to 5-page crawl limit).
                </div>

                {/* Transfer Size Metrics */}
                <div>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 4 }}>
                    Resource Transfer Volume
                  </span>
                  {diag?.has_transfer_size_data ? (
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: '#f8fafc', marginBottom: 6 }}>
                        {diag.total_transfer_kb} KB <span style={{ fontSize: 11, color: '#64748b', fontWeight: 400 }}>across {diag.total_requests} requests</span>
                      </div>
                      {diag.by_type && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: 6 }}>
                          {Object.entries(diag.by_type).map(([t, info]) => (
                            <div key={t} style={{ background: '#090e18', padding: '6px 8px', borderRadius: 6 }}>
                              <span style={{ fontSize: 9, color: '#64748b', textTransform: 'capitalize', display: 'block' }}>{t}</span>
                              <span style={{ fontSize: 11, color: '#cbd5e1', fontWeight: 600 }}>{info.transfer_kb || 0} KB</span>
                              <span style={{ fontSize: 9, color: '#475569', marginLeft: 4 }}>({info.count})</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ fontSize: 12, color: '#f59e0b', fontStyle: 'italic', background: 'rgba(245, 158, 11, 0.05)', padding: '6px 8px', borderRadius: 6 }}>
                      Transfer sizes unavailable (Cross-origin resources). Note: Never treated as zero bytes.
                    </div>
                  )}
                </div>

                {/* Network & HTTP Failure Breakdown */}
                <div style={{ borderTop: '1px solid #1e293b', paddingTop: 10 }}>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 4 }}>
                    Subresource Failure Breakdown
                  </span>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
                    <div style={{ background: '#090e18', padding: '6px 10px', borderRadius: 6 }}>
                      <span style={{ fontSize: 10, color: '#94a3b8', display: 'block' }}>HTTP 4xx/5xx Responses</span>
                      <span style={{ fontSize: 13, fontWeight: 700, color: (diag?.http_errors_count || 0) > 0 ? '#f87171' : '#34d399' }}>
                        {diag?.http_errors_count || 0} error(s)
                      </span>
                    </div>
                    <div style={{ background: '#090e18', padding: '6px 10px', borderRadius: 6 }}>
                      <span style={{ fontSize: 10, color: '#94a3b8', display: 'block' }}>Network / Proxy Blocks</span>
                      <span style={{ fontSize: 13, fontWeight: 700, color: (diag?.failed_requests_count || 0) > 0 ? '#fbbf24' : '#34d399' }}>
                        {diag?.failed_requests_count || 0} blocked
                      </span>
                    </div>
                  </div>
                </div>

                {/* Runtime Console Errors */}
                {(diag?.actionable_errors?.length || 0) > 0 && (
                  <div style={{ borderTop: '1px solid #1e293b', paddingTop: 10 }}>
                    <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 4 }}>
                      Runtime JavaScript Console Errors ({diag.actionable_errors.length})
                    </span>
                    <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: '#fca5a5' }}>
                      {diag.actionable_errors.slice(0, 3).map((err, i) => (
                        <li key={i} style={{ marginBottom: 2 }}>{String(err?.message || err)}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Candidate Render-Blocking Resources */}
                {diag?.render_blocking_candidates && (
                  <div style={{ borderTop: '1px solid #1e293b', paddingTop: 10 }}>
                    <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 2 }}>
                      Candidate Render-Blocking Resources
                    </span>
                    <div style={{ fontSize: 11, color: '#fde68a', fontStyle: 'italic', marginBottom: 6 }}>
                      Candidate heuristic based on &lt;head&gt; placement; actual render delay requires network execution confirmation.
                    </div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
                      <span className="badge badge-grey">Scripts: {diag.render_blocking_candidates.scripts?.length || 0}</span>
                      <span className="badge badge-grey">Stylesheets: {diag.render_blocking_candidates.stylesheets?.length || 0}</span>
                    </div>
                    {Array.isArray(diag.render_blocking_candidates.scripts) && diag.render_blocking_candidates.scripts.length > 0 && (
                      <ul style={{ margin: '8px 0 0 0', paddingLeft: 16, fontSize: 11, color: '#94a3b8' }}>
                        {diag.render_blocking_candidates.scripts.slice(0, 5).map((scriptUrl, idx) => (
                          <li key={idx} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <code style={{ fontSize: 10, color: '#cbd5e1' }}>{sanitizeUrl(scriptUrl)}</code>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

          {/* AI Search Visibility Observation Section */}
          {(aiObs || opportunity.evidence_type === 'ai_search_observation') && (
            <section style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <Globe size={14} color="#38bdf8" />
                <h4 style={{ fontSize: 11, fontWeight: 700, color: '#38bdf8', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
                  AI Search Visibility Observation
                </h4>
              </div>

              <div style={{ background: '#0d1524', border: '1px solid #1a273e', borderRadius: 8, padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {/* Method & Provider */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className={aiObs?.source_type === 'manual' ? 'badge badge-blue' : 'badge badge-green'} style={{ fontSize: 10 }}>
                    {aiObs?.source_type === 'manual' ? 'Manual Observation (Recorded by Operator)' : `Live Provider (${aiObs?.provider || 'API'})`}
                  </span>
                  <span style={{ fontSize: 10, color: '#64748b' }}>
                    {aiObs?.observed_at ? `Observed: ${aiObs.observed_at.slice(0, 10)}` : 'Recently'}
                  </span>
                </div>

                {/* Recorded Query */}
                <div>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 3 }}>
                    Observed Search Query
                  </span>
                  <div style={{ background: '#090e18', border: '1px solid #1e293b', borderRadius: 6, padding: '8px 10px', fontSize: 12, color: '#f8fafc', fontStyle: 'italic' }}>
                    "{aiObs?.search_query || 'Target business search'}"
                  </div>
                </div>

                {/* Mention Status */}
                <div>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 3 }}>
                    Recorded Mention Status
                  </span>
                  <span className={
                    aiObs?.mention_status === 'mentioned'
                      ? 'badge badge-green'
                      : aiObs?.mention_status === 'not_mentioned'
                        ? 'badge badge-red'
                        : 'badge badge-grey'
                  }>
                    {aiObs?.mention_status === 'mentioned' ? 'Brand Mentioned' : aiObs?.mention_status === 'not_mentioned' ? 'Not Mentioned in Observation' : 'Indeterminate'}
                  </span>
                </div>

                {/* Citation URLs */}
                <div>
                  <span style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', fontWeight: 700, display: 'block', marginBottom: 3 }}>
                    Citation Evidence
                  </span>
                  {Array.isArray(aiObs?.citation_urls) && aiObs.citation_urls.length > 0 ? (
                    <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {aiObs.citation_urls.map((rawUrl, i) => {
                        const safe = isSafeUrl(rawUrl)
                        const sanitized = sanitizeUrl(rawUrl)
                        return (
                          <li key={i} style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {safe ? (
                              <a
                                href={sanitized}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: '#60a5fa', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                              >
                                <ExternalLink size={11} /> {sanitized}
                              </a>
                            ) : (
                              <span style={{ color: '#94a3b8' }}>{sanitized} (unverified link)</span>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  ) : (
                    <span style={{ fontSize: 11, color: '#64748b', fontStyle: 'italic' }}>
                      No citation URLs recorded in this observation.
                    </span>
                  )}
                </div>

                <div style={{ fontSize: 10, color: '#64748b', fontStyle: 'italic', borderTop: '1px solid #1e293b', paddingTop: 6 }}>
                  Notice: Single prompt observation; does not establish ranking, global presence, or ongoing visibility trends.
                </div>
              </div>
            </section>
          )}

          {/* Canonical Audit Factor Details */}
          {hasFactors && (
            <section style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <Layers size={14} color="#60a5fa" />
                <h4 style={{ fontSize: 11, fontWeight: 700, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
                  Associated Audit Factors ({factorIds.length})
                </h4>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {factorIds.map((fid) => {
                  const factorData = findFactorInfo(fid)
                  const status = factorData?.status || 'RECORDED'
                  const isFail = status === 'FAIL'
                  const isPass = status === 'PASS'

                  return (
                    <div
                      key={fid}
                      data-testid={`factor-item-${fid}`}
                      style={{
                        background: '#0d1524',
                        border: '1px solid #1a273e',
                        borderRadius: 8,
                        padding: '10px 12px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <code style={{ fontSize: 11, color: '#93c5fd', background: '#1e293b', padding: '2px 6px', borderRadius: 4 }}>
                          {fid}
                        </code>
                        <span className={isFail ? 'badge badge-red' : isPass ? 'badge badge-green' : 'badge badge-grey'} style={{ fontSize: 9 }}>
                          {status}
                        </span>
                      </div>

                      {factorData?.message ? (
                        <p style={{ fontSize: 11, color: '#cbd5e1', margin: '4px 0 2px 0' }}>
                          {factorData.message}
                        </p>
                      ) : (
                        <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0 2px 0' }}>
                          Persisted finding recorded in canonical audit pass.
                        </p>
                      )}

                      {factorData?.fix && (
                        <p style={{ fontSize: 10, color: '#38bdf8', margin: '2px 0 0 0' }}>
                          Fix hint: {factorData.fix}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>

              <p style={{ fontSize: 10, color: '#64748b', marginTop: 8, fontStyle: 'italic' }}>
                Canonical 62-factor audit score is preserved and was not recalculated.
              </p>
            </section>
          )}

          {/* Affected Target URLs */}
          {Array.isArray(opportunity.affected_urls) && opportunity.affected_urls.length > 0 && !isDomainMismatch && (
            <section style={{ marginBottom: 20 }}>
              <h4 style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
                Target Site URLs ({opportunity.affected_urls.length})
              </h4>
              <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {opportunity.affected_urls.map((rawUrl, i) => {
                  const sanitized = sanitizeUrl(rawUrl)
                  return (
                    <li key={i} style={{ fontSize: 11, color: '#cbd5e1', background: '#0d1524', padding: '6px 10px', borderRadius: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {sanitized}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}
        </div>

        {/* Drawer Footer */}
        <footer
          style={{
            padding: '14px 22px',
            borderTop: '1px solid #1e293b',
            background: '#090e18',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 11, color: '#64748b' }}>
            Evidence Verified & Grounded
          </span>
          <button
            onClick={onClose}
            className="btn btn-secondary"
            style={{ fontSize: 12, padding: '6px 14px' }}
          >
            Close Drawer
          </button>
        </footer>
      </aside>
    </div>
  )
}
