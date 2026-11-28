import { expect, it, afterEach } from 'vitest'
import { createAssemblyInputForm, inputDefault, validateInput, referenceKind } from './assembly_input_form.js'
afterEach(() => { document.body.innerHTML = '' })
const number = { type: 'number', nullable: true }
function mount(properties, inputs = {}, references = {}) {
  const form = createAssemblyInputForm({ schema: { properties }, inputs, references }); document.body.append(form.element); return form
}
const control = label => document.querySelector(`[aria-label="${label}"]`)
const change = (label, value) => { control(label).value = value; control(label).dispatchEvent(new Event('input', { bubbles: true })) }
it('preserves omitted and unchanged fields while clearing limits explicitly', () => {
  const f = mount({ min_limit: number, max_limit: number, ratio: { type: 'number' } }, { min_limit: null, max_limit: 3, ratio: 2 })
  expect(() => f.read()).toThrow('Change an input')
  change('Max limit action', 'null')
  expect(f.read()).toEqual({ max_limit: null })
  change('Min limit', '-1')
  expect(f.read()).toEqual({ min_limit: -1, max_limit: null })
})
it('exposes boolean and previously null optional values without coercing other defaults', () => {
  const f = mount({ invert: { type: 'boolean', nullable: true }, name: { type: 'string', nullable: true } }, { invert: null, name: null })
  change('Invert', 'false'); change('Name', 'Updated')
  expect(f.read()).toEqual({ invert: false, name: 'Updated' })
})
it('uses named historical choices and permits changing owners in one patch', () => {
  const f = mount({ instance_a_id: { type: 'string' }, overhang_a_id: { type: 'string' } },
    { instance_a_id: 'a', overhang_a_id: 'oh-a' }, { instance: [{ value: 'a', label: 'First' }, { value: 'b', label: 'Second' }],
      overhang: [{ value: 'oh-a', label: 'First / Handle', instance_id: 'a' }, { value: 'oh-b', label: 'Second / Handle', instance_id: 'b' }] })
  expect(control('Instance a').textContent).toContain('Second')
  change('Instance a', 'b'); change('Overhang a', 'oh-b')
  expect(f.read()).toEqual({ instance_a_id: 'b', overhang_a_id: 'oh-b' })
})
it('edits nested objects and growable arrays without raw JSON', () => {
  const schema = { type: 'array', minItems: 1, items: { type: 'object', required: ['arc_param'], properties: { arc_param: { type: 'number' } } } }
  const f = mount({ copies: schema }, { copies: [{ arc_param: 0.2 }] })
  document.querySelector('button').click() // removes first
  expect(() => f.read()).toThrow('invalid number')
  document.querySelector('button').click() // add
  change('Copies 1 / Arc param', '0.6')
  expect(f.read()).toEqual({ copies: [{ arc_param: 0.6 }] })
})
it('validates integers, finite vectors and rigid transforms', () => {
  expect(validateInput({ type: 'integer', minimum: 1 }, 1.2)).toContain('finite integer')
  const vector = { type: 'array', items: { type: 'number' }, minItems: 3, maxItems: 3, format: 'vector' }
  expect(validateInput(vector, [0, 0, 0], 'Axis direction')).toContain('nonzero')
  expect(validateInput(vector, [NaN, 1, 2])).toContain('finite')
  const matrix = { ...vector, minItems: 16, maxItems: 16, format: 'matrix' }
  const identity = inputDefault(matrix)
  expect(validateInput(matrix, identity)).toBeNull()
  identity[0] = 2
  expect(validateInput(matrix, identity)).toContain('scaling')
})
it('maps references and supplies typed defaults', () => {
  expect(referenceKind('subgroup_ids')).toBe('group')
  expect(referenceKind('sub_domain_a_id')).toBe('sub_domain')
  expect(referenceKind('connector_label')).toBe('connector')
  expect(referenceKind('label')).toBeNull()
  expect(inputDefault({ type: 'object', required: ['count'], properties: { count: { type: 'integer', minimum: 2 } } })).toEqual({ count: 2 })
})
