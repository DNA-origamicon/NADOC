# exp55 report — two-extra-base orientation phase space

## Archive audit and selection

The archive contains 10 NAMD packages named for `2hb_1xT`. Seven carry a design snapshot
that is structurally identical to the current `workspace/2hb_1xT.nadoc` after model
normalization (the current file has newer default UI and identity metadata). Two early
packages have no stored `design.json`; one failed older package is structurally different.

The plotted ensemble uses only the structurally matched, unrestrained production data:

- replica A: 200 ns (`29c5b267380f`);
- replica B: stored 69.81–82.06 ns prelude (`7d5937e569c6`) and its 800 ns continuation
  (`4c0ba3a85587`).

The 2 ns bring-up trajectory and all ENM/MGHH/protocol-test stages are inventoried but not
used. The common sampling interval is 200 ps. The archive itself was not modified.

## Processed data

The CSV contains 10,124 insert observations (5,062 sampled frames × two inserts). After
linker, local-pairing, global-pairing, template-fit, and contiguous-window filtering,
4,250 observations remain in the plotted stable ensemble:

| lineage | insert bp13 | insert bp14 |
|---|---:|---:|
| replica A | 916 | 887 |
| replica B | 749 | 1,698 |

Replica B contributes fewer stable points than its duration suggests because the minimal
two-helix construct loses global/local pairing during substantial parts of the long run.
The figures therefore show phase-space support, not equilibrium population estimates.

## Orientation result

Circular mean directions of the directed slab-face normal, reported as
`(azimuth, polar)` in degrees:

| lineage | insert bp13 | R | insert bp14 | R |
|---|---:|---:|---:|---:|
| replica A | (−64.8, 141.4) | 0.962 | (+7.4, 100.2) | 0.896 |
| replica B | (−118.9, 108.4) | 0.812 | (+56.0, 61.3) | 0.830 |

`R` is the mean-vector resultant length (1 = tightly concentrated, 0 = isotropic). The
two reciprocal inserts occupy distinct basins within each lineage, but the basin centers
also shift strongly between lineages. Pooling them as a single equilibrium distribution
would hide that dependence and is not recommended.

For frames where both inserts pass simultaneously, the directed face-normal separation is
72.3 ± 16.8° in replica A (`n=887`) and 146.7 ± 27.4° in replica B (`n=720`). This is the
clearest coupled-orientation difference between the lineages.

As a positional control, mean C1′ distance from the two-helix-frame origin is 6.96/4.06 Å
for bp13/bp14 in replica A and 8.05/4.53 Å in replica B. The positional angular phase space
is exported separately from slab orientation.

## Exports

- `plots/slab_orientation_phase_space.{png,pdf}` — primary 2D spherical phase spaces.
- `plots/c1_position_phase_space.{png,pdf}` — C1′ positional control.
- `plots/slab_orientation_pair_coupling.{png,pdf}` — paired angle over time and density.
- `data/orientation_samples.csv` — all points, quality decisions, spherical angles, and
  component vectors.
- `data/summary.json` — group means, stable windows, failures, and paired-angle statistics.
- `data/archive_inventory.json` — all matching archive packages and DCD classification.

The face normal is directed because it comes from the nucleotide template. If a later
analysis treats a plain rectangular slab as head–tail symmetric, it should fold antipodal
directions explicitly; these exports intentionally retain the chemically directed frame.

## 24hb comparison — 338 crossover environments

The archived `24hb_1xT` metric cache supplies 509 sampled frames for all 338 extra bases.
Mean global duplex pairing is 99.28% (minimum 98.59%); 160,333 insert observations survive
the same stable-window filters. The density gives every crossover unit total mass, so a
site with more valid frames cannot dominate a site with fewer. Confidence intervals use
300 crossover-level bootstrap replicates and the histogram is corrected for spherical
solid angle.

Of the 338 inserts, 318 form 159 adjacent reciprocal pairs: 159 lower-bp and 159 higher-bp
sides. Twenty have no adjacent reciprocal insert and are reported separately.

| group | sites | traversal-aligned density peak (azimuth, polar) | per-site median R |
|---|---:|---:|---:|
| reciprocal lower-bp | 159 | (+162.5°, 62.5°) | 0.876 |
| reciprocal higher-bp | 159 | (−157.5°, 117.5°) | 0.883 |
| no adjacent reciprocal insert | 20 | (−102.5°, 177.5°) | 0.715 |

The key interpretation is hierarchical: **an individual crossover usually holds its extra
base in a fairly concentrated orientation, but different crossovers select different
basins.** Pooling all sites weakens the mean because those basins partly cancel, not
because every base is freely isotropic. After aligning every frame to the chemical 3′
source→5′ destination direction, the equal-crossover mean normals of the reciprocal lower
and upper sides are separated by 61.7°.

The minimal 2hb construct remains useful as a mechanistic example but is not sufficient by
itself for a general orientation claim.

Large-bundle exports:

- `plots/24hb_orientation_density.{png,pdf}` — full-ensemble, traversal-aligned spherical
  densities for all 160,333 stable observations with equal crossover weighting.
- `plots/24hb_reciprocal_full_ensemble_density.{png,pdf}` — focused lower/higher full-
  ensemble comparison (`24hb_per_crossover_means` is retained as a legacy filename alias).
- `data/24hb_orientation_samples.csv.gz` — all 160,333 stable observations.
- `data/24hb_per_crossover_summary.csv` — one statistical row per crossover.
- `data/24hb_density_grid.npz` / `data/24hb_summary.json` — density estimates,
  crossover-bootstrap intervals, and numerical summaries.
- `data/24hb_hop_orientation_samples.csv.gz` — all stable observations transformed into
  the chemical-hop frame, including sequence and candidate-component annotations.
- `data/24hb_hop_density_grid.npz` / `data/24hb_hop_density_summary.json` — plotted
  traversal-aligned grids and numerical summaries.

## Lower- versus higher-bp subpopulations and sequence context

Subpopulation tests use one mean slab normal per crossover (`n=159` per reciprocal side).
The fixed-ID frame initially gives a strong two-lobe result: silhouette 0.69 on the
lower-bp side and 0.73 on the higher-bp side. This is not evidence for two conformational
states. Chemical traversal direction explains 100.0% and 98.1% of those assignments,
respectively. The lobes arise because a frame that always points from the lower helix ID
to the higher helix ID reverses relative to the crossover's 3′→5′ chemical hop.

After rotating every observation into a common chemical-hop frame, the lower-bp side has
only a weak/ambiguous partition: the candidate two-component silhouette is 0.353, while a
three-component fit is only marginally higher at 0.378. Its two-component labels have
median adjusted Rand index (ARI) 0.656 under 500 independent 80% subsamples. This is more
consistent with a broad or continuous distribution than two well-separated states.

The higher-bp side retains a moderate two-component structure. The candidate centers are
approximately (−142.3°, 71.2°) and (−154.0°, 114.4°), with 46 and 113 sites. Its
silhouette is 0.417 and median 80%-subsample ARI is 0.949. These are reproducible candidate
subpopulations, but their overlap and moderate silhouette do not establish distinct
thermodynamic states.

Flanking bases are defined on the extra-base-containing strand as the covalently adjacent
3′ source nucleotide and 5′ destination nucleotide. Paired-strand identities are exact
Watson–Crick complements and therefore are not independent predictors. Association tests
use the full 3D mean direction in the chemical-hop frame and permute base labels within
`lattice edge × bp mod 21` structural strata (20,000 permutations). False-discovery rates
are controlled across the eight prespecified side/flank tests.

No lower-bp association is detected: source identity explains 1.0% of directional
variance (`q=0.957`) and destination identity explains 1.9% (`q=0.661`). On the higher-bp
side, source identity explains 5.3% (`p=0.0109`, `q=0.0436`), while destination identity
does not survive (`R²=2.8%`, `q=0.425`). Collapsing source identity to purine versus
pyrimidine explains 3.1% (`p=0.00340`, `q=0.0272`): the purine mean is shifted by 11.4°
in polar angle relative to pyrimidines (structure-stratified bootstrap 95% CI 4.4–18.6°).
The exploratory 16-level source→destination dinucleotide test is positive only on the
higher-bp side (`R²=15.3%`, `p=0.0119`), but it is sparse and likely includes the source
effect; it was not included in the prespecified FDR family.

These sequence results are associations within one design and one trajectory, not a
causal base-stacking test. Sequence, scaffold position, and unmodeled local geometry can
remain correlated even after the structural stratification. Independent trajectories and,
ideally, sequence-swapped crossover constructs are needed to establish causality.

Additional exports:

- `plots/24hb_orientation_subpopulations.{png,pdf}` — full-ensemble densities for each
  chemical-hop-frame candidate component; site assignments still come from crossover
  means so trajectory frames are not treated as independent replicates.
- `plots/24hb_flank_sequence_association.{png,pdf}` — 16 full-ensemble phase densities
  split by lower/higher side, source/destination flank, and base identity.
- `data/24hb_subpopulation_membership.csv` — per-crossover frames, flank identities, and
  candidate assignments.
- `data/24hb_sequence_association_tests.csv` — effect sizes, permutation p-values, and
  prespecified-test FDR values.
- `data/24hb_subpopulation_summary.json` — cluster centers, silhouette sweep, stability,
  bootstrap intervals, and sequence checks.

## Representative molecular pair audit

Four real stable observations were selected from distinct reciprocal pairs to make the
pairwise angle language visually concrete. The panels span a strongly opposed case
(159.1°), an ensemble-typical case (127.0°), a near-orthogonal case (90.7°), and a rare
same-hemisphere case (62.0°). Selection required both per-site resultant lengths above
0.75 and both frame-level template-fit RMSDs below 1 Å.

Each local view shows the lower-bp insert and directed template normal in blue, the
higher-bp insert and normal in orange, and five neighboring base-pair levels on both
helices in gray. These are actual coordinates extracted from the archived 181 GB DCD;
they are not reconstructed from the phase-density means. The examples illustrate support
across the distribution and must not be interpreted as four equally populated states.

- `plots/24hb_pair_orientation_audit.{png,pdf}` — four-panel molecular comparison.
- `data/pair_orientation_audit/manifest.{json,csv}` — exact crossover IDs, frames, times,
  measured angles, fit quality, and render provenance.
- `data/pair_orientation_audit/*/{context,lower,upper}.pdb` and `normals.bild` — local
  structures and directed-normal overlays for interactive ChimeraX inspection.
