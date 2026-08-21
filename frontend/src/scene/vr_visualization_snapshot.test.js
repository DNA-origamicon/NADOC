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

  it('keeps extra-base positions in every simulation display feed', () => {
    const updates = [{
      helix_id: '__xb__', bp_index: 'xo-all', direction: 0,
      backbone_position: [3, 4, 5],
    }]
    for (const mode of [
      'namd_display', 'oxdna_display', 'lammps_display', 'snupi_display',
      'blade_display', 'cando_display', 'mrdna_display',
    ]) {
      const snapshot = buildVRVisualizationSnapshot(updates, null, mode)
      expect(snapshot.visualization_mode).toBe(mode)
      expect(decodeURIComponent(snapshot.visualization_points[0].owner_token))
        .toBe(JSON.stringify(['base', '__xb__:xo-all:0']))
      expect(snapshot.visualization_points[0].position).toEqual([3, 4, 5])
    }
  })

  it('publishes exact slab frames and full trajectory atom positions', () => {
    const snapshot = buildVRVisualizationSnapshot([
      {
        helix_id: 'h0', bp_index: 14, direction: 'FORWARD',
        backbone_position: [1, 2, 3],
      },
    ], { 'h0:14:FORWARD': 0x123456 }, 'namd_rmsf', {
      slabFrames: [{
        base_key: 'h0:14:FORWARD', center: [4, 5, 6],
        axis_x: [0.3, 0, 0], axis_y: [0, 0.06, 0], axis_z: [0, 0, 0.7],
      }],
      atoms: [{
        atom: { name: 'O1P', base_key: 'h0:14:FORWARD' },
        position: [7, 8, 9],
      }],
    })

    expect(snapshot.visualization_points).toEqual([
      {
        owner_token: encodeURIComponent(JSON.stringify(['base', 'h0:14:FORWARD'])),
        position: [1, 2, 3], color: 0x123456,
        slab_center: [4, 5, 6], slab_axis_x: [0.3, 0, 0],
        slab_axis_y: [0, 0.06, 0], slab_axis_z: [0, 0, 0.7],
      },
      {
        owner_token: encodeURIComponent(JSON.stringify(['atom', 'h0:14:FORWARD', 'OP1'])),
        position: [7, 8, 9], color: 0x123456,
      },
    ])
  })

  it('publishes an explicit clear when no simulation overlay is active', () => {
    expect(buildVRVisualizationSnapshot(null, null, 'namd_display')).toEqual({
      visualization_mode: 'none', visualization_points: [],
    })
  })
})
