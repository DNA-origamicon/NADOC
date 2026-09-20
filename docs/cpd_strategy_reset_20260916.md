# CPD strategy reset — 2026-09-16

## Assessment

The campaign has accumulated useful QM targets, corrected connectivity/stereochemistry,
and NAMD/OpenMM energy/force agreement, but has not delivered an accepted CPD nucleotide
or solvated DNA model. Engine agreement establishes implementation consistency, not
physical validity. Recent charge-only Drude fitting still misses static electrostatic
transfer criteria; re-minimizing old trajectory frames is not new candidate dynamics.

A previous reassessment (cpd_parameterization_literature_reassessment.md, September 15)
already recommended a published cis-syn comparator and a separate anti research track.
That recommendation was not completed before further custom fitting. The corrective
step is to execute the comparison, not repeat the literature review or launch another
unbounded fit. No existing failed gate is changed by this assessment.

## Established options and access

- CGenFF assigns additive CHARMM atom types, charges and bonded parameters with analogy
  penalties. It is an initial model, not molecule-specific validation. The web service
  requires an account; no account was created or terms accepted in this review.
  https://cgenff.com/
  https://app.cgenff.com/signup
  https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/
- FFParam provides CHARMM additive and Drude optimization/validation, supports Psi4 and
  OpenMM, and v2 adds LJ/condensed-phase and coupled bonded fitting capabilities. This
  is the relevant established comparator for our bespoke Drude optimizer. The public
  installation/download pages still describe v1.2; v2 availability and exact dependencies
  must be checked before promising an operational installation.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11260432/
  https://ffparam.silcsbio.com/manual/installation.html
  https://ffparam.silcsbio.com/download.php
- Ma/van der Vaart 2017 supplies CPD parameter tables, atom numbering and charges in SI.
  Existing project provenance already records this candidate. Reconstruct and audit a
  comparison stream; absent original machine-readable files is an engineering/provenance
  task, not evidence that wholesale independent fitting is necessary.
  https://pubs.acs.org/doi/10.1021/acs.jcim.7b00215
- The AMBER parameter archive offers an actual DIM library and force-field file.
  Broken pdrives links were recovered from the corresponding public personalpages paths.
  Hashes and downloads are in .development-artifacts/cpd-strategy-review-20260916/.
  Contributor notes cite Antony, Medvedev and Stuchebrukhov, JACS 2000, 122, 1057;
  HF/6-31G* RESP charges and no QM fit of bonded parameters. The force-field header is
  PARM94. Exact chemical identity, stereochemistry, atom completeness and modern DNA
  compatibility have NOT been established. Do not treat the database label as validation.
  https://personalpages.manchester.ac.uk/staff/Richard.Bryce/amber/index.html
  https://personalpages.manchester.ac.uk/staff/Richard.Bryce/amber/nuc/DIM.lib
  https://personalpages.manchester.ac.uk/staff/Richard.Bryce/amber/cof/FADH-_inf.html
- NAMD directly supports additive AMBER topology/coordinates. An AMBER alternative needs
  a coherent AMBER DNA/lesion/water model and verified exclusions/scaling, not insertion
  of AMBER lesion constants into CHARMM DNA.
  https://www.ks.uiuc.edu/Research/namd/3.0/ug/node13.html

The official February 2026 CHARMM archive was already searched and pinned in
cpd_forcefield_provenance.md. It did not contain a ready CPD DNA patch; repeating that
search is lower priority than evaluating the published comparator.

## Next concrete milestones

1. Freeze further ad hoc fitting expansion. Preserve the bounded running water and sugar
   calculations and their results. No new cloud allocation for this review.
2. Reconstruct the published CHARMM cis-syn model as an isolated comparator with explicit
   atom mapping, source-table checks, full term/charge audits, and documented dependencies.
   Obtain a CGenFF assignment if account access is available; otherwise do not stall the
   published-model reconstruction on web registration.
3. Assemble complete CPD d(TpT) and a short duplex plus matched undamaged control. Validate
   all new sugar/base boundary terms, chirality, engine energies/forces, then replicated
   explicit-solvent behavior and relevant structural observables. A successful load or
   short stable trajectory alone does not establish physical validity.
4. Keep cis-anti interstrand Drude as an explicit separate requirement, not implicitly
   satisfied by cis-syn success. Benchmark FFParam against existing QM data and current
   model before adding targets. Review charge/polarizability/Thole/LJ coupling and model
   adequacy rather than repeating charge-only fits.
5. Separate inviolable topology/numerical checks from quantitative model-quality targets
   and intended-use validation. Any revised release policy must be explicit and versioned;
   previously failed results remain failed. No thresholds were relaxed in this review.

The persistent full CPD goal remains incomplete. A published additive baseline is a
way to obtain comparative evidence and an earlier cis-syn deliverable, not a replacement
for the requested anti/Drude validation.
