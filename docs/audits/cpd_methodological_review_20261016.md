# Corrected cis-anti-I: methodological review

Reviewed 2026-10-16 (America/Denver). Scope: pre-simulation parameter qualification;
user-managed melting systems are excluded. No new native calculation or installation
was performed for this review. Existing numerical failures remain preserved.

## Decision

Keep the DDX/PCMSolver retry routes closed. Return priority to the **matched
intramolecular QM–MM discrepancy**, using the existing canonical neutral endpoint
data before generating more reference energies. Solvent calculations are a separate
chemical-transfer diagnostic, not a prerequisite that must be made to converge at
any cost. A successful solvent calculation would not repair the original 7.74
kcal/mol gas-phase mismatch or establish a transferable bonded correction.

An independent PySCF IEF-PCM implementation is the preferred *conditional*
solvent cross-check, not the next large production calculation. Its Gaussian
surface representation and analytic AO/surface integrals offer a different
numerical route. Its memory demands must be established before use.

## What our evidence establishes

- Increasing the neutral endpoint reference basis changed the relative QM energy
  by 0.58 kcal/mol, leaving approximately 7.74 kcal/mol QM–MM disagreement. Further
  basis escalation is not the first intervention.
- The cap-H cross comparisons did not remove the heavy-geometry discrepancy.
  Do not repeat this already completed diagnostic or attribute everything to OH
  orientation.
- A one-term exocyclic torsion correction looked promising locally but failed
  prospective ±30-degree holdouts, including a crowded OH/base contact. It remains
  rejected. Neither deleting that point nor fitting a larger torsional coefficient
  without decomposing the contact error is justified.
- The charged terminal proxy differs in charge, atom count, caps and reference
  method from the original neutral MP2 endpoint. Its HF/PCM relative energy cannot
  be subtracted from the neutral gas-phase MM result as a corrected fit residual.
- At fixed charge/geometry/UFF1.1 cavity, converged coarse/fine SCFs differ by
  1.802 kcal/mol. Finer density integration gives a smaller incremental frozen-
  density change (0.077), but surface refinement gives approximately 1.31.
  Removing FMM leaves 1.286 kcal/mol surface sensitivity. FMM alone is not the cause.
- Occupied-subspace loss and gaps are single-diagonalization diagnostics at a
  fixed density, not electronic stability analyses or evidence of a physical
  electronic transition. SCF convergence is not a minimum certificate.

Sources: repository audits `cpd_endpoint_basis_review_20261016.json`,
`cpd_endpoint_cap_review_20261016.json`, `cpd_endpoint_exocyclic_holdout_20261016.json`,
`cpd_ddx_standard_grid_review_20261016.json`, and
`cpd_ddx_standard_direct_closeout_20261016.json`.

## Literature and implementation assessment

CHARMM development fits selected intramolecular QM surfaces and treats
water-interaction/electrostatic targets and condensed-phase behavior separately.
DNA force-field development explicitly refined sugar puckering alongside backbone
behavior. Modified-nucleotide work likewise combines QM targets with subsequent
simulation validation, acknowledging limited experimental information [1–3]. These
precedents support a hierarchical validation strategy; they do not require exact
agreement with every isolated gas-phase conformer or justify ignoring our failed
holdouts.

The ddX theory discusses the assumption of charge contained inside the cavity and
the escaped-charge issue for Gaussian tails; it also reports this is generally
not problematic in practical applications [4]. **Our data do not demonstrate
escaped charge as the cause.** Diffuse-density/cavity interactions, surface
conditioning and density-to-reaction-potential consistency remain hypotheses.
No electron-density leakage integral or energy-derivative consistency test has
been performed. Calling this a general ddX bug would be unsupported.

The installed Psi4 interface independently controls surface harmonics/quadrature
and density-integration grids. Its reaction matrix combines numerical integrals
with an external-charge potential. Official documentation confirms these distinct
resolution controls [5]. A smooth small baseline calculation is therefore
insufficient validation for this diffuse, charged endpoint.

PySCF's non-domain-decomposition PCM supports IEF-PCM and Gaussian surface
charges; its documented source evaluates surface coupling using three-center
integrals [6,7]. This avoids the *same* Psi4/ddX density-projection path, but does
not guarantee convergence or solve every escaped-charge issue. Use explicit
UFF1.1 radii and epsilon78.3553 for comparison: default modified-Bondi radii would
change the physical cavity. Even with matched radii the discretizations differ.
Avoid switching to SMD and interpreting its extra terms as numerical repair.

Availability: PySCF is absent from the active nadoc-qm Python; NWChem is absent
from PATH. `/usr/bin/orca` is the desktop Orca application, not evidence that ORCA
quantum chemistry is installed. No system-wide executable search or installation
was performed. Any new runtime must be isolated on Archive.

## Recommended sequence and stop rules

1. **Reconcile existing endpoint targets first; no new QM.** Assemble the original,
   alternate, cap-cross and exocyclic holdout geometries into one versioned table.
   Verify identical chemistry and energy conventions within each contrast; retain
   method/basis distinctions. Report sugar pseudorotation, glycosidic/exocyclic
   torsions, close contacts, and MM bonded/electrostatic/LJ contributions at the
   exact QM coordinates. Reuse existing decompositions where available. Include
   the rejected candidate as a failed comparator, not the baseline. Determine
   whether the residual follows coupled sugar/torsion motion or contact repulsion.
2. **Only then select a small missing discriminating panel.** Use isolated,
   canonical fragments and matched constraints; distinguish rigid contact stress
   tests from constrained-relaxed torsional targets. Choose at most four new
   geometries initially, preserving previously failed holdouts and reserving new
   validation geometries. Separate terminal from phosphate-connected chemistry.
   Do not modify standard DNA sugar parameters to fix a CPD-specific endpoint.
   If no localized, transferable correction emerges, retain a parameter envelope
   rather than fitting the two endpoint energies exactly.
3. **Conditional independent solvent pilot.** First verify a pinned PySCF runtime
   and a small upstream/reference calculation. Build only the target surface to
   count retained points and estimate peak dense-matrix memory before SCF. For
   56 atoms, the unpruned 302-point surface has 16,912 points: one float64 square
   matrix is 2.13 GiB; at590 points it is8.13 GiB. Several matrices and factorization
   workspaces are required. These are upper-bound point counts, not measured peak
   memory; surface filtering can reduce them. Reject a configuration whose
   conservative peak estimate exceeds an8GiB working budget within the12GiB
   service cap. Do not quietly reduce resolution and call it validated.
4. If admitted, one same-geometry HF/def2-SVPD pilot, then one finer surface,
   each with a60-minute native/65-minute total limit, four CPUs,12GiB/no swap.
   Runtime estimates are unmeasured; these are limits, not promises. SCF energy
   and density criteria stay1e-9. Save density/checkpoint and native settings;
   audit geometry, charge, basis/AO conventions and any restart mapping. Do not
   import a Psi4 AO matrix directly without a verified basis-order transform.
   A0.5kcal/mol individual-energy screen remains an engineering triage gate.
   For a subsequent paired relative-energy comparison, predeclare0.2kcal/mol
   numerical sensitivity as the target; neither is a universal publication rule.
   One failed bounded independent pilot triggers review, not an engine/grid sweep.

All native steps remain sequential, Archive-only and event-driven. No cloud
spending. No full Hessian or optimization is needed for a fixed-geometry numerical
pilot. No CPD promotion follows from numerical completion. Final readiness still
needs held-out parameter transfer and chemically valid NAMD context checks;
thermal-stability or melting claims require the user's system-specific sampling.

## References

1. Vanommeslaeghe et al., CGenFF methodology:
   https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/
2. Hart et al., CHARMM DNA backbone and sugar optimization:
   https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/
3. Additive CHARMM force field for naturally occurring modified ribonucleotides:
   https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/
4. Nottoli et al., ddX theory and implementation:
   https://arpi.unipi.it/bitstream/11568/1258447/1/WIREs_ddX.pdf
5. Psi4 ddX interface documentation:
   https://psi4.github.io/psi4docs/master/ddx.html
6. PySCF solvent documentation:
   https://pyscf.org/user/solvent.html
7. PySCF PCM implementation:
   https://pyscf.org/_modules/pyscf/solvent/pcm.html

Literature interpretation is limited to accessible primary-source material;
current PMC full-page requests encountered access challenges, while indexed
primary article passages were available. No claims of new experimental validation.
