---
name: main-init
description: main.js the composition root — boot shape, factory-init placement, store-subscription order (position overlays), canvas event priority, frame-callback safety.
paths:
  - "frontend/src/main.js"
  - "frontend/src/scene/scene.js"
---

# main-init

**Scope.** `frontend/src/main.js` is the app's **composition root**: one `async function main()`
(opens `:250`, closes `:7959`, invoked at `:8055` as `main().catch(...)`) that constructs every
subsystem and wires them together. Almost nothing lives at module scope — only the icon preamble
and `window.nadocDebug` (`:7965`). This rule covers the *boot contract*: what must be built before
what, which subscriber order is load-bearing, and the two ways this file kills the app.
`scene/scene.js` is in scope because it owns the render loop that `main()` feeds.

## Status — 8,059 LOC and RISING (measured 2026-07-30)

154 factory inits · 41 `store.subscribe` sites · 151 region banners · **zero unit tests**.

Down from ~16.5k, but **up +245 since 7,814 (2026-07-13) and +1,094 since the last carve session
left it at 6,965 (2026-06-06)**. MD/SNUPI/jobs feature work has been re-growing the closure. That
is the module-first law in `CLAUDE.md` + `FEATURE_DEVELOPMENT.md` leaking: **a feature commit must
leave this file flat or lower** — imports + a one-line factory init + thin per-action wiring only.
If your diff adds a cohesive block here, extract it before committing.

## Finding anything in this file (recipe — there is deliberately no table)

```bash
rg -n '\binit[A-Z]\w*\(' frontend/src/main.js    # all 154 factory inits, in boot order
rg -n 'store\.subscribe\(' frontend/src/main.js  # all 41 subscribers, in registration order
rg -n '^  // ── ' frontend/src/main.js           # the 151 region banners = the file's TOC
```

**Never cite a `main.js:NNNN` anchor without re-grepping it.** The carve-up moves every line in
this file, most sessions. This rule previously carried a 30-row init-order table with line numbers:
at audit, **30 of 30 line numbers were wrong** (2–3× off) and 6 of the 30 symbols no longer existed,
while ~124 factory inits were invisible to it. An enumeration whose length tracks the codebase
belongs in a grep command, not in a doc.

**Where the mass is** (coarse, changes only when a subsystem appears): selection + overhang dialog
`~800–1330` · view modes (unfold / cadnano / deform / animation player) `~1530–1660` · overlays
`~1640–1860` · the **whole MD stack** (oxDNA, mrDNA, CanDo, SNUPI, LAMMPS, engine selector, jobs
panels, forces/anchors/floor setup) `~1860–2420` · menus + slice plane + context menus `~2530–3050`
· file / session / multi-document / part-edit lifecycle `~3050–3750` · menu bar + tools + view
toggles `~3750–4500` · panels `~4500–4750` · the **whole assembly subsystem** `~4750–6330` ·
sidebar tabs + photo mode + export `~6330–7160` · debug menu + Playwright test helpers + editor
tab registry `~7160–7940`.

## Store subscription order — the position-overlay chain (the one ordering fact that matters)

The store fires subscribers **in registration order**, and every position overlay rewrites bead
positions, so **last writer wins**. On `currentGeometry` / `currentDesign` change:

| Fires | Who | Does |
|---|---|---|
| 1 | `designRenderer` (`initDesignRenderer` :286) | `_rebuild()` — beads back at raw 3D geometry |
| 2 | `unfoldView` (:1535) | `applyUnfoldOffsets(_currentT)` if active |
| 3 | `loopSkipHighlight` (:1646) | re-apply loop/skip offsets |
| 4 | `overhangLocations` (:1657) | rebuild overhang sprites |
| 5 | `sequenceOverlay` (:2488) | rebuild letter sprites at raw 3D positions |
| 6 | **cadnano reapply** (:2500) | `cadnanoView.reapplyPositions()` if active |
| 6b | **cadnano compensator** (:2517) | keyed on `straightGeometry`/`straightHelixAxes`, not design |
| 7 | `domainEnds` (`initDomainEnds` :2988) | rebuild, then re-apply cadnano *or* unfold |

Load-bearing details, with the code that proves them:

- **Step 6 is registered immediately after `initSequenceOverlay` on purpose** — the in-file comment
  at `:2490` says so. It must fire *after* the overlay rebuilds sprites at raw 3D positions.
- **6b exists because `deform_view` is guarded against cadnano.** When a design has
  deformations, `deform_view` fetches straight geometry asynchronously; its own subscriber
  won't re-apply while `cadnanoActive`, so this second subscriber restores the cadnano layout
  when the fetch lands.
- **Step 7 is conditional, not unconditional.** `domain_ends.js:589-593`: after `_rebuild`, it
  re-applies cadnano positions if `cadnanoActive && _lastCadnanoParams`, and calls
  `getUnfoldView?.()?.reapplyIfActive()` **only when `!cadnanoActive`**. The local variable in
  `main.js` is still named `bluntEnds`; the factory is `initDomainEnds`.

**Hard rule for extractions:** if you lift anything that subscribes, **re-register at the same
point in `main()`.** Reordering subscribers breaks position overlays silently — no error, just
beads in the wrong place for one frame or forever.

For `selectedObject`-only changes: `end_extrude_arrows` rebuilds arrows (reads `entry.pos`, never
writes it); UI panels update display; nothing moves geometry.

## Canvas event priority — TWO gates, not one

**Gate 1 — capture-phase deform listeners** (`:694`, `:699`, `:712`, all `{ capture: true }`,
under the banner at `:671`). Handlers are import aliases (`:78-80`):
`handlePointerMove/Down/Up as deformPointerMove/Down/Up`.

```
capture: deformPointerMove / Down / Up   → run first
bubble:  selectionManager
bubble:  OrbitControls

pointerdown: if (consumed) e.stopImmediatePropagation()   // :704 — selection + orbit never see it
pointerup:   stops ONLY if (_deformConsumedDown && e.button === 0)   // :716
```

The `pointerup` asymmetry is deliberate: a missed click must still reach OrbitControls so it can
exit its drag cleanly. Don't "fix" it to match `pointerdown`.

**Gate 2 — the `selectableTypes` blanking subscriber** (`:4318-4344`). On `deformToolActive`
going true it saves `_savedSelectableTypes` and sets **all 9 selectable-type flags to false**, and
drops representation to `full` if it was `hull-prism` (`:4327`); on false it restores. Events still
arrive — every capture filter simply returns false. Both gates are live at once; a change to one
does not cover the other. (`RUNBOOK_SELECTION.md` describes this gate from the selection side.)

Other canvas listeners this rule does not model: cursor tracking `:684/:689`, contextmenu `:1742`,
pointercancel `:4390`, assembly pointer `:5261/:5264` and the dynamically added/removed set at
`:5799-5802`, click `:7266`.

## Frame callbacks must not read late-declared `const`s (render-loop killer)

`addFrameCallback(fn)` (`scene/scene.js:239-252`) adds `fn` to a `Set` consumed by
`renderer.setAnimationLoop(() => { ...; _frameCallbacks.forEach(fn => fn()); _renderFn() })`.
three.js reschedules the loop **only after the callback returns**, so **one uncaught throw in any
frame callback kills the render loop permanently** — canvas freezes, geometry loads but never
draws ("blank workspace").

A frame callback that reads a `const` declared *later* in `main()` is a temporal-dead-zone
landmine: any boot path that yields to `requestAnimationFrame` before that declaration runs fires a
frame while the binding is in TDZ → throw → dead loop. Optional chaining does **not** save you (TDZ
throws even under `?.`). The `?part-instance=` part-editor path (`:3379`, first `await` at `:3396`)
is exactly such an early-yield path.

**Fix pattern:** forward-declare `let x = null` before the callback and assign at creation — the
file has many live examples (`let jointRenderer = null` :1555, `let engineSelector = null` :2091,
`let _viewToolButtons = null` :2085). There are only **2** frame callbacks in main.js today
(`:319` frame-stats/LOD HUD, `:615` adaptive camera clipping); when adding a third, verify every
symbol it reads is declared before it or null-forward-declared.

## Routing check state

`:720-738`. `const _routingChecks = { scaffoldEnds: false }` — **one field**, mirrored to the menu
DOM by `_setRoutingCheck` via `_routingIdMap`. `_clearScaffoldChecks()` (`:736`) clears it on
scaffold topology change. `_setRoutingCheck` is injected into `initAutoscaffoldPicker` (`:3931`).

## Factory-init placement

`const x = initX({...})` is **not hoisted** — it must sit where its deps already exist AND before
anything *executes* one of its methods. The two recurring failure cases (deps declared below the
banner; a callback registered ~1000 lines earlier needing a method) and their `let _x = null` +
lazy-arrow fixes are in the detail file below — read it when you're placing an init, not before.

## Invariants

1. Subscriber **registration order** is API. Re-register at the same point when extracting.
2. A frame callback may only read symbols declared above it or forward-declared `let x = null`.
3. Lazy getters (`getUnfoldView`, `getOverhangLocations`, `getLoopSkipHighlight`,
   `getOverhangLinkArcs`, `getFlexibleArcs`, `getProteinRenderer`) exist so early-initialized
   modules can reach late-initialized ones. Pass `() => module`, never `module`.
4. `main()` is one closure — a `const` added at the bottom is invisible to everything above it.
5. Feature work leaves this file flat or lower in LOC (module-first law).
6. `initSelectionManager(canvas, camera, designRenderer, opts)` — `opts` has **25 keys**
   (6 lazy getters + 11 right-click/action callbacks + `isDisabled`/`getCamera`/`getHoverEntry`/
   `onDrillLevel` + 4 renderer getters). Its in-file JSDoc undercounts; count the real object.

## Traps — comments and names that contradict the code

- **`_clearStapleChecks()` (`:733`) is an empty no-op** ("no staple-routing checks currently
  tracked") yet is still called from 5 sites (`:829`, `:840`, `:3496`, `:3891`, `:3918`). Don't
  infer that staple checks exist.
- **`bluntEnds` is a variable name, not a module** — the factory is `initDomainEnds`
  (`scene/domain_ends.js:350`). `initBluntEnds` does not exist.
- **`designRenderer.clearFemOverlay()` (`design_renderer.js:1241`) has zero callers.** It still
  contains a cadnano/unfold guard that this rule once presented as a CRITICAL live invariant. It
  guards nothing; logged in `project_tech_debt`.
- `_floorReach` (`:614`) is a permanent `() => null` stub — photo-mode v1's ground plane was
  archived. The frame callback that reads it is dead weight, deliberately kept as a revive seam.

## Test coverage — none

**There is no `main.js` unit test and no test imports it.** ~30 sibling `*.test.js` files mention
main.js only in "extracted from main.js" comments. `frontend/e2e/*.spec.js` exercises the app
end-to-end but pins no main.js symbol. The only real gates on this file are `just smoke` (console-
error + teardown) and exercising the app by hand. `main-init` is the only rule whose glob matches
`main.js` — nothing else covers it.

## Removed API — do not resurrect

All gone from `frontend/src` (present only under `archive/physics_xpbd_fem/`, retired with XPBD/FEM):
`initPhysicsClient` · `initFastPhysicsClient` · `initFastPhysicsDisplay` · `initFemClient` ·
`applyPhysicsPositions` · the FEM "stale results" store subscriber in `main()` (it does not exist;
`revertToGeometry` is now called only from `unfold_view.js` and inside `applyFemPositions`).

Never existed / renamed: `initBluntEnds` (→ `initDomainEnds`) · `initConfigPanel` (a phantom —
design-scoped configurations were never built; configurations shipped **assembly-scoped**, see
`.claude/rules/animation.md`) · `photoRenderer` in main.js (photo mode is `initPhotoMode` `:6750`;
the name survives only as a parameter in `scene/export_video.js`) · `_routingChecks.prebreak` ·
`_routingChecks.autoMerge`.

> **Detail.** The closure→module extraction loop, its worked examples, the adapted-code pin-proving
> rule, and the gesture-validation harness live in
> [main_init_detail.md](../../memory/main_init_detail.md). The backlog + metrics are
> `main_js_carveup.md` and `main_js_extraction_log.md` — both at the **repo root**, not in
> `memory/`. Read on demand only. (`/carve-router` is the *backend* loop and explicitly excludes
> main.js; this loop has no slash command.)
