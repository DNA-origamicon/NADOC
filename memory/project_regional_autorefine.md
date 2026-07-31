---
name: project_regional_autorefine
description: LIVE REFERENCE — the shipped always-on skip fine-tune pass (skip_finetune + greedy_finetune_skips) and the shelved wholesale regional placer it grew out of. Read before touching autorefine skip placement.
metadata:
  type: project
---

# Regional autorefine — what shipped, what's shelved

**STATUS (audited 2026-07-30 against live code): this is a LIVE REFERENCE, not a plan.**
Its "Phase 5 / NOT viable / NEXT" framing was misleading in both directions. Two halves:

- **SHIPPED and ALWAYS ON** — the re-scoped 1–5-edit greedy fine-tuner. Every ✦ Autorefine
  click runs it (`AutorefineStartRequest.finetune=True`, no UI toggle). All four functions of
  `backend/core/skip_finetune.py` are on the live path.
- **SHELVED, unreachable from the UI** — wholesale regional (non-uniform) re-placement of the
  full skip budget. `regional=False` everywhere; the frontend exposes **no** `regional`/`w_dev`/
  `w_strain`/`min_spacing` control, so it is reachable only by hand-POSTing the API.

History (Phases 5.0–5.4, the four proxy refutations, the re-scope) → `project_regional_autorefine_archive.md`.

> **MEASUREMENT CAVEAT — do not cite this file's or the archive's degree values as physics.**
> Every twist number here was measured before exp34 (2026-06-29) found the **~5M-step twist
> equilibration transient** on the 3×6×400 SQ bundle; the standard 8M production with
> `equil_steps=100_000` never equilibrated, so all of them are biased mid-transient reads
> (±9° scatter). The *qualitative* findings (placement strongly moves net twist; wholesale
> redistribution diverges) were independently re-derived by exp32/34/35 and stand. The numbers
> did not. Current science lives in `project_skip_twist_curvature_sweep.md` + LESSONS A6/A7/A8.
> `autorefine_sq_design` now defaults `equilibration_steps=10_000_000` (the exp34 fix, validated
> by exp35 — necessary but **not sufficient**; see that file for the residual slow glide).

## What runs when you click ✦ Autorefine

1. `prepare_design_for_autorefine(base)` — if the design has no skip marks **or** any undefined
   `'N'` base, apply the analytical seed period + `full_sequence`. An already-skipped+sequenced
   design is untouched (hand-tuning preserved). Emits `phase="prepared"`.
2. **Count / net-twist gate (unchanged, the thing that actually works):** the scalar secant over
   uniform period via `PeriodAdjuster`, driven by the *differential* twist (sim − analytic).
   Step is **adaptive** — `frac = clamp(|residual|·explore_gain, explore_min, explore_max)` with
   `0.015 / 0.03 / 0.5`. Big when far (square lattice needs roughly half the analytical period),
   gentle when close. A fixed gentle step stalled; see the archive.
3. **Fine-tune pass (always on):** `greedy_finetune_skips` — `identify_finetune_edits` proposes
   ≤`finetune_max_edits` (default 5) local edits (ADD a deletion in an over-wound hotspot, REMOVE
   the nearest in an under-wound one), each applied → re-simulated → **accepted only if `dev_max`
   improves and |net twist| ≤ tol**, else reverted. A flat/noise field yields 0 edits (does no harm).
   Sets `placement="finetuned"` + `converged_skips` (the explicit final pattern).
4. **Apply:** the completion call passes **no period**, so the route lays `converged_skips`
   verbatim. Uniform runs fall back to the converged period.

Why 1–5 edits is safe where wholesale wasn't: on a full-scale origami one skip ≈ 0.2° of a ~50°
total correction, so ≤5 edits perturb net twist <1° **by construction**. Wholesale re-placement
rewrites the global deletion register, which alone swings net twist ±30–45°.

## Code locations (verified 2026-07-30)

| Thing | Where |
|---|---|
| Fine-tune candidate ID + edit application | `backend/core/skip_finetune.py` (118 LOC, 4 fns): `current_skips_by_helix:20`, `_signed_overtwist_slope:26`, `identify_finetune_edits:44`, `apply_finetune_edit:104` |
| Greedy re-sim / accept-or-revert loop | `backend/api/skip_twist_tuning.py:346` `greedy_finetune_skips` (+ `_finetune_measure:298`) |
| Orchestrator | `skip_twist_tuning.py:495` `autorefine_sq_design` — fine-tune block at `:663`; **its own `finetune` default is `False`**, the `True` default lives on the request model |
| Auto-prepare | `skip_twist_tuning.py:417` `prepare_design_for_autorefine` |
| Period secant | `skip_twist_tuning.py:127` `PeriodAdjuster`, `_explore_step:168`, constants `:144-148` |
| Convergence driver | **`backend/api/headless_oxdna_build.py:985` `iterate_to_constraint`** (NOT in `skip_twist_tuning`) — imported `skip_twist_tuning.py:535`, called `:614`; its `on_measure` hook is built only in the regional branch (`:603-622`, else `None`) |
| Skip-pattern builders | `skip_twist_tuning.py`: `build_sq_skip_from_design:190`, `build_regional_skip_design:211`, `build_explicit_skip_from_design:242` |
| Field measurement | `skip_twist_tuning.py:264` `measure_skip_fields` |
| Routes | `backend/api/routes_autorefine.py` — start `:99`, apply `:124`, stop `:197`, poll `:216`. Registered `backend/api/main.py:79` + `:276` (`prefix="/api"`). **Moved out of `crud.py`** |
| Request model | `routes_autorefine.py:31` `AutorefineStartRequest` — 18 fields; `finetune=True` at `:47` |
| Apply branch | `routes_autorefine.py:151-153` (`explicit_skips = result["converged_skips"]`, gated on `period is None`), `:178-190` explicit vs uniform |
| Frontend | `frontend/src/ui/oxdna_jobs_panel.js` — start `:763`, fine-tune result block `_finetuneBlock:603` (rendered `:642`), completion apply `:718-724`, deviation-map toggle `oxdna-jobs-deviation-toggle` (`:445/:836/:2267`) |
| Metrics | `backend/core/oxdna_health.py`: `geometry_deviation_map:1110`, `measure_bundle_twist:1186`, `measure_bundle_twist_profile:1283`, `measure_bundle_bend:1358`, `_dispatch_measure:2063`, `backbone_strain_field:3324`. **`backbone_bond_pairs` / `oxdna_backbone_site` live in `backend/physics/oxdna_interface.py:2179/:1446`**, re-imported at `oxdna_health.py:30/33` |

`placement` takes three values: `"uniform"` / `"regional"` (`skip_twist_tuning.py:633`) and
`"finetuned"` (`:670`, overwrites).

## The shelved half — `regional_skip_placer.py` is NOT dead code

`backend/core/regional_skip_placer.py` (259 LOC) is **mixed**: the wholesale placer is shelved,
but three of its functions are load-bearing elsewhere. **Do not delete this module.**

| Function | Status |
|---|---|
| `core_candidates:43` | **Most-reused symbol in the file** — `backend/core/cando_autorefine.py:161-162` (production CanDo autorefine) + `skip_sweep_strategies.py:77/124/148`. Deleting the module breaks production CanDo |
| `aggregate_deviation_per_bp:34` | **Wired** — `skip_twist_tuning.py:283/343` (live fine-tune path) |
| `detrend_error_profile:130` | **Wired** — `skip_twist_tuning.py:314/339` |
| `place_regional_skips:70`, `budget_from_uniform_period:252` | Shelved — one caller each, inside `build_regional_skip_design`, reachable only via `regional=True` |
| `redistribute_by_twist_profile:208` | **Fully orphaned** — tests only (`tests/test_regional_skip_placer.py:207/234/263`) |

**The real successor to this plan's ambition is `backend/core/cando_autorefine.py`** (53 KB) —
its docstring `:12` says it is `greedy_finetune_skips` with the FEM oracle swapped in. Fully
wired: `routes_cando_autorefine.py:70/186`, `cando_runner.py:333`, router registered
`main.py:71/272`. It reuses `core_candidates` and mirrors the fine-tuner's noise gate (`:92`).

Two other newer modules occupy adjacent ground, both **experiment/test-only, no production
import**: `skip_sweep_strategies.py` (placement strategies for exp31/33/34/35) and
`profile_guided_refine.py` (the exp32 signed-profile controller — **diverged**, LESSONS A7).

## Do not resurrect without reading LESSONS A6/A7

Wholesale redistribution of the full skip budget was refuted four times (one-shot deviation
placement, naive iterative, detrended iterative, and the exp32 per-segment secant). Root cause:
**net twist is exquisitely sensitive to the exact deletion register** — the placement scheme
alone swings it far more than the local-shape signal a regional optimizer would be correcting.
The control authority's side-effect exceeds its target, so the optimizer chases its own
placement artifacts. The deviation / strain / twist-profile fields are a **diagnostic** (show
where a design deviates or is strained, for manual regional exceptions), not an optimizer signal.

## Known open defects on the SHIPPED fine-tuner

Both owned by `project_skip_twist_curvature_sweep.md` (exp34/exp35) — recorded here so nobody
reads this file as "shipped and clean":

1. **`greedy_finetune_skips` / `identify_finetune_edits` rank + accept on unsigned `dev_max`,
   which violates LESSONS A6** — they need the signed-twist variant. Flagged as follow-up tech
   debt in `project_skip_twist_curvature_sweep.md`.
2. **Never GPU-validated end-to-end.** The always-on fine-tune pass ships to every Autorefine
   click but has only ever been exercised against mock/stub engines + the 4 mocked e2e specs.
   exp34 Gate 2 was designed as its validation and the run never resolved it.

## Tests (counted 2026-07-30)

`tests/test_regional_skip_placer.py` **18** · `tests/test_skip_finetune.py` **10** ·
`tests/test_skip_twist_tuning.py` **22** (incl. `test_autorefine_apply_regional_lands_explicit_pattern:269`,
`test_period_adjuster_step_scales_with_residual_and_is_directed:123`,
`test_prepare_design_for_autorefine_applies_skips_and_sequences:105`) ·
`tests/test_skip_twist_tuning_production.py` **3** ·
`tests/test_headless_oxdna_build.py::test_autorefine_regional_runs_end_to_end_and_reports_pattern:223` ·
`frontend/e2e/autorefine_button.spec.js` **4** (mocked).
**None of these carry `@pytest.mark.slow`** — they are all fast-suite.

## Corrections — what the pre-audit head got wrong

- `iterate_to_constraint` was described as living in `skip_twist_tuning`; it is in
  `headless_oxdna_build.py:985`.
- Claimed a pin `test_period_adjuster_first_step_is_small_and_directed` (cited twice) — **it does
  not exist**. The live pin is the adaptive-step one.
- Claimed 10 tests in `test_regional_skip_placer.py`; there are **18**.
- Described the `oxdna-jobs-finetune-toggle` checkbox as live in one section and removed in
  another. **Removed is correct** — zero hits repo-wide; the frontend sends no `finetune` field
  and relies on the route default.
- Its "KNOWN v1 gap" (the completion apply passing `converged_period` instead of `period=None`)
  is **fixed** — `oxdna_jobs_panel.js:718-724` applies with no period for finetuned/regional.
- Its whole "Next / 5.4 GPU validation / 5.5 frontend" open list was stale: 5.5 shipped, and 5.4
  validates a path that is now shelved.
- `results/profiles/uniform_d+0.csv` is exp31-relative →
  `experiments/exp31_skip_twist_curvature_sweep/results/profiles/uniform_d+0.csv`.
- `backbone_bond_pairs` / `oxdna_backbone_site` are in `backend/physics/oxdna_interface.py`,
  not `oxdna_health.py`.

## Related

[[project_skip_twist_selfconsistency]] (the uniform secant this post-processes) ·
[[project_skip_twist_curvature_sweep]] (exp31–35: the current science, the equilibration
transient, and both open defects above) · [[project_cando_fem]] (`cando_autorefine`, the FEM-oracle
successor) · [[project_md_twist_validation]] (exp33 atomistic cross-check) · LESSONS A6/A7/A8.
