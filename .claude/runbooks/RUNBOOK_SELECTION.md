# selection — diagnostics runbook

Loaded on demand from the `selection` rule's Diagnostics pointer. Symptom → diagnosis; not
auto-loaded. Architecture lives in [`.claude/rules/selection.md`](../rules/selection.md) — read
that for what the code *is*; this file is only for when something misbehaves.

Rewritten 2026-07-30 (`/audit-plan`) — the previous version's worked example, its `deformToolActive`
diagnosis and its Ctrl+click measurement tree all named symbols/mechanisms that no longer exist.

## Symptoms index

| Symptom | Go to |
|---|---|
| Clicking a bead/strand does nothing at all | §1 |
| Click selects the *wrong granularity* (whole strand when you wanted a domain, etc.) | §2 |
| Clicking a crossover selects nothing, or picks a stray cone | §3 |
| Ctrl+click replaces the selection instead of adding to it | §4 |
| Lasso captures the wrong element type | §5 |
| Context-menu item is visible but the handler no-ops | §6 |
| Measurement `[X]` does nothing after picking two beads | §7 |
| Hover preview is missing, or highlights the wrong thing | §8 |
| Selection glow survives / vanishes wrongly after a rebuild | §9 |

---

## §1 Click does nothing at all

1. **`store.deformToolActive`** — if stuck true, `main.js:4318–4335` has zeroed every
   `selectableTypes` flag. Events still arrive; every capture filter returns false. Check
   `store.getState().selectableTypes` in the console: all-false with the deform tool closed means
   the restore branch didn't run and `_savedSelectableTypes` is holding the real values.
   *(The old runbook said events are intercepted at capture phase. They are not.)*
2. **`isDisabled`** (`main.js:982`) — `slicePlane?.isContinuation() || store.forceXoverActive`.
   A slice-plane continuation drag or an active force-crossover tool disables the manager wholesale.
3. **`selectableTypes` for the type you clicked** — the relevant category flag must be on. Note
   `domains`, `ends`, `crossoverArcs`, `clusters`, `overhangs`, `loops`, `skips`, `extensions` all
   default **false**; only `scaffold`, `staples`, `strands` default true.
4. **Global gates** — `selectableTypes.scaffold` / `.staples` block by strand *type* at three
   sites (beads `:3459`, cones `:3472`, arcs `:3250`). Deselecting "stap" makes every staple
   unclickable even at strand level.
5. **Don't confuse `toolFilters` with `selectableTypes`.** `toolFilters` is overlay visibility
   only (`store.js:136`) and never gates a click.
6. **NDC** — `_setNdc` (`:3226`) must use `canvas.getBoundingClientRect()`. Any new code path using
   `window.innerWidth/Height` misses by the sidebar width and picks nothing near the edges.

## §2 Wrong granularity

The level is the whole story. `selectionManager.getSelectionLevel()`.

- A **fixed** level selects only its own type — a mismatched click is a deliberate **no-op**, not a
  bug, and there is no strand fallback (`_v2HandleBead/Cone/Arc`).
- `default` (no button engaged) = strand, or the leaf under the cursor.
- If Tab lands somewhere unexpected: the cycle is `TAB_CYCLE` in `selection_level.js:30` —
  `strand → domain → end → xover → default`. **`cluster` is not in it.** The comments at
  `keyboard_shortcuts.js:282` and `:287` claim it is; they are wrong.
- Level buttons are static markup (`index.html:6255–6298`) wired by `ui/selection_filter.js`. A
  button that looks engaged but doesn't change behavior → check `BTN_LEVEL`/`LEVEL_BTN`
  (`selection_level.js:35–36`) for a `data-key` mismatch; the map is not identity
  (`line`→`domain`, `ends`→`end`, `clust`→`cluster`).
- In mixed representation the pick is capped by the column's rep: cylinders→domain,
  surface→strand, full/vdw/ballstick→nucleotide, via `_repEntryFor` (`:2261`) +
  `designRenderer.columnRepAt`. A domain-level click that yields a whole strand in a
  surface-rendered region is that cap, working as designed.

## §3 Crossover won't select

1. Level must be `xover` (or `default` with the cursor on the arc). Crossovers are **arc-only** —
   cones never select one.
2. `selectableTypes.crossoverArcs` must be on for a fixed-level pick.
3. `_arcCrossoverBlocked()` (`:3250`) applies the scaffold/staple gate to arcs. Arcs with a null
   `crossover_id` are exempt — if a *non*-crossover arc selects and a real crossover doesn't, the
   gate is the reason.
4. If a stray invisible cone flashes at 0.12 scale, the cross-helix exclusion has regressed —
   it lives at `:3471` (`selCones` filter) **and** `:2019` (`_pickNearestBeadCone`). Both are
   required; fixing one leaves the other path pickable.

## §4 Ctrl+click replaces instead of adds

`_toggleAtLevel` (`:2962`) calls `_promoteSelectionToMulti()` (`:2880`) **first**, which folds a
prior plain-click `selectedObject` into the matching multi pool. If "plain-click A, Ctrl-click B"
ends with only B, the promote branch for that level is missing or mismatched — branches are
cluster `:2887`, end `:2903`, xover `:2924`, domain `:2935`, strand/default `:2947`.

Single selection and the multi pools are **separate stores** — a UI reading only `selectedObject`
will look empty during a multi-select and vice versa. The pools: `multiSelectedStrandIds`,
`multiSelectedDomainIds`, `multiSelectedOverhangIds`, `multiSelectedClusterIds`, plus the
closure-scoped `_ctrlBeads` and `_multiCrossoverArcs` (read via `getCtrlBeads()` /
`getMultiCrossoverArcs()`).

**Clusters:** presence is decided by the cluster-**id** pool, never by "are all its strands
selected" — two clusters can share a bridging staple. Pure rule `toggleClusterSelection()`
(`selection_level.js:123`).

Shift+click is a literal alias of Ctrl+click (`:2999–3001`). Shift+**drag** is a no-op by design —
if someone reports "shift-lasso doesn't work", that's correct behavior; lasso is Ctrl-only.

## §5 Lasso captures the wrong type

`lassoCaptureType({selLevel, overhangFilter})` (`selection_level.js:91`) decides, and it is pure —
reproduce it in a unit test before touching the caller.

- **`overhangFilter` (= `selectableTypes.overhangs`) takes precedence over the level** and returns
  overhangs-only. A lasso that ignores your level is almost always the overhang gate left on.
- `beadLevel` is hard-coded `false` — `end` captures 5′/3′ termini only, never interior beads.
- At cluster level the lasso is **additive** and fills `multiSelectedClusterIds` *and* the member
  strands. At cylinder LOD it resolves clusters via `getCylinderDomainData()`
  (`helix_renderer.js:2961` → `design_renderer.js:1172`), not beads — if cluster lasso works at
  full detail but not in cylinder view, that call is the suspect.

## §6 Context-menu handler no-ops

**The state-capture pattern.** A handler that (1) reads closure state and (2) calls a cleanup
function that nulls that state must capture into a `const` **first**:

```js
// WRONG — always exits early
function _handleThing() {
  _hideMenu()          // nulls _thingInfo
  if (!_thingInfo) return   // always returns
}

// CORRECT
function _handleThing() {
  const info = _thingInfo   // capture FIRST
  _hideMenu()               // now safe to null
  if (!info) return
}
```

Then: **find the right file.** Most menus have left `selection_manager.js`, which now keeps one
`contextmenu` listener (`:3700`) and two `deferrableContextMenu` uses. Menu owners:

| Menu | File |
|---|---|
| shared contextmenu wrapper `deferrableContextMenu` | `scene/right_click_menu.js:33` |
| strand items (shared with the cadnano editor) | `ui/strand_menu_items.js` |
| blunt ends | `ui/blunt_end_menus.js` (`initBluntEndMenus`, `main.js:2953`) |
| empty space | `scene/empty_space_menu.js` |
| representation overrides | `scene/representation_overrides.js` |
| assembly | `scene/assembly_context_menu.js` |
| overhang orientation | `ui/overhang_orientation_menu.js` |

Other canvas `contextmenu` listeners that can win the event: `main.js:1742`, `main.js:5802`
(assembly), `scene/domain_ends.js:566` (**capture phase**), `scene/slice_plane.js:1843`.

## §7 Measurement `[X]` does nothing

1. `getCtrlBeads()` must return exactly 2 entries. **Beads are picked with Alt+click, not
   Ctrl+click** (changed 2026-05-17) — Ctrl+click is the multi-select toggle now.
2. `selectionManager.onCtrlBeadsChange(cb)` (`:4145`) is registered inside `initMeasurementTool`
   (`main.js:993–1001`), not inline in main.
3. The `X` key handler is in `ui/keyboard_shortcuts.js`; the tool itself is
   `scene/measurement_tool.js`. Neither is in `main.js` any more.

## §8 Hover preview missing or wrong

- Preview is **yellow `0xffe000`** (`design_renderer.js:75`, `:87`). Three code comments call it
  red (`selection_level.js:59`, `selection_manager.js:2028`, `:2126`) — ignore them.
- Snap radius is `_NEAR_HOVER_PX = 80` (`:2031`); the click commits the *previewed* nearest, so a
  preview/commit mismatch means two different nearest-searches are running.
- The already-selected element is intentionally skipped (stays green) via `_selectedLevelKey()`
  (`:2118`, used `:2208`). "Preview doesn't show on the thing I have selected" is correct.

## §9 Glow wrong after a rebuild

`_setSelectionGlow` splits highlighted entries: bead-rendered domains get sphere glow,
cylinder-rendered domains get cylinder glow (no double halo). The post-rebuild subscription
re-applies single `domain`/`cluster` modes; if a conversion rebuild clears the glow, that
re-apply branch fell through to the else. See `memory/project_mixed_representation.md`.

---

## Before you edit `selection_manager.js`

It is **4179 LOC with zero unit tests**. The three sibling modules are tested precisely because
they are pure. If the change you're about to make can be expressed as a function of
(level, hit, flags) → decision, put it in `scene/selection_level.js` and pin it there.
