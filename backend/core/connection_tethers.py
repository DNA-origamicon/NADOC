"""Free-until-taut tethers from a REGULAR cluster's applied overhang CONNECTIONS —
directly-connected duplexes + ss/ds linker bridges — for the move/rotate tool's
"Constrained (tethers)" drag.

Companion to:
  * ``flexible_segments.derive_flexible_connections`` — ssDNA flexible-segment tethers.
  * ``duplex_cluster.duplex_cluster_tethers`` — tethers for the DUPLEX child cluster itself.

This module answers the complementary question: when a user drags a REGULAR part cluster,
which of ITS overhang connections should pull back (free until taut)? Each returned tether
is ``{moving:{helix_id,bp,direction}, fixed:{helix_id,bp,direction}, contour_nm}`` — the same
shape the gizmo's ssDNA projector consumes — with ``moving`` on the dragged cluster and
``fixed`` on the partner.

Contours (user decision 2026-07-01):
  * directly-connected duplex → ~0.67 nm (one backbone bond): a near-rigid junction, so the
    parts may pivot/wobble about the connection but not pull apart.
  * ss linker → n_bases · SSDNA_RISE_PER_BASE_NM (flexible, like an ssDNA segment).
  * ds linker → (n_bp − 1) · BDNA_RISE_PER_BP (free-until-taut at the duplex length).

Display/pose layer only — never mutates topology.
"""
from __future__ import annotations

from backend.core.constants import SSDNA_RISE_PER_BASE_NM
from backend.core.models import Design


def _dir_value(d):
    return getattr(d, "value", d)


def _bead_owner_resolver(design: Design, remap_duplex: bool = True):
    """(helix_id, bp, direction) → owning cluster id. When ``remap_duplex`` (default), a duplex
    CHILD cluster is remapped to its parent (a duplex rides its parent under a rigid move, so its
    beads move with the parent) — matching the ssDNA gate's notion of "which rigid body carries
    this bead". With ``remap_duplex=False`` the duplex child is reported as itself, so a caller can
    tell a bead ON the duplex LINK apart from a bead on a part."""
    from backend.core.flexible_segments import _build_bead_graph, _owning_cluster_id

    _adj, bead_domain = _build_bead_graph(design)
    parent_of = ({c.id: c.parent_cluster_id
                  for c in design.cluster_transforms if c.overhang_duplex_driver_id}
                 if remap_duplex else {})

    def resolve(helix_id, bp, direction):
        # bead_domain keys are (helix, bp, Direction-enum); match on value to accept strings.
        sd = None
        key = None
        for k, v in bead_domain.items():
            if k[0] == helix_id and k[1] == bp and _dir_value(k[2]) == _dir_value(direction):
                sd, key = v, k
                break
        if key is None:
            return None
        cid = _owning_cluster_id(design, key, sd)
        return parent_of.get(cid, cid)  # duplex child → parent (when remap)

    return resolve


def _overhang_domain(design: Design, oh_id: str):
    """(strand, domain_index, domain) for the overhang's tagged domain, or None."""
    for s in design.strands:
        for di, d in enumerate(s.domains):
            if d.overhang_id == oh_id:
                return s, di, d
    return None


def _overhang_attach_bead(design: Design, oh_id: str, attach: str) -> dict | None:
    """The (helix_id, bp, direction) bead at an overhang's ``root`` (bundle junction) or
    ``free_end`` (tip). Junction-bp convention mirrors ``deformation`` / ``direct_relax``:
    the root is ``end_bp`` when the overhang domain is the strand's FIRST domain, else
    ``start_bp``; the free end is the opposite terminus of the overhang domain."""
    got = _overhang_domain(design, oh_id)
    if got is None:
        return None
    s, di, d = got
    root_bp = d.end_bp if di == 0 else d.start_bp
    free_bp = d.start_bp if di == 0 else d.end_bp
    bp = root_bp if attach == "root" else free_bp
    return {"helix_id": d.helix_id, "bp": int(bp), "direction": _dir_value(d.direction)}


def _linker_contour_nm(conn) -> float:
    from backend.core.linker_relax import _ds_target_length_nm, _linker_bp

    if conn.linker_type == "ds":
        return float(_ds_target_length_nm(conn))
    return float(_linker_bp(conn) * SSDNA_RISE_PER_BASE_NM)


def cluster_connection_tethers(design: Design, cluster) -> list[dict]:
    """Tethers from ``cluster``'s applied overhang connections (direct duplex + ss/ds linker)
    to the partner cluster. moving = anchor on ``cluster``; fixed = anchor on the partner.

    Skips connections where both ends or neither end land on ``cluster`` (both ends on one
    rigid body ⇒ they move together, no constraint). Never mutates topology."""
    from backend.core.duplex_cluster import duplex_cluster_tethers

    owner = _bead_owner_resolver(design)
    cid = cluster.id
    out: list[dict] = []
    seen: set = set()

    def _emit(a: dict, b: dict, contour: float, rigid: bool = False):
        # a, b are {helix_id, bp, direction}; decide which rides `cluster`.
        oa = owner(a["helix_id"], a["bp"], a["direction"])
        ob = owner(b["helix_id"], b["bp"], b["direction"])
        if oa == cid and ob != cid:
            moving, fixed = a, b
        elif ob == cid and oa != cid:
            moving, fixed = b, a
        else:
            return  # both/neither on this cluster → no relative constraint
        sig = (moving["helix_id"], moving["bp"], _dir_value(moving["direction"]),
               fixed["helix_id"], fixed["bp"], _dir_value(fixed["direction"]))
        if sig in seen:
            return
        seen.add(sig)
        # `rigid` = bilateral distance (resists compression AND extension) — a ds-linker rod
        # acting as a fixed-length strut with ball joints at both ends. Non-rigid = free-until-taut.
        out.append({"moving": moving, "fixed": fixed, "contour_nm": float(contour), "rigid": bool(rigid)})

    # 1. Directly-connected duplexes. When the dragged cluster is the duplex's PARENT, the duplex
    #    rides it rigidly, so it's a STATIC tether to the OTHER part (handled here). When the dragged
    #    cluster is the NON-parent part, the duplex is a MOVABLE LINK that swings — handled by
    #    `cluster_movable_links`, NOT a static tether — so skip it here to avoid double-constraining.
    for dcl in design.cluster_transforms:
        if not dcl.overhang_duplex_driver_id:
            continue
        if dcl.parent_cluster_id != cid:
            continue
        for t in duplex_cluster_tethers(design, dcl):
            _emit(t["moving"], t["fixed"], t["contour_nm"])

    # 2. ss/ds linker bridges (OverhangConnection metadata). A ds linker is a rigid rod
    #    (bilateral strut); an ss linker is a flexible free-until-taut tether.
    for conn in getattr(design, "overhang_connections", []) or []:
        a_bead = _overhang_attach_bead(design, conn.overhang_a_id, conn.overhang_a_attach)
        b_bead = _overhang_attach_bead(design, conn.overhang_b_id, conn.overhang_b_attach)
        if a_bead and b_bead:
            _emit(a_bead, b_bead, _linker_contour_nm(conn), rigid=(conn.linker_type == "ds"))

    return out


def cluster_movable_links(design: Design, cluster) -> list[dict]:
    """Movable INTERMEDIATE links for dragging ``cluster`` (part A), with the partner part B held
    fixed and the link swinging to follow. Today: overhang-duplex child clusters, which have a
    backbone bond to a root on EACH part — a genuine hinge body between the two parts.

    Each descriptor:
      {kind:'duplex', link_cluster_id, helix_ids, domain_ids,
       tethers:[{l:{helix,bp,dir}, part:{helix,bp,dir}, contour_nm, part_dragged:bool}]}
    where `l` rides the link body and `part` rides a part cluster (`part_dragged` = it's on A, so
    its world position must be re-read from A's live pose each frame; else it's on fixed B).

    ds/ss LINKER bridges are NOT movable-body links (the rod is rendered from its anchors and is
    handled by the rigid/free connection tether) — they emit no link body here."""
    from backend.core.duplex_cluster import duplex_cluster_tethers

    raw_owner = _bead_owner_resolver(design, remap_duplex=False)
    cid = cluster.id
    links: list[dict] = []
    for dcl in design.cluster_transforms:
        if not dcl.overhang_duplex_driver_id:
            continue
        # Dragging the duplex's OWN parent → the duplex rides it rigidly (a static tether to the
        # other part, via cluster_connection_tethers), NOT a swinging link. Only the NON-parent
        # part sees the duplex as a movable intermediate body.
        if dcl.parent_cluster_id == cid:
            continue
        tethers: list[dict] = []
        touches_a = False
        for t in duplex_cluster_tethers(design, dcl):
            l_bead = t["moving"]   # on the duplex link (its tip/connecting bead)
            p_bead = t["fixed"]    # root bead on a part
            p_owner = raw_owner(p_bead["helix_id"], p_bead["bp"], p_bead["direction"])
            part_dragged = (p_owner == cid)
            if part_dragged:
                touches_a = True
            tethers.append({
                "l": l_bead, "part": p_bead,
                "contour_nm": t["contour_nm"], "part_dragged": part_dragged,
            })
        # Only a link that actually bonds to the dragged part is relevant to its drag.
        if touches_a and len(tethers) >= 2:
            links.append({
                "kind": "duplex",
                "link_cluster_id": dcl.id,
                "helix_ids": list(dcl.helix_ids or []),
                "domain_ids": [dr.model_dump() for dr in (dcl.domain_ids or [])],
                "tethers": tethers,
            })
    return links


def clusters_with_connection_tethers(design: Design) -> list[str]:
    """Ids of the (non-duplex) clusters that have ≥1 connection tether — drives the
    move/rotate "Constrained (tethers)" option's availability alongside the ssDNA gate."""
    out: list[str] = []
    for c in design.cluster_transforms:
        if c.overhang_duplex_driver_id:
            continue
        if cluster_connection_tethers(design, c) or cluster_movable_links(design, c):
            out.append(c.id)
    return out
