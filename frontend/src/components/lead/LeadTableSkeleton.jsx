import React from 'react'

export default function LeadTableSkeleton({ rows = 6 }) {
  return (
    <div className="space-y-2 p-4 animate-pulse">
      {[...Array(rows)].map((_, i) => (
        <div
          key={i}
          className="h-14 bg-slate-900/70 border border-slate-800/60 rounded-lg flex items-center px-4 justify-between gap-4"
        >
          <div className="w-5 h-5 bg-slate-800 rounded" />
          <div className="w-40 h-4 bg-slate-800 rounded" />
          <div className="w-48 h-4 bg-slate-800/80 rounded hidden sm:block" />
          <div className="w-32 h-4 bg-slate-800/60 rounded hidden md:block" />
          <div className="w-20 h-5 bg-slate-800 rounded-full" />
          <div className="w-24 h-4 bg-slate-800/60 rounded hidden lg:block" />
          <div className="w-20 h-7 bg-slate-800 rounded" />
        </div>
      ))}
    </div>
  )
}
