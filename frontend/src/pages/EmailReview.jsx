import { useState, useEffect, useCallback } from 'react'
import { Mail, RefreshCw, Check, X, AlertTriangle, Inbox, ExternalLink, Loader2, ChevronDown } from 'lucide-react'
import {
  getEmailCorrections, scanEmails, acceptCorrection,
  dismissCorrection, getEmailReviewStats
} from '../api/client'

// ── helper ────────────────────────────────────────────────────────────────────
const timeAgo = (iso) => {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return `${Math.round(diff)}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

const SOURCE_LABELS = {
  homepage_text:   'Homepage text',
  homepage_mailto: 'Homepage mailto link',
  contact_text:    'Contact page text',
  contact_mailto:  'Contact page mailto',
  website:         'Website',
}

// ── Status pill ───────────────────────────────────────────────────────────────
function StatusPill({ status }) {
  const styles = {
    pending:   { bg: '#fef3c7', color: '#92400e', label: 'Pending Review' },
    accepted:  { bg: '#dcfce7', color: '#166534', label: 'Accepted' },
    dismissed: { bg: '#f1f5f9', color: '#475569', label: 'Dismissed' },
  }
  const s = styles[status] || styles.dismissed
  return (
    <span style={{
      background: s.bg, color: s.color,
      fontSize: 11, fontWeight: 700, padding: '2px 10px',
      borderRadius: 20, letterSpacing: '0.5px', whiteSpace: 'nowrap',
    }}>
      {s.label}
    </span>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────
function EmptyState({ filter, onScan, scanning }) {
  return (
    <div style={{
      textAlign: 'center', padding: '72px 24px',
      color: 'var(--color-text-muted)',
    }}>
      <Inbox size={52} strokeWidth={1.2} style={{ margin: '0 auto 16px', opacity: 0.35 }} />
      <p style={{ fontSize: 18, fontWeight: 600, color: 'var(--color-text)', marginBottom: 8 }}>
        {filter === 'pending' ? 'No pending email corrections' : 'No corrections found'}
      </p>
      <p style={{ fontSize: 13, maxWidth: 380, margin: '0 auto 24px' }}>
        {filter === 'pending'
          ? 'Run a scan to check all leads for domain-matched email addresses.'
          : 'Change the filter above to see accepted or dismissed corrections.'}
      </p>
      {filter === 'pending' && (
        <button
          className="btn-primary"
          onClick={onScan}
          disabled={scanning}
          style={{ gap: 8 }}
        >
          {scanning
            ? <><Loader2 size={15} className="spin" /> Scanning…</>
            : <><RefreshCw size={15} /> Scan All Leads Now</>}
        </button>
      )}
    </div>
  )
}

// ── Correction row ────────────────────────────────────────────────────────────
function CorrectionRow({ item, onAccept, onDismiss, acting }) {
  return (
    <div style={{
      background: 'var(--color-surface-card)',
      border: '1px solid var(--color-surface-border)',
      borderRadius: 12,
      padding: '16px 20px',
      display: 'grid',
      gridTemplateColumns: '1fr auto',
      gap: 12,
      alignItems: 'start',
    }}>
      {/* Left: info */}
      <div style={{ minWidth: 0 }}>
        {/* Row 1: business name + status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text)' }}>
            {item.business_name}
          </span>
          <StatusPill status={item.status} />
          {item.website && (
            <a
              href={item.website}
              target="_blank"
              rel="noreferrer"
              style={{ color: 'var(--color-brand)', fontSize: 11, display: 'flex', alignItems: 'center', gap: 3 }}
            >
              <ExternalLink size={11} /> {item.website.replace(/^https?:\/\/(www\.)?/, '')}
            </a>
          )}
        </div>

        {/* Row 2: Email comparison */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          background: 'var(--color-surface)', borderRadius: 8, padding: '10px 14px',
          border: '1px solid var(--color-surface-border)', marginBottom: 8,
        }}>
          {/* Old */}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', fontWeight: 600, marginBottom: 2, letterSpacing: '0.5px', textTransform: 'uppercase' }}>
              Current Email in DB
            </div>
            <div style={{
              fontSize: 13, color: '#b91c1c', fontFamily: 'monospace',
              background: '#fef2f2', padding: '3px 8px', borderRadius: 6,
              border: '1px solid #fecaca',
            }}>
              {item.old_email}
            </div>
          </div>

          <div style={{ color: 'var(--color-text-muted)', fontSize: 18, fontWeight: 300 }}>→</div>

          {/* New */}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', fontWeight: 600, marginBottom: 2, letterSpacing: '0.5px', textTransform: 'uppercase' }}>
              Found on Website
            </div>
            <div style={{
              fontSize: 13, color: '#166534', fontFamily: 'monospace',
              background: '#dcfce7', padding: '3px 8px', borderRadius: 6,
              border: '1px solid #bbf7d0',
            }}>
              {item.new_email}
            </div>
          </div>
        </div>

        {/* Row 3: meta */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11, color: 'var(--color-text-muted)' }}>
          <span>Source: <strong>{SOURCE_LABELS[item.source] || item.source}</strong></span>
          <span>Detected: {timeAgo(item.detected_at)}</span>
          {item.reviewed_at && <span>Reviewed: {timeAgo(item.reviewed_at)}</span>}
          {item.lead_status && (
            <span>Lead status: <strong style={{ color: 'var(--color-brand)' }}>{item.lead_status}</strong></span>
          )}
        </div>
      </div>

      {/* Right: action buttons (only for pending) */}
      {item.status === 'pending' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 120 }}>
          <button
            className="btn-primary"
            onClick={() => onAccept(item.id)}
            disabled={acting === item.id}
            style={{ fontSize: 12, padding: '7px 14px', gap: 6 }}
          >
            {acting === item.id
              ? <Loader2 size={13} className="spin" />
              : <Check size={13} />}
            Accept
          </button>
          <button
            onClick={() => onDismiss(item.id)}
            disabled={acting === item.id}
            style={{
              fontSize: 12, padding: '7px 14px',
              background: 'transparent',
              border: '1px solid var(--color-surface-border)',
              borderRadius: 8, color: 'var(--color-text-muted)',
              cursor: 'pointer', display: 'flex', alignItems: 'center',gap: 6,
              justifyContent: 'center',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#fef2f2'; e.currentTarget.style.borderColor = '#fca5a5'; e.currentTarget.style.color = '#b91c1c' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'var(--color-surface-border)'; e.currentTarget.style.color = 'var(--color-text-muted)' }}
          >
            <X size={13} /> Dismiss
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function EmailReview() {
  const [items, setItems]       = useState([])
  const [stats, setStats]       = useState({ pending: 0, accepted: 0, dismissed: 0, total: 0 })
  const [filter, setFilter]     = useState('pending')
  const [loading, setLoading]   = useState(false)
  const [scanning, setScanning] = useState(false)
  const [acting, setActing]     = useState(null)
  const [toast, setToast]       = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const loadStats = useCallback(async () => {
    try {
      const r = await getEmailReviewStats()
      setStats(r.data)
    } catch {}
  }, [])

  const loadItems = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getEmailCorrections(filter)
      setItems(r.data.items || [])
    } catch (e) {
      showToast('Failed to load corrections.', 'error')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    loadStats()
    loadItems()
  }, [loadStats, loadItems])

  const handleScan = async () => {
    const onlyUnscanned = window.confirm("Do you want to scan ONLY the leads that have never been scanned?\n\nClick OK for Unscanned only.\nClick Cancel to scan ALL leads in the database.")
    setScanning(true)
    try {
      await scanEmails(onlyUnscanned)
      showToast('Email scan started! Results will appear within a few minutes.')
      // Poll for results after 5s
      setTimeout(() => { loadItems(); loadStats() }, 5000)
    } catch (e) {
      showToast('Scan failed. Check backend logs.', 'error')
    } finally {
      setScanning(false)
    }
  }

  const handleAccept = async (id) => {
    setActing(id)
    try {
      const r = await acceptCorrection(id)
      showToast(`Email updated. Lead reset to NEW for fresh outreach.`)
      loadItems()
      loadStats()
    } catch (e) {
      showToast(e?.response?.data?.detail || 'Accept failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  const handleDismiss = async (id) => {
    setActing(id)
    try {
      await dismissCorrection(id)
      showToast('Dismissed — lead email unchanged.')
      loadItems()
      loadStats()
    } catch (e) {
      showToast(e?.response?.data?.detail || 'Dismiss failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 900, margin: '0 auto' }}>

      {/* ── Toast ── */}
      {toast && (
        <div style={{
          position: 'fixed', top: 20, right: 24, zIndex: 9999,
          background: toast.type === 'error' ? '#b91c1c' : '#16a34a',
          color: '#fff', borderRadius: 10, padding: '12px 20px',
          fontSize: 13, fontWeight: 600, boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
          animation: 'fadeIn 0.2s ease',
        }}>
          {toast.msg}
        </div>
      )}

      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: 'linear-gradient(135deg, #2563eb, #7c3aed)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Mail size={18} color="#fff" />
            </div>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: 'var(--color-text)', margin: 0 }}>
              Email Review
            </h1>
            {stats.pending > 0 && (
              <span style={{
                background: '#dc2626', color: '#fff',
                fontSize: 11, fontWeight: 800, padding: '2px 8px',
                borderRadius: 20, marginLeft: 4,
              }}>
                {stats.pending}
              </span>
            )}
          </div>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
            Review auto-detected email mismatches. Accept to update the lead and move to <strong>NEW</strong> for re-audit.
          </p>
        </div>

        {/* Scan button */}
        <button
          className="btn-primary"
          onClick={handleScan}
          disabled={scanning}
          style={{ gap: 8, whiteSpace: 'nowrap' }}
        >
          {scanning
            ? <><Loader2 size={15} className="spin" /> Scanning All Leads…</>
            : <><RefreshCw size={15} /> Scan All Leads</>}
        </button>
      </div>

      {/* ── Stats cards ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: 'Pending Review', value: stats.pending,   color: '#d97706', bg: '#fef3c7' },
          { label: 'Accepted',       value: stats.accepted,  color: '#16a34a', bg: '#dcfce7' },
          { label: 'Dismissed',      value: stats.dismissed, color: '#64748b', bg: '#f1f5f9' },
        ].map(({ label, value, color, bg }) => (
          <div key={label} style={{
            background: 'var(--color-surface-card)',
            border: '1px solid var(--color-surface-border)',
            borderRadius: 12, padding: '14px 18px',
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <div style={{ width: 40, height: 40, borderRadius: 10, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, fontWeight: 800, color }} >{value}</div>
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 600 }}>{label}</span>
          </div>
        ))}
      </div>

      {/* ── Filter tabs ── */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 20 }}>
        {['pending', 'accepted', 'dismissed', 'all'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
              cursor: 'pointer', border: 'none',
              background: filter === f ? 'var(--color-brand)' : 'var(--color-surface-card)',
              color: filter === f ? '#fff' : 'var(--color-text-muted)',
              transition: 'all 0.15s',
              textTransform: 'capitalize',
            }}
          >
            {f}
          </button>
        ))}
        <button
          onClick={() => { loadItems(); loadStats() }}
          style={{
            marginLeft: 'auto', background: 'transparent',
            border: '1px solid var(--color-surface-border)',
            borderRadius: 8, padding: '6px 12px',
            cursor: 'pointer', color: 'var(--color-text-muted)', fontSize: 12,
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-muted)' }}>
          <Loader2 size={28} className="spin" style={{ margin: '0 auto 12px' }} />
          <p style={{ fontSize: 13 }}>Loading corrections…</p>
        </div>
      ) : items.length === 0 ? (
        <EmptyState filter={filter} onScan={handleScan} scanning={scanning} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map(item => (
            <CorrectionRow
              key={item.id}
              item={item}
              onAccept={handleAccept}
              onDismiss={handleDismiss}
              acting={acting}
            />
          ))}
        </div>
      )}

      {/* ── Info box ── */}
      <div style={{
        marginTop: 32, background: 'var(--color-surface-card)',
        border: '1px solid var(--color-surface-border)',
        borderRadius: 12, padding: '16px 20px',
        display: 'flex', gap: 14, alignItems: 'flex-start',
      }}>
        <AlertTriangle size={18} color="#d97706" style={{ marginTop: 2, flexShrink: 0 }} />
        <div>
          <p style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-text)', margin: '0 0 4px' }}>
            How this works
          </p>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0, lineHeight: 1.7 }}>
            <strong>Scan</strong> crawls every lead's website and looks for email addresses that match the lead's own domain (e.g. <code>@vertexindustries.es</code>), ignoring free providers (Gmail, Webador, Wix, etc.).<br />
            <strong>Accept</strong> — updates the lead's email to the domain-matched address and moves the lead to <strong>NEW</strong> so it can be re-audited and re-emailed fresh.<br />
            <strong>Dismiss</strong> — keeps the existing email and marks the suggestion as reviewed.
          </p>
        </div>
      </div>

      <style>{`
        .spin { animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  )
}
