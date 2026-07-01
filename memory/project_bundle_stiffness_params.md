---
name: Bundle inter-helix stiffness parameter database
description: Extracted 6-DOF inter-helix stiffness values (0T complete, 1T pending), file location, gaps, and physical interpretation
type: project
originSessionId: 85e914a3-d5e4-4a02-abe8-93dbd35a351b
---
## Parameter database location

`backend/data/parameters/bundle_stiffness.json`

Schema: entries indexed by (crossover_type × context), each with K_matrix, K_diagonal, equilibrium geometry (from per-pair means), ESS, provenance.

---

## 0T crossovers (standard DX, no extra bases) — COMPLETE as of 2026-04-30

Source: 10hb.nadoc, 304 ns production, 310 K, 150 mM NaCl, CHARMM36.
All contexts converged (ESS ≥ 208 for all DOFs).

| Context | n_pairs | ESS_min | K_axial | K_lat1 | K_lat2 | K_tilt | d_cc |
|---------|---------|---------|---------|--------|--------|--------|------|
| 2-2 | 6 | 1233 | 0.069 | 0.010 | 0.011 | 76.9 | 20.8±1.9 Å |
| 2-3 | 4 | 824  | 0.227 | 0.030 | 0.085 | 215.5 | 21.1±3.5 Å |
| 3-3 | 1 | 208  | 0.501 | 0.482 | 0.438 | 985.1 | 24.0±0.0 Å |

K_axial / K_lat units: kJ/mol/Å². K_tilt units: kJ/mol/rad². K_alpha/K_gamma (q3, q5) are gimbal-locked and unreliable — do not use.

**Physical interpretation:**
- Stiffness increases ~3–13× per context level (2-2 → 2-3 → 3-3)
- 3-3 lateral stiffness is ~45× larger than 2-2: interior helices are tightly constrained by 3 crossover connections per neighbor
- Lateral stiffness is isotropic in 3-3 (0.48 ≈ 0.44) but anisotropic in 2-3 (0.030 vs 0.085) — asymmetric crossover pattern in 2-3 context
- Equilibrium tilt angles (7–12°) are non-trivial; helices genuinely tilt in MD relative to design geometry
- Design center-to-center = 22.5 Å; MD mean = 20–24 Å (context-dependent)

**Why:** The number of crossover connections per pair determines constraint density.
**How to apply:** Use context label (neighbor counts of both helices) to look up K.
For FEM integration: convert K_lat [kJ/mol/Å²] → [pN/nm] × 0.001 / (N_A * 10^-20) or use 1 kJ/mol/Å² = 16.61 pN/nm.

---

## 1T crossovers — ABANDONED (2026-05-06)

Source: 3NN_opt2.nadoc. Run was stopped at 141/300 ns (47%) and will not be completed.
Decision: not worth completing; B_tube full MD is the priority.
Checkpoint at `runs/3NN_opt2_bundle_params/nominal/prod.cpt` (step 70,509,600).

---

## Known gaps and open questions

1. **FEM integration not yet done.** The fem_solver.py still uses Castro et al. hardcoded
   values (EA=1100 pN, EI=230 pN·nm²). The per-context K matrix from MD is not yet wired in.
   Mapping: K_diagonal[q1]/[q2] (lateral) ≈ crossover spring k_trans; K_diagonal[q4] (tilt)
   ≈ bending stiffness for rotational springs.

2. **Gimbal-lock fix not implemented.** K_alpha (q3) and K_gamma (q5) are unreliable due
   to Euler ZYZ degeneracy at small tilt. Need axis-angle or quaternion representation.

3. **Crossover centroid bias not fixed.** Crossover residues pull helix centroids inward
   (~11 Å from axis). Pairs with lat < 12 Å in all_pairs.json should be flagged unreliable.
   Fix: exclude crossover-bp positions from centroid in _interhelix_q.

4. **2T, 3T crossovers not yet parameterized.** Would complete the T-count sweep.

5. **Castro et al. validation not done.** No comparison between MD-derived K and FEM
   predictions from helix geometry. Needed to validate FEM model.

6. **Single 3-3 pair in 0T.** 10hb has only 1 3-3 pair (h_XY_1_1 ↔ h_XY_0_1).
   ESS=208 is at the margin. 3NN_opt2 will give 5 3-3 pairs for 1T, providing much
   better 3-3 statistics.
