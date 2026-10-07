import { useEffect, useState, useRef, useCallback } from 'react'
import {
  Plus, Send, RefreshCw, Users, FlaskConical, X, ChevronDown, ChevronRight,
  Trash2, Pause, Play, RotateCcw, Clock, CheckCircle, AlertCircle, SkipForward,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getCampaigns, createCampaign, sendCampaign, pauseCampaign, resumeCampaign,
  resetCampaign, deleteCampaign, getCampaignLogs, getAllLeadsForPicker, sendTestEmail,
  retryCampaignFailed,
} from '../api/client'


const STATUS_BADGE = {
  draft:     'badge-grey',
  scheduled: 'badge-yellow',
  sending:   'badge-blue',
  paused:    'badge-yellow',
  done:      'badge-green',
}

const DEFAULT_TEMPLATE = `{hi|hey|hello} {business_name},

{i was|i've been} {checking out|looking at} your website ({website}) and {noticed|spotted} a few things that {could be|might be} {hurting|affecting} your Google rankings.

{specifically,|to be specific,} {the site has|your website has} {audit_summary}.

{we offer|we have} three ways {i can|we can} help:

1. $25 — {i'll send you|you get} the full PDF report with exact fix instructions.
2. $60 — {we send|you get} the report {and|plus} our team {manually patches|fixes} the issues.
3. $150 — everything above {plus|and} we {create|set up} your missing social profiles.

{if you're interested|just reply} and {we'll talk|i'll get back to you}.

{cheers|thanks},
TEB Solutions`


// ── Time-ago helper ───────────────────────────────────────────────────────────
function timeAgo(isoStr) {
  if (!isoStr) return null
  const diff = Date.now() - new Date(isoStr).getTime()   // ms
  const mins  = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days  = Math.floor(diff / 86400000)
  if (mins < 2)   return 'just now'
  if (mins < 60)  return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days === 1) return '1 day ago'
  return `${days} days ago`
}

// Returns true if the lead is still in the 7-day email cooldown
function inCooldown(isoStr) {
  if (!isoStr) return false
  return (Date.now() - new Date(isoStr).getTime()) < 7 * 24 * 3600 * 1000
}


function useCountdown(nextEmailAt) {
  const [remaining, setRemaining] = useState(null)
  useEffect(() => {
    if (!nextEmailAt) { setRemaining(null); return }
    const target = new Date(nextEmailAt).getTime()
    const tick = () => {
      const diff = Math.max(0, target - Date.now())
      setRemaining(diff)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [nextEmailAt])
  return remaining
}

function CountdownDisplay({ nextEmailAt }) {
  const ms = useCountdown(nextEmailAt)
  if (ms === null) return null
  if (ms === 0) return <span style={{ color: '#60a5fa', fontSize: 12 }}>⏳ Sending now…</span>
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#94a3b8', fontSize: 12 }}>
      <Clock size={12} />
      Next in {mins}m {secs}s
    </span>
  )
}


// ── Log status icon ───────────────────────────────────────────────────────────
function LogIcon({ status }) {
  if (status === 'sent')    return <CheckCircle size={13} color="#4ade80" />
  if (status === 'failed')  return <AlertCircle size={13} color="#f87171" />
  if (status === 'skipped') return <SkipForward size={13} color="#facc15" />
  return null
}


// ── Expandable campaign logs panel ────────────────────────────────────────────
function CampaignLogs({ campaignId, onRetryDone }) {
  const [logs, setLogs]         = useState(null)
  const [loading, setLoading]   = useState(false)
  const [retrying, setRetrying] = useState(false)

  async function load() {
    if (loading) return
    setLoading(true)
    try {
      const res = await getCampaignLogs(campaignId, 200)
      setLogs(res.data)
    } catch { toast.error('Could not load logs') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [campaignId])

  async function handleRetry() {
    if (retrying) return
    setRetrying(true)
    try {
      const res = await retryCampaignFailed(campaignId)
      toast.success(`Retrying ${res.data.retrying_count} failed emails…`)
      setTimeout(() => { load(); if (onRetryDone) onRetryDone() }, 1500)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Retry failed')
    } finally { setRetrying(false) }
  }

  if (loading && !logs) return (
    <div style={{ padding: '12px 16px', color: '#64748b', fontSize: 13 }}>Loading logs…</div>
  )
  if (!logs || logs.length === 0) return (
    <div style={{ padding: '12px 16px', color: '#64748b', fontSize: 13 }}>No emails sent yet.</div>
  )

  // 1. Sort newest first so we can pick the latest log per email
  const newestFirst = [...logs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
  
  // 2. Dedup by email to show only the most recent status
  const uniqueLogsMap = new Map()
  newestFirst.forEach(l => {
    if (!uniqueLogsMap.has(l.email)) uniqueLogsMap.set(l.email, l)
  })
  const uniqueLogs = Array.from(uniqueLogsMap.values())

  // 3. Sort for display: failed first, then pending/skipped, then sent last
  const sorted = uniqueLogs.sort((a, b) => {
    const order = { failed: 0, skipped: 1, sent: 2 }
    const oa = order[a.status] ?? 1
    const ob = order[b.status] ?? 1
    if (oa !== ob) return oa - ob
    return new Date(b.created_at) - new Date(a.created_at)
  })

  // 4. Calculate actual unique counts
  const failedCount = uniqueLogs.filter(l => l.status === 'failed').length
  const sentCount   = uniqueLogs.filter(l => l.status === 'sent').length


  function fmtSentDate(iso) {
    const d = new Date(iso)
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).toUpperCase()
  }

  // Extract sender label from message ("via Hostinger (...)" or "via Gmail (...)")
  function parseSenderBadge(message) {
    if (!message) return null
    if (message.toLowerCase().includes('hostinger')) return { label: 'Hostinger', color: '#fb923c', bg: 'rgba(251,146,60,0.12)', border: 'rgba(251,146,60,0.3)' }
    if (message.toLowerCase().includes('gmail'))     return { label: 'Gmail',     color: '#60a5fa', bg: 'rgba(96,165,250,0.10)', border: 'rgba(96,165,250,0.25)' }
    return null
  }

  // Extract human error reason from message
  function parseErrReason(message) {
    if (!message) return ''
    const m = message
    if (m.includes('Daily sending limit')) return '⚠． Daily limit exceeded'
    if (m.includes('Server busy'))         return '⏳ Server busy – retry later'
    if (m.includes('Authentication'))      return '🔒 Auth failed'
    if (m.includes('timeout'))             return '⏱ Timeout'
    // strip via ... prefix to get the note part
    const parts = m.split('—')
    return parts.length > 1 ? parts.slice(1).join('—').trim() : m
  }

  return (
    <div style={{ maxHeight: 340, overflowY: 'auto' }}>
      {/* Summary bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '8px 14px', background: 'rgba(0,0,0,0.2)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
          <span style={{ color: '#4ade80' }}>✔ {sentCount} sent</span>
          {failedCount > 0 && <span style={{ color: '#f87171' }}>✕ {failedCount} failed</span>}
        </div>
        {failedCount > 0 && (
          <button onClick={handleRetry} disabled={retrying}
            style={{
              fontSize: 11, fontWeight: 700, padding: '4px 12px', borderRadius: 6, cursor: 'pointer',
              background: retrying ? 'rgba(251,146,60,0.08)' : 'rgba(251,146,60,0.15)',
              border: '1px solid rgba(251,146,60,0.4)', color: '#fb923c',
              display: 'flex', alignItems: 'center', gap: 5,
            }}>
            <RotateCcw size={11} />{retrying ? 'Retrying…' : `Retry ${failedCount} Failed`}
          </button>
        )}
      </div>

      <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: 'rgba(0,0,0,0.2)', position: 'sticky', top: 0 }}>
            {['', 'Business', 'Email', 'Status / Sender', 'Error / Note'].map(h => (
              <th key={h} style={{ padding: '7px 10px', textAlign: 'left', color: '#94a3b8', fontWeight: 600, fontSize: 10, letterSpacing: '0.4px' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(log => {
            const isSent    = log.status === 'sent'
            const isFailed  = log.status === 'failed'
            const sender    = parseSenderBadge(log.message)
            const errReason = isFailed ? parseErrReason(log.message) : ''
            return (
              <tr key={log.id} style={{
                borderTop: '1px solid rgba(255,255,255,0.04)',
                opacity: isSent ? 0.72 : 1,
                background: isFailed ? 'rgba(248,113,113,0.04)' : isSent ? 'rgba(74,222,128,0.02)' : 'transparent',
              }}>
                <td style={{ padding: '6px 10px' }}><LogIcon status={log.status} /></td>
                <td style={{ padding: '6px 10px', color: isSent ? '#94a3b8' : '#e2e8f0', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {log.business_name || '—'}
                </td>
                <td style={{ padding: '6px 10px', color: '#64748b', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {log.email}
                </td>
                <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {isSent ? (
                      <span style={{
                        padding: '3px 7px', borderRadius: 5, fontSize: 10, fontWeight: 700,
                        background: 'rgba(74,222,128,0.12)', color: '#4ade80',
                        border: '1px solid rgba(74,222,128,0.2)', letterSpacing: '0.3px',
                      }}>✉ SENT ON {fmtSentDate(log.created_at)}</span>
                    ) : isFailed ? (
                      <span style={{
                        padding: '3px 7px', borderRadius: 5, fontSize: 10, fontWeight: 700,
                        background: 'rgba(248,113,113,0.15)', color: '#f87171',
                        border: '1px solid rgba(248,113,113,0.3)',
                      }}>FAILED</span>
                    ) : (
                      <span style={{
                        padding: '3px 7px', borderRadius: 4, fontSize: 11,
                        background: 'rgba(250,204,21,0.15)', color: '#facc15',
                      }}>{log.status}</span>
                    )}
                    {sender && (
                      <span style={{
                        padding: '2px 6px', borderRadius: 4, fontSize: 9, fontWeight: 700,
                        background: sender.bg, color: sender.color, border: `1px solid ${sender.border}`,
                      }}>{sender.label}</span>
                    )}
                  </div>
                </td>
                <td style={{ padding: '6px 10px', color: isFailed ? '#fca5a5' : '#475569', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>
                  {isFailed ? errReason : (isSent ? '' : (log.message || '—'))}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


// ── Test Email floating mini-panel ────────────────────────────────────────────
function TestPanel({ leads, onClose }) {
  const [toEmail, setToEmail] = useState('')
  const [leadId, setLeadId]   = useState('')
  const [sending, setSending] = useState(false)
  const [result, setResult]   = useState(null)

  async function handleSend(e) {
    e.preventDefault()
    if (!leadId)  { toast.error('Select a lead'); return }
    if (!toEmail) { toast.error('Enter email'); return }
    setSending(true)
    setResult(null)
    try {
      const res = await sendTestEmail(leadId, toEmail)
      setResult(res.data)
      toast.success(`Sent via ${res.data.sender}`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Send failed')
    } finally { setSending(false) }
  }

  return (
    <div style={{
      position: 'fixed', bottom: 28, right: 28, width: 380, zIndex: 1000,
      background: 'linear-gradient(135deg,#1e293b,#0f172a)',
      border: '1px solid rgba(255,255,255,0.08)', borderRadius: 16,
      boxShadow: '0 24px 64px rgba(0,0,0,0.5)', padding: 24,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontWeight: 600, color: '#e2e8f0' }}>🧪 Test Email Preview</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}>
          <X size={16} />
        </button>
      </div>
      <form onSubmit={handleSend} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <select value={leadId} onChange={e => setLeadId(e.target.value)}
          style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#e2e8f0', padding: '8px 10px', fontSize: 13 }}>
          <option value="">Select a lead…</option>
          {leads.map(l => <option key={l.id} value={l.id}>{l.business_name} ({l.email})</option>)}
        </select>
        <input type="email" value={toEmail} onChange={e => setToEmail(e.target.value)}
          placeholder="Send preview to…"
          style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#e2e8f0', padding: '8px 10px', fontSize: 13 }} />
        <button type="submit" disabled={sending} className="btn-primary" style={{ justifyContent: 'center' }}>
          {sending ? 'Sending…' : <><Send size={14} /> Send Preview</>}
        </button>
      </form>
      {result && (
        <div style={{ marginTop: 12, padding: 10, background: 'rgba(34,197,94,0.08)', borderRadius: 8, fontSize: 12, color: '#4ade80' }}>
          ✅ Sent via {result.sender}<br />
          <span style={{ color: '#64748b' }}>Subject: {result.subject}</span>
        </div>
      )}
    </div>
  )
}


// ── Campaign row ──────────────────────────────────────────────────────────────
function CampaignRow({ c, onAction, onRetryFailed }) {
  const [expanded, setExpanded] = useState(false)
  const isSending = c.status === 'sending'
  const isPaused  = c.status === 'paused'
  const isDone    = c.status === 'done'
  const isDraft   = c.status === 'draft'
  const total     = c.lead_ids?.length || 0
  const hasFailed = (c.failed_count || 0) > 0

  return (
    <>
      <tr style={{ transition: 'background 0.15s' }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.025)'}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      >
        {/* Expand toggle */}
        <td style={{ padding: '14px 12px', width: 32 }}>
          <button onClick={() => setExpanded(x => !x)}
            style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', display: 'flex' }}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        </td>

        {/* Name */}
        <td style={{ padding: '14px 8px' }}>
          <div style={{ fontWeight: 600, color: '#e2e8f0', fontSize: 14 }}>{c.name}</div>
          {isSending && <CountdownDisplay nextEmailAt={c.next_email_at} />}
          {isPaused && <span style={{ fontSize: 11, color: '#facc15' }}>⏸ Paused — {c.pending_lead_ids?.length || 0} remaining</span>}
        </td>

        {/* Leads */}
        <td style={{ padding: '14px 8px', color: '#94a3b8', fontSize: 13 }}>
          <Users size={13} style={{ marginRight: 4, verticalAlign: 'middle' }} />{total}
        </td>

        {/* Progress */}
        <td style={{ padding: '14px 8px', minWidth: 120 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ height: '100%', background: isDone ? '#4ade80' : '#3b82f6', width: total ? `${Math.round((c.sent_count / total) * 100)}%` : '0%', transition: 'width 0.4s', borderRadius: 2 }} />
            </div>
            <span style={{ fontSize: 11, color: '#64748b', whiteSpace: 'nowrap' }}>
              {c.sent_count}/{total}
              {c.skipped_count > 0 && <span style={{ color: '#facc15' }}> · ⟳{c.skipped_count}</span>}
              {c.failed_count > 0  && <span style={{ color: '#f87171' }}> · ✗{c.failed_count}</span>}
            </span>
          </div>
        </td>

        {/* Status */}
        <td style={{ padding: '14px 8px' }}>
          <span className={`badge ${STATUS_BADGE[c.status] || 'badge-grey'}`}>{c.status}</span>
        </td>

        {/* Created */}
        <td style={{ padding: '14px 8px', color: '#64748b', fontSize: 12, whiteSpace: 'nowrap' }}>
          {new Date(c.created_at).toLocaleDateString('en-IN')}
        </td>

        {/* Actions */}
        <td style={{ padding: '14px 8px' }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Send / Resume */}
            {(isDraft) && (
              <button onClick={() => onAction('send', c)} className="btn-primary" style={{ padding: '5px 12px', fontSize: 12 }}>
                <Send size={12} /> Send
              </button>
            )}
            {isPaused && (
              <button onClick={() => onAction('resume', c)} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', fontSize: 12, background: 'rgba(74,222,128,0.12)', border: '1px solid rgba(74,222,128,0.3)', color: '#4ade80', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
                <Play size={12} /> Resume
              </button>
            )}
            {/* Pause */}
            {isSending && (
              <button onClick={() => onAction('pause', c)} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', fontSize: 12, background: 'rgba(250,204,21,0.12)', border: '1px solid rgba(250,204,21,0.3)', color: '#facc15', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
                <Pause size={12} /> Pause
              </button>
            )}
            {/* 🔴 RETRY FAILED — shown directly on row when failed_count > 0 */}
            {hasFailed && !isSending && (
              <button
                onClick={() => onRetryFailed(c)}
                title={`Retry ${c.failed_count} failed email${c.failed_count > 1 ? 's' : ''}`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '5px 12px', fontSize: 12, fontWeight: 700,
                  background: 'rgba(251,146,60,0.13)',
                  border: '1px solid rgba(251,146,60,0.4)',
                  color: '#fb923c', borderRadius: 8, cursor: 'pointer',
                  animation: 'pulse 2s infinite',
                }}>
                <RotateCcw size={12} /> Retry {c.failed_count}
              </button>
            )}
            {/* Reset for stuck/done */}
            {(isSending || isDone) && (
              <button onClick={() => onAction('reset', c)} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '5px 10px', fontSize: 12, background: 'rgba(148,163,184,0.08)', border: '1px solid rgba(148,163,184,0.2)', color: '#94a3b8', borderRadius: 8, cursor: 'pointer' }}>
                <RotateCcw size={11} /> Reset
              </button>
            )}
            {/* Delete */}
            {!isSending && (
              <button onClick={() => onAction('delete', c)} title="Delete campaign" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '5px 10px', fontSize: 12, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', color: '#f87171', borderRadius: 8, cursor: 'pointer' }}>
                <Trash2 size={11} />
              </button>
            )}
          </div>
        </td>
      </tr>

      {/* Expanded log row */}
      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: 0, background: 'rgba(0,0,0,0.25)', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ padding: '4px 0' }}>
              <div style={{ padding: '8px 16px 4px', fontSize: 12, color: '#64748b', fontWeight: 600, letterSpacing: '0.5px' }}>EMAIL LOG</div>
              <CampaignLogs campaignId={c.id} onRetryDone={() => onRetryFailed(c, true)} />
            </div>
          </td>
        </tr>
      )}
    </>
  )
}


// ── New Campaign inline panel (no modal) ─────────────────────────────────────
function NewCampaignPanel({ leads, onClose, onCreate }) {
  const [form, setForm] = useState({
    name: '', template: DEFAULT_TEMPLATE,
    subject_template: '{business_name} — quick question',
    selectedLeads: [],
  })
  const [saving, setSaving]       = useState(false)
  const [quickNum, setQuickNum]   = useState('')   // custom number input

  const hasSuccessfulAudit = (lead) => lead.audit_status === 'done'
  const campaignReadyLeads = leads.filter(hasSuccessfulAudit)
  // Fresh = successfully audited (audit.status=done) AND never emailed.
  const freshLeads    = leads.filter(l => !l.last_emailed_at && hasSuccessfulAudit(l))
  // Not ready = never emailed but no successful audit yet.
  const notAuditedLeads = leads.filter(l => !l.last_emailed_at && !hasSuccessfulAudit(l))
  const cooldownLeads = leads.filter(l => l.last_emailed_at && inCooldown(l.last_emailed_at))
  const expiredLeads  = leads.filter(l => l.last_emailed_at && !inCooldown(l.last_emailed_at) && hasSuccessfulAudit(l))

  const toggleLead = (id) => {
    const lead = leads.find(l => l.id === id)
    if (!lead || !hasSuccessfulAudit(lead)) return
    setForm(f => ({
      ...f,
      selectedLeads: f.selectedLeads.includes(id)
        ? f.selectedLeads.filter(x => x !== id)
        : [...f.selectedLeads, id],
    }))
  }

  const selectAll = () =>
    setForm(f => ({ ...f, selectedLeads: campaignReadyLeads.map(l => l.id) }))

  // Select first N fresh leads
  function selectFresh(n) {
    const ids = freshLeads.slice(0, n).map(l => l.id)
    setForm(f => ({ ...f, selectedLeads: ids }))
  }

  function handleQuickNumSelect() {
    const n = parseInt(quickNum, 10)
    if (!isNaN(n) && n > 0) selectFresh(n)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim())               { toast.error('Enter a campaign name'); return }
    if (form.selectedLeads.length === 0)  { toast.error('Select at least one lead'); return }
    const readyIds = new Set(campaignReadyLeads.map(l => l.id))
    if (form.selectedLeads.some(id => !readyIds.has(id))) {
      toast.error('Remove leads without a successful audit before creating the campaign')
      return
    }
    setSaving(true)
    try {
      const res = await createCampaign({
        name: form.name.trim(),
        template: form.template,
        subject_template: form.subject_template,
        lead_ids: form.selectedLeads,
      })
      toast.success(`Campaign "${form.name}" created!`)
      onCreate(res.data)
      onClose()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Create failed')
    } finally { setSaving(false) }
  }

  return (
    <div style={{
      marginTop: 16,
      background: 'linear-gradient(135deg, rgba(15,23,42,0.98), rgba(15,23,42,0.95))',
      border: '1px solid rgba(59,130,246,0.25)',
      borderRadius: 16,
      overflow: 'hidden',
      animation: 'slideDown 0.22s ease',
      boxShadow: '0 8px 40px rgba(0,0,0,0.4)',
    }}>
      {/* Panel header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '14px 24px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(59,130,246,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#3b82f6', boxShadow: '0 0 8px #3b82f6' }} />
          <span style={{ fontWeight: 700, color: '#e2e8f0', fontSize: 15 }}>New Campaign</span>
          <span style={{ color: '#475569', fontSize: 13 }}>
            — {freshLeads.length} audited fresh · {notAuditedLeads.length} not audited · {expiredLeads.length} re-sendable · {cooldownLeads.length} on cooldown
          </span>
        </div>
        <button onClick={onClose} title="Cancel"
          style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#f87171', borderRadius: 8, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', fontSize: 12 }}>
          <X size={13} /> Cancel
        </button>
      </div>

      {/* Two-column layout — 40% form / 60% leads */}
      <form onSubmit={handleSubmit}>
        <div style={{ display: 'grid', gridTemplateColumns: '42% 58%', minWidth: 0 }}>

          {/* LEFT — name, subject, template */}
          <div style={{ padding: '20px 20px', borderRight: '1px solid rgba(255,255,255,0.06)', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
            <div>
              <label style={{ display: 'block', fontSize: 10, color: '#64748b', marginBottom: 5, fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase' }}>Campaign Name</label>
              <input value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))}
                placeholder="Q1 Outreach — Pune Manufacturers"
                autoFocus
                style={{ width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#e2e8f0', padding: '9px 12px', fontSize: 13, boxSizing: 'border-box', outline: 'none' }} />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 10, color: '#64748b', marginBottom: 5, fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase' }}>Email Subject</label>
              <input value={form.subject_template} onChange={e => setForm(f => ({...f, subject_template: e.target.value}))}
                style={{ width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#e2e8f0', padding: '9px 12px', fontSize: 13, boxSizing: 'border-box', outline: 'none' }} />
            </div>

            <div style={{ flex: 1 }}>
              <label style={{ display: 'block', fontSize: 10, color: '#64748b', marginBottom: 5, fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase' }}>Email Template <span style={{ color: '#475569', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>(spintax supported)</span></label>
              <textarea value={form.template} onChange={e => setForm(f => ({...f, template: e.target.value}))}
                rows={11}
                style={{ width: '100%', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#cbd5e1', padding: '10px 12px', fontSize: 12, fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box', outline: 'none', lineHeight: 1.6 }} />
            </div>
          </div>

          {/* RIGHT — leads picker (full 58% width) */}
          <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>

            {/* Header row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label style={{ fontSize: 10, color: '#64748b', fontWeight: 700, letterSpacing: '0.8px', textTransform: 'uppercase' }}>
                Select Leads
                {form.selectedLeads.length > 0 && (
                  <span style={{ marginLeft: 8, color: '#3b82f6', fontWeight: 800, fontSize: 12 }}>
                    {form.selectedLeads.length} selected
                  </span>
                )}
              </label>
              <button type="button" onClick={selectAll}
                style={{ fontSize: 11, color: '#64748b', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>
                All Ready ({campaignReadyLeads.length})
              </button>
            </div>

            {/* Quick-select row */}
            <div style={{
              display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
              padding: '8px 12px', borderRadius: 8,
              background: 'rgba(59,130,246,0.04)', border: '1px solid rgba(59,130,246,0.12)',
            }}>
              <span style={{ fontSize: 10, color: '#64748b', fontWeight: 700, letterSpacing: '0.5px', whiteSpace: 'nowrap' }}>⚡ QUICK SELECT</span>
              {[50, 60, 80].map(n => (
                <button key={n} type="button"
                  onClick={() => selectFresh(n)}
                  disabled={freshLeads.length < 1}
                  style={{
                    fontSize: 11, fontWeight: 700, padding: '4px 12px', borderRadius: 6, cursor: freshLeads.length < 1 ? 'not-allowed' : 'pointer',
                    background: 'rgba(59,130,246,0.12)',
                    border: '1px solid rgba(59,130,246,0.3)', color: '#60a5fa',
                    opacity: freshLeads.length < 1 ? 0.4 : 1,
                  }}>
                  {n} Fresh
                </button>
              ))}
              <span style={{ color: '#1e293b', fontSize: 14, fontWeight: 300 }}>|</span>
              <input
                type="number" min={1} max={leads.length} value={quickNum}
                onChange={e => setQuickNum(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), handleQuickNumSelect())}
                placeholder="Enter number"
                style={{
                  width: 96, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 6, color: '#e2e8f0', padding: '4px 8px', fontSize: 12, outline: 'none',
                }} />
              <button type="button" onClick={handleQuickNumSelect}
                disabled={!quickNum}
                style={{ fontSize: 11, fontWeight: 600, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#94a3b8' }}>
                Go
              </button>
            </div>

            {/* Legend */}
            <div style={{ display: 'flex', gap: 14, fontSize: 10, color: '#475569', flexWrap: 'wrap' }}>
              <span>✦ <span style={{ color: '#4ade80' }}>Green</span> = successful audit &amp; ready</span>
              <span>⚠ <span style={{ color: '#fb923c' }}>Orange</span> = not audited yet</span>
              <span>✉ <span style={{ color: '#94a3b8' }}>Grey</span> = ok to resend</span>
              <span>⏱ <span style={{ color: '#f87171' }}>Red</span> = 7-day cooldown</span>
            </div>

            {/* Leads list — expand to fill */}
            <div style={{ flex: 1, overflowY: 'auto', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, padding: '3px', minHeight: 220, maxHeight: 320 }}>
              {leads.length === 0 ? (
                <div style={{ padding: 24, textAlign: 'center', color: '#64748b', fontSize: 13 }}>No leads found. Upload a CSV first.</div>
              ) : leads.map(l => {
                  const ago        = timeAgo(l.last_emailed_at)
                  const cooldown   = inCooldown(l.last_emailed_at)
                  const isAudited  = hasSuccessfulAudit(l)
                  const isNew      = !isAudited
                  const isSelected = form.selectedLeads.includes(l.id)
                  // Dim un-audited leads so user knows they aren't campaign-ready
                  const rowOpacity = !isAudited ? 0.45 : cooldown ? 0.6 : 1
                  return (
                    <label key={l.id}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '7px 10px', cursor: 'pointer', borderRadius: 7,
                        transition: 'background 0.1s',
                        background: isSelected ? 'rgba(59,130,246,0.1)' : 'transparent',
                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                        opacity: rowOpacity,
                      }}
                      onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                      onMouseLeave={e => { e.currentTarget.style.background = isSelected ? 'rgba(59,130,246,0.1)' : 'transparent' }}>
                      <input type="checkbox" checked={isSelected} disabled={!isAudited} onChange={() => toggleLead(l.id)}
                        style={{ accentColor: '#3b82f6', flexShrink: 0, width: 14, height: 14, cursor: isAudited ? 'pointer' : 'not-allowed' }} />
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: isSelected ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {l.business_name}
                        </div>
                        <div style={{ color: '#475569', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.email}</div>
                      </div>
                      {ago ? (
                        // Previously emailed: show Cooldown or Sent badge
                        <span style={{
                          flexShrink: 0, fontSize: 10, fontWeight: 700, padding: '3px 7px', borderRadius: 5,
                          background: cooldown ? 'rgba(239,68,68,0.15)' : 'rgba(100,116,139,0.18)',
                          color:      cooldown ? '#fca5a5'              : '#94a3b8',
                          border:     cooldown ? '1px solid rgba(239,68,68,0.3)' : '1px solid rgba(100,116,139,0.25)',
                          whiteSpace: 'nowrap',
                        }}
                          title={cooldown ? `7-day cooldown (sent ${ago})` : `Previously emailed ${ago}`}>
                          {cooldown ? `Cooldown` : `Sent ${ago}`}
                        </span>
                      ) : isAudited ? (
                        // Audited + never emailed = campaign-ready Fresh
                        <span style={{
                          flexShrink: 0, fontSize: 10, fontWeight: 600, padding: '3px 7px', borderRadius: 5,
                          background: 'rgba(34,197,94,0.08)', color: '#4ade80',
                          border: '1px solid rgba(34,197,94,0.2)', whiteSpace: 'nowrap',
                        }} title="Audited and ready to email">✦ Fresh</span>
                      ) : (
                        // status=new: never audited — show warning badge
                        <span style={{
                          flexShrink: 0, fontSize: 10, fontWeight: 600, padding: '3px 7px', borderRadius: 5,
                          background: 'rgba(251,146,60,0.1)', color: '#fb923c',
                          border: '1px solid rgba(251,146,60,0.25)', whiteSpace: 'nowrap',
                        }} title="Not audited yet — run Audit All first">Not Audited</span>
                      )}
                    </label>
                  )
                })}
            </div>

            <button type="submit" disabled={saving} className="btn-primary"
              style={{ justifyContent: 'center', padding: '12px', fontSize: 14, width: '100%', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Creating…' : <><Plus size={16} /> Create Campaign</>}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}


// ── Main Campaigns page ───────────────────────────────────────────────────────
export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([])
  const [leads, setLeads]         = useState([])
  const [showDrawer, setShowDrawer] = useState(false)
  const [showTest, setShowTest]     = useState(false)
  const [loading, setLoading]       = useState(true)
  const pollRef = useRef(null)

  const fetchAll = useCallback(async () => {
    try {
      const [cRes, lRes] = await Promise.all([getCampaigns(), getAllLeadsForPicker()])
      setCampaigns(cRes.data)
      // Sort: never emailed → emailed but cooldown over → in cooldown (last)
      const sortedLeads = (lRes.data.items || []).slice().sort((a, b) => {
        const aAt = a.last_emailed_at ? new Date(a.last_emailed_at).getTime() : 0
        const bAt = b.last_emailed_at ? new Date(b.last_emailed_at).getTime() : 0
        const now = Date.now()
        const WEEK = 7 * 24 * 3600 * 1000
        const aCooldown = aAt > 0 && (now - aAt) < WEEK
        const bCooldown = bAt > 0 && (now - bAt) < WEEK
        // uncontacted (0) come first, then cooldown-expired, then in-cooldown last
        if (!aAt && bAt)  return -1   // a never emailed → before b
        if (aAt && !bAt)  return  1   // b never emailed → before a
        if (aCooldown && !bCooldown) return  1  // a in cooldown → after b
        if (!aCooldown && bCooldown) return -1  // b in cooldown → after a
        return 0
      })
      setLeads(sortedLeads)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to load campaigns or leads')
    } finally { setLoading(false) }
  }, [])

  // Poll every 8 seconds to keep timer + counts fresh
  useEffect(() => {
    fetchAll()
    pollRef.current = setInterval(fetchAll, 8000)
    return () => clearInterval(pollRef.current)
  }, [fetchAll])

  async function handleAction(action, campaign) {
    try {
      if (action === 'send') {
        await sendCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" started!`)
      } else if (action === 'pause') {
        await pauseCampaign(campaign.id)
        toast.success('Campaign paused — current email will finish first')
      } else if (action === 'resume') {
        await resumeCampaign(campaign.id)
        toast.success('Campaign resumed!')
      } else if (action === 'reset') {
        if (!confirm(`Reset campaign "${campaign.name}" back to draft?`)) return
        await resetCampaign(campaign.id)
        toast.success('Campaign reset to draft')
      } else if (action === 'delete') {
        if (!confirm(`Delete campaign "${campaign.name}"? This cannot be undone.`)) return
        await deleteCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" deleted`)
      }
      await fetchAll()
    } catch (err) {
      toast.error(err.response?.data?.detail || `${action} failed`)
    }
  }

  async function handleRetryFailed(campaign, silent = false) {
    try {
      const res = await retryCampaignFailed(campaign.id)
      if (!silent) toast.success(`↺ Retrying ${res.data.retrying_count} failed emails for "${campaign.name}"`)
      await fetchAll()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Retry failed')
    }
  }

  const hasSending = campaigns.some(c => c.status === 'sending')

  return (
    <div style={{ padding: '32px 40px', maxWidth: 1100 }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700, color: '#e2e8f0' }}>Campaigns</h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 14 }}>
            Create and launch humanized cold email campaigns.
            {hasSending && <span style={{ color: '#60a5fa', marginLeft: 8 }}>● Live campaign running</span>}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={fetchAll} className="btn-secondary"><RefreshCw size={16} /></button>
          <button onClick={() => setShowTest(x => !x)} className="btn-secondary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <FlaskConical size={16} /> Test Email
          </button>
          <button onClick={() => setShowDrawer(x => !x)} className={showDrawer ? 'btn-secondary' : 'btn-primary'}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {showDrawer ? <><X size={15} /> Cancel</> : <><Plus size={16} /> New Campaign</>}
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 60 }}>Loading campaigns…</div>
      ) : campaigns.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 80 }}>
          <Plus size={40} style={{ opacity: 0.2, marginBottom: 12 }} />
          <div>No campaigns yet. Create your first one!</div>
        </div>
      ) : (
        <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 16, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <th style={{ padding: '12px 12px', width: 32 }}></th>
                {['NAME', 'LEADS', 'PROGRESS', 'STATUS', 'CREATED', 'ACTIONS'].map(h => (
                  <th key={h} style={{ padding: '12px 8px', textAlign: 'left', fontSize: 11, color: '#64748b', fontWeight: 600, letterSpacing: '0.5px' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {campaigns.map(c => (
                <CampaignRow key={c.id} c={c} onAction={handleAction} onRetryFailed={handleRetryFailed} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Inline new-campaign panel — appears below the table */}
      {showDrawer && (
        <NewCampaignPanel
          leads={leads}
          onClose={() => setShowDrawer(false)}
          onCreate={() => { fetchAll(); setShowDrawer(false) }}
        />
      )}

      {/* Test email floating panel (bottom-right) */}
      {showTest && (
        <TestPanel leads={leads} onClose={() => setShowTest(false)} />
      )}
    </div>
  )
}
