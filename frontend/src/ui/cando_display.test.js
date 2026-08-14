import { describe, it, expect, vi } from 'vitest'
import {
  toFemUpdates, initCandoDisplay, viridisHex, deviationHex,
  flexColorMap, deviationColorMap, thermalCylinderFrame, thermalCylinderAxis,
} from './cando_display.js'
import { colormapHex } from './colormaps.js'

// A ready /cando/jobs/{id}/snapshot-geometry response — the job's own design snapshot
// that the display modes render (via renderExternalGeometry) before overlaying the FEM
// shape.  Minimal but non-empty so _snapshotReady() passes.
const snapshotResp = () => ({
  ready: true,
  design: { helices: [{ id: 'h' }], strands: [], crossovers: [] },
  nucleotides: [{ helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0] }],
  helix_axes: [{ helix_id: 'h', start: [0, 0, 0], end: [1, 0, 0] }],
})

describe('toFemUpdates', () => {
  it('returns [] for a not-ready / empty response', () => {
    expect(toFemUpdates(null)).toEqual([])
    expect(toFemUpdates({ ready: false, positions: [] })).toEqual([])
    expect(toFemUpdates({ ready: true })).toEqual([])
  })

  it('maps positions to applyFemPositions updates (no normals) and carries the loop copy', () => {
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3] },
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 1, backbone_position: [4, 5, 6] },
    ] }
    expect(toFemUpdates(resp)).toEqual([
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 0, backbone_position: [1, 2, 3] },
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 1, backbone_position: [4, 5, 6] },
    ])
  })

  it('threads the wound slab frame (nx/ny/nz + tx/ty/tz) when the display carries it', () => {
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', backbone_position: [1, 2, 3],
        nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1 },
    ] }
    expect(toFemUpdates(resp)[0]).toEqual({
      helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 0, backbone_position: [1, 2, 3],
      nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
    })
  })
})

describe('thermalCylinderFrame', () => {
  it('moves helix axes to backbone midpoints and carries crossover joints with them', () => {
    const base = {
      helices: [{ helix_id: 'h', points: [[0, 0, 0], [1, 0, 0]], rmsf: [0.1, 0.2] }],
      joints: [[[0, 0, 0], [1, 0, 0]]],
    }
    const keys = [['h', 0, 'FORWARD', 0], ['h', 0, 'REVERSE', 0],
      ['h', 1, 'FORWARD', 0], ['h', 1, 'REVERSE', 0]]
    const moved = thermalCylinderFrame(base, keys, [0, 2, 0, 0, 4, 0, 2, 2, 0, 2, 4, 0])
    expect(moved.helices[0].points).toEqual([[0, 3, 0], [2, 3, 0]])
    expect(moved.joints[0]).toEqual([[0, 3, 0], [2, 3, 0]])
    expect(moved.helices[0].rmsf).toEqual([0.1, 0.2])
  })
})

describe('thermalCylinderAxis', () => {
  it('uses the true FEM centerline rather than groove-precessing backbone midpoints', () => {
    const base = {
      helices: [{ helix_id: 'h', points: [[0, 0, 0], [1, 0, 0]], rmsf: [0.1, 0.2] }],
      joints: [[[0, 0, 0], [1, 0, 0]]],
    }
    const moved = thermalCylinderAxis(base, [
      { helix_id: 'h', bp_index: 0, position: [0, 2, 0] },
      { helix_id: 'h', bp_index: 1, position: [1, 3, 0] },
    ])
    expect(moved.helices[0].points).toEqual([[0, 2, 0], [1, 3, 0]])
    expect(moved.joints[0]).toEqual([[0, 2, 0], [1, 3, 0]])
  })
})

describe('initCandoDisplay controller', () => {
  function makeDeps() {
    const designRenderer = {
      applyFemPositions: vi.fn(), clearScalarColors: vi.fn(),
      renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn(),
    }
    const api = {
      getCandoDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      ] })),
      getCandoSnapshotGeometry: vi.fn(async () => snapshotResp()),
    }
    return { designRenderer, api }
  }

  it('showDeform renders the job snapshot + applies fem positions; stopDeform restores', async () => {
    const { designRenderer, api } = makeDeps()
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showDeform('job1')
    expect(r.ok).toBe(true)
    // Renders the job's OWN snapshot topology first, THEN overlays the FEM shape.
    expect(api.getCandoSnapshotGeometry).toHaveBeenCalledWith('job1', expect.any(AbortSignal))
    expect(designRenderer.renderExternalGeometry).toHaveBeenCalled()
    expect(designRenderer.applyFemPositions).toHaveBeenCalledWith(expect.any(Array))
    expect(c.deformActive()).toBe(true)
    expect(c.deformJobId()).toBe('job1')

    c.stopDeform()
    expect(designRenderer.clearExternalGeometry).toHaveBeenCalled()   // live model restored
    expect(c.deformActive()).toBe(false)
    expect(c.deformJobId()).toBe(null)
  })

  it('showDeform returns not-ready when the response is empty (model untouched)', async () => {
    const { designRenderer } = makeDeps()
    const api = {
      getCandoDisplay: vi.fn(async () => ({ ready: false, positions: [] })),
      getCandoSnapshotGeometry: vi.fn(async () => snapshotResp()),
    }
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showDeform('j')
    expect(r.ok).toBe(false)
    expect(designRenderer.renderExternalGeometry).not.toHaveBeenCalled()
    expect(designRenderer.applyFemPositions).not.toHaveBeenCalled()
    expect(c.deformActive()).toBe(false)
  })

  it('predicted shape uses thermal conformations automatically instead of the static mean', async () => {
    const { designRenderer, api } = makeDeps()
    api.getCandoThermalTrajectory = vi.fn(async () => ({
      ready: true, temperature_k: 298, n_frames: 2, representative_frame: 1,
      keys: [['h', 0, 'FORWARD', 0]], frames: [[2, 3, 4], [5, 6, 7]],
      representative_positions: [{
        helix_id: 'h', bp_index: 0, direction: 'FORWARD', copy: 0,
        backbone_position: [5, 6, 7], nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
      }],
    }))
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showDeform('job-moving')
    expect(r.ok).toBe(true)
    expect(c.lastStats()).toMatchObject({ kind: 'deform', thermal: true, frames: 2 })
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith([
      expect.objectContaining({
        backbone_position: [5, 6, 7], nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
      }),
    ])
    c.stopAndRestore()
  })

  it('showDeform returns not-ready when the snapshot geometry is unavailable', async () => {
    const { designRenderer } = makeDeps()
    const api = {
      getCandoDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] },
      ] })),
      getCandoSnapshotGeometry: vi.fn(async () => ({ ready: false, nucleotides: [] })),
    }
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showDeform('j')
    expect(r.ok).toBe(false)
    expect(designRenderer.renderExternalGeometry).not.toHaveBeenCalled()
    expect(c.deformActive()).toBe(false)
  })

  it('stopAndRestore reverts an active deform and invalidates in-flight fetches', async () => {
    const { designRenderer, api } = makeDeps()
    const c = initCandoDisplay({ designRenderer, api })
    await c.showDeform('j')
    expect(c.deformActive()).toBe(true)
    c.stopAndRestore()
    expect(designRenderer.clearExternalGeometry).toHaveBeenCalled()
    expect(c.deformActive()).toBe(false)
  })

  it('a stale showDeform response (superseded by a newer request) is ignored', async () => {
    const { designRenderer } = makeDeps()
    let resolveFirst
    const api = {
      getCandoDisplay: vi.fn()
        // first call hangs until we resolve it manually
        .mockImplementationOnce(() => new Promise((res) => { resolveFirst = res }))
        .mockImplementationOnce(async () => ({ ready: true, positions: [
          { helix_id: 'h', bp_index: 1, direction: 'REVERSE', backbone_position: [9, 9, 9] },
        ] })),
      getCandoSnapshotGeometry: vi.fn(async () => snapshotResp()),
    }
    const c = initCandoDisplay({ designRenderer, api })
    const p1 = c.showDeform('old')
    const r2 = await c.showDeform('new')       // bumps epoch → old response is stale
    resolveFirst({ ready: true, positions: [
      { helix_id: 'h', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0] },
    ] })
    const r1 = await p1
    expect(r2.ok).toBe(true)
    expect(r1.ok).toBe(false)                  // stale request rejected
    expect(c.deformJobId()).toBe('new')
  })
})

// ── Colour ramps + colour-map builders (pure) ─────────────────────────────────

describe('colour ramps', () => {
  it('viridis + deviation ramps clamp to [0,1] and span endpoints', () => {
    expect(viridisHex(-1)).toBe(viridisHex(0))     // clamp low
    expect(viridisHex(2)).toBe(viridisHex(1))      // clamp high
    expect(viridisHex(0)).not.toBe(viridisHex(1))  // ramp actually moves
    // deviation: 0 = green, 1 = red (distinct, red channel dominates at the top)
    expect((deviationHex(1) >> 16) & 0xff).toBeGreaterThan((deviationHex(0) >> 16) & 0xff)
  })
})

describe('flexColorMap', () => {
  const disp = { ready: true, positions: [
    { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0] },
    { helix_id: 'h', bp_index: 0, direction: 'forward', copy: 1, backbone_position: [0, 0, 0] },  // loop copy
    { helix_id: 'h', bp_index: 0, direction: 'reverse', backbone_position: [0, 0, 0] },
    { helix_id: 'h', bp_index: 5, direction: 'forward', backbone_position: [1, 0, 0] },  // no RMSF node
  ] }
  const rmsf = {
    rmsf: [{ helix_id: 'h', bp_index: 0, rmsf_nm: 1.2 }],
    min_nm: 0.5, p95_nm: 1.3, max_nm: 1.5,
  }

  it('returns null when positions or RMSF are missing', () => {
    expect(flexColorMap(disp, { rmsf: [] })).toBeNull()
    expect(flexColorMap({ ready: false }, rmsf)).toBeNull()
  })

  it('colours covered bp (both strands + each loop copy), leaves uncovered bp uncoloured', () => {
    const map = flexColorMap(disp, rmsf)
    expect(map.updates).toHaveLength(4)              // every display position kept
    const hex = colormapHex('jet', (1.2 - 0.5) / 0.8)
    // bp 0 copy 0 → 3-part alias + 4-part key; the LOOP COPY (copy 1) → its own 4-part key.
    expect(map.colorByKey['h:0:forward']).toBe(hex)
    expect(map.colorByKey['h:0:forward:0']).toBe(hex)
    expect(map.colorByKey['h:0:forward:1']).toBe(hex)   // loop copy coloured (the bug fix)
    expect(map.colorByKey['h:0:reverse']).toBeDefined()
    expect(map.colorByKey['h:5:forward']).toBeUndefined()
    expect(map).toMatchObject({ min: 0.5, max: 1.3, dataMax: 1.5 })
  })
})

describe('deviationColorMap', () => {
  const resp = { ready: true, rmsd_nm: 2.5, min_deviation: 0, max_deviation: 4, positions: [
    { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0], deviation: 0 },
    { helix_id: 'h', bp_index: 0, direction: 'forward', copy: 1, backbone_position: [0, 0, 0], deviation: 2 },
    { helix_id: 'h', bp_index: 1, direction: 'forward', backbone_position: [1, 0, 0], deviation: 4 },
  ] }

  it('returns null for a not-ready response', () => {
    expect(deviationColorMap({ ready: false })).toBeNull()
    expect(deviationColorMap({ ready: true, positions: [] })).toBeNull()
  })

  it('maps deviation green→red over [0,max], carries RMSD, and colours each loop copy', () => {
    const map = deviationColorMap(resp)
    expect(map.updates).toHaveLength(3)
    expect(map.updates[1].copy).toBe(1)                          // loop copy positioned
    expect(map.rmsd).toBe(2.5)
    expect(map.colorByKey['h:0:forward']).toBe(deviationHex(0))    // copy 0: matches → green
    expect(map.colorByKey['h:0:forward:1']).toBe(deviationHex(0.5)) // loop copy: its own colour
    expect(map.colorByKey['h:1:forward']).toBe(deviationHex(1))    // far → red
  })

  it('threads the wound slab frame through the deviation updates when present', () => {
    const withFrame = { ready: true, max_deviation: 4, positions: [
      { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0], deviation: 1,
        nx: 1, ny: 0, nz: 0, tx: 0, ty: 0, tz: 1 },
    ] }
    const map = deviationColorMap(withFrame)
    expect(map.updates[0]).toMatchObject({ nx: 1, ny: 0, nz: 0, tx: 0, ty: 0, tz: 1 })
  })
})

describe('initCandoDisplay — flex / deviation modes', () => {
  function makeFullDeps() {
    const designRenderer = {
      applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn(),
      renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn(),
    }
    const api = {
      getCandoDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0] },
      ] })),
      getCandoRmsf: vi.fn(async () => ({
        rmsf: [{ helix_id: 'h', bp_index: 0, rmsf_nm: 1.0 }], min_nm: 0.5, max_nm: 1.5,
      })),
      getCandoDeviation: vi.fn(async () => ({ ready: true, rmsd_nm: 1.7, min_deviation: 0,
        max_deviation: 3, positions: [
          { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0], deviation: 1 },
        ] })),
      getCandoSnapshotGeometry: vi.fn(async () => snapshotResp()),
    }
    return { designRenderer, api }
  }

  it('showFlex deforms + recolours and reports the RMSF range', async () => {
    const { designRenderer, api } = makeFullDeps()
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showFlex('j')
    expect(r.ok).toBe(true)
    expect(designRenderer.applyFemPositions).toHaveBeenCalledWith(expect.any(Array))
    expect(designRenderer.applyScalarColors).toHaveBeenCalled()
    expect(c.mode()).toBe('flex')
    expect(c.lastStats()).toMatchObject({ kind: 'flex', min: 0.5, max: 1.5 })
  })

  it('showDeviation deforms + recolours and reports the RMSD', async () => {
    const { designRenderer, api } = makeFullDeps()
    const c = initCandoDisplay({ designRenderer, api })
    const r = await c.showDeviation('j')
    expect(r.ok).toBe(true)
    expect(r.rmsd).toBe(1.7)
    expect(c.mode()).toBe('deviation')
    expect(c.lastStats()).toMatchObject({ kind: 'deviation', rmsd: 1.7 })
  })

  it('modes are mutually exclusive — switching to deform clears the scalar colours', async () => {
    const { designRenderer, api } = makeFullDeps()
    const c = initCandoDisplay({ designRenderer, api })
    await c.showFlex('j')
    await c.showDeform('j')
    expect(c.mode()).toBe('deform')
    expect(designRenderer.clearScalarColors).toHaveBeenCalled()
  })

  it('refresh re-applies the active mode (live-follow after a job completes)', async () => {
    const { designRenderer, api } = makeFullDeps()
    const c = initCandoDisplay({ designRenderer, api })
    await c.showDeviation('j')
    api.getCandoDeviation.mockClear()
    await c.refresh()
    expect(api.getCandoDeviation).toHaveBeenCalledWith('j', expect.any(AbortSignal))
  })

  it('drives the shared colour-scale widget: shown for flex/deviation, hidden for deform/off', async () => {
    const { designRenderer, api } = makeFullDeps()
    const flexScale = { show: vi.fn(), hide: vi.fn() }
    const c = initCandoDisplay({ designRenderer, api, flexScale })

    await c.showFlex('j')
    expect(flexScale.show).toHaveBeenLastCalledWith(expect.objectContaining({
      title: 'RMSF (nm)', min: 0.5, max: 1.5, mapType: 'flex', onRecolor: expect.any(Function),
    }))

    await c.showDeviation('j')
    expect(flexScale.show).toHaveBeenLastCalledWith(expect.objectContaining({
      title: 'Deviation (nm)', min: 0, max: 3, mapType: 'deviation', onRecolor: expect.any(Function),
    }))

    await c.showDeform('j')          // non-colour-mapped → widget hidden via teardown
    expect(flexScale.hide).toHaveBeenCalled()

    flexScale.hide.mockClear()
    c.stopDeform()
    expect(flexScale.hide).toHaveBeenCalled()
  })
})

describe('initCandoDisplay — CanDo-style cylinder mode', () => {
  function makeCylDeps() {
    const designRenderer = {
      applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn(),
      renderExternalGeometry: vi.fn(), clearExternalGeometry: vi.fn(),
      setDesignVisible: vi.fn(),
    }
    const cylinderOverlay = { update: vi.fn(), clear: vi.fn() }
    const setDesignVisible = vi.fn()
    const api = {
      getCandoDisplay: vi.fn(async () => ({ ready: true, positions: [
        { helix_id: 'h', bp_index: 0, direction: 'forward', backbone_position: [0, 0, 0] },
      ] })),
      getCandoSnapshotGeometry: vi.fn(async () => snapshotResp()),
      getCandoRmsf: vi.fn(async () => ({ rmsf: [{ helix_id: 'h', bp_index: 0, rmsf_nm: 1 }], min_nm: 0.5, max_nm: 1.5 })),
      getCandoCylinders: vi.fn(async () => ({
        ready: true, tube_radius_nm: 1.125, joint_radius_nm: 0.2, n_helices: 2, n_joints: 3,
        has_rmsf: true, rmsf_min: 0.44, rmsf_p95: 1.21, rmsf_max: 1.62,
        helices: [{ helix_id: 'h', points: [[0, 0, 0], [1, 0, 0]] }], joints: [[[0, 0, 0], [1, 0, 0]]],
      })),
    }
    return { designRenderer, api, cylinderOverlay, setDesignVisible }
  }

  it('showCandoStyle draws the tubes and hides the native model', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible })
    const r = await c.showCandoStyle('j')
    expect(r.ok).toBe(true)
    expect(cylinderOverlay.update).toHaveBeenCalledWith(
      expect.objectContaining({ n_helices: 2 }),
      expect.objectContaining({ colormap: expect.any(String) }))
    expect(setDesignVisible).toHaveBeenCalledWith(false)          // native model hidden
    expect(c.mode()).toBe('cando')
    expect(c.lastStats()).toMatchObject({ kind: 'cando', helices: 2, joints: 3 })
  })

  it('shows the RMSF scale (min→p95) for the cylinder heat map; hidden when no RMSF', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    const flexScale = { show: vi.fn(), hide: vi.fn() }
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible, flexScale })

    await c.showCandoStyle('j')
    expect(flexScale.show).toHaveBeenLastCalledWith(expect.objectContaining({
      min: 0.44, max: 1.21, mapType: 'cando', onRecolor: expect.any(Function),
    }))

    // A job run without RMSF → grey tubes → no scale (only the teardown hide fires).
    api.getCandoCylinders.mockResolvedValueOnce({
      ready: true, n_helices: 2, n_joints: 3, has_rmsf: false,
      helices: [{ helix_id: 'h', points: [[0, 0, 0], [1, 0, 0]] }], joints: [],
    })
    flexScale.show.mockClear()
    await c.showCandoStyle('j')
    expect(flexScale.show).not.toHaveBeenCalled()
    expect(flexScale.hide).toHaveBeenCalled()
  })

  it('stopDeform clears the tubes and restores the native model', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible })
    await c.showCandoStyle('j')
    setDesignVisible.mockClear()
    c.stopDeform()
    expect(cylinderOverlay.clear).toHaveBeenCalled()
    expect(setDesignVisible).toHaveBeenLastCalledWith(true)       // native model restored
    expect(c.mode()).toBe(null)
  })

  it('switching cando → flex clears the tubes + restores the model before recolouring', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible })
    await c.showCandoStyle('j')
    await c.showFlex('j')
    expect(cylinderOverlay.clear).toHaveBeenCalled()             // tubes torn down
    expect(setDesignVisible).toHaveBeenLastCalledWith(true)      // model shown again
    expect(designRenderer.applyScalarColors).toHaveBeenCalled()  // flex map applied
    expect(c.mode()).toBe('flex')
  })

  it('switching flex → cando clears the bead overlay before drawing tubes', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible })
    await c.showFlex('j')
    await c.showCandoStyle('j')
    expect(designRenderer.clearExternalGeometry).toHaveBeenCalled()  // snapshot render torn down
    expect(designRenderer.clearScalarColors).toHaveBeenCalled()
    expect(cylinderOverlay.update).toHaveBeenCalled()
    expect(setDesignVisible).toHaveBeenLastCalledWith(false)
  })

  it('not-ready cylinders response leaves the model shown', async () => {
    const { designRenderer, api, cylinderOverlay, setDesignVisible } = makeCylDeps()
    api.getCandoCylinders = vi.fn(async () => ({ ready: false, helices: [], joints: [] }))
    const c = initCandoDisplay({ designRenderer, api, cylinderOverlay, setDesignVisible })
    const r = await c.showCandoStyle('j')
    expect(r.ok).toBe(false)
    expect(cylinderOverlay.update).not.toHaveBeenCalled()
    expect(setDesignVisible).not.toHaveBeenCalled()
  })
})
