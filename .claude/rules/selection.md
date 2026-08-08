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

One `selectionLevel ∈ {default, cluster, strand, domain, end, xover, base}`
(`selection_level.js`). `default` = no filter button engaged → click selects the strand, or
the leaf under the cursor (bead→end, cone/arc→crossover). A fixed level selects **only its own
type**: a mismatched click is a **no-op**, never a strand fallback. Esc → `default`. An engaged
level persists across an empty-space click.

- **Pure model** lives in `scene/selection_level.js` (150 LOC, no DOM/scene/store — unit-tested).
- **Click paths** are `_v2HandleBead` (`selection_manager.js:1840`), `_v2HandleCone` (`:1884`),
  `_v2HandleArc` (`:1938`).
- **Tab cycle is `strand → domain → end → xover → base → default`** — `TAB_CYCLE`
  (`selection_level.js`). **`cluster` is NOT in the cycle** (button-only; its `#select-filter`
  row sits below the cycle rows, before the divider). Two code comments still claim otherwise —
  see *Traps*. Each Tab also calls `selectionFilter.flashLevelChange(cur, next)` — see
  *The collapsed picker*.
- **`base` picks ONE bead** and is the only level that spans all five bead renderers — see
  *Base level* below. It is a level, not a gate: it has **no `selectableTypes` key**.
- Tab and Esc are bound in **`ui/keyboard_shortcuts.js`** (Tab `:285`, handler `:289`; Esc
  `:707`), **not** `main.js`. Tab is blocked while translate/rotate is active.
- API: `selectionManager.getSelectionLevel()` / `.setSelectionLevel(lv)`.

## File map

| File | LOC | Role | Tests |
|---|---|---|---|
| `scene/selection_manager.js` | 4179 | Everything stateful: raycasting, click/lasso/modifier paths, multi-select pools, hover preview, context menus | **none** |
| `scene/selection_level.js` | ~160 | Pure model: `LEVELS`, `TAB_CYCLE`, `BTN_LEVEL`/`LEVEL_BTN`, `normalizeLevel`, `nextTabLevel`, `toggleLevel`, `lassoCaptureType`, `toggleClusterSelection`, `hoverPreviewTarget` | 36 |
| `scene/base_ref.js` | ~125 | Pure: the base-level KEY format — `baseKey`, `xbKey`, `parseBaseKey`, `baseFamily`, `toggleBaseKey`, `dedupeBaseKeys`, `mergeBaseKeys` | 20 |
| `scene/base_pick.js` | ~215 | Base-level candidates across all five bead renderers + the pure `nearestCandidate` / `candidatesInRect` / `isVisibleChain` | 27 |
| `ui/selection_filter.js` | ~300 | Owns the whole collapsed picker: trigger label, menu open/close, Tab flash, buttons ↔ level; `computeFilterToggle`, `collapsedSelectable`, `initSelectionFilter` | 38 |
| `scene/selection_bbox.js` | 108 | Pure geometry: `selectionBBox`, `instanceUnionBox`, `nucleotideLocalBox`, `nucleotideBoxOverflow` (used by `main.js`, assembly renderers) | 17 |
| `scene/right_click_menu.js` | — | `deferrableContextMenu(canvas, handler)` — the shared contextmenu wrapper | yes |
| `ui/strand_menu_items.js` | — | `buildStrandMenuItems` — shared by `selection_manager.js:42` **and** `cadnano-editor/main.js:48` | yes |
| `ui/blunt_end_menus.js` | — | `initBluntEndMenus` (`main.js:2953`) — owns the former `_bluntInfo` panel | yes |
| `scene/empty_space_menu.js`, `scene/representation_overrides.js`, `scene/assembly_context_menu.js`, `ui/overhang_orientation_menu.js` | — | Further menu owners split out of selection_manager | — |

## The collapsed picker (2026-08-08)

The 11 buttons no longer sit inline in the strip. They are **static markup** inside the
`#select-filter-menu` drop-down — no JS builds them — and the strip shows only
`#select-filter-trigger`. Menu DOM order is
`strand, line, ends, xover, base, default, clust | scaf, stap, skip, loop, ovhangs`:
the level group leads in **TAB_CYCLE order** (so the Tab flash reads top-to-bottom), with
out-of-cycle `clust` after it. Every button still needs its own `.sf-btn.active[data-key="…"]`
CSS rule or it is **invisible when lit**, and every query is still
`#select-filter .sf-btn[data-key="…"]`.

- **`default` is now a real row** (`data-key="default"`, no `BTN_LEVEL` entry — `default` is the
  *absence* of an engaged level, so its click calls `setSelectionLevel('default')` directly).
  It is in `LEVEL_ONLY_BTNS` with a `null` storeKey, like `base`.
- **Trigger label** = `collapsedSelectable({selectionLevel, selectableTypes})` (pure, tested). An
  engaged `skips`/`loops`/`overhangs` gate **outranks the level**, because those already take
  precedence for clicks + lasso. A scaffold/staple restriction shows as a `scaf only` / `stap only`
  / `none` note, suppressed while an exclusive gate is up (it clears scaf+stap by design). The
  trigger's icon is **cloned from the reported row's `<svg>`** — each icon exists once in the markup.
- **Close policy:** picking a level closes the menu (one-shot choice); toggling a gate leaves it
  open. Outside `pointerdown`, Escape (not swallowed — Esc still drops the level), and arming a
  deform/translate tool also close it.
- **Tab flash:** `flashLevelChange(prev, next)` pops the menu open with `.sf-flash`
  (`pointer-events:none`), slides `.sf-menu-marker` from the outgoing row's `offsetTop` to the
  incoming one over 150 ms, and closes after 250 ms. A repeat Tab **restarts** the timer, so held
  Tab reads as one continuous scroll; a hand-opened menu is left open. It is wired from the Tab
  shortcut, **not** from `reflectDrillLevel` — that also fires on every canvas click.

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
| `multiSelectedBaseKeys` | — | `string[]` — base-level pool; **the only multi-pool with no `selectedObject` counterpart** |
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

`lassoCaptureType` returns `{strands, domains, ends, beadLevel, cluster, xover, base, overhangs,
loops, skips}`. **`beadLevel` is hard-coded `false`** — `end` captures 5′/3′ termini only.

**`beadLevel` is NOT the base-level hook. Do not merge them.** It looks like one, but at `base`
level `ends` is false so the loop guard `useEnds && (beadLevel || isEnd)` never fires — and if it
did, `endEntries` drains into **`_ctrlBeads`**, the measurement pool `measurement_tool.js` expects
to hold exactly 2. `base` has its own flag and its own accumulator.

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

## Base level — one bead, five renderers

`base` is the finest grain and the only level whose candidates come from **four different
renderers**. Every other picker in the app does
`[...new Set(backboneEntries.map(e => e.instMesh))].filter(m => m.visible)`, which reaches family 1
and nothing else; there is still no other aggregator.

| Family | Drawn by | Key |
|---|---|---|
| backbone beads · 5′ cubes · extension tails | `helix_renderer` `iSpheres`/`iCubes` | `helix:bp:dir[:copy]` |
| fluorophore / modification tips | `helix_renderer` `iFluoros` (`getFluoroEntries`) | same |
| extra crossover bases | `crossover_connections` `beadsMesh` | `__xb__:<xoId>:<k>` |
| flexible ssDNA arc beads | `flexible_arcs`, one mesh per connection | resolved via `segment_bead_keys[i]` |
| ss-linker bridge beads | `overhang_link_arcs`, one mesh per connection | `__lnk__<connId>:<slot>:FORWARD` |

- **Keys are strings, not objects** — `scene/base_ref.js` owns the format. `__xb__:<xoId>:<k>` is
  the repo's pre-existing pseudo-nucleotide address (crossover_connections, design_renderer's scalar
  colour path, `backend/core/atomistic.py`), reused verbatim rather than re-invented.
- **`parseBaseKey` splits from the RIGHT** — `__ext_<uuid>`, `__lnk__<connId>` and `__xb__`'s
  crossover-id field all contain separators.
- **The pool is key-based on purpose.** `flexible_arcs._render()` disposes and rebuilds its
  InstancedMeshes on every render — including every cluster-drag frame — so a pool holding
  mesh+instance references would go stale mid-gesture. Positions re-resolve at paint time via
  `_repaintBaseGlow()`; the rebuild subscriber re-resolves rather than clearing, and `main.js` calls
  `selectionManager.refreshBaseGlow()` right after `flexibleArcs.applyLiveUpdate`.
- **`selectedObject` stays `null` at base level** — deliberate. ~85 sites read that slot (delete
  key, per-bead context menu, extrude arrows); base is a selection *primitive*, so consumers opt in
  by reading `multiSelectedBaseKeys`. The only consumer today is the properties panel's readout.
  `_promoteSelectionToMulti` early-returns here: one pool means nothing to promote.
- **Highlight is glow-only** — no `setEntryColor`/`setBeadScale` (those exist only for families 1–2,
  `setEntryColor` is clobbered by any colour repaint, and `_clearCtrlBeads` restores scale `1.0`
  rather than `_beadScale`). Touches `instanceAlpha` zero times.
- **Visibility uses `isVisibleChain`, not `.filter(m => m.visible)`** — flexible-arc and ss-linker
  groups are **scene** children, not design-root children, so a hidden group is invisible to the
  leaf-only check. (It is wrong for the backbone meshes too: `iSpheres.visible` stays true while the
  design root is hidden in atomistic/surface mode.)
- **The `simBeadIndex` flip is load-bearing.** The geometric bead slot a click yields is not the
  5′→3′ insert index `__xb__:<xo>:<k>` means; `designRenderer.getXoverBeadEntries()` applies
  `simBeadIndex` and the candidate carries both `i` and `simK`. Getting it backwards silently
  mislabels every bead on a B→A crossover.
- **Explicit no-op at cylinder LOD** (no beads exist) and at the overhang filter (which keeps its
  documented precedence over every level).
- **Cost:** `_baseCandidates()` is rebuilt per pointer event and never memoized — 1.2 ms for 18k
  candidates, the same order `_nearestBead` already pays.

### Downstream: anchors + the occupancy-cloud scope

The pool feeds both, through ONE read — `resolveSelectionAnchors` (`scene/efield_math.js`). The
occupancy scope card *is* the anchor widget with `engine:'occupancy'`, so wiring the pool there
lit up all six anchor cards, the scope picker and the purple halo at once.

`partitionBaseKeys` maps each family to the descriptor kind the backend can actually resolve:

| Family | Kind | Backend match |
|---|---|---|
| backbone · flexible ssDNA · ss-linker | `base` | `(helix_id, bp, direction)` provenance |
| crossover extra bases | `extra_base` | key `("__xb__", crossover_id, k)` |
| extension tails | `extension` | key `("__ext_<id>", k, direction)` |

The synthetic two exist because `_walk_strand_nucleotides` gives those beads
`helix_id/bp/direction = None` — no coordinate criterion can ever reach them. Omit `k` to take
the whole run/tail. Staleness is checked per family against the live design, because the backend
resolves a dead descriptor to **zero particles silently**.

**oxDNA only.** mrDNA double-filters extension beads and has no `nt_key` for extra bases; NAMD's
`built_pdb_residue_keys` stores a synthetic residue under its *flanking* nucleotide's key, so a
`base` anchor there already over-selects them; CanDo/SNUPI mesh nodes are duplex-core only.

**Unverified:** the ss-linker slot→bp mapping. The bridge nucleotides are real (`__lnk__<conn>__s`,
excluded from `iSpheres` so the arc can draw them), but the mesh is *sized* from
`linkerLengthToBases(conn)` — derived from `conn.length_value`, independent of the geometry — so a
slot is addressed-but-unproven. Family 4 (flexible arcs) has **no fixture in the repo at all**
(`flexible_connections` is empty in every `.nadoc`); its builder is unit-tested but has never run
against real meshes.

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

## Traps — silent failures when adding a LEVEL

Three sites fail *quietly* — no error, just wrong behaviour. Learned adding `base`; check all three
before adding the next level.

1. **`_v2HandleCone` and `_v2HandleArc` guard by explicit OR-LIST**
   (`if (_selLevel === 'domain' || _selLevel === 'end' || _selLevel === 'base')`), not by `else`.
   An unlisted level **falls through to the default drill branch and selects a whole strand**.
2. **`attachFilterButtons` iterates `SEL_KEY_MAP`**, which is keyed on `selectableTypes`. A
   level-only button has no row there, so it gets **no click listener** — while `V2_LEVEL_KEYS` and
   `reflectDrillLevel` (both derived from `BTN_LEVEL`/`LEVEL_BTN`) *do* pick it up and light it from
   Tab. Result: a button that looks live and does nothing. `LEVEL_ONLY_BTNS` exists for this.
3. **`_toggleAtLevel` and `_promoteSelectionToMulti` branch on `st.crossoverArcs`** — a
   `selectableTypes` flag *independent of the engaged level*. A new level's branch must sit **after**
   the overhang branch (preserving overhang precedence) and **before** the crossoverArcs branch, or
   that gate hijacks its Ctrl+clicks.

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
Everything that *is* pinned is the pure/DOM-thin periphery: `selection_level.test.js` (36),
`selection_bbox.test.js` (17), `selection_filter.test.js` (38), `base_ref.test.js` (20),
`base_pick.test.js` (27), plus Tab/Esc cycling inside `keyboard_shortcuts.test.js`. Assembly-side
selection has its own (`assembly_lasso.test.js`, `assembly_pointer.test.js`,
`assembly_multi_box.test.js`) — different stack. No pytest touches selection.

E2E exists but is **not** routine (see `CLAUDE.md`): `frontend/e2e/` has `drill_v2_select.spec.js`,
`bead_select.spec.js`, `base_select.spec.js`, `base_select_families.spec.js`,
`assembly_select.spec.js`, `assembly_overhang_select.spec.js`, `dsdna_linker_selection.spec.js`,
`joint_indicator_selection.spec.js`.

**Camera trap for any bead-picking spec.** `loadScaffoldedPart` never moves the camera, so every
bead projects outside the NDC cube and `beadCandidates` returns `[]` — this is why
`bead_select.spec.js` fails in a fresh checkout. Even after `f` (fit-to-view) the whole 200-bp part
spans ~24 px, so all 199 beads sit inside the 80 px magnet and no two clicks can resolve to
different bases. `base_select.spec.js`'s `loadFramedPart` does fit **then wheel-zoom** to a ~670 px
spread; copy it rather than re-deriving.

**The pattern to copy:** the tested modules are tested *because* they were extracted pure.
`base_pick.js` takes an injected `project(cand) → {x,y}|null` for exactly this reason — the magnet
and rect tests run against a fake projector with no scene.
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
