---
id: H019
title: B_tube 2-period staged release from k1 reaches unrestrained production
status: pending
date_opened: 2026-05-14
literature:
  - "The 1-period staged release failed progressively; repeat for 2-period cell to test whether additional axial context shifts the restraint threshold."
parameter_change:
  key: btube_2x_staged_release
  from: H018 abrupt constraints off from H017
  to: staged fixed-Z release 0.75 -> 0.50 -> 0.25 -> 0.10 -> 0.05 -> off
baseline_run: H017_k1_relax_100ps
test_duration_ns: 0.3
---

## Hypothesis

The 2-period B_tube cell can survive a gradual restraint release even though
abrupt release failed.

Confirmation threshold: final C1' pairing fraction `>= 0.95` in the final
constraints-off stage.

## Method

Run 25,000-step fixed-Z NVT stages from H017 with:
`constraintScaling 0.75`, `0.50`, `0.25`, `0.10`, `0.05`, then `constraints off`.

## Expected Outcome

Adopt if the final off stage stays `>= 95%` paired. Reject if degradation begins
at or above the same restraint floor as the 1x cell.

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
