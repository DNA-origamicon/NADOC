"""Keep exact degree targets while accepting audited restart angle residuals.

The v1 implementation is preserved for historical source pins. Fresh seeds still
use its strict startup check; accepted restarts use the existing native angle
tolerance without moving coordinates or changing the installed target.
"""
import numpy as np

from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR
from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle
from experiments.cpd_anti_additive.endpoint_scan_geometry import wrapped


def verify_constraint_configuration(constraints, spec, *, accepted_restart=False):
    targets = np.asarray(constraints.targets)
    residual = np.asarray(constraints.residual())
    if targets.shape != (1,) or residual.shape != (1,) or not np.isfinite([targets, residual]).all():
        raise ValueError('Expected exactly one finite glycosidic constraint')
    actual_target = float(np.degrees(targets[0]))
    if abs(wrapped(actual_target - spec['target_degrees'])) > 1e-8:
        raise ValueError('Installed Sella target differs from planned degree target')
    tolerance = min(float(spec['tolerance_degrees']), 0.01)
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Invalid restart angle tolerance')
    limit = np.radians(tolerance) if accepted_restart else 1e-8
    if abs(residual[0]) >= limit:
        raise ValueError('Initial Sella constraint residual is not satisfied')
    return dict(installed_target_degrees=actual_target,
                initial_residual_radians=float(residual[0]),
                accepted_restart=accepted_restart, residual_limit_radians=float(limit))


def make_scan_constraints(atoms, spec, *, accepted_restart=False):
    from sella import Constraints
    physical = require_scan_angle(atoms.positions / BOHR, spec)
    constraints = Constraints(atoms)
    constraints.fix_dihedral(tuple(spec['indices']), target=spec['target_degrees'])
    report = {**physical, **verify_constraint_configuration(
        constraints, spec, accepted_restart=accepted_restart)}
    return constraints, report
