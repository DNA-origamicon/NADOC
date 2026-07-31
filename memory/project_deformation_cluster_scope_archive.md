---
name: deformation-cluster-scope-archive
description: History for [[deformation-cluster-scope]] — the 2026-05-14..05-27 work log (five backend geometry fixes, the feature-log edit rebuild, the edit-in-place rewrite, the PATCH-flood coalescing). Not read in a routine loop.
metadata:
  node_type: memory
  type: project
---

# ARCHIVE — Bend/twist cluster scoping work log (2026-05-14 → 2026-05-27)

> **Read the head first: [project_deformation_cluster_scope.md](project_deformation_cluster_scope.md).**
> This file is history. Every `crud.py:~10xxx` / `main.js:~7xx` line anchor below is DEAD (the
> router carve-up moved the backend into `routes_deformation.py` + `feature_log_edit.py`, and
> `main.js` shrank 16.5k→8k). The *root-cause explanations* below are still accurate and are the
> reason to keep this file — the anchors are not. Audited 2026-07-30 (`/audit-plan`).
>
> **One section below is now obsolete, not just re-anchored:** "Deformation edit is now IN-PLACE
> (no seek)" describes a flow that was later replaced by peel-and-preview. See the head's
> Corrections section.

## What changed

- **Data model**: `DeformationOp.cluster_id: Optional[str]` →
  `DeformationOp.cluster_ids: List[str]` (`backend/core/models.py`). Empty
  list = unscoped (apply to all crossing helices). Hard break, no
  auto-migration: old `.nadoc` files with `cluster_id` will fail to load —
  re-author affected designs.
- **API**: `AddDeformationBody.cluster_ids: list[str]` plus a
  `_resolve_cluster_scope` helper in `backend/api/crud.py` that filters
  `affected_helix_ids` to the union of the named clusters' `helix_ids` and
  drops missing cluster ids. The deformation-branch of
  `/design/features/{i}/edit` follows the same path.
- **Frontend**: `addDeformation(..., clusterIds = [])`; the deformation
  editor stores a per-session `_sessionClusterIds`. `setDeformSessionClusterIds`
  is async and rebuilds the live preview op when called mid-session (params
  update via PATCH can't change scope; delete+recreate is required).
- **UI**: multi-select cluster picker in `frontend/src/ui/bend_twist_popup.js`
  with All / None buttons. Hidden when the design has 0–1 clusters.
  Defaults to `[activeClusterId]`, falls back to the single cluster, else
  `[]` (unscoped).

## Why this matters (and what it doesn't fix)

- "Different parts can occupy the same bp range" works *as long as the
  clusters have disjoint `helix_ids`*. Two clusters sharing a helix still
  share a single axis, so the bend deforms the axis for both — Phase 2
  (per-domain sub-axis isolation) is deferred.

## `_frame_at_bp` arm anchor — fixed (2026-05-14)

After fixing the helix-axis sampling to pass arm-local bp (`local_bp +
bp_offset`), the axis still drifted to the old "translate forward" position
on Ultimate Polymer Hinge — but only the axis, not the nucleotides. Root
cause: `_frame_at_bp` was using `helices[0].bp_start` as the arm anchor for
converting global op-plane bp to arm-local. When the first helix in the
arm wasn't the one with the smallest bp_start (typical when a Scaffold
Cluster spans the whole design and `design.helices` isn't ordered by
bp_start), this offset by `(helices[0].bp_start − arm_min_bp_start) × RISE`
from where the centroid math placed things. The nucleotide path appeared
correct because the buggy anchor and its own `arm_min_bp_start` subtraction
happened to cancel inside `nucleotide_positions_arrays`, but the axis path
exposed the mismatch. Fixed by replacing `helices[0].bp_start` with
`min(h.bp_start for h in helices)` in `_frame_at_bp`. Regression covered
by `test_frame_at_bp_uses_min_bp_start_not_first_helix`. The same anchor
convention is already used by `_precompute_arm_frames` (takes `arm_min_bp`
as a parameter from callers).

## Apply race + axis arm-local bp — fixed (2026-05-14)

Two follow-on bugs surfaced once cluster-scoped bend was actually exercised
on Ultimate Polymer Hinge 191016.nadoc:

**Apply doesn't bend (race).** `confirmDeformation` called
`_clearPreviewSession()` first, which delegates to `_cancelPreview()` —
that fires `api.deleteDeformation(opId, preview=true).catch(...)` as a
fire-and-forget, no await. Then the awaited `api.addDeformation(...)`
runs in parallel. Both responses come back to the client and the *last*
one to arrive overwrites `currentDesign` via `_syncFromDesignResponse`.
When the DELETE response arrived last, the client store went back to a
no-deformations state even though the server state and feature_log were
correct — visible as "Apply doesn't bend but the feature-log entry
appears." Fixed by awaiting the DELETE sequentially before the POST in
`confirmDeformation` (inlining the cleanup so `_clearPreviewSession`'s
fire-and-forget never runs in the confirm path).

**Helix axis lines drift from nucleotides during preview.** In
`deformed_helix_axes`, the per-helix sampling loop iterated `local_bp ∈
[0, h.length_bp)` and passed that value directly to `_frame_at_bp(...)`
— but `_frame_at_bp` expects **arm-local** bp, not helix-local. For any
helix whose `bp_start ≠ arm_min_bp_start` (routing-adjusted short
helices that begin mid-bundle), the axis line was sampled at the wrong
Z. The nucleotide path correctly converted with `p − arm_min_bp_start`.
Fixed by adding `bp_offset = h.bp_start − arm_min_bp` and passing
`local_bp + bp_offset` to `_frame_at_bp`. Regression covered by
`test_helix_axis_samples_use_arm_local_bp_for_off_anchor_helices`.

## Centroid projection — fixed in `_bundle_centroid_and_tangent` (2026-05-14)

When a cluster's helices have mixed `bp_start`s — typical for routing-adjusted
sub-clusters where short helices begin mid-bundle (e.g. Ultimate Polymer
Hinge's Geometry Cluster 3 with bp_starts 114/123/129/135) — adding *any*
deformation op covering that cluster shifted every helix in it forward
along the tangent by `(avg(bp_start) − arm_min_bp_start) × BDNA_RISE_PER_BP`.
At angle=0 the bend was visually a no-op but the cluster still translated
~2.5 nm in Z. Plane-A drag flickered between shifted/not-shifted because the
preview op was deleted+recreated on every drag-end.

Root cause: `_bundle_centroid_and_tangent` averaged raw `axis_start`s, which
sit at each helix's own `bp_start`. But the spine math uses
`arm_min_bp_start` as the reference for that centroid. The fix projects each
`axis_start` back along the tangent to `arm_min_bp_start` before averaging,
so `centroid_0.z = arm_min_bp_start × RISE` for canonical Z-aligned helices
and the identity `axis_deformed == axis_orig` holds for the angle=0 case.

Single-arm same-bp_start designs are unaffected (projection is a no-op when
`h.bp_start == arm_min_bp_start` for every helix). Regression covered by
`test_mixed_bp_start_cluster_zero_angle_bend_does_not_translate`. This change
touches every caller of `_bundle_centroid_and_tangent` — full suite still
green vs pre-existing failures.

## Per-helix short-circuit — fixed by `_ops_affecting_helix` (2026-05-14)

Adding *any* preview deformation op to a design caused un-affected helices to
shift by a small, per-cluster amount even before angle/twist controls were
touched. Visible as "the other clusters translate forward when I place plane
A on this cluster." Root cause: when no op covers a helix, the frame-math
path still ran with that helix's arm, and the
`spine + R @ cs_offset = axis_orig` identity doesn't hold exactly when the
arm has mixed `bp_starts` or axis offsets — every helix outside the bent
arm drifted by `(centroid_0.z - h_start.z + (bp_start - arm_min_bp_start) * RISE)`.

Fix: short-circuit four nucleotide/atomistic paths and the helix-axis path
with `_ops_affecting_helix(design, helix.id)`. When the result is empty
(no op covers this helix), skip frame math and return the straight geometry
+ cluster rigid transforms. Regression covered by
`test_unaffected_cluster_does_not_translate_when_other_cluster_bent`.

The math drift is a pre-existing identity-preservation issue in
`deformed_nucleotide_positions` / `deformed_helix_axes`; we sidestep it
rather than fixing the root math, which would require revisiting the
centroid / cs_offset / arm_min_bp convention used everywhere in
`backend/core/deformation.py`. The short-circuit is also a perf win.

## Default-cluster leak — fixed by `_arm_filter_cluster` (2026-05-14)

When a design has an auto-created umbrella cluster
(`ClusterRigidTransform(is_default=True, helix_ids=<all>)`) plus specific
sub-clusters, the physics-layer arm filter at five sites in
`backend/core/deformation.py` (~1279/1384/1491/1557/2120) picked
`clusters[0]` — which could be the default cluster. The default cluster
contains every helix, so the filter became a no-op and a bend scoped to a
single sub-cluster bled across helices in OTHER sub-clusters. Now the five
sites call `_arm_filter_cluster(clusters)` which prefers the first
non-default cluster, falling back to `clusters[0]` only when no specific
cluster exists. Regression covered by
`tests/test_deformation_clusters.py::test_default_cluster_does_not_leak_bend_to_other_clusters`.

## Unequal-length bundles ("teeth") — fixed 2026-05-26

teeth.nadoc bends only half its helices and plane B couldn't reach the structure
end. Two independent bugs, both triggered by a bundle whose helices have unequal
lengths (teeth.nadoc: rows 0–1 = backbone bp 0–251; rows 2–3 = teeth bp 0–209
with internal scaffold gaps):

- **Only full-length helices bent.** `helices_crossing_planes`
  ([backend/core/deformation.py](backend/core/deformation.py)) required a helix to
  cover BOTH planes (`bp_start ≤ lo and bp_start+len−1 ≥ hi`). With plane B at 230,
  the teeth (end 209) failed and were dropped from `affected_helix_ids`, then
  short-circuited straight by `_ops_affecting_helix`. Fix: **overlap** test
  (`bp_start ≤ hi and bp_start+len−1 ≥ lo`). The bend math is bp-parameterized
  (`arc_bp = min(target_bp, local_b) − local_a`) so a partially-spanning helix
  bends over the bp range it occupies and ends partway along the arc — no arm/
  centroid change (arm was already all 16 via the default umbrella cluster, so no
  LESSONS-E1 centroid shift). Regression: `test_geometry.py::
  test_helices_crossing_planes_includes_partially_spanning_helix` +
  `test_short_helix_bends_when_window_extends_past_its_end`.
- **Plane B capped at the mean clamp (bp 230).** `_pickBpFromPoint`
  ([frontend/src/scene/deformation_editor.js](frontend/src/scene/deformation_editor.js))
  AVERAGED each helix's nearest bp after clamping each to its own `[0, lengthBp−1]`
  → (8·251 + 8·209)/16 = 230, unreachable past. Fix: snap to the bp of the
  NEAREST helix axis (not the average), so past the teeth's end only a long helix
  is nearby → plane reaches bp 251. Also `_defaultBpForPlaneB` now uses the
  LONGEST helix's far end (was `Math.min` = shortest, defaulted to 209).

NOTE: a saved op stored before the fix keeps its stale 8-helix `affected_helix_ids`
on load (not recomputed). Re-apply / edit the bend to pick up all helices.

## Editing a deformation feature must rebuild from the LOG, not the live design (2026-05-26)

Editing a twist/bend via the feature-log ✎ silently failed to save (404, swallowed
by the frontend), and the feature-log slider didn't return to its pre-edit position.

**Root cause (two bugs).**
1. `_onEditFeature` ([frontend/src/main.js](frontend/src/main.js)) seeks the design
   back to `featureIndex-1` to drive the edit preview. That rolls the target op
   (and any LATER deformation — e.g. teeth.nadoc's bend at log idx 10 when editing
   the twist at idx 9) OUT of `design.deformations`, and the preview adds a transient
   `preview=true` op. The old `_edit_deformation_feature`
   ([backend/api/crud.py](backend/api/crud.py)) looked the op up by id in the live
   (seeked) `design.deformations` → not found → **HTTP 404**, which the confirm
   handler didn't null-check → "doesn't save."
2. The confirm branch set `_editContext = null` BEFORE `deformExitTool()`, so the
   `onExit` callback (which seeks back to `ctx.priorCursor`) saw null and never ran
   → slider stuck at the seeked-back pre-feature position.

**Fix.**
- Backend: `_edit_deformation_feature` now rebuilds the deformation set from the
  LOG (the source of truth) — update the entry's `op_snapshot`, then
  `rebuilt_ops = [e.op_snapshot for e in new_log if feature_type=='deformation']`,
  and `copy_with(deformations=rebuilt_ops, feature_log_cursor=-1)`. Robust to the
  seeked-out state, keeps later ops (the bend), drops the preview op (no log entry).
  Works because deformations are geometric-only (DTP-6a) → live topology is the
  latest regardless of the preview seek. Raises 409 if `op_snapshot` is None
  (evicted/broken — revert + re-apply instead).
- Frontend: the confirm branch no longer clears `_editContext` early, so
  `deformExitTool()` → `onExit` restores the cursor to `priorCursor`; added an
  error toast on a null edit response.
- Test: `tests/test_feature_log_snapshot.py::
  test_edit_deformation_after_seek_back_saves_and_keeps_later_ops` (bundle-create
  snapshot + twist + bend, seek back, add preview op, edit twist → 200, twist
  updated, bend kept, preview dropped, cursor -1). Note the test MUST create the
  bundle via the endpoint so a snapshot precedes the deformations — otherwise the
  twist is at log idx 0 and `seek(position=-1)` means "seek to end" (no rollback),
  hiding the bug.

## Deformation edit is now IN-PLACE (no seek) — fast + popup opens immediately (2026-05-26)

Two follow-on UX/perf problems with the edit flow:
1. Clicking ✎ on a twist/bend entry didn't open the popup until the user clicked into the
   3D canvas — `_watchDeformState()` (which opens the popup when the deform state hits BOTH)
   was only called from the canvas `pointerdown` handler, never after `_onEditFeature`.
2. Edit-open was slow (several seconds, several GETs): `_onEditFeature` did
   `await _seekFeaturesWithDelta(featureIndex-1)` (full pre-state geometry recompute) AND the
   popup's `openPopup` auto-fired an initial preview → `previewDeformation` added a `preview=true`
   op (another recompute). Plus a `getStraightGeometry` fetch on tool activation.

**Fix (frontend only; the backend `_edit_deformation_feature` rebuild-from-log already supports
editing on the live/latest state):**
- `_onEditFeature` ([main.js](frontend/src/main.js)) NO LONGER seeks. It edits the op IN PLACE on
  the current state, passes `op.id` + `op.params` to `startToolForEdit(t,a,b,opId,origParams)`,
  and calls `_watchDeformState()` itself so the popup opens immediately.
- `_watchDeformState` passes `skipInitialPreview = !!_editContext` to `openPopup`; in edit mode the
  op is already applied so the popup does NOT auto-fire a preview (cuts a redundant recompute).
- [deformation_editor.js](frontend/src/scene/deformation_editor.js) gained edit-in-place state
  (`_editOpId`, `_editOrigParams`, `_editDirty`, `_editCommitted`). `previewDeformation` in edit
  mode PATCHes the LIVE op (`api.updateDeformation(opId, params)`) instead of seek+add-preview —
  one round-trip per slider change, and the preview now shows the correct COMBINED geometry (the
  other deformations stay; the old seek dropped them). `_exitTool` silently reverts to
  `_editOrigParams` on cancel/Esc UNLESS `markEditCommitted()` was called (main.js calls it right
  before `editFeature`). On confirm, editFeature rebuilds from the log (committed params win).
- Cursor: no seek means the cursor never moves during edit; confirm's editFeature sets it to
  latest (-1); if the user was mid-scrub (`priorCursor != -1`) onConfirm seeks back. Cancel leaves
  the cursor untouched (silent PATCH revert), so the old onExit blanket-seek was removed.
- Net edit-open cost: ZERO geometry calls (popup opens instantly); the first recompute happens only
  when the user moves a slider. Plane edits during edit apply on confirm (no live plane-drag preview
  in edit mode — `updateDeformation` is params-only; acceptable, noted).
- Verified: `npx vite build` passes. NOT yet click-verified in app (local :8000 backend was hung).

### Preview PATCH flood during a slider drag — fixed 2026-05-27
Editing a twist/bend (the popup's value slider fires `input` on every drag tick — ~40 events) flooded
the backend: each `previewDeformation` → `api.updateDeformation` PATCH → `_syncFromDesignResponse` →
a SEPARATE `GET /design/geometry` (the PATCH response carries no embedded geometry), with NO in-flight
guard → ~40 concurrent PATCH+geometry round-trips, each ~30 s under saturation. Fix
([deformation_editor.js](frontend/src/scene/deformation_editor.js) `previewDeformation`): coalesce the
update path (both `_editOpId` edit-in-place and `_previewOpId`) with `_updateInFlight` +
`_pendingUpdateParams` — if a PATCH is in flight, stash the latest params and bail; the in-flight
handler flushes the newest when it finishes (latest wins, render keeps up at backend speed). Cleared in
`_clearPreviewSession`. Verified (throwaway Playwright): a 20-input drag → 2 PATCH + 2
`/design/geometry` (was ~20-40 each). Same in-flight-guard pattern as the assembly refresh coalescing
([[polymerize-origami]]).
