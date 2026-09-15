# Streptavidin on gold: simulation precedents and packing calibration

Literature checked 2026-09-12. This is a research assessment, not a force-field
implementation or a change to existing saved coatings.

## Direct and adjacent simulation precedents

**Direct coated-sphere precedent:** Gurtovenko, Javanainen, Lolicato and Vattulainen,
[The Devil Is in the Details…](https://doi.org/10.1021/acs.jpclett.9b00065),
J. Phys. Chem. Lett. 10, 1005–1011 (2019), explicitly simulated streptavidin-coated
5 and 10 nm gold spheres attached to membrane lipids. They used Martini in
GROMACS 5.1.4, with three 50 μs replicas per principal system. The particle and
coating affected lipid motion, including interactions by non-linking tetramers.
This establishes a working precedent, not an equilibrium coverage calculation.
[Author-hosted paper](https://www.biosimu.org/publications/PDFs/gurt2019-NP-bilayer-jpclett.pdf).

The [supporting information, pp. S3–S4](https://ndownloader.figshare.com/files/14405075)
is especially useful: they **assumed 50% coverage and 25 nm² contact area**,
then assigned **one tetramer to 5 nm and six to 10 nm**. PDB 1SWE was completed
with Modeller and converted to Martini 2.2 with an elastic network. Gold was
represented by C5 beads with gold atomic masses, using one bead per gold atom.
Protein amino groups were bonded to surface beads; biotin binding was also
represented by a bond. These are coarse-grained attachment assumptions, not
validated atomistic Au–amine chemistry or reversible biotin kinetics. Thus the
paper supports a reproducible sparse-loading benchmark, not universal saturation.

**Atomistic attachment/orientation precedent:** Dutta et al.,
[Tuning gold-based surface functionalization for streptavidin detection](https://doi.org/10.3389/fmolb.2022.1006525)
(2022), combined SDA Brownian docking with GROMACS/GolP atomistic refinement on
flat Au(111) bearing thiol–PEG/biotin–PEG. PEG densities were 0.4 and 0.8 chains/nm²,
with 50% or 100% biotinylation. Stable protein center heights were approximately
3.5 or 5.5 nm in different preparations; the sparse half-biotinylated case detached.
These are protein-center heights, not linker lengths. Ligand density and
multivalent contact matter; this is not a curved-sphere packing study.

**NAMD:** Comer, Ho and Aksimentiev,
[Toward detection of DNA-bound proteins using solid-state nanopores](https://pmc.ncbi.nlm.nih.gov/articles/PMC3789251/)
(2012), simulated streptavidin–biotin–DNA using CHARMM-compatible biotin and custom
linker topology, including linker force–extension calibration. It is relevant to
protein/linker preparation, but contains no streptavidin-coated gold core.
I did not locate a directly matching NAMD coated-gold study in this search.

**oxDNA:** I did not locate a directly matching streptavidin-coated gold simulation.
[Fochtman's 2017 thesis](https://scholarworks.uark.edu/etd/1926/) extended oxDNA for
DNA-functionalized gold building blocks, without establishing streptavidin packing.
The [DNANM implementation](https://github.com/sulcgroup/anm-oxdna) supplies protein
ANM plus oxDNA2, providing a possible foundation rather than gold-coating parameters.
Negative search results are not proof that no such work exists.

## Experimental loading anchors

| Evidence | Reported quantity | Interpretation |
|---|---|---|
| [Biofunctionalization of gold nanoparticles… (2007)](https://doi.org/10.1016/j.mee.2007.01.247) | Approximately 40 nm² per streptavidin molecule on citrate-stabilized gold, from a monolayer/flocculation procedure | Supports our existing effective-area default for that preparation |
| [Streptavidin-coated gold nanoparticles… (2017)](https://www.beilstein-journals.org/bjnano/articles/8/1) | 14.1 ± 0.4 nm TEM core; geometric estimate ≈25 tetramers, optical-shell estimate ≈30; DLS diameter changes 19.4 → 31.1 nm | The estimates are method-dependent; the 5.8 nm radial hydrodynamic increment is not a measured linker length |
| [Cytodiagnostics technical table](https://www.cytodiagnostics.com/pages/gold-silver-gold-nanourchin-conjugates-technical-information) | Theoretical maxima of 5 and 20 streptavidins for 5 and 10 nm particles | Vendor docking-area capacities, not measured occupancies; do not equate these to the sparse simulation preparation |

The 2017 optical count implies an effective core area of `π × 14.1² / 30 =
20.82 nm²/tetramer` (our calculation). Its geometric estimate and optical estimate
are not independent direct protein counts. Do not promote 30 to an exact target
for every particle of that size. Core area, hydrated-shell area, experimental
loading, and maximum geometric occupancy are different quantities.

A separate [gold-nanorod modeling study](https://pmc.ncbi.nlm.nih.gov/articles/PMC2811423/)
contrasted random sequential adsorption (packing fraction 0.54) with ordered
hexagonal packing (0.9). This reinforces the need to distinguish deposition
history from ideal packing; those planar hard-particle fractions are not a
universal law for finite spherical PDB proteins.

## Consequences for NADOC (our calculations and recommendations)

Our current target is `floor(πD² / A_effective)`, with `A_effective = 40 nm²`.
For 5, 10 and 14.1 nm cores this yields 1, 7 and 15 tetramers. The first two are
close to the sparse 2019 simulation, but 15 falls well below the 2017 estimates.
The UI's current 25–100 nm² range also excludes the effective 20.82 nm² value.
Therefore the existing setting is a reference preparation, not a validated
universal loading curve.

Use an explicit count/density or a chemistry-specific preset. If exposing a
physical footprint `A_contact` and an occupied fraction `f`, the target is
`N = floor(f × πD² / A_contact)`. Keep `A_effective = A_contact/f` distinct:
applying another packing fraction to an already empirical effective area would
count the packing reduction twice. A 25 nm² footprint at 50% occupancy gives an
effective area of 50 nm² and reproduces the 2019 integer counts. Permit zero and
single-protein cases for intentionally sparse preparations.

For an ideal locally hexagonal arrangement, characteristic anchor spacing is
`s ≈ sqrt(2 A_effective / sqrt(3))`. Thus 40 and 50 nm² correspond to approximately
6.8 and 7.6 nm. These are derived surface-spacing estimates, **not observed
protein-center spacings**. On a sphere, for angular separation θ and common
protein-center height h, the center chord is `2(R+h) sin(θ/2)`; the corresponding
core-surface arc is `Rθ`. Small particles require the actual PDB transforms,
not a planar conversion. Report nearest-neighbor center distances, heavy-atom
gaps, center height, and accessible binding-pocket distances separately.

A diagnostic calculation on the present 14.1 nm model (seed 1) found:

| Current mode | Actual tetramers | Geometric protein-center height above core (nm) | Nearest-center distance min / median / max (nm) |
|---|---:|---:|---:|
| Adsorption | 15 | 2.760–3.737 | 8.173 / 8.698 / 9.011 |
| Biotin tether, 4 nm spacer | 15 | 4.153 | 7.198 / 8.024 / 10.110 |

Here centers are unweighted means of protein heavy-atom positions, excluding
biotin, not mass-weighted centers of mass. The outermost protein atoms extend
6.962 and 7.245 nm above the respective cores. These geometric extents cannot
be equated directly to a DLS shell thickness. The current 4 nm tether spacer is
an implementation clearance choice, not literature-calibrated PEG chemistry.

For relative spacing, retain explicit PDB sterics but replace the single uniform
Fibonacci realization with a choice of uniform or random sequential deposition,
multiple seeds, and optional relaxation. Report the achieved count and its spread.
Clash rejection after one orientation attempt is not a saturation search.

For attachment orientation, distinguish adsorption, amine-mediated conjugation,
and biotin–PEG tethering. Our two current modes do not reproduce the 2019
amine-linked construction. Sample physically allowed contact sites and linker
conformations; a rigid pocket aimed at the center cannot substitute for a
validated distribution of tilt, height and mono-/multivalent attachment.

Prioritize reproducing the 2019 5/10 nm benchmark, then compare a separate dense
14.1 nm preparation with experimental loading and hydrodynamic measurements.
For oxDNA use calibrated excluded-volume bodies and attachment potentials; for
NAMD prepare protein, ligand, linker and compatible gold interactions explicitly.
Keep the existing engine guards until these models are validated. No runtime
packing defaults or saved designs were changed by this literature check.
