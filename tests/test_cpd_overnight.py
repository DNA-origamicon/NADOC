from experiments.cpd_published_comparator.overnight_checks import (
    admit_block,
    estimate_block_seconds,
)


def test_budget_admission_reserves_analysis_time_and_adapts_to_recent_speed():
    assert not admit_block(600, [], 500)
    assert admit_block(721, [], 500)
    assert not admit_block(721, [700] * 6, 500)
    assert admit_block(500, [1000] + [300] * 6, 500)


def test_throughput_uses_wall_clock_from_native_log(tmp_path):
    p = tmp_path / "cpd/replica-1"
    p.mkdir(parents=True)
    (p / "run.log").write_text(
        "TIMING: 100 CPU: 5, 0.0001/step Wall: 6, 0.002/step, 86 ns/days\n"
    )
    assert estimate_block_seconds(tmp_path) == 530
