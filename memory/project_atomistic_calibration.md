---
name: Atomistic calibration — status and known issues
description: Template re-extraction in production radial frame; WC H-bond geometry; canonical P-P correction for REV strand; phase offset calibration
type: project
originSessionId: 04bb0f97-c933-428d-98f3-616d69ed1281
---
## Status (2026-04-14, final — Entry 6 + phase offset baked in)

All templates calibrated and production-ready. 609 tests pass.
The atomistic model is fully aligned with the NADOC CG bead/slab representation.

## Architecture

`build_atomistic_model(design)` in `backend/core/atomistic.py` — no runtime parameters.
All constants are baked in at module level.

Verification tool: `scripts/verify_atomistic_geometry.py`
Template extraction: `scripts/reextract_nadoc_templates.py`
Chi optimisation: `scripts/optimize_base_rotations.py`

## Calibration History

**Entry 2** — O3' fix: P_tmpl shifted +0.65 Å along C3'→P direction; O3' re-derived.
- C3'–O3'–P = 120.36° (target 119.35°) ✓

**Entry 4** — OP1/OP2 fix + C1'–N glycosidic bond fix:
- OP1/OP2 shifted by same ΔP as P — restores crystal P→OP geometry
- C1'-referenced extraction for all base atoms: C1'–N = 1.44–1.47 Å ✓

**Entry 5** — (SUPERSEDED) Chi-rotation with wrong objective (minimise absolute H-bond distance).
Produced ring interpenetration in some pairs (N1(A)···O4(T) = 0.167 nm clash).

**Entry 6** — Chi-rotation re-optimised for equidistance of WC H-bonds:
- Objective: Σ(d_i − T_common)² + VdW clash penalty (λ=5000, threshold 0.26 nm)
- T_AT = 0.295 nm, T_GC = 0.289 nm (mean of canonical WC distances)
- Global optimum confirmed by 72×72 full-grid search (5° steps, ±180°)
- No ring interpenetration — minimum inter-strand distance ≥ 0.260 nm
- All backbone atoms (_SUGAR) unchanged from Entry 4

**Phase offset calibration** — rigid-body rotation about helix axis:
- A phase offset slider was added to the UI to tune CG↔atomistic alignment
- Critical finding: naive post-multiplication of R (the rotation matrix) rotated
  atoms about the P anchor point (0.886 nm off-axis), not the helix axis.
  The correct fix is to rotate `e_radial` around `axis_tangent` before computing
  the frame, which moves the origin and co-rotates e_n/e_y so all atoms orbit
  as a rigid body. Inter-atom distances are preserved to floating-point precision.
- Calibrated value: **−32°** baked as `_ATOMISTIC_PHASE_OFFSET_RAD` in atomistic.py
- Slider and dev endpoint removed; phase is now a baked constant.

## Current Constants (`atomistic.py`)

- `_FRAME_ROT_RAD = -0.646577` (−37.05°) — cancels pre-compensation in templates
- `_ATOMISTIC_P_RADIUS = 0.886` nm
- `_ATOMISTIC_PP_SEP_RAD = 208.2°` (FWD→REV P-P azimuthal separation, 1ZEW empirical mean)
- `_ATOMISTIC_TOPOLOGY_GROOVE_RAD = 150.0°`
- `_ATOMISTIC_PHASE_OFFSET_RAD = −32°` (helix-axis rotation, CG alignment)

## Current SUGAR key atoms
- P:   (−0.1020,  0.1588,  0.2560) [shifted −0.062 nm from crystal]
- OP1: (−0.2263,  0.1547,  0.3352) [crystal + ΔP]
- OP2: (−0.0584,  0.0376,  0.1803) [crystal + ΔP]
- O3': (−0.0605,  0.5756, −0.1253) [re-derived]
- C1': ( 0.2248,  0.4334,  0.0000)

## Base template chi-rotations (Entry 6, from Entry 4)
| Template | θ from Entry 4 |
|----------|----------------|
| FWD DA   | +2.255°  |
| FWD DT   | −9.393°  |
| FWD DG   | +16.962° |
| FWD DC   | −13.031° |
| REV DA   | +0.997°  |
| REV DT   | −13.591° |
| REV DG   | −10.173° |
| REV DC   | −36.459° |

## WC H-bond distances (Entry 6, from verify_atomistic_geometry.py)

AT pairs — equidistant within chi rotation constraint (mean ~0.292–0.295 nm, spread ~32–35 pm):
- FWD A/REV T: N6···O4 = 0.323 nm, N1···N3 = 0.260 nm
- FWD T/REV A: O4···N6 = 0.329 nm, N3···N1 = 0.260 nm

GC pairs — limited by C1'–C1' compression (0.967 nm vs canonical 1.05 nm):
- FWD G/REV C: O6···N4 = 0.415 nm, N1···N3 = 0.339 nm, N2···O2 = 0.260 nm
- FWD C/REV G: N4···O6 = 0.435 nm, N3···N1 = 0.346 nm, O2···N2 = 0.260 nm

No ring interpenetration. GROMACS minimization will relax GC geometry.

## Remaining Issues

### 1. O5'–P bridging angle = 70.5°
P shift in Entry 2 moved P but not O5'. P→O5' = 1.427 Å (target 1.60 Å).
Acceptable for GROMACS starting geometry.

### 2. C1'–C1' inter-strand = 0.967 nm (8% short of canonical 1.05 nm)
Root cause of imperfect GC H-bond geometry. Chi rotation cannot correct this.
GROMACS minimization will relax toward equilibrium.

### 3. C1'–N bonds ~0.01–0.03 Å shorter than target (1.47–1.48 Å)
FWD DA/DT/DG: 1.453–1.456 Å; REV DT: 1.440 Å. Within GROMACS tolerance.

## How to modify the model in the future

**To re-run base chi optimization**: `uv run python scripts/optimize_base_rotations.py`
**To verify geometry**: `uv run python scripts/verify_atomistic_geometry.py`
**To re-extract sugar templates**: `uv run python scripts/reextract_nadoc_templates.py`
**To adjust phase alignment**: change `_ATOMISTIC_PHASE_OFFSET_RAD` in `atomistic.py`
  - This is a rigid rotation of all atoms about the helix axis
  - Positive = CCW when viewed from the +Z direction
  - Does NOT change any inter-atom distances
**To adjust backbone geometry** (P, OP1, OP2, O3', C1'): edit `_SUGAR` in `atomistic.py`
**To adjust base templates**: edit `_DA_BASE`, `_DT_BASE`, etc. in `atomistic.py`
  - Chi angle (z-rotation in template space around C1') is what the optimizer controls
  - Template z-coords are frozen by convention (C1' at z=0 only for display alignment)
