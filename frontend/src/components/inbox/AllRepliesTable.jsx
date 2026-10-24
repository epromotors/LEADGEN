import React, { useState } from 'react'
import {
  Inbox, Eye, Search, ExternalLink, Mail, Trash2,
  ArrowLeftRight, CheckCircle2, Clock, AlertTriangle,
  Send, Info, ShieldCheck
} from 'lucide-react'

function ReplyTypeBadge({ type, status }) {
  const norm = (type || status || 'other').toLowerCase()
  if (norm === 'positive' || norm === 'converted') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
        <CheckCircle2 size={11} /> Positive (YES)
      </span>
    )
  }
  if (norm === 'soft_bounce') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30">
        <Clock size={11} /> Out of Office
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-400 border border-slate-700">
      <Mail size={11} /> Other / General
    </span>
  )
}

export default function AllRepliesTable({
  replies = [],
  total = 0,
  onPreview,
  onCompose,
  onReclassify,
  onDelete,
  loading,
}) {
  const [filterType, setFilterType] = useState('all') // 'all' | 'positive' | 'soft_bounce' | 'other'
  const [search, setSearch] = useState('')

  const filtered = replies.filter(lead => {
    const rType = (lead.reply_type || lead.status || '').toLowerCase()
    if (filterType === 'positive' && rType !== 'positive' && rType !== 'converted') return false
    if (filterType === 'soft_bounce' && rType !== 'soft_bounce') return false
    if (filterType === 'other' && (rType === 'positive' || rType === 'converted' || rType === 'soft_bounce')) return false

    if (search.trim()) {
      const q = search.toLowerCase().trim()
      const matchName = (lead.business_name || '').toLowerCase().includes(q)
      const matchEmail = (lead.email || '').toLowerCase().includes(q)
      const matchSnippet = (lead.reply_snippet || '').toLowerCase().includes(q)
      if (!matchName && !matchEmail && !matchSnippet) return false
    }
    return true
  })

  const positiveCount = replies.filter(r => (r.reply_type === 'positive' || r.status === 'converted')).length
  const softBounceCount = replies.filter(r => r.reply_type === 'soft_bounce').length
  const otherCount = replies.filter(r => r.reply_type === 'other' || (!r.reply_type && r.status !== 'converted')).length

  return (
    <div className="card-elevated p-0 overflow-hidden border border-slate-800">
      {/* Header & Filter Controls */}
      <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-2">
            Classification:
          </span>
          {[
            { id: 'all', label: `All Ingested (${replies.length})` },
            { id: 'positive', label: `Positive (${positiveCount})`, color: 'text-emerald-400' },
            { id: 'soft_bounce', label: `Out of Office (${softBounceCount})`, color: 'text-amber-400' },
            { id: 'other', label: `Other (${otherCount})`, color: 'text-slate-400' },
          ].map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setFilterType(tab.id)}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                filterType === tab.id
                  ? 'bg-blue-600/20 text-blue-300 border border-blue-500/40'
                  : 'text-slate-400 hover:text-slate-200 border border-transparent'
              } ${tab.color || ''}`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
          <input
            type="text"
            placeholder="Search all replies…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="text-xs bg-slate-900 border border-slate-700/80 rounded-md pl-8 pr-3 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-56"
          />
        </div>
      </div>

      {/* Suppression Notice Banner */}
      <div className="px-4 py-2.5 bg-slate-950/70 border-b border-slate-800 text-[11px] text-slate-400 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck size={13} className="text-emerald-400 shrink-0" />
          <span>
            <strong className="text-slate-300">Compliance &amp; Suppression:</strong> STOP / Unsubscribe requests and hard bounce signals are automatically purged from the active database upon IMAP sync to enforce recipient opt-outs.
          </span>
        </div>
      </div>

      {/* Table / Empty */}
      {filtered.length === 0 ? (
        <div className="p-16 text-center text-slate-400">
          <Inbox size={36} className="mx-auto text-slate-600 mb-3 opacity-40" />
          <p className="text-sm font-semibold text-slate-300 mb-1">No replies matching filter</p>
          <p className="text-xs text-slate-500">
            {replies.length === 0
              ? 'No incoming replies have been captured yet. Run an Inbox Sync to check Hostinger mail.'
              : `Zero replies categorized under '${filterType}'.`}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-900/40 border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                <th className="py-3 px-4">Sender / Lead</th>
                <th className="py-3 px-4">Contact Route</th>
                <th className="py-3 px-4">Classification</th>
                <th className="py-3 px-4 max-w-[280px]">Reply Snippet</th>
                <th className="py-3 px-4">Received</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filtered.map(lead => {
                const isConverted = lead.status === 'converted' || lead.reply_type === 'positive'

                return (
                  <tr
                    key={lead.id}
                    className="hover:bg-slate-900/40 transition-colors group"
                  >
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-200">{lead.business_name}</div>
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      <a
                        href={`mailto:${lead.email}`}
                        className="text-slate-400 hover:text-blue-400 font-medium"
                      >
                        {lead.email}
                      </a>
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      <ReplyTypeBadge type={lead.reply_type} status={lead.status} />
                    </td>

                    <td className="py-3 px-4 max-w-[280px]">
                      {lead.reply_snippet ? (
                        <button
                          type="button"
                          onClick={() => onPreview(lead)}
                          className="text-left text-xs text-slate-300 hover:text-white transition-colors truncate block w-full"
                          title="Click to view full reply message"
                        >
                          <span className="italic">"{lead.reply_snippet}"</span>
                        </button>
                      ) : (
                        <span className="text-slate-500 italic text-[11px]">No snippet text</span>
                      )}
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap text-slate-400 text-[11px]">
                      {lead.replied_at
                        ? new Date(lead.replied_at).toLocaleDateString('en-IN', {
                            day: 'numeric',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>

                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        {isConverted && (
                          <button
                            type="button"
                            onClick={() => onCompose(lead)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                            title="Compose Email 2 proposal"
                          >
                            <Send size={11} /> Email 2
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => onPreview(lead)}
                          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                          title="View message"
                        >
                          <Eye size={13} />
                        </button>

                        {isConverted && (
                          <button
                            type="button"
                            onClick={() => onReclassify(lead)}
                            className="p-1.5 rounded-md text-amber-400/80 hover:text-amber-300 hover:bg-amber-950/20 transition-colors"
                            title="Move to other"
                          >
                            <ArrowLeftRight size={13} />
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => onDelete(lead.id, lead.business_name)}
                          className="p-1.5 rounded-md text-rose-400/80 hover:text-rose-300 hover:bg-rose-950/20 transition-colors"
                          title="Delete lead permanently"
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
      )}
    </div>
  )
}
