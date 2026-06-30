# design-automation log — oracle catalog, lessons, difficulties

Sibling of `backend_router_extraction_log.md` / `issues_fix_log.md`. The four-file layout (split 2026-06-25
to keep each readable in one pass — see the ledger-audit note):
- **`design_automation_backlog.md`** — protocol + ranked backlog + the ≤8-line living handoff.
- **`design_automation_log.md`** (this file) — the per-loop durable state: the **oracle catalog** (validation
  building blocks to mirror), the **lessons** (anti-patterns banked), and the **difficulties ledger**.
- **`design_automation_harness.md`** — do-not-rebuild reference: shipped wrapper signatures + banked gotchas.
  Consult per-item, NOT per loop.
- **`design_automation_metrics.md`** — the per-item metrics rows + data fits. Append new rows there; read on demand.

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
| `assert_periodic_chain_tiles` (`polymerize_periodic` straggler) | a SINGLE-part periodic polymer's AUTO-DERIVED repeat unit tiles the chain seamlessly: over every synthesized rigid `seam0:*` junction, (1) ≥1 junction (a chain was grown), (2) copy-k `seam0:3p` world ≈ copy-(k+1) `seam0:5p` world (resolved with the resolver's own `_get_connector_world` on the instance-overridden design), (3) a SINGLE repeat unit — every junction's `T_high@inv(T_low)` shares one translation length (≤`step_tol_nm`) + rotation angle (≤`angle_tol_deg`), magnitudes-only so direction-agnostic (forward `delta` and backward `delta_inv` share both → holds for `both`), (4) step>`min_step_nm` non-vacuity guard. The periodic analog of `assert_mate_coincident` but over a whole DERIVED chain + the single-repeat-unit invariant `assert_polymer_chain` (mate-seeded, delta re-derived from two existing instances) does not check; load-bearing because `canonical_assembly` sees the chain's structure survive `.nass` but is blind to whether the derived delta actually tiles. Can-go-red on a copy shoved off the chain (open seam) or a lone un-polymerized seed (no junctions) | `tests/automation_harness.py` (`assert_periodic_chain_tiles`); `backend/api/headless_assembly_build.py` (`polymerize_periodic`); drives `backend/core/periodic_polymer.derive_periodic_delta` | any auto-derived (no hand-mate) repeating chain whose junction geometry must close (periodic/belt seam tiling, future ring-closure checks) |
| `assert_part_from_primitive` (AF-12 Phase 2 — `from_primitive` catalog-by-name) | a `{"from_primitive": "<name>"}` part instance resolves to **exactly** the catalog primitive of that name — proving the grammar's *name→catalog-path resolver* picked the right primitive. The check `assert_part_from_file` cannot give: that oracle trusts a path already on the instance; here the catalog **NAME** is the input, so a resolver that mapped the name to the wrong/renamed primitive (or to nothing) must be caught. INDEPENDENTLY re-resolves `primitive_name` via `primitive_catalog.design_path` (NOT the interpreter's resolution), loads that primitive's `.nadoc`, computes `canonical_topology`, and delegates to `assert_part_from_file` (which loads what the *instance* actually references and compares) — so a name pointing at a different primitive than the build wired makes the two topologies diverge. Asserts name resolves in the catalog + instance is file-backed + topology matches. Can-go-red: wrong/renamed name → topology mismatch; unknown name → catalog-resolution guard | `tests/automation_harness.py` (`assert_part_from_primitive`); `backend/core/build_spec.py` (`PrimitivePart`/`_parse_part`); `backend/api/headless_spec_build.py` (`_resolve_primitive_path`); drives `backend/core/primitive_catalog.design_path` | any by-name resource resolver whose name→artifact mapping the structure fingerprint can't see (future `from_primitive` parametric/template kinds, named-fixture references) |
| `assert_part_is_circular_disc` (AF-12 Phase 2b — `from_primitive` PARAMETRIC circle) | a `{"from_primitive": "<circle>", "params": {"radius_nm": R}}` part instance is a GENERATIVELY-built circular disc of radius ≈ R — the parametric counterpart to `assert_part_from_primitive`, which is file-backed-only and would actively FAIL on this inline part. A parametric primitive is NOT file-referenced: the driver re-derives the disc at the requested radius (lowering to the SAME single `circle_segment` op a hand-authored spec uses) and embeds it INLINE, so the load-bearing check is GEOMETRIC, not a source pin. Asserts the instance is inline-backed (a file source means the static saved-default-radius disc was instanced instead of the requested parametric one — the wrong build branch), loads the design the instance embeds (via `_load_design_from_source`), and delegates to the AF-4 `assert_circular_disc` (reads placed axis geometry → circular + radius ≈ R). Pins `params.radius_nm → footprint → circle_segment → placed geometry` *through the assembly layer*, which `canonical_assembly` (keys an inline source by its embedded topology fingerprint, blind to whether that geometry is circular *of radius R*) cannot. Can-go-red: wrong requested radius → circularity/radius fail; a file-backed (static) instance → inline guard | `tests/automation_harness.py` (`assert_part_is_circular_disc`); `backend/core/build_spec.py` (`PrimitivePart.params`/`_parse_part`); `backend/api/headless_spec_build.py` (`_resolve_primitive_part`/`_build_circle_primitive`); reuses `assert_circular_disc` (AF-4) | any generatively-built (vs file-referenced) parametric part whose placed geometry must match a requested parameter (future `primitive_kind` template/hinge kinds; the inline-vs-file branch check reusable for any "right build path was taken" pin) |
| `assert_field_ready_specimen` (AF-18 — Tier 6 specimen spine) | the FIRST composite physical-layer oracle: an end-to-end-built design is *ready to run an electric-field experiment*. Composes three independently-proven properties into one verdict — (1) fully sequenced (`assert_fully_sequenced`), (2) relaxed geometry recovered (`assert_relaxed_geometry_recovered`), (3) **anchorable under a field**: the anchor descriptor resolved to real nucleotides AND a SHORT PROBE field child branched off the relaxed parent holds the anchored beads while the free part deflects ALONG the field (`measure_field_response.passed`). Load-bearing because each piece was pinned ALONE — nothing proved they **compose** into one runnable, anchorable specimen (the user's "build → … → set as anchor → run a field" chain). Direction-agnostic (probe measures magnitudes/projection); Three-Layer-clean (reads relaxed/field geometry, never writes it back). Can-go-red: unsequenced design (clause 1) / non-completed relaxation (clause 2) / empty-anchor or non-deflecting field (clause 3) | `tests/automation_harness.py` (`assert_field_ready_specimen`); `backend/api/headless_oxdna_build.py` (`build_field_specimen`); drives `resolve_anchor_particles` + `measure_field_response` | the Tier-6 field-experiment items (AF-19 equilibration τ, AF-20 field sweep, AF-23 cross-design campaign) — each runs its field on a specimen this oracle certified ready |
| `measure_field_equilibration` + `assert_equilibration_timeline` (AF-19 — Tier 6 time-resolved) | the FIRST TIME-RESOLVED physical oracle: where `measure_field_response` (AF-18) is **endpoint-only** (final pose vs reference), this reads the WHOLE field-stage trajectory and measures, frame by frame, (1) the free body's **alignment** (mean displacement of non-anchored nucleotides ALONG the field vs frame 0 — the `measure_field_response` projection, per frame) and (2) per-frame **base-pair retention** (`base_pair_retention`). Fits the monotone approach to its plateau (tail mean) and extracts the **equilibration time τ** (interpolated time to `1−1/e` of plateau). `converged` requires non-vacuous rise (≥`min_rise_nm`) + monotone-within-noise + an actual plateau (late-frame slope ≤ `plateau_slope_frac`·early slope — a run still climbing has NOT equilibrated → `tau=None`); `melted`=True if bp dips below `melt_floor` at ANY frame (transient-melt watch, blind to `measure_field_response`). Pure (`backend/core`, takes `read_trajectory_frames_full` maps + `design`); direction-agnostic (projection magnitude); Three-Layer-clean. The asserter confidence-gates trajectory frame count, then asserts converged + finite positive τ + no melt. Can-go-red: linear (never-plateau) ramp → no finite τ; bp floor breach mid-swing → melted; too-few frames → INCONCLUSIVE | `backend/core/oxdna_health.py` (`measure_field_equilibration`); `tests/automation_harness.py` (`assert_equilibration_timeline`); drives `read_trajectory_frames_full` + `base_pair_retention` | the AF-20 field sweep (measure τ per `(|E|,dir)` cell → field↔τ correlation map) + the AF-23 cross-design campaign; the per-frame-observable pattern reusable for any trajectory-resolved measure (R_g vs t, angle vs t) |
| `assert_field_sweep_map` (AF-20 — Tier 6 response surface) | the FIRST MULTI-config physical oracle: where every prior physical oracle (AF-13/18/19) measured one structure at one condition, this asserts a *response surface* over a swept `(|E|, direction)` grid. Four clauses on the `hox.sweep_field_response` map: (1) **no gaps** — nothing skipped + every grid cell carries a verdict (a sweep that silently dropped a condition is not a map); (2) **a non-destructive window exists** in `benign_range` — RECOMPUTED from the raw measured `aligned ∧ bp_min ≥ melt_floor`, NOT the wrapper's stored `destructive` flag (anti-echo: the oracle measures the surface, doesn't echo it); (3) **the destructive regime is destructive** — `destructive_range` covers ≥1 swept cell AND every such cell melted (the "without ripping it apart" window has a real upper bound; non-vacuity-guarded); (4) **τ ↔ |E| correlation** — within each direction's responsive (non-destructive) band, ordered by |E|, the equilibration time τ is monotone non-increasing AND actually falls (the strongest responsive field equilibrates faster than the weakest — not a flat line; ≥2 cells required). Direction-agnostic (τ + retention are magnitudes); Three-Layer-clean (reads each field trajectory, never writes back). Can-go-red: a skipped/incomplete grid; a benign band with no safe cell; a destructive band that did not melt; a flat field-independent τ | `tests/automation_harness.py` (`assert_field_sweep_map`); `backend/api/headless_oxdna_build.py` (`sweep_field_response`/`_measure_field_cell`); drives `measure_field_equilibration` per cell | the AF-23 cross-design campaign (run this sweep per specimen → per-design operating window + alignment-vs-field response); any multi-condition response-surface oracle over a physical-layer measure (force-extension curves, salt sweeps) |
| `field_equilibrium_observables` + `assert_oxpy_equilibrium_parity` (AF-21 — Tier 6 interactive engine) | the FIRST oracle over a SECOND engine: every prior physical oracle (AF-13/18/19/20/23) drove the *batch* CLI binary; AF-21 introduces a persistent in-process **oxpy** session (`backend/physics/oxdna_live.LiveOxdnaSession`/`_OxpyStepper`) that loads once, burst-steps, and re-aims a uniform field LIVE between bursts (no engine re-init), driven by `hox.run_live_field`. Pure `field_equilibrium_observables(field_full_map, ref_full_map, field_dir, anchor_keys, *, design)` composes 3 equilibrium observables — alignment (`measure_field_response` proj along field), `radius_of_gyration` (`measure_radius_of_gyration`), `bp_retention` (`base_pair_retention`) — into one engine-INDEPENDENT fingerprint (+ `field_equilibrium_from_confs` for the batch side). The oracle asserts (1) confidence-gated, (2) the live burst-stepped run reaches the SAME equilibrium (alignment + R_g within `tol_nm`, bp within `bp_tol`) the one-shot batch engine reaches — equilibrium-PROPERTY parity, since a stochastic thermostat forbids trajectory parity — and (3) a mid-run field re-aim STEERED the body (`mutation.followed`: deflection along the new vector increased). Load-bearing because nothing before proved the interactive engine is physically equivalent to the validated batch engine (else "real-time" output is untrustworthy) NOR that live field control actually steers. Direction-agnostic (magnitudes); the parity clause is testable GPU-free against the binary `_FIELD_MOCK_OXDNA` (an in-process mock stepper mirrors its position-based deflection so burst-stepping == one-shot), the live-mutation clause against the real oxpy build (binding-patched to expose `BaseForce.F0`/`.dir`). Can-go-red: a live run diverging from batch beyond tol (clause 2); a dead field re-aim that doesn't move the body (clause 3); a sub-gate confidence (clause 1) | `tests/automation_harness.py` (`assert_oxpy_equilibrium_parity`); `backend/core/oxdna_health.py` (`field_equilibrium_observables`/`field_equilibrium_from_confs`); `backend/physics/oxdna_live.py` (`LiveOxdnaSession`); `backend/api/headless_oxdna_build.py` (`run_live_field`) | AF-22 live field-steering (the steered timeline calls the same session); any second-engine equivalence proof (GROMACS/NAMD live analog) or interactive-vs-batch parity check |
| `assert_live_field_following` (AF-22 — Tier 6 interactive control loop) | the FIRST oracle over a STEERED PATH of field changes: where `assert_oxpy_equilibrium_parity` (AF-21) pins ONE field re-aim's equilibrium, this pins an arbitrary *sequence* of waypoints — the headless analog of a user dragging the field gizmo through a path. On the `hox.steer_field_session` timeline (`{"timeline":[{field_dir, proj_before_nm, proj_after_nm, bp_retention, …}, …], "n_waypoints":N}`): (1) **non-vacuity** — ≥2 waypoints AND ≥1 leg whose field-following move (`proj_after−proj_before`) ≥ `min_following_nm` (a stationary all-zero timeline cannot pass); (2) **field-following** — at EVERY waypoint the free body's deflection ALONG that leg's own field vector ROSE across the burst (`proj_after>proj_before`), i.e. running under the re-aimed field moved the structure toward the new direction (a body that ignored a waypoint change fails); (3) **no melt during steering** — `bp_retention ≥ melt_floor` at EVERY waypoint (followed the field across the whole path WITHOUT ripping apart — the "without melting" half, now over a *trajectory* of field changes). Load-bearing because nothing before proved the interactive control LOOP (many field changes in sequence) sustains field-following without a melt — AF-21 pins a single re-aim, blind to a multi-step path. Direction-agnostic (signed projections along each leg's own vector → no handedness); GPU-free testable against the `_MockFieldStepper` (orthogonal waypoints → each leg's `proj_before≈0`→`proj_after≈200·F0`); reds hand-built (the no-melt mock can't melt). Can-go-red: an ignored waypoint (clause 2); a melt at any waypoint (clause 3); a stationary timeline (clause 1) | `tests/automation_harness.py` (`assert_live_field_following`); `backend/api/headless_oxdna_build.py` (`steer_field_session`); drives the AF-21 `LiveOxdnaSession.set_field`/`run`/`equilibrium_observables` | the frontend live-steering UI (the headless control loop behind it); any interactive multi-step control sequence whose per-step response must be proven (a steered temperature/salt ramp, a gizmo-driven deformation path) |
| `assert_field_campaign` (AF-23 — Tier 6 CAPSTONE, cross-design study) | the FIRST MULTI-DESIGN physical oracle: where every prior physical oracle (AF-13/18/19/20) measured ONE structure (AF-20 at many conditions), this asserts a *campaign* — the same `(|E|, direction)` sweep run + compared across MANY designs. Four clauses on the `hox.run_field_campaign` result: (1) **no dropped design** — `skipped` empty + `sweeps` non-empty (a campaign that silently lost a design is not a study; AF-20's no-truncation rule, one level up); (2) **every design is a valid response surface** — each design's sweep passes `assert_field_sweep_map` (populated grid + benign window + destructive bound + τ↔\|E\|), so each carries a *reported* non-destructive operating window; (3) **DISTINGUISHABILITY** — ≥2 designs differ at a shared responsive `(\|E\|, dir)` cell by ≥`min_tau_separation_steps` τ (a floppier/longer-lever design equilibrates on a different timescale), recomputed from raw `aligned ∧ bp_min ≥ melt_floor` (anti-echo, NOT `cell["destructive"]`) — the load-bearing NEW assertion over AF-20: AF-20 pins ONE surface, nothing before proved the campaign produces design-DISCRIMINATING surfaces (the whole point of "various designs"); (4) **reproducible** — if `repro` (a 2nd run) given, every shared design+cell τ matches within `tau_tol_steps` (the deterministic-mock re-run is identical — a prerequisite for trusting any automated cross-design conclusion). Direction-agnostic (τ + retention magnitudes); Three-Layer-clean (reads each field trajectory, never writes back). Can-go-red: a skipped design (clause 1); a design with no safe/destructive window (clause 2); indistinguishable designs (clause 3); a non-deterministic re-run (clause 4) | `tests/automation_harness.py` (`assert_field_campaign`/`_campaign_tau_signature`); `backend/api/headless_oxdna_build.py` (`run_field_campaign`); composes `assert_field_sweep_map` per design | ANY cross-design / cross-condition campaign over a physical-layer measure (multi-design force-extension, salt/temperature campaigns, batch screening); the distinguishability pattern (per-design signature → assert ≥2 differ at a shared cell) reusable for any "prove the study discriminates its subjects" oracle |
| `assert_linker_connects` (AF-27 P1 — overhang-linker tie) | an overhang LINKER connection wires the two named overhangs at the requested contour length and **persists across a `.nadoc` round-trip**. Re-reads the connection (by id) on BOTH the in-memory design and its `roundtrip_nadoc` re-import, asserting: (1) the connection exists; (2) `{overhang_a_id, overhang_b_id}` == the expected set (order-independent — A/B is symmetric); (3) `_length_value_to_bp(length_value, length_unit)` == `bridge_bp` (the route's OWN lowering, so an nm length pins through the B-DNA-rise conversion). Load-bearing because `canonical_topology` does NOT fingerprint `overhang_connections` — the same blind-spot the cluster/loop-skip/binding oracles work around, so a build that dropped the tie or rewired it to a different overhang while keeping the linker strands would slip past a structure check; only re-reading the connection after export→import catches it. Three-Layer note: creating the connection IS a topological edit (appends linker complement strand(s) + a virtual `__lnk__` bridge helix for ds) — an allowed write, distinct from the Phase-2 relax pose. Can-go-red: no connection (clause 1) / wrong partner overhang (clause 2) / a length that lowered to a different bp count (clause 3) / a connection the import silently dropped (round-trip pass). | `tests/automation_harness.py` (`assert_linker_connects`); `backend/api/headless_build.py` (`connect_overhangs`); drives `backend/core/lattice._length_value_to_bp` | any metadata-bearing design-layer relation the topology fingerprint can't see (the AF-27 P2 relax pose, future linker/bond relations); the order-independent join-set + route-own-lowering checks reusable for any "this relation wires the right endpoints at the right magnitude" pin |
| `assert_flexible_segments_relaxed` (AF-29 — hinge ssDNA scaffold-tether relax) | a headless flexible-segment relax reached the SAME physical rest state the in-app PBD solve reaches. Three clauses: (1) **constraint satisfied** (load-bearing, solver-independent) — every `flexible_connection`'s anchor-to-anchor chord, measured on the POSED geometry (`_geometry_for_design` applies the relaxed cluster transforms), is ≤ `contour_length_nm + tol` (no tether left overstretched); (2) **a pose moved** (`require_moved` — the vacuous-pass guard, same shape as AF-2's forward-mutated guard): ≥1 cluster's translation/rotation differs from `before`, so a no-op "relax" on an overstretched design can't pass; (3) **topology unchanged** — `canonical_topology(before)==canonical_topology(after)` (the Three-Layer Law as a pin: relax is a display/pose move, never a strand-graph edit). Pairs with the JS↔Python PARITY pin (`relax_cluster_pose` reproduces the `flexible_relax_solver.js` golden to 1e-6) so the headless result == in-app. Can-go-red: still-overstretched after (clause 1) / no pose moved (clause 2) / a topology-mutating relax (clause 3) | `tests/automation_harness.py` (`assert_flexible_segments_relaxed`); `backend/core/flexible_relax.py` (`relax_cluster_pose`/`compute_relax_transforms`); `backend/api/headless_build.py` (`relax_flexible_segments`); parity golden in `frontend/src/scene/flexible_relax_solver.{js,test.js}` ↔ `tests/test_flexible_relax.py` | any display/pose-layer constraint solve whose RESULT must satisfy a geometric bound (linker relax pose AF-27 P2, future ssDNA constrained drags); the "measure the posed result, not the solver internals" + JS↔Python-golden-parity pattern reusable for any ported frontend solver |
| `assert_forced_ligation` (AF-32 — forced-ligation tie) | a forced ligation merged the named 3'/5' strand ends into ONE strand, recorded the right junction endpoints, AND the record persists across a `.nadoc` round-trip. Takes BOTH `before` (pre-ligation, to re-derive the expected endpoints exactly as the route does — 3' = last domain of the 3' strand, 5' = first domain of the 5' strand → catches a 3'/5' swap or wrong helix/bp) and `after`. Five clauses: (1) both named strands exist in `before`; (2) the `ForcedLigation` record exists under `fl_id` with stored 3'/5' `(helix_id, bp, direction)` == re-derived; (3) the two strands merged into one (`len(after.strands) == len(before.strands) − 1`); (4) a single strand spans both endpoints (the AF-31 `_strand_spans_both` — the backbone-merge pin, not just a record appended); (5) **the record survives a `.nadoc` round-trip** (load-bearing — the FL record lives on `design.forced_ligations`, OFF the strand graph, so `canonical_topology` is blind to it; only re-reading after export→import proves persistence, the cluster/overhang-connection blind-spot again). Reuses AF-2 `assert_inverse_pair` as a CLEAN force-ligate→delete pair (forced ligation adds NO nicks, unlike AF-31's crossover place). Can-go-red: missing strand (1) / no record or wrong endpoint (2) / wrong strand count (3) / record-without-merge (4) / round-trip dropped the record (5) | `tests/automation_harness.py` (`assert_forced_ligation`); `backend/api/headless_build.py` (`force_ligate`/`delete_forced_ligation`); reuses `_strand_spans_both` (AF-31) + `roundtrip_nadoc` (AF-1) | any "this op wired the named endpoints AND merged the backbone, and its off-strand-graph record persists across save/load" pin (the AF-33 hinge builder's 2N cross-gap FL links next); the before+after endpoint-re-derivation pattern reusable for any op whose stored record should match what it operated on |
| `assert_matches_primitive` (AF-33 — hinge golden-equality) | a code-built hinge primitive is byte-for-byte the validated hand-built golden `workspace/Primitives/<name>.nadoc` — the pin that "recreate the standard hinges in code" must not DRIFT from. Loads the golden (resolved via `primitive_catalog.design_path`, the same resolver the `from_primitive` grammar uses) and asserts, in order: (1) the golden exists (catalog-resolution guard); (2) `canonical_topology(built)` == golden's (same helices/cells/strand-paths/axis geometry → catches a wrong leaf layout / duplex span / dropped strand); (3) **forced-ligation endpoint-set equality** via `_fl_endpoint_set` (3'/5' `(helix_id,bp,direction)`, order-independent) — **load-bearing** because `canonical_topology` does NOT fingerprint `forced_ligations` (the off-strand-graph blind-spot, 5th instance after clusters/loop-skips/connections/FL-record), so a dropped/extra/mis-wired cross-gap link slips past clause 2 entirely; (4) `roundtrip_nadoc`-stable (topology AND FL-set unchanged across export→import); (5) `validate_design` passes. Can-go-red: dropped/extra/mis-wired link (3) / wrong leaf layout or duplex span (2) / import silently altered (4) / unknown name (1) | `tests/automation_harness.py` (`assert_matches_primitive`/`_fl_endpoint_set`); `backend/api/headless_hinge_build.py` (`build_hinge_primitive`); drives `backend/core/primitive_catalog.design_path` + `roundtrip_nadoc` (AF-1) | any "code-built artifact reproduces a saved golden, INCLUDING its off-strand-graph records" pin (AF-33 P2 2x4/2x6 hinges; future generated primitives/templates); `_fl_endpoint_set` reusable for any FL-bearing design comparison |
| `assert_crossover_joins` (AF-31 — manual crossover place) | a manually-placed crossover RECORDED the two named half-sites AND (when ligated) actually merged the backbone between them. Four clauses: (1) the `Crossover` record exists under `xover_id`; (2) it joins the two named half-sites as an **order-independent** `(helix_id, index)` set (A/B is symmetric); (3) **ligation outcome matches** `expect_ligated`: True → the crossover is NOT in `unligated_crossover_ids` **and** a single strand spans both half-sites (load-bearing via `_strand_spans_both` — this catches a "record appended but ligate silently failed because nick_bp was wrong → no terminal match" build, which is NOT in the same-strand unligated set, so the unligated-set check alone would miss it); False → the crossover IS in `unligated_crossover_ids` (the documented recorded-but-unligated cycle-avoidance outcome); (4) `validate_design` passes — **ligated branch only** (an unligated crossover sits at a strand terminus the validator flags as non-physical, "Nick the strand to ligate", by design). Reuses the AF-2 `assert_inverse_pair` as **delete→place** (NOT place→delete: place adds nicks a desplice doesn't undo). Can-go-red: missing record (1) / rewired half-site (2) / record-without-backbone-merge or ligated-when-cycle-expected (3) | `tests/automation_harness.py` (`assert_crossover_joins`/`_strand_spans_both`); `backend/api/headless_build.py` (`place_crossover`/`delete_crossover`); drives `backend/api/crud.unligated_crossover_ids` | any "this op wired the named endpoints AND actually changed the strand graph (not just appended a record)" pin where a metadata record and the backbone edit can diverge (forced-ligation AF-32 next, future junction ops); the ligated-vs-unligated-outcome branch reusable for any op with a deliberate partial-success state |
| `assert_scaffold_routing_compliant` (AF-34 — autoscaffold routing compliance) | a headless autoscaffold output is *routing-compliant* origami — a real seamed (or seamless) route, NOT a single-pass raster with scaffold crossovers buried in staple domains. The reusable harness face of `backend.core.scaffold_invariants.scaffold_routing_invariants` (the regression gate added after the 2026-06-26 hinge incident, LESSONS H8 — a seamless raster shipped green because `validate_design` encodes none of these properties), previously asserted only INSIDE `test_scaffold_invariants.py` over fixed entry points. Two clauses: (1) **non-vacuity** — the design HAS a non-reference scaffold strand (an un-routed/empty design has no crossovers → the checker returns `[]` vacuously, so without this guard the oracle passes on a design `auto_scaffold` silently failed to route); (2) **compliant** — `scaffold_routing_invariants(design, require_seams=...)` returns no violations (seamed: genuine mid-helix seam crossovers present AND every non-seam end/turn scaffold crossover ≥`MIN_SSDNA_MARGIN`=3 bp clear of any staple domain on its helix; `require_seams=False` for inherently seamless/zig-zag routes). GOTCHA: a plain `create_bundle` routed seamed is NOT compliant (its blunt full-length staples bury the end crossovers) — the genuine seamed-green path is the HINGE end-to-end (the duplex shift leaves proper margins); the oracle's seamless route (`require_seams=False`) is the non-hinge green example, and the SAME seamless route at `require_seams=True` is the load-bearing red (LESSONS H8). Can-go-red: no scaffold (1); a seamless raster at `require_seams=True` (2 — no seams); a buried crossover (2 — margin) | `tests/automation_harness.py` (`assert_scaffold_routing_compliant`); wraps `backend/core/scaffold_invariants.scaffold_routing_invariants`; driven end-to-end via `backend/api/headless_hinge_build.build_hinge_primitive` → `headless_build.auto_scaffold` (dispatches to `backend/core/hinge_router`) | any headless autoscaffold output (every future routed build can pin "this is real routable origami, not a buried-crossover raster"); the non-vacuity-then-gate pattern reusable for any "wrap a self-gate checker as a build-time oracle" |
| `assert_primitive_placed` (AF-35 — multi-op primitive placement) | a whole pre-built primitive (a hinge: two rigid leaves + cross-gap forced-ligation links) was placed into a host design **verbatim** — a clean rigid translation of the standalone primitive, anchored at `anchor_cell`, host content untouched. Takes `before`/`after` (host pre/post) + the `primitive` Design. Six clauses: (1) **non-vacuity** — ≥1 helix added (`after`⊋`before` by id); (2) **additive** — the host portion of `after` (helices ∈ `before` ids + its strands/FLs/clusters) has `canonical_topology` == `before` (placement never mutates the existing strand graph); (3) **anchored** — the placed sub-structure's min `grid_pos` == requested `anchor_cell` (it landed where asked); (4) **verbatim** — offset-correct the placed sub-structure back by the lattice vector `anchor_cell` implies (re-derived INDEPENDENTLY from `_lattice_position` — the lattice CONSTANT, not the graft's own `_world_delta`, so a graft plane-mapping/per-helix-translation bug can't self-mask) → its `canonical_topology` == the primitive's; (5) **FL links preserved** — placed FL set keyed by helix *grid_pos* (id-independent — survives the remap) == primitive's, **load-bearing** because `canonical_topology` is blind to `forced_ligations` (the off-strand-graph blind-spot, so a dropped/mis-wired cross-gap hinge link slips past clause 4); (6) **cluster groupings preserved** — placed rigid-leaf clusters keyed by member grid_pos == primitive's (also invisible to clause 4). Can-go-red: nothing placed (1) / host mutated (2) / wrong cell (3) / distorted-or-mis-translated copy (4) / dropped FL (5) / lost cluster (6) | `tests/automation_harness.py` (`assert_primitive_placed` + `_placement_subdesign`/`_translate_subdesign`/`_fl_grid_set`/`_cluster_grid_sets`); `backend/api/headless_build.py` (`place_primitive`); `backend/core/primitive_placement.py` (`place_primitive_into`); drives `backend/core/lattice._lattice_position` | any "this op grafted a whole sub-structure VERBATIM (rigid copy at a named cell, off-strand-graph records intact) without disturbing the host" pin (future multi-op primitive placement / pretransformed-cluster compose); the independent-offset-correct-via-the-lattice-constant pattern reusable for any "prove a placement is an exact rigid copy" check, and the grid-keyed FL/cluster sets reusable for any id-remapped comparison |
| `_rail_faces_toward` (AF-36 — hinge phase-paired short/long routing) | which of a hinge's cross-gap rungs is SHORT vs LONG ssDNA, from helical PHASE not a hardcoded column parity. The scaffold backbone radial at the gap-face duplex-edge bp (axis-projected) · the rail-A→rail-B chord: `>0` (faces TOWARD the far leaf) → that rung takes a SHORT (2nt) tether; `<0` (faces AWAY) → LONG (16nt ≈ 1 turn to re-phase toward the partner). Neighbouring columns alternate (adjacent helices carry opposite phase). `build_hinge` derives the per-column scaffold extension from this and reproduces the 2x2/2x4 goldens byte-for-byte (canon + `_fl_endpoint_set`); replaced the uniform every-rung tether. Three-Layer-clean (a geometric READ of the post-shift design; never writes topology). Can-go-red: a hinge built uniform (all-short or all-long) fails the golden match | `backend/api/headless_hinge_build.py` (`_rail_faces_toward`/`_scaffold_on_helix`/`build_hinge`); validated vs `workspace/Primitives/2x{2,4}_*.nadoc` | any phase-governed fine-routing decision (which face a crossover/tether/overhang takes from backbone azimuth); the "backbone-radial · target-chord at a reference bp" test reusable for any "does this helix face toward X" question |
| seek-fidelity restore (AF-36 — `_topology_substitute` ← cluster_joints + flexible marks/connections) | a feature-log SEEK reconstructs the FULL state at a position INCLUDING joints + flexible-segment marks/connections, not just the strand graph. Bug class: `_topology_substitute` (the seek snapshot restorer) swapped only strand-graph topology + overhangs, so `cluster_joints`, `flexible_segment_marks`, and the derived `flexible_connections` lived in BASE state and persisted at EVERY seek position incl. the empty state (a joint/mark placed late never disappeared scrubbing back). Fix: restore all three from the seek snapshot (membership is topology-like — same rationale as overhangs; joints store a LOCAL-frame axis so invariant under the cluster-transform delta replay that runs after). Companion: commit a relax as a logged `cluster_op` (`transform_cluster(log=True)`), NOT the `flexible-relax` snapshot route — seek rebuilds cluster poses ONLY from cluster_op, so a flexible-relax pose bakes into base state (revert-endpoint-only). Pins (both proven red-without-fix): seek before the op → gone, seek to latest → restored | `backend/api/crud.py` (`_topology_substitute`); `tests/test_joints.py::test_seek_before_joint_placement_drops_the_joint`; `tests/test_flexible_segments.py::test_seek_before_mark_drops_flexible_marks` | any autogenerated design whose feature-log timeline must be faithful (every pose/joint/annotation op toggles on the slider); the "membership from the snapshot, overlays from deltas" rule for any new persisted-but-not-delta-replayed field |
| `assert_linker_relaxed_pose` (AF-27 P2 — overhang-linker relax pose) | a headless "Relax Linker" pose pulled the linker toward its natural span, moved a rigid pose, and **did not touch topology**. STRAIN-REDUCTION (the user-chosen property, not raw chord-≤-contour): `strain(d) = |chord(d) − natural_span|` where `chord` is the distance between the two linker attach anchors RE-MEASURED on the POSED geometry (`_geometry_for_design` → `linker_relax._anchor_pos_and_normal`, the relax's own ground-truth anchor lookup — NOT its connector-arc optimiser) and `natural_span` is the ds duplex visualLength (`_ds_target_length_nm`; `natural_span_nm=` override for an ss FJC R_ee). Three clauses: (1) `strain(after) < strain(before)` — load-bearing, solver-independent; a relax that left the linker no closer to its span fails (so does a DEGENERATE hinge whose moving anchor sits on the joint axis — rotation can't change the chord, the natural can-go-red); (2) a cluster pose moved (vacuous-pass guard); (3) `canonical_topology` unchanged (the Three-Layer Law as a pin — the linker relax mutates only `cluster_transforms`+a `ClusterOpLogEntry`). The relax optimises connector-ARC residuals internally; this oracle pins the solver-INDEPENDENT consequence (chord → natural span), the AF-29 "measure the posed result, not the solver internals" rule again. Can-go-red: no-op/degenerate (1+2); topology-mutating relax (3) | `tests/automation_harness.py` (`assert_linker_relaxed_pose` + shared `_assert_relax_pose`/`_relax_pose_moved`); `backend/api/headless_build.py` (`relax_overhang_connection`); reuses `linker_relax._anchor_pos_and_normal`/`_ds_target_length_nm` | any display/pose-layer constraint solve whose RESULT must move a measured quantity toward a natural target (AF-27 follow-ups, future ssDNA/linker rest-pose solves); the strain-reduction-on-posed-geometry pattern reusable for any "relax pulled X toward its target without editing topology" pin |
| `assert_bond_relaxed_pose` (AF-27 P2 — generic backbone-bond relax pose) | the `assert_linker_relaxed_pose` analog for the generic `relax_bond` (crossover / forced-ligation / linker-arc / strand-arc): `strain = |bond_chord − target_nm|` where `bond_chord` is the distance between the two named nucleotide endpoints (`{helix_id, bp_index, direction, strand_id?}`) re-measured on the POSED geometry, and `target_nm` is the chord target the relax closes onto (crossover ~0.13, ligation 0, arc ~0.67). Same three clauses (strain reduced + pose moved + `canonical_topology` unchanged) — chord re-measured independently of the relax's `relax_info`. Pins the 0-DOF rigid-translate AND 1-DOF/N-DOF joint-rotate paths identically. Can-go-red: no-op / topology-mutating relax | `tests/automation_harness.py` (`assert_bond_relaxed_pose`); `backend/api/headless_build.py` (`relax_bond`); shares `_assert_relax_pose` with the linker oracle | any generic backbone-bond pose relax (crossover/ligation/arc rest-pose checks); the endpoint-by-(helix,bp,dir) chord re-measure reusable for any "this op closed a named bond toward its target" pin |
| `assert_binding_relaxed_pose` (AF-38 — direct root-to-root BINDING relax pose) | the `assert_linker_relaxed_pose` analog for the DIRECT-binding relax (`relax_overhang_binding`): `strain = |chord − target_nm|` (default 0.67) where `chord` is the distance between the two bound sub-domains' junction anchors (`binding_relax._sub_domain_junction_anchor`) re-measured on the POSED geometry. Same three clauses (strain reduced + cluster pose moved + `canonical_topology` unchanged), reuses `_assert_relax_pose`. **Fixture gotcha:** use a Z-axis joint — a Y-axis joint leaves a y-offset the rotation can't close (chord already at its x-z minimum → false degenerate). Can-go-red: no-op / topology-mutating relax | `tests/automation_harness.py` (`assert_binding_relaxed_pose`); `backend/api/headless_build.py` (`relax_overhang_binding`); reuses `binding_relax._sub_domain_junction_anchor` | any direct WC-bind rest-pose check; the sub-domain-junction chord re-measure reusable for binding/lock relax pins |
| `assert_end_to_root_relaxed_pose` (AF-38 — end-to-root relax pose) | the end-to-root analog: `strain = |FL_chord − target_nm|` (default 0.67) where `FL_chord` is the spliced ForcedLigation chord (binder connecting bead ↔ B-root connecting bead) re-derived on POSED geometry via `end_to_root_relax._find_binder_and_root` + `_bead_pos`. Clauses: strain reduced + **a pose moved (cluster transform OR A's `OverhangSpec.rotation` — the 2-DOF duplex swing lives on the rotation, so the same-rigid-body swing-only relax isn't a false negative)** + `canonical_topology` unchanged (the swing + cluster poses don't touch helix axes, all the fingerprint reads). Can-go-red: no-op / topology-mutating relax | `tests/automation_harness.py` (`assert_end_to_root_relaxed_pose` + `_overhang_rotation_changed`); `backend/api/headless_build.py` (`relax_end_to_root`); reuses `end_to_root_relax._find_binder_and_root`/`_bead_pos` | any relax whose pose move can land on an overhang ROTATION (not just a cluster) — the rotation-aware pose-moved guard reusable for overhang-orientation-driven rest poses |
| `assert_end_to_root_binder` (end-to-root direct binding — regenerate B as A's RC binder) | applying an `end-to-root` ConnectionVersion is a TOPOLOGICAL splice, not a metadata append: it asserts, on BOTH the in-memory design and its `roundtrip_nadoc` re-import — (1) A survives as a free overhang (spec + backing domain); (2) **exactly one** binder domain tagged `binds_overhang_id == A` exists, on A's helix, at A's bp range, antiparallel to A; (3) it's spliced into a STAPLE strand (B's former root) with ≥2 domains and the binder is a strand TERMINAL (B-root → binder is one continuous 5'→3' strand); (4) **B is consumed** — no `OverhangSpec` for B, no domain tagged `overhang_id == B`; (5) when a scaffold sequence exists, the binder reads RC(A) after `assign_staple_sequences` (else the `binds_overhang_id` link in clause 2 already guarantees the sync, pinned by `test_oh_binder.py`); (6) **no orphaned helix** — B's emptied overhang helix is deleted (every helix has ≥1 domain); (7) **no stale crossover** — every crossover half references a live helix (B's overhang crossover that pointed at the deleted tip helix is gone — the caDNAno stale-line bug); (8) **forced ligation at the root→binder junction** (relocated tip lands on A's non-adjacent helix → the parent→tip jump becomes a `ForcedLigation`, not a lattice crossover). The "exactly one" + "B gone" clauses AFTER re-import are the red test for the `autodetect_overhangs` `binds_overhang_id` skip-guard (lattice.py:3370) — without it save→load spawns a phantom B overhang. Can-go-red: no-op apply (B tip still there) / binder on B's helix / standalone-strand binder (not spliced) / phantom overhang on round-trip. | `tests/automation_harness.py` (`assert_end_to_root_binder`); `backend/api/headless_build.py` (`create_connection_version` + `apply_connection_version`, route coverage 50→52); drives `lattice.apply_end_to_root_binder` + extracted `_binder_domain_for_overhang` | any "abstract relation materialized into real spliced topology" pin where one entity is consumed into another's strand; the exactly-one + consumed-partner + round-trip-survives pattern reusable for direct-binding / merge-style ops the topology fingerprint can't see |

---

## Metrics rows + Data summaries → archived

Moved to **`design_automation_metrics.md`** (2026-06-25) so this file stays under the Read cap.
That archive holds one metrics row per shipped AF item (+ data fits). Append new rows THERE; read it on demand.

---

## Lessons (anti-patterns banked — read before building)

- **1-DOF relax fixtures can be FALSE-DEGENERATE (AF-38).** A strain-reduction relax test only proves anything if
  the joint can actually reduce the chord. A single revolute joint sweeps the moving anchor on a circle in the plane
  ⊥ to its axis; if that plane is orthogonal to the chord's reducible direction (or the chord is already at the
  circle's closest approach), rotation changes nothing and the relax correctly no-ops — your "passing" test is
  vacuous, and your "can-go-red" degenerate is indistinguishable from a real no-op. AF-38's binding fixture hit this
  with a Y-axis joint (the two whole-overhang sub-domain anchors carried a y-offset rotation couldn't close); the fix
  was a **Z-axis joint** so rotation acts in the anchors' z=0 plane (chord 2.735→1.89 nm, genuine). NOT a product bug
  — the relax is right to do nothing. When you build a relax fixture: pick the joint axis so the chord's gap lies IN
  the rotation plane, and print chord-before/after to confirm a real reduction before trusting the green.

_(Candidates the audit already suggests:)_
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

### Banked from AF-18 (Tier 6 — field-specimen builder)
- **`assert_relaxed_geometry_recovered`'s key-set-equality is exact only for DENSELY-populated bundles.** It asserts
  the oxDNA display readback covers EVERY `_geometry_for_design` slot. But the geometry kernel emits a slot for every
  `(helix, bp, direction)` on an occupied helix, while oxDNA exports only actual *strand* nucleotides — and a **routed
  scaffold doesn't doubly-occupy every lattice slot** (a `bundle → auto_scaffold → full_autostaple` 6hb has geom 756 ⊃
  oxDNA-order 630, 126 strand-less slots). So the strict oracle passes on the dense `_sequence_for_oxdna(make_6hb)`
  fixture (geom == order == 504) but FAILS on any routed design. Prove the dense fixture with the full composite
  oracle; prove other build branches (sequence/build-spec) with their *specific* property (e.g. `assert_fully_sequenced`
  + `canonical_topology` equality) and skip the geometry clause. NOT a bug — geometry slots ⊋ strand nucleotides is
  legitimate for partially-occupied helices.
- **An `overhang_id` tag makes `full_sequence` SKIP that domain** (overhangs have no WC partner → left `'N'`), so a
  field run then 400s on undefined bases. Tag the anchor overhang AFTER sequencing (the `_design_with_overhang_anchor`
  fixture does), or — when you need `sequence=True` to run — use a `domain`/`cluster` anchor (no topology tag) instead.
- **You cannot build a field specimen from an UNSEQUENCED design at all** — `create_oxdna_job` 400s on any undefined
  base, so the relaxation refuses before the oracle runs. To exercise the composite oracle's "not fully sequenced"
  can-go-red path, hand the oracle a *raw* design as its `design` arg (clause 1 = `assert_fully_sequenced` fires
  first, before the job is touched) rather than trying to build an unsequenced specimen.
- **`build_field_specimen` is COMPOSITION (coverage flat 37).** It wraps no new route — it chains `build_design` /
  `overhang_extrude` / `full_sequence` / `run_relaxation` + `resolve_anchor_particles`. The new validation power is
  the composite "field-ready" oracle + the proven probe-field, exactly like the 4-bar capstone. Don't expect a
  coverage bump; the justification is the composition.

### Banked from AF-25 (feature-log seek)
- **Seek reconstruction split topology membership from display deltas — and dropped one.** `crud._seek_feature_log`
  rebuilds a past state in two passes: `_seek_snapshot_base` → `_topology_substitute` restores the topology-bearing
  *fields* from the nearest snapshot, THEN a delta-replay loop re-applies overlays (deformations, cluster transforms,
  overhang **rotations**). The trap: `_topology_substitute` listed helices/strands/crossovers/extensions/… but **not
  `overhangs`**, and the delta loop only ever rotates overhangs — it never adds/removes them. So overhang *membership*
  had no owner: seeking before an overhang-extrude (or to empty) removed the overhang's helix + strands but left a
  dangling `overhangs` entry. Lesson: when a field is split across "snapshot restores membership" + "delta replays the
  display attribute", **every such field must appear in the snapshot-substitution list** — a field that's only ever
  *adjusted* by deltas, never *created/destroyed* by them, will silently keep stale live membership.
- **A stale fingerprint field is invisible until something hashes it.** `overhangs` is in `design_build_fingerprint`,
  so the dangling entry quietly poisoned the hash → the job-roll's `fp(seeked)==fp(snapshot)` clean-path check failed
  and silently took the fallback branch; nothing crashed, no test caught it (per-slice tests never seeked *past* an
  overhang). The oracle that records the forward fingerprint and demands the back-seek reproduce it is what surfaced
  it. Write fingerprint-equality oracles for any "reconstruct an earlier state" path.

### Banked from AF-12 Phase 2b (parametric `from_primitive` circle)
- **A parametric primitive flips the part SOURCE from file to inline — so its pin must be geometric, not a source
  pin.** AF-12 P2 (static) resolves a catalog name → a `.nadoc` PATH and instances by reference (`add_file_instance`);
  `assert_part_from_primitive` re-resolves the path and compares topology. A *parametric* circle has no fixed saved
  geometry to reference — its size is the spec's knob — so it is built GENERATIVELY and embedded INLINE
  (`add_inline_instance`). `assert_part_from_primitive` would actively FAIL on it (it asserts `source.type == "file"`).
  The right pin is `assert_part_is_circular_disc`: load the embedded design and reuse the AF-4 `assert_circular_disc`
  geometric oracle. The inline-vs-file assertion in that oracle doubles as a "right build branch was taken" check —
  a parametric primitive that came out file-backed means the driver re-used the saved default-radius disc.
- **Build the parametric disc by LOWERING to its primordial op, not by hand-constructing a Design.** `_build_circle_primitive`
  emits a one-op design spec `{"lattice":"SQUARE","ops":[{"op":"circle_segment","radius_nm":R,…}]}` and runs it through
  `build_design` — so a `from_primitive` circle is canonical-topology-identical to a hand-authored `circle_segment` op,
  inherits all the op parser's validation (SQUARE-required, `radius_nm > 0`), and keeps coverage flat (no new route).
  Reuse the catalog's saved `plane`/`min_chord_bp` (via `primitive_catalog.derive_placement_spec`) so only the radius is
  the author's knob.
- **Keep the parser catalog-agnostic; decide param rules at BUILD time.** `_parse_part` validates `params` as a generic
  name→number map only — it does NOT know whether a name is a circle. "circle requires `radius_nm`" and "a static
  primitive forbids params" are enforced in `_resolve_primitive_part`/`_build_circle_primitive`, *after* the catalog's
  `primitive_kind` is read. This mirrors AF-12 P2's "name validity is a build-time check" rule and keeps the pure parser
  free of catalog knowledge.

### Banked from `crossover_extra_bases` (design op — extra bases at crossover junctions)
_headless-coverage Δ:_ **39 → 41 / 239** (the single + batch extra-bases PATCH routes flipped to covered) ·
_oracle shipped:_ `assert_crossover_extra_bases(design, seq, *, crossover_filter | expected_count)`.
- **Extra bases were automatable manually but NOT declaratively — a real gap, not a deferred item.** The topology field
  (`Crossover.extra_bases`) + the single/batch PATCH routes + the `crossover-extra-bases` minor-log entry all existed;
  the build-spec had `auto_crossover` (places junctions, zero params) but no way to *annotate* them. Closed with one op,
  two addressing modes, mirroring loop_skip's shape.
- **Address placed junctions declaratively, never by uuid.** `auto_crossover` assigns random uuids, so a portable spec
  can't reference them. Precise mode addresses a junction by its two helix cells + shared bp index (order-independent on
  the pair); bulk mode by a `scaffold|staple|all` filter resolved through the existing `enumerate_crossovers`
  `crossover_type` (NO new placement/topology reasoning — `feedback_crossover_no_reasoning` respected: the op only sets
  metadata on junctions the engine already placed).
- **The pin must READ extra_bases back — `canonical_topology` is blind to it (like a loop/skip mark).** Extra bases are
  junction metadata outside the strand graph, so `assert_spec_matches_calls` only proves topology preservation, never the
  value landed. `assert_crossover_extra_bases` is the load-bearing pin; its exclusivity check (every NON-targeted
  crossover must stay `None`) is the can-go-red guard against a bulk set bleeding onto the wrong junction type.

### Banked from AF-31 (manual crossover place/delete)
- **An op + its "delete" is NOT always a clean inverse — find which direction restores.** `place_crossover` =
  nick + ligate + record; `delete_crossover` only desplices (re-splits the merged strand). The nicks place
  introduced PERSIST after a desplice, so **place→delete on a fresh bundle leaves extra nicks and fails
  `assert_inverse_pair`** (proven empirically — the round-trip topology differed by 2 nicks). The clean inverse is
  **delete→place** from a design that already carries the crossover: delete splits at the junction, place
  re-ligates (the re-nick is a no-op since the fragments already terminate there). When an op's inverse isn't a
  perfect round-trip, try the *other* ordering before assuming the op is buggy.
- **The same-strand "unligated" set does NOT prove a crossover ligated — check the strand graph directly.**
  `unligated_crossover_ids` only catches the cycle-avoidance case (both halves resolve to the SAME strand). A
  place whose `nick_bp` was wrong (no terminal match) ligates nothing yet is NOT in that set, so
  `xover_id not in unligated_set` is necessary-but-not-sufficient for "ligated". The load-bearing check is
  `_strand_spans_both` — a single strand actually has domains covering both half-sites. Belt-and-suspenders: the
  set tells you the *intended* outcome, the strand-graph walk proves it happened.
- **A deliberately-incomplete state legitimately FAILS `validate_design` — gate it by the expected outcome.** A
  recorded-but-unligated crossover sits at a strand terminus the validator flags as non-physical ("Nick the
  strand to ligate") — that's the route's *intended* partial-success state, not a bug. So the `validate_design`
  gate in `assert_crossover_joins` runs for `expect_ligated=True` only. When an oracle has a "partial success"
  branch, don't apply the well-formedness gate to it.

### Banked from AF-32 (forced-ligation place/delete)
- **The coverage-count meta-test is in THREE files, not one — `rg` the count before committing.** The handoff
  warns (AF-1 lesson) that flipping a route invalidates the "this count" meta-tests, but it only named
  `test_oxdna_coverage_report_separate`. Bumping 45→47 there left TWO more hard-coded `== 45` asserts red in the
  full suite (`test_cluster_obb.py::test_align_cluster_edge_adds_no_coverage`,
  `test_headless_spec_build.py::test_spec_build_adds_no_coverage`) — both "this feature adds NO coverage" pins that
  also assert the absolute total. **Every AF session that flips a route must `rg -n 'covered.*== *4[0-9]' tests/`
  and bump ALL of them**, not just the one the handoff cites. (Caught only by `just test`, not the targeted run.)
- **When the route derives a record's fields, the oracle should re-derive them the SAME way to catch a swap.**
  `force_ligate` takes two *strand ids*, but the `ForcedLigation` record stores `(helix, bp, direction)` endpoints
  the route computes (`strand_a.domains[-1]` / `strand_b.domains[0]`). `assert_forced_ligation` takes the `before`
  design + the same two ids and re-derives those endpoints itself, then asserts the stored record matches — so a
  route that swapped 3'/5' or read the wrong domain is caught. Re-deriving "the same way the route does" is NOT
  tautological here: the route's *input* is strand ids, its *output* is endpoints, and the oracle pins that the
  mapping is correct (mirrors AF-4's "wrapper takes the parameter, re-chews the payload" but for the read side).
- **A round-trip-persistence clause can't always be red-tested in isolation — exercise it positively.** Clause 5
  (FL record survives `.nadoc` round-trip) is load-bearing, but the record genuinely survives (it's a real model
  field) and stripping it to force a red makes the earlier clause-2 "record exists" fire first. So clause 5 is
  proven by the PASSING test (the oracle does a real round-trip + re-read internally) and the third red-test pins
  a *different* clause (clause 3, not-merged, by re-attaching the record to the un-merged strand graph). An oracle
  clause whose failure you can't manufacture cheaply is still worth keeping if a real bug (a dropped-on-export
  field) would trip it — just don't fake a red you can't honestly build.

### Banked from AF-30 (strand end-resize)
- **A backlog-prescribed "REUSE this oracle" can be subtly wrong — re-derive the surface before trusting it.** The
  AF-30 spec asserted `assert_inverse_pair` would be clean (`+δ` then `−δ` → `canonical_topology` unchanged) because
  "resize moves the bp-range so the forward-mutated guard fires honestly". The bp-range *does* restore — but
  `canonical_topology` ALSO fingerprints helix axis floats, and `resize_strand_ends` re-trims a helix's `axis_end` to
  `(max_index−min_index)·rise` while `create_bundle` uses `length_bp·rise` (one rise longer). So the FIRST resize off
  a raw bundle shifts the convention and never returns → the inverse pair fails on the axis, not the bp-range. Fix:
  capture `start` AFTER one settling resize so both ±δ runs share the re-trim convention. Lesson: the handoff's oracle
  recommendation is a hint, not a proof — run it before writing the test and let it tell you the real invariant.
- **Two builders disagreeing on a geometry convention is an ASK-FIRST finding, not a silent workaround.** The
  axis-endpoint off-by-one (logged ISSUE-13) is a real latent discrepancy (`create_bundle` vs `resize_strand_ends`/
  `shift_domains`); it's cosmetic — it shifts the axis-line *endpoint float* by one rise, NOT the nucleotide count
  (`length_bp` is unchanged; the resize's own count change is a separate, correct effect) — but it's a geometry
  convention, so per CLAUDE.md it goes to the user, not a reflexive `+1`. The test works around it explicitly +
  cites the ISSUE so the next session sees why.
- **The geometric length oracle only fires if the resized strand DEFINES the helix extent.** A helix's geometry
  count is `2·length_bp` where `length_bp` = the strand-coverage UNION span. In a 2hb bundle each helix carries a
  scaffold AND a staple both spanning the full length, so resizing one of them OUTWARD past the other grows the union
  (count moves); resizing INWARD (within the other's span) leaves the union — and the count — unchanged (the same
  blind-spot `design_renderer._scaffoldCoverageChanged` works around in the UI). Pick the fixture so the resized end
  is the one that sets the extent.

### Banked from AF-33 (hinge-primitive builder, P1)
- **A hand-built golden's own `feature_log` IS the build recipe — decode it, don't reverse-engineer the geometry.**
  The 2x2 hinge looked daunting (variable helix lengths 32/48/35, 14 strands, asymmetric bridge extensions). But the
  saved `.nadoc`'s feature log is a `SnapshotLogEntry` (`op_kind="bundle-create"`, `params` = the exact cells/length/
  flags) + a `RoutingClusterLogEntry` whose `children` are the literal `strand-end-resize` + `forced-ligation-create`
  minor entries with their params. Decoding those (the `params` dicts off the log entries) handed me the precise op
  sequence; replaying it through the shipped wrappers reproduced `canonical_topology` on the first try. For any
  "recreate this hand-built artifact" item, read its feature log FIRST — the GUI already recorded the recipe.
- **Replay the golden's op SEQUENCE verbatim, not an "equivalent" shortcut — axis floats are convention-bound.**
  The golden is at bp 8…39, reachable by `create(len=32, start=8)` OR `create(len=40) → resize every low end +8`. They
  are NOT topology-equal: AF-30's ISSUE-13 axis re-trim means the resize path leaves different `axis_end` floats, which
  `canonical_topology` fingerprints. The golden took the create-40-then-shift path, so the builder must too. Same lesson
  as AF-5 (sample-then-post) / AF-30 (settling resize): when an op has a history-dependent geometry side effect, fidelity
  means replaying the history, not landing the same nominal endpoint.
- **The gap-bridge geometry is hand-authored — replay it as a per-primitive constant, do NOT geometrically derive it.**
  The bridge trims are asymmetric (`scaf_1_0` 3p −3 vs `scaf_1_1` 5p −16) — they encode the physical span the scaffold
  must cross between leaves, a directionality/topology decision (`CLAUDE.md` ASK-FIRST). The *uniform* +8 duplex shift IS
  safe to derive mechanically (low-bp end per strand, read off live domain directions). Split the builder accordingly:
  derive what's mechanical, constant-encode what's hand-routed, and don't reason about the latter.
- **`canonical_topology` is blind to `forced_ligations` — the FL-endpoint-set is the 5th instance of that blind-spot.**
  After clusters (AF-16), loop/skips (AF-3), overhang-connections (AF-27 P1), and the FL-record (AF-32), AF-33 is the 5th
  off-strand-graph relation the topology fingerprint can't see. The golden-equality oracle MUST add `_fl_endpoint_set`
  equality or a builder that dropped/mis-wired a link passes clause 2. The reusable `_fl_endpoint_set` (order-independent,
  id-free) is now the canonical FL comparator.

### Banked from AF-33 P2 (2x4/2x6 hinges)
- **Before hand-encoding a golden's spec, check whether a parametric generator already reproduces it.** The 2x6 golden
  (`2x6_triple_hinge_link.nadoc`) turned out to have been *generated* by the existing `build_hinge(2,6)` (uniform LO-end
  FL geometry, NO bridge trims) — a one-line probe (`canonical_topology(build_hinge(2,6)) == golden` + `_fl_endpoint_set`
  equal) confirmed it before I wrote a single spec line. The 2x4 golden (older, hand-authored) does NOT match
  `build_hinge(2,4)` (it carries asymmetric hand trims the generator omits). So: probe the generator against each golden
  FIRST — it tells you which goldens need a verbatim hand-spec and which are already covered, and de-risks the whole edit
  before touching the module.
- **Per-bridge (trim→FL) ordering reproduces a golden's all-trims-then-all-FLs when each unit's strands are independent.**
  The golden's *Fine Routing* cluster did ALL trims, then ALL forced ligations; the `_HingeSpec` replay does them grouped
  per-column (trim then FL). These commute because each column's scaffold strands are disjoint — an FL merging col-c's
  strands never touches col-(c+1)'s, so the trim for a later column still addresses a live strand id. Verified by a probe
  (both candidate specs matched their goldens byte-for-byte) before editing. Don't assume op-order is free; prove the
  independence.

### Banked from AF-36 (end-to-end hinge generation + phase-paired routing + seek fidelity)
- **A hinge's cross-gap ssDNA connections come in phase-paired short/long, NOT uniform.** Two neighbouring rail helices
  carry OPPOSITE phase; the one whose gap-face backbone faces TOWARD the far leaf takes a SHORT (2nt) tether, the neighbour
  (facing AWAY) a LONG (16nt) one — it must extend ~1 helical turn to re-phase toward the partner. `_rail_faces_toward`
  (backbone radial · rail-pair chord at the duplex-edge bp) decides it; validated byte-for-byte vs the goldens. `build_hinge`
  now derives this per column (was uniform). ALL ssDNA on the leaf-A rail; leaf B blunt. Default magnitudes 2/16 are
  user-fixed (no design-intent to derive better).
- **When a golden contradicts a stated rule, SURFACE it — don't silently match.** The 2x2 golden was the INVERTED
  (mis-authored) case: its away-facing pair carried the SHORT connection while 2x4 (and the user's description) said
  toward→short. Measuring both goldens and flagging the discrepancy let the user catch + correct an authoring bug mid-session
  (after which `build_hinge(2,2)` reproduces the corrected golden byte-for-byte). Had I quietly tuned the rule to "match the
  golden", the bug would have propagated into the generator.
- **Feature-log SEEK was blind to cluster_joints + flexible marks/connections (a whole bug CLASS).** `_topology_substitute`
  (the seek snapshot restorer) swapped only strand-graph topology + overhangs, so joints, `flexible_segment_marks`, and the
  derived `flexible_connections` lived in BASE state → present at EVERY seek position incl. the empty state (a joint/mark
  placed late never disappeared scrubbing back). Same shape as the historical overhang-membership fix. Lesson: any persisted
  field that is set by a snapshot op with NO delta-replay path must be restored from the seek snapshot (membership from the
  snapshot, overlays from deltas) — joints/marks were two more instances. Each fix got a red-without-fix pin.
- **Commit a relax as a logged `cluster_op`, not the `flexible-relax` route, when the timeline must be seek-faithful.**
  The seek reconstructs cluster poses ONLY from `cluster_op` entries; a `flexible-relax` snapshot bakes the pose into base
  state (recoverable via the revert endpoint, but the slider can't toggle it). So `compute_relax_transforms` →
  `transform_cluster(..., log=True)` per moved cluster makes the relax a visible, seek-reversible move/rotate.
- **"Set the hinge angle to X°" = compose the fold onto the relaxed REST pose** (the relax leaves a few-degree tilt, so a
  naive "X° from rest" reads < X° between the arms). Solve the fold θ so the SIGNED dihedral about the hinge axis (between
  the arms' helical w-axes) == X — dihedral-about-the-axis is linear in θ, so it is exact. Place the joint BEFORE folding:
  rotation about its own axis leaves the hinge line invariant, so the joint's stored local axis stays correct.

## Difficulties ledger (genuinely-stuck items + why)

**2026-06-23 — Tier 6 physics is mock-validated, not engine-validated (the AF-24 gap).** Tier 6 (AF-18..AF-23)
ships complete CODE + ORACLES + live-engine PLUMBING, but the only real-engine confirmation is AF-21's
`test_run_live_field_real_oxpy_steers` (live `F0`/`dir` re-aim steers a real specimen — confirmed PASSING in 13s
this session). AF-19 (τ), AF-20 (|E|↔τ sweep), AF-23 (cross-design campaign) are pinned ONLY against hand-built
mock binaries (`mock_oxdna_field_traj`/`_sweep`/`_campaign`) whose τ/melt signatures are coded to satisfy the
oracle (campaign mock: `k=clamp((4.5−12·F0)·(540/N))`, melt at `F0≥0.4`). So the oracles prove their MEASUREMENT
code is correct given a right-shaped trajectory — NOT that the real engine produces alignment-τ, the τ↓-as-|E|↑
law, a non-destructive window, or distinguishable per-design τ (the user's actual goal). **Why it stayed open:**
a meaningful real run needs a PROPERLY-relaxed duplex (short relaxations give bp_retained≈0, under-formed — see
`project_oxdna_efield`), i.e. real GPU runtime, deliberately deferred during the build loops. **De-risked this
session (so it's no longer stuck, just queued):** oxpy imports, the F0/dir binding patch is live, the binary
resolves at `/home/joshua/oxDNA/build/bin/oxDNA`, an RTX 2080 SUPER is present, and the real gated path RUNS not
skips. → **Diverted to AF-24** (real-engine gated validation, staged P1 τ → P2 sweep → P3 campaign/melt), now the
backlog's `▶ NEXT` ahead of the AF-12/13 stragglers. Each AF-24 phase reuses an EXISTING asserter unchanged and
ships no wrapper (coverage FLAT 37) — the augment is the real-engine gated test that retires the mock-only caveat.

**2026-06-23 (later) — AF-24 ROOT-CAUSED + the fix is known: the automation ran a MOCK-TUNED relaxation (10⁴× too
few steps) on the real engine, so the duplex never RE-ANNEALED.** NOT the field oracle, NOT the retention metric,
NOT the export, and NOT a "relaxation melts" artifact (an earlier draft of this entry concluded that — it was WRONG,
corrected below). User domain insight cracked it: *oxDNA drops base-pairing initially, then re-anneals over the long
md_relax stage.* Investigated on CUDA (RTX 2080 SUPER) with oxDNA's OWN `HBList` (`oxdna_interface.count_hbonds` →
`DNAnalysis`) as ground truth. Findings:
- **The oxDNA EXPORT is flawless** (still true): at t=0, HBList = **42/42**; every pair COM–COM 1.05 nm, base-site
  0.37 nm, `a1·a1 = a3·a3 = −1.00`; backbone bonds 0.785 units (FENE eq. 0.7564). Export geometry is correct.
- **`base_pair_retention` is SOUND** (still true): tracks oxDNA's energy-based HBList (the "diagnose metric first"
  call — answered, not a metric bug).
- **THE BUG — mock-tuned step counts reached the real engine.** `headless_oxdna_build.create_job` defaults to
  **mc=100 / md_relax=100 / equil=100**, `min_bp_retained=0.0`, `max_relax_retries=0` — EXPLICITLY tuned for the
  identity mock (its docstring says a real run "should raise [the gate] back to ~0.5" and "pass a positive [retry]
  budget"). The STANDARD relax (`oxdna_protocol` / `routes_oxdna` defaults) is **mc=1000 / md_relax=1_000_000 /
  equil=100_000**. The AF Tier-6 builders (`build_field_specimen`/`run_field`) + every probe inherited the mock
  defaults → gave the real engine 10⁴× too few md_relax steps → it dropped pairing and never had time to re-anneal.
  My "melts monotonically with steps (100→40 … 50000→0)" sweep was an artifact of scaling ALL stages to small EQUAL
  counts — it truncates before the re-anneal AND over-runs a trap-free equil; it never ran the real protocol.
- **PROOF the protocol is correct (user's working case `workspace/test343.nadoc`, a 42 bp duplex + 7 nt overhang
  anchor, headless STANDARD relax mc=1000/md=1e6/equil=1e5, 217 s on GPU):** HBList **mc 35 → md 39 → equil 42/42**.
  It DROPS then RE-ANNEALS to a perfect 42/42, and `3_equil` (mutual traps OFF) HOLDS 42/42 → the annealed structure
  SELF-SUSTAINS. Exactly the user's description; the protocol works.
- **Secondary (separate) issue:** the bare `make_minimal_design(1 helix, 42 bp)` duplex CRASHES at md=1e6 with an
  oxDNA cell-list overflow (`a cell contains more than _max_n_per_cell (42)` — "box too large for the simulation":
  `box_nm_for_positions` gives a sparse 50 nm box, and `render_stage_input` doesn't set `cells_auto_optimisation =
  false` / `max_density_multiplier`). test343 (a real app design) relaxes fine, so use a real-design fixture; OR add
  those cell keys for sparse small systems. Not the main blocker.
- **`write_mutual_traps` docstring is WRONG** (claims backbones start ~1.9 nm apart / unformed; reality 1.05 nm,
  fully bonded) — fix when touched.
- **THE FIX (now well-understood, NOT ASK-FIRST — just use documented standard params; no topology reasoning):**
  the AF Tier-6 real-engine path must run a STANDARD-grade relaxation (mc≈1000, md_relax≈1e6, equil≈1e5,
  `min_bp_retained≈0.5`, `max_relax_retries>0`) on a real-design fixture (test343-style), NOT the mock defaults.
  Then build AF-24 P1 (gated real test) on that: the annealed 42/42 specimen → field stage → `assert_equilibration_
  timeline`. The field stage is unbiased MD, but the equil result shows the annealed duplex self-sustains, so it
  should hold pairing under a field (the remaining empirical check is τ_align < τ_melt — now likely fine). Repro:
  scratchpad `af24_standard.py` (test343 standard relax), `af24_duplex.py`, the t=0 HBList/orientation probes.
- **Status — AF-24 P1 SHIPPED 2026-06-23.** The fix landed: `headless_oxdna_build.STANDARD_RELAX_PARAMS`
  (mc=1000 / md_relax=1e6 / equil=1e5 / `min_bp_retained=0.5` / `max_relax_retries=3`) — a REAL Tier-6 specimen
  build passes `**STANDARD_RELAX_PARAMS` explicitly (the mock-tuned `build_field_specimen` defaults stay the default
  so the GPU-free mock suite — whose mock cost scales with step count — stays fast). The gated test
  `test_field_specimen_reanneals_and_equilibrates_real_engine` (opt-in `NADOC_RUN_OXDNA_SLOW=1`; `@pytest.mark.slow`)
  builds `tests/fixtures/test343.nadoc`, asserts re-anneal (retention ≥ 0.9), runs an anchored field (pN=2, 20k
  steps), and reuses `assert_equilibration_timeline` UNCHANGED → **PASSED on real CUDA, 252 s** (converged + finite
  τ + not melted; τ_align < τ_melt confirmed). The `write_mutual_traps` docstring was corrected. Remaining: AF-24
  P2 (real |E|↔τ sweep) + P3 (real cross-design campaign) — same pattern, slower (multi-cell). See
  `project_oxdna_relaxation`.

---

## Ledger audit log

**2026-06-25 — context-bloat split (ledger-only, no code).** The per-loop read had ballooned: the backlog's
`## Next-session handoff` (contracted to ≤8 lines, overwrite-each-session) had instead grown to ~895 lines as
sessions *appended* 33 `▶ HARNESS NOW AVAILABLE` "do-not-rebuild" blocks; and `design_automation_log.md` had
reached 276 KB — over the 256 KB file-read cap, i.e. *unreadable in one pass* by the tool the protocol tells a
cold session to read. **Fix (four-file layout):** (a) extracted the per-item **metrics rows + data summaries**
(1758 lines) → new `design_automation_metrics.md`; (b) moved the 33 harness blocks + the historical handoff
narrative → new `design_automation_harness.md` (with a compact one-line **index** of shipped wrappers); (c)
restored the backlog handoff to ≤8 lines. Nothing deleted — everything moved verbatim. Updated the protocol
(steps 1+8), the skill, and the MEMORY index to point at the new layout and forbid re-appending to the handoff.
Per-loop read now = `backlog` (protocol + ≤8-line handoff + ranked items) + `log` (oracle catalog + lessons +
difficulties); `harness`/`metrics` are opened on demand per-item only. AF-24 P1 / AF-25 / AF-26 confirmed
shipped + committed; stale duplicate Tier-7 "original intake" checkboxes flipped to truthful `[x]`.

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

---

## 2026-06-25 — crossover extra bases: simulate + validate + render (end-to-end)

Extra bases at crossovers (`Crossover.extra_bases`, e.g. "TT" — single-stranded thymines) were design
metadata that reached only the atomistic/GROMACS path; the **oxDNA CG** model ignored them and the renderer
drew them on a geometric Bézier arc, not the real conformation. This session wired them through both, with
validation. Durable details in `memory/project_oxdna_extra_bases.md`.

- **oxDNA wiring** (`backend/physics/oxdna_interface.py`): extra bases now materialize as ssDNA particles
  `("__xb__", crossover_id, k)` in the topology+configuration via one shared strand-walk generator
  (`_walk_strand_nucleotides`) + `crossover_extra_base_junctions` + `_resolve_extra_base_geometry`, threaded
  through all 7 walk consumers. **Gotcha (banked):** the relaxation health check's `backbone_bond_pairs` must
  thread the inserts or it measures a phantom `prev→next` bond across the widened gap → spurious FENE
  over-stretch → relaxation falsely fails after 3 escalations.
- **Validation**: `tests/test_oxdna_extra_bases.py` (unit pins + `assert_extra_bases_in_oxdna` oracle, can-go-red),
  `tests/test_oxdna_extra_base_production.py` (real-CUDA, `@pytest.mark.slow`, `NADOC_RUN_OXDNA_SLOW=1`) — 6hb
  and 18hb × {one crossover, all crossovers} all reached `completed` relax + 5M-step production. Surfaced + fixed
  a real `wait_for_terminal` relax→append race (terminal-on-disk before the runner deregisters) that bites any
  headless automation chaining relax→production.
- **Rendering** (real simulated positions, not the arc): Phase 1 CG beads/slabs (`design_renderer.js`
  `partitionExtraBaseUpdates` routes `__xb__` updates to the bead instances; live Playwright e2e); Phase 0 Atom
  `crossover_id`/`extra_base_k` identity; Phase 2 atomistic + surface heavy reps (`xb_pos_override` threaded into
  `build_atomistic_model`; **skip the scipy bridge minimisation when sim positions are present** or it re-seats
  the insert onto the design arc); Phase 3 MD CG trajectory (unique `__xb__` P-atom keys via shared
  `md_pkey`/`md_rigid_reference` in `atomistic_to_nadoc.py`). **Gotcha (banked):** the live MD display ws handler
  (`backend/api/ws.py`) had a DUPLICATE copy of the rigid-mask `bp_index >= 0` compare that crashed on the
  string `crossover_id` (`Display failed` after the seed frame) — now both copies route through the shared
  helper so the `__xb__` handling can't drift.
