# Public QM and parameterization alternatives for cis-anti CPD

Reviewed 2026-09-26 UTC at the user's request. Target: preliminary additive
CHARMM/NAMD simulations of the existing ordered interstrand cis-anti lesion,
with documented limitations. This is a literature/software review, not a new
execution policy. No installation, QM, fitting, minimization, MD or remote
submission was performed. No cloud spending. The frozen v2 policy and historical
verdicts are unchanged; the previously proposed restart exception remains pending.

**Recommendation:** investigate energy/force fitting of the retained QM data as
a distinct, established parameterization route. ForceBalance is the strongest
general framework found for that purpose. If another stationary-point acquisition
attempt is chosen, use an independent optimizer, preferably Sella in minimization
mode with our existing Psi4 gradient evaluator; DL-FIND is another credible
choice. ORCA plus ffTK is the most direct alternative conventional CHARMM workflow.
These are alternatives to select between, not an automatically authorized sequence
of retries.

## Match the software to the actual failure

The [latest audited results](cpd_anti_resume_results_20260925.md) distinguish three
problems:

| Problem | Actual evidence | What an alternative can address |
|---|---|---|
| Constrained QM geometry convergence | The last 26 cached evaluations pass electronic-response, identity and stereochemistry checks. The native optimizer's small residual disagrees with the independently calculated Cartesian tangent gradient: maximum 4.6722e−5 versus the fixed 1.5e−5 hartree/bohr limit. | An independent optimizer can retain the electronic method and replace the coordinate/step/convergence machinery. This result does not show MP2 itself is unusable. |
| Force-field energy landscape | Charges pass all 17 registered water curves; three representative geometries pass. One older QM basin collapses under MM, and conformational energies remain unresolved. | Fit parameters that control the landscape, using an appropriate objective. Repeating the successful charge stage or only changing equilibrium angles will not directly fix that residual. |
| Full-DNA construction | The 62-atom fixture passed 100 ps NAMD; the 3,043-atom DNA topology passes coverage. Source conditioning reached its iteration cap with maximum mobile force 19.7611 kcal/mol/Å. | A separate construction/minimization method is needed. A fragment QM solver cannot establish that the strained DNA coordinates are ready for MD. |

The default-constraint job remains a failed reference acquisition. Its
electronically converged, correctly identified snapshots may nevertheless contain
usable **nonstationary energy/gradient data**. That use must be explicitly defined;
it does not turn those snapshots into optimized structures or certified minima.

## Independent geometry optimizers

**Sella — preferred independent optimizer pilot.** This open-source optimizer has
native dihedral constraints and custom equality/inequality constraints, so it can
express the existing fixed torsion. Its current implementation requires explicitly
selecting `order=0` for minimization; the default seeks a saddle. Internal coordinates
also need an explicit choice. Integration through an ASE calculator wrapping our
audited Psi4 evaluator is a proposed adapter, not an already tested local interface.
Pin a release and verify the callback's atom order, force sign and units before
spending new QM evaluations. Sources: [official constraints documentation](https://github.com/zadorlab/sella/wiki/Constraints),
[implementation](https://raw.githubusercontent.com/zadorlab/sella/master/sella/optimize/optimize.py),
[Hermes et al. 2022](https://doi.org/10.1021/acs.jctc.2c00395).

There is comparative evidence beyond the package authors' claims. Shajan et al.
tested open-source optimizers on 30 Baker molecules with QUICK. Sella and Berny
needed the fewest iterations; DL-FIND had lower measured wall time in their small
molecule benchmark. These were not constrained MP2 optimizations of CPDs, and
the study's convergence settings differ from ours. It supports testing another
algorithm, not predicting a guaranteed winner or relaxing our criteria.
[Published comparison, 2023](https://doi.org/10.1021/acs.jctc.3c00188),
[public author manuscript](https://par.nsf.gov/servlets/purl/10517529).

**DL-FIND — credible alternative with a direct gradient callback.** This mature
open-source library supports constrained internal-coordinate optimization,
including torsions, with several optimization algorithms. `libdlfind` provides
Python/C access to energy/gradient callbacks. We could retain Psi4 MP2 and replace
the optimizer. Wrapper compilation, constraint encoding and independent stopping
checks still need verification. It is not necessary to adopt a new force field.
[Kästner et al. 2009](https://doi.org/10.1021/jp9028968),
[official constraint documentation](https://www.chemshell.org/wp-content/static_files/tcl-chemshell/manual/dlfind.html),
[Python wrapper](https://github.com/digital-chemistry-laboratory/libdlfind).

Both options should use the same graph, stereochemistry, QM settings and exact
Cartesian tangent-gradient audit as the existing calculation. An optimizer's
success flag establishes neither independent stationarity nor positive curvature.
Count all new gradient calls, including optional finite-difference/Hessian work,
against the chosen budget.

## Alternative electronic engines and conventional fitting

**ORCA plus ffTK — strongest conventional CHARMM alternative.** ORCA is free for
academic/personal use but is not open source. Its documented capabilities include
MP2/RI-MP2 analytic gradients and explicit dihedral constraints. ffTK develops
CHARMM-compatible charges and bonded parameters, and its version-2 update
explicitly adds ORCA support. The same webpage retains an older Gaussian-only
paragraph; the update notice is the relevant newer statement. Sources:
[ORCA availability](https://www.faccts.de/orca/),
[MP2 methods](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/MP2.html),
[geometry constraints](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html),
[ffTK documentation](https://www.ks.uiuc.edu/Research/vmd/plugins/fftk/),
[original ffTK paper](https://doi.org/10.1002/jcc.23422).

For this campaign, use only the missing bonded/torsional work; retain accepted
charges and parent DNA/LJ terms. Before combining target data, match frozen-core,
basis, density-fitting/auxiliary-basis and electronic-convergence conventions and
check the two engines on identical coordinates. No mixing of unrelated absolute
energy zeros. An ORCA run also needs independent stationarity checks. This route
has a real integration and data-consistency cost; it is not a free retry button.

**NWChem and PySCF — viable open-source QM replacements, lower immediate priority.**
Both expose MP2 gradients. NWChem supplies its own DRIVER/STEPPER optimization
machinery. PySCF commonly delegates geometry optimization to geomeTRIC or PyBerny;
choosing geomeTRIC would reuse the optimizer implicated in the present failure.
Changing the electronic engine alone therefore need not resolve it.
[NWChem MP2](https://nwchemgit.github.io/MP2.html),
[NWChem optimization](https://nwchemgit.github.io/Geometry-Optimization.html),
[PySCF MP2 gradient implementation](https://pyscf.org/_modules/pyscf/grad/mp2.html),
[PySCF quickstart](https://pyscf.org/quickstart.html).

## Fit the potential using forces as well as energies

**ForceBalance — most promising change of fitting method.** Its published
framework fits parameters to weighted data with regularization. The documented
ab-initio targets compare energies and forces at supplied configurations; those
configurations need not all be stationary. OpenMM is one supported evaluation
engine. This offers a principled use for verified optimization snapshots and
deliberately displaced structures, reducing dependence on completing every relaxed
scan point. Sources: [Wang, Martínez and Pande 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC9649520/),
[manual, section 3.3.1](https://leeping.github.io/forcebalance/doc/ForceBalance-Manual.pdf),
[repository](https://github.com/leeping/forcebalance).

Application to this CPD is a proposal, not a published CPD validation:

- Retain the successful charges, LJ and unaffected DNA parameters. Expose a small,
  explicitly named lesion torsion set first.
- Use physical Cartesian QM gradients, not gradients projected to remove the
  scan constraint. Verify units/sign: the manual's `FORCES` input label actually
  expects gradients in hartree/bohr.
- Fit relative energies using the same registered reference and consistent atom
  maps. Specify force components/weights before fitting; do not select favorable
  components after seeing the residuals.
- Treat the existing trajectory as exposed, correlated development data. It is
  not broad coverage or a blind validation set. Preserve known competing basins
  and register candidate hashes before acquiring prospective checks.
- Audit CHARMM energy/force fidelity through the adapter and export, including
  Urey–Bradley terms, harmonic impropers, exclusions and 1–4 interactions. Support
  for OpenMM does not establish a ready-made CHARMM parameter-file fitting path.

There is also a useful mathematical simplification. At fixed coordinates and
fixed torsion periodicities/phases,

`E(x;k) = E_fixed(x) + sum_j k_j [1 + cos(n_j phi_j(x) - delta_j)]`.

Both energies and their Cartesian gradients are linear in the amplitudes `k_j`.
With fixed weights, quadratic regularization and box bounds, fitting those
amplitudes is a convex quadratic problem. This is our derivation for a restricted
fit, not a claim about ForceBalance's default solver. A bounded least-squares
feasibility analysis can report rank, conditioning and the minimum attainable
weighted residual for that basis. If even the best feasible unregularized residual
misses the registered target, additional iterations of the same fit cannot fix it.
That conclusion applies only to the chosen data, weights, bounds and parameter
basis; relaxed structures and barrier validation remain separate nonlinear tests.

This directly addresses the moving-goalpost concern: distinguish an optimizer
failure from insufficient data or an inadequate parameter basis before buying
another batch of QM. The current v2 conformational stage still requires its
unresolved +15° reference. A force-matching branch therefore needs a versioned
prospective protocol; this review does not bypass that guard or overwrite its
failure.

**Q-Force — useful for missing stiffness and torsion fitting.** This open-source
workflow combines QM Hessian and torsion targets with transferable nonbonded
parameters. The paper discusses CHARMM compatibility, and the documentation allows
CHARMM36/external LJ data and external charges. It could address force constants
that our equilibrium-geometry fitting did not calibrate. Its output/conversion
path and defaults need auditing: documented defaults include OPLS, charge scaling
of 1.2 and a different multilevel QM recipe. Keep the accepted charge convention;
do not inherit those defaults or silently accept missing scan points. A local
Hessian alone cannot fix the full basin landscape.
[Sami et al. 2021](https://doi.org/10.1021/acs.jctc.1c00195),
[options](https://qforce.readthedocs.io/en/latest/options.html),
[source](https://github.com/selimsami/qforce).

## Other public automation: useful, but not first choices here

| Tool | What exists | Reason to place it behind the shortlist |
|---|---|---|
| OpenFF BespokeFit | Open-source automation of bespoke torsion parameterization using TorsionDrive and ForceBalance. [2022 paper](https://doi.org/10.1021/acs.jcim.2c01153), [source](https://github.com/openforcefield/openff-bespokefit). | Uses the OpenFF/SMIRNOFF parent model, and its standard acquisition uses geomeTRIC. Neither a direct CHARMM replacement nor an independent optimizer escape. Any fragmentation must preserve the CPD ring and relevant attachments. |
| QUBEKit | Open-source automated density-derived nonbonded and Hessian/torsion parameterization, with customizable stages. [Source and cited publications](https://github.com/qubekit/QUBEKit). | The complete default workflow changes the nonbonded model. More appropriate for a separately defined force-field branch; selective Hessian fitting is more relevant than restarting all stages. |
| ParaMol | Published energy/force fitting through OpenMM, bonded linear least squares and CHARMM parameter symmetrization. [2021 paper](https://doi.org/10.1021/acs.jcim.0c01444), [source](https://github.com/JMorado/ParaMol). | The repository explicitly says active development has stopped. Valuable algorithmic precedent, less attractive as a new maintained dependency. |
| Pysisyphus | Open-source geometry/constraint algorithms and interfaces to multiple QM engines. [Source](https://github.com/eljost/pysisyphus). | The author explicitly describes it as unmaintained since November 2024. Its capabilities do not remove the support risk. |
| AFFDO | A 2026 paper describes automated GAFF2 torsion fitting using QUICK/DL-FIND, with a free web service for molecules up to 90 atoms. [Public author paper](https://theory.rutgers.edu/resources/pdfs/automated-force-field-developer-and-optimizer-platform-torsion-reparameterization.pdf), [DOI](https://doi.org/10.1021/acs.jcim.6c00528). | Concrete evidence that integrated automation exists, but it targets AMBER/GAFF2. The paper's service offer is not verification of present access or an open-source license. No structures were submitted. |

A targeted literature search did not identify a verified, ready-made additive
CHARMM parameter set for this exact cis-anti interstrand CPD. Some superficially
similar cis-anti results concern other DNA adducts. This is a search result, not
proof that no such parameters exist.

## Finite decision and acceptance boundaries

1. **First assess reuse, without new QM.** Inventory the verified cached energies,
   raw gradients, geometries and Hessians against the fixed atom maps and known
   basins. Prepare a parameter/target manifest for a restricted force fit. Report
   coverage gaps explicitly. Do not start fitting under the old scan-completion
   policy or label exposed data blind.
2. **Choose one bounded method test.** A Sella/Psi4 stationary-point pilot and a
   ForceBalance-style force-fit pilot answer different questions. Select the
   question, freeze the inputs, success metrics, evaluation/wall budgets and
   zero-continuation rule before launching it. The outstanding 15-gradient
   corrected-geomeTRIC proposal is a separate option, not approval for either.
3. **Keep qualification tests finite.** Preserve the successful water stage,
   0.03 Å/3° geometry targets at registered representative minima and the
   1 kcal/mol RMSE / 2 kcal/mol maximum relevant-energy targets. A force-fitting
   objective needs its own declared weights and stopping condition; there is no
   universal published force-error certificate to import. Do not add a new
   Hessian requirement at every training configuration or require proof of a
   global minimum.
4. **Verify export and context separately.** Recheck the changed candidate in
   native NAMD, then require independently acceptable full-DNA starting geometry
   before context dynamics. The existing 100 ps fragment smoke remains an
   engineering pass with limited scope. Full-DNA construction is still unresolved.
5. **Stop at the declared cap or a demonstrated basis limitation.** Report whether
   the failure is acquisition, fitting, representation or construction. Do not
   automatically iterate through every package in this review, extend budgets,
   remove hard targets or change the chemical model.

The literature establishes practical algorithms and validation conventions; it
does not guarantee that this CPD will meet every selected CHARMM target. Published
CHARMM geometry conventions and our locally chosen energy/water limits remain
distinguished in the [earlier primary-literature review](cpd_cis_anti_workflow_review_20260925.md).
The most useful improvement is a finite, interpretable fitting problem with a
clear failure diagnosis, followed by the already defined preliminary scope.
