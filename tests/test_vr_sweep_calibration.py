"""Independent seeded stress regression through the real native smoother."""
import numpy as np
import pytest

from tools.vr_motion.sweep_calibration import (
    build_adapter, calibration_stroke, controller_tip_points, distances_to_polyline, evaluate, smooth_native,
)


@pytest.fixture(scope="module")
def smoother(tmp_path_factory):
    return build_adapter(tmp_path_factory.mktemp("native-sweep-calibration"))


def test_stroke_reproducibility_and_three_dimensional_noise():
    trace = calibration_stroke(seed=11)
    assert trace == calibration_stroke(seed=11)
    assert trace != calibration_stroke(seed=12)
    actual = np.asarray([s["hands"]["right"]["position"] for s in trace["samples"]])
    ideal = np.asarray(trace["provenance"]["ideal_points_m"])
    assert np.all(np.std(actual-ideal, axis=0) > .005)
    assert [e["pressed"] for e in trace["events"]] == [True, False]


@pytest.mark.parametrize("preset", ["variable_fast", "variable_deliberate"])
@pytest.mark.parametrize("shape", ["line", "s-curve", "arc"])
@pytest.mark.parametrize("seed", [8, 11, 15])
def test_unstable_profiles_remove_wandering_and_preserve_curve(smoother, preset, shape, seed):
    # Held-out seeds: defaults were selected using seeds 0..3. Bounds cover
    # intentional overshoot/correction as well as noise; no targets are snapped.
    result = evaluate(smoother, calibration_stroke(shape, preset, seed))
    assert result["accepted"]
    assert 2 <= result["point_count"] <= 16
    assert .65 <= result["length_ratio"] <= 1.5
    assert result["smoothed_length_nm"] < result["raw_length_nm"]*.7
    assert result["rms_error_nm"] < 3.6
    assert result["maximum_missing_curve_nm"] < 5.


def test_physical_smoothing_is_consistent_across_zoom(smoother):
    trace = calibration_stroke("s-curve", "variable_deliberate", 11)
    positions = controller_tip_points(trace)
    previous = None
    for scale in [50., 100., 200.]:
        knots, path = smooth_native(smoother, positions*scale, .036*scale, .015*scale, .0015*scale)
        path /= scale
        assert 2 <= len(knots) <= 16
        if previous is not None:
            assert distances_to_polyline(path, previous).max() < .001
        previous = path


def test_spatial_oracle_detects_collapsed_three_dimensional_curve():
    trace = calibration_stroke("arc", "steady_fast", 0)
    ideal = np.asarray(trace["provenance"]["ideal_points_m"])
    assert distances_to_polyline(ideal, ideal[[0, -1]]).max() > .1
