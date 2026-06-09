---
id: H013
title: B_tube remains stable after abrupt release from stable k1 restrained production
status: complete
date_opened: 2026-05-14
literature:
  - "A direct release probe distinguishes inadequate equilibration from an intrinsically unsupported reduced periodic model."
parameter_change:
  key: btube_release_from_stable_k1
  from: H012 fixed-Z production with constraintScaling 1.0
  to: fixed-Z continuation with constraints off
baseline_run: H012_k1_prod
test_duration_ns: 0.1
---

## Hypothesis

After 500 ps of stable fixed-Z restrained production at `constraintScaling 1.0`,
the B_tube 21 bp periodic segment can tolerate abrupt release of DNA heavy-atom
positional restraints for at least 100 ps.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 100 ps, with
fixed `Z = 70.140 Å`, stable temperature, and no fatal NAMD errors.

## Mechanism

If H013 passes, H007 likely failed because restraints were released before the
bundle had enough time to equilibrate at the exact-Z cell. If H013 fails
immediately, the periodic reduced cell likely needs either a much slower release
path, different physical constraints, improved geometry, or additional origami
context.

## Method

1. Start from `results/hyp_runs/H012/output/H012_k1_prod.restart.*`.
2. Continue fixed-Z NVT for 50,000 steps with `constraints off`.
3. Analyze C1' pairing and NAMD log/XST metrics.

## Expected Outcome

Adopt as a viable route toward unrestrained production if pairing remains
`>= 95%`. If it fails, record the time scale and try slower ramping from H012.

---

## Result

H013 completed mechanically with no fatal NAMD errors. Temperature was stable
(`309.4 ± 0.7 K`) and fixed `Z = 70.140 Å` was preserved.

Structurally it failed immediately after constraints were disabled:

- first saved DCD frame: `81.2%` paired, mean C1' `11.05 Å`
- 100 ps window: `56.4%` mean paired
- final: `49.2%` paired, mean C1' `12.28 Å`

## Conclusion

Reject. A stable 500 ps `constraintScaling 1.0` run is not enough to permit
abrupt full release. The collapse occurs within the first saved frame after
release, while energy/temperature remain normal, so the failure is structural
relaxation of the reduced model rather than a NAMD integration crash. Next test:
staged release from the same H012 checkpoint.
