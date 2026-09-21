import { createModal } from './primitives/modal.js'
import { el } from './primitives/dom.js'
import { attachmentMetrics, elementStatus, STATUS, validateSnapshot } from './cpd_progress_model.js'
import { drawStructure, svgElement } from './cpd_progress_diagram.js'
import './cpd_progress.css'

export function showCpdProgress({ load = () => fetch('/cpd-progress.json', { cache: 'no-store' }).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}) } = {}) {
  let data, model, selection, yaw = -.35, pitch = .6, zoom = 1, drag, pinned = false, generation = 0, radius
  let torsions = [0, 0]
  const body = el('div', { className: 'cpd-progress' })
  const status = el('p', { text: 'Loading CPD evidence…', attrs: { role: 'status' } })
  const select = el('select', { attrs: { 'aria-label': 'Photoproduct structure' } })
  const scope = el('select', { attrs: { 'aria-label': 'Validation scope' }, children: [
    el('option', { text: 'Overall readiness', attrs: { value: 'overall' } }),
    el('option', { text: 'Available local checks', attrs: { value: 'local' } }),
  ] })
  const refresh = el('button', { text: 'Reload evidence', on: { click: () => reload() } })
  const reset = el('button', { text: 'Reset view', on: { click: () => { yaw = -.35; pitch = .6; zoom = 1; resetTorsions(); draw() } } })
  const unpin = el('button', { text: 'Unpin details', on: { click: () => { pinned = false; unpin.hidden = true } } }); unpin.hidden = true
  const svg = svgElement('svg', { viewBox: '0 0 660 480', 'aria-label': 'Interactive CPD atomic structure', role: 'group' })
  const details = el('section', { className: 'cpd-progress__details', attrs: { 'aria-label': 'Atom or bond checks' } })
  const description = el('p')
  const gallery = el('div', { className: 'cpd-progress__gallery', attrs: { 'aria-label': 'All eight CPD isomers' } })
  const context = el('input', { attrs: { type: 'checkbox', checked: true }, on: { change: () => draw() } })
  const metrics = el('p', { className: 'cpd-progress__metrics', attrs: { 'data-cpd-metrics': '' } })
  const torsionSliders = [1, 2].map(endpoint => {
    const value = el('output', { text: '0°' })
    const slider = el('input', { attrs: { type: 'range', min: -180, max: 180, step: 5, value: 0, 'aria-label': `Endpoint ${endpoint} sugar rotation` }, on: { input: e => {
      torsions[endpoint - 1] = Number(e.target.value); value.textContent = `${e.target.value}°`; draw()
    } } })
    return { slider, value, label: el('label', { children: [`${endpoint} · sugar rotation `, slider, value] }) }
  })
  const contextControls = el('div', { className: 'cpd-progress__context', children: [
    el('label', { children: [context, ' Show sugar–phosphate context'] }), ...torsionSliders.map(s => s.label),
  ] })
  const contextLegend = el('p', { className: 'cpd-progress__context-legend', children: [
    el('span', { text: '● Endpoint 1', attrs: { style: 'color:#69c9ff' } }), ' · ',
    el('span', { text: '● Endpoint 2', attrs: { style: 'color:#d0a2ff' } }),
    ' · pale bars: CPD crosslinks · outlined O5′: NADOC backbone bead · dashed arrows: local 5′/3′ exits. Colors identify endpoints, not validation.',
  ] })
  const hint = el('p', { text: 'Drag to rotate · scroll to zoom · hover or Tab for details · click or Enter to pin.' })
  const legend = el('div', { className: 'cpd-progress__legend', children: Object.entries(STATUS).map(([, s]) => el('span', { text: `● ${s.label}`, attrs: { style: `color:${s.color}` } })) })
  const validationHint = el('p', { text: 'Green means all available local checks pass only when that scope is selected. Overall readiness stays incomplete until DNA validation is complete.' })
  body.append(status, gallery, el('div', { className: 'cpd-progress__toolbar', children: [select, scope, refresh, reset, unpin] }), legend,
    validationHint,
    description, contextControls, contextLegend, metrics, el('div', { className: 'cpd-progress__layout', children: [svg, details] }), hint)
  const modal = createModal({ title: 'CPD progress', size: 'xl', body, className: 'cpd-progress-modal', onClose: () => { generation++; drag = null } })
  modal.open()

  function showDetails(item, kind) {
    selection = { item, kind }
    const local = item.checks ?? []
    const state = STATUS[elementStatus(local, scope.value === 'overall')]
    const heading = el('h3', { text: `${kind}: ${item.id}` })
    const summary = el('p', { text: state.label, attrs: { style: `color:${state.color}` } })
    details.replaceChildren(heading, summary)
    if (model.stereochemistry) details.append(el('p', { text: `${model.qualification}. Ordered C5 configurations: ${model.orderedC5.join(' / ')}. Endpoints 1 and 2 keep their identities; this preview does not assume that they belong to the same strand.` }))
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
    const atoms = drawStructure(svg, model, { yaw, pitch, zoom: zoom * (model.stereochemistry ? 1.35 : 1), radius, context: context.checked, torsions, overall: scope.value === 'overall', interactive })
    if (model.stereochemistry) {
      const m = attachmentMetrics(atoms)
      metrics.textContent = `C1′ separation: ${m.c1.toFixed(2)} Å · O5′ separation: ${m.o5.toFixed(2)} Å · local P→O3′ direction angle: ${m.angle.toFixed(0)}°. These describe this conformer only.`
    }
  }
  function resetTorsions() {
    torsions = [0, 0]
    for (const s of torsionSliders) { s.slider.value = 0; s.value.textContent = '0°' }
  }
  function choose() {
    model = [...(data.isomers ?? []), ...data.models].find(m => m.id === select.value) ?? data.models[0]
    pinned = false; unpin.hidden = true; resetTorsions()
    const isomer = Boolean(model.stereochemistry)
    for (const node of [contextControls, contextLegend, metrics]) node.hidden = !isomer
    legend.hidden = validationHint.hidden = isomer; scope.disabled = isomer
    for (const card of gallery.children) card.setAttribute('aria-pressed', String(card.dataset.isomer === model.id))
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
      const previous = select.value
      const group = (label, models) => el('optgroup', { attrs: { label }, children: models.map(m => el('option', { text: m.label, attrs: { value: m.id } })) })
      select.replaceChildren(...(data.isomers?.length ? [group('All isomers · DNA context', data.isomers)] : []), group('Evidence studies · model fragments', data.models))
      if ([...(data.isomers ?? []), ...data.models].some(m => m.id === previous)) select.value = previous
      // Shared origin and scale make the core orientations directly comparable.
      // Leave space for sugar rotations and the labeled exit arrows.
      radius = Math.max(12, ...(data.isomers ?? []).flatMap(m => m.atoms.map(a => Math.hypot(...a.position) + 4)))
      gallery.replaceChildren(...(data.isomers ?? []).map(m => {
        const thumbnail = svgElement('svg', { viewBox: '0 0 660 480', 'aria-hidden': 'true' })
        drawStructure(thumbnail, m, { radius, zoom: 1.35, miniature: true })
        return el('button', { className: 'cpd-progress__isomer', dataset: { isomer: m.id }, attrs: { 'aria-label': `Inspect ${m.label}`, 'aria-pressed': false }, children: [
          thumbnail, el('strong', { text: m.label.replace(' TT-CPD', '') }), el('small', { text: m.qualification }),
        ], on: { click: () => { select.value = m.id; choose() } } })
      }))
      status.textContent = `Evidence snapshot: ${new Date(data.generatedAt).toLocaleString()}. ${data.summary} This is a saved evidence report, not live job monitoring.`
      choose()
    } catch (e) {
      if (modal.isOpen() && token === generation) { model = null; gallery.replaceChildren(); svg.replaceChildren(); details.replaceChildren(); status.textContent = `Could not load CPD progress: ${e.message}. Reload to retry.` }
    } finally { if (token === generation) refresh.disabled = false }
  }
  reload()
  return modal
}
