# Post-Overhaul Triage: Master Guide

## Executive Summary

During `feature/massive-cadnano-overhaul`, the crossover system was replaced wholesale:

| Old | New |
|-----|-----|
| Crossovers implicit in strand domain topology | Explicit `Design.crossovers: list[Crossover]` |
| `crossover_locations.js` — 3D interactive overlay | DELETED — no replacement yet |
| Crossover rendering via strand traversal | `crossover_connections.js` reads `design.crossovers` directly |
| Crossover placement via 3D context menus | 2D cadnano editor + 3D overlay (to rebuild) |

Every feature that touched crossover data is in an unknown state. This guide organizes the triage into five phases of increasing dependency, with links to per-feature documents.

---

## New Crossover Infrastructure

### Data Model (`backend/core/models.py`)
```python
class HalfCrossover(BaseModel):
    helix_id: str
    index: int        # global bp index — must match on both halves
    strand: Direction # FORWARD or REVERSE

class Crossover(BaseModel):
    id: str           # UUID
    half_a: HalfCrossover
    half_b: HalfCrossover
```

`Design.crossovers: list[Crossover]` is the single source of truth. Both scaffold and staple crossovers are stored here.

### Backend Logic (`backend/core/crossover_positions.py`)
- `all_valid_crossover_sites(design)` — returns all geometrically valid (helix, bp, direction) triples
- `validate_crossover(design, half_a, half_b)` — checks adjacency, slot occupancy, geometry
- `crossover_neighbor(lattice_type, row, col, index)` — table lookup for adjacent cell

### API Routes
| Method | Path | Effect |
|--------|------|--------|
| `GET` | `/design/crossovers/valid` | All valid sites |
| `POST` | `/design/crossovers` | Add crossover |
| `DELETE` | `/design/crossovers/{id}` | Remove crossover |

### 3D Renderer (`frontend/src/scene/crossover_connections.js`)
- `buildCrossoverConnections(design, geometry)` → `THREE.LineSegments | null`
- One white line per `Crossover` between backbone positions of the two halves
- Stateless: rebuilt on every design/geometry change

### Known Gaps (as of overhaul)
- No 3D interactive overlay showing *valid* sites — `crossover_locations.js` was deleted
- `design_renderer.js` may not call `buildCrossoverConnections()` on every rebuild path
- `crossover_connections.js` not integrated into cadnano/unfold position map updates

---

## Phased Execution Order

Dependencies flow downward. Do not start a phase until the previous phase's features pass all experiments.

```
Phase A — Foundation
  [10] 3D Representations      ← crossover_connections.js wired into all render paths
  [08] cadnano import           ← design.crossovers populated after import
  [09] scadnano import          ← design.crossovers populated after import

Phase B — Core 2D/3D Views
  [01] Expanded quick view      ← arcs re-anchor in expanded layout
  [02] Cadnano 3D mode (K key)  ← crossover arcs in flat cadnano layout

Phase C — Topology Mutations
  [06] Prebreak + Autocrossover ← 3D overlay rebuilt; batch crossover add
  [07] Autoscaffold             ← scaffold crossovers written to design.crossovers

Phase D — Transform Features
  [03] Clustering               ← crossovers move with cluster gizmo
  [04] Deform tools             ← crossovers render at deformed positions

Phase E — Temporal / Presentation
  [05] Animation                ← cluster configs + crossover state over time
```

---

## Shared Test Fixtures

| Fixture | Use case | Phase |
|---------|----------|-------|
| `Examples/multi_domain_test.nadoc` | Minimal — few helices, known topology | A |
| `Examples/3NN_ground truth.nadoc` | Medium — 3NN HC, verified crossovers | A, B |
| `Examples/26hb_platform_v3.nadoc` | Large — 26HB, many crossovers | B, C |
| `Examples/multi_domain_test3_bend90.nadoc` | Deformation baseline | D |
| `Examples/Honeycome_6hb_test1_NADOC.nadoc` | Cluster baseline | D |

**Fixture verification (must pass before use)**:
```bash
# Load each fixture and confirm design.crossovers is non-empty where expected
curl -X POST http://localhost:8000/api/design/load \
  -H 'Content-Type: application/json' \
  -d '{"path": "Examples/3NN_ground truth.nadoc"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['design']['crossovers']))"
```

---

## Playwright Conventions

All e2e experiments go in `frontend/e2e/triage/`. Name files `exp_NN_M_description.spec.js`.

### Store access
```javascript
// Get current crossover count
const xoCount = await page.evaluate(() =>
  window._nadoc?.store?.getState()?.currentDesign?.crossovers?.length ?? -1
)

// Get first 5 geometry entries for position sanity check
const geo = await page.evaluate(() =>
  window._nadoc?.store?.getState()?.currentGeometry?.slice(0, 5)
)

// Check scene for crossover mesh
const hasMesh = await page.evaluate(() =>
  !!window._nadoc?.scene?.getObjectByName('crossoverConnections')
)
```

### Screenshot convention
```javascript
await page.screenshot({
  path: `screenshots/exp_${FEATURE}_${STEP}_${label}.png`,
  fullPage: false,
})
```

### 3D measurement
Use Playwright's `page.evaluate` to query Three.js geometry directly from `window._nadoc` — this avoids pixel-counting heuristics. Expose any needed internals via `window._nadoc` if not already there.

### Experiment result table (append to each spec file as a comment)
```javascript
// RESULTS:
// Pass/Fail | Condition | Measured | Expected | Notes
```

---

## Performance Baseline Protocol

Run **before and after** every refactor section:

1. Open DevTools → Performance tab → Start recording
2. Load the large fixture (`26hb_platform_v3.nadoc`)
3. Perform the feature-specific operation 3×
4. Stop recording → note **Scripting** and **Rendering** ms totals
5. Record in the feature document's Refactor Plan section as:
   ```
   Before: Scripting Xms / Rendering Yms (mean of 3 runs)
   After:  Scripting Xms / Rendering Yms
   Delta:  −X% scripting
   ```

---

## Cross-Feature Invariants

These rules apply across all features and must be checked whenever a feature interacts with the crossover model:

1. **`design.crossovers` is the only source of truth** — no feature may infer crossover connections from strand topology
2. **`buildCrossoverConnections()` is stateless** — it must be called every rebuild, not cached across design changes
3. **cadnanoActive / unfoldActive guards** — any code calling `revertToGeometry()` after a topology mutation must check these flags (see `MAP_CADNANO.md`)
4. **`Design(...)` rebuild carries deformations** — every `Design(...)` constructor call in `lattice.py` must pass `deformations=existing.deformations` (see `MAP_DEFORMATION.md`)
5. **Scaffold crossovers in `design.crossovers`** — confirmed by user; all import/routing code must populate scaffold entries too

---

## Per-Feature Document Index

| # | Feature | Phase | Document |
|---|---------|-------|----------|
| 01 | Expanded quick view | B | [01_expanded_quick_view.md](01_expanded_quick_view.md) |
| 02 | Cadnano 3D mode | B | [02_cadnano_3d_mode.md](02_cadnano_3d_mode.md) |
| 03 | Clustering | D | [03_clustering.md](03_clustering.md) |
| 04 | Deform tools | D | [04_deform_tools.md](04_deform_tools.md) |
| 05 | Animation | E | [05_animation.md](05_animation.md) |
| 06 | Prebreak + Autocrossover | C | [06_prebreak_autocrossover.md](06_prebreak_autocrossover.md) |
| 07 | Autoscaffold | C | [07_autoscaffold.md](07_autoscaffold.md) |
| 08 | cadnano import | A | [08_cadnano_import.md](08_cadnano_import.md) |
| 09 | scadnano import | A | [09_scadnano_import.md](09_scadnano_import.md) |
| 10 | 3D representations | A | [10_3d_representations.md](10_3d_representations.md) |
