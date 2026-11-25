"""Corner endpoint transport and native insert candidates, isolated from display.

Use canonical helical sites and the existing Full/insert placement authority.
Cylinder intersections never stand in for backbone endpoints. Candidate distances
are screening evidence only; this module does not approve, publish or install a
molecular placement, and does not change any placement constants.
"""

from dataclasses import dataclass

import numpy as np

from backend.core.native_full_placement import place_native_full
from backend.core.vr_scene_projection import crossover_extra_base_full_projections


def transported_full_sites(sites, *, center_nm, rotation):
    """Project the outgoing wedge after a proper rigid transform of its sites."""
    center = np.asarray(center_nm, dtype=float)
    matrix = np.asarray(rotation, dtype=float)
    if (center.shape != (3,) or matrix.shape != (3, 3)
            or not np.isfinite(center).all() or not np.isfinite(matrix).all()
            or not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-8, rtol=0)
            or not np.isclose(np.linalg.det(matrix), 1, atol=1e-8, rtol=0)):
        raise ValueError('Corner endpoint transport requires a finite proper rigid rotation.')
    # Validate source authority too; a projected payload cannot be reinterpreted
    # as canonical sites. Copy arrays so cached source geometry remains untouched.
    place_native_full(sites)
    moved = {key: value.copy() if isinstance(value, np.ndarray) else value
             for key, value in sites.items()}
    for key in ('axis_points', 'positions', 'base_positions'):
        if key in moved:
            moved[key] = (moved[key] - center) @ matrix.T + center
    for key in ('radial_hats', 'axis_tangents', 'base_normals'):
        if key in moved:
            moved[key] = moved[key] @ matrix.T
    return place_native_full(moved)


def endpoint_from_full_sites(sites, bp_index, direction):
    """Return a native Full endpoint, rejecting missing or ambiguous addresses."""
    from backend.core.native_full_placement import SOURCE

    if sites.get('placement_source') != SOURCE:
        raise ValueError('Corner requires authoritative native Full endpoint positions.')
    value = getattr(direction, 'value', direction)
    if value not in ('FORWARD', 'REVERSE'):
        raise ValueError('Corner endpoint direction must be FORWARD or REVERSE.')
    rows = np.flatnonzero((sites['bp_indices'] == bp_index)
                         & (sites['directions'] == int(value == 'REVERSE')))
    if len(rows) != 1:
        raise ValueError('Corner endpoint is missing or has ambiguous loop-copy identity.')
    index = rows[0]
    return {'backbone_position': sites['positions'][index].tolist(),
            'axis_tangent': sites['axis_tangents'][index].tolist(),
            'direction': value}


@dataclass(frozen=True)
class SeamGeometryCandidate:
    sequence: str
    insert_backbone_positions: tuple[tuple[float, float, float], ...]
    backbone_lengths_nm: tuple[float, ...]

    @property
    def max_backbone_length_nm(self):
        return max(self.backbone_lengths_nm)


def native_seam_candidate(three_prime, five_prime, sequence):
    """Existing insert placement, in explicit 3′ exit → 5′ entry order.

    No acceptance predicate lives here. A short maximum bond does not establish
    absence of clashes, ring piercings, or sufficient mechanical constraints.
    """
    import re

    if not isinstance(sequence, str) or re.fullmatch('[ACGTN]*', sequence) is None:
        raise ValueError('Corner seam sequence must be explicit uppercase DNA.')
    for endpoint in (three_prime, five_prime):
        position = np.asarray(endpoint['backbone_position'], dtype=float)
        axis = np.asarray(endpoint['axis_tangent'], dtype=float)
        if (position.shape != (3,) or axis.shape != (3,)
                or not np.isfinite(position).all() or not np.isfinite(axis).all()
                or not np.isclose(np.linalg.norm(axis), 1, atol=1e-6, rtol=0)
                or endpoint['direction'] not in ('FORWARD', 'REVERSE')):
            raise ValueError('Corner seam endpoints need finite native positions and unit tangents.')
    projected = crossover_extra_base_full_projections(three_prime, five_prime, sequence,
        sim_reversed=False, local_frame_reversed=three_prime['direction'] == 'REVERSE')
    inserts = tuple(tuple(float(v) for v in row.bead_center)
                    for row in sorted(projected, key=lambda row: row.sim_k))
    points = np.asarray([three_prime['backbone_position'], *inserts, five_prime['backbone_position']])
    if not np.isfinite(points).all():
        raise ValueError('Native Corner insert placement returned nonfinite coordinates.')
    lengths = tuple(float(value) for value in np.linalg.norm(np.diff(points, axis=0), axis=1))
    return SeamGeometryCandidate(sequence, inserts, lengths)
