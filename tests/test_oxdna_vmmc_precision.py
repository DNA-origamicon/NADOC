"""Statistical oracles, independent of native simulation execution."""
import numpy as np
import pytest

from backend.core.oxdna_vmmc_precision import (
    histogram_blocks, precision_report, tm_of, yield_curve,
)
from tools.oxdna_vmmc.train_weights import flat_weights


def artificial_replicas(centers, samples=4000, correlated=1, seed=41):
    rng = np.random.default_rng(seed)
    ts = np.linspace(60, 80, 41)
    arrays = []
    for center in centers:
        # Known binding ratio 2 exp[-0.25 (T-Tm)], with multiplicative noise.
        # The same random contribution reweights coherently at every T.
        draws = rng.lognormal(-.5*.4**2, .4, (samples//correlated, 2))
        draws = np.repeat(draws, correlated, axis=0)
        arrays.append(np.stack((draws[:, 0, None]*np.ones_like(ts),
                                draws[:, 1, None]*2*np.exp(-.25*(ts-center))), axis=1))
    return arrays, ts


def test_analytic_melting_and_interval_recovers_known_transition():
    arrays, ts = artificial_replicas([70]*4)
    report = precision_report(arrays, ts, bootstrap=200)
    assert report['ci95_c'][0] < 70 < report['ci95_c'][1]
    assert report['halfwidth_c'] < .3
    assert report['status'] == 'target_met'
    assert tm_of(np.array([[1, 1, 1], [8, 2, .5]]), [60, 70, 80]) == 70
    assert yield_curve(np.array([[0., 1.], [1., 0.]])).tolist() == [1., 0.]


def test_correlation_widens_uncertainty_and_opposite_starts_block_acceptance():
    independent, ts = artificial_replicas([70]*4)
    correlated, _ = artificial_replicas([70]*4, correlated=10)
    fast = precision_report(independent, ts, bootstrap=100)
    slow = precision_report(correlated, ts, bootstrap=100)
    assert slow['halfwidth_c'] > fast['halfwidth_c']
    disagree, _ = artificial_replicas([71, 69, 71, 69])
    report = precision_report(disagree, ts, bootstrap=100)
    assert report['status'] == 'inconclusive'
    assert any('starts' in r or 'start' in r for r in report['reasons'])


def test_unbracketed_or_short_series_cannot_claim_precision():
    arrays, ts = artificial_replicas([90]*4)
    assert precision_report(arrays, ts, bootstrap=100)['ci95_c'] is None
    arrays, ts = artificial_replicas([70]*4, samples=30)
    assert precision_report(arrays, ts, bootstrap=100)['status'] == 'inconclusive'


def test_cumulative_native_histograms_are_differenced_not_resampled_as_independent(tmp_path):
    path = tmp_path/'hist.dat'
    path.write_text('#t = 0; extr. Ts: 0.114383\n0 0 0 0\n1 0 0 0\n'
                    '#t = 10; extr. Ts: 0.114383\n0 10 10 10\n1 20 20 20\n'
                    '#t = 20; extr. Ts: 0.114383\n0 15 15 15\n1 30 30 30\n')
    blocks, interval = histogram_blocks(path, 1, [70])
    assert interval == 10
    np.testing.assert_allclose(blocks[:, :, 0], [[10, 20], [5, 10]])
    path.write_text(path.read_text().replace('0 15 15 15', '0 1 1 1'))
    with pytest.raises(ValueError, match='decreased'):
        histogram_blocks(path, 1, [70])


def test_prior_histogram_weights_flatten_expected_occupancy_without_changing_target():
    physical = np.array([.3, .001, .099, .6])
    old = np.array([.01, 1, .03, .001])
    biased_counts = 1e8*physical*old
    new = flat_weights(old, biased_counts)
    np.testing.assert_allclose(physical*new, np.full(4, (physical*new)[0]))
    recovered = (physical*new)/new
    np.testing.assert_allclose(recovered/recovered.sum(), physical)
    with pytest.raises(ValueError, match='positive'):
        flat_weights(old, [0, 1, 2, 3])
