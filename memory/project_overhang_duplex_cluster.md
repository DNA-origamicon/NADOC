---
name: overhang-duplex-cluster
description: "PLAN ONLY (2026-07-01) — promote the overhang-duplex pose (currently an OverhangSpec.rotation/translation overlay + a bespoke orientation panel) into a first-class, sidebar-listed, gizmo-movable CLUSTER with a rotation-point dropdown (end A / end B / centroid) and flexible-region-style constrained movement for multivalent/multi-connection cases. Unifies overhang orientation edit + the just-shipped bridge relax into the cluster system."
metadata: 
  node_type: memory
  type: project
  originSessionId: f15e083b-6e16-4cf7-a87d-e75a3380eb1f
---

# Overhang Duplex as a Cluster — design plan (PLAN ONLY)

**Status:** planning; no code. Supersedes the standalone overhang orientation panel by
folding the duplex pose into the cluster move/rotate system. Related: [[overhang-duplex-foundation]]
(the Duplex graph + the shipped `direct_relax` bridge relax), [[cluster_joints]] (local-frame
joint storage precedent), [[ssdna_flexible_segments]] / [[ball_joint]] (the free-until-taut
constrained-drag model to reuse).

## Plain-language summary
Today, when you apply an overhang connection the duplex is placed by a hidden per-overhang
"pose" (a rotation + a shift stored on the overhang), and you edit its orientation through a
separate little panel. Users want the duplex to instead show up in the normal **movable-cluster
sidebar** and be dragged with the **same gizmo** as any rigid body — but with a dropdown to
pick what point it rotates around (either end of the duplex, or its middle), and with the
**same "slides until a tether goes tight" constrained motion** that flexible ssDNA regions
already give clusters. This lets multivalent/multi-connection duplexes still be nudged within
the play their bonds allow. The core realization: the duplex pose is *already* a cluster
transform under the hood — we're promoting it to a real one.

---

## 1. The key realization — it's already a (synthetic) cluster transform
`apply_overhang_rotation_if_needed` ([deformation.py:1040](backend/core/deformation.py))
builds a temporary `ClusterRigidTransform` every geometry pass:
- `helix_ids=[driver helix]`, `rotation=ovhg.rotation`, `translation=ovhg.translation`,
  `pivot=junction bead`, `domain_ids=[driver overhang domain, *partner_refs]`.
- `partner_refs` = `_overhang_binding_partner_refs` ([deformation.py:922](backend/core/deformation.py)):
  the relocated **driven tip**, LINKER complements, OH_BINDER strands, end-to-root binders.
- Applied via `_apply_cluster_transforms_domain_aware` — the SAME `p' = R(p−pivot)+pivot+t`
  ([deformation.py:752](backend/core/deformation.py)) used by real clusters.

So the duplex pose and a domain-level cluster are mathematically identical. The pose storage
(`OverhangSpec.rotation`/`.translation`/`.pivot`, [models.py:272](backend/core/models.py)) is a
per-overhang overlay; a cluster ([models.py:1054](backend/core/models.py)) is a first-class
sidebar entity with a gizmo, CRUD, feature-log, and the flexible-tether PBD. **The plan is to
move the pose from the overlay onto a cluster-shaped entity.**

## 2. THE CENTRAL DECISION — parent composition (needs user sign-off)
A duplex is not a free rigid body: the driver overhang domain lives on the driver part's helix
and must move **with the driver part** AND carry a **local** pose relative to it. Ordering today:
1. driver cluster transform is applied to the whole driver helix (incl. the overhang beads);
2. THEN the overhang overlay applies `R_oh` about the (already-cluster-moved) junction bead.

A **plain flat cluster** with `domain_ids` = the duplex domains does NOT compose — the
domain-aware path *replaces* the parent's transform on those domains ([deformation.py:650](backend/core/deformation.py)),
so the overhang would **detach** from the driver part (follow only the duplex cluster). Worse,
the overlay stores `R_oh` in the **world** frame, so even the current overlay drifts if the
driver part is rotated *after* the pose is set (latent bug, masked because relax recomputes the
pose each time). The correct model is a **CHILD transform stored in the driver's local frame**,
composed *after* the parent — exactly the pattern `ClusterJoint` already uses (local-frame axis,
world derived lazily; [[cluster_joints]]).

**Options:**
- **(A) Overlay-backed pseudo-cluster (fast MVP).** Keep the pose on `OverhangSpec`; just make
  the sidebar + gizmo treat it as a movable entry, writing `rotation`/`translation` via
  `PATCH /design/overhangs/rotations` ([crud.py:4877](backend/api/crud.py)). Composes-after-parent
  already (junction pivot read live). Cheapest, but: world-frame drift persists, and the flexible
  PBD (cluster-based) must be adapted to drive an overlay.
- **(B) Real CHILD cluster, local-frame (principled target).** New/extended `ClusterRigidTransform`
  with `parent_cluster_id` + local-frame rotation/translation, applied *after* the parent in
  `_apply_cluster_transforms_domain_aware`. Unifies sidebar/gizmo/PBD/feature-log; fixes the
  drift. Most work; touches the geometry core + the just-shipped relax.

**Recommendation:** target **(B)** (child cluster, local-frame) — it's the only model that makes
"it's a cluster" *true* rather than cosmetic, and it makes the constrained-drag reuse trivial
(the PBD already operates on clusters). Ship it phased, with **(A)** available as a fallback if
(B)'s core-geometry change proves too risky. **Confirm with the user before building.**

## 3. Rotation-point dropdown (end A / end B / centroid)
Maps directly onto the cluster `pivot` field ([models.py:1070](backend/core/models.py)) — the
gizmo already rotates about `pivot` and even supports rotating about an *arbitrary* origin while
keeping the pivot elsewhere (the joint-ring rebase math, [cluster_gizmo.js ~534-663](frontend/src/scene/cluster_gizmo.js)).
- Compute three candidate pivots from the duplex connecting beads (reuse `direct_relax._root_anchors`
  → `c_A`,`c_B`; centroid = `(c_A+c_B)/2` or the mean of duplex beads).
- On dropdown change: set `cluster.pivot` to the chosen bead and **rebase translation** to hold
  the duplex in place (`rebaseClusterTranslationForPivot`, [cluster_gizmo.js ~84-129](frontend/src/scene/cluster_gizmo.js)).
- Rotating about **end A** keeps A's root bond closed and swings B (and vice-versa); **centroid**
  swings both symmetrically. This is the interactive generalization of the shipped relax
  (`duplex_midpoint_placement` centers; the clash spin rotates about the root→root axis).
- Multivalent nuance: with >2 ends there is no single "end A/B" — offer per-partner end options
  or fall back to centroid + each partner's junction (see §7).

## 4. Constrained movement (reuse the flexible-region PBD)
Reuse `_projectSsdnaConstraints` ([cluster_gizmo.js:828](frontend/src/scene/cluster_gizmo.js)) and
its Python parity solver ([flexible_relax.py:49](backend/core/flexible_relax.py)): a free-until-taut
position-based-dynamics loop (6 iters/frame, torque-rotation + translation, skips slack tethers).
- **Tether source is different.** Flexible segments tether two clusters via a marked ssDNA run
  (`FlexibleConnection{cluster_a,cluster_b,anchor_a,anchor_b,contour_length_nm}`,
  [models.py:419](backend/core/models.py); derived in [flexible_segments.py:183](backend/core/flexible_segments.py)).
  For a duplex the tethers are the **connection backbone bonds**: `c_A ↔ P_A` (driver root),
  `c_B ↔ P_B` (driven root), one per applied duplex end. For MULTIVALENCY read them off the
  **Duplex graph** ([[overhang-duplex-foundation]]): every `Duplex` touching this overhang
  contributes a tether to its partner's anchor.
- **Contour = bond length (~0.67 nm), not a long ssDNA run.** A single connection's two ~0.67 nm
  bonds are nearly rigid → the only real play is **rotation about the root→root axis** (the exact
  DOF the shipped clash spin uses). Two+ non-collinear tethers (multivalent) pin more DOF. So the
  constrained drag naturally yields "rotate-about-the-bond-line, wobble-until-taut," which is the
  intended behavior. The PBD must be **re-validated for very short tethers** (it's tuned for
  multi-nm ssDNA; short stiff constraints can oscillate — see §8).
- Commit path mirrors flexible-relax: one atomic `mutate_with_feature_log` entry
  (`POST /design/flexible-relax` analog, [routes_flexible_segments.py:107](backend/api/routes_flexible_segments.py)),
  single undo.

## 5. Sidebar + gizmo integration
- **Sidebar** ([cluster_panel.js](frontend/src/ui/cluster_panel.js)): list duplex-clusters
  (auto-created on Apply — see §6) with a distinct kind/badge so they read as "duplex", not a
  user rigid body. Click → activate the standard gizmo. Add the rotation-point dropdown to the
  move/rotate panel ([move_rotate_panel.js](frontend/src/scene/move_rotate_panel.js), next to the
  existing ssDNA-constraint dropdown).
- **Gizmo** ([cluster_gizmo.js](frontend/src/scene/cluster_gizmo.js)): reuse translate/rotate +
  the constrained-drag mode. For model (B) the gizmo drives a child cluster directly; for (A) it
  drives the overlay (new commit branch → `PATCH /design/overhangs/rotations`).
- **Retire** the bespoke orientation panel ([overhang_orientation_panel.js](frontend/src/ui/overhang_orientation_panel.js))
  + its menu item once the cluster path covers rotate/reset (keep "Reset Orientation" as a
  cluster-transform reset).

## 6. Auto-creation, membership sync, migration
- **Auto-create on Apply.** `_cv_create_bound_binding` ([crud.py:7336](backend/api/crud.py)) and
  `duplex.relocate_duplex` ([core/duplex.py:279](backend/core/duplex.py)) already relocate the tip
  and stamp the pose; have them also create the duplex-cluster (`domain_ids` = the duplex domains
  from `_overhang_binding_partner_refs`). Delete/unbind (`revert_bind_topology`) removes it.
- **Membership reconciliation.** The duplex `domain_ids` change with topology (relocation, added
  binders, multivalency). Extend the cluster reconciler ([[cluster_reconcile]]) — or derive the
  duplex-cluster's `domain_ids` from the overhang/Duplex graph each rebuild rather than storing a
  static list (safer; mirrors how `_overhang_binding_partner_refs` is dynamic).
- **Migrate the shipped relax.** `direct_relax.relax_direct_binding` writes
  `OverhangSpec.rotation`/`.translation` today; under (B) it writes the duplex-cluster transform
  (arc-min still moves the *parent* clusters; re-seat + clash spin become the duplex-cluster's
  local pose). Keep the SAME three-step math; only the write target changes.
- **`_apply_ovhg_rotations_to_axes`** ([deformation.py:1808](backend/core/deformation.py)) must
  route through the cluster path too, or the axis line desyncs (this was a real bug in the relax
  work — the pivot-de-translation subtlety at [deformation.py ~1885](backend/core/deformation.py)).

## 7. Multivalency & the Duplex graph
The Proposal-B `Duplex` records are the natural source of truth: one overhang may appear in
several `Duplex` edges (multivalent) → several partners → several tethers. Implications:
- The "duplex" the user clusters may be **a set of duplexes** sharing the driver overhang. Decide
  whether one cluster covers all of them (longest-drives) or one per edge.
- Rotation-point "ends" are ambiguous with >2 anchors → default to centroid + expose each
  partner's junction as an option.
- Conflicting registers (mismatched multivalent geometry) can over-constrain the PBD → it will
  settle to least-violation (that's fine, but surface a warning like the existing zero-overlap
  duplex validator flag).

## 8. Anticipated issues / risks (ranked)
1. **Parent composition / local-frame (§2)** — THE decision. Flat cluster detaches the overhang;
   world-frame overlay drifts on parent rotation. Must pick child-cluster-local-frame or accept
   the overlay's drift. Everything else depends on this.
2. **Double-transform during migration.** If both the `OverhangSpec` overlay AND a duplex-cluster
   apply to the same domains, geometry doubles. Migration must move the pose (not copy) and gate
   `apply_overhang_rotation_if_needed` off for domains owned by a duplex-cluster.
3. **Short-tether PBD stability.** `_projectSsdnaConstraints` is tuned for multi-nm ssDNA (gain
   0.6, 6 iters, 0.25 rad/iter clamp). ~0.67 nm bonds are near-rigid → risk of oscillation /
   never-converging. Likely need a stiffer/clamped variant or an analytic 1-DOF (rotate-about-
   root-root-axis) fast path for the common monovalent case, falling back to PBD for multivalent.
4. **`domain_ids` drift.** The duplex domains are dynamic (relocation puts the driven tip on the
   driver helix; binders/toeholds extend past the OH range). A static `domain_ids` goes stale;
   prefer deriving it live from the overhang/Duplex graph.
5. **Cross-cluster tether.** The driven tip is on the DRIVER helix but its root (`P_B`) is on the
   DRIVEN part's helix/cluster — the tether spans two parent clusters. The PBD's anchor
   resolution must handle "duplex-cluster ↔ two different parent clusters," unlike flexible
   segments which tether exactly two clusters.
6. **Same-body & standalone cases.** Both overhangs on one rigid body → no relative DOF (drag is a
   no-op, matches the relax's `same_body`). Standalone single-domain driver (no root) → only one
   tether; `_root_anchors` returns `None` for that side (already handled in relax).
7. **Undo / feature-log unification.** Duplex pose edits currently log `OverhangRotationLogEntry`
   ([models.py:1243](backend/core/models.py)); cluster moves log `ClusterOpLogEntry`. Under (B)
   pick one (cluster op) and ensure revert/replay + the `feature_log_cursor` truncation still work.
8. **Assembly / cross-part connections.** Overhang connections can be cross-part in assemblies
   ([[assembly_overhang_bindings]]). A duplex-cluster in assembly context (part-clone instancing,
   shared renderer) is a separate rendering/ownership problem — likely defer to a later phase.
9. **Rendering.** Duplex-cluster hull/gizmo, and the linker-bridge/duplex cylinder rep already
   have bespoke paths ([[overhang_connections]]); ensure the cluster hull doesn't double-draw.
10. **Live-preview parity.** The orientation panel's client-side preview mirrors the server
    (`ovhgDomainIds`+`ovhgBinderDomainIds`, [design_queries.js:30](frontend/src/scene/design_queries.js));
    the cluster gizmo's live paint uses `captureClusterBase`/`applyClusterTransform`. Unify so the
    preview still matches server geometry exactly.
11. **Pivot recompute on topology change.** If the duplex length/register changes (cadnano drag,
    sequence edit), the end/centroid pivots move; rebase or the gizmo origin drifts.

## Decisions (user, 2026-07-01)
(1) **Option B** — child-cluster, local-frame. (2) **Auto-create on Apply** with a toast
("Cluster X made from overhangs"). (3) Constrained drag = **translational wobble-until-taut**,
consistent with the ssDNA taut model. (4) **One cluster covers ALL duplexes** on the overhang;
the rotation-point dropdown offers **each participating overhang's ROOT bead** (+ centroid) — a
monovalent duplex → 2 root beads + centroid, a trivalent → 3 + centroid. (5) **Replace** the
orientation panel outright.

## 9. Phased build
- **P0 — model + composition. ✅ DONE 2026-07-01.** `ClusterRigidTransform.parent_cluster_id`
  ([models.py:1080](backend/core/models.py)); `_apply_cluster_transforms_domain_aware`
  ([deformation.py:650](backend/core/deformation.py)) now applies CHILD clusters FIRST (inner,
  rest-frame, masked to their domains) then the parent on top → child domains end at
  `T_parent(T_child(p_rest))`. **Behaviour-neutral** (no child clusters ⇒ identical path; the
  legacy domain-level overwrite is the OUTER order `T_child(T_parent)`, distinct from the child
  INNER order — proven). Pins: [test_child_cluster_composition.py](tests/test_child_cluster_composition.py)
  (compose / parent-carries-child-drift-free / child-moves-only-its-domains / behaviour-neutral).
  `just test` green. **Deferred to P1:** the helix-AXIS path (`_apply_cluster_transforms_to_point`
  / `_apply_ovhg_rotations_to_axes`) still needs child-aware composition for a partial-helix child;
  a light validator (parent must exist, child must be domain-level, no cycles).
- **P1a — pose-migration PRIMITIVES + validation + automation + mark-for-deletion.
  ✅ DONE 2026-07-01.** The risky core (the frame conjugation) is built and PROVEN
  geometry-neutral, ahead of any wiring:
  - `ClusterRigidTransform.overhang_duplex_driver_id` marker ([models.py](backend/core/models.py)).
  - [core/duplex_cluster.py](backend/core/duplex_cluster.py): `conjugate_world_pose_into_parent_rest`
    (`T_child = T_P^{-1}·T_W·T_P`, closed form), `materialize_duplex_cluster` (move the driver
    OverhangSpec pose → child cluster covering the duplex domains, CLEAR the spec pose;
    idempotent), `dematerialize_duplex_cluster` (inverse), `duplex_cluster_for`. **pivot_world
    must be read from a pose-CLEARED copy** (else the overlay's own translation shifts it —
    the bug the parity test caught).
  - Validation ([validator.py](backend/core/validator.py)): child parent exists + is
    domain-level + no cycle; a duplex cluster whose driver still carries a non-identity
    OverhangSpec pose is flagged (double-transform guard).
  - Automation: headless `hb.materialize_duplex_cluster` ([headless_build.py](backend/api/headless_build.py))
    + oracle `assert_duplex_cluster_materialized` (geometry-neutral + pose-moved + topology
    unchanged, [automation_harness.py](tests/automation_harness.py)).
  - Delete-on-completion ledger entry added ([project_tech_debt.md](memory/project_tech_debt.md)).
  - Tests: [test_duplex_cluster_parity.py](tests/test_duplex_cluster_parity.py) (conjugation
    parity w/ non-identity parent, materialize geometry-neutral + idempotent + round-trip,
    headless+oracle, validator red-tests). `just test` green.
- **P1b — geometry-source switch. IN PROGRESS.**
  - **DONE 2026-07-01 — per-domain SEGMENT axis composes the child inside the parent.**
    `deformed_helix_axes` orders `clusters_with_keys` child-first;
    `_apply_cluster_transforms_to_point` EXCLUDES duplex children (`overhang_duplex_driver_id`)
    from the whole-helix centre-line (partial coverage → the segment path handles them). The
    duplex domain segment now follows `T_parent(T_child(rest))`. Behaviour-neutral (no duplex
    clusters ⇒ unchanged). Pin: `test_duplex_cluster_segment_axis_follows_child_composition`.
    `just test` green (763 in the cluster/deform slice, no regressions).
  - **BLOCKER found (needs the running app):** the DESIGN view draws the overhang SHAFT from
    `ovhg_axes` ([helix_renderer.js:583/1356](frontend/src/scene/helix_renderer.js)), which is
    driven by the (now-cleared) OverhangSpec overlay in `_apply_ovhg_rotations_to_axes` — so
    clearing the pose desyncs the shaft (the exact axis bug that burned before). Sourcing
    `ovhg_axes` from the child-aware `segments` collides with segment DEDUP: driver overhang +
    relocated driven tip share ONE bp range → `_segments_for_helix` keeps a single stick, but
    the frontend wants one `ovhg_axes` entry PER overhang id. Resolving this (per-overhang
    ovhg_axes sourced from the child segment, or a frontend switch to `segments` for
    cluster-backed overhangs) is a VISUAL change → must be verified in the running app, so it's
    NOT landed blind.
  - **DONE 2026-07-01 — `ovhg_axes` shaft-follow.** For a cluster's DRIVER overhang (whose
    OverhangSpec pose was cleared), `_apply_ovhg_rotations_to_axes` sources `ovhg_axes` from the
    child-aware `segments` entry (`_overhang_is_duplex_cluster_driver`). The driven/partner
    overhangs keep their (identity) overlay entry — matching the pre-cluster behavior and
    dodging the segment-dedup collision (driver + relocated tip share one bp range → one stick).
  - **DONE 2026-07-01 — geometry-source switch WIRED + verified on the live server.**
    * Apply auto-creates the child cluster (`_cv_create_bound_binding` → `materialize_duplex_cluster`).
    * `relax_direct_binding` wraps the (unchanged) solver with dematerialize→relax→re-materialize
      so its geometry reads stay consistent and the result lands back on the cluster.
    * `revert_bind_topology` drops the duplex cluster on unbind/teardown.
    * Migration-on-load: `_materialize_duplex_clusters_on_load` on `/design/load` + `/design/import`.
    * **VERIFIED against the running app on `workspace/2x2_OH_test.nadoc`:** load → `Duplex 1`
      cluster (driver pose, parent = part cluster, 2 domains); server geometry **bit-identical**
      to the overlay (max overhang-bead delta 0.0 nm); relax updates the cluster pose, driver
      OverhangSpec stays identity, `validate_design` = 0 failures. Frozen-fixture parity pin:
      `test_real_fixture_materialize_is_bead_and_shaft_neutral`. Direct/relax tests updated to
      assert the cluster pose (not OverhangSpec). `just test` green.
  - **FOLLOW-UPS DONE 2026-07-01:**
    (a) **Different-length path** — `relocate_duplex` ([core/duplex.py](backend/core/duplex.py))
    now midpoint-places + `materialize_duplex_cluster`, same as the binding path; revert drops
    the cluster via the shared `revert_bind_topology`.
    (b) **Toast** — `_onApply` ([overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js))
    diffs cluster ids across apply and `showToast("Cluster X made from overhangs")` when a new
    `overhang_duplex_driver_id` cluster appears. **NOT hand-driven** (the click gesture);
    logic is a simple id-diff.
    (c) **Feature-log seek** — a cluster-backed relax now logs a `ClusterOpLogEntry` for the
    DUPLEX cluster (source `relax:duplex-cluster`, STABLE id reused across relaxes via
    `materialize_duplex_cluster(..., cluster_id=)`) and NOT an `OverhangRotationLogEntry`, so
    `_seek_feature_log` reconstructs the cluster pose instead of double-transforming the cleared
    OverhangSpec. Pin: `test_relax_logs_cluster_op_not_overhang_rotation_for_cluster_backed`.
    Verified headlessly on `2x2_OH_test` (1 `relax:duplex-cluster` op, 0 `overhang_rotation`,
    stable id). **The running server needs a RESTART** to pick up the latest `direct_relax.py`
    (uvicorn --reload held a stale copy). `just test` = 3454 passed (only the pre-existing
    `test_build_2x6_matches_golden` golden-drift fails).
- **P1c — Sidebar visibility. DONE 2026-07-01.** [cluster_panel.js](frontend/src/ui/cluster_panel.js)
  renders a `⛓` tag on any cluster with `overhang_duplex_driver_id`; the standard gizmo already
  attaches to it.
- **P2 — Gizmo + rotation-point dropdown. DONE 2026-07-01.** Manipulate via the standard gizmo; the
  Move/Rotate pivot dropdown offers each participating overhang's ROOT bead + the centroid (user
  decision 4), with a translation rebase so the geometry doesn't jump.
  - **Backend.** `duplex_cluster_rotation_points(design, cluster)` returns `[OH1 root, OH2 root,
    Centroid]` (each `{kind, overhang_id, label, point}`); `set_duplex_cluster_pivot(design, id, p)`
    rebases `t' = t + (R−I)@(p−old_pivot)`. Endpoints `GET /design/cluster/{id}/rotation-points`
    + `POST /design/cluster/{id}/rotation-point` in [routes_clusters.py](backend/api/routes_clusters.py)
    (404 unless it's a duplex cluster; 422 on unknown point; pushes undo). Pins:
    `test_duplex_cluster_rotation_point.py` (3).
  - **Frontend.** `api.setClusterRotationPoint` + `api.getClusterRotationPoints` (doc-aware GET)
    ([client.js](frontend/src/api/client.js)); [move_rotate_panel.js](frontend/src/scene/move_rotate_panel.js)
    adds `dup:root:{oid}` options (`_mrSetPivotOptions` reads the active cluster's driver+driven overhang)
    and an async pivot-change handler → `setClusterRotationPoint` → `clusterGizmo.clearPendingTransform`
    → `attach`; centroid routes through the same path for a duplex cluster. Wired at all 3
    `_mrSetPivotOptions(joints, id)` call sites in [main.js](frontend/src/main.js) + the
    `setClusterRotationPoint` dep.
  - **BUG (found in hand-test 2026-07-01, FIXED): the dropdown reverted to Centroid + the pivot always
    snapped to the centroid.** Two independent causes, both in `_setDuplexRotationPoint`:
    1. It called `refreshClusterPivotForAttach`, which recomputes the pivot from the cluster's VISUAL
       CENTROID and queues it as a pending gizmo transform — silently overriding the just-set root pivot
       (the "always rotates about centroid" half). Fix: drop that call; `clearPendingTransform` + attach
       so the gizmo reads the server-set pivot verbatim.
    2. `clusterGizmo.attach()` does `detach()` (→ `activeClusterId:null`) then re-sets it → that
       activeClusterId change fires main.js's activeClusterId subscriber (`main.js:~6281`) which
       hardcodes the pivot `<select>` back to `centroid` (the "dropdown reverts" half). Fix: re-assert
       the intended option after attach (`_mrPivotSel.value = dup:root:{oid}` / `centroid`).
    (A secondary `_mrSetPivotOptions` preserve-selection guard handles the joints-subscriber rebuild.)
  - **Pins.** `move_rotate_panel.test.js` (+4 cases incl. preserve-selection + "holds root, clears
    centroid pending, no refreshPivot"); **e2e** `duplex_rotation_point.spec.js` — the honest
    reproduction: loads `workspace/2x2_OH_test.nadoc`, activates design Move/Rotate on the duplex
    cluster (new hooks `__nadocTest.activateDesignMoveTool`/`getMoveRotatePivotState`), selects a root
    via the REAL `<select>`, asserts the dropdown HOLDS it + `cluster.pivot` lands on the root bead, then
    switches to centroid and asserts a distinct pivot. Proven pin (reverting either fix → e2e fails
    "Received: centroid"). 1861 frontend vitest green.
  - **VERIFIED on the live server** (`2x2_OH_test`, `Duplex 1`): GET → OH1 root / OH2 root / Centroid;
    POST OH1 root → pivot set, overhang beads **byte-identical** before/after, `validate_design` passed;
    e2e drives the full dropdown→pivot round-trip green.
  - **KNOWN minor UX gap (not the reported bug):** on activation the dropdown shows "Centroid" but the
    materialized cluster's actual pivot may already be a root bead — the displayed default doesn't read
    back the real pivot. Cosmetic; deferred.
  - **FOLLOW-UP BUG (found + fixed 2026-07-01, selection-driven Move/Rotate + 45° buttons work):** the
    NEW numeric quick-rotate (+45°/Reset/typed fields) TELEPORTED a duplex to a distant location, and
    Cancel didn't restore it. Root cause: the gizmo pivot (set by `_refreshClusterPivotForAttach` to the
    world visual centroid) and the panel NUMBER BOXES (populated from the STORED translation, relative to
    the stored pivot) disagreed. For a normal cluster stored-pivot≈centroid so the mismatch is ~0; for a
    duplex it was large → `setTransform([storedT], q)` set `dummy = centroid + storedT` = teleport. Cancel
    skipped restore because `setTransform` never marked the tool dirty (only drag did, via `onTransformUpdate`).
    **Fix (the two that WORKED):** (a) the field-population sites (tool `activate` + the activeClusterId
    subscriber, [main.js](frontend/src/main.js)) read `clusterGizmo.getPendingTransform(id) ?? stored` so the
    boxes match the gizmo's actual pivot (no-op for normal clusters); (b) `setTransform`
    ([cluster_gizmo.js](frontend/src/scene/cluster_gizmo.js)) now calls `onTransformUpdate` → marks dirty +
    re-syncs fields, so Cancel restores.
  - **DEAD END (do not retry): skipping `_refreshClusterPivotForAttach` for duplex clusters.** I first also
    early-returned that helper for `overhang_duplex_driver_id` clusters, thinking the stored pivot was the
    "real" rotation point. WRONG — a duplex is a CHILD cluster; its stored `rotation/translation/pivot=[0,0,0]`
    are in the PARENT-REST frame, NOT world. The gizmo places its handles at world `pivot+translation`, so the
    skip put the gizmo at `[0,0,0]+childframeT` = a distant location off the structure (the "gizmo appears far
    away" report). `_refreshClusterPivotForAttach` computing the WORLD visual centroid + rebasing is exactly
    what gives the gizmo a correct world pivot. **Keep it running for duplex clusters.** (Classic "reasoned
    about the duplex frame and got it wrong" — the CLAUDE.md warning.)
  - **KEY geometry fact for this gizmo:** the EFFECTIVE rotation center is `gizmoPos = pivot + translation`
    (where the handles render), NOT the internal `_pivot`. Backend applies `q = R·(p−pivot)+pivot+T`, so
    `|q − (pivot+T)| = |p−pivot|` is constant under R → the cloud rotates about `pivot+T`. Measured on
    `2x2_OH_test` `Duplex 1`: centroid pivot → gizmo exactly on the bead centroid (0.000 nm), +45 spins in
    place; OH1-root pivot → gizmo 0.73 nm from the root bead, +45 swings the far end; both are clean rotations
    (0.000 nm radius error) with no teleport. Pin: **e2e `duplex_gizmo_pivot.spec.js`** (dev hooks
    `__nadocTest.getClusterGizmoState` + `clusterGizmo.getGizmoWorldPosition`). Frontend pins:
    `translate_rotate_tool.test.js` (+2 fields-from-pending). **NOT hand-driven:** the actual WebGL ring-drag
    spin (MV-MRSEL(i) / MV-DUPPIVOT).
  - **NOT hand-driven:** only the actual gizmo-RING drag spinning the duplex about the chosen point on
    the WebGL canvas remains human-eye (the dropdown-hold + pivot-move is now e2e-covered). MV-DUPPIVOT.
- **P3 — Constrained (taut-bond) movement. MECHANISM DONE 2026-07-01 (drag stability = human-eye).**
  Reuses the gizmo's existing ssDNA free-until-taut projector (`setConstraint('ssdna', payload)` +
  `_projectSsdnaConstraints`) — NO new solver — fed with the duplex's connection-bond tethers instead
  of flexible-segment tethers. Decision (3): translational wobble-until-taut, consistent with the
  ssDNA taut model.
  - **Backend.** `duplex_cluster_tethers(design, cluster)` ([duplex_cluster.py](backend/core/duplex_cluster.py)):
    each participating overhang's applied connection = one backbone bond — MOVING end = the duplex
    connecting bead `c` (on the duplex helix → rides the child cluster), FIXED end = the embedded-staple
    ROOT bead `P` (on the parent part), `contour_nm = 0.67` (one bond). Reuses `_find_driven_tip_and_root`;
    standalone/never-applied side contributes no tether; multivalency → more tethers as more overhangs
    participate. `GET /design/cluster/{id}/duplex-tethers` ([routes_clusters.py](backend/api/routes_clusters.py),
    404 unless duplex cluster). Pins: `test_duplex_cluster_tethers.py` (3 — two bond tethers, anchors
    resolve to real beads, moving-on-duplex-helix / fixed-off-it). Live-verified on `2x2_OH_test`.
  - **Frontend.** `api.getClusterDuplexTethers` ([client.js](frontend/src/api/client.js));
    `flexRelax.buildDuplexTautPayload(clusterId)` ([flex_relax.js](frontend/src/scene/flex_relax.js))
    fetches tethers → `{connections:[{movingKey,fixedKey,contour}], resolveWorldPos}` (same shape the
    ssDNA projector consumes; key = `helix:bp:direction`). [move_rotate_panel.js](frontend/src/scene/move_rotate_panel.js)
    adds a **"Constrained (taut bonds)"** pivot option for duplex clusters → `setConstraint('ssdna', payload)`
    (falls back to centroid + warns if no resolvable bonds). Pins: 3 new `move_rotate_panel.test.js` cases
    + **e2e** `duplex_taut_constraint.spec.js` (the integration risk: endpoint → doc-aware client →
    `helix:bp:direction` key format → geometry resolution; asserts every anchor resolves + the mode arms).
    1854 frontend vitest green; backend green (pre-existing `test_build_2x6_matches_golden` golden-drift
    aside).
  - **NOT hand-driven / RISK:** the actual gizmo-ring **drag** with the taut projection is a WebGL gesture
    (human-eye), AND the flagged short-tether stability (#3: the PBD is tuned for multi-nm ssDNA; ~0.67 nm
    bonds are near-rigid → possible oscillation) can only be judged by dragging in-app. If it oscillates,
    the follow-up is the analytic 1-DOF (rotate-about-root→root-axis) fast path for the monovalent case.
    MV-DUPTAUT.
- **P4 — Cleanup. ROUTING DONE 2026-07-01 (log-migration remaining).**
  - **SCOPE CORRECTION (2026-07-01):** the plan's premise ("cluster path covers what the panel does,
    replace outright") was WRONG on two counts, verified before touching anything:
    (a) the orientation panel/menu orients **any** overhang incl. **standalone/unconnected** ones (no
    duplex cluster exists → the gizmo can't cover them); (b) `OverhangRotationLogEntry` is **dual-purpose**
    — whole-overhang rotation (the duplex pose) AND per-sub-domain θ/φ (no `ClusterOpLogEntry` equivalent).
    User re-scoped (2026-07-01): **retire only for DUPLEX overhangs** (route them to the gizmo; keep the
    panel for standalone); Reset Orientation → cluster gizmo/menu; migrate ONLY duplex-backed whole-overhang
    log entries.
  - **DONE — menu routing.** [overhang_orientation_menu.js](frontend/src/ui/overhang_orientation_menu.js):
    if the right-clicked overhang is duplex-backed (`duplexClusterForOverhang`, new in
    [design_queries.js](frontend/src/scene/design_queries.js) — matches driver directly / driven via
    domain_ids), the top two items become **"Move / Rotate duplex"** (→ activate the cluster gizmo via
    `_activateTranslateRotateTool(clusterId)`) + **"Reset Orientation"** (→ `patchCluster` to identity
    pose + `getGeometry`). Standalone/non-duplex overhangs keep **"Edit Orientation"** (panel) +
    whole-overhang identity reset. Pins: `overhang_orientation_menu.test.js` (+4 routing cases),
    `design_queries.test.js` (+1 `duplexClusterForOverhang`). 1859 frontend green; boot-clean (both duplex
    e2e specs pass). main.js net −7 this session.
  - **REMAINING — feature-log migrate-on-load.** Convert old saved designs' whole-overhang
    `OverhangRotationLogEntry` slots (for now-duplex overhangs) → `ClusterOpLogEntry` so history-scrub
    doesn't re-apply a stale OverhangSpec rotation that fights the materialized cluster (would trip the
    validator's "duplex driver pose must be identity" guard). SUBTLE: faithful conversion needs the
    conjugated cluster transform re-derived per log position (what `materialize_duplex_cluster` computes);
    the safe fallback is to DROP those now-obsolete slots on load. Backend-only; do with fresh context +
    careful `_seek_feature_log` replay tests. Keep `OverhangRotationLogEntry` for sub-domain θ/φ + standalone.
  - **NOT hand-driven:** the right-click "Move / Rotate duplex" gesture on a 3D duplex overhang + the
    Reset visual are human-eye (unit-pinned routing logic + boot-clean).

## 10. Open questions for the user (before P0)
1. **(B) child-cluster (fixes drift, more work) vs (A) overlay-backed (faster, keeps drift)?**
2. **Auto-create the duplex-cluster on every Apply, or only when the user chooses "make movable"?**
   (Auto = discoverable but clutters the sidebar.)
3. **Monovalent constrained drag:** is "rotate about the root→root axis only" (the clash DOF) the
   intended play, or do you also want small translational wobble until a bond goes taut?
4. **Multivalent:** one cluster covering all duplexes on an overhang, or one per duplex edge? And
   what should the rotation-point dropdown offer when there are >2 ends?
5. **Keep the separate orientation panel** during migration, or replace it outright?

## References (from a 3-agent codebase sweep, 2026-07-01)
- Cluster model/CRUD/gizmo/sidebar: `models.py:1054`, `routes_clusters.py:61/123/183`,
  `crud.py:10647` (begin-drag), `cluster_panel.js`, `cluster_gizmo.js`,
  `deformation.py:650/733` (domain-aware apply).
- Flexible constrained drag: `models.py:386-437`, `flexible_segments.py`, `flexible_relax.py:49`,
  `cluster_gizmo.js:828` (`_projectSsdnaConstraints`), `flexible_arcs.js`,
  `routes_flexible_segments.py:107`, `move_rotate_panel.js`.
- Overhang pose + orientation edit: `models.py:242-283`, `deformation.py:1040`
  (`apply_overhang_rotation_if_needed`) + `:922` (`_overhang_binding_partner_refs`) + `:1808`
  (`_apply_ovhg_rotations_to_axes`), `overhang_orientation_panel.js`, `crud.py:4877`
  (`patch_overhang_rotations_batch`), `design_queries.js:30-53`, and the shipped
  `direct_relax.py` (`duplex_midpoint_placement`, `_root_anchors`, bridge relax).
