from types import SimpleNamespace
import numpy as np
import pytest

from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle, verify_constraint_configuration
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, rotate_sugar


def fixture_geometry():
    x = np.array([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.], [1., 0., 1.]])
    return x, dict(indices=[0, 1, 2, 3], target_degrees=torsion(x, [0, 1, 2, 3]), tolerance_degrees=0.01)


def test_off_target_geometry_is_rejected_before_qm():
    x, spec = fixture_geometry()
    assert require_scan_angle(x, spec)['torsion_error_degrees'] == 0
    y, _ = rotate_sugar(x, [(0, 1), (1, 2), (2, 3)], spec['indices'], 0.02)
    with pytest.raises(ValueError, match='before QM'):
        require_scan_angle(y, spec)


def test_unit_conversion_regression_detects_wrong_configured_target_at_valid_seed():
    _, spec = fixture_geometry()
    target = np.radians(spec['target_degrees'])
    correct = SimpleNamespace(targets=np.array([target]), residual=lambda: np.zeros(1))
    verify_constraint_configuration(correct, spec)
    wrong = SimpleNamespace(targets=np.array([np.radians(target)]), residual=lambda: np.array([target-np.radians(target)]))
    with pytest.raises(ValueError, match='degree target'):
        verify_constraint_configuration(wrong, spec)


def test_nonzero_startup_residual_is_rejected():
    _, spec = fixture_geometry()
    invalid = SimpleNamespace(targets=np.radians([spec['target_degrees']]), residual=lambda: np.array([1e-4]))
    with pytest.raises(ValueError, match='residual'):
        verify_constraint_configuration(invalid, spec)
