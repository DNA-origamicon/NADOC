# Cis-anti qualification: remaining work

Current result: an earlier parameter bundle passed the100ps full-DNA NAMD
engineering tests. The latest development trial, model61, passes energy and
representative geometry checks but fails three exposed shape tests. It has not
received prospective validation or engine checks with its changed parameters.
See the [audited closeout](cpd_anti_shape_fit_closeout_20260927.md).

This roadmap does not authorize calculations, reopen a fit round, change a gate,
or redefine an old failure. The completed two-round contract remains closed.

## First resolve the parameter-model question

Keep Sella for molecular geometry optimization and use process isolation for its
repeated calls. The remaining issue is parameter fitting and transferability.
Only three outer parameter centers and their66 derivative probes completed;
termination was by the wall clock. That does not demonstrate a converged optimum
or prove the additive model cannot pass. Conversely, unfinished model70 already
has nine shape failures, so simply finishing that vector would not produce a pass.

The next review should use the saved Jacobians and geometries to distinguish two
possibilities before registering another finite execution:

1. The present22-coefficient model can improve further but needs a better bounded
   outer optimization attempt. Any new execution must state its compute allowance
   and stop conditions up front, retain all23 exposed targets, original references,
   coefficients/bounds and acceptance thresholds, and report infeasibility or
   incomplete convergence explicitly. A sum-of-squares improvement alone cannot
   satisfy the separate per-case geometry gates.
2. The allowed torsions cannot correct the relative sugar/base shape without
   degrading other targets. If local response evidence supports this, propose a
   small, chemically justified revision of coupled attachment/ring bond-angle
   terms and force constants, with QM distortion/curvature targets. Preserve parent
   DNA chemistry and audit all affected targets. Do not widen bounds or add terms
   solely because a trial failed.

The three failed whole-fragment RMSDs are0.297–0.321Å against0.25Å, while sugar
and lesion-base groups separately align within0.102–0.120Å. This supports examining
their relative arrangement. It does not uniquely identify a missing parameter.
The representative angle tests already pass; profile angle discrepancies are
diagnostic evidence, not a newly invented acceptance gate.

QM-derived bond/angle distortion targets are part of established CHARMM
parameterization: [ffTK methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC3874408/)
and the [author-maintained tutorial, section5](https://www.ks.uiuc.edu/Training/TutorialsOverview/science/ffTK/fftk-tutorial.pdf).
Positive curvature establishes local stability; agreement with QM curvature tests
stiffness. Those are different claims. Reuse valid representative evidence and
fill specific gaps; do not require a Hessian at every scan point by default.

## Then complete the fixed validation sequence

1. **Freeze a development-passing candidate.** Retain the water/charge checks,
   all23 energy/shape targets and three representative criteria. Preserve all
   failed candidates and the current energy RMS0.294398kcal/mol as exposed evidence.
2. **Run genuinely prospective fragment validation.** The registered successor
   proposes four±18.75° targets, subject to a historical exposure audit before
   acquisition. Register the candidate first and score once using shared QM/MM
   reference identities. The old±22.5° points remain exposed. Broader hydration or
   interaction transfer claims need separately specified independent targets;
   passing17 fitted water curves alone is not evidence for every environment.
3. **Verify the final parameter bundle in NAMD.** Repeat affected export/energy/
   force checks and the staged full-DNA solvent pilot using the final parameters.
   Check ordinary masses/timestep, stereo, bonds, clashes, restart continuity and
   periodic-image clearance. The previous bundle's engineering pass cannot be
   transferred automatically to changed parameters.
4. **Run the agreed interstrand-context campaign.** Freeze the wall budget and
   analyses for three anti and three matched undamaged seeds, with staged startup
   followed by10ns per replica. Examine chemical integrity, lesion/attachment
   geometry, sugar/glycosidic states, local pairing/stacking/opening and replica
   variability. This is the existing bounded preliminary structural stage, not
   an equilibrium-population or mechanical-accuracy certificate.
5. **Package only the supported scope.** Preserve parameter/source hashes,
   limitations, provenance, reproducible native tests and appropriate registry
   status. Application placement remains a separate demonstrated geometry review;
   the old source-placement failure cannot be erased by trajectory stability.

## Meaning of full qualification

Completing the above establishes the previously agreed scope: preliminary
exploratory structural use for the specified additive cis-anti interstrand
context. It does not automatically support quantitative weld stiffness, free
energies, equilibrium conformer populations, different sequences/ions, or
photochemistry.

For stronger scientific claims, first specify the observables, conditions,
independent comparison data and acceptable uncertainty. Then assess relevant
QM/MM stiffness, attachment/base/ion interactions and converged solution sampling
against those references. A fixed trajectory length is a resource budget, not
a universal convergence criterion. Missing experimental anti-junction data must
remain an explicit limitation. No full94-record legacy campaign, Drude switch,
unlimited sampling or new fitting budget is silently added by this roadmap.
