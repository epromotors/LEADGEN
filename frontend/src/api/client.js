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
export const bulkDeleteLeads = (ids) => api.post('/leads/bulk-delete', { ids })
export const deleteAllLeads  = ()    => api.delete('/leads/all')
export const updateLead      = (id, data) => api.patch(`/leads/${id}`, data)

// ─── Audits ────────────────────────────────────────────────────────────────
export const triggerAudit     = (leadId) => api.post(`/audits/trigger/${leadId}`)
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
export const sendTestEmail    = (leadId, toEmail)      => api.post('/campaigns/send-test', { lead_id: leadId, to_email: toEmail })

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

export default api
