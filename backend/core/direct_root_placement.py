"""Rigid duplex placement constrained by the actual covalent overhang roots.

Topology relocation is supplied by the existing binding/duplex operations.
This module only changes the duplex pose; parent bodies remain stationary.
Manual Move/Rotate does not call it. Collision clearance is advisory.
"""

from __future__ import annotations

import numpy as np
from fastapi import HTTPException
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from backend.core.overhang_root_constraints import overhang_root_bond, rotate_overhang_about

ROOT_TOLERANCE_NM = 1e-8
BUILDERS = (("viewer", True), ("export", False))


def rooted_binding_topology(source, topology):
    """Keep the pre-bind root lengths with the existing restoration snapshot."""
    from dataclasses import replace
    from backend.core.duplex_cluster import _duplex_domain_refs

    ids = [topology.driver_oh_id, topology.driven_oh_id]
    _, refs = _duplex_domain_refs(source, topology.driver_oh_id)
    strands = {s.id: s for s in source.strands}
    ids.extend(strands[r.strand_id].domains[r.domain_index].overhang_id for r in refs
               if strands[r.strand_id].domains[r.domain_index].overhang_id)
    targets = capture_root_lengths(source, ids)
    return replace(topology, snapshot={**topology.snapshot, "root_bond_lengths_nm": targets})


def capture_root_lengths(design, overhang_ids):
    """Serializable constraints measured before a placement operation."""
    result = {}
    for oid in dict.fromkeys(overhang_ids):
        lengths = {}
        for name, fast in BUILDERS:
            root = overhang_root_bond(design, oid, fast_bridges=fast)
            if root is not None:
                lengths[name] = root.length_nm
        if lengths:
            result[oid] = lengths
    return result


def _refuse():
    raise HTTPException(422, detail=(
        "The duplex cannot be placed while preserving its covalent root bonds. "
        "Move the parent parts or change the connection before applying it."
    ))


def fit_root_transform(moving, fixed, lengths):
    """Rigid transform satisfying every endpoint-distance constraint, or refuse.

    The triangle bound proves some inputs unreachable before optimization.
    Otherwise use deterministic starts and accept only an exact feasible pose.
    A failed finite search is a refusal, not a proof that no pose exists.
    """
    moving, fixed, lengths = map(lambda x: np.asarray(x, dtype=float), (moving, fixed, lengths))
    if (moving.ndim != 2 or moving.shape[1:] != (3,) or fixed.shape != moving.shape
            or lengths.shape != (len(moving),) or not len(moving)
            or not all(np.isfinite(x).all() for x in (moving, fixed, lengths))
            or np.any(lengths < 0)):
        raise ValueError("Root constraints require finite endpoint pairs and nonnegative lengths")
    pivot = moving.mean(axis=0)
    local = moving - pivot

    def endpoints(x):
        return local @ Rotation.from_rotvec(x[:3]).as_matrix().T + pivot + x[3:]

    def residual(x):
        return np.linalg.norm(endpoints(x) - fixed, axis=1) - lengths

    zero = np.zeros(6)
    if np.max(np.abs(residual(zero))) <= ROOT_TOLERANCE_NM:
        return np.eye(3), pivot, np.zeros(3)
    for i in range(len(lengths)):
        for j in range(i):
            # A native linker can change construction convention on relocation.
            # Identical final endpoint pairs cannot retain different old lengths.
            if (np.linalg.norm(moving[i] - moving[j]) + np.linalg.norm(fixed[i] - fixed[j])
                    + 2 * ROOT_TOLERANCE_NM < abs(lengths[i] - lengths[j])):
                raise HTTPException(422, detail=(
                    "The native viewer and export root linkers cannot both retain their "
                    "original lengths after this relocation. The connection was not applied."
                ))
    for i in range(len(lengths)):
        for j in range(i):
            separation_change = abs(np.linalg.norm(fixed[i] - fixed[j]) - np.linalg.norm(moving[i] - moving[j]))
            if separation_change > lengths[i] + lengths[j] + ROOT_TOLERANCE_NM:
                _refuse()

    starts = [zero, np.r_[np.zeros(3), fixed.mean(axis=0) - pivot]]
    i, j = np.unravel_index(np.argmax(np.linalg.norm(moving[:, None] - moving[None, :], axis=2)), (len(moving), len(moving)))
    if np.linalg.norm(moving[j] - moving[i]) > 1e-9 and np.linalg.norm(fixed[j] - fixed[i]) > 1e-9:
        from backend.core.direct_relax import _quat_align

        aligned = Rotation.from_quat(_quat_align(moving[j] - moving[i], fixed[j] - fixed[i]))
        axis = fixed[j] - fixed[i]
        axis /= np.linalg.norm(axis)
        for angle in (0., np.pi / 2, -np.pi / 2, np.pi):
            rotation = Rotation.from_rotvec(axis * angle) * aligned
            starts.append(np.r_[rotation.as_rotvec(), fixed.mean(axis=0) - pivot])
    feasible = []
    for start in starts:
        solved = least_squares(residual, start, max_nfev=400, ftol=1e-12, xtol=1e-12, gtol=1e-12)
        if np.max(np.abs(residual(solved.x))) <= ROOT_TOLERANCE_NM:
            radius2 = max(float(np.mean(np.sum(local * local, axis=1))), .01)
            score = float(np.mean(np.sum((endpoints(solved.x) - moving) ** 2, axis=1)))
            score += radius2 * Rotation.from_rotvec(solved.x[:3]).magnitude() ** 2
            feasible.append((score, solved.x))
    if not feasible:
        _refuse()
    x = min(feasible, key=lambda row: row[0])[1]
    return Rotation.from_rotvec(x[:3]).as_matrix(), pivot, x[3:]


def place_direct_roots(design, driver_id, targets):
    """Preserve roots, except fixed roots on one rigid body: retain their strain."""
    from backend.core.duplex_cluster import dematerialize_duplex_cluster, duplex_cluster_for, materialize_duplex_cluster
    from backend.core.direct_root_policy import root_length_exemptions

    if not targets:
        return design
    exemptions = root_length_exemptions(design, targets)
    if exemptions:
        exempt_ids = {oid for group in exemptions for oid in group["overhang_ids"]}
        remaining = {oid: expected for oid, expected in targets.items() if oid not in exempt_ids}
        # Retaining an exempt pose needs no atom construction or numerical fit.
        # Only other roots on this duplex still need a distance check.
        measured = capture_root_lengths(design, remaining)
        # One rigid duplex cannot be moved to repair other roots while retaining
        # an exempt group's authored strain. Do not extend the exemption to them.
        for oid, expected in remaining.items():
            if oid not in measured or any(name not in measured[oid] for name in expected):
                raise ValueError("Direct placement lost a covalent root constraint")
            if any(abs(measured[oid][name] - value) > ROOT_TOLERANCE_NM
                   for name, value in expected.items()):
                _refuse()
        return design
    cluster = duplex_cluster_for(design, driver_id)
    working = dematerialize_duplex_cluster(design, driver_id)
    moving, fixed, lengths = [], [], []
    for oid, expected in targets.items():
        for name, fast in BUILDERS:
            root = overhang_root_bond(working, oid, fast_bridges=fast)
            if root is None or name not in expected:
                raise ValueError("Direct placement lost a covalent root constraint")
            moving.append(root.moving)
            fixed.append(root.fixed)
            lengths.append(expected[name])
    rotation, pivot, translation = fit_root_transform(moving, fixed, lengths)
    if np.array_equal(rotation, np.eye(3)) and not np.any(translation):
        return design
    out = rotate_overhang_about(working, driver_id, rotation, pivot,
                               translation=translation, materialize=False)
    if cluster is not None:
        out, _ = materialize_duplex_cluster(out, driver_id, cluster_id=cluster.id, name=cluster.name)
    measured = capture_root_lengths(out, targets)
    if any(abs(measured[oid][name] - value) > ROOT_TOLERANCE_NM
           for oid, expected in targets.items() for name, value in expected.items()):
        _refuse()
    return out
