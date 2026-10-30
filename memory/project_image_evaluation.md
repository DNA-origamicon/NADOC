# Image evaluation — 2026-10-27

Corrected Gerling files (2026-10-28):
`workspace/Gerling2018_FigS1_p7560_LOOP_OVERHANGS_WITH_EXTRA_T.nadoc` and
`workspace/Gerling2018_FigS1_p7560_LOOP_OVERHANGS_WITHOUT_EXTRA_T.nadoc`.
User requires the 66-base scaffold excess on its own ssDNA helix, not an
extension: helix **42 BP39–104**, with forced ligations **41 BP72 → 42 BP39**
and **42 BP104 → 41 BP71**. NADOC's bookkeeping nick is on helix42 BP71/72;
stored p7560 starts at original index7527 (circular rotation, paired register
unchanged). Helix42 is an editable straight carrier, not a relaxed loop shape.
User explicitly selected: outer tails become inline overhangs; internal single-T
caps remain terminal inserts. Full variant:84 outer overhangs (81×10T +3×1T),
342 internal single-T extensions,453 TT junction inserts, all213 published oligos.
T-removed variant removes exactly2061 annotated unpaired staple Ts, preserving
all7494 paired bases (including paired Ts) and all7560 scaffold bases.
Authoring script:`tools/gerling2018/build_variants.py`; evidence:
`.development-artifacts/gerling2018_corrected_variants_20261028/`.
Earlier original design is preserved. Its current saved version has177 junctions
classified as forced ligations; retain that classification. The oxDNA walk now
includes their inserts (previously silently omitted). See project_oxdna_extra_bases.
Both variants passed normal app load and caDNAno canvas checks; the full variant's
3D and schematic captures were visually inspected. Both expose66 unpaired scaffold
beads on helix42 and two loop ligations. Full variant has813 overhang beads;
T-removed variant has none. Both pass218 validator checks and canonical sequence/
reciprocal-backbone/save-reload checks. All14988 original paired nucleotide poses
are unchanged to floating-point precision. Focused exporter tests:54 passed,
6 skipped. Broader FAST:14873 passed,92 skipped,10 failed,4 errors; FULL deferred.
One FAST gate-self-test subprocess timeout latched rendering; documented explicit
infrastructure review after22 self-tests passed/1 skipped cleared only that incident
(no placement changes or gate bypass). Browser retry:2 passed. Original files preserved.

Latest Gerling42hb13 reconstruction (2026-10-28): **213/213 full published staples
exactly matched to all213 Fig.S1 gray paths**, with7494 paired scaffold bases and
66 unpaired excess bases =7560. NO missing staples. Supersedes ALL provisional
REVNANO maps below. Root issue: earlier design substituted the native scaffold
router and compressed uneven PDF columns to a7-base grid. Tracing the actual
blue scaffold with UNIFORM2.02PDFpoints/base solves the complete list directly.
Do not continue optimizing the obsolete5292-base native walk / globaloffset17.
Scaffold index0 is helix41 BP71 under the recovered coordinate convention.
New user design: `workspace/Gerling2018_FigS1_p7560_SEQUENCE_RECONSTRUCTED.nadoc`.
Scientific evidence: `.development-artifacts/gerling2018_trace_reconstruction_20261027/`
(Archive). Scripts: `tools/gerling2018/reconstruct_fig_s1.py`,
`render_reconstruction.py`. All old files preserved;42hb14 not reconstructed.
Full topology/sequence agreement is verified; no physical relaxation performed.

Help → Experimental → Image evaluation is a read-only PDF evidence viewer, independent of the
active part/assembly. Core: backend/core/image_evaluation.py; API:
POST /api/image-evaluation (raw PDF body); UI: frontend/src/ui/image_evaluation.js.

PDF vector recognition groups stroked paths by color and spatial region, detects
horizontal tracks and inter-row branches, and suppresses overlapping candidates.
It is heuristic, not a certified caDNAno recognizer. Raster-only figures are
reported unsupported. Limits: 25 MiB, 100 pages, 16 candidates, serialized parser.
Uploads/results stay in memory; no workspace designs or simulations are created.

Index labels explicitly remain hypotheses: first detected column defaults to 0,
plane step 7 (honeycomb) or 8 (square), with individual column overrides. Gerling
S1 requires first-column BP6 to align its first1–10 crossover to13. Missing planes
cannot be distinguished uniquely from drawing stretch. Row numbers are inferred,
not read helix identities. Endpoints are possible termini, not asserted nicks.
Single branches and skipped opportunities are observations, not automatic errors.

Gerling source PDF is retained under the Archive design_reconstruction/gerling2018
folder; it is not a repository fixture. Synthetic PDF tests cover reproducible
recognition. Optional E2E source selected with NADOC_IMAGE_EVALUATION_PDF.

Validation: 5 focused backend tests; 7 focused frontend/cleanup-policy tests;
2 feature browser tests including Gerling. Full frontend: 8464 passed, 1 skipped.
Backend FAST and general smoke expose failures outside this feature; compact
report: /media/jojo/Archive/NADOC_archive/development/image-evaluation/VERIFICATION.txt.
main.js change for this feature is five lines of lazy menu wiring.

## Experimental menu and Nanobase inventory — 2026-10-27

Image evaluation now lives under **Help → Experimental**, together with Generate design,
T-junction previews, Connectivity, CPD research panels, FJC, PEG testing and Create Seam.
Existing action IDs/handlers are preserved. General help/install/VR controls remain in Help.

The same submenu opens the read-only **Nanobase publication inventory**: all 109 public
records in the October 27 snapshot, inspected file schemas/manifests, publication links,
explicit supplementary-figure evidence, and unresolved statuses. New UI module:
`frontend/src/ui/nanobase_inventory.js`; snapshot: `frontend/src/data/nanobase_inventory.json`.
No entry is an approved training pair: upload/publication equivalence is untested.
MagicDNA/other 3D diagrams are distinguished from caDNAno routing figures. Offline audit
scripts and provenance rules: `tools/design_archive/README.md`. Filters and CSV/JSON exports
work without a loaded design. The inventory adds five thin wiring lines to main.js.

Inventory validation: 16 focused frontend checks, 2 provenance tests, and 3 browser
checks passed (including Gerling S1 under the new submenu). Full frontend: 8,475
passed / 1 skipped. General smoke: 22 passed / Close Session progress-overlay
failure logged as ISSUE-105. New Python modules lint clean; repository lint has
7 unused-import errors elsewhere. Final audit/cleanup summary: Archive
`runtime/development-artifacts/nanobase-inventory/verification.json`.

## 21-record benchmark and stage-two prototype — 2026-10-27

All 21 verified Nanobase figure records evaluated offline with original PDF hash/page
provenance. Baseline finds candidates in only 3 (132,18,270); 14 raster-routing records
are unsupported and rotation/scaling can cause severe grid false positives. Candidate
counts are not reconstruction success. No approved independent image/native pairs yet.

New `backend/core/image_reconstruction.py` and `tools/design_archive/reconstruct_image.py`
provide raw vector evidence, non-extrapolating piecewise calibration, an explicit reviewed
5′→3′ trace compiler, and site/crossover/terminus/indel reference differences. No guessed
polarity, automatic junction completion, live-workspace mutation, or frontend changes.
All 24 parseable reference variants have reciprocal source connectivity; moDON remains
unparsed. Full image-derived drafts remain unvalidated, especially raster evidence.

Archive `runtime/development-artifacts/nanobase-reconstruction-20261027/` contains the
per-record audit. Nine deposited configurations across eight records reproduce pinned
tacoxDNA geometry to numerical precision. Record35's labelled-unrelaxed configuration has
nonzero time/energies and is excluded. NADOC counts/strand-length multisets match all ten
export trials, and tested address-mapped directed links match; insertion-copy alignment
is excluded. Positions/orientations differ significantly: production export equivalence
is NOT established. No molecular constants, geometry or jobs were changed. Main.js Δ0.
Record35 also has a filename-labelled unrelaxed alternative with zero time/energies;
its description conflicts and geometry differs from tacoxDNA by2.926nm RMSD. Retained
as unresolved, not conflated with either the excluded simulated frame or verified starts.

## User clarification and direction deductions — 2026-10-27

User explicitly requires deducing missing mappings from images; deposited caDNAno is
CHECK ONLY, not a source of direction/identity. This supersedes the earlier unanswered
reference-assistance question. `image_direction_inference.py` implements canonical
track-offset hypotheses, isolated crossover-attachment corroboration, and constraint
propagation retaining global reversal for unanchored components. No geometry changes.

Separate CLI inference freezes hashes before `check_direction_deductions.py` reads native
files. Exploratory results: Square132 88/88, Tweezer18 48/48 (both variants), modular
triangle270 26/26 agree CONDITIONALLY on displayed track order matching stored order.
Not proof of helix identity or complete reconstruction. Square461 and triangle270649
attachment observations agree with opposite directions. Shared dumbbell page has9
conflicts; vertical rotation and raster tracing remain unresolved. No reference-based
repairs. Sources and report: Archive `nanobase-deductions-20261027/REPORT.txt`.
Scoped FAST8 passed/3 skipped; full suite deferred; task main.js delta0.

## First inspectable figure-derived import — 2026-10-27

User requested workspace folder `Nanobase Imports` and a full figure→caDNAno→NADOC
exercise. Created ModularTriangle270 Fig.S1 draft there via standard user import,
save and reload routes in a headless scratch session. Source figure has explicit
helix labels/cross-section; used instead of Square's weaker placement evidence.
29helices,1 scaffold8064nt,208 staples8603nt;16667nt total. Standard imported part,
not a fabricated native generative recipe. Actual geometry preview inspected offline.

`tools/design_archive/import_triangle_figure.py` is an explicit figure-specific
vector tracer, not a general recognizer. Reads only source PDF; tracks labels,
cross-section, line edges/caps, junction attachments, red deletion Xs, and insertion
symbols (their anchor is0.75cell widths in cadnano renderer). Published figure
traces709interhelix links; all agree with deposited reference after registration.
24 staple bases present only in reference on helices27/29 need endpoint review.
Do not repair the draft from reference. All496 strand-specific indel annotations match.

New `image_crossover_register.py` scores all32 square phases from image crossovers
and generic tables: best29=708same-index matches; runner-up28=361. No reference
input to inference, but exploratory code was developed after initial comparison;
do not advertise pristine held-out accuracy. Uniform origin gauge remains±32bp.
NADOC classifies708crossovers plus126forced ligations (including long same-helix
transitions). Shape is straight lattice geometry, not relaxed triangle. No sequences,
chemistry or simulations inferred. Archive audit `nanobase-imports-20261027/triangle`.
Scoped FAST5passed/3skipped; fullsuite deferred; task main.js delta0.

## Brick sequence agreement overlay — 2026-10-27

Image evaluator now has an optional **Highlight Brick sequence matches** toggle.
GET `/api/image-evaluation/brick-matches?minimum=12` reads a snapshot of the active
part; the PDF-only workflow still works without a design. Bundled reference is
`backend/data/gerling2018_brick.json` (211 exact Table S1 Brick entries; workbook
hash/source/DOI retained). Matcher: `backend/core/image_sequence_matches.py`.
Exact same-orientation maximal matches stay within individual duplex domains;
overhang/binder/reference strands excluded, missing/inconsistent sequences skipped,
loop/skips mapped to bp anchors. No sequence assignment or design writes.

UI module `image_sequence_overlay.js`: green whole-domain matches, purple partial
matches; adjustable6–40nt cutoff(default12); click for source index/offset/sequence.
Active-design snapshot stays fixed until Refresh. Equal row/helix counts initially
map by design order, explicitly an assumption, with editable per-row assignments.
Projection interpolates calibrated columns and clips outside their supported BP
range; invalid/nonincreasing calibration produces no markers. Export evidence
includes reference provenance, snapshot hash/revision, matches and row mapping.

User confirmed S24 is mislabelled. Do not treat it as reliable Brick routing.
Comparison evidence: `analysis/gerling2018_sequence_comparison_20261027/`.
S7/S24 vector coordinates agree under affine scaling (44,286 points, RMS2.6e-5pt).
Saved Gerling v4 returns36 domains with matches>=12nt, including9 whole domains;
these are local sequence agreement, not validated topology or scaffold register.

Overlay validation:9 focused backend tests,7 frontend tests,2 isolated browser
checks passed (synthetic interaction plus Gerling PDF with actual offline matcher
results). Gerling screenshot visually inspected;31/36 spans inside calibrated
columns at firstBP6. Backend lint clean. No main.js changes. Review artifacts:
Archive/development/brick-sequence-overlay/. Full suites not run for this change.

## Brick overlay active-document fix — 2026-10-27

User saw no matches in Gerling Page3. Root cause: optional sequence fetch used raw
fetch without `X-NADOC-Doc`, unlike normal per-tab APIs. It read the default
backend document instead of the open design. Added `docHeaders()` to the match
request. Earlier browser evidence used mocked matching responses and missed this
transport failure; do not cite those tests as end-to-end active-document proof.
Added a real-API regression that loads the external Gerling design into an
isolated document, verifies unscoped request404, then imports PDF/selectsPage3 and
checks the actual scoped response and visible highlights. Frontend unit test also
asserts the active-document header. No design or sequence changes.
Validation of the scoping fix:7 frontend unit checks and1 real-API browser check
passed. Actual Page3 overlay screenshot inspected:36/666 matching domains and31
spans within firstBP6 calibrated columns; toggle-off negative case has0 markers.
Archive/development/brick-sequence-overlay/scoped-review-real-api.png retained.

## p7560 local origin evidence — 2026-10-27

User requires retaining p7560 for the Fig.S1 design until rigorously ruled out.
Main article Table1 resolves the apparent conflict: brick-like TT1–3/1–4 usep7560;
polymerization Brick usesp8064. Brick-tab anchors must not rejectp7560 forFig.S1.
Current savedv4 already has5292/5292 paired-base complements correct (666domains),
scaffold sequencep7560[0:5292], noindels. Break5-prime h_XY_6_1 bp54,3-prime bp55.
Local all-offset search against42hb(1)-(3): first60 contains5full domains/58nt;
3541 and3650 matchall5. First98 has8full domains/92nt;ONLY offset3541 matchesall8.
This is a locally supported origin, not global route validation. Two pairs of
adjacent domain segments concatenate in published209/131, supporting nick review.
Break-spanning staple207/domain1 matches published35 asCGATCTAAAG only under
full7560 circular continuity, not stored5292 traversal (CGTAATTCGC atoffset3541).
2268 scaffold bases unrepresented; placement/paired status unresolved. Next
junction into h_XY_6_3 atindex98 already disagrees;local shifts12–15 ambiguous.
No design mutation. Reproducible audit, candidate-domain CSV and full rotated
reference at analysis/gerling2018_sequence_comparison_20261027/;
P7560_START_FINDINGS.txt distinguishes complementarity, local matches, and missing
continuity. Do not blindly assign rotated sequence globally to truncated design.

## Reference selection resolved / reconstruction proposal — 2026-10-27

User reconsidered Brick and requested a reference check plus reconstruction proposal.
Primary Fig.S1 target is42hb(1)-(3):213 paths/213 oligos,p7560 perTable1.
42hb(1)-(4) isFig.S5:176 paths/oligos,additional5T-loop motif. Brick211 is the
separate polymerization target; priorBrick-basedp8064 conclusions do not apply to
Fig.S1. Evaluator is still Brick-only; proposal recommends a reference selector,
not implemented during this analysis-only request.
Same >=12nt exact domain matcher, currentorigin0 -> hypothetical3541 unchangedroute:
(1)-(3)30->43 domains, whole>=12nt9->18; (1)-(4)23->23,3->4;
Brick36->29,9->9. Eight start anchors at3541 match8/8,5/8,4/8 respectively.
Rawmatchcount is not reference identity or held-out validation (3541 selected
using(1)-(3)). Proposed next experiment: constrain full circularp7560 ordered
published-domain chains using local3541 seed,solvebreakcontinuity+firstjunction
into h6_3 before globally extending. Keep indels,terminalTs andTT motifs explicit;
no blanketligation/stretching or guessed2268nt loop. No design mutation.
Report:analysis/gerling2018_sequence_comparison_20261027/RECONSTRUCTION_PROPOSAL.txt;
script:compare_reference_tabs.py;fullhash-pinned results:reference_tab_comparison.json.

## Whole-oligo reconstruction supersedes3541; evaluator previews — 2026-10-27

Whole-cap and ordered-path constraints support register17 relative to the current
break coordinates, not3541. This is LOCAL and conditional, not a validated global
origin. Two full published oligos (#178,#46) recovered; first2 domains of#142
support it. Proposed nick boundaries: helix41 31/32->37/38; helix40 28/29->30/31.
Scaffoldjunction alternatives on helix40: J21/B7220,J22/B539,J22/B7220. Cropped
hypotheses and reproducible evidence in analysis/gerling2018_reconstruction_attempt_20261027/.
Evaluator now selects42hb13(default),42hb14,Brick; current-sequence or detached
p7560offset17/0/3541 preview. Preview does NOT apply local topology changes.
Optional Fig.S1 markers expose nickpositions/junction alternatives, not recovered
BP calibration. Viewer helix labels use explicit label or zero-based helix order;
never display internal IDs. See feedback_helix_labels.md (user requirement).

Verification: six focused backend tests and eight frontend tests passed. Real
Gerling PDF Page3 + active scoped document browser check passed with offset17,
reference selection, four reconstruction markers, numeric helix tooltip and toggle
off. Detached offset17 preview reports34/666 matching domains atminimum12 on the
current savedv4; do not confuse this with the two whole-oligo cropped models.
Reference index now built once per comparison (~0.08s local preview vs~2.4s before).
main.js unchanged (LOC delta0). Broader test-smart:14856passed,10failures/4errors
outside image evaluator (CPD/proof/VR/provenance); broad lint7 existing unused imports
outside changed files. Focused lint passes. just smoke refused by activeoxDNA guard.
Screenshot: .development-artifacts/image-offset-preview/review-real-api.png.

## Circular contact-map comparison — 2026-10-27

User requested simple native-vs-published circle graphs. PNG/SVG and reproducible
script: analysis/gerling2018_circle_graphs_20261027/. Native savedv4 offset0 retained:
213staples,5292paired scaffoldbases,707contiguous-scaffold intervals (domains split
at scaffoldjumps),494interval links. Independent circularp7560 exact>=12nt matcher
retains per-base unique placements:208/213published oligos,241anchors,4147distinct
scaffoldbases,33same-oligo links.62overlapping assignments markedred;1219coveredbases
outside native0..5291. This is PARTIAL, not a globally solved sequence contactmap;
short/repeated domains omitted, dashedlinks can skip unknown domains. Circle
positions are p7560indices, NOT helixlabels or physical geometry. Native CSV uses
visible helixlabels; no helixidentities invented for sequence-onlyanchors.
REVNANO/contactmap primarydocs reviewed as precedent and next global-solver option.

## REVNANO trial — 2026-10-27

Upstream1.1 cloned with contactmap under .development-artifacts/revnano-gerling2018/;
commits pinned, no solver changes. Results/inputs/logs in
analysis/gerling2018_revnano_20261027/. Both unmarked complete42hb13(213) and42hb14(176)
lists on circularp7560 hit300s limit in Stage0; numerous10000-subtree limits, no
contactmap. This is NOT a disproof ofp7560 or correctly annotated input.
Official format REQUIRES *...* around nonhybridizing tails/loopouts. Four exact
cap controls#163,171,174,178:raw0/4(Error2),same sequences annotated4/4,76bp;
all outputsequences and positions independently verified. Six-control annotated
set adds#46,#142:5/6placed,103bp;#142omitted(no-route14mer and ambiguous7mer).
#46first10bp mapped5+5 to1355..1351/1386..1382, contradicting figure-constrained
8+2/9+1 localalternatives; last17bp50..34agree. Sparse controls lack whole-bundle
constraints, so neither success nor omission establishes full42hb topology.
REVNANO's bundled Brick example is1512nt/45staples, notGerling42hb. Next:explicit
unpairedT annotation with competing boundaries; do NOT mark/remove everyTT.

## Bounded-memory parallel REVNANO — 2026-10-27

User authorized source optimization for processors/memory. Implemented separate
local adapter tools/revnano_accel/{run.py,engine.py,stage0_hook.patch,README.txt};
pinned upstreamsource outsideapp. Stage0Pass1 sequential; Pass2 bounded4-worker
spawn batches on frozenfootprints, deterministic commit; laterstages sequential
with disk-backed mutableTreeStore cachingonetree. Sequence-scanLRU32MiB/process;
LinuxRLIMIT_AS controller1024MiB/workers512MiB,worker countclampedCPU/budget.
No timeout, no routingparameterchanges, resourcefailuresabort ratherthan omit.
Profile showed94% CPUtime repeatedget_run,~79MiB RSS, not demonstratedRAMbottleneck.
Raw4 unprofiled3.68s original vs0.388s cached. Exactoriginal/cached/parallel parity
forcap4,local6,upstream90,raw4(allstages/treedigests/contactmaphashes). Fourfocused
unit tests andruffpass; real16MiBworker failurefailclosed,99workersrequestbudget
2048clamped2withexactlocal6parity. Stage0hookonly7lines; appunchanged.
Complete rawlists (NO5mintimeout):42hb13 cached102.77s vsparallel50.13s,42hb14
148.93s vs59.44s. Exactcachedserial/parallelstageandtreeparity both. Parallel
sumperprocesspeakRSSupperbounds505/512MiB, not simultaneousmeasurements.
Both reachactualREVNANOError2:2/213 and0/176uniqueroutes afterStage1. Thusraw
unannotatedinputsremain scientificallyunsolved; needunpairedT annotations.
Benchmarks/logs/provenance:analysis/gerling2018_revnano_20261027/performance/;
full_results.json,parity.json,IMPLEMENTATION.txt. No liveprocesses left running.

2026-10-27: User requested estimated unpaired-T annotations for REVIEW BEFORE
any further REVNANO run. Drafts in analysis/gerling2018_T_annotations_20261027/:
review.html and Gerling2018_unpaired_T_review.xlsx (editable reviewer columns),
CSV/JSON and unexecuted draft .rev inputs. All 389 published oligos preserved.
Heuristic uses 7/14 spacing, 1T ends, TT crossovers, 10T cap controls; 42hb14 also
5T/merged7T loops per FigS5 caption. Alternatives and ambiguity shown. v2 agrees
with six prior local controls, which informed refinement (not independent test).
42hb13 101 clearer/106 ambiguous/6 weak; 7485 candidate paired bases.
42hb14 54 clearer/113 ambiguous/9 weak; 8119 candidate paired bases EXCEEDS p7560
by559 and is not globally feasible under non-overlapping occupancy. Do not treat
these annotations as validated routing. No solver run or design changes this turn.
Source preservation, only-T annotations, input order, workbook richtext roundtrip
and HTML rendering/filtering passed. See README.txt for methods and limitations.

2026-10-27 subsequent user approved T annotations and asked for REVNANO rerun.
Executed both full lists unchanged, p7560 circular, bounded parallel adapter4workers.
Outputs: analysis/gerling2018_revnano_annotated_20261027/ (logs, native contactmaps,
results.json, published-ID result CSVs, README). Both allstages exit0 in4.77/5.77s.
42hb13 final147/213 physical staples,5101/7560 bases;42hb14 final27/176,1171/7560.
Intermediate606/683 and567/852 virtual-fragment counts must not be called physical
staples. Recomposition discards whole oligos if any fragment is missing.
Audit: exact full published sequences, all mapped bases complementary, zero overlap,
unchanged annotated unpaired masks, full7560scaffold, reciprocal indices consistent.
Four19ntcapcontrols163/171/174/178 correct;46 omitted foroverlap,142notree+collapsed.
Partial sequence-consistent maps, not solved geometric reconstruction. 42hb14
559-base candidate pairing excess persists. Focus next on66missing13oligos and
local46/142conflicts. No annotation or NADOC design changes this run.

Circle graphs updated from final reviewed-annotation REVNANO contact maps:
analysis/gerling2018_circle_graphs_20261027/gerling2018_circle_graphs.png/.svg
now native vs42hb13 (147complete staples,466intervals,319links,5101bases).
gerling2018_revnano_both_lists.png/.svg compares13vs14 (14:27staples,128intervals,
101links,1171bases). Original anchor plots archived *_pre_revnano.*. Reproduce
with build_revnano_graphs.py; updated CSVs use published IDs. Gray=unmapped,
not proven unpaired. No geometry inferred or scaffold rotation. README updated;
old report.json/contact_maps.json still historical; new revnano_plot_report.json
records current sources and metrics. Verified native sourcehash and plotted totals.

2026-10-27 user requested TT-included vsTT-omitted scaffold comparison forambiguous
annotations. Completed analysis/gerling2018_TT_boundary_comparison_20261027/:
review.html,TT_comparison.xlsx (Priority review24windows),CSV,JSON,README,compare.py.
All219 ambiguous strands,915TTwindows fromproposal+3alternatives; overlappingTT
windows notindependent. Up to14ntflanks,>=4eachside spanning; circularp7560 exact
hits; unique>=12ntspanning favors included/omitted. One-sided>=12 possibleonly;
independentunique>=7flanks compatibleunpairednotdecisive. Original-proposalTTs:
13:177tested,10pairedfavored,2unpairedfavored;14:338tested,6pairedfavored,6unpaired.
16pairedfavoredwindows across14distinct list/staple pairs. Example13#53bases18-19:
TCGCCATTAAAAATACC unique17ntTT-includedmatch at6798, noqualifyingomittedbridge.
No geometry/occupancy enforcement; cannot inferunpaired fromlackofcontiguousmatch
atcrossover. No single-Tpaired hypothesis;5T/7Tcapsoutsidecomparison. Original
annotations/maps unchanged,noREVNANOrerun. Allreportedmatches checkedagainstS,
workbook915rows/24priority andHTMLfilters/renderpassed. ReadREADMEforlimitations.

2026-10-27 user authorized iterative annotation variations with preference for
7-base-multiple domains, seeking fully resolved REVNANO maps. Search in
analysis/gerling2018_revnano_variations_20261027/ completed250 recorded full-list
trials incl scientific failures/controls, plus serial validation. FULL RESOLUTION
NOT ACHIEVED. Selected inputs require candidatepairedtotal<=7560:
42hb13:176/213 complete physical staples,6071/7560 bases(80.3%); candidatepaired7459.
42hb14:87/176 staples,3775/7560 bases(49.9%); candidatepaired7558.
Compare approved baseline147/5101 and27/1171. Both useMU_MIN5,SIGMA4,BETA.2,
ordered-pruning fix enabled; selected route7bonus0 (tested1/3/7 didnothelp earlier).
7multiple preference remains in annotation ranking. Lastlocalrounds plateaued;
capacityrepair on latest14input yielded87withtotal7558 (preservesalloriginalbases).

Artifacts: README.txt,selected_best.json,final_report.json,best_annotations_review.xlsx,
*_best.rev,*_best_contactmap.csv/.json,*_best_staples.csv,*_fragment_diagnosis.csv,
*_uncovered_regions.csv,current_design_vs_best_42hb13.png/.svg,best_circle_graphs.*,
search_progress.png,trial_comparison.csv. NativeNADOCdesign/approvedannotations
unchanged. No physicalhelix geometry inferred; circlepositionsare0-basedp7560.
Stage3 virtual fragments cover6981/6420 bases; recomposition discards910/2645 bases
because wholeoligos withanymissingfragment are omitted. NOT complete-staple counts.
Caps163/171/174/178 retaincorrect19ntcores.46 and142stillunplaced (see diagnoses).

Methods: grid7prior/protection/longmatchweights;5T/7Tlooppriors14;solverguidedlocal
andunoccupied-scaffold variations; expanded exactdomain pools; restrictedbinary
jointassignment finds183/118 feasiblewholeoligos butthoseareNOT REVNANOresults.
Used thoseannotations as inputs again, not as substitute counts. Testedmu5/6,
sigma2/4/6,beta.2/.3/.5,soft7routebonus1/3/7,thenreappliedlocalalternatives and
capacity-constrainedbranch. Selectedfullmaps allcomplementary,zerooverlap,exact
publishedsequences+annotationmasks,reciprocalindicesvalid. All250 includedruns'
actualparameters checked. Cachedserial vsparallel stages,trees,contactmaphashes
EXACT forbothselectedinputs. Workbookcounts389 and.revsourcepreservationchecked.

Found actualUPSTREAMStage2 nontermination bug: two routes ofvirtualfragment825,
[(1556,6),(6452,4),(5955,4)] and[(1556,6),(5955,4),(6452,4)], bothsurviveupstream
membership-based shortest-route pruning. Observed>900repeatiterations;SIGINT
stoppedthatone run (notwalltimeout). Savedtree reproducesindependently ofadapter.
Opt-in tools/revnano_accel/ordered_pruning.py retainsorderedroutebytree-depth.
Previouslystuckcase finishes44.6s;defaultcontrolmapsremainbyteidentical. Six
regression/cache/memorytests+ruffpass. Upstreamcheckoutunchanged. toolsrun.py now
exposes--mu-min,--sigma,--beta,--ordered-pruning,--seven-route-bonus(default0),
savesadapter_source andfragmentdiagnostics,recordsCtrl-Cstatus130. READMEupdated.

Oneinitialcapacitybranch failedtoforward intendedoptions duebrittletextreplacement.
Native summaries exposedactual6/4/.3;12runsEXCLUDEDandmetadata corrected;see
capacity_branch/EXCLUDED.txt. Noresultimprovedbest. Replacedargumentassembly with
explicitparameterforwarding+assertions, reran capacity_branch_corrected withactual
2workers/512MiBparent/256MiBworkers/1024MiBbudget alongside main3072MiBceilings.
Separate capacity_repair minimizedsupported changes tofit7560. Logs/code/state
retained(~498MiBscientificartifacts). Alllaunchedruns finished; no liveREVNANO jobs.

## Reciprocal crossover constraints — 2026-10-27

User suggested eliminating missing routes using neighboring crossover partners.
Diagnostic in `analysis/gerling2018_graph_constraints_20261027/`; no source map,
NADOC design or approved annotation changed; no new REVNANO run. All jobs finished.
For a full reciprocal junction, staple jump x→y predicts (y+1)→(x-1), modulo7560.
This is conditional, with nicks, half-junctions, scaffold seams and wrong routes
as possible exceptions. Consecutive scaffold positions with loopouts excluded.
42hb13 current395 jumps include109 reciprocal pairs(218 jumps);94 unpaired jumps
predict two free endpoints,46 predict one occupied endpoint,37 predict both occupied.
Raw unplaced-oligo search finds47 predicted partners with>=5nt flanks (25 oligos),
43 with>=7nt flanks (22 oligos), each pointing to one unplaced oligo at that threshold.
Local connections do not equal complete-staple reconstruction.

Whole-route enumeration: previous annotation pools+identical placed Stage3 routes
yield502 routes for16 unplaced staples with current176 fixed. Requiring all strong
reciprocal predictions and expanding all internalTT masks,1/5/10Tends,min5 exact
contiguous blocks gives326 routes across11 staples (includes compatible old routes).
Five conditionally unique routes:22,61,98,147,209;206nt total,mutually nonoverlapping.
Would increase6071→6277(83.0%) IF accepted, but NOT promoted as confirmed recovery.
Not exhaustive for new scaffold-seam splits or very short domains.98's35 paired
bases supported by reciprocal connections to49,34,1.

Binary joint feasibility exposes conflict: cannot place all11;maximum10.
Minimal conflicting pair111/147 both require CATTACC at5236–5242(0-based) in this
fixed-map model. Alternate exact site4390–4396 blocked on4bases by placed92;
third site2779–2785 blocked by177/199. Does not prove92 alone wrong. Need reopen
weak existing routes and solve connected conflict groups, not freeze80% as truth.
Validation rechecks326 mappings,all raw local matches,occupancy,sequence andsource
hash. Artifacts README.txt,crossover_audit.csv,predicted_partner_matches.csv,
conditional_unique_staples.csv,graph_enumeration_summary.json,joint_check_summary.json,
conflict_example.png/.svg (visually inspected),validation.json. No new helix labels
inferred; retain visible-label-only preference when adding geometry.

## Unresolved staples versus wide schematic intervals — 2026-10-27

User asked whether unsolved staples map to suspected stretched BP ranges.
Diagnostic: `analysis/gerling2018_unsolved_schematic_20261027/`. Four wide PDF gaps
are between provisional anchors27/34,48/55,69/76,90/97; integer bands28–34,49–55,
70–76,91–97. Drawing gap ratios2.44–2.59, NOT proof of physical stretch or extra DNA.
Projected sequence evidence using UNVERIFIED existing5292-base route atoffset17:
unresolved fragments173/700 basesinside(24.7%);placed staples929/4170(22.3%);
native routed sites1176/5292(22.2%). Weak1.11ratio, not clear concentration.
Inside unresolved counts byband50,29,32,62;placed235,250,226,218. Descriptivecounts,
no independence/significance claim.35/37 unresolved oligos project some fragments,
25/35 touchbands;placed118/152projectableoligos touchbands. Only700/1388candidate
paired unresolved bases project:478have noStage3route,210mapped outside native
traversal. Missing domains could themselves occur inbands, so cannot rejecthypothesis.
Offset sensitivity10..24 givesratio0.941..1.111; not equally supportedoffsets/nulltest.

Better grounded localpathcrosscheck:mapped46/path203 on40/41 spans21–37afterlocal
nickcorrection andcrossesfirstband;142/path208 prefix identifies41→40→31→30,
span14–27outsidebands (remainingsequenceassignmentsunverified). Globalprojection
places142finalCTTTCTC on29bp30–36, whereasfigurepathends30bp21–27: concretewarning
that globalprojectionisnotvalidatedgeometry. No global sequence-to-figure assignment.
Charts provisional_projection.png/.svg and anchored_paths.png/.svg inspected;
README.txt,summary.json,perstaple/perbaseCSV,wideintervalcounts,offsetsensitivity,
reproducibleanalyze.py. Allfragmentscomplementary,zerooverlap,sourcehashunchanged.
No design,selectedmap,annotations orimage-evaluatorcode changed. Alljobsfinished.

## Connectivity-assisted gap filling — 2026-10-27

User proposed joining unresolved domains on lattice neighbors, e.g.1 and10.
Confirmed53 neighbor pairs; helix1 neighbors0,2,10. However only2/223 old
crossovers with both endpoints projected land on neighbors within1BP under the
unverified5292-base nativewalk+offset17. A soft prior using453 observed figure
crossover sites did not change the contactmap. Do not force global lattice
constraints on this projection or interpret absent crossover partners as errors.

Found upstreamStage2 omits graph connections across annotated loopouts, and
single-contiguous7mer routes tie because their scores ignore neighboring
fragments of the SAME oligo. Experimental private adapter restores those edges
and ranks candidates by graph distance to placed predecessor/successor fragments.
No sequence changes or new base matches; normal overlap competition retained.
Controlledfull-list results: nohook176/6071(exactoldparity);edgesonly173/5950;
contextonly183/6362;both185/6432;both+lattice185/6432(exactlyidentical map).
The185 result retains all176 and adds22,63,78,98,100,102,105,111,147, unchanged
annotations. Reroutes2,7,36,92,110,120,129,150,151; resolves111/147's old conflict
by allowing earlier placements such as92 to move. Graph-distance choices remain
heuristic, not proof of physical topology.

Local142 candidate adds35bases, giving186/6467(85.5%),396net more than baseline.
Figure path208 is41→40→31→30,7+7+14+7paired; restore original reviewed annotation
`*T*AGAGTCC*TT*AAGAATA*TT*CTTAAGTGTCCTAC*TT*CTTTCTC*T*` (candidatepairedtotal7457).
Routes0based:57/7,102/7,[799/12+6497/2],859/7. Last2bases are a scaffold-seam
piece within proposed14-base helix31 domain, not a2-base physical domain.
142 edge96→799 reciprocates167 edge800→95;142 edge6496→859 reciprocates104
edge860→6495. Seed exact12+2 candidate only for its Stage0 fragment with no valid
routes; Stage1–3 accepts it in full-list run. Annotation change alone leaves185.
This is an externally guided candidate, NOT an independent blind reconstruction
or proven unique assignment.7 and67 reroute vs185; all185 remain.46 still missing;
its optional seed candidates were SKIPPED because48 Stage0 routes already exist.
No conclusion that46's local routes have been exhaustively tested.

Selected: trials/142_seed under lattice_completion. New10 IDs22,63,78,98,100,102,
105,111,142,147; old10 rerouted2,7,36,67,92,110,120,129,150,151;none lost.
Remaining27wholeoligos,1093scaffoldbases. Stage3 fragmentcoverage7086 includes619
fromincompleteoligos; do NOT count these in final6467. All rawpublishedsequences,
annotationmasks,exactcomplements,nooverlap,reciprocalindices validated.19-base caps
163/171/174/178 pass. Cachedserial/4workerparallel maps,tree digests,stage results
exactly identical.4 connectivity/tree regression tests pass. MU5/SIGMA4/BETA.2,
orderedpruningtrue. Private runner under analysis; productionadapter/upstream,
sourceNADOC,oldselectedmaps,approvedannotation source,imageevaluator unchanged.

Artifacts: README.txt,summary.json,selected_best.json,trial_results.json,
seam_trial_results.json,staple_changes.csv,fragment_diagnosis.csv,projected_bases.csv,
baseline_lattice_audit.csv,42hb13_best_contactmap.json/.csv,42hb13_best.rev,
42hb13_best_annotations.json. Before/after provisional_projection_updated.png/.svg
shows newteal,changedpurple,remainingorange,oldblue;helix1/10 outlined. Circlegraphs
circle_graphs_updated.png/.svg uses whole staples only. Both visually inspected.
Globalprojection still disagrees with local142 geometry; do not overwrite the
globalmap with local helix labels without rebuilding the full scaffold walk.
All solver jobs finished. Next use local figure/reciprocal evidence on remaining
connected conflicts; retain separate evidence levels and preserve old snapshots.

## Complete Fig. S1 reconstruction — 2026-10-28

All213 full 42hb (1)-(3) oligos match all213 gray PDF paths exactly after tracing
actual blue scaffold and applying uniform2.02PDFpoints/base. Script derives paths
directly from PDF, verifies against both backend JSON and original workbook.
42helices:24×178paired+18×179paired=7494;83 scaffold domains;666 staple domains;
453 stapleTT bridges. Total rawstaple9555 =7494paired+2061unpairedT (906junction,
345ordinary1T+81terminal10T=1155). Scaffold0 athelix41BP71, traverses toBP-5;
helix40 startsindex77 atBP-5, endsindex104 atBP22. Excessindices7494–7559=66bases
matches drawn below-schematic tail. New NADOC preserves it as3-prime extension
athelix41BP72; standardlinearizedscaffold convention, not evidenceofphysicalnick.
Oldperiodicwide bands28–34,49–55,70–76,91–97 become28–44,59–76,91–107,122–139:
17/18/17/18 bases. Do NOT treattheoldBPaxisoroffset17projectionascurrentgeometry.
46 selects oldJ22/B7220 alternative.142's previous35-base candidate is confirmed.

Compared186 provisionaloligos:27newlyresolved,44corrected,142unchanged;
46annotationschanged. Prior exactcomplement/nooverlap didnotproveproperrepeat
placement. BlindREVNANO with nowexactannotations still gives198/213,6937bases:
181correctwhole routes,17incorrectrepeatroutes,15unresolved. Complete213 map is
fromPDFconstrained reconstruction, not independentblindREVNANO success.

New .nadoc builtwithnativeDomains,Crossovers(TT),StrandExtensions(1/10T),explicit
helixlabels0–41 andpublishedstaplenames.535crossovers,427extensions,214strands,
17115nucleotides. All218 nativevalidatorchecks pass; canonical oxDNA nucleotide
walk reproducesall213 fulloligos ANDexactp7560 includingtail;save/reloadidentical.
No lockedgeometryconstantschanged, noCPD, noMD/relaxation. Originaldesign and
previousmaps untouched. Workspace copy sha256 recordedin scientificsummary.

Artifacts under .development-artifacts/gerling2018_trace_reconstruction_20261027:
review.html (linked interactive schematic/circle),reconstructed_schematic.png/.svg,
complete_circle_graphs.png/.svg,published_staples.csv/.xlsx,matched_staples.json,
figure_trace.json,scaffold_coordinates.csv,contactmap.json/.csv,input.rev,
annotations.json,summary.json,nadoc_validation.json,revnano_comparison.json,
README.txt. Scientificplotsvisuallyreviewed. NADOC schematicloadsandall42labels
visible; optionalbrowserreviewtestin frontend/e2e/gerling_reconstruction_review.spec.js
usesprivateArchiveworkspace andcleanup. Check app_verification.json forfinaltest.
42hb14unchanged. Fullsequenceexport caveat: standardNADOC Strand.sequence stores
onlydomainbases; full213 orderingsequences includingTT andtailsareinprovidedCSV/XLSX.
Final browser verification PASSED:1test(18.7s),42helices,214strands,all0–41labels;
nativegeometryloaded;NADOCschematicvisuallyinspected;HTMLdropdown+actualstroke
click selects matchingstaple inbothmaps. App_verification.json recordsdetails.
InitialreviewHTMLnewlineescapingandSVGzero-heightlocatorissuesfixedandrerun;
no productionbehaviorchanges. Disposablebrowserprofile/cache/testworkspace and
capturesremoved afterallprocessesfinished;cleanup.json recordscounts/bytes.
