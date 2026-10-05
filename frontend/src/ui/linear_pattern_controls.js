import { el } from './primitives/dom.js'
import { linearPatternOffsets } from './linear_pattern_math.js'
import './linear_pattern.css'
import { toolSection } from './tool_sections.js'

export const linearPatternDefaults = { direction: 'X', vector: [1, 0, 0], spacing: 10, instances: 3, two_dimensional: false, direction2: 'Y', vector2: [0, 1, 0], spacing2: 10, instances2: 2 }

export function linearPatternSection(title, children = []) {
  const section = toolSection(title, children)
  section.classList.add('lp-section')
  return section
}

/** Shared by creation and feature editing, including custom vectors and unit steppers. */
export function createLinearPatternControls(initial, onChange) {
  const values = { ...linearPatternDefaults, ...initial,
    vector: [...(initial.vector ?? linearPatternDefaults.vector)], vector2: [...(initial.vector2 ?? linearPatternDefaults.vector2)] }
  const element = el('div', { className: 'cp-controls' })
  const buttons = [], customFields = []
  const getValues = () => {
    const result = { ...values, vector: [...values.vector], vector2: [...values.vector2] }
    // Unfinished hidden controls must not invalidate an otherwise valid pattern.
    if (!result.two_dimensional) {
      if (!Number.isInteger(result.instances2) || result.instances2 < 1 || result.instances2 > 128) result.instances2 = 2
      if (!Number.isFinite(result.spacing2) || result.spacing2 === 0) result.spacing2 = 10
    }
    for (const suffix of ['', '2']) {
      const inactive = result[`direction${suffix}`] !== 'Custom' || (suffix && !result.two_dimensional)
      if (inactive && !result[`vector${suffix}`].every(Number.isFinite)) result[`vector${suffix}`] = [...linearPatternDefaults[`vector${suffix}`]]
    }
    return result
  }
  function update() {
    second.hidden = !values.two_dimensional
    for (const [button, key, axis] of buttons) button.setAttribute('aria-pressed', String(values[key] === axis))
    for (const [fields, key] of customFields) fields.hidden = values[key] !== 'Custom'
    onChange(getValues(), linearPatternOffsets(values))
  }
  function steppedNumber(key, label, number, instances) {
    const input = el('input', { className: 'input input--sm', attrs: { type: 'number', step: 1, value: values[key], 'aria-label': label, ...(instances ? { min: 1, max: 128 } : {}) }, on: { input: event => {
      values[key] = event.target.value === '' ? NaN : Number(event.target.value); update()
    }, keydown: event => {
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); step(event.key === 'ArrowUp' ? 1 : -1) }
    } } })
    function step(delta) {
      const current = input.value === '' ? linearPatternDefaults[key] : Number(input.value)
      let next = Number((current + delta).toPrecision(15))
      if (instances) next = Math.min(128, Math.max(1, next))
      input.value = next
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    const arrows = el('span', { className: 'lp-stepper-arrows' })
    for (const [delta, action, glyph] of [[1, 'Increase', '▲'], [-1, 'Decrease', '▼']]) {
      const title = `${action} ${instances ? 'instances' : 'spacing'} ${number} by ${instances ? '1 instance' : '1 nm'}`
      arrows.append(el('button', { text: glyph, attrs: { type: 'button', 'aria-label': title, title }, on: { click: () => step(delta) } }))
    }
    return el('div', { className: 'lp-number-field', children: [el('span', { text: label }), el('div', { className: 'lp-stepper', children: [input, arrows] })] })
  }
  function directionFields(isSecond = false) {
    const suffix = isSecond ? '2' : '', number = isSecond ? 2 : 1
    const key = `direction${suffix}`, vectorKey = `vector${suffix}`
    const group = linearPatternSection(`Direction ${number}`)
    const axes = el('div', { className: 'cp-presets' })
    for (const axis of ['X', 'Y', 'Z', 'Custom']) {
      const button = el('button', { className: 'btn btn--sm', text: axis, attrs: { type: 'button', 'aria-label': `Direction ${number} ${axis}`, 'aria-pressed': String(values[key] === axis) }, on: { click: () => {
        values[key] = axis
        const other = isSecond ? 'direction' : 'direction2'
        if (axis !== 'Custom' && values[other] === axis) values[other] = ['X', 'Y', 'Z'].find(a => a !== axis)
        update()
      } } })
      buttons.push([button, key, axis]); axes.append(button)
    }
    const vectorFields = el('div', { className: 'lp-vector', attrs: { role: 'group', 'aria-label': `Direction ${number} vector` } })
    for (const [i, axis] of ['X', 'Y', 'Z'].entries()) vectorFields.append(el('label', { children: [axis, el('input', { className: 'input input--sm', attrs: { type: 'number', step: 'any', value: values[vectorKey][i], 'aria-label': `Direction ${number} vector ${axis}` }, on: { input: event => {
      values[vectorKey][i] = event.target.value === '' ? NaN : Number(event.target.value); update()
    } } })] }))
    vectorFields.hidden = values[key] !== 'Custom'; customFields.push([vectorFields, key])
    const fields = el('div', { className: 'lp-number-fields', children: [
      steppedNumber(`spacing${suffix}`, `Spacing ${number} (nm)`, number, false),
      steppedNumber(`instances${suffix}`, `Instances ${number}`, number, true),
    ] })
    group.append(axes, vectorFields, fields)
    return group
  }
  const first = directionFields(), second = directionFields(true)
  const toggle = el('input', { attrs: { type: 'checkbox', 'aria-label': '2D pattern' }, on: { change: event => { values.two_dimensional = event.target.checked; update() } } })
  toggle.checked = values.two_dimensional
  second.hidden = !values.two_dimensional
  element.append(first, el('label', { className: 'cp-snap', children: [toggle, '2D pattern'] }), second)
  return { element, getValues }
}
