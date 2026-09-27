---
name: Preliminary cis-syn CPD strand-builder integration
description: Additive v6 is usable through explicit-solvent NAMD; full scientific release remains pending.
type: project
status: active
authority: supporting
---

User accepted bounded preliminary research qualification, then requested strand-builder
integration (2026-09-20). See `docs/cpd_strand_builder.md` and its verification report.

- `simulation_ready` still means full scientific release (false); `simulation_supported`
  also allows hash-verified preliminary research qualification. Do not mark old full gates passed.
- Curated assets: `backend/data/forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/`.
  No runtime archive dependency. Review + evidence hashes travel in every package.
- Scope: additive, adjacent internal TT, 5′→3′ patch ordering, ordinary masses, ≤2 fs.
  Drude, other stereoisomers, termini/interstrand/nonadjacent contexts remain unsupported.
- CSV6 retypes both nucleotides, retains carbonyl impropers, deletes two reactant planar
  C5 impropers present in bundled THY but absent in the tested reference fixtures.
- Product coordinates use native-relaxed 1T4I template, never falsely label provenance as QM.
  Base-only placement preserves normal sugar/backbone geometry; rejects clashes/strain.
- Raw solute coordinate override and graphene-only omission are blocked for product designs.
- Example .nadoc is under docs/examples; native ZIP + screenshot under
  `.development-artifacts/cpd-builder-integration-v1/`.
- 12-bp builder duplex passed 1,000 native minimization + 1,000 dynamics steps (2 ps).
  Earlier overnight 34-ns benchmark remains stability evidence; one CPD replica opening
  is unresolved energetically, not automatic reason to refit indefinitely.
- Final verification: 61 scoped backend tests, 6,573 frontend tests, CPD builder/progress
  browser checks pass. Broad backend/smoke/lint retain non-CPD failures; see report.
- No spending or new long-run campaign during integration. Shared VR/other work preserved.

User-visible copy requested 2026-09-20: `workspace/CPD/cpd_preliminary_duplex.nadoc`.
Completed native integration job `a2c3e3a2b7bd` lives in standard `workspace/md_jobs/`,
linked by `design_source_path`. Both min + 2-ps NVT recorded; 10-frame/24-nucleotide
trajectory and display readiness verified through the running app API. No new simulation.
The docs example remains a reusable regression fixture.


Cis-anti scientific continuation 2026-09-27 UTC: user chose Sella as default for
new molecular geometry work; memory/feedback_sella_default.md and CPD rule record
it without modifying frozen inputs. docs/cpd_anti_scientific_qualification_20260927.md
and docs/cpd_anti_shape_correction_review_20260927.md record the first-candidate result.
CLOSED AT DEADLINE: docs/cpd_anti_shape_fit_closeout_20260927.md. Recovery ended
2026-09-27T04:29:42UTC, orderly budget termination (solver_success=false), no OOM.
Wake5b5de21a-1f24-4815-8a3f-36f4abb54225 eventcomplete ACK04:30:00.571278UTC.
69 complete models =3 outer centers (1,24,47) +66 derivative probes; replay
reaches incomplete70 bitwise. Selected61 objective2.529452, exposedenergyRMS
.294398/max.915744kcal/mol; all3 representatives pass; three endpoint1 RMSD fails:
-15 .296755Å, -30 .320938Å, exposed -22.5 .321259Å, threshold.25Å unchanged.
All maxpropererrors<20deg. ParametersSHA3c029534fabc7a963958d566c8f6cef1b7d2e7db892aa8244c2444effe21d4f2.
Service completion_delivery_verified.json audits36 recovered models +24 recorded
cases of70 (960cases/32883 evals); original33-model evidence rehashed unchanged.
Combined1818 unique complete-case records/62194 saved evals; model70 has37 further
saved evals in unrecorded representative1, fullforce.000512917kcal/A but no native
completion record/minimum credit. Last representative unstarted. Model70's23
available profiles have9 shapefails, energyRMS.318288; incomplete/fullobjectiveabsent.
partial_model70_force_correction.json corrects projection/fullgradient diagnostic
label for that unconstrained partialcase; numericmaxsame, allverdicts unchanged.
optimizer_closeout_verified.json verifies replay; two small replay-helper failures
preserved alongside correctedv3. Journal peak671.7MiB/zero swap through termination.
cpd-anti-shape-closeout-v2-r2/assessment.json pins failed selected trial+audits+ledger.
residual_geometry_review.json uses savedcoords only: failed groups individually
align.102-.120Å; combinedRMSD fails, implicating relative sugar/base arrangement,
without identifying unique missingparameter or introducing new gates.
Both original rounds and absolute wall window exhausted. No active fit, automatic
continuation, newQM, contextMD or cloud. Prior NAMD milestone applies originalbundle,
not unvalidated model61. Scientific qualification/minimum/release flags stayfalse.

Recovery launch history: docs/cpd_anti_shape_fit_oom_recovery_20260927.md. Original second/final fit
launched02:29:42UTC, cgroup6GiB OOM02:41:50UTC; worker2179155 and supervisor2179120
dead. Raw status.json stillrunning is stale; systemd/kernel prove OOM. Service
cpd-anti-shape-fit-service-v2-r2 token2c49745f-d67f-4036-9db5-0acec5e1b04e delivered
supervisor_stopped, ACK02:43:38UTC. completion_delivery_verified.json verifies33
complete models+16 complete cases of34 =874 fragments/29,870 saved MM evaluations,
final E/F, all objectives/chemistry/forces. Incomplete seventeenth case8frames,
maxforce5.50409kcal/A. Best trial32 loss2.877326, exposedenergyRMS.426142/max1.127347,
6shape failures (includes new ep1+30 failure); no development/minimum pass.
Recovery code shape_fit_isolated_recovery_v1.py + sella_cached_mm_replay_v1.py
prepared in cpd-anti-shape-recovery-preparation-v1b. Replay33 outer
residuals reaches34 bitwise, all33 objective vectors identical; complete37-eval
and interrupted8-eval Sella prefixes replay with zero new energies, peak392628KiB.
Four guard tests pass; expected early v1 helper import failure preserved. Per-model
subprocesses were used, same6GiB/360 models/max_nfev12/per-case caps and original
absolute04:29:42UTC fit deadline (22:29:42MDT Sep26); no deadline reset. Requires
explicit recovery confirmation received: user “Resume with the interrupted round”.
authorization.json pins planSHA262ea4d63d8505dedf714f9a99a349abda9175236c2e65689f55980988d1dc2a.
Launched04:16:06UTC with815seconds remaining, no clock reset. Service
cpd-anti-shape-fit-recovery-service-v1, output cpd-anti-shape-fit-recovery-v1;
supervisor2434317, watcher2434319, armed token5b5de21a-1f24-4815-8a3f-36f4abb54225
subsequently delivered/ACKed as above. Model34 native audit independently verifies26 fragments /
909 saved evaluations, final E/F, constraints, chemistry and exact residual;
16 cases reused, interrupted case8 cached +26new evaluations, six shape failures.
At handoff41 models complete; best36 energyRMS.424368/max1.094948, six shapefails;
servicepeak704380928bytes (672MiB). handoff_health.json pins progress snapshot,
live process identities (worker2434320, changing child), CPUs4–7 and armedwatcher.
Original pending_confirmation.json is historical, superseded by authorization.json.
No third round, automatic further recovery, changed inputs or cloud spending.
Inputs cpd-anti-shape-inputs-v2-r2 receiptSHA26f42f347a7625cc1ae1e1d59e6ab95dfbb167ecb65fb4495e4820ae3f7b4557.
State cpd-anti-shape-state-v2-r2 inherits round1 and reserves round2 through original
guard; old candidate/policy/ledger preserved, exclusive successor pointer registered.
Both rounds now accounted for; no third fit, duplicate/restart or automatic extension.
Original registered run:22 coefficients,23 exposed +3 representative structures, Sella inner geometry,
bounded least-squares outer fit includes energy and geometry, total shifts±5 from
original v2g (not reset from r1). Cap2h/360 model evaluations incl Jacobian probes,
max_nfev12; CPUs4–7,6GiB,service2.25h. Initialmodel independently verified26
structures/879 saved MM evals/final E/F; same8 shape failures. Six guard tests and
15 static export checks pass. Frozen code shape_fit_v2.py/shape_fit_protocol_v2.py
must not change during run. Future±18.75 validation requires historical exposure
audit and revised-candidate registration first; no newQM/contextMD yet.
All four prospective QM cases independently pass constrained stationarity (73 native
gradients), followed by one fixed-candidate MM relaxation each (133 evaluations).
Complete prospective energy RMS .855945/max1.621983 kcal/mol passes 1/2 limits;
first target RMSD .33480 Å fails .25. Seven exposed geometry mismatches retained.
Acquisition completed 02:05:54 UTC; no active QM. Token
a88710de-cc8e-4d06-b9c8-116f9aed758e delivered/ACKed 02:06:33 UTC; native receipt
in QM service/completion_delivery_verified.json. Fourth final max1.07264e−5 au.
Scorer cpd-anti-prospective-score-v2-r1 freezes references and one-attempt targets;
all four records now complete; do not rerun them. First scoring
service v2-r1-a complete; token7f89baac-4fc6-4060-86c0-4147f5b7943a delivered and
ACKed 01:43:24 UTC. completion_delivery_verified.json independently replays all
54 native gradients / 97 saved MM evaluations and reproduces the three scores.
Immutable scoring_progress_snapshot.json preserves the partial master progress
before future updates, with origin/hash in scoring_snapshot_archive.json.
Four new guard tests pass. Second scoring service v2-r1-b complete 02:07:17 UTC;
scientific_review.json independently replays all73 native gradients/133 saved MM
evaluations and four final MM E/F. Token3f5b0f34-03f8-4151-bf1c-7e2c01fdfd05
delivered/ACKed02:19:31 UTC; fresh completion_delivery_verified.json repeats
native audit, preserves original scientific_review.json and all verdicts.
cpd-anti-profile-geometry-diagnosis-v1 replays all19 saved pairs, localizes N1/base
ring shape and sugar coupling, no new energy/fit. Extended diagnosis
cpd-anti-shape-model-diagnosis-v1c examines all23 pairs/19 baselines and actual
proper/improper inventory. First fit improves10→7 exposed shape failures but
introduces worst lower+15 regression(.1366→.6885Å). Six of12 coefficients only
change frozen-coordinate energy;66 tangent-gradient checks max1.382e−9 Å⁻¹.
v1 failed OpenMM attribute inspection and v1b reversed-quartet classification
erratum preserved; v1c checks both quartet orientations. The frozen versioned
shape correction is now closed at its deadline, preserving candidate lock, original two-round
budget and all23 cases as exposed. Context6×10ns waits for parameter qualification and
frozen context budget. No threshold change, cloud, app promotion or minimum claim.

Cis-anti-I is a separate isolated development campaign. Before explicit resume on2026-09-25, further
parameter fitting is gated by `docs/cpd_validation_protocol.md` and
`experiments/cpd_anti_additive/validation_policy_v1.json`: acquire and freeze a
basin-checked reference set first; all previously inspected scans remain exposed.
The fixed contract is not completed validation. Preserve syn's existing scope;
no anti product integration follows automatically from fragment qualification.

Latest delivered wake 2026-09-26: engine v2e token 8751ba64-5c1a-4491-a580-0259886dd234
ACK 23:01:16 UTC. Read-only replay reproduces all four static E/F comparisons,
200 saved frames plus two final geometries and 202 finite native energy records;
both cases pass 100 ps NAMD. Stereo/bonds/contacts/piercings pass at checked frames.
Original review/final geometry and downstream pins preserved. All 104 portable
bundle files / 125,113,925 bytes rehashed successfully. Receipts in service-v2e;
no new energy or MD. At 23:02:29 UTC prospective supervisor/watcher alive,
seven native gradients verified at first target, max .00274370 au nonstationary;
three targets queued, candidate/inputs frozen. Continue bounded batch then fixed
scoring, no auto refit/MD extension/product promotion/minimum certificate/cloud.

Earlier delayed wake 2026-09-26: engine v2d token 79b56005-d132-48c7-acde-22d1c85dcd4e
ACK 22:58:09 UTC. Four native static logs reproduce solute passes / solvent force
failures .00158725/.00176688 against .001; zero minimization/MD. Two saved diagnostic
logs reproduce .0000250293/.0000243028 after only `bondedGPU 0`, identical physical
inputs. Later v2e uses CPU bonded terms in both static and MD. Old failures/pins
preserved; receipt in cpd-anti-solvated-engine-service-v2d. At 23:00:02 UTC active
prospective supervisor/watcher alive, inputs/candidate frozen, six native gradients
verified at first target; max .00187437 au remains nonstationary. Three targets
queued; existing caps apply, no duplicate calculation/refit/cloud. Read-only helper
verify_prospective_health.py in that service accepts a new output path for later
snapshots; it never overwrites old receipts or starts calculations.

Earlier delayed wake 2026-09-26: engine v2 token bec5870a-93eb-4c37-823e-b21c2b9c1cd4
ACK 22:55:21 UTC. Both solute static comparisons replay successfully; both solvent
fixtures fail PSF NATOM parsing with a blank title. Zero minimization/MD. Later
v2e solvent PSF differs only in title; old failure and downstream pins preserved.
Receipt in cpd-anti-solvated-engine-service-v2. Prospective batch still active:
five gradients at first target, latest native energy/gradient/response verified,
projected maximum .00204913 au still nonstationary. Supervisor/watcher alive,
candidate/inputs frozen, no duplicate calculation, refit or cloud spending.

Earlier delayed wake 2026-09-26: stereo-protected construction token
70e14be3-e04f-4e45-9373-c508ccd81f1c ACK 22:51:54 UTC. Read-only replay verifies
400 native logs / 20,400 energy rows / 400 saved frames, input hashes and downstream
review pins; original independent review unchanged. Both complete 10,000 steps,
5,000 unrestrained; chemical geometry passes, but forces 36.301/38.568 still fail
0.01 and placement fails 3.5 Å. No minimum certificate. Receipt and prospective
health snapshot in cpd-anti-stereo-protected-construction-service-v2.
Active prospective supervisor/watcher alive; first target has four completed
gradients, independently checked against native printed energies/gradients,
response residuals, stereo and three projection steps. Latest maximum .00709593 au
is nonstationary. Candidate/inputs frozen, three targets queued, no duplicate
calculation. Continue existing bounded batch, then independent review/fixed-candidate
scoring; no refit or cloud spending. Full-DNA NAMD milestone remains passed.

Earlier delayed wake2026-09-26: solvent-v1c token1bdb0fa8-33ef-4994-8a97-098d4259f038
ACK22:44:59UTC. Replay8native logs/1508energyrows/30DCDframes and hashes: both
stop750steps onD000:7:C3′ inversion (firstsaved550anti/650control). Final44.046/
80.555forces are restrained; no unrestrained phase/MD/minimum. Originalfailed
verdicts untouched; completion_delivery_verified.json lives inservice-v1c.
Prospective service/watch process identities alive; firstpoint2gradients at
snapshot, first independently verified response9.649e−11 and projectedmax.00820787
au (nonstationary). No duplicate/new calculation launched for this delayed wake.

Earlier anti continuation2026-09-26: delayed solvent-v1 wake8f08635d-0b1f-44e7-a5ee-58f2101a614e
ACK22:33:02UTC. Both native logs reject CHARMM `set nat ?NATC` before any
energy/minimization/MD; all input hashes verified; original failure retained.
New prospective validation registered BEFORE QM in cpd-anti-prospective-qm-v2-r1.
STATE/conformational_candidate_lock.json pins r1 parameters/reference energies/
four ±22.5° seeds; blocks further fits (verified); stage input locks and1usedround
unchanged. Actual angle targets ep1−97.61596/−52.61596, ep2lower61.96594/106.96594.
All49atom seeds preserve reference stereo, rotate graph-defined17sugar atoms;
Sella angle/projection preflight passes; all targets7.5° from exposed inventory.
Service cpd-anti-prospective-qm-service-v2-r1 launched22:40:54UTC, watcherarmed;
first native MP2 gradient running. Sequential4cases,40grads each/160total,
6hpercase/12htotal,4localCPU,6GiBPsi4/10GiBservice,zeroextensions. Do not duplicate
on delayed old wakes. Docs/cpd_anti_prospective_validation_20260926.md. Nextafter
termination: independent raw-native stationarity review, then one fixedcandidate
MM scoring pass at acquired QM targets/common frozen references. No fitting,
minimum certificate, research qualification or cloud spending. NAMD milestone
below remains passed and its portable bundle unchanged.

Earlier anti action2026-09-26: conditioning wake8f4a206c-9f01-42fa-a115-dbd4a56a044e
acknowledged21:40:33UTC; independent Reference replay retains1000iteration failure,
force1.3606541>0.01 anddisplacement14.05149>3.5. See
`docs/cpd_anti_source_stereo_repair_20260926.md`. Psfgen four-coordinate guessing
failed (poor O3 coordinates); explicit native-bond/angle reconstruction succeeds
for all288chemical sugar signs+10antiQM checks, but phosphate bonds remain strained.
OnlyO3′/H3′ atD000:7,D002:26 replaced, everything else unchanged. Same-frame PNG
visually inspected; no product promotion. Source artifacts
cpd-anti-source-stereo-explicit-v2. Frozen native construction
cpd-anti-stereo-protected-construction-v2/service-v2 protects corrected frames,
then weakens/removes temporary288sugar impropers. Completed10ksteps/case,
including5000 fully unrestrained. Independent replay400logs/400savedframes verifies
chemical stereo, final bonds/contacts/piercings; geometry engine-eligible. Final
force36.301/38.568 and displacement8.254/3.505Å still fail .01/3.5 screens.
Isolated engine service cpd-anti-solvated-engine-service-v2e completed22:25:57UTC:
native solute/water-ion comparisons followed by100ps/case,300K,1fs,PME,normal
masses,zero additional minimization/artificial restraints,5960s shared cap.
Independent replay PASS:4E/F,200savedframes+2finalgeometries, all chemistry/bond/
contact/piercing checks; native finite energy/finalforce. FullDNA NAMD-testable
milestone achieved; research qualification/product/minimum not passed.
Report docs/cpd_anti_full_dna_engine_20260926.md; portable bundle
cpd-anti-solvated-namd-bundle-v2-r1 with relative configs, exact native inputs,
accurate start/final viewPDBs, trajectories, manifests. Native system.pdb retains
earlier seed coordinates as an index container; authoritative start.coor overrides.
Next scientific stage4registeredprospectiveQM targets, retain7profilegeometry
mismatches; no auto refit, longer trajectory or normalapp promotion.
V2 solvent-PSF empty
title failure, v2b/v2c prelaunch format failures retained, zero MD steps consumed.
V2d exact diff only adds nonempty solvent-fixture PSF title, then fails solvent
force .001587/.001767 >.001. CPU-bonded diagnostic .00002503/.00002430 passes;
V2e uses bondedGPU0 for static+MD, unchanged physical inputs/tolerances.
No prior MD steps. Gate-scope audit:
immutablev2 engine does not require fullDNAstationarity or3.5productplacement;
keep both numerical screens/reports and historical failed verdicts unchanged,
score geometry eligibility separately; no policy/fit/threshold edits or cloud.

Earlier native wake b9d98b9c-40cb-4729-80a5-d760ea8c5d15
actually acknowledged21:13:47UTC; ten E/F comparisons and102 fragment geometries
replayed, all ten original-QM centers preserved. New isolated paired solvent
construction: `docs/cpd_anti_solvated_construction_20260926.md`, artifacts
`cpd-anti-solvated-construction-v1c`, service `cpd-anti-solvated-construction-service-v1c`.
30,867 atoms/case,9223 TIP3P waters,124Na+/31Cl−,shared solvent coordinates;
solute parameters/topology unchanged. Unpatched source control has known source
defects, not an equilibrated reference. Staged native minimization≤10k steps/case,
2h total,250-step checkpoint checks; no dynamics/automatic continuation.
V1 startup and V1b preparation format failures consumed zero physical steps;
retained. Exact full-system water-parameter export equivalence passes.
Terminal21:31:52UTC: both cases failed at750steps onD000:7:C3′ inversion;
first saved inverted frames550anti/650control. Eight native logs and30DCDframes
replayed; no unrestrained stage/MD. Source audit: canonical[C2′,C4′,O3′,H3′]
C3 signedvolumes positive for both QM references and95/96source sugars, but
D002:26 negative−11.92081Å³ with3.44176Å C3′–O3′. Anti seed retained negative
−9.14757 despite bond repair. D000:7 source near-planar volume0.28328Å³.
Historical288source-sugar preservation means source-relative, not absolute
chemical correctness. Keep old evidence; next prepare source stereo correction
and shared-frame review before a new bounded method attempt, no blind extension.
All jobs terminal; no cloud; force/placement limits and fit budget unchanged.

User paused the anti campaign on2026-09-25 and requested cleanup/commit. Do not
resume simulations from completion wakes. `campaign_pause.json` in the validation
artifact folder blocks launches; three legacy CPD timers/path triggers were disabled
with prior states recorded. Read `docs/cpd_anti_closeout_20260925.md` before explicit
resume. Latest +15 fresh-Hessian restart failed after its final20-gradient allowance.

Review after closeout (2026-09-25): user confirmed **preliminary additive NAMD for
exploratory structural simulations, with documented limitations** as the anti
milestone. See `docs/cpd_cis_anti_workflow_review_20260925.md` for primary-literature
comparison, objective mismatches and proposed finite stages. No calculations,
policy activation or resume occurred during that review.

Subsequent explicit instruction “Begin next steps. Then resume the campaign to get
to NAMD testable cis-anti CPDs” activated `docs/cpd_preliminary_protocol_v2.md` and
`experiments/cpd_anti_additive/preliminary_policy_v2.json`. Activation and stage
input locks live in `.development-artifacts/cpd-anti-preliminary-v2/`; old pause
receipt is preserved, current pause is false, legacy timers stay disabled.
V1 remains the default guard for historical fitting scripts. V2 stage guards
permit independent electrostatics and isolated engine diagnostics with explicit
failed scientific metrics. No normal app geometry or full release promotion.
One default-constraint +15 QM test: at most40 new gradients/six hours, no extension;
`cpd-anti-default-constraint-service-v2` watcher belongs to thread
`01a0db22-ab9c-78d1-beca-a95e0be69849`. Charge stage:17 clean curves/three HF dipoles,
actual water minima, two rounds maximum, second only after recorded residual review.

Resume results: `docs/cpd_anti_resume_results_20260925.md`. Charge round1 passes
all17 clean water curves (independent maxima0.41045 kcal/mol,0.12391 Å); no second
round needed. Candidate `cpd-anti-engine-candidate-v2g` has62 atoms/two separate
nucleosides with correct anti crosslinks. Native10 static checks and100-ps vacuum
smoke pass (`cpd-anti-native-smoke-v2b/independent_review.json`). This is a fragment
engineering milestone only: full DNA untested, research qualification false.
Older endpoint2 QM basin collapses to remote MM basin (8.684° angle discrepancy);
energy landscape remains unresolved. Never erase this failure or auto-promote.
The QM test was the sole remaining computation after the fragment smoke;
the subsequent local placement attempt below is separately bounded.
Acknowledge queued wakes when actually delivered.
Superseded prep/native-startup failures were corrected with retained evidence;
do not repeat finished fits/tests from those old completion messages.

Charge-fit wake token `deabe86b-6aaf-424d-9afa-74c3da3389b7` was actually delivered,
acknowledged and reverified (17 curves); delivery receipt is now recorded.
Subsequent full-DNA topology work: `cpd-anti-dna-topology-v2b` passes coverage and
independent parent-force invariance at the exact frozen site (D001:15/D000:8;
96 nucleotides, 3,043 atoms). Only28 base atoms retyped; native sugar/phosphate
terms retained. Exact222 coefficient transfers, parent3015 atom properties fixed,
total charge−93e. Lesion residues have fractional charges; pair total−2e is correct.
That topology stage performed no coordinate fitting or dynamics; capped-fragment
smoke does not qualify this DNA transfer. Do not promote ordinary app geometry
or release gates.

Placement review `cpd-anti-placement-review-v2` now supplies an interactive/static
shared-frame A/B. Fixed-sugar rigid placement fails: source/template C1′ separations
4.077/7.126 Å, glycosidic lengths1.007/0.971 Å, max base displacement8.159 Å,
one severe contact. Correct stereo and no piercing do not rescue it. Whole-sugar
rigid construction also rejected (24 contacts, one phosphate/base-ring piercing).
Live source hash differs only in loadout metadata/numeric serialization; current
design and exact ordered site coordinates are numerically identical to the frozen
snapshot. No saved-design mutation or site remapping.

Launched one isolated local construction (now terminal failed): `cpd-anti-local-placement-v2`, watcher
`cpd-anti-local-placement-service-v2`, token079b1d06-0c77-45f9-815d-8b0a515e91d1,
same originating thread.322 atoms mobile in±2 sequential residues at each endpoint,
2721 fixed exactly; unchanged full CHARMM vacuum energy.5000 iterations/8000
energy evaluations/2h, expected20min, overdue30min, no extension. Stopped at accepted
step24/26 evaluations on D000:7 C3′ inversion (source volume−0.28328Å³, failed
+0.14450Å³); four lesion centers remain correct. Last valid iterate independently
reviewed: mobile force88.34294kcal/mol/Å, all288 source sugar signs and ten QM
local stereo centers preserved, no severe contacts/piercings, displacement7.73290Å
still fails original3.5Å product screen. No minimum certificate or app promotion.
Seven parent-DNA bond defects already present in source: three local O3′–P bonds
2.114/3.905/4.246Å, four fixed D002:26–27 backbone bonds3.357–3.457Å. Two new
anti links measured on old syn geometry are separate, not parent defects. Local
relaxation alone cannot repair the fixed defects. The subsequent source-conditioning
method revision below addresses these explicitly. Interactive/static A/B
plus exact sugar close-up at `cpd-anti-local-placement-v2/review.html` and
`failure_comparison.png`; standalone browser interaction/cleanup verified.
Terminal token079b1d06-0c77-45f9-815d-8b0a515e91d1 nowactuallydelivered/acked
2026-09-26UTC. Direct coordinate check gives source/lastvalid/failed C3′volumes
−0.283275/−0.275564/+0.144497Å³. Rechecked288sugar+10QMlocal signs inlastvalid,
2721fixedatoms exact, retainedforce versusindependentreview88.34294kcal/mol/Å,
7sourcebonddefects/4remoteunrepaired. completion_delivery_verified.json saved.
No rerun; laterconditioningfailureandpendingQMrestartdecisionunchanged.
The default-constraint QM test subsequently terminated; independent rejection
and the pending corrected-restart decision are recorded below.

Superseded prep v2 token8bbe03cf-bd00-445c-a550-baa09cab0daa actually delivered;
ack plus delivery review link native atomic_number error to completed v2g/native
corrections. Do not duplicate finished work on this or later obsolete prep wakes.
Prep v2b tokend371e0b3-d03e-46d4-bf4e-4061839b1d0e actually delivered/acknowledged:
native mass-Quantity subtraction error already fixed. Rechecked10 native static
logs/force files and102 trajectory geometries, each with ten preserved stereo
centers. Evidence linkage is in its completion_delivery_verified.json.

Prep v2c tokend62cfcda-bdc6-4f14-bf18-2d69eb606d06 delivered/acknowledged; native
Quantity-formatting error in MASS output was already fixed.62 atom masses rechecked
against parameter table plus retained native output hashes; no duplicate fixture run.

Launched (now terminal failed) `cpd-anti-source-conditioning-v1b`, watcher
`cpd-anti-source-conditioning-service-v1b`, token43fb08cf-0ba0-4c0b-9014-a9311c4604ed,
same originating thread. Versioned method revision seeded from retained last valid
local iterate; the earlier failure remains failed.514 atoms mobile (adds D002:24–29),
2529 fixed. Two inherited remote contacts now explicit repair targets. Preparation
v1 performed no calculations: its wrong zero-starting-contact preflight was corrected
with partial files retained; zero FINAL contacts still required. One actual trial.
Phase1 trust-constr,52 signed-volume inequalities≥0.1Å³, keep_feasible+analytic
sparse Jacobian,500 iterations. Phase2 removes constraints,1500 L-BFGS iterations;
requires phase1 success, geometry pass and no near-active artificial bound.
Total6000energy evaluations/2h, expected20min/overdue30min,2threads4GiB,no extension,
no dynamics/parameter/topology changes. Derivative and fixed/reflection tests pass2.
Independent review and fresh interactive/static A/B now complete:500 constrained
iterations reached cap, phase2 never ran, added constraints were not removed.
All7 inherited bond defects now within0.7–1.3 equilibrium-length construction
screen (not QM0.03Å quality);2remotecontacts gone,no piercing,288sourcesugar signs
and10QMlocal centers preserved. Reference maxmobileforce19.76108kcal/mol/Å fails
0.01 threshold; maxbasedisplacement7.52176Å fails3.5Å product screen. All2529fixed
coordinates exact. No minimum/fullDNA-NAMD qualification or continuation.
Viewer interaction and cleanup verified; saved design unchanged. Token43fb08cf-
0ba0-4c0b-9014-a9311c4604ed nowactuallydelivered/acked2026-09-26UTC. Nativephase
andcoordinatechecks reconfirm500constrainediterations/no phase2,7bonds within
construction screen,288source+10QMstereocenters preserved,2529fixedatoms exact.
Retainedforces agreewithindependent19.76108kcal/mol/Å failedstationarity.
completion_delivery_verified.json links receipt, failureandunchangedA/B. No rerun;
separateQMrestartdecisionstillpending.
Numerical feasibility margins are preparation settings, not literature acceptance.

2026-09-26UTC v2d prepwake token5cc9838d-23c0-4f19-a1cb-73bee39d8fc0 received/acked.
Native psfgen-not-on-systemd-PATH failure linked to corrected pinned binary,
successful native62atom build and10native comparisons. Oldfailurepreserved.

Default-constraint QM terminal:26eval=1cached+25new,~70min. Native "Converged!"
but `review_geometric.py` forceassert fails. Native tangentmax2.616e−6au versus
independent exactCartesianmax4.6722044e−5/RMS1.00107068e−5; fixed1.5e−5/1e−5 limits.
All26nativehashes,graph/stereo/dihedral/responsechecks pass; maximumresponse4.348e−11.
No acceptedreference/minimum. `independent_review_failure.json` preserved.
Cached `cpd-anti-default-constraint-projection-review-v1` reproduces native report
using initialDLCbasis; exactcurrentnormal projection retains failed residual.
RefreshedDLCmaximum4.6354e−5 alsofails but is notexactCartesian. Analyticnormal
versusfinite-difference maxerror9.26e−11. No newQM for diagnosis.

Prepared `cpd-anti-projection-repair-proposal-v1`:isolatedexactprojectionworker,
2regressiontestspass,26cachedgradientoutputsagree. Max15newgradients (25prior+15=40),
2h,4threads10GiB,onecorrectedrestart,no furthercontinuation,unchangedforce/electronics.
IMPORTANT: userdecisionrequestedandpending; original frozenv2 max_continuations=0.
Do not launch without explicit answer approving this narrowexception. Worker
requires explicit_restart_approval.json binding exactproposalhash+userinstruction.
No currentcalculation. OldqueuedwakesareNOTanswerstothisapprovalquestion.
QMtoken9ba53c3b-b126-40bb-bce8-918eee37429d actuallydelivered/acked2026-09-26UTC.
Rechecked26nativeresult+geometryhashes,response≤4.348e−11,optimizedcoords correspondence.
Three-step finite-difference projection fromcachedgradient reproduces max4.6722e−5au
failure. completion_delivery_verified.json linksreceivedack+nativeevidence; original
failure/proactivereviewpreserved. No newQM/restart. Explicitexceptiondecisionpending.

Native-engine token6a84a001-26db-4c72-8eb0-519ecc6c354f actually delivered and acked
2026-09-26UTC. Original NAMD fatal error: Langevin enabled after startup; stopped
after1000minsteps/before dynamics. Corrected v2b enables thermostat beforeminimize;
same configuration lines, final101000step/101DCDframes/100ps. Rechecked10native
comparison logs and binaryforcefiles plus pinned independentreview/trajectory
hashes. completion_delivery_verified.json links evidence, oldfailure preserved.
No duplicatecalculation or minimum/fullDNApromotion. PendingQMrestartdecision
unanswered; this obsoletewake is not authorization for the exception.

Successful native-smoke tokena4df7a55-0425-41b0-aa8b-17bd0f4e1290 nowactually
delivered/acked. Tenstatic log/forcepairs andnativecompletionverified; reread101DCD
frames+finalbinarycoordinates=102,all10QMstereocenters preserved. Receipt at
cpd-anti-native-smoke-service-v2b/completion_delivery_verified.json. Existing100ps
fragmentengineeringpass only; no fullDNA/minimum/researchqualification,no newrun.
QMrestartapproval remains pending.

2026-09-26 UTC: user requested public QM/parameterization alternatives. Review at
`docs/cpd_qm_md_alternatives_20260926.md` ranks Sella (explicit minimum mode) or
DL-FIND with existing Psi4 gradients, ORCA+ffTK, and ForceBalance fitting of raw
QM energies/gradients at nonstationary geometries. Q-Force offers Hessian/torsion
fitting but defaults need CHARMM/charge-convention overrides. Pysisyphus/ParaMol
maintainers state they are unmaintained/no longer actively developed. Restricted
fixed-coordinate torsion amplitudes permit a convex fit and basis-feasibility
diagnosis; this is a proposal, not an executed fit or relaxed-landscape proof.
Any force-matching branch needs a versioned prospective protocol; current failed
scan verdicts and policy remain unchanged. No installation, QM, fitting, MD,
remote submission or cloud spending in this review. Pending restart exception
still unanswered. Full-DNA construction remains independently unresolved.

2026-09-26: user explicitly selected a fresh Sella attempt. Current next step is
`docs/cpd_anti_sella_attempt_20260926.md`, not the older pending geomeTRIC repair.
`cpd-anti-sella-fresh-v1` freezes original 49-atom endpoint-2 +15 lower-basin seed,
fresh Sella optimizer/Hessian, no reused QM, same Psi41.11 DF-MP2/6-31G(d), final
exact Cartesian limits 1.5e-5 max/1e-5 RMS and 0.01degree constraint. New explicit
authorization/plan hashes; old v2 policy and failed verdicts unchanged. One attempt,
60 new gradient calls/6h/zero continuations; four cores/6GiB Psi4/10GiB service.
Sella2.6.0 installed in isolated cache venv; production dependencies unchanged.
Three regression tests pass; cached constraint normal and analytic Sella interface
preflight pass, no new QM in preparation. Service root `cpd-anti-sella-service-v1`.
On wake, acknowledge actual token and review native evaluations plus independent
three-step projection. No minimum certification, fit or DNA dynamics follows merely
from optimizer completion. No cloud spending.
Sella launched18:28UTC; watcher armed tokena4dba472-7edd-497e-9d8b-cc0eef55d68c,
originating thread01a0db22-ab9c-78d1-beca-a95e0be69849; first native gradient started.
18:32UTC first fresh gradient completed179s, independently reviewed; secondrunning.
Sella firststep passeschemistry/torsion1.89e-8degree. Firstseedmax/RMSforce
.00627785/.00182527au notconverged. Comparedsamearchivedseed E−2.63e-9Eh,
maxgradientdifference2.34e-6au, recordedwithoutnewgate. Immutablefirstaudit in
first_gradient_independent_review.json; worker terminal independent_review.json
mayreplace its interim report. No completion/minimum claim.

2026-09-26 19:23UTC Sella completed successfully:20 newgradients/19steps/55.5min.
Actual wake a4dba472-7edd-497e-9d8b-cc0eef55d68c received/acked19:24UTC. Independent
delivery review parses all20 native energies/gradients, rehashes inputs/results,
checks all20 trajectoryframes/finalXYZ/chemistry, projects printed final gradient
at three steps and compares Sella analyticnormal. Max1.4434545e-5/RMS6.2129007e-6au,
torsion1.219e-8degree PASS originallimits. E−1364.507961799582Eh. Constrained
stationarity only; no Hessian/minimum/global claim. No polishing or extension.
Final Sella printedfmax lags one geometry due ASE log-before-convergence ordering;
currentnative gradient and convergence_checks establish the pass. See
`cpd-anti-sella-fresh-v1/completion_delivery_verified.json` and attempt report.
`cpd-anti-conformational-inventory-v2b/inventory.json`:all15historical+4lowerQM cases,
hash/geometry/map checks;18cachedgradientmetrics,legacyep1−15nativeauditretained.
New+15 is1.41969kcal/molbelow old+15,2.50790above lowerref; distinctsame-angle
conformers retained (heavyRMSD.64169Å,maxheavyproper71.178°). All dataexposed.
Inventory ready=false: parameter identities/bounds and MM branch/reference
manifest must be fixed before conformational stage lock; no fit/extraQM launched.
Inventoryv2a tuple-indexing preparationerror+source retained; corrected v2b is
read-only. FullDNA construction stillfailed separately. No currentcalculation,
no cloudspending, no change to original v2 policy/oldfailures/product support.

2026-09-26 continuation: user requested next steps toward NAMD readiness.
`cpd-anti-conformational-inputs-v2/receipt.json` and stage input lock now frozen.
Four attachment proper keys (O4'C1'N1C2 and C2'C1'N1C6 per endpoint), n1/2/3,
signed coefficient shifts±5kcal, phases0/180, charges/LJ/allothertermsfixed.
One guarded/budgeted round used via require_fit_ready(stage='conformational') and
begin_round. All19 exposed targets retained, common ep1original/ep2lowerref.
`cpd-anti-conformational-fit-v2-r1`: baseline/freshcandidate19+19 SellaMM
relaxations allstationary/chemistrypass. RelaxedenergyRMS2.1952→.54206,
max7.0071→1.00992kcal PASS1/2. Three registeredrepresentative geometriesPASS
.03Å/3°. Allfivefixtures localMMminima/positivecurvature. IndependentPRMreplay
verifies19E/F/geometry/projections. Branchdescriptors12/19pass;sevenretainedfails,
largestlower+15 RMS.68845Å/heavyproper40.10° atN1attachment. Fouroriginal/lower
same-anglepairsremainseparate. Secondfitunused; no prospectiveQMregistration.
`cpd-anti-conformational-native-v2-r1`: tencomparisons maxE.0005581/maxF.0007097,
100ps1fs300K62atoms,101frames+final,allfourlesion+sixsugarQMstereocentersPASS.
`cpd-anti-fitted-dna-v2-r1`: exactlyfourproperkeysupdated,allotherforceobjects
andparticlesexactunchanged; nativeparentDNA retained.3043atomrun0NAMDpasses
abs-or-relativepolicy: dE.00550,dF.00640 vs5.5326/.04945 limits. NoDNA dynamics.
`cpd-anti-fitted-conditioning-v2`: separateversionedSLSQP1000 constrained/
1500free cap,6000eval/2h/zeroextension,514mobile2529fixed. Failedfirstphase
1000steps1005eval26s. Newpotentialforce25.4001→1.36065>.01,displacement14.0515>3.5.
All288sourcesugar+10localQMstereo preserved,bondratios.8012..1.0797,zerosevere
contacts/piercings,fixedcoordsunchanged; minimumvolume7.932>.1,notactivebound.
No freephase/dynamics.IndependentPRMforce/stereo replay and shared-framePNG/HTML
retained;PNGvisuallyinspected,HTMLnotbrowser-tested. CPUfinite-diffenergy noisy
at1e-4Å (error4.97) despiteanalyticCPU/Referencegradientagreement4.8e-4;
ReferenceFDerror2.04e-6pass. Do not claim minimum or extendfailedattempt.
Portableinputs: `cpd-anti-namd-engineering-bundle-v2-r1/README.md` (tested62atom
smoke;fullDNAstaticonly). Currentreport docs/cpd_anti_conformational_results_20260926.md.
4focusedtestsPASS1.04s; noapplicationbehaviorchange/saveddesignwrites/cloud.
Alljobs terminal. Watchers queued completion messages, not yet received/acked
in this turn; onactualwake acktoken thenreviewretainedreports, avoidduplicatejobs.
Nextconstructionreview must address large unsolvated/fixed-boundarydeformation;
neitherlargeroptimizercapnorlowerenergyrmse is the selectedautomaticnextstep.

2026-09-26 21:07:54UTC actual conformationalfit wake received/acked:
e84c10a1-cc03-434f-98bb-f53a1c5529bd, eventcomplete. Service
cpd-anti-conformational-service-v2-r1/completion_delivery_verified.json audits
38rawMMrelaxations/1323evaluations,hashes,finalevaluatedcoords,3-stepforce
projections; RMS.5420568/max1.0099183 reproduced; stageunqualified7geometryfails.
No duplicatejob/fit/QM. Nativeengineandconditioningwakesremainunackeduntilactualreceipt.
Read-only21frameconstructiondiagnosis cpd-anti-construction-method-review-v1:
energychange−2004.277kcal,lesiondisplacement7.522→14.051Å,no frame<3.5;
lesioncentroid8.695ÅvsalignedinternalheavyRMS.2955Å. RemoteunmodifiedD00226
maxheavydisplacement22.030Å(centroid14.477fromseed),D0007max19.842Å.
No newenergycalculations. Environment−93e vacuum/fixedboundary suspect;
notcausallyproven. Hart2012PMC3285246primarymethods supportneutralizedTIP3P,
stagedheavyrestraintsthenrelease. Selectednextdirection=solvatedneutralized
construction+undamagedcontrol,separateversionedboundedengineeringplanbeforelaunch.
Notexecutableyet; no thresholdwaiver/automaticextension/secondfit/contextqualification.
See docs/cpd_anti_construction_method_review_20260926.md. Alljobsstopped.
