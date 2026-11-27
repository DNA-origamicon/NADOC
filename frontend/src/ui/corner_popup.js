import { createToolPopup } from './tool_popup.js'
import { el } from './primitives/dom.js'
import { cornerParameters, cornerPositionStep, cornerPositionNm, cornerPositionBp } from './corner_parameters.js'

/** Shared NADOC popup, fields and buttons; calculation is owned by the tool. */
export function createCornerPopup({ onChange, onCancel, onApply, onSelect, onInvalid }) {
  const inputs = {}
  const fields = el('div', { className: 'def-fields' })
  const hint = el('p', { className: 'tool-picking-hint', text: 'Select a cluster.' })
  const selection = el('button', { className: 'btn btn--sm', text: 'Change selection',
    attrs: { type: 'button' }, on: { click: onSelect } })
  const parameters = el('fieldset', { className: 'tool-section', children: [el('legend', { text: 'Corner' })] })
  const status = el('p', { attrs: { role: 'status', 'aria-live': 'polite' } })
  const progress = el('progress', { attrs: { max: 100, 'aria-label': 'Full corner preview calculation' } })
  progress.hidden = true
  const apply = el('button', { className: 'def-btn primary', text: 'Apply',
    attrs: { type: 'button', disabled: true }, on: { click: onApply } })
  const cancel = el('button', { className: 'def-btn', text: 'Cancel', attrs: { type: 'button' }, on: { click: onCancel } })
  const panel = el('div', { id: 'corner-panel', children: [fields,
    el('div', { className: 'def-btn-row', children: [cancel, apply] })] })
  panel.style.display = 'none'
  fields.append(hint, selection, parameters, progress, status)
  const popup = createToolPopup({ panel, title: 'Corner', onClose: onCancel, panelDisplay: 'flex' })
  let setting = false, valid = false, editing = false

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
      if (name === 'positionNm') inputs.positionBp.value = cornerPositionBp(inputs.positionNm.valueAsNumber)
      const params = cornerParameters(Object.fromEntries(
        ['positionBp', 'angleDeg', 'directionDeg'].map(key => [key, inputs[key].valueAsNumber])))
      inputs.positionNm.value = String(Number(cornerPositionNm(params.positionBp).toFixed(6)))
      inputs.directionDeg.value = String(params.directionDeg)
      anchorSteps()
      valid = true
      onChange(params)
    } catch (error) { valid = false; progress.hidden = true; status.textContent = error.message; onInvalid?.() }
  }
  for (const [name, label, unit, step, initial] of [
    ['positionBp', 'Plane position', 'bp', 8, 0],
    ['positionNm', 'Plane position', 'nm', 2.672, 0],
    ['angleDeg', 'Angle', '°', 15, 90],
    ['directionDeg', 'Direction', '°', 15, 0],
  ]) {
    const input = el('input', { attrs: { id: `corner-${name}`, type: 'number', step, value: initial,
      'aria-label': `${label} (${unit})` }, on: { input: () => changed(name) } })
    if (name === 'angleDeg') { input.min = '0'; input.max = '179.999' }
    inputs[name] = input
    parameters.append(el('div', { className: 'def-row', children: [
      el('label', { text: `${label}:`, attrs: { for: input.id } }), input,
      el('span', { className: 'unit', text: unit }),
    ] }))
  }
  return {
    setEditing(value) { editing = !!value; selection.hidden = editing; popup.setTitle(editing ? 'Edit Corner' : 'Corner') },
    setBusy(value) { parameters.disabled = value || !valid; selection.disabled = value || editing; cancel.disabled = value; if (value) apply.disabled = true },
    open() { valid = false; parameters.disabled = true; apply.disabled = true; status.textContent = ''; progress.hidden = true; hint.textContent = 'Select a cluster.'; popup.show() },
    selected(label, lattice, values) {
      setting = true
      const step = cornerPositionStep(lattice)
      inputs.positionBp.step = String(step)
      inputs.positionNm.step = String(cornerPositionNm(step))
      for (const name of ['positionBp', 'angleDeg', 'directionDeg']) inputs[name].value = String(values[name])
      inputs.positionNm.value = String(Number(cornerPositionNm(values.positionBp).toFixed(6)))
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
