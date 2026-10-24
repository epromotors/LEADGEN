import React from 'react'
import { Link } from 'react-router-dom'
import { Globe, Pencil, Search, Trash2, ArrowRight, AlertTriangle } from 'lucide-react'
import {
  LifecycleBadge,
  VerificationBadge,
  AssociationBadge,
  WebsiteStatusBadge,
  SkippedReasonBadge,
} from './LeadStatusBadge'

export default function LeadRowMobileCard({
  lead,
  isSelected,
  onToggleSelect,
  onEdit,
  onAudit,
  onDelete,
  isAuditing,
}) {
  const looksScraped =
    lead.business_name.includes('|') ||
    lead.business_name.includes(' - ') ||
    lead.business_name.length > 60

  return (
    <div
      className={`card-elevated p-4 transition-all duration-150 ${
        isSelected ? 'border-blue-500/50 bg-blue-950/10' : ''
      }`}
    >
      {/* Top row: Checkbox, Name, Status */}
      <div className="flex items-start justify-between gap-3 mb-2.5">
        <div className="flex items-start gap-2.5 min-w-0">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(lead.id)}
            className="w-4 h-4 rounded mt-0.5 accent-blue-600 cursor-pointer"
          />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-xs font-bold text-slate-100 truncate" title={lead.business_name}>
                {lead.business_name}
              </span>
              {looksScraped && (
                <span title="Name contains tagline delimiters" className="text-amber-400 text-xs">
                  ⚠️
                </span>
              )}
            </div>
            <p className="text-[11px] text-slate-400 font-mono truncate mt-0.5">
              {lead.email}
            </p>
          </div>
        </div>

        <LifecycleBadge
          status={lead.status}
          lastEmailedAt={lead.last_emailed_at}
          isAuditing={isAuditing}
        />
      </div>

      {/* Website & Badges */}
      <div className="space-y-1.5 mb-3 pt-2 border-t border-slate-800/80 text-xs">
        {lead.website ? (
          <div className="flex items-center gap-2">
            <a
              href={lead.website}
              target="_blank"
              rel="noreferrer"
              className="text-blue-400 hover:text-blue-300 font-mono text-[11px] flex items-center gap-1 truncate max-w-[200px]"
            >
              <Globe size={11} className="shrink-0" />
              {lead.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
            </a>
            <WebsiteStatusBadge
              status={lead.website_association_status}
              candidates={lead.website_candidates}
            />
          </div>
        ) : (
          <span className="text-slate-500 italic text-[11px]">No website URL</span>
        )}

        {/* Verification & Association Pills */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <VerificationBadge
            status={lead.email_verification_status}
            isQuarantined={lead.is_quarantined}
            quarantineReason={lead.quarantine_reason}
          />
          <AssociationBadge status={lead.email_business_association_status} />
          {lead.audit_error?.startsWith('SITE_STATUS:') && (
            <SkippedReasonBadge auditError={lead.audit_error} />
          )}
        </div>

        {/* Quarantine notice if active */}
        {lead.is_quarantined && (
          <div className="p-2 rounded bg-rose-950/20 border border-rose-900/30 text-[10px] text-rose-300 leading-tight">
            <span className="font-bold">Quarantined:</span>{' '}
            {lead.quarantine_reason || lead.email_association_reason || 'Safety hold'}
          </div>
        )}
      </div>

      {/* Footer: Date & Action buttons */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[11px]">
        <span className="text-slate-500">
          {new Date(lead.created_at).toLocaleDateString()}
        </span>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onEdit(lead)}
            className="p-1.5 text-slate-300 hover:text-white rounded bg-slate-800 hover:bg-slate-700"
            title="Edit lead"
          >
            <Pencil size={13} />
          </button>
          <button
            onClick={() => onAudit(lead.id)}
            disabled={isAuditing}
            className="p-1.5 text-blue-300 hover:text-white rounded bg-blue-900/40 hover:bg-blue-800/60 disabled:opacity-40"
            title="Run Audit"
          >
            <Search size={13} />
          </button>
          {lead.status === 'audited' && (
            <Link
              to="/audits"
              className="p-1.5 text-emerald-300 hover:text-white rounded bg-emerald-950/40 hover:bg-emerald-900/60"
              title="View in Audits workspace"
            >
              <ArrowRight size={13} />
            </Link>
          )}
          <button
            onClick={() => onDelete(lead.id)}
            className="p-1.5 text-rose-400 hover:text-white rounded bg-rose-950/40 hover:bg-rose-900/60"
            title="Delete lead"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  )
}
