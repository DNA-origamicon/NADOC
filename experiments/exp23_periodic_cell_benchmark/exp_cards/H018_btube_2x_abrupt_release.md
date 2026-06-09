---
id: H018
title: B_tube 2-period cell remains stable after abrupt restraint release
status: complete
date_opened: 2026-05-14
literature:
  - "A 2-period cell may preserve enough axial context to improve unrestrained stability relative to the 1-period cell."
parameter_change:
  key: btube_2x_release_from_k1
  from: H017 2x fixed-Z k1 restrained checkpoint
  to: fixed-Z continuation with constraints off
baseline_run: H017_k1_relax_100ps
test_duration_ns: 0.1
---

## Hypothesis

The 2-period B_tube cell has enough additional axial context to tolerate abrupt
removal of DNA heavy-atom positional restraints for 100 ps.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 100 ps.

## Method

Start from `results/hyp_runs/H017/output/H017_k1_relax_100ps.*`, disable
constraints, and run fixed-Z NVT for 50,000 steps.

## Expected Outcome

If H018 passes, continue to 500 ps and then run staged release checks. If it
fails, compare the time scale and final pairing against the 1x H013 failure.

---

## Result

H018 completed mechanically with no fatal NAMD errors. Temperature and fixed-Z
cell behavior were normal.

Base-pairing failed rapidly:

- first saved DCD frame at 10 ps: `52.4%` paired, mean C1' `12.03 Å`
- 100 ps window: `42.3%` mean paired
- final saved frame at 90 ps: `37.7%` paired, mean C1' `13.16 Å`

## Conclusion

Reject. The 2-period cell did not rescue abrupt unrestrained release. In this
direct test it failed at least as quickly as the 1-period cell, despite the
retained-restraint H017 baseline being stable at the final frame.
