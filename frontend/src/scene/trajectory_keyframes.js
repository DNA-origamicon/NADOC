/**
 * Trajectory keyframes — the animation player's view of a simulation trajectory.
 *
 * There used to be a SECOND trajectory pipeline inside animation_player.js: it fetched
 * /trajectory, /frames-atomistic and /frames-surface itself into private Maps that it
 * threw away on every stop. It was a bad copy of ui/oxdna_display.js —
 *
 *   - no cache across plays (every Play re-downloaded the whole trajectory and re-ran
 *     every all-atom rebuild),
 *   - fixed 40 / 20-frame caps instead of a memory budget derived from free RAM,
 *   - no topology-once fetch, so a NAMD frame shipped whole atom OBJECTS (~72 MB/frame
 *     against ~5.4 MB of coordinates) and rebuilt the atom meshes per frame,
 *   - no serialised fetch queue, so it raced the jobs panel for the same backend slot —
 *     and `md_analysis_runner` supersedes by KILLING the loser,
 *   - job coordinates applied onto the ACTIVE design's atom buffer, which mis-maps every
 *     serial if the design was edited after the job ran.
 *
 * So this module owns no fetching and no caching. It drives the same display controllers
 * the jobs panels drive (`oxdnaDisplay` for oxDNA/LAMMPS, `mdViz` for NAMD), which is
 * what makes an animation and a panel scrub share one cache, one budget, one fetch queue
 * and one job-topology rebuild.
 *
 * **One job per controller at a time.** A controller holds a single job's trajectory
 * (`loadTrajectory` drops the previous job's bakes), so `prepare` loads the FIRST job per
 * controller and a second job on the SAME engine is swapped in when its segment is
 * reached — a reload each time it comes round. Two jobs on DIFFERENT engines are free
 * (they land on different controllers). Every animation in the workspace today uses one
 * job; if multi-job on one engine ever becomes real, the fix is a per-job cache inside
 * the controller, not a second pipeline back in here.
 *
 * Display-only, like everything else on this path: the controllers write bead/atom
 * positions and never touch topology (Three-Layer Law).
 */

/**
 * Pure: the composite RESOLUTION one trajectory keyframe addresses its frame indices in.
 *
 * The two engines say this differently and neither is optional detail — a frame index
 * only means the same thing within one resolution:
 *
 *   oxDNA/LAMMPS  `scope`  'job'     = this job's own stages, EVERY frame oxDNA wrote.
 *                          'lineage' = the whole ancestor chain strided to ~200 frames.
 *   NAMD          `stride` N >= 1    = every Nth frame of each written segment.
 *                          undefined = the backend's legacy 200-frame budget.
 *
 * A keyframe saved before these fields existed carries neither, and must keep resolving
 * to the old sparse view or its saved start/end would address other frames.
 */
export function keyframeTrajSpec(kf) {
  const engine = kf?.trajectory_engine || 'oxdna'
  if (engine === 'namd') {
    const s = Math.floor(Number(kf?.trajectory_stride))
    // MD has no lineage/job scope; the adapter drops it. Pinned to 'lineage' only so
    // the spec compares equal against a controller the MD panel loaded.
    return { engine, scope: 'lineage', stride: s >= 1 ? s : undefined }
  }
  return { engine, scope: kf?.trajectory_scope === 'job' ? 'job' : 'lineage', stride: undefined }
}

/** Pure: which trajectory jobs an animation references, in keyframe order, and at what
 *  resolution. `Map<jobId, {engine, scope, stride}>` — the FIRST keyframe naming a job
 *  wins, since one controller holds one resolution of one job at a time. */
export function trajectoryJobs(animation) {
  const out = new Map()
  for (const kf of animation?.keyframes ?? []) {
    if (kf?.trajectory_job_id && !out.has(kf.trajectory_job_id)) {
      out.set(kf.trajectory_job_id, keyframeTrajSpec(kf))
    }
  }
  return out
}

/**
 * @param {object}   opts
 * @param {function(string): object|null} opts.getController  engine → display controller
 * @param {function(object): Promise<object|null>} [opts.planPrebuild]  controller → memory plan
 */
export function initTrajectoryKeyframes({ getController, planPrebuild = null } = {}) {
  // jobId → frame count of its loaded composite trajectory (0 = failed / not loaded).
  const _frames  = new Map()
  // jobId → the {engine, scope, stride} resolution it was asked for, so a mid-playback
  // swap and a preview scrub reload at the SAME resolution the frame indices assume.
  const _specs   = new Map()
  // controller → the jobId it currently holds FOR US.
  const _loaded  = new Map()
  // controller → its state before we touched it, so release() can put it back.
  const _prev    = new Map()
  // Last (job, frame) actually pushed to a controller — the frame-change guard. The old
  // player re-applied the same frame on every rAF: a full framesToUpdates rebuild plus an
  // applyFemPositions scene sweep, 60× a second, for a frame that had not moved.
  let _lastJob   = null
  let _lastFrame = -1
  let _swapping  = null

  function _remember(ctrl) {
    if (_prev.has(ctrl)) return
    _prev.set(ctrl, {
      active: !!ctrl.isActive?.(),
      jobId:  ctrl.activeJobId?.() ?? null,
      mode:   ctrl.mode?.() ?? null,
      // trajectoryInfo().frame is 1-based for display; showFrame takes a 0-based index.
      frame:  Math.max(0, (Number(ctrl.trajectoryInfo?.()?.frame) || 1) - 1),
    })
  }

  /** Load `jobId` into `ctrl` at `spec`'s resolution (skipped when it already holds that
   *  job AT THAT RESOLUTION — the whole point of sharing the panel's controller) and
   *  prebuild its heavy frames within budget. */
  async function _loadInto(ctrl, jobId, spec, onProgress) {
    const { engine, scope, stride } = spec
    _remember(ctrl)
    _specs.set(jobId, spec)
    // Reusing a held trajectory is only sound at the SAME resolution: the caller's frame
    // indices are composite indices, and 'job'/stride=1 is a different frame space from
    // the sparse lineage view. A mismatch falls through to a real load.
    const sameSpec = ctrl.trajSpecMatches ? ctrl.trajSpecMatches({ scope, stride }) : true
    // Three ways in, cheapest first: the panel (or a previous play) already has this job
    // showing; a previous play suspended it but the controller still holds every frame;
    // or it genuinely has to be downloaded.
    const showing  = sameSpec && ctrl.activeJobId?.() === jobId && ctrl.mode?.() === 'trajectory'
                     && ctrl.isActive?.()
    const resumed  = !showing && ctrl.resumeTrajectory?.(jobId, { scope, stride }) === true
    if (showing || resumed) {
      _frames.set(jobId, Number(ctrl.trajectoryInfo?.()?.total) || 0)
    } else {
      onProgress?.({ phase: 'load', jobId, engine, done: 0, total: 1 })
      const r = await Promise.resolve(
        ctrl.loadTrajectory?.(jobId, true, scope, stride)).catch(() => null)
      if (!r?.ok) { _frames.set(jobId, 0); return false }
      _frames.set(jobId, Number(r.n_frames) || 0)
    }
    _loaded.set(ctrl, jobId)
    _lastJob = null; _lastFrame = -1   // the model just moved under us

    // Heavy reps only: prebuildHeavy is a no-op in a CG representation, so a bead-rep
    // animation pays nothing here.
    if (typeof ctrl.prebuildHeavy === 'function') {
      const plan = planPrebuild
        ? await Promise.resolve(planPrebuild(ctrl)).catch(() => null)
        : null
      await Promise.resolve(ctrl.prebuildHeavy(
        (done, total) => onProgress?.({ phase: 'frames', jobId, engine, done, total }),
        { budgetBytes: plan?.budgetBytes ?? null },
      )).catch(() => null)
    }
    return true
  }

  /**
   * Load every job the animation needs (one per controller) and report progress.
   * Returns Map<jobId, nFrames> so the caller can clamp its authored frame ranges
   * against what the trajectory actually has.
   */
  async function prepare(animation, { onProgress } = {}) {
    _frames.clear()
    _specs.clear()
    const jobs = trajectoryJobs(animation)
    if (!jobs.size) return _frames
    const first = new Map()   // controller → the first job that lands on it
    for (const [jobId, spec] of jobs) {
      const ctrl = getController?.(spec.engine)
      if (!ctrl) { _frames.set(jobId, 0); continue }
      _specs.set(jobId, spec)
      if (!first.has(ctrl)) first.set(ctrl, { jobId, spec })
    }
    for (const [ctrl, { jobId, spec }] of first) {
      await _loadInto(ctrl, jobId, spec, onProgress)
    }
    return _frames
  }

  /** Frames in this job's loaded trajectory (0 = not loaded / no trajectory). */
  function frameCount(jobId) { return _frames.get(jobId) ?? 0 }

  /** True when this animation touched any trajectory job. */
  function hasJobs() { return _prev.size > 0 }

  /** Swap a second same-engine job into its controller. Async and single-flighted: the
   *  frame loop is synchronous, so playback holds the current frame until it lands. */
  function _swap(ctrl, jobId, engine) {
    if (_swapping) return
    const spec = _specs.get(jobId) ?? { engine, scope: 'lineage', stride: undefined }
    _swapping = _loadInto(ctrl, jobId, spec, null)
      .catch(() => {})
      .finally(() => { _swapping = null })
  }

  /**
   * Show frame `frameIdx` of `jobId`. No-op when that frame is already on screen —
   * the controller's showFrame does a full CG position sweep plus a heavy-rep apply,
   * which is not something to run per rAF for an unchanged frame.
   */
  function show(jobId, engine, frameIdx) {
    const ctrl = getController?.(engine)
    if (!ctrl) return
    if (_loaded.get(ctrl) !== jobId) { _swap(ctrl, jobId, engine); return }
    if (_lastJob === jobId && _lastFrame === frameIdx) return
    _lastJob = jobId; _lastFrame = frameIdx
    ctrl.showFrame?.(frameIdx)
  }

  /** Drop the frame-change guard — something other than us moved the model, so the next
   *  show() must re-apply even if the index is unchanged. */
  function invalidate() { _lastJob = null; _lastFrame = -1 }

  /**
   * Step aside for a segment that is NOT a trajectory: hand the heavy rep back to the
   * design, keeping every cached frame so the next trajectory segment is still instant.
   *
   * Needed because the controller leaves the atomistic renderer holding the JOB's atom
   * set. A feature-log keyframe then writes DESIGN coordinates over it, and if the design
   * was edited after the job ran the two atom sets don't correspond — every serial lands
   * on the wrong atom. Edge-triggered, so the common all-trajectory and no-trajectory
   * animations never pay for it.
   */
  function suspend() {
    if (_lastJob === null && _lastFrame < 0) return   // nothing of ours is showing
    invalidate()
    for (const ctrl of _loaded.keys()) ctrl.releaseHeavyToDesign?.()
  }

  /** Tell the controllers playback is running: while it is, heavy reps are forced to the
   *  pre-built coarse grid (a per-frame exact rebuild would stall the loop). */
  function setPlaying(on) {
    for (const ctrl of _prev.keys()) ctrl.setPlaying?.(!!on)
  }

  /** Abandon an in-flight prepare: aborts a trajectory download in transfer and stops a
   *  grinding prebuild. Leaves whatever landed in place — release() does the restoring. */
  function cancel() {
    for (const ctrl of _prev.keys()) {
      ctrl.setPlaying?.(false)      // bumps the controller's prebuild token
      ctrl.cancelPendingLoad?.()    // and terminates the HTTP body transfer
    }
  }

  /** Put every controller back the way the animation found it. */
  function release() {
    for (const [ctrl, prev] of _prev) {
      ctrl.setPlaying?.(false)
      if (!prev.active) {
        // Nothing was displayed before → restore the design, but KEEP the loaded
        // trajectory and its frame bakes so pressing Play again is instant.
        // stopAndRestore() would drop them and re-download the lot next time.
        if (typeof ctrl.suspendToDesign === 'function') ctrl.suspendToDesign()
        else ctrl.stopAndRestore?.()
      } else if (prev.mode === 'trajectory' && prev.jobId
                 && prev.jobId === ctrl.activeJobId?.()) {
        // The panel was already scrubbing this job → put its frame back under it.
        ctrl.showFrame?.(prev.frame)
      } else {
        // We replaced whatever the panel was showing; restoring it would mean re-running
        // its fetch. Leave the plain design instead of a half-swapped view.
        ctrl.stopAndRestore?.()
      }
    }
    _prev.clear(); _loaded.clear(); _frames.clear(); _specs.clear()
    invalidate()
  }

  // ── Authoring preview ────────────────────────────────────────────────────────
  // The animation panel's frame-range bar scrubs the model while you drag its playhead,
  // so you can SEE which frames you are bracketing instead of guessing at index numbers.
  // It goes through this module rather than touching a controller itself, so a preview
  // and a subsequent Play share the one download, the one budget and the one restore
  // path — the same reason the player does.

  /**
   * Load one keyframe's job for authoring preview. Same reuse rules as `prepare`
   * (already-showing → free; suspended-but-held → free; otherwise a real download at the
   * keyframe's own resolution). Returns the frame count, or 0 if it could not load.
   */
  async function previewLoad(jobId, spec, { onProgress } = {}) {
    const ctrl = getController?.(spec?.engine)
    if (!ctrl || !jobId) return 0
    await _loadInto(ctrl, jobId, spec, onProgress)
    return _frames.get(jobId) ?? 0
  }

  /** Scrub the preview to a composite frame index. Same frame-change guard as `show`. */
  function previewShow(jobId, engine, frameIdx) { show(jobId, engine, frameIdx) }

  /** True when this module is holding a controller for preview (nothing is playing). */
  function isPreviewing() { return _prev.size > 0 }

  return {
    prepare, frameCount, show, invalidate, suspend, setPlaying, cancel, release, hasJobs,
    previewLoad, previewShow, isPreviewing,
  }
}
