---
name: cadnano-2d
description: In-app Cadnano 2D mode (K key) — ortho camera, two-track flat view, bead posmaps, loop/skip markers, subscriber ordering.
paths:
  - "frontend/src/scene/cadnano_view.js"
  - "frontend/src/scene/loop_skip_highlight.js"
---

# cadnano-2d

**Scope: the K-key VIEW MODE of the 3D app** — a read-only camera/layout mode that flattens the
existing Three.js helix meshes into two tracks. It edits nothing.

**Not this rule:** `frontend/src/cadnano-editor/` is a **separate 10.7k-LOC Vite app** (own HTML
entry, own `editorStore`, own `api.js`, reached by `window.open`). It shares **no module** with
`cadnano_view.js` — neither imports the other. Don't reason about one from the other. It has its
own rule: [cadnano-editor](cadnano-editor.md).

## Files

| Thing | Location |
|---|---|
| Main module | `frontend/src/scene/cadnano_view.js` — `initCadnanoView(...)` :42 |
| Init site | `main.js:1542` (import :106) — **still in main.js; not carved out** |
| Flat-position collaborator | `frontend/src/scene/unfold_view.js` — `applyCadnanoPositions(toMap, t, fromMap)` :1205 |
| Domain ends | `frontend/src/scene/domain_ends.js` — `initDomainEnds` (aliased `bluntEnds`, built `main.js:2988`); `applyCadnanoPositions` :736 |
| Loop/skip markers | `frontend/src/scene/loop_skip_highlight.js` — `applyCadnanoPositions(rowMap, spacing, midX)` :303 |
| Axis arrows | `design_renderer.js:1478` → `helix_renderer.js:4405` `setAxisArrowsVisible()` |
| Renderer hooks | `design_renderer.js` — `refreshAllGlow()` :955 · `applyCadnanoPositions()` :1264 · `getBackboneEntries()` :795 |
| Minimap | `frontend/src/scene/cross_section_minimap.js` — `hide()` :661, `clearSlice()` :675 (built `main.js:2530`) |
| Slice highlights | `sliceHighlighter.clear()` — `initSliceHighlighter` at `main.js:2922` |

## Init signature (8 params — the 5th is vestigial)

```javascript
initCadnanoView(sceneCtx, designRenderer,
  getUnfoldView, getSequenceOverlay,
  _getCrossoverLocations,          // always passed null; never referenced in the body
  getSlicePlane, getBluntEnds, getLoopSkipHighlight)
```
`sceneCtx` members actually used: `camera`, `controls`, `scene`, `renderer`, `setRenderCamera`,
`restoreRenderCamera`, `pushControls`, `popControls`, `setResizeCallback`, `clearResizeCallback`,
`animateCameraTo`. (`captureCurrentCamera` exists on sceneCtx but this module never calls it.)

Returned API (:692): `{ activate, deactivate, toggle, isActive, reapplyPositions, forceExit }`
— :407 / :457 / :513 / :518 / :552 / :526.

## Store key

`cadnanoActive` — default `state/store.js:194`, persisted in the `viz` set `store.js:388`.
Set true `cadnano_view.js:451`, false `:503`, force-cleared `main.js:3540`.

It is read far outside this module: `deform_view.js:245,262,298,344,360` (straight-geometry
staleness), `end_extrude_arrows.js:382-394` (Z-axis override so extrude drag works flat),
`selection_manager.js:2355`, `translate_rotate_tool.js:30,573,597`, `view_menu_pills.js:43,50,59`,
`view_tool_buttons.js:153,164,234`, `design_renderer.js:750,1242`, `main.js:2749`
(`effectivePlane = cadnanoActive ? 'XY' : plane`), `main.js:4704`. **Anything that changes bead
positions must consider this flag.**

Guard flags: `_active` / `_inTransition` (:43-44; re-entry guards at :408, :458, :527).

## Two-stage activation

`ANIM_STAGE1_MS = 250` (:35), `ANIM_STAGE2_MS = 250` (:36).

```
Stage 1: unfoldView.activateWithDuration(250)   (:415) — helices stack
Stage 2: Promise.all (:428-435)
  _animate(_unfoldPosMap, _cadnanoPosMap, ...)  — beads lerp to flat positions
  sceneCtx.animateCameraTo(X- orbit, same dist + target)
After:
  designRenderer.setAxisArrowsVisible(false)
  getBluntEnds().applyCadnanoPositions(_rowMap, _spacing, _midX)
  getLoopSkipHighlight().applyCadnanoPositions(_rowMap, _spacing, _midX)
  _buildRowBands()        :263 — YZ-plane translucent bands
  _activateOrthoCamera()  :181
  _showSlicePlane()       :310
  _active = true; cadnanoActive = true
```

`_enableSideEffects()` (:402) **and** `_restoreSideEffects()` (:403) are **both empty no-ops** —
they survive as call sites only. Rationale at :396-401: the base-sequence overlay is deliberately
KEPT in cadnano (its letter quads face +X = the ortho view axis), so nothing needs hiding.

## Position maps

`_cadnanoPosMap` / `_unfoldPosMap`: `Map<"helix_id:bp_index:direction", THREE.Vector3>`
(built `:148`, `:574`). Same key format as `unfold_view.js` `_straightPosMap` (:60, built :66-71).

### `_unfoldPosMap` is MERGE-ONLY (CRITICAL)

Only insert keys not already present. Never reassign the map, never `snapshotPositions()`:

```javascript
if (!_unfoldPosMap) _unfoldPosMap = new Map()
for (const entry of designRenderer.getBackboneEntries()) {
  if (entry.nuc.helix_id.startsWith('__xb_'))  continue   // :572
  if (entry.nuc.helix_id.startsWith('__ext_')) continue   // :573
  const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
  if (!_unfoldPosMap.has(key)) _unfoldPosMap.set(key, entry.pos.clone())
}
```

**Why:** `reapplyPositions()` runs twice per geometry change — once synchronously (beads at unfold
positions → correct baseline) and once from a deferred async callback (beads already at cadnano
positions → would corrupt the baseline). Merge-only ignores the second call.

**Prefix-skip asymmetry (deliberate, easy to "fix" wrongly):** the posmap loops skip exactly
`__xb_` and `__ext_`, but the `_midX` loop (:117) and the scaffold-direction loop (:129) skip the
broader `__`. `__lnk__` is **real duplex** and must NOT be skipped in the posmaps.

## `reapplyPositions()` (:552-590)

Called from the main.js subscribers below whenever geometry OR design changes while cadnano is
active (the API sometimes delivers design first and geometry in a separate async fetch → two
separate `setState` calls). Actual order:

1. `_active` guard, early return (:553)
2. `_cadnanoPosMap = _computeCadnanoPosMap()` + abort if empty (:559-564) — **recompute, not reuse**
3. merge-only `_unfoldPosMap` rebuild (:570-576)
4. `designRenderer.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)` (:578)
5. `getSequenceOverlay?.()?.applyUnfoldOffsets(new Map(), 1.0, _cadnanoPosMap, null)` (:580)
6. `getUnfoldView?.()?.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)` (:581)
7. `getBluntEnds?.()?.applyCadnanoPositions(_rowMap, _spacing, _midX)` (:582)
8. `getLoopSkipHighlight?.()?.applyCadnanoPositions(_rowMap, _spacing, _midX)` (:583)
9. `designRenderer.refreshAllGlow()` (:587)
10. `_startPostReapplyMonitor()` (:589) — debug-only, no-ops unless `window._cnDebug`

## Glow positioning invariant (CRITICAL)

The selection glow bakes `entry.pos` into an InstancedMesh **at the moment `setGlowEntries()` is
called**; it does not track later mutations of `entry.pos`.

selectionManager's rebuild subscriber fires **before** cadnanoView's reapply subscriber, so it
re-applies the glow at 3D/unfold positions; `reapplyPositions()` then moves `entry.pos` to cadnano
coordinates and the glow is left stale.

**Rule: every path that mutates `entry.pos` to cadnano coordinates ends with
`designRenderer.refreshAllGlow()`** — (a) the `_animate()` frame loop after `applyCadnanoPositions()`,
(b) `reapplyPositions()` step 9. (`unfold_view.js` already does this per-frame.)

## Arc / domain-end tracking

`unfold_view.applyCadnanoPositions(toMap, t, fromMap)` is called every `_animate()` frame and from
`reapplyPositions()` so arcs track their beads.

`domain_ends.js:590-593` `reapplyIfActive()` has **two** branches — both matter:
```javascript
if (store.getState().cadnanoActive && _lastCadnanoParams) {
  _applyCadnanoPositions(_lastCadnanoParams.rowMap, _lastCadnanoParams.spacing, _lastCadnanoParams.midX)
}
if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()
```
i.e. it re-applies from a cached `_lastCadnanoParams` (set in `_applyCadnanoPositions` :624) rather
than merely suppressing unfold offsets. Don't confuse `domain_ends.js` with
`scene/blunt_end_connectors.js` — different module, no `applyCadnanoPositions`.

## Loop/skip in cadnano mode

`loop_skip_highlight.js`:
- **Loop torus** at `(midX, -row*spacing, bpIndex*BDNA_RISE_PER_BP)` — helix centre, between tracks
- **Skip × arms**: quaternions swap from XY-plane `_Q45A`/`_Q45B` (Euler Z ±45°) to YZ-plane
  `_Q45A_CN`/`_Q45B_CN` (Euler X ±45°) so the × faces the ortho X- camera — constants :58-62
- `applyUnfoldOffsets` restores the XY quats on exit (:283-286)

Markers are **not** animated during the 250 ms bead lerp — they snap after it (same as domain ends).

## Deactivation

```
_restoreSideEffects() (no-op); _hideSlicePlane() — this also does sp.setCamera(perspCamera) :344
_removeRowBands(); capture ortho state → matching perspective position (same dist via FOV)
designRenderer.setAxisArrowsVisible(true); _deactivateOrthoCamera()
place perspective camera at orthoTarget + camDir * -perspDist
await _animate(_cadnanoPosMap, _unfoldPosMap, ...)   — reverse lerp
unfoldView.setSpacing(...)   — re-applies unfold offsets to ALL overlays, restoring loop/skip quats
_active = false; cadnanoActive = false
if (!keepUnfold && !_wasUnfoldActive) unfoldView.deactivate()
```
`_wasUnfoldActive` declared :59, set :413, consumed :508.

`forceExit()` (:526-538) — synchronous hard exit for new-design load. Cancels the animFrame, runs
`_restoreSideEffects` / `_hideSlicePlane` / `setAxisArrowsVisible(true)` / `_removeRowBands` /
`_deactivateOrthoCamera`, resets both flags and nulls both maps. Does **not** clean up
minimap/highlights — `_resetForNewDesign()` (`main.js:3488`) does that at :3513-3515 after calling
`forceExit()` at :3499.

## Ortho camera

- Position/quaternion/up copied from the perspective camera exactly → seamless visual switch
- Frustum (:192-196): `fh = 2 * dist * Math.tan(fovRad / 2)` (**full** height), then
  `(-fw/2, fw/2, fh/2, -fh/2)`. `halfH` appears only in the resize path (:213) and deactivate (:470)
- Resize (:210-217): preserves `halfH` (zoom level), recomputes `halfW` for the new aspect
- OrbitControls: `enableRotate = false` (:204), `enableDamping = false` (:205) — pan + zoom only
- Shift+right-click: `_orthoShiftRightFix` (:225-238) is a **capture-phase** listener that strips
  `shiftKey` before OrbitControls sees it, so shift+right-click pans as in 3D. Removed :247-250
- **Fragility:** `PERSP_FOV_DEG = 55` (:40) is hardcoded here and must stay in lockstep with
  `scene/scene.js`. Nothing enforces it

## View transitions

`deactivate({ keepUnfold = false })`.

| From | To | Key | Path |
|---|---|---|---|
| 3D | Unfold | U | `_toggleUnfold()` → `unfoldView.activate()` |
| 3D | Cadnano | K | `_toggleCadnano()` → `cadnanoView.activate()` (auto-enables unfold) |
| Unfold | 3D | U | `_toggleUnfold()` → `unfoldView.deactivate()` |
| Cadnano | 3D | K | `cadnanoView.deactivate()` — unfold dropped if auto-activated |
| Unfold | Cadnano | K | as 3D→Cadnano; `_wasUnfoldActive=true` → unfold stays on K exit |
| **Cadnano** | **Unfold** | **U** | `_toggleUnfold()` intercepts → `deactivate({keepUnfold:true})` |

**Key bindings live in `frontend/src/ui/keyboard_shortcuts.js`** — `u` :259-264, `k` :266-271, both
`blockedInInput`. Handlers are injected deps wired at `main.js:4510-4511`; the same arrows also go to
`initViewToolButtons` (`main.js:4362-4363`) and the View menu binds them directly
(`main.js:4214/4216`). (`frontend/src/input/shortcuts.js` is only the ~98-line registry.)

U-key intercept, `main.js:2554-2563`:
```javascript
if (cadnanoView.isActive()) {
  await cadnanoView.deactivate({ keepUnfold: true })
  if (!slicePlane.isVisible()) {
    crossSectionMinimap.clearSlice(); crossSectionMinimap.hide(); sliceHighlighter.clear()
  }
  document.getElementById('mode-indicator').textContent =
    '2D UNFOLD — helices stacked by label order · [U] to return to 3D'
  return
}
```
`mode-indicator` strings at `main.js:2643-2648`. `_toggleUnfold` :2541, `_toggleCadnano` :2608.

## Subscriber ordering hazards (CRITICAL)

Two reapply subscribers exist in main.js — the rule used to document only the first:

1. **`main.js:2499-2508`** — the cadnano reapply subscriber. Registered *after* `initSequenceOverlay`
   so it fires last (ordering comment :2490-2498).
2. **`main.js:2517-2525`** — fires on `straightGeometry` / `straightHelixAxes` change; compensates for
   `deform_view`'s async straight-geometry fetch (whose own subscriber is `cadnanoActive`-guarded at
   `deform_view.js:344`).

(A debug-only `cadnanoActive` transition logger sits at `main.js:1816-1822`.)

**The hazard is still real:** any subscriber registered *after* these that pushes 3D geometry
positions into the renderer will overwrite cadnano bead positions and cause a one-frame flash to 3D
after every topology mutation. If you add one, guard it on `cadnanoActive || unfoldActive`.

The historical culprit — the FEM "clear stale results" subscriber — **no longer exists**;
`design_renderer.clearFemOverlay()` (:1241) survives with its guard intact but has **zero callers**
(dead code; its comment now describes the mrDNA relaxed-position overlay). Don't go looking for it.

## Cross-feature interactions

- Requires unfold; auto-activates it, auto-deactivates on exit unless `_wasUnfoldActive`
- **Blocked in atomistic representation** — `main.js:2614-2617` toasts and returns (same for unfold :2620)
- Deformation tool blocked while cadnano is active — `main.js:2659-2662`; also store-side via
  `view_menu_pills.js:43` (`disabled = !!(s.cadnanoActive || s.unfoldActive)`)
- Expanded spacing forced off before activation — `expandedSpacing.forceOff()` `main.js:2634`
- Selection highlight: `selection_manager.js:2354-2355` — `otherScale = cadnanoActive ? 1.0 : 1.2`
  (whole-strand highlight suppressed; only the end bead is meaningful in the flat view)
- End-extrude: `end_extrude_arrows.js:382-394` overrides axis/origin/outward to the cadnano **Z**
  axis so extrude drag works in the flat layout
- Translate/rotate tool disabled — `translate_rotate_tool.js:30,573,597`

## Test coverage — there is none, directly

**No unit test file exists for `cadnano_view.js`** (nor for `unfold_view.js` or
`loop_skip_highlight.js`). Treat every change here as unpinned; exercise it in the app.

Indirect coverage only: `ui/keyboard_shortcuts.test.js:129,139` (K/U dispatch + input-blocking),
`ui/view_menu_pills.test.js:88,100`, `scene/translate_rotate_tool.test.js:449-461`,
`ui/view_tool_buttons.test.js:63`, `scene/domain_ends.test.js`.

**Neither `e2e/cadnano_*.spec.js` covers this mode** — `cadnano_crosssection.spec.js` tests
cadnano-*file import*; `cadnano_sliceview_positions.spec.js` tests the separate cadnano *editor*.

## Removed API — do not resurrect

| Dead name | Reality |
|---|---|
| `frontend/src/cadnano/` | Never existed at this path. The editor is `frontend/src/cadnano-editor/` (separate app) |
| `frontend/src/scene/blunt_ends.js` | Renamed → `scene/domain_ends.js` (`initDomainEnds`, aliased `bluntEnds`) |
| `_clearSliceHighlights()` | Gone → `sliceHighlighter.clear()` (`main.js:2922`, called :2559 / :2641 / :3515) |
| `_helixCtrl.clearFemColors()` | Gone from `clearFemOverlay()`; no such function in the frontend |
| FEM "clear stale results" subscriber (`main.js:2475`) | Gone; `clearFemOverlay()` itself is uncalled |
| `captureCurrentCamera` in this module's sceneCtx contract | Exists on sceneCtx, never called by `cadnano_view.js` |
| `snapshotPositions()` for `_unfoldPosMap` | Forbidden — breaks the merge-only invariant |

## Debugging → [.claude/runbooks/RUNBOOK_CADNANO.md](../runbooks/RUNBOOK_CADNANO.md)

Bead-position intercept technique and known issues live in the runbook. The module installs
`window._cnEntries` (:593), `window._cnMonitor` (:597), `window._cnCheck` (:673); the post-reapply
monitor is inert unless `window._cnDebug` is set.
