"""Synthetic statistical curves and persisted restart segments, no MD sampling."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core.oxdna_energy_fit import fit_energy
from backend.core.oxdna_thermal_metrics import energy_history, energy_metrics, read_metrics


@pytest.mark.parametrize('sign',[-1,1])
def test_complete_exponential_reports_location_and_remaining_change(sign):
    t=np.linspace(0,100,1001);y=-1.4+sign*.4*np.exp(-t/10)
    r=fit_energy(t,y)
    assert r['passed'] and r['model']=='exponential'
    assert r['tau']==pytest.approx(10,rel=.01)
    assert r['elapsed_tau']==pytest.approx(10,rel=.01)
    assert r['asymptote']==pytest.approx(-1.4,abs=1e-4)
    assert r['samples']==1001 and r['fraction_remaining']<.001


def test_early_exponential_and_linear_drift_do_not_pass():
    t=np.linspace(0,10,501)
    assert not fit_energy(t,-1+.5*np.exp(-t/20))['passed']
    assert not fit_energy(t,-1+.1*t)['passed']


def test_flat_noise_is_identified_without_fabricating_decay_time():
    rng=np.random.default_rng(4);t=np.arange(2000.)
    r=fit_energy(t,-1+rng.normal(0,.005,len(t)))
    assert r['passed'] and r['model']=='constant' and r['tau'] is None


def test_late_transition_and_nonfinite_data_cannot_pass():
    t=np.arange(1000.)
    y=-1+.5*np.exp(-t/30);y[-100:]+=.2
    assert not fit_energy(t,y)['passed']
    y[2]=float('nan')
    assert not fit_energy(t,y)['passed']


def test_full_history_retains_transient_that_tail_only_would_hide():
    t=np.linspace(0,100,1001);y=-1+.5*np.exp(-t/20)
    r=fit_energy(t,y)
    assert r['samples']==1001
    assert r['amplitude']==pytest.approx(.5,rel=.01)
    assert r['tau']==pytest.approx(20,rel=.01)


def test_restart_segments_keep_raw_boundaries_and_receipt_time_gaps(tmp_path):
    (tmp_path/'energy.r1.dat').write_text('0 -1 .3 -.7\n1 -.9 .3 -.6\n')
    (tmp_path/'energy.dat').write_text('0 -.8\n1 -.7\n')
    (tmp_path/'input.txt').write_text('seed = 77\ndt = 0.1\n')
    (tmp_path/'thermal_attempt_20_retry0.json').write_text(json.dumps({'seed':77,'banked_steps':20}))
    c=energy_history(tmp_path)
    assert c['points'][0][-2:]==[.3,-.7]
    assert c['fit_times']==[0,1,2,3]
    assert len(c['points'])==4
    (tmp_path/'thermal_attempt_20_retry0.json').write_text(json.dumps({'seed':77,'banked_steps':10}))
    c=energy_history(tmp_path)
    assert c['fit_times']==[0,1,2] and len(c['points'])==4


def test_persisted_metrics_are_display_ready_and_read_without_refitting(tmp_path):
    d=tmp_path/'1_thermal';d.mkdir()
    t=np.linspace(0,100,301)
    (d/'energy.dat').write_text('\n'.join(f'{a} {-1+.5*np.exp(-a/10)}' for a in t))
    cfg=SimpleNamespace(energy_tolerance=.02,min_effective_samples=10)
    fit,c=energy_metrics(d,cfg,evaluated_steps=1000000)
    assert len(c['points'])==len(c['fitted_energy'])==301 and fit['passed']
    j=SimpleNamespace(job_id='test',job_dir=lambda _:tmp_path,stages=[SimpleNamespace(name='1_thermal')],
                      run_config={'thermal_progress':{'1_thermal':{'temperature':'298K','decision':'done'}}})
    result=read_metrics(j,tmp_path)
    assert result['stages'][0]['energy_curve']['fit']==fit
    assert result['stages'][0]['decision']['decision']=='done'
    (d/'energy.dat').write_text('0 nan\n')
    assert not energy_metrics(d,cfg)[0]['passed']


def test_noisy_relaxation_passes_without_requiring_constant_energy():
    rng=np.random.default_rng(18);t=np.linspace(0,100,1001)
    y=-1+.5*np.exp(-t/10)+rng.normal(0,.01,len(t))
    result=fit_energy(t,y)
    assert result['passed'] and result['model']=='exponential'
    assert result['remaining_change_upper_95'] < .02


def test_history_is_not_truncated_at_old_3000_sample_limit(tmp_path):
    t=np.arange(4001.)
    (tmp_path/'energy.r1.dat').write_text('\n'.join(f'{i} {-1+.5*np.exp(-i/100)}' for i in t))
    (tmp_path/'energy.dat').write_text('0 -1\n1 -1\n')
    cfg=SimpleNamespace(energy_tolerance=.02,min_effective_samples=10)
    fit,curve=energy_metrics(tmp_path,cfg)
    assert fit['samples']==4002 and len(curve['points'])==4003
    assert fit['amplitude']==pytest.approx(.5,rel=.001)
