import { useEffect, useMemo, useState } from 'react'
import {
  AlertCircle, CheckCircle2, Filter, Mail, RefreshCw, Search,
  ShieldAlert, ShieldCheck, TrendingUp, Users, Zap, Activity as ActivityIcon,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { getActivity } from '../api/client'

const EVENT_META = {
  leads_imported: { icon: Users, color: 'text-blue-400', bg: 'bg-blue-500/10', category: 'Lead' },
  lead_created: { icon: Users, color: 'text-blue-400', bg: 'bg-blue-500/10', category: 'Lead' },
  audit_triggered: { icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-500/10', category: 'Audit' },
  audit_done: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', category: 'Audit' },
  audit_failed: { icon: AlertCircle, color: 'text-rose-400', bg: 'bg-rose-500/10', category: 'Audit' },
  email_sent: { icon: Mail, color: 'text-purple-400', bg: 'bg-purple-500/10', category: 'Campaign' },
  email_failed: { icon: AlertCircle, color: 'text-rose-400', bg: 'bg-rose-500/10', category: 'Campaign' },
  campaign_created: { icon: ActivityIcon, color: 'text-cyan-400', bg: 'bg-cyan-500/10', category: 'Campaign' },
  campaign_started: { icon: TrendingUp, color: 'text-orange-400', bg: 'bg-orange-500/10', category: 'Campaign' },
  email_verification: { icon: ShieldAlert, color: 'text-indigo-400', bg: 'bg-indigo-500/10', category: 'Verification' },
  legacy_quarantine_reverification: { icon: ShieldAlert, color: 'text-indigo-400', bg: 'bg-indigo-500/10', category: 'Verification' },
  email_scan_started: { icon: ShieldAlert, color: 'text-indigo-400', bg: 'bg-indigo-500/10', category: 'Verification' },
  email_accepted: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', category: 'Verification' },
  email_dismissed: { icon: ShieldAlert, color: 'text-amber-400', bg: 'bg-amber-500/10', category: 'Verification' },
  email_corrected: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', category: 'Verification' },
  association_approved: { icon: ShieldCheck, color: 'text-sky-400', bg: 'bg-sky-500/10', category: 'Verification' },
}

function parseUTC(value) {
  if (!value) return null
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`)
}

function eventMeta(eventType) {
  const known = EVENT_META[eventType]
  if (known) return known
  if (eventType?.includes('verification') || eventType?.includes('quarantine')) {
    return { icon: ShieldAlert, color: 'text-indigo-400', bg: 'bg-indigo-500/10', category: 'Verification' }
  }
  if (eventType?.includes('reply')) return { icon: Mail, color: 'text-sky-400', bg: 'bg-sky-500/10', category: 'Reply' }
  if (eventType?.includes('campaign') || eventType?.includes('email')) return { icon: Mail, color: 'text-purple-400', bg: 'bg-purple-500/10', category: 'Campaign' }
  if (eventType?.includes('audit')) return { icon: Zap, color: 'text-yellow-400', bg: 'bg-yellow-500/10', category: 'Audit' }
  if (eventType?.includes('lead')) return { icon: Users, color: 'text-blue-400', bg: 'bg-blue-500/10', category: 'Lead' }
  return { icon: ActivityIcon, color: 'text-slate-400', bg: 'bg-slate-500/10', category: 'System' }
}

function outcome(eventType) {
  if (/(failed|error|blocked|quarantined)/i.test(eventType || '')) return { label: 'Attention', tone: 'text-rose-300 bg-rose-950/50 border-rose-800/60' }
  if (/(done|sent|created|started|accepted|completed)/i.test(eventType || '')) return { label: 'Recorded', tone: 'text-emerald-300 bg-emerald-950/50 border-emerald-800/60' }
  return { label: 'Recorded', tone: 'text-slate-300 bg-slate-800/70 border-slate-700' }
}

export default function ActivityLog() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [category, setCategory] = useState('All')
  const [query, setQuery] = useState('')

  async function fetchEvents() {
    setLoading(true)
    setError('')
    try {
      const response = await getActivity(200)
      setEvents(Array.isArray(response.data) ? response.data : [])
    } catch (requestError) {
      setError(requestError.response?.data?.detail || 'Activity events could not be loaded. Refresh to try again.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchEvents() }, [])

  const categories = useMemo(() => ['All', ...new Set(events.map(event => eventMeta(event.event_type).category))], [events])
  const filteredEvents = useMemo(() => {
    const term = query.trim().toLowerCase()
    return events.filter((event) => {
      const meta = eventMeta(event.event_type)
      const categoryMatch = category === 'All' || meta.category === category
      const text = [event.event_type, event.message, event.lead_id].filter(Boolean).join(' ').toLowerCase()
      return categoryMatch && (!term || text.includes(term))
    })
  }, [events, category, query])

  return (
    <div className="p-5 sm:p-8 page-enter">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Activity Log</h1>
          <p className="mt-1 text-sm text-slate-500">Operational audit trail from the latest 200 recorded events.</p>
        </div>
        <button onClick={fetchEvents} disabled={loading} className="btn-secondary" aria-label="Refresh activity log">
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="card mb-4 flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
        <label className="flex flex-1 items-center gap-2 rounded-lg border border-surface-border bg-surface px-3 py-2 text-slate-400 focus-within:border-brand-500">
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} className="w-full bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-600" placeholder="Search event, message, or lead ID" />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <Filter size={15} />
          <span className="sr-only">Event category</span>
          <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-slate-200 outline-none">
            {categories.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-rose-800/70 bg-rose-950/40 p-4 text-sm text-rose-200">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <div><p>{error}</p><button onClick={fetchEvents} className="mt-2 text-xs font-semibold text-rose-100 underline">Retry</button></div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="hidden grid-cols-[minmax(170px,1.4fr)_130px_minmax(100px,.8fr)_110px] gap-4 border-b border-surface-border px-6 py-3 text-[11px] font-bold uppercase tracking-wider text-slate-500 md:grid">
          <span>Event</span><span>Category</span><span>Entity</span><span>Outcome</span>
        </div>
        {loading ? (
          <div className="py-16 text-center"><span className="spinner" /></div>
        ) : !error && filteredEvents.length === 0 ? (
          <div className="py-16 text-center text-slate-500"><ActivityIcon size={32} className="mx-auto mb-2 opacity-30" /><p className="text-sm">{events.length ? 'No events match the active filters.' : 'No activity recorded yet.'}</p></div>
        ) : (
          <div className="divide-y divide-surface-border">
            {filteredEvents.map((event) => {
              const meta = eventMeta(event.event_type)
              const Icon = meta.icon
              const result = outcome(event.event_type)
              const timestamp = parseUTC(event.created_at)
              return (
                <article key={event.id} className="grid gap-3 px-4 py-4 transition-colors hover:bg-surface-hover/30 sm:px-6 md:grid-cols-[minmax(170px,1.4fr)_130px_minmax(100px,.8fr)_110px] md:items-start md:gap-4">
                  <div className="flex min-w-0 gap-3">
                    <div className={`mt-0.5 shrink-0 rounded-lg p-2 ${meta.bg}`}><Icon size={15} className={meta.color} /></div>
                    <div className="min-w-0"><p className="text-sm leading-snug text-slate-200">{event.message || 'No event message recorded.'}</p><p className="mt-1 text-xs text-slate-500">{timestamp && !Number.isNaN(timestamp.getTime()) ? `${timestamp.toLocaleString()} · ${formatDistanceToNow(timestamp, { addSuffix: true })}` : 'Timestamp unavailable'}</p></div>
                  </div>
                  <span className={`badge h-fit w-fit ${meta.bg} ${meta.color}`}>{meta.category}</span>
                  <div className="text-xs text-slate-400"><span className="mr-1 text-slate-600 md:hidden">Entity:</span>{event.lead_id ? `Lead ${String(event.lead_id).slice(0, 8)}` : 'System event'}</div>
                  <span className={`h-fit w-fit rounded-full border px-2 py-1 text-[11px] font-semibold ${result.tone}`}>{result.label}</span>
                </article>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
