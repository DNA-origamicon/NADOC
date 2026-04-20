# Feature 01: Expanded Quick View
**Phase**: B (Core 2D/3D Views — requires Phase A foundation)

---

## Feature Description

The **expanded spacing** mode spreads helices apart laterally to reduce visual clutter in dense bundles. It is a view-only transformation — no topology changes.

**Key file**: `frontend/src/scene/expanded_spacing.js`
**Store key**: (check `expanded_spacing.js` for the store key name — likely `expandedSpacing` or `spacingFactor`)
**Trigger**: `E` key or View menu item

When expanded spacing is active, each helix is displaced from its lattice position by a scale factor applied to the XY cross-section. The 3D bead positions update accordingly. Crossover arc endpoints must also update to follow their attached backbone beads.

**Interaction with crossovers**: In `unfold_view.js`, arc geometry (`unfold_view.applyCadnanoPositions()` and arc build path) reads from `design.crossovers`. Under expanded spacing, the beads are at non-lattice positions, so arcs must re-anchor from the live bead positions, not pre-computed lattice positions.

---

## Pre-Condition State

- `crossover_locations.js` was the old provider of "expanded crossover overlay" positions — it is deleted
- Arc geometry in `unfold_view.js` may still reference the old crossover location system
- Unknown whether `crossover_connections.js` (the new 3D line renderer) updates correctly when bead positions change due to expanded spacing
- No Playwright test covers expanded spacing + crossover interactions

---

## Clarifying Questions

1. In the expanded view, should crossover **arc** height (bow height) scale proportionally with the inter-helix spacing, or stay at a fixed bow height?
   - Proportional: arcs look the same relative to helix spacing at all zoom levels
   - Fixed: arcs could appear flat (too small) when helices are very far apart, or very tall when close

2. Should expanded spacing be available simultaneously with the **cadnano 3D mode** (K key)?
   - Current `MAP_CADNANO.md` says: "Expanded spacing: forced off before cadnano activation"
   - Confirm this is still the intended behavior

3. Is expanded spacing a continuous slider, discrete steps, or a toggle (off/2×)?

---

## Experiment Protocol

### Experiment 1.1 — Expanded spacing activates and beads move

**Hypothesis**: Pressing `E` (or activating from menu) on a loaded design causes all helix backbone beads to spread laterally from the lattice center. Bead count is unchanged.

**Test Steps**:
1. Load `26hb_platform_v3.nadoc`
2. Confirm bead positions at t=0 (note a few reference positions)
3. Press `E` to activate expanded spacing
4. Check bead positions have changed (displaced laterally)

**Data Collection**:
```javascript
// Sample 3 helix positions before and after
const sample = await page.evaluate(() => {
  const geo = window._nadoc?.store?.getState()?.currentGeometry
  return geo?.slice(0, 3).map(n => ({ helix: n.helix_id, bp: n.bp_index, pos: n.backbone_position }))
})
```

**Pass Criteria**: Positions change after `E`, lateral displacement > 0. Bead count identical.

**Fail → Iteration 1.1a**: If beads don't move, `expanded_spacing.js` is not applying its transform to the renderer. Check the subscriber chain — does `expanded_spacing.js` call `designRenderer.applyExpandedPositions()` or equivalent?

---

### Experiment 1.2 — Crossover lines follow expanded bead positions

**Hypothesis**: After activating expanded spacing, the white crossover connection lines (`crossover_connections.js` mesh) move with the beads and still connect the correct pairs.

**Test Steps**:
1. Load `3NN_ground truth.nadoc`, note crossover mesh segment count
2. Activate expanded spacing
3. Check crossover mesh is still present and segment count unchanged
4. Screenshot: crossover lines should visually connect bead pairs at new expanded positions

**Data Collection**: Screenshot before and after; mesh vertex positions via console.

**Pass Criteria**: Crossover lines visible at new positions; no `[XOVER 3D] unresolved crossover` warnings; segment count unchanged.

**Fail → Iteration 1.2a**: If lines stay at original positions while beads move, `crossover_connections.js` is rebuilt from `currentGeometry` positions but the geometry store is not updated when expanded spacing changes. Find where expanded spacing sets bead positions and ensure a `setCurrentGeometry()` store update fires.

**Fail → Iteration 1.2b**: If lines disappear, the geometry rebuild triggered by expanded spacing disposes the crossover mesh without rebuilding it. Fix: ensure the expanded-spacing position update path calls `buildCrossoverConnections()`.

---

### Experiment 1.3 — Arc bow height behavior under expanded spacing

**Hypothesis**: Crossover arcs in unfold view (U key while expanded) have bow heights that scale with the expanded helix spacing.

**Test Steps**:
1. Load `3NN_ground truth.nadoc`
2. Press `U` (unfold) + `E` (expanded) simultaneously or in sequence
3. Screenshot arc heights at default spacing
4. Increase expanded spacing
5. Screenshot arc heights at larger spacing

**Data Collection**: Measure arc midpoint Y displacement vs. helix center Y distance ratio. Should be constant (proportional) or note if it's fixed.

**Pass Criteria**: Determined by user answer to clarifying question #1. Document the measured behavior and compare to expectation.

---

### Experiment 1.4 — Cadnano mode blocks expanded spacing

**Hypothesis**: Activating cadnano mode (K key) while expanded spacing is active forces expanded spacing off, and the spacing UI control is disabled.

**Test Steps**:
1. Activate expanded spacing
2. Press K (cadnano mode)
3. Check: expanded spacing disabled? UI control greyed out? Beads at standard cadnano positions?

**Data Collection**: Store state after K press:
```javascript
const state = window._nadoc?.store?.getState()
console.log('cadnanoActive:', state.cadnanoActive, 'expandedSpacing:', state.expandedSpacing)
```

**Pass Criteria**: `expandedSpacing === false` (or 0/default) when `cadnanoActive === true`.

**Fail → Iteration 1.4a**: If expanded spacing persists in cadnano mode, `cadnano_view.js::activate()` is not resetting the spacing before entering cadnano mode. Add `store.setState({ expandedSpacing: false })` (or call the appropriate reset function) at the start of cadnano activation.

---

### Experiment 1.5 — Deactivation restores original positions

**Hypothesis**: Pressing `E` again (or toggling off) returns all beads to their exact lattice positions with no floating-point drift.

**Test Steps**:
1. Record reference positions for 5 beads
2. Activate expanded spacing
3. Deactivate expanded spacing
4. Check positions returned to reference within 0.001 nm tolerance

**Pass Criteria**: `|final_pos - reference_pos| < 0.001 nm` for all 5 sampled beads.

---

## Performance Notes

*Do not implement until experiments pass.*

- If expanded spacing triggers a full `rebuild(design, geometry)` on every slider tick, that is expensive for large designs. The expansion is a pure XY transform of existing bead positions — it should be applied as a per-entry `entry.pos.x *= scale; entry.pos.y *= scale` mutation, not a full rebuild.
- Crossover mesh should be rebuilt (it's cheap — pure Float32Array write) on expansion change, but the helix renderer should not be fully torn down.
- If expansion change uses a debounce (e.g., 50ms after last slider tick), document the debounce interval as a tunable constant.

---

## Refactor Plan

*Execute only after all 1.x experiments pass.*

1. **Position update path**: ensure expanded spacing uses in-place `entry.pos` mutation via `applyExpandedPositions(scale)` rather than triggering a full `rebuild()`. Add this as a named method on `designRenderer`.
2. **Arc height scaling**: implement proportional arc bow height as a function of spacing factor. Store `_baseArcHeights` at 1× spacing and scale on each expansion change.
3. **Performance baseline**: record the scripting time for a slider drag from 1× to 3× on the 26HB fixture.
