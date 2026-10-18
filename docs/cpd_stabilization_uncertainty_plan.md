# CPD stabilization range: prospective study plan

## Current priority — 2026-10-17

The [bounded parameter sensitivity plan](cpd_bounded_parameter_sensitivity_plan.md)
supersedes the next-compute recommendations below. Test whether plausible local
parameter variation affects NAMD stability or local DNA behavior before investing
in further QM refinement. This is a planned isolated qualification campaign, not
a launched melting study. Keep the sampling/parameter/occupancy distinctions below;
system-specific melting and occupancy studies remain user-owned.

## User scope clarification —2026-10-16

The user will manage melting simulations in specific systems. This campaign now
focuses on CPD pre-simulation correctness: canonical chemical identity, export/
restart engineering and tractable parameter/reference discrepancies. When further
refinement primarily requires system-specific MD, provide a qualified handoff and
explicit parameter limitations rather than withholding readiness for an agent-run
melting/occupancy campaign. Sampling and occupancy analysis below are guidance for
the user-owned studies, not authorization or a prerequisite to run them here.
The active calculation is a two-conformer frozen-geometry QM basis-sensitivity
check. Archived bad-sugar DNA input remains excluded; canonical fragment references
are retained. No automatic production geometry replacement.

Authorized 2026-10-16: resume toward a robust stabilization range with separate
sampling, parameter and weld-occupancy uncertainties. No cloud; Archive-first
storage; one native job at a time, restartable segments below16h, evidence audits
and completion/failure/deadline triggers rather than periodic polling.

## Immediate chemical prerequisite

The independent2026-10-16 sugar audit found that the archived formation-context
weld sites disagree with the PDB CCD DT reference: C3′ at both endpoints and C4′
at endpoint2. Both ideal and experimental-model CCD coordinates agree with the
QM endpoint1 reference. The discrepancies predate MD and occur in both welded and
control seeds. Earlier dynamic checks preserved seed signs, but did not establish
canonical DNA sugar identity. Retain all40ns validation trajectories as engineering
history; exclude them from canonical-DNA stabilization claims. The sample-based
fragment mapping and attachment relevance conclusions require reevaluation in a
correct context. No new QM or MD was launched from the failed preflights.

Source-wide audit: all98DNA residues screened;6 C3′ and2 C4′ mismatches also
exist in the source package PDB and equilibrated checkpoint. Next work: trace
the upstream preparation origin; verify atom names/connectivity independently.
Prepare an isolated corrected context and an atom-level A/B review with per-center
signed volumes, chirality, bonds and contact changes. Follow the repository molecular
geometry authorization gate before integrating a changed geometry into normal app
paths. No registry/golden changes or silent replacement of historical geometry.
Require canonical sugar identity and CPD identity independently, then restart
bounded preparation/validation. No need to repeat the certified CPD-core QM solely
because the DNA context failed; its exact source and scope remain separate.

## Observable and interpretation

Working default pending user preference: temperature-dependent structural retention
for matched welded/unwelded constructs. Define intact domains using prospective
base-pair geometry and strand connectivity, not RMSD or the exploratory8Å centroid
contact proxy. Record the heating/hold protocol, observation time, salt, concentration,
sequence and weld-site identity. A finite-time retention or survival curve is not
an equilibrium melting curve. Estimate equilibrium delta-T50 only if reversible
sampling and state populations support that interpretation. Never infer melting
from an absence of unbinding in a short trajectory.

## Separate uncertainty axes

1. Sampling: independent velocities and, where feasible, independently equilibrated
   starting configurations; temperature and state-transition coverage; correlation
   times, effective sample sizes and replica/block uncertainty. Frames are not
   independent replicates. Adapt sampling only when it can reduce uncertainty in
   the selected observable; distinguish kinetic trapping from equilibrium.
2. Parameters: use QM/MM checks at chemically valid DNA-relevant geometries and
   analog water/electrostatic targets to construct a small defensible candidate set.
   Hold out geometries before fitting; preserve standard sugar parameters unless
   independent evidence justifies changing them. Benchmark low-cost methods before
   large scans. Report the envelope across acceptable candidates separately from
   within-candidate sampling intervals. Do not tune parameters to cancel one7.15616
   kcal/mol fragment energy mismatch or call a model envelope a95% confidence band.
3. Weld occupancy: predict conditional outcomes for specified sites/counts, including
   zero welds. Account for layout and correlated formation, not just weld fraction.
   With no measured occupancy distribution, report scenario bounds; do not assume
   independent Bernoulli welds or a uniform prior as experimental facts. Combine
   scenarios only under an explicit distribution; measured bulk curves alone must
   not simultaneously determine force-field parameters and weld yield.

For a retention observable at fixedT/time, an occupancy mixture can be written
R(T,t)=sum_w p(w)R(T,t|w). Propagate sampling within each conditional prediction,
parameter variation across models, and occupancy assumptions across distributions.
If a T50 is meaningful, solve it from each resulting curve; do not average scenario
T50 values. Preserve interactions among uncertainties instead of adding their
ranges or variances without justification.

## Staged compute decisions

- First: resolve the stereochemical input discrepancy without further production MD.
- Then: a two-geometry native QM/MM pilot, capped30minutes, only after geometry,
  cap/contact and source-method checks pass. Audit raw energy/gradient evidence;
  stop if caps or thermal strain dominate rather than expanding an angular grid.
- Next: register parameter alternatives and withheld checks before fitting; qualify
  engine equivalence without claiming scientific validation from execution alone.
- Next: one small matched temperature/sampling pilot in the corrected context;
  establish costs, transitions and useful observables before a temperature grid.
- Add replicas, parameter alternatives and occupancy layouts according to the
  uncertainty currently limiting the intended conclusion. Numerical stopping
  tolerances must be declared with the intended experimental comparison before
  interpreting the final range; there is no universal literature certificate.

Deliverables: conditional curves, sampling intervals, parameter envelope,
occupancy-scenario envelope, convergence diagnostics and explicit claim scope.
If transitions are insufficient, deliver finite-time retention bounds or state that
an equilibrium stabilization estimate is unresolved, rather than a false delta-Tm.
