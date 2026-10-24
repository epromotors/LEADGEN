import React, { useEffect, useState } from 'react'
import { Pencil, X, Sparkles, Check, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { updateLead, getAudit } from '../../api/client'

export default function EditLeadModal({ lead, onSaved, onClose }) {
  const [form, setForm] = useState({
    business_name: lead.business_name || '',
    email: lead.email || '',
    phone: lead.phone || '',
    website: lead.website || '',
  })
  const [saving, setSaving] = useState(false)
  const [suggestedName, setSuggestedName] = useState(null)
  const [loadingSuggestion, setLoadingSuggestion] = useState(false)

  // Fetch audit data to check for AI suggested business name
  useEffect(() => {
    if (['audited', 'emailed', 'replied'].includes(lead.status)) {
      setLoadingSuggestion(true)
      getAudit(lead.id)
        .then(res => {
          const name = res.data?.suggested_name
          if (name && name.trim().toLowerCase() !== (lead.business_name || '').trim().toLowerCase()) {
            setSuggestedName(name.trim())
          }
        })
        .catch(() => {})
        .finally(() => setLoadingSuggestion(false))
    }
  }, [lead.id, lead.status, lead.business_name])

  function applySuggestion() {
    if (!suggestedName) return
    setForm(f => ({ ...f, business_name: suggestedName }))
    setSuggestedName(null)
    toast.success('Applied suggested business name')
  }

  async function handleSave(e) {
    e.preventDefault()
    if (!form.business_name.trim()) {
      toast.error('Business name is required')
      return
    }
    if (!form.email.trim()) {
      toast.error('Email is required')
      return
    }

    setSaving(true)
    try {
      await updateLead(lead.id, {
        business_name: form.business_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || null,
        website: form.website.trim(),
      })
      toast.success('Lead updated successfully')
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const looksScraped =
    form.business_name.includes('|') ||
    form.business_name.includes(' - ') ||
    form.business_name.length > 60

  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={e => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="card-elevated w-full max-w-lg p-0 overflow-hidden shadow-2xl border border-slate-700/80 animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
              <Pencil size={16} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Edit Lead Record
              </h3>
              <p className="text-[11px] text-slate-400 truncate max-w-xs font-mono">
                {lead.website?.replace(/^https?:\/\//, '') || lead.email}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* AI Name Suggestion */}
        {loadingSuggestion && (
          <div className="mx-6 mt-4 p-3 rounded-lg bg-violet-950/20 border border-violet-800/40 flex items-center gap-2.5 text-xs text-violet-300">
            <span className="spinner w-3.5 h-3.5 border-violet-400 border-t-transparent" />
            <span>Scanning site metadata for clean business name suggestion…</span>
          </div>
        )}

        {suggestedName && !loadingSuggestion && (
          <div className="mx-6 mt-4 p-3.5 rounded-lg bg-violet-950/30 border border-violet-800/50">
            <div className="flex items-start gap-2.5">
              <Sparkles size={16} className="text-violet-400 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <span className="text-[10px] uppercase font-bold text-violet-400 tracking-wider block mb-1">
                  AI Metadata Suggestion
                </span>
                <p className="text-xs font-bold text-slate-100 mb-2 truncate">
                  "{suggestedName}"
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={applySuggestion}
                    className="btn-primary py-1 px-2.5 text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white"
                  >
                    <Check size={12} /> Use this name
                  </button>
                  <button
                    type="button"
                    onClick={() => setSuggestedName(null)}
                    className="btn-secondary py-1 px-2.5 text-xs text-slate-400"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSave} className="p-6 space-y-4">
          <div>
            <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
              Business Name *
            </label>
            <input
              type="text"
              className="input text-xs"
              value={form.business_name}
              onChange={e => setForm(f => ({ ...f, business_name: e.target.value }))}
              placeholder="Acme Legal Services"
              required
              autoFocus
            />
            {looksScraped && (
              <p className="text-[11px] text-amber-400 mt-1.5 flex items-center gap-1.5">
                <AlertTriangle size={12} className="shrink-0" />
                Name contains delimiters (| or -). Clean the title before outreach.
              </p>
            )}
          </div>

          <div>
            <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
              Email Address *
            </label>
            <input
              type="email"
              className="input text-xs"
              value={form.email}
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              placeholder="contact@company.com"
              required
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                Phone
              </label>
              <input
                type="text"
                className="input text-xs"
                value={form.phone}
                onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                placeholder="+1 555-0199"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                Website URL
              </label>
              <input
                type="text"
                className="input text-xs"
                value={form.website}
                onChange={e => setForm(f => ({ ...f, website: e.target.value }))}
                placeholder="https://company.com"
              />
            </div>
          </div>

          <div className="pt-3 flex gap-2 justify-end border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary text-xs py-2 px-4 font-semibold"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="btn-primary text-xs py-2 px-5 font-bold shadow-lg shadow-blue-900/30 flex items-center gap-1.5"
            >
              {saving ? (
                <>
                  <span className="spinner w-3.5 h-3.5 border-white border-t-transparent" />
                  Saving…
                </>
              ) : (
                <>
                  <Check size={14} />
                  Save Changes
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
