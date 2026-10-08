"""Read-only lattice addresses and placement for the native Extrude slice.

The records use the same candidate source resolution as frame extrusion. Tablet
pan/zoom never enters this transform: local lattice nm map into the serialized
scene's nm coordinates before the viewer's normalization and manipulation.
"""
import numpy as np

from backend.core.deformation import _apply_cluster_transforms_to_point
from backend.core.legacy_plane_extrusion import legacy_plane_source
from backend.core.lattice_occupancy import occupied_lattice_cells


PLANE_AXES = {'XY': (0, 1, 2), 'XZ': (0, 2, 1), 'YZ': (1, 2, 0)}


def lattice_plane_context(design, plane, view_rotation=None):
    """Return a uniquely addressable default plane, or None when ambiguous."""
    # Geometry-only scene projections may not carry the editable document.
    # Missing source metadata must not be advertised as an empty lattice.
    if not hasattr(design, 'helices'):
        return None
    rotation = np.eye(3) if view_rotation is None else np.asarray(view_rotation)
    axes = PLANE_AXES[plane]
    origin = np.zeros(3)
    clusters = []
    if design.helices:
        if not design.lattice_frames:
            try:
                transverse, clusters = legacy_plane_source(design, plane)
            except ValueError:
                return None
            origin[list(axes[:2])] = transverse
        else:
            # Keep native plane selection identical to the browser plan. A plane
            # shared by independent frames needs a frame picker, not merged cells.
            matches = [f for f in design.lattice_frames if f.plane == plane]
            if len(matches) != 1 or any(not h.lattice_frame_id for h in design.helices):
                return None
            frame = matches[0]
            clusters = [c for c in design.cluster_transforms if c.id == frame.placement_cluster_id]
            if len(clusters) != 1 or clusters[0].domain_ids or clusters[0].parent_cluster_id:
                return None
    elif any(getattr(design, field, ()) for field in ('strands', 'overhangs', 'protein_assets',
            'protein_attachments', 'nanoparticles', 'extensions', 'crossovers', 'forced_ligations')):
        return None

    def point(value):
        return rotation @ np.asarray(_apply_cluster_transforms_to_point(value.tolist(), clusters))

    placed_origin = point(origin)
    basis = [point(origin + np.eye(3)[axis]) - placed_origin for axis in axes]
    cells = sorted(occupied_lattice_cells(design, plane,
        frame_id=frame.id if design.helices and design.lattice_frames else None))
    return {'plane': plane, 'origin': placed_origin, 'basis': basis, 'cells': cells}


def lattice_context_records(design, view_rotation=None):
    """Optional NADOCVR v16 placement L and occupancy G records."""
    records = []
    for plane in PLANE_AXES:
        # Occupancy remains known even when several frames make the placement
        # ambiguous. Keep it separate from L's unique placement contract.
        if hasattr(design, 'helices'):
            occupied = sorted(occupied_lattice_cells(design, plane))
            cells = ' '.join(f'{row} {col}' for row, col in occupied)
            records.append(f'G {plane} {len(occupied)}' + (' '+cells if cells else ''))
        context = lattice_plane_context(design, plane, view_rotation)
        if context is None:
            continue
        vectors = [context['origin'], *context['basis']]
        values = ' '.join(f'{float(v):.9g}' for vector in vectors for v in vector)
        cells = ' '.join(f'{row} {col}' for row, col in context['cells'])
        records.append(f'L {plane} {values} {len(context["cells"])}' + (' '+cells if cells else ''))
    return records
