# VR authoring campaign — active goal, 2026-09-22

Watch both workflows: [terminal demo instructions](vr_workflow_demo.md).

Goal: support and independently validate two complete user workflows, then achieve
at least 90% observed end-to-end success with the highest-variability simulated
controller profiles. This goal is **active**, not achieved. Existing draft painting
and transport checks do not count as successful authoring.

Current checkpoint: the desktop-first workflow now passes a combined physical
runtime diagnostic: real desktop mouse extrusion → VR default plane → blunt end →
freeform → Undo/redo → cadnano edit → save/reload. Final all-control noisy validation
is still missing: ideal menus/placement/end acquisition and semantic VR activation
prevent cohort credit. The combined sequence still profiles only paint reaches; the separate VR-first
regression now profiles menu reaches too (see its retained variable_fast failure below).

## Editable workspace

Open `workspace/VR Testing/` in NADOC's workspace library. On this workstation it is
`/media/jojo/Archive/NADOC_archive/runtime/workspace/VR Testing/`.
Current published output: `vr-first.nadoc`, from a verified steady_fast VR-first
round trip (6authored helices plus1empty cadnano-added helix). The old blank starting
parts were removed; desktop-first review output awaits regeneration. These files
are editable outputs, never proof or expected input for validation.

User instruction explicitly permits persistent VR test parts and deletion of old
parts on retest even after user edits. This is a narrow exception to the general
rule against development artifacts in the user workspace. **Every .nadoc file
inside this marked folder is disposable on retest**, including renamed files and
real subfolders. Move anything worth keeping outside the folder. Symlinked folders
are never traversed; file symlinks are unlinked without deleting their targets.
Other files, including notes, are retained. No reset targets other workspace folders.

Commands:

```sh
python -m tools.vr_workflows.workspace init
python -m tools.vr_workflows.workspace prepare  # delete old parts, create two blank parts
python -m tools.vr_workflows.workspace reset    # delete old parts without recreating them
```

The runner must hold `campaign_workspace` for its entire run and close its browser
documents/stop its own autosave writers before reset, so an old document cannot
reappear after deletion. Do not close unrelated user documents. The lock excludes
other campaign runners; it cannot lock out interactive user editing. Capture evidence
before reset, not copies of accumulating old parts. User part content is never a
validation oracle. Regression tests use fresh isolated models and temporary paths.

Playwright inventory exception authorized by this user: the two intended review
parts persist in this dedicated folder instead of being removed by global teardown.
Any incidental workspace parts still use `__e2e__` and failure-safe cleanup. Before
running, inventory every output and verify that only the two intended review parts
remain afterward. Evidence belongs under `.development-artifacts/vr-workflows/`.

## Workflows and division of tools

1. New part → desktop extrusion of a six-helix honeycomb bundle → enter VR →
   create default-plane extrusion → extend a blunt end → create a freeform bundle
   at an oblique pose → inspect/edit in desktop 3D and cadnano → save/reload and
   undo/redo. All three VR extrusion modes must succeed within each passing trial.
2. New part → enter VR while empty → initial default-plane extrusion → the same
   desktop/cadnano editing and persistence checks. No desktop pre-created geometry.

Playwright owns actual browser controls, document lifecycle, workspace opening,
VR launch/return, 3D and cadnano interactions. ScryWrite applies simulated Vive
poses/buttons, observes hit outcomes and committed transactions, measures pixels
and retains stereo captures. APIs independently inspect topology, IDs, lattice
coordinates, rigid transforms, revisions and saved documents. API seeding cannot
substitute for an interaction counted toward workflow success. Semantic activation
may diagnose a failure, but cannot count as successful user tool acquisition.

Independent checks must compare against the requested operation: helix counts,
cell addresses, bp ranges, strand endpoints/connectivity and frame placement;
preview/committed agreement; no accidental extra cells; no overlapping exported
cell identities; actual edit of the intended helix in cadnano; persistence and
undo/redo. Never derive the expected geometry by rereading the editable workspace
output. Numeric render checks run frequently; actual eye/desktop images remain
required at stage boundaries. Native submission is not compositor acknowledgement.

## Fixed acceptance cohort

`tools/vr_workflows/acceptance.py` defines both workflows, required stage evidence,
seeds 0–19 and two groups per workflow: `variable_fast`, `variable_deliberate`.
Both presets share the highest current positional/rotational variability (12 mm,
2 degrees, 15% overshoot); speeds/reaction times differ. Require ≥18/20 successful
whole workflows **in each of four groups**, with all 20 attempted and recorded.
Missing trials block completion. Duplicate seed entries are rejected; retries
cannot replace failures. In total this is 80 validation trials. This is an observed
cohort success threshold, not a statistical claim that the population rate is ≥90%.
Use different tuning seeds (1000+) during development. Any UI/code change during
final validation starts a fresh cohort; record code revision/diff digest, profile
parameters, runtime versions, target dimensions, seed, timing and all failures.

Start each implementation increment with `steady_fast`; final regression checks
include all four profiles. Numeric aggregation only checks recorded verdicts:
it does not independently prove their truth. Completion additionally requires a
review of the evidence and executable geometry oracles for every required stage.

## Implementation order and current gaps

- [x] Persistent goal, reset policy, editable workspace and fixed cohort evaluator.
- [ ] Browser-driven workflow runner and independent geometry/persistence oracles.
- [ ] Canonical lattice-frame identity, occupancy/membership and editor addressing.
  Explicit persisted frame identity and independent-bundle candidate builder added;
  membership lookup distinguishes frames. Export packs separate frames without
  changing local cells. Slice frame selection and local-cell add/remove are verified.
  Continuation and crossover-neighbor lookup remain.
- [ ] Browser-authoritative atomic VR extrusion commit; stale/repeated requests rejected.
  Painted cell/lattice transport is now implemented and verified through native
  input, event parsing and browser reduction. Selection changes and tool reset
  advance the config sequence. Frame resolution/commit executor remain pending.
- [ ] Empty-part VR launch and default-plane authoring. Empty snapshots/native loading
  now support explicit v14 `Q empty_authoring`; physical runtime and default XY
  draft painting verified. Browser launch, commits and full workflow remain pending.
- [ ] Blunt-end continuation using existing topology/polarity semantics.
- [ ] Freeform canonical-plane topology plus persisted rigid pose; collision-safe editing.
- [ ] Desktop/cadnano inspection, targeted editing, save/reload and undo/redo.
- [ ] VR UI refinement and profile-based usability trials.
- [ ] Fixed final cohort reaches the threshold with reviewable evidence.

Reuse established builders, transforms and history. Do not rewrite phase constants
or create a VR-specific geometry engine. Coordinate boundaries and known collisions
are recorded in [the lattice mapping audit](vr_extrude_lattice_mapping_audit.md).
Bare cadnano JSON cannot retain arbitrary 3D placement; the native document must.

For UI improvements, use actual task failures to choose changes: clear action labels,
mode-specific fields, primary confirm/cancel, observable preview and confirmation,
hit target dimensions at operating distance, missed/extra activations, time and
correction count. Keep developer transport/status text in the inspector. Evaluate
baseline and candidate with matched profiles/seeds; preserve baseline failures.
Do not make buttons larger only during tests or weaken hit thresholds to pass.

## Draft transport contract

Native configuration carries optional `painted_footprint` with `lattice_type`
(HONEYCOMB/SQUARE) and distinct integer `[row,column]` cells. Empty selection is
valid. Limit matches native capacity (16,641 cells); coordinates are bounded to
±100,000. Python and browser parsers validate/copy the payload. It does not imply
authoring-frame resolution: `footprint_state` remains unresolved until a validated
part/frame/placement candidate exists. Existing exact-end context is preserved.
The event-file byte limit is 512 KiB to accommodate native draft capacity; geometry
operation bounds and document revision checks remain separate requirements.

Live evidence: `.development-artifacts/vr-workflows/draft-live-report.json` and
`draft-browser-input.json` (actual native event parsed by backend, used by browser
exercise). These are diagnostic outputs, not editable workspace validation fixtures.

### Browser workspace isolation

Smoke testing exposed a shared mrDNA job-reconciliation write race despite separate
HTTP servers. Backend already honors `NADOC_WORKSPACE`; browser scene-harness saves
and global teardown now honor the same variable. Run disposable regression checks
with a temporary workspace and failure-safe removal. For the authoring campaign,
use the explicitly managed VR Testing directory, so generated parts are inspectable
without exposing unrelated jobs to the campaign backend. Merely using different
ports is not filesystem isolation. Existing topology assertions must remain intact.

The initial shared-workspace smoke failure is retained under
`.development-artifacts/vr-workflows/shared-workspace-smoke-failure/`; isolated
comparison log and cleanup manifest are `draft-isolated-smoke.log` and
`draft-isolated-cleanup.json`. The reproducible isolation wrapper is
`isolated-smoke.py` in the same evidence directory.

## Lattice-frame candidate increment (2026-09-22)

`Helix.lattice_frame_id` refers to a `Design.lattice_frames` entry containing its
canonical plane and placement-cluster reference. Legacy helices keep a null frame
and their existing behavior. Load validation rejects missing/duplicate frame IDs
and missing placement clusters. `append_independent_bundle` uses the existing
standard bundle builder with explicit local cells, then existing rigid-cluster
placement with zero pivot. It does not mutate the input or infer ligation. It is
a pure candidate builder. The revision-checked endpoint described below now
exposes independent frame creation; the native controller adapter is still pending.

Regression oracles cover HC/SQ × XY/XZ/YZ, a 37-degree rotation/translation, exact
cell identity, negative bp intervals, save/load, unrelated-cluster inheritance and
dangling references. Export lays separate frames into disjoint bands with row
offsets divisible by six, preserving parity/row phase. Local cells stay unchanged.
Pose remains in .nadoc; compatibility notes disclose cadnano pose loss. Multiple
segments at one cell within a frame currently raise a consolidation-required error
in that export layout, rather than silently overlapping or changing their topology.

A fresh two-frame candidate was imported through the running desktop app; both
placements and frame records survived and four unique cadnano export cells were
verified. The actual 3D screenshot was inspected. An initial screenshot was
obscured by the welcome screen despite passing state assertions; that evidence is
retained and the browser check now opens a part via normal UI and frames geometry.
See `.development-artifacts/vr-workflows/frames-browser-review/`. This initial check did not prove cadnano-editor selection/editing; the next
increment below covers local-cell editing. Neither proves a full VR authoring workflow.


## Frame-specific cadnano editing (2026-09-22)

The slice view now offers a lattice-frame selector. Occupied cells and empty-cell
insertion use that frame's local coordinates and canonical plane. New helices
inherit its placement cluster, including distant cells that have no nearby
neighbor. Existing unframed insertion excludes framed reference helices. The
mutation uses normal history, and undo restores the prior document.

Browser validation imports a fresh two-frame design, selects the second frame,
adds a cell by clicking the actual slice SVG, checks frame/cluster membership,
switches back to verify the first frame is unchanged, and removes the new empty
helix through the UI. An existing incorrect deletion URL was corrected. Frame
switching now centers occupied cells using rendered bounds; the browser asserts
full visibility and retains a reviewed screenshot. The selector uses readable
contrast. Evidence: `.development-artifacts/vr-workflows/frame-editor-validation.md`.

This covers local-cell editing, not continuation/ligation, arbitrary-frame VR
commit, or the final controller-profile cohort. Those remain required. Path view
continues to display all helices; local slice selection disambiguates cell addresses.


## Independent-frame commit API (2026-09-22)

`POST /api/design/frame-extrusion/validate` validates a canonical cell footprint,
source plane and rigid part-space placement without mutating the document.
`POST /api/design/frame-extrusion` commits it through normal snapshot history.
Both require the expected design ID and revision. Commit checks these under the
mutation lock; stale/repeated requests fail without changing the document.
Requests carry nanometres and a unit XYZW quaternion, not raw tracking metres.
The request is bounded to 200,000 base-pair cells per interactive operation.

The browser API `addFrameExtrusion` uses normal geometry/store synchronization;
`validateFrameExtrusion` is read-only. Commit returns the feature entry identity
for the existing VR transaction coordinator. A dedicated `extrude-frame` history
kind preserves undo/redo/revert without offering the legacy length-only replay
editor, which would otherwise lose frame placement.

A running-app check creates an empty part, commits a canonical extrusion and an
obliquely placed second frame, rejects a repeated confirmation, verifies both in
3D and the cadnano frame selector/export, then undo/redoes the second edit.
Initial evidence exposed missing geometry refresh when using a bare design GET;
the commit now uses the shared response synchronization path. Evidence is under
`.development-artifacts/vr-workflows/frame-commit-synced/`.

This API creates independent frames; it does not infer end ligation or certify
physical collision freedom. It does not yet resolve native paint/source selection,
inverse tracking placement, or attach the native Confirm button to this operation.
Those and blunt-end continuation remain necessary before any trial can pass.


## Empty-part painted preflight (2026-09-22)

The browser now resolves a normalized targetless painted draft against a genuinely
empty document into an `extrude_frame` descriptor. It pins design ID/revision,
explicit XY/XZ/YZ source plane, signed length and copied cell arrays. It calls the
real `validateFrameExtrusion` API without committing or changing displayed geometry.
Missing paint, lattice mismatch, zero length, missing plane, unsupported strand
filter and existing authored objects produce explicit blocking reasons. Existing
parts still need explicit frame/placement resolution; they are never implicitly
extruded as a fresh overlapping frame at the origin.

Focused planning/coordinator tests: 21 passed. Full frontend: 464 files, 6617 tests
passed. Browser `vr_frame_commit.spec.js` verifies real painted preflight and that
the document remains empty before commit, then the existing 3D/cadnano/undo checks.
Evidence: `.development-artifacts/vr-workflows/painted-preflight-browser.log` and
`painted-preflight-frontend.log`; temporary-workspace cleanup confirmed.

Native Confirm requires action-time configuration binding, retained validated
plans, targetless execution acknowledgements and native controls enabled only for
the matching preflight. The first two are implemented in the next increment below;
the latter two and the commit handler remain pending. No controller workflow success is claimed by this read-only increment.


## Action-time draft binding (2026-09-22)

Native `publishToolIntent` snapshots `tool_action_config_sequence` at click time;
later paint changes update only the current configuration sequence. The backend
validates this integer against the current sequence and preserves it in the event.
Legacy events remain explicitly unbound (zero). Browser session events carry
`configSequence`; they never substitute the latest configuration for a missing
click-time binding.

The preflight coordinator retains a copied plan only after an OK verdict is
published. `takeValidatedPlan(sequence)` consumes it once for the matching action;
wrong sequences cannot consume it. Any new request (including malformed input) or
cancel invalidates it immediately. A generation check after feedback delivery
prevents late network completion from resurrecting an invalidated plan.

Native build and all 36 CTests pass. Focused backend transport: 16 passed. Frontend:
464 files / 6620 tests passed. The browser exercises the real backend validator and
one-shot retained plan with an isolated feedback sink, then existing commit/3D/
cadnano checks. This is not live native Confirm verification. Evidence:
`.development-artifacts/vr-workflows/action-binding-browser.log` and related
`action-binding-*` logs. Native Confirm remains gated pending its browser commit
handler, targetless execution acknowledgement and native execution-state wiring.


## Browser painted Confirm/Undo executor (2026-09-22)

`vr_painted_commit.js` now intercepts targetless extrusion Confirm/Cancel/Undo in
the actual native-event handler. Confirm consumes the plan for the click-time
configuration sequence, checks document ID/revision, publishes pending, then uses
the shared VR transaction coordinator and `addFrameExtrusion`. Pending delivery
must succeed before mutation. A failed terminal acknowledgement never replays the
mutation. Repeated action sequences are ignored; Undo remains bound to the exact
feature-log tail and refuses intervening desktop edits.

Execution feedback accepts targetless extrusion as `none -`; Move/Rotate still
requires an object target. Native acknowledgement parsing preserves this distinction
and skips Move/Rotate's transient GL commit/undo transforms for extrusion. Native
Confirm control enablement is still pending; do not claim a physical controller
commit from these browser checks.

`vr_painted_commit.spec.js` runs the real app event handler, backend authoring API,
store/geometry refresh and undo. Only native feedback delivery is isolated. It
verifies duplicate Confirm does not add an edit, matching commit/undo feature IDs,
and zero helices after Undo. The real desktop capture was inspected. Evidence:
`.development-artifacts/vr-workflows/painted-commit-browser/`. Frontend 6625 tests,
focused backend 74 tests, native build and all 36 CTests pass.


## First physical Confirm acknowledgement (2026-09-22)

Native Confirm now requires matching current configuration/preflight, nonempty
paint, positive length, an event channel and no pending transaction. The status
shows READY TO EXTRUDE and Confirm turns green only then. ToolShell enters pending
immediately. `painted_commit_ready` is exposed for observable-state waits.

An opt-in physical test launched a fresh empty part from the browser, used real
production controller hit testing to paint two cells, set length, and click native
Confirm. Browser committed two one-bp helices in one frame/feature; native displayed
COMMITTED and the matching feature ID. No feedback interception was used. All 36
native checks pass. Physical integration passed its **acknowledgement-only** scope.

The original eye capture exposed missing topology refresh. This is now implemented
by revision-checked `/api/vr/scene-refresh` publication and native atomic scene
replacement. Replacement preserves normalization, primitive identities, view,
input, visualization and session state. Browser painted commit/undo requests it;
ordinary desktop edits are not yet subscribed. Stale documents/revisions reject.
Native reports `scene_revision` only after successfully building the replacement.

A subsequent physical run verified revision 3 and canonical authored object pixels
in both eyes after closing the lattice panel and using production RECENTER. Counts
were only 5/9 pixels: transport/render presence passes, but useful visibility does
not. The reviewed image confirms the structure remains too small. Do not count this
as a user-workflow or usability pass. Next: fit-to-authored-bounds presentation,
visible desktop mirror proof, undo replacement and meaningful 6HB-sized paint.
Also remove stale target-required activation toasts and update the legacy
`commit_supported:false` diagnostic. No final-cohort successes are counted.

Refresh evidence: `.development-artifacts/vr-workflows/scene-refresh-validation.md`.

Evidence: `.development-artifacts/vr-workflows/native-confirm-browser/` contains
physical submitted-eye captures, native state, and desktop image. Captures reviewed.
Test scope uses semantic tool entry and ideal aim, not a controller-profile trial;
no final-cohort successes are counted. `native-confirm-cleanup.json` confirms no
parts left. The idle diagnostic viewer was restored afterward with no input loop.
Initial harness launch failed because the sanitized native PATH lacked npx and its
script lacked the repository import root; both were corrected before the successful
run. No SteamVR/runtime/display setting was changed.

## Authored-bounds Recenter and physical Undo (2026-09-22)

RECENTER now fits actual authored primitive bounds (including current displayed
transforms, excluding unowned viewer axes) in front of the tracked head. Fit uses
a 0.25 m bounding radius within existing 0.05–20 display scale limits. It changes
presentation only; normalization, lattice coordinates and stored geometry stay
fixed. Empty scenes retain the previous recenter fallback. The same two 1-bp
helices improved from 5/9 visible authored pixels to 3774/3724; the reviewed mirror
shows the bases, although a meaningful 6HB authoring run is still needed.

Physical browser→native commit/Undo now passes: COMMITTED revision 3, then UNDONE
revision 4 with zero canonical object pixels in both eyes and zero browser helices.
This remains ideal aiming/semantic activation, not the noisy acceptance cohort.
Repository-owned probe: `tools/vr_workflows/native_confirm_probe.py`, invoked by
`frontend/e2e/vr_native_confirm.spec.js`; persisted workspace files are not oracles.

Repeated runs uncovered ISSUE-33 (null draft target resolution stopped polling)
and ISSUE-34 (non-atomic state publication plus destructive status reads could
orphan a viewer). Both corrected; failed attempts retained. Menu navigation now
uses observed controls after explicitly reacquiring a right-hand input pose.
Evidence: `.development-artifacts/vr-workflows/fit-validation.md`,
`fit-physical/`, `fit-undo-atomic/`. Goal remains active; remaining work includes
6HB/profile-driven interaction, stale target toasts/diagnostics, source-frame and
blunt-end/freeform authoring, actual desktop-window visibility, round trips and
all fixed-denominator acceptance cohorts.

## Physical 6HB baseline (2026-09-22)

The opt-in physical probe now paints the desktop preset's six honeycomb cells
`[[0,0],[0,1],[1,0],[2,1],[0,2],[1,2]]` and sets 42 bp using production controls.
The actual browser-backed run verifies exact cells, per-helix lengths and frame
membership; native authored pixels; six cadnano vstrands each with 42 scaffold
and staple bases; six occupied editor cells; and physical Undo to an empty part.
`sixhb-timed/` passed in25.3s (28.2s with startup). Commit/snapshot took12.185s.
Both eye buffers contained authored pixels (5758/5709); reviewed mirror is end-on
and still small, so no legibility or through-lens comfort claim. Cadnano screenshot
shows all six 42-bp rows and their lattice cells.

This exposed ISSUE-35: autosave advances revision during snapshot serialization.
Refresh now retries at most three times only when the same design has a newer
revision; it never repeats the mutation, retries an unchanged revision, or switches
design identity. Old snapshot guard remains intact. Failed runs are retained as
`sixhb-physical/` (409 stale snapshot) and `sixhb-refresh/` (10s diagnostic wait).
The physical observation window is now120s within180s overall to measure the larger
workload; this is not a responsiveness acceptance target or a controller timing
relaxation. Controller variability is still absent; no cohort success is counted.

Next: replace repeated + clicks with profile-driven wheel interaction; improve
oblique inspection, complete all origin modes and edit/round-trip checks.
Evidence index: `.development-artifacts/vr-workflows/sixhb-validation.md`.

## Profile-driven cell acquisition (2026-09-22)

`tools/vr_workflows/profile_input.py` computes a controller ray orientation from
exported live cell positions and plays the existing preset at20Hz with its original
noise/reaction/duration. Endpoint noise is retained. It records intended/noisy/actual
poses, frame IDs, lag and applied-pose error. No native aim command or endpoint snap
is used for these cell reaches. Length/menu/Confirm controls remain ideal-input
diagnostics and are explicitly outside this partial profile coverage.

The initial steady_fast seed0 diagnostic clicked a neighboring cell, toggling a
previously painted cell off; retained under profile-steady/. Input delivery was
accurate, so this exposed acquisition sensitivity. The probe now checks the visible
hover highlight before clicking and allows at most three noisy reaches per target.
Every miss and correction is retained; exhausted acquisition fails the trial. This
is a declared visual-feedback user model, not an ideal correction or hidden retry.

Steady_fast seed0 then passed all6HB/cadnano-read/Undo baseline checks in33.1s.
Seven reaches, six clicks, one correction,119 measured poses; maximum delivery
error0.004881mm,0.000085degrees and playback lag0.000473s. Six focused motion tests
passed. Physical runs are serial per user crash caution; no broad suites or builds
were started. No whole-workflow/profile cohort success is counted.
Evidence: profile-corrected/, profile-motion-summary.json; variable-fast diagnostic
recorded separately in profile-variable/.

Variable_fast seed0 failed first-cell acquisition after three noisy reaches
(hovered[-2,-2],[1,0],[-1,4]); no incorrect click was sent. Preserve this baseline
and improve production target presentation/acquisition before a final cohort.
See profile-validation.md. This is not a blocker requiring user input.

### Zoom and approach diagnosis

`NADOC_VR_PAINT_ZOOM=4` uses existing two-hand scene grip as declared ideal
presentation setup (cell radius6.48→25.92mm). Tablet border resizing alone does
not enlarge cells. Variable_fast seed0 still missed at66–71degree ray incidence.
`NADOC_VR_PAINT_APPROACH=normal` instead approaches25cm along tablet normal,
keeping original noise. First three cells acquired, but(2,1) was clipped out of
visible_cells at this zoom. No cell skipped and no validation pass claimed.
Next add production lattice pan/recenter; preserve coordinate/footprint identity.
Evidence: zoom-acquisition-validation.md, profile-zoom4/, profile-normal4/.

### Center paint implemented

Native footer **CENTER PAINT** recenters the lattice view around painted-cell
bounds, with no cell/length/source-plane edits. Empty paint preserves origin.
ScryWrite exposes button bounds and extrude.view_origin. Two-worker build and
36 CTests pass. Physical variable_fast seed0 at4x scene zoom/normal approach
now passes6HB/cadnano-view/export/Undo with8 reaches and6 correct clicks.
View origin changed[0,0]→[1,1], cells remained exactly equal.
Evidence: center-paint-validation.md and profile-centered/. Other controls remain
ideal; no final cohort success. This supplies recentering, not arbitrary lattice
panning. Reviewed mirror still has small text; desktop legibility remains open.

### Desktop edit/save/reload checkpoint

Physical variable_fast seed0 partial diagnostic now also stops VR, redoes the
6HB in desktop, adds an empty seventh helix through cadnano, saves, and opens
the saved part through the workspace library in another document. Helices,
strands, lattice frame, placement clusters and504 nucleotide positions survive
exactly. Desktop screenshot reviewed: model visible with welcome screen gone.
Cadnano cell addition intentionally creates no new strands.
Evidence: `.development-artifacts/vr-workflows/desktop-roundtrip-validation.md`.
One serial browser test passed38.7s; temporary parts removed; idle native viewer
restored and observed. Earlier test-assumption/visibility failures retained.
No full workflow or final profile cohort success counted.

### Existing source-frame operation

Frame-extrusion API now accepts `source_frame_id` for default-plane cells in an
existing logical frame. It retains that frame's rigid placement exactly once,
rejects occupied cells or mismatched planes, and supports undo/redo. Shared
canonical builder handles independent and existing-frame cases.33 focused tests
and an isolated desktop/cadnano browser exercise passed; reviewed screenshots
show the added populated cell in the oblique frame. Backend FAST suite retains
the same30 failures/9errors as the previous baseline. Full suite deferred.
Evidence: `.development-artifacts/vr-workflows/existing-frame-validation.md`.
Native/browser source selection and legacy desktop-frame resolution are still
needed; the painted planner still refuses nonempty parts. No cohort success.

### Source-plane planner integration

The painted planner now accepts an existing part when its helices have valid
frame references and Extrude from identifies exactly one source frame by plane.
It pins source_frame_id, retains backend preflight/revision guards, rejects
occupied cells or ambiguous frames, and avoids reapplying rigid placement.
Frontend6631tests, browser planner/API exercise and23smoke checks pass.
Evidence: `.development-artifacts/vr-workflows/source-plane-validation.md`.
Physical controller confirmation of this new branch remains pending; legacy
unframed desktop geometry and multiple same-plane frame choice remain open.

### Existing-frame live checkpoint and autosave revision fix

Steady_fast seed0 physical diagnostic now passes desktop6HB creation via frame
API → VR six new painted cells in same37degree-rotated frame → desktop/cadnano
checks → native Undo preserving original6 → cadnano edit/save/reopen with1008
positions unchanged. Corrected confirmed autosave revision acknowledgements
(ISSUE-36). Commit/Undo snapshots take20.1/12.4s; responsiveness remains open.
Scale0.6 was needed for26.57mm paint targets; 4x and1x failures retained.
`visible_cells` can include clipped, non-pickable centers: needs stronger targets.
Only cell reaches use profiles; other controls ideal. No final cohort successes.
Evidence: `.development-artifacts/vr-workflows/existing-frame-live-validation.md`.
Frontend6633tests and23smoke tests pass. Backend FAST suite remains failing, with
one extra session-cache test passing on focused rerun; full suite deferred.

### Standard desktop create-bundle handoff

Fresh desktop bundles now carry canonical cells/frame IDs in all three source
planes. Disconnected placement clusters receive separate frames. Primitive copy
paths preserve/remap frame identity; derived assembly simulation flattening clears
frame references only on its baked copies. Ordinary createBundle→liveVR additional
cells→cadnano/save/reopen passes with steady_fast seed0. Desktop creation still
uses the API; actual desktop painting gestures remain to be covered. Existing
files are not migrated automatically. Source disambiguation remains necessary.
Evidence: `.development-artifacts/vr-workflows/desktop-frame-validation.md`.
Adaptive diagnostic zoom now targets26mm using observed radius (0.569x in this
run). Desktop screenshot reveals side-panel clipping; improve full-model framing.
Backend FAST suite returned to exact prior30failure/9error names,8787passed,
under90s timing gate; full suite deferred. No final cohort success counted.

### Frame-scoped blunt-end continuation foundation

Continuation API accepts source_frame_id and frontend adapter sourceFrameId.
Conflict/end lookup is limited to that frame; forward/backward/gap extension
retains local cell/frame identity and rigid placement.11focused tests and browser
normal-API exercise pass: one rotatedXZ42bp helix becomes63bp, fourothers remain42,
cadnano exports those exact lengths. Reviewed full-tip desktop capture.
Evidence: `.development-artifacts/vr-workflows/frame-continuation-validation.md`.
Frontend6634tests and23smoke checks pass; backend FAST retains prior failures.
Native From blunt end transaction wiring is implemented in the later end-executor
checkpoint; physical controller validation remains open.


### Canonical VR end context on rotated frames

VR end selection now separates the rendered face locator from the canonical
continuation plane/offset. A uniquely placed framed helix carries sourceFrameId
through preflight and commit; rigid placement alone is no longer classified as
bending. True deformations, overlapping domain placements, invalid axes and
ambiguous placement remain rejected. No molecular geometry constants changed.

The running browser exercised its rendered end table and VR preflight planner
against an XZ frame rotated 45 degrees about X: selected helix42→63bp, four other
helices unchanged, placements unchanged,462 displayed bases and matching cadnano
export lengths. The diagnostic supplies selection identity and invokes the normal
continuation API; it does not establish native controller picking/Confirm success.
Reviewed screenshot shows both frames and the entire extended tip. Evidence:
`.development-artifacts/vr-workflows/vr-end-source-validation.md`.
Native target-bound execution is implemented below; no final cohort success counted.


### Guarded continuation transaction prerequisite

Continuation validation/commit now accept paired expected_design_id and
expected_revision. Commit checks revision under the mutation lock and design ID
inside the mutation; stale or wrong-document requests leave topology unchanged.
Legacy desktop calls may omit both. The response includes the exact feature-entry
ID for the shared VR Undo coordinator. Frontend adapters pass optional guards.
Native Confirm is connected in the end-executor checkpoint below.

Five focused backend tests pass. The guarded browser exercise initially refused
revision8 against server9 after a separate cadnano client; failure retained.
Refreshing the document before preparing the operation gives a passing browser
exercise with the same geometry/cadnano oracles. No mutation retry added.
Evidence: `.development-artifacts/vr-workflows/continuation-guard-validation.md`.


### Shared end extrusion executor

End preflight/commit descriptors now pin document/revision and owner tokens.
The existing painted commit coordinator also executes exact end continuation,
resolving the target again before mutation and rejecting changed owners/revision.
Both branches share pending acknowledgement, one-shot plans, duplicate suppression,
feature-bound Undo and native scene refresh. main.js gains only a target-resolver
argument (zero LOC increase). Native readiness/shell now admit validated end
Confirm with matching configuration sequence and identity.

Native build/36tests, frontend6643tests and the browser executor check pass.
The browser check uses the real end table, preflight and continuation mutation,
with diagnostic identity plus substituted VR feedback/refresh transport; one
42bp oblique-frame helix becomes63bp and all desktop/cadnano oracles pass.
This does not establish physical controller picking, end preview placement or
live scene refresh; those are the next physical checks. No final cohort successes.
Evidence: `.development-artifacts/vr-workflows/end-executor-validation.md`.


### Live end-acquisition diagnostic (not passing)

New `tools/vr_workflows/native_end_probe.py` and opt-in
`frontend/e2e/vr_native_end.spec.js` exercise real headset selection before Confirm.
Probe uses visible primitive IDs/depth and production controller-volume selection;
this is ideal diagnostic input, not a human-profile trial. Initial focus/menu
assumptions were corrected; ray selection was replaced with the actual12cm-offset
selection sphere. Captured pixels show overlap at the intended terminal, but
browser feedback returns default mode/strand owners after choosing END.
ISSUE-37 tracks the unresolved boundary. No end commit or cohort success claimed.
Evidence `.development-artifacts/vr-workflows/end-live-validation.md`.


### End selection-mode diagnosis refined

Two-hand interaction fixes the missed End control: left hand holds the menu,
right hand aims/clicks. Same-hand aiming was moving the attached menu; explicit
hover checks now catch this before subsequent actions. The latest physical trace
confirms selection_level end. Also corrected browser poll order (level before
selection) and prevented native feedback for an earlier selection overwriting a
new local level choice. Native36tests and frontend6643tests pass.

The remaining physical refusal is exact-target ambiguity: the25mm selection
sphere contains both terminal nucleotides and a spanning axis alias which resolves
to the far endpoint. ISSUE-38 tracks exact end acquisition; no geometry commit or
acceptance success. Evidence: end-two-hand trace plus
`.development-artifacts/vr-workflows/end-selection-fix-validation.md`.


### First physical blunt-end commit and desktop round trip

End-mode acquisition excludes ambiguous multi-end aliases and unresolved hits.
The diagnostic targets a visible terminal backbone bead, using captured depth to
position the normal controller selection sphere; exact owner match is required.
Physical Confirm now passes: one42bp helix grows to63bp, other stays42, frame/cell
and placement unchanged; native scene revision and COMMITTED acknowledged.
Native Undo restores42/42. Redo, cadnano empty-cell edit, save/reload verify210
nucleotide positions unchanged. Roundtrip helper accepts explicit document/base
count/neighbor-length expectations for mixed-length designs.

Native36tests, live end-roundtrip-framed pass. Desktop camera was rotated and
refitted to show full geometry; final model is small but unclipped. This is ideal
input using semantic tool activation; it does not count toward noisy human-profile
cohorts or prove arbitrary exact-end acquisition/physical through-lens visibility.
Remaining: coarse single-end aliases, source modes/freeform, all-control profiles,
complete desktop gestures and whole-workflow acceptance. Evidence:
`.development-artifacts/vr-workflows/end-exact-validation.md`.


### Freeform placement coordinate foundation

`native/vr_viewer/src/freeform_placement.hpp` converts a desired canonical frame
pose from tracking space into source nanometers plus a rigid quaternion. It undoes
view translation/rotation/uniform zoom and scene normalization; rejects shear,
reflection, nonuniform scale, singular/nonfinite transforms. Tests recover known
source poses through rotated/translated views at0.2x,1x,5x. This helper is not yet
wired to a user action or freeform commit; freeform remains incomplete.

End-mode filtering also excludes spanning `segment:` primitives with only one end
alias. Native36tests and physical end-segment-filter(27.6s) pass, including exact
Confirm, Undo and210-base cadnano edit/save/reload. Idle viewer restored focused;
no input loop or editor/runtime restart. Evidence:
`.development-artifacts/vr-workflows/freeform-placement-validation.md`.
Next: capture placement pose, publish bounded freeform draft through backend and
frontend validators, show source-plane-mapped preview, commit independent frame.
Empty-part initial extrusion must continue to use default-plane mode.


### Validated freeform draft and browser authoring path

Optional `freeform_placement` carries source-space translation_nm and rotation_xyzw
through native event parsing and frontend config normalization. Validators reject
nonfinite/out-of-range translation, nonunit/zero quaternion, extra scale fields and
end-target freeform drafts. Planner pins document/revision and creates an independent
canonical frame with that rigid placement. Empty-part freeform is refused, preserving
default-plane first extrusion. Existing source-plane continuation behavior is unchanged.

Running browser now creates its rotatedXZ frame through freeform preflight/plan,
then edits/continues it and verifies desktop/cadnano geometry. Native controller
pose capture, freeform UI choice and preview are still unwired; this is not a live
freeform success. Frontend6645tests and focused backend18tests pass. Backend FAST
8796pass/31fail/9error includes one extra session-cache restore-count failure which
passes alone; FULL deferred. Evidence:
`.development-artifacts/vr-workflows/freeform-draft-validation.md`.


### Physical freeform UI, preview and round trip

Native settings now offer Place freeform for targetless extrusion on an existing
part. Trigger captures controller position/orientation, converted through inverse
view/normalization into a canonical-frame rigid placement. The source plane stays
explicit; its positive extrusion axis follows controller forward. Confirm is
unavailable while placement is armed. Cancel clears placement; Use default plane
removes it. The placed wireframe and committed draft use the same stored pose.
The tablet-mounted preview is hidden after placement to avoid two conflicting
preview locations. Inspector state exposes freeform_armed/freeform_placed.

Physical freeform-complete passes (~1.3m): ordinary desktop bundle API creates6,
profiled paint reaches add6 via native freeform capture/Confirm, separate canonical
frame/rigid placement, original geometry unchanged, native scene refresh, cadnano
frame selection/export, native Undo restoring original6, redo, empty-cell edit in
source frame, save/reload1008nucleotide positions unchanged. Preview stereo and
reloaded desktop images reviewed. Native36tests pass. This is still a diagnostic:
semantic activation, ideal menu/capture controls, no independent runtime placement
accuracy oracle or complete highest-variability workflow trial.

Retained failures: freeform-physical Undo view missed remaining geometry; now
Recenter after Undo with pre-framing capture retained. freeform-reframed timed out
on fixed cell outside source-frame viewport; roundtrip helper now explicitly selects
frame/cell and bounds the click. Freeform-complete passes these stronger checks.
Evidence: `.development-artifacts/vr-workflows/freeform-ui-validation.md`.

## Desktop mouse seed integrated with physical freeform

`frontend/e2e/helpers/vr_desktop_seed.js` now drives Tools → Extrude, clicks six
rendered lattice cells, sets +42bp, and clicks Extrude. A read-only test facade
projects visible cell meshes; selection and mutation use actual mouse events.
The resulting cells, lengths and frame membership are checked independently.
The normal Fit shortcut exposes the off-origin bundle before review/VR entry.
`vr_native_confirm.spec.js` uses this helper for its desktop-bundle starting path.

The isolated gesture test and physical desktop→freeform→Undo→cadnano→save/reload
diagnostic pass. Frontend: 468 files, 6646 tests pass. Original API-seeded runs
remain historical evidence. Neither this diagnostic nor the earlier tests complete
the combined default/blunt/freeform workflow or provide all-control noisy cohort
credit. Current evidence: `.development-artifacts/vr-workflows/desktop-gesture-validation.md`.

## Combined physical authoring checkpoint

`frontend/e2e/vr_combined_authoring.spec.js` passes the complete desktop-first mode
sequence in one viewer/document (2.8m). It checks6→12→18helices, exactly one42→63bp
continuation,2canonical frames, exact Undo restoration and1554nucleotide positions
unchanged through cadnano editing/save/reload. `native_confirm_probe.py` requires
a fresh feature and newer scene revision per commit. End→freeform uses Inspect
and empty-space selection clearing. The terminal acquisition diagnostic uses a
recorded4×normal two-hand zoom; original failed-scale evidence is retained.

Three isolated workspaces cleaned and idle viewer restored. Reviewed reloaded
desktop image. No highest-variability cohort credit; this is still partly ideal
input. Evidence: `.development-artifacts/vr-workflows/combined-validation.md`.

## Profiled menus and VR-first regression

`ProfileControls` in `tools/vr_workflows/profile_controls.py` now drives menu reaches
without snapping. Exported rectangle intersection and hover must agree before a
trigger is sent; every miss and its path/size/distance/edge margin remain recorded.
This also guards against stale hover feedback; native '+' maps to '_', while '-' stays '-'. Enable via
`NADOC_VR_PROFILE_CONTROLS=1`. Tablet exit/centering and initial activation still
use ideal input.

VR-first steady_fast passes Confirm/Undo/cadnano/save/reload with48/48menu reaches.
Variable_fast fails after34increments:50attempts/16misses, ending with three '+'
misses26–33mm outside its edge. This establishes a repeated-button usability gap.
Next evaluate length wheel acquisition/drag/correction with these profiles; do not
increase retries to turn this failure into a pass. Focused tests8pass. Evidence:
`.development-artifacts/vr-workflows/profile-controls-validation.md`.

## Profiled length wheel evaluation

`profile_wheel.py` now records noisy acquisition/drag/correction with guaranteed
trigger release. Steady_fast VR-first passes in43.4s using one0→42bp drag.
Variable_fast failed exact length after three drags (35→56→28bp); normal panel
enlargement also failed (35→49→35bp). Native honeycomb detents are7bp,10.5mm at
initial panel scale and17.5mm after enlargement. The12mm positional noise is
comparable to that travel. Next evaluate coarse wheel followed by bounded
single-base +/- correction; do not raise retries. A pre-wheel283ms timing failure
and a test-driver SIZE + label mismatch are preserved; label normalization is now
corrected and regression-tested.12focused tests pass; no cohort credit.
Evidence: `.development-artifacts/vr-workflows/profile-wheel-validation.md`.

## Coarse wheel plus fine correction

NADOC_VR_FINE_LENGTH=1 enables at most one detent's worth of profiled single-base
+/- clicks after the coarse wheel; each must change exactly1bp and preserve cells.
Variable_fast VR-first passes59.8s: wheel35bp then7clicks→42bp, Confirm/Undo/cadnano/
save-reload504positions unchanged. Variable_deliberate fails before length control
on first paint target: three final ray misses29–31mm versus26mm hit radius.
No retry limit/noise changes; failures retained.15focused tests pass; both isolated
workspaces cleaned. Next resolve paint acquisition and remaining ideal controls
before final cohorts. Evidence: `.development-artifacts/vr-workflows/profile-length-validation.md`.

## Feedback acquisition: variable-deliberate VR-first pass

NADOC_VR_FEEDBACK_ACQUISITION=1 uses observed correct-cell hover continuously.
After the initial reaction interval, a full preset reaction interval of uninterrupted
hover permits clicking; noise keeps evolving until acquisition. This replaces the
endpoint-only decision for paint, records truncated vs planned duration and policy
version, and is explicitly an uncalibrated synthetic feedback-policy experiment.
A rejected final20%phase restriction and its failure evidence remain preserved.

Variable_deliberate now passes the VR-first roundtrip (~1.8m): all6cells within3
attempts each, wheel0→77→28→49bp,7fine '-' clicks→42bp, Confirm/Undo/cadnano/save-reload
504positions unchanged. Fixed a probe boundary preventing fine correction after
the third wheel drag; no fourth drag permitted.25focused tests pass,3workspaces
cleaned. No cohort credit; previous variable_fast used a different paint policy.
Evidence: `.development-artifacts/vr-workflows/profile-feedback-validation.md`.

## Visible menu activation and ISSUE-39

NADOC_VR_MENU_ACTIVATION=1 drives Tools→Inspect→Extrude with profiled menu reaches,
including framing-helper activations. Actual menu testing exposed two native gaps:
targetless Extrude was classified unsupported, and the menu omitted paint-tablet
initialization. It now requires configuration for an empty selection and shares
the existing tablet initializer with radial activation. Other tools retain their
selection requirements. Native regression covers empty/none Extrude and Bend.

Physical steady_fast VR-first roundtrip passes58.6s through visible menus without
semantic activation;26focused tooling tests and36native tests pass. Submitted
left-eye image reviewed: settings and paint tablet both open and visible. Still
ideal: tablet exit/centering and setup/placement gestures. UI review also shows
remaining generic OPTION/FLAG labels and developer-oriented preflight text to refine.
Evidence: `.development-artifacts/vr-workflows/menu-activation-validation.md`.

## Profiled Center Paint and Exit

ProfileControls now covers tablet controls without ideal aiming. Exit exports its
production hit rectangle; both actions require geometric hit plus lattice input
ownership. Center preserves the footprint; Exit must close the tablet.29focused
tests and36native tests pass. Steady_fast visible-menu VR-first roundtrip passes
59.3s through tablet actions, Undo and cadnano/save-reload. Variable_fast stops
earlier at menu Extrude: three rejected hits on adjacent Twist/Move Rotate items.
No high-variability tablet verdict. Setup/zoom and remaining workflow1motions are
still not fully profiled. Evidence: `.development-artifacts/vr-workflows/tablet-controls-validation.md`.

## Menu feedback and review publication

ProfileControls now supports the same sustained-hover feedback policy as paint.
Redundant Inspect activation is skipped. Steady_fast VR-first passes57.1s with
visible menu/tablet controls; variable_fast still fails Extrude acquisition at
37.5mm target height and~300mm controller distance.30focused tests pass.

Successful desktop roundtrip checks emit `review-part.nadoc` with the exact saved
bytes. Publish outputs with `uv run python -m tools.vr_workflows.workspace publish
--vr-first <artifact> --desktop-then-vr <artifact>` (either source may be omitted).
Publication deletes all old review parts, even edited files; validates all sources
before reset and rejects the editable folder as an input.18publication/control
tests pass. `vr-first.nadoc` is now published; desktop-first output pending.
Evidence: `.development-artifacts/vr-workflows/control-feedback-validation.md`.

## Larger Tools targets

Tools rows now have60mm height at default scale (previously37.5mm), with7.5mm
separation. A shared rectangle drives border/picking/audit/inspector export;
status text moved below the rows.36native tests pass. Initial steady trial failed
201ms playback lateness; retained retry passed the full VR-first roundtrip57.0s.
Both submitted-eye images and live layout audit confirm separated visible rows.
Variable_fast passed earlier Extrude acquisition and painting, then failed the
still-small minus length button after three reaches. No cohort credit.
Next improve actual settings controls without changing noise, retry or timing
policy; physical-headset comfort and desktop-window delivery remain unverified.
Serial browser smoke23/23passed; all temporary workspaces removed.
Evidence: `.development-artifacts/vr-workflows/menu-targets-validation.md`.

## Settings controls and explicit approach strategy

Settings primary/secondary controls now60mm at default scale, with -1 BP/+1 BP
and STRANDS/LIGATE labels for Extrude. Image review caught absent minus glyph;
ISSUE-40 fixes it with a glyph regression.36native tests pass; corrected steady
VR-first roundtrip passes56.3s. Variable_fast now commits successfully, but failed
Back acquisition at~77cm controller distance (entire workflow still fails).

`NADOC_VR_APPROACH_CONTROLS=1` enables an explicit synthetic operator strategy:
reach toward30cm from the current control along its exported panel normal, staying
on the current hand side, with unchanged noise/overshoot/duration and sustained
hover. This is a new diagnostic policy, not a learned population model or endpoint
snap. Ideal/noisy/applied paths, target position and policy are logged.34focused
tests pass; approach steady_fast VR-first passes57.3s. Final cohorts remain pending.
See `.development-artifacts/vr-workflows/settings-targets-validation.md` for all
trial outcomes, including failures. Setup/end/freeform motions still need profiling.

Approach four-preset diagnostic: steady_fast, variable_fast and steady_deliberate
passed; variable_deliberate failed final cell[1,2] after3reaches. Five cells correct.
Menu approach does not yet apply to paint; after Center Paint the hand remained
20–24cm below that cell and37–41cm distant. Next extend the same measured approach
to paint, then profile end/freeform/setup and run the fixed cohorts. Failed attempts
remain evidence, not replaced by passing retries. Policy fingerprint recorded in
`settings-approach-policy.json`; acceptance credit remains zero.

Serial smoke23/23passed; all seven physical trial workspaces plus smoke workspace
removed. just lint retains3unrelated baseline findings; no new frontend/backend
behavior this step, full suites not repeated. Goal remains active.

## Per-cell approach and less sensitive wheel

`NADOC_VR_APPROACH_CELLS=1` extends the same measured30cm normal approach to every
paint cell, including after Center Paint, and removes the ideal initial paint jump.
35focused tests pass. This resolved the sixth-cell diagnostic failure; the retained
next failure was wheel length0→56→28→63bp after3drags.

Wheel sensitivity now requires30mm travel per detent at default scale (was10.5mm);
honeycomb still advances7bp.36native tests include perturbation tolerance, signed
detents, real input ownership and controlled/flick release. A42bp drag is19.5cm;
physical comfort remains MV-38 debt. All four wheel-travel preset diagnostics now
pass VR-first, including native Undo and desktop/cadnano edit/save/reload. Variable
profiles used9/11paint attempts and7fine length clicks; steady profiles used6paint
attempts and one exact wheel drag. These are seed0diagnostics, not final cohorts.
Evidence: `.development-artifacts/vr-workflows/cell-approach-validation.md`.

Combined-profile-approach passes3.3m on the new revision, with steady menu/paint
profiles but still ideal blunt-end and freeform-placement gestures. Verified outputs
are now both published: `workspace/VR Testing/desktop-then-vr.nadoc` (19helices,
2frames,1554positions) and `vr-first.nadoc` (7helices,504positions). One helix in
each is the empty cell added in cadnano. Provenance:combined-review-publication.json.

New visibility debt ISSUE-41: native framed view has only82x64authored-pixel bounds,
largely end-on, despite passing the presence threshold. Desktop reload image is
useful. Improve ordinary view rotation/zoom and the visibility oracle, then complete
profile coverage and final cohorts. Smoke23/23passed; all temporary roots removed.

## Review visibility checkpoint (2026-09-23)

ISSUE-41 is resolved for the opt-in review path: `NADOC_VR_REVIEW_VIEW=1` applies
ordinary post-authoring grip rotation and bounded scaling; original captures remain.
Both eyes must show useful bounds, visible RGB and every expected placement cluster.
`NADOC_VR_DESKTOP_REVIEW=1` reuses the owned LiveSession and verifies actual X11
client pixels against the native mirror. Combined and variable_deliberate VR-first
pilots pass, including independent desktop/cadnano save/reload. Their temporary
workspaces are verified absent. Focused checks23passed. Report:
`.development-artifacts/vr-workflows/review-view-validation.md`.

These are observation gestures, not profiled authoring. Physical headset comfort,
controller trace delivery in these workflows, profiled end/freeform placement and
the fixed acceptance cohorts remain open. Zero final acceptance credit. Following
the reported editor crash, continue one bounded workload at a time; no automatic
editor/SteamVR/display restart. Current read-only checks do not establish crash cause.

## Profiled freeform placement (2026-09-23)

`NADOC_VR_PROFILE_PLACEMENT=1` replaces the ideal freeform placement jump with
a20Hz noisy reach to an explicit position/quaternion. The shared profile input
retains requested wrist roll, reaction and overshoot; it neither ray-aims away the
roll nor pins the endpoint. Freeform capture records the actual applied pose.
All four presets have pure reach coverage; playback tests detect injected transport
error.40focused input/control/wheel checks pass.

Serial steady_fast combined pilot `combined-profile-placement` passes3.4m, including
default/end/freeform, native Undo, desktop/cadnano edit/save/reload and delivered X11
mirror checks. Freeform endpoint differs from intent by2.066mm/0.150deg; max
requested-to-applied position discrepancy0.00438mm. Capture pose equals last applied
sample; no endpoint snap. Actual freeform desktop has1104bright feature pixels and
100%match under existing tolerances. Both groups visibly present, not detailed
per-nucleotide legibility. Cleanup verified, idle viewer restored; no editor/SteamVR
restart or overlapping workload. `just lint` retains the same3unrelated findings.

Evidence: `.development-artifacts/vr-workflows/placement-validation.json` and
`combined-profile-placement/`. Remaining: fully profiled blunt-end actions; an
independent forward/inverse placement check connecting applied tracking pose to
saved cluster transform (current live telemetry lacks presentation matrix and
normalization); authoring trace delivery; fixed final cohorts. Zero cohort credit.
No production frontend/backend change in this step; main.js LOC delta0.

## Profiled blunt-end authoring (2026-09-23)

`NADOC_VR_PROFILE_END=1` enables the same controller preset for terminal acquisition,
menu navigation,21single-base length clicks and Confirm. Target is still the most
visible rendered far-end primitive; its depth determines the intended controller
volume center. The actual noisy endpoint is clicked once, never snapped. The exact
end owner must match before any commit; wrong-end or missed selections fail.

`menu_navigation.py` replaces duplicate painted-menu navigation and adds selected-end
activation without Inspect (which can discard the target). Identity is checked
across navigation; fresh paint still resets the tool and checks tablet opening.
34focused navigation/input/control tests pass, including lost-identity rejection.

`combined-profile-end` steady_fast pilot passes3.6m with default, blunt-end and
freeform modes, exact one42→63bp extension, unchanged source frame/transforms,
desktop/cadnano edit/save/reload and Undo/redo. End reach17samples,1.599mm/0.502deg
endpoint deviation; max requested-to-applied position error0.00710mm. Actual
default/freeform desktop mirror checks pass. Temporary workspace verified removed;
owned idle viewer restored. `just lint` retains3unrelated baseline findings.

Both checked review parts republished byte-for-byte to `workspace/VR Testing`,
replacing all prior part files per user policy. Sources/hashes/deletions:
`.development-artifacts/vr-workflows/end-profile-publication.json`; metrics:
`end-profile-validation.json`. Review files remain outputs, never oracle inputs.

No final cohort credit. Still needed: high-variability end/combined pilots; fixed
watchdogs sized for bounded deliberate actions; profiled empty-space target clear
and an explicit setup/observation policy; independent applied-pose→saved-transform
oracle; intended/actual trace delivery in authoring workflows; fixed80trial cohort.
No production frontend/backend change; main.js LOC delta0.

## User-requested stopping point and visible demo (2026-09-23)

Run `uv run python -m tools.vr_workflows.demo` from the repository; details in
[vr_workflow_demo.md](vr_workflow_demo.md). The command runs both workflows in a
headed browser with steady_fast simulated controls, reveals only its PID-verified
native mirror during VR, and adds six-second review holds outside measured reaches.
It resets old marked review parts (including edits), validates in an isolated
workspace, republishes checked outputs, and restores the owned idle viewer.

Verified demo: `.development-artifacts/vr-workflows/demo-kzp60tl9/`, both workflows
passed. Combined3.9m; second VR-first also passed. Actual desktop mirror matches
passed for all three authoring review stages. The new independent forward mapping
oracle passes on real captured freeform pose:0.00295mm position error and0.02575deg
orientation error versus saved cluster placement. Read-only native presentation
telemetry exposes normalization and display transform; no geometry or head pose
was changed to make the check pass.11oracle tests cover all canonical planes and
invalid transforms; total final focused tooling69passed, native36passed.

A separate variable_fast combined diagnostic passed4.1m before the new telemetry:
end selection deviated19.23mm/5.017deg yet selected the exact intended owner. Menu
attempts retained8default,8end,12freeform and4Undo misses before bounded acquisition.
These diagnostic retries remain visible and do not establish a population success
rate. Earlier `combined-placement-oracle` stopped on0%desktop pixel agreement;
its failure is retained. Its precise occluder/cause was not established afterward.
The headed demonstration explicitly raises its owned viewer and still requires
the original desktop pixel thresholds.

Cleanup: demo temporary root absent, zero leftover part files; published review
files are byte-identical to checked outputs (publication.json). Restored viewer
reports VIEW ONLY, focused/runtime connected, revision0, no controller path loop.
`just lint` still has3unrelated baseline findings; no claim of a clean broad suite.
Frontend main.js net change for this accumulated checkpoint:+4lines (thin wiring).

Stop here at the user's request after committing/pushing the checkpoint. The
persistent goal is unfinished: the fixed80trial acceptance campaign has zero
credited results; variable_deliberate combined execution and fixed action/setup
policy still need validation. Intended/actual path overlays are not yet integrated
into these authoring workflows, and physical headset comfort/legibility remains
manual debt. Do not relabel the successful demo as the required90%acceptance.
