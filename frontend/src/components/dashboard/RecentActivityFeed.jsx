import React from 'react'
import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import {
  Users, Zap, CheckCircle, Mail, Activity, TrendingUp,
  Clock, ArrowRight, ShieldCheck, Trash2, Edit3
} from 'lucide-react'

const EVENT_METAS = {
  leads_imported: { icon: Users, color: 'text-blue-400', bg: 'bg-blue-500/10' },
  audit_triggered: { icon: Zap, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  audit_done: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  email_sent: { icon: Mail, color: 'text-purple-400', bg: 'bg-purple-500/10' },
  email_failed: { icon: Mail, color: 'text-rose-400', bg: 'bg-rose-500/10' },
  campaign_created: { icon: Activity, color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
  campaign_started: { icon: TrendingUp, color: 'text-orange-400', bg: 'bg-orange-500/10' },
  lead_updated: { icon: Edit3, color: 'text-sky-400', bg: 'bg-sky-500/10' },
  legacy_quarantine_reverification: { icon: ShieldCheck, color: 'text-teal-400', bg: 'bg-teal-500/10' },
  leads_deleted: { icon: Trash2, color: 'text-rose-400', bg: 'bg-rose-500/10' },
}

export default function RecentActivityFeed({ activities = [] }) {
  return (
    <div className="card-elevated p-6 flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
              <Clock size={16} />
            </div>
            <h3 className="text-base font-bold text-slate-100">
              Live Operations Feed
            </h3>
          </div>
          <Link
            to="/activity"
            className="text-xs font-semibold text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            All Logs <ArrowRight size={13} />
          </Link>
        </div>

        {activities.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">
            No system activity recorded yet. Ingest leads or run audits to view real-time events.
          </div>
        ) : (
          <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
            {activities.slice(0, 7).map(evt => {
              const meta = EVENT_METAS[evt.event_type] || {
                icon: Activity,
                color: 'text-slate-400',
                bg: 'bg-slate-800',
              }
              const Icon = meta.icon
              const timeAgo = evt.created_at
                ? formatDistanceToNow(new Date(evt.created_at), { addSuffix: true })
                : 'just now'

              return (
                <div
                  key={evt.id}
                  className="p-3 rounded-lg bg-slate-900/50 border border-slate-800/70 hover:border-slate-700/80 transition-colors flex items-start gap-3"
                >
                  <div className={`p-1.5 rounded-lg border border-white/5 ${meta.bg} ${meta.color} shrink-0 mt-0.5`}>
                    <Icon size={14} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-300 font-medium leading-relaxed truncate" title={evt.message}>
                      {evt.message}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-slate-500">
                        {timeAgo}
                      </span>
                      <span className="text-[9px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700 font-mono">
                        {evt.event_type.replace(/_/g, ' ')}
                      </span>
                    </div>
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
