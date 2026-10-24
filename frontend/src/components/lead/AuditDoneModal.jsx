import React from 'react'
import { CheckCircle2, ArrowRight } from 'lucide-react'

export default function AuditDoneModal({ count, onOk }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4"
    >
      <div className="card-elevated w-full max-w-sm p-6 text-center shadow-2xl border border-slate-700/80 animate-in fade-in zoom-in-95 duration-200">
        <div className="w-16 h-16 rounded-full bg-emerald-500/10 border-2 border-emerald-500/40 flex items-center justify-center mx-auto mb-4 text-emerald-400">
          <CheckCircle2 size={32} />
        </div>
        <h3 className="text-lg font-bold text-slate-100 mb-1">
          Audit Batch Complete!
        </h3>
        <p className="text-xs text-slate-400 leading-relaxed mb-6">
          {count === 1
            ? '1 lead website was audited and verified against the factor contract.'
            : `${count.toLocaleString()} lead websites were audited and verified against the factor contract.`}
        </p>
        <button
          onClick={onOk}
          className="btn-primary w-full text-xs py-2.5 px-4 font-bold justify-center shadow-lg shadow-blue-900/30"
        >
          <span>Refresh Table</span>
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  )
}
