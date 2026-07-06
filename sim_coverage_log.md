# Sim-coverage loop — session log, oracle catalog, lessons

Companion to [`SIM_COVERAGE_PLAN.md`](SIM_COVERAGE_PLAN.md) + [`sim_coverage_plan.json`](sim_coverage_plan.json).
One entry per session/commit. Live task status lives in the JSON; this is the durable narrative + the reusable
oracle library.

## Conventions

- One task per session, one commit (`feat(<engine>-coverage): <task> + <oracle>`), auto to master, no push.
- Pass criterion = a **comparable prediction with a property oracle**, never a bare run. Each session row ends
  with **"Comparable prediction gained, not just a run: ___."**
- New code is module-first; `backend/core` imports nothing from `backend/api`; metrics reuse the shared card.
- Fast/slow: real-engine tests get registered in `tests/conftest.py` (`_SLOW_MODULES`/`_SLOW_TESTS`); everything
  else stays in the fast loop.
- Three-Layer Law: outputs are Physical/display-only; anchors/fields are job-request annotations.

## How to check coverage (the probe)

```bash
# Which features does each engine cover? Grep the headless entry points + oracles per engine.
rg -l "def .*(anchor|field|extra_base|linker)" backend/core backend/physics
# Which engines feed the comparison card?
rg -n "register.*compare-source|compute_shape_descriptors" backend/core/shape_metrics.py 2>/dev/null
# Cross-engine agreement results land in sim_coverage_metrics.md § "Cross-engine agreement".
```

## Oracle catalog — the reusable validation building blocks (MIRROR THESE)

Fill one row per shipped oracle so later tasks reuse rather than re-derive.

| Oracle / pattern | Asserts (property, not "ran") | File(s) | Reuse for |
|---|---|---|---|
| _(S4) field-response_ | anchors held ≤ tol AND free beads deflect along +field AND monotone in \|F\| | `shape_metrics.py` (generalize `oxdna_health.measure_field_response`) | every engine's E-field task (C2, M2, N1) |
| **(S1) shape descriptors** ✅ | straight→twist≈0 & bend≈0; `_twist_bundle(60)`→60±10°, signed+monotone; `_arc_bundle(R,sweep)`→arc-span±12° & R±25%; can-go-red (twist>20 on twisted frame); single-helix→twist None | `backend/core/shape_metrics.py::compute_shape_descriptors`, `tests/test_shape_metrics.py` | every descriptor-emitting task (O1, C5, M5, N4); S3 consumes its dict; S4 field panel |
| _(S3) descriptor agreement_ | identical inputs→perfect; known-perturbed→expected Δ/correlation | `shape_metrics.py` | all cross-validation milestones |
| _(display-vs-oracle)_ | card's displayed numbers == headless oracle within tol; else STOP+ask | one-off Playwright per card (deleted after) | S5, C5, M5, N4 |

_(rows above are seeded targets; mark them shipped as the tasks land.)_

## Session entries

### 2026-07-05 — `S1` shape descriptors (shared-metric track head)

- **Picked** `S1` — head of the shared-metric track (M-METRIC-CORE), no deps, critical: no cross-validation
  *claim* is possible until a comparable descriptor set exists. Unblocks S3/S4/O1/C5.
- **Built** `backend/core/shape_metrics.py::compute_shape_descriptors(positions, *, n_slices=0)` — a thin,
  engine-agnostic composition layer over the *locked* `oxdna_health` bundle estimators. One call over any
  engine's display-position map (`{helix_id, bp_index, direction, backbone_position, …}`) returns:
  `twist_total_deg` (signed global twist), `twist_per_turn_deg` (÷ axial_span/`BDNA_PITCH_NM`≈3.505),
  `bend_angle_deg` + `bend_radius_nm` (both from ONE `bundle_slab_centreline` polyline via `_chord_sagitta_bend`
  → internally consistent), `radius_of_gyration_nm`, `end_to_end_nm` (chord between the two axial-end
  cross-section centroids), `axial_span_nm`, `n_nucleotides`. Degenerate frames → per-descriptor `None`
  (twist needs ≥2 helices) instead of crashing.
- **Additive helper** `oxdna_health.bundle_slab_centreline` (+31/−0; the locked estimators are byte-unchanged) —
  exposes the slab-centroid centreline so bend angle+radius derive from the same polyline. Reviewed +31/−0 with
  one caller.
- **Oracle** `tests/test_shape_metrics.py` (9 tests, **fast**), written before the module (imported it first → red
  on missing import). Asserts *properties*: null straight bundle, recovered programmed twist (signed+monotone),
  recovered arc-span angle+radius, Rg grows with bundle radius, and a can-go-red twisted frame. Fresh-context
  review: no defects; one by-design note (core-filtering is the caller's job on real ssDNA-ended frames).
- **Gates**: oracle 9/9; `just test-fast` = 4057 passed / 1 pre-existing flaky (`test_job_archive::
  test_md_list_includes_size` — passes in isolation, the known xdist active-design cross-test artifact, not this
  diff); `ruff check` clean on the 3 touched files (repo has unrelated pre-existing lint debt — not swept, per
  `feedback_no_bulk_reformat`). No UI this session (the card is S5) → no smoke/Playwright.
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** any engine's frame now yields the SAME twist/bend/Rg/
  end-to-end descriptor set on the SAME substrate — the common yardstick S3 needs to say "these two engines
  agree to X%". (Not itself a cross-engine comparison — that's S3/S5 — but the prerequisite measurement layer.)

## Lessons (anti-patterns banked)

_(none yet — bank per-session gotchas here as `### Banked from <TASK-ID>` subsections.)_

## Difficulties ledger (genuinely-stuck items + why)

_(none yet — if a task is set `status="blocked"`, record the reason + what was tried here.)_
