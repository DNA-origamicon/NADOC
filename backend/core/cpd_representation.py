"""Project the current CPD conformation onto the shared Full-view landmarks."""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.cpd_product import _proper_kabsch
from backend.core.nucleotide_landmarks import FULL_REP_BACKBONE_ATOM, PYRIMIDINE_RING


def project_cpd_residue(atoms, *, backbone_fixed=False):
    """Resolve O5′ and the base-ring centroid before the saved unit transform.

    The coordinate origin carries placement, not a chemical landmark. Only the
    slab orientation needs a rigid fit; positions come from the actual local
    conformation, including independent sugar/phosphate torsions.
    """
    from backend.core.atomistic import _DT_BASE

    required = PYRIMIDINE_RING if backbone_fixed else (FULL_REP_BACKBONE_ATOM, *PYRIMIDINE_RING)
    if not all(name in atoms for name in required):
        return None
    template = {name: xyz for name, _, *xyz in _DT_BASE}
    ring = np.array([atoms[name] for name in PYRIMIDINE_RING])
    rotation, _, _ = _proper_kabsch(
        np.array([template[name] for name in PYRIMIDINE_RING]), ring
    )
    return {
        **({"backbone_fixed": True} if backbone_fixed else {"backbone_position": list(atoms[FULL_REP_BACKBONE_ATOM])}),
        "base_position": ring.mean(axis=0).tolist(),
        "frame_rotation": Rotation.from_matrix(rotation).as_quat().tolist(),
        "bond_sites": {name: (((np.array(atoms[name]) - ring.mean(axis=0)) @ rotation)[[1, 2, 0]]
                              / np.array([.30, .06, .70])).tolist() for name in ("C5", "C6")},
    }


def inject_cpd_representation(design_dict):
    """Derived display payload, regenerated for old saves and every geometry edit."""
    for lesion in design_dict.get("photoproduct_junctions", []):
        from backend.core.photoproduct_chemistry import load_chemical_definition
        definition = load_chemical_definition(lesion["product"], lesion["stereochemistry"])
        lesion["display_crosslinks"] = [[b["atom_1"].split(":")[1], b["atom_2"].split(":")[1]]
                                       for b in definition["graph_delta"]["bonds_added"]]
        lesion["representation_geometry"] = {
            key: geometry
            for key, atoms in lesion.get("design_coordinates", {}).items()
            if (geometry := project_cpd_residue(atoms, backbone_fixed=lesion.get("orientation_method") == "manual-base-only-mvp-v1")) is not None
        }


def apply_base_only_cpd_geometry(records, design):
    """Transport base landmarks only; the existing backbone record is untouched."""
    from backend.core.base_keys import parse_base_key
    from backend.core.cpd_conversion import METHOD, endpoint_transform
    geometries = {}
    for lesion in design.photoproduct_junctions:
        if lesion.orientation_method != METHOD:
            continue
        for key, atoms in lesion.design_coordinates.items():
            geometry = project_cpd_residue(atoms, backbone_fixed=True)
            pose = endpoint_transform(design, parse_base_key(key))
            center = np.array(geometry["base_position"])
            frame = Rotation.from_quat(geometry["frame_rotation"]).as_matrix()
            if pose:
                r = Rotation.from_quat(pose.rotation).as_matrix()
                pivot = np.array(pose.pivot)
                center = pivot + r @ (center - pivot) + pose.translation
                frame = r @ frame
            geometries[key] = center, frame
    for record in records:
        key = f"{record['helix_id']}:{record['bp_index']}:{record['direction']}"
        copy = record.get("copy_k", record.get("copy", 0)) or 0
        if copy:
            key += f":{copy}"
        if key in geometries:
            center, frame = geometries[key]
            record.update(base_position=center.tolist(), base_normal=frame[:, 0].tolist(),
                          axis_tangent=frame[:, 2].tolist(), placement_source="manual-cpd-base-only-v1")


def apply_cpd_context_geometry(records, design):
    """Move flanking backbone beads while retaining their exact native slab poses."""
    from backend.core.base_keys import parse_base_key
    from backend.core.cpd_conversion import endpoint_transform
    from backend.core.native_slab_placement import _expected_slab_pose
    by_key = {k: a for lesion in design.photoproduct_junctions for k,a in lesion.context_coordinates.items()}
    for record in records:
        key = f"{record['helix_id']}:{record['bp_index']}:{record['direction']}"
        copy = record.get('copy_k', record.get('copy', 0)) or 0
        if copy: key += f":{copy}"
        if key not in by_key: continue
        atoms = by_key[key]
        if FULL_REP_BACKBONE_ATOM not in atoms: continue
        center, _ = _expected_slab_pose(record)
        bead = np.array(atoms[FULL_REP_BACKBONE_ATOM])
        pose = endpoint_transform(design, parse_base_key(key))
        if pose:
            r = Rotation.from_quat(pose.rotation).as_matrix()
            pivot = np.array(pose.pivot)
            bead = pivot + r @ (bead-pivot) + pose.translation
        record.update(backbone_position=bead.tolist(), fixed_slab_position=center.tolist(),
                      placement_source='manual-cpd-context-v1')
