---
name: project_corner_primitive
description: Native Corner tool, replayable scaffold/staple routing, approved seam geometry, Full preview, validation and remaining limits.
metadata: 
  node_type: memory
  type: project
  originSessionId: 2716c75a-b4c8-4c6c-9b45-def883afa1b3
---

# Corner tool — November 23, 2026

## Geometry explicitly approved — November 23, 2026

The user approved the demonstrated candidate: **"Geometry approved. It looks
good enough for simulations but we'll need to validate that once implemented."**
This supersedes every pending molecular-approval note below. Proceed with scoped
production integration; do not ask for that approval again. It is not proof of
simulation stability or authorization for a physical production campaign.
Keep the frozen comparison as an independent regression fixture. The assembly
shared-source versus selected-instance ownership question is still unanswered.

## Calculation profiling and exact optimizations — November 23, 2026

Routing plus native recording takes about 0.15–0.30 s for the 168 bp 6HB and
flat square benchmark. Full and undeformed molecular projections dominate.
A serial 6HB cProfile run (both projections, 28.8 s including profiler overhead)
attributes 13.2 s to seam closure, 4.8 s to initial bridge fitting, and 5.7 s to
recursive cache memory accounting. Those instrumented numbers are hotspot
evidence, not interactive latency predictions.

Corner now accelerates the seed bridge's scalar cost while retaining the native
finite-difference solver, initial guess, stopping criteria and atom scatter.
The seed uses NumPy bond powers and Python angle powers; preserving these types
retains its exact cost. Closure reuses invariant offsets/branch membership and
compiles its existing cross-product arithmetic without fastmath. Memory charging
short-circuits exact built-in scalar leaves while retaining identical charges,
array/object handling, subclass traversal and cache limits.

Paired backend measurements, including both worker projections:

| Case / cache condition | Before | After |
| --- | ---: | ---: |
| 6HB, cold geometry caches | 13.30 s | 10.13 s |
| 6HB, identical inputs | 5.99 s | 5.25 s |
| 6HB, direction changed by 15° | 11.23 s | 9.99 s |
| 1×8 square, cold geometry caches | 14.33 s | 11.26 s |
| 1×8 square, identical inputs | 7.68 s | 6.32 s |
| 1×8 square, direction changed by 15° | 15.19 s | 12.27 s |

These are single paired runs on the development machine with the numerical
compiler's disk cache already populated; they exclude HTTP and browser rendering.
Reproduce with `just validate-safe uv run python -m scripts.benchmark_corner`.
It builds through native recorded commands in disposable in-memory sessions and
checks that preview does not mutate the source; it writes only timing JSON.
The frozen geometry fixture and all solver limits remain unchanged. ISSUE-264's
1–2 s target remains open; molecular fitting is still the dominant remaining cost.

Validation: 36 focused backend checks pass, including exact scalar costs and seed
solver output, the four frozen atom cases, ordinary/physical isolation, memory
charges, worker cancellation, prepared Apply and native replay. Lint passes for
backend/tests and the benchmark; `main.js` LOC delta is zero. Both 6HB and flat
square app workflows pass through preview, Apply, undo/redo and history edit;
both applied axis displays were inspected. The combined run's square case hit
the unchanged 240 s overall limit during its last preview; the isolated rerun
passes in 3.9 minutes without code or timeout changes. Cold server previews in
these software-rendered app runs remain 15.85 s (6HB) and 18.93–19.17 s (square),
so the isolated backend improvement must not be presented as an equivalent
end-to-end browser speedup. Parameter-to-ready times were 15.74 / 20.54 s in the
combined run. All test parts, revision stores, reports, sessions, scratch and
isolated credentials were verified absent after both runs. No broader suite or
physical simulation was run for this pure calculation optimization.

## Preview publication and cropped axis correction — November 23, 2026

Apply now consumes the exact native candidate evaluated for Full preview. The
server retains its real recorded/replayed history, validation and both geometry
projections under a single-use token bound to the document/session, source object,
revision, feature selection, inputs and host policy. Publication uses the normal
undoable replacement transaction; no fitting, routing or command replay is repeated.
The cache is limited to four entries / 96 MiB serialized total and expires tokens
after 15 minutes. Direct API authoring without a preview still uses native commands.

Full and undeformed-view projections run independently in two bounded disposable
workers so preparing the complete handoff does not serialize their numerical fits.
Both are reaped on cancellation. Their output matches the unchanged serial native
providers. This is software performance work, not a molecular geometry change.
The existing editor save hold drains pending acknowledgements before source capture
and defers autosave during the interaction; publication source guards remain strict.

Curved axis tubes now honor even a single occupied domain. Corner's retained full
indexed paths remain available for frame evaluation, while the visible axis stops
at the actual domain boundaries. No helix path, base position or topology is changed.
Issues 268–270 track these corrections. Nine selected backend tests and 59 frontend
checks pass, including exact equality with the canonical response, ownership
refusals, replay and both worker cancellations. App workflows pass for 6HB and
flat 1×8 square creation/edit, plus native save/reopen/delete/revert/undo and
independent recipe verification. Both applied axis displays were inspected.
An initial Chromium response-body capture failure was corrected by collecting
stream bodies immediately; the square rerun passes the unchanged time limits.

Measured Apply response headers arrived in 0.38–0.82 s. Complete scene refresh
still takes 4.3–5.1 s in the software-rendered browser; edits take 2.8–5.3 s. This
is not an instantaneous UI promise. Before the subsequent calculation optimization,
Full preview prepared both projections in about 16–22 s in these app cases;
the original 1–2 s target remains open (ISSUE-264).
The frozen molecular fixture retains SHA-256
`e5af0d648a6b0ab28a0397f84ac3bf2a9181481b6e3c1a5f88cb82dbaeccb5d2`.
No production physical simulation ran. `main.js` LOC delta is zero.
Lint passes. Smoke remains 26 passed / 2 skipped / 1 known assembly-fixture timeout
at `scene_harness.js:434` (ISSUE-266, previously reproduced on untouched upstream).
All isolated test artifacts and the verified legacy-fixture revision cache were
removed; no user-workspace files were modified by these checks.

## Approved provider integrated and checked

The native atom builder defers only recorded Corner seam inserts until the final
wedge frames, then runs the approved two-pass closure. Ordinary junctions and
explicit physical coordinate overrides retain their providers. Four frozen cases
match all atoms (1e-8 nm), bonds and residue metadata; mixed Corner/non-Corner
inserts preserve unrelated atoms bit for bit. The frozen fixture is unchanged.

Full beads, base slabs and endpoint O5′ sites come from those atoms. Compact and
partial updates carry fitted inserts; saved poses apply once. oxDNA conversion
uses the unchanged duplex ring's rigid particle frame; inserted oxDNA residues
retain the existing physical seed interpolation. No production simulation or
physical stability validation has run.

Exact bridge/clearance arithmetic, ordered clash queries, reused fit setup and a
bounded exact-coordinate cache reduce calculation cost without changing the
approved oracle. Bounded disposable workers perform detached display projection;
source-bound native commands still own authoring. Cancellation reaps that worker
and shared memory. Progress counts actual completed fits; ETA starts after
observed fitting work. Identity encoding avoids GZip buffering. Library watchers
subscribe only to mutation events, avoiding unused read-event traffic.

Tests cover exact arithmetic, frozen atoms, source/physical override isolation,
worker cancellation and independent local-provider equivalence. The 6HB live
workflow now passes preview, numeric arrows, Apply/rendered seam positions,
undo/redo and history edit. The dedicated persistence app test passes delete,
revert, undo after each, native save/reopen, and independent recipe verification.
All four representative live workflows pass (6HB, flat square, nicked 6HB and
sequence-assigned continuous-scaffold 6HB; 13.2 min). Flat 1×8 square Full preview was
visually inspected in that run. Cold server previews measured 14.09 s (6HB) and
17.51 s (square); parameter changes took 21.8/25.6 s including browser actions.
The requested 1–2 s Full-preview target remains unmet (ISSUE-264). Cylinder
preview passes the two-second check. No timeout or geometry oracle was relaxed.

Corner edits part topology. Assembly invocation explains how to open the source
part from the library; direct instance authoring awaits an explicit shared-source
versus independent-part ownership policy. It does not mutate a hidden part. Explicitly organized parts and selected
attachments/other references still require placement-membership/remapping
support; unsupported inputs are refused before authoring.

Final integration uses an isolated `codex/corner-tool` worktree atop
origin/master to preserve unrelated dirty work. Upstream extension-slab behavior
is retained. Integration also exposed recursive extension-slab projection inside Corner
atom construction (ISSUE-265). The bounded native-authoring regression reproduced
it; endpoint-only internal queries now omit extension display slabs. All 174 selected backend checks pass, including reopened replay and shared
placement boundaries. Two preview assertions needed only JSON list/tuple
normalization; exact coordinate equality remains enforced. All 114 frontend
checks pass. Lint passes. The frozen review SHA-256 remains
`e5af0d648a6b0ab28a0397f84ac3bf2a9181481b6e3c1a5f88cb82dbaeccb5d2`.

Corner issue IDs were shifted from local 258–262 to 260–264 because
258/259 were independently used upstream. Integration branch: `codex/corner-tool`; target: `origin/master`. See Git for
the delivered commit identity; the dirty shared main worktree is preserved.

### Final validation and remaining scope

- 174 focused backend checks and 114 frontend checks pass. Exact frozen atoms,
  non-Corner isolation, physical-coordinate overrides, fitted Full landmarks,
  worker cancellation and replay are covered. `just lint` passes.
- All four representative browser workflows pass in the working tree. The
  integrated tree's 6HB and persistence/replay workflows also pass (3.7 min),
  with actual rendered inserts checked and the final Full preview inspected.
  Latest integrated 6HB: 14.36 s cold server preview; 14.94 s input-to-ready
  measured in the page (22.35 s including automation actions). Main.js LOC Δ: +3.
- `just smoke`: 26 passed, 2 skipped, one assembly fixture timeout. A focused
  single-worker retry and untouched upstream `afbc311c` reproduce the same
  timeout before the exit action (ISSUE-266). This is not a green smoke verdict.
- No temporary test parts, revisions, sessions, bridge credentials or reports
  remain. The smoke fixture's two newly-created legacy revision snapshots were
  identified and removed only from the isolated workspace (ISSUE-267). The
  shared main workspace retains its 1,322 pre-existing snapshots.
- Full preview is functional but still exceeds the requested 1–2 seconds.
  Organized-part placement ownership, direct assembly instance edits and
  selected attachment/reference remapping remain unsupported. This does not
  establish physical simulation stability; no production simulation was run.

## Historical continuation: edit progress and diagnostic scope

ISSUE-263 is fixed: history-preview percentages now cover four observed phases
(source proof, selected seam rebuild, suffix replay/validation, Full projection),
with fractional seam progress and approximate ETA. Only completed Full projection
reports 100%. Two focused history/stream checks pass. The 1×8 square app workflow
also passes, now asserting streamed monotonic percentages/ETA and actual numeric
arrows. Preview ready 2.160 s / paint 2.624 s; run 2.0 min. Its screenshot was
already removed by teardown before inspection; do not claim a new square visual
inspection. Previous square visual checks remain recorded below. Cleanup verified
no Corner parts/session artifacts, reports or 5175 credentials; 1,322 existing
revision snapshots remain. No active tests.

`experiments/corner_seam_scope.py` prevents the isolated candidate's global
insert deferral from operating on non-Corner inserts. It checks native Corner
command output namespaces before atom construction. This is not a replay proof
or a production adapter. The new test uses real Corner → Join → inserted bases,
reopens and independently replays the source, and verifies rejection before any
atom construction. Scope plus optimizer tests: 2 passed. Existing candidate
coordinates and frozen A/B evidence are unchanged; production is still untouched.

Assembly inspection confirms Corner changes source topology, so ownership must
be explicit. An async question is pending: update the shared source and all its
instances, or create an independent source for only the selected instance? The
existing part-editor save-back writes shared source content, while source-open
also renames metadata without a native feature. Do not reuse those paths as a
provenance-complete Corner adapter without resolving their recording semantics.
The assembly ownership question remains unanswered; molecular approval was later
explicitly granted as recorded above.

## Git delivery and numeric-control follow-up

The user explicitly requested **commit and push when finished**. Do not commit
the unfinished feature or include unrelated dirty work. Current branch is
`master`, tracking `origin/master`, locally reported 12 commits behind at
inspection; remote is `https://github.com/DNA-origamicon/NADOC.git`. Resolve
synchronization safely at delivery without rewriting history. This request
does not by itself authorize unrelated changes.

ISSUE-262: number spinners were snapping off-grid inputs to a step multiple
(83 bp → 84 HC / 88 square), rather than adding 7/8 bp. Corner now anchors native
steps to each valid input, including linked nm and arbitrary angles. The lower
angle limit follows the same step origin. Regression failed for both lattices
before the fix; 13 popup/parameter/controller tests pass. The 6HB app test passes
actual arrow keys, Full preview, Apply, undo/redo, edit, delete and revert in
2.4 min. Preview ready in 1.945 s / paint 2.301 s; screenshot inspected. Cleanup
verified no test parts, session files, captures, reports or 5175 credentials;
1,322 pre-existing revision snapshots remain. An initial command setup failure
ran Playwright from the wrong directory; its sole 45-byte report was removed.
Use `just validate-safe env -C frontend node node_modules/playwright/cli.js test
e2e/corner.spec.js --grep=Corner.6HB:`. No active test processes remain.
Main composition-root delta remains +3 wiring lines.

## Current continuation: isolated review ready; geometry approval pending

`?geometryReview=corner` opens the prepared comparison in NADOC. The first
focused browser attempt timed out switching to the large square Ball and Stick
model; the review now defaults to Full-style atom landmarks. The following run
passed all4cases, representation switching, seam focus, source immutability,
and disposal in1.7min. 6HB atom/junction/Full and square/HC2/SQ2 Full images were
visually inspected. Test parts, revisions, reports and5175credentials were
verified absent afterward. The review explicitly reports the unchanged0.08nm
severe-overlap threshold (1–2/1–3 exclusions), rather than implying van der
Waals clearance. Its threshold-label unit checks and four-case app rerun passed.
The user was asked asynchronously to authorize the demonstrated Corner seam
provider. **No answer or approval yet; do not promote production geometry.**

Exact-plane **authored nicks** are now supported. Each side must have unique
occupancy and a genuine existing strand terminus; no arbitrary strand joining
is introduced. Each nick end follows its own wedge tip through clipping or
extension. Ordinary crossovers at the plane and unpaired gaps still reject.
Existing accepted v1/v2 routes remain unchanged.27focused checks passed across
routing, topology, and native command replay, including both polarities and
JSON-reopened Nick→Make Cluster→Corner recipes. The nicked6HB app exercise passed together with the review threshold-label
check (2tests,2.5min). Native preview ready1.713s/paint2.064s; Apply,undo/redo
and history edit passed. Its screenshot was inspected and all test parts,
revision stores,captures,reports and5175credentials were verified cleaned.

The global `group_organization` host rollout remains disabled independently of
Corner (`part_group_organization_gate.py`); do not enable that unrelated rollout
to remove a Corner admission error. Broader routed-source/assembly support and
molecular promotion remain outstanding; this is not a finished feature.

## Current command version: v3 sequence ownership

New commands now use `_proof_version:3`. The insert-count policy remains v2's
0.68nm screen, but newly extended duplex tips receive N instead of duplicating
assigned sequence from the opposite side of the cut. Retained bases keep their
original sequence. v1/v2 retain their recorded sequence behavior; v1/v2/v3
counts and JSON-reopened process replay are tested. History editing and frontend
native-feature recognition accept all3versions. This is topology/sequence
ownership only; no production atomistic placement changed. The frozen A/B
artifact still faithfully describes its v2 native source; its unassigned source
and seam counts are unaffected by this v3 sequence-only change.

A native continuous-scaffold test exposed an original endpoint claimed by both
wedges when their miter extensions overlap. Routing plans now carry the original
split station; endpoint remapping retains an original endpoint only on its
original side. This fixes a previously rejected input; it does not move ordinary
crossovers.29routing/topology/native-command checks passed before the sequence
fix. Afterward23command/history/preview/topology checks passed, including the
sequenced continuous scaffold, both nick polarities, v1/v2/v3 replay and unchanged
crossover identities/stations.9frontend history/parameter/review checks passed.
The routed, sequence-assigned6HB app check passed in1.4min: preview ready
1.687s/paint2.040s, Apply,undo/redo and history edit. Its screenshot was inspected.
All test parts/revisions/reports/5175credentials were verified cleaned, with1322
pre-existing snapshots unchanged. Main.js remains+3thin wiring lines. ISSUE-260
records the ownership fix; ISSUE-261 tracks the unapproved atomistic provider.

## Earlier v2 ssDNA contour screen (retained in v3)

Corner v2 selects the shortest
native insert candidate whose Full backbone steps are ≤ the existing
`SSDNA_CONTOUR_PER_NT_NM` (0.68nm). v1 retains the earlier 1.2nm ordinary
crossover screen. No molecular placement changed. Native recording now preserves
Corner's validated explicit version instead of stamping every snapshot as v1;
edit admission and frontend native-feature recognition accept both versions.
Source v1/v2 counts survive JSON reopen and independent replay. The 6HB 84bp,
90°/15° case uses [2,3,3,3,2,3,1,5,3,3,3,4] in v2 versus the v1 list
[1,2,1,2,1,1,1,2,1,1,1,2]. These are unpaired seam bases, not terminal extensions.
Focused Corner command/history/preview/Sweep checks: **13 passed**; shared
recording transaction and recipe-edit checks: **70 passed**. Frontend version
and feature-history checks: **5 passed**. The in-app v2 run **passed both cases**
in3.2min:6HB ready1.996s/paint2.321s; SQ ready2.372s/paint2.783s. Both cover
pick→Drill, Full, Apply, undo/redo and history edit;6HB also deletes/reverts.
The v2 6HB screenshot was inspected; square's v2 screenshot was cleaned before
inspection (the square v1 geometry was visually inspected previously). All
parts, revision stores, reports and5175credentials were verified cleaned.

The isolated 6HB component search with the entire native duplex atom environment
completed. All 12 seams have a local candidate with 1–3 bases satisfying ≤0.20nm
flexible covalent bonds, zero local clashes/piercings and zero external atom
contacts <0.08nm. Every count chosen by the v2 Full contour screen is among
those clear local options. This does NOT test exact external ring piercing or
interactions between insert seams. Evidence:
`joint-closure-6hb-context-2026-11-23.json` (source was still v1; counts are explicit
component alternatives, not a changed Design).

`experiments/corner_seam_context.py` now builds an isolated **same-topology**
candidate from the actual native v2 source. It preserves atom count/order,
identity, bonds, sequences and recorded insert counts, and optimizes each seam
against all other current atoms in two passes. No output enters normal display,
export or simulation. `corner_tool_audit.py --close` invokes it and now also
reports all junction flexible covalent edges, not just O3′–P between residues.
The whole-model run completed on both bundles:
- HC:39,780 atoms,760 displaced;47 seam covalent edges; worst candidate seam
  and flexible junction bond0.191827nm; **0 piercings,0 heavy-atom clashes**.
- SQ:52,900 atoms,1,020 displaced;63 seam edges; worst candidate seam/flexible
  bond0.191994nm; **0 piercings,0 clashes**.
Source atoms/identity/order/bonds and Design bytes were preserved. Evidence is
`whole-closure-v2-comparison-2026-11-23.json`. Production placement unchanged.
The full **53-case phase sweep is complete**: all21HC+32SQ native2HB
station classes independently replayed. Candidate results are0nonfinite atoms,
0heavy-atom clashes and0ring piercings across all53; worst flexible junction
bond0.192629nm. Current native placement has nonfinite atoms in16cases; their
geometry checks explicitly remain incomplete. Evidence:
`whole-closure-v2-phase-sweep-2026-11-23.json` (`complete:true`). These are
90°/15° cases, not arbitrary-angle or arbitrary-source coverage.

`experiments/corner_placement_review.py` prepared four same-topology A/B cases:
6HB,flat1×8SQ,2HBHC84bp,and2HBSQ85bp. Each source was JSON-reopened and
independently replayed. The read-only gzip bundle contains actual native
commands, readable F1Extrude/F2MakeCluster/F3Corner construction, an explicitly
separate diagnostic evaluation program, exact atom/bond/defect data, all
junction deltas, and the53phase summary. Candidate coordinates are not put into
an authored Design, atomistic reference, export or simulation.

`experiments/corner_review_projection.py` provides a diagnostic-only Full-style
projection of the actual atom models (O5′ beads, base centroids/slab axes and
actual O3′–P connectivity). Its coordinate/rigid-axis checks passed in the
candidate test. `corner_review_full_layer.js` and `corner_placement_review.js`
render these privately, with shared cameras and seam focus. The shared viewer
only selects this projection for its explicit diagnostic schema. Four cases
are registered in Help→geometry Review (`?geometryReview=corner`). Nine focused
frontend checks passed, including the unchanged Gold review. The four-case app check passed; see the current continuation above for the
subsequent threshold-label rerun and the pending explicit molecular approval.

## Current continuation: native tip cuts and complete Full bond coverage

Native Corner preflight now trims integer duplex endpoints using the actual
rigid sugar/base van der Waals support on each side of the miter. Flexible
O3′/P/OP1/OP2/O5′ atoms are excluded from that rigid envelope. This changes the
new Corner's recorded topology, not production molecular placement. Batch
support matches independently built native atoms, including ATGC sequence,
loop copies, skips, twist, pose, and XZ frames. Cuts retreat past ambiguous
multi-copy/deleted seam stations. No phase or placement constants changed.

Both the cylinder guide and rigid support now restrict their domain to authored
occupied station spans. Ghost extensions of previously cut axes cannot create
extra plane crossings or reject another Corner. A pure curved-prefix regression
and native repeated-Corner replay cover this. Cancellation is checked before
preflight and between tip-support helices; oversized indexed paths fail before
the atom-template work. Focused verification: **36 passed** (plan, preflight,
command, Sweep XY/XZ/YZ, tip support).

Shared bond review now measures native Full insert coordinates, retaining the
recorded half order, strand-walker index and saved residue poses. Both Corner
fixtures have complete Full backbone coverage with no long seam edges; the
intentional forced-junction >20% review trigger is retained. Photoproduct
inserts explicitly remain unmeasured by this adapter. **21 tests passed** across
insert position/order/pose, legacy bond review and native Corner preview. This
is not an atomistic bond-closure certificate.

Post-trimming isolated final-frame molecular comparison:
- 6HB: 39,400 atoms; 380 displaced candidate atoms; worst seam bond 4.8647→0.6805nm;
  ring piercings 8→5; candidate heavy-atom clashes 8.
- 1×8SQ: 52,420 atoms; 545 displaced; worst seam bond 12.7790→0.6608nm;
  ring piercings 15→6; candidate clashes 12.
Evidence is `.development-artifacts/corner-tool-audit/trimmed-final-frame-comparison-2026-11-23.json`.
The previous untrimmed results below are historical, not the current topology.

Count exploration 1–8 shows that post-closure native terminal gamma rotation
can stretch a previously closed bond. Native two-base rigid poses also occur
after initial bridge interpolation. Re-closing flexible bridges after all poses
does not solve all local defects; it additionally changes terminal gamma and
is NOT promoted. `seam-reclosure-comparison-2026-11-23.json` records before/after
gamma and final reclosure, all flexible covalent lengths, exact local clashes
and piercings. These are copied component alternatives, not authored parts;
source recipes and original Design bytes remain intact.

`experiments/corner_seam_closure.py` is a new isolated joint rigid-insert /
flexible-phosphate optimizer with analytical gradients. It preserves rigid
duplex atoms and insert ring shape; terminal gamma is explicitly not fixed.
It can screen a fixed native duplex atom environment; other seams and exact
external ring piercings still need a complete-model check. It is not imported
by production. Its analytical gradient (including environmental repulsion),
rigid insert distances, fixed duplex atoms and source immutability test passed.
An initial 2HB HC local-only run found clean candidates with ≤0.20nm flexible
covalent bonds for all four seams (minimum counts 1,3,1,2); recorded counts were
1,2,1,1. Thus correcting placement alone is insufficient for two of those seams.
Many fits hit the 400-iteration bound despite passing local distance/contact
checks; no convergence or global-validity claim is made. Evidence:
`joint-closure-2hb-hc-2026-11-23.json`. A 6HB 1–8-base run with the native duplex
environment is currently running. No geometry approval requested.

Latest browser verification after native tip trimming and occupancy clipping:
6HB passed creation, native pick→Drill, Full, edit, undo/redo, **delete and revert**.
Input→ready 1.983s, paint2.336s, final-read→ready38ms. Square passed creation,
Full, Apply and undo/redo but initially left Apply disabled during history edit
(30s assertion timeout). A focused square rerun passed the full flow including
history edit: ready2.103s, paint2.507s, final-read→ready48ms. The intermittent
failure remains unexplained; the assertion now includes popup status to diagnose
any recurrence. Both latest preview screenshots were visually inspected before
cleanup. Teardown removed all test parts/project stores; workspace/report/5175
credential inventories were empty after both runs. No test browser remains.

## Latest completed checks and next molecular work

Both untraced browser cases **passed**: native File→New, cluster pick→Drill,
6HB/1×8 SQ Full preview, visible cutting plane, Apply, undo/redo, and native
history edit retaining feature identity/count. Total3.8min. Both screenshots
were inspected at a diagonal camera showing the actual corner; all prefixed
workspace artifacts/project stores, report dirs and5175bridge artifacts were
verified absent after teardown. The subsequent progress-coalescing change also
passed `tests/test_corner_preview_stream.py` (actual streamed guide/progress/Full,
source immutability, cancellation/released worker slots). No browser process
remains active. Coalescing still needs new in-app latency evidence. No structure
has been published or delivered; the goal is still active and incomplete.

The isolated final-frame comparison ran successfully, preserving original
Design bytes, atom count/identity/order and complete bond connectivity. Evidence:
`.development-artifacts/corner-tool-audit/final-frame-comparison-2026-11-23.json`.
It includes the actual ordered recorded commands, independent replay result,
and the explicit diagnostic evaluation program. Production placement unchanged.

- 6HB:300atoms move; worst insert-associated covalent bond3.9056→0.5314nm;
  ringpiercings14→13; heavy-atom clashes50→48.
- 1×8SQ:400atoms move; worst seam bond11.9601→0.5433nm;
  ringpiercings20→21; clashes45→63.
- Only inserted atoms and the ordinary endpoint O3′/P/OP1/OP2/O5′ atoms move;
  duplex rigid rings/bases remain unchanged. This comparison is **NOT acceptable
  for promotion** and no approval has been requested.
- Remaining piercings include ordinary glycosidic/base bonds into nearby rigid
  rings (e.g. native report A89→A92 inHC, B105→B108 inSQ). This implicates the
  untrimmed duplex tips meeting at centerline-only miter cuts, in addition to the
  demonstrated source-frame insert-registration bug. Do not infer a fix from
  aggregate counts; inspect exact atoms/rings in A/B evidence.
- Candidate seam O3′–P bonds still0.53nm: the current shortest-insert selection
  using only Full maximum backbone spacing≤1.2nm is insufficient. A physically
  constrained local endpoint/insert-length search is needed before approval.

Potential next implementation (analysis only, NOT implemented): derive endpoint
cutbacks from actual native rigid-residue support relative to the miter plane,
so the two retained duplex wedges do not overlap, then evaluate short ssDNA
counts against native chemical seam closure and ring/clash diagnostics. Prefer
actual canonical atom support over guessed radius/phase constants. Changes to
new Corner topology must remain within the real recorded/replayed command;
any molecular placement correction stays isolated pending required A/B review
and explicit authorization. The final-frame candidate alone is inadequate.

Shared Full bond review is also incomplete for inserts: `_position_lookup` in
`backend/core/design_bond_review.py` only consumes regular `_geometry_for_design`
records, so all24HC/32SQ seam-chain edges lack positions. Its topology counts
correctly classify all12HC/16SQ forced seam records and preserve the review
trigger. Native Full insert positions already exist in the authoritative
`crossover_extra_base_full_projections` used by Corner projection/renderer;
a future read-only report adapter can measure them without altering placement.
Do not waive the incomplete report, silently invent positions, or bypass the
publication guard. No shared bond-report code has been changed this turn.

## Latest continuation: transported planes and molecular defect found

Corner's guide now derives its material frame directly from nominal canonical
sites and their actual deformed/posed counterparts. This applies all owner
poses and constructs a right-handed frame for XZ as well as XY/YZ. Native
indexed paths can already transport these rotation operators over their stored
station range; no shared Sweep or molecular placement code changed. The
XY-only Corner restriction was removed. Focused command/preflight/Sweep checks:
**13 passed**, including independent replay and every Full nucleotide/base site
for recorded Sweeps in all three construction planes. Existing loop/skip copies
are preserved. Indexed-path extrapolation outside the stored station range is
not covered (shared Sweep helper's returned tangent still assumes Z, but the
Corner's stored range contains every source station).

The transparent cutting plane and outline now remain visible in guide and Full
previews. A second, diagonal camera view was inspected for both 6HB and 1×8 SQ;
it visibly shows the two joined wedges and the cutting plane. The earlier
traced app rerun passed 6HB and timed out after 180 s during square history edit,
after square creation/undo/redo passed. Both test parts/project stores and all
reports/bridge credentials were verified cleaned. The next run disables
continuous trace screenshots (assertions/failure screenshots remain) and is
still active; collect its result. Its 6HB passed in 1.4 min, input→ready2584ms,
paint3114ms, last-read→ready46ms; square preview3155ms/paint3797ms,
last-read→ready89ms. Native scene construction is thus a small part of latency.
`corner_preview_stream.py` now coalesces actual progress to at most20Hz while
always emitting stage changes and100%; this change is not in that active server
and still needs focused stream verification and new latency evidence.

**Molecular acceptance failed.** Read-only `experiments/corner_tool_audit.py`
built real recorded 6HB and flat SQ Corners, independently replayed them, and
built their actual native atomistic models. Evidence:
`.development-artifacts/corner-tool-audit/2026-11-23.json` (not a structure).
6HB40560atoms: max insert-associated covalent bond3.9056nm,14ringpiercings
(7withinsertidentities). SQ54080atoms: max11.9601nm,20piercings(4withinserts).
Shared Full bond review reports forced-seam fractions requiring review and
incomplete geometry; preview's own explicit inserted-bead screen was not enough.
Do not publish or call molecular geometry complete. Normal atomistic builder
still constructs inserts in undeformed coordinates and subsequently transforms
them using only their source helix, leaving the opposite wedge misregistered.
No production molecular placement or phase constants have been changed.

`experiments/corner_seam_candidate.py` is a new **unrun**, isolated diagnostic
provider `corner-final-frame-seams-diagnostic-v1`: build the same native duplex
atoms with inserts/gamma deferred in a standalone process, transport duplex
atoms, then call the existing native insert/bridge builder at final endpoints,
apply existing gamma/clearance, and thread sequences. It produces only a derived
AtomisticModel for comparison, no changed Design/export seed. The original
recorded commands and ordered candidate evaluation program are retained in the
comparison report, not fabricated feature rows. `corner_tool_audit --compare`
now checks topology/atom identity and source immutability and records per-atom
displacement, shared clashes, piercing identities and covalent distances. Run
it after the active browser workflow ends. It is NOT approved for production;
full A/B visual evidence, representative2HB/phase sweep and explicit molecular
placement authorization remain required before promotion. Preparing that
comparison is authorized; no permission question has been sent yet.

## Active-goal continuation: history editing, pose retention and Sweep support

Native Corner history editing now uses a source/revision/feature-bound PATCH
route and a detached full-recipe preview. `corner_history.py` independently
proves the original recipe, binds the selected Corner prefix, rebuilds the edit
and its later suffix, and projects the resulting native Full geometry. It
preserves stable feature/operation IDs; a later Corner remains intact. The
feature-log panel now exposes the shared Corner popup for edits, including an
earlier Corner with later features and evicted recovery data. Popup commit
controls are disabled while applying, and document-reset cleanup is forced.
Native labels show Corner and updated parameters while preserving custom names.
Main.js Corner LOC delta is **+3** (import, factory, history-edit callback).

The real 6HB app flow passed creation, undo/redo and editing the history row with
the same feature ID/count. Its browser-local input-to-ready was 2688 ms and
double-animation-frame paint was 3296 ms; Playwright action timing was 7159 ms.
The latter includes dispatch overhead and is not computation time. Cleanup was
verified. Performance remains above the requested 1–2 s and incomplete.

A new regression caught a placement bug: resetting the owner cluster pose moved
shorter uncut members. Corner now retains that cluster's pose and converts only
the derived cut paths from world coordinates into its local frame. Other
members/children retain their existing transforms. Whole-cut members relinquish
other placement memberships as before. Every cut and uncut Full site agrees
with its intended rigid transform, and independent replay passes.

Genuine native Sweep sources now retain loop/skip marks and all per-copy
geometry. Material frames are sampled at nominal stations on a temporary helix
component without marks; the saved authored helices still carry the original
marks. Miter endpoints retreat into their wedge past non-ordinary stations so
seam endpoint identities are unambiguous. The native recorded Sweep → Corner
integration compares every Full nucleotide/base position and independently
replays. Its initial missing-root failure came from the test's legacy scratch
initializer; the test now starts with the public Create Design command. No
production history gate was weakened. Non-XY construction remains unsupported:
XZ source frame admission failed orthonormality; indexed Sweep tangent currently
assumes a Z construction frame. This still needs a justified implementation.

Latest focused backend run: **15 passed** (command, history, preflight, preview,
stream and genuine Sweep integration); frontend follow-up: **12 passed** (tool,
history, labels, transport). Ruff and diff whitespace checks pass for the changed
Corner files. Preview no longer calculates/sends an unused source projection;
its work total is seam candidates + recording + final projection. Cylinder
segments now use two InstancedMeshes instead of one draw call per segment.
A serial app rerun for 6HB and flat 1×8 SQ is in progress; do not claim its final
result until the active process is collected. The current 6HB retest measured
2541 ms ready / 3116 ms paint. Screenshot was visually inspected in Playwright's
output before its cleanup; the chosen camera foreshortens the outgoing arm.

`experiments/corner_tool_audit.py` is a new read-only native-command molecular
audit (not yet run): independent process, shared Full bond report, actual
atomistic seam covalent distances and ring-piercing report for both sections.
It writes only diagnostic JSON under .development-artifacts, no structure or
geometry overrides. Atomistic placement still needs investigation before any
acceptance/publication; existing extra-base atoms follow the source helix's
frame, which may disagree with final-endpoint Full inserts across a Corner.

## Active-goal continuation: menu and live preview now wired

Corner now appears immediately below Twist/Bend. `ui/corner_tool.js` owns
one-shot cluster picking (shared selection helper restores Drill/default),
debounced source-bound preview requests, stale-response rejection, cooperative
cancellation, Apply, and document-change teardown. Main.js adds only one import
and one factory call: **LOC +2**. Fields/buttons use `corner_popup.js` and the
shared Bend/Twist styles.

`POST /api/design/corner/preview` captures a source/revision-bound copy and
streams NDJSON: cylinder guide, measured work progress with estimated remaining
time, then native Full candidate. `corner_preview_stream.py` bounds active
workers (2) and queued events (8), closes workers on disconnect, and never
installs the candidate. `api/corner.js` consumes split stream records and uses
the normal source-bound authoring response for Apply. `scene/corner_preview.js`
uses the real native Full renderer and native crossover/forced-ligation insert
renderer; private meshes/palette are disposed on replacement. Inserted seams
exclude duplicate endpoint-to-endpoint connection lines by endpoint identity.
The initial cylinder guide currently overlays the unchanged live scene; a
plane mesh/isolated selected-cylinder presentation still needs visual review.

Validation this continuation: 11 focused frontend tests pass (parameters,
popup, launcher stale/cancel/commit behavior and NDJSON transport). The backend
stream integration passes, including actual guide→progress→Full data,
disconnect worker-release, source immutability and stale revision rejection.
The real `e2e/corner.spec.js` passes: File→New native recorded 6HB, real bead
raycast cluster selection, Drill restoration, field update, complete Full
preview, Apply, Corner feature, scaffold/staple seam counts, undo/redo and zero
console errors. Its first attempt failed because API-only setup left the welcome
menu locked; the spec now uses File→New. Both successful runs and the failure
had verified teardown (no remaining prefixed parts/project stores, test reports
or isolated browser bridge credentials).

**Performance remains incomplete:** the real 6HB parameter-edit→Full-ready
measurement was **5895 ms**, above the requested 1–2 s. Backend-only checks are
subsecond; profile transport, native mesh construction and browser frame cost
before claiming interactive speed. Flat 1×8 SQ app exercise also remains.
Feature history has native backend edit/delete/replay, but the feature-log UI
does NOT yet expose Corner editing: `feature_log_panel.js`'s snapshot whitelist
omits it. Implement a source-bound history preview/edit adapter instead of
applying a second Corner to an already-cornered source. Assembly-host behavior,
broader routed-source support, complete molecular review and saved/reopened
guarded publication remain outstanding.

Required `just smoke`: 25 passed, 2 skipped, 2 timeouts (assembly setup and New
Part dialog Cancel). Focused one-worker rerun passed Cancel; assembly setup
again timed out at `scene_harness.js:434` in `assemblyInstanceCandidates`, before
the exit action. A disposable response-interception baseline removed only the
two Corner bootstrap lines from served main.js and reproduced the identical
60-second assembly setup timeout. No source file was changed for that baseline;
its diagnostic spec was removed afterward. This isolates the unresolved smoke
timeout from Corner bootstrap but does not turn smoke green. All browser runs
had verified artifact teardown. Corner-related backend Ruff check passes after
removing one unused import. Do not repeat the broad smoke suite without new
changes/evidence; investigate the specific assembly setup failure if relevant.

## Active-goal continuation: native command and isolated Full evaluation

`routes_corner.py` now exposes the real source/revision-bound POST
`/api/design/corner` transaction. `part_corner_commands.py` owns strict versioned
inputs/dependencies; `corner_build.py` derives paths, topology and inserts with
stable output IDs. Corner is registered in SnapshotOpKind and native proof
dispatch. `part_edit_identity.py` preserves its operation ID/version on edits.
The native recorder and proof executor preserve Corner's explicit placement
membership instead of generic cluster inheritance, which otherwise discarded
the outgoing wedge and could restore superseded poses. Corner guide selection
now scopes to occupied material at the requested station for successive corners.

Four integration tests in `tests/test_corner_command.py` pass: 6HB and 1×8 SQ
geometry and independent replay, undo/redo/stale revision; edit/delete on a
bent+twisted source; two successive corners in different local directions.
No structure has been published. Saved/reopened publication audit, physical
junction review, genuine Sweep-source integration, and rigid-pose command
integration still need verification.

`corner_preview.py` evaluates through the **real feature recorder** on a detached
session under a copied ContextVar context. It preserves the source history and
adds a native Corner entry without installing the candidate or leaking request
revision/entry stamps. Progress counts source projection, tested seam lengths,
recording and final projection; ETA is an elapsed-work estimate, not a promise.
`corner_preview_projection.py` uses ordinary native Full geometry and explicitly
includes every inserted seam's sequence, bead positions and backbone distances.
The older deformation comparison DTO rejects inserted bases; do not weaken it
or omit inserts to reuse its renderer. The new Corner display adapter must use
`buildHelixObjects` plus `buildCrossoverConnections` (which handles native forced
ligation inserts) and native connection lines. The frontend adapter, streamed
preview route, cancellation lifecycle and menu/launcher wiring were added above.
Two preview integration tests pass for both cross sections, including independent
candidate replay, inserted-site inventory, unchanged live state/revision and
cooperative cancellation. Each full test including replay takes ~0.5 seconds;
this is not yet an in-app preview latency measurement.

Current build still selects the shortest existing native insert with maximum
Full backbone separation ≤1.2 nm. This is a distance screen, **not** steric,
ring-piercing or atomistic acceptance. Ordinary crossings are preserved, and
within-wedge rerouting unsupported by current planner is explicitly rejected.
Remaining limitations include organized parts, selected attachments/other
references, loop/skips, non-XY construction, independent residue poses, and
the indexed path station bound. These remain development work, not accepted
reductions of the user's requested scope. Main.js LOC delta remains 0.
Latest focused `test-smart` run: 75 passed across Corner command/preview,
feature-recording transactions and protected edit identities. No app exercise
or new saved part has been produced in this continuation.

## Active-goal continuation: native seam components

Latest continuation added `backend/core/corner_wedge_paths.py`:
`corner_bundle_paths` derives **two shared indexed Sweep paths**, one per wedge,
from the source's actual transported canonical sites. It does not create a
Design. `corner_wedge_paths` is its per-helix frame extraction helper. The paths
retain existing bends/twists, current rigid poses and raw lattice phase; the
outgoing path alone receives the requested corner rotation. Shared station
frames/spines are checked across helices, rejecting incompatible independently
posed cross sections rather than silently fitting them. Indexed path positions
are world-space, so the owning Corner executor must replace superseded
deformation scope and rebase selected cluster poses without changing outsiders.

`tests/test_corner_wedge_paths.py`: 4 parameterized integration tests pass via
`just test-smart`, checking every helix in an 8-helix source for straight, bent,
twisted and combined source operations plus a recorded rigid pose. Independent
native Full projection agrees before rotation and with the exact rigidly rotated
source after rotation to 1e-10 nm; input source remains unchanged. No candidate
Design, native Corner command, or UI integration was introduced in this step.
Current extraction limits: XY construction axes, 2–2048 ordinary stations, no
loop/skips or independently posed residues. These are explicit incomplete areas,
not a new definition of the final tool's scope. Add a genuine recorded Sweep
source test too; mathematical/native-path compatibility alone is not that test.

The next concrete implementation is a `corner` snapshot command using these
paths, `materialize_corner_topology`, existing seam candidate evaluation, and
deterministic operation/output IDs. Register it in SnapshotOpKind and native
proof dispatch/dependencies; expose/record it through a real Corner route before
generating candidate Designs. Preserve ordinary crossover identity via the
endpoint map and preserve all unrelated references/state. Then inspect Full
and atomistic seam placement: existing `_build_extra_base_atoms` constructs
inserts before `apply_deformations_to_atoms`, which uses the source helix frame
for extra-base atoms. Do not assume its resulting corner insert coordinates
equal the already-tested final-endpoint candidate placements. Any repair to
production placement needs the existing isolated A/B review gate.

The thread now has an active goal to finish the entire tool. Keep it active until
all UI, topology, geometry, history, replay and app requirements pass; a helper
or focused test pass is not completion.

Component foundation (now used by the registered command above; UI still unwired):
- `backend/core/corner_topology.py` materializes a route plan into native Strand
  and ForcedLigation components, not a Design. Both scaffold and staple seam
  directions come from actual 5′→3′ traversal. It preserves retained sequences,
  metadata/custom-scaffold source length, stable output identities and endpoint/
  domain remapping receipts. Bridge sequences must be supplied explicitly.
  A changed within-wedge connection is refused rather than converted from an
  ordinary crossover to a forced ligation.
- Current repository feedback now explicitly permits intentional corner seams
  represented as forced ligations (D003 clarification in
  `feedback_structure_requires_process.md` and `docs/design_bond_review.md`).
  Use that existing native representation; do not invent a duplicate junction
  collection. This is not a blanket geometry approval or review exemption.
- `backend/core/corner_junction_geometry.py` transports canonical sites through
  a proper rigid rotation and projects endpoints through the existing native
  Full authority. It evaluates explicit insert sequences using the existing
  `crossover_extra_base_full_projections`, unchanged. Results include every
  native insert position and consecutive backbone distance, **not an acceptance
  verdict**. Phase/clash/piercing validation and final bridge selection remain.
- `backend/api/corner_junction_evaluation.py` joins preflight with the shared
  `native_full_arrays_for_helix` authority (including its correct phase roll),
  applies saved nucleotide poses to endpoints, rotates only outgoing endpoints,
  and enumerates 1–8 inserted-base candidates per seam. Actual completed/total
  callbacks and cooperative cancellation are tested. No Design is changed.
- Zero-angle preflight now returns an identity route, with no duplicated duplex
  bases or artificial junctions.

Verification this continuation: topology/routing tests 14 passed; native geometry
and updated preflight tests 13 passed, through `just test-smart` with explicit
new-source coverage rationale. The recorded-source 6HB test evaluates 12 seams ×
8 candidates in ~0.10 s including source creation, but this is **not** a complete
Full-preview performance benchmark. No browser flow or Corner publication yet.
`main.js` LOC delta remains zero.

Next required work: validated phase/steric bridge choice; native topology-changing
Corner executor that transports the complete wedge geometry while remapping
existing connections/references; real feature recording and independent replay;
source-bound preview/apply lifecycle; menu/selection/scene integration and app
verification. Existing routes still reject a nick exactly at the split and
changed within-wedge connections: these need the requested local routing solver,
not a forced-ligation bypass. Existing atomistic insert construction happens
before generic deformation application; verify final insert placement agrees
with candidate endpoints rather than assuming that a suffix residue pose moves
its connected insert atoms correctly.

## Agreed behavior and earlier work

The user confirmed: angle is the axis deflection (0° straight, 90° right angle);
direction rotates around the local axis. Preserve routing outside the junction,
reroute both scaffold and staples locally, and allow local nucleotide counts to
change. Position controls step 8 bp for square and 7 bp for honeycomb, with linked
nm fields; angle and direction step 15°. Required: a Tools menu entry below
Twist/Bend, shared popup styling, cluster picking then Drill, immediate cylinder
guide followed by calculated Full preview with actual progress, and a native
Corner feature supporting the complete history lifecycle. Reference designs:
NanoBase 270, 242 (MagicDNA Hilbert), and Chau 274/275/277/278. Wireframes,
including the 2011 hinged tetrahedron, are explicitly excluded.

The user explicitly approved introducing short **unpaired scaffold and staple
segments** where needed at the junction. This is resolved; do not ask again.
These must be authored nucleotides in the strand paths, not display-only
FlexibleSegmentMark annotations or terminal-extension substitutes.

`backend/core/corner_plan.py` now implements the read-only cylinder-guide miter
calculation. It accepts explicit current world-space axis paths/bp stations and
a right-handed material frame, computes the bisector plane, intersects both
wedge faces, and rotates the outgoing path suffix. It retains sampled bends and
sweeps, follows the supplied twisted frame, and rejects absent/multiple/tangent
intersections and insufficient arm material rather than clipping. It does not
create any Design, edit topology, calculate molecular bridges, or record a
feature. No API/UI adapter is wired to it yet. `just test-focused
tests/test_corner_plan.py`: 19 passed (analytic straight-miter, posed-frame,
curved-path, direction, bounds and invalid-intersection oracles).

Further read-only implementation:
- `backend/api/corner_guide.py` adapts current native axis samples and the
  transported material frame to the miter planner.
- `backend/core/corner_routing.py` plans both strand types in actual 5′→3′
  traversal, retaining unchanged external domain transitions and explicitly
  listing every changed connection. It rejects duplicate occupancy, overhang
  reinterpretation, and a nick/crossover/unpaired region exactly at the split
  (endpoint matching is not yet implemented). It returns plans, never Designs.
- `backend/api/part_corner_commands.py` currently contains only typed inputs
  and read-only preflight, **not a registered/native authoring command**.
  It quantizes duplex cut endpoints but does not resolve phase or build bridges.
- Focused checks: `tests/test_corner_routing.py` (7 passed),
  `tests/test_corner_preflight.py` (3 passed). Preflight tests use recorded
  Extrude / Make Cluster / Twist operations on 6HB and 1×8 SQ sources. They
  verify both strand types, unchanged source state, and the twisted local frame.

No topology-changing builder, molecular junction evaluator, native Corner
record/replay registration, API endpoint, menu wiring, or complete app workflow
has been added. Do not describe these plans as routed molecular structures.
The standard extra-base atomistic path and saved residue transforms cannot be
assumed to regenerate bridges from final rotated endpoints; inspect/validate
that ordering before using them. Do not substitute a sharp deformation, pasted
geometry, or ordinary-crossover-to-forced-ligation conversion to finish the tool.

The independent parameter and popup components also exist:
`frontend/src/ui/corner_parameters.js` and `corner_popup.js`. They reuse
`createToolPopup` and shared Bend/Twist styles. They are **not menu-wired** and
have no molecular evaluator, selection controller, live geometry, authoring
command, or feature-history integration. Progress accepts real caller-supplied
percentages; it does not simulate calculation progress. Apply starts disabled.
39 focused Corner/Bend/Twist tests pass. A disposable Chromium component harness
verified HC ArrowUp, linked parameters, Cancel, and disposal; the actual Corner
workflow has not been exercised in NADOC because it is not yet implemented.
`main.js` LOC delta is zero.

The old builder below is not the requested operation: it creates new square
sheets at 90° and joins only scaffold seams with forced ligations. Do not wire it
to Corner or claim it provides local rerouting on existing deformed clusters.
No Corner structure has been generated or published in this work. The remaining
native routed junction path must be implemented and independently replayed before
publication; otherwise report `AGENT_PROCESS_REQUIRED`.

# Historical headless mitred-corner primitive (July 8, 2026)

`backend/api/headless_corner_build.py` — a design-automation primitive
(`/automate-feature` family) that builds a 90° corner from two planar SQUARE
sheets, folded at a mitred seam, entirely headless. Mirrors
`headless_hinge_build.py`; composes existing `headless_build` wrappers only (NO new
route, god-file LOC Δ = 0).

## Entry point
`build_corner(*, n_helices=6, base_length_bp=56, lattice=SQUARE, target_angle_deg=90,
optimize=True, window_bp=2, col_offset=None) -> Design` (returns a standalone copy).

Recipe (the clean version of what the reference `.nadoc` was hand-built as):
`create_bundle` two 1×N sheets (A cols 0..N-1, B cols offset..offset+N-1; each sheet =
its own cluster) → `resize_strand_end` trims each helix's FAR end into a ~45° staircase
miter (BOTH scaffold + staple by the same negative delta; far end = 3p if helix FORWARD
else 5p) → `transform_cluster(log=True)` folds sheet B 180° about the miter diagonal →
`force_ligate` the N cross-seam scaffold links. Result carries a full replayable feature
log (bundle-create → resize → **cluster_op** → forced-ligation).

`col_offset` MUST be ODD (each B helix gets OPPOSITE scaffold parity to its A mate — SQ
parity `(row+col)%2==0`→FORWARD — giving one free 3′ + one free 5′ per seam so every
forced ligation is legal). Default `_default_col_offset` = smallest odd ≥ n+3 (n=6 → 9,
matching the reference cols 0–5 ↔ 9–14).

## The two-constraint principle (the core)
A mitred helix length must satisfy TWO constraints; naive uniform stagger honours only #1:
1. **AXIAL (miter):** far end lands on the 45° plane. Ideal stagger = spacing/rise =
   2.25/0.334 ≈ **6.74 bp/helix** — non-integer, so integer stepping is never exact.
   `_ideal_lengths` = `base − round(i·6.74)`.
2. **ROTATIONAL (phase):** a forced ligation bonds the 3′ bead of one helix to the 5′ bead
   of its partner, each ~1 nm off-axis at azimuth `phase_offset + bp·33.75°`. ±1 bp swings
   the terminal bead 33.75° — from pointing away (bond ~1.3 nm, overstretched) to facing
   its partner (~0.3–0.5 nm). A_i and B_i must FACE each other → joint per-seam-pair search.

**Two optimizer stages (both default-on):**

**Stage 1 — LENGTHS (`optimize=True`):** per seam, search integer `(len_Ai, len_Bi)` in
`ideal ± window_bp` and pick the pair minimising the posed FL backbone stretch —
**user-chosen lexicographic objective (2026-07-08): min total stretch, tiebreak smaller
axial residual; ±2bp window is the hard axial bound.** Result (n=6): total posed FL
stretch **1.87 nm** (max 0.69) vs uniform baseline **5.51 nm** vs reference **3.43 nm**.

**Stage 2 — FOLD POSE (`optimize_fold=True`, user request 2026-07-08):** the clash lever.
Stage 1's tight tooth-mating PACKS the cross-sheet backbones, so the residual clashes are a
property of the FOLD, not the lengths (a pure translation trades clashes 1:1 for bond length
— it just slides the tradeoff). A small extra ROTATION of sheet B (a few °) about the fold
pivot + a small shift swings B's bulk off A while the seam beads stay mated → genuinely
lowers clashes. Co-optimizer = **stage A lengths → stage B fold (grid search min
`clash + 4·Σbond` s.t. every bond < `max_stretch_nm`=1.0 and angle within `angle_tol_deg`=5)
→ stage C re-optimize lengths under the tweaked fold.** Result (n=6): **genuine clashes
24→11, FL total 2.82 nm (max 0.72), angle 93°** — beats the hand-tuned reference on BOTH
axes (11 clashes / 3.43 nm / 0.94 max). `optimize_fold=False` keeps the tight-bonds-only
1.87 nm / 24-clash result.

The fold perturbation `(Rextra, off)` folds into ONE `transform_cluster` pose via
`_compose_fold` (rotation `Rextra·R0`, same pivot, translation `tr0+off`) — still a single
logged `cluster_op`. Fast (~5.5 s): the grid is analytic (path-B) AND pre-filters to B beads
within reach of A (only cross-sheet A–B pairs can clash under a rigid B pose; an A-bead
KD-tree is built once, transformed near-B beads queried against it, straight-close pairs
pre-excluded). `build_corner` args: `optimize`, `optimize_fold`, `window_bp`,
`max_stretch_nm`, `angle_tol_deg`.

## Optimizer is path-B FAST (do NOT rebuild per candidate)
Straight backbone beads are **trim-invariant** — a bead at bp k does NOT move when the
helix is trimmed past k (verified, max move 0). So build the straight sheets ONCE
(`create_len = base + window` to cover the window), then per coordinate-descent pass
capture the fold transform from ONE real build and search all candidate lengths
ANALYTICALLY: `R@(bead − pivot) + pivot + trans` on the recorded straight beads reproduces
the geometry kernel's posed positions EXACTLY (diff 0). Re-fix the fold each pass →
converges in ~2 passes / ~5 builds / **1.3 s** (vs 451 builds / 59 s naive per-candidate).

## Validated with the clash detector (`backend/core/clash.py`)
Oracle `tests/automation_harness.py::assert_corner_folded` (7 clauses, all 3 layers): corner
angle ~90° (posed mean axes via `deformed_helix_axes`); N forced ligations; every posed FL
stretch < 1 nm; total ≤ uniform baseline (optimizer helped); genuine steric clashes ≤
baseline; a `cluster_op` log entry for the folded cluster; round-trip stable + all FL
records persist. Tests `tests/test_headless_corner_build.py` (13).

**KEY calibration insight (banked):** a GOOD forced ligation (~0.3 nm) is itself a sub-0.65
nm "clash" to `clash_report` — FL partners are ~20 nm apart STRAIGHT, so the detector's
straight-vs-posed exclusion does NOT drop them. Raw `clash_report.count` is therefore
ANTI-correlated with ligation quality. The corner metric MUST exclude the seam FL bonds:
`steric_clash_count(design)` = `clash_report` count minus the FL-partner pairs. This is what
the task's "ideally 0 after seam design" means. (Optimized has 1 MORE raw clash than uniform
but FEWER genuine ones: 24 vs 26.)

## Reproduction / calibration notes
- The reference `tests/fixtures/corner_miter_test.nadoc` (= `workspace/corner_miter_test.nadoc`)
  is the human-tuned target the clash detector was calibrated against (15 raw / 11 genuine
  clashes, 3.43 nm bonds). Its FOLD was hand-tuned in the gizmo (pivot z 12.58 vs the
  deterministic far-end-centroid 12.02). The DETERMINISTIC base fold (lengths-only) packs
  tighter (24 genuine clashes) BUT reproduces the task's stated uniform baseline 5.31 nm
  exactly. The **stage-2 fold optimizer** recovers a better fold pose programmatically →
  11 genuine clashes at 2.82 nm bonds, beating the hand-tuned reference on BOTH axes without
  any manual gizmo work.
- The reference feature-log is messy trial-and-error; the clean recipe is create→trim→fold→
  ligate. `create_bundle(ligate_adjacent=True)` does NOT merge adjacent scaffolds (24 strands);
  the 6 seam ligations merge them (→18).
- Seam ligation: the FORWARD helix's scaffold 3′ → the REVERSE helix's scaffold 5′, both at
  their trimmed far bp (= len−1).
- `target_angle_deg` only 90 supported (the 2.25/0.334 stagger geometry); a general angle would
  need a different miter stagger + fold rotation.

Related: [[project_clash_detector]] (the metric), [[project_headless_build]] (the wrappers it
composes: create_bundle / resize_strand_end / transform_cluster / force_ligate),
[[project_hinge_autoscaffold]], [[REFERENCE_SQUARE_LATTICE]].
