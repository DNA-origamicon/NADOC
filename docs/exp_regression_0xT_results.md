# Exp 0×T regression pilot — 2026-10-07

**A trained CPU model is installed in Exp.** This establishes an end-to-end
NADOC geometry → mapped NAMD labels → regression → saved checkpoint → preview
pipeline. It is an infrastructure pilot, not an equilibrium or atomistic-seeding
validation. No GPU, RunPod, or Alpine resources were used.

## Current all-atom revision

The installed checkpoint is now `backend/data/exp/strain_atoms_v1.json`
(`exp-0xT-atoms-v1`). `tools/train_exp_atoms.py` refits the same six global modes
against **every DNA atom**, including hydrogen and P-free termini. Native atom
identities and hydrogen coordinates come from the existing CHARMM/psfgen builder;
training requires an exact segment/residue/atom-name match to each source PSF.
No solvent, ions, or protein atoms are predicted. Local inference requires the
existing psfgen executable; no MD or GPU work is launched. Measured inference
took 6.08 s for 24HB and 1.12 s for 6HB, including native all-atom construction.

The all-atom extraction, fitting and review finished in **15.23 seconds on CPU**,
using 128 evenly sampled frames per design from the same last-half windows.
Phosphates define rigid alignment; all DNA atoms enter the loss with equal total
weight per design. These windows passed the earlier strand-based image audit;
this extraction does not independently unwrap every atom or test image contacts. The native and predicted errors below use those aligned
all-atom means; they are not instantaneous-frame or bond-geometry errors.

| Held-out design | DNA atoms (H included) | Hydrogens | Native RMS, nm | Predicted RMS, nm |
|---|---:|---:|---:|---:|
| 24HB 0×T | 213,445 | 75,952 | 1.076 | 0.860 |
| 6HB 0×T | 42,131 | 14,965 | 0.682 | 0.591 |

Each row trains on the other design only. The installed model fits both; its
0.746/0.577 nm residuals are training errors. This is still a **global shape model**,
not learned local atomistic equilibration. Applying the field to each atom can
distort bonds and rings; neither atom averaging nor coordinate availability makes
the result a validated simulation seed. Extra-base identity transport is retained,
but extra bases remain outside training coverage.

The result API carries all atom coordinates, names, elements and nucleotide keys.
The visible preview uses only the existing **Full representation**, via the same
12-float nucleotide frame and `applyFemPositions` path as NAMD Display MD.
Backbone anchors, base ring centroids and plane normals are measured from the
predicted atoms. No separate points or prediction highlighting are drawn.
Unchecking the toggle, leaving Full, changing engines or changing designs clears
the preview. Assembly previews use the frozen flattened job input as an external
Full model; clearing restores the authored assembly. Native geometry, topology
and export/seed inputs are unchanged.

Evidence: `.development-artifacts/exp_atoms_20261007/training/` contains compact
atom datasets, exact sample indices/source hashes, checkpoint and automatic review.
The following sections document the **superseded phosphate-only pilot**, whose
sampling, timing and error numbers should not be confused with this revision.

## All-atom revision verification

- `just test-smart`: **FAST**, 9,962 passed, 90 skipped.
- `just test-frontend`: 614 files passed; 7,472 passed, 1 skipped.
- Running app: **3 passed** (real CPU inference/Full display and representation
  gating, fixture Stop/progress, real assembly inference/restore). Tests verify
  actual rendered instance movement, unchanged colors, restoration, and changed
  visible DNA pixels with a hidden-model negative control. These fixtures test
  software behavior, not predictive accuracy outside the two training designs.
- Initial coordinate-only checks passed but their screenshot did not visibly
  frame the model. Closing obstructing panels and framing the camera from native
  coordinates exposed it; no production geometry or rendering settings changed.
  The reviewed [Full preview](../.development-artifacts/exp_atoms_20261007/exp-full-preview.png)
  is retained. Repeat via `frontend/e2e/exp_panel.spec.js` with the isolated smoke
  configuration and validation guard.
- Direct 24HB/6HB all-atom inference passed with 6,720/1,328 Full frames, finite
  positions, all hydrogens present, and unchanged input designs.
- `just smoke` was refused by the active-NAMD guard; no override was used.
- All changed Python modules pass Ruff; `git diff --check` is clean. Global
  `just lint` still reports the pre-existing unused `pathlib.Path` import in
  `tests/test_cpd_cube_validation_v6.py:1` (also present in HEAD).
- `main.js` LOC delta: **0** (+4/−4 for the complete Exp feature).
- Browser teardown removed all three `__e2e__exp-*` documents. Post-run inventory
  found no new project directories, session caches, isolated bridge credentials,
  or disposable Playwright output. Scientific datasets/native structures, logs,
  and one reviewed screenshot remain in the task artifact folder (~109 MiB).
  Installed checkpoint SHA-256 matches the trainer output:
  `ce15788d80699d7d411ce3ba40af6ad8989b9b96a54d6d4aee0dbeb44b0f575e`.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

## Historical phosphate-only pilot

Extraction, fitting and automatic review initially finished in **17.8 seconds**;
the final run after correcting ridge normalization took **2.22 seconds** with warm
filesystem cache. A regression test caught that duplicated sampling rows could
otherwise change the regularization strength; normalization now preserves equal
weight per design. The training run was far below ten minutes, so no delayed
assistant review trigger was necessary. The trainer itself writes a completion
`review.json` automatically on success or failure; results were reviewed in this
session. This is not a scheduled future assistant callback.

## Data and mapping

| | 24HB 0×T | 6HB 0×T |
|---|---|---|
| Job | `594917c0d119` | `892ad3d12d4f` |
| Selected DCD window, ns | 60.34–120.64 | 10.02–19.97 |
| Frames sampled evenly | 256 | 256 |
| Sequence-verified residues | 6,720 | 1,328 |
| Phosphates with coordinate targets | 6,644 | 1,307 |
| First/last block-mean difference, nm | 0.489 | 0.457 |
| Mean block deviation from overall mean, nm | 0.253 | 0.218 |

Each design receives equal total regression weight. The many nucleotides and
frames are not independent designs. One selected production lineage per size
is used; overlapping continuations and different output strides are not treated
as additional independent examples.

The 6HB design comes from its immutable job snapshot. The 24HB file was recovered
at `/media/jojo/Archive/NADOC_archive/runtime/workspace/24hb_0xT.nadoc`; it is a
workspace candidate, not proof of the original snapshot's identity. Existing
NADOC strand traversal and package segment maps give complete, unique residue
correspondence, with **zero sequence mismatches** for both designs. Copies of
the validated designs and source hashes are retained with the dataset.

Initial package versus current native geometry differs by 0.348/0.299 nm RMS after
rigid alignment. The pilot explicitly trains against the **current NADOC geometry**,
so it includes this difference rather than assuming today's builder reproduces
the old package exactly. P-free termini are excluded from the target loss; their
preview positions receive the fitted global field without direct supervision.

Frame extraction reads only the DNA prefix, avoiding solvent-sized arrays. PSF
atom counts are checked against DCD headers. Explicit strand identities are used
for minimum-image checks; neither chosen window required a nontrivial image
correction. This does **not** rule out interactions with periodic images.
Frames are rigidly aligned to the current native geometry before averaging.
All reported times are DCD-header times, not a reconstructed full lineage clock.

Both training systems use historical **Na-neutralized DNA plus hydrated Mg and
Cl**, not the newer Mg-counterion recipe. Direct PSF counts are 6644 Na / 103 Mg /
206 Cl for 24HB, and 1307 Na / 24 Mg / 48 Cl for 6HB. This was checked because the
24HB manifest's generated `protocol_fidelity` text incorrectly claims no Na.
The actual counts are included in the training manifest and installed model card.
Both run at 300 K with 4 fs HMR and DNA constraints off; Langevin damping differs
(1/ps for 24HB, 5/ps for 6HB). This matters for finite-time sampling. Current
Mg-counterion-protocol accuracy has not been established by this pilot.

## Model and evaluation

The model has six shared scalar coefficients: radial expansion, axial strain,
and twist, each with an end-dependent counterpart. These vector modes use the
principal axis of the input cloud, preserve its centroid, and transform with
rigid rotations/translations. Ridge strength is fixed at 0.01; it is not selected
using the held-out design. This model cannot express independent helix bending,
local chickenwire geometry, crossover states, or chemical sequence effects.

**Leave one complete bundle size out:**

| Held-out design | Native geometry RMS, nm | Regression RMS, nm | Reduction |
|---|---:|---:|---:|
| 24HB, trained only on 6HB | 1.088 | 0.865 | 20.5% |
| 6HB, trained only on 24HB | 0.702 | 0.604 | 13.9% |

Errors are per-phosphate RMS distances to the aligned sampled mean; they are not
errors against independently certified equilibrium structures. Two successful
folds establish a useful infrastructure check, not a broad accuracy estimate.

The installed model is refit on **both** designs. Its training errors are 0.762 nm
(24HB) and 0.591 nm (6HB); do not quote those as held-out accuracy. The block
differences above remain material uncertainty in the target definition.

## Extra-base expansion and limits

The current training cohort contains only zero extra bases. Frozen native topology,
nucleotide identity keys, per-nucleotide mean targets, sampled frames, four block
means, and an explicit zero-extra-base field are retained. A future version can
derive local crossover sequence/count features and change the versioned vector
basis without rebuilding the data plumbing. Simply setting an extra-base count
on this checkpoint cannot produce a learned extra-base effect: none was trained.

Exp accepts other designs without a software lattice/size gate. Extra-base designs
receive an explicit outside-training-coverage label. All results are opt-in
session previews. Dense, nearly isotropic, bent or otherwise unfamiliar structures
are outside the assessed shape family; principal-axis modes may be inappropriate.
No atomistic seed, fluctuation distribution, salt-response model, or new NAMD job
is produced. The next meaningful improvement is local geometry features plus
more independent bundle examples and protocol/image-contact checks.

## Reproduction and artifacts

Trainer: [tools/train_exp_regression.py](../tools/train_exp_regression.py).
Model/encoder: [backend/core/exp_regression.py](../backend/core/exp_regression.py).
Installed checkpoint: [strain_v1.json](../backend/data/exp/strain_v1.json).

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=. nice -n 10 \
  .venv/bin/python tools/train_exp_regression.py \
  --manifest .development-artifacts/exp_regression_20261007/manifest.json \
  --output .development-artifacts/exp_regression_20261007/run --samples 256
```

The retained artifact directory holds the manifest, two frozen designs, two
compressed datasets, two provenance records, checkpoint, automated review and
validation logs. Training does not automatically overwrite the installed model.
Source trajectories and user NADOC files were read-only throughout.

Measured inference, including native geometry generation on one CPU thread:
**0.206 s for 6HB and 0.401 s for 24HB**. Both adapter outputs match the saved
dataset/checkpoint prediction exactly (maximum difference 0 nm). These are two
local timing observations, not a general runtime guarantee.

Retained artifacts occupy approximately 24 MB (21 files). Browser teardown and a
post-run inventory confirmed no remaining test designs, matching project stores,
session caches, or isolated browser credentials. Dataset checksums were verified.

## Verification

- Backend `just test-smart`: **FAST**, 9958 passed, 90 skipped, including six new
  regression tests for rigid-motion equivariance, centroid preservation, known
  strain recovery, design weighting, adapter isolation, and model validation.
- Frontend: 7468 passed, 1 skipped.
- Running app: two browser tests passed, including real installed-model inference
  and visible preview creation, plus stop/progress/teardown contract checks.
- `just smoke` refused to run because NAMD is active; the guard was not overridden.
- Ruff and `git diff --check` passed. `main.js` received no further changes in the
  training task (its complete Exp feature delta remains zero net lines).

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

## Direct DeepSNUPI comparison: 6HB 0×T

**DeepSNUPI runs on this workstation.** On 2026-10-07 the released seven-checkpoint
ensemble was installed in an isolated Python 3.10 CPU environment and run on the
same frozen 6HB design used above. NADOC's environment and active Exp checkpoint
were not replaced. No GPU, NAMD trajectory, cloud rental or new MD was used.

The six-parameter Exp model is a calibration baseline, not a deep neural network.
Its loss contains all DNA atoms, but its output is a shared analytic radial/axial/
twist displacement field applied to native atoms. It has no learned local sequence,
crossover, bond, or neighborhood response. A cached fit on 24HB alone took 0.090 s;
the previously reported 15.23 s included atom construction, trajectory extraction,
averaging, fitting and output. More training iterations cannot add missing modes.
The instantiated upstream DeepSNUPI network has **7,743,052 parameters per model**.

### Matched input and reference

The existing caDNAno exporter and validated SNUPI schema shim generated the graph
input from the frozen 6HB NADOC design. A caDNAno-compatible staple sequence CSV
contained zero unknown bases. Official SNUPI v3.10 recognized that CSV and exported
`GEN_INIT_DGNN=1`; static, dynamics, NMA and GPU options were disabled. Graph size:
630 duplex nodes and 1,380 directed edges. Every duplex node matched by topology;
SNUPI initial coordinates matched the NADOC mechanics reference at 0.0148 nm RMS.
The saved node-order map is bijective, with no unmatched or salvaged nodes.

NAMD reference: 128 aligned frames from job `892ad3d12d4f`, ~10.02–19.97 ns.
As in the existing SNUPI/MD comparator, the MD and Exp shape proxy is the midpoint
of each paired C1′. DeepSNUPI contributes its base-pair node positions. Each method
gets a separate proper rigid-body alignment to the same reference, with no scaling.
This is an approximate common coarse shape representation, **not an all-atom RMSD**
or a Curves+ base-pair-origin comparison. It is not comparable to the paper's
aggregate SNUPI-target error or the all-atom pilot table above.

| Method | RMS to NAMD mean, nm | Interpretation |
|---|---:|---|
| Native NADOC | 0.606 | Paired C1′ midpoints |
| SNUPI initial geometry | 0.668 | Unrelaxed graph node positions |
| DeepSNUPI released ensemble | 1.518 | Seven checkpoints; upstream mechanical-energy selection chose `pre_train` |
| DeepSNUPI + default energy refinement | 0.521 | Upstream 200-step request; no NAMD target enters optimization |
| Exp trained on 24HB only | 0.497 | 6HB excluded from fitting |
| Exp installed model | 0.484 | Includes 6HB training; not a held-out result |

The seven-checkpoint forward inference took **1.24 s** on one CPU thread; default
refinement took **57.34 s**. These exclude fresh Python imports and SNUPI graph
preparation. This proves small-design local CPU feasibility, not a whole-dataset
training memory budget. The environment ran under the standard 8 GiB guard.

The refined DeepSNUPI and held-out Exp errors differ by only **0.024 nm**. That is
insufficient to establish a winner given this single design, the differing node
representations, conditions, and finite-window sampling. The NAMD first/last block
means differ by 0.367 nm on the same 630-node proxy. This is a sampling-sensitivity
measure, not a confidence interval. DeepSNUPI targets SNUPI mechanics; Exp targets
historical Na-neutralized NAMD data. Membership of this exact design in upstream
training has not been established. Broad superiority is **not** demonstrated.

### Numerical fidelity and inspection

Pinned upstream revision: `05c8a372a81a4e4974a262f902e55b513df5f26c`. Numerical
source was left unchanged. Python 3.10.20 was used with PyTorch 2.0.0+cpu,
PyG 2.3.1, and RoMa 1.3.2; upstream documents Python 3.9. Tensor-only checkpoint
loading was enforced. The released predictor omits `model.eval()`; that behavior
was preserved. A separate explicit-eval diagnostic performed substantially worse
on this graph and was not silently substituted. The `small` specialist alone
scored 0.896 nm, but selecting it using the known NAMD target would change the
benchmark's model-selection rule, so it is not reported as the ensemble result.

[Static comparison](../.development-artifacts/deepsnupi_compare_20261007/6hb_comparison.png)
· [Interactive 3D comparison](../.development-artifacts/deepsnupi_compare_20261007/6hb_comparison.html)
· [Numeric report and provenance](../.development-artifacts/deepsnupi_compare_20261007/comparison.json).
The grey curves are the selected NAMD mean; colored curves are predictions aligned
to it. The static figure was inspected; all panels show the expected matched
bundle geometry. Atomistic stereochemistry is deliberately not assessed by this plot.

Reusable inputs, scripts, installed environment, dependency lock, weights/hashes,
logs and coordinates are retained only under
`.development-artifacts/deepsnupi_compare_20261007/`. `run_inference.py`,
`run_refinement.py`, and `compare.py` reproduce their respective stages. Run CPU
work serially under `scripts/validation_guard.sh` with one BLAS/OpenMP thread and
`CUDA_VISIBLE_DEVICES=''`. The first two use that folder's Python; `compare.py`
uses NADOC's `.venv` with `PYTHONPATH=.`. The app was not changed in this comparison.

Sources: [upstream README](https://github.com/SSDL-SNU/DeepSNUPI),
[prediction and refinement](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/predict.py),
[network architecture](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/model.py).
