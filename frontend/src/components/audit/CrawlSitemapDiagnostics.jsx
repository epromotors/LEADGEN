import React, { useState } from 'react'
import {
  FileCode, Compass, Layers, AlertTriangle, CheckCircle2, XCircle,
  ExternalLink, ChevronRight, ShieldCheck, Search, Info
} from 'lucide-react'

export default function CrawlSitemapDiagnostics({
  audit,
  requestedUrl = '—',
}) {
  const [pageFilter, setPageFilter] = useState('')

  const siteSummary = audit?.site_summary || {}
  const crawlCoverage = siteSummary.crawl_coverage || audit?.crawl_coverage || {}
  const architecture = siteSummary.architecture || {}
  const pageAudits = audit?.page_audits || []

  // Derive origin robots URL
  let originRobots = audit?.robots_url
  if (!originRobots && requestedUrl && requestedUrl !== '—') {
    try {
      const u = new URL(requestedUrl.startsWith('http') ? requestedUrl : `https://${requestedUrl}`)
      originRobots = `${u.origin}/robots.txt`
    } catch {
      originRobots = '/robots.txt'
    }
  }

  const sitemapUrl = audit?.sitemap_url || siteSummary.sitemap_url || null
  const hasSitemap = Boolean(audit?.has_sitemap)
  const hasRobots = Boolean(audit?.has_robots)

  const sitemapCount = siteSummary.sitemap_url_count || 0
  const linkCount = siteSummary.link_discovered_count || 0
  const totalDiscovered = siteSummary.total_discovered_count || (sitemapCount + linkCount) || pageAudits.length || 1
  const totalAudited = siteSummary.total_pages || pageAudits.length || 1
  const crawlLimitHit = Boolean(siteSummary.crawl_limit_hit)
  const explanation = siteSummary.discovery_explanation || 'Bounded multi-source crawl completed.'

  // Filtered pages
  const filteredPages = pageAudits.filter(p => {
    if (!pageFilter.trim()) return true
    const q = pageFilter.toLowerCase()
    return (
      (p.url || '').toLowerCase().includes(q) ||
      (p.title || '').toLowerCase().includes(q) ||
      (p.h1 || '').toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-6">
      {/* ── 1. Origin Robots & XML Sitemap Diagnostics Cards ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Robots.txt Discovery Card */}
        <div className="card-elevated p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <FileCode size={16} className="text-blue-400" />
                <h4 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
                  Origin Robots.txt Resolution
                </h4>
              </div>
              <span className={`badge ${hasRobots ? 'badge-green' : 'badge-yellow'} text-[10px]`}>
                {hasRobots ? 'Origin Root Validated' : 'Not Declared (Allow All)'}
              </span>
            </div>

            <div className="url-badge text-blue-200 mb-3 select-all">
              {originRobots}
            </div>

            <p className="text-xs text-slate-300 leading-relaxed mb-2">
              Robots.txt is resolved strictly from the origin root (scheme + hostname), preventing sub-path crawler misdirection.
            </p>
          </div>

          <div className="pt-3 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
            <span>Directive check: <strong className="text-slate-200">{hasRobots ? 'Parsed' : 'Default Allow'}</strong></span>
            {originRobots && originRobots.startsWith('http') && (
              <a
                href={originRobots}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:text-blue-300 flex items-center gap-1 font-semibold"
              >
                Inspect File <ExternalLink size={11} />
              </a>
            )}
          </div>
        </div>

        {/* XML Sitemap Validation Card */}
        <div className="card-elevated p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <FileCode size={16} className="text-purple-400" />
                <h4 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
                  XML Sitemap Discovery & Validation
                </h4>
              </div>
              <span className={`badge ${hasSitemap ? 'badge-green' : 'badge-yellow'} text-[10px]`}>
                {hasSitemap ? 'Verified XML (<urlset>)' : 'Missing XML Sitemap'}
              </span>
            </div>

            <div className="url-badge text-purple-200 mb-3 select-all">
              {sitemapUrl || 'None discovered in robots.txt or root'}
            </div>

            <p className="text-xs text-slate-300 leading-relaxed mb-2">
              {hasSitemap
                ? `Valid XML format confirmed with ${sitemapCount} declared URLs. Soft-200 HTML error pages were strictly filtered.`
                : 'No XML sitemap found at standard locations or in robots.txt. Crawlers must rely entirely on page links.'}
            </p>
          </div>

          <div className="pt-3 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
            <span>Declared URLs: <strong className="text-slate-200">{sitemapCount}</strong></span>
            {sitemapUrl && sitemapUrl.startsWith('http') && (
              <a
                href={sitemapUrl}
                target="_blank"
                rel="noreferrer"
                className="text-purple-400 hover:text-purple-300 flex items-center gap-1 font-semibold"
              >
                Inspect Sitemap <ExternalLink size={11} />
              </a>
            )}
          </div>
        </div>
      </div>

      {/* ── 2. Crawl Discovery Funnel & Coverage Outcome ── */}
      <div className="card-elevated p-5">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-4 pb-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Compass size={17} className="text-emerald-400" />
            <h3 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
              Crawl Discovery Outcome & Coverage
            </h3>
          </div>
          <span className="text-xs text-slate-400">
            Audit Lifecycle: <strong className="text-emerald-400">{crawlCoverage.status || 'COMPLETE'}</strong>
          </span>
        </div>

        {/* Funnel Metrics Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
            <span className="text-[10px] uppercase font-bold text-slate-500 block mb-1">
              Total Discovered URLs
            </span>
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-black text-slate-100">{totalDiscovered}</span>
              <span className="text-[10px] text-slate-500">discovered</span>
            </div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
            <span className="text-[10px] uppercase font-bold text-slate-500 block mb-1">
              Pages Fully Audited
            </span>
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-black text-emerald-400">{totalAudited}</span>
              <span className="text-[10px] text-slate-500">audited</span>
            </div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
            <span className="text-[10px] uppercase font-bold text-slate-500 block mb-1">
              Discovery Sources
            </span>
            <div className="flex flex-col text-[11px] text-slate-300">
              <span>Sitemap: <strong className="text-purple-300">{sitemapCount}</strong></span>
              <span>In-page links: <strong className="text-blue-300">{linkCount}</strong></span>
            </div>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
            <span className="text-[10px] uppercase font-bold text-slate-500 block mb-1">
              Coverage Status
            </span>
            <div className="flex items-center gap-1.5 mt-1">
              {crawlLimitHit ? (
                <span className="badge badge-yellow text-[10px] font-bold">
                  Bounded at Cap ({totalAudited} pages)
                </span>
              ) : (
                <span className="badge badge-green text-[10px] font-bold">
                  100% Full Discovery
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Discovery Explanation Banner */}
        <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-lg flex items-start gap-2.5">
          <Info size={15} className="text-blue-400 shrink-0 mt-0.5" />
          <div className="text-xs text-slate-300 leading-relaxed">
            <span className="font-bold text-slate-200">Discovery Narrative: </span>
            {explanation}
          </div>
        </div>
      </div>

      {/* ── 3. Site Architecture Classification Card (If Available) ── */}
      {architecture && architecture.architecture && (
        <div className="card-elevated p-5">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-4 pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Layers size={17} className="text-sky-400" />
              <h3 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
                Site Architecture Classification
              </h3>
            </div>
            <div className="flex items-center gap-2">
              <span className={`badge text-[10px] font-black uppercase ${
                architecture.architecture === 'single_page'
                  ? 'badge-green'
                  : architecture.architecture === 'hybrid'
                  ? 'badge-yellow'
                  : 'badge-blue'
              }`}>
                {architecture.architecture.replace('_', ' ')} ARCHITECTURE
              </span>
              <span className="text-[10px] text-slate-400 bg-slate-800 px-2 py-0.5 rounded font-bold">
                {architecture.confidence?.toUpperCase()} CONFIDENCE
              </span>
            </div>
          </div>

          <p className="text-xs text-slate-300 leading-relaxed mb-4">
            {architecture.summary}
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800 text-center">
              <span className="text-[10px] text-slate-500 uppercase block font-bold">Distinct Docs</span>
              <strong className="text-base text-slate-200">{architecture.distinct_document_count || 1}</strong>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800 text-center">
              <span className="text-[10px] text-slate-500 uppercase block font-bold">In-Page Sections</span>
              <strong className="text-base text-sky-400">{architecture.section_count || 0}</strong>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800 text-center">
              <span className="text-[10px] text-slate-500 uppercase block font-bold">Section Anchors</span>
              <strong className="text-base text-purple-400">{architecture.section_anchor_links_count || 0}</strong>
            </div>
            <div className="bg-slate-950/60 p-2.5 rounded border border-slate-800 text-center">
              <span className="text-[10px] text-slate-500 uppercase block font-bold">Distinct Routes</span>
              <strong className="text-base text-emerald-400">{architecture.distinct_document_count || 1}</strong>
            </div>
          </div>

          {/* Sections List */}
          {architecture.sections?.length > 0 && (
            <div>
              <span className="text-[11px] font-bold text-slate-400 block mb-2 uppercase tracking-wider">
                Identified Architecture Sections:
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                {architecture.sections.map((sec, idx) => (
                  <div key={idx} className="bg-slate-950/60 p-2 rounded border border-slate-800/80 text-xs flex items-center justify-between">
                    <span className="font-mono text-sky-300 text-[11px] truncate">
                      {sec.id ? `#${sec.id}` : sec.tag || `Section ${idx + 1}`}
                    </span>
                    <span className="text-[10px] text-slate-400 bg-slate-900 px-1.5 py-0.5 rounded">
                      {sec.purpose || 'content'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 4. Crawled Pages Breakdown Table ── */}
      {pageAudits.length > 0 && (
        <div className="card-elevated p-5">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-4 pb-3 border-b border-slate-800">
            <h4 className="text-xs font-bold text-slate-200 tracking-wide uppercase">
              Audited Pages Breakdown ({pageAudits.length} Document{pageAudits.length > 1 ? 's' : ''})
            </h4>
            <div className="relative w-64">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                placeholder="Filter pages..."
                value={pageFilter}
                onChange={e => setPageFilter(e.target.value)}
                className="input text-xs py-1 pl-8 w-full"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/80 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-3">Page URL</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Page Title</th>
                  <th className="py-2.5 px-3">H1 Heading</th>
                  <th className="py-2.5 px-3 text-right">Issues Found</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {filteredPages.map((page, idx) => {
                  const issueCount = Array.isArray(page.issues) ? page.issues.length : page.issue_count || 0
                  return (
                    <tr key={idx} className="hover:bg-slate-900/40 transition">
                      <td className="py-2.5 px-3 font-mono text-[11px] text-blue-300 max-w-xs truncate" title={page.url}>
                        {idx === 0 ? '🏠 ' : '📄 '}
                        {page.url}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`badge ${page.status_code === 200 || !page.status_code ? 'badge-green' : 'badge-red'} text-[10px]`}>
                          HTTP {page.status_code || 200}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-slate-300 max-w-xs truncate" title={page.title || '—'}>
                        {page.title || '—'}
                      </td>
                      <td className="py-2.5 px-3 text-slate-400 max-w-xs truncate" title={page.h1 || '—'}>
                        {page.h1 || '—'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-bold">
                        <span className={issueCount > 0 ? 'text-amber-400' : 'text-emerald-400'}>
                          {issueCount}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
