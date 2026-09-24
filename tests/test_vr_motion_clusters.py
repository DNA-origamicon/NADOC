import numpy as np
import pytest
from tools.vr_motion.cluster import features, fit


def recording(n=400):
    frames = np.zeros((n, 4)); frames[:, 0] = np.arange(n); frames[:, 3] = 1/30
    hand = np.zeros((n, 8)); hand[:, 0] = 1
    head = hand.copy()
    t = np.arange(n)/30
    hand[:, 1] = .1*np.cos(t); hand[:, 2] = .1*np.sin(t)
    return frames, hand, head


def test_features_remove_shared_locomotion_and_reject_bad_tracking():
    f, h, head = recording()
    quality, base = features(f, h, head)
    assert quality['eligible'] and .09 < base['speed_median_m_s'] < .11
    h[200:, 1:4] += 10; head[200:, 1:4] += 10
    _, moved = features(f, h, head)
    assert np.isclose(moved['speed_median_m_s'], base['speed_median_m_s'])
    h[200:, 1] += 10
    quality, _ = features(f, h, head)
    assert quality['jump_fraction'] > 0
    h[:100, 0] = 0
    quality, _ = features(f, h, head)
    assert not quality['eligible']


def test_bad_timing_excluded_and_no_gap_acceleration():
    f, h, head = recording()
    f[10:100, 3] = np.nan
    quality, metrics = features(f, h, head)
    assert not quality['eligible'] and quality['bad_timing_fraction'] > .2
    assert all(np.isfinite(x) for x in metrics.values())


def test_cluster_deterministic_and_exclusions_have_no_label():
    pytest.importorskip("sklearn")
    from tools.vr_motion.cluster import FEATURES
    rng = np.random.default_rng(4)
    rows = [{'id': str(i), 'task': 'same_task', 'hand': 'right',
             'quality': {'eligible': i != 0},
             'features': dict(zip(FEATURES, (rng.random(5)+i%3*3).tolist())), 'cluster': None}
            for i in range(40)]
    a = fit(rows, 3); labels = [r['cluster'] for r in rows]
    b = fit(rows, 3)
    assert a == b and labels == [r['cluster'] for r in rows]
    assert rows[0]['cluster'] is None and a['excluded'] == 1
