# Cis-anti shape correction: second and final v2 fit round

This versioned execution contract follows the user's instruction to continue to
scientific quality and the [recorded residual review](cpd_anti_shape_correction_review_20260927.md).
The first candidate remains locked and failed for shape correspondence. All 23
inspected QM structures are now explicitly exposed development/regression data.
Numerical acceptance limits and the original two-round campaign budget are unchanged.

**Final execution verdict:** authorized recovery ended at the original
04:29:42UTC deadline, with69 complete models. Selected model61 passes energy and
representative checks but fails three profile RMSDs. The
[native closeout](cpd_anti_shape_fit_closeout_20260927.md) preserves all failures.
No optimizer convergence, minimum certificate, scientific qualification or
automatic further continuation; both fitting rounds and wall time are exhausted.

**Execution stopped at02:41:50UTC by the6GiB cgroup memory limit.** The native
[termination audit and prepared recovery](cpd_anti_shape_fit_oom_recovery_20260927.md)
preserve33 complete models and the partial34th. Best completed trial32 has six
shape failures and remains unqualified. The user explicitly authorized recovery
with “Resume with the interrupted round.” It launched at04:16:06UTC in
`cpd-anti-shape-fit-recovery-service-v1`, with fresh child processes per model,
saved-work reuse and all original limits, including absolute04:29:42UTC fitting
deadline. No budget was extended; no automatic further recovery is authorized.

The registered fit launched at **2026-09-27 02:29:42 UTC** in
`cpd-anti-shape-fit-service-v2-r2` (CPUs4–7, 6GiB). Its separate completion watcher
delivered the stopped-supervisor event, now acknowledged. Round two is reserved;
it cannot be automatically rerun or replaced by a third round.
The initial model independently passes numerical checks on all26 structures,
879 saved MM evaluations, and final exported energy/force replays. It reproduces
the same eight shape failures and energy RMS0.608393/max1.621983 over all23
exposed points. No improved model has been qualified at this initial checkpoint.
Receipt: the service's `initial_model_independent_review.json`.

## Model and objective frozen before fitting

`cpd-anti-shape-inputs-v2-r2/receipt.json` pins all inputs, executable sources,
runtime versions, exact atom-type keys, multiplicities, coefficients and budgets.
The twelve original attachment coefficients remain adjustable. Six additional
proper families contribute ten coefficients:

| Proper, for each ordered endpoint e | Multiplicities |
|---|---|
| C2(e)–N1(e)–C6(e)–C5(other) | 3, 6 |
| N3(e)–C2(e)–N1(e)–C6(e) | 2, 4 |
| N1(e)–C2(e)–N3(e)–C4(e) | 2 |

These existing ring coordinates participate in the diagnosed N1/base-ring
distortions, in both capped and sugar-bearing fragments. Their exact type keys
and every topology occurrence are checked. There are **22 coefficients total**.
Changes remain within ±5 kcal/mol relative to the original v2g baseline, including
the first round's changes. Starting from the first candidate does not reset these
bounds. Phases remain 0/180°. Charges, LJ, bonds, angles, impropers, nonselected
proper terms and parent DNA parameters remain fixed.

Each parameter-vector evaluation starts 23 profile/validation fragments and three
representative fragments from their fixed QM coordinates. Sella uses order=0,
internal coordinates, eig=False and independent force/chemistry checks. Scan angles
stay fixed at their measured QM values; the remote free case and three
representatives remain unconstrained. Existing per-fragment caps are 400 steps,
600 evaluations and projected maximum force below 0.001 kcal/mol/Å.

The least-squares residual includes five equally weighted mean-square blocks:
relative-energy errors / 1 kcal/mol; aligned heavy-coordinate RMSD / 0.25 Å;
maximum heavy proper errors / 20°; representative maximum lesion/attachment bond
errors / 0.03 Å; representative maximum lesion/attachment angle errors / 3°.
Add 0.05 times the mean squared total coefficient shift / 3 kcal/mol. Every
numerically failed fragment contributes a residual of 1000 and remains in the
record; it cannot be removed to improve the score. QM and MM use the same fixed
reference conformer identities. The objective weights are explicit local choices.

Parameter fitting uses SciPy's bounded trust-region reflective least-squares
method with a fixed 0.02 kcal/mol finite-difference step for its Jacobian. This
outer parameter solver is distinct from Sella's inner molecular optimization.
An explicit total-model cap counts Jacobian probes, since SciPy's `max_nfev`
does not count those probes. See the [SciPy primary documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html).

## Finite budget and stopping

- One remaining fit round, carrying forward the consumed first round.
- Two hours of fitting wall time; service hard limit 2.25 hours for finalization.
- At most 360 evaluated parameter vectors, including derivative probes, and
  `max_nfev=12` for the outer solver. No automatic restart or continuation.
- Stop at the first evaluated candidate passing every development gate, or at
  solver/budget termination. Otherwise retain the lowest-objective numerically
  valid evaluated candidate with its failures. Do not claim a global optimum.
- All 23 cases must pass stationarity/chemistry and the original shape limits;
  their relative energies must pass RMS ≤1 / maximum ≤2 kcal/mol. All three
  representatives must pass the original lesion/attachment geometry limits.

Passing this fit still does not confer prospective validation, minimum
certification, engine validity for changed parameters, or scientific release.

## Exposure, lineage and independent validation

The original state and candidate lock remain byte-identical. Its new exclusive
`conformational_successor.json` identifies exactly one successor state,
`cpd-anti-shape-state-v2-r2`. That state's guard verifies the parent candidate,
closeout, original one-round ledger and full 23-case exposure list. It uses the
unchanged preliminary protocol's input-lock and round-reservation functions with
the registered successor state. Its ledger starts with the original record and
can append only round two. A third round, alternate successor, reset ledger,
changed inputs or paused campaign is rejected. Old fitting entry points remain
blocked by the original candidate lock.

The prospective plan specifies four ±18.75° offsets from the same endpoint-1 and
lower endpoint-2 references, with unchanged acquisition/acceptance limits. Before
acquisition, audit historical evaluated-angle identities for overlap. Any overlap
requires stopping for a versioned plan change, not substituting a convenient
target. Register the revised candidate before any new target acquisition.
The observed ±22.5° structures will not be called blind data again.

Six focused guard tests passed in 1.07 seconds. Native preflight verifies three
parameter vectors—exported initial, original first candidate, and a fixed ±0.1
kcal/mol diagnostic perturbation—across five fragment topologies. Independent
cosine additions reproduce exported energies/forces within the original
1e−5 kcal/mol / 1e−4 kcal/mol/Å limits, including CHARMM constant offsets and
every typed occurrence. This preflight involved no optimization or parameter fit.

No context trajectories, application geometry promotion, cloud spending or
change to the declared preliminary structural scope is authorized by this result.
