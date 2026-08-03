import { describe, it, expect, vi } from 'vitest'
import { trajectoryJobs, keyframeTrajSpec, initTrajectoryKeyframes } from './trajectory_keyframes.js'

/** A stand-in for ui/oxdna_display.js's controller — only the surface this module uses. */
function makeCtrl({ jobId = null, mode = null, active = false, nFrames = 100, frame = 1,
                    scope = 'lineage', stride = undefined } = {}) {
  const c = {
    _job: jobId, _mode: mode, _active: active, _frames: nFrames,
    _scope: scope, _stride: stride,
    shown: [], prebuilds: [], loads: [], loadArgs: [], restored: 0, stopped: 0, playing: null,
    isActive:     () => c._active,
    activeJobId:  () => c._job,
    mode:         () => c._mode,
    trajectoryInfo: () => (c._mode === 'trajectory'
      ? { frame, total: c._frames, atomSerials: 1000, nNucleotides: 50 }
      : null),
    loadTrajectory: vi.fn(async (id, _align, sc, st) => {
      c.loads.push(id); c.loadArgs.push({ id, scope: sc, stride: st })
      c._job = id; c._mode = 'trajectory'; c._active = true
      c._scope = sc; c._stride = st
      return { ok: true, n_frames: c._frames, markers: [] }
    }),
    trajSpec: () => ({ scope: c._scope, stride: c._stride }),
    trajSpecMatches: (spec = {}) => {
      const norm = (v) => (v == null ? null : v)
      if ('scope'  in spec && norm(spec.scope)  !== norm(c._scope))  return false
      if ('stride' in spec && norm(spec.stride) !== norm(c._stride)) return false
      return true
    },
    prebuildHeavy: vi.fn(async (onProgress, opts) => {
      c.prebuilds.push(opts)
      onProgress?.(1, 2); onProgress?.(2, 2)
      return { ok: true, n: 2 }
    }),
    showFrame:  vi.fn((i) => c.shown.push(i)),
    setPlaying: vi.fn((on) => { c.playing = on }),
    releaseHeavyToDesign: vi.fn(() => { c.restored++ }),
    // Restores the design display but keeps _traj/_jobId/_mode — the real contract.
    suspendToDesign: vi.fn(() => { c.suspended++; c._active = false }),
    resumeTrajectory: vi.fn((id, spec = null) => {
      if (c._active || c._mode !== 'trajectory' || c._job !== id) return false
      if (spec && !c.trajSpecMatches(spec)) return false
      c._active = true; c.resumed++; return true
    }),
    stopAndRestore: vi.fn(() => { c.stopped++; c._active = false; c._mode = null; c._job = null }),
    cancelPendingLoad: vi.fn(),
  }
  c.suspended = 0; c.resumed = 0
  return c
}

const anim = (...kfs) => ({ keyframes: kfs })
const trajKf = (jobId, engine = 'oxdna', extra = {}) =>
  ({ trajectory_job_id: jobId, trajectory_engine: engine, ...extra })
/** The default the UI now writes on every new oxDNA trajectory keyframe. */
const fullKf = (jobId) => trajKf(jobId, 'oxdna', { trajectory_scope: 'job' })

describe('trajectoryJobs', () => {
  it('collects each referenced job once, in keyframe order', () => {
    const jobs = trajectoryJobs(anim(trajKf('A'), {}, trajKf('B', 'namd'), trajKf('A')))
    expect([...jobs.keys()]).toEqual(['A', 'B'])
    expect(jobs.get('A').engine).toBe('oxdna')
    expect(jobs.get('B').engine).toBe('namd')
  })

  it('defaults a missing engine to oxdna and ignores non-trajectory keyframes', () => {
    const jobs = trajectoryJobs(anim({ trajectory_job_id: 'A' }, { camera_pose_id: 'p' }))
    expect([...jobs.keys()]).toEqual(['A'])
    expect(jobs.get('A')).toEqual({ engine: 'oxdna', scope: 'lineage', stride: undefined })
  })

  it('is empty for a null animation or one with no keyframes', () => {
    expect(trajectoryJobs(null).size).toBe(0)
    expect(trajectoryJobs({}).size).toBe(0)
  })

  it('carries each job\u2019s authored resolution, first keyframe wins', () => {
    const jobs = trajectoryJobs(anim(fullKf('A'), trajKf('A', 'oxdna', { trajectory_scope: 'lineage' })))
    expect(jobs.get('A').scope).toBe('job')
  })
})

describe('keyframeTrajSpec', () => {
  it('reads the oxDNA full-job scope off the keyframe', () => {
    expect(keyframeTrajSpec(fullKf('A')))
      .toEqual({ engine: 'oxdna', scope: 'job', stride: undefined })
  })

  it('leaves a keyframe saved before the field existed on the sparse lineage view', () => {
    // Its saved trajectory_frame_start/end index the ~200-frame space; silently
    // promoting it to full scope would point them at other frames.
    expect(keyframeTrajSpec(trajKf('A')).scope).toBe('lineage')
  })

  it('reads a NAMD frame interval, ignoring the oxDNA-only scope', () => {
    expect(keyframeTrajSpec(trajKf('A', 'namd', { trajectory_stride: 1 })))
      .toEqual({ engine: 'namd', scope: 'lineage', stride: 1 })
  })

  it('treats a zero / negative / absent NAMD stride as the backend default', () => {
    expect(keyframeTrajSpec(trajKf('A', 'namd')).stride).toBeUndefined()
    expect(keyframeTrajSpec(trajKf('A', 'namd', { trajectory_stride: 0 })).stride).toBeUndefined()
    expect(keyframeTrajSpec(trajKf('A', 'namd', { trajectory_stride: -4 })).stride).toBeUndefined()
  })
})

describe('initTrajectoryKeyframes.prepare', () => {
  it('loads the job into its engine controller and reports its frame count', async () => {
    const ox = makeCtrl({ nFrames: 42 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    expect(ox.loads).toEqual(['A'])
    expect(tk.frameCount('A')).toBe(42)
  })

  it('does NOT reload a job the controller is already showing — the shared-cache win', async () => {
    const ox = makeCtrl({ jobId: 'A', mode: 'trajectory', active: true, nFrames: 77 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    expect(ox.loadTrajectory).not.toHaveBeenCalled()
    expect(tk.frameCount('A')).toBe(77)          // taken from the controller it already holds
  })

  it('routes each engine to its own controller, so two engines both stay loaded', async () => {
    const ox = makeCtrl(), md = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: (e) => (e === 'namd' ? md : ox) })
    await tk.prepare(anim(trajKf('A'), trajKf('B', 'namd')))
    expect(ox.loads).toEqual(['A'])
    expect(md.loads).toEqual(['B'])
  })

  it('loads only the FIRST job per controller — one controller holds one job', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A'), trajKf('B')))
    expect(ox.loads).toEqual(['A'])
  })

  it('asks for the FULL per-job trajectory when the keyframe says so', async () => {
    // The bug this fixes: the animation path passed no scope at all, so every keyframe
    // silently got the whole-lineage view strided down to ~200 frames, however many
    // frames the job's own production runs actually wrote.
    const ox = makeCtrl({ nFrames: 12000 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(fullKf('A')))
    expect(ox.loadArgs).toEqual([{ id: 'A', scope: 'job', stride: undefined }])
    expect(tk.frameCount('A')).toBe(12000)
  })

  it('forwards a NAMD keyframe\u2019s frame interval', async () => {
    const md = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => md })
    await tk.prepare(anim(trajKf('B', 'namd', { trajectory_stride: 1 })))
    expect(md.loadArgs).toEqual([{ id: 'B', scope: 'lineage', stride: 1 }])
  })

  it('RELOADS a job the controller holds at a different resolution', async () => {
    // The panel left this job showing at ~200 lineage frames; the keyframe indexes the
    // full 12 000. Reusing it would make every authored frame number address the wrong
    // instant, so the shared-cache shortcut must decline here.
    const ox = makeCtrl({ jobId: 'A', mode: 'trajectory', active: true, scope: 'lineage' })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(fullKf('A')))
    expect(ox.loadArgs).toEqual([{ id: 'A', scope: 'job', stride: undefined }])
  })

  it('reuses a held job when the resolution DOES match', async () => {
    const ox = makeCtrl({ jobId: 'A', mode: 'trajectory', active: true, scope: 'job', nFrames: 12000 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(fullKf('A')))
    expect(ox.loadTrajectory).not.toHaveBeenCalled()
    expect(tk.frameCount('A')).toBe(12000)
  })

  it('declines to RESUME a suspended trajectory held at another resolution', async () => {
    const ox = makeCtrl({ active: false, mode: 'trajectory', jobId: 'A', scope: 'lineage' })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(fullKf('A')))
    expect(ox.resumed).toBe(0)
    expect(ox.loadArgs).toEqual([{ id: 'A', scope: 'job', stride: undefined }])
  })

  it('passes the memory budget to prebuildHeavy instead of a fixed frame cap', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({
      getController: () => ox,
      planPrebuild: async () => ({ budgetBytes: 12345 }),
    })
    await tk.prepare(anim(trajKf('A')))
    expect(ox.prebuilds).toEqual([{ budgetBytes: 12345 }])
  })

  it('prebuilds with a null budget when no planner is injected', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    expect(ox.prebuilds).toEqual([{ budgetBytes: null }])
  })

  it('reports load then per-frame progress', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    const seen = []
    await tk.prepare(anim(trajKf('A')), { onProgress: (p) => seen.push(p) })
    expect(seen.map(p => p.phase)).toEqual(['load', 'frames', 'frames'])
    expect(seen[2]).toMatchObject({ done: 2, total: 2, jobId: 'A' })
  })

  it('records zero frames when the load fails, so the segment is skipped not crashed', async () => {
    const ox = makeCtrl()
    ox.loadTrajectory = vi.fn(async () => ({ ok: false, reason: 'no trajectory yet' }))
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    expect(tk.frameCount('A')).toBe(0)
    expect(ox.prebuildHeavy).not.toHaveBeenCalled()
  })

  it('survives a missing controller for an engine', async () => {
    const tk = initTrajectoryKeyframes({ getController: () => null })
    await tk.prepare(anim(trajKf('A')))
    expect(tk.frameCount('A')).toBe(0)
  })
})

describe('initTrajectoryKeyframes.show', () => {
  const prepared = async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    ox.shown.length = 0
    return { ox, tk }
  }

  it('applies a frame once and skips the repeat — the per-rAF guard', async () => {
    const { ox, tk } = await prepared()
    tk.show('A', 'oxdna', 7)
    tk.show('A', 'oxdna', 7)
    tk.show('A', 'oxdna', 7)
    expect(ox.shown).toEqual([7])
  })

  it('applies every frame that actually changes', async () => {
    const { ox, tk } = await prepared()
    tk.show('A', 'oxdna', 1); tk.show('A', 'oxdna', 2); tk.show('A', 'oxdna', 1)
    expect(ox.shown).toEqual([1, 2, 1])
  })

  it('re-applies the same index after invalidate()', async () => {
    const { ox, tk } = await prepared()
    tk.show('A', 'oxdna', 4)
    tk.invalidate()
    tk.show('A', 'oxdna', 4)
    expect(ox.shown).toEqual([4, 4])
  })

  it('does not show a job its controller does not hold — it swaps instead', async () => {
    const { ox, tk } = await prepared()
    tk.show('B', 'oxdna', 3)
    expect(ox.shown).toEqual([])
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
    expect(ox.loads).toEqual(['A', 'B'])
  })
})

describe('initTrajectoryKeyframes.suspend', () => {
  it('hands the heavy rep back to the design and forces the next frame to re-apply', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.show('A', 'oxdna', 5)
    ox.shown.length = 0
    tk.suspend()
    expect(ox.restored).toBe(1)
    tk.show('A', 'oxdna', 5)
    expect(ox.shown).toEqual([5])       // re-applied despite the unchanged index
  })

  it('is a no-op when no trajectory frame is showing', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.suspend()
    expect(ox.restored).toBe(0)
  })
})

describe('initTrajectoryKeyframes.release', () => {
  it('restores the design but KEEPS the trajectory when nothing was displayed before', async () => {
    const ox = makeCtrl({ active: false })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.release()
    expect(ox.suspended).toBe(1)
    expect(ox.stopped).toBe(0)          // NOT torn down — that would drop every cached frame
    expect(ox.playing).toBe(false)
  })

  it('falls back to a full teardown on a controller without suspendToDesign', async () => {
    const ox = makeCtrl({ active: false })
    delete ox.suspendToDesign
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.release()
    expect(ox.stopped).toBe(1)
  })

  it('a second play RESUMES the suspended trajectory instead of re-downloading it', async () => {
    const ox = makeCtrl({ active: false, nFrames: 199 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.release()
    expect(ox.loads).toEqual(['A'])

    await tk.prepare(anim(trajKf('A')))       // press Play again
    expect(ox.loads).toEqual(['A'])           // ← no second download
    expect(ox.resumed).toBe(1)
    expect(tk.frameCount('A')).toBe(199)
  })

  it('still downloads when the controller holds a DIFFERENT job', async () => {
    const ox = makeCtrl({ active: false })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.release()
    await tk.prepare(anim(trajKf('B')))
    expect(ox.loads).toEqual(['A', 'B'])
    expect(ox.resumed).toBe(0)
  })

  it("puts the panel's own frame back when it was already scrubbing that job", async () => {
    const ox = makeCtrl({ jobId: 'A', mode: 'trajectory', active: true, frame: 12 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.show('A', 'oxdna', 3)
    ox.shown.length = 0
    tk.release()
    expect(ox.stopped).toBe(0)
    expect(ox.shown).toEqual([11])       // trajectoryInfo().frame is 1-based, showFrame is 0-based
  })

  it("restores the design when it replaced a DIFFERENT job's view", async () => {
    const ox = makeCtrl({ jobId: 'Z', mode: 'trajectory', active: true })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.release()
    expect(ox.stopped).toBe(1)
  })

  it('forgets its state, so a second animation prepares from scratch', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    expect(tk.hasJobs()).toBe(true)
    tk.release()
    expect(tk.hasJobs()).toBe(false)
    expect(tk.frameCount('A')).toBe(0)
  })
})

describe('initTrajectoryKeyframes.cancel / setPlaying', () => {
  it('cancel stops the prebuild and aborts an in-flight download', async () => {
    const ox = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.prepare(anim(trajKf('A')))
    tk.cancel()
    expect(ox.setPlaying).toHaveBeenCalledWith(false)
    expect(ox.cancelPendingLoad).toHaveBeenCalled()
  })

  it('setPlaying reaches every touched controller', async () => {
    const ox = makeCtrl(), md = makeCtrl()
    const tk = initTrajectoryKeyframes({ getController: (e) => (e === 'namd' ? md : ox) })
    await tk.prepare(anim(trajKf('A'), trajKf('B', 'namd')))
    tk.setPlaying(true)
    expect(ox.playing).toBe(true)
    expect(md.playing).toBe(true)
  })
})

describe('initTrajectoryKeyframes preview', () => {
  const spec = { engine: 'oxdna', scope: 'job', stride: undefined }

  it('loads at the keyframe resolution and reports the frame count', async () => {
    const ox = makeCtrl({ nFrames: 8400 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    expect(await tk.previewLoad('A', spec)).toBe(8400)
    expect(ox.loadArgs).toEqual([{ id: 'A', scope: 'job', stride: undefined }])
    expect(tk.isPreviewing()).toBe(true)
  })

  it('costs nothing when the Simulations panel already holds that job at that resolution', async () => {
    const ox = makeCtrl({ jobId: 'A', mode: 'trajectory', active: true, scope: 'job', nFrames: 900 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    expect(await tk.previewLoad('A', spec)).toBe(900)
    expect(ox.loadTrajectory).not.toHaveBeenCalled()
  })

  it('scrubs the controller, skipping a frame that is already on screen', async () => {
    const ox = makeCtrl({ nFrames: 500 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.previewLoad('A', spec)
    ox.shown.length = 0
    tk.previewShow('A', 'oxdna', 120)
    tk.previewShow('A', 'oxdna', 120)
    tk.previewShow('A', 'oxdna', 121)
    expect(ox.shown).toEqual([120, 121])
  })

  it('reports 0 and stays clear when there is no controller for the engine', async () => {
    const tk = initTrajectoryKeyframes({ getController: () => null })
    expect(await tk.previewLoad('A', spec)).toBe(0)
    expect(tk.isPreviewing()).toBe(false)
  })

  it('release() hands the display back and leaves the trajectory cached for Play', async () => {
    const ox = makeCtrl({ active: false, nFrames: 300 })
    const tk = initTrajectoryKeyframes({ getController: () => ox })
    await tk.previewLoad('A', spec)
    tk.release()
    expect(ox.suspended).toBe(1)
    expect(ox.stopped).toBe(0)
    expect(tk.isPreviewing()).toBe(false)

    await tk.prepare(anim(fullKf('A')))   // the user now presses Play
    expect(ox.loads).toEqual(['A'])       // ← still one download
    expect(ox.resumed).toBe(1)
  })
})
