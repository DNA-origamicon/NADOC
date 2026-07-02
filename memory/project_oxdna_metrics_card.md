---
name: project_oxdna_metrics_card
description: "oxDNA \"Graphs and Metrics\" card — user-facing twist/curvature/base-pairing graphs + PNG/CSV export over a job or its parent/child lineage"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d759f99-4da3-482f-a190-713ec2efa196
---

# oxDNA "Graphs and Metrics" card (shipped 2026-07-02)

Surfaces the autorefine research readouts (exp31–35 twist/curvature profiles + the
exp34 equilibration time series) as a first-class in-app tool. See
[[project_skip_twist_selfconsistency]] / [[project_regional_autorefine]] /
[[project_skip_twist_curvature_sweep]] for the science.

Shipped + user-VALIDATED in-app 2026-07-02 (MV-20 closed).

## What it does
**Collapsible** `.ox-card` (starts collapsed; `#oxdna-metrics-toggle` header + `#oxdna-metrics-arrow`;
toggle wired inside the factory). It is the LAST card in the oxDNA Dynamics panel, with the
**Export oxDNA ZIP** button (`#oxdna-jobs-export-btn`) placed BELOW it as the section's final element.
Scope radio (**Latest job** / **All parent/child jobs**) + three metric rows — **Twist**,
**Curvature**, **Base pairing** — each with Generate/Refresh, Display, Export buttons + a per-row
loading bar with live `(done/total frames) · ~ETA`.

- **Both domains per metric**: spatial (vs position along bundle) + temporal (vs sim time).
- **Base pairing = merged** BP-health + WC-pairing (same base-site H-bond quantity in the
  CG model): fraction of designed pairs formed + designed-pair count. User decision.
- **Scope**: `latest` = one job; `chain` = whole lineage — temporal CONCATENATES end-to-end,
  spatial OVERLAYS one profile per job.
- One background pass computes ALL THREE metrics (frame reads dominate), so any Generate
  populates the whole card.

## Backend
- `backend/core/oxdna_health.py` (all pure/additive, pins in `test_oxdna_relaxation.py`):
  - `production_metric_series(design, traj_paths, ref_conf, analytic_reference, *, n_slices, on_frame)`
    — SINGLE trajectory pass (mirrors `production_twist_series` frame handling); per frame:
    twist + curvature (differential vs analytic), base-pairing fraction (`base_pair_retention`
    on the FULL map). Accumulates mean structure (spatial twist/curve profiles) + per-pair
    formed counts (spatial base-pairing). `on_frame()` fires per frame for ETA.
  - `differential_profile(sim, analytic)` — interpolate both onto a shared 0..1 axial grid,
    subtract (sim/analytic have different slab centres). Pure.
  - `base_pairing_spatial_profile(per_pair_formed_frac, mean_positions, *, n_slices)` — bin
    time-avg formed fraction by axial position (reuses `_bundle_axis_frame` slab machinery).
  - `count_trajectory_frames(path)` — streaming `t `-line count to size the ETA bar.
- `backend/api/routes_oxdna_metrics.py` — background registry (mirrors `routes_autorefine`
  `_RUNS`+daemon+poll): `POST /oxdna/jobs/{id}/metrics/start` (body `{scope,n_slices}`) →
  `{metrics_id}`; `GET /oxdna/metrics/{run_id}` → `{state,progress,eta_s,frames_done,
  frames_total,result?}`. Registered in `main.py`. Loads jobs like `get_oxdna_deviation`
  (design.json + `_stage_trajectories` + `core_reference_geometry`). Result shape:
  `{twist,curvature,base_pairing}` each `{temporal:{per_frame,boundaries[,n_designed]},
  spatial:[{job_id,points}]}` + `jobs[]`.
- `backend/core/oxdna_job.py` — `resolve_job_chain(job_id, all_jobs)` (root→all descendants,
  chronological) + `descendants_of` (extracted from the delete route's inline subtree walk;
  delete route now calls it).

## Frontend (module-first — main.js LOC-Δ = 0)
Card is a CHILD module of the oxDNA jobs panel (`initOxdnaMetricsCard` wired from
`initOxdnaJobsPanel`, passed `getSelectedJob`/`getJobs`; refreshed on `nadoc:design-changed`).
- `frontend/src/ui/metric_graph.js` — pure cores (`niceTicks`, `dataToPixel`, `buildChartSpec`,
  `metricSeries`, `metricCSVs`) + `drawChart`/`renderToDataURL` (vanilla canvas, NO chart lib —
  CSP/offline; PNG export = `toDataURL`). `METRIC_META` holds axis labels/units per metric+domain.
- `frontend/src/ui/metric_graph_popup.js` — Display popup (2 canvases spatial+temporal; `metricSpecs`
  pure builder reused for PNG export). `frontend/src/ui/metric_export_modal.js` — PNG/Data/Both
  checkbox modal + `downloadText`/`downloadHref`; pure `exportChoiceFiles`.
- `frontend/src/ui/oxdna_metrics_card.js` — factory: scope state, per-metric Generate→poll→cache
  (keyed by scope), Display→popup, Export→modal→downloads. `_activeJobId` = selected job else newest.
- `frontend/src/api/client.js` — `startOxdnaMetrics(id,body)` + `getOxdnaMetricsRun(runId)`
  (NOTE the pre-existing `getOxdnaMetrics` = different metrics.jsonl route; don't confuse).

## Tests
Backend pins (test_oxdna_relaxation.py): `production_metric_series` one-pass all-metrics,
`differential_profile`, `base_pairing_spatial_profile`, `count_trajectory_frames`,
`resolve_job_chain`/`descendants_of`, metrics route latest+chain+404. Frontend: vitest
`metric_graph.test.js` (11), `metric_export_modal.test.js`, jsdom `oxdna_metrics_card.test.js`
(Generate→poll→Display, scope re-key). E2E `oxdna_metrics_card.spec.js` (card renders +
Generate wiring; popup draws non-blank real canvases). `just test` 3627 pass (1 pre-existing
machine-specific fixture fail in test_duplex_geometry). Live graphs on REAL sim data = MV-20.

## Gotchas
- Frames-per-file read all-at-once (`read_trajectory_frames_full`) → ETA is per-file coarse +
  per-frame fine. Fine for a loading bar.
- `base_pair_retention` needs BOTH FORWARD+REVERSE at a (helix,bp); FORWARD-only synthetic
  bundles report 0 designed pairs (test fixture `_paired_bundle` adds both strands).
