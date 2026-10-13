import { ENGINE_KEYS, ENGINE_LABELS } from '../ui/engine_capabilities.js'
import { simulationJobMetadata } from '../ui/jobs_panel_render.js'
import { docHeaders } from '../shared/doc_id.js'
import { SIMULATION_CARDS, clean, isTrajectory, simulationControls, simulationProgress, simulationJobSummary } from './vr_simulation_controls.js'
import { createVRSimulationTrajectory } from './vr_simulation_trajectory.js'
export { simulationControls } from './vr_simulation_controls.js'

export function createVRSimulations({ jobs, engineSelector, doc = document, request = fetch, onError = console.error,
  api, controller = () => null, companion = () => null, ensureFull = async () => {}, prepareFrame = async () => {}, onFrame = () => {}, scale = () => null }) {
  let version = Math.floor(Math.random() * 1e9), acknowledged = 0, signature = '', published = null, sending = false, epoch = 0
  let trajectoryMode = '', owner = '', pendingMessage = '', actionBusy = false
  const trajectory = api ? createVRSimulationTrajectory({ api, controller, companion, ensureFull, prepareFrame, request, changed: geometry => { if (geometry) { doc.documentElement.dataset.vrSimulationTrajectory = 'true'; const radio = simulationControls(doc, engineSelector.getSelected()).find(c => c.kind === 'mode' && c.group === trajectoryMode); if (radio) radio.element.checked = true; onFrame() } void publish().catch(() => {}) } }) : null
  doc.defaultView?.addEventListener('nadoc:representation-change', () => {
    if (trajectory?.active) { trajectory.pause(); void trajectory.seek(trajectory.snapshot().index) }
    onFrame()
  })
  function snapshot() {
    const engine = engineSelector.getSelected(), selection = jobs.getSelected()
    const list = doc.getElementById('simulate-jobs-list'), rows = [...(list?.querySelectorAll('[data-job-id]') ?? [])]
    const selected = engine === 'exp' ? 'session' : rows.some(row => row.dataset.jobId === selection.id) ? selection.id : ''
    const key = `${engine}:${selected}`
    if (owner && key !== owner) { owner = ''; trajectoryMode = ''; delete doc.documentElement.dataset.vrSimulationTrajectory; trajectory?.reset() }
    const controls = selected ? simulationControls(doc, engine, { trajectoryMode }) : []
    if (actionBusy) for (const c of controls) c.enabled = false
    if (trajectoryMode) for (const c of controls) if (c.kind === 'mode') c.active = c.group === trajectoryMode
    const progress = simulationProgress(doc, engine)
    if (pendingMessage) progress.push({ label: pendingMessage, fraction: -1, busy: true })
    const ts = trajectoryMode ? trajectory?.snapshot() : null
    if (ts && (trajectory.busy || ['metadata','loading','buffering','error'].includes(ts.phase))) progress.push({ label: ts.message, fraction: ts.progress, busy: ts.phase !== 'error' })
    return { engine, selected, mode: trajectoryMode || controls.find(c => c.kind === 'mode' && c.active)?.group || '',
      engines: ENGINE_KEYS.map(id => ({ id: `e:${id}`, label: ENGINE_LABELS[id], enabled: !actionBusy, active: id === engine })),
      jobs: rows.flatMap((row, i) => {
        const meta = simulationJobMetadata(row), status = meta?.status || ''
        const summary = simulationJobSummary(jobs.getJobDetails?.(row.dataset.jobId), status === 'running' && Number.isFinite(meta?.progress) ? `${Math.round(meta.progress * 100)}%` : /ns/i.test(meta?.summary || '') ? meta.summary : /done|completed|ready/.test(status) ? 'DONE' : status)
        const result = { id:`j:${i}`, label:clean(meta?.name || row.textContent), detail:clean([meta?.time, summary].filter(Boolean).join(' / ') || row.title), enabled:!list.inert && !actionBusy, active:row.dataset.jobId === selected, element:row, jobId:row.dataset.jobId }
        const tree = [...row.children].find(child => ['▸','▾'].includes(child.textContent))
        return tree ? [result, { ...result, id:`j:${i}:tree`, label:tree.title, active:false, element:tree, jobId:'' }] : [result]
      }),
      controls, trajectory: ts, progress, scale: scale()?.snapshot?.() ?? null }
  }
  const wire = state => JSON.parse(JSON.stringify(state, (key, value) => ['element', 'jobId', 'choice'].includes(key) ? undefined : value))
  const identity = state => JSON.stringify([state.engine, state.selected, state.mode, state.jobs.map(j => [j.id,j.jobId]), state.controls.map(c => [c.id, c.kind, c.group, c.choice, c.element?.id])])
  async function publish() {
    if (sending) return
    const state = snapshot(), data = wire(state), sig = JSON.stringify(data), context = identity(state)
    if (published?.signature === sig && published.acknowledged === acknowledged) return
    if (context !== signature) { signature = context; version++ }
    sending = true; const generation = epoch, current = version, ack = acknowledged
    try {
      const response = await request('/api/vr/simulations', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, version: current, acknowledged: ack }) })
      if (!response.ok) throw new Error('Could not update VR simulations')
      if (generation === epoch) published = { state, version: current, signature: sig, context, acknowledged: ack }
    } finally { sending = false }
  }
  async function activate(event) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= acknowledged) return
    acknowledged = event.sequence
    const current = snapshot()
    if (!published || event.version !== published.version || identity(current) !== published.context) { await publish(); return }
    if (event.id.startsWith('t:') && trajectoryMode && trajectory) {
      const action = event.id.slice(2)
      if (action === 'load') void trajectory.load().catch(error => onError(error.message))
      else if (action === 'cancel') trajectory.cancel()
      else if (action === 'configure') trajectory.configure(event)
      else if (action === 'play') trajectory.toggle()
      else if (action === 'smooth') trajectory.smooth()
      else if (action === 'loop') trajectory.loop()
      else if (action === 'seek') { trajectory.pause(); void trajectory.seek(event.value) }
      await publish(); return
    }
    if (event.id.startsWith('c:')) { scale()?.applyVR?.(event.id.slice(2), event.value); onFrame(); await publish(); return }
    const control = [...current.engines, ...current.jobs, ...current.controls].find(c => c.id === event.id)
    if (!control?.enabled || actionBusy) { await publish(); return }
    if (control.kind === 'mode' && isTrajectory(control.element) && trajectory) {
      // Pause/tear down the current desktop view, but do not click its auto-load radio.
      const off = current.controls.find(c => c.kind === 'mode' && c.group === 'off')
      off?.element.click(); trajectoryMode = control.group; owner = `${current.engine}:${current.selected}`
      void trajectory.select(jobs.getSelected()?.engine || current.engine, current.selected, /full/i.test(control.group) ? 'job' : current.engine === 'oxdna' ? 'lineage' : 'job')
      await publish(); return
    }
    if (control.id.startsWith('e:') || control.id.startsWith('j:') || control.kind === 'mode') {
      trajectory?.reset(); trajectoryMode = ''; owner = ''; delete doc.documentElement.dataset.vrSimulationTrajectory
    }
    try {
      actionBusy = true
      if (control.id.startsWith('e:')) {
        pendingMessage = 'Reading simulation jobs'; await publish()
        const tab = doc.querySelector('.left-tab-btn[data-tab="dynamics"]'); if (tab && !tab.classList.contains('active')) tab.click()
        engineSelector.select(control.id.slice(2)); await jobs.refresh()
      } else if (control.id.startsWith('j:')) {
        pendingMessage = 'Reading selected job'; await publish(); if (control.id.endsWith(':tree') || current.selected !== control.jobId) control.element.click()
      } else {
        if (control.group !== 'off') { pendingMessage = 'Preparing visualization'; await publish(); await ensureFull() }
        const el = control.element
        if (el.tagName === 'SELECT') { el.value = control.choice; el.dispatchEvent(new Event('change', { bubbles: true })) }
        else if (control.kind === 'number') {
          if (!Number.isFinite(event.value)) return
          el.value = String(Math.max(control.minimum, Math.min(control.maximum, event.value)))
          el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }))
        } else el.click()
        if (trajectoryMode && el.closest('#md-jobs-solvent-opts')) await trajectory.refreshCompanions()
        onFrame()
      }
    } finally { actionBusy = false; pendingMessage = ''; await publish() }
  }
  return { snapshot, trajectory, activate: event => activate(event).catch(error => onError(error.message)), publish: () => publish().catch(() => {}),
    reset() { epoch++; trajectory?.reset(); trajectoryMode = ''; owner = ''; delete doc.documentElement.dataset.vrSimulationTrajectory; version = Math.floor(Math.random() * 1e9); acknowledged = 0; signature = ''; published = null } }
}
export function simulationViewActive(doc) {
  return Object.values(SIMULATION_CARDS).some(id => [...(doc.getElementById(id)?.querySelectorAll('input[type="radio"]:checked') ?? [])].some(el => ['cando-display-mode', 'snupi-display-mode', 'mrdna-display-mode', 'oxdna-viz', 'md-viz', 'mode'].includes(el.name) && el.value !== 'off')) || !!doc.getElementById('exp-viz')?.checked || doc.documentElement?.dataset.vrSimulationTrajectory === 'true'
}
