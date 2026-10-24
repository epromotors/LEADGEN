import React, { useState } from 'react'
import { Globe, ArrowRight, FileCode, Copy, Check, ExternalLink, AlertTriangle, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'

export default function UrlIdentityBanner({
  requestedUrl = '—',
  finalUrl = '—',
  canonicalUrl = '—',
  isRedirected = false,
  isCanonicalSame = true,
  hasCanonical = false,
}) {
  const [copiedKey, setCopiedKey] = useState(null)

  const copyToClipboard = (text, key) => {
    if (!text || text === '—') return
    navigator.clipboard.writeText(text)
    setCopiedKey(key)
    toast.success(`Copied ${key} URL to clipboard`)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  // Cross-origin detection between requested and final
  let isCrossOriginRedirect = false
  try {
    if (requestedUrl !== '—' && finalUrl !== '—') {
      const reqHost = new URL(requestedUrl.startsWith('http') ? requestedUrl : `https://${requestedUrl}`).hostname
      const finHost = new URL(finalUrl.startsWith('http') ? finalUrl : `https://${finalUrl}`).hostname
      isCrossOriginRedirect = reqHost.toLowerCase() !== finHost.toLowerCase()
    }
  } catch {}

  // Canonical domain mismatch detection
  let isCanonicalCrossDomain = false
  try {
    if (finalUrl !== '—' && hasCanonical && canonicalUrl !== '—') {
      const finHost = new URL(finalUrl.startsWith('http') ? finalUrl : `https://${finalUrl}`).hostname
      const canHost = new URL(canonicalUrl.startsWith('http') ? canonicalUrl : `https://${canonicalUrl}`).hostname
      isCanonicalCrossDomain = finHost.toLowerCase() !== canHost.toLowerCase()
    }
  } catch {}

  return (
    <div className="card-elevated p-5 mb-6">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-blue-400" />
          <h3 className="text-sm font-bold text-slate-200 tracking-wide uppercase text-xs">
            URL Identity & Destination Tracking
          </h3>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {isRedirected && (
            <span className={`badge ${isCrossOriginRedirect ? 'badge-red' : 'badge-yellow'} font-semibold flex items-center gap-1`}>
              <AlertTriangle size={12} />
              {isCrossOriginRedirect ? 'Cross-Domain Redirect' : 'Internal Redirect (301/302)'}
            </span>
          )}
          {hasCanonical && !isCanonicalSame && (
            <span className={`badge ${isCanonicalCrossDomain ? 'badge-red' : 'badge-yellow'} font-semibold flex items-center gap-1`}>
              <AlertTriangle size={12} />
              {isCanonicalCrossDomain ? 'Cross-Domain Canonical' : 'Canonical Alternate'}
            </span>
          )}
          {isCanonicalSame && hasCanonical && (
            <span className="badge badge-green font-semibold">Self-Canonical Declared</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Requested Target URL */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-3 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-1.5">
                <Globe size={13} className="text-blue-400" />
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Requested Target
                </span>
              </div>
              <span className="text-[10px] text-slate-500 font-mono">Input</span>
            </div>
            <div className="url-badge text-blue-200 mb-2 select-all" title={requestedUrl}>
              {requestedUrl}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-900">
            <button
              onClick={() => copyToClipboard(requestedUrl, 'requested')}
              className="text-slate-400 hover:text-white text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
              title="Copy requested URL"
            >
              {copiedKey === 'requested' ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
              <span className="text-[11px]">{copiedKey === 'requested' ? 'Copied' : 'Copy'}</span>
            </button>
            {requestedUrl !== '—' && (
              <a
                href={requestedUrl.startsWith('http') ? requestedUrl : `https://${requestedUrl}`}
                target="_blank"
                rel="noreferrer"
                className="text-slate-400 hover:text-blue-400 text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
                title="Open in new tab"
              >
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>

        {/* Final Destination URL */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-3 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-1.5">
                <ArrowRight size={13} className={isRedirected ? 'text-amber-400' : 'text-emerald-400'} />
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Final Destination URL
                </span>
              </div>
              <span className={`text-[10px] font-bold ${isRedirected ? 'text-amber-400' : 'text-emerald-400'}`}>
                {isRedirected ? 'Redirected' : 'Direct (HTTP 200)'}
              </span>
            </div>
            <div className="url-badge text-emerald-200 mb-2 select-all" title={finalUrl}>
              {finalUrl}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-900">
            <button
              onClick={() => copyToClipboard(finalUrl, 'final')}
              className="text-slate-400 hover:text-white text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
              title="Copy final URL"
            >
              {copiedKey === 'final' ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
              <span className="text-[11px]">{copiedKey === 'final' ? 'Copied' : 'Copy'}</span>
            </button>
            {finalUrl !== '—' && (
              <a
                href={finalUrl.startsWith('http') ? finalUrl : `https://${finalUrl}`}
                target="_blank"
                rel="noreferrer"
                className="text-slate-400 hover:text-blue-400 text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
                title="Open in new tab"
              >
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>

        {/* Declared Canonical URL */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-3 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-1.5">
                <FileCode size={13} className="text-purple-400" />
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Declared Canonical
                </span>
              </div>
              <span className={`text-[10px] font-bold ${isCanonicalSame ? 'text-emerald-400' : hasCanonical ? 'text-amber-400' : 'text-slate-500'}`}>
                {isCanonicalSame ? 'Self-Canonical' : hasCanonical ? 'Alternate Specified' : 'None Declared'}
              </span>
            </div>
            <div className="url-badge text-purple-200 mb-2 select-all" title={canonicalUrl}>
              {canonicalUrl}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-900">
            {hasCanonical && (
              <button
                onClick={() => copyToClipboard(canonicalUrl, 'canonical')}
                className="text-slate-400 hover:text-white text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
                title="Copy canonical URL"
              >
                {copiedKey === 'canonical' ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                <span className="text-[11px]">{copiedKey === 'canonical' ? 'Copied' : 'Copy'}</span>
              </button>
            )}
            {canonicalUrl !== '—' && canonicalUrl.startsWith('http') && (
              <a
                href={canonicalUrl}
                target="_blank"
                rel="noreferrer"
                className="text-slate-400 hover:text-purple-400 text-xs flex items-center gap-1 p-1 rounded hover:bg-slate-800 transition"
                title="Open in new tab"
              >
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
