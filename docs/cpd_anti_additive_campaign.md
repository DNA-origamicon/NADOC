# Cis-anti-I additive parity campaign

**PAUSED BY USER — 2026-10-08. Explicit resume required.**
Stopped control2 completion watcher first,then entire NAMD service. Both units
inactive/dead; no NAMD remains. This pause supersedes all earlier next-job
admissions and wake instructions. Do not continue from a delayed completion wake.
Control2 worker reviewed segments01–09 (9ns),all gates pass; independent full
control2 audit remains pending. Segment10 interrupted at user request.
Verified latest checkpoint step5100000 =9.14ns validation; log reached5101000.
Complete265477-atom coor/vel/fullXSC finite,geometry/water/image pass,image48.625A;
checkpoint matches saved DCD coordinates and cell. Remaining430000steps=0.86ns
to5530000. Raw tail after checkpoint is retained but not credited on resume.

Pause receipt `cpd-anti-gpu-cube-context-v5/campaign_pause_20261008.json`, copied
to service `user_pause_20261008.json`. Original supervisor status can remain
stale running; actual inactive units and explicit pause receipt are authoritative.
See [resume handoff](cpd_resume_handoff_20261008.md). All simulation data retained;
no automatic restart,deadline reset or commit requested/performed. No readiness
promotion. Prior failures and all three completed10ns validation audits preserved.

**Anti2 aggregate10ns audited; control2 admitted (latest).**
Wake7849095e-efc6-4f8d-9bd6-9b311afc60b0 ACKed. Remaining8.9ns returned0
in28755.90s (7.99h),without another startup exception. Successful aggregate10ns
native31382.61s (27.53ns/day). Auditor`audit_cube_anti2_v12.py` checks1000DCD
cells,100periodic restart triples,22native jobs,33stratified geometry frames,
11binary endpoints and native/restart/CPU endpoint energies.1011worker geometry
records pass; not independent all-frame chemistry. Exact step sequence535000
through5530000 excludes failed originalsegment02 and duplicate endpoints.

Minimum image36.743A,max sampled void3.780A. Late5ns299.185K,+1.640bar,
density1.022953g/cm3,149.844mM addedNaCl; density half-change-0.00000236g/cm3.
All finite context gates pass,not equilibrium/minimum/readiness certification.
On same28 shared contact identities,anti2 blockretention0.744–0.813 versusanti1
0.464–0.605. Prepared fractions0.821 versus0.643 demonstrate initial-state
variation. Control1 retention0.811–0.853 is contextual,not matchedcontrol2.
Both anti outcomes retained; no preference for favorable replica or parameter
refit. `replicate_comparison_v12.json` stores baselines,blocks and per-contact
retention. Initial-state/replica variability remains a material limitation.

Anti2 original`validation/aggregate_assessment_v12.json`,
`aggregate_native_audit_v12.json`,`aggregate_performance_v12.json`,
`completion_review.json` retain evidence/admission. Failedstartup source and
one successful diagnostic remain preserved; unresolved runtime rootcause is
not called fixed. Any recurrence stops for method investigation without retries.

Three of six registered10ns runs complete. Next ONLYcontrol2 via unchanged
v6launcher/worker;15h cap,1ns audits,100ps checkpoints,10psDCD,fullXSC and
unchanged gates. Service`cpd-anti-cube-validation-control-2-v6`, evidence
`cpd-anti-cube-validation-control-2-service-v6`. Completes second matchedpair,
testing control variability; no extra anti extension/tuning justified by timing.
On wake ACK and run `audit_cube_replica_v9.py /tmp/control2_audit.json control 2`
with NADOC_REPO_ROOT andOPENBLAS_NUM_THREADS=1; review shared28contacts and
preparedbaseline with anti2/control1,without treating correlated frames as
independent replicas. Pin assessment,audit,performance_report in completion_review
before anti3. Anti3/control3,final interpretation,provenance errata and portable
package remain pending; no cloud or readiness promotion.

**Anti2 startup diagnostic passed; remaining8.9ns admitted — 2026-10-07.**
Wake d4abb3c9-b784-4ec4-ba03-326018ddb9db ACKed.100ps test returned0 in305.67s
(5.09min),295.62native s. Native startup exception did not reproduce; root cause
remains unresolved,not declared fixed. Audit replays all10DCD frames plus binary
endpoint,full cells,complete1050000 restart triple,1080000 endpoint and CPU/
resident initial/endpoint energies. Minimum image51.345A,max void3.338A;
50ps blocks299.338/299.257K,-7.447/+15.695bar,density1.023196/1.022833.
Same originalcheckpoint/seed55227/engine/method/gates; only runlength/output
changed. Credit100ps after audit,bringing anti2 to1.1ns. Failed originalsegment02
has zero credit and remains preserved. No equilibrium/minimum/readiness claim.

Worker`continue_cube_v11.py`: new output`anti/replica-2/validation-remaining-v11`,
first1080000→1530000 (0.9ns),then segments03–10 (8ns),final5530000. Full saved
coor/vel/XSC from diagnostic endpoint,unchanged2fs,NPT force-switch,PME144,p4.
New seedbase95027+100*segment declared; no bitwise RNG continuity claim.13h
hard cap (<16h),~8–9h expected; conservative budget12.452h.100ps checkpoints,
10psDCD,per-segment chemistry/water/image/cell/energy/observable checks and
slowdown/time admission unchanged. Any native exception stops; no automatic
retry. If bad_any_cast recurs, investigate runtime/method before another retry.

Service`cpd-anti2-remaining-v11`, evidence`cpd-anti2-remaining-service-v11`.
On completion ACK and audit aggregate10ns:originalsegment01(1ns),diagnostic
1030000–1080000(0.1ns),v11segment02(0.9ns),segments03–10(8ns). Excludefailed
originalsegment02 and duplicate endpoints. Include failure history and shared
contact comparison to anti1/prepared baselines; aggregate review precedescontrol2.
Write originalanti2 validation/completion_review with pinned aggregate assessment,
audit,performance_report for successor admission. Six focused tests passed for
exactpartial-segment chaining,no overlap/overwrite,failure stopping and timing
limits. No cloud,parameter changes or readiness promotion.

**Anti2 native startup failure preserved; bounded diagnostic admitted — 2026-10-07.**
Failed wake d8262642-3a41-4cab-81aa-cd41fdd05583 ACKed. Segment01 completed1ns
and passed worker checks; segment02 aborted after2.03s at native startup with
returncode-6 and Charm++ `bad any_cast` in SynchronousCollectives recvIndexData
<unsigned long long>. No segment02 ENERGY record, so zero new simulation credited.
Root cause remains unresolved; this is not a recorded chemistry/image failure.
Outside-sandbox nvidia-smi confirms healthy RTX3080Ti and no NAMD process.
Restricted-sandbox driver-access error was not evidence of driver failure.

Checkpoint audit replays all100 saved segment01 frames plus endpoint,full cells,
water/chemistry/image/observables,ten regular checkpoints and endpoint/restart
energies. Step1030000 complete coor/vel/XSC verified. Minimum image44.292A,
max void3.470A; native1ns2915.69s,29.63ns/day. Preserve completed segment01,
failed segment02/config/traceback and original deadlines. Do not launch control2
or count anti2 as10ns completed.

Next is ONE same-engine,same-p4,same-seed55227 diagnostic from step1030000,
100ps to1080000,unchanged2fs,NPT force-switch,PME144,fullXSC and scientific gates.
Only run length/output directory differs from failed attempt. Worker
`cube_startup_diagnostic_v10.py`; output`anti/replica-2/validation-startup-diagnostic-v10`.
Expected~5–8min,hard15min cap; no retry loop. Service
`cpd-anti2-startup-diagnostic-v10`, evidence
`cpd-anti2-startup-diagnostic-service-v10` retains failure audit/authorization.
On wake ACK/audit native initial and endpoint energies,all10 frames plus endpoint,
checkpoint,physical/observables and performance. If startup failure recurs,stop
for runtime-method investigation rather than another blind retry. If diagnostic
passes,review whether to credit the100ps and prepare a new bounded continuation
for remaining8.9ns (450000steps to original segment02 endpoint1530000,then8ns).
No original output overwrite,threshold changes or readiness promotion. All later
replicas remain gated. No cloud.

**Control1 audited; matched structural limitation retained; anti2 admitted — 2026-10-07.**
Wake85ca6cd5-9764-4364-aa71-d3651c1c5417 ACKed. Control1 return0,10ns in
31190.17service s (8.66h),30426.73native s (28.40ns/day). Independent native/cell/
restart audit verified20native jobs,1000DCD cells,100periodic triples,restart/CPU
endpoint energies,30stratified geometry frames and10binary endpoints. All1010
worker geometry records pass; chemistry routines reused,not independent all-frame.
Minimum image33.655A. Late5ns299.231K,+0.192bar,density1.022883g/cm3,
149.833mM addedNaCl,density half-change+0.00001576g/cm3. No former image/cavity/
tension failure; finite physical behavior does not establish equilibrium.

Matched comparison uses28 shared preregistered contacts keyed by segid,resid,
atomname and fixed3.5A descriptive cutoff,not raw fractions from different35/34
source lists. Anti1 per-ns retention0.464–0.605 versus control1 0.811–0.853.
Prepared baselines0.643/0.679 and mean shared-contact distances6.206/3.553A
already differ. This is a material structural difference with initial-state
confounding,not an isolated lesion causal effect,significance or parameter-fidelity
claim. Correlated frames are not independent replicas. Preserve limitations;
no source contacts,fit parameters,acceptance thresholds or readiness flags changed.
Report`matched_pair1_comparison_v9.json`; script`compare_cube_pair_v9.py`.

Control1 `validation/native_audit_v9.json` and `completion_review.json` retain
native and physical/structural/performance/necessity review; auditor
`audit_cube_replica_v9.py` supports uninterrupted case/replica audits. CLI:
`NADOC_REPO_ROOT=/home/jojo/Work/NADOC OPENBLAS_NUM_THREADS=1 .venv/bin/python experiments/cpd_anti_additive/audit_cube_replica_v9.py /tmp/audit.json CASE REPLICA`.
Two of six registered10ns runs complete. Next anti2 fresh10ns using registered
seed and unchanged worker/method,15h cap,1ns checks/100ps checkpoints. Service
`cpd-anti-cube-validation-anti-2-v6`, evidence
`cpd-anti-cube-validation-anti-2-service-v6`. Necessity: test persistence/variation
of anti structural behavior across another registered preparation,not extend/refit
anti1. Retainp4/2fs/cube; no new tuning justified by current timing.
On completion ACK/audit all native outputs and physical/structural/performance
trends before control2 admission. Compare against anti1 and prepared baselines;
update comparisons without relabeling correlated frames as replica evidence.
Remaining replicas,final interpretation,provenance errata and package pending.

**Anti1 complete10ns audited; matched control1 admitted — 2026-10-07.**
Wake9bde86a2-0e42-4903-a994-2e79bb78146d acknowledged. Remaining8ns return0,
26489.83s (7.36h),25964.46native s (26.62ns/day). Audit verified800 new DCD
cells,80 periodic restart triples,16 native jobs, restart/CPU endpoint energies,
24 stratified geometry frames and8 binary endpoints. Prior200frame audits
remain linked. Combined1000 unique10ps frames span535000..5530000 without
interrupted tail or duplicate endpoints. Final8ns worker808geometry records
pass; replay is stratified for chemistry, not independent all-frame chemistry.

Late5ns299.217K,+2.146bar,density1.022959g/cm3,149.844mM addedNaCl;
density half-change+0.00000718g/cm3. Final8ns image minimum34.425A, maximum
sampled void3.679A. No former image/cavity/tension failure. Crosslink1ns means
~1.566–1.583A; source-contact means0.478/0.517(first2ns),0.390(at6ns),0.455(at10ns),
endpoint0.486. Structural evolution is retained, not called converged or attributed
to CPD without controls. No threshold changed, no refit, no readiness promotion.

Original anti1 `validation/aggregate_assessment_v8.json`,
`aggregate_native_audit_v8.json`, `aggregate_performance_v8.json` and
`completion_review.json` record the split10ns and admission decision. Auditor
`audit_cube_aggregate_v8.py` archived alongside results. Native speed projection
for fresh10ns~9.02h; preserve conservative13.93h budget and15h cap from startup.
Current p4 method remains preferable to unmotivated cell/timestep/core changes.

Next only control1 fresh10ns via unchanged`launch_cube_validation_v6.py`,
service`cpd-anti-cube-validation-control-1-v6`, evidence
`cpd-anti-cube-validation-control-1-service-v6`. Ten1ns stages,100ps checkpoints,
fullXSC,10ps frames,registered observables and unchanged gates; stop on failure,
time-budget shortage or>20%slowdown; completion review before anti2. On wake
ACK and independently audit native/restart/cell evidence and sampled chemistry,
review physical/structural/performance with anti1 using shared contact pairs
(the source-specific contact fractions alone are not a matched effect estimate).
Write control1 validation/completion_review with pinned assessment,audit and
performance_report before anti2 admission. Four later replicas, full matched
interpretation,provenance errata and portable package still remain. No cloud.

**Resumed segment02 audited; remaining8ns admitted — 2026-10-07.**
Wake d97adfe9-34e3-4413-b96a-1c1f65e1296d ACKed. Service return0;0.46ns
finished in1527.62s (25.46min). Native audit verifies three jobs, exact saved-step
CPU/resident energy agreement, endpoint energy, all46 DCD frames plus endpoint,
full cells and four complete100ps restart sets. Geometry replay uses frozen
engine routines; earlier154frame audit retained, uncheckpointed old tail excluded.
Anti1 is now at2ns; no convergence/minimum or full-readiness claim.

Remainder minimum image35.681A,max void witness3.413A.50ps-block means299.207K,
-2.693bar,density1.022825g/cm3,149.825mM addedNaCl. Source-contact fraction across
retained0–2ns ranges0.343–0.686, ends0.486; variation is descriptive only.
Native3247.045s/ns (26.61ns/day), faster than preparation reference. Retainp4,
ordinary2fs,cubic cell and fixed gates; no need for repetition or tuning detour.

New `continue_cube_v8.py` runs segments03–10 only, starting step1530000 from
`validation-resume-v7/segment-02-remainder/result.restart` with full coor/vel/XSC.
Outputs `anti/replica-1/validation-remaining-v8`; no overwrites or duplicated time.
Registered seedbase84017+100*segment; no bitwise RNG continuity claim.
Worst preparation native+analysis costs with25%margin and1800s reserve give
11.24h for8ns; hard12h (<16h), nominal~8–9h. Check each1ns segment,100ps
checkpoints,10ps DCD,CPU endpoint/restart energy,all saved chemistry/water/image,
physical blocks/voids/observables; stop on failure,insufficient time or>20%slowdown.

Service`cpd-anti-cube-remaining-anti-1-v8`, evidence
`cpd-anti-cube-remaining-anti-1-service-v8`. Watcher review at10h if still active.
On completion ACK and audit all outputs. Aggregate10ns consists of original
segment01, original segment02 only through1300000, v7 remainder1300000–1530000,
and v8 segments03–10. Exclude duplicate endpoints/tail in time series. Independently
review aggregate physical/structural/performance evidence before control1. Write
original `validation/completion_review.json` with approved_for_next_run and pinned
aggregate assessment,audit,performance_report to satisfy successor launcher.
No other replica automatically admitted. Six-replica comparison,provenance errata
and portable package still pending. Tests cover exact8ns chaining,stop on failure,
no overwrite and interrupted-log checkpoint handling.

**Explicit resume; bounded segment02 continuation — 2026-10-07.**
The user said "resume", superseding the6October pause for newly admitted work.
Historical pause/deadlines remain unchanged. No existing NAMD process was found.
New `resume_cube_v7.py` audit replayed154 saved frames through step1300000,
including full cells, chemistry/water/image gates, registered observables and16
complete100ps checkpoint sets. Minimum image36.049A; checkpoint geometry passes.
Completed segment01 native termination and CPU endpoint energy verified; partial
segment02 energy parsed explicitly through checkpoint, never treated as completed.
Bulk blocks remain near299K,1.023g/cm3 and149.85mM; no equilibrium claim.
Source-contact fraction0.486→0.543 is short-time descriptive evidence only.

Launch only remaining0.46ns from step1300000 to1530000 in
`anti/replica-1/validation-resume-v7/segment-02-remainder`, preserving existing
segment02 and discarding uncheckpointed tail after1300000 from continuation.
Before MD, exact checkpoint CPU run0 energy must agree with original saved-step
potential; resident initial energy checked too. Full coor/vel/XSC,2fs,p4,NPT
force-switch,PME144,100ps checkpoints and10ps DCD retained. New seed74217 is
registered; stochastic trajectory is not claimed bitwise identical.2h hard cap,
~30–40min expected. Worker stops at2ns total validation endpoint for model audit;
eight remaining ns require new admission. No duplicate10ns launch or overwrites.

Service `cpd-anti-cube-resume-anti-1-v7`, evidence
`cpd-anti-cube-resume-anti-1-service-v7`, containing resume_authorization, archived
worker/launcher, resume_audit and plan. On completion ACK and audit exact native
restart/endpoint energies, all46 frames plus endpoint, checkpoints, physical/
structural trends and performance before admitting subsequent8ns. Review must
include earlier1.54ns without counting discarded tail twice. Readiness false.
Eight focused tests pass, including interrupted-log checkpoint-energy selection,
gap/nonfinite rejection and earlier restart/limit tests. Unrelated working-tree
extrusion changes are outside this task. Historical handoff below remains evidence.

**PAUSED BY USER — 2026-10-06. Do not launch or continue jobs until explicit resume.**
The user requested: "Pause the run. commit what we have so far. prepare to resume later."
Stopped `cpd-anti-cube-validation-anti-1-v6-watch.service` first, then the complete
`cpd-anti-cube-validation-anti-1-v6.service` cgroup. Both are inactive/dead; no NAMD
process remains. No completion wake should resume this paused campaign. This
pause supersedes every earlier next-job admission and continuation instruction.

Six preparations remain audited. Anti1 validation segment01 completed 1 ns and
passed worker gates; independent validation review is still pending. Segment02
was interrupted, not accepted. Latest complete checkpoint is step1300000,
1.54 ns into validation; native log reached1328000 (~1.596 ns) before stopping.
Checkpoint coor/vel arrays have265477 finite atoms, full XSC at the matching step,
cubic edge137.93626449 A, geometry/water checks pass, image clearance41.0346 A.
The checkpoint is a restart candidate, not acceptance of all partial trajectory.
Preserved all native outputs and original provenance/authorization/deadline files.
Machine pause receipt: `cpd-anti-gpu-cube-context-v5/campaign_pause_v6.json`;
service copy `cpd-anti-cube-validation-anti-1-service-v6/user_pause.json`.
The old supervisor status may still say running because it was terminated;
user_pause and actual inactive systemd state are authoritative.

Resume handoff: [cpd_resume_handoff_20261006.md](cpd_resume_handoff_20261006.md).
No automatic restart or deadline extension. Existing launcher refuses duplicate
validation outputs; a reviewed continuation must use a new plan/output location
and retain full checkpoint state. No full NAMD readiness or minimum certification.

**All six preparations audited; first cubic validation admitted — 2026-10-06.**
Control3 wake 1eb68864-3b27-452d-a4e0-86535386f220 acknowledged and linked to
native audit/review in `cpd-anti-cube-prep-control-3-service-v6`. Return 0;
4073.93 s (67.90 min). Audit verified 209 input pins, five new native jobs,
existing static comparisons, all 555 DCD cells, ten complete 100 ps restart
sets, restart/endpoint potentials, nine stratified frames and three endpoints.
Control3 NPT minimum image 38.765 A; late500ps 299.176 K,+0.731 bar,
density1.022940 g/cm3,149.842 mM added NaCl; density half-change+0.0001460.
Endpoint/restart void witnesses3.353/3.299 A. All preparation gates pass;
short physical histories do not establish equilibrium or minimum certification.

Aggregate `cpd-anti-gpu-cube-context-v5/startup_admission_v6.json` admits
bounded validation only. Six preparations:3330 saved DCD cells,60 complete
100ps checkpoint sets,54 stratified frames and18 endpoints replayed;
3348 worker geometry records pass, not independent full-frame chemistry.
NPT minimum-image range31.417–40.110 A; late density1.022940–1.023110 g/cm3,
addedNaCl149.842–149.867 mM. Frozen `startup_endpoints_lock_v6.json` retains
six complete step530000 checkpoints, distinct velocities, full XSC and finite
registered observables. Historical failures and gates remain intact.

Worst native1ns3590.166s plus worst preparation analysis277.340s; ten times
their sum with25%margin and1800s additional reserve =50143.83s (13.93h).
First validation has15h hard cap (<16h),~11h expected, overdue review at13h.
New worker`gpu_cube_validation_v6.py` and launcher`launch_cube_validation_v6.py`
reuse pinned cube engine and dynamically correct265477-atom final composition.
Only anti1 launches: ten1ns NPT segments, ordinary-mass2fs,p4,PME144cubed,
force-switch10–12A,full XSC,100ps checkpoints and1ns endpoints; DCD10ps and
raw energy2ps retain preceding registered validation cadence. Every segment
checks saved chemistry/water/image/cell/restart/CPU endpoint energy, physical
blocks, voids and registered structural observables. Any gate failure stops;
>20% native slowdown stops for explicit review. Time admission reserves margin
before another segment. Partial files/checkpoints are retained on interruption;
no automatic rerun or overwrite.

Service`cpd-anti-cube-validation-anti-1-v6`, evidence
`cpd-anti-cube-validation-anti-1-service-v6`, plan`validation_anti_1_v6.json`.
On completion ACK, independently audit native evidence/checkpoint sets and
stratified chemistry, review all segment physical/structural/throughput trends
and necessity/alternatives, then write validation/completion_review.json with
approved_for_next_run plus pinned assessment,audit,performance_report before
control1 admission. Preserve failed evidence and halt on uncertainty requiring
method review. No parallel replicas, cloud or promotion. Six fresh10ns runs,
structural interpretation, provenance errata and portable package remain.
19 focused tests pass, including deadline margin, exact restart chaining,
failures/slowdown stopping, no output overwrite and pending-readiness semantics.

**Anti replica 3 audited; final control preparation admitted — 2026-10-06.**
Wake 77652072-116c-4f19-a62d-6035d0d8c672 acknowledged; delivery verification
links audit/review in `cpd-anti-cube-prep-anti-3-service-v6`. Return 0;
4057.59 s (67.63 min). Audit verified 207 input pins, five new native jobs,
existing exact-system static comparisons, all 555 DCD cells, ten complete
100 ps restart sets, restart/endpoint potentials, nine stratified frames and
three binary endpoints. All 558 worker geometry records pass. This remains
sampled chemistry replay, not independent full-frame or minimum certification.

NPT minimum image 40.110 A. Late 500 ps: 299.123 K, +1.170 bar, density
1.023110 g/cm3, added NaCl 149.867 mM; density half-change -0.0001849 g/cm3.
Pressure 50 ps blocks -8.586..+14.368 bar. Heating endpoint void witness
4.872 A reduces under NPT; sampled NPT witnesses 3.090..3.532 A, restart
endpoint 3.414 A. No previous sustained-tension/large-cavity pattern; no
convergence/equilibrium claim. NPT 1 ns took 3573.794 s plus 274.885 s analysis;
GPU mean 97.52%. Timing remains consistent; retain qualified method and p4.

Five of six preparations complete. Next single job control3, paired seed 63037,
verified common control minimization, 50 ps heat + 1 ns NPT + 10 ps restart;
3 h hard cap, 100 ps checkpoints, completion-triggered review. Service
`cpd-anti-cube-prep-control-3-v6`, evidence `cpd-anti-cube-prep-control-3-service-v6`.
On completion audit control3, then review all six preparations together and
freeze exact restart endpoints. Prepare/test a versioned validation runner
using final dynamic composition, full XSC, unchanged gates and observables,
100 ps checkpoints and 1 ns endpoints. Estimate full per-job native plus
analysis runtime and margin below 16 h before admitting only anti1 validation.
Each later validation requires a scientific/performance/necessity audit of its
predecessor. No automatic next job, cloud, parameter changes or promotion.
Structural interpretation, provenance correction and portable package remain.

**Control replica 2 audited; anti replica 3 admitted — 2026-10-06.**
Wake bc8f222b-afcc-4e23-9aa7-3251ff359c4d acknowledged; delivery verification
links audit/review in `cpd-anti-cube-prep-control-2-service-v6`. Return 0;
4070.84 s (67.85 min). Audit verified 205 input pins, five new native jobs,
existing static comparisons, all 555 DCD cells, ten complete 100 ps restart
sets, restart/endpoint potentials, nine stratified frames and three binary
endpoints. All 558 worker geometry records pass; sampled chemistry replay
is not independent full-frame validation or minimum/equilibrium certification.

NPT minimum image 37.855 A. Late 500 ps: 299.247 K, +6.504 bar, density
1.023082 g/cm3, added NaCl 149.863 mM; density half-change +0.0000450 g/cm3.
Pressure blocks range -8.020 to +20.375 bar. Endpoint/restart void witnesses
3.280/3.124 A; transient NPT maximum 3.818 A subsides, with late values near
3.2 A. Bulk properties remain consistent with the first three preparations;
no former sustained-tension/large-cavity pattern. Short blocks do not prove
pressure convergence. NPT 1 ns took 3584.769 s plus 275.913 s analysis; GPU
mean 97.22%. Projected 10 ns ~9.96 native h + ~0.77 analysis h before margin.
Retain qualified method and p4; no new evidence warrants a tuning detour.

Four of six preparations complete. Next single job anti3, paired seed 63037,
using verified common anti minimization, 50 ps heat + 1 ns NPT + 10 ps restart;
3 h hard cap, 100 ps checkpoints, completion-triggered review. Service
`cpd-anti-cube-prep-anti-3-v6`, evidence `cpd-anti-cube-prep-anti-3-service-v6`.
Audit before control3 with the same paired seed. After all six reviews, freeze
startup endpoints and prepare/review the bounded validation runner and budget
before the first fresh 10 ns job. No cloud, automatic next job, duplicate static
work or readiness promotion. Structural interpretation, provenance correction
and portable package remain pending.

**Anti replica 2 audited; control replica 2 admitted — 2026-10-06.**
Wake1873de87-51f0-43b3-9294-9c9b18b2c9eb acknowledged; delivery verification
links native audit and review in`cpd-anti-cube-prep-anti-2-service-v6`.
Return0;4056.94s (67.62min). Audit verified203 input pins, five new native jobs,
replayed existing exact-system static comparisons, all555 DCD cells, ten complete
100ps restart sets, restart/endpoint potentials, nine stratified frames and three
binary endpoints.558 worker geometry records pass; not independent full-frame
chemistry or equilibrium/minimum certification.

NPT minimum image38.071A; endpoint/restart void witnesses3.303/3.243A after
heating transient4.475A. Late500ps299.160K,+0.292bar,density1.023027g/cm3,
149.855mM addedNaCl; density half-change+0.0002126g/cm3; pressure50ps blocks
-12.750..+7.288bar. No former sustained-tension/large-cavity pattern. NPT1ns
3570.643s (24.197ns/day), consistent with preceding runs; GPU mean97.72%.
Measured1ns analysis275.993s. Ten ns projects~9.92nativeh+~0.77analysis h at
this cadence, before margin; re-evaluate admission after remaining preparations.
Retain method/p4 because no new evidence supports a tuning detour.

Three of six preparations complete. Next single job control2, pairedseed52027,
verified common control minimization,50psheat+1nsNPT+10psrestart,3h hard cap and
100ps checkpoints. Service`cpd-anti-cube-prep-control-2-v6`, evidence
`cpd-anti-cube-prep-control-2-service-v6`. Completion review required before anti3,
then control3 (pairedseed63037). Use unchanged launcher and frozen worker;
no duplicate static/minimization, automatic next job, cloud spending or readiness
promotion. All six startup reviews precede fresh10ns validation, structural
interpretation, provenance correction and portable packaging.

**Control replica 1 audited; anti replica 2 admitted — 2026-10-06.**
Wake c99d5f24-9bce-4fe1-8a1d-900783c27519 acknowledged and linked to review/audit
in `cpd-anti-cube-prep-control-1-service-v6`. Return0;4096.10s (68.27min) total.
Independent audit verified198 input pins, eight native jobs, static forces/energies,
all555 DCD cells, ten complete100ps restart sets, restart/endpoint potentials,
nine stratified frames and three binary endpoints.558 worker geometry records
pass; this is not independent full-frame chemistry replay.

Control NPT minimum image37.507A; endpoint/restart void witnesses3.280/3.308A
(the heating endpoint transient was4.590A). Late500ps299.205K,+3.818bar,
density1.023005g/cm3,149.851mM addedNaCl; density half-change-0.0000876g/cm3.
50ps pressure blocks -5.373..+14.172bar. Bulk density and salt closely match anti1;
no sustained-tension/large-cavity pattern, but no equilibrium certification.
NPT1ns3590.166s,24.066ns/day,0.22% slower than anti1; GPU mean97.38%.
Current10ns native estimate9.97h before analysis/margin, within16h policy.
Retain p4,cell and timestep; no evidence for a new tuning experiment. Heating
summary uses audited unique-timestep rows; frozen historical summary preserved.

Two of six matched preparations complete. Next single job anti2, pairedseed52027:
reuse verified common anti minimization,50psheat+1nsNPT+10psrestart; expected
~1–1.5h, hard3h cap,100ps checkpoints. Service`cpd-anti-cube-prep-anti-2-v6`,
evidence`cpd-anti-cube-prep-anti-2-service-v6`. On wake audit before control2;
then anti3/control3 with pairedseed63037 individually. No duplicate static or
minimization jobs, parameter changes, cloud use or validation launch. All six
preparations still require review before fresh10ns validations. Readiness remains
false; final structural interpretation, provenance and package remain pending.

**Anti replica 1 audited; matched control 1 admitted — 2026-10-06.**
Completion wake 7328e6be-6b6e-4a11-bd3c-33714a53cf99 acknowledged and linked to
native audit/review in `cpd-anti-cube-prep-anti-1-service-v6`. Native return 0;
4086.72 s (68.11 min) total. Independent replay verified 194 input pins, eight
native jobs, exact final-system static force/energy comparison, all 555 DCD cells,
ten complete 100 ps checkpoint sets, restart/endpoint potentials, nine stratified
frames and three binary endpoints. Worker 558 geometry records pass; sampled
replay is not an independent full-frame chemistry audit.

NPT minimum saved image clearance 31.417 A; endpoint/restart void witnesses
3.206/3.215 A. Late500ps: 299.120 K, -2.753 bar, density1.022951 g/cm3,
149.843 mM added NaCl; density half-change -0.0001955 g/cm3. Pressure blocks
fluctuate -21.32 to +10.07 bar; no prior sustained-tension/large-cavity pattern.
These support proceeding, not equilibrium or full NAMD readiness.

NPT1ns took3582.307s (~24.12ns/day), 11% slower than prior3227.944s reference.
GPU mean97.19%; p4 retained because prior p8 gain<1%. Current10ns estimate
9.95nativeh; add runtime margin and analysis before admitting validation. No
new core/timestep/cell experiment justified now; control supplies the next matched
performance measurement. Frozen worker heat summary duplicated nine run-boundary
energy rows; audited statistics use unique timesteps and the complete50ps.
Original reports retained; NPT/restart summaries unaffected. Auditor command:
`NADOC_REPO_ROOT=/home/jojo/Work/NADOC OPENBLAS_NUM_THREADS=1 .venv/bin/python experiments/cpd_anti_additive/audit_cube_preparation_v6.py --plan .development-artifacts/cpd-anti-gpu-cube-context-v5/preparation_anti_1_v6.json`.

Next single job: control replica1, pairedseed41017, same final composition/method,
static checks + minimization +50psheat +1nsNPT +10psrestart; 3h cap, ~1–1.5h
expected,100ps checkpoints. Launcher`launch_cube_preparation_v6.py` requires
hash-verified passed audits and affirmative completion reviews for every earlier
preparation and rejects duplicate admission/outputs. Frozen worker and original
inputs reused; historical failed campaigns remain held. Service
`cpd-anti-cube-prep-control-1-v6`, evidence`cpd-anti-cube-prep-control-1-service-v6`.
On completion audit control before admitting anti2 (pairedseed52027), then
control2/anti3/control3 individually. No full validation yet.

**Sequential resumption authorized — 2026-10-06.**
The user resumed CPD readiness work and authorized individual restartable jobs
strictly below 16 hours, with longer processes split into chunks and audits of
progress, necessity, alternatives, and speed between jobs. This supersedes the
expired aggregate time caps and the pending 84-hour budget question below; it
is not a reset of scientific gates or historical evidence. No further budget
confirmation is needed for work within this instruction. Historical holds on
failed campaigns remain; only the new final-composition path is admitted.

First job: final cubic anti replica 1 preparation, seed 41017, at
`cpd-anti-gpu-cube-context-v5`, using versioned worker
`experiments/cpd_anti_additive/gpu_cube_preparation_v6.py` and frozen v5 engine.
265477 atoms, 87289 waters, 237 salt pairs, mass 1617952.3015 Da; dynamic assembly
values replace provisional diagnostic composition. Exact-system static CPU/GPU
energy and force checks, 1000 minimization steps, 50 ps heating, 1 ns NPT, and
10 ps restart test. Expected about 1–1.5 hours including analysis; hard cap
3 hours. Four CPU cores, ordinary masses, 2 fs, force switch, PME 144 cubed.
Unique complete restart sets every 100 ps, full XSC, all saved-frame chemistry,
water and >12 A image gates retained. No automatic retry or next replica.

Service `cpd-anti-cube-prep-anti-1-v6`; service evidence directory
`cpd-anti-cube-prep-anti-1-service-v6`. Separate event-driven completion watcher
queues a review to this resumed thread. On completion acknowledge the wake,
verify native outputs and independently replay representative checks, review
physical blocks/voids/salt/performance and usefulness before admitting control 1
preparation. Then prepare anti2/control2/anti3/control3 individually with paired
seeds 52027/63037, checking frozen initial inputs and each prior review. All six
startups need review before validation. Prepare a versioned validation runner
for six sequential 10 ns runs (historical estimate ~9 native hours each), retaining
1 ns endpoints and intermediate audits; enforce <16-hour process limits. If
measured runtime exceeds that, split further, preserving complete checkpoint
state and unchanged scientific gates. Do not invoke obsolete v4 deadline guards.

Authorization and first job plan are retained as
`sequential_authorization_20261006.json` and `preparation_anti_1_v6.json` in the
final cube root. Failures and original clocks remain intact. Stop/restart uses
a newly admitted output directory after auditing the last complete checkpoint;
the worker refuses to overwrite existing native stage directories. Final
structural interpretation, provenance errata and portable package still remain.
Current scope is preliminary cis-anti-I and matched controls; no general CPD,
equilibrium, minimum-certification or production-readiness claim.

Validation before launch: 13 focused tests passed for admission expiry/caps/input
integrity, final composition/PME/checkpoint settings, native logs and restart XSC.

**Cube qualification audited; final inputs ready, replacement-budget decision pending — 2026-10-05.**
Wakef3cee3ce-259c-46c8-9793-5788fb5013cb ACKed. Service returned0; independent
`audit_gpu_cube_diagnostic_v5.py` verified508inputpins,22nativejobs, staticforce/
energy comparisons,1140DCDcells,23complete100psrestartsets and endpoint/restart
potentials. Worker1149geometryrecords pass; independent27stratifiedframes and
9binaryendpoints pass (not independentall-framechemistry replay). Native resident,
force-switch andpiston states verified. Evidence `cpd-anti-gpu-cube-diagnostic-v5/
startup_native_audit.json`, `qualification_review.json`, archivedauditorsource;
service completion_delivery_verified links ACK/review/audit. Priorfailures remain.

Late500ps anti/control: temperature299.210/299.137K,pressure+1.664/+1.486bar,
density1.023279/1.023342g/cm3,volume2625955.29/2625792.88A3; densityhalfchanges
-0.0001354/-0.0000160g/cm3. FinalNPTcube edges137.922/137.887A; endpointimage
48.998/47.372A. NPT/restartendpointvoidwitnesses3.115–3.346A; noformerlargecavities.
Supports cubeNPT method, not equilibrium/futureconformation/fullcontext readiness.

265433atom p4benchmark26.896late ns/day,24.204wallns/atom/step (~8%betterperatom
thansmallbox26.289). p2=26.558,p8=27.012ns/day; <1%benefitfrom8,retain4 byfixedrule.
p4meanGPUutil98.09%,power345.41W,clock1830MHz,temp72–81C. The added walltime is
systemsize, not observedCPUcorebottleneck. Full1ns timings3216.021/3227.944s.

Provisional248pairs equilibrated to156.824/156.834mM addedNaCl. PooledV2625874.08862A3
selects237pairs bypreregisterednearest150mMrule. STATIC finalprepared root
`cpd-anti-gpu-cube-context-v5`; preparer`prepare_gpu_cube_context_v5.py`.
265477atoms,87289waters,330Na/237Cl including93neutralizers, mass1617952.3015Da.
Predicted~149.873mM atcalibrationvolume; actualnewNPTconcentration stillpending.
Originalsoluteseeds andsameemptypacking reused, notdiagnostictrajectories.
Input/outputpins,neutrality,identity/mass,sharedsolvent andunchangedforcefield
bytes independentlyverified. ExactfinalNAMDstartup must stillqualifynewcomposition.

Concrete machineproposal `docs/cpd_cube_replacement_proposal_20261005.json` is
AWAITING BUDGET DECISION, NOT ACTIVATED. Existingcontextdeadline1791281108.8733842
andoveralldeadline1791339464.4342022 retain18.16h/34.37h atproposal. Worstmeasured
1ns adjustedfortinyatomcountchange:8.968nativeh per10ns; six=53.808h. Sixfresh
50psheat+1nsNPT+10psrestart preparations=5.704nativeh.25%native margin+3hcontext
analysis+6hpackage=>83.390h total. Propose NEW84h replacementwindow fromlaunch,
78hcontext and6hpackage, explicitly supersedingtimecaps onlyafterapproval; retain
originalclockledger andallscientificcriteria. Same six3anti/3control10ns, no credit
fromfailedorprovisionaldiagnostic runs; sequential, Archive,100psrestartsets,
completionwakes andreviewaftereach10ns, no cloud/polling/longproduction.

Asyncapproval requested: approve84hreplacementwindow orstopatcurrentbudget.
Reason: fixedcontract forbidsautomaticcapextensions; sixnative runsalone cannot
fitremaining34hoverall. No newfullcampaign ordeadline reset whileanswerpending.
Nextafterapproval: freezeversioned finalcube worker/launcher withdynamicN/NW/MASS,
PME144cubed, newapproved78hcontext/84htotal clocks andpinnedstaticinputs; exact
final-system staticforces/energies,6matchedstartups andnativechecks, then sequential
anti1/control1/anti2/control2/anti3/control3, reviewingphysical/structural/performance
andbudget aftereach. Do NOT reusev4hardcoded70624dimensionsor48hauthorize guard,
orv5diagnostic248pairs/mass1618198.80017 forfinal237pairs. Keep sourceversions.
Finalstructuralinterpretation, v3fitmetadata/provenanceerrata andportablepackage
remain. No present simulation-ready,minimization/equilibrium oracademicacceptanceclaim.


**Image audit complete; rotation-aware cube diagnostic launched — 2026-10-05.**
Wake218be842-603f-4bde-a5f8-a05ded8e75c1 ACKed and completion_delivery_verified
written in `cpd-anti-gpu-npt-anti-1-failure-audit-service-v4`. Audit all909 saved/
finalgeometries: exactly2imagefailures, segment9frames80/85 at11.761505/11.825183A
acrossy; ZERO other registeredchemical/water failures. All9native segments,
restart/endpointenergies and90complete100pscheckpoint sets verified; original
validation remains FAILED. Missingsegment9reference was staticrun0, no extraMD.
Largest observedsolute diameter112.571640A; anyshortestlatticevector>124.571640A
bounds recordedconformation imageclearance>12A underarbitraryrigidrotation.
This cannotbound futureconformationalexpansion or boxcontraction. Virtualy+20 and
xy+20 minimum23.550548A overrecordedframes wouldsolvepastcontacts, but leave short
axes/rotationalvulnerability. Do not repeat incrementalaxispatches aslong-termproof.

Prepared originalsolute seeds in140A cube, centered bycommontranslation
[47.535,36.281,13.6185]A; nofailedcoordinates reused. Newroot
`cpd-anti-gpu-cube-diagnostic-v5`, preparer`prepare_gpu_cube_diagnostic_v5.py`.
265,433atoms,87,267waters,341Na/248Cl, mass1618198.80017Da eachcase. Salt248pairs
is PROVISIONAL nearest150mM ininitialcube (150.078mM), notequilibrated150mM.
Afterdiagnostic derive finalcommonnearest150mM count frompooledlate500psvolume,
then prepare/qualify finalcomposition iffullreplacementadmitted. Counterions93
unchanged; allsolute/forcefieldidentity/masses/neutrality/coverage/seed checks pass.
Inputslocked; staticNAMDmethodcomparison shows onlypaths and requiredPMEX/Y
72/88->144 differ (Z144 unchanged), keeping~1Agridresolution. NPTbehavior remains
300K/1.01325bar,isotropicforce-switch10–12A,ordinarymasses/2fs,fullXSC.
At5%linearcontraction cube133A still exceeds recordedDmax by20.43A; unchanged12A
framegate remains active, no guarantee onfutureflexibility.

RUNNING `cpd-anti-gpu-cube-diagnostic-service-v5`, unitwithout-service suffix,
tokenf3cee3ce-259c-46c8-9793-5788fb5013cb. Supervisor running/watcher armed atlaunch.
Frozenworker `gpu_cube_diagnostic_v5.py`/archive`diagnostic_worker.py` andplan
`diagnostic_plan.json`. Scope: twooriginalseed cases, onepairedseed41017,
commonminimization+50psheat+1nsNPT+10psrestart EACH, then3x100pssamecheckpoint
p4/p2/p8 timingbranches. Diagnostics only; nofresh10nslaunch orvalidationcredit.
GPUresidentMD only; staticCPUreferences retained. Alljobssequential; Archive
trajectories/logs/telemetry andunique100psrestartsets; no modelpolling/cloud.
3hcap and2.5hwatcherestimate fit existing48hcontextdeadline1791281108.8733842;
original72hoverall1791339464.4342022 preserved. No fullreplacementbudget activated.

Onwake ACK/audit actualnative,exactnewPSFforces/energies/geometry/checkpoints,
NPTcell/physical/salt evidence and GPUthroughput. Measurefullreplacementcost:
freshsix10ns plusremainingfresh6x1nspreparation, margin,structuralanalysis and
package. Thislargercell may exceedremainingcontext ANDoverallbudget; do notclaim
itfits orsilentlyextendoriginalledgers. Finish a concrete measuredproposal before
requestinganynecessarybudgetdecision. User permits sequential evidence-based
pivots andwants endpointcomplete, butscientificcriteria/failedrecords never reset.
Finalendpoint still sixmatched10ns+structuralreview+provenanceerrata+portablepackage;
no currentreadiness,equilibrium,minimumcertification or longproduction claim.


**Anti1 stopped on fixed image-clearance gate; failure audit running — 2026-10-05.**
Failedwake40f05a7b-05ac-4150-a569-9fd1bd25fa85 ACKed in requested service.
Native NAMD completed9x1ns segments normally; worker acceptedsegments1–8 then
stopped while reviewingsegment9 frame80 (validation8.81ns,step4935000).
Independent witness reconstruction gives11.7615049468A imageclearance<unchanged12A.
Witness indices1433/2695, lattice shift(0,-1,0), cell63.111640686/84.989305996/
129.044983095A; solutespans36.5308/84.9094/93.3142A; diameter102.7937A atwitness.
The approach is acrossy, notthepreviousz failure. Witness stereo/bonds/contacts,
waterOO2.4484A andOHstorage-residual0pass. Unalignedconstructiondisplacement is
not the MDchemistrygate. Segment9 ended5030000 withnativeexit0, terminal log and
savedcoordinates/velocities/XSC; this is notanenginecrash or optimizer/minimumissue.
Originalfailure andallnative/checkpoint/trajectory evidence remain untouched.
Do notcount8passedsegmentsor9nativecompletedns as full10nsvalidation success.

Late native rates segments1–9:93.126,92.402,93.057,93.325,93.222,92.871,92.763,
92.789,91.750ns/day, close tomatched93.073benchmark. No performancepivot indicated.
Late500ps pressures acrosssegments -8.683to16.980bar,temperature299.093–299.452K;
no evidence fromthesevalues oftheformerbulkpressurefailure. Fullphysical replay
remains underway; do notinfer allframephysicalpass fromaverages.

RUNNING failureaudit `cpd-anti-gpu-npt-anti-1-failure-audit-service-v4`, unitwithout
-service suffix; completiontoken218be842-603f-4bde-a5f8-a05ded8e75c1.
Worker `audit_npt_image_failure_v4.py`, frozenplan/source/archive at
`cpd-anti-gpu-npt-anti-1-failure-audit-v4`. Supervisor/watcher armed.
Scope: all909saved/finalgeometries, native modes/cadence/restart/endpointenergies,
90periodiccheckpoints, actualcells, physicalstats/voids/timing; missingsegment9
endpointreference is staticrun0 only. No newdynamics, no subsequentreplica,
no duplicatejobs/cloud/polling.15min estimate,1hcap withinexistingcontextdeadline.
Completes originalservice deliveryverifiedreceipt onlyafter fullaudit.

Virtualy+20 andxy+20 cellchecks plus per-frameconvexhull solutediameter characterize
why earlierelongatedbox qualification didnotensure rotationalclearance.
For recordedconformations anyshortestlatticevector>Dmax+12A yieldsa rotation-
independent lower bound on pairimageclearance; itdoesnotboundfutureconformational
expansion or NPTcontraction. Prefer a defensible rotation-aware cell design over
repeatedminimalaxispatches. Virtualgeometry isnotnewsolvation/validation.
Onwake auditfullresults, structuralbehavior and newnativecost/budget feasibility
beforechoosinga versionedcorrection. No thresholdrelaxation/refit/failureexclusion.
User permits evidence-basedpivots; scientificendpoint remains sixfreshmatched10ns,
structuralreview,provenancecorrections,portablepackage. Originalrecords/deadlines
preserved; do notsilentlyclaim replacementcampaign fitswithout costingit.


**Startup audited; first fresh10ns validation running — 2026-10-05.**
Wake8718a5bd-0154-4b5a-909e-f96371f84403 complete ACKed and delivery verification
written in `cpd-anti-gpu-npt-startup-service-v4`. Independent script
`audit_gpu_npt_startup_v4.py` produced `cpd-anti-gpu-npt-context-v4/startup_native_audit.json`:
470inputpins,42nativejobs,2case staticforce/energy comparisons,3390DCDcells,
allregular/finalcoordinate/cell identities,66complete100psrestartsets verified.
Worker3411geometryrecords allpass; independent63stratifiedframes+21binaryendpoints
pass. This is not an independent all-frame chemistry replay or minimum proof.
Native GPUresident/force-switch/piston modes and endpoint/restart energies verified.

Allsix late500ps preparations: rawpressure -5.139 to+10.322bar,temperature
299.081–299.349K,density1.051364–1.051672g/cm3,addedNaCl150.620–150.664mM.
Late250ps-half densitychanges -0.000379 to+0.000318g/cm3. Independent2Agrid
endpointvoidwitnesses: heating5.362–6.922A, subsequentNPT3.032–3.236A,
restart2.897–3.183A. Thus transientunrelaxedheatingvoids were present, explicitly
retained and resolved by the NPTpreparation; do not claim absence atallstages.
No return offormer17A+voids or sustainedlargeNPTtension. These observations support
starting preliminary structural validation; do not certify equilibrium or readiness.

Same70,624atom force-switchNPT benchmarks: late throughput p4=93.073,p2=92.864,
p8=93.133ns/day. Retain+p4 byprospective>5%improvementrule;8coresyieldno meaningfulgain.
p4=26.289ns wall/atom/step at2fs;meanGPUutil96.67%,power340.96W,SMclock1920MHz,
temperature62–80C. No observedCPUcorecountbottleneck. Benchmarks are local/matched,
not auniversalperatom NAMDtarget or comparableto4fs/HMR/differentGPU benchmarks.
These benchmarkbranches receive no validationcredit.

`startup_admission.json` and `validation_plan.json` are frozen and hash-pinned.
Measured925.430s/ns ->expected11568s per10ns (25%native margin); sixremainingruns
plus3hfinalcontextreview reserve=22.28h versus23.383h remainingatadmission.
Contextdeadline1791281108.8733842 andoverall1791339464.4342022 unchanged.

RUNNING `cpd-anti-gpu-npt-anti-1-service-v4`, unit`cpd-anti-gpu-npt-anti-1-v4`,
completiontoken40f05a7b-05ac-4150-a569-9fd1bd25fa85. Supervisor running and watcher
armed atlaunch. Firstanti1 fromfresh1.06ns startup checkpointstep530000; ten1ns
validationsegments to5530000. OneNAMDprocess atatime, GPUresident+p4/affinity/GPU0;
100psuniquerestartsets andeach1nsendpoint retained onArchive. No modelpolling.
Oncompletion ACK/audit native,physical,structural and throughput evidence; write
`anti/replica-1/validation/completion_review.json` with approved_for_next_run and
pinnedassessment/performance_report onlyifsupported. Then use frozenlauncher
`replica --case control --replica 1`; next orderanti2/control2/anti3/control3.
Recompute remaining complete-budget admission at eachlaunch. User permits pivots
unlesssteeredotherwise; preservefailures andregistermethodchanges. Stillpending
six10ns+structuralreview+fitmetadataerrata+restartablepackage; no readiness,
equilibrium,minimumcertification,cloudspending or longproductionclaim.


**Sequential campaign authorized and startup launched — 2026-10-05.**
User responded to the explicit budget request: "Run until complete", specifying
sequential jobs, regular restart checkpoints, Archive storage, and review/pivot
after each complete NAMD job unless superseded by user steering. This is the new
continuation authority after the prior launch rejection, recorded verbatim in
`cpd-anti-gpu-npt-context-v4/budget_extension_approval.json`. Scoped activation
accepts the pending36->48h context proposal; absolute deadline1791281108.8733842
(2026-10-06 04:05 MDT), original72h deadline1791339464.4342022 unchanged. Preserve
historical contract, failed evidence and oldNVT hold. Correctedv4 only is admitted.

RUNNING service `cpd-anti-gpu-npt-startup-service-v4`, systemd unit
`cpd-anti-gpu-npt-startup-v4`; completion token
`8718a5bd-0154-4b5a-909e-f96371f84403`. Supervisor running and watcher armed at launch.
No other namd3 process was active. Never start duplicate jobs or poll native runs;
wait for completion-triggered review. Startup qualifies final70,624atom systems,
six50psheat+1nsNPT+10psrestart preparations, then200ps core tests at4/2/8 sequentially.
Three-hour startup cap; review expected in about2–3h, not a claim of completion.

All native jobs are blocking/sequential and all simulation data live under the
Archive root. Added `restartsave yes`, `restartname checkpoint`, `restartfreq50000`:
unique complete coordinate/velocity/XSC sets every100ps, plus explicit stage/1ns
endpoint restarts. Source behavior confirmed in exact NAMD Output.C/Controller.C.
Review verifies every regular set's atom counts, finiteness, cell/step, hashes,
and coordinate/cell agreement with saved frames. No old restart sets overwritten.
11 scoped tests pass, including missing checkpoint component rejection. Worker,
launcher, input pins and plan frozen in newroot; do not edit these live sources.

On startup wake ACK and verify actual native/static/checkpoint/trajectory,
physical and performance evidence. Freeze matched validation plan and measured
remaining-budget admission, then start anti1 10ns. Run order remains anti1,
control1, anti2, control2, anti3, control3, with one service/completion wake per10ns.
Each contains1ns restart/native/geometry audits; each complete10ns gets physical,
structural and throughput review before nextlaunch. Compare late ns/day and
walltime/atom/step against matched GPUresident benchmark, inspect GPU telemetry
and review/I/O overhead, and investigate>20% slowdown. That flag never relaxes a
scientific threshold. User permits evidence-based pivots without repeated routine
permission requests; preserve failed states and register any method changes first.
The final endpoint remains allsix10ns, structural review, provenance corrections
and restartable package. No current simulation-ready/minimum certification,
no cloud, no launch of long production. User review requests steer ongoing work.


**Six-run continuation prepared; explicit budget approval requested after launch rejection — 2026-10-05.**
User instructed: "Proceed with the six fresh 10ns runs. Review after each to make
sure the simulation is running as fast per atom as we would normally get with NAMD."
The six runs and per-run performance reviews are authorized. The attempted startup
launch was rejected BEFORE execution by automatic approval review: it judged this
instruction insufficiently explicit to approve the 36-to-48-hour context extension,
which the original contract prohibits activating automatically. No activation,
startup service, or new native run was created. Explicit approval was requested
for 48 hours, ending 2026-10-06 04:05 MDT (10:05 UTC); overall72h remains unchanged.
Do not retry indirectly or treat this rejection as a simulation failure.

Prepared workers `gpu_npt_context_v4.py` and `launch_gpu_npt_context_v4.py`:
- Exact new-system CPU static reference / GPU-resident force and energy checks;
  common minimization, six matched50ps heat +1nsNPT +10psrestart preparations.
- Full XSC strain, fixed PME72/88/144, force switching10–12A, ordinary masses/2fs,
  original chemistry/water/image and native energy tolerances. Actual per-frame
  cells, raw50ps physical blocks, updated439755.32252Da mass, salt/void review.
- Bounded200ps benchmarks at+p4/+p2/+p8, CPU affinity, same NPT method/checkpoint.
  Retain+p4 unless another improves late median step time by>5%. These diagnostic
  branches receive no validation credit. NAMD recommends measuring a small core
  count for resident mode: https://www.ks.uiuc.edu/Research/namd/3.0/ug/node102.html
- One watched service per complete10ns replica, order anti1/control1/anti2/control2/
  anti3/control3. Retain ten1ns checkpoint/native/geometry reviews within each run.
  No next replica before its predecessor's physical/structural/performance review.
- Report native and late ns/day, seconds/step and wall ns/atom/step, GPU telemetry,
  and nontrajectory overhead. >20% slowdown against matched benchmark flags a
  performance investigation; it is not a scientific acceptance tolerance. Keep
  PME/timestep/ensemble/hardware distinctions explicit in external comparisons.

Scoped tests:10 passed (NPT cell/strain config, timing normalization/transient
exclusion, invalidXSC, deadline/hold enforcement, native parser). Config comparison
against qualified force-switch NPT shows only expected paths/seeds/counters,
run/output commands and added timing differ. GPU driver works outside filesystem
sandbox; no namd3 process was active at preflight. No cloud spending.

Launcher now requires `cpd-anti-gpu-npt-context-v4/budget_extension_approval.json`
with explicit_user_approval=true, context_max_hours=48,
context_deadline_epoch=1791281108.8733842, overall_deadline_epoch=1791339464.4342022,
and verbatim user_instruction. Create ONLY after explicit approval; preserve
original contract/proposal/static preparation records. A scoped activation leaves
legacy failed NVT jobs held. Any later hold change stops v4 stages.
After approval recheck time; startup requires24h remaining in proposed contextcap.
On startup wake review physical/timing data, then create validation_plan.json with
pinned inputs, startup_admission(approved_for_validation), context_deadline_epoch,
run_order, paired_seeds, selected cores, reference_late_seconds_per_step,
expected_seconds_per_10ns, final_context_review_reserve_seconds (preserve planned
analysis reserve), and observables. Budget admission must cover all remaining
runs plus final review; do not reset clocks. Per-run completion_review.json must
pin assessment/performance_report and explicitly approve next run. No readiness
or minimum certification until the remaining scientific endpoint is satisfied.


**Force-switch qualification reviewed; fresh inputs prepared, budget decision pending — 2026-10-05.**
Wake `3e1b7e51-2fad-4775-951b-426f975b8af8` acknowledged in the requested service.
Both cases completed 1 ns NPT plus a 10 ps NPT restart. Independent native audit
verified 293 input pins, four static comparisons, all four dynamic stages,
1,010 DCD cells against XST/native volumes, complete binary/XSC checkpoints,
and restart/endpoint energy agreement within the unchanged limits. Maximum
restart error was 0.0245 kcal/mol; endpoint error was 0.1568 kcal/mol.
GPU-resident execution remained active. The CUDA force-table warning is expected
for force switching, as confirmed in the exact local NAMD source and native logs.

The worker checked 1,014 saved/final geometries. Independent replay checked four
binary endpoints and 20 stratified DCD frames; do not describe this as an
independent all-frame chemistry replay. Endpoint void radii on a 1.5 A grid were
3.067–3.180 A, with continuous-space upper bounds below 4.479 A; image clearances
were 32.32–36.90 A. No former large cavities were found in these checks.
Registered late-500-ps raw means were anti/control pressure -1.082/+16.524 bar,
temperature 299.220/299.148 K, and total density 1.052046/1.052268 g/cm3.
Density changes between the two 250 ps halves were +0.000058/-0.000250 g/cm3.
This supports the corrected force-switch/NPT method for fresh validation;
it does not establish equilibrium, CPD transferability, or long-term readiness.
No favorable pressure/density threshold was invented after observing these data.

Append-only evidence in `cpd-anti-gpu-force-switch-qualification-v3` includes
`qualification_review_20261005.json`, three independent audit scripts/results,
and `plan_metadata_erratum_20261005.json`. The latter corrects an inherited
"100 ps NVT probe" phrase: the registered steps and actual qualification were
only 1 ns NPT plus 10 ps NPT restart per case. Frozen plans and failures remain.
The service's `completion_delivery_verified.json` links the reviewed evidence.

Static preparation completed at `cpd-anti-gpu-npt-context-v4` using
`prepare_gpu_npt_context_v4.py`. Pooled late force-switch volume 694211.0844 A3
selects 63 added NaCl pairs by the previously proposed nearest-integer rule:
156 Na including 93 neutralizers, 63 Cl, 22,454 waters, 70,624 total atoms.
Predicted added NaCl at the calibration volume is 150.695 mM; initial-box
concentration is 138.793 mM. Actual new NPT concentration remains unmeasured;
neither quantity denotes total ionic strength. Independent assembly audit
verified all 32 output and 33 input pins, original translated solute seeds,
unchanged topology/forcefields/masses, neutrality, and identical shared solvent.
Use the NEW system mass 439755.32252 Da for later density calculations.
The OpenMM XML establishes parameter coverage only; exact new-system NAMD
force-switch startup/restart checks still remain. No new native runs were launched.

Measured force-switch NPT speed is 898.138 seconds/ns: fresh 60 ns alone needs
14.969 hours, already exceeding the remaining original context budget before
preparation, review, or reserve. The concrete 36-to-48-hour context proposal in
`docs/cpd_corrected_context_proposal_20261005.json` remains NOT APPROVED.
Keep the original deadline 1791237908.8733842 and production hold TRUE; automatic
wake messages are not approval of a cap extension. No full validation launch,
deadline reset, partial-duration credit, parameter refit, or readiness promotion.
Once explicitly approved, recheck remaining time against the proposed absolute
deadline before admission. Pending scientific endpoint remains six fresh matched
10 ns runs, structural review, metadata crosswalk, and a restartable package.


**NPT diagnostic complete; force-switch qualification and budget decision — 2026-10-05.**
Wake d14e0c2d-3d0a-4057-ac30-f3d2d05a13f5 ACKed. Independent native audit checked
all input hashes, four staticCPU/resident comparisons, sixstage step/cadence,
variablecells/checkpoints, finalDCD/binarycoordinates, restart/endpointenergies.
Independent1.5Aperiodicgrid endpointvoidradii3.09–3.46A; continuum bounds<4.76A;
30stratifiedframes also checked independently. Full1116geometry native replay is
first phase of next watched service and writes startupservice deliveryreceipt.
No numerical/chemical issue found; physicalinterpretation remains separate.

Last500psNPT rawmeanpressure anti-3.097/control+10.483bar,temperature298.94/299.21K,
totaldensity1.05636/1.05672g/cm3. Volumescontract8.264/8.296%; no sampledoldlarge
cavities, clearance>26.87A. Supportspressure/densityequilibration correction, not
exclusivecausality or equilibriumcertification. NVT100psprobe pressures-59.6/-72.1bar
atinstantaneousendpointvolumes do not qualifyambientNVT. NPTselectedforproposed
correctedcontextcampaign. Original68saltpairsbecome~0.1633M aftercontraction;
finalfreshpreparation must recompute nearest150mM commonioncount from calibration
volume and discloseactualconcentrations, not claim original68pairsremain150mM.

Force-switch chosen prospectively fromCHARMMparameterVFSWITCH provenance and
Lee2016CHARMM-GUI recommendation. Staticon/offdifference+837kcal and+77bar isreal
Hamiltonianchange, not provenoldcavitycause. New `ensemble_force_switch_v3.py`
changes ONLYvdwForceSwitchingoff->on for dynamics; existingpassingstaticONresident
reference used forinitialpotential. Original110pssetupseeds reused diagnostically;
2cases x(1nsNPT+10psNPTrestart), no repeatedNVTprobe or productioncredit.
Active service `cpd-anti-gpu-force-switch-qualification-service-v3`, artifacts
`cpd-anti-gpu-force-switch-qualification-v3`. Fullpriorframeaudit precedes dynamics.
One-hour cap also boundedbyoriginaldiagnostic2hdeadline and originalcontextclock;
productionpause remainsTRUE. Noautomaticretry,productionlaunch,budgetextension,
refit or tolerancerelaxation. Completionwatcher, no modelpolling/cloudspending.

MeasuredNPT1ns899.66saverage ->fresh60ns14.994h native; preparation+analysis+reserve
cannotfit~15.8h remainingoriginalcontextbudget. Concreteproposal recorded at
`docs/cpd_corrected_context_proposal_20261005.json`: onecontextcap36->48h extension,
original72h overallcap and6hpackagingcap unchanged; finalforce-switchqualification,
freshmatched3replicaspercondition with1nsNPTpreparation then10nsNPTvalidationeach,
alloriginalgates plusexplicitphysicalreview. Approximately24.6h planned including
margin/analysis/qualification. Userbudgetdecision requested asynchronously and
NOT YET APPROVED. Do notactivate newdeadline orlaunchfull60ns withoutreply.
Currentforce-switchqualification is withinexistingcap and independentofapproval.
At timecapstop/reportincomplete; do not call fewerreplicasorbadNVTstatesready.


**Delayed initial ensemble-diagnostic wake acknowledged — 2026-10-04 MDT.**
Token8d0a8cb7-b2bd-494e-9ba8-5163c172ee1a fromservicev3 is the previously reviewed
static-output/header failure, superseded byr1. ACK andcompletion_delivery_verified
receipt written. Reverified nativeexit0/terminalrun0log, finite70604atomforces,
missingETITLE and parsertrace. No MD ran and forceequivalence was not scored;
retain failedverdict. R1plan retains originaldiagnosticdeadline=startv3+7200s.
No duplicatejob or restart launched; productionhold remainsTRUE. Await r1's
completionwake d14e0c2d-3d0a-4057-ac30-f3d2d05a13f5; do not poll its trajectories
in response to this superseded wake. No readiness/minimum claim.


**Review-hold wake verified; bounded ensemble diagnostic — 2026-10-04 MDT.**
Wake fc8149cf-50af-44a2-93e8-d05e4b4c5dee ACKed. Native service stopped as intended
at the pause assertion before a new segment, not a native crash. All28 completed
segments retained; lastcontrol replica2segment5 ended2555000 with exact native
checkpoint and terminal log verified. Durations anti/control5/5/4ns each. These
remain limited engineering evidence, not physically qualified production.
Original context36h and overall72h clocks remain unchanged; no deadline extension.

Read-only diagnosis: source216waterboxdensity1.00084g/cm3 vs raw rectangular
packing0.972857g/cm3 before solute insertion; commonunionextra exclusiononly70/58
waters versus individualseeds. Strong tension already existed at startup; seeds
had no largevoids. Watercharges/geometry/LJ/salt identity show no gross anomaly.
Packing+unrelaxedNVT is a supported hypothesis, not proven exclusive cause.
Potential-switch versus CHARMMVFSWITCH convention is separately unresolved;
do not silently change Hamiltonian or infer a cause from that discrepancy.

Launched narrowly scoped `cpd-anti-gpu-ensemble-diagnostic-service-v3-r1`, artifacts
`cpd-anti-gpu-ensemble-diagnostic-v3-r1`, workerensemble_diagnostic_v3_r1.py.
Production pause remainsTRUE; separate diagnostic authority/plan is recorded,
not an automatic removal of scientific hold. Two cases from untouchedreplica1
110pssetupstates (verified no cavities), each1nsNPT+10psNPTrestart+100psNVTprobe.
GPUresident/cycle10/+p4/GPU0,2fs,300K unchanged; isotropicLangevinpiston1.01325bar,
period200fs/decay100fs,useGroupPressureyes. Preserve fullXSC strain state; fixed
PMEgrid72/88/144. No newrestraints or parameterfit. Static samecoordinateforce-
switch off/on nativeCPUreference vsresident checks first; dynamicsretainoff to
isolateensemble. Force-switchdecision still required beforeproduction.

Existingchemical/water/image12Agates retained using actualDCD/XSTcells. Exact
cadence,cell/nativevolume,checkpoint/DCDstorage checks; restart andstaticendpoint
potential comparisons unchanged. Fixedlast500psNPT/50psblocks; every2psrawpressure
andtemperature,volume/densitydrift;2Aperiodicgrid nearestANYatom voidwitnesses
at50ps intervals/endpoints. No newfavorablepressure/densitythreshold, noequilibrium
claim. Endstatus remainsphysical_interpretation_pending evenonnativecompletion.
One-hourwatcherestimate;2hdiagnosticcapcountedfrominitialv3launch, notreset.
Noautomatic60nsrelaunch; inspectmethod/physicalevidence andremainingbudget first.

Initial diagnosticv3 failed beforeMD: staticCPUruntime0 returned0 but omitted
ETITLE withenergycadence1000 atstep55000. Frozenfailure/logs retained; queuedwake
8d0a8cb7-b2bd-494e-9ba8-5163c172ee1a is this superseded implementation failure.
R1 changes ONLY staticrun0energycadence500 to obtainnativeheader; samephysics,
limits,durations, and original2hdeadline. Do not duplicate r1whenv3wakearrives.

Append-only interpretation correction: exactGPUresidentController.C uses
TEMPAVG/GPRESSAVG asrollingaveragesofprintedoutputs(defaultwindow20), notevery-step
intervalaverages. Diagnosticblocks therefore use rawTEMP/GPRESSURE at2pscadence.
Earliernegativepressureconclusion remains supported byrawGPRESSURE andcavities;
do not use rollingAVGcolumns as independenttimeblocks. Existingpinnedfilesunchanged.


**Scientific review hold: physical solvent failure, no readiness promotion — user review dated2026-10-04.**
Broad independent gate/method/ensemble reviews found sustained negative pressure
(~-1270bar in several completed1ns segments) and large atom-free solvent cavities.
Reproducible read-only evidence: `docs/cpd_ensemble_review_20261004.json`, generated
by `experiments/cpd_anti_additive/review_ensemble_v3.py`; review conclusions and
primary sources in `docs/cpd_verification_review_20261004.json`.
Anti3segment3 point[46,40,12]A is17.93245A from nearest ANY atom; control1segment1
point[62,14,36]A is17.25714A from nearest atom. Native endpoint potentials match
independent static replay and checkpointcoordinates match exactly. This is a
physical-solvent issue missed by the geometry/native gates, not evidence of the
old corrupted-output syndrome or proof that CPD parameters are wrong.

The existing campaign_pause guard is now TRUE with origin assistant scientific
review, not a fabricated user stop instruction. Separate archive receipt
`cpd-anti-gpu-longbox-v3/physical_ensemble_review_hold.json` preserves prior flag
and evidence. Current segment may finish/checkpoint/review; no next segment may
start. A failed-service wake caused by this guard is EXPECTED; do not remove it
and resume the same NVT campaign automatically. Existing bounded research
permission remains; resume requires documented physical-ensemble correction and
budget/scope review. No deadline reset, threshold relaxation, file deletion,
parameter refit or mutation of pinned workers. No new simulations launched by review.

This corrects a verification omission: prior workflow review requested
thermostat/density checks, while current validation only records temperature range
and never establishes appropriate pressure/density/homogeneous solvent. Fixed NVT
was an engineering test; its numerical passes cannot certify ambient aqueous
structural qualification. Earlier pass flags remain valid only for named checks.
Do not silently broaden10ns stability into physical equilibrium or mechanics.

Most quantitative current gates were preserved, but method/scope DID change:
v1->preliminaryv2, directHFdipoles, updatedprospectivetargets, representation-aware
GPUfixtures, andDCDuncertainty correction. Each must be explicit in publication;
no retrospective old-policy pass. All23oldfitpoints plusnew24th remain included;
water17curvespass currentchargefit, latestfourprospectivepoints pass but test
nearby interpolation on same49atomfragments. BroaderCPD/isoformtransfer unproven.
Stationarity/directionalcurvature is not minimum certification. Correct inherited
least_squares/trf/timestamp/constrained metadata with append-only provenance
crosswalk before packaging; actualv3fit usedfinite-difference/SLSQPminimax.

Next recommendation: one preregistered bounded GPUresidentpressure-equilibration
qualification after existing-outputdiagnosis, then fresh matchedvalidation only
if physicalconditions and originalremainingbudget permit. No arbitrary posthoc
favorablepressure/densitycutoff, no endlesssimulationextensions. Finalstructural
review, applicabilitylimits andportablepackage remain; publicationclaim must be
explicit. Academicacceptance cannot be promised.


**Long-box startup native checks pass; audit-gated validation service launched — 2026-10-04T23:30Z.**
Wake b616813a-a2a8-43dd-8c5f-826857926b81 ACKed in requested service. All6 startup
reports passed; independently parsed native startup/restart/static endpoint logs,
exact checkpoint identities/steps and restart/endpoint energies. All source pins
verify. Native100ps timings anti73.116/71.158/70.504s, control71.008/70.972/70.925s:
full60ns projection11.880h,25%margin+1hanalysis=15.850h; include10minaudit=16.017h.
Remaining original context budget22.585h; original deadline1791237908.8733842.
No extension, refit, failed-state reuse or partial-duration credit.

Active service `cpd-anti-gpu-longbox-validation-service-v3` / unit
`cpd-anti-gpu-longbox-validation-v3` executes `cpd-anti-gpu-longbox-v3/audit_then_validate.py`.
First independently replays672 saved/final frames and2minimized endpoints, verifies
static forces and energies plus native restart checks. Only after complete pass
and fresh measured-budget admission does it write validation_plan.json and run
six10ns GPU-resident validation. Failure at any step exits and wakes; no retries.
Startup service final completion_delivery_verified receipt is written after full
audit; currently native_review_pending_frame_audit.json records verified scope.
One external watcher covers audit and dynamics; no model polling between phases.

New worker `gpu_longbox_validation_v3.py` and frozenvalidation_worker.py import
longbox helper/root (70,604atoms). Config preflight compared all6qualified restart
configs allowing only paths,seeds,counters,cadences; observable6endpoint checkpasses.
GPUresident on,stepspercycle10,no precedingrun0,+p4/GPU0,2fs/ordinarymasses/PME
unchanged.60 roundrobin1ns segments; every10ps+final solute,image>12A,waterOO>2A,
OHbeyondfloat32storage<1e-5A checks; binary checkpoints, restart potential and
per-segment staticCPU-bondedrun0 endpoint replay. No CPU dynamics/cloud spending.
After completion verify actual native/frame/structural evidence, compare registered
observables and shared contact pairs, then package only if acceptable. No current
simulation-ready, equilibrium, or minimum certification; preserve all failures.


**Failure audit complete; long-axis replacement startup running — 2026-10-04T23:15Z.**
Wake21f995b9-7cfc-4f03-9aa7-a8a423ed0619 ACKed; status/native reports, all pinned
inputs and1010 saved/final frame records verified. Ten native segments completed;
all solute/water screens and endpoint/restart energy comparisons pass. Two frames
fail12A image gate, both control replica2 segment2; historical validation remains
failed. Evidence: `cpd-anti-gpu-largebox-failure-audit-v3/assessment.json` and
`admission_review.json`, plus completion_delivery_verified receipt in service.

Selected box64.93x87.438x132.763A (z+20A), conservative minimum23.3643A across
all audited frames. z+40 gives no better global bound; all-axis+20 costs more.
Virtual feasibility does not guarantee future trajectories; existing gates unchanged.
Contact fractions differ between conditions/replicas in partial trajectories;
no final structural or equilibrium conclusion from unequal1–2ns data. Full matched
replica review remains required; no physical minimum certification.

Reprepared original pre-startup seeds (translate10A allaxes), shared solvent,
frozen candidate/ordinary masses unchanged:70,604atoms,22,444waters,161Na/68Cl.
No failed coordinates reused and no partial-duration credit. Unminimized packing
screen preserved; >1.5A oxygen admission only for static/minimization, >2A for
postmin and every MD frame. Same qualified GPUresident/cycle10/+p4/GPU0 settings.
New sources `prepare_gpu_longbox_v3.py`, `gpu_longbox_startup_v3.py`; frozen inputs
and copies in `cpd-anti-gpu-longbox-v3`. Historical pinned modules not edited.

Active service `cpd-anti-gpu-longbox-startup-service-v3`, unit
`cpd-anti-gpu-longbox-startup-v3`. Six50psheat+50pseq+10psrestart tests with
1000step common minima and native static force/endpoint checks; 2h cap,30min
watcher estimate. Supervisor running/watcher armed token
b616813a-a2a8-43dd-8c5f-826857926b81. No polling/duplicate jobs/cloud.
Projected full60ns native12.38h; 25%margin+2hchecks=17.475h versus22.829h remaining
at launch. ORIGINAL context deadline1791237908.8733842 unchanged. Admit full
replacement6x10ns only after startup native audit and measured timing fit budget.
On wake use new ROOT/helper throughout; oldvalidation helper points to failedcell.
Then retain every10ps frame gates,1ns endpoint static replay, structural review,
and restartable package before any readiness claim. No long production authorized.


**GPU-resident validation stopped on control image clearance — 2026-10-04T23:06Z.**
Wake fd8a7c9f-b89b-4063-b393-2b50964b0fb0 failed; requested ACK and verified receipt
written. Ten native1ns segments completed normally, nine passed full segment review.
Control replica2 segment2 first failed at frame42/step770000, validation time1.43ns:
26-image clearance10.45042679A below unchanged12A gate. Independently reproduced
from DCD: periodic z-neighbor contact between D002 ADE26 H62(index2217) and
D002 ADE1 H1'(index1420). Solute spans31.954/54.373/102.781A in box
64.93/87.438/112.763A. Solute stereochemistry/bonds/contacts and water checks pass
at witness; native segment ended normally at1055000, binary checkpoints match.
This is a physical cell-clearance failure, not optimizer/minimum evidence or an
observed GPU crash. Original failed segment and all earlier failures preserved.
No validation continuation or tolerance relaxation launched.

Active service `cpd-anti-gpu-largebox-failure-audit-service-v3` (unit without
-service suffix) replays all1010 saved/final geometries, all native endpoints and
restart continuity; missing endpoint reference is staticCPU-bondedrun0 only.
Diagnostic artifacts `cpd-anti-gpu-largebox-failure-audit-v3`. Virtual cells z+20A,
z+40A and allaxes+20A evaluated against saved coordinates; this is feasibility,
not actual resolvation or future trajectory guarantees. One-hour bound,20minute
watcher estimate, completion-triggered wake. Original context deadline unchanged;
22.98h remained at audit launch. No dynamics, cloud, refit or new minimum claim.
On completion: inspect every failure and native energy replay, review structural
observables, choose a justified cell only if full restarted matched campaign plus
startup/analysis fits remaining budget; otherwise ask about bounded scope/budget.
Do not count failed-cell partial segments toward replacement validation duration.


**Larger-box startup independently audited; GPU-resident validation running — 2026-10-04.**
Wake `810aeb49-ea72-4843-ad6a-1dcc17d06369` acknowledged at the requested service.
All six 100ps startup +10ps restart reports passed in the 59,247-atom cell.
Measured native 100ps times: anti replicas 65.171/62.176/62.738s;
control replicas 62.685/63.082/62.688s. These replace the earlier volume-scaled
estimate: about 1.75h per10ns, 10.52h for all60ns, plus analysis/static checks.
Independent native replay passed all672 saved/final geometries, both minimized
endpoints, static force/energy comparisons and restart continuity. Evidence:
`cpd-anti-gpu-largebox-v3/startup_native_audit.json`; delivery receipt saved.

Prepared `gpu_largebox_validation_v3.py`: six10ns replicas, round-robin1ns
segments, same frozen forcefield, +p4/GPU0, GPUresident on,stepspercycle10,
no preceding run0, original 2fs/PME/NVT settings. Config preflight compares all
six qualified restart configurations; eight parser/water-check tests pass.
Every10ps saved frame plus binary endpoint undergoes solute,26-image,waterOO
and OH/storage-precision checks. Every segment verifies binary restart records,
initial energy continuity and static CPU-bonded run0 endpoint energy replay.
These static references do not advance CPU dynamics. All dynamics remain resident.
Any failure stops all subsequent runs; no automatic retries or widened gates.
Fresh declared Langevin seed per segment; no bitwise stochastic-continuity claim.

Original36h context deadline remains 2026-10-05T22:05:08.873384Z; no extension.
Active service `cpd-anti-gpu-largebox-validation-service-v3` launched at
2026-10-04T21:12:04Z. Supervisor running; first native log confirms resident mode
and cycle10. External watcher armed for this thread, token
`fd8a7c9f-b89b-4063-b393-2b50964b0fb0`. Expected14.14h includes25% runtime
margin plus1h analysis allowance; 24.88h remained at launch. No budget reset.
The service uses completion-triggered waking, no model polling, no cloud.
After native validation, structural observable review and restartable packaging
remain required. Historical failures remain failed; no minimum/equilibrium or
long-term readiness certification is inferred from startup success.


**GPU-resident cycle10 qualified; expanded-box startup launched — 2026-10-04.**
Wake `0ee3ab36-07a5-4771-8b4e-83edc8e5abfc` received/ACKed. Independent native
audit verifies175 saved/final geometries, all pinned inputs, finite logs/steps,
solute/water/image gates and exact checkpoint records. Anti/control endpoint
reference energy errors0.0676/0.0472kcal/mol and native restart errors0.0065/0.0051
pass frozen limits. Both resident50ps+10ps tests pass, plus anti50ps4-thread test.
Evidence: `cpd-anti-gpu-resident-cycle10-v3/native_audit.json` and service receipt.
This qualifies GPUresident on,stepspercycle10,no precedingrun0,2fs/ordinary masses,
all-H constraints,fullElectFrequency1 and original PME settings. Original cycle1
failures and double-coordinate solvent precision failures remain disclosed; force
qualification uses the explicit representation-aware method, not a false old pass.

Small-box timing: anti/control25.746/25.771s per50ps at2threads;4threads25.100s
(172.1ns/day). Four threads selected, with only~3% observed advantage and no strong
scaling claim. Larger-box60ns projection15.68h is volume-scaled, not measured.
At launch25.23h remained in ORIGINAL36h context budget;48h extension never activated.
Original72h deadline and packaging scope remain. No minimum/equilibrium claim.

**Active service:** `cpd-anti-gpu-largebox-startup-service-v3`; artifacts
`cpd-anti-gpu-largebox-v3`. Prepared59,247atoms (3043solute,18,665waters,151Na,58Cl),
box64.93×87.438×112.763Å and matched~0.15M excesssalt. Original pre-startup solute
coordinates translated10Å inx/y, solutePSFs/charges/bonds/masses and frozen candidate
unchanged; shared solvent excludes union of both seeds. Registered observables
retained by identical solute indices. Distinct historical seed conditioning remains
explicit. No failed dynamics state reused. Parameter coverage/neutrality verified.

Unminimized GROMACS packing has nearestOO1.84296Å, so fails the production2Å screen.
That failure is recorded, not passed. It admits only native static comparisons and
bounded1000-step common minimization (preminOO>1.5Å,originalsolute/image/OH checks).
Postminimization and allMD require fullOO>2Å,originalsolute/image gates and precision-
awareOH checks. Startup service first compares same-coordinate fullPME reference/
resident forces under unchanged limits, then GPU-resident minimization, matched
six50psheating+50psequil+10psrestart tests and independent endpoint energy replays.
No CPU/offload dynamics fallback.2h/16GiB/4threads,expected30min,external eventwake;
worker also enforces original context deadline. On wake ACK/audit actual evidence,
use measured larger-box throughput for6×10ns admission with analysis reserve,then
launch only if allstartup gates and remaining budget pass. Long production stays
unlaunched; restartable package follows successful validation and structural review.

**GPU restart diagnostic wake reviewed; cycle10 continuation launched.**
Token `f19f2977-56fb-40bb-9896-5177e59059ab` received/ACKed. Both registered50ps
runs completed natively. Cycle1 still develops severe solvent overlaps (final
O–O0.02723Å); removal of run0 does not repair it. Cycle10 retains all solute/image
gates and minimum saved water O–O2.44356Å. Its recorded failure was the newly
added1e-5Å OH diagnostic applied to float32 DCD without storage uncertainty:
maximum nominal error1.39475e-5Å, while double checkpoint error9.25e-9Å.
Versioned precision replay uses double arithmetic and explicit half-ULP coordinate
bounds for each DCD atom; all cycle10 frames are consistent with physical1e-5Å
limit and the binary endpoint directly passes. Original failed reports remain.
Two regression tests confirm this distinguishes DCD quantization from real bond
stretch/periodic overlap. Cycle1 remains failed under this corrected inspection.

Active `cpd-anti-gpu-resident-cycle10-service-v3`, output-cycle10-v3. Reuse the
completed anti50ps; independently compare endpoint potential and test10ps restart.
Then control50ps plus endpoint/reference/restart and a single anti50ps4-thread
benchmark. Same2fs/ordinary masses/PME/fullElect1/tolerances; GPUresident on,
stepspercycle10,no precedingrun0. CPU mode is static reference only. Original
qualification/context deadlines apply,1h service cap,expected5min,event watcher.
Observed cycle10 anti timing25.75s/50ps is provisional until restart/controls pass;
not a readiness or general engine-bug conclusion. No reboxing/long validation yet.

**Delayed R2 GPU qualification failure wake acknowledged and replayed.**
Token `be6179d2-8a03-47ac-9050-a44d0e88cefb` received/ACKed. Independent native
replay confirms precision-controlled solvent force residuals4.38346e-5/3.53850e-5
and full-system PME force differences0.00334069/0.00461564kcal/mol/Å, all passing
their frozen revised tests. The50ps anti trajectory nonetheless fails resident
qualification: final periodic water O–O minimum0.0339342Å, despite intact OH
constraints and nonzero checkpoint velocities; restart reports VDW≈198million
kcal/mol and has no normal termination. Static success does not certify dynamics.
Receipt: service-v3-r2/completion_delivery_verified.json. Original failures remain
preserved. The two-case GPU restart diagnostic is already running, watcher armed
and supervisor alive; no duplicate or slower dynamics job launched. Await its wake.

**R1 wake ACKed; R2 resident trajectory/restart failure under diagnosis.**
Token `51c10830-3e62-48b1-8b32-1be027066f3c` was acknowledged; native replay verifies
both passing solutes and both original failing solvent force comparisons in-r1.
No MD ran there; all failure records retained. R2 has now completed precision-aware
solvent fixtures and both full-system PME force comparisons successfully. Its anti
50ps native trajectory completed in34.64s and passed original solute geometry
checks, but native restart initialVDW≈198millionkcal/mol disagrees with the saved
endpoint. Binary velocities are nonzero despite run0 reporting zero kinetic energy.
DCD/final coordinates agree and water OH constraints remain intact; periodic
water-oxygen overlaps nevertheless develop during the trajectory (none at first
10ps,24 sub0.5Å pairs by25ps,302 by50ps). This is a real resident output/trajectory
consistency failure, not just the earlier log parser or zero-kinetic print behavior.
Original solute-only checks were insufficient; this trajectory is not qualified.

**Active service:** `cpd-anti-gpu-restart-diagnostic-service-v3`, output
`cpd-anti-gpu-restart-diagnostic-v3`, external wake,1h service cap also bounded by
original qualification/context deadline. Exactly two50ps GPU-resident diagnostics
from the original passing anti startup, both without preceding run0, using
stepspercycle1 versus10. Same physical parameters,2fs,full electrostatics each step,
1e-8 rigid tolerance. Every saved1ps frame checks original solute/image gates plus
periodic water O–O>2Å and rigid OH error<1e-5Å. Only passing cases get an independent
native static endpoint energy comparison and10ps resident restart. CPU-bonded
reference is run0 only; no slower MD fallback. This diagnoses run sequencing versus
update scheduling; no variant is predeclared successful. No validation/reboxing
launch until resident consistency is established. Earlier-r2 queued wake must not
restart that failed job. No minimum or readiness claim; failures preserved.

**Delayed initial GPU qualification failure wake acknowledged.**
Token `8ca2d13c-5048-4773-adcf-1f855ebbd388` was received and ACKed. Native evidence
confirms the passing anti-solute comparison and the one-patch/two-thread solvent
startup rejection before solvent forces or MD. Failure remains preserved; service
`completion_delivery_verified.json` records the audit. Revised GPU-resident
qualification service-v3-r2 is already running with its watcher armed and supervisor
alive. No duplicate job or superseded restart was launched. Await its completion
wake; no minimum or readiness claim.

**GPU-resident coordinate-precision diagnosis; revised checks launched.**
Recovery-r1 completed remaining static fixtures: both solutes pass, both original
solvent force comparisons fail (0.00158725/0.00176689 against0.001kcal/mol/Å).
No dynamics ran. Single-patch coordinates are represented as floats relative to
the bounding-box center (native PatchMap and bonded-kernel source inspected).
Independent OpenMM replay at those rounded coordinates reduces native residuals
to0.00004736/0.00004291; original double-coordinate outputs remain unchanged.
This identifies coordinate-representation sensitivity, not grounds to erase fails.

New `cpd-anti-gpu-resident-qualification-v3-r2` freezes an explicit method revision:
retain original failures; separate predicted coordinate-rounding force response
from native kernel residual under the original0.001 bound; test two deterministic
binary-grid solvent fixtures whose patch-relative coordinates are exactly float
representable (same force field, grid2^-16Å). Also compare native resident and
reference full-system PME forces at identical original startup coordinates under
original absolute/relative bounds. This is representation-aware qualification,
not a claim that old double-coordinate solvent comparisons now pass. No numerical
tolerance increase or parameter refit. Both already-passing solutes are reused.
Only if all revised checks pass, run the previously frozen short resident MD,
restart and thread benchmarks. Active service has suffix-v3-r2; prior-v3/r1
failure wakes are superseded orchestration records, not restart instructions.
All prior native outputs and original qualification/context deadlines retained.

**GPU-resident qualification startup correction — 2026-10-04.**
Initial GPU-resident anti-solute comparison passed unchanged force/energy limits
(force error0.00212353 versus0.00413254kcal/mol/Å limit). Eight-atom solvent
fixture then rejected two CPU threads because resident mode requires at least
one spatial patch per thread. Failure precedes solvent force evaluation and all
MD; original native log and traceback retained in qualification-v3.
Versioned recovery `cpd-anti-gpu-resident-qualification-v3-r1` uses one thread for
static fixtures, reuses the completed hash-pinned anti-solute result, and retains
all original tolerances and qualification/context deadlines. Its separate service
has an event watcher. Dynamics/benchmarks remain conditional on all static gates.
Do not relaunch the superseded initial service on its already-queued failure wake.

**GPU-resident direction authorized; qualification launched — 2026-10-04.**
User explicitly requires GPU-resident preparation and future dynamics after
qualification, with no use case for the slower mode once established. New frozen
policy/plan: `cpd-anti-gpu-resident-qualification-v3`. Earlier box failure, engine
failures, historical source hashes and budgets remain intact. The proposed48h
context extension is not activated; original36h context /72h overall deadlines
still apply. No new QM, refit, or tolerance changes. Future dynamics must explicitly
set `GPUresident on` and native logs must confirm that mode; no silent fallback.
CPU/reference calculations remain diagnostic references, not a production mode.

**Active service:** `cpd-anti-gpu-resident-qualification-service-v3`,2h/12GiB cap,
expected15min,external completion/failure wake. Qualification reruns the four
original solute/solvent fixtures against frozen OpenMM references and unchanged
absolute-or-relative tolerances. All four are retained even if one fails; no MD
unless all pass. Then50ps anti/control plus10ps native checkpoint continuation each,
original geometry/image/restart checks, and bounded2-versus4-thread10ps benchmarks.
The failed1ns validation state is not reused; diagnostics start from previously
passing startup checkpoints and do not count as replacement validation replicas.
Native source confirms GPU-resident computes all bonded terms, so the old
`bondedGPU 0` setting is removed rather than assumed effective in resident mode.
On wake audit actual results, resolve any numerical failure without discarding it,
then prepare/qualify the expanded box and measure throughput before admitting the
six10ns GPU-resident replicas under remaining budget. No long production launch.

**Validation stopped: actual periodic-image failure confirmed — 2026-10-04.**
Wake `69654d4f-5efe-4a11-a238-2950adae6376` was acknowledged and audited. NAMD
completed anti replica1 segment1 (1ns,steps55000–555000,1252.34s), then the old
parser crashed because energies preceded its first ETITLE. Native Controller.C
prints ETITLE every10×outputEnergies; with firststep55000 and interval5000, the
first header is at100000. New standalone `native_log_v3.py` reads consistent
native headers anywhere in a completed log without dropping early energies;
six regression tests pass. Pinned historical helpers/workers remain unchanged.

Corrected replay found a real scientific failure: at saved frame16 (step140000,
170ps after validation start) solute-image clearance crosses12Å. Across all100
saved frames plus final, minimum clearance is8.82104Å. All101 original chemistry,
stereo,bond/contact/piercing checks pass; finite native energies, complete DCD,
exact checkpoints and initial restart energy continuity also pass. The failure
is periodic-image separation, not a waived chemistry or native-integration error.
All native outputs, original traceback/servicefailure and failing-frame reports
are retained. This1ns does not count toward passing validation. No further MD runs.
Evidence: `cpd-anti-context-v3/validation_image_failure_audit.json` and service
`completion_delivery_verified.json`. No minimum or readiness claim.

**Recovery proposal awaiting scope decision:**
`cpd-anti-context-v3/expanded_box_recovery_proposal.json`. Virtual26-image checks
on the same saved solute give17.7247Å minimum for54.93×77.438×112.763Å, and
21.0899Å for64.93×87.438×112.763Å (proposed larger option). These are geometric
checks only, not re-solvated dynamics or a guarantee. The proposed box volume is
1.8737×original; simple measured-runtime scaling projects39.11h for60ns
before startup/audits, exceeding the roughly35h left in the36h context cap.
Propose one replacement matched campaign in the larger box and amend total
context cap to48h from the ORIGINAL context start, counting all elapsed work.
Original72h overall limit,6h package/review allowance,local-only execution and all
scientific gates remain. Re-solvate original frozen pre-startup seeds at the same
water/salt conditions; repeat engine/startup/restart checks and fresh6×10ns.
Stop on another failure; no further replacement,cap reset or long production.
This cap extension is not yet authorized, so no replacement MD has launched.

**Matched startup independently passed; six 10 ns replicas launched — 2026-10-04.**
Wake `5b779e8f-5ef8-46e0-85fa-06d9958005a3` was acknowledged and delivery verified.
Native startup completed in1067s. Independent replay checks all672 saved/final
startup/restart geometries, all input hashes, native logs/steps/configurations,
26-image clearance and exact checkpoint records. All pass; minimum clearance
14.5332Å (>12Å), maximum restart potential discrepancy0.0062kcal/mol within the
unchanged continuity tolerance. Both common1000-step minimization endpoints also
pass original chemistry/image checks, without any minimum claim.
Evidence in `cpd-anti-context-v3/startup_native_audit.json` and
`common_minimization_native_audit.json`. Two inspection-only false alarms were
preserved: the initial audit matched `minimize` in an input path instead of a
command, and the initial preflight expected an unresolved symlink path. Corrected
versioned inspections pass; no native/scientific failure was waived.

**Active service:** `cpd-anti-context-validation-service-v3`, frozen worker and
`validation_plan.json` under `cpd-anti-context-v3`. Six paired replicas run10ns
apiece in ten1ns segments, round-robin over replica/anti/control. Same qualified
2fs ordinary-mass, all-H-bond constraints,300K NVT, PME and CPU bonded settings.
One local GPU job /8workers /12GiB; no cloud. Measured0.66ns native startup took
784.37s, projecting19.81h for60ns;35.60h context time remained at launch. The
original context deadline is2026-10-05T22:05:08.873384Z, not a reset budget.
Watcher expected21.79h, with terminal/failure or a single overdue wake; no model
polling. Watcher and supervisor verified alive/armed.

At each1ns boundary the worker verifies all100 saved10ps frames plus the final
geometry, original stereo/bond/contact/piercing gates, exact26-image distance>12Å,
finite energies, step counts, binary checkpoint equality and restart potential
continuity. Stop at first failure/deadline; no automatic retries or parameter edits.
Explicit final checkpoints cover segment endpoints not divisible by100ps restart
cadence. Seeds are paired_seed+2000+100*segment; physical binary state continues,
while stochastic state is freshly seeded, so no bitwise trajectory-continuity claim.
Preflight confirms all other native settings match the qualified restart; registered
observables are invariant under rigid transforms to2e-12 numerical error.

On completion/failure wake ACK and audit actual native evidence, preserving failures.
If all six10ns pass, independently review preregistered structural observables,
including common polar atom-pair identities across conditions and all replicate
spread/first-last5ns summaries, then prepare the restartable production package.
Worker success alone does not establish structural readiness. No long production,
app promotion, equilibrium, full-Hessian minimum or mechanics claim is authorized.

**Final-parameter engine audit passed; matched startup launched — 2026-10-04.**
Wake `3f2a819a-6e02-4413-a2b6-caec8ad7019d` was acknowledged. Independent
OpenMM recomputation and native NAMD comparisons pass all four static fixtures.
All 200 saved frames plus two final geometries preserve the original 298 anti /
288 control centers, bond integrity, and zero severe contacts/ring piercings.
Exact 26-image checks at every saved/final geometry give minimum clearance
18.8323 Å anti / 15.3852 Å control (>12 Å). Final binary coordinates/velocities
match the step-100000 restart files exactly; box records match. Evidence:
`cpd-anti-solvated-engine-v3/{independent_review,periodic_restart_audit}.json`;
service `completion_delivery_verified.json`. No minimum certification.

**Active service:** `cpd-anti-context-startup-service-v3`; frozen plan and worker
under `cpd-anti-context-v3`. Native timing at 1 fs implies about 40 h for 6×10 ns,
so startup qualifies ordinary-mass 2 fs with all bonds to hydrogen constrained
(the documented NAMD `rigidBonds all` scheme). CPU bonded terms, full electrostatics
every step, original PME/cutoff/box, 300 K NVT remain. One common 1000-step
minimization per chemistry avoids three identical minimizations. Paired seeds
41017/52031/63043 each receive 50 ps staged heating, 50 ps at 300 K, then a
10 ps native restart test using exact binary coordinates, velocities and box.
Check every saved 1 ps frame, original chemistry gates and >12 Å image clearance;
compare restart initial potential to the preceding endpoint. Stop on any failure.
The new common startup is matched; differing historical seed conditioning remains
disclosed. No NPT, equilibrium or perfect causal-comparison claim.

This startup begins the shared 36-hour context cap, bounded also by the original
72-hour deadline. Startup itself has 2 h / 12 GiB / 8 workers; one GPU job at a
time, expected 1 h, external completion/failure watcher armed. No model polling.
`observables_registration.json` freezes lesion/attachment distances, sugar/chi
angles, original chemistry checks, local source-selected polar contacts and
ring-plane opening/stacking descriptors before trajectories. All replicas and
first/last 5 ns summaries must be reviewed, with no invented equilibrium gate.
Source contact selections differ slightly (35 anti / 34 control), so compare
shared atom-pair identities as well as each condition's retention, never pooled
fractions as if denominators were identical. Geometry contacts are not assigned
hydrogen bonds. On wake audit all six startup/restart outputs, then launch the
registered six 10 ns validation runs only if all pass and remaining budget permits.
Long production and readiness claims remain gated on validation and packaging.

**Prospective validation passed; exact-parameter NAMD pilot launched — 2026-10-04.**
Wake `a475b661-abeb-4fff-b041-5ae25e89fe96` was ACKed. All four±18.75° targets
completed in12,372s and each received exactly one locked-candidate MM score.
Native audit verifies74 QM gradients and138 MM evaluations. EnergyRMS0.425150,
max0.723403kcal/mol; all four geometry and numerical/chemistry checks pass.
Candidate SHA remains`b5d295e934910ef5ef0b3ea960f12155875d4943476ceb33d1974f2eba49b547`.
Scoring `native_audit.json` provides authoritative acquired-target provenance;
the scorer's historical template fields in `point.json` are not source provenance.
Conformational qualification passes, not yet full-context structural readiness.

**Active service:** `cpd-anti-solvated-engine-service-v3`, output
`cpd-anti-solvated-engine-v3`. Final fragment parameters were mapped to native
DNA types using the established transfer procedure. Full-system OpenMM checks
show precisely10 intended proper-torsion occurrences changed for anti,0forcontrol;
all masses and non-proper forces remain identical.30,867atoms each,ordinary masses,
1fs,rigidwater,300K NVT,existing0.151M excessNaCl box and source-conditioned seeds.
Both starting geometries pass chemistry; all26 neighbor images were checked for
>12Å solute-image clearance. A bounded image precheck's exact-minimum label was
corrected in a separately retained full-image report; its pass verdict is unchanged.
Initial preparation used the QM runtime lackingParmEd and stopped before work;
the established repository engine runtime passed preparation.

Pilot runs the original solute/solvent static NAMD/OpenMM comparisons with CPU
bonded terms,then100pspercase with the final parameters. Expected15min,2hcap,
8nativeworkers/12GiB,eventwatcher. No additional minimization in this engineering
stage; replica startup remains next. On wake ACK/audit logs,forces,all saved/final
chemical geometries,periodic clearance and checkpoint continuity; then freeze
matched6×10ns context conditions/analyses/budget before launch. Distinct historical
anti/control conditioning remains disclosed; no minimum or source-placement claim.

**First development pass audited; prospective validation launched — 2026-10-04.**
Fit wake `167d7ef9-22bf-4802-941a-998f0fbc272f` was received/ACKed. Round1 stopped
at the first full pass,model48,after48 vectors/1124s. The independent native replay
verifies45,305 saved MM evaluations across1,296 fragments,all residual/gate values,
final stereo/constraints/forces and five selected-parameter export fixtures.
Candidate SHA256 `b5d295e934910ef5ef0b3ea960f12155875d4943476ceb33d1974f2eba49b547`.
Energy RMS0.471083,max1.287714kcal/mol; original23 RMS0.399339. Worst target heavy
RMSD0.240585Å/proper discrepancy19.2133°; all24 and all3representatives pass.
This is development qualification only, not prospective/engine/context readiness.

The preregistered±18.75° targets were screened against117 historical JSONfiles
containing explicit acquisition-angle fields(905angle records); zero matches
within0.01° circular angle tolerance. Search/provenance receipt and executable
audit are in `cpd-anti-prospective-exposure-v3`. Absolute targets are endpoint1
−93.8659559/−56.3659559°, endpoint2lower65.7159437/103.2159437°. Old±22.5° targets
remain exposed. Candidate lock in `cpd-anti-readiness-fit-state-v3` blocks further
fitting; registration and fixed scoring predate any new acquisition.

**Active service:** `cpd-anti-prospective-qm-service-v3-r1`; native output
`cpd-anti-prospective-qm-v3-r1`. Four sequential Sella/Psi4 cases,40 gradients each,
160 total,6h/case,12h/batch,4cores/12GiB service. Expected4h; one overdue wake6h.
The scoring worker `score_prospective_v3.py` and plan are already frozen under
`cpd-anti-prospective-score-v3-r1`: one QM-seeded MM attempt per target, original
common QM/MM references from model48,1/2kcal energy and0.25Å/20° correspondence
gates, unchanged force/chemistry limits. On wake ACK/audit native QM, then execute
that single scoring pass. No refit, target omission, separate re-zeroing or long
production launch. If prospective gates pass, proceed to final exact-parameter
NAMD checks and the authorized matched6×10ns campaign under the72h contract.

**Curvature audited; new bounded fitting round launched — 2026-10-03, 23:58 MDT.**
Wake `0275d289-ff56-48c3-9b97-83b232d00311` was ACKed. Native audit verifies all
eight gradients, electronic response, stereo/constraints and both two-step energy
curvatures. Old/new+30° curvatures are0.22808/0.22114hartree/bohr²; step differences
0.0109%/0.0415%. Both pass the directional check, not an all-mode minimum claim.

The new readiness fitting state is `cpd-anti-readiness-fit-state-v3`, independent
of the exhausted historical ledgers. It retains the exact23 old point records and
adds `endpoint-1-+30-lower-sella-v3`, with actual native provenance, recomputed
geometry descriptors and the same endpoint1 reference for relative energies.
All24 energy/shape targets and all3 representatives must pass. The original23
energy RMSE is also checked separately so adding a target cannot dilute a prior
failure. Original22 coefficient identities, ±5kcal/mol shifts from the same base,
charges/LJ/bond/angle/improper terms and numerical/chemistry gates remain fixed.
The generic preliminary protocol's unchanged input-lock/round-reservation logic
is used in this new, explicitly authorized state. Its maximum is two rounds;
round2 requires an evidence-based residual review. Old locks/ledgers are hash-pinned.

**Active service:** `cpd-anti-readiness-fit-service-v3-r1`; results
`cpd-anti-readiness-fit-v3-r1`. Starts from prior trial7, computes fresh22-column
finite-difference Jacobians, then gate-directed trust-region proposals. Each vector
uses a fresh isolated Sella process. Stop on first complete actual development
pass,240 vectors,2h,failed derivative/child,or4 rejected trust steps. Expected1h;
single overdue wake1.5h;6GiB/4cores. No automatic second round or prospective
acquisition. Three numerical regression tests, runtime-version checks and five
parameter export energy/force fixtures passed before launch. No new QM in fit.
On wake ACK/replay native MM evidence, review the selected candidate against all
gates, then register prospective targets only after freezing a passing candidate.
Scientific/NAMD qualification flags remainfalse until downstream stages pass.

**Recovery complete and basin evidence audited — 2026-10-03, 23:25 MDT.**
Wake `8d326563-b02c-42a2-958b-f74238121087` was received/ACKed. Both recovered
cases completed within the original caps: trial7 used25 completed/26 attempted
gradients, model61 likewise25/26 (each includes one killed incomplete attempt).
Recovery added18 completed gradients in3015s; no saved complete gradient was
recomputed. Combined native audit verifies75 gradients and four constrained
stationary cases, including original-reference stereochemistry, printed MP2
energies/gradients, electronic response and three projection step sizes.
Evidence: `cpd-anti-competing-basin-review-v3-20261003/native_audit.json` and
`basin_comparison.json`; service receipt `completion_delivery_verified.json`.

At+30°, trial7 returns to the original QM conformation (heavy RMSD0.000077Å),
while trial1 reaches a distinct stationary shape (0.13024Å from old QM) lower
by1.111677kcal/mol. Trial1's MM seed remains0.33317Å from that new QM shape,
so the new branch does not itself remove the MM correspondence failure. At−22.5°,
model61 returns to the existing Sella QM target (0.000222Å), still0.32122Å from
its MM starting conformation. Thus two references are reproducible from competing
starts, while an additional+30° stationary branch must be retained as exposed data.
Neither optimizer stationarity nor lower energy establishes all-mode stability.

**Active next step:** `cpd-anti-competing-curvature-service-v3-20261003`, output
`cpd-anti-competing-curvature-v3-20261003`. Eight sequential MP2 gradients sample
±0.02/±0.04bohr along the aligned basin-separation direction at each+30° shape,
projected/retracted to the same torsion. Existing electronic/stereo settings stand;
eight geometry checks and four finite-displacement tangent checks pass. Expected
30min,1h hard cap,4cores/12GiB service. Frozen numerical criterion: positive
constrained energy curvature at both steps and≤10% step-halving difference.
This checks one relevant direction only, not a full Hessian/minimum certificate.
Preserve both conformations; no old target or failed verdict is overwritten.
An initial preparation list/array conversion error is archived separately;
it occurred before native calculations. On completion ACK/audit native outputs,
then register an evidence-based fitting successor retaining all23 old exposed
targets plus the new branch, with original common energy-reference identities
and unchanged acceptance limits. Do not resume the exhausted old fit ledger.

**Parallel OOM audit and sequential recovery — 2026-10-03, 22:34 MDT.**
The guardian failure wake `0bf582bc-7162-496c-b3dc-996614b3e695` was received
and acknowledged. Systemd records the parallel service OOM at22:27 MDT; its
stale `running` status is not authoritative. The guardian correctly detected
supervisor exit, then failed reading the missing upstream assessment. These
execution failures remain preserved. The abandoned stopped serial dispatcher
was released after verifying it had no live native child.

Read-only audit `audit_competing_qm_v3.py` verifies57 completed native gradients:
1 old-reference,24 trial1,20 trial7,12 model61. Both completed +30° cases satisfy
the existing constrained stationarity/chemistry checks. Trial1-derived QM is
1.111677kcal/mol below the old QM reference at the same constrained torsion.
This is evidence for competing conformations, not yet a curvature/minimum or
solution-population claim. The two interrupted gradient attempts (21 and13)
remain consumed against their original40-attempt budgets.

Recovery `.development-artifacts/cpd-anti-competing-recovery-v3-20261003/`
replays the20/12 saved gradients to restore Sella state. Both preflights reached
the interrupted next geometry **bitwise**, with zero new QM calls. Their expected
replay-only stop exceptions are retained; an initial import-path preflight failure
also occurred before calculations and is retained. Native recovery permits only
19+27=46 additional attempts, sequentially, four cores and12GiB service memory,
retaining original absolute6h case/12h batch deadlines. No completed gradient is
recomputed; incomplete killed evaluations have no reusable gradient. Original
inputs, locks and failure verdicts are untouched.

**Current authoritative wake/service:**
`cpd-anti-competing-recovery-service-v3-20261003` (expected2h; single overdue wake3h).
On completion, ACK that token and audit the combined old/new native records,
including gaps for the two lost attempts, then compare the stationary basins and
continue within the72h readiness contract. Recovery completion alone is not
scientific qualification. Two-worker concurrency proved unsuitable at the chosen
memory limit; do not repeat it without a new memory budget assessment.

**Parallel scheduling update — 2026-10-03 (America/Denver).** User requested
better core utilization without additional scientific work. The machine has
16 physical cores /32 threads,30GiB RAM; with one ~6GiB QM process, available
memory was ~11GiB. The existing benchmark measured one gradient at204s/4threads
versus152s/8threads. Two independent four-core cases are the chosen throughput
configuration; no additional targets or gradient budget were introduced.

The original +30° QM reference completed with one gradient; its preliminary
stationarity report passes (native evidence still needs batch review). The live
trial1 optimization was preserved on CPUs4–7 and trial7 started on CPUs0–3.
The first handoff coordinator encountered `os.pidfd_open` missing in the Sella
Python runtime. Its failed observation incorrectly released a lane and briefly
started the fourth case. That fourth process was immediately stopped with its
optimizer/gradient state retained. The corrected guardian uses `/usr/bin/python3`,
whose pidfd/native-exit-status behavior was tested, and resumes that same process
only after trial1 exits. No QM process was restarted; no gradient was repeated.
The repository dispatcher now rejects incompatible runtimes before handoff;
the frozen failed coordinator remains preserved.

**Authoritative completion event:**
`cpd-anti-competing-parallel-event-service-v3-20261003`; guardian/results:
`.development-artifacts/cpd-anti-competing-parallel-event-guard-v3-20261003/`.
Its watcher is armed for the originating thread. Both superseded watchers were
stopped after the replacement was armed. The original serial dispatcher remains
stopped while its native child runs, and is terminated only after native work
finishes. Its eventual failed transport status means superseded orchestration.
Likewise, the intermediate parallel assessment retains the pidfd observation
error. The guardian assessment replaces only that observation with the actual
original native exit/result; it must not waive a scientific failure. The original
12h batch deadline,6h case caps,160 total gradient limit and72h contract stand.
The final reviewer must ACK the guardian service token, inspect all four native
cases at the original output paths, and review the preserved handoff error.
No model polling is required; the guardian blocks on process-exit events.

**Readiness continuation authorized — 2026-10-03.** The user accepted the proposed
endpoint: preliminary structural qualification in the existing additive cis-anti-I
interstrand TT context, three anti and three matched undamaged 10 ns replicas,
and a restartable production package without launching long production. They
explicitly require completion-triggered wakes instead of polling. The new
`.development-artifacts/cpd-anti-readiness-v3-20261003/contract.json` records the
72-hour local compute ceiling, stage caps, unchanged scientific gates and scope.
This is a new continuation; historical fit budgets/locks are not reset.

The first diagnostic is `experiments/cpd_anti_additive/competing_qm_v3.py`:
four sequential Sella/Psi4 MP2 optimizations, at most 40 gradients each / 160 total,
six hours per case and twelve hours for the batch. At endpoint-1 +30°, compare
the historical QM seed with MM trial1 and trial7 seeds. At −22.5°, compare the
MM model61 seed with the already stationary Sella QM evidence. All starts retain
the same graph, atom mapping, electronic model, stereochemistry and prescribed
torsion. These are exposed diagnostics, not prospective validation targets.
The preflight resolves the −22.5° source from its actual native acquisition;
misleading inherited parent metadata is not reused as that target's provenance.

Inputs and runtime are frozen under
`.development-artifacts/cpd-anti-competing-qm-v3-20261003/`. On the service's
completion/failure wake, acknowledge its token, verify native energies/gradients
and constraints, then compare basins before deciding on reference or model
changes. Native convergence alone is not a minimum or readiness certificate.
Follow-on fitting requires a separately frozen evidence-based plan; the old
two-round ledger remains closed. No threshold relaxation or cloud spending.

**Shape evidence review and bounded Sella refinement — 2026-09-27 17:20 UTC.**
The [new review](cpd_anti_shape_evidence_review_20260927.md) distinguishes local
MM–QM correspondence gates from an experimentally established CPD shape. It
resolves inherited metadata for four Sella targets and reconstructs all three
saved Jacobians. A separate 12-vector / 600-second attempt completed in 280 seconds;
selected trial7 reduces worst RMSD from 0.3213 to 0.2589 Å but still fails three
RMSDs, maximum energy (2.0158 kcal/mol) and one representative angle (3.1118°).
All 11,074 native evaluations replay correctly. No development pass or model
inadequacy is established. Original contracts/ledgers remain closed and unchanged.
No calculation is active; targeted Sella QM comparison of competing conformations
is the next evidence priority before further forcing correspondence or adding terms.

**Resumed by user — 2026-09-25.** The instruction “Begin next steps. Then resume the campaign to get to NAMD testable cis-anti CPDs” activates the bounded [preliminary protocol v2](cpd_preliminary_protocol_v2.md). The earlier [closeout](cpd_anti_closeout_20260925.md), failed results and v1 gates remain historical evidence.

**Second fit closed at original deadline — 2026-09-27 04:29:42 UTC.** The
[recovery closeout](cpd_anti_shape_fit_closeout_20260927.md) records69 complete
models and an interrupted70th. Selected model61 improves exposed energy RMS/max
to0.294398/0.915744kcal/mol and retains three endpoint1 shape failures: RMSDs
0.296755,0.320938,0.321259Å against0.25Å. All three representatives pass. Full
native audit of36 recovered models plus24 recorded fragments of70 passes;
original33-model evidence is unchanged. Peak recovery memory approximately672MiB.
The wake token `5b5de21a-1f24-4815-8a3f-36f4abb54225` / `complete` was ACKed
04:30:00UTC. This was wall-budget termination, not optimizer convergence or a
minimum/scientific certificate. Both rounds and wall budget are exhausted; no
automatic continuation. `cpd-anti-shape-closeout-v2-r2/assessment.json` pins the
failed selected trial and all evidence. No active fit, newQM, contextMD or cloud.

**Second fit interrupted by memory limit — 2026-09-27 02:41:50 UTC.**
Kernel/systemd evidence identifies a6GiB cgroup OOM. Supervisor and worker are
dead; the preserved service `status.json` is stale (`running`). Wake
`2c49745f-d67f-4036-9db5-0acec5e1b04e` / `supervisor_stopped` ACKed02:43:38UTC.
The service's `completion_delivery_verified.json` independently checks all33
complete model evaluations plus16 complete fragments of model34:874 complete
fragment optimizations /29,870 saved MM evaluations and their final E/F.
The interrupted seventeenth fragment has8 cached evaluations and is nonstationary.
Lowest-objective completed model32 has energy RMS.426142/max1.127347 kcal/mol
over23 exposed cases and six shape failures, including a new endpoint1+30 failure.
No model passed all gates; this is not a completed fit or minimum certificate.

**Recovery launch history — 2026-09-27 04:16:06 UTC (now closed above).** The user explicitly instructed
“Resume with the interrupted round.” The [memory-isolation recovery](cpd_anti_shape_fit_oom_recovery_20260927.md)
verified its frozen plan and preparation checks, recorded the authorization, and
launched `cpd-anti-shape-fit-recovery-service-v1`. Output:
`cpd-anti-shape-fit-recovery-v1`. It reuses the33 completed models and the saved
model34 prefix with fresh processes per uncached model. Model34's independent
native audit verifies26 fragments /909 saved evaluations and preserves six shape
failures. At handoff,41 models were complete; service peak memory672MiB. All33 prior
residuals and complete/partial Sella prefixes reproduced during preparation;
four guard tests passed. Limits remain6GiB,360 vectors,max_nfev12,original
per-case caps and absolute fit deadline04:29:42UTC (about815 seconds remained
at launch). No clock or round reset. The separate watcher subsequently delivered
token `5b5de21a-1f24-4815-8a3f-36f4abb54225`, now ACKed as above. No automatic repeat.

**Second/final fit round launched — 2026-09-27 02:29:42 UTC (original process stopped; authorized recovery above).** The
[shape-v2.2 contract](cpd_anti_shape_fit_v2_r2.md) is frozen in
`cpd-anti-shape-inputs-v2-r2`. The registered successor state
`cpd-anti-shape-state-v2-r2` inherits the original round and has reserved round two;
the original candidate lock/policy/ledger are preserved. Both permitted rounds
are now consumed; the explicitly authorized recovery above has ended.
No duplicate, third fit or automatic further recovery is permitted.
Service `cpd-anti-shape-fit-service-v2-r2` ran locally on CPUs4–7 with a 6GiB cap,
two-hour fitting wall budget and 2.25-hour service limit. It fits 22 coefficients
against all23 exposed structures plus three representatives, using Sella geometry
optimization and an objective that includes geometry as well as energies. Limits:
360 total model evaluations including Jacobian probes, max_nfev12, no continuation.
Independent audit of its initial model verifies all26 structures/879 saved native
MM evaluations and final E/F replays, preserving the same eight shape failures.
Six lineage/budget guard tests and15 static export checks pass. The external
watcher token `2c49745f-d67f-4036-9db5-0acec5e1b04e` was delivered/ACKed as above.
Future validation uses preregistered ±18.75° targets only after an exposure audit
and revised-candidate registration; old ±22.5° targets remain exposed. No context
MD, minimum claim, app promotion or cloud spending.

**Sella default and scientific continuation — 2026-09-27 UTC.** The user selected
Sella for future molecular geometry work and requested scientific qualification.
The [continuation report](cpd_anti_scientific_qualification_20260927.md) records the
fixed gates, completed native audits, prospective scores and shape diagnosis.
All four prospective targets now pass independent constrained QM stationarity
(73 native gradients) and fixed-candidate MM stationarity (133 evaluations).
The complete prospective energy test passes: RMS 0.855945 / maximum 1.621983
kcal/mol. Endpoint 1 −22.5° fails the retained shape descriptor (RMSD0.33480Å);
the seven exposed mismatches also remain. Scientific qualification still fails.
The [candidate closeout and shape-correction review](cpd_anti_shape_correction_review_20260927.md)
records the complete result and bounded next correction design. The acquisition
wake `a88710de-cc8e-4d06-b9c8-116f9aed758e` was acknowledged at 02:06:33 UTC;
native delivery evidence is in the QM service's `completion_delivery_verified.json`.
`cpd-anti-prospective-score-v2-r1` is frozen and reentrant by completed target;
all four attempts are now complete and must not be rerun. Second scoring service
`cpd-anti-prospective-score-service-v2-r1-b` completed at 02:07:17 UTC; independent
`scientific_review.json` reproduces all four scores. Its token
`3f5b0f34-03f8-4151-bf1c-7e2c01fdfd05` was delivered and ACKed at 02:19:31 UTC.
Fresh `completion_delivery_verified.json` reproduces all73 QM gradients/133 MM
evaluations and four final E/F checks without changing the earlier review.
First scoring service `cpd-anti-prospective-score-service-v2-r1-a` completed;
token `7f89baac-4fc6-4060-86c0-4147f5b7943a` was delivered and acknowledged
at 2026-09-27 01:43:24 UTC. Read-only delivery review reproduces all 54 native QM
gradients and 97 saved MM evaluations, with all existing verdicts preserved.
The service contains `completion_delivery_verified.json` and an immutable copy
of the three-target scoring progress (`scoring_progress_snapshot.json`). Four
scoring guard tests pass. `cpd-anti-shape-model-diagnosis-v1c` examines all 23
saved pairs and inventories the actual ring/cap proper terms. Half the fitted
coefficients have zero tangent derivative under the scan constraint (66 checks);
baseline shape failures improved 10→7, but lower +15° regressed 0.1366→0.6885Å.
Earlier diagnostic v1 failure/v1b classification erratum are retained. Candidate
lock, policy and original used-round ledger remain unchanged. The successor fit
above is now closed at its original deadline; no new QM, context production
or app promotion yet.
Sella preference: `memory/feedback_sella_default.md`. No cloud spending.

**Full-DNA NAMD-testable milestone reached — 2026-09-26 22:25:57 UTC.**
The corrected cis-anti and control each passed100ps in30,867-atom explicit solvent.
Independent replay verifies four static E/F comparisons,200 saved frames plus
two final geometries, chemical stereo/bond/contact/piercing integrity, and finite
native energy/final forces. See the [full-system report](cpd_anti_full_dna_engine_20260926.md)
and [portable runnable bundle](../.development-artifacts/cpd-anti-solvated-namd-bundle-v2-r1/README.md).
This completes isolated engine testing; scientific qualification, product placement
and minimum certification remain incomplete. Next scientific stage: the four
registered prospective QM targets against the locked candidate, retaining seven
exposed profile geometry mismatches. No automatic refit, trajectory extension or
normal app integration. No cloud spending.

**Prospective QM validation launched — 2026-09-26 22:40:54 UTC.**
Delayed solvent-construction v1 wake `8f08635d-0b1f-44e7-a5ee-58f2101a614e`
was acknowledged at22:33:02UTC. Both native logs confirm parameter-stream startup
rejection before any energy/minimization/MD; old failure preserved, no duplicate
construction. The [prospective validation handoff](cpd_anti_prospective_validation_20260926.md)
now formally registers the first-round candidate and four prescribed ±22.5° targets.
The new `conformational_candidate_lock.json` blocks further fitting; existing
input locks/policy and one-used-fit-round ledger are unchanged. Preflight verifies
exact case/reference identities, chemical stereochemistry, new target angles,
Sella constraint convention and independent projection. No QM during registration.
`cpd-anti-prospective-qm-service-v2-r1` is active with its watcher armed; first
49-atom native MP2 evaluation is running. Four sequential local Sella cases,
≤40 gradients each/160 total,≤6h per case/12h total,4 CPU threads,6GiB Psi4/10GiB
service,zero continuations. Check current status before any launch; delayed wakes
must not start duplicates. Next after acquisition: independent native review and
one fixed-candidate MM scoring pass, not a refit. No minimum or research certificate.

**Delayed v1c construction wake reviewed — 2026-09-26 22:44:59 UTC.**
Token `1bdb0fa8-33ef-4994-8a97-098d4259f038` acknowledged. Read-only replay
verifies frozen inputs, eight native logs/1508 finite energy rows and30 saved
frames. Both cases stopped at750 minimization steps after D000:7:C3′ inversion;
first inverted saved frames are550anti/650control. Final forces44.046/80.555
kcal/mol/Å include positional restraints; neither case reached the unrestrained
phase or dynamics. The failure and source-reference caveat remain unchanged.
The active prospective service/watch process identities were checked: first point
has two completed gradients at this snapshot. Its first native electronic response
9.649e−11 passes1e−10, while projected force0.00820787au is nonstationary. No
new calculation or duplicate service was launched in response to this delayed wake.
Receipt: `cpd-anti-solvated-construction-service-v1c/completion_delivery_verified.json`.

**Delayed stereo-protected construction wake reviewed — 2026-09-26 22:51:54 UTC.**
Token `70e14be3-e04f-4e45-9373-c508ccd81f1c` acknowledged. Read-only replay
verifies frozen inputs, 400 native logs / 20,400 finite energy rows and 400 saved
frames across both cases. Each completed 10,000 steps, including 5,000 with all
temporary restraints removed. Chemical stereochemistry and final bond/contact/
piercing screens pass; final solute forces 36.301/38.568 kcal/mol/Å still fail
the unchanged 0.01 stationarity criterion, and both placement screens remain failed.
The original independent review is byte-identical and matches its downstream
engine-plan pin. No minimum certification or historical verdict changed.
Receipt: `cpd-anti-stereo-protected-construction-service-v2/completion_delivery_verified.json`.
The active prospective QM supervisor and external watcher were verified alive.
Four completed gradients at the first target were independently checked against
native printed energies/gradients, electronic-response residuals, chemical stereo
and three finite-difference projection steps. Latest projected maximum is
0.00709593 au, still nonstationary. Candidate/input hashes remain frozen; the
remaining three targets are queued. No duplicate calculation or cloud spending.
Continue the existing batch under its registered caps, then perform the prescribed
independent review and fixed-candidate scoring. The NAMD milestone above remains passed.

**Delayed engine v2 failure wake reviewed — 2026-09-26 22:55:21 UTC.**
Token `bec5870a-93eb-4c37-823e-b21c2b9c1cd4` acknowledged. Native replay verifies
both 3043-atom solute static comparisons under the unchanged absolute-or-relative
tolerances. Both solvent fixtures fail PSF startup (`DIDN'T FIND "NATOM"`);
their declared title record is blank. No solvent energy, minimization or MD ran.
The later v2e solvent PSFs differ only in that title line; the original failed
assessments/logs and downstream hash pins remain intact. Verification receipt:
`cpd-anti-solvated-engine-service-v2/completion_delivery_verified.json`.
At 22:57:11 UTC, prospective QM supervisor/watcher remain alive and input/candidate
hashes match. First target has five completed gradients; latest native energy,
printed gradient, electronic response and independent projection were checked.
Projected maximum 0.00204913 au still fails stationarity. Continue the registered
batch; no duplicate run, refit, minimum claim or cloud spending.

**Delayed engine v2d failure wake reviewed — 2026-09-26 22:58:09 UTC.**
Token `79b56005-d132-48c7-acde-22d1c85dcd4e` acknowledged. Replay of four v2d
static logs reproduces passing solute comparisons and failing solvent force
differences 0.00158725/0.00176688 kcal/mol/Å against the unchanged 0.001 limit.
Solvent energies pass; no minimization or dynamics ran. Replay of the two saved
precision-diagnostic logs gives force differences 0.0000250293/0.0000243028.
Their coordinates, PSFs, PDBs and references are byte-identical to v2d; configuration
differs only by `bondedGPU 0`. Later v2e uses that setting for both static tests
and MD. Original failures, input hashes and downstream pins remain intact.
Receipt: `cpd-anti-solvated-engine-service-v2d/completion_delivery_verified.json`.
At 23:00:02 UTC the existing prospective QM supervisor/watcher are alive, candidate
and inputs frozen, with six native gradients independently verified at target one.
Latest projected maximum 0.00187437 au remains nonstationary. Three other targets
are queued. Continue the existing bounded batch; no duplicate calculation,
threshold change, refit, minimum certificate or cloud spending.

**Delivered engine v2e completion verified — 2026-09-26 23:01:16 UTC.**
Token `8751ba64-5c1a-4491-a580-0259886dd234` acknowledged. Read-only replay of
native forces/energies against the saved independent references confirms all four
static comparisons. Both 100,000-step trajectories reproduce the archived review:
200 saved frames plus two final geometries pass the chemical stereo, bond, contact
and piercing screens; all 202 energy records and final forces are finite. Native
configs use 1 fs and CPU bonded terms, without further minimization or artificial
restraints. The original review/final-geometry files and prospective input pin
remain unchanged. All 104 portable-bundle files (125,113,925 bytes) match their
manifest. Receipts: `cpd-anti-solvated-engine-service-v2e/completion_delivery_verified.json`
and `portable_bundle_delivery_verified.json`. No new energy calculation or MD.
At 23:02:29 UTC the existing prospective QM supervisor/watcher are alive; seven
completed gradients at target one independently pass native evidence/chemistry
checks, but projected maximum 0.00274370 au remains above stationarity tolerance.
Candidate/input hashes are frozen. Continue that bounded acquisition, followed by
the registered independent review and fixed-candidate scoring. No automatic refit,
trajectory extension, minimum certification, research qualification or cloud spending.

**Review after closeout:** the user confirmed the next target is a preliminary
additive NAMD model for exploratory structural simulations, with documented
limitations. The [QM-to-MD workflow review](cpd_cis_anti_workflow_review_20260925.md)
identifies objective/validation mismatches and proposes bounded stages. That review
ran no calculations; the subsequent explicit resume activates v2.

**Current workflow:** v2 uses independent, hash-locked stage inputs and finite
round budgets. Original scripts still enforce [v1](cpd_validation_protocol.md);
new fitting entry points must explicitly name their v2 stage. The bounded
default-constraint QM test is terminal: native convergence failed the independent
projected-force check. The water-minimum/dipole charge fit has completed and passed
its fixed water criteria. The fresh Sella attempt now passes independent constrained
stationarity after 20 gradients/55.5 minutes. The subsequent user-authorized
first torsion fit is complete: all19 relaxed energies pass (RMS0.5421,
maximum1.0099kcal/mol), and the three registered representative geometries pass
0.03Å/3°. Seven profile geometry descriptors and prospective validation remain
unresolved. Conformational inputs are now hash-locked; one of two fit rounds is used.
The updated62-atom candidate passes ten native comparisons and100ps NAMD;
full3043-atom DNA passes static native comparison with parent sugar/phosphate
retained. The new bounded SLSQP DNA construction failed at1000 iterations:
mobile force1.36065>0.01kcal/mol/Å, base displacement14.0515>3.5Å. No extension or
full-DNA dynamics followed from that failed attempt. Those jobs are terminal;
the corrected-source construction and isolated engine test below are current. See the
[fit/native/construction report](cpd_anti_conformational_results_20260926.md) and
[engineering bundle](../.development-artifacts/cpd-anti-namd-engineering-bundle-v2-r1/README.md).
No scientific qualification or normal app integration has been granted.

**Current source repair and full-system engine test — 2026-09-26:** the delayed fitted-conditioning
wake `8f4a206c-9f01-42fa-a115-dbd4a56a044e` was acknowledged at21:40:33UTC;
the1000-iteration/1.36065-force/14.0515Å failure was independently reproduced.
The [source-stereo repair](cpd_anti_source_stereo_repair_20260926.md) now uses
chemically mapped QM sugar references and a concrete four-coordinate-per-case
reconstruction. Native psfgen's unsuccessful guesses remain archived. The explicit
reconstruction fixes the two diagnosed sugar signs. The separately frozen
`cpd-anti-stereo-protected-construction-service-v2` completed10ksteps per case,
including5000 after all temporary restraints were removed, and repaired adjoining
phosphate bonds. Independent replay verifies400 native logs/400 saved frames:
all mapped sugar and lesion stereochemistry retained; no final severe contacts,
piercings or bond violations. Forces36.30/38.57 and base displacement8.254/3.505Å
still fail stationarity0.01 and product displacement3.5, separately scored;
the immutable v2 engine criteria do not require whole-DNA minimum certification.
An isolated100ps-per-case NAMD smoke completed under
`cpd-anti-solvated-engine-service-v2e`:30,867 atoms,300K,1fs,normal masses,PME,
no further minimization/restraints. Both cases passed independent native replay;
the runnable bundle and report are linked above. Earlier engine v2 solvent-PSF
format failure and v2b/v2c prelaunch
checks are retained; zero MD steps consumed. V2d changes only the solvent-fixture
title line. V2d then failed the solvent force check (.001587/.001767 >.001);
CPU-bonded diagnostic gives .00002503/.00002430 with identical physical inputs.
V2e uses `bondedGPU 0` in both comparisons and MD; no tolerance change or prior
MD steps. Direct solute/solvent energy-force checks passed before MD. This engineering
stage carries all unresolved scientific and product-placement metrics.
No old verdict, threshold, policy hash, parameter or fit budget changed.

**Delayed fit wake received — 2026-09-26 21:07:54 UTC:** token
`e84c10a1-cc03-434f-98bb-f53a1c5529bd` acknowledged. All38 saved MM relaxations/
1323 evaluations and downstream report hashes verified; no duplicate calculation.
The [construction-method review](cpd_anti_construction_method_review_20260926.md)
finds increasing displacement despite decreasing vacuum energy, including22.03Å
at an unmodified remote nucleotide. The next method direction is solvated,
neutralized, staged-restraint construction with an undamaged control, under a
separate bounded engineering plan. Existing criteria, failures and fitting budget
are unchanged.

**Delayed native wake and solvent construction — 2026-09-26:** token
`b9d98b9c-40cb-4729-80a5-d760ea8c5d15` acknowledged at21:13:47UTC.
Saved native forces/energies and102 geometries independently replayed; all ten
QM-referenced stereocenters preserved. The
[paired solvent construction](cpd_anti_solvated_construction_20260926.md)
now has frozen executable inputs:30,867 atoms per case,9223 TIP3P waters,
124Na+/31Cl−,identical solvent/ions,unchanged CPD/native-DNA potential.
An unpatched source control retains its known starting defects explicitly.
`cpd-anti-solvated-construction-service-v1c` ran staged native minimization under
at most10,000 steps/case and2h total, with250-step geometry checks and no MD.
V1 native format failure and V1b preparation failure occurred before any energy
or minimization and are retained. Parameter-only export passes exact full-system
equivalence; criteria and physical budgets were not expanded. **Both cases failed
at750 steps on D000:7:C3′ inversion**; neither reached unrestrained minimization.
Independent review verifies eight native logs and30 saved frames. A separate
source audit finds D002:26:C3′ opposite to both QM sugar references and95 other
source nucleotides. Historical source-relative chirality preservation is not
absolute chemical validation. This failed construction is terminal; the later source
repair and reviewed construction are described above. No old failure was extended
or relabeled; no minimum certification.

**First resumed results:** the new charge fit passes all 17 clean water curves;
a complete 62-atom, two-nucleoside anti fixture passes 10 native engine comparisons
and 100 ps of NAMD dynamics. Full DNA and conformational qualification remain
unfinished. See [results and bounded continuation](cpd_anti_resume_results_20260925.md).
Full-DNA topology/parameter transfer now passes at the frozen 96-nucleotide site
(`cpd-anti-dna-topology-v2b`), retaining native parent sugar/phosphate terms.
Rigid base-only placement fails the existing screens: fixed sugars compress
glycosidic bonds to about 1 Å. The shared-frame rejection artifact is linked from
the results report. The bounded local construction (`cpd-anti-local-placement-v2`)
stopped at step24 on neighboring sugar inversion. Independent review confirms
the last valid iterate is nonstationary and identifies seven inherited parent-DNA
bond defects, four outside the movable region. The failure and shared-frame
diagnostic remain archived; no continuation or dynamics. Full-DNA NAMD requires
source-geometry conditioning as well as the anti patch.
The versioned source-conditioning diagnostic `cpd-anti-source-conditioning-v1b`
stopped at its 500-iteration constrained-phase cap. All seven inherited bond
defects now pass the construction screen; stereochemistry is preserved and the
two remote severe contacts are gone. However, maximum mobile force is
19.7611 kcal/mol/Å, and the unconstrained phase never ran. This remains a failed
construction, with independent evidence and a new shared-frame A/B archived.

Cached QM analysis reproduces the optimizer's premature convergence: its
internal-coordinate projection reports 2.616e−6 au, while the exact Cartesian
tangent maximum is 4.6722e−5 au, above the unchanged 1.5e−5 limit. A corrected
stopping check is implemented and tested. `cpd-anti-projection-repair-proposal-v1`
prepares at most 15 additional gradients (25 already used; 40 cumulative),
two hours, one restart and no further continuation. This required an explicit
exception because the frozen v2 policy permits zero continuations. The user
subsequently selected a fresh Sella attempt instead; the geomeTRIC correction
remains unlaunched. An obsolete completion wake does not approve that exception.
No torsion fit or full-DNA dynamics may follow from the failed results.

**Fresh Sella attempt — explicitly authorized 2026-09-26:** the user selected
“a from scratch attempt” through Sella. The [frozen attempt record](cpd_anti_sella_attempt_20260926.md)
starts from the original screened 49-atom +15° lower-basin seed, with new optimizer
and Hessian state and no replayed gradients. Sella 2.6.0/Psi4 1.11, unchanged
DF-MP2 method and final force criteria; at most 60 new gradients/six hours,
no automatic continuation. Three regression tests and native analytic/cached-data
interface checks passed without new QM. Artifacts: `cpd-anti-sella-fresh-v1`;
external service/watcher: `cpd-anti-sella-service-v1`. This is a separate versioned
method attempt; the old geomeTRIC continuation remains unlaunched and is no longer
the selected next step. No fitting or full-DNA dynamics is chained to the result.
Completed 19:23 UTC after20 gradients/55.5min; token
`a4dba472-7edd-497e-9d8b-cc0eef55d68c` received and acknowledged. All20 native
energies/printed gradients, hashes and trajectory/export coordinates independently
verified. Final tangent max1.4434545e−5/RMS6.2129007e−6 au and torsion1.219e−8°
pass the original limits; chemistry preserved. **Constrained stationarity only,
no Hessian/minimum certification.** The failed geomeTRIC results remain failed.
`cpd-anti-conformational-inventory-v2b` now contains all15 historical+4lower cases,
retaining exposed branch identities and explicit common-reference proposals.
New+15 is1.41969kcal/mol below the old+15 conformer and2.50790above the lower
reference. No fit or new acquisition was run during this completion review.

**Public-method search — 2026-09-26 UTC:** the requested
[QM/parameterization alternatives review](cpd_qm_md_alternatives_20260926.md)
identifies Sella/DL-FIND as independent optimizers, ORCA plus ffTK as a conventional
CHARMM route, and ForceBalance energy/force fitting as a distinct way to reuse
verified nonstationary QM snapshots. The latter requires a versioned fitting
protocol, not reclassification of failed scan points. The review ran no calculations
and changed no policy; the user subsequently selected the Sella attempt above.

Started 2026-09-20 at the user's request to bring cis-anti-I to cis-syn-I's level.
User-confirmed target: additive CHARMM parity with the preliminary cis-syn v6
candidate. The existing Drude track remains separate; none of its failed gates
is superseded by this campaign. No cloud resources have been allocated.

## Next batch — 2026-09-21

User requested watcher repairs and efficient CPU utilization. The replacement
launcher (`experiments/cpd_anti_additive/launch.py`) freezes execution and watcher
scripts, pins the absolute codex executable and originating thread, and arms a
**separate systemd watcher service before starting computation**. Notifications
use inotify/pidfd, survive computation-cgroup death, preserve tokens/attempts
across retries, record queue exceptions, and deduplicate accepted terminal
notifications. They distinguish supervisor disappearance from scientific success.

Seven fast watcher tests pass. A live supervisor-SIGKILL test in
`cpd-anti-watcher-live-test-v1` survived in its external watcher and queued the
`supervisor_stopped` event, message `01a0c2c1-b941-7002-b2f4-1a8dd357f379`.
Token `97c6c81d-7002-4bdd-a01b-942bc6762215`. Actual originating-session delivery was received and acknowledged at
2026-09-21 07:10:59 UTC (01:10:59 MDT); matching `completion_wake_ack.json`
and `completion_wake_review.json` verify the complete crash → queue → session
wake chain. No duplicate job was launched.

Running/queued work:

- `nadoc-cpd-anti-endpoint2-cartesian-v1`: native unconstrained Cartesian RFO
  retry from original evaluated step 25 (lowest native maximum-force iterate
  passing all graph-distance, sugar and lesion stereochemistry screens).
  Original force 5.40e-4 au is **not converged**. Maximum trust step is 0.1,
  initial 0.05; GAU_TIGHT and the electronic method/convergence are unchanged.
  Four threads pinned to physical cores 12–15, 4 GiB Psi4 / 6 GiB service cap;
  provisional expected 4 hours, overdue 6 hours, hard resource bound 12 hours.
  Exact restart provenance: `cpd-anti-additive-next-v2/endpoint2_restart_audit.json`.
  Output: `cpd-anti-endpoint2-cartesian-v1`; watcher/status: `cpd-anti-endpoint2-service-v1`.
- `nadoc-cpd-anti-scaling-v1` and `nadoc-cpd-anti-scaling3-v1`: identical
  endpoint-1 reference gradients at 2, 3, 4 and 8 threads, 3 GiB per worker.
  Timing copies retain all QCSchema inputs/results; one validated reference
  result is checkpointed into the production Hessian rather than recomputed.
- `nadoc-cpd-anti-endpoint1-hessian-v2`: waits on benchmark exits via pidfd,
  then measures concurrent useful gradient batches at 3×4 and 4×3 (and 4×2
  only if serial scaling justifies it). Initial preference 3×4 changes only
  for >10% measured throughput improvement. Maximum four 3-GiB workers in a
  16-GiB service, initially cores 0–11; no SMT oversubscription. On endpoint-2
  exit an event releases cores 12–15 and enables four workers with the fastest
  measured 2/3/4-thread latency (requires >5% gain to change thread count).
  Completed benchmark/pilot gradient pairs are reused. All 289 immutable tasks
  are then assembled through the established frequency pipeline and independently
  audited for a harmonic minimum. Provisional expected 10 hours, overdue 15,
  resource bound 24 hours. Results: `cpd-anti-endpoint1-hessian-v2`; watcher/status:
  `cpd-anti-hessian-service-v2`. v1 was replaced **while waiting, before any
  Hessian gradient launched**, to add event-driven CPU reclamation.

The completed 3-thread benchmark exposed a terminal-status race: a normal exit
could be labeled supervisor_stopped if it fell between the status read and the
process check. The watcher now rereads the atomically written final status after
observing exit; its dedicated regression passes. The three active watcher services
were restarted with the fix, retaining tokens/receipts and leaving QM untouched.
The preserved original 3-thread receipt still shows the old event label; its actual
status and native gradient result confirm successful computation.

First timings for the identical reference gradient: 2 threads 311.8 s,
3 threads 292.2 s, 4 threads 204.2 s. These are single timings under the then-current
background workload; the useful concurrent pilots, not extrapolation alone,
select final throughput. The 8-thread probe remains part of the registered batch.

Three fast adaptive-scheduling tests pass: exactly-once task coverage, live
process-exit reclamation without timer polling, and task-failure propagation.
The conda-compatible libc pidfd call was also exercised. Native scientific
completion and actual throughput are recorded by the running jobs, not inferred
from these software checks.

The endpoint-1 optimized-audit adapter in `cpd-anti-additive-next-v2` is linked to
the actual hash-verified independent audit; it is not fabricated optimization
history or a minimum claim. Initial preparation v1 failed only on parsing the
optional mass column in intermediate Psi4 geometry tables; v2 preserves that
column's format and selected evaluated geometry correspondence explicitly.

## Status review — 2026-09-21 00:44 MDT

The v2 campaign is terminal, not running. Endpoint 1 converged and passed the
independent geometry/identity/stereochemistry audit at 00:43 MDT; its Hessian
certification remains outstanding. Endpoint 2 stopped at 23:35 MDT with Optking
“Step is far too large” / “Maximum dynamic_level reached”; no optimized target
was exported. Do not rerun endpoint 1. Recover and audit endpoint 2's trajectory
before choosing a bounded optimizer repair; endpoint 1 Hessian and additive
baseline preparation can proceed independently.

Both notification processes failed because systemd's PATH did not contain codex.
Absolute executable paths are now pinned at preparation, checked before watcher
arming, and recorded in watcher_config.json. A restricted-PATH executable check
passes; end-to-end queue delivery has not been retested. No wake delivery is
claimed. Source snapshots and terminal failures are preserved in the v2 root.

Runtime was 3 h 31 min; total CPU use 22 h 28 min (about 6.4 CPU cores on average).
The original allocation was eight threads on a 16-core / 32-thread PC, with
6.6 GiB observed service memory peak. At review, CPU was 97–99% idle and about
21 GiB RAM was available. The campaign does not fully utilize the PC.

## Executed and running

- `cpd-anti-additive-core-baseline-v1`: reconstructed the 36-atom capped anti
  core from the independently recorded bonded graph and hash-checked anti QM
  reference. Explicitly verified C5–C6/C6–C5 crosslinks, 38 bonds and all four
  lesion stereocenters. Published cis-syn types/charges are a **transfer
  hypothesis**, not anti-specific electrostatic validation. Both published
  torsion-table interpretations were retained. The `last` interpretation has
  maximum bond error 0.036573 Å and angle error 6.86516°, despite stationarity
  and positive internal curvature. It fails the unchanged 0.03 Å / 3° targets.
- `cpd-anti-additive-core-angle-v1`: bounded equilibrium-angle training diagnostic
  (±6°, 50 outer evaluations, no changes to charges, force constants or torsions).
  Errors decrease to 0.034607 Å / 3.05908°. Still fails both geometry targets;
  this is not a releasable fit. XML stays isolated; generic type changes must
  never be inserted into DNA force-field files. Joint CPD-specific bond/angle
  fitting across the core and both sugar targets is the next fitting stage.
- `cpd-anti-additive-boundary-qm-v2`: two concurrent 49-atom neutral anti
  glycosidic-fragment optimizations, retaining endpoint 1 or endpoint 2 sugar.
  Start from the independently screened repaired seeds, not the earlier
  wrong-chirality fragment calculations or an interrupted final iterate.
  Frozen-core DF-MP2/6-31G(d), Psi4 1.11, GAU_TIGHT; electronic and optimizer
  settings are unchanged from the prior plan. Four threads / 4 GiB Psi4 per
  endpoint, 14 GiB service cap, no swap, 12-hour wall-time limit. Independent
  native convergence, atom correspondence, sugar and lesion stereochemistry,
  and catastrophic-contact audits follow each successful optimization.
  Geometry optimization alone does not certify positive QM curvature.
- `cpd-anti-additive-boundary-qm-v1` failed before any QM started because the
  conda Python lacks `os.pidfd_open`. Preserved. v2 uses system Python for
  event supervision. No scientific tolerance changed.

All roots are under `.development-artifacts/` (Archive-backed), outside the
user design workspace. No registry, production geometry or supported-isomer
flag was changed.

## Fixed DNA comparison site

User selected `workspace/2hb_1xT_CPD.nadoc`, retaining the existing ordered CPD
pair for all isomer comparisons. Frozen byte-identical snapshot and atom-resolved
site manifest: `cpd-anti-additive-2hb-site-v1`.

- Endpoint 1: `__xb__:4a12dd44-bce2-46be-8296-093ce52d2ec9:0`,
  thymine on `stpl_XY_1_1`.
- Endpoint 2: `__xb__:54c5689d-127b-4693-bc11-f51121719fad:0`,
  thymine on `stpl_XY_0_1`.

Both resolve independently to crossover-extra thymines on different strands.
Measured **world-coordinate** syn crosslinks are 1.6290 and 1.5624 Å; anti
cross-pairs at this unchanged syn geometry are 2.3196 and 2.1905 Å. Stored
`design_coordinates` are before per-residue transforms and must not be measured
as world coordinates. The original design is unchanged. This freezes the site,
not an anti placement; the anti structure must be rebuilt and checked, rather
than relabeling syn coordinates or merely exchanging bonds.

## Verification

The refined core passed an independent four-center stereochemistry audit and
stationarity / step-halved MM curvature check in
`cpd-anti-additive-core-angle-verification-v1`: maximum force
3.243e-6 kcal/mol/Å; smallest internal curvature 0.6850824 and 0.6850817
kcal/mol/Å² at displacement steps 1e-4 and 5e-5 Å. This certifies only the
local MM minimum; the geometry-quality failures remain. Ruff check, Ruff
format check and Python compilation pass for the new experiment scripts.
No app behavior changed or app qualification claimed.

## Supervision and continuation

Completed calculation service: `nadoc-cpd-anti-additive-boundary-qm-v2.service`.
Failed cgroup-exit fallback (notification-path issue above): `nadoc-cpd-anti-additive-boundary-fallback-v2.service`.
The main watcher uses inotify/pidfd; the fallback survives a whole calculation
cgroup timeout/OOM and detects supervisor exit. Both target the exact originating
thread, recorded in `completion_wake.json` and `fallback_armed.json`.
Expected wall time is provisionally 6 hours, with one overdue notification at
9 hours and a 12-hour hard resource bound. These are estimates, not measured
completion guarantees. On wake, acknowledge the recorded token and inspect the
native outputs and per-endpoint audits before continuing. Queue acceptance is
not proof of delivery. Preserve incomplete and failed calculations.

## Remaining parity gates, in dependency order

1. Finish both repaired sugar targets; verify native convergence, exact graph,
   atom identity and all sugar/lesion centers. Certify QM minima with Hessians;
   reuse old core Hessian/response evidence only with matching source hashes.
2. Create anti-specific atom-role aliases and a full-term baseline, then jointly
   fit core and both boundary bonds/angles with the same geometry targets as
   syn. Preserve source force constants unless independent Hessian/PES evidence
   motivates changing them. Freeze before independent validation. Core-only
   angle fitting above cannot establish sugar transfer.
3. Audit the anti additive electrostatics against existing QM targets with the
   correct additive water conventions. Do not import Drude charges, screened
   exclusions or its correlated-water target conventions into additive CHARMM.
   Clearly label all previously exposed data as development/regression evidence.
4. Build complete product nucleotides with correct sugar-interface charges,
   connectivity and term coverage; verify native NAMD/OpenMM energy and forces,
   stationarity, step-halved MM curvature and stereochemistry. Provide concrete
   molecular review artifacts before any normal app geometry integration.
5. Stage explicit-solvent minimization/heating/equilibration followed by three
   anti/control replicas in the intended **interstrand** context. Use ordinary
   masses and ≤2 fs for additive, with box-size/image-distance checks and lesion,
   sugar, backbone and duplex-contact observables comparable to the syn work.
   The syn adjacent intrastrand duplex fixture is not an anti junction fixture.
   Use the fixed `2hb_1xT_CPD` site and explicit ordered keys above; do not infer
   anti connectivity or molecular placement from its syn patch.
6. Review bounded preliminary qualification separately from full scientific
   release. Only then package a portable anti-specific overlay and extend app
   support under the existing geometry authorization requirements.

Reproduce preparation with:

```bash
/home/jojo/miniforge3/envs/nadoc-qm/bin/python \
  experiments/cpd_anti_additive/run_boundary_qm.py \
  --prepare --root .development-artifacts/<fresh-root>
```

Launch using the recorded resource limits and `CODEX_THREAD_ID`; arm the
separate fallback service as well. Existing artifact roots must not be reused.

## Three-thread wake evidence review

Acknowledged token `8b2f07c0-3e2c-45e5-a4bd-d7730f74fe73` in the originating
session. Native task success, plan/input/result hashes and all 147 finite gradient
components verified. The four 2/3/4/8-thread reference gradients use identical
inputs; detailed numerical differences and timings are in
`cpd-anti-scaling3-service-v1/completion_wake_review.json`. The apparent supervisor
stop was the already-fixed status-read race. The existing Hessian scheduler has
advanced to its 3×4 concurrent pilot; no duplicate calculations were launched.

## Endpoint-2 six-hour overdue review

At 07:02 MDT Sep21, native Cartesian optimization reached step77 with decreasing
energy and active derivative calculations. Maximum force 0.00106 au remains
about71 times GAU_TIGHT; this is not near-converged. An independent snapshot
audit retains all sugar/lesion centers, graph-distance and contact screens.
Continue the same process for two hours, then review again; no restart or
tolerance change. The original12-hour hard limit remains. A versioned review
deadline is armed in the independent watcher, preserving all prior receipts.
Evidence: `cpd-anti-endpoint2-overdue-review-v1/`.

Concurrent throughput selected3×4:30.67 gradients/hour versus29.18 for4×3.
The Hessian has212/289 completed reference/pilot/production tasks at this review;
QM processes together consume about15 CPU cores, with15GiB RAM available.

## Endpoint-2 eight-hour overdue review

At09:04 MDT Sep21, step104 has max force2.63e-5 and RMS force9.14e-6 au.
RMS force passes, but max force and both displacement criteria still fail.
Max force improved about40-fold since the previous review. Independent
geometry/sugar/lesion checks still pass. Continue unchanged, with another
review in two hours and the original12-hour hard limit intact. Snapshot,
audit, prior acknowledgment and revised deadline evidence are preserved in
`cpd-anti-endpoint2-overdue-review-v2`. Hessian progress285/289 gradients;
assembly and minimum certification remain pending. No duplicate simulations.

## Endpoint-1 Hessian completion and numerical follow-up

At09:08 MDT Sep21, all289 native gradient tasks completed and their plan/input/
result hashes and147 finite gradient components were independently verified.
The assembled147×147 Hessian passes the registered harmonic-minimum audit:
141 internal modes, zero imaginary, lowest16.2478 cm^-1. Reference maximum
force4.12314e-6 au; matrix asymmetry2.22e-16. This qualifies the endpoint-1
QM fragment under that audit, not the additive force field or solution model.
Evidence: `cpd-anti-hessian-service-v2/completion_wake_review.json`.

Because cross-thread gradient differences reached2.75e-6 au and the lowest mode
is soft, a bounded numerical follow-up is running: `cpd-anti-endpoint1-soft-mode-v1`.
Five MP2/6-31G(d) gradient evaluations (reference and±0.04/±0.02 bohr along the
normalized Cartesian direction of the lowest projected mass-weighted mode),
with SCF E/D convergence1e-12 and response SOLVER_CONVERGENCE1e-10. Three
four-thread workers use cores0–11; endpoint2 continues on12–15. Native response
cutoffs are checked. Prospective checks: reference max force≤1.5e-5 au, positive
directional curvature at both steps, step-halving discrepancy≤10%. This is a
directional numerical check, not a second full Hessian or a new release gate.
Expected30 minutes, overdue45 minutes, hard resource bound2 hours; independent
watcher/status in `cpd-anti-soft-mode-service-v1`. No other optimization restarted.

## Endpoint-1 soft-mode completion and additive boundary baseline

The soft-mode completion wake `ed51acdc-95de-43a9-9af3-4ab8668626d6`
was acknowledged and all five native results, hashes, finite gradients and
response cutoffs checked. Reference maximum force is 3.899787e-6 au.
Directional curvatures at 0.04 and 0.02 bohr are 1.0058648656e-4 and
9.845699924e-5 Eh/bohr²: positive at both steps, with 2.1171% step-halving
discrepancy. All prospective numerical checks pass. The tighter small-step
curvature is 68.05% above the original Hessian directional value; the original
16.2478 cm^-1 should not be treated as a precision-validated frequency. A full
tighter Hessian would be needed before precise low-mode force-constant fitting.
This directional check supports endpoint-1 minimum evidence, not force-field
or solution qualification. Review and acknowledgment are preserved in
`cpd-anti-soft-mode-service-v1/`.

Ran `experiments/cpd_anti_additive/boundary_baseline.py`, producing isolated
`cpd-anti-additive-boundary-baseline-v1/`. The independently audited endpoint-1
QM geometry was compared with the unfitted published additive transfer
hypothesis on the anti graph. All 49 atoms and 52 bonds match the fragment
graph; all sugar and lesion stereo signs survive minimization. Glycosidic bond
error 0.0280723 Å passes the 0.03 Å target, but maximum boundary-angle error
6.09084° fails the 3° target. Across the whole fragment, maximum bond/angle
errors are 0.0336004 Å / 7.60860°. Keep this failed baseline as evidence for
joint anti refinement; it is not simulation-ready.

Prepared `cpd-anti-additive-types-v1/` using `prepare_anti_types.py`: isolated
anti atom-role aliases for core and endpoint-1, with no parameter fitting or
charge changes. Exported CHARMM/OpenMM energies and forces exactly match both
input systems at their recorded coordinates. Endpoint-2 will still need to be
incorporated before shared joint fitting. Use the repository `.venv` Python for
this ParmEd-dependent script; the initial `nadoc-qm` interpreter attempt failed
on import before any artifact creation. Both new scripts pass Ruff checks.

Endpoint-2 optimization and its independent watcher remain active. Next review
is 11:05:22 MDT Sep21, with the original twelve-hour hard limit unchanged.
CPU use is now limited by this remaining optimization gate; the parallel Hessian
and soft-mode tasks are finished. Do not launch duplicates or speculative full
Hessians merely to occupy idle cores. Production readiness remains false.

## Endpoint-2 ten-hour overdue review

At 11:06 MDT Sep21, native step150 has maximum/RMS forces 4.62e-6 /
1.76e-6 au: both pass GAU_TIGHT. Maximum/RMS displacements 1.36e-4 /
4.38e-5 au still fail their 6e-5 / 4e-5 limits. Energy continues decreasing;
independent evaluated-geometry screening preserves all sugar/lesion centers
and passes covalent-distance/contact checks. Continue the existing process
without a restart or tolerance change. Optimization has not converged, and
endpoint-2 minimum certification still requires a Hessian after convergence.

Snapshot, convergence rows, chemistry audit, prior receipts and review script
are retained in `cpd-anti-endpoint2-overdue-review-v3/`. The wake was
acknowledged, and the next review deadline is 12:36:48 MDT Sep21; terminal
notification remains armed. The original twelve-hour service limit (about
13:01 MDT) remains unchanged. No duplicate jobs or cloud spending. The first
review-script invocation used the repository interpreter without RDKit and
failed before creating artifacts; the recorded successful review used
`nadoc-qm` Python.

## Endpoint-2 optimization completion and Hessian launch

At 11:25 MDT Sep21, endpoint-2 completed at native step158. Maximum/RMS
forces are 4.64e-6 / 1.28e-6 au; maximum/RMS displacements are 5.98e-5 /
2.16e-5 au. All four active GAU_TIGHT criteria pass. The independent audit
passes identity, native/result/XYZ agreement, all sugar and lesion centers,
covalent distances and heavy contacts. Audit source hashes were rechecked.
The completion wake was acknowledged with prior overdue receipts preserved.
Optimization completion is not minimum certification.

Prepared 289 distributed gradient tasks in `cpd-anti-endpoint2-frequency-v2/`
and launched `nadoc-cpd-anti-endpoint2-hessian-v1`, with control/status/watcher
in `cpd-anti-endpoint2-hessian-service-v1/`. Four workers each use four threads
and 3 GiB Psi4 memory, restricted to physical cores0–15; service memory cap
18 GiB, no swap, hard limit16 hours. Endpoint-2 optimization is finished, so
its former four-core reservation is available. This extends the previously
measured four-thread worker layout without SMT oversubscription. Expected
runtime8 hours, overdue notification12 hours, terminal notification armed;
actual throughput will determine completion. Confirmed four workers running
and a live independent watcher on the original campaign thread.

The Hessian uses the same immutable v1.7.0 protocol as endpoint-1. Inspect
reference stationarity and all internal modes on completion; use a tighter
soft-direction check if needed given the endpoint-1 numerical sensitivity.
No force-constant fitting should assume precision of the lowest modes.
`cpd-anti-endpoint2-frequency-v1/` preserves an unsuccessful preparation:
the first script expected the wrong native success-marker wording. No QM
was launched by that attempt. The v2 preparation checks the actual final
geometry marker plus all four explicit convergence criteria. Production
readiness remains false; no duplicate simulations or cloud spending.

## Endpoint-2 Hessian completion and joint-refinement preparation

At 17:27 MDT Sep21, the endpoint-2 Hessian finished in 6.02 hours. All289
native task success records, input/plan/result hashes and147 finite gradient
components per task were reverified, together with the assembled Hessian and
frequency output hashes. Reference maximum gradient4.97706e-6 au. The
frequency audit passes candidate harmonic minimum:141 internal modes, zero
imaginary, lowest28.1170 cm^-1; Hessian asymmetry1.11e-16. The requested
completion acknowledgment and review are in `cpd-anti-endpoint2-hessian-service-v1`.
This is QM minimum evidence, not additive or solution qualification.

A five-gradient tighter soft-mode follow-up is running in
`cpd-anti-endpoint2-soft-mode-v1`, controlled by
`cpd-anti-endpoint2-soft-mode-service-v1`. It uses the same prospectively
specified two steps (±0.04/±0.02 bohr), electronic/response tolerances and
pass criteria as endpoint1. Three four-thread workers use cores0–11, with
14 GiB service cap, no swap, expected30 minutes, overdue45 minutes, hard
limit2 hours. Independent watcher confirmed live and armed. No duplicate
Hessian jobs. The original numerical frequency remains provisional in
precision until this check is reviewed.

Ran the endpoint2 additive transfer baseline in
`cpd-anti-additive-boundary-endpoint2-v1`: glycosidic bond error0.00527143 Å
passes; boundary angle error7.82837° fails. Whole-fragment maximum bond error
0.0323846 Å also fails. All sugar and lesion stereochemistry is preserved.
This failed baseline remains available for joint core/endpoint1/endpoint2
refinement. `boundary_baseline.py` now takes explicit --root, --endpoint and
--audit arguments and checks matching model identity and atom order.

Prepared `cpd-anti-additive-types-v2` across core and both sugar endpoints.
Role/type alias export reproduces input energies and forces exactly for all
three recorded coordinate sets. It contains no fitted parameters or changed
charges. The earlier v1 candidate remains preserved. Native MM/export checks
and Ruff passed for the edited experiment scripts. Next: review endpoint2
soft-mode evidence, then joint refinement and anti electrostatic targets;
keep all DNA/interstrand and force-field release gates separate.

## Endpoint-2 soft-mode review and additive training launch

At 17:39 MDT Sep21, endpoint2 tighter soft-mode check completed. Verified all
five input/plan/native/result hashes,49×3 finite gradients and response cutoffs
≤1e-10. Reference maximum force4.53412e-6 au. Directional curvatures at0.04 /
0.02 bohr:1.4427726317e-4 /1.4455924036e-4 Eh/bohr²; both positive,
step-halving discrepancy0.19506%, small-step stiffness5.24968% lower than the
original Hessian. All registered checks pass. Acknowledgment and native review
are preserved in `cpd-anti-endpoint2-soft-mode-service-v1`. Both sugar fragments
now have optimization, harmonic-minimum and tighter soft-direction evidence;
this does not qualify additive parameters or the interstrand DNA model.

Started local HF/6-31G(d) ESP and dipole targets for both audited fragments:
`cpd-anti-boundary-esp-v1`, controlled by `cpd-anti-boundary-esp-service-v1`.
Uses the registered deterministic four-shell grid and immutable protocol,
two four-thread workers on physical cores0–7,3 GiB per worker,10 GiB service
cap, expected30 minutes, overdue45 minutes, hard limit2 hours. These are
charge-training targets; water interaction and transfer validation remain.

Concurrently started bounded joint additive geometry training across core and
both endpoints in `cpd-anti-joint-fit-v1`, controlled by
`cpd-anti-joint-fit-service-v1`. Anti-specific aliases isolate103 shared
bond/angle equilibrium groups, with maximum shifts0.01 Å /6° and fixed
force constants, charges and torsions. The inherited syn training algorithm
now uses anti crosslink neighbors in every lesion stereochemistry check.
Acceptance remains all bond errors≤0.03 Å, all angle errors≤3°, preserved
sugar/lesion stereochemistry; fitting is training, not independent validation.
The fit uses one BLAS thread and is confined to cores8–15 (serial minimization/
response solves do not benefit from reserving eight workers). Service cap6 GiB,
expected30 minutes, overdue45 minutes, hard limit3 hours. Both independent
watchers are armed; no duplicate jobs, cloud spending or production changes.

### Immediate training results and ESP protocol correction

Both initial training services completed in about34 seconds, with terminal wakes
acknowledged and reviews recorded. The bounded joint fit preserves all sugar
and lesion centers but fails the geometry thresholds: endpoint1 max angle/bond
errors4.10848°/0.0304743 Å; endpoint2 5.35985°/0.0288891 Å; core
3.26067°/0.0298076 Å. All final MM forces are small, but this is not independent
MM minimum certification or accepted geometry. Preserve the failed candidate;
do not expand bounds just to force a pass. Charge-sensitive geometry and
parameter-group residuals need review before choosing the next fit.

ESP v1 produced finite, hash-verified1289/1287-point potential targets, but
its default helper protocol omitted the requested dipole: the default protocol
was older than v1.7.0. These ESP-only results are retained as incomplete for the
intended combined target. Corrected `boundary_esp.py` to explicitly pin v1.7.0
and require a passing ESP audit plus a finite dipole. A distinct corrected
calculation is running in `cpd-anti-boundary-esp-v2`, with independent watcher
`cpd-anti-boundary-esp-service-v2`; identical resource limits, no overlapping
original calculations. The prior claim that v1 generated dipoles was incorrect.
Next review should verify v2 native outputs and dipoles, then assess charge
transfer and joint-fit residuals. No production gates advanced.

## Joint-fit v1 completion wake: optimizer-budget diagnosis

Reviewed and acknowledged token8bb46122-5efd-4b2f-9c24-90599d0646c1.
Reverified the joint-fit source hashes and native optimizer/report evidence.
The command returned zero, but optimizer_success is false: the maximum40
function evaluations were exhausted. There are38/103 normalized shifts
within1% of a bound. All geometry acceptance failures reported above remain.
The largest errors are opposite-signed C1'-N1-C6 angles in the two sugar
endpoints (−4.10848° /+5.35985°); this suggests a shared-parameter compromise,
not a reason to alter anti chemistry or automatically split types.

Launched one warm-start continuation with the same targets, regularization,
103 parameter groups,0.01 Å/6° limits, unchanged charges/constants/torsions,
and unchanged acceptance criteria: `cpd-anti-joint-fit-v2`, controlled by
`cpd-anti-joint-fit-service-v2`. Maximum200 evaluations, expected10 minutes,
overdue15 minutes, hard limit1 hour,6 GiB cap, single BLAS thread on cores8–15.
This tests whether the evaluation budget was limiting; it does not expand
scientific bounds. Previous failures remain intact. Watcher confirmed live
and armed; corrected ESP v2 was still running at launch. Native completion
of either service requires reviewing scientific results separately.

### Same-turn continuation result

The short continuation completed before handoff; its terminal watcher delivered
and exited normally. Optimizer now satisfies ftol, but geometry still fails:
endpoint1 4.10479°/0.0304360 Å, endpoint2 5.36614°/0.0288887 Å, core
3.26118°/0.0298012 Å. Stereo retained. More evaluation budget did not fix the
shared-model mismatch; do not repeatedly restart this objective.

Corrected ESP v2 also finished. Both native output/potential hashes and target
audits were verified:1289/1287 ESP points, with dipole magnitudes2.72032 /
1.38613 e·bohr. Both required dipole vectors are present and finite. Completion
receipts and reviews for both v2 services are recorded. No jobs remain running
in these two services. Next useful work is assessing transferred charges against
these targets and water interactions, and investigating the conflicting shared
angle residuals before any new parameter fit. Qualification remains incomplete.

## ESP v1 late wake, transferred-charge diagnostic and water calibration

Acknowledged late token424a2ab5-dae1-41f5-a70e-73ed2c8fb339; reverified both
v1 native output and potential hashes. V1 is valid ESP-only evidence, incomplete
for the requested dipole target and superseded by verified v2. No rerun.

Computed `cpd-anti-charge-transfer-diagnostic-v1` at the actual audited QM
geometries with unchanged additive charges and the v2 potential grids.
Endpoint1/2 ESP RMS errors0.0108337/0.0103720 au, relative RMS errors51.925% /
57.350%; gas-phase HF versus MM dipole-vector errors0.87971/1.50292 D and
angular deviations6.8297°/17.8050°. These are unscaled diagnostic comparisons,
not retrospectively selected acceptance thresholds, charge fitting, or an
independent validation set. Both fragment charge sums remain neutral.

Prepared and launched `cpd-anti-water-calibration-v1`, controlled by
`cpd-anti-water-calibration-service-v1`: identical-geometry DF/DIRECT
HF/6-31G(d) interaction pairs at three sites per endpoint (1:O2,2:O4 and
attached endpoint H3 on N3), twelve native jobs total. TIP3P target-probe
separation1.9 Å; chose the least crowded of0/120/240° azimuths and verified
all non-target intermolecular separations≥1.1 covalent-radius sums. This is
a deterministic clash screen, not optimum water orientation or a complete
interaction curve. Explicit v1.7.0 protocol uses neutral interaction scaling1.16
and distance offset−0.2 Å; the DF/DIRECT tolerance remains0.02 kcal/mol.
Each endpoint has its own three-site calibration audit.

Four four-thread workers on physical cores0–15,3 GiB each,18 GiB service cap,
no swap; expected1 hour, overdue90 minutes, hard limit4 hours. Independent
watcher handles terminal events. Generate production distance curves only
after this calibration is reviewed. Joint geometry failures remain preserved;
no new charge candidate or production flag has been accepted. Ruff and native
preparation checks passed for both new experimental scripts.

## Corrected ESP v2 late wake and screened distance-grid preparation

Acknowledged token4752ce62-ddfc-4b87-a4a4-49d35d592a27 and reverified both
v1.7.0 ESP/dipole jobs, source XYZ/parent/input/grid hashes, native output and
potential hashes, and complete dipole vectors. Both are training targets, not
charge validation. No duplicate calculations were launched.

While the twelve-job DF/DIRECT calibration remains active, prepared
`cpd-anti-water-curve-plans-v1`: six sites on each endpoint (O2,O4,N3–H3 on
both bases), each with seven target-probe distances1.5–2.7 Å in0.2 Å steps.
All twelve site grids pass the registered non-target distance screen at every
point, using the least crowded of0/120/240° water azimuths. All candidate
orientation screen values are retained, not only the chosen orientation.
This yields84 prospective interaction points, not executed jobs. Orientation
and distance minima still require scientific review; a curve minimum at an
edge requires extension, not an accepted fitted target.

Execution remains gated on each endpoint's passed three-site DF/DIRECT audit.
The future generator must explicitly pass protocol v1.7.0 to
`generate_water_interaction_job`; do not rely on older helper defaults. Scripts
and preparation passed Ruff/native checks. No release or minimum gate changed.

## Joint-fit v2 late wake and independent MM numerical checks

Acknowledged token085c693f-26d1-480e-a569-9190edd883e4. Reverified all fit-input
and warm-start hashes. Native optimizer ftol termination is genuine, while all
three geometric training cases still fail their existing acceptance criteria.
No duplicate fit or relaxed criterion was introduced.

Ran `verify_joint_candidate.py`, retaining results in
`cpd-anti-joint-fit-verification-v1`. Independent force evaluation and projected
MM Hessians at1e-4 and5e-5 Å steps show stationary positive-curvature minima
for core and both sugar fragments. Maximum forces≤6.59e-6 kcal/mol/Å;
smallest internal curvatures at the halved step are0.5679702,0.3929877,
0.1155391 kcal/mol/Å² respectively, all with zero negative internal modes.
Reloading the exported CHARMM parameters reproduces candidate XML energies
within4.08e-10 kcal/mol and forces within6.03e-9 kcal/mol/Å. These checks
support numerical stability/export correctness only; the geometry and charge
mismatches remain. They do not qualify a force field or DNA simulation.

Water calibration was still running at this review. Its existing watcher
remains responsible for the next computational gate; the84 screened water
curve points remain unlaunched pending calibration. All failed candidates and
native outputs are retained; no cloud spending.

## Water calibration completion and production distance curves

Acknowledged token9bc6f626-f3b3-4ac2-b90d-6d2a20391946. Reverified all12
native calibration jobs and their model/water/parent/input hashes, and reran
the calibration audit independently from native outputs. Both endpoint audits
pass: maximum DF/DIRECT interaction errors0.00387297 and0.00448968 kcal/mol
versus0.02 tolerance, covering three distinct sites per endpoint. These
validate the sampled SCF approximation, not charges or a molecular minimum.
Independent reviews reside in `cpd-anti-water-calibration-service-v1`.

Launched the screened distance curves in `cpd-anti-water-curves-v2`, controlled
by `cpd-anti-water-curves-service-v1`. There are84 points over12 sites; six
identical calibration DF geometries are reused through their original immutable
job directories after model/protocol/coordinate matching, leaving78 new jobs.
All new jobs explicitly use protocol v1.7.0. Four four-thread workers on
physical cores0–15,3 GiB per worker,18 GiB service cap, no swap; expected1 hour,
overdue90 minutes, hard limit4 hours. Terminal watcher and progress.json track
completion. Each seven-point curve will be audited separately; an unbracketed
minimum remains incomplete and requires extension before charge fitting.
No charge fit, additive release or DNA validation is implied by job completion.

Preserved `cpd-anti-water-curves-v1` preparation failure: a NumPy boolean reuse
flag could not serialize into the plan. No QM jobs were launched from v1.
The corrected v2 casts that flag to a native bool and passed native preparation
and Ruff checks. No duplicate computations or cloud spending.

## Water-curve completion and initial bounded charge candidates

Acknowledged tokenc6266ae5-9ab1-47e4-b3e9-5fe9a23af119. All84 native
output/input/model/water/parent provenance chains verify, including six reused
calibration points. All12 seven-point curves have bracketed minima and pass
the curve audit. This is complete charge-target evidence, not charge acceptance
or molecular minimum certification.

`cpd-anti-water-transfer-diagnostic-v1` evaluates unchanged published-transfer
charges and CHARMM TIP3P (including hydrogen LJ) on these curves, with no
relevant pair-specific NBFIX terms. QM interaction energies use1.16 scaling;
QM minima use the registered−0.2 Å distance offset. Local three-point parabolas
interpolate both minima. N3–H3 contacts overbind by3.37–4.27 kcal/mol; carbonyl
errors range−2.10 to+0.76 kcal/mol. All MM minima are bracketed. This explains
why the transferred charge hypothesis needs refinement independent of the
remaining bonded-geometry compromise.

Ran `cpd-anti-charge-candidates-v1`: three prospectively recorded L2 restraint
strengths (1,10,100) with per-atom charge shifts bounded±0.15e. The28 stable
base atoms have shared charges across the two fragments; sugar/caps and all LJ
and bonded parameters remain fixed. Constraints preserve neutral totals and
equal methyl-H shifts within each base. Objective combines ESP and three
near-minimum water points per site, evaluating MM water at the−0.2 Å shifted
separations. All inputs are explicitly development data. No independent holdout
or final charge acceptance is claimed; dipoles are diagnostics outside the fit
objective. No charge candidate was exported into PSF or production.

All three numerical optimizations converge. The least restrained candidate
has ESP relative RMS errors38.77%/43.41% (baseline51.93%/57.35%), dipole-vector
errors0.316/0.921 D, and maximum water-minimum energy errors1.328/1.443 kcal/mol.
The more restrained candidates improve less. These residuals remain material;
do not label the candidate accepted because the optimizer converged. Next:
independent charge/geometry transfer checks and parameterization tradeoff review
before selecting charges and revisiting bonded fitting. Prior failed geometry
and original charge baselines remain intact. Native calculations and experiment
Ruff checks completed; no duplicate jobs or cloud spending.

## Overall-status and progress-visualizer refresh

Regenerated Help → CPD progress from current retained evidence. Replaced stale
anti “stopped/deferred” studies with audited QM minimum coordinates and checks;
added three separate additive training structures with per-atom/bond angle and
length failures, stereochemistry, MM-curvature/export checks, charge-target
progress and pending interstrand validation. Anti gallery campaign checks and
overall summary now agree with this document. Gallery illustrative coordinates,
normal application geometry and registry qualification remain unchanged.

At refresh, no CPD calculation services were running: reference targets are
complete, while parameter selection/refinement and independent transfer/DNA
validation remain. Cis-syn retains preliminary v6 integration and its existing
finite DNA stability evidence, with the unresolved lesion-site conformational
finding separate from release qualification. Anti is not yet at that level.

Verification: all6590 frontend tests (458 files) passed; all3 CPD Chromium
browser tests passed after updating the obsolete starting-structure assertion.
The new browser check explicitly inspects anti QM and failed additive studies.
Evidence references resolve; Ruff and diff-whitespace checks pass. Verified
Playwright reports/screenshots and test workspace artifacts cleaned after run.
Refresh review saved in `cpd-progress-refresh-v1/review.json`.

## Next geometry/charge set: controlled coupling and retrospective transfer

User authorized another set for failed geometry and charge candidates. Prepared
`cpd-anti-coupled-round-v1` and launched independent watched service
`cpd-anti-coupled-round-service-v1`. Five tasks: three joint geometry fits using
existing charge strengths1/10/100 and two charge fits each trained on one sugar
endpoint and evaluated on both. The latter are retrospective transfer checks,
not blind validation, since both fragments already informed development.

Charge-assignment preparation verifies exact candidate charges in each endpoint,
neutral totals in all three compounds, unchanged sugar/cap charges and graph,
and successful standalone CHARMM system creation. Core receives the same stable
base-atom shifts, retaining neutral methyl caps. Charge-dependent nonbonded
exceptions are regenerated from each new PSF. Isolated artifacts only; no normal
app/production PSF is changed.

All three geometry fits retain the original±0.01 Å/±6° parameter bounds,
fixed force constants/LJ/torsions, and≤0.03 Å/≤3° geometry criteria. They start
from the previous joint equilibrium-parameter shifts and receive200 evaluations;
no repeat of the unchanged baseline. Endpoint transfer repeats the same three
charge restraints and±0.15e bounds, with the opposite endpoint excluded from
the fitting objective. Record both improvements and regressions; no charge
candidate is selected merely because it gives a better training score.

Three concurrent tasks, one BLAS/OpenMP thread each, on physical cores0–15;
these small MM-response problems do not benefit from16-thread BLAS. Service
memory cap12 GiB, no swap, expected20 minutes, overdue30 minutes, hard limit2h.
Completion watcher targets the existing campaign session. Preparation and Ruff
checks passed; preserve any failed tasks. No cloud spending.

## Coupled-round completion: charges do not resolve the geometry compromise

Acknowledged tokenda9fa588-cfbb-4530-ba40-bdd8736e7a70. Verified all five
assessment hashes and fit-source hashes against the registered plans. Every
optimizer converged, but all three charge-dependent geometry fits still fail:
endpoint1 angles4.05–4.10° and bonds0.03051–0.03067 Å; endpoint2 angles
5.37–5.42°; core angles3.24–3.26°. All stereocenters survive. These new
candidates have no independent MM Hessian certification yet; optimizer success
is not minimum certification or geometry acceptance. No charge set is accepted.

Retrospective leave-one-endpoint-out fits worsen on the excluded fragment.
For restraint1, train endpoint1→evaluate endpoint2: ESP relative RMS46.9%,
dipole-vector error1.374 D, max water-energy error1.890 kcal/mol. Reverse:
41.6%,0.455 D,1.739 kcal/mol. Both fragments are previously seen development
data; these results are sensitivity/transfer diagnostics, not blind validation.
The existing joint charge candidate remains exploratory.

Started the next isolated diagnostic: `cpd-anti-ordered-types-v1` retains the
ordered endpoint number in each atom-role alias, rather than tying same-named
atoms across the stereochemically distinct anti endpoints. Terms for each
ordered endpoint remain shared between core and sugar models. All three
pre-fit energies and forces exactly reproduce the original additive baseline,
so aliasing alone changes no physics. Charges, LJ and force constants are fixed.

`cpd-anti-ordered-fit-v1`, controlled by `cpd-anti-ordered-fit-service-v1`, fits
this alternative grouping with the original±6°/±0.01 Å limits and≤3°/≤0.03 Å
criteria,200 evaluations, starting from zero shifts (old alias names cannot
safely transfer previous parameter shifts). This tests the cross-endpoint
sharing assumption; extra parameters do not by themselves establish physical
validity. Single BLAS thread on cores8–15,6 GiB cap, expected10 minutes,
overdue15 minutes, hard limit1h, independent watcher. No cloud spending.
Progress snapshot now records coupled-round failures and this pending diagnostic.

## Ordered-endpoint geometry success and charge-coupled verification

Acknowledged token83c1c68f-0437-4ff4-9f36-01706daad72e and verified native
fit/source evidence. The ordered-endpoint hypothesis passes all three original
geometry criteria, with maximum angle/bond errors: core2.34462°/0.0267218 Å,
endpoint1 2.61156°/0.0261182 Å, endpoint2 2.89065°/0.0288070 Å. All stereo
signs remain correct. These are fitted training results, not new independent
reference data. Independent two-step MM curvature, stationarity and CHARMM
export checks also pass (`cpd-anti-ordered-verification-v1`).

Then ran `cpd-anti-ordered-coupled-v1` (service `cpd-anti-ordered-coupled-service-v1`):
three pre-existing charge hypotheses with ordered-endpoint typing, same bounds,
and the ordered baseline's fitted parameter shifts as initialization. No
retrospective charge-fit jobs were duplicated. All three optimizers converged,
and all nine compound/charge combinations pass geometry and stereo checks.
Maximum angle error across them2.89040°; maximum bond error0.0288074 Å.
The least restrained charge candidate gives core2.22659°, endpoint1 2.52372°,
endpoint2 2.88964°, with all bonds within0.0288049 Å. No charge selection or
release is implied by these geometry results.

Independent verification for all nine systems is retained in
`cpd-anti-ordered-coupled-verification-{1,10,100}-v1`: every system is stationary,
has positive projected internal curvature at both finite-difference steps,
and reproduces its CHARMM export to the declared numerical tolerance. The
coupled service finished during this review; its wake was acknowledged and
scientific results recorded. No jobs remain active in these services.

Progress visualizer now retains the historical failed shared-role candidates,
adds the three successful ordered-endpoint baseline training structures, and
reports successful charge-coupled geometry separately from unresolved charge
accuracy/transfer and interstrand DNA validation. Numerical minimum evidence
is not electrostatic qualification. Next work should obtain independent
conformational/energetic validation of the enlarged parameter grouping and
resolve charge/water residuals before DNA qualification. No cloud spending.

## Ordered-coupled late wake and fresh conformational probes

Acknowledged token477a9c9e-9cf7-488b-b6e7-afc96751e610 and rechecked the three
fit assessments plus all nine independent MM-verification source hashes.
Geometry, stereochemistry, stationary internal curvature and CHARMM exports
remain passed within their documented isolated training scope. No repeated fits.

Prepared and launched `cpd-anti-glycosidic-probes-v1`, controlled by
`cpd-anti-glycosidic-probes-service-v1`. Four new MP2/6-31G(d) gradient/energy
calculations rotate the17 sugar atoms rigidly by±15° about N1–C1' for each
endpoint. Core/caps stay fixed. All graph-bond lengths remain unchanged within
1e-8 Å, all degree-four tetrahedral signs are preserved, and every nonbonded
heavy-atom separation exceeds one covalent-radius sum. Reference energies and
coordinates reuse the verified tighter soft-mode reference jobs, avoiding two
duplicate calculations. Electronic E/D1e-12 and response1e-10 match those
references. The original preparation snapshot is retained; a closure-binding
lint fix in the comparison code is separately hashed in the plan's runner record.

On completion compare relative energies and dE/dtheta at exactly the same
coordinates against the baseline ordered model and all three charge-coupled
models, without refitting. These are fresh fixed-geometry response diagnostics,
not relaxed torsion profiles, new minima, solution validation or predetermined
release gates. Four four-thread workers use physical cores0–15,3 GiB each,
18 GiB service cap, expected30 minutes, overdue45 minutes, hard limit2 hours.
External watcher is armed; progress visualizer includes the pending probes.
No cloud spending or production changes.

## Fresh ±15° probes reveal off-minimum nonbonded mismatch

Acknowledged token52bd636c-5f82-4785-a7b1-1856c26a6ba4. Reverified all four
native result/input/plan/output hashes,147 finite gradient components per job,
response tolerances, both reused reference results and all compared MM systems.
No fixed-geometry probe is called a minimum. Endpoint1−15°: QM relative energy
1.4068 kcal/mol versus MM8.71–8.90; endpoint2+15°: QM3.9683 versus
MM12.73–13.02. Other directions agree more closely. Charge changes do not
resolve the large asymmetric errors. These probes remain unre-fitted evidence.

Force-group decomposition (`cpd-anti-glycosidic-decomposition-v1`) finds bond,
angle and Urey–Bradley changes numerically zero under the rigid rotation;
periodic torsion changes are small. Exact pair decomposition
(`cpd-anti-glycosidic-pairs-v1`) reproduces OpenMM nonbonded deltas within1e-5
kcal/mol: the high-penalty directions contribute LJ+9.0468/+15.4799 kcal/mol
and Coulomb−0.3779/−1.4153 respectively. Leading contacts involve sugar O5'
and the opposite base methyl hydrogens/carbon. This is a capped-fragment,
rigid-rotation diagnostic; do not soften LJ or fit compensating torsions solely
to these points, nor assume the same contact behavior in a full DNA boundary.

Launched four smaller±7.5° probes in `cpd-anti-glycosidic-half-probes-v2`,
controlled by `cpd-anti-glycosidic-half-probes-service-v2`. Same reference reuse,
method/tolerances, graph/stereo/contact screens, candidate comparison and
resources as±15°. This checks whether mismatch extends close to the minimum.
The first half-step preparation failed because its label formatter expected an
integer angle; the accompanying service failed for missing plan before any QM
ran. Both v1 failures are preserved. Corrected v2 prepared successfully and
runs with an independent watcher; no duplicates or cloud spending. Progress
visualizer reports the energetic mismatch and pending smaller probes.

### Late failed-v1 notification review

Acknowledged tokenc1d6f8ac-c4fa-447d-ab33-4200e8b0c905. Confirmed the preserved
v1 failure is the missing-plan consequence of integer angle-label formatting;
there are no v1 native outputs or QM result files. Rechecked all four corrected
v2 input hashes and native-output presence. Its supervisor and watcher are
live; continue that run unchanged. No duplicate jobs or new scientific verdict.

## Half-angle probe completion and constrained-relaxation next set

Acknowledged token6343a3c4-ba2c-490a-8281-89796ae6e5e7. Verified four native
input/plan/output/result chains, finite gradients and response cutoffs, reused
references and compared MM-system hashes. At endpoint1−7.5°, QM relative
energy0.4437 kcal/mol versus MM2.6386–2.7313; at endpoint2+7.5°, QM0.8413
versus MM2.0887–2.2262. Angular energy derivatives also disagree. Thus the
asymmetric mismatch persists near the QM minimum, not only at±15°. These
are fixed-geometry response probes, not unconstrained minima or fitted targets.

Prepared four constrained relaxed±15° points in `cpd-anti-relaxed-glycosidic-v1`,
controlled by `cpd-anti-relaxed-glycosidic-service-v1`. Reuse previously screened
±15° seeds, explicit C2–N1–C1'–O4' dihedral and hash-pinned model graph. The
registered v1.7.0 generator verifies that N1–C1' is a real acyclic single bond
and that each starting torsion agrees with its target. It freezes that dihedral
and relaxes other coordinates with MP2/6-31G(d), frozen core, GAU_TIGHT and
the generator's existing default optimizer/electronic convergence policy.
Unlike the tighter fixed probes, these use the unmodified registered torsion
input; review numerical tolerances before any fine energy comparison.

Four four-thread jobs, physical cores0–15,3 GiB per job,18 GiB service cap,
no swap, expected6 hours, overdue9 hours, hard limit12 hours. Jobs fail
individually without discarding other results; native outputs are retained.
Completion includes a constraint/tetrahedral/covalent-distance screen, followed
by independent review. Constrained convergence is not unconstrained harmonic
minimum certification, and these four points are not a full torsion profile.
No force-field parameters were changed. The next comparison requires matched
constrained MM relaxation and checks for contact/cap artifacts, rather than
fitting compensating charges or torsions to rigid-probe errors. Visualizer
reports both probe mismatches and the pending relaxed points. No cloud spending.

## Constrained-relaxation overdue review — 2026-09-22

Acknowledged overdue token a182d768-6742-491f-83d6-f6919348775a at
15:27 UTC. All four native runs remain active, with no completed optimizer
or final geometry audit. Latest completed iterations at review: endpoint1−15
41, endpoint1+15 31, endpoint2−15 41, endpoint2+15 43. Endpoint1−15 meets
force thresholds but not displacement thresholds; endpoint2−15 still has
large forces. Native output hashes and convergence rows are retained in
`cpd-anti-relaxed-glycosidic-service-v1/overdue_review_20260922.json`.
Continue these workers under the existing 12-hour hard limit, without
restarting or launching duplicates. The watcher delivered overdue successfully
and remains waiting for completion/failure. CPU use averaged about 3.3 cores
over nine hours; cgroup I/O pressure was substantial, with no OOM kills or CPU
quota throttling. Do not infer a CPU benefit from adding more concurrent jobs.
Progress JSON was regenerated successfully (14 evidence structures). No new
minimum certification, parameter acceptance, or DNA-validation readiness.

## Hard-timeout reconciliation — 2026-09-22 12:45 MDT

Systemd stopped the constrained-relaxation service at12:25:09 MDT after its
12-hour cap (Result=timeout). Endpoint1−15 completed at12:12 after46 steps;
its native success marker, output/optimized-coordinate hashes and passing
constraint/stereochemistry/covalent screen were verified. Endpoint1+15,
endpoint2+15 and endpoint2−15 were interrupted after last complete iterations
40,46 and48 respectively; none is accepted as converged. All native files
remain intact. No unconstrained harmonic minimum is certified by this batch.

The killed supervisor left stale running status. Preserved that status and
systemd journal, then reconciled status.json to failed with per-point outcomes.
The watcher remained alive with its pidfd already consumed and only inotify
open, consistent with observing exit while /proc identity still existed and
then waiting indefinitely. Watcher now retains the authoritative process_exit
event rather than discarding it; a regression covers lingering /proc identity.
Updating status wakes the existing watcher. No duplicate QM jobs were started.
Next scientific work remains matched constrained MM relaxation and reviewed
continuations for the three incomplete points, with reduced disk contention.

## Reviewed continuations — 2026-09-22

Acknowledged supervisor_stopped token a182d768-6742-491f-83d6-f6919348775a,
preserving the previous overdue acknowledgement. Prepared three coordinate
continuations in `cpd-anti-relaxed-glycosidic-v2`, controlled by
`cpd-anti-relaxed-glycosidic-service-v2`. Each latest native evaluation geometry
passes original-atom-order, graph bond-distance, tetrahedral-sign and fixed-angle
checks. Sources are hash-pinned; these are fresh optimizer histories, not binary
restarts. The successful endpoint1−15 point is reused, never recomputed.

Keep registered MP2/6-31G(d), frozen-core, GAU_TIGHT/default electronic policy.
Use two concurrent four-thread workers with6GiB each and local scratch under
`/home/jojo/.cache/nadoc-qm/cpd-anti-relaxed-continuation-v2`, rather than four
workers contending on the archive disk. Local disk initially has34GiB free;
each task refuses to start below15GiB free. Prior scratch was about4.3GiB per
unfinished job. Service cap20GiB, no swap,24h hard limit,6h expected/9h overdue.
Scratch is retained on failure; old raw evidence is untouched. Corrected watcher
retains pidfd exit evidence. Native launch/status and independent watcher checked.
No cloud use or parameter promotion; matched constrained MM comparison remains
pending after the required QM geometries.

## Continuation failure review and tighter follow-up — 2026-09-22

Acknowledged v2 failed token7ba6f8e7-4090-4bac-bcc1-f11283bcf656. All three
native runs failed at50 optimizer iterations, not missing input or disk space.
Verified native output hashes against run manifests. The wrapper attempted a
geometry audit after failed native execution and obscured the cause with absent
optimized.xyz; it now reports native failure and its manifest before auditing.
Endpoint2+15 meets force criteria but misses maximum displacement; the other
two retain larger residual forces. Local scratch reduced50-step runs to about
1h53–2h15; no new constrained convergence or minimum certification.

Prepared fresh screened last-evaluation-coordinate continuations. v3 used an
invalid CPHF_CONVERGENCE option and failed immediately before QM; preserved.
Corrected v4 uses installed-Psi4-verified CPHF_R_CONVERGENCE=1e-10,
SCF E/D=1e-12, GEOM_MAXITER=150. The GAU_TIGHT geometry criteria, MP2 method,
basis, frozen core, fixed torsion and chemistry remain unchanged. This is an
explicit campaign override recorded with hashes in each new job manifest,
not the unmodified registered protocol. v4 has two4-thread6GiB workers,
local versioned scratch,20GiB service cap/no swap,24h hard cap,8h expected
and12h overdue. v2 and v3 raw failures remain intact; v1 successful point reused.
The independent watcher is armed. Progress snapshot reflects the new attempt.

## Post-reboot recovery — 2026-09-23

System journal records v4 stopped during host shutdown Sep22 at19:08:06 MDT;
current boot began19:08:24. No QM workers or watcher survived. Preserved stale
running status and journal; reconciled v4 as interrupted, not completed.
Endpoint1+15 last completed step47 still had substantial force residual;
endpoint2−15 step46 remained unconverged. Endpoint2+15 never started.

Prepared v5 from the latest printed evaluation geometries of the two interrupted
points, retaining the queued point's original v2 native seed. All three pass
atom-order, covalent-distance, tetrahedral-sign and fixed-angle screens. This is
a fresh optimizer history; no false binary-checkpoint restart claim. Successful
v1 endpoint1−15 is still reused. Retain v4 method/SCF/optimizer settings and
resource limits: two4-thread6GiB workers, local scratch,20GiB service cap,
24h hard runtime,8h expected/12h overdue. New independent watcher pins the
installed26.917.62051 Codex executable; original thread retained. v5 native
start and armed watcher verified. Progress snapshot updated.

Numerical caveat discovered during recovery: despite the global
CPHF_R_CONVERGENCE=1e-10 setting, v4 native CGR output converged near1e-6.
Do not claim a verified1e-10 MP2 response solve from that option alone.
Native response tolerance must be resolved before fine energy/gradient
comparisons; resumption does not promote these geometries or certify minima.

## Adaptive optimization update — 2026-09-23

Literature review and implemented policy are in `docs/cpd_optimization_strategy.md`.
Added experiment-only per-evaluation stall/excursion/nonfinite/budget detection,
evaluated-geometry/gradient checkpoints, and bounded native adaptive trust/backsteps.
Five unit tests and a real Psi4 smoke optimization passed. Retrospective v5 replay
flags failures at16/36steps; these are diagnostic heuristics, not proof or minimum
certification. Stopped remaining v5 after repeated excursions and preserved its
outputs/status. v6 is a single endpoint2+15 pilot from screened near-converged v2,
with other points held. Uses actual SOLVER_CONVERGENCE control; native verification
required. Independent watcher pins current executable; progress snapshot updated.
No cloud use or geometry/parameter promotion. Recovery ladder beyond bounded
native backtracking remains a reviewed next step, not an automatic retry loop.

## v6 reviewed, v7 bounded pilot — 2026-09-23

Acknowledged tokendc8cdb0a-8dcc-4105-8090-780ec52e25e2. v6 native output hash
verified; diagnostic guard stopped at14 evaluations for sustained excursion.
Response residuals now reach<1e-10, but trust/backtracking controls had silently
used defaults due to option aliases. Corrected and added effective-option checks
before the first gradient. Six unit tests and a constrained native smoke passed,
including the trust cap and fixed angle. Prepared/started v7 from the same
screened near-converged v2 seed with immutable guard snapshot and same resource
bounds. No other point launched, no cloud spend, no minimum certification.
See `docs/cpd_optimization_strategy.md` for evidence and limitations.

## v7 bounded failure; gradient-consistency diagnostic — 2026-09-23

Acknowledged failed token9e488ffc-677b-452f-8f1b-cdec1fe272b5. Verified native
output hash, intended option values, trust cap<=0.1 and response residuals<1e-10.
V7 exhausted its permitted backsteps/dynamic level after25minutes, with9 post-step
records plus the final evaluated checkpoint saved before the failing step.
This bounded failure is not convergence; the lowest-force/lowest-energy point
remains the first evaluation. No further optimization extension launched.

Prepared `cpd-anti-gradient-consistency-v1`, controlled by its corresponding
service-v1. Five fixed-geometry MP2 gradients: repeat first v7 checkpoint and
central±0.002/±0.001bohr displacements along the first optimizer displacement,
projected tangent to the frozen torsion at the reference. Coordinates are
straight-line finite differences, not exactly constrained optimized points.
All prepared points preserve tetrahedral signs, covalent lengths within1% of
reference and target dihedral within0.01degree. Native electronic settings match
v7, including verified SOLVER_CONVERGENCE. Two4-thread6GiB workers, local scratch,
20GiB cap/no swap,2h hard runtime,30min expected. Assessment reports repeat-gradient
and energy differences, analytic versus finite-difference directional derivative,
and two-step directional curvature; no automatic stationarity/minimum acceptance.
This checks local energy-gradient consistency before any alternative optimizer.

## Gradient-consistency assessment recovery — 2026-09-23

Acknowledged failed token7126d759-1f27-4ba3-9e49-0d866d8546c2. All five native
jobs returned0 with finite results; failure was postprocessing broadcasting a
49x3 array against the saved147-vector. Corrected assessment-only entry point
reshapes explicitly and reuses all native results, checking input/output hashes.
Original failed service status is retained with recovery annotation. A synthetic
quadratic regression verifies flattened-reference handling, reused reference,
configurable steps, derivative and curvature (1test passed).

Recovered repeat-gradient max difference2.51094e-7 au, energy difference−5.23e-12Eh.
Analytic directional derivative−8.15816e-7Eh/bohr; finite differences at0.002/0.001
bohr are−3.33955e-6/+1.06247e-5. Gradient-difference directional curvatures
0.00145445/0.00153225Eh/bohr². Small-step energy derivatives are inconsistent;
this is not a demonstrated gradient bug or certified stationarity.

Launched four larger-step probes±0.02/±0.01bohr in gradient-consistency-v2,
reusing v1 reference (no duplicate reference QM). Same screened direction,
electronic method/tolerances and resource bounds. All seeds preserve stereo,
bond distances and near-target angle checks. This tests whether small energy
differences/noise dominate; larger-step anharmonicity remains a possible limitation.
No optimizer extension or minimum certification. Independent watcher armed.

## Larger-step consistency results and alternative optimizer — 2026-09-23

Acknowledged complete token59397f44-7c0f-4b46-9869-b0b2f472f2bc. Four native
jobs returned0; verified input/output hashes and response residuals<=1e-10,
plus the reused reference hash. At0.02/0.01bohr, finite-difference energy slopes
are−8.03391e-7/−3.21916e-7Eh/bohr versus analytic−8.15816e-7. Directional
gradient curvatures0.00146240/0.00146274Eh/bohr² agree to0.023%. Improved but
step-sensitive energy slopes suggest numerical-resolution sensitivity; not proof
of complete gradient consistency, constrained positive Hessian, or minimum.

Installed geomeTRIC1.1.1 with no dependency changes under isolated artifacts
`cpd-geometric-runtime-v1`; package Python sources hash-pinned in pilot plan.
Primary implementation/constraint documentation reviewed. Prepared one
`cpd-anti-geometric-pilot-v1` using the same49-atom endpoint2+15 seed, chemical
graph and QM method/tolerances; reused the verified reference gradient. TRIC,
exact-constraint enforcement enabled, trust0.02Å max0.05Å, GAU_TIGHT,
40-evaluation budget (including reused evaluation), single4-thread6GiB worker,
local scratch,12GiB service cap,4h hard runtime. geomeTRIC displacement/force
metrics differ from OptKing's internal-coordinate metrics; do not equate named
threshold sets numerically. Every requested geometry is screened for graph,
stereo and frozen dihedral; every computed gradient is saved with native hashes.
No full Hessian or harmonic certification is implied by eventual convergence.

Constrained HF/STO-3G peroxide integration smoke converged in9 evaluations with
zero reported torsion error and passing bond screen. First smoke stopped on
provenance check because setup kept writing the reference log after hashing;
preserved it, fixed the test setup and reran in a new root. Production reference
comes from a separate completed immutable job. Alternative pilot and independent
watcher launched, no duplicate OptKing retry or cloud spending.

## Alternative optimizer pilot completion — 2026-09-23

Acknowledged complete token96ce3510-ef32-400f-bc9a-6eaa389f9fc7. geomeTRIC
endpoint2+15 converged in1474seconds,10 evaluations (9new,1reused). Verified
all result/native/geometry hashes, response residuals<=1e-10, optimizer log,
and final coordinates against the last evaluated gradient. Frozen torsion
error6.6e-11degrees; stereo and covalent screen pass. Independent Cartesian
projection onto the frozen-dihedral tangent gives maximum atom force norm
4.10155e-6 and RMS1.28646e-6 au, below the selected thresholds; numerical
constraint Jacobian step-halving difference1.84e-10relative. Trust contracted
near the numerical floor, and tiny energy increases persisted, so do not treat
convergence as a full resolution of energy noise or Hessian/minimum certification.
Evidence: `cpd-anti-geometric-pilot-v1/independent_review.json`.

Launched the remaining endpoint1+15 and endpoint2−15 in
`cpd-anti-geometric-pair-v1`, under one20GiB bounded service. Seeds reuse the
screened v4 preparation (last evaluated v2 coordinates), avoiding the worse
late OptKing iterates. Graph, atom order, stereo, bond and frozen-angle seed
checks pass. Same geomeTRIC/TRIC, MP2/basis/tolerances, exact-constraint handling
and40-evaluation per-point budget. Two separate4-thread6GiB workers, local
scratch,4h hard runtime; retain independent outcomes and completion watcher.
Completed endpoint1−15 and endpoint2+15 are not recomputed. No cloud spending,
no harmonic-minimum claim or parameter/DNA gate promotion.

## GeomeTRIC pair partial completion — 2026-09-23

Acknowledged failed token79b690a4-de4c-4885-af5c-549566fc8c7b. Failure is partial:
endpoint2−15 converged in19evaluations; endpoint1+15 exhausted40evaluations.
Verified59 native gradient/geometry/result chains and response residuals<=1e-10.
Independent frozen-dihedral-tangent projection confirms endpoint2−15 max atom
norm8.01392e-6/RMS3.00744e-6au; final geometry matches evaluated gradient and
passes stereo/bond/frozen-angle checks. This is constrained stationarity, not a
certified Hessian minimum. Three of four constrained points now converged.

Endpoint1+15 remains unconverged (independent projected max6.02769e-5,
RMS2.28322e-5au). Unlike prior runaway/stalled OptKing attempts, recent native
steps show decreasing energy with predicted/actual quality near1.3–1.6, supporting
a bounded continuation. v2 replays the40 saved gradients only at matching
coordinates (max difference<1e-10bohr), rebuilding optimizer history without
claiming a binary restart; any unmatched coordinate requires new native QM.
At most40 new gradients and80 total evaluations, same tolerances/constraints,
one4-thread6GiB worker,12GiB cap and4h hard runtime. Prior attempts immutable.
Replay integration smoke reconstructed the constrained peroxide run with all9
saved evaluations and zero new QM. Independent completion watcher armed.

## Fourth constrained point complete; matched MM campaign — 2026-09-23

Acknowledged complete token8f3455b6-b640-418a-ad64-60d335ebbb3d. Endpoint1+15
converged after56 total evaluations:40reused and16new gradients. Verified all
result/native/coordinate hashes, new response residuals<=1e-10, and final
coordinate agreement with its evaluated gradient. Independent tangent-projected
maximum atom norm4.05579e-6/RMS1.67332e-6au passes; geometry screen and frozen
angle pass. All four±15° constrained QM points have optimizer convergence,
not unconstrained or constrained-Hessian minimum certification.

Prepared/launched `cpd-anti-matched-mm-v1` under its service-v1:24 local MM
relaxations = four unchanged candidate systems × two endpoints × three target
angles (reference and±15°). Same target torsions and screened QM starting
coordinates. geomeTRIC/TRIC handles exact constraints, OpenMM Reference supplies
energies/analytic gradients. Per-system finite-difference component checks validate
unit conversion; each trial screens stereo/bonds/angle. MM convergence uses
stricter projected force thresholds (max5e-7/RMS2e-7au) and200-evaluation budget.
Hash-pinned MM systems; no parameter fitting or promotion. Assessment will compare
relaxed MM relative energies with existing QM differences, keeping failed cases.
Endpoint1−15 QM retains older default electronic tolerances, so this is exploratory
matching rather than fine-precision numerical equivalence. No cloud use.

## Matched MM completion and reference-basin check — 2026-09-23

Acknowledged complete token5f5caeba-4c6c-433d-a2ee-7a93202099d6. All24 matched
MM cases converged. Independent review reconstructs each hashed OpenMM system,
verifies native convergence, final atom order/geometry, recomputes energy and
projects the final gradient against the dihedral constraint; all satisfy selected
max5e-7/RMS2e-7au thresholds within output precision. This remains constrained
stationarity, not positive-Hessian or global-minimum certification.

Relaxation removes most large rigid-probe penalties but leaves energetic errors.
Endpoint2+15 QM relative+0.41968kcal/mol versus MM−1.3320 to−1.5463 across the
four candidates (error−1.7517 to−1.9659). Other errors range+0.4001–0.8832.
QM endpoint1−15 is−0.12730 relative to its original reference. These sign/ranking
changes motivate checking reference-basin dependence before compensating fits.

Launched16 MM reference-torsion multistarts: four candidates × two endpoints ×
two neighboring optimized MM geometries, rigidly back-rotated about the same
N1–C1' axis using the existing17 sugar-atom mapping. Seed checks compare stereo
against actual neighbor coordinates, verify atom order and target angle/bonds.
Then relax at the exact reference torsion with unchanged MM systems. Compare
energies with the original MM reference relaxation; preserve all failures and
avoid claiming global minima. Native results and independent watcher remain
under `cpd-anti-mm-reference-multistart-v1`/service-v1. No charges, force-field
parameters or normal-app geometry changed; no cloud spending.

## MM reference-basin result and QM check — 2026-09-23

Acknowledged complete tokenf9b03eb6-f83a-46df-81c0-fdb3fbcbd13b. All16 MM
reference multistarts converged. Independent OpenMM energy/constraint-projected
force, atom order, stereo, bond and native-convergence checks pass. Energy changes
relative to original MM references are at most9.45e-9kcal/mol in magnitude.
These tested starts do not explain the1.75–1.97kcal/mol endpoint2+15 mismatch;
this is not a proof of a unique or global MM minimum. Parameters remain unchanged.

Prepared/launched two QM reference-torsion checks in
`cpd-anti-qm-reference-multistart-v1`: endpoint1 from its−15° optimized neighbor,
endpoint2 from its+15° optimized neighbor, back-rotated using the established
17-atom sugar group and N1–C1' axis. Seed stereo checked against both actual
neighbor and original reference, plus exact reference torsion and graph distances.
Reference source hashes retained. Same bounded geomeTRIC/TRIC plus tight MP2
settings,40evaluations each, two4-thread6GiB workers,20GiB cap,4h hard runtime.
This probes QM reference-basin dependence, especially the negative endpoint1−15
relative energy, before fitting torsion corrections. No duplicate completed
reference run, harmonic certification, release gate or cloud spending.


## QM reference budget review and bounded continuation — 2026-09-24

Acknowledged failed token5ef0442b-c1ee-4538-bc51-57d53fe11d13. Both v1 checks
exhausted their40-evaluation budgets, without electronic calculation failures.
Independent review verified all80 result/native/coordinate hash chains, geometry
screens and MP2 response residuals<=1e-10. Last energies remain above original
references by0.0024035 and0.0097199kcal/mol for endpoints1 and2. Recent steps
continue descending; these results establish neither convergence nor a lower basin.
Original failures and native outputs remain preserved.

Launched `cpd-anti-qm-reference-multistart-v2` with two4-thread6GiB workers,
20GiB service cap and4h hard runtime. Each reconstructs optimizer history from
40 hash-verified saved gradients and permits at most40 new evaluations (80 total).
Same physics, convergence thresholds, constraints and trust limits. Explicit unique
local scratch paths avoid collisions between identically named child tasks across
versions. Completion watcher armed; progress visualizer updated. No parameter
promotion, minimum certification or cloud spending.


## QM reference checks complete; relaxed midpoint profile — 2026-09-24

Acknowledged complete tokena3b37222-9efb-49d0-bd56-9334771d1c0f.
Both reference-torsion checks converged: endpoint1 used63 evaluations (40 replay,
23 new); endpoint2 used55 (40 replay,15 new). Independent review checked every
result/native/coordinate hash, response residual<=1e-10, final coordinate agreement,
stereo/bond/constraint screen and native convergence. Projected maximum atom
 gradients are4.7272e-6 and9.4308e-6au; RMS1.3005e-6 and2.5012e-6au.
Energy differences from original references are+0.00000723 and−0.00001524kcal/mol.
These starts do not explain the MM energetic mismatch. This is constrained
stationarity; neither global basin uniqueness nor positive-Hessian certification.
Original failed budget-limited attempts remain preserved.

Launched `cpd-anti-relaxed-half-v1` / `cpd-anti-relaxed-half-service-v1`:
four ±7.5° points seeded by rigid rotation of the established17-atom sugar group
from the converged reference checks. Seed bond distances and stereochemistry
checked against actual reference coordinates. Same tight MP2/6-31G(d), TRIC,
constraints/trust limits;60-evaluation cap each, two4-thread6GiB workers,
20GiB service cap,8h runtime limit. Four tasks run two at a time. The added
midpoints will resolve profile shape before torsion fitting; parameters unchanged.
Independent completion watcher armed; progress view updated. No cloud spending.


## Midpoint partial completion and continuation — 2026-09-24

Acknowledged failed token5d4b46d3-e19d-43ce-9ba4-0df0310a15c4. Three of four
QM points converged: endpoint1+7.5 (54 evaluations), endpoint2−7.5 (50),
endpoint2+7.5 (53). Independent native/hash/response/geometry and projected-gradient
review passes, saved in `cpd-anti-relaxed-half-v1/independent_review.json`.
Maximum projected atom gradients are7.4933e-6,3.8061e-6,2.8561e-6au respectively.
Endpoint1−7.5 exhausted60 evaluations. Last projected RMS5.1608e-6/max1.2863e-5au
passes force thresholds but maximum displacement7.397e-5Å fails GAU_TIGHT;
recent force improvement supports bounded continuation, not a convergence claim.
All217 evaluated QM points passed native response and geometry checks.

Launched `cpd-anti-relaxed-half-v2`/service-v2 for only endpoint1−7.5:
replay60 saved gradients, at most40 new, unchanged thresholds and physics,
one4-thread6GiB worker,12GiB service cap,4h hard limit. Prior failures preserved.
Also running12 matched MM relaxations for the three verified midpoint QM points
and four unchanged candidate systems under `cpd-anti-matched-half-mm-v1`.
Reference MM energies reused from the prior verified campaign; no duplicate QM
or parameter promotion. These checks do not certify positive Hessian curvature.

All12 matched midpoint MM relaxations converged and passed independent native,
energy, projected-gradient, atom order and geometry checks. Errors across four
candidates: endpoint1+7.5 [0.32634, 0.36449] kcal/mol. Full per-case errors saved in matched-half-mm-v1/assessment.json.
No fitting performed pending the fourth midpoint. Continuation verified60 replayed
evaluations and new native work, with independent watcher active.


## Complete midpoint profile and outer validation — 2026-09-24

Acknowledged complete tokenc5212850-ab97-402c-b06f-3a3b3cb8fa09. Endpoint1−7.5
converged after66 evaluations:60 replayed plus6 new. Independent native, hash,
response, final geometry and projected-gradient checks pass (maximum1.1061e-5,
RMS4.5559e-6au). All four midpoint points now have constrained optimizer
convergence; no Hessian certification. Original failed run remains preserved.

Completed four additional MM cases in `cpd-anti-matched-half-mm-v2`, with independent
energy/gradient/geometry checks passing. All16 midpoint MM cases are verified.
`cpd-anti-local-profile-diagnostic-v1` combines these with the existing ±15 profile.
For each unchanged candidate/endpoint, an exploratory correction
 a*(cos(delta)-1)+b*sin(delta) trained only on ±15 predicts held-out ±7.5 residuals
within0.089kcal/mol. This is a local energy diagnostic, not accepted force-field
parameters: it creates nonzero reference torque and unconstrained global periodic
ranges32.7–37.2kcal/mol. Coupled equilibrium geometry and wider angular coverage
are not validated. No charge or torsion parameters promoted.

Launched `cpd-anti-relaxed-outer-v1`/service-v1 with four ±30° points, seeded from
completed ±15° QM neighbors by another15° rotation of the established sugar group.
Actual target offsets, unchanged bond lengths and stereo against each actual
neighbor checked. Same tight MP2 and bounded TRIC settings,60 evaluations each,
two4-thread6GiB workers,20GiB service cap,8h runtime limit. This tests extrapolation
before coupled torsion fitting. Watcher armed, progress view updated; no cloud use.

Demo pause/resume: outer-profile service and watcher frozen at user request;
resumed2026-09-24T20:02UTC with original QM processes intact. Runtime and watcher
deadlines extended by10591 seconds of pause; no duplicate QM jobs launched.
Exact timestamps and service state retained in service-v1/demo_pause.json.


## Outer-angle QM complete — 2026-09-25

Acknowledged complete token866daf66-18b1-4b7f-8c4e-c6179d56e743. All four
±30° points converged (endpoint1−/+54/58 evaluations; endpoint2−/+58/52).
Independent review verifies all222 native/result/coordinate hash chains,
response residuals<=1e-10, geometry constraints/stereo/bonds, final coordinate
agreement and native convergence. Projected maximum gradients6.131e-6,
7.008e-6,4.241e-6,4.470e-6au respectively. Constrained stationarity only;
no Hessian or global minimum certification.

Running16 matched MM relaxations against four unchanged systems under
`cpd-anti-matched-outer-mm-v1`. Previously fitted local ±15° residual correction
is frozen for evaluation on ±30° points; no outer data refit. Independent
force-group decomposition will describe relaxed energy contributions without
claiming causal attribution. Original failures and all parameter candidates retained.


All16 outer MM relaxations converged and passed independent energy, projected
force and geometry checks. `cpd-anti-outer-profile-review-v1` evaluates the frozen
local correction without refitting: residual ranges(kcal/mol), endpoint1+30
−1.384 to−1.339; endpoint1−30 −0.477 to−0.451; endpoint2+30 +0.795 to+0.830;
endpoint2−30 +0.031 to+0.055. Thus the midpoint diagnostic does not establish
outer-angle accuracy. Force-group differences sum to independently recalculated
relative MM energy; decomposition retained as descriptive evidence only.

Launched16 outer MM multistarts in `cpd-anti-outer-mm-multistart-v1`/service-v1,
using each candidate's optimized ±15 MM neighbor rotated to the exact ±30 target.
Seeds screened against both actual neighbor and existing QM stereo. Compare with
original outer MM relaxations before broader torsion fitting; all parameters fixed.
Single-thread local MM,4GiB cap,1h limit, independent watcher. No cloud use.


## Outer MM basin agreement and broader torsion screening — 2026-09-25

Acknowledged complete token56673b9b-d749-4302-bd73-3edd156918f1. All16 outer
MM multistarts converged and independently passed energy/gradient/geometry checks.
Largest absolute energy difference from original outer relaxations2.6293e-8kcal/mol.
These tested starts do not explain profile mismatch; no global minimum claim.

`cpd-anti-broad-torsion-diagnostic-v1` compares n=1,2 Fourier residual models,
free torque versus analytically zero reference torque, trained on ±15/±30 with
±7.5 held out. Predeclared ridge sweep0.0001/0.01/0.1 and coefficient bounds±10
(kcal/mol; transformed sin1 can reach20 in zero-torque family). No fit accepted by
held-out tuning. Endpoint2 zero-torque fits have substantially larger residuals.

Ran `cpd-anti-torsion-geometry-v1`/service-v1: all four candidates, two endpoints,
two torque families at fixed ridge0.01. Isolated OpenMM CustomTorsionForce overlays;
angle convention checked against actual geometry and force finite differences.
Unconstrained L-BFGS geometry screening from original MM minima, no CHARMM export.
All16 attained maximum force<0.001kcal/mol/Å and stereo/bond checks pass. Endpoint2
moves about19–20° for free-torque fits and47–50° for zero-reference-torque fits.
Endpoint1 moves about5–8°. The zero-torque condition refers to the QM reference
angle, not necessarily the original MM minimum. These shifts require further
coupled validation; energy-fit improvement is not geometry acceptance. No Hessian
certification, charge acceptance, full DNA test or parameter promotion. Watcher
and visualizer updated; originals and all trial failures retained. No cloud use.


## Independent torsion geometry audit and remote wells — 2026-09-25

Acknowledged complete tokendd065509-d313-4255-a7a9-877c2102c87b. Independent
reconstruction of all16 serialized trial systems confirms max force<0.001
kcal/mol/Å. Internal MM Hessians at1e-4 and5e-5Å displacements are positive
for all16 after removal of six rigid modes. This supports local MM minima only,
not QM certification, global minima, transferability or release acceptance.
Training geometry comparison: endpoint1 maximum angle errors2.72–2.93°;
endpoint2 free-torque3.61–3.62° and zero-torque5.97–6.08°. Endpoint2 maximum
bond errors0.0301–0.0386Å. Thus the endpoint2 trials degrade prior geometry gates.
Evidence saved in torsion-geometry-v1/independent_review.json; failures preserved.

Crucial scope correction: original baseline endpoint2 MM torsion177.9226°
versus QM reference84.4659° (difference93.4567°). The earlier training bond/angle
success did not imply torsion or full conformational agreement. Endpoint1 original
MM/reference difference−3.5476°. Local residual fits around the QM reference
cannot establish behavior at the distant endpoint2 MM well. Zero-reference-torque
is defined at the QM angle, not the original MM minimum.

Launched `cpd-anti-remote-wells-v1`/service-v1: two constrained endpoint2 QM
relaxations seeded from baseline MM minimum and baseline zero-torque trial minimum,
at each actual glycosidic angle (about178° and131° respectively). Both seed graphs,
bonds and stereo screened against QM reference. Tight MP2/6-31G(d),60 evaluations
per point, two4-thread6GiB workers,20GiB service cap,6h runtime limit. These compare
remote conformations before further fitting; no unconstrained QM minimum claim.
No parameter or normal-app geometry promotion. Watcher and progress view updated;
no cloud spending.


## Remote-well budget review and continuation — 2026-09-25

Acknowledged failed tokend1b0ddfa-708b-4734-a722-fd268b7dade9. Both remote
points exhausted60 gradient evaluations; no native electronic failure. Independent
review of all120 result/native/coordinate chains and geometry screens passed,
including tight response residuals. Last projected max/RMS atom gradients:
baseline-well3.938e-6/1.424e-6au; zero-torque-well9.237e-6/3.561e-6au.
Forces pass GAU_TIGHT, but displacement convergence has not been attained.
Baseline-well recent energy changes are noise-scale with alternating trust updates;
zero-torque-well has recently improving forces. No optimizer convergence claimed.

Current energies relative to the original endpoint2 reference are−7.08002 and
−0.76032kcal/mol respectively. These establish lower-energy evaluated
conformations, not unconstrained or constrained-Hessian certified minima. In
particular, the original QM reference must not be assumed to be the global well
when fitting away the remote MM preference. Further fitting remains deferred.

Launched `cpd-anti-remote-wells-v2`/service-v2:60 hash-verified cached gradients
replayed per point, at most20 new evaluations each (80 total), same thresholds,
constraints and electronic settings. Two4-thread6GiB workers,20GiB cap,3h hard
runtime. Old failures immutable; watcher armed and visualizer updated. No cloud
spending or parameter promotion.


## Remote constrained convergence; restraint release — 2026-09-25

Acknowledged complete token4adeddb3-9153-43ea-8f0e-7c5a31b93015. Both remote
points converged: baseline-well61 evaluations (60 replay+1 new), zero-torque-well62
(60 replay+2 new). Independent native/hash/geometry/response review passes;
projected maximum atom gradients5.970e-6 and6.418e-6au. Relative energies remain
about−7.08002 and−0.76032kcal/mol versus original endpoint2 reference. These are
constrained stationary conformations, not certified unconstrained minima.

Added explicit opt-in `freeze_torsion=false` to isolated geomeTRIC worker; default
constrained behavior unchanged. Bond/stereo screens retained; angle drift permitted
only for the unconstrained mode. Review uses full gradients in this mode. Native
peroxide HF smoke first exposed geomeTRIC1.1.1 conmethod1 incompatibility without
constraints (zero QM evaluations, failure preserved); corrected free-run plans omit
constraint-specific conmethod/enforce options. Smoke v2 converged11 evaluations,
full maximum atom gradient1.528e-7au and35° torsion drift, confirming actual release.

Launched `cpd-anti-remote-unconstrained-v1`/service-v1 from the two verified remote
geometries. Each reuses its last hash-verified gradient, then permits60 new
calculations. Same tight MP2/6-31G(d), two4-thread6GiB workers,20GiB service cap,
6h hard runtime. Hessian work waits for full-gradient unconstrained convergence.
No parameter promotion, cloud spending or global-minimum claim. Watcher armed,
progress view updated; original failures preserved.


## Remote unconstrained convergence and Hessian — 2026-09-25

Acknowledged complete token80bb0bc3-265a-4800-9734-3729450bdf45. Both remote
starts converged unconstrained:30 and39 evaluations, each including one reused
gradient. Independent native/hash/response/geometry/final-coordinate checks pass;
full (not constraint-projected) maximum atom gradients4.195e-6 and4.561e-6au,
RMS9.364e-7 and1.430e-6au. Existing review field names retain 'projected' but
freeze_torsion=false explicitly selects the full gradient in the implementation.
Aligned all-atom RMS difference0.0003544Å, energy difference3.95e-6kcal/mol,
final glycosidic angles−168.4701/−168.4775°. Both are about7.58404kcal/mol below
the original endpoint2 reference. This demonstrates lower unconstrained stationary
conformations; a global minimum is not established.

Prepared one Hessian at baseline-well-derived stationary geometry to avoid duplicate
calculation for indistinguishable conformations. `cpd-anti-remote-frequency-v1`
has289 independent gradient tasks (reference plus288 displacements). Same existing
frequency protocol1.7.0 and MP2/6-31G(d), with its default electronic convergence
settings (not the extra-tight optimizer settings). Tight soft-mode follow-up is
required for ambiguous curvature, as in earlier certification campaigns. No
Hessian/minimum pass asserted before native assembly and audit.

Launched `cpd-anti-remote-hessian-service-v1`: established four4-thread3GiB worker
layout on CPUs0–15,18GiB service cap,16h runtime limit, resumable per-task outputs.
Independent watcher active, progress view updated. Charges/torsions remain
unaccepted pending reference-state reassessment; no cloud spending.


## Remote Hessian harmonic audit and soft-mode follow-up — 2026-09-25

Acknowledged complete tokenbbe934f0-ad3b-483e-a644-01dc1a04964e. Hessian batch
finished289 tasks in5.84h. Independent review rechecked every task's input/result/
run-record hash, plan identity, native success and finite147-component gradient;
assembled Hessian, native output and run manifest hashes verified. Frequency audit
passes candidate harmonic minimum:141 projected positive modes, zero imaginary,
lowest14.9846cm−1. This supports a local harmonic QM minimum at MP2/6-31G(d),
not a global minimum, accepted CHARMM parameters, or DNA validation.

Launched `cpd-anti-remote-soft-mode-v1`/service-v1 using established soft-mode
protocol: tight reference plus ±0.04 and±0.02bohr along the lowest projected
mass-weighted mode transformed to a normalized Cartesian direction. SCF E/D1e-12,
response solver1e-10. Tests force at reference, positive gradient-difference
curvature and<=10% step-halving disagreement. Three4-thread3GiB workers,
14GiB service cap,2h hard limit. Exact lowest-mode stiffness remains provisional
until this independent directional check, which does not replace a full Hessian.
Watcher active; visualizer updated. No cloud spending or parameter promotion.


## Remote soft-mode consistency failure — 2026-09-25

Acknowledged failed tokenbaccc3f0-2f39-4578-b1ad-0ff629f4f97c. All five native
calculations completed and independently verified input/plan/native/result hashes,
finite gradients and actual final response residuals<=1e-10. Reference maximum
component force2.558e-6au passes. Directional curvatures are positive:
1.1323492e-4 at0.04bohr and9.9591082e-5 at0.02bohr (Eh/bohr²). Step-halving
relative difference0.120491 fails the unchanged0.10 criterion. Original Hessian
curvature4.6632687e-5 is substantially smaller. Harmonic positive-mode evidence
remains, but the numerical soft-mode validation failed; precise stiffness and
robust minimum qualification remain unresolved. No negative curvature observed.

Launched `cpd-anti-remote-soft-resolution-v1`/service-v1: five new tight gradients,
±0.01/±0.08bohr along the same saved direction plus repeat reference. Prior five
results are hash-referenced, not rerun or overwritten. Four-scale trend and repeat
noise diagnostic only; no automatic acceptance by selecting a favorable pair.
Same tight settings, three4-thread3GiB workers,14GiB cap,2h runtime. Original
failures preserved. Watcher and visualizer updated; no cloud or parameter promotion.


## Four-scale soft-mode evidence and conformer electrostatics — 2026-09-25

Acknowledged complete token1cc40ead-26e1-48aa-94d8-49fc1faaa7d2. Independently
verified all10 old/new native result/input/plan hashes and response residuals;
recomputed the four directional curvatures. At0.01/0.02/0.04/0.08bohr:
9.9851203e-5,9.9591082e-5,1.1323492e-4,1.1418131e-4Eh/bohr², all positive.
Smallest pair agrees0.2605%; largest pair0.8288%; middle pair still fails12.0491%.
Reference repeat projected-gradient difference9.284e-9au (maximum Cartesian
component difference1.569e-7au), energy difference−2.956e-12Eh. Reference repeat
noise does not establish error bounds at displaced geometries. Two different
curvature plateaus and default-Hessian stiffness discrepancy remain unexplained.
The original failed10% gate is not relabeled passed. Combined with the positive
full harmonic spectrum and unconstrained stationarity, this strengthens local
minimum evidence; precise soft stiffness and full tight-Hessian qualification
remain provisional. No global minimum or force-field acceptance claim.

Launched `cpd-anti-remote-esp-v1`/service-v1 to add HF/6-31G(d) ESP and dipole
targets at the lower-energy endpoint2 conformation using existing ESP generator
and audit. Original reference-conformer targets retained; not replacing history or
accepting charges. One4-thread3GiB native job,6GiB service cap,2h runtime limit.
Source harmonic audit and unresolved soft-mode review retained in plan. Watcher
and visualizer updated; no cloud spending or parameter promotion.


## Remote electrostatics and three-conformer charge trial — 2026-09-25

Acknowledged complete tokena68013cf-cd17-41a6-bf99-107de46bb204. Verified native
successful run, job/source/output hashes,1274 finite ESP values with matching grid,
and audited dipole vector. Initial audit re-invocation correctly refused to overwrite
existing esp_audit.json; existing evidence was preserved and independently checked.
Frozen baseline and charge1/10/100 predictions have remote ESP relative errors
0.6248/0.4595/0.5418/0.6090 and dipole vector errors1.739/1.204/1.227/1.614D.
This prospective comparison is saved before refitting in remote-esp-v1 review.

Ran `cpd-anti-multiconformer-charge-v1`: adds remote ESP as a third equally weighted
conformer block to existing two ESP and original water-target blocks. Same28 shared
base variables,±0.15e bounds, neutral summed shift, equal methyl-H shifts,
regularization1/10/100; caps/sugar/LJ/bonded terms fixed. All optimizers converged
and charge constraints pass. New target is now training, not held-out validation.
Lowest-regularization remote relative ESP error0.4216 and dipole error0.8775D;
remaining two candidates0.5237/1.0276D and0.6041/1.5555D. Original water maximum
energy errors for lowest regularization are1.14 and1.53kcal/mol by endpoint.
Substantial residuals remain; no candidate selected, exported or promoted.

Launched `cpd-anti-remote-water-calibration-v1`/service-v1: three representative
screened contacts at the new conformer, each evaluated with DF and DIRECT HF using
identical coordinates. Established>=1.1 non-target covalent-radius-ratio screen;
production curves await calibration. Four4-thread3GiB workers,18GiB cap,2h runtime.
Original conformer datasets/candidates retained. Soft-mode numerical limitations
remain explicit; watcher and visualizer updated, no cloud spending.


## Remote water calibration passed; distance curves — 2026-09-25

Acknowledged complete token83ac0f2a-c454-4812-8043-d608a689e65c. Independent
review verified all six DF/DIRECT job/source/water/native hashes, successful
execution and recomputed calibration audit from native data. Three matched sites
pass: errors0.003688,0.004324,0.001783kcal/mol, maximum below0.02kcal/mol limit.
This validates the sampled DF approximation, not force-field charges.

Screened six donor/acceptor site orientations for the lower-energy endpoint2
conformer, distances1.5–2.7Å in0.2Å increments. All six pass non-target separation
>=1.1 covalent-radius sums; least crowded of registered0/120/240° azimuths used.
Prepared42 distance points, with three exact geometry/protocol matches reused
from calibration. Launched39 new native DF HF interaction calculations under
`cpd-anti-remote-water-curves-v1`/service-v1. Four4-thread3GiB workers,18GiB cap,
3h hard limit. Native curve audits follow, then evaluate frozen original and
three-conformer charge candidates before any new fit. Fixed orientation is not
orientation optimization. Original data and soft-mode limitations retained;
watcher and visualizer updated, no parameter promotion or cloud spending.


## Remote water curves: partial scientific pass — 2026-09-25

Acknowledged complete tokenc1c33644-61d0-4e17-8a47-ea974d60ce77. Independently
verified42 job/native/source/water/output hash chains and successful execution;
recomputed six curve audits without overwriting originals. Five bracket minima.
1-O4 fails: all sampled interactions repulsive through2.7Å (+5.543kcal/mol at
outer edge), minimum at grid boundary. Service completion was process completion,
not all_curves_passed. Future remote curve runner now returns failure when audits
fail, while retaining assessments and individual successful results.

Frozen baseline/original charge1 and new three-conformer charge1 give worst
usable-site minimum energy errors3.663/1.461/1.417kcal/mol respectively, with
existing1.16 energy scaling and−0.2Å target-distance offset. All seven frozen
candidate predictions retained in remote-water-transfer-v1/frozen_candidates.json.
Unbracketed1-O4 excluded explicitly; no refit or parameter acceptance performed.

Extension v1 setup requested2.9–4.5Å but generator rejected distances above4.0Å.
Six valid2.9–3.9Å job inputs existed; no native outputs or complete plan existed.
An inadvertently invoked v1 service failed on missing plan, with no native work.
Failure retained in extension-v1/preparation_failure.json. Corrected v2 reuses
those six valid inputs, seven original native outputs and unchanged orientation,
within supported range. Launched extension-service-v2: four4-thread3GiB workers,
18GiB cap,2h limit. Re-audit13-point curve after completion; if still unbracketed,
do not infer a minimum. Watcher/visualizer updated; no cloud spending.

Acknowledged delayed extension-v1 failure wake2355b2bc-9b11-4109-b414-bdeeb45d78b7.
Native launch never occurred in v1 (missing plan). Corrected v2 remains active,
with six new jobs and seven reused points; native outputs progressing and watcher
active. No additional jobs launched in response to the stale notification.


## Extended contact specificity and updated charge trials — 2026-09-25

Acknowledged complete tokenbaca7b30-9e69-4d7b-ba85-40fb349cd06f. All13 points
(seven reused, six new) independently verified by native/hash/source checks;
recomputed series audit now brackets the1-O4 minimum at sampled3.7Å, scaled
interaction−3.4958kcal/mol. However nearest water H1/model contact is sugar2:O5′
at2.5188Å, whereas nominal1:O4 is3.7Å away. Thus this is a mixed-contact minimum,
not a clean nominal O4 target. Preserve it as diagnostic and exclude it from
direct site fitting; contact_review.json records distances. Original failure retained.

Ran `cpd-anti-multiconformer-water-charge-v1`: original three-conformer ESP and
water targets plus five usable remote water curves;1-O4 excluded explicitly.
Same28 charge variables, neutrality/methyl constraints,±0.15e bounds and
regularization1/10/100. Lowest-regularization remote ESP relative error0.4293,
dipole error0.8263D, worst remote water minimum energy error1.2145kcal/mol.
Original endpoint water maxima1.2769/1.5529kcal/mol. These are now training
metrics; preceding frozen transfer measurements preserved. No candidate accepted.

Ran12 isolated charge-only geometry screens in `cpd-anti-charge-conformer-geometry-v1`
/service-v1: three strengths × two endpoints × two starting conformations.
Charges and corresponding nonzero pair exceptions updated consistently; fixed
LJ/bonded terms. Endpoint1 uses original QM/MM starts; endpoint2 original/remote
QM starts. All report stationarity and stereo/bond screen pass. Endpoint2 ends
at different torsions by start (~171° versus179–180°); independent geometry,
force and Hessian validation remains required. No optimizer success is treated
as minimum certification. Serialized trial systems stay isolated; watcher and
visualizer updated, no cloud spending or parameter promotion.


## Independent charge geometry audit and bonded refinement — 2026-09-25

Acknowledged complete tokencb2589ca-dd43-43cd-9c08-238ed5b71f39. Reconstructed
all12 serialized systems; verified final hashes, energy/forces, unchanged bonded
and LJ terms, and consistent charge-product exception rescaling. Internal MM
Hessians at1e-4/5e-5Å both positive for all12, with maximum force<0.001kcal/mol/Å.
Local MM minima supported, not global minima or force-field acceptance. Endpoint1
two starts converge to same minima; endpoint2 remote-derived minima lie1.35–1.57
kcal/mol below original-start minima. Maximum target angle errors endpoint1
2.55–2.60°, endpoint2 original4.36–4.37°, remote5.05–5.24°. Charges alone do not
retain desired geometry quality. Native failure history remains preserved.

Prepared/launched `cpd-anti-remote-coupled-v1`/service-v1. Three multiconformer
charge strengths frozen while jointly refining original core/endpoint1 and the
lower-energy endpoint2 QM geometry. Endpoint2 starts from that actual remote
geometry; original reference retained as separate validation data, not erased.
Existing ordered CPD type aliases, absolute±6° angle/±0.01Å bond-equilibrium
bounds relative to original typed parameters, fixed torsions/LJ,100 optimizer
function evaluations per candidate. Target provenance and unresolved soft-mode
stiffness caveat recorded. Original geometric-fit engine reused through hash-pinned
reference adapter; all reported endpoint2 boundary target angles now correspond
to new geometry. Three single-BLAS-thread fits,10GiB cap,4h limit. Subsequent
independent curvature/export/multiconformer checks required; no release or cloud.

Coupled service-v1 failed before starting any fit because the QM interpreter lacks
ParmEd. Preserved log; relaunched the same prepared inputs via service-v2 with
the repository virtual environment used successfully for preparation and original
MM fitting. No simulation duplication or input regeneration.

Acknowledged delayed service-v1 failure wake7a684d2f-a450-4327-8402-f01723176f09.
Confirmed missing ParmEd import before fit execution. Corrected service-v2 remains
active; strengths10/100 have final training reports and strength1 is still working.
These reports are not independent curvature/export validation. No duplicate fits
launched in response to this stale notification.


## Lower-reference fits verified; retained-profile transfer — 2026-09-25

Acknowledged complete tokenfa448364-5a85-44e4-b1f9-1aa24501ebe1. All three
bounded geometry fits completed. Verified source hashes, optimizer success,
±6°/±0.01Å parameter bounds and reported training geometry/stereo gates.
Maximum endpoint angle errors2.7263/2.7153/2.7022° for strengths1/10/100;
maximum endpoint bond errors<=0.0261Å. Independent reconstruction of all nine
core/fragment systems confirms stationarity, positive projected MM Hessians at
two step sizes, and numerical equivalence with CHARMM PSF/parameter export.
Reports remote-coupled-verify-{1,10,100}-v1 retained; no full force-field acceptance.

Launched `cpd-anti-remote-profile-mm-v1`/service-v1:45 constrained relaxations,
three fixed candidates ×15 existing QM points. Points include both original
references,±7.5/±15/±30 for both endpoints, and new lower-energy endpoint2 minimum.
Old-reference profiles are retained rather than hidden by target replacement.
Same strict MM stationarity/geometry screens and200-evaluation budget per case.
Single-thread native MM,4GiB cap,2h hard runtime. This is retrospective transfer,
not unseen experimental validation; endpoint1−15 retains older electronic settings.
Independent audit follows completion. Watcher/progress view updated; no parameter
promotion or cloud spending.


## Refined profiles: stationarity passes, energy transfer fails — 2026-09-25

Acknowledged complete token7e7f991a-17a9-4900-9e48-03a8d2ac7b24. All45
constrained MM cases independently pass native convergence, system/source hashes,
atom order/geometry, re-evaluated energies and projected force thresholds. This is
constrained stationarity, not Hessian certification of every profile point.

Relative to the respective original-reference constrained relaxations, remote
endpoint2 MM energies are−17.475/−16.987/−16.637kcal/mol for strengths1/10/100,
versus QM−7.584: errors−9.891/−9.403/−9.053kcal/mol. Endpoint2−30 errors are
−9.351/−6.461/−6.625kcal/mol, much larger than prior local-profile results.
Thus training geometry/export success does not establish energetic transfer.
A conformational-basin switch is a hypothesis requiring explicit multistarts;
these relative energies must not silently be treated as global minimum differences.
No candidate accepted and no compensating fit launched from these data.

Launched `cpd-anti-refined-basin-check-v1`/service-v1:18 cases = three refined
candidates × two target angles(original endpoint2 reference and−30) × three MM
neighbor starts. Neighbors are prior constrained minima at−30/+30/remote for
reference target, and−15/reference/remote for−30 target. Existing17-atom sugar
rotation, target/bond/stereo checks against actual neighbors and QM signs; no
parameter edits. Compare to original45-case energies. Single-thread local MM,
4GiB cap,2h limit. Failure evidence retained, watcher/progress view updated; no cloud.


## Refined MM basin dependence confirmed — 2026-09-25

All18 follow-up cases completed and independently passed native convergence,
source/system hashes, atom order/stereo/geometry, energy reconstruction and
projected stationarity. No Hessian certification of these constrained points.
Remote-seeded reference-angle energies are lower than original starts by
4.84849/4.81028/4.90808 kcal/mol for strengths1/10/100. At -30, remote-seeded
energies match strength1 but lower strengths10/100 by2.96882/2.90732 kcal/mol.
Other starts retain higher stationary basins. Thus basin dependence is confirmed;
initial -9.05 to -9.89 relative-energy errors include reference-basin bias and
must not be interpreted as comparisons between global minima. These new references
alone do not eliminate the remote relative-energy discrepancy. Preserve all starts.

Launched `cpd-anti-refined-profile-basin-v1`/service-v1:36 unchanged-parameter
MM cases, three strengths × six remaining endpoint2 targets × two seeds from
lower reference/-30 basins. Exact target rotation, stereo/bond checks against
both neighbor and QM reference, hash-pinned sources. This will characterize the
lowest observed MM profile before deciding whether further QM basin matching or
parameter fitting is justified. Single-thread native MM,4GiB cap,2h hard limit,
20min watcher estimate; no duplicate jobs, cloud spending, or candidate promotion.

Acknowledged delayed basin-check completion wake a9a85420-9305-4639-b214-d7c64192b8b9. Rechecked native outputs and independent stationarity audit:18/18 pass, no minimum certification. Follow-up profile multistarts already active (5/36 completed at review); separate watcher active. No duplicate jobs launched.


## Lowest observed MM profiles; QM basin matching — 2026-09-25

Acknowledged completion token c886fe91-0bf3-4256-b94e-6bc60e65a2ef. All36
remaining-angle MM multistarts pass independent native/hash/geometry/energy/
projected-stationarity audit. These constrained stationary points are not
Hessian-certified. Retained every original and alternate-start result.
`cpd-anti-refined-profile-basin-v1/profile_envelope.json` compares lowest observed
MM energies over original45 plus18+36 multistarts with existing QM points.
After using lower reference basins, remote endpoint2 errors are -5.0424/-4.5926/
-4.1446 kcal/mol (strengths1/10/100), versus initial -9.89/-9.40/-9.05.
At -30 errors remain -4.503/-4.619/-4.624. At +15 errors are +2.356/+2.374/
+2.394. No accepted energy transfer; lowest observed is not a global minimum.

Launched `cpd-anti-refined-basin-qm-v1`/service-v1: constrained MP2/6-31G(d)
DF frozen-core tight electronic settings and geomeTRIC TRIC/GAU_TIGHT, two
starts at original reference and -30 angles using strength1 remote-seeded lower
MM basins. Strength1 chosen for largest remote energy discrepancy, not assumed
representative of all candidate basins. Same atom map/stereo/bond/target screens,
60 evaluations per point,4 threads and6GiB per worker; two concurrent workers,
20GiB service cap,8h hard limit,4h watcher review estimate. No parameter changes.
These decisive QM checks test whether the old QM profile missed corresponding
lower conformers before fitting further. Separate watcher armed; no cloud.


## QM basin checks: one converged, one budget-limited — 2026-09-25

Acknowledged failed wake78ce4402-586c-4d4f-95c6-b4e2b58dfc4f. Service-v1
finished after3.24h; failure is reference-point60-evaluation guard, not SCF failure.
Independent audit verifies all114 native MP2 gradient/source/geometry records.
-30 converged at54 evaluations; projected max/RMS7.485e-6/2.167e-6au,
energy-1364.5176844454218Eh,8.87179kcal/mol below previous same-angle QM.
Thus previous QM scan missed a lower constrained stationary conformer. No
Hessian certification or proof of global minimum. Original evidence retained.
Reference latest energy-1364.5119583781861Eh is3.50790kcal/mol below old
reference but NOT converged: independent projected max/RMS3.775e-5/1.128e-5au.
Recent native gradient/displacement decrease supports a bounded continuation.

Launched service-v2/root`cpd-anti-refined-basin-qm-v2` for reference only:
60 hash-verified cached gradients replayed to reconstruct optimizer history,
80 total/20 new evaluations maximum, unchanged convergence/settings,4 threads,
6GiB worker/10GiB service cap,3h hard limit,70min watcher review estimate.
The successful -30 calculation is referenced and not duplicated. Further
relative-energy fitting waits for reference convergence; no cloud/promotion.


## Lower-basin QM reference converged — 2026-09-25

Acknowledged complete wakee185c845-c91c-46d2-8c40-cc853e5b34de. Independent
native/hash/stereo/geometry/gradient audit passes:67 evaluations,60 reused/7 new,
energy-1364.5119583961437Eh, projected max/RMS1.47248e-5/4.35294e-6au.
Native GAU_TIGHT convergence and independent thresholds pass; no Hessian or
unconstrained/global-minimum certification. Reference is3.507914kcal/mol below
old same-angle QM. Combined with converged -30, QM relative energy is-3.593150
kcal/mol; lowest observed MM errors now+0.86090/+0.74441/+0.73977 for strengths
1/10/100. Remote QM is-4.076126 relative to updated reference, leaving MM errors
-8.55019/-8.10079/-7.65294. Earlier comparisons used an obsolete QM reference;
all historical results retained. Exact full-conformer correspondence and global
minima remain unproven. No candidate accepted or parameter refit yet.

Launched `cpd-anti-lower-basin-profile-v1`/service-v1: two constrained QM points
at -15/+15 from the newly converged QM reference, screened17-atom sugar rotations
against seed and original QM stereo/bond/target geometry. Same tight MP2 settings,
TRIC/GAU_TIGHT,60-evaluation budgets, two4-thread/6GiB workers,20GiB service cap,
8h hard limit and4h watcher review estimate. This extends the newly discovered
lower-basin profile before further torsion fitting. No cloud or product promotion.


## Fixed validation contract established — 2026-09-25

User requested literature research and codification to replace repeated ad hoc fits.
See docs/cpd_validation_protocol.md for primary sources, exact limits, membership,
exposure rules and review workflow. Machine manifest contains94 records:63 required
for reference acquisition,28 prospective holdouts,3 export checks. These are records,
not94 new jobs. Current scans continue; no new full-grid or DNA jobs launched.

Native optimization is not basin closure. Use multiseed bidirectional propagation,
fixed matched reference identity and full conformer descriptors. Old inspected data
are exposed regression/development, never relabeled blind. New fit entry guards
block without a hash-verified acquisition lock; candidate registration blocks further
fitting to protect holdouts. Missing/changed evidence and unmatched basins fail closed.
Current contract intake is0/63 adapted reviews, not a claim that prior QM evidence
is worthless or failed. Required closure/curvature gaps remain real. Final dataset
is not certified merely by publishing its membership. Failure archives preserved.

Verification:26 scoped validation/watcher tests passed, including missing evidence,
NaN/Infinity, altered hashes, reflection/basin mismatch, inconsistent energy zeros,
RMSE failure, holdout coverage, and preventing fit-service creation without a lock.
Current native acquisition and watcher remain active. No broad backend or frontend
behavior change; exported progress data refreshed. Native-audit adapters and full
wavefront scheduling remain acquisition work, explicitly not claimed complete.


## Lower-basin profile: +15 stalls; diagnose before extending — 2026-09-25

Acknowledged failed wake4dcbd02c-9d80-418d-b2e7-31561fe54fff. Independent
native/hash/geometry/response audit covers49+60 evaluations. -15 converged with
projected max/RMS1.27418e-5/3.36044e-6au, energy-1364.5159999680018Eh.
No Hessian or basin closure certification. +15 stopped on60-evaluation guard:
projected max/RMS2.28489e-4/8.08984e-5au, ~15x maximum-force tolerance.
Final native gradient plateau near2.4e-4 despite small energy decreases; do not
justify another budget extension solely by energy descent. All outputs retained.

Launched `cpd-anti-lower-profile-gradient-v1`/service-v1, five single-point
MP2 energy/gradient checks at stalled geometry: repeat reference and +/-0.005,
+/-0.0025bohr along normalized downhill projected Cartesian gradient. This is
a straight-line directional derivative test, not constrained curvature/minimum
certification. Hash/geometry/stereo screens and tight native response retained.
Two4-thread/6GiB workers,20GiB service cap,2h hard limit,20min watcher estimate.
Review both symmetric energy slopes against analytic slope, repeat-gradient noise
and step dependence before choosing optimizer continuation/repair. Local diagnostic
criteria recorded in plan; no acceptance limits changed. Fitting remains blocked
under fixed validation v1; no blind data acquired or cloud spending.


## Stalled +15 diagnostic: slopes agree, repeatability narrowly fails — 2026-09-25

Acknowledged complete wake7f58eb71-5488-43e9-aa91-a44e7aa8e672. Independently
verified five native results, hashes, screened coordinates, finite gradients and
response residuals<=1e-10. Analytic tangent slope-5.663524e-4Eh/bohr agrees with
symmetric energy slopes to0.1479%/0.7517%. Reference gradient component difference
1.083921e-6au exceeds preregistered1e-6 limit: overall diagnostic criteria FAIL,
not silently relaxed. Reference energy difference4.775e-12Eh. This supports a
real downhill gradient at the stalled point; it does not certify stationarity,
curvature, basin closure or accurate soft-mode stiffness.

Launched `cpd-anti-lower-profile-restart-v1`/service-v1: one bounded method test
from same last geometry with fresh initial TRIC Hessian (not replaying stale Hessian
updates), one cached diagnostic reference gradient and at most20 new evaluations.
Original60-evaluation failure plus repeatability failure are linked in plan. This
uses the one continuation allowed by validation v1; no further automatic extensions.
Tight QM and GAU_TIGHT criteria unchanged.4 threads/6GiB worker,10GiB cap,3h hard
limit,70min watcher estimate. Fitting remains blocked; no holdout or cloud work.


## Fresh-Hessian continuation exhausted; method review required — 2026-09-25

Acknowledged failed wake3d922444-a0da-44b2-92a3-27223ccf690b. Native geomeTRIC
maxiter20 failure;21 evaluations=1cached+20new. Independent audit verifies all
native/hash/stereo/response records but NOT convergence. Final projected max/RMS
2.74580e-4/9.14524e-5au versus starting max2.28489e-4. Trust shrank to~4e-6Å;
steps often~1e-7Å with noisy energy changes and persistent gradient. Final energy
is higher than restart seed. No further automatic continuation: the one20-new
allowance is exhausted. Original60 plus20 optimizer evaluations remain unresolved.

Read-only `coordinate_review.py/json` reconstructs initial/final TRIC Jacobians:
rank147/147, condition~91.6, exact expected bond-distance primitives, gradient
reconstruction residual<2.4e-16au initially. This does not implicate graph mismatch
or a missing Cartesian subspace at those two geometries; it does not prove the
internal step/constraint enforcement is correct. No new QM was launched. Store
`method_review.json`: next work is cached-iteration constraint/trust-step and
energy-noise review before selecting a changed method. Prior repeatability failure
remains failed. +15 is unresolved coverage, not an exclusion or certified minimum.
Fixed dataset fitting gate remains closed; no holdout, cloud or candidate promotion.

User-requested closeout complete: pause receipt and launch guard active; legacy
CPD automatic triggers disabled with prior states recorded. Deleted4.81GB of
regenerable integral scratch, preserved all31,188 existing evidence files and
retained three wavefunction snapshots with hashes. See closeout/cleanup manifest.
37 scoped Python tests and3 browser checks pass; browser artifact cleanup verified.
