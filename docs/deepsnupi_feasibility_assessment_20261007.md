# DeepSNUPI feasibility with NADOC simulation data

Assessment date: October 7, 2026.

**We have enough existing evidence to develop a useful thymine-crossover model and begin a DeepSNUPI-like surrogate. We do not yet have a curated, sufficiently diverse NAMD dataset to justify a general replacement trained only on our trajectories.** The strongest approach combines broad mechanical-model supervision with local corrections and conformational distributions learned from atomistic MD. Better treatment of extra-base junctions is the clearest opportunity; superior whole-origami accuracy and inference speed remain hypotheses to test.

This assessment covers the published method, the released implementation, simulation files under `/home/jojo/Work` and the mounted Archive drive, existing analysis products, and NADOC's current mechanics. It does not report a newly trained network, a completed convergence audit, or a measured DeepSNUPI speed comparison.

## What DeepSNUPI predicts

DeepSNUPI predicts the equilibrium shape of an already specified DNA origami design. Its supervised targets are SNUPI mechanical solutions. The paper used 312 labelled designs, split into 252 training and 60 test designs, approximately 1,000–17,000 bp each. The six classes cover blocks, curved, twisted, hinged, and 2D/3D wireframe structures. The reported ensemble achieved mean aligned RMSD 3.31 nm against SNUPI and mean inference time 0.98 s versus 431 s for SNUPI. Experimental comparisons also support selected structures, but these aggregate errors are against the simulator. Large assemblies required additional optimization, with CPU refinement reaching 66 hours. [Published paper](https://www.nature.com/articles/s41563-024-01846-8).

Consequently, three different claims need different evidence: reproducing SNUPI, matching atomistic equilibrium distributions, and predicting experimental structures. Better agreement with one does not automatically establish either of the others. A fast predictor also does not replace a folding simulation or provide physical dynamics merely by producing successive optimized coordinates.

## What the authors needed to build it

The underlying SNUPI work supplied sequence-dependent geometry and mechanics for 74 motif types: regular steps, nicked steps, crossover-adjacent steps, and single/double crossovers. Its supporting information describes ten MD systems totalling **2.34 microseconds**, with **1.50 microseconds sampled** for analysis; some data and duplex parameters came from prior work. Simulations used CHARMM36, TIP3P, 20 mM MgCl2, 300 K, and 2 fs timesteps. Motif parameters were inferred using geometric fluctuations with explicit restrictions on the configurations to which the harmonic approximation was applied. These trajectories were the foundation for the mechanical model, rather than the direct whole-design training set for DeepSNUPI. [Local SNUPI supporting information, Note S14 and Table S10](../Literature/SNUPI_SI.pdf), [original publication](https://doi.org/10.1021/acsnano.0c07717).

DeepSNUPI then needed a literature design collection, reliable graph construction, mechanical solutions, differentiable energies, an augmentation generator, model training, and structural validation. Its hybrid objective combines mechanical energy, electrostatic energy, and aligned positional/orientational error. The paper describes 504 unlabelled insertion/deletion variants. Supporting Table 11 reports 72 hours of pretraining and 8/6/5/4/8/12 hours for six specialists: **115 training hours in total**, excluding data preparation and validation. AdamW starts at 1e-4; the electrostatic weight is 0.1 and supervised weights are 500/1,000. There is a reproducibility detail to resolve: Table 11 says one variant per design whereas the main text describes two. These are reported training hours, not a hardware-normalized GPU budget. [DeepSNUPI supporting information, Notes 4–5 and Tables 2 and 11](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41563-024-01846-8/MediaObjects/41563_2024_1846_MOESM1_ESM.pdf).

The implication for NADOC is encouraging: matching their approach does not require hundreds of independent all-atom origami trajectories. It requires broad, trustworthy mechanical supervision, plus atomistic evidence for the physics we intend to improve.

## What the released code actually provides

Inspected revision: `05c8a372a81a4e4974a262f902e55b513df5f26c`.

The network separates positions and rotation vectors, embeds features in 128 dimensions, and uses five processing blocks with edge/node updates, two-head graph attention, and GRUs. A final interhelix interaction block uses a 2.5 nm radius graph. It consumes 33 edge features and predicts six coordinates per node. Absolute positions and rotation vectors enter ordinary neural layers; exact rotational equivariance should therefore be tested rather than inferred from the use of aligned loss. [Model implementation](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/model.py), [configuration](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/config.py).

The loader expects SNUPI-exported connectivity, initial coordinates, and properties, optionally final coordinates. Two downloaded examples contained node arrays of width 8, labels of width 6, and edge-property arrays of width 36. The energy implementation uses crossover-specific triads and a special single-strand edge type. Its electrostatic screening length is hardcoded at 1.2576 nm. **Generic single-strand support already exists:** our proposed advantage must be explicit, validated T/TT junction physics, including sequence, asymmetry, stacking, and conformational states. The released interface provides no separate inserted-thymine pose/distribution output. [Loader and energy implementation](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/utils.py).

The repository tree contains 252 training `.pt` files, 90 sample `.mat` files, seven checkpoints, and inference/refinement code. It does **not** contain a complete from-scratch training program, the full augmentation pipeline, or a clean, documented machine-readable reproduction of every experimental split. User input evaluates seven checkpoints; sample input follows a different selection path. Selection in code uses mechanical energy, and refinement minimizes total energy. Inference reloads checkpoints inside the prediction loop and does not explicitly call `eval()`. These details need a pinned reference baseline before changes. [Prediction implementation](https://github.com/SSDL-SNU/DeepSNUPI/blob/05c8a372a81a4e4974a262f902e55b513df5f26c/src/predict.py), [repository tree](https://github.com/SSDL-SNU/DeepSNUPI/tree/05c8a372a81a4e4974a262f902e55b513df5f26c).

The tree has no explicit license file; inspect reuse terms before planning redistribution of upstream code or weights. The scientific method and a new NADOC implementation can be assessed independently of that packaging question.

## What is present locally

The fresh file/header inventory found **1,660 DCD files, 1.853 TB decimal or 1.686 TiB**. Of these, 1,558 are physically on Archive; the NADOC workspace itself is a symlink onto Archive. The scan avoids duplicate inodes but does not claim bytewise deduplication of copied trajectories. It includes preparatory runs, tests, legacy collections, biased sampling, and incomplete files. There are 824 DCDs under development artifacts alone.

Within identifiable managed jobs, **42 jobs have files named as production, covering 16 design names and approximately 10.44 microseconds of stored intervals**. That is a candidate inventory, not a count of independent equilibrated examples. Distinct names are also not a rigorous topology count. The table below aggregates stored intervals before overlap, restart, restraint, and convergence qualification.

| Design or family | Stored production-named sampling | Interpretation |
| --- | ---: | --- |
| 2hb, T/T | 2,014 ns across 6 jobs | Includes 200 ns, 800 ns, and two 500 ns runs, plus short pieces; distinguish continuations and common starting structures |
| 2hb, TT/TT | 2,200 ns across 4 jobs | 200 ns, 1,000 ns, and two 500 ns runs; substantial local-junction evidence |
| 2hb, T/TT | 2,000 ns across 3 jobs | One 1,000 ns and two 500 ns runs |
| 2hb, TT/T | 1,000 ns | Useful reciprocal-asymmetry comparison |
| 2hb, 0/T | 1,000 ns | Whole-DNA orientation restraint is active; classify separately |
| 2hb, T/0 | 1,402 ns across 4 jobs | 1,200 ns with positional constraints off; 202 ns with two atom anchors |
| 24hb, no inserts | 284.59 ns across 4 jobs | Valuable large-bundle control, but exact design snapshot remains unresolved in these job lineages |
| 24hb, T inserts | 232.64 ns total | Main long run is 223.64 ns; 338 inserted Ts across many junction environments |
| 24hb, TT inserts | 215.50 ns | 338 inserted crossovers, 676 extra Ts; one long production job |
| 6hbx100, no inserts | 45.97 ns | Four related jobs; useful small-bundle control with limited global sampling |
| 6hbx100, T inserts | 1.51 ns | Short runs, insufficient as a mature shape ensemble |
| 6hb, TT inserts | 8.97 ns | Short runs with historical cohesion concerns requiring current review |
| Square 3x4 | 5.50 ns | Short; immutable design mapping unresolved |
| Square 3x6 with normalized skips | 28.18 ns | A useful additional square-lattice candidate; convergence unestablished |
| Square 3x6x400 | 0.11 ns | Startup-scale sample |
| 6hbx100, 90-degree variant | 2.00 ns | Short sample |

Exact paths, parent IDs, frame counts, config settings, and snapshot resolution are in the [production audit](../.development-artifacts/deepsnupi_assessment_20261007/production_audit.json) and [CSV](../.development-artifacts/deepsnupi_assessment_20261007/production_jobs.csv). The [complete file inventory](../.development-artifacts/deepsnupi_assessment_20261007/current_inventory.json) also includes unmanaged collections.

The existing 24hb T-insert analysis already extracted **509 sampled frames and 160,333 observations in its selected stable windows**, including 159 reciprocal junction pairs and 20 unpaired inserts. These are many local environments within one bundle trajectory, not 160,333 independent designs. [Cached analysis](../experiments/exp55_2hb_extra_base_orientation/data/24hb_summary.json).

Legacy `Archive/NAMD/CPD_2xT` contains additional long runs, including approximately 2.77 microseconds in `Interdigit1`; `CPD_1xT` contains a roughly 413 ns run and shorter runs. AutoNAMD includes multiple umbrella campaigns. They may be recoverable motif data after residue mapping and bias/protocol inspection. Their frames cannot be counted as unbiased equilibrium labels from names alone. Local `Work/CPD_2xT/meta` also contains biased sampling. These holdings are outside the 10.44-microsecond managed-production subtotal.

Other useful assets already exist: the official SNUPI executable and example/output files under `/home/jojo/SNUPI`, NADOC's corotational mechanics, motif parameter tables, atom-to-design mapping, Curves+-calibrated base-frame extraction, and trajectory shape comparison. The oxDNA skip/refinement campaigns have 25, 9, and 12 recorded results that could supplement mechanical training after qualification. Their atomistic follow-up, exp33, records **414 failed attempts**; those directories must not be mistaken for 414 successful NAMD labels. [exp31](../experiments/exp31_skip_twist_curvature_sweep/results/results.json), [exp32](../experiments/exp32_profile_guided_refine/results/results.json), [exp34](../experiments/exp34_finetune_validation/results/results.json), [exp33](../experiments/exp33_md_twist_validation/results/results.json).

## The most important gaps

| Gap | Evidence and consequence | Required action |
| --- | --- | --- |
| Whole-design diversity | Production-named managed data are concentrated in 2hb/6hb/24hb and a few square bundles; few mature curved, hinged, wireframe, or hierarchical targets | Use broad mechanical labels, preserve external held-out design families, then add selected atomistic/experimental tests |
| Arrangement and environment balance | Strong small-system T/TT matrix, but large bundles mainly have uniform T or TT inserts | Add matched asymmetric, mixed, and no-insert controls; include honeycomb/square and interior/boundary/seam contexts |
| Convergence and replication | Long 24hb T/TT data each represent one mature trajectory; older 2hb orientation analyses disagree between runs | Measure state populations, block convergence and autocorrelation by observable; independent starting conformations matter in addition to velocity seeds |
| Exact provenance | 11 of 42 jobs lack their own snapshot; ancestry resolves three, leaving eight unresolved | Recover immutable design/sequence and atom-index maps; validate against actual PSF/PDB connectivity before training |
| Hidden restraints | A 200 ns T/0 trajectory and its 2 ns precursor have anchors despite `k0` names; 0/T has an orientation restraint | Use configuration-aware labels; keep anchored and orientation-controlled data distinct from free-solution benchmarks |
| Periodic image interactions | Several long-run manifests explicitly flag inadequate clearance for arbitrary rotation | Measure actual image contacts with the saved cells and reconstructed molecule; a box warning is not proof that every frame is contaminated |
| Protocol mismatch | 300 versus 310 K, different damping, HMR/rigid-bond settings, older 12.5 mM Mg recipes versus published 20 mM conditions | Record conditions and forcefield hashes; run matched comparisons, and avoid interpreting thermostat-dependent kinetics as experimental rates |
| Label representation | Existing shape/RMSF comparison deliberately removes synthetic extra-base keys | Add a separate insert/junction label stream alongside base-pair centers and orientations |
| Experimental truth | Most available labels are simulations | Reserve cryo-EM/AFM/SAXS/FRET or other appropriate measured observables for independent validation, matched to solution/surface conditions |

The restraint findings are confirmed from the actual configs and anchor/colvar files, not inferred from job status. The production audit preserves those settings.

Pairing filters require special care. The exp59 analysis explicitly revised older filtering because expected ssDNA conformations and terminal fraying were being rejected. A low old filter-pass rate does not establish global instability. Preserve all validly decoded conformations and annotate local pairing, fraying and structural state; apply target-specific criteria to an intact-duplex mean or harmonic stiffness estimate. Quantify how exclusions change results. [Existing ungated analysis and sensitivity comparison](../experiments/exp59_kimmdy_extra_base_matrix/REPORT_UNGATED.md).

There are also historical seed-geometry and crossover-winding concerns in the repository. Reconcile builder/version provenance with actual seed topology and trajectories; do not assume every old run has a defect or that simulation duration removes it. The groove-seed comparison has four prepared jobs recorded but no completed result in the inspected experiment. [Geometry history](../memory/project_extra_base_spacing.md), [seed comparison](../experiments/exp52_groove_seed_sweep/runs.json).

## The best initial model

**Start with an improved junction model coupled to a whole-origami mechanical model, then train the fast graph surrogate.** This uses our strongest evidence while keeping large-scale structure constrained by mechanics.

NADOC already has an `extra_base_co` family. The current implementation assigns the same family to extra-base crossovers without differentiating T from TT mechanics. Its parameter table contains one geometry, six rigidities, and zero values for all 15 couplings. The provenance documents a fit to approximately 6 ns of 24hb TT data and modest validation on approximately 9 ns of T data; axial stiffness was an upper bound. The much longer current runs support revisiting this approximation. [Implementation](../backend/physics/fem_solver.py), [parameters](../backend/data/parameters/snupi_params.json), [provenance](../memory/project_snupi_mimic.md).

The junction model should condition on ordered insert counts and identities, flanking sequence, reciprocal versus isolated crossing, local nick state, crossover spacing/phase, lattice environment, and thermodynamic conditions. It should predict relative duplex geometry and a conformational distribution for the extra bases. A practical first version can use a small state mixture with state-specific rest geometry and positive-definite stiffness. A neural model is justified only if it improves held-out prediction over that simpler baseline.

Represent rotations with local frames or an explicitly rotation-equivariant construction. Keep ordered chemical traversal and chirality; reflection invariance is inappropriate for DNA. Preserve explicit inserted nucleotides in topology even if a coarse mechanics edge integrates out their fast motion. Predict extra-base orientations/stacking separately when the user needs molecular placement or photochemical geometry.

For a locally harmonic state, `K_eff = k_B T C^-1` is a useful estimator after alignment, consistent units, and regularization. **A covariance measured inside a constrained bundle is an effective response of that environment.** Directly assigning it as a transferable bare crossover stiffness can count surrounding constraints twice. Fit the junction contribution in the surrounding mechanical model, test transfer across bundle sizes, and separate within-site fluctuations from between-site differences in equilibrium geometry. A single Gaussian across different conformational states is especially unsafe.

Train the whole-origami surrogate on broad solver-generated labels, then use atomistic mean structures and junction distributions to learn corrections. Keep teacher fidelity identifiable. An unchanged SNUPI energy penalty can suppress the very correction we want if its junction or electrostatic physics conflicts with MD. Calibrate or condition that energy first and tune its weight using genuinely held-out data.

The resulting outputs can include mean base-pair pose, uncertainty, and junction-state probabilities. RMSF/covariance prediction is a separate target needing convergence evidence; reliable kinetics need additional validation. CPD propensity geometry is useful ancillary information but does not by itself supply equilibrium stiffness, force labels, photochemical yield, or reaction rates.

## A concrete staged program

1. **Create a qualified dataset from existing files.** Resolve lineage and design mapping, identify copied/overlapping intervals, record restraints/conditions, reconstruct periodic coordinates, and extract compact DNA features. Mark windows by observable rather than applying one global pass/fail mask. Produce per-site means, SO(3) orientation statistics, state populations, covariance with block uncertainty, and whole-core shape labels. Existing DCDs contain coordinates; force matching would require recomputing and projecting forces under the original Hamiltonian.

2. **Establish three baselines.** Run pinned upstream DeepSNUPI on supported public designs; run official SNUPI and NADOC mechanics on matched inputs; evaluate the current generic extra-base family. Keep upstream behavior and any repaired inference version distinguishable. Recover the original train/test identities before reusing the 90 sample inputs as a benchmark.

3. **Build the local extension first.** Fit T/T, TT/TT, T/TT, TT/T, and one-sided junctions from available data. Compare with the shared existing spring and a simple context-conditioned statistical model. Hold out full replicas and whole bundle environments. This is the first useful deliverable that existing data can support without new MD.

4. **Add broad shape supervision.** Use upstream data where reuse is suitable, or generate an independent set with the installed official solver and a qualified NADOC solver. Target at least the scale and architectural breadth of the original collection; several hundred to a few thousand synthetic designs is a planning range, not a demonstrated sample-complexity requirement. Include insertion/deletion variants, crossover arrangements, sizes and boundary conditions. Keep related variants in the same split. Existing oxDNA sweeps are supplementary fidelity, not independent atomistic truth.

5. **Spend new MD on gaps exposed by uncertainty.** Priorities are matched direct-crossover controls, missing large-bundle asymmetric arrangements, square-lattice insert junctions, sequence/phase diversity, and independent replicas of mature 24hb conditions. Add salt/temperature variation only if the first release will promise it. A few targeted starts can be more informative than extending an already trapped trajectory.

6. **Distil and deploy only after validation.** A single compact model, cached graph construction, resident weights and optional mechanics refinement could lower latency. Benchmark those options against the released ensemble at equal quality. Maintain a fallback for unsupported contexts and an explicit out-of-domain indicator.

## Compute and stopping criteria

The workstation has an RTX 3080 Ti with 12 GiB GPU memory and approximately 32 GiB system RAM. It is a plausible pilot-training platform if graphs and labels are streamed. Upstream recommends 8 GB GPU memory and 128 GB RAM; the larger RAM recommendation is not a measured lower bound for a redesigned loader. Store derived labels and scan trajectories in chunks on Archive. [Upstream requirements](https://github.com/SSDL-SNU/DeepSNUPI#hardware-requirements-recommended).

For scale, a prospective motif matrix of two lattice contexts × seven ordered insertion arrangements × three starts × 300 ns is **12.6 microseconds**. At roughly 300–500 ns/day observed in our archived small-system job metadata, this corresponds to **25–42 aggregate GPU-days** on comparable hardware, before preparation and failed runs. Existing qualified cells reduce the amount needed. This is an illustrative initial sampling allocation, not a claim that 300 ns converges every observable.

Large bundles are more expensive: the archived 24hb runs report approximately 31–32 ns/day. Six to twelve new 200 ns runs would therefore cost approximately **38–77 aggregate GPU-days** at those rates. Parallel GPUs reduce elapsed time, not aggregate work. These measured rates are hardware/protocol-specific and are not predictions for the desktop. The first expenditure should be extraction and convergence analysis of the long runs already paid for.

Use explicit acceptance criteria:

| Desired improvement | Evidence required |
| --- | --- |
| More accurate global shape | Lower held-out base-pair RMSD and errors in twist, bend and interhelix spacing, with structure-level uncertainty; compare with experiment as well as MD where possible |
| Better junction physics | Held-out likelihood or distribution distance, orientation/stacking occupancy, geometry and covariance errors across T/TT arrangements and bundle environments |
| Faster inference | Warm and cold end-to-end median/p95 timings on the same hardware and graph sizes, including preprocessing and optional refinement, at matched quality |
| Wider scope | Successful tests on explicitly held-out insertion arrangements, lattices, sizes or conditions; label untested combinations as unsupported |
| Reliable uncertainty | Errors increase where model uncertainty increases; independent groups attain the intended predictive coverage |

Random frame splitting is unsuitable. Split by design family and simulation lineage; keep continuations and nearby variants together. Use time blocks longer than measured correlation times. Hundreds of junctions in one 24hb trajectory provide useful local diversity but share collective motion and preparation history. Report both within-design interpolation and transfer to a new architecture.

## Audit evidence and limits

The [inventory script](../.development-artifacts/deepsnupi_assessment_20261007/inventory.py) reads directory metadata and DCD headers/record layouts without loading full trajectories. It checks stored complete-frame counts against file length. Five representative large/long DCDs were cross-checked with MDAnalysis for frame count and timestep; that check also corrected an initial frame-time offset in the audit script. Four files have incomplete trailing frame bytes, including one 2hb T/T production prelude. Complete preceding frames can be recovered; the incomplete tails are not labels.

The counts are a dated filesystem snapshot, with inode deduplication and exclusions for environment/cache directories. Header readability is not proof of frame integrity, physical convergence, or uniqueness. Full coordinate-level qualification, complete protocol ancestry, content deduplication, and experiment-level validation remain the next stage. No production simulation, model training, or modification of existing simulation inputs was performed for this assessment.
