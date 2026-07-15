---
name: selection
description: Selection 3-click model, lasso, context menus, selectable types, NDC rule.
paths:
  - "frontend/src/scene/selection_manager.js"
---

# selection

> **Selection-level model (ISSUE-4).** The ONLY selection model: one
> `selectionLevel ∈ {default,cluster,strand,domain,end,xover}`. Default click =
> strand → leaf-under-cursor (bead→end | cone/arc→crossover); the #select-filter
> level buttons + Tab set a fixed level; Esc → default; an engaged level persists
> across an empty-space click. Pure model in `scene/selection_level.js`; click
> paths in `selection_manager.js` are `_v2HandleBead`/`_v2HandleCone`/`_v2HandleArc`.
> The legacy auto-drill ladder / manual filter pins / Tab drill-lock + the
> `NADOC_DRILL_V2` flag were PHYSICALLY DELETED 2026-06-06 — there is no opt-out and
> no `_autoDrill*`/`_drillLock`/`_manualFilters` any more. **Note:** some click/lasso
> descriptions below predate this and describe the old auto-drill path — trust
> `selection_level.js` + the `_v2Handle*` functions for current behavior.
> API: `selectionManager.{get,set}SelectionLevel`.

> **Selection-rules UX (2026-06-07, VALIDATED — MV-3).** Built on the model above:
> - **Tab cycle is `strand→domain→end→xover→default` — CLUSTER is NOT in it** (button-
>   only; its `#select-filter` button moved into the gate group with skip/loop/ovhg).
> - **Fixed levels select ONLY their own type** — a mismatched click is a no-op (no
>   strand fallback) in `_v2HandleBead/Cone/Arc`; `end` selects only 5′/3′ termini.
> - **Crossovers = ARC only, rendered as a green glow TUBE** (`designRenderer.setSelection
>   Arc[s]`, r=`PREVIEW_ARC_RADIUS`=0.147, 12 radial segs, DoubleSide, depthTest:false).
>   Cones never select a crossover; cross-helix cones (the invisible connectors that
>   FEED the arc pipeline in `helix_renderer`) are excluded from `selCones`/`_pickNearest
>   BeadCone` so they can't be picked or flash visible via `_highlightCone`'s 0.12 scale.
>   Single-click + lasso + Ctrl+click multi-toggle all share the tube form.
> - **Generic YELLOW hover preview** (`_previewGlowLayer`/`_previewArcMat` = `0xffe000`)
>   at every filter level: hover shows what a click selects (same form as the green
>   selection), snap-to-nearest within `_NEAR_HOVER_PX`=80; the click commits the
>   previewed nearest. The **already-selected** element is skipped (stays green) via
>   `_selectedLevelKey()` / per-branch `_mode`+id checks.

## Architecture

## Entry & Initialization
- **File**: `frontend/src/scene/selection_manager.js`
- **Init**: `initSelectionManager(canvas, camera, designRenderer, opts)` — called at main.js ~line 175
- **opts callbacks**: `onNick`, `onLoopSkip`, `onOverhangArrow`, `getUnfoldView`, `getOverhangLocations`, `getLoopSkipHighlight`, `controls`, `getHoverEntry`

## Store Keys
| Key | Type | Semantics |
|-----|------|-----------|
| `selectedObject` | `{type, id, data} \| null` | Single selected object; type = `'nucleotide' \| 'helix' \| 'strand'` |
| `multiSelectedStrandIds` | `string[]` | Ctrl+drag lasso — strand pool (white highlight) |
| `multiSelectedDomainIds` | `{strandId, domainIndex}[]` | Domain lasso when `selectableTypes.domains=true` |
| `toolFilters` | `{bluntEnds, overhangLocations, extensionLocations}` | Overlay **visibility only** — does NOT gate selection |
| `selectableTypes` | `{scaffold, staples, strands, domains, ends, loops, skips, extensions}` | Gates lasso and click capture |

Note: `_ctrlBeads` (ctrl-clicked endpoints) is **module-level in selection_manager.js**, NOT in the store.

## Key Functions
```
pointerdown → raycaster.setFromCamera(ndc, camera)
           → intersects backbone/cone instanced meshes
           → click count: 1st = strand, 2nd = domain/nucleotide, 3rd = bead
           → store.setState({ selectedObject })
right-click → context menu (color picker / nick / loop-skip / isolate)
Ctrl+drag  → lasso rectangle → captures the active level's element type (strands/domains/
              ends/xover/cluster). Overhang filter active → captures OVERHANGS ONLY
              (precedence over the level), via `lassoCaptureType({overhangFilter})` (2026-06-07).
              At cluster level it is ADDITIVE (promotes a prior plain-click cluster first)
              and fills `multiSelectedClusterIds` as well as the member strands; at cylinder
              LOD it resolves clusters from `getCylinderDomainData()`, not beads (2026-07-09).
Ctrl+click (no drag) → UNIFIED multi-select toggle (2026-06-07): add the clicked element
              if absent, remove if present — at the ACTIVE level (snap-to-nearest, same
              radius as hover). strand/default→strand, domain→domain, end→ctrl-bead,
              xover→crossover arc, overhang filter→overhang. `_toggleAtLevel(e)` dispatches
              to `_toggle{Strand,Domain,Overhang,Crossover,EndBead,Cluster}`.
              ADDITIVE-FROM-PLAIN (2026-07-08): `_toggleAtLevel` first calls
              `_promoteSelectionToMulti()`, which folds a prior PLAIN-click single
              selection (`selectedObject`) into the matching multi-pool before toggling
              the new element — so "plain-click A, Ctrl-click B" ends with BOTH selected,
              not just B (single-selection and the multi pools are separate stores).
              Covers cluster→multiSelectedClusterIds(+member strands), end→_ctrlBeads,
              strand/default→_multiStrandIds, domain→_multiDomainIds,
              xover→_multiCrossoverArcs; no-op once already multi-selecting.
              CLUSTER (2026-07-09): presence is decided by the CLUSTER-id pool, never by
              "are all its strands selected" (two clusters can share a bridging staple) —
              pure rule `toggleClusterSelection()` in `selection_level.js`. The sidebar
              "Movable Clusters" rows Ctrl/Cmd/Shift+click into the SAME pool via the
              exported `selectionManager.toggleCluster(id)`; a plain row click stays a
              single selection (and still auto-opens Move/Rotate), an additive one never
              opens the gizmo — the gizmo drives exactly one cluster.
Shift+click → ALIAS of Ctrl+click (same `_toggleAtLevel`). Shift+drag is NOT a lasso (no-op).
Alt+click  → _ctrlBeads toggle (measurement mode) + capped-2 overhang toggle for the
              Overhangs Manager     [measurement moved from Ctrl 2026-05-17]
```

Module-level state for the new modifier paths: `_altDownPos` (Alt deferred-click position), `_shiftDownPos` (Shift deferred-click position). Both clear on lasso-finalize or normal click.

## NDC Rule
All raycaster NDC coords use `canvas.getBoundingClientRect()`. **Never** use `window.innerWidth/Height`.

## Cross-Feature Interactions
- `store.deformToolActive = true` → selection manager disabled (main.js blocks canvas events)
- `store.selectableTypes.ends = true` → selected ends go to `_ctrlBeads` (gold, 1.6× scale), not `selectedObject`. (As of 2026-05-17 the manual measurement-bead pick is **Alt-click**, not Ctrl-click.)
- `store.unfoldActive` → unfoldView coordinates helix positions; raycaster still works (meshes translated)
- `_effectiveColors()` in design_renderer.js merges `store.strandColors` + `store.strandGroups` (group wins)

## Invariants
1. `toolFilters` = overlay visibility only. Changing it does NOT affect click/lasso behavior.
2. Capture module-level state into `const` **BEFORE** calling any cleanup function that nulls it.
3. Context menu state capture pattern (see `RUNBOOK_SELECTION.md`).
4. `selectableTypes.scaffold / staples` are global gates — affect strands, ends, AND arcs.

## Diagnostics → [.claude/runbooks/RUNBOOK_SELECTION.md](../runbooks/RUNBOOK_SELECTION.md)

## Files to Read
- `frontend/src/scene/selection_manager.js` — all context menu handlers, raycaster logic
- `frontend/src/main.js` — `store.deformToolActive` gate, `_ctrlBeads` check, Ctrl key tracking

## Related
- `MAP_SELECTION.md` — full selection architecture

