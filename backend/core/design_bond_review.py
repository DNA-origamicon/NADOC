"""Read-only review of realized backbone connectivity and native Full geometry.

The denominators are unique covalent edges in the existing strand paths, never
the number of crossover records. Pending terminal connections are not bonds.
Reference strands are excluded. The canonical nucleotide walker accounts for
loop copies, skips, nucleotide extensions and junction inserts; no design or
geometry is constructed or repaired here.

The 1.2 nm cutoff is a conservative native Full displayed-backbone endpoint
envelope, not an O3'-P chemical bond-length criterion. Geometry that the Full
projection does not supply (currently including junction-insert nucleotides)
is reported as incomplete rather than interpolated into a passing result.
"""

from __future__ import annotations

from collections import defaultdict
import math

from backend.core.design_geometry import _geometry_for_design
from backend.core.topology_integrity import forced_edge, half_slot
from backend.physics.oxdna_interface import _walk_strand_nucleotides


FULL_BACKBONE_ENVELOPE_NM = 1.2
_MAX_EXAMPLES = 20


def _exceeds_threshold(count: int, total: int) -> bool:
    """Strictly more than one fifth, without floating-point boundary rounding."""
    return total > 0 and count * 5 > total


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _slot(key: tuple) -> tuple:
    return key[:3]


def _realized_edges(design):
    """Return unique physical edges and their directed path annotations.

    Junction inserts replace a direct endpoint bond with their actual chain of
    bonds. Each such bond inherits the flanking junction's forced/interhelix
    classification. Duplicated records cannot multiply a physical edge.
    """
    # The shared export walker can associate a crossover insert by its source
    # half. Require both endpoints here: a pending/mismatched annotation must not
    # manufacture an insert chain at a different realized strand junction.
    insert_endpoints = {
        record.id: (forced_edge(record), True)
        for record in design.forced_ligations
        if record.extra_bases
    }
    insert_endpoints.update({
        record.id: ((half_slot(record.half_a), half_slot(record.half_b)), False)
        for record in design.crossovers
        if record.extra_bases
    })
    paths = defaultdict(list)
    nodes = {}
    for step in _walk_strand_nucleotides(design):
        if step.strand.is_reference:
            continue
        if step.is_extra_base:
            actual = (_slot(step.flank_prev_key), _slot(step.flank_next_key))
            recorded, directed = insert_endpoints.get(step.key[1], (None, True))
            if recorded != actual and (directed or recorded != actual[::-1]):
                continue
        paths[step.strand_idx].append(step)
        nodes.setdefault(step.key, step)

    records = defaultdict(list)
    for index, record in enumerate(design.forced_ligations):
        records[forced_edge(record)].append(index)
    matched_records = set()
    edges = {}
    for path in paths.values():
        for first, second in zip(path, path[1:]):
            extra = first if first.is_extra_base else second if second.is_extra_base else None
            if extra is not None:
                directed_slots = (_slot(extra.flank_prev_key), _slot(extra.flank_next_key))
                interhelix = directed_slots[0][0] != directed_slots[1][0]
            elif first.helix_id is not None and second.helix_id is not None:
                directed_slots = (_slot(first.key), _slot(second.key))
                interhelix = first.helix_id != second.helix_id
            else:
                directed_slots = None
                interhelix = False
            matching = records.get(directed_slots, ())
            matched_records.update(matching)
            key = frozenset((first.key, second.key))
            if key not in edges:
                edges[key] = {
                    "first": first.key,
                    "second": second.key,
                    "interhelix": interhelix,
                    "forced": bool(matching),
                }
            else:
                edges[key]["forced"] |= bool(matching)
                edges[key]["interhelix"] |= interhelix
    return list(edges.values()), nodes, matched_records


def _position_lookup(design):
    positions = {}
    for nucleotide in _geometry_for_design(design):
        if nucleotide.get("is_modification"):
            continue
        raw = nucleotide.get("backbone_position")
        if raw is None or len(raw) != 3:
            continue
        pos = tuple(float(value) for value in raw)
        if not all(math.isfinite(value) for value in pos):
            continue
        key = (
            nucleotide.get("helix_id"),
            nucleotide.get("bp_index"),
            nucleotide.get("direction"),
        )
        copy = int(nucleotide.get("copy_k", 0))
        positions[(*key, copy)] = pos
        if copy == 0:
            positions[key] = pos
    return positions


def _endpoint(key, nodes, labels):
    step = nodes[key]
    if step.is_extra_base:
        return {"kind": "junction_insert", "index": step.eb_k}
    if step.is_extension:
        anchor = step.ext_anchor_key
        return {
            "kind": "extension",
            "index": step.ext_k,
            "end": step.ext_end,
            "anchor_helix_label": labels.get(anchor[0]),
            "anchor_bp": anchor[1],
        }
    return {
        "kind": "nucleotide",
        "helix_label": labels.get(step.helix_id),
        "bp": step.bp,
        "direction": step.direction,
        "copy_index": key[3] if len(key) == 4 else 0,
    }


def _edge_description(edge, nodes, labels):
    return {
        "from": _endpoint(edge["first"], nodes, labels),
        "to": _endpoint(edge["second"], nodes, labels),
        "interhelix": edge["interhelix"],
        "forced_ligation": edge["forced"],
    }


def review_design_bonds(design, *, include_geometry: bool = True) -> dict:
    """Produce bounded, JSON-serializable evidence without modifying *design*.

    Both whole-backbone and interhelix subsets independently trigger review at
    strictly >20%. An interhelix edge joins distinct helix objects, including
    native overhang roots and continuous split-helix boundaries. Circular closure
    is counted only when present in the realized path; pending connection records
    cannot establish closure. Topology integrity and process replay remain
    independent requirements; this numerical review does not replace them.
    """
    edges, nodes, matched_records = _realized_edges(design)
    total = len(edges)
    interhelix = sum(edge["interhelix"] for edge in edges)
    forced = sum(edge["forced"] for edge in edges)
    forced_interhelix = sum(edge["forced"] and edge["interhelix"] for edge in edges)
    reasons = []
    if _exceeds_threshold(forced, total):
        reasons.append("FORCED_BACKBONE_FRACTION_GT_20_PERCENT")
    if _exceeds_threshold(forced_interhelix, interhelix):
        reasons.append("FORCED_JUNCTION_FRACTION_GT_20_PERCENT")

    geometry = {
        "requested": include_geometry,
        "complete": False,
        "status": "not_checked",
        "threshold_nm": FULL_BACKBONE_ENVELOPE_NM,
        "long_all": 0,
        "long_interhelix": 0,
        "fraction_all": 0.0,
        "fraction_interhelix": 0.0,
        "measured_bonds": 0,
        "missing_bonds": 0,
        "worst_edges": [],
        "missing_edge_examples": [],
    }
    if include_geometry:
        labels = {
            helix.id: helix.label if helix.label is not None else index
            for index, helix in enumerate(design.helices)
        }
        try:
            positions = _position_lookup(design)
        except Exception as exc:
            # A geometry failure is review evidence, never a clean bill of health.
            positions = {}
            geometry["error_type"] = type(exc).__name__
        measured = []
        for edge in edges:
            first, second = positions.get(edge["first"]), positions.get(edge["second"])
            if first is None or second is None:
                geometry["missing_bonds"] += 1
                if len(geometry["missing_edge_examples"]) < _MAX_EXAMPLES:
                    geometry["missing_edge_examples"].append(_edge_description(edge, nodes, labels))
                continue
            distance = math.dist(first, second)
            geometry["measured_bonds"] += 1
            if distance > FULL_BACKBONE_ENVELOPE_NM:
                geometry["long_all"] += 1
                geometry["long_interhelix"] += int(edge["interhelix"])
            measured.append((distance, edge))
        measured.sort(key=lambda item: -item[0])
        geometry["worst_edges"] = [
            {**_edge_description(edge, nodes, labels), "distance_nm": distance}
            for distance, edge in measured[:_MAX_EXAMPLES]
        ]
        geometry["fraction_all"] = _ratio(geometry["long_all"], total)
        geometry["fraction_interhelix"] = _ratio(geometry["long_interhelix"], interhelix)
        geometry["complete"] = geometry["missing_bonds"] == 0 and "error_type" not in geometry
        geometry["status"] = "complete" if geometry["complete"] else "incomplete"
        if _exceeds_threshold(geometry["long_all"], total):
            reasons.append("LONG_BACKBONE_FRACTION_GT_20_PERCENT")
        if _exceeds_threshold(geometry["long_interhelix"], interhelix):
            reasons.append("LONG_JUNCTION_FRACTION_GT_20_PERCENT")
        if not geometry["complete"]:
            reasons.append("BOND_GEOMETRY_INCOMPLETE")

    return {
        "schema_version": 1,
        "review_required": bool(reasons),
        "reason_codes": reasons,
        "threshold_fraction": 0.2,
        "counts": {
            "backbone_bonds": total,
            "interhelix_bonds": interhelix,
            "matched_forced_bonds": forced,
            "matched_forced_interhelix_bonds": forced_interhelix,
            "unmatched_forced_records": len(design.forced_ligations) - len(matched_records),
            "matched_forced_records": len(matched_records),
            "nucleotides": len(nodes),
        },
        "ratios": {
            "forced_all": _ratio(forced, total),
            "forced_interhelix": _ratio(forced_interhelix, interhelix),
        },
        "geometry": geometry,
    }
