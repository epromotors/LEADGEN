import React, { useState, useEffect, useCallback } from 'react'
import {
  Inbox, RefreshCw, TrendingUp, Mail, AlertTriangle,
  Server, ShieldCheck, CheckCircle2, XCircle
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getConvertedLeads,
  getAllReplies,
  getReplyStats,
  checkRepliesNow,
  reclassifyReply,
  deleteLead,
} from '../api/client'
import InboxKpiCards from '../components/inbox/InboxKpiCards'
import ConvertedLeadsTable from '../components/inbox/ConvertedLeadsTable'
import AllRepliesTable from '../components/inbox/AllRepliesTable'
import InboxSyncPanel from '../components/inbox/InboxSyncPanel'
import ReplyDetailModal from '../components/inbox/ReplyDetailModal'
import Email2ComposeModal from '../components/inbox/Email2ComposeModal'
import InboxSkeleton from '../components/inbox/InboxSkeleton'

export default function InboxPage() {
  const [activeTab, setActiveTab] = useState('converted') // 'converted' | 'all_replies' | 'sync'
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  // Converted leads state
  const [convertedLeads, setConvertedLeads] = useState([])
  const [convertedTotal, setConvertedTotal] = useState(0)
  const [convertedPage, setConvertedPage] = useState(1)

  // All replies state
  const [allReplies, setAllReplies] = useState([])
  const [allRepliesTotal, setAllRepliesTotal] = useState(0)

  // Stats & sync state
  const [stats, setStats] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [lastSynced, setLastSynced] = useState(null)
  const [syncResult, setSyncResult] = useState(null)

  // Modals state
  const [previewLead, setPreviewLead] = useState(null)
  const [reclassifying, setReclassifying] = useState(false)
  const [composeLead, setComposeLead] = useState(null)

  // Load stats
  const fetchStats = useCallback(async () => {
    try {
      const res = await getReplyStats()
      setStats(res.data)
    } catch {
      // quiet
    }
  }, [])

  // Load converted leads
  const fetchConverted = useCallback(async (isSilent = false) => {
    if (!isSilent) setLoading(true)
    setError('')
    try {
      const res = await getConvertedLeads({ page: convertedPage, page_size: 25 })
      setConvertedLeads(res.data?.items || [])
      setConvertedTotal(res.data?.total || 0)
    } catch (err) {
      setError('Failed to load converted leads.')
    } finally {
      if (!isSilent) setLoading(false)
    }
  }, [convertedPage])

  // Load all replies
  const fetchAllReplies = useCallback(async (isSilent = false) => {
    if (!isSilent) setLoading(true)
    setError('')
    try {
      const res = await getAllReplies({ page: 1, page_size: 200 })
      setAllReplies(res.data?.items || [])
      setAllRepliesTotal(res.data?.total || 0)
    } catch (err) {
      setError('Failed to load replies inbox.')
    } finally {
      if (!isSilent) setLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  useEffect(() => {
    if (activeTab === 'converted') {
      fetchConverted()
    } else if (activeTab === 'all_replies') {
      fetchAllReplies()
    }
  }, [activeTab, fetchConverted, fetchAllReplies])

  // Sync inbox trigger
  const handleSync = async () => {
    setSyncing(true)
    setSyncResult(null)
    setError('')
    try {
      const res = await checkRepliesNow()
      setSyncResult(res.data)
      setLastSynced(new Date())
      toast.success('IMAP inbox synchronization finished')
      await fetchStats()
      if (activeTab === 'converted') await fetchConverted(true)
      if (activeTab === 'all_replies') await fetchAllReplies(true)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Sync failed. Verify Hostinger IMAP credentials.'
      setError(msg)
      toast.error(msg)
    } finally {
      setSyncing(false)
    }
  }

  // Delete lead
  const handleDelete = async (leadId, name) => {
    if (!confirm(`Delete "${name}" permanently? This cannot be undone.`)) return
    try {
      await deleteLead(leadId)
      toast.success(`Lead "${name}" deleted`)
      setConvertedLeads(prev => prev.filter(l => l.id !== leadId))
      setAllReplies(prev => prev.filter(l => l.id !== leadId))
      setConvertedTotal(prev => Math.max(0, prev - 1))
      fetchStats()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to delete lead')
    }
  }

  // Reclassify reply (move from Converted to Other)
  const handleReclassify = async (lead) => {
    setReclassifying(true)
    try {
      await reclassifyReply(lead.id)
      toast.success(`Reclassified ${lead.business_name} as 'Other'`)
      setConvertedLeads(prev => prev.filter(l => l.id !== lead.id))
      setConvertedTotal(prev => Math.max(0, prev - 1))
      setPreviewLead(null)
      fetchStats()
      if (activeTab === 'all_replies') fetchAllReplies(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to reclassify lead')
    } finally {
      setReclassifying(false)
    }
  }

  const tabs = [
    {
      id: 'converted',
      label: 'Converted Leads',
      icon: TrendingUp,
      count: stats?.converted,
      countColor: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
    },
    {
      id: 'all_replies',
      label: 'All Ingested Replies',
      icon: Mail,
      count: allRepliesTotal || null,
      countColor: 'bg-blue-500/20 text-blue-300 border border-blue-500/30',
    },
    {
      id: 'sync',
      label: 'Mailbox Sync & Rules',
      icon: Server,
      count: null,
    },
  ]

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-slate-100 tracking-tight">
              Reply Inbox &amp; Converted Leads
            </h1>
            {stats?.converted > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                <CheckCircle2 size={12} />
                {stats.converted} Converted
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Automated IMAP reply ingestion, sentiment classification, hot lead conversion, and CAN-SPAM suppression.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="btn-primary text-xs py-2 px-4 flex items-center gap-2 font-bold shadow-md shadow-blue-500/20 disabled:opacity-50"
          >
            <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
            <span>{syncing ? 'Syncing Mailbox…' : 'Sync Inbox Now'}</span>
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-3.5 bg-rose-950/20 border border-rose-800/40 rounded-xl text-rose-300 text-xs flex items-center gap-2">
          <XCircle size={15} className="text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Top KPI Cards */}
      <InboxKpiCards
        stats={stats}
        lastSynced={lastSynced}
        onSyncNow={handleSync}
        syncing={syncing}
      />

      {/* Tab Navigation */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
        {tabs.map(tab => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`tab-pill ${isActive ? 'tab-pill-active' : ''}`}
            >
              <Icon size={14} />
              <span>{tab.label}</span>
              {tab.count != null && (
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${tab.countColor || 'bg-slate-800 text-slate-300'}`}>
                  {tab.count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Main Tab View */}
      {loading && activeTab !== 'sync' ? (
        <InboxSkeleton />
      ) : activeTab === 'converted' ? (
        <ConvertedLeadsTable
          leads={convertedLeads}
          total={convertedTotal}
          page={convertedPage}
          setPage={setConvertedPage}
          onPreview={setPreviewLead}
          onCompose={setComposeLead}
          onReclassify={handleReclassify}
          onDelete={handleDelete}
          loading={loading}
        />
      ) : activeTab === 'all_replies' ? (
        <AllRepliesTable
          replies={allReplies}
          total={allRepliesTotal}
          onPreview={setPreviewLead}
          onCompose={setComposeLead}
          onReclassify={handleReclassify}
          onDelete={handleDelete}
          loading={loading}
        />
      ) : (
        <InboxSyncPanel
          onSync={handleSync}
          syncing={syncing}
          lastSynced={lastSynced}
          syncResult={syncResult}
        />
      )}

      {/* Reply Snippet Detail Modal */}
      {previewLead && (
        <ReplyDetailModal
          lead={previewLead}
          onClose={() => setPreviewLead(null)}
          onReclassify={handleReclassify}
          reclassifying={reclassifying}
        />
      )}

      {/* Email 2 Follow-Up Compose Modal */}
      {composeLead && (
        <Email2ComposeModal
          lead={composeLead}
          onClose={() => setComposeLead(null)}
          onSent={() => {
            fetchStats()
            if (activeTab === 'converted') fetchConverted(true)
          }}
        />
      )}
    </div>
  )
}
