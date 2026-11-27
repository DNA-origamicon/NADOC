# Image evaluation — 2026-10-27

## Exact controlled Pointer image routing — 2026-11-25

`diagram_route_extraction.py` now recovers an undirected graph from visible
ruler/row labels and vector primitives, joins fragmented strokes, reads deletion
crosses and the numbered square-lattice inset, then resolves each staple's
orientation independently using sequence agreement. No reference input is
accepted by the extractor. Detect designs calls this graph detector independently
of the old whole-path detector, which missed fragmented strokes.

Controlled reference-image extraction matches all 15,240 source sites and every
predecessor/successor pointer, all 161 staples, the deletion, and 82 normalized
lattice positions. The oracle is separate from extraction. Tests vary scale,
row spacing, stroke order/orientation and fragmentation. Incorrect sequences,
missing rulers and missing deletion marks do not produce a directed solution.
This is **not** a successful extraction of the original published Pointer image.
The available Gerling S7 is a modified variant with 159 continuous gray paths;
its outlined labels are not supported. Raster/OCR and full molecular construction
remain future work. Unknown partner bases (740) are explicitly retained as unknown.

See `docs/pointer_image_extraction.md` for the contract and reproduction command.
The benchmark writes only diagram/review evidence, not authored molecular files.
`tools/design_archive/pointer_image_benchmark.py` isolates the extractor worker
from the reference-bearing renderer/validator. Eight extraction/integration tests,
seven existing detection tests, fourteen frontend tests and three browser flows
passed, including blind Pointer extraction through the actual API. Temporary
preview images and browser artifacts were cleaned. Main.js task LOC delta: zero.

## Agent-less figure/list hypotheses — 2026-11-25

**Detect designs** now analyzes uploaded PDFs alongside XLS/XLSX/CSV/JSON/text
staple lists; workbook sheets stay separate and raw sequence case is retained.
PDF page sequence tables are also extracted. Vector candidates and captioned
raster pages appear as independently selectable design candidates. Nearby
caption/list labels nominate pairings; sequence support outranks context-only
associations, and unrelated lists remain unassigned. Users select design(s) and
inspect likely lists and competing direction/register/calibration hypotheses.

`article_design_detection.py` retains source hashes, PDF path IDs, drawing
coordinates and calibration assumptions. It rejects fragmented/cropped paths
for complete-route inference. Whole-scaffold-length and 7/8-base-interval scales
are tested against the chosen scaffold (default M13mp18, explicitly a hypothesis).
`article_sequence_inference.py` tests both scaffold and staple senses, nominates
registers using up to 12 paths, then checks all paths/list rows. Uppercase cores
and raw oligos are explicit alternative interpretations. Ties remain unresolved;
unknown scaffold partners are not invented. Evidence scores measure agreement,
not calibrated molecular reconstruction probability. These are transient drawing
and sequence hypotheses, not authored NADOC structures; Reconstruct stays disabled.

Pointer reference validation recovers all 161 2017 published staple cores at
M13mp18 offset 0, including 7,249 verified paired bases and 740 unknown-partner
bases. Reversing the observed staple order recovers the opposite direction.
The original XLS was read directly: 161 oligos on `pointer staples`, with two
other sequence-containing sheets kept separate. Added `xlrd` for legacy XLS.
No published Pointer diagram PDF was available locally: this is a reference-route
sequence oracle, not evidence of reconstruction from the original Pointer image.
Independent synthetic vector PDF tests recover 12/12 staples and retain six
symmetric alternatives. Multi-design PDFs test separate caption/list pairings.

Earlier heuristic method limits: vector-only route inference, continuous paths, uniform scale,
known scaffold sequence, no recovered lattice positions or insertion/deletion
annotations. Raster candidates are detected but not traced. Fragmented/wrapped
sequence rows and multi-page list merging need additional extraction. Partial
path evidence remains visible when complete calibration cannot be recovered.

Validation: seven new backend tests, thirteen frontend tests and four serial
browser flows passed; the two detection flows use the real analysis API. Browser
artifacts and test-server credentials were cleaned. Task main.js LOC delta: zero.

## Reconstruct from Article screening — 2026-11-25

The Help → Experimental entry now opens **Reconstruct from Article** with DOI,
paper PDF and up to two supplement PDF inputs and an explicit Check action.
`article_reconstruction.js` consumes incremental NDJSON checks from
`POST /api/article-reconstruction/check`. Input edits/cancel/close invalidate
pending results. The original diagram/calibration/sequence evidence viewer
remains accessible through **Inspect diagram evidence**.

Current scope is basic, agent-less screening. DOI lookup checks Crossref and
Europe PMC metadata plus available open-access full text/captions, with upload fallback. A supplemental caDNAno diagram/schematic label
or description suffices to proceed to image analysis; neither caDNAno files nor
verified staple sequences are prerequisites. Staple-list mentions are reported
separately. Missing accessible evidence is not proof the paper lacks it.

Image detail analysis is deferred to **Detect designs**; complete reconstruction
feasibility/confidence remains a later stage, not a failed basic check. No reconstruction confidence is fabricated (the
screening result reports null). Reconstruct is disabled for this session's
scope. Future reconstruction is intended to derive all required information
from article evidence without agents or caDNAno files. The agent-orchestrated
construction policy must not be presented as a product screening blocker.
Separate publisher supplement downloads, raster analysis and spreadsheet
extraction remain future work. Users can supply supplement PDFs now.

PDF uploads have no application byte-size limit, individually or combined, in
both article screening and the diagram evidence viewer. The 100-page limit
and two-supplement count limit remain. Remote article text likewise has no
byte-size cap. Large files are still buffered in memory during processing.

Validation: ten backend screening/API tests and ten frontend dialog/evidence
tests passed. External Europe PMC request timed out in this environment;
service contracts/fallbacks are covered with controlled responses. Two browser
flows passed, including DOI readiness with controlled screening responses;
cleanup verified. Task-specific main.js LOC delta: zero.

## Gerling flanking-frame and sequence audit — 2026-11-06

Audited all 453 TT joins (276 standard, 177 forced) in the existing failed-job
design. All use upstream as half A: half ordering is not this design's remaining
forced/standard difference. Effective geometry (not stored, rederived phase fields)
puts forced source radial azimuths 17.1429 degrees behind corresponding standard
motifs. Both paths share placement; eight new sequenced parity cases confirm
atom identity for matched endpoints across A/C/G/T pairs and both directions.

All 67 forced-insert hits are REVERSE exits: a normal ~0.156 nm P–O5′ bond of the
next paired nucleotide beyond the destination crosses TT[1]'s sugar. Exact next-
base association: A 34/34, C 16/16, G 17/17 pierced; T 0/22. All 88 FORWARD forced
joins are clear. Standard insert hits (26) involve extensions; the other 144 hits
also involve extensions. Current full count stays 237; eliminating only this class
would leave 170 extension-associated hits. No job resubmission/override.

After a proper 24-sugar-atom fit of the two flanking base pairs to same-direction
standard motifs, flank RMSD is 0.163–0.182 nm; insert RMSD is 0.147–0.165 nm (F)
or 0.459–0.487 nm (R), max atom deviation 0.701 nm. The R forced middle C3′–C5′
anchor span is only 0.07465 nm; current TT linear closure divides it into 0.01866 nm
intra-link bonds. Standard TT middle links are ~0.0353 nm. Rigid TT moves cannot
repair that compression; upper-length checks and same-insert clash exclusions
do not establish chemically sound linker geometry.

36 isolated editor-recorded displacement/rotation trials on a new 2HB with the
Gerling local sequence: -10 degrees around ring-local y, pivot at TT[1] O3′, clears
G/C piercing with no external clashes; max movement 0.10755 nm, longest insert
bond unchanged 0.28255 nm. A case clears piercing but clashes increase 1→2.
21 registers × four next-base choices (84 cases): total hits 194→194, seven cases
gain piercings, 23 gain external clashes. Candidate NOT promoted; no production
geometry changed. Candidate construction uses real Extrude/Nick/Force Ligation/
Extra Bases/Sequence/Move commands and passes independent replay after JSON round
trip. Original full Gerling legacy input fails agent publication proof (missing
empty construction root); read-only diagnosis only, no derivative part published.

Evidence under `.development-artifacts/gerling_seed_topology_20261105/`:
`junction_audit.html`, `junction_summary.csv`, `junction_frame_audit.json` (every
insert atom in both flanking sugar frames and every bridge), `junction_review.png`
(visually checked G-positive/A-negative controls), `junction_review_process.json`,
`local_adjustment_trials.json`, `phase_sequence_sweep.json`. Reproduction scripts
are adjacent. Focused placement tests: 17 passed, including eight new sequenced
parity cases. No frontend behavior changed in this follow-up.

## Paired forced-ligation schematic bows — 2026-11-06

Unique adjacent reciprocal strand transitions now classify the lower BP left and
the higher BP right in native caDNAno forced-ligation drawing and hit targets.
Pairing requires matching directed tracks and matching adjacent BP order on both
helices; ambiguous, unpaired, and periodic seam transitions retain prior behavior.
Gerling has 75 pairs (75 left / 75 right) and 27 unpaired forced TT joins.

This fixes a schematic defect, not molecular placement: all 75 pairs already have
opposed atomistic bow vectors (cosine about -0.669415, angle about 132 degrees).
Read-only fast-build recheck gives 237 piercings before and after, identical atom
coordinate hashes, and 391364 bonds. Do not infer a molecular bow flip from the
schematic left/right rule. No saved design or job was modified.

Validation: full frontend suite 10127 passed, 1 skipped; native pathview exercised
in a private browser page with existing Gerling JSON, API calls blocked, actual
leftward curve observed, no browser errors, and screenshot visually inspected.
Temporary screenshot removed after inspection. Evidence is under
`.development-artifacts/gerling_seed_topology_20261105/`: `paired_bow_browser.json`,
`paired_bow_audit_20261106.json`, `paired_bow_piercing_recheck.json`, and
`paired_bow_frontend.log`.

## Gerling extra-T atomistic bond audit — 2026-11-05

**Placement parity follow-up (same day):** user requested that forced ligations
follow standard crossover placement. Forced insert junctions now skip preliminary
direct closure, receive the shared post-closure 45° clockwise downstream gamma
rotation, and enable v7 clearance even without standard TT crossover records.
Directed forced endpoints must occur in the actual consecutive-domain walk before
receiving the gamma step. Existing native/trajectory override guards are retained.
No pose tables, phase constants, or saved designs changed. The earlier
coordinate-hash invariance below applies to the bond-only fix, not this follow-up.

Gerling now has 237 uncapped ring intersections in both build modes (294 after the
bond-only fix). Forced insert-related hits: 67 across 67/177 junctions, all sugar;
standard insert-related hits: 26 across 15/276 junctions, all pyrimidine. All 453
insert destinations receive gamma, including all 177 forced destinations. The
structure still fails seed preparation; no resubmission or override was performed.
Evidence: `after_placement_parity.json` in the audit directory below.

Exact geometric equivalence has an endpoint-frame condition: forced records encode
upstream/downstream, and their existing adapter uses upstream as half A. Matched
standard records with that ordering agree atom-for-atom for 1xT/2xT in both
directions and exact/fast modes: a 21-base-repeat scan checked all 48 editor-valid
cases (BP6,7,11,12,22,23; 2 sequences × 2 directions × 2 build modes), with zero
coordinate delta. The other 120 combinations were rejected as invalid standard
crossover sites and are not claimed as parity evidence (`phase_sweep.json`).
The standard placer itself is NOT invariant to
reversing half A/B: a TT audit with downstream as half A differed by 2.462259 nm
(FORWARD source) or 1.708447 nm (REVERSE source), across 45 atoms. Changing that
convention would also change existing standard crossover geometry; this follow-up
does not choose a new bow/frame or claim universal equivalence for arbitrary
forced spans. See `half_order_audit.json` and `test_forced_ligation_placement.py`.
Follow-up validation: nine new placement tests and six standard v7 tests passed;
FAST 20565 passed / 90 skipped / the same unrelated CPD comparison-schema failure.
Aggregate timing guard failed at 194 s/90 s, zero individual violators. Broad FULL
debt remains deferred. Scoped Ruff/diff checks passed; the inspected placement
plot was removed. No molecular golden or test guard was changed.

Alpine preparation of WITH_EXTRA_T (job `0695583ec45b`) failed locally at
the ring gate; no Slurm submission occurred. The uncapped old model had 382
ring intersections, not the error message's reporting limit of 200. All 177
TT-bearing forced ligations incorrectly retained a direct O3′–P bond alongside
the insert path (5.51–9.87 Å, O3′ degree 3 / P degree 5). Atomistic bond building
now excludes the exact directed forced-ligation endpoint pair when inserts are
present; zero-insert ligations retain their direct bond. Placement sets are
deliberately unchanged: connectivity repair is not molecular-placement approval.

The saved job rebuild loses exactly 177 bonds (391541 → 391364), with identical
coordinate hashes in both exact and fast builds. Uncapped intersections fall
382 → 294. Among TT insert-related hits, standard crossovers have 26 hits across
15/276 junctions; forced ligations have 110 across 110/177 junctions. Other hits
involve ordinary residues/extensions. The no-extra-T workspace variant had zero
ring hits in the initial audit; this does not certify other bond/geometry checks.

Placement comparison: both kinds share measured endpoint projection, proportional
2xT linker closure and promoted v6 directional residue poses. The post-closure
45° clockwise downstream gamma branch rotation is applied to 276 standard
endpoints and zero forced endpoints. Forced ligations also miss the suppression
of preliminary direct crossover closure. The v7 phosphate-clearance entry condition
checks standard TT crossovers only: it runs on this mixed Gerling design (140
atoms moved in exact mode, zero in fast mode), but would skip a forced-only design.
These were the geometry differences at the bond-only stage; the explicit parity
follow-up above supersedes that implementation state. No saved design/job was
changed or resubmitted.
Read-only evidence: `.development-artifacts/gerling_seed_topology_20261105/`
(`bond_audit.json`, `compare_paths.py`, `after_fix_comparison.json`).
Validation: forced-ligation suite 34 passed (18 new insert-path/valence cases),
standard 2xT defaults/auditor suite 6 passed, scoped Ruff clean. FAST: 20556 passed,
90 skipped, 1 unrelated CPD comparison-schema failure; aggregate runtime guard
also failed at 190 s/90 s, with zero per-test violators. FULL remains deferred.
Slow-test triage found no task-specific timing offender; no test guards or
classifications changed. Existing-model bond close-ups were visually inspected;
the temporary plot was removed, and no shared app state was mutated.

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

## Original-publication extension (2026-11-25)

`publication_diagram_labels.py` decodes corrupted PDF numeral maps by rendered
shape matching. `publication_routing.py` handles quarter-turn figures, legacy
base-cell paths, endpoint-table pairing/register shifts, antiparallel scaffold
orientation, honeycomb insets and constrained insertion lengths. Wired into
`article_design_detection.py` and the design selection UI; returns evidence only.

Five real designs audited using `tools/design_archive/publication_routing_benchmark.py`.
Right-twisted 10×6 bundle: all 15,119 occupied pointer entries, 60 lattice cells,
and 361 insertion sites/lengths match the separate native oracle. Straight 3×6:
all 15,362 routing entries match, but the inset omits auxiliary helix locations.
Monolith/square nut/railed bridge have exact recovered routing but missing native
staple sites. Do not describe those as complete recovery. Details and reproducible
commands: `docs/publication_routing_extraction.md`. Native authoring, general
deletion handling and full sequence reconciliation remain unfinished; Reconstruct
is disabled. No molecular artifacts were created.

D005 sequence reconciliation implemented in `publication_sequence_search.py`:
exhaustive 2×8064 register/direction candidates, insertion-expanded partners,
all 217 staples exact (7,919 paired bases), unique offset 0 in recovered direction;
runner-up 5,551 mismatches. Wired into publication analysis and evidence UI.
Explicit user sequence overrides the scaffold named in the publication. Missing
library sequences, unresolved insertion lengths, ties and unknown partners remain
explicit. Search never moves a physical nick or edits topology. User generally
authorizes bounded scaffold-shift/nick-position searches; see
`feedback_bounded_sequence_search.md`. Native construction remains unfinished.

Cross-design alignment extension: D006 now uses a pinned upstream p7704 sequence
(`backend/core/p7704.txt`, provenance JSON alongside). D006 matches 209 staples /
7,658 paired bases; D007 144 / 5,880; D008 148 / 4,977. All unique zero-mismatch,
offset 0. D007/D008 use explicit length-matched library hypotheses since their
tables do not name a scaffold. D009 refuses alignment while two insertion lengths
remain unresolved. `publication_sequence_benchmark.py` audits all five from PDFs
alone. Added rejection/coverage checks and tests for duplicate evidence, mutations,
ambiguous library matches, batch boundaries and virtual-nick changes. Sequence
alignment is not whole-design reconstruction; native construction stays pending.

D009 update: user-authorized +/-1 length candidates and deliberate scaffold-loop
search implemented in `publication_loop_search.py`. From PDF/table evidence alone,
39/39 inserted bases plus a one-base gap at the observed nick boundary give zero
mismatches at 6,686 comparable bases. Equal-length 40/39 has 408 mismatches.
Confidence is a transparent heuristic: 80.96/100 after a 10-point discrepancy
penalty plus missing-row/unknown-partner penalties. Gap location/cause remain
unverified; no topology is edited. Sequence-supported loops are returned in
reconstruction evidence alongside the original unresolved annotations. D009 full
validation remains false (10 table rows unmatched, 276 unknown partner bases).
This supersedes the previous blanket D009 alignment blocker. Native construction
and geometry remain unfinished.

Native publication follow-up (2026-11-25): D005 is now built from the PDF through
2,681 ordinary recorded actions, published by the guard and independently replayed
from the saved file. A separate post-publication native reference comparison is
exact for all scaffold/staple pointers, relative lattice cells and insertion
counts. The original supplement and pinned extraction implementations travel in
Shared Designs/.provenance/D005. D006–D009 remain unsupported for complete native
publication; the compiler rejects missing lattice, unresolved routing/sequence
and unexplained unpaired scaffold runs. Do not imply README analysis rows appear
in the welcome library. Native loop-count/history editing now admits 1–512 bases;
process/document/history traversal remains bounded at 4,000 rows. The interactive
Reconstruct button remains disabled; publication currently uses the CLI workflow.

D006 loop follow-up (2026-11-25): user identifies sideways diagram and path-only
bundle 19, authorizing inference of deliberate unpaired scaffold loops from
negative staple complement evidence. Partial lattice recovery retains all 18
inset cells and explicitly lists missing track 19. `publication_unpaired_scaffold`
reports 26/3/3/14 unpaired runs and two anchored excursions containing 49 paired
bases each. Short repeats in fully assigned staples are reported separately from
unassigned-staple matches; minimum contiguous match is explicit (default 7, whole
run when shorter). All four quarter-turn orientations are tested. Evidence is
wired into publication analysis; no 3D position inferred, no D006 native output.
Native publication reports AGENT_PROCESS_REQUIRED for missing auxiliary placement
or native loop representation, rather than treating negative sequence evidence
as a recovered physical pose. The user has been asked how to represent the
path-only auxiliary track; do not invent a slice cell to unblock publication.

Auxiliary placement clarification (2026-11-25): user authorizes inferring a vacant
cell from odd/even polarity and nearest scaffold attachments; no published pose
is required merely to run that search. `publication_auxiliary_placement.py`
checks label parity against directed routing, enumerates an analytically bounded
HC search, excludes occupied cells and preserves numerical ties. D006 has two
exactly equivalent closest reverse-direction cells (2.25 nm to bundle 0 and
sqrt(15.1875) nm to bundle 1). Neither is promoted. Public publication evidence
returns both candidates; compiler reports ambiguous lattice placement. This
supersedes the previous question about requiring a published pose. No new native
structure or physical pose has been authored. Local reproducible evidence and
lattice schematic: `.development-artifacts/d006-auxiliary-placement/`.

D006 two-loop/ligation correction (2026-11-25): user confirms separate excursions
from helices 0 and 1 and requests minimizing forced-ligation lengths. The two
source-track-19 segments have independent 49-base staples, no cross-segment
staple, and 29/17 unpaired bases. `publication_ligation_placement.py` uses the
canonical native Full O5 projection and fixed source register; minimizes SUM of
3D join spans per independent segment with an exhaustive analytic search bound.
Both minima unique; combined span61.119926nm vs best shared-cell61.197591nm.
The second optimum was outside the old center-distance two-cell shortlist.
Segment identity/source ranges preserved; connected staples and endpoint indels
block unsafe inference. Old center-distance tie retained as diagnostic only.
Long25–28nm spans remain: no axial fit, phase change, flexible-loop geometry or
native D006 publication. Do not label this a geometry pass. Evidence/schematic in
`.development-artifacts/d006-ligation-placement/`. Native authoring guard now
names independent segment/loop representation and geometry review as the blocker.

D006 native follow-up (2026-11-25): user approved generalization/publication.
`publication_native_tracks.py` maps independent auxiliary source-row intervals
bijectively to ordinary recorded helix/domain commands; rejects collisions,
overlaps, missing sites and unresolved placements. D006 published through guard:
2116 replayed commands,20 tracks,210 strands,15362nt. All209 staples and p7704
scaffold exact; independent post-construction reference comparison zero missing,
extra or wrong pointers. Source row19 splits into visible native18(loop from0)
and19(loop from1);46 unpaired bases retained as scaffold domains, no extensions.
Full topology recovery is confirmed, not simulation-ready geometry: all15152
bonds measured;22 long joins (18 source end-to-end staple wraps ~140nm,4 loop
joins). Do not silently infer periodic seams or assembled instances from these.
Portable source/code/audits in Shared Designs/.provenance/D006. Remaining D007–009
have no native documents. D007's1680 reference-only positions are70 WHOLE end
staples (20x12,20x24,30x32),28basesperhelix/840perend. All144 published paths
exactly match other reference strands. Figure shows bare scaffold at those ends:
source-variant difference, not missing interior tracing; reason still unverified.

D006 precursor/polymerization correction (2026-11-25): user explicitly confirms
the 18 end-to-end staple joins as polymerization. Fresh PDF reconstruction uses
1434 native commands: 18 body staple pens + two auxiliary-track pens, terminal
nicks, native crossover placement; all segments of 18 polymerization staples
are reserved and drawn separately. Periodic seams use existing is_periodic_seam
semantics; no assemblies/extensions or simulation policy changes. Four nonlocal
scaffold-loop joins remain. Exact source topology/sequences and saved independent
replay pass. Generic opt-in compiler/CLI flags continuous_staples and
periodic_staple_seams; the latter requires explicit caller confirmation and only
classifies jumps between same-helix scaffold extrema, never interior jumps.
Native source snapshots updated with this rebuild; previous file/provenance
retained in .development-artifacts/d006-precursor-polymerization.
Welcome-screen reopen and ordinary browser autosave also pass independent replay
(1434 commands), retain all18 periodic seams, and preserve exact sequences/routes.
Isolated browser workspace/config/spec removed; published-file hash unchanged.

General precursor defaults and D007 completion (2026-11-25): user requests the
D006 method in the general algorithm and confirms D007 terminal labels are bare
scaffold ends. compile_publication/CLI now default to continuous staple pens and
the user-authorized same-helix scaffold-extrema polymerization rule. Other
nonlocal staples remain separately authored without periodic reclassification;
interior jumps are not inferred to be seams. Original D005/D006 saved histories
and their pinned code remain unchanged. D007 publishes 1298 commands, 60 helices,
144 staples/5880 staple bases,7560 scaffold bases;1680 terminal scaffold bases
stay unpaired (28 per helix). No extra70 reference-only staples authored. Exact
published routes/sequences and independent saved replay pass; all13295 bonds
measured,zero forced/long/missing bonds. No relaxation prediction of bare ends.
Terminal admission requires supported sequence/routing, positioned source tracks,
and sites outside that helix's published staple band; interior gaps stay guarded.
Portable PDF/code/reference/replay audits in Shared Designs/.provenance/D007.
D007 welcome-screen open/save verified in an isolated byte-identical workspace:
60 helices,145 strands,13440nt,zero browser/API errors; autosaved copy independently
replays1298 commands. Cleanup verified; published original unchanged. Focused
authoring18,precursor4,unpaired12 tests pass.

D008/D009 follow-up (2026-11-25): default updated algorithm plus two general
recovery modules. publication_missing_staples admits an existing unlisted drawn
route only with complete exact scaffold alignment, full partner coverage,
unanimous antiparallel polarity and no occupied staple overlap; sequence is
explicitly derived, excluded from independent table validation. D008 publishes
1186 commands,60 helices,149 staples (148 table +1 drawn38nt at27[60]→17[55]),
7560scaf+5015stap=12575nt;2545 bare terminal scaffold bases retained. All source
pointers match separately consulted reference; no120 extra reference terminal
staples added. All12425 bonds measured,zero forced/long/missing. PDF/code/replay
and reference audits in Shared Designs/.provenance/D008.
publication_lattice_insets independently fits repeated inset copies and requires
full translated-cell consensus. D009's5 copies/46 helices now resolve. Still
10 absent drawn table routes,276 unknown scaffold partners (233terminal,
43internal),two39base loops and1base p7704 discrepancy. Score80.96 unchanged;
no D009 native model or silent extension substitution. Development evidence in
.development-artifacts/d008-d009-recovery. No source reference used to author.
D008 welcome-screen open/save verified:60 helices,150 strands,12575nt;zero
browser/API errors. Browser autosave independently replays1186commands; temporary
workspace/config/spec removed and original saved hash unchanged. Focused tests:
recovery9,authoring18,publication routing7 pass.

User-authorized on-helix staple overhang rule (2026-11-25): classify routed
staple sites lacking scaffold partners as on-helix overhangs, including internal
segments. publication_staple_overhangs selects exact table offsets (with indels),
compares independently decoded image letters, explicitly falls back if absent or
unreadable; readable conflicts never silently fall back. publication_base_labels
uses color-isolated glyph templates despite broken Unicode; optional installed
monospaced templates improve coverage, uncertainty remains unreadable. D009 has
276bases:266 image/table matches,8 absent-image table fallbacks,2 imageA/tableT
conflicts at8[117] and9[118].272bases accepted; two2base segments unresolved.
Confidence84.87 policy on-helix-overhang-v1; original6686paired comparisons and
129exact fully paired staples retained (no self-validation from table fallback).
Ten unmatched routes and1base scaffold discrepancy still block native D009;
recorded native on-helix authoring including internal segments remains required.
No extensions or molecular files written. Analysis UI shows separate counts.
Evidence .development-artifacts/d009-overhangs; real dialog browser test passed,
isolated workspace/config/spec cleaned.
Focused verification:34 backend tests (9overhang,18authoring,7routing),9UI tests,
and actual-dialog browser rendering with computed D009 evidence pass. Image/table
conflict addresses are displayed explicitly; no native files were modified.

User base-conflict policy (2026-11-25): simply note image/table disagreements;
do not block sequence assignment for them. Prefer strongest evidence; equal
evidence defaults T > A > C > G, regardless of source. Reusable resolver in
publication_base_conflicts retains original observations, selected_base, reason,
support and notice severity; duplicates from one source do not add votes.
Readable image/table each have equal default weight; OCR confidence is admission
quality, not biological support. Overhang sequences use the selected bases;
original table_sequence remains separate. D009 selectsT at8[117] and9[118],
accepts276overhangbases,score84.92; retains2notices plus10missing routes and
1base discrepancy. No native files modified. Evidence d009-base-conflicts.

D009 end-to-end audit (2026-11-25): fresh compiler still blocks at missing routes
(187/197; ten table-only paths total327nt). No native output. Fixed analysis→native
39/39 loop handoff using shared apply_supported_insertions; originals immutable.
Remaining native gaps: approved1base discrepancy still rejected by exact-length
gates; on-helix overhang authoring/comparison still blocked; native min/max
scaffold coverage masks138 of276 unpaired bases inside same-helix scaffold gaps
(other138 outside bounds), including43 internal staple bases. UI Reconstruct
is explicitly disabled and only check/analyze endpoints exist. Native generation
requires route completion, explicit candidate sequence bookkeeping, interval-aware
overhang recording/replay and endpoint/UI wiring, then saved replay/bond audit.
Details and ten endpoint pairs: docs/d009_reconstruction_readiness.md. This is an
implementation/readiness report, not a finding that new source data is certainly
necessary. No reference design was used for this audit.

## Partial native reconstruction — 2026-11-25

D009 is published as a partial source-only native design: 1591 operations, 46
helices, 194 staples, 7703 scaffold bases, two 39-base insertions, 285 native
overhang bases. Seven of ten table-only routes are unique under bounded native
crossover/sequence search; two are ambiguous, one has no match. No archived
reference was used. Source comparison, guard publication and saved replay pass.
Native review measures 14678 bonds, six >1.2 nm (two nonlocal joins/four loop
boundaries); unrelaxed geometry. See docs/d009_partial_reconstruction.md.

Arbitrary scaffold gaps are split/tagged as native overhang domains. Initial
staple fine routing spans interior gaps, then records nicks/deletions to remove
unsupported intervals. Partial output omits unresolved routes, preserving full
process for all included strands. The CLI defaults to --allow-partial. A new
reconstruct endpoint and selected-figure/table dialog download ZIP packages with
reports, source PDFs and recipes; failures retain reports without fake models.
Custom scaffold native generation remains unsupported and is explicitly rejected.

Gap overhang reconciliation also transfers OverhangSpec identity with joined
strand ownership; otherwise the first sequence normalization can discard prior
labels/subdomain identities and later document-source replay diverges. The
ownership regression test covers this; final native rebuild uses the fix.

Final validation: 67 focused backend checks, 13 UI tests, two real-app flows;
browser autosave independent replay and downloaded native package both verified.
Temporary test workspaces/configs cleaned. D009 partial visible on welcome.
Main.js task LOC delta: 0. Broad regression suites were not run.

## Source figure colors and helix order — 2026-11-25

publication_appearance.py preserves PDF stroke colors; table-only routes use a
unanimous observed palette mapping or explicit nominal-table fallback. The
compiler applies color with final sequence metadata and uses recorded
helix-reorder after routing to preserve figure row order without renumbering.
D009 is rebuilt with 1592 operations and appearance verification. Its figure
order is 45–34, 16–21, 0–15, 33–22 (first/last descending). The source visibly
labels both 30[119] and 42[119] as 39-base insertions; saved deltas are +39, not
skips. See docs/publication_appearance.md.

Appearance validation: 23 focused backend tests and the live welcome/caDNAno
editor flow passed, including all colors, row order/labels and insertion deltas.
Browser autosave replay/source comparison passed; temporary artifacts cleaned.
Main.js task LOC delta: 0.

November 26, 2026 — preferred large scaffold insertion representation:
`publication_insertion_loops.py` selects native `strand-loop-set` for multi-base
scaffold-only insertion annotations, requiring a unique anchor, following base,
and source-supported polarity. Paired insertions and single-base corrections
remain helix-wide loop/skip marks. Compilation places loops after scaffold joins
and before final sequence assignment; reports expose the representation and the
native-only export limitation. D009 selects 39 bases on each of visible helices
30 and 42 at 119; D005 selects its 144-base insertion. No bulk migration of
legacy files or collapse of D006 auxiliary routed tracks. The user requested
this preference after the strand-owned loop feature shipped; it uses that
feature's approved default geometry without changing molecular placement code.
D009 source rebuild and saved independent replay passed (1592 commands, two
strand-owned loops, unchanged 7703 scaffold bases and 194/197 staples). Cold
browser geometry took ~239 seconds after navigation, autosave ~265 seconds;
90s and 240s observation budgets failed despite eventual successful render/save.
Retain this display-performance limitation; do not bypass approved ring fitting
or claim simulation/export support. Evidence: `.development-artifacts/d009-strand-loops/`.
Longer app observation completed both 39-base loop render checks and caDNAno
colors/order/count assertions without app errors. Its inherited 360s suite
budget expired in teardown; do not report a clean Playwright pass. Browser
save audit/cleanup is handled separately by finish-browser-audit.py in the
same evidence directory.

Browser-saved D009 independently replayed and matched source evidence; all four
cleanup checks passed, including unchanged published-file hash. 26 focused
backend tests passed. Loop close-ups and caDNAno screenshots were inspected.

November 26 optimized-loop end-to-end benchmark (HEAD eab2ca3b plus current
reconstruction changes): actual reconstruct_package, one fresh process per
design, serial Ryzen 9 9950X runs. D005 332.882s, D006 100.050s, D007 78.268s,
D008 63.986s, D009 243.827s. Includes PDF extraction/planning, native recorded
authoring, all three audit passes, save/reopen and ZIP packaging. Starts with
PDF and figure/table selection supplied; excludes DOI/network, detection UI,
Python startup and browser rendering. D005–D008 complete; D009 194/197 staples,
partial. All five source comparisons, guarded publications and reopened replays
verified; loaded code hashes stable, shared files unchanged. Reports, source/code
hashes and reproducible driver: `.development-artifacts/reconstruction-benchmark-20261126/`.
Temporary package copies removed after retaining verification reports; scratch
cleaned. This does not remeasure or supersede the historical browser-load timing.

November 26 D014 lower-quality publication probe: channel-and-flap nanopore,
10.1038/s41467-019-13284-1; Figure31 PDFp45, Table6 pp46–49. Catalog79 is
manual image recoverability, not measured completion. Actual detect_designs
finds the raster figure and four page lists (52/80/80/58 tokens); native package
returns report-only in0.44s: no uniformly labelled publication ruler. No native
models or validated routes. Four unique image assets in five PDF placements,
including an overlapping duplicate, need compositing/registration and raster
tracing. Endpoint-free Module/Notes/Sequence table needs multi-page grouping,
variant and modification preservation; Note6's explicit module rule yields
219 staples for each Top_A/Top_B variant, not all270 tokens combined. Header-
derived exploratory inventory preserves raw chemical tokens and bold spans.
Local exact12mer probe: M13mp18 supports at least one match for all219 rows;
similar scaffolds support218. This does not resolve global route/register or
prove scaffold identity; uncovered bases are not automatically overhangs.
Context-only figure/list score60 is inflated by repeated paper-header words.
Eight gaps/acceptance checks, source hash, actual baseline and deterministic
probe scripts: `.development-artifacts/d014-reconstruction-exploration/limits.json`.
No production behavior changed; shared D005–D009 hashes unchanged. Disposable
page renderings inspected and removed; original corpus source retained.

## Structured table import and raster trace evidence — 2026-11-26

`publication_table_import.py` recognizes Module/Notes/DNA Sequence headers and
adjacent continuation pages. It preserves physical rows, source boxes, bold
functional spans, slash-delimited chemistry, module names and notes. Unlabelled
rows retain possible continuation links rather than silently concatenating.
D014 imports all 270 physical rows across pages 46–49; Top_A and Top_B remain
separate 20-row modules (the documented Top_A+inner+cyl*/flap* selection is 219).
The UI allows explicit module selections for the evidence report, not automatic
assembly of every variant/accessory into one design.

`publication_raster_tracing.py` renders the visible PDF composition (including
occlusion), registers pixels back to unrotated PDF coordinates, and skeletonizes
chromatic layers into paths with branch ambiguity retained. It does not bridge
missing pixels or infer nucleotide coordinates/polarity. Neutral strokes remain
unclassified. This replaces caption-only raster evidence but is not OCR or
helix/base registration; D014 native reconstruction remains blocked there.

Lipids are explicitly unsupported. Recognized terminal modification tokens are
checked against NADOC's existing modification registry; terminal Cy5 is supported
pending verified strand mapping, whereas internal Cy3 and unspecified /DYE/ are
unsupported. Handles/toeholds are labeled native-overhang candidates pending
verified unpaired intervals; bold text alone never proves an overhang. No
terminal extension substitutes for overhang DNA. These annotations are retained
in source evidence; no native chemistry is created on an unresolved route.

Reconstruction ZIPs preserve source PDF, table rows, selected modules, annotation
notices and registered raster traces even when native construction fails.
Focused source-import/regression tests and the real D014 browser upload → module
selection → report download passed. No shared molecular designs changed.
Main.js task LOC delta: 0.

Validation for this increment: 26 focused backend tests passed; real D014 raster
probe produced 14,902 raw color-skeleton fragments and 1,814 ambiguous junction
observations across five image placements (no trace cap reached). These counts
include unclassified marks, not recovered oligos. The required smoke run was
25 passed / 2 skipped / 2 failed: assembly setup exceeded 60 seconds and Close
Session's progress-visible assertion failed. Those separate paths were not
modified. Browser downloads, test structures and browser artifacts were cleaned.

### D014 troubleshooting follow-up — 2026-11-26

Corrected the prior missing-ruler diagnosis: visual source review finds an
apparent 21 marker, while deterministic grid probes recover periods ~5.681,
4.786 and 5.339 native pixels/cell for upper-left, lower-left and flap panels.
Recovered 40/21/42 row-circle observations; helix 39 overlaps in the two left
assets. These are evidence probes, not verified native registrations.

Fixed production tracing to preserve native raster resolution within a 4096px
page cap, reporting downsampling explicitly. D014 now uses 3.397 rather than
2.613 pixels/PDF point. More detail does not solve semantic graph extraction:
raw fragments/junction observations increase to 19,988/2,531. Template OCR and
short-domain sequence probes do not yield a unique route. Details and measured
limitations are in docs/publication_native_authoring.md, D014 troubleshooting.
Main remaining implementation is cadnano lane/endpoint/crossing recognition and
joint sequence-constrained pairing across panel cuts, not another unconstrained
scaffold-offset search. Do not call the source impossible to reconstruct.

17 focused backend tests and the real D014 browser flow passed after this fix;
lint passed. Native model count remains zero. Temporary source images and browser
artifacts cleaned; three useful source crops/probe results retained locally.

### Registration algorithms and bounded sequence fallback — 2026-11-26

Researched/tested phase correlation, SIFT/RANSAC and grid-normalized normalized
cross-correlation. NCC supports D014's shared left-panel strip (0.872 vs next
0.545), while the flap has weak ambiguous peaks (~0.453/0.443). Production
`publication_panel_registration.py` reports these image-only hypotheses and caps
asset size/panel count. Raster evidence and UI distinguish image overlap from
molecular connectivity.

Added `publication_sequence_domains.py`: bounded split-domain alignment, circular
scaffold indexing, explicit unassigned bases, retained alternatives/pruning flags,
and HiGHS occupancy compatibility with a second-optimum check. Native failure
packages run 8-/6-base passes for selected modules; unset membership is deferred.
Beam-8 D014 pools give 4,152/4,683 compatible paired bases with equal-score
solutions. Beam-32/60s gives 5,243 incumbent bases, not proven optimal (~2% gap).
These are candidate contact assignments, never completion percentages/native routes.
Research/probes are under `.development-artifacts/d014-registration-search/`.
See docs/publication_native_authoring.md for method references and caveats.

REVNANO research comparison: upstream commits recorded in development artifacts;
no example models/contact maps supplied as inputs. Raw D014 trial timed out at
180s. Explicit bold-functional-span-as-unpaired hypothesis (438 bases/32 strands)
with default MU_MIN=6, SIGMA=4, BETA=.3 resolved 78/219 before GAMMA=.65 stopped
stage 2; SIGMA=2 resolved 73/219. No final contact map returned, no native model
published; both runs used default GAMMA=.65. This is a research comparison only, not a
runtime dependency. Tesseract numeric OCR trials also retained disagreements;
temporary OCR runtime/debs cleaned with package hashes/recreation script retained.

Alternative scaffold trials: p7560 resolved 68/219 before the same prerequisite;
p8064 timed out during routing-tree construction at 120s (incomplete trial).
Production full-PDF/219-row package probe completed in 10.64s, reporting one panel
overlap and both ambiguous sequence passes; no native part. Decode PDF image
assets through PyMuPDF rather than Pillow to handle this source's image streams.

Validation: 28 focused backend tests, 16 frontend unit tests and the real D014
upload/detect/module-select/download browser flow passed. Browser test now waits
for and asserts the analysis HTTP response before checking cards; the previous
card-only wait timed out. Browser downloads/artifacts and isolated bridge
credentials were cleaned. This task made no main.js changes or native structures.

### Stable sequence anchors — 2026-11-26

Added `publication_sequence_anchors.py`: base-level consensus across compatible
solutions, independent exact occurrence counts over the circular scaffold, and
bounded whole-core exclusion challenges. Missing staples count against support;
unique sequence occurrence is not unique native routing. Pruning, counterexamples,
retained-pool necessity and timeouts are explicit. Alternative occupancy assignments
are now retained, rather than only their scores.

`publication_sequence_refinement.py` adds anchor-conditioned candidates without
removing original alternatives; it preserves the best feasible incumbent if a
larger timed-out search regresses. `publication_sequence_neighborhoods.py` jointly
reassigns unresolved staples and their occupancy blockers while recording the fixed
outside context. It reports residual circular scaffold intervals without declaring
loops. `publication_anchor_image_mapping.py` reports length-compatible horizontal
spans, possible offsets and both directions; it never promotes length alone to a
native mapping. These stages are wired into failed reconstruction evidence and
compact report summaries. main.js task LOC delta remains zero.

D014 larger-budget exploration: 67 initially unique cores; 59 cores/961 bases
survive six assignments. Sixteen two-second exclusion trials were inconclusive.
Anchor-conditioned generation added 818 candidates across 62 rows, reaching 5,681
paired bases at 30s. A union-of-original-pools control reached 5,800 at 30s, so do
not attribute this gain to anchors. Eight local neighborhoods found no further
pairing gain. Best residual: 1,449 bases in 219 gaps, largest 44. Image screening
found 115 spans; even the longest surviving core has three candidates. Image
endpoint/strand identities and crossover connectivity still block native routing.
No D014 native structure was created.

Default production uses tighter budgets: four one-second challenges, 12 expanded
rows, beam 16, two one-second neighborhoods. Full PDF/219-row report completed in
17.76s, retained 4,721 paired bases and 86 consensus cores (85 unique initially).
These counts differ from broader exploration because fewer alternatives were
searched, not because default anchors are more certain. Reproducible evidence:
`.development-artifacts/d014-stable-anchors/`; detailed results and limitations in
`docs/publication_native_authoring.md`.

Validation for stable anchors: 39 focused backend tests passed (6.95s), including
shifted boundaries, repeated sequences, circular wrap, missing support, exclusion
witnesses/timeouts, incumbent preservation, blocker reassignment, and source-package
contracts. Real D014 browser upload/detect/select/download passed (37.7s). Ruff and
diff checks passed. Browser artifacts and the isolated bridge credential were
removed; only reproducible development evidence remains locally.

Visual review correction — D014 alignment demonstration (2026-11-26): all three
length-screen spans for longest core p49-r230 (`cyl_lip / Pal`, 27 bases) are blue
scaffold strokes, visible helices 80, 89 and 0. Do not call these three plausible
staple placements. ISSUE-265 tracks missing scaffold/staple lane classification
and endpoint/connectivity recovery. The user-requested annotated source review is
`.development-artifacts/d014-alignment-review/alignment-issue.png`; raw temporary
page/crop renders were removed. No algorithm or native structure changed here.

### Scaffold/staple classification and connected tracing — 2026-11-26

ISSUE-265 screening false positives are fixed: `publication_lane_classification.py`
learns the recurring scaffold hue and alternating paired-lane pattern, with local
corroboration. It does not assume blue means scaffold; blue staples and alternate
scaffold colors are covered by tests. Unsupported rows remain unclassified.
`publication_staple_tracing.py` traces the visible PDF composition, resolves only
coherent distinct-color straight crossings, and records source pixel connectivity,
domains and unresolved endpoint junctions. Same-color crossings and missing pixels
are not joined. Unbranched traces are not certified full strands. No native routing
or molecular geometry is generated.

`publication_anchor_image_mapping.py` now uses only classified staple domains with
supported color continuity. There is no raw-stroke fallback. All three prior source
false positives are excluded (source-coordinate regression); the longest core now
has one length-compatible staple fragment at visible helix 89, still not an identified
table staple. Detection UI reports classified/unbranched trace counts as fragments.

D014 visible source: two of four image placements support the pattern (32 flap and
30 upper-left row observations). Overlapping lower-left placements remain unsupported;
do not substitute hidden native assets. 309 staple trace observations, 99 unbranched;
not recovered-staple counts. One coherent fragment spans staple lanes at visible
helices 64 and 67. One distinct-color crossing resolved; dense junctions remain.
Anchor screening excludes 303 scaffold-domain observations. Page probe 6.22s;
full 219-row source-to-report package 18.54s, no native part. Evidence and annotated
source review: `.development-artifacts/d014-staple-tracing/`.

Remaining image work: terminal-marker recognition, ambiguous-junction recovery,
neutral strokes, absolute base registration and strand/table identity. Main.js task
LOC delta zero; native structures created zero.

Final classifier guard: a strong local color/phase contradiction leaves the row
unclassified even if the nominal scaffold lane contains some recurrent color.
This guard is regression-tested; D014 observations remain unchanged. 43 focused
backend tests and 17 frontend tests pass. Source-image review confirms separation
at visible helix 89 and the connected fragment between 64 and 67; the annotated
review is retained, disposable crop renders removed. Ruff and diff checks pass.
Final browser exercise after the contradiction guard passed (45.1s). No browser
artifacts or isolated bridge credential remain. Validation summary is retained in
`.development-artifacts/d014-staple-tracing/validation.json`.

D014 connector update: user identifies same-helix offset drawings on lower-bp
side of helices 86/89. Added generic continuous-detour recognition, bounded graph
alternatives, partial offset runs, neutral-ink screening and weak endpoint-marker
annotations. Geometry excludes drawing excursions from base counts. Real source:
89 partial offset with unresolved left continuity; 86 single thresholded dark
pixel marker, not established polarity/ligation. Five partial hypotheses, zero
complete connectors; upper-left 12k graph cap, marker caps100/panel. Full219-row
package19.80s,4721 candidate paired bases, no native part/coverage gain. Evidence:
.development-artifacts/d014-connector-drawings/. Source regression slow/headless;
53 focused backend and18 frontend tests passed. Main.js task delta0.

User correction (2026-11-26): helix86 dark pixel is a bp-index label, not an
endpoint marker. Reject single-pixel neutral components; source regression now
requires this false marker absent. Helix89 endpoint evidence is adequate to
continue sequence checks. Small image gaps are not strand-break evidence.
Added publication_sequence_continuity: same-row/color pairs with <=3 missing
raster pixels are screened against exact table/scaffold cores spanning both
fragments; retain directions/registers and competing identities. Offset connector
spans also feed sequence checks. Results are conditional on image register,
not automatic native ligations. Earlier connector-review.png helix86 annotation
is superseded. New evidence: .development-artifacts/d014-sequence-continuity/.
Current source verification: 2 small-gap continuity candidates; helix89 short
fragment now yields32 exact sequence candidates (cap reached, alternatives
truncated). No unique table identity/native route claimed. Full219-row package
20.07s.42 focused tests passed;11 affected tests rerun after short-fragment search
passed. Ruff/diff checks clean. No frontend changes; main.js task delta0.

Reconstruction reporting (2026-11-26) separates complete and partial audited
native output from report-only evidence. The download index and per-design
reports carry issue codes, stages, severity, evidence references and actions.
D014 remains report-only. Prioritize general labeled registration and joint
source constraints over tuning D014-specific pixel rules. Corpus probes compare
native-recipe outcomes, parser limits and independently reviewed source scope.
See docs/publication_reconstruction_triage.md. Main.js task LOC delta: zero.

2026-11-27 recovery session: authoring and Detect designs now try panel-local
vector registration when the single-ruler extractor fails. D010/D011/D012
match every directed pointer of their held-out author files, including rotated
D011 and the separately scoped pEGFP D012. D010 and D011 need two rigid group
frames plus validated scaffold junction geometry. All 32 catalog sources were
inventoried; see docs/publication_recovery_session_20261127.md for the 26
remaining targets, raster/fragmented source benchmarks and next discriminators.

D012 (pEGFP variant only) was published through recorded editor operations
in Shared Designs, then reopened and replayed (1,197 commands, 54 helices,
121 staples, 4,733 scaffold bases, one strand-owned 71-base loop). The
historical caDNAno scaffold resolves one discrepancy against GenBank.
The continuous variant pre-cuts the later domains of a revisited helix
before joins. It completed through the download path in 70.0 seconds with
926 commands. Legacy single-panel operation schedules are preserved.
The five-source sequence test measured 6.7 seconds in exhaustive full
publication register comparisons, now routed to slow/headless. The focused
run including it passed 81 tests. Main.js task LOC delta: zero.
