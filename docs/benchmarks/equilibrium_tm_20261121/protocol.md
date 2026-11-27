# Prespecified research pilot protocol — 2026-11-21

Existing 16-nucleotide export (native sequence rows GCGTTGCG / CGCAACGC),
sequence-dependent DNA2, 0.3 M salt, T=70 C, box side 7.6505909078802 oxDNA
units, 0.012 M total strands. Original topology, orientations and coordinates
copied unchanged. Four independent production seeds; alternating bound/separated
starts. No authored NADOC parts, engine modifications or CPD calculations.

Three exploratory cold-start pilots: translation/rotation/cluster cap
(0.1,0.2,12), (0.5,1,16), (1,2,16). Each: eight serial 200k-sweep tuning
rounds, 200k discarded equilibration per replica, 1M production per replica.
7-minute timeout each, incomplete blocks excluded. Native energy check every
10 sweeps, periodic-image guard retained, sampling weights frozen in production.
This changes proposals, not the equilibrium Hamiltonian. Independent training
means this comparison tests entire cold-start workflows; it does not isolate a
causal proposal-size effect from training variability.

Pilot selection is exploratory. A subsequent independent confirmation campaign
must use new seeds and fresh opposing starts. No pooling selection data into its
nominal fixed-budget confidence interval. Compare wall time including tuning,
equilibration, production and full-Hamiltonian analysis; report preceding method
selection cost separately. No under-hour claim based on amortized historical
weights. Four native workers maximum, methods sequential, no native build.

Diagnostics: biased q occupancy; q=0↔q>=6 and q=0↔q=8 passages, round trips per
replica (floor of alternating endpoint passages/2); q=0 versus q>0 population
reweighted with inverse frozen bias; full DNA2 energies reevaluated at 60–80 C,
0.5 C intervals; importance-weight ESS and influence autocorrelation; replica
and start-group Tm agreement; time-block bootstrap and between-replica t envelope.
Trapped or unbracketed replicas cannot certify precision. Native histogram
extrapolation is checked separately because its linear-temperature stacking
formula does not reevaluate temperature-dependent electrostatics.

Finite-size correction for two distinct strands: with r=Z_bound/Z_unbound in
the simulation box, bulk bound fraction = 2r/(2r+1+sqrt(4r+1)); at bulk Tm, r=2.
No concentration rescaling or change of physical model in the sampler comparison.
Sampling CIs do not include force-field error or experimental discrepancy.

Primary sources informing selection:
- Whitelam & Geissler (2007), collective virtual moves:
  https://arxiv.org/abs/cond-mat/0508100
- Ouldridge et al. (2009/2010), finite-size association correction:
  https://arxiv.org/abs/0910.1201
- Šulc et al. (2012), sequence-dependent thermodynamics:
  https://arxiv.org/abs/1207.3391
- Snodin et al. (2015), DNA2 and salt-dependent electrostatics:
  https://arxiv.org/abs/1504.00821
- Trebst, Huse & Troyer (2004), optimize round trips rather than flat occupancy:
  https://arxiv.org/abs/cond-mat/0401195
- Native VMMC umbrella inputs and histogram documentation:
  https://lorenzo-rovigatti.github.io/oxDNA/umbrella_sampling.html

Alternatives considered: temperature replica exchange needs full cross-Hamiltonian
swap energies and demonstrated configuration round trips, not just temperature
swaps; distance/pairing multidimensional bias may resolve hidden alignment but
requires independent coverage and normalization checks; optimized-ensemble
feedback requires enough initial endpoint traffic to estimate local diffusivity.
These are not benchmarked by the proposal pilots. Nearest-neighbor thermodynamics
is a useful rapid undamaged-sequence model, not a substitute for DNA2 equilibrium
or a CPD-isomer parameterization (SantaLucia 1998,
https://pmc.ncbi.nlm.nih.gov/articles/PMC19045/).

## Distance-coordinate follow-up (specified before its pilot)

Native `mindistance` over the eight native partner base-site pairs, split at
1 length unit; q=0 near and far bins both contribute to the unbound partition
sum. Far/bonded bins are checked to be unoccupied rather than silently discarded.
Translation .5, rotation 1, cluster cap 12. Four training walkers (alternating
bound/unbound), eight shared-weight 200k-sweep rounds; counts pooled at each
update. Fresh independent production starts, 200k discarded equilibration,
1M production/replica, output every 1k sweeps, 12-minute hard cap. A 10k-sweep
native smoke precedes it and is excluded from scientific estimates.

Only a candidate with endpoint traffic merits a substantially longer follow-up.
Inspect full round trips and opposing-start disagreement before choosing a
fixed-budget independent confirmation; do not extend merely to narrow a trapped
trajectory's error bar. A failed pilot is evidence about this budget and setting,
not proof that a class of algorithms cannot work. Any confirmation selection
and budget will be recorded before launch.

A matched four-walker, q-only control is also scheduled (seed 711100), with
identical moves (.5/1/cap12), training/equilibration/production lengths and 1k
cadence to the distance pilot. This separates the coordinate comparison from
the serial-training/small-move historical baseline, although one independently
trained campaign per arm still cannot establish a precise efficiency ranking.

## Relative melting temperatures

For later CPD comparisons, an alchemical bound/unbound thermodynamic cycle may
avoid repeating the rare association event for every isomer. This is a proposed
research direction, not an implemented or benchmarked result. It requires a
validated lesion Hamiltonian, reversible sampling of each end state, overlapping
intermediate ensembles and forward/reverse consistency. BAR/MBAR can estimate
free-energy differences from such overlapping equilibrium ensembles; neither
estimator repairs missing metastable states. Relevant primary methods:
https://doi.org/10.1016/0021-9991(76)90078-4 and
https://pmc.ncbi.nlm.nih.gov/articles/PMC2671659/ .

Independent per-design Tm intervals of ±1 C imply roughly ±1.41 C on their
difference, not ±1 C. Reused bias training is not evidence of beneficial covariance
between design estimates. A common-reference free-energy cycle may provide useful
covariance, but its magnitude and the uncertainty in the local melting-curve
slope must be measured. Force-field/systematic-error cancellation between CPD
isomers is unvalidated. No CPD simulations or parameters were changed here.

## Independent longer confirmation (specified after distance pilot, before launch)

The distance pilot completed two full round trips, one in each of two replicas;
the others did not bracket Tm. This limited endpoint traffic justifies one bounded
longer test, not a precision claim. After the matched q-only control, run the same
two-coordinate settings with independent seed 811100 and fresh four-walker
training (8×200k), fresh opposite production starts, 200k equilibration, and up to
8×1M production sweeps per replica. Fixed 27-minute driver cap, three minutes
reserved for full-Hamiltonian analysis (30-minute candidate budget). No precision
stopping; interim checks are diagnostic only. Earlier pilot samples are excluded
from its estimate. Pilot/selection costs are reported separately and also summed
for the two-coordinate development path. A new learned bias prevents treating
this as an extension of the favorable pilot trajectory.
