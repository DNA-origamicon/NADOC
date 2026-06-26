---
name: Create Near Ends / Create Far Ends — architecture, bugs, and open issues
description: Frontend handlers for capping scaffold arm termini with crossovers; search offsets, covSig grouping bug (hi-only fix applied, lo-only fix still needed), teeth.nadoc simulation
type: project
originSessionId: 9f602024-1a47-4924-9d3a-bebeb724cea3
---
## Pipeline (always in this order)
1. **Create Seam** — places HJs in the interior of each arm
2. **Create Near Ends** — caps each arm's lo (near) face with a crossover; extends helix axis_start + scaffold domain lo face backward to xoverBp
3. **Create Far Ends** — caps each arm's hi (far) face with a crossover; extends helix axis_end + scaffold domain hi face forward to xoverBp

All three handlers are in `frontend/src/main.js` (verify with `grep -n menu-create-` — line numbers drift):
- Create Seam: `menu-create-seam`
- Create Near Ends: `menu-create-near-ends`
- Create Far Ends: `menu-create-far-ends`

Backend:
- `POST /design/near-ends/create` — same structure as far-ends; extends axis_start + lo face
- `POST /design/far-ends/create` — extends axis_end + hi face

## Search offsets (both SQ, period=32)

Near ends: `for (let bp = lo - 3; bp >= lo - period; bp--)` — guarantees ≥3 bp extension below lo face.

Far ends: `for (let bp = hi + 3; bp <= hi + period; bp++)` — guarantees ≥3 bp extension above hi face.

Previous wrong values: `lo - 4` / `hi + 4` (caused off-by-one, sometimes landing on non-bow-right positions or skipping valid positions). Changed to `lo - 0` then corrected to `lo - 3` / `hi + 3` in 2026-04-28 session.

## SQ scaffold crossover map (both handlers share this)

```
SQ_SCAF_XOVER_MAP keys: '(0|1)_(mod)' → [dRow, dCol]
period = 32
SQ_SCAF_BOW_RIGHT = {0,3,5,8,11,13,16,19,21,24,27,29}
```

Bow-right crossovers produce a clean merge (no stub). Non-bow-right produce a 1-bp stub.

`nickBpForStrand(xoverBp, strand)`:
- `lowerBp = bowRight ? xoverBp - 1 : xoverBp`
- FORWARD → `lowerBp`, REVERSE → `lowerBp + 1`

## covSig grouping bug — ROOT CAUSE

Both handlers find a Hamiltonian path through helices, grouped by coverage signature. The pairing `(path[0],path[1]), (path[2],path[3]), …` must be **identical** between near-ends and far-ends so each arm gets its near and far crossover placed between the **same two helices**.

**Bug**: After Create Near Ends extends lo faces by different amounts per pair (e.g., h_XY_2_3/h_XY_3_3 extended by 8, h_XY_3_1/h_XY_3_2 extended by 5), each outer helix pair gets a unique `lo:hi` coverage signature. In Create Far Ends, this splits 8 outer helices into 4 groups of 2. The bridge-chain algorithm then connects them via insertion-order-dependent JS `Set` traversal — in some orderings this produces `h_XY_3_3 → h_XY_3_2` as an even-index pair (bp=128 crossover), **mismatched** from the near-end pairing `h_XY_2_3 ↔ h_XY_3_3`.

**Fix applied (2026-04-28)** — Create Far Ends covSig now uses hi-only:
```javascript
const covSig = id => scaffoldCoverage.get(id)
  .slice().sort((a, b) => a.hi - b.hi).map(({hi}) => `${hi}`).join('|')
```
Hi values are unchanged by near-end extension, so all outer helices with hi=41,125,209 stay in ONE group, restoring the same single-group DFS as near-ends.

**Symmetric fix applied (2026-05-09)** — Create Near Ends covSig now uses lo-only:
```javascript
const covSig = id => scaffoldCoverage.get(id)
  .slice().sort((a, b) => a.lo - b.lo).map(({lo}) => `${lo}`).join('|')
```
Hardens grouping against any operation that modifies hi values before Near Ends runs.

**Note (verified 2026-05-09)**: Create Far Ends has since been refactored beyond the original hi-only covSig — it now derives pairs directly from `create_near_ends` crossovers on the design, and refuses to run if no near-end crossovers exist. So the order-dependence concern is structurally enforced now, not papered over with covSig. The hi-only covSig in this file's earlier version no longer exists in the codebase; only Create Near Ends still uses covSig (lo-only).

## Simulation script

Python simulation used to trace the full pipeline: `/tmp/sim_teeth2.py` (not committed, but reproducing it is easy — see this session's conversation).

Key finding: pairs MUST match between near and far for the U-turn arms to be topologically correct. A mismatch creates a path like `seam → h_3_3_near → far_to_h_3_2 → h_3_2_near_back_to_h_3_1` — invalid topology.

## Test design: workspace/teeth.nadoc

- 4×4 SQ grid, 16 helices, all bp_start=0, length_bp=210
- Inner helices (rows 0–1): 8 helices, single scaffold interval [0,209]
- Outer helices (rows 2–3): 8 helices, 3 scaffold intervals [0,41],[84,125],[168,209]
- `"crossovers": []` — always load fresh (no seam, no near/far ends applied)
- Helix array indices: h_XY_0_0=0 ... h_XY_3_3=12, h_XY_3_2=13, h_XY_3_1=14, h_XY_3_0=15

## Expected near-end pairs (teeth.nadoc fresh, SQ DFS)

Path order: [h_XY_2_3, h_XY_3_3, h_XY_3_2, h_XY_3_1, h_XY_3_0, h_XY_2_0, h_XY_2_1, h_XY_2_2, …inner…]

| Pair | lo faces | xover bps |
|------|----------|-----------|
| h_XY_2_3 ↔ h_XY_3_3 | 0, 84, 168 | -8, 77, 163 |
| h_XY_3_2 ↔ h_XY_3_1 | 0, 84, 168 | -5, 80, 165 |
| h_XY_3_0 ↔ h_XY_2_0 | 0, 84, 168 | -3, 72, 157 |
| h_XY_2_1 ↔ h_XY_2_2 | 0, 84, 168 | -11, 75, 160 |

All are bow-right (merge, no stub). All ≥3bp extension.

## Expected far-end pairs (with hi-only fix)

Same pairs as near-ends. Skip helix: h_XY_0_0 (array index 0 — prevents scaffold loop closure).

| Pair | hi faces | xover bps |
|------|----------|-----------|
| h_XY_2_3 ↔ h_XY_3_3 | 41, 125, 209 | 44, 130, 215 |
| h_XY_3_2 ↔ h_XY_3_1 | 41, 125, 209 | 47, 132, 218 |
| h_XY_3_0 ↔ h_XY_2_0 | 41, 125, 209 | 50, 135, 220 |
| h_XY_2_1 ↔ h_XY_2_2 | 41, 125, 209 | 52, 128, 212 |

Most are stub (non-bow-right). bp=128 (h_XY_2_1↔h_XY_2_2, hi=125) is the only merge in far-ends.
