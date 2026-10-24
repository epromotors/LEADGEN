import React, { useState } from 'react'
import {
  Download, RefreshCw, Cpu, CheckCircle2, AlertTriangle, XCircle,
  Clock, Shield, ArrowUpRight, Calendar, Layers, Sparkles
} from 'lucide-react'

export default function AuditOverviewHeader({
  lead,
  audit,
  counts = {},
  criticalCount = 0,
  highCount = 0,
  score = 0,
  pdfUrl = null,
  onRetriggerWithKeywords = null,
  retriggering = false,
}) {
  const [showKwInput, setShowKwInput] = useState(false)
  const [kwText, setKwText] = useState('')

  const resolvedScore = score || audit?.score || audit?.seo_score || audit?.overall_score || audit?.total_score || 0

  const passCount = counts.PASS || 0
  const warnCount = counts.WARN || 0
  const failCount = counts.FAIL || 0
  const errorCount = counts.ERROR || 0
  const totalFactors = passCount + warnCount + failCount + errorCount || 62

  const passPct = Math.round((passCount / totalFactors) * 100)
  const warnPct = Math.round((warnCount / totalFactors) * 100)
  const failPct = Math.round((failCount / totalFactors) * 100)

  // Score band
  const getScoreBand = (s) => {
    if (s >= 85) return { color: '#22c55e', bg: 'rgba(34, 197, 94, 0.15)', border: '#16a34a', label: '🟢 Excellent', desc: 'Well-optimised' }
    if (s >= 65) return { color: '#facc15', bg: 'rgba(250, 204, 21, 0.15)', border: '#ca8a04', label: '🟡 Good — Needs Work', desc: 'Moderate issues' }
    if (s >= 40) return { color: '#fb923c', bg: 'rgba(251, 146, 60, 0.15)', border: '#ea580c', label: '🟠 Poor — Action Required', desc: 'Substantial defects' }
    return { color: '#f87171', bg: 'rgba(248, 113, 113, 0.15)', border: '#dc2626', label: '🔴 Critical', desc: 'Severe visibility risk' }
  }

  const band = getScoreBand(resolvedScore)
  const auditDate = audit?.created_at
    ? new Date(audit.created_at).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'Recently'

  const browserStatus = audit?.browser_status || 'DISABLED'
  const browserPages = audit?.browser_pages || []

  const handleRetrigger = (e) => {
    e.preventDefault()
    if (!kwText.trim()) return
    if (onRetriggerWithKeywords) {
      onRetriggerWithKeywords(kwText)
      setShowKwInput(false)
    }
  }

  return (
    <div className="card-elevated p-6 mb-6">
      {/* Top Header Row */}
      <div className="flex items-start justify-between flex-wrap gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <h2 className="text-2xl font-black text-slate-100 tracking-tight">
              {lead?.business_name || 'Website SEO Audit'}
            </h2>
            <span className="badge badge-blue font-semibold tracking-wide uppercase text-[10px]">
              62-Factor Verified Audit
            </span>
            {browserStatus === 'SUCCESS' && (
              <span className="badge badge-green font-semibold flex items-center gap-1.5 text-[10px]">
                <Cpu size={12} />
                Browser Rendered ({browserPages.length > 1 ? `${browserPages.length} pages` : 'Single page'})
              </span>
            )}
            {browserStatus === 'TIMEOUT' && (
              <span className="badge badge-yellow font-semibold text-[10px]">
                Browser Lab Timeout (HTTP Complete)
              </span>
            )}
          </div>

          <div className="flex items-center gap-4 text-xs text-slate-400 flex-wrap">
            <span className="flex items-center gap-1.5">
              <Calendar size={13} className="text-slate-500" />
              Audited on {auditDate}
            </span>
            <span className="text-slate-600">•</span>
            <span className="flex items-center gap-1.5">
              <Shield size={13} className="text-emerald-400" />
              Audit Status: <strong className="text-slate-200">{audit?.audit_lifecycle || 'COMPLETE'}</strong>
            </span>
            {lead?.website && (
              <>
                <span className="text-slate-600">•</span>
                <span className="font-mono text-slate-400">
                  {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                </span>
              </>
            )}
          </div>

          {audit?.audit_summary && (
            <p className="text-slate-300 text-xs md:text-sm mt-3 leading-relaxed max-w-3xl">
              {audit.audit_summary}
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3 flex-wrap">
          {pdfUrl && (
            <a
              href={pdfUrl}
              target="_blank"
              rel="noreferrer"
              className="btn-primary text-xs font-semibold py-2 px-3.5 shadow-md shadow-blue-900/30 flex items-center gap-2"
            >
              <Download size={14} /> Download Client PDF
            </a>
          )}
          {onRetriggerWithKeywords && (
            <button
              onClick={() => setShowKwInput(v => !v)}
              className="btn-secondary text-xs font-semibold py-2 px-3 flex items-center gap-1.5"
            >
              <RefreshCw size={13} className={retriggering ? 'animate-spin' : ''} />
              Re-run Audit
            </button>
          )}
        </div>
      </div>

      {/* Target Keywords Input Drawer (When requested) */}
      {showKwInput && (
        <form onSubmit={handleRetrigger} className="mb-6 p-4 bg-slate-900/90 border border-slate-700/80 rounded-lg">
          <p className="text-xs font-bold text-slate-200 mb-2">Re-audit Target Keywords (Comma-separated)</p>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="e.g. emergency plumber, leak detection, drain cleaning"
              value={kwText}
              onChange={e => setKwText(e.target.value)}
              className="input text-xs py-1.5"
              autoFocus
            />
            <button
              type="submit"
              disabled={retriggering || !kwText.trim()}
              className="btn-primary text-xs py-1.5 px-4 whitespace-nowrap"
            >
              {retriggering ? 'Auditing...' : 'Start Audit'}
            </button>
            <button
              type="button"
              onClick={() => setShowKwInput(false)}
              className="btn-secondary text-xs py-1.5 px-3"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Score & Health Distribution Section */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch pt-2 border-t border-slate-800/80">
        {/* Score Donut / Gauge Card */}
        <div className="lg:col-span-3 bg-slate-950/70 border border-slate-800 rounded-xl p-5 flex flex-col items-center justify-center text-center">
          <span className="text-[10px] font-black text-slate-400 tracking-wider uppercase mb-1">
            Overall SEO Score
          </span>
          <div className="flex items-baseline gap-1 my-1">
            <span
              className="text-5xl font-black tracking-tight"
              style={{ color: band.color }}
            >
              {resolvedScore}
            </span>
            <span className="text-xs text-slate-500 font-semibold">/100</span>
          </div>
          <span
            className="text-[11px] font-extrabold px-3 py-1 rounded-full mt-2 border"
            style={{ color: band.color, backgroundColor: band.bg, borderColor: band.border }}
          >
            {band.label}
          </span>
          <span className="text-[11px] text-slate-500 mt-1">
            {band.desc}
          </span>
        </div>

        {/* Health Distribution & Detailed Metric Cards */}
        <div className="lg:col-span-9 flex flex-col justify-between gap-4">
          {/* Segmented Distribution Bar */}
          <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
            <div className="flex items-center justify-between text-xs mb-2.5">
              <span className="font-bold text-slate-300 uppercase tracking-wider text-[11px]">
                Factor Health Distribution ({totalFactors} Total Checks)
              </span>
              <span className="text-slate-400 text-xs">
                {passPct}% Passing Ratio
              </span>
            </div>

            {/* Segmented Bar */}
            <div className="segmented-bar mb-3">
              <div style={{ width: `${passPct}%` }} className="segmented-bar-pass" title={`${passCount} Passing (${passPct}%)`} />
              <div style={{ width: `${warnPct}%` }} className="segmented-bar-warn" title={`${warnCount} Warnings (${warnPct}%)`} />
              <div style={{ width: `${failPct}%` }} className="segmented-bar-fail" title={`${failCount} Failures (${failPct}%)`} />
            </div>

            {/* Legend with exact numbers */}
            <div className="flex items-center justify-between text-xs flex-wrap gap-3">
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                <span className="text-slate-400">Passes:</span>
                <strong className="text-emerald-400 font-bold">{passCount}</strong>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                <span className="text-slate-400">Warnings:</span>
                <strong className="text-amber-400 font-bold">{warnCount}</strong>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
                <span className="text-slate-400">Confirmed Defects:</span>
                <strong className="text-red-400 font-bold">{failCount}</strong>
              </div>
              {errorCount > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-700" />
                  <span className="text-slate-400">Errors:</span>
                  <strong className="text-rose-400 font-bold">{errorCount}</strong>
                </div>
              )}
            </div>
          </div>

          {/* Quick Metrics Chips Row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-1">
                Verified Passes
              </span>
              <div className="flex items-baseline gap-1.5">
                <span className="text-xl font-black text-emerald-400">{passCount}</span>
                <span className="text-[11px] text-slate-500">factors</span>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-1">
                Warnings
              </span>
              <div className="flex items-baseline gap-1.5">
                <span className="text-xl font-black text-amber-400">{warnCount}</span>
                <span className="text-[11px] text-slate-500">items</span>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-1">
                Priority Actions
              </span>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="badge pri-critical text-[10px] font-bold">
                  {criticalCount} Critical
                </span>
                <span className="badge pri-high text-[10px] font-bold">
                  {highCount} High
                </span>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3">
              <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 block mb-1">
                Pages Crawled
              </span>
              <div className="flex items-baseline gap-1.5">
                <span className="text-xl font-black text-blue-300">
                  {audit?.site_summary?.total_pages || 1}
                </span>
                <span className="text-[11px] text-slate-500">documents</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
