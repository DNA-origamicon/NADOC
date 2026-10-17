# P5 desktop and part-VR repair UI audit

2026-10-15. Read-only UI audit; no browser, native build, solver, or app exercise.
Assemblies remain deferred by the user. Proposed implementation keeps `main.js`
unchanged and composes the controller inside the existing feature-log factory.

## Existing seams and gaps

| Area | Evidence / consequence |
| --- | --- |
| Desktop host | `frontend/src/ui/feature_log_panel.js` already composes `createFeatureLogVR`, handles timeline rows and loadout/part context, and is over 2,000 lines. Add a small controller/view seam; do not put the workflow inline. Its existing subscriptions/observer have incomplete teardown, so new modules must own their own cleanup. |
| Old edit gates | Snapshot `hasLaterSnapshot`/`editAllowed`, routing-child eviction/`REPLAYABLE_SUBTYPES`, and `generated_feature_fields.js::canReplayGenerated` still limit editing by recovery availability. Replace those conditions only for explicitly admitted native definitions; retain legacy recovery restrictions. A listed command kind alone does not establish admission of this particular definition. |
| Parameter form | `edit_feature_popover.js` is a reusable small modal with declared fields. Repair must produce exact typed `parameter_path` and `expected_old`, not submit the popover's merged parameter object or infer writable inputs from labels. `_generator.editable` is UI metadata, not replay authority. |
| Request transport | `api/client.js::_request` JSON-encodes every body, flattens structured failures into `lastError.message`, and automatically retries protected-loadout mutations on another editable loadout. Repair needs preserved typed error detail, `protectedRetry:false`, and a separate bounded raw-source upload path. |
| Metadata ordering | `api/design_revisions.js::acceptMetadata` can advance the observed revision without replacing geometry. Draft/source acknowledgements must use this pattern. `_design_response` excludes the full draft from `design` and returns a top-level summary, which the frontend currently ignores. Keep summary/proposal state separate from `currentDesign`; never merge a summary into the persisted draft schema. |
| Backend workflow | Saved-draft GET/POST, named-source inspection/raw upload, saved-draft evaluation, and the existing job inspect/cancel/commit lifecycle are implemented. See [draft API](../../part_repair_drafts.md). This audit found stale persistence/coating capability descriptions; the accompanying narrow correction describes those implemented boundaries without widening admission. |
| Replacement choices | `part_repair_selection.py` independently replays the prefix. Its catalog currently covers unowned gold/QD targets, free protein assets/attachments and typed rigid-copy IDs, at most 100 choices. Generated scopes, compound/owned selections and current routing-child kinds remain unsupported. Do not build choices from the displayed final model or run one solver per choice. |
| Comparison | Job inspection exposes compact changes and diagnostics, not candidate geometry. `/features/preview` seeks recovery history; it cannot display the independently regenerated repair candidate. No candidate projection currently exists. |
| Native VR | `ui/feature_log_vr.js` scrapes desktop button titles and supports edit/revert/delete/expand. `scene/vr_feature_log.js`, `backend/api/vr_feature_log.py`, and `native/vr_viewer/src/feature_log_panel.hpp` enforce that protocol, version/signature/sequence checks and busy state. A Repair button alone will not add a native action. |

## One shared controller, thin views

Add `frontend/src/features/part_repair_model.js` for pure state/diagnostic shaping,
`part_repair_controller.js` for lifecycle and requests, `ui/part_repair_panel.js`
for the desktop view, and `api/part_repair_endpoints.js` for endpoint adapters.
The existing panel factory injects store/API/context and exposes the controller's
compact view to its VR adapter. Avoid a second job manager or repair state machine.

Controller state is bound to document ID, part ID, active loadout, observed
revision, draft ID/generation and an in-memory request epoch. Server session
incarnation remains private. Document/loadout switches, history navigation and
dispose invalidate callbacks, polling and selection results. Cancel/discard of a
private candidate uses the existing job DELETE; draft discard is a distinct
metadata action. Persist neither candidates nor job readiness in browser storage.

Use a separate repair state slice/event to observe full-response summaries and
metadata acknowledgements. Metadata-only operations must not replace
`currentDesign`, fetch geometry, or trigger VR scene refresh. Add only a small
transport hook to retain structured error detail and acknowledge metadata in
the existing client; leave cohesive endpoint logic in its new module. Respect
the existing document request scope and use explicit origin `docId` on all calls.

The view should show, in order:

1. Published geometry status: unchecked, verified for the exact current source,
   stale, or failed replay. A loaded display is not automatically “last good.”
   Reserve “last verified” for a matching retained verification result; label
   historical recovery views as such.
2. The first failing feature and subsequent unevaluated boundary. Resolve stable
   `feature_id`, optional `child_id`, typed references and path tokens directly
   from backend diagnostics; preserve integer array indices and exact identities.
   Clicking a diagnostic expands/selects its actual row and input. Missing row
   identity is itself a stale-target diagnostic, not a guessed nearest row.
3. A saved proposal with explicit old/new input values. Backend-authorized direct
   ID slots offer selection jobs; other supported scalar/structured inputs use
   reviewed field adapters. Unsupported inputs explain the missing adapter.
   Rebase presents per-action conflicts and never fills new expectations silently.
4. Source actions distinguish staging bytes named by proposed inputs from
   restoring bytes of a published binding. Inspect first, then upload original
   bytes with the exact receipt. Check `File.size` before reading, honor the named
   family limit plus the 8 KiB header limit, and use abortable raw octet-stream
   transport. No base64 data in action JSON. Restoration requires explicit rebase
   before evaluation; it does not confer readiness or change displayed geometry.
5. Evaluate/cancel, compact changes, explicit Apply, Rebase and Discard. Only a
   current ready job enables Apply. Saved `pending`/`unchecked` is never ready;
   expiry, source/draft edits, navigation and failed polling invalidate readiness.
   Commit retains the proposal; same-branch geometry Undo retains it too.

## Staged completion gates

**UI-1 — diagnostics and saved proposals.** Implement transport/detail preservation,
metadata ordering, controller/view, typed issue navigation, supported input editors,
selection jobs, source inspect/upload, draft lifecycle, evaluation/cancel and
compact changes. Wire native eligibility separately from legacy snapshot gates;
use cheap backend per-definition admission/field metadata where required, not a
duplicated native schema or a full proof on every panel render. Explicit Check
starts a job; ordinary selection/rendering never hashes or regenerates the model.
Gate: broken native definition can be saved, reloaded, repaired and explicitly
applied with no geometry change before commit; stale responses cannot enable Apply.

**UI-2 — visual comparison.** Add a separately reviewed, bounded, on-demand
projection of the existing private candidate, guarded by job/source/session/
revision/expiry checks. Derive render data outside the state lock with explicit
work/output limits; do not rerun the command or create another numerical job.
Use an isolated renderer/scene and dispose it on stale/cancel/close. Published
geometry remains the normal export/simulation source. Clearly distinguish
published, historical reference and proposed views; counts alone are not visual
comparison. Molecular engine upgrades retain the existing A/B atom/junction
authorization gate; generic repair UI cannot substitute a “safe” checkbox.
Gate: candidate comparison works without changing `currentDesign`, recovery
history, export, simulation or persisted files, including expiry during preview.

**UI-3 — part VR.** Expose controller action descriptors explicitly, rather than
extending title-string scraping. Version the JS/Python/native feature-log protocol
for Repair and proposal controls, preserving sequence/epoch/signature guards.
Native selection/status/action controls delegate to the same controller; detailed
text and file selection may open the existing VR desktop panel with clear status.
Do not claim a native file picker. Metadata operations must not refresh the scene;
one successful Apply performs the existing commit refresh. Update protocol tests,
generated sidebar catalog through its tool, and register a reusable tour in
`tools/vr_workflows/tour_catalog.py`. Gate: desktop and VR perform the same part
repair lifecycle, including cancel, stale events, navigation and teardown.

Consolidate native/legacy edit eligibility and shared endpoint error/revision
handling as those seams change. Retain domain-specific protein/cluster repair,
scientific-readiness actions and dependency-delete confirmation: those are not
duplicates of recipe repair. Update stale capability/editor comments. Do not
expand this slice into assembly parity or wholesale cleanup of the large panel.

## Verification and app/artifact constraints

Root serializes checks. Add pure model tests and jsdom controller/view tests for
typed paths, generation conflicts, explicit rebase, one poll loop, cancellation,
stale completions after part/loadout/session replacement, error details, raw-upload
limits, metadata acknowledgement without geometry updates and disposal. Preserve
existing `feature_log_panel_scroll`, `feature_log_vr`, `scene/vr_feature_log` and
revision-tracker cases. Extend native protocol tests for new actions and malformed/
stale messages; test first-error navigation and native-vs-legacy edit eligibility.

For app verification, use the isolated `frontend/playwright.config.js` backend
8002/frontend 5175 and a tiny generated native fixture. Exercise a broken reference
through save/reload, replacement choice, evaluate/cancel, compare/apply, cold check,
Undo and rebase; separately restore a pinned source. Reuse the document teardown
pattern from `e2e/vr_feature_log.spec.js`. Before any browser run inventory
workspace parts/project revisions, disabled session cache, playback cache, Vite
bridge credentials, native sidecars, screenshots/traces and temporary downloads;
ensure failure-safe cleanup and verify leftovers afterward. Prefix all created
parts/documents with `__e2e__` and keep compact results only.

`e2e/feature_log_revert.spec.js` currently hardcodes the user's backend port 8000
and a user example design. Migrate that test to the isolated API/document helpers
before including it in this workflow; its presence is not authorization to run it.

At this audit no app listened on 8000/8002/5173/5175. Neither Archive mount path
existed, and `.development-artifacts` resolved to a real system-disk directory.
No app exercise was attempted. Bulk captures, traces and native scratch must wait
for a verified Archive destination; do not silently fall back to this directory.
Frontend shipment still requires the repo's app/smoke gates or an explicit
`NOT VERIFIED IN APP` report and tracked manual-validation debt.

## CAD precedent and policy distinction

Onshape provides a view-only healthy history alongside the current part, highlights
broken selections, and recommends fixing the earliest failed features first. Its
reference replacement supports explicit one-to-one replacement and optional
downstream propagation; unsupported mappings remain explicit.
[Official repair documentation](https://cad.onshape.com/help/Content/Document/repairing.htm).
Imported CAD changes use an explicit Update action followed by regeneration and
repair of affected features.
[Official imported-CAD documentation](https://cad.onshape.com/help/Content/Document/working_with_imported_cad.htm).
These support the proposed visual separation and explicit replacement workflow.
NADOC's saved-proposal generations, bounded jobs, exact old-value expectations and
explicit rebase are local design choices; no automatic propagation is proposed.

## UI-1 implementation boundary

The input model, lifecycle controller and endpoint/response adapters are separate
frontend modules. The first foundation run passed 37 Vitest cases in five files;
the subsequent desktop/controller/editor and existing history/VR run passed 70
cases in eleven files. The first full frontend run exposed a summary null guard
issue, and app-path review exposed the real commit-response mismatch (ISSUE-87).
After those corrections, 82 focused cases passed; the full rerun passed 8,177
cases with one skipped across 708 files in 309.76 seconds. Subsequent review
found the default-document response identity mismatch: frontend null denotes
the backend's explicit `__default__` slot. The targeted baseline confirmed three
failures and seven passes in 779 ms (correct sentinel refused; absent/null server
identity accepted). The response comparison now requires that exact sentinel
without changing request context or headers; its focused/full reruns are pending.
No app exercise has run. `main.js` remains unchanged.

`feature_log_panel.js` now has a thin standard-part launcher and exact diagnostic
row highlighting. The modal requests a reviewed `/features/repair-inputs` catalog
only when the user selects a feature or failing input. It uses scalar controls,
fixed-size pose fields, reference-selection jobs and named original-source file
actions. There is no generic parameter/model JSON editor. Saving and source upload
acknowledge metadata revisions without replacing `currentDesign`; a metadata GET
at a different revision requires refreshing the design and cannot advance the
revision of stale displayed geometry.

The optional `expected_old_json` receipt stays an opaque string through frontend
action creation, updates and JSON serialization. This preserves Python's exact
old numeric representation, including integral floats and signed zero, while the
backend validates the receipt against its displayed value before its unchanged
exact-value comparison. The UI never parses the receipt to reconstruct numbers.

The controller binds asynchronous work to its original document, loadout,
revision and request epoch. Close, navigation, same-ID document reset, cancellation
and disposal remove private job readiness and abort pending requests. A saved
proposal never enables Apply. Input/source changes require a fresh evaluation;
published-source restoration and successful Apply retain the proposal and require
explicit rebase against the new base. Source replacement hashes only the selected
bounded file on explicit user action and uploads raw bytes after saved-proposal
inspection. No browser storage contains the candidate or proposal readiness.

Current limitations remain explicit: schema-invalid old definitions are not
admitted by the shared repair planner; numerical-contract upgrades require the
separate atom/junction review and are not executable from this panel; comparison
shows compact changes only. Existing ordinary feature Edit/recovery gates are
unchanged. Visual candidate projection, native VR repair protocol and assembly
work remain separate phases. The modal explains protected loadouts and historical
cursors rather than silently redirecting mutations to another loadout.

### Publication is distinct from display refresh

The real job commit returns a small `{job_id,status,revision,design_id}` receipt,
not a design. The controller retains that receipt before attempting display
refresh and immediately removes candidate readiness. The adapter privately reads
`/design`, `/design/geometry`, `/design/revision`, then the committed job on the
original document. It requires matching design/loadout/revision and committed
job/session guards, and the controller checks local context once more before
normal synchronization with embedded geometry. Neither read independently calls
the global `getGeometry()` or updates the revision watermark. If refresh fails,
the panel says publication succeeded and offers **Refresh committed result**;
it neither commits again nor cancels a published job.

A lost commit response retains a separate pending publication handle scoped to
its original document/job. The panel reports **publication status unknown** and
offers **Check publication status**; it does not describe the result as an
unapplied private candidate. Explicit inspection can confirm committed status
and continue the same refresh. A still-ready/running result alone cannot prove
nonpublication because commit decoding may be in flight outside the catalog
lock. Documented prepublication HTTP refusals remain non-ready and cancellable;
network/server failures never trigger automatic recommit. These handles are
transient UI state, never saved proposal readiness or persistent browser data.

This explicit four-read path relies on existing compatibility mutations advancing
the revision and on committed-job inspection rejecting session/policy replacement.
It does not add a permanent geometry-read cache or strengthen every legacy
mutation's ownership semantics. A later immutable display snapshot/owned
projection seam can consolidate the reads. Candidate comparison before Apply is
a different, nonpublishing operation: see [UI-2 design](repair_comparison_plan.md).

### Prepared app exercise and output inventory

`frontend/e2e/part_repair.spec.js` is prepared, not run. It creates only one named
`__e2e__part-recipe-repair` gold part in the isolated Playwright document, introduces
one explicit broken native patch reference in its in-memory export text, then
drives typed diagnostics, prefix choices, scalar edit, save/reload, private
evaluate/cancel/Apply, published verification, stale-base refusal and Undo.
Original float text stays intact so actual browser actions exercise exact-old
receipts. It does not open a user design or create external source files.

| Potential output | Owner / required cleanup |
| --- | --- |
| Own in-memory document and evaluation jobs | Spec `afterEach` closes the page, cancels tracked job IDs on the original document, then deletes that document. |
| Prefixed autosave `.nadoc` and `.nadoc-projects` revisions | Existing global teardown removes only proven test-owned prefixed parts and their complete test histories. Inventory before/after the actual run remains required. |
| Session snapshots | Disabled by the isolated backend configuration. |
| Playback cache | No simulation in this spec; existing config uses prefixed scratch, globally cleaned. |
| Bridge credential | Existing Vite close hook and Playwright teardown remove the isolated-port credential. |
| Failure trace/screenshot, browser temporary profile | Config reporter removes its report outputs; root must first route initial writes and browser scratch to verified Archive storage. No browser invocation while Archive is unavailable. |
| Downloads, external fixtures, native/simulation output | None requested or created. |

The full Vitest output audit found small existing cleanup fixtures in
`shared/e2e_project_cleanup.test.js` (`afterEach` removes temporary gzip/JSON),
loopback bridge credentials in `perf/viewer_test_server.test.js` (close unlinks and
asserts absence), normal `node_modules/.vite/vitest/<project>/results.json`/Vite
caches, and the durable compact native-placement failure journal. Experimental
filesystem module caching is off. No browser, video, coverage report, native
build or downloads are part of `just test-frontend`; the opt-in live-atom fixture
test only reads its named file and compresses in memory. Preserve the existing
placement incident/review gate and never erase its journal to obtain a pass.


### Final UI-1 automated checkpoint

After the default-document correction, root ran86 focused cases across12 files
(4.92 seconds) and the full frontend suite:8,181 passed, one skipped,708 files
(309.16 seconds). No frontend source changed afterward before checkpoint.
ISSUE-87 is fixed in automated integration; MV-45 app/smoke/headset debt remains.
See [compact evidence](validation_repair_ui1_p5.json).
