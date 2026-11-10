import './simulation_submodel.css'
import { createSubmodelShell } from '../scene/simulation_submodel_shell.js'
import { initViewVolumes } from '../scene/view_volumes.js'

/** The view-volume editor owns every gesture. This adapter owns only job UI state. */
export function initSimulationSubmodel({ document, store, api, createEditor = initViewVolumes, ...sceneDeps }) {
  const hosts = {
    oxdna: document.getElementById('oxdna-submodel'),
    md: document.getElementById('md-submodel'),
  }
  if (!hosts.oxdna || !hosts.md) return null
  const records = new Map(), selected = { oxdna: null, md: null }, subscribers = new Set()
  let engine = 'oxdna', active = null, editor = null, disposed = false
  const sourceKey = () => {
    const s = store.getState()
    return `${s.assemblyActive ? 'assembly' : 'part'}:${(s.assemblyActive ? s.currentAssembly : s.currentDesign)?.id ?? 'empty'}`
  }
  let source = sourceKey()
  function record(forEngine) {
    const job = selected[forEngine]
    const key = `${forEngine}:${job ? `job:${job}` : `draft:${source}`}`
    if (!records.has(key)) records.set(key, { key, job, engine: forEngine, box: null, loaded: !job, loading: false, error: '', queue: Promise.resolve(), pending: 0 })
    return records.get(key)
  }
  const status = {}, buttons = {}, retries = {}, shellInputs = {}, projections = {}
  const shell = createSubmodelShell(sceneDeps.scene)
  const mdVisibility = document.getElementById('md-box-view-details')
  let oxVisibility = null
  const visible = r => engine === 'md' ? !!mdVisibility?.checked : r?.box?.visible !== false
  const stopSettingsEvent = event => event.stopPropagation()
  for (const [key, host] of Object.entries(hosts)) {
    host.addEventListener('input', stopSettingsEvent)
    host.addEventListener('change', stopSettingsEvent)
    const button = document.createElement('button')
    button.type = 'button'; button.className = 'btn btn--sm'; button.textContent = 'Define submodel'; button.id = `${key}-define-submodel`
    const label = document.createElement('p'); label.setAttribute('role', 'status')
    const note = document.createElement('p')
    note.textContent = key === 'oxdna'
      ? 'Submodels run locally on CPU with a Brownian thermostat. Only the box moves; the shell is fixed. Outside context remains visible but is not simulated. Maps include this frozen context; its zero fluctuation is imposed, not sampled.'
      : 'NAMD selection only — this box does not restrict Run.'
    const projection = document.createElement('p')
    projection.id = key + '-submodel-projection'
    projection.setAttribute('aria-live', 'polite')
    projections[key] = projection
    const retry = document.createElement('button')
    retry.type = 'button'; retry.className = 'btn btn--sm'; retry.textContent = 'Retry save'; retry.hidden = true
    retry.addEventListener('click', () => { const r = record(key); void save(r, r.box).catch(() => {}) })
    const shellLabel = document.createElement('label')
    shellLabel.className = 'submodel-shell-field'; shellLabel.textContent = 'Fixed shell (nm) '
    const shellInput = document.createElement('input')
    shellInput.type = 'number'; shellInput.min = '0'; shellInput.max = '1000'; shellInput.step = '0.1'; shellInput.value = '3'; shellInput.id = `${key}-submodel-shell`
    shellLabel.append(shellInput); shellInputs[key] = shellInput
    shellInput.addEventListener('change', () => {
      const r = record(key), radius = Number(shellInput.value)
      if (!shellInput.value.trim() || !Number.isFinite(radius) || radius < 0 || radius > 1000) { paint(); return }
      if (r.box) { save(r, { ...r.box, shell_nm: radius }); notify(); paint() }
    })
    const help = document.createElement('p')
    help.textContent = 'Distance outside the box. 0 nm keeps only directly bonded neighbours fixed. Bonded neighbours are always retained.'
    host.append(button, label, retry, shellLabel, help)
    if (key === 'oxdna') {
      const visibilityLabel = document.createElement('label')
      oxVisibility = document.createElement('input'); oxVisibility.type = 'checkbox'; oxVisibility.id = 'oxdna-submodel-visible'; oxVisibility.checked = true
      visibilityLabel.append(oxVisibility, ' Show box and shell'); host.append(visibilityLabel)
      oxVisibility.addEventListener('change', () => { const r = record('oxdna'); if (r.box) { save(r, { ...r.box, visible: oxVisibility.checked }); notify(); paint() } })
    }
    host.append(note, projection); buttons[key] = button; status[key] = label; retries[key] = retry
    button.addEventListener('click', () => {
      engine = key
      if (key === 'md' && mdVisibility && !mdVisibility.checked) { mdVisibility.checked = true; mdVisibility.dispatchEvent(new Event('change', { bubbles: true })) }
      if (key === 'oxdna' && record(key).box?.visible === false) save(record(key), { ...record(key).box, visible: true })
      refresh()
      if (active.box) editor.select('submodel')
      else editor.add('box')
    })
  }
  const mount = document.createElement('div')
  function volumes(r) {
    return r?.box ? [{ ...r.box, id: 'submodel', name: 'Submodel', enabled: false, outline_visible: visible(r), representation: 'full', opacity: 1 }] : []
  }
  function state() {
    const s = store.getState(), key = s.assemblyActive ? 'currentAssembly' : 'currentDesign'
    return { ...s, [key]: { ...s[key], id: active?.key, view_volumes: volumes(active) } }
  }
  function notify() { shell.update(active?.box, visible(active)); for (const fn of subscribers) fn(state()) }
  async function updateProjection(r) {
    if (r.engine !== 'oxdna' || !api.estimateSimulationSubmodel || !r.job || !r.box) return
    const key = JSON.stringify({ ...r.box, visible: undefined })
    if (key === r.projectionKey) return
    r.projectionKey = key
    r.projectionText = 'Estimating submodel…'; paint()
    try {
      const result = await api.estimateSimulationSubmodel(r.job, r.box)
      if (r.projectionKey !== key || disposed) return
      const p = result?.projection
      r.projectionText = p
        ? p.mobile_nucleotides + ' mobile + ' + p.fixed_nucleotides + ' fixed / ' + p.source_nucleotides + ' source bases. CPU host budget ~' + Math.ceil(p.host_ram_budget_bytes / 1048576) + ' MiB; simulation VRAM 0 MiB. MD estimate ~' + Math.ceil(p.md_seconds || 0) + ' s' + (p.mc_steps ? '; MC ETA after first samples.' : '.') + ' Reference hardware; viewer memory additional.'
        : 'Submodel estimate unavailable: ' + (api.lastErrorMessage?.() || 'check the region and job.')
    } catch { if (r.projectionKey === key) r.projectionText = 'Submodel estimate unavailable.' }
    paint()
  }
  function paint() {
    for (const key of Object.keys(hosts)) {
      const r = record(key)
      projections[key].textContent = r.box ? (r.projectionText || (key === 'oxdna' ? 'Create a job to estimate its particle count and resource budget.' : '')) : ''
      buttons[key].disabled = r.loading || !r.loaded
      shellInputs[key].disabled = r.loading || !r.loaded || !r.box
      shellInputs[key].value = String(r.box?.shell_nm ?? 3)
      if (key === 'oxdna') { oxVisibility.checked = r.box?.visible !== false; oxVisibility.disabled = !r.box || r.loading }
      retries[key].hidden = !r.error || !r.loaded
      buttons[key].textContent = r.box ? 'Edit submodel' : 'Define submodel'
      status[key].textContent = r.error || (r.loading ? 'Loading submodel…' : r.pending ? 'Saving submodel…' : r.box ? (r.job ? 'Submodel saved to job.' : 'Submodel ready for new job.') : 'No submodel defined.')
    }
  }
  function save(r, box) {
    r.box = box; if (!box) { r.projectionText = ''; r.projectionKey = null }; r.error = ''; r.loaded = true; r.loading = false
    if (!r.job) { paint(); return Promise.resolve() }
    r.pending++; paint()
    const snapshot = structuredClone(box)
    r.queue = r.queue.catch(() => {}).then(async () => {
      const result = await api.saveSimulationSubmodel(r.engine, r.job, snapshot)
      if (!result) throw new Error('Could not save submodel. Retry save before leaving this page.')
      r.error = ''
      void updateProjection(r)
    }).catch(error => { r.error = error.message; throw error }).finally(() => { r.pending--; if (!disposed) paint() })
    // Keep failures visible, without an unhandled rejection from a pointer event.
    r.queue.catch(() => {})
    return r.queue
  }
  const adapter = {
    getState: state,
    subscribe(fn) { subscribers.add(fn); return () => subscribers.delete(fn) },
    setState(patch) {
      const doc = patch.currentAssembly ?? patch.currentDesign
      const volume = doc?.view_volumes?.[0]
      const box = volume ? { ...active.box, shape: 'box', min_corner: volume.min_corner, max_corner: volume.max_corner, rotation: volume.rotation } : null
      save(active, box); notify()
    },
  }
  active = record(engine)
  hosts[engine].append(mount)
  editor = createEditor({ document, store: adapter, api: { saveViewVolumes: async () => ({}), saveAssemblyViewVolumes: async () => ({}) }, host: mount, outlineOnly: true, ...sceneDeps })
  function refresh() {
    active = hosts[engine] ? record(engine) : null
    mount.hidden = !active || !active.loaded || active.loading
    if (active) hosts[engine].append(mount)
    notify(); paint()
  }
  async function select(forEngine, id) {
    selected[forEngine] = id ?? null
    const r = record(forEngine)
    if (!r.loaded && !r.loading) {
      r.loading = true; refresh()
      try {
        const result = await api.getSimulationSubmodel(forEngine, id)
        if (!result) throw new Error('Could not load submodel. Select the job again to retry.')
        if (!r.loaded) { r.box = result.box; r.loaded = true; r.error = ''; void updateProjection(r) }
      } catch (error) { if (!r.loaded) r.error = error.message }
      finally { r.loading = false }
    }
    refresh()
  }
  const onEngine = event => { engine = event.detail?.engine === 'namd' ? 'md' : event.detail?.engine; refresh() }
  window.addEventListener('nadoc:simulation-engine', onEngine)
  const onMdVisibility = () => { notify(); paint() }
  mdVisibility?.addEventListener('change', onMdVisibility)
  window.addEventListener('nadoc:box-solvent-details', onMdVisibility)
  const unsubscribe = store.subscribe(() => {
    const next = sourceKey()
    if (source !== next) { source = next; selected.oxdna = null; selected.md = null }
    refresh()
  })
  refresh()
  return {
    select,
    async flush(forEngine) {
      const r = record(forEngine)
      await r.queue
      if (r.error || !r.loaded) throw new Error(r.error || 'Wait for the submodel to load before running.')
    },
    capture: forEngine => structuredClone(record(forEngine).box),
    async created(forEngine, id, box) {
      selected[forEngine] = id
      const r = record(forEngine)
      try { await save(r, box) } catch { /* Keep the created job selected and show the save failure. */ }
      refresh()
    },
    debug: { ...editor.debug, shellVisible: shell.visible, selectJob: select, saveToJob: async (forEngine, id) => { const box = structuredClone(record(forEngine).box); selected[forEngine] = id; await save(record(forEngine), box); refresh() } },
    dispose() { for (const host of Object.values(hosts)) { host.removeEventListener('input', stopSettingsEvent); host.removeEventListener('change', stopSettingsEvent) }; window.removeEventListener('nadoc:box-solvent-details', onMdVisibility); disposed = true; unsubscribe?.(); window.removeEventListener('nadoc:simulation-engine', onEngine); mdVisibility?.removeEventListener('change', onMdVisibility); shell.dispose(); editor.dispose(); mount.remove() },
  }
}
