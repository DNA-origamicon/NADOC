"""Read-only sampled material frames for interactive planar truncation."""
import numpy as np

from backend.core.corner_routing import occupied_duplex_spans
from backend.core.deformation import deformed_nucleotide_arrays, effective_helix_for_geometry, _initial_cross_section_frame
from backend.core.geometry import nucleotide_positions_arrays


def cached_display(design):
    """Read-only Full preview; embedded native records carry every seam insert."""
    from backend.core.bevel_geometry_cache import compact
    from backend.core.deformation import deformed_helix_axes
    from backend.api.corner_preview_projection import display_topology
    records = compact(design)
    if records is None:
        return None
    return dict(component_kind='corner-preview-dna', component_version=1,
        representation='native-full-v1', units='nm', nucleotides_compact=records,
        helix_axes=deformed_helix_axes(design), display_topology=display_topology(design))


def source_axes(design, cluster_id):
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None or cluster.domain_ids or cluster.base_ids:
        raise ValueError('Bevel needs a cluster of whole helices.')
    from backend.api.corner_build import _admit_references
    selected = set(cluster.helix_ids)
    if not selected or not selected.issubset({h.id for h in design.helices}):
        raise ValueError('Select a cluster containing complete helices.')
    try:
        _admit_references(design, selected, cluster_id)
    except ValueError as error:
        raise ValueError(str(error).replace('Corner', 'Bevel')) from error
    from backend.core import bevel_geometry_cache
    identity = bevel_geometry_cache.axes_key(design)
    cache_key = ('bevel-axes', cluster_id, identity) if identity is not None else None
    if cache_key is not None:
        cached = bevel_geometry_cache.get(cache_key)
        if cached is not None:
            return cached
    material = bevel_geometry_cache.material_key(design)
    spans = occupied_duplex_spans(design.strands)
    paths = []
    for helix in design.helices:
        if helix.id not in selected or helix.id not in spans:
            continue
        if helix.native_residues:
            raise ValueError('Bevel requires native duplex axes.')
        frame_key = ('bevel-material', material, helix.id) if material is not None else None
        frame = bevel_geometry_cache.get(frame_key) if frame_key is not None else None
        if frame is None:
            frame = _material_frame(helix, design)
            if frame_key is not None:
                bevel_geometry_cache.put(frame_key, frame)
        bps, points, z, right = frame
        lo, hi = spans[helix.id]
        mask = (bps >= lo) & (bps <= hi)
        paths.append(dict(helix_id=helix.id, bps=bps[mask].tolist(),
            points=points[mask].tolist(),
            tangents=z[mask].tolist(), rights=right[mask].tolist()))
    if not paths:
        raise ValueError('Select a bundle containing duplex material.')
    if cache_key is not None:
        bevel_geometry_cache.put(cache_key, paths)
    return paths


def _material_frame(helix, design):
    plain = helix.model_copy(update={'loop_skips': []})
    current = deformed_nucleotide_arrays(plain, design)
    raw = nucleotide_positions_arrays(effective_helix_for_geometry(plain, design))
    bps, indices = np.unique(current['bp_indices'], return_index=True)
    x, z = current['radial_hats'][indices], current['axis_tangents'][indices]
    rx, rz = raw['radial_hats'][indices], raw['axis_tangents'][indices]
    # Straight runs repeat the exact tangent at every station. Reuse its
    # frame within this calculation (bitwise keys preserve signed zeros).
    rights = {}
    def initial_right(tangent):
        key = tangent.tobytes()
        if key not in rights:
            rights[key] = _initial_cross_section_frame(tangent)[0]
        return rights[key]
    source_right = np.array([initial_right(t) for t in rz])
    ry = np.cross(rz, rx)
    right = (x * np.sum(rx * source_right, axis=1)[:, None]
             + np.cross(z, x) * np.sum(ry * source_right, axis=1)[:, None]
             + z * np.sum(rz * source_right, axis=1)[:, None])
    return bps, current['axis_points'][indices], z, right


def plane(paths, request):
    rows = [(p, p['bps'].index(request.position_bp)) for p in paths if request.position_bp in p['bps']]
    if not rows:
        raise ValueError('Plane position must cross occupied bundle material.')
    center = np.mean([p['points'][i] for p, i in rows], axis=0)
    p, i = rows[0]
    tangent, right = np.array(p['tangents'][i]), np.array(p['rights'][i])
    angle, direction = np.radians([request.angle_deg, request.direction_deg])
    normal = np.cos(angle) * tangent + np.sin(angle) * (np.cos(direction) * right + np.sin(direction) * np.cross(tangent, right))
    return center, normal


def retained_sites(paths, request):
    center, normal = plane(paths, request)
    sign = 1 if request.trim_end == 'end' else -1
    kept = {p['helix_id']: {bp for bp, distance in zip(p['bps'], (np.array(p['points']) - center) @ normal)
                           if sign * distance <= 1e-9} for p in paths}
    count = sum(map(len, kept.values()))
    if count == 0 or count == sum(len(p['bps']) for p in paths):
        raise ValueError('Bevel needs material on both sides of the cutting plane.')
    return kept
