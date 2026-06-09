---
id: H017
title: B_tube 2-period cell is stable with retained production restraints
status: complete
date_opened: 2026-05-14
literature:
  - "The 1-period B_tube cell requires retained restraints; a 2-period cell tests whether more axial context improves stability."
parameter_change:
  key: btube_periodic_cell_size
  from: 1 period / 21 bp / Z=70.140 Å
  to: 2 periods / 42 bp / Z=140.280 Å
baseline_run: periodic_cell_2x_run
test_duration_ns: 0.1
---

## Hypothesis

The 2-period B_tube cell can be equilibrated as a stable fixed-Z periodic
segment with retained DNA heavy-atom positional restraints at
`constraintScaling 1.0`.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 100 ps, with
fixed `Z = 140.280 Å`, stable temperature, and no fatal NAMD errors.

## Method

1. Build `results/periodic_cell_2x_run/` using
   `scripts/build_btube_periodic_variant.py --periods 2`.
2. Run fixed-Z NVT from the generated PDB with `constraints on` and
   `constraintScaling 1.0`.
3. Analyze C1' pairing with the same `base_pairing.py` metric.

## Expected Outcome

If H017 fails even with retained restraints, the 2x package itself needs
geometry/topology inspection before release testing. If it passes, branch H018+
constraints-off probes from this checkpoint.

---

## Result

The 2x package built successfully in `results/periodic_cell_2x_run/`.
Estimated system size was `332,911` atoms, `Z = 140.280 Å`, `1008` base pairs,
and `4` wrap bonds.

H017 ran direct fixed-Z NVT from the generated 2x PDB with `constraintScaling
1.0` for 100 ps after minimization. It completed with no fatal NAMD errors.

Base-pairing summary:

- `1008` pairs identified
- `95.3%` mean paired
- `97.0%` final paired
- final mean C1' distance `10.57 Å`

Log/XST summary:

- fixed `Z = 140.280 Å`
- no volume drift
- performance `~9.9 ns/day`

## Conclusion

Adopt as the initial 2-period retained-restraint checkpoint. Use
`output/H017_k1_relax_100ps.*` as the branch point for 2x release probes.
