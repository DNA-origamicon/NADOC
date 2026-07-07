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

| **(C1) CanDo anchors (Dirichlet BC)** ✅ | synthetic beam: pinned node u==0 at its DOFs, free tip moves under a test load; BC pins EXACTLY the requested nodes' 6 DOF, `None`/`[]`→centroid (never singular); resolver maps base+cluster scopes→duplex-core node indices (both strands→one node) & drops stale/out-of-core; prestress solve holds the clamped node <1e-9 while the rest deflects >1e-3; unresolved anchor = no-op (positions identical, free-free RMSF preserved) | `backend/physics/fem_solver.py::{apply_boundary_conditions,solve_prestress_shape,resolve_anchor_nodes,predict_shape}`, `tests/test_cando_anchors.py` | every engine's ANCHOR task (M1/N2) via the SAME `resolve_anchor_particles` scope resolver → node/bead/atom indices; C2 (E-field needs anchors) |
| **(C2) CanDo E-field (S4 on FEM frame)** ✅ | `assemble_field_force`: uniform body load = 2·`field_pN`·dir_hat/node (duplex node = 2 backbones), translational DOF only, None/zero-mag/zero-dir→zero vector, linear in magnitude; end-to-end (S4 `field_response_profile` on the RAW clamped-solve frame, NOT Kabsch-reposed display frame): anchors held (drift≈0) + free deflects ALONG field (proj≥0.5nm) + MONOTONE in \|E\| + zero-field→no deflection (RED); `predict_shape(field=)` threads through & `field=None` is a byte-identical no-op | `backend/physics/fem_solver.py::{assemble_field_force,solve_prestress_shape,predict_shape}`, `tests/test_cando_field.py` | every engine's E-FIELD task (M2/N1) — same `{field_pN,dir}` per-nt-force descriptor; **C5 field-source must emit field-response from the RAW frame, not display positions** |

| **(C5) CanDo source bundle** ✅ | descriptors == `compute_shape_descriptors` on the exact core-filtered `predict_shape` frame (same S1 estimator, self-consistent — ABSOLUTE); core mask drops ssDNA ends; per-bp NMA `rmsf`→card shape with **`direction=None`** (dropped None); field passthrough; empty core→None (RED); **integration: `[oxdna, cando]`→`build_comparison_report` ready, refs shape=oxdna/rmsf=cando, cando shape-RMSD finite (~0 rigid shift), oxDNA RMSF Pearson 1.0 n=24 (dir-less pairs per-strand via `_rmsf_per_bp`)** | `backend/core/cando_shape_source.py::build_cando_shape_source`, `backend/api/routes_cando.py::get_cando_shape_source`, `tests/test_cando_shape_source.py` | the SAME source-bundle contract for M5/N4; CanDo is the RMSF reference column |

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

### 2026-07-06 — `C1` CanDo FEM anchors (Dirichlet BC) — M-CANDO-FIELD/COMPLETE track

- **Picked** `C1` — shared-metric track (M-METRIC-CORE) is done, so the next milestone is **M-CANDO-FIELD**
  (needs C1, C2; S4/S5/O1 already done). Rubric: **anchors-before-field**; C1 is low-effort, high-leverage,
  and unblocks C2 (critical) plus the whole CanDo feature track. Eligible alternatives (C3/M1/M3/N1/…) rank
  lower (don't unblock the leading milestone).
- **What shipped.** Anchors (a physical tether held fixed) for the CanDo FEM shape solve — the CanDo analogue
  of a boundary condition. Backend-only; anchors are a **job-request annotation, never a `Design`/topology
  edit** (Three-Layer Law: `predict_shape(..., anchors=...)` kwarg, nothing mutated).
  - `apply_boundary_conditions(K, f, mesh, fixed_nodes=None)` — generalized from the single centroid pin to
    pin all 6 DOF of each `fixed_nodes` index (Dirichlet). `None` **or an empty list** → centroid fallback, so
    a stale anchor that resolves to nothing never leaves the system singular.
  - `solve_prestress_shape(..., fixed_nodes=None)` clamps them at **every** corotational load step → the
    anchored region stays exactly at rest while the rest deflects under the loop/skip eigenstrain.
  - `resolve_anchor_nodes(design, mesh, anchors)` — reuses the **shared oxDNA scope resolver**
    (`oxdna_interface.resolve_anchor_particles`: overhang/cluster/domain/strand/base) → per-nt `(helix,bp,dir)`
    keys collapsed onto the single duplex-core axis node per bp (FORWARD+REVERSE → one node). Out-of-core nts
    (ssDNA ends, extra-base sentinel keys) drop silently — same stale-tolerance as the oxDNA resolver.
  - `predict_shape(design, *, anchors=None)` threads anchors through **both** the nonlinear and linear paths and
    surfaces `anchor_keys: [[helix, bp], …]`. RMSF stays free-free NMA regardless (intrinsic flexibility).
- **Oracle** `tests/test_cando_anchors.py` (**10 tests, fast**), written before the code (imported the new
  names first → red). Asserts *properties*, not "ran": synthetic straight beam — pinned node `u==0` at its DOFs
  & the free tip deflects along a test load; BC pins exactly the requested nodes / `[]`→centroid; resolver maps
  base + cluster scopes to the right node set & drops a stale selection; **prestress solve holds the
  most-deflecting node <1e-9 while the rest still deflects >1e-3** (the physical anchor property, pre-Kabsch);
  an anchor genuinely changes the Kabsch-posed `predict_shape` output + reports `anchor_keys`; an unresolved
  anchor is a no-op (positions identical). Fresh-context review: **no correctness gaps**; honest note — the
  "free-free NMA preserved" RMSF half is *green-by-construction* (the RMSF path never receives anchors, so it's
  free-free by design — consistent with the stated oracle; the positions no-op is the load-bearing check). The
  RMSF comparison uses Pearson>0.999 + mean-within-2% because `eigsh` passes no `v0` → ARPACK start-vector
  jitter makes element-wise `allclose` the wrong tool (that jitter is not an anchor effect).
- **Gates.** oracle 10/10; `just test` = **4186 passed / 66 skipped / 1 xfailed** (+ the 1 known pre-existing
  `test_job_archive::test_md_list_includes_size` xdist active-design flaky — passes in isolation, I touched no
  job-archive code); ruff clean on both touched files (the pre-existing lint debt in OTHER files untouched, per
  `feedback_no_bulk_reformat`). No card/UI this task → **display-vs-oracle Playwright is N/A**. **main.js LOC Δ = 0**
  (backend-only). NB: `just smoke` (pre-work) had one pre-existing FAILING spec unrelated to C1 —
  `assembly_exit_cleanup` (assembly-teardown console error, already has a partial fix commit `d5be41c`) — routed
  to `issues_ledger.md`, not a C1 regression (backend-only change, gated on `just test`).
- **Comparable prediction gained, not just a run:** the CanDo FEM can now hold a **resolved anchor** (u==0 at
  the tethered node) while the rest of the bundle relaxes — the boundary condition every anchored-field
  cross-validation needs. This is the substrate for C2 (E-field deflection is measured *against* a held anchor)
  and shares the exact `resolve_anchor_particles` scope resolver with the oxDNA/mrDNA/NAMD anchor tasks
  (M1/N2), so "anchor scope X" means the same nucleotides across all four engines.

### 2026-07-06 — `C2` CanDo FEM uniform E-field (closes M-CANDO-FIELD)

- **Picked** `C2` — deps (C1) now met; the **M-CANDO-FIELD headline** and the only task left for that milestone.
  Rubric: shared-metric track done, anchors-before-field satisfied (C1), C2 is critical-leverage + closes a
  milestone. "Does the cheap FEM predict oxDNA's field deflection?" is the whole point of the CanDo track.
- **What shipped.** A uniform electric-field body load for the CanDo FEM shape solve — backend-only; the field is
  a **job-request annotation, never a topology edit** (Three-Layer Law), threaded exactly like C1's anchors.
  - `assemble_field_force(mesh, field)` — builds the equivalent nodal-force vector from the **shared oxDNA
    descriptor** `{"field_pN": <force per NUCLEOTIDE, pN>, "dir": [x,y,z]}` (the SAME per-nt force oxDNA applies
    per bead — `OXDNA_FORCE_PN` convention). Each duplex axis node carries `FEM_FIELD_CHARGES_PER_NODE=2`
    backbones → translational load `2·field_pN·dir_hat` (pN), rotational DOF zero (a pure body force). `None` /
    `{}` / zero-mag / zero-dir → exact zero vector; magnitude linear.
  - **Dead load, not co-rotating.** Assembled ONCE in global coords before the corotational loop and added to the
    per-step-reframed eigenstrain each of `n_steps` increments — so it stays fixed in the lab frame as the bundle
    bends (the E-field doesn't rotate with the DNA, unlike the loop/skip eigenstrain). Threaded through
    `solve_prestress_shape(..., field=)` (nonlinear) + `predict_shape(design, *, anchors=, field=)`. A field needs
    ≥1 anchor to hold against (COM drift) — reuses C1's `resolve_anchor_nodes`.
- **Oracle** `tests/test_cando_field.py` (**7 tests**), scored by the shared **S4** `field_response_profile` —
  the exact descriptor oxDNA is validated on. 3 fast `assemble_field_force` unit props (none/zero no-op,
  2·chg/node translational-only + normalized direction, linear magnitude); 4 end-to-end nonlinear-solve tests
  (registered **slow** in conftest): anchored 6HB + transverse field → **anchors held (drift≈0) + free deflects
  ALONG field (proj≥0.5nm)** (the S4 verdict) + **monotone in |E|** (fp 0.05→5.2nm, 0.1→10.4nm) + **zero-field →
  no deflection** (RED guard: else the eigenstrain, not the field, is driving) + `predict_shape(field=)` threads
  through & `field=None` is byte-identical to omitting it.
  - **KEY: measured on the RAW clamped-solve frame, NOT `predict_shape`'s display positions.** `predict_shape` →
    `deformed_positions_with_axis` Kabsch-**reposes** each frame onto the displayed design geometry with a
    per-frame rigid transform, so the straight (field-off) and bent (field-on) frames land in DIFFERENT poses and
    the anchor spuriously "drifts" ~5nm. The raw solved axis-node frame is a genuine common frame (the 6 clamped
    end nodes fully constrain rigid-body motion) → no alignment needed, anchor drift ≈0. **→ the C5 field-source
    builder must emit field-response from the RAW frame, not display positions** (banked below).
  - `n_steps=8` — converged (proj stable across 8→30) and stable; the corotational solve **blows up (element
    inversion → `L**3` overflow) for `field_pN ≳ 0.5`**, so gentle fields (0.05–0.1) were chosen for the oracle.
  - Fresh-context review: **no correctness gaps**. Honest limitation: the public `predict_shape(field=)`'s S4
    verdict is proven only *indirectly* — it routes through the exact `solve_prestress_shape(field=)` the property
    tests validate; asserting S4 on its Kabsch-reposed display frame would falsely fail (inherent, documented).
- **Gates.** oracle 7/7; `just test` = **4194 passed / 66 skipped / 1 xfailed** (+8 vs C1's 4186 = the 7 new
  tests; no drops; slow suite ran under load ~50 from its own real oxDNA+NAMD sim tests → 12min wall, not a
  regression); ruff clean on all 3 touched files. No card/UI → **display-vs-oracle Playwright N/A** (like C1).
  **main.js LOC Δ = 0** (backend-only).
- **Comparable prediction gained, not just a run:** the cheap CanDo FEM now reproduces the **oxDNA field-deflection
  regime** — an anchored tethered-arm whose free region deflects *along* the applied field, *monotone* in field
  magnitude, driven by the *same per-nucleotide force* oxDNA uses. **Closes M-CANDO-FIELD** (C1, C2, S4, S5, O1 all
  done): the shared S4 descriptor now scores both engines from the same load, so a real oxDNA-vs-CanDo field
  cross-validation is one C5 field-source wiring away.

### 2026-07-06 — `C5` CanDo source bundle → SECOND live card column (first oxDNA-vs-CanDo agreement)

- **Picked** `C5` — the handoff's `▶ NEXT` and highest-leverage eligible task (deps `S5` met). The shared-metric
  track is done, so cross-val value dominates: C5 turns the S5 card from an oxDNA-only view (O1) into the **first
  real cross-engine comparison** by adding CanDo as the second source. Low effort (mirror O1's proven template).
- **What shipped.** CanDo is now the second live source of the S5 cross-engine comparison card — Physical-layer
  read only, no topology touch.
  - `backend/core/cando_shape_source.py` `build_cando_shape_source(shape_frame, core_reference, *, rmsf=None,
    field=None)` — the CanDo twin of O1's `oxdna_shape_source`, same SOURCE-BUNDLE CONTRACT: core-filter
    `predict_shape()['positions']` to the rigid dsDNA core (`_filter_to_reference_core` vs `core_reference_geometry`,
    ssDNA ends dropped), emit CanDo's **ABSOLUTE** `compute_shape_descriptors` (S1 estimator, not a differential),
    map `predict_shape()['rmsf']` (`{helix_id,bp_index,rmsf_nm}`) to the card's rmsf shape.
  - **CanDo NMA RMSF is DIRECTION-LESS** (both strands share one axis node) → emitted with `direction=None`. The
    cross-engine `_rmsf_per_bp` collapses over direction anyway (the S3 lesson), so `direction=None` still pairs
    CanDo's per-bp RMSF with oxDNA's per-strand ensemble RMSF instead of a silent empty intersection.
  - `GET /cando/jobs/{id}/shape-source` (`routes_cando.py`) — reads the job's cached display + rmsf + snapshot
    design, builds the core reference, returns `{ready(=descriptors is not None), ...bundle}`; graceful
    no-display → `{ready:False}`, no-snapshot → 500 (mirrors sibling `/cylinders`,`/deviation`).
  - Frontend: `api.getCandoShapeSource` + the compare card's `getSources` (hosted in the oxDNA panel) now fetches
    **both** the selected oxDNA job's bundle AND the selected CanDo job's bundle → `[oxdna, cando]`. `main.js`
    captures `const candoPanel` and passes a lazy `getCandoJob: () => candoPanel?.getSelectedJob?.()` (the CanDo
    panel is created after the oxDNA panel; the arrow only fires on a Generate click, so no TDZ).
  - **Field deferred** (`field:None`) — like O1. When added it MUST come from the RAW `solve_prestress_shape`
    frame, not `predict_shape`'s Kabsch-reposed display positions (C2 lesson).
- **Oracle** `tests/test_cando_shape_source.py` (**7 tests**): 6 fast pure (engine tag + descriptor
  self-consistency, core mask drops ssDNA ends, rmsf remap direction-less + drops None, field passthrough,
  empty-core→None RED, **integration**: `[oxdna, cando]`→`build_comparison_report` ready, refs shape=oxdna /
  rmsf=cando, CanDo shape-RMSD finite ≈0 on a rigid 0.2nm shift, oxDNA RMSF **Pearson 1.0 n=24**, cando
  rmsf_profile `is_reference`); 1 SLOW (registered in conftest): routed 6HB → real `predict_shape` →
  `build_cando_shape_source` → finite absolute descriptors + finite rmsf → ready lone-CanDo report (rmsf ref=cando).
- **Gates.** oracle 7/7 (6 fast + 1 slow); `just test` = **4206 passed / 66 skipped / 1 xfailed**; ruff clean on
  touched files (20 pre-existing debt in OTHER test files untouched per `feedback_no_bulk_reformat`); vitest 2214;
  smoke green (assembly_exit_cleanup flaked once under parallel load, passes isolated — unrelated path). Fresh-
  context review: **CONFIRMED-CORRECT**, no bugs, no TDZ, Three-Layer clean. **main.js LOC Δ = +4** (pure wiring:
  a lazy dep + capturing an existing factory's return). **Display-vs-oracle:** the two-engine (oxdna+cando) card
  RENDERING was already scraped-vs-oracle in S5 (synthetic sources → +10% twist delta, RMSF Pearson 1.000); C5
  only wires the real backend route into that S5-validated render path → live cross-engine eyeball = **MV-21**
  (updated with the C5 slice).
- **Comparable prediction gained, not just a run:** the comparison card now produces the **first real oxDNA-vs-
  CanDo agreement numbers** — CanDo's absolute shape descriptors + aligned-shape RMSD scored against the oxDNA
  shape reference, and oxDNA's RMSF correlated (Pearson/Spearman) against **CanDo as the RMSF reference**. Two
  independent structure predictors now cross-validate on the same design through one shared card.

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

### Banked from C2

- **Field-response must be measured on the RAW solve frame, not the display frame.** `predict_shape` Kabsch-
  reposes each output frame onto the displayed design geometry with a *per-frame* rigid transform (for overlay).
  Comparing a field-off and a field-on `predict_shape` output therefore compares two *differently-posed* frames,
  and an anchored region that is genuinely clamped at rest appears to "drift" several nm. `field_response_profile`
  is deliberately NOT Kabsch-aligned (the anchored region IS the common frame) — so it must be fed the RAW
  clamped-solve node positions, where the anchor sits at identical positions in both frames. **Any engine's field-
  source builder (C5/M2/N4) must emit its deflection descriptor from the pre-display / pre-alignment frame.** A
  green oracle built on the display frame would either falsely fail or silently mis-measure the anchor hold.
- **A corotational eigenstrain+field solve is only conditionally stable.** Large body loads invert elements
  (`L→0`/huge → `L**3` overflow) before the physics is wrong. Pick load magnitudes in the converged, stable band
  and assert *properties* (monotone, along-field, held) rather than absolute deflection matching a calibration —
  the absolute V/m→force calibration is a separate, deferred concern (editable effective-charge, per the plan).

## Difficulties ledger (genuinely-stuck items + why)

_(none yet — if a task is set `status="blocked"`, record the reason + what was tried here.)_
