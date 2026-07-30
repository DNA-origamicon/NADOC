# unfold — diagnostics runbook

Loaded on demand from the `unfold` rule's Diagnostics pointer. Symptom → diagnosis; not auto-loaded.
Architecture, store keys, fan-out table and invariants live in [`.claude/rules/unfold.md`](../rules/unfold.md).

*Rewritten 2026-07-30 (plan-audit pass). The previous version's four "First-Check Invariants"
were one-right-three-wrong; see the Corrections footer.*

## First question, always

**Is the unfold view even allowed to be active right now?** All the entry policy is in
`main.js:2541 _toggleUnfold()`, not in `unfold_view.js`. Five gates refuse entry (deform tool
active, atomistic on, deformations/cluster transforms visually active, no design, expanded
spacing) and three of them are **silent or toast-only**. Read that function before debugging the
view itself.

## Symptom index

| Symptom | Go to |
|---|---|
| [U] does nothing at all | §1 |
| Some objects (labels, sequences, loop-skip marks, overhangs, extensions) stay at 3D positions | §2 |
| Positions correct on first unfold, wrong after undo/redo or an edit | §3 |
| Helices stacked in the wrong order, or a new helix lands at the bottom | §4 |
| Arcs vanish when you zoom in | §5 |
| Design looks bent/skewed while unfolded | §6 |
| Design snaps back to 3D unexpectedly | §7 |
| Minimap missing, or stuck on screen after leaving unfold | §8 |
| Cadnano (K) mode breaks when entering/leaving unfold | §9 |
| Helices spread apart in 3D but atoms/labels don't follow | §10 |

---

## §1 — [U] does nothing

Almost always a gate in `_toggleUnfold` (`main.js:2541`), not a broken view:

1. `main.js:2544` — `if (isDeformActive()) return`. **Silent, no toast.** The deform *tool*
   (gizmo), not the deform view.
2. `main.js:2547` — atomistic mode on → toast "exit atomistic first".
3. `main.js:2571-2586` — design has `deformations` or a non-identity `cluster_transforms` entry
   **and** `deformVisuActive` → toast "press D to suppress them, then unfold". There is no
   auto-snap; the user must press D.
4. No design or `helices.length === 0` → silent return.

If none of those fire, check the binding chain: `ui/keyboard_shortcuts.js:260-264` → injected
`toggleUnfold` dep (`main.js:4510`) → `_toggleUnfold`. `keyboard_shortcuts.js` does **not** import
`unfold_view.js`, so a broken import there presents as a dead key.

## §2 — A subsystem stays at 3D positions

The `applyUnfoldOffsets(offsets, t)` fan-out has **5 callees and 4 notify sites**. Both counts
matter.

1. Does the subsystem implement `applyUnfoldOffsets`? The six implementers are
   `design_renderer.js:1256`, `domain_ends.js:704`, `loop_skip_highlight.js:260`,
   `overhang_locations.js:355`, `sequence_overlay.js:375`, `atomistic_renderer.js:452`.
2. Is it wired into **all four** notify sites in `unfold_view.js`? `_animate` (`:883-893`),
   `deactivate` (`:941-949`), the geometry/design subscriber (`:997-1002`), `reapplyIfActive`
   (`:1277-1284`). A callee wired into 3 of 4 works on first unfold and fails on the fourth path.
3. **Extensions (5′/3′ tails) are a separate call**: `applyUnfoldOffsetsExtensions(extArcMap, t)`,
   with **five** sites — the four above plus `applyClusterExtArcUpdate` (`:1471`, cluster drags).
4. If the subsystem is new, it must also be added to `expanded_spacing.js:182-194`, which is the
   parallel fan-out for 3D spread.

## §3 — Correct on first unfold, wrong after undo/redo or an edit

This is the **ordering law**. `unfoldView` subscribes at `main.js:1535`, `domainEnds` at
`main.js:2988`; the store fires in registration order, so unfold applies offsets to sprites that
`domain_ends._rebuild()` is about to replace.

1. Check `domain_ends.js:593` still ends the rebuild with
   `if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()`.
2. If the broken subsystem is a *different* module that registered before a renderer, it needs the
   same call. `reapplyIfActive` (`unfold_view.js:1272`) no-ops when unfold is inactive, so it is
   safe to call unconditionally.
3. Do **not** "fix" this by reordering the inits — `domain_ends` initializes 1,400 lines later for
   unrelated dependency reasons.

## §4 — Wrong stacking order

`unfold_view.js` does not decide the order. It reads `store.unfoldHelixOrder` (`:826,830`) and
falls back to `allIds`, appending any helix missing from the stored order at the **end** (`:833`)
— that is why a newly added helix drops to the bottom.

The writers are the **slice-plane code in `main.js`**: `:2729` (sets the full order),
`:2736`/`:2785` (append new helices), `:3540` (reset to `null` on new design). Debug there.

`cadnano_view.js:97/164/264` re-derives the same `unfoldHelixOrder ?? allIds` expression
independently — if cadnano and unfold disagree about order, one of those four sites drifted.

## §5 — Arcs disappear on zoom

`unfold_view.js:190` must set `frustumCulled = false` on the arc object. Note the object is
`THREE.LineSegments` (`:189`), **not** `THREE.Line` — the file's own header comment (`:9`) is
wrong, so don't search for `new THREE.Line(`.

## §6 — Design looks bent or skewed while unfolded

Unfold assumes helices sit at pure topology positions. Two causes:

1. A deformation slipped past gate 3 of `_toggleUnfold` (e.g. it was applied *while* unfolded).
   Check `currentDesign.deformations` and `deformVisuActive`.
2. The deform lerp reset helix positions and unfold wasn't re-applied. `deform_view.js:308`
   calls `reapplyIfActive()` inside the async `getStraightGeometry()` fallback subscriber — that
   is the only place it does so, **not** on every `_applyLerp`. A new deform code path that moves
   helices must call it too.

Related: `unfold_view.js:1263 applyDeformLerp(straightPosMap, deformT)` (2 args) is member 3 of
the 6-subsystem deform fan-out at `deform_view.js:154`.

## §7 — Snaps back to 3D unexpectedly

1. Who cleared `unfoldActive`? Legitimate writers: `unfold_view.js:915/924/1146/1162` and
   `main.js:3540` (new design load / File>New). Anything else is the bug.
2. `unfold_view.js:1024` is the subscriber that reacts to `unfoldActive` being cleared *externally*
   — it calls `revertToGeometry(_straightPosMap, _straightAxesMap)`.
3. Turning unfold off deliberately **re-activates the deform view** (`main.js:2599-2602`). If the
   design looks bent right after exiting unfold, that is this, not a bug in unfold.

## §8 — Minimap missing or stuck

- It is drawn **bottom-left** (`cross_section_minimap.js:58-66`, `bottom:8px; left:8px`). The
  file's own header comment says "lower-right" and is wrong — don't hunt for a positioning bug
  that isn't there.
- Parent element is `#canvas-area` (`main.js:2530`), not `#viewport-container`.
- Its subscriber (`:616-649`) shows on `unfoldActive`, but on `unfoldActive → false` it **only
  hides when `_sliceOffsetNm === null`**. A minimap that won't go away means a slice plane is
  still set — see `crossSectionMinimap.clearSlice()` (`main.js:2556-2560`).
- It writes **no** store keys; it is purely a reader.

## §9 — Cadnano interaction

Cadnano *builds on* unfold: `cadnano_view.js:412-415` records `_wasUnfoldActive` and awaits
`unfoldView.activateWithDuration(ANIM_STAGE1_MS)`; `deactivate()` (`:494-509`) calls `setSpacing`
then `unfoldView?.deactivate()` **unless** `keepUnfold` or `_wasUnfoldActive`. Pressing [U] while
cadnano is active exits cadnano and stays unfolded (`main.js:2553-2564`).

Position ownership while cadnano is on belongs to cadnano — that is why `domain_ends.js:593`
guards its `reapplyIfActive()` with `!cadnanoActive`. Deeper cadnano diagnosis:
[`RUNBOOK_CADNANO.md`](RUNBOOK_CADNANO.md).

## §10 — Expanded spacing (3D spread) drops a subsystem

`expanded_spacing.js` is a second implementation of the same contract, with a **longer** callee
list than unfold: `:182-194` notifies designRenderer (+ extensions), bluntEnds, loopSkipHighlight,
overhangLocations, sequenceOverlay **and `atomisticRenderer` (`:194`)**. `unfold_view.js` never
calls the atomistic renderer — deliberately, since atomistic mode blocks unfold entirely. A
subsystem added to one fan-out and not the other fails in exactly one of the two modes.

`expandedSpacing.forceOff()` runs before unfold activates (`main.js:2578`) — the two are exclusive.

---

## Corrections to the previous version of this runbook

Kept for anyone who remembers the old text:

- **"Call `deformView.snapOff()` before unfold activates"** — `snapOff` has **0 callers
  repo-wide**. Unfold *blocks* on active deformations and asks the user to press D (§1 gate 3).
- **`blunt_ends.js` / `bluntEnds._rebuildSprites()`** — the file is `scene/domain_ends.js`; only a
  local variable in `main.js` still says `bluntEnds`.
- **`_buildArcMap`** — never existed. The real builders are `_buildXbArcMap` (`:435`) and
  `_buildExtArcMap` (`:510`).
- **"`applyUnfoldOffsetsExtensions` must be called at all 3 unfold update sites"** — there are
  **5** (§2).
- **"Minimap DOM element must be inside `#viewport-container`"** — it is `#canvas-area`, and the
  minimap is bottom-left, not top-right.
- **"Arc `THREE.Line`"** — `THREE.LineSegments`.
- **Init anchors `~859` / `~1753`** — real: `main.js:1535` / `main.js:2988`. The subscription-order
  hazard itself is real and the fix is live.
