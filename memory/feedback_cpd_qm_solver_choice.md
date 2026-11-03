# CPD QM solvent solver preference

User instruction, 2026-10-17: start future workflows with the independent solver
first. For analogous charged CPD fragment continuum-solvent reference calculations,
prefer the independently tested PySCF IEF-PCM implementation before Psi4/ddX or
PCMSolver retries. This is a scoped workflow preference, not a universal replacement
of Psi4 for gas-phase MP2, geometry optimization, Hessians or other proven tasks.

Proven runtime: Archive runtime/development-artifacts/cpd-pyscf-runtime-v1/site,
PySCF2.14.0 plus h5py, using nadoc-qm Python. Preserve isolated/runtime source pins.
Upstream IEF-PCM reference test passed. Same terminal-proxy HF/def2-SVPD,
explicit UFF1.1 radii,epsilon78.3553,SWIG302/350 passed paired numerical screen:
relative energy change0.010432kcal/mol. Original434 also tested;alternate434 and
590 configurations failed conservative memory admission. Do not silently use
PySCF default cavity radii or import Psi4 AO densities without mapping verification.

Every new chemistry still needs upstream/runtime checks, memory preflight,
explicit cavity/basis/charge provenance and a bounded numerical sensitivity check.
Success here is not universal solvent accuracy, a minimum certificate, resolution
of the neutral MP2/MM mismatch, or validated CPD stabilization prediction.

Use Archive for all bulk/scratch, sequential restartable jobs below16h, audits
between chunks, completion/deadline triggers rather than polling, no cloud spending.
Do not reopen preserved failed solver/grid/radius retry loops without new evidence.
See docs/audits/cpd_independent_pcm_pair_closeout_20261017.json and
 docs/cpd_anti_additive_campaign.md for evidence and current work.
