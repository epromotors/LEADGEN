import React from 'react'

export default function InboxSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* KPI Cards Skeleton */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card-elevated p-5 h-28 flex flex-col justify-between">
            <div className="flex justify-between items-center">
              <div className="h-3 w-24 bg-slate-800 rounded" />
              <div className="h-8 w-8 bg-slate-800 rounded-lg" />
            </div>
            <div className="h-7 w-20 bg-slate-800 rounded mt-2" />
            <div className="h-2.5 w-32 bg-slate-800/60 rounded" />
          </div>
        ))}
      </div>

      {/* Table Skeleton */}
      <div className="card-elevated p-0 overflow-hidden border border-slate-800">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/50">
          <div className="h-4 w-36 bg-slate-800 rounded" />
          <div className="h-8 w-48 bg-slate-800 rounded" />
        </div>
        <div className="divide-y divide-slate-800/60">
          {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className="p-4 flex items-center justify-between gap-4">
              <div className="space-y-1.5">
                <div className="h-4 w-40 bg-slate-800 rounded" />
                <div className="h-3 w-28 bg-slate-800/60 rounded" />
              </div>
              <div className="h-4 w-48 bg-slate-800 rounded" />
              <div className="h-5 w-20 bg-slate-800 rounded-full" />
              <div className="h-7 w-40 bg-slate-800 rounded" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
