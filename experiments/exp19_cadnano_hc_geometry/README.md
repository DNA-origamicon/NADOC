# Experiment 19 — caDNAno HC Physical Geometry

**Date**: 2026-03-20
**Branch**: cadnano
**Status**: ✅ Resolved

---

## Problem

Two tests were failing after reformulating the caDNAno import geometry:

- `test_6hb_neighbour_geometry` — FAIL
- `test_18hb_neighbour_geometry` — FAIL

The import was producing wrong helix XY positions, including one helix with
5 physical neighbours at 2.25 nm instead of the expected ≤3.

---

## Hypothesis

The HC import formula used **NADOC's row pitch (2.25 nm)** to compute caDNAno
physical positions. If the true caDNAno row pitch is different, helix positions
will be wrong and neighbour distances will be incorrect.

---

## The 4-NN Misunderstanding (Root Cause Analysis)

During debugging I claimed "18HB has interior helices with 4 nearest neighbours."
This was **incorrect**. Here is why:

### Wrong formula used in analysis

I was computing caDNAno physical Y positions as:

```python
y_down = row * 2.25 + (1.125 if col % 2 == 1 else 0)   # WRONG
```

This used **NADOC's row pitch = 2.25 nm** and caDNAno's column-based stagger.

With this formula, from helix (row=9, col=13):
- (row=8, col=13): dist = 2.25 nm ← found as neighbour
- (row=10, col=13): dist = 2.25 nm ← **incorrectly** found as neighbour
- (row=9, col=12): dist = 2.25 nm ← found
- (row=9, col=14): dist = 2.25 nm ← found

→ 4 antiparallel neighbours claimed.

### Correct caDNAno2 formula (from source)

From `cadnano2/model/parts/honeycombpart.py::latticeCoordToPositionXY`:

```python
x = column * radius * root3          # COL_PITCH = R√3 ≈ 1.9486 nm
if isOddParity(row, column):         # (row%2) ^ (col%2) == 1
    y = row * radius * 3 + radius    # row * 3R + R
else:
    y = row * radius * 3             # row * 3R
```

The **row step is 3R = 3.375 nm**, not 2.25 nm.

With the correct formula, from (row=9, col=13):
- (row=8, col=13): `|9×3.375 - (8×3.375+1.125)| = |2.25| = 2.25 nm` ✓ neighbour
- (row=10, col=13): `|(10×3.375+1.125) - 9×3.375| = |4.5| = 4.5 nm` ✗ NOT a neighbour

The four candidate positions I found are only 3 actual HC neighbours (the fourth
pair is 4.5 nm apart, not 2.25 nm).

### caDNAno2 lattice neighbour rule (from source)

From `honeycombpart.py::getVirtualHelixNeighbors`:

```python
if isEvenParity(r, c):          # row%2 == col%2  → FORWARD
    neighbors = [(r, c+1),      # p0: right column
                 (r-1, c),      # p1: row ABOVE (r-1, not r+1!)
                 (r, c-1)]      # p2: left column
else:                           # odd parity → REVERSE
    neighbors = [(r, c-1),      # p0: left column
                 (r+1, c),      # p1: row BELOW (r+1, not r-1!)
                 (r, c+1)]      # p2: right column
```

**Key insight**: For EVEN-parity helices, the vertical neighbour is at `row-1`
(the row above in caDNAno's Y-down coordinate), not `row+1`. So (9,13) EVEN
connects upward to (8,13), not downward to (10,13).

With 3R row pitch:
- (9,13) EVEN → (8,13): `Δy = |9×3R - (8×3R+R)| = |3R-R| = 2R = 2.25 nm` ✓
- (9,13) EVEN → (10,13): `Δy = |(10×3R+R) - 9×3R| = |3R+R| = 4R = 4.5 nm` ✗

Every HC helix has **exactly 3 antiparallel neighbours at 2.25 nm with 120° gaps**.
The user was correct all along.

---

## Correct Import Formula

```python
# Y-down position in caDNAno (before flip)
y_cad = row * 3 * HONEYCOMB_LATTICE_RADIUS + (HONEYCOMB_LATTICE_RADIUS if (row%2)^(col%2) else 0)

# Y-up position in NADOC (after flip, normalised so min = 0)
max_y_cad = max(y_cad for all vstrands)
y_nadoc = max_y_cad - y_cad
```

Where `HONEYCOMB_LATTICE_RADIUS = 1.125 nm` and row step = `3 × 1.125 = 3.375 nm`.

---

## Verification

Computed positions for 6HB (min_col=15, max_row=17) match NADOC reference exactly:

| vstrand      | caDNAno formula result | NADOC reference |
|--------------|------------------------|-----------------|
| (17,15)→h_XY_0_0 | (0.0000, 1.1250) | (0.0000, 1.1250) ✓ |
| (16,15)→h_XY_1_0 | (0.0000, 3.3750) | (0.0000, 3.3750) ✓ |
| (16,16)→h_XY_1_1 | (1.9486, 4.5000) | (1.9486, 4.5000) ✓ |
| (16,17)→h_XY_1_2 | (3.8971, 3.3750) | (3.8971, 3.3750) ✓ |
| (17,17)→h_XY_0_2 | (3.8971, 1.1250) | (3.8971, 1.1250) ✓ |
| (17,16)→h_XY_0_1 | (1.9486, 0.0000) | (1.9486, 0.0000) ✓ |

18HB symm (compact ring): all 18 helices have ≤3 antiparallel NN, and all
helices with exactly 3 NN have uniform 120° angular gaps.

---

## Conclusion

- **Root cause of 4-NN claim**: used wrong row pitch (2.25 nm instead of 3.375 nm)
- **Fix**: replaced formula in `_helix_xy` with correct caDNAno2 physical formula
- **Test result**: 17/17 cadnano tests pass; 317/317 total tests pass
- **Key reference**: `cadnano2/model/parts/honeycombpart.py` cloned to `/home/joshua/cadnano2`
