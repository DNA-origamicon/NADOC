---
name: NAMD explicit-solvent solvation pipeline
description: backend/core/namd_solvate.py — automated TIP3P solvation + PSF merge + NAMD GPU-resident package builder
type: project
originSessionId: 9c9be7c6-98b4-42c3-a595-eb7159ceae86
---
## Summary

`backend/core/namd_solvate.py` — fully automated NAMD explicit-solvent package builder.

**Public API:**
```python
build_namd_solvated_package(design, *, padding_nm=1.2, ion_conc_mM=150.0) -> bytes
get_solvation_stats(design, *, padding_nm=1.2, ion_conc_mM=150.0) -> dict
```

## Pipeline

1. `export_pdb(design)` → DNA heavy-atom PDB (Angstroms, CHARMM36 naming)
2. `complete_psf(design)` → full PSF with angles/dihedrals (from namd_package)
3. `gmx editconf -bt triclinic -d {padding_nm}` → rectangular box GRO
4. `gmx solvate -cs spc216.gro` → TIP3P water placed around DNA
5. Parse solvated GRO → list of `_Water(ox,oy,oz,h1x,h1y,h1z,h2x,h2y,h2z)` in nm
6. Count DNA charge from P atoms in PDB (not PSF partial charges — those don't sum right without H)
7. Python ion placement: replace random water molecules with Na+/Cl-
8. `_extend_psf` → append TIP3/SOD/CLA atoms to NATOM section; add bonds/angles to NBOND/NTHETA
9. `_build_solvated_pdb` → DNA ATOM records + water/ion HETATM records with updated CRYST1
10. NAMD conf with `CUDASOAintegrate on`, PME, NPT 310K/1atm, `rigidBonds water`, 2 fs timestep

## Physics choices

- **CUDASOAintegrate on**: GPU-resident MD (fastest NAMD3 mode, requires explicit solvent + PME)
- **PME**: `PMEGridSpacing 1.0`
- **rigidBonds water**: SHAKE on O-H bonds allows 2 fs timestep
- **NPT**: Langevin piston, 1 atm
- **NaCl**: 150 mM default (configurable), Na+ used to neutralize DNA charge first

## Ion parameters (CHARMM36 / toppar_water_ions_cufix.str)

| Species | CHARMM type | charge | mass |
|---------|-------------|--------|------|
| TIP3/OH2 | OT | -0.834 | 15.999 |
| TIP3/H1,H2 | HT | +0.417 | 1.008 |
| SOD (Na+) | SOD | +1.00 | 22.990 |
| CLA (Cl-) | CLA | -1.00 | 35.450 |

## PSF segment naming

- DNA strands: `DNAA`, `DNAB`, ... (from pdb_export.py)
- Water: segment `SOLV`, resname `TIP3`
- Ions: segment `IONS`, resname `SOD` or `CLA`

## Critical bugs fixed during development

1. **`-bt rectangular` is invalid** — use `-bt triclinic` for editconf
2. **GRO residue number wraparound**: GROMACS wraps residue/atom numbers at 100,000. Parsing by `resnum` dict gives only 100,000 waters. Fix: sequential parsing — buffer atoms in `sol_buf`, emit when len==3.
3. **Unit conversion error in ion count**: `1 nm³ = 1e-24 L` (not `1e-21 L`). `vol_L = bx*by*bz * 1e-24`.
4. **DNA charge from heavy-atom PSF is wrong**: partial charges without H don't sum to physical -1/nt. Fix: count P atoms in PDB → `-n_P` = real DNA net charge.

## Validated results (y4HB, 4 helices, 6816 DNA atoms)

- 31,771 TIP3P water molecules (95,313 atoms)
- 434 Na+, 98 Cl- at 150 mM NaCl (for 150 mM bulk + neutralization of ~334 phosphates)
- Total: 102,661 atoms
- Build time: ~0.8 s
- PSF NATOM == PDB total atoms ✓

**Why:** Needed automated solvation for NAMD GPU-resident (CUDASOAintegrate) benchmarks. GBIS implicit solvent disables GPU PME offload; CUDASOAintegrate requires explicit solvent + PME.

**How to apply:** Use `build_namd_solvated_package(design)` to get a ZIP for NAMD3 GPU-resident simulation. For B_tube, expect ~2.5M atom system (~16×16×105 nm box). Full ZIP build may take 30-120 s; use `get_solvation_stats()` for quick size estimates.
