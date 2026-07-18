import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, viridisHex, rmsfColorMap, framesToUpdates, initOxdnaDisplay, repKind, rmsfToVertexColors, deviationHex, deviationColorMap } from './oxdna_display.js'

const tick = () => new Promise((r) => setTimeout(r, 0))

describe('framesToUpdates', () => {
  it('zips the shared key list with a flat frame into applyFemPositions updates', () => {
    const keys = [['h0', 0, 'FORWARD'], ['h0', 0, 'REVERSE']]
    const frame = [1, 2, 3, 1, 0, 0,  4, 5, 6, 0, 1, 0]
    expect(framesToUpdates(keys, frame)).toEqual([
      { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0, backbone_position: [1, 2, 3], nx: 1, ny: 0, nz: 0 },
      { helix_id: 'h0', bp_index: 0, direction: 'REVERSE', copy: 0, backbone_position: [4, 5, 6], nx: 0, ny: 1, nz: 0 },
    ])
  })

  it('carries a 4th key element as the loop-copy index', () => {
    const updates = framesToUpdates([['h0', 5, 'REVERSE', 2]], [7, 8, 9, 0, 1, 0])
    expect(updates[0].copy).toBe(2)
  })
  it('returns [] for bad input', () => {
    expect(framesToUpdates(null, [])).toEqual([])
    expect(framesToUpdates([], null)).toEqual([])
  })
})

describe('toFemUpdates', () => {
  it('returns [] for not-ready / empty responses', () => {
    expect(toFemUpdates(null)).toEqual([])
    expect(toFemUpdates({ ready: false, positions: [] })).toEqual([])
    expect(toFemUpdates({ ready: true })).toEqual([])
    expect(toFemUpdates({ ready: true, positions: 'nope' })).toEqual([])
  })

  it('maps the display payload to applyFemPositions update shape (a1 → nx/ny/nz)', () => {
    const resp = {
      ready: true,
      positions: [
        { helix_id: 'h0', bp_index: 3, direction: 'FORWARD',
          backbone_position: [1, 2, 3], nx: 0.1, ny: 0.2, nz: 0.3 },
      ],
    }
    expect(toFemUpdates(resp)).toEqual([
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD', copy: 0,
        backbone_position: [1, 2, 3], nx: 0.1, ny: 0.2, nz: 0.3 },
    ])
  })

  it('carries a loop-copy index through to the update (defaults 0)', () => {
    const resp = { ready: true, positions: [
      { helix_id: 'h0', bp_index: 3, direction: 'REVERSE', copy: 2,
        backbone_position: [4, 5, 6], nx: 0, ny: 1, nz: 0 },
    ] }
    expect(toFemUpdates(resp)[0].copy).toBe(2)
  })
})

describe('viridisHex', () => {
  it('clamps to the endpoints and ramps dark-purple → yellow', () => {
    expect(viridisHex(0)).toBe((68 << 16) | (1 << 8) | 84)     // 0x440154
    expect(viridisHex(1)).toBe((253 << 16) | (231 << 8) | 37)  // 0xfde725
    expect(viridisHex(-5)).toBe(viridisHex(0))                 // clamp low
    expect(viridisHex(99)).toBe(viridisHex(1))                 // clamp high
    expect(viridisHex(NaN)).toBe(viridisHex(0))               // NaN-safe
  })
  it('is monotonic-ish: midpoint differs from the endpoints', () => {
    const mid = viridisHex(0.5)
    expect(mid).not.toBe(viridisHex(0))
    expect(mid).not.toBe(viridisHex(1))
  })
})

describe('deviationHex', () => {
  it('ramps green (low deviation) → red (high), clamped + NaN-safe', () => {
    expect(deviationHex(0)).toBe((63 << 16) | (185 << 8) | 80)    // green = matches design
    expect(deviationHex(1)).toBe((248 << 16) | (81 << 8) | 73)    // red = far from design
    expect(deviationHex(-5)).toBe(deviationHex(0))                // clamp low
    expect(deviationHex(99)).toBe(deviationHex(1))                // clamp high
    expect(deviationHex(NaN)).toBe(deviationHex(0))               // NaN-safe
    expect(deviationHex(0.5)).not.toBe(deviationHex(0))           // amber midpoint distinct
  })
})

describe('deviationColorMap', () => {
  it('returns null for not-ready / empty responses', () => {
    expect(deviationColorMap(null)).toBe(null)
    expect(deviationColorMap({ ready: false, positions: [] })).toBe(null)
    expect(deviationColorMap({ ready: true, positions: [] })).toBe(null)
  })
  it('scales deviation min→max and colours the extremes green/red', () => {
    const resp = {
      ready: true, min_deviation: 0.3, max_deviation: 2.1,
      positions: [
        { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, deviation: 0.3 },
        { helix_id: 'h0', bp_index: 1, direction: 'FORWARD', backbone_position: [1, 0, 0], nx: 1, ny: 0, nz: 0, deviation: 2.1 },
      ],
    }
    const map = deviationColorMap(resp)
    expect(map.updates).toHaveLength(2)
    expect(map.updates[0]).not.toHaveProperty('deviation')          // stripped to applyFem shape
    expect(map.colorByKey['h0:0:FORWARD']).toBe(deviationHex(0))     // best match → green
    expect(map.colorByKey['h0:1:FORWARD']).toBe(deviationHex(1))     // worst → red
    expect(map.min).toBe(0.3)
    expect(map.max).toBe(2.1)
  })
  it('handles a uniform deviation without dividing by zero', () => {
    const resp = { ready: true, min_deviation: 0.8, max_deviation: 0.8,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, deviation: 0.8 }] }
    const map = deviationColorMap(resp)
    expect(map.colorByKey['h0:0:FORWARD']).toBe(deviationHex(0))
  })
})

describe('rmsfColorMap', () => {
  it('returns null for not-ready / empty responses', () => {
    expect(rmsfColorMap(null)).toBe(null)
    expect(rmsfColorMap({ ready: false, positions: [] })).toBe(null)
    expect(rmsfColorMap({ ready: true, positions: [] })).toBe(null)
  })
  it('scales RMSF relative to min→max and colours the extremes purple/yellow', () => {
    const resp = {
      ready: true, min_rmsf: 0.2, max_rmsf: 1.2,
      positions: [
        { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.2 },
        { helix_id: 'h0', bp_index: 1, direction: 'FORWARD', backbone_position: [1, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 1.2 },
      ],
    }
    const map = rmsfColorMap(resp)
    expect(map.updates).toHaveLength(2)
    expect(map.updates[0]).not.toHaveProperty('rmsf')            // stripped to applyFem shape
    expect(map.colorByKey['h0:0:FORWARD']).toBe(viridisHex(0))   // rigid end → purple
    expect(map.colorByKey['h0:1:FORWARD']).toBe(viridisHex(1))   // flexible end → yellow
    expect(map.min).toBe(0.2)
    expect(map.max).toBe(1.2)
  })
  it('handles a uniform-RMSF design without dividing by zero', () => {
    const resp = { ready: true, min_rmsf: 0.5, max_rmsf: 0.5,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.5 }] }
    const map = rmsfColorMap(resp)
    expect(map.colorByKey['h0:0:FORWARD']).toBe(viridisHex(0))   // span 0 → all rigid colour
  })

  it('honours explicit bounds (clamping out-of-range to the endpoints); reported min/max stay the data range', () => {
    const resp = { ready: true, min_rmsf: 0, max_rmsf: 2, positions: [
      { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.5 },
      { helix_id: 'h0', bp_index: 1, direction: 'FORWARD', backbone_position: [1, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 1.5 },
    ] }
    const map = rmsfColorMap(resp, 0.5, 1.5)              // tightened window
    expect(map.colorByKey['h0:0:FORWARD']).toBe(viridisHex(0))   // 0.5 → bottom of window
    expect(map.colorByKey['h0:1:FORWARD']).toBe(viridisHex(1))   // 1.5 → top of window
    expect(map.min).toBe(0)                                       // data range, not bounds
    expect(map.max).toBe(2)
  })
  it('keeps loop-insertion copies distinct (MD flex map): same helix/bp/dir, different copy', () => {
    // A curved design's loop base + its insertion copy share (helix,bp,dir); the
    // backend now tags them with `copy` so each addresses its OWN bead/colour.
    const resp = { ready: true, min_rmsf: 0, max_rmsf: 1, positions: [
      { helix_id: 'h0', bp_index: 5, direction: 'FORWARD', copy: 0, backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0 },
      { helix_id: 'h0', bp_index: 5, direction: 'FORWARD', copy: 1, backbone_position: [1, 1, 1], nx: 1, ny: 0, nz: 0, rmsf: 1 },
    ] }
    const map = rmsfColorMap(resp)
    expect(map.updates).toHaveLength(2)                           // neither copy dropped
    expect(map.updates[0].copy).toBe(0)
    expect(map.updates[1].copy).toBe(1)
    // 4-part keys differ so applyFemPositions routes each to its own bead...
    expect(map.colorByKey['h0:5:FORWARD:0']).toBe(viridisHex(0))
    expect(map.colorByKey['h0:5:FORWARD:1']).toBe(viridisHex(1))
    // ...and the 3-part alias is the copy-0 base (unchanged for legacy consumers).
    expect(map.colorByKey['h0:5:FORWARD']).toBe(viridisHex(0))
  })
})

describe('rmsfToVertexColors', () => {
  it('maps per-vertex RMSF onto the viridis ramp (3 RGB floats per vertex)', () => {
    const col = rmsfToVertexColors([0, 0.5, 1], 0, 1)
    expect(col).toBeInstanceOf(Float32Array)
    expect(col.length).toBe(9)
    // lo end = viridis[0] (#440154), hi end = viridis[4] (#fde725).
    expect(col[0]).toBeCloseTo(0x44 / 255, 5)
    expect(col[6]).toBeCloseTo(0xfd / 255, 5)
    expect(col[8]).toBeCloseTo(0x25 / 255, 5)
  })
  it('clamps out-of-range values and tolerates a zero-width scale', () => {
    const clamped = rmsfToVertexColors([-5, 5], 0, 1)            // both clamp to endpoints
    expect(clamped[0]).toBeCloseTo(0x44 / 255, 5)               // ≤lo → dark purple
    expect(clamped[3]).toBeCloseTo(0xfd / 255, 5)               // ≥hi → yellow
    const flat = rmsfToVertexColors([0.5], 1, 1)                // span 0 → t=0
    expect(flat[0]).toBeCloseTo(0x44 / 255, 5)
  })
})

describe('initOxdnaDisplay controller', () => {
  function makeDeps(displayResp) {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaDisplay: vi.fn().mockResolvedValue(displayResp) }
    return { designRenderer, api }
  }

  it('applies positions and tracks active job', async () => {
    const resp = { ready: true, stage_name: '3_equil',
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0,
        backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }
    const deps = makeDeps(resp)
    const ctrl = initOxdnaDisplay(deps)

    const r = await ctrl.displayJob('job1')
    expect(r.ok).toBe(true)
    expect(r.n).toBe(1)
    expect(r.stage).toBe('3_equil')
    expect(deps.designRenderer.applyFemPositions).toHaveBeenCalledWith(resp.positions)
    expect(ctrl.isActive()).toBe(true)
    expect(ctrl.activeJobId()).toBe('job1')
  })

  it('forwards each frame to onFrame and null on stop (flexible-arc sim positions)', async () => {
    const resp = { ready: true, stage_name: 's',
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0,
        backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }
    const deps = makeDeps(resp)
    const onFrame = vi.fn()
    const ctrl = initOxdnaDisplay({ ...deps, onFrame })
    await ctrl.displayJob('job1')
    expect(onFrame).toHaveBeenCalledWith(resp.positions)
    ctrl.stopAndRestore()
    expect(onFrame).toHaveBeenLastCalledWith(null)
  })

  it('does not activate when there is no relaxed frame', async () => {
    const deps = makeDeps({ ready: false, positions: [] })
    const ctrl = initOxdnaDisplay(deps)
    const r = await ctrl.displayJob('job1')
    expect(r.ok).toBe(false)
    expect(ctrl.isActive()).toBe(false)
    expect(deps.designRenderer.applyFemPositions).not.toHaveBeenCalled()
  })

  it('displayLiveFrame applies a positions payload directly (live mode, no fetch)', () => {
    const deps = makeDeps({ ready: false, positions: [] })
    const ctrl = initOxdnaDisplay(deps)
    const positions = [{ helix_id: 'h0', bp_index: 2, direction: 'REVERSE', copy: 0,
      backbone_position: [4, 5, 6], nx: 0, ny: 1, nz: 0 }]
    const applied = ctrl.displayLiveFrame(positions)
    expect(applied).toBe(true)
    expect(deps.api.getOxdnaDisplay).not.toHaveBeenCalled()   // no network for a live frame
    expect(deps.designRenderer.applyFemPositions).toHaveBeenCalledWith(positions)
    expect(ctrl.isActive()).toBe(true)
    expect(ctrl.mode()).toBe('live')
    expect(ctrl.activeJobId()).toBe(null)
  })

  it('displayLiveFrame ignores empty/bad payloads', () => {
    const deps = makeDeps({ ready: false, positions: [] })
    const ctrl = initOxdnaDisplay(deps)
    expect(ctrl.displayLiveFrame([])).toBe(false)
    expect(ctrl.displayLiveFrame(null)).toBe(false)
    expect(ctrl.isActive()).toBe(false)
  })

  it('stopAndRestore clears the overlay', async () => {
    const resp = { ready: true, positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD',
      backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }
    const deps = makeDeps(resp)
    const ctrl = initOxdnaDisplay(deps)
    await ctrl.displayJob('job1')
    ctrl.stopAndRestore()
    expect(deps.designRenderer.applyFemPositions).toHaveBeenLastCalledWith(null)
    expect(deps.designRenderer.clearScalarColors).toHaveBeenCalled()
    expect(ctrl.isActive()).toBe(false)
    expect(ctrl.activeJobId()).toBe(null)
  })

  it('a displayJob fetch that resolves AFTER stopAndRestore does not re-apply positions', async () => {
    // Reproduces the "toggle off but sim positions stay" desync: the live-follow
    // poll's displayJob is in flight when the user turns the display off.
    const resp = { ready: true, stage_name: 's', positions: [{ helix_id: 'h0', bp_index: 0,
      direction: 'FORWARD', backbone_position: [7, 7, 7], nx: 1, ny: 0, nz: 0 }] }
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaDisplay: vi.fn().mockResolvedValue(resp) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    await ctrl.displayJob('job0')       // display is on, showing job0
    expect(ctrl.isActive()).toBe(true)

    // Now a live-follow poll's displayJob is in flight when the user toggles off.
    let release
    api.getOxdnaDisplay = vi.fn().mockReturnValue(new Promise((res) => { release = () => res(resp) }))
    const p = ctrl.displayJob('job0')   // fetch in flight
    ctrl.stopAndRestore()               // user toggles off mid-flight
    release()
    const r = await p
    expect(r.ok).toBe(false)            // the late fetch bailed (superseded)
    expect(ctrl.isActive()).toBe(false)
    // applyFemPositions(null) from stopAndRestore is the LAST call — no re-apply after it.
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(null)
  })

  it('switching to a job with no relaxed frame clears the previous job\'s stale overlay', async () => {
    const respA = { ready: true, stage_name: 's', positions: [{ helix_id: 'h0', bp_index: 0,
      direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaDisplay: vi.fn().mockResolvedValue(respA) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    await ctrl.displayJob('jobA')
    expect(ctrl.activeJobId()).toBe('jobA')

    api.getOxdnaDisplay = vi.fn().mockResolvedValue({ ready: false, positions: [] })
    const r = await ctrl.displayJob('jobB')   // jobB has no frame yet
    expect(r.ok).toBe(false)
    expect(ctrl.isActive()).toBe(false)       // stale jobA overlay cleared
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(null)
  })

  it('loadTrajectory caches frames and showFrame deforms to a given frame', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const traj = {
      ready: true, n_frames: 2, n_nucleotides: 1,
      keys: [['h0', 0, 'FORWARD']],
      frames: [[1, 1, 1, 1, 0, 0], [2, 2, 2, 1, 0, 0]],
      markers: [{ frame: 1, kind: 'production' }], stages: [{ kind: 'equil' }, { kind: 'production' }],
    }
    const api = { getOxdnaTrajectory: vi.fn().mockResolvedValue(traj) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const r = await ctrl.loadTrajectory('jobT')
    expect(r.ok).toBe(true)
    expect(r.n_frames).toBe(2)
    expect(ctrl.mode()).toBe('trajectory')
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(
      [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0, backbone_position: [1, 1, 1], nx: 1, ny: 0, nz: 0 }])
    ctrl.showFrame(1)
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(
      [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', copy: 0, backbone_position: [2, 2, 2], nx: 1, ny: 0, nz: 0 }])
  })

  it('aborts an in-flight trajectory request when toggled off before it loads', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    let signal, release
    const api = { getOxdnaTrajectory: vi.fn((id, opts) => {
      signal = opts?.signal
      return new Promise(resolve => { release = () => resolve(null) })
    }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const pending = ctrl.loadTrajectory('wrong-job')
    expect(signal.aborted).toBe(false)
    ctrl.cancelPendingLoad()
    expect(signal.aborted).toBe(true)
    release()
    await expect(pending).resolves.toMatchObject({ ok: false, reason: 'superseded' })
  })

  it('loadTrajectory reports not-ready when there are no frames', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaTrajectory: vi.fn().mockResolvedValue({ ready: false, reason: 'no trajectory yet' }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const r = await ctrl.loadTrajectory('jobT')
    expect(r.ok).toBe(false)
    expect(ctrl.isActive()).toBe(false)
  })

  it('displayRmsf deforms to the average structure and recolours by RMSF', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaRmsf: vi.fn().mockResolvedValue({
      ready: true, n_frames: 12, min_rmsf: 0.1, max_rmsf: 0.9, mean_rmsf: 0.5,
      confidence: { n_frames: 12, rel_error: 0.2, preliminary: true }, production_running: true,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.1 }],
    }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const r = await ctrl.displayRmsf('jobF')
    expect(r.ok).toBe(true)
    expect(r.min).toBe(0.1)
    expect(r.max).toBe(0.9)
    expect(r.nFrames).toBe(12)                    // confidence passthrough
    expect(r.confidence.preliminary).toBe(true)
    expect(r.running).toBe(true)
    expect(designRenderer.applyFemPositions).toHaveBeenCalled()
    expect(designRenderer.applyScalarColors).toHaveBeenCalled()
    expect(ctrl.mode()).toBe('rmsf')
    // Switching to the relaxed display clears the scalar colours.
    api.getOxdnaDisplay = vi.fn().mockResolvedValue({ ready: true, stage_name: 's',
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] })
    await ctrl.displayJob('jobF')
    expect(designRenderer.clearScalarColors).toHaveBeenCalled()
    expect(ctrl.mode()).toBe('relaxed')
  })

  it('recolorRmsf re-applies colours from the cached payload with custom bounds, without moving positions', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaRmsf: vi.fn().mockResolvedValue({ ready: true, n_frames: 5, min_rmsf: 0.1, max_rmsf: 0.9, mean_rmsf: 0.5,
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.5 }] }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    await ctrl.displayRmsf('jobF')
    expect(designRenderer.applyFemPositions).toHaveBeenCalledTimes(1)
    designRenderer.applyScalarColors.mockClear()

    const ok = ctrl.recolorRmsf(0.1, 0.5)
    expect(ok).toBe(true)
    expect(designRenderer.applyScalarColors).toHaveBeenCalledTimes(1)
    expect(designRenderer.applyFemPositions).toHaveBeenCalledTimes(1)   // positions untouched
  })

  it('recolorRmsf is a no-op when the flexibility map is not the active overlay', () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const ctrl = initOxdnaDisplay({ designRenderer, api: {} })
    expect(ctrl.recolorRmsf(0, 1)).toBe(false)
    expect(designRenderer.applyScalarColors).not.toHaveBeenCalled()
  })

  it('displayRmsf reports not-ready reason without touching the renderer', async () => {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaRmsf: vi.fn().mockResolvedValue({ ready: false, reason: 'waiting for production' }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const r = await ctrl.displayRmsf('jobF')
    expect(r.ok).toBe(false)
    expect(r.reason).toBe('waiting for production')
    expect(designRenderer.applyScalarColors).not.toHaveBeenCalled()
  })
})

describe('repKind', () => {
  it('maps scene representations to the renderer that drives them', () => {
    expect(repKind('vdw')).toBe('atomistic')
    expect(repKind('ballstick')).toBe('atomistic')
    expect(repKind('surface')).toBe('surface')
    expect(repKind('full')).toBe('cg')
    expect(repKind('beads')).toBe('cg')
    expect(repKind('cylinders')).toBe('cg')
    expect(repKind(undefined)).toBe('cg')
  })
})

describe('initOxdnaDisplay heavy reps (atomistic / surface)', () => {
  function makeHeavyDeps(repr = 'ballstick') {
    const state = { repr }
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const atom = { getMode: () => 'ballstick', applyPositionLerp: vi.fn(), update: vi.fn(),
                   applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const surf = { getMode: () => (state.repr === 'surface' ? 'on' : 'off'), applyPositionLerp: vi.fn(),
                   applyScalarVertexColors: vi.fn() }
    const onRestoreDesignHeavy = vi.fn()
    const onHeavyStatus = vi.fn()
    const api = {
      getOxdnaDisplay: vi.fn().mockResolvedValue({ ready: true, stage_name: 's',
        positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }),
      getOxdnaDisplayAtomistic: vi.fn().mockResolvedValue({ ready: true, atomistic: [1, 2, 3, 4, 5, 6], topology_hash: 'jobtopo', n_atoms: 2 }),
      getOxdnaAtomisticModel: vi.fn().mockResolvedValue({ topology_hash: 'jobtopo',
        atoms: [{ serial: 0, element: 'C', strand_id: 's', residue: 'DT' }, { serial: 1, element: 'O', strand_id: 's', residue: 'DT' }], bonds: [[0, 1]] }),
      getOxdnaDisplaySurface:   vi.fn().mockResolvedValue({ ready: true, surface: { vertices: [0, 0, 0, 1, 1, 1], faces: [0, 1, 2] } }),
      getOxdnaRmsf: vi.fn().mockResolvedValue({ ready: true, n_frames: 5, min_rmsf: 0.1, max_rmsf: 0.9, mean_rmsf: 0.5,
        positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.5 }] }),
      getOxdnaRmsfAtomistic: vi.fn().mockResolvedValue({ ready: true, atomistic: [7, 8, 9] }),
      getOxdnaRmsfSurface: vi.fn().mockResolvedValue({ ready: true, surface: { vertices: [0, 0, 0, 1, 1, 1, 2, 2, 2], faces: [0, 1, 2], vertex_rmsf: [0.1, 0.5, 0.9] } }),
      getOxdnaTrajectory: vi.fn().mockResolvedValue({ ready: true, n_frames: 5, keys: [['h0', 0, 'FORWARD']],
        frames: [[0, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0], [2, 0, 0, 1, 0, 0], [3, 0, 0, 1, 0, 0], [4, 0, 0, 1, 0, 0]] }),
      getOxdnaFramesAtomistic: vi.fn().mockImplementation((id, idxs) =>
        Promise.resolve(Object.fromEntries(idxs.map((i) => [String(i), [i, i, i]])))),
      getOxdnaFramesSurface: vi.fn().mockImplementation((id, idxs) =>
        Promise.resolve(Object.fromEntries(idxs.map((i) => [String(i), { vertices: [i, i, i], faces: [0, 1, 2] }])))),
    }
    const ctrl = initOxdnaDisplay({
      designRenderer, api, atom, surf, onRestoreDesignHeavy, onHeavyStatus,
      getAtomisticRenderer: () => atom, getSurfaceRenderer: () => surf,
      getCurrentRepr: () => state.repr,
    })
    return { ctrl, api, atom, surf, designRenderer, onRestoreDesignHeavy, onHeavyStatus, state }
  }

  it('relaxed display REBUILDS the renderer from the job topology, then overlays atoms', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('ballstick')
    await ctrl.displayJob('job1')
    await tick()
    expect(api.getOxdnaDisplayAtomistic).toHaveBeenCalledWith('job1', true)
    // The renderer is rebuilt from the JOB's own atoms/bonds (not the loaded design),
    // so the serial-indexed relaxed positions land on the right atoms (no scramble).
    expect(api.getOxdnaAtomisticModel).toHaveBeenCalledWith('job1')
    expect(atom.update).toHaveBeenCalledWith({
      atoms: [{ serial: 0, element: 'C', strand_id: 's', residue: 'DT' }, { serial: 1, element: 'O', strand_id: 's', residue: 'DT' }],
      bonds: [[0, 1]],
    })
    expect(atom.applyPositionLerp).toHaveBeenCalledWith([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6], 0, null, [], null)
  })

  it('relaxed display uses the FAST stamp path when the bundle endpoint exists', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('ballstick')
    // Combined bundle: renderer topology (atoms+bonds) + stamp descriptor in one fetch.
    // 2 rigid atoms under one identity-framed nucleotide.
    api.getOxdnaAtomisticDisplayBundle = vi.fn().mockResolvedValue({
      topology_hash: 'jobtopo', n_nuc: 1, n_atoms: 2,
      atoms: [{ serial: 0, element: 'C', strand_id: 's', residue: 'DT' }, { serial: 1, element: 'O', strand_id: 's', residue: 'DT' }],
      bonds: [[0, 1]],
      atom_nuc: [0, 0], atom_local: [1, 0, 0, 0, 1, 0], nonrigid_serials: [],
    })
    api.getOxdnaDisplayAtomisticFrames = vi.fn().mockResolvedValue({
      ready: true, topology_hash: 'jobtopo', n_nuc: 1,
      frames: [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], nonrigid_xyz: [],
    })
    await ctrl.displayJob('job1')
    await tick()
    // Fast path: bundle + frames fetched; the SLOW full-flat + separate model NOT called.
    expect(api.getOxdnaAtomisticDisplayBundle).toHaveBeenCalledWith('job1')
    expect(api.getOxdnaDisplayAtomisticFrames).toHaveBeenCalledWith('job1', true)
    expect(api.getOxdnaDisplayAtomistic).not.toHaveBeenCalled()
    expect(api.getOxdnaAtomisticModel).not.toHaveBeenCalled()
    // Expanded client-side: atom0 = origin+R·(1,0,0)=(1,0,0), atom1 = (0,1,0).
    const arg = atom.applyPositionLerp.mock.calls.at(-1)[0]
    expect(Array.from(arg)).toEqual([1, 0, 0, 0, 1, 0])
  })

  it('does NOT paint the renderer at native positions before the relaxed frame arrives (no flash)', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('ballstick')
    // Fast bundle path, but hold the relaxed FRAMES pending so we can observe the window
    // that used to show native atoms (ar.update ran, then this fetch was awaited).
    let resolveFrames
    const framesP = new Promise((res) => { resolveFrames = res })
    api.getOxdnaAtomisticDisplayBundle = vi.fn().mockResolvedValue({
      topology_hash: 'jobtopo', n_nuc: 1, n_atoms: 2,
      atoms: [{ serial: 0, element: 'C', strand_id: 's', residue: 'DT' }, { serial: 1, element: 'O', strand_id: 's', residue: 'DT' }],
      bonds: [[0, 1]],
      atom_nuc: [0, 0], atom_local: [1, 0, 0, 0, 1, 0], nonrigid_serials: [],
    })
    api.getOxdnaDisplayAtomisticFrames = vi.fn().mockReturnValue(framesP)

    const p = ctrl.displayJob('job1')
    await tick(); await tick()   // bundle resolves; frames still pending
    // The renderer must NOT have been rebuilt (painted at native) while frames are pending.
    expect(atom.update).not.toHaveBeenCalled()
    expect(atom.applyPositionLerp).not.toHaveBeenCalled()

    resolveFrames({ ready: true, topology_hash: 'jobtopo', n_nuc: 1,
      frames: [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1], nonrigid_xyz: [] })
    await p; await tick()
    // Painted AND relaxed together: update once, immediately followed by the position apply.
    expect(atom.update).toHaveBeenCalledTimes(1)
    expect(atom.applyPositionLerp).toHaveBeenCalledTimes(1)
  })

  it('re-applies the relaxed CG overlay when a CG rep is restored (re-pins __xb__/__ext_)', async () => {
    const { ctrl, designRenderer } = makeHeavyDeps('full')   // CG target rep
    await ctrl.displayJob('job1'); await tick()
    const updates = designRenderer.applyFemPositions.mock.calls.at(-1)[0]
    expect(updates?.length).toBeTruthy()
    designRenderer.applyFemPositions.mockClear()
    // Switching back to a CG rep fires reapplyForRepr — it must re-apply the last relaxed
    // overlay so extra-base / extension beads aren't left stranded at native by the
    // arc-layout pass that runs on setCGVisible.
    ctrl.reapplyForRepr()
    expect(designRenderer.applyFemPositions).toHaveBeenCalledWith(updates)
  })

  it('rebuilds the job topology only ONCE per job (cached across frames)', async () => {
    const { ctrl, api } = makeHeavyDeps('ballstick')
    await ctrl.displayJob('job1'); await tick()
    await ctrl.displayJob('job1'); await tick()      // same job again
    expect(api.getOxdnaAtomisticModel).toHaveBeenCalledTimes(1)
  })

  it('relaxed display in surface rep pushes a reconstructed mesh', async () => {
    const { ctrl, api, surf } = makeHeavyDeps('surface')
    await ctrl.displayJob('job1')
    await tick()
    expect(api.getOxdnaDisplaySurface).toHaveBeenCalledWith('job1', true, expect.anything())
    const data = { vertices: [0, 0, 0, 1, 1, 1], faces: [0, 1, 2] }
    expect(surf.applyPositionLerp).toHaveBeenCalledWith(data, data, 0)
  })

  it('flexibility map drives the atomistic rep AND recolours atoms by RMSF', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('vdw')
    await ctrl.displayRmsf('jobF')
    await tick()
    expect(api.getOxdnaRmsfAtomistic).toHaveBeenCalledWith('jobF', { align: true })
    expect(atom.applyPositionLerp).toHaveBeenCalledWith([7, 8, 9], [7, 8, 9], 0, null, [], null)
    // Atoms get the SAME viridis ramp as the beads: a colorByKey keyed by helix:bp:dir.
    expect(atom.applyScalarColors).toHaveBeenCalled()
    const cmap = atom.applyScalarColors.mock.calls.at(-1)[0]
    expect(cmap).toHaveProperty('h0:0:FORWARD')
  })

  it('flexibility map colours the surface mesh by per-vertex RMSF (scalar, not strand)', async () => {
    const { ctrl, api, surf } = makeHeavyDeps('surface')
    await ctrl.displayRmsf('jobF')
    await tick()
    expect(api.getOxdnaRmsfSurface).toHaveBeenCalledWith('jobF', {}, { align: true })
    const pushed = surf.applyPositionLerp.mock.calls.at(-1)[0]
    expect(pushed.scalar).toBe(true)                          // forces viridis through any colour mode
    expect(pushed.vertex_colors).toBeInstanceOf(Float32Array)
    expect(pushed.vertex_colors.length).toBe(3 * 3)           // 3 verts × RGB
  })

  it('stopAndRestore clears active/mode BEFORE restoring the design heavy rep (so the restore does not re-defer → rep persists, no revert to CG)', async () => {
    const seen = {}
    const surf = { getMode: () => 'on', applyPositionLerp: vi.fn() }
    const atom = { getMode: () => 'off', clearScalarColors: vi.fn() }
    const designRenderer = { applyFemPositions: vi.fn(), clearScalarColors: vi.fn() }
    const api = {
      getOxdnaDisplay: vi.fn().mockResolvedValue({ ready: true, stage_name: 's',
        positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0 }] }),
      getOxdnaDisplaySurface: vi.fn().mockResolvedValue(
        { ready: true, surface: { vertices: [0, 0, 0, 1, 1, 1], faces: [0, 1, 2] } }),
    }
    // The restore callback captures the controller's active/mode state at restore time —
    // drivesHeavy() (which decides whether applySurfaceMode DEFERS) reads exactly these.
    const ctrl = initOxdnaDisplay({
      designRenderer, api,
      getAtomisticRenderer: () => atom, getSurfaceRenderer: () => surf,
      getCurrentRepr: () => 'surface',
      onRestoreDesignHeavy: () => { seen.active = ctrl.isActive(); seen.mode = ctrl.mode() },
    })
    await ctrl.displayJob('job1'); await tick()
    ctrl.stopAndRestore()
    expect(seen.active).toBe(false)   // overlay already inactive → drivesHeavy() false → no defer
    expect(seen.mode).toBe(null)
  })

  it('flex map is cached across toggle-off → re-toggle is instant (no re-fetch)', async () => {
    const { ctrl, api } = makeHeavyDeps('full')   // CG so no heavy rebuild noise
    await ctrl.displayRmsf('jobF')
    await tick()
    expect(api.getOxdnaRmsf).toHaveBeenCalledTimes(1)
    ctrl.stopAndRestore()                          // user toggles the flex map OFF
    await ctrl.displayRmsf('jobF')                 // …then ON again
    await tick()
    expect(api.getOxdnaRmsf).toHaveBeenCalledTimes(1)   // served from cache — NOT recomputed
    // refresh() forces a re-fetch (production may have advanced).
    await ctrl.refresh()
    expect(api.getOxdnaRmsf).toHaveBeenCalledTimes(2)
  })

  it('recolorRmsf re-applies the new scale to the active atomistic overlay (no re-fetch)', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('vdw')
    await ctrl.displayRmsf('jobF')
    await tick()
    api.getOxdnaRmsfAtomistic.mockClear()
    atom.applyScalarColors.mockClear()
    expect(ctrl.recolorRmsf(0.2, 0.6)).toBe(true)
    expect(atom.applyScalarColors).toHaveBeenCalled()        // recoloured in place…
    expect(api.getOxdnaRmsfAtomistic).not.toHaveBeenCalled() // …without re-fetching positions
  })

  it('recolorRmsf recolours the active surface overlay from cached per-vertex RMSF', async () => {
    const { ctrl, surf } = makeHeavyDeps('surface')
    await ctrl.displayRmsf('jobF')
    await tick()
    expect(ctrl.recolorRmsf(0.2, 0.6)).toBe(true)
    expect(surf.applyScalarVertexColors).toHaveBeenCalled()
    expect(surf.applyScalarVertexColors.mock.calls.at(-1)[0]).toBeInstanceOf(Float32Array)
  })

  it('leaving the flex map clears the atomistic scalar overlay (no stale RMSF on the design)', async () => {
    const { ctrl, atom } = makeHeavyDeps('vdw')
    await ctrl.displayRmsf('jobF')
    await tick()
    ctrl.stopAndRestore()
    expect(atom.clearScalarColors).toHaveBeenCalled()
  })

  it('flexibility-map heavy reconstruction reports build status (true→false), so the panel can show a spinner', async () => {
    const { ctrl, onHeavyStatus } = makeHeavyDeps('vdw')
    await ctrl.displayRmsf('jobF')
    await tick()
    const flags = onHeavyStatus.mock.calls.map((c) => c[0].building)
    expect(flags).toContain(true)                        // announced while rebuilding the avg structure
    expect(flags[flags.length - 1]).toBe(false)          // cleared when done (no frozen panel)
    expect(onHeavyStatus.mock.calls.some((c) => c[0].mode === 'rmsf')).toBe(true)
  })

  it('coarse trajectory fetches grid cells LAZILY (one frame per visit), never a big upfront batch, and caches revisits', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT')           // showFrame(0) → fetch ONLY the nearest grid cell
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledTimes(1)
    expect(api.getOxdnaFramesAtomistic.mock.calls[0][1]).toEqual([0])   // one frame — NOT a 40-frame bake
    api.getOxdnaFramesAtomistic.mockClear()
    ctrl.showFrame(3)                            // a new grid cell → one more single-frame fetch
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledTimes(1)
    expect(api.getOxdnaFramesAtomistic.mock.calls[0][1]).toEqual([3])
    api.getOxdnaFramesAtomistic.mockClear()
    ctrl.showFrame(0)                            // revisit a cached cell → NO refetch
    await tick()
    expect(api.getOxdnaFramesAtomistic).not.toHaveBeenCalled()
    expect(atom.applyPositionLerp).toHaveBeenCalled()
  })

  it('reports heavy-status (building true→false) around an uncached coarse rebuild, and false on stop', async () => {
    const { ctrl, onHeavyStatus } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT')           // showFrame(0) → uncached cell → building true then false
    await tick()
    const flags = onHeavyStatus.mock.calls.map((c) => c[0].building)
    expect(flags).toContain(true)
    expect(flags[flags.length - 1]).toBe(false)   // cleared when the rebuild finished
    onHeavyStatus.mockClear()
    ctrl.stopAndRestore()                        // toggle-off mid-anything always clears the spinner
    expect(onHeavyStatus).toHaveBeenCalledWith({ building: false, kind: null, mode: expect.anything() })
  })

  it('fine granularity reconstructs the EXACT scrubbed frame on demand', async () => {
    const { ctrl, api } = makeHeavyDeps('ballstick')
    ctrl.setGranularity('fine')
    await ctrl.loadTrajectory('jobT')
    await tick()
    api.getOxdnaFramesAtomistic.mockClear()
    ctrl.showFrame(2)
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledWith('jobT', [2], true)
  })

  it('stopAndRestore rebuilds the design heavy reps; a late reconstruction does not re-apply', async () => {
    const { ctrl, api, atom, onRestoreDesignHeavy } = makeHeavyDeps('ballstick')
    await ctrl.displayJob('job1')       // heavy overlay applied
    await tick()
    expect(atom.applyPositionLerp).toHaveBeenCalledTimes(1)
    // A re-apply (e.g. rep change) is now in flight when the user toggles off.
    let release
    api.getOxdnaDisplayAtomistic = vi.fn().mockReturnValue(
      new Promise((res) => { release = () => res({ ready: true, atomistic: [9, 9, 9] }) }))
    ctrl.reapplyForRepr()               // pending reconstruction
    atom.applyPositionLerp.mockClear()
    ctrl.stopAndRestore()               // toggle off mid-reconstruction
    expect(onRestoreDesignHeavy).toHaveBeenCalledTimes(1)   // overlay → design rebuilt
    expect(ctrl.isActive()).toBe(false)
    release()                           // late reconstruction resolves…
    await tick()
    expect(atom.applyPositionLerp).not.toHaveBeenCalled()   // …but is discarded (superseded)
  })

  it('prebuildHeavy builds every coarse grid cell once (for smooth playback), reporting progress', async () => {
    const { ctrl, api } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT')           // showFrame(0) caches grid cell 0
    await tick()
    api.getOxdnaFramesAtomistic.mockClear()
    const progress = []
    const r = await ctrl.prebuildHeavy((done, total) => progress.push([done, total]))
    expect(r.ok).toBe(true)
    // n_frames=5 → grid is [0..4]; cell 0 already cached → 4 more single-frame builds.
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledTimes(4)
    expect(api.getOxdnaFramesAtomistic.mock.calls.every((c) => c[1].length === 1)).toBe(true)
    expect(progress[progress.length - 1]).toEqual([5, 5])   // all cells built
    // A second prebuild is a no-op (everything cached).
    api.getOxdnaFramesAtomistic.mockClear()
    await ctrl.prebuildHeavy(() => {})
    expect(api.getOxdnaFramesAtomistic).not.toHaveBeenCalled()
  })

  it('prebuildHeavy is a no-op for the CG rep (frames are instant — nothing to bake)', async () => {
    const { ctrl, api, state } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT'); await tick()
    state.repr = 'full'                          // CG
    api.getOxdnaFramesAtomistic.mockClear()
    const r = await ctrl.prebuildHeavy(() => {})
    expect(r).toEqual({ ok: true, n: 0 })
    expect(api.getOxdnaFramesAtomistic).not.toHaveBeenCalled()
  })

  it('setPlaying(true) forces COARSE even when granularity is fine (no per-tick fine rebuild stalls the loop)', async () => {
    const { ctrl, api } = makeHeavyDeps('ballstick')
    ctrl.setGranularity('fine')
    await ctrl.loadTrajectory('jobT'); await tick()
    ctrl.setPlaying(true)
    api.getOxdnaFramesAtomistic.mockClear()
    ctrl.showFrame(2)                            // would be a fine [2] fetch when paused…
    await tick()
    // …but while playing it snaps to the coarse grid cell instead (cell 2 here).
    expect(api.getOxdnaFramesAtomistic.mock.calls.every((c) => c[1].length === 1)).toBe(true)
    ctrl.setPlaying(false)
  })

  it('reapplyForRepr re-overlays the current frame onto a freshly-built rep', async () => {
    const { ctrl, api, surf, state } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT')
    await tick()
    // User switches the scene to surface — the new mesh needs the oxDNA overlay.
    state.repr = 'surface'
    ctrl.reapplyForRepr()
    await tick()
    expect(api.getOxdnaFramesSurface).toHaveBeenCalled()
    expect(surf.applyPositionLerp).toHaveBeenCalled()
  })
})

describe('proteinTransformMap', () => {
  it('extracts {attachmentId: 16-float} from a /display proteins list', async () => {
    const { proteinTransformMap } = await import('./oxdna_display.js')
    const M = Array.from({ length: 16 }, (_, i) => i)
    const resp = { proteins: [{ attachment_id: 'a1', transform: M }] }
    expect(proteinTransformMap(resp)).toEqual({ a1: M })
  })
  it('skips malformed / missing entries and tolerates no proteins', async () => {
    const { proteinTransformMap } = await import('./oxdna_display.js')
    expect(proteinTransformMap({})).toEqual({})
    expect(proteinTransformMap({ proteins: [{ attachment_id: 'a', transform: [1, 2, 3] }] })).toEqual({})
    expect(proteinTransformMap({ proteins: [{ transform: Array(16).fill(0) }] })).toEqual({})
  })
})
