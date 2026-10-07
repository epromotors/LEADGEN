import { useEffect, useState } from 'react'
import { RefreshCw, Users, Search, Mail, Activity, Zap, TrendingUp, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { getActivity } from '../api/client'
import { formatDistanceToNow } from 'date-fns'

const EVENT_META = {
  leads_imported:   { icon: Users,        color: 'text-blue-400',   bg: 'bg-blue-500/10' },
  audit_triggered:  { icon: Zap,          color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  audit_done:       { icon: Search,       color: 'text-green-400',  bg: 'bg-green-500/10' },
  email_sent:       { icon: Mail,         color: 'text-purple-400', bg: 'bg-purple-500/10' },
  email_failed:     { icon: AlertCircle,  color: 'text-red-400',    bg: 'bg-red-500/10' },
  campaign_created: { icon: Activity,     color: 'text-cyan-400',   bg: 'bg-cyan-500/10' },
  campaign_started: { icon: TrendingUp,   color: 'text-orange-400', bg: 'bg-orange-500/10' },
}

// Backend stores datetimes in UTC but without a 'Z' suffix.
// Appending 'Z' tells JavaScript to treat the string as UTC, not local time.
function parseUTC(str) {
  if (!str) return new Date()
  // If already has timezone info (+XX or Z), parse as-is
  if (/[Z+]/.test(str.slice(-6))) return new Date(str)
  return new Date(str + 'Z')
}



export default function ActivityLog() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)

  async function fetchEvents() {
    setLoading(true)
    try {
      const res = await getActivity(100)
      setEvents(res.data)
    } catch {
      toast.error('Failed to load activity')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchEvents() }, [])

  return (
    <div className="p-8 page-enter">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Activity Log</h1>
          <p className="text-slate-500 text-sm mt-1">Full chronological event stream — last 100 events.</p>
        </div>
        <button onClick={fetchEvents} className="btn-secondary">
          <RefreshCw size={16} />
        </button>
      </div>

      <div className="card p-0 divide-y divide-surface-border">
        {loading ? (
          <div className="py-16 text-center"><span className="spinner" /></div>
        ) : events.length === 0 ? (
          <div className="py-16 text-center text-slate-500">
            <Activity size={32} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">No activity recorded yet.</p>
          </div>
        ) : events.map(evt => {
          const meta = EVENT_META[evt.event_type] || { icon: Activity, color: 'text-slate-400', bg: 'bg-slate-500/10' }
          const Icon = meta.icon
          return (
            <div key={evt.id} className="flex items-start gap-4 px-6 py-4 hover:bg-surface-hover/30 transition-colors">
              <div className={`p-2 rounded-lg ${meta.bg} flex-shrink-0 mt-0.5`}>
                <Icon size={15} className={meta.color} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-200 leading-snug">{evt.message}</p>
                <p className="text-xs text-slate-600 mt-0.5">
                  {parseUTC(evt.created_at).toLocaleString()} &middot;&nbsp;
                  {formatDistanceToNow(parseUTC(evt.created_at), { addSuffix: true })}
                </p>
              </div>
              <span className={`badge flex-shrink-0 ${meta.bg} ${meta.color}`}>
                {evt.event_type.replace(/_/g, ' ')}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
