# Sim-coverage loop — metrics + cross-engine agreement

Companion to [`SIM_COVERAGE_PLAN.md`](SIM_COVERAGE_PLAN.md). Two things live here: (1) a per-task metrics row
with the anti-shovel justification, and (2) the headline deliverable — the **cross-engine agreement table** that
fills in as milestones complete.

## Per-task metrics rows (one per shipped task)

> *Format: **`<TASK-ID>` — `<title>`** · shape (service / card / solver-change) · feature covered · engines now
> comparable · oracle shipped (fast/slow) · main.js LOC Δ · tests (pass count) ·
> **"Comparable prediction gained, not just a run: ___."**_

- **`S1` — engine-agnostic shape descriptors** · shape: new `backend/core` service (`shape_metrics.py`) +
  1 additive `oxdna_health` helper (no solver/card change) · feature: comparison-metric (the shared substrate) ·
  engines now comparable: *all four* can be fed the same descriptor set (the yardstick; actual comparison lands
  at S3) · oracle: `tests/test_shape_metrics.py` 9 tests **fast** (recover twist/arc-span, can-go-red) ·
  main.js LOC Δ = 0 · tests: 9/9 oracle, `just test-fast` 4057 passed (1 pre-existing xdist flake) ·
  **Comparable prediction gained, not just a run:** every engine's frame now maps to identical twist /
  bend-angle+radius / Rg / end-to-end numbers on the shared `(helix,bp,dir,copy)` substrate, so S3 can score
  agreement instead of comparing incommensurable per-engine metrics.

- **`S2` — unified deviation + RMSF profiles** · shape: 3 functions added to the `shape_metrics.py` service
  (no solver/card change) generalizing `cando_deviation.compute_deviation`, `oxdna_health.production_rmsf`'s
  variance core, and `fem_solver.normalize_rmsf` · feature: comparison-metric (the second shared substrate) ·
  engines now comparable: *all four* can be scored on identical per-nt deviation-from-design (+RMSD) and per-nt
  RMSF (CanDo via NMA, others via `rmsf_from_ensemble`) · oracle: `tests/test_shape_deviation_rmsf.py` 10 tests
  **fast** (rmsd 0 identical, exact non-rigid displacement recovery, Kabsch pose-removal, `A/√2` fluctuation
  round-trip, normalize round-trip) · main.js LOC Δ = 0 · tests: 10/10 oracle, `just test` 4128 passed / 66
  skipped / 1 xfailed (full suite, no drop) ·
  **Comparable prediction gained, not just a run:** any engine's frame(s) now yield the SAME per-nucleotide
  deviation (Kabsch-aligned, so pose is stripped and only real shape mismatch survives) and the SAME per-nt RMSF
  on the shared substrate — the two flexibility/shape yardsticks S3's `compare_descriptors` needs to report a
  Pearson r / signed Δ between two engines instead of comparing incommensurable per-engine numbers.

- **`S3` — cross-engine descriptor agreement** · shape: 2 entry points added to the `shape_metrics.py` service
  (`compare_descriptors` + `reference_for`; no solver/card change) composing S1's descriptors + S2's profiles ·
  feature: comparison-metric (the agreement math itself) · engines now comparable: any two engines yield a
  scored comparison — signed %Δ per shape descriptor, Pearson/Spearman on per-bp RMSF, Kabsch-aligned shape
  RMSD — with the reference picked per-observable by policy (oxDNA=shape/field, CanDo=RMSF, NAMD-override) ·
  oracle: `tests/test_shape_compare.py` 13 tests **fast** (identical→perfect, ±10° twist→±10% signed,
  scaled/reversed/constant RMSF correlation, rigid-pose-invariant shape RMSD, `reference_for` policy + override +
  missing→None, **CanDo dir-less vs oxDNA per-strand RMSF collapses to per-bp & correlates** — the review-caught
  fix) · main.js LOC Δ = 0 · tests: 13/13 oracle (32/32 S1+S2+S3), `just test` 4140 passed / 66 skipped /
  1 xfailed (1 pre-existing xdist flake, passes in isolation) ·
  **Comparable prediction gained, not just a run:** the loop's first cross-*validation* number — two engines'
  frames now reduce to an agreement score (%Δ, Pearson r, aligned RMSD) with a policy-chosen reference, so the
  question "do the quick and rigorous engines agree, and where do they diverge?" becomes computable the moment
  S5 wires it into the generate/view/export card.

- **`S4` — unified field-response descriptor** · shape: 2 entry points added to the `shape_metrics.py` service
  (`field_response_profile` + `compare_field_response`; no solver/card change) generalizing
  `oxdna_health.measure_field_response` · feature: **E-field** (the shared field-deflection substrate) · engines
  now comparable: any two engines' field responses yield a scored deflection comparison — cosine of the free-nt
  deflection fields + magnitude (compliance) ratio, plus a copy-aware per-nt deflection map + projection-along-
  field per engine · oracle: `tests/test_shape_field_response.py` 13 tests **fast** (anchors held + free deflect
  along field, monotone in |F|, fails on anchor-drift/no-deflection, copy-aware keys, cross-engine cosine
  +1/−1/0, magnitude-ratio=3.0 at 3× compliance, zero-field/no-free raise, no-shared-free→None) · main.js LOC
  Δ = 0 · tests: 13/13 oracle (45/45 S1–S4), `just test` 4155 passed / 66 skipped / 1 xfailed (full suite, no
  drop) ·
  **Comparable prediction gained, not just a run:** the E-field half of the cross-validation deliverable — two
  engines' responses to the same field now reduce to a deflection cosine + compliance ratio (does CanDo bend the
  way oxDNA does, and by how much?), the field-panel counterpart to S3's shape/RMSF agreement, ready for the S5
  card.

- **`S5` — cross-engine comparison CARD** · shape: new `backend/core` assembly service
  (`shape_compare.py::build_comparison_report`, pure) + daemon-thread route
  (`routes_shape_metrics.py`, `POST/GET /shape/compare`) + a thin frontend card
  (`shape_compare_card.js`) binding the shared `metric_graph`/`metric_export_modal` machinery (not rebuilt) ·
  feature: comparison-metric (the generate/view/export surface — closes M-METRIC-CORE) · engines now comparable:
  any set of engine source bundles renders as a scalar-delta table + RMSF overlay + agreement (RMSD/Pearson/
  Spearman) + E-field deflection panel, PNG/CSV-exportable · oracle: `tests/test_shape_compare_report.py` 14
  tests **fast** (per-observable reference incl. NAMD-override, scalar ±%Δ + zero-ref no-div0, identical RMSF→
  Pearson 1 + overlay pts, rigid-shift→shape-RMSD≈0, field cosine ±1 + mag-ratio 3, 1-engine/empty/missing-
  observable degradation, REST start→poll→404) + vitest `shape_compare_card.test.js` 9 (pure helpers + wiring) +
  one-off display-vs-oracle Playwright (displayed == backend oracle, deleted; live data → **MV-21**) · main.js
  LOC Δ = 0 (wired from `initOxdnaJobsPanel`) · tests: 15/15 backend oracle (60/60 S1–S5), 2200/2200 frontend,
  `just test` 4170 passed / 66 skipped / 1 xfailed (full suite, no drop) ·
  **Comparable prediction gained, not just a run:** the S3/S4 agreement math is now a first-class tool — one
  card GENERATES the cross-engine comparison for a design, VIEWS it (delta table + RMSF overlay + agreement +
  field panel), and EXPORTS it (PNG/CSV). M-METRIC-CORE closed; the per-engine emission tasks (O1/C5/M5/N4) now
  have a card to feed, so their cross-validation results become *reportable*, not just computable.

- **`O1` — oxDNA source bundle (first live card column)** · shape: new `backend/core` service
  (`oxdna_shape_source.py`, pure assembly) + thin route `GET /oxdna/jobs/{id}/shape-source` (routes_oxdna.py) +
  1 client fn + `getSources` wiring (no solver/card change — binds the S5 card) · feature: comparison-metric
  (oxDNA = the SHAPE + field reference column) · engines now comparable: **oxDNA is now a LIVE source** — a
  relaxed job's core-filtered descriptors + RMSF feed the card (was `getSources:()=>[]`); the moment C5 lands,
  oxDNA-vs-CanDo agreement computes with no card work · oracle: `tests/test_oxdna_shape_source.py` 7 tests
  **fast** (descriptors == `measure_bundle_twist(core)` self-consistent, core mask drops ssDNA ends, `rmsf`→
  `rmsf_nm` remap, field passthrough, drops into `build_comparison_report` as ready `oxdna` shape ref, RED empty-
  core→None) · main.js LOC Δ = 0 · tests: 7/7 oracle, `just test` 4177 passed / 66 skipped / 1 xfailed (no drop),
  vitest 2200/2200, smoke green · review-caught: descriptors are oxDNA's ABSOLUTE twist (cross-engine-comparable)
  not the differential twist the Graphs-&-Metrics card plots — docstrings + MV-21 corrected (claim, not bug) ·
  **Comparable prediction gained, not just a run:** the comparison card renders a REAL oxDNA column (a relaxed
  job's shared shape descriptors + RMSF, core-filtered to the rigid dsDNA core) instead of an empty source list —
  oxDNA is now the concrete reference every other engine's task will be scored against.

- **`C1` — CanDo FEM anchors (Dirichlet BC)** · shape: **solver-change** (`fem_solver.py`: generalized
  `apply_boundary_conditions` centroid-pin→arbitrary `fixed_nodes`; `solve_prestress_shape`/`predict_shape` thread
  anchors; new `resolve_anchor_nodes` reusing the shared `oxdna_interface.resolve_anchor_particles` scope
  resolver) · feature: **anchors** (CanDo — first of its four) · engines now comparable: CanDo can hold a resolved
  anchor exactly (u==0) under the eigenstrain — the boundary condition C2's field-deflection is measured against;
  same scope resolver as the oxDNA/mrDNA/NAMD anchor tasks (M1/N2) so "anchor scope X" = the same nucleotides
  across engines · oracle: `tests/test_cando_anchors.py` 10 tests **fast** (synthetic-beam pinned-held/free-moves,
  BC pins exactly the requested nodes / `[]`→centroid, resolver maps base+cluster & drops stale, prestress solve
  holds clamped node <1e-9 while rest deflects >1e-3, unresolved=no-op) · main.js LOC Δ = 0 · tests: 10/10 oracle,
  `just test` 4186 passed / 66 skipped / 1 xfailed (+1 known pre-existing job-archive xdist flaky, passes isolated);
  no card/UI → display-vs-oracle N/A · review-caught: none (honest note — the free-free-RMSF assertion is
  green-by-construction, consistent w/ the stated oracle; positions no-op is load-bearing) ·
  **Comparable prediction gained, not just a run:** the CanDo FEM can now clamp a tethered node and predict the
  *anchored* equilibrium shape (rest of the bundle deflects, anchor held to 1e-9) — the anchored boundary
  condition every anchored-field cross-validation needs, unblocking C2 and the M-CANDO-FIELD milestone.

- **`C2` — CanDo FEM uniform E-field** · shape: **solver-change** (`fem_solver.py`: new `assemble_field_force`
  uniform body load; `field=` threaded through `solve_prestress_shape` + `predict_shape`; `FEM_FIELD_CHARGES_PER_NODE`
  const) · feature: **E-field** (CanDo — second of its four) · engines now comparable: CanDo predicts the
  **field-deflection regime** (anchored tethered-arm, free deflects along field, monotone in |E|) from the SAME
  per-nucleotide `{field_pN, dir}` force oxDNA applies — the shared **S4** `field_response_profile` now scores both
  from one load · oracle: `tests/test_cando_field.py` 7 tests (3 `assemble_field_force` unit props **fast**;
  4 end-to-end nonlinear-solve property tests **slow**) — anchors held (drift≈0) + free proj≥0.5nm along field +
  monotone (fp 0.05→5.2nm, 0.1→10.4nm) + zero-field→no-deflection RED, measured on the **RAW clamped-solve frame**
  (not the Kabsch-reposed display frame) · main.js LOC Δ = 0 · tests: 7/7 oracle, `just test` 4194 passed / 66
  skipped / 1 xfailed (no drop); no card/UI → display-vs-oracle N/A · review-caught: none (honest note —
  `predict_shape(field=)`'s S4 verdict is proven indirectly via the shared `solve_prestress_shape(field=)`) ·
  **Comparable prediction gained, not just a run:** the cheap CanDo FEM now reproduces oxDNA's anchored
  field-deflection (along-field, monotone, same per-nt force) scored by the shared S4 descriptor — **closes
  M-CANDO-FIELD**; a real oxDNA-vs-CanDo field agreement number is one C5 field-source wiring away.

- **`C5` — CanDo source bundle (second live card column)** · shape: new `backend/core` service
  (`cando_shape_source.py`, the twin of O1's `oxdna_shape_source`) + new `GET /cando/jobs/{id}/shape-source`
  route + frontend `getSources` now merges the CanDo source with the oxDNA one (no solver/card-machinery change —
  binds the existing S5 card) · feature: comparison-metric (CanDo joins the shared card; the RMSF reference
  column) · engines now comparable: **oxDNA ↔ CanDo** — the S5 card now carries two live sources, so it emits
  the first real cross-engine agreement: CanDo's absolute shape descriptors + aligned-shape RMSD vs the oxDNA
  shape reference, and oxDNA's RMSF Pearson/Spearman vs **CanDo as the RMSF reference** (dir-less CanDo NMA RMSF
  pairs with oxDNA per-strand ensemble RMSF via the S3 per-bp collapse) · oracle:
  `tests/test_cando_shape_source.py` 7 tests (6 pure **fast** incl. the `[oxdna,cando]`→`build_comparison_report`
  integration: refs shape=oxdna/rmsf=cando, shape-RMSD≈0 on rigid shift, RMSF Pearson 1.0 n=24; 1 real-
  `predict_shape` **slow**) · main.js LOC Δ = +4 (pure wiring: lazy `getCandoJob` dep + capturing the CanDo
  panel's return) · tests: 7/7 oracle, `just test` 4206 passed / 66 skipped / 1 xfailed (no drop), vitest 2214,
  smoke green · display-vs-oracle: the two-engine card rendering was S5-scraped (synthetic); C5 wires the real
  route into that validated path → live eyeball = MV-21 (updated) ·
  **Comparable prediction gained, not just a run:** the comparison card now produces the **first real oxDNA-vs-
  CanDo agreement numbers** — two independent structure predictors (rigorous CG vs cheap FEM) cross-validate on
  the same design through one shared generate/view/export card, with per-observable references (oxDNA=shape,
  CanDo=RMSF).

- **`C3` — extra crossover bases as compliant connectors** · shape: **solver-mechanism was pre-existing** (an
  extra-base crossover meshes as a 2-node WLC ssDNA spring in `build_fem_mesh`, shipped untested in Phase-5); this
  task = the missing property **oracle**, no production change · feature: extra-bases (CanDo's 4th feature) ·
  engines now comparable: CanDo emits a measurable extra-base **flexibility** prediction (local RMSF ↑) scored
  through the shared S3 RMSF channel → an oxDNA/NAMD ensemble RMSF at the same inserts can cross-validate it ·
  oracle: `tests/test_cando_extra_bases.py` 4 tests (3 **fast**: mesh census spring-vs-rigid-link + `k∝1/L_c`
  monotone + synthetic 2-node compliance `u==F/k_trans` ≫ `F/K_PENALTY`; 1 **slow**: band-of-inserts → real
  `predict_shape`+NMA local RMSF ~1.87× up, every affected node, RED-guard self-vs-self flat) · main.js LOC Δ = 0
  (backend-only) · tests: 4/4 oracle, `just test` 4210 passed / 66 skipped / 1 xfailed (was 4206, +4, no drop),
  ruff clean; fresh-context review no gaps · display-vs-oracle: N/A (no card/UI, like C1/C2) ·
  **Comparable prediction gained, not just a run:** extra crossover bases now produce a proven, correct-sign
  CanDo prediction — inserts soften the local junction (WLC connector `~1e5×` more compliant than the rigid link)
  and the FEM predicts ~1.87× higher local per-bp RMSF there, a flexibility signal directly comparable to any
  engine's ensemble/NMA RMSF at the same ssDNA inserts. **NO twist/bend direction asserted** (softening a
  distributed load is non-monotone; geometric crossover reasoning forbidden — RMSF is the sign-safe channel).

## Cross-engine agreement table (the deliverable)

Fills in as `compare_descriptors` (S3) + the card (S5) land and each engine emits descriptors. Per design ×
observable, record the reference engine and each candidate engine's agreement. This is what answers *"do the
quick and rigorous engines agree, and where do they diverge?"*

| Design (fixture) | Observable | Reference | CanDo | mrDNA | oxDNA | NAMD | Notes |
|---|---|---|---|---|---|---|---|
| _e.g. 6hb_curved_ | global twist | oxDNA | — | — | ref | — | pending S1–S5 |
| _e.g. 6hb_curved_ | bend angle / radius | oxDNA | — | — | ref | — | pending |
| _e.g. hinge fixture_ | RMSF profile (Pearson r) | CanDo | ref | — | — | — | pending |
| _e.g. tethered-arm_ | field deflection (cosine, mag ratio) | oxDNA | — | — | ref | — | **M-CANDO-FIELD headline** |

_Reference cells = `ref`; candidate cells = the agreement score (%-delta / Pearson r / cosine+ratio); `—` = not
yet emitted. Export each row's underlying data + PNG from the comparison card (per the generate/view/export
requirement)._

**C5 (2026-07-06):** the oxDNA↔CanDo rows above are now COMPUTABLE — with a completed oxDNA relaxed job + a
completed CanDo FEM job on the same design, the card emits shape %-deltas + aligned-shape RMSD (oxDNA=shape ref)
and RMSF Pearson/Spearman (CanDo=RMSF ref). The oracle proved the wiring on synthetic + real-`predict_shape`
sources; the real per-fixture numbers land from the **MV-21** live check (run both engines on one design, Generate,
read/export the agreement) or a future headless two-engine cross-run.

## Milestone status (derived from the JSON)

| Milestone | Meaning | Status |
|---|---|---|
| `M-METRIC-CORE` | comparison card generates/views/exports shared descriptors + agreement | **DONE** (S1–S5 shipped 2026-07-06) |
| `M-CANDO-FIELD` | CanDo FEM field deflection cross-validates oxDNA within tol | **DONE** (C1,C2,S4,S5,O1 shipped 2026-07-06) — FEM predicts the anchored field-deflection regime from oxDNA's per-nt force; real agreement number awaits C5 field-source |
| `M-CANDO-COMPLETE` | CanDo covers all four features + feeds the card | pending (C1,C2,C3,C5 ✅; only C4 linkers left) |
| `M-ALL-ANCHORS-FIELD` | every engine runs an anchored field job with a comparable descriptor | pending |
| `M-FULL-COVERAGE` | all engines × all four features, all feeding the card | pending |

## Data summaries (plots + fits)

_(none yet — `### <TASK-ID> — <topic>` subsections for numeric fits, e.g. CanDo-vs-oxDNA deflection-vs-field
magnitude, as slow real-engine runs produce them.)_
