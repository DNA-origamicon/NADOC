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
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', undefined, { stride: undefined })
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
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', sig, { stride: undefined })
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', sig)
  })

  it('tolerates a bare call and never forwards align (the /md/ routes have no align param)', () => {
    const api = { getMdTrajectory: vi.fn(), getMdRmsf: vi.fn() }
    const a = mdVizApiAdapter(api)
    a.getOxdnaTrajectory('J1')
    a.getOxdnaRmsf('J2', { align: false })
    expect(api.getMdTrajectory).toHaveBeenCalledWith('J1', undefined, { stride: undefined })
    // align is dropped, not smuggled into the signal slot — md_trajectory.py always aligns.
    expect(api.getMdRmsf).toHaveBeenCalledWith('J2', undefined)
  })

  it('maps the per-frame heavy reps, dropping the oxDNA-only align/scope', () => {
    // Leaving these unmapped is what made a ball-and-stick / VDW switch during
    // "View trajectory" show the design's native positions: no fetcher to call.
    const api = { getMdFramesAtomistic: vi.fn(), getMdFramesSurface: vi.fn() }
    const a = mdVizApiAdapter(api)
    a.getOxdnaFramesAtomistic('J1', [3], true, 'lineage', 20)
    expect(api.getMdFramesAtomistic).toHaveBeenCalledWith('J1', [3], { stride: 20, positionsOnly: true })
    a.getOxdnaFramesSurface('J1', [3], { stride: 20, probe_radius: 0.3 }, true, 'lineage')
    expect(api.getMdFramesSurface).toHaveBeenCalledWith('J1', [3], { stride: 20, probe_radius: 0.3 })
  })

  it('still does NOT expose the FLEXIBILITY-map heavy reps (they fail closed)', () => {
    // Those colour a mean structure by per-atom RMSF and need their own MD mapping;
    // the per-frame trajectory reps above are a different payload entirely.
    const a = mdVizApiAdapter({})
    expect(a.getOxdnaRmsfAtomistic).toBeUndefined()
    expect(a.getOxdnaRmsfSurface).toBeUndefined()
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

    it('carries the frame INTERVAL through to getMdTrajectory', async () => {
      // Same seam, same failure mode as the align/signal regression above: the panel's
      // interval is only real if it survives controller → adapter → client.  Drive it
      // through the actual controller, not a remembered call shape.
      const api = { getMdTrajectory: vi.fn(async () => ({ ready: false })) }
      const ctrl = initOxdnaDisplay({ designRenderer: renderer(), api: mdVizApiAdapter(api) })
      await ctrl.loadTrajectory('J1', true, 'lineage', 20)
      const [, , opts] = api.getMdTrajectory.mock.calls[0]
      expect(opts).toEqual({ stride: 20 })
    })

    // ── The atomistic bug: NAMD frames never reached the renderer ──────────────
    //
    // Switching to a ball-and-stick / VDW rep while scrubbing a NAMD trajectory left
    // the atoms at the DESIGN's native positions: the adapter mapped no heavy fetcher,
    // so the controller called `undefined` and the catch swallowed it.
    //
    // The fix routes MD down the SAME shape oxDNA already uses — atom identity fetched
    // ONCE as a topology, then coordinates only per frame. That is what makes holding a
    // whole all-atom trajectory possible: ~5 MB of coordinates per frame instead of
    // ~72 MB of JavaScript atom objects.
    const TRAJ = (n = 4) => ({
      ready: true, n_frames: n, keys: [['h', 0, 'F']],
      frames: Array.from({ length: n }, () => [0, 0, 0, 0, 0, 1]),
      markers: [], stages: [{ name: 's', n_frames: n }],
    })
    const MODEL = {
      atoms: [{ serial: 0, element: 'P', strand_id: 'A', helix_id: 'h', bp_index: 0, direction: 'F', x: 0, y: 0, z: 0 }],
      bonds: [], n_serials: 1,
    }
    const heavyApi = (over = {}) => ({
      getMdTrajectory: vi.fn(async () => TRAJ()),
      getMdAtomisticModel: vi.fn(async () => MODEL),
      getMdFramesAtomistic: vi.fn(async (id, idxs) =>
        Object.fromEntries(idxs.map(i => [String(i), [i, i, i]]))),
      ...over,
    })
    const heavyCtrl = (api, ar) => initOxdnaDisplay({
      designRenderer: renderer(), api: mdVizApiAdapter(api),
      getAtomisticRenderer: () => ar, getCurrentRepr: () => 'ballstick',
    })
    const AR = () => ({
      getMode: () => 'ballstick', update: vi.fn(),
      applyPositionLerp: vi.fn(), clearScalarColors: vi.fn(),
    })

    it('paints the frame\'s coordinates instead of leaving design positions', async () => {
      const api = heavyApi(); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 20)
      await new Promise(r => setTimeout(r, 0))
      expect(api.getMdAtomisticModel).toHaveBeenCalledWith('J1')   // topology ONCE
      expect(api.getMdFramesAtomistic).toHaveBeenCalled()
      expect(ar.applyPositionLerp).toHaveBeenCalled()              // coordinates painted
    })

    it('asks for coordinates only — atom objects per frame are what blew the memory budget', async () => {
      const api = heavyApi(); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 20)
      await new Promise(r => setTimeout(r, 0))
      expect(api.getMdFramesAtomistic.mock.calls[0][2]).toEqual({ stride: 20, positionsOnly: true })
    })

    it('repeats the frame INTERVAL on the heavy fetch, so atoms and beads agree', async () => {
      // A composite index only addresses the same frame within one interval. Dropping
      // the stride would put the atoms at a different point in the run than the beads.
      const api = heavyApi(); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 7)
      await new Promise(r => setTimeout(r, 0))
      expect(api.getMdFramesAtomistic.mock.calls[0][2].stride).toBe(7)
    })

    it('prebuilds EVERY frame in ONE batched request, not one request per frame', async () => {
      // The whole point of the prebuild: the MD context build is paid per CALL, so N
      // separate fetches paid it N times and each scrub target stalled again.
      const api = heavyApi(); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 20)
      await new Promise(r => setTimeout(r, 0))
      api.getMdFramesAtomistic.mockClear()
      const r = await ctrl.prebuildHeavy(() => {})
      expect(r.ok).toBe(true)
      expect(r.frames).toBe(4)                       // every trajectory frame, not a 12-cell grid
      expect(api.getMdFramesAtomistic).toHaveBeenCalledTimes(1)
      expect(api.getMdFramesAtomistic.mock.calls[0][1].length).toBeGreaterThan(1)
    })

    it('builds the frames nearest the PLAYHEAD first, so a seek is served first', async () => {
      // The "buffer from here" behaviour: with a fixed ~30 s cost per request, the frames
      // the user is actually looking at have to be in the FIRST batch, not wherever they
      // happen to fall in index order.
      const api = heavyApi({
        getMdTrajectory: vi.fn(async () => TRAJ(80)),          // > one chunk
      }); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 1)
      await new Promise(r => setTimeout(r, 0))
      ctrl.showFrame(70)                                       // seek near the end
      await new Promise(r => setTimeout(r, 0))
      api.getMdFramesAtomistic.mockClear()
      await ctrl.prebuildHeavy(() => {})
      const first = api.getMdFramesAtomistic.mock.calls[0][1]
      const meanDist = first.reduce((a, i) => a + Math.abs(i - 70), 0) / first.length
      const allIdx = api.getMdFramesAtomistic.mock.calls.flatMap(c => c[1])
      const meanAll = allIdx.reduce((a, i) => a + Math.abs(i - 70), 0) / allIdx.length
      expect(meanDist, 'first batch clusters on the playhead').toBeLessThan(meanAll)
      // 70 itself is absent because the seek already cached it — the batch is the frames
      // AROUND it, nearest-first, which is exactly the buffer-ahead behaviour wanted.
      expect(first).not.toContain(70)
      expect(first.slice(0, 4).sort((a, b) => a - b)).toEqual([68, 69, 71, 72])
    })

    it('a prebuilt frame is served from cache — scrubbing must not refetch', async () => {
      const api = heavyApi(); const ar = AR()
      const ctrl = heavyCtrl(api, ar)
      await ctrl.loadTrajectory('J1', true, 'lineage', 20)
      await ctrl.prebuildHeavy(() => {})
      await new Promise(r => setTimeout(r, 0))
      api.getMdFramesAtomistic.mockClear()
      ctrl.showFrame(3)
      await new Promise(r => setTimeout(r, 0))
      expect(api.getMdFramesAtomistic).not.toHaveBeenCalled()
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
