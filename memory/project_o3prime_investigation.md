---
name: O3' inter-residue geometry — root cause and fix path
description: Investigation of why C3'-O3'-P angle is 93.60° instead of 119.35°, what doesn't work, and what the correct fix is
type: project
originSessionId: be1b56df-f448-4499-aef3-747e18428bd8
---
## Problem (2026-04-14)

Inter-residue tetrahedral geometry at phosphate is wrong:
- C3'–O3'–P = **93.60°** (1zew target: 119.35°)
- O3'–P–OP1 = **147.53°** (target ~109°)
- O3'–P–OP2 = **89.10°** (target ~108°)
- O3'–P–O5' = **76.76°** (target ~105°)
- O3'–P distance = **1.653 Å** (target 1.607 Å — close)
- ε torsion (C4'–C3'–O3'–P) = **95.01°** (1zew: 97.84° — approximately correct)
- Intra-residue geometry: all correct (C3'–O3' = 1.42 Å, C4'–C3'–O3' = 109.1°, etc.)

## What Was Tried (Doesn't Work)

1. **O3' sweep around C4'–C3' axis**: Best achievable RMS = 49.18° — IMPOSSIBLE to fix by repositioning O3' alone (preserving intra-residue bond/angle). See `scripts/fix_o3prime.py`.

2. **Method C (linear solve for ideal O3')**: Requires O3' at z=+0.0308 (5' side of C3') — impossible, breaks intra-residue topology.

3. **Decrease P_RADIUS 0.971→0.928**: Made angle WORSE (85.86°, not better). Rate: ~180°/nm. To fix from 93.60° to 119.35° by P_RADIUS alone requires P_RADIUS ≈ 1.114 nm — outside HELIX_RADIUS and physically unreasonable.

4. **Azimuth correction (`_ATOMISTIC_AZIMUTH_RAD`)**: Analytically proven to NOT affect C3'–O3'–P (both C3' and O3' rotate identically around helix axis, so angular relationship to P is preserved).

5. **`_ATOMISTIC_AXIAL_CORR` / `_FRAME_SHIFT_Z`**: Also invariant — they shift all residues equally so the inter-residue axial separation doesn't change.

## Root Cause

The template coordinates in `_SUGAR` were extracted from 1zew.pdb using `pdb_import.py:compute_nucleotide_frame` (origin = P atom, e_n = partner_C1'→self_C1'). A **C1'→z=0 shift** was then applied (shifting all z coords by +0.2712 so C1' lands at z=0).

The calibration (`scripts/calibrate_pdb.py` → `calibrate_from_pdb`) derives FRAME_SHIFT_{N,Y,Z} as the offset from the corrected backbone bead to **P_pdb** (not to the shifted origin). This means:

- `_atom_frame()` origin ≈ P_pdb (from calibration)  
- But the template has P at z=+0.2712, so P world = origin − 0.2712·axis_tangent

**The calibration is mis-targeted.** The frame origin should be at P_pdb + 0.2712·axis_tangent (= 0.2712 nm toward 3' from P, the C1' axial level). The calibration currently puts origin AT P_pdb, so NADOC places its P atom 0.2712 nm displaced from the crystallographic P.

Consequently, consecutive residues' frames don't step in a way that produces correct inter-residue O3'→P geometry. The ε torsion is approximately right (azimuthal), but the C3'–O3'–P opening angle is ~25° too small because P(N+1) in world space is not where the crystallographic structure expects it.

## Correct Fix: Template Re-Extraction

Re-extract ALL template coordinates from 1zew.pdb using NADOC's ACTUAL `_atom_frame()` geometry (including current P_RADIUS, FRAME_SHIFT_*, azimuth correction). Steps:

1. Build a synthetic NADOC helix matched to 1zew's geometry (as `calibrate_from_pdb` does).
2. For each inner PDB residue N, call `_atom_frame(nuc_pos, dir, axis_pt)` to get (origin_N, R_N).
3. Kabsch-align the PDB structure to NADOC's coordinate frame (or use the same helix axis).
4. Express PDB atom world positions in NADOC's frame: `local = R_N.T @ (PDB_world - origin_N)`.
5. Apply the C1'→z=0 shift consistently across the newly extracted coords.
6. Average across inner residues to get new template values.
7. Also fix `calibrate_from_pdb` to target `P_pdb + 0.2712·axis_tangent` (not `P_pdb`).

This guarantees O3'(N) and P(N+1) land at their crystallographic positions when placed by consecutive calls to `_atom_frame()`, giving exact inter-residue geometry.

## Why It Must Be Re-Extraction (Not Parameter Tuning)

The inter-residue geometry depends on the RELATIVE placement of frame(N) vs frame(N+1). No single parameter (P_RADIUS, FRAME_SHIFT, azimuth) can fix this because they all act identically on each residue and cancel in the frame-to-frame difference. Only the template coordinates themselves encode where O3'(N) sits relative to where frame(N+1) places P.

## Diagnostic Script

`scripts/fix_o3prime.py` — connects to live API, creates a 21-bp helix at (1,1), queries atomistic model, measures all angles. Documents the current failure mode and sweeps show impossibility of fixing O3' alone.

## How to Apply

Next session: write a new script `scripts/reextract_templates.py` that:
- Uses `calibrate_from_pdb` to build the synthetic NADOC helix from 1zew  
- Calls `_atom_frame()` for each residue (requires importing _atom_frame as-is)  
- Uses Kabsch SVD to align 1zew atoms into NADOC frame  
- Outputs `_SUGAR` and `_D?_BASE` tuples as Python source for copy-paste into `atomistic.py`  
- Also outputs corrected `FRAME_SHIFT_Z` that targets the right origin (P + 0.2712·axis_tangent shift)
