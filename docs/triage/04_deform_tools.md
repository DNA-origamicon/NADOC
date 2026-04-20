# Feature 04: Deform Tools (Bend, Twist, Translate/Rotate + Deformed View)
**Phase**: D (Transform Features — requires Phase A + B + C)

---

## Feature Description

Three deformation tools that alter the geometric shape of a bundle:

| Tool | Model | Key params |
|------|-------|-----------|
| **Bend** | `BendParams` | `angle_deg`, `direction_deg` |
| **Twist** | `TwistParams` | `total_degrees` OR `degrees_per_nm` |
| **Cluster Rigid Transform** | `ClusterRigidTransform` | `translation`, `rotation` (quaternion), `pivot` |

Translate/rotate is handled by the cluster system (see Feature 03). Bend and twist are the domain of the deformation editor.

**Key files**:
- `frontend/src/scene/deformation_editor.js` — state machine (`IDLE → AWAITING_A → A_PLACED → BOTH_PLANES_PLACED`)
- `frontend/src/ui/bend_twist_popup.js` — parameter sliders
- `frontend/src/scene/deform_view.js` — lerp between straight (t=0) and deformed (t=1) geometry
- `backend/core/deformation.py` — `deformed_nucleotide_positions()`, `_precompute_arm_frames()`
- `backend/core/geometry.py` — calls `deformed_nucleotide_positions()` when `design.deformations` is non-empty

**Store keys**: `deformToolActive`, `deformVisuActive`, `straightGeometry`, `straightHelixAxes`

**Critical invariant** (from MAP_DEFORMATION.md): Every `Design(...)` constructor call in `lattice.py` that rebuilds from an existing design **MUST** include `deformations=existing_design.deformations`. Missing this causes silent deformation loss after any topology mutation.

---

## Pre-Condition State

From MAP_DEFORMATION.md known issues:
- Intermittent bug: bend/twist geometry wrong after certain sequences of routing ops
- The `Design(...)` invariant — unknown if any new crossover mutation paths in `lattice.py` miss `deformations=`
- Unknown: does `POST /design/crossovers` trigger a `Design(...)` rebuild that may drop deformations?
- `deform_view.js` integration with new crossover rendering is unverified

---

## Clarifying Questions

1. When a crossover is added/removed while deformations are active (non-empty `design.deformations`), should the deformation be:
   - (a) Automatically re-applied to the new geometry (consistent user experience)
   - (b) Preserved but geometry frozen until user manually triggers recompute
   - (c) Cleared (too dangerous — user must re-apply deformation after topology changes)

2. Is the **deformed view toggle** (`deformVisuActive`) expected to work while cadnano 3D mode (K key) is active?
   - MAP_CADNANO.md says the deformation *tool* is blocked while cadnano is active
   - Is the *view toggle* (lerp to deformed positions) also blocked?

3. After the overhaul, should crossover lines in `crossover_connections.js` be drawn at:
   - (a) **Deformed** backbone positions (crossover lines curve with the bundle)
   - (b) **Straight** backbone positions always (crossover lines are always straight, even if bundle is bent)
   - (c) Whatever position `currentGeometry` reports — deformed or straight depending on `deformVisuActive`

---

## Experiment Protocol

### Experiment 4.1 — Deformations persist after crossover mutation

**Hypothesis**: After applying a bend deformation, adding a crossover (which triggers a `Design(...)` rebuild in the backend) does NOT clear `design.deformations`. The geometry remains bent.

**Test Steps**:
1. Load `multi_domain_test3_bend90.nadoc` (pre-bent 90° fixture)
2. Verify bend is active: check `design.deformations` non-empty
3. Add a crossover via `POST /design/crossovers`
4. Fetch geometry — check it is still bent (backbone positions at deformed locations)

**Data Collection**:
```bash
# Before crossover add
curl http://localhost:8000/api/design | python3 -c "import sys,json; d=json.load(sys.stdin); print('deformations:', len(d['design']['deformations']))"

# After crossover add
curl -X POST http://localhost:8000/api/design/crossovers -H 'Content-Type: application/json' \
  -d '{"half_a": {...}, "half_b": {...}}'
curl http://localhost:8000/api/design | python3 -c "import sys,json; d=json.load(sys.stdin); print('deformations after xo add:', len(d['design']['deformations']))"
```

**Pass Criteria**: `len(design.deformations)` unchanged after crossover add.

**Fail → Iteration 4.1a**: If deformations are lost, find the `Design(...)` constructor call in the crossover add path in `crud.py` / `lattice.py` that omits `deformations=`. Grep `Design(` in `lattice.py` and `crud.py` to find the culprit.

---

### Experiment 4.2 — Crossover lines render at deformed positions

**Hypothesis**: When `deformVisuActive = true`, `crossover_connections.js` renders crossover lines at the deformed backbone positions (not straight lattice positions).

**Test Steps**:
1. Load `multi_domain_test3_bend90.nadoc`
2. Toggle deformed view on (`deformVisuActive = true`)
3. Check crossover mesh positions — endpoints should be at curved positions

**Data Collection**:
```javascript
// Check a crossover endpoint position when deformVisuActive = true vs false
const xo = window._nadoc?.store?.getState()?.currentDesign?.crossovers?.[0]
// half_a position from currentGeometry should match deformed backbone_position
const geo = window._nadoc?.store?.getState()?.currentGeometry
const half_a_nuc = geo?.find(n =>
  n.helix_id === xo.half_a.helix_id &&
  n.bp_index === xo.half_a.index &&
  n.direction === xo.half_a.strand
)
console.log('half_a backbone_position (should be deformed):', half_a_nuc?.backbone_position)
```

**Pass Criteria**: Backbone positions when `deformVisuActive = true` differ from straight positions by the expected bend displacement. Crossover mesh positions match.

**Fail → Iteration 4.2a**: If crossover lines don't update when `deformVisuActive` toggles, `crossover_connections.js` is using stale geometry. Check that `buildCrossoverConnections()` is called whenever `deformVisuActive` changes, using the correct geometry (straight vs. deformed).

---

### Experiment 4.3 — Deformed view lerp animation

**Hypothesis**: Toggling `deformVisuActive` triggers a 500ms smooth lerp from straight to deformed (or back). During the lerp, crossover lines update each frame to track the intermediate bead positions.

**Test Steps**:
1. Load bent design, ensure deformVisuActive = false
2. Toggle deformVisuActive = true
3. Record frame-by-frame crossover mesh positions during the 500ms lerp

**Data Collection**: Screenshot at t=0ms, t=250ms, t=500ms. Confirm crossover endpoints are at lerp-interpolated positions.

**Pass Criteria**: Smooth visual transition; crossover lines move continuously during lerp.

**Fail → Iteration 4.3a**: If crossover lines snap rather than lerp, `deform_view.js::applyLerp()` updates bead positions but the crossover mesh is only rebuilt at the end of the lerp. Fix: call `buildCrossoverConnections()` (or update mesh in-place) on every `applyLerp()` tick.

---

### Experiment 4.4 — Deform tool is blocked in cadnano mode

**Hypothesis**: The deformation tool is correctly blocked when `cadnanoActive = true`. Attempting to place plane A while in cadnano mode does nothing.

**Test Steps**:
1. Enter cadnano mode (K key)
2. Attempt to activate deformation tool
3. Verify: tool does NOT activate; `deformToolActive` remains false

**Pass Criteria**: No deformation tool activation while `cadnanoActive = true`.

---

### Experiment 4.5 — Bend/twist wrong after routing (intermittent bug regression)

**Hypothesis**: The intermittent bug ("bend/twist geometry wrong after certain sequences of routing ops") is reproducible via a specific sequence.

**Test Steps** (combinatorial — try each sequence):
1. Sequence A: autoscaffold → prebreak → apply 45° bend → check geometry
2. Sequence B: apply 45° bend → autoscaffold → check geometry (expect deformations preserved)
3. Sequence C: apply 45° bend → add crossover → apply 30° twist → check geometry

**Data Collection**: For each sequence, measure the actual end position of helix 0's final bp against the expected deformed position. Use `GET /design/deformation/debug` for frame-level detail.

**Pass Criteria**: Geometry matches analytical expectation (from `deformation.py` formula) for all sequences. Any failure pinpoints the sequence that triggers the bug.

**Fail → Iteration 4.5a**: If Sequence B fails (deformation cleared after autoscaffold), grep `Design(` in `auto_scaffold()` and its sub-functions for missing `deformations=` argument.

**Fail → Iteration 4.5b**: If Sequence C fails (compound deformation wrong), check `_precompute_arm_frames()` handling of the case where both bend and twist ops exist on the same segment.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_precompute_arm_frames()` in `deformation.py` (line ~522) is described as "vectorized" — verify it is actually using NumPy array ops, not a Python for-loop with NumPy element accesses.
- `deformed_nucleotide_positions()` (line ~809) returns all nucleotide positions; check if it iterates helices in a Python loop and calls `_precompute_arm_frames()` once per helix. If so, pre-concatenate all helix bp ranges and do one large vectorized pass.
- `deform_view.js::applyLerp()` iterates all backbone entries per frame. This is unavoidable for lerp but could be accelerated with a `Float32Array` in-place lerp using `for(let i=0;i<buf.length;i+=3) buf[i] = a[i] + t*(b[i]-a[i])` instead of `Vector3.lerp()` calls.

---

## Refactor Plan

*Execute only after all 4.x experiments pass.*

1. **Audit `Design(...)` calls**: use `grep -n 'Design(' backend/core/lattice.py backend/api/crud.py` and verify every call that rebuilds from an existing design passes `deformations=existing.deformations`. Document the complete list.
2. **In-place Float32 lerp** in `deform_view.js`: replace `Vector3.lerp()` calls with a typed array inner loop for the lerp tick — benchmark improvement.
3. **Crossover lines during lerp**: add crossover mesh update to `applyLerp()` tick (see Iteration 4.3a).
4. **Write regression test**: `tests/test_deformation.py` — add test that applies bend, then adds crossover, and asserts `len(design.deformations)` unchanged.
5. **Performance baseline**: record `deformed_nucleotide_positions()` execution time on 26HB before/after vectorization.
