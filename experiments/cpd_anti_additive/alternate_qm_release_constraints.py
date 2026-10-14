"""Single-chi constraints for the audited alternate endpoint core release."""
import numpy as np

from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR
from experiments.cpd_anti_additive.corrected_fixed_core_boundary import free_projection
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import make_scan_constraints
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped


def geometry_constraints(x_bohr, reference_bohr, fixed, spec):
    x = np.asarray(x_bohr, float)
    if fixed:
        raise ValueError('Released endpoint must not fix any atom positions')
    if x.shape != np.asarray(reference_bohr).shape or not np.isfinite(x).all():
        raise ValueError('Invalid constrained geometry')
    error = abs(wrapped(torsion(x, spec['indices']) - spec['target_degrees']))
    if error > min(.01, spec['tolerance_degrees']):
        raise ValueError('Trial violates chi target')
    return dict(fixed_atom_count=0, chi_error_degrees=error,
                maximum_coordinate_change_from_original_A=float(np.max(abs(x-reference_bohr))*BOHR),
                coordinate_change_is_constraint_error=False)


def stationarity(x_bohr, gradient_au, fixed, free, spec):
    x = np.asarray(x_bohr, float)
    if fixed or list(free) != list(range(len(x))):
        raise ValueError('All endpoint atoms must contribute to released stationarity')
    tangent = free_projection(x*BOHR, gradient_au, [], spec['indices'])
    norms = np.linalg.norm(tangent, axis=1)
    maximum = float(norms.max())
    rms = float(np.sqrt(np.mean(norms**2)))
    return dict(max_free_projected_atom_gradient_au=maximum,
                rms_free_projected_atom_gradient_au=rms,
                passed=maximum < 1.5e-5 and rms < 1e-5,
                scope='Single fixed chi; all49endpoint atoms free; RMS over all49atoms. No minimum certification.')


def constraints_for(atoms, reference_bohr, fixed, spec):
    geometry_constraints(atoms.positions/BOHR, reference_bohr, fixed, spec)
    constraints, configuration = make_scan_constraints(atoms, spec, accepted_restart=True)
    rank = int(np.linalg.matrix_rank(constraints.jacobian(), tol=1e-8))
    if rank != 1:
        raise ValueError('Expected only one independent chi constraint')
    return constraints, dict(**configuration, rank=rank, free_dimensions=3*len(atoms)-rank,
                             fixed_atom_count=0, internal_free_dimensions=3*len(atoms)-rank-6,
                             fixed_target='Only original chi target; no fixed Cartesian coordinates.')
