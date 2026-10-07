import { useState, useEffect, useCallback } from 'react'
import {
  Inbox, RefreshCw, CheckCircle2, Trash2, ExternalLink,
  TrendingUp, Mail, AlertTriangle, XCircle, Users, Clock,
  ChevronLeft, ChevronRight, Eye, ArrowLeftRight, Info,
  Send, Loader,
} from 'lucide-react'

const API = import.meta.env.VITE_API_URL || '/api'

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${localStorage.getItem('teb_token')}`,
  }
}

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: authHeaders(),
    ...options,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Stat Card ──────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, color = '#6366f1', sub, tooltip }) {
  const [showTip, setShowTip] = useState(false)
  return (
    <div style={{
      background: 'var(--surface-card, #1e2535)',
      border: '1px solid var(--surface-border, #2d3748)',
      borderRadius: 14,
      padding: '20px 24px',
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      minWidth: 180,
      position: 'relative',
    }}>
      <div style={{
        width: 48, height: 48, borderRadius: 12,
        background: `${color}22`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        <Icon size={22} style={{ color }} />
      </div>
      <div>
        <div style={{ fontSize: 26, fontWeight: 800, color: '#f1f5f9', lineHeight: 1 }}>
          {value ?? '—'}
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
          {label}
          {tooltip && (
            <span style={{ position: 'relative', cursor: 'help' }}
              onMouseEnter={() => setShowTip(true)}
              onMouseLeave={() => setShowTip(false)}>
              <Info size={11} style={{ color: '#4b5563' }} />
              {showTip && (
                <span style={{
                  position: 'absolute', bottom: '140%', left: '50%',
                  transform: 'translateX(-50%)',
                  background: '#0f172a', border: '1px solid #2d3748',
                  color: '#94a3b8', fontSize: 11, padding: '6px 10px',
                  borderRadius: 6, whiteSpace: 'nowrap', zIndex: 10,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
                }}>
                  {tooltip}
                </span>
              )}
            </span>
          )}
        </div>
        {sub && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{sub}</div>}
      </div>
    </div>
  )
}

// ── Badge ──────────────────────────────────────────────────────────────────
function Badge({ type }) {
  const cfg = {
    converted:   { label: 'YES ✓',        bg: '#16a34a22', color: '#4ade80', border: '#16a34a55' },
    replied:     { label: 'Replied',       bg: '#2563eb22', color: '#60a5fa', border: '#2563eb55' },
    soft_bounce: { label: 'Out of Office', bg: '#d9770622', color: '#fb923c', border: '#d9770655' },
    positive:    { label: 'Positive',      bg: '#16a34a22', color: '#4ade80', border: '#16a34a55' },
    stop:        { label: 'STOP',          bg: '#dc262622', color: '#f87171', border: '#dc262655' },
    bounce:      { label: 'Bounced',       bg: '#dc262622', color: '#f87171', border: '#dc262655' },
    other:       { label: 'Other',         bg: '#33333322', color: '#94a3b8', border: '#44444455' },
  }
  const c = cfg[type] || { label: type, bg: '#33333322', color: '#94a3b8', border: '#44444455' }
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '0.8px',
      textTransform: 'uppercase', padding: '3px 10px',
      borderRadius: 20, background: c.bg, color: c.color,
      border: `1px solid ${c.border}`,
    }}>
      {c.label}
    </span>
  )
}

// ── Reply Preview Modal ────────────────────────────────────────────────────
function ReplyModal({ lead, onClose, onReclassify, reclassifying }) {
  if (!lead) return null
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#131c2e',
          border: '1px solid #2d3748',
          borderRadius: 16,
          padding: 28,
          width: '100%',
          maxWidth: 620,
          boxShadow: '0 24px 60px rgba(0,0,0,0.6)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <h2 style={{ color: '#f1f5f9', fontWeight: 800, fontSize: 17, margin: 0 }}>
              Reply Preview
            </h2>
            <p style={{ color: '#64748b', fontSize: 12, margin: '4px 0 0' }}>
              {lead.business_name} · <a href={`mailto:${lead.email}`} style={{ color: '#60a5fa' }}>{lead.email}</a>
            </p>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#64748b',
            cursor: 'pointer', fontSize: 20, lineHeight: 1, padding: 4,
          }}>✕</button>
        </div>

        {/* Current classification */}
        <div style={{
          background: '#0f172a', borderRadius: 10, padding: '12px 16px',
          marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span style={{ color: '#64748b', fontSize: 12, fontWeight: 600 }}>CLASSIFIED AS:</span>
          <Badge type={lead.reply_type || lead.status} />
          {lead.replied_at && (
            <span style={{ color: '#4b5563', fontSize: 11, marginLeft: 'auto' }}>
              {new Date(lead.replied_at).toLocaleString('en-IN')}
            </span>
          )}
        </div>

        {/* Reply text */}
        <div style={{
          background: '#0a1628',
          border: '1px solid #1e3a5f',
          borderRadius: 10,
          padding: '16px 18px',
          marginBottom: 20,
          minHeight: 100,
          maxHeight: 280,
          overflowY: 'auto',
        }}>
          {lead.reply_snippet
            ? (
              <p style={{
                color: '#cbd5e1', fontSize: 13, lineHeight: 1.7,
                margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {lead.reply_snippet}
              </p>
            )
            : <p style={{ color: '#4b5563', fontStyle: 'italic', margin: 0 }}>No reply text saved.</p>
          }
        </div>

        {/* Note about snippet */}
        <p style={{ color: '#4b5563', fontSize: 11, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 4 }}>
          <Info size={11} />
          Showing first 500 characters of the email body captured during sync.
        </p>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{
            padding: '9px 18px', borderRadius: 8,
            background: 'none', border: '1px solid #2d3748',
            color: '#94a3b8', cursor: 'pointer', fontWeight: 600, fontSize: 13,
          }}>
            Close
          </button>
          <button
            onClick={() => onReclassify(lead)}
            disabled={reclassifying}
            style={{
              padding: '9px 20px', borderRadius: 8,
              background: reclassifying ? '#1e2535' : '#1e3a5f',
              border: '1px solid #1e4080',
              color: reclassifying ? '#4b5563' : '#60a5fa',
              cursor: reclassifying ? 'wait' : 'pointer',
              fontWeight: 700, fontSize: 13,
              display: 'flex', alignItems: 'center', gap: 7,
            }}
          >
            <ArrowLeftRight size={14} />
            {reclassifying ? 'Moving…' : 'Move to Other'}
          </button>
        </div>

        {/* Explain what "move to other" does */}
        <p style={{ color: '#374151', fontSize: 11, marginTop: 12, textAlign: 'right' }}>
          "Move to Other" → keeps lead in DB, removes from Converted, marks as generic reply
        </p>
      </div>
    </div>
  )
}


// ── Email 2 Compose / Preview Modal ───────────────────────────────────────
// Two tabs: "Preview" (rendered iframe) and "Edit HTML" (raw textarea edit)
function Email2Modal({ lead, onClose }) {
  const [loading, setLoading]   = useState(true)
  const [html, setHtml]         = useState('')        // current HTML (editable)
  const [origHtml, setOrigHtml] = useState('')        // server-generated original
  const [tab, setTab]           = useState('preview') // 'preview' | 'edit'
  const [sending, setSending]   = useState(false)
  const [sent, setSent]         = useState(false)
  const [error, setError]       = useState('')

  const domain = (lead.website || '').replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]
  const defaultSubject = `Your site audit — ${domain}`
  const [subject, setSubject]   = useState(defaultSubject)

  // Fetch preview HTML on mount
  useEffect(() => {
    setLoading(true)
    setError('')
    apiFetch(`/replies/preview-email2/${lead.id}`)
      .then(data => {
        setHtml(data.html)
        setOrigHtml(data.html)
        setLoading(false)
      })
      .catch(() => { setError('Failed to load email preview.'); setLoading(false) })
  }, [lead.id])

  function handleReset() {
    if (window.confirm('Reset email to auto-generated content?')) {
      setHtml(origHtml)
      setSubject(defaultSubject)
    }
  }

  async function handleSend() {
    if (!window.confirm(`Send Email 2 to ${lead.email}?`)) return
    setSending(true)
    setError('')
    try {
      await apiFetch(`/replies/send-email2/${lead.id}`, {
        method: 'POST',
        body: JSON.stringify({
          custom_html: html !== origHtml ? html : null,
          custom_subject: subject !== defaultSubject ? subject : null,
        }),
      })
      setSent(true)
    } catch (e) {
      setError(e.message || 'Failed to send email.')
    } finally {
      setSending(false)
    }
  }

  if (!lead) return null

  const tabBtn = (id, label) => (
    <button
      onClick={() => setTab(id)}
      style={{
        padding: '7px 18px', borderRadius: '8px 8px 0 0',
        background: tab === id ? '#1e2535' : 'transparent',
        border: tab === id ? '1px solid #2d3748' : '1px solid transparent',
        borderBottom: tab === id ? '1px solid #1e2535' : '1px solid #2d3748',
        color: tab === id ? '#f1f5f9' : '#64748b',
        cursor: 'pointer', fontWeight: 700, fontSize: 12,
        marginBottom: -1,
      }}
    >{label}</button>
  )

  const isEdited = html !== origHtml || subject !== defaultSubject

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1100,
        background: 'rgba(0,0,0,0.8)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 16,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#131c2e',
          border: '1px solid #2d3748',
          borderRadius: 16,
          width: '100%',
          maxWidth: 820,
          maxHeight: '95vh',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 32px 80px rgba(0,0,0,0.7)',
          overflow: 'hidden',
        }}
      >
        {/* ─── Header ─── */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '18px 24px 14px',
          borderBottom: '1px solid #1e2535',
          flexShrink: 0,
        }}>
          <div>
            <h2 style={{ color: '#f1f5f9', fontWeight: 800, fontSize: 17, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Send size={16} style={{ color: '#60a5fa' }} />
              Email 2 Compose
              {isEdited && (
                <span style={{
                  fontSize: 10, fontWeight: 700, background: '#78350f', color: '#fde68a',
                  borderRadius: 20, padding: '2px 8px', letterSpacing: '0.5px',
                }}>EDITED</span>
              )}
            </h2>
            <p style={{ color: '#64748b', fontSize: 12, margin: '4px 0 0' }}>
              To: <a href={`mailto:${lead.email}`} style={{ color: '#60a5fa' }}>{lead.email}</a>
              <span style={{ margin: '0 6px', color: '#374151' }}>·</span>
              <span style={{ color: '#94a3b8' }}>{lead.business_name}</span>
            </p>
          </div>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#64748b',
            cursor: 'pointer', fontSize: 20, lineHeight: 1, padding: 4,
          }}>✕</button>
        </div>

        {/* ─── Editable subject line ─── */}
        <div style={{
          padding: '8px 24px',
          background: '#0f172a',
          borderBottom: '1px solid #1e2535',
          display: 'flex', alignItems: 'center', gap: 10,
          flexShrink: 0,
        }}>
          <span style={{ color: '#475569', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>Subject:</span>
          <input
            value={subject}
            onChange={e => setSubject(e.target.value)}
            style={{
              flex: 1, background: 'transparent', border: 'none',
              color: '#cbd5e1', fontSize: 13, fontWeight: 600,
              outline: 'none', padding: '2px 0',
              borderBottom: '1px solid transparent',
              transition: 'border-color 0.15s',
            }}
            onFocus={e => e.target.style.borderBottomColor = '#3b82f6'}
            onBlur={e => e.target.style.borderBottomColor = 'transparent'}
          />
          {subject !== defaultSubject && (
            <button
              onClick={() => setSubject(defaultSubject)}
              title="Reset subject"
              style={{
                background: 'none', border: 'none', color: '#64748b',
                cursor: 'pointer', fontSize: 11, padding: '2px 6px',
              }}
            >↩ Reset</button>
          )}
        </div>

        {/* ─── Tab bar ─── */}
        <div style={{
          padding: '12px 24px 0',
          background: '#0c1526',
          borderBottom: '1px solid #2d3748',
          display: 'flex', gap: 4,
          flexShrink: 0,
        }}>
          {tabBtn('preview', '👁 Preview')}
          {tabBtn('edit', '✏️ Edit HTML')}
          {isEdited && (
            <button
              onClick={handleReset}
              style={{
                marginLeft: 'auto', padding: '6px 14px', borderRadius: 8,
                background: 'none', border: '1px solid #374151',
                color: '#94a3b8', cursor: 'pointer', fontSize: 11, fontWeight: 600,
              }}
            >↩ Reset to original</button>
          )}
        </div>

        {/* ─── Tab content ─── */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, gap: 10, color: '#64748b' }}>
              <Loader size={20} style={{ animation: 'spin 1s linear infinite' }} />
              Loading email…
            </div>
          ) : error && !html ? (
            <div style={{ padding: 24, color: '#f87171', fontSize: 13 }}>{error}</div>
          ) : tab === 'preview' ? (
            /* ── Preview iframe ── */
            <div style={{ flex: 1, background: '#fff', overflow: 'auto' }}>
              <iframe
                key={html}  /* re-render when html changes */
                srcDoc={html}
                title="Email 2 Preview"
                style={{ width: '100%', height: '100%', minHeight: 480, border: 'none', display: 'block' }}
                sandbox="allow-same-origin"
              />
            </div>
          ) : (
            /* ── HTML editor ── */
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <div style={{
                padding: '8px 24px',
                background: '#0a1628',
                borderBottom: '1px solid #1e2535',
                fontSize: 11, color: '#475569',
                flexShrink: 0,
              }}>
                Edit the HTML below. Switch to Preview to see how it renders. Changes are sent when you click "Send Email 2".
              </div>
              <textarea
                value={html}
                onChange={e => setHtml(e.target.value)}
                spellCheck={false}
                style={{
                  flex: 1,
                  background: '#0a1628',
                  color: '#94d3a2',
                  border: 'none',
                  padding: '16px 24px',
                  fontSize: 12,
                  fontFamily: '"Fira Code", "Consolas", "Courier New", monospace',
                  lineHeight: 1.6,
                  resize: 'none',
                  outline: 'none',
                  overflowY: 'auto',
                  tabSize: 2,
                }}
              />
            </div>
          )}
        </div>

        {/* ─── Footer actions ─── */}
        <div style={{
          padding: '14px 24px',
          borderTop: '1px solid #1e2535',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          flexShrink: 0,
          background: '#0f172a',
        }}>
          <p style={{ color: '#374151', fontSize: 11, margin: 0 }}>
            {isEdited
              ? '⚠️ You have unsaved edits — your edited version will be sent.'
              : 'Auto-generated email will be sent as shown.'
            }
          </p>
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={onClose} style={{
              padding: '9px 18px', borderRadius: 8,
              background: 'none', border: '1px solid #2d3748',
              color: '#94a3b8', cursor: 'pointer', fontWeight: 600, fontSize: 13,
            }}>Cancel</button>

            {sent ? (
              <div style={{
                padding: '9px 20px', borderRadius: 8,
                background: '#0f2623', border: '1px solid #16a34a55',
                color: '#4ade80', fontWeight: 700, fontSize: 13,
                display: 'flex', alignItems: 'center', gap: 7,
              }}>
                <CheckCircle2 size={14} /> Sent!
              </div>
            ) : (
              <button
                onClick={handleSend}
                disabled={sending || loading || (!html && !!error)}
                style={{
                  padding: '9px 20px', borderRadius: 8,
                  background: sending ? '#1e3a5f' : 'linear-gradient(135deg,#2563eb,#1d4ed8)',
                  border: '1px solid #1e4080',
                  color: '#fff',
                  cursor: (sending || loading) ? 'wait' : 'pointer',
                  fontWeight: 700, fontSize: 13,
                  display: 'flex', alignItems: 'center', gap: 7,
                  boxShadow: sending ? 'none' : '0 4px 12px rgba(37,99,235,0.35)',
                  transition: 'all 0.2s',
                  opacity: (loading || (!html && !!error)) ? 0.5 : 1,
                }}
              >
                {sending
                  ? <><Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Sending…</>
                  : <><Send size={14} /> Send Email 2</>
                }
              </button>
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && !loading && (
          <div style={{
            background: '#3f1515', borderTop: '1px solid #7f1d1d',
            padding: '10px 24px', color: '#fca5a5', fontSize: 12,
            flexShrink: 0,
          }}>
            {error}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Converted Table ────────────────────────────────────────────────────────
function ConvertedTable({ leads, total, page, setPage, onDelete, onPreview, onCompose, loading }) {
  const PAGE_SIZE = 25
  const totalPages = Math.ceil(total / PAGE_SIZE)

  if (!loading && leads.length === 0) {
    return (
      <div style={{
        textAlign: 'center', padding: '60px 0',
        color: '#64748b',
      }}>
        <CheckCircle2 size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
        <p style={{ fontSize: 16, fontWeight: 600 }}>No converted leads yet</p>
        <p style={{ fontSize: 13, marginTop: 6 }}>
          When a lead replies positively, they'll appear here.
        </p>
      </div>
    )
  }

  return (
    <div>
      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #2d3748' }}>
              {['Business', 'Email', 'Website', 'Reply Preview', 'Type', 'Replied At', ''].map(h => (
                <th key={h} style={{
                  padding: '10px 14px', textAlign: 'left',
                  color: '#64748b', fontWeight: 600, fontSize: 11,
                  textTransform: 'uppercase', letterSpacing: '0.7px',
                  whiteSpace: 'nowrap',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} style={{ padding: '12px 14px' }}>
                      <div style={{
                        height: 14, borderRadius: 4,
                        background: '#2d3748',
                        width: j === 3 ? 200 : 80,
                        animation: 'pulse 1.5s infinite',
                      }} />
                    </td>
                  ))}
                </tr>
              ))
              : leads.map(lead => (
                <tr
                  key={lead.id}
                  style={{
                    borderBottom: '1px solid #1e2535',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = '#1a2540'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '12px 14px', fontWeight: 600, color: '#e2e8f0' }}>
                    {lead.business_name}
                  </td>
                  <td style={{ padding: '12px 14px', color: '#94a3b8' }}>
                    <a href={`mailto:${lead.email}`} style={{ color: '#60a5fa', textDecoration: 'none' }}>
                      {lead.email}
                    </a>
                  </td>
                  <td style={{ padding: '12px 14px' }}>
                    {lead.website
                      ? <a href={lead.website} target="_blank" rel="noreferrer"
                           style={{ color: '#60a5fa', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {lead.website.replace(/^https?:\/\//, '')}
                          </span>
                          <ExternalLink size={11} />
                        </a>
                      : <span style={{ color: '#4b5563' }}>—</span>
                    }
                  </td>
                  {/* Reply preview — click to open full modal */}
                  <td style={{ padding: '12px 14px', maxWidth: 220 }}>
                    {lead.reply_snippet
                      ? (
                        <button
                          onClick={() => onPreview(lead)}
                          title="Click to view full reply"
                          style={{
                            background: 'none', border: 'none', cursor: 'pointer',
                            textAlign: 'left', padding: 0, width: '100%',
                          }}
                        >
                          <span style={{
                            display: 'block', color: '#7dd3fc', fontSize: 12,
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            maxWidth: 200,
                            textDecoration: 'underline',
                            textDecorationStyle: 'dotted',
                            textUnderlineOffset: 3,
                          }}>
                            "{lead.reply_snippet}"
                          </span>
                        </button>
                      )
                      : <span style={{ color: '#4b5563' }}>—</span>
                    }
                  </td>
                  <td style={{ padding: '12px 14px' }}>
                    <Badge type={lead.reply_type || lead.status} />
                  </td>
                  <td style={{ padding: '12px 14px', color: '#64748b', whiteSpace: 'nowrap' }}>
                    {lead.replied_at
                      ? new Date(lead.replied_at).toLocaleDateString('en-IN', {
                          day: '2-digit', month: 'short', year: 'numeric',
                          hour: '2-digit', minute: '2-digit',
                        })
                      : '—'
                    }
                  </td>
                  <td style={{ padding: '12px 14px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {/* View full reply */}
                      <button
                        onClick={() => onPreview(lead)}
                        title="View received reply"
                        style={{
                          padding: '5px 8px', borderRadius: 6,
                          background: '#1a2540', color: '#7dd3fc',
                          border: '1px solid #1e3a5f', cursor: 'pointer',
                          display: 'flex', alignItems: 'center',
                        }}
                      >
                        <Eye size={13} />
                      </button>
                      {/* Compose Email 2 */}
                      <button
                        onClick={() => onCompose(lead)}
                        title="Preview & send Email 2 (audit + pricing)"
                        style={{
                          padding: '5px 8px', borderRadius: 6,
                          background: 'rgba(37,99,235,0.18)', color: '#60a5fa',
                          border: '1px solid #1e4080', cursor: 'pointer',
                          display: 'flex', alignItems: 'center', gap: 4,
                          fontSize: 11, fontWeight: 600,
                        }}
                      >
                        <Send size={12} /> Email 2
                      </button>
                      {/* Simple mailto fallback */}
                      <a
                        href={`mailto:${lead.email}`}
                        title="Open in mail client"
                        style={{
                          padding: '5px 8px', borderRadius: 6,
                          background: '#1e3a5f', color: '#60a5fa',
                          border: '1px solid #1e4080', textDecoration: 'none',
                          display: 'flex', alignItems: 'center',
                        }}
                      >
                        <Mail size={13} />
                      </a>
                      {/* Delete */}
                      <button
                        onClick={() => onDelete(lead.id, lead.business_name)}
                        title="Delete lead permanently"
                        style={{
                          padding: '5px 8px', borderRadius: 6,
                          background: '#3f1515', color: '#f87171',
                          border: '1px solid #7f1d1d', cursor: 'pointer',
                          display: 'flex', alignItems: 'center',
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 0 0', justifyContent: 'flex-end' }}>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            style={{
              padding: '6px 10px', borderRadius: 6, background: '#1e2535',
              border: '1px solid #2d3748', color: page === 1 ? '#4b5563' : '#94a3b8',
              cursor: page === 1 ? 'default' : 'pointer',
            }}
          >
            <ChevronLeft size={14} />
          </button>
          <span style={{ color: '#64748b', fontSize: 12 }}>
            Page {page} of {totalPages} ({total} total)
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            style={{
              padding: '6px 10px', borderRadius: 6, background: '#1e2535',
              border: '1px solid #2d3748', color: page === totalPages ? '#4b5563' : '#94a3b8',
              cursor: page === totalPages ? 'default' : 'pointer',
            }}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

// ── Sync Panel ─────────────────────────────────────────────────────────────
function SyncPanel({ onSync, syncing, lastSynced, syncResult }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Action card */}
      <div style={{
        background: 'var(--surface-card, #1e2535)',
        border: '1px solid var(--surface-border, #2d3748)',
        borderRadius: 14, padding: 28,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 16,
      }}>
        <div>
          <h2 style={{ color: '#f1f5f9', fontWeight: 700, fontSize: 16, margin: 0 }}>
            Sync Email Inbox
          </h2>
          <p style={{ color: '#64748b', fontSize: 13, marginTop: 6 }}>
            Scans <strong style={{ color: '#94a3b8' }}>INBOX + Spam</strong> on
            {' '}<code style={{ color: '#60a5fa', background: '#0f172a', padding: '2px 6px', borderRadius: 4 }}>
              imap.hostinger.com:993
            </code>
            {' '}for unseen replies.
          </p>
          {lastSynced && (
            <p style={{ color: '#4b5563', fontSize: 12, marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Clock size={11} />
              Last synced: {lastSynced.toLocaleTimeString('en-IN')}
            </p>
          )}
        </div>
        <button
          onClick={onSync}
          disabled={syncing}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '12px 28px', borderRadius: 10,
            background: syncing ? '#1e3a5f' : 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
            color: '#fff', border: 'none', cursor: syncing ? 'wait' : 'pointer',
            fontWeight: 700, fontSize: 14,
            boxShadow: syncing ? 'none' : '0 4px 14px rgba(37,99,235,0.35)',
            transition: 'all 0.2s',
          }}
        >
          <RefreshCw size={16} style={{ animation: syncing ? 'spin 1s linear infinite' : 'none' }} />
          {syncing ? 'Syncing…' : 'Sync Inbox Now'}
        </button>
      </div>

      {/* Sync result */}
      {syncResult && (
        <div style={{
          background: '#0f2623', border: '1px solid #16a34a55',
          borderRadius: 12, padding: '18px 22px',
        }}>
          <p style={{ color: '#4ade80', fontWeight: 700, fontSize: 13, margin: '0 0 6px' }}>
            ✅ Sync complete
          </p>
          <p style={{ color: '#4b5563', fontSize: 11, margin: '0 0 14px' }}>
            Note: "Newly Converted" = emails classified positive AND matched a DB lead.
            The Converted Leads card (top-left) shows your <em>current total</em> in the database.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
            {[
              { label: 'Emails fetched',    value: syncResult.fetched,     color: '#60a5fa', tip: 'Total unseen emails downloaded from IMAP' },
              { label: 'Newly Converted',   value: syncResult.positive,    color: '#4ade80', tip: 'Positive replies that matched a lead → now Converted' },
              { label: 'Leads Deleted',     value: syncResult.deleted,     color: '#f87171', tip: 'Bounce / STOP replies → lead removed from DB' },
              { label: 'Soft Bounce',       value: syncResult.soft_bounce, color: '#fb923c', tip: 'Out of office / temp unavailable → flagged only' },
              { label: 'No Match / Other',  value: syncResult.other,       color: '#94a3b8', tip: 'Email did not match any lead, or unclassified' },
              { label: 'Errors',            value: syncResult.errors,      color: '#fbbf24', tip: 'Processing errors during this sync' },
            ].map(({ label, value, color, tip }) => (
              <div key={label} style={{
                background: '#0a1628', borderRadius: 8, padding: '10px 14px',
                cursor: 'default',
              }} title={tip}>
                <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* What happens section */}
      <div style={{
        background: 'var(--surface-card, #1e2535)',
        border: '1px solid var(--surface-border, #2d3748)',
        borderRadius: 14, padding: '22px 28px',
      }}>
        <h3 style={{ color: '#94a3b8', fontWeight: 700, fontSize: 13,
          textTransform: 'uppercase', letterSpacing: '0.7px', margin: '0 0 16px' }}>
          What happens during sync
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { icon: CheckCircle2, color: '#4ade80', label: 'YES / Interested', desc: 'Lead marked as Converted → appears in Converted Leads tab' },
            { icon: XCircle,      color: '#f87171', label: 'STOP / Unsubscribe', desc: 'Lead permanently deleted from database' },
            { icon: XCircle,      color: '#f87171', label: 'Hard Bounce (550, invalid address, no such user)', desc: 'Lead permanently deleted from database' },
            { icon: AlertTriangle,color: '#fb923c', label: 'Out of Office / Soft Bounce', desc: 'Lead flagged only — NOT deleted. Email may be valid.' },
            { icon: Mail,         color: '#94a3b8', label: 'Other replies', desc: 'Marked as read in inbox — no action taken on lead' },
          ].map(({ icon: Icon, color, label, desc }) => (
            <div key={label} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
              <Icon size={16} style={{ color, flexShrink: 0, marginTop: 2 }} />
              <div>
                <span style={{ color: '#e2e8f0', fontWeight: 600, fontSize: 13 }}>{label}</span>
                <span style={{ color: '#64748b', fontSize: 12, marginLeft: 6 }}>— {desc}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function InboxPage() {
  const [activeTab, setActiveTab] = useState('converted')
  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loadingLeads, setLoadingLeads] = useState(false)

  const [stats, setStats] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [lastSynced, setLastSynced] = useState(null)
  const [syncResult, setSyncResult] = useState(null)
  const [error, setError] = useState('')

  // Preview modal state
  const [previewLead, setPreviewLead] = useState(null)
  const [reclassifying, setReclassifying] = useState(false)

  // Email 2 compose modal state
  const [composeLead, setComposeLead] = useState(null)

  // ── Fetch stats ──
  const fetchStats = useCallback(async () => {
    try {
      const s = await apiFetch('/replies/stats')
      setStats(s)
    } catch { /* quiet */ }
  }, [])

  // ── Fetch converted leads ──
  const fetchLeads = useCallback(async () => {
    setLoadingLeads(true)
    setError('')
    try {
      const data = await apiFetch(`/replies/converted?page=${page}&page_size=25`)
      setLeads(data.items)
      setTotal(data.total)
    } catch (e) {
      setError('Failed to load converted leads.')
    } finally {
      setLoadingLeads(false)
    }
  }, [page])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => {
    if (activeTab === 'converted') fetchLeads()
  }, [activeTab, fetchLeads])

  // ── Sync inbox ──
  const handleSync = async () => {
    setSyncing(true)
    setSyncResult(null)
    setError('')
    try {
      const result = await apiFetch('/replies/check-now', { method: 'POST' })
      setSyncResult(result)
      setLastSynced(new Date())
      // Refresh stats + leads after sync
      await fetchStats()
      if (activeTab === 'converted') await fetchLeads()
    } catch (e) {
      setError('Sync failed. Check that IMAP is enabled on your Hostinger account.')
    } finally {
      setSyncing(false)
    }
  }

  // ── Delete lead ──
  const handleDelete = async (leadId, name) => {
    if (!confirm(`Delete "${name}" permanently? This cannot be undone.`)) return
    try {
      await apiFetch(`/leads/${leadId}`, { method: 'DELETE' })
      setLeads(prev => prev.filter(l => l.id !== leadId))
      setTotal(prev => prev - 1)
      await fetchStats()
    } catch {
      alert('Failed to delete lead.')
    }
  }

  // ── Reclassify: move from Converted → Other ──
  const handleReclassify = async (lead) => {
    setReclassifying(true)
    try {
      await apiFetch(`/replies/reclassify/${lead.id}`, { method: 'PATCH' })
      // Remove from list immediately
      setLeads(prev => prev.filter(l => l.id !== lead.id))
      setTotal(prev => prev - 1)
      setPreviewLead(null)
      await fetchStats()
    } catch (e) {
      alert('Failed to reclassify lead: ' + e.message)
    } finally {
      setReclassifying(false)
    }
  }

  const tabs = [
    { id: 'converted', label: 'Converted Leads', icon: TrendingUp, count: stats?.converted },
    { id: 'sync',      label: 'Check Replies',   icon: RefreshCw,  count: null },
  ]

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1100, margin: '0 auto' }}>
      {/* Reply preview modal */}
      {previewLead && (
        <ReplyModal
          lead={previewLead}
          onClose={() => setPreviewLead(null)}
          onReclassify={handleReclassify}
          reclassifying={reclassifying}
        />
      )}

      {/* Email 2 compose/preview modal */}
      {composeLead && (
        <Email2Modal
          lead={composeLead}
          onClose={() => setComposeLead(null)}
        />
      )}

      {/* ── Page header ── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: '#16a34a22', border: '1px solid #16a34a55',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Inbox size={20} style={{ color: '#4ade80' }} />
          </div>
          <div>
            <h1 style={{ color: '#f1f5f9', fontWeight: 800, fontSize: 22, margin: 0 }}>
              Reply Inbox
            </h1>
            <p style={{ color: '#64748b', fontSize: 13, margin: 0 }}>
              Track email replies — convert hot leads, clean invalid addresses
            </p>
          </div>
        </div>
      </div>

      {/* ── Stat cards ── */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 28 }}>
        <StatCard
          icon={CheckCircle2} label="Converted Leads" color="#16a34a"
          value={stats?.converted ?? '—'}
          sub="Current total in database"
          tooltip="Leads currently marked as Converted in the database (cumulative)"
        />
        <StatCard
          icon={AlertTriangle} label="Soft Bounces" color="#d97706"
          value={stats?.soft_bounce ?? '—'}
          sub="Out of office / temp"
          tooltip="Flagged leads — email is valid but person is unavailable"
        />
        <StatCard
          icon={Trash2} label="Deleted Today" color="#dc2626"
          value={stats?.deleted_today ?? '—'}
          sub="Bounce / STOP purged"
          tooltip="Leads permanently removed today due to hard bounce or STOP request"
        />
      </div>

      {/* ── Why numbers differ ── notice ── */}
      <div style={{
        background: '#0f172a',
        border: '1px solid #1e3a5f',
        borderRadius: 10,
        padding: '10px 16px',
        marginBottom: 20,
        display: 'flex', alignItems: 'flex-start', gap: 10,
        fontSize: 12, color: '#64748b',
      }}>
        <Info size={14} style={{ color: '#3b82f6', flexShrink: 0, marginTop: 1 }} />
        <span>
          <strong style={{ color: '#60a5fa' }}>Why do the numbers differ?</strong>{' '}
          The cards above show your <em>current database totals</em>. The sync result
          shows what happened <em>during that sync session only</em> — some positive emails may
          have no matching lead (already deleted or never uploaded), so they count as "No Match / Other".
        </span>
      </div>

      {/* ── Tabs ── */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #2d3748', paddingBottom: 0 }}>
        {tabs.map(({ id, label, icon: Icon, count }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 7,
              padding: '10px 18px',
              background: 'none', border: 'none',
              borderBottom: activeTab === id ? '2px solid #2563eb' : '2px solid transparent',
              color: activeTab === id ? '#60a5fa' : '#64748b',
              fontWeight: activeTab === id ? 700 : 500,
              fontSize: 13, cursor: 'pointer',
              transition: 'all 0.15s',
              marginBottom: -1,
            }}
          >
            <Icon size={14} />
            {label}
            {count != null && (
              <span style={{
                padding: '1px 7px', borderRadius: 20,
                background: activeTab === id ? '#1e3a5f' : '#1e2535',
                color: activeTab === id ? '#60a5fa' : '#64748b',
                fontSize: 11, fontWeight: 700,
              }}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div style={{
          background: '#3f1515', border: '1px solid #7f1d1d',
          borderRadius: 10, padding: '12px 18px',
          color: '#fca5a5', fontSize: 13, marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <XCircle size={15} />
          {error}
        </div>
      )}

      {/* ── Tab content ── */}
      <div style={{
        background: 'var(--surface-card, #1e2535)',
        border: '1px solid var(--surface-border, #2d3748)',
        borderRadius: 14, padding: 24,
      }}>
        {activeTab === 'converted' && (
          <ConvertedTable
            leads={leads}
            total={total}
            page={page}
            setPage={setPage}
            onDelete={handleDelete}
            onPreview={setPreviewLead}
            onCompose={setComposeLead}
            loading={loadingLeads}
          />
        )}

        {activeTab === 'sync' && (
          <SyncPanel
            onSync={handleSync}
            syncing={syncing}
            lastSynced={lastSynced}
            syncResult={syncResult}
          />
        )}
      </div>

      {/* Spin animation */}
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
    </div>
  )
}
