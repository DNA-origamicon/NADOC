---
name: NAMD PDB serial number limit at 9999
description: NAMD's PDB parser silently discards records with 5-digit serials (≥10000), causing atom count mismatches
type: feedback
originSessionId: 9c9be7c6-98b4-42c3-a595-eb7159ceae86
---
Cap all PDB serial numbers at 9999 in any NAMD-targeted PDB writer using:
`pdb_serial = (serial - 1) % 9999 + 1`

Apply this in both DNA atom records and water/ion HETATM records.

**Why:** When a PDB serial ≥ 10000 is formatted as a 5-digit number (no leading space), the record becomes e.g. `HETATM10000 OH2 ...` — NAMD's C PDB parser sees no space between record type and serial and silently discards the record. Python's `grep -cE '^(ATOM|HETATM)'` counts it fine, but NAMD's internal atom count is lower than the PSF count → "FATAL ERROR: Number of pdb and psf atoms are not the same!" Empirically confirmed via binary search: exactly at the 10000 boundary.

NAMD matches atoms by `(segid, resid, atomname)` tuple, not serial number — so cycling serials within 1–9999 is safe. The serial field is only used for display/bonds in PDB format.

**How to apply:** Any time building a PDB file for NAMD with >9999 atoms, cycle serials. This is already implemented in `namd_solvate.py:_hetatm_record` and `pdb_export.py:_pdb_atom_record`. Do NOT remove this cap if refactoring those functions.
