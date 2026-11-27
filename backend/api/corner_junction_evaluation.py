"""Read-only molecular seam evaluation against the exact current source.

Returns native insert candidates and actual work progress, not a ready-to-apply
Design. Selection of a route needs duplex-phase, steric and bond validation.
"""

from dataclasses import dataclass

import numpy as np

from backend.api.part_corner_commands import preflight
from backend.core.corner_junction_geometry import endpoint_from_full_sites, native_seam_candidate
from backend.core.design_geometry import native_full_arrays_for_helix, apply_nucleotide_transforms_to_geometry

DEFAULT_MAX_INSERT_BASES = 8

@dataclass(frozen=True)
class EvaluatedSeam:
    strand_id: str
    exit_domain: int
    three_prime: dict
    five_prime: dict
    candidates: tuple


def evaluate_corner_junctions(design, params, *, max_insert_bases=DEFAULT_MAX_INSERT_BASES,
                              on_progress=None, check_cancel=None, first_within_nm=None):
    if type(max_insert_bases) is not int or not 1 <= max_insert_bases <= 32:
        raise ValueError('Corner insert search must be bounded to 1–32 bases.')
    guide, routes = preflight(design, params, check_cancel=check_cancel)
    center = np.asarray(guide['center_nm'])
    rotation = np.asarray(guide['rotation'])
    strands = {s.strand_id: s for s in routes.strands}
    helices = {h.id: h for h in design.helices}
    arrays = {}
    total = len(routes.junctions) * max_insert_bases
    completed = 0
    if on_progress:
        on_progress(completed, total)

    def endpoint(row, bp):
        if row.helix_id not in arrays:
            arrays[row.helix_id] = native_full_arrays_for_helix(helices[row.helix_id], design)
        record = endpoint_from_full_sites(arrays[row.helix_id], bp, row.direction)
        record.update(helix_id=row.helix_id, bp_index=bp, copy_k=0)
        apply_nucleotide_transforms_to_geometry([record], design)
        if row.side == 'outgoing':
            record['backbone_position'] = (center + rotation @ (np.asarray(record['backbone_position']) - center)).tolist()
            record['axis_tangent'] = (rotation @ np.asarray(record['axis_tangent'])).tolist()
        return record

    seams = []
    for junction in routes.junctions:
        if check_cancel:
            check_cancel()
        rows = strands[junction.strand_id].domains
        a, b = rows[junction.exit_domain], rows[junction.entry_domain]
        if {a.side, b.side} != {'incoming', 'outgoing'}:
            raise ValueError('Corner needs a local lattice-routing solution for a changed within-wedge connection.')
        first, second = endpoint(a, a.end_bp), endpoint(b, b.start_bp)
        candidates = []
        for count in range(1, max_insert_bases + 1):
            if check_cancel:
                check_cancel()
            candidates.append(native_seam_candidate(first, second, 'N' * count))
            completed += 1
            if on_progress:
                on_progress(completed, total)
            # Construction chooses the shortest passing insert. Each length
            # has exactly one candidate, so longer candidates cannot win.
            # The inspection API still evaluates all lengths by default.
            if first_within_nm is not None and candidates[-1].max_backbone_length_nm <= first_within_nm:
                total -= max_insert_bases - count
                if on_progress:
                    on_progress(completed, total)
                break
        seams.append(EvaluatedSeam(junction.strand_id, junction.exit_domain, first, second, tuple(candidates)))
    return guide, routes, tuple(seams)
