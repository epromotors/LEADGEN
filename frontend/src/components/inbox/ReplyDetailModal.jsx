import React from 'react'
import { X, ArrowLeftRight, Mail, ExternalLink, Calendar, CheckCircle2, Clock, AlertTriangle } from 'lucide-react'

function ReplyBadge({ type }) {
  const norm = (type || 'other').toLowerCase()
  if (norm === 'positive' || norm === 'converted') {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
        <CheckCircle2 size={12} /> Positive (YES / Interested)
      </span>
    )
  }
  if (norm === 'soft_bounce') {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30">
        <Clock size={12} /> Out of Office / Soft Bounce
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-800 text-slate-300 border border-slate-700">
      <Mail size={12} /> General Reply / Other
    </span>
  )
}

export default function ReplyDetailModal({ lead, onClose, onReclassify, reclassifying }) {
  if (!lead) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="card-elevated border border-slate-700/80 w-full max-w-xl p-6 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>

        <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-800">
          <div>
            <h3 className="text-base font-bold text-slate-100">{lead.business_name}</h3>
            <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
              <a href={`mailto:${lead.email}`} className="text-blue-400 hover:underline">
                {lead.email}
              </a>
              {lead.website && (
                <>
                  <span className="text-slate-600">·</span>
                  <a
                    href={lead.website}
                    target="_blank"
                    rel="noreferrer"
                    className="text-slate-300 hover:text-blue-300 flex items-center gap-1"
                  >
                    <span>{lead.website.replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0]}</span>
                    <ExternalLink size={10} />
                  </a>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Classification status & timestamp */}
        <div className="flex items-center justify-between p-3 bg-slate-900/80 border border-slate-800 rounded-lg mb-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-slate-400 font-semibold text-[11px] uppercase tracking-wider">Classification:</span>
            <ReplyBadge type={lead.reply_type || lead.status} />
          </div>
          {lead.replied_at && (
            <span className="text-slate-400 text-[11px] flex items-center gap-1">
              <Calendar size={11} className="text-slate-500" />
              {new Date(lead.replied_at).toLocaleString('en-IN', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          )}
        </div>

        {/* Reply Body Content */}
        <div className="mb-4">
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
            Captured Message Body (First 500 chars)
          </label>
          <div className="p-4 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono leading-relaxed text-slate-200 min-h-[120px] max-h-60 overflow-y-auto whitespace-pre-wrap">
            {lead.reply_snippet || (
              <span className="text-slate-500 italic">No message snippet was captured for this reply.</span>
            )}
          </div>
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-between pt-3 border-t border-slate-800">
          <div className="text-[11px] text-slate-500">
            {lead.status === 'converted' ? (
              <span>Demoting removes from Converted list without deleting the lead.</span>
            ) : (
              <span>Lead is preserved in database.</span>
            )}
          </div>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary text-xs py-2 px-4"
            >
              Close
            </button>

            {lead.status === 'converted' && (
              <button
                type="button"
                onClick={() => onReclassify(lead)}
                disabled={reclassifying}
                className="inline-flex items-center gap-1.5 text-xs py-2 px-4 rounded-md font-semibold bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/25 transition-colors disabled:opacity-50"
              >
                <ArrowLeftRight size={13} className={reclassifying ? 'animate-spin' : ''} />
                {reclassifying ? 'Reclassifying…' : 'Move to Other'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
