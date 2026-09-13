# PEG continuation parsing and skip-decision verification

2026-09-12. This fixes the false p10 failure in job `48c1995afbd5` without changing
native inputs, forces, timesteps, coordinates or the simulation's energy records.

## Evidence parsing

The PEG validator uses a strict continuation reader (`namd_peg_evidence.py`). It
collects ETITLE schemas across the segment's logs, requires them to agree, and uses
that verified schema for ENERGY records before a delayed header or in a headerless
continuation. Missing schemas, incompatible schemas, incorrect column counts,
nonfinite values, fractional/negative steps and nonmonotone per-log steps are errors.
The general DNA parser is unchanged.

Continuation precedence is numeric (`resume2` before `resume10`), independent of
file timestamps. The emitted continuation configuration supplies `firsttimestep`.
At rollback, old samples beyond that checkpoint are discarded. Each coordinate
frame is paired only with an energy record from its own simulation attempt; a
missing record cannot be borrowed from another attempt at the same timestep.
Expected DCD cadence is checked against the manifest, including trajectory gaps.

## Safety versus convergence

Safety results name each failed check and record missing energy/trajectory steps,
expected and matched frame counts, maximum wall/graft excursions and force-energy
agreement. Parser failures include the affected file/line or schema problem.
Unsafe segments are marked failed in the timeline, with a durable health sample.

A safe segment that has not converged reports:

> PEG safety passed; continue relaxation: convergence not established; this is not a safety failure.

Convergence uses the same matched coordinate/energy frames. There must be at least
20 valid samples with matching chain dimensions. Every chain's geometric radius
of gyration and height must pass **two disjoint trailing ten-frame windows**, and
the mean difference between those windows must also pass. The criteria are:

| Quantity | Relative mean drift | Relative standard deviation |
| --- | --- | --- |
| Potential energy | <0.05% | <0.35% |
| Volume, when present | <0.30% | <0.50% |
| Each chain's Rg and height | <5% | <10% |

Exact threshold equality does not pass. No averaging across chains is permitted
for the verdict. Missing samples, mismatched chain arrays and nonfinite values
cannot authorize a skip. Every metric exposes its two window measurements,
between-window drift, threshold values and pass/fail result.

Skip application additionally requires the user toggle to be enabled, remaining
chunks in that relaxation stage, and all three nonempty checkpoint files. The
runner writes `<segment>.peg-skip.json` with explicit blockers and the evidence
used. Skipped chunks inherit checkpoint files and retain their `skipped` flags;
no fake trajectory or native execution log is created for them. Warm-up and final
chunks have no remaining same-stage chunk to skip.

## Proof and its limits

- **29 evidence/metric tests**: headerless/delayed headers, invalid records,
  incompatible/missing schemas, numeric ordering, rollback pairing, sparse samples,
  drift in one chain, transient plateaus, jumps between flat windows, nonfinite data,
  missing volume, shape mismatch, exact thresholds and missing checkpoints. Additional safety tests independently exercise wall/graft
  limits, force-energy mismatch, trajectory gaps, missing completion, offload and
  native fatal-error detection.
- **24 cutoff/runner tests passed**, including four new PEG runner scenarios using
  the real validator and runner with controlled coordinate/energy inputs and a
  stubbed NAMD process: stationary noisy/flat data allows skip; drift holds;
  disabling skip runs every chunk; missing energy stops with a precise failure.
  The positive runner test verifies exact restart-file inheritance and proves the
  skipped chunks never launch or acquire fabricated logs/trajectories.
- The original native p10 package passes reanalysis **without rewriting any native
  log**: all 30 frames match, maximum penetration 0.3384 Å, maximum graft excursion
  0.8350 Å, maximum force-energy mismatch 0.00005736 kcal/mol.
- Its correct verdict is **HOLD / continue**: potential-energy mean drift is 0.0962%
  in the earlier window and 0.3592% in the later window (limit 0.05%); the difference
  between window means is 0.2818%. Polymer convergence also fails.

The positive skip proof is controlled software testing, not a claim that this
native brush is equilibrated. These operational thresholds have not been calibrated
against long independent PEG trajectories for false-positive rates or equilibrium
observables. No threshold was loosened to force the native case to skip.

## Regression results

The focused runs passed **57 tests**: 29 evidence/safety tests, 24 cutoff/runner
tests and four existing PEG protocol tests. `just test-smart` selected **FULL**:
**8,692 passed, 143 skipped, 1 xfailed, 15 failed**. The failures remain the 12
unavailable BigO/smallO fixtures, two oxDNA PEG-live bonded-distance errors and
SNUPI RPY RMSF tolerance failure previously documented. No full-suite deferral.
The seven additional individual-safety cases were added after full-suite collection
and passed in the final focused run. Changed files pass Ruff and `git diff --check`.
No frontend code changed; `main.js` delta for this turn is zero.

Per-job evidence is retained in `output/<segment>.peg-health.json` (safety and
per-chain measurements) and `output/<segment>.peg-skip.json` (decision and blockers).

## Live continuation confirmation

The ordinary development API resumed job `48c1995afbd5` under the user-opened
compute session. The runner revalidated p10, withheld skipping for the recorded
energy/polymer convergence failures, and entered **p50** from the completed p10
checkpoint. GPU-resident integration and a newly written p50 trajectory frame
were verified. At handoff, warm-up and p10 are done, p50 is running, p100 is pending,
no chunks are falsely marked skipped, and the job error is null. The full run is
still in progress; its final convergence verdict is not yet available.
