import { framesToUpdates } from './oxdna_display.js'
import { docHeaders } from '../shared/doc_id.js'

/** Session-only screening preview. Never writes positions to the design or exporters. */
export function createExpPreview(designRenderer, { setVisible = () => {}, restoreNative = () => {} } = {}) {
  let active = false
  return {
    clear() {
      if (active) {
        designRenderer.applyFemPositions(null)
        designRenderer.clearExternalGeometry?.()
        restoreNative()
      }
      active = false
    },
    show(result, snapshot = null) {
      const updates = framesToUpdates(result.full?.keys, result.full?.frame)
      if (!updates.length) throw new Error('Prediction has no Full display frame')
      active = true
      if (snapshot) {
        const axes = Object.fromEntries((snapshot.helix_axes ?? []).map(ax => [ax.helix_id, {
          start: ax.start, end: ax.end, samples: ax.samples ?? null,
          ovhgAxes: ax.ovhg_axes ?? null, segments: ax.segments ?? null,
        }]))
        designRenderer.renderExternalGeometry(snapshot.design, snapshot.nucleotides, axes)
      }
      designRenderer.applyFemPositions(updates)
      setVisible(true)
    },
  }
}

export function initExpPanel({ designRenderer, getCurrentRepr = () => 'full', store, api, request = fetch, setVisible, restoreNative, preview = createExpPreview(designRenderer, { setVisible, restoreNative }) }) {
  const run = document.getElementById('exp-run')
  const bar = document.getElementById('exp-progress')
  const status = document.getElementById('exp-status')
  const viz = document.getElementById('exp-viz')
  if (!run) return
  const events = new AbortController()
  const listenerOptions = { signal: events.signal }
  let operation = null, result = null, snapshot = null, epoch = 0
  const busy = () => operation !== null
  function paint(message) {
    run.textContent = busy() ? 'Stop' : 'Run'
    viz.disabled = !result || getCurrentRepr() !== 'full'
    viz.title = getCurrentRepr() === 'full' ? 'Display predicted DNA positions' : 'Select Full representation to display predictions'
    if (message) status.textContent = message
  }
  async function json(path, method, headers) {
    const response = await request(`/api/exp${path}`, { method, headers })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Exp request failed')
    return data
  }
  function clearPreview() { preview.clear(); viz.checked = false }
  async function stop(op) {
    op.cancelled = true
    paint('Stopping…')
    if (op.id) await json(`/jobs/${op.id}/stop`, 'POST', op.headers)
  }
  function reset() {
    ++epoch
    const old = operation
    operation = null
    if (old) stop(old).catch(() => {})
    result = null
    snapshot = null
    clearPreview()
    bar.value = 0
    paint('Run an experimental shape prediction. Results are session-only.')
  }
  async function start() {
    const ticket = ++epoch
    const op = { headers: docHeaders(), cancelled: false, id: null }
    operation = op
    result = null
    snapshot = null
    clearPreview()
    bar.removeAttribute('value') // actual pending request, never a simulated percentage
    paint('Checking model…')
    try {
      const model = await json('/status', 'GET', op.headers)
      if (!model.available) throw new Error(model.message)
      if (op.cancelled || epoch !== ticket) return
      await api.prepareExpPrediction()
      if (op.cancelled || epoch !== ticket) return
      let job = await json('/jobs', 'POST', op.headers)
      op.id = job.job_id
      // A Stop/document change during POST must also cancel the newly-created job.
      if (op.cancelled || epoch !== ticket) { await stop(op); return }
      while (['running', 'stopping'].includes(job.status)) {
        if (epoch !== ticket) return
        bar.value = job.progress
        paint(job.message)
        await new Promise(resolve => setTimeout(resolve, 400))
        if (epoch !== ticket) return
        job = await json(`/jobs/${op.id}`, 'GET', op.headers)
      }
      if (epoch !== ticket) return
      bar.value = job.progress
      if (job.status === 'completed' && !op.cancelled) {
        // Compact assembly launches leave the editor document intact. Build an
        // external Full model from this job's frozen input, as CanDo does.
        if (store.getState?.().assemblyActive) {
          paint('Preparing Full assembly preview…')
          const geometry = await json(`/jobs/${op.id}/snapshot-geometry`, 'GET', op.headers)
          if (epoch !== ticket || op.cancelled) return
          snapshot = geometry
        }
        result = job.result
      }
      const limits = job.model?.limits
      paint(`${job.message}${result ? ` — ${result.label}` : ''}${limits ? ` — ${limits}` : ''}`)
    } catch (error) {
      if (op.id) await json(`/jobs/${op.id}/stop`, 'POST', op.headers).catch(() => {})
      if (epoch === ticket) { bar.value = 0; paint(op.cancelled ? 'Stopped' : error.message) }
    } finally {
      if (epoch === ticket) {
        operation = null
        if (!bar.hasAttribute('value')) bar.value = 0
        paint(op.cancelled ? 'Stopped' : null)
      }
    }
  }
  run.addEventListener('click', () => {
    if (operation) stop(operation).catch(error => paint(error.message))
    else start()
  }, listenerOptions)
  viz.addEventListener('change', () => {
    try {
      if (viz.checked && result && getCurrentRepr() === 'full') preview.show(result, snapshot)
      else clearPreview()
    } catch (error) { clearPreview(); paint(error.message) }
  }, listenerOptions)
  window.addEventListener('nadoc:representation-change', () => {
    if (getCurrentRepr() !== 'full') clearPreview()
    paint()
  }, listenerOptions)
  window.addEventListener('nadoc:workspace-path-change', reset, listenerOptions)
  window.addEventListener('nadoc:design-changed', reset, listenerOptions)
  window.addEventListener('nadoc:simulation-engine', event => {
    if (event.detail.engine !== 'exp') clearPreview()
    // Exp has its own deliberately minimal, session-only controls.
    for (const id of ['simulate-jobs', 'simulate-run-dir', 'simulate-status-line', 'engine-speed-axis']) {
      const element = document.getElementById(id)
      if (element) element.hidden = event.detail.engine === 'exp'
    }
  }, listenerOptions)
  const unsubscribe = store.subscribe((state, previous) => {
    if (state.currentDesign !== previous.currentDesign || state.currentAssembly !== previous.currentAssembly || state.assemblyActive !== previous.assemblyActive) reset()
  })
  paint()
  return { reset, dispose() { reset(); events.abort(); unsubscribe?.() } }
}
