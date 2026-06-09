---
id: H020
title: B_tube 2-period unrestrained release is stable with 1 fs timestep and per-step PME
status: pending
date_opened: 2026-05-14
literature:
  - "Repeat the 1 fs / per-step PME integrator sanity check for the 2-period cell."
parameter_change:
  key: btube_2x_unrestrained_integrator_check
  from: H018 constraints off with 2 fs and fullElectFrequency 2
  to: constraints off with 1 fs and fullElectFrequency 1
baseline_run: H017_k1_relax_100ps
test_duration_ns: 0.02
---

## Hypothesis

The 2-period abrupt release failure is caused or amplified by the 2 fs /
multiple-time-step integrator.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over a 20 ps
unrestrained fixed-Z probe.

## Method

Start from `H017_k1_relax_100ps.*`, turn constraints off, set `timestep 1.0`,
`fullElectFrequency 1`, and run 20,000 steps.

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
