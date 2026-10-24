import { useState, useEffect } from 'react'
import {
  Eye, Plus, CheckCircle2, XCircle, HelpCircle, ArrowRightLeft,
  Calendar, Globe, Search, Link2, FileText, Filter, AlertTriangle,
  RefreshCw, Info, ExternalLink, ShieldAlert
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getAiObservations,
  recordAiObservation,
  compareAiObservations,
  getAiSearchCoverage,
} from '../api/client'

export default function AiVisibilityObservationsPanel({ lead }) {
  const [loading, setLoading] = useState(false)
  const [coverage, setCoverage] = useState(null)
  const [observations, setObservations] = useState([])
  const [selectedSource, setSelectedSource] = useState('')
  const [selectedStatus, setSelectedStatus] = useState('')
  const [searchFilter, setSearchFilter] = useState('')

  // Record Form State
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formData, setFormData] = useState({
    query: '',
    engine: 'Google Gemini',
    source_type: 'manual',
    mention_status: 'mentioned',
    citation_urls: '',
    evidence_snippet: '',
    notes: '',
    observed_at: new Date().toISOString().slice(0, 10),
  })

  // Comparison State
  const [comparing, setComparing] = useState(false)
  const [comparisonResult, setComparisonResult] = useState(null)
  const [baseObsId, setBaseObsId] = useState('')
  const [targetObsId, setTargetObsId] = useState('')

  useEffect(() => {
    loadData()
  }, [lead?.id, lead?.website])

  async function loadData() {
    setLoading(true)
    try {
      const cleanDomain = extractDomain(lead?.website)
      const [covRes, obsRes] = await Promise.all([
        getAiSearchCoverage({ domain: cleanDomain, lead_id: lead?.id }),
        getAiObservations({ domain: cleanDomain, limit: 100 }),
      ])
      setCoverage(covRes.data)
      setObservations(obsRes.data?.observations || [])
    } catch (err) {
      console.warn('Failed to load AI visibility observations:', err)
    } finally {
      setLoading(false)
    }
  }

  function extractDomain(url) {
    if (!url) return ''
    try {
      const u = url.startsWith('http') ? url : `https://${url}`
      return new URL(u).hostname.replace(/^www\./, '')
    } catch {
      return url.replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]
    }
  }

  async function handleRecordSubmit(e) {
    e.preventDefault()
    if (!formData.query.trim()) {
      toast.error('Search query is required.')
      return
    }

    const cleanDomain = extractDomain(lead?.website)
    if (!cleanDomain) {
      toast.error('Target domain is required.')
      return
    }

    // Parse citation URLs from newlines or commas
    const rawCitations = formData.citation_urls
      .split(/[\n,]/)
      .map(u => u.trim())
      .filter(Boolean)

    setSubmitting(true)
    try {
      await recordAiObservation({
        lead_id: lead?.id,
        domain: cleanDomain,
        brand_name: lead?.business_name,
        query: formData.query.trim(),
        engine: formData.engine,
        source_type: formData.source_type,
        provider: formData.source_type === 'manual' ? 'Manual Observation' : formData.engine,
        mention_status: formData.mention_status,
        citation_urls: rawCitations,
        evidence_snippet: formData.evidence_snippet.trim() || undefined,
        notes: formData.notes.trim() || undefined,
        observed_at: new Date(formData.observed_at).toISOString(),
      })
      toast.success('AI visibility observation recorded.')
      setFormData({
        query: '',
        engine: 'Google Gemini',
        source_type: 'manual',
        mention_status: 'mentioned',
        citation_urls: '',
        evidence_snippet: '',
        notes: '',
        observed_at: new Date().toISOString().slice(0, 10),
      })
      setShowForm(false)
      loadData()
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to record observation'
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRunComparison(baseId, targetId) {
    if (!baseId || !targetId) return
    setComparing(true)
    try {
      const res = await compareAiObservations(baseId, targetId)
      setComparisonResult(res.data)
    } catch (err) {
      const msg = err.response?.data?.detail || 'Comparison failed'
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setComparing(false)
    }
  }

  // Filtered observations
  const filtered = observations.filter(obs => {
    if (selectedSource && obs.source_type !== selectedSource) return false
    if (selectedStatus && obs.mention_status !== selectedStatus) return false
    if (searchFilter) {
      const term = searchFilter.toLowerCase()
      const q = (obs.search_query || '').toLowerCase()
      const eng = (obs.engine || '').toLowerCase()
      if (!q.includes(term) && !eng.includes(term)) return false
    }
    return true
  })

  return (
    <div style={{ marginTop: 24 }} className="space-y-6">
      {/* ── Status & Coverage Bar ── */}
      <div style={{
        background: '#070b13', border: '1px solid #1e293b', borderRadius: 10,
        padding: '16px 20px', display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', flexWrap: 'wrap', gap: 16
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.25)',
            borderRadius: 8, padding: 8, display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}>
            <Eye size={20} style={{ color: '#10b981' }} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h4 style={{ fontSize: 15, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                Dated AI Visibility Records
              </h4>
              <span className="badge badge-purple" style={{ fontSize: 9 }}>
                Score-Neutral Observation
              </span>
            </div>
            <p style={{ fontSize: 12, color: '#64748b', margin: '2px 0 0' }}>
              Historical observation ledger separating verified manual records from provider-backed tracking.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Coverage Range</div>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8' }}>
              {coverage?.earliest_date && coverage?.latest_date
                ? `${coverage.earliest_date.slice(0, 10)} → ${coverage.latest_date.slice(0, 10)}`
                : 'No observations recorded'}
            </div>
          </div>

          <div style={{ borderLeft: '1px solid #1e293b', height: 28 }} />

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Records Ledger</div>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#38bdf8' }}>
              {coverage?.total_observations || 0} Total ({coverage?.manual_count || 0} Manual, {coverage?.provider_count || 0} Live API)
            </div>
          </div>

          <button
            onClick={() => setShowForm(!showForm)}
            className="btn btn-primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 14px', fontSize: 12, fontWeight: 700 }}
          >
            <Plus size={14} />
            {showForm ? 'Close Form' : 'Record Observation'}
          </button>
        </div>
      </div>

      {/* ── Record Observation Form (Collapsible) ── */}
      {showForm && (
        <form onSubmit={handleRecordSubmit} style={{
          background: '#0d1527', border: '1px solid #1e3a5f', borderRadius: 10,
          padding: 20, display: 'flex', flexDirection: 'column', gap: 16
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h5 style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileText size={16} style={{ color: '#38bdf8' }} /> Record Dated Observation for {lead?.business_name || 'Site'}
            </h5>
            <span style={{ fontSize: 11, color: '#94a3b8' }}>
              Target: <code style={{ color: '#38bdf8' }}>{extractDomain(lead?.website)}</code>
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Search Engine / Source
              </label>
              <select
                value={formData.engine}
                onChange={e => setFormData({ ...formData, engine: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '6px 10px', background: '#070b13' }}
              >
                <option value="Google Gemini">Google Gemini Search</option>
                <option value="ChatGPT (Search)">ChatGPT (Web Search)</option>
                <option value="Perplexity AI">Perplexity AI</option>
                <option value="Claude (Artifacts/Web)">Claude Web Search</option>
                <option value="Microsoft Copilot">Microsoft Copilot</option>
                <option value="Other">Other / Human Review</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Source Category
              </label>
              <select
                value={formData.source_type}
                onChange={e => setFormData({ ...formData, source_type: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '6px 10px', background: '#070b13' }}
              >
                <option value="manual">Manual Entry (Human Observation)</option>
                <option value="structured_import">Structured File Import</option>
                <option value="provider_api">Authorized Provider API</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Mention Status
              </label>
              <select
                value={formData.mention_status}
                onChange={e => setFormData({ ...formData, mention_status: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '6px 10px', background: '#070b13' }}
              >
                <option value="mentioned">Mentioned / Recommended in Response</option>
                <option value="not_mentioned">Not Mentioned in Response</option>
                <option value="unknown">Unknown / Inconclusive</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Observation Date
              </label>
              <input
                type="date"
                value={formData.observed_at}
                onChange={e => setFormData({ ...formData, observed_at: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '6px 10px', background: '#070b13' }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
              Search Prompt / User Query *
            </label>
            <input
              type="text"
              placeholder="e.g. Best car mechanic and brake repair in Lucknow"
              value={formData.query}
              onChange={e => setFormData({ ...formData, query: e.target.value })}
              className="input-field"
              style={{ width: '100%', fontSize: 13, padding: '8px 12px', background: '#070b13' }}
            />
          </div>

          <div>
            <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
              Observed Citation URLs (Separate by newline or comma)
            </label>
            <textarea
              rows={2}
              placeholder="https://carmedicmotors.in/services&#10;https://carmedicmotors.in/reviews"
              value={formData.citation_urls}
              onChange={e => setFormData({ ...formData, citation_urls: e.target.value })}
              className="input-field"
              style={{ width: '100%', fontSize: 12, padding: '8px 12px', background: '#070b13' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Evidence Snippet (Excerpt from AI Response)
              </label>
              <textarea
                rows={2}
                placeholder="Paste the short quote where the business was recommended..."
                value={formData.evidence_snippet}
                onChange={e => setFormData({ ...formData, evidence_snippet: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '8px 12px', background: '#070b13' }}
              />
            </div>

            <div>
              <label style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', display: 'block', marginBottom: 4 }}>
                Operator Notes
              </label>
              <textarea
                rows={2}
                placeholder="Optional internal review notes or context..."
                value={formData.notes}
                onChange={e => setFormData({ ...formData, notes: e.target.value })}
                className="input-field"
                style={{ width: '100%', fontSize: 12, padding: '8px 12px', background: '#070b13' }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="btn btn-secondary"
              style={{ fontSize: 12, padding: '6px 14px' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="btn btn-primary"
              style={{ fontSize: 12, padding: '6px 18px', fontWeight: 700 }}
            >
              {submitting ? 'Saving Record...' : 'Save Observation'}
            </button>
          </div>
        </form>
      )}

      {/* ── Observations Ledger Table & Controls ── */}
      <div style={{
        background: '#070b13', border: '1px solid #1e293b', borderRadius: 10,
        padding: 20
      }}>
        {/* Table Filters */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: 9, color: '#64748b' }} />
              <input
                type="text"
                placeholder="Filter by query or engine..."
                value={searchFilter}
                onChange={e => setSearchFilter(e.target.value)}
                className="input-field"
                style={{ paddingLeft: 30, fontSize: 12, width: 220, padding: '6px 10px 6px 30px' }}
              />
            </div>

            <select
              value={selectedSource}
              onChange={e => setSelectedSource(e.target.value)}
              className="input-field"
              style={{ fontSize: 12, padding: '6px 10px', background: '#0f172a' }}
            >
              <option value="">All Sources</option>
              <option value="manual">Manual Entry Only</option>
              <option value="provider_api">Provider API Only</option>
              <option value="structured_import">Structured Import</option>
            </select>

            <select
              value={selectedStatus}
              onChange={e => setSelectedStatus(e.target.value)}
              className="input-field"
              style={{ fontSize: 12, padding: '6px 10px', background: '#0f172a' }}
            >
              <option value="">All Statuses</option>
              <option value="mentioned">Mentioned</option>
              <option value="not_mentioned">Not Mentioned</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>

          <button
            onClick={loadData}
            disabled={loading}
            className="btn btn-secondary"
            style={{ fontSize: 12, padding: '5px 12px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <RefreshCw size={12} className={loading ? 'spin' : ''} /> Refresh Ledger
          </button>
        </div>

        {/* Comparison Selector Bar */}
        {observations.length >= 2 && (
          <div style={{
            background: 'rgba(56, 189, 248, 0.05)', border: '1px solid rgba(56, 189, 248, 0.2)',
            borderRadius: 8, padding: '10px 14px', marginBottom: 16, display: 'flex',
            alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ArrowRightLeft size={16} style={{ color: '#38bdf8' }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: '#f8fafc' }}>Compare Observations:</span>
              <select
                value={baseObsId}
                onChange={e => setBaseObsId(e.target.value)}
                className="input-field"
                style={{ fontSize: 11, padding: '4px 8px', maxWidth: 220 }}
              >
                <option value="">Select Baseline...</option>
                {observations.map(o => (
                  <option key={o.observation_id} value={o.observation_id}>
                    {o.observed_at.slice(0, 10)} - {o.search_query.slice(0, 30)}...
                  </option>
                ))}
              </select>
              <span style={{ color: '#64748b', fontSize: 11 }}>vs</span>
              <select
                value={targetObsId}
                onChange={e => setTargetObsId(e.target.value)}
                className="input-field"
                style={{ fontSize: 11, padding: '4px 8px', maxWidth: 220 }}
              >
                <option value="">Select Target...</option>
                {observations.map(o => (
                  <option key={o.observation_id} value={o.observation_id}>
                    {o.observed_at.slice(0, 10)} - {o.search_query.slice(0, 30)}...
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={() => handleRunComparison(baseObsId, targetObsId)}
              disabled={comparing || !baseObsId || !targetObsId}
              className="btn btn-secondary"
              style={{ fontSize: 11, padding: '5px 12px', fontWeight: 700 }}
            >
              {comparing ? 'Analyzing...' : 'Run Comparison'}
            </button>
          </div>
        )}

        {/* Comparison Result Modal / Drawer */}
        {comparisonResult && (
          <div style={{
            background: '#0d1527', border: '1px solid #1e3a5f', borderRadius: 8,
            padding: 16, marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 10
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ fontSize: 13, color: '#38bdf8', display: 'flex', alignItems: 'center', gap: 6 }}>
                <ArrowRightLeft size={14} /> Observation Comparison Report
              </strong>
              <button
                onClick={() => setComparisonResult(null)}
                style={{ background: 'transparent', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 14 }}
              >
                ✕
              </button>
            </div>

            {!comparisonResult.comparable ? (
              <div style={{
                background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: 6, padding: '10px 12px', fontSize: 12, color: '#fca5a5'
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>Non-Comparable Observations:</div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {comparisonResult.non_comparable_reasons?.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="space-y-3">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, fontSize: 12 }}>
                  <div style={{ background: '#070b13', padding: 10, borderRadius: 6 }}>
                    <span style={{ color: '#64748b', display: 'block', fontSize: 10 }}>Transition</span>
                    <strong style={{
                      color: comparisonResult.status_transition === 'gained_mention' ? '#10b981' :
                             comparisonResult.status_transition === 'lost_mention' ? '#f87171' : '#f8fafc'
                    }}>
                      {comparisonResult.status_transition?.toUpperCase().replace('_', ' ')}
                    </strong>
                  </div>
                  <div style={{ background: '#070b13', padding: 10, borderRadius: 6 }}>
                    <span style={{ color: '#64748b', display: 'block', fontSize: 10 }}>Days Elapsed</span>
                    <strong style={{ color: '#f8fafc' }}>{comparisonResult.days_between} days</strong>
                  </div>
                  <div style={{ background: '#070b13', padding: 10, borderRadius: 6 }}>
                    <span style={{ color: '#64748b', display: 'block', fontSize: 10 }}>Citations Net Delta</span>
                    <strong style={{
                      color: comparisonResult.citation_changes?.net_citation_delta > 0 ? '#10b981' :
                             comparisonResult.citation_changes?.net_citation_delta < 0 ? '#f87171' : '#94a3b8'
                    }}>
                      {comparisonResult.citation_changes?.net_citation_delta > 0 ? '+' : ''}
                      {comparisonResult.citation_changes?.net_citation_delta} URLs
                    </strong>
                  </div>
                </div>

                {comparisonResult.citation_changes?.added_citations?.length > 0 && (
                  <div style={{ fontSize: 12, color: '#10b981' }}>
                    <strong>+ Gained Citations:</strong>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                      {comparisonResult.citation_changes.added_citations.map((u, i) => (
                        <li key={i}><a href={u} target="_blank" rel="noreferrer" style={{ color: '#38bdf8' }}>{u}</a></li>
                      ))}
                    </ul>
                  </div>
                )}

                {comparisonResult.citation_changes?.removed_citations?.length > 0 && (
                  <div style={{ fontSize: 12, color: '#f87171' }}>
                    <strong>- Removed Citations:</strong>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                      {comparisonResult.citation_changes.removed_citations.map((u, i) => (
                        <li key={i}><span style={{ textDecoration: 'line-through' }}>{u}</span></li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Empty State vs Table */}
        {filtered.length === 0 ? (
          <div style={{
            padding: '36px 20px', textAlign: 'center', background: '#070b13',
            borderRadius: 8, border: '1px dashed #1e293b'
          }}>
            <HelpCircle size={28} style={{ color: '#64748b', margin: '0 auto 10px' }} />
            <h5 style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' }}>
              No Observations Recorded Yet
            </h5>
            <p style={{ fontSize: 12, color: '#64748b', maxWidth: 440, margin: '0 auto 16px' }}>
              No dated AI visibility observations exist for this site. Click "Record Observation" above to manually enter verified search findings or configure an AI provider to track queries automatically.
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="btn btn-secondary"
              style={{ fontSize: 12, padding: '6px 14px' }}
            >
              Record First Observation
            </button>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1e293b', textAlign: 'left', color: '#64748b' }}>
                  <th style={{ padding: '8px 12px' }}>Date</th>
                  <th style={{ padding: '8px 12px' }}>Source & Engine</th>
                  <th style={{ padding: '8px 12px' }}>Search Query</th>
                  <th style={{ padding: '8px 12px' }}>Mention Status</th>
                  <th style={{ padding: '8px 12px' }}>Citations</th>
                  <th style={{ padding: '8px 12px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(obs => (
                  <tr key={obs.observation_id} style={{ borderBottom: '1px solid #0f172a' }}>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap', color: '#94a3b8' }}>
                      {obs.observed_at ? obs.observed_at.slice(0, 10) : '—'}
                    </td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
                      <span className={`badge ${obs.source_type === 'manual' ? 'badge-grey' : 'badge-green'}`} style={{ fontSize: 10, marginRight: 6 }}>
                        {obs.source_type === 'manual' ? 'MANUAL' : 'PROVIDER API'}
                      </span>
                      <strong style={{ color: '#f1f5f9' }}>{obs.engine}</strong>
                    </td>
                    <td style={{ padding: '10px 12px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#e2e8f0' }} title={obs.search_query}>
                      {obs.search_query}
                    </td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
                      <span className={`badge ${
                        obs.mention_status === 'mentioned' ? 'badge-green' :
                        obs.mention_status === 'not_mentioned' ? 'badge-red' : 'badge-grey'
                      }`} style={{ fontSize: 10 }}>
                        {obs.mention_status === 'mentioned' ? 'Mentioned' :
                         obs.mention_status === 'not_mentioned' ? 'Not Mentioned' : 'Unknown'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap', color: '#94a3b8' }}>
                      {obs.citation_urls?.length ? (
                        <span style={{ color: '#38bdf8', fontWeight: 700 }}>
                          {obs.citation_urls.length} URL{obs.citation_urls.length > 1 ? 's' : ''}
                        </span>
                      ) : (
                        '0'
                      )}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                      <button
                        onClick={() => {
                          setBaseObsId(obs.observation_id)
                          toast('Observation selected as baseline for comparison.', { icon: '📍' })
                        }}
                        className="btn btn-secondary"
                        style={{ fontSize: 10, padding: '3px 8px' }}
                      >
                        Set Baseline
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
