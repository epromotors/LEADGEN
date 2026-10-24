import React from 'react'

export default function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* Header skeleton */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="h-7 w-48 bg-slate-800 rounded-lg mb-2" />
          <div className="h-4 w-72 bg-slate-800/60 rounded" />
        </div>
        <div className="flex gap-2">
          <div className="h-9 w-24 bg-slate-800 rounded-lg" />
          <div className="h-9 w-28 bg-slate-800 rounded-lg" />
        </div>
      </div>

      {/* KPI cards skeleton */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card-elevated p-5 space-y-3">
            <div className="flex justify-between items-center">
              <div className="h-3 w-20 bg-slate-800 rounded" />
              <div className="h-8 w-8 bg-slate-800 rounded-lg" />
            </div>
            <div className="h-8 w-16 bg-slate-700 rounded-md" />
            <div className="h-3 w-32 bg-slate-800/60 rounded" />
          </div>
        ))}
      </div>

      {/* 2-column breakdown skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card-elevated p-6 space-y-4">
          <div className="h-5 w-40 bg-slate-800 rounded" />
          <div className="h-3 w-full bg-slate-800 rounded-full" />
          <div className="grid grid-cols-3 gap-3">
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} className="h-16 bg-slate-900/80 rounded-lg" />
            ))}
          </div>
        </div>
        <div className="card-elevated p-6 space-y-4">
          <div className="h-5 w-44 bg-slate-800 rounded" />
          <div className="h-20 bg-slate-900/80 rounded-lg" />
          <div className="h-24 bg-slate-900/80 rounded-lg" />
        </div>
      </div>

      {/* Activity and recent leads skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card-elevated p-6 space-y-3">
          <div className="h-5 w-36 bg-slate-800 rounded mb-4" />
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-12 bg-slate-900/80 rounded-lg" />
          ))}
        </div>
        <div className="card-elevated p-6 space-y-3">
          <div className="h-5 w-36 bg-slate-800 rounded mb-4" />
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-12 bg-slate-900/80 rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  )
}
