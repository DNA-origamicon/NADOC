---
name: Create Seam algorithm — architecture, rules, and regression fixture
description: Frontend Create Seam handler in main.js: Hamiltonian path, coverage groups, HJ placement rules, and the 10-6-10 golden test
type: project
originSessionId: 9f602024-1a47-4924-9d3a-bebeb724cea3
---
## What Create Seam does

Inserts Holliday junctions (double scaffold crossovers) to form a seam through a DNA-origami bundle. Implemented entirely in the frontend (`frontend/src/main.js`, `menu-create-seam` click handler). Fires one atomic `POST /design/crossovers/place-batch` call.

## Key data structures

**scaffoldCoverage** — `Map<helixId, [{lo, hi}]>`: scaffold bp intervals per helix, built from scaffold strand domains then **merged** (adjacent intervals with gap ≤ 1 bp are collapsed). Merging is critical: re-running seam on an already-seamed design splits scaffold strands; without merging each split produces multiple small intervals → spurious extra HJs.

**globalAdj** — HC adjacency graph where an edge (hA, hB) exists iff there is at least one bp in `intersectCoverage(covA, covB)` that is a valid HC scaffold crossover from hA to hB.

**Coverage signature** (`covSig`) — `"lo1:hi1|lo2:hi2|…"` sorted by lo. Helices with identical signatures belong to the same **coverage group**. For 10-6-10: outer group `"0:41|126:167"`, core group `"0:167"`.

## Path-finding algorithm

1. Find connected components in globalAdj.
2. For each component:
   - Group helices by coverage signature.
   - **Single group** (uniform design like 6HB/18HB): find one global Hamiltonian path via DFS (degree-ascending start heuristic).
   - **Multiple groups** (dumbbell etc.):
     - Sort groups by total scaffold bp ascending (arm groups first).
     - Find Hamiltonian path within each group using **local** (within-group) adjacency only.
     - Chain group paths via a single bridge edge: orient the arm path so its bridge-end helix is last; find the bridge core helix; find the core path starting from that helix.
     - Result: `arm_rail … arm_bridge | core_bridge … core_rail`.
3. `path[0]` and `path[last]` are rails (no HJs). Interior consecutive pairs `(path[1],path[2])`, `(path[3],path[4])`, … each get Holliday junctions.

## HJ placement per pair

For each interior pair `(hA, hB)`:
1. Compute `overlap = intersectCoverage(covA, covB)` — already-merged intervals.
2. For **each interval** `{lo, hi}` in overlap:
   - Collect all valid HC crossover bps in `[lo, hi]`.
   - Find the consecutive pair `(bp, bp+1)` closest to `intervalMid = (lo+hi)/2`.
   - Emit two crossovers (one HJ) at those bps.

**Interval count per pair type:**
- core↔core: one interval → one HJ.
- outer↔outer: two intervals (left arm + right arm) → two HJs.
- bridge (outer↔core): two intervals → two HJs (one per arm section).

**Why this is correct:** same-group pairs with two intervals span two disconnected scaffold segments; each segment needs its own junction. Re-running seam doesn't create extra intervals because of the merge step.

## Nick bp computation

```js
lowerBp = bowRightSet.has(bp % period) ? bp - 1 : bp
nickBpFwd = lowerBp
nickBpRev = lowerBp + 1
```
HC bow-right set: `{2,5,9,12,16,19}`, period 21.

## Regression fixture

**File:** `tests/fixtures/10-6-10hb_seamed.nadoc`
**Test:** `tests/test_create_seam.py::TestCreateSeamReferenceLayout` (4 tests)

Expected HJ layout for the 10-6-10 dumbbell (10 helices, bp 0-167):

| Pair              | Type        | Interval   | HJ bps  |
|-------------------|-------------|------------|---------|
| h_0_5 ↔ h_1_5    | outer↔outer | [0,41]     | 18, 19  |
| h_0_5 ↔ h_1_5    | outer↔outer | [126,167]  | 144,145 |
| h_1_4 ↔ h_1_3    | bridge      | [0,41]     | 22, 23  |
| h_1_4 ↔ h_1_3    | bridge      | [126,167]  | 148,149 |
| h_1_2 ↔ h_1_1    | core↔core   | [0,167]    | 85, 86  |
| h_0_1 ↔ h_0_2    | core↔core   | [0,167]    | 88, 89  |

Rails (no crossovers): `h_0_4` (outer), `h_0_3` (core).
Global path: `[h_0_4, h_0_5, h_1_5, h_1_4, h_1_3, …core…, h_0_3]`

**Why:** `h_0_4` is the outer path endpoint (degree-1 node, the DFS starts there). `h_1_4` is the outer bridge endpoint (connects to core `h_1_3`). The outer group local path is the only Hamiltonian path through the linear chain `h_0_4–h_0_5–h_1_5–h_1_4`.

## Files touched

- `frontend/src/main.js` — `menu-create-seam` click handler (~line 8282)
- `frontend/src/api/client.js` — `placeCrossoverBatch`
- `backend/api/crud.py` — `POST /design/crossovers/place-batch`
- `frontend/src/scene/helix_renderer.js` — `buildStapleColorMap` (staple-only index, color stability)
- `tests/fixtures/10-6-10hb_seamed.nadoc` — golden reference
- `tests/test_create_seam.py` — regression tests
