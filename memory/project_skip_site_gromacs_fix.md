---
name: GROMACS NVT LINCS failure root cause and fix
description: Diagnosis and fix for NVT LINCS failures — applies to skip-site structures AND extra-T crossover structures in explicit solvent
type: project
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
Non-deformed exports with skip sites (delta=-1) OR solvated designs with extra-T crossover bases can both trigger LINCS failures during NVT.

**Why:** Both cases produce slightly non-ideal X-H bond geometry after EM (EM with `constraints=none` lets h-bond lengths drift; the extra-T crossover residue at residue 163 DT produced C5'-H5' = 1.12 Å instead of 1.09 Å). When NVT starts with either: (a) gen-vel=yes at 310K (kinetic energy shock), or (b) continuation=no at high temperature, LINCS must apply a large h-bond correction on top of randomly directed 310K velocities. This causes a resonance explosion — in 3NN_opt2 (solvated, 16hb, extra-T), atom C5'-H5' at residue 163 DT exploded to 19.9 Å at t=16 ps (step 8028).

**Root cause chain (solvated extra-T case):**
1. `constraints = none` in em.mdp → EM lets C5'-H5' drift to ~1.12 Å (target 1.09 Å).
2. NVT with `gen-vel = yes, gen-temp = 310` → kinetic energy shock. POSRES keeps heavy DNA atoms in place but LINCS must correct the ~0.03 nm h-bond overshoot in the presence of 310K random velocities.
3. Resonance builds over ~8000 steps and explodes at t=16 ps.

**Root cause chain (vacuum skip-site case, documented earlier):**
1. `constraints = none` in em.mdp → C2-H2 adenine bonds near skip sites stretch to ~2.5 Å.
2. LINCS in NVT must correct 1.4 Å — matrix near-singular → catastrophic displacements at step 0.

**Fix (applies to both cases):**
- **em.mdp**: Add `constraints = h-bonds`, `constraint-algorithm = LINCS`, `lincs-iter = 2`, `lincs-order = 4`. Steep EM supports LINCS (L-BFGS does not). After constrained EM, all X-H bonds are at their constraint target lengths.
- **nvt.mdp**: Set `gen-temp = 0.0` (not 310), `dt = 0.001` (not 0.002), add simulated annealing `0→100→310 K` over 20 ps. Zero initial kinetic energy + annealing ramp prevents LINCS from seeing a large correction + large velocity at t=0.
- Keep `gen-vel = yes` (needed to initialise velocities from scratch); just change `gen-temp`.

**Test result (3NN_opt2, solvated, 421k atoms, extra-T at 76 crossovers):**
- EM: 8851 steps, converged to machine precision (Fmax=7185 on crossover atom — expected for constrained crossover geometry).
- NVT: 50000 steps (50 ps), zero LINCS warnings, completed cleanly.

**Note on Fmax after EM:** The extra-T crossover residue sits in a geometrically constrained environment; Fmax never drops below ~5000–7000 kJ/mol/nm regardless of EM steps. This is expected and not a problem — constrained EM ensures h-bond lengths are correct, which is what matters for NVT stability.

**gromacs_package.py coverage:**
- Skip-site vacuum path: `_has_skips` block sets `dt=0.001`, simulated annealing. Does NOT yet add `constraints=h-bonds` to em.mdp for the vacuum path (the template comment warns of LINCS warnings from crossover terminal O3'/O5' atoms — that specific case needs further testing before changing the template).
- Solvated extra-T path: currently NOT handled by `_has_skips` (delta=+1 not ≤-1). If future runs show the same pattern, add a `_has_extra_t` flag alongside `_has_skips`.
