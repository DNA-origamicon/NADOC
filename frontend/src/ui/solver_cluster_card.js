import { estimateSolverResources, lastErrorMessage, getClusterAvailability } from '../api/client.js'
import { schedulerWarning } from './cluster_availability_rows.js'
import { solverResourceWizard } from './solver_resource_wizard.js'
/** Shared Alpine execution card. Identical controls for part and assembly hosts. */
import { initSolverRunpodCard } from './solver_runpod_card.js'
import { initClusterAvailability } from './cluster_availability.js'
import { initClusterConnection } from './cluster_connection.js'

export function solverExecutionPayload(target, values = {}) {
  if (target === 'local') return { execution_target: 'local' }
  if (target !== 'alpine') throw new Error('Unknown execution target')
  if (!values.python?.startsWith('/')) throw new Error('Enter the absolute path to Python on Alpine.')
  const settings = { ...values }
  for (const key of ['cores', 'mem_gb', 'walltime_minutes']) {
    settings[key] = Number(values[key])
    if (!Number.isInteger(settings[key]) || settings[key] < 1) throw new Error('CPU, RAM and walltime must be positive whole numbers.')
  }
  return { execution_target: 'alpine', cluster_settings: settings }
}

export function remoteSolverStatus(job) {
  if (!['alpine', 'runpod'].includes(job?.execution_target)) return ''
  const r = job.remote || {}
  const phase = ['completed', 'failed', 'cancelled'].includes(job.status) ? job.status : r.downloading ? 'Downloading results' : r.scheduler_state || 'Preparing submission'
  return `${job.execution_target === 'alpine' ? 'Alpine' : 'RunPod'}${r.pod_id ? ` · Pod ${r.pod_id}` : ''}${r.slurm_job_id ? ` · Job ${r.slurm_job_id}` : ''} · ${phase}${r.last_error ? ` · ${r.last_error}` : ''}`
}

export function initSolverClusterCard({ mount, engine, onChange = () => {}, storage = globalThis.localStorage } = {}) {
  if (!mount) return { prepareLaunch: async () => ({ execution_target: 'local' }), isRemote: () => false, payload: () => ({ execution_target: 'local' }), showJob() {}, dispose() {} }
  const lifetime = new AbortController()
  const key = `nadoc:${engine}:alpine-settings`
  let saved = {}
  try { saved = JSON.parse(storage.getItem(key) || '{}') } catch { /* unavailable storage */ }
  const defaults = { python: '', partition: engine === 'mrdna' ? 'aa100' : 'acpu',
    qos: engine === 'mrdna' ? 'gpu-normal' : 'cpu-normal', account: 'ucb-general',
    cores: 8, mem_gb: engine === 'mrdna' ? 32 : 64, walltime_minutes: 120, arbd: '', ...saved }
  mount.classList.add('ox-card')
  // Same shell and provider mounts as oxDNA/NAMD; titles drive canonical ordering.
  mount.innerHTML = `<div id="${engine}-jobs-cluster-toggle" class="ox-card__header" style="color:#c9d1d9">
                  <span id="${engine}-jobs-cluster-arrow" class="ox-card__chevron icon icon--xs icon--rotates" data-icon="chevron-down"></span><span class="ox-card__title">Clusters</span>
                </div>
                <div id="${engine}-cluster-body" class="ox-card__body">
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:var(--text-xs);color:#8b949e">
                    <span>Run on:</span>
                    <label style="display:flex;align-items:center;gap:3px;cursor:pointer">
                      <input id="${engine}-run-target-local" type="radio" name="${engine}-run-target" value="local" checked style="accent-color:#3fb950">Local
                    </label>
                    <label style="display:flex;align-items:center;gap:3px;cursor:pointer">
                      <input id="${engine}-run-target-alpine" type="radio" name="${engine}-run-target" value="alpine" style="accent-color:#58a6ff">Alpine
                    </label>
                    <label style="display:flex;align-items:center;gap:3px;cursor:pointer">
                      <input id="${engine}-run-target-runpod" type="radio" name="${engine}-run-target" value="runpod" style="accent-color:#d29922">RunPod
                    </label>
                  </div>
                  <div id="${engine}-jobs-local-pane" hidden></div>
                  <div id="${engine}-jobs-alpine-pane" hidden>
                    <div id="${engine}-cluster-connection-mount" style="margin-bottom:6px"></div>
                    <div id="${engine}-jobs-alpine-availability" style="margin-bottom:6px"></div>
                  </div>
                  <div id="${engine}-jobs-runpod-pane" hidden>
                    <div id="${engine}-runpod-setup-mount" style="margin-bottom:6px"></div>
                    <div id="${engine}-jobs-runpod-status"
                         style="border:1px solid #30363d;border-radius:3px;padding:6px;margin-bottom:6px;background:#0d1117"></div>
                    <div id="${engine}-jobs-runpod-picker"
                         style="border:1px solid #30363d;border-radius:3px;padding:6px;margin-bottom:6px;background:#0d1117"></div>
                  </div>
                </div>`
  const toggle = mount.querySelector('.ox-card__header')
  const body = mount.querySelector('.ox-card__body')
  toggle.setAttribute('role', 'button')
  toggle.tabIndex = 0
  toggle.setAttribute('aria-expanded', 'true')
  toggle.setAttribute('aria-controls', body.id)
  const radios = [...mount.querySelectorAll('input[type="radio"]')]
  const target = () => radios.find(radio => radio.checked)?.value || 'local'
  const pane = mount.querySelector(`#${engine}-jobs-alpine-pane`)
  const connection = initClusterConnection({ mount: mount.querySelector(`#${engine}-cluster-connection-mount`) })
  const availability = initClusterAvailability({ mount: mount.querySelector(`#${engine}-jobs-alpine-availability`) })
  const settings = document.createElement('details')
  settings.innerHTML = '<summary style="cursor:pointer;font-size:var(--text-xs);color:#8b949e">Solver settings</summary>'
  pane.append(settings)
  const fields = new Map()
  const labels = { python: 'Remote Python', partition: 'Partition', qos: 'QoS', account: 'Account',
    cores: 'CPU cores', mem_gb: 'RAM (GiB)', walltime_minutes: 'Walltime (minutes)', arbd: 'Remote ARBD executable' }
  for (const [name, label] of Object.entries(labels)) {
    if (name === 'arbd' && engine !== 'mrdna') continue
    const row = document.createElement('label')
    row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:6px;font-size:var(--text-xs)'
    const span = document.createElement('span')
    span.textContent = label
    span.style.flex = '1'
    const input = document.createElement('input'); input.className = 'input'
    input.id = `${engine}-cluster-${name}`
    input.type = ['cores', 'mem_gb', 'walltime_minutes'].includes(name) ? 'number' : 'text'
    if (input.type === 'number') { input.classList.add('input--data'); input.min = '1'; input.step = '1' }
    input.value = defaults[name]
    input.style.cssText = 'width:55%;min-width:0'
    row.append(span, input)
    settings.append(row)
    fields.set(name, input)
  }
  const note = document.createElement('p')
  note.style.cssText = 'font-size:var(--text-xs);color:#8b949e'
  note.textContent = engine === 'snupi'
    ? 'CPU solver. BigO-poly NMA measured about 46 GiB on Alpine; 64 GiB is a provisional allocation. Dynamics timestep setup remains slow. Remote Python needs NADOC dependencies.'
    : 'Requires a CUDA GPU partition, mrDNA in remote Python, and ARBD. Uses the allocated GPU as device 0. BigO-poly Fine currently hits the PDB residue limit; more RAM does not fix that export error.'
  const check = document.createElement('button')
  check.className = 'btn'; check.type = 'button'; check.textContent = 'Check Alpine environment'
  const checkStatus = document.createElement('div'); checkStatus.setAttribute('role', 'status')
  checkStatus.style.cssText = 'font-size:var(--text-xs);overflow-wrap:anywhere'
  check.addEventListener('click', async () => {
    check.disabled = true
    try {
      const values = Object.fromEntries([...fields].map(([name, input]) => [name, input.value.trim()]))
      const { cluster_settings: settings } = solverExecutionPayload('alpine', values)
      const response = await fetch('/api/solver-cluster/alpine-check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ engine, settings }),
      })
      const data = await response.json()
      checkStatus.textContent = response.ok ? data.message : (typeof data.detail === 'string' ? data.detail : 'Invalid cluster settings')
    } catch (error) { checkStatus.textContent = error.message }
    finally { check.disabled = false }
  })
  settings.append(check, checkStatus)
  const lifecycle = document.createElement('p')
  lifecycle.style.cssText = note.style.cssText
  lifecycle.textContent = 'Uses the current part or whole assembly and the solver options below. Results download when Alpine is connected. Timeouts do not auto-resubmit; a new run starts from the original snapshot.'
  settings.append(note, lifecycle)
  const status = document.createElement('div')
  status.setAttribute('role', 'status')
  status.hidden = true
  status.style.cssText = 'font-size:var(--text-xs);overflow-wrap:anywhere;margin-top:6px'
  const runpodPane = mount.querySelector(`#${engine}-jobs-runpod-pane`)
  const runpod = initSolverRunpodCard({ mount: runpodPane, engine })
  body.append(status)
  const toggleBody = () => {
    body.hidden = !body.hidden
    toggle.setAttribute('aria-expanded', String(!body.hidden))
    toggle.querySelector('.ox-card__chevron').style.transform = body.hidden ? 'rotate(-90deg)' : ''
  }
  const toggleKey = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleBody() } }
  toggle.addEventListener('click', toggleBody)
  toggle.addEventListener('keydown', toggleKey)
  const change = () => { pane.hidden = target() !== 'alpine'; runpodPane.hidden = target() !== 'runpod'; if (!runpodPane.hidden) runpod.refresh(); if (!pane.hidden) void connection.refresh(); onChange() }
  radios.forEach(radio => radio.addEventListener('change', change))
  let selectedJobId = null
  return {
    isRemote: () => target() !== 'local',
    async prepareLaunch(options) {
      const destination = target()
      if (destination === 'local') return { execution_target: 'local' }
      if (destination === 'alpine' && connection.getState() !== 'connected') throw new Error('Connect to Alpine before submitting.')
      const need = await estimateSolverResources(engine, options)
      if (!need) throw new Error(lastErrorMessage() || 'Could not estimate solver resources')
      const initial = destination === 'runpod' ? runpod.values()
        : Object.fromEntries([...fields].map(([name, input]) => [name, input.type === 'number' ? Number(input.value) : input.value.trim()]))
      const fetchChoices = async (settings, force = true) => {
        if (destination === 'alpine') {
          const availability = await getClusterAvailability({ force })
          if (!availability) throw new Error(lastErrorMessage() || 'Could not read Alpine availability')
          return need.alpine.map(row => {
            const part = availability.partitions?.find(p => p.partition === row.id)
            const resource = part?.gpu_resources?.find(g => !g.mig && g.gres_type === row.gres_type)
            return { ...row, availability: resource ? { ...part, ...resource } : part,
              availability_warning: schedulerWarning(availability, { partition: row.id, gresType: row.gres_type })?.message }
          })
        }
        const query = new URLSearchParams({ mem_gb: settings.mem_gb, cores: settings.cores, include_unavailable: true })
        const response = await fetch('/api/solver-cluster/runpod-options?' + query)
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Could not verify RunPod resources')
        return (data.gpus || []).map(row => ({ ...row, allocation_mem_gib: settings.mem_gb, allocation_cores: settings.cores }))
      }
      let rows
      try { rows = await fetchChoices({ ...initial, mem_gb: Math.max(need.min_ram_gib, initial.mem_gb) }, false) }
      catch (error) {
        if (destination !== 'alpine') throw error
        rows = need.alpine.map(row => ({ ...row, availability_error: 'Availability unknown: ' + error.message }))
      }
      const checkAllocation = destination !== 'runpod' ? undefined : async settings => {
        const available = await fetchChoices(settings)
        const row = available.find(row => row.id === settings.gpu_id)
        if (!row || row.stock?.toLowerCase() === 'none' || !Number(row.on_demand)) throw new Error('This GPU is unavailable at your volume location with the selected RAM and CPUs. Choose another GPU or adjust the allocation, then review again.')
        if (Number(row.on_demand) !== settings.quoted_rate) throw new Error('The RunPod price changed. Cancel and reopen the wizard for a fresh quote.')
      }
      const payload = await solverResourceWizard({ engine, target: destination, need, rows, initial, signal: lifetime.signal, checkAllocation, loadRows: fetchChoices })
      if (payload?.runpod_settings) runpod.applySettings(payload.runpod_settings)
      if (payload?.cluster_settings) {
        for (const [name, input] of fields) input.value = payload.cluster_settings[name] ?? ''
        try { storage.setItem(key, JSON.stringify(payload.cluster_settings)) } catch { /* optional preferences */ }
      }
      return payload
    },
    payload() {
      if (target() === 'runpod') return runpod.payload()
      if (target() === 'alpine' && connection.getState() !== 'connected') throw new Error('Connect to Alpine before submitting.')
      const values = Object.fromEntries([...fields].map(([name, input]) => [name, input.value.trim()]))
      const payload = solverExecutionPayload(target(), values)
      if (payload.cluster_settings) {
        if (engine === 'mrdna' && !values.arbd?.startsWith('/')) throw new Error('Enter the absolute path to ARBD on Alpine.')
        try { storage.setItem(key, JSON.stringify(payload.cluster_settings)) } catch { /* optional preferences */ }
      }
      return payload
    },
    showJob(job) {
      status.textContent = remoteSolverStatus(job)
      status.hidden = !status.textContent
      runpod.showJob(job?.execution_target === 'runpod' ? job : null)
      // Polls update evidence without overwriting a user's next-run settings.
      const id = job?.job_id ?? null
      if (id !== selectedJobId) {
        selectedJobId = id
        if (!job) return
        const destination = job.execution_target || 'local'
        for (const radio of radios) radio.checked = radio.value === destination
        if (destination === 'runpod') runpod.applySettings(job.remote?.settings || {})
        if (destination === 'alpine') {
          for (const [name, input] of fields) input.value = job.remote?.settings?.[name] ?? defaults[name]
        }
        change()
      }
    },
    dispose() { lifetime.abort(); runpod.dispose(); connection.dispose(); availability.dispose(); radios.forEach(radio => radio.removeEventListener('change', change)); toggle.removeEventListener('keydown', toggleKey); toggle.removeEventListener('click', toggleBody); mount.replaceChildren() },
  }
}
