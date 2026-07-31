---
name: overhang-duplex-cluster
description: "SHIPPED (P0–P3 + P4 routing, 2026-07-01) — the overhang-duplex pose is a first-class CHILD cluster (parent_cluster_id + overhang_duplex_driver_id) with sidebar entry, gizmo, rotation-point dropdown and taut-bond constrained drag. Rank P2 — the only remaining work is feature-log migrate-on-load for designs saved before 2026-07-01."
metadata: 
  node_type: memory
  type: project
  originSessionId: f15e083b-6e16-4cf7-a87d-e75a3380eb1f
---

# Overhang Duplex as a Cluster

**Status: SHIPPED and wired end-to-end.** Audited 2026-07-30 (`/audit-plan`): every anchor this
plan names resolves in live code except one claimed test that never existed. **Rank: P2** — one
narrow backend-only item is left (feature-log migrate-on-load, §Open items 1), it affects only
`.nadoc` files saved before 2026-07-01, and it has a cheap safe fallback.

> **The old head said "planning; no code" and listed "Open questions for the user (before P0)".**
> That was wrong by a month. P0/P1a/P1b/P1c/P2/P3 are DONE and P4's menu routing is DONE. If you
> came here to design this, stop — **it exists**; you are about to rebuild shipped code. The
> design narrative, the phase log, the answered open questions, and the DEAD-END list are in
> `project_overhang_duplex_cluster_archive.md`.

## The law (what the mechanism actually is)

A duplex pose is a **CHILD `ClusterRigidTransform`** — `parent_cluster_id` = the driver part's
cluster, `overhang_duplex_driver_id` = the driver overhang id, `domain_ids` = the duplex domains.
Its `rotation`/`translation`/`pivot` are stored in the **parent's REST frame, not world**.

- **Composition order is child-INNER**: `p' = T_parent(T_child(p_rest))`. `deformation.py:673-675`
  partitions `parent_cluster_id`-bearing clusters out, `:716-723` applies them masked to their own
  domains first, `:726` lays the parent on top. This is *distinct* from the legacy domain-level
  overwrite, which is the OUTER order `T_child(T_parent)`.
- **The pose MOVES, it is not copied.** `materialize_duplex_cluster` conjugates the world pose into
  the parent rest frame (`T_child = T_P⁻¹·T_W·T_P`) and **clears** the driver's `OverhangSpec`
  pose to identity (`duplex_cluster.py:186-190`). `validate_design` errors if a duplex driver still
  carries a non-identity spec pose (`validator.py:331-340`) — that's the double-transform guard.
- **The gizmo's stored pivot is NOT a world point.** `_refreshClusterPivotForAttach` (computing the
  world visual centroid + rebasing) **must keep running for duplex clusters** — skipping it puts the
  handles at `[0,0,0]+childT`, far off the structure. The effective rotation centre is
  `pivot + translation`, where the handles render, not the internal `_pivot`. (Archive: DEAD END.)

**The old overlay is not dead — the two paths are mutually exclusive PER OVERHANG, not layered.**
`ovhg.rotation/.translation/.pivot` still has 11 read sites (all in `deformation.py`) and remains
the *sole* mechanism for **standalone/unconnected overhangs**, for every **driven partner** (which
keeps its identity overlay entry), and for the whole **per-sub-domain θ/φ** chain. Only a
*materialized driver* is cleared and short-circuited (`apply_overhang_rotation_if_needed:1144-1153`).
Do not "finish the migration" by deleting the overlay.

## Where the code is (probed 2026-07-30)

### Backend

| Thing | Location |
|---|---|
| `ClusterRigidTransform.parent_cluster_id` / `.overhang_duplex_driver_id` | `models.py:1181` / `:1187` |
| Core module (13 fns) | `backend/core/duplex_cluster.py` |
| `materialize_duplex_cluster` (5 callers) | `:156` ← `crud.py:6335` (load), `crud.py:7695` (`_cv_create_bound_binding`), `direct_relax.py:593`, `duplex.py:343` (`relocate_duplex`), `headless_build.py:926` |
| `dematerialize_duplex_cluster` | `:311` ← `direct_relax.py:365` only |
| `duplex_cluster_for` | `:142` ← `crud.py:6323/6330`, `direct_relax.py:354/361/595` |
| `duplex_cluster_rotation_points` / `set_duplex_cluster_pivot` | `:227` / `:294` ← `routes_clusters.py:217/277`, `:283` |
| `duplex_cluster_tethers` | `:257` ← `routes_clusters.py:231`, **`connection_tethers.py:135/177`** |
| `conjugate_world_pose_into_parent_rest` | `:80` — internal only (used at `:197`) |
| Child-first composition / partial-coverage skip | `deformation.py:650` (`:673-675`, `:716-723`) · `_apply_cluster_transforms_to_point:816` sorts children first `:829`, skips a duplex cluster on partial helix coverage `:832-838` |
| `_overhang_is_duplex_cluster_driver` / axes re-source | `deformation.py:808` · `apply_overhang_rotation_if_needed:1131` (`:1144-1153`) · `_apply_ovhg_rotations_to_axes:1897` (driver check `:1969`) |
| Validation (parent exists / domain-level / no cycle / identity-pose guard) | `validator.py:303-342` |
| Routes | `routes_clusters.py:207` GET rotation-points · `:220` GET duplex-tethers · `:263` POST rotation-point (router registered `main.py:52`) |
| Migration-on-load (**poses only**) | `_materialize_duplex_clusters_on_load` `crud.py:6317` ← `/design/load` `:1368` + `/design/import` `:1402` |
| Relax wrap | `direct_relax.py:365` dematerialize → solve → `:593` re-materialize reusing the same `cluster_id` |
| Teardown | `revert_bind_topology` (`binding_relax.py:505`) ← `duplex.py:353`, `crud.py:7757/8720/8813` |
| Headless + oracle | `headless_build.py:915` · `assert_duplex_cluster_materialized` `tests/automation_harness.py:1724` |

### Frontend

| Thing | Location |
|---|---|
| Sidebar `⛓` tag | `ui/cluster_panel.js:226-228` |
| Pivot dropdown (`dup:root:{oid}`, `dup:taut`) | `scene/move_rotate_panel.js:92` (`_mrSetPivotOptions`, 4 `main.js` sites), option build `:110`/`:115-118`, handlers `:275-296`, `_setDuplexRotationPoint:251` |
| Taut payload | `scene/flex_relax.js:137` `buildDuplexTautPayload` ← `move_rotate_panel.js:287` → `cluster_gizmo.setConstraint('ssdna',…)` `:1315` / `_projectSsdnaConstraints:1137` |
| API client | `api/client.js:2809` `setClusterRotationPoint` (wired) · `:2785` `getClusterDuplexTethers` (wired) · `:2778` `getClusterRotationPoints` **orphaned — e2e-only** |
| Right-click routing | `ui/overhang_orientation_menu.js:69-93` (duplex → "Move / Rotate duplex" + cluster-identity "Reset Orientation"; standalone → the panel) · `scene/design_queries.js:476` `duplexClusterForOverhang` |
| Apply toast | `ui/overhang_connections_panel.js:768-776` (cluster-id diff) |
| Orientation panel (still live, standalone overhangs) | `ui/overhang_orientation_panel.js` ← `main.js:167/4785` |

### Tests (all fast, none `slow`)

`test_child_cluster_composition.py` (4) · `test_duplex_cluster_parity.py` (7, incl.
`test_duplex_cluster_segment_axis_follows_child_composition:144`) · `test_duplex_cluster_rotation_point.py`
(3) · `test_duplex_cluster_tethers.py` (3) ·
`test_direct_connection_unified.py:221` (`…logs_cluster_op_not_overhang_rotation…`).
Vitest: `move_rotate_panel.test.js` (24 duplex refs), `overhang_orientation_menu.test.js` (20),
`design_queries.test.js:173-185`. E2E under **`frontend/e2e/`**: `duplex_rotation_point.spec.js`,
`duplex_gizmo_pivot.spec.js`, `duplex_taut_constraint.spec.js`; their dev hooks are all live
(`main.js:7625/7637/7648`, `cluster_gizmo.js:1607`).

## Open items (live, rewritten against the 2026-07-30 probe)

1. **Feature-log migrate-on-load — the only real remaining phase work (P4).** Old saved designs
   still hold whole-overhang `OverhangRotationLogEntry` slots for overhangs that are now
   duplex-backed. `_materialize_duplex_clusters_on_load` (`crud.py:6317-6336`) migrates **poses
   only — it never touches `design.feature_log`**, and `_seek_feature_log` is entirely
   duplex-blind (`rg duplex` over `crud.py:9000-11000` = 0 hits; the `overhang_rotation` branch
   at `:10829` has no cluster awareness). So scrubbing history on a pre-2026-07-01 file re-applies
   a stale OverhangSpec rotation that fights the materialized cluster and trips the validator's
   identity-pose guard. Faithful conversion needs the conjugated transform re-derived per log
   position; **the safe fallback is to DROP those now-obsolete whole-overhang slots on load.**
   Backend-only. Keep `OverhangRotationLogEntry` — it is still emitted at `crud.py:5050/5128/5300/5390`
   and is dual-purpose (whole-overhang **and** per-sub-domain θ/φ).
2. **A claimed pin does not exist.** `test_real_fixture_materialize_is_bead_and_shaft_neutral` —
   the frozen-fixture "materialize is bead-and-shaft neutral" parity test the phase log cites as
   proof of the geometry-source switch — has **zero hits repo-wide**. The parity property is
   covered synthetically in `test_duplex_cluster_parity.py`, but nothing pins it on a real
   `.nadoc`. Either write it or stop citing it.
3. **`getClusterRotationPoints` is orphaned in the app** (`client.js:2778`, 0 callers under
   `frontend/src`; only `frontend/e2e/duplex_rotation_point.spec.js:51`). The panel builds its
   `dup:root:` options client-side from the active cluster's driver+driven overhang instead of
   asking the server, so the GET route and the client fn exist for the test alone. Either consume
   it (and get the server's labels/centroid for free) or delete both.
4. **Dropdown doesn't read back the real pivot.** On activation the pivot `<select>` shows
   "Centroid" even when the materialized cluster's pivot is already a root bead. Cosmetic, known,
   deferred.
5. **Short-tether PBD stability is still unjudged.** `_projectSsdnaConstraints` is tuned for
   multi-nm ssDNA; duplex tethers are ~0.67 nm bonds (near-rigid) → possible oscillation under
   drag. Only a human eye on the WebGL ring-drag settles it. If it oscillates, the follow-up is an
   analytic 1-DOF (rotate-about-root→root-axis) fast path for the monovalent case. **MV-DUPTAUT.**
6. **Hand-validation owed** (`manual_validation_debt.md`, repo **root** — this plan did file its
   debt, all 4 rows still describe reachable gestures): **MV-CONNLINK**, **MV-DUPMENU**,
   **MV-DUPPIVOT**, **MV-DUPTAUT**. All are WebGL gestures (gizmo ring-drag, right-click routing).

**Closed since the plan was written, do not re-open:** P0's two deferred items are both done —
the helix-AXIS path is child-aware (`_apply_cluster_transforms_to_point:829-838`) and the light
validator shipped (`validator.py:303-342`). The §10 "open questions for the user" were all
answered on 2026-07-01 (Option B / auto-create on Apply / translational wobble-until-taut / one
cluster per overhang covering all its duplexes / replace the panel for duplex overhangs only).

## Which doc to open

- **This file** — the child-cluster mechanism: composition order, frame conjugation, gizmo pivot,
  taut tethers.
- [[overhang-duplex-foundation]] (P1) — the `Duplex`/`DuplexEnd` model of record, the 9 duplex
  routes, and the `OverhangBinding` coexistence truth table. It **defers duplex-cluster topics
  here**; this plan supplied its P4b(2) relax-for-a-binding-less-duplex.
- [[overhang_connections_panel]] — the Apply/Relax pipeline as the *user* drives it. Note its
  known bug narrative about `_duplex_domain_refs` → `materialize_duplex_cluster` `domain_ids`
  (`:126/135`); the different-length partial-coverage variant of that was **confirmed and fixed**
  2026-07-30 via `deformation._bound_driver_driven_pairs` (see LESSONS **E8**).
- [[ssdna_ball_joints]] — carries behaviour this plan does not describe: its gate takes
  `duplex_ids` and **skips** any ball-joint crossing where either side is a duplex child, and its
  tether payload reuses `duplex_cluster_tethers`' bond shape.
- [[cluster_joints]] — the local-frame storage precedent this design copied.
- `project_tech_debt.md:16-45` — the DELETE-ON-COMPLETION entry for the legacy overlay. **Its
  precondition is open item 1, not "the plan ships"**, and the overlay itself must survive for
  standalone overhangs + sub-domain θ/φ.
- `.claude/rules/deformation.md:94` mentions `parent_cluster_id` in one line with stale anchors
  (`:676-689`; the partition is now `:673-675`, Step 1 `:716-723`).

**History:** `project_overhang_duplex_cluster_archive.md` (design narrative §1–§8, the full P0–P4
phase log with both P2 bug root-causes, the DEAD-END list, the 2026-07-01 decisions, references).
