"""Display-only extension slabs measured from the existing atomistic model.

The extension arc remains the coarse/physical backbone authority. Slabs describe
the actual atomic rings, just as in measured MD display; they do not move atoms
or replace the extension's particle frame.
"""
import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.md_base_frames import measured_base_frames, ordered_ring_indices
from backend.core.native_full_placement import NativePlacementError
from backend.core.native_slab_placement import _frame


def project_extension_slabs(records, model):
    targets = [r for r in records if r.get("extension_id") and not r.get("is_modification")]
    if not targets:
        return
    residues = {}
    for atom in model.atoms:
        if atom.extension_id is not None:
            residues.setdefault((atom.extension_id, atom.ext_k), {})[atom.name] = (atom.x, atom.y, atom.z)
    for record in targets:
        identity = (record["extension_id"], record["bp_index"])
        atoms = residues.get(identity, {})
        names = list(atoms)
        indices = {name: i for i, name in enumerate(names)}
        ring = ordered_ring_indices(indices)
        expected_size = 9 if any(name in atoms for name in ("N9", "C8", "N7")) else 6
        if "O5'" not in indices or len(ring) != expected_size:
            raise NativePlacementError("Incomplete atomistic extension ring for Full slab.", details={"identity": identity})
        xyz = np.asarray([atoms[name] for name in names])
        anchors = np.array([indices["O5'"]])
        inward = np.full((1, 3), np.nan)
        centers, normals = measured_base_frames(xyz, anchors, [(np.array([0]), ring[None])],
                                                xyz[anchors], None, None, inward_out=inward)
        frame = _frame(inward[0], normals[0])
        record["slab_position"] = centers[0].tolist()
        record["slab_quaternion"] = Rotation.from_matrix(frame).as_quat().tolist()


def attach_extension_slabs(records, design):
    if not any(r.get("extension_id") and not r.get("is_modification") for r in records):
        return
    from backend.core.atomistic_cache import build_atomistic_model_cached
    project_extension_slabs(records, build_atomistic_model_cached(design, fast_bridges=True))
