# oxDNA physics implementation — 2026-09-14

The numerical corrections from the [A/B audit](oxdna_physics_ab_2026-09-13.md) are installed locally as `8028cf33b3cba12992b771156085fa54879f50cd-adaptive-memory-physics-v3`. GPU is the explicitly requested default for MD; Monte Carlo preparation remains CPU. Code comments record that further convergence and sampling checks are required (TD-OXDNA-PHYSICS).

## Delivered behavior

- CPU/CUDA Bussi use measured current kinetic energy at each update. Bussi remains the default relaxation thermostat.
- John/Brownian and Langevin no longer assign fictitious angular momentum to protein point particles. CUDA sorting and random-draw order are preserved.
- CUDA guards normalization of an exactly zero stacking-torque cross product, preventing the ideal-DNA startup NaNs reproduced in the audit.
- Ordinary DNA2 jobs carry the pinned upstream equal-strength parameter file, providing the same average model to both backends. Each job retains its own copy; remote inputs reference the uploaded copy. DNANM keeps its existing parameter initialization.
- Stage settings expose thermostat, explicit positive diffusion for local baths, force caps, and velocity refresh. Invalid local-bath settings prevent creation. Existing cap and velocity-refresh defaults are retained.
- Fixed gold/strep/DNA is accepted on GPU while preserving external attachment/exclusion forces, absolute coordinates, and MD timestep at most 0.0001. The wizard preview follows these constraints.
- Local, Alpine, and RunPod builders apply the v3 patch and invalidate old markers. Older local engines cannot start new runs. The local engine and oxpy bindings were rebuilt. Remote build/submission checks were tested, but no remote build or additional cloud spending occurred in this implementation pass.

Protein–DNA contact amplitudes remain native (CPU 1, CUDA 2). Selecting an amplitude was deferred pending upstream or relevant experimental evidence. These builds therefore do **not** establish CPU/GPU equivalence for interacting protein–DNA systems.

## Native corrective checks

The [validation script](../../scripts/validation/validate_oxdna_physics_v3.py) compares the frozen v2 baseline with installed v3, sequentially on the same machine (RTX 2080 SUPER for CUDA).

| Check | Before | Installed v3 |
| --- | --- | --- |
| Vanishing-coupling Bussi limit, CPU/CUDA | Approximately −50% kinetic-energy change | Approximately −0.00013%; passes the <0.1% bound |
| Raw ideal DNA, CUDA edge and non-edge | Nonfinite output/failure | Both produce finite configurations at the requested final step |
| Point angular momentum, CPU/CUDA John and Langevin, including CUDA sorting | Fictitious point rotations | Exactly zero; force-free physical positions/velocities unchanged in all six controls |

### Paired throughput

Twelve randomized pairs per row: 72 pairs / 144 timing runs. Ratios are v3/v2 wall time, with 95% Student-t intervals on paired log ratios. DNA inputs use the explicit average file in both arms. Timing runs are serial and do not overlap builds or other validation simulations.

| Input | Bath | Backend | Time ratio | 95% interval |
| --- | --- | --- | --- | --- |
| biotin10 | Bussi | CPU | 1.0004 | 0.9786–1.0228 |
| biotin10 | Bussi | CUDA | 0.9964 | 0.9798–1.0133 |
| biotin10 | John | CPU | 0.9946 | 0.9818–1.0075 |
| biotin10 | John | CUDA | 1.0071 | 0.9888–1.0258 |
| DNA | Bussi | CPU | 0.9820 | 0.9693–0.9949 |
| DNA | Bussi | CUDA | 1.0192 | 0.9953–1.0436 |

No comparison resolves a slowdown: none has its lower confidence bound above 1. Every upper bound is below the 5% resolution target. This is neither permission for a slowdown nor proof of zero overhead. Independent useful samples per unit time and time to equilibrium remain unvalidated.

## Application verification

Frontend: 139 tests passed after the final wizard changes. Backend: the broad focused run passed 305 tests with one outdated engine-signature mock failure; after fixing that mock, all 63 tests in the final focused rerun passed, including native full gold/strep/DNA CPU and CUDA execution. The earlier protocol-only set passed 32 tests. Ruff and `git diff --check` passed.

Final Playwright: **3 passed in 2.4 minutes**, using isolated application servers and one browser worker:

1. Gold/strep/biotin-DNA conjugation, 3D preview census, undo, and redo.
2. DNA-only job creation with default GPU, real CPU Monte Carlo preparation and CUDA MD stages, finite native output, and relaxed-coordinate display.
3. Full 500-particle gold/strep/DNA job creation with default GPU, required diffusion validation, explicit John bath and velocity handoff, real CPU/CUDA stages, finite output, and relaxed-coordinate display.

The two execution tests do not mock engine or job APIs. They use short stages (1,000 MC, 10,000 MD-relax, 1,000 equilibration steps), disable the base-pair retention gate and relaxation retries for this smoke check, and verify every saved final coordinate is finite. They exercise workflow correctness, not relaxation convergence. Test jobs and scratch designs are deleted afterward.

## Remaining validation and provenance

TD-OXDNA-PHYSICS retains the unresolved energy-convergence/sampling criteria from the earlier audit, contact-amplitude decision, and useful-sample performance. Short application workflows exercise preparation, execution, and display; they do not certify equilibrium, solvent dynamics, or experimental agreement.

TD-STREP-NAMD records the requested validation of the original streptavidin-on-gold system in NAMD: gold/coating attachment, biotin–DNA linkage, complete force-field treatment, stability, and experimentally informed orientation/accessibility. NAMD validation has not been performed by these oxDNA tests.

The [machine-readable timing summary](oxdna_physics_implementation_2026-09-14.json) includes executable and shared-library SHA-256 hashes. Local raw inputs, outputs, build logs, and test logs are under `workspace/validation/physics_implementation_20260913/`. The previous installed engine and original managed source checkout were retained.
