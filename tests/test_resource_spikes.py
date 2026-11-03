import pytest
from backend.core.resource_spikes import summarize_series, summarize_startup


def test_short_spike_duration_uses_time_not_sample_count():
    r=summarize_series([(0,100),(10,200),(10.1,100),(30,100)],warmup_s=0)
    assert r['median_mib']==100 and r['episode_count']==1
    assert r['mean_mib']==pytest.approx((10*100 + .1*200 + 19.9*100)/30)
    assert r['episodes'][0]['duration_s']==pytest.approx(.1)
    assert not r['episodes'][0]['right_censored']


def test_capacity_growth_is_censored_not_reported_as_completed_spike():
    r=summarize_series([(0,100),(25,200),(30,200)],warmup_s=0)
    assert r['episodes'][0]['right_censored']


def test_startup_separate_and_missing_time_not_invented():
    r=summarize_series([(0,1000),(3,100),(10,100)],warmup_s=5)
    assert r['startup_peak_mib']==1000 and r['peak_mib']==100
    assert r['mean_mib']==100
    assert r['episode_count']==0
    with pytest.raises(ValueError):summarize_series([(0,1),(1,1)])


def test_startup_ramp_to_plateau_is_not_a_transient_spike():
    r=summarize_startup([(0,0),(1,200),(2,1000),(9,1000),(10,0)],
        startup_end_s=2,running_start_s=3,running_end_s=9)
    assert r['classification']=='no_distinct_startup_overshoot'
    assert r['startup_extra_above_running_peak_mib']==0
    assert r['running_median_mib']==1000


def test_startup_overshoot_and_later_growth_are_distinct():
    r=summarize_startup([(0,0),(1,1200),(2,800),(10,800)],
        startup_end_s=2,running_start_s=3,running_end_s=9)
    assert r['classification']=='startup_overshoot'
    assert r['startup_extra_above_running_peak_mib']==400
    r=summarize_startup([(0,0),(1,800),(4,1200),(10,1200)],
        startup_end_s=2,running_start_s=4,running_end_s=9)
    assert r['classification']=='continued_growth'


def test_startup_requires_observed_running_window_and_uses_time_weights():
    samples=[(0,1000),(1,1000),(4,800),(4.001,1200),(4.002,800),(10,800)]
    r=summarize_startup(samples,startup_end_s=2,running_start_s=4,running_end_s=9)
    assert r['running_median_mib']==800
    # A later running peak also requires capacity, even if very brief.
    assert r['running_peak_mib']==1200
    assert r['startup_extra_above_running_peak_mib']==0
    with pytest.raises(ValueError):
        summarize_startup(samples,startup_end_s=2,running_start_s=4,running_end_s=11)
