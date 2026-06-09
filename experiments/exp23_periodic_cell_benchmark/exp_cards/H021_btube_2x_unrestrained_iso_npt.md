---
id: H021
title: B_tube 2-period unrestrained release is stable under isotropic NPT
status: pending
date_opened: 2026-05-14
literature:
  - "Repeat the ensemble/stress check for the 2-period cell."
parameter_change:
  key: btube_2x_unrestrained_ensemble_check
  from: H018 fixed-Z NVT constraints off
  to: isotropic NPT constraints off
baseline_run: H017_k1_relax_100ps
test_duration_ns: 0.05
---

## Hypothesis

The 2-period unrestrained release fails because fixed-Z NVT overconstrains the
box; isotropic NPT will preserve C1' pairing.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 50 ps.

## Method

Start from `H017_k1_relax_100ps.*`, turn constraints off, enable isotropic
Langevin piston NPT, and run 25,000 steps.

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
