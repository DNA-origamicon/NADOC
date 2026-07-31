# deformation — diagnostics runbook

Loaded on demand from the `deformation` rule's Diagnostics pointer. Symptom → diagnosis;
not auto-loaded. **Rewritten 2026-07-30** against live code — the previous version's three
"First-Check Invariants" were all wrong or unimplemented (see *Corrections* at the bottom).
Architecture, line anchors and the model live in
[.claude/rules/deformation.md](../rules/deformation.md).

## Symptom index

| # | Symptom |
|---|---|
| 1 | Deformations vanish after a topology mutation (nick / extrude / copy) |
| 2 | Design comes back **bent** (or straight) after a sim / trajectory overlay stops |
| 3 | Ghost planes or the preview overlay stuck in the scene after cancel/confirm |
| 4 | Preview doesn't update when the slider moves |
| 5 | `deformVisuActive` toggle has no visual effect |
| 6 | Displayed angle ≠ typed angle, or helices rotate by different amounts |
| 7 | A cluster-scoped bend hits the wrong helices, or a scope change is ignored |
| 8 | A preview / cancel wrote to disk, or the assembly updated on cancel |
| 9 | A primitive extruded on a bent face stays bent after the bend is deleted |
| 10 | One subsystem stays straight while everything else bends |
| 11 | Polymerized tiles don't close |

---

## 1. Deformations vanish after a topology mutation

**Do NOT start by grepping `Design(` in `lattice.py`.** That was the old first check and it is
obsolete: `lattice.py` has exactly one `Design(` call (`:365`, a *fresh* builder) and zero
`deformations=` kwargs. Every rebuilder (`make_bundle_segment`, `make_bundle_continuation`,
`make_bundle_deformed_continuation`, `make_nick`) returns `existing_design.copy_with(...)`, and
`Design.copy_with` (`models.py:2590`) carries every unlisted field forward. Adding
`deformations=…` there is a no-op.

Real causes, in order:

1. **A `Design(...)` constructed from scratch somewhere else.** `rg 'Design\(' backend/ | rg -v test`
   — there are ~15 hits, but only one true rebuild-from-existing (`cluster_copy.py:180`, which
   already passes a *scoped* list via `_scoped_deformations` `:177`). A new one that forgets is
   the failure mode. Note `assembly_flatten.py:273` deliberately(?) carries neither
   `deformations` nor `cluster_transforms` — if flattening loses a bend, that is the line.
2. **Feature-log truncation.** Revert (`crud.py:10066`) rebuilds `design.deformations` by
   re-seeking the log via `_seek_feature_log` (`crud.py:10578`). If the deformation's
   `DeformationLogEntry` (`models.py:1305`) was never appended (`routes_deformation.py:135`),
   the op is dropped on the next revert/seek even though it applied at the time.
3. **Empty-log path.** Truncating to zero entries routes through the `-2` no-features reset
   because `_seek_feature_log`'s empty-log fast path skips the overlay rebuild. If that reset
   regresses, an empty log leaves stale deformed geometry.
4. **It's a display problem, not a data problem.** Check the design JSON first:
   `rg -c 'deformations' <file>.nadoc` or the `/api/design/deformation/debug` route
   (`routes_deformation.py:203`). If the ops are still there → jump to symptom 5.

## 2. Design comes back bent (or straight) after a sim overlay stops

**Mechanism (verified by reading, 2026-07-30; not reproduced in-app — confirm before "fixing").**

`designRenderer.applyFemPositions(null)` is the universal "stop overlay" call
(`helix_renderer.js:3316`). With `null` it calls `revertToGeometry()` **with no arguments**
(`:3317`), and the no-arg branch writes `nuc.backbone_position` — i.e. the **backend geometry,
which is already deformed**. It does not consult `_currentT`.

So after any overlay teardown (oxDNA / mrDNA display stop, trajectory keyframe clear at
`animation_player.js:1209`):
- deform view **ON** (t=1) → correct by accident.
- deform view **OFF** (t=0) → the design snaps to the **bent** pose while the toggle still reads
  straight.

The fix that was written for this and never wired is `deformView.reapplyLerp()`
(`deform_view.js:378` — literally `_applyLerp(_currentT)`), whose JSDoc says *"call this after
physics is stopped."* Physics (XPBD/FEM) was retired to `archive/physics_xpbd_fem/`, which is
how it lost its only caller. **It has zero callers in all of `frontend/`.**

Before wiring it: `rendering.md` and `RUNBOOK_RENDERING.md` both used to assert this call as a
standing invariant when nothing had ever made it. Decide deliberately — either call it from the
overlay-stop paths, or delete it plus `snapOff`/`setT`/`getT` (also zero callers) and pass the
straight maps to `revertToGeometry(straightPosMap, straightAxesMap)` the way `unfold_view.js:925`
and `:1024` already do.

Related, and **not** this bug: `oxdna_display.test.js:404-425` pins that a late-resolving
`displayJob` fetch does not re-apply positions after `stopAndRestore` — it asserts
`applyFemPositions` was last called with `null`. It says nothing about deform state.

## 3. Ghost planes / preview overlay stuck in the scene

1. Plane ghosts are `_ghostA` / `_ghostB` (`deformation_editor.js:75-76`), removed by
   `_removePlanes()` `:995` (called from `:443`). If a plane persists, `_removePlanes` didn't run.
2. The preview OVERLAY is different: the committed design is kept **solid** as `_frozenRoot`
   (`design_renderer.js:119`, swapped in at `:437-440`) with a translucent ghost of the deformed
   result at `PREVIEW_GHOST_OPACITY = 0.38` (`deformation_editor.js:33`). Teardown is
   `designRenderer.endDeformPreview()` (`design_renderer.js:1514`), called from `_cancelPreview`
   (`deformation_editor.js:489`) — the universal teardown. A lingering solid copy means
   `_cancelPreview` did not run.
3. Scene dimming is separate again: `setToolOpacity` (`design_renderer.js:1491`) from `_dimScene`
   (`deformation_editor.js:1005`), 0.15 while the tool is open. A uniformly dim scene after exit
   = the restore branch of `_dimScene` was skipped.
4. If `confirmDeformation()` (`:332`) throws on an API error, does teardown still run? That path
   is untested — `deformation_editor.js` has **zero unit tests**.

## 4. Preview doesn't respond to the slider

1. The popup must be wired: `main.js:1361` passes **4** callbacks (`onPreview`, `onConfirm`,
   `onCancel`, `onPlaneChanged`). The JSDoc at `bend_twist_popup.js:64` lists only 3 — ignore it.
2. New op vs edit take different routes. New: `POST /api/design/deformation` with
   **`preview` in the request BODY** (`routes_deformation.py:55`, branch `:124`) — *not* a query
   string. Edit: `PATCH /api/design/deformation/{op_id}` (`:148`). Only DELETE takes
   `?preview=` as a real query param (`:178`).
3. `_previewOpId` (`deformation_editor.js:43`) must be deleted before the next preview creates
   one, or ops pile up in `design.deformations` and the visible result is the sum of them.
4. Check `store.currentGeometry` actually changed — the renderer redraws off geometry, not off
   the op.

## 5. `deformVisuActive` toggle has no visual effect

`deform_view.js` owns this and has **6 store subscribers** — find which one should have fired:

| Line | Fires on | Does |
|---|---|---|
| 231 | `straightGeometry` / `straightHelixAxes` change | rebuilds the 3 straight maps, re-applies at current t — **skipped while `cadnanoActive`** |
| 250 | `currentGeometry` change | the big one: no-deformations fast path, cadnano defer (`_straightGeomStale`), auto-embed path, explicit `getStraightGeometry()` fallback (`client.js:1493`) |
| 312 | `deformVisuActive` cleared externally (e.g. unfold on) | cancels the anim, snaps to t=0 |
| 341 | `currentDesign` change | auto-reactivates when the last deformation/transform disappears; skipped under cadnano/unfold |
| 359 | `cadnanoActive` falls | runs the deferred `getStraightGeometry()` |
| 370 | `deformToolActive` falls | re-applies the lerp because tool-exit resets all material opacity |

Checks: `activate()` `:186` awaits `getStraightGeometry()` only when `_straightPosMap.size === 0`
— a stale non-empty map is never refetched. If `straightGeometry` is null the lerp has no t=0
anchor. **Cadnano and unfold both own bead positions and force deform OFF**; `activate()` while
either is active would fight for the lerp, which is why `:344` bails.

## 6. Displayed angle ≠ typed angle, or helices rotate unevenly

Expected, not a bug — see the rule's *Bend parameterization*. κ (`curvature_deg_per_bp`) applies
**only inside `[plane_a_bp, plane_b_bp]`**, and each helix rotates by `κ × its overlap with the
window`. Staggered helices that don't span the window get partial rotation. Move the planes to
bracket the bundle's bp extrema for uniform rotation.

**Trap:** `_effective_bend_window` (`deformation.py:308`) *used* to auto-extend the window across
stagger and no longer does (`:311-324`, it `del`s its `arm_helices` arg). Three comments still
claim it does — `deformation.py:337-340`, `models.py:1110`, `tests/test_periodic_polymer.py:161`.
Don't diagnose from them, and don't delete the function (2 live call sites: `:348`, `:2603`).

## 7. Cluster-scoped bend hits the wrong helices / scope change ignored

- **First check: is the op's `affected_helix_ids` wrong, or its `cluster_ids`?** Scope is
  **frozen into `affected_helix_ids` at create/edit time** and the geometry math reads *only*
  that — `cluster_ids` is metadata. If they drift, geometry silently follows
  `affected_helix_ids`, and a **saved op is never recomputed on load** (re-apply/edit the bend to
  pick up a fix). `GET` debug route `routes_deformation.py:203` echoes both.
- The scope field is **`cluster_ids: List[str]`** (plural, `models.py:1129`). Empty = unscoped
  (all crossing helices). Old `.nadoc` files carrying a singular `cluster_id` **load fine** —
  `models.py` sets no `model_config`, so pydantic's default `extra='ignore'` drops the field
  silently and the op becomes unscoped with its stored `affected_helix_ids` intact. (Corrected
  2026-07-30: the topic file and this runbook both used to claim they "fail to load".)
- The filter is `resolve_cluster_scope(design, cluster_ids, helix_ids)`
  (`deformation.py:2683`). It intersects `affected_helix_ids` with the union of those clusters'
  helices and drops unknown ids — so a stale cluster id silently narrows the scope to nothing.
  **Four callers**: `routes_deformation.py:111` (POST), `core/feature_log_edit.py:162` (edit),
  `routes_loop_skip.py:269` (loop-skip reuses it), and `tests/test_deformation_params_core.py`.
- **PATCH cannot change scope** — params only. The editor must delete + recreate the preview op;
  see `setDeformSessionClusterIds` (`deformation_editor.js:567`, async), driven from
  `bend_twist_popup.js:387/411/432`.
- Two clusters sharing a helix still conflict — the known limitation in the topic file. The
  **mechanism**: `_arm_filter_cluster` (`deformation.py:603`) picks the first **non-default**
  cluster containing that helix and never consults `op.cluster_ids`, so with two non-default
  clusters the winner is arbitrary list order.
- Cluster arm-filtering runs inside every hot path (`deformation.py:1468,1582,1687,1768,2445`);
  child clusters resolve through `parent_cluster_id` at `:676-689`.
- **Symptom "editing a bend from the feature log behaves oddly"**: the edit flow is
  *peel-and-preview*, not in-place PATCH — `_onEditFeature` (`main.js:1441`) deletes the op as a
  preview (`:1513`) and re-enters via the new-op path with `opId=null` (`:1523`). The in-place
  branch in `deformation_editor.js:60-63/510-516` still exists but is **unreachable**; don't
  diagnose from it.

## 8. A preview or cancel wrote to disk / pushed to the assembly

The gate is `wasLastDesignSyncTransient()` (`client.js:358`), set inside
`_syncFromDesignResponse` (`:360`, flag `:357`, cleared at `:419` and `:558`) and read
**synchronously** by the auto-save subscriber at **`app/lifecycle.js:167`**, gate `:174`. (It is
not in `main.js` — any doc citing `main.js:~9272` predates the extraction; main.js is 8,059 lines.)

Tagged transient: `addDeformation` when `preview=true` (`client.js:1337`), `updateDeformation`
**always** (`:1370`), `deleteDeformation` when `preview=true` (`:1378`). If a new client method
does preview-ish work and forgets `{transient: true}`, every slider tick writes the file, fires
SSE and republishes the part to assemblies. The renderer subscriber is intentionally not gated,
so previews still draw.

## 9. Primitive on a bent face stays bent after the bend is deleted

The deformed-continuation replay. `_rebuild_deformed_continuations` (`crud.py:10357`) has exactly
**2 callers** — `delete_feature` (`crud.py:9617`) and `_edit_deformation_feature` (`crud.py:9899`).
If neither ran, nothing re-places.

Then check, in order:
1. Does the request carry `source_bp`? (`BundleDeformedContinuationRequest.source_bp`,
   `crud.py:788`.) **Legacy entries without it re-run with their baked frame by design** —
   graceful degradation, not a bug. Frontend threads it as `sourceBp`:
   `blunt_end_menus.js` → `slice_plane.showDeformed` / `showPlacementDeformed`
   (`_deformedSourceBp`) → `client.addBundleDeformedContinuation`.
2. Is the frame being recomputed? `_build_extrude_deformed_continuation` (`crud.py:1127`) must
   call `deformed_frame_at_bp` (`crud.py:1124,1136`), not trust the baked frame.
3. **Known-unhandled:** a non-DC snapshot wedged *between* two re-placed DCs keeps its stale
   baked helices (best-effort), and slider-seek still shows baked — only delete/edit trigger the
   replay. Pinned by `tests/test_deformed_continuation_replace.py` (4 tests).

## 10. One subsystem stays straight while everything else bends

It isn't in the fan-out. `deform_view.js` `_applyLerp` `:151-157` drives **six** subsystems, each
with a *different* arity — helix renderer (4 args, incl. the base-normal map), domain_ends (2),
unfold_view (2), loop_skip_highlight (3), overhang_locations (3), joint_renderer (1). Anything
that owns positions must implement `applyDeformLerp` and be added there.

If a subsystem bends but is **rotated ~30° at t=0**, it's the base-normal map: only the
`designRenderer` → `helix_renderer.js:3571` pair receives `_straightBnMap`
(`deform_view.js:42`), and dropping it produces exactly that error.

## 11. Polymerized tiles don't close

Closure is a separate concern from the visual bend. Per-tile Kabsch δ ≈ `κ × (seam_length − 1)`
because of the straight +1 ligation step, so it varies with stagger — a κ that looks right in
the scene will not close the ring. Use the panel's "snap κ to close"
(`ui/polymerize_panel.js:418`) → `GET /api/assembly/instances/{id}/periodic-closure`
(`routes_assembly_polymerize.py:171`) → `solve_closing_curvature` (`periodic_polymer.py:300`),
which probes the design and inverts δ_rot(κ). Residual check: `closure_residual` (`:341`).
Oracles: `tests/test_periodic_polymer.py:141-261`.

---

## Known intermittent bug (still open, still unreproduced)

Bend/twist geometry wrong after certain sequences of routing operations — suspected interaction
between deformation bp-index math and routing state (extrude near/far, scaffold topology). Needs
combinatorial coverage: plane positions (near end, ⅓, ½, ⅔, near far end) × HC and SQ ×
extrude amounts, asserting on both `deformed_nucleotide_positions` (`deformation.py:1739`) and
`deformed_helix_axes` (`:2332`).

## Corrections to the previous version of this runbook (2026-07-30)

- **First-Check #1** ("every `Design(...)` in `lattice.py` MUST include `deformations=`") — obsolete
  since the `copy_with` migration. It sent readers to add a redundant kwarg to 4 functions that
  don't construct a `Design` at all. Replaced by symptom 1.
- **First-Check #3** ("`deformView` fetches `getStraightGeometry()` when design changes with
  deformations") — true only on one of four branches; the common path is the backend
  auto-embedding `straight_positions_by_helix` and no fetch happening at all. See symptom 5.
- The diagnosis tree said "check `cluster_transforms`, `overhangs`, `extensions` for the same
  pattern" — same obsolete premise.
- `MAP_DEFORMATION.md`, cited by the rule as the source of the invariant, **never existed
  anywhere in the repo**. `docs/triage/04_deform_tools.md:28,34` still cites it.
