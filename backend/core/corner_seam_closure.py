"""Approved Corner seam closure, derived geometry only.

Promoted from the inspected joint-seam diagnostic on November 23, 2026.
Insert rings move rigidly; duplex rings remain fixed. This geometric fit is
not a molecular dynamics relaxation or a statement of physical stability.
"""

import numpy as np
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation
from scipy.spatial import cKDTree

from backend.core.corner_seam_bridge_math import bridge_cost_grad as _backbone_bridge_cost_grad
from backend.core.corner_seam_math import cross, scatter_add, clearance_gradient


def _key(atom):
    return atom.helix_id, atom.bp_index, atom.direction, atom.crossover_id, atom.extra_base_k


def _right_jacobian(vector):
    theta = np.linalg.norm(vector)
    x, y, z = vector
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    if theta < 1e-7:
        return np.eye(3) - skew/2 + skew@skew/6
    return np.eye(3) - (1-np.cos(theta))/theta**2*skew + (theta-np.sin(theta))/theta**3*(skew@skew)


class ComponentClosure:
    def __init__(self, model, *, environment=None):
        self.original = np.array([[a.x, a.y, a.z] for a in model.atoms])
        residues = {}
        for atom in model.atoms:
            residues.setdefault(_key(atom), {})[atom.name] = atom.serial
        self.bodies = [np.array(list(row.values())) for key, row in residues.items() if key[3]]
        self.pivots = [self.original[ids].mean(axis=0) for ids in self.bodies]
        bridges = []
        for i, j in model.bonds:
            a, b = model.atoms[i], model.atoms[j]
            if a.name == 'P' and b.name == "O3'":
                a, b = b, a
            if a.name == "O3'" and b.name == 'P':
                src, dst = residues[_key(a)], residues[_key(b)]
                bridges.append([src["C3'"], src["O3'"], dst['P'], dst["O5'"], dst["C5'"]])
        self.bridges = np.asarray(bridges, dtype=int)
        self.free = self.bridges[:, 1:4].ravel()
        if len(set(self.free)) != len(self.free):
            raise ValueError('Closure component has duplicate phosphate ownership.')
        self.branches = []
        for row in residues.values():
            if row.get('P') in self.free:
                self.branches.extend((row['P'], row[name]) for name in ('OP1', 'OP2') if name in row)
        self.variable_start = 6*len(self.bodies)
        self.x0 = np.r_[np.zeros(self.variable_start), self.original[self.free].ravel()]
        free_set = set(self.free) | {i for _, i in self.branches}
        self.rigid = [np.array([i for i in ids if i not in free_set], dtype=int) for ids in self.bodies]
        self.owners = {int(i): b for b, ids in enumerate(self.bodies) for i in ids}
        # These offsets and ownership lists are invariant for the entire fit.
        # Keep their original subtraction and iteration order, but do it once
        # instead of allocating the same arrays at every objective evaluation.
        self.body_offsets = [self.original[ids]-pivot for ids, pivot in zip(self.bodies, self.pivots)]
        self.rigid_offsets = [self.original[ids]-pivot for ids, pivot in zip(self.rigid, self.pivots)]
        self.branch_offsets = [(p, o, self.original[o]-self.original[p], self.owners.get(o))
                               for p, o in self.branches]
        self.body_branches = [[(o, offset) for _, o, offset, owner in self.branch_offsets if owner == body]
                              for body in range(len(self.bodies))]
        adjacent = {i: set() for i in range(len(model.atoms))}
        for i, j in model.bonds:
            adjacent[i].add(j)
            adjacent[j].add(i)
        movable = free_set | set(self.owners)
        self.movable = np.array(sorted(movable), dtype=int)
        self.environment = (None if environment is None else
                            cKDTree(np.asarray(environment, dtype=float).reshape(-1, 3)))
        self.query_bounds = None
        pairs = [(i, j) for i in range(len(model.atoms)) for j in range(i+1, len(model.atoms))
                 if (i in movable or j in movable) and j not in adjacent[i]
                 and not adjacent[i].intersection(adjacent[j])]
        self.pairs = np.asarray(pairs, dtype=int)

    def coordinates(self, x):
        poses = x[:self.variable_start].reshape(-1, 6)
        rotations = Rotation.from_rotvec(poses[:, 3:]).as_matrix()
        xyz = self.original.copy()
        for body, offset, pivot, pose, rotation in zip(self.bodies, self.body_offsets, self.pivots, poses, rotations):
            xyz[body] = offset@rotation.T + pivot + pose[:3]
        xyz[self.free] = x[self.variable_start:].reshape(-1, 3)
        for phosphorus, oxygen, offset, owner in self.branch_offsets:
            xyz[oxygen] = xyz[phosphorus] + (rotations[owner]@offset if owner is not None else offset)
        return xyz, rotations

    def objective(self, x):
        xyz, rotations = self.coordinates(x)
        gradient = np.zeros_like(xyz)
        cost = 0.
        for ids in self.bridges:
            value, *g = _backbone_bridge_cost_grad(*xyz[ids])
            cost += 10*value
            scatter_add(gradient, ids, 10*np.asarray(g))
        # A bounded local clearance penalty, not a physical simulation or a
        # chemical-validity oracle. Independent clash/piercing checks still run.
        penetration = clearance_gradient(xyz, self.pairs, gradient)
        cost += float(penetration@penetration)
        if self.environment is not None:
            queries = xyz[self.movable]
            bounds = np.array([queries.min(axis=0), queries.max(axis=0)])
            self.query_bounds = bounds if self.query_bounds is None else np.array([
                np.minimum(self.query_bounds[0], bounds[0]), np.maximum(self.query_bounds[1], bounds[1])])
        if self.environment is not None and self.environment.n:
            neighbours = self.environment.query_ball_point(queries, .20)
            counts = np.array([len(row) for row in neighbours])
            if counts.sum():
                own = np.repeat(self.movable, counts)
                other = np.concatenate(neighbours).astype(int)
                delta = xyz[own]-self.environment.data[other]
                distance = np.linalg.norm(delta, axis=1)
                penetration = distance-.20
                cost += float(penetration@penetration)
                scatter_add(gradient, own, (2*penetration/np.maximum(distance, 1e-12))[:, None]*delta)
        pose_gradient = np.zeros((len(self.bodies), 6))
        poses = x[:self.variable_start].reshape(-1, 6)
        for body, (ids, offset, rotation) in enumerate(zip(self.rigid, self.rigid_offsets, rotations)):
            pose_gradient[body, :3] = gradient[ids].sum(axis=0)
            torque = cross(offset, gradient[ids]@rotation).sum(axis=0)
            for oxygen, branch_offset in self.body_branches[body]:
                torque += cross(branch_offset, gradient[oxygen]@rotation)
            pose_gradient[body, 3:] = _right_jacobian(poses[body, 3:]).T@torque
        for phosphorus, oxygen in self.branches:
            gradient[phosphorus] += gradient[oxygen]
        # Select a nearby solution among underdetermined chain conformations.
        deviation = x-self.x0
        cost += 1e-5*float(deviation@deviation)
        return cost, np.r_[pose_gradient.ravel(), gradient[self.free].ravel()] + 2e-5*deviation


def close_component(model, *, max_iterations=400, environment=None):
    from backend.core.corner_seam_cache import fit_key, get_fit, put_fit
    from backend.core.corner_seam_dependencies import find_dependency, remember_dependency, trace_box

    problem = ComponentClosure(model, environment=environment)
    key = fit_key(problem, max_iterations)
    cached = get_fit(key)
    if cached is None:
        cached = find_dependency(problem, max_iterations)
    if cached is None:
        result = minimize(problem.objective, problem.x0, jac=True, method='L-BFGS-B',
                          options={'maxiter': max_iterations, 'ftol': 1e-12, 'gtol': 1e-7})
        xyz, _ = problem.coordinates(result.x)
        report = {'converged': bool(result.success), 'iterations': result.nit,
                  'objective': float(result.fun), 'preserves_terminal_gamma': False,
                  'max_displacement_nm': float(np.linalg.norm(xyz-problem.original, axis=1).max())}
        report['_environment_bounds'] = (None if problem.query_bounds is None else problem.query_bounds.tolist())
        put_fit(key, xyz, report)
        remember_dependency(problem, max_iterations, xyz, report)
    else:
        xyz, report = cached
    trace_box(report.get('_environment_bounds'), fit=True)
    for atom, position in zip(model.atoms, xyz):
        atom.x, atom.y, atom.z = map(float, position)
    return {key: value for key, value in report.items() if key != '_environment_bounds'}
