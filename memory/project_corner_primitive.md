---
name: project_corner_primitive
description: Native Corner and Bevel tools, replayable routing/truncation, approved Corner seam geometry, Full preview, validation and limits.
metadata: 
  node_type: memory
  type: project
  originSessionId: 2716c75a-b4c8-4c6c-9b45-def883afa1b3
---

# Corner tool — November 23, 2026

## Cold opening investigation — November 27, 2026

Opening `corner_test.nadoc` spends its time generating both posed and straight
Corner projections, not parsing the file. Exact compiled closure arithmetic,
expanding local environment/candidate lists, batched finite-difference seed
evaluations and indexed seam components reduce unprofiled combined generation
from 43.94 s to 20.6–22.3 s serially on the measured source. Bounded two-process
posed/straight projection in the file-load route lowers fresh-process generation
to 13.40 s (14.23 s including imports/setup), with vectorized clash cell indexing.
Warm requests spawn no workers; worker transport limits fall back to local
geometry. The follow-up worker/clash/approved-atom selection passes 12 tests.
The subsequent compiled atom-stamping, candidate-only bond exclusion, solver
bookkeeping and cost-only seed pass measures 13.21 s (14.24 s with imports/setup)
from isolated staged source: no material further end-to-end gain is established.
30 focused tests pass both in the worktree and without unrelated workspace edits.
Both complete display outputs
compare exactly with the captured original provider. 21 focused tests pass,
including approved atoms, exact numerical contracts and dependency/cache reuse.
The five-second cold target remains unmet; first-ever machine-code compilation
adds latency. Truncating to 100 iterations changed sampled posed atoms by up to
0.120 nm and was not adopted. MagicDNA's oxDNA-calibrated vertex model is a
potential separate model; retrieved supplementary Data S1 contains sequences,
not a relaxed atomistic seam library. No placement constants, authoring history,
saved designs or physical simulation paths were changed. See the
[cold-load evidence and reproduction](../docs/corner_cold_load_performance.md).

## Bevel tool — November 27, 2026

User scope: remove material beyond a plane, leaving mismatched/open scaffold and
staple ends. Autoscaffold repairs are a separate session; eventual MagicDNA-style
connections between bevel-ended bundles remain future work.

Tools → Bevel reuses Corner's cluster picker, popup, bp/nm and angle/direction
fields. The plane uses Bend's face-drag convention: a camera-facing drag plane
and nearest sampled helix-axis station. Tab outside form controls toggles native
rotation rings. Inputs and Full preview update during both gestures. The popup
uses the shared adjacent-sidebar layout on narrow canvases to leave the plane
accessible; ordinary Tab navigation inside fields is preserved.

Creation reuses already-loaded native Full geometry in private preview buffers
and requests only current axis stations/material frames. Immediate parameter
updates do not wait for server calculation or rebuild meshes: complete residues
and bonds are masked locally, including seam inserts whose endpoints are removed. If native
geometry is unavailable, it is projected once. History editing independently
replays and projects the feature's input once; the live preview shows that stage,
with an explicit note that later features replay on Apply. Apply still uses the
real server recorder/replay with source/revision checks. The UI no longer performs
speculative Bevel preparation: the user requires the first Apply itself to be fast.
The optional prepared API remains cancellable and source-bound for other callers.

Apply latency investigation (November 27): the plane classification was cheap;
serial Full + straight geometry rebuilt the entire atom model and optimized Corner
seams. An instrumented baseline measured 0.71 s recording and 55.06 s projection.
The earlier background-preparation workaround was rejected and removed.

Current implementation records exact optimizer-query bounds, including rejected
trials, and ordered environment-coordinate fingerprints. This permits exact fit
reuse after distant deletions. A stricter whole-projection certificate requires
unchanged placement/Corner connections, contiguous strand slices, identical retained
sequence, no deletion within any queried neighbourhood, and preservation of capped
clash traversal prefixes. Unsupported or nearby cuts use the canonical calculation.
No optimizer equation, tolerance, placement constant, or approved golden changes.

Bounded, content-keyed projection and serialized display caches survive history
navigation and Save As identity changes; source/revision publication checks remain
separate. Certified deletions reuse retained native frames and recompute strand,
occupancy and terminal metadata. Returned records are isolated. Full projection
releases temporary atom models after extracting landmarks/certificates, while
ordinary atomistic consumers retain their existing cache policy. This removes
large cyclic-GC scans from subsequent Bevel edits. Edit previews request Full only,
without an unused straight-view payload.

Validation (November 27): fresh canonical Full/straight equality, approved atom
regressions, independent process verification, source immutability and cache
ownership/invalidation checks pass. Direct compact-array trimming avoids expanding
and re-transposing Full records; edit source uses the same ordinary compact format.

**ISSUE-273 remains open: the strict subsecond target is not consistently met.**
The last unprofiled complete app run on `corner_test.nadoc` measured Apply 982 ms,
undo 760 ms, redo 394 ms, editor opening 1170 ms, edit commit 1469 ms, delete 785 ms,
undo-delete 503 ms, revert 516 ms and undo-revert 588 ms. Live Full preview updates
were 3–9 ms. Straight/curved app flows passed; the Corner app flow passed independent
replay but failed the unchanged 1000 ms latency assertion. A diagnostic profiled run
located 544 ms in upstream Corner replay when opening the editor; Apply's backend
was 390 ms and edit's backend 622 ms. Profiling instrumentation was removed.

These are click/API through scene synchronization measurements; continuous software
raster is paused as in the Bend harness. Initial design loading is separate and no
Bevel candidate is prepared in the background. Unsupported seam-changing cuts,
restoring previously absent material and empty projection caches retain canonical
fallbacks; universal cold subsecond performance is not established. No fit tolerance,
geometry golden, history proof requirement or timing threshold was weakened.

Focused regression coverage: 50 backend checks across Bevel commands/live cuts,
projection equivalence, dependency/fit caches, atom-cache retention, worker
cancellation, preflight selection and Corner command-version replay; 16 frontend
checks across Bevel tool/API and deformation display synchronization passed.
`just lint` passes. `just lint-memory` retains an unrelated missing index entry for
`project_oxdna_occupancy_clouds.md`; oversized Corner chronology was moved to the
linked archive without discarding it. Current `just smoke`: 28 passed, one assembly-exit fixture timed out at 60 s while
loading/framing its assembly, before exit (the documented ISSUE-266 pattern).
No timeout was raised; the isolated workspace, reports, browser profile and
revision stores were removed and absence verified. All Bevel browser scratch
roots were likewise removed; `corner_test.nadoc` SHA-256 remains
`c8f531df79bf5086f9b3ee23deda4e7b78b015868186445947116f8586a06815`.

New commands record `_proof_version: 2`. Every occupied duplex station is
classified by its signed distance from the plane. Entire Corner wedges can be
retained or removed; curved paths may retain several intervals, splitting the
strand at every removed interval. 0° is perpendicular, tilt stays below 90°,
and direction is local azimuth. End/Start select the forward/reverse plane side.
The frame follows occupied material rather than extrapolated empty Corner axes.
Version 1 retains its original single-crossing replay semantics; the recorder
preserves the command's actual version rather than stamping the generic version.

Retained sequences, polarity, construction axes, deformation parameters and
native placements are preserved. Cut crossover/ligation records are removed;
no junctions, turnarounds or autoscaffold changes are added. Attached references,
organized parts and scoped membership needing remapping remain explicit refusals.
Direct assembly invocation still requires source-part topology ownership.
Autoscaffold and MagicDNA export compatibility have not been qualified.

`corner_test.nadoc` validation uses an isolated imported copy with a recorded
metadata rename; the original bytes are unchanged. Backend checks cut both arms,
verify retained native coordinates and independently replay the recorded process.
The live app checks Full updates at several stations, real face drags across the
corner from 60 to 140 bp and along its arm from 140 to 153 bp, Tab/ring rotation,
Apply and independent verification. Cached update samples were 2.9–5.1 ms,
excluding rasterization. Like the existing Bend
latency harness, the large-design test pauses continuous software WebGL rendering
and explicitly renders inspected views; these timings are not an FPS claim.
Straight/curved workflows also cover history edit and undo/redo. Scratch roots
are removed by the isolated launcher's failure-safe cleanup. `main.js` task LOC
Δ is 0 (existing factory wiring gains camera/canvas/controls arguments).
Focused validation passed 80 backend checks, 27 frontend checks, and all three
straight, curved, and actual corner-design app workflows.
Lint and diff checks passed. Smoke passed 28 checks and repeated the pre-existing
assembly-exit fixture timeout in `scene_harness.js:434` before teardown; its
isolated scratch root was removed and verified absent.

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

## Detailed implementation chronology

The [Corner archive](project_corner_primitive_archive.md) preserves command-v3
sequence ownership, tip-cut and Full bond coverage details, historical review
stages, and the original optimizer design. Earlier pending-approval statements
there are superseded by the approval recorded above.
