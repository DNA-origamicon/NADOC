# Final investigation status — 2026-09-14

All required simulations and analyses are complete. No application changes were implemented. Review FINDINGS.md and REVIEW_PROPOSAL.md. The replacement NVT control completed 172000 steps / 344 ps from the shared 156 ps checkpoint; its last saved frame (+340 ps) has 128.576 nm³ of void. At equal +200 ps, NVT has 114.304 nm³ / 504 aperture waters versus NPzAT 0 nm³ / 806 waters. Original GPU-resident 92% segment remains explicitly failed, not discarded. Both full OpenMM 50 ps comparisons and the full NAMD 10 ps check completed. No local dynamics remains running or paused. Original input hashes and tracked application diff are preserved.

The setup defect is missing compatible solvent-density equilibration for fixed periodic graphene. The proposed change is fresh wet-system fixed-area/normal-pressure equilibration through restraint release, hydration/volume convergence checks, then NVT from the equilibrated cell. Exact reservoir padding and full-system equilibration duration remain unvalidated. Existing dry full-system checkpoints did not rehydrate in the short tests. See run_audit.json and preservation_check.json for completion/preservation evidence.

The remainder is the historical work log and includes superseded interim statuses.

---

# Working state (2026-09-14, about 20:50 UTC)

The explicit investigation goal remains active. No application or old-job changes are authorized; all work is confined to this experiment directory and audit documentation. Do not spawn agents. User is away. Final deliverables are `FINDINGS.md`, `REVIEW_PROPOSAL.md`, figures and reproducible evidence, with no implementation patch applied.

Completed since initial investigation:
- Four bulk controls, 200 ps each. `bulk_statistics.json` has post-50-ps block statistics. NVT ~−631 bar at216nm³ vs NPT near atmospheric at208.1–208.4nm³.
- Bare graphene 100% water,500ps; NPzAT branch200ps; hydrated300mV500ps. Field branch wet throughout500frames,806watersplane at end,139sampled crossing events16distinctions. Recrossings included; not conductance.
- Actual full NAMD CPU NPzAT10ps completed,50kcal/Å²wall,4fs/8fsPME unchanged; membrane-centered origin. Z24.2394→23.78886nm, accessible cavity363.264→350.080nm³, planeO1, stilldry. No instability.
- Original8ps snapshot static checks: porewet799O; group pressures−986.7815(allstageforces),−380.8999(noENM),−344.8877(noENM/wallrestraints). Same initialized300Kvelocities because archivedframevelocities unavailable. Staticdiagnostics, not archivedruntimeaverages.
- `enm_virial.json` all saved restrained-stage direct ENMcontributions mean−316/−105/−21bar, decreasingwhilecavitygrows. ExactfirstframeenergyagreesNAMDforce-toggle; directvirialwithin0.3%ofNAMDpressuretoggle(constraintcouplingdiff).
- `accessible_void.json` excludespointswithin.35nmDNAheavy/graphene and requiresnowaterOwithin.4nm. Originalmin2.56,8ps3.52,stage01 101.12,02 221.248,03 306.304,04 363.264nm³. Largestinitialcomponent.32nm³ vs finaloneconnected363nm³. Strong evidence cavitynotDNAexcludedvolume.
- OpenMM8.6.dev-c6173db independent fullGPUengine validated. See `openmm_full/VALIDATION.md` andenergy_validation.json. Bonded energiesmatch<.04kcal, LJwithin1.163/520539kcal, electrostatic0.0141%, allmassesmatch, wallenergywithin.664/23039kcal. ExactNAMD r²switch used, noLJdispersioncorrection, properzeroNGRCNBFIX, samePMEgridalpha. Engineuses2fsLangevinMiddle/allHthermostat, differentPMEinterpolation andMCbarostat, so comparewithinengine andlabeldifferences.
- Full OpenMM NPzAT50ps completed: Z23.963305nm (1.14%contraction); accessible cavity353.088nm³;planeO0. MCpressuremovesadapt slowly; no claimdensityequilibrated. Originaldrycoordinates/vel/masses/forcefield/restraints preserved; translatingcenter putsgraphplaneatz0.

RUNNING / QUEUED:
1. OpenMM full NVT comparison50ps: PID295175, spawned byqueuePID281281 (execsession84344), logfile `openmm_validation/nvt.log`, metrics `openmm_full/nvt/metrics.jsonl`. At~20:50UTC4ps, ~22sec/ps; expectedfinish~21:07UTC. Fixed-volume comparison must finish.
2. Barepore96%NAMD is **SIGSTOP paused** at~161000/252000steps,PID256111, toavoidGPUcontention. RunnerPID215154 (execsession67975) waits foritthenautomaticallyruns92%water500ps.
3. WatcherPID287864 (execsession92477),script `openmm_validation/pause_small_during_full_pair.py`, will SIGCONT256111 afterNVTcompletes oranyfullpairTraceback, or3hlimit. State `openmm_validation/gpu_schedule.json`. VERIFYRESUMED; do notleaveourtestpausedatcompletion.
4. 92%watercasehasnotstarted. Expected96remaining~10minand92~30minonceGPUfree. Letfinish; decidefurthercontrolonlyifnewdatarequiresit.

Useful final commands (fromrepo, PYTHONPATH=. .venv/bin/python forbackendimports):
- `analyze_controls.py [optionalcase names]` updatescontrol_analysis.json; selectedcasespreserveothers. Full500framefieldanalysisalreadydone; do notneedlesslyrepeatalluntilfinal.
- `count_control_crossings.py`
- `accessible_void.py` (originalchecks,NAMDtrace,allavailableOpenMM5pssnapshots), then `plot_recovery.py` (nowusesaccessiblevoidand0–400/0–850axes).
- `plot_evidence.py`
- `audit_runs.py` validatesendmarkers+finalsteps+nofatal (NAMD canreturn0onfatal!)
- `verify_preservation.py` checks14originalinputhashesandpre-existingtrackedgitdiffunchanged. Passedtwice; rerunatend.

Remaining writing:
- UpdateFINDINGS/README/REVIEW_PROPOSALfrominterimtofinalaftercontrols; addfullOpenMMpairedresultand96/92results, limitations, maybeunderfillrecoverybranchifcausallyneeded.
- Keepconclusionscalibrated: missingcompatiblepressureequilibrationisconfirmed; initialnetworkadds tension; porebeginswet, originalearlyphysicalsystemunderpressure,cavitygrows~360nm³. Simplelargerreservoirisnotanevidencedstandalonecure. Fulloldcavitynotrapidlyrepaired; recommendfreshwetconstant-area/normal-pressureequilibrationthroughrestraintrelease, thenNVTatequilibratedcell. Exactduration/paddingandfreshwhole-systemrolloutnotvalidated.
- ExistingreviewproposalcontainsconcreteexperimentalTclsettingsandapplicationpathsbutexplicitlynotuniversaldefaultsandnoappimplementation. Originalgraphenemembrane arbitraryorientation requiresitsalignedcellframe; do notgloballyturnonisotropicNPTorflipnpt_allowedalone.
- Updategoalcompleteonlywhenremainingrequiredexperiments/analysis/reportfinished. No tokenbudgettoreport.

All originalsourcejobs/read-only paths and primaryreferences are documented inREADME/FINDINGS. Originalproductionavailable94.96ns, notfullrequested200ns. Do notclaimunsampledcrossingsexcluded. All originalappchanges(32trackedfiles)mustremainuntouched.

UPDATE ~21:11 UTC: Both full OpenMM50psbranchesfinishedcleanly. `full_statistics.json`: NPzATZ23.963305,−1.139%,normalpressure9samples10–50psmean−231.43bar,last20psZslope−.00732nm/ps => NOT equilibrated; NVTFixedZ24.2394,mean−398.74bar. Bothaperture0final. AccessiblevoidfinalNPzAT353.088 vsNVT368.256 fromsame363.264. FINDINGSupdatedwithpairedtableandlimitations. `plot_recovery.py`now usesaccessiblevoidandnormalzerobaselineaxes. `accessible_void.py`alsoevaluatesall25NAMDfullDCDframes.
WatcherautomaticallyresumedNAMD96PID256111; verifiedRstateandprogress. Watcher/queuefinished.96now~193000/252000steps (~382/500ps), shouldfinish~21:16UTCthenrunnerautomaticallystarts92%500ps. NoOpenMMdynamicprocessremains. Finalrequiredworkis96/92completion,finalanalysis/figures/reportstatus/provenancecheckandgoalcompletion. ConsideradditionalunderfillNPzATrecoveryonlyifnewresultsjustify; do notbroadenautomatically.

UPDATE ~21:26UTC:96%finishedwet500ps(lastplane709,last60psGPRESSAVG−1299bar,maxvoidtiny),14distinctionscrossed.92%nowrunning~96k/252ksteps (188ps),developingvoid:largest6.08nm³at96ps,19.712at186ps,planewater538. Newevidencejustifiedoneboundedintervention: `branch_depleted_npzat.py` (session3779) capturedimmutable92%restartstep80000/time156ps, launched `open_pore/fill_92_npzat`200ps. Source92continuesNVT. Atbranch20psZ11.047nmvs12,void9.216nm³,planewater652. Bothmustfinishbeforefinal. Read`depleted_npzat_status.log` andchildmeta.
IMPORTANTnewpressureanalysis: NAMDoutputPressurelogscontain **GPRESSAVG tensor**, notjustinstantGPRESSURE. `namd_normal_pressure.py` parsesit. FullNAMD10ps4–10psmeanPzz−0.989bar,intervalSD8.27bar (15samples),whilePx/Py−85/−109bar. So normalmechanicalpressureapproached1atmshort-term butcavitypersisted. FINDINGS/READMEupdated; no claimcompletehydrationequilibrium. Forchild92NPzAT, thisscriptwillanalyzePzzafter50psonceavailable. Child100NpZATdidnotrequestoutputPressure,sotensorunavailablethere. ExistingbulkGPRESSAVGanalyseswerealreadycorrect.

UPDATE~21:33UTC: Original92%GPUresidentcase FAILED step96012 (188.024ps), return−6, movingtoo fast(0atomsPE0). Preservefailedrunoutputs; do notcount500pscomplete. Detectedbecauseprogressstopped. Pressurebranchcontinuesstable(>150ps),nearlyeliminatedvoidby80ps,plane797. Added`run_depleted_offload.py` session80346, `open_pore/fill_92_nvt_offload`, startingSAMEimmutable80000/156pssnapshotasNPzAT; NVT344ps(run172000),GPUresidentoff,+p4,margin4(sameasNPzAT). At~21:33,12ps;benchmark~.0158sstepduringGPUcontention (~45minworst,improvesafterNPzATdone). Checkcrossingoldfailuretime32psintobranch. Nochangeapp/nativeNAMDcode. Samepotentialatbranchmatchesparentwithin.007kcal; startupconstraintprojectiontemperaturediff.05K. Needfinishbothbranches,combine/reportfailedsegmenthonestly, adaptfiguresfornewNVT_offloadname/parentoffset.
