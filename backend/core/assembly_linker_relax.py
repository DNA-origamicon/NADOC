"""Rigid-placement relax for cross-part ds linkers (AssemblyOverhangConnection).

The per-design ``relax_linker`` (:mod:`backend.core.linker_relax`) rotates the
overhangs' owning *clusters* about their ``ClusterJoint`` axes to bring the
bridge duplex to its native length. The cross-part case is different: relax is a
closed-form **two-translation** placement (per the 2026-05-21 decision) — no
rotation, so it never reorients an otherwise-unconstrained part:

1. Generate the bridge from the current overhang anchors and read its two
   boundary beads (the ends the connector arcs attach to).
2. **T1 — slide the bridge** so its FIXED-side boundary bead lands exactly on
   the fixed overhang's anchor (closes the fixed-side connector arc).
3. **T2 — slide the MOVED part** (pure translation) so its overhang anchor lands
   on the bridge's other boundary bead, after T1 (closes the moved-side arc).

Both connector arcs collapse to ~0. The bridge ends up rigidly extending from
the fixed overhang (it is NO LONGER auto-centered between the two parts). Since
the moved part is translated only, every overhang's binding domain (its
complement) stays fixed relative to that overhang.

*v1 limitation*: satisfies the ONE connection being relaxed. If the moving part
carries other linkers, relaxing one may disturb them — same one-at-a-time model
as per-design relax. ds only; ss/FJC deferred.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np

from backend.core.models import Direction
from backend.core.lattice import _opposite_direction
from backend.core.assembly_linker import _world_axes_for_helix


# ── Status / gate ────────────────────────────────────────────────────────────
def assembly_relax_status(assembly, conn, inst_a, inst_b) -> dict[str, Any]:
    """Describe whether a cross-part linker can be rigid-place relaxed.

    Returns ``{available, reason, movable_instance_id, fixed_instance_id,
    linker_type}``. Which part moves (mirrors the per-design bind-relax
    side-A-driver tiebreak): exactly one side ``fixed`` → the other moves;
    neither fixed → side A is held, B moves; both fixed → unavailable.
    """
    out = {
        "available": False,
        "reason": "",
        "movable_instance_id": None,
        "fixed_instance_id": None,
        "linker_type": conn.linker_type,
    }
    if conn.linker_type != "ds":
        out["reason"] = "ss linker relax is not supported yet (ds only)."
        return out
    if conn.length_value == 0:
        out["reason"] = "Indirect linker has no materialized bridge to relax."
        return out
    if inst_a.id == inst_b.id:
        out["reason"] = "Both overhangs are on the same part instance; moving it can't relax the linker."
        return out

    a_fixed = bool(getattr(inst_a, "fixed", False))
    b_fixed = bool(getattr(inst_b, "fixed", False))
    if a_fixed and b_fixed:
        out["reason"] = "Both parts are fixed; free a part to relax."
        return out
    if a_fixed:        # only A fixed → move B
        fixed_id, movable_id = inst_a.id, inst_b.id
    elif b_fixed:      # only B fixed → move A
        fixed_id, movable_id = inst_b.id, inst_a.id
    else:              # neither fixed → hold A, move B
        fixed_id, movable_id = inst_a.id, inst_b.id

    out.update(available=True, reason="", movable_instance_id=movable_id,
               fixed_instance_id=fixed_id)
    return out


# ── Anchor + axial exit direction ────────────────────────────────────────────
def _world_anchor_axial(design, instance, ovhg_id: str, attach: str,
                        oh_dom) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """World ``(anchor_position, axial_exit_direction)`` at the overhang's
    attach end.

    ``anchor_position`` is the complement-nuc position (identical to
    :func:`backend.core.assembly_linker._world_anchor`). ``axial_exit_direction``
    is the unit vector pointing from the overhang body out through the attach
    end — the direction the bridge duplex extends. Computed as
    ``normalize(pos(attach_bp) − pos(other_end_bp))`` so it is sign-correct by
    construction (the bridge continues the overhang's helix axis past the
    anchor). Falls back to the helix world axis for a degenerate 1-bp overhang.
    """
    if oh_dom is None:
        return None
    helix = design.find_helix(oh_dom.helix_id)
    if helix is None:
        return None

    from backend.core.deformation import deformed_nucleotide_arrays

    tip_bp  = oh_dom.end_bp if ovhg_id.endswith("_3p") else oh_dom.start_bp
    root_bp = oh_dom.start_bp if tip_bp == oh_dom.end_bp else oh_dom.end_bp
    attach_bp = tip_bp if attach == "free_end" else root_bp
    other_bp  = root_bp if attach == "free_end" else tip_bp
    direction = _opposite_direction(oh_dom.direction)
    dir_int   = 0 if direction == Direction.FORWARD else 1

    arrs    = deformed_nucleotide_arrays(helix, design)
    bp_arr  = arrs["bp_indices"]
    dir_arr = arrs["directions"]

    def _pos_local(bp: int) -> Optional[np.ndarray]:
        m = (bp_arr == bp) & (dir_arr == dir_int)
        if not m.any():
            return None
        return np.asarray(arrs["positions"][int(m.argmax())], dtype=float)

    pos_attach = _pos_local(attach_bp)
    if pos_attach is None:
        return None
    pos_other = _pos_local(other_bp)

    T = instance.transform.to_array()
    R = T[:3, :3]
    pos_world = (T @ np.array([pos_attach[0], pos_attach[1], pos_attach[2], 1.0]))[:3]

    if pos_other is not None and not np.allclose(pos_other, pos_attach):
        axdir_world = R @ (pos_attach - pos_other)
    else:
        # Degenerate 1-bp overhang: use the helix world axis, oriented away
        # from the helix midpoint toward the attach position.
        ws, we = _world_axes_for_helix(helix, T)
        axis = we - ws
        if np.dot(axis, pos_world - 0.5 * (ws + we)) < 0:
            axis = -axis
        axdir_world = axis

    n = float(np.linalg.norm(axdir_world))
    if n < 1e-9:
        return None
    return pos_world, axdir_world / n


# ── Connector-arc endpoints (ACTUAL emitted backbone beads) ───────────────────
def _connector_arc_endpoints(nucs: list, strands: list, conn) -> dict[str, Optional[Tuple[np.ndarray, np.ndarray]]]:
    """``{'a': (anchor, bead), 'b': (anchor, bead)}`` — the two ends of each ds
    side strand's rendered connector arc, read from the EMITTED ``nucs``:

      - ``anchor`` = the COMPLEMENT-domain junction backbone bead (on the part's
        helix) — the overhang's binding-domain end, the same actual 3D coordinate
        the per-design ``_anchor_pos_and_normal`` reads.
      - ``bead``   = the BRIDGE-domain junction backbone bead (on the ``__lnk__``
        helix) — the other end of the arc.

    The junction is the cross-helix domain transition ``domain[i].end_bp ↔
    domain[i+1].start_bp`` where exactly one adjacent domain is on the ``__lnk__``
    bridge helix (mirrors the frontend ``_buildAssemblyConnectorArcs``). ``None``
    for a side whose beads aren't both present in the emission.
    """
    bridge_hid = f"__lnk__{conn.id}"
    pos: dict = {}
    for n in nucs:
        sid, hid, bp = n.get("strand_id"), n.get("helix_id"), n.get("bp_index")
        p = n.get("backbone_position") or n.get("base_position")
        if sid is not None and hid is not None and bp is not None and p is not None:
            pos[(sid, hid, int(bp))] = np.asarray(p, dtype=float)

    strand_by_id = {s.id: s for s in strands}
    out: dict[str, Optional[Tuple[np.ndarray, np.ndarray]]] = {"a": None, "b": None}
    for side in ("a", "b"):
        sid = f"__lnk__{conn.id}__{side}"
        strand = strand_by_id.get(sid)
        if strand is None:
            continue
        domains = strand.domains or []
        for i in range(len(domains) - 1):
            d0, d1 = domains[i], domains[i + 1]
            d0_bridge = (d0.helix_id == bridge_hid)
            d1_bridge = (d1.helix_id == bridge_hid)
            if d0_bridge == d1_bridge:
                continue   # need exactly one bridge domain in this adjacent pair
            p0 = pos.get((sid, d0.helix_id, int(d0.end_bp)))
            p1 = pos.get((sid, d1.helix_id, int(d1.start_bp)))
            if p0 is None or p1 is None:
                continue
            # The bridge-side junction nuc is the bead; the other is the anchor.
            anchor, bead = (p1, p0) if d0_bridge else (p0, p1)
            out[side] = (anchor, bead)
            break
    return out


# ── Placement solver (two translations, on the ACTUAL emitted beads) ──────────
def relax_assembly_linker(
    conn, nucs: list, strands: list, inst_moved,
    *, movable_instance_id: str, fixed_instance_id: str,
) -> Tuple[list[float], list[float], dict[str, Any]]:
    """Two-translation, rotation-free relax computed on the ACTUAL emitted
    backbone-bead coordinates (``nucs`` from
    :func:`backend.api.assembly._linker_geometry_for_assembly`, generated with a
    fresh bridge). This is the assembly analog of the per-design relax, which
    likewise minimizes the real ``_anchor_pos_and_normal`` bead positions — not a
    re-derived approximation.

    - **T1** slides the whole bridge so its FIXED-side boundary bead lands on the
      fixed overhang's complement-junction anchor (closes the fixed-side arc).
    - **T2** slides the MOVED part (pure translation) so its complement-junction
      anchor lands on the bridge's other boundary bead after T1 (closes the
      moved-side arc).

    Returns ``(moved_transform_values, bridge_translation, info)`` — the movable
    part's 16-float world transform (a pure translation of its current one) and
    the 3-vector the caller must apply to the ``__lnk__`` bridge helix.
    """
    endpoints = _connector_arc_endpoints(nucs, strands, conn)
    side_f = "a" if fixed_instance_id == conn.instance_a_id else "b"
    side_m = "b" if side_f == "a" else "a"
    ef, em = endpoints.get(side_f), endpoints.get(side_m)
    if ef is None or em is None:
        raise ValueError("Could not resolve connector-arc beads from emitted geometry.")
    anchor_f, bead_f = ef
    anchor_m, bead_m = em

    # T1: slide the bridge so its fixed-side bead lands on the fixed anchor.
    t1 = anchor_f - bead_f
    # T2: slide the moved part so its anchor lands on the moved bead after T1.
    t2 = (bead_m + t1) - anchor_m

    # Movable part — pure world translation (rotation block unchanged).
    D = np.eye(4); D[:3, 3] = t2
    T_new = D @ inst_moved.transform.to_array()

    info = {
        "moved_instance_id": movable_instance_id,
        "fixed_instance_id": fixed_instance_id,
        "bridge_translation_nm": [float(v) for v in t1],
        "part_translation_nm":   [float(v) for v in t2],
        # The arc lengths this move is closing (actual emitted-bead distances).
        "pre_arc_fixed_nm": float(np.linalg.norm(bead_f - anchor_f)),
        "pre_arc_moved_nm": float(np.linalg.norm(bead_m - anchor_m)),
    }
    return [float(v) for v in T_new.flatten()], [float(v) for v in t1], info
