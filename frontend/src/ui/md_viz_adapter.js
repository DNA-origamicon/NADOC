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
  return {
    getOxdnaTrajectory: (id) => api.getMdTrajectory(id),
    getOxdnaRmsf:       (id) => api.getMdRmsf(id),
  }
}
