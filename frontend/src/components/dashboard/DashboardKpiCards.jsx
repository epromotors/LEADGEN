import React from 'react'
import { Users, CheckCircle2, ShieldCheck, Mail, Zap, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function DashboardKpiCards({ metrics, auditStats, emailStats, campaigns }) {
  const totalLeads = metrics?.total_leads ?? auditStats?.total ?? 0
  const auditsDone = metrics?.audits_complete ?? auditStats?.audited ?? 0
  const auditPercent = totalLeads > 0 ? Math.round((auditsDone / totalLeads) * 100) : 0
  
  // Deliverability pool
  const deliverableCount = emailStats?.deliverable ?? 0
  const quarantinedCount = emailStats?.quarantined ?? 0
  const deliverablePercent = totalLeads > 0 ? Math.round((deliverableCount / totalLeads) * 100) : 0

  // Campaign count
  const activeCampaigns = metrics?.campaigns_active ?? 0
  const totalEmailsSent = metrics?.emails_sent ?? 0

  const cards = [
    {
      id: 'kpi-leads',
      label: 'Total Leads Ingested',
      value: totalLeads.toLocaleString(),
      subtext: `${(auditStats?.new ?? 0).toLocaleString()} new · ${(auditStats?.audited ?? 0).toLocaleString()} audited`,
      icon: Users,
      iconColor: 'text-blue-400',
      iconBg: 'bg-blue-500/10 border-blue-500/20',
      linkTo: '/leads',
      linkLabel: 'View leads',
    },
    {
      id: 'kpi-audits',
      label: 'SEO Audits Completed',
      value: auditsDone.toLocaleString(),
      subtext: auditStats?.batch_running 
        ? 'Batch crawler in progress'
        : `${auditPercent}% coverage of active leads`,
      badge: auditStats?.batch_running ? 'Crawling' : null,
      badgeColor: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
      icon: CheckCircle2,
      iconColor: 'text-emerald-400',
      iconBg: 'bg-emerald-500/10 border-emerald-500/20',
      linkTo: '/audits',
      linkLabel: 'View audits',
    },
    {
      id: 'kpi-deliverable',
      label: 'Deliverability Pool',
      value: deliverableCount.toLocaleString(),
      subtext: emailStats 
        ? `${deliverablePercent}% sendable · ${quarantinedCount} quarantined`
        : 'Deliverability stats unavailable',
      icon: ShieldCheck,
      iconColor: 'text-cyan-400',
      iconBg: 'bg-cyan-500/10 border-cyan-500/20',
      linkTo: '/leads?status=quarantined',
      linkLabel: 'Inspect safety',
    },
    {
      id: 'kpi-outreach',
      label: 'Campaigns & Outreach',
      value: `${activeCampaigns} Active`,
      subtext: `${totalEmailsSent.toLocaleString()} total emails sent`,
      icon: Mail,
      iconColor: 'text-violet-400',
      iconBg: 'bg-violet-500/10 border-violet-500/20',
      linkTo: '/campaigns',
      linkLabel: 'Manage',
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map(card => {
        const Icon = card.icon
        return (
          <div
            key={card.id}
            className="card-elevated p-5 flex flex-col justify-between hover:border-slate-600 transition-all duration-200 group relative overflow-hidden"
          >
            {/* Ambient subtle glow */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 rounded-full blur-2xl pointer-events-none" />

            <div>
              <div className="flex items-center justify-between gap-2 mb-3">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {card.label}
                </span>
                <div className={`p-2 rounded-lg border ${card.iconBg} ${card.iconColor} shrink-0`}>
                  <Icon size={18} />
                </div>
              </div>

              <div className="flex items-baseline gap-2 mb-1.5">
                <span className="text-2xl lg:text-3xl font-extrabold text-slate-100 tracking-tight">
                  {card.value}
                </span>
                {card.badge && (
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${card.badgeColor} flex items-center gap-1`}>
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                    {card.badge}
                  </span>
                )}
              </div>

              <p className="text-xs text-slate-400 font-medium leading-relaxed truncate">
                {card.subtext}
              </p>
            </div>

            <div className="pt-4 mt-3 border-t border-slate-800/80 flex items-center justify-between text-xs">
              <Link
                to={card.linkTo}
                className="text-blue-400 hover:text-blue-300 font-medium inline-flex items-center gap-1 group-hover:translate-x-0.5 transition-transform"
              >
                {card.linkLabel}
                <ArrowUpRight size={13} />
              </Link>
            </div>
          </div>
        )
      })}
    </div>
  )
}
