# Feature 03: Clustering
**Phase**: D (Transform Features — requires Phase A + B + C)

---

## Feature Description

Clusters are named rigid groups of helices that move together as a unit. Transformation is applied via a 3D gizmo (translate + rotate). Clusters use `ClusterRigidTransform` in the model.

**Key files**:
- `frontend/src/scene/cluster_gizmo.js` — 3D transform manipulator
- `frontend/src/ui/cluster_panel.js` — sidebar management
- `backend/core/models.py` — `ClusterRigidTransform`, `ClusterJoint`
- `backend/core/deformation.py` — `_apply_cluster_rigid_transform()` (line ~350), `_apply_cluster_transforms_domain_aware()` (line ~414)
- `backend/api/routes.py` — cluster CRUD + joint routes

**API routes**:
- `POST /design/cluster` — create
- `PATCH /design/cluster/{id}` — update transform
- `DELETE /design/cluster/{id}` — delete
- `POST /design/cluster/{id}/begin-drag` — start drag
- `POST /design/cluster/{id}/joint` — add joint
- `PATCH /design/joint/{id}` — update joint
- `DELETE /design/joint/{id}` — delete joint

**Known pre-existing bugs**: `project_cluster_joints.md` — rotation tools have known bugs. **Read before editing.**

### Crossover interaction
When a cluster is moved, the helices in the cluster move rigidly. Crossover connections between helices in the cluster should move with the cluster. Crossover connections from cluster helices to non-cluster helices (inter-cluster crossovers) should stretch between the moved and unmoved positions.

---

## Pre-Condition State

- `crossover_connections.js` reads `design.crossovers` and looks up current backbone positions from `currentGeometry`
- If `currentGeometry` is updated after a cluster transform (via `PATCH /design/cluster/{id}`), crossover lines should automatically move to the new backbone positions — no special handling needed
- Unknown: does the cluster drag path update `currentGeometry` in real-time (every drag frame), or only on release?
- `project_cluster_joints.md` has known bugs — full status must be read before touching joint code

---

## Clarifying Questions

1. During a live cluster drag (before release), do crossover lines:
   - (a) Update every drag frame (requires frontend-only transform, not API call each frame)
   - (b) Update only when the drag is committed (release → API call → geometry update)
   - (c) Currently option (b); should it be changed to (a) for better UX?

2. Are cluster transforms applied **before** or **after** deformation ops (`TwistParams`, `BendParams`) in the geometry computation pipeline?
   - This determines whether a twisted helix in a cluster can be correctly rotated as a unit

3. Are joints (connectors between clusters that allow relative rotation) still expected to use `design.crossovers` entries to identify connection points, or do joints have their own positional data?

---

## Experiment Protocol

### Experiment 3.1 — Cluster moves helices in 3D

**Hypothesis**: After creating a cluster with 2 helices and translating it via the gizmo, the selected helices move in 3D while non-cluster helices stay in place.

**Test Steps**:
1. Load `Honeycome_6hb_test1_NADOC.nadoc`
2. Select 2 adjacent helices, add them to a cluster
3. Translate the cluster via the gizmo (+5 nm in X)
4. Check: selected helices moved; other helices unchanged

**Data Collection**:
```javascript
const geo = window._nadoc?.store?.getState()?.currentGeometry
const helix0_pos = geo?.find(n => n.helix_id === clusterHelixId && n.bp_index === 0)
console.log('helix0 backbone_position after translate:', helix0_pos?.backbone_position)
```

**Pass Criteria**: Cluster helices at new position; non-cluster helices at original positions.

---

### Experiment 3.2 — Intra-cluster crossovers move with cluster

**Hypothesis**: A crossover between two helices in the same cluster moves rigidly with the cluster transform — the line segment moves but its length (inter-bead distance) is unchanged.

**Test Steps**:
1. Load design with a crossover between two helices
2. Add both helices to a cluster
3. Record crossover line endpoints (from mesh geometry)
4. Translate cluster
5. Check endpoints moved by exactly the translation vector

**Data Collection**:
```javascript
// Before and after translate, check crossover mesh positions
const mesh = window._nadoc?.scene?.getObjectByName('crossoverConnections')
const positions = Array.from(mesh.geometry.attributes.position.array)
// Expected: positions shift by [dx, dy, dz] uniformly for intra-cluster xovers
```

**Pass Criteria**: Intra-cluster crossover line shifts by the cluster translation vector within 0.001 nm tolerance.

**Fail → Iteration 3.2a**: If crossover line doesn't move, `crossover_connections.js` is being rebuilt from the post-transform `currentGeometry` correctly. Check that `currentGeometry` is updated after the cluster translate API call.

---

### Experiment 3.3 — Inter-cluster crossovers stretch

**Hypothesis**: A crossover between a helix in cluster A and a helix NOT in cluster A shows the crossover line stretching when cluster A is translated — one endpoint moves, the other stays.

**Test Steps**:
1. Load `3NN_ground truth.nadoc` (has crossovers between adjacent helices)
2. Put helix 0 in cluster A
3. Translate cluster A by +10 nm in X
4. Check crossover line between helix 0 and helix 1: one end at new position, other at original

**Pass Criteria**: Line stretches; both endpoints correct.

---

### Experiment 3.4 — Joint system with new crossover model

**Hypothesis**: Cluster joints (hinge connectors between two clusters) position their connection points based on `design.crossovers` entries or their own explicit positions — not on old strand topology inference.

**Test Steps**:
1. Read `project_cluster_joints.md` for the joint creation workflow
2. Create two clusters with a joint between them
3. Check: joint position in 3D vs. nearest `design.crossovers` entry
4. Rotate one cluster via its joint
5. Check joint endpoint positions

**Data Collection**: Joint position from `GET /design` joint data; compare to `design.crossovers[N].half_a.index`.

**Pass Criteria**: Joint positions are at or near existing crossover positions (or at user-specified positions if joints are independent of crossovers).

**Fail → Iteration 3.4a**: If joints reference old crossover model fields that no longer exist, update joint positional data to use `design.crossovers` IDs.

---

### Experiment 3.5 — Known cluster joint bugs from project_cluster_joints.md

**Test Steps**:
1. Read `project_cluster_joints.md` — list all open bugs with reproduction steps
2. Reproduce each bug systematically
3. Document: which bugs are still present after the overhaul?

**Pass Criteria (for triage purposes)**: Complete current-state documentation added to `project_cluster_joints.md`. At least one previously-known bug confirmed present or confirmed fixed.

---

## Performance Notes

*Do not implement until experiments pass.*

- `cluster_gizmo.js` re-queries backbone entries on each drag frame to update the gizmo's visual anchor. This is O(n_beads) per frame. Cache the per-cluster bead entry set at gizmo activation time and invalidate only on design rebuild.
- `PATCH /design/cluster/{id}` triggers a full backend geometry recompute. For live drag (if implemented), this is too slow. A frontend-only transform preview (apply translation matrix to cached cluster positions in JS, no API call) should be used during drag, with a single API commit on mouse-up.
- `_apply_cluster_transforms_domain_aware()` is called during `deformed_nucleotide_positions()`. Profile its contribution to overall geometry computation time.

---

## Refactor Plan

*Execute only after all 3.x experiments pass.*

1. **Frontend-only drag preview**: implement a `ClusterDragPreview` class in `cluster_gizmo.js` that applies a `THREE.Matrix4` to cached bead positions during drag, bypassing API calls. Commit to backend only on mouse-up.
2. **Crossover line live update during drag**: after implementing drag preview, ensure crossover endpoints are also updated from the preview transform each frame.
3. **Cache bead entries per cluster**: at `beginDrag`, snapshot which `backboneEntries` belong to this cluster and cache them. Clear on `endDrag`.
4. **Update `project_cluster_joints.md`**: document findings from Experiment 3.5.
5. **Performance baseline**: record drag frame rate on 26HB with 2 clusters of 6 helices each.
