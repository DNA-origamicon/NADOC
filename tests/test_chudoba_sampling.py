"""Diagnostic behavior for known mixing and nonmixing trace ensembles."""
import numpy as np
import pytest
from experiments.peg_chudoba.sampling_diagnostics import split_rhat


def test_stationary_and_separated_chains():
    x=np.random.default_rng(61).normal(size=(4,4000))
    assert split_rhat(x)['maximum']<1.01
    separated=x+np.arange(4)[:,None]*2
    assert split_rhat(separated)['maximum']>1.2


def test_folded_rhat_detects_scale_mismatch():
    x=np.random.default_rng(62).normal(size=(4,4000))*np.array([1,1,4,4])[:,None]
    result=split_rhat(x)
    assert result['rank_normalized']<1.01
    assert result['folded']>1.1


def test_constant_and_invalid_traces_are_not_converged():
    assert np.isinf(split_rhat(np.ones((3,100)))['maximum'])
    with pytest.raises(ValueError):split_rhat([[1,2,3],[4,5,6]])


def test_autocorrelation_against_ar1_reference():
    from scipy.signal import lfilter
    from experiments.peg_chudoba.analyze_chain import correlation_time
    noise=np.random.default_rng(63).normal(size=100000)
    values=lfilter([1],[1,-.8],noise)[1000:]
    assert correlation_time(values)==pytest.approx((1+.8)/(1-.8),rel=.15)
    antithetic=lfilter([1],[1,.8],noise)[1000:]
    assert correlation_time(antithetic)==pytest.approx(1.)
