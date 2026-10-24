import React from 'react'
import { Send, RotateCcw, Trash2, AlertTriangle, X, ShieldAlert, CheckCircle2 } from 'lucide-react'

export default function CampaignActionModal({ isOpen, action, campaign, onConfirm, onCancel, loading }) {
  if (!isOpen || !campaign) return null

  const actionConfig = {
    send: {
      title: `Launch Campaign: ${campaign.name}`,
      icon: Send,
      iconColor: 'text-blue-400',
      iconBg: 'bg-blue-500/10 border-blue-500/30',
      btnText: 'Confirm & Launch Outreach',
      btnClass: 'bg-blue-600 hover:bg-blue-500 text-white',
      description: (
        <div className="space-y-3 text-xs text-slate-300">
          <p>
            You are about to start dispatching personalized emails to{' '}
            <strong className="text-white font-semibold">
              {campaign.lead_ids?.length || 0} targeted recipients
            </strong>{' '}
            for campaign <strong className="text-blue-300 font-semibold">{campaign.name}</strong>.
          </p>
          <div className="p-3 bg-slate-900 border border-slate-800 rounded-lg space-y-1.5">
            <div className="flex items-center gap-2 text-emerald-400 font-semibold">
              <CheckCircle2 size={13} />
              <span>Safety Safeguards Active</span>
            </div>
            <ul className="list-disc list-inside text-slate-400 text-[11px] space-y-0.5 ml-1">
              <li>Humanized delay between successive emails (rate-limit protection)</li>
              <li>Pre-send gatekeeper verifies MX routing &amp; business association</li>
              <li>7-day recipient cooldown automatically respected</li>
              <li>Campaign execution can be paused at any time</li>
            </ul>
          </div>
        </div>
      ),
    },
    reset: {
      title: `Reset Campaign: ${campaign.name}`,
      icon: RotateCcw,
      iconColor: 'text-amber-400',
      iconBg: 'bg-amber-500/10 border-amber-500/30',
      btnText: 'Reset to Draft',
      btnClass: 'bg-amber-600 hover:bg-amber-500 text-white',
      description: (
        <div className="space-y-2 text-xs text-slate-300">
          <p>
            Resetting will transition <strong className="text-white">{campaign.name}</strong> from{' '}
            <span className="font-semibold text-amber-300">{campaign.status}</span> back to{' '}
            <span className="font-semibold text-slate-200">draft</span>.
          </p>
          <p className="text-slate-400">
            Execution counters and pending queues will be cleared. You can review template settings or adjust lead selection before re-launching.
          </p>
        </div>
      ),
    },
    delete: {
      title: `Delete Campaign: ${campaign.name}`,
      icon: Trash2,
      iconColor: 'text-rose-400',
      iconBg: 'bg-rose-500/10 border-rose-500/30',
      btnText: 'Delete Campaign Permanently',
      btnClass: 'bg-rose-600 hover:bg-rose-500 text-white',
      description: (
        <div className="space-y-2 text-xs text-slate-300">
          <div className="flex items-start gap-2 p-3 bg-rose-950/20 border border-rose-800/40 rounded-lg text-rose-300">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            <span>
              This will permanently remove the campaign record. Existing recipient delivery logs will be purged. This action cannot be reversed.
            </span>
          </div>
        </div>
      ),
    },
  }

  const current = actionConfig[action] || actionConfig.send
  const Icon = current.icon

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="card-elevated border border-slate-700/80 w-full max-w-md p-6 shadow-2xl relative">
        <button
          onClick={onCancel}
          disabled={loading}
          className="absolute top-4 right-4 text-slate-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className={`p-2.5 rounded-xl border ${current.iconBg} ${current.iconColor}`}>
            <Icon size={20} />
          </div>
          <div>
            <h3 className="text-base font-bold text-slate-100">{current.title}</h3>
            <p className="text-xs text-slate-400">Confirmation required</p>
          </div>
        </div>

        <div className="mb-6">{current.description}</div>

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="btn-secondary text-xs py-2 px-4"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={`btn-primary text-xs py-2 px-4 font-semibold ${current.btnClass} ${
              loading ? 'opacity-50 cursor-wait' : ''
            }`}
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <span className="spinner w-3.5 h-3.5 border-white border-t-transparent" />
                Processing…
              </span>
            ) : (
              current.btnText
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
