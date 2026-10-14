"""Explicit degree targets and guards before constrained QM acquisition."""
import numpy as np

from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped


def require_scan_angle(x_bohr, spec):
    angle = torsion(x_bohr, spec['indices'])
    error = abs(wrapped(angle - spec['target_degrees']))
    tolerance = min(float(spec['tolerance_degrees']), 0.01)
    if not np.isfinite([angle, error, tolerance]).all() or tolerance <= 0 or error >= tolerance:
        raise ValueError(f'Scan angle outside target before QM: {angle} deg; error {error} deg')
    return dict(torsion_degrees=angle, torsion_error_degrees=error)


def verify_constraint_configuration(constraints, spec):
    targets = np.asarray(constraints.targets)
    residual = np.asarray(constraints.residual())
    if targets.shape != (1,) or residual.shape != (1,) or not np.isfinite([targets, residual]).all():
        raise ValueError('Expected exactly one finite glycosidic constraint')
    actual_target = float(np.degrees(targets[0]))
    if abs(wrapped(actual_target - spec['target_degrees'])) > 1e-8:
        raise ValueError('Installed Sella target differs from planned degree target')
    if abs(residual[0]) > 1e-8:
        raise ValueError('Initial Sella constraint residual is not satisfied')
    return dict(installed_target_degrees=actual_target, initial_residual_radians=float(residual[0]))


def make_scan_constraints(atoms, spec):
    from sella import Constraints
    physical = require_scan_angle(atoms.positions / BOHR, spec)
    constraints = Constraints(atoms)
    # Public fix_dihedral(target=...) accepts degrees, although targets/calc use radians.
    constraints.fix_dihedral(tuple(spec['indices']), target=spec['target_degrees'])
    report = {**physical, **verify_constraint_configuration(constraints, spec)}
    return constraints, report
