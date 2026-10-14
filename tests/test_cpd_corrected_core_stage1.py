"""Safety gates for the bounded, unconstrained corrected-core attempt."""
import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_stage1 import (
    admission, checked, metrics, native_audit, pin, stationary,
)


def test_native_exit_does_not_replace_electronic_convergence():
    gradient = np.zeros((36, 3))
    with pytest.raises(ValueError, match="SCF"):
        native_audit("exited normally", -100., gradient)
    with pytest.raises(ValueError, match="response"):
        native_audit("Energy and wave function converged.\nCGR 3 1 0 1.0E-07", -100., gradient)
    result = native_audit("Energy and wave function converged.\nCGR 30 1 0 1.0E-11", -100., gradient)
    assert result["scf_converged"]
    assert result["response_residuals"] == [1e-11]


def test_unconstrained_stationarity_retains_every_force_component():
    gradient = np.zeros((36, 3))
    gradient[0, 2] = 2e-5
    assert not stationary(metrics(gradient))
    gradient[:] = [0, 0, 1.1e-5]
    assert not stationary(metrics(gradient))
    gradient[:] = [0, 0, 9e-6]
    assert stationary(metrics(gradient))
    gradient[0, 0] = np.nan
    with pytest.raises(ValueError, match="gradient"):
        metrics(gradient)


def test_no_new_gradient_crosses_allocation_or_checkpoint_boundary():
    with pytest.raises(RuntimeError, match="allocation"):
        admission(60, 60, 1000, [10])
    with pytest.raises(RuntimeError, match="boundary"):
        admission(1, 60, 179, [100])
    admission(1, 60, 181, [100])
    with pytest.raises(RuntimeError, match="boundary"):
        admission(0, 1, 89, [])


def test_changed_native_evidence_cannot_replay(tmp_path):
    target = tmp_path/"native.dat"
    target.write_text("preserved failure")
    ref = pin(target)
    assert checked(ref) == target
    target.write_text("replacement success")
    with pytest.raises(ValueError, match="Changed source"):
        checked(ref)


def test_native_table_parser_rejects_missing_or_reordered_atoms():
    from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table
    native = ('Total Energy = -123.456 [Eh]\n-Total Gradient:\n'
              '1 0.000001 0.0 -0.000002\n2 0.0 0.000003 0.0\n')
    energy, gradient = parse_native_table(native, 2)
    assert energy == -123.456
    np.testing.assert_allclose(gradient, [[1e-6,0,-2e-6],[0,3e-6,0]])
    with pytest.raises(ValueError, match="incomplete or out of order"):
        parse_native_table(native, 3)
    with pytest.raises(ValueError, match="incomplete or out of order"):
        parse_native_table(native.replace('2 0.0', '1 0.0'), 2)
    with pytest.raises(ValueError, match="ambiguous"):
        parse_native_table('Total Energy = -100.0 [Eh]\n'+native, 2)
