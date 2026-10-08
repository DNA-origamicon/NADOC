"""Authored backbone connections between successive records of one helix track.

Sweep stores its new segment as a separate helix in a separate lattice frame.
The strand domain sequence still records an ordinary phosphodiester connection
at the attachment. These edges are not crossovers or newly forced ligations.
Recognition uses authored topology and sweep attachment metadata, never geometry.
"""

from __future__ import annotations

from typing import TypeAlias


BackboneSlot: TypeAlias = tuple[str, int, str]
BackboneEdge: TypeAlias = tuple[BackboneSlot, BackboneSlot]


def _slot(helix_id, bp, direction) -> BackboneSlot:
    return helix_id, bp, getattr(direction, "value", direction)


def backbone_continuation_edges(design) -> set[BackboneEdge]:
    """Return realized, directed 3′→5′ connections along continuous helix tracks.

    A connection must already appear between adjacent non-reference strand
    domains, on the same lattice cell and polarity at consecutive bp indices.
    A sweep attachment supplies segment provenance. An explicit forced ligation
    also supplies provenance, allowing independently authored segments to join.
    Existing ligation records are never altered, including periodic metadata.
    Inserted bases are not ordinary backbone continuations and remain distinct.

    Both scaffold and staple edges are included. Merely touching coordinates,
    sharing grid cells, or having adjacent extents does not create an edge.
    """
    helices = {h.id: h for h in design.helices}
    forced = {
        (_slot(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction),
         _slot(fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)): fl
        for fl in design.forced_ligations
    }
    attachments: dict[str, list[tuple[int, int, set[str]]]] = {}
    for op in design.deformations:
        if op.type != "sweep" or op.params.start_step != 1:
            continue
        direction = op.params.direction
        boundary = op.plane_a_bp if direction == 1 else op.plane_b_bp
        members = set(op.affected_helix_ids or ())
        for hid in members:
            attachments.setdefault(hid, []).append((boundary, direction, members))

    def is_attachment(new: BackboneSlot, source: BackboneSlot) -> bool:
        h_new, h_source = helices[new[0]], helices[source[0]]
        if h_new.lattice_frame_id is None or h_new.lattice_frame_id == h_source.lattice_frame_id:
            return False
        return any(
            new[1] == boundary
            and source[1] == boundary - direction
            and source[0] not in members
            for boundary, direction, members in attachments.get(new[0], ())
        )

    edges = set()
    for strand in design.strands:
        if strand.is_reference:
            continue
        for first, second in zip(strand.domains, strand.domains[1:]):
            if first.overhang_id or first.binds_overhang_id or second.overhang_id or second.binds_overhang_id:
                continue
            a = _slot(first.helix_id, first.end_bp, first.direction)
            b = _slot(second.helix_id, second.start_bp, second.direction)
            if a[0] == b[0] or a[2] != b[2] or b[1] != a[1] + (1 if a[2] == "FORWARD" else -1):
                continue
            h_a, h_b = helices.get(a[0]), helices.get(b[0])
            if (h_a is None or h_b is None or h_a.grid_pos is None
                    or h_a.grid_pos != h_b.grid_pos or h_a.direction != h_b.direction):
                continue
            edge = a, b
            fl = forced.get(edge)
            if fl is not None:
                if not fl.extra_bases:
                    edges.add(edge)
            elif is_attachment(a, b) or is_attachment(b, a):
                edges.add(edge)
    return edges
