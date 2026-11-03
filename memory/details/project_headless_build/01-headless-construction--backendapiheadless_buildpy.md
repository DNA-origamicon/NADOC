# Headless construction — `backend/api/headless_build.py` — supporting detail

[Topic head](../../project_headless_build.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
