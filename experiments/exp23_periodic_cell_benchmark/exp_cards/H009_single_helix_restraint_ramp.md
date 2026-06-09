---
id: H009
title: Single 21 bp periodic dsDNA survives gradual restraint release
status: complete
date_opened: 2026-05-14
literature:
  - "Abrupt removal of positional restraints can launch a strained solvated DNA model away from a locally equilibrated restrained basin."
parameter_change:
  key: restraint_release_protocol
  from: H008 bridge-minimized fixed-Z restart with abrupt constraints off
  to: bridge-minimized fixed-Z restart with staged constraintScaling ramp before constraints off
baseline_run: single_helix_bridge_min/H008_fixed_z_relax
test_duration_ns: 0.15
---

## Hypothesis

The H008 bridge-minimized duplex is chemically improved but fails because all
heavy-atom positional restraints are removed at once. A short fixed-Z NVT ramp
from `constraintScaling 0.5 -> 0.25 -> 0.10 -> 0.03 -> 0.01 -> off` should let
the helix breathe without immediate base-pair loss.

Confirmation threshold: final C1' pairing fraction `>= 0.95` during the
unrestrained fixed-Z stage.

## Mechanism

H008 stayed `100%` paired while restrained but dropped to `66.7%` paired by the
first unrestrained DCD frame. Energies, temperature, and fixed-Z cell dimensions
were normal, so the failure looks like a restraint-release transient or a
residual geometric basin mismatch rather than an MD crash.

## Method

1. Start from `results/single_helix_bridge_min/output/H008_fixed_z_relax.restart.*`.
2. Run fixed-Z NVT with DNA heavy-atom restraints at decreasing
   `constraintScaling` values: `0.5`, `0.25`, `0.10`, `0.03`, `0.01`.
3. Continue fixed-Z NVT with constraints off.
4. Measure pairing for the full ramp and the final unrestrained stage with
   `base_pairing.py`.

## Expected Outcome

Adopt if the final unrestrained stage stays `>= 95%` paired. Reject if pairing
still collapses early after constraints are removed; that would indicate the
periodic duplex needs a different construction or weaker physical restraints in
production rather than just a gentler release.

---

## Result

All stages completed mechanically with fixed `Z = 70.140 Å` and no fatal NAMD
errors. A config-chain issue was found during the first pass: 20 ps stages write
final `.coor/.vel/.xsc` files rather than `.restart.*` files because
`restartFreq = 25000` is longer than the stage. The stage-to-stage configs were
corrected to consume the final output files.

Base-pair retention by stage:

| Stage | scale | mean paired | final paired | final mean C1' |
|-------|-------|-------------|--------------|----------------|
| H009_ramp_01 | 0.50 | 100.0% | 100.0% | 10.33 Å |
| H009_ramp_02 | 0.25 | 100.0% | 100.0% | 10.55 Å |
| H009_ramp_03 | 0.10 | 100.0% | 100.0% | 10.87 Å |
| H009_ramp_04 | 0.03 | 85.7% | 81.0% | 11.38 Å |
| H009_ramp_05 | 0.01 | 66.7% | 66.7% | 11.70 Å |
| H009_unrestrained | off | 51.2% | 42.9% | 12.07 Å |

## Conclusion

Reject full restraint release for the current constructed duplex. The ramp
localizes the threshold: `constraintScaling 0.10` remains stable over this short
window, while `0.03` begins losing base pairs and `off` fails. Next test should
run a longer weak-restraint production at `constraintScaling 0.10` to determine
whether the reduced periodic model can be made usable with a minimal physical
restraint.
