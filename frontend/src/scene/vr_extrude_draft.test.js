import { describe, it, expect } from 'vitest'
import { normalizePaintedFootprint } from './vr_extrude_draft.js'
import { normalizeVRToolConfig, vrToolConfigMissing, reduceVRToolConfig, initialVRToolConfigState } from './vr_tool_config.js'

describe('painted VR footprint transport', () => {
  it('copies cells without claiming a resolved authoring frame', () => {
    const footprint = { lattice_type: 'HONEYCOMB', cells: [[-1, 2], [0, 0]] }
    const draft = normalizeVRToolConfig({ mode: 'extrude', target_identity: null,
      target_kind: 'none', target_owner_tokens: [], length_bp: 21, direction_sign: 1,
      strand_filter: 'both', ligate_adjacent: false, footprint_state: 'unresolved',
      painted_footprint: footprint })
    expect(draft.painted_footprint).toEqual(footprint)
    footprint.cells[0][0] = 99
    expect(draft.painted_footprint.cells[0]).toEqual([-1, 2])
    expect(vrToolConfigMissing(draft)).toContain('footprint')
    const reduced = reduceVRToolConfig(initialVRToolConfigState, { sequence: 1, draft },
      { targetSnapshotPresent: true, toolTarget: null })
    expect(reduced.accepted).toBe(true)
    expect(reduced.reason).toBe('incomplete')
  })
  it.each([[[0, 0], [0, 0]], [[true, 0]], [[.5, 0]], [[0, 100001]], [[NaN, 0]], [[0]]].map(cells => [cells]))(
    'rejects invalid cells %j', cells => {
      expect(normalizePaintedFootprint({ lattice_type: 'SQUARE', cells })).toBeNull()
    })
  it('accepts full native capacity and rejects overflow or extra fields', () => {
    const value = { lattice_type: 'SQUARE', cells: Array.from({ length: 16641 }, (_, i) => [i, -i]) }
    expect(normalizePaintedFootprint(value).cells).toHaveLength(16641)
    expect(normalizePaintedFootprint({ ...value, cells: [...value.cells, [99999, 0]] })).toBeNull()
    expect(normalizePaintedFootprint({ ...value, frame: 'invented' })).toBeNull()
  })
})
