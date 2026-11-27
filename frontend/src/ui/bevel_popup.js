import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { bevelParameters, bevelPositionStep, bevelPositionNm, bevelPositionBp } from './bevel_parameters.js'

/** Shared NADOC popup, fields and buttons; calculation is owned by the tool. */
export function createBevelPopup({ onChange, onCancel, onApply, onSelect, onInvalid }) {
  const inputs = {}
  const fields = el('div', { className: 'def-fields' })
  const hint = el('p', { className: 'tool-picking-hint', text: 'Select a cluster.' })
  const selection = el('button', { className: 'btn btn--sm', text: 'Change selection',
    attrs: { type: 'button' }, on: { click: onSelect } })
  const parameters = el('fieldset', { className: 'tool-section', children: [el('legend', { text: 'Bevel' })] })
  const status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const progress = el('progress', { attrs: { max: 100, 'aria-label': 'Full bevel preview calculation' } })
  progress.hidden = true
  const apply = el('button', { className: 'def-btn primary', text: 'Apply',
    attrs: { type: 'button', disabled: true }, on: { click: onApply } })
  const cancel = el('button', { className: 'def-btn', text: 'Cancel', attrs: { type: 'button' }, on: { click: onCancel } })
  const panel = el('div', { id: 'bevel-panel', children: [fields,
    el('div', { className: 'def-btn-row', children: [cancel, apply] })] })
  panel.style.display = 'none'
  fields.append(hint, selection, parameters, el('p', { className: 'tool-help',
    text: '0° cuts perpendicular to the bundle. Removed material leaves open strand ends.' }), progress, status)
  const popup = createToolPopup({ panel, title: 'Bevel', onClose: onCancel, panelDisplay: 'flex' })
  let setting = false, valid = false, editing = false

  const end = el('select', { attrs: { id: 'bevel-trimEnd', 'aria-label': 'End to trim' },
    children: ['end', 'start'].map(value => el('option', { text: value === 'end' ? 'End (higher bp)' : 'Start (lower bp)', attrs: { value } })),
    on: { change: () => changed('trimEnd') } })
  parameters.append(el('div', { className: 'def-row', children: [el('label', { text: 'Trim:', attrs: { for: 'bevel-trimEnd' } }), end] }))

  function anchorSteps() {
    // Native spinners otherwise snap to multiples of step from the initial
    // value (or min), rather than adding a full increment to the typed value.
    for (const input of Object.values(inputs)) input.defaultValue = input.value
    inputs.angleDeg.min = String(Number(inputs.angleDeg.value) % 15)
  }

  function changed(name) {
    if (setting) return
    apply.disabled = true
    valid = false
    try {
      if (name === 'positionNm') inputs.positionBp.value = bevelPositionBp(inputs.positionNm.valueAsNumber)
      const params = bevelParameters({ trimEnd: end.value, ...Object.fromEntries(
        ['positionBp', 'angleDeg', 'directionDeg'].map(key => [key, inputs[key].valueAsNumber])) })
      inputs.positionNm.value = String(Number(bevelPositionNm(params.positionBp).toFixed(6)))
      inputs.directionDeg.value = String(params.directionDeg)
      anchorSteps()
      valid = true
      onChange(params)
    } catch (error) { valid = false; progress.hidden = true; status.textContent = error.message; onInvalid?.() }
  }
  for (const [name, label, unit, step, initial] of [
    ['positionBp', 'Plane position', 'bp', 8, 0],
    ['positionNm', 'Plane position', 'nm', 2.672, 0],
    ['angleDeg', 'Angle', '°', 15, 0],
    ['directionDeg', 'Direction', '°', 15, 0],
  ]) {
    const input = el('input', { attrs: { id: `bevel-${name}`, type: 'number', step, value: initial,
      'aria-label': `${label} (${unit})` }, on: { input: () => changed(name) } })
    if (name === 'angleDeg') { input.min = '0'; input.max = '89.999' }
    inputs[name] = input
    parameters.append(el('div', { className: 'def-row', children: [
      el('label', { text: `${label}:`, attrs: { for: input.id } }), input,
      el('span', { className: 'unit', text: unit }),
    ] }))
  }
  return {
    setEditing(value) { editing = !!value; selection.hidden = editing; popup.setTitle(editing ? 'Edit Bevel' : 'Bevel') },
    setBusy(value) { parameters.disabled = value || !valid; selection.disabled = value || editing; cancel.disabled = value; if (value) apply.disabled = true },
    open() { valid = false; parameters.disabled = true; apply.disabled = true; status.textContent = ''; progress.hidden = true; hint.textContent = 'Select a cluster.'; popup.show() },
    selected(label, lattice, values) {
      setting = true
      end.value = values.trimEnd ?? 'end'
      const step = bevelPositionStep(lattice)
      inputs.positionBp.step = String(step)
      inputs.positionNm.step = String(bevelPositionNm(step))
      for (const name of ['positionBp', 'angleDeg', 'directionDeg']) inputs[name].value = String(values[name])
      inputs.positionNm.value = String(Number(bevelPositionNm(values.positionBp).toFixed(6)))
      anchorSteps()
      hint.textContent = label
      parameters.disabled = false
      valid = true
      setting = false
    },
    calculating(percent, message) {
      apply.disabled = true; progress.hidden = false
      if (Number.isFinite(percent)) { progress.value = Math.max(0, Math.min(100, percent)); status.textContent = `${Math.round(progress.value)}% — ${message}` }
      else { progress.removeAttribute('value'); status.textContent = message }
    },
    error(message) { apply.disabled = true; progress.hidden = true; status.textContent = message },
    ready(message) { if (valid) { progress.hidden = true; apply.disabled = false; status.textContent = message } },
    hide() { popup.hide() },
    dispose() { popup.dispose() },
  }
}
