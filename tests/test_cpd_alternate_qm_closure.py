"""Bounded native acquisition and constrained stationarity safety checks."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_alternate_qm_closure import (
    BOHR, ChunkBoundary, admit, geometry_constraints, stationarity,
)
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion


def geometry_and_spec():
    x = np.array([[1., .2, .7], [0., 0., 0.], [.1, 1.1, 0.],
                  [.2, 1.3, 1.2], [2., 1., 1.]])
    spec = dict(indices=[0, 1, 2, 3], target_degrees=torsion(x, [0, 1, 2, 3]),
                tolerance_degrees=.01)
    return x, spec


def test_budget_preserves_time_for_complete_gradient_and_checkpoint():
    plan = dict(max_new_gradients=12, task_timeout_seconds=600)
    admit(11, 631, plan)
    for count, remaining in [(12, 1000), (0, 630), (0, 500)]:
        with pytest.raises(ChunkBoundary):
            admit(count, remaining, plan)


def test_fixed_targets_remain_original_across_a_restart():
    reference, spec = geometry_and_spec()
    # Use an atom outside chi so the fixed-coordinate gate is isolated.
    checkpoint = reference.copy()
    checkpoint[4, 0] += .75e-7 / BOHR
    geometry_constraints(checkpoint, reference, [4], spec)
    trial = checkpoint.copy()
    trial[4, 0] += .75e-7 / BOHR
    with pytest.raises(ValueError, match='fixed-core or chi'):
        geometry_constraints(trial, reference, [4], spec)


def test_changed_glycosidic_angle_is_rejected_before_native_work():
    reference, spec = geometry_and_spec()
    trial = reference.copy()
    trial[3, 0] += .1
    with pytest.raises(ValueError, match='fixed-core or chi'):
        geometry_constraints(trial, reference, [4], spec)


def test_nonfinite_geometry_is_rejected():
    reference, spec = geometry_and_spec()
    trial = reference.copy()
    trial[0, 0] = np.nan
    with pytest.raises(ValueError, match='Invalid'):
        geometry_constraints(trial, reference, [4], spec)


def test_rms_uses_free_atoms_without_dilution_by_fixed_zeros():
    x, spec = geometry_and_spec()
    gradient = np.zeros_like(x)
    gradient[4, 0] = 1.49e-5
    result = stationarity(x, gradient, [0, 1, 2], [3, 4], spec)
    assert result['max_free_projected_atom_gradient_au'] < 1.5e-5
    assert result['rms_free_projected_atom_gradient_au'] == pytest.approx(1.49e-5 / np.sqrt(2))
    assert not result['passed']


def test_fixed_atom_reaction_forces_do_not_prevent_free_stationarity():
    x, spec = geometry_and_spec()
    gradient = np.zeros_like(x)
    gradient[[0, 1, 2]] = 1e8
    assert stationarity(x, gradient, [0, 1, 2], [3, 4], spec)['passed']
