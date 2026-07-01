---
name: md-viz-tools
description: MD jobs panel trajectory-scrub + flexibility-map (RMSF) tools — reuse the oxDNA display controller via an API adapter
metadata: 
  node_type: memory
  type: project
  originSessionId: 515d0592-f4a2-4e8a-8812-9d875d0bd184
---

The MD jobs panel got oxDNA-parity visualization tools (trajectory scrub + flexibility/RMSF map) to replace VMD for viewing NAMD runs. Built 2026-06-22.

**Architecture — reuse, don't reimplement.** `initOxdnaDisplay({api, ...})` is a factory that takes its data source as an injected `api` dep and calls it through oxDNA-named methods (getOxdnaTrajectory, getOxdnaRmsf, ...). The CG/nadoc-bead trajectory + RMSF payloads are byte-identical between oxDNA and MD (`md_trajectory.py` mirrors `oxdna_health`'s shapes). So a SECOND controller instance pointed at `mdVizApiAdapter(api)` (frontend/src/ui/md_viz_adapter.js — maps getOxdnaTrajectory→getMdTrajectory, getOxdnaRmsf→getMdRmsf) gives NAMD jobs the whole scrub/colour/recolor machinery with ZERO changes to the validated oxDNA controller. `mdViz` is created in main.js right after `oxdnaDisplay` (same renderer deps) and passed to initMdJobsPanel as `getMdViz`.

**Backend.** `md_rmsf()` in backend/core/md_trajectory.py pools ALL written segments (user chose "all segments" gating), Kabsch-aligns each sampled frame via the existing `_extract_md_nadoc_frame`, returns the oxDNA `/rmsf` shape. Route: `GET /md/jobs/{id}/rmsf` in routes_md.py. Trajectory endpoints (`/trajectory`, `/trajectory-meta`, `/frames-atomistic`, `/frames-surface`) already existed. RMSF default max_frames=150 (statistics fine; bounds per-frame Kabsch cost).

**Panel (md_jobs_panel.js).** flex + traj toggles/controls mirror oxdna_jobs_panel; reuse `oxdna_trajectory_player.js`. Three display modes (live "Display MD" / flexibility map / trajectory) are MUTUALLY EXCLUSIVE — each deforms the same design model, so activating one calls stopAndRestore on the others. Rows now have `data-job-id` (for the e2e + the existing md_live_no_stale spec).

**v1 scope = CG/nadoc representation only.** Deliberate follow-ons: (1) heavy-rep (atomistic/surface) RMSF colouring — the per-frame atomistic data shapes differ between oxDNA (template) and NAMD (real DCD atoms), needs its own mapping, so the adapter intentionally omits the heavy methods (controller heavy path is a no-op for CG, fails closed for atomistic/surface scenes); (2) the draggable colour-rescale widget (flex_scale.js is a single global DOM widget — sharing it between the oxDNA + MD panels needs main.js coordination); v1 flex map uses viridis colouring + a min/max legend.

**PERFORMANCE caveat (real, not yet addressed).** Trajectory load (200 frames) and RMSF (150 frames) each take ~1-2 min for a solvated system because every frame does an MDAnalysis seek + P-atom select + Kabsch SVD in Python. VMD is instant; this is the main gap for "replacing VMD". Worth optimizing (vectorize the per-frame extraction, cache the built ctx across requests, or stream). The frontend shows "Loading trajectory…" / "Computing…" meanwhile.

**Verification gotchas (cost real time).** The dev backend uses uvicorn `--reload`; editing backend files under load WEDGES it on WSL2 (the smoke config runs WITHOUT --reload for this reason). The single-worker dev backend SERIALIZES requests, so concurrent heavy trajectory/RMSF reads + a Playwright run starve each other. Headless Playwright boot can CLEAR the active design (the trajectory/RMSF routes need it via get_or_404 → 404 "no trajectory yet" is really "no design"). The stable e2e (e2e/md_viz_tools.spec.js) asserts the toggle FIRES the right endpoint (page.waitForRequest) rather than waiting for the multi-minute compute — proves DOM→handler→mdViz→adapter→endpoint without the flaky slow path. See also [[md-job-system]] and [[md-panel-implementation-status-and-algorithm-details]].
