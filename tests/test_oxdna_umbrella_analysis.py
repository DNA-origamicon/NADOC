"""Analytic statistical checks for experimental fixed-window umbrella analysis."""
import numpy as np
import pytest
from tools.oxdna_umbrella.analysis import solve,tabulated_bias,bulk_yield,statistical_inefficiency
from tools.oxdna_umbrella.native import restraint


def test_unbinned_wham_recovers_known_harmonic_ensemble():
    rng=np.random.default_rng(917)
    centers=np.linspace(-2,2,5);k=2.;counts=[1000]*5
    # U0=x²/2, Bi=k(x-ci)²/2: exact biased ensembles are Gaussian.
    x=np.concatenate([rng.normal(k*c/(1+k),1/np.sqrt(1+k),n) for c,n in zip(centers,counts)])
    bias=.5*k*(x[None,:]-centers[:,None])**2
    w,overlap,_,_=solve(bias,counts,1.)
    assert w.sum()==pytest.approx(1.)
    assert w@x==pytest.approx(0.,abs=.06)
    assert w@(x*x)==pytest.approx(1.,abs=.08)
    assert overlap.sum(axis=1)==pytest.approx(np.ones(5),abs=2e-6)
    shifted=solve(bias+np.arange(5)[:,None]*3,counts,1.)[0]
    assert shifted==pytest.approx(w,abs=1e-8)


def test_native_tabulated_bias_and_two_sided_force_contract():
    # A half-cell evaluation is the exact linear interpolation, not a second spring.
    value=tabulated_bias([1.0025],[1.],2.)[0,0]
    assert value==pytest.approx(.5*.005**2)
    text=restraint([0,1],[2,3],1.,2.,7.)
    assert text.count('type = meta_com_trap')==2
    assert 'mode = 1' in text and 'mode = 2' in text
    assert text.count('PBC = true')==2
    with pytest.raises(ValueError):tabulated_bias([7.],[1.],2.)


def test_bulk_correction_and_time_correlation():
    assert bulk_yield(2/3)==pytest.approx(.5)
    assert bulk_yield(0.)==0
    assert bulk_yield(1.)==1
    rng=np.random.default_rng(56);noise=rng.normal(size=2000)
    assert statistical_inefficiency(noise)<2
    assert statistical_inefficiency(np.repeat(noise[:100],20))>10


def test_normal_native_exit_does_not_certify_partial_stage(tmp_path):
    from tools.oxdna_umbrella.native import execute
    # A truncated native checkpoint header is sufficient to exercise this gate;
    # this fixture contains no molecular coordinates.
    binary=tmp_path/'fake_native'
    binary.write_text('#!/bin/sh\nprintf "t = 5\\n" > last_conf.dat\nprintf "END OF THE SIMULATION\\n"\n')
    binary.chmod(0o755)
    with pytest.raises(ValueError,match='Incomplete native stage: 5/100'):
        execute(binary,tmp_path/'attempt','steps = 100\n')
