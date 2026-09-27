# Cis-anti preliminary protocol v2

Activated for the user's instruction to resume toward NAMD-testable cis-anti CPDs.
The [review](cpd_cis_anti_workflow_review_20260925.md) supplies the rationale and
primary references; [machine policy](../experiments/cpd_anti_additive/preliminary_policy_v2.json)
fixes stage membership, objective conventions, limits and budgets before native work.

V1 and its failed/incomplete results remain archived. Existing scripts calling
`require_fit_ready()` without a stage still enforce v1. New fitting entry points
call `require_fit_ready(stage=...)`, check the active v2 policy and an immutable
stage input lock, and reserve one of the two permitted fitting rounds. Changes
to target hashes, policy, candidate registration or pause state block fitting.
There is no override flag and no blanket authorization to rerun historical scripts.

The stages can progress independently where their inputs are independent:

- **Optimizer method test:** one case, the unresolved lower-basin endpoint-2 +15°
  point, using the same MP2 targets and stationarity limits. Cached-step analysis
  supports testing default `conmethod=0` with exact enforcement and initial/max
  trust 0.002/0.02 Å. Maximum 40 new gradients, six hours, no continuation.
  Expected two hours; the external watcher reports completion/failure and one
  overdue event. Success requires native convergence and independent force,
  constraint, graph, hash and stereochemistry checks.
- **Electrostatics:** all 17 existing clean curves and all three HF dipoles are
  development data. Fix sugar/cap and aliphatic-H charges, fit remaining ordered
  base charges within ±0.15e with exact charge conservation. Fit actual minimum
  energies/distances and dipole vectors. Preserve the 0.5 kcal/mol / 0.2 Å maximum
  water limits; report ESP without fitting it. Two rounds maximum, one hour each;
  a second round needs a recorded residual-based decision. This stage does not
  depend on completing a torsion scan.
- **Conformational fit:** retain all 15 historical profile records and the four
  lower-basin records, including unresolved +15°. Freeze exact sources, branch
  correspondence and common reference identities before fitting changed torsions.
  No unresolved point becomes a high-energy exclusion. Registration precedes
  four prospective ±22.5° targets. Energy criteria remain 1 kcal/mol RMSE and
  2 kcal/mol maximum within the declared relevant set; two fit rounds maximum.
- **Engine candidate:** an isolated, fully mapped/covered candidate may undergo
  NAMD implementation checks with failed scientific metrics explicitly attached.
  Maximum 10,000 minimization steps and 100 ps smoke, ordinary masses and ≤2 fs,
  two-hour cap. Cross-engine comparison, finite energies/forces, stereo and bond
  integrity are mandatory. Passing means NAMD-testable, not research-qualified.
- **Preliminary structural qualification:** requires parameter and engine stages
  to pass, then anti/undamaged interstrand controls, three seeds each, initially
  100 ps and then 10 ns per replica. Fix the wall budget and context checks before
  launch. No equilibrium, quantitative mechanics or photochemistry claim.

All numerical limits beyond the cited fitting conventions are local prospective
choices, not universal literature certificates. Failed/incomplete stages remain
visible. No automatic continuation, new chemical model, full scan grid, extra water
orientation campaign, Drude transition, cloud allocation or normal app promotion
follows from finishing a job. The user's current instruction authorizes the bounded
campaign and necessary diagnostic candidate work; production geometry remains a
separate demonstrated integration decision.
