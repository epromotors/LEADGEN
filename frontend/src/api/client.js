import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Attach JWT token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('teb_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})


// ── Frontend → Backend log sink ───────────────────────────────────────────────
// Sends browser-side errors to /api/logs/frontend so they appear in the same
// IST rotating log file as the backend.
// Queued to avoid log loops (skipLog flag) and deduplicated every 5 s.
const _logQueue  = []
let   _logFlush  = null

function _sendToBackend(level, message, context = '') {
  _logQueue.push({ level, message, context })
  if (!_logFlush) {
    _logFlush = setTimeout(() => {
      const batch = _logQueue.splice(0)
      _logFlush  = null
      batch.forEach(entry => {
        // Fire-and-forget — never throw
        fetch('/api/logs/frontend', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify(entry),
        }).catch(() => {})
      })
    }, 300)   // batch up entries within 300 ms
  }
}


// ── Auto logout on 401 + log all API errors ───────────────────────────────────
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.config?._skipLog !== true) {
      const status  = err.response?.status ?? 'network'
      const url     = err.config?.url ?? '?'
      const method  = (err.config?.method ?? 'GET').toUpperCase()
      const detail  = err.response?.data?.detail ?? err.message ?? 'unknown error'
      const level   = status === 401 ? 'info' : status >= 500 ? 'error' : 'warn'
      _sendToBackend(level, `API ${method} ${url} → ${status}: ${detail}`, window.location.pathname)
    }

    if (err.response?.status === 401) {
      localStorage.removeItem('teb_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)


// ── Global JS error / unhandled promise rejection capture ────────────────────
if (typeof window !== 'undefined') {
  window.addEventListener('error', (e) => {
    const msg = `${e.message} (${e.filename}:${e.lineno}:${e.colno})`
    _sendToBackend('error', msg, 'window.onerror')
  })

  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason?.message ?? String(e.reason ?? 'unhandled promise rejection')
    _sendToBackend('error', reason, 'unhandledrejection')
  })
}


// ─── Auth ──────────────────────────────────────────────────────────────────
export const login = (username, password) =>
  api.post('/auth/login', { username, password })

// ─── Leads ─────────────────────────────────────────────────────────────────
export const uploadLeads = (formData) =>
  api.post('/leads/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

// getLeads: paginated list used by Leads page
export const getLeads = ({ page = 1, page_size = 50, status = '', q = '' } = {}) =>
  api.get('/leads/', { params: { page, page_size, ...(status && { status }), ...(q && { q }) } })

// getAllLeadsForPicker: load all leads for campaign creation panel (no page cap)
export const getAllLeadsForPicker = () =>
  api.get('/leads/', { params: { page: 1, page_size: 2000 } })

export const deleteLead      = (id)  => api.delete(`/leads/${id}`)
export const bulkDeleteLeads = (ids) => api.post('/leads/bulk-delete', { ids, confirmed_count: ids.length })
export const updateLead      = (id, data) => api.patch(`/leads/${id}`, data)
export const getLeadQualityReviewQueue = (params = {}) => api.get('/leads/quality-repair/review-queue', { params })
export const previewLeadQualityRepair = (leadIds) => api.post('/leads/quality-repair/preview', { lead_ids: leadIds })
export const retryLeadQualityDiscovery = (id, reverifyEmail = false) =>
  api.post(`/leads/quality-repair/${id}/retry`, { reverify_email: reverifyEmail })
export const keepLeadUnderReview = (id) =>
  api.post(`/leads/quality-repair/${id}/keep-under-review`)

// ─── Lead Discovery (Scraper + Bulk Import) ─────────────────────────────────
export const getDiscoveryPresets = () =>
  api.get('/leads/discovery/presets')
export const getDiscoveryProviders = () =>
  api.get('/leads/discovery/providers')
export const uploadDiscoveryTxt = (file, fileType) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/leads/discovery/upload-txt', fd, {
    params: { file_type: fileType },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const previewDiscovery = (data) =>
  api.post('/leads/discovery/preview', data)
export const createDiscoveryJob = (data) =>
  api.post('/leads/discovery/jobs', data)
export const getDiscoveryJobs = () =>
  api.get('/leads/discovery/jobs')
export const getDiscoveryJob = (jobId) =>
  api.get(`/leads/discovery/jobs/${jobId}`)
export const pauseDiscoveryJob = (jobId) =>
  api.post(`/leads/discovery/jobs/${jobId}/pause`)
export const resumeDiscoveryJob = (jobId) =>
  api.post(`/leads/discovery/jobs/${jobId}/resume`)
export const cancelDiscoveryJob = (jobId) =>
  api.post(`/leads/discovery/jobs/${jobId}/cancel`)
export const getDiscoveryExportUrl = (jobId, format = 'leadgen', sendableOnly = false) =>
  `/api/leads/discovery/jobs/${jobId}/export?format=${format}${sendableOnly ? '&sendable_only=true' : ''}`
export const downloadDiscoveryExport = async (jobId, format = 'leadgen', sendableOnly = false) => {
  const resp = await api.get(`/leads/discovery/jobs/${jobId}/export`, {
    params: { format, sendable_only: sendableOnly },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(new Blob([resp.data]))
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', `leads_${jobId}_${format}${sendableOnly ? '_sendable' : ''}.csv`)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}
export const approveLeadAssociation = (leadId, data) =>
  api.post(`/leads/${leadId}/approve-association`, data)

export const triggerAudit     = (leadId, targetKeywords = null) => {
  if (targetKeywords && targetKeywords.length) {
    return api.post(`/audits/trigger/${leadId}`, { target_keywords: targetKeywords })
  }
  return api.post(`/audits/trigger/${leadId}`)
}
// mode: 'new_only' | 'not_emailed' | 'force_all'
export const triggerAllAudits = (mode = 'new_only') =>
  api.post('/audits/trigger-all', null, { params: { mode } })
export const triggerSkippedAudits = () => api.post('/audits/trigger-skipped')
export const getAuditStats    = () => api.get('/audits/stats')

export const getAudit      = (leadId)  => api.get(`/audits/${leadId}`)
export const getPdfUrl     = (leadId)  => `/api/audits/pdf/${leadId}`

// ─── Campaigns ─────────────────────────────────────────────────────────────
export const getCampaigns     = ()                     => api.get('/campaigns/')
export const getCampaign      = (id)                   => api.get(`/campaigns/${id}`)
export const createCampaign   = (data)                 => api.post('/campaigns/', data)
export const sendCampaign     = (id, force = false)    => api.post(`/campaigns/${id}/send`, null, { params: { force } })
export const pauseCampaign    = (id)                   => api.post(`/campaigns/${id}/pause`)
export const resumeCampaign   = (id)                   => api.post(`/campaigns/${id}/resume`)
export const resetCampaign    = (id)                   => api.post(`/campaigns/${id}/reset`)
export const deleteCampaign   = (id)                   => api.delete(`/campaigns/${id}`)
export const retryCampaignFailed = (id)               => api.post(`/campaigns/${id}/retry-failed`)
export const getCampaignLogs  = (id, limit = 50)       => api.get(`/campaigns/${id}/logs`, { params: { limit } })
export const recalculateCampaign = (id)             => api.post(`/campaigns/${id}/recalculate`)
export const sendTestEmail    = (leadId, toEmail)      => api.post('/campaigns/send-test', { lead_id: leadId, to_email: toEmail })
export const getCampaignSegments = ()                  => api.get('/campaigns/segments')
export const getSenderStatus  = ()                     => api.get('/campaigns/sender-status')
export const previewCampaignEmail = (data)             => api.post('/campaigns/preview', data)
export const checkCampaignAudience = (data)            => api.post('/campaigns/audience-check', data)
export const refreshCampaignAudit   = (leadId)          => api.post(`/campaigns/refresh-audit/${leadId}`)

// ─── Replies & Inbox ───────────────────────────────────────────────────────
export const checkReplies         = ()                  => api.post('/replies/check')
export const checkRepliesNow      = ()                  => api.post('/replies/check-now')
export const getConvertedLeads    = ({ page = 1, page_size = 50 } = {}) =>
  api.get('/replies/converted', { params: { page, page_size } })
export const getAllReplies        = ({ page = 1, page_size = 100 } = {}) =>
  api.get('/replies/all-replies', { params: { page, page_size } })
export const getReplyStats        = ()                  => api.get('/replies/stats')
export const previewEmail2        = (leadId)            => api.get(`/replies/preview-email2/${leadId}`)
export const sendEmail2           = (leadId, data = {}) => api.post(`/replies/send-email2/${leadId}`, data)
export const reclassifyReply      = (leadId)            => api.patch(`/replies/reclassify/${leadId}`)

// ─── Activity / Metrics ────────────────────────────────────────────────────
export const getActivity = (limit = 50)  => api.get('/activity/', { params: { limit } })
export const getMetrics  = ()            => api.get('/activity/metrics')

// ─── Email Review ──────────────────────────────────────────────────────────
export const scanEmails          = (onlyUnscanned = false) => api.post('/email-review/scan', null, { params: { only_unscanned: onlyUnscanned } })
export const getEmailCorrections = (status = 'pending') =>
  api.get('/email-review/', { params: { status } })
export const acceptCorrection    = (id)        => api.post(`/email-review/${id}/accept`)
export const dismissCorrection   = (id)        => api.post(`/email-review/${id}/dismiss`)
export const getEmailReviewStats = ()          => api.get('/email-review/stats')

// ─── Proposals & Service Opportunities ─────────────────────────────────────
export const getProposal     = (leadId) => api.get(`/proposals/${leadId}`)
export const editProposal    = (leadId, data) => api.put(`/proposals/${leadId}`, data)
export const approveProposal = (leadId, userEmail = 'operator@tebsolutions.in') =>
  api.post(`/proposals/${leadId}/approve`, { user_email: userEmail })
export const sendProposal    = (leadId, targetEmail, dryRun = true) =>
  api.post(`/proposals/${leadId}/send`, { target_email: targetEmail, dry_run: dryRun })

// ─── Search Console & AI Search ────────────────────────────────────────────
export const getGscStatus          = (propertyKey = 'default') => api.get('/gsc/status', { params: { property_key: propertyKey } })
export const getGscAuthUrl         = (propertyKey = 'default', state) => api.get('/gsc/auth-url', { params: { property_key: propertyKey, ...(state ? { state } : {}) } })
export const getGscProperties      = (propertyKey = 'default') => api.get('/gsc/properties', { params: { property_key: propertyKey } })
export const getGscPerformance     = (siteUrl, propertyKey = 'default', days = 28) => api.get('/gsc/performance', { params: { site_url: siteUrl, property_key: propertyKey, days } })
export const exchangeGscToken      = (payload) => api.post('/gsc/oauth/exchange', payload)
export const getAiSearchStatus     = () => api.get('/ai-search/status')
export const getAiReadiness        = (leadId) => api.get(`/ai-search/readiness/${leadId}`)
export const runAiVisibilityCheck  = (payload) => api.post('/ai-search/run', payload)
export const getAiSearchHistory    = (leadId) => api.get(`/ai-search/history/${leadId}`)
export const getLatestAiSearchRun  = (leadId) => api.get(`/ai-search/latest/${leadId}`)
export const recordAiObservation   = (data) => api.post('/ai-search/observations', data)
export const getAiObservations     = (params = {}) => api.get('/ai-search/observations', { params })
export const compareAiObservations = (baseId, targetId) => api.get('/ai-search/observations/compare', { params: { base_id: baseId, target_id: targetId } })
export const getAiObservation      = (id) => api.get(`/ai-search/observations/${id}`)
export const getAiSearchCoverage   = (params = {}) => api.get('/ai-search/coverage', { params })

// ─── Email Verification & Deliverability Hub ──────────────────────────────
export const verifySingleEmail            = (data) => api.post('/email-verify/single', data)
export const verifyLeadEmail              = (leadId, data = {}) => api.post(`/email-verify/lead/${leadId}`, data)
export const reverifyLead                 = (leadId, data = {}) => api.post(`/email-verify/reverify/${leadId}`, data)
export const bulkVerifyEmails             = (data = {}) => api.post('/email-verify/bulk', data)
export const getEmailVerificationProgress = () => api.get('/email-verify/progress')
export const cancelEmailVerificationJob   = () => api.post('/email-verify/cancel')
export const getEmailVerificationStats    = () => api.get('/email-verify/stats')
export const getEmailVerificationLeads    = (params = {}) => api.get('/email-verify/leads', { params })

export default api
