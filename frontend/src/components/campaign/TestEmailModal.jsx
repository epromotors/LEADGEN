import React, { useState } from 'react'
import { FlaskConical, X, Send, CheckCircle2, AlertCircle, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'
import { sendTestEmail } from '../../api/client'

export default function TestEmailModal({ isOpen, onClose, leads = [], segments = {} }) {
  const [leadId, setLeadId] = useState('')
  const [toEmail, setToEmail] = useState('')
  const [campaignType, setCampaignType] = useState('generic_first_contact')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  if (!isOpen) return null

  async function handleSend(e) {
    e.preventDefault()
    if (!leadId) {
      toast.error('Select a sample lead for variable substitution')
      return
    }
    if (!toEmail || !toEmail.includes('@')) {
      toast.error('Enter a valid destination email')
      return
    }

    setSending(true)
    setResult(null)
    setError(null)
    try {
      const res = await sendTestEmail(leadId, toEmail)
      setResult(res.data)
      toast.success(`Preview email dispatched via ${res.data.sender}`)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Test send failed'
      setError(msg)
      toast.error(msg)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="card-elevated border border-slate-700/80 w-full max-w-lg p-6 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="p-2.5 rounded-xl border bg-blue-500/10 border-blue-500/30 text-blue-400">
            <FlaskConical size={20} />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-100">Send Test Outreach Preview</h3>
            <p className="text-xs text-slate-400">
              Renders exact personalized email and delivers it to an operator inbox
            </p>
          </div>
        </div>

        <form onSubmit={handleSend} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              1. Sample Prospect Lead
            </label>
            <select
              value={leadId}
              onChange={e => setLeadId(e.target.value)}
              className="input text-xs"
              required
            >
              <option value="">Select a lead for variable substitution…</option>
              {leads.map(l => (
                <option key={l.id} value={l.id}>
                  {l.business_name} ({l.email || 'No email'}) {l.website ? `· ${l.website}` : ''}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-slate-500 mt-1">
              Provides business name, audit findings, and score to the template renderer
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              2. Outreach Segment / Strategy
            </label>
            <select
              value={campaignType}
              onChange={e => setCampaignType(e.target.value)}
              className="input text-xs"
            >
              {Object.entries(segments).map(([id, seg]) => (
                <option key={id} value={id}>
                  {seg.name || id.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              3. Deliver Preview To
            </label>
            <input
              type="email"
              value={toEmail}
              onChange={e => setToEmail(e.target.value)}
              placeholder="e.g. operator@yourcompany.com"
              className="input text-xs"
              required
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Destination inbox to review visual appearance and rendering quality
            </p>
          </div>

          {result && (
            <div className="p-3 bg-emerald-950/20 border border-emerald-800/40 rounded-lg text-emerald-300 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-bold">
                <CheckCircle2 size={13} />
                <span>Test Email Delivered</span>
              </div>
              <div>Route: <span className="font-mono text-white">{result.sender}</span></div>
              <div className="truncate">Subject: <span className="text-slate-200">{result.subject}</span></div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-rose-950/20 border border-rose-800/40 rounded-lg text-rose-300 text-xs flex items-start gap-2">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={sending}
              className="btn-secondary text-xs py-2 px-4"
            >
              Close
            </button>
            <button
              type="submit"
              disabled={sending}
              className="btn-primary text-xs py-2 px-4"
            >
              {sending ? (
                <span className="flex items-center gap-1.5">
                  <span className="spinner w-3.5 h-3.5 border-white border-t-transparent" />
                  Sending Test Email…
                </span>
              ) : (
                <span className="flex items-center gap-1.5">
                  <Send size={13} /> Send Test Email
                </span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
