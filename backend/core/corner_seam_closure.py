"""Approved Corner seam closure, derived geometry only.

Promoted from the inspected joint-seam diagnostic on November 23, 2026.
Insert rings move rigidly; duplex rings remain fixed. This geometric fit is
not a molecular dynamics relaxation or a statement of physical stability.
"""

import numpy as np
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation
from numba.typed import List

from backend.core.corner_local_environment import LocalEnvironment
from backend.core import corner_closure_math as compiled



def _key(atom):
    return atom.helix_id, atom.bp_index, atom.direction, atom.crossover_id, atom.extra_base_k


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
        adjacent = np.zeros((len(model.atoms), len(model.atoms)), dtype=bool)
        for i, j in model.bonds:
            adjacent[i, j] = adjacent[j, i] = True
        movable = free_set | set(self.owners)
        self.movable = np.array(sorted(movable), dtype=int)
        self.environment = None if environment is None else LocalEnvironment(environment)
        self.query_bounds = None
        moving = np.zeros(len(model.atoms), dtype=bool)
        moving[self.movable] = True
        self.pairs = compiled.eligible_pairs(adjacent, moving)
        self.compiled_rigid = List(self.rigid)
        self.compiled_offsets = List(self.rigid_offsets)
        self.compiled_branches = List([
            np.array([b[0] for b in row], dtype=np.int64) for row in self.body_branches])
        self.compiled_branch_offsets = List([
            np.array([b[1] for b in row], dtype=float).reshape(-1, 3) for row in self.body_branches])
        self.branch_array = np.array(self.branches, dtype=np.int64).reshape(-1, 2)
        self.compiled_bodies = List(self.bodies)
        self.compiled_body_offsets = List(self.body_offsets)
        self.compiled_pivots = np.asarray(self.pivots)
        self.all_branch_offsets = np.asarray([b[2] for b in self.branch_offsets]).reshape(-1, 3)
        self.all_branch_owners = np.asarray([
            b[3] if b[3] is not None else -1 for b in self.branch_offsets], dtype=np.int64)

    def coordinates(self, x):
        poses = x[:self.variable_start].reshape(-1, 6)
        rotations = Rotation.from_rotvec(poses[:, 3:]).as_matrix()
        xyz = compiled.coordinates(
            x, self.original, self.variable_start, self.compiled_bodies,
            self.compiled_body_offsets, self.compiled_pivots, self.free,
            self.branch_array, self.all_branch_offsets, self.all_branch_owners, rotations)
        return xyz, rotations

    def objective(self, x):
        xyz, rotations = self.coordinates(x)
        cost, gradient = compiled.local_gradient(xyz, self.bridges, self.pairs, 2.)
        if self.environment is not None:
            if self.query_bounds is None:
                self.query_bounds = np.array([[np.inf] * 3, [-np.inf] * 3])
            compiled.extend_query_bounds(xyz, self.movable, self.query_bounds)
            cost += self.environment.accumulate(xyz, self.movable, gradient)
        penalty, gradient = compiled.pose_gradient(
            x, self.x0, self.variable_start, self.compiled_rigid, self.compiled_offsets,
            rotations, self.compiled_branches, self.compiled_branch_offsets,
            self.branch_array, self.free, gradient, 2.)
        return cost+penalty, gradient


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
