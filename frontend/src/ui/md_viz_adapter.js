/**
 * md_viz_adapter.js — let the oxDNA display controller drive MD-job visualization.
 *
 * `initOxdnaDisplay({ api, … })` already takes its data source as an injected `api`
 * dependency and calls it through oxDNA-named methods (getOxdnaTrajectory,
 * getOxdnaRmsf, …).  The CG (nadoc-bead) payloads — composite trajectory and the
 * per-nucleotide RMSF flexibility map — are byte-identical between the oxDNA and MD
 * backends (`md_trajectory.py` mirrors `oxdna_health`'s shapes).  So a second
 * controller instance pointed at this adapter gives NAMD jobs the same trajectory
 * scrub + flexibility map, with zero changes to the validated oxDNA controller.
 *
 * Scope: CG/nadoc beads, plus the per-frame heavy reps WHILE SCRUBBING A TRAJECTORY.
 * The heavy trajectory frames were originally left unmapped, which is why switching to
 * a ball-and-stick / VDW / surface rep during "View trajectory" showed the design's
 * native positions: the controller had no MD fetcher to call, the request threw, and
 * the catch left the heavy rep untouched at design coordinates.
 *
 * The two engines mean different things by "a heavy frame", and the difference is real,
 * not cosmetic: oxDNA reconstructs the DESIGN's atoms (flat XYZ over a per-job topology
 * template), while NAMD renders the SIMULATION's own atoms, so each frame carries its
 * own `{atoms, bonds}` set. The controller branches on that shape; nothing is faked here.
 *
 * Flexibility-map heavy reps are mapped too: NAMD supplies its own atoms at their
 * trajectory-average positions and a surface carrying per-vertex nucleotide RMSF.
 *
 * Display-state only — never writes topology.
 */
export function mdVizApiAdapter(api) {
  // The controller calls these as `(id, { align, signal })`.  Take the OPTIONS OBJECT —
  // taking `(id, signal)` here is what silently broke this adapter once: the controller's
  // `align` bound to `signal`, the real AbortSignal was dropped, and `fetch` then rejected
  // on `signal: true`.  Destructure explicitly so a shape change can't slide through again.
  //
  // `align` is intentionally NOT forwarded: /md/jobs/{id}/trajectory and /rmsf take no
  // align param — md_trajectory.py always Kabsch-aligns each frame to the design — so there
  // is nothing to pass it to.  The MD panel never asks for align=false, and if it ever
  // does, the request must be honoured server-side rather than quietly ignored here.
  //
  // `stride` (the user-set frame interval) IS forwarded — the MD route honours it.  The
  // controller's `scope` is not: that is an oxDNA-only lineage/job distinction with no MD
  // equivalent.  Anything added here must be honoured server-side or left out; silently
  // swallowing an option is how this adapter broke the last time.
  return {
    // The MD analysis rebuilds its context (PSF parse + model) once per REQUEST, not per
    // frame, so asking for many frame indices in one call is dramatically cheaper. This
    // tells the controller it may batch its prebuild; oxDNA leaves it unset and keeps
    // fetching one frame at a time, which is right for a per-frame reconstruction.
    heavyBatch: true,
    preferTrajectoryBin: true,
    getOxdnaTrajectory: (id, { signal, stride } = {}) => api.getMdTrajectory(id, signal, { stride }),
    ...(api.getMdTrajectoryBin ? {
      getOxdnaTrajectoryBin: (id, { signal, stride, onProgress } = {}) =>
        api.getMdTrajectoryBin(id, signal, { stride, onProgress }),
    } : {}),
    getOxdnaRmsf:       (id, { signal } = {}) => api.getMdRmsf(id, signal),
    getOxdnaRmsfAtomistic: (id) => api.getMdRmsfAtomistic(id),
    getOxdnaRmsfSurface: (id, params = {}) => api.getMdRmsfSurface(id, params),
    // Heavy trajectory frames. The controller calls these POSITIONALLY as
    // `(id, frameIndices, align, scope, stride)` / `(id, frameIndices, params, align,
    // scope)`. `align`/`scope` are oxDNA-only and dropped (md_trajectory.py always
    // aligns; there is no lineage/job scope for MD). `stride` is NOT optional here —
    // the indices are composite, so without it the atoms would come from a different
    // point in the run than the beads they sit on.
    // Topology ONCE + coordinates per frame, exactly like oxDNA — so the controller's
    // validated `_ensureJobAtomistic` → `applyPositionLerp` path is reused unchanged,
    // the per-frame mesh rebuild disappears, and a whole all-atom trajectory becomes
    // small enough to hold in memory (5.4 MB/frame of Float64 coords for a 300 k-atom
    // system, against ~72 MB/frame of JavaScript atom objects).
    getOxdnaAtomisticModel: (id) => api.getMdAtomisticModel(id),
    getOxdnaFramesAtomistic: (id, frameIndices, _align, _scope, stride) =>
      api.getMdFramesAtomistic(id, frameIndices, { stride, positionsOnly: true }),
    getOxdnaFramesSurface: (id, frameIndices, params = {}) =>
      api.getMdFramesSurface(id, frameIndices, params),
  }
}
