/** Help → Bundle T-junctions: an independent, interactive routing concept. */
import { buildTJunctionPreviewModel, T_JUNCTION_SOURCES } from '../design/t_junction_preview.js'
import { createTJunctionPreviewViewer } from '../scene/t_junction_preview.js'
import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import './t_junction_help.css'

const PRESETS = [
  { id: 'right', label: '90° T', angleDeg: 90, azimuthDeg: 0, attachment: 0.5 },
  { id: 'acute', label: '60°', angleDeg: 60, azimuthDeg: 0, attachment: 0.5 },
  { id: 'obtuse', label: '120°', angleDeg: 120, azimuthDeg: 0, attachment: 0.5 },
  { id: 'offset', label: 'Off-center', angleDeg: 90, azimuthDeg: 0, attachment: 0.3 },
  { id: 'spatial', label: 'Spatial', angleDeg: 90, azimuthDeg: 45, attachment: 0.5 },
]
let active = null
let nextId = 0

export function showTJunctionHelp({ viewerFactory = createTJunctionPreviewViewer } = {}) {
  if (active?.isOpen()) { active.root.querySelector('button')?.focus(); return active }
  const priorFocus = document.activeElement
  const prefix = `tjh-${++nextId}`
  const body = el('div', { className: 'tjh-body' })
  body.innerHTML = `
    <p class="tjh-intro" id="${prefix}-intro">Explore how a branch bundle can join the side of another bundle through two scaffold connections.</p>
    <div class="tjh-layout">
      <div class="tjh-controls">
        <fieldset class="tjh-presets"><legend>Junction shape</legend><div class="tjh-preset-list"></div></fieldset>
        <div class="tjh-sliders">
          <label class="tjh-field" for="${prefix}-angle"><span>Desired angle <output data-readout="angleDeg" for="${prefix}-angle"></output></span><input id="${prefix}-angle" data-param="angleDeg" type="range" min="30" max="150" step="1" value="90"></label>
          <label class="tjh-field" for="${prefix}-azimuth"><span>Out-of-plane rotation <output data-readout="azimuthDeg" for="${prefix}-azimuth"></output></span><input id="${prefix}-azimuth" data-param="azimuthDeg" type="range" min="-60" max="60" step="1" value="0"></label>
          <label class="tjh-field" for="${prefix}-attachment"><span>Attachment position <output data-readout="attachment" for="${prefix}-attachment"></output></span><input id="${prefix}-attachment" data-param="attachment" type="range" min="0.2" max="0.8" step="0.01" value="0.5"></label>
        </div>
        <label class="tjh-field" for="${prefix}-stage"><span>Connection stage</span><select id="${prefix}-stage" data-control="stage"><option value="joined">Joined scaffold</option><option value="separate">Separate loops</option></select></label>
        <label class="tjh-field" for="${prefix}-view"><span>Show</span><select id="${prefix}-view" data-control="representation"><option value="both">Bundles + scaffold</option><option value="bundles">Bundles</option><option value="scaffold">Scaffold</option></select></label>
        <label class="tjh-check"><input data-control="highlight" type="checkbox" checked> Highlight connection sites</label>
        <button class="btn tjh-reset" type="button" data-action="reset">Reset view</button>
      </div>
      <section class="tjh-scene-column" aria-label="Junction preview">
        <div class="tjh-viewer" data-tjunction-viewer></div>
        <p class="tjh-view-hint">Drag to orbit · scroll to zoom · focus the view and use arrow keys to rotate</p>
        <div class="tjh-legend" aria-label="Preview colors"><span><i class="tjh-swatch tjh-swatch--body"></i>Body bundle</span><span><i class="tjh-swatch tjh-swatch--branch"></i>Branch bundle</span><span><i class="tjh-swatch tjh-swatch--bridge"></i>To branch</span><span><i class="tjh-swatch tjh-swatch--return"></i>Back to body</span><span><i class="tjh-swatch tjh-swatch--cut"></i>Segments opened</span></div>
        <div class="tjh-metrics" data-tjunction-metrics role="status" aria-live="polite" aria-atomic="true"></div>
      </section>
    </div>
    <div class="tjh-explanation" data-tjunction-explanation></div>
    <p class="tjh-limitation">One scaffold connection pair; linker lengths, helical phase, staples and joint rigidity are not validated.</p>
    <p class="tjh-sources">MagicDNA end-to-side bundle connection: <a href="${T_JUNCTION_SOURCES.paper}" target="_blank" rel="noopener noreferrer">Paper</a> · <a href="${T_JUNCTION_SOURCES.supplement}" target="_blank" rel="noopener noreferrer">Supplement</a> · <a href="${T_JUNCTION_SOURCES.code}" target="_blank" rel="noopener noreferrer">Source</a></p>`
  let params = { angleDeg: 90, azimuthDeg: 0, attachment: 0.5, joined: true }
  let options = { representation: 'both', highlightBridges: true }
  let model = buildTJunctionPreviewModel(params)
  let viewer = null
  let closed = false
  const modal = createModal({
    title: 'Routing concept preview · Bundle T-junctions',
    size: 'xl',
    className: 'tjh-modal',
    body,
    actions: [createButton({ label: 'Close', onClick: () => modal.close() })],
    onClose: () => {
      if (closed) return
      closed = true
      viewer?.dispose()
      viewer = null
      modal.root.removeEventListener('keydown', keyboard)
      active = null
      if (priorFocus?.isConnected) priorFocus.focus()
    },
  })
  const title = modal.header.querySelector('.modal__title')
  title.id = `${prefix}-title`
  modal.root.setAttribute('aria-labelledby', title.id)
  modal.root.setAttribute('aria-describedby', `${prefix}-intro`)
  modal.overlay.classList.add('tjh-overlay')

  function refresh() {
    model = buildTJunctionPreviewModel(params)
    for (const input of body.querySelectorAll('[data-param]')) input.value = String(params[input.dataset.param])
    for (const readout of body.querySelectorAll('[data-readout]')) {
      const key = readout.dataset.readout
      readout.textContent = key === 'attachment' ? `${Math.round(params[key] * 100)}% requested` : `${params[key]}°`
    }
    for (const button of body.querySelectorAll('[data-preset]')) {
      const preset = PRESETS.find(p => p.id === button.dataset.preset)
      button.setAttribute('aria-pressed', String(['angleDeg', 'azimuthDeg', 'attachment'].every(key => params[key] === preset[key])))
    }
    const cycles = model.routes.length
    const metrics = body.querySelector('[data-tjunction-metrics]')
    metrics.replaceChildren(
      el('strong', { text: `${cycles} scaffold ${cycles === 1 ? 'cycle' : 'cycles'}` }),
      el('span', { text: `${model.metrics.helixCount} helices` }),
      el('span', { text: `Side port bp ${model.params.portBp} (${Math.round(model.params.actualAttachment * 100)}%)` }),
      el('span', { text: `${model.bridges.length} scaffold bridges` }),
    )
    if (params.joined && Number.isFinite(model.metrics.maxBridgeSpanNm)) metrics.append(el('span', { text: `Longest bridge ${model.metrics.maxBridgeSpanNm.toFixed(1)} nm` }))
    body.querySelector('[data-tjunction-explanation]').textContent = model.explanation
    viewer?.update(model, options)
  }
  for (const preset of PRESETS) {
    const button = createButton({ label: preset.label, size: 'sm', onClick: () => {
      params = { ...params, angleDeg: preset.angleDeg, azimuthDeg: preset.azimuthDeg, attachment: preset.attachment }
      refresh()
      viewer?.resetView()
    } })
    button.dataset.preset = preset.id
    button.setAttribute('aria-pressed', 'false')
    body.querySelector('.tjh-preset-list').append(button)
  }
  for (const input of body.querySelectorAll('[data-param]')) input.addEventListener('input', () => {
    params = { ...params, [input.dataset.param]: Number(input.value) }
    refresh()
  })
  body.querySelector('[data-control="stage"]').addEventListener('change', event => {
    params = { ...params, joined: event.target.value === 'joined' }
    refresh()
  })
  body.querySelector('[data-control="representation"]').addEventListener('change', event => {
    options = { ...options, representation: event.target.value }
    refresh()
  })
  body.querySelector('[data-control="highlight"]').addEventListener('change', event => {
    options = { ...options, highlightBridges: event.target.checked }
    refresh()
  })
  body.querySelector('[data-action="reset"]').addEventListener('click', () => viewer?.resetView())

  function keyboard(event) {
    // Keep editor shortcuts from acting on the current document behind this dialog.
    event.stopPropagation()
    if (event.key === 'Escape') { event.preventDefault(); modal.close(); return }
    if (event.key !== 'Tab') return
    const focusable = [...modal.root.querySelectorAll('*')].filter(node => node.matches('button,input,select,a[href],[tabindex]') && !node.disabled && !node.hidden && node.tabIndex >= 0)
    const first = focusable[0], last = focusable.at(-1)
    if (event.shiftKey && (document.activeElement === first || !modal.root.contains(document.activeElement))) {
      event.preventDefault(); last?.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !modal.root.contains(document.activeElement))) {
      event.preventDefault(); first?.focus()
    }
  }
  modal.root.addEventListener('keydown', keyboard)
  modal.open()
  const host = body.querySelector('[data-tjunction-viewer]')
  try {
    viewer = viewerFactory(host, model, options)
  } catch (error) {
    host.replaceChildren(el('p', { className: 'tjh-render-error', text: `The 3D preview could not start: ${error?.message || error}`, attrs: { role: 'alert' } }))
  }
  refresh()
  body.querySelector('[data-preset="right"]')?.focus()
  active = { ...modal, getModel: () => model }
  return active
}
