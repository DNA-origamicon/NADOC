import pytest
from experiments.cpd_anti_additive.corrected_core_directional_check import directional_verdict

LIMITS = dict(absolute_slope_error_au=1e-6, relative_slope_error=.05,
              relative_step_halving_difference=.02)


def test_quadratic_centered_slopes_and_wrong_gradient():
    slope = .00015
    samples = [(h, slope*h+.4*h*h, -slope*h+.4*h*h) for h in (.005, .0025)]
    assert directional_verdict(slope, samples, LIMITS)['passed']
    assert not directional_verdict(2*slope, samples, LIMITS)['passed']


def test_requires_both_scales_and_rejects_unresolved_step_dependence():
    samples = [(.005, .00015*.005, -.00015*.005),
               (.0025, .00015*1.04*.0025, -.00015*1.04*.0025)]
    assert not directional_verdict(.00015, samples, LIMITS)['passed']
    with pytest.raises(ValueError, match='Two finite'):
        directional_verdict(.00015, samples[:1], LIMITS)
