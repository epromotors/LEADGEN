import React from 'react'
import {
  RefreshCw, CheckCircle2, XCircle, AlertTriangle, Mail,
  Clock, ShieldCheck, Server, AlertOctagon, HelpCircle
} from 'lucide-react'

export default function InboxSyncPanel({ onSync, syncing, lastSynced, syncResult }) {
  return (
    <div className="space-y-6">
      {/* Sync Trigger Card */}
      <div className="card-elevated p-6 border border-slate-800 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Server size={18} className="text-blue-400" />
            Hostinger IMAP Inbox Synchronization
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Connects to <code className="text-blue-300 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">imap.hostinger.com:993</code> (SSL) and scans <strong className="text-slate-200">INBOX + Spam</strong> folders for unread replies.
          </p>
          {lastSynced && (
            <p className="text-[11px] text-slate-500 mt-2 flex items-center gap-1.5 font-mono">
              <Clock size={11} className="text-slate-400" />
              Last synchronization executed at: {lastSynced.toLocaleString('en-IN')}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onSync}
          disabled={syncing}
          className="btn-primary text-xs py-2.5 px-5 font-bold flex items-center gap-2 shadow-lg shadow-blue-500/20 disabled:opacity-50"
        >
          <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
          {syncing ? 'Scanning Mailbox…' : 'Sync Inbox Now'}
        </button>
      </div>

      {/* Sync Result Summary Cards */}
      {syncResult && (
        <div className="card-elevated p-5 border border-emerald-500/30 bg-emerald-950/10">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={16} className="text-emerald-400" />
            <h3 className="text-sm font-bold text-emerald-300">
              Synchronization Complete
            </h3>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              {
                label: 'Emails Fetched',
                value: syncResult.fetched ?? 0,
                color: 'text-blue-400',
                desc: 'Unseen messages downloaded',
              },
              {
                label: 'Newly Converted',
                value: syncResult.positive ?? 0,
                color: 'text-emerald-400',
                desc: 'Positive replies matched to leads',
              },
              {
                label: 'Suppressed / Purged',
                value: syncResult.deleted ?? 0,
                color: 'text-rose-400',
                desc: 'STOP or bounce leads removed',
              },
              {
                label: 'Soft Bounces (OOO)',
                value: syncResult.soft_bounce ?? 0,
                color: 'text-amber-400',
                desc: 'Temporary absence flagged',
              },
              {
                label: 'Other / No Match',
                value: syncResult.other ?? 0,
                color: 'text-slate-400',
                desc: 'Unmatched or generic notes',
              },
              {
                label: 'Sync Errors',
                value: syncResult.errors ?? 0,
                color: syncResult.errors > 0 ? 'text-rose-400' : 'text-slate-500',
                desc: 'IMAP parsing failures',
              },
            ].map(item => (
              <div
                key={item.label}
                className="p-3 bg-slate-900/80 rounded-lg border border-slate-800"
              >
                <div className={`text-xl font-extrabold ${item.color}`}>
                  {item.value}
                </div>
                <div className="text-[11px] font-semibold text-slate-300 mt-0.5">
                  {item.label}
                </div>
                <div className="text-[10px] text-slate-500 mt-1 truncate" title={item.desc}>
                  {item.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Compliance & Policy Explanation */}
      <div className="card-elevated p-6 border border-slate-800 space-y-4">
        <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <ShieldCheck size={16} className="text-emerald-400" />
          Automated Reply Classification &amp; Suppression Pipeline
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs text-slate-400">
          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-emerald-400">
              <CheckCircle2 size={14} />
              <span>Positive Replies (YES / Interested / Blueprint)</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Promoted immediately to <strong className="text-white">Converted</strong> status. Saved with reply body snippet and timestamp for operator review and proposal generation.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-rose-400">
              <XCircle size={14} />
              <span>STOP / Unsubscribe Signals</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Enforces CAN-SPAM and outreach compliance. The lead and associated audits are <strong className="text-white">permanently deleted</strong> to guarantee suppression from future campaigns.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-rose-400">
              <AlertOctagon size={14} />
              <span>Hard Bounces (550 / Invalid Recipient)</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Recipient mailbox does not exist. Lead is <strong className="text-white">permanently purged</strong> to protect sender reputation and prevent repeated bounce penalties.
            </p>
          </div>

          <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 space-y-1.5">
            <div className="flex items-center gap-2 font-semibold text-amber-400">
              <AlertTriangle size={14} />
              <span>Soft Bounces / Out of Office</span>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-400">
              Flagged with <code className="text-amber-300">reply_type=soft_bounce</code>. The lead is <strong className="text-white">retained in the database</strong> because the address is valid.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
