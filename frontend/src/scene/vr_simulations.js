import { ENGINE_KEYS, ENGINE_LABELS } from '../ui/engine_capabilities.js'
import { docHeaders } from '../shared/doc_id.js'

const CARDS = { cando: 'cando-display-card', snupi: 'snupi-display-card', mrdna: 'mrdna-jobs-display-body', oxdna: 'oxdna-jobs-viz-body', namd: 'md-jobs-viz-body' }
const clean = text => String(text ?? '').replace(/\s+/g, ' ').trim()
const trajectory = el => /traj|trajectory/i.test(`${el.id} ${el.name} ${el.value} ${el.closest('label')?.textContent ?? ''}`)
const label = el => {
  const wrapper = el.labels?.[0]?.cloneNode(true)
  wrapper?.querySelectorAll('input,select,button').forEach(child => child.remove())
  return clean(wrapper?.textContent || el.getAttribute('aria-label') || el.title || el.textContent || el.id)
}

/** Only visualization controls are exposed; simulation launch/delete controls never enter this map. */
export function simulationControls(doc, engine) {
  const root = doc.getElementById(CARDS[engine]), result = []
  for (const [index, el] of [...(root?.querySelectorAll('input,select,button') ?? [])].entries()) {
    if (trajectory(el) || el.type === 'hidden') continue
    const key = `v:${index}`
    const hidden = !!el.closest('[hidden]') || el.style.display === 'none'
    const base = { label: label(el), detail: clean(el.closest('label')?.title || el.title), enabled: !el.disabled && !hidden, active: !!el.checked, element: el }
    if (el.tagName === 'SELECT') {
      for (const [i, option] of [...el.options].entries()) result.push({ ...base, id: `${key}:${i}`, label: `${base.label.split(':')[0]}: ${clean(option.textContent)}`, active: option.selected, enabled: base.enabled && !option.disabled, value: option.value })
    } else if (['number', 'range'].includes(el.type)) {
      for (const sign of [-1, 1]) result.push({ ...base, id: `${key}:${sign}`, label: `${base.label}: ${el.value} ${sign < 0 ? '(-)' : '(+)'}`, delta: sign })
    } else if (['radio', 'checkbox', 'button', 'submit'].includes(el.type) || el.tagName === 'BUTTON') result.push({ ...base, id: key })
  }
  return result
}

export function createVRSimulations({ jobs, engineSelector, doc = document, request = fetch, onError = console.error }) {
  let version = Math.floor(Math.random() * 1e9), acknowledged = 0, signature = '', published = null, sending = false, epoch = 0
  function snapshot() {
    const engine = engineSelector.getSelected(), selection = jobs.getSelected()
    const list = doc.getElementById('simulate-jobs-list')
    const rows = [...(list?.querySelectorAll('[data-job-id]') ?? [])]
    const selected = rows.some(row => row.dataset.jobId === selection.id) ? selection.id : ''
    const controls = selected ? simulationControls(doc, engine) : []
    return { engine, selected, engines: ENGINE_KEYS.map(id => ({ id: `e:${id}`, label: ENGINE_LABELS[id], enabled: true, active: id === engine })),
      jobs: rows.map((row, i) => ({ id: `j:${i}`, label: clean(row.textContent), detail: clean(row.title), enabled: !list.inert, active: row.dataset.jobId === selected, element: row, jobId: row.dataset.jobId })), controls }
  }
  const wire = state => JSON.parse(JSON.stringify(state, (key, value) => ['element', 'jobId', 'value', 'delta'].includes(key) ? undefined : value))
  async function publish() {
    if (sending) return
    const state = snapshot(), data = wire(state), sig = JSON.stringify(data)
    if (published?.signature === sig && published.acknowledged === acknowledged) return
    if (sig !== signature) { signature = sig; version++ }
    sending = true
    const generation = epoch, current = version, ack = acknowledged
    try {
      const response = await request('/api/vr/simulations', { method: 'POST', headers: { ...docHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...data, version: current, acknowledged: ack }) })
      if (!response.ok) throw new Error('Could not update VR simulations')
      if (generation === epoch) published = { state, version: current, signature: sig, acknowledged: ack }
    } finally { sending = false }
  }
  async function activate(event) {
    if (!Number.isSafeInteger(event.sequence) || event.sequence <= acknowledged) return
    acknowledged = event.sequence
    const current = snapshot()
    if (!published || event.version !== published.version || JSON.stringify(wire(current)) !== published.signature) { await publish(); return }
    const control = [...current.engines, ...current.jobs, ...current.controls].find(c => c.id === event.id)
    if (!control?.enabled) { await publish(); return }
    if (control.id.startsWith('e:')) {
      const tab = doc.querySelector('.left-tab-btn[data-tab="dynamics"]')
      if (tab && !tab.classList.contains('active')) tab.click()
      engineSelector.select(control.id.slice(2))
      await jobs.refresh()
    } else if (control.id.startsWith('j:')) {
      if (current.selected !== control.jobId) control.element.click()
    } else {
      const el = control.element
      if (el.tagName === 'SELECT') { el.value = control.value; el.dispatchEvent(new Event('change', { bubbles: true })) }
      else if (control.delta) {
        const step = Number(el.step) || 1, min = el.min === '' ? -Infinity : Number(el.min), max = el.max === '' ? Infinity : Number(el.max)
        el.value = String(Math.max(min, Math.min(max, Number(el.value) + control.delta * step)))
        el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }))
      } else el.click()
    }
    await publish()
  }
  return { snapshot, activate: event => activate(event).catch(error => onError(error.message)), publish: () => publish().catch(() => {}), reset() { epoch++; version = Math.floor(Math.random() * 1e9); acknowledged = 0; signature = ''; published = null } }
}

/** A static result needs the actual desktop meshes (cylinders, maps, clouds), not only nucleotide offsets. */
export function simulationViewActive(doc) {
  return Object.values(CARDS).some(id => [...(doc.getElementById(id)?.querySelectorAll('input[type="radio"]:checked') ?? [])].some(el => ['cando-display-mode', 'snupi-display-mode', 'mrdna-display-mode', 'oxdna-viz', 'md-viz', 'mode'].includes(el.name) && el.value !== 'off' && !trajectory(el)))
}
