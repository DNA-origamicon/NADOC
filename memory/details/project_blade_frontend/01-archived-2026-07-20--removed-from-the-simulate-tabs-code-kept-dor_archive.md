# ARCHIVED (2026-07-20) — removed from the simulate tabs, code kept dormant — historical evidence

[Topic head](../../project_blade_frontend.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
