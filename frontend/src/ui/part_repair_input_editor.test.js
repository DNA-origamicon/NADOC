import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRepairInputEditor } from './part_repair_input_editor.js'

const catalog = fields => ({ version: 1, assessment: 'inputs_only', definition_supported: true,
  feature_id: 'group', child_id: 'child', fields })
const button = (root, text) => [...root.querySelectorAll('button')].find(item => item.textContent === text)
function setup(fields) {
  const onChange = vi.fn(), onSelect = vi.fn(), onSource = vi.fn(), onError = vi.fn()
  const editor = createRepairInputEditor({ onChange, onSelect, onSource, onError })
  document.body.append(editor.root); editor.render(catalog(fields))
  return { editor, onChange, onSelect, onSource, onError }
}
afterEach(() => document.body.replaceChildren())

describe('reviewed repair field editor', () => {
  it('offers the explicit structural repair without scalar version or arbitrary JSON controls', () => {
    const onUpgrade = vi.fn(), onChange = vi.fn(), onError = vi.fn()
    const editor = createRepairInputEditor({ onUpgrade, onChange, onError })
    const upgrade = { label: 'Preserve empty group owners (v2)', action: {
      action: 'upgrade_cluster_creation', feature_id: 'group', child_id: null,
      expected_version: 1, expected_cluster_id: 'owner', expected_definition_sha256: 'a'.repeat(64),
    } }
    editor.render({ ...catalog([]), child_id: null, upgrades: [upgrade] })
    const action = button(editor.root, upgrade.label)
    expect(action).toBeTruthy()
    expect(editor.root.textContent).toContain('Structural repair')
    expect(editor.root.querySelector('input,select,textarea')).toBeNull()
    editor.setDisabled(true); action.click()
    expect(onUpgrade).not.toHaveBeenCalled()
    editor.setDisabled(false); action.click()
    expect(onUpgrade).toHaveBeenCalledExactlyOnceWith(upgrade)
    expect(onChange).not.toHaveBeenCalled(); expect(onError).not.toHaveBeenCalled()
    editor.render({ ...catalog([]), definition_supported: false, upgrades: [upgrade] })
    expect(button(editor.root, upgrade.label)).toBeUndefined()
  })

  it('shows published values separately and edits a saved nullable pose through typed controls', () => {
    const field = { input_type: 'number_list', parameter_path: ['pose'], expected_old: null,
      label: 'Pose', length: 2, nullable: true }
    const h = setup([field])
    h.editor.render(catalog([field]), [{ action: 'set_input', feature_id: 'group', child_id: 'child',
      parameter_path: ['pose'], expected_old: null, value: [1, 2] }])
    expect(h.editor.root.textContent).toContain('Published: null')
    expect(h.editor.root.querySelector('[aria-label="Pose: no value"]').checked).toBe(false)
    expect(h.editor.root.querySelector('[aria-label="Pose 1"]').value).toBe('1')
    const second = h.editor.root.querySelector('[aria-label="Pose 2"]')
    second.value = '3'; second.dispatchEvent(new Event('input'))
    button(h.editor.root, 'Add proposed change').click()
    expect(h.onChange).toHaveBeenCalledWith(field, ['1', '3'])
    h.editor.root.querySelector('[aria-label="Pose: no value"]').checked = true
    button(h.editor.root, 'Add proposed change').click()
    expect(h.onChange).toHaveBeenLastCalledWith(field, null)
    h.editor.focusPath(['pose'])
    expect(document.activeElement.dataset.repairPath).toBe('["pose"]')
  })

  it('shows only selection choices bound to the exact routing child and typed path', () => {
    const field = { input_type: 'reference', parameter_path: ['protein_ids', 0], expected_old: 'missing', label: 'Protein' }
    const h = setup([field])
    button(h.editor.root, 'Find replacements').click()
    expect(h.onSelect).toHaveBeenCalledWith(field)
    const selected = { target: { feature_id: 'group', child_id: 'other', parameter_path: ['protein_ids', 0] },
      candidates: [{ identity: 'valid', label: 'Source protein' }] }
    h.editor.setSelection(selected)
    expect(button(h.editor.root, 'Source protein (valid)')).toBeUndefined()
    h.editor.setSelection({ ...selected, target: { ...selected.target, child_id: 'child' } })
    button(h.editor.root, 'Source protein (valid)').click()
    expect(h.onChange).toHaveBeenCalledWith(field, 'valid')
    expect(h.editor.root.textContent).toContain('full repair still needs evaluation')
    h.editor.setSelection(null)
    expect(button(h.editor.root, 'Source protein (valid)')).toBeUndefined()
  })

  it('binds source bytes to an explicit named original descriptor without reading the file', () => {
    const source = { sha256: 'a'.repeat(64), size_bytes: 3 }
    const field = { input_type: 'source', parameter_path: ['source'], expected_old: source, label: 'Protein source',
      source_binding: { parameter: 'source', source, max_size_bytes: 300, replacement_supported: false } }
    const h = setup([field]), file = new File(['PDB'], 'source.pdb')
    const input = h.editor.root.querySelector('input[type=file]')
    Object.defineProperty(input, 'files', { value: [file] })
    input.dispatchEvent(new Event('change'))
    expect(h.onSource).toHaveBeenCalledWith(field, file, 'restore_published', source)
    expect(button(h.editor.root, 'Propose replacement file')).toBeUndefined()
    expect(h.editor.root.textContent).toContain('Maximum 300 bytes')
  })

  it('refuses unsupported definitions or oversized vectors without exposing arbitrary JSON', () => {
    const h = setup([{ input_type: 'number_list', parameter_path: ['pose'], label: 'Pose', length: 100000 }])
    expect(h.editor.root.querySelectorAll('input')).toHaveLength(0)
    h.editor.render({ definition_supported: false, reason: { detail: 'Legacy construction needs migration' }, fields: [] })
    expect(h.editor.root.textContent).toContain('Legacy construction needs migration')
    expect(h.editor.root.querySelector('textarea')).toBeNull()
    expect(h.editor.root.querySelector('input')).toBeNull()
  })

  it('disables newly rendered reference choices with the rest of a busy or protected form', () => {
    const field = { input_type: 'reference', parameter_path: ['id'], expected_old: 'old', label: 'Target' }
    const h = setup([field]); h.editor.setDisabled(true)
    h.editor.setSelection({ target: { feature_id: 'group', child_id: 'child', parameter_path: ['id'] }, candidates: [{ identity: 'new' }] })
    expect([...h.editor.root.querySelectorAll('button')].every(item => item.disabled)).toBe(true)
    button(h.editor.root, 'new (new)').click()
    expect(h.onChange).not.toHaveBeenCalled()
  })
})

it('offers connection migration only as a reviewed proposal with evaluation required', () => {
  const onUpgrade = vi.fn(), editor = createRepairInputEditor({ onUpgrade })
  const upgrade = { label: 'Follow native connection creators', action: {
    action: 'upgrade_connection_owners', feature_id: 'group', child_id: null,
    expected_definition_sha256: 'a'.repeat(64),
  } }
  editor.render({ ...catalog([]), child_id: null, upgrades: [upgrade] })
  expect(editor.root.textContent).toContain('Connection reference repair')
  expect(editor.root.textContent).toContain('Save and evaluate')
  expect(editor.root.querySelector('input,select,textarea')).toBeNull()
  button(editor.root, upgrade.label).click()
  expect(onUpgrade).toHaveBeenCalledExactlyOnceWith(upgrade)
})
