# PEG validation and calibration plan

Research and timing assessment: 9 September 2026. **Revised recommendation:
reuse published implicit-solvent PEG parameters and reproduce their CG
benchmarks first.** The [prior-work inventory](peg_prior_work.md) identifies
explicit bonded/nonbonded parameters from Chudoba et al. (2017), downloadable
MARTINI PEO assets, and existing oxDNA crowder code. Bulk atomistic
reparameterization is not a prerequisite. New atomistic work should target
the remaining surface, DNA-contact, electrolyte or field-response gaps.

The following budgets are retained as **optional new-calibration scenarios,
not the recommended starting campaign**. For short PEG at one temperature and
specified solution/surface chemistry, the previously proposed
**0.78 µs pilot costs approximately 94–255 RTX PRO 6000 GPU-hours**.
A broader neutral-surface calibration allocation is **7.72 µs and
938–2,492 GPU-hours**, about **39–104 days on one card**, with a central
estimate of 62 days. These are conditional planning estimates, not measured
PEG performance or guarantees of convergence. The pilot can contribute to the
larger campaign if its chemistry, force field, and initial states remain usable.

**No calibration production was launched. Cloud spend for this assessment: $0
of the authorized $3 benchmark budget.** Three local NAMD timing tests were run.

## Scope and assumptions

The target chemistry was not specified when this estimate was prepared. The
baseline is short neutral PEG, degree of polymerization (DP) 9–36, at 300 K;
choose one monovalent-salt bath before production, provisionally 0.15 M NaCl.
DP counts chemical ethylene-oxide repeats. Hydroxyl-terminated chains in this
range have molecular weights approximately 414–1,604 g/mol; graft chemistry
changes the end groups and molecular weight. This estimate is **not for PEG
5k/20k**, mixed electrolytes, arbitrary substrates, or an unrestricted field range.

The existing review file has eight *statistical* segments of 0.7 nm per chain.
It has no established conversion to chemical DP. Its oxDNA salt setting is
0.5 M, so results at the provisional 0.15 M bath must not be labeled as a
calibration of that salt condition. The actual substrate, linker, end group,
PEG dispersity, density, electrolyte, and intended voltage range should select
the final training conditions. Estimates below include one chosen substrate,
not a comparison across gold, graphene, silica, and lipid coatings.

“RTX PRO 6000” means the full **96 GB Blackwell** GPU, not RTX A6000, RTX 6000
Ada, or a 24 GB MIG partition. Server, workstation, and Max-Q power limits can
change throughput. All times are aggregate GPU-hours; independent replicas
and windows can run across multiple cards. Eight cards ideally divide elapsed
production time by eight, but do not divide total GPU-hours.

## What the literature supports

A particularly relevant precedent is Xie et al. (2016): an implicit-water,
freely jointed bead model fitted to PEG radius of gyration, osmotic pressure,
and second virial coefficient. It supports calibrating a simple fast model
against experimental thermodynamics rather than reproducing every atom. Its
chemical-repeat mapping and fixed bonds differ from our statistical-segment
mapping and harmonic bonds; published parameters cannot simply be copied.
[Paper](https://doi.org/10.1016/j.polymer.2015.12.034).

An alternative implicit-solvent PEG model derives effective interactions from
atomistic oligomer solutions and refines them using polymer-scale data. It
uses bonded structure and solvent-dependent pair potentials, illustrating
why changing only a WCA diameter may be insufficient. Its atomistic reference
replicas were 33 ns, while coarse-grained chain sampling extended much longer:
those numbers are different levels of resolution, not interchangeable NAMD
production prescriptions.
[Paper](https://arxiv.org/html/1710.09191v1).

For atomistic reference data, the CHARMM C35r ether study reproduced a PEG/PEO
persistence length near 0.37–0.38 nm and experimental hydrodynamic sizes.
That gives an initial Kuhn-length scale near 0.74–0.76 nm, not a validation of
our bead diameter or spring constant.
[Original study abstract](https://www.ks.uiuc.edu/Research/vmd/allversions/citations/abstracts/WOS%3A000257889400005.html).
A later ether parameterization documents deficiencies in older CHARMM ether
parameters and notes that the C35r revisions were not included in the official
C36 release it examined. Audit the actual parameter files and water model;
“CHARMM36” alone is not sufficient provenance.
[Leonard et al., 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC6295153/).

The transferable MARTINI PEO work fits transfer free energies, chain size, and
mapped bonded distributions, then tests other conditions. This is useful as
an independent comparison and possible intermediate-resolution reference;
it is not independent experimental validation of a new model fitted to it.
[Paper](https://arxiv.org/abs/1901.04413).

PEG–DNA interactions deserve their own calibration. Experiments separate
excluded-volume effects from preferential chemical interactions, including
interactions with surfaces exposed on DNA melting. A repulsive PEG–DNA
center sphere cannot be assumed to reproduce both duplex exclusion and
single-strand/base affinity.
[Knowles et al., 2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3150925/).

## Validation order and decision criteria

1. **Specify the mapping and check the engine cheaply.** Define each bead as a
   center of mass of a particular atom group, then map reference trajectories
   consistently. Measure coarse bond/angle distributions, end-to-end vectors,
   radius of gyration, and contour extension. Test CPU/CUDA equilibrium
   distributions, timestep halving, root/wall forces, and energy gradients.
   Existing pair-force checks verify implementation; they do not validate PEG.
   For a freely jointed chain with N fixed bonds and no wall or sterics, use
   `<R²> = N b²`, `<Rg²> = b² N(N+2)/[6(N+1)]`, and the Langevin
   force–extension relation. Those exact tests require disabling the additional
   interactions. Harmonic-bond distributions need their radial `r²` measure;
   they are not simply a Gaussian centered at b.

2. **Fit bulk equilibrium behavior first.** Fit chain size across DP, mapped
   bond statistics, and osmotic pressure/second virial data jointly. Reserve
   DP 27, selected concentrations, and independent replicas as held-out tests.
   A single radius of gyration cannot determine b, k, sigma, epsilon, and the
   chemical mapping uniquely. Start from a published implicit-solvent model
   and ask whether our restricted harmonic/WCA form can reproduce it. If
   chain size and osmotic pressure cannot both be fitted, add an effective
   solvent-quality term or bonded angular potential before buying more data.
   Use proper radial/angular measures when constructing Boltzmann-inverted
   initial potentials; refine iteratively rather than treating a dense-fluid
   pair distribution as an isolated pair potential.

3. **Fit and test the surface.** Compare monomer density versus height,
   chain-end height distributions, lateral correlations, and compression
   free energy for isolated/mushroom and more crowded coatings. Map tether
   location and flexibility; a stiff artificial root trap is not a chemical
   linker. Check area and solvent-height dependence. Do not use a brush
   scaling exponent as the only validation of four short sparse chains:
   the semidilute assumptions need to hold.
   [Brush scaling criteria](https://arxiv.org/abs/cond-mat/0208007).

4. **Measure DNA approach free energies.** Use a stable 12–20 bp duplex,
   with clearly stated terminal/orientation restraints applied consistently
   in atomistic and coarse-grained systems. Sample approach through a coating
   with umbrella windows, at least two approach orientations, and independent
   starts. Fit the PEG–DNA interaction against mean forces and free energies,
   not just whether two objects overlap. Hold out an orientation or portion
   of the separation range. Check contact orientations and whether attractive
   or base-specific terms are required. Duplex-only calibration must remain
   labeled duplex-only; ssDNA/overhang binding requires additional data.

5. **Accept according to uncertainty, not a fixed number of nanoseconds.**
   Proposed targets are held-out mean Rg/end-to-end size within 5–10%, surface
   mean height within 10% with the distribution also reproduced, and approach
   free energies within approximately 1 kBT over the populated working range.
   These are engineering targets, not established accuracy of this model.
   Estimate integrated autocorrelation times for the slowest measured
   coordinate. Seek at least ~100 effective samples for key means, enough
   well-separated blocks to estimate uncertainty, and agreement between
   replicas begun in extended and coiled states. Require connected umbrella
   histogram overlap and stable WHAM/MBAR profiles under time-block and
   leave-one-replica checks. Rare-event tails may need much more sampling.
   Extend unconverged states in 100–200 ns blocks or use enhanced sampling;
   a nominal 200 ns run is not proof of equilibration.

Fit equilibrium parameters before dynamics. Matching diffusion or height
relaxation requires a separate friction/time calibration. Removing solvent
also removes hydrodynamic correlations, so one Langevin friction value may
not reproduce relaxation across chain lengths and coating densities. The
current default nucleotide-like mass/time scale is not a PEG kinetic model.
The previously run QM campaign concerns other chemistry; its results are not
PEG parameters. New targeted ether/linker QM calculations would be useful
only if missing torsions or polarization are identified.

## Atomistic simulations to budget

The following is a proposed initial allocation for a broader neutral model,
with existing literature and any reusable reference trajectories supplying
starting parameters. “Equil + sample” is per replica or umbrella window.
All atoms include explicit water, ions, DNA where present, and an allowance
for substrate atoms. Use NAMD 3 GPU-resident where the required features work,
2 fs integration with constrained hydrogen bonds, PME, and the audited
force-field nonbonded settings. Do not assume a 4 fs/HMR speedup until it is
validated for the selected observables.

| Purpose | Conditions and independent replicas | Atoms per simulation | Equil + sample | Aggregate time |
|---|---|---:|---:|---:|
| Free-chain mapping and held-out length | DP 9, 18, 27, 36 × 3 | 25k–60k | 20 + 100 ns | 1.44 µs |
| Solvent quality / concentration transfer | 3 concentrations × 3 | 30k–100k | 20 + 100 ns | 1.08 µs |
| Surface height and crowding | DP 18/36 × 2 densities × 3 | 120k–220k | 50 + 200 ns | 3.00 µs |
| DNA approach free energy | 2 orientations × 16 windows × 2 starts | 100k–250k | 5 + 20 ns | 1.60 µs |
| Larger-box controls | 2 representative states × 2 | 250k–500k | 50 + 100 ns | 0.60 µs |
| **Total** | **101 trajectories/windows** | | | **7.72 µs** |

For the concentration tests, choose points spanning the target layer's local
polymer concentration (for planning, roughly 5%, 15%, and 30% by mass). They
are not three extra temperatures or salts. Published pure-water force-field
checks should precede target-salt runs; if no reusable reference is available,
a three-replica 20 + 100 ns pure-water chain control adds 0.36 µs and about
22–54 GPU-hours to this allocation.

For surface sizing, a 12 × 12 nm patch holds approximately 4 chains at the
review density, 0.0278 chains/nm², or 22 chains at 0.15 chains/nm². A water
region 8–12 nm high alone contains approximately 115k–173k atoms, using
~100 water atoms/nm³. Substrate and polymer add atoms; electrode vacuum/slab
padding adds PME work even without atoms. Choose water height from chain
height and correlation tests, not these dimensions blindly. Under strong
stretching a longer box is necessary. Keep lateral substrate area fixed;
do not isotropically pressure-scale a grafted slab or a vacuum gap. Native
harmonic substrate restraints can preserve the GPU-resident path; confirm
support for the exact wall/field implementation before timing production.

DNA windows should span bulk separation through the physically relevant
compressed coating, initially around 0.25–0.5 nm apart and adjusted for
histogram overlap. Two starts per window do not make a poorly overlapping
free-energy calculation converged. The larger-box states should stress the
most crowded coating and a representative compressed DNA state; if the PMF
is box-sensitive, repeating its windows is additional work.

For a **pilot**, use one DP 18 free chain with 3 × (10 + 50 ns), one coating
with 3 × (20 + 100 ns), and 8 preliminary DNA windows with
2 × (5 + 10 ns): **0.78 µs total**. The pilot tests parameter identifiability,
slow correlation times, and the adequacy of repulsive-only DNA sterics. It
is not enough to establish transfer across lengths, densities, or salts.
If suitable atomistic trajectories already exist, the corresponding rows
can be reduced after checking their mapping and sampling. Cheap CG sweeps
should select the expensive atomistic states; do not simulate every UI
slider value atomistically.

## Runtime evidence and estimate

Local tests used NAMD 3.0.2, one RTX 3080 Ti, four CPU threads, 2 fs steps,
NVT, a 12 Å cutoff, PME, and full electrostatics every step. The 35,254-atom
DNA/water timing proxy ran 20,000 steps per case; the official 92,224-atom
ApoA1 proxy ran for the built-in 60-second benchmark limit. Its expected
benchmark termination prints a CmiAbort message, not a dynamics instability.
The unrelated QM process was left running; the GPU showed 16% utilization
before timing. No PEG atomistic input was constructed for these tests.

| Local timing proxy | Median short timing rate | Longer timing average |
|---|---:|---:|
| 35,254 atoms, no Colvars | 147 ns/day | 143 ns/day |
| Same system, 4 distance Colvars | 119 ns/day | 121 ns/day |
| 92,224 atoms, ApoA1 | 94 ns/day | 93 ns/day |

These short timing samples are performance diagnostics, not independent
scientific replicas. The Colvars case had about 20% lower throughput in this
local comparison; that penalty is not universal. Logs, exact configurations,
checksums, and results are retained in
[`experiments/peg_validation_benchmark`](../experiments/peg_validation_benchmark/benchmark_summary.json).
[Official benchmark source](https://www.ks.uiuc.edu/Research/namd/benchmarks/).

As a target-hardware anchor, NVIDIA's **RTX PRO 6000 Blackwell Server Edition
section** reports aggregate NAMD rates of 964 ns/day for ApoA1 NVE across two
GPUs and 74 ns/day for STMV NVE across two GPUs, using independent MPS
instances. Dividing by two gives aggregate per-GPU equivalents of 482 and
37 ns/day, not guaranteed single-trajectory rates. These are different
settings/version from our local tests; a direct speedup ratio is invalid.
The page's following PRO 4500 section also has tables labeled “6000,” so use
the surrounding section heading to avoid mixing datasets.
[NVIDIA performance page](https://developer.nvidia.com/hpc-application-performance).

NAMD's documentation recommends benchmarking CPU thread count and notes that
Colvars/Tcl forces can reintroduce CPU/device transfers. Independent replicas
are generally a better use of multiple GPUs for small systems than splitting
one small trajectory. These details are why the forecast uses separate rates
for bulk, surfaces, and umbrella windows.
[NAMD GPU guidance](https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node102.html).

| Stage | Assumed RTX PRO 6000 rate, ns/day | Central rate | GPU-hours including 25% overhead |
|---|---:|---:|---:|
| Free chains | 200–500 | 350 | 86–216 |
| Concentration series | 150–400 | 250 | 81–216 |
| Grafted surfaces | 100–250 | 160 | 360–900 |
| DNA windows with bias | 60–180 | 110 | 267–800 |
| Larger boxes | 50–125 | 80 | 144–360 |
| **Total** | | | **938–2,492; central 1,477** |

Rates mean effective aggregate simulated ns/day per GPU; if replicas run
concurrently, sum their throughput once and do not also divide GPU-hours by
the replica count. These rate bands are **our planning assumptions**, bounded by local proxies
and published target-card results; no RTX PRO 6000 PEG benchmark was run.
They are not statistical confidence intervals. Routine minimization,
restart/setup work, and short fitting/analysis runs are provisioned by the
25% overhead allowance. Large parameterization iterations, GPU-offload-only
surface methods, poor mixing, and additional chemistry are outside it.
Difficult states can require 2–4 times their allocated sampling. A dedicated
10–20 minute target-card test becomes worthwhile once the real PEG boxes,
restraints, and field methods are fixed; it will narrow throughput uncertainty
but will not determine the sampling time needed for convergence.

Arithmetic is `GPU-hours = 1.25 × 24 × aggregate_ns / throughput_ns_per_day`.
The [calculator](../experiments/peg_validation_benchmark/estimate_campaign.py),
[CSV](../experiments/peg_validation_benchmark/campaign_estimate.csv), and
[JSON](../experiments/peg_validation_benchmark/campaign_estimate.json) retain
all allocations and rates. Replacing a rate updates the estimate transparently.

Runpod's current GPU listing shows RTX Pro 6000 from $1.69/hour; its Secure
Cloud guide quotes $2.09/hour. Availability, edition, and storage can change
actual quotes. At those illustrative rates, the pilot is approximately
**$159–533**, and the neutral campaign **$1,585–5,208**, excluding storage.
The $3 authorization covered assessment benchmarks only; no production budget
has been spent or assumed authorized.
[GPU listing](https://www.runpod.io/gpu-models),
[Secure Cloud pricing guide](https://www.runpod.io/articles/guides/ai-server-cost).

For trajectory storage, 7.72 µs sampled every 10 ps at an illustrative
150k atoms/frame is about 1.4 TB of uncompressed xyz data. Save polymer/DNA
coordinates and reduced observables frequently, full solvent much less often,
and separate short high-frequency trajectories if calibrating dynamics.

## Electric fields: a separate model decision

The neutral oxDNA PEG beads currently have no dipoles, polarizability, or
field-dependent potential. **More NAMD data cannot calibrate a direct neutral
field response into an interaction that has no such degree of freedom.**
Uniform-field atomistic simulations can test whether that missing response
matters and provide a reference for a future effective interaction.

There is direct precedent for field-induced conformational switching in
PEG-terminated alkanethiol monolayers on gold, with polarity-dependent
conformations. It is evidence that microscopic chemistry matters, not a
parameter set transferable to a neutral water-soluble chain on any surface.
[Vemparala et al., 2004](https://doi.org/10.1063/1.1781120).

After the zero-field model passes, an initial field-response allocation is
one DP at two densities, E = 0, ±0.01, ±0.05 V/nm, three replicas per state,
each 50 ns equilibration plus 200 ns sampling. Reusing the two zero-field
states leaves **8 × 3 × 250 ns = 6 µs additional sampling**. Larger solvent
boxes and field/bias work justify an assumed 80–200 ns/day, or **900–2,250
additional GPU-hours** including 25% overhead. This is one end-group chemistry
and one electrolyte. A charged-terminal series adds approximately another
similar block; it is not automatically covered by the neutral series.

The field values are diagnostic local-field hypotheses, not recommended
operating voltages. Test both signs, relaxation from both starting directions,
height/dipole distributions, ion profiles, and uncertainty in reversible
switching. A constant field in periodic salt water can drive ion current;
monitor that nonequilibrium behavior instead of automatically treating a
height histogram as an equilibrium free energy. An optional effective
height/orientation potential is condition-specific. Assigning arbitrary
charges to neutral beads is not a substitute for its derivation.

For a **voltage-controlled conducting electrode**, model induced electrode
charge and the electrolyte double layer, or validate a reduced electrostatic
boundary condition against such a model. A uniform NAMD `eField` alone is not
that boundary condition. LAMMPS has a documented constant-potential electrode
method and is a more direct candidate for this part; benchmark its exact
implementation separately. The NAMD GPU rates above do not price that solver.
[Constant-potential method](https://docs.lammps.org/fix_electrode.html),
[Finite-field/constant-potential study](https://arxiv.org/abs/1907.00622).

The defensible first deliverable is therefore a neutral, equilibrium PEG
coating calibrated over an explicit length/density/salt range. The pilot
should decide whether the present interaction family can support that
claim before extending the model or paying for a field/electrode campaign.
