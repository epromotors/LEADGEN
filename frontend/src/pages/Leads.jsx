import { useCallback, useEffect, useRef, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  Upload, Trash2, Search, RefreshCw, Globe, PlayCircle, Filter,
  CheckCircle2, Pencil, X, Sparkles, Check,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getLeads, uploadLeads, deleteLead, bulkDeleteLeads, deleteAllLeads,
  triggerAudit, triggerAllAudits, triggerSkippedAudits, updateLead, getAudit, getAuditStats,
} from '../api/client'

const STATUS_BADGE = {
  new:      'badge-grey',
  auditing: 'badge-yellow',
  audited:  'badge-blue',
  emailed:  'badge-green',
  replied:  'badge-green',
}


// ── Audit Complete Modal ───────────────────────────────────────────────────────
function AuditDoneModal({ count, onOk }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#1e293b', borderRadius: '16px',
        padding: '40px 48px', textAlign: 'center',
        boxShadow: '0 24px 60px rgba(0,0,0,0.5)',
        border: '1px solid #334155', maxWidth: '380px', width: '90%',
        animation: 'modalPop 0.25s ease',
      }}>
        <div style={{
          width: '72px', height: '72px', borderRadius: '50%',
          background: 'rgba(34,197,94,0.15)', border: '2px solid #22c55e',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 20px',
        }}>
          <CheckCircle2 size={36} color="#22c55e" />
        </div>
        <h2 style={{ color: '#f1f5f9', fontSize: '22px', fontWeight: 700, margin: '0 0 10px' }}>
          Audit Complete!
        </h2>
        <p style={{ color: '#94a3b8', fontSize: '15px', margin: '0 0 28px', lineHeight: 1.6 }}>
          {count === 1
            ? '1 website has been audited successfully.'
            : `${count} websites have been audited successfully.`}
          <br />
          <span style={{ fontSize: '13px', color: '#64748b' }}>
            Click OK to refresh the list.
          </span>
        </p>
        <button
          onClick={onOk}
          style={{
            background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
            color: '#fff', border: 'none', borderRadius: '10px',
            padding: '12px 40px', fontSize: '15px', fontWeight: 700,
            cursor: 'pointer', width: '100%',
            boxShadow: '0 4px 16px rgba(37,99,235,0.4)',
          }}
        >
          OK — Refresh
        </button>
      </div>
      <style>{`
        @keyframes modalPop {
          from { opacity: 0; transform: scale(0.88); }
          to   { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  )
}


// ── Audit Mode Selection Modal ───────────────────────────────────
function AuditModeModal({ stats, onSelect, onClose }) {
  const notAuditedCount  = stats?.new      ?? 0
  const notEmailedCount  = (stats?.new ?? 0) + (stats?.audited ?? 0)
  const forceAllCount    = stats?.total    ?? 0

  const modes = [
    {
      key: 'new_only',
      icon: '🆕',
      title: 'New Sites Only',
      desc: 'Audit leads that have never been audited before.',
      count: notAuditedCount,
      countLabel: 'unaudited leads',
      color: '#3b82f6',
      bg: 'rgba(59,130,246,0.10)',
      border: 'rgba(59,130,246,0.30)',
      disabled: notAuditedCount === 0,
    },
    {
      key: 'not_emailed',
      icon: '📋',
      title: 'All Not Emailed',
      desc: "Re-audit all leads that are new or audited but haven't been emailed yet.",
      count: notEmailedCount,
      countLabel: 'leads to audit',
      color: '#f59e0b',
      bg: 'rgba(245,158,11,0.10)',
      border: 'rgba(245,158,11,0.30)',
      disabled: notEmailedCount === 0,
    },
    {
      key: 'force_all',
      icon: '🔄',
      title: 'Re-audit Everything',
      desc: 'Fresh audit for all leads including already-emailed ones.',
      count: forceAllCount,
      countLabel: 'total leads',
      color: '#ef4444',
      bg: 'rgba(239,68,68,0.08)',
      border: 'rgba(239,68,68,0.25)',
      disabled: forceAllCount === 0,
    },
    {
      key: 'skipped',
      icon: '⚠️',
      title: 'Re-audit Skipped',
      desc: 'Fresh audit for leads that timed out or were wrongly marked as unreachable.',
      count: stats?.skipped ?? 0,
      countLabel: 'skipped leads',
      color: '#f97316',
      bg: 'rgba(249,115,22,0.10)',
      border: 'rgba(249,115,22,0.30)',
      disabled: (stats?.skipped ?? 0) === 0,
    },
  ]

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.72)', backdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '16px',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#1e293b', borderRadius: '18px', width: '100%', maxWidth: '480px',
        boxShadow: '0 32px 80px rgba(0,0,0,0.6)', border: '1px solid #334155',
        animation: 'modalPop 0.22s ease',
      }}>
        <div style={{
          padding: '20px 24px 16px', borderBottom: '1px solid #1e3a5f',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <p style={{ color: '#f1f5f9', fontWeight: 700, fontSize: '16px', margin: 0 }}>
              ⚡ Audit All — Choose Mode
            </p>
            <p style={{ color: '#475569', fontSize: '12px', margin: '3px 0 0' }}>
              Select which leads to audit
            </p>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#475569', padding: '4px', borderRadius: '6px',
            fontSize: '18px', lineHeight: 1,
          }}>✕</button>
        </div>

        <div style={{ padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {modes.map(m => (
            <button
              key={m.key}
              disabled={m.disabled}
              onClick={() => { if (!m.disabled) onSelect(m.key) }}
              style={{
                width: '100%', textAlign: 'left',
                background: m.disabled ? 'rgba(255,255,255,0.02)' : m.bg,
                border: `1px solid ${m.disabled ? '#1e293b' : m.border}`,
                borderRadius: '12px', padding: '14px 16px',
                cursor: m.disabled ? 'not-allowed' : 'pointer',
                opacity: m.disabled ? 0.45 : 1,
                transition: 'all 0.15s',
                display: 'flex', alignItems: 'center', gap: '14px',
              }}
              onMouseEnter={e => { if (!m.disabled) e.currentTarget.style.borderColor = m.color }}
              onMouseLeave={e => { if (!m.disabled) e.currentTarget.style.borderColor = m.border }}
            >
              <span style={{ fontSize: '26px', flexShrink: 0 }}>{m.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ color: m.disabled ? '#475569' : '#f1f5f9', fontWeight: 700, fontSize: '14px' }}>
                    {m.title}
                  </span>
                  <span style={{
                    fontSize: '12px', fontWeight: 700,
                    color: m.disabled ? '#334155' : m.color,
                    background: m.disabled ? 'transparent' : m.bg,
                    border: `1px solid ${m.disabled ? '#1e293b' : m.border}`,
                    borderRadius: '6px', padding: '2px 8px',
                  }}>
                    {m.count.toLocaleString()} {m.countLabel}
                  </span>
                </div>
                <p style={{ color: '#64748b', fontSize: '12px', margin: '4px 0 0', lineHeight: 1.5 }}>
                  {m.desc}
                </p>
              </div>
            </button>
          ))}
        </div>

        <div style={{ padding: '0 24px 20px' }}>
          <p style={{ color: '#334155', fontSize: '11px', textAlign: 'center' }}>
            Audits run in the background — you can continue using the app
          </p>
        </div>
      </div>
      <style>{`
        @keyframes modalPop {
          from { opacity: 0; transform: scale(0.91) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
      `}</style>
    </div>
  )
}


// ── Edit Lead Modal ────────────────────────────────────────────────────────────
function EditLeadModal({ lead, onSaved, onClose }) {
  const [form, setForm] = useState({
    business_name: lead.business_name || '',
    email:         lead.email         || '',
    phone:         lead.phone         || '',
    website:       lead.website       || '',
  })
  const [saving,          setSaving]          = useState(false)
  const [suggestedName,   setSuggestedName]   = useState(null)   // from audit
  const [loadingSuggestion, setLoadingSuggestion] = useState(false)

  // Fetch audit data on mount to get AI name suggestion
  useEffect(() => {
    if (lead.status === 'audited' || lead.status === 'emailed' || lead.status === 'replied') {
      setLoadingSuggestion(true)
      getAudit(lead.id)
        .then(res => {
          const name = res.data?.suggested_name
          if (name && name.trim().toLowerCase() !== form.business_name.trim().toLowerCase()) {
            setSuggestedName(name.trim())
          }
        })
        .catch(() => {})
        .finally(() => setLoadingSuggestion(false))
    }
  }, [lead.id])

  function applySuggestion() {
    setForm(f => ({ ...f, business_name: suggestedName }))
    setSuggestedName(null)
    toast.success('Name updated — click Save to confirm')
  }

  async function handleSave(e) {
    e.preventDefault()
    if (!form.business_name.trim()) { toast.error('Business name is required'); return }
    if (!form.email.trim())         { toast.error('Email is required'); return }
    setSaving(true)
    try {
      await updateLead(lead.id, {
        business_name: form.business_name.trim(),
        email:         form.email.trim(),
        phone:         form.phone.trim() || null,
        website:       form.website.trim(),
      })
      toast.success('Lead updated successfully')
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const inputStyle = {
    width: '100%', background: '#0f172a', border: '1px solid #334155',
    borderRadius: '8px', padding: '9px 12px', color: '#f1f5f9',
    fontSize: '13px', outline: 'none', boxSizing: 'border-box',
    transition: 'border-color 0.15s',
  }
  const labelStyle = {
    display: 'block', fontSize: '11px', fontWeight: 700,
    color: '#64748b', marginBottom: '5px', textTransform: 'uppercase',
    letterSpacing: '0.6px',
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.72)', backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '16px',
    }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#1e293b', borderRadius: '16px', width: '100%', maxWidth: '480px',
        boxShadow: '0 32px 80px rgba(0,0,0,0.6)',
        border: '1px solid #334155', animation: 'modalPop 0.22s ease',
        display: 'flex', flexDirection: 'column',
      }}>

        {/* Header */}
        <div style={{
          padding: '18px 24px', borderBottom: '1px solid #334155',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px', height: '32px', borderRadius: '8px',
              background: 'rgba(37,99,235,0.15)', border: '1px solid rgba(37,99,235,0.3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Pencil size={15} color="#60a5fa" />
            </div>
            <div>
              <p style={{ color: '#f1f5f9', fontWeight: 700, fontSize: '15px', margin: 0 }}>
                Edit Lead
              </p>
              <p style={{ color: '#475569', fontSize: '11px', margin: 0 }}>
                {lead.website?.replace(/^https?:\/\//, '').slice(0, 40)}
              </p>
            </div>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: '#475569', padding: '4px', borderRadius: '6px',
            display: 'flex', alignItems: 'center',
          }}
            onMouseEnter={e => e.currentTarget.style.color = '#94a3b8'}
            onMouseLeave={e => e.currentTarget.style.color = '#475569'}
          >
            <X size={18} />
          </button>
        </div>

        {/* AI Name Suggestion Banner */}
        {loadingSuggestion && (
          <div style={{
            margin: '16px 24px 0',
            background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.25)',
            borderRadius: '10px', padding: '12px 14px',
            display: 'flex', alignItems: 'center', gap: '10px',
          }}>
            <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', borderTopColor: '#a78bfa', flexShrink: 0 }} />
            <span style={{ fontSize: '12px', color: '#a78bfa' }}>
              Checking website metadata for a cleaner business name…
            </span>
          </div>
        )}

        {suggestedName && !loadingSuggestion && (
          <div style={{
            margin: '16px 24px 0',
            background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.35)',
            borderRadius: '10px', padding: '14px 16px',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
              <Sparkles size={16} color="#a78bfa" style={{ flexShrink: 0, marginTop: '1px' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ color: '#c4b5fd', fontSize: '11px', fontWeight: 700, margin: '0 0 4px',
                  textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                  AI-suggested name from website metadata
                </p>
                <p style={{ color: '#f1f5f9', fontSize: '14px', fontWeight: 600, margin: '0 0 10px',
                  wordBreak: 'break-word' }}>
                  "{suggestedName}"
                </p>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={applySuggestion}
                    style={{
                      background: 'rgba(139,92,246,0.25)', border: '1px solid rgba(139,92,246,0.5)',
                      color: '#c4b5fd', borderRadius: '6px', padding: '5px 12px',
                      fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                      display: 'flex', alignItems: 'center', gap: '5px',
                    }}
                  >
                    <Check size={12} /> Use this name
                  </button>
                  <button
                    onClick={() => setSuggestedName(null)}
                    style={{
                      background: 'none', border: '1px solid #334155',
                      color: '#64748b', borderRadius: '6px', padding: '5px 12px',
                      fontSize: '12px', cursor: 'pointer',
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSave} style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>

          {/* Business Name */}
          <div>
            <label style={labelStyle}>Business Name *</label>
            <input
              style={inputStyle}
              value={form.business_name}
              onChange={e => setForm(f => ({ ...f, business_name: e.target.value }))}
              placeholder="Acme Corp"
              required
              autoFocus
              onFocus={e => e.target.style.borderColor = '#3b82f6'}
              onBlur={e => e.target.style.borderColor = '#334155'}
            />
            {form.business_name.includes('|') || form.business_name.includes(' - ') ? (
              <p style={{ fontSize: '11px', color: '#f59e0b', margin: '4px 0 0', display: 'flex', alignItems: 'center', gap: '4px' }}>
                ⚠️ Name appears to contain a tagline — consider trimming it.
              </p>
            ) : null}
          </div>

          {/* Email */}
          <div>
            <label style={labelStyle}>Email *</label>
            <input
              style={inputStyle}
              type="email"
              value={form.email}
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              placeholder="info@business.com"
              required
              onFocus={e => e.target.style.borderColor = '#3b82f6'}
              onBlur={e => e.target.style.borderColor = '#334155'}
            />
          </div>

          {/* Phone + Website in row */}
          <div style={{ display: 'flex', gap: '12px' }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Phone</label>
              <input
                style={inputStyle}
                value={form.phone}
                onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                placeholder="+91 98765 43210"
                onFocus={e => e.target.style.borderColor = '#3b82f6'}
                onBlur={e => e.target.style.borderColor = '#334155'}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Website</label>
              <input
                style={inputStyle}
                value={form.website}
                onChange={e => setForm(f => ({ ...f, website: e.target.value }))}
                placeholder="https://business.com"
                onFocus={e => e.target.style.borderColor = '#3b82f6'}
                onBlur={e => e.target.style.borderColor = '#334155'}
              />
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', gap: '10px', paddingTop: '4px' }}>
            <button type="button" onClick={onClose}
              style={{
                flex: 1, background: 'none', border: '1px solid #334155',
                borderRadius: '8px', padding: '10px', color: '#64748b',
                fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                transition: 'border-color 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = '#475569'}
              onMouseLeave={e => e.currentTarget.style.borderColor = '#334155'}
            >
              Cancel
            </button>
            <button type="submit" disabled={saving}
              style={{
                flex: 2,
                background: saving ? '#1e3a8a' : 'linear-gradient(135deg, #2563eb, #1d4ed8)',
                border: 'none', borderRadius: '8px', padding: '10px',
                color: '#fff', fontSize: '13px', fontWeight: 700,
                cursor: saving ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                boxShadow: '0 4px 14px rgba(37,99,235,0.35)',
                transition: 'opacity 0.15s',
              }}
            >
              {saving
                ? <><span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} /> Saving…</>
                : <><Check size={14} /> Save Changes</>
              }
            </button>
          </div>
        </form>
      </div>

      <style>{`
        @keyframes modalPop {
          from { opacity: 0; transform: scale(0.91) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
      `}</style>
    </div>
  )
}


// ── Main Page ──────────────────────────────────────────────────────────────────
export default function Leads() {
  const [leads, setLeads]             = useState([])
  const [total, setTotal]             = useState(0)
  const [loading, setLoading]         = useState(false)
  const [filter, setFilter]           = useState('')
  const [search, setSearch]           = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [page, setPage]               = useState(1)
  const [selected, setSelected]       = useState(new Set())
  const [editLead, setEditLead]       = useState(null)   // lead object being edited

  // ── Audit polling state ────────────────────────────────────────────────
  // auditProgress   → used by Audit All (count-based, works for 2,500+ leads)
  // pendingAuditIds → used by single/bulk triggers (ID-based, small sets)
  const [pendingAuditIds, setPendingAuditIds]   = useState(new Set())
  const [auditProgress, setAuditProgress]       = useState(null) // { triggered, done_baseline, done_now, mode }
  const [auditDoneModal, setAuditDoneModal]     = useState({ visible: false, count: 0 })
  const [auditModeModal, setAuditModeModal]     = useState(false)
  const [dbStats, setDbStats]                   = useState(null)
  const pollRef       = useRef(null)
  const singlePollRef = useRef(null)
  const searchDebounce = useRef(null)

  const pageSize = 50

  async function fetchLeads(silent = false) {
    if (!silent) setLoading(true)
    try {
      const res = await getLeads({ page, page_size: pageSize, status: filter, q: search })
      setLeads(res.data.items)
      setTotal(res.data.total)
      if (!silent) setSelected(new Set())
    } catch {
      toast.error('Failed to load leads')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  // Debounce search input — fire after 350ms of no typing
  function handleSearchInput(val) {
    setSearchInput(val)
    if (searchDebounce.current) clearTimeout(searchDebounce.current)
    searchDebounce.current = setTimeout(() => {
      setSearch(val)
      setPage(1)
    }, 350)
  }

  function clearSearch() {
    setSearchInput('')
    setSearch('')
    setPage(1)
  }

  useEffect(() => { fetchLeads() }, [page, filter, search])

  // ── Stats-based Audit All polling (uses /audits/stats — immune to batch gaps) ──
  // Done condition: batch_running===false (backend confirms queue empty) AND
  // auditingNow===0 (no lead currently marked 'auditing') AND doneNow > baseline.
  // Checking only auditingNow===0 was firing prematurely between semaphore slots.
  useEffect(() => {
    if (!auditProgress) {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const s     = await getAuditStats()
        const stats = s.data
        setDbStats(stats)
        fetchLeads(true)

        const auditingNow  = stats.auditing     ?? 0
        const doneNow      = (stats.audited ?? 0) + (stats.emailed ?? 0) + (stats.replied ?? 0)
        const batchRunning = stats.batch_running ?? true  // default true = stay polling

        setAuditProgress(prev => {
          if (!prev) return null
          const updated = { ...prev, done_now: doneNow, auditing_now: auditingNow }
          // Only declare done when the backend batch runner has fully exited
          // AND no lead is currently in 'auditing' state.
          if (!batchRunning && auditingNow === 0 && doneNow > (prev.done_baseline ?? 0)) {
            clearInterval(pollRef.current)
            const gained = doneNow - (prev.done_baseline ?? 0)
            setTimeout(() => {
              setAuditDoneModal({ visible: true, count: prev.triggered ?? gained })
            }, 0)
            return null
          }
          return updated
        })
      } catch { /* ignore transient errors */ }
    }, 6000)
    return () => clearInterval(pollRef.current)
  }, [auditProgress])

  // ── ID-based single/bulk audit polling (small sets only) ──────────────────
  useEffect(() => {
    if (pendingAuditIds.size === 0) {
      if (singlePollRef.current) clearInterval(singlePollRef.current)
      return
    }
    singlePollRef.current = setInterval(async () => {
      try {
        const res  = await getLeads({ page: 1, page_size: 200, status: 'auditing' })
        const auditingIds = new Set(res.data.items.map(l => l.id))
        const stillGoing  = new Set([...pendingAuditIds].filter(id => auditingIds.has(id)))
        fetchLeads(true)
        if (stillGoing.size === 0) {
          clearInterval(singlePollRef.current)
          const doneCount = pendingAuditIds.size
          setPendingAuditIds(new Set())
          setAuditDoneModal({ visible: true, count: doneCount })
        } else {
          setPendingAuditIds(stillGoing)
        }
      } catch { }
    }, 10000)
    return () => clearInterval(singlePollRef.current)
  }, [pendingAuditIds])

  function handleAuditDoneOk() {
    setAuditDoneModal({ visible: false, count: 0 })
    fetchLeads()
  }

  // ── Checkbox helpers ───────────────────────────────────────────────────────
  const allSelected  = leads.length > 0 && selected.size === leads.length
  const someSelected = selected.size > 0 && !allSelected

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(leads.map(l => l.id)))
  }
  function toggleOne(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // ── CSV Dropzone ───────────────────────────────────────────────────────────
  const onDrop = useCallback(async (files) => {
    if (!files[0]) return
    const fd = new FormData()
    fd.append('file', files[0])
    const t = toast.loading(`Uploading ${files[0].name}…`)
    try {
      const res = await uploadLeads(fd)
      toast.success(
        `Imported ${res.data.imported} leads. Skipped ${res.data.skipped_duplicates} duplicates.`,
        { id: t }
      )
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload failed', { id: t })
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/csv': ['.csv'] },
    multiple: false,
  })

  // ── Actions ────────────────────────────────────────────────────────────────
  async function handleDelete(id) {
    if (!confirm('Delete this lead and all its data?')) return
    try {
      await deleteLead(id)
      toast.success('Lead deleted')
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete failed')
    }
  }

  async function handleBulkDelete() {
    const ids = Array.from(selected)
    if (!confirm(`Delete ${ids.length} selected lead(s) and all their data?`)) return
    const t = toast.loading(`Deleting ${ids.length} leads…`)
    try {
      const res = await bulkDeleteLeads(ids)
      toast.success(`Deleted ${res.data.deleted} leads`, { id: t })
      setSelected(new Set())
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk delete failed', { id: t })
    }
  }

  async function handleBulkAudit() {
    const ids  = Array.from(selected)
    const t    = toast.loading(`Triggering ${ids.length} audits…`)
    const started = new Set()
    try {
      for (const id of ids) {
        try { await triggerAudit(id); started.add(id) } catch { /* skip */ }
      }
      toast.success(`${started.size} audits started — you'll be notified when complete`, { id: t })
      setSelected(new Set())
      fetchLeads()
      if (started.size > 0) setPendingAuditIds(started)
    } catch {
      toast.error('Failed', { id: t })
    }
  }

  async function handleAudit(id) {
    const t = toast.loading('Starting audit…')
    try {
      await triggerAudit(id)
      toast.success('Audit started — you\'ll be notified when complete', { id: t })
      fetchLeads()
      setPendingAuditIds(prev => new Set([...prev, id]))
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed', { id: t })
    }
  }

  async function handleDeleteAll() {
    if (!confirm(`⚠️ DELETE ALL ${total} LEADS?\n\nThis will permanently remove every lead and all audit data.\n\nType OK to continue.`)) return
    const confirmText = window.prompt(`Type DELETE to confirm removing all ${total} leads. This cannot be undone.`)
    if (confirmText?.trim().toUpperCase() !== 'DELETE') {
      toast.error('Cancelled — you must type DELETE to confirm')
      return
    }
    const t = toast.loading('Deleting all leads…')
    try {
      const res = await deleteAllLeads()
      toast.success(`Deleted all ${res.data.deleted} leads`, { id: t })
      setSelected(new Set())
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete all failed', { id: t })
    }
  }

  async function handleAuditAll() {
    // Check if a batch is already running before opening the modal
    try {
      const s = await getAuditStats()
      setDbStats(s.data)
      if (s.data.batch_running) {
        toast.error('A batch audit is already running. Wait for it to finish before starting a new one.')
        return
      }
    } catch { /* show modal anyway if stats fails */ }
    setAuditModeModal(true)
  }

  async function runAuditMode(mode) {
    setAuditModeModal(false)
    const labels = {
      new_only:    'Auditing new sites…',
      not_emailed: 'Re-auditing all not-emailed leads…',
      force_all:   'Re-auditing everything…',
      skipped:     'Re-auditing skipped sites…',
    }
    const t = toast.loading(labels[mode] ?? 'Triggering audits…')
    try {
      // Snapshot current done count as baseline
      const snapRes = await getAuditStats()
      const snap = snapRes.data
      const baselineDone = (snap.audited ?? 0) + (snap.emailed ?? 0) + (snap.replied ?? 0)

      let res
      if (mode === 'skipped') res = await triggerSkippedAudits()
      else res = await triggerAllAudits(mode)
      
      const triggered = res.data.triggered ?? 0

      if (triggered === 0) {
        toast.success('No leads matched — nothing to audit.', { id: t })
        return
      }

      toast.success(
        `✓ ${triggered.toLocaleString()} audits queued — running in background`,
        { id: t, duration: 5000 }
      )

      // Start stats-based progress tracking
      setAuditProgress({
        triggered,
        mode,
        done_baseline: baselineDone,
        done_now: baselineDone,
        auditing_now: triggered,
      })

      fetchLeads()
    } catch (err) {
      // Show the backend 409 "already running" message if present
      const detail = err?.response?.data?.detail
      toast.error(detail || 'Failed to queue audits', { id: t })
    }
  }

  const isPolling = auditProgress !== null || pendingAuditIds.size > 0

  return (
    <div className="p-8 page-enter">

      {auditModeModal && (
        <AuditModeModal
          stats={dbStats}
          onSelect={runAuditMode}
          onClose={() => setAuditModeModal(false)}
        />
      )}

      {auditDoneModal.visible && (
        <AuditDoneModal count={auditDoneModal.count} onOk={handleAuditDoneOk} />
      )}

      {editLead && (
        <EditLeadModal
          lead={editLead}
          onSaved={() => fetchLeads(true)}
          onClose={() => setEditLead(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Leads</h1>
          <p className="text-slate-500 text-sm mt-1">{total} total leads in database</p>
        </div>
        <div className="flex gap-2 items-center">
          {auditProgress && (() => {
            const triggered    = auditProgress.triggered ?? 1
            const baselineDone = auditProgress.done_baseline ?? 0
            const currentDone  = auditProgress.done_now ?? baselineDone
            const gained       = Math.max(0, currentDone - baselineDone)
            const pct          = Math.min(100, Math.max(2, (gained / triggered) * 100))
            const remaining    = auditProgress.auditing_now ?? (triggered - gained)
            return (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                background: 'rgba(234,179,8,0.10)', border: '1px solid rgba(234,179,8,0.3)',
                borderRadius: '10px', padding: '8px 16px',
                fontSize: '12px', color: '#fbbf24', minWidth: '280px',
              }}>
                <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', borderTopColor: '#fbbf24', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                    <span style={{ fontWeight: 700 }}>Auditing in background…</span>
                    <span style={{ color: '#a3a3a3' }}>
                      {gained.toLocaleString()} / {triggered.toLocaleString()}
                    </span>
                  </div>
                  {/* Progress bar */}
                  <div style={{ height: '5px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      background: 'linear-gradient(90deg, #fbbf24, #f59e0b)',
                      borderRadius: '3px',
                      width: `${pct}%`,
                      transition: 'width 1.5s ease',
                    }} />
                  </div>
                  <div style={{ color: '#64748b', fontSize: '10px', marginTop: '3px' }}>
                    {remaining > 0
                      ? `${Math.min(remaining, auditProgress.auditing_now ?? 3)} actively crawling · ${Math.max(0, remaining - (auditProgress.auditing_now ?? 0)).toLocaleString()} queued`
                      : 'Finishing up…'}
                  </div>
                </div>
              </div>
            )
          })()}
          {!auditProgress && pendingAuditIds.size > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px',
              background: 'rgba(234,179,8,0.12)', border: '1px solid rgba(234,179,8,0.3)',
              borderRadius: '8px', padding: '6px 14px',
              fontSize: '13px', color: '#fbbf24',
            }}>
              <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', borderTopColor: '#fbbf24' }} />
              {pendingAuditIds.size} audit{pendingAuditIds.size > 1 ? 's' : ''} running…
            </div>
          )}
          <button onClick={() => fetchLeads()} className="btn-secondary">
            <RefreshCw size={16} />
          </button>
          <button
            onClick={handleAuditAll}
            className="btn-primary"
            disabled={!!(dbStats?.batch_running)}
            title={dbStats?.batch_running ? 'A batch audit is already running…' : 'Start audit session'}
            style={dbStats?.batch_running ? { opacity: 0.45, cursor: 'not-allowed' } : {}}
          >
            <PlayCircle size={16} /> Audit All
          </button>
          {total > 0 && (
            <button
              onClick={handleDeleteAll}
              title="Delete ALL leads permanently"
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.4)',
                color: '#f87171', borderRadius: '8px', padding: '7px 14px',
                fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'rgba(239,68,68,0.22)'
                e.currentTarget.style.borderColor = 'rgba(239,68,68,0.7)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'rgba(239,68,68,0.12)'
                e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)'
              }}
            >
              <Trash2 size={14} /> Delete All
            </button>
          )}
        </div>
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={`
          border-2 border-dashed rounded-xl p-8 mb-6 text-center cursor-pointer
          transition-all duration-200
          ${isDragActive
            ? 'border-blue-500 bg-blue-600/10'
            : 'border-slate-700 hover:border-blue-600/50 hover:bg-blue-600/5'}
        `}
      >
        <input {...getInputProps()} />
        <Upload size={28} className="mx-auto mb-3 text-slate-500" />
        {isDragActive ? (
          <p className="text-blue-400 font-medium">Drop your CSV here…</p>
        ) : (
          <>
            <p className="text-slate-300 font-medium">Drag &amp; drop leads.csv here</p>
            <p className="text-slate-600 text-sm mt-1">
              or click to browse — columns: business_name, email, phone, website
            </p>
          </>
        )}
      </div>

      {/* Filter + Search */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
        {/* Status filter */}
        <div className="relative" style={{ minWidth: '185px' }}>
          <Filter size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <select
            className="input pl-8 text-sm"
            value={filter}
            onChange={e => { setFilter(e.target.value); setPage(1) }}
          >
            <option value="">All Statuses</option>
            <option value="new">New (Not Audited)</option>
            <option value="auditing">Auditing…</option>
            <option value="audited">Audited (Ready to Send)</option>
            <option value="emailed">Emailed ✉</option>
            <option value="replied">Replied ✔</option>
            <option value="skipped">Skipped (Errors)</option>
          </select>
        </div>

        {/* Search box */}
        <div className="relative" style={{ flex: 1, minWidth: '220px', maxWidth: '400px' }}>
          <Search size={14} style={{
            position: 'absolute', left: '11px', top: '50%', transform: 'translateY(-50%)',
            color: searchInput ? '#60a5fa' : '#475569', pointerEvents: 'none',
          }} />
          <input
            type="text"
            className="input text-sm"
            style={{
              paddingLeft: '34px',
              paddingRight: searchInput ? '32px' : '12px',
              width: '100%',
              borderColor: searchInput ? 'rgba(59,130,246,0.5)' : undefined,
              boxShadow: searchInput ? '0 0 0 3px rgba(59,130,246,0.08)' : undefined,
              transition: 'border-color 0.15s, box-shadow 0.15s',
            }}
            placeholder="Search by name or email…"
            value={searchInput}
            onChange={e => handleSearchInput(e.target.value)}
          />
          {searchInput && (
            <button
              onClick={clearSearch}
              title="Clear search"
              style={{
                position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer', color: '#475569',
                display: 'flex', alignItems: 'center', padding: '2px', borderRadius: '4px',
              }}
              onMouseEnter={e => e.currentTarget.style.color = '#94a3b8'}
              onMouseLeave={e => e.currentTarget.style.color = '#475569'}
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Search result count pill */}
        {search && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            fontSize: '12px', color: '#64748b',
          }}>
            <span style={{ color: '#60a5fa', fontWeight: 700 }}>{total}</span>
            <span>result{total !== 1 ? 's' : ''} for</span>
            <span style={{
              background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.25)',
              borderRadius: '6px', padding: '1px 8px', color: '#93c5fd', fontWeight: 600,
              fontStyle: 'italic',
            }}>"{search}"</span>
          </div>
        )}
      </div>


      {/* Bulk Action Bar */}
      {selected.size > 0 && (
        <div className="mb-4 flex items-center gap-3 bg-blue-600/10 border border-blue-500/30 rounded-xl px-4 py-3">
          <span className="text-blue-400 font-semibold text-sm">
            {selected.size} lead{selected.size > 1 ? 's' : ''} selected
          </span>
          <div className="ml-auto flex gap-2">
            <button onClick={handleBulkAudit} className="btn-primary py-1.5 px-3 text-xs">
              <Search size={13} /> Audit Selected
            </button>
            <button onClick={handleBulkDelete} className="btn-danger py-1.5 px-3 text-xs">
              <Trash2 size={13} /> Delete Selected
            </button>
            <button onClick={() => setSelected(new Set())} className="btn-secondary py-1.5 px-3 text-xs">
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <table className="w-full">
          <thead style={{ backgroundColor: '#0f172a' }}>
            <tr>
              <th className="th" style={{ width: '42px' }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={el => { if (el) el.indeterminate = someSelected }}
                  onChange={toggleAll}
                  style={{ width: '15px', height: '15px', cursor: 'pointer', accentColor: '#2563eb' }}
                  title="Select all"
                />
              </th>
              <th className="th">Business</th>
              <th className="th">Email</th>
              <th className="th">Website</th>
              <th className="th">Status</th>
              <th className="th">Added</th>
              <th className="th">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="td text-center py-12 text-slate-500">
                <span className="spinner" />
              </td></tr>
            ) : leads.length === 0 ? (
              <tr><td colSpan={7} className="td text-center py-12 text-slate-500">
                No leads found. Upload a CSV to get started.
              </td></tr>
            ) : leads.map(lead => {
              const isAuditing  = lead.status === 'auditing'
              // Warn if name looks like a scraped tagline (contains | or long)
              const looksScraped = lead.business_name.includes('|')
                || lead.business_name.includes(' - ')
                || lead.business_name.length > 60

              return (
                <tr
                  key={lead.id}
                  className="table-row"
                  style={selected.has(lead.id) ? { backgroundColor: 'rgba(37,99,235,0.08)' } : {}}
                >
                  <td className="td" style={{ width: '42px' }}>
                    <input
                      type="checkbox"
                      checked={selected.has(lead.id)}
                      onChange={() => toggleOne(lead.id)}
                      style={{ width: '15px', height: '15px', cursor: 'pointer', accentColor: '#2563eb' }}
                    />
                  </td>

                  {/* Business Name — with scraped tagline warning */}
                  <td className="td font-medium" style={{ maxWidth: '220px' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                      <span
                        title={lead.business_name}
                        style={{
                          color: looksScraped ? '#fbbf24' : '#f1f5f9',
                          overflow: 'hidden', textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap', maxWidth: '190px', display: 'block',
                          fontSize: '13px',
                        }}
                      >
                        {lead.business_name}
                      </span>
                      {looksScraped && (
                        <span
                          title="Name looks like a scraped tagline — click Edit (✏️) to fix"
                          style={{ fontSize: '10px', color: '#f59e0b', flexShrink: 0, cursor: 'help' }}
                        >⚠️</span>
                      )}
                    </div>
                  </td>

                  <td className="td" style={{ fontSize: '13px' }}>{lead.email}</td>

                  <td className="td">
                    <a
                      href={lead.website}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 text-blue-400 hover:text-blue-300"
                      style={{ fontSize: '12px' }}
                    >
                      <Globe size={12} />
                      {lead.website.replace(/^https?:\/\//, '').slice(0, 28)}
                    </a>
                  </td>

                  <td className="td">
                    <div className="flex flex-col gap-1 items-start">
                      <div className="flex items-center gap-2">
                        {lead.status === 'emailed' && lead.last_emailed_at ? (
                          <span style={{
                            padding: '3px 8px', borderRadius: 6, fontSize: 10, fontWeight: 700,
                            background: 'rgba(74,222,128,0.12)', color: '#4ade80',
                            border: '1px solid rgba(74,222,128,0.25)', letterSpacing: '0.3px',
                            whiteSpace: 'nowrap',
                          }}>
                            ✉ SENT {new Date(lead.last_emailed_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }).toUpperCase()}
                          </span>
                        ) : (
                          <span className={`badge ${STATUS_BADGE[lead.status] || 'badge-grey'}`}>
                            {lead.status}
                          </span>
                        )}
                        {isAuditing && (
                          <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderTopColor: '#fbbf24' }} />
                        )}
                      </div>
                      
                      {/* Show skip reason if present */}
                      {lead.audit_error?.startsWith('SITE_STATUS:') && lead.status !== 'auditing' && (
                        <span style={{
                          fontSize: '10px', color: '#f97316', background: 'rgba(249,115,22,0.1)', 
                          padding: '1px 6px', borderRadius: '4px', border: '1px solid rgba(249,115,22,0.2)',
                          display: 'inline-block'
                        }}>
                          {lead.audit_error.split(':')[1].toUpperCase().replaceAll('_', ' ')}
                        </span>
                      )}
                    </div>
                  </td>

                  <td className="td text-slate-500 text-xs">
                    {new Date(lead.created_at).toLocaleDateString()}
                  </td>

                  <td className="td">
                    <div className="flex gap-1.5">
                      {/* Edit */}
                      <button
                        onClick={() => setEditLead(lead)}
                        className="btn-secondary py-1 px-2 text-xs"
                        title="Edit lead"
                        style={{ color: '#60a5fa' }}
                      >
                        <Pencil size={13} />
                      </button>
                      {/* Audit */}
                      <button
                        onClick={() => handleAudit(lead.id)}
                        className="btn-primary py-1 px-2 text-xs"
                        title="Trigger Audit"
                        disabled={isAuditing}
                        style={isAuditing ? { opacity: 0.4, cursor: 'not-allowed' } : {}}
                      >
                        <Search size={13} />
                      </button>
                      {/* Delete */}
                      <button
                        onClick={() => handleDelete(lead.id)}
                        className="btn-danger py-1 px-2 text-xs"
                        title="Delete"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > pageSize && (
        <div className="flex justify-between items-center mt-4">
          <p className="text-sm text-slate-500">
            Page {page} of {Math.ceil(total / pageSize)}
          </p>
          <div className="flex gap-2">
            <button className="btn-secondary py-1 px-3 text-sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>Previous</button>
            <button className="btn-secondary py-1 px-3 text-sm" onClick={() => setPage(p => p + 1)} disabled={page * pageSize >= total}>Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
