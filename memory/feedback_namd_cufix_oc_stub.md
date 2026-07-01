---
name: namd-cufix-oc-stub
description: NAMD3 fatal error with MGH (Mg-hexahydrate) — OC/NH3/OG2P1 vdW parameters missing from cufix NBFIX
metadata: 
  node_type: memory
  type: feedback
  originSessionId: baf07637-75d1-45c3-9ad6-60ff363faf17
---

NAMD3 exits with "DIDN'T FIND vdW PARAMETER FOR ATOM TYPE OC" (and OG2P1, NH3, etc.)
when simulating DNA+water+**MGH** (Mg-hexahydrate) with only `par_all36_na.prm` +
`toppar_water_ions_cufix.str`.

**Why:** NAMD validates ALL NBFIX pairs where either member is in the PSF. `toppar_water_ions_cufix.str`
has NBFIX entries for protein/lipid types (`OC`, `OCL`, `OG2D2`, `OC2D2`, `O2L`, `OG2P1`,
`OC2DP`, `NH3`, `NH3L`, `NC2`, `NG3P3`, `NP`, `NR3`) paired with `OTMG`/`OTCA`/ions. These
types come from protein/lipid force fields not loaded in DNA-only runs. With bare Mg²⁺ (no MGH)
NAMD never checks — but with MGH, `OTMG` is in the PSF so NAMD demands all its NBFIX partners
be defined.

**Fix:** `backend/data/forcefield/par_stub_ions_nbfix.str` — defines NONBONDED stubs for all 13
missing types with standard CHARMM36 protein/lipid values. None of these atoms ever appear in a
DNA+water+Mg simulation so the values don't affect physics.

**How to apply:** This file is in `_FF_FILES` in `namd_solvate.py` and is added as
`parameters forcefield/par_stub_ions_nbfix.str` in both the solvation conf template
(`namd_solvate.py`) and the segment conf template (`md_protocols.py` → `_common_header`).
Any time a new NAMD conf template is written for MGH systems, include this file.

Missing types (as of CHARMM36 cufix version in use): OC, OCL, OG2D2, OC2D2, O2L, OG2P1, OC2DP, NH3, NH3L, NC2, NG3P3, NP, NR3.
