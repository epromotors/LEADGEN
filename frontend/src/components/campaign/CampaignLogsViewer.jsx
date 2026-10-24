import React, { useState, useEffect, useMemo } from 'react'
import {
  CheckCircle2, AlertCircle, SkipForward, RotateCcw, Search,
  Filter, Mail, Server, Clock, AlertTriangle, ShieldAlert
} from 'lucide-react'
import toast from 'react-hot-toast'
import { getCampaignLogs, retryCampaignFailed } from '../../api/client'

function parseSenderBadge(message) {
  if (!message) return null
  const lower = message.toLowerCase()
  if (lower.includes('hostinger')) {
    return { label: 'Hostinger SMTP', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30' }
  }
  if (lower.includes('gmail')) {
    return { label: 'Google Workspace', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30' }
  }
  return null
}

function parseErrReason(message) {
  if (!message) return ''
  const m = message
  if (m.includes('Daily sending limit')) return 'Daily SMTP sending limit reached'
  if (m.includes('Server busy')) return 'Server busy or rate limited (temporary)'
  if (m.includes('Authentication')) return 'SMTP authentication failure'
  if (m.includes('timeout') || m.includes('Timeout')) return 'Connection timed out'
  if (m.includes('Sender address rejected')) return 'Sender address rejected by upstream provider'
  if (m.includes('Template rendering failed')) return 'Template syntax or placeholder resolution error'
  if (m.includes('quarantined')) return 'Quarantined lead excluded by pre-send gate'
  if (m.includes('cooldown')) return '7-day recipient cooldown active'
  const parts = m.split('—')
  return parts.length > 1 ? parts.slice(1).join('—').trim() : m
}

export default function CampaignLogsViewer({ campaignId, onRetryDone }) {
  const [logs, setLogs] = useState(null)
  const [loading, setLoading] = useState(true)
  const [retrying, setRetrying] = useState(false)
  const [statusFilter, setStatusFilter] = useState('all') // 'all' | 'sent' | 'failed' | 'skipped'
  const [searchQuery, setSearchQuery] = useState('')

  async function loadLogs() {
    setLoading(true)
    try {
      const res = await getCampaignLogs(campaignId, 300)
      setLogs(res.data || [])
    } catch {
      toast.error('Could not load email execution logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLogs()
  }, [campaignId])

  async function handleRetry() {
    if (retrying) return
    setRetrying(true)
    try {
      const res = await retryCampaignFailed(campaignId)
      toast.success(`Queued ${res.data.retrying_count} failed emails for retry`)
      setTimeout(() => {
        loadLogs()
        if (onRetryDone) onRetryDone()
      }, 1200)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Retry failed')
    } finally {
      setRetrying(false)
    }
  }

  // Deduplicate newest log per recipient email
  const { uniqueLogs, counts } = useMemo(() => {
    if (!logs) return { uniqueLogs: [], counts: { total: 0, sent: 0, failed: 0, skipped: 0 } }
    const sortedDesc = [...logs].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    const map = new Map()
    sortedDesc.forEach(l => {
      const key = (l.email || '').toLowerCase().trim()
      if (key && !map.has(key)) map.set(key, l)
    })
    const list = Array.from(map.values())
    const c = {
      total: list.length,
      sent: list.filter(l => l.status === 'sent').length,
      failed: list.filter(l => l.status === 'failed').length,
      skipped: list.filter(l => l.status === 'skipped').length,
    }
    return { uniqueLogs: list, counts: c }
  }, [logs])

  const filteredLogs = useMemo(() => {
    return uniqueLogs.filter(log => {
      if (statusFilter !== 'all' && log.status !== statusFilter) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim()
        const matchEmail = (log.email || '').toLowerCase().includes(q)
        const matchName = (log.business_name || '').toLowerCase().includes(q)
        const matchMsg = (log.message || '').toLowerCase().includes(q)
        if (!matchEmail && !matchName && !matchMsg) return false
      }
      return true
    })
  }, [uniqueLogs, statusFilter, searchQuery])

  if (loading && !logs) {
    return (
      <div className="p-8 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
        <span className="spinner w-3.5 h-3.5 border-blue-400 border-t-transparent" />
        Loading delivery logs…
      </div>
    )
  }

  if (!logs || logs.length === 0) {
    return (
      <div className="p-8 text-center text-slate-400 text-xs">
        <Mail size={24} className="mx-auto text-slate-600 mb-2 opacity-50" />
        No emails have been processed for this campaign yet.
      </div>
    )
  }

  return (
    <div className="bg-slate-950/70 border-t border-slate-800/80 rounded-b-xl overflow-hidden">
      {/* Control Toolbar */}
      <div className="p-3 bg-slate-900/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        {/* Filters */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {[
            { id: 'all', label: `All (${counts.total})` },
            { id: 'sent', label: `Sent (${counts.sent})`, color: 'text-emerald-400' },
            { id: 'failed', label: `Failed (${counts.failed})`, color: 'text-rose-400' },
            { id: 'skipped', label: `Skipped (${counts.skipped})`, color: 'text-amber-400' },
          ].map(f => (
            <button
              key={f.id}
              type="button"
              onClick={() => setStatusFilter(f.id)}
              className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                statusFilter === f.id
                  ? 'bg-blue-600/20 text-blue-300 border border-blue-500/40'
                  : 'text-slate-400 hover:text-slate-200 border border-transparent'
              } ${f.color || ''}`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Search & Actions */}
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
            <input
              type="text"
              placeholder="Search recipient / err…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="text-xs bg-slate-900 border border-slate-700/80 rounded-md pl-7 pr-3 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-44"
            />
          </div>

          {counts.failed > 0 && (
            <button
              type="button"
              onClick={handleRetry}
              disabled={retrying}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold bg-rose-500/15 border border-rose-500/40 text-rose-300 hover:bg-rose-500/25 transition-colors disabled:opacity-50"
              title="Retry delivery for currently failed recipients"
            >
              <RotateCcw size={12} className={retrying ? 'animate-spin' : ''} />
              {retrying ? 'Retrying…' : `Retry ${counts.failed} Failed`}
            </button>
          )}
        </div>
      </div>

      {/* Logs Table */}
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="bg-slate-900/40 border-b border-slate-800 text-[10px] text-slate-400 uppercase tracking-wider font-semibold sticky top-0 backdrop-blur-sm">
              <th className="py-2 px-3 w-8">Status</th>
              <th className="py-2 px-3">Recipient &amp; Business</th>
              <th className="py-2 px-3">Delivery Timestamp</th>
              <th className="py-2 px-3">Sender Route</th>
              <th className="py-2 px-3">Outcome Notes / Skip Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900/80">
            {filteredLogs.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-6 text-center text-slate-500 text-xs">
                  No execution logs match filter '{statusFilter}'
                </td>
              </tr>
            ) : (
              filteredLogs.map(log => {
                const isSent = log.status === 'sent'
                const isFailed = log.status === 'failed'
                const isSkipped = log.status === 'skipped'
                const senderBadge = parseSenderBadge(log.message)
                const errReason = isFailed ? parseErrReason(log.message) : (isSkipped ? parseErrReason(log.message) : '')

                return (
                  <tr
                    key={log.id}
                    className={`hover:bg-slate-900/50 transition-colors ${
                      isFailed ? 'bg-rose-950/10' : isSkipped ? 'bg-amber-950/5' : ''
                    }`}
                  >
                    <td className="py-2.5 px-3">
                      {isSent && <CheckCircle2 size={14} className="text-emerald-400" />}
                      {isFailed && <AlertCircle size={14} className="text-rose-400" />}
                      {isSkipped && <SkipForward size={14} className="text-amber-400" />}
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="font-medium text-slate-200 truncate max-w-xs">
                        {log.business_name || 'Prospect'}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate max-w-xs">
                        {log.email}
                      </div>
                    </td>
                    <td className="py-2.5 px-3 text-slate-400 whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString('en-IN', {
                        day: 'numeric',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      {senderBadge ? (
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border ${senderBadge.bg} ${senderBadge.color}`}>
                          <Server size={10} />
                          {senderBadge.label}
                        </span>
                      ) : (
                        <span className="text-slate-500 text-[11px]">—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-slate-300">
                      {isSent ? (
                        <span className="text-[11px] text-emerald-400/90 font-medium">
                          Delivered via verified SMTP route
                        </span>
                      ) : isFailed ? (
                        <span className="text-[11px] text-rose-300 font-medium flex items-center gap-1">
                          <AlertTriangle size={11} className="text-rose-400 shrink-0" />
                          {errReason || log.message || 'SMTP delivery rejected'}
                        </span>
                      ) : (
                        <span className="text-[11px] text-amber-300/90 flex items-center gap-1">
                          <SkipForward size={11} className="text-amber-400 shrink-0" />
                          {errReason || log.message || 'Skipped by safety check'}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
