import { createModal } from './primitives/modal.js'
import { createButton } from './primitives/button.js'
import { el } from './primitives/dom.js'
import { createLinearPatternControls, linearPatternSection } from './linear_pattern_controls.js'
import { toolSection } from './tool_sections.js'
import { linearPatternOffsets } from './linear_pattern_math.js'
import { patternAngles } from './circular_pattern_math.js'
import { normalizedAxis } from './circular_pattern_panel.js'
import './circular_pattern_panel.css'

export function isPatternFeature(kind) {
  return kind === 'circular-pattern' || kind === 'linear-pattern'
}

export function editPatternFeature(entry) {
  return new Promise(resolve => {
    let values = structuredClone(entry.params ?? {}), settled = false
    const finish = value => { if (!settled) { settled = true; resolve(value) } }
    const body = el('div', { className: 'cp-panel-body' })
    const error = el('div', { className: 'cp-readout', attrs: { 'aria-live': 'polite' } })
    error.hidden = true
    if (entry.op_kind === 'linear-pattern') {
      const controls = createLinearPatternControls(values, next => { values = next })
      values = controls.getValues()
      controls.element.append(linearPatternSection('Info', [el('p', { className: 'lp-help', text: 'Custom vectors are normalized; spacing is in nm. 2D directions must not be parallel.' }), error]))
      body.append(controls.element)
    } else {
      const controls = el('div', { className: 'cp-controls' })
      function number(label, value, change, integer = false) {
        return el('label', { children: [label, el('input', { className: 'input input--sm', attrs: { type: 'number', step: integer ? '1' : 'any', value, 'aria-label': label }, on: { input: event => change(event.target.value === '' ? NaN : Number(event.target.value)) } })] })
      }
      controls.append(toolSection('Pattern', [el('div', { className: 'tool-fields', children: [number('Instances', values.instances, v => { values.instances = v }, true), number('Total angle (degrees)', values.total_angle, v => { values.total_angle = v })] })]))
      for (const [key, title] of [['axis_point', 'Axis origin (nm)'], ['axis_direction', 'Axis direction']]) {
        const fields = el('div', { className: 'tool-fields' })
        for (const [i, axis] of ['X', 'Y', 'Z'].entries()) {
          const field = number(`${title} ${axis}`, values[key][i], v => { values[key][i] = v })
          field.firstChild.textContent = axis
          fields.append(field)
        }
        controls.append(toolSection(title, [fields]))
      }
      controls.append(toolSection('Info', [el('p', { className: 'tool-help', text: 'Counts include the original. The axis direction is normalized.' }), error]))
      body.append(controls)
    }
    const save = () => {
      const valid = entry.op_kind === 'linear-pattern' ? linearPatternOffsets(values) : patternAngles(values.instances, values.total_angle) && normalizedAxis(values.axis_point, values.axis_direction)
      if (!valid) {
        error.hidden = false
        error.textContent = entry.op_kind === 'linear-pattern' ? 'Use finite, nonzero vectors and spacing, and integer counts; at most 128 total instances. 2D directions must not be parallel.' : 'Use 1–128 instances, an angle greater than 0° and at most 360°, and a finite origin and nonzero axis direction.'
        return
      }
      finish(values); modal.close()
    }
    const modal = createModal({ title: `Edit ${entry.op_kind === 'linear-pattern' ? 'Linear' : 'Circular'} Pattern`, size: 'sm', body,
      actions: [createButton({ label: 'Cancel', onClick: () => { finish(null); modal.close() } }), createButton({ label: 'Save', variant: 'primary', onClick: save })],
      onClose: () => finish(null),
    })
    modal.root.setAttribute('aria-label', `Edit ${entry.op_kind === 'linear-pattern' ? 'Linear' : 'Circular'} Pattern`)
    modal.open()
  })
}
