# Periodic MD Experiment Tracker — exp23

Hypothesis cards live in `exp_cards/`. One file per testable claim. Fill **Result** and
**Conclusion** after the run; the framework will not let you skip them.

Run a hypothesis:
```
python experiments/exp23_periodic_cell_benchmark/scripts/run_hypothesis.py H001
```
Extract metrics from any NAMD log:
```
python experiments/exp23_periodic_cell_benchmark/scripts/metrics_extract.py \
    --log results/foo.log --id H001 --out metrics/H001_metrics.json
```

---

## Status Table

| ID   | Hypothesis                              | Status    | Key Result                                    | Decision       |
|------|-----------------------------------------|-----------|-----------------------------------------------|----------------|
| H001 | `rigidBonds all` fixes C1' pairing loss | complete  | bp_fraction=0.323 (↓ from 0.478); P=−124.9 bar | Reject (Z-lock tension dominates; keep rigidBonds all) |
| H002 | `fullElectFrequency 1` (per-step PME)   | pending   | —                                             | —              |
| H003 | `langevinDamping 1` for production      | pending   | —                                             | —              |
| H004 | Isotropic NPT vs locked-Z NVT ensemble  | partial   | production_iso_npt: 56%→14.5% (17.8 ns); Z=70.14 Å IS equilibrium | Blocked: needs clean starting structure |
| H005 | NPT temp spike already fixed in v2      | pending   | —                                             | —              |
| H006 | Combined: H001+H003 (best practice)     | pending   | —                                             | —              |
| H007 | Full pipeline redo with rigidBonds all  | running   | —                                             | —              |
| H008 | Single-helix bridge minimization        | complete  | fixed-Z unrestrained bp_fraction=0.476 final; 100% while restrained | Reject alone; improved but release still destabilizes |
| H009 | Single-helix restraint release ramp     | complete  | 100% through scale 0.10; falls at 0.03/off, final off=0.429 | Reject full release; weak restraint likely needed |
| H010 | Weak production restraint scale 0.10    | complete  | 100 ps final=0.952, but 500 ps final=0.857 | Reject for 500 ps stability |
| H011 | Weak production restraint scale 0.20    | complete  | 500 ps: bp_fraction=0.995 mean, 1.000 final; Z fixed; 231 ns/day | Adopt interim stable protocol |
| H012 | B_tube retained restraint scale 1.0     | complete  | 500 ps: bp_fraction=0.966 mean, 0.960 final; Z fixed; 24.7 ns/day | Adopt first stable B_tube protocol |
| H013 | B_tube abrupt release from k1           | complete  | 100 ps off: first frame 0.812, final 0.492; no NAMD crash | Reject; release collapses immediately |
| H014 | B_tube staged release from k1           | complete  | fails progressively: 0.75 final=0.948, 0.50=0.933, off=0.518 | Reject; not abrupt-shock only |
| H015 | B_tube off with 1 fs + PME every step   | complete  | 20 ps off: first frame 0.849, final 0.629 | Reject; not timestep/MTS artifact |
| H016 | B_tube off in isotropic NPT             | complete  | 50 ps off/NPT: first frame 0.796, final 0.562 | Reject; not fixed-box stress alone |
| H017 | B_tube 2x retained restraint baseline   | complete  | 100 ps k1: bp_fraction=0.953 mean, 0.970 final; Z fixed; 9.9 ns/day | Adopt 2x baseline checkpoint |
| H018 | B_tube 2x abrupt release from k1        | complete  | 100 ps off: first frame 0.524, final 0.377; no NAMD crash | Reject; 2x does not rescue abrupt release |
| H019 | B_tube 2x staged release from k1        | pending   | configured                                    | —              |
| H020 | B_tube 2x off with 1 fs + PME every step | pending   | configured                                   | —              |
| H021 | B_tube 2x off in isotropic NPT          | pending   | configured                                    | —              |

---

## Protocol Decisions Log

**2026-05-10** — Adopted isotropic NPT (`useFlexibleCell no`) for production. Anisotropic
(`useFlexibleCell yes`) caused uncontrolled Z expansion 70→93 Å in ~556 ps.

**2026-05-10** — Discarded locked-Z NVT as primary production ensemble. NPT equilibrium
Z ≈ 67.8 Å vs design Z = 70.14 Å; locking creates 3.4% axial tension inconsistent with
the architectural constraint (DTP-PMD-2 says lock only if studying axial strain).
Ramp stages in locked-Z NVT are kept as equilibration path; production continues with
isotropic NPT.

**2026-05-10** — Identified three additive causes of 47.8% C1'–C1' pairing loss in
5 k-step smoke test:
1. `rigidBonds water` — base N-H/C-H resonance causes local heating at 2 fs integrator
2. `minimize + reinitvels` per ramp stage (old ramp) — v2 ramp removed this
3. 10 ps window is shorter than thermal equilibration of C1' fluctuations

Full production_iso_npt (50 ns) is running with stable energy and T ≈ 310 K,
confirming no catastrophic melting.

**2026-05-10** — H001 (`rigidBonds all`) complete. bp_fraction_final = 0.323. `rigidBonds all`
is correct and must be kept throughout (zero performance cost), but cannot repair a starting
structure that was already damaged during the ramp.

**2026-05-10** — CRITICAL FINDING: `ramp_v2_03` starting structure is already 44% disrupted.
production_iso_npt frame 0 (which starts from ramp_v2_03 coords) shows bp_fraction = 0.562
with mean C1'–C1' = 11.62 Å. Over 17.8 ns, pairing falls monotonically to 14.5% with mean
19.7 Å, p90 = 29.7 Å. Total energy is stable (−652 kcal/mol), consistent with helix-helix
separation in XY rather than base-pair hydrogen-bond breaking.

Root cause: `rigidBonds water` was used throughout the ramp stages (ramp_v2_00 through
ramp_v2_03). N-H/C-H resonance at 2 fs accumulated over 400 ps × 4 ramp stages,
progressively distorting the DNA before the production phase began.

**H003/H004/H006 are blocked until the ramp protocol is redone with `rigidBonds all`.**
**production_iso_npt is running a broken trajectory; recommend stopping.**

**2026-05-14** — Single 21 bp dsDNA periodic helix control added. Baseline
unrestrained runs are mechanically stable but structurally unstable: restrained
NPT and restrained fixed-Z NVT stay 100% paired, but unrestrained isotropic NPT
falls to 42.9% final pairing and unrestrained fixed-Z NVT falls to 28.6% final
pairing over ~100 ps. Dry geometry shows O3'->P copy/wrap distances of 2.066 Å.
H008 tests whether applying canonical local bridge minimization before solvation
fixes the single-helix pairing loss.

**2026-05-14** — H008 completed. Bridge-minimized geometry fixed all adjacent
and wrap O3'--P links to `1.600 Å`, and the restrained fixed-Z NVT stage stayed
`100%` paired through `~105 ps`. Abrupt unrestrained fixed-Z continuation still
lost pairing immediately: first production frame was already `66.7%` paired,
with `45.0%` mean and `47.6%` final pairing over `~95 ps`. Mechanical MD was
stable (`T = 308.4 ± 2.0 K`, no fatal errors, fixed `Z = 70.140 Å`), so H008
improves the baseline but is insufficient by itself. H009 tests whether gradual
restraint release prevents the removal shock.

**2026-05-14** — H009/H010/H011 restraint-floor bracket completed for the
single-helix periodic duplex. H009 showed full release is not stable: pairing
stayed `100%` through `constraintScaling 0.10`, fell at `0.03` (`81.0%` final),
and was `42.9%` final with constraints off. H010 showed `0.10` is too weak for
500 ps (`85.7%` final). H011 adopted `constraintScaling 0.20` as the interim
stable protocol: 500 ps fixed-Z NVT completed with no fatal errors,
`99.5%` mean pairing, `100.0%` final pairing, `Z = 70.140 Å`, and
`~231 ns/day` on the RTX 2080 SUPER/NAMD 3.0.2 CUDA path.

**2026-05-14** — H012 translated the single-helix lesson back to the full
B_tube 21 bp periodic segment. H007 stage analysis showed the B_tube bundle is
more fragile than the single helix under the C1' metric: `constraintScaling
0.50` reached only `93.5%` final and `0.10` reached `78.0%` final. H012
therefore retained `constraintScaling 1.0` for the first B_tube production
smoke. The 500 ps fixed-Z NVT run completed with no fatal errors,
`96.6%` mean pairing, `96.0%` final pairing, `Z = 70.140 Å`, and
`~24.7 ns/day`. Adopt this as the first stable B_tube periodic-segment protocol;
next tuning should bracket downward (`0.75`, then `0.60`/`0.50`) from this
working point.

**2026-05-14** — H013-H016 attempted to reach no-restraint B_tube production
from the stable H012 checkpoint. All no-restraint variants failed structurally
without NAMD fatal errors:

- H013 abrupt fixed-Z release: `49.2%` final paired over 100 ps; first saved
  frame already `81.2%`.
- H014 staged release: degradation begins before full release; `0.75` final
  `94.8%`, `0.50` final `93.3%`, `0.10` final `80.2%`, off final `51.8%`.
- H015 1 fs + `fullElectFrequency 1`: `62.9%` final paired over 20 ps.
- H016 isotropic NPT with constraints off: `56.2%` final paired over 50 ps.

Current theory: the 21 bp B_tube periodic segment is not self-supporting under
the current C1' pairing metric when DNA positional support is removed. This is
not primarily a crash, timestep artifact, fixed-Z stress, or abrupt-release
shock. More likely causes are residual construction/reference strain, missing
longer-range origami context, insufficient crossover/connectivity constraints
inside a single 21 bp repeat, or the fact that positional restraints are doing
essential architectural work in this reduced model. The best current production
protocol remains H012 (`constraintScaling 1.0`); unconstrained production should
not be advertised as stable until the geometry/model is changed.

Design Z = 70.14 Å IS the isotropic NPT equilibrium (tail mean = 70.144 Å, std = 0.026 Å
from 17888-frame XST tail). H004's original "Z ≈ 67.8 Å" premise was wrong; Z-lock tension
is not the primary issue. Hypothesis H004 has been revised to test NPT vs NVT ensemble quality.

---

## Metrics Schema

`metrics/HXXX_metrics.json` — see `scripts/metrics_extract.py --help`.

Key fields used for decisions:
- `temperature.mean` — should stay 308–312 K
- `temperature.max` — must not exceed 350 K (DNA Tm in 150 mM NaCl)
- `pressure.mean` — should be ≈ 0 bar in isotropic NPT
- `volume_angstrom3.drift_pct` — < 1% acceptable
- `z_cell_angstrom.std` — < 0.05 Å in locked NVT, free in NPT
- `bp_fraction_final` — C1'–C1' ≤ 12 Å; target > 90% at end of 500 ps unrestrained
- `fatal_errors` — must be empty

---

## Adding a New Hypothesis

1. Copy `exp_cards/_template.md` to `exp_cards/HXXX_short_name.md`.
2. Fill all frontmatter fields and the Hypothesis/Method/Expected sections.
3. Add a row to the Status Table above (Status = `pending`).
4. Run with `run_hypothesis.py HXXX`.
5. Fill Result + Conclusion in the card. Update the table.
