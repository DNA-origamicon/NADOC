# NADOC Development Plan

## Architecture Axioms (never violate these)

Three strictly separated layers:
1. **Topological layer** — strand graph, crossover graph, scaffold routing. Ground truth. Edits go here only.
2. **Geometric layer** — helix axes, nucleotide positions derived from topology + constants. Read-only output.
3. **Physical layer** — XPBD/oxDNA relaxed positions. Display state only. Never written back to topology.

## DTP-0 Decisions (recorded 2026-03-10)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DTP-0a: nucleotide model | Add base bead to `NucleotidePosition` now | Required for oxDNA export; retroactively adding it is a larger refactor |
| DTP-0b: crossover placement | Constrained only (caDNAno2 style) | Expert user doesn't need freeform; invalid crossovers are never useful |
| DTP-0c: scaffold routing | Multiple scaffold paths supported (MagicDNA style) | Required for clockwork multi-component assemblies |
| DTP-0d: Part frame origin | Designated interface point (option 4) | Most useful for assembly; blunt ends derived from helix terminus geometry |

## 3D Validation Protocol (all phases)

Every 3D validation checkpoint follows this pattern:
1. The element under validation is **colored a unique highlight color** and **scaled ≥3×**
2. Its ID and relevant numeric properties are **displayed in an overlay panel**
3. A **specific directional question** is asked — never "does this look right?"
4. Validation must be confirmed before the next phase begins

---

## Phase 0 — Foundation

**Status: ✅ Complete — 29/29 tests passing**

- uv project, all dependencies
- `backend/core/constants.py` — B-DNA parameters (single source of truth)
- `backend/core/models.py` — full Pydantic model hierarchy
- `backend/core/geometry.py` — `nucleotide_positions()` (backbone bead, base bead, base-normal, axis-tangent)
- `backend/core/validator.py` — `validate_design()` → `ValidationReport`
- `tests/test_geometry.py` — 15 geometry tests
- `tests/test_models.py` — 14 model serialisation tests
- `justfile` — dev, test, frontend targets

---

## Phase 1 — Geometry Visualization Harness

**Status: ✅ Complete — 35/35 tests passing, all V1.x checkpoints confirmed**

**Goal**: See nucleotide positions rendered correctly in 3D. No editing. No physics.
If geometry is wrong here, every downstream phase builds on a lie.

### Deliverables
- FastAPI `main.py` serving API endpoints; CORS for Vite dev proxy
- REST: `GET /api/health`, `GET /api/design/demo`, `GET /api/design/demo/geometry`
- Seed design: single 42 bp helix along +Z axis
- Vite + Three.js frontend:
  - Helix axis as white line
  - FORWARD backbone beads — green spheres
  - REVERSE backbone beads — blue spheres
  - Base beads — smaller, slightly dimmer version of strand color
  - Backbone→base connector segments
  - Base-normal vectors as short line segments
  - OrbitControls (drag=rotate, scroll=zoom, right-drag=pan)
  - `?debug=1` shows raw position values in overlay when nucleotide is clicked

### 3D Validation Checkpoints

**V1.1 — Handedness**
Camera moves to look from +Z (above). FORWARD nucleotides bright green.
Prompt: *"Looking down the helix axis from above, the green FORWARD strand should spiral COUNTERCLOCKWISE for right-handed B-DNA. Does it?"*

**V1.2 — Rise per bp**
bp 0 and bp 1 FORWARD backbone beads colored red, scaled 3×. Distance label between them.
Prompt: *"The two red enlarged spheres are bp 0 and bp 1 FORWARD backbone beads. The label shows their separation. Does it read 0.334 nm?"*

**V1.3 — Base normal direction** ✅
bp 0 FORWARD: base-normal spike drawn at 5× length in yellow.
Confirmed: base_normal is the cross-strand vector from FORWARD backbone toward REVERSE backbone (NOT inward toward helix axis).

**V1.4 — Major/minor groove geometry** ✅
bp 10: FORWARD backbone red, REVERSE backbone blue, white line connecting them.
Confirmed: REVERSE strand is at 120° (minor groove) from FORWARD. White connector does NOT pass through axis. Backbone-to-backbone distance ≈ 1.732 nm (√3 × helix_radius).

### Geometry conventions confirmed by V1.x
- Strands are 120° apart (minor groove offset), NOT antipodal (180°)
- base_normal = normalize(rev.backbone − fwd.backbone) — cross-strand, not radial
- V1.2 axial rise = dot(displacement, axis_tangent) = 0.334 nm

### Documentation checkpoint
After V1.1–V1.4 confirmed: update `MEMORY.md` with confirmed 3D orientation conventions.

---

## Phase 2 — Bundle Creator (caDNAno-style cross-section)

**Status: ✅ Complete — 99/99 tests passing, all features shipped**

**Goal**: Create honeycomb bundle designs from a 2D cross-section view. Validate scaffold parity rules and extrude UI.

### DTP-2 Decision (2026-03-10, binding)
**Pre-computed valid positions as clickable markers only.** No register gauge. Backend pre-computes valid crossover bp positions for a given helix pair; frontend shows them as markers. Consistent with DTP-0b (no freeform crossovers). Valid bp offsets: multiples of ~10.495 bp/turn, nearest-integer candidates.

### Honeycomb cell rule (binding, 2026-03-11)
`val = (row + col%2) % 3`
- 0 → valid cell, scaffold FORWARD (5′ at bp 0)
- 1 → valid cell, scaffold REVERSE (5′ at bp N-1)
- 2 → hole (no helix placed here)

This 3-coloring of the triangular lattice guarantees every pair of adjacent valid cells is antiparallel — a necessary condition for scaffold crossovers. Verified: 0 violations over full 8×12 grid.

### Phase offset convention (binding, updated 2026-03-20)
For helices along +Z, `_frame_from_helix_axis` gives `frame[:,0]=(0,-1,0)`, `frame[:,1]=(1,0,0)`.
- **FORWARD cells (val=0)**: `phase_offset = 322.2°`
- **REVERSE cells (val=1)**: `phase_offset = 252.2°`

These values were optimised empirically to equalise backbone distance at all three HC crossover pair directions simultaneously (spread 0.004 nm). Implemented in `lattice.py::_lattice_phase_offset()` and `cadnano.py::_PHASE_FORWARD/_PHASE_REVERSE`.

HC staple crossover positions (per 21-bp period), ground truth in `drawings/lattice_ground_truth.png`:
- **p330** (FORWARD→REVERSE angle 330°): `{0, 20}`
- **p90**  (FORWARD→REVERSE angle  90°): `{13, 14}`
- **p210** (FORWARD→REVERSE angle 210°): `{6, 7}`

Lookup table in `backend/core/crossover_positions.py::_HC_OFFSETS`. A distance guard (≤ 2.25 nm × 1.05) prevents non-adjacent helices from matching on angle alone.

### Color scheme (binding, 2026-03-11)
- All scaffold strands: sky blue `#29b6f6` (role-based, not direction-based)
- Staple strands: per-strand color from STAPLE_PALETTE (12 distinct hues, assigned by strand_id hash)
- Unassigned backbone beads: dark slate `#445566`

### Honeycomb lattice constants (caDNAno convention)
- `HONEYCOMB_LATTICE_RADIUS = 1.125 nm` (per-helix spacing unit)
- `HONEYCOMB_HELIX_SPACING = 2.25 nm` (= 2 × LATTICE_RADIUS, centre-to-centre)
- `HONEYCOMB_COL_PITCH = 1.125 × √3 ≈ 1.9486 nm`
- `HONEYCOMB_ROW_PITCH = 2 × 1.125 = 2.25 nm` (triangular close-packing, NOT 3×)

### Deliverables (99/99 tests passing)
- `backend/core/constants.py` — HONEYCOMB_HELIX_SPACING, LATTICE_RADIUS, COL_PITCH, ROW_PITCH
- `backend/core/lattice.py` — unified `honeycomb_cell_value`, `is_valid_honeycomb_cell`, `scaffold_direction_for_cell`, `make_bundle_design` (hole rejection + phase offsets + scaffold/staple pair per helix)
- `backend/api/crud.py` — POST /api/design/bundle; 5′/3′ placement fix (start_bp=5′, end_bp=3′ convention)
- `frontend/src/api/client.js` — createBundle({cells, lengthBp, name})
- `frontend/src/ui/lattice_editor.js` — 2D hex canvas, click-to-toggle, teal=FORWARD/coral=REVERSE coloring
- `frontend/src/ui/extrude_panel.js` — 3 button styles (A=Blender, B=Fusion, C=SOLIDWORKS), nm/bp unit toggle
- `frontend/index.html` — 3-panel layout (220px lattice | flex-1 3D canvas | 300px props)
- `frontend/src/scene/scene.js` — ResizeObserver on container (not window)
- `frontend/src/scene/helix_renderer.js` — role-based colors; customColors; `setStrandColor`; 5′ cube placement
- `frontend/src/scene/selection_manager.js` — two-click model (strand→bead); right-click 12-color picker
- `frontend/src/scene/design_renderer.js` — `setStrandColor` persisted in store.strandColors
- `frontend/src/scene/crossover_markers.js` — NDC fix; canvas param
- `frontend/src/scene/workspace.js` — honeycomb hole filtering; all lattice circles same gold
- `frontend/src/state/store.js` — `strandColors` state
- `tests/test_lattice.py` — 34 lattice/bundle tests
- `tests/test_crud.py` — 5′ placement regression test
- Server auto-initializes with demo design on startup

### 3D Validation Checkpoints (confirmed)
- **V2.1** ✅: Scaffold direction correct per cell rule (FORWARD/REVERSE)
- **V2.2** ✅: 5′ cube at correct end (bp 0 for FORWARD, bp N-1 for REVERSE); tested via `test_geometry_five_prime_placement`
- **V2.3** ✅: Strand colors (scaffold=blue, staple=per-palette); two-click selection; right-click color override

---

## Phase 3 — Slice Plane (3D Layer Editor)

**Status: ✅ Complete — all V3.x checkpoints passed**

**Goal**: Enable adding helix segments at arbitrary axial positions by dragging a slice plane through the 3D scene.

### Delivered
- `frontend/src/scene/slice_plane.js` — semi-transparent plane + arrow drag handle, snaps to 0.334 nm grid
- `frontend/src/scene/workspace.js` — blank workspace + plane picker
- `frontend/src/scene/blunt_ends.js` — proximity-fade ring indicators at helix ends; click opens continuation mode
- Bundle continuation: `POST /design/bundle-continuation` extends existing strand domains for occupied cells; creates fresh scaffold+staple for new cells; correct FORWARD/REVERSE prepend/append topology
- Slice plane disabled when continuation mode active (no double-open)
- Slice plane auto-closes after extrusion
- `tests/test_crud.py` — bundle-continuation endpoint tested

### V3 Validation Checkpoints
- **V3.1** ✅ Slice plane snaps to 0.334 nm increments.
- **V3.2** ✅ Occupied cells shown amber in continuation mode.
- **V3.3** ✅ Extrude extends strands at correct axial position.

---

## Phase 4 — Staple Crossover Editor

**Status: ✅ Complete — 164/164 tests pass**

**Goal**: Enable staple crossovers between neighboring helices using true topological strand split+reconnect (caDNAno style). Crossover candidates appear as proximity-fading cyan cylinders; clicking one places a single backbone jump (half-crossover).

### DTP-4 (recorded 2026-03-11)
- Crossover placement uses geometrically pre-computed positions only (consistent with DTP-0b).
- Valid positions use `valid_crossover_positions()` with `direction_a`/`direction_b` tracking which strand direction is closest.
- **One cylinder per valid position** — off-by-1 positions (bp_a ≠ bp_b) are valid and shown; the earlier "companion" formula (bp±1) was geometrically incorrect (gives ~1.27nm gap, far above threshold).
- Clicking a cylinder places a **half-crossover** (one backbone jump). A DX motif forms naturally when two cylinders at different bp positions on the same pair are each clicked.
- No explicit "crossover mode" — proximity markers are always on.
- Scaffold strands are never affected by staple crossover placement.
- Loop strands (circular staple topology) render red; selecting one offers "Nick automatically" popup.

### Deliverables (complete)
- `backend/core/crossover_positions.py` — `CrossoverCandidate` with `direction_a`/`direction_b` fields
- `backend/core/lattice.py` — `make_staple_crossover()`, `make_half_crossover()`, `_find_strand_at()`
- `backend/core/validator.py` — `_is_loop_strand()`, `loop_strand_ids` in `ValidationReport`
- `backend/api/crud.py` — `GET /design/crossovers/all-valid`, `POST /design/staple-crossover`, `POST /design/half-crossover`, `_half_placed_flags()`
- `frontend/src/api/client.js` — `getAllValidCrossovers()`, `addHalfCrossover()`
- `frontend/src/scene/crossover_markers.js` — one cylinder per valid position, proximity fade, gold hover, click → half-crossover
- `frontend/src/scene/helix_renderer.js` — loop strand red rendering
- `frontend/src/scene/design_renderer.js` — passes `loopStrandIds` from store to renderer
- `frontend/src/state/store.js` — `loopStrandIds` state field
- `frontend/src/main.js` — loop strand popup (nick/leave)
- `tests/test_crossover_positions.py` — direction field correctness (3 tests)
- `tests/test_lattice.py` — `make_staple_crossover`, `make_half_crossover`, `_is_loop_strand` (23 new tests)
- `tests/test_crud.py` — all-valid, staple-crossover, half-crossover endpoint tests

### 3D Validation Checkpoints
- **V4.1**: Load a 2-helix bundle, hover near a helix pair. "Do cyan cylinders appear between the two helices where a crossover is geometrically possible?" ✅
- **V4.2**: Move cursor to within ~40px of a cylinder. "Does it turn gold and reach full opacity?" ✅
- **V4.3**: Click a gold cylinder. "Does the strand topology update (strand domains split and reconnect correctly)?" ✅

---

---

## Performance Roadmap (items 3–5)

*Items 1 (instanced rendering) and 2 (crossover position cache) were implemented
at the end of Phase 4.  The remaining items below are deferred; the recommended
trigger for each is noted.*

### Item 3 — Binary geometry transport
**Defer until**: designs routinely exceed 50 helices OR the geometry response
payload exceeds ~5 MB (measurable via browser DevTools Network tab).

Replace `GET /design/geometry` JSON response with a MessagePack or raw
`Float32Array` binary response.  At 14 400 nucleotides the JSON payload is
~3–6 MB; binary reduces this 3–4× and eliminates the JS JSON-parse cost.
Requires a small Vite plugin or custom fetch decoder on the frontend.

### Item 4 — Frustum culling + mousemove throttle for crossover markers
**Defer until**: crossover_markers.js is confirmed to cause frame drops
(>2 ms per mousemove event on a target machine with a large design loaded).

Two independent sub-tasks:
- Project-to-screen culling: skip `_toScreen()` for markers whose world position
  is outside the camera frustum (use `THREE.Frustum.containsPoint()`).
- mousemove throttle: gate `_updateOpacities()` to run at most once per
  `requestAnimationFrame` tick rather than on every raw mousemove event.

### Item 5 — Delta geometry for strand mutations
**Defer until**: Phase 5 (physics) or whenever `POST /design/staple-crossover`
or `POST /design/nick` latency is noticeable (>200 ms round-trip including
geometry refetch).

Add a `GET /design/geometry/delta?since=<version>` endpoint that returns only
nucleotides whose positions changed since the given design version.  The
frontend merges the delta into `currentGeometry` rather than replacing it.
Requires a monotonic version counter on the server-side Design object and a
per-nucleotide identity key (`helix_id + bp_index + direction`).

---

## Phase 5 — Physics Layer (XPBD + oxDNA Interface)

**Status: 🔧 Implementation complete — 188/188 tests pass — awaiting V5.x visual validation**

**DTP-5 Resolution (2026-03-12)**: Constraints: backbone bond length + excluded volume (Jacobi vectorised numpy). Angle constraints, electrostatics, base-pairing deferred. Numba JIT deferred until profiling shows need. Bond rest lengths derived from initial geometric positions (near-equilibrium start). Validated via `test_helix_remains_helical_after_relaxation`.

**Goal**: Real-time XPBD relaxation for feedback; batch oxDNA for validation.

### Deliverables (complete)
- `backend/physics/xpbd.py` — `SimState`, `build_simulation`, `xpbd_step` (Jacobi vectorised), `sim_energy`, `positions_to_updates`
- `backend/api/ws.py` — WebSocket `/ws/physics`: `start_physics` → stream at 10 fps; `stop_physics`; `reset_physics` rebuilds SimState from current design
- `backend/physics/oxdna_interface.py` — `write_topology`, `write_configuration`, `read_configuration`, `run_oxdna`, `write_oxdna_input`
- Frontend: `[P]` key / View > Toggle Physics — yellow sphere overlay at XPBD positions; white geometric positions always visible underneath (V5.1 overlay). Toggle off clears overlay exactly (V5.3).
- `frontend/src/physics/physics_client.js` — WebSocket client, start/stop/reset
- `frontend/src/state/store.js` — `physicsMode`, `physicsPositions` fields
- `frontend/src/scene/design_renderer.js` — `applyPhysicsPositions()` + yellow InstancedMesh overlay
- `tests/test_xpbd.py` — 24 tests: build_simulation, xpbd_step, sim_energy, positions_to_updates, oxDNA topology/configuration/round-trip/nucleotide-order

### 3D Validation Checkpoints
- **V5.1**: Single helix XPBD relaxation — before (white) and after (yellow) overlay. "Is the yellow helix still recognizably a helix?"
- **V5.2**: oxDNA round-trip — geometric positions (white) vs. read-back from oxDNA file (cyan). "Are any cyan spheres displaced from their white counterpart?"
- **V5.3**: Mode toggle — switch design↔physics 3 times. "Do positions change each time, and do design-mode positions return exactly?"

---

## Phase 6 — Bend & Twist Tooling, Part A: UI + Geometric Deformation

**Status: 🔵 Planned**

**Goal**: Add Bend and Twist tools under a new *Tools* menu. In this phase all deformation is geometric-layer only — the topological layer (strand graph, crossover positions, domain lengths) is unchanged. The user defines two cut planes, enters parameters in a popup, sees a live preview, and can chain multiple operations to create complex paths (V-shapes, S-curves, zigzags). No loop/skip base modifications are written to the model; that is Phase 7.

### DTP-6 Architecture Decisions (2026-03-12, binding)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DTP-6a: Deformation layer | Geometric-only (Part A) | Nail down UX before adding loop/skip topology |
| DTP-6b: Plane representation | Integer bp index, consistent across bundle | All bundle helices same length; bp-level snapping is sufficient |
| DTP-6c: Composition model | Ordered `Design.deformations` list; accumulated world frame | Enables chained V-shapes, zigzags; order is significant |
| DTP-6d: Fixed / mobile ends | Plane A (first selected) = fixed; Plane B translates | Matches extrude UX mental model |
| DTP-6e: Helix inclusion | All helices crossing both planes, included by default | Per-helix selection/deselection UI is a Phase 7 sub-task |
| DTP-6f: State persistence | Tool state (plane A + plane B positions) preserved across accidental Escape if design is unmodified | Prevents frustrating re-selection |
| DTP-6g: Bend direction input | Numeric degrees in popup + draggable SVG compass rose | No extra 3D click needed; 0° = +X direction in the plane perpendicular to the helix axis |
| DTP-6h: Undo | Each confirmed deformation op is one undo step via existing undo stack | Consistent with crossover placement and nick undo |

### New Model Types (`backend/core/models.py`)

```python
class TwistParams(BaseModel):
    total_degrees: float | None = None   # mutually exclusive
    degrees_per_nm: float | None = None  # positive = right-handed, negative = left-handed

class BendParams(BaseModel):
    radius_nm: float          # > 0; practical minimum ~6 nm (3×6 bundle, see Phase 7)
    direction_deg: float      # 0–360°; 0 = +X in the cross-section plane

class DeformationOp(BaseModel):
    id: str
    type: Literal['twist', 'bend']
    plane_a_bp: int           # Fixed plane (5′ side); must be < plane_b_bp
    plane_b_bp: int           # Mobile plane (3′ side)
    affected_helix_ids: list[str]   # populated automatically; editable later
    params: TwistParams | BendParams

# Design gains:
# deformations: list[DeformationOp] = []
```

### Geometric Deformation Module (`backend/core/deformation.py`)

**Twist math** — for segment `[p1, p2]`, at helix axis position `p` (in bp):

```
α(p) = total_twist_rad × (p − p1) / (p2 − p1)    (linearly interpolated)

For nucleotide at world position (x, y, z) where z encodes axial depth p:
  cx, cy = bundle centroid at plane p (from helix axes)
  x' = cx + (x−cx)·cos(α) − (y−cy)·sin(α)
  y' = cy + (x−cx)·sin(α) + (y−cy)·cos(α)
  z' = z
```

**Bend math** — constant-curvature arc in direction φ, radius R, from world frame at `p1`:

```
Arc length: s = (p − p1) × RISE_PER_BP    (nm from plane A)
Arc angle:  θ(s) = s / R                  (radians)
Direction unit vector: d̂ = (cos φ, sin φ, 0)

Axis world position at s:
  pos(s) = frame_p1.origin + R·sin(θ)·d̂ + (R·(1−cos(θ)))·ẑ  (in frame_p1 coords)

Local tangent:  t̂(s) = −sin(θ)·d̂ + cos(θ)·ẑ
Local normal:   n̂(s) = cos(θ)·d̂ + sin(θ)·ẑ
Local binormal: b̂(s) = cross(t̂, n̂)   (= −d̂⊥, the cross-section lateral axis)

Helix offset (Δx, Δy) in cross-section is rotated by local frame → world position.
Backbone/base bead vectors relative to helix axis are similarly rotated.
```

**Composition** — ops applied in `Design.deformations` order:
- Maintain an accumulated 4×4 rigid transform `world_frame` that updates at `plane_b_bp` of each op.
- Segments not spanned by any op: straight, inheriting the accumulated `world_frame`.
- `deformed_nucleotide_positions(helix, design)` → same interface as `nucleotide_positions(helix)`.
- The geometry endpoint transparently calls deformed version when `design.deformations` is non-empty.

**Key functions:**
- `compute_bundle_centroid(design, bp) → np.ndarray` — (x, y) centroid of helix axis points at bp
- `world_frame_at(design, bp) → Transform4x4` — accumulated frame from all ops up to `bp`
- `deformed_nucleotide_positions(helix, design) → list[NucleotidePosition]`

### API Endpoints (`backend/api/crud.py`)

| Method | Path | Action |
|--------|------|--------|
| `POST` | `/design/deformation` | Add op (body: DeformationOp without id). Returns updated design. Pushes to undo stack. |
| `PATCH` | `/design/deformation/{op_id}` | Update params only (for live preview). Does NOT push to undo stack. Returns updated design. |
| `DELETE` | `/design/deformation/{op_id}` | Remove op. Pushes to undo stack. |

### Frontend: Tools Menu (`frontend/index.html`, `frontend/src/main.js`)

New `<div class="dropdown">` between Edit and View:
```html
<button class="menu-btn" id="menu-tools">Tools ▾</button>
<div class="dropdown-menu" id="dropdown-tools">
  <button class="dropdown-item" id="menu-tools-twist">Twist…</button>
  <button class="dropdown-item" id="menu-tools-bend">Bend…</button>
</div>
```

### Frontend: Deformation Editor (`frontend/src/scene/deformation_editor.js`)

**State machine:**
```
IDLE
  → [Tools > Bend/Twist]   → AWAITING_PLANE_A

AWAITING_PLANE_A
  → [hover helix axis]     → ghost plane rectangle drawn normal to that helix axis, snapped to nearest bp; axis arrow glows
  → [click helix axis]     → PLANE_A_PLACED  (plane A solidifies, yellow-white, slice-plane style)
  → [click blunt-end ring] → PLANE_A_PLACED  (snaps to terminus bp)
  → [Escape]               → IDLE (preserve A+B state if design unmodified)

PLANE_A_PLACED
  → [hover beyond plane A] → ghost plane B follows cursor (orange ghost); only positions > plane_a_bp shown
  → [click]                → BOTH_PLANES_PLACED  (plane B solidifies, orange border)
  → [Escape]               → IDLE (preserve A position)

BOTH_PLANES_PLACED
  → popup opens automatically
  → [Preview ON + param input] → PATCH /design/deformation (ephemeral, no undo push) → geometry redraws
  → [Preview OFF]              → PATCH with identity params to clear preview
  → [Confirm]                  → POST /design/deformation (committed, undo push) → IDLE
  → [Cancel]                   → DELETE ephemeral preview op if one exists → PLANE_A_PLACED
  → [Escape]                   → same as Cancel
```

**Visual modes when tool is active:**
- All geometry: opacity → 0.2 (instanced mesh + cones)
- Helix axis arrows: scale 2×, opacity 1.0, color #aaddff
- Affected helices (crossing both planes): full opacity highlight during BOTH_PLANES_PLACED
- Plane A: yellow-white semi-transparent rect, thick white border (matches slice plane)
- Plane B: orange semi-transparent rect, thick orange border
- Ghost planes: thin dashed rect, animated pulse, 50% transparent

### Frontend: Parameter Popup (`frontend/src/ui/bend_twist_popup.js`)

**Twist popup:**
```
┌─ Twist ──────────────────────────────────────────────────── × ─┐
│  ○ Total degrees:  [______] °                                   │
│  ● Degrees per nm: [______] °/nm                                │
│  Direction: [−] Left-handed  [+] Right-handed                   │
│  ☑ Preview                                                      │
│  [Cancel]                              [Apply Twist]            │
└─────────────────────────────────────────────────────────────────┘
```

**Bend popup:**
```
┌─ Bend ───────────────────────────────────────────────────── × ─┐
│  Radius of curvature: [______] nm                               │
│  Bend direction:  [______] °   [SVG compass rose — draggable]   │
│  ☑ Preview                                                      │
│  [Cancel]                               [Apply Bend]            │
└─────────────────────────────────────────────────────────────────┘
```

Compass rose: a small SVG circle with a draggable arm; dragging updates the numeric input and vice versa. 0° = +X (east in cross-section view), increases counterclockwise.

### 3D Validation Checkpoints

- **V6.1 Twist gradient**: Apply 180° twist over a full bundle. "Does the far end appear rotated 180° from the near end, with a smooth continuous rotation between?"
- **V6.2 Bend arc**: Apply 90° bend, R=20 nm. "Does the bundle axis trace a quarter-circle? Does the cross-section remain perpendicular to the local tangent throughout?"
- **V6.3 Composition — V-shape**: Straight → 90° bend → straight. "Does the second straight segment extend perpendicular to the first? Are helix positions in the second segment correct?"
- **V6.4 Composition — S-curve**: Two 45° bends in opposite directions. "Does the shape resemble an S with smooth transitions at both planes?"
- **V6.5 Live preview**: Drag the bend direction compass. "Does the 3D view update in real-time, continuously tracking the input?"
- **V6.6 Undo**: Apply a twist, then Ctrl+Z. "Does the geometry return exactly to the pre-twist state?"

---

## Phase 7 — Bend & Twist Tooling, Part B: Topological Loop/Skip Implementation

**Status: ✅ Complete — 429/429 tests passing (master, 2026-03-30)**

**Goal**: Translate geometric deformation parameters into actual loop/skip base modifications in the topological layer, following the mechanism established in Dietz, Douglas & Shih (*Science* 2009). After this phase, applying a bend or twist modifies domain lengths, generates loop/skip markers at specific bp positions, and invalidates + regenerates the staple crossover positions.

### Deliverables (complete 2026-03-23)

- `backend/core/models.py` — `LoopSkip(bp_index, delta)` model; `Helix.loop_skips` field
- `backend/core/geometry.py` — `nucleotide_positions()` updated to skip/loop bp positions (accumulated delta, multi-skip/loop support)
- `backend/core/loop_skip_calculator.py` — `twist_loop_skips()`, `bend_loop_skips()`, `apply_loop_skips()`, `clear_loop_skips()`, `predict_global_twist_deg()`, `predict_radius_nm()`, `min_bend_radius_nm()`, `max_twist_deg()`, `validate_loop_skip_limits()`; gap-aware per-helix active-interval filtering; centroid from active-DNA helices only
- `backend/core/deformation.py` — `deformed_nucleotide_positions()` and `deformed_helix_axes()` use global bp indices (fixes scaffold collapse when `bp_start ≠ 0`)
- `backend/api/crud.py` — `POST /design/loop-skip/twist`, `POST /design/loop-skip/bend`, `GET /design/loop-skip/limits`, `DELETE /design/loop-skip`; `design=design` passed to `twist_loop_skips` / `bend_loop_skips` for gap-aware placement
- `tests/test_loop_skip.py` — 54 tests covering model, geometry, calculator, API helpers, gap-domain multi-helix designs
- `experiments/exp10_twist_loop_skip/` — **PASS**: R² = 0.9999, max residual = 16.8° ≤ 34.3°, Dietz 10/11 bp/turn calibration verified
- `experiments/exp11_bend_loop_skip/` — **PASS**: R_min = 5.25 nm (vs Dietz ~6 nm), mean relative error 3.5%, limit enforcement verified

### Key DTP-7 Decisions (2026-03-13, binding)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DTP-7a: Modification granularity | One `LoopSkip` entry per bp per helix | Matches caDNAno convention; multiple entries accumulate (delta summed) |
| DTP-7b: Distribution algorithm | Bresenham per-cell counts + intra-cell spread | No rounding accumulation; 3 del/cell maximum respected at all scales |
| DTP-7c: Limit enforcement | 6 ≤ T ≤ 15 bp/turn per cell at every helix | Direct from Dietz paper; raises ValueError before applying mods |
| DTP-7d: Predict-first approach | `predict_*()` functions for round-trip verification | Enables unit tests and UI feedback without physics simulation |
| DTP-7e: Large-R fallback | Return empty mods if Δ_bp < 1 for all helices | Avoids spurious zero-modification designs; UI should suggest geometric deformation |

### Experimental findings (binding)

- **Twist accuracy**: ±34.3°/2 = ±17° maximum rounding error. Users should be shown the quantized actual twist that will result.
- **Bend accuracy**: < 2% for R ≤ 30 nm (practical regime). Degrades to ≈18% at R = 100 nm due to integer rounding with few total modifications.
- **R_min formula**: `R_min = 7 × r_max / 3` (nm), where r_max is the bundle's maximum cross-section extent in the bend direction. Agrees with Dietz to within 14%.
- **Gradient twist cancellation**: The inner-deletion/outer-insertion pattern inherently cancels net twist, yielding near-pure bend. Residual twist is proportional to inner/outer modification count asymmetry from rounding.

### 3D Validation Checkpoints

- **V7.1 Twist topology**: Apply +205.7° twist to a 6-helix bundle. Inspect loop/skip markers. "Do exactly 6 deletions per helix appear, 1 per 3 cells, as in the Dietz 10 bp/turn design?" ✓ (confirmed in exp10)
- **V7.2 Bend topology**: Apply 90° bend R=20 nm to 6HB. "Do inner-face helices show deletions and outer-face helices show insertions in correct proportions?" ✓ (confirmed multi_domain_test3 2026-03-23)
- **V7.3 Geometry update**: After applying loop/skips, "do nucleotide positions correctly omit skipped bp and add extra nucleotides for loops?" ✓ (54 geometry tests)
- **V7.4 Staple re-routing**: After topology write, trigger autostaple. "Do crossover positions update to account for modified cell lengths?" ✓ (confirmed 2026-03-23)
- **V7.5 Multi-domain gap designs**: In a design with a gap in the bend plane, only connector helices (spanning the gap) receive mods; outer helices with no DNA in the bend plane correctly receive zero mods. ✓ (confirmed multi_domain_test3 2026-03-23)

### Physical Mechanism (from literature)

B-DNA baseline: 10.5 bp/turn, 34.3°/bp, 0.335 nm/bp rise. In a honeycomb bundle, consecutive crossover planes are spaced 7 bp apart (7 × 34.3° = 240° = one crossover-neighbor angular interval). Each **array cell** (7-bp segment between adjacent crossover planes) is the atomic unit of modification.

- **Deletion** (skip, −1 bp per cell): cell spans 6 bp over same 240° → effectively ~9 bp/turn locally → overtwisted → left-handed torque + tensile strain (bends inward / twists left)
- **Insertion** (loop, +1 bp per cell): cell spans 8 bp → ~12 bp/turn → undertwisted → right-handed torque + compressive strain (bends outward / twists right)
- **Uniform mods across all cross-section positions** → global twist, bending contributions cancel
- **Gradient across cross-section** → global bend, torsional contributions cancel; steeper gradient = smaller radius

### Loop/Skip Computation Theory

**Target twist density from user input:**
```
θ_natural = 360 / 10.5 = 34.286 °/bp  (= 102.35 °/nm)
θ_target_per_bp = θ_natural + twist_total_deg / N_bp_in_segment
T_target (bp/turn) = 360 / θ_target_per_bp
```

**Per-cell modification (uniform twist):**
```
ideal_cell_length = 7 × T_target / 10.5
Δ = round(ideal_cell_length) − 7   ∈ {−1, 0, +1} for mild twists
# Mix of floor/ceil for fractional Δ:
n_mod_cells = round(|7 × T_target/10.5 − 7| × N_cells)  (evenly spaced)
```

**Bend — helix-specific twist density:**
```
For helix at cross-sectional offset r (nm) from bundle centroid in direction φ:
  κ = 1/R  (desired curvature, nm⁻¹)
  Δ_θ_per_nm(r) = κ × r × θ_natural   (extra/missing °/nm at this radial position)
  T_helix(r) = T_natural + Δ_θ_per_nm × 0.335 / 360 × 10.5   (bp/turn)
```
Constraint: 6 ≤ T_helix ≤ 15 bp/turn. Violation → error: "bend too tight for this cross-section width; minimum radius is X nm."

**Minimum achievable radius** for a bundle of cross-section half-width W (nm):
```
R_min = W / (15/10.5 − 1) = W / 0.429   (inner at 15 bp/turn, outer at 6 bp/turn)
For 3-row honeycomb (W ≈ 2 × 2.25 = 4.5 nm):  R_min ≈ 6 nm  (matches paper)
```

### Domain Model Changes Required (Phase 7)

```python
class LoopSkip(BaseModel):
    bp: int                          # position within domain (0-indexed from domain start_bp)
    delta: Literal[-1, +1]           # +1 = insertion (loop), -1 = deletion (skip)

# Domain gains:
# loop_skips: list[LoopSkip] = []
```

- `nucleotide_positions(helix)` must accumulate bp offset shifts from loop_skips
- `valid_crossover_positions(h_a, h_b)` recomputes for helices with loop/skips
- Crossover markers need to update after any deformation-topology write
- Autostaple must handle non-uniform cell lengths
- Per-helix selection/deselection UI for the affected helix set (deferred from Phase 6)

### 3D Validation Checkpoints (Phase 7)

- **V7.1 Twist topology**: Apply +360°/10 helices twist. Inspect loop/skip markers in properties panel. "Do 10 deletions appear, evenly spaced along the affected helices?" ✓
- **V7.2 Bend topology**: Apply 90° bend R=20 nm to 6HB. "Do inner-face helices show deletions and outer-face helices show insertions in the correct proportions?" ✓
- **V7.3 oxDNA validation**: Export bent structure to oxDNA, run minimization. "Does the equilibrium bend angle match the target within 10°?" (deferred to Phase 9)
- **V7.4 Staple re-routing**: After topology write, trigger autostaple. "Do crossover positions update to account for the modified cell lengths?" ✓
- **V7.5 Gap-domain mods**: Bend multi-domain design. "Only connector helices with DNA in the bend plane receive mods; gap helices receive zero mods." ✓

---

## Phase S — Sequence, View Enhancements, and Export  (2026-03-16)

**Status: ✅ Shipped (2026-03-18) — basic scaffold/staple routing considered production-ready for standard structures. Edge cases (very short helices, non-standard topologies) deferred to later testing phase.**

**Goal**: Assign real DNA sequences to scaffold and staples, provide sequence visualization, improve the scaffold routing end-treatment, add staple isolation and hide/show controls, extrude filter, manual loop/skip insertion, and caDNAno-format sequence export.

### Feature S1 — Scaffold End Loops
**Status: ✅ Complete**

Currently `auto_scaffold` starts the scaffold `nick_offset` bp away from the helix-1 terminal, leaving the terminus covered only by a staple fragment. This causes blunt-end stacking and potential aggregation.

**Change**: Add `scaffold_loops=True` parameter to `auto_scaffold`. When True, the 5′ end of the scaffold is placed at bp 0 (FORWARD) or bp N-1 (REVERSE) of helix 1, so the terminal base pairs are single-stranded scaffold (ss-DNA loop). The 3′ end is already at the physical terminus of the last helix.

`nick_offset` is repurposed as `loop_length` in the UI — it controls the count of ss-DNA loop bases shown as a convenience number, but the scaffold domain always extends to bp 0.

**Files**: `backend/core/lattice.py`, `backend/api/crud.py`, `frontend/index.html` (autoscaffold modal checkbox).

### Feature S2 — Scaffold Sequence Assignment (m13)
**Status: ✅ Complete**

`backend/core/sequences.py` — M13MP18_SEQUENCE (7249 nt, standard caDNAno ordering). `assign_scaffold_sequence(design, start_offset=0)` assigns consecutive bases from M13MP18_SEQUENCE to the scaffold strand 5′→3′. Each base position in each domain gets one nucleotide from the sequence. Circular wrap at 7249.

**API**: `POST /design/assign-scaffold-sequence  body: {start_offset: 0}` — updates scaffold strand sequence field. Undo pushes.

### Feature S3 — Staple Sequence Assignment
**Status: ✅ Complete**

`assign_staple_sequences(design)` — for each staple strand, derive its sequence as the Watson-Crick complement of the scaffold bases at the same (helix_id, bp_index) positions. Staple strands that cover positions not on the scaffold get `N` (unknown).

**API**: `POST /design/assign-staple-sequences` — assigns sequence to all staple strands. Requires scaffold sequence to be assigned first (returns 422 otherwise). Undo pushes.

### Feature S4 — View Sequences Overlay
**Status: ✅ Complete** — InstancedMesh per letter (A/T/G/C/N); 5 draw calls; unfold view support via `applyUnfoldOffsets` (2026-03-18)

View menu toggle **View > View Sequences** (id `menu-view-sequences`). When on:
- `frontend/src/scene/sequence_overlay.js` creates CSS2DObject labels (or Three.js sprites) per nucleotide showing its letter (A/T/G/C or `?`)
- Bases with unassigned sequence render in red (#ff4444); assigned bases in bright white
- Toggle off removes all labels

State: `store.sequencesVisible` (bool, default false).

### Feature S5 — Isolate Staple Strand
**Status: ✅ Complete**

Right-click context menu item **Isolate** appears when a staple strand is selected (mode = 'strand', not scaffold). Clicking it sets `store.isolatedStrandId = strand_id` which causes `design_renderer.js` to render all OTHER staple strands at opacity 0.05 (ghosted). A second menu item **Un-isolate** (or keyboard Escape) restores visibility.

Feature 7 (hide all staples) overrides/resets isolation.

### Feature S6 — Extrude Filter (Scaffold / Staples / Both)
**Status: ✅ Complete**

The extrude panel (`extrude_panel.js`) gets three radio buttons: **Both** (default), **Scaffold only**, **Staples only**. The selection is passed as `extrude_filter` in the onExtrude callback and forwarded to the API as `strand_filter: "both"|"scaffold_only"|"staples_only"` on `POST /design/bundle-segment` and `/bundle-continuation`.

**Backend**: `make_bundle_segment` and `make_bundle_continuation` accept optional `strand_filter` argument:
- `"scaffold_only"` — only scaffold domains are created/extended; no staple strands added
- `"staples_only"` — only staple strands created; existing scaffold is NOT extended
- `"both"` — current behavior

### Feature S7 — Hide / Show All Staples
**Status: ✅ Complete**

View menu toggle **View > Hide Staples** (id `menu-view-hide-staples`). When on:
- `store.staplesHidden = true`
- `design_renderer.js` sets all non-scaffold strand instances invisible
- Overrides and resets `isolatedStrandId`

### Feature S8 — Manual Loop / Skip Insertion
**Status: ✅ Complete**

When a **backbone bead is selected** (mode = 'nucleotide'), the right-click context menu gains two items:
- **Add Loop here** — inserts a +1 LoopSkip at `bead.bp_index` on `bead.helix_id`
- **Add Skip here** — inserts a −1 LoopSkip at `bead.bp_index` on `bead.helix_id`

**API**: `POST /design/loop-skip/insert  body: {helix_id, bp_index, delta}` — adds a LoopSkip to the helix model. Undo pushes.

**Backend**: `insert_loop_skip(design, helix_id, bp_index, delta)` in `loop_skip_calculator.py` — merges the new LoopSkip into `helix.loop_skips` (sorted, no duplicates).

### Feature S9 — caDNAno Sequence Export
**Status: ✅ Complete**

`GET /design/export/sequence-csv` — returns a CSV file with one row per staple strand, columns matching caDNAno's export format:

| Column | Content |
|--------|---------|
| Strand | strand index (1-based) |
| Sequence | strand sequence 5′→3′ (or blank if unassigned) |
| Length | strand length in nt |
| Color | strand color hex |
| Start Helix | helix_id of first domain |
| Start Position | 5′ bp index |
| End Helix | helix_id of last domain |
| End Position | 3′ bp index |

**Frontend**: File > Export > Sequences (CSV) menu item triggers browser download.

### Feature S10 — Autostaple Stage 3: Auto Merge
**Status: ✅ Complete (2026-03-18)**

After Stage 2 nicking (≤60 nt), a third pass re-merges adjacent same-helix staple pairs whose combined length ≤ 56 nt (≤ 8×7), provided the merge does not violate the sandwich rule (no interior domain shorter than both its neighbours).

- `make_merge_short_staples(design, max_merged_length=56)` in `backend/core/lattice.py`
- Greedy, longest-first; iterates until no more merges are possible
- Merge detection: `(helix_id, bp, direction)` 5′-index lookup; match on `last.end_bp ± 1` same-helix
- `POST /design/auto-merge` endpoint; **Tools > Auto Merge** menu item

### Feature S11 — Camera Centering on Histogram Strand Selection
**Status: ✅ Complete (2026-03-18)**

When a strand is highlighted by clicking the strand-length histogram bar, the 3D camera orbit target is immediately shifted to the centroid of that strand's backbone positions, preserving camera distance and direction.

- `_centerOnStrand(strandId)` helper in `main.js`; called after `selectionManager.selectStrand()`
- Algorithm: `dist = camera.position.distanceTo(controls.target)`; `dir = (camera − target).normalize()`; `new camera = centroid + dir × dist`

### Bugfix — Prebreak Grid Anchoring for Scaffold-Extended Helices
**Status: ✅ Fixed (2026-03-18)**

`scaffold_extrude_near` shifts all staple bp indices by N (extension length). The old `make_prebreak` always started its 7-bp grid at bp 6/7, creating short stub fragments (4 nt and 3 nt) on extended helices.

- `make_prebreak` now computes `staple_low[(helix_id, direction)]` = minimum staple bp per helix/direction, then anchors the prebreak grid to `low_bp + 6/7`
- `_ligation_positions_for_pair` accepts an `offset` parameter; `make_auto_crossover` passes the per-pair minimum staple bp as offset, keeping ligation positions aligned with the shifted prebreak grid

### Questions for user (before implementing S1 details)

1. **Scaffold loops on internal helices**: In seam-line mode, the scaffold crosses between helices mid-helix, so the helix termini of internal helices are covered only by staple strands. Should the scaffold be routed through helix termini in seam-line mode (requires algorithmic changes), or is ss-DNA only at the structural 5′/3′ ends (h1 and h_last) sufficient?

2. **Extrude filter**: When "Scaffold only" is selected, should the crossover markers still be shown and clickable so the user can manually place staple crossovers after extruding?

3. **Manual loop/skip**: Should the loop/skip be inserted at the exact bp the user clicked, or snapped to a 7-bp-period boundary (like the automatic tool)?

---

## Phase 8 — Parts Library and Assembly CAD

*(Previously Phase 6 — pushed to accommodate Bend/Twist tooling)*

**Status: 🔵 Planned (branch `phase-8-assembly`)**

**Goal**: Store validated designs as `Part` objects in a local SQLite library; compose
multi-part assemblies by snapping blunt-end interface points together; manage cross-part
sequence continuity and export full assembly as a single caDNAno/PDB file.

---

### DTP-8 (resolved): Interface point placement

Blunt-end interface points are derived algorithmically from helix terminus geometry:
- `normal` = helix axis tangent (unit vector from `axis_start` → `axis_end`)
- `position` = average backbone bead position of the terminal bp
- Manual specification only for non-blunt connections (toeholds, biotins, covalent bonds)

This guarantees sub-degree angular accuracy for clockwork assemblies without user input.

---

### Sub-phase 8-A: Parts Library Backend

**Branch deliverable**: Save/load/search design variants as `Part` records.

#### 8-A-1: `backend/library/` package

```
backend/library/
  __init__.py
  database.py      — SQLModel schema + engine init
  models.py        — Part, InterfacePoint ORM models
  crud.py          — save_part, list_parts, get_part, delete_part
  matcher.py       — find_matching_parts(cross_section, length_range, lattice_type)
```

**`Part` schema**:
```python
class Part(SQLModel, table=True):
    id:          str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name:        str
    description: str = ""
    design_json: str          # full Design serialized as JSON string
    lattice_type: str         # "honeycomb" | "square"
    helix_count:  int
    length_bp:    int         # max domain length in design
    tags:         str = ""    # comma-separated
    created_at:   datetime = Field(default_factory=datetime.utcnow)
    updated_at:   datetime = Field(default_factory=datetime.utcnow)
```

**`InterfacePoint` schema**:
```python
class InterfacePoint(SQLModel, table=True):
    id:        str = Field(primary_key=True)   # e.g. "iface_h_0_0_3p"
    part_id:   str = Field(foreign_key="part.id")
    helix_id:  str
    end:       str   # "5p" | "3p"
    pos_x:     float
    pos_y:     float
    pos_z:     float
    normal_x:  float
    normal_y:  float
    normal_z:  float
    strand_type: str  # "scaffold" | "staple" | "both"
```

Interface points are auto-derived at save time from terminal helix geometry.

#### 8-A-2: REST endpoints (`backend/api/library.py`)

```
POST   /library/part               — save current active design as a Part
GET    /library/parts              — list all Parts (lightweight, no design_json)
GET    /library/part/{id}          — full Part with embedded design_json
DELETE /library/part/{id}          — remove
PUT    /library/part/{id}          — update name/description/tags
POST   /library/part/{id}/load     — set as active design (replaces singleton)
GET    /library/part/{id}/interfaces — list InterfacePoints
POST   /library/parts/search       — find by cross_section, lattice, length_range
```

#### 8-A-3: Frontend Library Panel

Sidebar panel "Library" between Overhangs and Physics:
- Save button → dialog: name, description, tags
- Searchable list with helix_count + length_bp badges
- "Load" per row → replaces active design
- "Use in Assembly" per row → opens Assembly View

**Validation checkpoint V8-A.1**: Load a saved Part → design renders correctly; helix count and structure match original.

---

### Sub-phase 8-B: Interface Point System

**Branch deliverable**: Visualise and interact with blunt-end interface points.

#### 8-B-1: `backend/core/interface_points.py`

```python
def compute_interface_points(design: Design) -> list[InterfacePointData]:
    """
    Returns one InterfacePointData per terminal helix end (5p/3p).
    position = mean of last-bp backbone bead positions across all strands on that helix end.
    normal   = normalised axis_end - axis_start.
    """
```

Returns `InterfacePointData(helix_id, end, position: np.ndarray, normal: np.ndarray, strand_type)`.

#### 8-B-2: `GET /design/interface-points` endpoint

Returns list of interface points for the active design. Called by the frontend blunt-ends overlay.

#### 8-B-3: `frontend/src/scene/interface_points.js`

- Render each interface point as a coloured double-cone (like a spindle):
  - Scaffold terminus: red
  - Staple terminus: blue
  - Both: white
- Scale: 1.5× normal bead radius
- Click → select, show details in sidebar (helix, end, coordinates)

**Validation checkpoint V8-B.1**: Single helix → both terminal cones rendered at correct positions pointing outward along helix axis.

---

### Sub-phase 8-C: Assembly View

**Branch deliverable**: Compose multiple Parts into a multi-part assembly in a dedicated view.

#### 8-C-1: Assembly data model (`backend/core/assembly.py`)

```python
@dataclass
class PartInstance:
    instance_id:  str              # uuid
    part_id:      str
    design:       Design           # embedded (no DB query per frame)
    transform:    np.ndarray       # 4×4 homogeneous matrix (rotation + translation)
    connections:  list[Connection] # interface point pairs

@dataclass
class Connection:
    a_instance_id: str
    a_iface_id:    str
    b_instance_id: str
    b_iface_id:    str

@dataclass
class Assembly:
    id:        str
    name:      str
    instances: list[PartInstance]
    connections: list[Connection]
```

Assembly singleton stored in `backend/api/assembly_state.py` (same pattern as design singleton).

#### 8-C-2: REST endpoints (`backend/api/assembly.py`)

```
POST   /assembly/instance          — add Part instance to assembly {part_id}
DELETE /assembly/instance/{id}     — remove instance
POST   /assembly/connect           — snap two interface points {a_instance, a_iface, b_instance, b_iface}
DELETE /assembly/connection/{idx}  — remove connection
GET    /assembly                   — full assembly state (all instances + transforms + connections)
GET    /assembly/export/cadnano    — merge all instances → single caDNAno JSON (HC only)
GET    /assembly/export/pdb        — merge all instances → single PDB (all lattices)
```

#### 8-C-3: Frontend Assembly View (`frontend/src/views/assembly_view.js`)

- Activated via "Assembly" menu item or hotkey `[A]`
- Separate Three.js scene overlaid on main viewport (same canvas, separate render pass)
- Each Part instance rendered in its own colour tint (using `strandColors` per instance)
- Interface point spindles shown; selected pair highlighted yellow
- "Snap" button after selecting two interface points:
  - Computes rigid transform aligning B's selected iface normal antiparallel to A's
  - Applies `PUT /assembly/instance/{id}/transform`
- Drag to reposition un-snapped instances (translate along ground plane)
- Connection lines drawn as thick white cylinders between connected iface pairs

**Validation checkpoint V8-C.1**: Two 6HB blunt ends — snap produces correct alignment; helix axes coplanar, normals antiparallel, backbones ~2 nm apart.

---

### Sub-phase 8-D: Cross-Part Sequence Management

**Branch deliverable**: Assign M13 scaffold across part boundaries; propagate staple sequences.

#### 8-D-1: Scaffold continuity

When two scaffold termini are connected (5′ of Part B connects to 3′ of Part A):
- `POST /assembly/assign-scaffold-sequence` runs M13 assignment treating the assembly
  as a single linear scaffold: Part A scaffold → junction → Part B scaffold → ...
- Requires topological order of instances along scaffold path (user or auto from connection graph)

#### 8-D-2: Staple sequences

`POST /assembly/assign-staple-sequences` runs complementary assignment over all instances
using merged scaffold sequence map.

#### 8-D-3: Sequence export

`GET /assembly/export/sequence-csv` exports all staples across all instances with Part name prefix.

**Validation checkpoint V8-D.1**: 2-Part assembly (both 18HB) → scaffold sequence spans both; staple CSV contains Part A + Part B staples with no duplicates.

---

### Sub-phase 8-E: Assembly Export

**Branch deliverable**: Export the full multi-part assembly as a single file.

#### 8-E-1: caDNAno export

`GET /assembly/export/cadnano` — transforms all Part helix positions by instance transform,
remaps helix IDs to avoid collisions, merges into a single caDNAno JSON. HC only.

#### 8-E-2: PDB export

`GET /assembly/export/pdb` — runs atomistic pipeline on each Part in its transformed frame;
concatenates MODEL records. Supports HC and SQ lattices.

#### 8-E-3: oxDNA export

`GET /assembly/export/oxdna` — generates topology + configuration files for multi-part assembly.

**Validation checkpoint V8-E.1**: 2-Part 6HB assembly export → load in Chimera/PyMOL; visual check that helices are positioned correctly relative to each other.

---

### 3D Validation Checkpoints (summary)

| Checkpoint | What to check |
|-----------|---------------|
| V8-A.1 | Saved/loaded Part renders correctly |
| V8-B.1 | Interface point cones at correct terminal positions, pointing outward |
| V8-C.1 | Snap produces correct blunt-end alignment (antiparallel normals, ~2 nm gap) |
| V8-D.1 | Scaffold sequence spans both Parts; staple CSV complete |
| V8-E.1 | Multi-part PDB renders correctly in molecular viewer |

---

### Implementation order

1. **8-A** (Library backend + panel) — standalone, no assembly logic
2. **8-B** (Interface points) — depends on 8-A geometry; needed before snap
3. **8-C** (Assembly view) — depends on 8-A + 8-B
4. **8-D** (Sequence continuity) — depends on 8-C connection graph
5. **8-E** (Export) — depends on 8-C transform state

---

## Phase 9 — Checker Integrations

*(Previously Phase 7)*

**Goal**: Close the validation loop with oxDNA minimization, CanDo, SNUPI.

### Deliverables
- `backend/checkers/oxdna_checker.py` — minimization job + `ValidationRecord` update
- `backend/checkers/cando_checker.py` — CanDo API integration
- `backend/checkers/snupi_checker.py` — local SNUPI binary wrapper
- Checker panel: status rows per checker, run buttons, result summaries

### 3D Validation Checkpoints
- **V9.1**: oxDNA RMSD heat map — green→yellow→red per nucleotide. "Are high-RMSD nucleotides at expected locations (crossovers, termini)?"
- **V9.2**: CanDo flexibility map — blue→red RMSF heat map. "Do flexible regions match design intent?"

---

## Phase SEQ — Sequencing (2026-03-18)

**Status: 🔧 In progress (branch `sequencing`)**

**Goal**: Correct sequence assignment and overlay rendering. The scaffold sequence is assigned starting from the scaffold's existing 5′ terminus (no manual offset). The sequence overlay renders letters co-incident with their base beads. Staple sequences follow as Watson-Crick complements.

### Feature SEQ-1 — Scaffold sequence uses native 5′ start
The `assign_scaffold_sequence` API no longer requires a `start_offset` parameter. The offset into M13MP18 is always 0, meaning the first scaffold base (5′ terminus) receives M13[0]. The user cannot specify an offset — the 5′ end is the source of truth. (`backend/core/sequences.py`, `backend/api/crud.py`)

### Feature SEQ-2 — Sequence overlay position fix
Sequence letter sprites/instanced meshes in `sequence_overlay.js` must be placed at the **base bead position** (`base_position` from `NucleotidePosition`), not at the backbone bead or some other derived point. Positions are read from the geometry response (`/api/design/geometry`). A 3D validation checkpoint is required before this is marked complete.

### 3D Validation Checkpoints
- **VSEQ.1**: Sequence overlay — toggle on with a sequenced design. "Does each letter sit directly on its base bead?"

---

## Cross-Cutting: Documentation Protocol

At end of each phase, before marking complete:
1. Update `MEMORY.md` with confirmed conventions from validation checkpoints
2. Create/update topic file in `memory/` for phase-specific notes
3. Update `README.md` with current feature set
4. Record any DTP decisions in `memory/architecture_decisions.md`

## Cross-Cutting: Anti-Drift Rule

Each phase's validation checkpoints must be signed off before Phase N+1 begins. A failed checkpoint means the phase is incomplete, regardless of how much else is done.

---

## Phase SQ — Square Lattice Support

**Status: 🔵 In progress (branch `square-lattice`, 2026-03-18)**

**Goal**: Full support for square-lattice DNA origami designs alongside the existing honeycomb lattice.  Every existing feature (crossover placement, auto-scaffold, auto-staple, sequence assignment, physics, bend/twist, loop/skip, overhang extrusion, groups, lasso selection, CSV export) must correctly detect the design's lattice type and adapt its parameters accordingly.

### Design decisions (DTP-SQ, binding)

| ID | Decision | Rationale |
|----|----------|-----------|
| DTP-SQ-a | Lattice type stored on `Design`, not per-helix | All helices in one design share a single lattice; mixed-lattice assemblies are Phase 8 |
| DTP-SQ-b | Square twist = 30°/bp (12 bp/turn, 2 turns/24 bp) | User specification; slight under-winding relative to B-form |
| DTP-SQ-c | Crossover period = 8 bp | User specification; 4 neighbor directions, one crossover slot per direction per 8 bp window |
| DTP-SQ-d | Helix spacing = 2.6 nm | Already in `constants.py` as `SQUARE_HELIX_SPACING`; row pitch = col pitch = 2.6 nm |
| DTP-SQ-e | Cell validity rule: `(row + col) % 2 != 2` (all cells valid), direction: `(row + col) % 2` → 0=FORWARD, 1=REVERSE | Ensures all 4 adjacent neighbors are antiparallel |
| DTP-SQ-f | Prebreak domain length = 8 bp (vs 7 bp honeycomb) | Matches crossover period |
| DTP-SQ-g | Min end margin = 8 bp for auto-staple (vs 9 bp honeycomb) | Scaled to crossover period |
| DTP-SQ-h | `File > New` shows a lattice-picker dialog; lattice stored in `Design.lattice_type` | Already implemented: dialog selects HONEYCOMB or SQUARE |

### Square lattice geometry constants (add to `constants.py`)

```python
SQUARE_TWIST_PER_BP_DEG: float = 30.0          # 360 / 12 bp/turn
SQUARE_TWIST_PER_BP_RAD: float = math.radians(30.0)
SQUARE_BP_PER_TURN: float      = 12.0
SQUARE_CROSSOVER_PERIOD: int   = 8             # bp between crossover slots
SQUARE_ROW_PITCH: float        = 2.6           # nm (= SQUARE_HELIX_SPACING)
SQUARE_COL_PITCH: float        = 2.6           # nm (= SQUARE_HELIX_SPACING)
```

### Crossover position scheme for square lattice

Each helix has **4 neighbor directions**: N (row−1), S (row+1), W (col−1), E (col+1).  
Within each 8 bp period, each direction gets **one crossover slot** at a fixed phase offset:

| Direction | Phase angle | bp offset in 8-bp period |
|-----------|-------------|--------------------------|
| W (left)  |   0°        | 0                        |
| N (up)    |  90°        | 3                        |
| E (right) | 180°        | 4 (half-period)          |
| S (down)  | 270°        | 6                        |

*Exact offsets to be confirmed by 3D geometric validation checkpoint VSQ.1.*

Crossover positions along a helix of length L:  `{offset + k×8 | k = 0,1,2,… ; offset+k×8 < L−min_margin}`

For a REVERSE helix the sense of N/S/E/W flips (or the FORWARD partner's table is consulted); adopt the honeycomb convention of always querying from the lower-indexed helix.

### Files to create / modify

| File | Change |
|------|--------|
| `backend/core/constants.py` | Add SQUARE_* constants |
| `backend/core/models.py` | `LatticeType.SQUARE` already exists; confirm `Design.lattice_type` propagates |
| `backend/core/geometry.py` | Branch on `design.lattice_type` (or pass twist/rise explicitly) to use `SQUARE_TWIST_PER_BP_DEG` and `SQUARE_RISE_PER_BP` |
| `backend/core/lattice.py` | Add `is_valid_square_cell`, `square_direction_for_cell`, `square_helix_xy`, `_square_neighbor_ids`; add `lattice_type` guard at every entry point (`make_bundle_segment`, `compute_autostaple_plan`, `make_prebreak`, `auto_scaffold`, `scaffold_extrude_*`, etc.) |
| `backend/core/crossover_positions.py` | Add `square_crossover_positions(helix_id, direction, length_bp, neighbor_dir)` lookup |
| `frontend/src/scene/workspace.js` | Square grid rendering: square cells, 4-neighbor adjacency, different cell colours |
| `frontend/src/scene/helix_renderer.js` | Pass `lattice_type` to any geometry that depends on it (rise, twist) |
| `frontend/index.html` | New-design dialog already implemented ✅ |
| `frontend/src/main.js` | File > New wired to dialog ✅; workspace must receive lattice type on new-design event |
| `tests/test_square_lattice.py` | New test file: grid geometry, crossover positions, auto-scaffold/staple round-trip |

### Feature SQ-1 — Square grid rendering and cell selection
**Status: 🔵 Planned**

The workspace renders a square grid (instead of honeycomb hexagonal grid) when `Design.lattice_type === 'SQUARE'`.  Cell selection, multi-select, and the Extrude operation all work identically to honeycomb.

- `workspace.js`: detect lattice type from store, branch grid rendering code  
- Cell XY coordinates: `x = col × 2.6`, `y = row × 2.6`  
- Cell color rule: `(row + col) % 2 == 0` → FORWARD color (green), else REVERSE color (blue)
- Adjacency: 4 neighbors, not 6

### Feature SQ-2 — Square lattice geometry
**Status: 🔵 Planned**

`nucleotide_positions()` (in `geometry.py`) receives the design lattice type and uses:
- `SQUARE_TWIST_PER_BP_DEG = 30.0°/bp` (vs 34.3°/bp honeycomb)
- Rise per bp unchanged: 0.334 nm/bp
- Helix radius unchanged: 1.0 nm
- The backbone bead positions, base normals, and helix axes all computed with the modified twist

**3D Validation Checkpoint VSQ.2**: Enable square design, view from above.  "With 30°/bp, at bp 12 the FORWARD strand should have returned to its starting angular position (360°). Does the backbone bead at bp 12 appear directly above bp 0 when viewed along the helix axis?"

### Feature SQ-3 — Square lattice crossover positions
**Status: 🔵 Planned**

`crossover_positions.py` gains `square_crossover_positions()`.  The existing `crossover_positions_for_pair()` dispatcher detects square lattice by helix ID convention OR by a passed `lattice_type` arg.

**3D Validation Checkpoint VSQ.3**: In a 2×1 square-lattice bundle, run `make_auto_crossover`. "Do crossover cones appear at bp 0, 8, 16, 24 (every 8 bp)? Are they on the face that points toward the adjacent helix?"

### Feature SQ-4 — Auto-scaffold for square lattice
**Status: 🔵 Planned**

`auto_scaffold()` (in `lattice.py`) uses `_overhang_only_helix_ids()` already.  Square lattice changes:
- `_greedy_hamiltonian_path` uses 4-neighbor adjacency graph
- End crossover positions from `square_crossover_positions()`
- `loop_size` default = 8 (vs 7 honeycomb)

### Feature SQ-5 — Auto-staple for square lattice
**Status: 🔵 Planned**

`compute_autostaple_plan()` changes:
- `min_pair_spacing = 8` (vs 7 honeycomb)
- `make_prebreak` domain length = 8 bp
- `min_end_margin = 8` (vs 9 honeycomb)

### Feature SQ-6 — Existing features lattice-aware
**Status: 🔵 Planned**

Audit each feature for honeycomb-only assumptions and add lattice-type guards:

| Feature | Change needed |
|---------|--------------|
| Bend/twist deformation | Uses helix geometry only — no crossover assumptions; likely no change needed |
| Loop/skip | Uses bp index directly — no lattice assumption; no change needed |
| Sequence assignment | Watson-Crick only — no change needed |
| Physics (XPBD) | Uses backbone positions only — no change needed |
| Overhang extrusion | No lattice dependency — no change needed |
| Prebreak | Add `crossover_period` param (7 for HC, 8 for SQ) |
| Auto-merge | No lattice dependency — no change needed |
| CSV export | No lattice dependency — no change needed |

### 3D Validation Checkpoints

- **VSQ.1** — Crossover face alignment: single neighbor pair in square lattice, manual crossover placed at bp 0 and bp 8. "Do both crossover cones point directly at the adjacent helix's backbone bead?" (confirms phase offset table)
- **VSQ.2** — Twist rate: bp 12 should be angularly coincident with bp 0 for a 12 bp/turn helix. (See SQ-2 above)
- **VSQ.3** — Auto-scaffold path: 4×2 square bundle, run auto-scaffold. "Does the path visit all 8 helices exactly once?"
- **VSQ.4** — Staple length distribution: autostaple on 4×4 square bundle. "Are all staple lengths in the 16–40 nt range with no anomalous short or long outliers?"


---

## Phase CN — caDNAno v2 Import / Export  (2026-03-21)

**Status: ✅ Complete — merged to master**

**Goal**: Round-trip compatibility with caDNAno v2 `.json` files for both honeycomb (HC) and square (SQ) lattice designs.

### Features

| Feature | Status |
|---------|--------|
| `POST /design/import/cadnano` — HC import | ✅ |
| `POST /design/import/cadnano` — SQ import | ✅ |
| `GET /design/export/cadnano` — HC export | ✅ |
| `GET /design/export/cadnano` — SQ export | ✅ |
| Color import (`stap_colors`) → `store.strandColors` | ✅ |
| Loop/skip arrays imported to `Helix.loop_skips` | ✅ |
| Grid centering (HC: 30×32 center (15,16); SQ: 50×50 center (25,25)) | ✅ |
| `File > Export caDNAno (.json)` menu item | ✅ |

### Key architectural decisions

**HC coordinate mapping**
- `nc = col − min_col`, `nr = max_row − row` (0-based, Y-flipped)
- `y_cad = row × 3R + (R if stagger else 0)`; row step = **3R = 3.375 nm** (not 2.25 nm)
- `axis_start.x = −(nc × COL_PITCH)` — NADOC 3D is mirrored about YZ vs caDNAno canvas; negating x preserves left-right order

**SQ coordinate mapping**
- `axis_start.x = +(nc × 2.25 nm)`, `axis_start.y = −(nr × 2.25 nm)`
- Y is negated because caDNAno's canvas row index increases downward while NADOC's Y axis increases upward
- **Accepted convention**: every known SQ visualizer (cadnano2, scadnano) accepts this slice-plane Y-inversion without correcting it; NADOC follows the same convention

**Lattice detection**
- Array length heuristic: `len % 32 == 0 and len % 21 != 0` → SQ; otherwise HC
- Both lattices use the same cell direction rule: `(row + col) % 2 == 0 → FORWARD`

**Phase offsets (cadnano.py)**
- HC: FORWARD = 322.2°, REVERSE = 252.2°
- SQ: FORWARD = 337.0°, REVERSE = 287.0°

**Export centering**
- Helices are placed at the caDNAno grid centre ± their normalised (nc, nr) offsets
- Parity of row_offset and col_offset must be equal (mod 2) to preserve FORWARD/REVERSE assignment

### Tests
- `tests/test_cadnano.py` — 17 tests covering HC + SQ import geometry, direction assignment, crossover reconstruction, color import, loop/skip, and export round-trip

---

## Phase UX-1 — Overhang + UI Polish  (2026-03-24)

**Status: ✅ Complete — merged to master**

**Goal**: Fix overhang 3D positioning bugs introduced by caDNAno imports, and deliver a suite of UX improvements across selection, grouping, extrude, and rotation.

### Bug fixes

| Bug | Root cause | Fix |
|-----|-----------|-----|
| +Z overhang beads disappear after brief correct display | Three.js InstancedMesh frustum culling uses stale bounding sphere; deformation centroid shifted by overhang helix | `frustumCulled = false` on all four InstancedMeshes; exclude overhang helices from `_arm_helices_for` centroid group |
| "By Sequence" overhang creates wrong domain length on caDNAno imports | `patch_overhang` resize used `new_length_bp - 1` assuming `bp_start=0`; fails for `bp_start=308` | Anchor resize at crossover end: FORWARD → `end_bp = start_bp + new_length_bp - 1`; REVERSE → `start_bp = end_bp + new_length_bp - 1` |
| Overhang helices not appearing in unfold view | `unfoldHelixOrder` snapshot taken before overhang extrusion; `_buildOffsets` used stale order | Merge stored order with all current helix IDs; append new helices at bottom |
| Ctrl+drag lasso broken (OrbitControls intercepts Ctrl+left as pan) | OrbitControls listener registered before selection_manager; no way to stop it in bubble phase | Capture-phase `pointerdown` listener sets `controls.enabled = false` before OrbitControls sees Ctrl+drag |
| `C_SELECT_STRAND is not defined` error in lasso code | Missing constant declaration | Added `const C_SELECT_STRAND = 0xffffff` |
| Glow layer stops at ~4000 instances (full scaffold not highlighted) | Hard-coded `MAX_INSTANCES = 4000` InstancedMesh cap | Replaced with `_ensureCapacity(needed)` that rebuilds InstancedMesh when count exceeds allocated capacity |
| Selection highlight lost after group change | `strandGroups` change triggers 3D rebuild but selection manager's post-rebuild subscriber only watched `currentGeometry` | Extended condition to also fire on `strandGroups !== prevState.strandGroups` |

### UX improvements

| Feature | Description |
|---------|-------------|
| Properties sidebar text truncation | Strand text clamped to 2 lines via `-webkit-line-clamp` |
| Extrude tool — no camera snap | Removed `controls.enableRotate = false` and `_snapCameraToPlane()`; orbit stays active while extruding |
| Scaffold length recommendations | Both extrude menus show clickable rec-chips (7249 / 8064) assuming 14 nt scaffold loops per helix; chips autopopulate the input, popup stays open |
| Hide staples toggles crossover arcs | `staplesHidden` subscriber in `unfold_view.js` calls `_applyStapleArcVisibility()` for both 3D and 2D |
| Domain/bead glow narrowing | 2nd click → glow narrows to clicked domain; 3rd click → glow narrows to single bead |
| No rotation momentum | OrbitControls: `enableDamping = false`; TrackballControls: `staticMoving = true` |
| Right-click group dropdown | Flat group list replaced with `<select>` dropdown + inline "＋ New group…" input for single-strand context menu |
| Multi-select group dropdown | Same dropdown pattern for multi-strand right-click; selecting a group overrides any existing group membership for all selected strands |
| Group operations undoable | `pushGroupUndo()` / `popGroupUndo()` in `store.js`; Ctrl+Z pops group history before falling through to backend undo; covers single-strand menu, multi-select menu, spreadsheet, and groups panel |
| Multi-select group color propagation | When added to a group via multi-select, strands receive the group's palette color both in-scene (via `_effectiveColors` rebuild) and on the backend (via `api.patchStrand`) |

### Files changed

| File | Change |
|------|--------|
| `backend/core/deformation.py` | Exclude overhang helices from arm centroid group |
| `backend/api/crud.py` | Fix `patch_overhang` domain resize to anchor at crossover end |
| `frontend/src/state/store.js` | Add `strandGroupsHistory`; export `pushGroupUndo` / `popGroupUndo` |
| `frontend/src/scene/helix_renderer.js` | `frustumCulled = false` on all InstancedMeshes; narrowed glow on 2nd/3rd click |
| `frontend/src/scene/glow_layer.js` | Dynamic capacity via `_ensureCapacity`; removed hard cap |
| `frontend/src/scene/scene.js` | Remove damping/momentum from both orbit modes |
| `frontend/src/scene/selection_manager.js` | Capture-phase lasso fix; group dropdown (single + multi); `pushGroupUndo` calls; `C_SELECT_STRAND` constant |
| `frontend/src/scene/unfold_view.js` | Merge overhang helices into unfold order; `staplesHidden` arc visibility |
| `frontend/src/scene/slice_plane.js` | Remove camera snap; scaffold rec-chips |
| `frontend/src/scene/workspace.js` | Scaffold rec-chips for initial extrude |
| `frontend/src/ui/spreadsheet.js` | `pushGroupUndo` in `_assignGroup` |
| `frontend/src/main.js` | `pushGroupUndo` in groups panel; `popGroupUndo` hooked into Ctrl+Z and menu-edit-undo |
| `frontend/index.html` | Prop-val truncation CSS; rec-chip CSS |

---

## Phase UX-2 — Selection Filter Rework  (2026-03-25)

**Status: ✅ Complete — merged to master (3 commits)**

**Goal**: Split the single "Selection Filter" sidebar section into a **Tool Filter** (visibility toggles) and an extended **Selection Filter** (selectable types). Add lasso/click selection for loops, skips, placed crossover arcs, and 5′/3′ ends. Add right-click delete for crossovers (topological unroute) and loop/skip markers (delta=0).

### Architecture decisions

| Decision | Choice |
|----------|--------|
| Crossover unplace | `api.addNick` on arc `fromNuc` — nicks strand at cross-helix domain boundary, no new backend endpoint needed |
| Ends output channel | `_ctrlBeads` (gold individual-bead highlight), not `strandIdSet` (strand multi-select) |
| Lasso priority | crossoverArcs > loops/skips > strands/ends (earlier types return early) |
| Scaffold/staples + ends | Independent pools; ends beads go to `_ctrlBeads` after strand highlight so gold wins over white |

### Store changes

| Field | Change |
|-------|--------|
| `toolFilters` | NEW: `{bluntEnds: true, crossoverLocations: false}` — controls overlay tool visibility |
| `selectableTypes` | Removed `bluntEnds`/`crossovers`; added `loops`, `skips`, `crossoverArcs`, `ends` |

### New capabilities

| Feature | Trigger | Output |
|---------|---------|--------|
| Blunt Ends toggle | Tool Filter | `toolFilters.bluntEnds` → `bluntEndMarkers.setVisible()` |
| Crossover Sprites toggle | Tool Filter | `toolFilters.crossoverLocations` → `crossoverLocations.setVisible()` |
| Crossover arc click-select | Click arc midpoint (crossoverArcs=T) | Yellow highlight, added to `_multiCrossoverArcs` |
| Crossover arc lasso | Ctrl+drag (crossoverArcs=T) | All arc midpoints in rect → `_multiCrossoverArcs` |
| Unplace crossovers | Right-click on selected arcs | "Unplace N crossover(s)" → `api.addNick` per arc `fromNuc` |
| Loop/skip ctrl+click | Ctrl+click near marker | Toggle in `_multiLoopSkipEntries`, white highlight |
| Loop/skip lasso | Ctrl+drag (loops/skips=T) | Markers in rect → `_multiLoopSkipEntries` |
| Remove loops/skips | Right-click on selected markers | "Remove N loop(s)/skip(s)" → `api.insertLoopSkip(delta=0)` |
| Ends lasso | Ctrl+drag (ends=T) | End beads in rect → `_ctrlBeads` (gold, 1.6× scale) |
| Ends ctrl+click | Ctrl+click (ends=T, scaffold/staples=F) | Snaps to nearest end bead → `_ctrlBeads` |

### Bug fixes included

| Bug | Fix |
|-----|-----|
| `selectableTypes.bluntEnds` removed | `blunt_ends.js` updated to read `toolFilters.bluntEnds` |
| Ctrl+click ignored scaffold/staples filter | `_handleCtrlClickNuc` now builds `selBackbone` filtered by `selectableTypes` |
| Ends lasso added whole strands to `strandIdSet` | Now collects `endEntries` separately, populates `_ctrlBeads` |
| Ends ctrl+click/click did nothing (empty `selBackbone`) | End beads included in `selBackbone` when `selectableTypes.ends` |

### Files changed

| File | Change |
|------|--------|
| `frontend/index.html` | Split into Tool Filter + Selection Filter sections; add loops/skips/crossoverArcs/ends rows |
| `frontend/src/state/store.js` | Add `toolFilters`; extend `selectableTypes` |
| `frontend/src/main.js` | Tool Filter toggle loop wiring; updated Selection Filter keys; deform save/restore uses new keys |
| `frontend/src/scene/blunt_ends.js` | `_isBlocked()` and subscribe condition use `toolFilters.bluntEnds` |
| `frontend/src/scene/loop_skip_highlight.js` | Add `_highlightMat`; add `getEntries()` public method |
| `frontend/src/scene/selection_manager.js` | `_handleCtrlClick` dispatcher; `_finalizeLasso` extended; arc/loop-skip multi-select state + menus; ends → `_ctrlBeads` |

---

## Phase UX-3 — Draggable End Arrows + Inline Overhangs  (2026-03-25)

**Status: ✅ Complete (branch `strand-editing`, merged master 2026-03-25)**

**Goal**: Make the cyan 5′/3′ extrusion arrows interactive — draggable along the helix axis to
extend or shorten a strand. Automatically tag scaffold-less extensions as inline overhangs.

### Feature UX3-1 — Draggable End Arrows

Selected end beads show a cyan arrow that can be grabbed and dragged along the helix axis.
All visible arrows move together (same bp delta). Orbit is disabled while dragging.
Commit on mouseup (single undo step); Escape cancels.

| Property | Value |
|----------|-------|
| Snap precision | Integer bp |
| Hard stop (trim) | terminal domain ≥ 1 bp |
| Hard stop (extend) | nearest occupied bp on same helix + direction |
| Helix growth | automatic when extending past current bounds |
| Backend function | `resize_strand_ends(design, entries)` in `lattice.py` |
| Backend endpoint | `POST /design/strand-end-resize` in `crud.py` |
| Frontend module | `frontend/src/scene/end_extrude_arrows.js` |
| Ghost preview material | cyan (extend) / orange-red (trim), opacity 0.35 |

### Feature UX3-2 — Drag Tooltip

A floating monospace badge next to the cursor displays `[+N]` (cyan) or `[-N]` (orange) during drag.

| Implementation | `_tooltip` div appended to `document.body`; `display:none` when idle |
|---|---|
| vitest change | `environment` changed from `'node'` to `'jsdom'`; `jsdom` added as devDependency |

### Feature UX3-3 — Auto Inline Overhang Tagging

When a staple is dragged past scaffold coverage, the beyond-scaffold portion is automatically
tagged as an inline overhang so the user can assign sequences in the sidebar or spreadsheet.

| Property | Value |
|----------|-------|
| Overhang ID format | `ovhg_inline_{strand_id}_{5p\|3p}` |
| Distinguishes from extrude-style | `is_inline = ovhg_id.startswith("ovhg_inline_")` |
| Merge-then-re-split on repeat drag | Preserves any user-assigned sequence/label |
| Domain split helper | `_reconcile_inline_overhangs(...)` in `lattice.py` |
| Scaffold coverage helper | `_scaffold_coverage_by_helix(design)` in `lattice.py` |
| Sequence assignment fix | `patch_overhang` skips helix resize for inline overhangs |

### Bug fixes included

| Bug | Fix |
|-----|-----|
| `patch_overhang` destroyed main helix for inline overhangs | Added `is_inline` guard; skip helix resize; correct anchor-end formulas |
| Overhang geometry test regression (seam avoidance filtered needed crossovers) | Removed `auto_scaffold` call from `_make_stapled_6hb` test fixture |

### UI changes

- Overhangs sidebar panel moved between Groups and Physics (was after Physics)

### Files changed

| File | Change |
|------|--------|
| `backend/core/lattice.py` | `resize_strand_ends`, `_scaffold_coverage_by_helix`, `_reconcile_inline_overhangs` |
| `backend/api/crud.py` | `StrandEndResizeEntry/Request`, `POST /design/strand-end-resize`; inline fix in `patch_overhang` |
| `frontend/src/api/client.js` | `resizeStrandEnds(entries)` |
| `frontend/src/scene/end_extrude_arrows.js` | Full drag logic, ghost preview, tooltip; `controls` param |
| `frontend/src/main.js` | Pass `controls` to `initEndExtrudeArrows` |
| `frontend/vitest.config.js` | `environment: 'jsdom'` |
| `frontend/package.json` | `jsdom` devDependency |
| `frontend/index.html` | Overhangs panel repositioned |
| `tests/test_lattice.py` | 3 new inline overhang resize tests |
| `tests/test_overhang_geometry.py` | Remove `auto_scaffold` from `_make_stapled_6hb` |

---

## Phase LOD — Level of Detail + Strand Groups  (2026-03-28)

Performance rendering system for large designs and multi-origami assemblies, plus strand group color management improvements.

### LOD rendering

Three detail levels accessible via View → Representation:

| Level | Name | Geometry shown |
|-------|------|----------------|
| 0 | Full | All beads, cones, slabs |
| 1 | Beads | Beads + cones; slabs hidden |
| 2 | Cylinders | One `InstancedMesh` cylinder per staple domain; all bead geometry hidden |

**Cylinder LOD design decisions:**
- Scaffold domains excluded from cylinder build to avoid z-fighting (scaffold + staple are coaxial at same helix radius)
- Color uses `strand.id` (JS UUID field), not `strand.strand_id` (undefined on JS objects)
- Z-position uses physical axis length as parametric denominator (`arrow.aStart.distanceTo(arrow.aEnd)`), not `helix.length_bp` — fixes caDNAno imports where active bp range ≠ array length
- ±0.5 bp extension per cylinder end reduces visual gaps between adjacent domains
- Cylinder click: selects entire strand (highlights all cylinders for that strand); bead/cone raycasting disabled in cylinder LOD
- Cylinder lasso: ctrl+drag collects cylinder strand IDs into multi-select

**Crossover arc color sync:**
- Arc colors update on direct color changes via `strandColors` subscription in `unfold_view.js`
- Arc colors update on group changes via `strandGroups` subscription in `unfold_view.js`
- `helix_renderer.getPaletteColors()` exposes build-time `stapleColorMap` for reverting strands removed from a group

### Strand groups (color-only)

Groups are purely cosmetic — strand group membership and group color changes no longer trigger a full scene rebuild. This keeps views like unfold view active uninterrupted.

**Architecture change:** `strandGroups` removed from `design_renderer._rebuild()` trigger. Instead:
- A dedicated `strandGroups` diff handler in `design_renderer.js` computes `_effectiveColors` for both old and new state
- Only strands whose effective color changed receive a `setStrandColor` call
- Palette fallback via `_helixCtrl.getPaletteColors()` handles strands removed from groups

**Multi-select → new group:** The sidebar "+ New Group" button seeds the new group with `store.multiSelectedStrandIds` if a lasso selection is active. Same behaviour as "+ New Cluster From Selection".

### Files changed

| File | Change |
|------|--------|
| `frontend/src/scene/helix_renderer.js` | `iHelixCylinders` InstancedMesh; `_domainCylData`; cylinder selection API; `getPaletteColors()`; cylinder z-position fix |
| `frontend/src/scene/design_renderer.js` | `setDetailLevel` passthrough; cylinder API passthrough; `strandGroups` removed from rebuild trigger; live group color diff handler |
| `frontend/src/scene/unfold_view.js` | `strandColors` subscription for arc color sync; `strandGroups` subscription for arc color sync |
| `frontend/src/scene/selection_manager.js` | Cylinder LOD click/lasso selection; bead raycasting disabled in cylinder LOD; `effectiveStrandIds` for group creation with multi-select |
| `frontend/src/main.js` | LOD mode wiring; "+ New Group" button seeds from `multiSelectedStrandIds` |
| `frontend/index.html` | LOD options merged into Representation submenu; Auto LOD removed |

---

## Surface Representations + UX Hardening  (2026-03-28)

### Surface Representations

VdW (Van der Waals space-fill) and SES (Solvent Excluded Surface) added as two new entries in the Representation menu alongside the existing CG and atomistic modes.

**Algorithm** (`backend/core/surface.py`):
- Atom positions from `build_atomistic_model` (full all-atom pipeline)
- 3D occupancy grid at VdW radii + configurable grid spacing (default 0.25 nm)
- VdW: Gaussian smooth → marching cubes (`skimage.measure.marching_cubes`)
- SES: binary dilation by probe radius → erosion → re-dilation → smooth → marching cubes
- Vertex strand IDs via `cKDTree` nearest-atom lookup → strand palette colors
- `SurfaceMesh` dataclass: `vertices (N,3)`, `faces (M,3)`, `vertex_strand_ids`

**API** (`GET /api/design/surface`):
- Params: `surface_type` (vdw|ses), `color_mode` (strand|uniform), `probe_radius`, `grid_spacing`, `smooth_sigma`
- Returns: `{vertices, faces, vertex_colors, stats:{n_verts, n_faces, compute_ms}}`
- Dependency added: `scikit-image>=0.25.0`

**Frontend** (`frontend/src/scene/surface_renderer.js`):
- `THREE.BufferGeometry` from flat float32 vertex/face arrays
- `computeVertexNormals()` for Phong shading; `DoubleSide` material
- `setColorMode(mode)` swaps vertex-color vs uniform in-place (no re-fetch)
- `setOpacity(val)` live transparency

**Surface options sidebar panel:**
- Coloring: Strand / Uniform toggle
- Probe radius slider (0–0.50 nm)
- Opacity slider (0.05–1.00)

**Computing toast:** `showPersistentToast('Computing surface…')` appears immediately on fetch start; `dismissToast()` on response (or error) — gives feedback for large designs.

### Atomistic Representation Cleanup

Removed all 8 torsion/frame/crossover debug sliders from VdW Space-fill and Ball & Stick modes. Backend URL now uses hardcoded best defaults (`frame_rot_deg=39`, `frame_shift_n=-0.07`, `frame_shift_y=-0.59`, `crossover_mode=lerp`).

Replaced debug sliders with:
- **Atom radius scale** — VdW radius multiplier (0.50–1.50×)
- **Coloring** — CPK (per-element) or Strand (uses store `strandColors`/`strandGroups` palette)

Live strand color sync: `strandColors`/`strandGroups` changes automatically re-color the atomistic overlay without re-fetching geometry.

### New Workspace Reset Hardening

`_resetForNewDesign()` now fully cleans up state from the previous part:
- Calls `_setRepresentation('full')` — deactivates atomistic/surface renderers, resets representation radio + option panels
- Calls `_hideBluntPanel()` — clears stale blunt-end sidebar
- Camera snapped to Z+ (`viewCube.snapToNormal`) — consistent starting view on the XY workspace plane
- Store reset extended: `selectedObject`, `multiSelectedStrandIds`, `isolatedStrandId`, `crossoverPlacement`, `strandGroups`, `strandGroupsHistory`, `loopStrandIds`, `isCadnanoImport`, `lastError`, `activeClusterId`, `translateRotateActive`

**Backend undo history cleared on new design:** `create_bundle` and `create_design` now call `design_state.clear_history()` before `set_design()`, matching the existing behaviour of `load_design` / `import_design` / `import_cadnano`. Ctrl-Z cannot undo across design sessions.

### Strand Length Histogram — Delete by Bin

Right-click any histogram bar → context menu → "Delete N strand(s)" deletes all staples of that length. Uses existing `api.deleteStrand` sequential loop. Context menu uses the shared `.ctx-menu` CSS class.

### Tools Menu — Overhang Locations Removed

`menu-view-overhang-locations` button and separator removed from the Tools dropdown. The sidebar Tool Filter toggle (and `O` hotkey) remain as the single control point.

### Toast System — Persistent Variant

`frontend/src/ui/toast.js` gains two exports:
- `showPersistentToast(msg)` — stays visible until explicitly dismissed
- `dismissToast()` — fades out immediately; clears any pending auto-dismiss timer

### Bug Fix — TDZ in helix_renderer.js

`_cylRadiusScale` (and `_detailLevel`, `_beadScale`) were declared with `let` *after* the cylinder-build block that references them — a JavaScript Temporal Dead Zone error. Declarations moved before the block. This was the root cause of workspace planes persisting after extrude (exception propagated through the store subscriber chain and silently prevented `workspace.hide()` from being called).

### Files changed

| File | Change |
|------|--------|
| `backend/core/surface.py` | **NEW** — VdW/SES grid, marching cubes, KDTree vertex coloring |
| `backend/api/crud.py` | `GET /api/design/surface` endpoint; `clear_history()` in `create_bundle` + `create_design` |
| `pyproject.toml` | `scikit-image>=0.25.0` dependency |
| `frontend/src/scene/surface_renderer.js` | **NEW** — Three.js BufferGeometry surface mesh renderer |
| `frontend/src/scene/atomistic_renderer.js` | `setVdwScale()`, `setColorMode('cpk'|'strand')`, `_vdwScale`, `_strandColors` state |
| `frontend/src/scene/helix_renderer.js` | TDZ fix: `_detailLevel`/`_beadScale`/`_cylRadiusScale` declarations moved before cylinder-build block |
| `frontend/src/ui/toast.js` | `showPersistentToast`, `dismissToast` added |
| `frontend/src/state/store.js` | `surfaceMode`, `surfaceColorMode`, `surfaceOpacity` added to initial state |
| `frontend/src/main.js` | Surface mode wiring; atomistic cleanup; `_resetForNewDesign` hardening; histogram right-click delete; overhang locations menu removed |
| `frontend/index.html` | Surface options panel; atom radius/coloring rows; histogram ctx-menu; overhang locations menu item removed |

---

## Phase scaffold-sequence-overhaul — Scaffold Library, SQ Periodic Skips, caDNAno Fixes, Overhang UX  (2026-03-28)

**Status: ✅ Complete — merged master 2026-03-28**

**Goal**: Extend the scaffold sequence picker to a 3-sequence library, add automatic periodic skips for square-lattice designs, fix caDNAno import rendering bugs (helix shaft gaps, interior blunt-end rings), improve overhang autodetection and sidebar UX, and add half-cylinder LOD representation for overhang domains.

### Feature 1 — Scaffold Sequence Library (p7560, p8064)

`backend/core/sequences.py` now loads three scaffold sequences at startup:

| Name | Length | File |
|------|--------|------|
| M13mp18 | 7 249 nt | `backend/core/m13mp18.txt` |
| p7560 | 7 560 nt | `backend/core/p7560.txt` |
| p8064 | 8 064 nt | `backend/core/p8064.txt` |

`SCAFFOLD_LIBRARY: list[tuple[str, int, str]]` — ordered `(display_name, length, sequence)`.

`assign_scaffold_sequence(design, start_offset=0, scaffold_name="M13mp18")` selects from the library. Scaffold longer than the chosen sequence fills remaining positions with `'N'`.

**API**: `POST /design/assign-scaffold-sequence  body: {start_offset, scaffold_name}`.

**UI**: "Assign Scaffold Sequence…" now opens a picker modal (`#assign-scaffold-modal`) with three radio buttons, an inline length-vs-scaffold warning, and Cancel / Apply buttons.

### Feature 2 — Update Staple Routing Relocation + SQ Periodic Skips

**Menu relocation**: "Update Staple Routing" moved from Sequencing submenu to Routing submenu (after Auto Merge + separator). **Hotkeys shifted**: `[5]` = Update Staple Routing, `[6]` = Assign Scaffold Sequence, `[7]` = Assign Staple Sequences.

**SQ periodic skips**: `sq_lattice_periodic_skips(design)` in `loop_skip_calculator.py` places one skip per 48 bp on every helix of a square-lattice design, staggered by helix index (`offset_i = (i * 48) // N`). Applied automatically when "Update Staple Routing" runs on a SQ design (even without any bend/twist deformations).

`apply_loop_skips_from_deformations` in `crud.py` updated: guard relaxed so SQ designs proceed without deformations; SQ periodic skips prepended to `all_mods` before deformation-derived mods (deformation mods win at any conflicting position).

### Feature 3 — caDNAno Import Rendering Fixes

**Helix shaft segment positioning**: `_scaffoldIntervals` (helix_renderer.js) used `(lo - bp_start) / length_bp * axLen` where `length_bp` is the full caDNAno array size (not the active span). Fixed to `(lo - bp_start) * BDNA_RISE_PER_BP`. Correctly positions shaft segments on helices with `bp_start > 0` or `length_bp > active_span`.

**Interior blunt-end ring positioning**: `blunt_ends.js` used the same flawed formula. Fixed to `t = (bp - bp_start) * BDNA_RISE_PER_BP / axisLen`; exterior guard replaced from `bp === bp_start + length_bp - 1` to `t <= 0 || t >= 1`.

**Gap boundary blunt ends**: `_scaffoldIntervals` fallback for scaffold-free helices collects all strand domain intervals (not a single full-range fallback) so gaps in a caDNAno helix array are not bridged by the axis arrow. Strand termini adjacent to gaps now correctly receive selectable blunt-end rings.

### Feature 4 — Overhang Autodetection + Sidebar UX

**`_reconcile_inline_overhangs` scaffold-free fix**: Added early exit (`if helix_id not in scaf_cov: continue`) before the merge logic. Previously the merge path ran first, clearing tags set by `autodetect_overhangs` on scaffold-free helices (caDNAno imports with overhang-only helices).

**OH label auto-assignment**: `autodetect_all_overhangs` assigns `OH1`, `OH2`, … labels to all untagged overhangs after both detection passes.

**Overhang sidebar — permanent panel**: `#overhang-panel` is always visible (previously `display:none` until overhangs existed). Empty state shows placeholder text.

**Overhang sidebar — selection highlighting**: selecting any strand or domain that owns an overhang highlights the corresponding sidebar row (`background: #1e3a5f; border-left: 2px solid #58a6ff`). Tracks `selectedObject`, `multiSelectedStrandIds`, and `multiSelectedDomainIds`.

### Feature 5 — Half-Cylinder LOD for Overhang Domains

`GEO_HALF_CYL = THREE.CylinderGeometry(1.125, 1.125, 1, 8, 1, false, 0, Math.PI)` — D-shaped cross-section.

`iOverhangCylinders` InstancedMesh (DoubleSide material) activated at LOD level 2 alongside `iHelixCylinders`. Overhang half-cylinders use the owning strand's palette color (same formula as regular cylinders), not a fixed amber.

Wired into: `setDetailLevel`, `setCylinderRadius`, `setStrandColor`, `highlightCylinderStrands`, `clearCylinderHighlight`, `revertToGeometry`, `applyUnfoldOffsets`. Public accessors: `getOverhangCylinderMesh()`, `getOverhangCylinderDomainData()`, `getOverhangCylinderDomainAt()`.

### Feature 6 — Highlight Undefined Bases Toggle

"Highlight Undefined Bases" toggleable menu item in View submenu. Marks scaffold positions not covered by any staple (and vice versa) in the sequence overlay.

### Feature 7 — Domains Selectable Toggle

New "Domains" row in the Selection Filter sidebar (`#sel-row-domains` / `#sel-toggle-domains`). When enabled, individual domain segments are selectable by click/lasso in addition to full strands.

### Files changed

| File | Change |
|------|--------|
| `backend/core/sequences.py` | Scaffold library (p7560, p8064); `scaffold_name` param; N-fill for oversized scaffolds |
| `backend/core/p7560.txt` | **NEW** — 7560-nt scaffold sequence |
| `backend/core/p8064.txt` | **NEW** — 8064-nt scaffold sequence |
| `backend/core/models.py` | `scaffold_name` field on scaffold assignment request |
| `backend/core/loop_skip_calculator.py` | `sq_lattice_periodic_skips()` function |
| `backend/core/lattice.py` | `_reconcile_inline_overhangs` scaffold-free fix; OH label auto-assignment in `autodetect_all_overhangs` |
| `backend/api/crud.py` | `apply_loop_skips_from_deformations` SQ guard + SQ periodic skip prepend; scaffold assignment `scaffold_name` routing |
| `frontend/index.html` | Scaffold picker modal; Routing submenu USR button + hotkey shift; "Highlight Undefined Bases" toggle; "Domains" sel-row; `#overhang-panel` always visible |
| `frontend/src/main.js` | Scaffold picker modal wiring; hotkey map [5]/[6]/[7]; overhang sidebar permanent + selection highlight; USR click handler SQ guard |
| `frontend/src/scene/helix_renderer.js` | `GEO_HALF_CYL`; `iOverhangCylinders` InstancedMesh; overhang build loop; all LOD update paths |
| `frontend/src/scene/blunt_ends.js` | Interior ring RISE formula fix; `BDNA_RISE_PER_BP` import |
| `frontend/src/api/client.js` | `scaffold_name` forwarded to assign-scaffold endpoint |
| `frontend/src/scene/sequence_overlay.js` | Undefined bases highlight mode |
| `frontend/src/scene/selection_manager.js` | Domains selectable type support |
| `frontend/src/scene/design_renderer.js` | Overhang cylinder color sync |
| `frontend/src/scene/glow_layer.js` | Minor glow fixes |
| `frontend/src/scene/expanded_spacing.js` | Spacing updates |
| `frontend/src/scene/cluster_gizmo.js` | Cluster gizmo fixes |
| `frontend/src/scene/unfold_view.js` | Unfold arc fixes |
| `frontend/src/scene/workspace.js` | Workspace state fixes |
| `frontend/src/scene/scene.js` | Scene setup fixes |
| `frontend/src/state/store.js` | New store fields |
| `frontend/src/ui/cluster_panel.js` | Cluster panel improvements |

---

## Phase extensions — Strand Terminal Extensions + Fluorescence/FRET View  (2026-03-29)

### Goal
Add first-class `StrandExtension` model for 5′ and 3′ termini of staple strands, covering sequence tails (poly-T spacers), fluorophores (Cy3, Cy5, FAM, TAMRA, ATTO 488, ATTO 550), and quenchers/handles (BHQ-1, BHQ-2, Biotin). Full rendering across LOD levels (hidden in cylinders), unfold lerp support, spreadsheet bracket notation, and a right-click dialog. Two new View menu toggles: **Fluorescence** (emission-color sprite glows) and **FRET Checker** (live donor quenching indicator based on Förster radii).

---

### Data model

`StrandExtension` (`backend/core/models.py`):
- `id` (uuid), `strand_id`, `end` (`five_prime` | `three_prime`)
- `sequence` (ACGTN, optional), `modification` (from `VALID_MODIFICATIONS`, optional)
- At least one of `sequence`/`modification` must be set (`@model_validator`)
- `Design.extensions: List[StrandExtension]`

```
VALID_MODIFICATIONS = {cy3, cy5, fam, tamra, bhq1, bhq2, atto488, atto550, biotin}
MODIFICATION_COLORS = {cy3: "#ff8c00", cy5: "#cc0000", fam: "#00cc00", ...}
```

---

### Geometry

`_strand_extension_geometry(design, nuc_pos_map)` in `crud.py`:
- Resolves terminal domain (5′ = first domain, 3′ = last domain) and terminal bp
- Radial outward direction in XY from helix center; quadratic Bézier arc with +Z bow
- One geometry dict per sequence base (`is_modification=False`) + one for fluorophore (`is_modification=True`)
- Synthetic `helix_id = "__ext_{ext.id}"`; `domain_index = -1.0` (5′) or `float(len(domains))` (3′)
- Extra fields on `__ext_` nucleotides: `extension_id`, `is_modification`, `modification`

---

### API

Three original endpoints + two batch endpoints (batch registered BEFORE `{ext_id}` routes to avoid FastAPI shadowing):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/design/extensions` | Create single extension |
| `PUT` | `/design/extensions/{ext_id}` | Update single extension |
| `DELETE` | `/design/extensions/{ext_id}` | Delete single extension |
| `POST` | `/design/extensions/batch` | Upsert N extensions (single undo step) |
| `DELETE` | `/design/extensions/batch` | Delete N extensions by IDs |

Validation: staple-only; no duplicate `(strand_id, end)` pairs; at least one of seq/mod; valid modification key; valid ACGTN sequence chars.

---

### Frontend rendering

**`helix_renderer.js`**:
- `FLUORO_EMISSION_COLORS: Map<string, number>` — scientifically accurate emission hex colors; BHQ-1, BHQ-2, Biotin intentionally absent (no glow for dark quenchers/non-fluorophores)
- `GEO_FLUORO_SPHERE = SphereGeometry(0.25, 12, 10)` — larger distinct sphere for fluorophore beads
- Fluorophore beads (`is_modification: true`) excluded from `iSpheres`/`iCubes`/`iSlabs`; built into separate `iFluoros` InstancedMesh
- `__ext_` nucleotides skipped in slab loop and `getCrossHelixConnections`
- `applyUnfoldOffsetsExtensions(extArcMap, t)` — lerps extension + fluorophore beads during unfold
- `setExtensionsVisible(visible)` — hides/shows all extension beads for the `extensionLocations` tool filter
- `getFluoroEntries()` — returns fluorophore-only entries for FRET/fluorescence glow

**`glow_layer.js` — `createMultiColorGlowLayer`**:
- Replaced InstancedMesh approach with one `THREE.Sprite` per fluorophore
- Shared 128×128 canvas radial-gradient texture (white center → transparent edge) reused by all materials
- `SpriteMaterial` cached per hex emission color (at most 6 materials created)
- `scale = 20` (20 nm diameter = 10 nm radius) by default; supports per-entry `scale` override
- AdditiveBlending; auto-billboards to camera

---

### Fluorescence view (View menu)

Toggle `menu-view-fluorescence`: shows emission-color sprite glows over all fluorophore beads with known `FLUORO_EMISSION_COLORS` (cy3, cy5, fam, tamra, atto488, atto550). Glows rebuild on geometry reload.

---

### FRET Checker (View menu)

Toggle `menu-view-fret`: overlays same sprite glows as Fluorescence view, but donors within their Förster radius of a compatible acceptor are shown at **scale 3 (~1.5 nm radius)** to indicate energy transfer.

Supported donor→acceptor pairs and Förster radii (R₀):

| Donor | Acceptor | R₀ |
|---|---|---|
| Cy3 | Cy5 | 5.4 nm |
| FAM | TAMRA | 4.6 nm |
| ATTO 488 | ATTO 550 | 6.3 nm |
| FAM | BHQ-1 | 4.2 nm |
| FAM | BHQ-2 | 4.2 nm |
| Cy3 | BHQ-2 | 4.5 nm |
| TAMRA | BHQ-2 | 4.5 nm |

FRET re-check runs every animation frame when the toggle is on → live updates during translate/rotate gizmo drag. When both Fluorescence and FRET Checker are on, FRET scale takes priority for quenched donors.

---

### Context menu + dialog

`selection_manager.js`:
- Single-strand right-click (`_showColorMenu`): "Add extension…" / "Edit extensions…" / "Remove extensions" for staple strands
- Multi-strand right-click (`_showMultiMenu`): identical extension section for all selected staples
- `_openExtensionDialog(x, y, strandIds, existingsByStrand)`: unified dialog with 5′ / 3′ / Both radio, sequence input, modification `<select>`, label input. Calls `api.upsertStrandExtensionsBatch` on Apply
- Warning dialog fires before prebreak/autocrossover/automerge when extensions or crossover-bases exist

---

### Unfold view

`_buildExtArcMap(helixOffsets, straightPosMap)` in `unfold_view.js`: fans each extension out horizontally past the strand terminus (sign = −1 for 5′, +1 for 3′; spacing = 0.34 nm/bead). Called alongside `_buildXbArcMap`; `applyUnfoldOffsetsExtensions` called at all 3 unfold update sites.

---

### Spreadsheet

`_strandDisplaySequence` in `spreadsheet.js` prepends/appends bracket notation:
- `[seq/MOD]` — both sequence and modification
- `[seq]` — sequence only
- `[/MOD]` — modification only

Examples: `[TTTT/CY3]ACGTACGT`, `ACGTACGT[TT/FAM]`, `[/BIOTIN]ACGTACGT`

---

### Key files changed

| File | Change |
|---|---|
| `backend/core/models.py` | `StrandExtension`, `MODIFICATION_COLORS`, `VALID_MODIFICATIONS`, `Design.extensions` |
| `backend/api/crud.py` | `_strand_extension_geometry`, 5 extension endpoints + batch request models |
| `frontend/src/api/client.js` | `createStrandExtension`, `updateStrandExtension`, `deleteStrandExtension`, `upsertStrandExtensionsBatch`, `deleteStrandExtensionsBatch` |
| `frontend/src/state/store.js` | `toolFilters.extensionLocations`, `selectableTypes.extensions` |
| `frontend/src/scene/helix_renderer.js` | Extension + fluorophore rendering, `FLUORO_EMISSION_COLORS`, LOD guard, unfold lerp |
| `frontend/src/scene/glow_layer.js` | `createMultiColorGlowLayer` — sprite-based tapered glow (replaces InstancedMesh) |
| `frontend/src/scene/design_renderer.js` | Wires `setFluorescenceGlow`, `clearFluorescenceGlow`, `getFluoroEntries`, `setExtensionsVisible` |
| `frontend/src/scene/unfold_view.js` | `_buildExtArcMap`, `applyUnfoldOffsetsExtensions` wiring |
| `frontend/src/scene/selection_manager.js` | Extension context menu (single + multi-select), `_openExtensionDialog`, routing warning |
| `frontend/src/ui/spreadsheet.js` | Bracket notation for extensions |
| `frontend/index.html` | Fluorescence + FRET Checker menu items |
| `frontend/src/main.js` | `_refreshGlowModes`, FRET Checker logic + Förster radii, per-frame tick FRET update |

---

## Technical Debt — Scheduled Refactoring

These are known code-quality issues that don't block features but should be addressed before the
codebase grows further.

### TD-1: Split `auto_scaffold` god function — ✅ **Complete (2026-03-30)**

`auto_scaffold` in `backend/core/lattice.py` reduced from 691 → 144 lines. Three helpers extracted:
- `_find_dx_xover(h_a, dir_a, h_b, dir_b, target_bp_b, plane)` — pure DX crossover geometry search
- `_route_merged_cross_section_virt_seg(...)` — 3-sub-bundle bridge routing; returns `list[list[Domain]]`
- `_route_standard_virt_seg(...)` — all non-bridge cases; returns `list[list[Domain]]`
- `auto_scaffold` is now a 144-line orchestrator. 429/429 tests pass.

---

### TD-4: Centralise bp_start/geo_start coordinate conversion — ✅ **Complete (2026-03-30)**

`backend/core/bp_indexing.py` created as single source of truth for all three helix conventions
(native, caDNAno, hybrid):
- `get_helix_geo_bp_start(helix)` — geometric bp_start from axis projection
- `get_helix_bp_count(helix)` — active bp count from axis length
- `stored_to_global_bp(helix, stored_bp, geo_start=None)` — `stored - bp_start + geo_start`
- `global_to_stored_bp(helix, global_bp, geo_start=None)` — inverse

`crossover_positions.py` private `_helix_bp_count` / `_helix_axis_bp_start` removed; all call sites
updated to import from `bp_indexing`. 429/429 tests pass.
