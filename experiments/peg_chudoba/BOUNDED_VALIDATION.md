# Bounded bulk PEG validation — 2026-09-10 revision

User authorized finishing the general bulk model checks after discussion of
cost and the eventual gold-grafted application. This revision supersedes the
production scope in NARROW_VALIDATION.md; that original file and the timing
plan remain unchanged as benchmark provenance. No force-field parameters or
statistical acceptance tolerances change.

## Required evidence

- Neutral methyl-capped PEG, implicit water, 294 K, documented Chudoba zero-tail
  reconstruction. Existing CPU equilibrium dimensions for N=9,18,27,36,76,135,
  275,455,795 are reused if they pass the original sampling and 10% engineering
  criteria. Three independent origins; no timing trajectories pooled into these.
- N135 solution EOS: 108 chains at 1,10,20,50,100,200,1000 kPa. Preserve the
  original concentration/uncertainty, volume, shape, contact and drift criteria.
  Finish the 12 already reserved 20,000-sweep replicas, then permit at most two
  additional 20,000-sweep allocations per origin per pressure, only if needed.
  A capped unresolved state remains incomplete and does not block assessment of
  other pressures or GPU cohorts. Adequately sampled disagreement stops for
  diagnosis; no fitting to the observed discrepancy.
- GPU NVT equilibrium: N36 and N135, 294 K, three independent CPU-equilibrated
  origins per length, at both 2 fs and 1 fs. First 20 ns per origin; one further
  80 ns continuation only if needed (100 ns total maximum per origin/timestep).
  Retain original ESS >=100, R-hat <1.01, SEM <=2.5%, stability, and 5% CPU/GPU
  and timestep equivalence requirements including two combined SEM. Each latest
  continuation is assessed separately with its predefined 10% discard; starting
  at equilibrium alone is not evidence of independent sampling.
- N795 GPU: numerical potential-energy agreement on all completed serial GPU
  benchmark endpoints against the independent physical-unit reference, with
  tolerance 2e-5 internal energy units per bead. These are implementation checks,
  not GPU equilibrium evidence. Retain the existing force/unit verification
  manifest only after verifying its engine and reference hashes.

## Scheduling and completion

Use the completed two-round scheduling benchmark selection: independent CPU
replicas at the selected CPU concurrency and one GPU job if that wins. CPU and
GPU phases run separately; no unbenchmarked overlap is claimed. N135 inherits
GPU scheduling from the tested N36/N795 workloads, an explicit interpolation.
Keep existing process lease/recovery protection. Do not rebuild the engine.

These are maximum allocations, not assurances of convergence. Publish all
pass/unresolved verdicts; mark the overall validation passed only if every
required cohort and implementation check passes. No automatic extension beyond
these limits. Report bounded sampling failure for sampler diagnosis.

The claim is bulk equilibrium agreement with the preprint/SI benchmarks at
294 K. It does not establish physical kinetics, all-temperature transferability,
gold/linker interactions, grafted PEG behavior, PEG–DNA interactions, salt or
field response. The final journal main text/original author tables remain
unverified. Surface validation is the next application-specific stage.
