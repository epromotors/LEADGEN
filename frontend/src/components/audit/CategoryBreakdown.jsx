import React from 'react'
import { Filter, Layers, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react'

export const CANONICAL_CATEGORIES = [
  { id: 'technical',       label: 'Technical SEO',   icon: '🔧', color: '#3b82f6', weight: 18 },
  { id: 'onpage',          label: 'On-Page SEO',     icon: '📄', color: '#a855f7', weight: 16 },
  { id: 'images',          label: 'Images',          icon: '🖼️', color: '#14b8a6', weight: 7 },
  { id: 'links',           label: 'Links',           icon: '🔗', color: '#f97316', weight: 5 },
  { id: 'conversion',      label: 'Conversion',      icon: '💼', color: '#10b981', weight: 12 },
  { id: 'ux',              label: 'UI / UX',         icon: '🎨', color: '#d946ef', weight: 10 },
  { id: 'indexability',    label: 'Indexability',    icon: '🗂️', color: '#06b6d4', weight: 8 },
  { id: 'content',         label: 'Content',         icon: '✍️', color: '#8b5cf6', weight: 8 },
  { id: 'local_seo',       label: 'Local SEO',       icon: '📍', color: '#f43f5e', weight: 7 },
  { id: 'performance',     label: 'Performance',     icon: '⚡', color: '#facc15', weight: 5 },
  { id: 'schema_advanced', label: 'Schema Advanced', icon: '🧩', color: '#34d399', weight: 4 },
]

export default function CategoryBreakdown({
  audit,
  selectedCategory = 'ALL',
  onSelectCategory = () => {},
}) {
  const auditResults = audit?.audit_results || {}

  // Compute stats per category
  const categoryStats = CANONICAL_CATEGORIES.map(cat => {
    let groupResults = auditResults[cat.id]
    // Fallback for schema_advanced / schema_adv naming
    if (!groupResults && cat.id === 'schema_advanced') {
      groupResults = auditResults['schema_adv']
    }

    let pass = 0
    let warn = 0
    let fail = 0
    let total = 0
    let score = null

    if (groupResults && typeof groupResults === 'object') {
      const items = Object.values(groupResults)
      total = items.length
      items.forEach(item => {
        const status = item?.status
        if (status === 'PASS') pass++
        else if (status === 'WARN') warn++
        else if (status === 'FAIL') fail++
      })

      if (total > 0) {
        const earned = pass * 1 + warn * 0.5
        score = Math.round((earned / total) * 100)
      }
    } else if (cat.id === 'ux' && audit?.ux_score !== undefined && audit?.ux_score !== null) {
      score = audit.ux_score
    }

    return {
      ...cat,
      pass,
      warn,
      fail,
      total,
      score,
    }
  })

  return (
    <div className="card-elevated p-5 mb-6">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Layers size={17} className="text-purple-400" />
          <h3 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
            Category Breakdown (11-Axis Verified Contract)
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400">Click a category to focus findings:</span>
          {selectedCategory !== 'ALL' && (
            <button
              onClick={() => onSelectCategory('ALL')}
              className="text-xs text-blue-400 hover:text-blue-300 font-bold px-2 py-0.5 rounded bg-blue-950/60 border border-blue-800 transition"
            >
              Reset Filter (Show All)
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {/* "All Categories" pill */}
        <div
          onClick={() => onSelectCategory('ALL')}
          className={`category-pill-card flex flex-col justify-between ${
            selectedCategory === 'ALL' ? 'category-pill-card-active' : ''
          }`}
        >
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-base">📋</span>
            <span className="text-[10px] font-bold text-slate-400 bg-slate-800/80 px-1.5 py-0.5 rounded">
              All
            </span>
          </div>
          <span className="text-xs font-bold text-slate-200 block truncate">
            All 62 Factors
          </span>
          <div className="mt-2 text-[10px] text-slate-400">
            Comprehensive View
          </div>
        </div>

        {/* 11 Axis Cards */}
        {categoryStats.map(cat => {
          const isSelected = selectedCategory === cat.id
          const scoreColor =
            cat.score === null
              ? '#64748b'
              : cat.score >= 80
              ? '#22c55e'
              : cat.score >= 50
              ? '#f59e0b'
              : '#ef4444'

          return (
            <div
              key={cat.id}
              onClick={() => onSelectCategory(isSelected ? 'ALL' : cat.id)}
              className={`category-pill-card flex flex-col justify-between ${
                isSelected ? 'category-pill-card-active' : ''
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-base" title={cat.label}>{cat.icon}</span>
                <span
                  className="text-xs font-black"
                  style={{ color: scoreColor }}
                >
                  {cat.score !== null ? `${cat.score}%` : 'N/A'}
                </span>
              </div>

              <span className="text-xs font-bold text-slate-200 block truncate" title={cat.label}>
                {cat.label}
              </span>

              {/* Progress mini-bar */}
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden mt-2 mb-1.5">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${cat.score !== null ? cat.score : 0}%`,
                    backgroundColor: scoreColor,
                  }}
                />
              </div>

              {/* Micro Pass / Fail stats */}
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span className="text-slate-500 font-mono">{cat.weight}% wt</span>
                <div className="flex items-center gap-1.5">
                  {cat.pass > 0 && <span className="text-emerald-400 font-bold">{cat.pass}P</span>}
                  {cat.warn > 0 && <span className="text-amber-400 font-bold">{cat.warn}W</span>}
                  {cat.fail > 0 && <span className="text-red-400 font-bold">{cat.fail}F</span>}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
