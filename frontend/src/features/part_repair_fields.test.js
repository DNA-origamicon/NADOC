import { expect, it, vi } from 'vitest'
import { actionFromRepairField, parseRepairField, replacementRepairSource, updateRepairActions } from './part_repair_fields.js'

it('uses backend exact old values, stable identities and typed paths for reviewed input actions', () => {
  const field = { input_type: 'integer', parameter_path: ['inputs', 0], expected_old: 2, minimum: 1, maximum: 10, label: 'Count' }
  const catalog = { version: 1, assessment: 'inputs_only', definition_supported: true, feature_id: 'group', child_id: 'child', fields: [field] }
  expect(actionFromRepairField(catalog, field, '3')).toEqual({ action: 'set_input', feature_id: 'group', child_id: 'child', parameter_path: ['inputs', 0], expected_old: 2, value: 3 })
  for (const value of ['', '2.5', 'NaN', '11']) expect(() => actionFromRepairField(catalog, field, value)).toThrow()
  expect(() => actionFromRepairField({ ...catalog, definition_supported: false }, field, '3')).toThrow(/supported/)
})

it('preserves authored text and explicit null while bounding matrices and strings', () => {
  expect(parseRepairField({ input_type: 'string', max_length: 12 }, ' spaced ')).toBe(' spaced ')
  expect(parseRepairField({ input_type: 'number_list', length: 2, nullable: true }, null)).toBeNull()
  expect(parseRepairField({ input_type: 'number_list', length: 2 }, ['1', '-2'])).toEqual([1, -2])
  expect(() => parseRepairField({ input_type: 'number_list', length: 2 }, ['1', ''])).toThrow()
  expect(() => parseRepairField({ input_type: 'string', max_length: 2 }, 'long')).toThrow()
  expect(() => parseRepairField({ input_type: 'object' }, {})).toThrow(/reviewed/)
})

it('carries the exact old-value JSON receipt unchanged through action edits and JSON serialization', () => {
  const field = { input_type: 'number_list', parameter_path: ['pose'], expected_old: [1, 0, -0],
    expected_old_json: '[1.0,0,-0.0]', label: 'Pose', length: 3 }
  const catalog = { version: 1, assessment: 'inputs_only', definition_supported: true,
    feature_id: 'feature', child_id: null, fields: [field] }
  const action = actionFromRepairField(catalog, field, ['1', '2', '3'])
  const body = JSON.parse(JSON.stringify(updateRepairActions([], action)))
  expect(body[0]).toMatchObject({ expected_old: [1, 0, 0], expected_old_json: '[1.0,0,-0.0]', value: [1, 2, 3] })
  const updated = actionFromRepairField(catalog, field, ['2', '2', '3'])
  expect(updateRepairActions(body, updated)[0].expected_old_json).toBe(field.expected_old_json)
})

it('replaces only the explicitly selected action, including an explicitly refreshed old value for rebase', () => {
  const first = { action: 'set_input', feature_id: 'first', child_id: null, parameter_path: ['ids', 0], expected_old: 'missing', value: 'a' }
  const other = { ...first, parameter_path: ['ids', 1] }
  const updated = { ...first, expected_old: 'new base', value: 'b' }
  expect(updateRepairActions([first, other], updated)).toEqual([updated, other])
  expect(first.expected_old).toBe('missing')
})

it('checks the named source ceiling before reading or digesting and forbids changing a fixed source', async () => {
  const arrayBuffer = vi.fn(async () => new Uint8Array([1, 2, 3]).buffer), digest = vi.fn(async () => new Uint8Array(32).fill(15).buffer)
  const field = { source_binding: { replacement_supported: true, max_size_bytes: 3,
    source: { version: 1, sha256: 'a'.repeat(64), size_bytes: 2, format: 'pdb', media_type: 'chemical/x-pdb' } } }
  await expect(replacementRepairSource(field, { size: 4, arrayBuffer }, digest)).rejects.toThrow(/1–3/)
  await expect(replacementRepairSource({ source_binding: { replacement_supported: false } }, { size: 3, arrayBuffer }, digest)).rejects.toThrow(/restoration/)
  expect(arrayBuffer).not.toHaveBeenCalled(); expect(digest).not.toHaveBeenCalled()
  expect(await replacementRepairSource(field, { size: 3, arrayBuffer }, digest)).toEqual({ ...field.source_binding.source,
    sha256: '0f'.repeat(32), size_bytes: 3 })
})
