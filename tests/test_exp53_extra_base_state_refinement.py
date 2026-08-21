import numpy as np

from experiments.exp53_extra_base_state_refinement.analyse import (
    adjusted_rand,
    robust_features,
    samples_for_insert,
    stable_windows,
    valid_sample,
)


CFG = {
    "global_paired_min": 0.9,
    "local_bp_min_A": 8.0,
    "local_bp_max_A": 13.0,
    "bond_min_A": 1.2,
    "bond_max_A": 2.2,
    "pose_rmsd_max_A": 1.5,
}


def good_sample():
    return {
        "bp_src": 10.5,
        "bp_dst": 10.5,
        "bond_src": 1.6,
        "bond_dst": 1.6,
        "pose_rmsd": 0.5,
    }


def test_integrity_filter_reports_each_failed_metric():
    ok, why = valid_sample(good_sample(), 0.95, CFG)
    assert ok and why == []
    bad = good_sample() | {"bond_dst": 4.0, "pose_rmsd": 2.0}
    ok, why = valid_sample(bad, 0.5, CFG)
    assert not ok
    assert set(why) == {"global_pairing", "destination_bond", "pose_fit"}


def test_stable_windows_are_contiguous_and_minimum_sized():
    mask = [False, True, True, False, True, True, True, False]
    assert stable_windows(mask, 3) == [(4, 7)]


def test_robust_features_drop_missing_panel_metrics_and_scale_outlier_resistant():
    samples = [{"x": x, "missing": np.nan} for x in (0.0, 1.0, 2.0, 100.0)]
    X, keys = robust_features(samples, ("x", "missing"))
    assert keys == ["x"] and X.shape == (4, 1)
    assert np.isfinite(X).all()
    empty, keys = robust_features([], ("x",))
    assert empty.shape == (0, 0) and keys == []


def test_adjusted_rand_is_label_permutation_invariant():
    assert adjusted_rand([0, 0, 1, 1], [1, 1, 0, 0]) == 1.0
    assert adjusted_rand([0, 0, 1, 1], [0, 1, 0, 1]) < 0.0


def test_historical_multi_insert_dump_is_deinterleaved():
    shared = [{"v": 0}, {"v": 1}, {"v": 2}, {"v": 3}]
    inserts = [
        {"crossover_id": "x", "k": 0, "samples": shared},
        {"crossover_id": "x", "k": 1, "samples": shared},
    ]
    data = {"paired_fraction": [1.0, 1.0], "inserts": inserts}
    assert [s["v"] for s in samples_for_insert(data, inserts[0])] == [0, 2]
    assert [s["v"] for s in samples_for_insert(data, inserts[1])] == [1, 3]
