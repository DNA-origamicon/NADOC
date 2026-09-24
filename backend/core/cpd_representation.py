"""Project the current CPD conformation onto the shared Full-view landmarks."""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.cpd_product import _proper_kabsch
from backend.core.nucleotide_landmarks import FULL_REP_BACKBONE_ATOM, PYRIMIDINE_RING


def project_cpd_residue(atoms):
    """Resolve O5′ and the base-ring centroid before the saved unit transform.

    The coordinate origin carries placement, not a chemical landmark. Only the
    slab orientation needs a rigid fit; positions come from the actual local
    conformation, including independent sugar/phosphate torsions.
    """
    from backend.core.atomistic import _DT_BASE

    if not all(name in atoms for name in (FULL_REP_BACKBONE_ATOM, *PYRIMIDINE_RING)):
        return None
    template = {name: xyz for name, _, *xyz in _DT_BASE}
    ring = np.array([atoms[name] for name in PYRIMIDINE_RING])
    rotation, _, _ = _proper_kabsch(
        np.array([template[name] for name in PYRIMIDINE_RING]), ring
    )
    return {
        "backbone_position": list(atoms[FULL_REP_BACKBONE_ATOM]),
        "base_position": ring.mean(axis=0).tolist(),
        "frame_rotation": Rotation.from_matrix(rotation).as_quat().tolist(),
    }


def inject_cpd_representation(design_dict):
    """Derived display payload, regenerated for old saves and every geometry edit."""
    for lesion in design_dict.get("photoproduct_junctions", []):
        lesion["representation_geometry"] = {
            key: geometry
            for key, atoms in lesion.get("design_coordinates", {}).items()
            if (geometry := project_cpd_residue(atoms)) is not None
        }
