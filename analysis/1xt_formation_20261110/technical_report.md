# Unwelded 2hb_1xT: all retained runs, November 10, 2026

Read-only analysis. No dynamics launched, force fields changed, or molecular structures authored.

## Coverage and methods

Analyzed all 13 matching jobs: nine production jobs and four preparation histories. Production contains 114,426 unique saved frames, representing approximately 2074.26 ns of sampled exposure across nonidentical protocols. This is not one continuous trajectory or an equilibrium ensemble. Every native saved frame was screened for all 153 thymine pairs. Production and restrained preparation remain separate.

The intended ordered endpoints are D001:15 then D000:8. Classifier identities I/II depend on endpoint order. The geometric screen assumes retained-neighbor suprafacial approach; it does not model excitation, quantum yields, reaction barriers, photoreversal, or isomer interconversion. Primary thresholds: both proposed bond distances 2.5–4.0 Å, absolute mapped torsion ≤45°, all four approach-face stereochemical signs matching, minimum normal-approach margin ≥0.25. Sensitivity grid: distance 3.6/4.0/4.5 Å × torsion 30/45/60° × margin 0.1/0.25/0.5. Catalog coverage does not establish chemical formation admissibility of every registered product.

Periodic images are reconstructed locally before contact measurements. Pairing is a distance proxy: all reference hydrogen-bond distances for a designed pair must remain within reference +0.75 Å. Local pairing covers designed pairs containing an endpoint-neighbor residue (±1); it is not a hydrogen-bond angle criterion or a melting measurement. Samples are correlated; occupancies below are descriptive time fractions, not independent observations or product probabilities.

## Production results

| Created (Denver) / ID | Retained time (ns) | Frames | Mean intended midpoint (Å) | Whole / local paired fraction | Primary intended frames | Distance-only frames ≤4 Å |
|---|---:|---:|---:|---:|---:|---:|
| 2026-07-28T18:50 e4a4 | 0.01–2.00 | 200 | 10.61 | 0.990 / 0.986 | 0 | 0 |
| 2026-07-28T19:09 29c5 | 0.01–200.00 | 20,000 | 11.41 | 0.942 / 0.928 | 0 | 0 |
| 2026-08-07T21:14 7d59 | 69.81–82.06 | 1,226 | 8.33 | 0.919 / 0.981 | 0 | 0 |
| 2026-08-13T01:10 4c0b | 0.02–800.00 | 40,000 | 5.17 | 0.845 / 0.898 | 135 | 658 |
| 2026-08-28T20:52 bd13 | 0.02–500.00 | 25,000 | 10.97 | 0.792 / 0.723 | 195 | 204 |
| 2026-08-29T00:12 07d7 | 0.02–500.00 | 25,000 | 6.59 | 0.916 / 0.833 | 1220 | 1232 |
| 2026-10-25T19:59 be74 | 0.02–20.00 | 1,000 | 10.61 | 0.945 / 0.933 | 0 | 0 |
| 2026-10-25T20:05 be5d | 0.02–20.00 | 1,000 | 8.30 | 0.938 / 0.732 | 0 | 0 |
| 2026-10-25T20:11 a926 | 0.02–20.00 | 1,000 | 11.81 | 0.974 / 0.984 | 0 | 0 |

The historical nominal 200 ns job created August 7 retains only ~69.81–82.06 ns; its missing trajectory is not counted. The early 2 ns job has a continuation: duplicate timestamps are removed. The 800 ns job descends from the August 7 history; the two 500 ns jobs share an earlier preparation parent. The October replicas share another preparation. These are not nine independent preparations.

## Stereochemical sensitivity and recurrence

Entries below show primary-frame count [minimum–maximum across the 27 threshold combinations]. Zero omitted only when every threshold gives zero.

| Run | Product | Primary [grid range] | Consecutive positive-frame groups | Groups after merging gaps ≤0.5 ns | Primary counts in chronological quarters |
|---|---|---:|---:|---:|---|
| 2026-08-13T01:10 4c0b | tt-cpd-trans-syn-ii | 0 [0–7] | 0 | 0 | [0, 0, 0, 0] |
| 2026-08-13T01:10 4c0b | tt-cpd-cis-anti-i | 135 [8–2720] | 106 | 56 | [106, 23, 3, 3] |
| 2026-08-28T20:52 bd13 | tt-cpd-cis-syn-ii | 195 [5–1000] | 164 | 13 | [0, 0, 0, 195] |
| 2026-08-29T00:12 07d7 | tt-cpd-cis-syn-ii | 1216 [29–6026] | 977 | 120 | [0, 170, 492, 554] |
| 2026-08-29T00:12 07d7 | tt-cpd-trans-syn-i | 4 [0–95] | 4 | 3 | [0, 4, 0, 0] |

Groups are saved-frame encounter episodes, not independent reaction trials; a zero observed span for a one-frame group does not imply zero physical lifetime. The long runs save at 10–20 ps intervals. No sub-frame contact kinetics or photochemical rates are inferred. See `encounters.json` for event times and pairing.

## Temporal stability

| Run | Midpoint mean by quarter (Å) | Whole pairing by quarter | Local pairing by quarter |
|---|---|---|---|
| 2026-07-28T18:50 e4a4 | 10.58, 11.91, 10.22, 9.71 | 0.994, 0.992, 0.989, 0.983 | 0.985, 0.980, 0.990, 0.990 |
| 2026-07-28T19:09 29c5 | 11.94, 11.02, 10.87, 11.79 | 0.988, 0.971, 0.939, 0.869 | 0.972, 0.981, 0.969, 0.791 |
| 2026-08-07T21:14 7d59 | 8.45, 8.07, 8.43, 8.35 | 0.921, 0.917, 0.920, 0.917 | 0.983, 0.979, 0.975, 0.985 |
| 2026-08-13T01:10 4c0b | 6.06, 4.90, 4.88, 4.82 | 0.869, 0.879, 0.816, 0.816 | 0.814, 0.807, 0.989, 0.983 |
| 2026-08-28T20:52 bd13 | 10.48, 10.85, 12.49, 10.05 | 0.890, 0.831, 0.747, 0.700 | 0.792, 0.742, 0.720, 0.638 |
| 2026-08-29T00:12 07d7 | 10.58, 5.92, 4.72, 5.14 | 0.954, 0.948, 0.896, 0.866 | 0.935, 0.890, 0.756, 0.751 |
| 2026-10-25T19:59 be74 | 10.67, 10.13, 10.84, 10.80 | 0.952, 0.943, 0.947, 0.938 | 0.941, 0.942, 0.934, 0.915 |
| 2026-10-25T20:05 be5d | 9.27, 7.44, 7.78, 8.69 | 0.943, 0.937, 0.941, 0.929 | 0.769, 0.747, 0.698, 0.714 |
| 2026-10-25T20:11 a926 | 11.36, 11.82, 12.12, 11.96 | 0.988, 0.977, 0.965, 0.967 | 0.989, 0.989, 0.972, 0.984 |

## Protocol and structural checks

| Run ID | Step (fs) | Langevin damping | Extra-base H6 mass (amu) | DNA atoms / total atoms | Ring-piercing hits (first/middle/last of each file) |
|---|---:|---:|---:|---|
| e4a49b2057a5 | 4 | 5 | 3.024 | 3043 / 21436 | [0, 0, 0, 0, 0, 0] |
| 29c5b267380f | 4 | 5 | 3.024 | 3043 / 21436 | [0, 0, 0] |
| 7d5937e569c6 | 4 | 1 | 3.024 | 3043 / 62677 | [0, 0, 0] |
| 4c0ba3a85587 | 4 | 1 | 3.024 | 3043 / 62677 | [0, 0, 0] |
| bd13e4dfa6c5 | 4 | 1 | 3.024 | 3043 / 62677 | [0, 0, 0] |
| 07d7cd2766e3 | 4 | 1 | 3.024 | 3043 / 62677 | [0, 0, 0] |
| be74a1436d66 | 2 | 1 | 1.008 | 3043 / 472630 | [0, 0, 0] |
| be5dc708adb2 | 2 | 1 | 1.008 | 3043 / 472630 | [0, 0, 0] |
| a9261569b8c7 | 2 | 1 | 1.008 | 3043 / 472630 | [0, 0, 0] |

Masses, ion inventories, actual box lengths, active parameter hashes, restraint settings, and structural spot checks are retained in `protocol_structure_checks.json`. Spot checks are not a proof of topology integrity at every frame; no full crossover-catenation audit is claimed. Parameter differences are confounded with seed, sampling length, and solvent box; the present data cannot identify their individual causal effects.

Production logs were parsed where retained. See `thermal_results.json` and per-log energy CSVs; absent logs are explicitly empty. Thermostatted energy traces are not an NVE energy-conservation test.

## Preparation histories

| Preparation created / ID | Saved frames | Intended primary count | Intended count at most permissive tested thresholds |
|---|---:|---:|---:|
| 2026-07-30T14:33 / 066b8dd60a2e | 270 | 0 | 0 |
| 2026-07-30T15:26 / 8c116f8db22b | 210 | 0 | 0 |
| 2026-07-28T16:39 / c8bcf4c1406f | 300 | 0 | 0 |
| 2026-10-25T16:04 / e00227c3d4e0 | 180 | 0 | 0 |

## Reproduce and inspect

Run from repository root, sequentially:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/extract.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/summarize.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/thermal.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/additional_shape.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/convergence.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/shapes.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/parameter_identity.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/checks.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python analysis/1xt_formation_20261110/report.py
```

Extraction resumes completed per-job outputs; remove only the relevant derived summary explicitly if deliberately recomputing changed inputs. Inputs are pinned by path, trajectory size/mtime, and design/config/parameter hashes. No full multi-GB trajectory hashes were computed. Classifier planar coverage, MDAnalysis-vs-subset reader, periodic imaging, direct descriptor recomputation, and rotation/translation checks passed in this execution (see verification.json).

Shape RMSD is fitted to each run’s first sampled frame; helix axes use topology-assigned paired core positions. Shape metrics are sampled at 0.1–0.2 ns, while contact and pairing metrics use all saved frames. Shape data for seven previously analyzed runs are reused only after source size/mtime verification, with trace hashes saved in `shape_results.json`. Shape summaries use the final 75% descriptively, without claiming equilibration.

Artifacts: `production_timeseries.png`, `production_summary.csv`, `production_results.json`, `encounters.json`, `competing_contacts.json`, `quarters.json`; each job has `series.npz` and `summary.json`. Native-time arrays include pairing, intended coordinates/descriptors, and all-pair primary masks. Configurations and the full threshold grids are preserved. Existing broad shape traces at 0.1–0.2 ns sampling are in the adjacent previous review; the two previously omitted July production runs have additional shape traces here.
