---
id: H008
title: Single 21 bp periodic dsDNA bridge minimization fixes unrestrained pairing loss
status: complete
date_opened: 2026-05-14
literature:
  - "CHARMM36 DNA protocols require chemically plausible phosphodiester geometry before dynamics; local minimization should not be asked to repair multi-angstrom backbone bridges during production."
parameter_change:
  key: single_helix_build_geometry
  from: copied 7 bp template with 2.066 Å O3'->P copy/wrap links
  to: local canonical C3'-O3'-P-O5'-C5' minimization for every adjacent and PBC link
baseline_run: single_helix_control
test_duration_ns: 0.1
---

## Hypothesis

Applying NADOC's canonical local phosphodiester bridge minimizer to every
single-helix adjacent link and both PBC wrap links will keep the unrestrained
fixed-Z 21 bp dsDNA helix paired after 100 ps.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over the 100 ps
unrestrained fixed-Z NVT smoke.

## Mechanism

The first single-helix control built the 21 bp helix by copying a 7 bp template
three times. Dry geometry showed O3'->P copy-junction and PBC wrap distances of
about `2.066 Å`, longer than the intended `1.60 Å`. Restrained runs stayed
paired, but unrestrained NPT and fixed-Z NVT both lost pairing rapidly without
NAMD fatal errors. This suggests the problem is constructed backbone strain
rather than NAMD stability.

## Method

1. Build a new variant in `results/single_helix_bridge_min/` with:
   `build_single_helix.py --bridge-minimize`.
2. Verify all O3'->P adjacent and PBC distances are `1.600 Å` after local
   minimization.
3. Run fixed-Z restrained NVT for 50,000 steps.
4. Run fixed-Z unrestrained NVT for 50,000 steps from that restart.
5. Measure final pairing with `base_pairing.py`.

## Expected Outcome

Adopt if final unrestrained pairing is `>= 95%` and there are no fatal errors or
sentinel energies. Reject if pairing still drops below `75%`, which would imply
that copied-helix base/baseframe geometry, sequence, restraint strategy, or
ensemble choice remains the dominant failure mode.

---

## Result

Build succeeded in `results/single_helix_bridge_min/` after patching
`build_single_helix.py` to resolve `--out-dir` to an absolute path. Dry geometry
after minimization reported all adjacent and PBC O3'->P distances at `1.600 Å`
(`before mean=1.754 Å`, `before max=3.257 Å`; `after mean=max=1.600 Å`).

Fixed-Z restrained NVT (`H008_fixed_z_relax`) completed with no fatal errors and
held `100%` pairing over `~0.105 ns`; final mean C1' distance was `10.16 Å`.

Abrupt unrestrained fixed-Z NVT continuation (`H008_fixed_z_prod`) completed
with no fatal errors and fixed `Z = 70.140 Å`, but pairing still deteriorated:
first DCD frame `66.7%` paired, `45.0%` mean paired, `47.6%` final paired over
`~0.095 ns`; final mean C1' distance `12.50 Å`, final p90 `14.60 Å`.
Temperature was stable (`308.4 ± 2.0 K`), and there were no sentinel energies.

## Conclusion

Reject as a standalone fix. Canonical bridge minimization removes one real
geometry defect and improves the earlier unrestrained fixed-Z result
(`28.6% -> 47.6%` final pairing), but it does not produce a stable unrestrained
periodic duplex. The next iteration should keep bridge minimization and test a
gradual restraint-release ramp, because the loss occurs within the first few ps
after abrupt restraint removal.
