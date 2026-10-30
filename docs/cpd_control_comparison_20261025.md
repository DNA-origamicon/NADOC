# Three undamaged 2hb_1xT controls versus CPD isomers — 25 October 2026

> **Superseded control comparison (26 October 2026):** The three small-box controls discussed here were deleted and replaced. The [new matched-control analysis](/media/jojo/Archive/NADOC_archive/analysis/cpd_controls_20261026/report.txt) uses two completed 6 nm-padding controls, with the third still running. One new control opens the same T–A pair implicated in cis-anti-I, substantially weakening the earlier lesion-specific interpretation below. Retain this document as historical evidence, not the current primary comparison.


The three new undamaged runs are now the primary controls for the CPD comparison. They support a reproducible local pairing deficit next to cis-anti-I and a strong but heterogeneous deficit next to trans-syn-I. Cis-syn-I retains local pairing in all three repeats; trans-syn-II remains close to the control range. None of these results establishes a quantitative mechanical or equilibrium stability ranking.

The new controls resolve the previous timestep/HMR mismatch and use the same relaxation recipe and parent force-field assets. They are still only **partially matched controls**: the solvent boxes and total magnesium number densities differ substantially. An all-atom image audit also finds one control frame just inside the real-space interaction cutoff. These limitations prevent treating the observed differences as a clean quantitative causal estimate of CPD effects.

[Comparison trajectories](/media/jojo/Archive/NADOC_archive/analysis/cpd_controls_20261025/control_comparison.png) · [Individual flanking pairs](/media/jojo/Archive/NADOC_archive/analysis/cpd_controls_20261025/flanking_pairs.png) · [Replica summary CSV](/media/jojo/Archive/NADOC_archive/analysis/cpd_controls_20261025/replica_summary.csv)

## Data and verification

The controls, in creation order, are `727d2c6cac38`, `ddb5a2152283`, and `4c8598f10a23`, under `/media/jojo/Archive/nadoc_jobs/`. All share relaxed parent `af2ba962f750`. Their topology and starting-coordinate hashes agree; velocity hashes and production seeds are distinct. Each completed 10,000,000 steps at 2 fs and supplies 1,000 frames at 20 ps spacing. Native logs terminate normally. Coordinates are finite, DNA hydrogen masses are ordinary 1.008 Da, no CPD crosslinks are present, and no DNA extra-bond restraints are retained in production. Maximum raw DNA bond lengths are 1.711, 1.731 and 1.740 Å. Mean logged temperatures are 299.24, 299.23 and 299.32 K for a 300 K thermostat target. Control trajectory sizes/mtimes were unchanged by analysis.

The third cis-syn-I repeat, `770c4764d1a3`, is now complete and included. Its 1,000-frame core audit passes, with no CPD chirality failures, verified packaged assets, normal native completion, finite coordinates and no DNA restraints. Its 200 supplemental samples show no checked lesion-sugar sign inversion; the conservative DNA-heavy-atom image-clearance lower bound remains above 22.46 Å. The combined comparison has **three repeats in each of five conditions: 15 × 20 ns = 300 ns**, rather than the unbalanced sample in the 23 October report.

Eleven previously analyzed CPD trajectories use the retained 23 October results; their bulk trajectories were not reread here. The three controls and new cis-syn repeat were newly analyzed. The older, protocol-mismatched undamaged baselines are excluded from the new comparison.

## Direct structural comparison

Numbers below are equal-weight means across three replicas, with the range of replica values in parentheses. RMSD is the whole-run mean, measured against each run's own starting coordinates. Final pairing is the last 5 ns average over four flanking base pairs. Ranges are descriptive, not confidence intervals.

| Condition | Whole-DNA RMSD (Å) | Six-residue local RMSD (Å) | Final flanking pairing | Difference from control mean |
|---|---:|---:|---:|---:|
| Undamaged control | 4.89 (4.85–4.92) | 2.20 (1.59–2.78) | 89.7% (85.3–92.0%) | — |
| cis-syn-I | 6.54 (4.41–9.46) | 1.86 (1.57–2.17) | 94.9% (94.2–96.2%) | +5.2 percentage points |
| cis-anti-I | 5.22 (4.97–5.61) | 2.29 (2.02–2.69) | 76.4% (71.5–79.1%) | −13.3 percentage points |
| trans-syn-I | 5.61 (5.34–5.91) | 2.50 (1.77–2.94) | 77.3% (60.2–95.9%) | −12.4 percentage points |
| trans-syn-II | 6.11 (4.01–9.12) | 1.81 (1.75–1.88) | 91.6% (87.8–95.1%) | +1.9 percentage points |

**Cis-anti-I:** D000:THY9–D002:ADE9 has 39.8–43.0% late distance-proxy occupancy across all three CPD repeats, compared with **73.6–97.2%** in the new controls. The angular hydrogen-bond criterion independently gives **16–24% versus 64–76%**. The control comparison therefore strengthens the conclusion that this particular junction ensemble perturbs the neighboring T–A pair. The effect is local: whole-DNA RMSD remains relatively near the control values. Shared initialization, solvent differences and parameter uncertainty prevent assigning the entire deficit uniquely to real CPD chemistry.

**Trans-syn-I:** D000:GUA7–D002:CYT44 has late distance-proxy occupancies **0%, 14.7% and 96.0%**, compared with **94.4%, 96.4% and 98.0%** in the controls. The angular criterion gives **0%, 4%, 70%** versus **58%, 68%, 60%**. Two repeats therefore show disruption absent from these three controls, while the third retains a control-like state. This supports heterogeneous local behavior, not inevitable opening or a converged opening probability.

**Cis-syn-I:** the newly completed third repeat ends with 96.2% flanking pairing and has local/global RMSD means of 1.57/4.41 Å. All three retain more late flanking pairing than these controls on the distance criterion, but whole-construct displacement varies widely. It is reasonable to describe local preservation in this finite sample; it is premature to claim enhanced global rigidity or thermal stabilization. Angular occupancies are not uniformly higher than controls, so the distance-proxy advantage should not be equated with stronger hydrogen bonds.

**Trans-syn-II:** modest local RMSD and mostly retained flanking pairing remain consistent across repeats, with substantial global variability. Its final pairing range overlaps controls. There is no compelling evidence here for either wholesale destabilization or a quantitatively superior junction.

The unlinked extra-thymine sugar C1′–C1′ separation averages **8.12–9.57 Å** across control repeats, versus **3.37–3.41 Å** for cis-syn-I, **7.00–7.04 Å** for cis-anti-I, **4.10–4.39 Å** for trans-syn-I, and **4.08–4.19 Å** for trans-syn-II. These are attachment distances, not covalent bond lengths or helix separations. They describe different geometrical arrangements of the extra bases. They do not measure stiffness. Local RMSD ranges overlap controls, so the new results do not support a general statement that every CPD reduces local deformation.

## How closely the protocols match

The native production inputs agree in 2 fs timestep, no HMR, hydrogen-bond constraints, 300 K Langevin control with damping 1 ps⁻¹, isotropic Langevin piston at 1.01325 bar, PME grid spacing 1.5 Å, 8–10 Å switching/cutoff, 12 Å pair list, full electrostatics every step, no DNA positional restraints, and output frequency. Five shared parent parameter files match by SHA-256. CPD-specific CGenFF parent/overlay files are the intentional additional force-field components.

The relaxation manifests specify the same 2 fs staged recipe, damping 5 ps⁻¹, 500 ps settle and restraint ladder. Control relaxation skips 16 chunks under the acceleration policy, as do cis-syn, cis-anti and trans-syn-I; trans-syn-II skips 15. Matching the recipe does not imply identical equilibration trajectories or independent starting basins. Each condition still has its own single relaxed coordinate start.

| Solvent/system attribute | New controls | CPDs |
|---|---:|---:|
| Initial box (Å) | 60.93 × 83.44 × 128.14 | 140.93 × 163.44 × 208.14 |
| Solvation padding | 2 nm | 6 nm |
| Atoms | 63,820 | approximately 472,624 |
| Hydrated Mg residues | 52 | 82 |
| Chloride ions | 11 | 71 |
| Total Mg number density, initial box | 132.5 mM | 28.4 mM |
| Chloride number density, initial box | 28.0 mM | 24.6 mM |

Using representative mean production volumes instead gives approximately **138 mM versus 29 mM total Mg**, and 29 versus 25 mM chloride. This is a total count divided by box volume, including DNA-neutralizing counterions, **not a measured free Mg concentration or bulk ionic strength**. The similar chloride density does not make the ionic environments equivalent. Differences in counterion density and finite-size electrostatics remain plausible contributors to different structural behavior; their magnitude and direction have not been established by these runs.

The subsequent in-app box-display audit found that the old “View details” overlay
recomputed a preparation preview from the current design, rather than reading the
selected simulation package. Its displayed dimensions therefore cannot be used
to reconstruct the runs. The values above were verified against saved topology,
configuration and NAMD cell-history files. The corrected interface now labels
and displays the initial saved package box and actual ion counts separately from
new-preparation previews; this display fix does not alter the trajectories or
remove the control/isomer box mismatch.

## Periodic-image audit

The final control image audit includes **all DNA atoms in every saved frame**, expanding the image enumeration as needed from each frame's coordinate extent and orthorhombic cell. Axis extents sometimes exceed one box length, so assuming only 26 neighboring images without checking is insufficient. Bounding-box pruning preserves the minimum; each run's worst frame was separately checked against 124 neighboring images.

| Control repeat | Minimum all-atom DNA–image distance | Time | Saved frames below 10 Å |
|---|---:|---:|---:|
| 1 | 9.816 Å | 19.30 ns | 1/1,000 |
| 2 | 12.735 Å | 17.56 ns | 0/1,000 |
| 3 | 13.633 Å | 18.24 ns | 0/1,000 |

The first repeat's nearest pair is D001:CYT9 O2P and D002:ADE52 H3T across the y-periodic boundary. It is a terminal hydrogen/phosphate separation just inside the 10 Å interaction cutoff, **not a steric clash or hydrogen bond**. Four frames in that repeat fall below 12 Å. The real-space contribution near the switching endpoint can be small; this observation alone does not demonstrate that the measured CPD-control differences are image artifacts. Nevertheless, it prevents a clean claim of isolated-solute behavior throughout all control trajectories. The controls are retained without post-hoc exclusions. Long-range periodic effects remain possible even when the direct distance exceeds the cutoff.

The earlier control JSON's `nearest_image_heavy_A` field covers heavy atoms and 26 neighboring images. The expanded all-atom results in `image_audit.json` supersede that preliminary screen for the image-isolation assessment.

## Interpretation for publication

These controls are useful and substantially better matched than the previous undamaged baselines. They strengthen the evidence for a recurring cis-anti local defect and a repeat-dependent trans-syn-I defect, while weakening a blanket claim that CPDs globally stabilize or rigidify this construct. They do not establish that those defects are unphysical. The same observations could reflect genuine junction strain, current force-field bias, solvent conditions, or a mixture.

For exploratory reporting, use all five three-replica groups, name the force fields and solvent differences, show each replicate, and describe the effects as finite-duration structural observations. For quantitative causal or mechanical claims, the most targeted next control is the undamaged construct prepared in the **same box and ionic setup as the CPD systems**, with the same conservative integration/relaxation recipe. Separately, validation of the actual deployed CPD parameters remains necessary; adding controls does not replace that validation. No new simulations or parameter changes were made in this analysis.

## Analysis details and artifacts

Data and reproducible scripts are under `/media/jojo/Archive/NADOC_archive/analysis/cpd_controls_20261025/`: `analyze_controls.py`, `compare.py`, `protocol_audit.py`, `image_audit.py`, the third-repeat `supplement.py`, per-job JSON/CSV traces, `controls.json`, `comparison.json`, `replica_summary.csv`, `flanking_pairs.json`, `protocol_audit.json`, `image_audit.json` and the contact witness.

Control atoms were mapped to the same 1,963 DNA heavy-atom identities and 126 local identities as the CPDs; residue identities were verified. All 42 canonical base-pair identities and the CPD reference-distance thresholds were reused. The local region consists of D001 residues 14–16 and D000 residues 7–9, with four flanking base pairs. No condition-specific contact lists were substituted.

Distance pairing requires every reference donor/acceptor heavy-atom distance to be within its common design reference plus 0.75 Å, with minimum-image distances. The supplemental angular criterion requires all canonical interactions to have D–A ≤3.5 Å and D–H–A ≥150°, accepting either chemically attached amino hydrogen. It is sampled at the same 100 ps interval for controls and CPDs. These strict joint geometric definitions are not equilibrium populations or energetic hydrogen-bond strengths.

New aggregate windows use rounded times to avoid floating-point boundary errors. Inherited per-site CPD occupancies retain the previous script's boundary convention, which can include one extra 20 ps frame around 15 ns; the maximum possible effect is about 0.4 percentage points and does not account for the large site-specific differences. Figures show replica ranges or individual replica values, never frame-level confidence intervals. Correlated frames, common initialization, continuing drift and n=3 per group preclude precise equilibrium inference.
