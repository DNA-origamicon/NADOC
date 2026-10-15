---
name: Feature Log Overhaul + Tabbed Sidebar
description: Architecture, critical files, and design decisions for the snapshot-bearing feature log, edit endpoint, broken-delta detection, and the three-tab left sidebar. Read before touching feature_log, mutate_with_feature_log, _seek_feature_log, or the left sidebar tab strip.
type: project
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---
# Feature Log Overhaul + Tabbed Sidebar (commit 873f3e6, branch feature-log-update, 2026-05-02)

## Current delivery status (2026-10-15)

The sections below retain earlier implementation context; use the latest
[implementation checkpoint](../docs/audits/feature_history_20261014/implementation.md)
for current availability and measured limits. P3's native DNA execution foundation
is implemented. P4 asset/attachment coverage, P5 repair UI and P6 trusted automation
enforcement remain incomplete; assembly work is explicitly deferred.

Portable `Design.repair_draft` proposals now persist across document/session,
loadout, project and package boundaries. Explicit metadata APIs support
create/update/rebase/discard, and ordinary responses expose a compact unchecked
summary. Draft metadata is excluded from replay and numerical authoring. A saved
proposal is never proof or publication authority. Canonical serialized-form
budgets prevent optional defaults from making a previously admitted draft
unloadable (ISSUE-84).

Explicit single-particle coating jobs are enabled within their measured bounded
scope; ordinary mixed-part coating routes are not covered. Registered batch
evaluation uses the existing isolated lifecycle, but its public availability gate
is still closed. Its first benchmark confirms that full-source undo cost cannot
be inferred from authoring-only capture: large excluded physical state and long
history need separate admission. Do not raise global capture limits, add proof
to render/scrub paths, or reuse a cached baseline while mutable aliases and
unclassified write paths remain. Private host policy/admission, exact-candidate
batch permits and a closed strict HTTP route table are implemented. Strict HTTP
refuses unknown routes before body acquisition and exposes only reviewed scalar
reads, empty creation and existing batch/verify jobs. Public batch stays gated;
immutable revision ownership and complete strict lifecycle remain open. This is
not authentication or a sandbox for unrestricted local Python.

An experimental ordinary free-protein importer records pinned original bytes and
separate import/placement inputs, but its server-owned gate remains false after
retained-history capture refusals. Existing ordinary import behavior remains
available. Its scalar-atom copy optimization preserves exact admission accounting;
no source deadline or GC policy was relaxed. Allocation-light private candidate
admission removes a redundant copy; a retained-protein refusal now has measured
45 ms generation-2 GC overlap during locked source isolation. Immutable strict
revision ownership is the next step after the closed HTTP boundary. Saved source
restoration has a real HTTP-to-cold-replay regression requiring explicit rebase.
Reviewed repair input metadata preserves canonical `expected_old_json` text
through JavaScript so integral floats do not falsely conflict (ISSUE-86). Actual
Node/HTTP draft save, reload, rebase and native preparation pass. Desktop workflow
integration is validating; comparison and native VR remain separate increments.

Focused tests and small in-memory qualification run serially. The Archive
filesystem is unavailable in this environment; broader suite, app, visual and
headset validation debt is recorded separately and must not be described as a
pass. The persistent goal remains active.

## Architecture review and hardening (2026-10-15)

See [architecture review](../docs/audits/feature_history_20261014/architecture_review.md)
for the persistent P3–P6 completion sequence and primary Onshape/SOLIDWORKS
precedents. The input-replay foundation remains sound, but the review found that
permissive native builders could skip missing targets and falsely verify a no-op.
Targeted batch/selection preconditions now reject those missing references with
typed parameter paths. Background proof uses one spawned process with bounded
shared-memory transport, terminating and reaping before releasing admission;
sync proof and edits retain cooperative deadlines. Join records reference-only
preview orientation choices and explicit precursor identities, preserving the
displayed native tether without relying on process set order. Reproducibility, reference
integrity, scientific validation and useful editability are distinct claims.
Opaque legacy `connectivity-core` receipts remain unverified; new generation now
emits native path/routing commands. Keep broken
definitions repairable, reserve full proof for explicit/background work, and
keep assemblies deferred. Consult the implementation ledger for subsequent fixes.

## Native recipe continuation (2026-10-15)

P3 plus current P4 input/attachment slices now has 115 versioned kinds (with method/action restrictions), pure native
builders shared by routes and proof, source-based continuation references,
thread-local deterministic routing IDs, actual-failure cascade analysis, and one
independently rebuilt prefix retained per edit. No saved outputs are proof inputs.
Generated ordinary DNA steps use the same builders with versioned typed part
scopes. Sparse planar/curved branches now separate seed, numeric path, crossover
constraints, section routing, curvature encoding and optional budget fitting.
Native semantic no-ops remain in the recipe. Seeds author their stable default
cluster before publication; response-time legacy normalization must not add an
unrecorded cluster. Independent-section seed/bounded-route contracts are the
foundation for the now implemented joined and connectivity compilers. Their
numeric inputs regenerate paths, routing and explicit Joins; budget fitting
checks that all retained Join sites, bonds and owners survive unchanged. CPD
conversion/relaxation uses explicit native source and pinned template/engine
contracts in separate 180-second evaluation jobs. Ordinary proof still rejects
expensive execution after cheap reference checks. The real CPD fixture has an
explicit imported topology and correctly remains `reproduced_import`. Preflight
photoproduct authoring remains supported. P3 is the DNA execution foundation;
full generated asset/attachment histories remain unverified. Asset/NP/duplex work is P4, UI repair is
P5, strict agent enforcement is P6; assemblies remain deferred.

P4a adds strict uncoated gold particle create/patch/delete using existing native
builders. Diameter/pose/gizmo inputs and stable particle identity are retained;
owned DNA/decorations/connections are outside this slice. Legacy same-kind rows
without `nanoparticle_version` remain unverified. Cold proof, early parameter
editing, cascade/undo and existing particle workflows pass focused checks.

P4b adds portable SHA/length-verified `input_sources`, a revision-checked pinned
PDB import endpoint, unowned free/overhang placement commands, and explicit
duplex lifecycle/sync plus bounded native relaxation. Whole-part import provenance
stays `reproduced_import`; unavailable bytes are unverified repair targets, never
cascade reasons. Scoped replay preserves source tables and uses typed historical
relocation definitions without treating them as live geometry. Native roots skip
legacy load/response inference; builders must author default clusters explicitly.
Project blobs are optional derived caches; portable inline inputs remain authority.
P4c adds small native protein conjugation plus explicitly owned constrained
move/visibility/delete, unbound thiol graft create/replace/delete, and pinned
quantum-dot catalog inputs with native diameter/pose edits. Existing operation
kinds use strict discriminators without adding model fields. The shared identity
module is in duplex numerical pins; prior pins are not silently upgraded.
Document reads/decompression are bounded separately from proof capture, and
explicit inactive-loadout source audits retain broken drafts with typed warnings.
Ordinary edits do not run those audits. Further import/decoration families,
large-asset capture qualification and physical provenance remain P4 work.
P4d adds exact-ownership unbound thiol particle motion/resize and bounded pinned
single-chain aptamer import. The unchanged importer reconstructs deposited sites
from captured PDB bytes; provenance remains imported. New-session imports use
the shared atomic initial-design boundary, including legacy imports. Admission
is 150 KB/1000 first-model atom records; whole-document capture can still refuse
on its independent cooperative time/node/byte bounds. Benchmarks retain those
refusals; no proof is added to ordinary edits. Typed rigid copy and larger coating
capture are separate increments. Existing sulfur-local resize behavior is
reproduced unchanged, without claiming chemical validity of that behavior.
P4e adds strict same-part rigid copy of unowned free proteins and undecorated
gold/QD particles, using typed source/output identities and native placement
formulas. The host-owned API requires expected document/revision; 16 elements
and 4000 selected protein atoms bound work. No DNA calculation or unselected
asset clone occurs in the pure copy builder. Frozen clipboard remains legacy.
Coating experiments justify only a prospective explicit single-coating job;
ordinary capture budgets are unchanged. P5 pure repair/explicit engine-upgrade
foundation is starting in parallel with remaining P4 contracts; UI/jobs are not
yet wired. New copy identity protection changes duplex pins conservatively.

`part_recipe_capabilities.py` exposes API/editor limitations explicitly. No new
frontend controls were added. Long jobs evaluate privately, omit candidates from
polling and commit once with document/revision/cancel/expiry checks. Input,
recovery and candidate retention limits are not hard process heap caps. See the latest continuation in
`docs/audits/feature_history_20261014/implementation.md` and its validation JSON.
Native regeneration must re-encode recovery data; cluster membership setters
before a later payload must not erase that payload's new inherited helices.
`part_overlay_recovery.py` handles this without executing proof on scrub paths.

## Standard part history foundation (2026-10-14)

The user explicitly deferred assembly history implementation until needed; it
must not block standard-part validation work. The current sequence and deferred
ledger are in `docs/audits/feature_history_20261014/implementation.md` and
`assembly_deferred.md`.

`api/feature_recording.py` now owns failure-atomic snapshot/minor recording,
including restore of full bounded undo/redo, revision and request markers on
callback, reconcile, encode/diff, validation or publication failure/cancellation.
Undo/revision publish only after validation. This preserves editable drafts and
the existing single design copy; legacy callbacks still run under the state lock.
It is not a pure isolated evaluator or a history certification gate.

`core/feature_registry.py` declares six snapshot and 14 minor executors;
`api/part_feature_commands.py` resolves their existing schemas/builders. Crud
entry points remain compatibility adapters, and dependency replayability derives
from the registry. `/design/features/capabilities` exposes executor availability,
explicitly not reproducibility certification. Frontend edit schemas are unchanged.

Unused payload clearing/accounting, the old eviction alias, obsolete budget
constant and unused delta-type set were removed. Part recording no longer calls
the no-op eviction hook; the hook remains for the deferred assembly adapter.
Tests assert retention directly instead of monkeypatching an inert budget.

## Sweep edits after downstream work (2026-10-09)

Sweep Edit is available after snapshots and Fine Routing. `sweep_history.py`
prepares the same candidate for preview and commit; `core/sweep_edit.py` maps
internal domain cuts proportionally (rounded to whole bp), preserving traversal,
strand/connection IDs and signed terminal resize offsets. A 10 bp inline overhang
remains 10 bp. Automatic curvature marks are regenerated around retained routing;
authored mark overrides survive. Existing sequences survive with review warnings
when lengths change. Crossovers retain their authored connections with a register
review warning; collapsed domains reject the candidate without changing the design.

Deformed continuations and attached sweeps retain their shape/length via rigid
`sweep-follow:` poses at their saved source cross-section, including chained
attachments. Their bp spans and source bp parameters shift together to retain
ordinary backbone continuations. The previously evaluated local helix phase is
retained so index rebasing cannot twist a rigid extrusion. Saved pre/post snapshots
and routing child diffs are rewritten so seek/revert do not resurrect old geometry.
The topology snapshot substitution restores these generated attachment poses.
Fine Routing diffs now include OverhangSpec membership for resized-end substeps.

The editor displays candidate backbone paths (including nicks and overhangs) and
helix axes only for the edited sweep and helices whose axes move with it. The
preview masks those helices and their connection arcs through the normal renderers and restores them on
cancel/error; independent geometry retains its ordinary colors, representation,
and visibility. Point cross-sections match native VR: opaque linear-RGB teal
(.25,.7,.78), selected gold (1,.87,.5), hull plus 16-segment helix rings. Changing footprint/strand
creation/attachment options with downstream features is rejected; this edit path
changes the sweep path and orientations. Evicted routing snapshots remain a
reconstruction limit. Regression: `tests/test_sweep_edit.py`,
`frontend/e2e/sweep_edit.spec.js` (isolated sweep-edit Playwright config).

## Desktop live sweep feedback (2026-10-09)

Desktop point translation and orientation now use `sweep_live_path.js` and
`sweep_live_preview.js`: a display-only natural/Hermite cubic with transported
frames and interpolated roll, based on the native VR sampler. Input is coalesced
into animation frames. A fixed GPU path buffer and at most 4096 cloud points
replace detailed tubes while a draft awaits its debounced server preview.
The cloud is bound once per authoritative response; outside-span offsets stay
fixed and `edit_attachment_groups` follow their root start/end frame rigidly.
Independent geometry retains normal rendering. Authoritative geometry and
warnings return when input settles; epoch checks reject obsolete replies and
Confirm stays disabled until the current draft has a valid server result.
Cancel disposes the pending frame and restores normal visibility. The local
cloud is approximate display feedback, never saved topology or validation.
`frontend/e2e/sweep_live_check.js` holds server replies while dragging the actual
gizmo, checks current path endpoints and buffer reuse, and saves frame timing.

## Autogenerated scrub-path markers (2026-10-09)

Every generated native history entry and Fine Routing child retains
`autogenerated_group_id`, outside operation parameters. The rail uses sunset
orange dots (#f28c45), connected only between adjacent entries of the same run,
with the tooltip “This feature was autogenerated.” Manual entries retain their
normal ticks. `ui/autogenerated_feature_rail.js` also recognizes legacy generator
snapshot metadata, bounded native carrier operations and the leading sweep.
Provenance survives persistence; it does not change feature replay or geometry.

## Native VR history rail (2026-10-08)

October 9 refresh fix: `vr_feature_log.js` uses `createVRCommitRefresh` with the
current store design and API revision watermark after the desktop seek. Display
settings from `_vrCompanionState()` are not a valid `/vr/scene-refresh` request:
the endpoint requires `expected_design_id` and `expected_revision`, otherwise
it returns 422 after the desktop has already changed. Regression coverage uses
the production adapter and actual browser history event dispatch in an isolated
part, with intercepted VR transport to preserve the user's headset session.
Debug → VR Tours & Tests → **Feature history · desktop-to-VR refresh** runs it
(`python -m tools.vr_workflows.history_refresh_check --validate`). This checks
browser geometry and publication identity; it does not claim controller motion
or physical headset visibility.


`feature_log_vr.js` exposes the actual desktop rows and action buttons to the
versioned VR bridge. Native uses an independent scroll rail and a state rail
that seeks only on release. F0, routing sub-positions, selected assembly parts,
assembly history and configurations route through existing handlers. Edit,
revert and delete dialogs/editors open on the VR desktop surface; desktop
availability and dependency checks remain authoritative. History changes refresh
the native scene. See `docs/vr_sidebar_menus.md` and `MV-42` for physical review.

## Scrubber preview and readiness (2026-10-08)

Interactive design seeks now use `routes_feature_log.preview_features` followed
by the normal seek with a revision-bound preparation token. `feature_seek.js`
controls the thumb ring and edit lock; `feature_seek_preview.js` displays sampled
helix paths until the editable response is applied. Queued obsolete previews
never commit. Selected assembly parts use a read-only local-axis preview plus
the existing shared-source commit/inline geometry path. Preview is display-only.

Revision-acknowledged seeks omit history bodies only when the client has complete
history; the position/cluster fast paths merge those bodies. Cold/stale requests
and other replace-response callers still receive full bodies. Geometry generation
batches native slab quaternion conversion without changing the pose authority.
Details and benchmark entry point: `docs/feature_evaluation.md`.

## Generated designs use ordinary operations (2026-10-08)

New generator runs use ordinary **Sweep** or additive **Extrude segment**
authoring, Auto Scaffold (seamed), native bend entries where needed, Full Autostaple,
Fine Routing loop/skip and nick children, scaffold/staple sequencing, overhang
extrusion/sequencing/rotation, cluster creation/moves, and nanoparticle pose and
connection operations. `generated_commands.py` compiles the planner's chosen
parameters into those native history types; v2 provenance is not a custom editor.
Standard feature editing/revert rules apply. Old v1 saved generator entries retain
their dependent rebuild editor; no saved user files are migrated automatically.
Native cluster-creation entries now retain an optional full creation snapshot,
including duplex ownership and parent membership. Seek reconstructs active groups
before pose replay; v2 snapshot baselines also restore the original pre-generator
groups. This preserves attachment parenting at every construction boundary.

Audit of `4NP_gen_test_aligned.nadoc`: “Create curved rod bundle” concealed an
ordinary solid cross-section extrusion, and “Curve rod through nanoparticle path”
concealed many ordinary bend windows. Curvature marks are reproducible using
manual insert/delete commands; the existing Apply Deformations command is **not**
equivalent because it rounds each short bend window independently. The generator
carries fractional counts across windows, then applies the selected ordinary marks.

Potential general tools, not missing molecular primitives: a multi-point planar
path planner, continuous-curvature loop/skip allocation, and a fixed-center
attachment pose fitter. The existing NP Relax command can move particle centers
and must not be substituted for the fixed-center search. Its selected rotations
are now explicit ordinary overhang/cluster/particle edits.

Generation progress is request- and document-scoped (`generation_progress.py`),
polled only while the popup is working. It reports actual scaffold routing,
staple sequence/nick/crossover/growth stages, attachment construction/fitting,
validation, history commit and display geometry. Percentages are stage milestones,
not an estimate of remaining time. The final 100% UI update follows response application.

## Pattern features (2026-10-04)

Tools → Linear Pattern creates a row or a 2D grid of whole-helix clusters. Each direction has X/Y/Z or Custom with XYZ vector fields, signed spacing in nm, and an instance count including the original; the total is capped at 128. Custom vectors are normalized, must be finite and nonzero, and must be nonparallel for a 2D pattern. Additional disjoint clusters can share the pattern. The panel separates Clusters, Direction 1, Direction 2, and Info with borders; the cluster list scrolls. Creation and editing share controls with explicit ±1 nm and ±1 instance steppers. Circular and linear creation reuse `backend/core/pattern_copy.py`, preserving canonical cells, independent frames, and composed source poses/deformations.

Both pattern kinds have feature-log edit dialogs. `backend/api/pattern_features.py` rebuilds the saved pre-state, keeps surviving copy IDs (including older circular patterns), rewrites the existing entry, and rebases independent later snapshots. Creation and edits are each one undo step. Later absolute cluster moves survive edits; seek before the move restores the pattern placement. Edits that invalidate dependent downstream features return a conflict without modifying history. Copying remains scoped to part-owned whole-helix clusters; domain-specific/nucleotide poses retain the copy engine's explicit rejection.

Regression coverage: `tests/test_linear_pattern.py`, `tests/test_circular_pattern.py`, `frontend/src/ui/linear_pattern_panel.test.js`, and `frontend/e2e/linear_pattern.spec.js`.

## What was built

**Snapshot system.** Added 4th variant `SnapshotLogEntry` to the `FeatureLogEntry` discriminated union ([backend/core/models.py](backend/core/models.py)). Every snapshot stores BOTH `design_snapshot_gz_b64` (pre-state) AND `post_state_gz_b64` (post-state) as gzip+base64 of `design.model_dump_json()` with `feature_log` and `feature_log_cursor` stripped to prevent recursion. 5 MB rolling budget enforced by `_evict_oldest_snapshots_if_over_budget` — newest snapshot is NEVER evicted (revert must always work for the most recent op). Both pre+post are evicted together; entries remain in the log so historical labels stay visible (`evicted=True`, payload cleared).

**State-layer chokepoint.** `mutate_with_feature_log(op_kind, label, params, fn)` in [backend/api/state.py](backend/api/state.py) is the canonical wrapper for snapshot-emitting ops. Captures pre-state, runs `fn(active_design)` (which may return new Design or mutate in place + return MutationReport), reconciles cluster membership, captures post-state, appends entry, validates, pushes undo. Returns `(design, validation_report, snap_entry)`.

**13 endpoints converted** (in [backend/api/crud.py](backend/api/crud.py)):
- 8 auto-ops: `auto-scaffold`, `auto-scaffold-seamed`, `auto-scaffold-seamless` (+ advanced variants), `auto-break`, `auto-merge`, `auto-crossover`, `create-near-ends`, `create-far-ends`
- 2 overhang-bulk: `clear_all_overhangs`, `generate_all_overhang_sequences`
- 5 extrusion: `bundle-create`, `bundle-segment`, `bundle-continuation`, `bundle-deformed-continuation`, `overhang-extrude`

The auto-scaffold variants share a `_run_auto_scaffold_with_feature_log` helper that threads the algorithm's `result` object out via a closure (so `result.warnings` etc. reach the response). The extrusion routes have per-op pure builder helpers (`_build_bundle`, `_build_extrude_segment`, etc.) that are reused by both the live endpoint and the edit endpoint.

**`bundle-create` resets to empty Design first** so its snapshot's pre-state is the canonical empty workspace — seek to F0 (position == -2) yields an empty design regardless of what was loaded before.

**Undo navigation boundaries (2026-09-06).** Native/caDNAno/scadnano/PDB replacement imports, file loads, new documents, flattened-assembly loads, and recovery establish atomic baselines through `load_design`/`load_assembly` (recovery also clears existing stacks). Do not use `clear_history(); set_design(...)`: the edit setter immediately pushes the previous file back onto undo. Branch navigation clears undo/redo while retaining the same project's observed save heads; Save As clears source-project history. Undo/redo retain the current workspace identity path/signoff instead of restoring obsolete persistence metadata. PDB merging remains an undoable edit and preserves earlier edits. Regression: `tests/test_undo_boundaries.py`; `frontend/e2e/undo_document_boundaries.spec.js` checks Hinge replacement import → empty undo/redo in the cadnano editor.

**Snapshot-aware seek.** `_seek_feature_log(design, position)` calls `_seek_snapshot_base(design, position)` to substitute topology-bearing fields (helices, strands, crossovers, overhang_connections, extensions, photoproduct_junctions, forced_ligations) from the most-recent non-evicted snapshot's POST-state at-or-before `position`. For positions before the first snapshot, falls back to the FIRST snapshot's PRE-state (the F0 baseline). Then the existing delta-replay logic runs on top, rebuilding deformations/clusters/overhangs from log entries 0..position. The geometry-batch endpoint (used by animation playback) calls `_seek_feature_log` per requested position, so animations automatically support seeking through snapshots.

**Why both pre AND post:** seek is destructive (writes the seeked-to state to active_design), so we can't recover "latest topology" from the live design after a back-seek. Storing post-state on every snapshot is the cleanest fix. Cost is ~2× snapshot bytes but the eviction budget handles it.

**Revert + edit endpoints.**
- `POST /design/features/{i}/revert`: decode pre-state, truncate log to entries before `i`, push prior state to undo. Returns 410 if the snapshot was evicted, 400 if not a snapshot entry.
- `POST /design/features/{i}/edit`: the original snapshot replay path is for extrusion op_kinds (`bundle-create`, `extrude-*`, `overhang-extrude`). Validates new params against the original Pydantic body class via `_edit_dispatch_run`, replays the op against the entry's pre-state, splices the updated entry (re-encoded pre+post) into the log. Refuses with 409 if any later snapshot entry exists (revert-and-rerun model). Refuses with 400 for auto-op snapshots (those should be reverted and re-run via the original UI).

**Frontend feature log panel** ([frontend/src/ui/feature_log_panel.js](frontend/src/ui/feature_log_panel.js)):
- Snapshot entries render with ◆ icon, params summary tooltip, amber `↶` revert button, and `✎` edit buttons for supported kinds, including circular and linear patterns. Extrusion edits use the schema-driven popover; pattern edits use `pattern_feature_editor.js`. The full updated params dict is sent to the edit endpoint.
- Broken-delta UI markers: deformation entries with no `op_snapshot` whose `deformation_id` is missing from `design.deformations`, cluster_op entries whose `cluster_id` is missing, and overhang_rotation entries where ALL `overhang_ids` are gone — render with a ⚠ icon + amber muted label + tooltip explaining the cause. Detection is frontend-only (no backend schema field).

**Animation keyframe picker** ([frontend/src/ui/animation_panel.js](frontend/src/ui/animation_panel.js)) now shows descriptive labels for snapshot and overhang_rotation entry types (was just `F${i+1}` for unhandled types). Snapshots show their `entry.label` (e.g. "Auto-scaffold") with `(evicted)` suffix when applicable.

**Empty-workspace UX.** `_seek_feature_log` to F0 may transition the design from non-empty → empty, or revert may transition empty → non-empty. Two symmetric subscriptions in [frontend/src/main.js](frontend/src/main.js) handle these:
- non-empty → empty: hide slice plane (with full teardown — minimap, highlights, slice menu toggle), show workspace.
- empty → non-empty: hide workspace + slice plane (with the same full teardown), reset mode indicator.
The in-tool createBundle cleanup at the createBundle callsite still runs first for its branch (it sets `currentPlane`/`unfoldHelixOrder` bookkeeping); the new subscription is idempotent and catches every other path (seek F0→F1, undo, edit-feature, file load).

**Tabbed left sidebar.** Three tabs (Feature Log / Dynamics / Scene) on a vertical strip that's always visible. `setActiveTab(tabId)` implements click-to-toggle (active tab clicked while expanded → collapse; collapsed click → expand+switch; different tab click while expanded → switch content). `toggleCollapsed()` is the dedicated arrow-button handler that flips collapse without changing activeTab. State persists to `localStorage` under key `nadoc.leftSidebar.v1`.

**Sidebar content assignments:**
- Feature Log tab: `#feature-log-panel`
- Dynamics tab: `#animation-panel`, `#cluster-panel`, `#joints-panel`, plus relocated `#physics-section`, `#fem-section`, `#oxdna-section`, `#md-panel` from the right panel (322 lines moved). Right panel now hosts only property/selection/edit panels.
- Scene tab: `#camera-panel`, `#assembly-panel` (lives permanently here; assembly-mode entry/exit just toggles its display + auto-switches to Scene via `_leftSidebar.setActiveTab('scene')`)

**Sidebar styling:** vertical centering via `justify-content: center`. Tabs styled like buttons (filled bg `#161b22`, border `#30363d`, border-radius 6px, blue accent `#1f6feb` when active, subtle box-shadow). Dedicated circular `#left-tab-toggle` arrow at the top of the strip (▶ collapsed / ◀ expanded with matching tooltip).

**`_setLeftPanelEnabled(enabled)`** ([main.js:2761](frontend/src/main.js#L2761)) disables both the tab buttons AND the toggle arrow when locked (assembly editor mode); CSS `:disabled` selector handles the visual dimming.

## Critical files

- [backend/core/models.py](backend/core/models.py) — `SnapshotLogEntry`, `SnapshotOpKind` literal union (14 entries).
- [backend/api/state.py](backend/api/state.py) — `mutate_with_feature_log`, `encode_design_snapshot`, `decode_design_snapshot`, `_evict_oldest_snapshots_if_over_budget`, `_snapshot_total_bytes`, `MAX_SNAPSHOT_BUDGET_BYTES = 5_000_000`.
- [backend/api/crud.py](backend/api/crud.py) — endpoint conversions, `_seek_snapshot_base`, `_seek_feature_log`, `revert_to_before_feature`, `edit_feature`, `_edit_dispatch_run`, per-op pure builders (`_build_bundle`, `_build_extrude_segment`, etc.), `_run_auto_scaffold_with_feature_log`.
- [frontend/index.html](frontend/index.html) — `#left-panel`, `#tab-content-{feature-log,dynamics,scene}`, `#left-tab-strip`, `#left-tab-toggle`.
- [frontend/src/main.js](frontend/src/main.js) — tab controller (`_leftSidebar` closure, `window.__leftSidebar`), `_setLeftPanelEnabled`, assembly-mode entry/exit, empty/non-empty transition subscriptions.
- [frontend/src/api/client.js](frontend/src/api/client.js) — `revertToBeforeFeature(index)`, `editFeature(index, params)`.
- [frontend/src/ui/feature_log_panel.js](frontend/src/ui/feature_log_panel.js) — snapshot rendering, revert/edit buttons, broken-delta markers.
- [frontend/src/ui/animation_panel.js](frontend/src/ui/animation_panel.js) — keyframe picker labels for snapshot + overhang_rotation.
- [tests/test_feature_log_snapshot.py](tests/test_feature_log_snapshot.py) — 18 tests, 1 skipped.
- [tests/test_crud.py](tests/test_crud.py) — `test_load_preserves_native_absolute_positions` regression.
- [frontend/e2e/feature_log_revert.spec.js](frontend/e2e/feature_log_revert.spec.js) — Playwright revert + save/load round-trip spec.

## Design decisions worth remembering

- **Snapshots are PRE+POST**, not just one. Pre is the revert target; post is the seek-forward target. Both evict together.
- **Edit is for extrusions only.** Auto-op edits = revert + re-run via original UI. Backend dispatcher in `_edit_dispatch_run` enforces this by raising 400 for unknown op_kinds.
- **Edit refuses when later snapshots exist** (HTTP 409). Replaying an early extrusion would invalidate later snapshot pre/post payloads against changed topology — too complex to validate. User must revert first.
- **Bundle-create wipes prior design** to make F0 = empty workspace deterministic. Old feature_log is lost on bundle-create (consistent with the existing "fresh start" semantics of the endpoint).
- **Seek is destructive.** Each seek writes the seeked-to state to active_design (existing behavior). Snapshot-aware seek is non-destructive ONLY because both pre+post are stored — the live `design.strands` no longer needs to be the source of truth for "latest topology."
- **Tab strip is OUTSIDE `#left-panel`** (sibling, not child) so it stays visible when `#left-panel.hidden` collapses to width 0.
- **`#assembly-panel` no longer reparents.** Lives permanently in `#tab-content-scene`. `_enterAssemblyMode` calls `_leftSidebar.setActiveTab('scene')` and toggles display via the existing `subscribeSlice('assembly')` wiring. The previous `insertBefore(asmEl, clusterEl)` would silently fail since they no longer share a parent.

## Per-sub-step Fine Routing revert/delete (2026-05-25)

When a `RoutingClusterLogEntry` ("Fine Routing") is expanded in the panel, each child sub-row now carries its own ↶ revert and × delete button (in addition to the cluster-header pair). Backed by an optional `sub_index` query param on the existing routes — no new routes:

- `DELETE /design/features/{i}?sub_index=j` → `_delete_routing_child` in [crud.py](backend/api/crud.py): rebuilds the cluster's post-state by replaying the *surviving* children on top of `pre_state`, re-encodes, leaves the cluster in the log as the topology anchor, then `_seek_feature_log`. Deleting the **only** child removes the whole cluster AND must `_topology_substitute(temp, rebuilt)` before seek — once the cluster (sole payload) is gone, `_seek_snapshot_base` has no anchor to roll topology back to. Uses `_design_replace_response` (matches seek/undo per LESSONS C3).
- `POST /design/features/{i}/revert?sub_index=j` → `_revert_before_routing_child`: hydrate `pre_state`, replay `children[0..j-1]`, truncate log to `[0..i-1] + [cluster-with-j-children]` (re-encoded post). `sub_index=0` drops the whole cluster (== full-cluster revert). Like the top-level revert it also drops all later top-level entries.
- Joint indicators: extracted `_reconcile_cluster_joints_between(design, from, to)` — migrates live `cluster_joints` from one design's joint set to another's (seek never replays joints). The old full-delete joint-inversion block now calls it as `(temp, post, pre)`. Child-delete calls it as `(temp, old_post, rebuilt)`.
- Evicted cluster (no `pre_state`) → 410; unreplayable subtype mid-cluster → 422 ("revert/delete the whole cluster instead"); out-of-range `sub_index` → 400.
- Client: `deleteFeature(index, subIndex=null)` / `revertToBeforeFeature(index, subIndex=null)` append `?sub_index=`. Panel sub-row buttons are gated OFF in assembly-part / part-patch contexts (those edit embedded designs that the active-design endpoints don't touch); cluster-header controls remain there.
- Collapse UX: expanded clusters get a top "Collapse Fine Routing (N)" handle + a clickable purple spine connecting it to the bottom chevron (so a 100-row cluster folds from anywhere). [feature_log_panel.js](frontend/src/ui/feature_log_panel.js).
- Tests: 12 in [tests/test_feature_log_clusters.py](tests/test_feature_log_clusters.py).

### Diff-based reconstruction (2026-05-25, supersedes replay-only)

The replay-based reconstruction above only worked for the ~14 op subtypes with `_replay_minor_op` builders. Real Fine Routing clusters are dominated by non-replayable ops (ligate, crossover-move, strands-color-bulk, helix-reorder/extend, forced-ligation-*, strand-add, …), so per-step revert/delete 422'd on them. **Now each minor edit records a compact content DIFF (before→after, post-reconcile) — captures ANY op type, no replay needed.** Plan: `~/.claude/plans/let-s-focus-on-the-peppy-starfish.md`.

- **[backend/core/design_diff.py](backend/core/design_diff.py)** (NEW): `encode_child_diff(pre,post)→(added_b64,removed_b64,modified_b64,size)`, `apply_child_diff_forward(anchor,...,*,defensive=False)→(Design,warnings)`, `is_diff_child(child)`. id-keyed per-field diff over `_DIFF_FIELDS` = helices/strands/crossovers/forced_ligations/extensions/overhang_connections/photoproduct_junctions/**cluster_joints** (joints in the diff → the legacy `_reconcile_cluster_joints_between` is a no-op on the diff path). Mirrors the assembly diff in [assembly_state.py](backend/api/assembly_state.py).
- **Model** ([models.py](backend/core/models.py)): `MinorMutationLogEntry.diff_{added,removed,modified}_b64 + diff_size_bytes`; `RoutingClusterLogEntry.diffs_evicted`. All-three-empty diffs = legacy entry → replay fallback.
- **Capture** ([state.py](backend/api/state.py) `mutate_with_minor_log`): `before` (the deep copy taken before `fn`) is ALWAYS the pre-child boundary (== cluster pre_state for child 0; == prev child's post for appends). Diff captured AFTER reconcile + ligation-retry, so it includes those effects. Eviction (`_payload_total_bytes`/`_clear_payload`) counts child diffs and clears them with pre/post (`diffs_evicted`).
- **Reconstruct** ([crud.py](backend/api/crud.py)): `_state_at_child_boundary(entry,k)` = decode pre_state + forward-apply diffs 0..k-1 (legacy children → replay, else 422). **CORE INVARIANT: reconstruction never re-reconciles** (diffs already include reconcile). Revert uses non-defensive prefix; `_delete_routing_child` forward-applies the tail j+1.. **defensively** (deleted step's dependents may dangle → skip-absent-remove / re-add-absent-modify, collect warnings). Best-effort warning = defensive anomalies OR validation-failure-count regression vs the pre-delete design, surfaced via `placement_warnings` (toasted by `_syncFromDesignResponse` + both fast-path syncs in [client.js](frontend/src/api/client.js)). `_seek_snapshot_base` sub_position branch is also diff-first now (mid-cluster scrub works for non-replayable clusters).
- **Gating** ([feature_log_panel.js](frontend/src/ui/feature_log_panel.js)): per-step ↶/× enabled iff `(child has diff OR op in REPLAYABLE_SUBTYPES) AND !diffs_evicted`; else disabled with a tooltip. Diff b64 ships to the client (bounded by 5 MB budget).
- **Limitation (decision):** per-step ops only work on clusters created AFTER this shipped — pre-existing saved clusters have no diffs and can't be retrofitted (intermediate states gone); they keep whole-cluster revert/delete + show disabled per-step buttons. Replayable legacy subtypes still work via the replay fallback.
- **Undo connection:** Ctrl-Z is capped at `MAX_UNDO_STEPS=50` (one slot/minor op); the durable feature-log revert is now the way to reach edits older than 50 ops. `MAX_UNDO_STEPS` deliberately NOT raised (deep-copies a multi-MB design per slot).
- Tests: [tests/test_fine_routing_diffs.py](tests/test_fine_routing_diffs.py) (14). Full suite **1446 passed**. Live HTTP verified: fresh `[nick,ligate,color]` cluster all-diffed; per-step revert + entangled delete (warning fires) end-to-end.

### Rapid-edit race → stale-response guard (2026-05-25)

Symptom: adding nicks very fast made later nicks "disappear a moment later", broke undo, and produced the same `Feature index N out of range (log has 1 entries)` revert error. Cause: rapid edits fire CONCURRENT mutations; the backend serializes them correctly (each `mutate_with_minor_log` under `_lock`), but the client had NO ordering guard — an earlier response arriving late clobbered newer `currentDesign`, desyncing the panel's feature_log from the backend. (My diff-encoding work amplified it: bigger responses + more latency per nick.)

Fix — monotonic revision + drop-stale:
- Backend stamps every design response with `revision`, captured ATOMICALLY at mutation time. `state._bump_revision(s)` does `s.revision += 1; set_request_revision(s.revision)`; the contextvar lives in [doc_context.py](backend/api/doc_context.py) (`current_request_revision`/`set_request_revision`) and is **reset to None per request by `DocContextMiddleware`** (else a read-only GET inherits a prior mutation's value — that exact leak failed the first test). `_design_response` ([crud.py](backend/api/crud.py)) adds `"revision": current_request_revision() or design_state.revision()`. All 12 `s.revision += 1` sites now call `_bump_revision`; undo/redo/set_design all bump, so revision is strictly monotonic across every state change.
- Client ([client.js](frontend/src/api/client.js)) tracks `_lastAppliedRevision`; `_isStaleDesignResponse(json)` drops (returns the json, truthy, WITHOUT applying) any design response with `revision < _lastAppliedRevision`. Applied at the top of `_syncFromDesignResponse` + both fast-path syncs. Scoped to design syncs only — cross-doc (`docId`) calls use assembly/instance paths, untouched.
- Verified: 8 concurrent nicks → 8 distinct monotonic revisions (5–12), all applied server-side; latest wins on the client.

## Delete vs. revert + the bundle-create exception (2026-05-26)

Semantic distinction (deliberate, tested): **revert** (`↶`) rolls topology back to the op's
pre-state and drops all later entries; **delete** (`×`) forgets just that log row but KEEPS the
current geometry (e.g. deleting an auto-break entry keeps the nicks —
`test_delete_snapshot_entry_allowed_does_not_change_design`).

**Exception — `bundle-create` (the "initial extrusion").** It's the root op; its pre-state is the
empty workspace and nothing precedes it. "Keep geometry" left orphaned helices with no creating op
in the log, which then persisted on save/reload (user-reported bug). Fix in `delete_feature`
([crud.py](backend/api/crud.py)): when the deleted entry is a `SnapshotLogEntry` with
`op_kind == 'bundle-create'` (non-evicted), pre-substitute its PRE-state (empty) topology into
`temp` before `_seek_feature_log` — `_seek_snapshot_base` can't roll it back itself because the
entry carrying that topology is the one being removed. Result: deleting the initial extrusion
empties the design (full-geometry response → frontend rebuilds; the empty→workspace subscriber then
re-shows the plane-picker). Other snapshot kinds (auto-break, auto-scaffold, segment/continuation
extrude, overhang-extrude) keep the "delete keeps geometry" behavior — use revert to roll those
back. Test: `test_delete_bundle_create_entry_clears_geometry` in
[tests/test_feature_log_snapshot.py](tests/test_feature_log_snapshot.py). NOTE: the part-edit /
assembly-part delete paths in [feature_log_panel.js](frontend/src/ui/feature_log_panel.js) splice
the log row locally (don't hit `delete_feature`), so they don't get this roll-back — out of scope.

## Delete = roll back geometry (option-1 semantics, 2026-06-19)

**Reversed the old "delete keeps geometry" doctrine.** Deleting a topology-producing
`SnapshotLogEntry` now rolls back the op's geometry (like a surgical revert of just that op),
keeping later entries that don't depend on it. Driven by the user (the old behavior was
inconsistent: deleting the *last* snapshot rolled back, deleting an earlier one kept the
geometry baked into a later snapshot's POST-state).

- **[backend/core/feature_dependencies.py](backend/core/feature_dependencies.py)** (NEW, pure, tested
  `tests/test_feature_dependencies.py`): `snapshot_delta(pre,post)→(added,modified)`,
  `delta_entry_targets`, `EntryInfo`, `analyze_dependents(infos,k)→[dependent indices]` (transitive).
  A later entry is a **dependent** of K iff it **references** an id K produced/modified OR is **not
  reconstructable** on a K-free base. Reconstructable = the 5 replayable extrusion ops
  (`REPLAYABLE_SNAPSHOT_OPS`, mirror of `_edit_dispatch_run`) + overlay deltas
  (deformation/cluster_op/cluster_create/overhang_rotation, which seek rebuilds). Everything else
  (auto-*, circle, protein, assembly snapshots, routing-cluster, evicted/diff) is non-reconstructable
  → always a dependent. **Reference-dependency and reconstructability are kept SEPARATE on purpose**:
  the deferred future work (re-run auto-ops on a new base, e.g. "two extrudes, delete one, re-apply
  auto-scaffold on the survivor") only needs to flip `reconstructable` + give the reconstruction path a
  re-exec hook; the analysis is untouched.
- **[crud.py](backend/api/crud.py) `delete_feature`**: a `SnapshotLogEntry` target routes to
  `_delete_snapshot_feature` (delta entries keep their existing seek-rebuild path; routing-cluster still
  KEEPS geometry — its rollback is deferred with auto-op re-derivation). With dependents and
  `cascade=False` → returns non-mutating `{needs_cascade_decision, target_*, dependents:[{index,label}]}`.
  `?cascade=true` → removes K + all dependents. Reconstruction = decode K's PRE-state full design, thread
  it forward through surviving replayable extrusions (`_edit_dispatch_run`, re-encoding their pre/post),
  carry overlay-delta survivors as-is, then `_seek_feature_log(base,-1)`. Threading the *full* pre-state
  (not just `_topology_substitute`) is what fixes overhangs+proteins, which aren't in the substitute set.
  The old `bundle-create` and `protein-import` delete special-cases were **removed** (subsumed by this path).
- **Frontend**: `client.deleteFeature(i, subIndex, {cascade})` passes the decision payload through
  untouched (no design to sync); `feature_log_panel.js` delBtn now awaits it and, on
  `needs_cascade_decision`, opens **`primitives/dependents_dialog.js`** (`showDependentsDecision`
  → 'cascade' | 'revert' | null) which lists the dependents and wires Delete-all / Revert-to-here / Cancel.
- Tests inverted to the new contract: `test_delete_snapshot_entry_rolls_back_geometry`,
  `test_api_relax_is_deletable_rolls_back_pose`, protein last-import-keeps-earlier /
  earlier-import-lists-dependent. New: parallel-extrusion-survives, dependent-auto-op-lists-then-cascades,
  last-extrusion-rollback-undoable. Full suite **2671 passed**. **Live dependents-dialog gesture NOT
  hand-checked in-app** (servers were down) → see manual_validation_debt MV row.

## Known limitations / deferred to v2

- **Manual-edit logging** (extrude, nick, ligate, manual crossover add/remove) — out of scope for v1. Manual edits between snapshots break the snapshot-seek invariant (post-state of K may not equal pre-state of K+1 if manual edits intervened). Documented in `_seek_snapshot_base` docstring.
- ~~Per-tab independent collapse memory~~ — shipped 2026-05-09 via [`frontend/src/ui/section_collapse_state.js`](frontend/src/ui/section_collapse_state.js); each panel reads/writes through `getSectionCollapsed(tab, section, default)` / `setSectionCollapsed(tab, section, collapsed)` keyed under `localStorage` key `nadoc.leftSidebar.sections.v1` with shape `{tab: {section: bool}}`.
- **Drag-resize of sidebar width** — fixed at 280 px.
- **Keyboard shortcut for sidebar toggle** — none. User declined Ctrl+B in v1.
- **Cross-version snapshot replay** — snapshots are pinned to current Pydantic schema. Loading new snapshots in older NADOC builds is not supported (consistent with existing `.nadoc` policy).
- **Selection state staleness on revert-to-empty** — `selectedObject`, `multiSelectedStrandIds`, `isolatedStrandId` are NOT cleared by the empty/non-empty transition subscriptions; only by `_resetForNewDesign()`. Renderers handle missing IDs gracefully (find→bail), so this is latent but not user-visible.

## Critical gotchas

- **Don't use `design_state.snapshot()` + `set_design_silent_reconciled()` for new auto-op endpoints.** Use `mutate_with_feature_log` instead. The two patterns coexist (older non-snapshot routes still use the former) but new endpoints should standardize on the wrapper.
- **`_DESIGN_PANEL_IDS` at [main.js:3288](frontend/src/main.js#L3288)** still includes the four moved sections (`#physics-section`, etc.). Lookup is by `getElementById`, so the move is transparent — keep them in the list so they remain hidden during assembly mode.
- **`_recenter_design` is for caDNAno / scadnano imports only.** Native `.nadoc` loads (`/design/load`, `/design/import`) do NOT recenter — see `feedback_native_files_preserve_positions.md`.
- **Feature/minor recording publishes undo only after recording and validation succeed.** Exceptions or cancellation anywhere in that transaction restore design, full undo/redo, revision and request markers. Invalid pattern requests must preserve redo. Existing invalid-draft validation reports remain permitted; strict agent enforcement is separate future work.
- **The `body` param in `params` is `body.model_dump(mode='json')`** — must be JSON-serializable. Pydantic Direction enums become strings, etc. Edit endpoint validates by reconstructing `BundleSegmentRequest.model_validate(params)` etc.
- **Snapshot decode without recursion guarantee:** `encode_design_snapshot` strips `feature_log` and `feature_log_cursor` before encoding. If you ever want to embed the log itself in a snapshot, you'd need a different mechanism — currently the recursion check is enforced by the encode side, not the schema.
- **Tests must not introduce flakiness.** The `test_seamless_router::test_teeth_closing_zig` is a known pre-existing flake (UUID ordering). Five other tests are pre-existing failures on master, deselected in the standard test command. New tests should NOT depend on UUID ordering.

## Verification

Backend smoke: `uv run pytest tests/test_feature_log_snapshot.py tests/test_crud.py -q` — 54 passed, 1 skipped.

Full backend: `uv run pytest tests/ -q --ignore=tests/test_md_pipeline.py --ignore=tests/test_mrdna_pipeline.py --ignore=tests/test_atomistic.py --ignore=tests/test_atomistic_round_trip.py --ignore=tests/test_xpbd.py --ignore=tests/test_fem_validation.py --deselect tests/test_scaffold_router.py::test_auto_scaffold_hinge_routes_partial_components_without_coverage_loss --deselect tests/test_scaffold_router.py::test_auto_scaffold_hinge_preserves_forced_scaffold_connections --deselect tests/test_seamed_router.py::test_seamed_autoscaffold_preserves_hinge_forced_scaffold_anchors --deselect tests/test_seamed_router.py::test_advanced_seamed_warns_when_hinge3_cannot_consolidate_fixed_edges --deselect tests/test_seamed_router.py::test_advanced_seamed_clears_existing_auto_route_before_teeth_reroute --deselect tests/test_seamless_router.py::test_teeth_closing_zig` — 710 passed, 18 skipped, 6 deselected.

E2E: `frontend/e2e/feature_log_revert.spec.js` (Playwright). Run via `cd frontend && npm run test:e2e` (requires backend running).

Frontend smoke (`just frontend`):
- Boot collapsed → click any tab → sidebar expands.
- Click active tab again or arrow → collapses.
- Switch tabs while expanded → content swaps, sidebar stays open.
- Persists state across reload.
- Run autoscaffold → ◆ entry appears in Feature Log; click ↶ revert → design returns to pre-scaffold.
- Hard-refresh after autoscaffold → snapshot survives via `localStorage`-persisted design; revert still works.
- Open assembly file → auto-switches to Scene tab; assembly panel visible.

## Reference-based clean delete (2026-06-27)

Supersedes the conservative "non-reconstructable means dependent" rule above for dependency
analysis. `backend/core/feature_dependencies.py` now marks a later feature as a dependent only
when its added/modified topology structurally references an id produced by the deleted feature
(transitively including true dependents). It scans field-level references such as strand-domain
helix ids, crossover/forced-ligation endpoints, cluster membership, flexible marks/connections,
overhang anchors, and modified strand ids. `targets=None` remains the conservative unknown
fallback.

`crud._delete_snapshot_feature` now uses structural subtraction for additive clean deletes:
remove the produced ids from the live design, prune cluster membership and empty clusters, scrub
the same ids out of surviving snapshot/routing-cluster pre/post payloads, then seek to end. This
fixes the `workspace/2x2_strutted_corner.nadoc` F2 case: deleting the independent
`extrude-segment` removes only `h_XY_0_4`/`h_XY_0_5` and their strands, while later Fine Routing,
flexible mark/relax, and cluster move entries survive. Non-additive rollback cases such as
auto-break still use the older pre-state/replay path so removed or modified existing strands can
be restored correctly.

### P2 proof infrastructure / P3 native bundle (2026-10-14)

P2 implementation exit criteria are now met: optional versioned `Design.recipe_root` (empty or explicit content-pinned import); complete authoring comparison and recipe/source fingerprints; typed append-incremental dependencies; isolated native command replay; bounded capture; one cancellable verification worker with eight retained results; revision/document invalidation during and after work. Import replay returns `reproduced_import` with native editability false. Unsupported commands remain unverified. Proof is distinct from integrity/scientific validity.

`POST /api/design/features/verification` remains an explicit, bounded synchronous check. `/verification/jobs` POST/GET/DELETE exposes bounded asynchronous work. No checks run automatically during edits, frames or scrubbing. Oversized capture is rejected with 413 rather than blocking on an unlimited clone. Cancellation/deadlines are cooperative, not hard Python preemption.

P3 now has 30 audited native command contracts and root-based producer/consumer regeneration for fully covered histories (`part_recipe_edit.py`). Supported edits preserve IDs, rebuild recovery data, reject source mismatches/stale revisions, and support routing-child parameter edits and explicit cascade deletion. Rootless/mixed unsupported histories retain recovery editors and remain unverified. Dependencies are conservative; full P3 coverage, generated construction, pose/grouping/join/auto-routing and frontend editor integration remain open. Pattern seeds and crossover IDs are recorded before construction. No assembly work or frontend enforcement was added. See `docs/audits/feature_history_20261014/implementation.md` for the exact coverage, remaining exit work and validation. P2/first-family P3 was pushed as `6336d1fe`; this continuation is not phase completion.

P4f/P5a adds bounded pinned caDNAno import into a fresh empty part via
`/design/features/import/cadnano`, explicit repair through the existing evaluation
job lifecycle, and pure pinned coating contracts. Repair rebuilds broken inputs
from their declared root; it never uses the old materialized model as proof.
Stable targets and exact expected inputs protect against stale replacement.
Explicit CPD/duplex engine upgrades retain provenance and undo; a real duplex
upgrade/commit/reload/cold-proof regression passes. Source audits now report both
coating inputs with exact repair paths. Coating live capture/publication remains
disabled pending live capture/publication qualification. The script-spawn pool
initialization failure is fixed with child-only runtime thread limits; all 24
cold coating stages now reproduce. The initial failure remains recorded. Explicit
coating numerical upgrades are supported alongside CPD/duplex. The pure P5b
selection adapter replays the exact prefix and returns bounded typed candidates,
without geometry or a whole-command validity claim; job integration is next.
Ordinary capture budgets remain unchanged. P5 drafts/UI and P6 enforcement remain
open. See the implementation ledger for measured capture and HTTP overhead.

P5b now exposes selection through the existing isolated jobs, with independent
host nonpublication and stale-choice invalidation. P5c shared action/draft schemas
and durable root/command/source fingerprints are implemented but not persisted
on Design yet. Exact transported recipe/authoring hashes protect every candidate
commit from decoder alias changes. Prepared replacement publication rolls back
source identity, full bounded stacks and request/revision state on cancellation
or exception (ISSUE-83), retaining one undo copy. Single-coating explicit jobs
use a fixed scoped capture profile; ordinary budgets are unchanged. Live-lock
qualification and public coating append remain pending. No draft UI or strict
automation policy is enabled; see current ledger rather than earlier phase notes.
