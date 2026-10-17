"""Snapshot copies placed by a rigid VR hand pose using existing copy engines."""
import numpy as np
from backend.core.pattern_copy import copy_pattern_instances
from backend.core.element_copy import paste_elements

PATTERN_FIELDS = ('helices', 'strands', 'crossovers', 'forced_ligations',
                  'lattice_frames', 'cluster_transforms', 'deformations')


def rigid_matrix(values):
    matrix = np.asarray(values, dtype=float).reshape((4, 4), order='F')
    rotation = matrix[:3, :3]
    if (not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-5)
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4)
            or not np.isclose(np.linalg.det(rotation), 1, atol=1e-4)):
        raise ValueError('Paste requires a finite rigid placement')
    return matrix


def paste_snapshot(design, source, refs, matrix):
    """Copy a domain-union snapshot; small picks promote to their owning domains."""
    from backend.core.clipboard_scope import domain_scope, scoped_source
    selected, proteins, particles = domain_scope(source, refs)
    # Retain the established lattice/frame copy for whole-cluster-only requests.
    if refs and all(r.get('kind') == 'cluster' for r in refs):
        try:
            copied, new_helices, _ = copy_pattern_instances(source, list(dict.fromkeys(r['id'] for r in refs)), [('clipboard', matrix)])
        except ValueError:
            pass  # Domain clusters and attached DNA use the exact domain-union copier.
        else:
            result = design.model_copy(deep=True)
            for field in PATTERN_FIELDS:
                old = {obj.id for obj in getattr(source, field)}
                getattr(result, field).extend(obj for obj in getattr(copied, field) if obj.id not in old)
            return result, new_helices
    scoped, geometry = scoped_source(source, selected)
    result, _ = paste_elements(design, scoped, proteins, particles, placement=matrix,
        strand_ids=[s.id for s in scoped.strands], source_geometry=geometry, pose_source=source)
    old = {h.id for h in design.helices}
    return result, [h.id for h in result.helices if h.id not in old]


def preview_snapshot(source, refs):
    """Bounded source-space strokes for the exact resolved snapshot, at every LOD."""
    from backend.core.clipboard_scope import domain_scope, scoped_source
    from backend.core.protein import compose_protein_world_transform, resolve_overhang_anchor
    selected, proteins, particles = domain_scope(source, refs)
    _, geometry = scoped_source(source, selected)
    lines = []
    previous = {}
    for n in geometry:
        point = np.asarray(n['backbone_position'])
        key = (n.get('strand_id'), n.get('domain_index'))
        if key in previous:
            lines.append({'a': previous[key].tolist(), 'b': point.tolist()})
        else:
            normal = np.asarray(n['base_normal']) * .15
            lines.append({'a': (point-normal).tolist(), 'b': (point+normal).tolist()})
        previous[key] = point

    def box(lo, hi, matrix):
        corners = [np.array([*(hi[j] if i & (1 << j) else lo[j] for j in range(3)), 1]) for i in range(8)]
        for i in range(8):
            for j in range(3):
                k = i ^ (1 << j)
                if i < k:
                    lines.append({'a': (matrix @ corners[i])[:3].tolist(), 'b': (matrix @ corners[k])[:3].tolist()})

    for p in source.nanoparticles:
        if p.id in particles:
            radius = p.diameter_nm/2
            box([-radius]*3, [radius]*3, p.pose.to_array())
    from backend.core.design_geometry import fitting_geometry
    anchor_geometry = fitting_geometry(source) if any(p.id in proteins and p.target.kind == "overhang" for p in source.protein_attachments) else geometry
    assets = {a.id: a for a in source.protein_assets}
    for p in source.protein_attachments:
        if p.id not in proteins:
            continue
        asset = assets[p.asset_id]
        tip, outward = resolve_overhang_anchor(anchor_geometry, p.target.overhang_id, p.target.attach_end) if p.target.kind == 'overhang' else (None, None)
        world = compose_protein_world_transform(asset, p, tip, outward)
        positions = np.array([[a.x, a.y, a.z] for a in asset.atoms])
        if len(positions):
            box(positions.min(axis=0), positions.max(axis=0), world)
    if not lines:
        raise ValueError('Selection has no preview geometry')
    # Evenly sample the entire scope instead of truncating later selected objects.
    if len(lines) > 8192:
        lines = [lines[i] for i in np.linspace(0, len(lines)-1, 8192, dtype=int)]
    return lines
