import { makeSpinner, statusBadge } from './job_status_symbol.js'
import '../styles/oxdna_thermal_job.css'

const expandedByList = new WeakMap()
const states = {
  completed: ['✓', 'Completed'], running: ['●', 'Running'], waiting: ['○', 'Queued'],
  skipped: ['↷', 'Skipped'], failed: ['!', 'Failed'], stopped: ['■', 'Stopped'], paused: ['Ⅱ', 'Paused'],
}

/** Expansion belongs to this list, and survives polling/rebuilding its DOM. */
export function thermalJobGroup(list, row, model, doc = document, onSelect, onContextMenu) {
  if (!model.thermalSteps) return row
  let expanded = expandedByList.get(list)
  if (!expanded) { expanded = new Set(); expandedByList.set(list, expanded) }
  const group = doc.createElement('div')
  group.className = 'thermal-job-group'
  const button = doc.createElement('button')
  button.type = 'button'
  button.className = 'thermal-job-toggle'
  const details = doc.createElement('div')
  details.className = 'thermal-job-details'
  details.style.marginLeft = `${(model.indentPx || 6) + 16}px`
  const summary = doc.createElement('div')
  summary.className = 'thermal-job-summary'
  summary.textContent = `${model.thermalSteps.filter(s => s.status === 'completed').length} / ${model.thermalSteps.length} temperature steps completed`
  const skipped = model.thermalSteps.filter(s => s.status === 'skipped').length
  if (skipped) summary.textContent += ` · ${skipped} skipped`
  details.append(summary)
  const children = doc.createElement('ol')
  children.setAttribute('aria-label', `Temperature steps for ${model.label}`)
  for (const step of model.thermalSteps) {
    const item = doc.createElement('li')
    item.className = 'thermal-job-step'
    item.dataset.thermalStage = step.name
    item.dataset.status = step.status
    const temperature = doc.createElement('span')
    temperature.textContent = `${step.temperature.replace(' °C', 'C')} - Run ${model.thermalNumber}`
    const state = doc.createElement('span')
    state.className = 'thermal-job-state'
    const [symbol, label] = states[step.status]
    if (['waiting', 'running'].includes(step.status)) state.append(makeSpinner(statusBadge(step.status === 'waiting' ? 'queued' : 'running').color, 11, doc))
    else state.append(symbol)
    state.append(` ${label}${step.reason ? ' (melt threshold)' : ''}`)
    item.title = `${step.name} · ${Number(step.steps || 0).toLocaleString()} scheduled steps`
    if (step.reason) item.title += ` · ${step.reason}`
    const select = doc.createElement('button')
    select.type = 'button'; select.className = 'thermal-job-select'
    select.setAttribute('aria-pressed', String(model.selected && model.thermalSelectedStage === step.name))
    select.append(temperature, state)
    select.addEventListener('click', event => { event.stopPropagation(); onSelect?.(model.jobId, step.name) })
    select.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') event.stopPropagation() })
    item.addEventListener('contextmenu', event => { event.stopPropagation(); onContextMenu?.(model.jobId, event) })
    item.append(select); children.append(item)
  }
  if (!model.thermalSteps.length) summary.textContent = 'Temperature steps are being prepared.'
  details.append(children)
  const paint = () => {
    const open = expanded.has(model.jobId)
    button.textContent = open ? '▾' : '▸'
    button.setAttribute('aria-expanded', String(open))
    button.setAttribute('aria-label', `${open ? 'Collapse' : 'Expand'} temperature steps for ${model.label}`)
    details.hidden = !open
  }
  button.addEventListener('click', event => {
    event.stopPropagation()
    if (expanded.has(model.jobId)) expanded.delete(model.jobId)
    else expanded.add(model.jobId)
    paint()
  })
  button.addEventListener('pointerdown', event => event.stopPropagation())
  // Keep application Enter/Space shortcuts from consuming native button activation.
  button.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') event.stopPropagation()
  })
  row.prepend(button)
  group.append(row, details)
  paint()
  return group
}
