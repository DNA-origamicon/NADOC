---
id: H004
title: Isotropic NPT (box breathing) vs locked-Z NVT — which maintains base pairing?
status: pending
date_opened: 2026-05-10
note: Premise revised 2026-05-10. Original claimed NPT equilibrium Z ≈ 67.8 Å; measured
      production_iso_npt tail (last 200 XST frames of 17888) shows Z mean = 70.144 Å,
      std = 0.026 Å. Design Z IS the isotropic NPT equilibrium. Z-lock tension is not the
      primary cause; revised to test NPT vs NVT ensemble.
literature:
  - "Loncharich et al. (1992) Biopolymers 32:523 — Langevin dynamics; ensemble artifacts in NVT vs NPT"
  - "Dans et al. (2016) PLoS Comput. Biol. 12:e1004974 — CHARMM36 DNA equilibrium properties"
  - "Cheatham & Case (2013) Biopolymers 99:969 — NPT for nucleic acid simulation, recommended default"
parameter_change:
  key: ensemble
  from: locked-Z NVT (useFlexibleCell no, no barostat)
  to: isotropic NPT (useFlexibleCell no, langevinPiston on, target 1.01325)
baseline_run: ramp_v2_03
test_duration_ns: 2.0
---

## Hypothesis

Isotropic NPT (box breathing) will maintain higher C1'–C1' pairing fraction than locked-Z
NVT over 2 ns of unrestrained MD from the same `ramp_v2_03` restart. The production_iso_npt
run (18 ns, already running) provides the empirical comparison.

## Mechanism (revised)

The isotropic NPT equilibrium for this DNA is Z ≈ 70.14 Å (confirmed from 17888-frame XST
tail of production_iso_npt: mean=70.14 Å, std=0.026 Å). Locked-Z NVT at the design Z is
therefore NOT imposing axial tension.

The −124.9 bar mean pressure in H001 (locked-Z NVT) likely reflects XY tension: the initial
box (a_x=155.6, b_y=151.3 Å) is slightly wider than the equilibrium (production_iso_npt
tail a_x≈155.5 Å). In locked-Z NVT, this cannot relax. In isotropic NPT, all three
dimensions breathe simultaneously; DNA conformation couples to barostat fluctuations.
Whether this coupling aids equilibration (by absorbing conformational energy) or hurts it
(by introducing barostat coupling artifacts) is the test.

Literature (Cheatham & Case 2013) recommends NPT as the default for nucleic acid
simulations in explicit solvent specifically because it avoids artifacts from small box
size in NVT.

## Method

1. Compare base_pairing analysis of `production_iso_npt.dcd` (isotropic NPT, ~18 ns,
   rigidBonds water) against H001 result (locked-Z NVT, 500 ps, rigidBonds all).
2. If production_iso_npt pairing is substantially better, the ensemble choice dominates.
3. Run a dedicated 2 ns isotropic NPT from `ramp_v2_03` restart with `rigidBonds all`
   to isolate NPT benefit from rigidBonds change.

## Expected Outcome

- `production_iso_npt` bp_fraction > 0.80 after 18 ns: NPT ensemble is better; adopt NPT
- `production_iso_npt` bp_fraction ≈ 0.32: structural problem; need longer equilibration
  or a fundamentally different starting point

---

## Result

*(Fill after run.)*

## Conclusion

*(Adopt / Reject / Needs more data.)*
*(Critical decision: if Z tension is confirmed, DTP-PMD-2 must be updated to state the
accepted equilibrium Lz rather than the design Lz.)*
