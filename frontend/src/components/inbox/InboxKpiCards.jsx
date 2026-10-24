import React from 'react'
import { CheckCircle2, AlertTriangle, Trash2, Radio, Server, Mail, ArrowUpRight } from 'lucide-react'

export default function InboxKpiCards({ stats, lastSynced, onSyncNow, syncing }) {
  const converted = stats?.converted ?? 0
  const softBounce = stats?.soft_bounce ?? 0
  const deletedToday = stats?.deleted_today ?? 0

  const cards = [
    {
      id: 'kpi-converted',
      label: 'Converted Leads',
      value: converted.toLocaleString(),
      subtext: 'Hot prospects who replied positively with interest',
      badge: converted > 0 ? 'High Intent' : null,
      badgeColor: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
      icon: CheckCircle2,
      iconColor: 'text-emerald-400',
      iconBg: 'bg-emerald-500/10 border-emerald-500/20',
    },
    {
      id: 'kpi-soft-bounce',
      label: 'Soft Bounces (OOO)',
      value: softBounce.toLocaleString(),
      subtext: 'Out-of-office / temporary absence (email preserved)',
      badge: softBounce > 0 ? 'Follow-Up' : null,
      badgeColor: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
      icon: AlertTriangle,
      iconColor: 'text-amber-400',
      iconBg: 'bg-amber-500/10 border-amber-500/20',
    },
    {
      id: 'kpi-deleted-today',
      label: 'Suppressed & Purged Today',
      value: deletedToday.toLocaleString(),
      subtext: 'STOP / Unsubscribe & hard bounce compliance purges',
      badge: 'CAN-SPAM Safe',
      badgeColor: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
      icon: Trash2,
      iconColor: 'text-rose-400',
      iconBg: 'bg-rose-500/10 border-rose-500/20',
    },
    {
      id: 'kpi-imap-health',
      label: 'IMAP Ingestion Route',
      value: 'Hostinger SSL',
      subtext: lastSynced
        ? `Last checked: ${lastSynced.toLocaleTimeString('en-IN')}`
        : 'INBOX + Spam scanner active',
      badge: syncing ? 'Syncing…' : 'Port 993',
      badgeColor: syncing ? 'bg-blue-500/20 text-blue-300 border-blue-500/30' : 'bg-slate-700 text-slate-300 border-slate-600',
      icon: Server,
      iconColor: 'text-blue-400',
      iconBg: 'bg-blue-500/10 border-blue-500/20',
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {cards.map(card => {
        const Icon = card.icon
        return (
          <div
            key={card.id}
            className="card-elevated p-5 flex flex-col justify-between hover:border-slate-600 transition-all duration-200 group relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 w-28 h-28 bg-emerald-500/5 rounded-full blur-2xl pointer-events-none" />

            <div>
              <div className="flex items-center justify-between gap-2 mb-3">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {card.label}
                </span>
                <div className={`p-2 rounded-lg border ${card.iconBg} ${card.iconColor} shrink-0`}>
                  <Icon size={18} />
                </div>
              </div>

              <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
                <span className="text-2xl lg:text-3xl font-extrabold text-slate-100 tracking-tight">
                  {card.value}
                </span>
                {card.badge && (
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${card.badgeColor} flex items-center gap-1`}>
                    {card.badge === 'Syncing…' && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
                    {card.badge}
                  </span>
                )}
              </div>

              <p className="text-xs text-slate-400 leading-relaxed truncate" title={card.subtext}>
                {card.subtext}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
