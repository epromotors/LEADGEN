import React, { useState, useEffect } from 'react'
import {
  Send, X, CheckCircle2, RotateCcw, AlertTriangle, Eye,
  Code, ShieldCheck, ShieldAlert, Sparkles, ExternalLink
} from 'lucide-react'
import toast from 'react-hot-toast'
import { previewEmail2, sendEmail2 } from '../../api/client'

export default function Email2ComposeModal({ lead, onClose, onSent }) {
  const [loading, setLoading] = useState(true)
  const [html, setHtml] = useState('')
  const [origHtml, setOrigHtml] = useState('')
  const [tab, setTab] = useState('preview') // 'preview' | 'edit'
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  const domain = (lead?.website || '')
    .replace(/^https?:\/\//, '')
    .replace(/^www\./, '')
    .split('/')[0]

  const defaultSubject = `Website redesign & modernization proposal for ${domain || lead?.business_name}`
  const [subject, setSubject] = useState(defaultSubject)

  useEffect(() => {
    if (!lead?.id) return
    setLoading(true)
    setError('')
    previewEmail2(lead.id)
      .then(res => {
        const body = res.data?.html || ''
        setHtml(body)
        setOrigHtml(body)
        setLoading(false)
      })
      .catch(err => {
        const msg = err.response?.data?.detail || err.message || 'Failed to generate proposal preview'
        setError(msg)
        setLoading(false)
      })
  }, [lead?.id])

  if (!lead) return null

  const isEdited = html !== origHtml || subject !== defaultSubject

  const handleReset = () => {
    setHtml(origHtml)
    setSubject(defaultSubject)
  }

  const handleSend = async () => {
    setSending(true)
    setError('')
    try {
      await sendEmail2(lead.id, {
        custom_html: html !== origHtml ? html : null,
        custom_subject: subject !== defaultSubject ? subject : null,
      })
      setSent(true)
      toast.success(`Email 2 sent to ${lead.email}`)
      if (onSent) onSent()
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to dispatch proposal'
      setError(msg)
      toast.error(msg)
    } finally {
      setSending(false)
      setConfirming(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="card-elevated border border-slate-700/80 w-full max-w-4xl max-h-[92vh] p-0 shadow-2xl flex flex-col relative overflow-hidden">
        {/* Header */}
        <div className="p-4 px-6 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
          <div>
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400">
                <Send size={15} />
              </div>
              <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                Compose Email 2 Proposal
                {isEdited && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300">
                    Customized
                  </span>
                )}
              </h3>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              To: <strong className="text-slate-200">{lead.business_name}</strong> &lt;
              <a href={`mailto:${lead.email}`} className="text-blue-400 hover:underline">
                {lead.email}
              </a>
              &gt;
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-md hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Subject Editor Bar */}
        <div className="px-6 py-2.5 bg-slate-950 border-b border-slate-800/80 flex items-center gap-3">
          <span className="text-xs font-semibold text-slate-400 whitespace-nowrap">Subject:</span>
          <input
            type="text"
            value={subject}
            onChange={e => setSubject(e.target.value)}
            className="flex-1 bg-transparent border-0 text-xs font-semibold text-slate-200 focus:outline-none focus:ring-0 placeholder-slate-500"
            placeholder="Subject line…"
          />
          {subject !== defaultSubject && (
            <button
              type="button"
              onClick={() => setSubject(defaultSubject)}
              className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 font-medium"
            >
              <RotateCcw size={10} /> Reset Subject
            </button>
          )}
        </div>

        {/* Tab Bar */}
        <div className="px-6 pt-3 bg-slate-900/40 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTab('preview')}
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-t-lg transition-colors border-t border-x ${
                tab === 'preview'
                  ? 'bg-slate-950 text-blue-400 border-slate-700/80 -mb-[1px]'
                  : 'text-slate-400 hover:text-slate-200 border-transparent'
              }`}
            >
              <Eye size={13} /> Visual Preview
            </button>
            <button
              type="button"
              onClick={() => setTab('edit')}
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-t-lg transition-colors border-t border-x ${
                tab === 'edit'
                  ? 'bg-slate-950 text-blue-400 border-slate-700/80 -mb-[1px]'
                  : 'text-slate-400 hover:text-slate-200 border-transparent'
              }`}
            >
              <Code size={13} /> Edit HTML Source
            </button>
          </div>

          {isEdited && (
            <button
              type="button"
              onClick={handleReset}
              className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 font-medium pb-2"
            >
              <RotateCcw size={11} /> Reset to Auto-Generated
            </button>
          )}
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-hidden flex flex-col bg-slate-950 min-h-[360px] max-h-[500px]">
          {loading ? (
            <div className="flex-1 flex items-center justify-center text-xs text-slate-400 gap-2">
              <span className="spinner w-4 h-4 border-blue-400 border-t-transparent" />
              Rendering tailored website proposal…
            </div>
          ) : error && !html ? (
            <div className="p-8 text-center text-rose-300 text-xs">
              <AlertTriangle size={24} className="mx-auto text-rose-400 mb-2" />
              {error}
            </div>
          ) : tab === 'preview' ? (
            <div className="flex-1 overflow-auto bg-white p-2">
              <iframe
                key={html}
                srcDoc={html}
                title="Email 2 Proposal Preview"
                className="w-full h-full min-h-[360px] border-none block"
                sandbox="allow-same-origin"
              />
            </div>
          ) : (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-6 py-2 bg-slate-900/60 border-b border-slate-800 text-[11px] text-slate-400">
                Edit the raw HTML below. Switch to Visual Preview to verify formatting.
              </div>
              <textarea
                value={html}
                onChange={e => setHtml(e.target.value)}
                spellCheck={false}
                className="flex-1 p-4 px-6 bg-slate-950 text-emerald-300 font-mono text-xs leading-relaxed border-0 resize-none focus:outline-none focus:ring-0"
              />
            </div>
          )}
        </div>

        {/* Error notification */}
        {error && (
          <div className="px-6 py-2 bg-rose-950/40 border-t border-rose-800/60 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle size={13} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Footer Actions */}
        <div className="p-4 px-6 border-t border-slate-800 flex items-center justify-between bg-slate-900/60">
          <div className="text-[11px] text-slate-400">
            {lead.is_quarantined ? (
              <span className="text-rose-400 flex items-center gap-1 font-semibold">
                <ShieldAlert size={12} /> Lead is quarantined — Email 2 cannot be sent.
              </span>
            ) : isEdited ? (
              <span className="text-amber-300">⚠️ Customized version will be delivered to prospect.</span>
            ) : (
              <span>Auto-generated proposal will be sent using primary configured SMTP sender.</span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={sending}
              className="btn-secondary text-xs py-2 px-4"
            >
              Cancel
            </button>

            {sent ? (
              <div className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-bold text-xs">
                <CheckCircle2 size={13} /> Proposal Dispatched!
              </div>
            ) : confirming ? (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="btn-secondary text-xs py-2 px-3"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={handleSend}
                  disabled={sending}
                  className="btn-primary text-xs py-2 px-4 bg-emerald-600 hover:bg-emerald-500 font-bold text-white"
                >
                  {sending ? 'Sending…' : `Confirm Send to ${lead.email}`}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                disabled={sending || loading || (!html && !origHtml) || lead.is_quarantined}
                className="btn-primary text-xs py-2 px-5 font-semibold flex items-center gap-1.5 disabled:opacity-40"
              >
                <Send size={13} /> Send Email 2 Proposal
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
