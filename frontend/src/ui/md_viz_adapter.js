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
 * Scope: CG/nadoc representation (trajectory + RMSF).  Heavy reps (atomistic/surface
 * frame reconstruction colouring) differ in wire shape between oxDNA and MD and are
 * intentionally NOT mapped here — the controller's heavy path is a no-op for CG and
 * fails closed (caught) for atomistic/surface scenes, leaving them untouched.
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
  return {
    getOxdnaTrajectory: (id, { signal } = {}) => api.getMdTrajectory(id, signal),
    getOxdnaRmsf:       (id, { signal } = {}) => api.getMdRmsf(id, signal),
  }
}
