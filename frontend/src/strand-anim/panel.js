/**
 * Right-sidebar parameter panel for the strand-animation playground.
 *
 * Builds labeled rows (number / range / select / checkbox / segmented toggle)
 * wired to the param state. Number inputs get drag-scrub. Calls onChange after
 * any edit so the app can rebuild geometry; refresh() pushes state → controls
 * (used when the ticker advances φ).
 */

import { el } from '../ui/primitives/dom.js'
import { createPanelSection } from '../ui/primitives/panel_section.js'
import { attachAllDragScrub } from '../input/drag_scrub.js'

/**
 * @param {HTMLElement} panelRoot
 * @param {ReturnType<import('./params.js').createParamState>} state
 * @param {object} io
 * @param {() => void} io.onChange       - param edited (rebuild geometry)
 * @param {() => void} io.onPlayToggle   - Play/Pause button pressed
 * @param {() => boolean} io.isPlaying
 * @returns {{ refresh:()=>void }}
 */
export function buildPanel(panelRoot, state, { onChange, onPlayToggle, isPlaying }) {
  const _refreshers = []   // fns that pull state → control value

  // Geometry rebuild + label refresh after any edit (refresh is hoisted).
  function emitChange() { onChange(); refresh() }

  // ── row builders ──────────────────────────────────────────────────────────
  function numberRow(parent, label, key, { min, max, step, unit }) {
    const input = el('input', {
      className: 'sa-num',
      attrs: { type: 'number', min, max, step, value: state.get(key) },
    })
    input.addEventListener('input', () => {
      const v = parseFloat(input.value)
      if (!Number.isNaN(v)) { state.set(key, v); emitChange() }
    })
    _refreshers.push(() => { if (document.activeElement !== input) input.value = state.get(key) })
    parent.appendChild(el('div', {
      className: 'sa-row',
      children: [
        el('label', { className: 'sa-lbl', text: label }),
        el('div', { className: 'sa-ctl', children: [input, unit ? el('span', { className: 'sa-unit', text: unit }) : null] }),
      ],
    }))
  }

  function rangeRow(parent, label, key, { min, max, step }) {
    const range = el('input', { className: 'sa-range', attrs: { type: 'range', min, max, step, value: state.get(key) } })
    const num = el('input', { className: 'sa-num sa-num--sm', attrs: { type: 'number', min, max, step, value: state.get(key) } })
    const sync = (v) => { state.set(key, v); range.value = v; num.value = (+v).toFixed(3); emitChange() }
    range.addEventListener('input', () => sync(parseFloat(range.value)))
    num.addEventListener('input', () => { const v = parseFloat(num.value); if (!Number.isNaN(v)) sync(v) })
    _refreshers.push(() => {
      const v = state.get(key)
      range.value = v
      if (document.activeElement !== num) num.value = (+v).toFixed(3)
    })
    parent.appendChild(el('div', {
      className: 'sa-row sa-row--stack',
      children: [
        el('div', { className: 'sa-row', children: [el('label', { className: 'sa-lbl', text: label }), el('div', { className: 'sa-ctl', children: [num] })] }),
        range,
      ],
    }))
  }

  function selectRow(parent, label, key, options) {
    const sel = el('select', { className: 'sa-sel' })
    for (const o of options) {
      const opt = el('option', { text: o.label, attrs: { value: o.value } })
      if (o.value === state.get(key)) opt.selected = true
      sel.appendChild(opt)
    }
    sel.addEventListener('change', () => { state.set(key, sel.value); emitChange() })
    _refreshers.push(() => { sel.value = state.get(key) })
    parent.appendChild(el('div', { className: 'sa-row', children: [el('label', { className: 'sa-lbl', text: label }), el('div', { className: 'sa-ctl', children: [sel] })] }))
  }

  function checkRow(parent, label, key) {
    const box = el('input', { className: 'sa-chk', attrs: { type: 'checkbox' } })
    box.checked = !!state.get(key)
    box.addEventListener('change', () => { state.set(key, box.checked); emitChange() })
    _refreshers.push(() => { box.checked = !!state.get(key) })
    parent.appendChild(el('div', { className: 'sa-row', children: [el('label', { className: 'sa-lbl', text: label }), el('div', { className: 'sa-ctl', children: [box] })] }))
  }

  function segmented(parent, label, key, options) {
    const btns = []
    const wrap = el('div', { className: 'sa-seg' })
    for (const o of options) {
      const b = el('button', { className: 'sa-seg-btn', text: o.label, attrs: { type: 'button' } })
      b.addEventListener('click', () => { state.set(key, o.value); paint(); emitChange() })
      btns.push({ b, v: o.value }); wrap.appendChild(b)
    }
    function paint() { btns.forEach(({ b, v }) => b.classList.toggle('is-active', v === state.get(key))) }
    paint()
    _refreshers.push(paint)
    parent.appendChild(el('div', { className: 'sa-row sa-row--stack', children: [el('label', { className: 'sa-lbl', text: label }), wrap] }))
  }

  // ── sections ────────────────────────────────────────────────────────────--
  const sForm = createPanelSection({ title: 'Scenario & form', collapsible: true })
  segmented(sForm.body, 'Scenario', 'scenario', [
    { label: 'Unzip', value: 'unzip' },
    { label: 'Strand displacement', value: 'displacement' },
  ])
  segmented(sForm.body, 'Representation', 'form', [
    { label: 'Straight line', value: 'straight' },
    { label: 'Helical', value: 'helical' },
  ])

  const sRx = createPanelSection({ title: 'Reaction coordinate', collapsible: true })
  rangeRow(sRx.body, 'φ (fraction paired)', 'phi', { min: 0, max: 1, step: 0.001 })
  const phiLabelEl = sRx.body.querySelector('.sa-lbl')   // relabeled per scenario in refresh()
  selectRow(sRx.body, 'Play direction', 'direction', [
    { label: 'Dehybridize (1→0)', value: 'dehybridize' },
    { label: 'Hybridize (0→1)', value: 'hybridize' },
  ])

  const sAnim = createPanelSection({ title: 'Animation', collapsible: true })
  const playBtn = el('button', { className: 'sa-play', attrs: { type: 'button' }, text: '▶ Play' })
  playBtn.addEventListener('click', () => onPlayToggle())
  sAnim.body.appendChild(el('div', { className: 'sa-row sa-row--stack', children: [playBtn] }))
  numberRow(sAnim.body, 'Speed', 'speed', { min: 0.02, max: 2, step: 0.02, unit: 'φ/s' })
  selectRow(sAnim.body, 'Easing', 'easing', [
    { label: 'linear', value: 'linear' },
    { label: 'ease-in', value: 'ease-in' },
    { label: 'ease-out', value: 'ease-out' },
    { label: 'ease-in-out', value: 'ease-in-out' },
  ])
  checkRow(sAnim.body, 'Loop', 'loop')
  checkRow(sAnim.body, 'Bounce (ping-pong)', 'bounce')

  const sModel = createPanelSection({ title: 'Strand model', collapsible: true })
  numberRow(sModel.body, 'Base pairs (N)', 'N', { min: 2, max: 200, step: 1 })
  numberRow(sModel.body, 'Rise', 'rise', { min: 0.30, max: 0.45, step: 0.001, unit: 'nm/bp' })
  numberRow(sModel.body, 'Duplex width (W)', 'W', { min: 0.5, max: 4.0, step: 0.1, unit: 'nm' })
  numberRow(sModel.body, 'Splay angle (θ)', 'thetaDeg', { min: 0, max: 85, step: 1, unit: '°' })
  numberRow(sModel.body, 'Helix twist', 'twistDeg', { min: 0, max: 90, step: 0.1, unit: '°/bp' })
  numberRow(sModel.body, 'Melt width', 'meltBp', { min: 0, max: 6, step: 0.25, unit: 'bp' })
  numberRow(sModel.body, 'ssDNA stretch', 'armPull', { min: 1.0, max: 2.0, step: 0.05, unit: '×' })
  numberRow(sModel.body, 'Toehold (displacement)', 'toeholdBp', { min: 0, max: 20, step: 1, unit: 'bp' })
  selectRow(sModel.body, 'Unzip from', 'endFrom', [
    { label: 'Right end', value: 'right' },
    { label: 'Left end', value: 'left' },
  ])
  checkRow(sModel.body, 'Fork from centerline', 'forkToCenter')

  for (const s of [sForm, sRx, sAnim, sModel]) panelRoot.appendChild(s.root)
  attachAllDragScrub(panelRoot)

  function refresh() {
    _refreshers.forEach((fn) => fn())
    playBtn.textContent = isPlaying() ? '⏸ Pause' : '▶ Play'
    if (phiLabelEl) {
      phiLabelEl.textContent = state.get('scenario') === 'displacement'
        ? 'φ (invader bound: toehold → displaced)' : 'φ (fraction paired)'
    }
  }
  refresh()

  return { refresh }
}
