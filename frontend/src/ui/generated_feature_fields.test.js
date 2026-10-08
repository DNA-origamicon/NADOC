import { describe, it, expect } from 'vitest'
import { generatedFeatureSchema, canReplayGenerated } from './generated_feature_fields.js'

const command = (group, editable = []) => ({ params: { _generator: { group_id: group, version: 1, editable } } })
describe('generated feature editing', () => {
  it('allows an earlier command to replay through later generated commands', () => {
    const log = [{ feature_type: 'checkpoint' }, command('g', ['length_bp']), command('g'), command('g', ['roll_deg'])]
    expect(canReplayGenerated(log, 1)).toBe(true)
    expect(canReplayGenerated(log, 3)).toBe(true)
    expect(canReplayGenerated(log, 0)).toBe(false)
    expect(canReplayGenerated([...log, { feature_type: 'cluster_op' }], 1)).toBe(false)
    expect(canReplayGenerated([...log, command('another-run')], 1)).toBe(false)
  })
  it('offers command parameters rather than a single generator editor', () => {
    expect(generatedFeatureSchema(command('g', ['sequence', 'spacer_nm']))).toEqual([
      { key: 'sequence', label: 'Sequence (5′ → 3′)', type: 'text' },
      { key: 'spacer_nm', label: 'Thiol spacer (nm)', type: 'number', min: 0, max: 100, step: 0.1 },
    ])
    expect(generatedFeatureSchema(command('g', ['length_bp']))[0].integer).toBe(true)
    expect(generatedFeatureSchema(command('g', ['bend_scale', 'path_order'])).map(f => [f.key, f.type])).toEqual([
      ['bend_scale', 'number'], ['path_order', 'text'],
    ])
    expect(generatedFeatureSchema(command('g', ['pathing']))[0]).toEqual({
      key: 'pathing', label: 'Pathing', type: 'select', options: ['colocalized', 'interior', 'exterior'],
    })
    expect(generatedFeatureSchema(command('g'))).toEqual([])
  })
})
