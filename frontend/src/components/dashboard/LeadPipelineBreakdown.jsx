import React from 'react'
import { Link } from 'react-router-dom'
import { Users, ShieldAlert, CheckCircle, Clock, AlertTriangle, ArrowRight, ShieldCheck } from 'lucide-react'

export default function LeadPipelineBreakdown({ auditStats, emailStats }) {
  const total = auditStats?.total ?? 0
  const countNew = auditStats?.new ?? 0
  const countAuditing = auditStats?.auditing ?? 0
  const countAudited = auditStats?.audited ?? 0
  const countEmailed = auditStats?.emailed ?? 0
  const countReplied = auditStats?.replied ?? 0
  const countSkipped = auditStats?.skipped ?? 0

  // Calculate percentages for segmented bar
  const getPct = (val) => (total > 0 ? (val / total) * 100 : 0)

  const segments = [
    { label: 'New', count: countNew, pct: getPct(countNew), color: 'bg-slate-500', status: 'new' },
    { label: 'Auditing', count: countAuditing, pct: getPct(countAuditing), color: 'bg-amber-500', status: 'auditing' },
    { label: 'Audited', count: countAudited, pct: getPct(countAudited), color: 'bg-blue-500', status: 'audited' },
    { label: 'Emailed', count: countEmailed, pct: getPct(countEmailed), color: 'bg-emerald-500', status: 'emailed' },
    { label: 'Replied', count: countReplied, pct: getPct(countReplied), color: 'bg-teal-400', status: 'replied' },
    { label: 'Skipped', count: countSkipped, pct: getPct(countSkipped), color: 'bg-rose-500', status: 'skipped' },
  ]

  // Deliverability counts from emailStats
  const deliverable = emailStats?.deliverable ?? 0
  const pendingVerif = emailStats?.pending_verification ?? emailStats?.unverified ?? 0
  const quarantined = emailStats?.quarantined ?? 0
  const demoOnly = emailStats?.demo_only_eligible ?? 0

  return (
    <div className="card-elevated p-6 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
              <Users size={16} />
            </div>
            <h3 className="text-base font-bold text-slate-100">
              Lead Lifecycle Pipeline
            </h3>
          </div>
          <Link
            to="/leads"
            className="text-xs font-semibold text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            Manage Leads <ArrowRight size={13} />
          </Link>
        </div>

        <p className="text-xs text-slate-400 mb-4 leading-relaxed">
          Distribution of {total.toLocaleString()} ingested leads through intake, crawler verification, and outbound communication.
        </p>

        {/* Segmented bar */}
        <div className="w-full h-3 bg-slate-900 rounded-full overflow-hidden flex mb-4 border border-slate-800">
          {segments.map(seg => (
            seg.pct > 0 ? (
              <div
                key={seg.label}
                style={{ width: `${Math.max(1, seg.pct)}%` }}
                className={`${seg.color} transition-all duration-300`}
                title={`${seg.label}: ${seg.count.toLocaleString()} (${Math.round(seg.pct)}%)`}
              />
            ) : null
          ))}
          {total === 0 && <div className="w-full bg-slate-800" />}
        </div>

        {/* Status Breakdown Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mb-6">
          {segments.map(seg => (
            <Link
              key={seg.label}
              to={`/leads?status=${seg.status}`}
              className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 transition-colors flex flex-col justify-between"
            >
              <div className="flex items-center justify-between gap-1 mb-1">
                <span className="text-[11px] font-medium text-slate-400 flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${seg.color}`} />
                  {seg.label}
                </span>
                <span className="text-[10px] text-slate-500 font-mono">
                  {total > 0 ? `${Math.round(seg.pct)}%` : '0%'}
                </span>
              </div>
              <span className="text-base font-bold text-slate-200">
                {seg.count.toLocaleString()}
              </span>
            </Link>
          ))}
        </div>

        {/* Deliverability & Safety Gate Summary */}
        <div className="pt-4 border-t border-slate-800/80">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <ShieldCheck size={14} className="text-cyan-400" /> Deliverability &amp; Safety Gate
            </span>
            <span className="text-[11px] text-slate-400">
              Strict Policy
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-900/30">
              <span className="text-[10px] uppercase font-bold text-emerald-400 block mb-0.5">
                Sendable
              </span>
              <span className="text-lg font-extrabold text-emerald-200">
                {deliverable.toLocaleString()}
              </span>
              <span className="text-[10px] text-emerald-500/80 block mt-0.5">
                Verified &amp; Matched
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-sky-950/20 border border-sky-900/30">
              <span className="text-[10px] uppercase font-bold text-sky-400 block mb-0.5">
                Demo-Only
              </span>
              <span className="text-lg font-extrabold text-sky-200">
                {demoOnly.toLocaleString()}
              </span>
              <span className="text-[10px] text-sky-500/80 block mt-0.5">
                Public Provider
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-amber-950/20 border border-amber-900/30">
              <span className="text-[10px] uppercase font-bold text-amber-400 block mb-0.5">
                Pending
              </span>
              <span className="text-lg font-extrabold text-amber-200">
                {pendingVerif.toLocaleString()}
              </span>
              <span className="text-[10px] text-amber-500/80 block mt-0.5">
                Unverified MX
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-rose-950/20 border border-rose-900/30">
              <span className="text-[10px] uppercase font-bold text-rose-400 block mb-0.5">
                Quarantined
              </span>
              <span className="text-lg font-extrabold text-rose-200">
                {quarantined.toLocaleString()}
              </span>
              <span className="text-[10px] text-rose-500/80 block mt-0.5">
                Safety Hold
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
