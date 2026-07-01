---
name: SD EM supports h-bond constraints; L-BFGS does not
description: Reminder that the SD integrator in GROMACS EM can run with LINCS h-bond constraints
type: feedback
originSessionId: 850be451-9e2e-4b70-a3e8-bb898f34b034
---
The SD (stochastic dynamics / steepest descent in EM mode) integrator in GROMACS supports `constraints = h-bonds` with LINCS. L-BFGS does NOT support constraints.

**Why:** This distinction matters when backbone strain (e.g. skip sites) can drive aromatic X-H bonds into false minima during unconstrained EM. Using `constraints = h-bonds` in em.mdp with `integrator = sd` (or `integrator = steep`) pins X-H bond lengths throughout minimization, preventing divergence.

**How to apply:** If em.mdp uses `integrator = sd` (or steep), it is safe to add `constraints = h-bonds`. If it uses `integrator = l-bfgs`, constraints are not available — would need to switch integrators first.
