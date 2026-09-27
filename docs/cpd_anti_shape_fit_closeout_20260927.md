# Second cis-anti shape fit: deadline closeout

The authorized memory-isolated recovery stopped at **2026-09-27 04:29:42 UTC**
(September26,22:29:42MDT), exactly at the original fitting deadline. Its process
returned zero after retaining the best completed trial. This is orderly budget
termination, **not outer optimizer convergence, a minimum certificate or passed
scientific qualification**. Wake `5b5de21a-1f24-4815-8a3f-36f4abb54225`, event
`complete`, was acknowledged at04:30:00.571278UTC.

The service journal reports671.7MiB peak memory and zero swap. The earlier live
cgroup snapshot records704,380,928 bytes (approximately672MiB). Process isolation
therefore held memory below the unchanged6GiB limit through this recovery. It
does not establish which allocator caused the original OOM. All earlier failures
and the original stale service status remain preserved.

## Selected result under the frozen rule

Model61 is the lowest-objective complete, numerically valid evaluated trial.
Its parameter SHA256 is
`3c029534fabc7a963958d566c8f6cef1b7d2e7db892aa8244c2444effe21d4f2`.
It is a finite-difference derivative probe, which the original selection rule
allows retaining; it is not a converged outer optimum.

| Fixed development check | Selected model61 | Verdict |
|---|---:|---|
| 23 exposed relative energies, RMS / maximum | 0.294398 / 0.915744 kcal/mol | Pass ≤1 / ≤2 |
| All26 independent force/chemistry checks | Pass | Numerical stationarity only |
| Three representative maximum bond errors | 0.02067,0.02607,0.02349 Å | Pass ≤0.03 |
| Three representative maximum angle errors | 2.1472,2.6730,2.4034° | Pass ≤3 |
| Exposed profile shape correspondence | 20/23 pass | **Fail** |
| Newly registered prospective validation | Not acquired | Incomplete |

All three remaining shape failures are endpoint1 negative-offset conformers:

| Offset | Heavy-atom RMSD, Å | Maximum heavy proper error |
|---|---:|---:|
| −15° | **0.296755** | 17.0046° |
| −30° | **0.320938** | 16.9292° |
| −22.5° (previous prospective target, now exposed) | **0.321259** | 17.0407° |

The limits remain0.25Å and20°. These are unchanged failures of RMSD; the proper
errors pass. Shape failures decreased from eight at the second-round starting
model, to six before the OOM, to three after recovery. Objective decreased from
3.503928 to2.529452. The23-case RMS is an exposed development score, not an
independent validation statistic. The first candidate's earlier prospective
energy RMS0.855945 and failed shape verdict remain unchanged historical evidence.

## Native evidence and interrupted work

The service's `completion_delivery_verified.json` replays all36 completed recovery
models (34–69), plus24 recorded fragments of model70:960 fragment records /
32,883 saved evaluations. It checks native ASE coordinates/energies/forces, final
exported OpenMM Reference E/F, constraint projections or full gradients as
appropriate, chemistry, geometry descriptors, and every complete residual vector.
The prior33-model audit and all its referenced coordinate/force/residual files
were hash-checked unchanged. Combined evidence covers1,818 distinct completed
fragment records and62,194 saved evaluations, plus37 evaluations of a fragment
whose completion record was interrupted.

Model70 has all23 profile records and its first representative record. Its
available profiles already have **nine shape failures** despite energy RMS
0.318288/max0.972636kcal/mol. Its next unconstrained representative wrote37
trajectory evaluations and final coordinates before the deadline interrupted
assessment bookkeeping. Independent static replay gives full maximum force
0.000512917kcal/mol/Å, below0.001; there is no native completion record, so it
receives no completed-case or minimum credit. The last representative was not
started. Model70 has no full objective and is ineligible for selection.

`partial_model70_force_correction.json` corrects the first audit's force descriptor
for this unrecorded representative: use the full gradient, not a torsion
projection. The numeric maximum happens to agree; no completed-case checks,
selected model or scientific verdict change. Two cached optimizer-replay helper
errors (exception-variable lifetime and list/array conversion) were preserved;
the corrected replay passes without any new potential evaluation or fitting.

`optimizer_closeout_verified.json` reconstructs all69 complete vectors and the
exact requested model70 vector. There were **three evaluated outer centers and
66 derivative probes**, not69 outer optimization steps. No convergence result
was reached. One coefficient is at its original+5kcal/mol bound: endpoint2
C2′–C1′–N1–C6,n=1. This alone does not establish model inadequacy.

## Residual diagnosis and campaign boundary

The saved-coordinate review in
`cpd-anti-shape-closeout-v2-r2/residual_geometry_review.json` localizes the three
remaining failures. Separately aligned sugar and lesion-base groups have RMSDs
0.102–0.120Å while their combined RMSDs fail. This is evidence that their relative
arrangement contributes substantially to the mismatch; it does not identify a
unique missing parameter. All three also share a3.14–3.48° error in the
N1(1)–C6(1)–C5(2) angle and approximately17° error in a capped-endpoint proper.
These are diagnostic observations, not additional or replacement gates. Ordered
N1 signed heights are shape descriptors, not new stereochemical assignments.

The [frozen execution contract](cpd_anti_shape_fit_v2_r2.md) says “No automatic
restart or continuation.” Both permitted rounds and the absolute wall window are
now exhausted. No additional fit, recovery, prospective QM acquisition, context
MD or application promotion has been launched. Further fitting needs an explicit,
versioned execution decision; these results do not justify relaxing acceptance
thresholds or calling the current model scientifically qualified.

The earlier100ps NAMD engineering milestone remains valid for its original
parameter bundle. It does not validate the changed model61 parameters. The
authoritative closeout is `cpd-anti-shape-closeout-v2-r2/assessment.json`, with
hash-linked selected parameters, native audits, authorization, ledger and failed
verdicts. No cloud spending.
