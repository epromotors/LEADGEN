import React from 'react'
import { Link } from 'react-router-dom'
import { Search, AlertTriangle, Play, RefreshCw, Mail, CheckCircle2, PauseCircle, Clock, ArrowRight } from 'lucide-react'

export default function AuditHealthPanel({ auditStats, campaigns = [] }) {
  const isBatchRunning = auditStats?.batch_running ?? false
  const skippedCount = auditStats?.skipped ?? 0
  const auditingCount = auditStats?.auditing ?? 0
  const totalLeads = auditStats?.total ?? 0
  const auditedCount = auditStats?.audited ?? 0

  return (
    <div className="card-elevated p-6 flex flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <Search size={16} />
            </div>
            <h3 className="text-base font-bold text-slate-100">
              Audit Engine &amp; Campaigns
            </h3>
          </div>
          <Link
            to="/audits"
            className="text-xs font-semibold text-emerald-400 hover:text-emerald-300 flex items-center gap-1"
          >
            Open Audits <ArrowRight size={13} />
          </Link>
        </div>

        {/* Audit Crawler Operational Status Banner */}
        <div className={`p-4 rounded-xl border mb-4 flex items-start gap-3 ${
          isBatchRunning
            ? 'bg-amber-950/20 border-amber-800/40'
            : 'bg-slate-900/60 border-slate-800/80'
        }`}>
          {isBatchRunning ? (
            <RefreshCw size={18} className="text-amber-400 animate-spin shrink-0 mt-0.5" />
          ) : (
            <CheckCircle2 size={18} className="text-emerald-400 shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-slate-200">
                {isBatchRunning ? 'Batch Crawler Active' : 'Crawler Ready'}
              </span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                isBatchRunning
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                  : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
              }`}>
                {isBatchRunning ? `${auditingCount} In Queue` : 'Standby'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              {isBatchRunning
                ? 'Bounded concurrency crawler is evaluating robots.txt, XML sitemaps, on-page factors, and browser render evidence.'
                : `${auditedCount.toLocaleString()} of ${totalLeads.toLocaleString()} leads fully audited with confirmed factor defects.`}
            </p>
          </div>
        </div>

        {/* Skipped Sites Notice */}
        {skippedCount > 0 && (
          <div className="p-3.5 rounded-xl bg-orange-950/20 border border-orange-800/30 mb-5 flex items-start justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle size={16} className="text-orange-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-bold text-orange-200">
                  {skippedCount} Skipped / Unreachable Sites
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Websites timed out or were flagged with parked domain statuses. No artificial audits were fabricated.
                </p>
              </div>
            </div>
            <Link
              to="/leads?status=skipped"
              className="text-[11px] font-bold px-2.5 py-1 rounded bg-orange-500/20 text-orange-300 border border-orange-500/30 hover:bg-orange-500/30 shrink-0 whitespace-nowrap transition-colors"
            >
              Filter Skipped
            </Link>
          </div>
        )}

        {/* Active Campaigns List */}
        <div className="pt-2">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <Mail size={14} className="text-violet-400" /> Recent Campaign Operations
            </span>
            <Link
              to="/campaigns"
              className="text-[11px] font-medium text-slate-400 hover:text-slate-300"
            >
              All ({campaigns.length})
            </Link>
          </div>

          {campaigns.length === 0 ? (
            <div className="p-4 text-center rounded-lg bg-slate-900/40 border border-slate-800 text-xs text-slate-500">
              No campaigns created yet. Create a targeted campaign from the Campaigns tab.
            </div>
          ) : (
            <div className="space-y-2">
              {campaigns.slice(0, 3).map(cmp => {
                const isSending = cmp.status === 'sending'
                const isCompleted = cmp.status === 'completed' || cmp.status === 'sent'
                const isPaused = cmp.status === 'paused'

                return (
                  <div
                    key={cmp.id}
                    className="p-3 rounded-lg bg-slate-900/60 border border-slate-800/80 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-semibold text-slate-200 truncate">
                          {cmp.name}
                        </p>
                        <span className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${
                          isSending
                            ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                            : isCompleted
                            ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                            : isPaused
                            ? 'bg-slate-800 text-slate-400 border-slate-700'
                            : 'bg-blue-500/10 text-blue-300 border-blue-500/20'
                        }`}>
                          {cmp.status.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        {cmp.sent_count ?? 0} dispatched · {cmp.total_leads ?? 0} audience leads
                      </p>
                    </div>

                    <Link
                      to={`/campaigns`}
                      className="text-xs text-slate-400 hover:text-slate-200 p-1.5 rounded hover:bg-slate-800 transition-colors shrink-0"
                      title="Inspect campaign"
                    >
                      <ArrowRight size={14} />
                    </Link>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
