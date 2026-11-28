"""Compiled arithmetic for the approved Corner fit, without fast math.

Floating exponents are runtime arguments deliberately: CPython/NumPy use libm
pow for these scalar powers. Folding a square into a multiply changes some last
bits and therefore changes the optimizer trajectory. Keep the reductions,
scatter order and BLAS operations identical to the reference calculation.
"""

import math
import numpy as np
from numba import njit
from backend.core.corner_seam_bridge_math import _bridge_terms, _bridge_cost_terms
from backend.core.corner_seam_math import clearance_gradient, cross


@njit(cache=True)
def extend_query_bounds(xyz, movable, bounds):
    for i in movable:
        for k in range(3):
            bounds[0, k] = min(bounds[0, k], xyz[i, k])
            bounds[1, k] = max(bounds[1, k], xyz[i, k])


@njit(cache=True)
def eligible_pairs(adjacent, moving):
    # Sparse two-bond walks instead of a dense Boolean matrix product.
    excluded = adjacent.copy()
    for i in range(len(adjacent)):
        for j in range(len(adjacent)):
            if adjacent[i, j]:
                for k in range(len(adjacent)):
                    if adjacent[j, k]:
                        excluded[i, k] = True
    pairs = []
    for i in range(len(adjacent)):
        for j in range(i + 1, len(adjacent)):
            if (moving[i] or moving[j]) and not excluded[i, j]:
                pairs.append((i, j))
    result = np.empty((len(pairs), 2), dtype=np.int64)
    for i in range(len(pairs)):
        result[i, 0], result[i, 1] = pairs[i]
    return result


@njit(cache=True)
def seed_costs(c3, xs, c5, power):
    out = np.empty(len(xs))
    for i, x in enumerate(xs):
        a, b, c, d, e, f, g = _bridge_cost_terms(c3, x[:3], x[3:6], x[6:], c5)
        out[i] = (
            math.pow(a, power)
            + math.pow(b, power)
            + math.pow(c, power)
            + math.pow(d, power)
            + 0.1 * (math.pow(e, power) + math.pow(f, power) + math.pow(g, power))
        )
    return out


@njit(cache=True)
def local_gradient(xyz, bridges, pairs, power):
    gradient = np.zeros_like(xyz)
    cost = 0.0
    for ids in bridges:
        terms, a, b, c, d, e = _bridge_terms(
            xyz[ids[0]], xyz[ids[1]], xyz[ids[2]], xyz[ids[3]], xyz[ids[4]]
        )
        u, v, w, x, y, z, t = terms
        value = (
            math.pow(u, power)
            + math.pow(v, power)
            + math.pow(w, power)
            + math.pow(x, power)
        ) + 0.1 * (math.pow(y, power) + math.pow(z, power) + math.pow(t, power))
        cost += 10 * value
        for i, g in enumerate((a, b, c, d, e)):
            for k in range(3):
                gradient[ids[i], k] += 10 * g[k]
    penetration = clearance_gradient(xyz, pairs, gradient)
    cost += np.dot(penetration, penetration)
    return cost, gradient


@njit(cache=True)
def right_jacobian(vector, power):
    theta = np.sqrt(np.dot(vector, vector))
    x, y, z = vector
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    if theta < 1e-7:
        return np.eye(3) - skew / 2 + skew @ skew / 6
    return (
        np.eye(3)
        - (1 - np.cos(theta)) / math.pow(theta, power) * skew
        + (theta - np.sin(theta)) / math.pow(theta, power + 1.0) * (skew @ skew)
    )


@njit(cache=True)
def pose_gradient(
    x,
    x0,
    variable_start,
    rigid,
    offsets,
    rotations,
    branches_by_body,
    branch_offsets_by_body,
    branches,
    free,
    gradient,
    power,
):
    poses = x[:variable_start].reshape(-1, 6)
    result = np.zeros((len(rigid), 6))
    for body in range(len(rigid)):
        ids, offset, rotation = rigid[body], offsets[body], rotations[body]
        result[body, :3] = gradient[ids].sum(axis=0)
        torque = cross(offset, gradient[ids] @ rotation).sum(axis=0)
        for i in range(len(branches_by_body[body])):
            oxygen = branches_by_body[body][i]
            torque += cross(
                branch_offsets_by_body[body][i], gradient[oxygen] @ rotation
            )
        result[body, 3:] = right_jacobian(poses[body, 3:], power).T @ torque
    for phosphorus, oxygen in branches:
        gradient[phosphorus] += gradient[oxygen]
    deviation = x - x0
    return 1e-5 * np.dot(deviation, deviation), np.concatenate(
        (result.ravel(), gradient[free].ravel())
    ) + 2e-5 * deviation


@njit(cache=True)
def coordinates(
    x,
    original,
    variable_start,
    bodies,
    offsets,
    pivots,
    free,
    branch_array,
    branch_offsets,
    branch_owners,
    rotations,
):
    poses = x[:variable_start].reshape(-1, 6)
    xyz = original.copy()
    for i in range(len(bodies)):
        xyz[bodies[i]] = offsets[i] @ rotations[i].T + pivots[i] + poses[i, :3]
    xyz[free] = x[variable_start:].reshape(-1, 3)
    for i in range(len(branch_array)):
        phosphorus, oxygen = branch_array[i]
        offset = branch_offsets[i]
        owner = branch_owners[i]
        xyz[oxygen] = xyz[phosphorus] + (
            rotations[owner] @ offset if owner >= 0 else offset
        )
    return xyz
