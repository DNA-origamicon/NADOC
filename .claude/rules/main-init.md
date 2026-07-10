---
name: main-init
description: main.js initialization order — module sequence, lazy getters, subscription fire order, dependency injection.
paths:
  - "frontend/src/main.js"
---

# main-init

## Init order

## Initialization Order in main() (approximate line numbers)

```
~99   initScene(canvas)                        → scene, camera, renderer, controls
~106  initDesignRenderer(scene, store)          → designRenderer  [store subscriber #1]
~109  initZoomScope(...)                        → zoomScope
~119  canvas.addEventListener('pointermove/down/up', capture=true)  [deform tool intercepts]
~175  initSelectionManager(canvas, camera, designRenderer, {
         lazy: getUnfoldView, getOverhangLocations, getLoopSkipHighlight
      })                                        → selectionManager  [store subscriber #2]
~205  initEndExtrudeArrows(...)
~264  IIFE: overhang dialog DOM creation        [sets _showOverhangLengthDialog]
~452  IIFE: loop strand popup                  [store subscriber #3 — loop detection]
~542  initPhysicsClient({onPositions → designRenderer.applyPhysicsPositions})  → physicsClient
~554  initFastPhysicsDisplay(...)               → fastDisplay
~556  initFastPhysicsClient({...})              → fastClient
~822  initDeformationEditor(scene, camera, canvas, controls, designRenderer, onExit)
~827  initBendTwistPopup({onPreview, onConfirm, onCancel})
~859  initUnfoldView(scene, designRenderer,     → unfoldView     [store subscriber — fires EARLY]
         lazy: bluntEnds, loopSkipHighlight, sequenceOverlay, overhangLocations)
~862  initExpandedSpacing(...)                  → expandedSpacing
~873  initDeformView(designRenderer,            → deformView
         lazy: bluntEnds, unfoldView, loopSkipHighlight, overhangLocations)
~876  initAnimationPlayer({camera, controls, designRenderer, deformView, getConfigPanel})  → animPlayer
~889  initDebugOverlay(canvas, camera, designRenderer, lazy: bluntEnds)  → debugOverlay
~896  initLoopSkipHighlight(scene)              → loopSkipHighlight  [store subscriber]
~906  initOverhangLocations(scene)              → overhangLocations  [store subscriber]
~1449 initSequenceOverlay(scene, store)         → sequenceOverlay
~1453 initViewCube(...)                         → viewCube
~1521 initSlicePlane(...)                       → slicePlane
~1753 initBluntEnds(scene, camera, canvas, {...})  → bluntEnds  [store subscriber — fires LATE]
~2291 initFemClient({...})                      → femClient
~3321 initCommandPalette({...})
~3338 initPropertiesPanel()
~3339 initSpreadsheet(store, {designRenderer})  → spreadsheet
~3382 initClusterGizmo(store, controls, ...)    → clusterGizmo
~3482 initClusterPanel(store, {onClusterClick}) → clusterPanel
~3508 initCameraPanel(store, {captureCurrentCamera, animateCameraTo, api})
~3511 initConfigPanel(store, {getHelixCtrl: () => designRenderer.getHelixCtrl(), api})
~3520 initAnimationPanel(store, {player: animPlayer, api})
```

## Lazy Getter Pattern
Dependencies injected as `() => module` (not `module`) so they resolve after all modules are initialized:
```js
initSelectionManager(canvas, camera, designRenderer, {
  getUnfoldView:        () => unfoldView,        // defined at ~859
  getOverhangLocations: () => overhangLocations, // defined at ~906
  getLoopSkipHighlight: () => loopSkipHighlight, // defined at ~896
  ...
})
```
This is how modules initialized before their dependencies reference them safely.

## CRITICAL: Subscription Order (Store Fires in Registration Order)

For geometry/design changes (`currentGeometry` / `currentDesign` / `loopStrandIds` changed):
```
~106  designRenderer        → _rebuild() — beads reset to 3D geometry positions
~859  unfoldView            → applyUnfoldOffsets(_currentT) — beads at unfold positions (if active)
~896  loopSkipHighlight     → reapply loop highlight offsets
~906  overhangLocations     → rebuild overhang sprites
~935  cadnanoView reapply   → reapplyPositions() — beads at cadnano positions (if active)
~1753 bluntEnds             → (various, fires late)
~2475 FEM clearOverlay      → clearFemOverlay() → revertToGeometry() if !cadnanoActive && !unfoldActive
```

**Key ordering consequences**:

1. **bluntEnds fires after unfoldView**: After topology mutation in unfold view, unfoldView's callback
   fires first (applies offsets to OLD sprites about to be disposed), then bluntEnds rebuilds at 3D
   positions. Fix: `bluntEnds._rebuild()` calls `unfoldView.reapplyIfActive()` at end.

2. **FEM clearOverlay fires LAST and calls revertToGeometry** (CRITICAL): The FEM "stale results"
   subscriber at ~line 2475 fires AFTER cadnanoView's reapply subscriber. It called
   `clearFemOverlay()` → `revertToGeometry()`, overwriting cadnano/unfold positions with 3D geometry.
   **Fix (2026-04-01)**: `clearFemOverlay()` now skips `revertToGeometry()` when `cadnanoActive` or
   `unfoldActive`. Any NEW late-registering subscriber calling `revertToGeometry()` must apply the
   same guard, or cadnano/unfold positions will flash to 3D for one frame after each mutation.

For `selectedObject` changes only (e.g. from `selectNucleotide()`):
- `end_extrude_arrows` rebuilds arrows (reads entry.pos, does NOT write it)
- UI modules (spreadsheet, properties panel, atomistic highlight) update their display
- Loop-strand popup suggests nick position (no position changes)
- FEM subscriber: `currentDesign` unchanged → returns early (safe)

## Canvas Event Priority (Capture vs Bubble)
```
pointerdown capture phase (lines ~119-143):
  1. deformPointerMove/Down/Up (capture=true) — runs first
  2. selectionManager (bubble phase, no capture)
  3. OrbitControls (bubble phase)

If deformPointerDown returns true → e.stopImmediatePropagation()
  → selectionManager and OrbitControls never see the event
```

## Frame callbacks must not reference late-declared `const`s (render-loop killer)

`addFrameCallback(fn)` registers `fn` into the `setAnimationLoop` loop in `scene.js`,
which runs `_frameCallbacks.forEach(fn => fn()); _renderFn()` and — critically —
three.js reschedules the loop **only after the callback returns**. So **one uncaught
throw in any frame callback kills the render loop permanently** (it never reschedules;
the canvas freezes, geometry loads but never draws → "blank workspace").

A frame callback that reads a module declared *later* in `main()` (e.g. `photoRenderer`,
created ~10.8k) is a temporal-dead-zone landmine: any boot path that **yields to
requestAnimationFrame before that declaration runs** fires a frame while the `const`
is in TDZ → throw → dead loop. The part-editor tab (`?part-instance=`) is exactly such
a path — it `await`s its design fetch early (~3800), long before `photoRenderer`.
Optional chaining does NOT save you (TDZ on a `const`/`let` throws even under `?.`).
**Fix pattern:** forward-declare as `let x = null` before the callback, assign at
creation (mirrors `let clusterPanel = null`). Fixed 2026-06-04 (`photoRenderer`); the
floor-reach callback had silently relied on boot reaching the const before the first
rAF frame. When lifting/adding frame callbacks during the carve-up, verify every symbol
they read is declared before the callback, or null-forward-declared.

## Routing Check State
`_routingChecks` object (local to main): tracks `{scaffoldEnds, prebreak, autoMerge}`. Cleared by `_clearStapleChecks()` on nick/loop-skip/undo/redo and `_clearScaffoldChecks()` on scaffold topology changes.


## Decomposing this file (extraction loop)

The streamlined closure→module extraction loop, its worked examples, and the adapted-code
pin-proving rules live in the detail file — read it only when you are actually extracting.

> **Detail.** Worked examples + extraction history live in [main_init_detail.md](../../memory/main_init_detail.md) and `main_js_carveup.md`. Read on demand only.
