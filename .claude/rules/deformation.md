---
name: deformation
description: Bend/twist deformation — the geometric overlay. Preview/confirm flow, cluster scoping, straight↔deformed lerp, feature-log replay.
paths:
  - "backend/core/deformation.py"
  - "backend/core/periodic_polymer.py"
  - "backend/api/routes_deformation.py"
  - "frontend/src/scene/deformation_editor.js"
  - "frontend/src/scene/deform_view.js"
  - "frontend/src/ui/bend_twist_popup.js"
  - "frontend/src/ui/blunt_end_menus.js"
---

# deformation

**Audited against live code 2026-07-30.** Line anchors are dated; `main.js` and `crud.py` are
under active carve-up, so **re-grep any `file:NNNN` before citing it**. The previous version of
this rule was wrong in its two most-obeyed sections (the `CRITICAL` invariant and the
`MAP_DEFORMATION.md` link) — see *Removed API* at the bottom for what it taught that never
existed or no longer applies.

## The one-line model

A deformation is a **geometric overlay**, never a topology edit (Three-Layer Law, layer 2).
`design.deformations: List[DeformationOp]` is the whole persisted state; nucleotide positions
and helix axes are re-derived from it on every geometry request. Nothing is ever "baked into"
the strand graph. The single exception — deformed *continuations* — is documented below and is
itself replayable.

## File map

| File | LOC | Role |
|---|---|---|
| `backend/core/deformation.py` | 2,703 | The math. 12 public fns, 51 defs. Bend/twist application, cluster-scoped rigid transforms, arm filtering |
| `backend/core/periodic_polymer.py` | ~370 | κ-closure for polymerized tiles: `derive_periodic_delta:272`, `solve_closing_curvature:300`, `closure_residual:341` |
| `backend/api/routes_deformation.py` | — | All 5 deformation routes (carved out of `crud.py`; see its module docstring) |
| `frontend/src/scene/deformation_editor.js` | 1,031 | Plane-placement tool + preview session. **Module singleton — `initDeformationEditor` returns nothing**, 21 top-level exports |
| `frontend/src/scene/deform_view.js` | 417 | The straight↔deformed lerp fan-out. **One export**, `initDeformView` |
| `frontend/src/ui/bend_twist_popup.js` | 493 | Angle/direction sliders + the cluster-scope multi-select |
| `frontend/src/ui/blunt_end_menus.js` | 200 | Threads `sourceBp` into deformed continuations |

Deformation code lives well outside these globs — `main.js` (71 hits), `api/client.js` (36),
`ui/feature_log_panel.js` (13), `scene/helix_renderer.js` (11), `scene/unfold_view.js` (11),
`app/lifecycle.js` (the transient-save gate). Those belong to `main-init` / `api-and-state` /
`rendering` / `unfold`; this rule owns the *deformation semantics* in them.

## Backend

### Public surface (`deformation.py`) — grep, don't trust a list

```bash
rg '^def [a-z]' backend/core/deformation.py          # 12 public fns
rg 'def _' backend/core/deformation.py | wc -l       # ~39 private
```
The load-bearing four: `deformed_nucleotide_positions(helix, design)` `:1739` ·
`deformed_helix_axes(design)` `:2332` · `deformed_frame_at_bp(design, source_bp, ref_helix_id=None)`
`:2495` · `compute_bend_centers(design)` `:2567`. Array-path twins for the hot loops:
`deformed_nucleotide_arrays` `:1424`, `deform_extended_arrays` `:1540`,
`apply_deformations_to_atoms` `:1629`.

**Direction of the dependency (the old rule had this backwards):** `geometry.py` knows nothing
about deformations — it has zero `deformations` hits and two comments saying so
(`geometry.py:375`, `:461`). `deformation.py` imports `nucleotide_positions` *from* `geometry.py`
and short-circuits when there is nothing to apply:

```python
# deformation.py:1752
if not design.deformations and not clusters:
    return nucleotide_positions(helix)
```

Callers of `deformed_nucleotide_positions` are `physics/fem_solver.py:2227`,
`api/headless_corner_build.py:159,502`, `core/cando_autorefine.py:318`,
`core/assembly_connectors.py:124`.

### Model

`DeformationOp` (`models.py:1118`) has **7 fields**: `id`, `type` (`Literal['twist','bend']`),
`plane_a_bp`, `plane_b_bp`, `affected_helix_ids`, **`cluster_ids: List[str]`** (`:1128`),
`params`. `params` is a discriminated union on `kind`: `TwistParams` (`:1091`, 3 fields —
`total_degrees` **or** `degrees_per_nm`) / `BendParams` (`:1098`, 3 fields —
`curvature_deg_per_bp` `:1114`, `direction_deg` `:1115`).
`Design.deformations` is `models.py:2250`.

### Cluster scoping is half the module — see [project_deformation_cluster_scope](../../memory/project_deformation_cluster_scope.md)

`cluster` matches **229 lines** of `deformation.py`. Empty `cluster_ids` = unscoped (all crossing
helices); a non-empty list filters `affected_helix_ids` to the union of those clusters' helices.
`resolve_cluster_scope(design, cluster_ids, helix_ids)` `deformation.py:2683` has **four**
callers: `routes_deformation.py:111` (POST), `core/feature_log_edit.py:162` (the edit path),
**`routes_loop_skip.py:269`** (loop-skip reuses deformation's scoping semantics — widen your blast
radius accordingly), and `tests/test_deformation_params_core.py`. Arm filtering by cluster runs
inside every hot path: `:1468`, `:1582`, `:1687`, `:1768`, `:2445`; child clusters via
`parent_cluster_id` at `:676-689`.

**The two mechanisms don't talk to each other.** `resolve_cluster_scope` freezes scope into
`op.affected_helix_ids` at create/edit time; the render-time filter `_arm_filter_cluster:603` picks
the first **non-default** cluster containing the helix and **never reads `op.cluster_ids`**. So
`affected_helix_ids` is the real enforcement, `cluster_ids` is metadata, and a helix in two
non-default clusters resolves by arbitrary list order. Saved ops are never recomputed on load.

### Routes

All mount under `/api` (`main.py:226`). Find them with
`rg '@router\.(get|post|patch|delete)' backend/api/routes_deformation.py`.

| Method | Path | File:line | Notes |
|---|---|---|---|
| POST | `/api/design/deformation` | `routes_deformation.py:90` | Add op. **`preview` is a BODY field** (`:55`, branch `:124`), not a query param |
| PATCH | `/api/design/deformation/{op_id}` | `routes_deformation.py:148` | Params only, no undo push, no scope change |
| DELETE | `/api/design/deformation/{op_id}` | `routes_deformation.py:177` | `preview` **is** a real `Query(False)` here (`:178`) |
| GET | `/api/design/deformation/debug` | `routes_deformation.py:203` | |
| POST | `/api/design/deformation/validate` | `routes_loop_skip.py:244` | lives with loop-skip, not here |
| POST | `/api/design/loop-skip/apply-deformations` | `crud.py:11065` | loop-skip's own overlay path |
| GET | `/api/design/deformed-frame` | `crud.py:1112` | |

⚠️ The POST/DELETE `preview` asymmetry (body vs query) is a real trap; the old rule's
`?preview=true` was only ever correct for DELETE.

## Frontend

### Init (verified 2026-07-30)

```js
// deformation_editor.js:97 — 7 positional args, returns nothing
initDeformationEditor(scene, camera, canvas, controls, designRenderer, onExit, onPlaneDragEnd = null)  // main.js:1333
// bend_twist_popup.js:65 — 4 callbacks (its own JSDoc :64 lists only 3 — stale)
initBendTwistPopup({ onPreview, onConfirm, onCancel, onPlaneChanged })                                 // main.js:1361
// deform_view.js:25 — 7 getters; param 3 is passed literal null
initDeformView(designRenderer, getBluntEnds, _getCrossoverMarkers, getUnfoldView,
               getLoopSkipHighlight, getOverhangLocations, getJointRenderer)                            // main.js:1558
```

### State machine

`deformation_editor.js:37` — `const STATE = { IDLE, AWAITING_A, A_PLACED, BOTH }`. Module-level
`let _state` `:39`, written by `_setState` (`:111,132,146,168,174`), read by `getState()` `:1010`
and `isActive()` `:180`, re-exported as `STATES` `:1013` and consumed in main.js as
`DEFORM_STATES` (`main.js:1413,1418`). The terminal state is **`BOTH`** — there is no
`BOTH_PLANES_PLACED`.

Flow: `previewDeformation` `:366` (per slider change, no undo) → `confirmDeformation` `:332` /
`cancelDeformation` `:357`. `_previewOpId` `:43` is the preview op's id; `_cancelPreview` `:486`
is the universal teardown and calls `designRenderer.endDeformPreview()` `:489`.
`PREVIEW_GHOST_OPACITY = 0.38` is defined at **`deformation_editor.js:33`** and passed to
`beginDeformPreview` `:380` (defined `design_renderer.js:1503`). Scene dimming is
`setToolOpacity` (`design_renderer.js:1491`) called from `_dimScene` `:1005` (0.15 / 1.0).

### The lerp fan-out — 6 subsystems, 6 different arities

`deform_view.js` `_applyLerp` `:145-158` is the only thing that drives deformed display:

| Line | Call | Arity |
|---|---|---|
| 151 | `designRenderer.setAxisShaftMode(_shaftMode)` | — |
| 152 | `designRenderer.applyDeformLerp(posMap, axesMap, **bnMap**, t)` → `helix_renderer.js:3571` | **4** |
| 153 | `getBluntEnds().applyDeformLerp(axesMap, t)` → `domain_ends.js:670` | 2 |
| 154 | `getUnfoldView().applyDeformLerp(posMap, t)` → `unfold_view.js:1263` | 2 |
| 155 | `getLoopSkipHighlight().applyDeformLerp(posMap, axesMap, t)` → `loop_skip_highlight.js:209` | 3 |
| 156 | `getOverhangLocations().applyDeformLerp(posMap, _axesMap, t)` → `overhang_locations.js:335` | 3 (axes ignored) |
| 157 | `getJointRenderer().applyDeformLerp(t)` → `joint_renderer.js:2981` | 1 |

**Add a subsystem that owns positions and it must join this list**, or it stays straight while
everything else bends. The `getBluntEnds` slot is wired to `initDomainEnds` (`main.js:2988`) —
the parameter name is legacy (`blunt_ends.js` no longer exists).

**The base-normal map is not optional.** `_straightBnMap` (`deform_view.js:42`,
`Map<"helix:bp:dir", Vector3>`) is fed only to the 4-arg pair; dropping it produces a ~30° slab
error at t=0. `helix_renderer.js:2225` recomputes the same quantity and says so.

### Store keys (all 4 names verified correct)

| Key | store.js | Semantics |
|---|---|---|
| `deformToolActive` | `:46` | Tool open. **13 readers/subscribers** across main.js, design_renderer, deform_view, selection_filter |
| `deformVisuActive` | `:207` | Deformed geometry visible (lerp t=1). Independent of the tool; 18 sites |
| `straightGeometry` | `:214` | t=0 anchor, positions |
| `straightHelixAxes` | `:220` | t=0 anchor, axes (`currentHelixAxes` `:37` is its deformed counterpart) |

`deformVisuActive`/`straightGeometry`/`straightHelixAxes` are persisted (`store.js:389`);
`deformToolActive` is in the other slice list (`:398`).

### How selection is actually blocked (the old rule was mechanically wrong)

There are **three** `deformToolActive` subscribers in `main.js`, not one and not two:

1. `main.js:4285` — hides the slice plane, minimap, highlighter; resets `#mode-indicator`.
2. `main.js:4319` — forces `hull-prism` → `full`, saves `_savedSelectableTypes`, then **zeroes
   all 10 `selectableTypes` flags** (`:4330-4336`); restores them on deactivate (`:4338-4342`).
   *This* is what disables selection — every filter reads `selectableTypes` and returns false.
3. `main.js:6854` — mutual exclusion with the translate/rotate tool.

The capture-phase canvas listeners (`main.js:694-718`, **not** ~119-143) do **not** blanket-block
anything. `pointermove` `:694` stops nothing. `pointerdown` `:699` calls `handlePointerDown`
(aliased `deformPointerDown`, `main.js:79`) and only `stopImmediatePropagation()` when it
actually consumed the event; `deformation_editor.js:199` returns false immediately for any
non-left button, so right/middle-click always passes through. `pointerup` `:712` stops only when
`_deformConsumedDown && button === 0` — deliberate, so an unconsumed drag still lets
OrbitControls exit (comment `:709-711`).

### Transient sync — previews must not touch disk or assemblies

`_syncFromDesignResponse(json, {skipGeometry, transient})` `client.js:360` sets
`_designSyncTransient` `:357` during the `setState` and clears it on both exits (`:419`, `:558`).
The auto-save subscriber reads it synchronously — it now lives in
**`app/lifecycle.js:167`**, gate at `:174` (it is *not* in main.js; main.js is 8,059 lines, so the
old "~9272" anchor could not have resolved for a long time).

Tagged transient: `addDeformation` when `preview=true` (`client.js:1337`), `updateDeformation`
**always** (`:1370`), `deleteDeformation` when `preview=true` (`:1378`). Commits
(`addDeformation` preview=false, `editFeature`) are not, so they save → SSE → assembly part
update. Net: **assemblies update only on Apply.** The renderer subscriber is not gated, so
previews still draw.

## Bend parameterization (2026-05-28, still true)

`BendParams.curvature_deg_per_bp` (κ) is the canonical storage — not a window-spanning angle.

- κ applies inside `[plane_a_bp, plane_b_bp]` only. **No auto-extension.** Outside, straight.
- Displayed "Angle" = `κ × (plane_b − plane_a)`, so the typed θ matches the scene.
- Staggered helices rotate by `κ × overlap_with_window` — partial spans get partial rotation. To
  get uniform rotation, bracket the bundle's bp extrema with the planes.
- Polymer closure is separate: per-tile Kabsch δ ≈ `κ × (seam_length − 1)` because of the
  straight +1 ligation step. The polymerize panel's "snap κ to close" button
  (`ui/polymerize_panel.js:418`) calls `GET /api/assembly/instances/{id}/periodic-closure`
  (`routes_assembly_polymerize.py:171` → `solve_closing_curvature` `:194`), which probes the
  design and inverts δ_rot(κ) for exact closure regardless of stagger.

## Feature-log revert / delete / replay

A bend logs a lightweight **delta** entry `DeformationLogEntry` (`models.py:1305`, 4 fields;
constructed `routes_deformation.py:135`) — not a baked topology snapshot.

- **Revert** `POST /api/design/features/{i}/revert` (**still `crud.py:10066`**, not
  `routes_feature_log.py`) accepts delta entries, truncates to `[0..i-1]` and re-seeks via
  `_seek_feature_log` (`crud.py:10578`), rebuilding `design.deformations` without this entry.
  Empty truncation routes through the `-2` no-features reset because `_seek_feature_log`'s
  empty-log fast path skips the overlay rebuild.
- **Delete** `DELETE /api/design/features/{i}` (`crud.py:9499`, handler `delete_feature` `:9500`)
  drops the op via replay.
- **Deformed continuations (Phase 2, 2026-06-14).** `make_bundle_deformed_continuation`
  (`lattice.py:1234`) bakes deformed world-coords into the new helices, but the op is
  **replayable**: `BundleDeformedContinuationRequest.source_bp` (`crud.py:788`) is stored and
  `_build_extrude_deformed_continuation` (`crud.py:1127`) recomputes the frame live via
  `deformed_frame_at_bp` (`crud.py:1124,1136`). `_rebuild_deformed_continuations`
  (`crud.py:10357`) forward-replays the log from the first DC entry, re-running replayable ops
  through `_edit_dispatch_run` (`crud.py:9815`) and accepting baked post-state for
  non-replayable ones (auto-*/circle). Exactly **2 callers**: `delete_feature` (`crud.py:9617`)
  and `_edit_deformation_feature` (`crud.py:9899`). Bend gone → recomputed frame is straight →
  the segment re-places flat.
  Frontend threads `sourceBp`: `blunt_end_menus.js` → `slice_plane.showDeformed` /
  `showPlacementDeformed` (`_deformedSourceBp`) → onPlace/onExtrude →
  `client.addBundleDeformedContinuation`.
  **Not handled:** a non-DC snapshot wedged between two re-placed DCs keeps stale baked helices;
  slider-seek still shows baked (only delete/edit trigger the replay); legacy DCs without
  `source_bp` degrade gracefully to their baked frame.

## Invariants

1. **Topology is never bent.** Deformations are layer-2 output. If a fix wants to write deformed
   coordinates back into helices/strands, stop — the only sanctioned bake is the DC path above,
   and it stores `source_bp` precisely so it can be un-baked.
2. **`design.deformations` survives rebuilds automatically.** All of `lattice.py`'s rebuilders
   (`make_bundle_segment:383`, `make_bundle_continuation:737`,
   `make_bundle_deformed_continuation:1234`, `make_nick:1508`) return
   `existing_design.copy_with(...)` (16 sites), and `Design.copy_with` (`models.py:2590`) carries
   *all* unlisted fields forward by `model_copy(update=...)`. **Do not add
   `deformations=existing_design.deformations` to these calls** — it is a no-op. The one true
   `Design(...)` rebuild-from-existing in the backend is `cluster_copy.py:180`, and it already
   passes a *scoped* list (`_scoped_deformations`, `:177`). `lattice.py` has exactly **1**
   `Design(` call (`:365`, a fresh builder) and **0** `deformations=` kwargs.
3. **Preview ops are single-instance.** `_previewOpId` must be deleted before
   `previewDeformation` creates the next one, or preview ops accumulate in `design.deformations`.
4. **Scope changes need delete+recreate.** PATCH updates params only — it cannot change
   `cluster_ids` (see the topic file's `setDeformSessionClusterIds`).
5. **Every position-owning subsystem must be in the `_applyLerp` fan-out** (`deform_view.js:151-157`).
6. **Transient mutations must stay transient.** Any new preview-ish client method has to pass
   `{transient: true}`, or the previewed bend gets written to disk and pushed to assemblies.

## Traps — code and comments that contradict the code

- **`_effective_bend_window(op, arm_helices)` (`deformation.py:308`) no longer auto-extends.** It
  returns the typed planes and `del`s its second arg (`:311-324`, docstring says so explicitly).
  Three places still claim it auto-extends: `deformation.py:337-340`, `models.py:1110`
  (BendParams docstring), `tests/test_periodic_polymer.py:161`. It *is* called (2 sites: `:348`,
  `:2603`) — don't delete it, and don't believe the comments.
- **`bend_twist_popup.js:64` JSDoc lists 3 callbacks; the call site passes 4.**
- **`deform_view.js` exposes 8 methods; 4 are dead** — `reapplyLerp` `:378`, `snapOff`, `setT`,
  `getT` have **zero callers in all of `frontend/`** (plus `dispose`). Two stale comments in
  `helix_renderer.js:555,595` still reference `reapplyLerp`. **`rendering.md` and
  `RUNBOOK_RENDERING.md` used to state "always call `deformView.reapplyLerp()` after
  `revertToGeometry()`" — that invariant was never implemented.** If a deformed design comes back
  straight after a sim overlay toggles off, that is a real symptom, but the fix is not to call a
  function nothing has ever called; see the runbook.
- **`getBluntEnds` / `bluntEnds`** name a module called `domain_ends.js`. `blunt_ends.js` does
  not exist.

## Test coverage (honest, 2026-07-30)

**Backend is well covered; the frontend has none.**

| Area | Tests |
|---|---|
| `tests/test_deformation_clusters.py` | 10 |
| `tests/test_deformation_params_core.py` | 9 |
| `tests/test_deformation_revert.py` | 5 |
| `tests/test_deformed_continuation_pose.py` | 3 |
| `tests/test_deformed_continuation_replace.py` | 4 |
| `tests/test_fem_curvature_validation.py` | 5 |
| `tests/test_periodic_polymer.py` | κ/closure oracles `:141-261` |
| `frontend` — `deformation_editor.js` (1,031), `deform_view.js` (417), `bend_twist_popup.js` (493) | **0** |

Only peripheral vitest touches deform *state* (`selection_filter.test.js`,
`view_tool_buttons.test.js`, `blunt_end_menus.test.js`, `lifecycle.test.js`,
`keyboard_shortcuts.test.js`) — none exercises these three modules. There is **no test anywhere
for `applyDeformLerp` behaviour**; `devtools_helpers.test.js:13` only mocks the name.
`oxdna_display.test.js:404-425` is about `applyFemPositions` after `stopAndRestore` — it is *not*
a deformation test, despite being cited as one.

## Removed API — do not resurrect

| Name | Reality |
|---|---|
| `compute_bundle_centroid` | Never/no longer exists. Nearest: private `_bundle_centroid_and_tangent(helices)` `deformation.py:189` |
| `world_frame_at` | Gone → `deformed_frame_at_bp` `deformation.py:2495` (private `_frame_at_bp` `:460`) |
| `compute_loop_skip_deformations` | Zero hits repo-wide |
| `BOTH_PLANES_PLACED` | State is `BOTH` (`deformation_editor.js:37`) |
| `deformPointerDown` (as a definition) | Import alias in main.js for `handlePointerDown` `deformation_editor.js:198` |
| `geometry.py` calls `deformed_nucleotide_positions` | Backwards — `deformation.py` imports from `geometry.py` |
| `deformations=` kwarg in `lattice.py` `Design(...)` | Obsolete; `copy_with` preserves it (invariant 2) |
| `POST /design/deformation?preview=true` | `preview` is a **body** field on POST; query param only on DELETE |
| `MAP_DEFORMATION.md` | **Never existed anywhere in the repo.** Still cited by `docs/triage/04_deform_tools.md:28,34` |

## Diagnostics → [.claude/runbooks/RUNBOOK_DEFORMATION.md](../runbooks/RUNBOOK_DEFORMATION.md)

## Related

- [REFERENCE_DEFORMATION_THEORY.md](../../memory/REFERENCE_DEFORMATION_THEORY.md) — DTP-6, loop-skip, bend/twist theory
- [project_deformation_cluster_scope.md](../../memory/project_deformation_cluster_scope.md) — the `cluster_ids` design
