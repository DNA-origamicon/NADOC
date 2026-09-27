import numpy as np
import pytest

from experiments.cpd_anti_additive.sella_pilot import force_pass, projected_metrics


def test_torsion_normal_removed_but_tangent_force_retained():
    xyz = np.array([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.], [1., 0., 1.]])
    # Analytic normal at this orthogonal geometry, in radians per coordinate unit.
    normal = np.array([[0., 0., -1.], [0., 0., 1.], [0., 1., 0.], [0., -1., 0.]])
    tangent = np.tile([.1, .2, .3], (4, 1))
    for h in (1e-4, 1e-5, 1e-6):
        result = projected_metrics(xyz, 5*normal+tangent, [0, 1, 2, 3], h)
        assert result['max_projected_atom_gradient'] == pytest.approx(np.linalg.norm(tangent[0]), abs=2e-8)
        assert result['rms_projected_atom_gradient'] == pytest.approx(np.linalg.norm(tangent[0]), abs=2e-8)


def test_native_success_cannot_substitute_for_both_force_limits():
    limits = dict(max_gradient=1.5e-5, rms_gradient=1e-5)
    assert not force_pass(dict(max_projected_atom_gradient=4.6722e-5,
                               rms_projected_atom_gradient=1.00107e-5), limits)
    assert not force_pass(dict(max_projected_atom_gradient=1.4e-5,
                               rms_projected_atom_gradient=1.1e-5), limits)
    assert force_pass(dict(max_projected_atom_gradient=1.4e-5,
                          rms_projected_atom_gradient=9e-6), limits)


def test_projection_rejects_nonfinite_data():
    with pytest.raises(ValueError, match='Nonfinite'):
        projected_metrics(np.zeros((4, 3)), np.full((4, 3), np.nan), [0, 1, 2, 3])
