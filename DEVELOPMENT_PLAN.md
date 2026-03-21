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

**Status: ✅ Core complete — 238/238 tests passing (branch `phase7-loop-skip`)**

**Goal**: Translate geometric deformation parameters into actual loop/skip base modifications in the topological layer, following the mechanism established in Dietz, Douglas & Shih (*Science* 2009). After this phase, applying a bend or twist modifies domain lengths, generates loop/skip markers at specific bp positions, and invalidates + regenerates the staple crossover positions.

### Deliverables (complete 2026-03-13)

- `backend/core/models.py` — `LoopSkip(bp_index, delta)` model; `Helix.loop_skips` field
- `backend/core/geometry.py` — `nucleotide_positions()` updated to skip/loop bp positions (accumulated delta, multi-skip/loop support)
- `backend/core/loop_skip_calculator.py` — `twist_loop_skips()`, `bend_loop_skips()`, `apply_loop_skips()`, `clear_loop_skips()`, `predict_global_twist_deg()`, `predict_radius_nm()`, `min_bend_radius_nm()`, `max_twist_deg()`, `validate_loop_skip_limits()`
- `backend/api/crud.py` — `POST /design/loop-skip/twist`, `POST /design/loop-skip/bend`, `GET /design/loop-skip/limits`, `DELETE /design/loop-skip`
- `tests/test_loop_skip.py` — 46 tests covering model, geometry, calculator, API helpers
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
- **V7.2 Bend topology**: Apply 90° bend R=20 nm to 6HB. "Do inner-face helices show deletions and outer-face helices show insertions in correct proportions?" (pending visual validation)
- **V7.3 Geometry update**: After applying loop/skips, "do nucleotide positions correctly omit skipped bp and add extra nucleotides for loops?" ✓ (46 geometry tests)
- **V7.4 Staple re-routing**: After topology write, trigger autostaple. "Do crossover positions update to account for modified cell lengths?" (pending)

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

- **V7.1 Twist topology**: Apply +360°/10 helices twist. Inspect loop/skip markers in properties panel. "Do 10 deletions appear, evenly spaced along the affected helices?"
- **V7.2 Bend topology**: Apply 90° bend R=20 nm to 6HB. "Do inner-face helices show deletions and outer-face helices show insertions in the correct proportions?"
- **V7.3 oxDNA validation**: Export bent structure to oxDNA, run minimization. "Does the equilibrium bend angle match the target within 10°?"
- **V7.4 Staple re-routing**: After topology write, trigger autostaple. "Do crossover positions update to account for the modified cell lengths?"

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

**Goal**: Store validated designs as `Part` objects; compose multi-part assemblies.

### Deliverables
- `backend/library/database.py` — SQLModel schema and CRUD for `Part`
- `backend/library/matcher.py` — `find_matching_parts(cross_section, length_range, lattice_type)`
- REST: `POST /api/library/part`, `GET /api/library/parts`, `GET /api/library/part/{id}`
- Assembly view: second viewport showing Parts at `local_frame` positions; interface point snapping
- Interface points shown as colored cones; snap when anti-parallel normals within threshold

### Deep Thinking Point (resolve before Phase 8)
**DTP-8: Interface point placement for clockwork assemblies.**
For sub-degree angular precision in clockwork mechanisms, manually specified interface points will accumulate error. Blunt-end interface points should be derived algorithmically from helix terminus geometry: normal = helix axis tangent, position = last bp backbone centroid. Manual specification only for toeholds, biotins, covalent bonds.

### 3D Validation Checkpoints
- **V8.1**: Interface point normal — green cone (5×) at interface point. "Does the cone tip point in the correct outward direction?"
- **V8.2**: Assembly alignment — red cone (Part A) + blue cone (Part B) + white connection arrow. "Does the proposed alignment look correct?"
- **V8.3**: Local frame — RGB axes at frame origin. "Is the frame origin at the expected location?"

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

