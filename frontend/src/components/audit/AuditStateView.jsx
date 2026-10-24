import React from 'react'
import { AlertTriangle, Clock, RefreshCw, Search, XCircle, Play, Sparkles } from 'lucide-react'

export function AuditLoadingSkeleton() {
  return (
    <div className="card-elevated p-6 space-y-4 animate-pulse">
      <div className="h-6 bg-slate-800 rounded w-1/3 mb-4" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="h-20 bg-slate-900 rounded-lg" />
        <div className="h-20 bg-slate-900 rounded-lg" />
        <div className="h-20 bg-slate-900 rounded-lg" />
      </div>
      <div className="h-28 bg-slate-900 rounded-lg mt-4" />
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-16 bg-slate-900 rounded-lg" />
        ))}
      </div>
    </div>
  )
}

export function AuditRunningState({ lead, onCancel = null }) {
  return (
    <div className="card-elevated p-8 text-center flex flex-col items-center justify-center my-4">
      <div className="w-12 h-12 rounded-full bg-blue-900/40 border border-blue-500/40 flex items-center justify-center mb-4">
        <RefreshCw size={24} className="text-blue-400 animate-spin" />
      </div>
      <h3 className="text-base font-bold text-slate-100 mb-1">
        62-Factor SEO Audit in Progress
      </h3>
      <p className="text-xs text-slate-400 max-w-md leading-relaxed mb-4">
        Auditing {lead?.business_name || 'website'} across 11 canonical performance groups. Bounded crawlers are inspecting robots.txt, XML sitemaps, internal links, and rendering evidence.
      </p>
      <div className="flex items-center gap-2 text-[11px] text-blue-400 font-mono bg-blue-950/60 px-3 py-1 rounded-full border border-blue-800/60">
        <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
        Executing factor pipeline...
      </div>
    </div>
  )
}

export function AuditSkippedState({ audit }) {
  const reason = audit?.error_message || audit?.audit_summary || 'Target site did not respond as an active website.'

  return (
    <div className="p-5 bg-amber-950/30 border border-amber-800/60 rounded-xl my-4">
      <div className="flex items-start gap-3">
        <AlertTriangle size={22} className="text-amber-400 shrink-0 mt-0.5" />
        <div>
          <h4 className="text-sm font-bold text-amber-200 mb-1">
            Audit Skipped (Site Offline or Unreachable)
          </h4>
          <p className="text-xs text-slate-300 leading-relaxed mb-2 font-mono">
            {reason}
          </p>
          <p className="text-xs text-slate-400">
            The target domain could not be resolved or returned a persistent connection failure. No factor findings or scores were fabricated.
          </p>
        </div>
      </div>
    </div>
  )
}

export function EmptyFindingsState({ onResetFilters = () => {} }) {
  return (
    <div className="p-8 text-center bg-slate-950/50 border border-slate-800/80 rounded-xl my-4">
      <Search size={24} className="text-slate-500 mx-auto mb-2" />
      <h4 className="text-sm font-bold text-slate-200 mb-1">
        No Matching Findings
      </h4>
      <p className="text-xs text-slate-400 max-w-sm mx-auto mb-4">
        No audit checks matched your active filter criteria (status, priority, category, or search keywords).
      </p>
      <button
        onClick={onResetFilters}
        className="btn-secondary text-xs py-1.5 px-4 font-semibold inline-flex items-center gap-1.5"
      >
        Reset All Filters
      </button>
    </div>
  )
}

export function NotAuditedState({ lead, onTriggerAudit, triggering }) {
  return (
    <div className="card-elevated p-8 text-center flex flex-col items-center justify-center my-4">
      <Sparkles size={28} className="text-slate-500 mb-2" />
      <h3 className="text-base font-bold text-slate-100 mb-1">
        No Audit Recorded for {lead?.business_name}
      </h3>
      <p className="text-xs text-slate-400 max-w-md leading-relaxed mb-5">
        Run the comprehensive 62-factor audit to analyze technical SEO, on-page optimization, site architecture, and browser performance.
      </p>
      <button
        onClick={() => onTriggerAudit && onTriggerAudit(lead.id)}
        disabled={triggering}
        className="btn-primary text-xs py-2 px-5 font-bold shadow-lg shadow-blue-900/30 flex items-center gap-2"
      >
        <Play size={14} className={triggering ? 'animate-spin' : ''} />
        {triggering ? 'Initiating Audit...' : 'Run Comprehensive Audit'}
      </button>
    </div>
  )
}
