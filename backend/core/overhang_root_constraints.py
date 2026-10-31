"""Covalent root constraints for automatic rigid overhang placement.

Manual Move/Rotate deliberately does not use these constraints. The native
atom builder owns the phosphodiester geometry; fitting reads its bond endpoints.
"""

from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class RootBond:
    fixed: np.ndarray
    moving: np.ndarray

    @property
    def length_nm(self):
        return float(np.linalg.norm(self.moving - self.fixed))


def overhang_root_bond(design, overhang_id, *, fast_bridges=True):
    """Read the actual bond crossing a terminal overhang's host boundary.

    A standalone strand has no covalent host root and returns None.
    """
    from backend.core.atomistic import build_atomistic_model

    found = [
        (s, i, d)
        for s in design.strands
        for i, d in enumerate(s.domains)
        if d.overhang_id == overhang_id
    ]
    if not found:
        raise ValueError("Overhang root could not be resolved.")
    if len(found) != 1:
        raise ValueError("Automatic fitting requires an unambiguous overhang domain.")
    strand, index, domain = found[0]
    if len(strand.domains) == 1:
        return None
    if index not in (0, len(strand.domains) - 1):
        raise ValueError("Automatic fitting requires a terminal overhang root.")
    parent = strand.domains[1 if index == 0 else index - 1]
    moving_bp = domain.end_bp if index == 0 else domain.start_bp
    fixed_bp = parent.start_bp if index == 0 else parent.end_bp
    moving_name, fixed_name = ("O3'", "P") if index == 0 else ("P", "O3'")
    helices = {domain.helix_id, parent.helix_id}
    model = build_atomistic_model(
        design,
        fast_bridges=fast_bridges,
        exclude_helix_ids={h.id for h in design.helices} - helices,
    )

    def atom(helix, bp, direction, name):
        hits = [
            a
            for a in model.atoms
            if a.strand_id == strand.id
            and a.helix_id == helix
            and a.bp_index == bp
            and a.direction == direction.value
            and a.name == name
        ]
        if len(hits) != 1:
            raise ValueError(
                "Automatic fitting requires an unambiguous covalent root bond."
            )
        a = hits[0]
        return a.serial, np.array([a.x, a.y, a.z])

    mi, moving = atom(domain.helix_id, moving_bp, domain.direction, moving_name)
    fi, fixed = atom(parent.helix_id, fixed_bp, parent.direction, fixed_name)
    if (mi, fi) not in model.bonds and (fi, mi) not in model.bonds:
        raise ValueError("Overhang root atoms are not covalently bonded.")
    return RootBond(fixed, moving)


def root_preserving_rolls(swing, axis, pivot, bond, preferred):
    """Solve the axial rolls preserving an additional native root bond exactly.

    Viewer and export linker builders have different endpoints. The primary
    root is the rotation pivot; this one scalar constraint also preserves the
    other builder's bond, without changing either builder's atom placements.
    """
    moving = swing @ (bond.moving - pivot)
    fixed = bond.fixed - pivot
    parallel = axis * np.dot(axis, moving)
    radial = moving - parallel
    a = 2 * np.dot(fixed, radial)
    b = 2 * np.dot(fixed, np.cross(axis, moving))
    c = (
        np.dot(moving, moving)
        + np.dot(fixed, fixed)
        - 2 * np.dot(fixed, parallel)
        - bond.length_nm**2
    )
    magnitude = np.hypot(a, b)
    if magnitude < 1e-12:
        return np.asarray(preferred) if abs(c) < 1e-10 else np.empty(0)
    if abs(c) > magnitude + 1e-10:
        return np.empty(0)
    offset = np.arctan2(b, a)
    angle = np.arccos(np.clip(c / magnitude, -1.0, 1.0))
    return np.unique(
        (np.array([offset - angle, offset + angle]) + np.pi) % (2 * np.pi) - np.pi
    )


def rotate_overhang_about(
    design, overhang_id, rotation, pivot, *, translation=None, materialize=True
):
    """Compose an incremental world rotation about an explicit fixed point.

    Rebase the stored overlay translation as well as its quaternion; its native
    rendering pivot is a backbone marker, not the covalent root atom.
    """
    from backend.core.design_geometry import fitting_geometry
    from backend.core.direct_relax import _overhang_root_pivot
    from backend.core.duplex_cluster import (
        dematerialize_duplex_cluster,
        duplex_cluster_for,
        materialize_duplex_cluster,
    )

    cluster = duplex_cluster_for(design, overhang_id)
    out = dematerialize_duplex_cluster(design, overhang_id)
    spec = next(o for o in out.overhangs if o.id == overhang_id)
    cleared = out.copy_with(
        overhangs=[
            o.model_copy(
                update={
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                    "translation": [0.0, 0.0, 0.0],
                }
            )
            if o.id == overhang_id
            else o
            for o in out.overhangs
        ]
    )
    base = _overhang_root_pivot(
        cleared, fitting_geometry(cleared, overhang_ids={overhang_id}), overhang_id
    )
    if base is None:
        raise ValueError("Overhang rotation pivot could not be resolved.")
    base, pivot = np.asarray(base), np.asarray(pivot)
    quaternion = (
        Rotation.from_matrix(rotation @ Rotation.from_quat(spec.rotation).as_matrix())
        .as_quat()
        .tolist()
    )
    translation = (
        rotation @ (base + np.asarray(spec.translation) - pivot) + pivot - base
        + (np.asarray(translation) if translation is not None else 0.0)
    )
    out = out.copy_with(
        overhangs=[
            o.model_copy(
                update={
                    "rotation": quaternion,
                    "translation": translation.tolist(),
                }
            )
            if o.id == overhang_id
            else o
            for o in out.overhangs
        ]
    )
    if not materialize:
        return out
    out, _ = materialize_duplex_cluster(
        out,
        overhang_id,
        cluster_id=cluster.id if cluster else None,
        name=cluster.name if cluster else None,
    )
    return out
