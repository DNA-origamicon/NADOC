/** Saved pair analysis → native-position colors. Filters never fetch trajectories. */
export function filterUvPairs(result, { interstrand = true, intrastrand = true, ttOnly = false } = {}) {
  return (result?.pairs || []).filter(p => (p.same_strand ? intrastrand : interstrand)
    && (!ttOnly || p.chemistry === 'TT'))
}

export function uvColorPayload(result, filters) {
  const pairs = filterUvPairs(result, filters)
  const values = new Map()
  for (const pair of pairs) {
    for (const index of [pair.a, pair.b]) values.set(index, Math.max(values.get(index) || 0, pair.opportunity))
  }
  return {
    ...result, n_candidates: pairs.length,
    base_likelihoods: (result?.sites || []).map((site, index) => ({
      ...site, relative_likelihood: values.get(index) || 0, aggregate_propensity: values.get(index) || 0,
    })),
  }
}

export function initUvCrosslinking({ api, getJobId, getDisplay, getScale, activate, onOff = () => {}, doc = document }) {
  const el = name => doc.getElementById(`md-jobs-${name}`)
  const toggle = el('photoproduct-toggle'), options = el('uv-options')
  const status = el('photoproduct-status'), progress = el('photoproduct-progress')
  const fill = el('photoproduct-progress-fill'), progressLabel = el('photoproduct-progress-label')
  const inter = el('uv-interstrand'), intra = el('uv-intrastrand'), tt = el('uv-tt-only')
  let controller = null, result = null, resultJob = null, cancelBarrier = Promise.resolve()
  let scale = { lo: 0, hi: 1, cmap: 'magma' }, epoch = 0
  const listeners = []
  const listen = (target, event, fn) => { target?.addEventListener(event, fn); listeners.push(() => target?.removeEventListener(event, fn)) }
  const filters = () => ({ interstrand: inter?.checked ?? true, intrastrand: intra?.checked ?? true, ttOnly: tt?.checked ?? false })
  function setStatus(text) { if (status) status.textContent = text }
  function paintProgress(p) {
    if (!progress) return
    progress.style.display = p ? '' : 'none'
    if (!p) return
    const percent = Math.round(100 * (p.fraction || 0))
    progress.setAttribute('aria-valuenow', String(percent))
    if (fill) fill.style.width = `${percent}%`
    if (progressLabel) progressLabel.textContent = `${p.message} · ${p.done || 0}/${p.total || '?'} frames · ${percent}%`
  }
  function apply() {
    if (!result || resultJob !== getJobId() || !toggle?.checked) return
    const payload = uvColorPayload(result, filters())
    const display = getDisplay?.()
    const applied = display?.displayPhotoproduct(resultJob, payload)
    if (!applied?.ok) throw new Error(applied?.reason || 'Could not apply UV analysis colors')
    display.recolorPhotoproduct(scale.lo, scale.hi, scale.cmap)
    setStatus(`${result.complete ? 'Saved analysis' : 'Partial analysis'} · ${result.n_sampled_frames}/${result.n_total_frames} frames`)
  }
  function off() {
    epoch++
    const runningJob = controller?.jobId
    controller?.abort()
    controller = null
    if (runningJob) cancelBarrier = cancelBarrier.then(() => api.cancelMdAnalysis(runningJob, 'photoproduct')).catch(() => {})
    if (getDisplay?.()?.mode?.() === 'photoproduct') getDisplay().stopAndRestore()
    if (toggle) toggle.checked = false
    if (options) options.style.display = 'none'
    getScale?.()?.hide?.()
    paintProgress(null)
    setStatus(runningJob ? 'Paused · completed frames saved; select again to resume' : '')
    onOff()
  }
  async function refresh() {
    const jobId = getJobId()
    if (!jobId || !toggle?.checked) return
    const token = ++epoch
    await cancelBarrier
    if (token !== epoch || !toggle.checked) return
    const abort = new AbortController()
    abort.jobId = jobId
    controller = abort
    // Revalidate the job's input fingerprint before reusing any prior payload.
    // Filters changed during loading must not repaint a stale trajectory result.
    result = null
    resultJob = null
    if (options) options.style.display = ''
    setStatus('Loading saved UV analysis or resuming completed frames…')
    paintProgress({ fraction: 0, message: 'Loading saved analysis' })
    let polling = false
    const poll = setInterval(async () => {
      if (polling || abort.signal.aborted) return
      polling = true
      try {
        const p = await api.getMdPhotoproductProgress(jobId)
        if (token === epoch && !abort.signal.aborted) paintProgress(p)
      } catch { /* The result request reports durable errors. */ }
      finally { polling = false }
    }, 750)
    try {
      const response = await api.getMdPhotoproductLikelihood(jobId, { signal: abort.signal })
      if (token !== epoch || abort.signal.aborted || jobId !== getJobId()) return
      if (!response.ready) throw new Error(response.reason || 'No production frames available')
      result = response
      resultJob = jobId
      scale = { lo: 0, hi: 1, cmap: scale.cmap }
      apply()
      getScale?.()?.show?.({
        title: 'UV geometric opportunity (frame fraction)', min: 0, max: 1, mapType: 'uv-crosslinking',
        onRecolor: (lo, hi, cmap) => { scale = { lo, hi, cmap }; getDisplay?.()?.recolorPhotoproduct?.(lo, hi, cmap) },
      })
      paintProgress(null)
    } catch (error) {
      if (token !== epoch || abort.signal.aborted) return
      off()
      setStatus(`UV analysis failed: ${error.message}. Completed frames remain saved.`)
    } finally {
      clearInterval(poll)
      if (controller === abort) controller = null
    }
  }
  listen(toggle, 'change', async () => {
    if (!toggle.checked) { off(); return }
    if (activate() === false) { off(); return }
    await refresh()
  })
  for (const target of [inter,intra,tt]) listen(target,'change',apply)
  return { off, refresh, dispose() { off(); listeners.forEach(f=>f()) } }
}
