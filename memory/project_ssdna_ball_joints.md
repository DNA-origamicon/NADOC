---
name: ssdna-flexible-segments
description: "Flexible ssDNA segments — mark unpaired runs flexible → fixed-length arc between EXISTING clusters → real-time \"ssDNA constrained\" cluster drag (free until taut). Replaced the auto-cut \"ball joint\" approach. Shipped 2026-05-30."
metadata: 
  node_type: memory
  type: project
  originSessionId: 874f5bfb-0255-4978-aea7-e313162dea01
---

# Flexible ssDNA segments + real-time "ssDNA constrained" drag

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Mark a contiguous run of UNPAIRED beads as a flexible tether. Each marked run bridging two **existing** clusters becomes a fixed-contour-length `FlexibleConnection`. The move/rotate tool gains an **"ssDNA constrained"** pivot option (enabled only when every inter-cluster connection from the selected cluster is flexible); dragging the cluster is clamped per-frame so no tether exceeds its contour length ("free until taut"), and the segment renders as a fixed-length geometric arc. Display-layer only — NEVER mutates topology. Plan: `~/.claude/plans/we-want-to-create-indexed-pancake.md`.

**REPLACED the earlier auto-cut "ball joint" approach** (mark beads → derive new arms → Powell solve). The user found that paradigm wrong. Rigid arms are now the user's OWN clusters; no auto-cut, no solver, no new clusters. (Old `ball_joint_arms.py`/`ball_joint_solve.py` deleted; `ClusterRigidTransform.kind` removed.)

## Key definition (got it wrong once)
"Unpaired" = **no Watson-Crick partner** at the same `(helix,bp)`, NOT `overhang_id`. mini_hinge's tethers are unpaired *scaffold* runs. `flexible_segments.unpaired_bead_keys(design)`.

## Architecture
- **Models** (`models.py`): `FlexibleSegmentMark{strand_id,domain_index,bp_index,direction}`, `FlexibleAnchor`, `FlexibleConnection{cluster_a_id,cluster_b_id,anchor_a,anchor_b,n_ss_bases,contour_length_nm=n×0.59,segment_bead_keys}`. `Design.flexible_segment_marks` (source of truth) + `Design.flexible_connections` (derived).
- **`backend/core/flexible_segments.py`**: `unpaired_bead_keys`; `_build_bead_graph` (backbone + forced-ligation + crossover edges); `derive_flexible_connections` (marked-component BFS → rigid neighbours grouped by owning EXISTING cluster via `_owning_cluster_id`; ≥2 clusters → a connection; crosses forced ligations because FL edges are in the graph); `cluster_flexible_gate`/`all_cluster_gates` (a cluster's inter-cluster crossing is flexible iff one endpoint is marked; gate = ≥1 crossing and no rigid crossing); `apply_marks` (recompute connections only — no cluster/topology mutation).
- **API** (`crud.py`): `is_flexible_segment` + `is_unpaired` per-bead geometry flags in `_strand_nucleotide_info`. Routes `POST/DELETE /design/flexible-segment`, `POST /design/flexible-segment/batch` (selective `marks=[...]`; `replace:true` w/ no marks clears all; NO "all ssDNA"), `GET /design/flexible-connections` (connections + per-cluster gates). Mark/unmark return full geometry (beads reclassify).
- **Frontend**:
  - `client.js`: markFlexibleSegment / unmarkFlexibleSegment / batchFlexibleSegment / getFlexibleConnections.
  - `helix_renderer.js`: `_isFlexibleSegmentNuc` excludes flexible beads from the rigid InstancedMeshes (same two filter sites as `_isSsLinkerBridgeNuc`).
  - `flexible_arcs.js` (NEW): `initFlexibleArcs(scene, designRenderer, getHelixAxes)` draws each connection as a circular arc of arc-length = contour_length (bows as chord shrinks; straightens when taut) between live anchor world positions (from `getBackboneEntries().pos`), beads sampled along it. `rebuild(design)` on design change; `applyLiveUpdate(helixIds, centerVec, dummyPos, incrQuat)` per drag frame (wired in main.js onLiveTransform). **Bow DIRECTION = cylinder repulsion**: away from nearby helix-axis centerlines (`store.currentHelixAxes`, within OBST_RADIUS=12nm), projected perp to the chord, so slack arcs bulge outward instead of diving through the structure. The moving cluster's axes are transformed by the live drag transform so obstacles share the arcs' frame. Hysteresis (BOW_SMOOTH=0.6 blend with previous) prevents mid-drag flips. Heuristic, not a true collision solve.
  - `selection_manager.js`: `_showFlexibleSegmentMenu` (gated on `nuc.is_unpaired`, frontmost over cone, non-linker) → Mark/Unmark flexible segment + Clear all; opt `onFlexibleSegmentRightClick`.
  - `main.js`: `_flexibleRunForBead` (contiguous unpaired run on the strand around the clicked bead → mark/unmark the whole run via batch replace). Move/rotate pivot dropdown gains "ssDNA constrained" when `_flexGates[clusterId].gate` (fetched via `_refreshFlexGates` on tool open / cluster switch); selecting it calls `clusterGizmo.setConstraint('ssdna', {connections, resolveWorldPos})` via `_buildSsdnaPayload`.
  - `cluster_gizmo.js`: `setConstraint('ssdna', {connections, resolveWorldPos})` (reuses normal translate/rotate TC — projection only). Armed at drag start (`_ssArmed` = per-tether {pM0 cloned, pF cloned, contour}). `_projectSsdnaConstraints()` runs in the `'change'` handler after `_incrQuat`: PBD rigid solve (6 iters), each iter = rotation about pivot from tether torque (clamped 0.25 rad/iter) + residual translation, gain 0.6. Candidate moving-anchor pos = `incrQuat·(pM0−startDummyPos)+dummyPos`. Free until taut (skips slack tethers). 1 taut → slide on sphere; 2+ → rotation about the taut-anchor line (emergent hinge axis). **The torque-rotation is a linearised no-SVD approx — most likely piece to need tuning.**

<a id="mini_hingenadoc-worked-example-verified"></a>
- [mini_hinge.nadoc (worked example, verified)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#mini_hingenadoc-worked-example-verified)

<a id="verification-2026-05-30"></a>
- [Verification (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#verification-2026-05-30)

<a id="drawstring-arc-fix-2026-05-30"></a>
- ["Drawstring" arc fix (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#drawstring-arc-fix-2026-05-30)

<a id="axis-stick-suppression-over-flexible-regions-2026-05-30"></a>
- [Axis-stick suppression over flexible regions (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#axis-stick-suppression-over-flexible-regions-2026-05-30)

<a id="base-slabs-on-the-flexible-arc-2026-05-30"></a>
- [Base slabs on the flexible arc (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#base-slabs-on-the-flexible-arc-2026-05-30)

<a id="feature-log--right-click-arc-unmark-2026-05-30"></a>
- [Feature-log + right-click-arc unmark (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#feature-log--right-click-arc-unmark-2026-05-30)

<a id="undo-fix-2026-05-30"></a>
- [Undo fix (2026-05-30)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#undo-fix-2026-05-30)

<a id="undo-fix-2--non-marks-topology-change-drops-the-flag-2026-06-07"></a>
- [Undo fix #2 — non-marks topology change drops the flag (2026-06-07)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#undo-fix-2--non-marks-topology-change-drops-the-flag-2026-06-07)

<a id="relax-command-right-click--relax-2026-05-31"></a>
- [Relax command (right-click → "Relax", 2026-05-31)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#relax-command-right-click--relax-2026-05-31)

<a id="imported--overlapping-cluster-fix-2026-06-01"></a>
- [Imported / overlapping-cluster fix (2026-06-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#imported--overlapping-cluster-fix-2026-06-01)

<a id="headless-relax-port--jspython-parity-af-29-2026-06-25"></a>
- [Headless relax port + JS↔Python parity (AF-29, 2026-06-25)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#headless-relax-port--jspython-parity-af-29-2026-06-25)

<a id="duplex-child-cluster-must-be-transparent-to-the-ssdna-gate-2026-07-01"></a>
- [Duplex-child cluster must be TRANSPARENT to the ssDNA gate (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#duplex-child-cluster-must-be-transparent-to-the-ssdna-gate-2026-07-01)

<a id="connected-overhangs-as-move-constraints--constrained-tethers-2026-07-01"></a>
- [Connected overhangs as move constraints — "Constrained (tethers)" (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#connected-overhangs-as-move-constraints--constrained-tethers-2026-07-01)

<a id="movable-link-tethers-duplexds-linker-swing-live-during-a-drag-2026-07-01"></a>
- [Movable-link tethers: duplex/ds-linker swing live during a drag (2026-07-01)](details/project_ssdna_ball_joints/01-mini_hingenadoc-worked-example-verified.md#movable-link-tethers-duplexds-linker-swing-live-during-a-drag-2026-07-01)

<a id="unified-scaffold-context-menu-2026-07-01"></a>
- [Unified scaffold context menu (2026-07-01)](details/project_ssdna_ball_joints/02-unified-scaffold-context-menu-2026-07-01.md#unified-scaffold-context-menu-2026-07-01)

<a id="oxdna-seed--display-of-flexible-runs-2026-07-02"></a>
- [oxDNA seed + display of flexible runs (2026-07-02)](details/project_ssdna_ball_joints/02-unified-scaffold-context-menu-2026-07-01.md#oxdna-seed--display-of-flexible-runs-2026-07-02)

## Deferred / refine
Kabsch (SVD) rigid fit instead of linearised torque; bow direction from exit-tangents; refresh gate dropdown when marks change while tool already open; per-frame arc rebuild allocates geometry (fine for few tethers, optimize if many).
