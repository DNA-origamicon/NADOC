# Experiment 20 — caDNAno SQ Import Coordinate Convention

**Date**: 2026-03-21
**Branch**: cadnano → master

---

## Question

Does importing a caDNAno square-lattice file produce the same helical orientation
at bp=0 as extruding a native NADOC square-lattice design?  And which axis
conventions are correct?

---

## Axis Inversion Investigation

caDNAno's canvas coordinate system:
- X increases left → right (column direction)
- Y increases top → bottom (row direction, screen-down)

NADOC's 3D coordinate system:
- X increases left → right
- Y increases bottom → top (world-up)

This means the **row (Y) axis is inverted** between caDNAno and NADOC.
A helix at caDNAno row 0 (top) should map to the *highest* Y in NADOC.

### What other visualizers do

cadnano2, scadnano, and every other known SQ visualizer accept this Y-inversion
without correcting it.  The SQ slice plane appears vertically mirrored relative
to the caDNAno canvas, but the structure is topologically correct.  **NADOC
follows the same accepted convention.**

### X-axis

For HC, NADOC negates X (`axis_start.x = -(nc × COL_PITCH)`) to mirror the
left-right ordering of the caDNAno canvas about the YZ plane.  Experiments
confirmed this makes the 3D view match caDNAno visually.

For SQ, the final convention is:
- `x = +(nc × 2.25 nm)` — **not negated** (col increases in +X)
- `y = -(nr × 2.25 nm)` — **negated** (row increases in −Y, following caDNAno screen-down)

In `_helix_xy()` (cadnano.py) this is achieved by returning `x_raw = -(nc*pitch)`
(so `axis_start(x = -x_raw)` yields `+(nc*pitch)`) and `y_raw = -(nr*pitch)`
(used directly as `axis_start.y`).

---

## Ground Truth — 2×4 SQ Design

Source file: `Examples/cadnano/2x4sq.json`
- Vstrands: rows 23–24, cols 29–32 → normalised nr ∈ {0,1}, nc ∈ {0,1,2,3}
- Array length: 64 bp (64 % 32 == 0 → SQ detected correctly)

### Helix positions after import (NADOC world frame)

| Helix ID   | nc | nr | x (nm)  | y (nm)  | Direction |
|------------|----|----|---------|---------|-----------|
| h_XY_0_0  |  0 |  0 |  0.000  |  0.000  | FORWARD   |
| h_XY_0_1  |  1 |  0 |  2.250  |  0.000  | REVERSE   |
| h_XY_0_2  |  2 |  0 |  4.500  |  0.000  | FORWARD   |
| h_XY_0_3  |  3 |  0 |  6.750  |  0.000  | REVERSE   |
| h_XY_1_0  |  0 |  1 |  0.000  | -2.250  | REVERSE   |
| h_XY_1_1  |  1 |  1 |  2.250  | -2.250  | FORWARD   |
| h_XY_1_2  |  2 |  1 |  4.500  | -2.250  | REVERSE   |
| h_XY_1_3  |  3 |  1 |  6.750  | -2.250  | FORWARD   |

Spacing between any adjacent pair = 2.25 nm ✓

### Phase / backbone orientation at bp=0

| Design         | FORWARD phase | REVERSE phase | Backbone az (FWD) |
|----------------|--------------|--------------|-------------------|
| Imported SQ    | 337.00°      | 287.00°      | 247.00°           |
| Native NADOC   | 337.00°      | 287.00°      | 247.00°           |

Import and native extrusion are **identical** at bp=0.  ✓

---

## Conclusion

- **Y-inversion is intentional and accepted**: all known SQ visualizers use it.
- **Import phase matches native extrusion exactly** (FORWARD=337°, REVERSE=287°).
- **X is not negated for SQ** (unlike HC where x is negated for YZ-mirror).
- Tests: exp confirmed with `experiments/exp_sq_phase_comparison.py`.
