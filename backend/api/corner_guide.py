"""Read-only adaptation of current native axes to Corner's cylinder guide."""

from dataclasses import asdict

import numpy as np

from backend.core.corner_plan import AxisPath, plan_corner_guide
from backend.core.corner_routing import occupied_duplex_spans
from backend.core.deformation import (
    _initial_cross_section_frame,
    deformed_nucleotide_arrays,
    deformed_helix_axes,
    effective_helix_for_geometry,
)
from backend.core.geometry import nucleotide_positions_arrays


def _material_frame(design, helix, station):
    # Sample a nominal station even when the source has a deletion there. Both
    # arrays use the same canonical phase, so their triads recover only the
    # transported frame, including every owning cluster's actual rigid pose.
    plain = helix.model_copy(update={'loop_skips': []})
    raw = nucleotide_positions_arrays(effective_helix_for_geometry(plain, design))
    current = deformed_nucleotide_arrays(plain, design)
    index = 2 * (station - helix.bp_start)
    def triad(sites):
        x, z = sites['radial_hats'][index], sites['axis_tangents'][index]
        return np.column_stack((x, np.cross(z, x), z))
    transform = triad(current) @ triad(raw).T
    right = transform @ _initial_cross_section_frame(raw['axis_tangents'][index])[0]
    tangent = current['axis_tangents'][index]
    # XZ's grid row convention is left-handed relative to its extrusion axis.
    # Corner rotation needs a right-handed material frame for every plane.
    return tangent, right, np.cross(tangent, right)


def bundle_axis_paths(design, cluster_id, position_bp, *, all_members=False):
    clusters = [c for c in design.cluster_transforms if c.id == cluster_id]
    if len(clusters) != 1:
        raise ValueError("Select an existing cluster for Corner.")
    cluster = clusters[0]
    if cluster.domain_ids or cluster.base_ids:
        raise ValueError("Corner needs a cross-section of whole helices.")
    identities = set(cluster.helix_ids)
    helices = [h for h in design.helices if h.id in identities]
    if not helices or len(helices) != len(identities):
        raise ValueError("The selected cluster has no complete helix selection.")
    if any(h.native_residues for h in helices):
        raise ValueError("Corner requires duplex axes, not an imported non-helical path.")
    # A previous corner retains the raw construction axis on both wedges, but
    # only one wedge contains material at a later station. Scope by authored
    # domains, never by those extrapolated raw axes, so repeated corners act on
    # the cross-section that actually crosses the requested plane.
    spans = occupied_duplex_spans(design.strands)
    helices = [h for h in helices if h.id in spans
               and (all_members or spans[h.id][0] < position_bp <= spans[h.id][1])]
    if not helices:
        raise ValueError("The corner plane does not cross occupied duplex material.")
    axes = {a['helix_id']: a for a in deformed_helix_axes(design)}
    paths = []
    for helix in helices:
        axis = axes.get(helix.id)
        if axis is None:
            raise ValueError("A selected helix has no current axis geometry.")
        samples = axis['samples']
        if len(samples) > 2:
            stations = list(range(helix.bp_start, helix.bp_start + helix.length_bp, 7))
            final = helix.bp_start + helix.length_bp - 1
            if stations[-1] != final:
                stations.append(final)
        else:
            # Straight native axes describe the full duplex extent. Curved
            # sampled axes stop at the final nucleotide station instead.
            curved = any(not op.affected_helix_ids or helix.id in op.affected_helix_ids
                         for op in design.deformations)
            stations = [helix.bp_start, helix.bp_start + helix.length_bp - int(curved)]
        path = AxisPath(helix.id, tuple(stations), tuple(map(tuple, samples)))
        paths.append(path.clipped(*spans[helix.id]))
    if not all(h.bp_start <= position_bp < h.bp_start + h.length_bp for h in helices):
        raise ValueError("Plane position must lie within the selected bundle axes.")
    frame = _material_frame(design, helices[0], position_bp)
    return paths, frame


def corner_guide(design, cluster_id, parameters):
    paths, (tangent, right, up) = bundle_axis_paths(design, cluster_id, parameters.position_bp)
    guide = plan_corner_guide(paths, parameters, axis_dir=tangent, frame_right=right, frame_up=up)
    return asdict(guide)
