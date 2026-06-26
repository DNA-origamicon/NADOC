---
name: project_headless_build
description: Mouse-free programmatic bundle/extrude construction API (seed for AI-driven design) + the test-design builders that use it
metadata: 
  node_type: memory
  type: project
  originSessionId: 88f75908-e5a2-4fbf-a999-f8f69e678526
---

# Headless construction — `backend/api/headless_build.py`

Programmatic, mouse-free design construction. The bundle/extrude **endpoints**
already are a "cells + length → bundle" API; this module is the in-process
surface over the same route handlers (`create_bundle`, `add_bundle_continuation`),
so scripted builds carry a real, replayable `feature_log` — indistinguishable
from a design built by clicking. Shipped 2026-06-09.

**Why:** path toward fully programmatic / AI-driven design (very-far-future goal
the user named). Also fixed an immediate gap: test designs built by calling the
core builders directly (`make_bundle_design`) had **empty feature logs**, because
the log is recorded one layer up by `state.mutate_with_feature_log`, which only
the route handlers wrap around the core builders.

**API:** `new_design` / `create_bundle` / `extrude` mirror the endpoints 1:1 on
the active doc; `build_bundle(cells, length_bp, *, lattice, passes=())` is a
one-shot **isolated** build (runs in a throwaway `doc_id` via `doc_context`,
dropped on exit — never disturbs the default session/undo). `passes`: int n →
`cells[:n]`, offset_nm = i×len×rise (the teeth pattern).

**Auto-op wrappers (2026-06-09):** scaffold routing, crossovers, staple
breaking, and overhangs — each a thin driver over the matching route handler,
returning the updated active design; chain them inside `scratch_session` exactly
as a person clicks. `auto_scaffold(seamless=False)`, `auto_crossover()`,
`auto_break(algorithm='basic')`, `auto_merge()`, `assign_scaffold_sequence(name)`,
`auto_break_aksel(**)`, `auto_route_aksel(**)`, `full_autostaple(name, **)`,
`overhang_extrude(helix_id, bp_index, ...)`. Handlers that fail raise
`fastapi.HTTPException` (catch like a status code). Composing
create_bundle→auto_scaffold→auto_crossover→auto_break at 388 bp reproduces a
fully-routed 18hb **deterministically**: `make_18hb_routed_design()` in conftest.

**Strand-edit wrappers (AF-2, 2026-06-16):** `nick(helix_id, bp_index, direction)`,
`ligate(helix_id, bp_index, direction)` (exact inverse — same `NickRequest` shape),
`delete_strand(strand_id)`. Each drives the real route handler (`add_nick` /
`ligate_strand` / `delete_strand`) and mutates the active doc; chain inside
`scratch_session`. Bad input → `HTTPException` (nick a 3′ terminus → 400; ligate
with no nick → 404).

**Loop/skip wrappers (AF-3, 2026-06-16):** `loop_skip(helix_id, bp_index, delta)`
(delta +1 loop / −1 skip / **0 removes** — the mark's own inverse) and
`apply_loop_skip_deformations()` (bake DeformationOps → marks; needs crossovers +
a deformation op, or a SQUARE design). Drive `insert_loop_skip` /
`apply_loop_skips_from_deformations`.

**Parametric circle wrapper (AF-4, 2026-06-17):** `circle_segment(radius_nm, *,
plane='XY', offset_nm=0, strand_filter, ligate_adjacent, min_chord_bp)` — takes the
**radius** (not the route's pre-computed `cells`+`cell_lengths`), runs the SAME
`circle_primitive.circle_footprint` analytic the JS preview mirrors, then drives
`add_circle_segment`. SQUARE-lattice (build in a SQUARE `scratch_session`). Raises
`ValueError` when the radius is below the min-chord floor (no helix qualifies).

**Deformed-continuation wrapper (AF-5, 2026-06-17):** `bundle_deformed_continuation(
cells, length_bp, *, source_bp, ref_helix_id=None, plane='XY')` — samples the deformed
frame (`get_deformed_frame`) then POSTs WITH `source_bp` so the route re-derives it
live (the replayable path). Drives `add_bundle_deformed_continuation`.

**Deformation wrappers (AF-6, 2026-06-17):** `add_bend(plane_a_bp, plane_b_bp, *,
curvature_deg_per_bp, direction_deg=0, affected_helix_ids=(), cluster_ids=())` and
`add_twist(plane_a_bp, plane_b_bp, *, total_degrees | degrees_per_nm, …)` (XOR — pass
exactly one twist spec or `ValueError`). Both drive `add_deformation`; bend/twist is a
geometric overlay (topology never bent). Magnitude pinned by `assert_deformation_angle`
(direction-agnostic — sign/frame is ASK-FIRST, deliberately not pinned).

**Cluster wrappers (AF-15 Phase 1, 2026-06-17; `log=` added AF-16, 2026-06-18):**
`add_cluster(name, helix_ids, *, domain_ids=(), log=False)` (drives `add_cluster` — creates
a named rigid-body cluster; only the default catch-all surrenders helices; `log=True` appends
a `cluster_create` feature-log entry — `ClusterCreateLogEntry`, mirrors `ClusterOpLogEntry` —
so a generated multi-bar part's grouping step is replayable; pin with
`assert_cluster_in_feature_log`, the load-bearing proof since `canonical_topology` is blind to
clusters; UI panel doesn't yet label this type → ISSUE-12) and
`transform_cluster(cluster_id, *, translation,
rotation, pivot, commit=True, log=False)` (drives `update_cluster`). The cluster pose is
a DISPLAY-layer rigid displacement applied by the geometry kernel
(`deformed_helix_axes` / `_apply_cluster_transforms_domain_aware`), NEVER a topology
edit (three-layer law). `canonical_topology` is BLIND to the pose (third overlay
blind-spot after loop/skip + deformation), so the load-bearing pin is the NEW geometric
`assert_cluster_translated` (below), not round-trip. First coverage gain since AF-9:
**32 → 34**. Rotation poses are ASK-FIRST (deferred to Phase 2's edge-alignment solver).

**Cluster OBB + edge alignment (AF-15 Phase 2, 2026-06-17):** NEW pure core
`backend/core/cluster_obb.py` — `cluster_obb(design, cluster_id) → OBB` (an
**equivariant** oriented bounding box of the cluster's posed helix axes; corners/edges
keyed `(axis, s1, s2)` via `OBB.edge_endpoints`/`corner`/`edges`) + the pure solver
`align_edge_transform(design, cluster_id, src_edge, *, target_edge|target_line) →
(quat, translation, pivot)`. Wrapper `hb.align_cluster_edge(cluster_id, src_edge, *,
target_edge=(other_cluster_id, edge_key) | target_line=(point, direction))` solves then
drives `transform_cluster` (wraps NO new route → coverage stays **34**). **Conventions
(user-fixed, NOT reasoned out): minimal rotation / auto-flip (≤90° onto ±target_dir) /
midpoint snap / roll free.** The OBB frame is **PCA-based, NOT
`deformation._initial_cross_section_frame`** (that snaps u/v to WORLD axes → not
equivariant → edge keys jump after a pose); sign anchor is **positional** (first sorted-id
helix with a clear u-projection), NOT a value-argmax (which ties on a rectangle's 4
symmetric corners → float-rounding flips the frame; the equivariance test catches this).
`cluster_obb` RAISES on a square footprint (ambiguous u/v) and < 2 helices → fixtures must
be **rectangular** (e.g. a 2×3 / 2×6 SQUARE grid). Pin: `assert_edges_collinear` (below) +
the equivariance test `test_obb_is_equivariant` (`OBB(g·design)=g·OBB(design)`). This module
is the shared foundation AF-14 (revolute-joint ROM) reuses. Tests: `tests/test_cluster_obb.py`.

**Validation harness — `tests/automation_harness.py`** (the design-automation
`/automate-feature` loop's shared oracle surface): `canonical_topology` (id/order-
independent fingerprint), `roundtrip_nadoc` + `assert_roundtrip_stable(build_fn)`
(build survives a real `.nadoc` save/load), `assert_inverse_pair(start, forward,
inverse)` (op∘inverse = topology-identity, with a "forward must mutate" guard),
`assert_geometric_length_delta(start, op, expected_bp_delta, *, helix_id=None,
strands_per_bp=2)` + `geometric_nucleotide_count(d, hid=None)` (AF-3 — geometry
kernel's nucleotide count changes by exactly the declared bp delta × 2 strands;
direction-agnostic so safe on bend/twist apply; per-`helix_id` = the strong bulk
check), `assert_circular_disc(design, requested_radius_nm, *, max_spread_nm=0.5,
radius_tol_nm=0.5, helix_ids=None)` (AF-4 — geometric oracle for disc primitives:
reads the *placed* helices' axis spans, asserts `circularity_spread < max_spread_nm`
+ `fit_radius` within tol of the requested R; pins the whole radius→geometry path),
`assert_on_deformed_frame(before, after, source_bp, cells, …)` (AF-5 — appended helices
land on the re-derived deformed frame AND are displaced > min from a straight extrude),
`assert_deformation_angle(design_after, plane_a_bp, plane_b_bp, expected_total_deg, *,
ref_helix_id=None, angle_tol_deg=1.0, step_bp=1, min_angle_deg=5.0)` (AF-6 — sums the
deformed frame's per-step relative-rotation magnitude → unwraps past 180°/360°; asserts
= κ·Δbp / total twist; direction-agnostic; covers both bend & twist),
`assert_cluster_translated(design_before, design_after, cluster_id, *, translation,
tol_nm=0.02, min_translation_nm=0.5)` (AF-15 — geometric pin for a cluster
rigid-TRANSLATION pose: reads posed helix axes via `deformed_helix_axes`, asserts the
cluster's helices shift by the exact vector AND only they move, `‖T‖>min` guard;
direction-agnostic, rotation poses out of scope = ASK-FIRST),
`assert_edges_collinear(design, cluster_id, src_edge, *, target_edge|target_line,
tol_nm=0.05, tol_deg=1.0, min_len_nm=0.5)` (AF-15 Phase 2 — geometric pin for the OBB
edge-alignment solver: recomputes the cluster OBB on the POSED design, asserts the named
src edge shares one line with the target — parallel/antiparallel direction AND on-line
endpoints; direction-agnostic, non-degeneracy guard),
`headless_coverage_report()` (route↔wrapper by function identity → the live
AF backlog, **34/239 covered after AF-15 Phase 1/2** — Phase 2 added a solver, no route; assembly relations gear/belt/polymerize
shipped via `headless_assembly_build.py`, bind_overhangs DEFERRED pending overhang-binding
rework). **Caveat: `canonical_topology` is blind to
loop/skips, deformations, AND cluster poses** (all live outside the strand graph) →
round-trip stability can't prove such an overlay persisted; a geometric oracle is what
does. See
`design_automation_backlog.md` / `design_automation_log.md`.

**How to apply:** to build a design in a test/script with full history, use
`headless_build.build_bundle(...)`, NOT the raw `backend.core.lattice` functions
(those skip the feature log + clustering). Tests: `tests/test_headless_build.py`.

## Test-design builders — `tests/conftest.py`

`make_teeth_design` / `make_6hb_design` / `make_18hb_design` /
`make_mini_hinge_base_design` + the general `build_extruded_bundle` (delegates to
`headless_build.build_bundle`). Cell layouts lifted verbatim from real designs'
feature logs (cited per constant) — never hand-derived (topology "ask first").

These rebuild common bundles from their own 6-op (teeth) / 1-op feature logs.
Replaces opening committed `.nadoc` blobs, killing the fixture-mutation
corruption surface. Pinned in `tests/test_section_router.py`:
`test_teeth_builder_matches_fixture` (canonical topology + identical
seamed/seamless routed output) and `test_18hb_builder_matches_fixture`. teeth
and 18hb have clean single-construction references; 6hb / mini_hinge-base do not
(real files carry extra routing/overhang ops), so they're construction-validated
+ visual only. mini_hinge here is the **base bundle only** (two 4×2 SQUARE
blocks → 2 clusters); the file's routing/flexible/overhang steps are not replayed.

Visual-validation tiles (gitignored scratch): `workspace/builder_tests/*.nadoc`
+ `builder_validation.png` (cross-sections + axial profiles). Regenerate from the
conftest makers.

## Overhang placement gate (2026-06-09)

The UI overhang tool only offers a placement where the staple end's **backbone
bead azimuthally faces** a vacant nearest-neighbour cell at that Z (radial
`dot ≥ 0.75` ≈ within 41°), per `frontend/src/scene/overhang_locations.js`. The
bead rotates with bp (helical phase), so a given bp can host an overhang only
toward the cell it faces. The raw extrude path historically enforced NONE of this
(only "a staple end exists here"), so direct-API / headless generation could
create overhangs at positions the UI would never allow (the 6hb_full_auto bug:
cells (0,0)/(1,4)/(−1,2) attached at bead-faces-away bps).

Fix: `overhang_candidate_error(design, orig_helix, bp, direction, nr, nc)` in
`backend/core/lattice.py` reproduces the UI predicate exactly (adjacency +
vacant-at-Z + dot≥0.75), computed on the **straight geometric layer** (NOT
deformed/physical). Enforced at the **endpoint layer** `_build_overhang_extrude`
(crud.py) → raises ValueError → HTTP 400, so UI / direct API / headless all gate;
the core `make_overhang_extrude` primitive stays **ungated** so geometry unit
tests (`test_overhang_geometry`) can probe arbitrary positions. The headless
`overhang_extrude` wrapper therefore raises `HTTPException` on a bad placement —
the generator catches it and skips. Tests:
`test_headless_build.py::test_overhang_extrude_{places_a_valid_candidate,rejects_a_non_candidate_placement}`.
**Nick-pair / end-cap occupancy bug (fixed 2026-06-09):** the cell-occupancy Z
check counted a helix's **axis** span, but a helix axis runs one base-rise past its
last nucleotide (the end-cap). For a short overhang that end-cap landed exactly on
the *adjacent* bp's Z, falsely suppressing the candidate one bp away (a nick-pair
sibling — e.g. placing an overhang at 1_2 bp55 killed the bp56 candidate). Fix:
occupancy uses the **nucleotide extent** `[axis_start.z, axis_end.z − one_rise]`,
via `_helix_nucleotide_z_band` (lattice.py) AND the frontend `cellZMap`
([overhang_locations.js:221]). `make_overhang_extrude` already shared the cell's
helix correctly for the second overhang (extends 8→16 bp, valid topology) — only
the gate was wrong. Regression: `test_adjacent_nick_overhangs_are_independently_placeable`.

`workspace/6hb_full_auto_test.nadoc` = the full demo: seamed scaffold + autostaple
+ **all** main-6hb overhang candidates filled (18 overhangs after the nick-pair fix;
was 14). Key insight: the gate
checks vacancy **at the staple end's Z**, and a short overhang occupies only a thin
Z-slice, so one lattice cell hosts MANY overhangs stacked along Z (the existing
helix is shared — cf. `test_two_overhangs_same_cell_share_helix`). "All candidate
locations" therefore means every (staple-end, facing-vacant-at-its-Z cell) pair, not
one-per-cell — a greedy loop that re-scans after each placement and stops when the
gate refuses all remaining mains (0 candidates left). Generator restricts the FROM
helix to the 6 ring cells so overhangs stem only from the main bundle, never from
overhang tips.

## Overhang test helpers consolidated (2026-06-09)

`conftest.valid_overhang_sites(design)` + `conftest.extrude_valid_overhang(design,
length_bp)` are the **single validated source of truth** for test overhang
placement — they enumerate staple-end × cell candidates and filter through
`overhang_candidate_error` (so test overhangs land exactly where the UI tool
offers). Replaced 3 bespoke enumerators that omitted the backbone-facing rule:
`test_sub_domains._extrude_overhang` (used by 11 tests across sub_domains /
subdomain_rotation / subdomain_boundary_hairpin) and
`test_overhang_sequence_resize._all_overhang_sites` now delegate. **Left
`test_overhang_geometry._all_overhang_sites` alone on purpose** — it tests the
ungated geometric PRIMITIVE at arbitrary positions (the facing filter would cut
coverage). New `test_headless_build.test_fill_all_overhang_candidates_saturates_and_stays_valid`
pins the fill-until-saturated behaviour (stacks >1 per cell, valid, 0 candidates left).

## Test-migration audit (2026-06-09) — what can/can't use the builders

`test_seamless_router.py::test_teeth_closing_zig` migrated teeth.nadoc →
`make_teeth_design()` (builder helix AND strand ids match the fixture exactly —
deterministic `h_XY_r_c` naming — so even id-referencing asserts are safe).

**Do NOT blindly swap the `workspace/18hb.nadoc` tests in `test_staple_scoring.py`
to `make_18hb_design()`** — that was a wrong recommendation from an automated
audit. `workspace/18hb.nadoc` is a FULLY ROUTED design (1 scaffold strand, 757
crossovers, sequences; feature_log = bundle-create→auto-scaffold-seamed→
auto-crossover→autobreak), NOT a bare bundle. The 4 skipping tests
(`test_score_workspace_18hb...`, `test_auto_break_aksel...`, `test_auto_route_aksel...`,
`test_full_autostaple_completes_on_18hb...`) need that routed input and assert
routing-specific outcomes (hardcoded 7188 nt scaffold / 6984 bound; or HTTP 422
"No complete legal breakpoint path"). A bare bundle invalidates all of them.
`test_precursor_graph_workspace_18hb...` was ALREADY migrated to the committed
bare `18hb_fixture.nadoc` (total_nt==388). `test_old_nadoc_loads_without_snapshot_entries`
deliberately wants an OLD no-feature-log file (`Examples/6hb_test.nadoc`, exists) —
the builder produces the opposite.

**Outcome of unblocking the 4 routed-18hb tests (done 2026-06-09):** with the
auto-op wrappers + `make_18hb_routed_design()`, 2 of the 4 migrated to run on CI
(no longer skip): `test_score_workspace_18hb...` (regen reproduces total_nt 7188 /
bound 6984 EXACTLY) and `test_full_autostaple_completes_on_18hb...` (structural
asserts hold). The 2 Aksel tests (`test_auto_break_aksel...`, `test_auto_route_aksel...`)
**stayed file-gated** — they assert the **422 "No complete legal breakpoint path"**
failure mode, which is a property of the bespoke workspace design; a clean regen
HAS a legal path and returns 200, so substituting it would destroy the regression.
Added `test_auto_route_aksel_succeeds_on_clean_18hb` as the positive (200)
complement. Lesson: structural/length-derived assertions survive regeneration;
design-specific *failure-mode* assertions do not — verify each individually, never
bulk-swap. Hinge3 / hingeV4 / mini_rect / 10hb-MD fixtures stay file-based (bespoke
or hand-routed).

Related: [[project_scaffold_router]], [[project_autoscaffold_single_strand]],
[[project_extrude_preview]].
