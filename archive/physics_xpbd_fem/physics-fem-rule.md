---
name: physics-fem
description: XPBD physics overlay + FEM analysis. WebSocket streaming, store keys, revert sequence, equilibrium debug.
paths:
  - "backend/physics/**/*.py"
  - "backend/core/fem*.py"
  - "frontend/src/scene/*physics*.js"
  - "frontend/src/scene/*fem*.js"
---

# physics-fem

## Architecture

## Entry Points
- **XPBD (detailed)**: `frontend/src/physics/physics_client.js` — `initPhysicsClient({onPositions, onStatus})`
- **XPBD (fast)**: `frontend/src/physics/physics_client.js` — `initFastPhysicsClient({onUpdate, onStatus})`
- **FEM**: `frontend/src/physics/fem_client.js` — `initFemClient({onProgress, onResult})` — main.js ~line 2291
- **Display**: `frontend/src/physics/displayState.js` — `initFastPhysicsDisplay(scene, designRenderer)`
- **Backend XPBD**: `backend/physics/xpbd.py`, `backend/physics/xpbd_fast.py`
- **Backend FEM**: `backend/physics/fem_solver.py`
- **Backend WebSocket**: `backend/api/ws.py` — `/ws/physics`

## Store Keys
| Key | Semantics |
|-----|-----------|
| `physicsMode` | XPBD overlay active |
| `physicsPositions` | `Map "hid:bp:dir" → [x,y,z]` from XPBD stream |
| `femMode` | FEM overlay active |
| `femPositions` | FEM-relaxed backbone positions |
| `femRmsf` | Per-nucleotide RMSF `[0,1]` — used for heatmap colormap |
| `femStatus` | `'idle' \| 'running' \| 'done' \| 'error'` |
| `femStats` | `{node_count, element_count, spring_count}` |

## Physics Mode Toggle ([P] key)
```
ON (fast mode):   fastClient.connect('/ws/physics/fast') → fastDisplay.start(particles)
ON (detailed):    physicsClient.connect('/ws/physics') → streams backbone positions at 10fps
                  → designRenderer.applyPhysicsPositions(updates)
                  → bluntEnds?.applyPhysicsPositions(updates)
                  → store.setState({ physicsMode: true })

OFF: _stopPhysicsIfActive()
  detailed: physicsClient.stop()
            designRenderer.applyPhysicsPositions(null)  ← calls revertToGeometry()
            deformView.reapplyLerp()  ← CRITICAL: restores deformation state
            store.setState({ physicsMode: false })
  fast:     fastClient.stop(); fastDisplay.stop()
```

## FEM Analysis
- Euler-Bernoulli beam elements: EA=1100, EI=230, GJ=460 pN·nm
- Inter-helix springs: rigid penalty (k=1e6) for duplexed regions; WLC spring for ssDNA
- RMSF via shift-invert `eigsh(σ=0, N_RMSF_MODES=30)` — centroid-pinned BC
- WebSocket `/ws/fem` with heartbeat progress bar

## FEM Known Issue
**Equilibrium overlay is disabled** (shows u=0). Root cause: torsional pre-stress not yet implemented. Priority 1 fix: apply `M = GJ × Δθ / L` torsional moments at inter-helix constraint nodes. See `REFERENCE_FEM.md` for full plan.

## Backend XPBD Files
- `backend/physics/xpbd.py` — `SimState`, `build_simulation()`, `xpbd_step()`
- `backend/physics/xpbd_fast.py` — Numba-accelerated helix-segment variant
- `backend/physics/skip_loop_mechanics.py` — loop/skip strain mechanics
- `backend/physics/fem_solver.py` — FEM stiffness assembly + RMSF solve

## Diagnostics → `RUNBOOK_PHYSICS.md`

## Diagnostics

## Symptoms
- FEM equilibrium shape overlay shows original geometry (no deformation)
- RMSF heatmap not colorizing backbone spheres
- Physics (XPBD) overlay not appearing / stuck after stopping
- "Equilibrium overlay" checkbox missing from UI
- RMSF coloring looks flat / no discrimination between flexible/rigid nodes

## First-Check Invariants

1. **Equilibrium overlay is intentionally disabled** — The "Equilibrium shape overlay" checkbox is hidden in the UI. Root cause: torsional pre-stress not implemented, so equilibrium displacement u=0 trivially. This is NOT a bug — it's deferred work. Don't try to re-enable it without implementing torsional pre-stress first.

2. **RMSF heatmap is the working feature** — RMSF (flexibility heatmap) works correctly. If RMSF is showing but seeming flat, see "weak RMSF discrimination" below.

3. **Physics revert sequence** — After XPBD off, must call both `revertToGeometry()` AND `deformView.reapplyLerp()`. Missing the second leaves structure in straight position.

## Diagnosis Tree

### FEM equilibrium shows original geometry (u=0)
- **Expected behavior** — equilibrium overlay is disabled pending torsional pre-stress implementation
- Priority 1 fix: For each domain segment:
  - `θ_natural = n_bp × (2π / 10.5)` (B-DNA preferred twist)
  - `Δθ = θ_actual - θ_natural` (mismatch from HC/SQ bp cells)
  - Apply torsional force pair at inter-helix constraint nodes: `M = GJ × Δθ / L`
  - Into `f[di+5]` and `f[dj+5]` (θ_z DOF = beam torsion)
- Reference: Castro et al. Nature Methods 8, 221 (2011) supplementary

### RMSF heatmap not colorizing
1. Check `store.femRmsf` — is it populated after FEM run?
2. Check `store.femStatus === 'done'`
3. Check `design_renderer.js` subscription to `femRmsf` — does it apply colormap?
4. Key format: `"helix_id:bp_index:direction"` — verify backend key format matches frontend

### Weak RMSF discrimination (all nodes look similar)
- Current: terminal vs interior nodes show very similar RMSF values
- Fix options: more eigenmodes (currently N_RMSF_MODES=30), different normalization, stronger ssDNA WLC springs
- See `REFERENCE_FEM.md` Priority 3

### XPBD overlay not appearing
1. Check `store.physicsMode` after pressing [P]
2. Check WebSocket connection to `/ws/physics` — console errors?
3. Check `_physSubMode` ('fast' vs 'detailed') — correct WebSocket endpoint?
4. Fast mode: `/ws/physics/fast` → fastDisplay.start(particles)
5. Detailed mode: `/ws/physics` → designRenderer.applyPhysicsPositions(updates)

### Physics overlay stuck after stopping
1. Find `_stopPhysicsIfActive()` in `main.js`
2. Detailed path must call: `physicsClient.stop()`, `designRenderer.applyPhysicsPositions(null)`, `deformView.reapplyLerp()`, `store.setState({ physicsMode: false })`
3. Fast path must call: `fastClient.stop()`, `fastDisplay.stop()`

## Files to Read
- `backend/physics/fem_solver.py` — stiffness assembly, RMSF eigsh, force vector
- `frontend/src/physics/fem_client.js` — WebSocket, `onResult` callback
- `frontend/src/scene/design_renderer.js` — femRmsf subscription, colormap application
- `frontend/src/main.js` — `_stopPhysicsIfActive()`, `_togglePhysics()`

## Related
- `MAP_PHYSICS.md` — physics architecture
- `REFERENCE_FEM.md` — full FEM theory, known issues, torsional pre-stress plan

