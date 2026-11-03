# Today's constraint (why this is new capability) — supporting detail

[Topic head](../../project_mixed_representation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Today's constraint (why this is new capability)

Single-structure rep is **strictly global** — whole design is cylinders OR beads OR hull, one
at a time. `_setRepresentation` ([main.js] ~14127) flips everything; geometry is one
monolithic `_helixCtrl` whose `setDetailLevel` ([design_renderer.js] ~648) hits all of it.
No per-strand/cluster/region rep exists in the single-design view. (The *assembly* renderer
has per-part rep + per-instance visibility texture + shader discard — prior art, but
whole-part granularity only.) Hull is the one already-subdivided seam: one mesh per cluster
([joint_renderer.js] ~2892), toggled by a single global boolean `setHullRepr`.
*(Line numbers approximate — verify at implementation time.)*

## KEYSTONE (the decision that makes B free)

Do **not** model representation as a property of a helix/strand. A spatial volume (B) cuts
through a helix, so per-helix rep can't express "nucs 1–20 detailed, 21–40 cylinders."

Model it as: **resolve representation per nucleotide, then draw as contiguous runs.**

A and B differ ONLY in how a layer's nucleotide set is produced:
- A: "nucs of selected strands / cluster" → whole-helix runs.
- B: "nucs whose 3D position ∈ volume" → possibly mid-helix runs.
Everything downstream (resolve map → segment into runs → build per-segment geometry) is
identical. B = one new selector branch + a gizmo. B's first version snaps the volume boundary
to the nearest bp (nuc in/out by center) and reuses A's pipeline wholesale; smooth
per-fragment edge clipping is an optional later refinement.

## Architecture

### 1. Data model (saved display state, never mutates topology)
Ordered list of overrides on the Design: `[{ selector, rep }, ...]`.
- `selector` = tagged union:
  - `{type:'strand', ids:[...]}`
  - `{type:'cluster', id}`
  - (future) `{type:'volume', shape, transform, halfExtents}`
- `rep` ∈ `'cylinders' | 'full'`.
- Store the **selector**, not a baked nuc list → override follows structure across edits; drop
  selector entries whose referenced strand/cluster no longer exists.
- Lives with global-rep state in [store.js] (~265 area). Round-trips in `.nadoc`.
- Three-Layer Law: this is display metadata derived over topology. Never written back.
  A's resolution reads only topology ids; B's reads geometric nuc positions (read-only).

### 2. Resolution (pure function, the reusable core)
`resolveRepMap(design, overrides) -> Map<nucId, rep>`:
- init every nuc to global rep
- apply overrides in order, later wins
- strand selector → nucs of those strands; cluster selector → nucs of that cluster

### 3. Segmentation
Per helix, walk nucs in index order, cut into contiguous same-rep runs →
`[{helixId, startIdx, endIdx, rep}, ...]`. For A these are whole-helix runs; B yields
mid-helix runs. **This is the B seam.**

### 4. Rendering
Generalize the monolithic `_helixCtrl` build to build **per run-segment**, each in its own
rep (cylinder tube over the run, or beads+slabs over the run). Disjoint nuc sets → coexist in
one scene, no overlap/z-fight. Reuse the per-cluster-hull coexistence pattern
([joint_renderer.js] ~2892), generalized "cluster" → "segment".
- Junction cosmetic: where a cylinder run meets a bead run in the same helix, decide how the
  cylinder caps at the last bp before detail begins. Eyeball on a real design.

### 5. UI
- Select strand(s) / cluster → context-menu or sidebar: "Set representation → Cylinders /
  Full Detail"; "Clear" reverts to global.
- Small overrides-list panel (add/remove) for the figure-making workflow.
- Cluster multi-select picker already exists (deformation cluster work) — reuse.

## Required touch point — photo mode
Photo mode is the export path for these figures and **currently forces one global export rep
onto everything** ([main.js] ~12886, `_applyRepAndAwaitRebuild` over all). It MUST honor
per-segment overrides instead of flattening them — otherwise the mixed view exports as a
single rep. Non-optional in A.

## Suggested implementation order
1. Data model + store state + `.nadoc` round-trip (+ edit-survival: drop dead selectors).
2. `resolveRepMap` + segmentation — pure, unit-testable, no rendering.
3. Per-segment build in design_renderer/helix_renderer (the real work). Verify two reps
   coexist on a loaded design.
4. Selection → set/clear override UI + overrides panel.
5. Photo-mode: honor overrides in export.
6. (Later, Path B) volume gizmo + `{type:'volume'}` selector branch; optional edge clipping.

## Test points
- Unit: `resolveRepMap` precedence (later override wins), strand vs cluster resolution,
  contiguous-run segmentation including a helix that spans two reps.
- Round-trip: save/load a design with overrides; delete a referenced strand → override drops.
- Visual: load a representative `.nadoc`, set a cluster to full while base is cylinders;
  confirm coexistence + junction look. Then export via photo mode and confirm the mix survives.

## Open questions / gotchas
- Junction appearance (cylinder cap → first detailed bp).
- Persistence schema version bump for `.nadoc` if needed.
- Confirm cylinders is a real detail level in helix_renderer (LOD 2) for the single-design path.
- Selection plumbing: strand selection exists; confirm cluster-selection → override wiring.
- Whether base rep being `hull` interacts oddly with `full`/`cylinder` overrides (A palette is
  cylinders+full, but base could still be hull globally) — decide if hull base is allowed.

## Related
- [[project_photo_mode]] — export path that must honor overrides
- [[project_hull_prism]] — per-cluster mesh coexistence pattern + LOD reps
- [[project_path_to_thousands]] — assembly renderer's per-instance vis-texture + shader-discard
  (prior art for per-piece rendering; whole-part granularity)

## Per-region AXIS LINES + CROSSOVER ARCS follow the rep (shipped 2026-06-02)

Two bugs after global cylinder LOD + a per-region `full` override (repro: `workspace/Ultimate Polymer Hinge2.nadoc`):

1. **Axis lines showed for ALL helices** instead of only full/beads-rendered columns.
   Root cause: axis-mesh visibility is written in THREE places, only one of which was rep-aware:
   `_applyShaftModeVisibility` (mode-only), `setDetailLevel`'s coarse-hide, AND
   `applyDeformLerp` (single curved shaft, line ~1883 — set `.visible=!useStraight` directly).
   On a deformed design the deform lerp/`setAxisShaftMode` re-asserts shaft visibility and
   was overriding the LOD hide. Fix in [helix_renderer.js]: module-level `_axisColRep`/`_axisSegOn`
   gate (column rep === 'full' → axis shown), applied in `_applyShaftModeVisibility` AND
   `applyDeformLerp`. Added `bp_lo`/`bp_hi` to each `axisArrows` entry for the shaft gate.
   Active-override branch re-calls `_applyShaftModeVisibility`. Axis meshes now named `'axisLine'`.

2. **Crossovers (arc lines) didn't show for a strand set to full.** Arc lines live in
   unfold_view `_arcMeta` (merged scaffold/staple LineSegments, shown in 3D too) and were
   globally hidden at LOD≥2 via `setArcsVisible(lvl<2)`. Fix: added `_arcRepHidden(e)` to
   `_reapplyArcHidden` — an arc hides when BOTH endpoints are non-`full` columns
   (`designRenderer.columnRepAt`). So global cylinders → all arcs collapse; a full region →
   its arcs reappear. Decoupled the group from LOD: 4 `setArcsVisible(... && _lastDetailLevel<2)`
   callers in [main.js] now pass only design-visibility; LOD/override changes call the new
   `unfoldView.refreshArcVisibility()` (re-runs `_reapplyArcHidden` + `_updateArcPositions`).
   The override-save rebuild re-gates automatically via the existing rebuild subscription.

**Extra-base beads NOT yet per-region**: `_applyXoverExtrasLod` still hides ALL extra-base
beads/slabs (the inserted-base markers) at LOD≥2 — restoring collapsed instances on LOD
toggle is fiddly and fights the other xover-visibility passes. Only crossovers WITH inserted
bases are affected; standard crossovers (the arc) are fully covered. Follow-up if needed.

Verified via Playwright on the hinge: global cylinders → 0 axis lines / 0 arcs; pin one
staple to full → only that region's axis + arcs reappear. NOT visually confirmed in the app.
Debug handles added: `__NADOC_DBG__.designRenderer`, `__NADOC_DBG__.unfoldView` (getter).

---
