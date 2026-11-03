# Cis-anti-I additive parity campaign

**Four-isomer provisional MVP closeout — 2026-10-17.**
Cis-syn-I external CGenFF return now passes independent identity/stereo/coverage,
charge-conserving transfer, two canonical six-T starts and two seeds/start.
All16admission stages and4paired1fs/2fsdiagnostics pass;916savedframe/endpoint
checks retain22centers; restartmax0.0048kcal/mol, NVEmaxfraction0.000152906.
Audit docs/audits/cpd_cis_syn_external_numerical_20261017.json. Legacy model untouched.
Allfour admitted isomers now have external provisional numerical MVP packages.
Finite campaign closes under the existing missing-reference/insufficient-evidence
policy: physical accuracy, practical equivalence and original parameter-sensitivity
question remain insufficient. This is not a full release or experimental validation.
No energetic refinement trigger demonstrated. Sharednative use3131.489166s
(52.19min)/48h; no active jobs. Archive cpd-provisional-mvp-models-v4.zip contains
parameters, provenance, qualification limits and reproducible example pointers.
Requirement-by-requirement audit: docs/audits/cpd_mvp_final_scope_audit_20261017.json.
Terminal/mixedisomer contexts and equilibrium behavior remain unqualified; excluded
orderedisomers are not silently admitted. No automatic extension or production promotion.

**External assignment blocker revalidated — 2026-10-17.**
Cis-syn-I assignment remains absent after consecutive input-preparation, NMR
retrieval, mapping and current inventory turns. Inspected extracted and zipped
CGenFF stream identities: only prior CAI/TSI/TSII/CAIS/TSIS/TSIIS/DTR returns.
Prepared CSIS input awaits the user-selected CGenFF account. No authenticated
connection/licensed executable is available locally. Completed numerical panel
stays closed; physical validation remains explicitly insufficient. No extra MD,
fit or repeated retrieval is justified merely to occupy this wait. Resume at
external-return identity/stereo/coverage audit when supplied. Blocker audit:
`docs/audits/cpd_mvp_external_assignment_blocker_20261017.json`. Native ledger
2947.395765s unchanged; no active native jobs. Goal incomplete.

**1TTD backbone reference mapping verified — 2026-10-17.**
All22deposited epsilon quartets resolve through explicit original-to-CIF mapping.
TTD merges originalT8/T9 into labelres8 and uses mixed sugar aliases; mapping
is supported by component bonds and20covalent-distance checks. Independent
MDAnalysis/numpy dihedrals agree within0.000072degrees. All72sugar centers in
the source structure are canonical. Lesion T9pA10 epsilon−72.3683degrees lies
in deposited−100to−70interval. Ten other source intervals have small overruns,
maximum circular deviation2.6097degrees, retained without widening criteria.
This is source-coordinate consistency, not force-field validation. Audit:
`docs/audits/cpd_cis_syn_nmr_mapping_20261017.json`. Source solution conditions,
measured-versus-assumed distance provenance and experimental forward-model
uncertainty remain gaps; no simulation or fit launched. Cis-syn CGenFF return
remains pending. Native ledger unchanged2947.395765s; goal remains incomplete.

**Cis-syn quantitative NMR deposition recovered — 2026-10-17.**
Archived1TTD MR/mmCIF and BMRB4415STAR with hashes. Parsed457restraints:
28assumed hydrogen bonds,407distance records requiring measurement-provenance
review,22dihedrals. Fifty non-Hbond records involve lesionT8/T9. Source epsilon
T9pA10 interval−100to−70degrees is a concrete candidate observable, not an
equilibrium-population confidence interval. BMRB conditions278±1K,pH*6.6±0.1,
0.7mM each DNA strand. Salt and primary-method uncertainty remain unresolved.
Current merged-TTD residue numbering differs from original author numbering;
map explicitly before analysis. Audit docs/audits/cpd_cis_syn_nmr_reference_20261017.json.
No new cis-syn CGenFF return identified in Downloads; legacy core(2)(2) is TSII.
No native jobs/fit. Next: source mapping/method qualification and external return.

**Cis-syn external input prepared — 2026-10-17.**
One62atom neutral canonical dinucleoside input passes10mapped sugar/ring centers
and MOL2 graph/stereo roundtrip. Archive cgenff-cis-syn-assignment-input-v1.zip
is ready for user CGenFF account; no local licensed executable/account connection.
See docs/audits/cpd_cis_syn_external_input_20261017.json. This closes input
preparation only, not assignment or qualification. Existing legacy model untouched.
Quantitative primary NMR data remain unregistered: retrieval failures preserved
in experimental-reference-review-v1/quantitative_reference_readiness.json.
Qualitative NOEs are not assigned invented numeric distance tolerances. No new
native simulation or fit; shared ledger unchanged2947.395765s. Goal remains active.

**Completion audit and formation correction — 2026-10-17.**
Goal remains incomplete despite numerical-panel success. See
`docs/audits/cpd_mvp_completion_gap_audit_20261017.json`. External-workflow
provenance remains incomplete for legacy cis-syn-I; quantitative applicable
experimental references and source-matched fixtures remain unregistered. No new
native computation or parameter fitting is justified yet. Primary PMID8374057
explicitly reports trans-syn-II from sensitized unmodified TpT photolysis at2%
yield, correcting our earlier modified-precursor-only restriction. This does not
establish ordinary genomic-DNA formation. Roster corrected; earlier closeout
statements retained as historical. NMR reference candidates identified for the
admitted isomers; quantitative observables/tolerances still require extraction.

**Finite CGenFF numerical panel closed — 2026-10-17.**
Downloaded sugar-bearing CGenFF assignments now yield isolated provisional v4
DNA candidates for cis-anti-I, trans-syn-I and trans-syn-II. All three passed two
canonical six-T starts and two independent velocity seeds per start: 10 ps
restrained + 10 ps unrestrained + 1 ps restart at 1 fs. All 48 stages passed;
2,748 saved-frame/endpoint checks retained all 18 sugar and four CPD centers.
Largest restart potential discrepancy 0.0048 kcal/mol (registered limit 0.01).
The paired 1 fs/2 fs NVE diagnostic passed all 12 one-ps runs; maximum absolute
energy change/initial kinetic energy was 0.00023875 (limit 0.001). Paired endpoint
solute displacements were 0.547–0.675 Å without fitting: this does not establish
trajectory or ensemble equivalence. Ordinary masses, rigidBonds all, no geometry
locks or production changes. Native campaign use 2947.396 s / 48 h; initial
admission panel used 552.661 s / 3600 s. No active jobs or automatic extension.

Explicit preregistered expectations and outcomes are in
`docs/audits/cpd_cgenff_numerical_panel_20261017.json`: identity/coverage/charge,
minimization energy decrease, finite/stereo retention, restart parity, and the
short integration diagnostic all passed. Minimization is not minimum certification.
Exact candidate files retained at Archive `minimum-viable-candidates-v4`, with
source hashes and scope restrictions. Their matched-reference charge transfer
remains provisional. Historical failed inputs/runs and v3 improper-order failure
remain preserved. Legacy cis-syn-I retains only its separately audited scope.

**Verdict:** provisional numerical qualification only. Physical validation and the
original parameter-sensitivity question remain insufficient/inconclusive: no
source-matched experimental DNA context, relevant basin coverage, calibrated
parameter family or physical equivalence margin was evaluated here. Terminal
lesions and mixed-isomer systems remain unqualified. Trans-anti I/II remain
excluded pending resolved attachment-order evidence; trans-syn-II formation
provenance remains context-limited. No established-observable discrepancy has
been demonstrated to trigger energetic refinement. Stop this finite panel; retain
these provisional candidates and require applicable observable validation before
claiming physical qualification. Melting studies remain user-owned.

**First solvated two-seed numerical admission passes — 2026-10-17.**
Cis-anti-I start1solvated with CHARMM TIP3P in68Åcube;28NaClpairs+5Na,
29538atoms, neutral and complete parameter coverage. Solute mapping/22center
signs unchanged by assembly. Solvent1000step and restrainedwhole2000step
minimization lower their own defined potentials. Twoindependent seeds35171/80239
pass10psrestrained+10psunrestrained+1psrestart at1fs, with all22centers retained
in every saved frame/endcoordinate. Restart potential deltas0.0030/0.0048kcal/mol
pass the0.01computational tolerance. Initial unsupported nonbondedFrequency
spelling failed before computation; corrected nonbondedFreq run and failure preserved.
No physical equivalence, population convergence,2fsqualification or known-basin
coverage claim. This is one six-T engineering start only. No active native job.
Audit: docs/audits/cpd_cgenff_solvated_pilot_20261017.json.
Next: remaining5registered starts/two seeds under the shared1h admission-panel
allowance; then intended-timestep checks and finite evidence review. No new fit.

**Canonical six-T engineering starts and native energy/force loading — 2026-10-17.**
Two191atom starts per admitted isomer now pass all18sugar+4CPDcenter signs,
including the rounded PDB coordinates consumed by NAMD. Proper-rotation heavy
RMSD between starts: cis-anti-I2.514Å, trans-syn-I5.128Å, trans-syn-II4.685Å.
These are distinct embeddings, not demonstrated experimental basins or equilibria.
Initial trans-syn embeddings failed because placeholder stereotags were used before
embedding. Bounded repair maps tags from independently audited sugar-bearing
coordinates; corrected starts pass. Original failed attempts retained.
NAMD caught an improper-order issue missed by permissive ParmEd matching:
parent C4,N3,C5,O4 versus donor C4,C5,N3,O4. Isolated transfer-v4 replaces only
that inherited tuple with exact donor ordering, retaining numerical parameters.
Prior v3candidate and native failure retained. V4independent topology/parent-term
comparison passes; all6GPU run-zero jobs terminate with finite energy/force arrays.
Maximum atomic forces344–366kcal/mol/Å indicate unrelaxed seeds, not minimum
certification or a parameter-refinement trigger. No dynamics or equivalence claim.
Audit: docs/audits/cpd_cgenff_dna_geometry_20261017.json.
Shared native use2394.7352s/48h. No active native job. Next: solvation, registered
bounded preparation/thermal/restart admission. Source-matched experimental-context
fixtures and observable registration remain required before physical validation.

**Sugar returns complete; isolated DNA topology transfer passes — 2026-10-17.**
All4external result sets copied byte-identically from Downloads to Archive;
input bytes, returned stereo, neutral charge and CGenFF5.0coverage pass. For all3
lesions, matched-reference charge deltas are−0.138e on bases,+0.138e on retained
sugars, zero on terminal OH H/O caps. No arbitrary redistribution needed.
Isolated v3policy uses native DNA q plus external lesion-minus-reference q;
retains native sugar/backbone bonded terms and LJ, copies external base/glycosidic
terms by atom role with isolated aliases. Original v2/production files unchanged.
Three191atom six-T topology harnesses resolve every term and retain net−5e.
Independent comparison confirms exactly2added crosslinks; unchanged nonbase terms
172bonds/318angles/454dihedrals/12impropers per case, plus unchanged nonbase UB.
Initial no-NBFIX assertion failure preserved; v2exporter retains external halogen
exceptions under aliases. No native dynamics or physical qualification claim.
Audit: docs/audits/cpd_cgenff_sugar_return_20261017.json.
Next: actual canonical-coordinate admission and both starting conformations,
finite native allocation and established-observable registration. Transfer policy
remains a provisional hypothesis requiring NAMD evaluation, not a validated model.
No new native simulation; shared used2392.9863s/48h unchanged.

**Canonical sugar-bearing external assignment package ready — 2026-10-17.**
Three62atom neutral dinucleoside CPDs and one31atom neutral thymidine reference
prepared for external CGenFF. Each CPD passes4mapped ring+6CCD-referenced sugar
centers; reference passes3sugar centers. All4pass graph/stereo MOL2 roundtrip.
ETKDG seeds only; no optimization/minimum claim or new QM. Corrected hydrogen
mapping and reference aromatic-MOL2 serialization failures retained. Final package
excludes failed inputs and uses USER_CHARGES formal placeholders.
Archive package: cgenff-sugar-assignment-inputs-v1.zip under campaign root.
Audit: docs/audits/cpd_cgenff_sugar_inputs_20261017.json.
Next: user CGenFF assignment of all4inputs; inspect actual glycosidic terms and
lesion-minus-reference charge differences at every retained atom and OH cap.
This is a proposed boundary-transfer diagnostic, not an approved charge correction.
The neutral-base constraint remains in force; no arbitrary spreading or automatic
promotion. Free3prime/5prime OH models do not themselves qualify phosphate transfer.

**Direct CGenFF core-to-DNA transfer fails boundary admission — 2026-10-17.**
A static mixed-type graph audit finds the same concrete gap for all3assignments.
Each removed N1-methyl cap carries+0.133e, leaving the retained base pair−0.266e;
the frozen DNA patch scope requires neutral bases and unchanged native sugar charges.
Combining returned CGenFF base types with native DNA sugar types leaves2bonds,
10angles and30dihedral instances uncovered per pair, including glycosidic terms.
Core completeness/native loading remains valid; it does not imply DNA completeness.
Audit: docs/audits/cpd_cgenff_dna_boundary_20261017.json.
No charges redistributed, terms invented, coordinates changed, or simulation launched.
Next: prepare actual canonical sugar-bearing external assignment inputs and define a
compatible boundary transfer policy; retain the existing neutral-base constraint until
an explicitly versioned alternative is justified. Existing two-sugar generator mixes
legacy fitted terms and cannot be reused as external CGenFF parameter authority.

**CGenFF returns admitted to capped-core native preflight — 2026-10-17.**
User supplied all3result directories in Downloads; originals untouched, all12files
byte-preserved on Archive at cgenff-return-intake-v1. Submitted MOL2 files match
prepared inputs exactly. Returned graphs/stereo pass current mapped RDKit checks.
CGenFF4.0 requires library5.0, available in Archive reference_forcefields.
All3cores have36atoms, neutral net charge,38bonds/72angles/114dihedrals/4impropers;
external ParmEd resolves all terms. Max parameter penalty46.1; charge42.242 for
cis-anti-I and42.083 for both trans-syns. These are analogy scores, not energy bounds.
All6NAMD GPU run-zero checks pass at submitted and archived-QM geometries using
short relative output names. Two initial runs (GPU/CPU) failed during output after
finite energies; CPU reported buffer overflow. Failures retained; shortening only
outputName resolves GPU run. This is static loading, not dynamics stability.
No practical equivalence, fullDNA qualification or sampling claim; no refit.
Audit: docs/audits/cpd_cgenff_return_intake_20261017.json.
Next: canonical DNA boundary/charge/parameter reconciliation and isolated admission
fixtures, then registered finite NAMD dynamics. External-assignment blocker resolved.

**User priority reset: minimum viable models per established TT isomer — 2026-10-17.**
Treat named CPD configurations as non-interconverting in ordinary NAMD. Each
formation-supported isomer requires separate model identity and qualification;
shared compatible parent terms may be reused. Registry membership alone does not
admit a product. No new-isomer discovery; melting remains user-owned.

Aim for finite minimum viable NAMD models using externally implemented workflows.
Correct chemistry, parameter completeness and native numerical stability remain
mandatory. Additional energetic refinement requires NAMD evidence of a substantial
departure from a prespecified established observable relevant to that isomer/context,
after setup and sampling explanations are assessed. Fragment QM discrepancies alone
are diagnostic limitations, not automatic vetoes or justification for indefinite
refinement. Missing references or insufficient sampling remain explicit limitations;
no invented equivalence claim. Preserve every earlier failure and verdict.

Policy: `docs/cpd_minimum_viable_namd_policy_20261017.json`.
Next: formation-supported roster, external-tool verification, reference observables
and finite allocation within the existing shared48h ceiling (known0.5161h used).
Do not multiply48h by isomer or silently expand scope. No new native job launched
by this policy update; candidates isolated and production approval gate unchanged.

**External reader numeric parity and assignment handoff — 2026-10-17.**
All three224x224 matrices match ffTK2.2 conversion to <5e-16 scaled error.
Includes harmonic half-factor,0.943^2 frequency scaling and per-stretch Bohr/Å
conversion; angular dimensions remain radians. This proves implementation parity,
not empirical scaling accuracy or complete parameter/model qualification.
Audit: docs/audits/cpd_archived_fftk_numeric_20261017.json.
Prepared Archive ZIP with all3checked CGenFF inputs and handoff instructions:
external-core-geometry-v1/cgenff-assignment-inputs-v2.zip (under campaign root).
User asked for local CGenFF path or account-based assignment. Initial assignments
remain an external dependency; no credential request, submission or cloud spend.
No new QM, fitting or NAMD job; shared native use remains2388.970s/48h.

**Archived targets through external OptKing/ffTK interface — 2026-10-17.**
All three admitted capped-core Hessians transform with unchanged external OptKing:
224 redundant coordinates, Jacobian rank102, finite symmetric matrices. ffTK2.2
unchanged parser reads224nonempty rows but adds an empty225th row at terminal
newline. Separately preserved copies omit only that final newline; readback then
returns exact224x224 matrices for all3. Native outputs and upstream code unchanged.
Expectations and verdicts: docs/audits/cpd_archived_fftk_interface_20261017.json.
No electronic calculation or parameter fitting. This is an explicit archived-data
adapter, not a newly completed native QM job or a complete ffTK fit qualification.
Numeric unit-conversion parity and reconciliation with final PSF remain required.
Initial CGenFF assignments remain unavailable locally. No production changes.

**Archived QM targets recovered and re-audited — 2026-10-17.**
All three admitted capped-core targets (cis-anti-I, trans-syn-I, trans-syn-II)
pass current mapped RDKit stereochemistry, element/order, provenance hash,
finite 108x108 Hessian and symmetry checks. Atom-order invariance and reflected
negative controls pass. Archived copies are hash-matched despite historical /tmp
paths; historical manifests remain unchanged. Frozen-core DF-MP2/6-31G(d) targets
are available without repeating electronic calculations. The recent cis-anti-I
optimization attempt was avoidable; preserve its deadline failure and cost.
Cis-anti-I retains its exact-core local harmonic minimum certification.
Trans-syn I/II retain historical positive-frequency evidence (102 modes each),
not a fresh independent stationarity certification. No DNA/minimum transfer claim.
Audit: docs/audits/cpd_qm_target_reuse_20261017.json.
Next: adapt archived targets to the external bonded interface and obtain external
initial assignments; no new core optimization/Hessian acquisition. External
assignment inputs already prepared; local licensed CGenFF executable unavailable.
No native calculation, fit or production change; known cost remains2388.970s/48h.

**Supported-core preparation and explicit trans-anti admission limit — 2026-10-17.**
User requires resolved experimental attachment-order evidence for trans-antiI/II;
class-level evidence does not admit either ordered DNA model. Roster updated.
External ffTK geometry inputs registered for cis-anti-I/trans-syn-I/trans-syn-II.
First cis-anti-I job reached300s deadline; panel stopped, both trans-syn jobs unrun.
Native process group terminated; no completed geometry/minimum or NAMD claim.
Do not repeat the same acquisition; inspect existing audited QM targets first.
CGenFF submission package prepared for all3neutral36atom capped cores, with
RDKit graph/stereo MOL2 roundtrip pass and atom maps. V2 fixes charge-method label
to USER_CHARGES/formal placeholders. No external submission or fitted charges.
Package: /media/jojo/Archive/NADOC_archive/runtime/development-artifacts/cpd-cis-anti-i-bounded-sensitivity-v1/external-core-geometry-v1/cgenff-inputs-v2/submission_manifest.json
CGenFF executable absent locally; prior biotin handoff records user website access.
Audit: docs/audits/cpd_external_core_preparation_20261017.json.
Known native use2388.970s=0.663603h/48h.
Next: existing-target inventory plus external initial assignments; preserve scope
and separate capped-core preparation from canonical DNA qualification.

**Cis-syn legacy evidence independently requalified for canonical configuration — 2026-10-17.**
Existing accepted cis-syn-joint-v6 files and all4linked evidence hashes match.
CCD-referenced heavy-neighbor sugar checks pass80starts/endpoints (4800centers).
Independent streaming audit passes all17000saved frames in68overnight blocks,
including mapped CPD ring configuration and crosslink graph;1054000center checks.
Retain existing preliminary model for its adjacent internal intrastrand tested scope;
no new refit is justified by one replica's lesion opening without an applicable
established-observable discrepancy. Numerical evidence is reusable. Practical
equivalence remains unestablished and lesion-opening sampling insufficient.
This legacy published-derived model includes local fitting: do not relabel it as
new external ffTK output or claim all-isomer external-workflow goal complete.
Audit: docs/audits/cpd_mvp_cis_syn_reuse_20261017.json.
No native jobs, parameter edits or production promotion; shared native cost unchanged.
Next: other isomer formation/parameter provenance and isolated candidate preparation.

**External bonded interface bounded check — 2026-10-17.**
Upstream ffTK2.2 bonded input generation passes through GUI-backed QMtool;
text-mode attempts and GUI old-package conflict preserved. No upstream source edit.
Three120s-capped attempts: first fails QCEngine subprocess PATH, second fails
missing pkg_resources, third reaches deadline during79-displacement Hessian.
Repairs: isolated OptKing0.2.1, runtime bin on PATH, Setuptools<81. QCEngine
version preflight now returns1.6. Last process group terminated; no active job.
Native completion expectation FAIL; Hessian readback NOT EVALUATED. This is an
incomplete tool check, not molecular instability or a bad CPD model verdict.
No further identical example retry. Geometry compatibility pass remains valid.
Audit: docs/audits/cpd_external_fftk_bonded_20261017.json.
Shared known native use2088.957s=0.580266h/48h. Formation and candidate
qualification work remains incomplete; no new parameters or production changes.

**Supported external runtime verified — 2026-10-17.**
Isolated upstream Psi4 1.6 installed on Archive, with Pydantic<2 dependency pin.
Unchanged ffTK2.2 input completed in4.071s. After correct PSF
initialization, unchanged reader imported3optimization frames. Original exactly-one
frame expectation FAILS and is retained; reader is designed to import all3markers.
Final14atom coordinates match native final geometry within PDB rounding
(max component error0.0004983A). No minimum certification or fitting claim.
Archive contains failed environment solve/import and reader harness attempts.
Audit: docs/audits/cpd_external_fftk_supported_runtime_20261017.json.
Working8-entry formation inventory: docs/audits/cpd_mvp_formation_roster_20261017.json;
pending ordered anti assignments are not exclusions or qualifications.
Known shared native use1866.646s (0.518513h/48h); no active native job.
Next: complete ordered formation provenance and test external charge/bonded fitting
interfaces using published assets before generating per-isomer candidate parameters.

**External native interoperability check — 2026-10-17.**
Unmodified ffTK2.2-generated pyrrolidine MP2/6-31G* input completed under
Psi4 1.11 in4.772s (120s registered cap). Expectation1 passes. Expectation2
fails: unmodified ffTK reader added zero coordinate frames, because it requires
an older OptKing output marker missing from this output. Preserve native output,
reader failure and input; no minimum certification or CPD qualification.
Shared known native use now1862.576s=0.517382h of48h. No active native job.
Audit: docs/audits/cpd_external_fftk_native_20261017.json.
Next: isolate a supported upstream runtime or reader; no identical rerun or
fabricated completion marker. Published-example fitting stages remain untested.

**External workflow static preflight — 2026-10-17.**
Author-distributed July2024 ffTK downloaded to isolated Archive; package identifies
as2.2 and loads in VMD1.9.3 with Psi4 writer/reader procedures. Upstream source
unchanged. Published supplementary dataset and PDF retrieved via
https://doi.org/10.60893/figshare.jcp.c.7254565; supplied MD5 checks pass.
Extracted unchanged14atom pyrrolidine solute from published Psi4 solvated PDB;
external writer generated syntactically valid MP2/6-31G* input (neutral singlet,
2threads,2GB). This proves input generation, not native QM/parser interoperability,
minimum certification, fitting, or CPD qualification. No QM/MD job launched.
Audit: docs/audits/cpd_external_fftk_preflight_20261017.json.
Next: reconcile shared budget and register bounded native example; complete
formation provenance/ordered atom mapping before per-isomer admission.

Earlier active-state entries below are retained history, superseded above.

**RDKit identity recheck and established-product scope — 2026-10-17.**
User limits work to previously established products of thymine-thymine
photoreactions, not discovery of new isomers. A mathematically possible registry
entry is not formation evidence or authorization to parameterize it. Require
experimental product provenance and the applicable chemical context before
admitting another isomer campaign. Do not assume all eight entries form in DNA.
Taylor2023 explicitly reports no evidence for adjacent cis-syn-II in dinucleotides
or longer DNA; adjacent trans-syn-II formation is reported for a modified
 dinucleotide derivative. These distinctions must remain visible in future scope.
Source: https://onlinelibrary.wiley.com/doi/full/10.1111/php.13694

Fresh RDKit2026.03.5 audit:8existing capped-core coordinate structures and10recent
canonical cis-anti-I directional-probe structures pass mapped connectivity/core
handedness checks. Stored stereo annotations removed before 3D reperception with
AssignStereochemistryFrom3D and recursive rdCIPLabeler. Both probe centers retain
canonical C1'/C3'/C4' parity. All8core atom-reordering controls pass; reflected
coordinates rejected. No new geometry, isomer enumeration, QM, MD, production
change or experimental formation claim. A reader schema-key error was repaired
before the successful run, with failed reader retained in Archive.
Audit: `docs/audits/cpd_rdkit_identity_20261017.json`.
This does not rehabilitate historical full-DNA sugar errors or qualify energetics.

Earlier active-state entries below are retained history, superseded above.

**Directional-energy panel audited and closed — 2026-10-17.**
Acknowledged failure trigger `51bc37ea-2b17-4034-a46c-7584197f0fd8`.
All10native energies succeeded in1857.80s (30.96min;0.5161/48h ceiling).
Failure was postprocessing NumPy-Boolean JSON serialization. Preserved failed
worker/log/failure.json; recovered report using scalar conversion only, zero new
native calls. Independent audit re-extracts native energies, checks returned
coordinates/canonical identity, fixed backgrounds/bonds/angles and recomputes MM.
Audit passes provenance/calculation checks; scientific predictions below do not
all pass. No tolerance changes, hidden retries, fit, MD or production promotion.

Explicit preregistered expectations versus results:
- E1 center reproducibility<=1e-5kcal/mol: FAIL overall. A1.03454e-5 (narrow miss),
  B8.06280e-7 (pass). Retain failure; not a validated bound on all point errors.
- E2 2/4degree derivative consistency<=max(10%,0.2 slope or2 curvature): FAIL
  overall. A QM slope difference0.23709 and MM0.20964 exceed0.2kcal/mol/rad.
  All curvature comparisons and all B comparisons pass.
- E3 positive QM/MM curvature at both starts/steps: PASS. Directional positivity
  does not certify a full minimum or NAMD numerical stability.
- E4 every incremental MM-QM error<=0.25kcal/mol: FAIL. At-4degrees A-0.262579,
  B-0.250669kcal/mol; other six displacements pass. These are diagnostic screens.
- E5 curvature agreement<=max(20% of QM,5kcal/mol/rad^2): FAIL overall, A fails
  at both steps; B passes. At2degrees A QM85.6183/MM52.0752 (39.18%softer MM),
  B QM60.1901/MM53.7671 (10.67%softer MM). Units kcal/mol/rad^2.

At2degrees slopes QM/MM: A-1.73462/+0.84714, B-3.34072/+0.02270kcal/mol/rad.
These are unrelaxed path slopes, not equilibrium conformational preferences.
Registered E1/E2 gates fail; no fully qualified local-agreement claim or parameter
range follows. Descriptive stiffness mismatch flags background A's exocyclic
response, conditional on its free-OH/contact geometry. Does not uniquely assign
error to a torsion term or establish DNA materiality. Neutral49atom free-OH/N1-methyl
chemistry only; both backgrounds and+/-4degree neighborhood. No population sampling.
Close finite panel; no automatic additional scan or numerical retry. Any follow-up
must distinguish exocyclic versus OH/contact response with independent precision
qualification. No NAMD stability, DNA practical equivalence, or model-freeze claim.
Audit: `docs/audits/cpd_directional_energy_20261017.json`.
Archive handoff: `cpd-cis-anti-i-bounded-sensitivity-v1/directional-energy-v1/closeout_handoff.json`.

Earlier active-state entries below are retained history, superseded above.

**Selected directional-energy test active — 2026-10-17.**
User explicitly authorized a few directional energy differences with predictions
registered before acquisition. Ten sequential frozen-core DF-MP2/def2-TZVP energies:
neutral canonical free-OH one-sugar/N1-methyl backgrounds A and B, each at exocyclic
O5'-C5'-C4'-C3' offsets0,+/-2,+/-4degrees. Centers are the previously audited
locally MM-relaxed geometries; no new optimization. All other internal coordinates
fixed by rigid graph-defined branch rotation. Both starts and all displaced
structures pass canonical identity, fixed-background and bond-preservation checks.
Analytic MM path slopes agree with small finite differences within1e-4kcal/mol/rad.
Maximum preflight atomic force40.272kcal/mol/A. Chemistry/contact limitations remain.

Predictions frozen in `directional-energy-v1/expectations.json` before new coordinate
energies: E1 center reproduction<=1e-5kcal/mol; E2 2/4degree derivative consistency
within max(10%,0.2kcal/mol/rad for slope or2kcal/mol/rad^2 for curvature); E3 positive
QM/MM directional curvatures; E4 every incremental MM-QM error<=0.25kcal/mol;
E5 curvature error<=max(20% of QM,5kcal/mol/rad^2). E4/E5 are explicitly diagnostic
screens, not DNA practical-equivalence tolerances. All points are exposed diagnostic
data, not independent holdouts for any future fit. No calibrated uncertainty claim.

Budget:10native calls maximum,600s/call,6600s service cap,4CPUs,12GiB/no swap;
charges against existing48h ceiling. One native job at a time. Completion/failure/
deadline watcher armed; no polling, cloud, automatic extension, fit or MD.
Archive-only outputs/scratch. Next: independently audit returned coordinates/native
energies and compare each expectation, including failures. Worker and sources pinned.
Handoff: `cpd-cis-anti-i-bounded-sensitivity-v1/directional-energy-v1/current_handoff.json`.

Earlier active-state entries below are retained history, superseded above.

**Bounded sensitivity admission closed inconclusive — 2026-10-17.**
Stage 0 registered and audited. Both canonical 49-atom endpoint conformations pass
fresh CPD/sugar identity checks; mapped cross-bonds are C5(1)-C6(2), C6(1)-C5(2).
Pinned baseline XML, candidate terms, native export and reference evidence remain
isolated. These free-OH one-sugar/N1-methyl fragments are not canonical two-sugar
DNA qualification fixtures. Historical bad-sugar DNA trajectories remain excluded.

Parameter-family gate failed: frozen exocyclic trial worsens holdout RMSE
6.24163 -> 6.63947 kcal/mol; six-point background/OH/contact confounding does not
supply a defensible local uncertainty interval. No +/-8 kcal/mol correction and no
artificial bias substituted for a transferable parameter family. Stop under the
plan's indefensible-range rule. Full MD registration (tolerances, DNA selections,
windows and measured-throughput job allocation) remains incomplete; no variant
force/curvature panel, native preflight or MD admitted. Zero native jobs/hours;
48-hour ceiling unused. No stability, equivalence, population or freeze claim.

Next discriminating evidence: controlled local directional-force/curvature reference
with explicit OH/phosphate chemistry and independent holdouts sufficient to justify
a transferable variant range, followed by canonical two-sugar DNA fixture admission.
No automatic QM sweep or continuation. User retains system-specific melting studies.
Audit: `docs/audits/cpd_bounded_sensitivity_admission_20261017.json`.
Archive: `cpd-cis-anti-i-bounded-sensitivity-v1/registration.json` and `closeout.json`.
Historical evidence and all production parameters/geometry preserved.

Earlier active-state entries below are retained history, superseded above.

**Next-work priority: bounded parameter sensitivity — 2026-10-17.**
The user requested a written plan and fresh-session launch prompt to determine
whether the unresolved sugar/exocyclic discrepancy matters for NAMD stability and
local DNA behavior. See [bounded sensitivity plan](cpd_bounded_parameter_sensitivity_plan.md)
and [launch prompt](cpd_bounded_sensitivity_session_prompt.txt).
This supersedes the proposed matched-QM-reference work below as the next priority;
the six-point results and archived closeout remain unchanged. Planning only: no
new calculation launched, no parameters promoted. Numerical qualification,
practical equivalence and insufficient sampling have separate outcomes. Further
QM refinement should target demonstrated sensitivity, not proceed indefinitely.
System-specific melting studies remain user-owned.

**Six-point panel audited and closed; matched QM-reference design next — 2026-10-17 14:32 Denver.**
Acknowledged `8cb8d6b0-cacb-4e26-8081-790d734389ac`. Two midpoint energies completed
in367.57s. Independent source/native MP2 energies, returned geometries, canonical
identity and recalculated MM audit passed. Midpoint background contrast QM-18.60992,
MM-26.27041,residual-7.66049kcal/mol. This is not resolution of main discrepancy.

Midpoint above endpoint chord: backgroundA QM21.47171/MM20.13991,error-1.33181;
backgroundB QM4.34960/MM1.02988,error-3.31972kcal/mol. These are three-point chord
deviations, NOT transition-state barriers or fitted derivatives. Six-point descriptor
audit shows OH5 torsions varying substantially, OH3 differing across backgrounds,
and O5-baseO4 distances2.47–4.14A. MidpointA has O5-O4=2.475A/HO5-O4=1.660A;
midpointB2.909/1.999A. These contact/cap differences accompany coupled geometry;
no unique attribution to sugar pucker, torsion or LJ is possible from this panel.

Close bounded six-point MM-selected geometry diagnostic with failures preserved.
No new job/timer and no scalar/2D fit. Next needs matched QM-constrained local
references, with explicit cap/OH branch controls and corresponding MM constraints,
rather than further vertical energies on MM-selected points. geomeTRIC is a
candidate independent optimizer; not yet installed/validated/admitted. Review
historical optimizer failures and analytic-gradient support before a bounded pilot;
no automatic repeated12-step continuations or full scan. Do not replace the
reference method silently or claim QM-relaxed/global minima from completed jobs.
Original neutral endpoint mismatch remains unresolved; production parameters unchanged.
Archive-only evidence,no polling/cloud spending.
Handoff: `endpoint-ring-exocyclic-midpoint-v1/closeout_handoff.json`.
Audit: `docs/audits/cpd_ring_exocyclic_panel_closeout_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Crossed diagnostic audited; two midpoint tests active — 2026-10-17 14:25 Denver.**
Acknowledged `e6da73ce-14a7-4b74-9ac6-465f27e9d068`. Crossed QM energies completed
in373.57s. Independent source/native energy, returned geometry, canonical identity
and recalculated MM audit passed; conditional contrasts recomputed directly from
Hartree differences. Fixed-exocyclic background residuals-6.75458/-4.59057kcal/mol;
fixed-background exocyclic residuals-3.55127/-1.38726. Coupling double difference
QM-10.11637,MM-7.95236,error+2.16401. Diagonal residual remains-8.14185.
An exocyclic-angle-only correction cannot eliminate residual at fixed angle.
This does NOT isolate pure sugar pucker: background includes other atoms, and
MM-selected branch/cap basins can contribute. No parameter fit or minimum claim.

Launched `endpoint-ring-exocyclic-midpoint-v1`: exactly two111.058096deg midpoint
orientations, one on each existing fixed background. Same independent SLSQP setup,
exact torsion and covalent bounds, then unchanged fixed MP2/def2-TZVP energy method.
Both pass independent fixed-atom/bond/torsion/projected-force preflight; inactive
bond inequalities,projected forces1.74e-5/5.81e-5kcal/mol/A. No fitted correction.
Compare midpoint energies with endpoint chords and conditional background residual;
inspect cap/contact changes before attributing curvature. These two points complete
a bounded six-point diagnostic, not a full surface or license to fit arbitrary2D
terms. Close panel for target/method decision after audit;no automatic extra sweep.
60min/energy,125min service cap,four CPUs,12GiB/no swap;completion/failure/deadline
watcher armed. Archive-only output/scratch,no periodic polling/cloud spending.
Historical failures retained; no production changes.
Handoff: `endpoint-ring-exocyclic-midpoint-v1/handoff.json`.
Audit: `docs/audits/cpd_ring_exocyclic_cross_review_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Crossed background/exocyclic tests active — 2026-10-17 14:17 Denver.**
User authorized next discriminating tests. Build two missing cells of a2x2 panel:
original fixed endpoint background with alternate exocyclic orientation, and vice
versa. Reuse audited relaxed diagonal QM/MM energies. Background includes ring
pucker AND other fixed-atom differences; do not interpret contrast as pure ring
energy. New conditional contrasts/double difference diagnose coupled residuals;
not another attempt to repair main mismatch by repeating local relaxation.

V1 Cartesian0.5A displacement box hit its limit on first crossed point, despite
optimizer success; projected force8.58kcal/mol/A. Rejected before QM; file preserved.
V2 replaces that local displacement box with covalent lengths90–110percent of input,
keeping exact torsion/fixed-atom/stereochemistry and low-force gates. Both inequalities
are inactive at accepted geometries. Independent recomputation verifies fixed atoms,
torsions and projected gradients1.42e-5/2.35e-5kcal/mol/A. Actual bond ratios range
0.985–1.017. Cartesian components move up to1.52/1.06A after large orientation swap;
this is recorded, not concealed as a small perturbation. No global minimum claim.
Existing diagonal displacements were inactive; references remain local MM-selected
geometries. Cap/branch basins and selection bias limit interpretation of coupling.

Launched `endpoint-ring-exocyclic-cross-v2`: two sequential frozen-core DF-MP2/
def2-TZVP energies with unchanged proven energy method.60min each,125min service
cap,four CPUs,12GiB/no swap;completion/failure/deadline watcher armed. Audit native
energies,identity,fixed atoms and recomputed contrasts before any fit or further
panel. No production geometry/parameter change. Archive-only bulk/scratch,no
periodic polling/cloud spending. Earlier failed fits and relaxation routes retained.
Handoff: `endpoint-ring-exocyclic-cross-v2/handoff.json`.
Audit: `docs/audits/cpd_ring_exocyclic_cross_admission_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Local-contact route closed: main discrepancy persists — 2026-10-17 13:48 Denver.**
Acknowledged `da04f2a9-96aa-4735-812c-e244b492be60`. Alternate fixed QM energy
completed in185.04s. Independent native energy/source hashes, returned coordinates,
canonical identity, fixed-ring/core atoms, torsion and recalculated MM audit passed.
Relaxed alternate-minus-original:QM-1.78519,MM-9.92703,residual-8.14185kcal/mol.
Prior residual-7.73658: absolute error WORSE by0.40527. This diagnostic did not
solve the conformer mismatch. Preserve all relaxed and rigid failures; no refit.

Enforce planned stop on local exocyclic-relaxation route; no new native job/timer.
The crowded holdout improved but the main endpoint discrepancy did not. Do not
infer a solution from optimizer success or from the smaller holdout error.
Computed existing-geometry descriptor panel: chi equal105.65946deg, whereas five
ring torsions and exocyclic orientation differ markedly. Local relaxation preserved
all five ring torsions exactly. Relaxed MM difference partitions into torsion-4.024,
nonbonded-4.255,angle-1.732kcal/mol plus small terms. This is not a QM decomposition
and cannot uniquely assign the mismatch to one parameter group.

Next investigation must distinguish coupled ring/exocyclic effects via a small,
matched constrained panel or directional-force evidence, using an independent
constraint optimizer if needed. Review against prior endpoint optimization failures
before launch. No more basis/cap/local-contact sweeps or single-torsion fitting.
The original full CPD readiness task remains incomplete; parameter discrepancy and
chemical-transfer qualifications remain. No production changes/minimum claim.
Archive evidence and failures retained; no polling/cloud spending.
Handoff: `endpoint-contact-relax-alternate-v1/closeout_handoff.json`.
Audit: `docs/audits/cpd_contact_relax_closeout_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Contact relaxation partly improves holdout; direct conformer test active — 2026-10-17 13:43 Denver.**
Acknowledged `708ffb22-1cee-4641-9021-e3b76f0d596c`. Two QM energies completed
in369.68s. Independent audit verifies source/native energies, returned geometries,
canonical identity, fixed atoms, torsion constraints and recalculated MM energies.
First reviewer regex incorrectly matched SCS Total Energy; failure recorded and
reviewer v2 anchors the unscaled Total Energy line. Native results unchanged.

Relaxed holdout increment:QM11.74713,MM7.36790,error-4.37923kcal/mol. Prior rigid
error+12.17178. Absolute discrepancy decreased but reversed sign: partial progress,
not a solved torsion/contact model. MM-selected geometries are biased and not QM
stationary points. Preserve both rigid and relaxed evidence; no parameter refit.

Apply identical independent SLSQP local branch relaxation to canonical alternate
endpoint:20 iterations, exact torsion equality, fixed core/ring, canonical identity
preserved;max displacement component0.093A,projected gradient7.17e-5kcal/mol/A.
Launched `endpoint-contact-relax-alternate-v1`: ONE new fixed MP2/def2-TZVP energy,
reusing audited relaxed-original energy to directly test main7.74kcal/mol conformer
residual. Frozen worker computes this contrast explicitly, not generic basis-check
interpretation. If no improvement, stop/review this local-relaxation route rather
than extend a sweep. No production parameters/geometry changed, no minimum claim.
60min native/65min service cap,four CPUs,12GiB/no swap;completion/failure/deadline
watcher armed. Archive-only bulk/scratch,no periodic polling,no cloud spending.
Handoff: `endpoint-contact-relax-alternate-v1/handoff.json`.
Audit: `docs/audits/cpd_contact_relax_review_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Sugar/contact discrepancy: new constrained-relaxation diagnostic active — 2026-10-17 13:35 Denver.**
User requests resolution without repeating failed methods; pursue alternative solvers
where useful. Review confirms failed single-torsion fit, surviving cap-cross error
and crowded rigid holdout. PySCF DF-MP2 analytic gradients are NotImplemented;
conventional MP2 gradient memory not admitted. Do not substitute HF gradients and
call them MP2. Independent SLSQP chosen for cheap, localized MM relaxation with
analytic OpenMM Reference gradient, instead of retrying long whole-endpoint QM
optimization or fitting the rejected torsion correction.

Two isolated geometries: original and its existing minus30 holdout. Freeze core
and sugar ring, hold O5-C5-C4-C3 torsion exactly; relax only graph-defined five-atom
C5/O5/HO5/H5/H5 branch. SLSQP500iteration limit,0.5A component displacement bounds;
both converged without active displacement bounds, projected gradient<1e-3
kcal/mol/A, torsion error<1e-6deg, canonical identity preserved. Crowded O5-O4
contact improves2.194->2.511A. All failed rigid holdout evidence retained.
These are MM-selected local geometries, not QM minima or unbiased fit targets.

Launched `endpoint-contact-relax-v1`: two fixed-geometry frozen-core DF-MP2/
def2-TZVP energies using previously validated Psi4 method. The changed optimizer
addresses geometry selection; reusing the energy evaluator keeps comparison with
prior rigid energies meaningful. Frozen runtime worker explicitly computes the
relaxed holdout increment and matching MM residual; it overrides the generic
basis-check worker's original conformer interpretation. Source preparation script
constructs geometry/plan; preserve frozen worker as exact executed artifact.
Audit relaxed-versus-rigid residual before choosing any further constrained QM
optimization, geomeTRIC trial or coupled fit. Never infer unique LJ error from
MM decomposition alone. No production geometry or parameter changes.
60min per energy,125min service cap,four CPUs,12GiB/no swap. Archive-only bulk/
scratch;completion/failure/deadline triggers,no periodic polling,no cloud spend.
Handoff: `endpoint-contact-relax-v1/handoff.json`.
Audit: `docs/audits/cpd_contact_relax_admission_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Future-workflow preference — 2026-10-17:** user requests independent solver first. Start analogous charged CPD solvent-reference work with tested PySCF IEF-PCM, retaining explicit cavity, numerical and memory gates. See `memory/feedback_cpd_qm_solver_choice.md`. This does not replace proven gas-phase QM methods or imply universal solvent validation.

**Independent solver paired screen passed; numerical pilot closed — 2026-10-17 02:43 Denver.**
Acknowledged `363283e9-cef2-4479-89cb-65908b4c1c58`. Original350 converged in
2732.52s (45.54min),29 cycles plus extra cycle; total-1963.9735539925232Eh,
solvent-0.151033471721709Eh. Independent source/native/checkpoint/density/restart/
geometry/settings audit passed;250-electron trace, gap0.48124Eh, gradient5.89e-10.
Original350-minus302=-0.031503kcal/mol;alternate shift=-0.021071. Paired
alternate-minus-original is-0.047194 at302 and-0.036762 at350: relative sensitivity
0.010432kcal/mol PASSES predeclared0.2 screen. Individual0.5 screens also pass.
Verified matched charge/elements/basis/auxbasis/cavity/epsilon across paired jobs.

This completes planned independent numerical pilot (five SCFs,3.87h total native
time). No further job or timer launched.302/350 near-degeneracy is only for fixed
charged terminal HF proxies; no solution populations, weld occupancy, thermal
stability, chemical-transfer validation or minimum certificate. Original434 is
supporting evidence only;alternate434/590 memory exclusions retained. No claim of
asymptotic grid convergence. Original neutral MP2/MM discrepancy remains unresolved.

Continued with no-QM target reconciliation: consolidated existing core-round1 cap
crosses, all four rigid holdouts and paired solvent results into provenance-linked
JSON/CSV. No missing solvent MM residual invented. Heavy-geometry discrepancy
persists at fixed caps; rejected torsion trial remains rejected. Crowded holdout's
MM response is LJ-dominated, but no QM decomposition uniquely assigns its error.
Next attach exact method/basis and sugar/contact descriptors to the existing neutral
panel before selecting new constrained-relaxed tests. Do not repeat cap/basis scans
or fit rigid contact repulsion into torsions. Production parameters unchanged.
Archive evidence/failures retained; no polling/cloud spend.
Handoff: `independent-pcm-pair-closeout-v1/handoff.json`.
Audits: `docs/audits/cpd_independent_pcm_pair_closeout_20261017.json` and
`docs/audits/cpd_target_reconciliation_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Alternate350 screen passes; final paired original350 active — 2026-10-17 01:56 Denver.**
Acknowledged `121ce2f5-baf3-4616-a18b-cd30707f2875`. Alternate350 converged in
2422.56s (40.38min),33 cycles plus extra cycle. Total-1963.973612577216Eh,
solvent-0.156033357893613Eh. Independent native/checkpoint/density/restart/geometry
and settings audit passed;250-electron trace, gap0.48198Eh, final gradient6.18e-10.
Alternate350-minus302=-0.021071kcal/mol PASSES0.5 engineering screen. No minimum
certificate, physical validation or reliable conformer preference inferred.

Launched `endpoint-pyscf-pcm-original350-v1`, last planned calculation in paired
302/350 check, from audited original302 density. Same basis,auxiliary basis,
geometry,charge,UFF1.1/epsilon and SWIG settings;only surface order31/350 changes.
Original350 conservative estimate6.074GiB admitted under unchanged8GiB working
screen. Four CPUs,12GiB/no swap,65-minute hard cap;60-minute review and completion/
failure watcher armed. All bulk/scratch Archive-only;no periodic polling/cloud.
After completion audit compute both conformer shifts and paired relative change
against0.2kcal/mol. Original434 supports original-only sensitivity;alternate434
remains excluded for memory. Close this paired diagnostic with its limitations,
not automatic grid escalation or fitting. Near-degenerate302 comparison remains
unranked until paired test; original neutral MP2/MM mismatch remains unresolved.
Handoff: `endpoint-pyscf-pcm-original350-v1/handoff.json`.
Audit: `docs/audits/cpd_independent_pcm_alternate350_review_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Alternate302 audited; alternate350 active — 2026-10-17 01:15 Denver.**
Acknowledged `d811343f-f0c1-43d2-9449-4e122a7d4a4f`. Alternate302 converged in
3043.95s (50.73min),43 cycles plus extra cycle; total-1963.9735789985798Eh,
solvent-0.155995583047468Eh. Independent source/native/checkpoint/density/geometry
and cavity audit passed. Electron trace250, orbital orthonormality verified;
final native gradient6.35e-10, gap0.48202Eh.

At matched302 resolution, alternate-minus-original=-0.047194kcal/mol. This is
near-degeneracy of these fixed proxy geometries, NOT reliable conformer preference,
solution populations or evidence that the neutral MP2/MM discrepancy is resolved.
Paired numerical sensitivity remains pending; cap preparation and chemistry
limitations remain in force. No fitting, optimization or minimum certification.

Launched `endpoint-pyscf-pcm-alternate350-v1`: alternate350 (order31), same basis,
auxiliary basis,charge,UFF1.1 cavity and epsilon, from pinned same-engine302 density.
Memory preflight6.359GiB within unchanged8GiB working screen;alternate434 excluded.
After native/restart audit and individual0.5kcal/mol screen, run original350 one at
a time to assess paired relative-energy sensitivity against0.2kcal/mol. A pass
would be a limited resolution check, not proof of asymptotic grid convergence.
65-minute cap, four CPUs,12GiB/no swap;60-minute review and completion/failure
watcher armed. Archive-only bulk/scratch, no periodic polling or cloud spend.
Handoff: `endpoint-pyscf-pcm-alternate350-v1/handoff.json`.
Audit: `docs/audits/cpd_independent_pcm_alternate_review_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Independent PCM original surface screen passes; alternate302 active — 2026-10-17 00:24 Denver.**
Acknowledged `a320a61a-b39f-42ef-b05d-2e7955240f48`. PySCF434 converged in
2882.32s (48.04min),34 cycles plus extra cycle; total-1963.9736363441589Eh,
solvent-0.151136651108997Eh. Native/checkpoint/density/restart/geometry audit passed.
Final gradient6.4e-10,250-electron trace, gap0.48123Eh. Original434-minus302 total
energy shift -0.083179kcal/mol PASSES existing0.5 engineering screen. This is local
numerical evidence, not a complete grid limit, physical validation or minimum.

Alternate preflight:302 retains5352 points,5.415GiB conservative estimate admitted;
434 retains7247,8.261GiB FAILS unchanged8GiB working screen.350 retains6047,
6.359GiB admitted. Preserve failed admission; no memory limits raised. Planned
relative-energy comparison becomes paired302/350, with original434 providing
additional evidence only for original conformer. This narrower comparison cannot
be represented as alternate434 validation or proof of asymptotic convergence.

Launched `endpoint-pyscf-pcm-alternate-v1`: alternate canonical charged-terminal
proxy, independent MINAO guess, matched original302 HF/basis/auxbasis/UFF1.1/
epsilon/IEF-PCM settings. After audit, evaluate alternate350 and original350 one
at a time; predeclared relative numerical sensitivity0.2kcal/mol. Preserve the
independently prepared cap-conformer limitations; these are diagnostic proxy
energies, not neutral MP2/MM fit residuals. No production parameter changes.
65-minute hard cap, four CPUs,12GiB/no swap;60-minute review and completion/failure
watcher armed. Archive-only bulk/scratch, no periodic polling or cloud spend.
Handoff: `endpoint-pyscf-pcm-alternate-v1/handoff.json`.
Audit: `docs/audits/cpd_independent_pcm_grid_review_20261017.json`.

Earlier active-state entries below are retained history, superseded above.

**Independent PCM SCF audited;434 surface refinement active — 2026-10-16 23:35 Denver.**
Acknowledged `1aa3e0db-7df5-4f0a-b07f-331bc706acb7`. PySCF302 SCF converged in
2854.03s (47.57min),45 cycles plus final extra cycle. Total energy
-1963.9735037900928Eh, solvent energy-0.150963220628633Eh. Independent audit verifies
native convergence, source/output hashes, saved checkpoint/density consistency,
250-electron trace, orbital orthonormality, unchanged geometry and explicit cavity
settings. Final native gradient6.18e-10; HOMO–LUMO gap0.48127Eh. This is SCF
feasibility, not minimum certification or numerical/parameter qualification.

Surface-only resource preflight:350 retains5846 points, conservative6.074GiB;
434 retains7023,7.880GiB. Both meet unchanged8GiB working screen. Selected434 as
stronger admitted refinement;590 remains excluded at12.070GiB estimated. No
memory limit raised or failed preflight discarded.
Launched `endpoint-pyscf-pcm-grid-v1`: same geometry/charge/basis/auxiliary basis,
UFF1.1 cavity,epsilon78.3553,IEF-PCM/SWIG; surface434 (Lebedev order35). Starts from
pinned audited same-engine302 density; no cross-engine AO mapping. Preserve exact
1e-9 convergence settings and0.5kcal/mol same-model numerical screen. Failure
stops blind grid refinement; pass still requires relative-conformer sensitivity.
Four CPUs,12GiB/no swap,65-minute hard cap,60-minute review/completion/failure
triggers armed. All outputs/scratch Archive-only; no polling or cloud spending.
Sugar/conformer work stays deferred per user priority. Historical failures retained.
Handoff: `endpoint-pyscf-pcm-grid-v1/handoff.json`.
Audit: `docs/audits/cpd_independent_pcm_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**User-prioritized independent solver pilot active — 2026-10-16 22:46 Denver.**
User explicitly requested independent solver before sugar/conformer reconciliation.
Installed PySCF2.14.0 and missing h5py into isolated Archive target; existing QM
runtime unchanged. Initial missing-h5py test failure preserved. Exact upstream
IEF-PCM reference test passes (energy error1.28e-13Eh), source/version pinned.

Target preflight: unchanged56 atoms,-1 charge,250 electrons,866 AO basis functions;
coordinate roundtrip below1e-15A. Explicit UFF1.1 radii in Bohr and water epsilon
78.3553. SWIG surface302 retains5201 points, conservative16-matrix-plus2GiB estimate
5.225GiB, passes8GiB working screen. Surface590 retains9191 points and estimates
12.070GiB, fails screen: NOT launched or treated as optional evidence to discard.

Launched `endpoint-pyscf-pcm-v1`: one independent DF-RHF/def2-SVPD IEF-PCM SCF,
SWIG302, def2-universal-jkfit auxiliary basis, independent MINAO guess (no unverified
Psi4 AO matrix import). Energy and orbital-gradient criteria1e-9,150-cycle maximum.
PySCF orbital-gradient criterion is not identical to Psi4 density RMS criterion.
SCF checkpoint and DF scratch are on Archive. Verified native startup settings.
Four CPUs,12GiB/no swap,65-minute hard cap;60-minute review trigger and completion/
failure watcher armed. No periodic polling, no cloud spending. Native completion
still requires independent audit and a resource-safe surface-refinement check.
Default cavity radii were explicitly overridden; cross-engine energies remain
numerical diagnostics, not directly interchangeable fit targets or minima.
Handoff: `endpoint-pyscf-pcm-v1/handoff.json`.
Audit: `docs/audits/cpd_independent_pcm_admission_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Methodological review complete — 2026-10-16 Denver.**
Review: `docs/audits/cpd_methodological_review_20261016.md`.
Keep failed DDX/PCMSolver retry routes closed. Priority returns to the original
matched intramolecular QM–MM discrepancy: reconcile existing canonical endpoint,
cap-cross and holdout data before selecting new computations. Charged-proxy HF/PCM
energies cannot repair or be directly compared as fit residuals to neutral MP2/MM
endpoints. The rejected exocyclic correction stays rejected; failed contacts remain.

Independent PySCF Gaussian-surface IEF-PCM is a conditional solvent cross-check,
not a readiness requirement or guaranteed cure. Runtime is absent from active QM
Python; dense surface matrices require explicit memory preflight before SCF.
No new simulation, runtime installation, timer or parameter change in this review.
Literature supports matched QM surfaces, water targets and separate transfer
validation. Escaped-charge effects remain a hypothesis, not our established cause.
Review records bounded pilot limits, numerical screens and stop criteria.
Handoff: `methodological-review-v1/handoff.json`.

Earlier active-state entries below are retained history, superseded above.

**DDX numerical-refinement route closed; methodological handoff — 2026-10-16 21:42 Denver.**
Acknowledged `9e8db4c1-b184-44a2-824e-6a5dea79e8c1`. Two direct fixed-density
solvent evaluations completed in98.03s. Independent audit verifies native
FMM=False for both, exact grid/radii settings, source hashes, saved density,
finite symmetric potential matrices and recomputed orbital response.

Direct surface12-to14 energy shift is+1.28567kcal/mol; gap0.24408 ->0.00569Eh
and occupied-subspace loss3.75474 in one diagonalization. Direct-minus-FMM energy
differences are+0.000563/-0.020304kcal/mol at surfaces12/14. Acceleration affects
results but is not the sole cause of the persistent surface sensitivity. These
are fixed-density diagnostics, not optimized wavefunctions, physical excited-state
assignments, minima or parameter certificates. The 1.80kcal/mol self-consistent
grid-screen failure remains unresolved. All raw outputs and failures preserved.

As prospectively specified, STOP this charged-fragment DDX numerical-refinement
route. No new job or timer launched; do not continue SCF/grid/radius tuning or
use these solvent energies as fit targets. The overall CPD campaign remains
incomplete, with the original approximately7.74kcal/mol QM–MM discrepancy and
chemical-transfer qualification unresolved. Production parameters unchanged.

Next work requires methodological review before compute: assess an independent
continuum implementation and treatment of diffuse anionic density/cavity
integration, then define a bounded pilot on exactly the same canonical terminal
fragment with explicit numerical-convergence criteria. This is a candidate
investigation, not an asserted diagnosis or a selected/available new engine.
Preserve charge/geometry and do not tune chemistry to force QM–MM agreement.
No alternate-conformer matrix until numerical sensitivity is controlled. Historical
bad-sugar DNA context remains excluded; user owns system-specific melting studies.
Archive-only evidence; no polling or cloud spend.
Handoff: `endpoint-ddx-standard-direct-v1/closeout_handoff.json`.
Audit: `docs/audits/cpd_ddx_standard_direct_closeout_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Surface sensitivity persists; bounded direct-solver comparison active — 2026-10-16 21:39 Denver.**
Acknowledged `5202d0c4-96d0-43a1-9839-c6f08e5dbfda`. Five fixed-density
solvent evaluations completed in205.48s. Independent source/native/radii/settings,
saved-density and finite symmetric matrix audit passed; recomputed orbital gaps
and occupied-subspace responses match. Baseline solvent energy reproduces SCF
within4.23e-8Eh. These are fixed-density diagnostics, not new SCF or minima.

Relative to surface12/590,integration75x302: coarse surface shift+1.73812kcal/mol;
coarse integration+1.18231; higher integration110x434 -0.07685; higher surface14/770
+1.30654. Higher integration response remains small, but higher surface gap falls
0.24408 to0.00847Eh with occupied-subspace loss3.968 in one Fock diagonalization.
This is not proof of a converged unstable electronic state, but does NOT justify
another higher-grid SCF. The 1.80kcal/mol SCF grid-screen failure remains in force.

Launched `endpoint-ddx-standard-direct-v1`: only two fixed-density solvent
calculations at surfaces12/590 and14/770 with FMM disabled, unchanged integration,
cavity and saved density. Compare energies/potential matrices with accelerated
results. If surface sensitivity and orbital disruption reproduce, close this
numerical-refinement route for methodological review; no further blind grid,
cavity or SCF tuning. If acceleration is responsible, independently verify direct
numerical convergence before energy targets. Alternate-conformer work stays held.
15-minute hard cap, four CPUs,12GiB/no swap; event watcher armed. Archive-only
bulk/scratch, no polling or cloud spend. No production parameters or certification.
Original7.74kcal/mol QM–MM discrepancy remains unresolved.
Handoff: `endpoint-ddx-standard-direct-v1/handoff.json`.
Audit: `docs/audits/cpd_ddx_standard_density_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Same-cavity grid screen failed; fixed-density decomposition active — 2026-10-16 21:35 Denver.**
Acknowledged `0bc0d5e4-2b66-43cf-8f7f-0215042c2261`. Coarse SCF converged in
324.94 s, -1963.9743571556853 Eh. Independent native/restart/radii/geometry/density
and source-hash audit passed. Native surface9/302, integration35x110, solvent
tolerance1e-9 verified. Saved density has 250 electrons and orthonormal orbitals.
Coarse-minus-fine total energy is +1.801591 kcal/mol at identical geometry and
UFF1.1 cavity: FAILS the predeclared 0.5 kcal/mol engineering screen. Execution
completion is not numerical qualification. Neither result is a minimum certificate.
Do not reinterpret the screen after seeing the result or proceed to alternate
conformer energies yet. Failure and native outputs retained.

Launched `endpoint-ddx-standard-density-v1`: five solvent evaluations at the
saved converged fine density: baseline, coarse surface alone, coarse integration
alone, higher integration110x434, higher surface14/770. Standard UFF1.1 cavity
unchanged. Recompute solvent potentials and orbital response, reproduce baseline,
and audit numerical sensitivity before deciding whether another SCF is useful.
No automatic repeated refinement, no fit or production changes. This diagnostic
cannot by itself establish self-consistent energy accuracy or resolve the original
7.74 kcal/mol QM–MM discrepancy. User-owned melting studies remain out of scope.
15-minute hard cap, four CPUs,12 GiB/no swap; event completion/failure/deadline
watcher armed. All bulk/scratch on Archive; no periodic polling or cloud spending.
Handoff: `endpoint-ddx-standard-density-v1/handoff.json`.
Audit: `docs/audits/cpd_ddx_standard_grid_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Standard-cavity fine-grid SCF audited; same-model grid check active — 2026-10-16 21:29 Denver.**
Acknowledged `85dcee37-af88-4d0a-abd2-ab55f028f5bf`. Native SCF converged in
535.40 s (11 iterations), energy -1963.977228174095 Eh. Independent audit verifies
actual orbital READ/no projection, standard UFF1.1 radii, fine surface settings,
unchanged coordinates, source/output hashes, saved wavefunction and density,
250-electron trace and orbital orthonormality. No observed surface-matrix warning.
This establishes SCF feasibility, not a minimum, energy accuracy or a parameter fit.
The original 7.74 kcal/mol QM–MM interconformer discrepancy remains unresolved.

Launched `endpoint-ddx-standard-grid-v1`: one original-conformer coarse-grid SCF
from the audited fine wavefunction, with unchanged geometry, basis and UFF1.1
cavity. Compare only within this physical model. Prospectively screen absolute
coarse/fine energy shift at 0.5 kcal/mol before alternate-conformer work; this is
an engineering screen, not a universal accuracy criterion. A pass still requires
paired conformer sensitivity before interpreting relative energies. No radius sweep.
Native timeout 30 min; total hard cap 35 min; four CPUs, 12 GiB, no swap.
Admission passed; completion/failure/deadline watcher armed. Archive-only bulk and
scratch, no periodic polling, no cloud spending, no production parameter changes.
Handoff: `endpoint-ddx-standard-grid-v1/handoff.json`.
Audit: `docs/audits/cpd_ddx_standard_scf_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Standard-cavity frozen-density check audited; one SCF feasibility attempt active — 2026-10-16 21:17 Denver.**
Acknowledged `8fd3caff-6044-456f-a6fb-f010b46b33b5`. Two fixed-density evaluations
completed in59.55s. Independent audit verifies source/output hashes, saved density,
native radii exactly1.1xUFF, unchanged coordinates, surface9/12 settings and
recomputed orbital spectra from finite symmetric saved Fock matrices. Both solves
converged; no observed solver failure warning. No minimum or parameter certificate.

Standard cavity preserves positive gaps0.46485/0.23556Eh at surfaces9/12 and
occupied-subspace losses0.000383/0.000834, versus~3 for the unscaled fine surface.
Frozen-density solvent energy changes-0.43258kcal/mol between surfaces. This is
promising for avoiding the observed collapse but not complete numerical accuracy,
SCF stability, or agreement with experiment. It is a distinct physical cavity,
not a rescue/relabeling of prior unscaled energies.

Launched `endpoint-ddx-standard-scf-v1`: one original-conformer HF/def2-SVPD SCF
with standardUFF1.1, unchanged fine-grid and convergence criteria, and saved
orbitals as starting guess. Native READ/no-projection verification remains required;
save resulting wavefunction/density. Old unscaled energy is NOT an accuracy
baseline. On failure stop this solvent route for methodological review; no radius
sweep. On success assess within-model grid sensitivity before any energy targets.
No production parameters, fitting, melting simulations or cloud spending.
30min native/35min total cap,12GiB/no swap,four CPUs;admission passed,event-driven
completion/failure/deadline watcher armed. All bulk/scratch on Archive;no polling.
Handoff:`endpoint-ddx-standard-scf-v1/handoff.json`.
Audit:`docs/audits/cpd_ddx_standard_cavity_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Restart genuinely read but SCF unstable; standard-cavity static check active — 2026-10-16 21:15 Denver.**
Acknowledged `c3437568-2860-4fb6-a523-6d400194439f`. Native restart log confirms
orbital READ with no projection and no SAD fallback. Iteration0=-1963.99860008Eh
matches the frozen-density expectation; first update drops~11Eh, followed by
hundreds/thousands-Eh excursions and ADIIS failure after iteration3 (254.49s).
No converged fine-grid result, no minimum or accuracy certificate. All native
failure evidence preserved. Do not keep changing SCF iteration counts/DIIS blindly.

Cheap saved-matrix audit: C^TSC identity and coarse Fock/eigenvalue agreement
verified. Frozen surface-resolution change nearly collapses the gap0.45033 ->
0.00304Eh and gives occupied-subspace loss~3.02; combined~3.01. Integration-only
retains gap0.45150 and loss0.000066. These are fixed-density one-diagonalization
measurements, not new SCF energies. Surface change is the problematic component
at this density; analysis does not prove underlying physical versus numerical cause.

Current cavity used unscaledUFF1.0. Installed ddx data declares standardUFF scale1.1.
Launched `endpoint-ddx-standard-cavity-v1`: two fixed-density evaluations using
that declared standard cavity at surface9/302 and12/590; both use75x302 integration
and1e-10solver tolerance. No SCF or fitting. This changes the physical cavity and
must not be relabeled a numerical-only continuation or tuned to fix prior energies.
If instability persists, stop solvent refinement and review methodological scope;
no further radius sweep. Even stable spectra do not establish converged accuracy.

10min hard cap,12GiB/no swap,four CPUs;resource admission passed. Event-driven
completion/failure/deadline watcher armed. Archive-only bulk/scratch,no periodic
polling,cloud spending or production parameter changes.
Handoff:`endpoint-ddx-standard-cavity-v1/handoff.json`.
Audit:`docs/audits/cpd_ddx_restart_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Frozen-density audit passed; saved-orbital fine-grid attempt active — 2026-10-16 21:09 Denver.**
Acknowledged `478bd6c3-4de4-4e93-b18d-9ffffe91e49e`. Diagnostic completed
in529.44s. Independent audit verifies native coarse SCF convergence/energy,
source/result hashes, saved wavefunction density equality, electron count,
unchanged geometry, finite symmetric Fock matrices and recorded norms.
Coarse energy reproduced within~1.3e-11Eh. Baseline solvent recovery differs by
only2.81e-9Eh. Saved full density and wavefunction are retained for reuse.

At this frozen density, integration-only solvent shift=-0.87116kcal/mol,
surface-only=+0.35102,combined=-0.72725. All forward/adjoint solves converged in
33–44iterations; none reproduced the prior runaway. These are frozen-density
solvent shifts, NOT converged fine-minus-coarse total energies. They do not identify
one proven cause or certify fine-grid accuracy/global SCF stability. The changes
are large enough that the registered numerical-accuracy checks remain necessary.

Launched `endpoint-ddx-restart-v1`: exactly one original-conformer fine-grid SCF
from the audited coarse orbitals. Psi4's supported restart_file path installs
GUESS READ; native log must confirm actual orbital read with no projection and
no SAD fallback. Same fine grid, method, SCF and solvent convergence criteria as
failed run; no damping/iteration-limit change or relaxed gate. Save final density
and wavefunction. Compare to original0.5kcal/mol absolute-shift screen; alternate
and0.2relative screen remain outstanding. Stop for review on failure, no automatic
repeat. No minimum or parameter certification.

30min native/35min total hard cap,12GiB/no swap,four CPUs; admission passed.
Completion/failure/deadline triggers armed;Archive-only bulk/scratch,no polling,
production changes or cloud spending. Prior solver failures remain preserved.
Handoff:`endpoint-ddx-restart-v1/handoff.json`.
Audit:`docs/audits/cpd_ddx_density_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Fine-grid SCF failure audited; frozen-density isolation active — 2026-10-16 20:59 Denver.**
Acknowledged `bc19a558-13ad-452b-a9f8-90c9eff7de15`. First fine-grid conformer
failed after504.38s in ADIIS minimization, before a converged energy. Iterates
fell from~-1963 to-4847Eh by iteration9. No completed point/alternate calculation;
these iterates are not physical energies or evidence of a minimum. Native settings
show intendedlmax12/Lebedev590,solute75x302 and1e-10solvent tolerance. Raw outputs,
solver failure and scratch retained. No iteration-limit increase or blind retry.

A cheap fixed-CHARMM-point-charge solver test on the same original geometry passed:
coarse9/302=-0.1441303352Eh;fine12/590 FMM=-0.1443439887Eh;fine direct=-0.1443439344Eh.
Fine FMM/direct difference5.4295e-8Eh (~0.000034kcal/mol); forward solves41/44/44
iterations. This weakens a simple FMM-only explanation for that fixed charge input,
not proof that full electronic density or coupled SCF is stable. No parameter fit.

Launched `endpoint-ddx-density-diagnostic-v1`: reproduce one coarse-grid solution
within1e-8Eh, save wavefunction and full density, freeze that density for four
solvent-response evaluations: baseline, finer integration only, finer surface only,
and both changes. Verify baseline solvation recovery and exact unchanged density;
save solvent energies and Fock matrices. No fine-grid SCF. This isolates numerical
response before further expensive iterations and retains reusable restart evidence.
35min total hard limit,12GiB/no swap,four CPUs,Archive-only outputs/scratch.
Admission passed and completion/failure/deadline watcher armed; no polling/cloud.
Grid accuracy and prior energy discrepancy remain unresolved; no minimum certificate.
Handoff:`endpoint-ddx-density-diagnostic-v1/handoff.json`.
Audit:`docs/audits/cpd_ddx_grid_failure_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**DDX pilot independently audited; paired grid check active — 2026-10-16 20:49 Denver.**
Acknowledged `f5e37355-6128-4d87-b22b-16e6112e8310`. Both fixed56atom/-1e
singlet HF/def2-SVPD calculations completed in838.97s total. Independent audit
checks every source/result pin, native energy/solvation values, convergence, actual
UFF radii and geometry, dielectric78.3553,lmax9,Lebedev302,solute35x110 and1e-9
solvent tolerance. No observed solver failure warnings. Coordinate error<1e-10A.
Reviewer first compared Bohr-tabulated radii with native Angstrom radii; that
reviewer failure is preserved and the corrected review uses engine conversion.
No native result was changed.

Alternate-minus-original HF/PCM energy=-3.85791kcal/mol. This is for independently
prepared charged cap conformers at HF; it does NOT resolve or directly measure
the prior neutral-fragment MP2/MM discrepancy. No fit or minimum certification.

Launched `endpoint-ddx-grid-v1`: paired numerical sensitivity check with same
chemistry/method/basis/radii/coordinates and lmax12,Lebedev590,solute75x302,
solvent tolerance1e-10. Registered engineering screens: each absolute energy
shift<=0.5kcal/mol and relative difference shift<=0.2kcal/mol. Not universal
literature limits or proof of complete convergence. Report both shifts; failure
requires cost/necessity review, not automatic grid escalation. Passing supports
only this HF numerical setup; chemically matched correlated/MM-solvent targets
remain to be designed before any fitting.

30min/point,65min total hard cap,12GiB/no swap,four CPUs; admission passed.
Completion/failure/deadline triggers armed;Archive-only output/scratch,no polling,
cloud spending or production changes. PCMSolver failures remain rejected.
Handoff:`endpoint-ddx-grid-v1/handoff.json`.
Audit:`docs/audits/cpd_ddx_pilot_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**PCMSolver branch closed; reference-tested ddx pilot active — 2026-10-16 20:33 Denver.**
Acknowledged `4baf532a-3df8-4aaa-bff4-725fc1fb8541`. V2 SCF completed in412.72s,
energy-1963.9944991263894Eh,charge-1,singlet,866orbital functions. Independent
native audit verifies0.2A² cavity,convergence and8.882e-16A coordinate error.
The two non-positive-definite S-matrix warnings recurred; strict gate rejected
result and prevented alternate-conformer execution. Both PCMSolver energies remain
unaccepted. No more cavity-mesh retries. All outputs/failures preserved.

Installed pyddx1.0.0 only under Archive `cpd-ddx-runtime-v1/site-v3`, leaving
existing environment unchanged. Initial wheel probe unavailable; metadata missing
pybind11 and two import-incompatible builds retained. Explicit matching Python
3.12.14 headers/library and pybind11 2.13.6 resolved the build/API mismatch.
Upstream Psi4 tests reproduced: NH3 DF energy error1.209e-5Eh against1e-4 gate;
fluorochloromethane PCM error8.049e-11Eh against1e-8 gate. These validate tested
runtime functionality, not CPD accuracy. Test logs and package/source pins retained.
Reference:https://psicode.org/psi4manual/master/ddx.html

Launched `endpoint-ddx-pilot-v1`: same two fixed56atom/-1e conformers and
HF/def2-SVPD,DDX PCM water,UFF radius scaling1.0,lmax9,Lebedev302,solute35x110,
solvent-solver tolerance1e-9. Different cavity implementations are not assumed
identical. Native feasibility only; no fit, vacuum-MM comparison or acceptance
of prior PCMSolver results. Further grid sensitivity needed before energy targets.
15min/point,35min hard limit,12GiB/no swap,four CPUs; resource admission passed.
Completion/failure/deadline triggers armed; no periodic polling or cloud spend.
Handoff:`endpoint-ddx-pilot-v1/handoff.json`.
Audit:`docs/audits/cpd_pcm_branch_closeout_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**PCM pilotV1 failure audited; one finer-mesh retry active — 2026-10-16 20:23 Denver.**
Acknowledged `773f251d-48a1-48bb-b62f-a67a27921230`. Native original-conformer
DF-RHF converged in354s,charge-1,multiplicity1,866orbital/2913auxiliary functions,
IEFPCM water,area0.3A²,energy-1963.9948553785655Eh. No accepted point or alternate
conformer result. The wrapper failed its coordinate check: campaign conversion
0.529177210903 differs from Psi4's0.52917721067A/Bohr. Apparent4.183e-9A motion
is uniform conversion scaling; corrected residual1.776e-15A. This is a wrapper
unit bug, not molecular displacement. V2 uses the engine constant with unchanged
1e-10A acceptance, not a relaxed tolerance.

Separately, PCMSolver twice reported S matrix not positive-definite, commuted to
warning by its installed patch. Native completion does not make this result
acceptable. Raw output, coordinates, warning and failure retained. Issue reference:
https://github.com/PCMSolver/pcmsolver/issues/206 . No minimum or accuracy certificate.

Launched `endpoint-pcm-pilot-v2`: one finer cavity-area0.2A² attempt with all
geometry/method/basis/solvent fixed. Explicitly reject surface-matrix warnings;
second conformer runs only if first passes. Save raw result before warning gate.
If warning recurs, stop this PCMSolver branch rather than repeat mesh variations.
This remains HF/PCM numerical feasibility, not MP2 fitting or vacuum-MM comparison.
15min/point,35min total hard limit,12GiB/no swap,four CPUs; resource admission
passed. Completion/failure/deadline watcher armed; Archive-only bulk/scratch,
no periodic polling, cloud spend or production parameter changes.
Handoff:`endpoint-pcm-pilot-v2/handoff.json`.
Audit:`docs/audits/cpd_pcm_pilot_failure_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Mixed-site coordinate preflight passed; PCM pilot awaits one admission retry — 2026-10-16 Denver.**
Completed graph, valence/formal-charge, parent-coordinate identity, canonical CPD/
sugar identity and bond/contact screens for both original/alternate conformers
of all four reference classes. Parent coordinates stayed exact; only added cap
atoms relaxed. No full minimum certification. ETKDG constrained embeddings failed
for phosphate cases and remain archived. Direct internal-coordinate cap seeds
passed terminal checks; a bounded1500-step continuation of the least problematic
internal seed passed both internal cases. Other failed/clashing seeds are retained.

Mapping audit corrected generic P to DNA P2 per native DEOX/DEOS. Native methyl
caps lack CN9-ON2-P2 angle/UB entries; v2/v3 failures preserved. V4 explicitly
transfers only those missing methyl-cap angle/UB analogs from P; existing P2 sugar
parameters remain unchanged. This is a surrogate approximation, not native DNA
validation or a new fitted CPD model. Earlier statement that ON5/ON2 versions of
the tested exocyclic torsion differ is corrected: their four coefficients are
identical here; charges and adjacent phosphate terms differ. No user-design or
production parameters modified; failed frozen torsion trial remains excluded.

Prepared two56atom/-1e5′terminal fixed-coordinate DF-RHF/def2-SVPD IEFPCM-water
energies. UFF cavity, scalingfalse,area0.3; PCM package present. HF/diffuse-basis
pilot explicitly checks charged-reference numerical feasibility/cost, not MP2
accuracy, vacuum-MM agreement, free energies or melting. Independently selected
cap conformers are not paired fitting targets. No cross-chemistry absolute-energy
comparison. Continuum water does not represent specific ions or salt effects.
Reference:https://psicode.org/psi4manual/master/pcmsolver.html

Initial launch rejected before service creation:MemAvailable~17.6GiB below the
unchanged18GiB admission gate. One20minute systemd admission retry is armed,
`nadoc-endpoint-pcm-pilot-admit.timer`; no periodic retries. Runner checks pause,
current handoff, source hashes and duplicate launch. Failure sends a wake; success
arms native completion/failure/deadline watcher. Native budget15min/point,35min
total,12GiB/no swap,four CPUs,Archive-only outputs/scratch. No QM running yet.
No cloud spending. Handoff:`endpoint-pcm-pilot-v1/deferred_handoff.json`.
Audit:`docs/audits/cpd_mixed_chemistry_preflight_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Mixed internal/terminal scope confirmed; reference topology matrix prepared — 2026-10-16 Denver.**
User confirmed a mixture of internal and terminal weld sites. This resolves the
reference-chemistry question; do not ask it again or restrict coverage to one class.
Native topology distinguishes free5′OH ON5/C5′charge+0.05 from phosphate-linked
ON2/C5′charge-0.08. The failed OH trial must not be applied to internal sites.

Prepared isolated one-sugar/N1-methyl reference topologies on Archive: double-OH
control49atoms/0e;5′OH-terminal with3′methyl-phosphodiester56atoms/-1e;
3′OH-terminal with5′methyl-phosphodiester56atoms/-1e; internal two-phosphodiester
proxy63atoms/-2e. Native3POM/5POM patches supply phosphate chemistry. All four
pass exact PSF graph, corrected CPD crosslink, charge, and complete OpenMM
parameter-coverage checks without warnings. No fitted trial term is installed.
These are topology fixtures, not geometries, two-sugar validation or NAMD-ready
packages. Prior two-sugar62atom fixture has both3′/5′OH on both ends and cannot
substitute for internal or singly terminal chemistry qualification.

Next: isolated canonical coordinate/cap-conformer preparation with stereochemistry,
valence, contact and parameter mapping audits. Register electrostatic environment
for charged references before one bounded pilot; compare conformers within each
chemistry, never absolute energies across different atom counts/net charges.
Geometry-dependent gates and native QM are not yet run. No active job or polling;
all new artifacts on Archive, no cloud or production/user-design modification.
Frozen trial remains rejected and original energy discrepancy unresolved.
Handoff:`endpoint-chemistry-matrix-v1/handoff.json`.
Audit:`docs/audits/cpd_endpoint_chemistry_matrix_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Prospective holdouts reject torsion trial; reference chemistry needed — 2026-10-16 11:49 Denver.**
Acknowledged `c22ce499-fb91-4e5a-a918-e376ae5116f4`. All four native energies
completed in749.59s; independently verified convergence, method/basis/occupations,
exact rotations and returned coordinates, bond lengths, canonical identity and
fresh MM increments. Execution completion is separate from scientific acceptance.

Frozen local-only trial FAILED its registered screen. Corrected errors for original
-30/+30 and alternate-30/+30 are +13.06349,-0.13173,-1.26734,-2.01298kcal/mol.
Two exceed1.5kcal/mol; pooled RMSE worsens6.24163 ->6.63947. Preserve all four
holdouts, reject the trial without retuning or exporting it. Earlier1.06kcal/mol
interconformer agreement was exploratory and does not survive this broader screen.

Independent static MM decomposition of original-minus30 reproduces native force
groups: nonbonded+37.72861 (LJ+41.86573,Coulomb-4.13712),torsions-1.37216kcal/mol.
O5′–other-base O4 compresses2.83668 ->2.19436A; HO5′–O4 compresses1.93660 ->1.25595A.
This identifies a crowded fragment contact, not a unique QM error attribution or
permission to discard a holdout. Alternate-plus30 also fails, so excluding the
crowded point would not rescue the registered trial. No LJ/charge/torsion change.

Stop this capped-fragment fit branch instead of adding harmonics or more points
until it passes. User clarification requested on intended weld-site chemistry:
internal phosphate-connected nucleotides, terminal free OH, or mixed. That answer
selects a representative reference for a topology/stereochemistry and parameter-
mapping review before any further QM. No active calculation or periodic polling;
this is a scientific decision boundary, not a user-requested pause or readiness
certificate. Existing candidate remains scientifically provisional;7.74kcal/mol
original diagonal discrepancy unresolved. User owns system/melting simulations;
old invalid-sugar DNA context remains excluded. All failures/raw outputs retained
on Archive. No cloud spending.
Handoff:`endpoint-exocyclic-holdout-v1/review_handoff.json`.
Audit:`docs/audits/cpd_endpoint_exocyclic_holdout_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Exocyclic response audited; frozen trial tested on prospective holdouts — 2026-10-16 11:36 Denver.**
Acknowledged `b8f4d724-ee39-494a-a200-83ee830f3deb`. All four native
DF-MP2/def2-TZVP energies completed in746.16s. Independent review verifies native
convergence, energies, occupations/bases, exact requested rotations and returned
coordinates, preserved bond lengths/stereochemistry, and fresh MM increments.
Local MM increment errors range -1.21826 to +0.66437kcal/mol. Original local
QM/MM slopes are -4.28910/-3.55463kcal/mol/radian; alternate slopes are
+0.78190/+4.37746. These finite-difference responses are not minimum certificates.

Static exploratory identifiability check: adjusting only the n1 phase-pi
O5′–C5′–C4′–C3′ coefficient using four local increments gives delta-k=-5.21507
kcal/mol, local residual RMSE0.41776, and predicts interconformer error+1.05998
instead of-7.73658. The separate conformer contrast was already inspected, so this
is diagnostic support, not blind validation. The trial would reverse the existing
term preference (k2.5 -> -2.71507, equivalent phase reversal plus constant).
No XML, NAMD parameter, standard sugar term or production model was changed.

Launched `endpoint-exocyclic-holdout-v1`: four new +/-30degree geometries,
frozen trial coefficient, same native method; no retuning to holdouts. Registered
screen: every corrected local increment error <=1.5kcal/mol and pooled RMSE
lower than unchanged MM. This is an engineering screen, not a literature standard
or full force-field qualification. A pass requires further chemical/transfer review;
a failure is retained and cannot be hidden by dropping a point. Original-minus30
has maxMM gradient260.79kcal/mol/A (others38.23–40.52), within the predeclared500
severe-clash screen; retain that demanding case and inspect native evidence.

Four sequential energies,15min per point,65min total hard limit;12GiB/no swap,
four CPUs,Archive-only outputs/scratch. Resource admission passed and completion/
failure/deadline watcher armed. No periodic polling, MD, cloud spend or melting
study. Invalid archived DNA context remains excluded; user owns chosen systems.
Handoff:`endpoint-exocyclic-holdout-v1/handoff.json`.
Audit:`docs/audits/cpd_endpoint_exocyclic_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Cap comparison audited; local exocyclic response diagnostic active — 2026-10-16 11:22 Denver.**
Acknowledged `6f984521-aa66-44d9-86ce-bce2237aec47`. Both native frozen-core
DF-MP2/def2-TZVP energies converged in a combined 396.85 seconds. Independently
verified native energies, basis/occupation inventory, unchanged returned coordinates,
canonical stereochemistry, cap-only changes, preserved bond lengths, and fresh MM
energies for all four geometries. Fixed-cap heavy-conformer errors remain -9.28066
and -7.76627 kcal/mol; cap-only increment errors are +0.02969 and +1.54408.
Thus cap orientation does not explain away the discrepancy. This does not establish
phosphate/solvent transfer or uniquely assign the error to a force-field term.
Stop further basis/cap repeats. All failures and raw evidence retained.

Next diagnostic: four frozen-geometry energies at +/-15 degrees of
O5′–C5′–C4′–C3′ about each canonical conformer. This isolates the local response
of the coordinate with the largest individual MM torsion energy change; existing
boundary scans primarily address glycosidic rotation. All preflight stereochemistry
and bond-preservation gates pass; maximum MM gradients 38.43–40.42 kcal/mol/A.
Compare local increments/slopes/curvatures before attributing or fitting an error.
If increments agree while the conformer discrepancy persists, stop targeting this
coordinate. Any later fit requires broader registered training and untouched
holdouts; these diagnostic points cannot be claimed as independent validation.

Launched `endpoint-exocyclic-check-v1`: four sequential energies, 15 minutes each,
65-minute total hard limit, four CPUs, 12 GiB/no swap; admission checked memory,
Archive mount/free space and absence of another active campaign job. Completion,
failure and deadline triggers armed. Bulk/scratch on Archive; no periodic polling,
MD, melting campaign or cloud spend. User owns chosen-system simulations.
No optimization or minimum certificate; scientific qualification remains provisional.
Handoff: `endpoint-exocyclic-check-v1/handoff.json`.
Audit: `docs/audits/cpd_endpoint_cap_review_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Larger-basis comparison audited; cap-orientation diagnostic active — 2026-10-16 11:11 Denver.**
Acknowledged `abac3a7a-109a-4613-a332-4487b59fceea`. Both native DF-MP2 energies,
SCF convergence, frozen-core occupations27/101/74/868/868/0,969/2443/2382 basis
functions and exact canonical geometries independently verified. Actual JK algorithm
is Core; both calculations completed in391.18s. The reviewer's initial wording-only
assertion failure is retained; native convergence was present and the corrected
review uses its actual marker. EarlierV1 timeout/scratch remain untouched.

Alternate-minus-original QM energy is-2.14430kcal/mol versus-2.72472 with6-31G(d),
a+0.58042 shift. Unchanged MM gives-9.88087; discrepancy remains-7.73658kcal/mol.
No minimum/free-energy certificate; stop basis escalation rather than repeat it.

Launched `endpoint-cap-check-v1`: two crossed OH-cap orientations, changing ONLY
HO3′ andHO5′ on each of the two canonical fragment heavy geometries. Same larger-
basis method/options; reuse both audited diagonal energies for a four-point
conditional comparison. No fitting or claim that cap changes represent phosphate
or solvent. Chemistry and bond lengths preserved; candidate maxMM gradients39.52
and38.56kcal/mol/A pass the prospective severe-clash screen. Perpoint15min,
total35min,12GiB/no swap/four CPUs. Completion/failure/deadline triggers armed;
all output/scratch on Archive. User owns melting/system studies; no MD/cloud.
Current handoff:`endpoint-cap-check-v1/handoff.json`.
Audit:`docs/audits/cpd_endpoint_basis_review_20261016.json`.

Earlier active-state entries are retained history, superseded above.

**Basis-checkV1 timeout audited; revised energy-onlyV2 active — 2026-10-16 11:02 Denver.**
Acknowledged `80f1f06f-0025-439b-861c-2b266b5fca71`. V1 stopped at its3600s
first-point boundary during DF-RHF iteration19, before an MP2 energy existed.
Native log reports DiskDFJK with3072MiB allocation; scratch integral file6.4GiB.
No point/minimum certification. Failure and6.6GiB scratch preserved on Archive.

New `endpoint-basis-check-v2` retains the exact two canonical geometries,
frozen-core DF-MP2/def2-TZVP and auxiliary-basis inventory. Psi4 memory10GiB,
service12GiB/no swap/four CPUs after verifying>18GiB available. SCF E/D thresholds
are prospectively1e-10 for this energy-only diagnostic (V1 used1e-12). This does
not relax geometry/forcefield acceptance or certify gradients. V1 last iterations
show energy changes~1e-11Hartree; do not equate that with a completed energy.
Perpoint1h,total2h5m,completion/failure/deadline watcher armed. Inspect actual
algorithm/cost/convergence on completion rather than assume speedup. No MD/cloud.
Current handoff:`endpoint-basis-check-v2/handoff.json`.
Audit:`docs/audits/cpd_endpoint_basis_timeout_20261016.json`.

Earlier active-state entries below are retained history, superseded above.

**Pre-simulation refinement resumed; canonical-fragment basis check active — 2026-10-16 10:01 Denver.**
User clarified that they own melting studies and have specific systems in mind.
Focus here on tractable sugar/reference and energy discrepancies. Handoff readiness
will not require agent-run melting or extended system-specific MD; scientific
limits must remain explicit. Prior temperature/occupancy simulation plans are
superseded as agent-run work.

Source trace: the parent job151b6da69fe5 packaged PDB already has the same6 C3′
and2 C4′ mismatches across98residues. This is an archived DNA-context defect,
not evidence of incorrect canonical QM endpoint1 sugar. That context remains
excluded; no user design, historical output or production geometry changed.

Exact MM decomposition reproduces force-group energies: alternate-minus-original
Coulomb=-4.33710,LJ=-0.35067,torsions=-4.28153kcal/mol. Cap-hydrogen-involving
Coulomb contributions sum to-12.16293 and cancel other contributions; this is not
an independently additive physical error or a solvent correction. Largest individual
torsion contribution is O5′–C5′–C4′–C3′=-4.21690kcal/mol. Do not refit CPD core or
standard sugar terms from this decomposition alone.

Admitted `endpoint-basis-check-v1`: exactly two frozen canonical49atom conformer
DF-MP2/def2-TZVP energies, unchanged coordinates and frozen core,969orbital functions.
Compare their difference with MP2/6-31G(d) and unchanged candidate MM. No optimization,
fit, new DNA model or MD. Perpoint3600s;total7500s (2h5m),8GiB/no swap/four CPUs,
Archive-only output/scratch. Completion/failure/deadline watcher armed. Audit actual
native methods/bases/geometry/energies before interpreting basis sensitivity.
Audit: `docs/audits/cpd_pre_simulation_refinement_20261016.json`.

The following entries are history and superseded where scope or active state differs.

**Scientific hold: DNA sugar-reference mismatch discovered during authorized uncertainty work — 2026-10-16 Denver.**
User authorized a robust stabilization range with separate sampling, parameter and
weld-occupancy uncertainties. Prospective study: `docs/cpd_stabilization_uncertainty_plan.md`.
A rigid-chi fragment transfer failed preflight with severe nonbonded strain; no QM
launched. Actual DNA-frame extraction then failed the endpoint sugar-identity gate.
Independent ordered heavy-neighbor determinants confirm C3′ mismatches at both
sites and C4′ at endpoint2 in the initial welded/control seeds and all four final
trajectories. Both ideal and model coordinates of freshly archived PDB CCD DT
agree with the original/alternate QM endpoint1 reference, not the formation seeds.

Earlier audits remain true as seed-relative execution/integrity checks, but do NOT
qualify canonical DNA chemistry. All40ns retained as engineering history; exclude
from stabilization inference pending source correction. The7.15616kcal/mol fragment
discrepancy is not resolved, and prior sample-to-fragment relevance comparisons cannot
validate parameters in this context. No fit, new QM, new MD or cloud spend.
Current handoff: `sugar-stereo-reference-audit-v1/handoff.json`. Source-wide audit now complete:98DNA residues,6 C3′ and2 C4′ mismatches in
the precursor frame, source package PDB and equilibrated checkpoint. The issue
predates corrected CPD placement. Next: trace upstream construction and prepare
an isolated corrected-context A/B review; do not simply change expected signs. This scientific
hold is not a user pause and does not revoke authorization for corrective work.
Audit: `docs/audits/cpd_stabilization_sugar_reference_20261016.json`.

The following completion and readiness statements are historical, superseded above.

**Two matched10ns replica pairs audited; attachment-reference review completed — 2026-10-16 Denver.**
Acknowledged `61bfebae-29e2-43d8-ab79-17aa94151f89`. Control replica2 completed10ns
in8.23h. Ten native terminal/checkpoint chains,1000 pinned frame verdicts,
30 independently replayed frames and10 endpoints pass. All failures retained.

Endpoint whole-solute aligned RMSD: welded1/control1=7.125/13.386Å;
welded2/control2=11.396/9.827Å. Ordering reverses; RMSD is not a stability metric.
Initial cross-strand base-centroid contact proxy (141pairs,<8Å): final126/120
and119/116 respectively. This is exploratory geometry, not basepair or melting evidence.

Read-only analysis of120 prespecified frames across four runs records both
attachment chi and five sugar torsions. Explicit common-atom/sign mapping shows
both original/alternate QM endpoint1 conformers have chi105.65946degrees, whereas
all60 sampled welded endpoint1 configurations differ by at least71.58degrees.
No sampled frame matches either six-torsion reference within a descriptive20degree
screen. This does not rule out accessibility, validate parameters, or establish an
energy correction; terminal OH caps also differ from DNA phosphodiesters.

Decision: defer third replicas and broad temperature runs while preparing a small
sampled-geometry QM/MM relevance/energy-decomposition diagnostic. Do not refit a
torsion simply to cancel the7.15616kcal/mol difference. Native jobs are currently
idle; campaign is not user-paused. Current handoff is
`replica-attachment-qm-relevance-v1/handoff.json`; precise next work recorded there.
All analysis retained on Archive; no cloud or new dynamics. Qualification remains
provisional. Audit: `docs/audits/cpd_corrected_cis_anti_i_two_pairs_20261016.json`.

The following active-state statements are retained history, superseded above.

**Control replica2 preparation audited;10ns validation active — 2026-10-15 20:40 Denver.**
Wake `bf2e803d-595f-49b0-baf2-771ca2f12924` acknowledged. Preparation completed
1.15ns in3509.58s (58.49min). All27 native terminal logs/restart bundles and250
pinned frame verdicts verified;81 sampled frames and27 endpoints independently
replayed. Initial seed614032; subsequent coordinate/velocity/cell lineage intact.
No scientific gates changed; all historical failures retained.

Launched `formation-replica2-validation-control-v1` from its own575000-step
checkpoint:10ns in ten1ns audited segments, validation seed614532,15h hard cap,
8GiB/no swap/four CPUs,5400s native segment timeout and unchanged20% slowdown gate.
Expected8–10h; completion/failure/deadline triggers armed, no periodic polling.
All large output/scratch on Archive; no cloud spending. Current handoff points
to the new validation job. Next: audit all ten segments and compare both matched
replica pairs before deciding on a third pair. Provisional parameters and same-
geometry seed replicas do not establish equilibrium, minimum or production readiness.
Audit: `docs/audits/cpd_corrected_cis_anti_i_replica2_control_preparation_20261015.json`.

The following active-state statements are retained history, superseded above.

**Welded replica2 audited; matched control replica2 preparation active — 2026-10-15 19:40 Denver.**
Wake `1f62f294-c6ff-4672-9508-990d8273383d` acknowledged. Resumed6ns completed
in5.30h; combined with preserved segments1–4, replica2 has10ns validation and
11.15ns total. All ten native terminal logs/checkpoint hashes, restart continuity,
1000 pinned worker-frame verdicts,30 independently replayed frames and10 endpoints
pass. Endpoint density1.02207–1.02471g/mL; final heavy-atom aligned RMSD11.3964Å
versus replica1 7.12488Å. This illustrates seed sensitivity, not convergence.
An audit-script variable collision was corrected in a versioned reviewer; original
script/failure retained. No native output or scientific gate was altered.

Admitted `formation-replica2-preparation-control-v1`: new initial velocity seed614032,
same minimized control geometry, established five sequential preparation stages,
1.15ns total,3h hard bound,8GiB/no swap/four CPUs. Watcher completion/failure/deadline
triggers armed; expected about1h. All bulk output/scratch on Archive; no cloud.
Audit preparation before admitting control10ns validation. Current handoff points
to this new control job. Parameter/transfer gates remain open; no production or
minimum certification. Audit: `docs/audits/cpd_corrected_cis_anti_i_replica2_validation_20261015.json`.

The following active/paused statements are retained history, superseded above.

**RESUMED — 2026-10-15 14:20 Denver, explicit user command.**
Welded replica2 continues from verified step2575000 (4/10ns validation),
using a new `formation-replica2-validation-anti-resume-v2` job/service and
six logical segments5–10. Original partial segment5 is preserved unchanged.
Every pinned input reverified; no duplicate CPD service. Resource limits:
8GiB RAM, no swap, four CPU cores, 15h hard stop including stop grace.
Completion/failure/deadline watcher armed; no periodic polling. Outputs and
scratch remain on Archive. Audit: `docs/audits/cpd_corrected_cis_anti_i_replica2_resume_20261015.json`.
Next: review all ten segments together, then assess matched control replica2.
This remains provisional validation, not parameter or minimum certification.

**Historical pause — superseded by the explicit resume below (2026-10-15).**
Campaign `pause.json` is set. Active welded replica2 validation service and its
completion/deadline watcher were stopped; both are inactive, and no CPD native
service or NAMD process remains running. No automatic continuation is authorized
until the user explicitly commands resume. Late wakes must not launch work.

Replica2 validation segments1–4 are complete: **4ns validation /5.15ns total**.
All four native terminal logs and checkpoint/velocity/cell/physical-audit hashes
verified; recorded physical/frame verdicts pass. Last reliable checkpoint:
`formation-replica2-validation-anti-v1/segment-04/result.{coor,vel,xsc}` at
**step2575000**. Segment5 partial output is preserved through loggedstep2779500
(about0.409ns further); it has no new coordinate/velocity restart checkpoint.
Resume must repeat segment5 from segment4, not infer velocities from the DCD.
Remaining validation **6ns**, segments5–10, targetstep5575000. Nothing deleted.

Archive `pause-handoff-20261015-replica2/resume_plan.json` pins the restart bundle,
original plan/progress, and a syntax-checked six-segment resume worker. Future launch
must create a new job/service, use seed614535 (original segment5 seed), fresh resource
admission and time bounds below16h, and fresh event triggers. Do not relaunch the
original10segment worker or overwrite partial outputs. Original sources and scientific
limitations remain: provisional parameter model; no minimum/production certificate.
Current handoff: `current_handoff.json` → `pause-handoff-20261015-replica2/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_pause_20261015.json`.

The following entries are retained history; their active-run statements are superseded.

**Welded replica2 preparation audited;10ns diagnostic validation active — 2026-10-15 Denver.**
Acknowledged `cbf958d5-da36-4f95-857e-fe2a3c338260`. Five preparation stages
completed **1.15ns in3531.58s (58.86min)**. Audit verifies all27 native segments,
source/worker/assessment/checkpoint hashes,250 pinned worker frame verdicts,
new initial seed614031, and continuous coordinates/velocities/cells thereafter.
Independent replay of first/middle/last frames persegment (**81 frames**) and all
27 endpoints agrees, including actual-cell NPT checks and restraint-corrected
restart continuity. Initial velocities were generated once; no later reset. All
stereo, contact, bond, ring, water and image checks pass under reviewedV2 policy.

Final conditioning endpoint densities **1.02273–1.02639g/mL**. Heavy-atom aligned
RMSD reaches **7.59081Å**, geometric Rg **29.25443Å**, compared with replica1
conditioning endpoint4.59984Å/28.01623Å. This is seed sensitivity, not convergence
or a quantified weld effect. Replica2 shares the same minimized starting structure;
it is not an independently sampled structural conformer. Parameter gaps, including
7.15616kcal/mol conformer-energy discrepancy, remain unresolved. No formal parameter-
qualified structural release, endpoint minimum or production certification implied.

Admitted `formation-replica2-validation-anti-v1` **07:45:59 Denver**:
10ns provisional welded replica2 NPT from its own audited1.15ns checkpoint,
validation seed614531 (replica1 used514531), unchanged native settings. Ten1ns
restart/audit boundaries, physical saved-frame checks every10ps. Four CPUs/GPU,
8GiB/no swap,5400-second native segment timeout,**15-hour total bound**.
Stop on failed physical acceptance or native runtime>3914.06s/ns; preserve completed
checkpoints. Expected8–10hours. Completion/failure watcher
`7117ff25-ad41-4116-9839-a5830dbb5153` armed; review **22:30:59**, hard stop
**22:45:59 Oct15 Denver**. No periodic simulation polling, duplicate jobs, new QM,
cloud spending or deletion. Bulk outputs/scratch remain on Archive.
Next event audits replica2 validation and compares seed sensitivity before matched
control replica2 preparation/validation; no automatic long extension or promotion.
Original failed services and versioned gate review remain preserved.
Current handoff: `current_handoff.json` → `formation-replica2-validation-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_replica2_preparation_20261015.json`.

The following entries are retained history, superseded above.

**First matched10ns pair audited; replica2 diagnostic preparation active — 2026-10-15 Denver.**
Acknowledged `b49a0fd2-4635-4ba0-9a31-7d5db9952d97`. Control10ns completed in
**30074.88s (8.35h)**. Every native log/checkpoint and1000 pinned worker frame
verdicts verified; independent first/middle/last-frame replay persegment (30 frames)
and all10 endpoints agree. Full DCD hashes recorded. All294 stereo sentinels and
physical integrity checks pass under documentedV2; original failed stages remain.
Control endpoint density1.02236–1.02521g/mL, mean temperatures299.18–299.26K,
group pressures−0.53–3.43bar. No minimum or ensemble-convergence claim follows.

Control aligned endpoint RMSD reaches **13.3859Å**, compared with welded7.1249Å;
this alone does not establish a weld effect. Read-only exploratory structural review
tracks all141 cross-strand base-centroid pairs initially within8Å in the common
control seed. Final retained counts **126 welded /120 control**; these are geometric
contact proxies, not assigned Watson–Crick pairs or a melting statistic. Per-strand
aligned RMSD shows internal rearrangement, not just relative rigid strand motion.
Both cases need replication; one trajectory pair cannot support quantitative stability,
stiffness or thermal conclusions. The analysis's first script failed on OpenMM mass
units before writing results; retained original script, corrected version uses daltons.

**Scope remains diagnostic:** preliminary protocolv2 requires parameter gates before
formal structural qualification. Those gates are not claimed passed:7.15616kcal/mol
QM/MM alternate-conformer discrepancy, sugar/charge transfer and holdout qualification
remain open. Additional seed diagnostics cannot waive them. No app/registry promotion.

Admitted **welded replica2 preparation** from the same original minimized context,
new velocity seed **614031** (replica1 used514031), at **06:44:54 Denver**.
`formation-replica2-preparation-anti-v1` batches the established10ps startup,
20ps300K approach,20ps restraint release,100ps NPT and1ns conditioning into one
bounded1.15ns job. Each stage retains its own frozen worker/plan/native outputs;
per-frame/segment gates and terminal assessment must pass before the next stage.
Only one native process runs at a time. Same starting geometry means independent
velocity-seed evidence, not independently sampled starting conformations. No10ns
replica2 validation automatically follows completion. Versioned startup/thermal/
release workers use the already-reviewedV2 dynamics predicate; no new thresholds.

Four CPUs/GPU,8GiB/no swap,900-second native segment timeout, **three-hour cap**.
Event watcher `cbf958d5-da36-4f95-857e-fe2a3c338260` armed; review **09:39:54**,
hard stop **09:44:54 Oct15 Denver**. Expected roughly65–75minutes. Batching avoids
unnecessary manual wakeups between already-established short preparation stages;
completion/failure trigger and audits remain. No polling, duplicate jobs, new QM,
cloud spending or deletion; bulk artifacts/scratch on Archive.
Next event audits seed lineage and all stage evidence before deciding10ns replica2
validation and matched control replica2. Remaining parameter gates stay separate.
Current handoff: `current_handoff.json` → `formation-replica2-preparation-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_matched_validation_20261015.json`.

The following entries are retained history, superseded above.

**First welded10ns validation audited; matched control validation active — 2026-10-14 Denver.**
Acknowledged `3ba51c92-7aa5-467c-b845-aa15472f0a6e`. Welded10ns completed in
**30100.61s (8.36h)**, total trajectory11.15ns. All ten native segments completed
normally. Reviewed every native log/checkpoint, all1000 hash-pinned worker frame
verdicts, and source/configuration/restart evidence. Independent replay of first,
middle and last frame persegment (**30 frames**) plus all10 endpoints agrees with
the worker; full DCD hashes are recorded. This is explicitly not a second full
1000frame replay. All298 stereo sentinels and physical integrity checks pass;
maximum restart energy difference0.0356kcal/mol. No slowdown stop: native throughput
**29.26ns/day**, individual1ns runtimes2935.80–3072.18s.

Endpoint density **1.02177–1.02454g/mL**, segment mean temperatures299.18–299.28K,
group pressures−0.43–2.42bar. Void witnesses3.17–3.58Å remain comparable to
initial solvent; no growing sampled cavity. Heavy-atom aligned endpoint RMSD
**5.76–7.30Å** and geometric Rg27.32–29.69Å continue fluctuating. Native integrity
and these physical summaries support matched validation; they do not establish
structural convergence, weld-induced stiffness, melting, minimum certification,
or force-field accuracy. Unresolved7.15616kcal/mol conformer-energy discrepancy,
transfer/holdout qualifications and independent replicas remain separate gaps.

Launched matched `formation-validation-control-v3`, **21:56:53 Oct14 Denver**:
10ns provisional NPT validation from audited control1.15ns checkpoint, same
worker/seed/settings. Ten1ns audit/restart boundaries; saved-frame physical checks
every10ps. Four CPUs/GPU,8GiB/no swap,5400-second native segment timeout,
**15-hour total bound**. Retain checkpoints and stop on physical failure or runtime
above3914.06s/ns. Expected8–10hours from actual native timings.
Completion/failure watcher `b49a0fd2-4635-4ba0-9a31-7d5db9952d97` armed;
review **12:41:53 Oct15**, hard stop **12:56:53 Oct15 Denver**. No periodic
simulation polling, duplicate jobs, new QM, cloud spending or deletion. Archive
has3.8TiB free; all bulk outputs/scratch stay there. Prior failures remain intact.

Next event audits the matched10ns pair, reviews structural trends and remaining
independent-replica/parameter requirements before further compute. No registry,
application or production promotion. Current handoff: `current_handoff.json` →
`formation-validation-control-v3/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_welded_validation_20261014.json`.

The following entries are retained history, superseded above.

**Matched1ns conditioning audited; bounded10ns welded validation active — 2026-10-14 Denver.**
Acknowledged `4059bbaa-cabd-4cbe-b628-569b38e695ed`. Control additional1ns
completed in **3329.87s (55.50min)**; both cases now have1.15ns preparation.
Independent replay verified ten native segments and all100 saved frames, source/
checkpoint hashes, actual-cell physical checks and structural descriptors. All294
sugar stereo sentinels and bond/contact/ring/water/image checks pass. Maximum
restart energy error0.0309kcal/mol. Control native runtime3261.72s/ns, about10.2%
slower than welded2960.08s/ns, within the existing20% material-slowdown criterion.

Control endpoint densities **1.02177–1.02483g/mL**, temperature means299.06–299.35K,
pressure means−6.82–7.23bar; void witnesses3.19–3.43Å. Physical trends resemble
the welded case. Control aligned heavy-atom RMSD rises4.31→6.45Å, geometric
Rg29.36→29.78Å (maximum30.03Å); welded final RMSD4.60Å/Rg28.02Å. Different
single trajectories are not a stiffness, melting, or weld-effect estimate. Ongoing
structural motion warrants longer validation, not a convergence claim. The unresolved
7.15616kcal/mol conformer-energy discrepancy and transfer/holdout gaps remain.

Admitted **one10ns provisional welded NPT validation**,
`formation-validation-anti-v3`, **13:33:55 Denver**. It starts from the audited
welded1.15ns checkpoint; no initial preparation rerun. Ten1ns restart boundaries,
physical/geometry frame audits every10ps, endpoint density/void/temperature/pressure,
aligned RMSD/Rg and checkpoint continuity at every boundary. Retain all failure
artifacts; stop after a completed segment if native runtime exceeds **3914.06s/ns**
(20% above recent matched reference3261.72s/ns), or immediately on failed physical
acceptance. Existing15h/10ns validation workflow is the scheduling comparator.
No production, force-field accuracy or ensemble-convergence certification implied.

Four CPUs/GPU,8GiB/no swap,5400-second native segment timeout, **15-hour total
bound**, below the user16h limit. Measured expected runtime roughly9hours; native
conditioning gave8.2–9.1hours per10ns before audit overhead. Completion/failure
watcher `3ba51c92-7aa5-467c-b845-aa15472f0a6e` armed; review **04:18:55 Oct15**,
hard stop **04:33:55 Oct15 Denver**. Event-driven, no periodic simulation polling,
duplicate jobs, new QM, cloud spending or deletion. Bulk files remain on Archive.
Next event reviews physical/structural trends, necessity/performance, matched control
validation and independent replica requirements. Parameter gaps remain separate;
no automatic registry/application promotion. Historical failed services preserved.
Current handoff: `current_handoff.json` → `formation-validation-anti-v3/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_validation_admission_20261014.json`.

The following entries are retained history, superseded above.

**Welded1ns conditioning audited; matched control continuation active — 2026-10-14 Denver.**
Acknowledged `d1f82c76-290a-439f-8aff-be3e1379a09e`. Additional welded1ns
completed in **3027.77s (50.46min)**; total trajectory preparation now1.15ns.
Independent reread/replay verifies ten native segments, all100 saved frames,
actual-cell physical and structural diagnostics, native/checkpoint hashes and
restart energy continuity (maximum0.0457kcal/mol). All298 stereo sentinels and
bond/contact/ring/water/image checks pass under the documentedV2 dynamics policy.
Native runtime2960.08s, **29.19ns/day**,100ps segments295.60–296.26s; no material
slowdown and no reason to tune or repeat this run for speed.

Endpoint density1.02259–1.02528g/mL; segment mean temperatures299.05–299.41K
and group pressures−10.00–10.96bar. Void witnesses3.13–3.40Å; endpoint image
clearance lower bounds36.96–44.79Å. Solute-heavy aligned RMSD3.57–4.60Å, geometric
Rg28.02–29.08Å; final RMSD4.60Å and Rg28.02Å. These descriptors show ongoing
structural motion, not demonstrated convergence. Physical preparation is progressing;
minimum certification, sampling convergence and parameter accuracy remain distinct.
The7.15616kcal/mol QM/MM conformer discrepancy and transfer/holdout gaps remain.

Launched matched `formation-npt-condition-control-v2` **12:36:31 Denver**:
additional1ns NPT, ten100ps segments from audited control150ps checkpoint, same
worker/seed/native settings and diagnostics. Four CPUs/GPU,8GiB/no swap,
900-second segment cap,**two-hour total bound**. Completion/failure watcher
`4059bbaa-cabd-4cbe-b628-569b38e695ed` armed; review **14:31:31**, hard stop
**14:36:31 Denver**. Expected runtime about51minutes from actual welded timing.
No intermittent simulation polling, duplicate jobs, new QM, cloud spending or
deletion. Bulk outputs/scratch stay on Archive; historical failed services remain.

Next event: audit matched conditioning, compare physical/structural trends, and
assess longer validation/independent replicas against the remaining parameter
requirements. No automatic full-production claim or promotion follows from1ns.
Current handoff: `current_handoff.json` → `formation-npt-condition-control-v2/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_welded_conditioning_20261014.json`.

The following entries are retained history, superseded above.

**Matched NPT pilots audited; bounded1ns welded conditioning active — 2026-10-14 Denver.**
Acknowledged `05d16185-0626-4b2a-813c-a1401748016f`. Control100ps NPT completed
in **317.23s**. Independent native/physical replay verified all20 frames, actual
cells, checkpoint hashes, restart energies and all294 stereo sentinels; no severe
contacts/ring piercings or bond/water/image failures. Endpoint densities
**1.02262,1.02555,1.02465,1.02562g/mL**, comparable to welded1.02245–1.02536.
Control segment mean temperatures299.01–299.67K; final box137.87804Å, added-salt
concentration0.15711M, water O–O2.46298Å, image-clearance lower bound38.29128Å.
Void witnesses3.20–3.30Å show no growing sampled cavity. Final true-base displacement
4.49129Å remains diagnostic under reviewedV2; absolute displacement is not hidden.
Neither pilot alone establishes ensemble convergence or adequate structural sampling.

**Parity inventory:** isolated/full-DNA native export and restart engineering have
passed. Corrected context now has150ps total percase, including100ps NPT. Historical
`gpu_cube_preparation_v6.py` specifies1ns NPT, and `gpu_cube_validation_v6.py`
specifies subsequent10ns runs with1ns boundaries; these are workflow comparators,
not claims that every prior isomer passed every gate. Longer sampling/independent
replicas remain open. Certified36atom core minimum does not certify sugar endpoints.
The **7.15616kcal/mol alternate-conformer QM/MM discrepancy**, incomplete sugar/charge
transfer and holdout qualification remain separate unresolved parameter gates.
Native MD stability cannot fix or waive these. No registry/application promotion.

Admitted `formation-npt-condition-anti-v2`, **11:44:01 Denver**: **additional1ns
NPT**, ten100ps segments from the audited welded150ps endpoint, same physical
settings. Audit frame geometry/water/cell every10ps and restart/physical trends at
each100ps boundary. Add aligned solute-heavy RMSD to prepared seed and geometric
radius of gyration as structural diagnostics; neither is given a post-hoc pass
threshold. Density, void witnesses, water counts, temperature/pressure and salt
concentration continue to be recorded. Initial physical audit precedes native work.
No repeat100ps pilot or new QM launched. Measured pilots imply roughly53minutes
for1ns, with bounded margin rather than repeated tiny admissions.

Four CPUs/GPU,8GiB/no swap,900-second native segment cap,**two-hour total bound**.
Completion/failure watcher `d1f82c76-290a-439f-8aff-be3e1379a09e` armed;
review **13:39:01**, hard stop **13:44:01 Denver**. No polling, duplicates, cloud
spending or deletion; bulk data/scratch stay on Archive. Checkpoint audits stop on
physical failure; the next event reviews necessity, efficiency and matched control
conditioning before longer validation. All historical failed verdicts remain intact.
Current handoff: `current_handoff.json` → `formation-npt-condition-anti-v2/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_matched_npt_parity_20261014.json`.
Minimum/parameter/production qualification remains limited as stated above.

The following entries are retained history, superseded above.

**Initial welded NPT audited; matched control NPT active — 2026-10-14 Denver.**
Acknowledged `64981a14-0d8d-4a97-99dc-dc4c2536028a`. Welded100ps NPT
completed in **316.39s**. Independent output replay verified all four native logs,
20 saved frames with actual-cell physical checks, coordinates/velocities/cell pins,
piston configuration/restart inputs, native volume agreement and restart energy
continuity (maximum **0.0251kcal/mol**). All298 stereo sentinels, bond/contact/ring,
water and image checks pass under the documented V2 dynamics policy.

Initial density **0.97968g/mL**;25ps endpoints **1.02536,1.02382,1.02470,1.02245**.
Final cubic side **138.02028Å**, added-salt concentration **0.15663M**.
Segment mean temperatures **299.81,299.26,298.95,299.66K**; group-pressure
means **−16.32,−11.07,5.56,4.87bar**. These are finite preparation summaries,
not uncertainty estimates or a stationarity/convergence certificate.2Å-grid
nearest-atom void witnesses **3.36,3.44,3.25,3.38Å**, versus initial3.43Å, show
no growing sampled large cavity. Water spatial counts remain comparable; these
coarse witnesses do not certify universal solvent uniformity. Final minimum water
O–O **2.46417Å**, image-clearance lower bound **38.11793Å**. Actual-base absolute
displacement reaches **6.42134Å** at the endpoint, retained as a dynamics diagnostic;
local/whole-DNA structural sampling and parameter accuracy still require assessment.

Launched matched `formation-npt-control-v1`, **11:37:24 Denver**: same100ps in
four25ps segments, same seed/native settings, from the audited control50ps endpoint.
No prior segments rerun. Four CPUs/GPU,8GiB/no swap,600-second segment timeout,
20-minute total bound. Event watcher `05d16185-0626-4b2a-813c-a1401748016f`
armed; review **11:55:24**, hard stop **11:57:24 Denver**. No polling, duplicates,
cloud spending or deletion; bulk files/scratch remain on Archive. Historical
failures and the policy-review trail remain intact.
Next audit compares matched physical/structural trends and inventories remaining
sampling/parameter/export requirements for parity with the developed isomers,
rather than assuming100ps is equilibration or automatically extending identical pilots.
Current handoff: `current_handoff.json` → `formation-npt-control-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_welded_npt_20261014.json`.
Minimum certification and production readiness remain unestablished.

The following entries are retained history, superseded above.

**Matched release complete under reviewed dynamics policy; initial welded NPT active — 2026-10-14 Denver.**
Acknowledged `d6861060-6021-4d2f-8959-de3b19c436c5`. Remaining control5ps
completed in **18.03s**. Independent replay verified all10 frames, final294 sugar
stereo sentinels, contacts/rings/bonds, rigid-water coordinates, and restart energy
error **0.0187kcal/mol**. Final temperature **299.618K**, bond ratios
**0.90691–1.08888**, image clearance **42.49820Å**. Both matched systems now have
50ps total preparation, including10ps unrestrained. Existing welded20ps and
control15ps release outputs were reused, not repeated. Original failed services
remain failed; progression relies on the separately documented V2 dynamics review,
not a retrospective claim that the original displacement gate passed.

Admitted `formation-npt-anti-v1`, **11:31:07 Denver**: initial **100ps isotropic
NPT at300K/1.01325bar**, four25ps native segments from the reviewed welded50ps
checkpoint. No restraints or velocity reset. Existing native piston settings:
period200fs, decay100fs, group pressure, fixed cell shape. Ordinary masses/2fs,
rigid hydrogen bonds/water, existing PME/force switching. Checkpoints retain
coordinates/velocities/cell and piston state through extendedSystem files.

Every5ps trajectory frame uses its actual DCD cell for image clearance and
periodic water contacts. At each25ps endpoint, audit stereo/contact/bond integrity,
rigid-water error after storage precision, water O–O>2Å and image clearance>=12Å.
Record density from actual PSF mass/volume, added-salt concentration, temperature/
pressure means, water spatial counts, and a2Å-grid nearest-atom void witness.
Void/density trends require review; completing100ps does not certify equilibrated
solvent or structural sampling. Initial physical audit must pass before native work.

Four CPUs/GPU,8GiB/no swap,600-second native segment timeout,20-minute service
bound. Event watcher `64981a14-0d8d-4a97-99dc-dc4c2536028a` armed;
review **11:49:07**, hard stop **11:51:07 Denver**. No polling, duplicate jobs,
cloud spending or deletion. All large outputs/scratch remain on Archive.
Next: audit NPT physical trends and engine restart evidence before matched control
NPT or any longer equilibration. Minimum certification, parameter qualification and
production readiness remain open. The historical old1×T hold remains unaffected.
Current handoff: `current_handoff.json` → `formation-npt-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_npt_admission_20261014.json`.

The following entries are retained history, superseded above.

**Matched failures audited; placement/dynamics gate separation reviewed — 2026-10-14 Denver.**
Acknowledged `8154118e-4895-4e52-acf3-b2bdfba68f04`. Control native release
completed15ps normally, stopping after the first unrestrained5ps because four
trajectory frames exceeded3.5Å. Independent replay verifies all30 frames and
native restart/coordinate/velocity/cell evidence; endpoint itself passes the old
gate. Maximum true-base displacement **4.14632Å**, dominated by thymine methyl
hydrogens H52/H53, not phosphate-selector contamination. Both welded and control
release retain stereo, bond/contact/ring integrity despite absolute displacement.
This comparison is diagnostic, not evidence that the candidate force field is accurate.

**Explicit versioned policy correction:** `placement_review_v2.py` establishes
3.5Å as an initial static CPD placement screen. Existing native dynamics
`solvated_engine_v3.geometry_passed` checks stereo, bond integrity, severe clashes
and ring piercing; its periodic checks add image/water integrity, not absolute
positions relative to a pre-reaction frame. The new release worker had incorrectly
extended that static screen to every unrestrained frame. V2 retains the initial
seed3.5Å gate, fixes base selection to the explicit28 thymine atoms (no OP1/OP2),
and reports subsequent absolute displacement as a diagnostic. Dynamic stereo,
contact, bond-ratio and image thresholds are unchanged. This is a documented
change in gate applicability, not a claim that either original failed gate passed.
Original services/failures and frozen workers remain unchanged. Application
placement rules and the rejected15Å old1×T route remain untouched.

Read-only V2 replay of **40 welded +30 control frames** passes dynamic integrity,
with water O–O endpoint minima **2.44672/2.45131Å** (last respective segments),
above the existing2Å check. Initial placements pass unchanged3.5Å. No new dynamics
were needed for this review; a minimum or ensemble certificate does not follow.

Admitted only the missing **5ps unrestrained control** from its existing45ps
checkpoint: `formation-release-control-finish-v2`, **11:28:42 Denver**. Same final
seed as the originally planned segment, preserved velocities/cell; no welded or
completed control segments rerun. V2 structural integrity audits every0.5ps,
unchanged restart/water checks. Four CPUs/GPU,8GiB/no swap,300-second native cap,
20-minute service bound. Event watcher `d6861060-6021-4d2f-8959-de3b19c436c5`
armed; review **11:46:42**, hard stop **11:48:42 Denver**. No polling or cloud.
All bulk evidence remains on Archive. Next audit combines existing15ps +new5ps
control release, then assesses matched50ps endpoints for bounded NPT with density,
void/water-uniformity and image checks. No NPT launched in this transition.
Current handoff: `current_handoff.json` → `formation-release-control-finish-v2/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_release_gate_review_20261014.json`.
Production readiness, minimum certification and parameter qualifications remain open.

The following entries are retained history, superseded above.

**Welded release fails displacement gate; matched control diagnostic active — 2026-10-14 Denver.**
Acknowledged failed token `f0421dd6-2235-4197-9312-ffb552f4240e`. Native NAMD
completed all four5ps segments normally; the worker failed the final geometry
acceptance, not integration or restart. Independent replay verifies all40 frames,
coordinate/velocity/cell evidence, restraint removal and restraint-corrected restart
energies. First15ps passes. In the last5ps, four saved frames fail the inherited
3.5Å displacement gate; endpoint **3.61646Å**, trajectory maximum **3.88535Å**.
All298 stereocenters, bond ratios, water geometry, severe-contact and ring-piercing
checks pass throughout. Final temperature298.48K. Original failure and all native
outputs remain unchanged; no failed endpoint is promoted or continued.

Read-only attribution found a real selector defect: the nominal base selector
excludes `O1P/O2P`, but this topology uses `OP1/OP2`, so it includes four phosphate
oxygens. Atom `2:OP2` dominates all four failed frames. Correctly excluding these
oxygens resolves three failures; the last frame still has **3.58763Å actual-base
displacement**, exceeding3.5Å. Thus fixing the selector alone cannot rescue this
run. Global alignment gives3.89021Å and local sugar alignment4.22024Å for that
last frame; simple rigid drift is not established as the explanation. These
aligned metrics are diagnostic only, not replacement thresholds. Placement-screen
semantics during unrestrained dynamics need review against matched control and
local structural evidence before any NPT. No threshold is relaxed post hoc.

Admitted `formation-release-control-v1` independently from its passing30ps thermal
checkpoint, **11:25:47 Denver**: same frozen20ps release protocol/seed and geometry
gates, including the disclosed selector defect for matched raw comparison. This
is a diagnostic to distinguish common motion from weld-specific behavior, not a
retry of the failed welded trajectory. Correct base-only attribution must accompany
its output audit. No additional welded dynamics or NPT admitted.

Four CPUs/GPU,8GiB/no swap,300-second native segment cap,20-minute total bound.
Completion/failure watcher `8154118e-4895-4e52-acf3-b2bdfba68f04` armed;
review **11:43:47**, hard stop **11:45:47 Denver**. No polling, duplicate jobs,
cloud spending or deletion. Bulk evidence remains on Archive. Next review compares
control/welded release, fixes selector in a versioned audit implementation, and
assesses structural/gate meaning before further progression; no fishing for a pass.
Current handoff: `current_handoff.json` → `formation-release-control-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_release_failure_20261014.json`.
No minimum, ensemble or production-readiness certification.

The following entries are retained history, superseded above.

**Matched thermal approach audited; welded restraint release active — 2026-10-14 Denver.**
Acknowledged `9e043bc2-473a-4256-a713-f39c5a096b01`. Control20ps continuation
completed in **72.64s**. Independent output replay verified all four native segments,
40 trajectory frames, all294 sugar stereo sentinels, finite/checkpoint restart
energy continuity, rigid-water geometry and fixed140Å cell. No severe heavy
clashes or ring piercings. Final bond ratios **0.92132–1.08929**, base displacement
**2.36674Å**, image clearance **44.01003Å**. Final temperature **298.8863K**;
last segment early/late means **298.34/298.78K**. Both matched systems now approach
300K sufficiently for the next preparation step; no further initial warming is
admitted. The inherited control replay next_action is superseded by this decision.
Neither temperature approach nor successful dynamics certifies a local minimum,
density/ensemble equilibration, parameter accuracy or production readiness.

Launched `formation-release-anti-v1` at **11:22:47 Denver**: four5ps NVT segments
at300K with restraint strengths **0.5,0.1,0,0**, preserving coordinates, velocities
and cell from the welded30ps checkpoint. Final10ps has no restraint directives.
Pressure coupling remains off to isolate release behavior. Geometry audited every
0.5ps with unchanged thresholds; endpoint water/restart checks remain. Restart
potential-energy comparison explicitly subtracts the known restraint-energy
change when strength changes, rather than misidentifying that change as a restart
failure. No tolerance increase. Early/late temperature means are recorded.

One local20ps job: four CPUs/GPU,8GiB/no swap,300-second native segment cap,
20-minute total bound. Completion/failure watcher
`f0421dd6-2235-4197-9312-ffb552f4240e` armed; review **11:40:47**, hard stop
**11:42:47 Denver**. No periodic polling, duplicates or cloud spending. Bulk files
remain on Archive; all prior failures are preserved. If successful, audit before
matched control release, then NPT preparation with density, solvent-uniformity and
periodic-cell checks. No automatic production promotion.
Current handoff: `current_handoff.json` → `formation-release-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_matched_thermal_20261014.json`.

The following entries are retained history, superseded above.

**Welded temperature approaches 300 K; matched control continuation active — 2026-10-14 Denver.**
Acknowledged `9d753ffa-6e8a-4db8-b8f5-0471ba86d7fb`. Welded20ps continuation
completed in **71.93 s**. Independent output replay verifies all four native logs,
40 trajectory frames, coordinate/velocity/cell pins, every restart including the
initial10ps checkpoint, rigid-water geometry and unchanged140Å cell. All **298
stereo sentinels** pass, with no severe heavy clashes or ring piercings. Final bond
ratios **0.92202–1.08969**, base displacement **2.75226Å**, image clearance
**44.69614Å**. Maximum restart potential-energy error **0.0190kcal/mol**.

Temperature second-half means per5ps segment: **278.06,293.76,297.80,299.23K**;
final instantaneous **299.5534K**. Final segment early/late means298.68/299.23K
show substantially reduced heating drift. This is sufficient thermal approach to
proceed with the next preparation assessment; no repeated welded warming is
justified now. It is not a density/ensemble-equilibration, unrestrained-stability,
force-field-accuracy, local-minimum or production certificate.

Matched unwelded `formation-thermal-control-v1` launched **11:20:36 Denver**:
same20ps at300K, four5ps segments, preserved velocities/cell, restraint coefficient1,
identical seed and geometry/restart/water gates. Four CPUs/GPU,8GiB/no swap,
300-second native timeout,20-minute total bound. Completion/failure watcher
`9e043bc2-473a-4256-a713-f39c5a096b01` armed; review **11:38:36**, hard stop
**11:40:36 Denver**. No periodic polling, duplicate jobs or cloud spending;
bulk files stay on Archive and prior failures remain preserved.
Next: audit matched temperature/geometry response and then admit restraint release
and NPT preparation with explicit density/solvent-uniformity/periodic-cell checks.
Provisional force-field limitations remain. No automatic production promotion.
Current handoff: `current_handoff.json` → `formation-thermal-control-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_welded_thermal_20261014.json`.

The following entries are retained history, superseded above.

**Matched restrained startup audited; welded300K continuation launched — 2026-10-14 Denver.**
Acknowledged `57acbcf8-efab-4376-a8a9-7813d1364f66`. Control completed10ps in
**54.59s**. Independent output replay verified all five native segments and
**50 frames**, all294 sugar stereo sentinels, no severe heavy clashes or ring
piercings, rigid-water geometry, restart inputs and fixed140Å cell. Final bond
ratios **0.91133–1.10333**, base displacement **2.67519Å**, image clearance
**44.25685Å**. Maximum restart energy difference **0.0119kcal/mol**, final
same-target difference **0.0057kcal/mol**. Final temperature **245.0486K** versus
**245.7941K** welded: both short pilots have comparable incomplete heating.
The control replay's inherited generic next-action text is superseded here:
matched startup is complete; no repeat10ps initial-velocity pilot is needed.
Neither restrained startup establishes equilibration, a minimum or production readiness.

Launched `formation-thermal-anti-v1` at **11:18:31 Denver**: **20ps additional
restrained NVT at300K**, four5ps segments from the welded10ps checkpoint,
retaining binary velocities/cell and restraint coefficient1. No velocity reset,
pressure coupling or restraint release. Audit geometry every0.5ps, water geometry
and restart continuity at each5ps endpoint, and record early/late temperature
means per segment to assess thermal approach. Existing geometry gates unchanged.

One local job, four CPUs/GPU,8GiB/no swap,300-second native segment cap,
20-minute total bound. Completion/failure watcher
`9d753ffa-6e8a-4db8-b8f5-0471ba86d7fb` armed; review **11:36:31**, hard stop
**11:38:31 Denver**. No periodic polling, duplicates or cloud spending. Bulk
outputs and scratch remain on Archive. Failures remain preserved.
Next audit decides matched control20ps and then restraint release/NPT preparation;
thermal/density/solvent-uniformity qualification and provisional force-field
limitations remain open. No automatic production or minimum certification.
Current handoff: `current_handoff.json` → `formation-thermal-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_matched_startup_20261014.json`.

The following entries are retained history, superseded above.

**Welded restrained startup audited; matched control running — 2026-10-14 Denver.**
Acknowledged `f35c66f2-a50d-457a-8abe-785e38fa5b53`. The welded10ps pilot
completed in **55.24 s**. Independent output replay verified pinned native logs,
coordinates/velocities/cell, all **50 trajectory frames**, preserved restart inputs,
finite energies/temperatures, rigid-water OH geometry and fixed140Å periodic cell.
All **298 stereo sentinels** pass; no severe heavy clashes or ring piercings.
Final bond ratios **0.92410–1.10056**, base displacement **2.16617Å**, conservative
image clearance **44.79110Å**. Maximum restart potential-energy difference is
**0.0189kcal/mol**; final same-target restart difference **0.0105kcal/mol**.
Final instantaneous temperature **245.7941K** shows that this10ps pilot has not
completed heating to300K. It establishes only restrained startup/restart behavior,
not thermal/density equilibration, unrestrained stability, a minimum, or production
readiness. No geometry/force-field gate was relaxed; prior failures are retained.

Matched unwelded `formation-startup-control-v1` launched **11:16:31 Denver** with
the same worker, seed,10ps protocol and restraint coefficient1. Five2ps segments,
thermostat targets50/100/200/300/300K,294 sugar stereo sentinels, all original
geometry/restart/water checks. One local job: four CPUs/GPU,8GiB/no swap,
300-second native segment cap,20-minute total bound. Completion/failure watcher
`57acbcf8-efab-4376-a8a9-7813d1364f66` armed; review **11:34:31**, hard stop
**11:36:31 Denver**. No periodic polling, duplicate jobs or cloud spending.
Bulk data and scratch remain on Archive.

Next: audit matched control, compare heating behavior, then admit additional300K
conditioning, restraint release and NPT preparation in bounded stages. Density,
solvent uniformity and thermal stationarity must be measured before treating the
context as equilibrated. Existing provisional parameter limitations remain.
Current handoff: `current_handoff.json` → `formation-startup-control-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_welded_startup_20261014.json`.

The following entries are retained history, superseded above.

**Native PME mode comparison audited; restrained welded startup launched — 2026-10-14 Denver.**
Acknowledged `dd45f221-5cd1-4cef-88cc-005ff003afd1`. All four native static jobs
terminated normally. Independent replay checked source/evidence hashes, exact
checkpoint use, requested/actual GPU mode, zero-step logs and binary force files.
Welded energy/maximum-force differences were **0.46770 kcal/mol / 0.00125263
kcal/mol/Å**; control **0.47980 / 0.00123306**. Both pass the existing full-system
relative1e-4/absolute0.001 policy. This compares native offload (CPU bonded terms,
GPU nonbonded) against resident mode, not an independent all-CPU reference or
force-field accuracy test. No dynamics were run for the comparison.

Launched `formation-startup-anti-v1` at **11:14:29 Denver**: five sequential **2 ps**
NVT segments, thermostat targets **50, 100, 200, 300, 300 K**, ordinary masses and
2 fs timestep, rigid water/H bonds. Heavy-solute restraint coefficient1 is retained
throughout. The final segment is a same-target restart using binary coordinates,
velocities and cell. Initial velocities are generated once; later segments retain
them. Check every100-step frame against the unchanged stereochemistry/contact/bond/
displacement/image gates, finite native energy/temperature, endpoint rigid-water
OH error<1e-4 Å, and restart energy continuity max(0.01,1e-6*previous |energy|).
Temperature0..600 K is an instability screen, not equilibration acceptance.

One job, **10 ps maximum**, four CPUs/GPU, **8 GiB/no swap**, 300-second native
segment timeout, **20-minute total bound**. Event watcher
`f35c66f2-a50d-457a-8abe-785e38fa5b53` armed; review **11:32:29**, hard stop
**11:34:29 Denver**. No periodic polling, cloud spending or duplicate jobs.
All bulk outputs and scratch remain on Archive. A failed audit stops continuation
and preserves native evidence. If successful, audit before matched control startup
and subsequent unrestrained/NPT preparation. This short restrained pilot cannot
establish density equilibration, unrestrained stability, melting behavior, a local
minimum, or production readiness. Provisional force-field limitations remain.
Current handoff: `current_handoff.json` → `formation-startup-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_pme_startup_20261014.json`.

The following entries are retained history, superseded above.

**Matched solvent conditioning audited; native PME mode qualification launched — 2026-10-14 Denver.**
Acknowledged control completion `fa4ed815-9d0f-40d2-b399-135859779371`.
Control completed **2,500 minimization steps / zero MD in 64.22 s**. Independent
reread/replay with the frozen geometry predicate verifies all ten terminal logs,
checkpoint hashes, fixed-solute invariance and all **40 mobile-solute frames**.
All **294 sugar stereo sentinels** pass; no severe heavy clashes or ring piercings.
Final bond ratios **0.96418–1.05127**, base displacement **1.66358 Å** and conservative
image clearance **43.91559 Å** pass the unchanged gates. The welded counterpart
already passed its corresponding replay. Neither finite minimization establishes
stationarity, a local minimum, thermal equilibration or production readiness.

Launched `formation-pme-qualification-v1` at **11:12:21 Denver**: four sequential
native `run 0` evaluations, welded/control final checkpoints each evaluated with
GPU offload/CPU bonded terms and GPU-resident mode. The comparison uses the
existing full-system tolerance `max(0.001, 1e-4*reference magnitude)` for energy
and maximum force component. This is a same-coordinate native mode comparison,
**not an independent all-CPU or cross-engine reference**; no dynamics are run.
Any failure stops progression and preserves its outputs. No tolerance relaxation.

Four CPUs, GPU, **8 GiB/no swap**, 300-second per-evaluation timeout, **20-minute
total bound**. Completion/failure watcher `dd45f221-5cd1-4cef-88cc-005ff003afd1`
is armed; review **11:30:21**, hard stop **11:32:21 Denver**. Event-driven follow-up,
no periodic polling, no duplicate jobs, no cloud spending. Bulk outputs stay on Archive.
Next: audit the numerical comparison, then prepare bounded matched solvent startup
and restart qualification. Provisional parameter limitations and the old 1×T hold
remain; no application or production promotion.
Current handoff: `current_handoff.json` → `formation-pme-qualification-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_matched_conditioning_20261014.json`.

The following entries are retained history, superseded by the current state above.

**Welded solvent conditioning audited; matched control launched — 2026-10-14 Denver.**
Acknowledged token `bae35099-9d0d-4c95-a9f7-246c10e8d01c` after native completion.
The welded pilot completed **2,500 minimization steps, zero MD, in 65.44 seconds**.
A separate replay verified all ten native terminal logs, checkpoint hashes and
coordinates, exact solute invariance during the first two segments, and all
**40 mobile-solute trajectory frames** using the frozen geometry predicate.
Final geometry retains **298 stereo sentinels**, zero severe heavy clashes or
ring piercings, bond ratios **0.93762–1.07436**, maximum lesion-base displacement
**2.70071 Å**, and conservative periodic-image clearance **43.89163 Å**.
Both final segments are unrestrained. These checks establish finite solvent
conditioning success; they do **not** establish stationarity, a local minimum,
thermal equilibration or production readiness. Parameter-transfer limitations
and all prior failed branches remain preserved.

The matched unwelded control began **11:10:09 Denver**, using the same ten
250-step stages and geometry thresholds (294 sugar stereo sentinels; no CPD
core centers). Four CPUs/GPU offload, 8 GiB, no swap, 300-second segment limit;
**20-minute total bound**, review **11:28:09**, hard stop **11:30:09**. The shorter
budget follows the measured welded runtime. Completion/failure watcher
`fa4ed815-9d0f-40d2-b399-135859779371` is armed. No periodic polling, duplicate
jobs, new QM, cloud spending or production launch. All bulk files stay on Archive.

Next: audit control evidence, then conditioned native PME/GPU numerical agreement
and bounded startup/restart qualification, one admitted job at a time. The old
1×T ensemble hold remains in place; this is the authorized new compatible context.
Current handoff: `current_handoff.json` →
`formation-solvent-minimize-control-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_solvent_minimization_20261014.json`.

The following entry records the preceding transition and is superseded above.

**Stationary 1×T placement rejected on displacement; formation-compatible solvent pilot active — 2026-10-14 Denver.**
Acknowledged completion token `cd4f6ed7-aacd-49d3-95ed-aa6c0d0cafac`.
V6 stopped early after **1,589 iterations / 1,651 force evaluations / 833.73 s**.
Independent force replay confirms **0.00971452 kcal/mol/Å** on the 322 mobile
atoms. All 292 stereo sentinels, bond ratios **0.96112–1.05830**, clashes/piercings
and fixed-coordinate checks pass. Conditioned full-DNA NAMD equivalence passes:
energy error **0.02511 kcal/mol**, force error **0.002372 kcal/mol/Å** under the
existing engineering policy. This is fixed-outer stationarity, not a minimum.

**A separate structural gate fails:** maximum lesion-base displacement is
**15.0073 Å** from the minimized unwelded control, versus the existing **3.5 Å**
screen. The initially grafted v3/v4 seeds already required 8.65/9.37 Å; subsequent
unsolvated relaxation increased the displacement. Native numerical agreement
and low local force do not qualify this placement. Preserve the entire branch;
no further vacuum relaxation, solvent promotion or application integration of
that 1×T endpoint. The source site was inherited from the old 1×T route, not
selected for corrected cis-anti-I precursor compatibility.

A read-only audit of existing corrected formation screens identified exactly
**seven compatible intended-weld samples** in the smaller 2HB-2×T job
`029a76c6a59f`, pair **D000:9~D001:15**. Their screened-base rigid-placement maximum
displacements are 1.22–1.76 Å. Selected the smallest displacement deterministically:
**sample180, DCD frame45225, time904520.0027 ps**. One full frame was read by direct
DCD seek, checked against cached coordinates and file size/mtime. No trajectory
was generated or multi-GB file copied. This selects a conditional engineering
context, not an unbiased population, reaction rate or formation yield.

Built fresh **3,107-atom / 98-residue** paired DNA fixtures from the archived
ordinary-mass PSF, adding only the corrected crosslinks and base assignments.
The new placement moves all lesion-base atoms by at most **2.65353 Å**; all
**298** stereo sentinels pass, there are no severe clashes or ring piercings,
and initial bond ratios are **0.91880–1.28732**. Parameter coverage passes.
The original full PSF had only solute-length zero NNB pointers; psfgen rejected
it. That failed attempt is preserved. A local copy pads the zero-exclusion
pointer table to the full atom count; atom/bond/parameter records are unchanged.
No archived source was modified. Source trajectory HMR4fs/magnesium conditions
are disclosed; only precursor geometry is reused, not its masses or solvent model.

Prepared matched **140 Å cubic**, ordinary-mass CHARMM TIP3P/NaCl systems:
**265,508 atoms**, **87,270 waters**, **343 Na / 248 Cl** (95 neutralizing Na,
248 added pairs ≈150mM in the initial box). Common solvent excludes both solutes;
independent binary comparison confirms identical solvent coordinates. Existing
empty-cube oxygen packing was reused with reconstructed TIP3P geometry, without
new Gromacs work. Actual post-equilibration concentration remains to be measured.

**Welded solvent-minimization pilot launched 11:04:03 Denver**, one native job:
500 steps with solute fixed, 1,000 with heavy-atom restraint coefficient5, 500 at1,
and 500 unrestrained — **2,500 minimization steps, zero MD**. Every250-step endpoint
and each50-step mobile-solute frame must retain stereo, bond ratios0.7–1.3,
no severe clashes/piercings, base displacement≤3.5 Å and image clearance≥12 Å.
Fixed-solute stages instead verify exact solute invariance. No stationary/minimum
claim follows from completing this finite pilot.

Four CPUs with GPU offload, **8 GiB/no swap**, 600-second native segment timeout,
**one-hour hard cap**. Completion/failure watcher
**bae35099-9d0d-4c95-a9f7-246c10e8d01c** is armed; one review **11:59:03**, hard stop
**12:04:03 Denver**. Actual first native segment completed normally during the
single startup verification. No periodic polling. Next audit decides matched
control conditioning and native PME/GPU/startup/restart qualification; no automatic
MD or production promotion. No new QM, parameter fit, cloud spending or deletion.

Current handoff: `current_handoff.json` → `formation-solvent-minimize-anti-v1/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_formation_context_20261014.json`.
All failures and superseded active-state records below remain preserved.

**Feasible relaxation made progress; bounded continuation active — 2026-10-14 Denver.**
Acknowledged failed wake `573c5e33-41ea-46a7-b42c-c685c40fd570`.
This terminal status means the **1,500-iteration cap** was reached, not a geometry
failure: 1,514 force evaluations, **775.47 seconds**, no stereo/contact rejection,
all **292** stereo sentinels intact, zero severe clashes/piercings, unchanged
fixed atoms, and bond ratios **0.96112–1.05548**. The minimum oriented volume is
7.7908 Å³, far from the 0.1 path boundary. The failed verdict remains preserved.

Energy decreased **14,747.016 kcal/mol** from the strained seed. It continued to
fall by **12.656 kcal/mol in the final 250 iterations**. Independent Reference
re-evaluation reproduces final energy **43,849.094427 kcal/mol** and maximum
mobile force **4.661775 kcal/mol/Å** exactly. The best transient maximum force was
0.7090; neither meets the unchanged **0.01** acceptance threshold. The largest
remaining forces are on nearby ordinary bases, not evidence of a new core
chemistry failure. This is useful conditioning progress, not stationarity.

Admitted **dna-placement-v6** from the exact valid final coordinates, retaining
the force field, 322 mobile atoms, fixed outer DNA, 0.05 Å step cap, Armijo descent
and pre-acceptance geometry guards. Allocation: **6,000 iterations / 9,000 force
evaluations or two hours**, whichever stops first. The stopping target is now
exactly the existing **0.01** acceptance threshold; v5 unnecessarily targeted
0.001 internally. This does not relax the acceptance criterion. No fresh seed,
QM, fitting or native dynamics was launched. L-BFGS memory restarts; no optimizer
history preservation is claimed. The new seed gradient finite-difference check
passes with **2.54e-5** error. Earlier focused solver tests cover the unchanged
algorithm; this continuation changes checkpoint, budget and stopping target only.

Started **10:39:23 Denver**, one CPU, 4 GiB/no swap. Completion/failure watcher
**cd4f6ed7-aacd-49d3-95ed-aa6c0d0cafac** is armed; one review **12:34:23**, hard stop
**12:39:23 Denver**. Startup and force preflight verified; no periodic polling.
At completion audit actual force and geometry, retain application displacement
screens separately, then conditioned native parity and matched solvent/restart
validation. Parameter qualification and minimum certification remain incomplete.
All outputs stay on Archive; no cloud spending or data deletion.

Current handoff: `current_handoff.json` → `dna-placement-v6/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_dna_continuation_20261014.json`.
Earlier active-state descriptions below are historical snapshots.

**SLSQP path failure audited; feasible-step recovery active — 2026-10-14 Denver.**
Acknowledged failed wake `b4885ed6-a80c-4ea2-9234-dfb8c310fa37`.
The v4 job stopped in less than one second, after **four energy/gradient calls
and two callback iterates**. Its second iterate moved atoms by up to **3.7034 Å**
and inverted two sugar sentinels (oriented volumes **−0.8749 / −1.9987 Å³**).
The stop guard worked; nonlinear constraints did not keep that intermediate
SLSQP iterate feasible. The file named `last_accepted.npy` contains the failing
iterate and **must not be used as a valid restart**. Original outputs, traceback,
service status and an explicit failure-geometry audit remain preserved.

Restarted from the unchanged, screened v4 seed under **dna-placement-v5**.
No parameters, atoms, mobile region, final force criterion or chemistry threshold
changed. The revised L-BFGS line search caps every per-atom trial displacement at
**0.05 Å**, requires Armijo energy descent and checks all 292 oriented stereo
volumes (>0.1 Å³), severe heavy contacts and ring piercing **before** force
evaluation/acceptance. Failed line search stops for audit instead of extending
blindly. Checkpoints contain only feasible accepted geometries. Double-precision
OpenMM Reference forces avoid CPU precision noise; seed directional finite
differences agree to **4.37e-5 kcal/mol/Å**. These are coordinate-construction
checks, not an endpoint or full-DNA minimum certificate.

Two focused solver tests passed: an independent anisotropic quadratic checks
convergence, energy descent and the displacement cap; an infeasible-boundary
test proves no energy call crosses the allowed region and no false convergence
is reported. No broader regression suite was run.

**Started 10:24:52 Denver.** One CPU, 4 GiB/no swap, 1,500 iterations or 6,000
energy/gradient calls, **two hours hard limit** with early convergence/stall stops.
Completion/failure watcher **573c5e33-41ea-46a7-b42c-c685c40fd570** is armed;
one review **12:19:52**, hard stop **12:24:52 Denver**. Startup limits and the
actual force preflight were verified. No periodic polling. At termination,
audit actual force/geometry and fixed coordinates, report existing application
displacement screens separately, then advance to conditioned static parity and
matched solvent startup only if warranted. No QM, fit, cloud spending or deletion.

Current handoff: `current_handoff.json` → `dna-placement-v5/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_dna_feasible_recovery_20261014.json`.
Earlier active-state descriptions below are superseded historical records.

**Corrected two-sugar/DNA transfer passed; local construction active — 2026-10-14 Denver.**
The user authorized continuing through parity with the other developed isomers.
This means the preliminary-research NAMD workflow and its actual evidence gates;
it does not authorize relabeling legacy anti trajectories or automatic registry
promotion. Parameter-accuracy limits remain visible throughout.

Built a fresh **62-atom, two-sugar corrected cis-anti-I model** with ten retained
stereocenters. Exact frozen core charge/equilibrium corrections transfer without
another fit; the second sugar uses the same native NA atom-role assignments.
The neutral N1 methyl cap is removed explicitly, and both sugars carry neutral
3′/5′ OH caps. Parameter coverage is complete. OpenMM export/reload errors are
below 7e-13 kcal/mol and 2e-13 kcal/mol/Å; native static errors **0.0008965
kcal/mol / 0.0004862 kcal/mol/Å** pass the existing 0.001 limits. The first build
failed on the CCD's phosphate atom; the versioned retry explicitly prunes atoms
outside the capped fragment, following the established endpoint graph procedure.

Transferred the candidate to the frozen **3,043-atom, 96-residue, three-segment**
origami topology: exactly the corrected C5–C6/C6–C5 crosslinks, two removed C5
planar impropers, 28 reassigned base atoms, unchanged **−93e net charge**, and
unchanged nonlesion atoms/bonds and native sugar/phosphate parameters. Complete
parameter coverage includes the explicit 1–4 NBFIX coefficients. An unused
ParmEd import failed before construction; its journal is preserved separately.

Coordinate preparation rejected a base-only graft for sugar stereochemistry
and clashes. Whole-nucleoside grafts retained stereochemistry but had clashes,
including a **0.206 Å H3–H5″ contact** missed by the heavy-atom screen. Static
OpenMM/NAMD checks at these extreme-overlap geometries failed and remain
preserved. No threshold was relaxed. The source was changed from unminimized
to previously minimized **unwelded control** coordinates, and one bounded,
six-degree-of-freedom rigid placement search used all-atom clash penalties and
backbone attachments. This is geometric construction, not QM or an MM minimum.
The selected seed has **all 292 monitored stereocenters preserved, zero severe
heavy-atom clashes and zero detected ring piercings**. The control source's
historical product-displacement-screen failure remains documented; no source
production qualification is implied.

Full-DNA static equivalence now passes the existing relative/absolute engine
policy: energy error **0.018995 kcal/mol** and maximum force error **0.044343
kcal/mol/Å**. This seed is strained: maximum reference force **2535.96
kcal/mol/Å**. Native agreement is an implementation check, not permission to
start dynamics at those forces. Final conditioned geometry must be checked again.

**Local relaxation launched 10:20:34 Denver**, `dna-placement-v4-service`:
322 mobile atoms within two residues of each lesion endpoint; outer coordinates
fixed. SLSQP uses analytic signed-volume constraints, then L-BFGS-B removes
those temporary constraints if the constrained stage passes. Limits: 1,000
constrained iterations, 1,500 release iterations, 6,000 energy/gradient calls,
**two hours total**, two CPUs, **4 GiB/no swap**. Accepted inversion or detected
ring piercing stops the attempt; checkpoints every 25 accepted iterations.
Final audit requires the unchanged 0.01 kcal/mol/Å mobile-force threshold,
0.7–1.3 bond-ratio screen and geometry integrity. Optimizer success alone is
insufficient, and no minimum certificate is claimed.

Completion/failure watcher **b4885ed6-a80c-4ea2-9234-dfb8c310fa37** is armed.
One review trigger **12:15:34**, hard stop **12:20:34 Denver**. Startup verified
worker execution and systemd limits; no periodic polling. Next audit must also
report base displacement/glycosidic attachment metrics against the existing
application placement screens, separately from isolated construction; no
silent application geometry promotion. Then prepare matched solvent systems,
qualify startup/restarts and undertake sequential bounded context validation.
No new QM, fit round, cloud spending, data deletion or relocation.

Focused validation: **2 chirality-derivative tests and 6 native-log tests passed**.
The initial combined test command was rejected by the single-target wrapper;
both files were subsequently run separately through `just test-focused`.
Current handoff: `current_handoff.json` → `dna-placement-v4/handoff.json`.
Audit: `docs/audits/cpd_corrected_cis_anti_i_dna_transfer_20261014.json`.
All preceding failures and their native outputs remain on Archive.

**Restart smoke recovered and complete — 2026-10-14 Denver.**
Acknowledged failure token `2926a2a7-c4df-4019-94b7-823fb7d9ba08` and resumed
on the user's instruction. The first native chunk had finished normally at
step 5500; its audit failed because RDKit rejected NumPy float32 coordinates
from DCD. A separately versioned worker promotes those recorded values to
float64, preserving all geometry thresholds and the original failure evidence.
All 55 first-chunk frames passed before reusing its exact binary checkpoint.
Only the remaining 5000 steps were run, under a one-CPU, 4 GiB/no-swap,
10-minute hard limit; native execution took 1.38 seconds.

The second native chunk also finished normally, at step 10500. Its initial
audit encountered restart ENERGY rows before the first ETITLE header. Reusing
the existing `native_log_v3` completed-log parser resolved this without more
simulation. The separate final audit passes **all 105 recorded frames**, both
final geometries, finite coordinates/velocities/energies, exact checkpoint
references and restart potential continuity: **0.0002 kcal/mol**, below the
unchanged 0.001 limit. Total dynamics remains **10 ps**, plus 500 minimization
steps; the 55 first-chunk frames include minimization frames. Both failed audit
attempts and all native outputs remain preserved. No QM or fitting was added.

This closes isolated endpoint integration/restart engineering only. It does
not establish parameter accuracy, DNA thermal behavior or an endpoint minimum.
The 7.15616 kcal/mol QM/MM conformer discrepancy remains unresolved.

The next DNA-context transfer inventory/plan is recorded under
`dna-context-transfer-preparation-v1/plan.json`. The verified export contains
one sugar and an N1 methyl cap, with no second sugar or phosphate: it cannot
be inserted directly as a full DNA patch. Next work must explicitly map the
corrected two-sugar topology, cap removal, charges and boundary parameters,
then check geometry and static engine equivalence before DNA dynamics. Legacy
anti fitted patches and trajectories are not corrected cis-anti-I evidence.
No automatic extra vacuum sampling, QM grid or second fit is scheduled.

**No native job or pending wake is active.** Current handoff:
`current_handoff.json` → `provisional-native-restart-smoke-audit-v3/handoff.json`.
Completion audit: `provisional-native-restart-smoke-audit-v3/completion_audit.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_native_restart_recovery_20261014.json`.
All new outputs and scratch remain on Archive; no cloud spending, no deletion
or relocation of existing data. Earlier entries below are historical snapshots.

**Alternate endpoint stationary; provisional NAMD export verified — 2026-10-14 Denver.**
Acknowledged completion token `dcf69bad-3abf-4037-9fd5-1ec816a09a77`.
Independent native/hash/trajectory/chemistry replay passes for all **five accepted
states**, including the reused checkpoint. The continuation stopped after
**four new gradients and 12.54 service minutes**. Both native optimizer and
independent single-chi stationarity pass: maximum projected atom gradient
**1.41843e-5 au**, RMS **4.87100e-6 au**, below the unchanged **1.5e-5 / 1e-5 au**
limits. All seven stereocenters remain intact. The alternate endpoint is
**2.72472 kcal/mol below** the original stationary same-chi reference. This is
an electronic-energy comparison, not a free energy or endpoint minimum
certificate. Stop this QM optimization; the unused 26-gradient allowance is
not a reason to continue. Uphill steps and earlier failures remain preserved.

The final candidate review uses only **two new static MM evaluations**, reusing
the four unchanged original/historical evaluations. The round-one candidate
favors the alternate geometry by **9.88087 kcal/mol**, an excess of **7.15616
kcal/mol** versus QM. Its remaining squared gradient residual is **50.33% on
base/methyl atoms and 49.67% on sugar/OH atoms**. Another core-only correction
cannot resolve the whole discrepancy. Keep the parameters provisional; no
second fit, new QM grid or endpoint Hessian is admitted by this result.

Advanced the independent engineering work: exported isolated **36-atom core and
49-atom endpoint** fixtures with full-precision charges, unique atom-role types,
bond/angle corrections and explicit 1–4 nonbonded parameters. OpenMM reloads
of the PSF/parameter exports match the original candidate to **2.5e-13 kcal/mol
in energy and 1.8e-13 kcal/mol/Å in force** at the three existing QM geometries.
Three native NAMD `run 0` checks pass the existing **0.001 kcal/mol and
0.001 kcal/mol/Å** engineering limits; worst observed errors are **0.0007001**
and **0.0006686**, respectively. No QM, minimization, dynamics or fitting was
needed for these checks. An initial exporter attempt failed on an OpenMM
Improper-object API assumption before any native call; v1 and its partial
files remain preserved. V2 reads the named atom fields and passes. These are
isolated fixture exports, not a full DNA patch or qualified production model.

**Next bounded job launched at 01:09:54 Denver:**
`provisional-native-restart-smoke-v1`, one unrestrained capped endpoint at 300 K,
500 minimization steps followed by **two 5 ps chunks at 1 fs**. Each chunk saves
native checkpoints and audits all recorded frames, stereocenters and endpoint
geometry before proceeding. The second chunk reuses binary coordinates,
velocities and timestep, with an explicitly declared new Langevin seed; no
bitwise stochastic-continuity claim. Restart potential must agree within the
existing 0.001 kcal/mol numerical limit. This tests integration/restart behavior
only, not DNA thermal stability, parameter accuracy or minimum certification.

One CPU, **4 GiB service cap/no swap**, 240-second native timeout per chunk and
**10-minute total hard limit**. Startup verified the resource limits and armed
completion/failure watcher `2926a2a7-c4df-4019-94b7-823fb7d9ba08`. Single review
trigger **01:18:54**, hard stop **01:19:54 Denver**. No periodic polling or
automatic extension of vacuum sampling. Archive-only output/scratch; no cloud.

Audits: `alternate-sugar-qm-release-v3/completion_audit.json`,
`stationary_candidate_review.json`, and `provisional-native-export-v2/completion_audit.json`.
Current handoff: `current_handoff.json` → `provisional-native-restart-smoke-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_stationary_native_export_20261014.json`.

**Resumed: alternate-sugar core release running — 2026-10-14 Denver.**
The user's resume instruction authorizes continuing the existing target. Memory
headroom is restored: **23.37 GiB available at admission**, above the unchanged
12 GiB requirement. One native calculation is running under
`alternate-sugar-qm-release-v3`, from the exact accepted release-v1 checkpoint.

The first resume attempt safely failed before service creation because a shared
helper's source hash had changed. The only difference in
`corrected_mm_endpoint_profile.py` was splitting two semicolon-separated
statements onto separate lines. Full-module Python AST comparison is identical.
The original source, current source, diff and failed attempt are preserved. A new
v3 manifest records the reviewed hash in both optimizer and native-gradient
source lists; previous manifests remain unchanged. The optimizer run code,
native evaluator, scientific settings, seed coordinates/gradient and allocation
are unchanged. Both native contexts and the checkpoint force calculation pass
preflight without acquiring new QM data. The separate repaired launcher retains
the service-identifier guard and all original resource checks.

Started **00:37:18 Denver**. Startup verification confirms the original chi
target **105.65946347935468°**, no fixed Cartesian atoms, the expected constraint
rank, and **four CPUs / 4 GiB Psi4 / 8 GiB service / no swap**. Allocation remains
**30 new gradients or two hours maximum**, with a 600-second per-gradient timeout
and immediate stop at convergence. Full-allocation estimate: **02:24:47**;
single review trigger: **02:32:18**; hard stop: **02:37:18**, all October 14 Denver.
Completion/failure watcher token `dcf69bad-3abf-4037-9fd5-1ec816a09a77` is armed.
No periodic polling or further admission retry timer is running.

At the next trigger, audit actual accepted native evidence and single-chi
stationarity before deciding the smallest useful parameter-candidate correction.
No new angular grid, endpoint Hessian or fit round is automatically admitted.
The endpoint remains uncertified as a minimum and the combined candidate remains
provisional. All output/scratch stays on mounted Archive; no cloud spending.

Current handoff: `current_handoff.json` →
`alternate-sugar-qm-release-v3/active_handoff.json`.
Source review and startup evidence: `source_revision_review.json` and
`launch_verification.json` in that job directory.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_resume_20261014.json`.

**Admission helper misidentified as a calculation; ready pending RAM — 2026-10-11 Denver.**
Acknowledged failed wake `677f42af-107e-4e3e-a31d-33d2b58c8ae4`.
The single timed attempt failed at the exclusive-job check, **before the memory
check or native launch**. The old guard searched entire `systemctl` rows.
The admission helper's default Description contained its `cpd-` Archive path,
so it matched its own helper as an active calculation. The preserved systemd
journal confirms this description; the traceback identifies the guard. No
QM service, launch receipt or new gradient was created. This is an admission
software failure, not an optimizer failure or new scientific result.

Prepared a separate pinned `alternate-sugar-qm-release-v2/repaired_launcher.py`
that checks **service identifiers only**, exempts watcher service identifiers,
and still rejects real CPD/native jobs. Six focused tests pass, including the
observed description false positive, real jobs whose descriptions contain
`-watch`, and unchanged resource boundaries. The original optimizer worker,
scientific plan, checkpoint, tolerances, 30-gradient/two-hour allocation and
resource limits remain unchanged. Historical sources/failures are preserved.

The one diagnostic snapshot found **11.235 GiB available RAM**, below the
unchanged **12 GiB** requirement, with about **0.97 MiB swap free**. No native
calculation was active. The admission timer is consumed; **no further retry
is armed and no periodic polling is running**. Restore memory headroom before
one reviewed resume using the repaired launcher. No user application was
terminated and no admission threshold was lowered. Archive storage and zero
cloud spending remain in force.

Current handoff: `current_handoff.json` →
`alternate-sugar-qm-release-v2/resource_wait_handoff.json`, with the exact resume
command and required startup verification. Failure audit:
`alternate-sugar-qm-release-v2-deferred-admission/failure_audit.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_admission_repair_20261011.json`.

**Released-core audit and consolidated candidate decision — 2026-10-11 Denver.**
Acknowledged completion token `29f7da0c-7627-492a-ae9d-703632ba9b59`.
All **13 evaluated/accepted states**, including the reused seed, pass independent
native/hash/chemistry checks. The **12 new gradients took 42.38 service minutes**;
the service reached its allocation boundary, not convergence. Maximum projected
atom gradient fell **149.55-fold**, including **85.14% over the last five states**,
to **4.26812e-5 au**; RMS is **1.68094e-5 au**. These remain **2.85 and 1.68 times**
the unchanged stationarity thresholds. Energy is **2.72468 kcal/mol below** the
original same-chi QM reference. The seven stereocenters remain intact. Uphill
trials and all prior failures are retained. No endpoint minimum is certified.

The requested consolidated review uses **six static MM evaluations** of existing
geometries, with no additional QM or relaxation. The historical relaxed parent
MM geometry is closer to the alternate QM geometry: heavy-atom RMSD **0.45325 →
0.21816 Å**, maximum heavy-atom proper-torsion difference **128.42 → 18.70°**.
These descriptors support the relevance of the alternate conformation; they
do not prove common basins or global minima. At the two QM geometries, the first
core-bonded candidate favors the alternate by **9.87875 kcal/mol**, versus QM's
**2.72468 kcal/mol**, leaving **7.15407 kcal/mol** excess stabilization. The
alternate QM point is not yet stationary. Endpoint gradient-component RMSE
improves only **8.0515 → 7.3555 kcal/mol/Å** between these geometries. The combined
candidate remains provisional; core-only equilibrium fitting barely changes
the conformer-energy discrepancy. Preserve the existing ring/charge-transfer
limitations and prospective holdouts.

This review admits completion of **this same alternate zero-offset target**:
`alternate-sugar-qm-release-v2`, exact accepted coordinates/gradient reused,
unchanged electronic method and single chi constraint, **30 new gradients or
two hours maximum**, stopping immediately at convergence. Four CPUs, 4 GiB
Psi4/8 GiB service, no swap, 600-second native timeout; expected full-allocation
cost **107.48 minutes**. Native preflight passes. This implements the larger
routine allocation from the big-picture audit without expanding scientific scope.
No additional angular grid, endpoint Hessian or second fit has been admitted.

**Queued, not running:** the direct launch failed before service creation because
available RAM was **11.876 GiB**, below the unchanged **12 GiB** admission guard.
The exception and resource snapshot are preserved. One admission timer is armed
for approximately **22:05:32 Denver** (`nadoc-alternate-release-v2-admit.timer`).
It attempts launch once; persistent resource failure generates a wake and requires
review instead of repeated retries. On admission, the native watcher handles
completion/failure and one **115-minute review deadline**, with a **two-hour hard
stop**. Five focused tests pass, covering failure notification, cancellation,
campaign pause scope and startup verification. No periodic polling or user-process
termination. All large files/scratch remain on Archive; no cloud spending.

Audit and comparison: `alternate-sugar-qm-release-v1/completion_audit.json` and
`consolidated_candidate_review.json`. Current handoff: `current_handoff.json` →
`alternate-sugar-qm-release-v2/queued_handoff.json`; the timer promotes the pointer
to `active_handoff.json` only after verifying native startup and watcher arming.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_consolidated_review_20261011.json`.

**Big-picture audit: useful progress, but tighten the route to NAMD — 2026-10-11 Denver.**
The user requested a campaign-level review of repeated 12-gradient chunks.
The corrected-isomer campaign has **35 finished service attempts totaling
16.64 wall hours**, excluding the active release job and preparation/audit time.
The glycosidic profile accounts for **9.05 hours**, corrected-core reference and
curvature work **4.30 hours**, and initial endpoint work **1.77 hours**. The five
failed services account for **11.75 minutes**. Failures are preserved; these
totals are not CPU-hours, calendar duration or the entire legacy campaign.

Recent work is productive: the alternate-sugar pilot plus fixed-core relaxation
used **16 distinct gradients and 55.01 service minutes** and reached constrained
stationarity at a geometry **2.433 kcal/mol below** the original QM reference.
It remains close to the MM alternative, so enforcing the original geometry
alone would be unjustified. At the user-requested snapshot, the released-core
job had seven completed new gradients and an eighth running. Independent native
replay confirms **40.48-fold** maximum projected-force reduction, another
**0.2896 kcal/mol** energy decrease and intact chemistry. Its maximum force
still exceeds the criterion by **10.51-fold**; this is progress, not convergence.
No later live-status samples were taken for this review.

The production bottleneck is the combined parameter candidate and its transfer
to DNA context. The corrected core minimum and planned reference inventories
exist; first charge/bonded candidates are provisional, the bonded improvement
is partial, and prospective qualification/NAMD context checks remain incomplete.
Chunk completion has been communicated more prominently than these milestones.

**Operating decisions for subsequent manifests:** finish/audit the current
admitted job, then consolidate existing original/alternate QM and MM geometry,
force, energy and target residuals into one candidate decision. Further QM must
identify the unresolved decision and the smallest acquisition that could change
it. Do not automatically add endpoint Hessians, rotamer searches, angular grids
or fit rounds after a service completes. Keep scoped minimum/stationarity claims
and existing evidence gates intact.

The **12-gradient limit is an operational choice**, not a scientific requirement
or the user's time ceiling. For established optimization methods, future manifests
should normally allow about **two hours (~30 gradients at measured cost)** within
the stage budget and 15-hour service ceiling, with early convergence stops and
native timeouts. Current restarts retain geometry/gradient but discard Sella
history; account for this overhead and only preserve history through a validated
restart mechanism. Small pilots remain appropriate when methods change.
The active immutable allocation and its triggers remain unchanged.

Prepare/check provisional NAMD topology and full-precision exports where existing
dependencies permit, while keeping engineering checks distinct from physical
qualification. Prioritize the intended preliminary welded/unwelded stability
scope and representative DNA context; exhaustive capped-sugar conformer searches
and absolute melting-temperature validation are not silently added prerequisites.
This review launches no new computation and changes no acceptance verdicts.

Audit: `big-picture-audit-20261011/review.json`, with native snapshot evidence.
Current handoff: `current_handoff.json` → `big-picture-audit-20261011/handoff.json`,
which preserves the active release-job handoff and adds these management decisions.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_big_picture_20261011.json`.

**Alternate sugar stationary with fixed core; matched-angle core release running — 2026-10-11 Denver.**
Acknowledged completion token `726a3d20-4cc5-4bd1-98fe-ee22d44be1f1`.
Independent native replay verifies **three new gradients and four accepted
states**, including the reused checkpoint. Both Sella and the independent
fixed-core/chi stationarity checks pass: maximum free projected atom gradient
**1.03312e-5 au**, RMS over the 17 free atoms **5.81052e-6 au**, below the unchanged
**1.5e-5 / 1e-5 au** limits. Total service time was **10.32 minutes**. Stop this
completed fixed-core optimization; its unused nine-gradient allowance is not
a reason to keep running. No curvature or full endpoint minimum is certified.

Final energy is **−1364.542104729633 Eh**, **2.43303 kcal/mol below** the original
central QM conformer. The latest chunk changes energy by only **+1.58e-6
kcal/mol** overall; its small uphill steps remain preserved. Heavy-atom RMSD
from the original conformer is **0.34872 Å**, and the exocyclic sugar torsion
remains **46.753°**. These are results for the explicitly fixed-core problem.

The same saved native gradient, projected with **only chi constrained**, gives
maximum atom gradient **0.00638305 au (7.56915 kcal/mol/Å)** and RMS
**0.00143671 au**. The maximum is **425.5 times** the stationarity limit, with
largest remaining gradients at 1:C2, 2:C4 and 1:O2. By comparison, the original
QM reference passes the single-chi criterion. Thus fixed-core convergence does
not yet permit a stationary comparison under the original endpoint constraints.
No new QM evaluation was needed to establish this distinction.

`alternate-sugar-qm-release-v1` admits one zero-offset matched-angle diagnostic:
release all 32 previously fixed core/methyl atoms, let all **49 atoms** move,
and retain the exact original chi target **105.65946347935468°**. Reuse the last
accepted geometry and full-precision gradient with fresh Sella order-0/internal
history. The electronic method, basis and all SCF/response settings are unchanged.
Four focused tests passed for released-force accounting, constraint scope and
invalid geometry. Native preflight confirms one independent constraint and
agreement with the independent projector within **2.55e-13 au**, without QM work.

Launched **21:01:58 Denver**. The single startup observation verified gradient
reuse, no fixed Cartesian atoms, the original chi target and first new native
DF-SCF calculation with 449 orbital functions. Allocation is **12 new gradients
maximum, 600 seconds per gradient, one hour total**; **four CPUs, 4 GiB Psi4 /
8 GiB service memory, no swap**. Expected finish is approximately **21:45:03**;
audit trigger **21:51:58**, hard stop **22:01:58**. Completion/failure watcher
`29f7da0c-7627-492a-ae9d-703632ba9b59` is armed. No periodic polling.

Next: audit native evidence and all-49-atom single-chi stationarity, then assess
relative energy and core/sugar/OH correspondence. Stop optimization when those
criteria pass; stationarity still does not certify curvature or global basin
closure. A further angular profile needs separate preregistration. Original
references, failures and audit verdicts remain preserved. The second bonded-fit
round and prospective holdouts remain untouched. All output and scratch are on
mounted Archive; no cloud spending or existing-data move/delete.

Audit: `alternate-sugar-qm-closure-v2/completion_audit.json`.
Stage decision: `alternate-sugar-qm-closure-v2/stage_transition_review.json`.
Current handoff: `current_handoff.json` → `alternate-sugar-qm-release-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_alternate_core_release_20261011.json`.

**Alternate-sugar QM chunk audited; continuation running — 2026-10-11 Denver.**
Acknowledged completion token `85f479a2-72de-45b7-ade2-83d5ff25bebb`.
The first chunk reached its **12-new-gradient allocation**, with service exit 0
and **optimizer convergence false**. Independent replay verifies all **13 native
evaluations and accepted states**, including the reused pilot, against full
precision geometry/gradient files, ASE trajectory and Sella energy log.
All original electronic settings, basis evidence, seven stereocenters and
fixed-core/chi requirements pass. The early uphill step is retained; the
trajectory is not described as uniformly downhill.

The last accepted energy is **−1364.5421047321433 Eh**, **2.43304 kcal/mol below**
the original central QM reference and **3.61168 kcal/mol below** the alternate
starting point. Maximum free projected atom gradient fell **380.8-fold**, to
**5.80807e-5 au (0.068873 kcal/mol/Å)**; free-atom RMS is **2.38775e-5 au**.
These still exceed the respective **1.5e-5 / 1e-5 au** stationarity limits.
The last five states show a further **74.84% force reduction**, with mean native
cost **206.33 seconds/gradient**, maximum **217.45 seconds**. Total service time
was **41.44 minutes**. Progress supports one further bounded chunk.

The relaxed geometry remains close to the alternate MM seed: heavy-atom RMSD
**0.04886 Å**, versus **0.34866 Å** from the original QM conformer. The exocyclic
sugar torsion is **46.754°**. This lower observed QM energy supports investigating
the alternate conformation rather than enforcing correspondence to the original
reference. It is not a converged relative basin energy, minimum certificate,
barrier or full basin-closure result. Maximum evaluated fixed-coordinate drift
was **1.27e-8 Å** and chi error **1.60e-6°**, within unchanged limits.

`alternate-sugar-qm-closure-v2` reuses the exact last accepted native geometry
and full-precision gradient with fresh Sella history. The original 32 fixed
reference targets and exact chi target are retained, without snapping the
restart coordinates or resetting targets to their small solver residuals.
Preflight independently verifies the 97-constraint projection within
**9.44e-14 au**. The inherited worker changes only its service name and the
reuse-reporting label. A preparation path check initially addressed the not-yet
created output directory; its failed source/report are preserved under
`alternate-sugar-qm-closure-v2-preparation-failure`. Checking the mounted existing
parent repaired the setup before any calculation was launched.

Launched **20:46:52 Denver**. The single startup observation verifies reuse of
the prior gradient, its accepted checkpoint, and the first new native DF-SCF
calculation with 449 orbital functions. Allocation remains **12 new gradients
maximum, 600 seconds per gradient, one hour total**, using **four CPUs,
4 GiB Psi4 / 8 GiB service memory, no swap**. Expected finish is approximately
**21:30:09**; audit trigger **21:36:52**, hard stop **21:46:52**. Completion/failure
watcher `726a3d20-4cc5-4bd1-98fe-ee22d44be1f1` is armed. No periodic polling.

Next: replay native and accepted-state evidence, assess stationarity and
conformer correspondence, and stop further optimization once the audited force
criteria pass. Any curvature work or further continuation requires a separate
evidence-based admission. The second bonded-fit round and prospective holdouts
remain untouched. All bulk output and scratch are on mounted Archive; no cloud
spending or existing-data move/delete.

Audit: `alternate-sugar-qm-closure-v1/completion_audit.json`.
Current handoff: `current_handoff.json` → `alternate-sugar-qm-closure-v2/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_alternate_qm_continuation_20261011.json`.

**Alternate-sugar QM pilot audited; bounded QM relaxation running — 2026-10-11 Denver.**
Acknowledged completion token `1aea941e-e6fa-4e19-ac9d-6058d4bf524a`.
Native replay confirms the original MP2/6-31G(d) method, basis, occupations,
SCF/response tolerances and fitting condition. Geometry and binary gradients
match native output; all seven stereocenters, the 32 exact fixed core coordinates
and the original chi target are preserved. The alternate MM geometry has QM
energy **−1364.5363491463504 Eh**, **1.17865 kcal/mol above** the existing central
QM conformer. Its maximum free projected atom gradient is **26.2253 kcal/mol/Å**,
with RMS **14.7189 kcal/mol/Å** across the 17 free atoms. It is not stationary.
This single-point difference cannot rank the relaxed basins or establish a
force-field defect. Native cost was **194.26 seconds**.

The pilot audit admits one `alternate-sugar-qm-closure-v1` chunk using Sella
order 0/internal coordinates and the unchanged native gradient worker. It
**reuses the pilot gradient**, fixes the same 32 core atoms to the original QM
reference positions, and retains the same chi target: **97 independent
constraints, 50 free dimensions**. Every evaluated trial and accepted native
checkpoint is retained. A restart must retain the original fixed targets,
not install residual-shifted checkpoint coordinates as new targets.

Independent stationarity requires maximum tangent atom gradient below
1.5e-5 au and RMS below 1e-5 au over only the 17 free atoms, together with native
Sella convergence and chemistry/constraint checks. Optimizer completion still
does not certify a minimum. A planned time or gradient-allocation boundary is
recorded separately from convergence and requires a new audit.

Six focused tests passed for acquisition limits, fixed-target retention, chi
and nonfinite-geometry rejection, and free-atom RMS semantics. Native preflight
confirmed the independent projection against the Sella constraint nullspace
within **5.50e-13 au**, without additional QM work.

Launched **20:00:40 Denver** with **four CPUs, 4 GiB Psi4 / 8 GiB service memory,
no swap**. The single startup observation verified pilot reuse, its initial
accepted checkpoint, the first new native DF-SCF calculation and 449-function
orbital basis. Allocation is **at most 12 new gradients**, **600 seconds per
gradient**, and **one hour total**. Expected finish is approximately
**20:41:32**; the audit trigger is **20:50:40**, hard stop **21:00:40**.
External completion/failure watcher `85f479a2-72de-45b7-ade2-83d5ff25bebb`
is armed. No periodic polling or concurrent calculation.

Next: audit native results and accepted-state energy/force progress, confirm
fixed targets/chi/stereochemistry, and compare sugar descriptors with both
starting conformers before deciding whether another bounded chunk is useful.
The remaining bonded-fit round, prospective holdouts and full candidate lock
remain untouched. All output and scratch are on mounted Archive. No cloud
spending or existing-data move/delete.

Audit: `alternate-sugar-qm-pilot-v1/completion_audit.json`.
Current handoff: `current_handoff.json` → `alternate-sugar-qm-closure-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_alternate_qm_closure_20261011.json`.

**Fixed-core boundary audit complete; one alternate-sugar QM pilot running — 2026-10-11 Denver.**
Acknowledged completion token `7bc78462-5dba-4224-8e76-10ea143f641d`.
Independent replay verifies **all 61 evaluated/accepted states**, native ASE
trajectory energies/forces, Sella log energies, all final stereocenters and the
97-constraint tangent forces. Both final states meet the fixed-core/chi and
projected-force requirements; neither is a certified full endpoint minimum.

| Offset | Maximum projected atom gradient, kcal/mol/Å | Exocyclic change | 5′ OH change | Largest sugar-ring change | MM relaxation energy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0° | 0.000813 | −128.75° | +158.78° | 42.19° | −12.315 kcal/mol |
| +30° | 0.000770 | −2.32° | −5.61° | 6.96° | −4.997 kcal/mol |

Heavy RMSD is **0.3678 Å / 0.0667 Å**. The central conformer still changes
substantially with the exact QM core held fixed, while +30° stays close to its
starting descriptors. This excludes core-shape relaxation as the sole cause of
the central mismatch. It does not establish which conformer QM prefers.

An initial audit incorrectly required a constant parent/candidate energy offset
to 1e-9 kcal/mol at every intermediate accepted state. The maximum transient
fixed-coordinate residuals are **7.96e-8 / 2.00e-8 Å**, within the frozen 1e-7 Å
limit, and induce offsets of **1.55e-6 / 2.28e-7 kcal/mol**. Exact reconstruction
from the actually changed core harmonic terms accounts for these offsets.
Parent/candidate free-atom forces are identical throughout; final offsets agree
within 7e-13 kcal/mol. The failed audit and source are preserved; no numerical
tolerance, native result or worker was changed.

The independent proper-torsion and nonbonded-pair reconstruction sums to native
OpenMM energies. At 0°, the changes are:

| Contribution | Energy change, kcal/mol |
| --- | ---: |
| Sugar-only proper torsions | −5.201 |
| Core–sugar boundary proper torsions | −0.174 |
| Sugar-only nonbonded interactions | −8.054 |
| Core–sugar boundary nonbonded interactions | +3.243 |

The largest individual torsion contribution is the existing
O5′–C5′–C4′–C3′ term (**−4.199 kcal/mol**). Thus internal sugar terms favor much
of the alternate geometry, while its net nonbonded interaction with the core
becomes less favorable. This is exact MM energy accounting, not a unique
decomposition of QM error. Do not compensate this mismatch by blindly refitting
CPD base terms or by changing standard sugar parameters to enforce the original
conformer. The remaining bonded-fit round is still reserved.

`alternate-sugar-qm-pilot-v1` acquires **one original-method MP2/6-31G(d) gradient**
at the audited central MM alternative. It restores the 32 fixed atoms exactly
from the original native QM reference, removing only **4.41e-14 Bohr** of solver
roundoff; all seven stereocenters and the exact chi target remain intact. The
source MM Bohr conversion is preserved explicitly. Native reference geometry,
energy, gradient, occupations and basis evidence were reopened before admission.
Basis preflight confirms **449 orbital / 2,737 SCF fitting / 1,820 MP2 fitting
functions**. Electronic settings, frozen core, fitting condition and all
SCF/response tolerances remain unchanged. No optimizer is running in this pilot.

The pilot compares a vertical QM energy and free projected gradient against the
existing central QM conformer before a possible separately audited closure
optimization. A higher-energy single point cannot rule out a lower nearby
alternate minimum; a lower point would show the original conformer is not the
lowest in this conditioned domain. Neither outcome alone certifies a basin,
minimum, barrier, relative formation probability or fitted target.

Launched **19:47:05 Denver**. The single startup check verified native DF-SCF
entry and 449-function basis, **four CPUs, 4 GiB Psi4 / 8 GiB service memory,
no swap**. One gradient has a **600-second timeout**, within a **15-minute total
service bound**. The prior reference gradient took 214 seconds; expected finish
is around **19:52:05**, audit deadline **19:59:05**, hard stop **20:02:05** Denver.
External completion/failure watcher `1aea941e-e6fa-4e19-ac9d-6058d4bf524a` is
armed. No periodic polling or concurrent calculation.

Next: reopen the completed pilot's actual native output, compare energy and
projected forces/cost, and decide whether a short QM branch-closure chunk is
necessary. No optimization, second fit, broader scan, prospective holdout,
candidate lock or product promotion is automatically admitted. All outputs and
scratch are on mounted Archive. No cloud spending or existing-data move/delete.

Audit: `fixed-core-boundary-v1/completion_audit.json`, with exact energy
decomposition and accepted torsion histories in each point folder.
Current handoff: `current_handoff.json` → `alternate-sugar-qm-pilot-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_boundary_qm_pilot_20261011.json`.

**Core bonded fit audited; fixed-core boundary diagnostics complete, audit queued — 2026-10-11 Denver.**
Acknowledged completion token `feb6b28d-3896-474a-9b13-66447eff9d11`.
The independent audit reconstructs the frozen objective from native gradients
and Hessians, verifies bound optimality, and replays **704 evaluated core states
and 671 accepted checkpoints**. The final geometry is the last accepted state.
Exact core/endpoint system comparison confirms that only the 54 paired
bond/angle equilibria changed; masses, force constants, all other terms and
full-precision charges are unchanged. All ten static core/endpoint records
reproduce their saved native energies and gradients.

| Core diagnostic | Parent | First bonded correction |
| --- | ---: | ---: |
| Gradient-component RMSE at QM geometry, kcal/mol/Å | 12.8563 | 4.4264 |
| Internal Hessian-component RMSE at QM geometry, kcal/mol/Å² | 24.0816 | 23.8769 |
| Relaxed heavy-atom RMSD, Å | 0.17536 | 0.17978 |
| Largest relaxed bond error, Å | 0.03000 | 0.01258 |
| Largest relaxed angle error | 5.5159° | 3.9964° |

Data objective falls from **171.8282 to 26.0532**, with prior contribution
**0.16460**. Four angle-equilibrium terms hit the ±8° bounds. The finite ring
even-energy discrepancies are **−12.82% and −11.19%**, versus −9.06% / −10.88%
for the parent. This is a useful partial force/bond-length correction, not a
uniform improvement or qualified candidate. Preserve it without widening
bounds or automatically consuming the remaining fit round.

The final MM core preserves corrected chemistry and has maximum atom gradient
**6.456e-6 kcal/mol/Å**. Independently replayed Hessians at 1e-4 and 5e-5 Å
steps have **102 positive internal eigenvalues**; the lowest is
**0.268909 kcal/mol/Å²**, while the projected step-difference operator norm is
**1.581e-5 kcal/mol/Å²**. This supports a **numerically certified local minimum
of this exact MM core system and saved geometry**. It does not certify the
sugar endpoint, a shared QM/MM basin, parameter accuracy, global minimum or
production readiness. Original worker flags remain untouched. The top-level
campaign minimum flag remains false; the audit scopes the isolated MM evidence
under `local_mm_minimum`.

Vertical endpoint relative-energy errors at −30, −15, +15 and +30° are
**+2.785, +0.700, −2.136 and −3.852 kcal/mol**. These use the same acquired QM
coordinates, not a matched relaxed profile. They do not establish whether
core correction repairs the sugar/cap conformer mismatch. The historical
L-BFGS-B core relaxation is retained and independently audited; subsequent
molecular optimizations follow the user's preferred Sella method.

`fixed-core-boundary-v1` tests **two existing endpoint conformers, 0° and +30°**.
Each retains its exact chi target while fixing all **32 base/methyl atoms to
that conformer's QM coordinates**; the 17 sugar/OH-cap atoms have **50 independent
free dimensions**. Native Sella uses order0/internal coordinates, unchanged
charges and the first core correction. Every fitted term involves fixed atoms
only. Preflight confirms the parent and candidate have identical free-atom
gradients and differ by a constant energy under sugar perturbations, within
1.8e-14 kcal/mol. Thus these conditioned sugar forces cannot be corrected by
further changes to the selected base-only equilibrium terms.

Native constraint rank is **97**; the independent masked-coordinate/chi
projection agrees with the analytic constraint nullspace within **2.0e-11**.
**Four focused tests pass in 1.14 seconds.** The 0° point probes the prior
large rotamer change; +30° supplies the less-drifted comparison. Audit actual
fixed-position drift, tangent forces, all seven stereocenters and cap/sugar
torsions. A conditioned result is not a full endpoint minimum or qualification
of the unconstrained glycosidic profile. If drift persists, review the boundary
and nonbonded interactions before the second fit; if suppressed, reconsider
coupling to core shape. No automatic additional QM or fit is admitted.

The service started **19:36:28 Denver** and completed both attempts in
**4.84 seconds**, before the single startup/outcome check. Completion token
`7bc78462-5dba-4224-8e76-10ea143f641d` is queued for independent audit.
**No calculation is running.** Requested limits: two sequential workers,
400 steps / 600 evaluations / 300 seconds each, **15 minutes total**, one CPU,
4 GiB, no swap. External completion/failure triggers and one audit deadline
replace periodic polling. Post-exit unit defaults do not measure live limits.

One bonded-fit round remains consumed; no second round, new QM, prospective
holdout acquisition, full candidate lock, registry promotion, cleanup, move or
delete. All bulk outputs and scratch remain on mounted Archive; no cloud
spending. Failed and rejected evidence remains preserved.

Audit: `core-bonded-fit-v1/completion_audit.json`; explicit target-Hessian
reconstruction: `target_hessian_reconstruction_addendum_v2.json` in that folder.
The v2 addendum corrects a source locator while preserving the earlier addendum;
the original completion-audit source hash is restored and archived.
Current handoff: `current_handoff.json` → `fixed-core-boundary-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_core_fit_boundary_20261011.json`.

**MM profile audited; first core bonded fit complete, audit queued — 2026-10-11 Denver.**
Acknowledged completion token `ba87ff19-75ed-4388-8a8f-de629cf5d138`.
Independent OpenMM replay verifies **all 248 evaluated states**, every accepted
checkpoint, native ASE trajectory energy/force and rounded Sella log energy.
All five endpoints preserve the corrected CPD and sugar stereochemistry and
pass independent constrained-stationarity checks. Analytic Sella constraint
Jacobians agree with the separate finite-difference projection. These are
constrained stationary states, **not certified minima**.

| Offset | Maximum projected atom gradient, kcal/mol/Å | Heavy RMSD, Å | Sugar exocyclic torsion change |
| --- | ---: | ---: | ---: |
| −30° | 0.000326 | 0.6286 | −16.36° |
| −15° | 0.000599 | 0.3750 | −119.17° |
| 0° | 0.000310 | 0.4533 | −128.42° |
| +15° | 0.000708 | 0.5419 | −139.08° |
| +30° | 0.000671 | 0.2741 | −6.58° |

All five fail the historical conformer descriptor checks; the middle three
undergo substantial exocyclic rotamer changes, accompanied by sugar-pucker
and base changes. The −30° state also changes several heavy torsions by
33–39°. **Reject the mixed-conformer relaxed energies as a glycosidic fitting
target.** Retain the trajectories and every numerical result. The 0.25 Å / 20°
flags are diagnostic conventions, not universal basin boundaries.

At the three middle offsets, relaxation lowers angle energy by 7.57–8.79,
proper-torsion energy by 3.91–7.16 and nonbonded energy by 12.73–16.81 kcal/mol.
These contributions do not uniquely assign the error to one parameter family.
The terminal 5′ OH–opposite O4 contact remains near 1.86–2.04 Å in those final
states, despite the exocyclic rotations; at −30° its distance increases from
2.01 to 3.89 Å. Distances alone are not hydrogen-bond assignments. Saved
accepted-state torsion histories include both OH-cap hydrogens and sugar-ring
descriptors. No additional unchanged-parent scans or QM are justified now.

`core-bonded-fit-v1` makes the **first bounded bonded-fit attempt**, correcting
only **10 base heavy-bond and 17 heavy-angle equilibrium groups**. Exact
base-exchange ties preserve equivalent terms; ordered atom roles distinguish
intrabase C5–C6 bonds from the welds. Force constants, Urey–Bradley terms,
proper/improper torsions, charges, LJ and every cap/sugar term stay fixed.
Prospective ordered type aliases are recorded for later CHARMM export; no
shared parent force-field types or production registry are changed.

The frozen objective uses core gradient RMS /1 kcal/mol/Å, full internal
Hessian RMS /10 kcal/mol/Å², and the four acquired ring-gradient differences
RMS /1 kcal/mol/Å, plus `0.1 mean(z²)`. Bond/angle scales are 0.02 Å / 4°,
with bounds ±0.04 Å / ±8°. These are explicit development choices, not measured
noise or literature acceptance criteria. No mixed relaxed endpoint energies
enter the objective. Existing training Hessian/ring data remain exposed;
prospective finite holdouts remain unacquired.

Preflight finds **27/27 response rank**, scaled condition number **191.16**.
Native combined-parameter energy/gradient checks agree within **6.4e-14**;
halving the Cartesian differentiation step changes the baseline Hessian by
at most 1.04e-5 kcal/mol/Å². Exact core-to-endpoint role transfer is verified.
**Six focused tests pass in 1.13 seconds**, covering derivatives, units,
exchange ties, weld isolation, projection and scalar/tensor Hessian assembly.

The service started **19:25:59 Denver**, completed in **0.44 seconds**, and
queued completion token `feb6b28d-3896-474a-9b13-66447eff9d11` before the single
startup/outcome check. **No calculation is running.** The first candidate,
one core relaxation, finite-step core Hessian diagnostics and vertical endpoint
evaluations are saved; their independent audit is pending. Requested limits:
**15 minutes total**, 1 CPU, 4 GiB, no swap; core relaxation at most 1,500
evaluations / 300 seconds. Post-exit unit defaults do not measure live limits.
External completion/failure triggers and one deadline replace periodic polling.

Next: reconstruct the fit objective and bound activity, replay native candidate
forces, audit the core geometry/stationarity/Hessian and compare training ring
responses plus vertical endpoint transfer. Do not infer acceptance from solver
success. A second fit, additional endpoint relaxations and new QM require that
evidence review, not renewed routine user permission. No full candidate hash
lock, minimum certification, transfer validation or production-readiness claim.
All outputs/scratch remain on mounted Archive; no cloud spending, cleanup,
existing-data relocation or deletion. Earlier failures remain preserved.

Audit: `mm-endpoint-profile-v2/completion_audit.json`.
Current handoff: `current_handoff.json` → `core-bonded-fit-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_mm_profile_core_fit_20261011.json`.

**Bonded baseline audited; constrained MM profile complete, audit queued — 2026-10-11 Denver.**
Acknowledged completion token `1d1071dd-da50-4a47-9477-91cabe4cb3e5`.
Independent OpenMM replay verifies all 20 fixed-geometry energy/gradient
records and both final core states. All accepted core frames correspond to
stored evaluated states. Both optimizers converged, independent checks of
unconstrained core stationarity pass, and corrected stereochemistry is
preserved. Neither MM core has a Hessian certification.

| Published-row hypothesis | Core heavy RMSD | Largest bond error | Largest angle error | Maximum atom gradient |
| --- | ---: | ---: | ---: | ---: |
| first | 0.3551 Å | 0.03062 Å | 5.1466° | 7.03e-6 kcal/mol/Å |
| last | 0.1754 Å | 0.03000 Å | 5.5159° | 5.82e-6 kcal/mol/Å |

The largest bond errors involve C2–N3; the largest angle errors involve the
crosslink carbons and their N1/C4 neighbors. The cores are stationary but do
not reproduce the target geometry adequately for a readiness claim. At the QM
core, gradient-component RMSE remains 12.74/12.86 kcal/mol/Å. Finite coupled-ring
even-energy errors are **−7.71%/−10.65%** for first and **−9.06%/−10.88%** for
last. These are measured discrepancies, not failures against a universal 5%
criterion, and they do not certify curvature at an MM stationary point.

For last, vertical endpoint relative-energy errors at −30, −15, +15 and +30°
are **+3.117, +0.574, −2.530 and −4.671 kcal/mol**. These compare identical QM
coordinates; their interpretation as relaxed-profile errors requires actual
conformer checks. No fitting or new QM is admitted from this comparison alone.

`mm-endpoint-profile-v2` independently starts **five constrained MM relaxations**
from the corresponding acquired QM points, preserving the exact glycosidic
targets and unchanged full-precision charges/parameters. Last-row is the
provisional parent because its core heavy RMSD is smaller; first-row evidence
and source ambiguity remain preserved. Native Sella order0/internal coordinates
use the audited degree-target helper. Independent tangent-force projection is
checked against Sella's analytic constraint Jacobian to **1.03e-10**. Every
evaluated trial and accepted checkpoint is retained. Review all seven centers,
bond/contact screens, heavy RMSD and **78 ordered heavy proper torsions**.
Historical 0.25 Å / 20° descriptor flags guide review; passing is not proof of
basin identity, global-minimum closure or publication validation.

A focused test caught tuple/list atom-index handling in the new descriptor
caller. Prepared `mm-endpoint-profile-v1` and its failed test receipt are
preserved; **no v1 native job launched**. The caller was corrected without
changing the shared pinned helper, and a fresh v2 source/plan was frozen.
**Eight focused tests pass**, including angular wrap, force projection,
tuple/list equivalence and descriptor changes.

The v2 service started at **19:11:54 Denver** and completed all five attempts
in **12.90 seconds**, before the single startup/outcome check. Its completion
audit is queued as `ba87ff19-75ed-4388-8a8f-de629cf5d138`; **no calculation is
running**. Requested limits were 500 steps / 750 optimizer evaluations per
point, 300 seconds per worker, **30 minutes total**, one CPU, 4 GiB, no swap.
Post-exit properties of the collected unit do not measure live resource use.
No repeated calculation or periodic polling is needed.

Next: independently verify final accepted states, actual projected forces and
conformer correspondence before constructing a bonded-fit objective. Preserve
any failed stationarity or changed basins. No minimum certification, fit-round
consumption, prospective holdout exposure, cloud spending, existing-data move/
delete or product promotion. All outputs and scratch remain on mounted Archive.

Baseline audit: `bonded-baseline-v1/completion_audit.json`.
Current handoff: `current_handoff.json` → `mm-endpoint-profile-v2/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_bonded_baseline_mm_profile_20261011.json`.

**Endpoint electrostatics audited; bonded baseline complete, audit queued — 2026-10-11 Denver.**
Acknowledged completion token `bd8e64b2-6175-4050-b481-1eff3440b15d`.
Both fixed-geometry HF calculations pass reopened native method, 449-function
Cartesian basis, geometry/stereochemistry, energy, dipole and ESP audits.
Final energy/density residuals meet the unchanged 1e-12 criteria. Independent
charge-sum/dipole/ESP reconstruction agrees with the saved diagnostics.
Total service time: **109.88 seconds**; no optimizer or new minimum assessment.

| Endpoint | Initial dipole-vector error | Candidate error | Initial → candidate ESP relative RMSE |
| --- | ---: | ---: | ---: |
| −30° | 4.566 D | 1.024 D | 61.12% → 42.51% |
| +30° | 5.714 D | 2.040 D | 75.33% → 51.47% |

The candidate improves both endpoint dipoles and every reported ESP region,
but substantial absolute errors remain. Nearest-methyl-cap ESP errors are
84.68%/89.73%; nearest-sugar errors are 38.35%/58.46%. These geometric regions
do not uniquely identify electronic error sources. **Electrostatic transfer
accuracy is not validated.** Retain the unchanged first charge candidate for
bonded-model diagnostics; no automatic second fit or additional water/HF grid.
Core plus these two endpoints use all three planned electrostatic conformers.

`bonded-baseline-v1` constructs fresh **36-atom/38-bond core** and
**49-atom/52-bond endpoint** fixtures from the corrected graph. Both retain
C5–C6 crosslinks, unchanged candidate charges and standard sugar/LJ terms.
Four carbonyl impropers are included; no planar C5 improper is imposed on the
saturated stereocenters. The published SI duplicate torsion rows are retained
as explicit **first/last hypotheses**, each combined with the same standard
parent terms. Additional parent Fourier multiplicities remain inherited.
Neither hypothesis is asserted to reproduce the authors' unavailable stream
or constitute a validated corrected-anti force field.

Preflight verifies native psfgen atom order, exact graph, all parameter coverage,
particle charges, graph-derived 1–2/1–3 exclusions and unscaled 1–4 charge
products. Serialized systems retain full-precision candidate charges; native
PSF text rounds by at most **4.903e-7 e**, so export precision/equivalence remains
explicitly pending before NAMD. Twelve component derivatives across the four
systems agree with independent energy differences within **9.4e-9
kcal/mol/Å**. Four focused geometry-diagnostic tests pass, including rejection
of reflected alignment and bond/angle units.

The allocation evaluates **ten acquired training geometries per hypothesis**
(core, four coupled-ring distortions, five sugar conformers), then performs one
bounded core relaxation per hypothesis. Endpoint energies are **vertical values
at QM coordinates**, not independently relaxed profiles or basin-closure evidence.
No new QM, parameter fitting, heldout exposure or MM Hessian is involved.
Limits: two sequential hypotheses, 1,500 evaluations / 300 seconds per core,
360 seconds per hypothesis, **15 minutes total**, one CPU, 4 GiB, no swap.

The service started at **18:58:20 Denver** and completed in **0.95 seconds**,
before the single startup/outcome check. Completion audit token
`1d1071dd-da50-4a47-9477-91cabe4cb3e5` is successfully queued. **No native job
remains running.** Post-exit properties of the collected transient unit do not
measure live resource use; requested limits remain in the frozen launch source.
Do not repeat this fast calculation or infer quality from its exit status.
Next audit must review actual geometry/force/profile/curvature errors, then
freeze necessary bonded-fit variables and isolated atom-role types. The charge
fit and these diagnostics are not a full candidate parameter hash lock.

All data and scratch remain on mounted Archive. Earlier failures are preserved;
no cloud spending, existing-data move/delete, registry promotion or readiness claim.
Transfer audit: `electrostatic-endpoint-transfer-v1/completion_audit.json`.
Current handoff: `current_handoff.json` → `bonded-baseline-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_endpoint_transfer_bonded_baseline_20261011.json`.

**Core charge fit audited; two sugar-endpoint diagnostics launched — 2026-10-11 Denver.**
Acknowledged completion token `7b3f2472-7066-4b7c-9498-5149e31c7393`.
The first fit passes independent reconstruction of all **1,176 MM grid
energies**, interpolated minima, objective blocks, charge constraints and the
saved six OpenMM Reference interaction checks. Both bases and methyl caps
remain neutral; corresponding base charges are equal; all 16 fixed atoms retain
their initial charges. The optimizer used 18 iterations; service time was
0.32 seconds. This supports a provisional core charge candidate, not a complete
force field, transfer validation or new minimum certification.

| Core diagnostic | Audited result |
| --- | ---: |
| Largest water minimum energy error | 0.01320 kcal/mol |
| Largest water minimum distance error | 0.10490 Å |
| Unscaled HF dipole-vector error | 0.00390 D |
| ESP relative RMSE, diagnostic only | 45.86% |
| Data-only Jacobian condition number | 1.635e6 |

All six wells satisfy the frozen 0.5 kcal/mol / 0.2 Å development limits.
Objective 0.87504 comprises water-energy 0.002676, water-distance 0.696971,
dipole 0.0000203 and charge-restraint 0.175371. **O4 reaches its +0.15 e shift
bound**; the data remain poorly conditioned, with eight directions above the
relative 1e-6 cutoff. The small water/dipole residuals do not establish unique
physical charges or erase the ESP discrepancy. Stop core fitting after round
one; a second round remains unadmitted pending meaningful residual evidence.
The OpenMM checks are static intermolecular energies at target-nearest grid
points, not bonded-system or NAMD tests. All previous failures remain preserved.

`electrostatic-endpoint-transfer-v1` freezes **two existing 49-atom endpoint
conformers at −30°/+30°**, spanning the acquired glycosidic interval. These are
constrained stationary points, not certified full minima. Two sequential
HF/6-31G(d) DF property calculations compare unchanged candidate and initial
charges against unscaled dipoles and ESP. The 28 base charges and opposite
neutral methyl cap transfer exactly; 17 sugar/OH-cap atoms retain native CHARMM
NA charges, including **C1′ +0.16 e**. No geometry optimization, water grid,
parameter fit or prospective holdout is included. The core plus these two
endpoints exhaust the planned three electrostatic conformers.

Source-pinned native psfgen generated the sugar template. Preflight reopened
the two MP2 outputs, checked graph/atom order, all seven stereocenters and exact
glycosidic targets, and verified Psi4 preserves the supplied Bohr coordinates.
ESP grids contain 1,264/1,253 exposed points; nearest-base/sugar/methyl regions
form a disjoint geometric partition, not a unique electronic decomposition.
Eight focused charge-transfer/unit tests pass. No new physical acceptance
threshold was introduced; review endpoint residuals before admitting further
water acquisition or a second fit. Core DF/DIRECT calibration is not an
endpoint-specific numerical error bound.

The service launched at **18:47:56 Denver**. One startup check verified native
DF entry, four CPUs, **4 GiB Psi4 / 8 GiB service memory**, no swap, and the
external completion watcher `bd8e64b2-6175-4050-b481-1eff3440b15d`.
Limits: **two SCFs, 300 seconds per SCF, 15 minutes total**. Expected finish
18:50:56; audit deadline 18:59:56; hard stop 19:02:56 Denver. Completion/failure
triggers and one deadline replace polling. All output and scratch remain on
mounted Archive; no cloud spending or existing-data relocation/deletion.

Next: audit endpoint electrostatics, then assemble the corrected bonded model
and compare matched conformers against the acquired core/Hessian, ring and
glycosidic training evidence. Keep prospective ±22.5° and reserved ring-mode
targets unacquired until full parameter hash lock. Legacy anti fitted data
cannot serve as corrected-isomer evidence. Production readiness remains false.

Charge audit: `charge-core-fit-v1/completion_audit.json`.
Current handoff: `current_handoff.json` → `electrostatic-endpoint-transfer-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_charge_fit_transfer_20261011.json`.

**Water acquisition complete; first charge fit finished, audit queued — 2026-10-11 Denver.**
Acknowledged wake `94a499f7-4aa6-4f32-a392-faae5331cb73` as service `complete`.
The 39 new DF calculations finished in **13.70 minutes**. All **44 records**
(42 contact points plus two isolated references, five reused) pass reopened
native geometry, identity, basis, energy and convergence checks. Every curve
brackets an attractive well with monotone flanks. No grid extension, repeated
water points or extra DIRECT calculations are justified.

Raw sampled minima are near **2.1 Å / −4.619 kcal/mol** for O2,
**2.1 Å / −2.921 kcal/mol** for O4 and **1.9 Å / −6.159 kcal/mol** for H3.
Local three-point interpolations supply approximate continuous target minima;
raw values are retained separately from the 1.16 energy / −0.2 Å corrections.
These are fixed-orientation radial wells, not full water-complex minima.
Largest corresponding-base difference across the grids is **0.000230 kcal/mol**.
The corrected 36-atom graph independently admits the exact base-exchange
permutation with chirality preserved. Corresponding base atoms therefore share
charges in the first fit; paired curves are not counted as independent replication.

`charge-core-fit-v1/policy.json` freezes ten paired charge groups (**nine
independent variables after neutrality**), initial charges/types, neutral methyl
caps, Lennard–Jones parameters, objective and bounds before fitting. Initial
base values come from the preserved published cis-syn Figure S1 transcription
as a **starting hypothesis only**; no legacy anti fitted charges or topology
are reused. Each N1-methyl cap remains CG331 −0.27 e plus three HGA3 +0.09 e.
Aliphatic H6/methyl-H, caps, LJ and bonded/sugar/phosphate terms remain fixed.
Each base remains neutral; shifts are limited to **±0.15 e**.

The objective is the sum of mean-square water minimum energy errors divided by
0.2 kcal/mol, distance errors divided by 0.1 Å and unscaled HF dipole-vector
errors divided by 0.5 D, plus **0.2 × mean((charge shift / 0.1 e)²)**.
The penalty coefficient is explicitly in the squared objective; ESP is diagnostic.
These weights and practical water limits (0.5 kcal/mol / 0.2 Å, bracketed MM
minima) are local modeling choices. Only one fit is admitted now; a second of
at most two requires residual review, with no automatic weight sweep.

Five focused fit-helper tests pass. Six MM distance grids (1.1–5.0 Å in 0.02 Å
steps) match the existing independent scalar interaction implementation. Twelve
OpenMM Reference cross-interaction checks, covering initial and neutral test
charges, agree within **7.3e-12 kcal/mol**. This verifies the nonbonded evaluator,
not a bonded model or NAMD simulation. Initial charges overbind H3-water by
**3.726 kcal/mol** and miss the HF dipole by **3.921 D**. The unregularized local
data Jacobian has nine numerical directions, but condition number **1.64e6**
and only eight above a relative 1e-6 singular-value cutoff. Report its full
spectrum before/after fitting; restrained numerical uniqueness does not imply
unique physical charge determination.

The first fitting allocation is **one SLSQP solve, at most 300 iterations /
ten optimizer minutes, within a 15-minute service**, one CPU and 4 GiB memory,
no swap. No new QM or held-out targets are involved. The next audit must separate
optimizer convergence, charge constraints, native MM agreement, water quality,
identifiability and transfer validation. No minimum certification or production
readiness follows from this fit. All files remain on mounted Archive; no cloud
spending or existing-data move/delete.

Water completion audit: `water-core-curves-v1/completion_audit.json`.
Charge-fit preparation/admission: `charge-core-fit-v1/admission.json`.

`cpd-corrected-anti1-charge-core-fit-v1.service` started at **18:36:47 Denver**
and finished in **0.32 seconds**, before the single startup/outcome review.
The watcher successfully queued `7b3f2472-7066-4b7c-9498-5149e31c7393` for its
completion audit. **No native job remains running.** The transient systemd unit
had already been collected; its post-exit default properties are not evidence
about live resource use. Requested limits are preserved in the frozen launch
source and execution plan. The fit result is saved but its quality/acceptance
has not yet been audited; do not repeat the fit or infer readiness from exit zero.
Current handoff: `current_handoff.json` → `charge-core-fit-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_water_complete_charge_fit_20261011.json`.

**HF calibration passes; six core water-distance curves active — 2026-10-11 Denver.**
Acknowledged wake `754def1a-8a36-4a8c-9fbe-692d73d251b7` as service `complete`.
The recovery completed three DIRECT complexes in **10.22 minutes**, preserving
and reusing seven earlier results. All ten native outputs pass reopened
geometry/identity, method, basis, energy, dipole and ESP checks. Final native
SCF energy/density residuals meet the unchanged **1e-12** settings. The original
150-second timeout and its incomplete output/scratch remain preserved.

| Contact at 1.9 Å | DF interaction (kcal/mol) | DIRECT interaction (kcal/mol) | Absolute raw difference |
| --- | ---: | ---: | ---: |
| 1:O2 | −4.270601 | −4.267196 | 0.003405 |
| 2:O4 | −2.327418 | −2.325530 | 0.001888 |
| 1:H3 | −6.159101 | −6.154484 | 0.004617 |

All three satisfy the existing **0.02 kcal/mol raw interaction** criterion;
maximum difference after 1.16 scaling is **0.005356 kcal/mol**. DIRECT complexes
took **187.74–222.71 seconds**, versus **19.90–24.91 seconds** for DF, an observed
**8.08–11.19-fold speedup**. No extra DIRECT pilot or core calculation is needed.
This calibration samples three contact types at one distance; it is not a proven
uniform error bound across every distance or orientation. Review any actual
curve anomaly before ordering selective additional diagnostics.

`water-core-curves-v1` admits **six fixed-orientation curves**, O2/O4/H3 on each
ordered base, at **1.5, 1.7, 1.9, 2.1, 2.3, 2.5 and 2.7 Å**. Of 42 contact
points, **three exact pilot points are reused** and **39 are new DF calculations**.
Core and isolated rigid TIP3P water references are also reused: 44 records total,
five reused. Both ordered bases are retained to examine environment equivalence
before imposing charge symmetry. Coordinates/orientations come from the frozen
pilot inventory; no global water-orientation optimization is claimed.

Independent preflight reconstructs all 42 contacts, verifies rigid TIP3P,
non-target steric screening, exact pilot reuse and certified-core coordinates
within **8.9e-16 bohr** through the installed Psi4 input API. Native worker,
parser and reuse functions are unchanged from the audited pilot. **Ten focused
curve-diagnostic tests pass**, covering a known well and rejection/review of
boundary, tied, flat, nonattractive, nonmonotonic or nonfinite curves. No QM was
spent during preflight. The completed curves must be reviewed for attractive,
bracketed minima and mixed contacts before use in charge fitting. Local
three-point interpolation is diagnostic, not a newly calculated minimum.

`cpd-corrected-anti1-water-core-curves-v1.service` started at **18:12:23 Denver**.
Limits: **39 new SCFs / one hour**, **180 seconds per SCF**, four threads,
4 GiB Psi4 / 8 GiB service, no swap. Default memory admission passed with
**12.27 GiB available**. Expected duration **20.24 minutes** uses the slowest
measured DF complex time plus 25% scheduling margin. One startup check verified
isolated-reference reuse, native entry and watcher
`94a499f7-4aa6-4f32-a392-faae5331cb73`. Expected finish **18:32:38**; audit deadline
**19:02:23**; hard stop **19:12:23 Denver**. Completion/failure triggers and one
audit deadline replace periodic polling. All outputs and scratch use mounted
Archive; no cloud spending or existing-data move/delete.

Current handoff: `current_handoff.json` → `water-core-curves-v1/handoff.json`.
Native calibration audit: `electrostatic-core-pilot-v2/completion_audit.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_hf_calibrated_water_curves_20261011.json`.
Acquisition is admitted; **charge fitting is not yet admitted**. Exact baseline
and cap charge vectors, constraints and numerical objective weights must be
frozen before fitting. Held-out targets remain unacquired until parameter lock.
No new minimum certification, fit acceptance or production-readiness promotion.

**HF pilot timeout audited; seven successes reused, three DIRECT contacts active — 2026-10-11 Denver.**
Acknowledged wake `aae6da15-f444-410e-b7b7-ff6e4482c4e7` as service `failed`.
The first allocation ran **6.31 minutes**, completing seven of ten calculations.
Reopened native evidence passes for all seven: geometry/identity, strict HF
settings, energies, dipoles and the two 1,029-point core ESP datasets. DF core
took **20.88 seconds**, three DF complexes **19.90–24.91 seconds**, DIRECT core
**138.47 seconds**; isolated water took less than 0.3 seconds per algorithm.

The first DIRECT complex, **1:O2**, hit the **150-second per-task limit** at
iteration 41. Its density residual had fallen **1.36 millionfold**, from
4.61730e-6 to **3.38432e-12**, while the last energy change was **−2.27374e-12
hartree**. Both convergence thresholds remain **1e-12**. This is progressing
SCF interrupted by an undersized scheduling limit, not a completed calculation
or evidence of a stalled method. No final energy/properties record exists;
the last iterate is excluded from targets. Failed output, traceback and
integral scratch remain intact. There is no saved usable wavefunction restart.

`electrostatic-core-pilot-v1/failure_review.json` pins the seven reusable results
and native timeout evidence. The core DIRECT dipole is **7.42767 D**;
DF/DIRECT dipole difference is **0.00218 D**, with ESP RMS difference
**6.39390e-6 au**. These core diagnostics do not substitute for the three
water-interaction comparisons. Full curves and fitting remain unadmitted.

Versioned recovery `electrostatic-core-pilot-v2` reuses all seven completed
results and executes only **1:O2, 2:O4 and 1:H3 DIRECT complexes**. The three
input files are byte-for-byte identical to v1; geometry, basis, convergence,
DF preguess behavior and scientific evaluation code are unchanged. Only
scheduling and evidence reuse change. Failed native/scratch files are not
overwritten. **Five focused reuse tests pass**; a test-only import-prefix
collection error was corrected and recorded before the passing run. Independent
preflight verifies exact input equality, unchanged scientific worker/parser and
rejection of completed-task execution before entering the native API. No QM was
spent during preflight.

`cpd-corrected-anti1-electrostatic-core-pilot-v2.service` started at
**17:56:52 Denver**, with **three new SCFs / 35 minutes**, **ten minutes per SCF**,
four threads, 4 GiB Psi4 / 8 GiB service and no swap. Default admission passed
with **12.29 GiB available**. One startup check verified reuse of seven results,
native entry only for the first remaining complex, resource limits and watcher
`754def1a-8a36-4a8c-9fbe-692d73d251b7`. Expected finish **18:06:52**, audit
deadline **18:26:52**, hard stop **18:31:52 Denver**. Completion/failure triggers
and one audit deadline replace periodic polling. All output/scratch is on
mounted Archive; no cloud spending or existing-data relocation/deletion.

After completion, reopen all ten native records and evaluate the unchanged
three-site **0.02 kcal/mol raw DF/DIRECT interaction criterion**. Further timeout
or plateau requires another evidence-based method review, not automatic
extension. If calibration supports DF, the inventoried 42-point water grid
needs at most **39 fresh DF complexes**, reusing three pilot points and isolated
references. Pilot completion alone does not admit that acquisition. There is
no new minimum claim, fitted parameter acceptance or production-readiness change.

Current handoff: `current_handoff.json` → `electrostatic-core-pilot-v2/handoff.json`.
Portable audit:
`docs/audits/cpd_corrected_cis_anti_i_electrostatic_timeout_recovery_20261011.json`.

**Coupled-ring acquisition audited; HF electrostatic pilot active — 2026-10-11 Denver.**
Acknowledged wake `472d5d97-3059-4b17-ba8f-9b009009d232` as service `complete`.
All four MP2 targets pass the reopened native audit: **432 gradient components,
eight geometry tables**, exact displaced coordinates, unchanged RHF/DF-MP2
settings, basis/occupation/fitting evidence and stereochemistry. Runtime was
**4.19 minutes**. Energy and gradient curvatures differ from the existing Hessian
by at most **0.00320% / 0.03323%** for the two selected directions. These are
observed discrepancies, not a newly imposed percentage gate. Signed asymmetry
is retained. The four-target acquisition is sufficient; no repeat calculation
or new Hessian is admitted. Displaced structures are not minima, and this is
not a fitted-force-field validation.

The HF dipole convention is resolved as an explicit local choice: **unscaled
HF/6-31G(d) dipoles**, following the modified-nucleotide charge protocol of
[Xu et al., 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/), with neutral
water interaction energies scaled by **1.16**, distance adjustment **−0.2 Å**, and
no counterpoise. That work also motivates a neutral methyl-capped base model.
Accordingly, the primary charge reference is the **exact certified 36-atom
N1-methyl core**. Up to two sugar endpoints may later test transfer if justified;
their full minimum certification remains false. This is an inference from close
chemical precedent, not CPD-specific validation or a universal dipole rule.
The general [CGenFF protocol](https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/)
and this choice are recorded in `electrostatic-core-pilot-v1/method_choice.json`.

`electrostatic-core-pilot-v1` admits **ten fixed-geometry HF calculations**:
core dipole/ESP, isolated rigid TIP3P water, and three contacts (1:O2, 2:O4,
1:H3 at 1.9 Å), each using DF and DIRECT SCF. The inherited numerical calibration
criterion is **≤0.02 kcal/mol raw interaction error** at all three contacts;
scaled errors, dipole vectors, ESP differences and measured timings are retained.
This tolerance is a local numerical criterion, not a literature accuracy claim.
Core ESP uses 1,029 exposed grid points. All six candidate water sites pass the
non-target steric screen after comparison of three azimuths; six seven-point
curves are inventoried but **full-curve acquisition remains unadmitted** pending
pilot audit. Orientation is fixed per curve, not globally optimized. Later
curves must bracket their minima and retain mixed-contact diagnostics.

Preflight caught and corrected the campaign/Psi4 Bohr-to-Å conversion difference
before QM. New HF inputs use Psi4's conversion, retaining the certified Bohr
coordinates within **8.9e-16 bohr**. The installed-engine input API verifies
all ten geometries, paired DF/DIRECT identity and rigid TIP3P geometry without
SCF. **15 focused tests pass** for native method/geometry/units/energy/dipole
evidence, nonfinite values and duplicated/missing records. Source, policy,
inventory, geometry and input hashes are frozen. Exact baseline/cap charge
vectors and objective weights must still be frozen before fitting; no charge
fit or parameter release occurs in this pilot.

`cpd-corrected-anti1-electrostatic-core-pilot-v1.service` started at
**17:46:14 Denver**. Limits: **ten SCFs / 30 minutes**, **150 seconds per SCF**,
four threads, 4 GiB Psi4 / 8 GiB service, no swap. Default memory admission
passed with **12.29 GiB available**. One startup check verified native entry,
resource limits and watcher `aae6da15-f444-410e-b7b7-ff6e4482c4e7`.
Conservative expected finish: **17:56:14**; audit deadline **18:11:14**;
hard stop **18:16:14 Denver**. Completion/failure triggers and one audit deadline
replace periodic polling. Outputs and scratch remain on mounted Archive.
No cloud spending, relocation or deletion of existing data.

Current handoff: `current_handoff.json` → `electrostatic-core-pilot-v1/handoff.json`.
Portable audit:
`docs/audits/cpd_corrected_cis_anti_i_ring_complete_electrostatic_pilot_20261011.json`.
All five glycosidic profile points and four ring targets are acquired; preserve
all failed attempts. Held-out acquisitions remain deferred until parameter hash
lock. Endpoint minimum certification, conformer matching, fitting acceptance,
formal registry review and production readiness remain pending.

**Five-point glycosidic acquisition complete; four coupled-ring references active — 2026-10-11 Denver.**
Acknowledged wake `340c50e7-03d5-417f-94ab-9504f5b46859` as service `complete`.
The +30° v3 optimizer stopped on **convergence**, after **five new gradients /
17.30 minutes**. The independent v4 audit verifies six records including the
cached seed, **882 native gradient components**, 12 native geometry tables and
six accepted checkpoints/frames. Maximum/RMS projected gradients are
**7.26153e-6 / 3.54227e-6 au**; final angle error **6.0713e-8°**. Electronic
settings and seven stereocenters pass. This is constrained stationarity;
**unconstrained endpoint stationarity and full endpoint minimum certification
remain false**. No more optimization at these completed targets is admitted.

All five development offsets now pass their native and constrained convergence
audits. Relative energies use the preserved lower-branch zero:

| Offset (degrees) | Relative energy (kcal/mol) |
| --- | ---: |
| −30 | −1.652114 |
| −15 | −1.162456 |
| 0 | 0 |
| +15 | +1.324736 |
| +30 | +3.439952 |

`glycosidic-branch-profile-v1/completed_profile_review.json` records exact results,
all cap/sugar/core torsions, adjacent changes and saved-gradient angle slopes.
The final +15→+30 change is at most **4.20°** in sugar-ring torsions, **6.08°** in
the 5′-OH cap and **1.07°** in the cyclobutane descriptor. Across the grid,
geometries vary gradually; no observed final-profile discontinuity currently
justifies extra reverse scans. This is a provisional interpretation, not basin
closure or fitting acceptance. Match QM/MM geometries and conformers before
fitting; preserve all prior references, original seed-contact evidence and
wrong-angle failures. Held-out ±22.5° points remain unacquired.

The next planned acquisition is `coupled-ring-training-v1`: **four fixed-geometry
MP2 gradients**, two signs along each of the two core modes with greatest
Cartesian displacement participation on the four cyclobutane carbons. The
existing certified 36-atom core and its Hessian are reused. Saved mode columns
**46 / 62** have ring participation **25.55% / 19.16%**. Unit-Cartesian steps
**±0.1 bohr** move every atom by less than **0.020 Å**, with predicted even
harmonic responses **0.420 / 0.932 kcal/mol**. The complete ranking, sign
convention, amplitudes and four exact inputs were frozen before acquisition.
All displaced identities pass and shortest nonbonded contacts remain
**2.309–2.351 Å**, versus **2.330 Å** at the reference, excluding graph separations
of one or two bonds. Six focused selection tests pass; independent displacement
reconstruction and source checks require no new QM.

Third-ranked mode column **32**, at the same two signed amplitudes, is reserved
for prospective finite-amplitude validation after parameter hash lock. Its
direction derives from the exposed development Hessian; it is not independent
structure validation. No held-out coordinates or electronic targets were acquired.
Two training directions do not span all ring terms. No new Hessian or independent
ring-bond torsion scan is launched, and these displaced geometries are not minima.

`cpd-corrected-anti1-coupled-ring-training-v1.service` started at **17:30:13 Denver**.
Limits: **four gradients / 15 minutes**, four threads, 4 GiB Psi4 / 8 GiB service,
no swap, three minutes per gradient. Default 12 GiB memory admission passed with
**12.28 GiB available**. One startup check verified the native child, resource
limits and watcher `472d5d97-3059-4b17-ba8f-9b009009d232`. Expected finish
**17:34:20**, audit deadline **17:43:13**, hard stop **17:45:13 Denver**.
Completion/failure events trigger review; no periodic polling. Outputs and
scratch are on verified mounted Archive. No cloud spending or storage cleanup.

Current handoff: `current_handoff.json` → `coupled-ring-training-v1/handoff.json`.
Portable audit: `docs/audits/cpd_corrected_cis_anti_i_profile_complete_ring_start_20261011.json`.
After the finite response audit, prepare the bounded electrostatic inventory and
resolve the HF dipole convention from primary literature before charge acquisition.
Fitting acceptance, formal registry review and production readiness remain pending.

**+30° v2 substantially improved but remains unconverged; v3 active — 2026-10-11 Denver.**
Acknowledged wake `2c10786b-45a0-453b-aa6a-8c34b98acb94` as service `complete`.
The independent v4 audit passes native evidence and all constrained angles:
20 new gradients plus one reused gradient, **3,087 components**, **42 geometry
tables**, and **21 accepted checkpoints/frames**, with electronic settings and
seven stereocenters preserved. The allocation ended after **69.63 minutes**;
**optimizer and constrained stationarity remain false**. Maximum/RMS projected
gradients are **4.86344e-5 / 1.61731e-5 au**, respectively **3.24× / 1.62×** the
unchanged limits. Maximum projected force fell **207.45-fold** over the chunk
and **68.08%** over the last five records. Energy fell **2.94665 kcal/mol**;
the remaining **+3.43999 kcal/mol relative to branch zero is unfinished**, not
a fitting target. The original clashing H/H pair now separates by **2.1223 Å**.
Sugar-ring torsions changed by up to **23.23°** during this chunk; record these
changes for eventual conformer matching rather than assuming basin closure.

The last accepted checkpoint has an angle error of **2.21050e-6°**, below the
existing **0.01°** acquisition/audit limit (maximum error over the chunk:
**4.98904e-6°**). Two legacy startup-only checks nevertheless reject it:
the restart validator's **1e-6°** gate and the installed-constraint check's
**1e-8-radian** residual gate. Versioned helpers now admit an **audited accepted
restart** under the existing native angle criterion. Exact coordinates and
cached gradient remain unchanged; the installed degree target, optimizer
settings, electronic method and force thresholds remain unchanged. Fresh seeds
retain the strict residual check. Old helpers, plans and failed checks are
preserved; three import/call lines differ in the new frozen worker. **Twelve
focused tests pass**, and the installed Sella integration confirms cached reuse,
three moving synthetic steps and rejection of double conversion/off-target
native entry, with **zero new QM evaluations** during these checks.

The continued force reduction justifies one more bounded continuation;
`cpd-corrected-anti1-glyco-branch-plus30-v3.service` started at **17:05:51 Denver**.
Limits are **20 new gradients / 90 minutes**, four threads, **4 GiB Psi4 / 8 GiB
service memory**, no swap and ten minutes per gradient. Default 12 GiB admission
passed with **12.32 GiB available**. One startup verification confirms exact
checkpoint-gradient reuse, the correct target and the armed watcher. Expected
full-allocation finish is **18:15:45**; audit deadline **18:25:51**, hard stop
**18:35:51 Denver**. Completion/failure events trigger review; no periodic
polling or automatic extension on stalled progress. Outputs and scratch use the
verified mounted Archive filesystem. No cloud spending or storage cleanup.

Four profile points remain converged and +30° remains unresolved. Full endpoint
minimum certification, conformer matching, fitting acceptance, held-out testing
and production readiness remain pending. Audit:
`docs/audits/cpd_corrected_cis_anti_i_branch_plus30_v3_20261011.json`;
native review: `endpoint-1-glyco-branch-plus30-v2/continuation_review.json`;
resume pointer: `current_handoff.json` → `endpoint-1-glyco-branch-plus30-v3/handoff.json`.

**+30° allocation ended unconverged; seed-contact diagnosis and bounded restart — 2026-10-11 Denver.**
Acknowledged wake `e71cc400-15c6-4cf3-bea3-fdc6f3ff0af6` as service `complete`.
**The +30° target is not converged.** Its first chunk exhausted 20 new gradients
after **69.75 minutes**. The v4 audit passes native evidence and every angle:
2,940 gradient components, 40 geometry tables and 20 accepted checkpoints/frames,
with preserved electronic settings and seven stereocenters. Maximum angle error
is **1.53e-8°**. Final projected maximum/RMS gradients are
**0.01008910 / 0.00205197 au**, about **673×** the maximum-force limit.
The profile still has four converged points; the last +30° energy of
**+6.38664 kcal/mol relative to branch zero is unfinished**, not a fitting target.

The original rigid 30° seed contains a **0.5805 Å nonbonded contact between
1:HO5′ and 2:H52** and starts **161.22 kcal/mol above branch zero**. Its old
preflight passed bond/stereochemical identity and angle checks, but **did not
screen nonbonded seed contacts**. That limitation and original evidence are
preserved; native evaluations remain valid at their recorded coordinates.
The accepted checkpoint opens this contact to **1.9275 Å**. A static alternative
made by rotating the converged +15° structure to the same target still has a
**1.3068 Å** contact. No QM was spent on that alternative, so its relative
energy/basin ordering is not known. All distances exclude pairs separated by
one or two graph bonds. Future seed review must inspect nonbonded contacts
before spending QM, in addition to existing identity and constraint checks.

Force reduction slowed late in the first chunk, while the final five evaluations
still lower energy by **0.39059 kcal/mol** and reduce maximum projected force by
**13.68%**, with continuing cap/sugar motion. The reviewed next attempt therefore
uses the **exact last accepted geometry and cached full-precision gradient**, with
fresh Sella history after the large initial deformation. It does not repeat the
clashing seed or substitute the unevaluated alternative. One bounded restart is
admitted; persistently stalled force requires another method review, not automatic
extension. Full history, alternatives and preflight limitation are recorded in
`endpoint-1-glyco-branch-plus30-v1/continuation_review.json`.

`cpd-corrected-anti1-glyco-branch-plus30-v2.service` started at **15:52:00 Denver**.
The angle, electronic method, optimizer settings and force limits are unchanged.
Limits remain **20 new gradients / 90 minutes**, four threads, 4 GiB Psi4/8 GiB
service memory, no swap and ten minutes per new gradient. The unchanged native
worker reuses its prior 24-test evidence. A new integration check confirms cached
gradient dispatch and three moving synthetic steps, and rejects both the historical
degree-unit error and an off-target native entry before Psi4; zero new QM for tests.

The single startup check verifies the exact seed reuse, fixed angle and resource
limits. Default memory admission passed with **12.304 GiB** available. Completion/
failure watcher **`2c10786b-45a0-453b-aa6a-8c34b98acb94`** is armed; estimated
full-allocation finish **17:02:01**, audit deadline **17:12:00**, hard stop
**17:22:00**, all October 11 Denver time. No periodic polling or cloud spending.
All outputs and scratch stay on mounted Archive. The storage-cleanup inventory
remains pending user review; no candidates were moved or deleted.

Current handoff: `endpoint-1-glyco-branch-plus30-v2/handoff.json`, indexed by
`current_handoff.json`. Portable record:
`docs/audits/cpd_corrected_cis_anti_i_branch_plus30_continuation_20261011.json`.
Held-out targets remain unacquired. Original references and failures remain intact;
no endpoint minimum certificate, fitting acceptance or NAMD readiness is claimed.

**Lower-conformer +15° converged; final +30° point running — 2026-10-11 Denver.**
Acknowledged complete wake `bcbc4f01-1e20-474e-9435-a3442bea3224`.
The +15° target converged on its **20th new gradient**, after **68.90 minutes**;
the allocation did not end unconverged. The v4 audit verifies 2,940 native gradient
components, 40 geometry tables and 20 accepted checkpoints/trajectory frames,
with unchanged electronic settings and all seven stereocenters. Native evidence
and every evaluated scan angle pass; maximum angle error is **4.57e-6°**.
Projected maximum/RMS gradients are **9.277482e-6 / 2.645450e-6 au**, meeting the
unchanged criteria. No further relaxation at +15° is needed. Raw full-dimensional
stationarity and endpoint minimum certification remain false.

The accepted energy is **−1364.5361163412701 Eh**, **1.324736 kcal/mol above
the lower-conformer zero**. Relative to that source, the 5′ OH torsion changes
**−16.71°**, sugar-ring torsions by up to **6.97°**, and the monitored cyclobutane
torsion by **−0.424°**. The largest adjacent monitored sugar/cap change is
**3.07°**. These gradual changes support acquisition of the remaining profile
point without relabeling the conformation; they do not establish basin closure.
Per-evaluation evidence is in `endpoint-1-glyco-branch-plus15-v1/profile_point_review.json`.

Four exposed profile offsets now have constrained convergence:
**−30/−15/0/+15°**, with energies **−1.652114/−1.162456/0/+1.324736 kcal/mol**
relative to the matched zero. Their pinned results and audits are collected in
`glycosidic-branch-profile-v1/progress-after-plus15.json`. This is development
coverage, not automatic acceptance for fitting or production.

Only `cpd-corrected-anti1-glyco-branch-plus30-v1.service` is running, started
at **14:37:44 Denver**. It uses the preregistered matched-zero-derived seed and
absolute target **135.65946348°**, with no method, seed-policy or threshold change.
Limits remain **20 new gradients / 90 minutes**, four threads, 4 GiB Psi4/8 GiB
service memory, no swap and ten minutes per gradient. Source checks, exact seed
chemistry/constraint checks and a synthetic fresh-gradient dispatch check pass;
the unchanged worker reuses its existing 24-test regression evidence. Default
memory admission passed with **12.292 GiB** available.

The single startup check verifies constraint, resource limits, Archive paths and
completion/failure watcher **`e71cc400-15c6-4cf3-bea3-fdc6f3ff0af6`**.
Estimated full-allocation finish is **15:46:55**, audit deadline **15:57:44**,
hard stop **16:07:44**, all October 11 Denver time. No periodic polling or cloud
spending. Audit +30° before any further work; if converged, review the complete
five-point profile and conformer matching before choosing the next required stage.
Held-out ±22.5° targets remain unacquired. All bulk output/scratch stays on mounted
Archive; the storage-cleanup inventory remains unapproved and untouched.

Current handoff: `endpoint-1-glyco-branch-plus30-v1/handoff.json`, indexed by
`current_handoff.json`. Portable record:
`docs/audits/cpd_corrected_cis_anti_i_branch_plus15_20261011.json`.
Prior failures remain preserved; minimum support is still restricted to the
exact capped core, with endpoint certification and NAMD readiness pending.

**Lower-conformer −30° converged; +15° running — 2026-10-11, 13:28 Denver.**
Acknowledged complete wake `98413763-3004-44dd-948a-1e539f7b9c14`.
The −30° point converged after **16 new gradients / 55.16 minutes**. The v4
audit independently verifies 2,352 native gradient components, 32 geometry tables,
16 accepted checkpoints/trajectory frames, all seven stereocenters and the original
electronic settings. Every evaluated angle passes, with maximum error **4.92e-6°**.
Final projected maximum/RMS gradients are **1.076146e-5 / 4.516710e-6 au**.
Native-evidence and scan-target verdicts pass; no further relaxation is needed
at this fixed angle. Full raw stationarity and endpoint minimum certification
remain false.

The accepted energy is **−1364.540860253643 Eh**, **0.489658 kcal/mol below
−15°** and **1.652114 kcal/mol below the lower-conformer zero**. Relative to
the −15° source, the 5′ OH torsion changes **8.68°**, sugar-ring torsions by up
to **7.94°**, and the monitored cyclobutane torsion by **0.436°**. The largest
adjacent monitored sugar/cap change during this chunk is **5.04°**. These measured
changes support continuing the provisional profile without a new conformer
relabeling; they do not establish basin closure or a global/local minimum.
The full per-evaluation review is preserved in
`endpoint-1-glyco-branch-minus30-v1/profile_point_review.json`.

The next preregistered **+15°** point starts from the frozen matched-zero-derived
seed at absolute angle **120.65946348°**. No seed, method, convergence criterion,
profile membership or energy reference changed. The unchanged scientific worker
reuses its 24-test regression evidence; a new synthetic driver check verifies
the exact installed constraint and fresh-gradient dispatch without QM.
`cpd-corrected-anti1-glyco-branch-plus15-v1.service` started at **13:27:26 Denver**,
with **20 new gradients / 90 minutes**, four threads, 4 GiB Psi4/8 GiB service
memory, no swap and a ten-minute per-gradient timeout. Default memory admission
passed with **12.400 GiB** available.

Archive mount/device checks pass for both output and scratch, and `TMPDIR` and
`PSI_SCRATCH` point there. The user's storage-cleanup inventory remains pending
review: **nothing from it was moved or deleted**. Earlier failures and their
native evidence remain preserved.

The single startup verification confirms the angle, resource limits and armed
completion/failure watcher **`bcbc4f01-1e20-474e-9435-a3442bea3224`**.
Estimated full-allocation finish is **14:36:39**, audit deadline **14:47:26**,
hard stop **14:57:26**, all October 11 Denver time. No periodic polling, automatic
multi-job chaining or cloud spending. Audit +15° before preparing the remaining
frozen +30° point. Held-out ±22.5° targets remain unacquired; fit acceptance,
endpoint certification and NAMD production readiness remain pending.

Current handoff: `endpoint-1-glyco-branch-plus15-v1/handoff.json`, indexed by
`current_handoff.json`. Portable record:
`docs/audits/cpd_corrected_cis_anti_i_branch_minus30_20261011.json`.

**Matched-angle control audited; lower-conformer −30° point running — 2026-10-11, 12:30 Denver.**
Acknowledged complete wake `0a491221-1aec-44e3-967e-ca6f16b79f14`.
The control converged in **19 new gradients / 67.38 minutes**. The independent
v4 audit passes native evidence and every evaluated scan angle: 2,793 gradient
components, 38 geometry tables and 19 accepted trajectory frames. Final projected
maximum/RMS gradients are **9.446998e-6 / 3.846348e-6 au**; maximum angle error
over the run is **2.48e-6°**. No more relaxation at this target is needed.

At the same **105.65946348°** glycosidic angle, the new conformation is
**2.79623 kcal/mol below the original reference**. Its 5′ OH cap torsion differs
by **63.33°**, sugar-ring torsions by up to **29.99°**, and the monitored
cyclobutane torsion by only **0.217°**. The valid −15° point is **1.16246 kcal/mol
below this matched-angle control**. Thus the earlier −3.95869 kcal/mol comparison
to the original zero mixed angle response and cap/sugar conformation. These are
provisional path-connected conformations; **constrained convergence does not
establish full-dimensional stationarity, basin closure or an endpoint minimum**.
Exact sources and comparisons are preserved in
`endpoint-1-glyco-branchzero-v1/matched_angle_review.json`.

`glycosidic-branch-profile-v1/design.json` freezes a separate provisional profile
on the same original angle grid: −30, −15, 0, +15, +30°. The inspected −15/0
observations are reused as exposed development data. Exact new seeds and
constraints for −30/+15/+30 are frozen before acquisition; the original reference,
original profile and failures remain intact. Held-out ±22.5° targets remain
unacquired until candidate parameters are hash-locked. Fitting requires matched
QM/MM conformations and review of continuity/closure; this acquisition design
does not automatically accept targets or combine different conformations.

Only `cpd-corrected-anti1-glyco-branch-minus30-v1.service` is running, started
at **12:29:40 Denver**. It starts from the converged −15° geometry with a further
15° rigid sugar rotation, fixing the absolute angle at **75.65946348°**.
The unchanged native worker has **20 new gradients / 90 minutes**, four threads,
4 GiB Psi4/8 GiB service memory, no swap, and a ten-minute per-gradient timeout.
All three seeds pass chemistry, bond preservation and installed-constraint checks;
a synthetic driver check verifies fresh-gradient dispatch with zero QM. Existing
24-test evidence is reused with verified unchanged sources. Admission passed the
default 12 GiB floor with **12.530 GiB** available; no resource exception was needed.

The single startup check verifies the target, limits and armed completion/failure
watcher **`98413763-3004-44dd-948a-1e539f7b9c14`**. Estimated full-allocation
finish is **13:40:27**, audit deadline **13:49:40**, hard stop **13:59:40**,
all October 11 Denver time. Audit this point before any continuation or next
target; no periodic polling, cloud spending, or automatic multi-job chaining.
Current handoff: `endpoint-1-glyco-branch-minus30-v1/handoff.json`, indexed by
`current_handoff.json`. Portable record:
`docs/audits/cpd_corrected_cis_anti_i_matched_control_profile_20261011.json`.
Minimum support remains limited to the exact capped core; endpoint certification,
fit acceptance, formal chemical/parameter review and NAMD production readiness
remain pending.

**Missed admission diagnosed; matched-angle control running — 2026-10-11, 11:17 Denver.**
The user requested status after the scheduled launch. The timer did fire at
**01:41:11**, but the deferred runner cancelled against
`cpd-anti-validation-v1/campaign_pause.json`. That is an **October 5 scientific
hold on the older MD physical ensemble**, not a pause on this corrected QM
campaign; its own text preserves bounded research authorization. No current
corrected-campaign pause file exists, and the October 10 all-stage authorization
remains active. The deferred runner incorrectly broadened the old hold's scope
and intentionally suppressed notification after interpreting it as a pause.
Consequently **no native control ran overnight**. The original cancellation,
misleading `timer_scheduled` wake receipt and frozen runner are preserved with
`endpoint-1-glyco-branchzero-v1-deferred-admission/cancellation_review.json`.

The future deferred launcher now follows the same campaign-specific pause file
as the native worker and records terminal cancelled/skipped wake states. Four
focused tests cover the unrelated legacy hold, genuine campaign pause, duplicate
avoidance and single failure notification. The legacy MD hold remains unchanged.
A direct frozen-file invocation also failed before service/native creation
because its repository import environment was missing; that attempt is retained,
and the successful launch explicitly supplies the repository environment.

Memory was initially still below the former 12 GiB floor. A plan-specific review
retains the hard **8 GiB service cap**, no swap and a **3 GiB reserve** beyond
that cap, giving an 11 GiB admission floor for this exact job. Comparable valid
jobs peaked at 6.5 and 3.4 GiB with zero swap; the journal evidence and original
blocked admissions are retained. Three tests bind this change to the exact
unchanged 20-gradient/90-minute plan. At successful launch, available memory had
risen to **12.447 GiB**, also meeting the former threshold. The native worker,
electronic method, convergence criteria and hard runtime limit are unchanged.

`cpd-corrected-anti1-glyco-branchzero-v1.service` started at **11:16:42 Denver**.
Its single startup check verifies the intended **105.65946348°** constraint,
four threads, 4 GiB Psi4/8 GiB service memory and no swap. Completion/failure
watcher **`0a491221-1aec-44e3-967e-ca6f16b79f14`** is armed. Estimated full
allocation finish is **12:25:22**, one audit deadline **12:36:42**, and hard stop
**12:46:42**, all October 11 Denver time. No periodic polling or cloud spending.
This remains a matched-angle conformational diagnostic, not minimum certification
or automatic acceptance for fitting.

Current handoff: `endpoint-1-glyco-branchzero-v1/active_handoff.json`, indexed by
`current_handoff.json`. The consumed deferred timer is no longer active. Portable
recovery record: `docs/audits/cpd_corrected_cis_anti_i_branchzero_launch_recovery_20261011.json`.

**Corrected −15° response converged; matched-angle control queued — 2026-10-11 Denver.**
Wake `11e0f9f6-b0b4-4846-9ba0-e3a2ca2d750e` was acknowledged as complete.
The repaired scan converged after **18 new gradients in 61.58 minutes**.
The v4 audit independently verifies 2,793 native gradient components (including
the reused valid seed), 38 geometry tables and 19 accepted checkpoints/trajectory
frames, with preserved electronic settings and all seven stereocenters.
Every evaluated angle passes; the largest error is **5.70e-6 degrees**.
Both native-evidence and scan-target verdicts pass. Final projected maximum/RMS
gradients are **1.200785e-5 / 4.395124e-6 au**, meeting the unchanged limits.
No further relaxation at this −15° target is needed.

This is **constrained stationarity**, not full-dimensional stationarity or an
endpoint minimum certificate. Relative to the original stationary reference,
the relaxed point is **3.95869 kcal/mol lower**, with an **84.29° 5′ OH cap
rotation**, sugar-ring torsion shifts up to **23.42°**, and only **−0.087°** change
in the monitored cyclobutane torsion. The full history is preserved in
`endpoint-1-glyco-minus15-v3/converged_branch_review.json`. The energy difference
mixes angle response with cap/sugar conformation; it is not yet an accepted
glycosidic fitting target. All 20 new wrong-angle v2 evaluations remain excluded.

`endpoint-1-glyco-branchzero-v1/` is prepared as a **matched-angle diagnostic**.
It starts from the valid converged −15° conformation, rigidly rotating the sugar
to the original reference angle **105.65946348°**. All covalent bond lengths,
monitored internal conformer torsions and seven stereocenters pass seed checks.
Only that original angle is fixed during relaxation; the other coordinates remain
free. This directly compares conformations at the same angle. It is not an
unconstrained release, a silent replacement of the original reference, or an
already admitted second fitting profile. The separate diagnostic design is frozen;
original training/held-out membership and references remain intact.

The native/optimizer worker and regression-test sources are unchanged, so the
existing 24-test evidence was reused. One new synthetic fresh-seed smoke test
confirms the changed coordinates acquire a new gradient rather than reuse the
source gradient, with no QM performed. The control is bounded to **20 new
gradients / 90 minutes**, four threads, 4 GiB Psi4/8 GiB service memory, no swap,
and a ten-minute per-gradient timeout. Estimated allocation cost is 68.68 minutes.

**No native control job has started yet.** Runtime admission stopped before
service creation because available memory was about **11.78 GiB**, below the
unchanged **12 GiB** requirement; disk space is adequate. The failed admission
is preserved in `launch_attempt1_failure.json`. A single timer retry is armed for
**01:41:11 Denver October 11** under
`cpd-corrected-anti1-glyco-branchzero-v1-admit.timer`. It rechecks normal resource
and exclusivity guards. Successful admission performs one startup verification,
arms the native completion/failure watcher and one audit deadline, and updates
the current handoff; failed admission queues one review wake. There is no periodic
memory polling or automatic retry loop. Pause files and an existing launch receipt
cancel the timer attempt. Three focused timer-runner tests pass. The pinned Codex
executable directory is supplied explicitly because the user service manager's
PATH lacks it. The collected transient timer was recreated at the same deadline;
that harmless rearming failure and its original receipts are preserved.

Current handoff: `endpoint-1-glyco-branchzero-v1/handoff.json`, indexed by
`current_handoff.json`; deferred status lives in
`endpoint-1-glyco-branchzero-v1-deferred-admission/`. After a successful timed
launch, the index points to `active_handoff.json`. To pause before admission,
stop the listed `-admit.timer` and `-admit.service` as well as setting the campaign
pause marker. Portable evidence:
`docs/audits/cpd_corrected_cis_anti_i_glyco_converged_control_20261011.json`.
No cloud spending. Minimum support remains limited to the exact capped core;
endpoint minimum certification, fit-target acceptance and NAMD readiness remain
pending.

**Wrong-angle continuation preserved; repaired retry active — 2026-10-11 Denver.**
Wake `7e919bf5-7ff3-4028-95bc-2115faa48ef6` was acknowledged with event
`complete`, matching service termination. **The intended scan failed.**
The restart code introduced an angle-unit error: Sella's public
`Constraints.fix_dihedral(target=...)` accepts degrees, but the v2 worker passed
`np.radians(target_degrees)`. Sella converted the argument again internally.
The job therefore moved toward **1.582306° instead of 90.659463°**.
All **20 new evaluations**, acquired in **68.35 minutes**, are outside the
intended target tolerance and excluded from intended-scan fitting, progression
and restart selection. The original status, worker, preflight and outputs remain
intact. `endpoint-1-glyco-minus15-v2/scientific_failure.json` records the failure
and a reproduction using the installed API with zero new QM.

The native audit verifies 3,087 gradient components (including the reused seed),
42 geometry tables and 21 accepted checkpoint/trajectory frames, with preserved
electronic settings and seven stereocenters. Its `passed` field concerns native
evidence integrity; **it does not accept the wrong-angle scan**. The separate
scientific failure takes precedence. Independent convergence correctly remained
false, but that check did not prevent off-target acquisition. The old zero-budget
preflight checked the correctly angled seed and stopped before any displaced
step; it failed to inspect the optimizer's actual configured target/residual.
That earlier preflight verdict is preserved with this documented limitation.

The repair passes degrees directly, verifies Sella's actual target and startup
residual, and rejects off-target coordinates in the parent calculator, native
child before Psi4, and accepted checkpoints. The new v4 completion auditor checks
the angle of every evaluated geometry and separates native-evidence and scan-target
verdicts. Twenty-four focused tests pass. A test using the installed Sella performs
three moving steps on a clearly labeled synthetic potential, checks the angle,
reproduces/rejects the historical double conversion, and rejects a real preserved
off-target geometry at native entry before importing Psi4. No new QM was used for
diagnosis or tests; synthetic test values are excluded from scientific evidence.

`endpoint-1-glyco-minus15-v3/` restarts from the **valid v1 evaluation-020**,
reusing its exact geometry/full-precision gradient and fresh optimizer history.
No new v2 result is reused. The original v1 cap/sugar rearrangement still requires
review and a matched reference before fitting; the wrong-angle v2 trajectory
does not resolve that issue. The repaired job's startup receipt confirms target
**90.65946347935471°** and initial residual **8.51e-13 radians**.

One job is active with **20 new gradients / 90 minutes**, four threads, 4 GiB
Psi4/8 GiB service memory, no swap and a ten-minute timeout per gradient.
Completion/failure watcher `11e0f9f6-b0b4-4846-9ba0-e3a2ca2d750e` is verified.
Estimated full-allocation finish is **01:16:37 Denver October 11**, one audit
deadline **01:31:23**, and hard stop **01:41:23**. No intermittent polling or
cloud spending. Scientific validity, progress and necessity must be reviewed
before any next job; neither optimizer completion nor constrained stationarity
certifies an endpoint minimum.

Current handoff: `endpoint-1-glyco-minus15-v3/handoff.json`, indexed by
`current_handoff.json`. Portable record:
`docs/audits/cpd_corrected_cis_anti_i_glyco_angle_recovery_20261011.json`.
Existing minimum support remains limited to the exact capped core; endpoint
minimum certification, fit-target acceptance and NAMD readiness remain false.

**First glycosidic chunk audited; conformational continuation active — 2026-10-10 Denver.**
Wake `6a78c90a-0029-4b56-8a55-ef396577668b` was acknowledged as complete.
The −15° scan stopped cleanly at **20 gradients in 64.97 minutes**, without
convergence. Independent audit verifies 2,940 native gradient components,
40 geometry tables, 20 accepted checkpoints/trajectory frames, original electronic
settings and all seven stereocenters. The prescribed angle stayed within
3.13e-6 degrees throughout. Final projected maximum/RMS gradients are
**0.00372654 / 0.000944722 au**, above the unchanged convergence criteria.

Energy decreased by 0.00744937 hartree during this chunk, reaching **2.31461
kcal/mol below the original stationary reference**. This is ongoing relaxation,
not a qualified torsion target. The 5′ hydroxyl cap rotated 52.91°, sugar-ring
torsions shifted by up to 14.52°, and the monitored cyclobutane torsion changed
only 0.65°. This suggests departure from the original conformation; a distinct
basin has not yet been established. All product/sugar stereocenters remain intact.
The original stationary reference and all intermediate states are preserved.
`endpoint-1-glyco-minus15-v1/conformational_progress_review.json` records the
full projected-gradient and torsion histories. Before fitting, resolve this
coupled cap/sugar relaxation and assess a matched zero-offset control; do not
treat the energy difference as a pure glycosidic contribution or silently replace
the original zero reference.

One continuation, `endpoint-1-glyco-minus15-v2/`, reuses the exact last accepted
geometry and full-precision gradient at the same frozen angle. Its purpose is
to identify the relaxed destination before selecting further reference work.
Fresh optimizer history follows the recorded restart policy. The continuation
checks preceding audit, target, method, model, runtime and binary gradient
identity, and sets the explicit original angle in Sella. Twenty-one focused tests
pass. A preflight using the installed optimizer and existing gradient confirms
reuse, accepted checkpoint writing and a clean test-only zero-allocation stop;
it performs no new QM.

The active chunk is capped at **20 new gradients / 90 minutes**, with four
threads, 4 GiB Psi4/8 GiB service memory, no swap and a ten-minute timeout per
gradient. The preceding native mean/max times were 194.20/208.19 seconds;
systemd reported 6.5G peak memory and no swap. Stable cost and continued descent
support one further chunk without a new timing benchmark or method change.
Completion/failure watcher `7e919bf5-7ff3-4028-95bc-2115faa48ef6` passed the
single startup check. Estimated full-allocation finish is **00:02:46 Denver
October 11**, one audit deadline is **00:17:32**, and the hard stop is **00:27:32**.
No intermittent polling or cloud spending. Audit progress and conformational
changes again before any subsequent job.

Endpoint minimum certification and fit-target acceptance remain false; existing
minimum support remains limited to the exact capped core. Current handoff:
`endpoint-1-glyco-minus15-v2/handoff.json`, indexed by `current_handoff.json`.
Portable record: `docs/audits/cpd_corrected_cis_anti_i_glyco_branch_continuation_20261010.json`.
All earlier failures and assessments remain preserved.

**Endpoint stationary; first glycosidic training scan active — 2026-10-10 Denver.**
Wake `fd45703a-6ab2-4d89-b545-18e30bd42eaa` was acknowledged as complete.
The continuation converged after **two new gradients in 389.39 service seconds
(6.49 minutes)**. Independent native audit verifies 441 gradient components
(294 new plus the reused seed), six printed geometry tables, three accepted
checkpoints/trajectory frames, full-precision binaries, electronic settings and
all seven stereocenters. Maximum atom-gradient norm is **1.4684165e-5 au**,
RMS **5.4113661e-6 au**, meeting the unchanged 1.5e-5/1e-5 criteria.
The tiny net energy increase, 8.16e-9 hartree, is retained in the audit.
No further unconstrained endpoint optimization is presently justified.

The first read-only auditor failed in its final summary because it indexed a
ten-record energy window in a three-record chunk. Its source and failure receipt
are preserved; the versioned auditor handles the available window and passes.
No QM was rerun. `stationary_endpoint_review-v1/review_packet.json` contains the
exact stationary geometry and endpoint-exchanged mapping for formal human review.
Both mappings represent **one distinct QM reference**, not independent data.

The **49-atom endpoint is stationary, not minimum-certified**. Existing local
minimum support applies only to the exact 36-atom capped core. A full endpoint
Hessian is deferred: the current method's budget estimate is 288 additional
gradients, about 15.50 hours at measured cost. Preliminary constrained response
acquisition does not require claiming a full-dimensional minimum; revisit
curvature work if scan branches or fitting residuals identify a need.
Chemical review, parameter qualification and NAMD readiness remain pending.

`glycosidic-training-v1/design.json` freezes the planned training offsets
−30°, −15°, 0°, +15°, +30° about the stationary O4′–C1′–N1–C2 angle
105.65946348°. The four displaced seeds preserve the molecular graph, bond
lengths and all seven stereocenters. Zero offset reuses the audited reference;
held-out ±22.5° targets remain unacquired until fitted parameters are locked.
Branch changes must be retained and reviewed, with matching QM/MM constraints
and reference basin. The electrostatic dipole convention still needs resolution
before charge-reference acquisition or fitting.

Only the **−15° scan** has launched, at fixed torsion 90.65946348°, with other
coordinates relaxed. Its allocation is **20 new gradients and 90 minutes**,
four threads, 4 GiB Psi4/8 GiB service memory, no swap and a ten-minute timeout
per gradient. Fifteen focused tests pass. A synthetic-potential integration
preflight verifies the installed constrained optimizer path, fresh gradient
acquisition at displaced coordinates and accepted checkpoints, with no QM.
Independent projected-gradient criteria and angle error are checked separately
from raw forces; constrained convergence is not minimum certification.

`cpd-corrected-anti1-glyco-minus15-v1.service` passed its single startup check.
Completion/failure watcher `6a78c90a-0029-4b56-8a55-ef396577668b` is armed.
The allocation estimate is 65.1 minutes; one audit deadline is **23:07:53 Denver**
on October 10 and the hard stop is **23:17:53**. No intermittent polling or cloud
spending. On wake, audit native evidence, constrained progress, branch behavior
and cost before another job. Current handoff: `endpoint-1-glyco-minus15-v1/handoff.json`,
indexed by `current_handoff.json`. Portable evidence index:
`docs/audits/cpd_corrected_cis_anti_i_endpoint_stationary_scans_20261010.json`.
All earlier failures, assessments and historical handoffs remain preserved.

**Endpoint chunk audited; shorter continuation active — 2026-10-10 Denver.**
Wake `aa576b15-f5c8-46c9-b874-230f0ada295e` was acknowledged as complete.
This was a clean **allocation-boundary stop**, not optimizer convergence. Thirty
new gradients completed in 5773.85 service seconds (96.23 minutes); their mean
native time was 191.84 seconds and maximum 213.86 seconds.

`endpoint-1-optimization-v1/completion_audit.json` independently reopens the
30 new evaluations plus reused pilot result: 4,557 native gradient components,
62 printed geometry tables, input/returned binaries, original electronic options,
actual basis/frozen-core occupations, all seven stereocenters and source hashes.
All 31 accepted XYZ checkpoints and 31 optimizer trajectory frames have matching
native coordinates, energies and forces. The last accepted restart is backed by
a full-precision saved gradient. No task was rerun for this audit.

Maximum atom-gradient norm decreased from 0.0297588 to **2.369859e-5 au**;
RMS is **9.974772e-6 au**. RMS meets its 1e-5 criterion, while the maximum remains
above 1.5e-5. Energy fell by 0.0234400 hartree and the final ten evaluations still
improve force/energy. This is substantial ongoing progress, with no evidence of
a stall. The limits and electronic method remain unchanged. No endpoint
stationarity or minimum certification is asserted.

`endpoint-1-optimization-v2/` starts from that exact last accepted geometry and
reuses its full-precision gradient. Fresh Sella history follows the recorded
restart policy. The reduced allocation is **15 new gradients and one hour**,
with a ten-minute per-gradient timeout, four threads, 4 GiB Psi4/8 GiB service
memory and no swap. The frozen context, seed identity and smaller allocation
guards were checked without QM. Native-gradient and optimizer behavior are
unchanged from the previously tested implementation; no redundant test suite
or timing benchmark ran.

`cpd-corrected-anti1-endpoint1-optimization-v2.service` is active, with verified
completion/failure watcher `fd45703a-6ab2-4d89-b545-18e30bd42eaa`.
Estimated full-allocation finish is 22:23 Denver time October 10, one audit
deadline at 22:25, and hard stop at 22:35. Convergence can end it earlier.
No intermittent polling, cloud spending or blind continuation. On the wake,
audit once and distinguish convergence from a chunk boundary before choosing
curvature/reference work or another justified continuation. All previous failed
and incomplete verdicts remain preserved. Current handoff:
`endpoint-1-optimization-v2/handoff.json`, also indexed by `current_handoff.json`.

**Endpoint pilot recovered without rerun; Sella optimization active — 2026-10-10 Denver.**
Wake `49f5471b-b1bb-4c75-a080-2c735075820f` was acknowledged as **failed**.
The original service, native output, frozen worker, failed assessment and traceback
remain intact. The native MP2 calculation completed successfully in about 197
seconds (197.448 service seconds); the worker then failed a literal whitespace
check. DiskDFJK prints seven spaces after `Fitting Condition:`, while the check
expected eight. Every native value is the intended 1e-10.

`endpoint-1-pilot-recovery-v1/completion_audit.json` verifies all 147 gradient
components, two printed geometry tables, charge/multiplicity, atom order, corrected
product and sugar stereochemistry, SCF convergence and response residual 3.964e-11.
It also reconciles the preflight JK count: the standalone builder reported 2396
spherical functions, while the actual SCF driver uses 2737 Cartesian JK functions
to match the Cartesian orbital basis. Replaying the installed driver's basis
construction confirms 449 orbital, 2737 JK and 1820 spherical RI functions, with
27 frozen core orbitals. No electronic settings changed and no QM reran.

The full-precision in-memory gradient was not saved before the old assertion.
The recovery explicitly uses the native 12-decimal gradient table, with at most
5e-13 hartree/bohr rounding per component, and the exact pinned input geometry.
This is ample precision for the initial Sella state; it is not presented as a
recovered binary array. The original `new_gradients=0` flag reflects failed worker
auditing; the supplemental record correctly accounts for one completed native
gradient. Maximum atom-gradient norm is 0.0297588 au, so the endpoint is not
stationary and receives no minimum claim.

The repaired parser reads numeric fitting conditions regardless of whitespace
and rejects missing or changed values. Future workers save full-precision returned
coordinates and gradients before downstream audits. Seventeen focused tests pass.
An integration check using the installed Sella and recovered gradient verifies
seed reuse, an accepted restart checkpoint and a clean allocation-boundary stop,
with zero new QM calculations.

`cpd-corrected-anti1-endpoint1-optimization-v1.service` is active for a bounded
Sella chunk: at most **30 new gradients and two hours**, four threads, 4 GiB
Psi4/8 GiB service memory, no swap, and a ten-minute timeout per gradient. The
pilot used 3.2G peak memory and no swap. Thirty gradients at its measured cost
would take 98.5 minutes; no additional benchmark or method change is justified.
The seed gradient is reused, every evaluated trial is retained, and each accepted
geometry has a matching-gradient restart checkpoint. A planned chunk boundary is
reported separately from optimizer convergence and native failure.

Completion/failure watcher `aa576b15-f5c8-46c9-b874-230f0ada295e` is verified
armed. Estimated allocation finish is 21:35 Denver time, one audit deadline at
21:45, and hard stop at 21:55 on October 10. No intermittent polling or cloud
spending. On wake, audit native evidence and progress once before admitting any
continuation. Optimizer completion remains distinct from local-minimum
certification. Current handoff: `endpoint-1-optimization-v1/handoff.json`, also
pointed to by `current_handoff.json`. Broad all-stage authorization remains active.

**Corrected core local minimum supported; sugar endpoint pilot active — 2026-10-10 Denver.**
Wake `766e12cc-361c-4f96-a1d8-094123680620` was acknowledged. All 16 low-mode
gradients completed in 915.94 service seconds (15.27 minutes); native work took
907.54 seconds. The completion audit verifies all 1,728 gradient components, 32
printed geometry tables, original electronic settings, atom order and corrected
identity. The initial read-only audit used a Python environment without RDKit;
that failure is preserved, and the unchanged audit succeeded in the pinned runtime.
No QM was repeated.

`core_local_minimum_assessment.json` now records a **numerically supported local
harmonic minimum for the exact 36-atom capped core** at the original frozen-core
DF-MP2/6-31G(d) settings. This decision combines independent stationarity, all 102
positive internal Hessian modes, and two-scale checks of the four most sensitive
modes. Energy-derived and extrapolated gradient curvatures differ by 0.29–0.56%;
these are observed results, not a new percentage gate.

The retained full Hessian-vector products also measure coupling to the other 98
internal modes. With their previously audited block held fixed, the coupled
sensitivity matrices remain positive at both steps and after extrapolation. Their
lowest frequencies are 57.95987, 57.95835 and 57.95444 cm⁻¹. The largest Schur
coupling correction is 4.80e-7, compared with a smallest curvature near 1.27e-4
hartree/(bohr² amu). The full hybrid matrix step difference is 6.29e-5 and its
extrapolation correction 2.10e-5; these empirical sensitivities are not rigorous
error bounds or a second independently acquired full Hessian. Raw asymmetry,
external-mode artifacts and every historical failed verdict remain preserved.
No additional core QM is warranted by an identified unresolved question.
The exact-geometry review packet is updated separately; formal human chemical
review, parameter qualification and NAMD readiness remain outstanding.

`endpoint-seeds-v2/` contains two newly rebuilt neutral 49-atom, 52-bond
C16H22N4O7 models: complete corrected CPD, one D-deoxyribose with 5′/3′ OH caps,
and one N1-methyl cap. Only the corrected certified core supplies reused
coordinates. The TTD graph supplies sugar stereochemistry; its original
coordinates and all legacy anti boundary coordinates are excluded. Three
attempts with tight-core embedding failed in `endpoint-seeds-v1/` and are retained.
Fresh stereochemical embedding followed by proper rotation and fixed-core UFF
seed relaxation succeeded for both models. UFF is seed preparation only.
Independent checks verify the exact graph, valences, charge, all seven centers,
contacts and RDKit/Open Babel identity agreement; six deliberately inverted sugar
centers are rejected by the audit.

The two isolated one-sugar models have the same stereochemical molecular identity.
An explicit endpoint permutation preserves every bond/order, element and all
coordinate stereocenters. Optimize one unique endpoint reference first and derive
its paired mapping from the same calculation. This saves a duplicate reference
optimization, but does not create independent validation data or imply equivalent
endpoint environments in full DNA. Independently embedded seeds can still differ
in conformation; no conformational equivalence is inferred from the InChIKey.
Neither model covers phosphate or two-sugar coupled terms.

`endpoint_reference_design_v1.json` freezes the first development reference and
prospective glycosidic membership: training offsets -30, -15, 0, +15, +30 degrees;
held-out offsets +/-22.5 degrees acquired only after parameter hash lock. Exact
scan constraints/geometries must be pinned before acquisition. The legacy dipole
convention conflict remains explicitly pending before electrostatic acquisition
or fitting; it does not affect this geometry pilot.

`cpd-corrected-anti1-endpoint1-pilot-v1.service` is active for **one gradient**,
using four threads, 4 GiB Psi4/8 GiB service memory and no swap. Eight focused tests
pass, alongside the six sugar-inversion checks. Its completion/failure watcher
is verified armed with token `49f5471b-b1bb-4c75-a080-2c735075820f`.
Expected finish is approximately 19:49 Denver time, one audit deadline at 19:57,
and hard stop at 20:00 on October 10 (15-minute total cap). No polling or cloud
spending. On the wake, audit native evidence and measured cost once, then admit
a checkpointed Sella optimization if supported, reusing the exact pilot gradient.
Broad all-stage authorization continues; no registry gate or production status
has changed. Current handoff: `endpoint-1-pilot-v1/handoff.json`.

**Full Hessian audited; four-mode numerical check active — 2026-10-10 Denver.**
Wake `f368588e-b371-421c-bb99-1f95cc5fe9e3` was acknowledged. Batch two
completed its 106 gradients and assembly in 6265.92 service seconds (104.43
minutes). Its independent completion audit verifies 11,448 native gradient
components, 212 printed geometry tables, exact input/returned coordinates,
stereochemistry, original electronic settings and complete displacement pairs.
Mean gradient time was 58.49 seconds, maximum 62.49; systemd recorded 4.5G peak
memory and zero swap. All 210 displaced gradients plus the reused reference are
now available; no missing task or repeated native calculation.

`hessian-stage2-v3/assembly/independent_completion_audit.json` rechecks all result,
input and native hashes, reconstructs the Hessian and independently builds the
six mass-weighted rigid-body directions. Cartesian reconstruction agrees within
7.56e-13 hartree/bohr²; independent internal-mode frequencies agree within
1.32e-11 cm⁻¹. There are **102 positive vibrational modes**, lowest 58.5231 cm⁻¹.
Unprojected external-mode artifacts, including -9.7705 cm⁻¹, remain recorded;
the audit verifies the six rigid-body directions rather than deleting selected
negative internal modes. A syntax error in the first read-only audit script is
preserved; its corrected copy used existing data and no QM rerun.

Minimum certification remains pending numerical sensitivity. The raw Hessian is
not exactly symmetric; the four lowest modes (58.52, 77.66, 83.92, 100.56 cm⁻¹)
also have the largest antisymmetric-action/curvature ratios, approximately 50%,
37%, 28% and 19%. These ratios guide a finite diagnostic allocation; they are
neither calibrated error bars nor a new universal percentage gate.

`low-mode-check-v1/` now runs 16 gradients: +/-0.04 and +/-0.02 bohr along each
of those four normalized Cartesian mode directions, with unchanged original QM
settings. All prepared geometries preserve corrected identity. Existing reference
gradients are reused. The worker reports energy-derived curvature, two-scale and
Richardson gradient curvature, and the coupled four-mode matrix; complete
Hessian-vector products are retained to assess coupling to the remaining modes.
Completion does not automatically certify a minimum or trigger another job.

`cpd-corrected-anti1-low-modes-v1.service` has a 30-minute total cap, three-minute
task timeout, complete-pair admission checks, four threads, 4 GiB Psi4/8 GiB
service memory and no swap. Twenty-six focused tests passed; preparation also
verified mode mass normalization and correspondence to the source Hessian.
Completion/failure watcher `766e12cc-361c-4f96-a1d8-094123680620` is verified
armed. Expected finish is about 19:33 Denver time, with a one-shot audit deadline
at 19:41 and hard stop at 19:46 on October 10. No intermittent polling or cloud
spending. All earlier failures and their original verdicts remain preserved.

On completion, acknowledge and audit native outputs once, then assess curvature
signs, absolute step corrections, energy/gradient consistency, mutual coupling and
remaining-mode sensitivity. Use that evidence to decide whether a local harmonic
minimum is sufficiently supported or a specific further calculation is necessary.
Do not repeat the full Hessian, relax a percentage gate, or run additional probes
without an identified unresolved question. Parameter and MD qualification remain
separate from this local QM assessment; broad all-stage authorization continues.

**Hessian batch one audited; batch two active — 2026-10-10.**
Wake `4feec596-92af-44c7-8057-a4783e22b10b` was acknowledged. Batch one
completed 104 new gradients plus the reused reference in 6109.18 service seconds
(101.82 minutes). `hessian-stage2-v3/batch-1/completion_delivery_audit.json`
independently verifies all hashes, native energies and 11,340 gradient components,
210 printed geometry tables, exact returned geometry/atom order, corrected identity,
original basis/convergence settings and all 52 complete displacement pairs.
Maximum response residual is 9.245e-11. No calculation was repeated for this audit.

New gradients averaged 58.18 seconds, maximum 62.74 seconds, with no sustained
slowdown. Systemd recorded 2.6G peak memory and zero swap; average CPU utilization
was about 3.75 cores within the four-core allocation. The remaining work fits the
existing cap. No measured benefit supports changing the thread count or electronic
method now; completing the reusable gradient plan followed by targeted uncertain-mode
checks is the selected next step.

The 52-direction partial Hessian has raw antisymmetry maximum 1.23709e-4 and
spectral norm 6.22248e-4 hartree/(bohr² amu). Its symmetric subspace eigenvalues
are positive, but the lowest is 3.01611e-4, so numerical sensitivity matters for
weak curvature. Antisymmetry is not a rigorous bound on symmetric errors. This
partial subspace neither represents all vibrational modes nor certifies a minimum.
The raw matrix is preserved in `batch-1/raw_partial_hessian.npy`.

`batch1_continuation_decision.json` records admission of the remaining 106 gradients
(53 pairs). `cpd-corrected-anti1-hessian-batch-2-v3.service` is active, using the
same frozen worker, four threads, 4 GiB Psi4/8 GiB service memory, no swap and a
three-hour total cap. Expected finish from measured batch-one performance is about
19:12 Denver time October 10, including assembly margin. The completion/failure
watcher is verified armed with token `f368588e-b371-421c-bb99-1f95cc5fe9e3`, one
audit deadline at 20:00 and hard stop at 20:26. No intermittent polling or cloud
spending. The worker is unchanged from the 28 passing tests; no redundant tests ran.

On completion, acknowledge the token and audit native results and assembly once.
Preserve raw asymmetry and all modes, verify the independent Hessian reconstruction,
and inspect rigid-body/internal modes and low-mode numerical sensitivity before
claiming a minimum. A successful process or assembled Hessian remains diagnostic.
All prior failures, the original reference-equality failure, and the failed 5%
directional check remain intact. No fitting, registry promotion or MD was launched.

**Original-method curvature audited; diagnostic Hessian batch one active — 2026-10-10.**
Wake `3e61db64-8efc-4a53-8617-869211c872a0` was acknowledged. All four native
gradients completed in 225.33 seconds (227.59 service seconds). The independent
completion audit verifies native energies, all gradient components, both printed
geometry tables per task, returned coordinates, corrected stereochemistry, basis
sizes and original convergence/conditioning settings. An initial audit parser
expected one geometry table; its failed source/receipt is preserved and the revised
parser checks both. No scientific calculation was repeated for this audit repair.

Directional gradient curvatures are 0.6377947974 and 0.6376542588 hartree/bohr²
at Cartesian unit-direction steps 0.02 and 0.01 bohr: 0.0220% difference.
Richardson curvature is 0.6376074125; the independent energy-based curvature is
0.6377754145 (0.0263% difference). Both are positive and well resolved in this
stiff direction. Extrapolated energy slope is 3.46605e-6 hartree/bohr; discrepancies
from the four original-method reference gradients remain 1.05e-6–1.78e-6. These
absolute differences are retained. This is useful diagnostic evidence, not exact
derivative qualification, soft-mode validation, or minimum certification.

`curvature_to_hessian_admission.json` admits diagnostic acquisition with unchanged
original MP2 settings and a doubled Psi4 displacement size of 0.01. Psi4 uses
mass-weighted symmetry-adapted Cartesian displacements, so this is not identical
to the pilot's normalized Cartesian direction. All 211 generated inputs replay
exactly and pass corrected identity; maximum Cartesian component displacement is
0.009645 bohr. The original successful QCEngine reference is reused with exact
analytic-gradient input bytes and independent stationarity verification. Its old
failed equality-gate verdict remains unchanged.

The active root is `hessian-stage2-v3/`. The preparation-only `hessian-stage2-v2/`
failure is preserved: Psi4 included its Hessian-only `FINDIF__DISP_SIZE` keyword in
the analytic-gradient input, preventing exact reference reuse. V3 explicitly strips
only that generator keyword from gradient tasks while retaining it in the Hessian
plan and exact displaced geometries. Replay verifies this narrow normalization;
all physical electronic options are unchanged. Zero QM evaluations were used in
preparation or recovery. Twenty-eight focused tests pass, including raw Hessian
reconstruction, mass weighting, pair boundaries and watcher behavior. A synthetic
test on the actual 105 displacement directions agrees within 4.3e-13; those
synthetic gradients are software tests, not molecular evidence.

`cpd-corrected-anti1-hessian-batch-1-v3.service` is active with 104 new gradients
(52 complete pairs) plus the reused reference. Expected native duration is about
1.6 hours. Each batch has a three-hour total cap, four threads, 4 GiB Psi4/8 GiB
service memory, no swap, per-task checkpoints and bounded stall detection.
The completion/failure watcher is armed with token
`4feec596-92af-44c7-8057-a4783e22b10b`. Expected finish is approximately 17:20
Denver time October 10, with a one-shot audit deadline at 18:14 and hard stop at
18:42. No intermittent polling or cloud spending.

On completion, acknowledge the token and audit batch one before admitting the
remaining 106 gradients in batch two. Review necessity, measured performance,
resource use and alternatives at that boundary. Final assembly saves the raw
Hessian asymmetry before Psi4 symmetrization, independently reconstructs the
Cartesian Hessian, and retains normal modes without clipping. Automatic minimum
certification is disabled for this diagnostic series. Numerical and low-mode
review must establish any later minimum claim; parameter fitting and MD readiness
remain separate. All-stage user authorization remains in force.

**Threshold reassessed; original-method curvature pilot active — 2026-10-10.**
The user requested a historical review of the 5% rule and the next best attempt.
`threshold_reassessment_20261010.json` records the decision and native evidence.
The 5% directional-slope cutoff and 1e-8 reference-gradient equality cutoff were
local diagnostic heuristics, without a literature-derived or measured uncertainty
basis for use as blanket campaign gates. The former failed result remains failed
under its original rule; it has not been relabeled or replaced by a convenient 10%
rule. The historical numerical-method hold below is superseded for this pilot.

Reanalysis of the existing conditioned results gives a Richardson-extrapolated
slope discrepancy of 1.27522e-5 hartree/bohr (8.65%). Step halving does not remove
it, and it is comparable in scale to the atom-gradient stationarity limit, though
the norms differ. It is neither proven harmless nor an 8.65% thermal-stability
error. The 1e-7 conditioning change is not adopted for optimization or certification.

All four existing original-method reference gradients were independently checked
against native tables and remain stationary at the unchanged force limits.
Historical evidence was rechecked: 19 native gradient files from the earlier
two-step and soft-mode diagnostics, plus all 20 fresh-Sella result/native hashes.
Fresh Sella resolved the previous constrained optimizer stall without looser force
limits; it is already our current optimizer. Larger-step probes and targeted soft
modes previously separated useful positive-curvature evidence from uncertain
stiffness. Old misidentified anti geometries supply method history only.

The [FHI-aims numerical-vibration guidance](https://fhi-aims.org/uploads/manual/Ch4/S6.html)
explains the displacement tradeoff between noise and anharmonicity and calls for
explicit step-size checks. [Psi4's optimization guidance](https://psicode.org/psi4manual/master/optking.html)
uses force, displacement and energy convergence criteria; neither provides a
universal 5% directional-derivative requirement for this campaign.

`original-method-curvature-pilot-v1/` now runs four sequential MP2 gradients at
displacements +/-0.02 and +/-0.01 bohr along the previous check's unit direction,
using the original optimized geometry and original electronic settings. This is
not asserted to be the softest mode. Existing reference gradients are reused.
The four calculations return both energies and gradients, enabling independent
curvature estimates and Richardson/step-size comparisons before a full Hessian.
Reports include absolute slope errors and empirical sensitivity scales; the latter
are not guaranteed error bounds. Completion means verified acquisition, not a
numerical-adequacy pass, minimum certificate, or readiness for MD.

Service `cpd-corrected-anti1-original-curvature-v1` has a 15-minute total cap,
three-minute per-task timeout, four threads, 4 GiB Psi4/8 GiB service memory and
no swap. Expected duration is about four minutes. Twenty-three targeted tests pass.
Completion/failure watcher `3e61db64-8efc-4a53-8617-869211c872a0` is verified armed
with one nine-minute audit deadline. No intermittent polling or cloud spending.
On its wake, acknowledge the token and audit once. Use the measured curvature,
step dependence and noise to decide admission and step size for a diagnostic
Hessian chunk. Full-Hessian and uncertain low-mode checks still precede minimum
certification. A resolved contradiction calls for a concrete method change, not
another tolerance sweep. Broad all-stage authorization remains in force.

**Directional consistency failed; numerical-method hold — 2026-10-10.**
Wake `757ceb1b-d217-4ef7-8678-8e937207215c` was acknowledged. All four native
energy calculations completed normally in 67.77 seconds (~69.88 service seconds).
The source-pinned completion audit verifies every native energy and input/output
geometry, units, atom order, corrected identity, basis sizes, frozen-core count,
convergence thresholds and declared fitting condition. No task needs rerunning.

The analytic directional slope is 1.47465985e-4 hartree/bohr. Centered energy slopes
at 0.005/0.0025 bohr are 1.34329559e-4/1.34617744e-4, respectively: errors
8.9081%/8.7127% fail the unchanged 5% limit. Step halving passes. Thus the improved
repeatability at fitting threshold 1e-7 is insufficient to qualify its gradient;
no reoptimization or Hessian was launched. This is a scientific consistency failure,
not a native crash, optimizer failure, or minimum certificate.

`method-review-v1/method_review.json` records the read-only implementation review,
rejected automatic continuations and remaining method choices. Official tagged Psi4
v1.11 sources confirm eigenvalue filtering in the fitting-metric machinery; this
inspection does not establish the exact installed-binary implementation or prove the
root cause. A single inexpensive auxiliary-metric preflight (no SCF/MP2 evaluation)
found DEF2-UNIVERSAL-JKFIT worse conditioned in this Cartesian setup, so no electronic
calculations were launched with that alternative. No further threshold sweep.

`method-review-v1/reproduction-evidence/` preserves the five existing native outputs
(reference gradient and four energies), exact inputs/results and a hashed manifest.
`numerical_method_hold.json` closes further scientific-stage admission pending a
concrete numerical-method resolution. This is not a user pause or revocation of broad
compute authorization. The next decision must specify a consistent auxiliary-metric
or alternative gradient implementation, its comparability, a small frozen diagnostic
and measured resource limits before restarting refinement. Preserve both successful
reproducibility and failed derivative checks; do not waive either limit retroactively.

No CPD calculation is active. There is no idle polling or recurring review timer;
future admitted jobs must arm completion/failure and one-shot deadline triggers.
No cloud spending, parameter promotion, minimum certification or production-readiness
claim. This block supersedes the active-probe status below.

**Conditioned gradient reproducibility passed; directional energy check launched — 2026-10-10.**
Wake `96db8ae9-1954-407c-9dc7-8f2397bbf5a1` was acknowledged. The final
conditioning diagnostic completed all three native gradients successfully in
166.71 seconds. Its independent audit reconstructs energies and every gradient
component from native tables, verifies all geometries/identity and checks the actual
1e-7 fitting threshold in native output. Pairwise gradient spread 4.3467e-9 au
passes the unchanged 1e-8 limit; energy spread is 5.1671e-10 hartree.

The revised numerical setting shifts the reference energy by about -0.2361 kcal/mol
and gives maximum atom gradient 8.7896e-5 au, which is **not stationary** under the
original 1.5e-5 threshold. Reproducibility is qualified only at this geometry;
minimum certification, parameters and simulation readiness remain pending. The
original Hessian failure and both preceding diagnostic outcomes remain preserved.

Provenance correction: Psi4 appended the next case's memory/thread setup lines to
the earlier still-open output file after its result hash was recorded. The original
hash matches an exact native prefix; the suffix contains only those setup lines.
`reference-conditioning-diagnostic-v2/independent_review.json` records this explicitly
and pins final immutable native snapshots. No native calculation was rerun for this
logging issue. The new worker closes outputs before hashing them.

`conditioned_method_continuation_decision.json` admits only four energy probes in
`conditioned-directional-check-v1/`, reusing the qualified `schema-2` gradient.
The normalized reference-gradient direction and symmetric steps +/-0.005 and
+/-0.0025 bohr are frozen before acquisition; all four geometries pass identity.
Both centered slopes must agree with the analytic slope within max(1e-6 au, 5%);
step-halving disagreement must be within max(1e-6 au, 2%). These are explicit local
derivative checks, not a Hessian or a proof of global force consistency.

The service `cpd-corrected-anti1-conditioned-directional-v1` has a 15-minute total
cap (14m45s runtime plus 15s shutdown grace), four threads/4 GiB Psi4, 8 GiB service
memory and no swap. Each energy task has a three-minute stall limit; each result
is checkpointed. Twenty targeted tests pass. Watcher startup now uses filesystem
events too. Completion/failure trigger `757ceb1b-d217-4ef7-8678-8e937207215c` is
verified armed with one nine-minute audit deadline. No intermittent polling.

On completion, acknowledge the new token and audit native results/recorded criteria
once. `conditioned_directional_handoff_20261010.json` pins the continuation evidence.
If both slopes and step-halving pass, prepare one bounded fresh optimization under
the revised options before rebuilding a Hessian plan; broad authorization permits
that normal continuation. If a criterion fails, preserve it and diagnose the method
rather than retrying blindly. No more threshold sweep is planned. The original
Hessian consumed one reference gradient (~59 s) and zero displaced tasks. No cloud
spending, automatic registry promotion or minimum certification.

**Completion-trigger monitoring; final conditioning diagnostic active — 2026-10-10.**
The user explicitly requested timers/triggers rather than intermittent polling.
`event_driven_monitoring_policy_20261010.json` records that standing instruction:
arm process-exit/file-change completion and failure triggers plus a one-shot audit
deadline for every native job, including short diagnostics. Re-enter on a delivered
event, deadline or user request. Audit sufficient completed evidence once; repeat
checks only for changed evidence or unresolved concerns. Do not poll simulation
progress from the model between these events.

The 1e-8 fitting-threshold diagnostic completed all three native gradients in
170.70 seconds. Its largest pairwise gradient difference is 5.0201e-8 au, about
44 times smaller than the original discrepancy but above the unchanged 1e-8
consistency limit; the revised forces are also not stationary. Its failed criterion,
all native outputs and independent review remain preserved. It was not accepted.

One further finite diagnostic, `reference-conditioning-diagnostic-v2/`, tests the
same three fixed-geometry cases at fitting threshold 1e-7, with the same ten-minute
hard cap and memory/thread limits. The `reference-conditioning-diagnostic-v2-service/`
attachment observes native process exit using a blocking pidfd, then publishes status
for the existing durable campaign watcher. The watcher was verified armed, with
completion/failure delivery and one audit deadline; it does not launch native work.
All original and revised scientific outputs remain separate.

On its completion wake: acknowledge the token, review the native tables and all
three diagnostic results once, and preserve process completion separately from
`reproducibility_pass`. If the declared limit still fails, stop this automatic
threshold sequence and prepare a numerical-method review. If it passes, first
review the method change and energy/gradient consistency, then perform a bounded
fresh optimization before preparing any revised Hessian inputs. No old stationarity
or certification transfers to changed numerical settings. The original Hessian
batch remains failed with zero displaced tasks; the three-hour Hessian allocations
remain unspent. Broad all-stage user authorization still applies; no cloud spending.

**Hessian reference check stopped; numerical diagnostic active — 2026-10-10.**
Batch one in `hessian-stage2-v1/` stopped after one successful native reference
gradient failed the independent consistency audit. No displaced calculation ran.
The energy difference from optimization is 5.70e-9 hartree, within its 1e-8 limit;
the largest gradient-component difference is 2.21e-6 hartree/bohr, above the
1e-8 reproducibility limit. Both gradients satisfy the original stationarity limits.
The failed assessment, native output and completion acknowledgement are preserved.
This supersedes the active-batch status below; minimum certification remains pending.

`reference-api-diagnostic-v1/` completed two bounded gradients and an independent
native-table audit. The energy difference tracks direct-text versus QCSchema molecule
construction even though geometries differ by less than 9e-16 bohr; repeat-gradient
noise also exceeds the original 1e-8 consistency limit. The actual Cartesian JK-fit
metric has condition number about 5.89e11. A separate spherical-metric calculation
is preserved as a diagnostic and is not substituted for the native Cartesian basis.
No root cause or numerical waiver is asserted from these observations alone.

`reference-conditioning-diagnostic-v1/` is testing a declared auxiliary fitting
threshold of 1e-8 with three fixed-geometry gradients (text, schema, schema repeat).
It has a ten-minute hard cap, four threads, 4 GiB Psi4/8 GiB service memory and no
swap. Energy/force changes and native convergence will be audited before adopting
any revised numerical protocol. All original protocols and failures remain intact.
The full Hessian and downstream work remain unlaunched pending this audit; broad
user authorization continues to apply. No cloud spending.

**Corrected-core Hessian batch one active — 2026-10-10.**
The expanded user authorization below is recorded and in force. The exact 211-task
preview was frozen into `cpd-corrected-cis-anti-i-refinement-v1/hessian-stage2-v1/`.
All regenerated task bytes and displaced stereochemistries pass; 24 targeted tests
passed, including checkpoint-pair, time-boundary, native-table and watcher checks.
The runner uses the existing Psi4/QCEngine task engine, with an isolated process and
immutable result per gradient. Reference energy/gradient must match the optimized
candidate before displaced tasks proceed.

`cpd-corrected-anti1-hessian-batch-1-v1.service` is active. Verified service settings:
2h59m45s runtime plus 15s shutdown grace inside the three-hour cap; four-core quota;
8 GiB MemoryMax and no swap. Psi4 tasks use four threads/4 GiB, with existing Archive
scratch directories before import. Batch one contains indices 0–104 (reference plus
52 complete displacement pairs). The separate completion watcher is armed. Each
task is independently audited and checkpointed; a failed task, a five-minute initial
task stall allowance, sustained >2x baseline slowdown or insufficient boundary time
stops the batch and preserves evidence. The allowed task timeout adapts to measured
cost but never exceeds ten minutes. No automatic numerical retries or blind chain.

On batch-one completion: acknowledge its token, inspect native outputs, run the frozen
`corrected_core_hessian.py review ... --batch batch-1`, and record the actual resource,
performance, necessity and alternative audit in `batch1_continuation_decision.json`,
pinning `batch-1/batch_review.json` with `proceed: true` only if warranted. Then launch
batch two using `prepare_corrected_core_hessian.py launch --batch batch-2`; no new user
permission is needed for normal progression. Batch two evaluates indices 105–210 and
assembles/audits the Hessian within its three-hour cap. All input bytes must match on
reconstruction. Every native gradient table is cross-checked against QCSchema.

Assembly requires all 211 task audits, a symmetric finite 108x108 Hessian and 102
internal modes after rigid-body projection. Imaginary modes fail minimum certification;
positive modes below 10 cm^-1 trigger numerical/mode review rather than automatic
certification. Independently review `assembly/harmonic_audit.json` before downstream
work. Keep all prior failures, gates and superseded-identity results accurately scoped.
Continue the authorized campaign as evidence supports; stop for intervention needs or
stalled progress. No cloud spending.

**All-stage continuation authorized — 2026-10-10.**
User instruction: `approved. continue through all stages as needed unless something
clearly requires intervention or shows stalled progress.` This supersedes the
stage-one-only and routine further-approval restrictions below. Continue corrected
cis-anti-I through the proposed refinement, validation and preliminary thermal-study
stages using finite task manifests and audits, without requesting permission at every
normal stage boundary. Stop for clear intervention needs or stalled progress.

`cpd-corrected-cis-anti-i-refinement-v1/campaign_authorization_20261010.json` records
the expanded authorization and pins the original design and 211-task Hessian proposal.
One native job at a time; normal 1–4-hour chunks and a global 15-hour service ceiling,
with saved checkpoints, native evidence, performance/necessity audits and preserved
failures. No cloud spending. Scientific evidence gates and honest review records remain
required; continuation permission is not minimum certification or registry approval.
The immediate allocation is the two three-hour Hessian batches, 105 then 106 tasks,
with an audit before the second batch. New execution records will supersede status
statements below; historical source files and approvals remain unchanged.

**Corrected cis-anti-I stage one passed; Hessian approval pending — 2026-10-10.**
Wake `ab61b089-2c2a-44d9-bd85-454dce0b2045` was acknowledged. Optimization completed
with native return 0 in 1736.84 service seconds (28.95 minutes), using 30 new
gradients plus the reused pilot gradient. The [completion handoff](audits/cpd_corrected_cis_anti_i_stage1_completion_20261010.json)
pins the full native audit and next-stage proposal. Runtime root remains
`.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1/`.

`stage1_completion_audit.json` independently verifies every energy and all 3348
gradient components against native tables, all 31 evaluated geometries, 31 accepted
checkpoints and 31 ASE trajectory frames. Final maximum/RMS atom gradients are
6.5408e-6/2.5706e-6 hartree/bohr, below the 1.5e-5/1e-5 limits. All four corrected
stereocenters and native electronic convergence pass. Final optimized XYZ, binary
geometry and restart checkpoint agree. Process peak RSS was 4.04 GiB. The initial
startup failure remains preserved. This is an unconstrained stationary candidate,
**not a certified minimum**; no Hessian or parameter/MD validation has run.

`stationary_candidate_review/review_packet.json` binds the new exact geometry and
atom map; the exported SDF agrees between RDKit and Open Babel on capped identity.
It is pending human review and has no registry effect. Exact binary/XYZ coordinates
remain authoritative over the rounded viewer SDF.

The planning-only `hessian-preview-v1/` contains 211 generated gradient inputs:
one reference and 105 +/- displacement pairs, three-point differences at 0.005 bohr.
The reference exactly matches the optimized binary geometry, every displaced
geometry retains identity, and pair midpoints match. No QM was executed. An initial
overstrict keyword-equality check was preserved: Psi4 only disables orbital writing
on displaced tasks; the subsequent audit verifies identical physical options.

`hessian_stage2_proposal.json` requests two sequential three-hour allocations,
105 then 106 tasks, keeping displacement pairs together. Measured mean gradient
time 57.78 seconds predicts 3.39 native hours total; the slowest observed gradient
with 50% headroom gives 5.33 hours within the six-hour reservation. Retain four
threads, 4 GiB Psi4/8 GiB service memory and Archive scratch, with checkpoints per
task and an audit before batch two. Include assembly/audit grace in batch two.
Resolve imaginary or ambiguous modes explicitly; do not clip them or infer a global
minimum. Only stage one was approved: **no Hessian job is queued**, and no fitting,
boundary QM, MD, registry promotion or cloud spending is authorized by this closeout.

**Corrected-core pilot passed; optimization active — 2026-10-10.**
The corrected `pilot-v2` completed normally with one MP2 gradient in 58.45 native
seconds. Reopening native output, exact coordinates and current definition passed
SCF/response convergence and all four stereocenter checks. Response residual
5.917e-11; maximum/RMS atom gradients 0.0938001/0.0408117 hartree/bohr: the static
seed is not stationary. Process peak RSS 3.84 GiB; observed service peak 4.50 GiB,
below its 8 GiB limit. Scratch was verified on Archive. Both pilot wake tokens
(initial startup failure and subsequent successful gradient) were acknowledged.

`pilot-v2/pilot_review_locked.json` and `pilot_continuation_decision.json` in the
stage-one runtime root preserve the independent audit and the resource, necessity,
alternative and performance decision. At the measured rate, 60 gradients project
to 58.4 native minutes, or about 88 minutes with 50% headroom; neither predicts
convergence. No extra thread benchmark or preoptimization was needed.

`cpd-corrected-anti1-optimization-v1.service` is active with verified 4-hour,
four-core-quota, 8 GiB and no-swap limits. The pilot gradient was reused at the
identical seed geometry; the initial accepted checkpoint and the first new native
QM evaluation are present. Every completed gradient is preserved; every accepted
geometry has a hash-pinned checkpoint. Restart from that geometry requires fresh
optimizer history, so no bitwise continuation is claimed. Hard limit: 60 new
gradients, one attempt, no automatic continuation or second seed.

On completion, inspect `optimization-service/status.json` and native outputs, then
run `optimization/corrected_core_stage1.py review` using the pinned Sella runtime
and `NADOC_REPO_ROOT=/home/jojo/Work/NADOC`. Audit all completed evaluations,
accepted checkpoints, final native and independent force convergence, and actual
performance. The separate completion watcher is armed. A user pause is recorded
in the stage-one root's `pause.json` and honored before the next gradient; preserve
any in-flight partial output if the service must be stopped. Do not launch a
Hessian, fit or MD: only stage one is approved. Minimum certification and registry
gates remain pending. No cloud spending.

**Corrected cis-anti-I stage one authorized and launched — 2026-10-10.**
User instruction: `Ok, proceed with the first stage.` This authorizes the proposed
single-gradient pilot (at most 1 hour) followed, only after its audit passes, by one
unconstrained core optimization (at most 4 hours and 60 new gradients). It does not
authorize the Hessian, reference-data/fitting or MD stages. The proposal below remains
an immutable review record; fresh per-job authorizations pin it and the executed code.

Runtime root: `.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1/`.
`pilot/` and `pilot-service/` preserve an import-time failure: `PSI_SCRATCH` initially
named a directory not yet created. No native QM evaluation started. The recorded
`pilot_startup_failure_audit.json` admits a corrected startup in `pilot-v2/`; Psi4
imports using an existing Archive directory, then uses an explicit job scratch path.
The failed wake was acknowledged. No native numerical retry or budget expansion.

`cpd-corrected-anti1-pilot-v2.service` is running, with native SCF iterations observed.
Verified service limits: 1 hour, CPU quota 4 cores, MemoryMax 8 GiB, no service swap.
Psi4 uses 4 threads/4 GiB. The separate completion watcher is armed for the current
thread. New source-pinned checks reconstruct full-graph CIP S/R/S/R, verify exact anti
crosslinks and reject reflected geometry, exchanged H6 atoms and broken bonds.
The analytic optimizer/unit preflight passed without QM; 19 targeted tests passed.

On pilot wake, inspect `pilot-v2-service/status.json`, native output and
`pilot-v2/independent_review.json`; re-run the frozen worker's `review` command.
Record the resource/performance/necessity decision in `pilot_continuation_decision.json`
before preparing or launching optimization. Preserve all failures. Do not infer a
minimum from optimizer success, transfer old anti approvals, or start later stages.
No cloud spending.

**Corrected cis-anti-I refinement proposed — 2026-10-10.**
The user requested refinement with an approval and compute schedule first. The
[source-pinned plan](audits/cpd_corrected_cis_anti_i_refinement_plan_20261010.json)
proposes a fresh corrected 36-atom core pilot: one MP2 gradient capped at 1 hour,
then one optimization capped at 4 hours/60 new gradients only if the pilot audit
passes. Initial reservation: at most 5 sequential native CPU hours, four threads,
4 GiB Psi4 memory and an 8 GiB service limit, subject to current memory headroom.
All scratch and native outputs go to Archive. No new QM/MD or service was launched;
the initial compute tranche awaits the requested plan approval.

Subsequent allocations require the measured pilot audit and a finite target manifest:
local harmonic-minimum certification, fresh atom-mapped identity and boundary-model
reviews, corrected QM references and fitting, prospective parameter checks, native
NAMD checks, then a matched finite DNA-context comparison. The plan explicitly flags
the differing dipole conventions in the generic workflow and old preliminary anti
policy for resolution before charge fitting. Old anti fits/trajectories remain scoped
to their superseded identity; undamaged controls are reusable only after a comparability
audit. Optimizer convergence does not certify a minimum, and neither this plan nor
compute approval passes a registry gate.

One native job at a time, normally 1–4 hours, with an audit before each continuation;
the global service ceiling is 15 hours, strictly below the user's 16-hour limit.
Later MD is proposed as 1 ns/2-hour jobs with 100 ps restart checkpoints. No blind
retry or service chain. A temperature campaign will receive its own concrete schedule
after refinement and context validation. No cloud spending.

**Geometric-opportunity priorities — 2026-10-10.**
The [priority audit](audits/cpd_isomer_priority_20261010.json) uses the three corrected
200-frame pilots, all competing TT pairs, 27 screening windows and distinct-pair/time-block
checks. Primary counts (intended/competing): cis-syn-I 2/5907, cis-syn-II 10/252,
trans-syn-I 1/13, trans-syn-II 17/10, cis-anti-I 514/87, cis-anti-II 1/35,
trans-anti-I 0/3, trans-anti-II 0/0. Counts are correlated pair-frame opportunities,
not independent reactions or a pooled equilibrium population.

For the campaign including competing products: corrected cis-anti-I first, cis-syn-II
second, trans-syn-II third. Cis-anti-I supplies 94.3% of primary intended opportunities
and 80.6–96.9% across the 24HB sensitivity grid. Cis-syn-II has broader, persistent
competing-product coverage and a capped-core reuse route. Trans-syn-II is the next trans
candidate; its intended opportunities exceed cis-syn-II at the primary cutoff, but vanish
at 3.6 Å. For intended welds alone, swap priorities two and three. Cis-anti-II is mostly
one late interstrand hotspot; confirm it before full refinement. Trans-syn-I and both
trans-anti variants are lower priority. Retain cis-syn-I as the existing preliminary
reference. This is a provisional research ranking, not a new simulation launch, minimum
certification or release. No new MD/QM or cloud spending.


**Anti detection repaired; prior anti identity superseded — 2026-10-10.**
The [correction audit](audits/cpd_anti_detection_correction_20261010.json) supersedes
the mapping diagnosis below. Syn-to-anti bond edits now preserve tetrahedral neighbor
parity, and absolute labels use RDKit's accurate recursive CIP implementation.
The initial C6-only counterfactual was insufficient: it restores coverage while
swapping anti cis/trans meanings. Correct registered identities instead change the
endpoint-1 C5 signed sentinel in all four anti definitions, with freshly constructed
coordinates and corrected C6 CIP labels. Ordered literature C5 labels are retained.

All eight planar precursor cases now pass unique identity **and methyl cis/trans**
checks. RDKit/Open Babel agree on static capped structures and six distinct products,
including trans-anti I/II symmetry collapse. These are identity checks, not minimum
certification. Corrected anti chemical-definition release gates are pending; old
human-review and QM minimum receipts remain explicitly attached to the old hashes.
No charges, parameter values, native simulation files, or historical receipts were changed.

Cached unwelded trajectories were reclassified with all competing T–T pairs retained.
At the exploratory primary window, the 2HB-2xT pilot has 7 cis-anti-I compatible
pair-frame samples; the 24HB-2xT pilot has 594 cis-anti-I, 36 cis-anti-II and 3 trans-anti-I
samples (508 anti samples at intended welds). Syn descriptors are unchanged. These
are correlated geometric opportunities, not reaction events or calibrated rates.
Outputs: `.development-artifacts/cpd-isomer-formation-corrected-v1/`.

Read-only inspection of all three archived anti final binary restart states confirms
that each fails corrected endpoint-1 C5 identity. The v17 package remains preserved
for the stored model; it must not be presented as corrected cis-anti-I validation.
Further anti production requires a separate parameter/geometry requalification decision.
Detection is usable now without new MD/QM. No cloud spending.


**Subsequent reactant-to-product mapping audit — 2026-10-10.**
The user requested isomer-resolved formation screening from unwelded trajectories,
including competing thymine pairs. A read-only prototype analyzed 200 frames each
from two 2HB jobs and one 24HB job, then failed an independent planar-precursor
mapping check: all four syn face combinations map, but none of the four anti face
combinations does. An isolated endpoint-1 C6 sign reversal in the anti definitions
makes all eight combinations map. A separate RDKit replay of the original
syn-to-anti bond edit shows odd neighbor-order permutations at C6/C5T/C6T while
chiral tags are retained. This is a chemical-identity/precursor-mapping discrepancy,
not evidence that anti products rarely form. See the
[source-pinned audit](audits/cpd_isomer_formation_feasibility_20261010.json) and
[analysis method](kimmdy_design_analysis.md#experimental-isomer-resolved-formation-screen-2026-10-10).

All pilot outputs and initial implementation failures are preserved. Each completed
pilot has a separate qualification review marking its eight-isomer ranking unusable;
the new default preflight stops further ranking. No native trajectory, prior receipt,
chemical definition, parameter file or registry gate was changed. No new MD/QM or
cloud spending occurred. Prior execution/restart/finite-context checks below remain
evidence for the stored model, not resolution of this newly found identity issue.
Before further anti production qualification or formation ranking, independently
reconstruct/audit all four centers and assess which existing anti assets are affected.

**Six-replica validation and research restart package complete — 2026-10-10.**
Control3 wake92598d9d-796f-4f2f-8e60-89e5e5579baa acknowledged; native
return0,10ns,32729.21service seconds (9.09h) within15h. Independentv9auditor
verified1000cells,100restart triples,30stratified chemistry frames,10binary
endpoints and1010worker records. Five earlier audits retained:all60ns complete.
All-six fixed28contact matched mean differences−0.305,+0.071,+0.019 show
replica/initial-state variability,not consistent causal lesion effect. No selective
extensions or refit. No more simulations automatically admitted.

`campaign_review_v17.json`,`replicate_comparison_v17.json` and append-only
`provenance_errata_v17.json` record physical/structural interpretation,actualv3
SLSQP method,timestamp and source-QM versusMM constraint crosswalk. Historical
failures,pauses,raw outputs and original metadata remain unchanged.
Portable `cpd-anti-restart-package-v17.tar.gz` includes allsix final restart states
and native validation receipts. Allsix relocated static NAMD checks passed;
zero additional MD. Standalone runner defaults static,allows at most1ns/2h per
explicit invocation,requires new output and input hashes,and never chains.
`campaign_closeout_v17.json` pins bundle/manifest/validation. Package review
field pending in earlier campaign_review is superseded only by this closeout.
See [final report](cpd_anti_validation_closeout_20261010.md). This completes the
authorized preliminary validation/packaging endpoint,not full production readiness,
equilibrium,minimum certification,isoform transfer or app/registry release.
No cloud spending; further simulation needs a specified scientific question.

**Anti3 aggregate10ns audited — 2026-10-09 MDT; control3 service active.**
Wakec8c45842-ea4d-4cc6-931a-6780273f2261 acknowledged. Continuation0.96ns
finished5530000 normally:3064.48native seconds,3314.38service seconds,within2h.
`audit_cube_anti3_v16.py` verifies prior pins plus996 completed-chunk DCD cells,
99 checkpoint triples,30 stratified chemistry frames,10 binary endpoints and
CPU/native restart/endpoint energies. Prior4partial frames and91 checkpoint
sets revalidated through their pinned audit. Combined1000 unique10ps frames,
100 distinct periodic checkpoint triples;1006 worker geometry records plus4
partial audit frames pass. Not independent all-frame chemistry replay. No tail
beyond paused checkpoint5050000 credited; all original raw evidence preserved.

Late5ns299.223K,+1.313bar,density1.022912g/cm3,149.838mM addedNaCl; density
halfchange-0.00002698g/cm3. Minimum worker image39.250A,max endpoint void3.456A.
Crossbond distances~1.55–1.58A. Measured9.96ns31745.50native seconds=27.11ns/day;
interrupted0.04ns has no terminal WallClock,so no exact full10ns runtime claim.

Fixed28contact anti3 blockretention0.740–0.814,prepared0.786,closer to anti2
0.744–0.813 thananti1 0.464–0.605. Keep all outcomes and prepared baselines;
first two pair orderings reverse. No causal lesion,equilibrium,convergence or
forcefield-quality inference. `replicate_comparison_v16.json` retains five
completed trajectories. Anti3 `validation/completion_review.json` pins aggregate
assessment,audit,performancev16 and comparison.

Control3 service `cpd-anti-cube-validation-control-3-v6` is active with verified
15h systemd cap and separate watcher armed for current thread. Wake token
92598d9d-796f-4f2f-8e60-89e5e5579baa; service directory
`cpd-anti-cube-validation-control-3-service-v6`. Worker rechecks inputs before
native dynamics; running supervisor alone does not establish native progress.

Five of six10ns validations audited. Control3 admitted with15h cap,1ns audits,
100ps restart triples and unchanged qualified method. Conservative13.93h budget
fits; no tuning detour justified. Stop on failure,insufficient boundary time or
>20percent slowdown. Prior anti2bad_any_cast remains unresolved; no retry loop.
After control3 completion independently audit with `audit_cube_replica_v9.py`
(casecontrol,replica3),review matchedpair3 and allsix structural/physical/
performance evidence,then complete provenance errata and portable restartable
package. No further simulation is automatically justified by completion.
Minimum certification,full readiness and equilibrium remain false. No cloud.

**Resumed — 2026-10-09; anti3 continuation service active.**
Latest user instruction `resume` supersedes the pause below. New v15continuation
will restore checkpoint5050000 for480000steps (0.96ns) to5530000, with fresh2h
cap,full coor/vel/XSC and declared RNG seed116037. No bitwise Langevin continuity
claim. Original interrupted output and pause receipts remain unchanged.
Two targeted tests passed: exact interval,checkpoint-energy rejection before
dynamics,and refusal to overwrite. Require CPU/native checkpoint potential
agreement before dynamics, then full aggregate review before control3.
Pre-resume audit passed:904 DCD cells/observables,91 checkpoint triples,
27 stratified completed-segment chemistry frames and4 partial frames,plus
checkpoint geometry. Minimum sampled image41.952A; completed worker gates pass.
Service `cpd-anti3-resume-v15` active with verified2h cap; separate watcher armed
for current thread,token c8c45842-ea4d-4cc6-931a-6780273f2261. Archive service
`cpd-anti3-resume-service-v15` retains worker,launcher,audit and execution plan.
Plan `anti3_resume_plan_v15.json`; output
`anti/replica-3/validation-resume-v15/segment-10-remainder`. Worker repeats final
input checks before native dynamics; running status alone is not MD progress.
On wake aggregate900 original completed frames,4 retained partial frames and96
continuation frames. Audit complete native/cell/restart evidence and structural/
physical/performance results before writing anti3 completion_review and admitting
control3. Preserve all failures; no cloud spending or readiness promotion.

**Historical pause — 2026-10-09; superseded by explicit resume above.**
Stopped anti3 completion watcher first,then worker cgroup; both inactive/dead,
no NAMD remains. This pause supersedes prior continuation/admission instructions;
delayed wakes do not authorize restart. Nine1ns segments passed worker checks;
full independent anti3 audit pending. Segment10 interrupted. Verified complete
checkpoint5050000 =9.04ns;480000steps (0.96ns) remain to5530000. Full coor/vel/
XSC finite,cell/DCD match and chemistry/water/image gates pass. Last log5073000
is uncheckpointed tail,retained but uncredited. Hashes and evidence recorded in
`campaign_pause_20261009.json` and service `user_pause_20261009.json`.
Historical supervisor running status is stale. Preserve old watcher and output;
new bounded continuation only after explicit resume and audit.
See [resume handoff](cpd_resume_handoff_20261009.md). Four complete audited
replicas retained; no cloud spending,commit or readiness promotion.

**Control2 aggregate10ns audited — 2026-10-09; anti3 service active.**
Wake2701d3c9-26d0-4c85-9a8b-ad2ae774e821 acknowledged. The0.86ns
continuation completed normally at5530000:2816.28native seconds,3066.45service
seconds,within2h cap. CPU checkpoint energy and native restart energy pass.
Original paused segment10 and its uncredited tail are preserved.

Auditor `audit_cube_control2_v14.py` revalidates pinned9.14ns evidence and
replays986 completed-chunk DCD cells,98 periodic triples,30 stratified chemistry
frames and10 binary endpoints. Combined1000 unique10ps frames and100 periodic
triples,without duplicate endpoints or discarded tail;996 completed worker
geometry records plus14 partial audit frames pass. Not an independent all-frame
chemistry replay. Late5ns statistics use200 contiguous50ps blocks across the
full10ns,avoiding truncated-block bias at the resume boundary. Late5ns299.209K,
+0.898bar,density1.022921g/cm3,149.839mM addedNaCl; density half-change
-0.00009336g/cm3. Minimum worker image37.018A,max endpoint void3.372A.
Measured9.86ns native31371.10s=27.16ns/day; interrupted0.14ns has no terminal
WallClock,so no exact complete10ns runtime claimed.

Matched28contact block retention:control2 0.686–0.726,anti2 0.744–0.813.
Prepared fractionscontrol2 0.571,anti2 0.821. Ordering reverses pair1; initial
state and replica variability prevent causal lesion or forcefield conclusions.
Control2 target cross-distances increase from~5.6A to~12A; retain this structural
change in final interpretation. No selective reruns,extensions or refitting.
`matched_pair2_comparison_v14.json` and originalpair1 evidence retained.

Anti3 service `cpd-anti-cube-validation-anti-3-v6` is active with verified15h
systemd cap and separate completion watcher armed for the current thread.
Wake token4e06a1c3-608f-4ada-b44a-49942b118ca2; service directory
`cpd-anti-cube-validation-anti-3-service-v6`. Worker repeats final input checks
before native dynamics; supervisor running alone is not native progress evidence.
Four restart-wrapper tests passed.

Control2 `validation/completion_review.json` pins aggregateassessment,audit and
performancev14. Four of six registered10ns runs now complete. Admit anti3 only,
then independently audit native outputs and structural/physical/performance
evidence before control3. Conservative13.93h estimate fits15h hardcap; retain
p4,2fs,fullXSC,PME144cube,1ns audits,100ps restart sets. Existing worker stops
on failure,insufficient boundary time or>20percent native slowdown. Earlier
anti2 bad_any_cast is unresolved; recurrence requires investigation,no retry loop.
After allsix,complete matched interpretation,provenance errata and restartable
package; full readiness,minimum and equilibrium claims remain false. No cloud.

**Resumed — 2026-10-09; control2 continuation service active.**
The user explicitly said `resume.` The October8 pause remains historical evidence.
Control2 continuation is admitted from checkpoint5100000, for430000steps (0.86ns),
under a new2h plan and fresh output directory. No old deadline or watcher revived.
New wrapper `resume_control2_v13.py` checks CPU and native initial energy against
the saved checkpoint row, preserves full coor/vel/XSC and declares seed105027;
no bitwise Langevin continuity claim. Tests cover exact continuation interval,
checkpoint-energy failure stopping before dynamics, and refusal to overwrite.
Pre-resume audit passed:914 DCD cells/observables,92 periodic restart triples,
27 stratified completed-segment chemistry frames and all14 partial frames;
all909 completed worker geometry records pass. Minimum sampled image41.9745A.
Original audit report retained with explicit correction of its textual checkpoint
count (91 to measured92); checkpoint records themselves were correct.
Four targeted tests passed. Service `cpd-control2-resume-v13.service` is active,
with verified systemd2h cap and external watcher armed for the current thread.
Service directory `cpd-control2-resume-service-v13` contains archived worker,
launcher,audit and execution plan. Wake token2701d3c9-26d0-4c85-9a8b-ad2ae774e821.
Worker performs final pinned-input admission before CPU checkpoint energy check
and native continuation; service running alone does not establish native progress.
Plan `control2_resume_plan_v13.json`; new output
`control/replica-2/validation-resume-v13/segment-10-remainder`. Historical pause,
old interrupted output,uncredited tail and earlier failures remain preserved.
After completion, independently aggregate original segments01–09,14 retained
segment10 frames, and86 continuation frames (1000 unique10ps frames total).
Review physical/structural/performance and matched28contacts with anti2 before
writing pinned aggregate assessment/audit/performance and control2 completion
review; only then admit anti3, followed by control3 with its own review.
No equilibrium,minimum or full NAMD readiness certification; no cloud spending.

**Historical pause — 2026-10-08; superseded by 2026-10-09 resume above.**
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
