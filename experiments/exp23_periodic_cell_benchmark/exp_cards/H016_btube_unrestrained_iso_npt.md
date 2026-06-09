---
id: H016
title: B_tube unrestrained release is stable under isotropic NPT
status: complete
date_opened: 2026-05-14
literature:
  - "If fixed-cell stress drives distortion, isotropic NPT should relieve it; if topology/geometry is unsupported, NPT will still fail structurally."
parameter_change:
  key: btube_unrestrained_ensemble_check
  from: H013 fixed-Z NVT constraints off
  to: isotropic NPT constraints off
baseline_run: H012_k1_prod
test_duration_ns: 0.05
---

## Hypothesis

Unrestrained B_tube release fails because fixed-Z NVT overconstrains the box;
isotropic NPT from the stable H012 checkpoint will preserve C1' pairing.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 50 ps.

## Method

Start from `H012_k1_prod.restart.*`, turn constraints off, enable isotropic
Langevin piston NPT, and run 25,000 steps.

## Expected Outcome

If NPT passes while fixed-Z fails, revisit the exact-Z production assumption. If
NPT fails too, the no-restraint problem is more likely reduced-model geometry or
missing stabilizing architecture.

---

## Result

H016 completed mechanically with no fatal NAMD errors. Isotropic NPT relieved
the high negative fixed-cell pressure: pressure average was near target by the
end of the short run and volume changed from the H012 fixed-cell value.

Base-pairing still failed rapidly:

- first saved DCD frame: `79.6%` paired, mean C1' `11.08 Å`
- 50 ps window: `62.8%` mean paired
- final: `56.2%` paired, mean C1' `11.85 Å`

## Conclusion

Reject. Allowing isotropic pressure relaxation does not rescue unrestrained
B_tube stability. The failure is therefore not explained solely by locked-Z or
fixed-volume stress.
