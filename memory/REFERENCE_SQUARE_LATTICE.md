---
name: REFERENCE_SQUARE_LATTICE
description: DTP-SQ decisions, SQ geometry constants, scaffold routing, implementation checklist
type: project
---

## Phase SQ — Square Lattice (complete, merged master 2026-03-19)

## DTP-SQ Decisions (binding)

| ID | Decision |
|----|----------|
| DTP-SQ-a | Lattice type on `Design.lattice_type`, not per-helix |
| DTP-SQ-b | Twist = 33.75°/bp (3 turns per 32 bp) — `3 * 360 / 32` |
| DTP-SQ-d | Helix spacing = row pitch = col pitch = 2.25 nm (same as honeycomb) |
| DTP-SQ-e | Cell rule: `(row+col)%2==0` → FORWARD; else → REVERSE (all cells valid, no holes) |
| DTP-SQ-g | `File > New` lattice-picker dialog — implemented |

## Constants
```python
# backend/core/constants.py
SQUARE_TWIST_PER_BP_DEG = 3 * 360 / 32   # = 33.75°/bp
SQUARE_TWIST_PER_BP_RAD = 33.75 * π / 180
SQUARE_BP_PER_TURN      = 32 / 3         # ≈ 10.667
SQUARE_HELIX_SPACING    = 2.25           # nm

# frontend/src/constants.js
SQUARE_HELIX_SPACING    = 2.25
SQUARE_TWIST_PER_BP_DEG = 33.75
SQUARE_TWIST_PER_BP_RAD = 33.75 * Math.PI / 180
```

## Scaffold Routing for SQ
- `sq_lattice_periodic_skips(design)` → one skip/48bp/helix, staggered by helix index; auto-applied on UpdateStapleRouting for SQ designs without existing deformations

## Lattice Detection (Frontend)
```javascript
Math.abs(helix.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-4
```
Used in: `slice_plane.js`, `overhang_locations.js`, `main.js`

## Overhang Arrows for SQ
- 4 cardinal neighbors only: `[[-1,0],[1,0],[0,-1],[0,1]]`
- Distance check uses `SQUARE_HELIX_SPACING`
- Helix ID regex supports negative row/col: `/^h_\w+_(-?\d+)_(-?\d+)$/`

## Test Coverage
`tests/test_square_lattice.py` — 23 tests (SQ-1 through SQ-5)

## Implementation Status
- SQ-1: Square grid rendering in workspace.js ✅
- SQ-2: Geometry (33.75°/bp twist) in geometry.py ✅
- SQ-4: Auto-scaffold 4-neighbor path ✅
- SQ-5: Auto-staple ✅
- SQ-6: Lattice-aware guards — slice plane, overhang arrows ✅
