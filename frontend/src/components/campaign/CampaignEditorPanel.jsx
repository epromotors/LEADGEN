import React, { useState, useEffect, useMemo } from 'react'
import {
  Plus, X, Eye, Sparkles, Filter, Users, ShieldCheck,
  ShieldAlert, AlertTriangle, CheckCircle2, ChevronRight,
  Globe, Mail, Info, Clock, AlertCircle, RefreshCw
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  createCampaign,
  previewCampaignEmail,
  checkCampaignAudience,
  refreshCampaignAudit,
} from '../../api/client'

const PUBLIC_EMAIL_DOMAINS = new Set([
  'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.in', 'yahoo.co.uk',
  'hotmail.com', 'outlook.com', 'live.com', 'msn.com', 'icloud.com', 'me.com',
  'mac.com', 'aol.com', 'zoho.com', 'mail.com', 'gmx.com', 'proton.me', 'protonmail.com',
  'yandex.com', 'rediffmail.com',
])

function extractDomain(email) {
  if (!email || !email.includes('@')) return ''
  return email.split('@')[1].trim().toLowerCase()
}

function inCooldown(isoStr) {
  if (!isoStr) return false
  return (Date.now() - new Date(isoStr).getTime()) < 7 * 24 * 3600 * 1000
}

function evaluateEligibility(lead, campaignType, backendDetail = null) {
  const ver = (lead.email_verification_status || 'unverified').toLowerCase()
  const assoc = (lead.email_business_association_status || 'unverified').toLowerCase()
  const emailDomain = extractDomain(lead.email)
  const isPublicProvider = PUBLIC_EMAIL_DOMAINS.has(emailDomain)
  const hasWebsite = Boolean(lead.website && lead.website.trim())
  const auditStatus = (lead.audit_status || 'pending').toLowerCase()

  // 1. Email Verification status
  let emailVerification = {
    status: ver,
    label: 'Pending Verification',
    color: '#fbbf24',
    bg: 'rgba(251,191,36,0.12)',
    border: 'rgba(251,191,36,0.3)',
  }
  if (ver === 'valid') {
    emailVerification = {
      status: 'valid',
      label: 'Deliverable (MX Valid)',
      color: '#34d399',
      bg: 'rgba(16,185,129,0.12)',
      border: 'rgba(16,185,129,0.3)',
    }
  } else if (ver === 'disposable' || ver === 'invalid') {
    emailVerification = {
      status: ver,
      label: ver === 'disposable' ? 'Disposable Email' : 'Invalid MX',
      color: '#f87171',
      bg: 'rgba(239,68,68,0.12)',
      border: 'rgba(239,68,68,0.3)',
    }
  }

  // 2. Association status
  let association = {
    status: assoc,
    label: 'Assoc Review',
    color: '#fb923c',
    bg: 'rgba(251,146,60,0.12)',
    border: 'rgba(251,146,60,0.3)',
  }
  if (assoc === 'matched') {
    association = {
      status: 'matched',
      label: 'Matched Domain',
      color: '#60a5fa',
      bg: 'rgba(59,130,246,0.12)',
      border: 'rgba(59,130,246,0.3)',
    }
  } else if (assoc === 'approved') {
    association = {
      status: 'approved',
      label: 'Approved Association',
      color: '#38bdf8',
      bg: 'rgba(56,189,248,0.12)',
      border: 'rgba(56,189,248,0.3)',
    }
  }

  // 3. Website / Audit status
  let websiteStatus = {
    status: 'no_website',
    label: 'No Website',
    color: '#94a3b8',
    bg: 'rgba(148,163,184,0.10)',
    border: 'rgba(148,163,184,0.25)',
  }
  if (hasWebsite) {
    if (auditStatus === 'done') {
      websiteStatus = {
        status: 'audit_done',
        label: 'Audit Complete',
        color: '#34d399',
        bg: 'rgba(16,185,129,0.12)',
        border: 'rgba(16,185,129,0.3)',
      }
    } else {
      websiteStatus = {
        status: 'audit_needed',
        label: 'Audit Required',
        color: '#fb923c',
        bg: 'rgba(251,146,60,0.12)',
        border: 'rgba(251,146,60,0.3)',
      }
    }
  }

  // If backend authoritative breakdown is provided
  if (backendDetail && typeof backendDetail.is_eligible === 'boolean') {
    const isEligible = backendDetail.is_eligible
    const reason = backendDetail.exclusion_reason || ''
    let badge = '✦ Ready'
    let color = '#4ade80'

    if (!isEligible) {
      if (backendDetail.audit_freshness === 'stale' || reason.toLowerCase().includes('stale')) {
        badge = 'Audit Stale'
        color = '#f97316'
      } else if (backendDetail.audit_freshness === 'refresh_in_progress' || reason.toLowerCase().includes('refresh is in progress')) {
        badge = 'Audit Refreshing'
        color = '#38bdf8'
      } else if (reason.toLowerCase().includes('proposal') || reason.toLowerCase().includes('approval required')) {
        badge = 'Proposal Required'
        color = '#c084fc'
      } else if (reason.toLowerCase().includes('audit')) {
        badge = 'Audit Required'
        color = '#fb923c'
      } else if (reason.toLowerCase().includes('quarantined')) {
        badge = 'Quarantined'
        color = '#f87171'
      } else if (reason.toLowerCase().includes('cooldown')) {
        badge = 'Cooldown'
        color = '#fca5a5'
      } else if (reason.toLowerCase().includes('unverified') || reason.toLowerCase().includes('pending')) {
        badge = 'Pending Verify'
        color = '#facc15'
      } else if (reason.toLowerCase().includes('association') || reason.toLowerCase().includes('assoc')) {
        badge = 'Assoc Review'
        color = '#fb923c'
      } else {
        badge = 'Ineligible'
        color = '#f87171'
      }
    } else if (campaignType === 'public_provider_demo') {
      badge = '✦ Demo Ready'
      color = '#38bdf8'
    }

    return {
      eligible: isEligible,
      reason: reason || (isEligible ? `Eligible for outreach` : 'Ineligible'),
      badge,
      color,
      emailVerification,
      association,
      websiteStatus,
      auditFreshness: backendDetail.audit_freshness,
      auditAgeDays: backendDetail.audit_age_days,
    }
  }

  // Client-side fallback checks
  if (!lead.email || !lead.email.trim()) {
    return {
      eligible: false,
      reason: 'Missing email address',
      badge: 'No Email',
      color: '#64748b',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  const isDemoCampaign = campaignType === 'public_provider_demo'

  if (ver === 'invalid' || ver === 'disposable') {
    return {
      eligible: false,
      reason: `Email is ${ver}`,
      badge: 'Invalid MX',
      color: '#f87171',
      emailVerification,
      association,
      websiteStatus,
    }
  }
  if (ver !== 'valid') {
    return {
      eligible: false,
      reason: 'Email verification pending (Deliverability check required)',
      badge: 'Pending Verify',
      color: '#fb923c',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  if (assoc === 'mismatched_source' || assoc === 'invalid_format') {
    return {
      eligible: false,
      reason: `Association excluded: ${assoc}`,
      badge: 'Assoc Blocked',
      color: '#f87171',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  if (lead.is_quarantined) {
    return {
      eligible: false,
      reason: `Quarantined: ${lead.quarantine_reason || 'Safety exclusion'}`,
      badge: 'Quarantined',
      color: '#f87171',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  if (isDemoCampaign) {
    if (!isPublicProvider) {
      return {
        eligible: false,
        reason: 'Only public-provider emails (Gmail, Yahoo, Outlook) use the demo outreach route',
        badge: 'Custom Domain',
        color: '#64748b',
        emailVerification,
        association,
        websiteStatus,
      }
    }
    return {
      eligible: true,
      reason: 'Eligible for Public Provider Demo Outreach',
      badge: '✦ Demo Ready',
      color: '#38bdf8',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  if (assoc !== 'matched' && assoc !== 'approved') {
    return {
      eligible: false,
      reason: `Association is ${assoc} (matched/approved required)`,
      badge: 'Assoc Review',
      color: '#fb923c',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  if (lead.last_emailed_at && inCooldown(lead.last_emailed_at)) {
    return {
      eligible: false,
      reason: 'In 7-day recipient cooldown',
      badge: 'Cooldown',
      color: '#fca5a5',
      emailVerification,
      association,
      websiteStatus,
    }
  }

  const auditRequired = campaignType !== 'no_website_design' && campaignType !== 'generic_first_contact'
  if (auditRequired) {
    if (!hasWebsite) {
      return {
        eligible: false,
        reason: 'Website required for audit-specific outreach',
        badge: 'No Website',
        color: '#64748b',
        emailVerification,
        association,
        websiteStatus,
      }
    }
    if (auditStatus !== 'done') {
      return {
        eligible: false,
        reason: `Audit evidence required (status: ${auditStatus})`,
        badge: 'Audit Required',
        color: '#fb923c',
        emailVerification,
        association,
        websiteStatus,
      }
    }
  }

  return {
    eligible: true,
    reason: 'Eligible for outreach',
    badge: '✦ Ready',
    color: '#4ade80',
    emailVerification,
    association,
    websiteStatus,
  }
}

export default function CampaignEditorPanel({
  leads = [],
  segments = {},
  onClose,
  onCreate,
}) {
  const segmentKeys = Object.keys(segments)
  const defaultSegment = segmentKeys[0] || 'generic_first_contact'

  const [selectedSegment, setSelectedSegment] = useState(defaultSegment)
  const [name, setName] = useState('')
  const [template, setTemplate] = useState(segments[defaultSegment]?.template || '')
  const [subjectTemplate, setSubjectTemplate] = useState(segments[defaultSegment]?.subject || '')
  const [selectedLeadIds, setSelectedLeadIds] = useState([])
  const [leadFilter, setLeadFilter] = useState('all') // 'all' | 'eligible' | 'audit_needed' | 'demo_eligible' | 'excluded'
  const [leadSearch, setLeadSearch] = useState('')
  const [quickNum, setQuickNum] = useState('')
  const [saving, setSaving] = useState(false)
  const [backendAudience, setBackendAudience] = useState(null)
  const [previewLead, setPreviewLead] = useState(null)
  const [previewData, setPreviewData] = useState(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [activePreviewTab, setActivePreviewTab] = useState('html')
  const [refreshingLeads, setRefreshingLeads] = useState(new Set())
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  // When segment changes, sync template defaults
  const handleSegmentChange = (segId) => {
    setSelectedSegment(segId)
    const seg = segments[segId]
    if (seg) {
      setSubjectTemplate(seg.subject || seg.default_subject || '')
      setTemplate(seg.template || seg.default_template || '')
    }
  }

  // Load authoritative backend audience breakdown
  useEffect(() => {
    let active = true
    async function loadAudience() {
      if (!leads.length) return
      try {
        const res = await checkCampaignAudience({
          lead_ids: leads.map(l => l.id),
          campaign_type: selectedSegment,
        })
        if (active && res.data) {
          setBackendAudience(res.data)
        }
      } catch {
        // client-side evaluation fallback
      }
    }
    loadAudience()
    return () => { active = false }
  }, [leads, selectedSegment, refreshTrigger])

  const handleRefreshAudit = async (leadId, businessName) => {
    setRefreshingLeads(prev => new Set(prev).add(leadId))
    try {
      await refreshCampaignAudit(leadId)
      toast.success(`Audit refresh initiated for ${businessName || 'lead'}`)
      setTimeout(() => setRefreshTrigger(t => t + 1), 1000)
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'Refresh failed'
      toast.error(detail)
    } finally {
      setRefreshingLeads(prev => {
        const next = new Set(prev)
        next.delete(leadId)
        return next
      })
    }
  }

  // Compute eligibility map
  const eligibilityMap = useMemo(() => {
    const map = new Map()
    leads.forEach(l => {
      const bDetail = backendAudience?.lead_details?.[String(l.id)]
      map.set(l.id, evaluateEligibility(l, selectedSegment, bDetail))
    })
    return map
  }, [leads, selectedSegment, backendAudience])

  const eligibleLeads = useMemo(() => {
    return leads.filter(l => eligibilityMap.get(l.id)?.eligible)
  }, [leads, eligibilityMap])

  const auditNeededLeads = useMemo(() => {
    return leads.filter(l => {
      const el = eligibilityMap.get(l.id)
      return !el?.eligible && el?.badge === 'Audit Required'
    })
  }, [leads, eligibilityMap])

  const staleAuditLeads = useMemo(() => {
    return leads.filter(l => {
      const el = eligibilityMap.get(l.id)
      return !el?.eligible && el?.badge === 'Audit Stale'
    })
  }, [leads, eligibilityMap])

  const displayedLeads = useMemo(() => {
    return leads.filter(l => {
      const el = eligibilityMap.get(l.id)
      if (leadFilter === 'eligible' && !el?.eligible) return false
      if (leadFilter === 'audit_needed' && el?.badge !== 'Audit Required') return false
      if (leadFilter === 'stale_audit' && el?.badge !== 'Audit Stale') return false
      if (leadFilter === 'demo_eligible' && el?.badge !== '✦ Demo Ready') return false
      if (leadFilter === 'excluded' && el?.eligible) return false

      if (leadSearch.trim()) {
        const q = leadSearch.toLowerCase().trim()
        const matchName = (l.business_name || '').toLowerCase().includes(q)
        const matchEmail = (l.email || '').toLowerCase().includes(q)
        const matchWebsite = (l.website || '').toLowerCase().includes(q)
        if (!matchName && !matchEmail && !matchWebsite) return false
      }
      return true
    })
  }, [leads, eligibilityMap, leadFilter, leadSearch])

  // Select helpers
  const toggleLead = (id) => {
    setSelectedLeadIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const selectAllEligible = () => {
    setSelectedLeadIds(eligibleLeads.map(l => l.id))
  }

  const selectQuickEligible = (num) => {
    const slice = eligibleLeads.slice(0, num).map(l => l.id)
    setSelectedLeadIds(slice)
  }

  const clearSelection = () => {
    setSelectedLeadIds([])
  }

  // Insert variable tag into template
  const insertVariable = (varName) => {
    setTemplate(prev => `${prev} {${varName}}`)
  }

  // Live preview handler
  const handleOpenPreview = async (lead) => {
    setPreviewLead(lead)
    setLoadingPreview(true)
    setPreviewData(null)
    try {
      const res = await previewCampaignEmail({
        campaign_type: selectedSegment,
        template,
        subject_template: subjectTemplate,
        lead_id: lead.id,
      })
      setPreviewData(res.data)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Preview generation failed')
    } finally {
      setLoadingPreview(false)
    }
  }

  // Submit campaign creation
  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) {
      toast.error('Campaign name is required')
      return
    }
    if (selectedLeadIds.length === 0) {
      toast.error('Select at least one eligible lead for this campaign')
      return
    }

    setSaving(true)
    try {
      await createCampaign({
        name: name.trim(),
        lead_ids: selectedLeadIds,
        template,
        subject_template: subjectTemplate,
        campaign_type: selectedSegment,
      })
      toast.success(`Campaign "${name}" created with ${selectedLeadIds.length} leads!`)
      if (onCreate) onCreate()
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'Creation failed'
      toast.error(detail)
    } finally {
      setSaving(false)
    }
  }

  const curSegment = segments[selectedSegment] || {}

  return (
    <div className="card-elevated p-6 border border-slate-700/80 mb-8 animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-6">
        <div>
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <Plus size={18} className="text-blue-400" />
            Create Segmented Outreach Campaign
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Target verified leads with authoritative audit personalized templates
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1.5 text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-800 transition-colors"
        >
          <X size={18} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Step 1: Campaign Details & Strategy */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                Campaign Name
              </label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Dental Q4 SEO Outreach"
                className="input text-sm"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                Outreach Strategy / Segment
              </label>
              <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                {Object.entries(segments).map(([id, seg]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => handleSegmentChange(id)}
                    className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                      selectedSegment === id
                        ? 'bg-blue-600/20 border-blue-500/50 text-blue-200 shadow-sm'
                        : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                    }`}
                  >
                    <div className="font-semibold text-slate-200">{seg.name || id}</div>
                    <div className="text-[11px] text-slate-400 truncate mt-0.5">{seg.description}</div>
                    {seg.requires_audit && (
                      <span className="inline-block mt-1 text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.2 rounded border border-amber-500/20">
                        Requires Audit
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Audience Eligibility Breakdown Card */}
            <div className="p-3.5 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2">
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">
                Audience Eligibility Breakdown
              </span>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 bg-slate-950/60 rounded border border-slate-800">
                  <div className="text-slate-400 text-[10px]">Total Available</div>
                  <div className="text-base font-bold text-slate-100">{leads.length}</div>
                </div>
                <div className="p-2 bg-emerald-950/20 rounded border border-emerald-800/40">
                  <div className="text-emerald-400 text-[10px]">Segment Ready</div>
                  <div className="text-base font-bold text-emerald-300">{eligibleLeads.length}</div>
                </div>
              </div>
              {auditNeededLeads.length > 0 && curSegment.requires_audit && (
                <div className="text-[11px] text-amber-400/90 flex items-center gap-1.5">
                  <AlertCircle size={12} className="shrink-0" />
                  <span>{auditNeededLeads.length} leads require audit completion first</span>
                </div>
              )}
            </div>
          </div>

          {/* Step 2: Subject & Template Editor */}
          <div className="lg:col-span-2 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1.5">
                Subject Line Template
              </label>
              <input
                type="text"
                value={subjectTemplate}
                onChange={e => setSubjectTemplate(e.target.value)}
                placeholder="{business_name} — quick observation"
                className="input text-sm font-medium font-mono"
                required
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                  Outreach Body Template
                </label>
                <span className="text-[11px] text-slate-500">
                  Supports Spintax <code>{`{hi|hello|hey}`}</code> &amp; Dynamic Tags
                </span>
              </div>
              <textarea
                value={template}
                onChange={e => setTemplate(e.target.value)}
                rows={9}
                className="input text-xs font-mono leading-relaxed resize-y"
                required
              />
            </div>

            {/* Variable Pills */}
            <div className="space-y-1.5">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                Click to Insert Dynamic Tokens:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {[
                  'business_name',
                  'website',
                  'sender_name',
                  'company_name',
                  'company_website',
                  'audit_summary',
                  'audit_findings',
                  'audit_recommendations',
                  'opportunity_summary',
                  'proposal_summary',
                ].map(v => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => insertVariable(v)}
                    className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-900 hover:bg-slate-800 text-blue-300 border border-slate-700/80 transition-colors"
                  >
                    +{`{${v}}`}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Step 3: Audience Selector & Quick Filters */}
        <div className="pt-4 border-t border-slate-800 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
                <Users size={16} className="text-blue-400" />
                Select Outreach Recipients ({selectedLeadIds.length} of {eligibleLeads.length} eligible selected)
              </h3>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Quick Select Buttons */}
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Quick:</span>
              <button
                type="button"
                onClick={selectAllEligible}
                disabled={eligibleLeads.length === 0}
                className="text-xs px-2.5 py-1 rounded-md font-semibold bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/25 transition-colors disabled:opacity-40"
              >
                All Eligible ({eligibleLeads.length})
              </button>
              {[25, 50, 100].map(n => (
                <button
                  key={n}
                  type="button"
                  onClick={() => selectQuickEligible(n)}
                  disabled={eligibleLeads.length < 1}
                  className="text-xs px-2 py-1 rounded-md font-semibold bg-blue-500/15 border border-blue-500/30 text-blue-300 hover:bg-blue-500/25 transition-colors disabled:opacity-40"
                >
                  Top {n}
                </button>
              ))}
              {selectedLeadIds.length > 0 && (
                <button
                  type="button"
                  onClick={clearSelection}
                  className="text-xs px-2 py-1 text-slate-400 hover:text-slate-200"
                >
                  Clear ({selectedLeadIds.length})
                </button>
              )}
            </div>
          </div>

          {/* Filter Bar & Search */}
          <div className="flex flex-wrap items-center justify-between gap-3 p-2 bg-slate-900/60 border border-slate-800 rounded-lg">
            <div className="flex items-center gap-1.5 flex-wrap">
              {[
                { id: 'all', label: `All (${leads.length})` },
                { id: 'eligible', label: `Eligible (${eligibleLeads.length})`, color: 'text-emerald-400' },
                { id: 'audit_needed', label: `Needs Audit (${auditNeededLeads.length})`, color: 'text-amber-400' },
                ...(staleAuditLeads.length > 0 ? [{ id: 'stale_audit', label: `Stale Audits (${staleAuditLeads.length})`, color: 'text-orange-400' }] : []),
                { id: 'excluded', label: `Excluded (${leads.length - eligibleLeads.length})`, color: 'text-rose-400' },
              ].map(f => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setLeadFilter(f.id)}
                  className={`text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                    leadFilter === f.id
                      ? 'bg-blue-600/20 text-blue-300 border border-blue-500/40'
                      : 'text-slate-400 hover:text-slate-200 border border-transparent'
                  } ${f.color || ''}`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            <input
              type="text"
              placeholder="Search leads by name, email, domain…"
              value={leadSearch}
              onChange={e => setLeadSearch(e.target.value)}
              className="text-xs bg-slate-900 border border-slate-700/80 rounded-md px-3 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 w-64"
            />
          </div>

          {/* Lead Selection Table */}
          <div className="max-h-64 overflow-y-auto border border-slate-800 rounded-lg bg-slate-950/40 divide-y divide-slate-800/60">
            {displayedLeads.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-xs">
                No leads match the current filter or search criteria.
              </div>
            ) : (
              displayedLeads.map(l => {
                const el = eligibilityMap.get(l.id)
                const isSelected = selectedLeadIds.includes(l.id)
                const isEligible = el?.eligible

                return (
                  <div
                    key={l.id}
                    className={`p-2.5 px-3 flex items-center justify-between gap-3 text-xs transition-colors ${
                      isSelected ? 'bg-blue-950/20' : 'hover:bg-slate-900/40'
                    } ${!isEligible ? 'opacity-70' : ''}`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={!isEligible}
                        onChange={() => toggleLead(l.id)}
                        className="rounded border-slate-700 text-blue-600 focus:ring-0 focus:ring-offset-0 disabled:opacity-40"
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-200 truncate">{l.business_name}</span>
                          <span
                            className="text-[10px] font-bold px-1.5 py-0.2 rounded border"
                            style={{
                              backgroundColor: `${el?.color}18`,
                              color: el?.color,
                              borderColor: `${el?.color}35`,
                            }}
                          >
                            {el?.badge}
                          </span>
                        </div>
                        <div className="text-[11px] text-slate-400 flex items-center gap-2 mt-0.5 truncate">
                          <span>{l.email || 'No Email'}</span>
                          {l.website && <span className="text-slate-500">· {l.website}</span>}
                          {!isEligible && el?.reason && (
                            <span className="text-rose-400/90 text-[10px]">({el.reason})</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      {(el?.badge === 'Audit Stale' || el?.auditFreshness === 'stale') && (
                        <button
                          type="button"
                          disabled={refreshingLeads.has(l.id)}
                          onClick={() => handleRefreshAudit(l.id, l.business_name)}
                          className="text-xs text-orange-400 hover:text-orange-300 font-medium px-2 py-1 rounded bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 shrink-0 flex items-center gap-1 disabled:opacity-50"
                          title="Trigger bounded audit refresh"
                        >
                          <RefreshCw size={11} className={refreshingLeads.has(l.id) ? "animate-spin" : ""} />
                          {refreshingLeads.has(l.id) ? "Refreshing…" : "Refresh Audit"}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleOpenPreview(l)}
                        className="text-xs text-blue-400 hover:text-blue-300 font-medium px-2 py-1 rounded bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 shrink-0"
                      >
                        <Eye size={12} className="inline mr-1" />
                        Preview
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-800">
          <p className="text-xs text-slate-400">
            Selected <strong className="text-white">{selectedLeadIds.length} leads</strong> for cold outreach dispatch
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="btn-secondary text-xs py-2 px-4"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || selectedLeadIds.length === 0}
              className="btn-primary text-xs py-2 px-5 font-semibold"
            >
              {saving ? (
                <span className="flex items-center gap-1.5">
                  <span className="spinner w-3.5 h-3.5 border-white border-t-transparent" />
                  Creating Campaign…
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <Plus size={14} /> Create Campaign ({selectedLeadIds.length})
                </span>
              )}
            </button>
          </div>
        </div>
      </form>

      {/* Live Preview Modal */}
      {previewLead && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="card-elevated border border-slate-700/80 w-full max-w-2xl max-h-[85vh] p-6 shadow-2xl flex flex-col relative overflow-hidden">
            <button
              onClick={() => setPreviewLead(null)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white"
            >
              <X size={18} />
            </button>

            <div className="mb-4">
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Eye size={16} className="text-blue-400" />
                Authoritative Email Preview
              </h3>
              <p className="text-xs text-slate-400">
                Prospect: <strong className="text-white">{previewLead.business_name}</strong> ({previewLead.email})
              </p>
            </div>

            {loadingPreview ? (
              <div className="py-16 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
                <span className="spinner w-4 h-4 border-blue-400 border-t-transparent" />
                Rendering exact template with backend variable substitutions…
              </div>
            ) : previewData ? (
              <div className="space-y-4 flex-1 overflow-y-auto pr-1">
                <div className="p-2.5 bg-slate-900 border border-slate-800 rounded-lg text-xs">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block font-semibold">Subject:</span>
                  <div className="text-slate-100 font-semibold mt-0.5">{previewData.subject}</div>
                </div>

                <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
                  <button
                    type="button"
                    onClick={() => setActivePreviewTab('html')}
                    className={`text-xs px-3 py-1 rounded font-medium ${
                      activePreviewTab === 'html'
                        ? 'bg-blue-600/20 text-blue-300 border border-blue-500/40'
                        : 'text-slate-400'
                    }`}
                  >
                    HTML Body
                  </button>
                  <button
                    type="button"
                    onClick={() => setActivePreviewTab('plain')}
                    className={`text-xs px-3 py-1 rounded font-medium ${
                      activePreviewTab === 'plain'
                        ? 'bg-blue-600/20 text-blue-300 border border-blue-500/40'
                        : 'text-slate-400'
                    }`}
                  >
                    Plain Text
                  </button>
                </div>

                {activePreviewTab === 'html' ? (
                  <div
                    className="p-4 bg-white rounded-lg text-slate-900 text-xs min-h-[200px] overflow-auto max-h-64"
                    dangerouslySetInnerHTML={{ __html: previewData.html_body }}
                  />
                ) : (
                  <pre className="p-4 bg-slate-950 rounded-lg text-slate-300 text-xs font-mono leading-relaxed overflow-auto max-h-64 whitespace-pre-wrap">
                    {previewData.plain_body}
                  </pre>
                )}
              </div>
            ) : null}

            <div className="pt-4 border-t border-slate-800 flex justify-end mt-4">
              <button
                type="button"
                onClick={() => setPreviewLead(null)}
                className="btn-secondary text-xs py-1.5 px-4"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
