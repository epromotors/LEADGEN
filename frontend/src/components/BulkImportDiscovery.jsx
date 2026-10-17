import { useState, useEffect, useRef } from 'react'
import {
  Upload, FileText, CheckCircle2, AlertTriangle, X, Play, Pause, Square,
  Download, RefreshCw, Layers, ShieldCheck, ChevronDown, ChevronUp, Globe,
  Mail, Phone, ExternalLink, HelpCircle, AlertCircle, Database
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  getDiscoveryPresets,
  getDiscoveryProviders,
  uploadDiscoveryTxt,
  previewDiscovery,
  createDiscoveryJob,
  getDiscoveryJobs,
  getDiscoveryJob,
  pauseDiscoveryJob,
  resumeDiscoveryJob,
  cancelDiscoveryJob,
  getDiscoveryExportUrl
} from '../api/client'

export default function BulkImportDiscovery({ onLeadsImported }) {
  const [isOpen, setIsOpen] = useState(true)
  const [keywords, setKeywords] = useState(() => {
    try {
      const saved = localStorage.getItem('leadgen_custom_keywords')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [locations, setLocations] = useState(() => {
    try {
      const saved = localStorage.getItem('leadgen_custom_locations')
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [keywordsMeta, setKeywordsMeta] = useState(null)
  const [locationsMeta, setLocationsMeta] = useState(null)
  const [mergeMode, setMergeMode] = useState(true)
  const [batchOffset, setBatchOffset] = useState(0)
  const [mode, setMode] = useState('uploaded_only')
  const [budget, setBudget] = useState(100)
  const [presets, setPresets] = useState({ keywords: [], locations: [] })
  const [providers, setProviders] = useState({})
  const [preview, setPreview] = useState(null)
  const [activeJob, setActiveJob] = useState(null)
  const [allJobs, setAllJobs] = useState([])
  const [showProviders, setShowProviders] = useState(false)
  const [loading, setLoading] = useState(false)
  const [uploadingKw, setUploadingKw] = useState(false)
  const [uploadingLoc, setUploadingLoc] = useState(false)

  const kwFileRef = useRef(null)
  const locFileRef = useRef(null)
  const pollTimerRef = useRef(null)

  // ─── Persistence to localStorage ───────────────────────────────────────────
  useEffect(() => {
    try {
      localStorage.setItem('leadgen_custom_keywords', JSON.stringify(keywords))
    } catch {}
  }, [keywords])

  useEffect(() => {
    try {
      localStorage.setItem('leadgen_custom_locations', JSON.stringify(locations))
    } catch {}
  }, [locations])

  // ─── Fetch Presets & Providers on Mount ─────────────────────────────────────
  useEffect(() => {
    fetchPresetsAndProviders()
    fetchJobs()
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [])

  async function fetchPresetsAndProviders() {
    try {
      const [presetsRes, provRes] = await Promise.all([
        getDiscoveryPresets(),
        getDiscoveryProviders()
      ])
      setPresets(presetsRes.data || { keywords: [], locations: [] })
      setProviders(provRes.data || {})
    } catch {
      // Non-fatal
    }
  }

  async function fetchJobs() {
    try {
      const res = await getDiscoveryJobs()
      const list = res.data || []
      setAllJobs(list)
      const running = list.find(j => j.status === 'running' || j.status === 'paused')
      if (running) {
        setActiveJob(running)
      } else if (list.length > 0 && !activeJob) {
        setActiveJob(list[0])
      }
    } catch {
      // Non-fatal
    }
  }

  // ─── Recalculate Preview whenever inputs change ───────────────────────────
  useEffect(() => {
    const kws = mode === 'presets_only' ? presets.keywords : keywords
    const locs = mode === 'presets_only' ? presets.locations : locations

    if (kws.length === 0 && locs.length === 0 && mode !== 'presets_only') {
      setPreview(null)
      return
    }

    previewDiscovery({
      keywords,
      locations,
      mode,
      custom_budget: Number(budget) || null,
      batch_offset: Number(batchOffset) || 0
    })
      .then(res => setPreview(res.data))
      .catch(() => {})
  }, [keywords, locations, mode, budget, presets, batchOffset])

  // ─── Polling for Active Job ────────────────────────────────────────────────
  useEffect(() => {
    if (!activeJob || (activeJob.status !== 'running' && activeJob.status !== 'pending')) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
      return
    }

    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await getDiscoveryJob(activeJob.job_id)
        setActiveJob(res.data)
        if (res.data.status === 'completed' || res.data.status === 'cancelled') {
          clearInterval(pollTimerRef.current)
          toast.success(`Discovery job ${res.data.job_id} finished!`)
          fetchJobs()
          if (onLeadsImported) onLeadsImported()
        }
      } catch {
        // Non-fatal
      }
    }, 2000)

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current)
    }
  }, [activeJob?.job_id, activeJob?.status])

  function mergeLists(existing, incoming) {
    const seen = new Set(existing.map(x => x.toLowerCase()))
    const merged = [...existing]
    let addedCount = 0
    for (const item of incoming) {
      if (!seen.has(item.toLowerCase())) {
        seen.add(item.toLowerCase())
        merged.push(item)
        addedCount++
      }
    }
    return { merged, addedCount, existingCount: existing.length }
  }

  // ─── Upload Handlers ───────────────────────────────────────────────────────
  async function handleFileUpload(e, fileType) {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.name.toLowerCase().endsWith('.txt')) {
      toast.error('Only .txt text files are accepted.')
      return
    }

    const isKw = fileType === 'keywords'
    if (isKw) setUploadingKw(true)
    else setUploadingLoc(true)

    const t = toast.loading(`Uploading and validating ${file.name}…`)
    try {
      const res = await uploadDiscoveryTxt(file, fileType)
      const data = res.data

      let finalEntries = data.entries
      let addedMsg = ''

      if (mergeMode) {
        const currentList = isKw ? keywords : locations
        if (currentList.length > 0) {
          const { merged, addedCount } = mergeLists(currentList, data.entries)
          finalEntries = merged
          addedMsg = ` (merged ${addedCount} new with ${currentList.length} existing)`
        }
      }

      toast.success(
        `Parsed ${data.valid_count} valid ${fileType}${addedMsg}. Skipped ${data.ignored_count} blanks/comments and ${data.duplicate_count} duplicates.`,
        { id: t }
      )

      if (data.invalid_entries && data.invalid_entries.length > 0) {
        toast((toastObj) => (
          <div className="text-xs">
            <p className="font-bold text-amber-400 mb-1">
              {data.invalid_entries.length} invalid items excluded:
            </p>
            <ul className="list-disc pl-4 max-h-24 overflow-y-auto">
              {data.invalid_entries.slice(0, 5).map((inv, idx) => (
                <li key={idx} className="text-slate-300">{inv}</li>
              ))}
              {data.invalid_entries.length > 5 && (
                <li className="text-slate-400">…and {data.invalid_entries.length - 5} more</li>
              )}
            </ul>
          </div>
        ), { duration: 6000, icon: '⚠️' })
      }

      if (isKw) {
        setKeywords(finalEntries)
        setKeywordsMeta(data)
        if (mode === 'presets_only') setMode('uploaded_only')
      } else {
        setLocations(finalEntries)
        setLocationsMeta(data)
        if (mode === 'presets_only') setMode('uploaded_only')
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'File validation failed', { id: t })
    } finally {
      if (isKw) setUploadingKw(false)
      else setUploadingLoc(false)
      e.target.value = ''
    }
  }

  function removeKeyword(idx) {
    setKeywords(prev => prev.filter((_, i) => i !== idx))
  }

  function removeLocation(idx) {
    setLocations(prev => prev.filter((_, i) => i !== idx))
  }

  // ─── Job Actions ───────────────────────────────────────────────────────────
  async function handleStartJob() {
    if (!preview || preview.total_combinations === 0) {
      toast.error('Please upload or select at least one keyword and location.')
      return
    }

    if (preview.exceeds_safety_limit) {
      toast.error(
        `Combinations budget (${preview.effective_budget}) exceeds safety limit (${preview.max_allowed_combinations}). Adjust entries or lower your budget.`
      )
      return
    }

    setLoading(true)
    const t = toast.loading('Initializing lead discovery job…')
    try {
      const res = await createDiscoveryJob({
        keywords,
        locations,
        mode,
        budget: Number(budget) || null,
        batch_offset: Number(batchOffset) || 0
      })
      toast.success(`Job ${res.data.job_id} started!`, { id: t })
      setActiveJob(res.data)
      fetchJobs()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to start job', { id: t })
    } finally {
      setLoading(false)
    }
  }

  async function handlePauseJob(jobId) {
    try {
      const res = await pauseDiscoveryJob(jobId)
      setActiveJob(res.data)
      toast.success('Job paused')
      fetchJobs()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to pause')
    }
  }

  async function handleResumeJob(jobId) {
    try {
      const res = await resumeDiscoveryJob(jobId)
      setActiveJob(res.data)
      toast.success('Job resumed')
      fetchJobs()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to resume')
    }
  }

  async function handleCancelJob(jobId) {
    if (!confirm('Are you sure you want to cancel this discovery job?')) return
    try {
      const res = await cancelDiscoveryJob(jobId)
      setActiveJob(res.data)
      toast.success('Job cancelled')
      fetchJobs()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to cancel')
    }
  }

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl mb-8 overflow-hidden backdrop-blur-md shadow-2xl transition-all">
      {/* ── Header ───────────────────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between p-6 bg-gradient-to-r from-slate-900 via-slate-800/80 to-slate-900 border-b border-slate-800/80 cursor-pointer"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
            <Layers size={22} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white tracking-wide">
                Bulk Keyword & Location Import
              </h2>
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                Automated Fallback Discovery
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Upload .txt files for multi-niche discovery across authorized APIs with HTTP/Playwright fallback.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setShowProviders(!showProviders)
            }}
            className="text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
          >
            <ShieldCheck size={14} className="text-emerald-400" />
            Providers & Failover
          </button>
          <div className="text-slate-400 hover:text-white transition-colors">
            {isOpen ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
          </div>
        </div>
      </div>

      {isOpen && (
        <div className="p-6 space-y-6">
          {/* ── Providers & Compliance Drawer ───────────────────────────────── */}
          {showProviders && (
            <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 text-xs text-slate-300 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                  <ShieldCheck size={16} className="text-emerald-400" />
                  Provider Failover Status & Compliance Controls
                </span>
                <span className="text-[11px] text-slate-400">
                  Strictly respects robots.txt & terms of service
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
                {Object.entries(providers).map(([pName, pData]) => {
                  const statusColors = {
                    available: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
                    rate_limited: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
                    quota_exhausted: 'bg-red-500/10 text-red-400 border-red-500/30',
                    authentication_error: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
                    temporarily_unavailable: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
                    disabled: 'bg-slate-800 text-slate-400 border-slate-700',
                    no_results: 'bg-slate-800 text-slate-400 border-slate-700',
                  }
                  return (
                    <div
                      key={pName}
                      className="p-2.5 rounded-lg bg-slate-900 border border-slate-800/80 flex flex-col justify-between"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium capitalize text-slate-200">{pName.replace('_', ' ')}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border uppercase font-bold ${statusColors[pData.status] || 'bg-slate-800 text-slate-400'}`}>
                          {pData.status}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-400 flex items-center justify-between">
                        <span>Configured: {pData.configured ? 'Yes' : 'No'}</span>
                        {pData.key_masked && <span className="font-mono text-[10px] text-slate-400">{pData.key_masked}</span>}
                      </div>
                      {pData.last_error && (
                        <p className="text-[10px] text-amber-400/90 mt-1 truncate" title={pData.last_error}>
                          {pData.last_error}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
              <div className="p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-300 text-[11px] flex items-start gap-2">
                <AlertCircle size={15} className="mt-0.5 shrink-0 text-amber-400" />
                <span>
                  <strong>Authorized Source Policy:</strong> Direct scraping of third-party Maps or directories without API authorization is prohibited. Discovery uses configured authorized APIs, public search fallbacks, and safe HTTP inspection of the candidate business's own website.
                </span>
              </div>
            </div>
          )}

          {/* ── Import & Merge Configuration ─────────────────────────────── */}
          <div className="p-3.5 rounded-xl bg-slate-800/20 border border-slate-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2">
              <input
                id="merge-mode-toggle"
                type="checkbox"
                checked={mergeMode}
                onChange={(e) => setMergeMode(e.target.checked)}
                className="w-4 h-4 rounded text-blue-600 bg-slate-900 border-slate-700 focus:ring-blue-500 cursor-pointer"
              />
              <label htmlFor="merge-mode-toggle" className="text-slate-200 font-medium cursor-pointer select-none">
                Merge imported entries with existing lists (preserve existing user entries)
              </label>
            </div>
            <span className="text-slate-400 text-[11px]">
              Formats: Niche pipe lists (<code>Category | kw1 | kw2</code>), <code>REGION:City</code>, UTF-8 BOM supported.
            </span>
          </div>

          {/* ── Two Upload Controls ─────────────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Control A: Keywords */}
            <div className="p-5 rounded-xl bg-slate-800/40 border border-slate-800 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                    <FileText size={16} className="text-blue-400" />
                    A. Upload Keywords (.txt)
                  </label>
                  {keywords.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setKeywords([])}
                      className="text-xs text-rose-400 hover:text-rose-300"
                    >
                      Clear ({keywords.length})
                    </button>
                  )}
                </div>
                <p className="text-xs text-slate-400 mb-4">
                  Multi-niche (<code>Category | kw1 | kw2</code>) or single per line. Comments with <code>#</code> ignored.
                </p>

                <input
                  ref={kwFileRef}
                  type="file"
                  accept=".txt"
                  className="hidden"
                  onChange={(e) => handleFileUpload(e, 'keywords')}
                />

                <div
                  onClick={() => kwFileRef.current?.click()}
                  className="border-2 border-dashed border-slate-700 hover:border-blue-500 rounded-xl p-4 text-center cursor-pointer bg-slate-900/50 hover:bg-slate-900 transition-all mb-3"
                >
                  <Upload size={20} className="mx-auto text-blue-400 mb-1" />
                  <span className="text-xs font-medium text-slate-300 block">
                    {uploadingKw ? 'Uploading…' : 'Click to select keywords.txt'}
                  </span>
                  <span className="text-[10px] text-slate-400">Max 1,000 entries · UTF-8 · 1 MB</span>
                </div>

                {keywordsMeta && (
                  <div className="text-[11px] text-slate-400 bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 mb-3 flex flex-wrap gap-x-3 gap-y-1">
                    <span className="text-emerald-400 font-semibold">✓ {keywordsMeta.valid_count} Valid</span>
                    <span>• {keywordsMeta.ignored_count} Blanks/Comments</span>
                    <span>• {keywordsMeta.duplicate_count} Duplicates</span>
                    {keywordsMeta.rejected_count > 0 && <span className="text-amber-400">• {keywordsMeta.rejected_count} Rejected</span>}
                  </div>
                )}

                {keywordsMeta?.invalid_entries?.length > 0 && (
                  <div className="text-[11px] bg-amber-500/10 border border-amber-500/20 p-2.5 rounded-lg mb-3 text-amber-300">
                    <span className="font-semibold block mb-0.5">⚠️ {keywordsMeta.invalid_entries.length} excluded entries:</span>
                    <span className="text-slate-400 truncate block">{keywordsMeta.invalid_entries.slice(0, 3).join(', ')}</span>
                  </div>
                )}
              </div>

              {/* Keywords Tag Preview */}
              {keywords.length > 0 && (
                <div className="max-h-28 overflow-y-auto pr-1 flex flex-wrap gap-1.5 pt-2 border-t border-slate-800/80">
                  {keywords.map((kw, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] bg-blue-500/10 text-blue-300 border border-blue-500/20"
                    >
                      {kw}
                      <button
                        type="button"
                        onClick={() => removeKeyword(i)}
                        className="hover:text-rose-400"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Control B: Locations */}
            <div className="p-5 rounded-xl bg-slate-800/40 border border-slate-800 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                    <Globe size={16} className="text-emerald-400" />
                    B. Upload Locations (.txt)
                  </label>
                  {locations.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setLocations([])}
                      className="text-xs text-rose-400 hover:text-rose-300"
                    >
                      Clear ({locations.length})
                    </button>
                  )}
                </div>
                <p className="text-xs text-slate-400 mb-4">
                  Target locations (e.g. <code>IN:Roorkee</code>, <code>Roorkee, Uttarakhand</code>, <code>Austin, Texas</code>).
                </p>

                <input
                  ref={locFileRef}
                  type="file"
                  accept=".txt"
                  className="hidden"
                  onChange={(e) => handleFileUpload(e, 'locations')}
                />

                <div
                  onClick={() => locFileRef.current?.click()}
                  className="border-2 border-dashed border-slate-700 hover:border-emerald-500 rounded-xl p-4 text-center cursor-pointer bg-slate-900/50 hover:bg-slate-900 transition-all mb-3"
                >
                  <Upload size={20} className="mx-auto text-emerald-400 mb-1" />
                  <span className="text-xs font-medium text-slate-300 block">
                    {uploadingLoc ? 'Uploading…' : 'Click to select locations.txt'}
                  </span>
                  <span className="text-[10px] text-slate-400">Max 1,000 entries · UTF-8 · 1 MB</span>
                </div>

                {locationsMeta && (
                  <div className="text-[11px] text-slate-400 bg-slate-900/80 p-2.5 rounded-lg border border-slate-800 mb-3 flex flex-wrap gap-x-3 gap-y-1">
                    <span className="text-emerald-400 font-semibold">✓ {locationsMeta.valid_count} Valid</span>
                    <span>• {locationsMeta.ignored_count} Blanks/Comments</span>
                    <span>• {locationsMeta.duplicate_count} Duplicates</span>
                    {locationsMeta.rejected_count > 0 && <span className="text-amber-400">• {locationsMeta.rejected_count} Rejected</span>}
                  </div>
                )}

                {locationsMeta?.invalid_entries?.length > 0 && (
                  <div className="text-[11px] bg-amber-500/10 border border-amber-500/20 p-2.5 rounded-lg mb-3 text-amber-300">
                    <span className="font-semibold block mb-0.5">⚠️ {locationsMeta.invalid_entries.length} excluded entries:</span>
                    <span className="text-slate-400 truncate block">{locationsMeta.invalid_entries.slice(0, 3).join(', ')}</span>
                  </div>
                )}
              </div>

              {/* Locations Tag Preview */}
              {locations.length > 0 && (
                <div className="max-h-28 overflow-y-auto pr-1 flex flex-wrap gap-1.5 pt-2 border-t border-slate-800/80">
                  {locations.map((loc, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                    >
                      {loc}
                      <button
                        type="button"
                        onClick={() => removeLocation(i)}
                        className="hover:text-rose-400"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Mode Selection & Search Budget ───────────────────────────────── */}
          <div className="p-4 rounded-xl bg-slate-800/30 border border-slate-800 flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-slate-300">Combination Mode:</span>
              {[
                { id: 'uploaded_only', label: 'Uploaded Only' },
                { id: 'presets_only', label: 'Built-in Presets' },
                { id: 'combine', label: 'Combine Presets + Uploaded' },
              ].map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setMode(opt.id)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${
                    mode === opt.id
                      ? 'bg-blue-600 border-blue-500 text-white font-medium shadow-md shadow-blue-600/30'
                      : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3">
              <label className="text-xs font-semibold text-slate-300 whitespace-nowrap">
                Max Job Budget:
              </label>
              <input
                type="number"
                min="1"
                max="500"
                value={budget}
                onChange={(e) => setBudget(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-24 px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs text-white text-center focus:outline-none focus:border-blue-500"
              />
              <span className="text-[11px] text-slate-400">combinations</span>
            </div>
          </div>

          {/* ── Estimation & Action Bar ──────────────────────────────────────── */}
          {preview && (
            <div className="p-4 rounded-xl bg-gradient-to-r from-blue-950/40 via-slate-900 to-slate-950 border border-blue-900/50 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/30 text-blue-400">
                  <Database size={24} />
                </div>
                <div>
                  <div className="text-sm font-bold text-white flex items-center gap-2">
                    <span>
                      {preview.keyword_count} keywords × {preview.location_count} locations = {preview.total_combinations.toLocaleString()} combinations
                    </span>
                    {preview.exceeds_safety_limit && (
                      <span className="text-[11px] px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30">
                        Budget Exceeds Single-Job Cap ({preview.max_allowed_combinations})
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {preview.total_batches > 1 ? (
                      <>
                        Batch <strong>{preview.current_batch_num}</strong> of <strong>{preview.total_batches}</strong>: Planned combinations <strong>{preview.batch_start.toLocaleString()}</strong> to <strong>{preview.batch_end.toLocaleString()}</strong> (effective limit: <strong>{preview.effective_budget} queries</strong>).
                      </>
                    ) : (
                      <>
                        Effective search limit for this run: <strong>{preview.effective_budget} queries</strong>.
                      </>
                    )}
                  </p>
                  {preview.total_batches > 1 && (
                    <div className="flex items-center gap-2 mt-2">
                      <button
                        type="button"
                        disabled={batchOffset === 0}
                        onClick={() => setBatchOffset(prev => Math.max(0, prev - (Number(budget) || 100)))}
                        className="text-[11px] px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 border border-slate-700 transition-colors"
                      >
                        ← Prev Batch
                      </button>
                      <span className="text-[11px] text-slate-400 font-mono">
                        Offset: {preview.batch_offset}
                      </span>
                      <button
                        type="button"
                        disabled={preview.batch_end >= preview.total_combinations}
                        onClick={() => setBatchOffset(prev => prev + (Number(budget) || 100))}
                        className="text-[11px] px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300 border border-slate-700 transition-colors"
                      >
                        Next Batch →
                      </button>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleStartJob}
                  disabled={loading || preview.total_combinations === 0 || preview.exceeds_safety_limit}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold flex items-center gap-2 shadow-lg shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  <Play size={15} />
                  Start Discovery Job {preview.total_batches > 1 ? `(Batch ${preview.current_batch_num})` : ''}
                </button>
              </div>
            </div>
          )}

          {/* ── Active Job Progress Monitor ─────────────────────────────────── */}
          {activeJob && (
            <div className="p-5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-slate-800 text-blue-400">
                    <RefreshCw
                      size={18}
                      className={activeJob.status === 'running' ? 'animate-spin' : ''}
                    />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-white">Job {activeJob.job_id}</span>
                      <span
                        className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${
                          activeJob.status === 'running'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                            : activeJob.status === 'completed'
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                            : activeJob.status === 'paused'
                            ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                            : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                        }`}
                      >
                        {activeJob.status}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400">
                      Progress: {activeJob.current_combination_idx} / {activeJob.effective_budget || activeJob.total_combinations} combinations
                    </span>
                  </div>
                </div>

                {/* Job Controls */}
                <div className="flex items-center gap-2">
                  {activeJob.status === 'running' && (
                    <button
                      type="button"
                      onClick={() => handlePauseJob(activeJob.job_id)}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-amber-400 text-xs font-semibold flex items-center gap-1.5 border border-slate-700"
                    >
                      <Pause size={13} /> Pause
                    </button>
                  )}
                  {activeJob.status === 'paused' && (
                    <button
                      type="button"
                      onClick={() => handleResumeJob(activeJob.job_id)}
                      className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold flex items-center gap-1.5 shadow"
                    >
                      <Play size={13} /> Resume
                    </button>
                  )}
                  {(activeJob.status === 'running' || activeJob.status === 'paused') && (
                    <button
                      type="button"
                      onClick={() => handleCancelJob(activeJob.job_id)}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/50 text-rose-400 text-xs font-semibold flex items-center gap-1.5 border border-slate-700"
                    >
                      <Square size={13} /> Cancel
                    </button>
                  )}
                  <a
                    href={getDiscoveryExportUrl(activeJob.job_id, 'leadgen')}
                    download
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-emerald-400 text-xs font-semibold flex items-center gap-1.5 border border-slate-700"
                  >
                    <Download size={13} /> Full CSV
                  </a>
                  <a
                    href={getDiscoveryExportUrl(activeJob.job_id, 'simple')}
                    download
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold flex items-center gap-1.5 border border-slate-700"
                  >
                    <Download size={13} /> 3-Col CSV
                  </a>
                </div>
              </div>

              {/* Progress Bar */}
              {(() => {
                const total = activeJob.effective_budget || activeJob.total_combinations || 1
                const cur = activeJob.current_combination_idx || 0
                const pct = Math.min(100, Math.round((cur / total) * 100))
                return (
                  <div>
                    <div className="flex justify-between text-xs text-slate-400 mb-1.5">
                      <span>Execution Progress</span>
                      <span className="font-semibold text-slate-200">{pct}% ({cur}/{total})</span>
                    </div>
                    <div className="h-2 w-full bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 rounded-full transition-all duration-300"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                )
              })()}

              {/* Statistics Tiles */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 pt-2">
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800/80">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-1">Searched</span>
                  <span className="text-base font-bold text-white">{activeJob.stats?.combinations_searched || 0}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800/80">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-1">Discovered</span>
                  <span className="text-base font-bold text-white">{activeJob.stats?.businesses_discovered || 0}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800/80">
                  <span className="text-[10px] uppercase font-bold text-amber-400 block mb-1">Target Sites</span>
                  <span className="text-base font-bold text-amber-300">{activeJob.stats?.outdated_or_dead_found || 0}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800/80">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block mb-1">Skipped Modern</span>
                  <span className="text-base font-bold text-slate-300">{activeJob.stats?.modern_skipped || 0}</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800/80">
                  <span className="text-[10px] uppercase font-bold text-emerald-400 block mb-1">Emails Extracted</span>
                  <span className="text-base font-bold text-emerald-300">{activeJob.stats?.emails_extracted || 0}</span>
                </div>
              </div>

              {/* Discovered Leads Results Table */}
              {activeJob.discovered_leads && activeJob.discovered_leads.length > 0 && (
                <div className="pt-2">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-300">
                      Discovered Leads ({activeJob.discovered_leads.length})
                    </span>
                  </div>
                  <div className="max-h-60 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/60">
                    <table className="w-full text-left text-xs text-slate-300">
                      <thead className="bg-slate-800/80 text-slate-400 uppercase text-[10px] sticky top-0">
                        <tr>
                          <th className="p-2.5">Business Name</th>
                          <th className="p-2.5">Email</th>
                          <th className="p-2.5">Website</th>
                          <th className="p-2.5">Classification</th>
                          <th className="p-2.5">Source & Method</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {activeJob.discovered_leads.map((lead, idx) => (
                          <tr key={idx} className="hover:bg-slate-800/40">
                            <td className="p-2.5 font-medium text-white">{lead.business_name}</td>
                            <td className="p-2.5 text-blue-400 font-mono text-[11px]">{lead.email}</td>
                            <td className="p-2.5 truncate max-w-[150px]">
                              {lead.website ? (
                                <a
                                  href={lead.website}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-slate-300 hover:text-white underline truncate block"
                                >
                                  {lead.website}
                                </a>
                              ) : (
                                <span className="text-slate-400 italic">No Website</span>
                              )}
                            </td>
                            <td className="p-2.5">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                                  lead.site_classification === 'outdated_website'
                                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                    : lead.site_classification === 'dead_website'
                                    ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                                    : 'bg-slate-800 text-slate-400 border-slate-700'
                                }`}
                                title={lead.site_classification_reason}
                              >
                                {lead.site_classification?.replace('_', ' ')}
                              </span>
                            </td>
                            <td className="p-2.5 text-[11px] text-slate-400 font-mono">
                              {lead.source} [{lead.extraction_method}]
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
