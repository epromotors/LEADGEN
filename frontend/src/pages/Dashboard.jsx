import { useEffect, useState } from 'react'
import { Users, CheckCircle, Mail, Zap, TrendingUp, Clock, Activity } from 'lucide-react'
import { getMetrics, getActivity } from '../api/client'
import { formatDistanceToNow } from 'date-fns'

function StatCard({ icon: Icon, label, value, color, sub }) {
  return (
    <div className="card relative overflow-hidden group hover:border-brand-600/50 transition-all duration-300">
      <div className={`absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 ${color} opacity-5`} />
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">{label}</p>
          <p className="text-3xl font-bold text-white mt-1">{value ?? '—'}</p>
          {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
        </div>
        <div className={`p-3 rounded-xl ${color}`}>
          <Icon size={20} className="text-white" />
        </div>
      </div>
    </div>
  )
}

const EVENT_ICONS = {
  leads_imported: { icon: Users,       color: 'text-blue-400' },
  audit_triggered:{ icon: Zap,         color: 'text-yellow-400' },
  audit_done:     { icon: CheckCircle, color: 'text-green-400' },
  email_sent:     { icon: Mail,        color: 'text-purple-400' },
  email_failed:   { icon: Mail,        color: 'text-red-400' },
  campaign_created:{ icon: Activity,   color: 'text-cyan-400' },
  campaign_started:{ icon: TrendingUp, color: 'text-orange-400' },
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null)
  const [activity, setActivity] = useState([])

  useEffect(() => {
    getMetrics().then(r => setMetrics(r.data))
    getActivity(20).then(r => setActivity(r.data))
  }, [])

  return (
    <div className="p-8 page-enter">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-slate-500 text-sm mt-1">Welcome back — here's your system overview.</p>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={Users}        label="Total Leads"       value={metrics?.total_leads}      color="bg-brand-600"      sub="in database" />
        <StatCard icon={CheckCircle}  label="Audits Complete"   value={metrics?.audits_complete}  color="bg-green-600"      sub="SEO scans done" />
        <StatCard icon={Mail}         label="Emails Sent"       value={metrics?.emails_sent}      color="bg-purple-600"     sub="all time" />
        <StatCard icon={Activity}     label="Active Campaigns"  value={metrics?.campaigns_active} color="bg-orange-600"     sub="currently running" />
      </div>

      {/* Activity Feed */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <Clock size={16} className="text-brand-400" /> Live Activity Feed
          </h2>
          <span className="badge badge-blue">{activity.length} events</span>
        </div>

        <div className="space-y-1">
          {activity.length === 0 && (
            <p className="text-sm text-slate-500 py-8 text-center">No activity yet. Upload leads to get started.</p>
          )}
          {activity.map((evt) => {
            const meta = EVENT_ICONS[evt.event_type] || { icon: Activity, color: 'text-slate-400' }
            const Icon = meta.icon
            return (
              <div key={evt.id} className="flex items-start gap-3 py-2.5 border-b border-surface-border last:border-0">
                <div className={`mt-0.5 flex-shrink-0 ${meta.color}`}>
                  <Icon size={15} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-300 truncate">{evt.message}</p>
                  <p className="text-xs text-slate-600 mt-0.5">
                    {formatDistanceToNow(new Date(evt.created_at), { addSuffix: true })}
                  </p>
                </div>
                <span className="badge badge-grey flex-shrink-0">{evt.event_type.replace(/_/g, ' ')}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
