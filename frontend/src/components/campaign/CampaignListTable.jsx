import React, { useState, useEffect } from 'react'
import {
  ChevronDown, ChevronRight, Send, Pause, Play, RotateCcw,
  Trash2, Users, Clock, Mail, CheckCircle2, AlertTriangle,
  RefreshCw, Filter, Search, Sparkles
} from 'lucide-react'
import CampaignLogsViewer from './CampaignLogsViewer'

const STATUS_BADGE = {
  draft: 'bg-slate-800 text-slate-300 border-slate-700',
  scheduled: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  sending: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  paused: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  done: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
}

function useCountdown(nextEmailAt) {
  const [remaining, setRemaining] = useState(null)
  useEffect(() => {
    if (!nextEmailAt) {
      setRemaining(null)
      return
    }
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
  if (ms === 0) {
    return <span className="text-blue-400 text-xs font-medium">⏳ Dispatching email now…</span>
  }
  const mins = Math.floor(ms / 60000)
  const secs = Math.floor((ms % 60000) / 1000)
  return (
    <span className="inline-flex items-center gap-1 text-slate-400 text-xs font-mono">
      <Clock size={11} className="text-blue-400" />
      Next in {mins}m {secs}s
    </span>
  )
}

export default function CampaignListTable({
  campaigns = [],
  onAction,
  onRetryFailed,
  onRecalculate,
  actionLoading,
}) {
  const [expandedId, setExpandedId] = useState(null)
  const [statusFilter, setStatusFilter] = useState('all') // 'all' | 'sending' | 'paused' | 'done' | 'draft'
  const [searchQuery, setSearchQuery] = useState('')

  const filteredCampaigns = campaigns.filter(c => {
    if (statusFilter !== 'all' && c.status !== statusFilter) return false
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      const matchName = (c.name || '').toLowerCase().includes(q)
      const matchType = (c.campaign_type || '').toLowerCase().includes(q)
      if (!matchName && !matchType) return false
    }
    return true
  })

  return (
    <div className="card-elevated p-0 overflow-hidden border border-slate-800">
      {/* Header & Filter Bar */}
      <div className="p-4 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-2">
            Filter:
          </span>
          {[
            { id: 'all', label: `All (${campaigns.length})` },
            { id: 'sending', label: `Sending (${campaigns.filter(c => c.status === 'sending').length})`, color: 'text-blue-400' },
            { id: 'paused', label: `Paused (${campaigns.filter(c => c.status === 'paused').length})`, color: 'text-amber-400' },
            { id: 'done', label: `Done (${campaigns.filter(c => c.status === 'done').length})`, color: 'text-emerald-400' },
            { id: 'draft', label: `Draft (${campaigns.filter(c => c.status === 'draft').length})`, color: 'text-slate-400' },
          ].map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setStatusFilter(tab.id)}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                statusFilter === tab.id
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
            placeholder="Search campaigns…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="text-xs bg-slate-900 border border-slate-700/80 rounded-md pl-8 pr-3 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-52"
          />
        </div>
      </div>

      {/* Campaigns Table */}
      {filteredCampaigns.length === 0 ? (
        <div className="p-12 text-center text-slate-400">
          <Mail size={32} className="mx-auto text-slate-600 mb-3 opacity-40" />
          <p className="text-sm font-semibold text-slate-300 mb-1">No campaigns found</p>
          <p className="text-xs text-slate-500">
            {campaigns.length === 0
              ? 'Create your first personalized cold outreach campaign to begin.'
              : `No campaigns match filter '${statusFilter}'.`}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-900/40 border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                <th className="py-3 px-3 w-8"></th>
                <th className="py-3 px-4">Campaign &amp; Strategy</th>
                <th className="py-3 px-3">Audience</th>
                <th className="py-3 px-4 min-w-[180px]">Delivery Progress</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3">Created</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredCampaigns.map(c => {
                const total = c.lead_ids?.length || 0
                const sent = c.sent_count || 0
                const failed = c.failed_count || 0
                const skipped = c.skipped_count || 0
                const pct = total > 0 ? Math.min(100, Math.round((sent / total) * 100)) : 0
                const isExpanded = expandedId === c.id
                const isSending = c.status === 'sending'
                const isPaused = c.status === 'paused'
                const isDraft = c.status === 'draft'
                const isDone = c.status === 'done'
                const badgeStyle = STATUS_BADGE[c.status] || STATUS_BADGE.draft

                return (
                  <React.Fragment key={c.id}>
                    <tr
                      className={`hover:bg-slate-900/40 transition-colors ${
                        isExpanded ? 'bg-slate-900/30' : ''
                      }`}
                    >
                      <td className="py-3 px-3">
                        <button
                          type="button"
                          onClick={() => setExpandedId(isExpanded ? null : c.id)}
                          className="p-1 text-slate-400 hover:text-slate-200 transition-colors"
                          title={isExpanded ? 'Collapse logs' : 'Expand recipient logs'}
                        >
                          {isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        </button>
                      </td>

                      <td className="py-3 px-4">
                        <div className="font-semibold text-slate-100 text-sm flex items-center gap-2">
                          <span>{c.name}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className="text-[10px] font-medium text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                            {(c.campaign_type || 'generic_first_contact').replace(/_/g, ' ')}
                          </span>
                          {isSending && <CountdownDisplay nextEmailAt={c.next_email_at} />}
                          {isPaused && (
                            <span className="text-[10px] text-amber-400 flex items-center gap-1 font-medium">
                              ⏸ Paused ({c.pending_lead_ids?.length || 0} queued)
                            </span>
                          )}
                        </div>
                      </td>

                      <td className="py-3 px-3 whitespace-nowrap text-slate-300">
                        <span className="inline-flex items-center gap-1 font-semibold text-slate-200">
                          <Users size={12} className="text-slate-400" />
                          {total.toLocaleString()}
                        </span>
                      </td>

                      <td className="py-3 px-4">
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-slate-300 font-medium">{pct}%</span>
                            <span className="text-slate-400 font-mono text-[10px]">
                              {sent}/{total} sent
                              {skipped > 0 && <span className="text-amber-400 ml-1">· {skipped} skip</span>}
                              {failed > 0 && <span className="text-rose-400 ml-1">· {failed} err</span>}
                            </span>
                          </div>
                          <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden flex">
                            <div
                              style={{ width: `${pct}%` }}
                              className={`h-full transition-all duration-300 ${
                                isDone ? 'bg-emerald-500' : 'bg-blue-500'
                              }`}
                            />
                            {failed > 0 && total > 0 && (
                              <div
                                style={{ width: `${Math.round((failed / total) * 100)}%` }}
                                className="h-full bg-rose-500/80"
                              />
                            )}
                          </div>
                        </div>
                      </td>

                      <td className="py-3 px-3 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-wide ${badgeStyle}`}>
                          {isSending && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
                          {c.status}
                        </span>
                      </td>

                      <td className="py-3 px-3 text-slate-400 whitespace-nowrap text-[11px]">
                        {new Date(c.created_at).toLocaleDateString('en-IN', {
                          day: 'numeric',
                          month: 'short',
                          year: 'numeric',
                        })}
                      </td>

                      <td className="py-3 px-4 text-right">
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          {isDraft && (
                            <button
                              type="button"
                              onClick={() => onAction('send', c)}
                              disabled={actionLoading}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
                              title="Launch outreach"
                            >
                              <Send size={11} /> Launch
                            </button>
                          )}

                          {isSending && (
                            <button
                              type="button"
                              onClick={() => onAction('pause', c)}
                              disabled={actionLoading}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/25 transition-colors disabled:opacity-50"
                              title="Pause sending"
                            >
                              <Pause size={11} /> Pause
                            </button>
                          )}

                          {isPaused && (
                            <button
                              type="button"
                              onClick={() => onAction('resume', c)}
                              disabled={actionLoading}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/25 transition-colors disabled:opacity-50"
                              title="Resume sending"
                            >
                              <Play size={11} /> Resume
                            </button>
                          )}

                          {failed > 0 && !isSending && (
                            <button
                              type="button"
                              onClick={() => onRetryFailed(c)}
                              disabled={actionLoading}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold bg-rose-500/15 border border-rose-500/30 text-rose-300 hover:bg-rose-500/25 transition-colors disabled:opacity-50"
                              title={`Retry ${failed} failed leads`}
                            >
                              <RotateCcw size={11} /> Retry {failed}
                            </button>
                          )}

                          {(isDone || isSending || isPaused) && (
                            <button
                              type="button"
                              onClick={() => onAction('reset', c)}
                              disabled={actionLoading}
                              className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                              title="Reset to draft"
                            >
                              <RotateCcw size={12} />
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => onRecalculate && onRecalculate(c)}
                            disabled={actionLoading}
                            className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                            title="Recalculate counts from logs"
                          >
                            <RefreshCw size={12} />
                          </button>

                          {!isSending && (
                            <button
                              type="button"
                              onClick={() => onAction('delete', c)}
                              disabled={actionLoading}
                              className="p-1.5 rounded-md text-rose-400/80 hover:text-rose-300 hover:bg-rose-950/20 transition-colors"
                              title="Delete campaign"
                            >
                              <Trash2 size={12} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Expandable Recipient Delivery Logs */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={7} className="p-0 bg-slate-950/40">
                          <CampaignLogsViewer
                            campaignId={c.id}
                            onRetryDone={() => onRetryFailed && onRetryFailed(c, true)}
                          />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
