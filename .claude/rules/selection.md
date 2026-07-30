---
name: selection
description: Selection-level model, click/lasso/modifier semantics, selectable-type gates, context-menu split, NDC rule.
paths:
  - "frontend/src/scene/selection_manager.js"
  - "frontend/src/scene/selection_level.js"
  - "frontend/src/scene/selection_bbox.js"
  - "frontend/src/ui/selection_filter.js"
  - "frontend/src/scene/right_click_menu.js"
  - "frontend/src/scene/empty_space_menu.js"
  - "frontend/src/ui/strand_menu_items.js"
  - "frontend/src/ui/blunt_end_menus.js"
  - "frontend/src/scene/measurement_tool.js"
  - "frontend/src/ui/keyboard_shortcuts.js"
---

# selection

Design-mode 3D selection: what a click/lasso picks, at what granularity, and what gates it.
**Not this rule:** assembly-instance selection (`scene/assembly_lasso.js`, `assembly_pointer.js`,
`assembly_multi_box.js` — a parallel stack with its own tests), and the cadnano *editor* app's
own `#select-filter` (`frontend/cadnano-editor.html:1277`, wired `cadnano-editor/main.js:706` —
see `.claude/rules/cadnano-editor.md`).

Verified against the code 2026-07-30 (`/audit-plan`). Line numbers drift; symbol names don't.

## Selection-level model (ISSUE-4) — the ONLY selection model

One `selectionLevel ∈ {default, cluster, strand, domain, end, xover}`
(`selection_level.js:26`). `default` = no filter button engaged → click selects the strand, or
the leaf under the cursor (bead→end, cone/arc→crossover). A fixed level selects **only its own
type**: a mismatched click is a **no-op**, never a strand fallback. Esc → `default`. An engaged
level persists across an empty-space click.

- **Pure model** lives in `scene/selection_level.js` (150 LOC, no DOM/scene/store — unit-tested).
- **Click paths** are `_v2HandleBead` (`selection_manager.js:1840`), `_v2HandleCone` (`:1884`),
  `_v2HandleArc` (`:1938`).
- **Tab cycle is `strand → domain → end → xover → default`** — `TAB_CYCLE`
  (`selection_level.js:30`). **`cluster` is NOT in the cycle** (button-only; its `#select-filter`
  button sits in the gate group with skip/loop/ovhg). Two code comments still claim otherwise —
  see *Traps*.
- Tab and Esc are bound in **`ui/keyboard_shortcuts.js`** (Tab `:285`, handler `:289`; Esc
  `:707`), **not** `main.js`. Tab is blocked while translate/rotate is active.
- API: `selectionManager.getSelectionLevel()` / `.setSelectionLevel(lv)`.

## File map

| File | LOC | Role | Tests |
|---|---|---|---|
| `scene/selection_manager.js` | 4179 | Everything stateful: raycasting, click/lasso/modifier paths, multi-select pools, hover preview, context menus | **none** |
| `scene/selection_level.js` | 150 | Pure model: `LEVELS`, `TAB_CYCLE`, `BTN_LEVEL`/`LEVEL_BTN`, `normalizeLevel`, `nextTabLevel`, `toggleLevel`, `lassoCaptureType`, `toggleClusterSelection`, `hoverPreviewTarget` | 33 |
| `ui/selection_filter.js` | 129 | Wires the `#select-filter` buttons ↔ level; `computeFilterToggle`, `initSelectionFilter` | 15 |
| `scene/selection_bbox.js` | 108 | Pure geometry: `selectionBBox`, `instanceUnionBox`, `nucleotideLocalBox`, `nucleotideBoxOverflow` (used by `main.js`, assembly renderers) | 17 |
| `scene/right_click_menu.js` | — | `deferrableContextMenu(canvas, handler)` — the shared contextmenu wrapper | yes |
| `ui/strand_menu_items.js` | — | `buildStrandMenuItems` — shared by `selection_manager.js:42` **and** `cadnano-editor/main.js:48` | yes |
| `ui/blunt_end_menus.js` | — | `initBluntEndMenus` (`main.js:2953`) — owns the former `_bluntInfo` panel | yes |
| `scene/empty_space_menu.js`, `scene/representation_overrides.js`, `scene/assembly_context_menu.js`, `ui/overhang_orientation_menu.js` | — | Further menu owners split out of selection_manager | — |

The `#select-filter` buttons are **static markup in `frontend/index.html:6255–6298`** — no JS
builds them. DOM order: `scaf, stap | strand, line, ends, xover | skip, loop, ovhangs, clust`.

## Entry & Initialization

`initSelectionManager(canvas, camera, designRenderer, opts = {})` — defined
`selection_manager.js:1649`, called **`main.js:820`**.

`opts` destructures **26** callbacks (`:1650`); the in-file JSDoc at `:1647` documents only 7 and
is stale. Full list:

- **Actions:** `onNick`, `onLoopSkip`, `onOverhangArrow`, `onScaffoldAssignSequence`,
  `onEditStrandSequence`, `onSetOverhangName`, `onOpenOverhangsManager`, `onClusterMoveRotate`,
  `onDrillLevel`
- **Right-click:** `onCrossoverRightClick`, `onFlexibleSegmentRightClick`, `onOverhangRightClick`,
  `onEmptyContextMenu`
- **Getters:** `getUnfoldView`, `getOverhangLocations`, `getOverhangLinkArcs`, `getFlexibleArcs`,
  `getLoopSkipHighlight`, `getHoverEntry`, `getCamera`, `getProteinRenderer`,
  `getRegionVdwRenderer`, `getRegionBallstickRenderer`, `getRegionSurfaceRenderer`
- **Control:** `controls`, `isDisabled`

`isDisabled` (`main.js:982`) is `slicePlane?.isContinuation() || store.forceXoverActive` —
**it does not check `deformToolActive`** (see *Invariants* #1).

Returned API (19 methods, `:4037–4178`): `selectStrand`, `selectNucleotide`, `selectOverhang`,
`openExtensionsForStrands`, `selectCluster`, `toggleCluster`, `getSelectionLevel`,
`clearSelection`, `setSelectionLevel`, `getCtrlBeads`, `clusterMemberStrandIds`, `getCtrlBeadPos`,
`onCtrlBeadsChange`, `clearCtrlBeads`, `setMultiHighlight`, `getMultiCrossoverArcs`,
`getSelectedCrossoverArc`, `clearMultiCrossoverArcs`, `clearMultiOverhangSelection`.

## Store keys (`frontend/src/state/store.js`)

| Key | Line | Shape |
|---|---|---|
| `selectedObject` | `:72` | `{type, id, data} \| null` — **10** real `type` values, see below |
| `multiSelectedStrandIds` | `:100` | `string[]` |
| `multiSelectedDomainIds` | `:108` | `{strandId, domainIndex}[]` |
| `multiSelectedOverhangIds` | `:113` | `string[]` |
| `multiSelectedClusterIds` | `:123` | `string[]` |
| `toolFilters` | `:136` | `{bluntEnds, overhangLocations, extensionLocations}` — overlay **visibility only** |
| `selectableTypes` | `:148` | 11 flags, below |

`selectedObject.type` actually assigned across the codebase (85 sites):
`nucleotide` · `strand` · `cluster` · `protein` · `domain` · `crossover` · `overhang` · `helix` ·
`forced_ligation` · `cone`. Canonical builders in `selection_manager.js`: cluster `:1736`,
domain `:1796`, nucleotide `:1815`, cone `:1829`, strand `:2276`, protein `:3523`.
**`store.js:69`'s doc comment still says only `'nucleotide' | 'helix' | 'strand'` — it is wrong.**

`selectableTypes` (11 flags, `store.js:148–161`):
- **Global gates:** `scaffold`, `staples` (both default `true`)
- **Category:** `clusters`, `strands`, `domains`, `ends`, `crossoverArcs`
- **Independent:** `loops`, `skips`, `extensions`, `overhangs`

`_ctrlBeads` (`:2621`) is **closure-scoped inside `initSelectionManager`**, not in the store and
not file-module scope. Companion `_ctrlBeadsChangeCbs` `:2622`. Read it via `getCtrlBeads()`.

Store subscriber channels: `selection` covers `selectedObject`, all four multi-pools,
`selectableTypes`, `crossoverPlacement`, `deformToolActive` (`store.js:396`). `toolFilters` is on
the **`ui`** channel (`:411`) — subscribing to `selection` will not see it change.

## Click / lasso / modifier semantics

```
pointerdown → _setNdc via canvas.getBoundingClientRect()  → raycaster
            → intersects backbone / cone / arc instanced meshes
            → _v2Handle{Bead,Cone,Arc} at the active level
            → store.setState({ selectedObject })

right-click  → context menu (color / nick / loop-skip / isolate / representation …)
               selection_manager keeps ONE contextmenu listener (:3700) + 2
               deferrableContextMenu uses; the rest moved out (see File map).

Ctrl+drag    → lasso rectangle. Capture type from lassoCaptureType({selLevel, overhangFilter})
               (selection_level.js:91). overhangFilter (= selectableTypes.overhangs) takes
               PRECEDENCE over the level → overhangs only. Cluster level is ADDITIVE (promotes a
               prior plain-click cluster first) and fills multiSelectedClusterIds plus the member
               strands; at cylinder LOD it resolves clusters from getCylinderDomainData()
               (helix_renderer.js:2961 → design_renderer.js:1172), not beads.

Ctrl+click   → unified multi-select TOGGLE at the active level (snap-to-nearest, hover radius).
  (no drag)    _toggleAtLevel(:2962) dispatches: promote → sidebar guard → overhang → xover →
               end → bead(domain/cluster/strand), to _toggle{Strand:2783, Domain:2792,
               Overhang:2805, Crossover:2814, EndBead:2823, Cluster:2869}.
               ADDITIVE-FROM-PLAIN: _promoteSelectionToMulti(:2880) folds a prior PLAIN-click
               selectedObject into the matching pool FIRST — "plain-click A, Ctrl-click B" ends
               with BOTH selected (single selection and the multi pools are separate stores).
               Branches: cluster :2887, end :2903, xover :2924, domain :2935, strand :2947.
               CLUSTER presence is decided by the CLUSTER-id pool, never by "are all its strands
               selected" (two clusters can share a bridging staple) — pure rule
               toggleClusterSelection() (selection_level.js:123). The sidebar "Movable Clusters"
               rows Ctrl/Cmd/Shift+click into the SAME pool via selectionManager.toggleCluster(id)
               → _toggleClusterById(cid, {promote}) (:2850). A plain row click stays a single
               selection (and auto-opens Move/Rotate); an additive one never opens the gizmo —
               the gizmo drives exactly one cluster.

Shift+click  → literal alias of Ctrl+click (both call _toggleAtLevel, :2999–3001).
               Shift+DRAG is a no-op — no lasso branch reads _shiftDownPos. Lasso is Ctrl-only.

Alt+click    → _ctrlBeads toggle (measurement) + capped-2 overhang toggle for the Overhangs
               Manager. [measurement moved OFF Ctrl on 2026-05-17]
```

Modifier precedence is **Alt > Shift > Ctrl** (`:3298`). `_altDownPos` (`:3289`) and
`_shiftDownPos` (`:3290`) hold deferred-click positions; both clear on lasso-finalize
(`:3380`) and on their own click paths (`:3389`, `:3397`).

`lassoCaptureType` returns `{strands, domains, ends, beadLevel, cluster, xover, overhangs, loops,
skips}`. **`beadLevel` is hard-coded `false`** (`:105`) — `end` captures 5′/3′ termini only.

## Crossover arcs & hover preview

- **Crossovers select as ARCs only**, rendered as a green glow TUBE via
  `designRenderer.setSelectionArc` (`design_renderer.js:844`) / `setSelectionArcs` (`:866`).
  `PREVIEW_ARC_RADIUS = 0.147` (`:78`, aliased `SELECTION_ARC_RADIUS` `:79`);
  `ARC_TUBE_RADIAL = 12` (`:82`); tubular segments `_arcTubeSegs = n => max(16, n*4)` (`:83`);
  `DoubleSide` + `depthTest:false` on both preview (`:89`) and selection (`:102`) materials.
- **Cones never select a crossover.** Cross-helix cones (the invisible connectors that FEED the
  arc pipeline in `helix_renderer`) are excluded at two sites — the `selCones` filter
  (`selection_manager.js:3471`, `if (e.isCrossHelix) return false`) and `_pickNearestBeadCone`
  (`:2019`) — so they can neither be picked nor flash visible via `_highlightCone`'s 0.12 scale
  (`:2363–2365`).
- **Hover preview is YELLOW `0xffe000`** at every level: `_previewGlowLayer`
  (`design_renderer.js:75`) + `_previewArcMat` (`:87`). Snap-to-nearest within
  `_NEAR_HOVER_PX = 80` (`selection_manager.js:2031`); the click commits the previewed nearest.
  The already-selected element is skipped (stays green) via `_selectedLevelKey()` (`:2118`,
  used `:2208`). Three code comments still call this preview "red" — see *Traps*.

## NDC rule

All raycaster NDC coords use `canvas.getBoundingClientRect()` (`_setNdc`, `:3226`).
**Never** `window.innerWidth/Height`.

## Invariants

1. **Deform blocks selection by ZEROING `selectableTypes`, not by intercepting events.** A
   subscriber at `main.js:4318–4335` saves `_savedSelectableTypes` and writes an all-false
   `selectableTypes` when `deformToolActive` flips on, restoring it on exit. The selection manager
   still receives every pointer event; each capture filter just returns false. Secondary effects:
   `ui/selection_filter.js:88` (button clicks suppressed), `:121` (`.filter-inactive` class).
   There is **no capture-phase event interception** anywhere on this path.
2. `toolFilters` is overlay **visibility** only. Changing it never affects click/lasso behavior.
3. `selectableTypes.scaffold` / `.staples` are **global** gates hit at three literal sites — beads
   (`:3459`), cones (`:3472`), arcs (`_arcCrossoverBlocked` `:3250`). Arcs with a null
   `crossover_id` are exempt.
4. Capture closure/module state into a `const` **before** calling any cleanup function that nulls
   it (context-menu handlers). See `RUNBOOK_SELECTION.md`.
5. `selection_manager.js` never reads `store.unfoldActive`. It reaches unfold state **only**
   through the injected `getUnfoldView()` opt (`:2104, 2326, 2925, 3160, 3262, 4170`), and only to
   pull `getArcEntries()`. Raycasting works unchanged in unfold (meshes are translated).
6. `_effectiveColors(strandColors, strandGroups)` (`design_renderer.js:151`) merges
   `store.strandColors` + `store.strandGroups`, **group wins**.

## Traps — code comments that contradict the code

These are wrong in the *source*, not here. Don't "fix" the code to match them.

- `ui/keyboard_shortcuts.js:282` and the `description` at `:287` say the Tab cycle is
  "cluster → strand → domain → end → xover". **Cluster is not in the cycle** (`TAB_CYCLE`).
- `selection_level.js:59`, `selection_manager.js:2028`, `:2126` call the hover preview **red**.
  It is yellow `0xffe000`.
- `store.js:69` documents `selectedObject.type` as 3 values; there are 10.
- `selection_manager.js:1647` JSDoc lists 7 of 26 opts.

## Test coverage — be honest

`selection_manager.js` is **4179 LOC with zero unit tests**. There is no `selection_manager.test.js`.
Everything that *is* pinned is the pure/DOM-thin periphery: `selection_level.test.js` (33),
`selection_bbox.test.js` (17), `selection_filter.test.js` (15), plus Tab/Esc cycling inside
`keyboard_shortcuts.test.js` (`:150, 614–651`). Assembly-side selection has its own
(`assembly_lasso.test.js`, `assembly_pointer.test.js`, `assembly_multi_box.test.js`) — different
stack. No pytest touches selection.

E2E exists but is **not** routine (see `CLAUDE.md`): `frontend/e2e/` has `drill_v2_select.spec.js`,
`bead_select.spec.js`, `assembly_select.spec.js`, `assembly_overhang_select.spec.js`,
`dsdna_linker_selection.spec.js`, `joint_indicator_selection.spec.js`.

**The pattern to copy:** the three tested modules are tested *because* they were extracted pure.
New logic in `selection_manager.js` should land in `selection_level.js` (pure) wherever it can.

## Removed API — do not resurrect

Deleted **2026-06-06** with the legacy auto-drill ladder; zero hits anywhere in `frontend/`:

| Dead symbol | Was |
|---|---|
| `_autoDrill()`, `_autoDrillBead`, `_autoDrillCylinder` | the click-count drill ladder (1st=strand, 2nd=domain, 3rd=bead) |
| `_drillLock` | Tab drill-lock |
| `_manualFilters` | manual filter pins, separate from `selectableTypes` |
| `NADOC_DRILL_V2` | the opt-out flag — there is no opt-out |

Surviving lookalike: **`_drillClusterId`** (`selection_manager.js:1673`) is deliberate and live.
Also live and unrelated: `_handleBeadHit` (`:2253`), `_repEntryFor` (`:2261`) — the mixed-rep
region-pick path.

Also dead / dangling:
- **`MAP_SELECTION.md` does not exist** anywhere in the repo. The old "Related" pointer was a
  dangling link for its whole life.
- `_bluntInfo` — zero hits; the blunt-end menu moved to `ui/blunt_end_menus.js`.
- `_pendingEntry` — left `selection_manager.js`; now `main.js:1117` (overhang-length dialog).
- `_handleExtrude` — never existed in the current tree (it was the runbook's worked example).

## Diagnostics → [.claude/runbooks/RUNBOOK_SELECTION.md](../runbooks/RUNBOOK_SELECTION.md)
