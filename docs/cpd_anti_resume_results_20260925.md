# Cis-anti campaign resume: first results

The user explicitly resumed the campaign after the literature review. The target
remains a preliminary additive model for exploratory structural simulations with
documented limitations. [Protocol v2](cpd_preliminary_protocol_v2.md) was activated
before calculations; its stage definitions, limits and round budgets are pinned
in `.development-artifacts/cpd-anti-preliminary-v2/`.

**A 62-atom cis-anti model containing both nucleosides is now NAMD-tested.** It is
an isolated engineering fixture, not yet a full interstrand DNA model or a
preliminary research qualification. No product registry or saved-design geometry
was changed.

**Latest continuation — 2026-09-26 UTC:** the first bounded torsion fit now passes
the19-case exposed relaxed-energy limits (RMS0.5421, maximum1.0099kcal/mol) and
three representative geometry limits. The updated two-nucleoside candidate
passes ten native comparisons and100ps NAMD. Full-DNA topology passes native
static comparison, but a new bounded construction failed at1000 iterations
(force1.36065kcal/mol/Å, displacement14.0515Å); no dynamics or extension.
Seven profile geometry descriptors and prospective QM validation remain
unresolved. See the [current results](cpd_anti_conformational_results_20260926.md).
All jobs are terminal; one conformational fit round remains unused.

**Earlier review — 2026-09-26 UTC:** the
[fresh Sella attempt](cpd_anti_sella_attempt_20260926.md) passed independent
constrained stationarity at19:23UTC after20 gradients/55.5minutes, using the
original force and geometry criteria. The prior geomeTRIC and source-conditioning
failures are preserved; no minimum certification or full-DNA qualification follows.
All19 declared QM cases are now inventoried for the next fitting-manifest review.
At that review, no calculation was running; the old geomeTRIC restart remains unlaunched.

## Results against the fixed criteria

| Stage | Result | Interpretation |
|---|---|---|
| Water interactions | All 17 clean curves pass: independent maximum energy error 0.41045 kcal/mol, distance error 0.12391 Å; limits 0.5 kcal/mol and 0.2 Å. | The first revised charge fit succeeds on the exposed development targets. No second fit round is needed. |
| Dipoles | Vector errors 0.441, 0.878, 0.986 D on the three conformers. | Direct HF targets were fitted; residuals are reported. No new dipole-ratio gate was introduced. Three charge shifts reach their ±0.15e bounds. |
| Representative geometry | Core, endpoint-1 and lower-energy endpoint-2: maximum angles 2.177°, 2.454°, 2.386°; bonds 0.02058, 0.02607, 0.02197 Å. | These structures retain the existing 3°/0.03 Å targets with the new charges and fixed historical bonded terms. |
| Older endpoint-2 conformer | Maximum angle discrepancy 8.684°; relaxation reaches the same minimum as the remote conformer, aligned all-atom RMSD 3.75e−7 Å. | The model does not retain this QM basin. This remains an explicit failed transfer result, not an excluded datum or reason to relax the criterion. |
| Local numerical stability | All five fixtures stationary; maximum force below 1.8e−5 kcal/mol/Å; positive internal curvature at both finite-difference step sizes; graph and stereo preserved. | Suitable for isolated implementation tests. Positive MM curvature does not validate QM stiffness. |
| Native NAMD equivalence | Ten starting/minimum comparisons across five fixtures pass. Maximum energy difference 0.000604 kcal/mol; force difference 0.000710 kcal/mol/Å. | Consistent with the predeclared native tolerances. |
| Native dynamics | Two-nucleoside model completes 100 ps in vacuum at 300 K, 1 fs, ordinary masses. All 101 saved frames plus final binary coordinates pass inspection. | Engineering smoke only. Four lesion and six sugar stereocenters match the original QM references throughout. |
| Conformational energies | Unfinished. Historical-geometry single-point diagnostic reaches 11.45 kcal/mol error on the original reference convention. | This is not a relaxed-profile score; it confirms that passing water interactions does not resolve the energy landscape. No torsion parameters were fitted. |
| Lower-basin +15° QM reference | Fresh Sella attempt passes: maximum/RMS tangent gradient 1.44345e−5/6.21290e−6 au; torsion error 1.219e−8°; 20 new gradients/55.5min. | Accepted constrained stationary reference under unchanged limits. Prior geomeTRIC failure preserved; no Hessian/minimum certification. |
| Full interstrand DNA | Topology and coverage pass: 96 nucleotides, 3 strands, 3,043 atoms. Rigid placement and local construction failed. Source conditioning resolves seven inherited bond-length defects under the construction screen but stops at 500 constrained iterations. | Maximum mobile force remains 19.7611 kcal/mol/Å; constraints were not removed. Full-DNA NAMD and context qualification remain unvalidated. |

The successful charge objective uses actual MM water minima and HF dipoles,
with fixed sugar/cap/aliphatic-H charges, fixed LJ terms, exact neutrality and
bounded base-charge changes. ESP remains a reported diagnostic. An independent
calculation reconstructing water geometries and minimizing the direct interaction
function confirms the result without using the fit's precomputed matrices.
The literature rationale and distinction between published conventions and local
acceptance limits remain in the [workflow review](cpd_cis_anti_workflow_review_20260925.md).

## What the NAMD fixture contains

There are two separate nucleoside residues, 62 atoms and 66 bonds. The only
inter-residue links are **1:C5–2:C6** and **1:C6–2:C5**. There is no artificial
phosphodiester connection between the endpoints. Each sugar comes from its
independently relaxed fragment, joined by a proper rigid alignment; the seed is
explicitly an MM assembly, not a QM structure. Heavy-base alignment RMSD was
0.06053 Å.

Native psfgen supplied the topology. Its six-decimal charge output introduced a
1e−6e net-charge rounding residual, so the raw PSF was retained and the original
12-decimal fitted assignments restored, without changing its graph. The resulting
net charge is approximately −1e−12e. The trajectory crosslinks span 1.479–1.654 Å
and 1.443–1.666 Å. All atoms retained ordinary masses.

The historical bonded overlay includes CPD-specific sugar bond/angle changes.
It must not silently become a generic DNA sugar/phosphate model. Transfer to the
full backbone is a separate, explicit parameter-coverage and geometry task.

On receipt of the charge-fit completion notice, full-DNA topology preparation
advanced independently of the running QM test. The isolated patch now maps the
frozen ordered keys to D001:15 and D000:8. It reassigns exactly 28 base atoms,
adds the two anti bonds and removes the two reactant C5 planar impropers. It
retains all native DNA sugar/phosphate types, charges and bonded terms. Total
charge is unchanged at −93e; the covalently joined lesion pair has charge −2e.
Individual lesion residue charges are fractional and must be audited as a pair
in any future package, rather than forced independently back to −1e.

An independent audit verifies 222 exact lesion/attachment coefficient transfers,
all 28 lesion mass/LJ assignments, and numerical invariance of every unaffected
parent force term and all 3,015 unaffected particles. Parameter coverage is
complete. That topology audit performed no coordinate minimization, energy
evaluation or full-DNA dynamics. Its retained source coordinates are explicitly
unsafe for dynamics.

## Placement diagnosis — 2026-09-26 UTC

The shared-frame [interactive comparison](../.development-artifacts/cpd-anti-placement-review-v2/review.html)
and [static comparison](../.development-artifacts/cpd-anti-placement-review-v2/comparison.png)
show why rigid base-only placement is rejected. Source C1′ separation is 4.07694 Å;
the independently tested anti MM fragment has 7.12611 Å. The four-anchor proper
rigid fit has RMSD 1.39512 Å, above the existing 1.2 Å limit. Holding the sugars
fixed compresses glycosidic bonds to 1.00676 and 0.97050 Å, versus template values
1.47523 and 1.47316 Å. Both errors exceed the existing 0.4 Å screen. Maximum base
displacement is 8.15923 Å, above 3.5 Å; one severe heavy-atom contact appears.
Lesion chirality and source sugar chirality are retained; no ring piercing was
detected. Correct chirality alone does not make this placement usable.

A second rigid construction using eight sugar-backbone anchors moves both whole
nucleosides. It is worse: anchor RMSD 3.14035 Å, 24 severe contacts, and a phosphate
P–O5′ bond piercing an endpoint pyrimidine ring. Its coordinates and rejection
are retained under `cpd-anti-local-placement-v2/rejected_whole_nucleoside*`.
It is not used as a relaxation seed.

The live source file hash differs from the frozen snapshot, but read-only review
finds identical design content outside saved-loadout metadata and numerically
equivalent JSON zeros. The ordered site coordinates agree exactly. The campaign
continues from the original hash-locked snapshot; no site remapping or saved-file
write occurred. See `cpd-anti-placement-review-v2/source_provenance_review.json`.

The standalone viewer passed interaction checks (three views, shared rotation,
whole/close-up switch, atom hover, no JavaScript errors). Browser outputs are
confined to the evidence directory; no application workspace was created.

The subsequent local construction **failed its predeclared guard after 24
accepted-step callbacks / 26 energy evaluations**. Step24 reverses D000:7 C3′
chirality, in the nucleotide preceding endpoint2. Its four-neighbor signed volume
changes from −0.28328 Å³ in the original source to +0.14450 Å³ at the rejected
step. All four anti lesion centers retain the correct stereochemistry. The last
valid iterate and the rejected step are stored separately.

Independent double-precision Reference-platform evaluation confirms the last valid
iterate's maximum mobile force is 88.34294 kcal/mol/Å; it is not stationary. All
288 sugar centers retain their source signs there, and all ten local centers also
match the original QM fragment references. There are no severe mobile contacts or
detected ring piercings. The ring search radius is derived from actual bond/ring
sizes rather than assuming normal geometry. Maximum base displacement remains
7.73290 Å, above the unchanged product-placement screen. None of these partial
improvements makes this an accepted construction or a certified minimum.

Source diagnosis identifies **seven inherited parent-DNA bond defects** under
the declared 0.7–1.3 equilibrium-length construction screen. Three are near the
lesion: phosphodiester O3′–P distances 2.11366, 3.90534 and 4.24650 Å. Four are
outside the movable region, at D002:26–27, with lengths 3.35735–3.45707 Å; their
native equilibrium lengths are 1.433–1.600 Å. They remain exactly unchanged in
the failed construction. Two additional mismatches arise only from evaluating
new anti crosslinks on original syn coordinates; those are reported separately,
not counted as inherited parent defects.

This separates a source-coordinate problem from anti parameter quality. Further
full-DNA construction needs a versioned source-conditioning diagnostic that
addresses the known strained backbone and nearly planar neighboring sugar,
without altering topology or ordinary saved-design geometry. The subsequent
bounded method revision below addresses those diagnosed defects; the original
local attempt remains failed. The independent QM reference test's terminal
review is recorded below.

Inspect the [interactive failure review](../.development-artifacts/cpd-anti-local-placement-v2/review.html)
and [source / last-valid / rejected-step comparison](../.development-artifacts/cpd-anti-local-placement-v2/failure_comparison.png).
The latter includes the exact C3′ stereocenter and its four neighbors in a shared
frame. The interactive viewer passed panel, shared-camera, whole/close-up and atom
hover checks without JavaScript errors. No browser-created workspace exists.

## Evidence and reproducibility

Paths below are relative to `.development-artifacts/`:

- Activation, policy and stage locks: `cpd-anti-preliminary-v2/`.
- Frozen charge inputs: `cpd-anti-charge-minima-inputs-v2/dataset.json`.
- First charge round and independent check:
  `cpd-anti-charge-minima-fit-v2/{assessment,independent_review}.json`.
- Prepared candidate and local checks: `cpd-anti-engine-candidate-v2g/`.
  `two-nucleosides/fragment.psf`, `fragment.rtf`, `minimum_A.txt`, `atom_map.json`
  and the parent `comparator_last.prm` define the complete fragment candidate.
- Ten native comparisons: `cpd-anti-native-engine-v2/progress.json` and its
  individual binary force files/logs.
- Successful native dynamics and independent identity/charge audit:
  `cpd-anti-native-smoke-v2b/{assessment,independent_review}.json`.
  Its `smoke/` directory contains a runnable PSF/PDB/parameter/config set and DCD.
- Charge-to-conformation diagnostic:
  `cpd-anti-charge-energy-diagnostic-v2/assessment.json`.
- Full-DNA topology, parameter transfer and independent parent-invariance audit:
  `cpd-anti-dna-topology-v2b/`. The first preparation's files are retained in v2;
  its audit stopped on OpenMM's C5M→C7 atom-name normalization, corrected in v2b.
- Rigid-placement rejection, stereo/contact audit and shared-frame viewer:
  `cpd-anti-placement-review-v2/`.
- Bounded local coordinate construction: `cpd-anti-local-placement-v2/`;
  external supervisor/watcher: `cpd-anti-local-placement-service-v2/`.
- Optimizer method selection: `cpd-anti-resume-step-audit-v1/assessment.json`.
- Bounded native QM test: `cpd-anti-default-constraint-v2/`; supervisor/watcher:
  `cpd-anti-default-constraint-service-v2/`.
- Native-convergence rejection: `cpd-anti-default-constraint-v2/independent_review_failure.json`.
- Cached projection diagnosis: `cpd-anti-default-constraint-projection-review-v1/assessment.json`.
- Prepared restart, pending explicit user approval: `cpd-anti-projection-repair-proposal-v1/`.
- Source-conditioning failure, independent review and A/B: `cpd-anti-source-conditioning-v1b/`;
  supervisor/watcher: `cpd-anti-source-conditioning-service-v1b/`.

Preparation attempts v2 through v2f retain their partial files. They exposed
OpenMM attribute/unit handling, systemd executable-path handling and PSF charge
precision issues. No parameter fit or scientific acceptance limit changed during
these corrections. The first native dynamics attempt stopped before integration
because Langevin was enabled after startup. The correction declares it before
minimization and reuses the ten completed static comparisons. Across both native
attempts there were 2,000 minimization steps and 100 ps of dynamics, within the
registered caps.

## Bounded QM outcome and prepared correction

The default-constraint geomeTRIC test for the unresolved lower-basin endpoint-2
+15° case is complete: 26 evaluations, including one cached and 25 new gradients,
about 70 minutes. The registered ceiling was 40 new gradients / six hours /
zero continuations. Native output reports convergence at −1364.5079618122547 Eh.
All 26 native results and hashes were checked; maximum response residual is
4.348e−11, and graph, stereo and constrained-dihedral screens pass.

**The independent stationarity gate fails.** Native tangent maximum/RMS are
2.616e−6 / 9.321e−7 au. Independent Cartesian tangent maximum/RMS are
4.6722044e−5 / 1.00107068e−5 au, against fixed limits 1.5e−5 / 1e−5 au.
Finite differences at three step sizes agree. `review_geometric.py` stopped on
the force assertion; its failure is retained explicitly. Native optimizer
completion neither accepts this reference nor certifies a minimum.

Using only cached gradients, `audit_projection_v2.py` reconstructs the pinned
geomeTRIC internal-coordinate projection. The basis built at the starting
geometry reproduces the native final report. The exact current Cartesian
projection, `g − n(n·g)/(n·n)` for the single constraint normal `n`, retains the
larger residual. Rebuilding the internal-coordinate basis gives a similar failed
maximum, 4.6354e−5 au, but is not identical to the exact projection. The analytic
normal agrees with an independent finite difference to 9.26e−11 in normalized
components. This diagnoses the convergence-metric discrepancy without new QM.

`exact_constraint_projection.py` implements the current exact projection;
`run_projection_repair.py` applies it only within an isolated approved worker.
Two focused tests pass, and its output agrees with the analytic audit for all
26 cached gradients. Existing runtime sources, native outputs and policy hashes
remain unchanged.

The concrete [proposal](../.development-artifacts/cpd-anti-projection-repair-proposal-v1/proposal.json)
uses the last evaluated geometry and cached gradient, unchanged electronic model
and force limits, **at most 15 additional gradients / two hours / one corrected
restart / no further continuation**. Cumulative new gradients cannot exceed the
original 40. The frozen policy nevertheless declares `max_continuations: 0`:
an explicit user decision on this narrow restart exception has been requested
and is still pending. The worker requires a hash-bound approval record and has
not launched. A queued completion notice is not such an approval.

The native-complete wake token `9ba53c3b-b126-40bb-bce8-918eee37429d` was delivered
and acknowledged on 2026-09-26 UTC. All 26 native-result/geometry hashes, response
residuals and the final optimized-coordinate correspondence were reverified.
Recomputing the Cartesian tangent projection from the cached gradient at three
finite-difference step sizes reproduces the failed force verdict. The original
proactive review and failure remain intact; `completion_delivery_verified.json`
links the actual delivery and native evidence. No new QM evaluations or restart
were launched. No torsion fit begins from the rejected reference. The older
endpoint-2 basin-loss result also remains failed.

Full-DNA topology and parameter transfer now pass. Coordinate assembly must
retain the two independent backbones at the previously frozen ordered site and
produce a concrete geometry review artifact before any normal app integration.
The new DNA transfer retains native sugar parameters and therefore needs its own
geometry and engine checks; the capped-fragment results do not certify it. Preliminary structural
qualification still requires the parameter stages, prospective checks and
registered anti/undamaged context simulations.

One local construction attempt was launched after retaining both rigid-placement
failures. It starts from the unpierced base-only seed and moves 322 atoms in the
two endpoint residues plus two sequential neighbors on each side (ten residues
total). The remaining 2,721 atoms are exactly fixed. It uses the unchanged full
CHARMM vacuum energy, without extra restraints, parameter fitting or dynamics.
The finite budget is 5,000 accepted iterations / 8,000 energy evaluations / two
hours, one attempt, no continuation. Expected runtime is 20 minutes and the
external watcher sends one overdue event at 30 minutes. Stereo is checked after
each accepted step, contacts and piercing every 25 accepted steps and at the end.
Inversion stopped this attempt at step24. Sparse contact checkpoints do
not prove a continuously unthreaded path between them.

Local construction has its own integrity report, including bond-length ratios
to native equilibrium lengths, unchanged contact threshold, all 288 source sugar
centers and four anti lesion centers, and fixed-coordinate retention. These are
construction checks, not substitutes for QM accuracy. Final force is reported
independently of optimizer termination; no Hessian/minimum certification is
claimed. The prior rigid-placement verdicts and 3.5 Å displacement screen remain
visible. Terminal evidence, independent forces/geometry and a new A/B artifact
have now been reviewed. Token `079b1d06-0c77-45f9-815d-8b0a515e91d1` was actually
delivered and acknowledged on 2026-09-26 UTC. Native failure output and retained
coordinates verify the step24 inversion: source / last valid / failed C3′ volumes
are −0.283275 / −0.275564 / +0.144497 Å³. All 288 sugar and ten original-QM local
stereocenters retain their signs in the last valid iterate; 2,721 fixed coordinates
are exact. Retained forces agree with the previous independent 88.34294 kcal/mol/Å
verdict. The delivery receipt links these checks and the seven-source-bond diagnosis
without altering either the original failure or the later conditioning result.
No duplicate construction or full-DNA dynamics was launched; the separate QM
restart decision remains pending.

### Source-conditioning method revision

The next delivered preparation wake was independently acknowledged rather than
rerunning the old fixture. Its turn prepared and launched
`cpd-anti-source-conditioning-v1b`, with a new frozen plan documenting why the
coordinate method and mobile region change. This uses the previous attempt's
last valid iterate as an explicitly nonstationary seed; it does not erase or
extend that run's recorded outcome.

The mobile region adds D002:24–29 around the four independently identified remote
bond defects: 514 movable atoms / 2,529 exactly fixed. Expanding the contact audit
also finds two inherited contacts involving D002:26 O3′, at 1.317 and 1.531 Å.
These are preparation targets; the final zero-severe-contact criterion is unchanged.
Preparation v1 stopped before any energy evaluation because its preflight wrongly
required zero starting contacts in a geometry-repair task. Its partial files and
`preparation_failure.json` are retained. Corrected v1b is the sole actual trial.

Phase1 uses `trust-constr` with 52 signed-volume inequalities, analytic sparse
Jacobians and `keep_feasible=True`. A 0.1 Å³ positive volume margin prevents
crossing the zero-volume surface. This is a local numerical preparation choice,
not a new force-field parameter or a literature-derived quality threshold.
The analytic Jacobian passes independent determinant/finite-difference and
fixed-atom/reflection tests (two scoped tests).

[SciPy's primary documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.NonlinearConstraint.html)
states that `keep_feasible` is supported by `trust-constr`, not SLSQP. The
[optimizer documentation](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-trustconstr.html)
distinguishes Lagrangian-gradient/constraint termination from trust-radius
termination; neither is a harmonic-minimum certificate. The installed numerical
version, settings and exact source hashes are recorded in the plan.

Phase1 is capped at 500 iterations. Phase2 removes every added chirality
constraint and allows at most 1,500 L-BFGS iterations under the unchanged CHARMM
energy. The second phase runs only if the first succeeds, passes the geometry
screens and lies more than 0.0001 Å³ inside every artificial volume bound.
Both phases together allow 6,000 energy evaluations / two hours, one trial,
no automatic continuation, two CPU threads and a 4-GiB service cap. Initial
expected runtime is 20 minutes; one overdue notification occurs at 30 minutes.
No parameters, masses, charges or topology change, and no dynamics are included.

Final forces are evaluated without the added constraints and assessed against
the existing 0.01 kcal/mol/Å local stationarity report threshold. All inherited
bond/contact/stereo criteria and the separate 3.5 Å product-placement screen
remain visible. A converged constrained phase alone cannot pass this diagnostic.
Independent review must also recheck all seven source bond defects and both
newly exposed source contacts, and create a fresh A/B before further use.

**Terminal outcome:** phase1 stopped at its 500-iteration cap, after about
20 seconds, with the native message "maximum number of function evaluations
exceeded." Phase2 did not run; the artificial constraints were never removed.
Independent review confirms all seven inherited parent-bond defects are now
within the declared 0.7–1.3 equilibrium-length construction screen. This broad
screen does not establish the 0.03 Å QM geometry target. The two inherited remote
severe contacts are gone; no ring piercing is detected. All 288 source sugar
signs and ten local QM stereocenters are retained; 2,529 fixed coordinates are exact.

The unconstrained CHARMM force evaluated at those coordinates remains
**19.76107978 kcal/mol/Å**, above the unchanged 0.01 stationarity threshold.
Maximum base displacement is 7.52176 Å, above the separate 3.5 Å product screen.
Minimum oriented volume is 0.29718 Å³, away from the 0.1 artificial bound;
this does not override the failed method/stationarity criteria. Independent
coordinate-integrity acceptance is false, with no minimum, full-DNA NAMD or
research qualification claimed. No source-conditioning continuation is launched.

The new [interactive A/B](../.development-artifacts/cpd-anti-source-conditioning-v1b/review.html)
and [static lesion/backbone comparison](../.development-artifacts/cpd-anti-source-conditioning-v1b/comparison.png)
show the original source and failed conditioned candidate in a common frame.
Browser panel, shared-rotation, region-switch and hover checks pass without
JavaScript errors; the context closed and saved design remained unchanged.

Supervisor/watcher: `cpd-anti-source-conditioning-service-v1b`, token
`43fb08cf-0ba0-4c0b-9014-a9311c4604ed`, same originating thread. The token was
actually delivered and acknowledged on 2026-09-26 UTC. Native output and the
single recorded phase confirm the 500-iteration failure and absent unconstrained
phase. Direct coordinate checks reverify all seven repaired bond lengths under
the construction screen, 288 source-sugar and ten QM stereocenter signs, and
2,529 exactly fixed atoms. Retained forces agree with the independently evaluated
19.76108 kcal/mol/Å failure. `completion_delivery_verified.json` links those checks
and the unchanged A/B artifacts. No preparation, optimization or dynamics was
repeated; the separate QM restart decision remains pending.

Completion notices from superseded preparation attempts should acknowledge those
attempts and refer to these retained corrections; they must not duplicate finished
fits, preparation or native tests. A queued notice is not proof of session delivery.
The delivered v2 preparation failure token `8bbe03cf-bd00-445c-a550-baa09cab0daa`
was acknowledged and reviewed against its native `atomic_number` exception and
the completed v2g preparation/native corrections. It did not trigger a duplicate
charge fit or fragment test.
The delivered v2b token `d371e0b3-d03e-46d4-bf4e-4061839b1d0e` was also
acknowledged. Its native failure is the subsequent NumPy/OpenMM mass-Quantity
subtraction error, already corrected in v2g. Ten native static logs/force files
and 102 trajectory geometries were rechecked, with all ten local stereocenters
preserved. No calculation was repeated to handle the obsolete notice.
The delivered v2c token `d62cfcda-bdc6-4f14-bf18-2d69eb606d06` was acknowledged
against the native `Quantity.__format__` error while writing `MASS` records.
All 62 corrected atom masses match the parameter table in daltons; corrected RTF
and retained native output/trajectory hashes verify. Its original files remain.
The delivered v2d token `5cc9838d-23c0-4f19-a1cb-73bee39d8fc0` was acknowledged
against its native failure to find `psfgen` under the systemd PATH. The pinned
absolute binary, successful corrected psfgen log, ten native comparisons and
completed trajectory evidence verify the correction. The obsolete wake caused
no duplicate fragment job and does not approve the proposed QM restart.
The delivered native-engine token `6a84a001-26db-4c72-8eb0-519ecc6c354f`
was acknowledged against the original NAMD fatal error: Langevin must be enabled
at startup. The old run reached minimization step1000, then stopped before any
dynamics. The corrected configuration has identical lines reordered to enable
the thermostat before minimization. Its native log reaches step101000 without
a fatal error, and the 101-frame DCD and prior independent review hashes verify.
All ten native comparison logs and binary force files were also rechecked.
`cpd-anti-native-engine-service-v2/completion_delivery_verified.json` links the
delivered receipt, preserved failure and corrected evidence. No simulation was
repeated; the separate QM restart decision remains pending.
The successful smoke token `a4df7a55-0425-41b0-aa8b-17bd0f4e1290` has now also
been delivered and acknowledged. Native output and ten static log/force-file
pairs verify; direct inspection of 101 DCD frames plus final binary coordinates
again preserves all ten original-QM stereocenter signs. Its delivery receipt is
`cpd-anti-native-smoke-service-v2b/completion_delivery_verified.json`. This confirms
the existing 100-ps fragment engineering result; full-DNA qualification and the
pending QM restart decision are unchanged. No new calculation was launched.

Software validation: 26 initial scoped tests and 3 subsequent transfer tests pass, covering legacy and v2 authorization,
immutable input/round guards, subgrid water minima and geometry-integrity checks.
The transfer tests protect parent sugar/phosphate terms and prevent methyl-cap
terms from entering DNA. Native calculations and evidence audits provide the
scientific checks above.
The two exact-projection regression tests and cached 26-gradient comparison
also pass. Source-conditioning acceptance remains failed despite its successful
geometry/browser checks.
