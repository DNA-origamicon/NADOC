---
id: H012
title: B_tube 21 bp periodic segment is stable with retained production restraints
status: complete
date_opened: 2026-05-14
literature:
  - "Single-helix H011 showed the reduced periodic model needs a retained positional restraint floor; B_tube H007 showed full release and low restraint ramps lose base-pair geometry."
parameter_change:
  key: btube_production_restraint_scaling
  from: H007 full release after ramp to 0.03
  to: fixed-Z production with constraintScaling 1.0 retained
baseline_run: H007_relax
test_duration_ns: 0.5
---

## Hypothesis

The full B_tube 21 bp periodic segment can be kept structurally stable in a
fixed-Z production smoke by retaining DNA heavy-atom positional restraints at
`constraintScaling 1.0`.

Confirmation threshold: final C1' pairing fraction `>= 0.95` over 500 ps, with
fixed `Z = 70.140 Å`, stable temperature, and no fatal NAMD errors.

## Mechanism

The single-helix control established that bridge minimization plus retained
restraints can stabilize the reduced periodic model. H007 showed B_tube loses
base-pair geometry as restraints are lowered: `0.50` was already `93.5%` final,
`0.10` was `78.0%` final, and unrestrained production was `~38%` final. The
first B_tube implementation should therefore establish a stable upper-bound
restraint before tuning the floor downward.

## Method

1. Start from the clean H007 fixed-Z restrained restart:
   `results/hyp_runs/H007/output/H007_relax.restart.*`.
2. Run fixed-Z NVT for 250,000 steps from that restart with:
   `rigidBonds all`, `constraints on`, `constraintScaling 1.0`,
   `wrapNearest on`, and standard CUDA.
3. Analyze C1' pairing with `base_pairing.py` and extract NAMD log/XST metrics.

## Expected Outcome

Adopt as a first working B_tube periodic-segment protocol if final pairing is
`>= 95%`. If it passes, tune downward with `0.75`, then `0.60`/`0.50`; if it
fails even at `1.0`, investigate the B_tube constructed geometry or C1' pairing
metric before further production.

---

## Result

Before running H012, the existing H007 fixed-Z stages were re-analyzed:

| Stage | scale | mean paired | final paired | final mean C1' |
|-------|-------|-------------|--------------|----------------|
| H007_relax | 1.00 | 95.5% | 96.6% | 10.47 Å |
| H007_ramp_00 | 0.50 | 93.3% | 93.5% | 10.59 Å |
| H007_ramp_01 | 0.25 | 88.6% | 88.5% | 10.77 Å |
| H007_ramp_02 | 0.10 | 77.7% | 78.0% | 11.06 Å |
| H007_ramp_03 | 0.03 | 64.0% | 61.3% | 11.53 Å |

This made `constraintScaling 1.0` the appropriate first stable implementation
target for B_tube.

H012 started from `results/hyp_runs/H007/output/H007_relax.restart.*` and ran
500 ps fixed-Z NVT with `constraintScaling 1.0`. The run completed with no fatal
NAMD errors.

Base-pairing summary over `~0.498 ns`:

- `504` base pairs identified
- `96.6%` mean paired
- `96.0%` final paired
- mean C1' distance `10.43 Å`
- final mean C1' distance `10.44 Å`
- final p90 C1' distance `11.50 Å`

Log/XST metrics:

- temperature `309.5 ± 0.8 K`, max `311.7 K`
- fixed `Z = 70.140 Å`, std `0.0 Å`
- volume drift `0.0%`
- no fatal errors or sentinel energies
- runtime `1746.7 s` for 250,000 steps, about `24.7 ns/day`

## Conclusion

Adopt as the first working B_tube 21 bp periodic-segment protocol:
bridge-minimized periodic package, fixed-Z NVT, standard CUDA, `rigidBonds all`,
and retained DNA heavy-atom positional restraints at `constraintScaling 1.0`.

This is a stability-first protocol, not the final tuned minimum restraint. The
next tuning step should branch from this success and test `constraintScaling
0.75` for 500 ps, followed by `0.60`/`0.50` if it remains above the `>= 95%`
pairing threshold.
