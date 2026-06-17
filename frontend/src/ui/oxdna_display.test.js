import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, viridisHex, rmsfColorMap, framesToUpdates, initOxdnaDisplay } from './oxdna_display.js'

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
      positions: [{ helix_id: 'h0', bp_index: 0, direction: 'FORWARD', backbone_position: [0, 0, 0], nx: 1, ny: 0, nz: 0, rmsf: 0.1 }],
    }) }
    const ctrl = initOxdnaDisplay({ designRenderer, api })
    const r = await ctrl.displayRmsf('jobF')
    expect(r.ok).toBe(true)
    expect(r.min).toBe(0.1)
    expect(r.max).toBe(0.9)
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
