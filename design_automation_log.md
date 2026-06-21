# design-automation extraction log — metrics, oracle catalog, lessons, difficulties

Sibling of `backend_router_extraction_log.md` / `issues_fix_log.md`. The backlog + protocol + handoff live
in **`design_automation_backlog.md`**; this file carries the durable state a cold session needs: the
**oracle catalog** (validation building blocks to mirror), the **metrics rows** (one per shipped AF item,
with the mandatory justification line), the **lessons** (anti-patterns banked), and the **difficulties
ledger** (genuinely-stuck items + why).

---

## Conventions

- One AF item (or one phase) per session, per commit. Commit message: `feat(automation): <op> + <oracle>`.
- The pass criterion is the **validation augment**, never "a wrapper exists" (see the backlog's anti-shovel
  contract). Every row below ends with **"Validation gained, not just a passthrough: ___."**
- New code lands in `headless_build.py` / a new `headless_*_build.py` / `backend/core`. **Never** in
  `crud.py` / `assembly.py` / `main.js`. Cite the god-file LOC Δ (must be flat-or-lower) in the row.
- `backend/core` imports nothing from `backend/api`. Wrappers run the *same* service the route runs — they
  do not re-implement it.

## How to check headless coverage (the probe)

Before picking an item, see what's already wrapped vs. what has only a route:

```bash
# routes defined in the backend:
rg -n '@router\.(get|post|patch|put|delete)\("' backend/api/ | rg -o '"/[^"]+"' | sort -u
# wrappers that exist today:
rg -n '^def |^    def ' backend/api/headless_build.py
# is a given op UI-wired (worth wrapping) or dead (delete candidate)?
rg "<url-fragment>" frontend/src/api/
```

(AF-1 turns this into `headless_coverage_report()` so it stops being a manual grep.)

---

## Oracle catalog — the validation building blocks (MIRROR THESE; don't reinvent)

Every AF item must ship a validation augment that is one of these forms or a faithful new instance of one.
Pulled from the 2026-06-16 audit; each is a *proven* pattern already green in the suite.

| Oracle / pattern | Pins | File(s) | Reuse for |
|---|---|---|---|
| `_canonical_topology(design)` | id/order-independent design fingerprint (helices by grid_pos; strands by grid_pos+bp-range+direction) | `tests/test_section_router.py` | round-trip equality for ANY headless build (AF-1 promotes it shared) |
| `validate_design(design)→ValidationReport` | no unresolved nicks, strand-position consistency, domain count | `backend/core/validator.py` | a "build is well-formed" gate on every wrapper |
| `derive_periodic_delta(design)` | rigid repeat transform (Kabsch on axis geom; pure axial translate, no spiral); `det(R)=+1` | `backend/core/periodic_polymer.py`; `tests/test_periodic_polymer.py` | polymerize / periodic / belt seam geometry (AF-9) |
| `solve_closing_curvature` / `closure_residual` | κ that closes an N-copy ring to <0.5°/<0.5 nm | `tests/test_periodic_polymer.py` | bend-by-curvature oracles (AF-6) |
| circle circularity oracle (`circularity_spread`, `column_lengths`, `fit_radius`) | disc profile spread <0.5 nm; even symmetric trim; ≥16 bp floor | `backend/core/circle_primitive.py`; `tests/test_circle_primitive.py` | parametric primitives (AF-4) |
| `derive_placement_spec(design)` | footprint cells + per-cell bp + anchor from feature log | `backend/core/primitive_catalog.py`; `tests/test_primitive_placement.py` | placement / continuation specs (AF-5) |
| section-router gap metrics (`intertooth_gap_extension`, `min_per_gap_clearance`, `_scaffold_coverage`) | multi-section routing geometric clearance | `tests/test_section_router.py`; `backend/core/seamed_router.py` | multi-section / irregular design routing |
| scaffold invariants (`_active_scaffolds`, matched-ends far-translate, seamless N−1 crossovers) | single active scaffold; polymerization-ready junctions | `tests/test_seamed_router.py`, `test_seamless_router.py` | any scaffold-routing wrapper |
| cadnano round-trip (`import_cadnano` ↔ export; helix-id encodes row/col) | external-format parity | `backend/core/cadnano.py`; `tests/test_cadnano.py` | import/export wrappers |
| atomistic round-trip (CG↔all-atom, RMSD<0.005 Å) | coarse→atom fidelity | `tests/test_atomistic_round_trip.py` | structural-export wrappers |
| feature-log round-trip | log entry shape/params/revertability survive JSON | `tests/test_feature_log_*` | any feature-logged (revertable) op |
| conftest builders (`make_teeth/6hb/18hb/mini_hinge_design`) | feature-log replay reconstructs a fixture's canonical topology | `tests/conftest.py`; `tests/test_section_router.py` | the build_fn input to `assert_roundtrip_stable` |
| `overhang_candidate_error` / `valid_overhang_sites` | geometric feasibility of an overhang placement | `backend/core/lattice.py`; `tests/conftest.py` | overhang wrappers |
| design-geometry kernel (`_geometry_for_design`, `_strand_nucleotide_info`) | nucleotide position + 5′/3′ terminus convention | `backend/core/design_geometry.py`; `tests/test_design_geometry_core.py` | geometry-level assertions |
| `assert_binding_resolves` (AF-9) | a metadata-only cross-part relation's endpoints resolve to live targets (survives round-trip; the gap `canonical_assembly` can't see) | `tests/automation_harness.py` | any metadata-only cross-part relation (overhang connections next) |
| `assert_instances_on_grid` / `assert_instances_on_ring` (AF-10) | placed instance origins form an exact regular lattice (grid: count + even pitch + every cell; ring: on-radius + even `360°/n` step), measured on placed transforms, non-degeneracy guard | `tests/automation_harness.py` | any parametric instance-layout (radial-facing layouts, AF-11 DSL layout specs) |
| `assert_spec_matches_calls` (AF-11) | a declarative build-spec is lowered to the SAME canonical structure as the equivalent hand-call wrapper sequence (`canonical_topology` design / `canonical_assembly` assembly), non-emptiness guard; doubles as the spec→fingerprint golden pin | `tests/automation_harness.py` | any interpreter/DSL/codegen that claims to be sugar over existing ops (AF-11 grammar growth) |
| `assert_cluster_translated` (AF-15) | a cluster's DISPLAY-layer rigid-TRANSLATION pose actually shifts the cluster's helix geometry by the exact vector (read via `deformed_helix_axes`), only the cluster moves, `‖T‖>min` guard; the load-bearing pin where `canonical_topology` is blind to the pose overlay | `tests/automation_harness.py` | any cluster/group pose op that is a geometric overlay outside the strand graph (cluster transforms, plate layout) — measure the placed geometry, don't trust round-trip |
| `assert_edges_collinear` (AF-15 P2) | a cluster's OBB edge shares one infinite line with a target edge/world line after the alignment solver — parallel-or-antiparallel directions (within `tol_deg`) AND both src endpoints on the target line (within `tol_nm`), recomputed on the POSED geometry; direction-AGNOSTIC, non-degeneracy guard | `tests/automation_harness.py`; `backend/core/cluster_obb.py` | any rigid-body edge/axis alignment (AF-14 joint-axis placement, the 4-bar parallelogram capstone) |
| OBB equivariance `OBB(g·design)=g·OBB(design)` (AF-15 P2) | the cluster OBB frame rotates WITH the cluster (half preserved, axes rotate, centre moves) — so a named edge/corner refers to the same physical feature before/after a pose; PCA cross-section frame + **positional** sign anchor (NOT a value-argmax, which ties on symmetric corners) | `backend/core/cluster_obb.py`; `tests/test_cluster_obb.py::test_obb_is_equivariant` | any named-feature picker on a posed rigid body (AF-14 corner/edge joint anchors) |
| `assert_joint_on_hull_corner` (AF-14 P1) | a revolute joint's world axis (re-derived from cluster-LOCAL storage via `_local_to_world_joint`, so it also pins the route's world→local→world round-trip on a posed cluster) lies along a named OBB edge / passes through a named corner of the independently recomputed OBB; direction-AGNOSTIC, non-degeneracy guard | `tests/automation_harness.py`; `backend/core/cluster_obb.py` (`hull_prism_axis` + `OBB.face_normal`) | any axis/feature anchored on a named OBB element (AF-14 P2 ROM candidates, the 4-bar capstone joints) |
| `assert_range_of_motion` (AF-14 P2) | a revolute joint's collision-free swing about a world axis equals the expected magnitude (swept OBB–OBB SAT, `_obb_intersect` 15-axis + per-step scan + bisection, OBBs padded by helix radius); total two-sided θ⁺+θ⁻ clamped to the joint limits, direction-AGNOSTIC; physical-bound guard + can-go-red (no-obstacle→full limit, obstacle in path strictly reduces) | `tests/automation_harness.py`; `backend/core/cluster_obb.py` (`obb_sweep_rom`/`cluster_range_of_motion`/`rank_joint_candidates`) | any swept-rigid-body clearance / kinematic-mechanism DOF check (the 4-bar parallelogram capstone, AF-12 linkage mobility) |
| `assert_parallelogram_linkage` + `grubler_mobility` (capstone) | an ASSEMBLED multi-cluster mechanism is a valid parallelogram four-bar linkage: closed quadrilateral (adjacent bars share an OBB corner, enclosed area > min — non-degeneracy guard) + opposite sides parallel-and-equal + Grübler/Kutzbach planar mobility == expected DOF (`3(n−1)−2·lower−higher`) + every hinge movable (nonzero swept-OBB ROM vs. the non-pinned bars); direction-AGNOSTIC; can-go-red on wrong joint count (mobility≠1) or unarranged bars (no shared corner) | `tests/automation_harness.py`; `backend/core/cluster_obb.py` (`grubler_mobility`) | any composed linkage / mechanism (AF-12 linkage layer); `grubler_mobility` reusable for any planar mechanism's DOF |
| `assert_cluster_in_feature_log` (AF-16) | a logged cluster-creation is recorded: exactly one `cluster_create` feature-log entry for the cluster, naming its exact helix set + name; the load-bearing pin where `canonical_topology` is blind to clusters (the loop/skip / deformation / pose blind-spot, 4th instance), so only the feature-log entry proves the grouping persisted across a `.nadoc` round-trip; can-go-red on an unlogged build (no entry) or a mismatched helix set | `tests/automation_harness.py`; `backend/core/models.py` (`ClusterCreateLogEntry`) | any feature-logged grouping/overlay op whose effect is invisible to the strand-graph fingerprint (cluster create, future group/layout log entries) |
| `assert_recommended_hinge` (AF-14 P3) | the #1 of a cluster's ranked hinge-edge recommendations is NOT parallel to the helical (`w`) axis (a fold, not a barrel-roll), is the LONGEST such non-axial edge, and is corner-anchored (stored `axis_origin` coincides with an edge endpoint, not the midpoint) — all re-measured on the independent equivariant OBB; direction-AGNOSTIC; can-go-red on an axial edge ranked first or a midpoint anchor | `tests/automation_harness.py`; `backend/core/cluster_obb.py` (`recommend_hinge_joints`) | any heuristic feature-ranker on an OBB (hinge/anchor recommenders); the corner-vs-midpoint anchor check reusable for any "named point on a named edge" placement |
| `assert_fully_sequenced` (full-sequencing feature) | a design carries a complete, *correct* sequence: zero undefined bases (same `count_undefined_bases` gate every export / `create_oxdna_job` path enforces, reference strands excluded) AND every scaffold-paired staple base is the `complement_base` of its scaffold base (walked independently of the assignment code, so a wrong-base fill fails, not just an `'N'`); non-vacuity guards on both; can-go-red on an unsequenced design or a corrupted staple base | `tests/automation_harness.py`; `backend/api/headless_build.py` (`full_sequence`/`assign_staple_sequences`) | any op that must leave a design fully + correctly sequenced (export readiness, the AF-13 oxDNA fixture, future autostaple-sequence checks) |
| `assert_relaxed_geometry_recovered` (AF-13 P1) | a headless oxDNA relaxation reached `completed` AND its relaxed last frame reads back (display route → `read_configuration_unwrapped`, PBC-unwrapped + Kabsch-aligned) into a full per-nucleotide position map: exactly one *finite* position per design nucleotide, every `(helix_id, bp, dir)` key a real key of the design's geometry (set-equal); the first **physical-layer** oracle (Tier 5), Three-Layer-clean (reads relaxed geometry, never writes it to `Design`); can-go-red on a non-completed job or a wrong nucleotide count | `tests/automation_harness.py`; `backend/api/headless_oxdna_build.py` (`run_relaxation`/`read_relaxed_positions`) | any physical-layer (oxDNA) headless run + geometry-recovery check (AF-13 P2 measurement/constraint oracles build on it) |
| `measure_end_to_end` + `assert_relaxed_measurement` (AF-13 P2) | the **first STOCHASTIC-class oracle**: a *measured* geometric property of the relaxed, **noise-averaged** mean structure (pooled production frames, PBC-unwrapped + Kabsch-aligned via `production_rmsf`) lies within `tol_nm` of a target — **gated by confidence** (≥ `min_confidence` pooled frames, else INCONCLUSIVE, the Phase-3 "met requires confidence" seed). `measure_end_to_end(positions, a, b)` is the pure reusable primitive: Euclidean nm between two `(helix_id, bp_index, direction)` landmark backbone sites (raises on empty/identical/absent — no silent 0/NaN). Physical-layer only (reads relaxed geometry, never writes it back). Can-go-red on a wrong target, too-few frames (confidence gate), or no production run | `tests/automation_harness.py` (`assert_relaxed_measurement`); `backend/core/oxdna_health.py` (`measure_end_to_end`); `backend/api/headless_oxdna_build.py` (`read_flexibility_map`) | any relaxed-structure measurement/constraint (R_g, inter-helix spacing, segment angle — add a `measure_*` + a `measure_spec` kind); AF-13 P3 declarative constraint checker + P4 iterate-until-met both build on this |
| `measure_segment_angle` (segment_angle measure) | the first ANGULAR + first 3-landmark relaxed-structure measure: the interior bend angle (degrees) at the middle of three `(helix_id, bp_index, direction)` landmark backbone sites (`arccos` magnitude → direction-agnostic), pinned to closed-form angles + leg-order-invariant + raising on empty/coincident/absent/zero-leg; flows through the existing `check_relaxed_constraint`/`assert_relaxed_measurement` (confidence gate + tolerance bracket, now in degrees); the load-bearing `captures_bend` augment proves it tracks a real topology bend (straight ~175° → bent ~119° on the SAME landmarks), not a constant | `backend/core/oxdna_health.py` (`measure_segment_angle`); `tests/test_oxdna_relaxation.py`; `tests/test_headless_oxdna_build.py` | any relaxed-structure ANGULAR constraint (inter-segment kink, hinge opening); the 3-landmark arity path is now proven for any future n-landmark `measure_*` |
| `measure_inter_helix_spacing` (inter_helix_spacing measure) | the first measure needing **helix-axis grouping** (vs the point-landmark measures): each of the two landmarks only NAMES a helix (via `helix_id`); ALL of that helix's backbone sites are gathered and a straight axis fit (`_fit_helix_axis` = centroid + PCA principal direction). The spacing is the **radial centre-to-centre gap** = the centroid separation projected *perpendicular to the common (mean) axis direction*, with PCA sign aligned (`d_a·d_b<0`→flip). Deliberately NOT the minimal infinite-line distance (which collapses to ~0 for near-parallel tilted axes — the fragile regime spacing means); exact for parallel helices, robust to relaxed-bundle tilt, magnitude→direction-agnostic. In nm (no unit wart). Pinned to analytic parallel/staggered/tilted values + raising on empty/same-helix/absent/single-site; flows through `check_relaxed_constraint`/`assert_relaxed_measurement` unchanged. Load-bearing `captures_separation` augment: a straight 3-in-a-row SQUARE bundle reads equal adjacent gaps (~2.25 nm) and a skip-one gap ~2× — tracks real geometry, not a constant | `backend/core/oxdna_health.py` (`measure_inter_helix_spacing`/`_fit_helix_axis`); `tests/test_oxdna_relaxation.py`; `tests/test_headless_oxdna_build.py` | any relaxed-structure spacing/clearance constraint (bundle compaction, duplex–duplex gap); the axis-grouping pattern (group-by-helix → fit axis → relate axes) reusable for any helix-axis measure |
| `parse_constraint_spec` + `check_relaxed_constraint` (AF-13 P3) | a declarative relaxed-structure constraint `{measure, landmarks, target_nm, tol_nm, min_confidence}` is validated at parse time (PURE, raises `ConstraintSpecError` before any run) and then *REPORTED* against a `read_flexibility_map` mean-structure dict → `{met, status∈{met,unmet,inconclusive}, measured_nm, n_frames, …}`. The REPORTER counterpart to P2's *asserter* (returns a verdict a closed loop branches on, doesn't raise); **load-bearing invariant: `met` is NEVER True below `min_confidence`** even when the value is within tolerance (the confidence gate, now a returned status). Reuses `measure_end_to_end`; `backend/core`-pure (takes the read dict, never imports the api read-wrapper). Can-go-red on a malformed spec, a tolerance-bracket flip, or a within-tol low-frame run reporting met | `backend/core/oxdna_health.py` (`parse_constraint_spec`/`check_relaxed_constraint`/`ConstraintSpecError`) | the AF-11 grammar's design `constraints` block; AF-13 P4 iterate-until-met (branch on `status`); any future `measure_*` constraint kind (R_g/spacing/angle — add to `_CONSTRAINT_MEASURES` + the dispatch) |
| `assert_relax_honors_hardware_default` (AF-17) | a benchmarked hardware default *reaches the simulation*: a headless relaxation tuned from `metadata.hardware_defaults` runs on the recommended `backend`/`device` (read off `OxdnaJob.backend`/`.device`), with a CPU/"0" fallback when nothing was benchmarked. Baseline-fallback + tuned-honoured + non-vacuity (requested ≠ CPU fallback) structure; GPU-free (mock binary ignores the declared backend). The bridge that connects the auto-tuner's output to an actual run — nothing else proves the stored config is consumed (the apply route only wrote metadata the frontend pre-fills). Can-go-red on a bridge that hard-codes CPU, or a vacuous CPU/0 request | `tests/automation_harness.py` (`assert_relax_honors_hardware_default`); `backend/core/benchmark.py` (`resolve_oxdna_relax_config`); `backend/api/headless_oxdna_build.py` (`run_oxdna_benchmark`/`apply_oxdna_benchmark`/`run_relaxation_tuned`) | AF-13 P4 iterate-until-met (relax each iteration on the fastest discovered backend via `run_relaxation_tuned`); any "stored config → run parameter" bridge (a NAMD `run_relaxation_tuned` analog, future per-machine sim defaults) |
| `iterate_to_constraint` + `assert_converges_to_constraint` (AF-13 P4) | **the Tier-5 capstone**: a CLOSED build→relax→production→measure→adjust loop *converges* a parametric **topology** knob to a relaxed-structure target — and does so HONESTLY (every `met` verdict was confidence-gated). The driver branches on the P3 verdict **status** (`met`/`unmet`/`inconclusive`), never the raw `measured_nm`: `unmet`→`adjust_fn` picks the next knob, `inconclusive`→append MORE production to the same job (pooling frames) until the gate clears. The oracle asserts convergence + the confidence gate held on EVERY step (not just the last) + final-within-tol + **non-vacuity** (first attempt off-target). Three-Layer-clean (knob edits topology; relaxed coords read, never written back). Can-go-red on an exhausted run (unreachable target) or a vacuous attempt-0 win | `tests/automation_harness.py` (`assert_converges_to_constraint`); `backend/api/headless_oxdna_build.py` (`iterate_to_constraint`/`_pool_until_conclusive`) | constraint-driven design (the AF-11 `constraints` block lowered to the loop); any closed search over a topology knob with a stochastic, confidence-gated oracle (more `measure_*` kinds, multi-knob search) |
| `assert_spec_constraints_reported` (AF-13 P5 — grammar `constraints` block) | a design spec's declarative `constraints` block is lowered to the SAME per-constraint `check_relaxed_constraint` verdict (status + `met` + `measured_nm`) a hand-driven call yields — the load-bearing pin where `assert_spec_matches_calls` is BLIND (the canonical-topology fingerprint cannot see whether a physical-layer constraint was attached, its grid_pos landmark resolved to the right helix, or reported at all). Non-vacuity + count-mismatch guards; the driver resolves each landmark's `grid_pos`→runtime id, relaxes ONCE, then reports every constraint. Can-go-red on a wrong-helix resolution (measured diverges), a dropped constraint (count), a flipped status, or an empty block (vacuity) | `tests/automation_harness.py` (`assert_spec_constraints_reported`); `backend/core/build_spec.py` (`constraints` grammar); `backend/api/headless_spec_build.py` (`build_and_check_design`/`check_design_constraints`) | any declarative→physical-layer lowering whose effect the structure fingerprint can't see (the iterate-loop knob clause next; future `measure_*` constraint kinds get the grammar path for free) |

---

## Metrics rows (one per shipped AF item)

_Format: **AF-N — <op>** · shape (wrapper/new-module/service) · headless-coverage Δ · god-file LOC Δ ·
oracle shipped · tests (pass count) · **"Validation gained, not just a passthrough: ___."**_

**AF-1 — round-trip validation harness + coverage report** · _shape:_ new shared test module
`tests/automation_harness.py` (NOT a god-file; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**;
`test_section_router.py` net **−21** lines, its `_canonical_topology` deduped into the harness) ·
_headless-coverage Δ:_ first measurement — **11 / 239** design+assembly mutation routes wrapped (the audit
is now `headless_coverage_report()`, automated, so this number self-updates) · _oracles shipped:_
`canonical_topology` (promoted), `roundtrip_nadoc` (real `to_json`→`POST /design/import`, scratch-isolated),
`assert_roundtrip_stable` (validate→round-trip→validate + fingerprint-equal, injectable `roundtrip` seam),
`headless_coverage_report` (route↔wrapper by **function-object identity**) · _tests:_ 8 new in
`test_automation_harness.py` (full suite **2206 passed / 55 skipped**, no drop) ·
**"Validation gained, not just a passthrough:** before AF-1 there was *no* reusable way to assert a headless
build is correct — now any wrapper pins itself with one line (`assert_roundtrip_stable(build_fn)`) proving
its output validates AND survives a real `.nadoc` save/load unchanged, and the load-bearing meta-test proves
that oracle actually *raises* on a corrupted round-trip (a green that can go red). The coverage report turns
the manual route-vs-wrapper grep into a function-identity audit that can't go stale.**"

---

**AF-2 — nick / ligate / delete-strand wrappers** · _shape:_ 3 wrappers in `backend/api/headless_build.py`
(each imports the exact route handler — `add_nick` / `ligate_strand` / `delete_strand` — so they register as
covered by function identity, NOT re-implemented) + 1 reusable oracle `assert_inverse_pair` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**11 → 14 / 239** (nick + ligate + delete-strand flipped to covered) · _oracle shipped:_ `assert_inverse_pair(
start, forward, inverse)` — op∘inverse is canonical-topology-identity AND the mid-state must differ from start
(the "forward really mutated" guard that lets it go red); delete additionally pinned by canonical strand-set
subtraction (exactly one entry removed, helices untouched) + `assert_roundtrip_stable` reuse · _tests:_ 5 new
in `test_headless_build.py` + 4 new in `test_automation_harness.py` (incl. two red-tests proving
`assert_inverse_pair` raises on a non-restoring inverse and on a vacuous no-op forward); full suite **2215
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** nick/ligate now carry a
*proven* inverse-pair invariant (nick a strand, ligate it back, the topology fingerprint is byte-identical) —
nothing previously asserted that the two ops compose to identity, and the oracle's mutate-guard means a
wrapper that silently no-ops fails. The oracle is reusable for every future +δ↔−δ / add↔delete pair (AF-3
loop/skip is the next consumer).**"

**AF-3 — loop/skip insert + apply-deformations wrappers** · _shape:_ 2 wrappers in
`backend/api/headless_build.py` (`loop_skip` imports `insert_loop_skip`; `apply_loop_skip_deformations`
imports `apply_loop_skips_from_deformations` — exact route handlers, so they register as covered by function
identity) + 1 reusable oracle `assert_geometric_length_delta` (+ `geometric_nucleotide_count`) in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**14 → 16 / 239** (loop-skip/insert + loop-skip/apply-deformations flipped to covered) · _oracle shipped:_
`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None, strands_per_bp=2)` — asserts the
geometry kernel's (`_geometry_for_design`) nucleotide count changes by exactly the declared bp delta × 2
strands; **direction-agnostic** (counts magnitude, not bend sign → no three-layer sign reasoning, stays clear
of the ASK-FIRST rule); per-`helix_id` scoping gives the strong conservation check for bulk apply · _tests:_ 6
new in `test_headless_build.py` (loop +1 → +1 bp, skip −1 → −1, delta=0 restores, loop survives `.nadoc`
round-trip, SQUARE apply-deformations per-helix conservation, coverage flip) + 2 new in
`test_automation_harness.py` (oracle passes on a real loop; **load-bearing red-test**: claiming +2 for a +1
loop raises); full suite **2223 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
loop/skip now carries a *proven* topology→geometry conservation law — a loop adds exactly one bp of rendered
geometry per strand, a skip removes one, delta=0 restores, and bulk apply-deformations is honoured helix-by-helix
(no mark leaks or is dropped). Nothing previously asserted that the geometry layer faithfully reflects loop/skip
marks; critically, `canonical_topology` is *blind* to loop/skips, so the round-trip oracle alone could never have
caught a dropped mark — the geometric count is the only thing that proves persistence, and the red-test proves
the oracle can fail.**"

**AF-4 — parametric circle (`circle-segment`) wrapper** · _shape:_ 1 wrapper in `backend/api/headless_build.py`
(`circle_segment` imports `add_circle_segment as _route_circle_segment` — exact route handler, registers as
covered by function identity; computes the footprint via `circle_primitive.circle_footprint`, the SAME analytic
the JS preview mirror uses, then drives the route) + 1 reusable oracle `assert_circular_disc` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_
**16 → 17 / 239** (circle-segment flipped to covered) · _oracle shipped:_ `assert_circular_disc(design,
requested_radius_nm, *, max_spread_nm=0.5, radius_tol_nm=0.5, helix_ids=None)` — a **geometric** oracle (not a
count/round-trip one): it reads the *placed* helices' axis-endpoint spans (Euclidean, plane-agnostic), orders
them by lattice column, and feeds them to the existing circularity functions (`circularity_spread`, `fit_radius`
from `core/circle_primitive`) — asserting the built disc's per-column implied radii agree to <0.5 nm AND that
asking for radius R lands a disc of radius ≈R (within 0.5 nm). Empirically the generated discs hold
spread ≤0.29 nm and fit error ≤0.1 nm across R∈{6,8,10.6,14,20} · _tests:_ 6 new in `test_headless_build.py`
(parametrized circularity over 5 radii, round-trip stable, radius-too-small→ValueError-no-mutation,
additive-over-existing-DNA, coverage flip, + a **load-bearing red-test**: stretching the centre helix's axis
makes `assert_circular_disc` raise "not circular") + repointed the AF-1 coverage meta-test from circle-segment
(now covered) to `bundle-deformed-continuation` (AF-5, still uncovered); full suite **2233 passed / 55 skipped**,
no drop · **"Validation gained, not just a passthrough:** before AF-4, `tests/test_circle_primitive.py` pinned
the footprint *math* (pure `circle_footprint`) and the route *separately* (with hand-passed cells) — nothing
asserted that handing a builder a **radius** yields placed geometry that is actually circular *of that radius*.
`assert_circular_disc` closes that gap by measuring the real axis geometry the route laid down (so a builder that
silently dropped a column, mis-centred a helix, or used the wrong column pitch would fail), and the red-test
proves the oracle goes red on a mangled disc. It's reusable for any future parametric-shape primitive whose
spec is 'a profile of per-column lengths.'**"

**AF-5 — deformed-continuation wrapper** · _shape:_ 1 wrapper in `backend/api/headless_build.py`
(`bundle_deformed_continuation` imports `add_bundle_deformed_continuation as _route_deformed_continuation` —
exact route handler, registers as covered by function identity — and `get_deformed_frame as
_route_deformed_frame` to sample the frame; it POSTs *with* `source_bp` so the route re-derives the frame
server-side, the replayable path, exactly mirroring the UI's `getDeformedFrame`→`addBundleDeformedContinuation`)
+ 1 reusable oracle `assert_on_deformed_frame` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/
`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **17 → 18 / 239** (bundle-deformed-continuation flipped to
covered) · _oracle shipped:_ `assert_on_deformed_frame(before, after, source_bp, cells, *, ref_helix_id=None,
pos_tol_nm=0.02, min_deflection_nm=0.5)` — a **geometric** oracle: it independently re-derives the deformed
cross-section frame (`deformed_frame_at_bp` on the pre-continuation design, the same input the route uses when
`source_bp` is set) and the per-cell placement `grid_origin + frame_right·lx + frame_up·ly`, asserts every
appended helix's `axis_start` lands there (< 0.02 nm), AND — the can-go-red guard — that the deformed placement
is displaced > 0.5 nm from the straight-frame placement (frame recomputed on a deformations-stripped copy), so
the oracle goes red on an un-deformed design instead of passing vacuously. Direction-agnostic (measures *that*
it moved + *where* it landed, never bend sign → stays clear of the ASK-FIRST rule) · _tests:_ 2 new in
`test_headless_build.py` (lands-on-deformed-frame green, coverage flip) + 3 new in `test_automation_harness.py`
(oracle passes on a real bent continuation; **two load-bearing red-tests**: a helix dragged off the frame
raises "did not land on the deformed", and a straight (un-bent) continuation raises the "had no geometric
effect" deflection guard) + repointed the AF-1 coverage meta-test from bundle-deformed-continuation (now
covered) to `/design/deformation` (AF-6, still uncovered); full suite **2238 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-5, `test_deformed_continuation_replace.py` checked
only that the appended helix's axis *direction* was non-axial (a coarse "looks bent" sign) and that
delete/edit of the bend re-placed it. Nothing asserted the placed helix *origins* match the analytically
re-derived deformed cross-section frame, nor quantified that they are displaced from a straight extrude.
`assert_on_deformed_frame` closes that by measuring the real placed geometry against an independent frame
derivation (so a builder that swapped frame_right/up, used the wrong lattice pitch, or silently fell back to
the straight blunt-end would fail) with a deflection guard proving it can't pass on a non-deformed build. It's
reusable for any future op that places geometry on a sampled deformed frame.**"

**AF-6 — bend / twist by constraint** · _shape:_ 2 wrappers in `backend/api/headless_build.py`
(`add_bend` / `add_twist` import `add_deformation as _route_add_deformation` + `AddDeformationBody` from
`routes_deformation` — exact route handler, registers as covered by function identity; `add_twist` validates
the `total_degrees` XOR `degrees_per_nm` mutual exclusion before the call) + 1 reusable oracle
`assert_deformation_angle` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **18 → 19 / 239** (`POST /design/deformation` flipped to covered) · _oracle shipped:_
`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *, ref_helix_id=None,
angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` — a **geometric MAGNITUDE** oracle: it samples the deformed
cross-section frame (`deformed_frame_at_bp`, the orthonormal `[frame_right|frame_up|axis_dir]`) at each bp from
`plane_a` to `plane_b` and SUMS the magnitude of each step's relative frame rotation
(`arccos((tr(R₁R₀ᵀ)−1)/2)`). Summing per-step magnitudes — not the single endpoint-to-endpoint relative
rotation — **unwraps** angles past 180°/360° (the single-rotation form folded a 400.8° twist to 40.8°; a 540°
twist to 180°). Asserts the total = the requested θ (κ×(b−a) for a bend; total twist for a twist) within
`angle_tol_deg`, plus a can-go-red guard `total > min_angle_deg` (fails on an un-deformed design). **Direction
-AGNOSTIC** (an `arccos` magnitude, never sign/handedness) → no ASK-FIRST violation; the signed-curvature/
closure oracle the backlog floated (`solve_closing_curvature`) was **deliberately not built** · _tests:_ 7 new
in `test_headless_build.py` (bend realises κ×Δbp; bend 200° unwraps past 180; twist `total_degrees`; twist
540° unwraps past 360; twist `degrees_per_nm` rate; `add_twist` XOR-spec ValueError-no-mutation; coverage
flip) + 4 new in `test_automation_harness.py` (af6-covered + oracle passes on a real bend + **two load-bearing
red-tests**: wrong expected θ raises "does not match the request", and a straight bundle raises the
"un-deformed" vacuity guard) + repointed the AF-1 coverage meta-test from `/design/deformation` (now covered)
to `/design/cluster` (still uncovered); full suite **2249 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-6 nothing pinned that asking for a bend of curvature
κ over an N-bp window actually rotates the geometry by κ·N degrees — `test_deformed_continuation_replace.py`
only checked a bend was "non-axial" (a coarse looks-bent sign). `assert_deformation_angle` closes that by
measuring the realised frame rotation against the user-meaningful request (so a builder that mis-scaled κ,
ignored the planes, or dropped the op fails), works for both bend and twist via one frame-rotation metric, and
its per-step summation correctly handles large angles the naive relative-rotation form silently folds. The
two red-tests prove it goes red on a wrong angle and on a non-deformed build.**"

**AF-7 — headless ASSEMBLY builder (Phase 1: place + resolve + round-trip)** · _shape:_ **NEW module**
`backend/api/headless_assembly_build.py` (the first assembly-layer headless builder — mirrors `headless_build.py`:
`assembly_scratch_session` + `new_assembly` + `add_inline_instance`/`add_file_instance`/`add_instance` +
`resolve` + `import_assembly`, each importing the exact route handler — `create_assembly` / `add_instance` /
`resolve_assembly` / `import_assembly` — so they register as covered by function identity, NOT re-implemented)
+ 3 reusable oracles (`canonical_assembly`, `roundtrip_nass`, `assert_assembly_roundtrip_stable`) in
`tests/automation_harness.py`; `headless_coverage_report` extended to scan BOTH `headless_build` and the new
module; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (zero god-file growth — all new code is a new module +
the test harness) · _headless-coverage Δ:_ **19 → 23 / 239** (create + add-instance + resolve + import all flip) ·
_oracle shipped:_ `assert_assembly_roundtrip_stable(build_fn, *, roundtrip=roundtrip_nass)` — the assembly analog
of `assert_roundtrip_stable`: validates the built assembly (`validate_assembly_report` — file sources resolve,
joint refs/limits hold, ids unique, flatten ok), round-trips it through the **real** `POST /assembly/import`
(`roundtrip_nass`: `to_json` v2 → import, **in-memory**, inline part designs travel inside the payload — no
workspace files), re-validates, and asserts the **id/order-independent** `canonical_assembly` fingerprint is
unchanged (instances keyed by source fingerprint — inline → the embedded design's `canonical_topology`, file →
path+sha — plus the world transform + mode/rep/fixed/visible; joints keyed by type+connector-labels+value for
AF-8). Injectable `roundtrip=` seam so the meta-test feeds a part-dropping round-trip and proves it raises ·
_tests:_ 7 new in `test_headless_assembly_build.py` (inline two-part round-trip stable, placement transform
survives, canonical order-independent + placement-sensitive, resolve no-op without joints, file-source structural,
coverage flip) + 4 new in `test_automation_harness.py` (af7-covered + oracle passes on a real build + **two
load-bearing red-tests**: a dropped-part round-trip raises "changed the assembly structure", a missing-file source
raises "did not validate before round-trip"); full suite **2260 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-7 there was *no way at all* to build an assembly without
a browser, and therefore no way to pin assembly construction — `headless_build` stopped at the design layer.
`assert_assembly_roundtrip_stable` is the first assembly correctness oracle: it proves a scripted multi-part
placement validates AND that every part, at its exact world transform, survives a real `.nass` save/load with an
identical id-independent fingerprint (so a builder that dropped a part, garbled a transform, or lost an inline
design would fail), with a red-test proving the green can go red. It is the spine the AF-8+ mate/joint, gear/belt,
and layout wrappers pin themselves against — the assembly analog of what AF-1 did for designs.**"

**AF-8 — headless mate/joint by connector labels** · _shape:_ 2 wrappers in
`backend/api/headless_assembly_build.py` (`add_connector` imports the `add_connector` route handler from
`routes_assembly_connectors`; `define_mate` imports `create_mate` + `CreateMateRequest`/`MateConnectorSpec` from
`routes_assembly_joints` — exact route handlers, registers covered by function identity, NOT re-implemented) + 1
reusable oracle `assert_mate_coincident` in `tests/automation_harness.py` + enriched `canonical_assembly`'s joint
key; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the harness) ·
_headless-coverage Δ:_ **23 → 25 / 239** (`POST /assembly/instances/{id}/connectors` + `POST
/assembly/joints/create-mate` flip to covered) · _oracle shipped:_ `assert_mate_coincident(assembly, joint_id, *,
tol_nm=0.01, min_offset_nm=0.5)` — a **geometric** oracle: it resolves the two mated connectors' world positions
with the SAME `_get_connector_world` machinery `resolve_assembly` uses (on the instance-overridden design, so it's
the real resolve definition of "where the connector is", not a re-derivation) and asserts they coincide within
`tol_nm`, plus a non-triviality guard that the two mated part *origins* are separated by > `min_offset_nm` (so the
coincidence is genuine alignment work on offset parts, not the vacuous both-stacked-at-origin case — the mate analog
of `assert_inverse_pair`'s "forward really mutated" guard). Also enriched `canonical_assembly`'s joint key from
`(type, conn_a, conn_b, value)` to additionally carry the two mated instances' *source fingerprints*
(id-independent), so the round-trip fingerprint detects a mate rewired to a different part · _tests:_ 5 new in
`test_headless_assembly_build.py` (mate makes connectors coincident, coincidence survives `resolve()`, mated
assembly round-trips stable WITH its joint + still coincident after re-import, dropping the mate changes the
fingerprint, + a **load-bearing red-test**: shoving the child +30 nm after the mate makes the oracle raise "not
coincident") + 4 new in `test_automation_harness.py` (af8-covered + oracle passes on a real mate + **two
load-bearing red-tests**: separated connectors raise "not coincident", stacked-at-origin parts raise the "trivial"
vacuity guard); full suite **2269 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
before AF-8 there was no way to mate parts headlessly, and nothing pinned that a mate actually snaps its two
connectors together — `assert_assembly_roundtrip_stable` (AF-7) checks the assembly *structure* survives save/load
but is blind to whether the joint's geometric promise (connector coincidence) holds. `assert_mate_coincident`
closes that by measuring the real connector world positions the resolver computes and asserting they coincide on an
offset pair of parts (so a builder that registered the joint but failed to snap, or snapped to the wrong connector,
fails), with a vacuity guard + red-tests proving the green can go red. It's the resolve-invariant spine the AF-9
gear/belt/polymerize wrappers pin themselves against (each is 'after resolve, this relation holds').**"

**AF-9 — gears (Tier 3 Phase 3, gear sub-op): `define_gear` + `drive_joint` + ratio oracle** · _shape:_ 2 wrappers
in `backend/api/headless_assembly_build.py` (`define_gear` imports `create_gear_relation` + `CreateGearRelationRequest`
from `routes_assembly_gears`; `drive_joint` imports `patch_joint` + `PatchJointRequest` from `routes_assembly_joints`
— exact route handlers, registers covered by function identity) + 1 reusable oracle `assert_gear_ratio` in
`tests/automation_harness.py` + enriched `canonical_assembly` to fingerprint `gear_relations` (now returns a 3-tuple
`(instances, joints, gears)`); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new
module + the harness) · _headless-coverage Δ:_ **25 → 27 / 239** (`POST /assembly/gear-relations` + `PATCH
/assembly/joints/{id}` flip to covered) · _oracle shipped:_ `assert_gear_ratio(assembly_before, assembly_after,
rel_id, *, expected_ratio, ratio_tol=0.02, min_angle_deg=2.0)` — a **geometric resolve-invariant** oracle: after
driving one side of the gear (`drive_joint`, whose PATCH auto-propagates the relation), it measures the two coupled
bodies' real **instance-transform rotation magnitudes** (relative rotation `arccos((tr(R₁R₀ᵀ)−1)/2)` of each gear-
endpoint instance, picked via `_gear_endpoint_side`) and asserts driven/driver = `|expected_ratio|`, with a can-go-red
"driver actually rotated > min_angle" guard (a no-op gear makes the ratio `0/0`). Measures the placed geometry, NOT
`joint.current_value` — so it is not a re-test of the route's own `θ_b = ratio·θ_a` arithmetic. **Direction-agnostic**
(magnitude only → no ASK-FIRST sign/handedness reasoning; `invert` flips the driven body's direction but not the
magnitude ratio). Also enriched `canonical_assembly` to key each `GearRelation` by its two coupled joints' id-
independent fingerprints + ratio/invert/anchors, so `assert_assembly_roundtrip_stable` now catches a dropped/rewired
gear · _tests:_ 6 new in `test_headless_assembly_build.py` (gear drives coupled wheel at ratio 2, fractional ratio
0.5, invert flips sign not magnitude, gear-over-rigid-mates 400s, geared assembly round-trips stable WITH its gear,
canonical distinguishes a gear) + 4 new in `test_automation_harness.py` (af9-covered + oracle passes on a real gear +
**two load-bearing red-tests**: reverting the driven wheel's transform raises "did not propagate", and an undriven
assembly raises the "nothing was driven" guard); full suite **2279 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-9 there was no way to couple parts headlessly, and nothing
pinned that a gear relation actually *drives* its coupled body — `assert_assembly_roundtrip_stable` (AF-7/8) checks the
gear's structure survives save/load but is blind to whether its kinematic promise (the angular ratio) holds when you
spin one wheel. `assert_gear_ratio` closes that by driving one side and measuring the *other body's real rotation*
against the promised ratio (so a builder that registered the gear but failed to propagate, or used the wrong ratio,
fails), with a can-go-red guard + two red-tests proving the green can go red. It's the resolve-invariant spine the
belt/polymerize sub-ops pin themselves against — a belt IS a gear-equivalent coupling (`_belt_to_relation`), so it
should reuse this same oracle with `expected_ratio = r_a/r_b`.**"

**AF-9 — belts (Tier 3 Phase 3, belt sub-op): `define_belt` + generalised ratio oracle** · _shape:_ 1 wrapper
in `backend/api/headless_assembly_build.py` (`define_belt` imports `create_belt_path` +
`CreateBeltPathRequest`/`BeltPulleyRequest` from `routes_assembly_belts` — exact route handler, registers
covered by function identity) + **generalised** the existing `assert_gear_ratio` oracle (now searches
`_coupling_relations`, which folds belt-derived relations in, instead of only `assembly.gear_relations`) +
extended `canonical_assembly` to fingerprint `belt_paths` (return is now a **4-tuple**
`(instances, joints, gears, belts)`); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the
existing new module + the harness) · _headless-coverage Δ:_ **27 → 28 / 239** (`POST /assembly/belt-paths`
flips to covered) · _oracle shipped:_ reused `assert_gear_ratio(before, after, rel_id, *, expected_ratio)` with
the belt's synthetic relation id `f"__belt__{belt.id}"` and `expected_ratio = radius_a/radius_b` — it measures the
two coupled pulleys' real **instance-transform rotation magnitudes** after driving one side and asserts
driven/driver = `|r_a/r_b|`, with the same can-go-red "driver actually moved" guard. The generalisation
(search `_coupling_relations`, not just stored gears) is backward-safe: gears are first in that list, so every
existing gear test is unchanged · _tests:_ 5 new in `test_headless_assembly_build.py` (belt drives pulley at
radius ratio 2, 3:1 ratio, belt-over-rigid-mates 400s, belted assembly round-trips stable WITH its belt,
canonical distinguishes a belt) + 3 new in `test_automation_harness.py` (af9-belt-covered + oracle passes on a
real belt + a **load-bearing red-test**: reverting the belt-driven pulley's transform raises "did not
propagate"); full suite **2287 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:**
before this, nothing proved that defining a belt with rim radii `r_a`/`r_b` actually couples its two pulleys at
angular ratio `r_a/r_b` — the belt→`GearRelation` synthesis (`_belt_to_relation`, which derives the ratio AND the
world-sense `invert` from the radii/sides/axes and folds the belt into propagation) was untested via a headless
build. The gear test (AF-9 gears) hand-passes a literal ratio; the belt test passes *radii* and asserts the
*derived* ratio drives the coupled body — so if `_belt_to_relation` computed `r_b/r_a`, dropped the belt from
`_coupling_relations`, or got the sign wrong, the belt test goes red while the gear test stays green. That is
distinct, new validation power, and the red-test proves the green can go red. `canonical_assembly` now also
catches a dropped/rewired belt in the round-trip fingerprint.**"

**AF-9 — polymerize (Tier 3 Phase 3, mate-seeded sub-op): `polymerize` + chain-lattice oracle** · _shape:_ 1
wrapper in `backend/api/headless_assembly_build.py` (`polymerize` imports `polymerize_assembly` +
`PolymerizeAssemblyRequest` from `routes_assembly_polymerize` — exact route handler, registers covered by
function identity) + 1 reusable oracle `assert_polymer_chain` in `tests/automation_harness.py`;
`canonical_assembly` **unchanged** (it already fingerprints instances+joints, and polymerize adds NO new
top-level relation list — so the round-trip oracle catches a dropped copy/joint with no extension, unlike
gears/belts); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the
harness) · _headless-coverage Δ:_ **28 → 29 / 239** (`POST /assembly/polymerize` flips to covered) · _oracle
shipped:_ `assert_polymer_chain(before, after, seed_joint_id, *, count, direction="forward", tol_nm=0.01,
min_delta_nm=0.5)` — a **geometric** oracle: re-derives the seed mate's repeat `delta = T_B @ inv(T_A)` from the
seed pair's world transforms ALONE (NOT the route's `compute_chain_transforms` — an independent derivation, so it
is not a tautology re-running the implementation), then asserts the `count−2` new instances form the exact
`delta`-power multiset (`delta^k @ T_B` forward / `inv(delta)^k @ T_A` backward) matched id-independently within
`tol_nm`, plus a can-go-red guard that `‖delta translation‖ > min_delta_nm` (stacked seed pair → every copy lands
on the seed → the oracle would pass vacuously; the analog of `assert_mate_coincident`'s separation guard).
Direction-agnostic on handedness (re-derives the documented fwd/back split, checks placed geometry, never a
bend/twist sign) · _tests:_ 5 new in `test_headless_assembly_build.py` (length-4 chain on the +10 nm delta
lattice, length-6 chain, count-2 no-op, 422-on-non-identical-parts, polymerized chain round-trips stable WITH its
2 replicated joints, + the coverage-flip assertion extended) + 4 new in `test_automation_harness.py`
(af9-polymerize-covered + oracle passes on a real chain + **two load-bearing red-tests**: a copy shoved off the
lattice raises "repeat", and a stacked seed pair raises the "~identity" vacuity guard); full suite **2296 passed
/ 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before this, nothing pinned that
mate-seeded polymerize lays its copies on a geometric progression — `test_polymerize.py` checked the pure chain
*math* (`compute_chain_transforms` with hand-fed matrices) and the route's *count*, but nothing asserted that a
**headless** build places `count−2` real instances at the seed mate's actual `delta`-power transforms. `assert_
polymer_chain` closes that by measuring the placed instance transforms against a `delta` re-derived solely from
the seed pair (so a builder that dropped a copy, used the wrong repeat, or mis-ordered the chain fails), with a
vacuity guard + two red-tests proving the green can go red. It's the resolve-invariant for any repeat-lattice
construction; `polymerize_periodic` will reuse the same 'each copy = `T_seed @ delta^k`' shape with `delta` from
`derive_periodic_delta` instead of the seed mate.**"

**AF-9 — overhang-bindings (Tier 3 Phase 3, binding sub-op): `bind/patch/unbind_overhangs` + integrity oracle**
· _shape:_ 3 wrappers in `backend/api/headless_assembly_build.py` (`bind_overhangs` imports
`create_assembly_overhang_binding`; `patch_binding` imports `patch_assembly_overhang_binding`;
`unbind_overhangs` imports `delete_assembly_overhang_binding` — all + their request models from
`routes_assembly_overhangs`, exact route handlers, registers covered by function identity) + 1 reusable oracle
`assert_binding_resolves` in `tests/automation_harness.py` + extended `canonical_assembly` to fingerprint
`overhang_bindings` (now returns a **5-tuple** `(instances, joints, gears, belts, bindings)`);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing new module + the harness) ·
_headless-coverage Δ:_ **29 → 32 / 239** (`POST` + `PATCH` + `DELETE /assembly/overhang-bindings` flip to
covered) · _oracle shipped:_ `assert_binding_resolves(assembly, binding_id, *, require_cross_part=True)` — a
**referential-integrity** oracle: it loads each endpoint's part design with the route's OWN
`_load_design_from_source` and asserts both `(overhang_id, sub_domain_id)` refs resolve to a live overhang
sub-domain, plus a non-degenerate guard (the two endpoints are distinct `(instance, sub-domain)` pairs and, by
default, cross-part). The binding is pure topology metadata (no geometry to measure), so the property to pin is
ref validity — and crucially that it survives a `.nass` round-trip · _tests:_ 6 new in
`test_headless_assembly_build.py` (bind resolves; bound assembly round-trips stable WITH its binding AND still
resolves after re-import; unbind restores the pre-bind fingerprint; canonical distinguishes a binding; patch
changes mode + fingerprint; unknown-sub-domain 404) + 4 new in `test_automation_harness.py`
(af9-overhang-binding-covered + oracle passes on a real binding + **two load-bearing red-tests**: a binding
pointing at a dropped sub-domain raises "dropped sub-domain", and a degenerate self-pair binding raises
"sub-domain with itself"); full suite **2306 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this, nothing pinned that a cross-part overhang binding's references stay valid — and
`assert_assembly_roundtrip_stable` *cannot* pin it, because `canonical_topology` (the inline-source fingerprint
`canonical_assembly` keys on) does NOT fingerprint a design's overhangs or sub-domains. So a round-trip that
regenerated a sub-domain id inside a part while the binding kept its stale id would slip past the structure
fingerprint entirely; `assert_binding_resolves` is the only thing that catches it, by resolving the binding's
endpoints against the actual round-tripped part designs. The two red-tests prove the green can go red. It's the
referential-integrity spine for any future metadata-only cross-part relation (assembly overhang *connections*
next).**"

**AF-10 — instance layout helpers (grid / ring): `place_grid` + `place_ring` + lattice oracles** · _shape:_
**NEW pure core** `backend/core/instance_layout.py` (`grid_translations` / `ring_translations` — spec→world
translations, plane in {XY,XZ,YZ}, identity orientation; mirrors `circle_primitive`) + 2 construction-sugar
wrappers in `backend/api/headless_assembly_build.py` (`place_grid` / `place_ring` — compute the per-slot
translations then drive the existing `add_inline_instance` once per slot) + 2 reusable oracles
(`assert_instances_on_grid`, `assert_instances_on_ring`) in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a new core module + the existing headless module
+ the harness) · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — the layout helpers wrap NO new route; they
compose the already-covered `add_instance`, so this item moves the oracle count, not the coverage count — a
construction-sugar item, not a route-wrapper item) · _oracles shipped:_ `assert_instances_on_grid(assembly,
rows, cols, *, pitch, row_pitch=None, plane="XY")` + `assert_instances_on_ring(assembly, n, *, radius,
plane="XY", center=…)` — both **geometric** oracles reading the *placed* instance origins (not the layout spec):
grid asserts the origins occupy exactly `cols` distinct columns × `rows` distinct rows, evenly spaced by
`pitch`/`row_pitch`, with every cell filled; ring asserts every origin is at `radius` from `center` with an even
`360°/n` angular step. The expected lattice is re-derived from the user-facing params as *properties* of the
result, never by re-running the placement formula, so a builder bug (wrong pitch, dropped slot, transposed axes)
is caught not mirrored. Each carries a non-degeneracy guard; the ring's `radius>min_radius` guard is
load-bearing (radius=0 stacks every part at `center` where `dist==radius==0` passes vacuously) · _tests:_ 17 new
in `test_instance_layout.py` (pure formula: grid count/spacing/centring/plane/reject + ring radius/step/
start-angle/center/plane/reject) + 4 new in `test_headless_assembly_build.py` (grid lands + rectangular grid
round-trips, ring lands + offset-centre XZ-plane ring round-trips) + 9 new in `test_automation_harness.py`
(helpers-compose + grid passes/off-lattice-fires/vacuity-guard + ring passes/off-ring-fires/vacuity-guard); full
suite **2334 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-10 there
was no way to lay out a parametric pattern of parts headlessly, and nothing pinned that a programmatic layout
places copies on a *regular* lattice. `assert_instances_on_grid` / `assert_instances_on_ring` close that by
measuring the real placed instance origins against the lattice the user asked for (so a builder that mis-scaled
the pitch, dropped a slot, used the wrong radius, or transposed the axes fails), with non-degeneracy guards +
red-tests (shoving one part off the grid/ring raises) proving the green can go red. The oracles are the
geometric spine the AF-11 DSL's layout specs will pin themselves against. NB: this is a construction-sugar item
(it wraps no route), so coverage is unchanged by design — the pass criterion was always the oracle, not a
coverage flip, and here that distinction is explicit.**"

**AF-11 — declarative build-spec interpreter (Phase 1): `build_design` / `build_assembly` + faithfulness oracle**
· _shape:_ **NEW pure core** `backend/core/build_spec.py` (`parse_design_spec` / `parse_assembly_spec` → ordered
`BuildOp` list; full grammar validation + assembly referential-integrity, NO execution, imports nothing from
`backend.api`) + **NEW driver** `backend/api/headless_spec_build.py` (`build_design` / `build_assembly` —
dispatch each parsed op to the REAL existing `hb.*` / `hab.*` wrappers; helices resolved by `grid_pos`, instances
by spec `ref`; nested part designs built via `build_design`) + 1 reusable oracle `assert_spec_matches_calls` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is two new modules +
the harness) · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — the interpreter wraps NO new route; it composes
the already-covered design/assembly wrappers, so like AF-10 it moves the oracle count, not the coverage count) ·
_oracle shipped:_ `assert_spec_matches_calls(build_from_spec, build_by_hand, *, kind="design"|"assembly")` — the
**faithful-façade / golden-pin** oracle: it asserts a spec build produces the SAME id/order-independent fingerprint
(`canonical_topology` for design, `canonical_assembly` for assembly) as the equivalent hand-call wrapper sequence,
with a non-emptiness guard so it can't pass vacuously on a spec that builds nothing. Because the hand-call
reference is deterministic, "the spec matches the calls" IS the spec→canonical-fingerprint golden pin the backlog
asked for · _tests:_ 25 new in `test_build_spec.py` (pure grammar: design/assembly normalisation + ~20 parametrized
rejections — unknown op, typo'd key, bad types, dangling part/mate/connector refs, degenerate layout, propagated
bad part spec) + 15 new in `test_headless_spec_build.py` (6hb spec ≡ `make_6hb_design`; teeth spec ≡
`build_bundle` passes; round-trip stable; nick→ligate declarative identity; nick-alone mutates; unknown-grid_pos
raises; isolation; grid/ring/mate spec ≡ hand-call; mate coincident; mate round-trips; coverage stays 32) + 4 new
in `test_automation_harness.py` (oracle passes on a faithful build + **load-bearing red-tests**: a divergent build
raises "did not produce the same canonical", an empty build trips the vacuity guard, + assembly-kind); full suite
**2378 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-11 there was no
way to drive a build from a declarative spec, and — the real point — nothing proved that a spec is lowered to the
*same* build a person's clicks produce. `assert_spec_matches_calls` closes that: it pins that a JSON spec builds a
byte-identical canonical structure to the equivalent hand-call wrapper sequence, so the interpreter is provably a
faithful façade (it drives the real wrappers; it does NOT re-implement an op) — the exact guarantee the
text-to-DNA goal rests on. Separately, the PURE parser is itself new validation power: it rejects a malformed spec
(unknown op, typo'd field, a `mate` referencing an instance never added or a connector label that doesn't exist) at
parse time with a precise error, before any build runs — 20+ rejection pins. The red-tests prove the green can go
red. This is the Tier-4 capstone, and it's deliberately composition-only (coverage flat) — the pass criterion was
always the oracle.**"

**AF-11 — build-spec grammar growth (Phase 2): `bend` / `twist` design ops** · _shape:_ grammar growth only — 2
new design ops in the PURE parser `backend/core/build_spec.py` (`bend`/`twist` allowed-key sets + a parse branch
that validates the two bp planes, bend's required curvature, and twist's `total_degrees` XOR `degrees_per_nm`)
+ 2 dispatch branches in the driver `backend/api/headless_spec_build.py` driving the REAL AF-6 wrappers
(`hb.add_bend` / `hb.add_twist` — re-implements nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over already-covered wrappers, wraps no new
route; like AF-10/AF-11-Phase-1 it moves the oracle count, not coverage) · _oracle shipped:_ **no new oracle —
reused `assert_deformation_angle` (AF-6) as the LOAD-BEARING augment** + `assert_spec_matches_calls` (AF-11) as a
secondary pin. The deciding fact: `canonical_topology` is **blind to a deformation overlay** (it lives outside the
strand graph — the AF-3 loop/skip lesson, now confirmed for deformations too), so `assert_spec_matches_calls`
*passes even if the bend were dropped* — it only proves the underlying bundle topology is faithful. What proves the
deformation actually flowed spec→parser→`hb.add_bend`→DeformationOp is the geometric `assert_deformation_angle` on
the spec-built design (κ×Δbp for a bend; θ for a twist; magnitude-only, direction-agnostic) · _tests:_ 1 grammar
normalisation + 5 grammar rejections (bend missing curvature, planes out of order, twist neither/both rate,
bend-can't-be-first) in `test_build_spec.py` + 4 driver tests in `test_headless_spec_build.py` (bend spec ≡
hand-calls, bend realises κ×Δbp, twist `total_degrees` realises θ, twist `degrees_per_nm` realises rate); full
suite **2388 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers
a declarative `{op:bend|twist}` to the real AF-6 deformation wrappers, and the spec-built bend/twist is *proven to
realise the requested angle* (`assert_deformation_angle`) — not merely structurally equal to the hand build. The
genuinely-new validation power is the recognition (and pinning) that `assert_spec_matches_calls` ALONE is vacuous
for a deformation cluster because the canonical fingerprint can't see the overlay; the geometric angle oracle is the
only thing that catches a dropped/mistranslated bend. No ASK-FIRST violation: the wrappers + oracle are AF-6's
direction-agnostic, already-cleared machinery; this layer adds zero new geometric/sign/frame reasoning, only
parameter plumbing.**"

**AF-11 — build-spec grammar growth (Phase 2): `loop_skip` design op** · _shape:_ grammar growth only — 1 new
design op in the PURE parser `backend/core/build_spec.py` (`loop_skip` allowed-key set `{op,helix,bp_index,delta}`
+ a parse branch validating the helix cell, a non-negative `bp_index`, and a route-faithful `delta ∈ {-1,0,+1}`
gate) + 1 dispatch branch in the driver `backend/api/headless_spec_build.py` driving the REAL AF-3 wrapper
`hb.loop_skip` (re-implements nothing; helix resolved by `grid_pos` like nick/ligate);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar
over the already-covered `insert_loop_skip` route; wraps no new route, moves the oracle count not coverage —
verified by the passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused
`geometric_nucleotide_count` / `assert_geometric_length_delta` (AF-3) as the LOAD-BEARING augment** +
`assert_spec_matches_calls` (AF-11) as a secondary pin. Same deciding fact as the bend/twist cluster: a loop/skip
mark lives on `Helix.loop_skips`, OUTSIDE the strand graph, so `canonical_topology` (and thus
`assert_spec_matches_calls`) is **blind to it** (the original AF-3 lesson) — a spec whose loop was silently dropped
would still match the hand-call canonical fingerprint. What proves the mark flowed spec→parser→`hb.loop_skip`→
geometry is the geometric nucleotide count on the spec-built design (a loop +1 adds exactly 1 bp = 2 nucleotides on
its helix; a skip −1 removes 2) · _tests:_ 1 grammar normalisation (loop/skip/remove deltas) + 4 grammar rejections
(delta out of {-1,0,+1}, missing delta, negative bp_index, loop_skip-can't-be-first) in `test_build_spec.py` + 4
driver tests in `test_headless_spec_build.py` (loop_skip spec ≡ bundle topology of hand-calls; loop +1 adds 2
nucleotides; skip −1 removes 2; loop survives a `.nadoc` round-trip via the geometric count) ; full suite **2397
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers a
declarative `{op:loop_skip}` to the real AF-3 wrapper, and the spec-built loop/skip is *proven to change the
geometry by the requested amount* (geometric nucleotide count) and to *persist through a save/load* — neither of
which `assert_spec_matches_calls` can pin, because the canonical fingerprint can't see a loop/skip mark. The
genuinely-new validation power is the geometric length-delta pin on a declarative length-changing op (a bundle
clicked-then-looped vs. a spec-looped build are now proven byte-identical in *emitted geometry*, not just
topology). The `delta ∈ {-1,0,+1}` parse-time gate also rejects a malformed length op before any build runs.
**Scope note:** `apply_loop_skips` (the AF-3 sibling) is deferred — its route requires crossovers placed
(cross-helix domain transitions), which the spec grammar has no op to produce yet; it rides with the
`auto_scaffold`/`auto_crossover` cluster that generates those crossovers. No ASK-FIRST violation: `hb.loop_skip` +
the count oracle are AF-3's direction-agnostic machinery; this layer adds only parameter plumbing.**"

**AF-11 — build-spec grammar growth (Phase 2): `circle_segment` design op** · _shape:_ grammar growth only — 1 new
PRIMORDIAL design op in the PURE parser `backend/core/build_spec.py` (`circle_segment` allowed-key set
`{op,radius_nm,plane,offset_nm,strand_filter,ligate_adjacent,min_chord_bp}` + a parse branch validating a positive
`radius_nm`; added to `_PRIMORDIAL_DESIGN_OPS` so it may be the FIRST op like `bundle`; + a spec-level guard that a
spec containing a `circle_segment` op MUST be `square` lattice — the chord profile assumes the SQUARE column pitch)
+ 1 dispatch branch in the driver `backend/api/headless_spec_build.py` driving the REAL AF-4 wrapper
`hb.circle_segment` (re-implements nothing — the wrapper itself runs the same `circle_footprint` analytic the UI
mirror uses); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED —
composition sugar over the already-covered `add_circle_segment` route; wraps no new route, moves the oracle count
not coverage — verified by the still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle
— reused BOTH `assert_spec_matches_calls` (AF-11, LOAD-BEARING here) AND the geometric `assert_circular_disc`
(AF-4)**. The deciding fact, and what makes this cluster DIFFERENT from loop_skip/bend/twist: a circle ADDS real
helices + strands to the strand graph, so `canonical_topology` *can* see it → `assert_spec_matches_calls` is a real,
load-bearing faithfulness pin (a spec whose disc was silently dropped would fail it, unlike the deformation/loop
overlays where it's vacuous). `assert_circular_disc` additionally pins the radius→footprint→route→placed-geometry
path end-to-end (spread <0.5 nm, fit_radius within 0.5 nm of R) · _tests:_ 1 grammar normalisation (primordial,
defaults filled) + 4 grammar rejections (missing radius_nm, non-positive radius, non-square lattice, typo'd field)
in `test_build_spec.py` + 5 driver tests in `test_headless_spec_build.py` (circle spec ≡ hand-call canonical; disc
of requested radius over R∈{8,10.6,14}; round-trip stable); full suite **2407 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** the grammar now lowers a declarative `{op:circle_segment,radius_nm}`
to the real AF-4 parametric-disc wrapper, and — distinctively for this cluster — the spec-built disc is pinned by the
faithful-façade oracle (`assert_spec_matches_calls` is load-bearing because the circle is *visible* in canonical
topology, the first Phase-2 op for which it is) AND by the geometric `assert_circular_disc` (the placed helices
actually trace a circle of the requested radius). The genuinely-new validation power is the parse-time SQUARE-lattice
guard: a `circle_segment` on a honeycomb lattice would silently produce a non-circular profile (the chord math
assumes the SQUARE pitch), and nothing else in the stack rejects it — the parser now catches it before any build
runs, alongside the positive-radius and primordial-first-op gates. No ASK-FIRST violation: `hb.circle_segment` +
`assert_circular_disc` are AF-4's already-cleared machinery; this layer adds only parameter plumbing + the lattice
guard.**"

**AF-11 — build-spec grammar growth (Phase 2): `gear` assembly op (relations cluster, sub-op 1)** · _shape:_
grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py` (`gear` allowed-key set
`{op,joint_a,joint_b,ratio,invert,name}` + a parse branch validating a non-zero `ratio`) **plus a NEW joint-`ref`
namespace**: the `mate` op grew an optional `ref` key, and the referential-integrity pass now tracks
`defined_joints: dict[ref→joint_type]` so a `gear` `joint_*` must name a prior mate `ref` **that is `revolute`**
(rejecting gear-over-rigid + dangling/duplicate joint refs at parse time) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.define_gear` (the driver tracks
`joint_refs: dict[ref→runtime joint id]`, capturing `joints[-1].id` after each `define_mate`; re-implements
nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED —
composition sugar over the already-covered `create_gear_relation` route; wraps no new route, moves the oracle count
not coverage — verified by the still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle
— reused BOTH `assert_gear_ratio` (AF-9, LOAD-BEARING) AND `assert_spec_matches_calls` (AF-11, also load-bearing
here)**. The deciding fact: a gear is a top-level `GearRelation` that `canonical_assembly` HAS fingerprinted since
AF-9, so `assert_spec_matches_calls` is a real faithfulness pin (a dropped/rewired gear fails it — like
`circle_segment`, unlike the bend/twist/loop_skip overlays). But it's necessary-not-sufficient: the fingerprint
catches a *structurally* dropped gear, NOT a gear that's present but fails to *propagate* (drive its coupled body).
`assert_gear_ratio` is the orthogonal kinematic pin — drive `rel.joint_a_id` 30°, measure the coupled wheel's real
instance-transform rotation, assert driven/driver = `|ratio|` (parametrized 2.0 + 0.5) — the same complementary
roles as AF-9 overhang-bindings (fingerprint + resolve oracle) · _tests:_ 7 new in `test_build_spec.py` (gear
normalisation incl. defaults; **5 rejections**: dangling joint ref, gear-over-rigid → "must be 'revolute'",
zero ratio, duplicate joint ref, missing `joint_b`) + 4 new in `test_headless_spec_build.py` (gear spec ≡ hand-call
canonical assembly; drives coupled wheel at ratio 2.0 + 0.5; geared assembly round-trips stable WITH its gear); full
suite **2418 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar now lowers
a declarative `{op:gear,joint_a,joint_b,ratio}` to the real AF-9 wrapper, and the spec-built gear is pinned BOTH
structurally (`assert_spec_matches_calls` — load-bearing because gears live in `canonical_assembly`) AND kinematically
(`assert_gear_ratio` — driving one joint of the *spec-built* assembly actually rotates the coupled wheel by the ratio,
so a gear that's registered but doesn't propagate fails). The genuinely-new validation power is two-fold: (1) the
parse-time `revolute` gate — a gear over a rigid mate is rejected before any build, mirroring the route's 400 up into
the pure grammar by tracking each mate ref's joint_type; (2) the joint-`ref` namespace itself, the first grammar
construct that lets one op reference the runtime output of two prior ops, which `belt`/`polymerize` now reuse. No
ASK-FIRST violation: `define_gear` + `assert_gear_ratio` are AF-9's direction-agnostic (magnitude-only) machinery;
this layer adds only parameter plumbing + the ref resolution.**"

**AF-11 — build-spec grammar growth (Phase 2): `belt` assembly op (relations cluster, sub-op 2)** · _shape:_
grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py` (`belt` allowed-key set
`{op,joint_a,joint_b,radius_a,radius_b,name}` + a parse branch validating positive `radius_a`/`radius_b`) **reusing
the gear's joint-`ref` namespace verbatim**: the referential-integrity pass's revolute-joint-ref check was widened
from `op == "gear"` to `op in ("gear","belt")` (so a belt `joint_*` must name a prior mate `ref` that is `revolute`,
rejecting belt-over-rigid + dangling joint refs at parse time) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.define_belt` (re-implements nothing — drives
the same `create_belt_path` route the gear-sibling drove for gears); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over the already-covered `create_belt_path` route;
wraps no new route, moves the oracle count not coverage — verified by the still-passing
`test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused BOTH `assert_gear_ratio` (AF-9,
LOAD-BEARING — handed the belt's synthetic relation id `f"__belt__{belt.id}"` + `expected_ratio = radius_a/radius_b`)
AND `assert_spec_matches_calls` (AF-11, also load-bearing here)**. Same deciding fact as gear: a belt is a top-level
`BeltPath` that `canonical_assembly` HAS fingerprinted since AF-9 (the 5-tuple), so `assert_spec_matches_calls` is a
real faithfulness pin (a dropped/rewired belt fails it) — but necessary-not-sufficient: the fingerprint catches a
*structurally* dropped belt, NOT a belt that's present but fails to *propagate*. `assert_gear_ratio` is the orthogonal
kinematic pin — drive `belt.pulley_a.joint_id` 30°, measure the coupled pulley's real instance-transform rotation,
assert driven/driver = `|radius_a/radius_b|` (parametrized 2:1 + 3:1) — which crucially passes the *radii* (not a
literal ratio) so it pins `_belt_to_relation`'s radius→ratio synthesis, distinct from the gear test · _tests:_ 8 new
in `test_build_spec.py` (belt normalisation incl. name; **5 rejections**: dangling joint ref, belt-over-rigid →
"must be 'revolute'", radius_a≤0, radius_b<0, missing `radius_b`) + 4 new in `test_headless_spec_build.py` (belt spec
≡ hand-call canonical assembly; drives coupled pulley at radius ratio 2:1 + 3:1; belted assembly round-trips stable
WITH its belt); full suite **2428 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the
grammar now lowers a declarative `{op:belt,joint_a,joint_b,radius_a,radius_b}` to the real AF-9 wrapper, and the
spec-built belt is pinned BOTH structurally (`assert_spec_matches_calls` — load-bearing because belts live in
`canonical_assembly`) AND kinematically (`assert_gear_ratio` — driving one pulley of the *spec-built* assembly
actually rotates the coupled pulley by the *rim-radius* ratio, so a belt that's registered but fails to propagate, or
whose radius→ratio synthesis is wrong, fails). The genuinely-new validation power over the gear sub-op is that the
spec passes pulley *radii* and the oracle asserts the *derived* `radius_a/radius_b` drives the coupling — if the
parser dropped a radius or the driver swapped `radius_a`/`radius_b`, the belt test goes red while the gear test stays
green. No ASK-FIRST violation: `define_belt` + `assert_gear_ratio` are AF-9's direction-agnostic (magnitude-only)
machinery; this layer adds only parameter plumbing, reusing the gear's revolute-ref gate by widening one condition.**"

**AF-11 — build-spec grammar growth (Phase 2): `polymerize` assembly op (relations cluster, sub-op 3)** ·
_shape:_ grammar growth only — 1 new assembly op in the PURE parser `backend/core/build_spec.py`
(`polymerize` allowed-key set `{op,joint,count,direction}` + a parse branch validating `count ≥ 2` and
`direction ∈ {forward,backward,both}`) **reusing the gear/belt joint-`ref` namespace** but referencing a
SINGLE seed mate (`joint`, not a pair) — and crucially **without** the revolute gate (polymerize replicates
the seed mate, it does not couple two revolute joints, so a referential-integrity branch checks only that
`joint` names a prior mate `ref` of ANY joint_type) + 1 dispatch branch in the driver
`backend/api/headless_spec_build.py` driving the REAL AF-9 wrapper `hab.polymerize` (re-implements nothing —
the driver resolves `joint_refs[p["joint"]]` and passes `count`/`direction`); `crud.py`/`assembly.py`/`main.js`
LOC Δ = **0** · _headless-coverage Δ:_ **32 → 32** (UNCHANGED — composition sugar over the already-covered
`polymerize_assembly` route; wraps no new route, moves the oracle count not coverage — verified by the
still-passing `test_spec_build_adds_no_coverage`) · _oracle shipped:_ **no new oracle — reused BOTH
`assert_spec_matches_calls` (AF-11, LOAD-BEARING) AND the geometric `assert_polymer_chain` (AF-9)**. Same
deciding fact as gear/belt: polymerize's new copies + replicated seam joints are top-level
instances/joints that `canonical_assembly` HAS fingerprinted since AF-7/8, so `assert_spec_matches_calls` is
a real faithfulness pin (a dropped copy or chain joint fails it) — but necessary-not-sufficient: the
fingerprint sees that N instances exist, NOT that they march along the seed's repeat. `assert_polymer_chain`
is the orthogonal geometric pin — it re-derives the seed mate's repeat `delta = T_B @ inv(T_A)` from the seed
pair alone (a synthetic seed-pair-only `before` projection of the spec-built assembly) and asserts the
`count−2` copies form the exact `delta`-power multiset, with the assertion that the +10 nm-X repeat the
connector snap produced is realised (parametrized count 4 + 6) · _tests:_ 7 new in `test_build_spec.py`
(polymerize normalisation incl. `both`; defaults direction→forward; **allows a rigid seed** — the no-revolute-gate
distinction from gear/belt; **3 rejections**: dangling joint ref, count<2, bad direction; missing `count`) + 4 new
in `test_headless_spec_build.py` (polymerize spec ≡ hand-call canonical assembly; lays count−2 copies on the
+10 nm delta lattice for count 4 + 6; polymerized assembly round-trips stable WITH its 2 replicated joints);
full suite **2444 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the grammar
now lowers a declarative `{op:polymerize,joint,count,direction}` to the real AF-9 wrapper, and the spec-built
chain is pinned BOTH structurally (`assert_spec_matches_calls` — load-bearing because the copies + seam joints
live in `canonical_assembly`) AND geometrically (`assert_polymer_chain` — the copies actually sit on the seed
mate's `delta`-power lattice, so a chain that's structurally present but laid off the repeat fails). The
genuinely-new validation power over the gear/belt sub-ops is the recognition (and pinning) that polymerize
takes a SINGLE seed `ref` and accepts ANY joint_type — the referential-integrity branch deliberately omits the
revolute gate gear/belt enforce, and `test_assembly_spec_polymerize_allows_rigid_seed` pins that distinction so
a future refactor can't silently over-constrain it. No ASK-FIRST violation: `hab.polymerize` +
`assert_polymer_chain` are AF-9's direction-agnostic (re-derives the documented fwd/back split, measures placed
geometry) machinery; this layer adds only parameter plumbing + the single-ref resolution.**"

**AF-15 — cluster rigid-transform wrappers (Phase 1): `add_cluster` / `transform_cluster` + translation oracle** ·
_shape:_ 2 wrappers in `backend/api/headless_build.py` (`add_cluster` imports `add_cluster` +
`AddClusterBody`; `transform_cluster` imports `update_cluster` + `PatchClusterBody` from `routes_clusters` —
exact route handlers, registers covered by function identity, NOT re-implemented) + 1 NEW reusable oracle
`assert_cluster_translated` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0**
(all new code is the existing headless module + the harness) · _headless-coverage Δ:_ **32 → 34** (`POST
/design/cluster` + `PATCH /design/cluster/{id}` flip to covered — the FIRST coverage gain since AF-9; AF-10/AF-11
were all composition-sugar) · _oracle shipped:_ `assert_cluster_translated(design_before, design_after,
cluster_id, *, translation, tol_nm=0.02, min_translation_nm=0.5)` — a **geometric** oracle: it reads the
cluster-posed helix axes from `deformed_helix_axes` (the geometry kernel's posed output — clusters apply at
geometry-compute time via `_apply_cluster_transforms_domain_aware`, never to the strand graph) on both designs and
asserts (1) every helix in the cluster has its posed `start`/`end` displaced by exactly the requested translation,
(2) every non-cluster helix is unchanged (the cluster-scoping property — the default catch-all cluster stays put),
(3) `‖translation‖ > min_translation_nm` (can-go-red guard — a zero translation makes every helix trivially
"unchanged" and the oracle pass vacuously). **Direction-AGNOSTIC** (a world-space translation is unambiguous — no
quaternion sign / pivot / frame convention to reason about → stays clear of the ASK-FIRST DNA-directionality rule;
**rotation poses deliberately out of scope**, they belong with Phase 2's edge-alignment flip/snap which IS a
directionality decision) · _tests:_ 5 new in `test_headless_build.py` (add_cluster creates a named non-default
identity-pose cluster; transform translates ONLY the cluster's 2 helices, parametrized over 2 vectors; clustered
pose survives a `.nadoc` round-trip AND still drives geometry after reload — the persistence pin
`canonical_topology` can't give; coverage flip) + 3 new in `test_automation_harness.py` (oracle passes on a real
translation + **two load-bearing red-tests**: claiming a translation the kernel didn't apply raises "did not
translate", and a zero translation trips the "vacuously" guard); repointed the AF-1 backlog-route coverage
meta-test from `/design/cluster` (now covered) to `/design/strand-end-resize` (still uncovered), and bumped
`test_spec_build_adds_no_coverage`'s expected count 32 → 34; full suite **2452 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-15 there was no way to group + pose a rigid cluster
headlessly, and — the deciding point — nothing could prove a cluster pose *flows into the geometry* or *persists*,
because `canonical_topology` is BLIND to the cluster-transform overlay (it lives outside the strand graph, the
third confirmed instance of that blind-spot after loop/skip and bend/twist), so `assert_roundtrip_stable` alone is
vacuous for the pose. `assert_cluster_translated` closes that by measuring the real posed helix axes the geometry
kernel emits (so a kernel that ignored the pose, mis-scaled it, applied it to the wrong frame, or leaked it onto
non-cluster helices fails), with a can-go-red guard + two red-tests. It's the geometric spine Phase 2's
`align_edge_transform` solver (and the 4-bar parallelogram capstone) pins itself against. The three-layer law is
honoured exactly: the wrappers pose a DISPLAY-layer rigid body, the oracle reads DISPLAY-layer geometry, and the
strand topology is never touched.**"

---

**AF-15 — cluster OBB enumerator + edge-alignment solver (Phase 2): `align_edge_transform` + `assert_edges_collinear`** ·
_shape:_ **NEW pure core** `backend/core/cluster_obb.py` (the `OBB` dataclass + `cluster_obb(design, cluster_id)`
equivariant enumerator with `edge_endpoints`/`corner`/`edges`, + the pure `align_edge_transform` solver — imports
`deformation.deformed_helix_axes` + scipy `Rotation`, NOTHING from `backend.api`) + 1 wrapper
`hb.align_cluster_edge` in `backend/api/headless_build.py` (calls the pure solver, then drives the already-covered
`transform_cluster`) + 1 NEW reusable oracle `assert_edges_collinear` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (new code is one new core module + the existing headless module +
the harness) · _headless-coverage Δ:_ **34 → 34** (UNCHANGED — `align_cluster_edge` wraps NO new route; it composes
`transform_cluster`, so like AF-10/AF-11 it's a construction-sugar/solver item, the oracle is the deliverable, not a
coverage flip — guarded by `test_align_cluster_edge_adds_no_coverage`) · _oracle shipped:_
`assert_edges_collinear(design, cluster_id, src_edge, *, target_edge|target_line, tol_nm=0.05, tol_deg=1.0,
min_len_nm=0.5)` — a **geometric** oracle: it recomputes the cluster's OBB on the POSED design and asserts the named
src edge is collinear with the target — (1) directions parallel-or-antiparallel within `tol_deg`, (2) both src
endpoints within `tol_nm` of the target line — with a non-degeneracy guard (edges longer than `min_len_nm`).
**Direction-AGNOSTIC** (a line, not a ray — both senses pass → no ASK-FIRST violation). The deeper deliverable is the
**equivariant OBB** itself, pinned by `test_obb_is_equivariant` (`OBB(g·design)=g·OBB(design)`): that property is what
makes a named edge refer to the same physical edge before/after the solve, so the oracle measures the edge the solver
intended · **ASK-FIRST conventions confirmed with the user (2026-06-17), NOT reasoned out:** minimal rotation /
auto-flip (≤90° onto ±target_dir) / midpoint snap (endpoints coincide) / roll left free · _tests:_ 11 new in
`test_cluster_obb.py` (OBB contains-snugly + right-handed-orthonormal + rejects degenerate/square footprints;
**equivariance parametrized over translation / Z-rotation / general screw**; solver: two-bar edge-snap, angled
world-line rotate+snap, align-to-rotated-bar 90°, auto-flip-to-minimal; coverage-unchanged guard) + 4 new in
`test_automation_harness.py` (oracle passes on a real alignment + **three red-tests**: edges left skew raise "off the
target line", wrong-angle raises "not collinear", and the equivariance pin doubles as the can-go-red proof); full
suite **2466 passed / 55 skipped**, no drop · _cohesion:_ `cluster_obb.py`'s one reason to change = the cluster OBB
geometry + edge-alignment math; dep surface = `deformed_helix_axes` + scipy `Rotation`, nothing from `backend.api` ·
**"Validation gained, not just a passthrough:** before this, nothing could align two rigid clusters by their OBB edges
headlessly, and — the load-bearing point — there was no Python OBB at all (it lived only in JS `joint_renderer.js`),
so no headless geometry could pin a kinematic-cluster arrangement. `assert_edges_collinear` proves the solved pose
actually lands the chosen edge on the target line (so a solver that mis-rotated, snapped to the wrong point, or
left the edges skew fails), recomputed on the real posed geometry. The genuinely-new, reusable validation power is the
**equivariant OBB** (`OBB(g·design)=g·OBB(design)`, proved) — the foundation AF-14's joint-axis placement and the 4-bar
parallelogram capstone both build on; without provable equivariance a named edge/corner picker is untrustworthy under
a pose. A subtle bug the equivariance test caught and banked: a value-argmax sign anchor ties on a rectangle's 4
symmetric corners and float-rounding flips the frame after a rotation — fixed with a positional (sorted-id) anchor.
Three-layer law honoured: the OBB READS the geometric layer (posed axes), the solver returns a DISPLAY-layer pose, the
strand topology is never touched.**"

---

**AF-14 — geometry-aware revolute-joint placement (Phase 1): `place_cluster_joint` + `hull_prism_axis` +
`assert_joint_on_hull_corner`** · _shape:_ 1 wrapper `hb.place_cluster_joint` in `backend/api/headless_build.py`
(imports the exact `add_joint` route handler + `AddJointBody` from `routes_cluster_joints` → covered by function
identity) + 1 pure helper `hull_prism_axis` (+ a new `OBB.face_normal` method) in the existing
`backend/core/cluster_obb.py` + 1 NEW reusable oracle `assert_joint_on_hull_corner` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (new code is the existing headless module + the existing core module +
the harness — NO god-file growth, NO new module) · _headless-coverage Δ:_ **34 → 35** (`POST
/design/cluster/{id}/joint` = `add_joint` flips to covered — a REAL route-wrapper item, the first coverage flip since
AF-15 Phase 1; the AF-15-P2 / AF-10 / AF-11 items in between were all construction-sugar) · _oracle shipped:_
`assert_joint_on_hull_corner(design, joint_id, *, edge=(axis,s1,s2) | corner=(su,sv,sw)+face=(axis,sign),
tol_nm=0.05, tol_deg=1.0)` — a **geometric** oracle: re-derives the placed joint's world axis from its cluster-LOCAL
storage + the cluster's current pose via `_local_to_world_joint` (so it measures where the axis really is after the
route's world→local→world conversion, honoring the local-frame round-trip on a *posed* cluster), recomputes the OBB
independently with the equivariant `cluster_obb`, and asserts — EDGE mode: the joint axis line is collinear with the
named edge (direction ∥/anti-∥ within `tol_deg` AND both edge endpoints within `tol_nm` of the joint line);
CORNER mode: the joint axis passes through the named corner (perp dist < `tol_nm`) AND its direction ∥/anti-∥ the
named face normal. **Direction-AGNOSTIC** (a line, not a ray — both senses pass → no ASK-FIRST sign/handedness
reasoning; the *swing sense* is Phase 2's ROM). Non-degeneracy guard (OBB edge longer than `min_len_nm`) · _tests:_
7 new in `test_cluster_obb.py` (`hull_prism_axis` edge-runs-along-edge / corner-pivots-along-face-normal / 4
rejections; `place_cluster_joint` lands-on-edge, passes-through-corner, **posed-cluster local-frame round-trip**,
coverage flip) + 5 new in `test_automation_harness.py` (oracle passes on a real edge + a real corner placement +
**two load-bearing red-tests**: a joint on edge (w,+1,+1) checked against the parallel-but-offset edge (w,−1,+1)
raises "off the joint axis line"; a joint at corner (+1,+1,+1) checked against corner (−1,+1,+1) raises "from
corner"; + af14-covered) + repointed the two coverage-count assertions (`test_align_cluster_edge_adds_no_coverage`,
`test_spec_build_adds_no_coverage`) 34 → 35; full suite **2478 passed / 55 skipped**, no drop · _cohesion:_
`hull_prism_axis` adds ONE reason to change to `cluster_obb.py` (named-OBB-feature → world axis), same dep surface
(the existing `cluster_obb` + numpy); `place_cluster_joint` is a thin route-driver · **"Validation gained, not just a
passthrough:** before AF-14 a revolute joint could only be placed by clicking a face of the hull approximation in the
gizmo — there was no headless entry, so no automated way to pin that a joint lands where you asked. `place_cluster_joint`
gives the entry and `assert_joint_on_hull_corner` proves the geometric promise: the placed joint's *real world axis*
(re-derived from its LOCAL storage, so it also exercises the world→local→world round-trip the route performs) lies on
the named OBB edge / passes through the named corner of an independently recomputed OBB — so a placer that snapped to
the wrong edge, mangled the world→local conversion, or used the wrong face normal fails. The posed-cluster test is the
sharp one: it places the joint on a translated+rotated cluster and the oracle still finds the axis on the edge,
proving the local-frame storage is drift-free (the whole point of storing the axis in local coords). Two red-tests
prove the green can go red. It's the per-joint geometry the AF-14 Phase-2 ROM selector and the 4-bar-parallelogram
capstone compose. Three-layer law honoured: placing a `ClusterJoint` is a topological/design-layer write, but the
hull-prism OBB it anchors to is a pure geometric *read* that never writes back.**"

**AF-14 — geometry-aware revolute-joint ROM (Phase 2): `cluster_range_of_motion` + `rank_joint_candidates` +
`assert_range_of_motion`** · _shape:_ pure swept-collision geometry added to the existing
`backend/core/cluster_obb.py` (`_obb_intersect` = Ericson 15-axis SAT; `_padded`/`_rotate_obb` helpers;
`obb_sweep_rom` = OBB-only per-step scan + 40-iter bisection of first contact in each sense; `cluster_range_of_motion`
= the design-level wrapper, anchored cluster swings vs. all others static; `rank_joint_candidates` = the 12 OBB edges
ranked by ROM) + 1 NEW reusable oracle `assert_range_of_motion` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is the existing core module + the harness — NO god-file
growth, NO new module) · _headless-coverage Δ:_ **35 → 35** (UNCHANGED — a construction/analysis item: it wraps NO new
route, it *reads* geometry; the deliverable is the oracle, not a coverage flip — like AF-10/AF-11/AF-15-P2) · _oracle
shipped:_ `assert_range_of_motion(design, cluster_id, axis, expected_deg, *, tol_deg=2.0, min_angle_deg=-180,
max_angle_deg=180, pad=HELIX_RADIUS, step_deg=2.0)` — a **geometric** oracle: computes the swept-OBB total two-sided
free swing about `axis` and asserts it == `expected_deg ± tol_deg`, with a physical-bound guard (`0 ≤ ROM ≤ max−min`).
**ASK-FIRST decisions confirmed by the user (2026-06-17):** (1) the *anchored* cluster is the moving body, every
other cluster a static obstacle; (2) ROM is the **total two-sided magnitude** θ⁺+θ⁻ (each clamped to the angular
limit) — direction-AGNOSTIC, no handedness, so it stays clear of the ASK-FIRST DNA-directionality rule the way AF-6
did; (3) each OBB is **padded by the helix radius** (~1 nm) so two bundles register contact rim-to-rim rather than
when their axis boxes overlap · _tests:_ 7 new in `test_cluster_obb.py` (SAT overlap/separation; **synthetic
rod+double-wall analytic** ROM = `2·(asin(Y0/√(L²+w²))−atan2(w,L))` to <1°, an independent closed-form derivation NOT
the SAT sweep; no-obstacle full-limit for 360° and a custom ±90°; lone-cluster full swing; **obstacle-reduces +
monotonic** on real bars; `rank_joint_candidates` sorted-by-ROM + door-jamb variation + target filter; oracle pass +
wrong-angle red) + 3 new in `test_automation_harness.py` (oracle passes on a lone cluster's full swing + **two
load-bearing red-tests**: a free 360° swing checked against 180° raises; a neighbour-blocked joint checked against
360° raises while the true reduced value passes) ; full suite **2488 passed / 55 skipped**, no drop · _cohesion:_ the
ROM block adds ONE reason to change to `cluster_obb.py` (swept-OBB clearance of a cluster about an axis), small dep
surface (the existing `cluster_obb`/`hull_prism_axis` + numpy/scipy `Rotation`) · **"Validation gained, not just a
passthrough:** before AF-14 P2 nothing could compute — let alone pin — how far a revolute-jointed cluster can swing
before it collides with a neighbour. `assert_range_of_motion` gives that, and its trustworthiness rests on TWO
independent legs: the analytic precision is proved on a synthetic rod-and-wall fixture whose contact angle is a
closed-form `asin`/`atan2` expression (so a bug in the SAT or the bisection would diverge from the trig), and the two
can-go-red guards are proved on real DNA bars (a lone cluster swings the full limit; pushing a neighbour into the
swing path strictly and monotonically shrinks the ROM). So a ROM that over-/under-counted contact, ignored the helix
pad, or escaped its angular limits fails. This is the swept-clearance spine the 4-bar-parallelogram capstone and the
AF-12 linkage-mobility check compose; `rank_joint_candidates` makes the door-jamb principle quantitative (the
interface hinge swings least, the away-facing hinge swings free). NB construction-sugar item: coverage flat by design
— the pass criterion was always the oracle.**"

---

**CAPSTONE — the headless 4-bar parallelogram (first headless kinematic mechanism)** · _shape:_ 1 new pure helper
`grubler_mobility(n_links, *, revolute, prismatic, higher)` in `backend/core/cluster_obb.py` (planar Kutzbach DOF —
`3(n−1)−2·lower−higher`, pure combinatorics, no geometry) + 1 reusable oracle `assert_parallelogram_linkage` in
`tests/automation_harness.py` + a reusable builder + integration test in NEW `tests/test_parallelogram_linkage.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is `backend/core` + the harness + a new test module) ·
_headless-coverage Δ:_ **35 → 35** (UNCHANGED — pure composition of already-covered wrappers `create_bundle` /
`add_cluster` / `update_cluster` (via `align_cluster_edge`) / `add_joint` (via `place_cluster_joint`); wraps no new
route, so like AF-10/AF-11/AF-15-P2 it moves the oracle count, not coverage — `test_parallelogram_wraps_no_new_route`
pins it) · _oracle shipped:_ `assert_parallelogram_linkage(design, bar_ids, *, joint_ids, tol_nm=0.1, tol_deg=2.0,
expected_dof=1, min_area_nm2=1.0, require_movable=True)` — a **composed geometric + kinematic** oracle measured on the
*posed* OBBs (recomputed, never trusting the solver's claimed transform): (1) **closed quadrilateral** — adjacent bars
share an OBB corner (the hinge point), the 4 shared corners enclose area > `min_area_nm2` (the non-degeneracy guard:
four collinear/collapsed bars fail); (2) **parallelogram** — opposite bars' long axes parallel-or-antiparallel within
`tol_deg` AND equal-length within `tol_nm`; (3) **mobility** — `grubler_mobility(4, revolute=len(joint_ids))` ==
`expected_dof`; (4) **each hinge movable** — each joint's world axis (re-derived from cluster-LOCAL storage via
`_local_to_world_joint`, the placed axis) admits a nonzero swept-OBB ROM vs. the non-adjacent (non-pinned) bars.
Direction-AGNOSTIC throughout · _tests:_ 4 in `test_parallelogram_linkage.py` (full capstone is 1-DOF + each hinge on
its shared-corner edge + adjacent bars share exact corners + wraps-no-route) + 3 grübler unit tests in
`test_cluster_obb.py` (four-bar=1, textbook cases, bad-input reject) + 3 harness meta-tests in
`test_automation_harness.py` (oracle passes on a real mechanism + **two load-bearing red-tests**: 3 joints → mobility 3
≠ 1 raises, one bar shoved away → closure raises); full suite **2498 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before the capstone, every kinematic-cluster oracle pinned ONE
construction step in isolation (`assert_edges_collinear` = one alignment, `assert_joint_on_hull_corner` = one joint,
`assert_range_of_motion` = one swing); nothing validated that *composing* them with the headless wrappers yields a
working mechanism. `assert_parallelogram_linkage` is the first **assembled-mechanism** oracle: it proves four bars
edge-aligned + hinged headlessly form a genuine closed, parallel, 1-DOF four-bar linkage (so a build that mis-aligned a
bar, dropped a joint, or collapsed the loop fails), and `grubler_mobility` makes the DOF claim a rigorous combinatorial
statement reusable for any planar linkage (the AF-12 layer). The two red-tests prove the green can go red on a wrong
joint count and a broken loop. This is the AF-12 linkage-mobility (Grübler) demo the AF-14/AF-15 geometry was built
toward — the validation is 'the assembled mechanism has the expected DOF and every hinge is movable.' NB
composition-only (coverage flat by design): the pass criterion was always the oracle.**"

---

**AF-11 — build-spec grammar growth (Phase 2): `auto_scaffold` / `auto_crossover` / `full_autostaple` / `apply_loop_skips`
design ops** · _shape:_ grammar growth only — 4 new design ops in the PURE parser `backend/core/build_spec.py`
(`auto_scaffold` allowed-keys `{op, seamless}`; `auto_crossover` / `apply_loop_skips` `{op}` only; `full_autostaple`
`{op, scaffold_name, custom_sequence, strand_id}` — all NON-primordial, so none may be the first op) + 4 dispatch
branches in the driver `backend/api/headless_spec_build.py` driving the REAL existing wrappers
(`hb.auto_scaffold` / `hb.auto_crossover` / `hb.full_autostaple` / `hb.apply_loop_skip_deformations` — re-implements
nothing); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **35 → 35** (UNCHANGED — composition
sugar over already-covered wrappers, wraps no new route; `test_spec_build_adds_no_coverage` still green at 35) ·
_oracle shipped:_ **no new oracle — reused `assert_spec_matches_calls` (AF-11) as the LOAD-BEARING augment for the three
routing ops** (`auto_scaffold`/`auto_crossover`/`full_autostaple` ADD a scaffold strand / crossover domain-transitions /
broken-merged staples that `canonical_topology` SEES — so the golden pin is genuinely load-bearing: the hand reference
runs the real auto ops, so a driver that silently dropped one would diverge and fail; a non-vacuity test confirms the
routed topology ≠ a bare bundle) **+ reused the AF-3 per-helix `geometric_nucleotide_count` conservation check as the
LOAD-BEARING augment for `apply_loop_skips`** (its baked marks live on `Helix.loop_skips`, OUTSIDE the strand graph, so
`assert_spec_matches_calls` is BLIND to them — the same AF-3/loop_skip lesson; the geometric per-helix law
`Δgeometry == 2 × net marks` is the only thing that proves the marks flowed spec → parser → wrapper → geometry
helix-by-helix). The session's keystone: `apply_loop_skips` was DEFERRED until a spec op could place crossovers — its
route 400s without them — and `auto_crossover` now produces exactly those, so both landed together (a
`test_apply_loop_skips_spec_requires_crossovers` red-test proves the route really runs by 400ing on a bare bundle) ·
_tests:_ 2 grammar normalisation (routing-ops defaults + fields) + 7 grammar rejections (4× can't-be-first, seamless
non-bool, full_autostaple typo'd field, auto_crossover extra field) in `test_build_spec.py` + 7 driver tests in
`test_headless_spec_build.py` (auto_scaffold+crossover spec ≡ hand-calls; routed-topology ≠ bare bundle non-vacuity;
full_autostaple spec ≡ hand-calls; full_autostaple round-trips stable; apply_loop_skips per-helix conservation;
apply_loop_skips requires-crossovers 400); full suite **2513 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** the grammar now lowers declarative bulk-routing ops to the real
scaffold/crossover/autostaple wrappers, and a spec-routed design is *proven byte-identical in canonical topology* to the
equivalent hand-clicked routing (`assert_spec_matches_calls` is load-bearing here — unlike bend/twist/loop_skip — because
the routing ADDS strands the fingerprint sees). Separately, `apply_loop_skips` — finally reachable now that
`auto_crossover` can place the crossovers its route demands — is proven to bake the SQUARE periodic-skip pattern with the
per-helix conservation law `Δgeometry == 2 × net marks` (no mark leaks between helices or is dropped), the only pin that
catches a dropped overlay the canonical fingerprint can't see. This closes the last DEFERRED design-op in the AF-11
Phase-2 grammar. No ASK-FIRST violation: every wrapper + oracle is already-cleared direction-agnostic machinery; this
layer adds only parameter plumbing + the parse-time grammar gates.**"

**AF-14 — Phase 3 hinge-joint recommender (`recommend_hinge_joints`) + corner anchoring** · _shape:_ pure
selector in `backend/core/cluster_obb.py` (`recommend_hinge_joints` — reuses the equivariant OBB +
`obb_sweep_rom`; imports nothing from `backend.api`) + an `anchor="midpoint"|"corner"` option threaded through
`hull_prism_axis` and the `hb.place_cluster_joint` wrapper (`headless_build.py`) + 1 reusable oracle
`assert_recommended_hinge` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ **35 → 35** (UNCHANGED — `recommend_hinge_joints` wraps NO route; the `anchor` option
drives the SAME already-covered `add_joint` route, so like AF-10/AF-15-P2 this moves the oracle count, not
coverage — verified by `test_recommend_hinge_adds_no_coverage`) · _oracle shipped:_
`assert_recommended_hinge(design, cluster_id, *, recommendations=None, axial_tol_deg=20, tol_nm=0.05,
length_tol_nm=0.1)` — re-measures on the **independently recomputed** equivariant OBB that the #1 recommendation
(1) is non-axial (edge angle to the helical `w` axis > `axial_tol_deg` — a fold, not a barrel-roll), (2) is the
**longest** non-axial edge (within `length_tol_nm`), and (3) is **corner-anchored** (stored `axis_origin`
within `tol_nm` of an edge endpoint, not the midpoint). Direction-AGNOSTIC (edge length + angle-to-axis are
magnitudes; ROM is the two-sided total). Injectable `recommendations=` seam so the red-tests feed a mangled
list · _tests:_ 7 new in `test_cluster_obb.py` (top is the wide `u`-edge non-axial corner-anchored; axial
`w`-edges demoted to the last 4 + flagged; corner-vs-midpoint anchor differ by half the edge length on the same
line; `target_rom_deg` filter; corner-anchored joint still passes `assert_joint_on_hull_corner` edge mode;
bad-anchor `ValueError`; no-coverage) + 3 harness meta-tests (passes on a real bar + **two load-bearing
red-tests**: an axial edge hand-ranked #1 raises "axial", a midpoint-anchored top raises "corner-anchored");
full suite **2523 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-14
P3 the only hinge ranker was `rank_joint_candidates`, which sorts by ROM ALONE — it would happily return an
axial `w`-edge (a barrel-roll about the bundle axis, kinematically useless) as #1 if that edge happened to swing
freest, and it anchored every joint at the edge midpoint. `recommend_hinge_joints` encodes the user's actual
design intent (the hinge is the longest cross-section *fold* edge, anchored at a face corner) and
`assert_recommended_hinge` *proves* the ranker honours it — that the top pick is a fold not a barrel-roll, is
the widest such edge, and is corner-anchored — none of which the ROM-only sort or any prior oracle asserted. The
two red-tests prove the green can go red on the exact two ways the recommendation can be wrong (axial-on-top,
midpoint-anchor). The corner-vs-midpoint anchor check is reusable for any 'named point on a named edge'
placement. No ASK-FIRST violation: all magnitudes (length, angle-to-axis, two-sided ROM), zero sign/handedness
reasoning.**"

**AF-16 — loggable cluster creation (`cluster_create` feature-log entry)** · _shape:_ NEW `ClusterCreateLogEntry`
Pydantic model in `backend/core/models.py` (mirrors `ClusterOpLogEntry`: `feature_type='cluster_create'`,
`cluster_id`/`name`/`helix_ids`/`domain_ids: List[DomainRef]`) added to the `FeatureLogEntry` discriminated union +
opt-in `log: bool = False` on the `add_cluster` route (appends the entry inside the same `copy_with(...)`, with the
cursor-truncation `update_cluster`'s commit+log path uses) + a `log=` passthrough on the `hb.add_cluster` wrapper
(default OFF — backward-compatible) + 1 reusable oracle `assert_cluster_in_feature_log` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (model in `core`, wiring in the
already-extracted `routes_clusters.py` sub-router, wrapper in `headless_build.py`) · _headless-coverage Δ:_ **35 →
35** (UNCHANGED — `add_cluster` was already covered since AF-15 P1; AF-16 adds the *log path* on an existing route,
wraps no new route — like AF-10/AF-11 it moves the oracle count, not coverage) · _oracle shipped:_
`assert_cluster_in_feature_log(design, cluster_id, *, expect_helix_ids=None)` — a **feature-log integrity** oracle:
asserts exactly one `cluster_create` entry carries `cluster_id`, its `helix_ids` are exactly the live cluster's set
(or `expect_helix_ids`), and its `name` matches. The deciding fact (4th confirmation of the blind-spot lesson):
`canonical_topology` does NOT fingerprint clusters (they're a display/geometry-layer grouping outside the strand
graph — same as loop/skip marks, deformation overlays, cluster poses), so `assert_roundtrip_stable` *cannot* prove
the grouping persisted — only the feature-log entry can; call the oracle on a `roundtrip_nadoc` result to pin
`.nadoc` survival · _tests:_ 3 new in `test_headless_build.py` (log=True records the entry with the right helices;
the entry survives a `.nadoc` round-trip; the default log=False appends NO entry — backward-compat + can-go-red) +
3 new in `test_automation_harness.py` (oracle passes on a logged creation + **two load-bearing red-tests**: an
unlogged build raises "created without logging", a mismatched `expect_helix_ids` raises "does not match the
cluster"); full suite **2529 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before
AF-16 there was no `ClusterCreateLogEntry` type at all — `add_cluster` built the cluster in design state but emitted
nothing to the feature log, so a generated multi-bar part's construction history could record the bars' *poses*
(`cluster_op`) and *joints* but never the *grouping* that created them; a user replaying the log saw bars appear
fully-formed with no creation step. AF-16 makes the grouping loggable AND `assert_cluster_in_feature_log` proves
the entry names the right cluster + exact helices AND survives a round-trip — none of which any prior oracle could
assert (canonical_topology is structurally blind to clusters). The two red-tests prove the green can go red on the
two real failure modes (unlogged build, wrong helix set). It's the feature-log-integrity spine for any future
display-layer grouping/overlay that needs a loggable, round-trip-durable construction step. No ASK-FIRST violation:
creating a cluster is a pure grouping, never a topology or directionality edit.**"

---

**Full-sequencing automation — `full_sequence` + `assign_staple_sequences` wrappers + `assert_fully_sequenced`**
· _shape:_ 2 wrappers in `backend/api/headless_build.py` (`assign_staple_sequences` imports the exact
`assign_staple_sequences_endpoint` route handler → covered by function identity; `full_sequence` is composition
sugar that assigns the scaffold sequence to every scaffold strand then drives `assign_staple_sequences`) + 1 reusable
oracle `assert_fully_sequenced` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_headless-coverage Δ:_ design/assembly **35 → 36** (`/design/assign-staple-sequences` flips to covered — the WC-
complement-every-staple op had no headless entry; `full_sequence` itself wraps no new route, it composes the
already-covered scaffold + the newly-covered staple wrappers) · _oracle shipped:_ `assert_fully_sequenced(design, *,
require_wc=True)` — asserts zero undefined bases (the `count_undefined_bases` gate every export / `create_oxdna_job`
path uses) AND that every scaffold-paired staple base is the Watson-Crick complement of its scaffold base, walked
*independently* of the assignment code; returns the count of WC positions verified, with non-vacuity guards on both
checks · _tests:_ 4 new in `test_headless_build.py` (full_sequence leaves no undefined base on a routed single-
scaffold 6hb; `assign_staple_sequences` alone 422s without a scaffold sequence; full sequencing survives a `.nadoc`
round-trip; coverage flip) + 3 new in `test_automation_harness.py` (oracle passes on a sequenced design + **two
load-bearing red-tests**: an unsequenced design raises "undefined", a corrupted staple base raises "WC complement");
full suite **2544 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** the headless
surface could route a design (`auto_scaffold`/`auto_crossover`/`auto_break`) and assign a *scaffold* sequence, but
there was no programmatic way to finish the job — WC-complement the staples — so a headless-built design could not be
made export / oxDNA ready without borrowing a test helper (`_sequence_for_oxdna`, exactly the gap AF-13 P1 hit).
`full_sequence` closes that, and `assert_fully_sequenced` proves the result is *complete AND correct* (no `'N'` AND
genuinely complementary, checked against the scaffold independently of the assignment code) — so a builder that left
positions undefined, or filled them with the wrong base, fails. The two red-tests prove the green can go red. NB:
the staple complement comes from the single active scaffold, so `full_sequence` needs a routed single-scaffold
origami (`auto_scaffold` first) — documented on the wrapper.**"

---

**AF-13 — headless oxDNA relaxation (Phase 1: drive + recover)** · _shape:_ **NEW module**
`backend/api/headless_oxdna_build.py` (the first *physical-layer* headless builder — distinct lifecycle subsystem,
rule 2; mirrors `headless_assembly_build.py`): `run_relaxation` (one-call: create-no-autostart → start → poll to
terminal) + `create_job`/`start_relaxation`/`append_production`/`read_relaxed_positions`/`wait_for_terminal`, each
importing the exact route handler — `create_oxdna_job`/`start_oxdna_job`/`append_oxdna_production`/`get_oxdna_display`
— so they register covered by function identity, NOT re-implemented. Two isolation context managers
(`_use_workspace` redirects the routes' module-global `routes_oxdna._WORKSPACE_DIR`; `_scratch_design` binds the
design into a throwaway doc) so a scripted relaxation never touches the real workspace / active design. The route
handlers are `async` → driven via `asyncio.run`. + 1 reusable oracle `assert_relaxed_geometry_recovered` in
`tests/automation_harness.py` + NEW **separate** `oxdna_coverage_report()` (refactored the existing report into a
shared `_coverage_report(modules, path_predicate)` core so `headless_coverage_report()`'s output is byte-identical —
still 35); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a new module + the harness) ·
_headless-coverage Δ:_ design/assembly **35 → 35** (untouched — oxDNA is a separate surface); NEW oxDNA audit shows
**3 `/oxdna` mutation routes covered** (`create_oxdna_job` + `start_oxdna_job` + `append_oxdna_production`;
`get_oxdna_display` is a read-only GET, correctly absent from the mutation audit, pinned by an import-identity test) ·
_oracle shipped:_ `assert_relaxed_geometry_recovered(job, design, workspace, *, expected_count=None)` — a
**physical-layer recovery** oracle: asserts (1) the terminal `OxdnaJob` reached `completed`; (2) the display route
reads the relaxed `last_conf` back (`ready`) via `read_configuration_unwrapped` (PBC-unwrapped + Kabsch-aligned);
(3) the recovered map has exactly one **finite** position per design nucleotide AND every recovered
`(helix_id, bp, direction)` key is a real key of the design's geometry (set-equal, so a dropped/truncated/mis-keyed
conf is caught). **Physical-layer only** — it reads the relaxed geometry, never asserts it was written into `Design`
(the Three-Layer Law) · _tests:_ 7 new in `test_headless_oxdna_build.py` (run_relaxation completes + recovers
geometry; create→start two-step; append-production extends a completed job + still recovers; coverage flip;
import-identity; + **two load-bearing red-tests**: a non-completed job raises "did not reach completed", a wrong
expected_count raises "expected …") + 1 new in `test_automation_harness.py` (oxDNA audit is separate + design/assembly
stays 35 + the 3 routes covered); runs against the mock binary (`$OXDNA_BIN`), `min_bp_retained=0.0` since the mock
copies conf→last_conf rather than relaxing; full suite **2537 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-13 the physical layer was browser-only — there was *no way
at all* to relax a design and recover the result without the Dynamics panel, and therefore nothing pinned that a
headless relaxation runs to completion and yields readable relaxed geometry. `assert_relaxed_geometry_recovered` is
the first physical-layer oracle: it drives a real oxDNA job to `completed` and proves the relaxed last frame reads
back as a full per-nucleotide position map (count + finiteness + key-coverage), so a builder that failed silently,
dropped nucleotides, or returned an unreadable conf fails — with two red-tests proving the green can go red. It is
the spine the AF-13 P2+ measurement/constraint oracles (the stochastic measured-property-within-tolerance class) pin
themselves against — the physical-layer analog of what AF-1 did for designs and AF-7 for assemblies. No ASK-FIRST
violation: Phase 1 exposes ONLY the read path and asserts a count/coverage property, no geometry/directionality
reasoning (the landmark-direction question is deferred to Phase 2, where the backlog flags it ASK-FIRST).**"

---

**AF-13 — relaxed-geometry MEASUREMENT oracle (Phase 2: the constraint primitive)** · _shape:_ **service + oracle
push** — pure `measure_end_to_end(positions, a, b)` in `backend/core/oxdna_health.py` (the reusable `measure_*`
primitive; Euclidean nm between two landmark backbone sites; raises on empty/identical/absent) + 1 read-wrapper
`read_flexibility_map(job_id, ws)` in `backend/api/headless_oxdna_build.py` (drives the REAL `get_oxdna_rmsf`
route handler — registers covered by function identity — for the pooled noise-averaged mean structure +
`confidence`) + 1 reusable oracle `assert_relaxed_measurement` in `tests/automation_harness.py`;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** (all new code is a pure core fn + the existing headless module +
the harness) · _headless-coverage Δ:_ **UNCHANGED** (oxDNA mutation routes still 3; `get_oxdna_rmsf` is a
read-only GET, like `get_oxdna_display` — excluded from the *mutation* audit, pinned instead by the
import-identity test `hox._route_get_rmsf is routes_oxdna.get_oxdna_rmsf`) · _landmark convention (ASK-FIRST,
answered by user):_ the raw **`(helix_id, bp_index, direction)` tuple** — most primitive, indexes the
relaxed-display + RMSF maps directly, no strand-polarity/terminus resolution (a strand-terminus convenience layer
can sit on top later) · _oracle shipped:_ `assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *,
workspace, min_confidence=RMSF_PRELIM_FRAMES)` — the **first STOCHASTIC-class oracle**: status-completed guard +
reads the production mean structure (preferred over a single frame — the mean cancels thermal noise) + **the
confidence gate** (≥ `min_confidence` pooled frames, else INCONCLUSIVE-raise — a too-short run cannot certify a
target; the load-bearing guard AF-13 P3 formalises) + measured ∈ [target ± tol]. `measure_spec =
{"measure":"end_to_end","landmarks":[a,b]}` · _tests:_ 3 pure in `test_oxdna_relaxation.py` (exact distance +
order-independence; Direction-enum/str normalisation; rejects empty/identical/absent) + 5 in
`test_headless_oxdna_build.py` driving a purpose-built trajectory-writing mock (mean+confidence readback;
end-to-end matches the design's own e2e to ~0.002 nm at tol 0.1; **3 load-bearing red-tests**: wrong target raises
"not within", 10 pooled frames < 50 raises "INCONCLUSIVE", no production run raises "no production mean
structure") + 1 import-identity assert; full suite **2552 passed / 55 skipped**, no drop ·
**"Validation gained, not just a passthrough:** before AF-13 P2 there was no way to *measure* a property of a
relaxed structure headlessly, and AF-13 P1 only proved geometry reads back — nothing asserted a
user-meaningful physical quantity (an end-to-end distance) is correct *and trustworthy*. `assert_relaxed_measurement`
closes that: it measures the noise-averaged mean structure (not a single noisy frame) and asserts the value within
tolerance ONLY when enough frames are pooled — the confidence gate is genuinely new validation power, because a
measured-property oracle without it would certify a target from a 1-frame run that's pure thermal noise. On the
identity-mock fixture the relaxed mean reproduces the design's own end-to-end to ~0.002 nm (a 0.1 nm pin), proving
the whole physical-layer measurement pipeline (drive production → pool → mean → address two landmarks → Euclidean
distance) is faithful; the 3 red-tests prove the green can go red on a wrong target, too-few frames, and a missing
production run. It is the stochastic-oracle spine AF-13 P3's declarative constraint checker + P4's iterate-until-met
loop both build on. No ASK-FIRST violation: the landmark convention was asked + answered (raw tuple), and the
measurement is a direction-agnostic Euclidean magnitude — no bend/sign/frame reasoning.**"

**AF-13 Phase 3 — declarative constraint spec + pure REPORTING checker** · _shape:_ **service + oracle push** —
2 pure HTTP-free fns in `backend/core/oxdna_health.py` (`parse_constraint_spec` validates+normalises a
`{measure, landmarks, target_nm, tol_nm, min_confidence}` spec, raising `ConstraintSpecError` at parse time;
`check_relaxed_constraint(constraint, relaxed_output)` REPORTS `{met, status, measured_nm, target_nm, tol_nm,
n_frames, min_confidence, confidence}` by reusing the P2 `measure_end_to_end` primitive over the
`read_flexibility_map` mean-structure dict) — NO route wrapped, `backend/api`/`backend/core` boundary respected
(the checker takes the already-read relaxed dict, never imports the api read-wrapper);
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **UNCHANGED** (composition over P2's
already-pinned read path + pure core math; wraps no new route — like AF-10/AF-11 it moves the oracle/primitive
count, not coverage) · _oracle/augment shipped:_ the **confidence-gated constraint REPORTER** itself
(`check_relaxed_constraint`) + its can-go-red test set — distinct from P2's *asserter* (`assert_relaxed_measurement`,
which raises in a test): the checker returns a verdict an automated loop branches on, with `status ∈
{met, unmet, inconclusive}` and the **load-bearing invariant `met` is NEVER True below `min_confidence`**. Pinned
by (a) 13 parametrized `parse_constraint_spec` rejections (bad dict/key/measure/landmark-count/identical/bp_index/
triple/target/tol/min_confidence) + idempotency + default-min_confidence; (b) the met/unmet tolerance bracket
(target 4.5 tol 0.5 → met at |Δ|=0.5; target 4.4 → unmet at 0.6); (c) **the confidence-gate red-test** — a value
squarely within tolerance but only 10 frames pooled reports `inconclusive`/`met=False` (flip the guard and it goes
red); (d) two integration tests driving a REAL `_MOCK_OXDNA_TRAJ` run → `read_flexibility_map` → checker (60-frame
→ met; 1000-step/10-frame → inconclusive-not-met), proving the checker consumes the actual relaxed-output dict
shape and the gate fires on a genuine under-sampled production · _tests:_ 20 new in `test_oxdna_relaxation.py`
(pure) + 2 new in `test_headless_oxdna_build.py` (real-run integration); full suite **2574 passed / 55 skipped**,
no drop (P2 baseline was 2552) · **"Validation gained, not just a passthrough:** before P3 there was only the
*asserting* oracle (P2's `assert_relaxed_measurement`, which raises inside a test); nothing gave a closed-loop
builder a *verdict to branch on* with the safety guarantee that it cannot certify `met` from an under-sampled
run. `check_relaxed_constraint` is that contract — a pure, tested decision function whose load-bearing,
red-tested invariant is "never report met below `min_confidence`, even when the value is within tolerance." That
is the exact guard AF-13 P4's iterate-until-met loop needs to avoid converging on thermal noise, and the
`parse_constraint_spec` rejection set is itself new validation power (a malformed constraint fails at parse time,
before any expensive relaxation runs). It slots into the AF-11 build-spec grammar as a design `constraints`
block. No ASK-FIRST: reuses P2's already-cleared landmark convention + direction-agnostic Euclidean measure;
this layer adds only spec validation + the confidence-gated met/unmet/inconclusive decision.**"

---

**AF-17 — headless simulation Benchmark access + relaxation auto-tune bridge** · _shape:_ **service + headless
wrappers** — 1 pure fn in `backend/core/benchmark.py` (`resolve_oxdna_relax_config(hw)` maps a stored
`HardwareBenchmark` → the `{backend, device}` a relaxation should use, CPU/"0" fallback when none; PURE, no I/O /
no hostname lookup — the caller selects the slot) + 3 wrappers in `backend/api/headless_oxdna_build.py`
(`run_oxdna_benchmark` drives the REAL `benchmark_runner.run_oxdna_trials` sweep inline against a size-matched
synthetic proxy, injectable `runner=`/`configs=` so the CUDA branch is exercisable GPU-free; `apply_oxdna_benchmark`
writes a recommendation into a COPY of the design's `metadata.hardware_defaults[hostname]`, mirroring the apply
route on a passed design; `run_relaxation_tuned` resolves that default → backend/device → `run_relaxation`, the
bridge for the iterate-until-met loop) + 1 reusable oracle `assert_relax_honors_hardware_default` in
`tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _headless-coverage Δ:_ **UNCHANGED**
(the benchmark routes are `/benchmark/*`, outside the design/assembly mutation audit; the sweep wrapper drives the
runner functions directly, not a route handler — like AF-10/AF-11 this moves the oracle count, not coverage) ·
_oracle shipped:_ `assert_relax_honors_hardware_default(design, workspace, *, backend, device="0", **params)` — a
**physical-layer bridge** oracle: (1) baseline — `run_relaxation_tuned` on a design with NO benchmarked default must
complete on the CPU/"0" fallback (also proving the non-CPU result below comes from the stored default, not a
constant); (2) tuned — apply `{backend, device}`, relax again, assert the terminal `OxdnaJob` carries that exact
backend/device (the metadata flowed benchmark→`hardware_defaults`→relaxation config, read straight off
`OxdnaJob.backend`/`.device`); (3) non-vacuity — the requested config must differ from the CPU fallback, so the
oracle is only meaningful for a non-default config (`backend="CUDA"`, `device="1"`). GPU-free: the mock binary
ignores the declared backend · _tests:_ 7 new in `test_headless_oxdna_build.py` (pure resolve+fallback; headless
sweep produces a well-formed recommendation; injected 2-config grid drives the real pick-best → CUDA wins;
the bridge oracle green; full producer→apply→relax chain; **two load-bearing red-tests**: a bridge that hard-codes
CPU raises "did not honour the benchmarked default", and a vacuous CPU/0 request is rejected); full suite **2678
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before AF-17 the Benchmark button's
auto-tuned config was written to `metadata.hardware_defaults` and read ONLY by the frontend to pre-fill the panel —
**no backend path consumed it into a run**, so nothing proved the discovered device ever reaches oxDNA, and an
automated loop had no way to run a benchmark or relax on its result. `assert_relax_honors_hardware_default` closes
that end-to-end: it proves a stored hardware default flows benchmark→metadata→relaxation backend/device (CUDA:1
lands in the oxDNA job; an un-tuned design falls back to CPU), with a non-vacuity guard + a red-test proving a
bridge that ignored the default goes red. That is the exact capability AF-13 P4's iterate-until-met loop needs to
relax on the fastest discovered backend instead of a hard-coded CPU default. No ASK-FIRST: this is hardware-config
plumbing (backend/device strings), not DNA topology/geometry — zero sign/frame reasoning.**"

---

**AF-13 Phase 4 — iterate-until-met loop (the Tier-5 CAPSTONE)** · _shape:_ **composition driver** — 1 loop driver
`iterate_to_constraint` + 1 helper `_pool_until_conclusive` in `backend/api/headless_oxdna_build.py` (composes the
already-covered `run_relaxation`/`run_relaxation_tuned` + `append_production` + `read_flexibility_map` wrappers +
the pure `parse_constraint_spec`/`check_relaxed_constraint`; re-implements NOTHING) + 1 reusable oracle
`assert_converges_to_constraint` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — composition-sugar over covered wrappers + a pure-core
reporter, like AF-10/AF-11; moves the oracle count, not the coverage count) · _oracle shipped:_
`assert_converges_to_constraint(result, *, target_nm, tol_nm, min_confidence=RMSF_PRELIM_FRAMES)` — asserts the loop
reached `status=="met"` within budget, the **winning** verdict is `met` AND pooled from ≥`min_confidence` frames, NO
intermediate iteration flipped `met` below the gate, the final measured value is within `tol_nm`, and — the
non-vacuity guard — the FIRST attempt was NOT already met (so the adjust loop was actually exercised). The driver
branches on the P3 verdict **status**, never the raw `measured_nm`; on `inconclusive` it appends MORE production to
the same job (the rmsf route pools every production stage → frames accumulate) until the gate clears, NOT a knob
change · _tests:_ 5 new in `test_headless_oxdna_build.py` (bend-curvature knob + bisection converges + oracle passes;
inconclusive→grow-production with the knob held on-target so the adjust_fn must never fire; **two load-bearing
red-tests**: an unreachable target exhausts and the oracle raises "did not converge"; an attempt-0 win raises the
non-vacuity guard; + a fail-fast `ConstraintSpecError` on a malformed constraint before any run); full suite **2732
passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before P4 the pieces existed
(P1 relax, P2 measure, P3 confidence-gated checker, AF-6 deformation knobs, AF-17 tuned relax) but nothing proved
they COMPOSE into a closed constraint-driven design loop that actually converges. `assert_converges_to_constraint` is
the first proof that a build→relax→measure→adjust loop drives a parametric topology knob into a relaxed-structure
tolerance band — AND that it never cheats the confidence gate on ANY step (the load-bearing P3 property, now enforced
across a closed loop instead of a single read), with red-tests proving an unreachable target exhausts rather than
falsely declaring met and that an already-on-target start is rejected as vacuous. The augment's key trick (reusable):
the identity mock can't move atoms, so a real TOPOLOGY knob (a bend) is what moves the measured geometry, making the
SEARCH testable GPU-free; a bend keeps landmark keys stable (it's a deformation overlay, not a topology change). No
ASK-FIRST: the driver + fixture are direction-AGNOSTIC end-to-end (curvature magnitude + Euclidean distance + AF-6's
already-cleared bend wrapper) — zero new sign/frame reasoning. This closes the Tier-5 physical-layer spine: the
text-to-DNA goal's constraint-driven-design capstone.**"

**measure_* growth — `radius_of_gyration` (whole-structure constraint kind)** · _shape:_ **service + oracle growth**
— 1 new pure measure `measure_radius_of_gyration(positions)` next to `measure_end_to_end` in
`backend/core/oxdna_health.py` + the grammar generalised to **measure-dependent landmark arity**
(`_MEASURE_LANDMARK_COUNT = {end_to_end:2, radius_of_gyration:0}`; `parse_constraint_spec` now accepts a
landmark-less whole-structure measure and REJECTS landmarks passed to one) + a `_dispatch_measure` arm wired into
`check_relaxed_constraint` + `assert_relaxed_measurement` (harness) branched to dispatch on the measure kind;
`crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — a pure-core
measure + grammar growth; moves the oracle count, not the coverage count) · _oracle shipped:_
`measure_radius_of_gyration(positions)` — the pure reusable primitive: `sqrt(mean_i |r_i − r_cm|²)` over ALL
nucleotide backbone sites (no landmarks), pinned to closed-form values (two points at ±5 nm → R_g 5.0; cube corners →
sqrt(3)·a) and raising on an empty map; it now flows through the EXISTING `check_relaxed_constraint` (confidence gate +
tolerance bracket unchanged) and `assert_relaxed_measurement` (status guard + confidence gate) — so the AF-13 P4
iterate loop + the AF-11 `constraints` block get R_g **for free** the moment they target it · _tests:_ 5 new in
`test_oxdna_relaxation.py` (analytic R_g; empty-raises; parse no-landmarks normalises + idempotent; parse rejects
landmarks-on-rg; `check_relaxed_constraint` dispatches rg with the confidence gate + tolerance bracket) + 2 new in
`test_headless_oxdna_build.py` (rg through the harness oracle on a real run; **load-bearing red-test**: a wrong R_g
target raises "not within"); full suite **2739 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this, the ONLY relaxed-structure constraint was a two-landmark end-to-end distance — nothing
could certify a structure's *overall* size/compactness, which a point-pair distance is blind to (a structure can hold
its end-to-end while its bulk swells or collapses). `measure_radius_of_gyration` adds that whole-structure measure, and
— the genuinely-new structural power — the constraint grammar now supports **measure-dependent landmark arity** (a
landmark-less measure parses; landmarks passed to one are rejected), so every future `measure_*` kind (inter-helix
spacing, segment angle) slots in by adding a name + arity + one dispatch arm rather than rewriting the parser. The
red-test proves the oracle goes red on a wrong target. No ASK-FIRST: R_g is a translation/rotation-invariant scalar
magnitude — zero sign/frame/handedness reasoning.**"

**measure_* growth — `segment_angle` (the first 3-landmark / non-length constraint kind)** · _shape:_ **service +
oracle growth** — 1 new pure measure `measure_segment_angle(positions, a, b, c)` next to `measure_end_to_end` /
`measure_radius_of_gyration` in `backend/core/oxdna_health.py` (the interior bend angle in DEGREES at the middle
landmark `b` of the chain a–b–c, `arccos((a−b)·(c−b)/(|a−b||c−b|))`, arccos-domain-clamped) + the name added to
`_CONSTRAINT_MEASURES` + `_MEASURE_LANDMARK_COUNT["segment_angle"]=3` (exercising the **3-landmark arity** for the
first time — `{0,2}`→`{0,2,3}`; the AF-13-P3 arity generalisation accepted it with zero parser changes) + a
`_dispatch_measure` arm + an `assert_relaxed_measurement` (harness) branch that reports the right **unit** (`deg`,
not `nm`, in the failure message); `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED**
(wraps no new route — a pure-core measure + grammar growth; moves the oracle count, not the coverage count) · _oracle
shipped:_ `measure_segment_angle` — the pure reusable primitive: pinned to closed-form angles (right angle → 90°,
collinear → 180°, 60° wedge → 60°; leg-order-about-the-vertex-invariant) + raising on empty map / coincident pair /
absent landmark / zero-length leg; it flows through the EXISTING `check_relaxed_constraint` (confidence gate +
tolerance bracket unchanged, now in degrees) and `assert_relaxed_measurement`. **The LOAD-BEARING augment is
`test_segment_angle_captures_bend`** — three collinear landmarks along a STRAIGHT bundle read ~175° and the SAME
landmarks on a bundle bent at the middle read strictly < (here 119°, a >55° drop): the geometric proof the measure
actually tracks curvature, not a constant · _tests:_ 6 new in `test_oxdna_relaxation.py` (analytic 90/180/60 +
leg-swap invariance; rejects empty/coincident/absent; parse 3-landmarks normalises + idempotent; parse rejects
2-landmarks-for-segment_angle [parametrized]; `check_relaxed_constraint` dispatches segment_angle with the confidence
gate + tolerance bracket) + 3 new in `test_headless_oxdna_build.py` (segment_angle through the harness oracle on a
real run, certified against the design's own angle with a 3° tol absorbing the oxDNA-vs-design backbone-site
convention; **load-bearing geometric augment** `captures_bend` straight-vs-bent; **red-test**: a wrong angle target
raises "not within"); full suite **2747 passed / 55 skipped**, no drop · **"Validation gained, not just a
passthrough:** before this every relaxed-structure constraint was a *length* (`end_to_end` nm, `radius_of_gyration`
nm) — nothing could certify a structure's *shape/curvature*, which a distance scalar is blind to (a bundle can hold
its end-to-end while kinking sharply at the middle). `measure_segment_angle` adds the first ANGULAR measure, and —
the genuinely-new structural power — `captures_bend` proves the angle actually responds to a topology bend
(straight ~175° → bent 119° on the SAME landmarks) rather than reading a constant; the red-test proves it goes red
on a wrong target. It also exercises the 3-landmark arity (the arity generalisation's first non-{0,2} consumer,
proving that path was real, not speculative), so segment angle slots into the iterate loop + the AF-11 `constraints`
block for free. No ASK-FIRST: an `arccos` is a magnitude — zero sign/frame/handedness reasoning.**"

**measure_* growth — `inter_helix_spacing` (the first axis-grouping constraint kind)** · _shape:_ **service +
oracle growth** — 1 new pure measure `measure_inter_helix_spacing(positions, a, b)` + a private `_fit_helix_axis`
helper in `backend/core/oxdna_health.py` + the name added to `_CONSTRAINT_MEASURES` + `_MEASURE_LANDMARK_COUNT
["inter_helix_spacing"]=2` (reuses the existing 2-landmark arity) + a `_dispatch_measure` arm + an
`assert_relaxed_measurement` (harness) branch (unit stays **nm** — no degrees wart); `crud.py`/`assembly.py`/`main.js`
LOC Δ = **0** · _oxDNA-coverage Δ:_ **UNCHANGED** (wraps no new route — a pure-core measure + dispatch growth; moves
the oracle count, not the coverage count) · _oracle shipped:_ `measure_inter_helix_spacing` — the first measure that
**groups by helix and fits an axis**: each landmark only NAMES a helix (via `helix_id`), ALL of that helix's backbone
sites are gathered, `_fit_helix_axis` fits a centroid + PCA principal direction, and the spacing is the centroid
separation projected *perpendicular to the common (mean) axis* (PCA sign aligned). Deliberately NOT the minimal
infinite-line distance — that collapses to ~0 for near-parallel tilted axes (the fragile regime spacing means); this
form is exact for parallel helices and robust to relaxed-bundle tilt. Pinned to analytic parallel/axially-staggered/
slightly-tilted values + raising on empty / same-helix / absent-landmark / single-site-helix; flows through the
EXISTING `check_relaxed_constraint` + `assert_relaxed_measurement` unchanged · _tests:_ 5 new in
`test_oxdna_relaxation.py` (analytic parallel 2.5 nm + symmetry; axial-stagger + tilt-robustness; rejects
empty/same-helix/absent/single-site; parse 2-landmarks normalises + idempotent; `check_relaxed_constraint` dispatches
it with the confidence gate + tolerance bracket) + 3 new in `test_headless_oxdna_build.py` (**load-bearing geometric
augment** `captures_separation`: a straight 3-in-a-row SQUARE bundle reads equal adjacent gaps ~2.25 nm and a skip-one
gap ~2×; the measure through the harness oracle on a real run; **red-test**: a wrong spacing target raises "not
within"); full suite **2755 passed / 55 skipped**, no drop · **"Validation gained, not just a passthrough:** before
this every relaxed-structure measure was either a point-to-point quantity (`end_to_end`, `segment_angle`) or a
whole-structure scalar (`radius_of_gyration`) — nothing could certify the *radial packing* of a bundle, the property
that says whether helices relaxed to their lattice spacing or splayed/collapsed. `measure_inter_helix_spacing` adds
that, and — the genuinely-new structural power — it introduces the **axis-grouping pattern** (group sites by helix →
fit an axis → relate two axes), which no prior measure needed; the `captures_separation` augment proves it tracks real
separation (adjacent vs skip-one, ~2× on a straight row) rather than a constant, and the red-test proves it goes red on
a wrong target. The design note that the infinite-line distance is fragile near-parallel (and is rejected in favour of
the perpendicular-to-mean-axis projection) is itself banked validation knowledge. No ASK-FIRST: a length magnitude with
sign-aligned axes — zero handedness/frame reasoning.**"

**AF-13 P5 — design `constraints` block wired into the AF-11 grammar (attach + report, no knob)** · _shape:_
**grammar growth + composition driver** — the pure parser `backend/core/build_spec.py` gains an optional top-level
`constraints` list on a design spec (`DesignSpec.constraints`; each constraint a `{measure, landmarks, target_nm,
tol_nm, min_confidence}` whose landmarks name a helix by **grid_pos** `{helix:[r,c], bp_index, direction}`), validated
at parse time by handing the cell-normalised constraint to the AF-13 P3 `parse_constraint_spec` (so a malformed
constraint fails BEFORE any build/relax) + 2 driver fns in `backend/api/headless_spec_build.py`
(`build_and_check_design(spec, ws, *, steps, tuned, **relax_params) → {design, verdicts}` and the lower-level
`check_design_constraints` — resolve each landmark's grid_pos → runtime id up front (fail-fast), relax ONCE +
production, then `check_relaxed_constraint` per constraint; drives the already-covered `hox.run_relaxation`/
`append_production`/`read_flexibility_map`, re-implements nothing) + 1 reusable oracle
`assert_spec_constraints_reported` in `tests/automation_harness.py`; `crud.py`/`assembly.py`/`main.js` LOC Δ = **0** ·
_oxDNA-coverage Δ:_ **UNCHANGED, 36** (wraps no new route — composition sugar over covered wrappers + a pure-core
reporter, like AF-10/AF-11/P4; `test_spec_build_adds_no_coverage` still asserts 36) · _oracle shipped:_
`assert_spec_constraints_reported(spec_result, hand_verdicts, *, measured_tol=1e-6)` — asserts the grammar's
`constraints` path reports the SAME per-constraint verdict (status + `met` + `measured_nm` within tol; `None` only
matches `None`) a hand-driven `check_relaxed_constraint` does, with a non-vacuity guard (≥1 verdict) + count-mismatch
guard. **It is load-bearing because `assert_spec_matches_calls` is BLIND to a physical-layer verdict** — the
canonical-topology fingerprint cannot see whether a constraint was attached, its landmark resolved to the right helix,
or it was reported at all; only verdict-equality proves the lowering is faithful · _tests:_ 2 grammar-normalisation +
7 grammar rejections (unknown measure, wrong landmark arity, landmarks-on-`radius_of_gyration`, non-positive tol,
landmark missing a field, typo'd field, constraints-not-a-list) in `test_build_spec.py` + 4 driver tests in
`test_headless_spec_build.py` (no-constraints → empty verdicts + no oxDNA run; `radius_of_gyration` reports == hand;
`end_to_end` grid_pos landmarks RESOLVE + report == hand; unknown grid_pos fails fast before any relaxation) + 5
oracle tests in `test_automation_harness.py` (passes on matching verdicts + **four load-bearing red-tests**: status
mismatch, measured divergence (wrong-helix), count mismatch, empty-list vacuity); full suite **2920 passed / 55
skipped**, no drop · **"Validation gained, not just a passthrough:** before this the AF-13 P3 `check_relaxed_constraint`
reporter existed but was un-wired — a design spec could not carry a relaxed-structure constraint, so nothing proved a
*declarative* constraint is lowered to the same verdict a hand call yields. `assert_spec_constraints_reported` closes
that: it proves the grammar resolves each grid_pos landmark to the correct runtime helix, runs the right measure, and
applies the confidence gate identically to a hand-driven check — the exact guarantee text-to-DNA's constraint clauses
rest on, and the property `assert_spec_matches_calls` is structurally blind to. All four `measure_*` kinds get the
grammar path for free (the parser dispatches on the measure name). The four red-tests prove the green can go red. No
ASK-FIRST: grid_pos→id resolution is a lookup, the measures are magnitudes — zero frame/sign reasoning.**"

---

## Lessons (anti-patterns banked — read before building)

_(none yet — first session. Candidates the audit already suggests:)_
- **Passthrough smell.** If your wrapper's body is one `requests`/service call and your "test" only asserts
  HTTP 200, you shipped a passthrough. The oracle must assert a *property of the result*, not that the call
  returned.
- **The route may be dead.** The audit found routes with no live frontend caller (e.g. parts of `/md/*`).
  Re-derive UI-wiring (protocol step 3) before wrapping — a dead route is a `issues_ledger.md` delete
  candidate, not an AF item.
- **Deformation is a three-layer minefield.** AF-6 touches bend/twist sign + frame conventions — `CLAUDE.md`
  says ASK FIRST on topology/geometry/directionality. Don't reason it out; confirm with the user.

### Banked from AF-2
- **An inverse-pair oracle needs a "forward really happened" guard or it passes vacuously.** If `forward`
  silently no-ops, then `forward∘inverse` trivially equals `start` and the oracle is green while proving
  nothing. `assert_inverse_pair` asserts the *mid*-state topology `!=` start before checking the round-trip —
  that guard is what makes it able to go red, and it's covered by a dedicated red-test.
- **Shipping a covered route invalidates the "this route is uncovered" meta-tests.** AF-1's
  `test_coverage_report_lists_real_backlog_routes` hard-coded `/design/nick` as uncovered; AF-2 covered it,
  so the test had to repoint to a *still*-uncovered backlog route (`/design/circle-segment`). Each AF session
  that flips a route must re-point any coverage meta-test that named it. (Coverage paths carry the `/api`
  prefix — match with `.endswith()`.)

### Banked from AF-3
- **`canonical_topology` ignores loop/skips — round-trip stability can't prove they persist.** Loop/skip
  marks live on `Helix.loop_skips`, not in the strand graph, so the fingerprint (and therefore
  `assert_roundtrip_stable` / `assert_inverse_pair`) is blind to them: a build with a loop and a build without
  it have identical canonical topology. To pin a length-changing op you need a *geometric* oracle that counts
  the kernel's emitted nucleotides (`geometric_nucleotide_count`). If a future op also lives outside the strand
  graph (cluster transforms, deformation ops, plate layout), the same blind-spot applies — pick the oracle form
  by what the op actually changes, not by reflex reaching for round-trip.
- **A global conservation check can cancel to zero — scope it.** apply-deformations places balanced
  loops+skips (twist) or near-balanced patterns (gentle bend), so the *global* net delta is ~0 and a
  whole-design count check passes vacuously. The real assertion is **per-helix**: each helix's geometric count
  must move by twice its own net mark delta. `assert_geometric_length_delta(..., helix_id=h.id)` is the strong
  form; loop over helices for bulk ops.
- **Geometry emits both strands per bp regardless of strand coverage.** `nucleotide_positions(helix)` emits
  forward+reverse for every effective bp of the helix span, joining strand metadata only as a lookup (default
  `_missing` when no strand covers). So a loop/skip's effect on the geometric count is a deterministic `2×δ`,
  independent of how the strands are routed — which is why the count oracle is robust on bare bundles and fully
  routed designs alike.

### Banked from AF-1
- **Drive the real route, don't reconstruct it.** `roundtrip_nadoc` round-trips through the actual
  `POST /design/import` handler (`Design.from_json` + migrate/autodetect/backfill), not a bare
  `Design.from_json`. A wrapper/oracle that re-implements the route's processing tests a *different* thing
  than what the user gets — always run the same service the route runs.
- **Match coverage by function identity, not strings.** `headless_coverage_report` maps routes→wrappers by
  the endpoint *function object* a wrapper imports. This is unstaleable (rename a route URL and nothing
  rots) AND enforces the anti-passthrough rule for free: a wrapper only counts as covered if it imports the
  real handler, so a re-implementation never shows as covered.
- **Make the oracle's seam injectable so you can prove it fails.** `assert_roundtrip_stable` takes a
  `roundtrip=` kwarg purely so the meta-test can feed it a *corrupting* round-trip and assert it raises. An
  oracle you've never seen go red is unproven — bake the negative test in from the start.

### Banked from AF-4
- **A pre-existing pure oracle does NOT cover the wrapper — measure the placed geometry, not the footprint.**
  `circle_footprint`/`circularity_spread` were already green in `test_circle_primitive.py`, so it was tempting
  to "reuse the oracle" by asserting on the footprint the wrapper computes. But that re-proves the pure math and
  proves *nothing* about the route/builder — a builder that mis-centred or dropped a helix would still pass.
  The validation augment must read the **result's geometry** (here: the placed helices' axis spans), closing the
  radius→footprint→route→builder→geometry loop. "Reuse the circularity *functions*" ≠ "reuse the circularity
  *test*"; the new oracle calls the former on data extracted from the built `Design`.
- **Wrapper-takes-the-parameter, not the pre-computed payload.** The route's `CircleSegmentRequest` wants
  `cells` + `cell_lengths` (the UI derives them in JS). A faithful headless wrapper takes the *radius* and runs
  the same `circle_footprint` the JS mirror runs, so the scripted disc is byte-identical to a clicked one — and
  the wrapper's surface is the user-meaningful knob (radius), not the route's internal payload. Mirror this for
  any op whose REST body is "pre-chewed" by a frontend: the wrapper re-chews from the high-level parameter.

### Banked from AF-5
- **`canonical_topology` / `assert_roundtrip_stable` cannot handle a `grid_pos=None` helix.** The fingerprint
  sorts helices on `grid_pos`, so any design containing a helix with `grid_pos=None` raises `TypeError: '<'
  not supported between NoneType and tuple`. `make_bundle_deformed_continuation` is the *only* bundle builder
  that omits `grid_pos` on its new helix (all others set `grid_pos=(row,col)`), so the round-trip oracle is
  unusable on a deformed-continuation build — AF-5 pinned it with the geometric `assert_on_deformed_frame`
  instead. Don't reflexively reach for `assert_roundtrip_stable`; if the op can emit a grid_pos-less helix,
  use a geometry oracle. (Whether the omission is a bug or intentional-to-preserve-baked-coords is a
  three-layer question logged as `ISSUE-11` — do NOT just add grid_pos without asking the user.)
- **The "differs from straight" guard is the deformed-placement analog of the inverse-pair mutate-guard.**
  Re-deriving the deformed frame and asserting the helices land on it is *near-tautological* (the oracle and
  the route call the same `deformed_frame_at_bp`), so on its own it would pass even if the deformation did
  nothing. The load-bearing assertion is that the deformed placement is displaced from the *straight* frame
  placement (recomputed on a deformations-stripped copy) — that is what makes the oracle go red on an
  un-deformed design and what proves the deformation actually drove the placement.
- **Sample-then-post with `source_bp` to mirror the replayable UI path.** The route accepts a baked frame
  (grid_origin/axis_dir/…) OR re-derives it server-side when `source_bp` is present. The wrapper fetches the
  frame via `get_deformed_frame` (to fill the required request fields) *and* passes `source_bp` — so a scripted
  continuation is replayable (survives delete/edit of the upstream bend) exactly like a clicked one, not frozen
  to a baked pose. Mirror this for any op whose route has a "trust the payload OR recompute live" fork.

### Banked from AF-6
- **A single endpoint-to-endpoint frame-rotation angle FOLDS past 180°/360° — sum per-step magnitudes to
  unwrap.** The naive oracle (`arccos((tr(R_b·R_aᵀ)−1)/2)` between the two plane frames) is only valid for a
  total rotation < 180°: a 200° bend reads 160°, a 400.8° twist reads 40.8°, a 540° twist reads 180°. Walking
  the frame in 1-bp steps and SUMMING each step's magnitude unwraps it (each step is ≪180°). This stays exact
  because bend/twist (and their superhelix composition) are constant-axis screw motions, so the SO(3) path
  length equals the geodesic — no over-counting. Confirmed empirically (bend 80/200, twist 90/540/400.8 all
  matched to the requested θ).
- **The deformed frame `R` already composes bend AND twist, so one magnitude oracle covers both.** `_frame_at_bp`
  integrates the combined screw motion (overlapping bend+twist → superhelix), and `deformed_frame_at_bp` exposes
  it as `[frame_right|frame_up|axis_dir]`. A bend tilts the axis; a twist spins right/up about the axis; both
  show up as the rotation-angle magnitude of the relative frame rotation. No need for a tangent-angle oracle for
  bend + a separate spin oracle for twist — the frame-rotation magnitude is the unified, direction-agnostic pin.
- **Staying direction-agnostic let AF-6 ship without the ASK-FIRST round-trip.** `CLAUDE.md` reserves bend/twist
  SIGN + frame conventions for the user. By pinning only the *magnitude* (κ·Δbp / total twist) — never which way
  it bends — the oracle is provably correct without needing the user to adjudicate sign/handedness. The backlog's
  floated signed-curvature/closure oracle (`solve_closing_curvature`) would have needed that conversation; it was
  deliberately not built. If a future item needs a *signed* curvature pin, that's the moment to ask.

### Banked from AF-7
- **A second headless module needs the coverage report taught about it, or its wrappers don't count.**
  `headless_coverage_report` matched routes against `vars(headless_build)` only. The new
  `headless_assembly_build.py` wrappers import real route handlers (so they ARE covered in spirit), but until the
  report scanned that module too, the `/assembly` routes stayed listed as uncovered — the wrapper existed yet the
  metric didn't move. When you add a `headless_*_build.py`, extend the report's module list in the same commit
  (it now iterates `(headless_build, headless_assembly_build)`), or the coverage Δ silently lies.
- **Round-trip via `import`, not `save`, to keep it in-memory and inline-preserving.** The backlog said "build →
  save → load", but `POST /assembly/save` auto-converts inline part designs to on-disk `.nadoc` files (changing the
  sources AND writing to the workspace). The faithful analog of `roundtrip_nadoc` is `to_json` → `POST
  /assembly/import` (`roundtrip_nass`): it exercises the real import handler, stays in memory, and keeps inline
  sources inline — so a self-contained scripted assembly round-trips with zero disk side effects. Use the file
  save/load path only when the test is specifically about the inline→file conversion.
- **Keep test assemblies ≤6 'full'-rep instances.** `import_assembly` runs `_maybe_auto_downgrade_for_memory`,
  which silently rewrites >6 `representation='full'` instances to `'cylinders'`. `canonical_assembly` reads the
  rep field, so an oversized assembly would fail the round-trip fingerprint check for a *non*-bug reason. The real
  threshold is a UI/memory guard, not a topology fact — small fixtures sidestep it.
- **`canonical_assembly` keys inline sources by the design's `canonical_topology`, NOT `design.id`.** The id is a
  uuid that *is* preserved across round-trip, so keying on it would pass — but it wouldn't be order/id-independent
  the way the design fingerprint is, and it would miss a builder that swapped one part's design for a
  topologically-different one carrying the same id. Reusing `canonical_topology` makes the assembly fingerprint
  inherit the design fingerprint's robustness for free (and composes cleanly when AF-8 adds joints).

### Banked from AF-8
- **The mate snaps at create time — you don't need `resolve()` to get coincidence, but pin both.** `create_mate`
  → `_compose_add_joint` derives the snap from the LIVE connector world positions (`ca_world − cb_world`) and
  applies it to the child instance immediately, so connectors are coincident the moment `define_mate` returns.
  `resolve_assembly` re-applies the same constraint. The handoff framed the oracle as "post-`resolve`", but the
  faithful pin is "coincident after the mate AND still coincident after an explicit resolve" — test both (a resolve
  that *broke* coincidence would be a real bug the create-time-only check would miss).
- **No FK transform needed for a connector mate — let the connector-derived snap align the parts.** The UI's
  `create_mate` also accepts `moved_instance_id`+`transform` (the live drag pose), but `_compose_add_joint`
  recomputes the snap from the connectors regardless ("safety net — frontend pre-aligns, backend recomputes to
  guarantee coincidence"). So a headless `define_mate` can omit the FK move entirely and still land coincident —
  simpler and it exercises the same guarantee the route promises. The connector LOCAL `position`/`normal` (set via
  `add_connector`) are what drive the alignment.
- **A coincidence oracle passes vacuously on stacked parts — guard on part-origin separation.** If both mated
  parts sit at the same world origin with connectors at their part origins, "connectors coincident" is trivially
  true with no snap. The non-triviality guard asserts the two mated instances' *origins* are separated (the snap
  moved the child to a distinct place yet the connectors still meet) — place mate connectors at a non-zero LOCAL
  offset from their part origins so this holds. Same shape as AF-5's "differs from straight" and AF-2's "forward
  really mutated" guards: an oracle you can't make go red is unproven.
- **Enrich the joint fingerprint with the mated parts' SOURCE keys, not their instance ids.** `canonical_assembly`
  keyed joints by `(type, conn_a_label, conn_b_label, value)` — blind to *which parts* a mate joins, so a mate
  rewired to a different instance with the same labels would pass the round-trip fingerprint. Keying additionally on
  the two instances' source fingerprints (`canonical_topology` for inline, path+sha for file — the same id-
  independent keys the instance fingerprint uses) makes the joint key inherit that robustness. Use `("world",)` for
  a World mate's absent parent so the sort doesn't trip over `None` vs. tuple.

### Banked from AF-9
- **A resolve-invariant oracle must measure the moved GEOMETRY, not the stored joint value.** The gear route
  computes `θ_b = anchor_b + sign·(θ_a − anchor_a)·ratio` and writes it to `joint_b.current_value`. An oracle that
  reads `current_value` back and checks the same formula is testing the route's arithmetic against itself —
  tautological, proves nothing about whether the *part* actually rotated. `assert_gear_ratio` instead measures each
  coupled instance's **transform rotation magnitude** (the `_apply_revolute_value_to_gear_endpoint` + FK actually
  moved it) and asserts the ratio on that — so a gear that set the value but failed to drive the body (an FK bug)
  fails. Same shape as AF-4's "measure the placed geometry, not the footprint."
- **Driving via PATCH auto-propagates the relation — no separate `resolve()` needed (path 1).** `patch_joint`
  calls `_propagate_gear_relations_from(assembly, joint_id)` after applying the revolute, so a single
  `drive_joint(joint_a, θ)` moves joint_a's body AND every gear/belt-coupled body in one call. The handoff framed
  the oracle as "drive then resolve"; the faithful (and simpler) path is just `drive_joint` — the same auto-apply
  insight as AF-8's "the mate snaps at create time." `resolve()` re-applies all constraints and is the right tool
  only when you didn't get there through a driving PATCH.
- **`canonical_assembly` ignored `gear_relations` — extend the fingerprint when a new relation type ships.** The
  fingerprint keyed instances + joints but not gears, so a round-trip that dropped a gear would have passed
  `assert_assembly_roundtrip_stable` silently. Keying each gear by its two coupled joints' *id-independent
  fingerprints* (not joint ids) + ratio/invert/anchors makes the round-trip oracle catch it — the direct analog of
  AF-8 enriching the joint key with part-source fingerprints and AF-7 teaching the coverage report about a second
  module. **When you add a new top-level assembly relation list (belts next), extend `canonical_assembly` in the
  same commit or the round-trip oracle silently under-pins it.** (The return is now a 3-tuple; callers index
  `[0]`/`[1]` and compare equality, so adding `[2]` was backward-safe.)
- **Magnitude-only kept AF-9 clear of ASK-FIRST, same as AF-6.** The gear's `ratio` magnitude is the core promise
  and is direction-agnostic; `invert` only flips the driven body's rotation *sign*. Pinning the magnitude ratio
  (an `arccos`, always ≥ 0) needs no handedness/frame-sign reasoning, so no user adjudication was required. The
  invert *direction* is verified at the cheap `current_value`-sign level inside a test (pure scalar arithmetic, not
  a geometric convention), never in the oracle.

### Banked from AF-9 belts
- **Generalise the existing resolve-invariant oracle, don't fork a near-clone.** The belt's coupling promise is
  the SAME shape as the gear's (drive one body, the other rotates by the ratio), and `_belt_to_relation` already
  expresses a `BeltPath` AS a `GearRelation`. The temptation is a second `assert_belt_ratio` that copy-pastes 90%
  of `assert_gear_ratio`. The clean move was a one-line generalisation: make the oracle look the relation up in
  `_coupling_relations(assembly, joint_by_id)` (gears + belt-derived) instead of `assembly.gear_relations`, and
  hand it the belt's synthetic id `f"__belt__{belt.id}"`. Backward-safe because gears are first in that list — no
  existing gear test moved. One oracle now pins both coupling types; a future relation that also lowers to a
  `GearRelation` (a chain/sprocket) reuses it for free.
- **The belt's `radius` is the kinematic knob even though the model calls it "advisory geometry".** `BeltPulley.radius`
  is documented as frontend-computed advisory metadata (the *rendered* belt geometry — tangent line, centres — is
  computed in JS and not re-derived on the backend). But `_belt_to_relation` reads `radius_a`/`radius_b` to set the
  coupling ratio, so the radius IS load-bearing for kinematics. The validation gain is pinning that ratio
  derivation, NOT the rendered belt-path geometry. The **tangent length** the handoff floated as a second oracle
  is a *frontend* computation with no backend invariant to pin headlessly — pinning it would need porting that JS
  math (a future JS↔Python-parity item or an MV row), not an AF backend oracle. Don't try to oracle a quantity the
  backend doesn't actually compute.
- **A new top-level relation list → extend `canonical_assembly` in the same commit (third time this rule fired).**
  Same as AF-7 (teach the coverage report about a 2nd module), AF-8 (enrich joint key with part sources), AF-9 gears
  (fingerprint `gear_relations`): the round-trip oracle silently under-pins a list it doesn't fingerprint. Added
  `belt_paths` keyed by the two pulley joints' id-independent fingerprints + radii/sides/anchors. The return grew
  from a 3-tuple to a 4-tuple; every caller compares the whole tuple for equality, so the widening was backward-safe
  (verify with `rg 'canonical_assembly'` that nothing indexes a fixed position before widening).

### Banked from AF-9 polymerize
- **Re-derive the lattice from the SEED, not the route's chain helper, or the oracle is a tautology.** The
  obvious move is to import `compute_chain_transforms` and compare the placed copies to its output — but that
  re-runs the exact code under test, so a bug in the helper passes. `assert_polymer_chain` re-derives
  `delta = T_B @ inv(T_A)` and the `delta`-power progression from the seed pair's two world transforms ALONE
  (numpy, ~6 lines), independent of the implementation. Same shape as AF-9 gears' "measure the moved geometry,
  not `current_value`" and AF-4's "measure the placed geometry, not the footprint": the oracle must stand
  outside the implementation it pins.
- **Polymerize needs source-identical seed parts — share ONE `Design` object across both inline instances.**
  `/assembly/polymerize` 422s unless `_sources_match(inst_a.source, inst_b.source)` — for inline parts that's a
  structural-dump equality that includes nested helix/strand ids. Two separate `make_6hb_design()` calls can
  carry different nested ids → the dumps differ → 422. Passing the SAME `Design` object to both
  `add_inline_instance` calls makes both embed the identical dict, so the dumps match. (AF-8's mate fixtures
  used two *separate* designs because mates don't require source identity; polymerize does.)
- **No `canonical_assembly` extension this time — polymerize adds no new top-level relation list.** AF-7/8/9
  gears/belts each had to extend the fingerprint (coverage-module list / joint-source key / gear list / belt
  list). Polymerize only appends to the EXISTING `instances` + `joints` lists, which `canonical_assembly`
  already fingerprints, so a polymerized chain round-trips through `assert_assembly_roundtrip_stable` and a
  dropped copy/joint is caught with zero harness change. The "extend the fingerprint in the same commit" rule
  fires only when you add a new *top-level list* on `Assembly`, not when you grow an existing one.

### Banked from AF-9 overhang-bindings
- **For a metadata-only relation, pin referential INTEGRITY, not geometry — and know what the structure
  fingerprint is blind to.** An `AssemblyOverhangBinding` applies no geometry (no snap, no transform), so there's
  no placed position to measure the way the mate/gear/polymerize oracles do. The right property is that the
  binding's refs *resolve* to live overhang sub-domains. The non-passthrough punch is that `canonical_assembly`
  (the round-trip structure oracle) is BLIND here: it keys inline instances by `canonical_topology`, which
  fingerprints only helices + strands — NOT overhangs or sub-domains. So a round-trip that regenerated a
  sub-domain id while the binding kept its stale ref would pass `assert_assembly_roundtrip_stable` silently.
  Resolving the endpoints against the actual part designs is the only thing that catches that — genuinely
  orthogonal validation power, not a re-check of the route's create-time 404.
- **Extend `canonical_assembly` for the new top-level list AND ship a semantic oracle — they cover different
  failures.** The "new top-level relation list → extend the fingerprint in the same commit" rule fired a **5th
  time** (after AF-7 coverage-module, AF-8 joint-source key, AF-9 gears, AF-9 belts): added `overhang_bindings`
  as the 5-tuple's `[4]`. But fingerprinting alone is insufficient for bindings — it catches a *dropped/rewired*
  binding (structure change) but not a *broken ref* (the sub-domain-id-regenerated case above, which doesn't
  change the structure fingerprint). The pair (`canonical_assembly` extension + `assert_binding_resolves`) is
  what fully pins it; for a geometry-bearing relation (mate/gear) the fingerprint + the geometric oracle play
  the same complementary roles.
- **`model_copy(update=…)` bypasses the model validator — use it to construct the "impossible" red-test state.**
  `AssemblyOverhangBinding` has a field validator that rejects a self-binding at construction. The degenerate
  self-pair red-test needs exactly that forbidden state to feed the oracle. Pydantic v2 `model_copy` does NOT
  revalidate, so `binding.model_copy(update={"instance_b_id": …, "sub_domain_b_id": …})` builds the degenerate
  object without tripping the validator — the clean way to manufacture a corrupt state a constructor would
  refuse. (Same trick the gear/belt/polymerize red-tests use to shove a body off its lattice.)

### Banked from AF-10
- **A construction-sugar item moves the ORACLE count, not the coverage count — and that's fine, but say so.**
  Coverage is matched by route-handler function identity (AF-1). `place_grid`/`place_ring` wrap no new route —
  they compose the already-covered `add_instance` — so the coverage Δ is **0** by construction. That is NOT a
  passthrough smell: the loop's pass criterion was always the *oracle* (a property of the result), never a
  coverage flip. Most AF items happen to flip a route too, so the two move together; AF-10 is the case where they
  don't, which makes explicit that "validation gained" — not "coverage moved" — is the real bar. Log it plainly
  so a future reader doesn't mistake the flat coverage for a shovel.
- **A lattice oracle must check PROPERTIES of the placed result, not re-run the placement formula.** The trap
  (same family as AF-4's "measure the placed geometry, not the footprint" and AF-9's "measure the moved geometry,
  not `current_value`"): import `grid_translations`, recompute the expected origins, and `np.allclose` them to the
  placed ones — that re-runs the code under test, so a bug in the formula passes. Instead the oracle re-derives the
  lattice from the *user-facing params* as invariants: grid → "the origins occupy exactly `cols` evenly-spaced
  columns × `rows` rows with every cell filled"; ring → "every origin at `radius`, consecutive angular steps ==
  `360°/n`". These hold for the canonical lattice regardless of construction order and catch a transposed-axes /
  wrong-pitch / dropped-slot bug the formula-replay would mirror.
- **The ring's `radius>0` guard is genuinely load-bearing (unlike the grid's pitch guard).** For a grid, stacking
  all parts at the origin already fails the count-of-distinct-columns check, so the `pitch>min_pitch` guard is
  belt-and-suspenders. For a ring, `radius=0` puts every origin AT the centre where `dist==radius==0` is trivially
  true AND all angles collapse — the on-ring + step checks both pass vacuously. So the `radius>min_radius` guard is
  the only thing that can make the ring oracle go red on a degenerate request; its red-test (build 6 stacked
  instances, ask the oracle to pass with radius=0) is the one that proves the guard fires.
- **Orientation is an ASK-FIRST convention — ship translation-only, defer facing.** A common ring want is parts
  *rotated* to face the centre / tangent, but "which local axis points at the centre" is exactly the
  geometry/directionality question `CLAUDE.md` reserves for the user. AF-10 places origins only (identity rotation)
  — fully pinnable by a direction-agnostic origin oracle — and defers radial facing to a future item that opens
  with the orientation-convention conversation. Same discipline as AF-6 staying magnitude-only to avoid the
  bend/twist sign ASK-FIRST.

### Banked from AF-11
- **The faithfulness oracle (`spec ≡ hand-call`) IS the anti-passthrough proof for an interpreter.** A spec
  interpreter's whole risk is that it quietly re-implements an op (different default, dropped/mis-ordered step,
  mistranslated param) instead of driving the real wrapper. You cannot catch that with round-trip stability alone
  (a re-implemented build can still round-trip). The catch is `assert_spec_matches_calls`: build the spec AND the
  equivalent hand-call sequence, assert equal `canonical_topology`/`canonical_assembly`. This is the AF-4 lesson
  ("measure the placed geometry, not the footprint") applied to a whole pipeline — the oracle stands outside the
  interpreter and compares it to the thing it claims to be sugar over. Bonus: because the hand-call is
  deterministic, this same oracle IS the "spec → fixed canonical fingerprint" golden pin (no separate stored hash).
- **Split the interpreter pure-parser ⟂ driver so the grammar is testable HTTP-free and the driver re-implements
  nothing.** `backend/core/build_spec.py` (parse → ordered `BuildOp` list, validate, NO execution) imports nothing
  from `backend.api`; the driver `backend/api/headless_spec_build.py` only dispatches `BuildOp`s to real wrappers.
  This let 25 grammar/rejection pins run as pure unit tests (no build, no scratch session) AND kept the driver a
  thin dispatch table — the parser does all the validating, the driver does all the driving, neither does both.
- **A declarative spec must reference runtime ids by STABLE keys, not generated ids.** A nick can't name a helix by
  its uuid (the spec is written before the build runs). The fix: reference helices by lattice `grid_pos`
  `[row,col]` and resolve to the runtime id in the driver; reference assembly instances by a spec-assigned `ref`
  key the driver maps to the created instance id. The parser validates `ref` integrity (every `mate` endpoint was
  defined by a prior `add_part`, with the named connector label) so a dangling reference fails at parse time.
- **Build nested part designs BEFORE entering the assembly scratch session — don't nest scratch sessions.** An
  assembly spec's parts are nested design specs; `build_assembly` builds each via `build_design` (its own design
  scratch) FIRST, collecting standalone `Design` copies, THEN opens the assembly scratch and places them. Building
  a part inside the assembly scratch would nest two `doc_context` bindings — works (different state modules) but is
  needless; build-then-place is cleaner and each part is a detached deep copy by the time it's embedded inline.
- **Composition-sugar items keep coverage flat — same as AF-10, say so explicitly.** The interpreter wraps no
  route (it composes the already-covered `hb.*`/`hab.*`), so `headless_coverage_report()["covered"]` stays 32. That
  is NOT a passthrough smell: the pass criterion was always the oracle. Pinned with an explicit
  `test_spec_build_adds_no_coverage` so a future reader doesn't mistake the flat coverage for a shovel.

### Banked from AF-11 Phase 2 (grammar growth — bend/twist)
- **`assert_spec_matches_calls` is VACUOUS for any op `canonical_topology` can't see — pick the oracle by what the
  op changes, not by reflex.** A `bend`/`twist` op adds a geometric `DeformationOp` overlay that lives OUTSIDE the
  strand graph (exactly like a loop/skip — the AF-3 blind-spot, now confirmed for deformations). So the spec-built
  and hand-built designs have *identical* canonical topology whether the bend is applied, dropped, or mistranslated
  — `assert_spec_matches_calls` passes regardless and proves only the bundle plumbing. The load-bearing pin for a
  deformation cluster is the geometric `assert_deformation_angle` on the spec-built design (it realises κ×Δbp / θ).
  General rule for Phase-2 grammar growth: before reaching for the AF-11 golden pin, ask "does the canonical
  fingerprint see this op's effect?" If not (deformations, loop/skips, cluster transforms, plate layout), the
  faithfulness oracle is necessary-but-insufficient — add the op's own geometric/count oracle as the real augment.
- **Grammar growth that drives an already-validated wrapper is NOT an ASK-FIRST geometry decision.** Bend/twist is
  a three-layer minefield, but the sign/frame conventions were settled (ASK-FIRST) back in AF-6, and both the
  wrappers (`hb.add_bend`/`add_twist`) and the oracle (`assert_deformation_angle`) are direction-agnostic. Adding a
  spec op that plumbs `plane_a_bp`/`plane_b_bp`/`curvature`/`total_degrees` straight into that wrapper introduces
  ZERO new geometric reasoning — it's parameter routing. The discipline holds: drive the real wrapper, never
  re-derive a convention. (Mirror the parser's XOR validation of `total_degrees`/`degrees_per_nm` so a malformed
  twist fails at parse time, before the wrapper's own ValueError.)

### Banked from AF-11 Phase 2 (grammar growth — loop_skip)
- **A spec op can depend on a not-yet-grammared op — check the wrapper's runtime preconditions before scoping the
  cluster.** `loop_skip` and `apply_loop_skips` were listed as one cluster, but `apply_loop_skips_from_deformations`
  raises 400 unless the design has **crossovers placed** (cross-helix domain transitions), and NO current grammar op
  produces them (`bundle`/`extrude`/`ligate_adjacent` only ligate collinear fragments along one helix). So the
  sibling op was undriveable — and therefore unvalidatable — this session; it was deferred to ride with the
  `auto_scaffold`/`auto_crossover` cluster that generates its precondition. Lesson: when a handoff groups ops,
  re-derive each op's runtime guard (read the route handler) before committing to ship both — split the cluster at
  the dependency boundary rather than shipping an op you can't exercise.
- **Mirror the route's input domain in the parser, not just the type.** The loop/skip route constrains `delta` to
  `{-1, 0, +1}` (an HTTPException otherwise). The parser gates on that exact set, so a `delta: 2` spec fails at
  PARSE time with a precise message — before any build — rather than surfacing as a 400 deep in the driver. Pushing
  a known finite domain up into the pure grammar is free, reusable validation power (the `circle_segment` radius and
  the assembly layout counts are the same shape).

### Banked from AF-11 Phase 2 (grammar growth — circle_segment)
- **`assert_spec_matches_calls` is load-bearing again the moment the op touches the strand graph.** The bend/twist
  and loop_skip lessons established the faithful-façade oracle is VACUOUS for an overlay outside the strand graph.
  `circle_segment` is the inverse case: it ADDS real helices + strands, so `canonical_topology` sees it and the
  oracle becomes a genuine pin (a silently-dropped disc fails it). The rule isn't "Phase-2 ops need a geometric
  oracle" — it's "the oracle's power tracks whether `canonical_topology`/`canonical_assembly` can see the op's
  effect." Strand-graph ops (bundle/extrude/nick/ligate/circle_segment) → `assert_spec_matches_calls` is real;
  overlay ops (loop_skip/bend/twist) → it's vacuous and you need the geometric oracle. Pair both when in doubt.
- **A primordial op needs the `_PRIMORDIAL_DESIGN_OPS` set, not a special case.** `circle_segment` builds its own
  helices (like `bundle`), so it must be allowed as the FIRST op. Generalising the old `ops[0].op != "bundle"`
  check to a membership test (`not in _PRIMORDIAL_DESIGN_OPS`) keeps the "first op must be 'bundle'" substring in
  the message (so the existing extrude/nick/loop_skip/bend "can't-be-first" rejection tests still match) while
  admitting the new op. Future scratch-creating ops (auto-built rings, imported parts) drop into the same set.
- **A geometry-assumption baked into a wrapper is grammar-level validation when the spec carries the lattice.** The
  circle chord profile assumes the SQUARE column pitch — the AF-4 wrapper just documents "build in a SQUARE session"
  and nothing rejects a honeycomb build (it silently produces a non-circular profile). Because the *spec* names the
  lattice, the pure parser can reject `circle_segment` + non-square at parse time — free validation power no
  individual wrapper enforces. When an op's correctness depends on a session-level fact the spec also declares,
  cross-check them in the parser.

### Banked from AF-11 Phase 2 (grammar growth — gear)
- **A spec op that couples the OUTPUTS of two prior ops needs its own ref namespace — don't overload the instance
  refs.** A gear references two *joints*, which are created by `mate` ops, not by `add_part`. The instance `ref`
  namespace (`defined`) names parts, not joints, so a gear can't reuse it. The clean move: give `mate` an optional
  `ref` (a joint key), track it in a parallel `defined_joints: dict[ref→joint_type]` in the parser, and a parallel
  `joint_refs: dict[ref→runtime joint id]` in the driver (captured as `assembly_state.get_or_404().joints[-1].id`
  right after `define_mate` returns — the mate appends exactly one joint). This is the first grammar construct where
  one op references the runtime output of two prior ops; `belt` (two joints) and `polymerize` (one joint) reuse it
  verbatim. General rule: when a new op references something a prior op *created at runtime*, add a ref namespace for
  that thing, mirroring the existing instance-ref pattern — don't try to address it positionally.
- **For a fingerprinted top-level assembly relation, `assert_spec_matches_calls` is load-bearing AGAIN — but still
  insufficient alone.** The "pick the oracle by what canonical sees" rule (banked from bend/twist, then inverted for
  circle_segment) holds: a gear IS a `GearRelation` that `canonical_assembly` has fingerprinted since AF-9, so the
  faithful-façade oracle is a real pin (catches a dropped/rewired gear), unlike the deformation/loop overlays where
  it's vacuous. BUT — new wrinkle for *relations* specifically — the structure fingerprint catches a *structurally*
  dropped gear, not a gear that's present but fails to *propagate* (an FK/coupling bug). So pair it with the
  kinematic `assert_gear_ratio` (drive one side, measure the other body's real rotation). Same complementary split
  as AF-9 overhang-bindings (fingerprint catches dropped binding; `assert_binding_resolves` catches a broken ref).
  The refined rule: fingerprinted relation → `assert_spec_matches_calls` (structure) + the relation's own
  semantic/kinematic oracle (behaviour); the two cover different failures.
- **Push the route's relation precondition up into the parser via the ref's tracked metadata.** The gear route 400s
  unless both joints are revolute. Because the parser already tracks each mate ref's `joint_type` (for the new joint
  namespace), checking "gear joints are revolute" at parse time is nearly free — and it rejects gear-over-rigid
  before any build, with a precise message instead of a deep 400. Same shape as the loop_skip `delta∈{-1,0,+1}` and
  circle_segment square-lattice gates: when the spec already carries the fact a downstream guard needs, cross-check
  it in the pure grammar.

### Banked from the capstone (the 4-bar parallelogram)
- **An assembled linkage's per-hinge ROM must exclude the *pinned* (adjacent) bars.** In a closed loop the bars
  touch at their shared corners, so a padded all-obstacle `cluster_range_of_motion` reads **0** for every hinge —
  the bars are in contact at rest (`_sweep_clearance` returns 0 the instant the rest OBBs intersect). That's not a
  bug; it's correct collision geometry. The *kinematic* meaning of "is this hinge movable" is swing-vs-the-bars-it-
  is-NOT-connected-to: pass `obstacles=[the non-adjacent bar(s)]`. The adjacent bars co-move through the joints in a
  real mechanism, so treating them as static obstacles is wrong.
- **For a multi-body mechanism the rigorous DOF claim is combinatorial (Grübler), not a swept-ROM number.** ROM is a
  per-joint geometric clearance; "this is a 1-DOF mechanism" is `grubler_mobility(n_links, revolute=…)`. Pair them:
  Grübler gives the DOF, the geometry (closure + opposite-sides-parallel-and-equal) makes the DOF claim non-vacuous
  (4 collinear bars also score Grübler 1 but aren't a parallelogram — the area>min guard catches that).
- **Compose, don't re-prove.** The capstone is composition-only (coverage flat): it drives the already-covered
  AF-14/AF-15 wrappers and ships ONE new assembled-mechanism oracle. Don't re-pin the individual steps (their own
  oracles already do); the new validation power is in the *composition*.

## Difficulties ledger (genuinely-stuck items + why)

_(none yet.)_

---

## Ledger audit log

**2026-06-21 — validity + goal-alignment sweep (no code touched, ledger-only).** Re-checked every backlog item
against its REST route / harness fn and against the two stated goals (automated validation testing;
eventual text-to-design). **Verified live (route/fn exists):** `routes_primitives.py` (GET-only — confirms
AF-12's "no placement route" premise is still true), `periodic_polymer.py` (AF-9 straggler), `routes_cluster_joints.add_joint`
+ `routes_clusters.add_cluster/update_cluster` (AF-14/AF-15), `cluster_obb.recommend_hinge_joints`,
`headless_oxdna_build.{run_relaxation_tuned,iterate_to_constraint}`, `headless_spec_build.build_and_check_design`
(has constraints attach+report; **no knob clause** → AF-13 P5 knob genuinely open). **Conclusions:** (1) nothing in
the backlog is dead or off-goal — every open item maps to a live route/fn and to a goal; (2) stale parent
checkboxes corrected in the backlog (AF-14/AF-15/AF-PHOTO → `[x]`; AF-9 → `[x]` with the `polymerize_periodic`
straggler still open); (3) ~5 superseded `▶ NEXT`/capstone handoff pointers (directing the next session to
already-shipped AF-13 P4 / AF-16 / 4-bar capstone / AF-14 P2) pruned — durable `▶ HARNESS NOW AVAILABLE` blocks
kept. **Open, validated work, priority order:** AF-13 P5 knob clause (constraint-driven text-to-design bridge) >
AF-12 primitives-in-build-spec > `polymerize_periodic` > assembly-level `constraints` + `bind_overhangs` (both
correctly deferred — blocked on an assembly headless-oxDNA path / overhang-binding firming). See the backlog's
`## Next-session handoff` audit banner for the full finding.
