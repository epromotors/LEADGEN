import React, { useState, useMemo } from 'react'
import { PlayCircle, X, Sparkles, RefreshCw, AlertTriangle, Layers, Check, Hash } from 'lucide-react'

export default function AuditModeModal({ stats, onSelect, onClose }) {
  // These are audit-history counts from the API, not Lead.status counts.
  const neverAuditedCount = stats?.never_audited ?? 0
  const retryFailedCount = stats?.retryable_failed ?? 0
  const restartInterruptedCount = stats?.restart_interrupted ?? 0
  const notEmailedCount = stats?.not_emailed_eligible ?? 0
  const forceAllCount = stats?.force_all_eligible ?? 0
  const skippedCount = stats?.skipped ?? 0

  const modes = [
    {
      key: 'new_only',
      title: 'Never Audited',
      desc: 'Audit only leads with no audit record. Interrupted or failed audits are excluded.',
      count: neverAuditedCount,
      countLabel: 'never audited',
      badgeColor: 'bg-blue-500/10 text-blue-300 border-blue-500/30',
      icon: Sparkles,
      iconColor: 'text-blue-400',
      disabled: neverAuditedCount === 0,
    },
    {
      key: 'retry_failed',
      title: 'Retry Failed Audits',
      desc: restartInterruptedCount > 0
        ? `${restartInterruptedCount} audit(s) were interrupted by a server restart and can be retried.`
        : 'Retry audit records that previously failed; completed and active audits are excluded.',
      count: retryFailedCount,
      countLabel: 'retryable failures',
      badgeColor: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
      icon: RefreshCw,
      iconColor: 'text-violet-400',
      disabled: retryFailedCount === 0,
    },
    {
      key: 'not_emailed',
      title: 'All Not Emailed',
      desc: "Re-audit eligible leads that are new or audited and have not received outreach; active audits are excluded.",
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
      desc: 'Execute fresh 62-factor crawls across every non-active lead in the database.',
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

  // Default to first non-disabled mode
  const defaultMode = useMemo(() => {
    const found = modes.find(m => !m.disabled)
    return found ? found.key : 'new_only'
  }, [modes])

  const [selectedMode, setSelectedMode] = useState(defaultMode)
  const [limitType, setLimitType] = useState('all') // 'all' | '10' | '25' | '50' | '100' | 'custom'
  const [customCount, setCustomCount] = useState(10)

  const currentModeObj = modes.find(m => m.key === selectedMode) || modes[0]
  const availableCount = currentModeObj.count

  const effectiveLimit = useMemo(() => {
    if (limitType === 'all') return null
    if (limitType === 'custom') {
      const parsed = parseInt(customCount, 10)
      if (isNaN(parsed) || parsed < 1) return 1
      return Math.min(parsed, availableCount || 1)
    }
    const val = parseInt(limitType, 10)
    return Math.min(val, availableCount || val)
  }, [limitType, customCount, availableCount])

  const countToAudit = effectiveLimit !== null ? Math.min(effectiveLimit, availableCount) : availableCount

  function handleStart() {
    if (currentModeObj.disabled || countToAudit <= 0) return
    onSelect(selectedMode, effectiveLimit)
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-start justify-center p-4 pt-16 overflow-y-auto"
      onClick={e => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="card-elevated w-full max-w-xl p-0 overflow-hidden shadow-2xl border border-slate-700/80 animate-in fade-in zoom-in-95 duration-200 flex flex-col max-h-[calc(100vh-6rem)] mb-8">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <PlayCircle size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Configure Batch Audit Session
              </h3>
              <p className="text-[11px] text-slate-400">
                Select target scope, fixed lead limit, and concurrency controls
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

        {/* Scrollable Body */}
        <div className="p-6 space-y-5 overflow-y-auto">
          {/* 1. Mode options */}
          <div className="space-y-2">
            <label className="text-xs font-bold text-slate-300 uppercase tracking-wider">
              1. Select Target Scope
            </label>
            <div className="space-y-2.5">
              {modes.map(m => {
                const Icon = m.icon
                const isSelected = selectedMode === m.key
                return (
                  <button
                    key={m.key}
                    type="button"
                    disabled={m.disabled}
                    onClick={() => {
                      if (!m.disabled) setSelectedMode(m.key)
                    }}
                    className={`w-full text-left p-3.5 rounded-xl border transition-all duration-200 flex items-start gap-3.5 group relative ${
                      m.disabled
                        ? 'opacity-40 cursor-not-allowed bg-slate-900/20 border-slate-800/60'
                        : isSelected
                        ? 'bg-blue-950/30 border-blue-500/80 shadow-md shadow-blue-950/50 ring-1 ring-blue-500/50 cursor-pointer'
                        : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 hover:bg-slate-800/40 cursor-pointer'
                    }`}
                  >
                    <div
                      className={`p-2 rounded-lg border ${
                        isSelected
                          ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                          : `bg-slate-800 border-slate-700/60 ${m.iconColor}`
                      } shrink-0 mt-0.5`}
                    >
                      <Icon size={16} />
                    </div>
                    <div className="flex-1 min-w-0 pr-6">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span
                          className={`text-xs font-bold transition-colors ${
                            isSelected ? 'text-white' : 'text-slate-200 group-hover:text-blue-300'
                          }`}
                        >
                          {m.title}
                        </span>
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded border ${m.badgeColor} shrink-0`}
                        >
                          {m.count.toLocaleString()} {m.countLabel}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">{m.desc}</p>
                    </div>

                    {isSelected && (
                      <div className="absolute right-3.5 top-3.5 w-5 h-5 rounded-full bg-blue-500 text-white flex items-center justify-center shadow">
                        <Check size={12} strokeWidth={3} />
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* 2. Fixed Number of Leads (Batch Limit) */}
          <div className="space-y-2 pt-2 border-t border-slate-800/80">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                <Hash size={13} className="text-blue-400" />
                2. Number of Leads to Audit
              </label>
              <span className="text-[11px] text-slate-400 font-mono">
                {availableCount.toLocaleString()} available in selected scope
              </span>
            </div>

            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {[
                { id: 'all', label: 'All' },
                { id: '10', label: '10' },
                { id: '25', label: '25' },
                { id: '50', label: '50' },
                { id: '100', label: '100' },
                { id: 'custom', label: 'Custom' },
              ].map(opt => {
                const isSelected = limitType === opt.id
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setLimitType(opt.id)}
                    className={`py-2 px-3 rounded-lg text-xs font-semibold border transition-all text-center ${
                      isSelected
                        ? 'bg-blue-600 text-white border-blue-500 shadow-sm shadow-blue-900/50'
                        : 'bg-slate-900/80 text-slate-300 border-slate-800 hover:border-slate-700 hover:bg-slate-800'
                    }`}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>

            {limitType === 'custom' && (
              <div className="pt-2 flex items-center gap-2">
                <span className="text-xs text-slate-400">Audit exactly:</span>
                <input
                  type="number"
                  min="1"
                  max={availableCount > 0 ? availableCount : 1000}
                  value={customCount}
                  onChange={e => setCustomCount(e.target.value)}
                  className="input-field text-xs py-1.5 px-3 w-28 font-mono bg-slate-950 border-slate-700 text-white focus:border-blue-500"
                  placeholder="e.g. 15"
                />
                <span className="text-xs text-slate-400">leads</span>
              </div>
            )}

            {/* Scope calculation summary */}
            <div className="p-3 rounded-lg bg-slate-950/70 border border-slate-800/80 text-xs text-slate-300 flex items-center justify-between">
              <span className="text-slate-400">Will queue for background audit:</span>
              <span className="font-bold text-emerald-400 font-mono">
                {countToAudit.toLocaleString()} lead{countToAudit === 1 ? '' : 's'}
              </span>
            </div>
          </div>
        </div>

        {/* Footer info & CTA */}
        <div className="px-6 py-4 border-t border-slate-800/80 bg-slate-950/60 flex flex-col sm:flex-row items-center justify-between gap-3 shrink-0">
          <p className="text-[11px] text-slate-500 text-center sm:text-left">
            Pause, resume, and cancel available anytime during crawling.
          </p>
          <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary text-xs py-2 px-3.5 font-semibold"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleStart}
              disabled={currentModeObj.disabled || countToAudit <= 0}
              className="btn-primary text-xs py-2 px-4 font-bold flex items-center gap-1.5 shadow-lg shadow-blue-900/30 disabled:opacity-40"
            >
              <PlayCircle size={14} />
              <span>
                Start Batch Audit ({countToAudit.toLocaleString()})
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
