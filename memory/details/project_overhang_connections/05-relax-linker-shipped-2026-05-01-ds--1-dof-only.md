# Relax Linker (shipped 2026-05-01, ds + 1-DOF only) — supporting detail

[Topic head](../../project_overhang_connections.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Relax Linker (shipped 2026-05-01, ds + 1-DOF only)

Right-click a linker → "Relax linker" optimizes the joint angle so the dsDNA linker's connector arcs collapse to zero length (chord between anchors = duplex `(bp - 1) × BDNA_RISE_PER_BP`). v1 scope: dsDNA only, exactly 1 DOF (one `ClusterJoint` on either overhang's owning cluster, not both, no joints in shared clusters). Other cases gray out with a tooltip. Endpoint: `POST /api/design/overhang-connections/{id}/relax`. Lightweight `GET …/relax-status` mirrors the DOF check for the menu. Cluster transform composition: `q_new = q_joint(θ*) ⊗ q_existing`, `t_new = R_joint(pivot + t − O) + O − pivot` (pivot unchanged). Appends a `ClusterOpLogEntry` so the op is undoable. Implementation: [backend/core/linker_relax.py](../../../backend/core/linker_relax.py); frontend mirror helper `_linkerRelaxStatus` in [selection_manager.js](../../../frontend/src/scene/selection_manager.js).

### Joint angle range (re-added 2026-05-09)

`ClusterJoint` now carries `min_angle_deg` / `max_angle_deg` (degrees, defaults `[-180, +180]` ≡ unbounded for backwards compat with old `.nadoc` files). Honoured by the linker-relax optimizer (1-DOF grid + bracket are clipped to the window; N-DOF Powell call passes `bounds=`). API: both `AddJointBody` and `PatchJointBody` accept the fields; the model validator and the patch endpoint reject `max < min` with 400.

Still unconstrained (open work, do NOT delete this note):
- the joint rotate gizmo / live-drag UI in `cluster_gizmo.js`
- the seek/animation player when interpolating `cluster_op` log entries

When you wire those, read `joint.min_angle_deg` / `joint.max_angle_deg`, convert to radians, and clamp the user's drag delta or interpolated angle against the cluster's *current* θ relative to the joint's pose. Tests for the existing optimizer clamp live in `tests/test_joints.py` (range fields + dict round-trip + 400 on inverted range) and `tests/test_overhang_connections.py::test_relax_respects_joint_angle_bounds` (end-to-end optimizer clamp).

### Future: relax v2

- Multi-DOF (co-optimize joints on both clusters; multi-basin search).
- ssDNA target length from physics (worm-like chain or similar) instead of geometric duplex length.
- Frontend live preview before commit.

## ds-linker bridge — real geometry pipeline (shipped 2026-05-03)

Bridge nucs are now **first-class geometry payload entries** emitted by `_emit_bridge_nucs` ([backend/api/crud.py](../../../backend/api/crud.py), called at the end of `_geometry_for_helices`). The standard helix renderer draws their backbone beads / slabs / cones via the normal pipeline — no JS-synthesized bridge mesh anymore.

### Anchor lookup rule (corrected 2026-05-03)

The anchor on side X is the **complement nuc on the OH's helix at the OH's `attach`-end bp** — direct same-bp lookup, NOT a "farthest from tip" heuristic. Per the user-facing rule:
- `attach=root` → anchor at OH-crossover bp (the bonded end where OH joins the bundle)
- `attach=free_end` → anchor at the OH-free-tip bp (opposite end from the crossover)

Both cases match the `_is_comp_first` derivation in [backend/core/lattice.py](../../../backend/core/lattice.py), so the polarity rule itself is unchanged. Implemented identically in three places (must stay in sync):
- backend `_anchor_pos_and_normal` ([backend/core/linker_relax.py](../../../backend/core/linker_relax.py))
- backend `_anchor_for` inside `_emit_bridge_nucs` ([backend/api/crud.py](../../../backend/api/crud.py))
- frontend `_linkerAttachAnchor` ([frontend/src/scene/overhang_link_arcs.js](../../../frontend/src/scene/overhang_link_arcs.js))

`_anchor_pos_and_normal` now takes `conn` (not `conn_id`) so it can read `overhang_a_attach` / `overhang_b_attach`.

### Bridge axis offset for native B-DNA radius

`bridge_axis_geometry(p_a, n_a, p_b, base_count, comp_first_a, comp_first_b)` in [linker_relax.py](../../../backend/core/linker_relax.py) is the **single source of truth** for bridge geometry. Used by both `_emit_bridge_nucs` (rendering) and `_arc_chord_lengths` (relax loss).

Symmetric placement: `axis_start = (p_a + p_b) / 2 − (radial_a + radial_b)/2 · R − fz · visualLength/2` chosen so the two boundary residuals are equal in magnitude and opposite in sign. Boundary beads sit at full `HELIX_RADIUS_NM` from the axis (native B-DNA), not at radius 0. When the relax target is reached both boundary beads exactly colocalize with their anchors. Polarity-aware boundary radials:
- side A's bridge bp 0:  FORWARD if `comp_first_a` else REVERSE
- side B's bridge bp L−1: REVERSE if `comp_first_b` else FORWARD

(Mirrors `_make_bridge_domain` in [lattice.py](../../../backend/core/lattice.py).)

### Cross-helix arc dedup

The linker strand spans an OH helix and the virtual `__lnk__` helix, so its inter-domain transition would normally generate a cross-helix arc via `getCrossHelixConnections()` in [helix_renderer.js](../../../frontend/src/scene/helix_renderer.js) — duplicating the connector arc that `overhang_link_arcs.js` already draws. Fix: skip any cross-helix connection where either side is a `__lnk__` helix (both the strand-cone branch and the placed-crossover branch).

### Right-click on bridge bead → linker context menu

Right-click on any part of a linker strand (complement bead, bridge bead, or strand cone) now routes to `_showLinkerMenu` (Delete + Relax), not `_showColorMenu`. Single dispatch point in [selection_manager.js](../../../frontend/src/scene/selection_manager.js): `directLinkerConn = linkerConnectionForStrandId(hitCone?.strandId ?? hitBead?.nuc?.strand_id)`.

### Debug overlay (Help → "Show Linker Anchor Debug")

Per side: red OH tip · pink OH attach · green anchor · cyan bridge bp. Cyan must coincide with green post-relax; pre-relax there's a visible offset.

### Critical gotcha for future linker work

Three independent pieces of code compute the bridge anchor and geometry. They MUST stay in lockstep, otherwise the rendered bridge, the relax loss, and the debug overlay will disagree:
1. `_anchor_pos_and_normal` (linker_relax.py) — relax loss + debug
2. `_anchor_for` inside `_emit_bridge_nucs` (crud.py) — backend rendering
3. `_linkerAttachAnchor` (overhang_link_arcs.js) — connector arc anchor in JS

For the bridge geometry, `bridge_axis_geometry` in linker_relax.py is the shared helper — DO NOT duplicate its math. The JS `_makeDsLinkerMeshes` no longer needs to compute bridge geometry at all; it just looks up bridge boundary positions from the geometry payload via `_bridgeBoundaryPos(nucsByStrand, connId, side, bp)`.

The JS-synthesized bridge mesh (beads/slabs/cones/coarse-cylinder) was removed entirely from `_makeDsLinkerMeshes`. The function now only draws the two connector arcs (anchor → bridge boundary). DO NOT re-add bridge mesh synthesis to `_makeDsLinkerMeshes` — the standard helix renderer handles it now. If you do, you'll get double-rendered bridges.

### Relax loss MUST be chord-magnitude-only (decoupled from bridge offset)

`_arc_chord_lengths` returns `|visualLength − |chord||/2` per side — a SCALAR magnitude residual, NOT the full 3D anchor-to-bridge-boundary distance. Fixed 2026-05-03 after the hinge over-relaxed to a fully-collapsed configuration. Why folding the bridge boundary offset into the loss is a trap: the boundary radials sit perpendicular to the chord, so the "gap to anchor" term decomposes into two INDEPENDENT components — a chord-magnitude residual AND a perpendicular term that varies with chord DIRECTION. The perpendicular term creates a degenerate minimum near chord ≈ 0 (the fz-fallback frame at chord = 0 makes some of the perpendicular offset cancel), and the optimizer happily collapses the hinge into a chord ≈ 0 saddle. The only physically meaningful relax constraint is `|chord| → visualLength` (the bridge duplex spans its native length); the small perpendicular offset between anchor and bridge boundary post-relax is absorbed by the connector arc visualisation.

DO NOT re-fold the boundary offset into the relax loss. If you ever need a tighter post-relax visual fit, do it by changing the rendering (e.g. shifting the bridge axis to anchor one boundary exactly, accepting a small offset on the other) — never by adding the perpendicular term back to the loss.

`comp_first_a`/`comp_first_b` are still passed to `_arc_chord_lengths` for API symmetry with `bridge_axis_geometry`, but the scalar form ignores them.

### Multi-minima selection in 1-DOF relax (shipped 2026-05-03, commit 7d8e093)

A 1-DOF cluster rotation typically produces **two** θ values per period at which `|chord| = visualLength` — chord descends through the target on one side of its valley, ascends through it on the other. They can be 50°+ apart, and very often only one of them avoids clashing with neighbouring clusters / scaffold geometry.

The prior optimizer used coarse-grid `argmin` + bracketed `minimize_scalar` refine — which deepest-valley the grid happened to sample first decided the choice, effectively at random. A small λ·θ² regularizer in the loss is **not** strong enough to swing the grid pick (the chord term has nm² scale and dominates the grid sort).

**Current 1-DOF strategy** (`_optimize_angle` in `linker_relax.py`):
1. Pure `chord_loss(θ)` (no regularizer) — used everywhere so refinement converges on the actual chord minimum.
2. Enumerate ALL grid local minima (`losses[i] < losses[i±1]` with periodic wrap).
3. Refine each in its ±2-step bracket with `minimize_scalar`.
4. Among refined minima within `tol = 1e-6` nm² of the best chord-residual, pick the smallest `|θ|`.

Test case (polymer hinge): two minima at θ ≈ −36.79° and θ ≈ −18.00°; both achieve chord = 9.686 nm. Old optimizer picked −36.79° (clashed). New optimizer picks −18.00° (clean).

**Multi-DOF path keeps the λ·θ² regularizer** in its Powell loss because Powell only finds one basin per call — `enumerate-all-minima` doesn't apply. `_THETA_REG_LAMBDA = 1e-3` is small enough that it never distorts chord fit but breaks ties between near-equivalent basins seeded from different θ_0.

### Bridge axis side / `_BRIDGE_PHASE_OFFSET` (shipped 2026-05-03, commit 7d8e093)

The symmetric `bridge_axis_geometry` placement puts the bridge axis on one specific side of the chord. The user wanted the opposite side (visually reads better against neighbouring structure — bridge sits ON TOP of the join rather than UNDER it).

The fix: a single constant `_BRIDGE_PHASE_OFFSET = π` added to every bridge radial angle. Applied IDENTICALLY in two places that MUST stay in sync:
- `_bridge_boundary_radials` in `linker_relax.py` (used by `bridge_axis_geometry` to compute axis_start)
- `_emit_bridge_nucs` in `crud.py` (used to place every per-bp bead, both boundary AND interior)

If those two diverge, the rendered bridge sits in a different place than what the relax loss / debug overlay believes, and gaps look wrong.

To flip the bridge to the other side again, change `_BRIDGE_PHASE_OFFSET` between `0.0` and `π` (any value works mathematically — π is just the symmetric flip — but only `0` and `π` give sensible duplex geometry, since other values rotate the radials without flipping which strand is which).

Net geometric effect: the gap vector `bridge − anchor` exactly negates (same magnitude, opposite direction); the duplex itself is 180°-rotated around its own axis (still a valid B-DNA duplex).
