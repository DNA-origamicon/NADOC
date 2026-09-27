# Four prospective cis-anti QM targets

The delayed solvent-construction v1 failure wake
`8f08635d-0b1f-44e7-a5ee-58f2101a614e` was acknowledged at
2026-09-26 22:33:02 UTC. Its two native logs reject `set nat ?NATC` in the
CHARMM water/ion stream before any energy, minimization or MD. Input hashes,
zero-step reports and absence of trajectories were verified; the failure remains.
The later [full-system NAMD engineering pass](cpd_anti_full_dna_engine_20260926.md)
is independent of that delayed notification and was not rerun.

## Registration before acquisition

The original preliminary v2 policy prescribes four prospective ±22.5° QM points.
The completed first-round fit had not yet registered its candidate for them.
That handoff is now explicit in `cpd-anti-prospective-qm-v2-r1`: the first-round
CHARMM parameter file, endpoint fixtures, all common reference identities/energies,
worker, runtime and four starting geometries are frozen before any new QM.
`cpd-anti-preliminary-v2/conformational_candidate_lock.json` blocks further fitting;
its blocking behavior was verified. One fit round remains used, with no second
round consumed. Existing stage input locks and the v2 policy are unchanged.

| Target | Frozen QM reference | Target O4′–C1′–N1–C2 angle |
|---|---|---:|
| Endpoint 1 −22.5° | `endpoint-1-reference` | −97.6159559234° |
| Endpoint 1 +22.5° | `endpoint-1-reference` | −52.6159559234° |
| Endpoint 2 −22.5° | `endpoint-2-reference-lower-mm-basin` | 61.9659437284° |
| Endpoint 2 +22.5° | `endpoint-2-reference-lower-mm-basin` | 106.9659437284° |

Each 49-atom seed rotates only the graph-defined 17-atom sugar component around
the existing N1–C1′ bond. All other coordinates are identical to the named QM
reference. Graph, charge, ordered anti crosslinks, reference stereochemistry and
covalent geometry pass preflight. Sella's signed angle and constraint normal agree
with independent Cartesian calculations. Every new target lies 7.5° from its
nearest exposed inventory angle; none of the 19 old points is relabeled prospective.
No new QM was evaluated during registration/preflight.

## Bounded local Sella acquisition

`cpd-anti-prospective-qm-service-v2-r1` runs one sequential batch with an external
completion watcher. Its four cases use the successful pilot's Sella `order=0`,
internal coordinates, `eig=False`, and unchanged Psi4 DF-MP2/6-31G(d), RHF,
frozen-core settings: E/D convergence10⁻¹², response10⁻¹⁰. No Hessian or optimizer
state is reused. Each case is a fresh optimization from its registered seed.

- At most 40 new gradients per case, 160 total; no continuations or extra seeds.
- At most 6 hours per case and 12 hours for the batch. An unstarted/timed-out case
  remains incomplete, with all partial outputs retained.
- Four local CPU threads, 6 GiB Psi4 memory, 10 GiB service limit; no cloud.
- Joint Sella convergence and independently projected maximum/RMS atomic gradients
  below1.5×10⁻⁵/10⁻⁵ au, and torsion error below0.01°. Chemistry is checked on
  every proposed/evaluated geometry. Final projection is repeated at three
  finite-difference spacings.

These are prospective execution caps using the existing numerical criteria;
they do not certify that a target will converge. Successful completion establishes
constrained stationarity, not a positive-curvature, unconstrained or global minimum.
Native electronic response, exact coordinate/gradient correspondence and optimizer
evidence must all be reviewed after termination.

## Fixed follow-on scoring

The registered plan allows one MM relaxation of the locked candidate from each
acquired QM geometry, under the existing 400-step/600-evaluation,0.001kcal/mol/Å
projected-force and0.01° limits. Use the same reference conformer identity in
both methods, with the already frozen QM/MM reference energies. Do not separately
re-zero to newly discovered minima or omit failed targets. Score the four energy
residuals against the original1kcal/mol RMS and2kcal/mol maximum criteria and
report shape/branch correspondence. This acquisition job does not run that MM
scoring or fit any parameters.

All seven exposed profile-geometry mismatches remain visible. Prospective target
completion alone cannot pass scientific qualification, product placement or
minimum certification. The NAMD engineering bundle remains usable within its
documented isolated scope while this independent validation stage runs.
