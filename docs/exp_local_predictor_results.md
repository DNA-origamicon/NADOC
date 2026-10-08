# Connectivity-aware predictor candidate (2026-10-07)

This is an isolated screening experiment. The installed Exp preview remains the
six-mode strain pilot until the candidate's geometry and validation evidence has
been reviewed. No native builder, topology, helical constants, export or NAMD seed
path is changed.

## Mg recipe and running 24HB control audit (2026-10-07)

The original 0×T training jobs used Na counterions plus MgCl2; newer extra-base
jobs used Mg counterions. Their labels therefore confound salt with extra bases.
Direct census of the Aksimentiev tutorial gives DNA charge -865 e, 516 hydrated
Mg and 167 chloride ions. The guide does not prescribe a universal 12.5 mM.
NADOC now interprets requested MgCl2 as added salt **after** Mg neutralization,
rather than max(counterions, salt). New charge audits record
`concentration_convention: added_salt_after_neutralization`; existing packages
retain their original ions. Focused ion tests: 13 passed; backend FAST suite:
9,978 passed, 90 skipped. Full-suite validation remains deferred without a session.

A real isolated default Fast preparation for archived 24HB 0×T verified 3,322
neutralizing Mg + 327 added MgCl2, 654 Cl and no Na in both normal/HMR PSFs.
All 22 stage configurations use those PSFs and retain Mg restraints/CUFIX;
remote transfer selection includes the same inputs. Three plan/config tests pass.
Counts depend on solvent volume; this preparation was not submitted or run.

A separate read-only inspection of running RunPod job `8466ccc17eff` found:

- Actual box 25.79 × 25.34 × 63.57 nm, 6 nm initial padding per face;
  measured nearest DNA-heavy-atom periodic image separation 12.004 nm initially.
  No dynamics were available: the job was still minimizing. Six nm is consistent
  with the previous approximately 5.7–6.0 nm envelope allowance, but arbitrary
  rotation is not accommodated and later stages have no orientation restraint.
  Recheck clearance after NPT contraction and throughout unrestrained production.
- Actual ions: 3,613 MGH (3,322 counterions + 291 MgCl2), 582 Cl, no Na.
  Total Mg per preparation solvent volume is about 155 mM versus 518/546 mM
  for archived 1×T/2×T. These include counterions; none measures free bulk Mg.
- **OPEN ISSUE-62:** submitted 4 fs relaxation files specify
  `fullElectFrequency 2` (8 fs PME), contradicting the manifest's frequency 1.
  Archived extra-base production uses frequency 1 (4 fs PME). This establishes
  a cadence/reporting mismatch, not observed instability. The prior Fast audit
  established ion consistency but missed this independent discrepancy.
- The remote chain enables energy/base-pair-based early stopping, including k=0.
  This does not certify equilibrium shape. Do not train on restrained stages or
  interpret the completed ladder as a converged production ensemble.
- Archived 1×T/2×T use much smaller boxes; the previous eight-frame C1′ screen
  found image distances down to 0.68/0.38 nm. These are proximity proxies, not
  an energy analysis, but require qualification before causal extra-base claims.
- Main CHARMM36 NA/CUFIX files match. Temperature and 4 fs/HMR match historical
  production; relaxation thermostat/barostat coupling differs. Compare matched
  unrestrained production, preferably rerunning all 0/1/2×T controls with matched
  salt convention and periodic clearance, replicas, and convergence checks.

No live job, pod, or submitted configuration was altered by the audit. PME-cadence
correction and reference-run qualification remain outstanding. The installed Exp
baseline is unchanged; neither neural pilot is approved for molecular seeding.
Evidence: `.development-artifacts/mg_recipe_audit_20261007/`,
`.development-artifacts/mg_fast_audit_20261007/`, and
`.development-artifacts/runpod_8466_audit_20261007/` (local artifacts, not bundled).
The electrostatic cadence interpretation follows the
[NAMD 3.0 guide](https://www.ks.uiuc.edu/Research/namd/3.0/ug/node37.html).

## Expanded data and GPU pilot (2026-10-07, later follow-up)

The user authorized additional 6HB/larger and square-lattice trajectory assessment,
extra-base training experiments, an Alpine availability check, and up to **$3 total**
Runpod testing. This follow-up is complete. Evidence and executable experiment
scripts are under `.development-artifacts/exp_expansion_20261007/`.
**The installed Exp model is unchanged.** The neural checkpoints below are short
training benchmarks, not qualified replacement predictors or NAMD seeds.

### Inventory and label qualification

A refreshed read-only scan found 1,664 DCDs (1.85 TB), 671 job records,
113 jobs with trajectories, and 42 jobs with production-named trajectories.
Related continuation files and preparation descendants are not independent designs.
All relevant production-job candidates were triaged; additional large unregistered
VoltronCore/B-tube trajectories were inspected separately. Long periodic-cell and
chemically modified/umbrella fragment data were not pooled with free intact origami.

| Additional case | Longest selected production file | Sampled late window | Core C1 first/last block difference |
|---|---:|---:|---:|
| 24HB 1×T / 6950d3b79138 | 223.64 ns | 111.84–223.64 ns | 0.572 nm |
| 24HB 2×T / fc12195d0636 | 215.50 ns | 107.76–215.50 ns | 0.565 nm |
| 6HB 2×T / cb616816195f | 7.00 ns | 3.51–7.00 ns | 0.509 nm |
| 18HB square / 983f5c8e66bc | 28.18 ns | 14.10–28.18 ns | 0.605 nm |

The 24HB variants are the strongest additional *finite-window* candidates. Neither
long duration nor stable radius of gyration certifies equilibrium. Their block
RMS fluctuations are about 0.32–0.34 nm. The square case fluctuates about 0.23–0.25 nm
within blocks while its mean moves farther between blocks. The older 3×4 square
job has a longest selected 2.5 ns segment, 310 K conditions and no recovered immutable
mapping in this experiment; it is unsuitable for pooling with the 300 K pilot.
VoltronCore A/B late block shifts are 2.06/1.61 nm (unwrapped qualification pending),
and B-tube F028 shifts 0.565 nm across a roughly 2 ns late window. These are not
additional qualified equilibrium shapes.

All six extracted designs (the original two plus the four rows above) pass exact
native/trajectory DNA atom-identity, atom-order and covalent-bond checks. All DNA
atoms, including hydrogens and **1,062 extra-base residue instances**, are retained.
The 24HB variants share a structural family; those instances are not independent
origami designs. The 6HB 2×T design is also shorter (656 nt versus 1,328 nt for 6HB
0×T), so the comparison is not a controlled insertion-only intervention.

Actual PSF composition exposes a major confound: 24HB 0×T has 6,644 Na, 103 hydrated
Mg and 206 Cl; 24HB 1×T/2×T have 3,491/3,660 hydrated Mg and no Na/Cl. 6HB 0×T
uses Na plus hydrated Mg/Cl; 6HB 2×T and square use Mg counterions. A protocol
indicator is provided to the neural network, but cannot disentangle effects absent
matched examples. Do not attribute gains specifically to extra-base mechanics.

A 128-frame covalent-continuity check found maximum DNA bond lengths below 0.175 nm.
An additional eight-frame orthorhombic periodic-image screen found minimum **C1-to-C1**
image separations of 0.57/0.68/0.38 nm for 24HB 0/1/2×T and 0.55 nm for square.
These are image-proximity diagnostics, not minimum heavy-atom distances or interaction
energies. Square paired-C1 separations above 1.5 nm rise from ~2.5% to ~4.0% of
mapped pairs across the sampled window; the other cases remain below 0.6%.
This argues against treating square as a clean equilibrium training target.

Extra-base coordinate means are particularly problematic: median heavy-atom residual
after the best rigid-nucleotide fit to each mean is 0.103–0.112 nm for extra bases,
versus ~0.023–0.029 nm for the corresponding core nucleotides. Flexible state averaging
and internal deformation need to be distinguished with frame/state-aware targets;
more parameters do not make an averaged coordinate cloud a physical conformation.

### Does the extra-base data help?

The same 519-coefficient model and unconstrained rigid-nucleotide reconstruction
were compared with zero-extra-base-only versus expanded training. Entire 6HB or
24HB families were held out; square was always excluded from training. Errors below
use one core-C1 alignment and all atoms in the indicated group. They are not directly
interchangeable with the earlier paired-midpoint/angle-projected table.

| Held-out case / observable | Zero-only training | Expanded training |
|---|---:|---:|
| 24HB 0×T, all atoms | 0.834 nm | 0.722 nm |
| 24HB 1×T, extra-base atoms | 0.861 nm | 0.777 nm |
| 24HB 2×T, extra-base atoms | 1.339 nm | 1.186 nm |
| 6HB 2×T, extra-base atoms | 0.843 nm | 0.752 nm |
| 6HB 0×T, all atoms | 0.557 nm | 0.553 nm |
| Square, all atoms | 1.057 nm | 1.092 nm |

Thus added data can improve local extra-base prediction (~10–11%) but does not
uniformly improve transfer. Square gets worse. Short 6HB 2×T sampling, protocol
confounding, image proximity, finite-window variability and limited independent
families prevent a general superiority claim.

### Actual GPU measurements and budget

At 17:08 MDT October 7, the authenticated NADOC Alpine connection showed all A100
and H200 nodes in maintenance/down/drain states. Their maintenance reservations end
**06:30 MDT October 8**; no start within an hour was credible. No Alpine job was
submitted, canceled or changed.

One Secure Cloud RTX 4090 pod was rented at its live $0.74/hour quote. It had a
one-hour provider expiry plus a separate exact-pod systemd watchdog and controller
cleanup. Two 240-update supervised bursts completed; all results/checkpoints were
retrieved and the pod was deleted, with provider absence confirmed. Rental lifetime
was 90.88 seconds, giving **$0.0187 estimated compute cost**; the ledger also reserves
$0.10 conservatively for disk overhead. This is below the $3 authorization. Account
balance had not yet reflected the charge when checked; this is not a finalized invoice.
No local GPU or new MD was used, and no further pod was left running.

The network is a five-layer message-passing model, with widths 128 and 384. Inputs
include existing local frame/connectivity features, explicit extra-base identity and
a protocol indicator. It retains every covalent/paired edge and at most eight spatial
neighbors per nucleotide. Rotation and relative-displacement losses train nucleotide
poses; a sparse graph solve plus rigid nucleotide reconstruction outputs every atom.
This benchmark loss has **no atomistic energy, torsion, steric or non-crossing term**.
It measures feasible neural infrastructure, not the final constrained architecture.

Training uses the three 24HB variants only; both 6HB designs and square are held out.
Normalization uses training designs only. Benchmark forward/backward passes do not
update weights, and initialization is restored before training. Platform has no labels:
its backward pass uses a synthetic objective exclusively to measure memory/time.
All graphs are resident on the GPU, one graph per optimization update, FP32.

| Measurement on RTX 4090 | 644,614 parameters | 5,177,862 parameters |
|---|---:|---:|
| 240 AdamW training updates | 3.51 s | 13.07 s |
| 24HB 2×T forward/backward | 0.0146 s | 0.0555 s |
| 24HB 2×T peak allocated memory | 1.99 GB | 4.71 GB |
| Platform forward/backward | 0.0280 s | 0.1043 s |
| Platform peak allocated memory | 3.43 GB | 8.56 GB |
| Maximum recorded allocator reservation | 4.63 GB | 11.28 GB |

Per-graph memory timings precede optimizer-state initialization; the timed 240-update
training runs include actual optimizer updates. The 5.18M model's FP32 Adam state adds
about 41 MB. CPU forward/backward on 6HB was 2.24 s with peak process RSS ~1.70 GB.
A 24 GB 4090 is sufficient for the measured sparse architecture; A100/48–80 GB is
not necessary. This does not establish memory needs for a dense all-atom graph or
future all-atom differentiable energy losses.

The early neural outputs are not seed-quality: the 5.18M model's held-out all-atom
RMS is 0.601 nm (6HB 0×T) and 0.727 nm (6HB 2×T), with 35/63 ring piercings in its
unconstrained reconstructions. The smaller network is not consistently worse.
These 240-update results establish learning/throughput, not convergence or evidence
that larger capacity alone fixes molecular geometry. Detailed local errors, complete
all-atom arrays and every piercing's atom indices are retained.

At the observed mixed-24HB training rate, 20,000 updates would take ~18 minutes
and 100,000 ~91 minutes, approximately $0.22/$1.12 GPU compute before evaluation,
setup and downloads. Provision 30–60 minutes for an initial 20k-update experiment
with validation. A next campaign allowance of **5–20 GPU-hours (~$4–15 at this rate)**
is more appropriate than the earlier speculative 100–500 hours for this architecture.
Stricter geometric losses and larger batches must be benchmarked separately.
Prioritize state-aware extra-base labels, protocol-matched examples, periodic-image
qualification and constrained reconstruction before a broad hyperparameter campaign.
No further campaign spend was initiated after the pilot.

Verification: six immutable design hashes and installed model checksum unchanged;
exact native/trajectory atom order and bond sets checked; both remote exit codes zero;
all twelve decoded all-atom outputs finite and complete; owned pod absence confirmed.
Experiments remain under the artifact directory. No application behavior changed and
no broad application test-suite result is claimed for this analysis-only follow-up.

## Model and scope

`backend/core/exp_local.py` implements a hierarchical regression, not a deep
neural network. The global six-mode strain fit supplies a coarse prior. Two shared
ridge regressors predict local nucleotide rotations and changes in relative
nucleotide centers. Their inputs include base identity, PSF covalent connectivity,
paired-site connectivity, local geometric contacts, atom-defined relative frames,
and two rounds of graph-neighbor scalar aggregation. A weighted graph Laplacian
integrates predicted relative displacements. A graph-only ablation omits the
strain prior. Hyperparameters were fixed before examining held-out results.

All DNA atoms, including hydrogens, are reconstructed by proper rigid transforms
of their native nucleotide. They are not independently predicted free coordinates:
intra-nucleotide distances, chirality and ring geometry are preserved exactly.
The first (v1) CPU optimization penalizes inter-nucleotide O3′–P bond deviations from the
CHARMM36 0.160 nm equilibrium and nonbonded inter-nucleotide heavy-atom distances
below 0.18 nm (excluding bonded and angle neighbors). These are soft constraints;
residual failures are reported, not treated as a pass. The final v2 candidate also optimizes inter-nucleotide angles and rotations.
Torsions, stacking energies, hydrogen-bond energies, electrostatics and solvation
are not optimized. Severe-clash and ring-piercing checks are independent diagnostics.

The native structures can already contain bond and ring defects. Preserving
intra-nucleotide geometry preserves any such internal defects too. Comparison
artifacts distinguish existing from introduced defects at individual covalent
junctions. Nothing here certifies a seed as safe for NAMD.

The graph retains atom/nucleotide identities and covalent connections for future
extra-base training; there is no honeycomb, size or 0×T inference gate. Nonstandard
inter-residue chemistry needs its own geometric parameters. Neither training
trajectory contains crossover insertions, so extra-base prediction remains
unvalidated. Solvent, ions and proteins are outside this model's output.

## Data and evaluation protocol

Training uses the already extracted, identity-matched all-DNA-atom means of 128
late-window NAMD frames for 6HB 0×T and 24HB 0×T. Source design hashes are checked
against extraction provenance before fitting. Each design has equal total fitting
weight. The 6HB validation model sees only 24HB labels; the 24HB validation model
sees only 6HB labels. No neighboring atoms or trajectory frames are randomly split
across training and validation. The final candidate checkpoint fits both designs.

`workspace/platform.nadoc` was frozen as a separate 34-helix honeycomb case and
uses the model fitted on both bundles. No corresponding NAMD trajectory was
supplied, so platform results measure disagreement and geometric plausibility,
**not prediction accuracy**.

The labels are finite-window averages, not certified equilibria. Both source
simulations use the historical Na-neutralized DNA plus hydrated Mg/Cl recipe at
300 K, not NADOC's newer Mg-counterion protocol. First/last block comparisons
quantify time-window sensitivity without claiming independent confidence bounds.
The 24HB design is a sequence-verified recovered workspace snapshot; 6HB has an
immutable job snapshot.

DeepSNUPI uses the seven released checkpoints and unchanged source pinned to
`05c8a372a81a4e4974a262f902e55b513df5f26c`, in the previously verified isolated
CPU environment. Official local SNUPI creates each graph from exported topology
and exact staple sequences with static/dynamic solving disabled. We retain
upstream's training-mode batch-normalization behavior, energy-based checkpoint
selection, and default 200-step energy-only refinement/early stopping. No NAMD
coordinates enter DeepSNUPI inference or refinement.

Comparisons require an exact topological node bijection, full coverage and a
0.1 nm initial mapping residual tolerance. Paired C1′ midpoints from atomistic
models are compared to DeepSNUPI base-pair nodes after independent proper rigid
alignment (no scaling/reflection). This is an approximate common **shape** proxy,
not an all-atom DeepSNUPI accuracy measure. Unpaired nucleotides are absent from
this comparison, but present in our all-atom output and geometry audit. Training
membership of these designs in upstream checkpoints is unknown.

## Reproduction and retained evidence

Task artifacts are in `.development-artifacts/exp_local_20261007/`. The isolated
SNUPI input directories, source snapshots, model checkpoints, per-design outputs,
node mappings and atom-level audits are retained there. The original source
NADOC files and trajectories are read only. The GPU is not used.

The serialized completion pipeline validates the local model, trains it, compares
all three cases, audits atoms/bonds/rings, and renders the review artifacts. Its
`pipeline_status.json` records success/failure. Commands use
`scripts/validation_guard.sh` with single-thread CPU numerical libraries.

- `tools/train_exp_local.py --output .development-artifacts/exp_local_20261007`
- `tools/evaluate_exp_local.py --output .development-artifacts/exp_local_20261007`
- `tools/audit_exp_local.py --output .development-artifacts/exp_local_20261007`

## Results and recommendation

The experiment is complete. The local model improves the two held-out shape
comparisons, but neither geometric reconstruction passes a seed-quality gate.
**Keep it isolated; do not replace the installed Exp baseline with it yet.**
The trained candidate and optional Full-frame adapter are usable for further
experimental evaluation, without modifying the live model.

The final fit has **519 coefficients** and took **1.55 seconds** from cached labels.
Preparation, fitting, two whole-design holdouts, graph-only ablations and first
reconstruction on all three designs took **61.91 seconds**. This is a small
regression with graph-derived features, not a trained deep graph neural network.
No GPU, cloud rental or Alpine submission was needed; no new NAMD trajectory
was launched.

### Held-out shape results

RMS to the finite-window NAMD mean, in nm, after proper rigid alignment:

| Method | 6HB (trained on 24HB) | 24HB (trained on 6HB) |
|---|---:|---:|
| Native C1′ midpoint | 0.606 | 0.999 |
| Original six-mode strain model | 0.497 | 0.735 |
| Local graph-only model, before constraints | 0.561 | 0.879 |
| Global + local model, before constraints | 0.471 | 0.713 |
| Global + local, bond/steric translation constraints (v1) | 0.468 | 0.700 |
| Global + local, joint rigid bond/angle/steric constraints (v2) | **0.460** | **0.698** |
| DeepSNUPI released ensemble, raw nodes | 1.518 | 2.122 |
| DeepSNUPI + default energy refinement, raw nodes | 0.521 | 0.848 |
| DeepSNUPI + refinement, transported C1′ observable | **0.547** | **0.907** |

The last row addresses a representation bias in the original node-versus-C1
comparison: the native offset from each SNUPI origin to its paired C1′ midpoint
is transported by that node's predicted rotation relative to its initial triad.
It uses only design geometry, never NAMD labels. Identity and rigid-motion tests
verify this transport. It remains a rigid base-pair approximation, not a
DeepSNUPI atomistic prediction. Both comparison conventions are retained to
avoid hiding sensitivity to the observable.

The local model's all-atom RMS is 0.554 nm (6HB) and 0.820 nm (24HB), versus
0.591/0.860 nm for the six-mode baseline. First/last MD block means differ by
0.367/0.362 nm on the common duplex-site proxy. Two designs, finite-window means,
unknown upstream training overlap and unmatched physical models preclude a
claim of general superiority. The graph-only ablation is worse than the global
baseline: the global prior remains important.

### Platform transfer

Platform contains 13,906 nucleotides and **441,966 DNA atoms**, including
hydrogens. All **6,766** duplex nodes match by identity, with 0.0135 nm initial
mapping residual. For comparison, 6HB matches 630/630 nodes (0.0148 nm residual)
and 24HB matches 3,192/3,192 (0.0168 nm), without salvage or partial coverage.

The v2 local prediction differs from refined DeepSNUPI's transported C1′
observable by **1.466 nm RMS**. Relative to native geometry, the local prediction
moves 1.437 nm RMS and DeepSNUPI moves 0.532 nm RMS. These are **disagreements,
not accuracy scores**: no platform NAMD reference is available. The broad plate
is a meaningful extrapolation from the two compact training bundles; it is not
validated merely because it uses a honeycomb lattice.

### What the geometric constraints did—and did not solve

v1 preserves rigid nucleotide geometry, fixes most link lengths and produces no
ring piercings, but worsens backbone angles and some overlaps. After that
independent geometry failure was observed, v2 added joint nucleotide rotations
and translations with CHARMM36 equilibrium-angle penalties. The learned weights
were unchanged, and no held-out RMS was used to tune them. This is an iterative
geometry repair experiment, **not a fresh blind model-selection test**.

| v2 diagnostic | 6HB | 24HB | Platform |
|---|---:|---:|---:|
| Native → candidate median inter-residue angle error (degrees) | 7.56 → 3.45 | 7.65 → 3.39 | 7.88 → 3.45 |
| Candidate inter-residue bonds outside 0.14–0.18 nm | 0 | 1 | 0 |
| Native → candidate ring piercings | 0 → 0 | **0 → 6** | **0 → 10** |
| Native → candidate nonbonded inter-residue heavy pairs below 0.18 nm, excluding 1–2/1–3 neighbors | 149 → 487 | 855 → 2,325 | 1,924 → 4,551 |

The most severe sub-0.12 nm overlaps decrease substantially, but many contacts
settle just below the soft 0.18 nm threshold. Counts at one cutoff are not an
energy or complete steric assessment. v2 introduces ring crossings despite
improved angles. All three optimizations reach their iteration limits without
claiming convergence. The largest correction repairs a pre-existing 6.0 nm
native 24HB link; the training and native DNA PSFs nevertheless have **identical
covalent bond sets** (230,154 and 45,433 bonds for 24HB and 6HB).

Native intra-nucleotide distances and chirality are preserved to numerical
precision. However, this does not protect inter-nucleotide ring topology or
base pairing. About **59–64%** of directed local edge corrections hit the 0.2 nm
trust bound, another reason to treat this as a bounded prototype.

The next implementation step is a coupled reconstruction with an explicit
bond/ring non-crossing barrier and stronger steric handling, while maintaining
bond/angle and base-pair/stacking geometry. It should be assessed on the same
retained failure sites before any seed use or promotion. The next data priority
is an independently qualified plate-like 0×T trajectory (or a smaller plate
representative), plus independent replicas/designs. Extra-base training then
needs matched insertion motifs and flexible-backbone reconstruction; adding
more layers to this two-design regression would not close those gaps.

### Timing and review artifacts

DeepSNUPI ensemble inference took 1.16/5.75/12.57 seconds for 6HB/24HB/platform;
its default refinement took 58.07/331.81/719.98 seconds. Our v2 geometry refinement
alone took 3.93/21.49/47.57 seconds. Those stage timings exclude native structure
construction and are not a matched end-to-end benchmark. CPU is sufficient for
this prototype; additional training hardware is not the current bottleneck.

- [Interactive v2 shape and atom/bond/ring review](../.development-artifacts/exp_local_20261007/review_angles.html)
- [Original v1 review](../.development-artifacts/exp_local_20261007/review.html)
- [v2 metrics](../.development-artifacts/exp_local_20261007/comparison_angles.json)
- [v2 geometry summary](../.development-artifacts/exp_local_20261007/geometry_summary_angles.json)
- [Final candidate weights](../.development-artifacts/exp_local_20261007/model_angles.json)
- [Frozen settings before first holdout evaluation](../.development-artifacts/exp_local_20261007/preregistered_spec.json)

Per-design folders contain all predicted atom coordinates, atom identities,
Full frames, exact node maps, per-junction numeric deltas and highlighted local
review examples. `exp_local_adapter.py` supplies the existing Exp all-atom/Full
transport, but is deliberately not selected by the live predictor singleton.

The platform evaluation also exposed and fixed a SNUPI PDB reader bug: adjacent
negative coordinate fields caused 1,194 nodes to be silently omitted. A
fixed-width fallback restores all nodes without changing their coordinates or
identities (ISSUE-59). Legacy whitespace parsing is retained and tested.


### Software validation

`just test-smart` selected **FAST**: **9,976 passed, 90 skipped**. Focused
connectivity/Full-transport tests passed (10), joint-constraint derivative and
rigid-invariant/common-observable tests passed (3), and PDB-reader tests passed
(2). The numerical objective's analytic gradients were checked against coordinate
finite differences. No frontend behavior was changed in this iteration;
`main.js` LOC delta is **0**. Candidate static shape/junction artifacts were
visually inspected; this is not a claim of a live-app candidate check.

Changed Python files pass Ruff. `just lint` still reports the pre-existing unused
`pathlib.Path` in `tests/test_cpd_cube_validation_v6.py:1`; unrelated code was left
alone. The active NAMD job makes suite timing unsuitable for performance triage.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

The full optional adapter was then exercised headlessly on all three frozen
designs using the corresponding evaluation weights. End-to-end CPU times,
including native all-atom building, local inference, v2 constraints and Full
frame generation, were **5.59 s / 29.29 s / 68.57 s** for 6HB/24HB/platform.
All predicted coordinates exactly matched the evaluated arrays. Counts were
42,131 / 213,445 / 441,966 DNA atoms, including 14,965 / 75,952 / 157,290
hydrogens. Every design remained unchanged. See
[adapter benchmark](../.development-artifacts/exp_local_20261007/adapter_benchmark.json).
