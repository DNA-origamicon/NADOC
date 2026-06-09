---
id: H005
title: NPT temperature spike (394 K) already fixed by starting from locked-NVT restart
status: pending
date_opened: 2026-05-10
literature:
  - "Feenstra et al. (1999) J. Comput. Chem. 20:786 — initial velocity spike from density mismatch in solvation"
  - "NAMD user guide — recommended pre-equilibration before NPT: NVT to relax box, then enable barostat"
parameter_change:
  key: NPT start coordinates
  from: initial solvation box (over-padded, 161×157 Å → water at wrong density)
  to: locked-NVT restart at 155×151 Å (near-equilibrium density)
baseline_run: initial_solvation_pdb
test_duration_ns: 1.0
---

## Hypothesis

The 394 K temperature peak observed in the smoke NPT run was caused by the previous
version of `equilibrate_npt.conf` starting from the raw GROMACS solvation coordinates
(over-padded 161×157×70 Å box, water not equilibrated). The current version already
starts from the `relax_locked_nvt` restart, which is at ~155×151×70 Å and has
pre-equilibrated water density. Therefore, the 394 K spike will not recur in any future
run using the current generated package.

This hypothesis is **confirmatory** — testing that the known fix is actually working,
not proposing a new change.

## Mechanism

GMX solvate places water molecules by excluding volumes, but the resulting water
configuration is not in thermal equilibrium. When a pressure-coupled NPT is started
directly from this state, the barostat tries to compress the over-padded box rapidly;
the sudden compression causes water molecules to collide, injecting kinetic energy into
the local environment → temperature spike. The spike duration depends on barostat
time constants (period 200 fs, decay 100 fs here) and the magnitude of the
initial density mismatch.

Starting from the locked-NVT restart at ~bulk density avoids this entirely.

## Method

1. Run `equilibrate_npt.conf` as currently written (starts from `relax_locked_nvt` restart).
   This is the standard workflow — no parameter changes needed.
2. Monitor temperature trace from the log: look at the first 5,000 steps (10 ps)
   where the spike would appear.
3. Run `metrics_extract.py`, check `temperature.max`.

## Expected Outcome

- `temperature.max` < 350 K throughout the run (vs 394 K in old version): **confirms fix**
- `temperature.mean` 308–312 K
- If `temperature.max` > 360 K: the current restart state is still too far from
  equilibrium; check whether NAMD `reinitvels` was used before starting NPT

---

## Result

*(Fill after run.)*

## Conclusion

*(Confirms / Refutes the fix. If confirmed: document that the two-phase protocol
(locked-NVT first, then anisotropic NPT) is required for safe box discovery.)*
