---
name: Crossover CG parameterization pipeline
description: New pipeline to derive mrdna CG potentials for non-standard crossover motifs from isolated atomistic MD
type: project
originSessionId: 96f9c7f1-a2dc-42fd-ade8-1e21c39596f9
---
Motivation: mrdna's CG potentials are parameterized for standard crossovers. Extra thymines at a crossover change local mechanics, so stripping and re-injecting was wrong. Correct approach: parameterize CG from isolated 2-crossover atomistic MD.

**Why:** Global shape of full-origami CG was biased because equilibrium was found for the wrong structure (T-stripped).

**How to apply:** Use 2hb_xover_val.nadoc as the parameterization system. Do NOT use the same trajectories for validation.

## Pipeline location
`backend/parameterization/` — 6 modules + `runs/crossover_parameterization/run_pipeline.py`

## Key design decisions
- Parameterization system: `Examples/2hb_xover_val.nadoc` — two antiparallel DX crossovers at bp 13-14 and 34-35, 20 bp inter-crossover measurement region, ~6 bp outer stubs
- NOT a dumbbell: paired crossovers needed to lock Holliday junction isoform
- Outer stubs: soft harmonic position restraints on terminal P atoms (k = 0.5, 1.0, 2.0 kcal/mol/Å² sweep). Open question: exact restraint model for origami-embedding
- Force field: CHARMM36-jul2022, TIP3P, NaCl ~150 mM
- First batch variants: T0 (baseline), T1, T2
- Sequences: random GC-balanced, seed=42

## Extraction status (as of 2026-04-30)

T0/nominal_c36: 200 ns production complete. T1/nominal: 185 ns. T2/nominal: 10 ns.

**CRITICAL FINDING:** The isolated 2hb system has τ ≈ 11 ns autocorrelation time.
ESS=9-90 for T0 at 200 ns. Need ~2 µs to reach ESS=100 via Method B.

Instead, use **Method A** (local junction extraction from 10hb bundle):
- Script: `runs/crossover_parameterization/extract_crossover_and_validate.py`
- Module: `backend/parameterization/local_crossover_extract.py`
- Key insight: bp-center (avg of both strand C1') at crossover bp position
  gives r0=19.03 Å — matches mrdna default 18.5 Å exactly.
- k_bond from 10hb interior crossovers (bp 1-40): context-dependent
  - 3-3 context: k ≈ 3-5 kJ/mol/Å² 
  - 2-2 context: k ≈ 0.1-0.9 kJ/mol/Å²
  - Pooled mean: 0.047 kJ/mol/Å²

**T1 r0 is a scaled estimate** (22.63 Å, scaled from T0 arm ratio). Replace with
3NN_opt2 bundle extraction when that run completes.

## Extracted parameter database

`backend/data/parameters/crossover_params.json` — T0 converged, T1 preliminary.
`CrossoverPotentialOverride.from_database("T0")` to load for mrdna injection.

## First run command (pipeline test)
```bash
cd runs/crossover_parameterization
python run_pipeline.py --variants T0 --prod-ns 10 --no-sweep
# After runs complete:
python run_pipeline.py --extract-only
```

## Module roles
1. `crossover_extract.py` — load design, assign sequences, T-count variants → PDB
2. `md_setup.py` — GROMACS solvation, restraint ITP, MDP files, run.sh
3. `param_extract.py` — MDAnalysis 6-DOF covariance → stiffness matrix → mrdna scalars
4. `convergence.py` — block averaging, ESS, running-mean diagnostics; GATES parameter emission
5. `mrdna_inject.py` — monkey-patches SegmentModel to override crossover bond/dihedral per type
6. `validation_stub.py` — placeholder; requires independent atomistic reference

## mrdna injection fragility
- Identifies crossover bonds by r0 ≈ 18.5 Å (±3.0 Å window)
- Identifies HJ dihedrals by angle proximity to hj_equilibrium_angle ± 0/180°
- Monkey-patches SegmentModel temporarily (NOT thread-safe)
- If mrdna crossover code changes, check segmentmodel.py lines 3314-3376
- Per-junction overrides (different T counts in same origami) not yet supported

## Critical rules
- NEVER use parameterization trajectories for validation
- ALWAYS run restraint sensitivity sweep before trusting parameters
- DO NOT extrapolate T=2 from T=1 and T=3 — simulate each independently
