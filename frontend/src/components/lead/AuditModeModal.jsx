import React from 'react'
import { PlayCircle, X, Sparkles, RefreshCw, AlertTriangle, Layers } from 'lucide-react'

export default function AuditModeModal({ stats, onSelect, onClose }) {
  const notAuditedCount = stats?.new ?? 0
  const notEmailedCount = (stats?.new ?? 0) + (stats?.audited ?? 0)
  const forceAllCount = stats?.total ?? 0
  const skippedCount = stats?.skipped ?? 0

  const modes = [
    {
      key: 'new_only',
      title: 'New Sites Only',
      desc: 'Audit leads that have never been crawled yet.',
      count: notAuditedCount,
      countLabel: 'unaudited leads',
      badgeColor: 'bg-blue-500/10 text-blue-300 border-blue-500/30',
      icon: Sparkles,
      iconColor: 'text-blue-400',
      disabled: notAuditedCount === 0,
    },
    {
      key: 'not_emailed',
      title: 'All Not Emailed',
      desc: "Re-audit leads that are new or audited but haven't received an outreach email.",
      count: notEmailedCount,
      countLabel: 'candidate leads',
      badgeColor: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
      icon: Layers,
      iconColor: 'text-amber-400',
      disabled: notEmailedCount === 0,
    },
    {
      key: 'force_all',
      title: 'Re-audit Everything',
      desc: 'Execute fresh 62-factor crawls across every lead in the database.',
      count: forceAllCount,
      countLabel: 'total leads',
      badgeColor: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
      icon: RefreshCw,
      iconColor: 'text-rose-400',
      disabled: forceAllCount === 0,
    },
    {
      key: 'skipped',
      title: 'Re-audit Skipped Sites',
      desc: 'Fresh audit retry for leads that timed out or were marked unreachable.',
      count: skippedCount,
      countLabel: 'skipped sites',
      badgeColor: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
      icon: AlertTriangle,
      iconColor: 'text-orange-400',
      disabled: skippedCount === 0,
    },
  ]

  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="card-elevated w-full max-w-lg p-0 overflow-hidden shadow-2xl border border-slate-700/80 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <PlayCircle size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Configure Batch Audit Session
              </h3>
              <p className="text-[11px] text-slate-400">
                Select target scope for background crawling queue
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Mode options */}
        <div className="p-6 space-y-3">
          {modes.map(m => {
            const Icon = m.icon
            return (
              <button
                key={m.key}
                type="button"
                disabled={m.disabled}
                onClick={() => onSelect(m.key)}
                className={`w-full text-left p-4 rounded-xl border transition-all duration-200 flex items-start gap-3.5 group ${
                  m.disabled
                    ? 'opacity-40 cursor-not-allowed bg-slate-900/20 border-slate-800'
                    : 'bg-slate-900/60 border-slate-800 hover:border-slate-600 hover:bg-slate-800/50 cursor-pointer'
                }`}
              >
                <div className={`p-2 rounded-lg bg-slate-800 border border-slate-700/60 ${m.iconColor} shrink-0 mt-0.5`}>
                  <Icon size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-bold text-slate-200 group-hover:text-blue-300 transition-colors">
                      {m.title}
                    </span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${m.badgeColor} shrink-0`}>
                      {m.count.toLocaleString()} {m.countLabel}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    {m.desc}
                  </p>
                </div>
              </button>
            )
          })}
        </div>

        {/* Footer info */}
        <div className="px-6 py-3 border-t border-slate-800/80 bg-slate-950/40 text-center">
          <p className="text-[11px] text-slate-500">
            Crawls execute asynchronously with bounded concurrency. You can continue using the workspace.
          </p>
        </div>
      </div>
    </div>
  )
}
