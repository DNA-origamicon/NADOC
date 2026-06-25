import { describe, it, expect } from 'vitest'
import { partitionExtraBaseUpdates } from './crossover_connections.js'

describe('partitionExtraBaseUpdates', () => {
  it('passes real updates through untouched (no copy) when there are no inserts', () => {
    const ups = [{ helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] }]
    const { real, simXb } = partitionExtraBaseUpdates(ups)
    expect(real).toBe(ups)
    expect(simXb).toBeNull()
  })

  it('routes __xb__ updates into a per-crossover map keyed by k, keeping real ones', () => {
    const ups = [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      { helix_id: '__xb__', bp_index: 'xoA', direction: 0, backbone_position: [1, 1, 1], nx: 1, ny: 0, nz: 0 },
      { helix_id: '__xb__', bp_index: 'xoA', direction: 1, backbone_position: [2, 2, 2], nx: 0, ny: 1, nz: 0 },
      { helix_id: 'h1', bp_index: 5, direction: 'REVERSE', backbone_position: [9, 9, 9] },
    ]
    const { real, simXb } = partitionExtraBaseUpdates(ups)
    expect(real.map((u) => u.helix_id)).toEqual(['h0', 'h1'])
    expect(simXb.get('xoA').get(0).pos).toEqual([1, 1, 1])
    expect(simXb.get('xoA').get(0).normal).toEqual([1, 0, 0])
    expect(simXb.get('xoA').get(1).pos).toEqual([2, 2, 2])
    expect(simXb.get('xoA').get(1).normal).toEqual([0, 1, 0])
  })

  it('groups multiple crossovers independently', () => {
    const { simXb } = partitionExtraBaseUpdates([
      { helix_id: '__xb__', bp_index: 'xoA', direction: 0, backbone_position: [0, 0, 0] },
      { helix_id: '__xb__', bp_index: 'xoB', direction: 0, backbone_position: [1, 0, 0] },
    ])
    expect([...simXb.keys()].sort()).toEqual(['xoA', 'xoB'])
  })

  it('null updates (revert to geometry) → null map', () => {
    const { real, simXb } = partitionExtraBaseUpdates(null)
    expect(real).toBeNull()
    expect(simXb).toBeNull()
  })

  it('defaults a missing base normal to zero', () => {
    const { simXb } = partitionExtraBaseUpdates([
      { helix_id: '__xb__', bp_index: 'xoB', direction: 0, backbone_position: [0, 0, 0] },
    ])
    expect(simXb.get('xoB').get(0).normal).toEqual([0, 0, 0])
  })
})
