---
id: H011
title: Single 21 bp periodic dsDNA is stable with weak production restraint 0.20
status: complete
date_opened: 2026-05-14
literature:
  - "The minimum viable restraint floor should be bracketed empirically after full release fails."
parameter_change:
  key: production_restraint_scaling
  from: constraintScaling 0.10 is marginal at 100 ps and fails by 500 ps
  to: fixed-Z production with constraintScaling 0.20 retained
baseline_run: single_helix_bridge_min/H009_ramp_02
test_duration_ns: 0.5
---

## Hypothesis

`constraintScaling 0.20` is strong enough to keep the bridge-minimized periodic
21 bp dsDNA helix paired for a 500 ps fixed-Z production smoke test.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 500 ps, with
stable temperature and no fatal NAMD errors.

## Mechanism

H009 located the failure threshold between `0.10` and `0.03` for short stages.
H010 showed that `0.10` is only marginal at 100 ps and insufficient at 500 ps.
Testing `0.20` checks whether a slightly stronger but still weak positional
floor is a workable interim protocol.

## Method

1. Start from `results/single_helix_bridge_min/output/H009_ramp_02.*`.
2. Run fixed-Z NVT for 250,000 steps with:
   `constraints on`, `conskFile restraints.pdb`, `constraintScaling 0.20`.
3. Analyze pairing and log/XST metrics.

## Expected Outcome

Adopt as the interim stable single-helix periodic protocol if final pairing is
`>= 95%`. If it fails, test `0.30` or switch effort to continuous canonical
duplex construction and/or base-pair-specific restraints.

---

## Result

The 500 ps fixed-Z weak-restraint run completed with no fatal NAMD errors.
Runtime was `186.9 s` for 250,000 steps, or `~231 ns/day` on the local
NAMD 3.0.2 CUDA path.

Base-pairing summary over `~0.495 ns`:

- `99.5%` mean paired
- `100.0%` final paired
- mean C1' distance `10.60 Å`
- final mean C1' distance `10.52 Å`
- final p90 C1' distance `11.21 Å`

Log/XST metrics:

- temperature `309.1 ± 2.7 K`, max `316.2 K`
- fixed `Z = 70.140 Å`, std `0.0 Å`
- volume drift `0.0%`
- no fatal errors or sentinel energies

## Conclusion

Adopt as the interim stable protocol for the single-helix periodic dsDNA smoke:
bridge-minimized geometry, fixed-Z NVT, and retained DNA heavy-atom positional
restraints at `constraintScaling 0.20`. This should be treated as a pragmatic
reduced-model restraint floor, not proof that the current constructed duplex is
stable without support. Next tuning target is whether `0.15` also survives
500 ps, or whether a continuous canonical duplex builder can eliminate the need
for a production restraint.
