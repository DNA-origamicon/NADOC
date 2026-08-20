import { describe, expect, it } from 'vitest'

import { buildVRVisualizationSnapshot } from './vr_visualization_snapshot.js'

describe('buildVRVisualizationSnapshot', () => {
  it('maps live MD positions and flex colors to native base owner tokens', () => {
    const snapshot = buildVRVisualizationSnapshot([
      {
        helix_id: 'h0', bp_index: 4, direction: 'FORWARD', copy: 0,
        backbone_position: [1, 2, 3],
      },
      {
        helix_id: 'h0', bp_index: 4, direction: 'FORWARD', copy: 1,
        backbone_position: [4, 5, 6],
      },
    ], {
      'h0:4:FORWARD': 0x112233,
      'h0:4:FORWARD:1': 0xabcdef,
    }, 'NAMD RMSF')

    expect(snapshot.visualization_mode).toBe('namd_rmsf')
    expect(snapshot.visualization_points).toEqual([
      {
        owner_token: encodeURIComponent(JSON.stringify(['base', 'h0:4:FORWARD'])),
        position: [1, 2, 3], color: 0x112233,
      },
      {
        owner_token: encodeURIComponent(JSON.stringify(['base', 'h0:4:FORWARD:1'])),
        position: [4, 5, 6], color: 0xabcdef,
      },
    ])
  })

  it('uses crossover extra-base identities and rejects malformed positions', () => {
    const snapshot = buildVRVisualizationSnapshot([
      {
        helix_id: '__xb__', bp_index: 'xo-7', direction: '2',
        backbone_position: [0, 1, 2],
      },
      { helix_id: 'h1', bp_index: 2, direction: 'REVERSE', backbone_position: [0, NaN, 2] },
    ], { '__xb__:xo-7:2': 0xff0088 }, 'oxDNA flex')

    expect(snapshot.visualization_points).toHaveLength(1)
    expect(decodeURIComponent(snapshot.visualization_points[0].owner_token))
      .toBe(JSON.stringify(['base', '__xb__:xo-7:2']))
    expect(snapshot.visualization_points[0].color).toBe(0xff0088)
  })

  it('publishes an explicit clear when no simulation overlay is active', () => {
    expect(buildVRVisualizationSnapshot(null, null, 'namd_display')).toEqual({
      visualization_mode: 'none', visualization_points: [],
    })
  })
})
