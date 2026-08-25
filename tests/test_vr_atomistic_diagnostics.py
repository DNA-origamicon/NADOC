from scripts.vr_atomistic_diagnostics import _steamvr_counter_deltas


def test_steamvr_counter_deltas_report_only_the_active_interval() -> None:
    before = {
        "frame_presents": 100,
        "frame_submits": 98,
        "dropped_frames": 12,
        "dropped_frames_timed_out": 10,
        "reprojected_frames": 4,
        "timed_out": 3,
    }
    after = {
        "frame_presents": 370,
        "frame_submits": 368,
        "dropped_frames": 13,
        "dropped_frames_timed_out": 10,
        "reprojected_frames": 4,
        "timed_out": 3,
    }

    interval = _steamvr_counter_deltas(before, after)

    assert interval["frame_presents"] == 270
    assert interval["frame_submits"] == 270
    assert interval["dropped_frames"] == 1
    assert interval["dropped_frames_timed_out"] == 0
    assert interval["reprojected_frames"] == 0
    assert interval["timed_out"] == 0


def test_steamvr_counter_deltas_tolerate_runtime_counter_reset() -> None:
    interval = _steamvr_counter_deltas(
        {"frame_presents": 500, "dropped_frames": 8},
        {"frame_presents": 20, "dropped_frames": 0},
    )

    assert interval["frame_presents"] == 0
    assert interval["dropped_frames"] == 0
