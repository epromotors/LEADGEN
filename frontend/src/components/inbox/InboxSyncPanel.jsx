import React, { useState, useEffect } from 'react'
import {
  RefreshCw, CheckCircle2, XCircle, AlertTriangle, Mail,
  Clock, ShieldCheck, Server, AlertOctagon, HelpCircle,
  Cpu, Zap, WifiOff, Eye, AlertCircle
} from 'lucide-react'
import { getAiStatus } from '../../api/client'

// ── AI Status Panel ──────────────────────────────────────────────────────────
function AiStatusPanel() {
  const [status, setStatus]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    let cancelled = false
    async function fetch() {
      try {
        const res = await getAiStatus()
        if (!cancelled) { setStatus(res.data); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail ?? 'Could not load AI status')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetch()
    // refresh every 30 s
    const id = setInterval(fetch, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const modeBadge = {
    off:    { label: 'OFF',    cls: 'bg-slate-700 text-slate-300'   },
    shadow: { label: 'SHADOW', cls: 'bg-amber-500/20 text-amber-300 border border-amber-500/40' },
    on:     { label: 'LIVE',   cls: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' },
  }

  const badge = status ? (modeBadge[status.mode] ?? modeBadge.off) : modeBadge.off

  const layers = status ? [
    { name: 'Structural DSN',  ready: true,                               desc: 'Bounce / auto-reply headers',  always: true },
    { name: 'Strict Rules',    ready: true,                               desc: 'Keyword + regex heuristics',   always: true },
    { name: 'LLM Fast Model',  ready: status.fast_model_ready,            desc: status.fast_model ?? 'none',    always: false },
    { name: 'Keyword Fallback',ready: true,                               desc: 'Always-on safety net',         always: true },
  ] : []

  if (loading) return (
    <div className="card-elevated p-4 border border-slate-800 flex items-center gap-2 text-xs text-slate-400">
      <RefreshCw size={14} className="animate-spin text-slate-500" />
      Loading AI classifier status…
    </div>
  )

  if (error) return (
    <div className="card-elevated p-4 border border-rose-800/40 bg-rose-950/10 text-xs text-rose-400 flex items-center gap-2">
      <AlertCircle size={14} /> {error}
    </div>
  )

  return (
    <div className="card-elevated border border-slate-700/60 bg-slate-900/40">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Cpu size={16} className="text-violet-400" />
          <span className="text-sm font-bold text-slate-200">AI Reply Classifier</span>
          <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${badge.cls}`}>
            {badge.label}
          </span>
        </div>

        {/* Ollama pill */}
        {status.ollama_reachable ? (
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400 bg-emerald-900/20 border border-emerald-700/40 px-2.5 py-1 rounded-full">
            <CheckCircle2 size={12} /> Ollama Connected
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-rose-400 bg-rose-900/20 border border-rose-700/40 px-2.5 py-1 rounded-full">
            <WifiOff size={12} /> Ollama Unreachable
          </span>
        )}
      </div>

      {/* Body */}
      <div className="p-4 space-y-4">

        {/* Ollama error message */}
        {status.ollama_error && (
          <div className="text-[11px] text-amber-400 bg-amber-950/20 border border-amber-700/30 rounded px-3 py-2 flex items-start gap-2">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>Ollama: {status.ollama_error} — classifier running in <strong>keyword-fallback mode</strong>.</span>
          </div>
        )}

        {/* Install Ollama callout */}
        {!status.ollama_reachable && (
          <div className="text-[11px] bg-slate-800/60 border border-slate-700 rounded px-3 py-2 space-y-1">
            <p className="font-semibold text-slate-300">Enable LLM classification:</p>
            <p className="text-slate-400">
              Install Ollama and run <code className="text-violet-300 bg-slate-900 px-1 rounded">ollama pull qwen2.5:3b</code>.{' '}
              <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="text-blue-400 underline">Download Ollama →</a>
            </p>
          </div>
        )}

        {/* 4-Layer pipeline */}
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-semibold">Classification Pipeline</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {layers.map((layer, i) => (
              <div key={layer.name} className="flex items-center gap-2 text-xs bg-slate-900/60 rounded px-3 py-2 border border-slate-800">
                <span className="text-slate-500 font-mono text-[10px] w-4">{i + 1}</span>
                {layer.ready
                  ? <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />
                  : <AlertTriangle size={13} className="text-amber-400 shrink-0" />
                }
                <div className="min-w-0">
                  <div className="font-semibold text-slate-200 truncate">{layer.name}</div>
                  <div className="text-[10px] text-slate-500 truncate" title={layer.desc}>{layer.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Needs Review badge */}
        {status.needs_review_count > 0 && (
          <div className="flex items-center gap-2 text-xs text-orange-300 bg-orange-950/20 border border-orange-700/30 rounded px-3 py-2">
            <Eye size={13} />
            <span>
              <strong>{status.needs_review_count}</strong> email{status.needs_review_count !== 1 ? 's' : ''} awaiting operator review — check the <strong>Needs Review</strong> tab.
            </span>
          </div>
        )}

        {/* Model info */}
        {status.fast_model && (
          <p className="text-[10px] text-slate-500">
            LLM: <code className="text-violet-300">{status.fast_model}</code>
            {status.fast_model_ready
              ? <span className="text-emerald-400 ml-1">✓ ready</span>
              : <span className="text-amber-400 ml-1">✗ not loaded</span>
            }
            {status.models_available?.length > 0 &&
              <span className="ml-2 text-slate-600">({status.models_available.join(', ')} available)</span>
            }
          </p>
        )}
      </div>
    </div>
  )
}

// ── Main sync panel ───────────────────────────────────────────────────────────
export default function InboxSyncPanel({ onSync, syncing, lastSynced, syncResult }) {
  return (
    <div className="space-y-6">
      {/* AI Classifier Status Panel */}
      <AiStatusPanel />

      {/* Sync Trigger Card */}
      <div className="card-elevated p-6 border border-slate-800 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Server size={18} className="text-blue-400" />
            Hostinger IMAP Inbox Synchronization
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Connects to <code className="text-blue-300 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">imap.hostinger.com:993</code> (SSL) and scans <strong className="text-slate-200">INBOX + Spam</strong> folders for unread replies.
          </p>
          {lastSynced && (
            <p className="text-[11px] text-slate-500 mt-2 flex items-center gap-1.5 font-mono">
              <Clock size={11} className="text-slate-400" />
              Last synchronization executed at: {lastSynced.toLocaleString('en-IN')}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onSync}
          disabled={syncing}
          className="btn-primary text-xs py-2.5 px-5 font-bold flex items-center gap-2 shadow-lg shadow-blue-500/20 disabled:opacity-50"
        >
          <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
          {syncing ? 'Scanning Mailbox\u2026' : 'Sync Inbox Now'}
        </button>
      </div>

      {/* Sync Result Summary Cards */}
      {syncResult && (
        <div className="card-elevated p-5 border border-emerald-500/30 bg-emerald-950/10">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={16} className="text-emerald-400" />
            <h3 className="text-sm font-bold text-emerald-300">
              Synchronization Complete
            </h3>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            {[
              {
                label: 'Emails Fetched',
                value: syncResult.fetched ?? 0,
                color: 'text-blue-400',
                desc: 'Unseen messages downloaded',
              },
              {
                label: 'Newly Converted',
                value: syncResult.positive ?? 0,
                color: 'text-emerald-400',
                desc: 'Positive replies matched to leads',
              },
              {
                label: 'Suppressed / Purged',
                value: syncResult.deleted ?? 0,
                color: 'text-rose-400',
                desc: 'STOP or bounce leads removed',
              },
              {
                label: 'Soft Bounces (OOO)',
                value: syncResult.soft_bounce ?? 0,
                color: 'text-amber-400',
                desc: 'Temporary absence flagged',
              },
              {
                label: 'Other / No Match',
                value: syncResult.other ?? 0,
                color: 'text-slate-400',
                desc: 'Unmatched or generic notes',
              },
              {
                label: 'Sync Errors',
                value: syncResult.errors ?? 0,
                color: syncResult.errors > 0 ? 'text-rose-400' : 'text-slate-500',
                desc: 'IMAP parsing failures',
              },
              {
                label: 'AI Classified',
                value: syncResult.ai_classified ?? 0,
                color: 'text-violet-400',
                desc: 'Emails processed by AI classifier',
              },
              {
                label: 'Needs Review',
                value: syncResult.ai_review ?? 0,
                color: syncResult.ai_review > 0 ? 'text-orange-400' : 'text-slate-500',
                desc: 'Low-confidence — await operator',
              },
            ].map(item => (
              <div
                key={item.label}
                className="p-3 bg-slate-900/80 rounded-lg border border-slate-800"
              >
                <div className={`text-xl font-extrabold ${item.color}`}>
                  {item.value}
                </div>
                <div className="text-[11px] font-semibold text-slate-300 mt-0.5">
                  {item.label}
                </div>
                <div className="text-[10px] text-slate-500 mt-1 truncate" title={item.desc}>
                  {item.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Compliance & Policy Explanation */}
      <div className="card-elevated p-6 border border-slate-800 space-y-4">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <ShieldCheck size={16} className="text-emerald-400" />
          Automated Reply Classification &amp; Suppression Pipeline
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs text-slate-400">
          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-emerald-400">
              <CheckCircle2 size={14} />
              <span>Positive Replies (YES / Interested / Blueprint)</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Promoted immediately to <strong className="text-white">Converted</strong> status. Saved with reply body snippet and timestamp for operator review and proposal generation.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-rose-400">
              <XCircle size={14} />
              <span>STOP / Unsubscribe Signals</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Enforces CAN-SPAM and outreach compliance. The lead and associated audits are <strong className="text-white">permanently deleted</strong> to guarantee suppression from future campaigns.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-rose-400">
              <AlertOctagon size={14} />
              <span>Hard Bounces (550 / Invalid Recipient)</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Recipient mailbox does not exist. Lead is <strong className="text-white">permanently purged</strong> to protect sender reputation and prevent repeated bounce penalties.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-amber-400">
              <AlertTriangle size={14} />
              <span>Soft Bounces / Out of Office</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Flagged with <code className="text-amber-300">reply_type=soft_bounce</code>. The lead is <strong className="text-white">retained in the database</strong> because the address is valid.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
