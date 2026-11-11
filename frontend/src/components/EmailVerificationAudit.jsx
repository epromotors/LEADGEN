import { useEffect, useState } from 'react'
import {
  Mail, ShieldCheck, ShieldAlert, CheckCircle2, XCircle, AlertTriangle,
  RefreshCw, Search, X, Check, ArrowRight, Eye, Shield, HelpCircle,
  Clock, Play, Ban, AlertCircle, Sparkles, Filter, Globe, Trash2, ArrowUpCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getEmailVerificationStats,
  getEmailVerificationLeads,
  verifyLeadEmail,
  reverifyLead,
  verifySingleEmail,
  bulkVerifyEmails,
  getEmailVerificationProgress,
  cancelEmailVerificationJob,
  approveLeadAssociation,
  bulkApproveDomainMatches,
  bulkReverifyLeads,
  promoteLeadToSendable,
  deleteLeadFromDB,
  bulkPromoteLeads,
  bulkDeleteLeadsFromDB,
} from '../api/client'

const STATUS_CONFIG = {
  valid: { label: 'Routeable (Syntax & MX) — Mailbox Unconfirmed', bg: 'bg-emerald-950/60', text: 'text-emerald-400', border: 'border-emerald-700/50', icon: CheckCircle2 },
  invalid: { label: 'Invalid', bg: 'bg-rose-950/60', text: 'text-rose-400', border: 'border-rose-700/50', icon: XCircle },
  disposable: { label: 'Disposable', bg: 'bg-amber-950/60', text: 'text-amber-400', border: 'border-amber-700/50', icon: AlertTriangle },
  catch_all: { label: 'Catch-All', bg: 'bg-purple-950/60', text: 'text-purple-400', border: 'border-purple-700/50', icon: HelpCircle },
  risky: { label: 'Risky / Typo', bg: 'bg-orange-950/60', text: 'text-orange-400', border: 'border-orange-700/50', icon: AlertCircle },
  not_found: { label: 'Not Found', bg: 'bg-red-950/60', text: 'text-red-400', border: 'border-red-700/50', icon: XCircle },
  timeout: { label: 'Timeout', bg: 'bg-slate-900/80', text: 'text-slate-400', border: 'border-slate-700/50', icon: Clock },
  error: { label: 'DNS Error', bg: 'bg-slate-900/80', text: 'text-slate-400', border: 'border-slate-700/50', icon: AlertTriangle },
  unverified: { label: 'Unverified', bg: 'bg-slate-800/60', text: 'text-slate-400', border: 'border-slate-700/40', icon: HelpCircle },
}

const ASSOCIATION_CONFIG = {
  matched: { label: 'Business matched', tone: 'text-emerald-400 border-emerald-700/50 bg-emerald-950/50' },
  approved: { label: 'Manually approved', tone: 'text-sky-400 border-sky-700/50 bg-sky-950/50' },
  mismatched_source: { label: 'Source mismatch', tone: 'text-rose-400 border-rose-700/50 bg-rose-950/50' },
  invalid_format: { label: 'Invalid association', tone: 'text-rose-400 border-rose-700/50 bg-rose-950/50' },
  external_domain_review: { label: 'External domain review', tone: 'text-amber-400 border-amber-700/50 bg-amber-950/50' },
  pending_review: { label: 'Pending association review', tone: 'text-amber-400 border-amber-700/50 bg-amber-950/50' },
  unverified_association: { label: 'Association unconfirmed', tone: 'text-slate-300 border-slate-700 bg-slate-800/60' },
  unverified: { label: 'Association unconfirmed', tone: 'text-slate-300 border-slate-700 bg-slate-800/60' },
}

function AssociationBadge({ status }) {
  const config = ASSOCIATION_CONFIG[status] || ASSOCIATION_CONFIG.unverified
  return <span className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-semibold ${config.tone}`}>{config.label}</span>
}

export default function EmailVerificationAudit() {
  const [activeView, setActiveView] = useState('active') // 'active' | 'quarantined'
  const [statusFilter, setStatusFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 50

  const [stats, setStats] = useState(null)
  const [leads, setLeads] = useState([])
  const [totalLeads, setTotalLeads] = useState(0)
  const [loading, setLoading] = useState(false)
  const [verifyingId, setVerifyingId] = useState(null)

  // Single ad-hoc test state
  const [testEmailInput, setTestEmailInput] = useState('')
  const [testTesting, setTestTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // Detailed Modal state
  const [selectedLead, setSelectedLead] = useState(null)

  // Operator approval modal state
  const [approvingLead, setApprovingLead] = useState(null)
  const [approvalReason, setApprovalReason] = useState('')
  const [submittingApproval, setSubmittingApproval] = useState(false)
  const [bulkApproving, setBulkApproving] = useState(false)

  // Bulk progress
  const [bulkProgress, setBulkProgress] = useState(null)
  const [bulkStarting, setBulkStarting] = useState(false)

  // Fetch deliverability stats
  async function loadStats() {
    try {
      const res = await getEmailVerificationStats()
      setStats(res.data)
    } catch {
      // silent fallback
    }
  }

  // Fetch leads
  async function loadLeads() {
    setLoading(true)
    try {
      const res = await getEmailVerificationLeads({
        view: activeView,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        search: searchQuery.trim() || undefined,
        page,
        page_size: pageSize,
      })
      setLeads(res.data.items || [])
      setTotalLeads(res.data.total || 0)
    } catch {
      toast.error('Failed to load email verification leads')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
    getEmailVerificationProgress()
      .then((res) => setBulkProgress(res.data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    setPage(1)
  }, [activeView, statusFilter, searchQuery])

  useEffect(() => {
    loadLeads()
  }, [activeView, statusFilter, searchQuery, page])

  // Poll bulk progress reactively whenever a job is running
  useEffect(() => {
    if (!bulkProgress?.is_running) return

    const interval = setInterval(async () => {
      try {
        const res = await getEmailVerificationProgress()
        const data = res.data
        setBulkProgress(data)
        if (!data?.is_running) {
          loadStats()
          loadLeads()
          if (data?.processed > 0) {
            toast.success(
              `Bulk verification finished: ${data.processed} leads processed (${data.valid} deliverable, ${data.invalid} invalid, ${data.quarantined} quarantined)`
            )
          }
        }
      } catch {
        // ignore
      }
    }, 1500)

    return () => clearInterval(interval)
  }, [bulkProgress?.is_running])

  // Verify / Re-verify single lead against official website and DNS/MX
  async function handleVerifyLead(leadId, isReverify = false) {
    setVerifyingId(leadId)
    try {
      const apiFn = isReverify ? reverifyLead : verifyLeadEmail
      const res = await apiFn(leadId)
      const data = res.data
      
      if (isReverify && data.outcome_status) {
        if (data.outcome_status === 'corrected') {
          toast.success(`Corrected email: ${data.old_email} → ${data.new_email} (${data.verification_status || 'valid'})`, { duration: 6000 })
        } else if (data.outcome_status === 'revalidated') {
          toast.success(`Revalidated & retained ${data.new_email || data.old_email}`, { duration: 5000 })
        } else if (data.outcome_status === 'manual_review') {
          toast(`Placed in manual review: external domain email detected`, { icon: '⚠️', duration: 5000 })
        } else if (data.outcome_status === 'no_email_found') {
          toast.error(`Excluded from active outreach: no company email found on official website`, { duration: 5000 })
        } else if (data.outcome_status === 'scrape_inconclusive') {
          toast(`Website scrape inconclusive; retained for retry without deletion`, { icon: 'ℹ️', duration: 5000 })
        } else {
          toast.success(data.is_quarantined ? 'Re-verify complete: Lead Quarantined' : 'Re-verify complete: Lead Deliverable')
        }
      } else {
        toast.success(data.is_quarantined ? 'Verification complete: Lead Quarantined' : 'Verification complete: Lead Deliverable')
      }

      loadStats()
      loadLeads()
      if (selectedLead && selectedLead.id === leadId) {
        setSelectedLead({
          ...selectedLead,
          email: data.new_email || selectedLead.email,
          verification_status: data.verification?.status || data.verification_status,
          deliverability_score: data.verification?.score ?? selectedLead.deliverability_score,
          is_sendable: data.is_sendable,
          is_quarantined: data.is_quarantined,
          quarantine_reason: data.quarantine_reason,
          details: data.verification || selectedLead.details,
          email_source_url: data.evidence_url || selectedLead.email_source_url,
        })
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to verify lead')
    } finally {
      setVerifyingId(null)
    }
  }

  // Run ad-hoc single test
  async function handleAdHocTest(e) {
    e?.preventDefault()
    if (!testEmailInput.trim()) return
    setTestTesting(true)
    setTestResult(null)
    try {
      const res = await verifySingleEmail({ email: testEmailInput.trim() })
      setTestResult(res.data)
      toast.success('Test complete')
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Verification error')
    } finally {
      setTestTesting(false)
    }
  }

  // Trigger bulk verify
  async function handleStartBulk() {
    setBulkStarting(true)
    try {
      const res = await bulkVerifyEmails({ unverified_only: true, limit: 500 })
      toast.success(res.data.message || 'Bulk verification started')
      loadStats()
      // Fetch immediate progress so bulkProgress.is_running triggers reactive polling
      const prog = await getEmailVerificationProgress()
      setBulkProgress(prog.data)
      if (!prog.data?.is_running) {
        loadStats()
        loadLeads()
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not start bulk verification')
    } finally {
      setBulkStarting(false)
    }
  }

  // Cancel bulk verify
  async function handleCancelBulk() {
    try {
      await cancelEmailVerificationJob()
      toast.success('Cancellation requested')
      const prog = await getEmailVerificationProgress()
      setBulkProgress(prog.data)
      loadStats()
      loadLeads()
    } catch {
      toast.error('Failed to cancel job')
    }
  }

  // Operator approval handler
  async function handleApproveAssociation() {
    if (!approvingLead || approvalReason.trim().length < 5) {
      toast.error('Justification reason must be at least 5 characters.')
      return
    }
    setSubmittingApproval(true)
    try {
      await approveLeadAssociation(approvingLead.id, {
        reason: approvalReason.trim(),
        policy_reference: 'manual_corporate_domain_review',
      })
      toast.success(`Association approved for ${approvingLead.business_name || approvingLead.email}`)
      setApprovingLead(null)
      setApprovalReason('')
      if (selectedLead && selectedLead.id === approvingLead.id) {
        setSelectedLead(null)
      }
      loadStats()
      loadLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to approve association')
    } finally {
      setSubmittingApproval(false)
    }
  }

  const eligibleDomainMatchLeads = activeView === 'corporate_review'
    ? leads.filter((lead) => (
      lead.verification_status === 'valid'
      && !lead.is_quarantined
      && lead.email_domain_match === true
      && lead.website_association_status === 'verified_primary'
      && ['unverified_association', 'external_domain_review', 'pending_review', 'unverified'].includes(lead.association_status)
      && lead.email_source_url
      && lead.email_source_type
    ))
    : []

  async function handleBulkApproveDomainMatches() {
    const eligibleCount = eligibleDomainMatchLeads.length
    if (!eligibleCount || bulkApproving) return
    const confirmed = window.confirm(
      `Approve ${eligibleCount} visible lead(s) with valid email verification, a verified primary website, matching corporate email domain, and recorded source evidence? Quarantined, inferred, free-email, and unmatched leads will stay in their current review segments.`
    )
    if (!confirmed) return

    setBulkApproving(true)
    try {
      const response = await bulkApproveDomainMatches({ lead_ids: eligibleDomainMatchLeads.map((lead) => lead.id) })
      const { approved_count = 0, skipped = [] } = response.data
      toast.success(`Approved ${approved_count} domain-matched lead(s); ${skipped.length} stayed in review.`)
      await Promise.all([loadStats(), loadLeads()])
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk domain approval failed')
    } finally {
      setBulkApproving(false)
    }
  }

  // ── Bulk Re-verify & Cleanup Modal State & Handlers ──────────────────
  const [showBulkReverifyModal, setShowBulkReverifyModal] = useState(false)
  const [bulkReverifyFilterMismatched, setBulkReverifyFilterMismatched] = useState(true)
  const [bulkReverifyFilterUnverified, setBulkReverifyFilterUnverified] = useState(false)
  const [bulkReverifyLimit, setBulkReverifyLimit] = useState(50)
  const [bulkReverifyLoading, setBulkReverifyLoading] = useState(false)
  const [bulkReverifyReport, setBulkReverifyReport] = useState(null)

  // ── Promote-to-Sendable & Delete state ────────────────────────────────────
  const [promotingId, setPromotingId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [confirmDeleteLead, setConfirmDeleteLead] = useState(null)

  // ── Row selection & bulk actions state ───────────────────────────────────
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkActionRunning, setBulkActionRunning] = useState(false)

  // Clear selection when tab or data changes
  useEffect(() => { setSelectedIds(new Set()) }, [activeView, page, searchQuery, statusFilter])

  const allPageIds = leads.map((l) => l.id)
  const allSelected = allPageIds.length > 0 && allPageIds.every((id) => selectedIds.has(id))
  const someSelected = selectedIds.size > 0

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(allPageIds))
    }
  }
  function toggleSelectOne(id) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleBulkVerifySelected() {
    if (!selectedIds.size || bulkActionRunning) return
    const ids = [...selectedIds]
    const isReverify = activeView === 'quarantined'
    if (!window.confirm(`${isReverify ? 'Re-verify' : 'Verify'} ${ids.length} selected lead(s)?`)) return
    setBulkActionRunning(true)
    let ok = 0, fail = 0
    for (const id of ids) {
      try {
        const apiFn = isReverify ? reverifyLead : verifyLeadEmail
        await apiFn(id)
        ok++
      } catch { fail++ }
    }
    toast.success(`Verification done: ${ok} processed${fail ? `, ${fail} failed` : ''}.`)
    setSelectedIds(new Set())
    loadStats(); loadLeads()
    setBulkActionRunning(false)
  }

  async function handleBulkPromoteSelected() {
    if (!selectedIds.size || bulkActionRunning) return
    const ids = [...selectedIds]
    if (!window.confirm(`Verify & promote ${ids.length} selected lead(s) to Active Sendable?`)) return
    setBulkActionRunning(true)
    try {
      const res = await bulkPromoteLeads({
        lead_ids: ids,
        reason: 'Bulk operator promotion from Email Verification Hub',
      })
      const { promoted_count = 0, failed_count = 0 } = res.data
      toast.success(
        `Promote complete: ${promoted_count} lead(s) moved to Active Sendable${failed_count ? `, ${failed_count} failed verification` : ''}.`,
        { duration: 6000 }
      )
      setSelectedIds(new Set())
      await Promise.all([loadStats(), loadLeads()])
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk promotion failed')
    } finally {
      setBulkActionRunning(false)
    }
  }

  async function handleBulkDeleteSelected() {
    if (!selectedIds.size || bulkActionRunning) return
    const ids = [...selectedIds]
    if (!window.confirm(`⚠️ Permanently delete ${ids.length} selected lead(s) from the database? This cannot be undone.`)) return
    setBulkActionRunning(true)
    try {
      const res = await bulkDeleteLeadsFromDB(ids)
      toast.success(`Deleted ${res.data.deleted ?? ids.length} lead(s) from database.`, { duration: 5000 })
      setSelectedIds(new Set())
      await Promise.all([loadStats(), loadLeads()])
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk deletion failed')
    } finally {
      setBulkActionRunning(false)
    }
  }

  async function handlePromoteToSendable(lead) {
    setPromotingId(lead.id)
    try {
      const res = await promoteLeadToSendable(lead.id, {
        reason: 'Operator-verified via Email Verification Hub: email and association confirmed sendable',
      })
      if (res.data.outcome === 'promoted') {
        toast.success(`✅ ${lead.business_name || lead.email} promoted to Active Sendable!`, { duration: 5000 })
      } else {
        toast.error(`Promotion failed: ${res.data.reason}`)
      }
      loadStats()
      loadLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to promote lead to sendable')
    } finally {
      setPromotingId(null)
    }
  }

  async function handleDeleteLead(lead) {
    setConfirmDeleteLead(null)
    setDeletingId(lead.id)
    try {
      await deleteLeadFromDB(lead.id)
      toast.success(`🗑 ${lead.business_name || lead.email} removed from database.`)
      loadStats()
      loadLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to delete lead')
    } finally {
      setDeletingId(null)
    }
  }

  async function handleRunBulkReverify(dryRun = true) {
    setBulkReverifyLoading(true)
    try {
      const payload = {
        filter_mismatched_only: bulkReverifyFilterMismatched,
        filter_unverified_association_only: bulkReverifyFilterUnverified,
        limit: Number(bulkReverifyLimit) || 50,
        dry_run: dryRun,
      }
      const res = await bulkReverifyLeads(payload)
      setBulkReverifyReport(res.data)
      if (dryRun) {
        toast.success(`Dry-run preview complete: ${res.data.total_records_examined} leads examined`)
      } else {
        toast.success(`Bulk re-verification applied! Corrected: ${res.data.emails_corrected_and_validated}, Excluded: ${res.data.records_excluded_from_active_pool}`)
        loadStats()
        loadLeads()
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to run bulk re-verification')
    } finally {
      setBulkReverifyLoading(false)
    }
  }

  const totalPages = Math.ceil(totalLeads / pageSize) || 1

  return (
    <div className="space-y-6">
      {/* ── KPI Metric Cards ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        <div className="card p-3 bg-slate-900/60 border border-slate-800">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Leads</p>
          <p className="text-2xl font-bold text-white mt-1">{stats?.total_leads ?? '—'}</p>
          <p className="text-[11px] text-slate-500 mt-1">In workspace DB</p>
        </div>

        <div className="card p-3 bg-emerald-950/30 border border-emerald-900/50">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Deliverable</p>
            <CheckCircle2 size={16} className="text-emerald-400" />
          </div>
          <p className="text-2xl font-bold text-emerald-300 mt-1">{stats?.deliverable ?? '—'}</p>
          <p className="text-[11px] text-emerald-500 mt-1">Ready for outreach</p>
        </div>

        <div className="card p-3 bg-amber-950/30 border border-amber-900/50">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Corporate Domains Pending Association Review</p>
            <ShieldAlert size={16} className="text-amber-400" />
          </div>
          <p className="text-2xl font-bold text-amber-300 mt-1">{stats?.corporate_pending_review ?? '—'}</p>
          <p className="text-[11px] text-amber-500 mt-1">Custom business domains</p>
        </div>

        <div className="card p-3 bg-rose-950/30 border border-rose-900/50">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-rose-400 uppercase tracking-wider">Invalid</p>
            <XCircle size={16} className="text-rose-400" />
          </div>
          <p className="text-2xl font-bold text-rose-300 mt-1">{stats?.invalid ?? '—'}</p>
          <p className="text-[11px] text-rose-500 mt-1">Syntax / DNS / 550</p>
        </div>

        <div className="card p-3 bg-amber-950/30 border border-amber-900/50">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Disposable</p>
            <AlertTriangle size={16} className="text-amber-400" />
          </div>
          <p className="text-2xl font-bold text-amber-300 mt-1">{stats?.disposable ?? '—'}</p>
          <p className="text-[11px] text-amber-500 mt-1">Throwaway domains</p>
        </div>

        <div className="card p-3 bg-purple-950/30 border border-purple-900/50">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-purple-400 uppercase tracking-wider">Catch-All / Risky</p>
            <HelpCircle size={16} className="text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-purple-300 mt-1">{(stats?.catch_all ?? 0) + (stats?.risky ?? 0)}</p>
          <p className="text-[11px] text-purple-400/80 mt-1">Accept-all / typos</p>
        </div>

        <div className="card p-3 bg-slate-900/50 border border-slate-800">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Unverified</p>
            <Clock size={16} className="text-slate-400" />
          </div>
          <p className="text-2xl font-bold text-slate-300 mt-1">{stats?.unverified ?? '—'}</p>
          <p className="text-[11px] text-slate-500 mt-1">
            {stats?.unverified_active ?? 0} active · {stats?.unverified_quarantined ?? 0} quarantined
          </p>
        </div>

        <div className="card p-3 bg-rose-950/40 border border-rose-800/60">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-rose-300 uppercase tracking-wider">Quarantined</p>
            <ShieldAlert size={16} className="text-rose-400" />
          </div>
          <p className="text-2xl font-bold text-rose-200 mt-1">{stats?.quarantined ?? '—'}</p>
          <p className="text-[11px] text-rose-400 mt-1">
            {stats?.quarantined_verified ?? 0} verified · {stats?.unverified_quarantined ?? 0} unverified
          </p>
        </div>
      </div>

      {/* ── Active Bulk Job Progress & Summary Banner ─────────────────────────────── */}
      {bulkProgress && (bulkProgress.is_running || (bulkProgress.processed > 0 && !bulkProgress.dismissed)) && (
        <div className={`card p-4 border flex flex-col md:flex-row items-center justify-between gap-4 ${
          bulkProgress.is_running
            ? 'bg-indigo-950/40 border-indigo-800/50'
            : (bulkProgress.failed || 0) > 0
            ? 'bg-amber-950/40 border-amber-800/50'
            : 'bg-emerald-950/30 border-emerald-800/50'
        }`}>
          <div className="space-y-1 w-full md:w-auto">
            <div className="flex items-center gap-2">
              {bulkProgress.is_running ? (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-indigo-400 animate-ping" />
                  <span className="text-sm font-semibold text-indigo-200">Bulk Email Verification in Progress</span>
                </>
              ) : (
                <>
                  <CheckCircle2 size={16} className="text-emerald-400" />
                  <span className="text-sm font-semibold text-emerald-200">Bulk Verification Completed</span>
                </>
              )}
              <span className="text-xs text-slate-400 font-mono">
                ({bulkProgress.processed} / {bulkProgress.total} leads checked)
              </span>
            </div>
            {/* Progress bar */}
            <div className="w-full md:w-80 h-2 bg-slate-800 rounded-full overflow-hidden mt-2">
              <div
                className={`h-full transition-all duration-300 ${bulkProgress.is_running ? 'bg-indigo-500' : 'bg-emerald-500'}`}
                style={{ width: `${Math.min(100, (bulkProgress.processed / Math.max(1, bulkProgress.total)) * 100)}%` }}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-slate-300">
              Valid: <strong className="text-emerald-400">{bulkProgress.valid}</strong> |
              Invalid: <strong className="text-rose-400">{bulkProgress.invalid}</strong> |
              Disposable: <strong className="text-amber-400">{bulkProgress.disposable}</strong> |
              Quarantined: <strong className="text-rose-300">{bulkProgress.quarantined}</strong>
              {(bulkProgress.failed || 0) > 0 && (
                <> | Failed: <strong className="text-red-400">{bulkProgress.failed}</strong></>
              )}
              {(bulkProgress.remaining || 0) > 0 && (
                <> | Remaining: <strong className="text-slate-400">{bulkProgress.remaining}</strong></>
              )}
            </span>
            {bulkProgress.is_running ? (
              <button
                onClick={handleCancelBulk}
                className="btn-secondary py-1 px-3 text-xs border-rose-800 text-rose-300 hover:bg-rose-950/40"
              >
                Cancel Job
              </button>
            ) : (
              <button
                onClick={() => setBulkProgress({ ...bulkProgress, dismissed: true })}
                className="btn-secondary py-1 px-2.5 text-xs text-slate-400 hover:text-white"
              >
                Dismiss
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Controls & Ad-hoc Tester ────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Ad-Hoc Test Card */}
        <div className="card p-4 border border-slate-800 bg-slate-900/60 lg:col-span-2">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Sparkles size={16} className="text-sky-400" />
            Ad-Hoc Single Email Diagnostics
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Test any email address against the 6-layer engine (Syntax, Typos, Disposable Blocklist, DNS/MX).
            <span className="text-slate-500 ml-1">SMTP diagnostics remain permanently disabled by default.</span>
          </p>
          <form onSubmit={handleAdHocTest} className="mt-3 flex gap-2">
            <input
              type="email"
              placeholder="e.g. contact@business.com"
              value={testEmailInput}
              onChange={(e) => setTestEmailInput(e.target.value)}
              className="input flex-1 py-1.5 text-xs bg-slate-950 border-slate-700 text-white placeholder-slate-500"
            />
            <button
              type="submit"
              disabled={testTesting || !testEmailInput.trim()}
              className="btn-primary py-1.5 px-4 text-xs font-semibold flex items-center gap-1.5"
            >
              {testTesting ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
              Test Email
            </button>
          </form>

          {testResult && (
            <div className="mt-4 p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-xs flex flex-col gap-2.5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className={`px-2.5 py-1 rounded-full text-xs font-bold border ${STATUS_CONFIG[testResult.status]?.bg || 'bg-slate-800'} ${STATUS_CONFIG[testResult.status]?.text || 'text-slate-300'} ${STATUS_CONFIG[testResult.status]?.border || 'border-slate-700'}`}>
                    {testResult.mailbox_confirmed ? 'Mailbox Verified' : (STATUS_CONFIG[testResult.status]?.label || testResult.status)}
                  </span>
                  <span className="font-mono text-slate-200 font-semibold">{testResult.email}</span>
                  {testResult.typo_suggestion && (
                    <span className="text-amber-400">
                      Did you mean: <strong>{testResult.typo_suggestion}</strong>?
                    </span>
                  )}
                  {testResult.exclusion_reason && (
                    <span className="text-rose-400 font-medium">[{testResult.exclusion_reason}]</span>
                  )}
                </div>
                <div className="flex items-center gap-3 text-slate-400 text-xs">
                  <span>Confidence: <strong className="text-white">{testResult.score}/100</strong></span>
                  <span>Duration: {testResult.duration_ms}ms</span>
                </div>
              </div>

              <div className="pt-2 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3 text-[11px] text-slate-400">
                <div className="flex items-center gap-3.5">
                  <span>Syntax: <strong className={testResult.syntax_ok ? "text-emerald-400" : "text-rose-400"}>{testResult.syntax_ok ? "Valid (RFC 5322)" : "Invalid"}</strong></span>
                  <span>DNS/MX: <strong className={testResult.has_mx ? "text-emerald-400" : "text-rose-400"}>{testResult.has_mx ? "Valid (MX/A)" : "Missing"}</strong></span>
                  <span>
                    SMTP Mailbox: <strong className={testResult.mailbox_confirmed ? "text-emerald-400" : "text-amber-400"}>
                      {testResult.smtp_check?.status === "not_checked" ? "Not Checked (Disabled)" : testResult.smtp_check?.status}
                    </strong>
                  </span>
                </div>
                <span className="text-slate-400 italic">
                  {testResult.diagnostic_summary || (testResult.mailbox_confirmed ? "Mailbox verified." : "Mailbox existence not confirmed (SMTP probe disabled).")}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Bulk Action Card */}
        <div className="card p-4 border border-slate-800 bg-slate-900/60 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <ShieldCheck size={16} className="text-emerald-400" />
              Pre-Send Deliverability Guard
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Verify unverified leads before running outreach. Ensures invalid and disposable emails never reach campaign queues.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between">
            <div className="text-xs text-slate-500">
              <span>Unverified: </span>
              <strong className="text-slate-300">{stats?.unverified ?? 0}</strong>
              <span className="text-[11px] text-slate-500 block">
                ({stats?.unverified_active ?? 0} active · {stats?.unverified_quarantined ?? 0} quarantined)
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setBulkReverifyReport(null)
                  setShowBulkReverifyModal(true)
                }}
                className="btn-secondary py-1.5 px-3 text-xs font-semibold flex items-center gap-1.5 border-indigo-700/60 text-indigo-300 hover:bg-indigo-950/40"
                title="Scrape company websites to validate ownership, fix mismatches, and exclude invalid records"
              >
                <Globe size={14} className="text-indigo-400" />
                Bulk Re-verify & Cleanup
              </button>
              <button
                onClick={handleStartBulk}
                disabled={bulkStarting || bulkProgress?.is_running || (stats?.unverified ?? 0) === 0}
                className="btn-secondary py-1.5 px-3 text-xs font-semibold flex items-center gap-1.5 border-emerald-700/60 text-emerald-300 hover:bg-emerald-950/40"
              >
                {bulkStarting || bulkProgress?.is_running ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
                {bulkProgress?.is_running ? 'Verifying...' : 'Verify All Unverified'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── View Segment Tabs (Active Sendable vs Quarantined) ─────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveView('active')}
            className={`py-2 px-4 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              activeView === 'active'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <ShieldCheck size={15} />
            Active Sendable Leads ({stats?.deliverable ?? 0})
          </button>
          <button
            onClick={() => setActiveView('corporate_review')}
            className={`py-2 px-4 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              activeView === 'corporate_review'
                ? 'bg-amber-600 text-white shadow-sm'
                : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <Shield size={15} />
            Corporate Domain Review ({stats?.corporate_pending_review ?? 0})
          </button>
          <button
            onClick={() => setActiveView('unverified')}
            className={`py-2 px-4 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              activeView === 'unverified'
                ? 'bg-sky-600 text-white shadow-sm'
                : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <Clock size={15} />
            Pending Verification ({stats?.unverified ?? 0})
          </button>
          <button
            onClick={() => setActiveView('demo_only')}
            className={`py-2 px-4 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              activeView === 'demo_only'
                ? 'bg-amber-600 text-white shadow-sm'
                : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <Sparkles size={15} />
            Demo-Only Eligible ({stats?.demo_only_eligible ?? 0})
          </button>
          <button
            onClick={() => setActiveView('quarantined')}
            className={`py-2 px-4 rounded-lg text-xs font-bold transition-colors flex items-center gap-2 ${
              activeView === 'quarantined'
                ? 'bg-rose-600 text-white shadow-sm'
                : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            <ShieldAlert size={15} />
            Excluded / Quarantined Leads ({stats?.quarantined ?? 0})
          </button>
        </div>

        {/* Filter & Search */}
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search email, business..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="input pl-8 py-1 text-xs w-48 sm:w-60 bg-slate-950 border-slate-700 text-white placeholder-slate-500"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input py-1 px-2.5 text-xs bg-slate-950 border-slate-700 text-white"
          >
            <option value="all">All Statuses</option>
            <option value="valid">Deliverable (Valid)</option>
            <option value="unverified">Unverified</option>
            <option value="invalid">Invalid</option>
            <option value="disposable">Disposable</option>
            <option value="risky">Risky / Typo</option>
            <option value="catch_all">Catch-All</option>
            <option value="not_found">Not Found</option>
          </select>

          <button
            onClick={loadLeads}
            className="btn-secondary py-1 px-2.5 text-xs"
            title="Refresh list"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {activeView === 'corporate_review' && (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 rounded-lg border border-amber-800/50 bg-amber-950/20 px-4 py-3">
          <p className="text-xs text-slate-300">
            Bulk approval covers {eligibleDomainMatchLeads.length} qualified lead(s) on this page. Valid, non-quarantined free-email leads stay in Demo-Only; no-website cases follow website review status, while unverified and quarantined leads stay in their review segments.
          </p>
          <button
            type="button"
            onClick={handleBulkApproveDomainMatches}
            disabled={!eligibleDomainMatchLeads.length || bulkApproving || loading}
            className="btn-primary shrink-0 py-2 px-3 text-xs font-semibold bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Approve visible leads only when verified website and corporate email domains match and source evidence is recorded"
          >
            {bulkApproving ? <RefreshCw size={13} className="inline mr-1.5 animate-spin" /> : <CheckCircle2 size={13} className="inline mr-1.5" />}
            {bulkApproving ? 'Approving…' : `Bulk Approve Matches (${eligibleDomainMatchLeads.length})`}
          </button>
        </div>
      )}

      {/* ── Leads Table ─────────────────────────────────────────────────── */}

      {/* ── Bulk Selection Action Bar (floats above table, appears when rows selected) ── */}
      {someSelected && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-700/60 bg-indigo-950/40 px-4 py-2.5 text-xs">
          <span className="font-semibold text-indigo-200 mr-1">{selectedIds.size} lead{selectedIds.size > 1 ? 's' : ''} selected</span>
          <button onClick={() => setSelectedIds(new Set())} className="text-slate-400 hover:text-white underline text-[11px]">Clear</button>
          <div className="flex flex-wrap items-center gap-2 ml-auto">
            {/* Verify / Re-verify (available on all tabs) */}
            <button
              onClick={handleBulkVerifySelected}
              disabled={bulkActionRunning}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded text-[11px] font-semibold bg-sky-700 hover:bg-sky-600 text-white border border-sky-600 transition-colors disabled:opacity-50"
              title="Run DNS & MX verification on selected leads"
            >
              {bulkActionRunning ? <RefreshCw size={12} className="animate-spin" /> : <ShieldCheck size={12} />}
              {activeView === 'quarantined' ? 'Bulk Re-verify' : 'Bulk Verify'}
            </button>
            {/* Promote to Sendable */}
            {(activeView === 'corporate_review' || activeView === 'demo_only' || activeView === 'quarantined') && (
              <button
                onClick={handleBulkPromoteSelected}
                disabled={bulkActionRunning}
                className="flex items-center gap-1.5 py-1.5 px-3 rounded text-[11px] font-semibold bg-emerald-700 hover:bg-emerald-600 text-white border border-emerald-600 transition-colors disabled:opacity-50"
              >
                {bulkActionRunning ? <RefreshCw size={12} className="animate-spin" /> : <ArrowUpCircle size={12} />}
                Bulk Promote to Sendable
              </button>
            )}
            {/* Delete */}
            <button
              onClick={handleBulkDeleteSelected}
              disabled={bulkActionRunning}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded text-[11px] font-semibold bg-rose-800/80 hover:bg-rose-700 text-rose-200 border border-rose-700 transition-colors disabled:opacity-50"
            >
              {bulkActionRunning ? <RefreshCw size={12} className="animate-spin" /> : <Trash2 size={12} />}
              Bulk Delete
            </button>
          </div>
        </div>
      )}

      {/* Tab hint banners (only when nothing selected) */}
      {!someSelected && activeView === 'demo_only' && (
        <div className="flex items-start gap-3 rounded-lg border border-indigo-800/50 bg-indigo-950/20 px-4 py-2.5">
          <Sparkles size={14} className="text-indigo-400 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-300 leading-relaxed">
            <strong className="text-indigo-300">Demo-Only:</strong> verified public-provider emails pending assignment.
            Select rows to <strong className="text-emerald-300">Bulk Promote</strong> or <strong className="text-rose-300">Bulk Delete</strong>, or use per-row actions.
          </p>
        </div>
      )}
      {!someSelected && activeView === 'quarantined' && (
        <div className="flex items-start gap-3 rounded-lg border border-rose-800/50 bg-rose-950/20 px-4 py-2.5">
          <ShieldAlert size={14} className="text-rose-400 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-300 leading-relaxed">
            <strong className="text-rose-300">Quarantined:</strong> excluded from campaigns.
            Select rows to <strong className="text-amber-300">Bulk Re-verify</strong>, <strong className="text-emerald-300">Bulk Promote</strong>, or <strong className="text-rose-300">Bulk Delete</strong> useless leads.
          </p>
        </div>
      )}
      {!someSelected && activeView === 'corporate_review' && !eligibleDomainMatchLeads.length && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-800/50 bg-amber-950/20 px-4 py-2.5">
          <Shield size={14} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-300 leading-relaxed">
            <strong className="text-amber-300">Corporate Review:</strong> select rows to <strong className="text-emerald-300">Bulk Promote</strong> (verify + approve) or <strong className="text-rose-300">Bulk Delete</strong> useless leads.
          </p>
        </div>
      )}
      {!someSelected && activeView === 'unverified' && (
        <div className="flex items-start gap-3 rounded-lg border border-sky-800/50 bg-sky-950/20 px-4 py-2.5">
          <Clock size={14} className="text-sky-400 mt-0.5 shrink-0" />
          <p className="text-xs text-slate-300 leading-relaxed">
            <strong className="text-sky-300">Pending Verification:</strong> select rows to <strong className="text-sky-300">Bulk Verify</strong> and assign to the right segment, or <strong className="text-rose-300">Bulk Delete</strong> entries you don&apos;t need.
          </p>
        </div>
      )}

      <div className="card border border-slate-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="table w-full text-left text-xs min-w-[1060px]">
            <thead className="bg-slate-900/90 text-slate-400 font-semibold border-b border-slate-800 whitespace-nowrap">
              <tr>
                {/* Select-all checkbox */}
                <th className="py-3 pl-4 pr-2 w-8">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    className="rounded border-slate-600 bg-slate-900 text-indigo-500 focus:ring-0 cursor-pointer"
                    title="Select all on this page"
                  />
                </th>
                <th className="py-3 px-4 min-w-[200px]">Business / Website</th>
                <th className="py-3 px-4 min-w-[190px]">Email Address</th>
                <th className="py-3 px-4 min-w-[140px]">Verification Status</th>
                <th className="py-3 px-4 min-w-[180px]">Business Association</th>
                {activeView === 'corporate_review' && <th className="py-3 px-4 min-w-[220px]">Provenance Evidence</th>}
                <th className="py-3 px-4 min-w-[120px]">Deliverability Score</th>
                {activeView === 'quarantined' && <th className="py-3 px-4 min-w-[260px] max-w-md">Exclusion Reason</th>}
                <th className="py-3 px-4 text-right min-w-[220px] whitespace-nowrap sticky right-0 bg-slate-900 shadow-[-8px_0_12px_rgba(15,23,42,0.8)]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading ? (
                <tr>
                  <td colSpan={(activeView === 'quarantined' || activeView === 'corporate_review') ? 8 : 7} className="py-12 text-center text-slate-500">
                    <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-indigo-400" />
                    Loading leads...
                  </td>
                </tr>
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={(activeView === 'quarantined' || activeView === 'corporate_review') ? 8 : 7} className="py-12 text-center text-slate-500">
                    {activeView === 'quarantined'
                      ? 'No leads currently in quarantine.'
                      : activeView === 'demo_only'
                      ? 'No demo-only eligible leads found.'
                      : activeView === 'corporate_review'
                      ? 'No corporate domain leads pending association review.'
                      : 'No leads found matching your criteria.'}
                  </td>
                </tr>
              ) : (
                leads.map((lead) => {
                  const conf = STATUS_CONFIG[lead.verification_status] || STATUS_CONFIG.unverified
                  const Icon = conf.icon
                  const score = lead.deliverability_score || 0

                  return (
                    <tr key={lead.id} className={`hover:bg-slate-800/30 transition-colors ${selectedIds.has(lead.id) ? 'bg-indigo-950/20' : ''}`}>
                      {/* Checkbox */}
                      <td className="py-3 pl-4 pr-2 w-8">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(lead.id)}
                          onChange={() => toggleSelectOne(lead.id)}
                          className="rounded border-slate-600 bg-slate-900 text-indigo-500 focus:ring-0 cursor-pointer"
                        />
                      </td>
                      <td className="py-3 px-4 min-w-[200px]">
                        <p className="font-semibold text-white truncate max-w-xs">{lead.business_name || '—'}</p>
                        <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
                          {lead.website ? (
                            <a
                              href={lead.website?.startsWith('http') ? lead.website : `https://${lead.website}`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-slate-400 hover:text-sky-400 truncate max-w-xs block font-mono inline-flex items-center gap-1"
                              title={lead.website}
                            >
                              <Globe size={11} className="shrink-0 text-slate-500" />
                              {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                            </a>
                          ) : (
                            <span className="text-[11px] text-slate-500 italic">No website URL</span>
                          )}
                          {lead.website_association_status === 'candidate_match' && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-500/10 text-blue-300 border border-blue-500/20" title="Inferred candidate website from business email domain — unverified">
                              Inferred — unverified
                            </span>
                          )}
                        </div>
                      </td>

                      <td className="py-3 px-4 font-mono text-slate-300 min-w-[190px]">
                        <span className="truncate block max-w-xs" title={lead.email}>{lead.email}</span>
                      </td>

                      <td className="py-3 px-4 whitespace-nowrap min-w-[140px]">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${conf.bg} ${conf.text} ${conf.border}`}>
                          <Icon size={12} />
                          {conf.label}
                        </span>
                      </td>

                      <td className="py-3 px-4 min-w-[180px]">
                        <AssociationBadge status={lead.association_status} />
                        {lead.association_reason && (
                          <p className="mt-1 max-w-[240px] truncate text-[10px] text-slate-500" title={lead.association_reason}>{lead.association_reason}</p>
                        )}
                      </td>

                      {activeView === 'corporate_review' && (
                        <td className="py-3 px-4 min-w-[220px]">
                          <div className="space-y-1">
                            <div className="flex items-center gap-1.5 text-[11px]">
                              <span className="text-slate-400">Match:</span>
                              {lead.website_association_status === 'candidate_match' && lead.email_domain_match === true ? (
                                <span className="text-blue-300 font-medium" title="Email domain matches inferred website candidate (unverified signal)">Inferred domain match</span>
                              ) : lead.email_domain_match === true ? (
                                <span className="text-emerald-400 font-medium">Domain matched</span>
                              ) : lead.email_domain_match === false ? (
                                <span className="text-amber-400 font-medium">External domain</span>
                              ) : (
                                <span className="text-slate-400 font-medium">Unchecked</span>
                              )}
                            </div>
                            {lead.email_source_type && (
                              <p className="text-[10px] text-slate-400">
                                Source: <span className="text-slate-300 font-mono">{lead.email_source_type}</span>
                              </p>
                            )}
                            {lead.email_source_url ? (
                              <a
                                href={lead.email_source_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-[10px] text-sky-400 hover:underline truncate block max-w-[200px]"
                                title={lead.email_source_url}
                              >
                                {lead.email_source_url}
                              </a>
                            ) : (
                              <span className="text-[10px] text-slate-500 italic">No source URL recorded</span>
                            )}
                          </div>
                        </td>
                      )}

                      <td className="py-3 px-4 whitespace-nowrap min-w-[120px]">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-2 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full ${score >= 80 ? 'bg-emerald-500' : score >= 50 ? 'bg-amber-500' : 'bg-rose-500'}`}
                              style={{ width: `${score}%` }}
                            />
                          </div>
                          <span className="text-[11px] font-mono text-slate-400">{score}%</span>
                        </div>
                      </td>

                      {activeView === 'quarantined' && (
                        <td className="py-3 px-4 min-w-[260px] max-w-md">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2">
                              {lead.verification_status === 'invalid' || lead.verification_status === 'not_found' || lead.association_status === 'mismatched_source' ? (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-950/60 text-rose-400 border border-rose-800/60">
                                  <Ban size={10} /> Confirmed Unsafe
                                </span>
                              ) : lead.verification_status === 'unverified' ? (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-950/60 text-amber-300 border border-amber-800/60">
                                  <Clock size={10} /> Unverified (Needs Check)
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">
                                  <Shield size={10} /> Review Required
                                </span>
                              )}
                            </div>
                            <span className="text-xs text-rose-300 font-medium block leading-relaxed" title={lead.quarantine_reason || 'Policy exclusion'}>
                              {lead.quarantine_reason || 'Policy exclusion'}
                            </span>
                          </div>
                        </td>
                      )}

                      <td className="py-3 px-4 text-right whitespace-nowrap min-w-[220px] sticky right-0 bg-[#0f172a] shadow-[-8px_0_12px_rgba(15,23,42,0.8)]">
                        <div className="flex items-center justify-end gap-1.5 flex-wrap">
                          {/* ── Details ── */}
                          <button
                            onClick={() => setSelectedLead(lead)}
                            className="btn-secondary py-1 px-2 text-[11px] text-slate-300 hover:text-white"
                            title="View detailed 6-layer audit"
                          >
                            <Eye size={12} className="inline mr-1" />
                            Details
                          </button>

                          {/* ── Tab-specific primary action ── */}
                          {activeView === 'corporate_review' ? (
                            <>
                              {/* Approve association → Active Sendable */}
                              <button
                                onClick={() => {
                                  setApprovingLead(lead)
                                  setApprovalReason('Verified corporate association between business website and corporate email domain via provenance evidence')
                                }}
                                className="btn-primary py-1 px-2 text-[11px] font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
                                title="Review & approve corporate domain association"
                              >
                                <CheckCircle2 size={12} className="inline mr-1" />
                                Approve
                              </button>
                              {/* Quick promote: re-verify + approve in one click */}
                              <button
                                onClick={() => handlePromoteToSendable(lead)}
                                disabled={promotingId === lead.id}
                                className="py-1 px-2 rounded text-[11px] font-semibold bg-sky-700 hover:bg-sky-600 text-white border border-sky-600 transition-colors"
                                title="Re-verify email and auto-approve to Active Sendable"
                              >
                                {promotingId === lead.id
                                  ? <RefreshCw size={12} className="animate-spin inline mr-1" />
                                  : <ArrowUpCircle size={12} className="inline mr-1" />}
                                Promote
                              </button>
                            </>
                          ) : activeView === 'demo_only' ? (
                            <>
                              {/* Promote demo-only lead → Active Sendable */}
                              <button
                                onClick={() => handlePromoteToSendable(lead)}
                                disabled={promotingId === lead.id}
                                className="py-1 px-2 rounded text-[11px] font-semibold bg-indigo-700 hover:bg-indigo-600 text-white border border-indigo-600 transition-colors"
                                title="Verify email and promote to Active Sendable segment"
                              >
                                {promotingId === lead.id
                                  ? <RefreshCw size={12} className="animate-spin inline mr-1" />
                                  : <ArrowUpCircle size={12} className="inline mr-1" />}
                                Promote
                              </button>
                            </>
                          ) : activeView === 'quarantined' ? (
                            <>
                              {/* Re-verify quarantined lead (may restore to sendable) */}
                              <button
                                onClick={() => handleVerifyLead(lead.id, true)}
                                disabled={verifyingId === lead.id}
                                className="py-1 px-2 rounded text-[11px] font-semibold bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700 transition-colors"
                              >
                                {verifyingId === lead.id
                                  ? <RefreshCw size={12} className="animate-spin inline mr-1" />
                                  : <ShieldCheck size={12} className="inline mr-1" />}
                                Re-verify
                              </button>
                              {/* Promote: force-verify + approve → move to Active Sendable */}
                              <button
                                onClick={() => handlePromoteToSendable(lead)}
                                disabled={promotingId === lead.id}
                                className="py-1 px-2 rounded text-[11px] font-semibold bg-emerald-800/70 hover:bg-emerald-700 text-emerald-200 border border-emerald-700 transition-colors"
                                title="Force-verify and promote to Active Sendable (clears quarantine if email passes)"
                              >
                                {promotingId === lead.id
                                  ? <RefreshCw size={12} className="animate-spin inline mr-1" />
                                  : <ArrowUpCircle size={12} className="inline mr-1" />}
                                Promote
                              </button>
                            </>
                          ) : (
                            /* active (unverified / active views) */
                            <button
                              onClick={() => handleVerifyLead(lead.id, false)}
                              disabled={verifyingId === lead.id}
                              className="btn-primary py-1 px-2 text-[11px]"
                            >
                              {verifyingId === lead.id
                                ? <RefreshCw size={12} className="animate-spin inline mr-1" />
                                : <Play size={12} className="inline mr-1" />}
                              Verify
                            </button>
                          )}

                          {/* ── Delete from DB (all tabs) ── */}
                          <button
                            onClick={() => setConfirmDeleteLead(lead)}
                            disabled={deletingId === lead.id}
                            className="py-1 px-2 rounded text-[11px] font-semibold bg-transparent hover:bg-rose-950/60 text-rose-500 hover:text-rose-300 border border-rose-900/50 hover:border-rose-700 transition-colors"
                            title="Permanently delete this lead from the database"
                          >
                            {deletingId === lead.id
                              ? <RefreshCw size={12} className="animate-spin inline" />
                              : <Trash2 size={12} className="inline" />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Pagination ──────────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>Showing Page {page} of {totalPages} ({totalLeads} total leads)</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="btn-secondary py-1 px-3 text-xs"
              style={{ opacity: page <= 1 ? 0.4 : 1 }}
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn-secondary py-1 px-3 text-xs"
              style={{ opacity: page >= totalPages ? 0.4 : 1 }}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* ── Detailed 6-Layer Diagnostic Modal ────────────────────────────── */}
      {selectedLead && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 p-4 bg-black/75 backdrop-blur-sm animate-fade-in overflow-y-auto">
          <div className="card w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-6 relative max-h-[calc(100vh-5rem)] overflow-y-auto mb-8">
            <button
              onClick={() => setSelectedLead(null)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white"
            >
              <X size={18} />
            </button>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-indigo-950/80 border border-indigo-700/50 flex items-center justify-center">
                <Mail size={20} className="text-indigo-400" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">{selectedLead.business_name || 'Lead Details'}</h3>
                <p className="text-xs font-mono text-slate-400">{selectedLead.email}</p>
              </div>
            </div>

            {/* Quarantine status badge in modal */}
            {selectedLead.is_quarantined && (
              <div className="mt-4 p-3 rounded-lg bg-rose-950/50 border border-rose-800/60 flex items-start gap-2.5">
                <ShieldAlert size={16} className="text-rose-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-xs font-bold text-rose-300">Lead is Quarantined / Non-Sendable</p>
                  <p className="text-[11px] text-rose-400 mt-0.5">
                    Reason: {selectedLead.quarantine_reason || 'Email verification policy violation'}
                  </p>
                </div>
              </div>
            )}

            <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-bold text-slate-300">Website & Identity Association</p>
                {!selectedLead.is_quarantined && selectedLead.verification_status === 'valid' && ['unverified_association', 'external_domain_review', 'pending_review', 'unverified'].includes(selectedLead.association_status) && (
                  <button
                    onClick={() => {
                      setApprovingLead(selectedLead)
                      setApprovalReason('Verified corporate association between business website and corporate email domain via provenance evidence')
                    }}
                    className="btn-primary py-1 px-2.5 text-[11px] font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1"
                  >
                    <CheckCircle2 size={12} />
                    Approve Association
                  </button>
                )}
              </div>

              {/* Website Candidate Display */}
              <div className="mt-3 p-2.5 rounded bg-slate-900/60 border border-slate-800 flex flex-col gap-1">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  {selectedLead.website_association_status === 'candidate_match' ? 'Inferred Website Candidate' : 'Business Website'}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  {selectedLead.website ? (
                    <a
                      href={selectedLead.website?.startsWith('http') ? selectedLead.website : `https://${selectedLead.website}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-mono text-sky-400 hover:underline flex items-center gap-1"
                    >
                      <Globe size={12} className="text-slate-400" />
                      {selectedLead.website}
                    </a>
                  ) : (
                    <span className="text-xs text-slate-500 italic">No website URL recorded</span>
                  )}
                  {selectedLead.website_association_status === 'candidate_match' && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-300 border border-blue-500/20">
                      Inferred — unverified
                    </span>
                  )}
                  {selectedLead.website_association_status === 'candidate_match' && (!selectedLead.details?.has_mx || selectedLead.verification_status === 'not_found' || selectedLead.quarantine_reason?.includes('NXDOMAIN')) && (
                    <span className="text-[10px] text-amber-400/90 font-medium">
                      (DNS / MX unconfirmed — domain does not resolve)
                    </span>
                  )}
                </div>
              </div>

              {/* Association Status & Explanation */}
              <div className="mt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <AssociationBadge status={selectedLead.association_status} />
                  {selectedLead.website_association_status === 'candidate_match' && selectedLead.email_domain_match === true ? (
                    <span className="text-[11px] text-blue-300 font-medium">
                      Email domain matches inferred candidate domain (unverified signal)
                    </span>
                  ) : selectedLead.email_domain_match === true ? (
                    <span className="text-[11px] text-emerald-400 font-medium">Email domain matches verified website</span>
                  ) : selectedLead.email_domain_match === false ? (
                    <span className="text-[11px] text-rose-400 font-medium">Email domain does not match website</span>
                  ) : null}
                </div>
                <p className="mt-2 text-xs text-slate-300 leading-relaxed font-sans">
                  {selectedLead.association_reason || 'No association explanation recorded.'}
                </p>
              </div>

              {/* Third-Party Evidence Provenance Link */}
              {selectedLead.email_source_url && (
                <div className="mt-3 pt-2.5 border-t border-slate-800/80">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                    Evidence Provenance ({selectedLead.email_source_type ? `${selectedLead.email_source_type.toUpperCase()} / ` : ''}External Discovery Source):
                  </span>
                  <a
                    className="mt-1 block truncate text-[11px] font-mono text-sky-400 hover:text-sky-300"
                    href={selectedLead.email_source_url}
                    target="_blank"
                    rel="noreferrer"
                    title={selectedLead.email_source_url}
                  >
                    {selectedLead.email_source_url}
                  </a>
                  <p className="mt-1 text-[10px] text-slate-500">
                    Third-party registry/directory link records where the lead contact was discovered. It is evidence provenance and is not the company's official website.
                  </p>
                </div>
              )}

              <p className="mt-2.5 text-[10px] text-slate-500 italic">
                Matching domains are a useful signal, not proof of ownership. Inference alone does not approve association or release quarantine.
              </p>
            </div>

            {/* 6 Verification Layers */}
            <div className="mt-5 space-y-3">
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">6-Layer Pipeline Inspection</h4>

              {/* Layer 1: Syntax */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between">
                <div>
                  <p className="text-xs font-bold text-white">Layer 1: Syntax Validation (RFC 5322)</p>
                  <p className="text-[11px] text-slate-400">Length checks, local part, domain structure</p>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${selectedLead.details?.syntax_ok ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}`}>
                  {selectedLead.details?.syntax_ok ? 'PASS' : 'FAIL'}
                </span>
              </div>

              {/* Layer 2: Typo Detection */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between">
                <div>
                  <p className="text-xs font-bold text-white">Layer 2: Domain Typo Detection</p>
                  <p className="text-[11px] text-slate-400">
                    {selectedLead.details?.typo_suggestion ? (
                      <span className="text-amber-400 font-semibold">Suggested typo fix: {selectedLead.details.typo_suggestion}</span>
                    ) : (
                      'No typo detected'
                    )}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${selectedLead.details?.typo_suggestion ? 'bg-amber-950 text-amber-400 border border-amber-800' : 'bg-emerald-950 text-emerald-400 border border-emerald-800'}`}>
                  {selectedLead.details?.typo_suggestion ? 'TYPO' : 'PASS'}
                </span>
              </div>

              {/* Layer 3: Disposable Domain Check */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between">
                <div>
                  <p className="text-xs font-bold text-white">Layer 3: Disposable Domain Blocklist</p>
                  <p className="text-[11px] text-slate-400">300+ known temporary / throwaway services</p>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${selectedLead.details?.is_disposable ? 'bg-rose-950 text-rose-400 border border-rose-800' : 'bg-emerald-950 text-emerald-400 border border-emerald-800'}`}>
                  {selectedLead.details?.is_disposable ? 'DISPOSABLE' : 'CLEAN'}
                </span>
              </div>

              {/* Layer 4: DNS / MX Lookup */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-start justify-between">
                <div>
                  <p className="text-xs font-bold text-white">Layer 4: DNS & MX Records (with A-Fallback)</p>
                  <p className="text-[11px] text-slate-400">
                    {selectedLead.details?.has_mx ? (
                      `Exchanges: ${(selectedLead.details?.mx_records || []).slice(0, 3).join(', ') || 'Active'}`
                    ) : (
                      'No valid MX or A records found'
                    )}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${selectedLead.details?.has_mx ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-rose-950 text-rose-400 border border-rose-800'}`}>
                  {selectedLead.details?.has_mx ? 'VALID' : 'NO MX'}
                </span>
              </div>

              {/* Layer 5: Optional SMTP Handshake */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between opacity-80">
                <div>
                  <p className="text-xs font-bold text-slate-300">Layer 5: SMTP Mailbox Handshake (Diagnostic)</p>
                  <p className="text-[11px] text-slate-500">
                    Status: {selectedLead.details?.smtp_check?.status || 'not_checked'} (Disabled by default)
                  </p>
                </div>
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                  {selectedLead.details?.smtp_check?.status || 'not_checked'}
                </span>
              </div>

              {/* Layer 6: Optional Catch-All Probe */}
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between opacity-80">
                <div>
                  <p className="text-xs font-bold text-slate-300">Layer 6: Catch-All Domain Analysis (Diagnostic)</p>
                  <p className="text-[11px] text-slate-500">
                    Status: {selectedLead.details?.catch_all_status || 'not_checked'} (Disabled by default)
                  </p>
                </div>
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700">
                  {selectedLead.details?.catch_all_status || 'not_checked'}
                </span>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                Verified at: {selectedLead.verified_at ? new Date(selectedLead.verified_at).toLocaleString() : 'Not yet'}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSelectedLead(null)}
                  className="btn-secondary py-1.5 px-3 text-xs"
                >
                  Close
                </button>
                <button
                  onClick={() => handleVerifyLead(selectedLead.id, selectedLead.is_quarantined)}
                  disabled={verifyingId === selectedLead.id}
                  className="btn-primary py-1.5 px-3 text-xs font-semibold"
                >
                  {verifyingId === selectedLead.id ? 'Verifying...' : 'Re-verify Lead'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Operator Corporate Domain Association Approval Modal ────────── */}
      {approvingLead && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 p-4 bg-black/75 backdrop-blur-sm animate-fade-in overflow-y-auto">
          <div className="card w-full max-w-lg bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-6 relative mb-8">
            <button
              onClick={() => {
                setApprovingLead(null)
                setApprovalReason('')
              }}
              className="absolute top-4 right-4 text-slate-400 hover:text-white"
            >
              <X size={18} />
            </button>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-950/80 border border-emerald-700/50 flex items-center justify-center">
                <ShieldCheck size={20} className="text-emerald-400" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Approve Corporate Domain Association</h3>
                <p className="text-xs text-slate-400">Operator review and auditable policy approval</p>
              </div>
            </div>

            <div className="mt-4 p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-2">
              <div className="flex justify-between">
                <span className="text-slate-400">Business:</span>
                <span className="text-white font-semibold">{approvingLead.business_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Website:</span>
                <span className="text-sky-400">{approvingLead.website || 'No website URL'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Email:</span>
                <span className="text-emerald-400 font-mono">{approvingLead.email}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Domain Match:</span>
                <span className="text-slate-300">{approvingLead.email_domain_match ? 'Matched' : 'External Domain'}</span>
              </div>
              {approvingLead.email_source_url && (
                <div className="flex justify-between gap-2">
                  <span className="text-slate-400 flex-shrink-0">Evidence URL:</span>
                  <span className="text-slate-300 font-mono truncate text-[11px] max-w-[280px]" title={approvingLead.email_source_url}>
                    {approvingLead.email_source_url}
                  </span>
                </div>
              )}
            </div>

            <div className="mt-4">
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Auditable Justification Reason (min 5 chars) *
              </label>
              <textarea
                rows={3}
                value={approvalReason}
                onChange={(e) => setApprovalReason(e.target.value)}
                placeholder="Document provenance evidence and justification..."
                className="input w-full p-2 text-xs bg-slate-950 border-slate-700 text-white placeholder-slate-500 rounded"
              />
            </div>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => {
                  setApprovingLead(null)
                  setApprovalReason('')
                }}
                disabled={submittingApproval}
                className="btn-secondary py-1.5 px-3 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleApproveAssociation}
                disabled={submittingApproval || approvalReason.trim().length < 5}
                className="btn-primary py-1.5 px-4 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5"
              >
                {submittingApproval ? <RefreshCw size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
                Confirm Approval
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Bulk Re-verify & Cleanup Modal ─────────────────────────────── */}
      {/* ── Delete Confirmation Modal ────────────────────────────────── */}
      {confirmDeleteLead && (
        <div className="fixed inset-0 z-[60] flex items-start justify-center pt-16 p-4 bg-black/80 backdrop-blur-sm overflow-y-auto">
          <div className="card w-full max-w-md bg-slate-900 border border-rose-800/70 rounded-xl shadow-2xl p-6 mb-8">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-rose-950/80 border border-rose-700/50 flex items-center justify-center">
                <Trash2 size={20} className="text-rose-400" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">Delete Lead from Database</h3>
                <p className="text-xs text-rose-400">This action is permanent and cannot be undone.</p>
              </div>
            </div>

            <div className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-2 mb-5">
              <div className="flex justify-between">
                <span className="text-slate-400">Business:</span>
                <span className="text-white font-semibold">{confirmDeleteLead.business_name || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Email:</span>
                <span className="text-rose-300 font-mono">{confirmDeleteLead.email}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Status:</span>
                <span className="text-slate-300">{confirmDeleteLead.verification_status || 'unknown'}</span>
              </div>
            </div>

            <p className="text-xs text-slate-400 mb-5 leading-relaxed">
              Deleting this lead will permanently remove it and all associated records (audit data, email verification history, activity logs) from the database. If you want to keep it but stop outreach, use <strong className="text-slate-200">Re-verify</strong> to quarantine it instead.
            </p>

            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setConfirmDeleteLead(null)}
                className="btn-secondary py-1.5 px-4 text-xs"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDeleteLead(confirmDeleteLead)}
                className="py-1.5 px-4 rounded text-xs font-semibold bg-rose-700 hover:bg-rose-600 text-white flex items-center gap-1.5 transition-colors"
              >
                <Trash2 size={13} />
                Yes, Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Bulk Re-verify & Cleanup Modal ─────────────────────────────── */}
      {showBulkReverifyModal && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 bg-black/75 p-4 backdrop-blur-sm overflow-y-auto">
          <div className="card w-full max-w-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl rounded-xl my-8">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <Globe size={18} className="text-indigo-400" />
                <h3 className="text-base font-bold text-white">Bulk Re-verify Email Ownership & Cleanup</h3>
              </div>
              <button
                onClick={() => setShowBulkReverifyModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-slate-300 mt-3 leading-relaxed">
              Scrapes each lead's official company website using bounded concurrency and SSRF protection.
              Discovers published contact emails, validates domain ownership, corrects mismatched addresses,
              re-runs syntax and MX verification, and safely excludes unverified or empty records via reversible quarantine.
            </p>

            {/* Scope / Filter Configuration */}
            <div className="mt-4 p-3.5 rounded-lg bg-slate-950 border border-slate-800 text-xs space-y-3">
              <span className="font-semibold text-slate-200 block">Workflow Scope & Filter Criteria:</span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={bulkReverifyFilterMismatched}
                    onChange={(e) => setBulkReverifyFilterMismatched(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span>Target domain mismatches only</span>
                </label>
                <label className="flex items-center gap-2 text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={bulkReverifyFilterUnverified}
                    onChange={(e) => setBulkReverifyFilterUnverified(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0"
                  />
                  <span>Unverified association only</span>
                </label>
              </div>

              <div className="flex items-center gap-3 pt-2 border-t border-slate-900">
                <span className="text-slate-400">Batch Size Limit:</span>
                <select
                  value={bulkReverifyLimit}
                  onChange={(e) => setBulkReverifyLimit(Number(e.target.value))}
                  className="input py-1 px-2 text-xs bg-slate-900 border-slate-700 text-white rounded"
                >
                  <option value={10}>10 records (fast test)</option>
                  <option value={25}>25 records</option>
                  <option value={50}>50 records (recommended)</option>
                  <option value={100}>100 records</option>
                  <option value={200}>200 records</option>
                </select>
              </div>
            </div>

            {/* Summary Metrics Report */}
            {bulkReverifyReport && (
              <div className="mt-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-white flex items-center gap-1.5">
                    <Sparkles size={14} className="text-amber-400" />
                    {bulkReverifyReport.mode === 'dry_run' ? 'Dry-Run Preview Report' : 'Applied Execution Report'}
                  </span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                    bulkReverifyReport.mode === 'dry_run' ? 'bg-amber-950/80 text-amber-300 border border-amber-800/60' : 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/60'
                  }`}>
                    {bulkReverifyReport.mode}
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-slate-500 block">Examined</span>
                    <strong className="text-white text-sm">{bulkReverifyReport.total_records_examined}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-amber-400 block">Domain Mismatches</span>
                    <strong className="text-amber-300 text-sm">{bulkReverifyReport.domain_mismatches_identified}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-emerald-400 block">Website Replacements</span>
                    <strong className="text-emerald-300 text-sm">{bulkReverifyReport.website_replacements_found}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-emerald-400 block">Emails Corrected</span>
                    <strong className="text-emerald-300 text-sm">{bulkReverifyReport.emails_corrected_and_validated}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-sky-400 block">Retained / Revalidated</span>
                    <strong className="text-sky-300 text-sm">{bulkReverifyReport.emails_revalidated_and_retained}</strong>
                  </div>
                  <div className="p-2.5 rounded bg-slate-950 border border-slate-800">
                    <span className="text-[10px] text-rose-400 block">Excluded from Outreach</span>
                    <strong className="text-rose-300 text-sm">{bulkReverifyReport.records_excluded_from_active_pool}</strong>
                  </div>
                </div>

                {/* Per-record preview table (first 8 results) */}
                {bulkReverifyReport.results?.length > 0 && (
                  <div className="mt-2 max-h-48 overflow-y-auto rounded border border-slate-800 text-[11px]">
                    <table className="w-full text-left">
                      <thead className="bg-slate-950 text-slate-400 sticky top-0 border-b border-slate-800">
                        <tr>
                          <th className="p-2">Business</th>
                          <th className="p-2">Previous Email</th>
                          <th className="p-2">Action / New Email</th>
                          <th className="p-2">Outcome</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60 bg-slate-900/80">
                        {bulkReverifyReport.results.slice(0, 15).map((r, i) => (
                          <tr key={i} className="hover:bg-slate-800/30">
                            <td className="p-2 font-medium text-slate-200 truncate max-w-[140px]">{r.business_name}</td>
                            <td className="p-2 text-slate-400 font-mono truncate max-w-[130px]">{r.old_email || '—'}</td>
                            <td className="p-2 font-mono truncate max-w-[140px]">
                              {r.outcome_status === 'corrected' ? (
                                <span className="text-emerald-400 font-semibold">{r.new_email}</span>
                              ) : (
                                <span className="text-slate-300">{r.new_email || '—'}</span>
                              )}
                            </td>
                            <td className="p-2">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                r.outcome_status === 'corrected' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                                r.outcome_status === 'revalidated' ? 'bg-sky-950 text-sky-400 border border-sky-800' :
                                r.outcome_status === 'no_email_found' ? 'bg-rose-950 text-rose-400 border border-rose-800' :
                                'bg-slate-800 text-slate-300'
                              }`}>
                                {r.outcome_status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Action buttons */}
            <div className="mt-5 flex items-center justify-end gap-2 pt-3 border-t border-slate-800">
              <button
                onClick={() => setShowBulkReverifyModal(false)}
                disabled={bulkReverifyLoading}
                className="btn-secondary py-1.5 px-3 text-xs"
              >
                Close
              </button>
              <button
                onClick={() => handleRunBulkReverify(true)}
                disabled={bulkReverifyLoading}
                className="btn-secondary py-1.5 px-3.5 text-xs font-semibold border-amber-700/60 text-amber-300 hover:bg-amber-950/40 flex items-center gap-1.5"
              >
                {bulkReverifyLoading ? <RefreshCw size={13} className="animate-spin" /> : <Eye size={13} />}
                Run Dry-Run Preview
              </button>
              <button
                onClick={() => handleRunBulkReverify(false)}
                disabled={bulkReverifyLoading}
                className="btn-primary py-1.5 px-4 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white flex items-center gap-1.5"
              >
                {bulkReverifyLoading ? <RefreshCw size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
                Apply Batch Correction
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
