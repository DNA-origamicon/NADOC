---
name: mrdna atomistic PDB cannot be used directly with GROMACS CHARMM27
description: mrdna's all-atom spline output has wrong bond geometry for CHARMM27, giving Fmax=inf and Epot>1e27
type: feedback
originSessionId: c428e99e-8e62-49bc-9619-c9563281a0f3
---
Do NOT attempt to run GROMACS EM on mrdna's all-atom spline-fit PDB (`*-fixed.pdb`) directly.

**Why:** mrdna's spline fit places atoms at positions optimized for the ARBD CG force field, not CHARMM27. Bond lengths are different → initial Epot=9×10^27 kJ/mol (vs ~10^12 for NADOC ideal B-DNA), Fmax=inf. EM halts at step 15 with "force on at least one atom is not finite."

**How to apply:** If someone wants to use mrdna output for GROMACS, the path is:
1. Use mrdna's DCD (CG positions) to extract helix axis geometry
2. Build all-atom coordinates via NADOC's template system (not mrdna's spline fit)
3. The `nuc_pos_override_from_mrdna` function is the intended bridge, but it also currently has issues (see session_handoff for details)

mrdna's native all-atom output is designed for NAMD (its own atomistic engine), not GROMACS.

**pdb2gmx conversion is possible but pointless** for all-atom output — it now works (serial overflow fixed, use `-ignh`, terminus `2=5'` and `4=3'` per chain) but the resulting EM fails anyway.
