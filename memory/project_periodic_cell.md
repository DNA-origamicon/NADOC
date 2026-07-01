---
name: NAMD periodic unit cell pipeline
description: backend/core/periodic_cell.py — 21 bp periodic cell for B_tube; all failure modes and fixes documented
type: project
originSessionId: 9c9be7c6-98b4-42c3-a595-eb7159ceae86
---
## Summary

`backend/core/periodic_cell.py` — builds a 1-period (21 bp) periodic unit cell package for honeycomb DNA origami.
`backend/core/namd_solvate.py` — provides `_render_periodic_namd_conf` and `_gmx_solvate_periodic`.

**Public API:**
```python
build_periodic_cell_package(design, *, n_periods=1, padding_nm=1.2, ion_conc_mM=150.0, bp_start=None) -> bytes
get_periodic_cell_stats(design, *, n_periods=1, ...) -> dict
```

## B_tube results (exp23)

- Design: B_tube.nadoc, 24 helices × 21 bp slice, bp range [21, 42)
- Total atoms: **165,524** (vs 2.46M full solvated)
- Wrap bonds: 4 O3'→P pairs at z-boundary
- Box: ~161 × 157 × 70 Å
- **Benchmark: 18.87 ns/day** (NAMD3 standard CUDA, RTX 2080 SUPER)
- Reference: GROMACS vacuum PME 8.40 ns/day; NAMD GBIS 2.36 ns/day

## Critical failure modes and fixes

### 1. PSF atom count misread (PSF !NATOM field width)
**Symptom:** "FATAL ERROR: Number of pdb and psf atoms are not the same!" despite Python grep showing equal counts.
**Cause:** Without `PSF EXT` in the header, NAMD reads !NATOM using an 8-char field.
A 10-char formatted count like `"    161540 !NATOM"` is read as `"    1615"` → NAMD thinks 1615 atoms.
**Fix:**
- Add `PSF EXT` to the PSF header line in `pdb_export.py:export_psf`
- Format !NATOM count as 8-char: `f"{len(atoms):>8d} !NATOM"` (not 10-char)

### 2. PDB serial ≥ 10000 causes NAMD to discard records
**Symptom:** Same as above — count mismatch even when Python sees equal counts.
**Cause:** Empirically confirmed via binary search: when PDB serial ≥ 10000, the 5-digit number immediately follows "HETATM" with no leading space. NAMD's C PDB parser silently discards these records.
Binary search result: 9999 atoms → OK; 10002 atoms → MISMATCH at exact threshold.
**Fix:** Cap all PDB serials at 9999: `pdb_serial = (serial - 1) % 9999 + 1` in both
`_hetatm_record` (water/ions in `namd_solvate.py`) and `_pdb_atom_record` (DNA in `pdb_export.py`).
NAMD matches atoms by (segid, resid, atomname) not serial, so cycling is safe.

### 3. GPU-resident mode fails with wrap bonds
**Symptom:** "FATAL ERROR: Low global CUDA exclusion count! (196428 vs 196455)" — 27 missing exclusions.
**Cause:** `CUDASOAintegrate on` (GPU-resident) builds its exclusion list from pairlist distances (16 Å max).
Wrap bonds connect O3' at z_end to P at z_start — 70 Å apart in real space. GPU-resident mode cannot find those bonded partners and misses ~7 exclusion relations per wrap bond × 4 bonds = 27 missing.
**Fix:** Remove `CUDASOAintegrate on` from `_render_periodic_namd_conf`. Standard CUDA mode handles PBC-wrapped bonded exclusions correctly via the CPU bonded-force path.
**Impact:** ~15% speed penalty vs GPU-resident mode, but simulation is physically correct.

### 4. Simulation instability from solvation geometry clashes
**Symptom:** "Atoms moving too fast; simulation has become unstable" — velocities > 6000 Å/ps at step 1.
**Cause:** Benchmark script stripped the `minimize` line from the conf, starting MD directly from the raw solvated geometry (water placed by gmx solvate, not energy minimized).
**Fix:** `_patch_conf_for_bench` in `run.py` must add `minimize 500` + `reinitvels 310` before the benchmark `run` line. Production conf template already includes `minimize 2000`.

### 5. Water segment overflow at resid 9999
**Cause:** NAMD limits resid to 4 digits in standard PDB. >9999 water molecules in one segment causes resid rollover, confusing NAMD's atom matching.
**Fix:** Multi-segment water: `SOLV`, `SOL1`, `SOL2`, ... with ≤9000 residues per segment. Implemented via `_water_seg_info(water_index)` in `namd_solvate.py`.

## Physics notes

- **Production barostat: ISOTROPIC NPT** (`useFlexibleCell no`). Anisotropic NPT (`useFlexibleCell yes`) is fatal — it causes Z to expand from 70.14→93 Å in ~556 ps while XY contracts (total volume conserved but cell shape distorts). Why: the barostat scales atom coordinates proportionally when it rescales each axis; the initial rectangular cell (155×151×70) has different pressure along each axis, so the barostat makes the cell more square, expanding Z uncontrollably despite wrap bonds. Isotropic NPT scales all 3 axes by the same factor → Lz stays within 70.14 ± 0.25 Å, XY shrinks by ~0.3 Å (tiny initial overpadding).
- **`useConstantArea yes` is NOT "XY-free/Z-fixed"** — it fixes XY area and frees Z (the opposite). No standard NAMD keyword achieves XY-free/Z-fixed without COLVARS scripting.
- **Erban & Togashi semiisotropic requirement**: E&T say to use XY-flexible, Z-fixed NPT. NAMD cannot do this natively. Isotropic NPT is the practical substitute: since the system is near equilibrium density already, isotropic scaling produces ≪1 Å Lz drift — well within E&T's 0.5 Å threshold.
- **wrapNearest on**: Required because DNA strands span the z-boundary (O3' at one end, P at the other). Without this, PBC wrapping places them at image positions and VMD shows broken helices.
- **Wrap bonds and force field**: O3'→P wrap bonds are real covalent bonds in the PSF. For B_tube (24 helices × 21 bp), only 2 wrap bonds exist (DNAG:35:O3'→DNAB:1:P and DNAM:35:O3'→DNAH:1:P) — most strands already have backbone continuity via crossovers at the periodic boundary. Angles and dihedrals are auto-generated by `_complete_psf_from_stub` traversing the bond graph.

## Experiment

`experiments/exp23_periodic_cell_benchmark/` — build + benchmark script.
`experiments/exp23_periodic_cell_benchmark/results/` — zip, run directory, logs, summary.

**Why:** Full B_tube solvated = 2.46M atoms → OOM on 16 GB. 21 bp periodic cell = 165k atoms, 14× reduction, same bulk thermodynamics, no end-cap artifacts.
**How to apply:** Use `build_periodic_cell_package(design)` for any honeycomb design with a 21 bp crossover period. Verify `n_wrap_bonds == 4×n_helices` from `get_periodic_cell_stats`.
