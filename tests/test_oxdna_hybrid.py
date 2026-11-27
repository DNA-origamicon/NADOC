"""Statistical and protocol oracles for the experimental hybrid sampler."""
import numpy as np
import pytest

from tools.oxdna_hybrid.analysis import diagnose, probability
from tools.oxdna_hybrid.bias import BiasSpec, deposit, evaluate
from tools.oxdna_hybrid.temperature import crossing, reweight


def test_well_tempered_hills_diminish_and_do_not_depend_on_walker_order():
    spec = BiasSpec()
    zero = np.zeros_like(spec.grid)
    first = deposit(spec, zero, [1., 4.], .1)
    second = deposit(spec, first, [1., 4.], .1)
    assert np.allclose(first, deposit(spec, zero, [4., 1.], .1))
    assert evaluate(spec, second-first, [1.])[0] < evaluate(spec, first, [1.])[0]
    # Adding duplicate walkers does not secretly double the hill budget.
    assert np.allclose(first, deposit(spec, zero, [1., 4., 1., 4.], .1))
    assert np.count_nonzero(zero) == 0


def test_positive_bias_is_removed_with_positive_beta_v():
    # True bound odds=4. Bias +ln(4) at bound cancels those odds, producing 50/50 samples.
    spec = BiasSpec()
    bias = spec.grid*np.log(4)
    data = np.zeros((200, 5))
    data[100:, 1:3] = 1
    data[100:, 3] = np.log(4)
    p, weights = probability(data, spec, bias, 1)
    assert p == pytest.approx(.8)
    assert weights.sum() == pytest.approx(1)


def test_trapped_samples_do_not_get_zero_uncertainty():
    spec = BiasSpec()
    data = np.zeros((100, 5))
    data[:, 1:3] = 6
    report = diagnose(data, spec, np.zeros_like(spec.grid), .1)
    assert report['conditional_ci95'] is None
    assert report['recorded_crossings'] == 0
    assert report['reasons_precision_not_certified']


def test_native_bias_energy_mismatch_is_fatal():
    spec = BiasSpec()
    data = np.zeros((100, 5))
    data[:, 3] = 1
    with pytest.raises(ValueError, match='bias mismatch'):
        diagnose(data, spec, np.zeros_like(spec.grid), .1)


def test_tabulated_interpolation_and_domain_checks():
    spec = BiasSpec()
    assert evaluate(spec, 2*spec.grid+3, [.123])[0] == pytest.approx(3.246)
    for value in [float('nan'), spec.maximum, spec.minimum-.1]:
        with pytest.raises(ValueError):
            evaluate(spec, spec.grid, [value])
    with pytest.raises(ValueError):
        BiasSpec(bias_factor=1)


def test_com_energy_double_counting_is_corrected():
    spec = BiasSpec(coordinate='com', minimum=0, maximum=7)
    data = np.zeros((100, 5))
    data[:, 1] = 1
    data[:, 3] = 2
    result = diagnose(data, spec, spec.grid, .1)
    assert result['bias_energy_max_error'] == pytest.approx(0)


def test_temperature_reweight_uses_target_hamiltonian_and_finite_size():
    spec = BiasSpec()
    temperatures = [60., 70., 80.]
    cvs, bound = np.array([0., 1.]), np.array([False, True])
    energies = np.zeros((3, 2))
    energies[0, 1] = -(60+273.15)/3000*np.log(4)
    energies[2, 1] = (80+273.15)/3000*np.log(4)
    curve, ess = reweight(energies, cvs, bound, temperatures, 70, spec, np.zeros_like(spec.grid))
    # Single-box bound odds 4,1,1/4 -> bulk yields via heterodimer mass action.
    expected = [2*r/(2*r+1+np.sqrt(4*r+1)) for r in (4., 1., .25)]
    assert np.allclose(curve, expected)
    assert ess[1] == pytest.approx(2)
    assert crossing([60, 70, 80], [.8, .5, .2]) == pytest.approx(70)
    assert crossing([60, 70, 80], [.9, .8, .7]) is None


def test_com_rounding_does_not_corrupt_native_energy_weights():
    spec = BiasSpec(coordinate='com', minimum=0, maximum=7)
    data = np.zeros((100, 5))
    data[:, 1] = 1.0000  # four-decimal printed coordinate
    data[:, 3] = 2 * 3 * 1.000049  # native energy retains the actual coordinate
    result = diagnose(data, spec, 3*spec.grid, .1)
    assert result['bias_energy_max_error'] <= result['bias_energy_rounding_bound']
