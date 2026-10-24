import React from 'react'
import { Link } from 'react-router-dom'
import { Users, Globe, ArrowRight, ExternalLink, ShieldCheck, ShieldAlert } from 'lucide-react'

export default function RecentLeadsTable({ leads = [] }) {
  return (
    <div className="card-elevated p-6 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Users size={16} />
            </div>
            <h3 className="text-base font-bold text-slate-100">
              Recent Lead Intake
            </h3>
          </div>
          <Link
            to="/leads"
            className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
          >
            Explore Table <ArrowRight size={13} />
          </Link>
        </div>

        {leads.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">
            No leads ingested yet. Use CSV upload or Bulk Discovery to add target accounts.
          </div>
        ) : (
          <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
            {leads.slice(0, 6).map(lead => {
              const isQuarantined = lead.is_quarantined
              const verifStatus = lead.email_verification_status || 'unverified'
              const auditStatus = lead.status || 'new'

              return (
                <div
                  key={lead.id}
                  className="p-3 rounded-lg bg-slate-900/50 border border-slate-800/70 hover:border-slate-700/80 transition-colors flex items-center justify-between gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-bold text-slate-200 truncate" title={lead.business_name}>
                        {lead.business_name}
                      </p>
                      {isQuarantined && (
                        <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-rose-950/40 text-rose-300 border border-rose-800/40">
                          Quarantined
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400 flex-wrap">
                      <span className="truncate max-w-[140px] text-slate-300">
                        {lead.email}
                      </span>
                      {lead.website && (
                        <a
                          href={lead.website}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-400 hover:text-blue-300 flex items-center gap-1 truncate max-w-[120px]"
                        >
                          <Globe size={11} />
                          {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                        </a>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                      auditStatus === 'audited'
                        ? 'bg-blue-500/10 text-blue-300 border-blue-500/20'
                        : auditStatus === 'emailed'
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                        : auditStatus === 'auditing'
                        ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                        : 'bg-slate-800 text-slate-400 border-slate-700'
                    }`}>
                      {auditStatus.toUpperCase()}
                    </span>

                    <Link
                      to={`/audits`}
                      className="p-1.5 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors"
                      title="Inspect audit"
                    >
                      <ArrowRight size={14} />
                    </Link>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
