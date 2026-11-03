/** Transient PDF evidence with an optional read-only active-design sequence overlay. */
import { createModal } from './primitives/modal.js'
import './image_evaluation.css'
import { brickControls, createBrickOverlay } from './image_sequence_overlay.js'

let active = null
export function estimateIndices(columns, first = 0, step = 7, overrides = {}) {
  first = Number.isInteger(first) ? first : 0
  step = Number.isInteger(step) && step > 0 ? step : 7
  return columns.map((_, i) => Number.isInteger(overrides[i]) ? overrides[i] : first + i * step)
}

export function showImageEvaluation({ fetchImpl = globalThis.fetch } = {}) {
  if (active?.isOpen()) return active
  const body = document.createElement('div')
  body.className = 'image-evaluation'
  body.innerHTML = `
    <p>Evaluate a caDNAno-style vector diagram. BP indices are hypotheses until calibrated; no design is modified.</p>
    <div class="ie-toolbar"><label>Import PDF <input data-file type="file" accept="application/pdf,.pdf"></label>
      <button data-cancel disabled>Cancel import</button><span data-status role="status" aria-live="polite">Select a PDF (up to 25 MiB / 100 pages).</span></div>
    <details data-note-box hidden><summary>PDF scan notes</summary><div data-notes></div></details>
    <div class="ie-layout"><aside><h3>Recognized routing candidates</h3><div data-candidates></div></aside>
    <section class="ie-main"><div class="ie-toolbar">
      <label>First column BP <input data-first type="number" value="0" step="1"></label>
      <label>Assumed plane spacing <select data-step><option value="7">7 bp · honeycomb hypothesis</option><option value="8">8 bp · square hypothesis</option></select></label>
      <label>Zoom <input data-zoom type="range" min="0.5" max="4" step="0.1" value="1"></label>
      <button data-reset>Reset view</button><button data-export disabled>Export evidence JSON</button>
    </div><div class="ie-toolbar">
      <label><input data-layer="columns" type="checkbox" checked> Estimated indices</label>
      <label><input data-layer="junctions" type="checkbox" checked> Junction branches</label>
      <label><input data-layer="ends" type="checkbox"> Possible termini / nicks</label>
      <label><input data-layer="flags" type="checkbox" checked> Flags</label>
    </div>
    ${brickControls}
    <div data-viewport class="ie-viewport" tabindex="0" aria-label="Figure viewer; scroll to pan, use zoom control to enlarge"><div data-stage class="ie-stage"></div></div>
    <p class="ie-legend">Blue: estimated column · cyan: junction branch · red: possible terminus · amber: review flag. Select an annotation for evidence.</p>
    </section><aside><h3>Evidence and review</h3><p data-summary></p><p data-detail role="status">Select a figure to begin.</p>
      <div data-flags></div><details><summary>Column calibration</summary><p>Override individual column indices when evidence shows skipped planes. Values remain user-supplied estimates.</p><p data-calibration-warning role="alert"></p><div data-calibration></div></details>
      <details open><summary>Limits and assumptions</summary><ul data-limits></ul></details></aside></div>`
  const q = s => body.querySelector(s)
  let controller = null, revision = 0, result = null, figure = null, overrides = {}, selected = null
  const modal = createModal({ title: 'Image evaluation', size: 'xl', className: 'ie-modal', body,
    onClose: () => { brick.dispose(); revision++; controller?.abort(); result = null; figure = null; body.replaceChildren(); active = null } })
  active = modal
  const brick = createBrickOverlay({ body, fetchImpl, redraw: draw, getFigure: () => figure, getIndices: indices })
  const message = (node, text) => { node.textContent = text }
  function showDetail(text, key) { selected = key; message(q('[data-detail]'), text); draw() }
  function indices() { return estimateIndices(figure.columns, Number(q('[data-first]').value) || 0, Number(q('[data-step]').value), overrides) }
  function draw() {
    if (!figure) return
    const stage = q('[data-stage]'); stage.replaceChildren()
    stage.style.width = `${Number(q('[data-zoom]').value) * 100}%`
    stage.style.aspectRatio = String(figure.aspect)
    const img = document.createElement('img'); img.src = figure.image; img.alt = figure.label; img.draggable = false; stage.append(img)
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', '0 0 1000 1000'); svg.setAttribute('preserveAspectRatio', 'none'); stage.append(svg)
    function mark(tag, attrs, detail, key) {
      const el = document.createElementNS(svg.namespaceURI, tag)
      for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value)
      if (detail) {
        el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); el.setAttribute('aria-label', detail)
        const title = document.createElementNS(svg.namespaceURI, 'title'); title.textContent = detail; el.append(title)
        el.addEventListener('click', () => showDetail(detail, key))
        el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showDetail(detail, key) } })
        if (selected === key) el.classList.add('ie-selected')
      }
      svg.append(el); return el
    }
    const bp = indices()
    message(q('[data-calibration-warning]'), bp.some((value, i) => i > 0 && value <= bp[i - 1]) ? 'Conflicting calibration: column indices must increase from left to right.' : '')
    if (q('[data-layer="columns"]').checked) figure.columns.forEach((x, i) => {
      mark('line', { x1: x, x2: x, y1: 22, y2: 995, stroke: '#226dca', 'stroke-width': 1, opacity: .4 })
      const label = mark('text', { x, y: 17, fill: '#163b9d', 'font-size': 10, 'text-anchor': 'middle' }, `Column ${i}: estimated BP ${bp[i]}. ${i in overrides ? 'User override.' : 'Assumes successive lattice planes.'}`, `col${i}`)
      label.append(document.createTextNode(`~${bp[i]}`))
    })
    if (q('[data-layer="junctions"]').checked) figure.crossovers.forEach((c, i) => {
      const estimated = bp[c.column] + (c.side === 'right' ? 1 : 0)
      mark('line', { x1: c.x, x2: c.x, y1: c.y1, y2: c.y2, stroke: '#009ca7', 'stroke-width': 2, opacity: .7 },
        `Rows ${c.rows.join('–')}, ${c.side} branch; estimated BP ${estimated}. Branch polarity and helix identities require confirmation.`, `xo${i}`)
    })
    brick.draw(mark)
    if (q('[data-layer="ends"]').checked) figure.endpoints.forEach((p, i) => mark('circle', { cx: p.x, cy: p.y, r: 2.7, fill: '#ce3248' }, `Row ${p.row}: PDF path endpoint, possible nick or terminus. A graphic path break is not proof of a backbone break.`, `end${i}`))
    if (q('[data-layer="flags"]').checked) figure.flags.forEach((f, i) => mark('circle', { cx: f.x, cy: f.y, r: selected === `flag${i}` ? 7 : 4, fill: '#f4a51c', stroke: '#704000', 'stroke-width': .7 }, f.detail, `flag${i}`))
  }
  function calibration() {
    const host = q('[data-calibration]'); host.replaceChildren()
    indices().forEach((bp, i) => {
      const label = document.createElement('label'); label.textContent = `Column ${i} `
      const input = document.createElement('input'); input.type = 'number'; input.step = '1'; input.value = bp; input.setAttribute('aria-label', `BP index for column ${i}`)
      input.addEventListener('change', () => { const value = Number(input.value); if (input.value !== '' && Number.isInteger(value)) overrides[i] = value; else delete overrides[i]; draw() })
      label.append(input); host.append(label)
    })
  }
  function select(item) {
    figure = item; brick.selectFigure(); overrides = {}; selected = null; q('[data-zoom]').value = '1'
    message(q('[data-summary]'), `${item.rows.length} inferred rows · ${item.columns.length} junction columns · ${item.crossovers.length} branches · ${item.path_count} graphic paths (not a verified strand count).`)
    message(q('[data-detail]'), (item.page_captions || []).join(' | ') || 'No text caption extracted. Confirm the selected diagram.')
    const host = q('[data-flags]'); host.replaceChildren()
    item.flags.forEach((f, i) => { const button = document.createElement('button'); button.textContent = `${f.kind}: ${f.detail}`; button.addEventListener('click', () => {
      showDetail(f.detail, `flag${i}`)
      const stage = q('[data-stage]'), view = q('[data-viewport]')
      view.scrollTo?.({ left: stage.clientWidth * f.x / 1000 - view.clientWidth / 2, top: stage.clientHeight * f.y / 1000 - view.clientHeight / 2, behavior: 'smooth' })
    }); host.append(button) })
    const limits = q('[data-limits]'); limits.replaceChildren()
    item.limitations.forEach(text => { const li = document.createElement('li'); li.textContent = text; limits.append(li) })
    for (const button of q('[data-candidates]').children) button.setAttribute('aria-pressed', String(button.dataset.id === item.id))
    q('[data-export]').disabled = false; calibration(); draw()
  }
  q('[data-file]').addEventListener('change', async event => {
    const file = event.target.files?.[0]; if (!file) return
    controller?.abort(); const current = ++revision; controller = new AbortController()
    if (file.size > 25 * 1024 * 1024) { message(q('[data-status]'), 'PDF exceeds the 25 MiB limit.'); return }
    q('[data-cancel]').disabled = false; message(q('[data-status]'), 'Scanning PDF vector paths…')
    figure = null; brick.selectFigure(); result = null; q('[data-stage]').replaceChildren(); q('[data-candidates]').replaceChildren(); q('[data-flags]').replaceChildren(); q('[data-calibration]').replaceChildren(); q('[data-limits]').replaceChildren(); message(q('[data-summary]'), ''); message(q('[data-detail]'), ''); message(q('[data-notes]'), ''); q('[data-export]').disabled = true
    try {
      const response = await fetchImpl('/api/image-evaluation', { method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file, signal: controller.signal })
      const payload = await response.json()
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'PDF evaluation failed.')
      if (revision !== current) return
      result = payload
      message(q('[data-status]'), `${payload.figures.length} routing candidate(s) found. ${payload.figures.length ? 'Choose a figure below.' : 'No supported vector routing recognized; try the original supplement PDF.'}`)
      message(q('[data-notes]'), payload.notes.join(' ')); q('[data-note-box]').hidden = payload.notes.length === 0
      payload.figures.forEach(item => {
        const button = document.createElement('button'); button.dataset.id = item.id
        const img = document.createElement('img'); img.src = item.image; img.alt = ''; button.append(img, document.createTextNode(`${item.label} · ${item.rows.length} rows`)); button.addEventListener('click', () => select(item)); q('[data-candidates]').append(button)
      })
    } catch (error) { if (revision === current) message(q('[data-status]'), error.name === 'AbortError' ? 'Import canceled.' : error.message) }
    finally { if (revision === current) q('[data-cancel]').disabled = true }
  })
  q('[data-cancel]').addEventListener('click', () => controller?.abort())
  for (const selector of ['[data-first]', '[data-step]']) q(selector).addEventListener('change', () => { if (figure) { overrides = {}; calibration(); draw() } })
  q('[data-zoom]').addEventListener('input', draw)
  body.querySelectorAll('[data-layer]').forEach(input => input.addEventListener('change', draw))
  q('[data-reset]').addEventListener('click', () => { q('[data-zoom]').value = '1'; q('[data-viewport]').scrollTo?.(0, 0); draw() })
  q('[data-export]').addEventListener('click', () => {
    if (!figure) return
    const { image, ...evidence } = figure
    const blob = new Blob([JSON.stringify({ method: result.method, source_sha256: result.source_sha256, evidence, sequence_overlay: brick.evidence(), calibration: { first: Number(q('[data-first]').value), step: Number(q('[data-step]').value), overrides, indices: indices(), status: 'unverified hypothesis' } }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `image-evaluation-${figure.id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  modal.open(); return modal
}
