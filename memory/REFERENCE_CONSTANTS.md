---
name: REFERENCE_CONSTANTS
description: All B-DNA and lattice constants — HC/SQ spacing, twist, cell rules. Source of truth: backend/core/constants.py
type: project
---

## B-DNA Parameters (constants.py)
```python
BDNA_RISE_PER_BP        = 0.334        # nm/bp
BDNA_TWIST_PER_BP_DEG   = 34.3         # degrees/bp  (360/10.5)
BDNA_TWIST_PER_BP_RAD   = 0.598430...  # rad/bp
BDNA_BP_PER_TURN        = 10.5
HELIX_RADIUS            = 1.0          # nm — backbone bead center-to-axis
BASE_DISPLACEMENT       = 0.3          # nm — base bead radially inward from backbone
BDNA_MINOR_GROOVE_ANGLE_RAD = 2π/3    # 120° — angle between FORWARD and REVERSE bead
```

## Honeycomb Lattice Constants
```python
HONEYCOMB_HELIX_SPACING = 2.25         # nm — center-to-center between adjacent helices
COL_PITCH = 1.125 * √3 ≈ 1.9486       # nm — x-spacing between columns
ROW_PITCH = 2.25                       # nm — y-spacing between rows (NADOC)
# NOTE: caDNAno HC row step = 3.375 nm (NOT 2.25) — see REFERENCE_CADNANO.md

HC_BP_PER_TURN = 10.5                  # (same as B-DNA)
```

## HC Cell Rule (binding)
```python
val = (row + col % 2) % 3
# 0 = FORWARD, 1 = REVERSE, 2 = HOLE
```

## Square Lattice Constants
```python
SQUARE_TWIST_PER_BP_DEG = 3 * 360 / 32  # = 33.75 deg/bp
SQUARE_TWIST_PER_BP_RAD = 33.75 * π/180
SQUARE_BP_PER_TURN      = 32 / 3        # ≈ 10.667
SQUARE_HELIX_SPACING    = 2.25          # nm (same as HC)
```

## SQ Cell Rule
```python
(row + col) % 2 == 0 → FORWARD; else → REVERSE  # all cells valid (no holes)
```

## Frontend Constants (constants.js)
```javascript
BDNA_RISE_PER_BP  = 0.334
HELIX_RADIUS      = 1.0
SQUARE_HELIX_SPACING    = 2.25
SQUARE_TWIST_PER_BP_DEG = 33.75
SQUARE_TWIST_PER_BP_RAD = 33.75 * Math.PI / 180
```

## Lattice Detection (Frontend)
```javascript
// Detect SQ design from helix twist_per_bp_rad:
Math.abs(helix.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-4
```

## XPBD Solver Constants (constants.py)
```python
ALPHA_BOND      = 1.0    # bond constraint compliance
ALPHA_BEND      = 0.8
ALPHA_BP        = 0.8
ALPHA_STACKING  = 0.5
SUBSTEPS        = 50
```

## STAPLE_PALETTE
12-color palette for staple strands: `STAPLE_PALETTE[strand_id % 12]`
Defined in `backend/core/constants.py`. Import from here only — never hardcode colors.

## Strand Color Scheme
- Scaffold: sky blue `#29b6f6`
- Staple: `STAPLE_PALETTE[strand_id % 12]`
- Unassigned: `#445566`
- Scaffold 5' glow: red `#ff4444`; 3' glow: blue `#4488ff`; scale 2.0
