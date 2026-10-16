import { afterEach, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { createMockStore } from '../test-helpers/mock_store.js'
import { createSelectionController } from '../scene/selection_controller.js'
import { linearDirection, linearPatternOffsets } from './linear_pattern_math.js'
import { initLinearPatternPanel } from './linear_pattern_panel.js'
import { editPatternFeature, isPatternFeature } from './pattern_feature_editor.js'

const defaults = { instances: 3, spacing: -10, direction: 'X', two_dimensional: true, instances2: 2, spacing2: 20, direction2: 'Z' }
const button = name => [...document.querySelectorAll('button')].find(b => b.textContent === name)
const field = label => document.querySelector(`[aria-label="${label}"]`)
function input(label, value) { const node = field(label); node.value = value; node.dispatchEvent(new Event('input')) }
afterEach(() => { window.dispatchEvent(new Event('nadoc:document-reset')); document.body.innerHTML = '' })

it('computes the full grid once per cell and rejects invalid or excessive counts', () => {
  expect(linearPatternOffsets(defaults)).toEqual([[0, 0, 0], [-10, 0, 0], [-20, 0, 0], [0, 0, 20], [-10, 0, 20], [-20, 0, 20]])
  expect(linearPatternOffsets({ ...defaults, two_dimensional: false })).toHaveLength(3)
  for (const change of [{ instances: 2.5 }, { instances: 65 }, { spacing: 0 }, { spacing: Infinity }, { direction2: 'X' }]) expect(linearPatternOffsets({ ...defaults, ...change })).toBeNull()
})

async function fixture(commitPattern = vi.fn().mockResolvedValue({}), organized = false) {
  document.body.innerHTML = '<div id="linear-pattern-panel"></div>'
  const store = createMockStore({ currentDesign: { id: 'd', helices: [{ id: 'h', length_bp: 20 }, { id: 'h2', length_bp: 30 }], cluster_transforms: [{ id: 'c', name: 'Source', helix_ids: ['h'] }, { id: 'c2', name: 'Second', helix_ids: ['h2'] }] }, currentGeometry: [{ helix_id: 'h', backbone_position: [2, 3, 4] }, { helix_id: 'h2', backbone_position: [20, 30, 40] }] })
  if (organized) store.setState({ currentDesign: { ...store.getState().currentDesign,
    group_organization: { version: 1, groups: [
      { id: 'c', name: 'Metadata group', helix_ids: ['h'] },
      { id: 'required', name: 'Required empty group', helix_ids: [] },
    ] }, deformations: [{ affected_helix_ids: ['h'], targets: [{ kind: 'part_group', id: 'required' }] }],
  } })
  const controller = createSelectionController({ store }), scene = new THREE.Scene()
  const tool = initLinearPatternPanel({ store, scene, commitPattern, showToast: vi.fn(), selectionManager: { clearSelection: controller.clear, setSelectionLevel: controller.setLevel } })
  tool.open(); controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  return { tool, store, scene, commitPattern, controller }
}

it('keeps explicit placements and separately submits selected copied group metadata', async () => {
  const { tool, commitPattern } = await fixture(undefined, true)
  expect(document.querySelector('[aria-label="Available placements"]')).not.toBeNull()
  const optional = field('Copy group Metadata group'), required = field('Copy group Required empty group')
  expect(optional.checked).toBe(true)
  expect(required.checked).toBe(true)
  expect(required.disabled).toBe(true)
  optional.click()
  field('2D pattern').click(); input('Instances 2', '3')
  button('Confirm').click(); await Promise.resolve(); await Promise.resolve()
  expect(commitPattern.mock.calls[0][0]).toMatchObject({ cluster_ids: ['c'], two_dimensional: true,
    _organization_copy: { version: 1, group_ids: ['required'] } })
  expect(commitPattern.mock.calls[0][1]).toMatchObject({ designId: 'd' })
  tool.close()
})

it('keeps a null-refused draft and its 2D controls open', async () => {
  const { tool } = await fixture(vi.fn(async () => null), true)
  field('2D pattern').click(); input('Spacing 1 (nm)', '17')
  button('Confirm').click(); await Promise.resolve(); await Promise.resolve()
  expect(tool.isActive()).toBe(true)
  expect(field('Spacing 1 (nm)').value).toBe('17')
  expect(document.querySelector('.cp-readout').textContent).toMatch(/accept|fail|refus/i)
  tool.close()
})

it('retires a held commit on same-ID reset and ignores its late result after reopening', async () => {
  let finish
  const { tool, scene, controller } = await fixture(vi.fn(() => new Promise(resolve => { finish = resolve })), true)
  button('Confirm').click()
  window.dispatchEvent(new Event('nadoc:document-reset'))
  expect(tool.isActive()).toBe(false)
  expect(scene.children).toHaveLength(0)
  tool.open(); controller.replace([{ kind: 'cluster', id: 'c' }]); await Promise.resolve()
  expect(tool.isActive()).toBe(true)
  const replacement = scene.getObjectByName('linearPatternPreview')
  finish({}); await Promise.resolve(); await Promise.resolve()
  expect(tool.isActive()).toBe(true)
  expect(scene.getObjectByName('linearPatternPreview')).toBe(replacement)
  tool.close()
})

it('keeps native history pattern inputs open on refusal and preserves its saved group selection', async () => {
  const params = { ...defaults, cluster_ids: ['historic-placement'], _organization_copy: { version: 1, group_ids: ['historic-group'] } }
  const onSave = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ accepted: true })
  const result = editPatternFeature({ op_kind: 'linear-pattern', params }, { onSave })
  input('Spacing 1 (nm)', '21'); button('Save').click()
  await Promise.resolve(); await Promise.resolve()
  expect(document.querySelector('[aria-label="Edit Linear Pattern"]')).not.toBeNull()
  expect(field('Spacing 1 (nm)').value).toBe('21')
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ cluster_ids: ['historic-placement'],
    _organization_copy: { version: 1, group_ids: ['historic-group'] }, spacing: 21 }))
  button('Save').click()
  expect(await result).toMatchObject({ spacing: 21, _organization_copy: params._organization_copy })
  expect(params.spacing).toBe(-10)
})

it('bounds read-only historical copy IDs without changing the authored request', async () => {
  const ids = Array.from({ length: 32 }, (_, i) => `${i}-` + 'g'.repeat(240))
  const params = { ...defaults, cluster_ids: ids, _organization_copy: { version: 1, group_ids: ids } }
  const pending = editPatternFeature({ op_kind: 'linear-pattern', params })
  const saved = document.querySelector('[aria-label="Saved pattern copy selection"]')
  expect(saved).not.toBeNull()
  expect(saved.textContent.length).toBeLessThan(10000)
  expect(saved.textContent).toMatch(/more/)
  button('Save').click()
  expect(await pending).toMatchObject({ cluster_ids: ids, _organization_copy: params._organization_copy })
})

it('previews a 2D grid and multiple sources, then cancels without writing', async () => {
  const { tool, scene, commitPattern, store } = await fixture()
  const original = store.getState().currentDesign
  const preview = scene.getObjectByName('linearPatternPreview')
  expect(preview.children).toHaveLength(2)
  expect(field('Direction 2 Y').closest('fieldset').hidden).toBe(true)
  field('2D pattern').click()
  expect(field('Direction 2 Y').closest('fieldset').hidden).toBe(false)
  input('Spacing 1 (nm)', '-12')
  field('Direction 2 Z').click()
  field('Include Second').click()
  expect(preview.children).toHaveLength(10)
  expect(preview.children[0].position.toArray()).toEqual([-10, 3, 4])
  expect(field('New BP created').textContent).toBe('250')
  expect(field('Total after pattern').textContent).toBe('300')
  input('Instances 1', '65')
  expect(button('Confirm').disabled).toBe(true)
  expect(preview.children).toHaveLength(0)
  expect(store.getState().currentDesign).toBe(original)
  tool.close()
  expect(scene.children).toHaveLength(0)
  expect(commitPattern).not.toHaveBeenCalled()
})

it('normalizes custom vectors and rejects zero or parallel 2D directions', () => {
  expect(linearDirection('X')).toEqual([1, 0, 0])
  expect(linearDirection('Custom', [0, 3, 4])).toEqual([0, .6, .8])
  for (const vector of [[0, 0, 0], [NaN, 1, 0], [1, 2]]) expect(linearDirection('Custom', vector)).toBeNull()
  const params = { ...defaults, direction: 'Custom', vector: [3, 4, 0], spacing: 10, direction2: 'Custom', vector2: [-4, 3, 0], spacing2: 5 }
  expect(linearPatternOffsets(params)).toEqual([[0, 0, 0], [6, 8, 0], [12, 16, 0], [-4, 3, 0], [2, 11, 0], [8, 19, 0]])
  expect(linearPatternOffsets({ ...params, vector2: [-6, -8, 0] })).toBeNull()
  expect(linearPatternOffsets({ ...params, spacing: 1e308 })).toBeNull()
})

it('shows section groups, custom XYZ fields, and exact unit steppers in the live preview', async () => {
  const { tool, scene } = await fixture()
  expect([...document.querySelectorAll('.lp-section > legend')].map(n => n.textContent)).toEqual(['Clusters', 'Direction 1', 'Direction 2', 'Info'])
  expect(field('Include Source').closest('.lp-cluster-list')).not.toBeNull()
  expect(field('Direction 1 vector X').parentElement.parentElement.hidden).toBe(true)
  field('Direction 1 Custom').click()
  expect(field('Direction 1 vector X').parentElement.parentElement.hidden).toBe(false)
  input('Direction 1 vector X', '0'); input('Direction 1 vector Y', '3'); input('Direction 1 vector Z', '4')
  input('Spacing 1 (nm)', '2.5')
  field('Increase spacing 1 by 1 nm').click()
  expect(field('Spacing 1 (nm)').value).toBe('3.5')
  field('Decrease spacing 1 by 1 nm').click()
  expect(field('Spacing 1 (nm)').value).toBe('2.5')
  field('Spacing 1 (nm)').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
  expect(field('Spacing 1 (nm)').value).toBe('3.5')
  field('Increase instances 1 by 1 instance').click()
  expect(field('Instances 1').value).toBe('4')
  field('Decrease instances 1 by 1 instance').click()
  expect(field('Instances 1').value).toBe('3')
  input('Instances 1', '1'); field('Decrease instances 1 by 1 instance').click()
  expect(field('Instances 1').value).toBe('1')
  input('Instances 1', '3')
  const offsets = scene.getObjectByName('linearPatternPreview').userData.offsets
  expect(offsets[1][0]).toBe(0)
  expect(offsets[1][1]).toBeCloseTo(2.1)
  expect(offsets[1][2]).toBeCloseTo(2.8)
  field('2D pattern').click(); field('Direction 2 Custom').click()
  input('Direction 2 vector X', '0'); input('Direction 2 vector Y', '6'); input('Direction 2 vector Z', '8')
  expect(button('Confirm').disabled).toBe(true)
  input('Direction 2 vector X', '1')
  expect(button('Confirm').disabled).toBe(false)
  tool.close()
})

it('submits once, blocks cancellation during commit, and cleans up', async () => {
  let done
  const commit = vi.fn(() => new Promise(resolve => { done = resolve }))
  const { tool, scene } = await fixture(commit)
  field('2D pattern').click(); field('Direction 1 Y').click()
  expect(field('Direction 2 X').getAttribute('aria-pressed')).toBe('true')
  button('Confirm').click(); button('Creating…').click(); tool.close()
  expect(commit).toHaveBeenCalledOnce()
  expect(commit.mock.calls[0][0]).toMatchObject({ cluster_ids: ['c'], direction: 'Y', direction2: 'X', two_dimensional: true })
  expect(tool.isActive()).toBe(true)
  done(); await Promise.resolve(); await Promise.resolve()
  expect(tool.isActive()).toBe(false)
  expect(scene.children).toHaveLength(0)
})

it('keeps rejected previews open for correction and closes on document changes', async () => {
  const { tool, store } = await fixture(vi.fn().mockRejectedValue(new Error('Unsupported source')))
  button('Confirm').click(); await Promise.resolve(); await Promise.resolve()
  expect(tool.isActive()).toBe(true)
  expect(document.querySelector('.cp-readout').textContent).toBe('Unsupported source')
  store.setState({ currentDesign: { id: 'other' } })
  expect(tool.isActive()).toBe(false)
})

it('edits linear settings with the shared 2D toggle and cancels without changing params', async () => {
  expect(isPatternFeature('linear-pattern')).toBe(true)
  expect(isPatternFeature('circular-pattern')).toBe(true)
  expect(isPatternFeature('extrude-segment')).toBe(false)
  const entry = { op_kind: 'linear-pattern', params: { ...defaults, cluster_ids: ['c'] } }
  let result = editPatternFeature(entry)
  input('Spacing 1 (nm)', '0'); button('Save').click()
  expect(document.querySelector('.cp-readout').hidden).toBe(false)
  input('Spacing 1 (nm)', '25'); input('Instances 2', ''); input('Spacing 2 (nm)', '')
  field('2D pattern').click(); button('Save').click()
  expect(await result).toMatchObject({ spacing: 25, two_dimensional: false, instances2: 2, spacing2: 10, cluster_ids: ['c'] })
  expect(entry.params.spacing).toBe(-10)
  result = editPatternFeature(entry); button('Cancel').click(); expect(await result).toBeNull()
})

it('edits circular counts, angle, origin, and arbitrary axis with validation', async () => {
  const result = editPatternFeature({ op_kind: 'circular-pattern', params: { cluster_id: 'c', instances: 3, total_angle: 360, axis_point: [1, 2, 3], axis_direction: [0, 0, 1] } })
  input('Instances', '2.5'); button('Save').click()
  expect(document.querySelector('.cp-readout').hidden).toBe(false)
  input('Instances', '4'); input('Total angle (degrees)', '180'); input('Axis origin (nm) X', '9'); button('Save').click()
  expect(await result).toMatchObject({ instances: 4, total_angle: 180, axis_point: [9, 2, 3], axis_direction: [0, 0, 1] })
})
