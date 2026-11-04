# Current CPD priority — 2026-11-04

Managed-start follow-up: the first builder/direct-engine smoke missed memory
admission's refusal of `reinitvels`. The user's cis-anti child failed before
native execution. That directive is now admitted; real production-create/start
HTTP handlers and the full runner completed 10 ps at 4 fs/HMR for all four
isomers. Resource-contention retries retained the admission guard. Temporary
jobs were removed and source job metadata stayed unchanged. See
`docs/audits/cpd_managed_start_20261104.json`.

The four exact provisional MVP asset sets (cis-syn-I, cis-anti-I, trans-syn-I/II)
now pass numerical 4 fs/HMR qualification with the current 8/10/12 Å nonbonded
settings, PME grid 1.5 Å and PME every step. Two existing starts/seeds per isomer
were compared against ordinary-mass 2 fs: 25 ps NPT + 10 ps NVE each. One cis-anti
short-window paired drift criterion failed; its retained, bounded 50 ps NVE
confirmation (both starts, both timesteps, unchanged limits) passed. Independent
saved-input/log/mass/endpoint audit passed. This qualifies numerical integration
only, not equilibrium/kinetic equivalence or force-field scientific release.

`backend/core/cpd_integrator.py` admits only exact tested parameter/topology/
chemical-definition hashes from `backend/data/forcefield/cpd_hmr_validation.json`.
Legacy preliminary-v6 and untested models retain the <=2 fs ordinary-mass block.
Mass-changing production starts redraw velocities and record that choice; same-mass
continuations preserve velocities. The HMR reader now handles historical mixed
I10-solute/I8-solvent PSF bond rows. Native managed-child launch and live app plan
checks passed; original designs/jobs were unchanged. Evidence and limitations:
`docs/audits/cpd_hmr_validation_20261104.json`.

## Earlier campaign state

2026-10-17 finite MVP campaign CLOSED: fouradmitted externalCGenFF models (cis-syn-I,cis-anti-I,trans-syn-I/II) separately pass canonical numericaladmission in internal six-T scope. Cis-syn return blocker resolved. Archive cpd-provisional-mvp-models-v4.zip; docs/audits/cpd_mvp_final_scope_audit_20261017.json. Physicalvalidation/equivalence/parameter-sensitivity remain explicitly insufficient under existing finitepolicy. No activejob, native3131.489166s/48h, no automaticrefit/extension orproductionpromotion. Earlier pending/blocker entries historical.

2026-10-17 completion gap: cis-syn-I independent external input now prepared and requested through user CGenFF account, Archive cgenff-cis-syn-assignment-input-v1.zip. Quantitative applicable NMR reference comparison remains unregistered; no automatic MD/fit. Trans-syn-II formation includes sensitized unmodified TpT (PMID8374057), correcting earlier modified-only restriction. Goal incomplete; see latest current_handoff.json and docs/audits/cpd_cis_syn_external_input_20261017.json.

2026-10-17 CGenFF v4 finite numerical panel CLOSED: all3new isomers,2starts each,2velocity seeds,1fs admission pass; all12paired1fs/2fs1ps NVE diagnostics pass. No active jobs. Native ledger2947.396s/48h. Provisional numerical scope only; physical validation/parameter-sensitivity equivalence remain insufficient. No automatic refit or extension. Archive minimum-viable-candidates-v4 and docs/audits/cpd_cgenff_numerical_panel_20261017.json are current. Earlier entries below retain historical stage states.

2026-10-17 next native candidate is isolated cgenff-dna-transfer-v4 (v3improper order failed strict NAMD matching). Six canonical191atom six-T starts pass GPU energy/force loading; all22center signs pass. Source/basin relevance and dynamics remain unqualified. Audit docs/audits/cpd_cgenff_dna_geometry_20261017.json. No further identical embedding/native-static retries needed.

2026-10-17 sugar-bearing CGenFF returns pass identity/coverage. Isolated DNA transfer-v3 uses native charges plus matched CGenFF lesion-reference increments (base−0.138e/sugar+0.138e; OH caps0). Three191atom topology harnesses pass full coverage/netcharge−5e and independent unchanged-backbone checks. Audit docs/audits/cpd_cgenff_sugar_return_20261017.json. Historical v2/production untouched. Coordinates/dynamics remain unqualified.

2026-10-17 CGenFF returns received: all3cores pass mapped identity, neutral charge, external coverage and6NAMD run-zero checks. Audit docs/audits/cpd_cgenff_return_intake_20261017.json. Use short relative NAMD outputName in Archive cwd: long absolute outputName caused output-writing crashes. Preserve failures. DNA boundary/dynamics remain unqualified; external-assignment blocker resolved.


2026-10-17 archived capped-core QM reuse: cis-anti-I/trans-syn-I/II pass current identity and source-integrity checks; see docs/audits/cpd_qm_target_reuse_20261017.json. Do not repeat core optimization/Hessian acquisition. Cis-anti-I retains exact-core minimum certification; trans-syn positive-frequency evidence remains historical. No new native use.
User requests minimum viable NAMD models for experimentally established TT
photoproduct isomers only, with separate stereochemical qualification and assumed
noninterconversion in ordinary MD. Use external parameterization implementations.
No indefinite fragment-driven refinement: further energetic refinement requires
substantial NAMD departure from a prespecified applicable established observable.
Chemical/numerical admission remains mandatory; insufficient evidence stays explicit.
See docs/cpd_minimum_viable_namd_policy_20261017.json and the latest campaign head.
Historical bad-sugar DNA results do not qualify canonical DNA. Retain historical
failures; no automatic expansion to all eight registry entries or budget reset.

User requires resolved experimental attachment-order evidence before trans-antiI/II admission; no provisional dual embedding from class-level evidence. See docs/audits/cpd_mvp_formation_roster_20261017.json.

Earlier state below is historical and superseded where inconsistent.

---
name: Preliminary CPD strand-builder integration
description: Preliminary cis-syn product boundary and last recorded cis-anti qualification hold.
type: project
status: active
authority: canonical
---

# CPD strand builder

Memory reorganized October 17, 2026; no scientific state was requalified.
The latest recorded campaign handoff is October 5. Expired clocks and historical
approval requests below do not authorize a new launch. Reconcile with the current
campaign record and explicit user authorization before resuming numerical work.
Full chronology and exact prior head: [archive](project_cpd_strand_builder_archive.md#active-head-snapshot-preserved-october-17-2026).

## Last recorded cis-anti qualification and pending decision

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

## Preliminary cis-syn product boundary

These are recorded integration results, not checks rerun during memory maintenance.

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

## Binding scientific and execution rules

- Preserve locked stage inputs, parameters, exposed/holdout identities, failed
  verdicts and original budget ledgers. No automatic fit, continuation, deadline
  reset, readiness promotion or cloud spending follows from a completion event.
- Scientific acceptance and molecular-geometry authorization remain separate.
  Prepare concrete atom/bond/ring A/B evidence before requesting placement changes;
  never alter constants, locks or goldens to obtain a pass.
- New geometry optimizations follow the [Sella preference](feedback_sella_default.md)
  and independent stationarity/chemistry checks; optimizer completion is not a minimum.
- Follow the [CPD validation rule](../.claude/rules/cpd-anti-validation.md),
  [campaign record](../docs/cpd_anti_additive_campaign.md), and applicable frozen
  versioned protocol. Historical protocols/worker sources must not be rewritten.
- Use verified Archive output/scratch, sequential authorized jobs and actual
  completion acknowledgements. Do not duplicate work from delayed historical wakes.
- Outstanding interpretation/provenance errata, final-context startup, six-run
  validation and portable packaging remain unqualified at the recorded hold.
  This maintenance task does not resume them or infer a replacement budget approval.
