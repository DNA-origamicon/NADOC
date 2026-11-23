import { formatHours, formatWait, availabilityView } from './cluster_availability_rows.js'
import '../styles/solver_resource_list.css'

const known = value => typeof value === 'number' && Number.isFinite(value) && value >= 0

/** Provider facts and solver timing stay separate from NAMD throughput predictions. */
export function solverResourceView(row, target, runtime) {
  const seconds = runtime?.seconds
  const duration = seconds => seconds < 60 ? '<1 min' : formatHours(seconds / 3600)
  const run = known(seconds) ? duration(seconds) : 'Unknown'
  let availability = 'Unknown'
  let wait = 'Unknown'
  let waitMinutes = null
  let waitBasis = 'No queue estimate available'
  if (target === 'alpine' && row.availability) {
    const a = row.availability
    const view = availabilityView(a)
    availability = a.request_only ? 'Request access' : `${view.free} GPUs free · ${view.badge.text}`
    waitMinutes = known(a.wait_min) && !a.request_only ? a.wait_min : null
    wait = waitMinutes === null ? 'Unknown' : formatWait(waitMinutes)
    waitBasis = a.wait_basis || 'General partition estimate'
  } else if (target === 'runpod') {
    availability = !row.stock ? 'Unknown' : row.stock.toLowerCase() !== 'none'
      ? `${row.stock} stock` : 'Unavailable'
    wait = 'Startup unknown'
    waitBasis = 'On-demand allocation; RunPod does not provide a startup-time forecast'
  }
  const completion = known(seconds) && waitMinutes !== null
    ? `≈ ${duration(seconds + waitMinutes * 60)}`
    : known(seconds) ? `≈ ${run} + ${target === 'runpod' ? 'startup' : 'wait'}` : 'Unknown'
  return { availability, wait, waitBasis, completion, run }
}

/** Native radios retain keyboard selection and disabled-resource semantics. */
export function createSolverResourceList({ mount, target, runtime, reason, onChange }) {
  mount.className = 'solver-resource-list'
  mount.setAttribute('role', 'group')
  mount.setAttribute('aria-label', target === 'alpine' ? 'Alpine resources' : 'RunPod GPUs')
  function render(rows, selected) {
    mount.replaceChildren()
    const header = document.createElement('div')
    header.className = 'solver-resource-list__header'
    for (const text of ['Resource / memory', 'Availability', 'Est. wait', 'Est. completion']) {
      const cell = document.createElement('span'); cell.textContent = text; header.append(cell)
    }
    const scroll = document.createElement('div')
    scroll.className = 'solver-resource-list__scroll'
    mount.append(header, scroll)
    if (!rows.length) {
      const empty = document.createElement('p')
      empty.textContent = 'No resources returned. Re-check availability to try again.'
      scroll.append(empty)
    }
    for (const row of rows) {
      const problem = reason(row)
      const view = solverResourceView(row, target, runtime)
      const label = document.createElement('label')
      label.className = 'solver-resource-list__row'
      label.dataset.selected = String(row.id === selected)
      label.dataset.disabled = String(!!problem)
      const identity = document.createElement('span')
      identity.className = 'solver-resource-list__identity'
      const radio = document.createElement('input')
      radio.type = 'radio'; radio.name = 'solver-resource'; radio.value = row.id
      radio.checked = row.id === selected; radio.disabled = !!problem
      radio.setAttribute('aria-label', row.label || row.display || row.id)
      radio.addEventListener('change', () => {
        for (const node of scroll.children) node.dataset.selected = String(node.contains(radio))
        onChange(row.id)
      })
      const name = document.createElement('strong'); name.textContent = row.label || row.display || row.id
      const info = document.createElement('small')
      info.textContent = (row.gpu_model ? row.gpu_model + ' · ' : '') + `${row.vram_gb ?? '?'} GB VRAM`
        + (target === 'alpine' ? ` · up to ${row.max_ram_gib} GiB RAM` : ` · ${row.on_demand ? '$' + row.on_demand + '/h' : 'Price unavailable'} · ${row.data_center_id || 'Volume location'}`)
      const text = document.createElement('span'); text.append(name, info)
      if (problem) { const why = document.createElement('small'); why.className = 'solver-resource-list__reason'; why.textContent = problem; text.append(why) }
      identity.append(radio, text); label.append(identity)
      for (const [text, title] of [[view.availability, 'Live availability snapshot'], [view.wait, view.waitBasis], [view.completion, runtime?.basis || 'Runtime estimate unavailable']]) {
        const cell = document.createElement('span'); cell.textContent = text; cell.title = title; label.append(cell)
      }
      scroll.append(label)
    }
  }
  return { render }
}
