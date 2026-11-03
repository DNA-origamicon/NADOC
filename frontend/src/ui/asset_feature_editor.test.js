import { expect, it } from 'vitest'
import { assetFeatureFields, assetEditorValues, assetEditorPatch, isNativeAssetFeature } from './asset_feature_editor.js'
const feature = (op_kind, params) => ({ feature_type: 'snapshot', op_kind, params: { _proof_version: 1, ...params } })
it('edits only exact native inputs and keeps bound move coordinates and preconstraint', () => {
  const entry = feature('nanoparticle-patch', { np_fitting_version: 1, gizmo_move: {
    pivot: [1, 2, 3], translation: [4, 5, 6], rotation: [0, 0, 0, 1], preconstrained: true } })
  expect(assetFeatureFields(entry)).toHaveLength(10)
  const values = assetEditorValues(entry)
  expect(values.rotation_w).toBe(1)
  expect(assetEditorPatch(entry, { ...values, translation_y: 9 })).toEqual({ gizmo_move: {
    ...entry.params.gizmo_move, translation: [4, 9, 6] } })
  expect(isNativeAssetFeature(entry)).toBe(true)
  expect(assetFeatureFields(feature('nanoparticle-patch', {}))).toEqual([])
  expect(assetFeatureFields({ ...entry, params: { ...entry.params, _generated_scope: 'generator' } })).toEqual([])
})
it('validates biotin sequences and preserves fixed-center choice as a boolean', () => {
  const entry = feature('nanoparticle-biotin-dna', { biotin_version: 1, action: 'create' })
  expect(assetFeatureFields(entry).map(f => f.key)).toEqual(['sequence', 'dna_per_strep', 'pocket', 'linker_nm'])
  expect(assetEditorPatch(entry, { sequence: ' acgt ' }).sequence).toBe('ACGT')
  expect(() => assetEditorPatch(entry, { sequence: 'x' })).toThrow('2–32')
  const fit = feature('nanoparticle-attach-overhang', { np_fitting_version: 1, fixed_center: false })
  expect(assetEditorValues(fit).fixed_center).toBe('false')
  expect(assetEditorPatch(fit, { fixed_center: 'false' }).fixed_center).toBe(false)
  expect(isNativeAssetFeature(feature('nanoparticle-connection-relax', { np_fitting_version: 1 }))).toBe(true)
})

it('edits coating choices while retaining pinned sources and automatic coverage', () => {
  const entry = feature('nanoparticle-patch', { coating_version: 1, action: 'set', count_override: null,
    pdb_source: { sha256: 'pinned' }, coverage_reference: 'saved-publication' })
  expect(isNativeAssetFeature(entry)).toBe(true)
  expect(assetEditorValues(entry).count_override).toBe(0)
  expect(assetEditorPatch(entry, { count_override: 0, seed: 8 })).toEqual({ count_override: null, seed: 8 })
  expect(assetFeatureFields(entry).map(f => f.key)).not.toContain('pdb_source')
  expect(assetFeatureFields(entry).map(f => f.key)).not.toContain('coverage_reference')
})

it('edits generated graft intent and fit choices without exposing fitted outputs', () => {
  const scope = { version: 2, group_id: 'group', input_ids: ['gold'] }
  const graft = feature('nanoparticle-conjugate', { _generated_scope: scope, thiol_version: 2 })
  expect(assetFeatureFields(graft).map(f => f.key)).toEqual(['sequence', 'spacer_nm'])
  const fit = feature('nanoparticle-attach-overhang', { _generated_scope: scope, np_fitting_version: 2 })
  expect(assetFeatureFields(fit).map(f => f.key)).toEqual(['fixed_center'])
  expect(assetEditorPatch(fit, { fixed_center: 'true' })).toEqual({ fixed_center: true })
})
