# Decision: unwelded 2hb_1xT

**We need longer, matched-protocol sampling before predicting isomer fractions. The present data identify two credible geometric candidates—cis-anti-I and cis-syn-II—but do not establish their relative formation probabilities. These unwelded runs provide no reason to refit the CPD QM parameters: those parameters are not active in them.**

All 13 available matching jobs were analyzed: nine production jobs and four preparation histories. After removing one repeated timestamp, production contributes **114,426 native saved frames and approximately 2.074 μs of sampled exposure**. This aggregate combines different ionic environments and related starting histories; it is not a single equilibrated ensemble. The nominal August 7 “200 ns” run retains only ~12.25 ns of trajectory.

[Full methods, all-run tables, and provenance](technical_report.md) · [Native contact/pairing traces](production_timeseries.png) · [Shape traces](shape_timeseries.png) · [Production CSV](production_summary.csv) · [Shape CSV](shape_summary.csv)

## What the complete screen found

The primary geometry screen requires both proposed bond distances to be 2.5–4.0 Å, mapped torsion within 45°, consistent stereochemical approach faces, and face margin ≥0.25. Counts are correlated saved frames, **not reactions or independent trials**. All 153 thymine pairs were screened; this table concerns only the intended ordered D001:15–D000:8 pair.

| Production history | Intended compatible frames | Fraction of that run | Temporal pattern |
|---|---:|---:|---|
| July 28, 200 ns | None | 0 | No encounters under any of 27 threshold combinations |
| August 13, 800 ns | 135 cis-anti-I | 0.338% | Quarter counts 106, 23, 3, 3 |
| August 28, 500 ns | 195 cis-syn-II | 0.780% | All between 457.30 and 491.30 ns |
| August 29, 500 ns | 1,216 cis-syn-II; 4 trans-syn-I | 4.864%; 0.016% | cis-syn-II quarter counts 0, 170, 492, 554 |
| October 25, three 20 ns replicas | None | 0 in each | No encounters under any of 27 threshold combinations |

The early 2 ns run and retained August 7 fragment also have zero intended encounters across the entire threshold grid. Preparation histories are separately tabulated; none has primary intended encounters.

Both leading candidates survive every tested threshold combination. Across the grid, counts range from **8–2,720 cis-anti-I frames** in the 800 ns run, **5–1,000 cis-syn-II frames** in the first 500 ns run, and **29–6,026 cis-syn-II frames** in the second. Thus candidate identity is more robust than occupancy magnitude. Trans-syn-I is much less supported; trans-syn-II appears only under permissive thresholds in seven frames of the 800 ns run. Other intended channels have no qualifying saved frames. Zero counts do not establish photochemical impossibility.

The cis-anti-I and cis-syn-II candidates arise in different long-lived conformations. Their contact-frame totals must not be pooled into a predicted product mixture. The current classifier evaluates a retained-neighbor suprafacial approach hypothesis, not excitation or branching yields. I/II identity is tied to the stated endpoint order.

## Why more elapsed time alone is insufficient

**The existing long trajectories are not converged with one another.** In the final 75% of the two 500 ns runs, intended midpoint means are **11.13 versus 5.26 Å**, and whole-duplex paired fractions are **0.759 versus 0.903**. Classical split-R̂ is 1.74 for separation and 3.33 for pairing. For the newer 20 ns replicas, late separation means are **10.59, 7.97, and 11.97 Å**, with split-R̂ 2.31. These are diagnostics of disagreement, not precise equilibrium uncertainty estimates; shared preparation and nonstationarity limit their interpretation. See [convergence.json](convergence.json).

**Contact geometry is coupled to local pairing.** Only 14 of the 135 cis-anti-I frames have all four local reference pairs intact by the distance criterion. The first 500 ns run has no fully locally paired qualifying frames; the second has 222 cis-syn-II frames with all four local pairs intact. Thus contacts are not restricted exclusively to damaged structures, but their observed frequencies depend strongly on local pairing state. Whole pairing in the first 500 ns run falls from 0.890 to 0.700 between first and last quarters. These traces cannot yet distinguish physically relevant breathing/fraying from a protocol-dependent tendency to destabilize the motif.

Consecutive positive-frame groups number 106 for cis-anti-I, and 164/977 for cis-syn-II in the two 500 ns runs. Merging interruptions up to 0.5 ns reduces these to 56 and 13/120. Neither count is a defensible number of independent photoreaction opportunities. The relevant uncertainty includes residence in, and recurrence between, conformational basins. Native 10–20 ps output cannot resolve sub-frame encounter lifetimes.

**A competing reaction is geometrically accessible.** D000:8–D000:9, an extra/native same-strand pair, gives cis-syn-I-compatible contacts in 29 and 69 frames of the two 500 ns runs and three frames of one newer replica. There are no other primary competing pairs in these trajectories. This is another reason that an intended-weld mixture alone may not explain melting curves. See [competing_contacts.json](competing_contacts.json).

## What differs between protocols

The shared nucleic-acid and ion parameter files are byte-identical. DNA atom identity, type, and charge signatures are identical across all nine production jobs; DNA charge is −93 e. The three newer runs additionally load protein/thiol parameter files, but the listed shared DNA and ion files match. There is **no active CPD product force field** in these unwelded runs.

| Cohort | Integrator/masses | Ion inventory | Approximate mean box volume |
|---|---|---|---:|
| July 200 ns | 4 fs, hydrogen mass repartitioning; damping 5 ps⁻¹ | 1 MGH, 93 Na, 2 Cl | 206,204 Å³ |
| August long runs | 4 fs, hydrogen mass repartitioning; damping 1 ps⁻¹ | 47 MGH, 1 Cl | 614,986 Å³ (800 ns log) |
| October replicas | 2 fs, ordinary masses; damping 1 ps⁻¹ | 82 MGH, 71 Cl | 4,676,840 Å³ (first replica log) |

MGH is the packaged hydrated Mg complex. The August and October boxes differ by ~7.6-fold in volume. Their total Mg number densities are approximately **127 versus 29 mM**, respectively; these are total counts divided by box volume, **not free Mg concentrations**. Neutralizing counterions dominate the small box. Chloride number densities are approximately 2.7 versus 25.2 mM. The July run is also sodium-rich. These trajectories are not interchangeable samples of one experimental salt condition.

The actual old PSFs have H6 masses of 3.024 amu versus 1.008 amu in the newer PSFs. They do not have the separate ×8 extra-base mass modification described in older project notes. Using the actual saved files avoids assuming a historical preparation recipe was applied.

Available logs show normal termination and mean temperatures ~297–299 K for a 300 K target. The earliest 2 ns history has pronounced box-volume relaxation and should not be treated as an equilibrated production reference. Three older jobs lack retained production logs. Thirty first/middle/last production-frame spot checks show no ring piercings; sampled DNA bonds remain below 1.8 Å in the broader shape analysis. No DNA extra-bond restraints were found. These checks do not establish a complete topology audit, timestep accuracy, or equilibrium sampling.

## Recommended next campaign

1. **Resolve the experimental ionic environment first.** Compare the actual Mg/monovalent salt concentrations, buffer, and temperature used during irradiation—not merely the melting ramp—with the packaged model. Choose one adequately solvated protocol. The October setup is a better numerical starting point because it uses ordinary masses and 2 fs, but its salt composition still needs that experimental match. Do not average it with the August ensemble.
2. **If the October protocol matches the experiment, extend its three replicas to 200 ns each as an initial checkpoint, with a provisional budget to 500 ns each.** The historical first contacts occur at ~68, 151, and 457 ns, so another 20 ns per replica would be weak evidence. Those times are observations under other conditions, not rate predictions or guaranteed sampling requirements. If the intended salt/box must change, prepare a matched campaign instead of relabeling the old continuations. No simulations were launched here.
3. **Use convergence criteria tied to the question.** Compare joint distributions of intended distance, relative orientation, local pairing, and global shape across replicas and temporal blocks. Require recurring transitions into and out of each candidate contact basin, stable conditional contact occupancies, and agreement across replicas. A flat RMSD or stable mean separation alone is insufficient; the 800 ns trace demonstrates that separation can stabilize while stereochemical encounter counts change strongly.
4. **Change one protocol variable at a time if a comparison is needed.** A matched 2 fs ordinary-mass versus 4 fs HMR comparison is useful if retaining 4 fs is important for throughput. Keep salt, box, temperature, thermostat, and starting-state ensemble fixed. The current data cannot isolate timestep bias. Contact lifetimes from mass-modified trajectories should not be interpreted as physical photochemical rates. Do not change charges, torsions, or temperature simply to produce more contacts.
5. **If matched long replicas remain trapped, move to explicit enhanced sampling of separation, relative base orientation, and the relevant local pairing state.** This requires overlap and convergence checks and proper reweighting; raw biased contact counts are not isomer probabilities. Ground-state geometry sampling still needs a photochemical model or product identification before it can establish formation ratios.

For the present manuscript, the defensible result is: **unwelded 1xT simulations identify cis-syn-II and cis-anti-I approach geometries, with strong dependence on conformation and local pairing; relative yields remain unresolved.** This narrows the experimental hypotheses, but it is not yet a quantitative prediction of the isomer mixture or a validated transferable SNUPI parameter set.
