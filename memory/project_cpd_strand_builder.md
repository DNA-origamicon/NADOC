---

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



CPD active state, 2026-10-04T21:12Z: larger-box startup wake810aeb49 acknowledged;
independent audit passed672 saved/final geometries plus2 minimized endpoints,
static force/energy and restart tests. Root `cpd-anti-gpu-largebox-v3`, audit
`startup_native_audit.json`; six100ps startup plus10psrestart each. Measured
native60ns estimate10.515h. Launched `cpd-anti-gpu-largebox-validation-service-v3`
(unit `cpd-anti-gpu-largebox-validation-v3`), six10ns GPU-resident runs, 60 paired
round-robin1ns segments, +p4/GPU0,cycle10,no precedingrun0. Watcher armed token
fd8a7c9f-b89b-4063-b393-2b50964b0fb0; confirmed first native resident/cycle10 log.
Expected14.14h including analysis allowance. Do not poll or duplicate jobs.
Original context deadline1791237908.8733842 unchanged (24.88h remained at launch),
original72h cap preserved. Worker `gpu_largebox_validation_v3.py`, frozen copy and
input hashes in root/validation_plan.json. Every10ps plusbinaryfinal checks solute,
image>12A,waterOO>2A,OHbeyondfloat32storage<1e-5A; checkpoints + potential continuity;
each1ns endpoint staticCPU-bondedrun0 energy replay catches saved-state corruption.
No CPU dynamics. Any gatefailure stops. All historical failures retained. On wake
verify native outputs and full structural observable comparisons, then production
package only if passing; no current simulation-ready/minimum/equilibrium claim.
Eight relevant tests pass; sixconfigcomparisons and observablepreflight pass.

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

name: Preliminary cis-syn CPD strand-builder integration
description: Additive v6 is usable through explicit-solvent NAMD; full scientific release remains pending.
type: project
status: active
authority: supporting
---

User accepted bounded preliminary research qualification, then requested strand-builder
integration (2026-09-20). See `docs/cpd_strand_builder.md` and its verification report.

Active continuation 2026-10-03: user authorized work through preliminary cis-anti
structural qualification, 3 anti + 3 matched control ×10ns, then restartable
production package (no long production launch), and explicitly requires triggered
wakes rather than polling. New local-only 72h contract:
`.development-artifacts/cpd-anti-readiness-v3-20261003/contract.json`.
First batch `cpd-anti-competing-qm-v3-20261003` is launched, with independent
watcher in `cpd-anti-competing-qm-service-v3-20261003`; exact originating thread
is recorded there. Four exposed Sella/Psi4 starts: endpoint1+30 old QM, MM trial1,
MM trial7, and endpoint1−22.5 MM model61. Same MP2 model/graph/stereo/constraints;
40 gradients each,160 total,12h batch,4 local CPUs,10GiB service. Expected4h,
single overdue wake6h. Preflight +12 guard/watcher tests pass. See current top
of `docs/cpd_anti_additive_campaign.md`. On wake ACK token, audit actual native
energies/gradients, compare basins, then continue within contract. Do not launch
duplicates, reset old fit ledgers, loosen gates or confuse stationarity with
minimum/readiness. Launch receipt verifies armed processes, not message delivery.
Separate short self-test wake is queued; ACK it when received without duplicating
the QM batch. Historical September statements below are preserved as history.

Update same date: self-test wake was received/ACKed, verifying delivery. User
requested better parallelism. Now two native cases run on CPUs4–7/0–3, with
fourth process parked until original trial1 exits. A handoff runtime mismatch
(Sella Python lacks os.pidfd_open) briefly dispatched that third live worker;
its process was paused, preserving work. System-Python pidfd guardian repairs
the dependency without any native restart. Authoritative service/wake is now
`cpd-anti-competing-parallel-event-service-v3-20261003`, results/plan/launch receipt
under `cpd-anti-competing-parallel-event-guard-v3-20261003`. Both superseded watchers
stopped after replacement armed. Original dispatcher parked; intermediate
assessment will retain scheduling failure; final guardian uses real native exit
and reviews all4 cases. Old scientific input hashes/caps/deadlines unchanged.
See campaign doc top for exact handoff semantics. Do not duplicate jobs or interpret
superseded service transport failure as a scientific result.12h original batch
and72h overall caps still apply. Final independent native/basin audit pending.

Latest22:34MDT Oct3: parallel service OOM killed; guardian wake0bf582bc-7162-496c-b3dc-996614b3e695
failed, ACKed and reviewed.57 native gradients verified; old+30reference and
trial1-derived QM stationary, latter1.111677kcal/mol lower (not minimum claim).
Trial7/model61 interrupted at20/12 completed gradients; two incomplete attempts
count against40each. Sequential recovery now active under
`cpd-anti-competing-recovery-service-v3-20261003`; output
`cpd-anti-competing-recovery-v3-20261003`. Saved prefixes reproduce both next
geometries bitwise,zero newQM inpreflight. At most46newattempts,4cores,12GiB,
original6hcase/12hbatch deadlines retained. Expected2h/singleoverdue3h, watcherarmed.
Oldstopped dispatcher released with no livechild; old parallel statusrunning stale.
On newwake audit combinedold/newnative outputs,then basin decision; no duplicate
calculations or repeat2worker14GiB configuration. Full details atop campaign doc.

Latest23:25MDT Oct3: recoverycomplete wake8d326563-b02c-42a2-958b-f74238121087
ACKed/audited.75 nativegradients verified,all4casesstationary. Trial7+30 and
model61−22.5 return original QM(0.000077/0.000222Å); trial1+30newQMbranch
is1.111677kcal/mol lower,0.13024Å fromoldQM butstill0.33317Å fromMMseed.
Do not eraseoldshape failures.18newgradients recovered in3015s; originalcapskept.
Nowactive `cpd-anti-competing-curvature-service-v3-20261003`, same-nameoutput
withoutservice.8gradients,±.02/.04bohr constrained basin-separation direction
atboth+30shapes;30minexpected/1hcap,4cores/12GiB,sequential,eventwatcherarmed.
One-directionpositivecurvature/10%stepagreement diagnostic,notfullminimum.
Afterwake auditnative,then newfittingsuccessor retaining23oldtargets+newbranch,
commonreferences/unchangedgates; oldledgersstayclosed. Fullcampaignendpointpending.

Latest23:58MDT Oct3: curvaturewake0275d289-ff56-48c3-9b97-83b232d00311
ACKed/audited8nativegradients; bothdirectionalcurvaturespositive,stepdifferences
.0109%/.0415%. Newfit launched `cpd-anti-readiness-fit-service-v3-r1`,output
`cpd-anti-readiness-fit-v3-r1`,newstate `cpd-anti-readiness-fit-state-v3`.
24targets(23exactold+lower+30branch),3reps,same22coefficients±5basebounds.
Legacy23energyRMSE separatelygated so24thpointcannotdilutefailure. Fresh22column
Jacobians/gate-directedsteps,isolatedSella,240vectors/2h/firstpass stop,6GiB4cores.
Expected1h/overdue1.5h,eventwatcherarmed.3numeric tests+5exportE/Ffixtures+versions
pass. Genericpreliminaryprotocol locks/roundreservations used innewauthorizedstate;
round1of2used,oldledgerspinnedunchanged. Noauto round2; residualreviewrequired.
Onwake auditactualMMalltargets,then freeze passingcandidate before prospectiveQM.

Latest Oct4: fitwake167d7ef9-22bf-4802-941a-998f0fbc272f ACKed. Model48 first
developmentpass after48vectors/1124s. Independentreplay45,305MM evaluations/1296
fragments+5exports confirms24targets+3reps pass. EnergyRMS.471083/max1.287714,
legacy23RMS.399339; worstRMSD.240585Å/proper19.2133°. Candidatehash
b5d295e934910ef5ef0b3ea960f12155875d4943476ceb33d1974f2eba49b547.
Candidate nowlocked(newstate conformational_candidate_lock.json); furtherfitblocked.
117historicalJSONs/905explicitangles screened, no±18.75overlap. Fourprospective
cases launched `cpd-anti-prospective-qm-service-v3-r1`,native `cpd-anti-prospective-qm-v3-r1`.
40gradseach/160total/6hcase/12hbatch,4cores12GiB,sequential,expected4h/overdue6h,
watcherarmed. Frozenone-attempt scorer `cpd-anti-prospective-score-v3-r1` ready.
Onwake ACK/nativeaudit then `score_prospective_v3.py ready`; preserve commonrefs,
energy1/2 andgeometry.25Å/20° limits. Passedprospective ->finalparameterNAMDchecks
->matched6×10ns ->restartablepackage. Noappfullrelease/minimumclaim yet.

Latest Oct4 03:48MDT: prospectivewakea475b661-abeb-4fff-b041-5ae25e89fe96
ACKed/audited74QM+138MM evaluations. All4prospective casespass:
energyRMS.425150/max.723403 andallgeometry/numericalchecks. Nativeaudit sidecar
resolves inherited scorer pointmetadata. Candidateunchanged. ExactfullDNAtransfer
verified10intendedpropertorsion occurrenceschanged,control0,allotherforces/masses
identical. Nowactive `cpd-anti-solvated-engine-service-v3`,output
`cpd-anti-solvated-engine-v3`: staticcrossenginecomparisons then2×100psNVT,
30,867atoms,1fsordinarymasses,rigidwater,300K,.151MNaCl;8workers12GiB,
15minexpected/2hcap,eventwatcherarmed. Exact26image startingclearance22.55/22.30Å.
Onwake nativeauditgeometry/static/checkpoints/PBC then freezeandrun matched6×10ns.
No fullqualification/minimum/app-placementclaim. Originalconditioningdifferences
remain disclosed; future matchedstartupprotocol must be explicit.

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


Latest cis-anti review, 2026-09-27 17:20 UTC:
`docs/cpd_anti_shape_evidence_review_20260927.md`. User cautions against inherited
shape expectations; Sella remains preferred. Local 0.25 Å / 20° correspondence
gates are not experimentally calibrated shape tolerances. The −22.5° failure
already uses independently stationary Sella QM, so older optimizers alone cannot
explain all failures. Four prospective records inherited misleading parent
provenance/gradient fields (endpoint1 also `constrained:false`); actual coordinates
and energies match native Sella targets exactly, and runtime constraints were
correct. Resolved evidence is in sidecars, historical inputs unchanged.
Reconstructed all3 Jacobians /69 residuals /1587 coordinate comparisons. Local
minimax predicts feasible original bounds, but native response is nonlinear.
Separate `cpd-anti-shape-gate-refinement-v1` completed12 vectors in280.2s under
12-vector/600s cap; stopped at model cap. Trial7 worstRMSD.258881Å vs old.321259;
old −15/−30 now pass, but ep1+30, ep2lower-reference, ep1−22.5 still fail.
EnergyRMS.997450 passes, max2.015809 fails; representativeangle3.111811° fails.
No development pass or promotion; original model61 remains its old contract's
selected trial. Native audit replays11074 evaluations/312 fragments, five export
fixtures, four QM final-gradient checks; 3 numerical tests passed. No active
calculation. Next evidence priority: targeted Sella QM comparison of competing
conformations and older references when decisive, before imposing shape or adding
bond/angle terms. Model inadequacy is not established. Old ledgers/locks unchanged.

Historical cis-anti continuation 2026-09-27 UTC: user chose Sella as default for
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
