---
name: unfold
description: 2D unfold view — helix offset stack, bezier arcs, the applyUnfoldOffsets fan-out, cross-section minimap, expanded spacing.
paths:
  - "frontend/src/scene/unfold_view.js"
  - "frontend/src/scene/cross_section_minimap.js"
  - "frontend/src/scene/expanded_spacing.js"
---

# unfold

*Rewritten against the code 2026-07-30 (plan-audit pass). Line anchors verified that day;
`main.js` is under active carve-up, so re-grep any `main.js:NNNN` before citing it.*

## Scope

The **2D unfold view** ([U] key): helices are lifted out of their 3D bundle and stacked in
rows, with crossovers drawn as bezier arcs. Three files:

| File | LOC | Role |
|---|---|---|
| `scene/unfold_view.js` | 1,610 | The view. Owns the offset stack, the arc meshes, and the fan-out. |
| `scene/cross_section_minimap.js` | 712 | The bp=0 cross-section overlay shown while unfolded. |
| `scene/expanded_spacing.js` | 296 | **Sibling mechanism** — reuses the same `applyUnfoldOffsets` protocol to spread helices apart *in 3D*. Not the unfold view, but it is the second implementation of the same contract. |

**Not this rule:** the K-key cadnano 2D mode (`.claude/rules/cadnano-2d.md`) — it *builds on*
unfold but is a separate view. The deform view (`.claude/rules/deformation.md`) — coupled both
ways, see below.

## Entry & initialization

```js
// main.js:1535 — 7 args
initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight,
               () => sequenceOverlay, () => overhangLocations, null)
```
- The 7th arg is **vestigial**: the callee names it `_getCrossoverLocations` (`unfold_view.js:42`)
  and never uses it. Always `null`.
- The `bluntEnds` dep is `initDomainEnds` at `main.js:3006` — the module was renamed
  `blunt_ends.js` → `scene/domain_ends.js`; **only the local variable still says `bluntEnds`.**
  There is no `blunt_ends.js`.
- All deps are lazy getters (`domain_ends` initializes 1,400 lines later; see the ordering law).
- Minimap: `initCrossSectionMinimap(document.getElementById('canvas-area'))` — `main.js:2530`.
  (Its own param is named `viewportContainer`; the element passed is `#canvas-area`.)
- Expanded spacing: `initExpandedSpacing(...)` — `main.js:1545`.

`initUnfoldView` **returns a 30-method object**. Don't enumerate it here — regenerate:
```bash
rg -n "^\s+\w+,?$" frontend/src/scene/unfold_view.js | sed -n '/1124,/,$p'   # or just read :1124-1609
```
The ones other modules actually call: `toggle`, `activate`, `deactivate`, `activateWithDuration`,
`isActive`, `setSpacing`, `getMidZ`, `applyDeformLerp`, `reapplyIfActive`, `getArcEntries`,
`applyHelixOffsets`, `applyClusterArcUpdate`, `applyClusterExtArcUpdate`, `setArcsVisible`,
`refreshArcVisibility`.

**U key** is bound in `ui/keyboard_shortcuts.js:260-264` → injected `toggleUnfold` dep
(`main.js:4510`) → **`main.js:2541 async function _toggleUnfold()`**. `keyboard_shortcuts.js`
does not import `unfold_view.js`. All the *policy* (what blocks unfold) lives in `_toggleUnfold`,
not in the view.

## Store keys

| Key | Read by unfold_view | Written by | Notes |
|---|---|---|---|
| `unfoldActive` | yes (subscriber :1018) | `unfold_view.js:915,924,1146,1162`; cleared on new design `main.js:3540` | The gate everything else reads |
| `unfoldSpacing` | yes (11 sites) | `unfold_view.js:936` | default **2.5** nm (`store.js:187`) |
| `unfoldHelixOrder` | **read-only here** (:826,830) | **`main.js:2729/2736/2785`** — the slice-plane code, and reset to `null` at `:3540` | Row order top-to-bottom. **The unfold view does not decide the order; the cross-section slice plane does.** |
| `showHelixLabels` | **never touched by unfold_view** | `main.js:4238` | Owned by `domain_ends.js:395/471/482/596`. Default **`false`** (`store.js:200`). Listed here only because the old rule wrongly claimed it. |

Also read (not written): `currentDesign`, `currentGeometry`, `straightGeometry`,
`straightHelixAxes`, `strandColors`, `strandGroups`, `coloringMode`, `staplesHidden`,
`showReferenceGeometry`, `showPeriodicSeamArcs`, `selectedObject`.

`unfold_view.js` registers **10 `store.subscribe`** callbacks — no `subscribeSlice`; re-grep for
the line numbers, the 2026-08-01 cluster-display work shifted them all. The 10th is the
cluster-display subscriber (keyed on `clusterDisplaySignature`, see the arc-colour section). The
minimap registers 1 and writes **nothing**.

`unfoldHelixOrder` / `unfoldSpacing` are also re-read independently by `cadnano_view.js` at
`:97, :164, :264`, each re-deriving `unfoldHelixOrder ?? allIds` itself. Change the ordering
convention and you must change four sites, not one.

## Layout — what the offsets actually are

`_buildOffsets(spacing)` (`unfold_view.js:825-869`) returns a **Map of translation offsets**, not
absolute positions:

```js
offsets.set(helixId, new Vector3(-cx, -row * spacing - cy, 0))   // (cx,cy) = helix 3D midpoint
```
Net result after the offset is added: `y = -row * spacing`, **and `x = 0` — every helix is also
x-centered** (the old rule's `position.y = -i*spacing` formula omitted this). Z is never touched;
`_toggleUnfold` instead moves the orbit target to `getMidZ()` (`main.js:2589-2596`) so imported
designs with large `axis_start.z` don't clip.

Row order = `unfoldHelixOrder ?? allIds`, with **any helix missing from the stored order appended
at the end** (`:833`) — so a newly added helix lands at the bottom rather than throwing.

## The `applyUnfoldOffsets` fan-out (the core contract)

Every subsystem that owns display positions must implement `applyUnfoldOffsets(offsets, t)` and be
notified on every animation frame, or its objects stay at 3D positions while the helices move.

`unfold_view.js` notifies **5** callees (the old rule listed 4 — it omitted `designRenderer`):

| Callee | Implementation |
|---|---|
| `designRenderer.applyUnfoldOffsets` | `design_renderer.js:1256` → `helix_renderer.js:2154` |
| `getBluntEnds()` | `domain_ends.js:704` |
| `getLoopSkipHighlight()` | `loop_skip_highlight.js:260` |
| `getOverhangLocations()` | `overhang_locations.js:355` |
| `getSequenceOverlay()` | `sequence_overlay.js:375` |

Plus `designRenderer.applyUnfoldOffsetsExtensions(extArcMap, t)` (`design_renderer.js:1260` →
`helix_renderer.js:5069`).

**Four notify sites in `unfold_view.js`, and they must stay in sync:** `_animate` frame loop
(`:883-893`), `deactivate`'s callback (`:941-949`), the geometry/design subscriber (`:997-1002`),
and `reapplyIfActive` (`:1277-1284`). `applyUnfoldOffsetsExtensions` has a **5th** site inside
`applyClusterExtArcUpdate` (`:1471`, cluster drags).

A **6th implementer exists that unfold never calls**: `atomistic_renderer.js:452`. It is driven
only by `expanded_spacing.js:194`. That is deliberate — unfold refuses to enter atomistic mode
(see gates) — but it means `expanded_spacing.js:182-194` is the *longer* fan-out list (7 calls
including atomistic). **Adding a position-owning subsystem means editing both files.**

## Animation

`toggle()` (`:930`) → `activate()`/`deactivate()`; `ANIM_DURATION_MS = 500` (`:28`), plain linear
`t` in `_animate` (`:873`) — no easing. `activateWithDuration(ms)` exists for cadnano's two-stage
entry.

Arcs are **`THREE.LineSegments`** (`:189`), *not* `THREE.Line` — the file's own header comment
(`:9`) and the old runbook both said `Line`. `line.frustumCulled = false` at `:190` is real and
is what stops arcs vanishing when zoomed.

### Arc vertex colours are RGBA (itemSize 4), not RGB — 2026-08-01

All arcs of a strand type share ONE merged `LineSegments`, hence one material, so there is no
per-arc material to fade. A **4-component** colour attribute makes three define `USE_COLOR_ALPHA`
(`diffuseColor *= vColor` in `color_fragment`), which is the only per-arc alpha channel available
here. Per-cluster opacity rides it. Consequences:

- `_setArcColor(e, hex, alpha = _arcAlpha(e))` is the single write funnel, stride **4**. A leftover
  `* 3` index does not throw — it smears each arc's blue channel into its neighbour's alpha.
- The `alpha` default is load-bearing: selection highlight (`_setArcColor(e, 0xffffff)`), the
  RMSF/flex overlay (`applyFemArcColors`) and the strand-colour/group subscribers all pass a colour
  only, and would each silently un-fade the arc they touched if the default were 1.
- `transparent: true` on the material is required or the alpha is ignored.
- **Arcs are drawn in the plain 3D view too** (straight, bow = 0 at `t = 0`), so an arc-side gap in
  colouring or fading is visible without ever entering unfold.

Pinned by `scene/unfold_view.test.js` — source-text assertions, the file's first tests.

**Colouring modes are `strand` / `overhang-only` / `cluster`.** `_arcModeColor` resolves an arc's
cluster from `fromNuc`, falling back to `toNuc` — the same owner rule `design_renderer` uses for the
extra-base beads, so an arc and the inserted bases riding it can never disagree. Alpha takes the
**lower** of the two endpoints. `base` is still unwired and should stay that way: an arc spans two
nucleotides and has no single base identity.

Arc maps: `_buildXbArcMap` (`:435`, extra-base / `crossover_bases` beads) and `_buildExtArcMap`
(`:510`, strand extensions fanned 5′-left / 3′-right past the terminus). **There is no
`_buildArcMap`.**

## Ordering law (the "subscription order bug" — still real)

`unfoldView` subscribes at `main.js:1535`; `domainEnds` at `main.js:3006`. The store fires
subscribers in registration order, so on any topology mutation:

1. `unfoldView`'s subscriber fires → offsets applied to the **old** sprites
2. `domainEnds._rebuild()` fires → new sprites created at **3D** positions → offsets lost

**Fix (live, do not remove):** `domain_ends.js:593` calls `getUnfoldView?.()?.reapplyIfActive()`
at the end of its rebuild — guarded by `if (!store.getState().cadnanoActive)`, with the cadnano
branch above it re-applying `_lastCadnanoParams` instead. `reapplyIfActive` (`:1272`) no-ops when
unfold is inactive, so the unguarded-looking call is safe in plain 3D.

The same hazard applies to any *future* subscriber registered before a position-owning renderer.

## Cross-feature gates — all policy is in `_toggleUnfold` (`main.js:2541-2606`)

In order, entering unfold is refused when:

1. no design / no helices (`:2542`)
2. **the deform tool is active** — `if (isDeformActive()) return`, silent (`:2544`)
3. **atomistic mode is on** (`:2547`) — toast *"exit atomistic first"*. Note the direction:
   atomistic blocks unfold, **unfold does not hide atomistic**.
4. **deformations or a non-identity cluster transform are visually active** (`:2571-2586`) —
   toast *"press D to suppress them, then unfold"*. There is **no automatic snap-to-straight**.
5. `expandedSpacing.forceOff()` runs first (`:2578`) — the two offset mechanisms are exclusive.

Special cases:
- **U while cadnano is active** exits cadnano but *stays unfolded*
  (`cadnanoView.deactivate({keepUnfold: true})`, `:2553-2564`) — it does not toggle unfold off.
- **Turning unfold OFF re-activates the deform view** if it isn't already
  (`main.js:2599-2602` → `deformView.activate()` + menu toggle).

**Cadnano builds on unfold** (`cadnano_view.js:412-415`): `activate()` records
`_wasUnfoldActive` and awaits `unfoldView.activateWithDuration(ANIM_STAGE1_MS)` if not already
unfolded; `deactivate()` (`:494-509`) calls `setSpacing(...)` then `unfoldView?.deactivate()`
unless `keepUnfold` or `_wasUnfoldActive`. Details belong to `cadnano-2d.md`.

**Deform coupling runs both ways:**
- `unfold_view.js:1263` implements `applyDeformLerp(straightPosMap, deformT)` (2 args) and is
  member 3 of the 6-subsystem deform fan-out at `deform_view.js:154`.
- `deform_view.js:308` calls `getUnfoldView?.()?.reapplyIfActive()` — **not** on every lerp; it is
  inside the async `getStraightGeometry()` fallback subscriber, because `_applyLerp` there resets
  helix positions.
- `deform_view.js:344`: `if (newState.cadnanoActive || newState.unfoldActive) return` — deform
  refuses to auto-reactivate while unfold or cadnano owns bead positions.
- There is **no central arbiter**. Mutual exclusion is 4 independent checks: `main.js:2544`,
  `deform_view.js:344`, `view_menu_pills.js:43` (greys "Deformed View"),
  `translate_rotate_tool.js:30,597`.

## Reference implementation — restoring straight geometry

`unfold_view.js:925` (`deactivate`) and `:1024` (the externally-cleared-`unfoldActive`
subscriber) are the **only two call sites in all of `frontend/`** that call
`revertToGeometry(_straightPosMap, _straightAxesMap)` **with the straight maps**. The only other
caller is `design_renderer.js:1244` inside the zero-caller `clearFemOverlay()`, and it passes
nothing.

That matters beyond unfold: the sim-overlay stop path calls `revertToGeometry()` argument-less and
therefore restores *deformed* positions (see `RUNBOOK_DEFORMATION.md`, symptom 2). If anyone fixes
that path, this is the pattern to copy — don't "simplify" it away.

## Minimap

- `SIZE = 224` px canvas (`:31`), high-DPI backing store.
- **Position is `bottom: 8px; left: 8px`** (`:58-66`) — lower-**left**.
- Helix radius `Math.max(6, s * HELIX_WORLD_R)`, `HELIX_WORLD_R = 1.125` (`:315`).
- Selected-strand highlight `RING_HL = '#ffa726'` (`:38`).
- Pan = pointer drag; zoom = wheel, cursor-anchored, clamped `[2, 300]` px/nm (`:602`);
  double-click resets (`:610`).
- Visibility subscriber (`:616-649`): shows on `unfoldActive`, but on `unfoldActive → false` it
  **only hides if `_sliceOffsetNm === null`** — it deliberately stays up while a slice plane is
  live. `show()`/`hide()`/`clearSlice()` are also callable directly (`main.js:2556-2560`,
  `cadnano-2d.md`).

## Invariants

1. **The unfold view never decides row order.** It reads `unfoldHelixOrder`; the slice-plane code
   in `main.js` writes it. Fixing "wrong stacking order" means looking at `main.js:2729-2785`.
2. **All five fan-out callees must be notified at all four notify sites.** A subsystem notified at
   3 of 4 looks correct until an undo or a geometry change.
3. **A renderer registered after `unfoldView` must call `reapplyIfActive()` after any rebuild** —
   see the ordering law. `domain_ends.js:593` is the template.
4. **Unfold owns bead/sprite positions while active.** Deform, cadnano and the translate/rotate
   tool all read `unfoldActive` to stand down; a new position writer must do the same.
5. **Never auto-suppress deformations to enter unfold.** The user presses D. Gate 4 exists because
   silently zeroing the deform lerp was rejected.
6. **Z is never translated.** Only the orbit target moves (`getMidZ`).

## Traps — comments and neighbours that contradict the code

- `cross_section_minimap.js:2-3` says "lower-**right** corner". The CSS says `bottom/left`.
- `unfold_view.js:9` says the arcs are `THREE.Line`. They are `LineSegments`.
- The local variable `bluntEnds` in `main.js` refers to `domain_ends.js`. Don't grep for
  `blunt_ends.js` — it does not exist.
- `expanded_spacing.js` looks like a small utility; it is the **second implementation** of the
  fan-out contract and is the only caller of `atomistic_renderer.applyUnfoldOffsets`.

## Test coverage — honest version

**Almost zero.** `scene/unfold_view.test.js` (added 2026-08-01) is the only unit test, and it is
**source-text only** — it pins the arc colour-buffer contract (RGBA stride, the `_setArcColor`
alpha default, the cluster-display subscriber guard) because a stride bug there is silent. It runs
no code. `cross_section_minimap.js` and `expanded_spacing.js` still have **0 tests**. The only
behavioural coverage is one Playwright smoke, `frontend/e2e/test_unfold_debug.spec.js` (43 lines)
— it loads a design, toggles unfold and asserts no console errors. It does not assert a single
position, offset or arc.

## Removed API — do not resurrect

| Name | Status |
|---|---|
| `deformView.snapOff()` "called before unfold activates" | **0 callers repo-wide.** Defined `deform_view.js:218`, exported `:408`, never invoked. Unfold *blocks* instead (gate 4). |
| "View cube hidden when unfold active" | Never existed. `view_cube.js` has 0 hits for `unfold`; `hide()/show()` are wired only to the welcome screen (`main.js:3119/3134`). |
| "Atomistic hidden when unfold active" | Reversed — atomistic **blocks** unfold (`main.js:2547`). |
| `_buildArcMap` | Never existed. → `_buildXbArcMap` (`:435`) / `_buildExtArcMap` (`:510`). |
| `blunt_ends.js` | Renamed → `scene/domain_ends.js`. |
| `MAP_UNFOLD.md`, `MAP_CADNANO.md` | **Phantom docs — never existed in this repo.** Still cited by 5 files in `docs/triage/`. |
| `showHelixLabels` as an unfold key | Owned by `domain_ends.js`; unfold_view has 0 hits. |

## Diagnostics → [.claude/runbooks/RUNBOOK_UNFOLD.md](../runbooks/RUNBOOK_UNFOLD.md)
