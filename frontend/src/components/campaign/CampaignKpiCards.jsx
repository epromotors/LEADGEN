import React from 'react'
import { Mail, Zap, CheckCircle2, ShieldCheck, ShieldAlert, AlertTriangle, Clock, RefreshCw } from 'lucide-react'

export default function CampaignKpiCards({ campaigns = [], senderStatus = null, onRefresh, refreshing }) {
  const totalCampaigns = campaigns.length
  const sendingCampaigns = campaigns.filter(c => c.status === 'sending')
  const pausedCampaigns = campaigns.filter(c => c.status === 'paused')
  const doneCampaigns = campaigns.filter(c => c.status === 'done')
  const draftCampaigns = campaigns.filter(c => c.status === 'draft')

  const totalTargeted = campaigns.reduce((acc, c) => acc + (c.lead_ids?.length || 0), 0)
  const totalSent = campaigns.reduce((acc, c) => acc + (c.sent_count || 0), 0)
  const totalFailed = campaigns.reduce((acc, c) => acc + (c.failed_count || 0), 0)
  const totalSkipped = campaigns.reduce((acc, c) => acc + (c.skipped_count || 0), 0)

  const deliverySuccessRate = (totalSent + totalFailed) > 0
    ? Math.round((totalSent / (totalSent + totalFailed)) * 100)
    : 100

  // Sender infrastructure
  const accounts = senderStatus?.accounts || senderStatus?.senders || []
  const isHealthy = (senderStatus?.status === 'configured' || senderStatus?.configured === true) && accounts.length > 0
  const dailyCapacity = senderStatus?.total_daily_capacity ?? accounts.reduce((acc, a) => acc + (a.daily_limit || 1000), 0)
  const sentToday = accounts.reduce((acc, a) => acc + (a.sent_today || 0), 0)
  const remainingToday = senderStatus?.remaining_today ?? Math.max(0, dailyCapacity - sentToday)

  const cards = [
    {
      id: 'kpi-campaigns-total',
      label: 'Campaign Overview',
      value: totalCampaigns.toLocaleString(),
      subtext: `${sendingCampaigns.length} sending · ${pausedCampaigns.length} paused · ${doneCampaigns.length} done · ${draftCampaigns.length} draft`,
      badge: sendingCampaigns.length > 0 ? `${sendingCampaigns.length} Running` : null,
      badgeColor: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
      icon: Mail,
      iconColor: 'text-blue-400',
      iconBg: 'bg-blue-500/10 border-blue-500/20',
    },
    {
      id: 'kpi-campaigns-progress',
      label: 'Delivery Volume',
      value: totalSent.toLocaleString(),
      subtext: `${totalTargeted.toLocaleString()} total targeted (${totalSkipped} skipped / cooldown)`,
      icon: Zap,
      iconColor: 'text-emerald-400',
      iconBg: 'bg-emerald-500/10 border-emerald-500/20',
    },
    {
      id: 'kpi-campaigns-rate',
      label: 'Delivery Health Rate',
      value: `${deliverySuccessRate}%`,
      subtext: totalFailed > 0 ? `${totalFailed} failed sends requiring retry` : 'Zero delivery rejections',
      badge: totalFailed > 0 ? `${totalFailed} Failed` : '100% Clean',
      badgeColor: totalFailed > 0 ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
      icon: totalFailed > 0 ? AlertTriangle : CheckCircle2,
      iconColor: totalFailed > 0 ? 'text-rose-400' : 'text-teal-400',
      iconBg: totalFailed > 0 ? 'bg-rose-500/10 border-rose-500/20' : 'bg-teal-500/10 border-teal-500/20',
    },
    {
      id: 'kpi-campaigns-sender',
      label: 'Sender Infrastructure',
      value: isHealthy ? `${remainingToday.toLocaleString()} Left` : 'Disabled',
      subtext: isHealthy
        ? `${accounts[0]?.email || accounts.length + ' accounts'} · Cap: ${dailyCapacity}/day`
        : 'No SMTP accounts configured',
      badge: isHealthy ? 'Fail-Closed' : 'Offline',
      badgeColor: isHealthy ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' : 'bg-rose-500/20 text-rose-300 border-rose-500/30',
      icon: isHealthy ? ShieldCheck : ShieldAlert,
      iconColor: isHealthy ? 'text-cyan-400' : 'text-rose-400',
      iconBg: isHealthy ? 'bg-cyan-500/10 border-cyan-500/20' : 'bg-rose-500/10 border-rose-500/20',
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
            <div className="absolute top-0 right-0 w-28 h-28 bg-blue-500/5 rounded-full blur-2xl pointer-events-none" />

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
                    {card.badge.includes('Running') && <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />}
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
