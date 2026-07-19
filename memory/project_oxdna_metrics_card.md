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
- `frontend/src/ui/metrics_card.js` — **the shared engine-agnostic factory** `initMetricsCard(
  {idPrefix, api:{start,poll}, getSelectedJob, getJobs})`: scope state, per-metric Generate→poll→cache
  (keyed by scope), Display→popup, Export→modal→downloads. `_activeJobId` = selected job else newest.
  `oxdna_metrics_card.js` is now a thin wrapper binding `idPrefix:'oxdna-metrics'` +
  `startOxdnaMetrics`/`getOxdnaMetricsRun`.
- `frontend/src/api/client.js` — `startOxdnaMetrics(id,body)` + `getOxdnaMetricsRun(runId)`
  (NOTE the pre-existing `getOxdnaMetrics` = different metrics.jsonl route; don't confuse).

## MD (NAMD) twin (shipped 2026-07-03)
Same card for NAMD jobs (goal: compare oxDNA vs NAMD twist/curvature/pairing). Reuses ALL the
pure graph/popup/export modules + the shared `initMetricsCard`; only the endpoints, ids, and the
base-pairing metric differ.
- **Backend** `backend/core/md_trajectory.py`: `md_metric_series(psf, segments, ref, design,
  analytic, *, n_slices, on_frame)` — MD analogue of `production_metric_series`, ONE DCD pass.
  Twist/curvature REUSE the engine-agnostic `oxdna_health` bundle measures verbatim (fed
  `_extract_md_nadoc_frame` P positions per (helix,bp,dir)). **Base pairing = native C1'…C1'
  fraction** (designed FWD/REV within `MD_BP_CUTOFF_NM=1.2 nm` = md_health `C1_PAIRED_MAX_DEFAULT`
  12 Å), NOT the oxDNA base-site distance — so pairing curves are comparable in TREND but not
  absolute cutoff (per `feedback_wc_calibration`: C1' is the MD primary metric). `_extract_md_nadoc_frame`
  gained `with_c1p=True` → returns aligned C1' (P + rotated P→C1', free — already computed for the
  base normal). `count_md_frames(segments)` sizes the ETA (DCD headers).
- `backend/api/routes_md_metrics.py` — mirrors `routes_oxdna_metrics` (daemon-thread registry +
  `on_frame` ETA): `POST /md/jobs/{id}/metrics/start` → `{metrics_id}`; `GET /md/metrics/{run_id}`.
  Loads inputs via `routes_md._md_segment_dcds`/`_md_snapshot_design`. Snapshot resolution **walks up
  `parent_job_id`** to the nearest ancestor with a `design.json` — a production/ensemble child runs the
  parent's PSF/PDB so it inherits the parent's topology (else metrics fail with a misleading "no NAMD
  trajectory" when the design isn't loaded). Active-design fallback only if the whole lineage lacks a
  snapshot. `_job_inputs` returns a **str reason** on failure (missing-snapshot ≠ missing-trajectory) so
  the card names the real cause. Write side: `md_ensemble.build_replica_package` copies the parent's
  design.json into the child (mirrors oxDNA child spawn). `chain` scope = refit lineage via
  `_md_job_chain`. Registered in main.py.
- **Frontend**: `md_metrics_card.js` (thin wrapper, `idPrefix:'md-metrics'` + `startMdMetrics`/
  `getMdMetricsRun`); `#md-metrics-card` in index.html AFTER the MD viz card; wired from
  `initMdJobsPanel` (`_metricsCard`, refreshed on `nadoc:design-changed`). Tests:
  `tests/test_md_metrics.py` (faked reader — one-pass all-metrics, C1' pairing drop, chain resolver,
  404, count); vitest `md_metrics_card.test.js` (3, mirrors oxDNA). NOT yet run on a real NAMD DCD.

## System monitor sub-section — live CPU/GPU/RAM sparklines (shipped 2026-07-18)
A **"System monitor"** collapsible sits at the TOP of the card body in ALL FOUR engine
cards (oxDNA, NAMD, CanDo, SNUPI). Toggle it open → three minigraphs (CPU / GPU / RAM
utilisation, 0–100%) that poll a whole-machine snapshot ~every 1.5 s and buffer it
client-side into rolling sparklines. **Live-only** (nothing persisted), **whole-machine**,
**local host** (RunPod-remote deferred) — user-chosen scope. Purely display-layer.
- Backend: `backend/core/system_resources.py` — pure `build_resource_sample(cpu_pct,
  ram_total, ram_avail, gpu_activity)` + thin `sample_system_resources()` (psutil for
  CPU%/RAM, reuses `md_vram.detect_gpu_activity` for GPU util+VRAM; GPU fields None on a
  CPU-only box). Route `GET /system/resources` in `backend/api/routes_system.py`
  (registered in main.py). Pins: `tests/test_system_resources.py`.
- Frontend: `frontend/src/ui/sparkline.js` (pure `sparklinePath` + `drawSparkline` — a
  bare no-axis minigraph, deliberately NOT metric_graph.js's full chart) and
  `frontend/src/ui/resource_monitor.js` (factory `initResourceMonitor({idPrefix, poll})`
  — owns timer + 3 ring buffers, polls ONLY while its toggle is open AND the tab is
  visible). Client: `getSystemResources()`. Wired from `initMetricsCard` (covers
  oxDNA+NAMD) + `initCandoMetricsCard` + `initSnupiMetricsCard`; **main.js LOC-Δ = 0**.
  Pins: `sparkline.test.js`, `resource_monitor.test.js`. Gotcha: `poll` is resolved
  LAZILY inside the tick (not in the default param) so partial-mock client.js tests don't
  trip on the added export. Live visual = [[manual_validation_debt]] **MV-SYSMON** (smoke
  blocked by a running NAMD job).

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
