---
name: amber_gbion
description: Closed decision record for native Amber26 OL15/GBION GPU validation.
metadata:
  type: project
  status: concluded
  authority: canonical
  review_after: 2027-08-28
---

# Native Amber26 OL15/GBION — concluded

## Final decision (2026-08-28)

Do not use or repeat exp58 as a production curved-origami equilibration workflow.
The definitive record is
`experiments/exp58_amber_gbion/FINAL_ASSESSMENT.md`.

The campaign proved native GPU execution, sound relaxed topology construction, short
duplex/6HB integrity, and a 4.97x nominal-throughput disadvantage versus the archived
NAMD 6HB. It did not measure effective equilibration and did not use the published
low-viscosity regime: exp58 used `gamma_ln=1.0 ps^-1`, anion-related GBION dielectric
coefficients of 10, and `gbsa=3`, versus the paper's `0.05 ps^-1`, coefficients of 8,
and normally `gbsa=0`.

Therefore the result is negative for raw throughput, inconclusive for wall time to a
converged curved-origami ensemble, and insufficient for production. Reopen only as a
new preregistered, replicated, same-force-field comparison using curvature convergence
and effective sample size per wall day—not nominal `ns/day`—as the primary endpoints.

## Goal

Use Amber26's native `pmemd.cuda` implementation of OL15 + GBneck2/GBION v3
with explicit 150 mM NaCl, validate basic duplex stability and throughput on
RunPod, and keep cumulative cloud spending at or below $5.

## Why this replaced salt-only OpenMM GBn2

The paired OpenMM 2HB test showed that OL15 in explicit TIP3P remained stable,
while salt-only GBn2 reproducibly over-separated and reoriented the two helices.
A complete bond/topology audit found no construction defect. GBION directly adds
the missing mobile-ion atmosphere and was parameterized with OL15 for DNA.

Native Amber is the first implementation target. An OpenMM port is deferred unless
Amber's GPU path proves unavailable, too slow, or operationally unsuitable.

## Historical duplex state (2026-08-27)

- The native Amber26 duplex gate passed on an RTX 4090. `pmemd.cuda` emitted its
  GPU banner and `gbion=3`; CPU/GPU one-cycle energies agreed at printed precision.
- The 21-bp OL15/GBneck2/GBION-v3 system used explicit SLTCAP 150 mM NaCl
  (51 Na+, 11 Cl-) and sampled 1 ns at 633.65 wall-clock ns/day.
- Mean core Watson-Crick occupancy was 0.987, final C1' RMSD was 0.429 nm,
  every final bond was 0.08–0.20 nm, and energies were finite.
- A same-GPU 38,882-atom TIP3P control ran at 604.06 wall-clock ns/day: only a
  1.049x speedup for the compact duplex. This validates execution and basic
  stability, not the expected sparse-origami efficiency advantage.
- RunPod spend was $0.69645; setup/launch/termination were confirmed and the
  campaign pod is absent. Unrelated pods were preserved.
- Authoritative outputs are in
  `/media/jojo/Archive/nadoc_amber_exp58/duplex_runpod/`; human audit is in
  `experiments/exp58_amber_gbion/RESULTS.md`.
- The local NAMD production job remains active and was untouched; local molecular
  tests remain forbidden until it finishes.

## Scaffold

- Experiment contract and manual handoff:
  `experiments/exp58_amber_gbion/README.md`
- Published SLTCAP count and GBION-v3 mdin generator:
  `experiments/exp58_amber_gbion/model.py`
- Fail-closed archive/account/budget preflight:
  `experiments/exp58_amber_gbion/preflight.py`
- Preregistered gates:
  `experiments/exp58_amber_gbion/validation_matrix.json`
- Deferred local tests:
  `tests/test_amber_gbion_scaffold.py`

The preflight checks the package before credentials or provider calls. It then
requires a clean confirmation queue, available budget, and no live exp58-owned
pod, while preserving unrelated workloads. It records the package size and
SHA-256 and uses a separate archive and spend ledger under
`/media/jojo/Archive/nadoc_amber_exp58/`.

## Implementation lessons

- Limit Amber's portable CUDA build to four jobs. A 96-way build exhausted memory
  at 93%; an incremental four-way build completed both SPFP and DPFP variants.
- NADOC's NAMD/CHARMM export includes each 5' phosphate. Remove P/OP1/OP2 for
  standard unphosphorylated Amber OL15 termini, preserve `TER`, and assert that
  LEaP produced no inter-strand covalent bonds.
- Do not interpret the 1.049x compact-duplex timing as an origami result. GPU
  launch/occupancy overhead dominates both small systems.

## Reopen gate (not scheduled)

Do not run another sample through the same model as a routine next step. Reopening
requires a new preregistered experiment using the published low-friction and NaCl
parameters, a genuinely curved nonequilibrium structure, matched OL15 controls,
replicas, and wall-time-to-convergence metrics. The detailed requirements and
break-even thresholds are in `FINAL_ASSESSMENT.md`.
