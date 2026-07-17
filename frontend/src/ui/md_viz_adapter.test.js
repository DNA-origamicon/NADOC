import { describe, it, expect, vi } from 'vitest'
import { mdVizApiAdapter } from './md_viz_adapter.js'
import { initOxdnaDisplay } from './oxdna_display.js'

describe('mdVizApiAdapter', () => {
  it('maps the oxDNA-named controller methods to the MD endpoints', () => {
    const api = {
      getMdTrajectory: vi.fn((id) => `traj:${id}`),
      getMdRmsf: vi.fn((id) => `rmsf:${id}`),
    }
    const a = mdVizApiAdapter(api)
    expect(a.getOxdnaTrajectory('J1')).toBe('traj:J1')
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', undefined)
    expect(a.getOxdnaRmsf('J2')).toBe('rmsf:J2')
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', undefined)
  })

  it('forwards an AbortSignal through to the MD endpoints', () => {
    // EXACTLY the shape oxdna_display uses: `api.getOxdnaTrajectory(id, { align, signal })`.
    // REGRESSION: the adapter used to take `(id, signal)`, so `align` bound to `signal`,
    // the real AbortSignal was dropped, and fetch rejected on `signal: true` — NAMD
    // trajectory + flexibility map were broken while this file's tests stayed green
    // because they called the adapter with the old 2-arg shape.
    const api = {
      getMdTrajectory: vi.fn((id) => `traj:${id}`),
      getMdRmsf: vi.fn((id) => `rmsf:${id}`),
    }
    const sig = new AbortController().signal
    const a = mdVizApiAdapter(api)
    a.getOxdnaTrajectory('J1', { align: true, signal: sig })
    a.getOxdnaRmsf('J2', { align: true, signal: sig })
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', sig)
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', sig)
  })

  it('tolerates a bare call and never forwards align (the /md/ routes have no align param)', () => {
    const api = { getMdTrajectory: vi.fn(), getMdRmsf: vi.fn() }
    const a = mdVizApiAdapter(api)
    a.getOxdnaTrajectory('J1')
    a.getOxdnaRmsf('J2', { align: false })
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', undefined)
    // align is dropped, not smuggled into the signal slot — md_trajectory.py always aligns.
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', undefined)
  })

  it('does NOT expose heavy-rep methods (CG-only scope — heavy fails closed)', () => {
    const a = mdVizApiAdapter({})
    expect(a.getOxdnaFramesAtomistic).toBeUndefined()
    expect(a.getOxdnaRmsfAtomistic).toBeUndefined()
  })

  // ── Contract test: the REAL controller, not a hand-written stand-in ──────────
  //
  // This is the test that was missing. Every test above pokes the adapter directly, so
  // they all kept passing while oxdna_display quietly moved from `(id, signal)` to
  // `(id, { align, signal })` — the adapter bound `align` to `signal`, dropped the real
  // AbortSignal, and fetch then rejected on `signal: true`. NAMD trajectory + flexibility
  // map were dead in the app with a green suite. Testing a seam against a REMEMBERED
  // contract proves nothing; drive it with the actual caller.
  describe('driven by the real oxdna_display controller', () => {
    const renderer = () => ({
      applyFemPositions: vi.fn(), applyScalarColors: vi.fn(), clearScalarColors: vi.fn(),
    })

    it('loadTrajectory reaches getMdTrajectory with a usable AbortSignal', async () => {
      const api = { getMdTrajectory: vi.fn(async () => ({ ready: false })) }
      const ctrl = initOxdnaDisplay({ designRenderer: renderer(), api: mdVizApiAdapter(api) })
      await ctrl.loadTrajectory('J1')
      expect(api.getMdTrajectory).toHaveBeenCalledTimes(1)
      const [id, signal] = api.getMdTrajectory.mock.calls[0]
      expect(id).toBe('J1')
      expect(signal, 'a real AbortSignal, not `true`').toBeInstanceOf(AbortSignal)
    })

    it('displayRmsf reaches getMdRmsf with a usable AbortSignal', async () => {
      const api = { getMdRmsf: vi.fn(async () => ({ ready: false, reason: 'x' })) }
      const ctrl = initOxdnaDisplay({ designRenderer: renderer(), api: mdVizApiAdapter(api) })
      await ctrl.displayRmsf('J2')
      expect(api.getMdRmsf).toHaveBeenCalledTimes(1)
      const [id, signal] = api.getMdRmsf.mock.calls[0]
      expect(id).toBe('J2')
      expect(signal, 'a real AbortSignal, not `true`').toBeInstanceOf(AbortSignal)
    })

    it('the signal the controller hands over actually aborts the in-flight MD load', async () => {
      let captured
      const api = { getMdTrajectory: vi.fn((id, signal) => { captured = signal; return new Promise(() => {}) }) }
      const ctrl = initOxdnaDisplay({ designRenderer: renderer(), api: mdVizApiAdapter(api) })
      ctrl.loadTrajectory('J3')
      expect(captured?.aborted).toBe(false)
      ctrl.cancelPendingLoad()
      expect(captured?.aborted, 'cancelling must reach the MD request').toBe(true)
    })
  })
})
