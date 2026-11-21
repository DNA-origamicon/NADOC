/** RunPod controls without NAMD-specific speed/cost predictions. */
import { initRunpodSetup } from './runpod_setup.js'
import { initRunpodGpuPicker } from './runpod_gpu_picker.js'
import { initRunpodStatus } from './runpod_status.js'

export function initSolverRunpodCard({ mount, engine, fetchImpl = fetch }) {
  const panel = 'border:1px solid #30363d;border-radius:3px;padding:6px;margin-bottom:6px;background:#0d1117'
  const providerMount = (id, style) => {
    const node = mount.querySelector(`#${id}`) || document.createElement('div')
    node.id = id; node.style.cssText = style; mount.append(node)
    return node
  }
  const setupMount = providerMount(`${engine}-runpod-setup-mount`, 'margin-bottom:6px')
  const statusMount = providerMount(`${engine}-jobs-runpod-status`, panel)
  const jobInfo = providerMount(`${engine}-runpod-selected-job`, panel)
  jobInfo.hidden = true
  jobInfo.style.fontSize = 'var(--text-xs)'
  jobInfo.style.overflowWrap = 'anywhere'
  const pickerMount = providerMount(`${engine}-jobs-runpod-picker`, panel)
  const status = initRunpodStatus({ mount: statusMount, fetchImpl, preflightPath: '/api/solver-cluster/runpod-check' })
  const setup = initRunpodSetup({ mount: setupMount, fetchImpl, solver: engine, onConnected: () => status.refreshSession() })
  let selected = null
  const picker = initRunpodGpuPicker({
    mount: pickerMount,
    estimateNote: 'Live quote; checked again before renting. Solver time and total cost estimates are not available.',
    fetchOptions: async () => {
      selected = null
      const response = await fetchImpl('/api/solver-cluster/runpod-options?' + new URLSearchParams({ mem_gb: controls.get('mem_gb').value, cores: controls.get('cores').value }))
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not check RunPod')
      return { ok: true, gpus: (data.gpus || []).map(row => ({ ...row,
        key: row.id, label: row.display || row.id, usd_per_hour: row.on_demand, live_price: true,
      })) }
    },
    onSelect: row => { selected = row },
  })
  const settings = document.createElement('details')
  settings.innerHTML = '<summary style="cursor:pointer;font-size:var(--text-xs);color:#8b949e">Solver settings</summary>'
  mount.append(settings)
  const controls = new Map()
  for (const [key, label, value, type] of [
    ['budget_usd', 'Compute budget ($)', '5', 'number'],
    ['mem_gb', 'Minimum host RAM (GiB)', engine === 'snupi' ? '64' : '32', 'number'],
    ['cores', 'Minimum vCPUs', '8', 'number'],
    ['walltime_minutes', 'Maximum pod time (minutes)', '120', 'number'],
    ['python', 'Python on network volume', '/workspace/nadoc-solver-env/bin/python', 'text'],
    ...(engine === 'mrdna' ? [['arbd', 'ARBD on network volume', '/workspace/bin/arbd', 'text']] : []),
  ]) {
    const row = document.createElement('label'); row.style.cssText = 'display:block;margin-top:6px;font-size:var(--text-xs)'
    row.textContent = label + ' '
    const input = document.createElement('input'); input.className = type === 'number' ? 'input input--data' : 'input'; input.type = type; input.value = value
    input.id = `${engine}-runpod-${key}`; input.style.width = '100%'
    if (type === 'number') { input.min = key === 'budget_usd' ? '0.01' : '1'; input.step = key === 'budget_usd' ? '0.01' : '1' }
    row.append(input); settings.append(row); controls.set(key, input)
  }
  const note = document.createElement('p'); note.style.fontSize = 'var(--text-xs)'
  note.textContent = 'Budget includes pod startup, checks, simulation and transfers; network-volume storage is billed separately. The default SNUPI environment is prepared automatically; custom environments and mrDNA must already be installed. Linear/Stokes SNUPI dynamics can use CUDA; unsupported modes retain CPU. RAM is separate from GPU VRAM. No automatic retries.'
  settings.append(note)
  return {
    showJob(job) {
      jobInfo.hidden = !job
      const remote = job?.remote || {}
      const config = remote.settings || {}
      jobInfo.textContent = !job ? '' : [
        `Selected job: ${job.job_id} · ${job.status}`,
        remote.pod_id && `Pod: ${remote.pod_id}`,
        config.gpu_id && `GPU: ${config.gpu_id}`,
        config.mem_gb && `Requested host RAM: ${config.mem_gb} GiB`,
        config.cores && `Requested vCPUs: ${config.cores}`,
        config.quoted_rate && `Submitted quote: $${config.quoted_rate}/hr`,
        config.budget_usd && `Compute budget: $${config.budget_usd}`,
      ].filter(Boolean).join(' · ')
    },
    refresh() { void status.refresh(); void status.refreshSession(); void status.refreshBilling() },
    values() { return { gpu_id: selected?.id, ...Object.fromEntries([...controls].map(([key, input]) => [key, input.type === 'number' ? Number(input.value) : input.value.trim()])) } },
    applySettings(values) {
      picker.clear() // The wizard may have selected a different GPU or a newer quote.
      for (const [key, input] of controls) if (values[key] !== undefined) input.value = values[key]
      selected = { id: values.gpu_id, on_demand: values.quoted_rate }
    },
    payload() {
      if (!selected) throw new Error('Check RunPod prices and choose a GPU.')
      const settings = { gpu_id: selected.id, quoted_rate: Number(selected.on_demand) }
      for (const [key, input] of controls) {
        settings[key] = input.type === 'number' ? Number(input.value) : input.value.trim()
        if (input.type === 'number' && (!Number.isFinite(settings[key]) || settings[key] <= 0)) throw new Error('RunPod budget and resource limits must be positive.')
      }
      return { execution_target: 'runpod', runpod_settings: settings }
    },
    dispose() { picker.clear(); setup.dispose(); mount.replaceChildren() },
  }
}
