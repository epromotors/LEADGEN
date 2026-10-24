import React from 'react'
import { ShieldCheck, ShieldAlert, CheckCircle2, Clock, AlertTriangle, AlertCircle, RefreshCw } from 'lucide-react'

export function LifecycleBadge({ status, lastEmailedAt, isAuditing }) {
  if (isAuditing || status === 'auditing') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30">
        <span className="spinner w-2.5 h-2.5 border-amber-400 border-t-transparent" />
        Auditing…
      </span>
    )
  }

  if (status === 'emailed') {
    const formattedDate = lastEmailedAt
      ? new Date(lastEmailedAt).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }).toUpperCase()
      : null

    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-950/40 text-emerald-300 border border-emerald-800/40">
        ✉ Sent {formattedDate ? `· ${formattedDate}` : ''}
      </span>
    )
  }

  if (status === 'replied') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-teal-950/40 text-teal-300 border border-teal-800/40">
        ✔ Replied
      </span>
    )
  }

  if (status === 'audited') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-950/40 text-blue-300 border border-blue-800/40">
        Audited
      </span>
    )
  }

  // default / new
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-900 text-slate-400 border border-slate-800">
      New Intake
    </span>
  )
}

export function VerificationBadge({ status, isQuarantined, quarantineReason }) {
  const normStatus = (status || 'unverified').toLowerCase()

  if (isQuarantined) {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-950/40 text-rose-300 border border-rose-800/40"
        title={quarantineReason ? `Quarantined (${normStatus}): ${quarantineReason}` : `Quarantined (${normStatus})`}
      >
        <ShieldAlert size={11} className="text-rose-400" />
        Quarantined
      </span>
    )
  }

  if (normStatus === 'valid') {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-950/40 text-emerald-300 border border-emerald-800/40"
        title="Email address verified with valid mail routing (MX)"
      >
        <ShieldCheck size={11} className="text-emerald-400" />
        Deliverable
      </span>
    )
  }

  if (normStatus === 'disposable') {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-950/40 text-rose-300 border border-rose-800/40"
        title="Disposable / temporary email domain"
      >
        <ShieldAlert size={11} className="text-rose-400" />
        Disposable
      </span>
    )
  }

  if (normStatus === 'invalid' || normStatus === 'not_found') {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-950/40 text-rose-300 border border-rose-800/40"
        title="Mailbox does not exist or MX route failed"
      >
        <AlertCircle size={11} className="text-rose-400" />
        Invalid MX
      </span>
    )
  }

  if (normStatus === 'catch_all') {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/40 text-amber-300 border border-amber-800/40"
        title="Catch-all domain configuration"
      >
        <Clock size={11} className="text-amber-400" />
        Catch-All
      </span>
    )
  }

  if (normStatus === 'risky') {
    return (
      <span
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/40 text-amber-300 border border-amber-800/40"
        title="Deliverability risks detected"
      >
        <AlertTriangle size={11} className="text-amber-400" />
        Risky
      </span>
    )
  }

  // unverified
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700"
      title="Unverified mailbox"
    >
      Unverified
    </span>
  )
}

export function AssociationBadge({ status }) {
  if (!status) return null

  if (['matched', 'approved'].includes(status)) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-emerald-950/40 text-emerald-300 border border-emerald-800/40"
        title="Email domain matches business website domain or verified by operator approval"
      >
        Domain Match
      </span>
    )
  }

  if (status === 'external_domain_review') {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-950/40 text-amber-300 border border-amber-800/40"
        title="Review Needed: email domain differs from website domain"
      >
        Review Needed
      </span>
    )
  }

  if (status === 'unverified_association') {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-slate-800 text-slate-400 border border-slate-700"
        title="Unverified business association"
      >
        Unverified Assoc
      </span>
    )
  }

  if (status === 'mismatched_source' || status === 'mismatch_quarantined') {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-rose-950/40 text-rose-300 border border-rose-800/40"
        title="Mismatched domain source"
      >
        Mismatched
      </span>
    )
  }

  return null
}

export function WebsiteStatusBadge({ status, candidates = [] }) {
  if (!status) return null

  if (status === 'candidate_match' || (candidates && candidates.length > 0)) {
    return (
      <span
        className="text-[9px] px-1.5 py-0.5 bg-blue-500/10 text-blue-300 rounded border border-blue-500/20 font-semibold inline-flex items-center"
        title="Inferred candidate website — unverified"
      >
        Inferred — unverified
      </span>
    )
  }

  if (status === 'conflicting') {
    return (
      <span
        className="text-[9px] px-1.5 py-0.2 bg-purple-500/10 text-purple-300 rounded border border-purple-500/20 font-semibold"
        title="Conflicting candidate websites"
      >
        Conflicting
      </span>
    )
  }

  if (status === 'inconclusive') {
    return (
      <span
        className="text-[9px] px-1.5 py-0.2 bg-slate-800 text-slate-400 rounded border border-slate-700"
        title="Discovery Inconclusive"
      >
        Inconclusive
      </span>
    )
  }

  return null
}

export function SkippedReasonBadge({ auditError }) {
  if (!auditError || !auditError.startsWith('SITE_STATUS:')) return null

  const reasonTag = auditError.replace('SITE_STATUS:', '').trim().toUpperCase().replace(/_/g, ' ')

  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] text-orange-300 bg-orange-950/30 border border-orange-800/40 px-1.5 py-0.5 rounded font-mono"
      title={auditError}
    >
      <AlertTriangle size={10} className="text-orange-400" />
      {reasonTag}
    </span>
  )
}
