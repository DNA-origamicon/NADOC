import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'
import { elementStatus, projectAtoms, STATUS, validateSnapshot } from './cpd_progress_model.js'
import './cpd_progress.css'

const svgElement = (name, attrs) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name)
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v)
  return node
}

export function showCpdProgress({ load = () => fetch('/cpd-progress.json', { cache: 'no-store' }).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}) } = {}) {
  let data, model, selection, yaw = 0, pitch = 0, zoom = 1, drag, pinned = false, generation = 0
  const body = el('div', { className: 'cpd-progress' })
  const status = el('p', { text: 'Loading CPD evidence…', attrs: { role: 'status' } })
  const select = el('select', { attrs: { 'aria-label': 'Photoproduct structure' } })
  const scope = el('select', { attrs: { 'aria-label': 'Validation scope' }, children: [
    el('option', { text: 'Overall readiness', attrs: { value: 'overall' } }),
    el('option', { text: 'Available local checks', attrs: { value: 'local' } }),
  ] })
  const refresh = el('button', { text: 'Reload evidence', on: { click: () => reload() } })
  const reset = el('button', { text: 'Reset view', on: { click: () => { yaw = pitch = 0; zoom = 1; draw() } } })
  const unpin = el('button', { text: 'Unpin details', on: { click: () => { pinned = false; unpin.hidden = true } } }); unpin.hidden = true
  const svg = svgElement('svg', { viewBox: '0 0 660 480', 'aria-label': 'Interactive CPD atomic structure', role: 'group' })
  const details = el('section', { className: 'cpd-progress__details', attrs: { 'aria-label': 'Atom or bond checks' } })
  const description = el('p')
  const hint = el('p', { text: 'Drag to rotate · scroll to zoom · hover or Tab for details · click or Enter to pin.' })
  const legend = el('div', { className: 'cpd-progress__legend', children: Object.entries(STATUS).map(([, s]) => el('span', { text: `● ${s.label}`, attrs: { style: `color:${s.color}` } })) })
  body.append(status, el('div', { className: 'cpd-progress__toolbar', children: [select, scope, refresh, reset, unpin] }), legend,
    el('p', { text: 'Green means all available local checks pass only when that scope is selected. Overall readiness stays incomplete until DNA validation is complete.' }),
    description, el('div', { className: 'cpd-progress__layout', children: [svg, details] }), hint)
  const modal = createModal({ title: 'CPD progress', size: 'xl', body, className: 'cpd-progress-modal', onClose: () => { generation++; drag = null } })
  modal.open()

  function showDetails(item, kind) {
    selection = { item, kind }
    const local = item.checks ?? []
    const state = STATUS[elementStatus(local, scope.value === 'overall')]
    const heading = el('h3', { text: `${kind}: ${item.id}` })
    const summary = el('p', { text: state.label, attrs: { style: `color:${state.color}` } })
    details.replaceChildren(heading, summary)
    if (!local.length) details.append(el('p', { text: 'No atom-specific or bond-specific check has been recorded. This is not a pass.' }))
    const render = checks => {
      for (const c of checks) {
        const card = el('div', { className: `cpd-progress__check cpd-progress__check--${c.state}`, children: [
          el('strong', { text: `${c.state.toUpperCase()} · ${c.label}` }),
          el('div', { text: c.value ?? 'No measurement recorded' }),
          ...(c.limit ? [el('div', { text: `Criterion: ${c.limit}` })] : []),
        ] })
        if (data.sources[c.evidence]) {
          const src = data.sources[c.evidence]
          card.append(el('details', { children: [el('summary', { text: 'Evidence source' }), el('code', { text: src.file }), el('code', { text: `SHA-256 ${src.sha256}` })] }))
        }
        details.append(card)
      }
    }
    render(local)
    details.append(el('h4', { text: 'Shared model checks and remaining work' }))
    render(model.checks)
  }

  function interactive(node, item, kind) {
    node.setAttribute('tabindex', '0'); node.setAttribute('role', 'button')
    node.setAttribute('aria-label', `${kind} ${item.id}: ${STATUS[elementStatus(item.checks, scope.value === 'overall')].label}`)
    const title = svgElement('title', {}); title.textContent = `${kind} ${item.id}`; node.append(title)
    node.addEventListener('pointerenter', () => { if (!drag && !pinned) showDetails(item, kind) })
    node.addEventListener('focus', () => { if (!pinned) showDetails(item, kind) })
    const pin = () => { pinned = true; unpin.hidden = false; showDetails(item, kind) }
    node.addEventListener('click', pin)
    node.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pin() } })
  }

  function draw() {
    if (!model) return
    const points = projectAtoms(model.atoms, yaw, pitch, zoom)
    const map = new Map(points.map(a => [a.id, a]))
    svg.replaceChildren()
    for (const b of model.bonds) {
      const [a, c] = b.atoms.map(id => map.get(id))
      const line = svgElement('line', { x1: a.x, y1: a.y, x2: c.x, y2: c.y, stroke: STATUS[elementStatus(b.checks, scope.value === 'overall')].color, 'stroke-width': 7, 'stroke-linecap': 'round', 'data-bond': b.id })
      interactive(line, b, 'Bond'); svg.append(line)
    }
    for (const a of points.sort((a, b) => a.z - b.z)) {
      const circle = svgElement('circle', { cx: a.x, cy: a.y, r: a.element === 'H' ? 4 : 8, fill: STATUS[elementStatus(a.checks, scope.value === 'overall')].color, stroke: '#101722', 'stroke-width': 1.5, 'data-atom': a.id })
      interactive(circle, a, 'Atom'); svg.append(circle)
      if (a.element !== 'H') { const text = svgElement('text', { x: a.x + 10, y: a.y - 8, fill: '#dce6f4', 'font-size': 11, 'pointer-events': 'none' }); text.textContent = a.id; svg.append(text) }
    }
  }
  function choose() {
    model = data.models.find(m => m.id === select.value) ?? data.models[0]
    yaw = pitch = 0; zoom = 1; pinned = false; unpin.hidden = true
    description.textContent = model.geometry
    draw(); showDetails(model.atoms[0], 'Atom')
  }
  select.addEventListener('change', choose)
  scope.addEventListener('change', () => { draw(); if (selection) showDetails(selection.item, selection.kind) })
  svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY }; svg.setPointerCapture?.(e.pointerId) })
  svg.addEventListener('pointermove', e => { if (!drag) return; yaw += (e.clientX - drag.x) * .012; pitch += (e.clientY - drag.y) * .012; drag = { x: e.clientX, y: e.clientY }; draw() })
  svg.addEventListener('pointerup', () => { drag = null })
  svg.addEventListener('pointercancel', () => { drag = null })
  svg.addEventListener('wheel', e => { e.preventDefault(); zoom = Math.max(.5, Math.min(3, zoom * (e.deltaY < 0 ? 1.1 : .9))); draw() }, { passive: false })
  async function reload() {
    const token = ++generation
    refresh.disabled = true; status.textContent = 'Loading CPD evidence…'
    try {
      const result = validateSnapshot(await load())
      if (!modal.isOpen() || token !== generation) return
      data = result
      select.replaceChildren(...data.models.map(m => el('option', { text: m.label, attrs: { value: m.id } })))
      status.textContent = `Evidence snapshot: ${new Date(data.generatedAt).toLocaleString()}. ${data.summary} This is a saved evidence report, not live job monitoring.`
      choose()
    } catch (e) {
      if (modal.isOpen() && token === generation) { model = null; svg.replaceChildren(); details.replaceChildren(); status.textContent = `Could not load CPD progress: ${e.message}. Reload to retry.` }
    } finally { if (token === generation) refresh.disabled = false }
  }
  reload()
  return modal
}
