---
name: project_blade_frontend
description: BLADE simulation tab — built + shipped 2026-07-20, then ARCHIVED the same day (removed from the simulate tabs by user decision; code kept dormant). Read the ARCHIVED block first — everything below it is the (still-accurate) build record, kept for a revive.
metadata:
  type: project
---

# BLADE frontend tab — build handoff

## ARCHIVED (2026-07-20) — removed from the simulate tabs, code kept dormant

**User decision:** the current origami of interest have too many unconventional features for BLADE
seeding to be useful, and the whole BLADE line was consuming disproportionate effort. So BLADE was
pulled from the simulate tabs. The tab + relax + "Use as NAMD seed" all worked (see below); this is
a product/priority call, not a bug.

**What was changed to de-list it (all one-line-reversible):**
- `engine_capabilities.js` — removed `'blade'` from `ENGINE_KEYS` (was `['cando','blade','snupi',…]`
  → `['cando','snupi','mrdna','oxdna','namd']`). `ENGINE_LABELS.blade` + `ENGINE_CAPABILITIES.blade`
  KEPT (dormant, nothing iterates them now). Archived comment in place.
- `index.html` — `#blade-jobs-panel` forced `style="display:none"` (the selector no longer manages it,
  so without this the orphaned markup would show). Archived comment in place.
- `engine_capabilities.test.js` — tab-order assertion back to the five engines; blade CENSUS row kept
  with an ARCHIVED note.
- Verified in-app: tabs read `CanDo · SNUPI · mrDNA · oxDNA · NAMD`, no BLADE, panel hidden, zero
  console errors. Frontend suite 3107 pass.

**What was intentionally KEPT (dormant, not deleted):** all BLADE modules
(`blade_jobs_panel.js`, `blade_display.js`, `blade_metrics_card.js`, `blade_relax_gpu.py`,
`backend/core/blade_{job,runner,worker}.py`, `routes_blade.py`), the `/blade/*` client block,
`main.js` construction + wiring (dormant — one stray empty `/blade/jobs` fetch on workspace change,
harmless), `sim_jobs.normalize_blade_job`, the `routes_simulate` merge, `engines.py` blade entry
(still shows in Help ▸ MD Engines — a separate surface the user did not ask to change), and the
**NAMD-side seed plumbing** (`MdJob.seed_blade_job_id`, `CreateJobRequest.blade_job_id`,
`build_namd_seed_from_blade`, the `seededBadge`/`mdDraftRunLabel` "BLADE" branches). All backend
tests still pass.

**To revive:** re-add `'blade'` to `ENGINE_KEYS` (between `'cando'` and `'snupi'`), drop the
`display:none` on `#blade-jobs-panel`, restore the six-engine parity assertion. That's it.

**Validation that still stands (for whoever revisits):** BLADE relax → exact seed → solvate → stable
NAMD production verified across 1×6-flat / 2×4-square / 18hb (both lattices, 5.5× size). Clean relax
speeds at default 400 iters / 3 ps / CUDA: 1×6 14.1 s, 2×4 34.3 s, 18hb 64.2 s. Auto-retry
(escalate minimization on a NaN) added to `blade_relax_gpu.py` — dense bundles need more
minimization than the default 400 (the 18hb NaN'd at 300; retry recovers). BUT the strategic verdict
(see [[atomistic_propagator]]) is that BLADE's speed edge is modest + ensemble-only, erodes at origami
scale (the learned correction costs what dropping water saved), and the "faster equilibration from a
seed" claim on a curved structure is UNPROVEN (RunPod-bound). The value, if revisited, is
uncertainty-gated local NAMD fallback, not raw speed.

---

## STATUS (2026-07-20): SHIPPED — relax tab (MVP) + Phase 2 "Use as NAMD seed" both live  [now archived — see above]

Decisions taken with the user: **MVP = relax-only** · **sim-guard gated** · display = playback
(+ per-atom uncertainty was requested but is BLOCKED — see below). **Phase 2 = "Use as NAMD seed"
action, exact all-atom seed** — details in the "PHASE 2 SHIPPED" section below.

**Verified in the running app** (Playwright, read-only — never clicked Run, per
[[feedback_no_live_server_mutation_for_verify]]; Playwright spins its own backend on :8002):
engine selector reads `CanDo · BLADE · SNUPI · mrDNA · oxDNA · NAMD`; panel renders; availability
line resolves to `OpenMM 8.2.0.dev-5377094 via ~/micromamba/envs/gpu/bin/python`; **▶ Relax (y=375.7)
→ ■ Stop (y=411) → Jobs card (y=476)** — Run/Stop hoisted above the jobs card exactly as the other
engines (SNUPI's Run measures the SAME y=375.7); E-field / Anchors / Hard surface chips correctly
greyed; zero console errors.

**BACKEND** — `blade_job.py` (mode/correction/minimize_iters/langevin_ps/nb_cutoff_A/temp_K/
traj_frames/platform; stages `build`→`relax`) · `blade_runner.py` (detached worker + PID persist +
reconcile; `find_blade_python()`/`blade_available()`; `build_solute_inputs()` via psfgen;
`_run_gpu_relax()` streaming JSON-line progress; `_check_sim_guard()`) · `blade_worker.py` ·
`backend/ml/propagator/blade_relax_gpu.py` (the promoted scratchpad driver — **not importable from
the uv env by design**) · `routes_blade.py` · registered in `main.py`, `sim_jobs.normalize_blade_job`,
`routes_simulate`, `engines.py` (`_blade_plan`). **27 tests passing.**

**FRONTEND** — `engine_capabilities.js` (+ its CENSUS parity test) · `blade_jobs_panel.js` (one Run
button; availability gate; no anchors/E-field cards) · `blade_display.js` (only `off`/`deform`/
`trajectory`) · `blade_metrics_card.js` (a readout, not charts — a relax has no per-bp series) ·
`#blade-jobs-panel` + `#blade-run-controls` in `index.html` · `/blade/*` client block ·
`main.js` wiring incl. `_moveRunControls(runControlEls.blade, 'blade-launch-row', 'blade-stop-row')`
· `simulate_jobs.js` (`[BL]` badge, panel routing, master status line). The disabled-Stop CSS rule
is now SHARED with SNUPI (`#snupi-jobs-stop-btn, #blade-jobs-stop-btn`) so the two can't drift.
**38 new vitest tests; 3108 frontend tests green. main.js LOC 8039 — wiring only, no cohesive block.**

## PHASE 2 SHIPPED (2026-07-20): "Use as NAMD seed" — BLADE-relaxed → solvated NAMD run

Reinterpreted from the original `mode=seed_namd` toggle after discovery: **oxDNA/mrDNA already
expose seeding as a "Use as NAMD seed" action on a completed relax**, and the NAMD stack (solvation,
ladder, checkpoint/resume, RunPod/Alpine remote submit, ensembles) is all bound to `MdJob`. So
rather than a BLADE run-mode that re-implements NAMD launch, Phase 2 = a seed ACTION that creates a
real NAMD `MdJob` seeded from BLADE's relaxed structure. Decisions (user): **action, not mode** +
**exact all-atom seed** (`solute_coords=`, not the heavy-atom `atomistic_model=` seam oxDNA uses).

**Why BLADE seeds better than oxDNA:** oxDNA/mrDNA reconstruct an atomistic model from a
coarse-grained frame; BLADE's `relaxed.pdb` IS already the exact all-atom conformation in psfgen
order, so the handoff is a coordinate read, not a reconstruction — fed straight into solvation.

**BACKEND** (all in the existing NAMD job system — no NAMD logic in the BLADE worker):
- `blade_runner.build_namd_seed_from_blade(job_id, ws)` → `BladeNamdSeed{design (snapshot),
  solute_coords (N,3 Å, psfgen order), n_atoms}` + `assert_blade_namd_seed_available` (cheap
  precheck) + `_parse_pdb_xyz` (fixed-width cols 30:54, ATOM/HETATM).
- `MdJob.seed_blade_job_id` provenance field (+ `new_job` param, load setdefault).
- `routes_md.CreateJobRequest.blade_job_id`; `create_md_job` (3-way mutual exclusion; **GBIS
  rejected** for a BLADE seed — exact coords need full psfgen topology, GBIS is implicit);
  `_prepare_job_bg` blade branch → `local_design = seed.design`, passes `solute_coords` +
  forces `require_full_topology=True` (skipped for the equilibrium-aware protocol, which already
  pins it — else duplicate-kwarg collision); wired through `_spawn_draft_job`, `_spawn_prep_job`,
  `prepare_draft_job`, `refit_md_job`, `estimate_md_disk` (skips), `_seed_design_name`.
- **The seeded NAMD run renders as its OWN root NAMD row** (cross-engine parent/child unsupported —
  `MdJob.load`/`list_jobs` are `md_jobs/`-only); the link is the `seed_blade_job_id` provenance
  ("BLADE seeded" badge), NOT tree nesting — same as oxDNA→NAMD today.
- The exact-coords atom-order contract holds because `relaxed.pdb` and the solvation step both
  derive from `build_charmm_psfgen_topology(design)` on the SAME snapshot. `_overwrite_solute_coords`
  raises on a count mismatch — the guard against a silently-garbled seed.
- **13 backend tests** (`tests/test_blade_namd_seed.py`), all passing.

**FRONTEND** (near-verbatim clone of the oxDNA seed button):
- `#blade-jobs-seed-btn` + status div in the detail block; `seedReady(job)` (completed-only) gate;
  handler POSTs `createMdJob({blade_job_id, draft:true, autostart:true})` and dispatches
  `nadoc:md-job-created` (with `detail.jobId`) + `nadoc:sim-jobs-changed` → main.js flips to the NAMD
  tab and md_jobs_panel selects the new draft (existing listeners, no new nav code).
- `md_jobs_panel`: `mdDraftRunLabel` → "▶ Relax from BLADE"; `seededBadge` → "BLADE seeded" +
  title; `client.createMdJob` doc. New vitest cases in `blade_jobs_panel.test.js` +
  `md_jobs_panel.test.js`. Frontend suite **3109 passing**.
- Verified in app (read-only): seed button present, disabled with no completed relax, inside the
  detail block, zero console errors. The click→create-draft→navigate flow is NOT clicked live
  (creates a NAMD draft = live-server mutation, and needs a completed relax) — covered by unit tests
  + being a verbatim clone of the proven oxDNA handler.

**Flow for the user:** relax a design in BLADE → on the completed job, "Use as NAMD seed" → NAMD tab
opens with a draft → set salt/Mg/protocol/target (incl. RunPod/Alpine) → "▶ Relax from BLADE"
solvates from the exact relaxed coords + runs. Faster-converging validation data, no clashing ideal
B-DNA start.

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

## Suggested CreateBladeJobRequest knobs
`mode` (relax|seed_namd), `design_source_path`, `correction` (baseline|unified), relax:
`minimize_iters`,`langevin_ps`,`nb_cutoff_A`; seed_namd: `production_steps`,`dcd_freq`,
`ion_conc_mM`,`mg_conc_mM`; `autostart`.

## Open questions — ANSWERED 2026-07-20 (see STATUS block at top)
- MVP = **relax-only**. `seed_namd` is rejected at create time until wired.
- Display = playback **+ uncertainty was requested**, but uncertainty is BLOCKED (no ensemble
  checkpoint — see the STATUS blocker). Playback is built; the overlay is refused at the API.
- **Yes, sim-guard gated** — `_check_sim_guard()` refuses a CUDA relax while a heavy sim owns
  the machine. CPU platform is exempt (it's the escape hatch), and the guard fails open.
