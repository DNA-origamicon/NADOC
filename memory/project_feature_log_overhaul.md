---
name: Feature Log Overhaul + Tabbed Sidebar
description: Architecture, critical files, and design decisions for the snapshot-bearing feature log, edit endpoint, broken-delta detection, and the three-tab left sidebar. Read before touching feature_log, mutate_with_feature_log, _seek_feature_log, or the left sidebar tab strip.
type: project
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---
# Feature Log Overhaul + Tabbed Sidebar (commit 873f3e6, branch feature-log-update, 2026-05-02)

## What was built

**Snapshot system.** Added 4th variant `SnapshotLogEntry` to the `FeatureLogEntry` discriminated union ([backend/core/models.py](backend/core/models.py)). Every snapshot stores BOTH `design_snapshot_gz_b64` (pre-state) AND `post_state_gz_b64` (post-state) as gzip+base64 of `design.model_dump_json()` with `feature_log` and `feature_log_cursor` stripped to prevent recursion. 5 MB rolling budget enforced by `_evict_oldest_snapshots_if_over_budget` — newest snapshot is NEVER evicted (revert must always work for the most recent op). Both pre+post are evicted together; entries remain in the log so historical labels stay visible (`evicted=True`, payload cleared).

**State-layer chokepoint.** `mutate_with_feature_log(op_kind, label, params, fn)` in [backend/api/state.py](backend/api/state.py) is the canonical wrapper for snapshot-emitting ops. Captures pre-state, runs `fn(active_design)` (which may return new Design or mutate in place + return MutationReport), reconciles cluster membership, captures post-state, appends entry, validates, pushes undo. Returns `(design, validation_report, snap_entry)`.

**13 endpoints converted** (in [backend/api/crud.py](backend/api/crud.py)):
- 8 auto-ops: `auto-scaffold`, `auto-scaffold-seamed`, `auto-scaffold-seamless` (+ advanced variants), `auto-break`, `auto-merge`, `auto-crossover`, `create-near-ends`, `create-far-ends`
- 2 overhang-bulk: `clear_all_overhangs`, `generate_all_overhang_sequences`
- 5 extrusion: `bundle-create`, `bundle-segment`, `bundle-continuation`, `bundle-deformed-continuation`, `overhang-extrude`

The auto-scaffold variants share a `_run_auto_scaffold_with_feature_log` helper that threads the algorithm's `result` object out via a closure (so `result.warnings` etc. reach the response). The extrusion routes have per-op pure builder helpers (`_build_bundle`, `_build_extrude_segment`, etc.) that are reused by both the live endpoint and the edit endpoint.

**`bundle-create` resets to empty Design first** so its snapshot's pre-state is the canonical empty workspace — seek to F0 (position == -2) yields an empty design regardless of what was loaded before.

**Snapshot-aware seek.** `_seek_feature_log(design, position)` calls `_seek_snapshot_base(design, position)` to substitute topology-bearing fields (helices, strands, crossovers, overhang_connections, extensions, photoproduct_junctions, forced_ligations) from the most-recent non-evicted snapshot's POST-state at-or-before `position`. For positions before the first snapshot, falls back to the FIRST snapshot's PRE-state (the F0 baseline). Then the existing delta-replay logic runs on top, rebuilding deformations/clusters/overhangs from log entries 0..position. The geometry-batch endpoint (used by animation playback) calls `_seek_feature_log` per requested position, so animations automatically support seeking through snapshots.

**Why both pre AND post:** seek is destructive (writes the seeked-to state to active_design), so we can't recover "latest topology" from the live design after a back-seek. Storing post-state on every snapshot is the cleanest fix. Cost is ~2× snapshot bytes but the eviction budget handles it.

**Revert + edit endpoints.**
- `POST /design/features/{i}/revert`: decode pre-state, truncate log to entries before `i`, push prior state to undo. Returns 410 if the snapshot was evicted, 400 if not a snapshot entry.
- `POST /design/features/{i}/edit`: only for extrusion op_kinds (`bundle-create`, `extrude-*`, `overhang-extrude`). Validates new params against the original Pydantic body class via `_edit_dispatch_run`, replays the op against the entry's pre-state, splices the updated entry (re-encoded pre+post) into the log. Refuses with 409 if any later snapshot entry exists (revert-and-rerun model). Refuses with 400 for auto-op snapshots (those should be reverted and re-run via the original UI).

**Frontend feature log panel** ([frontend/src/ui/feature_log_panel.js](frontend/src/ui/feature_log_panel.js)):
- Snapshot entries render with ◆ icon, params summary tooltip, amber `↶` revert button, and (for extrusion ops only) `✎` edit button. Clicking edit opens a `prompt()` for `length_bp`; the full updated params dict is sent to the edit endpoint.
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
- **`mutate_with_feature_log` pushes to undo on entry**, then runs `fn`. If `fn` raises, the snapshot is in undo but design is unchanged — Ctrl-Z would be a no-op. Acceptable; matches `mutate_with_reconcile` behavior.
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
