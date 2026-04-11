# Feature 02: Cadnano 3D Mode (K Key)
**Phase**: B (Core 2D/3D Views — requires Phase A foundation)

---

## Feature Description

The **cadnano 3D mode** (`K` key) projects the 3D design into a flat 2D layout matching caDNAno v2's visual convention:
- Helices arranged as horizontal rows in YZ space
- Orthographic camera looking along the X axis
- Backbone beads lerp from 3D positions to cadnano row positions (500ms transition)
- Crossover arcs shown between adjacent rows
- Row bands (translucent YZ planes) distinguish helix rows

**Key file**: `frontend/src/scene/cadnano_view.js` — `initCadnanoView(...)`
**Store key**: `cadnanoActive`
**Reference**: `memory/MAP_CADNANO.md` (comprehensive — read it before editing this feature)

### Crossover arc source (post-overhaul)
Previously arcs were sourced from `crossover_locations.js` (deleted). Now `unfold_view.js` provides `applyCadnanoPositions()` which builds arc geometry from `design.crossovers`. Arcs are rendered as bézier curves between the two backbone positions in the flat cadnano layout.

---

## Pre-Condition State

From `MAP_CADNANO.md` known issues (as of 2026-04-01):
- Arc bow direction in the flat cadnano layout is "visually reasonable but not verified against caDNAno conventions"
- `__xb_` and `__ext_` arc entries are silently skipped — visual state in cadnano mode undefined
- Known bead flash bug (`cadnano_view.js:661` — `console.error('[CN] bead left cadnano after reapply — STILL BROKEN')`): hard to reproduce
- No automated e2e tests for cadnano 3D mode
- After the crossover overhaul: unknown whether `unfold_view.js`'s arc builder reads from `design.crossovers` correctly

---

## Clarifying Questions

1. In cadnano 3D mode, should crossover arcs appear as:
   - (a) 90° arcs between adjacent rows (matching caDNAno2 visual convention — arcs bow horizontally in Z)
   - (b) Straight line segments (same as `crossover_connections.js`)
   - (c) The current bézier bow — just verify it matches the correct direction

2. Should `__xb_` (extension) entries:
   - (a) Hidden entirely in cadnano mode
   - (b) Shown as straight overhangs from the row positions
   - (c) Current behavior (silently skipped — invisible but no error)

3. Post-overhaul: are scaffold crossovers (now in `design.crossovers`) shown as arcs in cadnano mode, or should they be visually distinguished from staple crossovers?

---

## Experiment Protocol

### Experiment 2.1 — Smooth activation transition

**Hypothesis**: Pressing `K` on a loaded 6HB design triggers a smooth 500ms lerp from 3D positions to flat cadnano row positions. After transition, beads are at `x = midX` (constant), `y = -row * spacing`, `z = bpIndex * BDNA_RISE_PER_BP`.

**Test Steps**:
1. Load `Examples/Honeycome_6hb_test1_NADOC.nadoc`
2. Press K
3. After transition (>500ms), check bead positions

**Data Collection**:
```javascript
// Verify beads are at flat cadnano positions
const entries = window._cnEntries?.()
const firstEntry = entries?.[0]
console.log('[cadnano pos check]', {
  x: firstEntry?.pos.x.toFixed(3),  // should equal _midX (constant for all beads)
  y: firstEntry?.pos.y.toFixed(3),  // should be -row * spacing
})
// Use window._cnCheck() for full state
window._cnCheck?.()
```

**Pass Criteria**: All bead `pos.x` values equal `_midX` within 0.001; `pos.y` values match `−row × spacing` formula.

**Fail → Iteration 2.1a**: If transition doesn't start, `cadnano_view.js::activate()` is not being called. Check the K key handler in `main.js` (`_toggleCadnano()`).

**Fail → Iteration 2.1b**: If beads end up at wrong positions, `_cadnanoPosMap` is built incorrectly. Check `cadnano_view.js` map construction against HC row numbering.

---

### Experiment 2.2 — Crossover arcs appear in cadnano layout

**Hypothesis**: After K-mode activation, crossover arcs are visible between adjacent helix rows. Each arc connects two beads that share a `design.crossovers` entry.

**Test Steps**:
1. Load `3NN_ground truth.nadoc` (has many crossovers)
2. Press K, wait for transition
3. Screenshot cadnano view
4. Count visible arcs

**Data Collection**:
```javascript
// Count arc objects in unfold_view
const arcCount = await page.evaluate(() => {
  const scene = window._nadoc?.scene
  let arcs = 0
  scene?.traverse(obj => { if (obj.name?.startsWith('crossover-arc')) arcs++ })
  return arcs
})
```

**Pass Criteria**: `arcCount > 0` AND arcs visually connect adjacent row pairs at the correct bp positions. Screenshot shows arcs bowing in the expected direction.

**Fail → Iteration 2.2a**: If no arcs, `unfold_view.applyCadnanoPositions()` is not being called, or arcs are not built from `design.crossovers`. Trace the call from `cadnano_view.js::reapplyPositions()` to `getUnfoldView().applyCadnanoPositions()`.

**Fail → Iteration 2.2b**: If arc count doesn't match `design.crossovers.length`, some crossovers are failing the position lookup. Check for `[XOVER arc] unresolved` console warnings.

---

### Experiment 2.3 — Flash regression test

**Hypothesis**: After a topology mutation (nick) while in cadnano mode, beads do NOT flash to 3D positions for even one frame.

**Test Steps**:
1. Enter cadnano mode (`K`)
2. Enable `window._cnDebug = true`
3. Add a nick via UI or API
4. Watch for `_startPostReapplyMonitor` output — should report "all clear"
5. Look for `[INTERCEPT] pos.x →` logs (indicates a rogue writer)

**Data Collection**: Console output from `_cnDebug` monitor.

**Pass Criteria**: No `[INTERCEPT]` logs. No visual flash in the screenshot taken 1 frame after the mutation.

**Fail → Iteration 2.3a**: Identify the subscriber that writes 3D positions after `reapplyPositions()`. The stack trace from `_cnDebug` points directly to it. Add the `cadnanoActive` guard (see `MAP_CADNANO.md` — `clearFemOverlay()` fix pattern).

---

### Experiment 2.4 — Full view transition round-trip

**Hypothesis**: 3D → Cadnano → Unfold → 3D returns beads to their original 3D geometry positions within 0.001 nm.

**Test Steps**:
1. Record 5 reference bead positions (3D)
2. `K` → cadnano
3. `U` → exits cadnano, stays in unfold
4. `U` → back to 3D
5. Check positions match reference

**Data Collection**: Before/after position diff for 5 sampled beads.

**Pass Criteria**: `|final − reference| < 0.001 nm`.

**Fail → Iteration 2.4a**: Check `cadnano_view.js::deactivate()` — it should call `unfoldView.deactivate()` which in turn calls `revertToGeometry()`. If either is skipped, positions drift.

---

### Experiment 2.5 — Loop/skip markers in cadnano mode

**Hypothesis**: Loop tori and skip X-arm markers snap to cadnano YZ-plane positions at end of 250ms animation (they do not lerp — they snap). After deactivation, they return to XY-plane orientation.

**Test Steps**:
1. Load a design with loop/skip markers
2. Enter cadnano mode
3. Screenshot loop tori (should be visible as circles in the YZ plane from X- camera)
4. Exit cadnano mode (`K`)
5. Screenshot — tori should be back in XY plane

**Pass Criteria**: Loop tori visible in cadnano mode; quaternions change to YZ-plane; restored to XY after exit.

**Fail → Iteration 2.5a**: If tori invisible in cadnano, `loop_skip_highlight.applyCadnanoPositions()` is not being called. Trace from `reapplyPositions()` in `cadnano_view.js`.

---

## Performance Notes

*Do not implement until experiments pass.*

- `_buildRowBands()` (translucent YZ plane meshes) iterates all helices to find unique row numbers. This could be precomputed once when the design changes and cached as `_rowSet`. Invalidate on helix add/remove only.
- The `_unfoldPosMap` merge-only pattern (see `MAP_CADNANO.md`) is a correctness requirement, not just a performance optimization — document this explicitly in the code as a `// INVARIANT:` comment.
- `reapplyPositions()` calls 6+ overlay functions sequentially. These are all synchronous O(n) over backbone entries. No parallelization possible (JS is single-threaded), but grouping the position writes into a single `requestAnimationFrame` would batch GPU uploads.

---

## Refactor Plan

*Execute only after all 2.x experiments pass.*

1. **Write the first cadnano e2e test**: `frontend/e2e/cadnano_3d_mode.spec.js` covering experiments 2.1, 2.3, 2.4 as automated tests. This provides regression coverage going forward.
2. **Document arc bow direction decision**: whatever the user confirms for clarifying question #1, add a `// DESIGN DECISION:` comment in `unfold_view.js::applyCadnanoPositions()`.
3. **`__xb_` / `__ext_` handling**: based on answer to clarifying question #2, either add an explicit hide/show or document the skip as intentional.
4. **`_buildRowBands()` cache**: implement the `_rowSet` precomputation cache and verify no visual regression.
5. **Performance baseline**: record the activation transition time (0ms to `_active=true`) for the 26HB fixture.
