import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  Plus, RefreshCw, FlaskConical, X, AlertTriangle, CheckCircle2,
  Mail, Sparkles
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getCampaigns,
  getAllLeadsForPicker,
  getSenderStatus,
  getCampaignSegments,
  sendCampaign,
  pauseCampaign,
  resumeCampaign,
  resetCampaign,
  deleteCampaign,
  retryCampaignFailed,
  recalculateCampaign,
} from '../api/client'
import CampaignKpiCards from '../components/campaign/CampaignKpiCards'
import CampaignListTable from '../components/campaign/CampaignListTable'
import CampaignActionModal from '../components/campaign/CampaignActionModal'
import CampaignEditorPanel from '../components/campaign/CampaignEditorPanel'
import CampaignSkeleton from '../components/campaign/CampaignSkeleton'
import TestEmailModal from '../components/campaign/TestEmailModal'

const FALLBACK_SEGMENTS = {
  generic_first_contact: {
    name: 'Generic First Contact',
    description: 'Professional, neutral outreach discussing web presence and discoverability.',
    requires_audit: false,
    subject: '{business_name} — quick question regarding your web presence',
    template: `Hello {business_name},

I was looking at your business profile and wanted to reach out regarding your online presence and discoverability.

Our team helps local and regional businesses ensure their online touchpoints effectively capture prospective client enquiries.

Would you be open to a brief review of opportunities to strengthen your search visibility and customer conversion?

If you are interested, reply to this note and I can send over a quick summary.

Best regards,
{sender_name}
{company_name}`,
  },
  no_website_design: {
    name: 'No Website — Full Web Design Offer',
    description: 'Target businesses without an active website with a professional, mobile-friendly design offer.',
    requires_audit: false,
    subject: 'Website design & online presence for {business_name}',
    template: `Hello {business_name},

I noticed your business profile and saw that you don't currently have an active business website listed.

In today's market, having a dedicated, mobile-friendly website is one of the highest-leverage ways to build customer trust and capture inbound customer enquiries.

We specialize in clean, high-converting websites tailored specifically for businesses like yours, complete with:
• Fully responsive mobile-friendly layouts
• Clear service showcases and contact capture
• Direct WhatsApp and enquiry integration
• Foundational search engine discoverability

Would you be open to a brief consultation or a tailored mockup for {business_name}?

Best regards,
{sender_name}
{company_name}`,
  },
  valid_website_seo: {
    name: 'Valid Website — SEO & Discovery',
    description: 'Target verified websites on technical SEO, meta tags, and Google discoverability.',
    requires_audit: true,
    subject: 'Search visibility & technical SEO opportunities for {website}',
    template: `Hello {business_name},

I was reviewing the technical search foundations of {website} and identified a few specific technical SEO opportunities that could help improve your Google visibility.

{audit_findings}

{audit_recommendations}

We specialize in resolving core technical search bottlenecks to improve indexation, page authority, and qualified organic traffic.

Would you be open to reviewing these findings together on a quick call this week?

Best regards,
{sender_name}
{company_name}`,
  },
}

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([])
  const [leads, setLeads] = useState([])
  const [senderStatus, setSenderStatus] = useState(null)
  const [segments, setSegments] = useState(FALLBACK_SEGMENTS)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [partialError, setPartialError] = useState(null)

  // Modals & Panels state
  const [showEditor, setShowEditor] = useState(false)
  const [showTestModal, setShowTestModal] = useState(false)
  const [actionModal, setActionModal] = useState({
    isOpen: false,
    action: null,
    campaign: null,
    loading: false,
  })

  const pollRef = useRef(null)

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setPartialError(null)

    const [cRes, lRes, sRes, segRes] = await Promise.allSettled([
      getCampaigns(),
      getAllLeadsForPicker(),
      getSenderStatus(),
      getCampaignSegments(),
    ])

    const failed = []

    if (cRes.status === 'fulfilled') {
      setCampaigns(cRes.value.data || [])
    } else {
      failed.push('Campaigns')
    }

    if (lRes.status === 'fulfilled') {
      setLeads(lRes.value.data?.items || [])
    } else {
      failed.push('Prospect Leads')
    }

    if (sRes.status === 'fulfilled') {
      setSenderStatus(sRes.value.data)
    } else {
      failed.push('Sender Status')
    }

    if (segRes.status === 'fulfilled') {
      const rawList = Array.isArray(segRes.value.data)
        ? segRes.value.data
        : (segRes.value.data?.segments || [])
      if (rawList.length > 0) {
        const segMap = {}
        rawList.forEach(s => {
          segMap[s.id] = {
            name: s.name,
            description: s.description,
            subject: s.default_subject || s.subject,
            template: s.default_template || s.template,
            requires_audit: s.requires_audit,
          }
        })
        setSegments(segMap)
      }
    }

    if (failed.length > 0) {
      setPartialError(`Unable to reach: ${failed.join(', ')}. Remaining workspace data loaded.`)
    }

    setLoading(false)
    setRefreshing(false)
  }, [])

  useEffect(() => {
    loadData()
    pollRef.current = setInterval(() => loadData(true), 8000)
    return () => clearInterval(pollRef.current)
  }, [loadData])

  // Consequential action trigger (opens modal for send, reset, delete; executes immediately for pause, resume)
  const handleAction = async (action, campaign) => {
    if (action === 'pause') {
      try {
        await pauseCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" paused`)
        loadData(true)
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Pause failed')
      }
      return
    }

    if (action === 'resume') {
      try {
        await resumeCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" resumed`)
        loadData(true)
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Resume failed')
      }
      return
    }

    // Explicit confirmation modal for consequential operations (send, reset, delete)
    setActionModal({
      isOpen: true,
      action,
      campaign,
      loading: false,
    })
  }

  // Execute confirmed modal action
  const handleConfirmAction = async () => {
    const { action, campaign } = actionModal
    if (!campaign || !action) return

    setActionModal(prev => ({ ...prev, loading: true }))
    try {
      if (action === 'send') {
        await sendCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" launched successfully!`)
      } else if (action === 'reset') {
        await resetCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" reset to draft`)
      } else if (action === 'delete') {
        await deleteCampaign(campaign.id)
        toast.success(`Campaign "${campaign.name}" deleted permanently`)
      }
      setActionModal({ isOpen: false, action: null, campaign: null, loading: false })
      loadData(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || `${action} failed`)
      setActionModal(prev => ({ ...prev, loading: false }))
    }
  }

  // Retry failed leads in a campaign
  const handleRetryFailed = async (campaign, silent = false) => {
    try {
      const res = await retryCampaignFailed(campaign.id)
      if (!silent) {
        toast.success(`↺ Queued ${res.data.retrying_count} failed leads for retry`)
      }
      loadData(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Retry failed')
    }
  }

  // Recalculate counts from logs
  const handleRecalculate = async (campaign) => {
    try {
      const res = await recalculateCampaign(campaign.id)
      toast.success(res.data?.message || 'Counts recalculated from logs')
      loadData(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Recalculation failed')
    }
  }

  const hasSending = campaigns.some(c => c.status === 'sending')

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-slate-100 tracking-tight">
              Campaigns Workspace
            </h1>
            {hasSending && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-blue-500/15 text-blue-300 border border-blue-500/30">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                Live Sending Active
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Segmented cold outreach engine with fail-closed MX routing, evidence-backed personalization, and rate limiting.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="btn-secondary text-xs py-2 px-3 flex items-center gap-1.5"
            title="Refresh campaign status and delivery logs"
          >
            <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          <button
            type="button"
            onClick={() => setShowTestModal(true)}
            className="btn-secondary text-xs py-2 px-3 flex items-center gap-1.5"
            title="Dispatch a test preview to operator inbox"
          >
            <FlaskConical size={13} className="text-blue-400" />
            <span>Test Email</span>
          </button>

          <button
            type="button"
            onClick={() => setShowEditor(prev => !prev)}
            className={`btn-primary text-xs py-2 px-4 flex items-center gap-1.5 font-semibold ${
              showEditor ? 'bg-slate-700 hover:bg-slate-600' : ''
            }`}
          >
            {showEditor ? (
              <>
                <X size={14} /> Close Editor
              </>
            ) : (
              <>
                <Plus size={14} /> New Campaign
              </>
            )}
          </button>
        </div>
      </div>

      {/* Partial Error Banner */}
      {partialError && (
        <div className="p-3.5 bg-amber-950/20 border border-amber-800/40 rounded-xl text-amber-300 text-xs flex items-center gap-2">
          <AlertTriangle size={15} className="text-amber-400 shrink-0" />
          <span>{partialError}</span>
        </div>
      )}

      {/* Campaign Creation Drawer / Panel */}
      {showEditor && (
        <CampaignEditorPanel
          leads={leads}
          segments={segments}
          onClose={() => setShowEditor(false)}
          onCreate={() => {
            setShowEditor(false)
            loadData(true)
          }}
        />
      )}

      {/* KPI Overview Cards */}
      <CampaignKpiCards
        campaigns={campaigns}
        senderStatus={senderStatus}
        onRefresh={() => loadData(true)}
        refreshing={refreshing}
      />

      {/* Main Campaign List Table or Loading Skeleton */}
      {loading ? (
        <CampaignSkeleton />
      ) : (
        <CampaignListTable
          campaigns={campaigns}
          onAction={handleAction}
          onRetryFailed={handleRetryFailed}
          onRecalculate={handleRecalculate}
          actionLoading={refreshing}
        />
      )}

      {/* Action Confirmation Modal */}
      <CampaignActionModal
        isOpen={actionModal.isOpen}
        action={actionModal.action}
        campaign={actionModal.campaign}
        onConfirm={handleConfirmAction}
        onCancel={() => setActionModal({ isOpen: false, action: null, campaign: null, loading: false })}
        loading={actionModal.loading}
      />

      {/* Test Email Modal */}
      <TestEmailModal
        isOpen={showTestModal}
        onClose={() => setShowTestModal(false)}
        leads={leads}
        segments={segments}
      />
    </div>
  )
}
