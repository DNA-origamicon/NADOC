import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_curvature_pilot import summarize


def samples(slope=0., curvature=.1, cubic=0., quartic=0., gradient_bias=0.):
    def energy(t):
        return slope*t + curvature*t*t/2 + cubic*t**3 + quartic*t**4

    def gradient(t):
        return np.array([[slope + curvature*t + 3*cubic*t*t + 4*quartic*t**3 + gradient_bias, 0., 0.]])

    return [(h, energy(h), energy(-h), gradient(h), gradient(-h)) for h in (.02, .01)]


def test_stationary_quadratic_has_curvature_without_relative_slope_gate():
    r = summarize([[1., 0., 0.]], samples(), [0., 0.], 0.)
    assert r['richardson_energy_slope_au'] == pytest.approx(0.)
    assert r['richardson_gradient_curvature_au'] == pytest.approx(.1)
    assert r['energy_curvature_without_reference_energy_au'] == pytest.approx(.1)
    assert not r['minimum_certified']
    assert 'passed' not in r


def test_richardson_removes_cubic_slope_and_quartic_curvature_error():
    r = summarize([[1., 0., 0.]], samples(.003, .1, cubic=2., quartic=3.), [.003, .003], 0.)
    assert r['richardson_energy_slope_au'] == pytest.approx(.003)
    assert r['richardson_gradient_curvature_au'] == pytest.approx(.1)
    assert r['slope_step_correction_au'] > 0
    assert r['curvature_step_correction_au'] > 0


def test_constant_gradient_bias_remains_visible_despite_correct_curvature():
    r = summarize([[1., 0., 0.]], samples(gradient_bias=.01), [.01, .010001], 1e-8)
    assert min(r['absolute_slope_errors_au']) == pytest.approx(.01)
    assert r['richardson_gradient_curvature_au'] == pytest.approx(.1)
    assert r['empirical_slope_noise_scale_au'] == pytest.approx(1e-6)
    assert r['requires_completion_audit']


def test_negative_curvature_is_reported_and_not_certified():
    r = summarize([[1., 0., 0.]], samples(curvature=-.1), [0., 0.], 0.)
    assert r['richardson_gradient_curvature_au'] < 0
    assert r['energy_curvature_without_reference_energy_au'] < 0
    assert not r['minimum_certified']


def test_nonfinite_and_incompatible_shapes_rejected():
    with pytest.raises(ValueError, match='finite and normalized'):
        summarize([[np.nan, 0., 0.]], samples(), [0., 0.], 0.)
    bad = samples(); bad[0] = (*bad[0][:3], np.ones(3), bad[0][4])
    with pytest.raises(ValueError, match='gradient shape'):
        summarize([[1., 0., 0.]], bad, [0., 0.], 0.)
