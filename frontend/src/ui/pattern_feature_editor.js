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

function savedCopySelection(entry) {
  const params = entry.params ?? {}
  if (params._organization_copy?.version !== 1) return null
  // Historical inputs own these identities. Current groups can have different
  // membership or names, so this display intentionally performs no live lookup.
  const placementIds = entry.op_kind === 'linear-pattern' ? params.cluster_ids : [params.cluster_id]
  const rows = [['Placement IDs', placementIds], ['Copied group IDs', params._organization_copy.group_ids]]
  const content = rows.map(([label, value]) => {
    const ids = Array.isArray(value) ? value : []
    const visible = ids.slice(0, 16).map(id => typeof id === 'string'
      ? id.length > 128 ? `${id.slice(0, 128)}…` : id : '(invalid ID)')
    const remaining = ids.length - visible.length
    const text = visible.length ? `${visible.join(', ')}${remaining ? `; ${remaining} more` : ''}` : 'None'
    return el('p', { className: 'tool-help', text: `${label} (${ids.length}): ${text}` })
  })
  const section = toolSection('Saved copy selection', content)
  section.setAttribute('aria-label', 'Saved pattern copy selection')
  return section
}

export function editPatternFeature(entry, { onSave, isCurrent = () => true } = {}) {
  return new Promise(resolve => {
    let values = structuredClone(entry.params ?? {}), settled = false, saving = false, retired = false
    const finish = value => { if (!settled) { settled = true; window.removeEventListener('nadoc:document-reset', reset); resolve(value) } }
    const reset = () => { retired = true; modal.close() }
    const body = el('div', { className: 'cp-panel-body' })
    const savedSelection = savedCopySelection(entry)
    if (savedSelection) body.append(savedSelection)
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
    const save = async () => {
      if (saving || settled) return
      if (!isCurrent()) { error.hidden = false; error.textContent = 'The part changed. Reopen this pattern editor.'; return }
      const valid = entry.op_kind === 'linear-pattern' ? linearPatternOffsets(values) : patternAngles(values.instances, values.total_angle) && normalizedAxis(values.axis_point, values.axis_direction)
      if (!valid) {
        error.hidden = false
        error.textContent = entry.op_kind === 'linear-pattern' ? 'Use finite, nonzero vectors and spacing, and integer counts; at most 128 total instances. 2D directions must not be parallel.' : 'Use 1–128 instances, an angle greater than 0° and at most 360°, and a finite origin and nonzero axis direction.'
        return
      }
      if (!onSave) { finish(values); modal.close(); return }
      saving = true
      const controls = [...modal.root.querySelectorAll('input, select, button')]
      const disabled = controls.map(control => control.disabled)
      controls.forEach(control => { control.disabled = true })
      try {
        const result = await onSave(structuredClone(values))
        if (settled) return
        if (result == null) throw new Error('The pattern edit was not accepted. Your draft is unchanged.')
        saving = false; finish(values); modal.close()
      } catch (failure) {
        if (settled) return
        saving = false
        controls.forEach((control, i) => { control.disabled = disabled[i] })
        error.hidden = false; error.textContent = failure?.message || 'The pattern edit failed.'
      }
    }
    const modal = createModal({ title: `Edit ${entry.op_kind === 'linear-pattern' ? 'Linear' : 'Circular'} Pattern`, size: 'sm', body,
      actions: [createButton({ label: 'Cancel', onClick: () => { finish(null); modal.close() } }), createButton({ label: 'Save', variant: 'primary', onClick: save })],
      onClose: () => { if (saving && !retired) return false; finish(null) },
    })
    modal.root.setAttribute('aria-label', `Edit ${entry.op_kind === 'linear-pattern' ? 'Linear' : 'Circular'} Pattern`)
    modal.open()
    window.addEventListener('nadoc:document-reset', reset)
  })
}
