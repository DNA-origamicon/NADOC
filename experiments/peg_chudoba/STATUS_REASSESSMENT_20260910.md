# Bounded PEG validation reassessment

Read-only scientific/process assessment at approximately 20:51 MDT, 2026-09-10.
Evidence: `workspace/peg_chudoba/scheduling_294_20260910/validation.json`,
`REPORT.md`, `bounded_driver.json`, `cpu12_driver.log`, `lease.json`, native
run metadata and live `/proc` inspection. No simulations or controller state changed.

## Current execution

The bounded driver stopped at 19:27 MDT (2026-09-11 01:27 UTC) with
`GPU/CPU disagreement N36, dt=2; investigate integration before more sampling`.
Its PID 2916144 no longer exists. The lease is `restored`; PID 1606968 is the older
serial controller. A live native engine was running the historical N455/294 K,
100 kPa seed-402 EOS case. This is not the narrowed N135 validation campaign.
Other historical engines remain parked. The earlier finish-time estimate no
longer applies to successful validation: the narrowed campaign is stopped.

## Scientific results

- CPU equilibrium dimensions: all nine lengths N9–N795 pass the frozen bounded
  engineering/sampling checks; deviations from literature markers are +0.37% to
  +6.45%. These are comparisons to the documented preprint/SI reconstruction;
  the final journal text/original numerical tables remain unverified.
- N135 EOS: all seven pressures reached their permitted caps without passing.
  Mean concentration deviations are −0.11% to +3.94%, but minimum volume ESS is
  only 2.85–24.12 and volume R-hat spans 1.020–2.856. Concentration means alone
  cannot establish the osmotic constitutive law needed for brush mechanics.
- N36 GPU, 2 fs: three independent origins completed 20 ns each. RMS Rg =
  1.387526 ± 0.015167 nm (SEM); CPU = 1.341028 ± 0.008968 nm. Maximum bond
  length 0.4898 nm passes the 0.6 nm stability check. Minimum ESS 100.393 and
  R-hat 1.0099937 barely clear the current sampling cutoffs. Largest per-seed
  half-window RMS-Rg difference is 0.0953 nm; threshold crossing is not strong
  evidence of robust mixing.
- N36 1 fs and both N135 GPU timestep cohorts have not run in this campaign.
- Previously recorded implementation provenance and N795 endpoint energy checks
  pass. These do not prove MD ensemble correctness, forces at all configurations,
  or the equilibrium validation that remains missing.

## Stop-message interpretation

For GPU minus CPU, the difference is 0.046498 nm (3.467%). Twice the combined
SEM is 0.035239 nm. The frozen equivalence test evaluates

    abs(difference) + 2 * combined_SEM <= 0.05 * CPU_RMS_Rg

The left side is 0.081737 nm (6.095%); the tolerance is 0.067051 nm.
Thus equivalence has not been demonstrated. However, the approximate difference
interval [0.011259, 0.081737] nm straddles the positive equivalence boundary:
it does NOT establish a discrepancy larger than 5% either.

The driver's condition at `validate_narrow.py` currently classifies every failed
equivalence test with nominal sampling/precision passes as a disagreement and
raises before the already contemplated 80 ns continuation or 1 fs comparison.
This conflates **inconclusive equivalence** with **demonstrated out-of-band bias**.
Do not relax the 5% acceptance band or count this result as a pass. A revision
should distinguish those outcomes while retaining the existing allocation cap.

## Revised priorities

1. Correct the verdict/stop classification with tests for pass, inconclusive and
   statistically resolved out-of-band differences. Preserve raw evidence and the
   original validator snapshot. Check RMS definitions, parameter/temperature/unit
   identity and representative force agreement before assigning a physical cause.
2. Resolve the small N36 GPU case first: run its planned 1 fs comparison and, where
   needed, its capped continuation. Analyze replicas and drift, not just pooled Rg.
   The initial 1 fs cohort would cost roughly 48 minutes locally if doubling the
   measured 24-minute total for the three 2 fs trajectories remains valid. This is
   a timing estimate, not a convergence prediction. N135 follows after N36 is understood.
3. Diagnose EOS sampling on selected low/intermediate/high pressure states before
   authorizing another full matrix. Audit molecule-volume move acceptance/Jacobian,
   pressure/unit conventions, proposal scales and translational/conformational
   mixing. Compare useful ESS/hour, not merely sweeps/hour. Small-system diagnostic
   experiments can help isolate an implementation issue but cannot substitute for
   the original finite-size/literature comparison. Existing caps remain exhausted.
4. Reconcile scheduling deliberately: historical N455 work resumed automatically
   and does not address these two blockers. Prefer the bounded diagnostic work over
   additional broad N455 production when execution is resumed; do not bypass the
   controller/lease mechanism or manipulate native processes ad hoc.
5. Continue independent NAMD parameter acquisition and small-chain qualification.
   Defer large H200 brush campaigns and quantitative oxDNA brush-force claims until
   the GPU comparison and osmotic sampling gaps are addressed. Shift the immediate
   pilot effort to these diagnostics; increasing GPU count alone will not resolve them.

No engine defect has been established by this assessment. No additional simulations,
code fixes, scheduler changes or cloud expenditures were performed in this status check.
