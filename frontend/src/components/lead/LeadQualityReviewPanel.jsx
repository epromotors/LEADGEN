import React, { useState } from 'react'
import {
  AlertTriangle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  X,
  ChevronDown,
  ChevronUp,
  Trash2,
  ExternalLink,
  Check,
  CheckSquare,
  Square,
  Globe,
  Mail,
  FileText,
} from 'lucide-react'

export default function LeadQualityReviewPanel({
  records = [],
  total = 0,
  page = 1,
  pageSize = 50,
  counts = null,
  searchQuery = '',
  loading = false,
  onRetry,
  onKeepUnderReview,
  onDeleteOne,
  onBulkDelete,
  onPageChange,
  onSearchChange,
  onClose,
}) {
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [confirmBulkModal, setConfirmBulkModal] = useState(false)
  const [actionInProgress, setActionInProgress] = useState(null)
  const [localSearch, setLocalSearch] = useState(searchQuery || '')

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const isAllSelected = records.length > 0 && records.every(r => selectedIds.has(r.lead_id))
  const isSomeSelected = selectedIds.size > 0 && !isAllSelected

  function toggleSelectOne(id) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (isAllSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(records.map(r => r.lead_id)))
    }
  }

  function toggleExpand(id) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleSingleRetry(leadId, reverifyEmail = false) {
    setActionInProgress(leadId)
    try {
      if (onRetry) await onRetry(leadId, reverifyEmail)
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleSingleKeep(leadId) {
    setActionInProgress(leadId)
    try {
      if (onKeepUnderReview) await onKeepUnderReview(leadId)
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleSingleDelete(leadId, businessName) {
    if (!window.confirm(`Delete explicitly selected lead "${businessName}"? This action cannot be undone.`)) {
      return
    }
    setActionInProgress(leadId)
    try {
      if (onDeleteOne) await onDeleteOne(leadId)
      setSelectedIds(prev => {
        const next = new Set(prev)
        next.delete(leadId)
        return next
      })
    } finally {
      setActionInProgress(null)
    }
  }

  async function executeBulkDelete() {
    const ids = Array.from(selectedIds)
    setConfirmBulkModal(false)
    setActionInProgress('bulk-delete')
    try {
      if (onBulkDelete) await onBulkDelete(ids)
      setSelectedIds(new Set())
    } finally {
      setActionInProgress(null)
    }
  }

  const selectedRecords = records.filter(r => selectedIds.has(r.lead_id))

  const getActionBadge = (action) => {
    switch (action) {
      case 'recommend_deletion':
        return 'border-rose-700/60 bg-rose-950/40 text-rose-300'
      case 'retry_discovery':
        return 'border-blue-700/60 bg-blue-950/40 text-blue-300'
      case 'reverify':
        return 'border-purple-700/60 bg-purple-950/40 text-purple-300'
      case 'keep_for_review':
      default:
        return 'border-amber-700/60 bg-amber-950/40 text-amber-300'
    }
  }

  return (
    <section className="card-elevated border-amber-800/50 bg-amber-950/10 p-4 space-y-4" aria-label="Lead quality review queue">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 border-b border-amber-900/30 pb-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-bold text-amber-100 flex-wrap">
            <ShieldAlert size={16} className="text-amber-400" />
            Operator Lead Quality &amp; Quarantine Review Queue
            <span className="ml-2 rounded-full bg-amber-900/40 px-2 py-0.5 text-xs text-amber-300 font-mono">
              {total.toLocaleString()} total reviewable
            </span>
          </h2>
          {counts && (
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <span className="inline-flex items-center gap-1 rounded bg-blue-950/60 border border-blue-800/60 px-2 py-0.5 text-[11px] text-blue-300 font-mono" title="Operational Gatekeeper: quarantined leads or unresolved associations">
                Operational Queue: <strong className="text-blue-100">{counts.operational_queue?.toLocaleString()}</strong>
              </span>
              <span className="inline-flex items-center gap-1 rounded bg-purple-950/60 border border-purple-800/60 px-2 py-0.5 text-[11px] text-purple-300 font-mono" title="Data-Repair Actionable: content anomalies flagged by dry-run rules">
                Data-Repair Actionable: <strong className="text-purple-100">{counts.data_repair_actionable?.toLocaleString()}</strong>
              </span>
              <span className="inline-flex items-center gap-1 rounded bg-emerald-950/60 border border-emerald-800/60 px-2 py-0.5 text-[11px] text-emerald-300 font-mono" title="Belonging to both operational gatekeeper and data repair">
                Both: <strong className="text-emerald-100">{counts.both?.toLocaleString()}</strong>
              </span>
            </div>
          )}
          <p className="mt-1 text-xs text-slate-400">
            Evidence and provenance are inspectable below. Candidates do not authorize outreach or clear quarantine.
            Deletion requires explicit operator confirmation of selected records.
          </p>
        </div>
        <button
          onClick={onClose}
          className="self-end sm:self-auto rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          aria-label="Close quality review"
          title="Close review panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* ── Action & Selection Bar ── */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800 text-xs">
        <div className="flex items-center gap-3">
          <button
            onClick={toggleSelectAll}
            disabled={loading || records.length === 0}
            className="flex items-center gap-1.5 font-semibold text-slate-300 hover:text-white disabled:opacity-40"
          >
            {isAllSelected ? (
              <CheckSquare size={14} className="text-blue-400" />
            ) : isSomeSelected ? (
              <CheckSquare size={14} className="text-blue-400/60" />
            ) : (
              <Square size={14} className="text-slate-500" />
            )}
            <span>Select All on Page ({records.length})</span>
          </button>
          {selectedIds.size > 0 && (
            <span className="font-mono text-blue-400 font-medium">
              {selectedIds.size} selected
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {onSearchChange && (
            <div className="relative">
              <input
                type="text"
                placeholder="Search queue (name, email, domain)..."
                value={localSearch}
                onChange={(e) => {
                  setLocalSearch(e.target.value)
                  onSearchChange(e.target.value)
                }}
                className="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-white placeholder-slate-500 w-44 sm:w-60 focus:outline-none focus:border-amber-500"
              />
              {localSearch && (
                <button
                  onClick={() => {
                    setLocalSearch('')
                    onSearchChange('')
                  }}
                  className="absolute right-2 top-1.5 text-slate-400 hover:text-white"
                  title="Clear search"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          )}
          {selectedIds.size > 0 && (
            <button
              onClick={() => setConfirmBulkModal(true)}
              disabled={actionInProgress !== null}
              className="btn-danger text-xs py-1 px-3 font-semibold flex items-center gap-1.5 shadow-sm"
              title="Delete only explicitly selected leads"
            >
              <Trash2 size={13} />
              <span>Delete Selected ({selectedIds.size})</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <div className="py-8 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
          <RefreshCw size={14} className="animate-spin text-amber-400" />
          <span>Loading review evidence…</span>
        </div>
      ) : records.length === 0 ? (
        <div className="py-8 text-center text-xs text-slate-400">
          <ShieldCheck size={24} className="mx-auto mb-2 text-emerald-400" />
          <p>No records currently require review in this queue.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {records.map(record => {
            const isSelected = selectedIds.has(record.lead_id)
            const isExpanded = expandedIds.has(record.lead_id)
            const isBusy = actionInProgress === record.lead_id

            return (
              <article
                key={record.lead_id}
                className={`rounded-lg border transition-all text-xs ${
                  isSelected
                    ? 'border-blue-700/70 bg-blue-950/20'
                    : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'
                } p-3.5`}
              >
                {/* Top Row: Checkbox, Business info, and Action Buttons */}
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                  <div className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelectOne(record.lead_id)}
                      className="mt-1 w-4 h-4 rounded accent-blue-600 cursor-pointer"
                      aria-label={`Select ${record.business_name}`}
                    />
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-100 text-sm">{record.business_name}</span>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${getActionBadge(record.recommended_action)}`}>
                          {(record.recommended_action || 'keep_for_review').replaceAll('_', ' ')}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 flex-wrap font-mono text-[11px] text-slate-400">
                        <span className="text-slate-300">{record.email || 'No email recorded'}</span>
                        <span>·</span>
                        <span className="text-slate-400">Verification: <strong className="text-slate-300">{record.verification_status || 'unverified'}</strong></span>
                        <span>·</span>
                        <span className="text-slate-400">Association: <strong className="text-slate-300">{record.association_status || 'unverified'}</strong></span>
                      </div>
                    </div>
                  </div>

                  {/* Operation Buttons */}
                  <div className="flex items-center gap-1.5 flex-wrap self-end sm:self-auto">
                    <button
                      onClick={() => handleSingleRetry(record.lead_id, false)}
                      disabled={isBusy}
                      className="btn-secondary text-[11px] py-1 px-2.5 font-medium flex items-center gap-1 disabled:opacity-40"
                      title="Retry bounded website discovery"
                    >
                      <RefreshCw size={11} className={isBusy ? 'animate-spin' : ''} />
                      <span>Retry Discovery</span>
                    </button>

                    <button
                      onClick={() => handleSingleRetry(record.lead_id, true)}
                      disabled={isBusy}
                      className="btn-secondary text-[11px] py-1 px-2.5 font-medium flex items-center gap-1 text-purple-300 hover:text-purple-200 disabled:opacity-40"
                      title="Re-verify email deliverability via DNS check without SMTP probe"
                    >
                      <Mail size={11} />
                      <span>Re-verify</span>
                    </button>

                    <button
                      onClick={() => handleSingleKeep(record.lead_id)}
                      disabled={isBusy}
                      className="btn-secondary text-[11px] py-1 px-2.5 font-medium flex items-center gap-1 text-amber-300 hover:text-amber-200 disabled:opacity-40"
                      title="Explicitly retain lead under operator review"
                    >
                      <Check size={11} />
                      <span>Keep in Review</span>
                    </button>

                    <button
                      onClick={() => handleSingleDelete(record.lead_id, record.business_name)}
                      disabled={isBusy}
                      className="p-1.5 text-rose-400 hover:text-rose-200 rounded hover:bg-rose-950/40 transition-colors disabled:opacity-40"
                      title="Delete this explicitly selected lead"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* Issue Tags */}
                <div className="mt-2.5 flex flex-wrap gap-1.5 text-[10px]">
                  {record.is_operational_queue && (
                    <span className="rounded border border-blue-800/60 bg-blue-950/40 px-2 py-0.5 text-blue-200 font-medium" title="Operational Gatekeeper hold: quarantined or unapproved association">
                      gatekeeper hold
                    </span>
                  )}
                  {record.is_data_repair_actionable && (
                    <span className="rounded border border-purple-800/60 bg-purple-950/40 px-2 py-0.5 text-purple-200 font-medium" title="Data-Repair Actionable: flagged by repair service heuristics">
                      data repair flagged
                    </span>
                  )}
                  {(record.issue_types || []).map(issue => (
                    <span
                      key={issue}
                      className="rounded border border-amber-800/60 bg-amber-950/30 px-2 py-0.5 text-amber-200 font-medium"
                    >
                      {issue.replaceAll('_', ' ')}
                    </span>
                  ))}
                  {record.is_quarantined && (
                    <span className="rounded border border-rose-800/60 bg-rose-950/30 px-2 py-0.5 text-rose-200 font-medium">
                      quarantined
                    </span>
                  )}
                </div>

                {/* Quarantine Reason */}
                {record.quarantine_reason && (
                  <div className="mt-2.5 flex items-start gap-1.5 text-[11px] text-rose-300 bg-rose-950/30 border border-rose-900/40 p-2 rounded">
                    <AlertTriangle size={13} className="shrink-0 mt-0.5 text-rose-400" />
                    <span>{record.quarantine_reason}</span>
                  </div>
                )}

                {/* Expand / Inspect Candidates & Provenance Toggle */}
                <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between">
                  <button
                    onClick={() => toggleExpand(record.lead_id)}
                    className="flex items-center gap-1.5 text-[11px] text-blue-400 hover:text-blue-300 font-semibold"
                  >
                    {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    <span>
                      {isExpanded ? 'Hide' : 'Inspect'} Candidates &amp; Provenance Evidence
                      ({(record.website_provenance || []).length} website candidates, {record.email_provenance?.candidate_count || 0} emails)
                    </span>
                  </button>

                  {record.most_recent_outcome && (
                    <span className="text-[10px] text-slate-500 font-mono truncate max-w-[280px]">
                      Outcome: {record.most_recent_outcome}
                    </span>
                  )}
                </div>

                {/* Expanded Provenance Inspection Details */}
                {isExpanded && (
                  <div className="mt-3 space-y-3 bg-slate-900/70 p-3 rounded-lg border border-slate-800 text-slate-300 text-[11px]">
                    {/* Recorded Website vs Source */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pb-2 border-b border-slate-800">
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-semibold">Recorded Website:</span>
                        {record.website ? (
                          <a
                            href={record.website}
                            target="_blank"
                            rel="noreferrer"
                            className="text-blue-400 hover:underline flex items-center gap-1 font-mono"
                          >
                            <Globe size={11} /> {record.website} <ExternalLink size={10} />
                          </a>
                        ) : (
                          <span className="text-slate-500 italic">None recorded</span>
                        )}
                        <span className="text-slate-500 text-[10px] block mt-0.5">Status: {record.website_status || 'unverified'}</span>
                      </div>

                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase font-semibold">Email Source Provenance:</span>
                        {record.email_provenance?.source_url ? (
                          <a
                            href={record.email_provenance.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-blue-400 hover:underline flex items-center gap-1 font-mono truncate"
                          >
                            <FileText size={11} /> {record.email_provenance.source_url} <ExternalLink size={10} />
                          </a>
                        ) : (
                          <span className="text-slate-500 italic">No directory/source URL captured</span>
                        )}
                        <span className="text-slate-500 text-[10px] block mt-0.5">Type: {record.email_provenance?.source_type || 'unspecified'}</span>
                      </div>
                    </div>

                    {/* Discovered Website Candidates */}
                    <div>
                      <h4 className="text-[10px] uppercase font-bold text-slate-400 mb-1.5 flex items-center gap-1">
                        <Globe size={11} /> Website Candidates ({(record.website_provenance || []).length})
                      </h4>
                      {(record.website_provenance || []).length === 0 ? (
                        <p className="text-slate-500 italic text-[10px]">No website candidates discovered yet.</p>
                      ) : (
                        <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                          {record.website_provenance.map((c, i) => (
                            <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 p-1.5 bg-slate-950/60 rounded border border-slate-800 text-[10px]">
                              <div className="flex items-center gap-1.5 font-mono truncate max-w-sm">
                                <span className="text-blue-300 truncate">{c.url || c.domain || '(No URL)'}</span>
                                <span className="text-slate-500">[{c.source || 'unknown'}]</span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <span className="rounded bg-slate-800 px-1.5 py-0.2 text-slate-300 font-mono">{c.status || 'unverified'}</span>
                                {c.reason && <span className="text-slate-400 truncate max-w-[180px]" title={c.reason}>{c.reason}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Discovered Email Candidates */}
                    <div>
                      <h4 className="text-[10px] uppercase font-bold text-slate-400 mb-1.5 flex items-center gap-1">
                        <Mail size={11} /> Email Candidates ({(record.email_provenance?.candidates || []).length})
                      </h4>
                      {(record.email_provenance?.candidates || []).length === 0 ? (
                        <p className="text-slate-500 italic text-[10px]">No competing email candidates discovered.</p>
                      ) : (
                        <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                          {record.email_provenance.candidates.map((c, i) => (
                            <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 p-1.5 bg-slate-950/60 rounded border border-slate-800 text-[10px]">
                              <div className="flex items-center gap-1.5 font-mono truncate max-w-sm">
                                <span className="text-emerald-300">{c.email}</span>
                                {c.source_url && (
                                  <a href={c.source_url} target="_blank" rel="noreferrer" className="text-slate-500 hover:text-slate-300 truncate" title={c.source_url}>
                                    ({c.source_url})
                                  </a>
                                )}
                              </div>
                              <span className="text-slate-400 text-[10px] truncate max-w-[200px]" title={c.association_reason}>
                                {c.association_reason || c.association_status || 'candidate'}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Evidence Reasoning */}
                    {(record.evidence || []).length > 0 && (
                      <div className="pt-1.5 border-t border-slate-800 text-[10px]">
                        <span className="text-slate-400 font-semibold block mb-0.5">Classification Evidence:</span>
                        <ul className="list-disc list-inside space-y-0.5 text-slate-400">
                          {record.evidence.map((ev, i) => (
                            <li key={i}>{ev.replaceAll('_', ' ')}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {/* ── Pagination ── */}
      {total > pageSize && (
        <div className="flex flex-col sm:flex-row justify-between items-center gap-3 pt-2 text-xs text-slate-400 border-t border-amber-900/30">
          <p>
            Showing {((page - 1) * pageSize + 1).toLocaleString()}–
            {Math.min(page * pageSize, total).toLocaleString()} of {total.toLocaleString()} unresolved leads
          </p>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange(Math.max(1, page - 1))}
              disabled={page <= 1 || loading}
              className="btn-secondary text-xs py-1 px-3 font-semibold disabled:opacity-40"
            >
              Previous
            </button>
            <span className="px-2 font-mono text-slate-300">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages || loading}
              className="btn-secondary text-xs py-1 px-3 font-semibold disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* ── Bulk Delete Confirmation Modal ── */}
      {confirmBulkModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="card-elevated border-rose-800/80 bg-slate-900 max-w-lg w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2 text-rose-400 font-bold text-sm">
              <AlertTriangle size={18} />
              <span>Confirm Explicit Bulk Deletion</span>
            </div>

            <p className="text-xs text-slate-300">
              You have explicitly selected <strong className="text-white">{selectedIds.size}</strong> unresolved lead(s) for permanent deletion.
              Associated audits, proposals, and corrections will be cascaded, while activity log history and campaign referential integrity are preserved.
            </p>

            <div className="max-h-40 overflow-y-auto bg-slate-950 p-2.5 rounded border border-slate-800 text-[11px] text-slate-300 space-y-1">
              <span className="text-[10px] uppercase font-semibold text-slate-500 block mb-1">Selected leads to delete:</span>
              {selectedRecords.slice(0, 10).map(r => (
                <div key={r.lead_id} className="truncate">
                  • <strong>{r.business_name}</strong> <span className="text-slate-500 font-mono">({r.email || 'no email'})</span>
                </div>
              ))}
              {selectedRecords.length > 10 && (
                <div className="text-slate-500 italic text-[10px]">
                  … and {selectedRecords.length - 10} more selected leads.
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
              <button
                onClick={() => setConfirmBulkModal(false)}
                className="btn-secondary text-xs py-1.5 px-3 font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={executeBulkDelete}
                className="btn-danger text-xs py-1.5 px-3 font-semibold flex items-center gap-1.5"
              >
                <Trash2 size={13} />
                <span>Confirm Delete {selectedIds.size} Leads</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
