---
name: Crossover parameterization pipeline validation log
description: Running log of test results as we validate the pipeline end-to-end
type: project
originSessionId: 96f9c7f1-a2dc-42fd-ade8-1e21c39596f9
---
## Validation run: T0, 10 ns production, no sweep

**Date:** 2026-04-21  
**Command:** `python runs/crossover_parameterization/run_pipeline.py --variants T0 --prod-ns 10 --no-sweep`

### Setup phase ✅
- Design loaded: 2hb_xover_val.nadoc — 2 helices, 5 strands, 4 crossovers
- Sequences assigned: seed=42, GC=51% on both scaffolds
- PDB exported: T0/structure.pdb (2852 ATOM records)
- GROMACS setup: amber99sb-ildn (charmm36 not installed locally)
- Solvation: TIP3P + NaCl 150 mM — completed
- POSRES_TERMINAL injected into 5 chain ITPs, 15 P atoms total
- **Bugs fixed during setup:**
  - GC% log: operator precedence (100*G + 100*C/n → 100*(G+C)/n)
  - PDB double-nesting: T0/T0/ → T0/ (pass parent dir to generate_variant_pdb)
  - Restraint injection: was using global atom indices at system level; fixed to local indices inside moleculetype blocks
  - grompp: missing -r flag for POSRES reference coords

### grompp validation ✅
- EM grompp: passed, no errors, no warnings
- NVT/NPT/production grompp: NOT YET VALIDATED (run.sh handles these)

### Simulation ✅ COMPLETE (2026-04-21, restarted with triclinic box)
- EM ✅ → NVT ✅ (220 ns/day) → NPT ✅ (231 ns/day) → production ✅ (257 ns/day, ~56 min)
- System: 41304 atoms, 4.4×6.7×14.4 nm triclinic box (was 360k atoms cubic → 8.6× speedup)
- GPU: EM_GPU=-nb gpu; MD_GPU=-nb gpu -pme gpu -bonded gpu (PME GPU unsupported for steep integrator)

### Bug 6 fix ✅
- Chain E (central crossover staple, 42 residues) had POSRES_TERMINAL on resids 41-42 (MEASUREMENT REGION)
- Fix: md_setup.py now computes max_residues=max(scaffold chain lengths), skips longer chains
- Corrected restrained atom count: 12 P atoms on chains A, B, C, D (3 each; chain E = 0)

### Parameter extraction ✅ COMPLETE
- Bugs fixed during extraction:
  - Chain selection: chain E (42 res) was beating scaffolds (35 res); fixed to "paired chains" (longest length appearing ≥ 2×)
  - Measurement bp range: constants 15,33 were global bp numbers used as local 0-based indices; fixed to 8,26
  - Axis sign: PCA sign inconsistent across frames → q-vector means near zero; fixed by anchoring to frame-0 axis
  - r0: was q_mean[0] (axial ≈ 0 for parallel helices); fixed to Euclidean |q_mean[:3]|
- Final T0 parameters: r0=25.33 Å, k_bond=2.060 kJ/mol/Å², hj_angle=-82.5°, k_dihedral=1.588 kJ/mol/rad²
- Off-diagonal coupling: 0.38 (expected for DNA stretch-twist coupling)
- Convergence: PASSED (501 frames; 10 ns short but ESS threshold met)
- Output: T0/params.json, T0/convergence_report.json

### Known issues / next steps
- Force field is amber99sb-ildn, NOT charmm36 — need to install charmm36 or validate AMBER is acceptable
- hj_angle=-82.5° needs physical interpretation vs known DX junction geometry
- 10 ns too short for angular DOF convergence; real runs need 200 ns
- Off-diagonal coupling 0.38: diagonal-only mrdna injection misses stretch-twist coupling; acceptable for initial validation
- Next: run full 200 ns T0, then T1 and T2 variants
