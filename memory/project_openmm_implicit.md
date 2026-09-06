---
name: openmm_implicit
description: Active handoff for GPU-resident OpenMM OL15/GBn2 DNA-origami validation.
metadata:
  type: project
  status: active
  authority: canonical
  review_after: 2026-09-15
---

# OpenMM implicit-solvent origami — head

## CPU checker test audit (2026-09-06)

Under the user's dedicated test-session authorization, the legacy checker's real
CPU smoke and single-duplex 10 ps drift tests passed. Nine smoke assertions now
share one real simulation. No local CUDA validation is implied by these checks.

The user requested an audit and removal of the ongoing two-unconnected-duplex
COM-drift test if unnecessary. It was stopped and removed: its arbitrary
`<0.5 nm` separation-drift requirement is a model-validation claim, not a software
invariant, and the legacy checker has no app/API callers (only exp21). The exp57
paired-reference campaign below is the appropriate place to evaluate collective
separation/reorientation; its documented GBn2 limitations cannot be turned into
a software pass/fail gate for unconstrained duplexes. Exact metric tests retain
zero drift and add prescribed positive/negative separation changes under global
translation, without running dynamics. The real smoke and single-duplex MD
checks remain; no model, force-field setting, or production code was removed.

## Goal

Evaluate GPU-resident AMBER OL15 + GBn2 at 0.150 M generic monovalent ionic
strength as a box-free production surrogate for curved DNA origami. The active
explicit-water NAMD run is the reference. Do not execute OpenMM tests or create a
CUDA Context **on the local workstation** until that NAMD run finishes; bounded
remote RunPod validation is allowed under the user's explicit budget.

## Current state (2026-08-27)

- `openmm[cuda12]>=8.4,<9` is locked; current resolution is OpenMM 8.6.0 plus
  its CUDA 12 plugin/runtime wheels. Local OpenMM remains unprobed because the
  NAMD job owns the workstation GPU. A bounded RunPod duplex gate passed on
  OpenMM 8.6/CUDA mixed precision.
- OL15 is included by `amber14-all.xml`; GBn2 is `implicit/gbn2.xml`. No manual
  force-field file or Amber installation is required for the selected model.
- Core scaffold: `backend/core/openmm_implicit.py`.
- Deferred tests: `tests/test_openmm_implicit.py` plus existing
  `tests/test_openmm_checker.py`.
- Experiment runner, matrix, and pass criteria:
  `experiments/exp57_openmm_implicit_origami/`.
- RunPod result: 21-bp duplex, 1.02 ns, 99.3% mean core WC occupancy,
  max sampled aligned C1′ RMSD 0.290 nm. Implicit 1,778.7 ns/day versus
  same-GPU explicit OpenMM 578.6 ns/day: 3.074×.
- Paired crossover-2HB result: implicit 1,037.6 ns/day versus explicit OpenMM
  336.5 ns/day (3.083×; 3,011 versus 111,062 atoms). Explicit passed the fixed
  global C1′ gate at 0.527 nm; implicit failed reproducibly at 0.932 nm (prior
  technical repeat 0.756 nm). WC occupancy was 97.07% implicit versus 99.82%
  explicit and all crossover bonds remained intact. The defect is excessive
  collective separation/reorientation: implicit helix COM separation
  2.768–3.027 nm and maximum axis angle 23.59°, versus 2.493–2.652 nm and
  8.34° explicit. Do not advance salt-only GBn2 to 6HB.
- Total bounded RunPod campaign spend including integration/host-debug attempts:
  $0.522 of $5; final repeated account check found zero pods and no compute
  billing. See `RESULTS.md`.
- The old checker incorrectly requested a nonexistent top-level `DNA.OL15.xml`;
  it now uses the bundled pair above. Its GBn2 citation was also corrected.
- `uv sync` pruned locally editable cadnano/mrDNA/oxpy tools because they are not
  declared project dependencies; they were immediately restored with their
  prior Git/local editable sources. Do not run another bare `uv sync` without
  restoring them or deciding how to declare these site-local tools.
- Paid integration caught production blockers now fixed: canonical DNA names
  plus explicit terminal template maps for hydrogen addition; `unit.molar`;
  standalone GBn2 XML configured with Debye κ rather than redundant
  `implicitSolvent`; RunPod CUDA 12.9 host filtering for the resolved NVRTC; and
  contiguous chain/residue ordering for helix-oriented crossover atom models.

## Locked choices for the first validation

- Model: AMBER14/OL15 + nucleic-acid GBn2 (igb=8), dielectric 1/78.5.
- Salt: 0.150 M generic monovalent Debye screening. It is not explicit NaCl and
  cannot answer Na localization, counterion condensation, Mg bridging, or
  ion-specific kinetic questions.
- Integrator: Langevin-middle, 300 K, 1/ps, 2 fs, HBond constraints, no HMR.
- Platform: strict CUDA, mixed precision, explicit device and random seed. No
  silent CPU fallback.
- Correctness reference: nonperiodic NoCutoff. CutoffNonPeriodic at 3.0, 2.4,
  and 1.8 nm is experimental and must pass force/ensemble comparisons before use.
- Sparse trajectory/state output and periodic checkpoints limit GPU-to-host
  transfers and permit restart.

## Critical architecture finding

The checker/PDB route is not origami-safe. NADOC PDB chain IDs wrap after 62
strands and large viewer exports split strands across `MODEL` records. OpenMM
interprets models as coordinate frames, so later strands can disappear from the
topology. The new path builds OpenMM `Topology` directly from
`AtomisticModel`: arbitrary chain IDs, terminal residue templates, native OL15
atom names, and explicit `AtomisticModel.bonds` including crossover O3'-P edges.
It writes mmCIF for provenance only after topology construction.

## Validation ladder

1. 21-bp duplex template/minimization/restart smoke.
2. Two-helix double-crossover covalent-edge and junction-stability test.
3. Three-seed straight 6HB ensemble and cutoff ladder.
4. Three-seed curved 6HB compared with the completed NAMD trajectory.
5. 18HB >62-strand topology, memory, and throughput gate.

Compare WC occupancy/fraying, rise/twist, inter-helix spacing, crossover bonds,
Rg, bend-radius/tangent distributions, RMSF, force/energy deltas, ns/day, GPU
utilization and peak memory. A visually plausible structure or one RMSD is not a
validation.

## Handoff

After NAMD completes:

1. Run `tests/test_openmm_implicit.py` without the slow mark, then the existing
   checker tests. Fix static/API/template issues before a Context smoke.
2. Create one CUDA mixed-precision duplex Context and verify the reported
   platform/properties. Never accept automatic CPU fallback.
3. Run the duplex and crossover rungs, including checkpoint identity.
4. Freeze uncertainty-aware tolerances from explicit-NAMD blocks, then execute
   the 6HB cutoff ladder and replicated curved comparison.
5. Only after those pass, measure 18HB feasibility. GB is long-range and may
   become the new cost bottleneck even though water atoms are gone.

## Manual-download trigger

None for generic 150 mM OL15/GBn2. A future request for spatial Na distributions,
explicit Mg, GBION, or Amber-only ion-aware parameters would reopen the dependency
decision and may require AmberTools/Amber parameter files. That is outside this goal.
