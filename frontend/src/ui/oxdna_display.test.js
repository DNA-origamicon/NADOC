import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, viridisHex, rmsfColorMap, framesToUpdates, initOxdnaDisplay, repKind } from './oxdna_display.js'

const tick = () => new Promise((r) => setTimeout(r, 0))

describe('framesToUpdates', () => {
  it('zips the shared key list with a flat frame into applyFemPositions updates', () => {
    const keys = [['h0', 0, 'FORWARD'], ['h0', 0, 'REVERSE']]
    const frame = [1, 2, 3, 1, 0, 0,  4, 5, 6, 0, 1, 0]
    expect(framesToUpdates(keys, frame)).toEqual([
      { helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 2, 3], nx: 1, ny: 0, nz: 0 },
      { helix_id: 'h0', bp_index: 0, direction: 'REVERSE', backbone_position: [4, 5, 6], nx: 0, ny: 1, nz: 0 },
    ])
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
      { helix_id: 'h0', bp_index: 3, direction: 'FORWARD',
        backbone_position: [1, 2, 3], nx: 0.1, ny: 0.2, nz: 0.3 },
    ])
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
})

describe('initOxdnaDisplay controller', () => {
  function makeDeps(displayResp) {
    const designRenderer = { applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn() }
    const api = { getOxdnaDisplay: vi.fn().mockResolvedValue(displayResp) }
    return { designRenderer, api }
  }

  it('applies positions and tracks active job', async () => {
    const resp = { ready: true, stage_name: '3_equil',
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD',
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

  it('does not activate when there is no relaxed frame', async () => {
    const deps = makeDeps({ ready: false, positions: [] })
    const ctrl = initOxdnaDisplay(deps)
    const r = await ctrl.displayJob('job1')
    expect(r.ok).toBe(false)
    expect(ctrl.isActive()).toBe(false)
    expect(deps.designRenderer.applyFemPositions).not.toHaveBeenCalled()
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
      [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [1, 1, 1], nx: 1, ny: 0, nz: 0 }])
    ctrl.showFrame(1)
    expect(designRenderer.applyFemPositions).toHaveBeenLastCalledWith(
      [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [2, 2, 2], nx: 1, ny: 0, nz: 0 }])
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
    const atom = { getMode: () => 'ballstick', applyPositionLerp: vi.fn(), update: vi.fn() }
    const surf = { getMode: () => (state.repr === 'surface' ? 'on' : 'off'), applyPositionLerp: vi.fn() }
    const onRestoreDesignHeavy = vi.fn()
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
      getOxdnaTrajectory: vi.fn().mockResolvedValue({ ready: true, n_frames: 5, keys: [['h0', 0, 'FORWARD']],
        frames: [[0, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0], [2, 0, 0, 1, 0, 0], [3, 0, 0, 1, 0, 0], [4, 0, 0, 1, 0, 0]] }),
      getOxdnaFramesAtomistic: vi.fn().mockImplementation((id, idxs) =>
        Promise.resolve(Object.fromEntries(idxs.map((i) => [String(i), [i, i, i]])))),
      getOxdnaFramesSurface: vi.fn().mockImplementation((id, idxs) =>
        Promise.resolve(Object.fromEntries(idxs.map((i) => [String(i), { vertices: [i, i, i], faces: [0, 1, 2] }])))),
    }
    const ctrl = initOxdnaDisplay({
      designRenderer, api, atom, surf, onRestoreDesignHeavy,
      getAtomisticRenderer: () => atom, getSurfaceRenderer: () => surf,
      getCurrentRepr: () => state.repr,
    })
    return { ctrl, api, atom, surf, designRenderer, onRestoreDesignHeavy, state }
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
    expect(api.getOxdnaDisplaySurface).toHaveBeenCalledWith('job1', true)
    const data = { vertices: [0, 0, 0, 1, 1, 1], faces: [0, 1, 2] }
    expect(surf.applyPositionLerp).toHaveBeenCalledWith(data, data, 0)
  })

  it('flexibility map drives the atomistic rep from the average structure', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('vdw')
    await ctrl.displayRmsf('jobF')
    await tick()
    expect(api.getOxdnaRmsfAtomistic).toHaveBeenCalledWith('jobF')
    expect(atom.applyPositionLerp).toHaveBeenCalledWith([7, 8, 9], [7, 8, 9], 0, null, [], null)
  })

  it('coarse trajectory bakes ONCE per job then snaps scrubs to the nearest baked frame', async () => {
    const { ctrl, api, atom } = makeHeavyDeps('ballstick')
    await ctrl.loadTrajectory('jobT')           // showFrame(0) fires a bake
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledTimes(1)   // one downsampled bake
    const bakedIdxs = api.getOxdnaFramesAtomistic.mock.calls[0][1]
    expect(bakedIdxs[0]).toBe(0)
    expect(bakedIdxs[bakedIdxs.length - 1]).toBe(4)               // spans the range
    atom.applyPositionLerp.mockClear()
    ctrl.showFrame(3)
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledTimes(1)   // NO refetch — served from cache
    expect(atom.applyPositionLerp).toHaveBeenCalled()
  })

  it('fine granularity reconstructs the EXACT scrubbed frame on demand', async () => {
    const { ctrl, api } = makeHeavyDeps('ballstick')
    ctrl.setGranularity('fine')
    await ctrl.loadTrajectory('jobT')
    await tick()
    api.getOxdnaFramesAtomistic.mockClear()
    ctrl.showFrame(2)
    await tick()
    expect(api.getOxdnaFramesAtomistic).toHaveBeenCalledWith('jobT', [2])
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
