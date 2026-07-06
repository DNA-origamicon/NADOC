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
| **(S2) deviation + RMSF profiles** ✅ | identical→rmsd 0; known non-rigid displacement recovered exactly (align=False); rigid pose removed by Kabsch, shear survives (align=True); static ensemble→rmsf 0; known amplitude→A/√2 round-trip; align strips bulk drift keeps site fluctuation; normalize max→1 + rescale-back + all-zero safe | `backend/core/shape_metrics.py::{deviation_profile,rmsf_from_ensemble,normalize_rmsf_profile}`, `tests/test_shape_deviation_rmsf.py` | S3 (agreement math consumes both); per-nt deviation-map + flexibility-map for any engine (O1/C5/M5/N4) |
| **(S3) descriptor agreement** ✅ | identical→signed %Δ 0 & Pearson 1 & shape-RMSD 0; +10/−10° twist→±10% signed; scaled RMSF→Pearson 1, reversed→<−0.99, constant→None (not NaN); rigid pose→shape-RMSD≈0 but shear survives; **CanDo dir-less RMSF vs oxDNA per-strand collapses to per-bp & correlates**; `reference_for` honors oxdna=shape/field, cando=rmsf, NAMD-override, missing→None | `backend/core/shape_metrics.py::{compare_descriptors,reference_for}`, `tests/test_shape_compare.py` | all cross-validation milestones (S5 card, O1/C5/M5/N4 sources) |
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

### 2026-07-06 — `S2` deviation + RMSF profiles (shared-metric track)

- **Task**: generalize the two engine-specific flexibility/deviation implementations into `shape_metrics.py` as
  engine-agnostic per-nucleotide profiles S3's `compare_descriptors` will consume. Backend-only, fast, no UI.
- **Shipped** (all read-only over positions — Three-Layer Law; copy-aware `(helix,bp,dir,copy)` keys throughout):
  - `deviation_profile(cand, ref, *, align=True)` → `{positions:[{…,deviation}], rmsd_nm, min/max/mean_deviation,
    n}`. `align=True` = Kabsch best-fit candidate→ref (reuses `oxdna_health._kabsch_superpose`; strips rigid pose,
    intrinsic twist/bend survives) — generalizes `geometry_deviation_map`/`measure_geometry_rmsd`. `align=False` =
    direct key-matched distance (exact residual) — generalizes `cando_deviation.compute_deviation`.
  - `rmsf_from_ensemble(frames, *, align=True)` → per-nt RMS fluctuation about the mean over a frame list; the
    variance core of `oxdna_health.production_rmsf` stripped of the oxDNA trajectory-file I/O, so NAMD/mrDNA/any
    ensemble can feed it. CanDo instead supplies NMA RMSF directly (`predict_shape["rmsf"]`).
  - `normalize_rmsf_profile(profile)` → keyed `"{helix}:{bp}:{dir}"` [0,1] map from any `{helix_id,bp_index,
    rmsf_nm,direction?}` list (dir-less → both strands); generalizes `fem_solver.normalize_rmsf` off the mesh.
- **Oracle** `tests/test_shape_deviation_rmsf.py` (**10 tests, fast**), written before the code (imported the new
  names first → red on missing import). Asserts *properties*: rmsd 0 on identical, exact per-nt recovery of a
  known non-rigid displacement, Kabsch removes a pure rotate+translate (`d_raw>1.0` contrast) while a shear
  survives, static ensemble→0, `A/√2` amplitude round-trip, `align=True` strips ~3.6 nm bulk drift yet keeps a
  single-site fluctuation, normalize max→1 + rescale-back + all-zero safety. Fresh-context review: no defects;
  flagged the `align=True`-with-real-motion RMSF branch as unpinned → added
  `test_align_removes_bulk_drift_but_keeps_site_fluctuation` to close it (10th test).
- **Gates**: oracle 10/10; `just test` = **4128 passed / 66 skipped / 1 xfailed** (full suite, no drop); the 3
  touched files are ruff-clean (repo has unrelated pre-existing lint debt in other test files — not swept, per
  `feedback_no_bulk_reformat`). No UI this session (card is S5) → no smoke/Playwright. **main.js LOC Δ = 0**
  (backend-only).
- **Comparable prediction gained, not just a run:** any engine's frame(s) now yield the SAME per-nucleotide
  deviation-from-design (+global RMSD) and the SAME per-nucleotide RMSF on the shared substrate — the two
  profile yardsticks S3 needs to say "engine A's flexibility/shape agrees with engine B to r/Δ". (Not itself a
  cross-engine comparison — that's S3 — but its second prerequisite measurement, completing S1+S2.)

### 2026-07-06 — `S3` cross-engine agreement math (shared-metric track)

- **Picked** `S3` — critical path to `M-METRIC-CORE`: deps S1+S2 both done, and it's the last pure-math
  primitive before the S5 comparison card. It turns S1's descriptor dicts + S2's profiles into an actual
  *agreement score* — the first task that produces a cross-validation *number*, not just a shared measurement.
- **Built** `backend/core/shape_metrics.py` — two engine-agnostic entry points (pure over Physical-layer dicts,
  no topology):
  - `compare_descriptors(candidate, reference, *, align_shape=True)` — scores three observable classes:
    (1) `COMPARABLE_SCALARS` (7 shape descriptors) → `{candidate, reference, abs_delta, signed_pct_delta}`,
    pct = (cand−ref)/|ref|·100, `None` scalar → incomparable, zero-ref → abs_delta w/ `None` pct (no div0);
    (2) `rmsf` → Pearson+Spearman over shared base pairs `{pearson, spearman, n, candidate/reference_mean_rmsf_nm}`,
    degenerate (constant or <2 shared) → `None` coeff (not NaN, via `_finite_or_none`);
    (3) `shape_rmsd_nm` → reuses `deviation_profile(align=True)` Kabsch (rigid pose zeroed, real shape survives).
    A partial bundle yields a partial comparison (missing observable → `None`), never a crash.
  - `reference_for(engines, observable)` — per-observable policy (`shape`/`field`→oxdna, `rmsf`→cando) with
    NAMD gold-override across *all* observables; missing policy engine / unknown observable / empty → `None`
    (a missing reference is reported, never silently mis-assigned).
- **Oracle** `tests/test_shape_compare.py` (**13 tests, fast**), imports written first (red on missing name).
  Asserts *properties*: identical-source perfect agreement; signed-%Δ sign+magnitude; None/zero-ref safety;
  RMSF scaled→Pearson 1 / reversed→<−0.99 / constant→None; aligned-shape RMSD ignores a rigid rotate+translate
  but catches a shear; and `reference_for` policy + NAMD override + missing→None.
- **Review-caught HIGH bug, fixed**: the first cut keyed RMSF on `direction`, but CanDo's NMA RMSF (the *policy
  RMSF reference*) is direction-less (1 entry/bp) while ensemble RMSF is per-strand (2/bp) — the key-sets never
  intersected, so the one pairing the policy exists to make (`reference_for(...,"rmsf")=="cando"` vs any
  ensemble engine) silently returned `None`. Fix: `_rmsf_per_bp` collapses BOTH profiles to a per-`(helix,bp,
  copy)` mean over strand direction (mirrors the strand-agnostic collapse already in `normalize_rmsf_profile`).
  Added `test_rmsf_cando_directionless_vs_ensemble_per_strand_correlates` to pin exactly that case (the oracle
  had been green-by-construction on `direction="forward"` on both sides).
- **Gates**: oracle 13/13 (32/32 across S1+S2+S3); `just test` = **4140 passed / 66 skipped / 1 xfailed / 1
  pre-existing flaky** (`test_job_archive::test_md_list_includes_size` — passes in isolation, the known xdist
  active-design cross-test artifact, not this diff); `ruff check` clean on the 2 touched code files (repo has
  unrelated pre-existing lint debt — not swept, per `feedback_no_bulk_reformat`). No UI this session (card is
  S5) → no smoke/Playwright/display-vs-oracle (N/A: no card yet).
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** two engines' frames now yield an actual agreement score —
  signed %Δ per shape descriptor, Pearson/Spearman on the per-bp RMSF profile, and Kabsch-aligned shape RMSD —
  with the reference chosen per-observable by policy (incl. NAMD override). This is the first cross-*validation*
  number in the loop; S5 wraps it in the generate/view/export card.

## Lessons (anti-patterns banked)

### Banked from S3

- **Direction-keyed matching silently drops the primary cross-engine pairing.** Engines disagree on strand
  convention: CanDo NMA RMSF is a direction-less axis-node value (1/bp); `rmsf_from_ensemble` (oxDNA/NAMD/mrDNA)
  is per-strand (2/bp). Keying a cross-engine match on `direction` leaves an empty intersection → a *silent*
  `None`, which reads as "no data" not "misconfigured key". When reconciling per-nucleotide profiles ACROSS
  engines, collapse to the coarsest shared unit (per base pair) first. `normalize_rmsf_profile` already knew
  this (emits both strands for a dir-less entry); the new code initially didn't. **A green oracle that hand-
  matches `direction` on both sides is green-by-construction** — pin the *mixed*-convention case explicitly.

## Difficulties ledger (genuinely-stuck items + why)

_(none yet — if a task is set `status="blocked"`, record the reason + what was tried here.)_
