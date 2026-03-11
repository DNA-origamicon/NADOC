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

### Phase offset convention (binding, 2026-03-11)
For helices along +Z, `_frame_from_helix_axis` gives `frame[:,0]=(0,-1,0)`, `frame[:,1]=(1,0,0)`.
- **FORWARD cells (val=0)**: `phase_offset = 315° (= 7 × 45°)`
- **REVERSE cells (val=1)**: `phase_offset = 0°`

Rationale: r1,c0 REVERSE bead faces 30° at bp=0 (toward r2,c1 neighbor) with phase_offset=0. r2,c1 FORWARD ideally needs 210° (requires 300°), but 315° (nearest 45° multiple) gives only 15° error and yields **4 valid crossover bp positions per helix turn** (exhaustively verified across all 85 honeycomb edges). Using 0° for FORWARD gives 0 valid crossover positions.

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

**Status: 🔄 In Progress — backend complete, frontend proximity markers implemented**

**Goal**: Enable staple crossovers between neighboring helices using true topological strand split+reconnect (caDNAno style). Crossover candidates appear as proximity-fading cyan cylinders; clicking one places the crossover.

### DTP-4 (recorded 2026-03-11)
- Crossover placement uses geometrically pre-computed positions only (consistent with DTP-0b).
- Valid positions use `valid_crossover_positions()` with `direction_a`/`direction_b` tracking which strand direction is closest.
- Placement is topological: `make_staple_crossover()` splits the two staple strands at the target bp and reconnects them so the backbone path jumps between helices.
- No explicit "crossover mode" — proximity markers are always on; Ctrl+K crossover command removed.
- Scaffold strands are never affected by staple crossover placement.

### Deliverables (complete)
- `backend/core/crossover_positions.py` — `CrossoverCandidate` with `direction_a`/`direction_b` fields
- `backend/core/lattice.py` — `make_staple_crossover()`, `_find_strand_at()`
- `backend/api/crud.py` — `GET /design/crossovers/all-valid`, `POST /design/staple-crossover`
- `frontend/src/api/client.js` — `getAllValidCrossovers()`, `addStapleCrossover()`
- `frontend/src/scene/crossover_markers.js` — proximity-based cylinder markers, gold highlight on hover, click-to-place
- `tests/test_crossover_positions.py` — direction field correctness (3 new tests)
- `tests/test_lattice.py` — `make_staple_crossover` correctness (7 new tests)
- `tests/test_crud.py` — all-valid and staple-crossover endpoint tests (7 new tests)

### 3D Validation Checkpoints
- **V4.1**: Load a 2-helix bundle, hover near a helix pair. "Do cyan cylinders appear between the two helices where a crossover is geometrically possible?"
- **V4.2**: Move cursor to within ~40px of a cylinder. "Does it turn gold and reach full opacity?"
- **V4.3**: Click a gold cylinder. "Does the strand topology update (strand domains split and reconnect correctly)?"

---

## Phase 5 — Physics Layer (XPBD + oxDNA Interface)

**Goal**: Real-time XPBD relaxation for feedback; batch oxDNA for validation.

### Deliverables
- `backend/physics/xpbd.py` — Numba JIT constraint engine (bond length + excluded volume first)
- `backend/api/ws.py` — WebSocket: `start_physics` → stream position updates at ~30 fps; `reset_physics` on design edit; never write back to `Design`
- `backend/physics/oxdna_interface.py` — `write_oxdna_input()`, `run_oxdna()`, `read_oxdna_trajectory()`
- Frontend: design mode (geometric) vs. physics mode (relaxed) toggle with visual indicator
- `tests/test_xpbd.py` — convergence, energy monotonically decreasing (or bounded)

### Deep Thinking Point (resolve before Phase 5)
**DTP-5: XPBD force model scope.**
Minimum viable constraints for structural relaxation: backbone bond length + excluded volume. Adding backbone angle constraints improves helix rigidity but complicates tuning. Defer electrostatics and base-pairing. Validate convergence on a single helix before adding constraints.

### 3D Validation Checkpoints
- **V5.1**: Single helix XPBD relaxation — before (white) and after (yellow) overlay. "Is the yellow helix still recognizably a helix?"
- **V5.2**: oxDNA round-trip — geometric positions (white) vs. read-back from oxDNA file (cyan). "Are any cyan spheres displaced from their white counterpart?"
- **V5.3**: Mode toggle — switch design↔physics 3 times. "Do positions change each time, and do design-mode positions return exactly?"

---

## Phase 6 — Parts Library and Assembly CAD

**Goal**: Store validated designs as `Part` objects; compose multi-part assemblies.

### Deliverables
- `backend/library/database.py` — SQLModel schema and CRUD for `Part`
- `backend/library/matcher.py` — `find_matching_parts(cross_section, length_range, lattice_type)`
- REST: `POST /api/library/part`, `GET /api/library/parts`, `GET /api/library/part/{id}`
- Assembly view: second viewport showing Parts at `local_frame` positions; interface point snapping
- Interface points shown as colored cones; snap when anti-parallel normals within threshold

### Deep Thinking Point (resolve before Phase 6)
**DTP-6: Interface point placement for clockwork assemblies.**
For sub-degree angular precision in clockwork mechanisms, manually specified interface points will accumulate error. Blunt-end interface points should be derived algorithmically from helix terminus geometry: normal = helix axis tangent, position = last bp backbone centroid. Manual specification only for toeholds, biotins, covalent bonds.

### 3D Validation Checkpoints
- **V6.1**: Interface point normal — green cone (5×) at interface point. "Does the cone tip point in the correct outward direction?"
- **V6.2**: Assembly alignment — red cone (Part A) + blue cone (Part B) + white connection arrow. "Does the proposed alignment look correct?"
- **V6.3**: Local frame — RGB axes at frame origin. "Is the frame origin at the expected location?"

---

## Phase 7 — Checker Integrations

**Goal**: Close the validation loop with oxDNA minimization, CanDo, SNUPI.

### Deliverables
- `backend/checkers/oxdna_checker.py` — minimization job + `ValidationRecord` update
- `backend/checkers/cando_checker.py` — CanDo API integration
- `backend/checkers/snupi_checker.py` — local SNUPI binary wrapper
- Checker panel: status rows per checker, run buttons, result summaries

### 3D Validation Checkpoints
- **V7.1**: oxDNA RMSD heat map — green→yellow→red per nucleotide. "Are high-RMSD nucleotides at expected locations (crossovers, termini)?"
- **V7.2**: CanDo flexibility map — blue→red RMSF heat map. "Do flexible regions match design intent?"

---

## Cross-Cutting: Documentation Protocol

At end of each phase, before marking complete:
1. Update `MEMORY.md` with confirmed conventions from validation checkpoints
2. Create/update topic file in `memory/` for phase-specific notes
3. Update `README.md` with current feature set
4. Record any DTP decisions in `memory/architecture_decisions.md`

## Cross-Cutting: Anti-Drift Rule

Each phase's validation checkpoints must be signed off before Phase N+1 begins. A failed checkpoint means the phase is incomplete, regardless of how much else is done.
