"""Rigid-nucleotide bond/angle/steric projection for isolated Exp candidates.

Uses CHARMM36 equilibrium angles, not trajectory labels. This is a constrained
reconstruction objective, not a force field or equilibrium simulation.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from backend.core.exp_local import psf_block

PARAMETERS = Path(__file__).resolve().parents[1] / "data/forcefield/par_all36_na.prm"


def inter_angles(psf, residue_index):
    lines = psf.splitlines()
    start = next(i for i, line in enumerate(lines) if "!NATOM" in line)
    n = int(lines[start].split()[0])
    types = [line.split()[5] for line in lines[start + 1 : start + 1 + n]]
    angles = psf_block(psf, "!NTHETA", 3)
    r = residue_index[angles]
    angles = angles[
        (r >= 0).all(axis=1) & ((r[:, 0] != r[:, 1]) | (r[:, 1] != r[:, 2]))
    ]
    table = {}
    active = False
    for line in PARAMETERS.read_text().splitlines():
        f = line.split("!")[0].split()
        if f == ["ANGLES"]:
            active = True
            continue
        if f == ["DIHEDRALS"]:
            break
        if active and len(f) >= 5:
            table[tuple(f[:3])] = float(f[4])
            table[tuple(reversed(f[:3]))] = float(f[4])
    equilibrium = np.array([table[tuple(types[i] for i in a)] for a in angles])
    return angles, np.cos(np.radians(equilibrium))


def coordinates(parameters, offsets, ri, centers):
    p = parameters.reshape(-1, 6)
    rotated = np.einsum(
        "nij,nj->ni", Rotation.from_rotvec(p[:, 3:]).as_matrix()[ri], offsets
    )
    return rotated + centers[ri] + p[ri, :3], rotated


def objective(parameters, offsets, ri, centers, bonds, angles, angle_cos, pairs):
    p = parameters.reshape(-1, 6)
    xyz, rotated = coordinates(parameters, offsets, ri, centers)
    value = 0.5 * np.sum(p[:, :3] ** 2) + 0.125 * np.sum(p[:, 3:] ** 2)
    force = np.zeros_like(xyz)
    for links, target, weight, repulsive in [
        (bonds, 0.160, 400.0, False),
        (pairs, 0.18, 100.0, True),
    ]:
        a, b = links.T
        vector = xyz[a] - xyz[b]
        distance = np.linalg.norm(vector, axis=1).clip(1e-10)
        error = distance - target
        if repulsive:
            error = np.minimum(error, 0)
        value += 0.5 * weight * np.dot(error, error)
        gradient = weight * (error / distance)[:, None] * vector
        np.add.at(force, a, gradient)
        np.add.at(force, b, -gradient)
    a, b, c = angles.T
    u, v = xyz[a] - xyz[b], xyz[c] - xyz[b]
    lu, lv = (
        np.linalg.norm(u, axis=1).clip(1e-10),
        np.linalg.norm(v, axis=1).clip(1e-10),
    )
    cosine = np.einsum("ni,ni->n", u, v) / (lu * lv)
    residual = cosine - angle_cos
    value += np.dot(
        residual, residual
    )  # angle weight 2; cos residual stays finite near collinearity
    gu = (
        2
        * residual[:, None]
        * (v / (lu * lv)[:, None] - cosine[:, None] * u / (lu * lu)[:, None])
    )
    gv = (
        2
        * residual[:, None]
        * (u / (lu * lv)[:, None] - cosine[:, None] * v / (lv * lv)[:, None])
    )
    np.add.at(force, a, gu)
    np.add.at(force, c, gv)
    np.add.at(force, b, -gu - gv)
    grad = np.empty_like(p)
    grad[:, :3] = p[:, :3]
    grad[:, 3:] = 0.25 * p[:, 3:]
    np.add.at(grad[:, :3], ri, force)
    torque = np.zeros_like(centers)
    np.add.at(torque, ri, np.cross(rotated, force))
    w = p[:, 3:]
    theta = np.linalg.norm(w, axis=1)
    small = theta < 1e-5
    t = theta.clip(1e-10)
    aa = np.where(small, 0.5 - theta**2 / 24, (1 - np.cos(t)) / t**2)
    bb = np.where(small, 1 / 6 - theta**2 / 120, (t - np.sin(t)) / t**3)
    grad[:, 3:] += (
        torque
        - aa[:, None] * np.cross(w, torque)
        + bb[:, None] * np.cross(w, np.cross(w, torque))
    )
    return float(value), grad.ravel()


def project(data, raw, angles, angle_cos, cancel=None, rounds=3, iterations=250):
    ri = data["ri"]
    centers = np.array([raw[g].mean(0) for g in data["groups"]])
    offsets = raw - centers[ri]
    parameters = np.zeros((len(centers), 6))
    heavy = np.flatnonzero(data["heavy"])
    n = len(ri)
    excluded = {int(min(a, b) * n + max(a, b)) for a, b in data["bonds"]}
    neighbors = [[] for _ in ri]
    for a, b in data["bonds"]:
        neighbors[a].append(b)
        neighbors[b].append(a)
    for group in neighbors:
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                excluded.add(int(min(a, b) * n + max(a, b)))
    evaluations = 0
    history = []
    for _ in range(rounds):
        xyz, _ = coordinates(parameters, offsets, ri, centers)
        pairs = heavy[cKDTree(xyz[heavy]).query_pairs(0.26, output_type="ndarray")]
        pairs = np.array(
            [
                p
                for p in pairs
                if ri[p[0]] != ri[p[1]] and int(min(p) * n + max(p)) not in excluded
            ],
            dtype=int,
        ).reshape(-1, 2)

        def evaluate(p):
            if cancel and cancel():
                raise InterruptedError("Prediction stopped")
            return objective(
                p, offsets, ri, centers, data["cross"], angles, angle_cos, pairs
            )

        result = minimize(
            evaluate,
            parameters.ravel(),
            jac=True,
            method="L-BFGS-B",
            options=dict(maxiter=iterations, ftol=1e-10, gtol=1e-5, maxcor=10),
        )
        parameters = result.x.reshape(-1, 6)
        evaluations += result.nfev
        history.append(
            dict(
                converged=bool(result.success),
                iterations=result.nit,
                objective=float(result.fun),
            )
        )
    xyz, _ = coordinates(parameters, offsets, ri, centers)
    return xyz, dict(
        schema="rigid-bond-angle-v2",
        converged=bool(result.success),
        message=str(result.message),
        evaluations=evaluations,
        rounds=history,
        max_translation_nm=float(np.linalg.norm(parameters[:, :3], axis=1).max()),
        max_rotation_rad=float(np.linalg.norm(parameters[:, 3:], axis=1).max()),
    )
