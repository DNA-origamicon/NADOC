---
name: polymerize-origami
description: "Assembly → Polymerize Origami: grow a linear chain of identical mated parts from a single seed AssemblyJoint. Sidebar panel below #properties-section + POST /assembly/polymerize. Shipped 2026-05-15."
metadata: 
  node_type: memory
  type: project
  originSessionId: 82705120-6b9c-4081-a61d-9f0e8369685c
---

# Polymerize Origami (shipped 2026-05-15)

One-click linear polymerization of identical mated parts. Click an orange joint ring in the viewport while the panel is open, set a chain length and direction, hit Polymerize — backend spawns N new `PartInstance`s + new `AssemblyJoint`s mirroring the seed mate in one atomic feature-log step.

(Joint indicators are the orange shaft + arrowhead + ring drawn by `_buildIndicator` in [frontend/src/scene/assembly_joint_renderer.js](frontend/src/scene/assembly_joint_renderer.js) — `COLOUR = 0xff8c00`. The ring is also the rotation-drag handle for revolute joints. There is no separate "green ring" — the green color elsewhere (`CONN_PARENT_COL = 0x3fb950`) is for selected connector spheres during mate-define mode only.)

## What ships

### Data flow
- Seed: an existing `AssemblyJoint` whose `instance_a_id` / `instance_b_id` reference two `PartInstance`s with the same `PartSource` (file-backed: same `.path`; inline: same `Design.id` or equal structural dump).
- Per step (forward): new instance at `delta @ T_prev` where `delta = T_B @ inv(T_A)`. Backward uses `inv(delta)`. New joint between `(prev, new)`, axes derived by transforming the seed joint's `axis_origin`/`axis_direction` through `delta^i`.
- Count semantics: total chain length (existing + new). For `direction="both"`, new instances split evenly; the extra goes forward when `(count − 2)` is odd.
- Each new instance deep-copies the source side's per-instance state (representation / mode / overrides / `interface_points`) so the chain is uniform without re-defining connectors.

### Backend
- Pure math in [backend/core/assembly_polymer.py](backend/core/assembly_polymer.py) — `_sources_match`, `_split_count`, `compute_chain_transforms`, `transform_joint_axis`, `compute_chain_joint_axes`. Unit-testable without FastAPI.
- **Record-assembly orchestration also in core now (carve-up #21, 2026-06-08):** `build_polymer_chain(joint, inst_a, inst_b, additional_instances, count, direction, all_instances, all_joints) -> (existing_instances, new_instances, new_joints)` holds the connector-union + clone build + pattern-mate replication (the `_make_clone`/`_clone_id_*` closures). The `polymerize_assembly` HANDLER is now thin (validate→lookup→delegate→commit→respond, ~80 ln). Direct tests in [tests/test_assembly_polymer_core.py](tests/test_assembly_polymer_core.py) (12). **The PERIODIC build span is ALSO in core now (carve-up #22, 2026-06-15):** `build_periodic_chain(seed, delta, delta_inv, specs, count, direction, all_instances) -> (existing_instances, new_instances, new_joints)` holds the chain-split + delta-power placement + seam-IP union/replacement + uniform seam-joint wiring (`_clone`/`_seam_joint` closures); `polymerize_periodic_assembly` HANDLER is now thin (~50 ln). +8 unit tests in the same file (20 total). Both handlers thin → the 3-route ROUTER lift to `routes_assembly_polymerize.py` is the next carve-up step.
- Route `POST /assembly/polymerize` in [backend/api/assembly.py](backend/api/assembly.py) — body `{joint_id, count, direction}`. Errors: 400 on `count < 2`, 404 on unknown joint, 422 on `sources_differ` or single-side joint. `count == 2` is a no-op (no feature_log entry).
- New `SnapshotOpKind` literal `"assembly-polymerize"` ([backend/core/models.py](backend/core/models.py)).
- Feature_log params record `joint_id` / `count` / `direction` + `new_instance_ids` + `new_joint_ids` so the op can be identified later.

### Frontend
- Menu: `Assembly → Polymerize Origami…` in [frontend/index.html](frontend/index.html).
- Panel: new sidebar section [frontend/src/ui/polymerize_panel.js](frontend/src/ui/polymerize_panel.js), mounted as a DOM sibling immediately after `#properties-section`. Hidden until menu fires `open()`; closes on `Esc` or `✕`. Panel has two ways to pick a seed mate: a dropdown listing every joint in the assembly (label `"<joint.name>: <instA.name> ↔ <instB.name>"`) and a 3D click on the orange joint indicator.
- Selection: while open, the pick in [frontend/src/main.js](frontend/src/main.js) `_onAssemblyPointerDown` (~line 8596) uses `assemblyJointRenderer.pickJointAny(e)` — clicking the shaft, cone, OR ring of the indicator selects the mate. `pickJointRing` is still used outside polymerize mode to start revolute drags. (The ring alone is a narrow target — `RING_TUBE = 0.08 nm` — which is why the whole-indicator picker is needed here.)
- Non-identical warning: when the selected mate's two instances don't share a source, the panel shows a yellow `⚠` warning ("polymerization needs the same part on both sides") and the Polymerize button stays disabled. The backend independently 422's the same case.
- Client: `polymerizeAssembly(body)` in [frontend/src/api/client.js](frontend/src/api/client.js).
- **Chain length is UNBOUNDED (2026-05-22).** The old `max="64"` input attr + two
  `Math.min(64, …)` clamps in `polymerize_panel.js` were removed at user request — any count ≥ 2 is
  allowed. The backend never had an upper bound (only `count < 2` → 400). The non-blocking
  `projected >= 20` confirm dialog (OOM warning) stays; it doesn't limit length, just warns.
  Regression: [frontend/e2e/polymerize_no_length_limit.spec.js](frontend/e2e/polymerize_no_length_limit.spec.js).

### Tests
[tests/test_polymerize.py](tests/test_polymerize.py) — 21 tests covering source-match logic, chain math (forward / backward / both / odd-extra-goes-forward), transform-joint-axis math, and the full API path (count=2 no-op, 400/404/422 paths, connector preservation, joint-type/label propagation, feature_log entry). Full suite: 1301 passed (gained 21 from this feature, no regressions).

## Math worth remembering

The seed mate's `delta = T_B @ inv(T_A)` is a 4×4 row-major SE3 — both rotation and translation. `delta^i` compounds; for a rigid mate where A and B are colinearly offset on +Z, `delta` is just a pure translation along that axis, and the chain is straight along world +Z (validated by `test_polymerize_forward_extends_chain_to_total_count`).

For a revolute joint at non-zero `current_value`, the *current* relative transform differs from the joint's `base_transform`. v1 polymerizes from the live transforms (T_A, T_B as they sit now); new joints start at `current_value = 0` with `base_transform = new_inst.transform`. This means rotating the seed joint after polymerization doesn't propagate to the chain — each new joint is independent.

## Eligibility rule (mirrored in two places — keep them in sync)

`_sources_match` in [backend/core/assembly_polymer.py](backend/core/assembly_polymer.py) is authoritative. The frontend's `_sourcesIdenticalish` in [frontend/src/ui/polymerize_panel.js](frontend/src/ui/polymerize_panel.js) is a UI hint — it accepts any inline pair with the same `design.id`, plus file pairs with the same path. The backend's stricter structural-dump comparison is the source of truth at POST time; if the frontend says "eligible" but the dumps differ, the user sees a 422 with a clear error.

## Cylinders → full upgrade is now fast (shipped 2026-05-15)

After Phases 1–3, the user reported that loading 20 cylinders-mode instances was fine, but switching them back to `'full'` took ~1.5 min. Three compounding costs were responsible:

1. **Per-bp `setMatrixAt` loops** in [helix_renderer.js:525–683](frontend/src/scene/helix_renderer.js#L525-L683). For a 61k-bp design at full LOD that's ~120k iterations × 4 mesh types per instance. Inherent cost — unaddressed in this PR; would need a worker / typed-array refactor.
2. **Phase-1's `invalidateInstance + recursive rebuild`** at cheap → full transitions tore down the WHOLE instance group (arcs, crossover bead meshes, labels, overhang names) and re-fetched geometry over the network, even though only the helix LOD changed.
3. **20 parallel PATCHes**: `Promise.all(instances.map(api.patchInstance(...)))` returned 20 separate assembly responses; each fired the assembly subscription and triggered a full 20-instance rebuild walk.

Fixes:

**In-place helix LOD swap** in [frontend/src/scene/assembly_renderer.js](frontend/src/scene/assembly_renderer.js) (`_inPlaceHelixLodRebuild`). When `setDetailLevel` reports `needsRebuild`, the renderer now:
- Detaches `arcGroup` + `xoverResult.group` from the old `helixCtrl.root` so they survive the swap.
- Disposes only the old helix meshes (skipping `userData.shared` template singletons from Phase 1).
- Re-runs `buildHelixObjects` with the entry's cached `nucleotides` + new LOD — **no network round-trip, no rebuild of labels / overhang names / hull groups / crossovers**.
- Re-parents the stashed arc + xover groups under the new `helixCtrl.root`.

**Batch representation patch**: `PATCH /assembly/instances/batch` ([backend/api/assembly.py](backend/api/assembly.py)) extended to accept `representation` + `visible` per item, mirroring the per-instance route's session-state bookkeeping (`remember_instance_display`). The frontend "Apply to all" handler in [frontend/src/main.js:10245ish](frontend/src/main.js#L10245) now uses `api.batchPatchInstances` — one round-trip, one renderer rebuild walk, in-place LOD upgrade per entry.

Expected impact: the user's 20-instance cylinders → full switch should drop from ~1.5 min to ~10–20 s (still bottlenecked by item 1 above — the per-bp loops in `buildHelixObjects` itself).

Tests added in [tests/test_assembly_api.py](tests/test_assembly_api.py): `test_batch_patch_applies_representation_atomically` + `test_batch_patch_rejects_invalid_representation`. Suite: 1336 passed (+2 net), no regressions.

### Deferred (bigger systemic options)

- **Async-yielding `buildHelixObjects`**: chunk the per-bp loops + `await Promise(setTimeout)` so Chrome's UI thread isn't frozen during heavy builds. Doesn't reduce CPU time but stops the page from feeling hung.
- **Shared `helixCtrl` across identical-source instances**: build one InstancedMesh tree per unique source and represent N clones via N transform matrices. Phase 3 deduplicated the geometry DATA across instances; this step would deduplicate the rendered MESHES. Substantial refactor — per-clone selection / colour overrides / cluster-joint articulation all need new plumbing.
- **Worker-thread geometry build**: move `buildHelixObjects` into a Web Worker that streams matrix/color buffers back to the main thread.

## Phases 2 + 3 of the rendering-memory plan (shipped 2026-05-15)

Combined into one change because they share the response-reshape surface. The user reported Chrome still OOMing on the polymerized load after Phase 1 (cheap-LOD skip-allocate) shipped — Phase 1 cut per-instance GL state but the wire payload was still ~9 × ~30 MB JSON per polymerized clone.

**Phase 2 — compact wire format** ([backend/api/assembly.py](backend/api/assembly.py)):
- `GET /assembly/instances/{id}/geometry` now emits `nucleotides_compact` (parallel arrays per helix per direction) instead of the verbose per-nuc dict list. ~50% smaller wire payload, ~50% faster JS parse. The compact builder `_compact_geometry_from_nucleotides` already existed in `crud.py` for the main design path — reused here directly.

**Phase 3 — source-keyed dedup** (same file):
- `GET /assembly/geometry` (batch) is reshaped to `{ sources: {srcKey: entry}, instances: {instId: srcKey}, errors }`. Two N-clone instances of the same part share **one** source entry — wire size drops from O(N) to O(unique sources). The source key reuses `_geo_cache_key` so the dedup respects cluster-transform overrides (different overrides ⇒ different sources). Per-instance errors are surfaced separately so one bad instance doesn't poison the batch.

**Frontend** ([frontend/src/api/client.js](frontend/src/api/client.js)):
- New module-local `_expandCompactNucleotides(compact)` helper mirrors the existing main-design decoder used by `_syncFromDesignResponse`.
- `getInstanceGeometry` decodes `nucleotides_compact` into the flat list the renderer expects (no renderer change needed).
- `getAssemblyGeometry` projects the new `{sources, instances}` shape back into the legacy `{instances: {id: {nucleotides, helix_axes, design}}}` map the renderer consumes — but the per-instance entries share the **same** decoded JS array reference across instances pointing to the same source, so V8 doesn't carry N copies of identical nucleotide lists.

**Combined impact** for the user's 9-instance polymerize case:
- Wire size: ~270 MB → ~15 MB (Phase 2's compact form × Phase 3's 9:1 dedup).
- JS parse heap: drops similarly.
- Phase 1 covered the per-instance GL/InstancedMesh waste; Phases 2+3 cover the per-instance JSON/parse waste.

Tests in [tests/test_assembly_api.py](tests/test_assembly_api.py): `test_get_instance_geometry_inline` updated to assert the new `nucleotides_compact` shape; two new tests `test_assembly_geometry_dedups_identical_sources` + `test_assembly_geometry_distinct_sources_when_designs_differ` cover the batch dedup semantics. Suite: 1335 passed (+2 net), no regressions.

## Phase 1 of the rendering-memory plan (shipped 2026-05-15)

Background: the previous OOM mitigation (cheap-rep default for new clones + load-time auto-downgrade) hid the deeper problem. The systemic-investigation agent found three layers of waste; Phase 1 addresses the biggest (and only one that's frontend-only):

**Cheap LOD wasn't actually cheap.** `buildHelixObjects` in [frontend/src/scene/helix_renderer.js](frontend/src/scene/helix_renderer.js) used to allocate the full set of bead / cone / slab / fluoro InstancedMesh buffers regardless of `representation`. `setDetailLevel('cylinders')` only flipped `.visible = false`. For 9 polymerized instances of a 61k-bp part that's ~250 MB of resident-but-hidden InstancedMatrix Float32Arrays.

Fix:
- Added a `lod` parameter to `buildHelixObjects(geometry, design, scene, customColors, loopStrandIds, helixAxes, lod = 'full')`. Skips allocating the heavy per-bp count for beads/cones/slabs/fluoros when the LOD doesn't need them — falls back to a dummy count=1 InstancedMesh (64-byte buffer) so downstream code keeps its references but the per-bp loops never run.
- `_builtFlags` records what was actually allocated. `setDetailLevel(level)` now returns `{ needsRebuild: boolean }`; when the caller asks to upgrade to a level whose meshes weren't built, the assembly renderer invalidates the instance and triggers a rebuild so the heavier meshes are re-allocated at full count.
- `assembly_renderer.js` passes each instance's `representation` field as the build-time LOD and reacts to `needsRebuild` from `setDetailLevel`.

**Latent dispose-of-shared-singletons fixed.** Module-level template geometries (`GEO_SPHERE`, `GEO_CUBE_5P`, `GEO_UNIT_BOX`, `GEO_UNIT_CONE`, `GEO_UNIT_CYL`, `GEO_HALF_CYL`, `GEO_FLUORO_SPHERE`) are now tagged with `userData.shared = true` at definition. Every `traverse(o => o.geometry?.dispose())` call site in `assembly_renderer.js` (5 of them — `_disposeGroup`, hull groups, part-joint indicators, orphan-group cleanups in `rebuild` + `dispose`, linker-group teardown) now skips disposal when the flag is set. Previous behavior would have invalidated the shared GPU buffer for every other instance using the same template — a real bug, latent until the user happened to dispose and rebuild in the right order.

Expected impact: the user's 2D-polymerize case (9 heavy instances at `'cylinders'`) drops from ~250 MB Chrome heap to ~30 MB on the build itself. Total assembly geometry payload over the wire is unchanged in this phase (that's Phase 2's job).

Phase 2 (compact wire format) and Phase 3 (source-keyed dedup) — see `/home/joshua/.claude/plans/resilient-growing-sparrow.md`.

## OOM-on-polymerize-then-can't-reopen (fixed 2026-05-15)

User repro: `workspace/Hinge Polys.nass` polymerized to 16 × `Ultimate Polymer Hinge` (61,598 bp / 75 helices / 208 strands each). Each PartInstance at `representation='full'` builds ~50 MB+ of GL state in the browser; 16 of them OOM'd the tab. The saved `.nass` faithfully recorded all 16 at `'full'`, so re-opening reproduced the OOM.

Three coordinated fixes:

1. **Polymerize clones default to `'cylinders'`** in [backend/api/assembly.py](backend/api/assembly.py)`polymerize_assembly`. New primaries on both sides + pattern additionals all get `representation='cylinders'` at creation time. The user's seed instances are untouched; they can upgrade individual clones via the rep picker if they want detail on one of them. Tested by `test_polymerize_new_clones_default_to_cheap_representation` in [tests/test_polymerize.py](tests/test_polymerize.py).

2. **Load-time auto-downgrade** for assemblies that already exceed the threshold. `_maybe_auto_downgrade_for_memory` in [backend/api/assembly.py](backend/api/assembly.py): if more than `_AUTO_DOWNGRADE_FULL_REP_THRESHOLD = 6` instances are at `'full'`, every `'full'` instance is downgraded to `'cylinders'` before the active assembly is set. The `/assembly/load` and `/assembly/import` response gains an optional `notice` field describing what happened so the frontend can toast it. Tested by `test_load_auto_downgrades_when_too_many_full_instances` + `test_load_does_not_downgrade_when_under_threshold`. The user's saved file is now openable.

3. **Pre-polymerize confirm dialog** in [frontend/src/ui/polymerize_panel.js](frontend/src/ui/polymerize_panel.js): if the projected new instance count (≈ `(count-2) × (1 + n_additionals)`) reaches 10+, a `window.confirm` warns and shows what's about to happen + that clones default to cheap rep.

### Systemic notes / deferred

- Lazy geometry loading by visibility / LOD would let the renderer keep `'full'` everywhere and only build heavy geometry for the parts in frustum. Out of scope for this fix.
- A real memory-budget tracker (backend tracks estimated MB per instance, refuses to upgrade past a cap) would be more honest than a count-based threshold but needs per-design size metadata cached.
- `_AUTO_DOWNGRADE_FULL_REP_THRESHOLD = 6` is a guess tuned for the Hinge Polys case; revisit if other users hit OOM at lower counts.

## Off-by-one in pattern additional clone count (fixed 2026-05-15)

User report: with `count=N` and one additional pattern part, the final assembly had **N primaries but only N-1 instances of each additional**. Reproduces because the seed mate contributes two existing primaries (seed_a + seed_b) toward the chain length count, whereas each additional contributes only one existing instance. My loop created the same number of new clones for both (= n_forward = N-2), leaving additionals short by one.

Fix in [backend/api/assembly.py](backend/api/assembly.py) `polymerize_assembly`:
- `add_n_forward = n_forward + 1` for direction ∈ {forward, both}; `add_n_backward = n_backward + 1` for direction == backward (so each additional ends up with `count` total instances).
- Additional-clone creation moved out of the primary loop into its own loop so it can iterate independently.
- `_clone_id_forward` / `_clone_id_backward` now bounds-check + return `None` for steps that exceed the primary chain; pattern-mate replication iterates `max(n_*, add_n_*)` steps and silently skips mate replicas where the primary side has run out (e.g. seed_b-side mates at the extended step). The bonus mate replication uses the extra delta-power matrix from `compute_delta_powers(n_forward+1, n_backward+1)`.

Geometric assumption: the extra clone goes at the **end of the chain in the dominant direction**. This matches the common case where the additional was placed alongside seed_a (level 0) — the bonus clone fills the level-(N-1) slot. For additionals placed alongside seed_b (level 1), the bonus clone lands one position past the chain end; users wanting that geometry can adjust manually. A future refinement could detect each additional's level from its mates and place clones accordingly.

Regression test: `test_polymerize_chain_length_applies_to_every_pattern_member` in [tests/test_polymerize.py](tests/test_polymerize.py) — asserts for `count ∈ {3, 4, 5}` that both primary count and additional count equal `count`. Several pre-existing pattern tests updated to reflect the corrected counts (they previously captured the off-by-one behavior).

## Pattern polymerization — "To pattern" additional instances (shipped 2026-05-15)

The seed mate still defines the chain delta (and must connect identical parts on both sides), but the polymerize request now accepts an optional `additional_instance_ids: list[str]` payload. Each id is a non-seed PartInstance to carry along as part of the **pattern unit**. The clones go to `delta^step @ T(original)` at every new chain step so the additional part's spatial relationship to the chain primary is preserved.

Additionally, **any AssemblyJoint whose both endpoints live in the pattern unit (seed_a + seed_b + additionals) is replicated at every chain step** between the matching cloned instances, with the joint axis shifted by the same `delta^step`.

Key implementation pieces:
- New helpers in [backend/core/assembly_polymer.py](backend/core/assembly_polymer.py): `compute_additional_chain_transforms` (per-additional clone transforms) and `compute_delta_powers` (returns `delta^step` matrices for joint-axis transformation).
- `PolymerizeAssemblyRequest` ([backend/api/assembly.py](backend/api/assembly.py)) gains `additional_instance_ids: list[str] = Field(default_factory=list)`.
- `polymerize_assembly` builds per-additional clone arrays + tracks the per-step id maps (`forward_primary_ids`, `forward_add_ids`, etc.). Inner helpers `_clone_id_forward` and `_clone_id_backward` resolve `original_id → clone_id_at_step` honouring the level structure (seed_a → primary at level `step`, seed_b → primary at level `step+1`).
- The polymerize replay handler in `_replay_assembly_op` now delegates to `polymerize_assembly` itself (rather than duplicating the math) so additional_instance_ids are honoured during surgical mid-history delete and feature-log edit.
- Frontend: `polymerize_panel.js` gains a scrollable "To pattern" checkbox list of all assembly instances minus the seed pair. The set resets whenever the user picks a different seed mate. The Polymerize POST body includes `additional_instance_ids`.

Edge cases:
- Seed-pair ids included in `additional_instance_ids` are silently dropped (no double-cloning).
- Unknown ids 404.
- The additional part doesn't have to be identical to the seed (it's allowed to have a different source/design). Only the seed pair must be identical, since that constraint is what makes the chain delta semantically meaningful.

Tests added in [tests/test_polymerize.py](tests/test_polymerize.py): `test_polymerize_pattern_clones_additional_at_each_step`, `test_polymerize_pattern_replicates_intra_unit_mate`, `test_polymerize_pattern_silently_drops_seed_pair_from_additionals`, `test_polymerize_pattern_404_on_unknown_additional`, `test_polymerize_pattern_edit_changes_count_keeps_additionals`.

## Seek preserves display preferences (representation, visibility) — fixed 2026-05-15

The embedded `post_state_gz_b64` snapshot captures whichever `representation` + `visible` were active **at the time of the mutation**. If the user later switched a heavy part to a cheaper representation (e.g. `'full'` → `'cylinders'`) for performance, then scrubbed the slider, each scrub re-installed the older expensive representation — defeating the user's choice.

Fix: `assembly_state` now keeps a per-instance display-override dict that lives outside the assembly snapshot and survives feature-log scrubbing. Implementation:

- New module-level `_display_state: dict[str, dict]` in [backend/api/assembly_state.py](backend/api/assembly_state.py), plus helpers `remember_instance_display(instance_id, representation=?, visible=?)`, `get_display_overrides()`, `forget_instance_display(instance_id)`. Cleared by `close_session()`.
- `patch_instance` ([backend/api/assembly.py](backend/api/assembly.py)) calls `remember_instance_display` whenever `representation` or `visible` is patched.
- `delete_instance` calls `forget_instance_display` to drop the entry along with the part.
- `seek_assembly_features` decodes the entry's snapshot, then overlays each instance's `representation` + `visible` from `get_display_overrides()` (falling back to the current displayed state's values). Empty-state scrubs (`position = -2`) keep the dict intact even though no instances are in the current state — so the next scrub forward restores the user's preference.

This is a *transient* preference dict (lives only while the assembly session is active). When a user closes and reopens an assembly, the saved `.nass` carries whatever representation was last serialized on each instance — that becomes the baseline for the new session.

Regression test: `test_seek_preserves_per_instance_representation_and_visibility` in [tests/test_assembly_feature_log_actions.py](tests/test_assembly_feature_log_actions.py) — adds two parts, switches one to `'cylinders'` + hidden, scrubs to `-2 / 0 / 1 / -1` and asserts the preference holds at every step.

## Seek now preserves feature_log entries (fixed 2026-05-15)

Earlier implementation of `POST /assembly/features/seek` ([backend/api/assembly.py](backend/api/assembly.py)) stack-walked `assembly_state._history` undo/redo. Each prior snapshot in the deque carries a *shorter* `feature_log`, so after scrubbing back the panel literally rendered fewer entries — user reported "the slider is deleting features" and sometimes couldn't slide back to the latest position (if anything had cleared the redo deque).

Fix: seek now decodes the target entry's embedded `post_state_gz_b64` (or `design_snapshot_gz_b64` for position == -2), restores the assembly geometry to that state, but writes the **full feature_log** back onto the restored assembly before storing it. The undo/redo deque is **not touched** by seek — `assembly_state.set_assembly_silent` updates the active assembly without pushing or clearing either stack. Consequences:
- Scrubbing the slider never drops entries from the log.
- The slider can always reach `position = -1` (the latest state) by decoding the last entry's post-state.
- Ctrl-Z continues to undo actual mutations, not slider scrubs.

Legacy entries created before payload embedding (empty `design_snapshot_gz_b64` / `post_state_gz_b64`) cause seek to return the current display unchanged — the slider effectively no-ops on those positions but the entries stay visible in the panel.

Regression tests in [tests/test_assembly_feature_log_actions.py](tests/test_assembly_feature_log_actions.py): `test_seek_preserves_feature_log_entries` + `test_seek_does_not_drain_redo_stack`.

## Logged op kinds expansion + duplicate-instance (shipped 2026-05-15)

The following assembly mutations now also produce feature-log entries (they previously bypassed `_apply_assembly_mutation_with_feature_log` and were only Ctrl-Z-tracked):
- `assembly-add-instance` — POST `/assembly/instances`
- `assembly-delete-instance` — DELETE `/assembly/instances/{id}`
- `assembly-duplicate-instance` — POST `/assembly/instances/{id}/duplicate` (new route)
- `assembly-add-connector` — POST `/assembly/instances/{id}/connectors`
- `assembly-delete-connector` — DELETE `/assembly/instances/{id}/connectors/{label}`
- `assembly-add-joint` — POST `/assembly/joints` (the "Define Mate" path)
- `assembly-delete-joint` — DELETE `/assembly/joints/{id}`

All are added to `SnapshotOpKind` in [backend/core/models.py](backend/core/models.py) and to `_REPLAYABLE_OP_KINDS` in [backend/api/assembly.py](backend/api/assembly.py). `_EDITABLE_OP_KINDS` is unchanged — these new ops are replayable but don't have a useful Edit UI (renaming etc. would only be cosmetic).

The replay dispatcher in `_replay_assembly_op` honours stored ids (`instance_id`, `joint_id`, `new_instance_id`, `label`) so a mid-history surgical delete that re-runs subsequent add/delete ops doesn't generate fresh uuids — later entries that reference these ids still resolve.

`POST /assembly/instances/{id}/duplicate` body: `{ offset?: [x,y,z]=default [5,0,0], name?: str }`. Server-side path keeps the operation atomic: same `source`, deep-copied `interface_points`, transform translated by `offset`. Frontend invokes via the `⎘` button in each part row in [frontend/src/ui/assembly_panel.js](frontend/src/ui/assembly_panel.js)`_buildInstanceRow`. Client method: `duplicateInstance(instanceId, { offset?, name? })` in [frontend/src/api/client.js](frontend/src/api/client.js).

Tests added in [tests/test_assembly_feature_log_actions.py](tests/test_assembly_feature_log_actions.py):
- `test_add_instance_appears_in_feature_log`
- `test_delete_instance_appears_in_feature_log_and_replays`
- `test_add_connector_appears_in_feature_log`
- `test_add_joint_appears_in_feature_log`
- `test_duplicate_instance_clones_with_offset_and_connectors`
- `test_duplicate_instance_with_custom_offset_and_name`
- `test_duplicate_unknown_instance_404`
- `test_surgical_delete_replays_through_add_instance_entry`

Behaviour-change note: every "Add Part", "Define Mate", "Define Connector" action now creates a snapshot entry in the assembly feature log. Existing assemblies opened from disk still work — old entries (created with `evicted=True`) have no payload and can still be navigated via the slider, but Revert / Edit / Delete won't work on them (route returns 422 with the "no embedded pre-state" message). New mutations from now on always carry payloads.

## Feature-log per-entry actions (shipped 2026-05-15)

Polymerize is fully scrubbable and reversible through the assembly feature-log panel:

- **Revert** — `POST /assembly/features/{i}/revert` ([backend/api/assembly.py](backend/api/assembly.py)) restores the pre-state of entry *i* from its embedded `design_snapshot_gz_b64` and truncates the log to `[0:i]`. Pushes a snapshot so Ctrl-Z still restores.
- **Delete** — `DELETE /assembly/features/{i}` is surgical: pre-state of entry *i* is restored, then every later entry is re-run through `_replay_assembly_op` against the rebuilt state. Each replayed entry gets fresh pre/post payloads. If any later entry has an op kind not in `_EDITABLE_OP_KINDS` (the replayable set), the route 422s with a clear message — fall back to Revert.
- **Edit** — `POST /assembly/features/{i}/edit` re-runs entry *i* with new params merged onto the stored ones. v1 supports only the **latest** entry (no later-entry cascade yet). Editable kinds: `assembly-polymerize`, `assembly-overhang-connection-add`, `assembly-overhang-connection-patch`.

Payload embedding lives in `_apply_assembly_mutation_with_feature_log` ([backend/api/assembly.py:1203](backend/api/assembly.py#L1203)). Each new entry carries `design_snapshot_gz_b64` (pre) + `post_state_gz_b64` (post) via gzip+b64, encoded by `assembly_state.encode_assembly_snapshot` ([backend/api/assembly_state.py](backend/api/assembly_state.py)) — mirrors the design-level helper. `feature_log` / `feature_log_cursor` are stripped before encoding to prevent recursive nesting.

Slider scrubbing (`POST /assembly/features/seek`) is unchanged — it still stack-walks `assembly_state._history` undo/redo, and polymerize traverses cleanly (verified by `test_seek_scrubs_through_polymerize_entry`).

Frontend buttons live in `_rebuildAssemblyFeatureLog` ([frontend/src/ui/feature_log_panel.js](frontend/src/ui/feature_log_panel.js#L1215)). Edit prompts use simple `window.prompt` for v1 — count + direction for polymerize; length + bridge_sequence for overhang connections. Client methods: `revertAssemblyToBeforeFeature`, `deleteAssemblyFeature`, `editAssemblyFeature` in [frontend/src/api/client.js](frontend/src/api/client.js).

Tests: [tests/test_assembly_feature_log_actions.py](tests/test_assembly_feature_log_actions.py) — 11 tests covering payload embedding, revert/delete/edit happy paths, latest-entry-only gate on edit, mid-history surgical delete with polymerize replay, slider scrub through polymerize, Ctrl-Z after polymerize.

Deferred:
- Edit on non-latest entries (would need later-entry cascade rebuild like delete does).
- Replay support for `assembly-overhang-bind` / `-patch` / `-unbind` (currently mid-history delete is rejected if those are downstream of the deleted entry — UI offers Revert as fallback).
- Slider sub-position notches (not relevant — assembly ops don't have nested sub-steps yet).

## Connector-coverage rule (fixed 2026-05-15 after Hinge Polys.nass repro)

`AssemblyJoint`'s `connector_a_label` lives on `instance_a.interface_points`, and `connector_b_label` lives on `instance_b.interface_points`. In a typical user-built mate, the user only `Define Connector`s once per instance — so `inst_a` has just label `α` and `inst_b` has just label `β`. The original mate `(A, B)` is valid: A has α, B has β.

But polymerization creates joints `(B, C)`, `(C, D)`, … where **each interior instance plays BOTH roles** — it's `instance_a` in the next-pair joint (needs label α) and `instance_b` in the previous-pair joint (needs label β). If we just deep-copy the source instance's `interface_points`, every new joint lights up as broken (`_isBrokenMate` in [frontend/src/scene/assembly_joint_renderer.js](frontend/src/scene/assembly_joint_renderer.js)).

Fix in [backend/api/assembly.py](backend/api/assembly.py) `polymerize_assembly`:
- Build a union of `inst_a.interface_points ∪ inst_b.interface_points` (deduped by label).
- Apply the union to **both originals** (A and B) and to every new clone.
- Positions are in part-local coords and the parts are identical (guaranteed by the `_sources_match` precondition), so the union is well-defined.

Regression test: `test_polymerize_handles_seed_instances_with_single_connector_each` in [tests/test_polymerize.py](tests/test_polymerize.py) seeds A with only `connector_a` and B with only `connector_b`, polymerizes forward with count=4, then asserts every joint's `connector_a_label` resolves on its `instance_a` and `connector_b_label` resolves on its `instance_b`.

Diagnostic procedure (kept for future similar failures):
1. Dump the saved `.nass` JSON: `python -c "import json; …" workspace/<file>.nass`.
2. For each instance, print `id` + `name` + `len(interface_points)` + each `ip.label`.
3. For each joint, print `connector_a_label` + `connector_b_label` + `instance_a_id` / `instance_b_id`.
4. Cross-check: does every joint's connector label exist on its referenced instance's IP list?

## mate_relative_transform not propagated → chains resolved position but not orientation (fixed 2026-05-20)

User repro: `workspace/20 hinge test.nass`. Changing the hinge feature (shared source → all hinges update) re-resolved the assembly, but the polymerized mates snapped POSITION only, not ORIENTATION.

Root cause (data-verified, not geometric reasoning): all four `AssemblyJoint(...)` constructors in `polymerize_assembly` ([backend/api/assembly.py](backend/api/assembly.py) — forward primary ~4308, backward primary ~4374, pattern-mate fwd ~4474, pattern-mate bwd ~4496) copied the seed's type / clusters / connector-labels / limits but **omitted `mate_relative_transform`**, so it defaulted to `None`. In `resolve_assembly` the rigid-snap path branches on it: present → full SE3 snap (`snap_T = F_a @ M @ inv(F_b)`); **None → translation-only fallback** (`snap_T = I` with `t = ca − cb`, lines ~1616-1627). So the hand-created seed mates (`create_mate` captures `M = F_a_world⁻¹ @ F_b_world` at [assembly.py:3572](backend/api/assembly.py#L3572)) resolved fully, but every polymerized joint had `mate_rel=None` → orientation unconstrained.

Diagnostic that nailed it: load the .nass, for each joint compute `Fa,Fb = _get_connector_world_frame(...)` and compare `Fb` vs `Fa @ mate_rel` split into position vs rotation error. Joints with `mate_rel` (0, 4) → 0.0/0.0; the rest had `mate_relative_transform == None`.

Fix: pass `mate_relative_transform=joint.mate_relative_transform` (primaries) / `=pm.mate_relative_transform` (pattern mates) into the constructors. Correct because every clone replicates the SAME mate between identical parts with the same (connector_a-on-a-side, connector_b-on-b-side) structure — `F_a⁻¹ @ F_b` is a part-geometry constant (joint 0 vs joint 4 differed by only ~0.7°). Validated: fresh polymerize → all new joints carry the seed's mate_rel; re-resolve → worst orientation error 0.000°, position 0.000 nm. Regression test `test_polymerize_propagates_mate_relative_transform` in [tests/test_polymerize.py](tests/test_polymerize.py). Suite 1383 passed (+1), lone failure is the known nondeterministic seamed-router flake.

**Existing broken files** (e.g. the user's `20 hinge test.nass`): the fix only affects FUTURE polymerize ops; already-saved chains still have `mate_rel=None`. Recovery = revert the polymerize feature-log entry and re-run it (regenerates joints with mate_rel), OR a one-time backfill copying the seed joint's mate_rel onto the None chain joints + re-resolve (demonstrated to heal to 0.000° — but it edits the saved file, so confirm first). Do NOT backfill inside `resolve_assembly` from the live state — the live orientations are already wrong (translation-only-snapped), so capturing there would lock in the error.

## Deferred

- Auto-rebuilding the chain when the seed mate is patched (today: chain stays at original placement; user re-runs polymerize after editing the mate if they want updated spacing).
- Replicate `AssemblyOverhangBinding` / `AssemblyOverhangConnection` along the chain (see [project_assembly_overhang_bindings](project_assembly_overhang_bindings.md) — cross-part bindings between (A,B) are NOT propagated to (B,C) / (C,D) by polymerize).
- 2D / 3D crystal patterns (two-axis polymerization). Today only linear chains.
- Joint-bound preservation across chain rotations — new joints inherit `min_limit`/`max_limit` but not the current driven angle. If the user wants a curved chain they need to set per-joint values manually.
- Selection-layer integration: clicking a chain instance in 3D doesn't auto-select the seed mate; selection still works as before.

## Polymerize (Periodic) — no hand-defined mate (shipped 2026-05-26)

Sibling feature: grow a chain from a SINGLE periodic part instance, deriving the repeat transform from the part's `is_periodic_seam` forced ligations (the end-to-end seam marked in the cadnano editor's periodic-boundary view, see [[periodic-boundary]]). No mate picker needed.

- **Math**: new `backend/core/periodic_polymer.py` — `derive_periodic_delta(design)` rigidly registers (Kabsch, reflection-guarded) the part's NEAR-end seam cross-sections onto the FAR-end ones. CRITICAL conventions (empirically pinned, NOT reasoned): (1) register AXIS GEOMETRY ONLY — origin (true helix axis point) + axis-tangent (z) tip, via `_axis_points`; do NOT register the radial x/y (that leaked the incommensurate per-period twist into a spurious BEND → spiral; see LESSONS A5, fixed 2026-05-26). The axis point is still recovered direction-independently by undoing the minor-groove offset (z=axis_tangent identical fwd/rev). (2) near=lower-bp endpoint, far=higher-bp (a reverse strand presents its 3' at the near side, so key off bp not the 3'/5' role); (3) the far frame is advanced ONE BP (junction bond ≈ one rise, `_bp_step_screw`) so the period is L bp not L−1. Validated: straight bundle (commensurate AND incommensurate L) → pure axial translation, 0° rotation, det(R)=+1; teeth.nadoc (251 bp) → pure 84.168 nm translation. A genuinely curved part still bends (curvature lives in the axis-tangent direction). Twist is left to topology (groove phase may jump at incommensurate junctions; fibre stays straight). `extra_bases` junctions NOT yet modelled.
- **Route**: `POST /assembly/polymerize-periodic` {instance_id, count, direction} ([backend/api/assembly.py](backend/api/assembly.py), after `polymerize_assembly`). Places copy k at `T_seed @ delta^k` (delta is part-LOCAL → left-multiply seed world transform). Synthesizes `seam0:5p`/`seam0:3p` connectors on seed+clones + rigid joints between consecutive copies, capturing ONE `mate_relative_transform = inv(F_a^3p)@F_b^5p` reused on every junction (same pattern as `polymerize_assembly`). op_kind `assembly-polymerize-periodic` (in SnapshotOpKind + _EDITABLE/_REPLAYABLE + replay branch delegates to the route). 422 on non-periodic, 400 on count<2. Tests: `tests/test_periodic_polymer.py` (16). Verified live: 1 POST count=4 → 4 instances + 3 rigid mates, undo→1.
- **Frontend (UNIFIED into the regular Polymerize Origami panel, 2026-05-26)**: periodic parts appear as synthetic entries in the panel's Mate dropdown — `<instance> — via periodic boundary` (option value `periodic:<instanceId>`). Selecting one switches the panel to periodic mode: hides the "to pattern" section (`#poly-pattern-section`), shows periodic eligibility, and the Polymerize button calls `polymerizePeriodicAssembly({instance_id,count,direction})` instead of `polymerizeAssembly`. `initPolymerizePanel(store, { isInstancePeriodic })` ([polymerize_panel.js](frontend/src/ui/polymerize_panel.js)); the panel detects periodicity from `inst.source.design.forced_ligations` (inline sources embed the design) with the injected renderer-cache check as fallback (file sources). Right-clicking a periodic part → "Polymerize…" opens the panel pre-selecting its periodic entry (`open({periodicInstanceId})`). NO separate menu item / context item / panel (the earlier `initPeriodicPolymerizePanel` + `#menu-assembly-polymerize-periodic` were removed in the unification).
- **Gotcha during verification**: the app auto-saves the assembly back to the opened `.nass`, so repeated Playwright runs on the same fixture ACCUMULATE chains (1→4→7→…). Regenerate the fixture between runs; verify via the POST response body, not the persisted file.

### 3D rendering of the seam connector + View toggle (2026-05-27)
A periodic seam (forced ligation merging far-3'→near-5' on the SAME helix) makes the merged strand's two termini CONSECUTIVE but ~a-whole-part apart, so `buildHelixObjects` ([helix_renderer.js](frontend/src/scene/helix_renderer.js)) draws it as one giant full-radius backbone CONE spanning the structure (it's not cross-helix, so `getCrossHelixConnections` would otherwise skip it). Fix/feature: in the cone loop we detect periodic-seam pairs (`design.forced_ligations` where `is_periodic_seam`, keyed `helix:bp:DIRECTION`) and **treat them AS cross-helix** → the fat cone is suppressed (radius 0 at every site keyed off `isCrossHelix`) and the connector flows into the ARC pipeline tagged `isPeriodicSeam`. View menu → **"End-to-End Crossovers"** (`#menu-view-periodic-seam-arcs`, store `showPeriodicSeamArcs`, **default false**) shows/hides those arcs: single-design via `unfold_view._reapplyArcHidden` (mirrors the `showReferenceGeometry` per-arc `hidden` collapse + a store subscriber); assembly via a segregated `periodic` line in `_buildInstanceCrossoverArcs` toggled by a subscriber over `_cache.values()`. Zero impact on designs without periodic seams (empty seam-map short-circuits). Frontend-only.

## Periodic chains re-dock on part feature changes — LIVE seam connectors (2026-05-26)

Editing a feature of a periodic-polymerized part (e.g. a twist/bend on the source) did NOT
update the chain — copies stayed frozen at the polymerize-time pose. Two gaps, both fixed in
[backend/api/assembly.py](backend/api/assembly.py):

1. **Static seam connectors.** `polymerize_periodic_assembly` bakes `seam0:5p`/`seam0:3p` as
   STATIC `ip.position` snapshots. In `resolve_assembly`, connector frames are recomputed live
   from geometry ONLY for `blunt:helix:bp` labels (`_resolve_blunt_label_local` → `deformed_helix_axes`
   / `deformed_nucleotide_positions`); every other label (manual connectors AND the seam labels)
   fell back to the stale stored position. So the rigid seam joints snapped to old frames →
   chain never re-docked. Demonstrated on `workspace/Spiral.nass` (built from `teeth.nadoc`): the
   stored `seam0:3p` (17.0,−48.4,49.8) was already stale vs the live (1.9,−50.5,49.8); a twist
   moved the live anchor 43 nm while the static value used by resolve ignored it.
   **Fix:** new `_resolve_seam_label_local(design, "seam0:5p|3p")` recomputes the anchor from
   `principal_seam_connectors(design)` (live), and a dispatcher `_resolve_live_connector_local`
   (blunt-first, then seam) replaces the 3 `_resolve_blunt_label_local` call sites
   (`_local_frame_for_label`, `_get_connector_world_frame`, `_get_connector_world`). At original
   geometry live==stored → resolve stays a no-op (`test_periodic_resolve_is_stable_noop`). The
   captured `mate_relative_transform` M stays valid: it's a near-identity junction residual
   (the connector-coincidence holds), and it was captured via the same `_build_frame_from_normal`
   the live path uses, so the chain re-derives its effective delta from the live seam frames at
   each junction. Frame builder uses roll-from-normal only (no radial), so a straight part stays
   straight (no spiral — consistent with `derive_periodic_delta`'s axis-only fit, LESSONS A5).

2. **Resolve trigger too narrow.** `seek_instance_features` only auto-ran `resolve_assembly` when
   `_cluster_transforms_signature` changed — its docstring wrongly claimed "deformations don't
   move mate connectors." But connector frames ARE pulled from deformed geometry, so a twist/bend
   edit moves them. **Fix:** new `_part_geometry_signature(design)` = cluster_transforms +
   deformations + per-helix loop_skips; the seek gate compares it instead. (Manual `POST
   /assembly/resolve` always re-docks regardless of trigger.)

Tests: `tests/test_periodic_polymer.py::test_periodic_chain_re_docks_after_part_geometry_change`
(bend added to the shared part → resolve moves clones >1 nm + seam connectors still coincide under
new geometry), `tests/test_assembly_api.py::test_part_geometry_signature_detects_deformation_changes`.
Backend-only — the frontend already applies the resolve response (`solve_status`, geometry).
Scope note: covers the part-context SEEK path + manual Resolve.

### Part-editor save path now auto-resolves + faster cross-tab sync (2026-05-27)

Follow-up: editing the part via the PART EDITOR (separate `?part=&assemblyDoc=` tab → debounced
`_savePartToAssembly` → `patchInstanceDesign(docId=assemblyDoc)`) still left the polymerized chain
frozen, and the sync fired several redundant calls. Two fixes:
- **Backend** `patch_instance_design` ([backend/api/assembly.py](backend/api/assembly.py)) now
  auto-resolves exactly like `seek_instance_features`: compute `_part_geometry_signature` of the
  OLD source design vs the new `body.content`; if it changed AND the assembly has joints, call
  `resolve_assembly()` and return the re-docked assembly. Was the gap — the part-editor save path
  skipped resolve entirely, so the chain transforms never recomputed. Test:
  `tests/test_periodic_polymer.py::test_patch_instance_design_auto_resolves_periodic_chain`
  (file-backed periodic seed → polymerize → PATCH a bent design → chain moves >1 nm, no manual Resolve).
- **Frontend** `_refreshAssemblyPartInstance` ([frontend/src/main.js](frontend/src/main.js), the
  `part-design-updated` BroadcastChannel handler): (1) it invalidated ONLY the one instance whose id
  came through — now invalidates ALL instances sharing that source file, so every chain copy's
  GEOMETRY (shape) refetches, not just the seed's (positions came from getAssembly, but the clones
  kept stale shape); (2) marks the source path in `_selfSavedPaths` so the watchdog SSE `file-changed`
  echo (which would run a SECOND full rebuild + 4× `getInstanceDesign`) is skipped by
  `_handleLibraryEvent`; (3) the cluster-panel `getInstanceDesign` is fetched once and applied to all
  affected instances. Net: one rebuild + ~3 calls (getAssembly + getAssemblyGeometry + 1
  getInstanceDesign) instead of two rebuilds + ~6 calls. Frontend NOT click-verified (local :8000
  backend was hung); `npx vite build` passes.

The file-watchdog reload path for a part edited in plain design mode (no `_partEditContext`) still
goes through `_handleLibraryEvent` (which rebuilds but does not itself resolve — it relies on the
backend assembly_state already being resolved by whatever wrote the file; an external editor that
writes the file without hitting `patch_instance_design` would NOT auto-resolve — manual Resolve then).

### Part-edit sync FLOOD (40× rebuild) + hull/cylinder overlay — fixed 2026-05-27

User repro: editing a part in a part-editor tab and returning to the assembly produced a huge flood
in the assembly tab's console — dozens of `GET /assembly/geometry` (each a full rebuild of all N
instances) + one `GET /assembly/instances/{id}/design` PER instance, all concurrent, 20-30 s
responses (backend saturated). The hull-prism+cylinder LOD overlay only appeared after this, and was
a RACE during the 40-way concurrent rebuild (one rebuild's `dispose()` racing another's build → a
stale `sharedLodCurvedCyl` left drawing under the new `sharedLodHull`). The two issues were the same
root cause.

**Root cause:** the SHARED renderer's `invalidateInstance(id)` ([assembly_renderer.js](frontend/src/scene/assembly_renderer.js) ~5437)
IGNORES the id and does a full `rebuild(assembly)` (fire-and-forget). A prior fix had
`_refreshAssemblyPartInstance` ([main.js](frontend/src/main.js)) invalidate EVERY instance sharing the
edited source (to update clones) → for an N-copy chain that fired N full rebuilds → N×
`getAssemblyGeometry`. Plus the broadcast (`part-design-updated`) AND the watchdog SSE
(`file-changed`) BOTH ran a full `_refreshAssemblyPartInstance`, and the SSE handler additionally did
one `getInstanceDesign` per instance.

**Fix (frontend):**
- `_refreshAssemblyPartInstance` no longer invalidates per-instance. The shared `rebuild()` ALWAYS
  `dispose()`s every source and refetches the batch `getAssemblyGeometry` once (the part-edit cleared
  the backend geo cache), so a SINGLE rebuild updates every copy's geometry. Removing the loop turns
  N rebuilds into 1.
- New coalesced scheduler `_scheduleAssemblyPartRefresh(instanceId, reason)` (debounce 250 ms +
  drop-while-in-flight + one trailing). Both the `part-design-updated` broadcast handler AND
  `_handleLibraryEvent`'s assembly branch route through it, so a burst of edits (slider drag) + the
  broadcast + the SSE collapse into ONE refresh. The SSE branch no longer does its own rebuild /
  per-instance `getInstanceDesign`.
- Verified (Playwright, throwaway spec): a burst of 6 `part-design-updated` broadcasts → `getAssembly`
  ×1, `getAssembly/geometry` ×0-1 (was ×40), `getInstanceDesign` ×2 (was ×40). Single-tab rep
  switching (cylinders↔hull, incl. revert) was already clean; the overlay was flood-induced, so it's
  resolved by removing the flood.
- KEY GOTCHA for future work: on the shared renderer, `invalidateInstance` == full rebuild. NEVER
  call it in a loop. One call (or one `rebuild()`) refreshes the whole assembly.

### Blank scene + /library/files flood on part-edit refresh — fixed 2026-05-27
After the per-instance-rebuild fix, a part edit still showed: (a) the assembly going BLANK for the
whole refresh ("looks hung"), and (b) a `GET /library/files` flood (rising 384→3088 ms = backend
queuing). Three fixes:
- **No blank** — the shared `rebuild()` ([assembly_renderer.js](frontend/src/scene/assembly_renderer.js))
  called `dispose()` BEFORE the slow `getAssemblyGeometry()` fetch, blanking the viewport for the
  entire (seconds-long) fetch. Now it fetches FIRST and disposes only once the data is in hand, so
  the old chain stays on screen during the fetch (and stays on a fetch error instead of blanking).
- **Library flood** — `_handleLibraryEvent` ([main.js](frontend/src/main.js)) ran
  `libraryPanel.refresh()` (→ `GET /library/files`) on EVERY SSE incl. self-saved echoes, undebounced.
  Now the self-saved skip runs FIRST and the refresh is debounced (`_scheduleLibraryRefresh`, 400 ms).
- **Assembly autosave echo** — a part-edit refresh updates `currentAssembly` → the assembly autosave
  subscriber writes Spiral.nass → `file-changed assembly` SSE → another library refresh. The autosave
  now marks the assembly path (and the resolved `r.path`) in `_selfSavedPaths` so its own echo is
  skipped.
- Build passes; NOT cleanly verified in-app (see hazard below). All three are inspection-sound,
  low-risk reorder/debounce/skip changes.

⚠️ FIXTURE HAZARD (bit me hard this session): the app AUTO-SAVES the open assembly back to its `.nass`
on every change, so repeated Playwright runs against `workspace/Spiral.nass` MUTATE it (4→40 via the
polymerize-accumulate gotcha, then a part-editor-init `importAssembly(cached)` into the shared doc
reset it to 1 instance). ALWAYS use a throwaway copy of a `.nass` for assembly E2E, never the real
fixture, and verify via the response body not the persisted file. (Re-states the polymerize gotcha.)

## Related
- [[assembly-overhang-bindings]] — cross-part bindings + linkers; the polymerize feature does NOT replicate these.
- [[periodic-boundary]] — the cadnano-editor seam-marking feature that makes a part "periodic" (`is_periodic_seam` forced ligations).
- `AssemblyJoint` is the "mate" data class — see [backend/core/models.py:1767](backend/core/models.py#L1767). Both `Define Joint` and `Define Mate` menu items create one.
