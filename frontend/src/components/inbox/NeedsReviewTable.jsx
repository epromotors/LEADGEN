import React, { useState } from 'react'
import {
  Eye, ShieldOff, CheckCircle2, AlertTriangle,
  HelpCircle, ChevronLeft, ChevronRight, Loader2,
} from 'lucide-react'

// ─── Category badge ──────────────────────────────────────────────────────────
function CategoryBadge({ category, source }) {
  const cat = (category || 'other').toLowerCase()
  const src = (source || '').toLowerCase()

  const map = {
    converted:         { label: 'Converted',          cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
    hot_lead:          { label: 'Hot Lead',            cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
    question:          { label: 'Question',            cls: 'bg-blue-500/15 text-blue-300 border-blue-500/30' },
    referral:          { label: 'Referral',            cls: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
    not_now:           { label: 'Not Now',             cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
    out_of_office:     { label: 'Out of Office',       cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
    generic_auto_reply:{ label: 'Auto-Reply',          cls: 'bg-slate-700 text-slate-300 border-slate-600' },
    soft_bounce:       { label: 'Soft Bounce',         cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
    hard_bounce:       { label: 'Hard Bounce',         cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
    unsubscribe:       { label: 'Unsubscribe',         cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
    not_interested:    { label: 'Not Interested',      cls: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
    complaint:         { label: 'Complaint',           cls: 'bg-rose-600/20 text-rose-200 border-rose-500/40' },
    wrong_person:      { label: 'Wrong Person',        cls: 'bg-slate-700 text-slate-300 border-slate-600' },
    other:             { label: 'Other',               cls: 'bg-slate-700 text-slate-300 border-slate-600' },
    needs_review:      { label: 'Needs Review',        cls: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  }
  const { label, cls } = map[cat] || map.other
  const srcLabel = src ? ` · ${src}` : ''

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${cls}`}>
      {label}{srcLabel}
    </span>
  )
}

// ─── Confidence bar ───────────────────────────────────────────────────────────
function ConfidenceBar({ value }) {
  if (value == null) return <span className="text-slate-500 text-xs">—</span>
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 45 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-slate-400 tabular-nums w-7 text-right">{pct}%</span>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function NeedsReviewTable({
  leads = [],
  total = 0,
  page = 1,
  pageSize = 50,
  onPageChange,
  onClearReview,   // fn(lead, unSuppress)
  onPreview,
  clearing,        // Set<id> of leads being cleared
  loading,
}) {
  const [expandedId, setExpandedId] = useState(null)
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  if (loading) {
    return (
      <div className="card-elevated p-10 flex items-center justify-center">
        <Loader2 size={22} className="animate-spin text-slate-400" />
        <span className="ml-3 text-slate-400 text-sm">Loading flagged leads…</span>
      </div>
    )
  }

  if (leads.length === 0) {
    return (
      <div className="card-elevated p-10 text-center space-y-2">
        <CheckCircle2 size={32} className="text-emerald-400 mx-auto" />
        <p className="text-sm font-semibold text-slate-300">No leads pending review</p>
        <p className="text-xs text-slate-500">
          All AI classifications were high-confidence, or <code>REPLY_AI_MODE</code> is off.
        </p>
      </div>
    )
  }

  return (
    <div className="card-elevated p-0 overflow-hidden border border-slate-800">
      {/* Header */}
      <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <span className="text-sm font-bold text-orange-300 flex items-center gap-2">
            <AlertTriangle size={15} className="text-orange-400" />
            {total} lead{total !== 1 ? 's' : ''} flagged for review
          </span>
          <p className="text-xs text-slate-400 mt-0.5">
            Low-confidence or ambiguous AI classifications — automated outreach is paused until cleared.
          </p>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/40">
              <th className="text-left px-4 py-2.5 text-slate-400 font-semibold uppercase tracking-wider">Lead</th>
              <th className="text-left px-3 py-2.5 text-slate-400 font-semibold uppercase tracking-wider">AI Category</th>
              <th className="text-left px-3 py-2.5 text-slate-400 font-semibold uppercase tracking-wider">Confidence</th>
              <th className="text-left px-3 py-2.5 text-slate-400 font-semibold uppercase tracking-wider hidden lg:table-cell">Reasoning</th>
              <th className="text-left px-3 py-2.5 text-slate-400 font-semibold uppercase tracking-wider">Suppressed?</th>
              <th className="text-right px-4 py-2.5 text-slate-400 font-semibold uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {leads.map(lead => {
              const isClearing = clearing?.has(lead.id)
              const isExpanded = expandedId === lead.id
              return (
                <React.Fragment key={lead.id}>
                  <tr className="hover:bg-slate-800/30 transition-colors">
                    {/* Lead info */}
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-200 truncate max-w-[180px]" title={lead.business_name}>
                        {lead.business_name || '—'}
                      </div>
                      <div className="text-slate-500 truncate max-w-[180px]" title={lead.email}>
                        {lead.email}
                      </div>
                      {lead.replied_at && (
                        <div className="text-slate-600 mt-0.5">
                          {new Date(lead.replied_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                        </div>
                      )}
                    </td>

                    {/* Category */}
                    <td className="px-3 py-3">
                      <CategoryBadge category={lead.reply_category || lead.reply_type} source={lead.reply_source} />
                    </td>

                    {/* Confidence */}
                    <td className="px-3 py-3">
                      <ConfidenceBar value={lead.reply_confidence} />
                    </td>

                    {/* Reasoning (hidden on small screens) */}
                    <td className="px-3 py-3 hidden lg:table-cell max-w-[220px]">
                      {lead.reply_reasoning ? (
                        <span className="text-slate-400 leading-relaxed line-clamp-2" title={lead.reply_reasoning}>
                          {lead.reply_reasoning}
                        </span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>

                    {/* Suppressed badge */}
                    <td className="px-3 py-3">
                      {lead.is_suppressed ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30">
                          <ShieldOff size={10} /> Suppressed
                        </span>
                      ) : (
                        <span className="text-slate-600 text-[10px]">No</span>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {/* Snippet expand */}
                        {lead.reply_snippet && (
                          <button
                            type="button"
                            onClick={() => setExpandedId(isExpanded ? null : lead.id)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
                            title="View reply snippet"
                          >
                            <Eye size={13} />
                          </button>
                        )}
                        {/* Inspect in detail modal */}
                        {onPreview && (
                          <button
                            type="button"
                            onClick={() => onPreview(lead)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
                            title="Full lead detail"
                          >
                            <HelpCircle size={13} />
                          </button>
                        )}
                        {/* Clear review (keep suppression) */}
                        <button
                          type="button"
                          disabled={isClearing}
                          onClick={() => onClearReview(lead, false)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors disabled:opacity-50"
                          title="Mark reviewed — resume outreach eligibility check"
                        >
                          {isClearing ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
                          Clear
                        </button>
                        {/* Override & un-suppress (only shown when suppressed) */}
                        {lead.is_suppressed && (
                          <button
                            type="button"
                            disabled={isClearing}
                            onClick={() => onClearReview(lead, true)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-orange-900/40 hover:bg-orange-800/50 text-orange-300 border border-orange-700/40 transition-colors disabled:opacity-50"
                            title="Override AI decision: clear flag AND remove suppression"
                          >
                            {isClearing ? <Loader2 size={11} className="animate-spin" /> : <ShieldOff size={11} />}
                            Override & Un-suppress
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>

                  {/* Expanded snippet row */}
                  {isExpanded && lead.reply_snippet && (
                    <tr className="bg-slate-900/60">
                      <td colSpan={6} className="px-6 py-3">
                        <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider mb-1">Reply snippet</p>
                        <p className="text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed max-h-32 overflow-y-auto">
                          {lead.reply_snippet}
                        </p>
                        {lead.reply_reasoning && (
                          <p className="text-xs text-orange-400/80 mt-1.5 italic">
                            AI reasoning: {lead.reply_reasoning}
                          </p>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="p-3 border-t border-slate-800 flex items-center justify-between bg-slate-900/40">
          <span className="text-xs text-slate-500">
            Page {page} of {totalPages} · {total} total
          </span>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => onPageChange?.(page - 1)}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40 transition-colors"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => onPageChange?.(page + 1)}
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40 transition-colors"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
