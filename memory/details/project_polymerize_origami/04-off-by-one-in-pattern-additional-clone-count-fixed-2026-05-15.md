# Off-by-one in pattern additional clone count (fixed 2026-05-15) — supporting detail

[Topic head](../../project_polymerize_origami.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Off-by-one in pattern additional clone count (fixed 2026-05-15)

User report: with `count=N` and one additional pattern part, the final assembly had **N primaries but only N-1 instances of each additional**. Reproduces because the seed mate contributes two existing primaries (seed_a + seed_b) toward the chain length count, whereas each additional contributes only one existing instance. My loop created the same number of new clones for both (= n_forward = N-2), leaving additionals short by one.

Fix in [backend/api/assembly.py](../../../backend/api/assembly.py) `polymerize_assembly`:
- `add_n_forward = n_forward + 1` for direction ∈ {forward, both}; `add_n_backward = n_backward + 1` for direction == backward (so each additional ends up with `count` total instances).
- Additional-clone creation moved out of the primary loop into its own loop so it can iterate independently.
- `_clone_id_forward` / `_clone_id_backward` now bounds-check + return `None` for steps that exceed the primary chain; pattern-mate replication iterates `max(n_*, add_n_*)` steps and silently skips mate replicas where the primary side has run out (e.g. seed_b-side mates at the extended step). The bonus mate replication uses the extra delta-power matrix from `compute_delta_powers(n_forward+1, n_backward+1)`.

Geometric assumption: the extra clone goes at the **end of the chain in the dominant direction**. This matches the common case where the additional was placed alongside seed_a (level 0) — the bonus clone fills the level-(N-1) slot. For additionals placed alongside seed_b (level 1), the bonus clone lands one position past the chain end; users wanting that geometry can adjust manually. A future refinement could detect each additional's level from its mates and place clones accordingly.

Regression test: `test_polymerize_chain_length_applies_to_every_pattern_member` in [tests/test_polymerize.py](../../../tests/test_polymerize.py) — asserts for `count ∈ {3, 4, 5}` that both primary count and additional count equal `count`. Several pre-existing pattern tests updated to reflect the corrected counts (they previously captured the off-by-one behavior).

## Pattern polymerization — "To pattern" additional instances (shipped 2026-05-15)

The seed mate still defines the chain delta (and must connect identical parts on both sides), but the polymerize request now accepts an optional `additional_instance_ids: list[str]` payload. Each id is a non-seed PartInstance to carry along as part of the **pattern unit**. The clones go to `delta^step @ T(original)` at every new chain step so the additional part's spatial relationship to the chain primary is preserved.

Additionally, **any AssemblyJoint whose both endpoints live in the pattern unit (seed_a + seed_b + additionals) is replicated at every chain step** between the matching cloned instances, with the joint axis shifted by the same `delta^step`.

Key implementation pieces:
- New helpers in [backend/core/assembly_polymer.py](../../../backend/core/assembly_polymer.py): `compute_additional_chain_transforms` (per-additional clone transforms) and `compute_delta_powers` (returns `delta^step` matrices for joint-axis transformation).
- `PolymerizeAssemblyRequest` ([backend/api/assembly.py](../../../backend/api/assembly.py)) gains `additional_instance_ids: list[str] = Field(default_factory=list)`.
- `polymerize_assembly` builds per-additional clone arrays + tracks the per-step id maps (`forward_primary_ids`, `forward_add_ids`, etc.). Inner helpers `_clone_id_forward` and `_clone_id_backward` resolve `original_id → clone_id_at_step` honouring the level structure (seed_a → primary at level `step`, seed_b → primary at level `step+1`).
- The polymerize replay handler in `_replay_assembly_op` now delegates to `polymerize_assembly` itself (rather than duplicating the math) so additional_instance_ids are honoured during surgical mid-history delete and feature-log edit.
- Frontend: `polymerize_panel.js` gains a scrollable "To pattern" checkbox list of all assembly instances minus the seed pair. The set resets whenever the user picks a different seed mate. The Polymerize POST body includes `additional_instance_ids`.

Edge cases:
- Seed-pair ids included in `additional_instance_ids` are silently dropped (no double-cloning).
- Unknown ids 404.
- The additional part doesn't have to be identical to the seed (it's allowed to have a different source/design). Only the seed pair must be identical, since that constraint is what makes the chain delta semantically meaningful.

Tests added in [tests/test_polymerize.py](../../../tests/test_polymerize.py): `test_polymerize_pattern_clones_additional_at_each_step`, `test_polymerize_pattern_replicates_intra_unit_mate`, `test_polymerize_pattern_silently_drops_seed_pair_from_additionals`, `test_polymerize_pattern_404_on_unknown_additional`, `test_polymerize_pattern_edit_changes_count_keeps_additionals`.

## Seek preserves display preferences (representation, visibility) — fixed 2026-05-15

The embedded `post_state_gz_b64` snapshot captures whichever `representation` + `visible` were active **at the time of the mutation**. If the user later switched a heavy part to a cheaper representation (e.g. `'full'` → `'cylinders'`) for performance, then scrubbed the slider, each scrub re-installed the older expensive representation — defeating the user's choice.

Fix: `assembly_state` now keeps a per-instance display-override dict that lives outside the assembly snapshot and survives feature-log scrubbing. Implementation:

- New module-level `_display_state: dict[str, dict]` in [backend/api/assembly_state.py](../../../backend/api/assembly_state.py), plus helpers `remember_instance_display(instance_id, representation=?, visible=?)`, `get_display_overrides()`, `forget_instance_display(instance_id)`. Cleared by `close_session()`.
- `patch_instance` ([backend/api/assembly.py](../../../backend/api/assembly.py)) calls `remember_instance_display` whenever `representation` or `visible` is patched.
- `delete_instance` calls `forget_instance_display` to drop the entry along with the part.
- `seek_assembly_features` decodes the entry's snapshot, then overlays each instance's `representation` + `visible` from `get_display_overrides()` (falling back to the current displayed state's values). Empty-state scrubs (`position = -2`) keep the dict intact even though no instances are in the current state — so the next scrub forward restores the user's preference.

This is a *transient* preference dict (lives only while the assembly session is active). When a user closes and reopens an assembly, the saved `.nass` carries whatever representation was last serialized on each instance — that becomes the baseline for the new session.

Regression test: `test_seek_preserves_per_instance_representation_and_visibility` in [tests/test_assembly_feature_log_actions.py](../../../tests/test_assembly_feature_log_actions.py) — adds two parts, switches one to `'cylinders'` + hidden, scrubs to `-2 / 0 / 1 / -1` and asserts the preference holds at every step.

## Seek now preserves feature_log entries (fixed 2026-05-15)

Earlier implementation of `POST /assembly/features/seek` ([backend/api/assembly.py](../../../backend/api/assembly.py)) stack-walked `assembly_state._history` undo/redo. Each prior snapshot in the deque carries a *shorter* `feature_log`, so after scrubbing back the panel literally rendered fewer entries — user reported "the slider is deleting features" and sometimes couldn't slide back to the latest position (if anything had cleared the redo deque).

Fix: seek now decodes the target entry's embedded `post_state_gz_b64` (or `design_snapshot_gz_b64` for position == -2), restores the assembly geometry to that state, but writes the **full feature_log** back onto the restored assembly before storing it. The undo/redo deque is **not touched** by seek — `assembly_state.set_assembly_silent` updates the active assembly without pushing or clearing either stack. Consequences:
- Scrubbing the slider never drops entries from the log.
- The slider can always reach `position = -1` (the latest state) by decoding the last entry's post-state.
- Ctrl-Z continues to undo actual mutations, not slider scrubs.

Legacy entries created before payload embedding (empty `design_snapshot_gz_b64` / `post_state_gz_b64`) cause seek to return the current display unchanged — the slider effectively no-ops on those positions but the entries stay visible in the panel.

Regression tests in [tests/test_assembly_feature_log_actions.py](../../../tests/test_assembly_feature_log_actions.py): `test_seek_preserves_feature_log_entries` + `test_seek_does_not_drain_redo_stack`.

## Logged op kinds expansion + duplicate-instance (shipped 2026-05-15)

The following assembly mutations now also produce feature-log entries (they previously bypassed `_apply_assembly_mutation_with_feature_log` and were only Ctrl-Z-tracked):
- `assembly-add-instance` — POST `/assembly/instances`
- `assembly-delete-instance` — DELETE `/assembly/instances/{id}`
- `assembly-duplicate-instance` — POST `/assembly/instances/{id}/duplicate` (new route)
- `assembly-add-connector` — POST `/assembly/instances/{id}/connectors`
- `assembly-delete-connector` — DELETE `/assembly/instances/{id}/connectors/{label}`
- `assembly-add-joint` — POST `/assembly/joints` (the "Define Mate" path)
- `assembly-delete-joint` — DELETE `/assembly/joints/{id}`

All are added to `SnapshotOpKind` in [backend/core/models.py](../../../backend/core/models.py) and to `_REPLAYABLE_OP_KINDS` in [backend/api/assembly.py](../../../backend/api/assembly.py). `_EDITABLE_OP_KINDS` is unchanged — these new ops are replayable but don't have a useful Edit UI (renaming etc. would only be cosmetic).

The replay dispatcher in `_replay_assembly_op` honours stored ids (`instance_id`, `joint_id`, `new_instance_id`, `label`) so a mid-history surgical delete that re-runs subsequent add/delete ops doesn't generate fresh uuids — later entries that reference these ids still resolve.

`POST /assembly/instances/{id}/duplicate` body: `{ offset?: [x,y,z]=default [5,0,0], name?: str }`. Server-side path keeps the operation atomic: same `source`, deep-copied `interface_points`, transform translated by `offset`. Frontend invokes via the `⎘` button in each part row in [frontend/src/ui/assembly_panel.js](../../../frontend/src/ui/assembly_panel.js)`_buildInstanceRow`. Client method: `duplicateInstance(instanceId, { offset?, name? })` in [frontend/src/api/client.js](../../../frontend/src/api/client.js).

Tests added in [tests/test_assembly_feature_log_actions.py](../../../tests/test_assembly_feature_log_actions.py):
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

- **Revert** — `POST /assembly/features/{i}/revert` ([backend/api/assembly.py](../../../backend/api/assembly.py)) restores the pre-state of entry *i* from its embedded `design_snapshot_gz_b64` and truncates the log to `[0:i]`. Pushes a snapshot so Ctrl-Z still restores.
- **Delete** — `DELETE /assembly/features/{i}` is surgical: pre-state of entry *i* is restored, then every later entry is re-run through `_replay_assembly_op` against the rebuilt state. Each replayed entry gets fresh pre/post payloads. If any later entry has an op kind not in `_EDITABLE_OP_KINDS` (the replayable set), the route 422s with a clear message — fall back to Revert.
- **Edit** — `POST /assembly/features/{i}/edit` re-runs entry *i* with new params merged onto the stored ones. v1 supports only the **latest** entry (no later-entry cascade yet). Editable kinds: `assembly-polymerize`, `assembly-overhang-connection-add`, `assembly-overhang-connection-patch`.

Payload embedding lives in `_apply_assembly_mutation_with_feature_log` ([backend/api/assembly.py:1203](../../../backend/api/assembly.py#L1203)). Each new entry carries `design_snapshot_gz_b64` (pre) + `post_state_gz_b64` (post) via gzip+b64, encoded by `assembly_state.encode_assembly_snapshot` ([backend/api/assembly_state.py](../../../backend/api/assembly_state.py)) — mirrors the design-level helper. `feature_log` / `feature_log_cursor` are stripped before encoding to prevent recursive nesting.

Slider scrubbing (`POST /assembly/features/seek`) is unchanged — it still stack-walks `assembly_state._history` undo/redo, and polymerize traverses cleanly (verified by `test_seek_scrubs_through_polymerize_entry`).

Frontend buttons live in `_rebuildAssemblyFeatureLog` ([frontend/src/ui/feature_log_panel.js](../../../frontend/src/ui/feature_log_panel.js#L1215)). Edit prompts use simple `window.prompt` for v1 — count + direction for polymerize; length + bridge_sequence for overhang connections. Client methods: `revertAssemblyToBeforeFeature`, `deleteAssemblyFeature`, `editAssemblyFeature` in [frontend/src/api/client.js](../../../frontend/src/api/client.js).

Tests: [tests/test_assembly_feature_log_actions.py](../../../tests/test_assembly_feature_log_actions.py) — 11 tests covering payload embedding, revert/delete/edit happy paths, latest-entry-only gate on edit, mid-history surgical delete with polymerize replay, slider scrub through polymerize, Ctrl-Z after polymerize.

Deferred:
- Edit on non-latest entries (would need later-entry cascade rebuild like delete does).
- Replay support for `assembly-overhang-bind` / `-patch` / `-unbind` (currently mid-history delete is rejected if those are downstream of the deleted entry — UI offers Revert as fallback).
- Slider sub-position notches (not relevant — assembly ops don't have nested sub-steps yet).

## Connector-coverage rule (fixed 2026-05-15 after Hinge Polys.nass repro)

`AssemblyJoint`'s `connector_a_label` lives on `instance_a.interface_points`, and `connector_b_label` lives on `instance_b.interface_points`. In a typical user-built mate, the user only `Define Connector`s once per instance — so `inst_a` has just label `α` and `inst_b` has just label `β`. The original mate `(A, B)` is valid: A has α, B has β.

But polymerization creates joints `(B, C)`, `(C, D)`, … where **each interior instance plays BOTH roles** — it's `instance_a` in the next-pair joint (needs label α) and `instance_b` in the previous-pair joint (needs label β). If we just deep-copy the source instance's `interface_points`, every new joint lights up as broken (`_isBrokenMate` in [frontend/src/scene/assembly_joint_renderer.js](../../../frontend/src/scene/assembly_joint_renderer.js)).

Fix in [backend/api/assembly.py](../../../backend/api/assembly.py) `polymerize_assembly`:
- Build a union of `inst_a.interface_points ∪ inst_b.interface_points` (deduped by label).
- Apply the union to **both originals** (A and B) and to every new clone.
- Positions are in part-local coords and the parts are identical (guaranteed by the `_sources_match` precondition), so the union is well-defined.

Regression test: `test_polymerize_handles_seed_instances_with_single_connector_each` in [tests/test_polymerize.py](../../../tests/test_polymerize.py) seeds A with only `connector_a` and B with only `connector_b`, polymerizes forward with count=4, then asserts every joint's `connector_a_label` resolves on its `instance_a` and `connector_b_label` resolves on its `instance_b`.

Diagnostic procedure (kept for future similar failures):
1. Dump the saved `.nass` JSON: `python -c "import json; …" workspace/<file>.nass`.
2. For each instance, print `id` + `name` + `len(interface_points)` + each `ip.label`.
3. For each joint, print `connector_a_label` + `connector_b_label` + `instance_a_id` / `instance_b_id`.
4. Cross-check: does every joint's connector label exist on its referenced instance's IP list?

## mate_relative_transform not propagated → chains resolved position but not orientation (fixed 2026-05-20)

User repro: `workspace/20 hinge test.nass`. Changing the hinge feature (shared source → all hinges update) re-resolved the assembly, but the polymerized mates snapped POSITION only, not ORIENTATION.

Root cause (data-verified, not geometric reasoning): all four `AssemblyJoint(...)` constructors in `polymerize_assembly` ([backend/api/assembly.py](../../../backend/api/assembly.py) — forward primary ~4308, backward primary ~4374, pattern-mate fwd ~4474, pattern-mate bwd ~4496) copied the seed's type / clusters / connector-labels / limits but **omitted `mate_relative_transform`**, so it defaulted to `None`. In `resolve_assembly` the rigid-snap path branches on it: present → full SE3 snap (`snap_T = F_a @ M @ inv(F_b)`); **None → translation-only fallback** (`snap_T = I` with `t = ca − cb`, lines ~1616-1627). So the hand-created seed mates (`create_mate` captures `M = F_a_world⁻¹ @ F_b_world` at [assembly.py:3572](../../../backend/api/assembly.py#L3572)) resolved fully, but every polymerized joint had `mate_rel=None` → orientation unconstrained.

Diagnostic that nailed it: load the .nass, for each joint compute `Fa,Fb = _get_connector_world_frame(...)` and compare `Fb` vs `Fa @ mate_rel` split into position vs rotation error. Joints with `mate_rel` (0, 4) → 0.0/0.0; the rest had `mate_relative_transform == None`.

Fix: pass `mate_relative_transform=joint.mate_relative_transform` (primaries) / `=pm.mate_relative_transform` (pattern mates) into the constructors. Correct because every clone replicates the SAME mate between identical parts with the same (connector_a-on-a-side, connector_b-on-b-side) structure — `F_a⁻¹ @ F_b` is a part-geometry constant (joint 0 vs joint 4 differed by only ~0.7°). Validated: fresh polymerize → all new joints carry the seed's mate_rel; re-resolve → worst orientation error 0.000°, position 0.000 nm. Regression test `test_polymerize_propagates_mate_relative_transform` in [tests/test_polymerize.py](../../../tests/test_polymerize.py). Suite 1383 passed (+1), lone failure is the known nondeterministic seamed-router flake.

**Existing broken files** (e.g. the user's `20 hinge test.nass`): the fix only affects FUTURE polymerize ops; already-saved chains still have `mate_rel=None`. Recovery = revert the polymerize feature-log entry and re-run it (regenerates joints with mate_rel), OR a one-time backfill copying the seed joint's mate_rel onto the None chain joints + re-resolve (demonstrated to heal to 0.000° — but it edits the saved file, so confirm first). Do NOT backfill inside `resolve_assembly` from the live state — the live orientations are already wrong (translation-only-snapped), so capturing there would lock in the error.
