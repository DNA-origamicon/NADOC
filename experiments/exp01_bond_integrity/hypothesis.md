# Exp01 — Bond Integrity Hypothesis

## System
42 bp single duplex helix along +Z, standard B-DNA geometry.

## Setup
- Build ideal geometric positions (t=0).
- Perturb all backbone bead positions by uniform ±0.5 nm on each axis.
- Relax with 100 calls to `xpbd_step(sim, n_substeps=20)`, noise_amplitude=0, bond_stiffness=1.0.

## Hypothesis
After relaxation, all backbone bond lengths should recover to within ±0.05 nm of their
rest lengths (BACKBONE_BOND_LENGTH ≈ 0.678 nm). Specifically:

- **mean bond length** at t=final should be within 0.01 nm of the t=0 mean.
- **max deviation** from rest length at t=final should be < 0.05 nm.

## Rationale
This is the foundational constraint-solver correctness test. A ±0.5 nm perturbation
is large relative to the bond rest length (~74%), so if XPBD recovers cleanly it
demonstrates that the constraint projection is robust to large displacements.
If bonds do not converge, no downstream physics is trustworthy.
