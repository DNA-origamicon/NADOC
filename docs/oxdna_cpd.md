# CPD isomers in oxDNA

NADOC provides separate provisional interactions for **cis-syn-I** (`cis-syn`),
**cis-anti-I**, **trans-syn-I**, and **trans-syn-II**. Select two thymines, choose
**Convert to CPD…**, select the isomer, and create an oxDNA relaxation. Local managed jobs select the CPU
interaction automatically. The weld persists through equilibration, production,
copied jobs, and continuations; it is not a temporary relaxation restraint.

This is an experimental structural model. Successful job execution and numerical
validation do **not** establish accurate CPD melting temperatures, isomer yields,
or transferability from a crossover weld to an ordinary duplex lesion.

## Model and evidence

`scripts/fit_oxdna_cpd.py` extracts the two thymine particle frames from retained
NAMD trajectories. The base site is the six-membered-ring centroid. The first
axis points from C1′ to that centroid; the third axis is the orthogonalized,
negative N1–C2–C6 normal. The oxDNA centre is the centroid minus 0.4 reduced units
along the first axis. The same projection prepares authored CPD particles.
Coordinates are derived simulation inputs, never changes to authored atoms.

Each fit uses 5–20 ns from its October 18 and October 19 replicas, sampled
every 100 ps. The October 22 replica is reserved for comparison in this fit;
it was previously inspected and is not a blind validation dataset. Longer HMR
trajectories are not pooled into this ordinary-mass fit. Source paths, topology
and parameter-manifest hashes, sample times, and mapped-sample hashes are in
the individual `backend/data/oxdna/cpd_*_v1.json` files.

Four virtual sites on each rigid nucleotide give sixteen interparticle distance
springs. Their reference lengths come from the mean relative pose. Positive
spring constants approximate the six-dimensional covariance precision multiplied
by kBT. The regularization floor and relative Hessian fitting error are recorded in each
parameter file. Errors are 0.217 (cis-syn-I), 0.571 (cis-anti-I), 0.458
(trans-syn-I), and 0.186 (trans-syn-II). The larger errors for cis-anti-I and
trans-syn-I mean these springs are a coarser approximation of the sampled
covariance; runtime success does not eliminate that modeling error. This is a conditional effective fit:
environmental restoring forces contribute to the atomistic covariance, and
transfer can double-count their effect. It is not an isolated chemical force fit.

The native `CpdDNA2` interaction replaces the reacted pair's ordinary base-base
terms with this permanent rigid-body interaction. Existing backbone connectivity
is retained. Interactions with third nucleotides remain ordinary DNA2; no altered
hydrogen-bond strengths, stacking thermodynamics, or temperature dependence have
been fitted. The NAMD Mg-containing solvent is not asserted equivalent to the
oxDNA monovalent salt parameter. Thermal ranking requires additional validation.

## Execution and reproducibility

The CPU plugin supports both ordinary adjacent TT and non-backbone weld
connections without repurposing backbone neighbours. Additional bonded-pair
bookkeeping keeps nonadjacent welds active independently of neighbour-list
cutoffs. Both forces and body-frame torques derive from the same potential.
MD uses a maximum timestep of 0.0001 reduced units for this stiff interaction.

The standard engine installer builds the plugin. For an existing engine:

```sh
python tools/oxdna_cpd/build.py
```

Every prepared job freezes `cpd.dat`, `cpd_model.json`, `cpd_manifest.json`, and
`cpd_plugin/`. Hashes bind the interaction, model, topology and native plugin.
Each endpoint record identifies its isomer. A job containing different isomers
freezes a model bundle and writes the appropriate springs for each pair.
Continuation and copy routes inherit those inputs. Unsupported isomers and
incompatible interaction models are rejected instead of silently dropping CPDs.
This initial implementation targets local CPU DNA jobs, not CUDA, LAMMPS,
protein/PEG/gold hybrids, or remote plugin deployment.

`scripts/validate_oxdna_cpd.py OUTPUT --isomer ISOMER` authors a duplex through real editor
commands, assigns the selected isomer, publishes through the agent structure guard, checks
saved/reopened independent replay, and drives managed relaxation followed by a
one-million-step production stage. It preserves health gates and retries and
checks trajectory display availability. `scripts/check_oxdna_cpd_forces.py`
independently checks native forces and torques by finite differences against a
prepared job. Validation evidence must report actual outcomes, including failed
attempts, separately from the scientific limitations above.

Related precedent: [Lim et al., Nucleic Acids Research (2022)](https://doi.org/10.1093/nar/gkac082)
calibrated an intrastrand thymine-dimer oxDNA model against structural and melting
measurements. Its parameters are not substituted for this crossover-derived fit.

## Reproducing the additional isomers

The registered training/comparison job IDs are explicit in
`scripts/fit_oxdna_cpd.py`. Extraction verifies the NAMD manifest's isomer and
requires the registered 1,000-frame, 20 ps cadence trajectories. Each new fit
uses 300 training samples; no data are pooled across isomers.

```sh
uv run python -m scripts.fit_oxdna_cpd --isomer trans-syn-I --output parameters.json
uv run python -m scripts.validate_oxdna_cpd_isomers .development-artifacts/cpd-isomer-validation
```

The second command runs the three additional isomers serially, retaining all
failures. For each it publishes and independently replays an authored 16 bp
example, runs managed relaxation/equilibration/production, checks native
force/torque derivatives, and runs a separate Full Sim continuation. All jobs
use the normal 50% base-pair-retention gate and normal retry budget.

The broader assignment contract is version 3, in a separate module. The
existing cis-syn version 2 contract and its source pins remain intact, so the
previously delivered example remains replayable. No molecular placement
algorithm or authored atom coordinates were changed by this extension.

## Additional-isomer validation — 2026-11-16

Evidence: `.development-artifacts/cpd-oxdna-isomers-v1/native/results.json`.
All three runs passed managed relaxation, 100,000-step equilibration, 1,000,000
production steps, and a separate 1,000,000-step Full Sim continuation. All six
production trajectories load and have 100 finite, orthonormal saved frames.
No health thresholds were reduced; the default 50% retention gate was retained.

| Isomer | Relaxation + production job | Full Sim child | Relaxation retries | Final parent BP retention | Maximum derivative error |
|---|---|---|---:|---:|---:|
| cis-anti-I | `c5b5881c3904` | `d2d5a5eced57` | 1 | 68.75% | 1.93e-08 |
| trans-syn-I | `31e2c993abd5` | `1be3779ea07a` | 1 | 100% | 1.61e-08 |
| trans-syn-II | `12a9a871dd97` | `1d3e9e3ae45b` | 2 | 62.5% | 2.67e-08 |

Every example passed publication, saved/reopened independent replay, and a final
independent audit (four recorded commands each). The old cis-syn-I example still
passes its original version-2 replay. All four browser cases passed assignment,
CPU/model display, job creation, settings edits and package copying. The rendered
assignments were inspected; test parts, jobs, project histories and screenshots
were removed. Focused CPD contracts: 26 passed; existing conversion checks:
13 passed; frontend: 10,629 passed, one skipped. `main.js` LOC delta: 0.
Final backend `test-smart` decision: **FAST**, 20,913 passed, 90 skipped.
FULL remains deferred (the exact deferral is quoted below). Aggregate runtime
was 187 seconds with zero per-test budget violations; the existing timing warning
remains and no budget or test-session guard was weakened. Lint passed. The
post-fix browser cleanup recheck passed without the deleted-job warning.

The browser cleanup exposed a pre-existing deferred-analysis/deletion race:
background workers could load a job after it had been deleted. ISSUE-202 now
makes that missing-job load an empty operation while preserving errors for
corrupt manifests; four focused cases pass. This does not change simulation
physics or suppress errors from present jobs.

## Completed local validation — 2026-11-15

Evidence is retained in `.development-artifacts/cpd-oxdna-workflow-v4/`:

- `cis_syn_duplex.nadoc`: a 16-bp duplex with forward positions 6/7 converted to
  cis-syn-I. Publication, saved/reopened audit and independent replay all pass
  with four recorded construction commands and no recovery snapshots.
- Job `93fa6ac63e1c`: CPU MC 10,000 steps; MD relaxation initially 1,000,000
  steps, followed by the ordinary 3,000,000-step retry; equilibration 100,000;
  production 1,000,000. Completed without a terminal failure. Final base-pair
  retention was 56.25%, above the unchanged 50% gate.
- Job `be9f05d5029c`: separate Full Sim continuation through the normal `/run`
  handler, another 1,000,000 steps. Completed; trajectory display ready.
- Both production trajectories: all 100 saved frames have finite particle rows
  and orthonormal axes; permanent CPD package hashes verify; external relaxation
  forces are off. Mean virtual-site distance RMS deviations are 0.093 and
  0.075 nm, respectively. These are execution diagnostics, not convergence gates.
- Native central-difference audit: maximum absolute force/body-torque error
  `3.06163343566368e-08`, with zero net pair force.
- Browser workflow: ordinary T–T selection → Convert to CPD → cis-syn-I →
  Dynamics/oxDNA → prepared job; displayed CPU/model/timestep, settings edits,
  and frozen-package copying passed. The rendered pair was inspected. All
  browser-created parts, jobs and screenshots were removed afterward.

Earlier development attempts are not counted as passes. The v1 preparation
exposed the missing native-to-particle projection; v2 completed relaxation;
v3 relaxed successfully but production failed because a newly added package
hash field was absent from the package prepared before that code edit. V4 was
prepared and run with the complete package format. Historical attempts remain
under `/media/jojo/Archive/nadoc-dev-artifacts/cpd-oxdna-workflow-v[1-3]` on this
workstation; those prototype files are not release examples.

To reproduce a separate Full Sim continuation after the validation script:

```sh
uv run python -m scripts.validate_oxdna_cpd OUTPUT --continue-job JOB_ID
```

The browser check is deliberately opt-in:

```sh
NADOC_CPD_OXDNA_REVIEW=1 scripts/validation_guard.sh \
  frontend/node_modules/.bin/playwright test --config frontend/playwright.config.js \
  cpd_oxdna_workflow.spec.js --workers=1
```

This establishes a usable local CPU workflow for this isomer, not an assurance
for every topology or optional engine configuration. In particular, the small
production runs above do not validate relative melting temperatures. Temperature
sampling, duplex/open-state thermodynamics and experimental or independently
validated reference comparisons remain necessary before isomer ranking.

Software regression results: `just test-smart` selected **FAST** and passed
20,909 tests (90 skipped); frontend passed 10,629 (one skipped); final focused
CPD contracts passed 6, existing conversion tests passed 13, and wizard-model
checks passed 23. `just lint` passed. The saved/reopened part was independently
audited again after implementation was complete.

The repository's slow-test triage classified the actual native electrode
compilation test into the NAMD slow group. The other initially slow VR-build
and protocol-trimming checks have mocked/no native execution and were left in
the fast group; the final rerun had **zero per-test budget violations**. Aggregate
runtime remained 196 seconds for roughly 21,000 tests; no timing guard or budget
was weakened. The broad-suite deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```
