# Corrected cis-anti-I: bounded parameter sensitivity plan

Prepared 2026-10-17. Status: planning only; no calculation launched by this document.

## Decision and scope

Determine whether the unresolved local sugar/exocyclic energy discrepancy has a
practically important effect on NAMD stability or local DNA behavior. Prioritize
this decision over further open-ended QM refinement. A successful outcome is a
scope-qualified provisional parameter set, with a measured sensitivity envelope;
it need not reproduce every reference energy exactly.

The user owns system-specific melting studies. This plan covers small isolated
qualification fixtures, not origami melting, weld yield, or experimental validation.
Sampling error, variation across parameter models, and weld occupancy must remain
separate. Occupancy is fixed here; no occupancy distribution is inferred.

## Evidence to retain

- Read `cpd_anti_additive_campaign.md`,
  `audits/cpd_ring_exocyclic_panel_closeout_20261017.json`, and the archive's
  `current_handoff.json` before implementation. Recheck state for intervening work.
- Corrected cis-anti-I connectivity is C5(1)-C6(2), C6(1)-C5(2). Independently
  verify stereochemistry and atom mapping against the audited source manifest.
- The approximately 8 kcal/mol discrepancy is a QM-MM contrast on selected
  endpoint geometries, not a calibrated parameter confidence interval. The
  six-point panel confounds background conformation, exocyclic geometry and
  contacts/caps. Do not convert it mechanically to a +/-8 kcal/mol correction.
- The previously fitted exocyclic correction failed holdouts. It is not an
  acceptable validated alternative. Earlier DNA trajectories with noncanonical
  sugar stereochemistry are excluded from readiness evidence.
- Independent solvent calculations addressed a numerical reference-method issue;
  they did not resolve the neutral endpoint discrepancy. Optimization completion
  is not minimum certification. Preserve all failed calculations and fits.

## Stage 0 — register a finite experiment before MD

Inventory the exact baseline topology/parameter exports and usable canonical
fixtures; pin hashes, versions, atom mappings and intended run settings. Read
`../CLAUDE.md` and the geometry authorization policy. Keep candidates isolated;
production geometry promotion requires the specified concrete review and approval.

Create a machine-readable manifest with primary observables, physical tolerances,
parameter variants, fixture chemistry, starts/seeds, gates, analysis windows,
runtime estimates and a total budget. Numeric tolerances must be justified by the
local engineering question and baseline measurement resolution before comparing
variant trajectories. They are engineering decisions, not universal literature
standards. If no application-specific tolerance is defensible, report effect sizes
and precision without declaring practical equivalence.

Use baseline plus at most two initial stress-test variants, favoring opposite
local conformational preferences. Specify every changed term, units, phase,
amplitude and affected atoms. Derive a defensible range from existing references,
holdouts and physically acceptable forces/curvatures; do not invent statistical
coverage. Freeze validated core bonding, charges, nonbonded terms and unrelated
canonical DNA parameters. Avoid changing global atom types that affect other sites.
If the missing physics cannot be represented with a defensible local variation,
state that limitation and stop variant construction rather than force a fit.

A smooth imposed bias can be used as an explicitly artificial sensitivity probe
if necessary, but cannot qualify an exportable parameter family by itself. A
torsional preference probe does not bound uncertainty in all possible force-field
terms. Record this coverage limitation.

Fixtures: small canonical DNA environments covering internal/internal,
internal/terminal and terminal/terminal weld chemistry where relevant. Specify
free OH versus phosphate chemistry explicitly. Start with one representative
fixture for admission; cover remaining relevant chemistries before broad claims.
Use both relevant local conformations after independent geometry checks.
An unwelded control is optional context, not a substitute for comparing variants.

## Stage 1 — static and native-engine admission

For baseline and each variant on identical coordinates:

1. Verify connectivity, sugar and CPD stereochemistry, charge, parameter coverage,
   contacts, and canonical backbone identity. Preserve before/after structures.
2. Compare relative energies, maximum/local forces, and accessible local curvature
   on endpoints, holdouts and modest local displacements. Keep holdouts separate
   from any variant tuning. Identify new wells, singularities or excessive forces.
3. Confirm NAMD actually loads the intended terms. Cross-check representative
   energy differences/forces against the construction engine with compatible
   settings. Smooth energy offsets alone are not an instability test.
4. Minimize and stage thermalization; test checkpoint/restart continuity. After
   equilibration, use a short NVE segment and a smaller-timestep reference to
   distinguish integration error from parameter effects. Thermostatted energy
   stability alone is insufficient evidence of good integration.

Reject invalid variants without deleting their evidence. Do not soften unrelated
repulsion or change timestep only for one variant to disguise instability. Record
constraint failures, energy drift, maximum forces, temperature, bond distortions
and stereochemical changes. Passing means tested numerical qualification, not a
guarantee that arbitrary future systems will never fail.

## Stage 2 — local behavioral sensitivity

Use matched solvent, ions, boundaries, temperature, timestep and restraints across
models. Qualification restraints must be released for observables they influence.
Initially use two independently seeded replicas per starting conformation and
model on the pilot fixture: three models x two starts x two seeds = 12 trajectories.
This is a feasibility panel, not an automatic adequacy claim. Evaluate jobs one at
a time. Select segment length from measured throughput and correlation times.

Primary readouts: weld attachment distance/orientation distributions, sugar pucker
and glycosidic/exocyclic populations, local backbone strain and nearby base-pair
retention. Specify exact atom selections, definitions and tolerances in Stage 0.
RMSD alone is inadequate. Report both common-coordinate force differences and
sampled structural changes. A covalent weld remaining bonded in a fixed topology
model does not demonstrate realistic stiffness or population accuracy.

Analyze replica-level contrasts and autocorrelation-aware uncertainty, using
block/replica resampling rather than treating frames as independent observations.
Compare variant differences with baseline replica variation and prespecified
tolerances. Practical equivalence requires confidence intervals wholly inside
those tolerances for the primary endpoints. No significant difference is not
equivalence. Report secondary endpoints descriptively and account for multiple
primary decisions in the registered analysis.

Inspect dependence on starting conformation. If basins do not interconvert, report
conditional within-basin effects separately; do not pool arbitrary seed counts to
infer equilibrium populations. Lack of overlap or persistent start dependence is
an inconclusive result, not evidence that refinement is unnecessary.

## Bounds and stopping rules

- One native job at a time; no cloud. Each restartable process/chunk must be below
  16 hours. First pilot service cap: at most 2 hours. Before launching the panel,
  register a wall-time/job-count budget using that pilot; a conservative initial
  ceiling is 48 aggregate native-job hours including preparation and pilot work.
  This ceiling is a scheduling choice, not evidence of adequate sampling.
- Audit after completed chunks. Use completion/failure/deadline triggers, not
  intermittent polling. Verify no duplicate jobs before launch. Resource admission
  must respect the existing workstation limits and current competing workloads.
- Broaden to other fixture chemistries only after the pilot is informative and
  within the registered budget. Do not silently multiply the full matrix.
- Allow at most one explicitly justified extension for insufficient sampling
  within the registered ceiling. If still inconclusive, close with a specific
  sampling/coverage limitation and a proposed discriminating experiment.
- Instability: diagnose setup/integration versus the changed terms; retain failure.
  Do not repeat an identical failed method or enter an indefinite retry loop.
- Stable and practically equivalent: freeze the tested provisional model, document
  the tested domain and stop QM refinement for that scope.
- Stable but materially different: identify the sensitive observable/configuration;
  target refinement there, using independent solver evidence when QM is needed.
- Insufficient sampling or indefensible parameter range: report inconclusive;
  neither certify nor reflexively resume broad QM scans.

## Storage and deliverables

Create all bulk data and scratch from the first byte under the mounted Archive:
`/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/cpd-cis-anti-i-bounded-sensitivity-v1/`.
Verify mount/resolved filesystem and free space first; no fallback to primary disk.
Do not modify user designs, delete historical evidence, or promote production
geometry/parameters. Keep new code and compact manifests/audits in the repository.

Deliver the registered manifest, pinned baseline/variants, fixture audits, native
logs/checkpoints, per-model stability table, effect sizes with sampling intervals,
conditional parameter envelope, budget usage, and a short readiness decision.
Update campaign handoff/help state when implementation begins and at closeout.
The final qualification must name chemistry, temperature, run settings, observables,
parameter range and sampling limits. It is not a melting-temperature prediction,
an occupancy model, experimental validation, or certification of a QM minimum.

Fresh-session launch prompt: `cpd_bounded_sensitivity_session_prompt.txt`.
