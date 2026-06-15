import { describe, it, expect, vi } from 'vitest'
import { toFemUpdates, initOxdnaDisplay } from './oxdna_display.js'

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

describe('initOxdnaDisplay controller', () => {
  function makeDeps(displayResp) {
    const designRenderer = { applyFemPositions: vi.fn() }
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
    expect(ctrl.isActive()).toBe(false)
    expect(ctrl.activeJobId()).toBe(null)
  })
})
