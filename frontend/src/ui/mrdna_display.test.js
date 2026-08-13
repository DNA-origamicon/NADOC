import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, beadsToPoints, edgesFrom, initMrdnaDisplay } from './mrdna_display.js'

describe('toFemUpdates', () => {
  it('preserves relaxed slab frames and loop-copy addressing', () => {
    const resp = { ready: true, positions: [{
      helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 1,
      backbone_position: [1, 2, 3], base_position: [1, 2.3, 3],
      nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
    }] }
    expect(toFemUpdates(resp)).toEqual([{
      helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 1,
      backbone_position: [1, 2, 3], base_position: [1, 2.3, 3],
      nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
    }])
  })

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

  it('passes strand-extension (__ext_) tail beads through for the deform toggle', () => {
    // A 5′/3′ ssDNA tail bead is keyed ("__ext_<id>", bead_index, direction) — the
    // SAME geometry key oxDNA and NAMD emit, which design_renderer already addresses
    // (`${helix_id}:${bp_index}:${direction}`), so no renderer change is needed.  Note
    // bp_index here is an ordinary int (unlike __xb__'s crossover-id string): a filter
    // that drops non-int bp_index would NOT drop these.
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
      { helix_id: '__ext_e1', bp_index: 0, direction: 'REVERSE', backbone_position: [4, 5, 6] },
    ] }
    expect(toFemUpdates(resp)).toEqual([
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
      { helix_id: '__ext_e1', bp_index: 0, direction: 'REVERSE', backbone_position: [4, 5, 6] },
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
    const designRenderer = {
      applyFemPositions: vi.fn(), clearScalarColors: vi.fn(),
      applyScalarColors: vi.fn(), clearExternalGeometry: vi.fn(), renderExternalGeometry: vi.fn(),
    }
    const beadOverlay = { update: vi.fn() }
    const connectionOverlay = { update: vi.fn(), clear: vi.fn() }
    const setDesignVisible = vi.fn()
    const api = {
      getMrdnaDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      ], confidence: { direct: 1, interpolated: 3, lower_confidence: true } })),
      getMrdnaBeads: vi.fn(async () => ({ ready: true, beads: [[1, 1, 1], [2, 2, 2]], edges: [[0, 1]] })),
      getMrdnaSnapshotGeometry: vi.fn(async () => ({
        ready: true, design: { strands: [] }, nucleotides: [{ backbone_position: [0, 0, 0] }], helix_axes: [],
      })),
      getMrdnaRmsf: vi.fn(async () => ({
        ready: true, min_rmsf: 0.1, max_rmsf: 0.3, mean_rmsf: 0.2, n_frames: 4,
        confidence: { direct: 1, interpolated: 3, lower_confidence: true },
        positions: [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD',
          backbone_position: [1, 2, 3], rmsf: 0.3 }],
      })),
      getMrdnaDeviation: vi.fn(async () => ({
        ready: true, min_deviation: 0, max_deviation: 0.5, mean_deviation: 0.2, rmsd_nm: 0.25,
        positions: [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD',
          backbone_position: [1, 2, 3], deviation: 0.5 }],
      })),
      getMrdnaStrain: vi.fn(async () => ({
        ready: true, metric: 'backbone_geometric', min_strain: -0.1, max_strain: 0.2,
        abs_max_strain: 0.2, display_abs_strain: 0.2, n: 1,
        confidence: { direct: 1, interpolated: 3, lower_confidence: true },
        positions: [{ helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy: 0,
          backbone_position: [0, 0, 0], strain: 0.2, ss: false }],
      })),
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

  it('shows trajectory RMSF and snapshot-relative deviation as scalar maps', async () => {
    const d = makeDeps()
    const flexScale = { show: vi.fn(), hide: vi.fn() }
    const c = initMrdnaDisplay({ ...d, flexScale })
    const flex = await c.showFlex('job1')
    expect(flex).toMatchObject({ ok: true, kind: 'flex', nFrames: 4 })
    expect(flex.confidence).toEqual({ direct: 1, interpolated: 3, lowerConfidence: true })
    expect(d.designRenderer.renderExternalGeometry).toHaveBeenCalled()
    expect(d.designRenderer.applyScalarColors).toHaveBeenCalled()
    expect(d.designRenderer.applyFemPositions).toHaveBeenLastCalledWith([
      expect.objectContaining({ backbone_position: [0, 0, 0] }),
    ])
    expect(flexScale.show).toHaveBeenCalledWith(expect.objectContaining({ title: 'RMSF (nm)' }))

    const dev = await c.showDeviation('job1')
    expect(dev).toMatchObject({ ok: true, kind: 'deviation', rmsd: 0.25 })
    expect(c.mode()).toBe('deviation')
    expect(d.designRenderer.applyFemPositions).toHaveBeenLastCalledWith([
      expect.objectContaining({ backbone_position: [0, 0, 0] }),
    ])
    expect(flexScale.show).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'Deviation (nm)' }))

    const strain = await c.showStrain('job1')
    expect(strain).toMatchObject({ ok: true, kind: 'strain', n: 1 })
    expect(c.mode()).toBe('strain')
    expect(flexScale.show).toHaveBeenLastCalledWith(expect.objectContaining({ title: 'Backbone strain' }))
  })

  it('deform and beads are mutually exclusive visualization modes', async () => {
    const { designRenderer, beadOverlay, connectionOverlay, setDesignVisible, api } = makeDeps()
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay, connectionOverlay, setDesignVisible })
    await c.showDeform('j')
    await c.showBeads('j')
    expect(c.deformActive()).toBe(false)
    expect(c.beadsActive()).toBe(true)
    c.stopAndRestore()
    expect(c.deformActive()).toBe(false)
    expect(c.beadsActive()).toBe(false)
    expect(setDesignVisible).toHaveBeenLastCalledWith(true)    // restored on teardown
  })

  it('showDeform returns not-ready when the response is empty', async () => {
    const { designRenderer, beadOverlay } = makeDeps()
    const api = {
      getMrdnaDisplay: vi.fn(async () => ({ ready: false, positions: [] })),
      getMrdnaSnapshotGeometry: vi.fn(async () => ({ ready: false, nucleotides: [] })),
    }
    const c = initMrdnaDisplay({ designRenderer, api, beadOverlay })
    const r = await c.showDeform('j')
    expect(r.ok).toBe(false)
    expect(designRenderer.applyFemPositions).not.toHaveBeenCalled()
  })
})
