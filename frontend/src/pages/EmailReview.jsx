import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, Check, ExternalLink, Inbox, Loader2, MailCheck,
  RefreshCw, ShieldAlert, ShieldCheck, X,
} from 'lucide-react'
import {
  acceptCorrection, dismissCorrection, getEmailCorrections,
  getEmailReviewStats, scanEmails,
} from '../api/client'
import EmailVerificationAudit from '../components/EmailVerificationAudit'

const SOURCE_LABELS = {
  homepage_text: 'Homepage text',
  homepage_mailto: 'Homepage mailto link',
  contact_text: 'Contact page text',
  contact_mailto: 'Contact page mailto',
  website: 'Website',
}

const ASSOCIATION_LABELS = {
  matched: 'Business matched',
  approved: 'Manually approved',
  mismatched_source: 'Source mismatch',
  invalid_format: 'Invalid association',
  external_domain_review: 'External domain review',
  pending_review: 'Pending association review',
  unverified_association: 'Association unconfirmed',
  unverified: 'Association unconfirmed',
}

const VERIFICATION_LABELS = {
  valid: 'Routeable (syntax and MX)',
  invalid: 'Invalid address',
  disposable: 'Disposable address',
  catch_all: 'Catch-all domain',
  risky: 'Risky or typo',
  not_found: 'Mailbox not found',
  timeout: 'Verification timeout',
  error: 'Verification error',
  unverified: 'Unverified mailbox',
}

function timeAgo(value) {
  if (!value) return 'Timestamp unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Timestamp unavailable'
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return Math.round(seconds) + 's ago'
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ago'
  if (seconds < 86400) return Math.round(seconds / 3600) + 'h ago'
  return Math.round(seconds / 86400) + 'd ago'
}

function CorrectionStatus({ status }) {
  const tone = {
    pending: 'border-amber-800/60 bg-amber-950/50 text-amber-300',
    accepted: 'border-emerald-800/60 bg-emerald-950/50 text-emerald-300',
    dismissed: 'border-slate-700 bg-slate-800/70 text-slate-300',
  }[status] || 'border-slate-700 bg-slate-800/70 text-slate-300'

  return <span className={'badge border ' + tone}>{status === 'pending' ? 'Pending review' : status}</span>
}

function EvidenceBadge({ tone = 'slate', children }) {
  const tones = {
    emerald: 'border-emerald-800/60 bg-emerald-950/50 text-emerald-300',
    amber: 'border-amber-800/60 bg-amber-950/50 text-amber-300',
    rose: 'border-rose-800/60 bg-rose-950/50 text-rose-300',
    slate: 'border-slate-700 bg-slate-800/70 text-slate-300',
  }
  return <span className={'inline-flex w-fit items-center rounded-full border px-2 py-1 text-[11px] font-semibold ' + tones[tone]}>{children}</span>
}

function ReviewSafety({ item }) {
  const verificationTone = item.verification_status === 'valid' ? 'emerald'
    : ['invalid', 'disposable', 'not_found'].includes(item.verification_status) ? 'rose' : 'amber'
  const associationTone = ['matched', 'approved'].includes(item.association_status) ? 'emerald'
    : ['mismatched_source', 'invalid_format'].includes(item.association_status) ? 'rose' : 'amber'
  const restrictedByReply = ['stop', 'bounce', 'soft_bounce'].includes(item.reply_type)

  return (
    <div className="mt-3 grid gap-2 border-t border-slate-800 pt-3 sm:grid-cols-3">
      <div>
        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Verification</p>
        <EvidenceBadge tone={verificationTone}>{VERIFICATION_LABELS[item.verification_status] || item.verification_status || 'Unverified mailbox'}</EvidenceBadge>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
          {item.mailbox_confirmed ? 'Mailbox confirmation recorded.' : 'Routeability is not mailbox confirmation.'}
        </p>
      </div>
      <div>
        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Business association</p>
        <EvidenceBadge tone={associationTone}>{ASSOCIATION_LABELS[item.association_status] || item.association_status || 'Association unconfirmed'}</EvidenceBadge>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.association_reason || 'No association reason recorded.'}</p>
      </div>
      <div>
        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">Campaign safety</p>
        {item.is_quarantined ? (
          <>
            <EvidenceBadge tone="rose">Quarantined</EvidenceBadge>
            <p className="mt-1 text-[11px] leading-relaxed text-rose-300">{item.quarantine_reason || 'Existing quarantine restriction.'}</p>
          </>
        ) : restrictedByReply ? (
          <>
            <EvidenceBadge tone="rose">Existing {item.reply_type} restriction</EvidenceBadge>
            <p className="mt-1 text-[11px] leading-relaxed text-rose-300">The existing reply restriction remains in force.</p>
          </>
        ) : (
          <>
            <EvidenceBadge tone="slate">No extra restriction recorded</EvidenceBadge>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Eligibility is still enforced by the existing campaign gate.</p>
          </>
        )}
      </div>
    </div>
  )
}

function CorrectionCard({ item, acting, onAccept, onDismiss }) {
  const evidenceUrl = item.email_source_url || item.website
  const sourceLabel = SOURCE_LABELS[item.email_source_type || item.source] || item.email_source_type || item.source || 'Website evidence'

  return (
    <article className="card border-slate-800 bg-slate-900/50 p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-sm font-bold text-white">{item.business_name || 'Unknown business'}</h2>
            <CorrectionStatus status={item.status} />
            {item.email_domain_match === true && <EvidenceBadge tone="emerald">Domain matched</EvidenceBadge>}
            {item.email_domain_match === false && <EvidenceBadge tone="rose">Domain mismatch</EvidenceBadge>}
          </div>

          <div className="mt-3 grid gap-2 rounded-lg border border-slate-800 bg-slate-950/70 p-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Current address</p>
              <p className="mt-1 break-all font-mono text-xs text-rose-300">{item.old_email || 'Not recorded'}</p>
            </div>
            <span className="hidden text-center text-slate-600 sm:block">to</span>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Suggested website address</p>
              <p className="mt-1 break-all font-mono text-xs text-emerald-300">{item.new_email || 'Not recorded'}</p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span>Evidence: <strong className="font-medium text-slate-300">{sourceLabel}</strong></span>
            <span>Detected {timeAgo(item.detected_at)}</span>
            {item.reviewed_at && <span>Reviewed {timeAgo(item.reviewed_at)}</span>}
            {evidenceUrl && (
              <a href={evidenceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300">
                Open evidence <ExternalLink size={11} />
              </a>
            )}
          </div>

          <ReviewSafety item={item} />
        </div>

        {item.status === 'pending' && (
          <div className="flex shrink-0 gap-2 lg:w-32 lg:flex-col">
            <button onClick={() => onAccept(item.id)} disabled={acting === item.id} className="btn-primary flex-1 justify-center px-3 py-2 text-xs">
              {acting === item.id ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Accept
            </button>
            <button onClick={() => onDismiss(item.id)} disabled={acting === item.id} className="btn-secondary flex-1 justify-center border border-slate-700 px-3 py-2 text-xs">
              <X size={14} /> Dismiss
            </button>
          </div>
        )}
      </div>
    </article>
  )
}

function QueueEmptyState({ filter, scanning, onScan }) {
  return (
    <div className="card border-slate-800 py-16 text-center">
      <Inbox size={36} className="mx-auto mb-3 text-slate-600" />
      <p className="text-sm font-semibold text-slate-200">{filter === 'pending' ? 'No pending mismatch reviews.' : 'No corrections match this filter.'}</p>
      <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-slate-500">
        {filter === 'pending' ? 'A scan creates evidence-backed suggestions; it does not approve an association or change campaign eligibility.' : 'Select another review state to inspect recorded decisions.'}
      </p>
      {filter === 'pending' && (
        <button onClick={onScan} disabled={scanning} className="btn-primary mt-4 text-sm">
          {scanning ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Scan all leads
        </button>
      )}
    </div>
  )
}

export default function EmailReview() {
  const [workspace, setWorkspace] = useState('verification')
  const [items, setItems] = useState([])
  const [stats, setStats] = useState({ pending: 0, accepted: 0, dismissed: 0 })
  const [filter, setFilter] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [acting, setActing] = useState(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState(null)

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
    window.setTimeout(() => setToast(null), 3500)
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const response = await getEmailReviewStats()
      setStats(response.data || {})
    } catch {
      // The queue can still be loaded and provides the more useful error state.
    }
  }, [])

  const loadItems = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await getEmailCorrections(filter)
      setItems(response.data?.items || [])
    } catch (requestError) {
      setItems([])
      setError(requestError.response?.data?.detail || 'Mismatch reviews could not be loaded. Refresh to try again.')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    loadStats()
    loadItems()
  }, [loadItems, loadStats])

  async function handleScan() {
    const onlyUnscanned = window.confirm('Scan only leads that have never been scanned? Choose Cancel to scan all leads.')
    setScanning(true)
    try {
      await scanEmails(onlyUnscanned)
      showToast('Email scan started. New evidence will appear when the background scan finishes.')
      window.setTimeout(() => { loadItems(); loadStats() }, 5000)
    } catch (requestError) {
      showToast(requestError.response?.data?.detail || 'Scan failed. Check backend logs.', 'error')
    } finally {
      setScanning(false)
    }
  }

  async function handleAccept(id) {
    setActing(id)
    try {
      await acceptCorrection(id)
      showToast('Correction accepted. Existing verification, association, quarantine, and eligibility safeguards remain enforced.')
      loadItems()
      loadStats()
    } catch (requestError) {
      showToast(requestError.response?.data?.detail || 'Accept failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  async function handleDismiss(id) {
    setActing(id)
    try {
      await dismissCorrection(id)
      showToast('Correction dismissed; the recorded address is unchanged.')
      loadItems()
      loadStats()
    } catch (requestError) {
      showToast(requestError.response?.data?.detail || 'Dismiss failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="p-5 sm:p-8">
      {toast && (
        <div role="status" className={'fixed right-4 top-4 z-[60] max-w-sm rounded-lg border px-4 py-3 text-sm font-semibold shadow-2xl ' + (toast.type === 'error' ? 'border-rose-700 bg-rose-950 text-rose-100' : 'border-emerald-700 bg-emerald-950 text-emerald-100')}>
          {toast.message}
        </div>
      )}

      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-indigo-700/50 bg-indigo-950/70 p-2.5 text-indigo-300"><MailCheck size={20} /></div>
            <div>
              <h1 className="text-2xl font-bold text-white">Email Verification & Mismatch Review</h1>
              <p className="mt-1 max-w-3xl text-sm text-slate-500">Operational evidence for address routeability, business association, and human-reviewed correction decisions.</p>
            </div>
          </div>
        </div>
        {workspace === 'review' && (
          <button onClick={handleScan} disabled={scanning} className="btn-primary text-sm">
            {scanning ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Scan leads
          </button>
        )}
      </header>

      <div role="tablist" aria-label="Email operations workspace" className="mb-6 flex flex-wrap gap-2 border-b border-slate-800 pb-4">
        <button id="verification-tab" role="tab" aria-selected={workspace === 'verification'} aria-controls="verification-panel" onClick={() => setWorkspace('verification')} className={'tab-pill ' + (workspace === 'verification' ? 'tab-pill-active' : '')}>
          <ShieldCheck size={15} /> Verification workspace
        </button>
        <button id="review-tab" role="tab" aria-selected={workspace === 'review'} aria-controls="review-panel" onClick={() => setWorkspace('review')} className={'tab-pill ' + (workspace === 'review' ? 'tab-pill-active' : '')}>
          <ShieldAlert size={15} /> Mismatch review {stats.pending > 0 ? '(' + stats.pending + ')' : ''}
        </button>
      </div>

      {workspace === 'verification' ? (
        <section id="verification-panel" role="tabpanel" aria-labelledby="verification-tab">
          <p className="mb-4 rounded-lg border border-slate-800 bg-slate-900/50 px-4 py-3 text-xs leading-relaxed text-slate-400">
            A routeable address has passed stored syntax and DNS/MX checks. That does not confirm mailbox ownership or business association; standard outreach stays behind the existing fail-closed checks until the existing eligibility controls are satisfied.
          </p>
          <EmailVerificationAudit />
        </section>
      ) : (
        <section id="review-panel" role="tabpanel" aria-labelledby="review-tab">
          <div className="mb-5 grid gap-3 sm:grid-cols-3">
            {[
              ['Pending review', stats.pending, 'text-amber-300'],
              ['Accepted', stats.accepted, 'text-emerald-300'],
              ['Dismissed', stats.dismissed, 'text-slate-300'],
            ].map(([label, value, color]) => (
              <div key={label} className="card border-slate-800 bg-slate-900/50 p-4">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
                <p className={'mt-1 text-2xl font-bold ' + color}>{value ?? 0}</p>
              </div>
            ))}
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-2">
            {['pending', 'accepted', 'dismissed', 'all'].map((value) => (
              <button key={value} onClick={() => setFilter(value)} className={'tab-pill capitalize ' + (filter === value ? 'tab-pill-active' : '')}>{value}</button>
            ))}
            <button onClick={() => { loadItems(); loadStats() }} disabled={loading} className="btn-secondary ml-auto py-2 text-xs" aria-label="Refresh mismatch reviews">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>

          <div className="mb-4 flex gap-3 rounded-xl border border-amber-800/50 bg-amber-950/20 p-4 text-xs leading-relaxed text-amber-100">
            <AlertTriangle size={17} className="mt-0.5 shrink-0 text-amber-400" />
            <p><strong>Review safeguard:</strong> Accept applies only the selected email correction. It does not approve business association, clear quarantine, remove a suppression or bounce restriction, or make a lead campaign-eligible.</p>
          </div>

          {error ? (
            <div className="card border-rose-800/70 bg-rose-950/30 p-5 text-sm text-rose-200">
              <p>{error}</p>
              <button onClick={loadItems} className="mt-3 text-xs font-semibold underline">Retry</button>
            </div>
          ) : loading ? (
            <div className="card border-slate-800 py-16 text-center text-slate-400"><Loader2 size={26} className="mx-auto animate-spin" /><p className="mt-3 text-sm">Loading mismatch reviews...</p></div>
          ) : items.length ? (
            <div className="space-y-3">{items.map((item) => <CorrectionCard key={item.id} item={item} acting={acting} onAccept={handleAccept} onDismiss={handleDismiss} />)}</div>
          ) : (
            <QueueEmptyState filter={filter} scanning={scanning} onScan={handleScan} />
          )}
        </section>
      )}
    </div>
  )
}
