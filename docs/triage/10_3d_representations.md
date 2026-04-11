# Feature 10: 3D Representations
**Phase**: A (Foundation — must pass before all other features)

---

## Feature Description

All 3D rendering modes that display designs in the viewport:

| Mode | Files | Store Key |
|------|-------|-----------|
| Backbone beads (default) | `helix_renderer.js` | `currentGeometry` |
| Cylinder LOD | `helix_renderer.js` | (LOD level) |
| Atomistic (VdW / ball-stick) | `atomistic_renderer.js` | `atomisticMode` |
| Surface (VdW / SES) | `surface_renderer.js` | `surfaceMode` |
| Crossover connections | `crossover_connections.js` | `currentDesign.crossovers` |
| Glow / selection | `glow_layer.js` | `selectedObject` |
| Sequence overlay | `sequence_overlay.js` | `showSequences` |
| Physics overlay | `physics/displayState.js` | `physicsMode` |

**Critical new file**: `crossover_connections.js` — `buildCrossoverConnections(design, geometry)` returns a `THREE.LineSegments` mesh of white lines between crossover backbone positions. Must be added to the scene and rebuilt on every design/geometry change.

**Rebuild entry point**: `design_renderer.js::rebuild(design, geometry)` — this function calls `helix_renderer.buildHelixObjects()` and must also call `buildCrossoverConnections()`.

---

## Pre-Condition State (what's known broken)

- `crossover_connections.js` exists and is correct in isolation, but integration into `design_renderer.js` rebuild cycle is unverified
- The old `crossover_locations.js` (interactive valid-site overlay) is **deleted** — no replacement exists
- No e2e tests verify crossover lines appear after a design load or import
- LOD mode switching behavior with crossover lines is undefined
- Atomistic and surface modes have not been tested with the new `design.crossovers` model

---

## Clarifying Questions

Ask the user before implementing any fixes:

1. In which LOD modes should crossover connections be visible?
   - (a) All LOD modes (beads + cylinders + sticks)
   - (b) Beads only
   - (c) User-toggleable independently of LOD

2. Should scaffold crossovers render differently from staple crossovers?
   - (a) Scaffold = colored to match scaffold (blue by default), staple = white
   - (b) All crossovers white (current `crossover_connections.js` behavior)
   - (c) Crossover color matches the strand color of half_a

3. In atomistic mode, are crossover phosphate–phosphate bonds represented as explicit bonds in the atomistic bond graph, or are they visually covered by `crossover_connections.js` lines only?

4. Should the new 3D valid-site overlay (replacing `crossover_locations.js`) use:
   - (a) Semi-transparent spheres at each valid bp position
   - (b) Colored short line segments showing the potential crossover
   - (c) Exactly what `crossover_locations.js` did (need to check git history for reference)

---

## Experiment Protocol

### Experiment 10.1 — Crossover connections appear on design load

**Hypothesis**: After loading a design with `design.crossovers.length > 0`, the scene contains a `crossoverConnections` mesh with the correct number of line segments.

**Test Steps**:
1. Start dev server (`just dev`)
2. Load `Examples/3NN_ground truth.nadoc`
3. Check scene object and crossover count

**Data Collection**:
```javascript
// In browser console or Playwright
const xoCount = window._nadoc?.store?.getState()?.currentDesign?.crossovers?.length
const mesh = window._nadoc?.scene?.getObjectByName('crossoverConnections')
console.log('crossovers:', xoCount, 'mesh vertices:', mesh?.geometry?.attributes?.position?.count)
// Expected: mesh vertices == xoCount * 2 (two endpoints per line)
```

**Pass Criteria**: `mesh !== null` AND `mesh.geometry.attributes.position.count === xoCount * 2`

**Fail → Iteration 10.1a**: If mesh is null, `design_renderer.js::rebuild()` is not calling `buildCrossoverConnections()`. Find the rebuild call site and add it.

**Fail → Iteration 10.1b**: If vertex count is wrong, the geometry lookup in `crossover_connections.js` is failing for some crossovers. Check for `[XOVER 3D] unresolved crossover` warnings in console.

---

### Experiment 10.2 — Crossover lines survive geometry rebuild

**Hypothesis**: After a topology mutation (e.g., adding a nick), the crossover mesh is disposed and replaced — not duplicated or left stale.

**Test Steps**:
1. Load `3NN_ground truth.nadoc`, confirm mesh count = N
2. Add a nick via API: `POST /design/nick`
3. Confirm mesh count still = N (or N-delta if the nick removes a crossover)
4. Check no duplicate `crossoverConnections` objects in scene

**Data Collection**:
```javascript
const allXoverMeshes = []
window._nadoc?.scene?.traverse(obj => {
  if (obj.name === 'crossoverConnections') allXoverMeshes.push(obj)
})
console.log('mesh count:', allXoverMeshes.length) // should be exactly 1
```

**Pass Criteria**: Exactly 1 crossoverConnections mesh in scene after mutation.

**Fail → Iteration 10.2a**: If count > 1, old mesh is not disposed before rebuild. Add `scene.remove(oldMesh); oldMesh.geometry.dispose()` in the rebuild path.

---

### Experiment 10.3 — LOD mode switching preserves crossover lines

**Hypothesis**: Switching between Full/Cylinder/Sticks LOD modes does not remove or hide the crossover connections mesh.

**Test Steps**:
1. Load design, confirm crossover mesh present
2. Switch to Cylinders LOD (View menu)
3. Confirm crossover mesh still present
4. Switch to Sticks
5. Confirm crossover mesh still present

**Data Collection**: Same as 10.1 mesh check after each LOD switch.

**Pass Criteria**: Mesh present and vertex count unchanged after each LOD switch.

**Fail → Iteration 10.3a**: If crossover mesh disappears on LOD switch, the LOD rebuild path disposes all scene children including crossovers. Fix: track crossover mesh separately (not as a child of the helix group) and re-add after LOD rebuild.

---

### Experiment 10.4 — Atomistic mode does not crash with crossovers

**Hypothesis**: Switching to VdW atomistic mode on a design with `design.crossovers` renders without errors and shows the atomistic representation.

**Test Steps**:
1. Load `multi_domain_test.nadoc` (small design, faster atomistic build)
2. Open Representations menu → enable Atomistic VdW
3. Check console for errors
4. Screenshot

**Data Collection**: Console error count, screenshot of atomistic render.

**Pass Criteria**: No console errors, atomistic spheres visible.

**Fail → Iteration 10.4a**: If crash, check `atomistic_renderer.js` for any code that traverses strand domains to find crossovers (old model). Replace with `design.crossovers` lookup.

---

### Experiment 10.5 — Surface mode does not crash with crossovers

**Hypothesis**: Same as 10.4 but for surface (VdW/SES) mode.

**Test Steps**: Same as 10.4 but enable Surface mode instead.

**Pass Criteria**: No console errors, surface rendered.

---

### Experiment 10.6 — Selection glow at crossover nucleotide

**Hypothesis**: Clicking a nucleotide that is part of a crossover (i.e., matches a `half_a` or `half_b` position) triggers the glow layer correctly. The glow appears at the bead position, not at the origin or a stale 3D position when in cadnano/unfold mode.

**Test Steps**:
1. Load design with crossovers in 3D mode
2. Click a bead that is a crossover endpoint (identify from `design.crossovers`)
3. Confirm glow appears at that bead's position

**Data Collection**: Screenshot of glow position vs. bead position.

**Pass Criteria**: Glow centroid within 0.5 nm of bead position (measureable via `glow_layer` instance debug).

---

### Experiment 10.7 — Valid-site overlay baseline (discovery)

**Hypothesis**: Need to establish what `crossover_locations.js` did before it was deleted by examining git history, then determine what to rebuild.

**Test Steps**:
1. `git log --oneline -- frontend/src/scene/crossover_locations.js` — find the deletion commit
2. `git show <commit>^:frontend/src/scene/crossover_locations.js` — read the deleted file
3. Document: what data it consumed, what it rendered, how it handled user clicks

**Data Collection**: Copy of deleted file's content, note its import/export surface.

**Pass Criteria**: Written summary of what needs to be rebuilt in [06_prebreak_autocrossover.md](06_prebreak_autocrossover.md).

**Note**: This experiment is discovery only — the rebuild is tracked in feature 06.

---

## Performance Notes

*Do not implement these until all experiments above pass.*

- `buildCrossoverConnections()` allocates a new `Float32Array` and `BufferGeometry` every rebuild. For ≤500 crossovers this is fast (~1ms). For multi-origami designs with >5000 crossovers, switch to `bufferGeometry.attributes.position.array` in-place update with `needsUpdate = true` — avoids GC pressure.
- If crossover count never changes between frames (only positions change), use `updateRange` to upload only changed segments. This is a Phase 3+ optimization.
- Crossover mesh is a `THREE.LineSegments` — not instanced. For very large designs, consider `THREE.LineSegments2` (fat lines) which supports per-segment color but has higher draw cost.

---

## Refactor Plan

*Execute only after all 10.x experiments pass.*

1. **Extract crossover mesh management** out of `design_renderer.js` into a dedicated `CrossoverRenderer` module mirroring `crossover_connections.js` — gives a clean `rebuild(design, geometry)` / `dispose()` interface.
2. **Color by strand type**: pass `design.strands` into `buildCrossoverConnections`; color scaffold crossovers to match scaffold strand color, staple crossovers to match staple color. Requires adding a per-segment color attribute (LineSegments supports per-vertex color via `vertexColors: true`).
3. **LOD visibility**: add a `setVisible(lod)` method to CrossoverRenderer; called by design_renderer on LOD change. This replaces the current "rebuild everything on LOD change" path.
4. **Performance baseline**: record before/after for the 26HB fixture.
