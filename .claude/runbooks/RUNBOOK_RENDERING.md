# rendering — diagnostics runbook

Loaded on demand from the `rendering` rule's Diagnostics pointer. Symptom → diagnosis; not
auto-loaded. *Rewritten 2026-07-30 against live code — the previous version's two "First-Check
Invariants" were both wrong (see Corrections at the bottom).*

## Symptom index

| Symptom | Go to |
|---|---|
| Scene blank / stale after a mutation | §1 |
| Geometry updated in the store but the scene didn't change | §2 |
| Beads flash to 3D for one frame in cadnano or unfold mode | §3 |
| Strand or group color not updating | §4 |
| `instanceColor` is null / throws on `needsUpdate` | §5 |
| A representation override (mixed rep) does nothing on some helices | §6 |
| Simulation positions (oxDNA/mrDNA/CanDo/SNUPI/LAMMPS/MD) don't move the model, or don't revert | §7 |
| RMSF / scalar heat-map colors partly missing | §8 |
| Deform preview ghost stuck, or scene stuck translucent | §9 |
| Assembly view broke after a change to `helix_renderer.js` | §10 |
| Glow lags behind beads during animation | §11 |

---

## §1 — Scene blank or stale after a mutation

**Check the revision watermark first.** `api/client.js:51-57` `_isStaleDesignResponse(json)` is
consulted at `:362` (and again on the fast paths `:794`, `:821`) against `_lastAppliedRevision`
(`:46`). A response whose revision is behind the last applied one is **dropped silently** — no
store write, no rebuild, no error. If the backend was restarted or a doc switched, call the reset
(`resetRevision*` in the same file) or reload; otherwise every response looks ignored.

Then, in order:
1. `store.currentGeometry` null? → geometry was never fetched.
2. `store.currentDesign` null?
3. `store.lastError` — did the call fail?
4. Design non-null, geometry null → the route didn't use `_design_response_with_geometry`
   (`backend/api/crud.py:339`); the client then falls back to a second `getGeometry()` round-trip
   (`client.js:547`) which may have failed on its own.

## §2 — Store updated, scene unchanged

`design_renderer` subscribes **once** (`design_renderer.js:629`) and early-returns at `:706` unless
`geoChanged || designChanged || loopChanged` (identity comparison, not deep-equal). Three ways to
land here:

- **The identity didn't change.** Mutating `currentGeometry` in place never triggers a rebuild.
- **The Domain Designer modal is open** — `domainDesigner.modalActive` defers the rebuild
  (`:625-654`). Colors still repaint; structure doesn't.
- **The partial-patch fast path ran instead.** If `lastPartialChangedHelixIds` is set,
  `_tryPatchInPlace` (`:583`, called `:732`) touches only those helices. A helix missing from that
  list stays stale. It also early-outs entirely while a deform ghost is up
  (`if (!_helixCtrl || _ghostOpacity !== null) return false`).

Turn on `window._cnDebug = true` and watch for the `[CN f…] design_renderer._rebuild() geo:… des:…
loop:…` line (`design_renderer.js:751`) — it tells you which of the three flags fired, or that
none did.

## §3 — Beads flash to 3D for one frame in cadnano/unfold

**Mechanism (still true):** subscribers fire in registration order. Any subscriber registered
*after* the cadnano/unfold reapply that calls `revertToGeometry()` wins, and beads snap to their
3D positions until the next reapply.

**Guard pattern** any such caller must use:

```js
const { cadnanoActive, unfoldActive } = storeRef.getState()
if (!cadnanoActive && !unfoldActive) { _helixCtrl?.revertToGeometry() }
```

**Who can actually reach `revertToGeometry` today** (`helix_renderer.js:1934`) — the list is short,
so start here: `unfold_view.js:925`, `:1024`, and `applyFemPositions(null)` internally
(`helix_renderer.js:3317`). The historical culprit — a late subscriber calling
`designRenderer.clearFemOverlay()` — **is gone, and `clearFemOverlay` itself now has zero callers**
(`design_renderer.js:1241`); the guard inside it is dead code. If you see this flash now, the
caller is almost certainly a display module toggling off via `applyFemPositions(null)` (see §7).

**Diagnosing:** `window._cnDebug = true`, then look for `[INTERCEPT f…]` — **an intercept already
ships in-tree at `cadnano_view.js:642`**, you don't need to hand-install one. `window._cnEntries()`
(`cadnano_view.js:593`) returns the live backbone entries. If you do install a manual
`Object.defineProperty` trap on `entry.pos.x`, install it **after** `_rebuild()` creates new
entries — an entry captured before the rebuild is a stale object and never receives the bad write.

If the flash comes from a *second* `_rebuild()` rather than a revert, the `[CN f…]` lines in §2
will show two rebuilds for one action — usually a late subscriber changing `loopStrandIds` (e.g.
`selectNucleotide` → subscriber).

## §4 — Strand or group color not updating

1. `store.strandColors[strandId]` set?
2. `store.strandGroups` — is the strand in a group? **Group color overwrites the per-strand
   override** (`_effectiveColors`, `design_renderer.js:151-157`). Note the real signature is
   `_effectiveColors(strandColors, strandGroups)` returning a whole map, not a per-strand lookup.
3. The palette fallback is applied *downstream* (`:695-696`, `palette.js::nucColor:230`), so a
   strand with no override and no group falls to `STAPLE_PALETTE`
   (`scene/helix_renderer/palette.js:28`).
4. A color change repaints **in place** and must not rebuild — the repaint block (`:688-704`) runs
   *before* the structural early-return at `:706`. If someone moves it below, group changes stop
   working entirely.
5. For a single entry, the low-level call is `setEntryColor(entry, hex)`
   (`design_renderer:808` → `helix_renderer:192`).

## §5 — `instanceColor` null

Three.js allocates `instanceColor` lazily on the first `setColorAt`. Always:

```js
if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
```

Live examples: `crossover_connections.js:374-378`, `design_renderer.js:191-193`,
`selection_manager.js:2666`, `atomistic_renderer.js:227`.

## §6 — A representation override does nothing on some helices

Expected: `_applyRepOverrides` (`helix_renderer.js:2493`) sets per-instance alpha via
`_installInstanceAlpha` (:238).

**Two known blind spots — check these before debugging the override resolution:**
- It never touches the curved/deformed paths: `_curvedCylGroup` (:1121), `_curvedOvhgGroup`
  (:1251), `iCurvedHelixCylinders`, `iCurvedOverhangCylinders`, `iCurvedOverhangFullCylinders`,
  `iLinkerBindingCylinders`. Those are driven only by `_reapplyDetailVisibility` (:2484), i.e.
  the global LOD.
- With impostors on, `_installInstanceAlpha` **skips `iSpheres`/`iFluoros`** (:2420-2424,
  :2471-2479) — impostor beads have no per-instance alpha at all, so both rep-override alpha and
  reference-ghosting are no-ops on them.

If the design is deformed or impostors are enabled, the override *is* resolving correctly and
simply has nothing to write to. Tracked as P1 in `memory/project_mixed_representation.md`.

Also confirm which knob you're actually turning: `setDetailLevel` takes an **integer**
(`CG_LOD = {full:0, beads:1, cylinders:2}`, `helix_renderer.js:64`), while the F1–F7 menu has
**7** representations (`ui/representation_switcher.js:36-44`) — `surface`/`vdw`/`ballstick` are
different renderers entirely and will ignore anything in this pipeline.

## §7 — Simulation positions don't apply, or don't revert

`applyFemPositions(updates, amp = 1.0)` (`design_renderer.js:1019` → `helix_renderer.js:3316`) is
the single display-position channel for **eight** modules: `mrdna_display`, `oxdna_display`,
`cando_display` (a real FEM solver — the "Fem" name is not purely historical), `snupi_display`,
`lammps_display`, `blade_display`, `md_panel`, `animation_player`. `main.js` is not one of them.

- **Nothing moves** → the update keys must match the geometry key format, and `amp` must be
  non-zero. Confirm the module is `_active` (each display guards its own restore).
- **Positions don't revert on toggle-off** → the off path is `applyFemPositions(null)` →
  `revertToGeometry()`. `clearFemOverlay()` is orphaned; calling it fixes nothing.
- **Something else's positions got clobbered** → an unconditional `stopAndRestore()` reverts beads
  this overlay never set. `lammps_display.js:136-150` documents the exact bug (a cluster-move
  preview snapped back) and the fix: guard on `_mode === null` / `!_active` before restoring. Check
  any new display module for that guard.
- **A deformation exists and the model came back straight** → see the correction on
  `reapplyLerp` at the bottom; there is no wired re-apply. Toggle the deform view off/on, and
  treat a real fix as a code change, not a runbook step.

## §8 — Scalar (RMSF / heat-map) colors partly missing

Key format is **`"helix:bp:dir:copy"`** (`helix_renderer.js:3458-3459`, read at :3468/:3474).
`oxdna_display.js` emits the shorter `"helix:bp:dir"` form **only when `copy === 0`** — so a design
with multi-copy nucleotides that colors only the copy-0 bases has a key-format mismatch, not a
data gap.

`applyScalarColors` saves prior colors in `_savedScalarColors` and `clearScalarColors` restores
them, with **no rebuild**. If colors persist after clearing, something rebuilt between apply and
clear and the saved colors were dropped.

Arc colors are fanned out separately: `_scalarArcUpdater` → `unfold_view.applyFemArcColors` (wired
`main.js:1539`). If beads recolor but crossover arcs don't, that wiring is the suspect. The
atomistic view has its own parallel path (`atomistic_renderer.applyScalarColors`).

## §9 — Deform ghost stuck / scene stuck translucent

State lives in three flags on `design_renderer`: `_captureNextAsFrozen` (:121), `_frozenRoot`
(:119), `_ghostOpacity` (:120).

- `beginDeformPreview` is called **once per session** from `deformation_editor.js:380`
  (`if (!_previewOriginalAxes)`), `endDeformPreview` from `_cancelPreview` (`:489`) — the universal
  teardown. If a new exit path was added that bypasses `_cancelPreview`, `_frozenRoot` is never
  disposed and both copies stay in the scene.
- While `_ghostOpacity !== null`, both `setToolOpacity` (:1491) and `_tryPatchInPlace` (:584)
  early-out. A scene that refuses to change opacity or to patch in place is telling you a ghost
  session is still open.
- Scene at 0.15 with no ghost = the tool is active but no preview has run (`:529-532`), expected.
- Ghost opacity 0.38 is `PREVIEW_GHOST_OPACITY` in **`deformation_editor.js:33`**, passed in as an
  argument.

## §10 — Assembly view broke after a `helix_renderer.js` change

`buildHelixObjects` has **7 callers**, 6 of them in the assembly stack:
`assembly_renderer.js:608,:1180`, `assembly_renderer_shared.js:1217,:3179,:3590`,
`assembly_linker_render.js:132`. That stack is ~10k LOC, has **no rule** and few tests, so a
signature or return-shape change fails there silently. Two specific contracts it relies on:
the 7-arg positional signature `(geometry, design, scene, customColors, loopStrandIds, helixAxes,
lod)`, and `setDetailLevel` returning `{ needsRebuild: boolean }`.

## §11 — Glow lags behind beads during animation

`refreshAllGlow()` (`design_renderer.js:955-962`) must be called each frame after positions are
mutated (`unfold_view.js:886`, `cadnano_view.js:363,587`, `expanded_spacing.js:197`).
**It refreshes 6 of the 7 layers — `_captureGlowLayer` is omitted**, so capture glow specifically
will lag. That looks like a bug; confirm intent before "fixing" either side.

At cylinder LOD the selection glow is not spheres at all — `_setSelectionGlow`
(`selection_manager.js:2626`) routes to `designRenderer.glowCylinderDomains` (:2642) instead of
`setGlowEntries` (:2641). Debugging the sphere layer while at LOD 2 finds nothing.

---

## Corrections to the pre-2026-07-30 version of this runbook

- **"Design + geometry always arrive in one `setState`"** — true only on the embedded-geometry
  path (`client.js:461` → single setState `:536`). The fallback writes the store then awaits
  `getGeometry()` (`:547`) — two writes; the `skipGeometry` path writes 2 keys at `:416`. And the
  first thing to check is the revision watermark, which the old version never mentioned.
- **"After any `revertToGeometry()`, call `deformView.reapplyLerp()`"** — `reapplyLerp`
  (`deform_view.js:378`, exported `:409`) has **zero callers anywhere in `frontend/`**. This
  invariant has never been enforced by code. The wired analogue for unfold is
  `getUnfoldView?.()?.reapplyIfActive()` (`deform_view.js:308`, `domain_ends.js:593`).
- **"Known culprit (fixed 2026-04-01): a late subscriber calling `clearFemOverlay()`"** — the
  subscriber is gone and `clearFemOverlay` has zero callers; its cadnano/unfold guard is dead code.
- The old manual `[INTERCEPT]` console snippet duplicated an intercept that already ships at
  `cadnano_view.js:642`.
