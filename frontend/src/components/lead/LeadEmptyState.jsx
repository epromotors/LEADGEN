import React from 'react'
import { Search, Users, RefreshCw, X } from 'lucide-react'

export default function LeadEmptyState({ isFiltered, onResetFilters }) {
  if (isFiltered) {
    return (
      <div className="py-16 px-4 text-center flex flex-col items-center justify-center">
        <div className="w-12 h-12 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-500 mb-3">
          <Search size={22} />
        </div>
        <h4 className="text-base font-bold text-slate-200 mb-1">
          No Matching Leads Found
        </h4>
        <p className="text-xs text-slate-400 max-w-sm mx-auto mb-4 leading-relaxed">
          No leads in your database match the active search term or status filter.
        </p>
        <button
          onClick={onResetFilters}
          className="btn-secondary text-xs py-1.5 px-4 font-semibold inline-flex items-center gap-1.5"
        >
          <X size={13} />
          Reset Filters &amp; Search
        </button>
      </div>
    )
  }

  return (
    <div className="py-16 px-4 text-center flex flex-col items-center justify-center">
      <div className="w-14 h-14 rounded-2xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4">
        <Users size={28} />
      </div>
      <h4 className="text-base font-bold text-slate-200 mb-1">
        Lead Workspace Is Empty
      </h4>
      <p className="text-xs text-slate-400 max-w-md mx-auto mb-3 leading-relaxed">
        Upload a CSV file with your prospect list or run an automated Bulk Discovery session to populate this workspace.
      </p>
    </div>
  )
}
