import { useState, useEffect } from 'react'
import {
  Search, Globe, ExternalLink, RefreshCw, AlertCircle, CheckCircle2,
  Lock, ArrowUpRight, BarChart3, TrendingUp, Eye, MousePointerClick,
  SlidersHorizontal, ChevronRight, Layers, ShieldCheck, HelpCircle
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getGscStatus,
  getGscAuthUrl,
  getGscProperties,
  getGscPerformance,
} from '../api/client'

/**
 * SearchConsolePanel
 *
 * Optional, read-only Google Search Console (GSC) integration panel.
 * Domain C (Google Search Console Integration) compliant:
 * - Read-only scope: webmasters.readonly
 * - Honest unavailable/unconfigured/disconnected states
 * - Real performance aggregation: Clicks, Impressions, CTR, Average Position
 * - Date range and coverage indicators
 * - Verified property selector
 * - 100% score-neutral: zero effect on canonical 62-factor scoring registry
 */
export default function SearchConsolePanel({ lead }) {
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [loadingData, setLoadingData] = useState(false)
  const [gscStatus, setGscStatus] = useState(null)
  const [properties, setProperties] = useState([])
  const [selectedProperty, setSelectedProperty] = useState('')
  const [days, setDays] = useState(28)
  const [performanceData, setPerformanceData] = useState(null)
  const [activeView, setActiveView] = useState('queries') // 'queries' | 'pages'
  const [filterText, setFilterText] = useState('')
  const [connectingOAuth, setConnectingOAuth] = useState(false)

  // 1. Initial Load: Connection Status & Properties
  useEffect(() => {
    loadGscStatusAndProperties()
  }, [])

  // 2. Auto-fetch performance when property or days change
  useEffect(() => {
    if (selectedProperty && gscStatus?.connected) {
      loadPerformance(selectedProperty, days)
    }
  }, [selectedProperty, days])

  async function loadGscStatusAndProperties() {
    setLoadingStatus(true)
    try {
      const res = await getGscStatus('default')
      const status = res.data
      setGscStatus(status)

      if (status.connected) {
        try {
          const propsRes = await getGscProperties('default')
          if (propsRes.data?.success && propsRes.data?.properties) {
            const propsList = propsRes.data.properties
            setProperties(propsList)

            // Auto-select property matching lead website if found, otherwise first available
            if (propsList.length > 0) {
              const leadDomain = extractCleanDomain(lead?.website)
              const matched = propsList.find(p => {
                const cleanSite = p.site_url.replace(/^sc-domain:/, '').replace(/^https?:\/\//, '').replace(/\/$/, '')
                return cleanSite.toLowerCase() === leadDomain.toLowerCase()
              })
              setSelectedProperty(matched ? matched.site_url : propsList[0].site_url)
            }
          }
        } catch (err) {
          console.warn('Failed to load GSC properties:', err)
        }
      }
    } catch (err) {
      console.warn('Failed to check GSC status:', err)
      setGscStatus({
        connected: false,
        status: 'unconfigured',
        reason: 'Unable to reach Search Console service.',
      })
    } finally {
      setLoadingStatus(false)
    }
  }

  async function loadPerformance(siteUrl, selectedDays) {
    if (!siteUrl) return
    setLoadingData(true)
    try {
      const res = await getGscPerformance(siteUrl, 'default', selectedDays)
      setPerformanceData(res.data)
      if (!res.data.connected && res.data.reason) {
        toast.error(res.data.reason)
      }
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to fetch search performance metrics'
      toast.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      setPerformanceData({
        connected: false,
        status: 'api_error',
        reason: detail,
        summary: null,
        rows: [],
      })
    } finally {
      setLoadingData(false)
    }
  }

  async function handleConnectOAuth() {
    setConnectingOAuth(true)
    try {
      const res = await getGscAuthUrl('default')
      if (res.data?.authorization_url) {
        // Open OAuth consent window in popup or redirect
        window.open(res.data.authorization_url, '_blank', 'width=600,height=700')
        toast.success('Google authorization window opened. Complete consent to authorize.')
      } else {
        toast.error(res.data?.message || 'GSC OAuth credentials are not configured on the server.')
      }
    } catch (err) {
      toast.error('Failed to initiate Google Search Console authorization.')
    } finally {
      setConnectingOAuth(false)
    }
  }

  function extractCleanDomain(url) {
    if (!url) return ''
    try {
      const u = url.startsWith('http') ? url : `https://${url}`
      return new URL(u).hostname.replace(/^www\./, '')
    } catch {
      return url.replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]
    }
  }

  // Filter queries or pages
  const rows = performanceData?.rows || []
  const filteredRows = rows.filter(r => {
    if (!filterText) return true
    const term = filterText.toLowerCase()
    if (activeView === 'queries') {
      return (r.query || '').toLowerCase().includes(term)
    }
    return (r.page || '').toLowerCase().includes(term)
  })

  // Group pages if viewing pages
  const pageMap = new Map()
  if (activeView === 'pages') {
    rows.forEach(r => {
      const pageUrl = r.page || 'Home / Root'
      if (!pageMap.has(pageUrl)) {
        pageMap.set(pageUrl, {
          page: pageUrl,
          clicks: 0,
          impressions: 0,
          weightedPos: 0,
        })
      }
      const entry = pageMap.get(pageUrl)
      entry.clicks += r.clicks || 0
      entry.impressions += r.impressions || 0
      entry.weightedPos += (r.position || 0) * (r.impressions || 0)
    })
  }

  const aggregatedPages = Array.from(pageMap.values())
    .map(p => ({
      page: p.page,
      clicks: p.clicks,
      impressions: p.impressions,
      ctr: p.impressions > 0 ? p.clicks / p.impressions : 0,
      position: p.impressions > 0 ? p.weightedPos / p.impressions : 0,
    }))
    .filter(p => !filterText || p.page.toLowerCase().includes(filterText.toLowerCase()))
    .sort((a, b) => b.clicks - a.clicks)

  return (
    <div className="card-elevated p-6 space-y-6" style={{ background: '#070b13', borderColor: '#1e293b' }}>
      {/* ── Top Header Bar ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            background: 'rgba(56, 189, 248, 0.1)', border: '1px solid rgba(56, 189, 248, 0.25)',
            borderRadius: 8, padding: 8, display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}>
            <Search size={20} style={{ color: '#38bdf8' }} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h3 style={{ fontSize: 16, fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                Google Search Console Analytics
              </h3>
              <span className={`badge ${gscStatus?.connected ? 'badge-green' : 'badge-grey'}`} style={{ fontSize: 10 }}>
                {gscStatus?.connected ? 'OAuth Connected' : (gscStatus?.status || 'Disconnected').toUpperCase()}
              </span>
              <span className="badge badge-purple" style={{ fontSize: 9 }}>
                Score-Neutral (0 Impact)
              </span>
            </div>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              Real organic query clicks, impressions, CTR and keyword ranking positions
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={() => {
              loadGscStatusAndProperties()
              if (selectedProperty) loadPerformance(selectedProperty, days)
            }}
            disabled={loadingStatus || loadingData}
            className="btn btn-secondary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', fontSize: 12 }}
            title="Refresh Search Console data"
          >
            <RefreshCw size={13} className={(loadingStatus || loadingData) ? 'spin' : ''} />
            Refresh
          </button>

          {!gscStatus?.connected && (
            <button
              onClick={handleConnectOAuth}
              disabled={connectingOAuth}
              className="btn btn-primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 14px', fontSize: 12, fontWeight: 700 }}
            >
              <ExternalLink size={13} />
              {connectingOAuth ? 'Connecting...' : 'Connect Search Console'}
            </button>
          )}
        </div>
      </div>

      {/* ── Status Banner (Unconfigured / Disconnected / Error) ── */}
      {!gscStatus?.connected && (
        <div style={{
          background: gscStatus?.status === 'unconfigured' ? 'rgba(30, 41, 59, 0.4)' : 'rgba(239, 68, 68, 0.08)',
          border: `1px solid ${gscStatus?.status === 'unconfigured' ? '#334155' : 'rgba(239, 68, 68, 0.3)'}`,
          borderRadius: 8,
          padding: '14px 18px',
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
        }}>
          <AlertCircle size={18} style={{ color: gscStatus?.status === 'unconfigured' ? '#94a3b8' : '#f87171', flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: 12, lineHeight: 1.5 }}>
            <strong style={{ color: '#f1f5f9', display: 'block', marginBottom: 2 }}>
              {gscStatus?.status === 'unconfigured'
                ? 'Optional Integration: Google Search Console Not Configured'
                : 'Search Console Authorization Required'}
            </strong>
            <span style={{ color: '#94a3b8' }}>
              {gscStatus?.reason || 'Search Console credentials are not active. This integration is strictly optional and does not affect the 62-factor technical SEO audit.'}
            </span>
            {gscStatus?.status === 'unconfigured' && (
              <p style={{ color: '#64748b', fontSize: 11, marginTop: 6, marginBottom: 0 }}>
                To enable organic search click tracking, set <code style={{ color: '#38bdf8' }}>GSC_CLIENT_ID</code> and <code style={{ color: '#38bdf8' }}>GSC_CLIENT_SECRET</code> in the backend <code style={{ color: '#94a3b8' }}>.env</code> file and configure redirect URI <code style={{ color: '#94a3b8' }}>http://localhost:8001/gsc/oauth/callback</code> in your Google Cloud Console.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Connected Workspace Bar: Property Selector & Date Filter ── */}
      {gscStatus?.connected && (
        <div style={{
          background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8,
          padding: '12px 16px', display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', flexWrap: 'wrap', gap: 12
        }}>
          {/* Property Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 260 }}>
            <Globe size={15} style={{ color: '#38bdf8' }} />
            <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8' }}>Property:</span>
            {properties.length > 0 ? (
              <select
                value={selectedProperty}
                onChange={e => setSelectedProperty(e.target.value)}
                style={{
                  background: '#070b13', border: '1px solid #334155', borderRadius: 6,
                  color: '#f8fafc', fontSize: 12, padding: '5px 10px', outline: 'none',
                  cursor: 'pointer', maxWidth: 320, textOverflow: 'ellipsis'
                }}
              >
                {properties.map(p => (
                  <option key={p.site_url} value={p.site_url}>
                    {p.site_url} ({p.permission_level || 'verified'})
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={selectedProperty}
                onChange={e => setSelectedProperty(e.target.value)}
                placeholder="https://example.com/ or sc-domain:example.com"
                style={{
                  background: '#070b13', border: '1px solid #334155', borderRadius: 6,
                  color: '#f8fafc', fontSize: 12, padding: '5px 10px', outline: 'none',
                  flex: 1, maxWidth: 320
                }}
              />
            )}
            <button
              onClick={() => loadPerformance(selectedProperty, days)}
              disabled={loadingData || !selectedProperty}
              className="btn btn-secondary"
              style={{ padding: '5px 10px', fontSize: 11 }}
            >
              Analyze
            </button>
          </div>

          {/* Date Window Presets & Active Coverage */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 11, color: '#64748b', fontWeight: 600 }}>Window:</span>
            {[
              { label: '7 Days', val: 7 },
              { label: '28 Days', val: 28 },
              { label: '90 Days', val: 90 },
            ].map(preset => (
              <button
                key={preset.val}
                onClick={() => setDays(preset.val)}
                style={{
                  background: days === preset.val ? '#1e3a5f' : '#0a101d',
                  border: `1px solid ${days === preset.val ? '#38bdf8' : '#1e293b'}`,
                  color: days === preset.val ? '#38bdf8' : '#94a3b8',
                  borderRadius: 6,
                  padding: '4px 10px',
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                {preset.label}
              </button>
            ))}

            {performanceData?.date_range && (
              <span className="badge badge-grey" style={{ fontSize: 10, marginLeft: 6 }}>
                {performanceData.date_range.start} → {performanceData.date_range.end}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Metric Summary Cards ── */}
      {performanceData?.summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14 }}>
          {/* Total Clicks */}
          <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Total Clicks
              </span>
              <MousePointerClick size={15} style={{ color: '#38bdf8' }} />
            </div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#38bdf8', marginTop: 6, lineHeight: 1 }}>
              {performanceData.summary.total_clicks.toLocaleString()}
            </div>
            <span style={{ fontSize: 11, color: '#64748b', display: 'block', marginTop: 6 }}>
              Organic visitors in last {days} days
            </span>
          </div>

          {/* Total Impressions */}
          <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Total Impressions
              </span>
              <Eye size={15} style={{ color: '#a855f7' }} />
            </div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#c084fc', marginTop: 6, lineHeight: 1 }}>
              {performanceData.summary.total_impressions.toLocaleString()}
            </div>
            <span style={{ fontSize: 11, color: '#64748b', display: 'block', marginTop: 6 }}>
              SERP views in Google results
            </span>
          </div>

          {/* Average CTR */}
          <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Average CTR
              </span>
              <TrendingUp size={15} style={{ color: '#10b981' }} />
            </div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#10b981', marginTop: 6, lineHeight: 1 }}>
              {(performanceData.summary.average_ctr * 100).toFixed(2)}%
            </div>
            <span style={{ fontSize: 11, color: '#64748b', display: 'block', marginTop: 6 }}>
              Click-through percentage
            </span>
          </div>

          {/* Average Position */}
          <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8, padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Average Position
              </span>
              <BarChart3 size={15} style={{ color: '#f59e0b' }} />
            </div>
            <div style={{ fontSize: 26, fontWeight: 900, color: '#fbbf24', marginTop: 6, lineHeight: 1 }}>
              {performanceData.summary.average_position > 0 ? performanceData.summary.average_position.toFixed(1) : '—'}
            </div>
            <span style={{ fontSize: 11, color: '#64748b', display: 'block', marginTop: 6 }}>
              Weighted SERP ranking
            </span>
          </div>
        </div>
      )}

      {/* ── Data Breakdown Section (Queries & Pages) ── */}
      {gscStatus?.connected && (
        <div style={{ background: '#0a101d', border: '1px solid #1e293b', borderRadius: 8, overflow: 'hidden' }}>
          {/* Sub-Tabs & Filter */}
          <div style={{
            padding: '12px 16px', borderBottom: '1px solid #1e293b',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10
          }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setActiveView('queries')}
                style={{
                  background: activeView === 'queries' ? '#1e293b' : 'transparent',
                  border: `1px solid ${activeView === 'queries' ? '#38bdf8' : 'transparent'}`,
                  color: activeView === 'queries' ? '#f8fafc' : '#94a3b8',
                  borderRadius: 6, padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer'
                }}
              >
                Top Queries ({rows.length})
              </button>
              <button
                onClick={() => setActiveView('pages')}
                style={{
                  background: activeView === 'pages' ? '#1e293b' : 'transparent',
                  border: `1px solid ${activeView === 'pages' ? '#38bdf8' : 'transparent'}`,
                  color: activeView === 'pages' ? '#f8fafc' : '#94a3b8',
                  borderRadius: 6, padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer'
                }}
              >
                Top Pages ({aggregatedPages.length})
              </button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="text"
                placeholder={`Filter ${activeView}...`}
                value={filterText}
                onChange={e => setFilterText(e.target.value)}
                style={{
                  background: '#070b13', border: '1px solid #334155', borderRadius: 6,
                  color: '#f8fafc', fontSize: 11, padding: '5px 10px', outline: 'none', width: 180
                }}
              />
            </div>
          </div>

          {/* Table Content */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#070b13', borderBottom: '1px solid #1e293b', color: '#64748b', fontSize: 11, textTransform: 'uppercase' }}>
                  <th style={{ padding: '10px 16px' }}>{activeView === 'queries' ? 'Search Query' : 'Target Page URL'}</th>
                  <th style={{ padding: '10px 14px', textAlign: 'right' }}>Clicks</th>
                  <th style={{ padding: '10px 14px', textAlign: 'right' }}>Impressions</th>
                  <th style={{ padding: '10px 14px', textAlign: 'right' }}>CTR</th>
                  <th style={{ padding: '10px 16px', textAlign: 'right' }}>Position</th>
                </tr>
              </thead>
              <tbody>
                {activeView === 'queries' ? (
                  filteredRows.length > 0 ? (
                    filteredRows.map((r, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #162032' }}>
                        <td style={{ padding: '10px 16px', color: '#f1f5f9', fontWeight: 600 }}>
                          {r.query || '—'}
                          {r.page && (
                            <span style={{ display: 'block', fontSize: 10, color: '#64748b', marginTop: 2 }}>
                              Landing: {r.page}
                            </span>
                          )}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#38bdf8', fontWeight: 700 }}>
                          {r.clicks.toLocaleString()}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#94a3b8' }}>
                          {r.impressions.toLocaleString()}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#10b981', fontWeight: 600 }}>
                          {(r.ctr * 100).toFixed(2)}%
                        </td>
                        <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                          <span className={`badge ${r.position <= 3 ? 'badge-green' : r.position <= 10 ? 'badge-blue' : 'badge-grey'}`} style={{ fontSize: 10 }}>
                            #{r.position.toFixed(1)}
                          </span>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>
                        {loadingData ? 'Loading Search Console metrics...' : 'No queries found matching the selected window or filter.'}
                      </td>
                    </tr>
                  )
                ) : (
                  aggregatedPages.length > 0 ? (
                    aggregatedPages.map((p, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #162032' }}>
                        <td style={{ padding: '10px 16px', color: '#f1f5f9', fontWeight: 600, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.page}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#38bdf8', fontWeight: 700 }}>
                          {p.clicks.toLocaleString()}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#94a3b8' }}>
                          {p.impressions.toLocaleString()}
                        </td>
                        <td style={{ padding: '10px 14px', textAlign: 'right', color: '#10b981', fontWeight: 600 }}>
                          {(p.ctr * 100).toFixed(2)}%
                        </td>
                        <td style={{ padding: '10px 16px', textAlign: 'right' }}>
                          <span className={`badge ${p.position <= 3 ? 'badge-green' : p.position <= 10 ? 'badge-blue' : 'badge-grey'}`} style={{ fontSize: 10 }}>
                            #{p.position.toFixed(1)}
                          </span>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} style={{ padding: '30px', textAlign: 'center', color: '#64748b' }}>
                        {loadingData ? 'Loading Search Console metrics...' : 'No landing pages found for the selected property.'}
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Educational / Score-Neutral Integrity Notice ── */}
      <div style={{
        background: '#090e18', border: '1px solid #1e293b', borderRadius: 8,
        padding: '12px 16px', display: 'flex', alignItems: 'flex-start', gap: 10
      }}>
        <ShieldCheck size={16} style={{ color: '#10b981', flexShrink: 0, marginTop: 2 }} />
        <span style={{ color: '#94a3b8', fontSize: 12, lineHeight: 1.5 }}>
          <strong>Score-Neutral Diagnostic Layer:</strong> Google Search Console integration is an optional live diagnostic tool. Technical SEO audit scoring relies exclusively on reproducible crawl and DOM checks in the canonical 62-factor audit engine. Missing Search Console credentials will never penalize or alter an audit score.
        </span>
      </div>
    </div>
  )
}
