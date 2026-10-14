"""Compact display columns from the existing native array/slab authorities.

The bounded path avoids constructing transient nucleotide dictionaries for
ordinary occupied helical DNA. Chemical residues, extensions, bridges, and
per-nucleotide edits retain the complete record pipeline. This module changes
serialization work, never the definition of a native placement.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from backend.core.design_geometry import native_full_arrays_for_helix
from backend.core.models import Design, Direction
from backend.core.native_full_placement import SOURCE
from backend.core.native_slab_placement import native_slab_poses_for_arrays


def native_compact_geometry(design: Design) -> dict | None:
    """Return exact compact columns, or None when the general path is required.

    Array order is inherited from native_full_arrays_for_helix, including loop
    copies and skips. Domain assignment follows the existing last-domain-wins
    rule; unoccupied complementary slots are never emitted.
    """
    if (design.extensions or design.overhang_connections or design.overhangs
            or design.nucleotide_transforms or design.photoproduct_junctions
            or any(h.native_residues for h in design.helices)):
        return None
    helices = {h.id: h for h in design.helices}
    if len(helices) != len(design.helices):
        return None
    domains = defaultdict(list)
    for strand in design.strands:
        if not strand.domains:
            continue
        first, last = strand.domains[0], strand.domains[-1]
        five = (first.helix_id, first.start_bp, first.direction)
        three = (last.helix_id, last.end_bp, last.direction)
        for index, domain in enumerate(strand.domains):
            helix = helices.get(domain.helix_id)
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            if helix is None or lo < helix.bp_start or hi >= helix.bp_start + helix.length_bp:
                return None
            domains[helix.id].append((strand, index, domain, lo, hi, five, three))

    compact = {}
    for helix in design.helices:
        if helix.id.startswith("__lnk__"):
            continue
        arrays = native_full_arrays_for_helix(helix, design)
        if arrays.get("placement_source") != SOURCE:
            return None
        bps, directions = arrays["bp_indices"], arrays["directions"]
        count = len(bps)
        occupied = np.zeros(count, dtype=bool)
        sid, stype, ohid = (np.full(count, None, dtype=object) for _ in range(3))
        did = np.zeros(count, dtype=np.int32)
        is5, is3 = (np.zeros(count, dtype=bool) for _ in range(2))
        for strand, index, domain, lo, hi, five, three in domains[helix.id]:
            direction = int(domain.direction == Direction.REVERSE)
            mask = (directions == direction) & (bps >= lo) & (bps <= hi)
            occupied[mask] = True
            sid[mask], stype[mask], ohid[mask] = strand.id, strand.strand_type.value, domain.overhang_id
            did[mask] = index
            is5[mask] = ((bps[mask] == five[1]) if (helix.id, domain.direction) == (five[0], five[2]) else False)
            is3[mask] = ((bps[mask] == three[1]) if (helix.id, domain.direction) == (three[0], three[2]) else False)
        if not np.any(occupied):
            continue
        # Keep original interleaved row order when evaluating the shared slab
        # authority, exactly as the record pipeline does before compact packing.
        selected = {key: value[occupied] if isinstance(value, np.ndarray) and len(value) == count else value
                    for key, value in arrays.items()}
        centers, quaternions = native_slab_poses_for_arrays(selected)
        selected_directions = directions[occupied]
        _, first_indices = np.unique(selected_directions, return_index=True)
        buckets = {}
        for direction in selected_directions[np.sort(first_indices)]:
            mask = occupied & (directions == direction)
            slab_mask = selected_directions == direction
            buckets[("FORWARD", "REVERSE")[int(direction)]] = {
                "bp": bps[mask], "bb": arrays["positions"][mask],
                "bs": arrays["base_positions"][mask], "bn": arrays["base_normals"][mask],
                "at": arrays["axis_tangents"][mask], "sp": centers[slab_mask],
                "sq": quaternions[slab_mask], "pv": [SOURCE] * int(mask.sum()),
                "sid": sid[mask].tolist(), "stype": stype[mask].tolist(),
                "is5": is5[mask], "is3": is3[mask], "did": did[mask], "ohid": ohid[mask].tolist(),
            }
        compact[arrays["helix_id"]] = buckets
    return compact


def geometry_arrays_to_lists(value):
    """Keep the compatibility JSON response ordinary arrays at its boundary."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: geometry_arrays_to_lists(item) for key, item in value.items()}
    # Native columns are direct dictionary leaves. Existing JSON metadata,
    # axes, and Design lists need no traversal or duplicate allocations.
    return value
