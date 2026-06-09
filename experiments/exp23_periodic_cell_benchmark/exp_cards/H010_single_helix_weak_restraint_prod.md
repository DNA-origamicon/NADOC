---
id: H010
title: Single 21 bp periodic dsDNA is stable with weak production restraint
status: complete
date_opened: 2026-05-14
literature:
  - "Reduced periodic DNA controls may require weak reference restraints when explicit solvent and end-to-end PBC bonds remove the larger origami context."
parameter_change:
  key: production_restraint_scaling
  from: H009 full release fails below constraintScaling 0.10
  to: fixed-Z production with constraintScaling 0.10 retained
baseline_run: single_helix_bridge_min/H009_ramp_03
test_duration_ns: 0.1
---

## Hypothesis

The single periodic duplex can be made usable for short production windows by
retaining a weak DNA heavy-atom positional restraint at `constraintScaling 0.10`.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 100 ps fixed-Z
NVT, with stable temperature and no fatal NAMD errors.

## Mechanism

H009 stayed `100%` paired through the `0.10` restraint stage but started losing
pairs at `0.03`. This suggests the isolated periodic helix is missing stabilizing
context from the full origami bundle and needs a weak reference-restraint floor,
at least until the construction method is improved.

## Method

1. Start from `results/single_helix_bridge_min/output/H009_ramp_03.*`.
2. Continue fixed-Z NVT for 50,000 steps with:
   `constraints on`, `conskFile restraints.pdb`, `constraintScaling 0.10`.
3. Analyze pairing with `base_pairing.py` and extract log/XST metrics.

## Expected Outcome

Adopt as an interim production protocol if final pairing is `>= 95%`. If this
fails, test stronger/alternate restraints or rebuild the duplex with a continuous
canonical helix generator rather than copied B_tube frames.

---

## Result

The 100 ps weak-restraint run completed mechanically and initially looked
promising: `94.8%` mean paired and `95.2%` final paired over `~0.095 ns`, with
final mean C1' distance `11.10 Å`.

The same protocol extended for 500 ps did not remain stable enough:
`91.7%` mean paired and `85.7%` final paired over `~0.495 ns`, with final mean
C1' distance `10.97 Å`. Temperature and fixed-Z cell behavior remained normal;
the failure is structural by the C1' pairing threshold, not a mechanical NAMD
crash.

## Conclusion

Reject `constraintScaling 0.10` for 500 ps stability. It is a useful bracket
point: stronger than `0.03`/off and briefly acceptable, but too weak for a
production-like window. Next test uses `constraintScaling 0.20`.
