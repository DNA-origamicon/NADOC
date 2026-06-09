---
id: H014
title: B_tube staged release from stable k1 checkpoint reaches unrestrained production
status: complete
date_opened: 2026-05-14
literature:
  - "When abrupt release fails, staged release separates kinetic shock from intrinsic reduced-model instability."
parameter_change:
  key: btube_staged_release_from_k1
  from: H013 abrupt constraints off from H012
  to: staged fixed-Z release 0.75 -> 0.50 -> 0.25 -> 0.10 -> 0.05 -> off
baseline_run: H012_k1_prod
test_duration_ns: 0.25
---

## Hypothesis

A staged release from the stable H012 `constraintScaling 1.0` checkpoint can
reach an unrestrained fixed-Z B_tube segment without immediate C1' pairing loss.

Confirmation threshold: final C1' pairing fraction `>= 0.95` in the final
constraints-off stage, with stable temperature and no fatal NAMD errors.

## Mechanism

H013 failed within the first saved frame after abrupt release. If H014 succeeds,
the failure was primarily kinetic shock from removing all restraints at once. If
H014 fails at a specific low restraint floor, that floor marks where the reduced
B_tube segment no longer has enough physical support.

## Method

Run 25,000-step fixed-Z NVT stages from H012 with:
`constraintScaling 0.75`, `0.50`, `0.25`, `0.10`, `0.05`, then `constraints off`.
Analyze C1' pairing for every stage.

## Expected Outcome

Adopt if the final off stage remains `>= 95%` paired. Reject if pairing drops
well below threshold before or immediately after constraints off; record the
failure threshold and theorize reduced-model causes.

---

## Result

All stages completed mechanically with no fatal NAMD errors.

Base-pair retention by stage:

| Stage | scale | mean paired | final paired | final mean C1' | final p90 C1' |
|-------|-------|-------------|--------------|----------------|---------------|
| H014_ramp_01 | 0.75 | 95.6% | 94.8% | 10.49 Å | 11.62 Å |
| H014_ramp_02 | 0.50 | 93.8% | 93.3% | 10.59 Å | 11.82 Å |
| H014_ramp_03 | 0.25 | 89.5% | 89.7% | 10.71 Å | 12.02 Å |
| H014_ramp_04 | 0.10 | 81.0% | 80.2% | 11.00 Å | 12.45 Å |
| H014_ramp_05 | 0.05 | 73.2% | 72.2% | 11.24 Å | 12.90 Å |
| H014_off | off | 57.3% | 51.8% | 11.89 Å | 14.31 Å |

## Conclusion

Reject. Slower release improves the first 50 ps relative to abrupt off, but
structural loss begins as soon as the restraint floor drops below roughly
`0.75`. This argues against a pure abrupt-release shock; the reduced B_tube
periodic segment is relaxing away from the reference architecture when
positional support is removed.
