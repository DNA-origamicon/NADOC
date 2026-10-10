"""Bounded native Sweep transport; canonical geometry stays in core.sweep."""
import math
from backend.core.vr_extrude_draft import validate_painted_footprint


def validate_sweep_draft(raw):
    footprint = validate_painted_footprint(raw.get('painted_footprint'))
    points = raw.get('points_nm')
    if (raw.get('target_kind') != 'none'
            or 'freeform_placement' in raw or raw.get('source_helix_id') is not None
            or raw.get('extrude_from') not in {'XY', 'XZ', 'YZ'}
            or raw.get('strand_filter') not in {'both', 'scaffold', 'staples'}
            or not isinstance(raw.get('ligate_adjacent'), bool)
            or any(abs(v) > 10000 for cell in footprint['cells'] for v in cell)
            or not isinstance(points, list) or len(points) > 256
            or any(not isinstance(p, list) or len(p) != 3 or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 10000 for v in p)
                for p in points)):
        raise ValueError('invalid sweep configuration')
    orientations = raw.get('orientations_deg')
    if orientations is not None and (not isinstance(orientations, list) or len(orientations) != len(points)
            or any(a is not None and (not isinstance(a, list) or len(a) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 360 for v in a)) for a in orientations)):
        raise ValueError('invalid sweep orientations')
    return {**({'orientations_deg': [None if a is None else list(a) for a in orientations]} if orientations is not None else {}), 'painted_footprint': footprint, 'points_nm': [list(p) for p in points],
            'extrude_from': raw['extrude_from'], 'strand_filter': raw['strand_filter'],
            'ligate_adjacent': raw['ligate_adjacent']}
