import { createInput, createSelect } from './primitives/input.js'
import { createButton } from './primitives/button.js'
import { createSolverResourceList } from './solver_resource_list.js'
import { createModal } from './primitives/modal.js'

/** Unknown VRAM is ineligible for GPU solvers; host minima are requested at deployment. */
export function resourceChoiceReason(row, need, target, engine) {
  if (target === 'alpine' && row.availability?.request_only) return 'Requires partition access'
  if (target === 'runpod' && row.stock?.toLowerCase() === 'none') return 'Unavailable for this volume and allocation'
  if (target === 'alpine' && engine === 'mrdna' && !row.cuda) return 'Requires a CUDA GPU'
  if (need.min_vram_gb > 0 && !(Number(row.vram_gb) >= need.min_vram_gb)) return 'Insufficient or unknown VRAM'
  if (target === 'alpine' && row.max_ram_gib < need.min_ram_gib) return 'Insufficient RAM'
  if (target === 'runpod' && (!Number.isFinite(Number(row.on_demand)) || Number(row.on_demand) <= 0)) return 'Live price unavailable'
  if (need.min_ram_gib > 2048) return 'Exceeds supported RAM allocation'
  return ''
}

/** No submission side effects: resolves an allocation only after explicit review. */
export function solverResourceWizard({ engine, target, need, rows, initial = {}, signal, checkAllocation, loadRows }) {
  return new Promise(resolve => {
    if (signal?.aborted) { resolve(null); return }
    let result = null
    let reviewing = false
    let checking = false
    let closed = false
    let reviewedSettings = null
    const body = document.createElement('div')
    const summary = document.createElement('p')
    summary.textContent = `Estimated RAM: ${need.ram_gib.toFixed(1)} GiB · VRAM: ${need.vram_gib.toFixed(1)} GiB · Output disk: ${need.disk_gib.toFixed(1)} GiB. Allocations include 20% RAM and 15% VRAM headroom. These are conservative planning estimates, not guaranteed peaks.`
    body.append(summary)
    const form = document.createElement('form')
    form.addEventListener('submit', event => event.preventDefault())
    const fields = {}
    function field(name, label, type, value) {
      const wrap = document.createElement('label')
      wrap.style.cssText = 'display:block;margin:10px 0'
      wrap.textContent = label + ' '
      const input = type === 'select' ? createSelect() : createInput({ type, data: type === 'number' })
      if (type !== 'select') input.type = type
      input.name = name; input.setAttribute('aria-label', label)
      input.required = true; input.style.width = '100%'
      if (value !== undefined) input.value = value
      wrap.append(input); form.append(wrap); fields[name] = input
      return input
    }
    const choice = { value: rows.find(r => !resourceChoiceReason(r, need, target, engine) && r.id === (initial.partition || initial.gpu_id))?.id
      || rows.find(r => !resourceChoiceReason(r, need, target, engine))?.id || '' }
    const listMount = document.createElement('div')
    const list = createSolverResourceList({ mount: listMount, target, runtime: need.runtime,
      reason: row => resourceChoiceReason(row, need, target, engine),
      onChange: id => { choice.value = id; selectResource() } })
    const refresh = createButton({ label: 'Re-check availability', size: 'sm' })
    refresh.hidden = !loadRows
    const availabilityNote = document.createElement('p')
    const timing = document.createElement('p')
    timing.textContent = [need.runtime?.basis, need.runtime?.note,
      target === 'alpine'
        ? 'Wait is general partition availability, not a placement forecast for these RAM, CPU and walltime settings. Completion combines that wait with rough solver runtime.'
        : 'Completion shows rough solver runtime plus unknown pod startup; stock is checked for the selected volume and requested RAM/CPUs.',
      'These estimates are not the maximum time limit.'].filter(Boolean).join(' ')
    form.append(listMount, refresh, availabilityNote, timing)
    function renderList() {
      list.render(rows, choice.value)
      renderAvailabilityNote()
    }
    function renderAvailabilityNote() {
      availabilityNote.textContent = rows.find(r => r.id === choice.value)?.availability_warning
        || rows.find(r => r.availability_error)?.availability_error || ''
      const snapshot = rows[0]
      if (target === 'runpod' && snapshot?.allocation_mem_gib) {
        availabilityNote.textContent += ' Stock checked for ' + snapshot.allocation_mem_gib + ' GiB RAM and ' + snapshot.allocation_cores + ' CPUs. Re-check after changing the allocation.'
      }
    }
    const ram = field('mem_gb', 'RAM allocation (GiB)', 'number', Math.max(need.min_ram_gib, initial.mem_gb || 1))
    ram.min = need.min_ram_gib; ram.max = 2048; ram.step = 1
    const cores = field('cores', 'CPU cores', 'number', initial.cores || 8)
    cores.min = 1; cores.max = 256; cores.step = 1
    const qos = target === 'alpine' ? field('qos', 'QoS', 'select') : null
    const time = field('walltime_minutes', 'Maximum time (minutes)', 'number', initial.walltime_minutes || 120)
    time.min = target === 'alpine' ? 1 : 7; time.max = 10080; time.step = 1
    if (target === 'runpod') {
      const budget = field('budget_usd', 'Compute budget ($)', 'number', initial.budget_usd || 5)
      budget.min = .01; budget.max = 1000; budget.step = .01
      const note = document.createElement('p')
      note.textContent = 'Host RAM and CPU minima are requested when renting; availability is confirmed by RunPod. Startup and transfers consume the budget. Network-volume storage is billed separately.'
      form.append(note)
    } else field('account', 'Account', 'text', initial.account || 'ucb-general')
    const python = field('python', 'Remote Python path', 'text', initial.python || '')
    python.pattern = '/[^\\r\\n]+'
    if (engine === 'mrdna') field('arbd', 'Remote ARBD path', 'text', initial.arbd || '').pattern = '/[^\\r\\n]+'
    const status = document.createElement('p'); status.setAttribute('role', 'status')
    const review = document.createElement('p'); review.hidden = true; review.style.whiteSpace = 'pre-wrap'
    body.append(form, status, review)
    const cancel = createButton({ label: 'Cancel' })
    const back = createButton({ label: 'Back' }); back.hidden = true
    const next = createButton({ label: 'Review resources', variant: 'primary' })
    const modal = createModal({ title: `${engine === 'snupi' ? 'SNUPI' : 'mrDNA'} — ${target === 'alpine' ? 'Alpine' : 'RunPod'} resources`, size: 'xl', className: 'solver-resource-wizard', body,
      actions: [cancel, back, next], onClose: () => { closed = true; signal?.removeEventListener('abort', abort); resolve(result) } })
    const abort = () => modal.close()
    signal?.addEventListener('abort', abort, { once: true })
    const selected = () => rows.find(row => row.id === choice.value)
    function validate() {
      if (checking || closed) return false
      const row = selected()
      let error = !row ? 'No available resource meets the estimated requirements.' : resourceChoiceReason(row, need, target, engine)
      if (row && target === 'alpine') {
        ram.max = Math.min(2048, row.max_ram_gib)
        cores.max = Math.min(256, row.max_cores)
        cores.min = Math.max(1, Math.ceil(Number(ram.value) / row.mem_per_core_gb))
        time.max = row.qos.find(q => q.name === qos.value)?.minutes || 0
      }
      if (!error && !form.checkValidity()) error = `Enter RAM ${ram.min}–${ram.max} GiB, CPU cores ${cores.min}–${cores.max}, time ${time.min}–${time.max} minutes, and absolute executable paths.`
      if (!error && target === 'runpod' && Number(fields.budget_usd.value) <= Number(row.on_demand) * .1) error = 'Budget must cover more than six pod-minutes, including shutdown headroom.'
      status.textContent = error; next.disabled = !!error
      return !error
    }
    function selectResource() {
      renderAvailabilityNote()
      const row = selected()
      if (row && qos) {
        qos.replaceChildren(...row.qos.map(q => { const o = document.createElement('option'); o.value = q.name; o.textContent = q.name; return o }))
        if (row.qos.some(q => q.name === initial.qos)) qos.value = initial.qos
        ram.value = Math.min(Number(ram.value), row.max_ram_gib)
        cores.value = Math.min(row.max_cores, Math.max(Number(cores.value), Math.ceil(Number(ram.value) / row.mem_per_core_gb)))
        time.value = Math.min(Number(time.value), row.qos.find(q => q.name === qos.value)?.minutes || 0)
      }
      validate()
    }
    refresh.addEventListener('click', async () => {
      if (checking || closed || !loadRows) return
      if (!ram.checkValidity() || !cores.checkValidity()) {
        status.textContent = 'Enter a valid RAM and CPU allocation before refreshing.'
        return
      }
      checking = true; form.inert = true; next.disabled = true
      status.textContent = 'Refreshing resource availability…'
      try {
        const updated = await loadRows({ mem_gb: Number(ram.value), cores: Number(cores.value) })
        if (closed) return
        rows = updated
        if (!rows.some(r => r.id === choice.value)) choice.value = ''
        renderList()
      } catch (error) {
        status.textContent = 'Availability refresh failed; displayed values are the previous snapshot. ' + error.message
        return
      } finally { checking = false; form.inert = false }
      validate()
    })
    form.addEventListener('input', validate); form.addEventListener('change', validate)
    cancel.addEventListener('click', () => modal.close())
    back.addEventListener('click', () => { reviewing = false; form.hidden = false; review.hidden = true; back.hidden = true; next.textContent = 'Review resources'; validate() })
    next.addEventListener('click', async () => {
      if (checking || closed) return
      if (reviewing) {
        result = { execution_target: target, [target === 'alpine' ? 'cluster_settings' : 'runpod_settings']: reviewedSettings }
        modal.close()
        return
      }
      if (!validate()) return
      const settings = { ...initial }
      for (const [key, input] of Object.entries(fields)) {
        if (key !== 'resource') settings[key] = input.type === 'number' ? Number(input.value) : input.value.trim()
      }
      if (target === 'alpine') settings.partition = choice.value
      else { settings.gpu_id = choice.value; settings.quoted_rate = Number(selected().on_demand) }
      if (!reviewing && checkAllocation) {
        checking = true; form.inert = true; next.disabled = true
        status.textContent = 'Checking availability at your network volume location…'
        try { await checkAllocation(settings) }
        catch (error) { status.textContent = error.message; next.disabled = false; return }
        finally { checking = false; form.inert = false }
        if (closed) return
        next.disabled = false; status.textContent = ''
      }
      if (!reviewing) {
        reviewedSettings = settings
        reviewing = true; form.hidden = true; review.hidden = false; back.hidden = false
        review.textContent = `Review: ${selected().label || selected().display || selected().id}\n${settings.mem_gb} GiB RAM · ${settings.cores} CPU cores · ${settings.walltime_minutes} minutes${target === 'runpod' ? `\nRate: $${settings.quoted_rate}/hour · Compute cap: $${settings.budget_usd}. Confirming will rent a pod.` : `\nQoS: ${settings.qos} · Account: ${settings.account}`}`
        next.textContent = target === 'runpod' ? 'Rent pod and start' : 'Submit job'
      }
    })
    renderList(); selectResource(); modal.open()
  })
}
