import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingUp, Eye, Send, Search, ChevronLeft, ChevronRight,
  ExternalLink, Mail, Trash2, ArrowLeftRight, CheckCircle2,
  Calendar, FileText
} from 'lucide-react'

export default function ConvertedLeadsTable({
  leads = [],
  total = 0,
  page = 1,
  pageSize = 25,
  setPage,
  onPreview,
  onCompose,
  onReclassify,
  onDelete,
  loading,
}) {
  const [search, setSearch] = useState('')
  const totalPages = Math.ceil(total / pageSize) || 1

  const filtered = leads.filter(l => {
    if (!search.trim()) return true
    const q = search.toLowerCase().trim()
    const nameMatch = (l.business_name || '').toLowerCase().includes(q)
    const emailMatch = (l.email || '').toLowerCase().includes(q)
    const snippetMatch = (l.reply_snippet || '').toLowerCase().includes(q)
    return nameMatch || emailMatch || snippetMatch
  })

  return (
    <div className="card-elevated p-0 overflow-hidden border border-slate-800">
      {/* Top Header & Search */}
      <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-emerald-400" />
          <h2 className="text-sm font-bold text-slate-100">
            Converted Leads ({total} total hot prospects)
          </h2>
        </div>

        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
          <input
            type="text"
            placeholder="Search converted leads…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="text-xs bg-slate-900 border border-slate-700/80 rounded-md pl-8 pr-3 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-56"
          />
        </div>
      </div>

      {/* Table / Empty State */}
      {leads.length === 0 && !loading ? (
        <div className="p-16 text-center text-slate-400">
          <CheckCircle2 size={36} className="mx-auto text-emerald-500/40 mb-3" />
          <p className="text-sm font-semibold text-slate-200 mb-1">No converted leads yet</p>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">
            When prospects reply positively (e.g., "YES", "interested", "send quote"), they are automatically promoted to Converted.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-900/40 border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                <th className="py-3 px-4">Prospect Business</th>
                <th className="py-3 px-4">Contact Route</th>
                <th className="py-3 px-4">Website</th>
                <th className="py-3 px-4 max-w-[260px]">Reply Snippet</th>
                <th className="py-3 px-4">Replied At</th>
                <th className="py-3 px-4 text-right">Outreach Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filtered.map(lead => {
                const domainStr = (lead.website || '')
                  .replace(/^https?:\/\//, '')
                  .replace(/^www\./, '')
                  .split('/')[0]

                return (
                  <tr
                    key={lead.id}
                    className="hover:bg-slate-900/40 transition-colors group"
                  >
                    <td className="py-3 px-4">
                      <div className="font-semibold text-slate-100 text-sm">
                        {lead.business_name}
                      </div>
                      <div className="text-[10px] text-emerald-400 font-bold mt-0.5 flex items-center gap-1">
                        <CheckCircle2 size={10} /> POSITIVE REPLY
                      </div>
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      <a
                        href={`mailto:${lead.email}`}
                        className="text-slate-300 hover:text-blue-400 font-medium"
                      >
                        {lead.email}
                      </a>
                    </td>

                    <td className="py-3 px-4 whitespace-nowrap">
                      {lead.website ? (
                        <a
                          href={lead.website}
                          target="_blank"
                          rel="noreferrer"
                          className="text-slate-400 hover:text-blue-300 flex items-center gap-1 max-w-[140px] truncate"
                          title={lead.website}
                        >
                          <span className="truncate">{domainStr}</span>
                          <ExternalLink size={10} className="shrink-0 text-slate-500" />
                        </a>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>

                    <td className="py-3 px-4 max-w-[260px]">
                      {lead.reply_snippet ? (
                        <button
                          type="button"
                          onClick={() => onPreview(lead)}
                          className="text-left text-xs text-slate-300 hover:text-white transition-colors truncate block w-full group-hover:text-blue-200"
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
                            year: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>

                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        <button
                          type="button"
                          onClick={() => onCompose(lead)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                          title="Preview & send Email 2 proposal"
                        >
                          <Send size={11} /> Compose Email 2
                        </button>

                        <button
                          type="button"
                          onClick={() => onPreview(lead)}
                          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                          title="View reply message"
                        >
                          <Eye size={13} />
                        </button>

                        <Link
                          to={`/audits`}
                          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                          title="View audit findings"
                        >
                          <FileText size={13} />
                        </Link>

                        <button
                          type="button"
                          onClick={() => onReclassify(lead)}
                          className="p-1.5 rounded-md text-amber-400/80 hover:text-amber-300 hover:bg-amber-950/20 transition-colors"
                          title="Move to other (false positive)"
                        >
                          <ArrowLeftRight size={13} />
                        </button>

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

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="p-3 bg-slate-900/60 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
          <div>
            Showing Page <strong className="text-slate-200">{page}</strong> of{' '}
            <strong className="text-slate-200">{totalPages}</strong> ({total} leads)
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1.5 rounded border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-40"
            >
              <ChevronLeft size={13} />
            </button>
            <button
              type="button"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-40"
            >
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
