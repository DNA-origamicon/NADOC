"""Full-view CPD bars from the same slab-local sites used by the desktop."""
import numpy as np
from dataclasses import replace
from scipy.spatial.transform import Rotation

from backend.core.cpd_representation import inject_cpd_representation, project_cpd_residue


def cpd_extra_projections(design, connection_id, projections):
    """Transport the desktop's saved product landmarks into crossover Full."""
    if not getattr(design, "photoproduct_junctions", ()):
        return projections
    from backend.core.base_keys import parse_base_key
    from backend.core.cpd_conversion import endpoint_transform

    products = {key: (lesion, atoms) for lesion in design.photoproduct_junctions
                for key, atoms in lesion.design_coordinates.items()}
    result = []
    for projection in projections:
        key = f"__xb__:{connection_id}:{projection.sim_k}"
        if key not in products:
            result.append(projection)
            continue
        lesion, atoms = products[key]
        geometry = project_cpd_residue(
            atoms, backbone_fixed=lesion.orientation_method == "manual-base-only-mvp-v1")
        if geometry is None:
            raise ValueError(f"CPD Full landmarks are incomplete: {key}")
        bead = np.asarray(geometry.get("backbone_position", projection.bead_center))
        center = np.asarray(geometry["base_position"])
        frame = Rotation.from_quat(geometry["frame_rotation"]).as_matrix()
        pose = endpoint_transform(design, parse_base_key(key))
        if pose:
            r = Rotation.from_quat(pose.rotation).as_matrix()
            pivot = np.asarray(pose.pivot)
            bead = pivot + r @ (bead - pivot) + pose.translation
            center = pivot + r @ (center - pivot) + pose.translation
            frame = r @ frame
        x, y, z = frame[:, 1]*.30, frame[:, 2]*.06, frame[:, 0]*.70
        sign = -1 if np.dot(bead-center, z) < 0 else 1
        result.append(replace(projection, bead_center=bead, slab_center=center,
                              slab_axis_x=x, slab_axis_y=y, slab_axis_z=z,
                              slab_corner=center+x*.5+z*(sign*.5)))
    return result


def append_cpd_bars(design, slabs, emit, owner_tokens, solid_palette):
    payload = {"photoproduct_junctions": [
        lesion.model_dump(mode="json") for lesion in getattr(design, "photoproduct_junctions", ())
    ]}
    inject_cpd_representation(payload)
    for lesion in payload["photoproduct_junctions"]:
        keys = (lesion["base_key_1"], lesion["base_key_2"])
        geometry = lesion["representation_geometry"]
        if not all(key in slabs and key in geometry for key in keys):
            continue
        endpoints = [owner_tokens(("base", key)) for key in keys]
        scopes = tuple(slabs[key][2] for key in keys)
        weights = [{token: start for token, start, _ in slabs[key][3]} for key in keys]
        transform_owners = tuple((token, weights[0].get(token, 0.), weights[1].get(token, 0.))
                                 for token in dict.fromkeys((*weights[0], *weights[1])))
        for i, names in enumerate(lesion["display_crosslinks"]):
            points = []
            for key, name in zip(keys, names):
                center, axes = slabs[key][:2]
                points.append(center + axes @ np.asarray(geometry[key]["bond_sites"][name]))
            emit("C", f"cpd:{lesion['id']}:{i}", *points[0], *points[1], .025,
                 *solid_palette((230 / 255, 162 / 255, 60 / 255)),
                 aliases=tuple(dict.fromkeys((*endpoints[0], *endpoints[1]))),
                 endpoint_aliases=tuple(endpoints), tool_endpoint_tokens=scopes,
                 transform_owners=transform_owners)
