---
name: project_blade_frontend
description: NEXT-SESSION PRIORITY. Build spec for the BLADE simulation tab (between CanDo and SNUPI) — clone recipe grounded in file:line, reusing the unified job manager + collapsible card + run/stop/delete. Read this first to resume the frontend work.
metadata:
  type: project
---

# BLADE frontend tab — build handoff (NEXT-SESSION PRIORITY)

Goal: an **in-app BLADE tab** so the user can play with BLADE without the CLI+VMD loop.
BLADE = box-free CHARMM+GBSA baseline + learned solvent correction (see
[[project_atomistic_propagator]] for the science). This session shipped the compute + a
CLI benchmark; this file is the plan to put a UI on it. **Same unified job manager, same
collapsible card, same Run/Stop/Delete** as the other engines — clone SNUPI (its closest
analog: an in-process FEM sibling of CanDo), then swap in BLADE's external compute.

## Architecture in one paragraph (verified this session)
The 5 engines (`oxdna`,`mrdna`,`cando`,`snupi`,`namd`) are NOT free-standing tabs — they are
one **Simulate** section (`#simulate-panel`, index.html:3621) with a segmented **engine
selector** that show/hides one `*-jobs-panel` at a time. Tab ORDER is a single array:
`ENGINE_KEYS` in `frontend/src/ui/engine_capabilities.js:32`. A run is a **row** in the shared
job list (not a bespoke card); Run/Stop are panel-owned DOM buttons, Delete is the one master
`#simulate-job-actions` button dispatched by `simulate_jobs.js`. Backend: each engine = a trio
(`*_job.py` model + `*_runner.py` + `routes_*.py`) + registration in `main.js`, `main.py`,
`sim_jobs.py`, `routes_simulate.py`.

## Insertion point (user's ask: "between SNUPI and CanDo")
`engine_capabilities.js:32` → `ENGINE_KEYS = ['cando','blade','snupi','mrdna','oxdna','namd']`
(add `blade:'BLADE'` to `ENGINE_LABELS`, add a `blade:` block to `ENGINE_CAPABILITIES` with
`advancedParams`). The parity test `engine_capabilities.test.js` FAILS until every card key is
present — good forcing function.

## MVP scope — do the RELAX mode first
Start with the one thing already proven end-to-end this session:
- **Relax run:** pick a loaded design → BLADE implicit relax (OpenMM, gpu micromamba env,
  detached subprocess) → cache the relaxed trajectory (solute PSF + relax DCD) → in-app
  trajectory playback (clone `snupi_display` trajectory viz). This is exactly the
  `blade relax` CLI we ran on the curved 6hb (STABLE, 72 s), surfaced in the UI.
- Defer to later modes (same tab, a `mode` knob): **seed-NAMD** (the equilibration-benchmark
  leg — relax→solvate→NAMD, heavy/RunPod), **rollout** (invariant-measure dynamics).

## FRONTEND clone recipe (file:line)
1. `engine_capabilities.js:32/34/76+` — insert `'blade'`; add label + `ENGINE_CAPABILITIES.blade`
   (cards enabled or `off('reason')`; `advancedParams:['blade-jobs-mode','blade-jobs-corr',…]`).
2. New `frontend/src/ui/blade_jobs_panel.js` (clone `snupi_jobs_panel.js`, factory
   `initBladeJobsPanel({bladeDisplay,getWorkspacePath,getSelection})→{refresh,getSelectedJob,
   selectJob,deleteSelected}`), `blade_display.js` (clone `snupi_display.js`), `blade_metrics_card.js`
   (clone `snupi_metrics_card.js`). Swap ids `snupi-*`→`blade-*`, engine `'snupi'`→`'blade'`,
   `api.*Snupi*`→`api.*Blade*`. It uses the shared `jobs_panel_base.js`/`_model.js`/`_render.js` as-is.
3. `frontend/src/api/client.js` — clone the SNUPI block (2357-2381) → `/blade/*`:
   `bladeAvailable`, `createBladeJob`, `listBladeJobs`, `getBladeJob`, `getBladeProgress`,
   `getBladeErrorLog`, `startBladeJob`, `stopBladeJob`, `deleteBladeJob`, `getBladeDisplay/Trajectory`.
4. `frontend/index.html` — clone the SNUPI panel block **4581-4830** as `#blade-jobs-panel`
   (`blade-*` ids; advanced drawer 4630-4737 → BLADE's knobs); add `<div id="blade-run-controls"
   style="display:none">` before **index.html:3649**.
5. `frontend/src/main.js` — mirror: construct (2060-2067) `bladeDisplay`+`bladePanel`; run-controls
   (2199/2211) `runControlEls.blade` + `_moveRunControls(runControlEls.blade,'blade-launch-row',
   'blade-stop-row')`; selector (2278) `panelEls.blade`; `initSimulateJobs` (2319) gets `bladePanel`.
6. `frontend/src/ui/simulate_jobs.js` — add `blade` to `_ENGINE_BADGE` (46), `_panelFor` (332),
   timeline (288), and the engine-label switches (159,345,640). `initSimulateJobs` signature (top)
   gains `bladePanel`.

## BACKEND clone recipe (file:line)
7. New `backend/core/blade_job.py` (clone `snupi_job.py`; dir `workspace/blade_jobs/{id}`,
   `BladeStatus` enum, `save`/`load` JSON, `pid` field). `backend/core/blade_runner.py`
   (clone `snupi_runner.py` public surface: `prepare_blade_job`, `start_job`, `stop_job`,
   `is_running`, `job_progress`, `reconcile_blade_status`, `load_trajectory`).
   `backend/core/blade_worker.py` (clone `snupi_worker.py`). `backend/api/routes_blade.py`
   (clone `routes_snupi.py`; `CreateBladeJobRequest` = the launch schema).
8. `backend/api/main.py` — import (mirror :72) + `include_router(blade_router, prefix="/api")` (:260).
9. `backend/core/sim_jobs.py` — `normalize_blade_job` (mirror :121); `backend/api/routes_simulate.py`
   — add the `list_blade_jobs` merge block (mirror :177) so BLADE runs join `/simulate/jobs`.
10. `backend/core/engines.py` — add `find_openmm_env`/`blade` availability probe so `/blade/available`
    + the tab's ⚠ install badge resolve. NET-NEW: no OpenMM/micromamba resolver exists yet.

## BLADE-specific gotchas (where it DIVERGES from SNUPI — read before coding)
- **External compute, detached subprocess.** SNUPI solves in-process (scipy). BLADE's compute is
  OpenMM in the **micromamba `gpu` env** (+ a NAMD leg for seed mode) → the runner must use the
  **detached-subprocess + PID-persist + reconcile** model, NOT in-process. Mirror
  `snupi_runner.start_job` (`subprocess.Popen([...],start_new_session=True)`, persist `job.pid`,
  daemon `_reap` thread) and `namd_runner.py:1013` / `oxdna_runner.py:874`
  (`oxdna_subprocess_env()` env-patch + `find_oxdna()` override→PATH). `reconcile_*_status`
  recovers orphans after a `uvicorn --reload`.
- **The worker shells into the gpu env.** The benchmark already does this:
  `GPUPY = ['/home/joshua/micromamba/envs/gpu/bin/python']` then
  `subprocess.run(GPUPY + [blade_relax.py, ideal_pdb, solute_psf, FF, out_pdb, N, traj_dcd])`.
  `blade_worker` should invoke `blade_relax` via that gpu interpreter. **blade_relax CANNOT be a
  normally-imported backend module** — openmm/parmed are NOT in the uv env; it stays a script run
  by the gpu-env python. Home it at e.g. `backend/ml/propagator/blade_relax_gpu.py`.
- **Env resolver is net-new.** Add `$BLADE_OPENMM_ENV` (micromamba prefix) override → the gpu
  interpreter path, modeled on `find_oxdna()` + `oxdna_subprocess_env()`. Put it in `engines.py`.

## REUSE — session assets already on git (commit fdcac18) or in scratchpad
- `backend/core/namd_solvate.build_namd_solvated_package(solute_coords=)` — the BLADE-relaxed→NAMD
  seed hook (committed, tested). `local_run.prepare_local_reference(solute_coords=)` threads it.
- Scratchpad drivers to promote into the runner (`…/scratchpad/`): **blade_relax.py** (OpenMM
  CHARMM+OBC2 minimize+Langevin, CutoffNonPeriodic 18 Å, traj capture, platform logging),
  **equil_metric.py** (plateau-time metric), **blade_equil_benchmark.py** (the 2-arm harness — the
  seed-NAMD mode's backbone). Move these into the repo (gpu-env script + uv-env orchestrator halves).
- Models `workspace/propagator_pilot/energy/forcenet_unified.pt` (+ duplex/ssdna). Curved-6hb view
  artifacts in `workspace/propagator_pilot/blade_view/` (gitignored; regenerate via `relax` mode).

## Suggested CreateBladeJobRequest knobs
`mode` (relax|seed_namd), `design_source_path`, `correction` (baseline|unified), relax:
`minimize_iters`,`langevin_ps`,`nb_cutoff_A`; seed_namd: `production_steps`,`dcd_freq`,
`ion_conc_mM`,`mg_conc_mM`; `autostart`.

## Open questions for next session (decide with user)
- MVP = relax-only tab, or wire seed-NAMD too (heavy/RunPod)?
- Display: trajectory playback only, or also per-atom uncertainty overlay (EnsembleForceNet exists)?
- Does the relax run on the LOCAL GPU (ties up the card) — gate it behind the sim-guard like NAMD?
