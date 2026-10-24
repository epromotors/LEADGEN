import React, { useState } from 'react'
import {
  AlertCircle, CheckCircle2, AlertTriangle, XCircle, ArrowRight,
  Info, HelpCircle, ChevronDown, ChevronUp, Link as LinkIcon, ShieldCheck
} from 'lucide-react'

const PRIORITY_BADGES = {
  CRITICAL: {
    bg: '#450a0a',
    color: '#f87171',
    border: '#991b1b',
    label: 'CRITICAL',
    desc: 'Severe ranking or trust blocker — fix immediately',
  },
  HIGH: {
    bg: '#431407',
    color: '#fb923c',
    border: '#9a3412',
    label: 'HIGH',
    desc: 'High impact on indexing or click-through rates',
  },
  MEDIUM: {
    bg: '#2a1f05',
    color: '#facc15',
    border: '#854d0e',
    label: 'MEDIUM',
    desc: 'Standard optimization opportunity',
  },
  LOW: {
    bg: '#082138',
    color: '#38bdf8',
    border: '#0369a1',
    label: 'LOW',
    desc: 'Minor refinement or cosmetic signal',
  },
}

const STATUS_CONFIG = {
  PASS: {
    label: 'PASS',
    bg: 'rgba(34, 197, 94, 0.12)',
    border: 'rgba(34, 197, 94, 0.35)',
    color: '#4ade80',
    indicator: '#22c55e',
    icon: CheckCircle2,
  },
  WARN: {
    label: 'WARN',
    bg: 'rgba(234, 179, 8, 0.12)',
    border: 'rgba(234, 179, 8, 0.35)',
    color: '#facc15',
    indicator: '#eab308',
    icon: AlertTriangle,
  },
  FAIL: {
    label: 'FAIL',
    bg: 'rgba(239, 68, 68, 0.12)',
    border: 'rgba(239, 68, 68, 0.35)',
    color: '#f87171',
    indicator: '#ef4444',
    icon: XCircle,
  },
  ERROR: {
    label: 'ERROR',
    bg: 'rgba(225, 29, 72, 0.15)',
    border: 'rgba(225, 29, 72, 0.4)',
    color: '#fda4af',
    indicator: '#e11d48',
    icon: AlertCircle,
  },
  'N/A': {
    label: 'N/A',
    bg: 'rgba(100, 116, 139, 0.1)',
    border: 'rgba(100, 116, 139, 0.25)',
    color: '#94a3b8',
    indicator: '#64748b',
    icon: Info,
  },
}

export default function PrioritizedFindingCard({
  check,
  audit,
  affectedUrl = null,
}) {
  const [expanded, setExpanded] = useState(false)

  const raw = check.result || {}
  const statusKey = (raw.status || check.status || 'WARN').toUpperCase()
  const statusCfg = STATUS_CONFIG[statusKey] || STATUS_CONFIG['N/A']
  const StatusIcon = statusCfg.icon

  const rawPriority = (raw.severity || check.priority || 'MEDIUM').toUpperCase()
  const priorityCfg = PRIORITY_BADGES[rawPriority] || PRIORITY_BADGES.MEDIUM

  const label = check.label || check.name || 'Audit Check'
  const message = raw.message || check.why || 'Observation recorded during audit.'
  const fix = raw.fix || check.fix
  const whyItMatters = check.why || raw.why || 'Search engines and visitors rely on this factor for indexing and trust.'

  // Evidence extraction
  const detectedValue = raw.value !== null && raw.value !== undefined ? raw.value : null
  const unit = raw.unit ? ` ${raw.unit}` : ''
  const detail = raw.detail
  const confidence = raw.confidence || (raw.value !== null ? 'High' : 'Standard')

  const targetUrl = affectedUrl || audit?.final_url || audit?.requested_url || null

  return (
    <div
      className="finding-card relative"
      style={{
        borderLeft: `4px solid ${statusCfg.indicator}`,
      }}
    >
      {/* Top Header: Check Label, Category, Priority Badge, Status Pill */}
      <div className="flex items-start justify-between gap-3 mb-2.5">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h4 className="text-sm font-bold text-slate-100 truncate" title={label}>
              {label}
            </h4>
            {check.groupLabel && (
              <span className="text-[10px] font-semibold text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded">
                {check.groupLabel}
              </span>
            )}
            <span
              className="text-[9px] font-black px-2 py-0.5 rounded tracking-wider border"
              style={{
                backgroundColor: priorityCfg.bg,
                color: priorityCfg.color,
                borderColor: priorityCfg.border,
              }}
              title={priorityCfg.desc}
            >
              {priorityCfg.label} PRIORITY
            </span>
          </div>

          {targetUrl && (
            <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mt-0.5">
              <LinkIcon size={11} className="text-slate-500 shrink-0" />
              <span className="text-slate-500 font-mono text-[10px] truncate max-w-sm" title={targetUrl}>
                {targetUrl}
              </span>
            </div>
          )}
        </div>

        {/* Status Pill */}
        <div
          className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-black tracking-wide border shrink-0"
          style={{
            backgroundColor: statusCfg.bg,
            borderColor: statusCfg.border,
            color: statusCfg.color,
          }}
        >
          <StatusIcon size={13} />
          <span>{statusCfg.label}</span>
        </div>
      </div>

      {/* Main Structured Observation Message */}
      <p className="text-slate-300 text-xs leading-relaxed mb-3">
        {message}
      </p>

      {/* Detected Evidence Block */}
      {detectedValue !== null && (
        <div className="evidence-block mb-3 flex items-start justify-between gap-2">
          <div>
            <span className="text-slate-400 font-bold block mb-0.5 text-[10px] uppercase tracking-wider">
              Detected Evidence
            </span>
            <span className="text-blue-300 font-mono font-medium">
              {Array.isArray(detectedValue) ? detectedValue.join(', ') : String(detectedValue)}
              {unit}
            </span>
          </div>
          <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800/80 px-2 py-0.5 rounded shrink-0">
            {confidence} Confidence
          </span>
        </div>
      )}

      {/* Recommended Corrective Action (Prominent for FAIL and WARN) */}
      {statusKey !== 'PASS' && fix && (
        <div className="p-3 bg-blue-950/30 border border-blue-800/40 rounded-lg mb-2 flex items-start gap-2.5">
          <ArrowRight size={14} className="text-blue-400 shrink-0 mt-0.5" />
          <div className="text-xs">
            <span className="font-bold text-blue-200 block mb-0.5">Recommended Corrective Action:</span>
            <span className="text-blue-300 leading-relaxed">{fix}</span>
          </div>
        </div>
      )}

      {/* Collapsible "Why It Matters" & Technical Inspection */}
      <div className="pt-2 border-t border-slate-800/70">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="text-[11px] text-slate-400 hover:text-slate-200 font-semibold flex items-center gap-1 transition"
        >
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          <span>{expanded ? 'Hide Technical Context' : 'Why This Matters & Technical Context'}</span>
        </button>

        {expanded && (
          <div className="mt-2.5 p-3 bg-slate-950/80 border border-slate-800/80 rounded-lg text-xs space-y-2">
            <div>
              <span className="font-bold text-slate-300 block mb-0.5 text-[11px]">Why it matters:</span>
              <p className="text-slate-400 text-[11px] leading-relaxed">{whyItMatters}</p>
            </div>
            {detail && (
              <div>
                <span className="font-bold text-slate-300 block mb-0.5 text-[11px]">Audit Inspector Detail:</span>
                <p className="text-slate-400 text-[11px] leading-relaxed font-mono bg-slate-900/80 p-2 rounded border border-slate-800">
                  {detail}
                </p>
              </div>
            )}
            {raw.id && (
              <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1">
                <span>Canonical ID: <code className="text-slate-400">{raw.id}</code></span>
                {raw.score !== undefined && (
                  <span>Score Impact: <strong className="text-slate-300">{raw.score} / {raw.max_score || 10}</strong></span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
