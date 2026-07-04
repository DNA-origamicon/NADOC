import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, beadsToPoints, edgesFrom, initMrdnaDisplay } from './mrdna_display.js'

describe('toFemUpdates', () => {
  it('returns [] for a not-ready / empty response', () => {
    expect(toFemUpdates(null)).toEqual([])
    expect(toFemUpdates({ ready: false, positions: [] })).toEqual([])
    expect(toFemUpdates({ ready: true })).toEqual([])
  })

  it('maps positions to applyFemPositions updates (no normals)', () => {
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
    ] }
    expect(toFemUpdates(resp)).toEqual([
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
    ])
  })

  it('passes crossover extra-base (__xb__) entries through for the deform toggle', () => {
    // __xb__ entries carry crossover_id in bp_index and the insert index k in
    // direction; design_renderer.applyFemPositions routes them to the extra-base
    // beads/slabs via partitionExtraBaseUpdates.  toFemUpdates must not drop them.
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
      { helix_id: '__xb__', bp_index: 'xo-123', direction: 0, backbone_position: [4, 5, 6] },
      { helix_id: '__xb__', bp_index: 'xo-123', direction: 1, backbone_position: [7, 8, 9] },
    ] }
    const out = toFemUpdates(resp)
    const xb = out.filter((u) => u.helix_id === '__xb__')
    expect(xb).toEqual([
      { helix_id: '__xb__', bp_index: 'xo-123', direction: 0, backbone_position: [4, 5, 6] },
      { helix_id: '__xb__', bp_index: 'xo-123', direction: 1, backbone_position: [7, 8, 9] },
    ])
  })
})

describe('beadsToPoints', () => {
  it('returns [] for a not-ready response', () => {
    expect(beadsToPoints(null)).toEqual([])
    expect(beadsToPoints({ ready: false, beads: [[0, 0, 0]] })).toEqual([])
  })

  it('maps [x,y,z] tuples to {x,y,z} points', () => {
    const resp = { ready: true, beads: [[1, 2, 3], [4, 5, 6]] }
    expect(beadsToPoints(resp)).toEqual([{ x: 1, y: 2, z: 3 }, { x: 4, y: 5, z: 6 }])
  })
})

describe('edgesFrom', () => {
  it('returns [] when absent / not ready', () => {
    expect(edgesFrom(null)).toEqual([])
    expect(edgesFrom({ ready: false, beads: [[0, 0, 0]], edges: [[0, 0]] })).toEqual([])
    expect(edgesFrom({ ready: true, beads: [[0, 0, 0]] })).toEqual([])
  })
  it('drops edges whose endpoints are out of range', () => {
    const resp = { ready: true, beads: [[0, 0, 0], [1, 1, 1]], edges: [[0, 1], [1, 5], [0, -1]] }
    expect(edgesFrom(resp)).toEqual([[0, 1]])
  })
})

describe('initMrdnaDisplay controller', () => {
  function makeDeps() {
    const designRenderer = { applyFemPositions: vi.fn() }
    const beadOverlay = { update: vi.fn() }
    const connectionOverlay = { update: vi.fn(), clear: vi.fn() }
    const setDesignVisible = vi.fn()
    const api = {
      getMrdnaDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      ] })),
      getMrdnaBeads: vi.fn(async () => ({ ready: true, beads: [[1, 1, 1], [2, 2, 2]], edges: [[0, 1]] })),
    }
    return { designRenderer, beadOverlay, connectionOverlay, setDesignVisible, api }
  }

  it('showDeform applies fem positions and marks active; stopDeform restores', async () => {
    const { designRenderer, beadOverlay, api } = makeDeps()
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay })
    const r = await c.showDeform('job1')
    expect(r.ok).toBe(true)
    expect(designRenderer.applyFemPositions).toHaveBeenCalledWith(expect.any(Array))
    expect(c.deformActive()).toBe(true)
    expect(c.deformJobId()).toBe('job1')

    c.stopDeform()
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(null)
    expect(c.deformActive()).toBe(false)
  })

  it('showBeads draws beads + connections and hides the native model; hideBeads restores', async () => {
    const { designRenderer, beadOverlay, connectionOverlay, setDesignVisible, api } = makeDeps()
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay, connectionOverlay, setDesignVisible })
    const r = await c.showBeads('job1')
    expect(r.ok).toBe(true)
    expect(beadOverlay.update).toHaveBeenCalledWith(
      [{ x: 1, y: 1, z: 1 }, { x: 2, y: 2, z: 2 }], expect.any(Number), expect.any(Number))
    expect(connectionOverlay.update).toHaveBeenCalledWith(
      [{ x: 1, y: 1, z: 1 }, { x: 2, y: 2, z: 2 }], [[0, 1]])
    expect(setDesignVisible).toHaveBeenLastCalledWith(false)   // native model hidden
    expect(c.beadsActive()).toBe(true)

    c.hideBeads()
    expect(beadOverlay.update).toHaveBeenLastCalledWith([], expect.any(Number), expect.any(Number))
    expect(connectionOverlay.clear).toHaveBeenCalled()
    expect(setDesignVisible).toHaveBeenLastCalledWith(true)    // native model restored
    expect(c.beadsActive()).toBe(false)
  })

  it('deform and beads are independent (both can be active)', async () => {
    const { designRenderer, beadOverlay, connectionOverlay, setDesignVisible, api } = makeDeps()
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay, connectionOverlay, setDesignVisible })
    await c.showDeform('j')
    await c.showBeads('j')
    expect(c.deformActive()).toBe(true)
    expect(c.beadsActive()).toBe(true)
    c.stopAndRestore()
    expect(c.deformActive()).toBe(false)
    expect(c.beadsActive()).toBe(false)
    expect(setDesignVisible).toHaveBeenLastCalledWith(true)    // restored on teardown
  })

  it('showDeform returns not-ready when the response is empty', async () => {
    const { designRenderer, beadOverlay } = makeDeps()
    const api = { getMrdnaDisplay: vi.fn(async () => ({ ready: false, positions: [] })) }
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay })
    const r = await c.showDeform('j')
    expect(r.ok).toBe(false)
    expect(designRenderer.applyFemPositions).not.toHaveBeenCalled()
  })
})
