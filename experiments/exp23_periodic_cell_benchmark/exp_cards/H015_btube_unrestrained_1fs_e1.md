---
id: H015
title: B_tube unrestrained release is stable with 1 fs timestep and per-step PME
status: complete
date_opened: 2026-05-14
literature:
  - "A shorter timestep and per-step PME can rule out integration/MTS artifacts when structural loss occurs without fatal energies."
parameter_change:
  key: btube_unrestrained_integrator_check
  from: H013 constraints off with 2 fs and fullElectFrequency 2
  to: constraints off with 1 fs and fullElectFrequency 1
baseline_run: H012_k1_prod
test_duration_ns: 0.02
---

## Hypothesis

The unrestrained B_tube release failure is caused or amplified by the 2 fs /
multiple-time-step integrator rather than by the reduced model itself.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over a short
20 ps unrestrained fixed-Z probe.

## Method

Start from `H012_k1_prod.restart.*`, turn constraints off, set `timestep 1.0`,
`fullElectFrequency 1`, and run 20,000 steps.

## Expected Outcome

If this passes while H013 failed, revisit integrator settings before declaring
unrestrained production impossible. If it fails quickly, treat the release
failure as a structural/model issue rather than a timestep artifact.

---

## Result

H015 completed mechanically with no fatal NAMD errors. Temperature was stable.

Base-pairing failed rapidly:

- first saved DCD frame: `84.9%` paired, mean C1' `10.94 Å`
- 20 ps window: `69.2%` mean paired
- final: `62.9%` paired, mean C1' `11.57 Å`

## Conclusion

Reject. Reducing the timestep to 1 fs and using per-step PME did not prevent
fast unrestrained structural loss. The failure is unlikely to be a simple
multiple-time-step/integration artifact.
