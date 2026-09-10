import { ionPathsProgress } from './md_ion_paths_progress.js'

/** One cancellable load owns the paths, vector field, pore, and shared RMSF display. */
export function initMdIonPathsControls({ api, getOverlay, getJobId, getDisplay, getFlexScale, activate, onOff }) {
  const el = suffix => document.getElementById(`md-ion-paths-${suffix}`)
  const pathToggle = el('toggle'), vectorToggle = document.getElementById('md-ion-vector-field-toggle')
  const toggles = [pathToggle, vectorToggle].filter(Boolean)
  const options = el('options'), status = el('status'), bar = el('progress')
  let generation = 0, representationRevision = 0
  let abort = null, pollTimer = null
  let active = false, ownsAverage = false, loading = false, loadedKey = null
  let percentage = 0, summary = '', mode = 'paths'
  function progress(value, label, reset = false) {
    percentage = reset ? value : Math.max(percentage, value)
    if (bar) { bar.hidden = false; bar.value = percentage; bar.setAttribute('aria-valuetext', `${Math.floor(percentage)}% · ${label}`) }
    if (status) status.textContent = `${Math.floor(percentage)}% · ${label}`
  }
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null }
  function showModeOptions() {
    if (options) options.style.display = active ? 'block' : 'none'
    if (el('path-options')) el('path-options').style.display = mode === 'paths' ? 'block' : 'none'
    if (el('vector-options')) el('vector-options').style.display = mode === 'vector-field' ? 'block' : 'none'
  }
  function off() {
    generation++; representationRevision++
    abort?.abort(); abort = null
    stopPolling()
    active = false; loading = false; loadedKey = null
    getOverlay?.()?.clear()
    getFlexScale?.()?.hide?.()
    if (ownsAverage) { ownsAverage = false; getDisplay?.()?.stopAndRestore() }
    for (const toggle of toggles) toggle.checked = false
    showModeOptions()
    if (bar) bar.hidden = true
    if (status) status.textContent = ''
    if (el('percentage-label')) el('percentage-label').textContent = ''
    onOff?.()
  }
  function frames(name) {
    const input = el(name)
    const value = Math.max(1, Math.min(1000000, Math.trunc(Number(input?.value) || 10)))
    if (input) input.value = String(value)
    return value
  }
  function requestKey(job) { return `${job}:${frames('before')}:${frames('after')}` }
  function updatePercentage() {
    const value = Number(el('percentage')?.value ?? 100)
    const result = getOverlay?.()?.setPercentage?.(value)
    const label = el('percentage-label')
    if (label) label.textContent = result
      ? `${result.percentage}% · ${result.shown.toLocaleString()} / ${result.total.toLocaleString()} paths`
      : `${value}%`
  }
  function vectorSettings(densitySource = null) {
    const slider = el('density'), number = el('density-number')
    const rawDensity = densitySource === slider ? slider?.value : (number?.value || slider?.value)
    const density = Math.max(4, Math.min(1000000, Math.trunc(Number(rawDensity) || 14)))
    const arrowScale = Math.max(0.25, Math.min(3, Number(el('arrow-scale')?.value) || 1))
    if (slider) slider.value = String(Math.min(64, density))
    if (number) number.value = String(density)
    if (el('density-label')) el('density-label').textContent = String(density)
    if (el('arrow-scale')) el('arrow-scale').value = String(arrowScale)
    if (el('arrow-scale-label')) el('arrow-scale-label').textContent = `${arrowScale.toFixed(2)}×`
    return { species: el('species')?.value || 'NA', density,
      magnitude: el('magnitude')?.value === 'color' ? 'color' : 'size', arrowScale }
  }
  function applyMode() {
    const overlay = getOverlay?.()
    overlay?.setMode?.(mode)
    if (mode === 'paths') {
      overlay?.setWidth?.(el('width')?.value || 2)
      updatePercentage()
      const colorMode = el('color')?.value === 'time' ? 'time' : 'species'
      if (colorMode === 'time') {
        const range = overlay?.getPathFrameRange?.()
        if (range) getFlexScale?.()?.show?.({ title: 'Saved frame', min: range.min, max: range.max,
          mapType: 'ion-path-time',
          onRecolor: (lo, hi, colormap) => overlay?.setPathColorMode?.('time', { lo, hi, colormap }) })
        else overlay?.setPathColorMode?.('time')
      } else {
        getFlexScale?.()?.hide?.()
        overlay?.setPathColorMode?.('species')
      }
      return null
    }
    getFlexScale?.()?.hide?.()
    return overlay?.setVectorSettings?.(vectorSettings()) || null
  }
  async function poll(job, requestId, token, signal) {
    if (!api.getMdIonPathsProgress || token !== generation || signal.aborted) return
    try {
      const snapshot = await api.getMdIonPathsProgress(job, requestId, signal)
      if (token !== generation || !loading || signal.aborted) return
      const state = ionPathsProgress(snapshot)
      if (percentage <= 70) progress(state.percentage, state.label)
      if (snapshot?.state === 'done' || snapshot?.state === 'error') return
    } catch { /* An unavailable progress poll must not cancel the data request. */ }
    if (token === generation && loading && !signal.aborted) pollTimer = setTimeout(() => poll(job, requestId, token, signal), 400)
  }
  async function load({ force = false } = {}) {
    const job = getJobId()
    if (!job || !active || toggles.every(toggle => !toggle.checked || toggle.disabled)) return
    const key = requestKey(job)
    if (!force && loadedKey === key) {
      const result = applyMode()
      progress(100, result && mode === 'vector-field' ? `${result.arrows.toLocaleString()} ${result.species} vector arrows · ${summary}` : summary, true)
      return
    }
    abort?.abort(); stopPolling()
    abort = new AbortController()
    const signal = abort.signal, token = ++generation
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${token}-${Math.random().toString(36).slice(2)}`
    loading = true
    showModeOptions()
    progress(0, mode === 'paths' ? 'Preparing nanopore ion paths' : 'Preparing ion vector field', true)
    poll(job, requestId, token, signal)
    try {
      const data = await api.getMdIonPaths(job, frames('before'), frames('after'), signal, {
        requestId, onProgress: ({ fraction, stage }) => {
          if (token === generation) progress(stage === 'decode' ? 78 : 70 + 8 * fraction,
            stage === 'decode' ? 'Decoding ion data' : 'Downloading ion data')
        },
      })
      if (token !== generation) return
      stopPolling()
      if (!data || !Array.isArray(data.paths)) throw new Error(api.lastErrorMessage?.() || 'No ion data returned. Try loading again.')
      progress(80, mode === 'paths' ? 'Building ion paths and nanopore' : 'Building vector field and nanopore')
      await new Promise(resolve => setTimeout(resolve, 0))
      if (token !== generation) return
      getOverlay?.()?.setData(data)
      const viewResult = applyMode()
      const display = getDisplay?.()
      if (data.origami?.display_rmsf && display) {
        progress(85, 'Applying average origami and selected representation')
        ownsAverage = true
        const revision = representationRevision
        const result = await display.displayRmsf(job, { response: data.origami.display_rmsf, representations: data.origami, awaitHeavy: true })
        if (token !== generation) return
        if (!result?.ok) throw new Error(result?.reason || 'Could not display the average origami')
        if (revision !== representationRevision) await applyLatestRepresentation(token)
        if (token !== generation) return
      }
      loadedKey = key
      summary = `${data.crossings.toLocaleString()} aperture crossings · ${data.frames.toLocaleString()} saved frames${data.crossings ? '' : ' · No ions crossed the pore aperture'}${data.origami ? ` · RMSF average: ${data.origami.n_frames} sampled frames` : ''}`
      progress(100, viewResult && mode === 'vector-field' ? `${viewResult.arrows.toLocaleString()} ${viewResult.species} vector arrows · ${summary}` : summary)
    } catch (err) {
      if (token !== generation) return
      if (status) status.textContent = `${Math.floor(percentage)}% · ${err.message || 'Could not load ion data'}`
    } finally {
      if (token === generation) { loading = false; stopPolling() }
    }
  }
  async function applyLatestRepresentation(token) {
    let revision
    do {
      revision = representationRevision
      await getDisplay?.()?.reapplyForRepr({ strict: true })
    } while (token === generation && revision !== representationRevision)
  }
  async function reapplyRepresentation() {
    representationRevision++
    if (!active || !ownsAverage || loading) return
    const token = generation
    loading = true
    progress(0, 'Updating average origami representation', true)
    try {
      await applyLatestRepresentation(token)
      if (token === generation) progress(100, summary)
    } catch (err) {
      if (token === generation && status) status.textContent = err.message || 'Could not update representation'
    } finally { if (token === generation) loading = false }
  }
  function selectMode(nextMode, toggle) {
    if (!toggle.checked) return
    if (!active) {
      activate()
      active = true
      toggle.checked = true
    }
    mode = nextMode
    showModeOptions()
    load()
  }
  pathToggle?.addEventListener('change', () => selectMode('paths', pathToggle))
  vectorToggle?.addEventListener('change', () => selectMode('vector-field', vectorToggle))
  el('retry')?.addEventListener('click', () => load({ force: true }))
  for (const name of ['before', 'after']) el(name)?.addEventListener('change', () => { loadedKey = null; load() })
  el('width')?.addEventListener('input', () => {
    getOverlay?.()?.setWidth(el('width').value)
    if (active && !loading && mode === 'paths') progress(100, summary)
  })
  el('percentage')?.addEventListener('input', () => {
    updatePercentage()
    if (active && !loading && mode === 'paths') progress(100, summary)
  })
  el('color')?.addEventListener('change', () => {
    if (active && mode === 'paths') applyMode()
  })
  function updateVector(event) {
    const settings = vectorSettings(event?.currentTarget)
    const result = getOverlay?.()?.setVectorSettings?.(settings)
    if (active && !loading && mode === 'vector-field') progress(100,
      `${(result?.arrows || 0).toLocaleString()} ${result?.species || settings.species} vector arrows · ${summary}`)
  }
  for (const name of ['species', 'density', 'arrow-scale', 'magnitude']) el(name)?.addEventListener('input', updateVector)
  el('density-number')?.addEventListener('change', updateVector)
  return { off, reapplyRepresentation, isActive: () => active, setEnabled(enabled) {
    if (!enabled && active) off()
    for (const toggle of toggles) {
      toggle.disabled = !enabled
      const label = toggle.closest('label')
      if (label) { label.style.opacity = enabled ? '1' : '0.5'; label.style.cursor = enabled ? 'pointer' : 'not-allowed' }
    }
  } }
}
