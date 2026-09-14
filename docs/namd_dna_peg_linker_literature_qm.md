# DNA–PEG linker literature and QM plan

Assessed 2026-09-12. Status: research and proposed calculations only; no QM jobs
submitted, molecular placements changed, or parameters released.

## Chemistry recommendation

Prioritize **5′-modified DNA–DBCO + azido-PEG, forming the SPAAC cycloadduct**
for a literature-backed covalent origami conjugate. Retain **amino-DNA +
NHS-activated PEG, forming an amide**, as a simpler second target. This is an
implementation recommendation, not a measured ranking of laboratory adoption.
The targeted literature search does **not** establish a single “most commonly
used” covalent PEG–DNA linker.

Distinguish covalent conjugation from oligolysine–PEG passivation. The latter
is a well-established origami coating approach, but PEG-bearing oligolysine
associates electrostatically with DNA; it supplies no covalent DNA–PEG junction
to parameterize. [Ponnuswamy et al., 2017](https://www.nature.com/articles/ncomms15654)
and [Tailoring DNA Origami Protection, 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11826485/).

| Primary evidence | Actual connection and relevance |
|---|---|
| [In Situ Covalent Functionalization of DNA Origami Virus-Like Particles, 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8628367/) | Outward-facing staple 5′ ends bear TT and TEG–DBCO; PEG10k–azide is clicked onto assembled origami. Strong direct evidence for a covalent SPAAC target. |
| [Growth and site-specific organization of micron-scale biomolecular devices on living mammalian cells, 2021](https://www.nature.com/articles/s41467-021-25890-z) | NHS–PEG20k reacts with amino-modified DNA. Supports the amide alternative in an origami-seeded DNA nanotube system, rather than claiming it as a survey of origami coatings. |
| [Cooperative control of a DNA origami force sensor, 2024](https://www.nature.com/articles/s41598-024-53841-3) | DBCO–PEG4–NHS and azide-DNA participate in PEGylated surface attachment. Relevant to our surface tether; this combines amide and click chemistry. |
| [A DNA robotic switch with regulated autonomous display of cytotoxic ligand nanopatterns, 2024](https://www.nature.com/articles/s41565-024-01676-4) | PEG5k–ssDNA hybridizes to 20 origami protrusions. The retrieved methods establish assembly by hybridization but do not resolve the PEG–ssDNA chemical junction; excluded from chemistry ranking. |

Searches covered direct PEGylation, NHS/amine, DBCO/azide, maleimide/thiol and
oligolysine coatings. PEG precipitation, crowding, PEG-containing antibody
crosslinkers and non-PEG polymer conjugates were not counted as direct PEG–DNA
coating evidence. No bibliometric denominator was assembled. Thiol–maleimide
is not selected as the default on the evidence reviewed.

## Exact structure remains the first gate

“TEG–DBCO,” “NHS–PEG,” and a molecular weight do not fully specify the product.
Before generating coordinates, obtain the chosen supplier's chemical drawing
or an explicitly reviewed atom-mapped structure. Record:

- DNA terminus and nucleotide, phosphate connection, spacer connectivity and length.
- Reacted linker atom graph, stereochemistry, formal charge and protonation.
- Every distinct SPAAC regioisomer permitted by that particular cyclooctyne;
  do not assume a single CuAAC-like 1,4 product. Keep the full DBCO-derived ring
  system, including its substituents. Azide and alkyne are consumed.
- For the amide alternative, the actual activated ester's carbonyl-side spacer
  and the amino-DNA spacer. NHS is a leaving group and is absent from the product.
- Explicit PEG repeat count and both end groups. The current methyl-capped PEG8
  builder cannot retain a methyl cap at an end that the chemical product replaces.
- Which distal PEG end, if any, receives the existing mechanical surface graft.

These unresolved identities block executable QM inputs, not this plan. No
guessed SMILES or guessed 5′/3′ connectivity is introduced here. The proposal is
to start with the published 5′ SPAAC architecture; exact topology needs review.

## Scope of parameterization

Reuse the pinned additive ether repeat model and existing CHARMM DNA parameters.
Audit their combined atom types, nonbonded conventions and all junction terms
before deciding what needs fitting. A missing-parameter check alone cannot
validate a transferred parameter. Preserve established DNA and remote PEG
charges/terms; use new junction types where sharing a type would retune them.

Prepare three model classes after identity is resolved:

1. **Junction core:** complete reacted click linker with short flanking spacers
   and two EO repeats on the PEG side. Preserve conjugation and ring strain.
   Build each chemically distinct product separately. For an amide pilot,
   substitute its actual amide core and spacers.
2. **DNA boundary:** the actual terminal phosphate/spacer connection, with a
   chemically capped nucleotide model. Determine its integer charge from the
   graph; do not assume the neutral core's charge applies to this fragment.
3. **Transfer holdout:** a larger nucleotide–linker–PEG fragment, with additional
   EO units and conformers excluded from fitting. Increase fragment size until
   artificial caps do not materially determine the junction fit.

Do not do QM on an entire 5–20 kDa PEG or origami. We need equilibrium product
parameters; reaction transition states, reaction yields and ab initio MD are
not prerequisites for fixed-topology NAMD.

## Proposed calculation set

The CHARMM-compatible baseline is MP2/6-31G(d) geometry/Hessian/torsion work and
HF/6-31G(d) model–water targets for charge fitting. For neutral polar models,
the standard water target corrections are energy ×1.16 and distance −0.2 Å;
do not apply those neutral corrections to charged models. Fit charges against
hydration targets and appropriate dipole information, rather than substituting
an unrelated RESP workflow. See the primary
[ffTK methods paper, 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11531335/)
and [MacKerell force-field development resources](https://mackerell.umaryland.edu/ff_dev.shtml).

The following sampling counts and release thresholds are **our proposed pilot
design**, not claims that a paper mandates them:

| Stage | Calculations and deliverable |
|---|---|
| Coverage first | Enumerate atom types, charges, bonds, angles, Urey–Bradley terms, torsions, impropers and exclusions after patching. Record each term's source and analogy confidence. Fit only deficient terms. |
| Conformers | Generate inexpensive diverse conformers, including ring and spacer states; optimize 6–12 distinct candidates per core/product and boundary model. Deduplicate after optimization. |
| Curvature | Full Cartesian Hessians at 2–3 distinct low-energy minima per model. Check gradients and projected vibrational modes; investigate imaginary modes before accepting a minimum. Fit local bonds/angles without changing remote DNA constants. |
| Electrostatics | On at least two conformers, place TIP3P probes at every accessible new donor/acceptor site with at least two orientations. Optimize probe distance/orientation with fixed monomer geometries; retain monomer reference energies and raw/corrected targets. Enforce integer fragment charge and fixed boundary charges. Use a consistent origin for charged-model dipoles; they are not origin-independent targets. |
| Torsions | Relaxed constrained scans of deficient rotatable junction/spacer bonds: 24 points over 360° at 15° spacing, starting in both directions to expose hysteresis. Treat ring puckering with conformer families, not arbitrary independent ring-bond rotations. |
| Coupling | Only if residuals demonstrate coupling, add a 12×12 two-torsion surface for an adjacent pair; validate interpolated low-energy regions on independent points. |
| Holdouts | Predict larger-fragment geometry, hydration and low-energy conformer ordering without refitting to those targets. Split entire conformers/scan families, not neighboring scan points, between fit and validation. |

For anionic boundary models, the repository's existing QM protocol uses diffuse
basis functions. Adopt MP2/6-31+G(d) and HF/6-31+G(d) as the **proposed charged
branch**, benchmark representative water/conformer targets and document this
choice separately from the neutral reference protocol. Do not silently compare
energies from different model chemistries. Calibrate density-fitting against
direct calculations before using it for production hydration targets.

Example budget, **per core/product**, assuming eight new polar sites and six
deficient rotatable bonds: 8 optimizations + 3 Hessians + 32 probe optimizations
(8 sites × 2 orientations × 2 conformers) + 288 scan-point optimizations
(6 × 24 × 2 directions) = **331 top-level tasks**, plus monomer/property references,
holdouts, retries and the boundary models. One coupled surface adds 144 points
per starting conformer. These are planning counts, not submitted jobs or CPU-hour
estimates; a Hessian or probe optimization can contain many electronic calculations.
Benchmark one core optimization, Hessian and scan segment before allocating time.

## NAMD release and remaining barriers

Proposed initial acceptance targets are: complete parameter coverage and exact
charge/valence accounting; held-out junction bond lengths within 0.03 Å and angles
within 5° of corresponding QM minima; relative-energy RMSE ≤1 kcal/mol for held-out
conformers within 5 kcal/mol of the reference minimum. Report maximum errors and
hydration-site residuals as well as averages. These are screening gates, not
proof of physical accuracy; failures require diagnosis, not automatic tolerance
relaxation. Assess torsional minima/barriers explicitly even if average error passes.

Export a versioned topology/patch and parameter stream, with immutable atom maps,
source hashes, charge constraints and fitting provenance. Compare static energies
and forces between NAMD and a reference CHARMM-compatible implementation using
matched nonbonded settings. Check all junction-generated terms and 1–4 exclusions.

Then qualify soluble short-duplex–PEG, followed by the wall-tethered conjugate,
then origami. Rebuild HMR from the final covalent graph and compare physical-mass
2 fs against HMR 4 fs with multiple seeds and energy-drift probes. The successful
PEG-only 4 fs run does not validate a new linker. The wall and distal positional
graft need no QM; they remain mechanical approximations. DNA–PEG connectivity
uses the chemical topology, not an extra positional spring.

Mixed-system ion compatibility, DNA/PEG safety and restraint-energy accounting,
skip logic, atom classification and visualization remain separate engineering
gates in [the readiness assessment](namd_dna_peg_readiness.md).

Reuse the existing Psi4 generation/audit patterns in
`backend/parameterization/photoproduct_qm.py`, charge/Hessian/torsion fitting and
parameter-coverage tools, but introduce a linker-specific schema and adapters;
CPD-specific chemistry assumptions are not transferable. The declarative
[QM plan](../experiments/peg_dna_linker/qm_plan.json) is not accepted by a runner yet.
Implement input generation and fail-closed graph/charge/coverage checks before
submission. Normal molecular integration still requires the repository's concrete
geometry review artifact; real calculations use the guarded test-session workflow.
