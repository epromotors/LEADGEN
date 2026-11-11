import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, Check, ExternalLink, HelpCircle, Info, Loader2,
  RefreshCw, ShieldAlert, ShieldCheck, ShieldX, X, Clock, ChevronDown, ChevronUp, Lock
} from 'lucide-react'
import {
  getNoWebsiteReviewQueue,
  approveNoWebsiteAssociation,
  rejectNoWebsiteAssociation,
  deferNoWebsiteAssociation,
  bulkApproveNoWebsiteAssociation,
  bulkRejectNoWebsiteAssociation,
  getInconclusiveWebsiteInvestigation,
} from '../api/client'

function EvidenceBadge({ tone = 'slate', children }) {
  const tones = {
    emerald: 'border-emerald-800/60 bg-emerald-950/50 text-emerald-300',
    amber: 'border-amber-800/60 bg-amber-950/50 text-amber-300',
    rose: 'border-rose-800/60 bg-rose-950/50 text-rose-300',
    sky: 'border-sky-800/60 bg-sky-950/50 text-sky-300',
    purple: 'border-purple-800/60 bg-purple-950/50 text-purple-300',
    slate: 'border-slate-700 bg-slate-800/70 text-slate-300',
  }
  return (
    <span className={'inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ' + (tones[tone] || tones.slate)}>
      {children}
    </span>
  )
}

function ReviewCard({
  item,
  sectionType,
  acting,
  selected = false,
  onToggleSelect,
  onApprove,
  onReject,
  onDefer,
}) {
  const [actionModal, setActionModal] = useState(null) // 'approve' | 'reject' | 'defer' | null
  const [reasonInput, setReasonInput] = useState('')
  const [policyInput, setPolicyInput] = useState('evidence_review')

  const tokens = item.business_name_match_evidence?.distinctive_tokens || []
  const matchedTokens = item.business_name_match_evidence?.matched_tokens || []
  const hasTokenMatch = matchedTokens.length > 0

  const isApproved = item.association_status === 'approved' || item.is_approved
  const isEvidenceBacked = sectionType === 'evidence_backed' && !isApproved
  const isOperatorReview = sectionType === 'operator_review' && !isApproved
  const isUnsupported = sectionType === 'unsupported' || (item.is_quarantined && !isApproved)

  const handleActionSubmit = (e) => {
    e.preventDefault()
    if (!actionModal) return
    if (actionModal === 'approve') {
      onApprove(item.id, reasonInput, policyInput)
    } else if (actionModal === 'reject') {
      onReject(item.id, reasonInput)
    } else if (actionModal === 'defer') {
      onDefer(item.id, reasonInput)
    }
    setActionModal(null)
  }

  const openApprove = () => {
    setActionModal('approve')
    setReasonInput(
      isEvidenceBacked
        ? `Verified business profile presence confirmed with matching token '${matchedTokens.join(', ')}'. Association validated.`
        : `Operator confirmed business association evidence for ${item.business_name}.`
    )
    setPolicyInput(isEvidenceBacked ? 'verified_seller_profile_review' : 'manual_operator_review')
  }

  const openReject = () => {
    setActionModal('reject')
    setReasonInput(`Association rejected: insufficient provenance for business '${item.business_name}'.`)
  }

  const openDefer = () => {
    setActionModal('defer')
    setReasonInput(`Deferred: pending additional proof or secondary verification.`)
  }

  return (
    <article className={'card p-4 sm:p-5 transition-all ' + (selected ? 'border-indigo-500/80 bg-indigo-950/20' : 'border-slate-800 bg-slate-900/50 hover:border-slate-700')}>
      <div className="flex flex-col gap-4 lg:flex-row lg:justify-between">
        <div className="min-w-0 flex-1">
          {/* Header Row */}
          <div className="flex flex-wrap items-center gap-2">
            {!isUnsupported && onToggleSelect && (
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggleSelect(item.id)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-0 focus:ring-offset-0 cursor-pointer mr-1"
                aria-label={`Select ${item.business_name}`}
              />
            )}
            <h3 className="truncate text-base font-bold text-white">{item.business_name}</h3>
            {isApproved && <EvidenceBadge tone="emerald">Approved Association</EvidenceBadge>}
            {isEvidenceBacked && <EvidenceBadge tone="purple">Proposed Evidence-Backed</EvidenceBadge>}
            {isOperatorReview && <EvidenceBadge tone="amber">Requires Operator Review</EvidenceBadge>}
            {isUnsupported && <EvidenceBadge tone="rose">Excluded / Unsupported</EvidenceBadge>}

            {item.campaign_eligibility?.is_eligible ? (
              <EvidenceBadge tone="emerald">Campaign Eligible</EvidenceBadge>
            ) : (
              <EvidenceBadge tone="slate">Not Eligible</EvidenceBadge>
            )}

            {item.is_quarantined && (
              <EvidenceBadge tone="rose">Quarantined</EvidenceBadge>
            )}
          </div>

          {/* Email & Routeability Box */}
          <div className="mt-3 grid gap-2 rounded-lg border border-slate-800 bg-slate-950/70 p-3 sm:grid-cols-2 sm:items-center">
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Public-Provider Email</p>
              <p className="mt-0.5 break-all font-mono text-sm font-semibold text-sky-300">{item.email}</p>
              <p className="text-[11px] text-slate-500">Provider: <span className="font-mono text-slate-300">@{item.provider}</span></p>
            </div>
            <div className="min-w-0 border-t border-slate-800 pt-2 sm:border-l sm:border-t-0 sm:pl-3 sm:pt-0">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Routeability & Mailbox</p>
              <div className="mt-0.5 flex items-center gap-2">
                <EvidenceBadge tone={item.routeability_status === 'valid' ? 'emerald' : 'rose'}>
                  {item.routeability_status === 'valid' ? 'Syntax & MX Valid' : item.routeability_status}
                </EvidenceBadge>
                <span className="text-[11px] text-slate-400">
                  {item.mailbox_confirmed ? 'Mailbox Confirmed' : 'DNS/MX Routeable'}
                </span>
              </div>
            </div>
          </div>

          {/* Business-Name Match Evidence & Provenance */}
          <div className="mt-3 grid gap-3 border-t border-slate-800 pt-3 sm:grid-cols-2">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Business-Name Match Evidence</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {hasTokenMatch ? (
                  <>
                    <EvidenceBadge tone="emerald">Matched: {matchedTokens.join(', ')}</EvidenceBadge>
                    <span className="text-[11px] text-slate-400">in distinctive tokens ({tokens.join(', ')})</span>
                  </>
                ) : (
                  <EvidenceBadge tone="rose">No Distinctive Token Match</EvidenceBadge>
                )}
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                Method: <strong className="text-slate-300 font-mono">{item.extraction_method || 'direct'}</strong>
              </p>
            </div>

            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Source Provenance</p>
              {item.source_url ? (
                <div className="mt-1">
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300 break-all font-mono"
                  >
                    {item.source_url.length > 55 ? item.source_url.substring(0, 52) + '...' : item.source_url}
                    <ExternalLink size={12} className="shrink-0" />
                  </a>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {item.source_url.includes('instagram.com') || item.source_url.includes('facebook.com') || item.source_url.includes('globallinker.com')
                      ? 'Official business profile / verified seller listing'
                      : 'Web directory or search snippet citation'}
                  </p>
                </div>
              ) : (
                <p className="mt-1 text-xs text-rose-300 italic">No source URL recorded in provenance</p>
              )}
            </div>
          </div>

          {/* Exclusion & Audit Rationale */}
          <div className="mt-3 rounded border border-slate-800/80 bg-slate-950/40 p-2.5 text-xs">
            {isApproved ? (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-400">Approval Provenance & Audit Trail</p>
                <p className="mt-0.5 text-slate-200 leading-relaxed text-[11px]">
                  {item.association_reason || 'Approved by operator with verified business representation.'}
                </p>
              </div>
            ) : (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Shared Evaluator Exclusion Reason</p>
                <p className="mt-0.5 text-slate-300 leading-relaxed font-mono text-[11px]">
                  {item.campaign_eligibility?.exclusion_reason || 'No exclusion reason; lead is currently eligible for campaigns.'}
                </p>
              </div>
            )}
            {item.class_reason && (
              <p className="mt-1.5 text-[11px] text-amber-300/90 leading-relaxed">
                <strong>Audit note:</strong> {item.class_reason}
              </p>
            )}
            {item.is_quarantined && item.quarantine_reason && (
              <p className="mt-1 text-[11px] text-rose-300">
                <strong>Quarantine:</strong> {item.quarantine_reason}
              </p>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex shrink-0 gap-2 lg:w-36 lg:flex-col lg:justify-center border-t border-slate-800 pt-3 lg:border-t-0 lg:border-l lg:pl-4 lg:pt-0">
          {isApproved ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-center gap-1.5 rounded border border-emerald-800/60 bg-emerald-950/40 p-2 text-center text-xs font-semibold text-emerald-300">
                <Check size={14} className="text-emerald-400" />
                <span>Approved</span>
              </div>
              <button
                type="button"
                onClick={openReject}
                disabled={acting === item.id}
                className="btn-secondary flex-1 justify-center border border-rose-900/60 bg-rose-950/20 text-rose-300 hover:bg-rose-900/40 px-2.5 py-1.5 text-xs"
                title="Revoke approval and quarantine contact"
              >
                <X size={13} /> Revoke / Reject
              </button>
            </div>
          ) : !isUnsupported ? (
            <>
              <button
                type="button"
                onClick={openApprove}
                disabled={acting === item.id}
                className="btn-primary flex-1 justify-center px-3 py-2 text-xs bg-emerald-600 hover:bg-emerald-500"
              >
                {acting === item.id ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Approve
              </button>
              <button
                type="button"
                onClick={openReject}
                disabled={acting === item.id}
                className="btn-secondary flex-1 justify-center border border-rose-900/60 bg-rose-950/20 text-rose-300 hover:bg-rose-900/40 px-3 py-2 text-xs"
              >
                <X size={13} /> Reject
              </button>
              <button
                type="button"
                onClick={openDefer}
                disabled={acting === item.id}
                className="btn-secondary flex-1 justify-center border border-slate-700 px-3 py-2 text-xs text-slate-300"
              >
                <Clock size={13} /> Defer
              </button>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center p-2 text-center text-slate-500">
              <Lock size={16} className="mb-1 text-slate-600" />
              <span className="text-[11px] font-semibold">Excluded</span>
              <span className="text-[10px] text-slate-600">Approval locked</span>
            </div>
          )}
        </div>
      </div>

      {/* Modal / Action Form */}
      {actionModal && (
        <form onSubmit={handleActionSubmit} className="mt-4 rounded-lg border border-slate-700 bg-slate-950 p-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-800">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
              {actionModal === 'approve' && 'Approve Business Association'}
              {actionModal === 'reject' && 'Reject Association & Quarantine'}
              {actionModal === 'defer' && 'Defer Review Decision'}
            </h4>
            <button
              type="button"
              onClick={() => setActionModal(null)}
              className="text-slate-400 hover:text-slate-200"
            >
              <X size={14} />
            </button>
          </div>

          <div className="mt-3 space-y-3">
            <div>
              <label className="text-[11px] font-bold text-slate-400">Auditable Reason / Evidence Note</label>
              <textarea
                value={reasonInput}
                onChange={(e) => setReasonInput(e.target.value)}
                rows={2}
                required
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                placeholder="Enter justification recorded in permanent audit trail..."
              />
            </div>

            {actionModal === 'approve' && (
              <div>
                <label className="text-[11px] font-bold text-slate-400">Policy Reference</label>
                <input
                  type="text"
                  value={policyInput}
                  onChange={(e) => setPolicyInput(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  placeholder="e.g. verified_seller_profile_review"
                />
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setActionModal(null)}
                className="btn-secondary px-3 py-1.5 text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={acting === item.id || reasonInput.trim().length < 3}
                className={
                  'btn-primary px-4 py-1.5 text-xs ' +
                  (actionModal === 'approve' ? 'bg-emerald-600 hover:bg-emerald-500' :
                   actionModal === 'reject' ? 'bg-rose-700 hover:bg-rose-600' : 'bg-slate-700 hover:bg-slate-600')
                }
              >
                {acting === item.id ? <Loader2 size={13} className="animate-spin" /> : 'Confirm ' + actionModal}
              </button>
            </div>
          </div>
        </form>
      )}
    </article>
  )
}

export default function NoWebsiteReviewQueue() {
  const [queueData, setQueueData] = useState(null)
  const [inconclusiveData, setInconclusiveData] = useState(null)
  const [showInconclusive, setShowInconclusive] = useState(false)
  const [activeSection, setActiveSection] = useState('evidence_backed') // 'evidence_backed' | 'operator_review' | 'approved' | 'unsupported'
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState(null)

  // Multi-selection and bulk actions
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkModal, setBulkModal] = useState(null) // 'approve' | 'reject' | null
  const [bulkReason, setBulkReason] = useState('')
  const [bulkPolicy, setBulkPolicy] = useState('bulk_evidence_review')
  const [bulkError, setBulkError] = useState('')

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
    window.setTimeout(() => setToast(null), 4000)
  }, [])

  const handleSectionChange = (section) => {
    setActiveSection(section)
    setSelectedIds(new Set())
  }

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelectAll = (items) => {
    const selectable = items.filter((i) => !i.is_quarantined || activeSection === 'approved')
    const allSelected = selectable.length > 0 && selectable.every((i) => selectedIds.has(i.id))
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(selectable.map((i) => i.id)))
    }
  }

  const openBulkApprove = () => {
    setBulkError('')
    setBulkModal('approve')
    setBulkReason(
      activeSection === 'evidence_backed'
        ? 'Bulk approved: verified seller profile presence confirmed with matching distinctive tokens.'
        : 'Bulk approved: operator confirmed business association evidence for selected contacts.'
    )
    setBulkPolicy(activeSection === 'evidence_backed' ? 'verified_seller_profile_review' : 'bulk_evidence_review')
  }

  const openBulkReject = () => {
    setBulkError('')
    setBulkModal('reject')
    setBulkReason(
      activeSection === 'approved'
        ? 'Bulk revoked: operator revoked prior association approval and quarantined contacts.'
        : 'Bulk rejected: insufficient business association provenance for selected contacts.'
    )
  }

  const handleBulkSubmit = async (e) => {
    e.preventDefault()
    if (!bulkModal || selectedIds.size === 0) return
    const ids = Array.from(selectedIds)
    setActing('bulk')
    setBulkError('')
    try {
      if (bulkModal === 'approve') {
        const res = await bulkApproveNoWebsiteAssociation({
          lead_ids: ids,
          reason: bulkReason,
          policy_reference: bulkPolicy,
        })
        showToast(`Successfully bulk-approved ${res.data.approved_count} lead(s).`)
      } else if (bulkModal === 'reject') {
        const res = await bulkRejectNoWebsiteAssociation({
          lead_ids: ids,
          reason: bulkReason,
        })
        showToast(`Successfully rejected and quarantined ${res.data.rejected_count} lead(s).`, 'error')
      }
      setSelectedIds(new Set())
      setBulkModal(null)
      await loadQueue()
    } catch (err) {
      const errMsg = err.response?.data?.detail || err.message || 'Bulk action failed.'
      setBulkError(errMsg)
      showToast(errMsg, 'error')
    } finally {
      setActing(null)
    }
  }

  const loadQueue = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await getNoWebsiteReviewQueue()
      setQueueData(response.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load no-website review queue.')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadInconclusive = useCallback(async () => {
    try {
      const res = await getInconclusiveWebsiteInvestigation()
      setInconclusiveData(res.data)
    } catch {
      // Inconclusive summary is secondary
    }
  }, [])

  useEffect(() => {
    loadQueue()
    loadInconclusive()
  }, [loadQueue, loadInconclusive])

  const handleApprove = async (id, reason, policyReference) => {
    setActing(id)
    try {
      await approveNoWebsiteAssociation(id, { reason, policy_reference: policyReference })
      showToast('Association approved successfully. Campaign eligibility recalculated by shared evaluator.')
      await loadQueue()
    } catch (err) {
      showToast(err.response?.data?.detail || 'Approval failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  const handleReject = async (id, reason) => {
    setActing(id)
    try {
      await rejectNoWebsiteAssociation(id, { reason })
      showToast('Association rejected and lead quarantined.', 'error')
      await loadQueue()
    } catch (err) {
      showToast(err.response?.data?.detail || 'Rejection failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  const handleDefer = async (id, reason) => {
    setActing(id)
    try {
      await deferNoWebsiteAssociation(id, { reason })
      showToast('Review decision deferred with notes.')
      await loadQueue()
    } catch (err) {
      showToast(err.response?.data?.detail || 'Deferral failed.', 'error')
    } finally {
      setActing(null)
    }
  }

  const stats = queueData?.stats || {}
  const evidenceBackedItems = queueData?.evidence_backed || []
  const operatorReviewItems = queueData?.operator_review || []
  const approvedItems = queueData?.approved || []
  const unsupportedItems = queueData?.unsupported || []

  return (
    <div className="space-y-6">
      {toast && (
        <div
          role="status"
          className={
            'fixed right-4 top-4 z-[60] max-w-md rounded-lg border px-4 py-3 text-sm font-semibold shadow-2xl ' +
            (toast.type === 'error' ? 'border-rose-700 bg-rose-950 text-rose-100' : 'border-emerald-700 bg-emerald-950 text-emerald-100')
          }
        >
          {toast.message}
        </div>
      )}

      {/* Overview Stat Cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="card border-slate-800 bg-slate-900/60 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Confirmed No-Website</p>
          <p className="mt-1 text-2xl font-bold text-white">
            {loading ? <Loader2 size={18} className="animate-spin inline text-slate-500" /> : (stats.total_no_website ?? '—')}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">Businesses with verified no website</p>
        </div>

        <div className="card border-slate-800 bg-slate-900/60 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Routeable Public Leads</p>
          <p className="mt-1 text-2xl font-bold text-sky-400">
            {loading ? <Loader2 size={18} className="animate-spin inline text-slate-500" /> : (stats.routeable_public ?? '—')}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">Public-provider emails (syntax + MX)</p>
        </div>

        <div className="card border-slate-800 bg-slate-900/60 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Current Campaign Eligible</p>
          <p className={'mt-1 text-2xl font-bold ' + (Number(stats.campaign_eligible_count || 0) > 0 ? 'text-emerald-400' : 'text-rose-400')}>
            {loading ? <Loader2 size={18} className="animate-spin inline text-slate-500" /> : (stats.campaign_eligible_count ?? '—')}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">
            {stats.approved_count ? `${stats.approved_count} approved by operator` : 'Shared evaluator enforced: 0 until approved'}
          </p>
        </div>

        <div className="card border-slate-800 bg-slate-900/60 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Evidence Candidates</p>
          <p className="mt-1 text-2xl font-bold text-purple-400">
            {loading ? (
              <Loader2 size={18} className="animate-spin inline text-slate-500" />
            ) : stats.evidence_backed_count !== undefined ? (
              <>
                {stats.evidence_backed_count}{' '}
                <span className="text-xs text-slate-500 font-normal">/ {stats.operator_review_count ?? 0} review</span>
              </>
            ) : (
              '—'
            )}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">Proposed + operator review</p>
        </div>

        <div className="card border-slate-800 bg-slate-900/60 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Unsupported Excluded</p>
          <p className="mt-1 text-2xl font-bold text-slate-300">
            {loading ? <Loader2 size={18} className="animate-spin inline text-slate-500" /> : (stats.unsupported_count ?? '—')}
          </p>
          <p className="mt-1 text-[11px] text-slate-400">Unsupported public + other excluded</p>
        </div>
      </div>

      {/* Investigation Notification for Inconclusive Records */}
      <div className="rounded-xl border border-sky-800/50 bg-sky-950/20 p-4 text-xs">
        <div className="flex items-start justify-between gap-3">
          <div className="flex gap-2.5">
            <Info size={18} className="mt-0.5 shrink-0 text-sky-400" />
            <div>
              <p className="font-bold text-sky-200">
                {(inconclusiveData?.total_inconclusive_records ?? stats.audit_inconclusive_count) !== undefined ? (inconclusiveData?.total_inconclusive_records ?? stats.audit_inconclusive_count) : '—'} Website-Less Records Classified as Inconclusive (Read-Only Separation)
              </p>
              <p className="mt-1 text-sky-300/80 leading-relaxed">
                {(inconclusiveData?.total_inconclusive_records ?? stats.audit_inconclusive_count) ?? 'All'} leads without a website URL have unconfirmed search snippet candidates from directories (Tofler, ZaubaCorp, ExportersIndia) or ambiguous candidate domains. They are correctly classified as <code className="bg-sky-950 px-1 py-0.5 rounded text-sky-200 font-mono">AUDIT_INCONCLUSIVE</code> and are <strong>strictly excluded</strong> from the confirmed no-website pool.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowInconclusive(!showInconclusive)}
            className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-wider text-sky-400 hover:text-sky-300 shrink-0"
          >
            {showInconclusive ? 'Hide Details' : 'View Investigation'}
            {showInconclusive ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>

        {showInconclusive && inconclusiveData && (
          <div className="mt-3 border-t border-sky-900/60 pt-3 text-[11px]">
            <p className="font-semibold text-slate-200">Investigation Findings:</p>
            <p className="mt-1 text-slate-400 leading-relaxed">{inconclusiveData.summary}</p>
            <div className="mt-3">
              <p className="font-semibold text-slate-200">Sample Records (10 of {inconclusiveData.total_inconclusive_records}):</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {inconclusiveData.samples?.map((s) => (
                  <div key={s.id} className="rounded border border-slate-800 bg-slate-900/80 p-2">
                    <p className="font-bold text-white truncate">{s.business_name}</p>
                    <p className="text-[10px] text-slate-400">{s.candidates_count} candidate websites found in search snippets</p>
                    <div className="mt-1 space-y-0.5">
                      {s.sample_candidates?.map((c, i) => (
                        <p key={i} className="text-[10px] font-mono text-sky-300 truncate">
                          • {c.domain || c.url}
                        </p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Section Filter Pills */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
        <button
          type="button"
          onClick={() => handleSectionChange('evidence_backed')}
          className={'tab-pill flex items-center gap-1.5 ' + (activeSection === 'evidence_backed' ? 'tab-pill-active' : '')}
        >
          <ShieldCheck size={14} />
          Proposed Evidence-Backed ({evidenceBackedItems.length})
        </button>

        <button
          type="button"
          onClick={() => handleSectionChange('operator_review')}
          className={'tab-pill flex items-center gap-1.5 ' + (activeSection === 'operator_review' ? 'tab-pill-active' : '')}
        >
          <ShieldAlert size={14} />
          Operator Review Queue ({operatorReviewItems.length})
        </button>

        <button
          type="button"
          onClick={() => handleSectionChange('approved')}
          className={'tab-pill flex items-center gap-1.5 ' + (activeSection === 'approved' ? 'tab-pill-active border-emerald-500/50 text-emerald-300' : '')}
        >
          <Check size={14} className="text-emerald-400" />
          Approved & Eligible ({approvedItems.length})
        </button>

        <button
          type="button"
          onClick={() => handleSectionChange('unsupported')}
          className={'tab-pill flex items-center gap-1.5 ' + (activeSection === 'unsupported' ? 'tab-pill-active' : '')}
        >
          <ShieldX size={14} />
          Unsupported Excluded ({unsupportedItems.length})
        </button>

        <button
          type="button"
          onClick={loadQueue}
          disabled={loading}
          className="btn-secondary ml-auto py-1.5 text-xs"
          aria-label="Refresh review queue"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh Queue
        </button>
      </div>

      {/* Section Content */}
      {loading ? (
        <div className="card border-slate-800 py-16 text-center text-slate-400">
          <Loader2 size={26} className="mx-auto animate-spin" />
          <p className="mt-3 text-sm">Evaluating campaign eligibility and review cards...</p>
        </div>
      ) : error ? (
        <div className="card border-rose-800/70 bg-rose-950/30 p-5 text-sm text-rose-200">
          <p>{error}</p>
          <button onClick={loadQueue} className="mt-3 text-xs font-semibold underline">Retry</button>
        </div>
      ) : (
        <div className="space-y-4">
          {activeSection === 'evidence_backed' && (
            <div>
              <div className="mb-4 rounded-lg border border-purple-800/40 bg-purple-950/20 p-3.5 text-xs text-purple-200">
                <p className="font-bold text-purple-100 flex items-center gap-2">
                  <ShieldCheck size={16} className="text-purple-400" />
                  Section 1: Proposed Evidence-Backed Candidates ({evidenceBackedItems.length})
                </p>
                <p className="mt-1 leading-relaxed text-purple-200/80">
                  These contacts feature verified seller listings or official business profiles (e.g. GlobalLinker seller profile, Instagram Reels, Facebook business pages) with matching business-name tokens. Verify the source URL before operator approval.
                </p>
              </div>

              {evidenceBackedItems.length > 0 && (
                <div className="mb-3 flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3.5 py-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer select-none text-slate-300 hover:text-white">
                    <input
                      type="checkbox"
                      checked={evidenceBackedItems.length > 0 && evidenceBackedItems.every((i) => selectedIds.has(i.id))}
                      onChange={() => toggleSelectAll(evidenceBackedItems)}
                      className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 cursor-pointer"
                    />
                    <span className="font-medium">Select All ({evidenceBackedItems.length})</span>
                  </label>
                  {selectedIds.size > 0 && (
                    <span className="text-[11px] text-indigo-400 font-medium">
                      {evidenceBackedItems.filter((i) => selectedIds.has(i.id)).length} of {evidenceBackedItems.length} selected
                    </span>
                  )}
                </div>
              )}

              {evidenceBackedItems.length === 0 ? (
                <div className="card border-slate-800 p-8 text-center text-slate-400">
                  No proposed evidence-backed candidates currently in queue.
                </div>
              ) : (
                <div className="space-y-3">
                  {evidenceBackedItems.map((item) => (
                    <ReviewCard
                      key={item.id}
                      item={item}
                      sectionType="evidence_backed"
                      acting={acting}
                      selected={selectedIds.has(item.id)}
                      onToggleSelect={toggleSelect}
                      onApprove={handleApprove}
                      onReject={handleReject}
                      onDefer={handleDefer}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'operator_review' && (
            <div>
              <div className="mb-4 rounded-lg border border-amber-800/40 bg-amber-950/20 p-3.5 text-xs text-amber-200">
                <p className="font-bold text-amber-100 flex items-center gap-2">
                  <ShieldAlert size={16} className="text-amber-400" />
                  Section 2: Operator Review Queue ({operatorReviewItems.length} Candidates)
                </p>
                <p className="mt-1 leading-relaxed text-amber-200/80">
                  These public-provider contacts require manual operator confirmation. Evaluate whether the source citation and email handle demonstrate genuine business representation before approving. Approval requires authenticated operator action and recorded provenance.
                </p>
              </div>

              {operatorReviewItems.length > 0 && (
                <div className="mb-3 flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3.5 py-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer select-none text-slate-300 hover:text-white">
                    <input
                      type="checkbox"
                      checked={operatorReviewItems.length > 0 && operatorReviewItems.every((i) => selectedIds.has(i.id))}
                      onChange={() => toggleSelectAll(operatorReviewItems)}
                      className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 cursor-pointer"
                    />
                    <span className="font-medium">Select All ({operatorReviewItems.length})</span>
                  </label>
                  {selectedIds.size > 0 && (
                    <span className="text-[11px] text-indigo-400 font-medium">
                      {operatorReviewItems.filter((i) => selectedIds.has(i.id)).length} of {operatorReviewItems.length} selected
                    </span>
                  )}
                </div>
              )}

              {operatorReviewItems.length === 0 ? (
                <div className="card border-slate-800 p-8 text-center text-slate-400">
                  No operator-review candidates currently pending.
                </div>
              ) : (
                <div className="space-y-3">
                  {operatorReviewItems.map((item) => (
                    <ReviewCard
                      key={item.id}
                      item={item}
                      sectionType="operator_review"
                      acting={acting}
                      selected={selectedIds.has(item.id)}
                      onToggleSelect={toggleSelect}
                      onApprove={handleApprove}
                      onReject={handleReject}
                      onDefer={handleDefer}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'approved' && (
            <div>
              <div className="mb-4 rounded-lg border border-emerald-800/40 bg-emerald-950/20 p-3.5 text-xs text-emerald-200">
                <p className="font-bold text-emerald-100 flex items-center gap-2">
                  <Check size={16} className="text-emerald-400" />
                  Section 3: Approved & Campaign Eligible Contacts ({approvedItems.length})
                </p>
                <p className="mt-1 leading-relaxed text-emerald-200/80">
                  These public-provider email associations have been authenticated and approved by an operator. They satisfy all strict shared evaluator requirements and are immediately eligible for no-website campaigns. Approvals can be revoked or rejected if necessary.
                </p>
              </div>

              {approvedItems.length > 0 && (
                <div className="mb-3 flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3.5 py-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer select-none text-slate-300 hover:text-white">
                    <input
                      type="checkbox"
                      checked={approvedItems.length > 0 && approvedItems.every((i) => selectedIds.has(i.id))}
                      onChange={() => toggleSelectAll(approvedItems)}
                      className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 cursor-pointer"
                    />
                    <span className="font-medium">Select All ({approvedItems.length})</span>
                  </label>
                  {selectedIds.size > 0 && (
                    <span className="text-[11px] text-indigo-400 font-medium">
                      {approvedItems.filter((i) => selectedIds.has(i.id)).length} of {approvedItems.length} selected
                    </span>
                  )}
                </div>
              )}

              {approvedItems.length === 0 ? (
                <div className="card border-slate-800 p-8 text-center text-slate-400">
                  No approved contacts yet. Accept contacts from the pending review queues above to qualify them.
                </div>
              ) : (
                <div className="space-y-3">
                  {approvedItems.map((item) => (
                    <ReviewCard
                      key={item.id}
                      item={item}
                      sectionType="approved"
                      acting={acting}
                      selected={selectedIds.has(item.id)}
                      onToggleSelect={toggleSelect}
                      onApprove={handleApprove}
                      onReject={handleReject}
                      onDefer={handleDefer}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {activeSection === 'unsupported' && (
            <div>
              <div className="mb-4 rounded-lg border border-rose-800/40 bg-rose-950/20 p-3.5 text-xs text-rose-200">
                <p className="font-bold text-rose-100 flex items-center gap-2">
                  <ShieldX size={16} className="text-rose-400" />
                  Section 4: Unsupported Candidates ({unsupportedItems.length} Total Excluded)
                </p>
                <p className="mt-1 leading-relaxed text-rose-200/80">
                  Unsupported public contacts lack source URL provenance and have unrelated personal email handles. They remain strictly excluded along with quarantined entities (including <strong>A G TRADEMART PVT LTD</strong> / <code className="bg-rose-950 px-1 py-0.5 rounded font-mono">email.safety@tn.gov</code>). These contacts cannot be approved into campaigns.
                </p>
              </div>

              {unsupportedItems.length === 0 ? (
                <div className="card border-slate-800 p-8 text-center text-slate-400">
                  No unsupported excluded records to display.
                </div>
              ) : (
                <div className="space-y-3">
                  {unsupportedItems.map((item) => (
                    <ReviewCard
                      key={item.id}
                      item={item}
                      sectionType="unsupported"
                      acting={acting}
                      selected={false}
                      onToggleSelect={null}
                      onApprove={handleApprove}
                      onReject={handleReject}
                      onDefer={handleDefer}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Floating Bulk Action Bar */}
      {selectedIds.size > 0 && (
        <div className="sticky bottom-6 z-40 mx-auto flex max-w-2xl items-center justify-between gap-3 rounded-xl border border-indigo-500/50 bg-slate-900/95 p-3.5 shadow-2xl backdrop-blur-md">
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs font-bold text-white">
              {selectedIds.size}
            </span>
            <span className="text-xs font-semibold text-slate-200">
              {selectedIds.size} lead{selectedIds.size > 1 ? 's' : ''} selected
            </span>
          </div>
          <div className="flex items-center gap-2">
            {activeSection !== 'approved' && (
              <button
                type="button"
                onClick={openBulkApprove}
                disabled={acting === 'bulk'}
                className="btn-primary flex items-center gap-1.5 bg-emerald-600 px-3 py-1.5 text-xs hover:bg-emerald-500"
              >
                {acting === 'bulk' ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                Bulk Approve ({selectedIds.size})
              </button>
            )}
            <button
              type="button"
              onClick={openBulkReject}
              disabled={acting === 'bulk'}
              className="btn-secondary flex items-center gap-1.5 border border-rose-900/60 bg-rose-950/40 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-900/60"
            >
              <X size={13} />
              {activeSection === 'approved' ? 'Bulk Revoke' : 'Bulk Reject'} ({selectedIds.size})
            </button>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="btn-secondary px-2.5 py-1.5 text-xs text-slate-400 hover:text-white"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {/* Bulk Action Modal */}
      {bulkModal && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 p-4 pt-16 overflow-y-auto">
          <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-950 p-5 shadow-2xl mb-8">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h4 className="text-sm font-bold uppercase tracking-wider text-slate-100 flex items-center gap-2">
                {bulkModal === 'approve' ? (
                  <>
                    <Check size={16} className="text-emerald-400" />
                    Bulk Approve Association ({selectedIds.size} Leads)
                  </>
                ) : (
                  <>
                    <X size={16} className="text-rose-400" />
                    Bulk Reject & Quarantine ({selectedIds.size} Leads)
                  </>
                )}
              </h4>
              <button
                type="button"
                onClick={() => setBulkModal(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleBulkSubmit} className="mt-4 space-y-4">
              {bulkError && (
                <div className="rounded-lg border border-rose-900/60 bg-rose-950/40 p-2.5 text-xs text-rose-300">
                  {bulkError}
                </div>
              )}
              <div>
                <label className="text-xs font-semibold text-slate-300">
                  Auditable Reason / Evidence Note
                </label>
                <textarea
                  value={bulkReason}
                  onChange={(e) => setBulkReason(e.target.value)}
                  rows={3}
                  required
                  className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 p-2.5 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                  placeholder="Enter audit rationale for bulk decision..."
                />
              </div>

              {bulkModal === 'approve' && (
                <div>
                  <label className="text-xs font-semibold text-slate-300">
                    Policy Reference
                  </label>
                  <input
                    type="text"
                    value={bulkPolicy}
                    onChange={(e) => setBulkPolicy(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 p-2.5 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                    placeholder="e.g. bulk_evidence_review"
                  />
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setBulkModal(null)}
                  className="btn-secondary px-3 py-1.5 text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={acting === 'bulk' || bulkReason.trim().length < 3}
                  className={
                    'btn-primary px-4 py-1.5 text-xs ' +
                    (bulkModal === 'approve'
                      ? 'bg-emerald-600 hover:bg-emerald-500'
                      : 'bg-rose-700 hover:bg-rose-600')
                  }
                >
                  {acting === 'bulk' ? (
                    <Loader2 size={13} className="animate-spin inline mr-1" />
                  ) : null}
                  Confirm Bulk {bulkModal === 'approve' ? 'Approve' : 'Reject'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
