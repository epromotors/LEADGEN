import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import {
  Upload, Trash2, Search, RefreshCw, Globe, PlayCircle, Filter,
  CheckCircle2, Pencil, X, Sparkles, Check, ArrowUpDown, ChevronDown,
  ChevronUp, ArrowRight, ShieldAlert, ShieldCheck, AlertTriangle
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getLeads,
  uploadLeads,
  deleteLead,
  bulkDeleteLeads,
  triggerAudit,
  triggerAllAudits,
  triggerSkippedAudits,
  getAuditStats,
  getLeadQualityReviewQueue,
  retryLeadQualityDiscovery,
  keepLeadUnderReview,
} from '../api/client'
import BulkImportDiscovery from '../components/BulkImportDiscovery'
import EditLeadModal from '../components/lead/EditLeadModal'
import AuditModeModal from '../components/lead/AuditModeModal'
import AuditDoneModal from '../components/lead/AuditDoneModal'
import LeadTableSkeleton from '../components/lead/LeadTableSkeleton'
import LeadEmptyState from '../components/lead/LeadEmptyState'
import LeadRowMobileCard from '../components/lead/LeadRowMobileCard'
import LeadQualityReviewPanel from '../components/lead/LeadQualityReviewPanel'
import {
  LifecycleBadge,
  VerificationBadge,
  AssociationBadge,
  WebsiteStatusBadge,
  SkippedReasonBadge,
} from '../components/lead/LeadStatusBadge'

export default function Leads() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  // Status and search filters (synchronized with URL query params)
  const initialStatus = searchParams.get('status') || ''
  const [filter, setFilter] = useState(initialStatus)
  const [search, setSearch] = useState(searchParams.get('q') || '')
  const [searchInput, setSearchInput] = useState(searchParams.get('q') || '')
  const [page, setPage] = useState(1)

  // Selection & modals
  const [selected, setSelected] = useState(new Set())
  const [editLead, setEditLead] = useState(null)
  const [auditModeModal, setAuditModeModal] = useState(false)
  const [auditDoneModal, setAuditDoneModal] = useState({ visible: false, count: 0 })
  const [dbStats, setDbStats] = useState(null)
  const [qualityReviewOpen, setQualityReviewOpen] = useState(false)
  const [qualityReviewLoading, setQualityReviewLoading] = useState(false)
  const [qualityRecords, setQualityRecords] = useState([])
  const [qualityTotal, setQualityTotal] = useState(0)
  const [qualityPage, setQualityPage] = useState(1)
  const [qualityCounts, setQualityCounts] = useState(null)
  const [qualitySearch, setQualitySearch] = useState('')
  const qualityPageSize = 25

  async function openQualityReview(targetPage = 1, searchQuery = qualitySearch) {
    setQualityReviewOpen(true)
    setQualityReviewLoading(true)
    try {
      const params = { page: targetPage, page_size: qualityPageSize }
      if (searchQuery) params.search = searchQuery
      const res = await getLeadQualityReviewQueue(params)
      setQualityRecords(res.data.records || [])
      setQualityTotal(res.data.total ?? 0)
      setQualityPage(res.data.page ?? targetPage)
      setQualityCounts(res.data.counts || null)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to load lead quality review queue.')
    } finally {
      setQualityReviewLoading(false)
    }
  }

  function handleQualitySearch(query) {
    setQualitySearch(query)
    openQualityReview(1, query)
  }

  async function retryQualityDiscovery(id, reverifyEmail = false) {
    const t = toast.loading(reverifyEmail ? 'Re-verifying email deliverability…' : 'Running bounded discovery…')
    try {
      await retryLeadQualityDiscovery(id, reverifyEmail)
      toast.success(
        reverifyEmail
          ? 'Email verification updated without SMTP probing.'
          : 'Discovery evidence refreshed; no association or campaign eligibility was approved.',
        { id: t }
      )
      await openQualityReview(qualityPage)
      fetchLeads(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Discovery retry failed.', { id: t })
    }
  }

  async function keepQualityUnderReview(id) {
    const t = toast.loading('Acknowledging review…')
    try {
      await keepLeadUnderReview(id)
      toast.success('Lead acknowledged and retained under operator review.', { id: t })
      await openQualityReview(qualityPage)
      fetchLeads(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to retain lead under review.', { id: t })
    }
  }

  async function handleQualityDeleteOne(id) {
    const t = toast.loading('Deleting lead…')
    try {
      await deleteLead(id)
      toast.success('Lead deleted successfully.', { id: t })
      await openQualityReview(qualityPage)
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete failed.', { id: t })
    }
  }

  async function handleQualityBulkDelete(ids) {
    const t = toast.loading(`Deleting ${ids.length} selected lead(s)…`)
    try {
      const res = await bulkDeleteLeads(ids)
      const deletedCount = res.data.deleted ?? ids.length
      toast.success(`Deleted ${deletedCount} of ${ids.length} selected lead(s).`, { id: t })
      await openQualityReview(1)
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk delete failed.', { id: t })
    }
  }

  // Sync state if query param changes externally
  useEffect(() => {
    const qStatus = searchParams.get('status') || ''
    if (qStatus !== filter) {
      setFilter(qStatus)
      setPage(1)
    }
  }, [searchParams])

  const fetchLeads = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setLoadError(null)

    try {
      const res = await getLeads({
        page,
        page_size: pageSize,
        status: filter,
        q: search,
      })
      setLeads(res.data.items || [])
      setTotal(res.data.total ?? 0)
      if (!silent) setSelected(new Set())
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to load leads from database.'
      setLoadError(detail)
      if (!silent) toast.error(detail)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [page, filter, search])

  // Fetch leads on filter/page/search change
  useEffect(() => {
    fetchLeads()
  }, [fetchLeads])

  // Fetch db stats on mount for quick counts
  useEffect(() => {
    getAuditStats()
      .then(r => setDbStats(r.data))
      .catch(() => {})
  }, [])

  // ── Debounced search input ──────────────────────────────────────────────
  function handleSearchInput(val) {
    setSearchInput(val)
    if (searchDebounce.current) clearTimeout(searchDebounce.current)
    searchDebounce.current = setTimeout(() => {
      setSearch(val)
      setPage(1)
      const nextParams = new URLSearchParams(searchParams)
      if (val.trim()) nextParams.set('q', val.trim())
      else nextParams.delete('q')
      setSearchParams(nextParams, { replace: true })
    }, 350)
  }

  function clearSearch() {
    setSearchInput('')
    setSearch('')
    setPage(1)
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('q')
    setSearchParams(nextParams, { replace: true })
  }

  function handleFilterChange(newFilter) {
    setFilter(newFilter)
    setPage(1)
    const nextParams = new URLSearchParams(searchParams)
    if (newFilter) nextParams.set('status', newFilter)
    else nextParams.delete('status')
    setSearchParams(nextParams, { replace: true })
  }

  // ── Stats-based Audit All polling (immune to batch gaps) ────────────────
  useEffect(() => {
    if (!auditProgress) {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }

    pollRef.current = setInterval(async () => {
      try {
        const s = await getAuditStats()
        const stats = s.data
        setDbStats(stats)
        fetchLeads(true)

        const auditingNow = stats.auditing ?? 0
        const doneNow = (stats.audited ?? 0) + (stats.emailed ?? 0) + (stats.replied ?? 0)
        const batchRunning = stats.batch_running ?? true

        setAuditProgress(prev => {
          if (!prev) return null
          const updated = { ...prev, done_now: doneNow, auditing_now: auditingNow }

          if (!batchRunning && auditingNow === 0 && doneNow > (prev.done_baseline ?? 0)) {
            clearInterval(pollRef.current)
            const gained = doneNow - (prev.done_baseline ?? 0)
            setTimeout(() => {
              setAuditDoneModal({ visible: true, count: prev.triggered ?? gained })
            }, 0)
            return null
          }
          return updated
        })
      } catch {
        // Ignore transient poll network errors
      }
    }, 6000)

    return () => clearInterval(pollRef.current)
  }, [auditProgress, fetchLeads])

  // ── ID-based single/bulk audit polling ──────────────────────────────────
  useEffect(() => {
    if (pendingAuditIds.size === 0) {
      if (singlePollRef.current) clearInterval(singlePollRef.current)
      return
    }

    singlePollRef.current = setInterval(async () => {
      try {
        const res = await getLeads({ page: 1, page_size: 200, status: 'auditing' })
        const auditingIds = new Set((res.data.items || []).map(l => l.id))
        const stillGoing = new Set([...pendingAuditIds].filter(id => auditingIds.has(id)))
        fetchLeads(true)

        if (stillGoing.size === 0) {
          clearInterval(singlePollRef.current)
          const doneCount = pendingAuditIds.size
          setPendingAuditIds(new Set())
          setAuditDoneModal({ visible: true, count: doneCount })
        } else {
          setPendingAuditIds(stillGoing)
        }
      } catch {
        // Ignore transient errors
      }
    }, 10000)

    return () => clearInterval(singlePollRef.current)
  }, [pendingAuditIds, fetchLeads])

  function handleAuditDoneOk() {
    setAuditDoneModal({ visible: false, count: 0 })
    fetchLeads()
  }

  // ── Checkbox helpers ────────────────────────────────────────────────────
  const allSelected = leads.length > 0 && selected.size === leads.length
  const someSelected = selected.size > 0 && !allSelected

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(leads.map(l => l.id)))
  }

  function toggleOne(id) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── CSV Dropzone ────────────────────────────────────────────────────────
  const onDrop = useCallback(
    async files => {
      if (!files[0]) return
      const fd = new FormData()
      fd.append('file', files[0])
      const t = toast.loading(`Uploading ${files[0].name}…`)
      try {
        const res = await uploadLeads(fd)
        toast.success(
          `Imported ${res.data.imported} leads. Skipped ${res.data.skipped_duplicates} duplicates.`,
          { id: t }
        )
        fetchLeads()
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Upload failed', { id: t })
      }
    },
    [fetchLeads]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/csv': ['.csv'] },
    multiple: false,
  })

  // ── Single & Bulk Actions ───────────────────────────────────────────────
  async function handleDelete(id) {
    if (!confirm('Delete this lead and all associated audit data?')) return
    try {
      await deleteLead(id)
      toast.success('Lead deleted successfully')
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete failed')
    }
  }

  async function handleBulkDelete() {
    const ids = Array.from(selected)
    if (!confirm(`Delete ${ids.length} selected lead(s) and their audit data?`)) return
    const t = toast.loading(`Deleting ${ids.length} leads…`)
    try {
      const res = await bulkDeleteLeads(ids)
      toast.success(`Deleted ${res.data.deleted} leads`, { id: t })
      setSelected(new Set())
      fetchLeads()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Bulk delete failed', { id: t })
    }
  }

  async function handleBulkAudit() {
    const ids = Array.from(selected)
    const t = toast.loading(`Triggering audits for ${ids.length} leads…`)
    const started = new Set()
    try {
      for (const id of ids) {
        try {
          await triggerAudit(id)
          started.add(id)
        } catch {
          // Continue with rest
        }
      }
      toast.success(`${started.size} audits started — you'll be notified when complete`, { id: t })
      setSelected(new Set())
      fetchLeads()
      if (started.size > 0) setPendingAuditIds(started)
    } catch {
      toast.error('Failed to trigger bulk audits', { id: t })
    }
  }

  async function handleAudit(id) {
    const t = toast.loading('Initiating audit crawler…')
    try {
      await triggerAudit(id)
      toast.success('Audit started in background — notified when complete', { id: t })
      fetchLeads()
      setPendingAuditIds(prev => new Set([...prev, id]))
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Audit trigger failed', { id: t })
    }
  }

  async function handleAuditAll() {
    try {
      const s = await getAuditStats()
      setDbStats(s.data)
      if (s.data.batch_running) {
        toast.error('A batch audit is already running. Please wait for it to complete.')
        return
      }
    } catch {
      // Show modal even if stats check had an issue
    }
    setAuditModeModal(true)
  }

  async function runAuditMode(mode) {
    setAuditModeModal(false)
    const labels = {
      new_only: 'Auditing new sites…',
      not_emailed: 'Re-auditing all not-emailed leads…',
      force_all: 'Re-auditing everything…',
      skipped: 'Re-auditing skipped sites…',
    }
    const t = toast.loading(labels[mode] ?? 'Triggering audits…')

    try {
      const snapRes = await getAuditStats()
      const snap = snapRes.data
      const baselineDone = (snap.audited ?? 0) + (snap.emailed ?? 0) + (snap.replied ?? 0)

      let res
      if (mode === 'skipped') res = await triggerSkippedAudits()
      else res = await triggerAllAudits(mode)

      const triggered = res.data.triggered ?? 0

      if (triggered === 0) {
        toast.success('No leads matched — nothing to audit.', { id: t })
        return
      }

      toast.success(`✓ ${triggered.toLocaleString()} audits queued in background`, {
        id: t,
        duration: 5000,
      })

      setAuditProgress({
        triggered,
        mode,
        done_baseline: baselineDone,
        done_now: baselineDone,
        auditing_now: triggered,
      })

      fetchLeads()
    } catch (err) {
      const detail = err?.response?.data?.detail
      toast.error(detail || 'Failed to queue batch audits', { id: t })
    }
  }

  // ── Column Sorting (Client-side on current page) ────────────────────────
  function toggleSort(field) {
    if (sortField === field) {
      setSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortOrder('asc')
    }
  }

  const sortedLeads = useMemo(() => {
    if (!sortField) return leads

    return [...leads].sort((a, b) => {
      let aVal = a[sortField] ?? ''
      let bVal = b[sortField] ?? ''

      if (sortField === 'created_at') {
        aVal = new Date(aVal).getTime() || 0
        bVal = new Date(bVal).getTime() || 0
      } else if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase()
        bVal = bVal.toLowerCase()
      }

      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1
      return 0
    })
  }, [leads, sortField, sortOrder])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* ── Modals ── */}
      {auditModeModal && (
        <AuditModeModal
          stats={dbStats}
          onSelect={runAuditMode}
          onClose={() => setAuditModeModal(false)}
        />
      )}

      {auditDoneModal.visible && (
        <AuditDoneModal count={auditDoneModal.count} onOk={handleAuditDoneOk} />
      )}

      {editLead && (
        <EditLeadModal
          lead={editLead}
          onSaved={() => fetchLeads(true)}
          onClose={() => setEditLead(null)}
        />
      )}

      {/* ── Top Header & Actions ── */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-slate-800/80 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Leads Workspace
            </h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-950/40 text-blue-300 border border-blue-800/50">
              {total.toLocaleString()} Accounts
            </span>
          </div>
          <p className="text-slate-400 text-sm mt-1">
            Search, filter, audit, and inspect prospective accounts with deliverability safety.
          </p>
        </div>

        {/* Global Action Bar */}
        <div className="flex items-center gap-2 flex-wrap w-full sm:w-auto">
          {/* Real-time batch progress indicator */}
          {auditProgress && (() => {
            const triggered = auditProgress.triggered ?? 1
            const baselineDone = auditProgress.done_baseline ?? 0
            const currentDone = auditProgress.done_now ?? baselineDone
            const gained = Math.max(0, currentDone - baselineDone)
            const pct = Math.min(100, Math.max(2, (gained / triggered) * 100))
            const remaining = auditProgress.auditing_now ?? (triggered - gained)

            return (
              <div className="p-2 px-3 rounded-lg bg-amber-950/30 border border-amber-800/50 text-amber-300 text-xs min-w-[220px]">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-bold flex items-center gap-1.5">
                    <span className="spinner w-3 h-3 border-amber-400 border-t-transparent" />
                    Crawling…
                  </span>
                  <span className="text-[11px] font-mono">
                    {gained} / {triggered}
                  </span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-amber-400 to-amber-500 rounded-full transition-all duration-700"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            )
          })()}

          {!auditProgress && pendingAuditIds.size > 0 && (
            <div className="p-2 px-3 rounded-lg bg-amber-950/30 border border-amber-800/50 text-amber-300 text-xs flex items-center gap-2">
              <span className="spinner w-3 h-3 border-amber-400 border-t-transparent" />
              <span>{pendingAuditIds.size} auditing…</span>
            </div>
          )}

          <button
            onClick={() => fetchLeads()}
            className="btn-secondary text-xs py-2 px-3 font-semibold"
            title="Refresh current page"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>

          <button
            onClick={handleAuditAll}
            disabled={!!dbStats?.batch_running}
            className="btn-primary text-xs py-2 px-3.5 font-bold flex items-center gap-1.5 shadow-lg shadow-blue-900/30"
            title={dbStats?.batch_running ? 'Batch crawler active…' : 'Start batch audit'}
          >
            <PlayCircle size={14} />
            <span>Audit All</span>
          </button>

          <button
            onClick={openQualityReview}
            className="btn-secondary text-xs py-2 px-3 font-semibold flex items-center gap-1.5"
            title="Review quarantined and unresolved lead evidence"
          >
            <ShieldAlert size={14} />
            <span>Review quality</span>
          </button>

        </div>
      </div>

      {/* ── Bulk Import & Discovery ── */}
      <BulkImportDiscovery onLeadsImported={() => fetchLeads()} />

      {qualityReviewOpen && (
        <LeadQualityReviewPanel
          records={qualityRecords}
          total={qualityTotal}
          page={qualityPage}
          pageSize={qualityPageSize}
          counts={qualityCounts}
          searchQuery={qualitySearch}
          onSearchChange={handleQualitySearch}
          loading={qualityReviewLoading}
          onRetry={retryQualityDiscovery}
          onKeepUnderReview={keepQualityUnderReview}
          onDeleteOne={handleQualityDeleteOne}
          onBulkDelete={handleQualityBulkDelete}
          onPageChange={(targetPage) => openQualityReview(targetPage, qualitySearch)}
          onClose={() => setQualityReviewOpen(false)}
        />
      )}

      {/* ── CSV Dropzone ── */}
      <div
        {...getRootProps()}
        className={`card-elevated p-6 text-center cursor-pointer border-2 border-dashed transition-all duration-200 ${
          isDragActive
            ? 'border-blue-500 bg-blue-950/20 shadow-lg shadow-blue-900/20'
            : 'border-slate-800 hover:border-slate-600 bg-slate-900/40 hover:bg-slate-900/60'
        }`}
      >
        <input {...getInputProps()} />
        <Upload size={24} className="mx-auto mb-2 text-slate-400" />
        {isDragActive ? (
          <p className="text-xs font-bold text-blue-400">
            Release your CSV file to import…
          </p>
        ) : (
          <div>
            <p className="text-xs font-bold text-slate-200">
              Drag &amp; drop a leads.csv file here, or click to browse
            </p>
            <p className="text-[11px] text-slate-500 mt-1 font-mono">
              Expected columns: business_name, email, phone, website
            </p>
          </div>
        )}
      </div>

      {/* ── Error Banner if fetch failed ── */}
      {loadError && (
        <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-800/40 flex items-center justify-between gap-3 text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-rose-400 shrink-0" />
            <span>{loadError}</span>
          </div>
          <button
            onClick={() => fetchLeads()}
            className="btn-secondary text-xs py-1 px-3 font-bold text-rose-300 hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Search, Filters, and Tabs ── */}
      <div className="space-y-3">
        {/* Quick Filter Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
          {[
            { id: '', label: 'All Leads' },
            { id: 'new', label: 'New Intake' },
            { id: 'auditing', label: 'Auditing' },
            { id: 'audited', label: 'Audited' },
            { id: 'emailed', label: 'Emailed' },
            { id: 'replied', label: 'Replied' },
            { id: 'quarantined', label: 'Quarantined / Safety Hold' },
            { id: 'skipped', label: 'Skipped Sites' },
          ].map(tab => {
            const isActive = filter === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => handleFilterChange(tab.id)}
                className={`tab-pill whitespace-nowrap text-xs ${
                  isActive ? 'tab-pill-active' : ''
                }`}
              >
                {tab.label}
              </button>
            )
          })}
        </div>

        {/* Search input + Dropdown */}
        <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
          {/* Search box */}
          <div className="relative flex-1">
            <Search
              size={14}
              className={`absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none transition-colors ${
                searchInput ? 'text-blue-400' : 'text-slate-500'
              }`}
            />
            <input
              type="text"
              value={searchInput}
              onChange={e => handleSearchInput(e.target.value)}
              placeholder="Search by business name, email, or domain…"
              className="input pl-9 pr-8 text-xs"
            />
            {searchInput && (
              <button
                onClick={clearSearch}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                title="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Status selector dropdown */}
          <div className="relative sm:w-56 shrink-0">
            <Filter size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
            <select
              value={filter}
              onChange={e => handleFilterChange(e.target.value)}
              className="input pl-8 pr-8 text-xs appearance-none cursor-pointer"
            >
              <option value="">All Statuses</option>
              <option value="new">New (Unaudited)</option>
              <option value="auditing">Auditing In Progress</option>
              <option value="audited">Audited (Complete)</option>
              <option value="emailed">Emailed Outreach</option>
              <option value="replied">Replied Contacts</option>
              <option value="quarantined">Quarantined / Excluded</option>
              <option value="skipped">Skipped (Offline / Errors)</option>
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
          </div>
        </div>

        {/* Search / Filter result count */}
        {(search || filter) && (
          <div className="flex items-center gap-2 text-xs text-slate-400 pt-1">
            <span>
              Found <strong className="text-slate-200">{total.toLocaleString()}</strong> result{total !== 1 ? 's' : ''}
            </span>
            {search && (
              <span>
                for query <span className="text-blue-400 font-mono">"{search}"</span>
              </span>
            )}
            {filter && (
              <span>
                under status <span className="text-amber-400 font-mono">"{filter}"</span>
              </span>
            )}
            <button
              onClick={() => {
                clearSearch()
                handleFilterChange('')
              }}
              className="text-blue-400 hover:underline font-semibold ml-1"
            >
              Reset All
            </button>
          </div>
        )}
      </div>

      {/* ── Bulk Action Floating Bar ── */}
      {selected.size > 0 && (
        <div className="p-3.5 rounded-xl bg-blue-950/40 border border-blue-500/40 flex items-center justify-between gap-3 flex-wrap animate-in fade-in duration-150">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
            <span className="text-xs font-bold text-blue-200">
              {selected.size} lead{selected.size > 1 ? 's' : ''} selected
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleBulkAudit}
              className="btn-primary text-xs py-1.5 px-3 font-semibold flex items-center gap-1.5"
            >
              <Search size={13} />
              <span>Audit Selected</span>
            </button>
            <button
              onClick={handleBulkDelete}
              className="btn-danger text-xs py-1.5 px-3 font-semibold flex items-center gap-1.5"
            >
              <Trash2 size={13} />
              <span>Delete Selected</span>
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="btn-secondary text-xs py-1.5 px-2.5 font-semibold text-slate-400"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {/* ── Mobile Card View (< 768px) ── */}
      <div className="block md:hidden space-y-3">
        {loading ? (
          <LeadTableSkeleton rows={4} />
        ) : sortedLeads.length === 0 ? (
          <div className="card-elevated">
            <LeadEmptyState
              isFiltered={Boolean(search || filter)}
              onResetFilters={() => {
                clearSearch()
                handleFilterChange('')
              }}
            />
          </div>
        ) : (
          sortedLeads.map(lead => (
            <LeadRowMobileCard
              key={lead.id}
              lead={lead}
              isSelected={selected.has(lead.id)}
              onToggleSelect={toggleOne}
              onEdit={setEditLead}
              onAudit={handleAudit}
              onDelete={handleDelete}
              isAuditing={lead.status === 'auditing'}
            />
          ))
        )}
      </div>

      {/* ── Desktop Leads Table (>= 768px) ── */}
      <div className="hidden md:block card-elevated p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/60 text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                <th className="py-3 px-4 w-10">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={el => {
                      if (el) el.indeterminate = someSelected
                    }}
                    onChange={toggleAll}
                    className="w-4 h-4 rounded accent-blue-600 cursor-pointer"
                    title="Select all on current page"
                  />
                </th>

                <th
                  onClick={() => toggleSort('business_name')}
                  className="py-3 px-4 cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Business</span>
                    <ArrowUpDown size={11} className={sortField === 'business_name' ? 'text-blue-400' : 'opacity-40'} />
                  </div>
                </th>

                <th
                  onClick={() => toggleSort('email')}
                  className="py-3 px-4 cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Email &amp; Deliverability</span>
                    <ArrowUpDown size={11} className={sortField === 'email' ? 'text-blue-400' : 'opacity-40'} />
                  </div>
                </th>

                <th
                  onClick={() => toggleSort('website')}
                  className="py-3 px-4 cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Website</span>
                    <ArrowUpDown size={11} className={sortField === 'website' ? 'text-blue-400' : 'opacity-40'} />
                  </div>
                </th>

                <th
                  onClick={() => toggleSort('status')}
                  className="py-3 px-4 cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Status</span>
                    <ArrowUpDown size={11} className={sortField === 'status' ? 'text-blue-400' : 'opacity-40'} />
                  </div>
                </th>

                <th
                  onClick={() => toggleSort('created_at')}
                  className="py-3 px-4 cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Added</span>
                    <ArrowUpDown size={11} className={sortField === 'created_at' ? 'text-blue-400' : 'opacity-40'} />
                  </div>
                </th>

                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-800/80 text-xs">
              {loading ? (
                <tr>
                  <td colSpan={7} className="p-0">
                    <LeadTableSkeleton rows={6} />
                  </td>
                </tr>
              ) : sortedLeads.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <LeadEmptyState
                      isFiltered={Boolean(search || filter)}
                      onResetFilters={() => {
                        clearSearch()
                        handleFilterChange('')
                      }}
                    />
                  </td>
                </tr>
              ) : (
                sortedLeads.map(lead => {
                  const isSelected = selected.has(lead.id)
                  const isAuditing = lead.status === 'auditing'
                  const looksScraped =
                    lead.business_name.includes('|') ||
                    lead.business_name.includes(' - ') ||
                    lead.business_name.length > 60

                  return (
                    <tr
                      key={lead.id}
                      className={`hover:bg-slate-800/40 transition-colors ${
                        isSelected ? 'bg-blue-950/20' : ''
                      }`}
                    >
                      {/* Checkbox */}
                      <td className="py-3 px-4">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleOne(lead.id)}
                          className="w-4 h-4 rounded accent-blue-600 cursor-pointer"
                        />
                      </td>

                      {/* Business Name */}
                      <td className="py-3 px-4 max-w-[220px]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span
                            className="font-bold text-slate-100 truncate max-w-[190px]"
                            title={lead.business_name}
                          >
                            {lead.business_name}
                          </span>
                          {looksScraped && (
                            <span
                              title="Name appears to contain tagline delimiters. Consider editing."
                              className="text-amber-400 text-xs cursor-help"
                            >
                              ⚠️
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Email & Deliverability */}
                      <td className="py-3 px-4">
                        <div className="space-y-1">
                          <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-300">
                            <span>{lead.email}</span>
                          </div>
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <VerificationBadge
                              status={lead.email_verification_status}
                              isQuarantined={lead.is_quarantined}
                              quarantineReason={lead.quarantine_reason}
                            />
                            <AssociationBadge status={lead.email_business_association_status} />
                          </div>
                        </div>
                      </td>

                      {/* Website */}
                      <td className="py-3 px-4">
                        {lead.website ? (
                          <div className="space-y-1">
                            <a
                              href={lead.website}
                              target="_blank"
                              rel="noreferrer"
                              className="text-blue-400 hover:text-blue-300 font-mono text-[11px] inline-flex items-center gap-1 truncate max-w-[170px]"
                              title={lead.website}
                            >
                              <Globe size={11} className="shrink-0" />
                              {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                            </a>
                            <div>
                              <WebsiteStatusBadge
                                status={lead.website_association_status}
                                candidates={lead.website_candidates}
                              />
                            </div>
                          </div>
                        ) : (
                          <span className="text-slate-500 italic text-[11px]">No website URL</span>
                        )}
                      </td>

                      {/* Status & Skipped Details */}
                      <td className="py-3 px-4">
                        <div className="space-y-1">
                          <LifecycleBadge
                            status={lead.status}
                            lastEmailedAt={lead.last_emailed_at}
                            isAuditing={isAuditing}
                          />
                          {lead.audit_error?.startsWith('SITE_STATUS:') && (
                            <div>
                              <SkippedReasonBadge auditError={lead.audit_error} />
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Added Date */}
                      <td className="py-3 px-4 text-slate-500 text-[11px]">
                        {new Date(lead.created_at).toLocaleDateString()}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => setEditLead(lead)}
                            className="p-1.5 text-slate-400 hover:text-white rounded hover:bg-slate-800 transition-colors"
                            title="Edit lead"
                          >
                            <Pencil size={13} />
                          </button>

                          <button
                            onClick={() => handleAudit(lead.id)}
                            disabled={isAuditing}
                            className="p-1.5 text-blue-400 hover:text-blue-300 rounded hover:bg-blue-950/40 transition-colors disabled:opacity-40"
                            title="Run 62-factor SEO audit"
                          >
                            <Search size={13} />
                          </button>

                          {lead.status === 'audited' && (
                            <Link
                              to="/audits"
                              className="p-1.5 text-emerald-400 hover:text-emerald-300 rounded hover:bg-emerald-950/40 transition-colors"
                              title="Inspect full audit findings"
                            >
                              <ArrowRight size={13} />
                            </Link>
                          )}

                          <button
                            onClick={() => handleDelete(lead.id)}
                            className="p-1.5 text-rose-400 hover:text-rose-300 rounded hover:bg-rose-950/40 transition-colors"
                            title="Delete lead"
                          >
                            <Trash2 size={13} />
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

      {/* ── Pagination ── */}
      {total > pageSize && (
        <div className="flex flex-col sm:flex-row justify-between items-center gap-3 pt-2 text-xs text-slate-400">
          <p>
            Showing {(page - 1) * pageSize + 1}–
            {Math.min(page * pageSize, total)} of {total.toLocaleString()} leads
          </p>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-secondary text-xs py-1.5 px-3 font-semibold disabled:opacity-40"
            >
              Previous
            </button>
            <span className="px-2 font-mono text-slate-300">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="btn-secondary text-xs py-1.5 px-3 font-semibold disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
