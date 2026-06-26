---
name: reference-deformation-theory
description: "DTP-6 architecture decisions, bend/twist theory, Phase 7 loop/skip physical mechanism, Dietz reference"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b72afce-af90-40e7-8a0f-47acf65a8eab
---

## Phase 6A — Bend/Twist UI + Geometric Deformation (complete, merged master 2026-03-14)

### DTP-6 Decisions (binding)
| ID | Decision |
|----|----------|
| DTP-6a | Geometric-layer only deformation (no topological changes, no loop/skip markers) |
| DTP-6b | Plane positions stored as integer bp indices (consistent across bundle) |
| DTP-6c | Multiple deformations in `Design.deformations: list[DeformationOp]` (ordered). Composition via accumulated world frame → enables V-shapes, zigzags. OVERLAPPING ops (same bp range) compose too — see "Combined bend+twist" below (2026-05-26). |
| DTP-6d | Plane A = Fixed; Plane B = mobile end. First selected = fixed |
| DTP-6e | Helices whose bp span OVERLAPS the [plane_a, plane_b] window are included (was: cover BOTH planes). A short helix ("tooth") ending mid-window bends along the same arc over the bp range it occupies and terminates partway. `helices_crossing_planes` uses overlap, not full-coverage (fixed 2026-05-26 — teeth.nadoc only the full-length helices were bending). |
| DTP-6f | Tool state preserved across accidental Escape if design is unmodified |
| DTP-6g | Bend direction in degrees; draggable SVG compass rose (0° = +X in cross-section) |
| DTP-6h | Confirmed deformation = one undo step. PATCH (preview) does NOT push undo |

### Models
```python
TwistParams(total_degrees, degrees_per_nm)   # mutually exclusive; positive = right-handed
BendParams(angle_deg, direction_deg)          # angle_deg = total arc angle A→B; direction_deg = 0° = +X
DeformationOp(id, type, plane_a_bp, plane_b_bp, affected_helix_ids, params)
Design.deformations: list[DeformationOp] = []
```

### Backend Deformation.py Functions
- `compute_bundle_centroid(design, bp)` → (x, y) centroid at given bp
- `world_frame_at(design, bp)` → 4×4 transform from accumulated ops up to bp
- `deformed_nucleotide_positions(helix, design)` → positions with all ops applied (in order)
- Twist math: linear α(p) rotation around bundle centroid
- Bend math: constant-curvature arc; Frenet-Serret frame; cross-section offsets in local frame
- `geometry.py` transparent — calls `deformed_nucleotide_positions` when `design.deformations` non-empty

---

## Combined bend + twist = superhelix (geometry layer, 2026-05-26)

Bend and twist ops that cover the SAME / OVERLAPPING bp range on the same helices
now compose correctly (motivating case: `workspace/teeth.nadoc` — 45° twist bp 2–251
+ 90° bend bp 0–251, both on all 16 helices). Decided WITH the user (superhelix /
coil: bend direction co-rotates with accumulated twist — physically faithful to
honeycomb loops/skips whose bend gradient is anchored to material helix positions
that twist rotates).

**The old bug.** `_frame_at_bp` / `_precompute_arm_frames` propagated ops sorted by
`plane_a_bp` along a SINGLE moving bp cursor — fine for non-overlapping V-shape/
zigzag segments, but for overlapping ranges the scalar path hit `if target_bp <=
local_b: break` at the first (lowest plane_a) op and never reached the second (so
teeth.nadoc applied bend only, twist silently dropped); the vectorised path
double-counted the spine advance.

**The fix (deformation.py).** Replaced the single cursor with integration over
**maximal sub-intervals where the SET of active ops is constant**. On each, the
combined WORLD angular velocity is constant: `ω = Σ(twist rate)·tangent +
Σ(bend rate)·binormal` (rad/bp; rates = total_angle/seg_len). A constant ω is a
steady screw, integrated in closed form: `R(s)=exp(skew(ω)s)·R_start` (left-multiply,
matches the legacy convention), spine `+= RISE·∫₀ˢ exp(skew(ω)u)·tangent du` via
Rodrigues. Helpers: `_subinterval_walk`, `_omega_world_for`, `_advance_frame`
(scalar), `_fill_subinterval` (vectorised). The per-op axis derivation is copied
verbatim from the legacy code, so a single-op sub-interval reduces EXACTLY to the old
constant-curvature arc (bend) / pure axial spin (twist) — single-op geometry is
unchanged (proven analytically + golden tests). Order-independent (ω is a vector
sum). No signature/contract change → no caller edits.

**Scope.** GEOMETRY DISPLAY ONLY (consistent with DTP-6a). The combined *loop/skip
topological* placement is still Phase 7 / a follow-up: `crud.py`'s apply-deformations
handler accumulates twist (uniform) + bend (gradient) loops/skips per-op without
composing them on a shared range or re-checking `MAX_DELTA_PER_CELL` on the sum.

Tests: `tests/test_geometry.py` — `test_single_bend_reduces_to_arc_formula`,
`test_single_twist_is_straight_axial_spin`,
`test_overlapping_bend_twist_composes_not_drops`, `test_combined_order_independent`,
`test_scalar_and_vectorised_frames_agree_for_overlap`,
`test_combined_matches_fine_step_integration`,
`test_adjacent_nonoverlapping_ops_still_compose_sequentially`.

---

## Phase 7 — Loop/Skip Topology (deferred)

### Physical Mechanism (Dietz, Douglas & Shih Science 2009)
B-DNA natural twist: 10.5 bp/turn, 34.3°/bp, 0.335 nm/bp rise.
7-bp HC cells subtend 240°.

| Modification | bp | bp/turn | Effect |
|---|---|---|---|
| Skip (−1 bp) | 6 | ~9 | Overtwisted → left torque + tension → bends **inward** / twists left |
| Loop (+1 bp) | 8 | ~12 | Undertwisted → right torque + compression → bends **outward** / twists right |
| Uniform mods | all | same | Global twist (bend cancels) |
| Gradient | varies | varies | Global bend (torsion cancels) |

### Loop/Skip Computation Theory (don't implement until Phase 7)
For uniform twist to density T (bp/turn):
```
ideal_cell_len = 7 × T/10.5
distribute mix of floor/ceil across cells (evenly spaced)
```
For bend (radius R, direction φ):
```
helix at radial offset r from centroid in direction φ:
  ΔT(r) = r × 0.335 / R    (extra/missing bp/nm)
Minimum R: R_min = W/0.429 (~6 nm for 3-row 6HB)
Working range: 6–15 bp/turn
```

### New Model Fields Required (Phase 7)
- `LoopSkip(bp: int, delta: Literal[-1, +1])` — already implemented on Helix.loop_skips
- `nucleotide_positions()` must accumulate bp offset shifts for loop/skips
- Autostaple must handle non-uniform cell lengths
- Per-helix selection/deselection UI for affected helices

## Phase Renumbering (2026-03-12)
- Phase 6: Bend/Twist UI + geometric deformation ✅
- Phase 7: Bend/Twist topology / loop-skip (deferred)
- Phase 8: Parts Library + Assembly CAD (planned)
- Phase 9: Checker Integrations (planned)

## Feasibility guards (bend/twist achievability — 2026-06-02)

`classify_deformation()` in `loop_skip_calculator.py` predicts the per-cell loop/skip
density a bend/twist `DeformationOp` will need and classifies it OK / WARN / BLOCK
**without mutating** the design. Backed by literature thresholds (in bp/turn space):

- **HARD / BLOCK** — outside **6–15 bp/turn** (|δ| > 3 per 7-bp cell). Geometric
  ceiling; you cannot place the marks. Equivalent to radius < `min_bend_radius_nm`
  or |twist| > `max_twist_deg`. From Dietz/Douglas/Shih 2009.
- **SOFT / WARN** — outside **9–12 bp/turn**. Folds with reduced yield. From Lee Tin
  Wah et al., "Automated design of 3D DNA origami with non-rasterized 2D curvature"
  (Sci. Adv. 2023): "placing crossovers such that all sections of the DNA helices are
  between 9 and 12 bp per turn will help to maintain a high yield." Tight rings fold
  poorly (high strain at low radius); a 90° bend keeps ~1–8% broken bp in MD.
- Boundaries inclusive: exactly 9/12 → OK, exactly 6/15 → WARN. Constants:
  `HARD_BP_PER_TURN_{MIN,MAX}`, `RECOMMENDED_BP_PER_TURN_{MIN,MAX}`, `RECOMMENDED_DELTA_PER_CELL=1`.

**Policy (confirmed with user):** geometric editing layer stays permissive — WARN/BLOCK
are surfaced as a live readout (`def-feasibility` div, amber/red) and a `deformation_warning`
attached to `add/update_deformation` responses (toast on commit), but never raise. The hard
422 stays only in the realization path (`twist_loop_skips`/`bend_loop_skips` at Apply). This
honours the three-layer law: geometric permissive, loop-skip realization strict.

**Live preview endpoint:** `POST /design/deformation/validate` (always 200; verdict in
`status`). `bend_twist_popup.js` polls it debounced (~120 ms) via `validateDeformation()`.

**Shared converter / bug fix:** `_bend_params_to_radius_nm(κ) = RISE / radians(κ)` matches
`deformation.py:2440`'s geometric radius. This replaced a latent crash in
`apply_loop_skips_from_deformations` (read `p.angle_deg`, which `BendParams` never had —
canonical field is `curvature_deg_per_bp`). `_bend_per_cell_deltas()` is the single per-helix
density routine shared by `bend_loop_skips` (validates+places) and `classify_deformation`
(classifies) so warning and realization never drift.

**Edge-gradient (future, not built):** MagicDNA 2.0 (Pfeifer/Castro, Sci. Adv. 2023) programs
*continuous* curvature via an oxDNA-calibrated "edge gradient" (duplex-length difference ratio
between neighbouring helix layers; effective helical spacing 3.2 nm at vertices) — no closed-form
bend-angle(edge-gradient), so NADOC stays on the discrete per-cell δ / bp-turn model for now.
