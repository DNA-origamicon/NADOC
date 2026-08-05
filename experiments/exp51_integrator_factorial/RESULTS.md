# exp51 — timestep × rigidBonds × hydrogen mass, separated for the first time

**Date** 2026-08-05 · **Design** `workspace/2hb_1xT.nadoc` (2 helices × 26 bp; M13mp18
assigned in memory, 52 nt, 0 padded) · **System** 32,754 atoms, cell 44.1 × 66.6 × 113.6 Å,
Mg(H₂O)₆ + CUFIX · **Hardware** RTX 2080 SUPER, NAMD 3.0.2p1 CUDA (`+p8`) · **Report**
`runs/2hb_1xT/exp51_report.json`

One solvation → one minimisation (4,800 steps) → one shared 50 ps restrained NPT
equilibration (2 fs, `rigidBonds all`, k = 0.5, 56.7 ns/day) → 12 cells that differ **only**
in timestep, `rigidBonds`, and which PSF supplies the masses. GPU-resident is absent from
every cell — it is the variable that contaminated the historical comparisons. Each cell
draws fresh 300 K velocities (a velocity set equilibrated under one mass assignment is not
a 300 K distribution under another), runs 25 ps NVT at constant volume, then 10 ps **NVE**
from its own endpoint. Drift is fitted over the last half of the NVE window.

## The matrix

(*) = a combination the shipped code can emit. Everything else is unreachable today.

| cell | dt | rigidBonds | masses | NVT | ns/day | NVE drift (kcal/mol/ns/atom) | C1′ paired |
|---|---|---|---|---|---|---|---|
| `dt1_all_std`  | 1 | all  | std | ok | 23.3 | −8.6 × 10⁻⁴ | 0.947 |
| `dt1_all_hmr`  | 1 | all  | HMR | ok | 25.5 | −1.7 × 10⁻³ | 1.000 |
| `dt1_none_std` (*) | 1 | none | std | ok | 29.1 | **−5.3 × 10⁻⁴** | 1.000 |
| `dt1_none_hmr` | 1 | none | HMR | ok | 27.0 | **+1.9 × 10⁻²** | 0.947 |
| `dt2_all_std` (*) | 2 | all  | std | ok | 49.7 | −1.7 × 10⁻³ | 0.974 |
| `dt2_all_hmr`  | 2 | all  | HMR | ok | 47.3 | −6.0 × 10⁻³ | 1.000 |
| `dt2_none_std` | 2 | none | std | ok | 48.9 | −8.8 × 10⁻³ | 0.947 |
| `dt2_none_hmr` | 2 | none | HMR | ok | 47.0 | **+6.1 × 10⁻²** | 1.000 |
| `dt4_all_std`  | 4 | all  | std | **FAIL** step 4,200 — `Constraint failure in RATTLE for atom 922` | (94.6) | — | — |
| `dt4_all_hmr` (*) | 4 | all  | HMR | ok | **101.5** | +1.9 × 10⁻³ | 1.000 |
| `dt4_none_std` | 4 | none | std | **FAIL** step 0 — velocity limit | — | — | — |
| `dt4_none_hmr` | 4 | none | HMR | ok **FAIL** step 0 — velocity limit | — | — | — |

## Findings

**1. HMR is genuinely load-bearing at 4 fs — now measured, for the first time here.**
`dt4_all_std` (4 fs, rigid bonds, standard masses) had never been run anywhere in this
repo. It fails RATTLE at step 4,200 — i.e. after **16.8 ps**, not immediately. A probe
shorter than that would have scored it stable. The 4 fs ↔ HMR coupling is correct and
should stay.

**2. The 1 fs ↔ `rigidBonds none` coupling is a convention, not physics.**
`dt1_all_std` runs to completion with drift of the same order as the sanctioned
`dt1_none_std` (−8.6 × 10⁻⁴ vs −5.3 × 10⁻⁴ — a 1.6× ratio on a 5 ps fit, i.e. noise). The
code makes this combination unreachable: `_segment_conf` sets `rigid_bonds = "none" if
spec.soft else "all"` and `build_production_conf` hard-codes `rigid="none"` at ts == 1.0.
Nothing measured requires that.

**3. HMR is NOT free below 4 fs, and is actively harmful with flexible bonds.**
Holding dt and `rigidBonds` fixed and swapping only the mass set:

| | standard | HMR | ratio |
|---|---|---|---|
| 1 fs, `none` | −5.3 × 10⁻⁴ | +1.9 × 10⁻² | **35×** |
| 2 fs, `none` | −8.8 × 10⁻³ | +6.1 × 10⁻² | **7×** |
| 2 fs, `all`  | −1.7 × 10⁻³ | −6.0 × 10⁻³ | 3.5× |
| 1 fs, `all`  | −8.6 × 10⁻⁴ | −1.7 × 10⁻³ | 2× |

Both flexible-bond HMR cells also flip the drift **positive** (systematic energy gain) and
are 1–2 orders of magnitude above every other survivor — well outside fit noise. This is
Fix B's mechanism acting generally: repartitioning subtracts mass from the parent heavy
atom, so the heavy-atom librational modes get *faster* while the X–H stretch gets slower.
With `rigidBonds all` the stretch is frozen anyway, so only the harm remains.

**Direct consequence:** `soften_conf_for_stability` — the automatic post-RATTLE rescue —
sets `rigidBonds none` + 1 fs but **keeps the HMR PSF** (md_protocols.py:815-838), on a
comment-level argument that this is safe because repartitioning "only makes the X–H stretch
slower". That is cell `dt1_none_hmr`: the worst-conserving 1 fs combination in the matrix,
35× the plain-mass equivalent. The rescue path lands on the worst cell in its own tier.

**4. The 4 fs speedup is 2.0×, not 2.8×.** With GPU-resident held constant: 101.5 ns/day at
4 fs vs 49.7 at 2 fs = **2.04×**; vs 29.1 at 1 fs = 3.5×. The repo's 2.8× figure came from a
comparison whose 2 fs arm ran resident **on** and 4 fs arm resident **off**.

**5. First energy-conservation evidence that 4 fs + HMR is as well-integrated as 2 fs.**
`dt4_all_hmr` drifts +1.9 × 10⁻³ against `dt2_all_std` at −1.7 × 10⁻³ — same order. This is
*not* the structural equivalence the tree claims (see below); it is the integrator claim,
and it holds.

## What this does NOT establish

- **Structure is underpowered at 25 ps.** C1′ ranges 0.947–1.000 and broken base pairs
  11–15 across *every* survivor including the 1 fs reference; with 38 C1′ pairs one pair is
  0.026, so the whole spread is 2 pairs. Do not rank cells on it. The "4 fs is structurally
  indistinguishable from 2 fs" claim still has no adequate run pair — it needs ns-scale
  sampling, not a probe.
- **The `gentle`/declash tier is untouched.** `2hb_1xT` as it stands carries
  `extra_bases: null` on both crossovers despite its name, so this is a *clean* build. The
  extra-base failure mode that the 2 fs tier exists for is not exercised here and still
  needs a deliberately clashed variant.
- **One design, one replicate, one hardware.** 32.7k atoms, below the GPU-resident
  crossover; nothing here speaks to large systems.

## Correction to the audit that prompted this

The audit hypothesised that exp49's 4 fs arm named a `{stem}_hmr.psf` its own prep call
never wrote, because `prepare_mgh_slow_release` gates `write_hmr_psf` behind `if fast:`
(md_protocols.py:3134-3138) and exp49 does not pass `fast=True`. **That is wrong, and
PHASE 0 of this run disproves it**: both `fast=True` and `fast=False` packages contain the
HMR PSF, because solvation writes it unconditionally at
`namd_solvate.py:2687`, independent of `fast`. exp49's 4 fs arm had a real HMR PSF and its
blow-up was genuine dynamics. Its other confounds (4 fs and HMR moved together; no result
artefact; prepped `declash=False` while governing `declash=True` packages) are unaffected.

## Reproduce

```bash
python experiments/exp51_integrator_factorial/run_matrix.py workspace/2hb_1xT.nadoc \
    -o experiments/exp51_integrator_factorial/runs/2hb_1xT --fresh
```
~11 min end to end. Predictions are pre-registered in the module docstring and scored
automatically; P1 is reported REFUTED only because the 1.6× drift ratio grazes the script's
1.5× tolerance — see finding 2 for why that is a threshold artefact, not a result.
