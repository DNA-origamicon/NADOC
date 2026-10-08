Latest protocol audit: [Mg recipe, Fast verification and running 24HB control](exp_local_predictor_results.md#mg-recipe-and-running-24hb-control-audit-2026-10-07). Mg arithmetic is corrected; the independent 8 fs PME-cadence discrepancy remains open (ISSUE-62).

Latest follow-up: additional extra-base/square data and a completed, user-authorized $3 GPU pilot are documented in [expanded-data results](exp_local_predictor_results.md#expanded-data-and-gpu-pilot-2026-10-07-later-follow-up). The historical no-rental proposal below is superseded by that completed experiment; no further rental is active.

Latest candidate evaluation: [connectivity-aware model, 6HB/24HB/platform](exp_local_predictor_results.md).
The candidate improves the two held-out shape scores but fails ring/steric
qualification; the installed Exp baseline remains unchanged.

# Exp: NADOC-native screening predictor

Status, 2026-10-07: **all-DNA-atom CPU regression trained and installed in Exp**. The user
authorized an initial infrastructure experiment using 6HB and 24HB 0×T jobs.
The installed six-mode strain model predicts a finite late-production mean, not
a qualified equilibrium structure. See [pilot results](exp_regression_0xT_results.md).

The first target is an intact origami's mean shape at one reference NAMD protocol,
initially explored on basic honeycomb bundles. Exp imposes **no lattice, size, or
extra-base gate**. Its results are session-only, opt-in physical previews, separate
from the topology, builder geometry, exports, and NAMD seeds. The preview updates the existing Full model using NAMD Display MD transport.
It is disabled in other representations; leaving Full restores native positions.
Changing the design invalidates the result; switching engines removes the preview. Run/Stop,
real reported progress, failure reporting, document isolation, and late-result
cancellation are implemented. No MD engine or GPU is launched by Exp.

## Direct upstream check

DeepSNUPI is now installed and verified for 6HB CPU inference/refinement in an
isolated analysis environment. On 630 mapped duplex sites, RMS to the finite NAMD
mean is 0.606 nm native, 0.497 nm Exp trained on 24HB only, 1.518 nm upstream
DeepSNUPI ensemble, and 0.521 nm after its default energy refinement. Forward
inference took 1.24 s and refinement57.34s on one CPU thread. These are coarse
shape proxies, not all-atom errors or a broad accuracy ranking. The current Exp
model learns six shared coefficients; it does not yet learn local atomistic
relaxation. See the [matched comparison and figures](exp_regression_0xT_results.md#direct-deepsnupi-comparison-6hb-0t).

## Initial training decision (historical; superseded by the completed GPU pilot above)

The initial decision was not to rent a GPU yet. The first six-parameter ridge regression runs on CPU.
Both leave-one-size-out evaluations improve over current native geometry, but
only two sizes and two selected production windows were tested. A later local
rest-geometry model plus sparse reconstruction remains a proposed expansion.
The available trajectories are valuable; the audit below does **not** establish
that they are unusable or unequilibrated.

For the authorized infrastructure pilot, labels are explicitly **late-production
window means**, with finite-window uncertainty. No fit is represented as an
equilibrium predictor. A recovered 24HB 0×T NADOC file passed the full residue
sequence and mapping checks against its package; the earlier missing-snapshot
finding below records the initial inventory, not the current pilot status.

### New CPU evidence

`tools/exp_shape_audit.py` sampled 64 frames from the second half of one production
file per job, selected all PSF C1′ atoms (including extra bases), removed rigid
motion using two alignment passes, and divided those samples into four blocks.
The table gives the RMS distance between first and last block means after a
further rigid alignment. It is **not prediction error** or a convergence p-value.

| Design / job | Sampled DCD time, ns | Block mean difference, nm | Interpretation |
|---|---:|---:|---|
| 24HB 1×T / `6950d3b79138` | 111.84–223.64 | 0.577 | Best large-bundle candidate with saved design; shape uncertainty remains |
| 24HB 2×T / `fc12195d0636` | 107.76–215.50 | 0.571 | Matched size, different crossover extra bases; one long lineage |
| 24HB 0×T / `594917c0d119` | 60.34–120.64 | 0.473 | Recover the exact design-to-atom map before supervised use |
| 6HB noT / `892ad3d12d4f` | 10.02–19.97 | 0.436 | Size holdout candidate, but short sampling and shape changes |
| 6HB noT / `07c05aaecc12` | 5.04–10.00 | 1.083 | Superseded segment; not an independent additional design |
| 2HB T/T / `4c0ba3a85587` | 400.02–800.00 | 0.633 | Local motif data; substantial conformational variation |
| 2HB T/T / `bd13e4dfa6c5` | 250.02–500.00 | 0.546 | Related prepared ancestor; split by lineage |
| 2HB T/T / `07d7cd2766e3` | 250.02–500.00 | 0.438 | Related prepared ancestor; split by lineage |
| 2HB TT/TT / `029a76c6a59f` | 500.02–1000.00 | 0.280 | Priority candidate for local motif qualification |
| 2HB T/TT / `9cd897159f47` | 500.01–1000.00 | 0.623 | Multiple conformations should not be collapsed blindly |
| 2HB TT/T / `e6d49ff6d011` | 500.01–1000.00 | 0.654 | Same caution; asymmetry matters |

For both 24HB T variants, the within-block RMS fluctuations are approximately
0.31–0.34 nm, while the radius of gyration changes by only a few hundredths of a
nanometre. A stable radius of gyration therefore does not establish a stable mean
shape. Conversely, different finite-block means can reflect equilibrium slow
modes, not just unfinished relaxation. This sparse triage cannot distinguish them.

Limitations: no periodic-boundary unwrapping or image-contact check; no effective
sample-size estimate; no core-only versus flexible-tail sensitivity analysis;
no independent-replica mean comparison. Times are those recorded in DCD headers,
not a reconstructed continuation timeline. One longest file is selected rather
than concatenating possibly overlapping output. The superseded 6HB file uses its
job's retained PSF after verifying atom count; exact atom-order provenance still
needs checking. An initial missing-PSF error for that job was resolved in the
second audit, not counted as a second result.

Raw evidence: `.development-artifacts/exp_predictor_20261007/shape_triage*.json`.
Eleven distinct jobs were read, taking roughly one minute of summed sampling
wall time with one BLAS thread. No production trajectory was modified. The broader
[DeepSNUPI assessment](deepsnupi_feasibility_assessment_20261007.md) has the inventory,
lineage, and initial protocol audit.

### Conditions and label qualification

Use a single **versioned NADOC production recipe**, based on the
[local Aksimentiev protocol reference](../memory/REFERENCE_AKSIMENTIEV_PROTOCOL.md):
300 K, CHARMM36/CUFIX, explicit water and hydrated magnesium, unrestrained DNA in
the production stage. The tutorial's short k=0 stage does not itself certify an
equilibrium ensemble. Do not silently pool older Na-neutralized screening runs
with newer Mg-neutralized runs, or anchored/field runs with free DNA.

The inspected 24HB 1×T package records Mg counterions, zero Na, hydrated Mg,
4 fs HMR, 300 K, Langevin damping 1/ps, and DNA constraints off. Its ionization
metadata contains both `n_mg_bulk=84` and total/neutralizing Mg counts of 3491 with
zero chloride; actual PSF ion counts and the parent preparation need to settle
the recipe rather than assuming a nominal bath concentration. The 6HB candidate
uses damping 5/ps. Treat dynamics differences separately from equilibrium
structure, particularly if the training target is finite-time relaxation.

Next CPU work is to reconstruct immutable NADOC/PSF mappings, audit restraints,
unwrap whole molecules, measure actual image contacts, and extract block means
of helix centerlines, twist, bend, interhelix spacing, and crossover geometry.
Compare increasing block lengths and independent replicas. Preserve flexible
extra-base states rather than rejecting all unpaired nucleotides. Choose windows
from these observables, not production filenames or duration alone.

## First model and validation

The installed baseline fits radial expansion, axial strain, and twist, each with
an end-dependent mode, in the bundle's principal-axis frame. It cannot represent
local crossover mechanics or independent helix deformations. Next, test a small
regularized model of local corrections using strand/crossover connectivity,
helix neighborhood, terminal distance, nicks, and explicit extra-base features,
with connectivity-constrained reconstruction. Extra-T
coverage in the data is an advantage, but few large independent bundles limit
the claim about transferring that effect across sizes and arrangements.

The current deliverable includes all DNA atom coordinates (including H), with
Full-view positions and base frames measured from them. Six global modes still
cannot predict local atomistic relaxation. An atomistic seed requires
stereochemical/contact checks,
and a measured reduction in NAMD relaxation cost. An average of atom coordinates
is not automatically a valid seed. Fluctuation amplitudes, conformational-state
populations, solvent, kinetics, and arbitrary environmental conditions are outside
the initial target.

Split by **design and preparation lineage**, holding out a whole bundle/size;
do not random-split adjacent trajectory frames or different output strides.
Compare held-out aligned shape, centerline bend/twist, interhelix spacing, and
local crossover geometry against the initial NADOC geometry and existing fast
baselines. Report runtime separately from training and trajectory extraction.
Measure errors against block uncertainty. With only a couple of large related
designs, report the actual narrow held-out result rather than general accuracy.

## Hardware proposal

Local machine observed: Ryzen 9 9950X, 16 cores/32 threads; 30 GiB visible RAM
(about 17 GiB available at inspection); RTX 3080 Ti 12 GB already occupied.

| Work | Initial resource allocation | Decision |
|---|---|---|
| Sparse trajectory qualification and mapped feature extraction | 1–2 CPU workers, streamed frames, aim below 8 GiB | Run locally; sparse triage completed |
| Ridge/local regression and sparse reconstruction | 2–4 CPU threads, 4–8 GiB target | Local CPU first after labels are defined; no GPU required |
| Small graph network, if it outperforms the CPU baseline | One 24 GB NVIDIA GPU, roughly 8 vCPUs and 32 GB RAM | Profile only after data and baseline exist |

The initial extraction/fit/review completed in 18 seconds on one CPU thread;
a repeated run with warm filesystem cache took 2.2 seconds. Future neural-model
allocations above remain estimates. Dense all-pairs
attention on whole origami would invalidate this memory estimate; use sparse
connectivity and bounded neighborhoods.

If a neural model is warranted, propose **one RTX 4090 RunPod**, a four-hour pilot,
and a price ceiling of $1/GPU-hour (at most $4 compute, storage/transfer separate).
The [official 4090 page](https://www.runpod.io/gpu-models/rtx-4090) currently headlines
$0.74/hour but also retains $0.34/hour prose; obtain the live pod quote before
renting. Transfer compact features/labels, not the approximately 1.85 TB raw DCD
inventory. No pod has been rented.

Alternatively propose Alpine: partition `aa100`, one GPU (`--gres=gpu:1`), one
task, 8 CPUs, 32 GB RAM, normal QoS, four-hour walltime. Confirm allocation/account
and current scheduler availability before submission. The
[official Alpine hardware guide](https://research-computing-user-tutorials.readthedocs.io/en/stable/clusters/alpine/alpine-hardware.html)
documents that partition and GPU request. This is an allocation proposal, not a
ready neural training job: there is no neural trainer/checkpoint yet. No Alpine job
has been submitted.

## Implementation and remaining work

- `backend/core/exp_predictor.py`: CPU-only, single-task lifecycle and adapter
  contract; the trained adapter is loaded from `backend/data/exp/strain_atoms_v1.json`.
  Invalid outputs fail explicitly.
- `backend/api/routes_exp.py`: model status, start, poll, stop; document-scoped.
- `frontend/src/ui/exp_panel.js`: controls and Full-only native model preview, opt-in and
  invalidated on design changes. No point cloud or atomistic-mode display override. Assembly launches use the shared compact
  simulation projection rather than disabling assembly mode. A frozen job-input
  Full model is rendered during assembly preview, then cleared on toggle-off.
- `backend/core/exp_atomistic.py` constructs all DNA atoms using CHARMM/psfgen,
  predicts every coordinate, and derives the NAMD Full display frame.
  `tools/train_exp_atoms.py` trains the installed all-atom checkpoint in 15.23 s
  on CPU; see the current section in the pilot report for held-out errors.
- `backend/core/exp_regression.py` supplies a versioned vector-basis encoder and
  adapter; `tools/train_exp_regression.py` extracts mapped targets, fits, evaluates,
  and automatically writes `review.json` on completion (including failures).
  No training button or automatic checkpoint promotion is provided.
- Current results are in-memory only. Persistent jobs, atomistic NAMD seeding,
  and reload recovery are not implemented.

`main.js` is unchanged in total line count: four lines added and four removed,
consisting of the factory import/init and panel wiring.

## Initial controls verification (before the trained adapter)

- Focused backend lifecycle: 6 passed.
- `just test-smart`: **FAST**, 9,952 passed, 90 skipped. The selector reported:

  ```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  ```

- `just test-frontend`: 614 files passed; 7,468 tests passed, 1 skipped.
- Isolated running-app checks: 2 passed, real missing-model handling plus an
  explicitly mocked model contract for progress, stop, preview and teardown.
  This verifies the feature in the app, not scientific predictions.
- `just smoke`: refused by the active-NAMD simulation guard. No override used.
  The focused app checks do not clear that broad gate.
- Ruff passed for the new Python files; `git diff --check` clean.
- Playwright teardown removed both `__e2e__exp-*` parts. A subsequent inventory
  found no test parts, matching project snapshots, session caches, or isolated
  browser bridge credentials. The configured reporter deleted screenshots and
  disposable browser reports. Scientific audit JSON and validation logs remain
  under `.development-artifacts/exp_predictor_20261007/`, outside user designs.
