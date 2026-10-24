import React, { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  RefreshCw, Users, Search, Mail, AlertTriangle, ArrowRight,
  Sparkles, CheckCircle2, ShieldCheck, Activity
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getMetrics,
  getAuditStats,
  getEmailVerificationStats,
  getCampaigns,
  getActivity,
  getLeads,
} from '../api/client'
import DashboardSkeleton from '../components/dashboard/DashboardSkeleton'
import DashboardKpiCards from '../components/dashboard/DashboardKpiCards'
import LeadPipelineBreakdown from '../components/dashboard/LeadPipelineBreakdown'
import AuditHealthPanel from '../components/dashboard/AuditHealthPanel'
import RecentActivityFeed from '../components/dashboard/RecentActivityFeed'
import RecentLeadsTable from '../components/dashboard/RecentLeadsTable'

export default function Dashboard() {
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [partialError, setPartialError] = useState(null)

  const [metrics, setMetrics] = useState(null)
  const [auditStats, setAuditStats] = useState(null)
  const [emailStats, setEmailStats] = useState(null)
  const [campaigns, setCampaigns] = useState([])
  const [activity, setActivity] = useState([])
  const [recentLeads, setRecentLeads] = useState([])

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setPartialError(null)

    const results = await Promise.allSettled([
      getMetrics(),
      getAuditStats(),
      getEmailVerificationStats(),
      getCampaigns(),
      getActivity(15),
      getLeads({ page: 1, page_size: 6 }),
    ])

    const [
      metricsRes,
      auditStatsRes,
      emailStatsRes,
      campaignsRes,
      activityRes,
      leadsRes,
    ] = results

    const failedEndpoints = []

    if (metricsRes.status === 'fulfilled') {
      setMetrics(metricsRes.value.data)
    } else {
      failedEndpoints.push('Metrics')
    }

    if (auditStatsRes.status === 'fulfilled') {
      setAuditStats(auditStatsRes.value.data)
    } else {
      failedEndpoints.push('Audit Stats')
    }

    if (emailStatsRes.status === 'fulfilled') {
      setEmailStats(emailStatsRes.value.data)
    } else {
      failedEndpoints.push('Deliverability Stats')
    }

    if (campaignsRes.status === 'fulfilled') {
      setCampaigns(campaignsRes.value.data || [])
    } else {
      failedEndpoints.push('Campaigns')
    }

    if (activityRes.status === 'fulfilled') {
      setActivity(activityRes.value.data || [])
    } else {
      failedEndpoints.push('Activity')
    }

    if (leadsRes.status === 'fulfilled') {
      setRecentLeads(leadsRes.value.data.items || [])
    } else {
      failedEndpoints.push('Recent Leads')
    }

    if (failedEndpoints.length > 0) {
      setPartialError(
        `Unable to reach: ${failedEndpoints.join(', ')}. Remaining dashboard metrics loaded successfully.`
      )
    }

    setLoading(false)
    setRefreshing(false)
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const totalLeads = metrics?.total_leads ?? auditStats?.total ?? 0

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* ── Top Header & Actions ── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-slate-800/80 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Operational Dashboard
            </h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/40 text-emerald-400 border border-emerald-800/50">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Realtime OS
            </span>
          </div>
          <p className="text-slate-400 text-sm mt-1">
            System overview across lead intake, 62-factor crawler verification, and delivery.
          </p>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="btn-secondary text-xs py-2 px-3.5 font-semibold flex items-center justify-center gap-2 flex-1 sm:flex-none"
            title="Refresh dashboard data"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
          </button>

          <Link
            to="/leads"
            className="btn-primary text-xs py-2 px-3.5 font-bold flex items-center justify-center gap-1.5 flex-1 sm:flex-none shadow-lg shadow-blue-900/30"
          >
            <Users size={14} />
            <span>Leads Workspace</span>
          </Link>
        </div>
      </div>

      {/* ── Partial Error Warning Banner (if any endpoint fails) ── */}
      {partialError && (
        <div className="p-3.5 rounded-xl bg-amber-950/20 border border-amber-800/40 flex items-center justify-between gap-3 text-xs text-amber-300">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-amber-400 shrink-0" />
            <span>{partialError}</span>
          </div>
          <button
            onClick={() => loadData(true)}
            className="font-bold underline hover:text-amber-200 shrink-0"
          >
            Retry Failed
          </button>
        </div>
      )}

      {/* ── Content: Loading or Rendered ── */}
      {loading ? (
        <DashboardSkeleton />
      ) : (
        <>
          {/* Empty Database State Notice */}
          {totalLeads === 0 && (
            <div className="card-elevated p-8 text-center flex flex-col items-center justify-center">
              <div className="w-14 h-14 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4">
                <Sparkles size={28} />
              </div>
              <h3 className="text-lg font-bold text-slate-100 mb-1">
                No Leads in Database Yet
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto mb-5 leading-relaxed">
                Import leads using a CSV upload or launch an automated keyword &amp; location discovery session in the Leads Workspace.
              </p>
              <Link
                to="/leads"
                className="btn-primary text-xs py-2.5 px-5 font-bold flex items-center gap-2 shadow-lg shadow-blue-900/30"
              >
                <Users size={15} />
                Open Leads Workspace
              </Link>
            </div>
          )}

          {/* 1. Hero KPI Grid */}
          <DashboardKpiCards
            metrics={metrics}
            auditStats={auditStats}
            emailStats={emailStats}
            campaigns={campaigns}
          />

          {/* 2. Lead Pipeline Breakdown & Audit Engine State */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <LeadPipelineBreakdown
              auditStats={auditStats}
              emailStats={emailStats}
            />
            <AuditHealthPanel
              auditStats={auditStats}
              campaigns={campaigns}
            />
          </div>

          {/* 3. Recent Leads Intake & Live Activity Feed */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RecentLeadsTable leads={recentLeads} />
            <RecentActivityFeed activities={activity} />
          </div>
        </>
      )}
    </div>
  )
}
