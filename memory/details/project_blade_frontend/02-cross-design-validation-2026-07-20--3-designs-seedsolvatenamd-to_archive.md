# Cross-design validation (2026-07-20) — 3 designs, seed→solvate→NAMD to stable production — historical evidence

[Topic head](../../project_blade_frontend.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Cross-design validation (2026-07-20) — 3 designs, seed→solvate→NAMD to stable production
Drove the FULL path (relax → exact seed → GROMACS solvate → NAMD minimize+restrained ladder →
fully-released free production k=0) on three shapes, both lattices, 5.5× size range. All reached a
stable production run (all ladder segments done, finite energy, no NaN/constraint failure), 2 fs /
no-HMR (stricter than the feature's 4 fs HMR), 12.5 mM Mg/MGH. Isolated scratch WS, not the live
server.

| design | lattice | solute atoms | NAMD final energy |
|---|---|---|---|
| 1×6 flat | square | 18,530 | −672,817 |
| 2×4 square | square | 25,054 | −599,516 |
| 18hb | honeycomb | 101,937 | −2,674,489 |

**Atom-order contract holds across all three**: seed atoms == relax atoms == solvated solute count;
solvation never raised (it raises on any mismatch). This is the design-agnosticism the seed needed.

**BLADE-relax robustness fix (the one real issue found).** A dense bundle's ideal B-DNA build has
severe inter-helix crossover clashes; too few minimization iters leave a contact that explodes into
an OpenMM `Particle coordinate is NaN` on the first Langevin step. The 18hb (102k atoms) NaN'd at 300
iters; it's MARGINAL at the default 400 (the relax is stochastic — random velocities + Langevin — so
a marginal structure NaNs non-deterministically). Fix: `blade_relax_gpu.py` now ESCALATES
minimization on a non-finite coordinate — reset to ideal coords, retry at `max(iters*8, 4000)` then
run-to-convergence (maxIterations=0), up to 3 attempts; `used_minimize_iters` + `relax_attempts` in
the result, a `minimize_retry` event in the worker log. Verified: forced NaN at 25 iters → auto-retry
at 4000 → finite. Recovery repeats only minimize+settle (the psfgen build isn't redone). Clean relax
speeds at default 400 iters / 3 ps / CUDA: 1×6 15.8 s, 2×4 46.6 s, 18hb 101.9 s (build 1.3/2.1/10.7 s).
Validation scripts in scratchpad (`blade_seed_validation.py`, `blade_seed_18hb_close.py`,
`blade_relax_compare.py`). Possible follow-up: proactively scale initial minimize_iters with atom
count to skip the wasted first attempt on big designs (retry already covers correctness).

**NOT DONE:** registering `"blade"` in `md_pipeline.CROSS_ENGINE_SEED_FIELD` (the separate P3
pipeline-chaining feature — the button path doesn't use it; a future extension). The
`mode="seed_namd"` field on `CreateBladeJobRequest` is now vestigial (still rejected 400) — the
action supersedes it; consider removing it.

**BLOCKER on the uncertainty overlay (user asked for it; refused at the API with a 400).**
`EnsembleForceNet` (`backend/ml/propagator/uncertainty.py`) does emit per-atom epistemic uncertainty
from `forward()` → `(mean_force [N,3], u [N])` — but **no ensemble checkpoint has ever been trained
or saved.** `workspace/propagator_pilot/energy/forcenet_unified.pt` holds a SINGLE `ForceNet`
(schema `{state,hidden,layers,cutoff}`); a K-member ensemble format doesn't exist. So per-atom
uncertainty is unobtainable from any artifact today.
Second obstacle even once a checkpoint exists: `atomistic_renderer.applyScalarColors(map)` is
**nucleotide-keyed**, so per-*atom* colouring needs a new channel — and the scalar-colour channel is
single-slot (it would supersede RMSF/deviation, not compose).
To unblock: train + save K seeded ForceNets, add a `load_ensemble()` resolver (there is NO repo-side
checkpoint loader at all — every existing load is a scratchpad script with a cwd-relative path),
then decide per-atom vs per-nucleotide granularity.

**Key reuse discovered (don't re-derive):** the trajectory does NOT need a bespoke format —
`blade_runner._build_trajectory` routes the all-atom DCD through NAMD's
`md_trajectory.md_composite_trajectory(psf, [("relax","relax",dcd)], ideal_pdb, design)`, which
already owns P-atom ordering, 5'-terminus recovery, base normals and the ≤200-frame downsample,
and emits the canonical `{keys, frames, n_frames}` — so the existing frontend scrubber
(`framesToUpdates`) works on BLADE runs with zero new client decoding. `/blade/jobs/{id}/display`
serves the settled shape as `{keys, frame}` in that same encoding.

---

## ↓ HISTORICAL — the original build plan (executed 2026-07-20) ↓
Kept for the architecture notes and the file:line map, which are still accurate. The step-by-step
clone recipe is DONE; do not re-run it. Where the plan and the STATUS block above disagree, the
STATUS block is right — notably: the metrics card was NOT cloned (a relax has no per-bp series),
the display has only 3 modes, and there are no anchors/E-field cards.

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
