# Gold restart discrepancy: diagnosed and corrected

2026-09-15. The dominant discrepancy was NAMD's **default removal of center-of-mass
velocity at restart**, not a demonstrated failure of the gold force field or the
slab correction. New gold restart configurations now set `COMmotion yes`.

## Basis for the diagnosis

The [NAMD 3.0 Dynamics documentation](https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node37.html)
specifies COMmotion=no by default and explains that initialization removes COM
motion, although external forces, restraints and Langevin noise can subsequently
generate it. [NAMD developer guidance](https://www-s.ks.uiuc.edu/Research/namd/mailing_list/namd-l.2015-2016/0620.html)
explicitly confirms this also happens when reading restart velocities.

The local source corroborates this: `WorkDistrib.C:690–715` reads binary velocities
then calls `remove_com_motion` unless `comMove` is true. Its implementation at
3448 subtracts the mass-weighted mean velocity from every atom. `SimParameters.C:625`
sets the default false. The original gold configuration generator omitted this option.

Early inspection also identified constrained-integrator startup operations in
`SequencerCUDA.C:1970–2260`. Controls ruled these out as the dominant discrepancy:
the effect persists with flexible water and affects gold and ions as well as water.
Removing gold restraints substantially reduces it, consistent with eliminating
a source of net momentum. The zero-step velocity shift is approximately uniform
across all atoms and matches the checkpoint's independently computed COM velocity.

### Quantitative causal check

`particle_rigid` and `slab_rigid` reproduce the old default at 1 fs. A zero-step
restart changes coordinates only at ~1e-14 Å, but changes velocities. For total mass
M and saved COM velocity V, subtracting V predicts ΔK = −M|V|²/2.

| System | Measured ΔK, kcal/mol | Predicted ΔK, kcal/mol | Max velocity residual after subtracting predicted COM shift, Å/AKMA |
| --- | ---: | ---: | ---: |
| Particle | −0.004916469 | −0.004916355 | 1.38e-8 |
| Two gold slabs | −0.021123327 | −0.021123289 | 1.67e-8 |

With `COMmotion yes`, corresponding zero-step kinetic changes are −1.09e-7 and
−4.32e-8 kcal/mol; maximum velocity changes are 7.87e-9 and 1.51e-8 Å/AKMA.
These are observations, not proposed universal tolerances. The binary arrays use
NAMD's Å/AKMA velocity units; mass-weighted kinetic energy is in kcal/mol.
Raw calculations: [impulses.json](impulses.json), [mechanism.json](mechanism.json),
[preserve_com.json](preserve_com.json).

## Corrected generator and repeated-run control

Fresh native runs use the actual corrected shared generator, pinned engine,
full binary checkpoints, unchanged atom order, 1 fs, no thermostat or barostat.
The slab retains its GPU EW3DC correction. Compare 40 continuous steps against
20+20, and independently repeat the continuous run from the identical checkpoint.

| System | Split max Δr, Å | Split max Δv, Å/AKMA | Repeated continuous max Δr, Å | Repeated continuous max Δv, Å/AKMA |
| --- | ---: | ---: | ---: | ---: |
| Particle | 3.46e-6 | 1.46e-5 | 3.52e-6 | 1.12e-5 |
| Two slabs | 3.69e-6 | 1.83e-5 | 2.85e-6 | 1.17e-5 |

The residual is comparable in scale to variability between repeated uninterrupted
GPU runs. This supports treating it as numerical reproducibility sensitivity;
it does not prove the origin of every residual component or long-time equivalence.
Both corrected cases happen to fall below the old 1e-4 threshold, but that threshold
has no established physical basis and is not the reason this correction is accepted.
The decisive evidence is the predicted, observed, and removed momentum impulse.

A solvent-only control, obtained by deleting Au while retaining the solvent state,
has max split Δv of 1.69e-5 by default and 1.35e-5 with preserved COM motion. This
has a cavity and is **not a bulk-water equilibrium reference**. It helps demonstrate
that residual differences of this order also occur without gold or its restraints.
See [fixed_generator.json](fixed_generator.json) and [solvent_control.json](solvent_control.json).

## Literature-based physical check, and its limits

[Merz and Shirts (2018)](https://doi.org/10.1371/journal.pone.0202764) describe
integrator validation through NVE energy conservation and timestep scaling:
second-order symplectic integration should have total-energy fluctuations scaling
quadratically with timestep in the applicable numerical regime. This is a physical
test with a theoretical basis, unlike requiring atomwise trajectory identity.

Six bounded NVE runs cover 4 ps each at 2, 1 and 0.5 fs, starting from the same
saved state per geometry, with preserved COM motion and energy output every step.
The table uses ordinary TOTAL energy (not the GPU running average TOTALAVG), over
the common 0.2–4 ps window. No fitted acceptance percentage is imposed.

| System | σ(E), 2 fs | σ(E), 1 fs | σ(E), 0.5 fs | Ratios 2→1 / 1→0.5 |
| --- | ---: | ---: | ---: | ---: |
| Particle | 0.43089 | 0.11271 | 0.04491 | 3.82 / 2.51 |
| Two slabs | 0.31707 | 0.07963 | 0.03490 | 3.98 / 2.28 |

Energy units are kcal/mol. The 2→1 fs reduction is consistent with the expected
factor of four. The 1→0.5 fs reduction is not; this short study does **not** establish
quadratic convergence across the entire range. Finite precision, tabulated forces,
mesh accuracy and finite sampling are possible contributors, not diagnosed causes.
Native logs report force/energy table inconsistencies near the cutoff. Measured
linear slopes range −0.0227 to +0.0139 kcal/mol/ps and are descriptive only: four
picoseconds is insufficient to certify long-time drift or equilibrium sampling.
See [energy plot](energy_convergence.png) and [nve_energy.json](nve_energy.json).

The restart question is resolved without extending this into a campaign to force
a numerical ratio to pass. Further force-table/PME precision and longer energy
controls belong to separate numerical qualification, alongside density/hydration
validation. These results do not qualify adsorption, applied voltage or Au–S chemistry.

## Changes and retained evidence

- `backend/core/namd_gold_package.py`: set COMmotion=yes when reading a restart;
  fresh velocity initialization retains NAMD's existing default.
- `tests/test_gold_interfaces.py`: guard the restart-versus-fresh configuration contract.
- `experiments/gold_interfaces/restart_probe.py`: report the old threshold comparison
  explicitly as historical, with no physical pass/fail claim. Native execution and
  finite-state failures still raise errors. Add source/tag/timestep CLI controls.
- Saved historical packages, verdicts and checkpoints remain unchanged. This fix
  applies to newly generated configs, including future completed-stage continuations.
  Previously queued configs retain their original behavior and input hashes.
- Partial-stage recovery remains unimplemented; no installed engine was modified.

The diagnostic directory retains configs, native logs, copied initial checkpoints,
outputs, scripts and input/engine hashes. A diagnostic Python argument-type error
and one solvent control missing its required PDB were corrected; their failed logs
remain in `driver.log`, `controls.log`, and `solvent_only/default_full.log`. The
corrected solvent preparation is `solvent_only_v2`. Neither was a dynamics failure.

Engine SHA256: `2fda225c5f8838e5dbcb6a4e6a3e7e337f498df61cae2e6e320f994cb7c8b9bf`.
Slab plugin SHA256: `f2970cc4400abe0dbb4dd7bfe88ad7a46d53249f246bcbb1994db18b64a020ce`.

For a fresh diagnostic using retained copied inputs:

```bash
uv run python -m experiments.gold_interfaces.restart_probe \
  workspace/gold_restart_diagnosis_20260915/particle_fixed_generator \
  --binary /home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3 \
  --source seed --tag review_repeat --dt 1
```

Use a new tag on every invocation. `diagnose.py` intentionally reconstructs the
historical COM default for its controls; inspect the per-run configs to distinguish
controls from the corrected generator. `controls.py` records impulse and energy analysis.

## Verification

Focused gold tests: **20 passed**. Scoped Ruff and `git diff --check`: passed.
Required `just test-smart` selected **FAST**: **8,438 passed, 110 skipped, 9 failed**.
The nine failures are missing BigO/smallO workspace fixtures in assembly/CanDo,
also present in the prior review. [Full output](test-smart.log).

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

No browser validation was needed for this backend/configuration change.
