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
| **(S4) field-response** ✅ | anchors held ≤ tol AND free nts deflect along +field AND monotone in \|F\|; cross-engine deflection cosine +1 identical / −1 opposite / 0 orthogonal, magnitude-ratio = compliance ratio; zero-field & no-free raise; copy-aware, no-shared-free→None | `shape_metrics.py::{field_response_profile,compare_field_response}`, `tests/test_shape_field_response.py` | every engine's E-field task (C2, M2, N1); S5 field panel |
| **(S1) shape descriptors** ✅ | straight→twist≈0 & bend≈0; `_twist_bundle(60)`→60±10°, signed+monotone; `_arc_bundle(R,sweep)`→arc-span±12° & R±25%; can-go-red (twist>20 on twisted frame); single-helix→twist None | `backend/core/shape_metrics.py::compute_shape_descriptors`, `tests/test_shape_metrics.py` | every descriptor-emitting task (O1, C5, M5, N4); S3 consumes its dict; S4 field panel |
| **(S2) deviation + RMSF profiles** ✅ | identical→rmsd 0; known non-rigid displacement recovered exactly (align=False); rigid pose removed by Kabsch, shear survives (align=True); static ensemble→rmsf 0; known amplitude→A/√2 round-trip; align strips bulk drift keeps site fluctuation; normalize max→1 + rescale-back + all-zero safe | `backend/core/shape_metrics.py::{deviation_profile,rmsf_from_ensemble,normalize_rmsf_profile}`, `tests/test_shape_deviation_rmsf.py` | S3 (agreement math consumes both); per-nt deviation-map + flexibility-map for any engine (O1/C5/M5/N4) |
| **(S3) descriptor agreement** ✅ | identical→signed %Δ 0 & Pearson 1 & shape-RMSD 0; +10/−10° twist→±10% signed; scaled RMSF→Pearson 1, reversed→<−0.99, constant→None (not NaN); rigid pose→shape-RMSD≈0 but shear survives; **CanDo dir-less RMSF vs oxDNA per-strand collapses to per-bp & correlates**; `reference_for` honors oxdna=shape/field, cando=rmsf, NAMD-override, missing→None | `backend/core/shape_metrics.py::{compare_descriptors,reference_for}`, `tests/test_shape_compare.py` | all cross-validation milestones (S5 card, O1/C5/M5/N4 sources) |
| **(S5) comparison report** ✅ | per-observable reference selection (oxDNA=shape/field, CanDo=RMSF, NAMD-override); scalar reference→0-delta & candidate recovers ±known %; zero-ref→None (no div0); identical RMSF→Pearson 1 + overlay points; rigid-shift→shape-RMSD≈0; field cosine +1/−1 & mag-ratio 3; 1-engine→raw-no-agreement; empty→not-ready; missing observable omits its rows; REST start→poll→result+404 | `backend/core/shape_compare.py::build_comparison_report`, `backend/api/routes_shape_metrics.py`, `tests/test_shape_compare_report.py` | the compare card; per-engine source-bundle contract for C5/O1/M5/N4 |
| _(display-vs-oracle)_ ✅ (S5) | card's displayed numbers == headless oracle within tol; else STOP+ask | one-off Playwright per card (deleted after) | S5 ✓, C5, M5, N4 |
| **(O1) oxDNA source bundle** ✅ | descriptors == `measure_bundle_twist(core)` on the exact core-filtered frame (same estimator, self-consistent — ABSOLUTE not the differential graph); core mask drops ssDNA ends; `production_rmsf` `rmsf`→`rmsf_nm` remap (None dropped); field passthrough; drops into `build_comparison_report` as ready `oxdna` SHAPE reference; empty core ref→None descriptors (RED) | `backend/core/oxdna_shape_source.py::build_oxdna_shape_source`, `backend/api/routes_oxdna.py::get_oxdna_shape_source`, `tests/test_oxdna_shape_source.py` | the SAME source-bundle contract for C5/M5/N4 (each engine builds `{engine, descriptors, rmsf, shape_frame, field}` from its own frame + core mask) |

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

### 2026-07-06 — `S4` unified field-response descriptor (shared-metric track)

- **Picked** `S4` — highest-leverage eligible task: shared-metric track leads, deps=S1 met, low effort, closes
  half of what remained in `M-METRIC-CORE` (S4+S5) and unblocks the E-field oracle every engine's field task
  (C2, M2, N1) will reuse + enriches the S5 card's field panel.
- **Built** `backend/core/shape_metrics.py` — the engine-agnostic E-field layer (pure read-over-positions, no
  topology; NOT Kabsch-aligned — the anchored region IS the common frame, aligning would erase the measured
  motion):
  - `field_response_profile(field_positions, reference_positions, field_dir, anchor_keys, *, anchor_tol_nm=1.0,
    min_free_proj_nm=0.5)` — generalizes `oxdna_health.measure_field_response`. Reproduces its aggregates +
    physical verdict byte-for-byte (`passed` = anchored_max_drift ≤ tol AND free_proj_along_field ≥ min; same two
    `ValueError`s on zero field-dir / no free nts) and ADDS a copy-aware `per_nt` deflection map
    `[{helix_id,bp_index,direction,copy,disp_vec_nm,disp_nm,proj_along_field_nm,anchored}]` plus the mean free
    `deflection_vec_nm`. Keys via `_dev_key` (copy-distinct so inserted-base copies stay separate); anchor
    membership is copy-AGNOSTIC (an anchored bp pins all its copies).
  - `compare_field_response(candidate_profile, reference_profile)` — cross-engine agreement over the SHARED FREE
    nucleotides: `cosine_similarity` (cosine of the two engines' concatenated free displacement vectors:
    identical→+1, opposite→−1, orthogonal→0) + `magnitude_ratio` (‖cand‖/‖ref‖ = relative compliance), `None`
    on degenerate/empty (`n_shared_free=0`). Both profiles normalize `direction` identically → no S3-style
    silent-empty-intersection.
- **Oracle** `tests/test_shape_field_response.py` (**13 tests, fast**), imports written first (red on missing
  name). Asserts *properties*: anchors held + free deflect along field, per-nt map covers every shared nt with
  correct anchored flags, deflection monotone in |F|, fails when anchors drift or free doesn't deflect,
  copy-aware keys stay distinct, zero-field & no-free raise; cross-engine cosine +1/−1/0, magnitude-ratio=3.0 at
  3× compliance, no-shared-free→all-None. Fresh-context review: no correctness gaps against the oracle.
- **Gates**: oracle 13/13 (45/45 across S1–S4); `just test` = **4155 passed / 66 skipped / 1 xfailed** (full
  suite, no drop from S3's 4140 + these 13 + repo growth); `ruff check` clean on the 2 touched files (repo has
  unrelated pre-existing lint debt in other test files — not swept, per `feedback_no_bulk_reformat`). No UI this
  session (field panel lands in the S5 card) → no smoke/Playwright/display-vs-oracle (N/A: no card yet).
- **main.js LOC Δ = 0** (backend-only, no frontend).
- **Comparable prediction gained, not just a run:** two engines' E-field responses now yield an actual agreement
  score — a copy-aware per-nt deflection field, the free-region projection-along-field, and a cross-engine
  deflection cosine + magnitude ratio — so "does CanDo deflect the way oxDNA does under the same field?" becomes
  a number, not a vibe. This is the E-field half of the cross-validation deliverable; S5 wraps it in the card.

### 2026-07-06 — `S5` cross-engine comparison CARD (closes M-METRIC-CORE)

- **Picked** `S5` — the last shared-metric task; the S1–S4 math existed but couldn't be *reported*. Closes
  M-METRIC-CORE and unblocks the per-engine emission tasks (C5/O1/M5/N4). deps=S3 met.
- **Backend** `backend/core/shape_compare.py::build_comparison_report(sources)` — a PURE assembly that composes
  S3/S4 (`reference_for` + `compare_descriptors` + `compare_field_response`) into one card payload from a list of
  per-engine source bundles `{engine, descriptors?, rmsf?, shape_frame?, field?}`: a scalar table (each engine's
  value + signed %-delta vs the SHAPE reference), per-engine RMSF overlay profiles (collapsed per-bp), agreement
  rows (shape-RMSD vs shape-ref, RMSF Pearson/Spearman vs rmsf-ref, field cosine/ratio vs field-ref), and a field
  panel (per-engine held+deflected verdict + cosine-vs-ref). Per-observable reference honors the S3 policy
  (oxDNA=shape/field, CanDo=RMSF, NAMD overrides all). Graceful: 1 engine → raw values no deltas; missing
  observable → no rows for it; never crashes. Read-only over Physical-layer dicts (Three-Layer Law) — no topology.
- **Backend route** `backend/api/routes_shape_metrics.py` — daemon-thread registry (mirrors `routes_oxdna_metrics`):
  `POST /shape/compare/start` (body `{sources:[…]}`) → `{metrics_id}`; `GET /shape/compare/{run_id}` →
  `{state, progress, result?}`. Registered in `main.py`. (Compute is instant now — sources are posted
  pre-computed — but the daemon pattern is kept so the per-engine tasks can later make source-*gathering* slow
  without changing the card.)
- **Frontend** `frontend/src/ui/shape_compare_card.js` — the card factory + PURE helpers (`fmtNum`, `fmtDelta`,
  `scalarTableModel`, `rmsfOverlaySpec` via the shared `metric_graph.buildChartSpec`, `comparisonCSVs`).
  Generate → gather sources → `POST`/poll → render scalar table + RMSF overlay canvas + agreement table + field
  panel; Export → shared `metric_export_modal` (PNG of the overlay via `renderToDataURL`, CSV of the three tables).
  Hosted as a collapsible card in the oxDNA Dynamics panel, wired from `initOxdnaJobsPanel` (`getSources: ()=>[]`
  for now — live per-engine sources are O1/C5/M5/N4, tracked as MV-21). Reuses `metric_graph`/`metric_export_modal`
  verbatim — the card machinery is bound, not rebuilt. **`main.js` LOC Δ = 0.**
- **Oracle** `tests/test_shape_compare_report.py` (**14 tests, fast**), written before the assembly (imported the
  new name first → red). Asserts *properties*: per-observable reference selection incl. NAMD-override; scalar
  reference=0-delta & candidate recovers ±known %; zero-ref→None delta no div0; identical RMSF→Pearson 1 + overlay
  points; rigid-shifted frame→shape-RMSD≈0 (Kabsch); field cosine +1/−1 & magnitude-ratio 3; 1-engine→raw no
  agreement; empty→not-ready; missing observable omits its rows; REST start→poll→result + 404.
- **Frontend pins** `frontend/src/ui/shape_compare_card.test.js` (6 pure-helper + 3 wiring tests): fmt/null, table
  view-model column order + reference flag, overlay series order (ref first) + empty, CSV sections/numbers,
  Generate→poll→render fills tables + enables Export, empty-sources reports not-ready without a run, refresh clears.
- **Display-vs-oracle** (one-off Playwright, deleted): drove the REAL card + REAL client against the REAL
  throwaway backend with two synthetic engine sources; scraped the rendered table and asserted it shows the
  backend oracle's `+10.0%` twist delta, `oxdna · ref`, RMSF Pearson `1.000`, and `Reference: shape=oxdna` —
  displayed == oracle. Passed. Standing human-eye check on live cross-engine data filed as **MV-21**.
- **Gates**: oracle 15/15; `just test-frontend` = **2200 passed / 177 files**; `just test` = **4170 passed / 66
  skipped / 1 xfailed** (full suite, no drop — S4's 4155 + these 15 + the field-ref-fix test);
  `ruff check` clean on all touched backend files (repo's 19 pre-existing lint errors in other test files
  untouched, per `feedback_no_bulk_reformat`); `just smoke` green (pre-work) + the one-off display-vs-oracle.
  Fresh-context review: no correctness bugs; math + layer discipline + backend↔frontend shape contract all
  sound. One benign edge flagged (policy field-reference mislabelled when it carries no field data) — FIXED this
  session (field comparison/panel now resolve the reference among field-carrying engines; new test
  `test_field_reference_resolves_among_field_carrying_engines_only`).
- **Comparable prediction gained, not just a run:** the cross-engine comparison built in S3/S4 is now
  GENERATABLE/VIEWABLE/EXPORTABLE — one card turns two engines' descriptor bundles into a scalar-delta table, an
  RMSF-overlay + Pearson/Spearman, an aligned-shape RMSD, and a field-deflection cosine, with PNG/CSV export.
  M-METRIC-CORE is closed; every per-engine emission task (C5/O1/M5/N4) now has a card to feed.

### 2026-07-06 — `O1` oxDNA source bundle → first LIVE card column (M-CANDO-FIELD track)

- **What shipped.** The S5 comparison card had `getSources: () => []` — the machinery existed but no engine fed
  it. O1 wires the FIRST live source: `backend/core/oxdna_shape_source.py::build_oxdna_shape_source(shape_frame,
  core_reference, rmsf_positions?, field?)` — a PURE Physical-layer assembly that core-filters the relaxed frame
  to the rigid dsDNA core (`_filter_to_reference_core` against `core_reference_geometry` — same mask the
  Graphs-&-Metrics card uses, so ssDNA ends drop out), computes `compute_shape_descriptors` (S1) on it, and maps
  `production_rmsf` positions into the card's rmsf-profile shape. Route `GET /oxdna/jobs/{id}/shape-source`
  (routes_oxdna.py) reads the latest relaxed `last_conf` (same frame `/display` shows) + optional trajectory
  RMSF; frontend `getSources` async-fetches the selected job's bundle. `main.js` Δ = 0.
- **Oracle** `tests/test_oxdna_shape_source.py` (**7 tests, fast**), written before the module (imported the
  missing name first → red). Asserts: descriptors == `measure_bundle_twist(core)` on the exact core frame (the
  "matches oxdna_health" property — same locked estimator, self-consistent), core mask drops ssDNA-end columns
  absent from the reference, `rmsf`→`rmsf_nm` remap (None-rmsf dropped), field passthrough, the bundle drops into
  `build_comparison_report` as a ready `oxdna` SHAPE reference (value present, no self-delta), and RED: an empty
  core reference → None descriptors/frame → not a usable column.
- **Review-caught (claim, not bug).** The descriptors are oxDNA's **absolute** twist/bend on the relaxed frame
  (the cross-engine-comparable quantity — oxDNA-abs vs CanDo-abs), which is the RIGHT choice; but my docstrings +
  the MV-21 wording overclaimed they "match the Graphs-&-Metrics twist/curvature". That card plots the
  **differential** (measured − analytic) twist over the *production trajectory* — a different quantity on a
  different frame. Corrected the module + route docstrings and MV-21 so nobody expects the two cards to show
  equal numbers. Code unchanged; the oracle already asserted self-consistency with the estimator, not the graph.
- **Field deferred.** O1 emits `field: None`. A field bundle needs `field_response_profile` with the pre-field
  reference frame + resolved anchor_keys + field vector off a field JOB — a natural follow-up when C2 needs the
  oxDNA field reference. Shape + RMSF (O1's oracle) ship now.
- **Gates.** 7/7 oracle; `just test` 4177 passed / 66 skip / 1 xfail; ruff clean on touched files (the 19-error
  pre-existing debt in OTHER test files untouched, per `feedback_no_bulk_reformat`); vitest 2200; `just smoke`
  green (pre-work). Live-on-real-relaxed-job eyeball = **MV-21** (updated).
- **Comparable prediction gained, not just a run:** the comparison card now renders a REAL oxDNA column — a
  relaxed job's shared shape descriptors + RMSF, core-filtered — instead of an empty source list; the moment a
  second engine (C5 CanDo) lands, the card computes an actual oxDNA-vs-CanDo agreement with no further card work.

## Lessons (anti-patterns banked)

### Banked from O1

- **"Matches oxdna_health" is ambiguous — pin the estimator, not the graph.** The card's descriptor and the
  Graphs-&-Metrics card both derive from `measure_bundle_twist`, but the metrics card reports the DIFFERENTIAL
  (measured − analytic) over the production mean while the shared descriptor reports the ABSOLUTE value on the
  relaxed frame. Same function, different reference + frame → different number. When a task says "match existing
  values within tol", decide WHICH value: the raw estimator output (what cross-engine comparison wants) or the
  differential the existing UI displays. The oracle should assert self-consistency with the estimator on the
  chosen frame — asserting equality to the differential graph would be wrong-by-construction.

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
