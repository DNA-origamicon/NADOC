import { ionPathsProgress } from './md_ion_paths_progress.js'

/** One cancellable load owns both the companions and the shared RMSF display. */
export function initMdIonPathsControls({ api, getOverlay, getJobId, getDisplay, activate, onOff }) {
  const el = suffix => document.getElementById(`md-ion-paths-${suffix}`)
  const toggle = el('toggle'), options = el('options'), status = el('status'), bar = el('progress')
  let generation = 0, representationRevision = 0
  let abort = null, pollTimer = null
  let active = false, ownsAverage = false, loading = false
  let percentage = 0, summary = ''
  function progress(value, label, reset = false) {
    percentage = reset ? value : Math.max(percentage, value)
    if (bar) { bar.hidden = false; bar.value = percentage; bar.setAttribute('aria-valuetext', `${Math.floor(percentage)}% · ${label}`) }
    if (status) status.textContent = `${Math.floor(percentage)}% · ${label}`
  }
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null }
  function off() {
    generation++; representationRevision++
    abort?.abort(); abort = null
    stopPolling()
    active = false; loading = false
    getOverlay?.()?.clear()
    if (ownsAverage) { ownsAverage = false; getDisplay?.()?.stopAndRestore() }
    if (toggle) toggle.checked = false
    if (options) options.style.display = 'none'
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
  function updatePercentage() {
    const value = Number(el('percentage')?.value ?? 100)
    const result = getOverlay?.()?.setPercentage?.(value)
    const label = el('percentage-label')
    if (label) label.textContent = result
      ? `${result.percentage}% · ${result.shown.toLocaleString()} / ${result.total.toLocaleString()} paths`
      : `${value}%`
  }
  async function poll(job, requestId, token, signal) {
    if (!api.getMdIonPathsProgress || token !== generation || signal.aborted) return
    try {
      const snapshot = await api.getMdIonPathsProgress(job, requestId, signal)
      if (token !== generation || !loading || signal.aborted) return
      const state = ionPathsProgress(snapshot)
      // Late poll replies cannot replace a later transfer/rendering status.
      if (percentage <= 70) progress(state.percentage, state.label)
      if (snapshot?.state === 'done' || snapshot?.state === 'error') return
    } catch { /* An unavailable progress poll must not cancel the data request. */ }
    if (token === generation && loading && !signal.aborted) pollTimer = setTimeout(() => poll(job, requestId, token, signal), 400)
  }
  async function load() {
    const job = getJobId()
    if (!job || !toggle?.checked || toggle.disabled) return
    abort?.abort(); stopPolling()
    abort = new AbortController()
    const signal = abort.signal, token = ++generation
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${token}-${Math.random().toString(36).slice(2)}`
    active = true; loading = true
    if (options) options.style.display = 'block'
    progress(0, 'Preparing nanopore ion paths', true)
    poll(job, requestId, token, signal)
    try {
      const data = await api.getMdIonPaths(job, frames('before'), frames('after'), signal, {
        requestId, onProgress: ({ fraction, stage }) => {
          if (token === generation) progress(stage === 'decode' ? 78 : 70 + 8 * fraction,
            stage === 'decode' ? 'Decoding path data' : 'Downloading path data')
        },
      })
      if (token !== generation) return
      stopPolling()
      if (!data || !Array.isArray(data.paths)) throw new Error(api.lastErrorMessage?.() || 'No ion-path data returned. Try loading again.')
      progress(80, 'Building ion paths and nanopore')
      // Allow the browser to paint the status before allocating large path buffers.
      await new Promise(resolve => setTimeout(resolve, 0))
      if (token !== generation) return
      getOverlay?.()?.setData(data)
      getOverlay?.()?.setWidth(el('width')?.value || 2)
      updatePercentage()
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
      summary = `${data.crossings.toLocaleString()} aperture crossings · ${data.frames.toLocaleString()} saved frames${data.crossings ? '' : ' · No ions crossed the pore aperture'}${data.origami ? ` · RMSF average: ${data.origami.n_frames} sampled frames` : ''}`
      progress(100, summary)
    } catch (err) {
      if (token !== generation) return
      if (status) status.textContent = `${Math.floor(percentage)}% · ${err.message || 'Could not load ion paths'}`
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
  toggle?.addEventListener('change', () => {
    if (!toggle.checked) { off(); return }
    if (active) { load(); return }
    activate(); toggle.checked = true; load()
  })
  el('retry')?.addEventListener('click', load)
  for (const name of ['before', 'after']) el(name)?.addEventListener('change', load)
  el('width')?.addEventListener('input', () => {
    getOverlay?.()?.setWidth(el('width').value)
    if (active && !loading) progress(100, summary)
  })
  el('percentage')?.addEventListener('input', () => {
    updatePercentage()
    if (active && !loading) progress(100, summary)
  })
  return { off, reapplyRepresentation, isActive: () => active, setEnabled(enabled) {
    if (!enabled && active) off()
    if (toggle) {
      toggle.disabled = !enabled
      const label = toggle.closest('label')
      if (label) { label.style.opacity = enabled ? '1' : '0.5'; label.style.cursor = enabled ? 'pointer' : 'not-allowed' }
    }
  } }
}
