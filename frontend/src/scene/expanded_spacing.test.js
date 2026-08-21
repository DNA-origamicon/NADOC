import { describe, expect, it } from 'vitest'
import { buildExtensionArcMap } from './expanded_spacing.js'

describe('buildExtensionArcMap', () => {
  it('offsets extension beads from the host strand terminal helix', () => {
    const design = {
      strands: [{ id: 's1', domains: [
        { helix_id: 'h5' }, { helix_id: 'h3' },
      ] }],
      extensions: [
        { id: 'e5', strand_id: 's1', end: 'five_prime' },
        { id: 'e3', strand_id: 's1', end: 'three_prime' },
      ],
    }
    const geometry = [
      { extension_id: 'e5', bp_index: 0, backbone_position: [1, 2, 3] },
      { extension_id: 'e3', bp_index: 4, backbone_position: [5, 6, 7] },
    ]
    const offsets = new Map([
      ['h5', { x: 10, y: 20, z: 30 }],
      ['h3', { x: -1, y: -2, z: -3 }],
    ])
    const result = buildExtensionArcMap(offsets, design, geometry)
    expect(result.get('e5').get(0)).toEqual({ x: 11, y: 22, z: 33 })
    expect(result.get('e3').get(4)).toEqual({ x: 4, y: 4, z: 4 })
  })

  it('skips extensions without geometry or a host strand', () => {
    expect(buildExtensionArcMap(new Map(), {
      strands: [], extensions: [{ id: 'e1', strand_id: 'missing', end: 'five_prime' }],
    }, [{ extension_id: 'e1', bp_index: 0, backbone_position: [0, 0, 0] }]).size).toBe(0)
  })
})
