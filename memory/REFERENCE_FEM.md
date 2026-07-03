---
name: REFERENCE_FEM
description: FEM analysis theory + xpbd notes (DERELICT — both archived 2026-05-10). Reference only for revival planning.
type: project
originSessionId: 0f03295e-0d56-4711-b877-76c393d9521b
---
## REVIVAL IN PROGRESS (2026-07-02) — see [[project_cando_fem]]
The FEM is being revived as a native **CanDo-replica** shape predictor (twist/
curvature/RMSF, 1-to-1 within tolerance, zero export). Phase 0 research is DONE
(**GO w/ conditions**); the full method spec, reference-data path, and phase plan
live in `project_cando_fem.md`. Key corrections to the notes below: CanDo has **NO
twist-stretch coupling** (don't add it); RMSF uses **200 modes @ 298 K** (not 30);
the real solver is **geometrically NONLINEAR** (archived linear solve can't reach
90° bends). The constants below (1100/230/460) are CONFIRMED correct.

## DERELICT (2026-05-10)
**Both FEM solver and XPBD physics were archived to `archive/physics_xpbd_fem/` per user 2026-05-10.** Neither feature ever reached working-as-intended state:
- FEM: equilibrium overlay was disabled (u=0 trivially) pending torsional pre-stress that was never implemented; RMSF outputs did not match published references; beam parameters never calibrated against B-DNA stiffness measurements.
- XPBD: did not converge on representative designs (slow + non-converging); fast variant had unfixed `Crossover` model divergence (read removed `xover.strand_a_id` / `domain_a_index`).

The notes below are preserved as a *reference for revival planning* only. They describe what was attempted, not what is currently live. Do not consult these as if they describe live behavior.

## Status (final, before archive 2026-05-10)
- RMSF heatmap: was wired up but outputs not validated against literature
- Equilibrium shape overlay: disabled (u=0 trivially) — pending torsional pre-stress that was never implemented

## Model: Euler-Bernoulli Beam FEM
```
Beam elements:     EA=1100, EI=230, GJ=460  pN·nm units
Inter-helix springs: k=1e6 (rigid penalty for duplexed regions)
                     WLC spring (k << K_PENALTY, ssDNA extra-base regions)
RMSF:              shift-invert eigsh(σ=0, N_RMSF_MODES=30)
BC:                centroid-pinned (avoids cantilever RMSF artifact)
```

## Root Cause of Disabled Equilibrium Overlay
The original implementation had a physically wrong force term. The correct interpretation is that inter-helix constraints enforce **zero relative displacement** (captured by K matrix alone). No force term should be derived from axis-to-axis distance.

## Priority 1: Torsional Pre-stress (makes equilibrium overlay meaningful)

DNA origami helices are under/over-wound relative to B-DNA preferred 10.5 bp/turn. This creates torsional pre-stress that drives global curvature/twisting (the phenomenon CanDo was built to predict).

### Implementation Plan
For each domain segment:
```python
n_bp = domain length in base pairs
θ_natural = n_bp * (2π / 10.5)                    # B-DNA preferred twist
θ_actual  = n_bp * twist_per_bp_rad_of_helix       # actual twist (HC: 34.3°/bp)
Δθ = θ_actual - θ_natural                          # mismatch
M  = GJ * Δθ / L                                   # torsional moment
f[di+5] += M;  f[dj+5] -= M                        # θ_z DOF (beam torsion)
```

### References
- Castro et al. Nature Methods 8, 221 (2011) supplementary — torsional pre-stress equations
- Kim et al. Nucleic Acids Research 40(7), 2862 (2012) — CanDo FEM validation

## Priority 2: Helix-Axis Rotation in deformed_positions
Currently applies only translational displacement. For large rotational DOF displacements, backbone beads should also be rotated around the deformed axis.

## Priority 3: Better RMSF Discrimination
Currently: terminal vs interior nodes have similar RMSF values.
Options: increase N_RMSF_MODES (currently 30), different normalization.

## Priority 4: Per-domain Twist Visualization
Show twist mismatch (Δθ) per domain as a color overlay distinct from RMSF heatmap.

## Key Files
- `backend/physics/fem_solver.py` — stiffness assembly, RMSF eigsh, force vector `f`
- `frontend/src/physics/fem_client.js` — WebSocket `/ws/fem`, progress bar
- `tests/test_fem_validation.py` — FEM validation suite (275 lines)
