---
name: NAMD anisotropic NPT fails for periodic axial cells
description: useFlexibleCell yes causes Z runaway for rectangular DNA axial-PBC cells; use isotropic NPT instead
type: feedback
originSessionId: 85365772-ce9b-40f9-939f-8ce7c896b9c5
---
Never use `useFlexibleCell yes` (anisotropic NPT) for NAMD axial-periodic DNA cells with a non-square XY cross-section.

**Why:** The barostat scales atom coordinates proportionally when it rescales each axis independently. A rectangular initial cell (e.g., 155×151×70 Å for B_tube) has unequal pressure along X, Y, Z. The barostat contracts XY and expands Z until the cell becomes approximately square, while total volume stays conserved. This destroys the periodic Lz constraint. Observed: Z expanded 70.14 → 93 Å in 556 ps, completely unphysical even with 2 O3'→P wrap bonds.

**How to apply:** Use `useFlexibleCell no` (isotropic NPT) for production. The initial cell volume is already near bulk density (solvated by GMX), so isotropic scaling keeps Lz within ±0.25 Å of design value. This is within Erban & Togashi's ±0.5 Å acceptance criterion and avoids the cell distortion problem entirely.

Also: `useConstantArea yes` is NOT "XY-free, Z-fixed" — it is the opposite (Z-free, XY-fixed). NAMD has no built-in XY-free/Z-fixed mode without COLVARS.
