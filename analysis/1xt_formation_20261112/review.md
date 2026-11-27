# 2hb_1xT: completed 200 ns precursor follow-up

The new trajectory does **not resolve the isomer ranking**. It never reaches intended reactive contact at any of the tested thresholds. The result is a complete saved-frame negative for this trajectory, not evidence that photo-welding or a particular product is impossible.

Analyzed **2hb_1xT run created 2026-11-11 09:56:14 MST**: 10,000 production frames, 0.02–200 ns, 20 ps spacing. The NAMD log ends normally at 100,000,000 steps; the downloaded job is recorded completed and its transfer inventory verified. The preparation created November 11 at 00:02 contributes another 210 saved frames, analyzed separately; no primary intended contacts occur there. The other production created November 11 at 09:34 remains recorded running and has only one local frame, so it is not treated as a completed replica.

[Time-series plot](followup_timeseries.png) · [Full numerical results](production_results.json) · [Protocol/image checks](followup_checks.json) · [Recovered session context](session_context.json)

## Recovered purpose

Recovered the November 10 session `01a1c8cd-1df2-7be2-9e8b-6ec1fdf1d2cf`, including the initially reported conditions of **20 mM MgCl₂, 20 °C**. The user subsequently clarified that lamp heating brings the irradiated samples to **approximately 27 °C**, so **300 K (26.85 °C) is the desired, experimentally appropriate target**. The earlier proposed pilot was 200 ns, 293.15 K, 2 fs, ordinary masses and unrestrained production. In this follow-up the user clarified that **the smaller box was deliberate: assessing whether 6 nm margins are actually necessary is part of the scientific question**. The admission warning is therefore evaluated against actual trajectory clearance, not treated as an automatic rejection. The previous analysis identified cis-anti-I and cis-syn-II approach geometries in different old trajectories, but could not infer their equilibrium occupancies or product yields. This follow-up preserves that classifier and its 27-threshold sensitivity grid.

## Encounters and pairing

- **0/10,000 intended contacts**, for all eight stereochemical channels, across all 27 combinations (maximum forming-bond distances 3.6/4.0/4.5 Å, torsion tolerances 30/45/60°, face margins 0.1/0.25/0.5).
- The closest saved geometry still has a longer proposed bond of **6.68 Å** (syn connectivity; anti minimum 6.75 Å). Even distance-only screening with a 6 Å upper cutoff gives zero. Stereochemical face assignment is not the bottleneck.
- Intended C5=C6 midpoint separation: mean **12.66 Å**, minimum 6.20 Å, median 12.71 Å.
- **No competing pair passes the primary screen**, among all 153 thymine pairs. This statement uses the primary screen, not every permissive threshold.
- Mean reference-relative pairing is **91.8% overall and 92.1% across four junction-adjacent pairs**. All four local pairs are intact in 7,213 frames. These are geometric distance criteria, not a full hydrogen-bond angular/energetic classification.

| Production interval (ns) | Midpoint separation (Å) | Whole pairing | Local pairing | Intended contacts |
|---|---:|---:|---:|---:|
| 0–50 | 12.41 | 0.934 | 0.934 | 0 |
| 50–100 | 13.51 | 0.916 | 0.926 | 0 |
| 100–150 | 12.84 | 0.907 | 0.911 | 0 |
| 150–200 | 11.86 | 0.916 | 0.914 | 0 |

The new and old plans cover the same physical donor/acceptor atom pairs but use different reference distances (new minus old mean -0.359 Å). Therefore old and new native pairing percentages are not directly interchangeable. A separate 0.1 ns analysis remaps the old plan by atom identity: this run gives 94.4% whole and 97.9% local pairing under the old definition. The new 91.8% whole-pairing result uses the new, generally stricter reference.

**Endpoint-order correction:** the old narrative listed D001:15–D000:8, but its saved calculations actually used **D000:8 → D001:15**, exactly as this analysis does. I/II labels here retain the actual computational order; the previous counts have not been relabeled based on the reversed prose.

## Structure and sampling

The following are descriptive statistics for 50–200 ns, sampled every 0.1 ns. SD is temporal fluctuation, not uncertainty of the equilibrium mean; effective sample sizes assume stationarity and cannot establish it. RMSD is fitted to the first production frame. Helix axes use topology-assigned paired-core positions.

| Observable | Mean | Temporal SD | Approximate effective samples |
|---|---:|---:|---:|
| Heavy-atom RMSD (Å) | 7.66 | 1.77 | 3.5 |
| Radius of gyration (Å) | 27.27 | 0.68 | 5.2 |
| Helix centroid separation (Å) | 26.34 | 1.77 | 14.3 |
| Helix tilt (°) | 13.15 | 6.26 | 25.5 |

Maximum sampled DNA covalent-bond length is **1.723 Å**. First/middle/last ring-piercing checks are retained in `protocol_structure_checks.json`; these are spot checks, not a complete topological audit.

Mean fitted heavy-atom RMSD rises from 4.42 Å in the first 50 ns to 9.24 Å in the last 50 ns, while mean helix tilt changes from 22.93° to 11.96°. This continuing conformational evolution is a stronger caution than the nearly steady temperature or pairing average.

The native-frame late-window midpoint estimate has effective sample size **20.8**, despite 7,500 saved late frames; its two half-window means differ by -1.20 Å. Zero reactive-basin visits and only one completed fresh-protocol replica prevent assessment of basin recurrence or between-replica convergence. No binomial upper bound based on 10,000 independent trials is appropriate. The 20 ps output may miss shorter contacts; it cannot determine photochemical rates.

## Actual protocol versus intended pilot

| Setting | Actual saved input / observed result |
|---|---|
| Temperature | **300 K**, both thermostat and barostat; observed log mean 299.29 K. User clarified that irradiation warms samples to ≈27 °C; 300 K is desired. |
| Integrator | 2 fs, ordinary H masses (H6 = 1.008 amu), rigid bonds, damping 1 ps⁻¹ |
| Restraints | No DNA extra-bond restraints; packaged extra bonds maintain hydrated Mg complexes. Positional constraints off. |
| Ions | 66 hydrated Mg complexes, 39 chloride, DNA charge ≈ −93 e |
| Mean volume | 1,552,473 Å³ |
| Total ion densities | Mg ≈ 70.6 mM; chloride ≈ 41.7 mM; chloride-equivalent MgCl₂ ≈ 20.9 mM |
| Box | 3.5 nm initial padding per face; ≈89.4 × 111.5 × 155.6 Å during production; isotropic NPT |
| Clearance admission | Rotation/image-clearance check failed; `allow_undersized_cell=True` |

Total Mg includes the neutralizing counterions. The custom 20 mM MgCl₂ setting is approximately reflected in the chloride-equivalent salt density, while the DNA concentration makes total Mg much higher; neither number is a free-ion concentration. DNA atom identity, types and charges match the October control: **True**. Shared parameter-file hashes match: **True**. No CPD product potential is active in this unwelded simulation, so the result cannot diagnose the CPD product parameterization.

The failed admission check is a conservative rotation-based warning, not proof of an actual image collision. I measured nearest DNA heavy-atom distances to periodic copies at **2000 frames, every 0.1 ns**: minimum **14.28 Å at 117.72 ns**; 0 samples below the 10 Å nonbonded cutoff and 0 below the 12 Å pair-list distance. The first, closest-image and last samples independently agree with brute-force atom-pair calculations. This does not exclude between-frame contacts or periodic electrostatic finite-size effects.

The expanded audit checks **all 10,000 saved frames and all 3,043 DNA atoms, including hydrogens**. Its minimum image gap is **13.81 Å at 117.50 ns**; 0 frames fall below 10 Å and 0 below 12 Å. The closest all-atom pair was independently checked by brute-force distance calculation. See [native-frame clearance data](all_frame_image_clearance.json).

**Are 6 nm margins necessary here?** This run provides a direct test of the 3.5 nm box against short-range image contacts. No saved frame entered even the 12 Å pair-list radius. **The 3.5 nm margins were sufficient to avoid direct image contacts in the sampled conformations over this 200 ns run; 6 nm was not necessary for that observed criterion.** A conservative rotation warning alone does not overturn this measured result. That claim is limited to the saved conformations. It does not establish equilibrium finite-size independence, clearance between 20 ps frames, or clearance of unvisited future contact states.

The previous 6 nm-margin runs are not a controlled box-size comparison: they requested **12.5 mM MgCl₂**, versus **20 mM** here, and lasted only 20 ns each. They also have different initial histories. Their mean volume was ≈4.677 million Å³, with 82 Mg complexes/71 chloride (≈29.1 mM total Mg, ≈12.6 mM chloride-equivalent MgCl₂), versus 1.552 million Å³, 66 Mg/39 chloride here (≈70.6 and 20.9 mM, respectively). Thus salt, DNA/counterion concentration, length and initial state confound a box-size comparison. The smaller box uses **157,402 atoms rather than 472,630**, about one-third as many.

## Comparison with the old evidence

These are different protocols and preparations; do not pool their contact counts into a mixture estimate.

| 2hb_1xT production creation time (local) | Retained exposure (ns) | Primary intended-contact frames |
|---|---:|---|
| 2026-07-28 18:50 | 2.00 | None |
| 2026-07-28 19:09 | 200.00 | None |
| 2026-08-07 21:14 | 12.26 | None |
| 2026-08-13 01:10 | 800.00 | cis-anti-i: 135 |
| 2026-08-28 20:52 | 500.00 | cis-syn-ii: 195 |
| 2026-08-29 00:12 | 500.00 | cis-syn-ii: 1216, trans-syn-i: 4 |
| 2026-10-25 19:59 | 20.00 | None |
| 2026-10-25 20:05 | 20.00 | None |
| 2026-10-25 20:11 | 20.00 | None |
| 2026-11-11 09:56 | 200.00 | None |

The old cis-anti-I/cis-syn-II geometries remain hypotheses supported by those old trajectories. The new run neither reproduces them nor provides a competing stereochemical preference. Their earlier appearances under smaller boxes/different ionic environments cannot be interpreted as relative yields for the new conditions.

## Decision

**Sampling of the intended contact basin remains the immediate limitation; this run cannot choose the most likely isomer.** Retain this trajectory at the desired 300 K irradiation temperature. Complete the comparison with the already-running sibling when its full data become available. That assesses reproducibility at the desired irradiation temperature.

**Do not discard the intentional smaller-box run solely because of the admission warning, or assume 6 nm is required.** Use its measured clearance as the geometric evidence. To decide whether box size changes the structural ensemble, compare matched 3.5 nm and 6 nm replicas at the same temperature, salt prescription, integration settings and initial-state ensemble, with sufficient sampling and ion-atmosphere/structural diagnostics. Counterion number density necessarily changes with volume at fixed one-DNA-per-box; report this as part of the finite-size comparison rather than calling the systems chemically identical.

Keep **300 K** for both box sizes: the clarified irradiation temperature of approximately 27 °C supports this choice. Do not change to 293.15 K based on the earlier ambient-temperature description. Changing temperature and box size simultaneously would prevent attribution of a difference to either factor. No additional simulations were launched.

The earlier 200 ns checkpoint has answered a useful question: this fresh preparation does not rapidly reach a candidate reactive geometry. Further unbiased time may help, but this one zero-contact trajectory does not supply a reliable duration needed for convergence. If matched independent trajectories remain in separated basins, the next methodological step is a separately scoped, reweighted enhanced-sampling design over separation, orientation and local pairing. Do not tune CPD parameters or raise temperature to manufacture contacts. Even converged precursor geometry probabilities would still require photochemical/product evidence to become isomer yields.

## Reproduction and verification

Run the scripts in order from the repository root with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python`: `extract.py`, `summarize.py`, `additional_shape.py`, `thermal.py`, `checks.py`, `all_frame_box.py`, `followup.py`, then `report.py` and `verify.py`, all under `analysis/1xt_formation_20261112/`. Extraction caches completed results; its inventory selects completed 2hb_1xT jobs created after November 10, so future reuse should pin the retained inventory rather than silently extending this report.

Inputs are identified by exact paths, sizes/mtimes and topology/configuration/parameter hashes. The classifier's planar-reactant audit, descriptor recomputation, rigid-transform invariance, subset-reader comparison and periodic imaging checks passed. Source DCD size/mtime checks passed. No new simulation, molecular structure, parameter fit or design edit was made. Derived coordinate arrays are analysis measurements, not published structures. Old analyses and jobs are preserved.
