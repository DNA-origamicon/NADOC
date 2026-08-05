"""Measurements beat tables, and a missing measurement says so rather than pretending.

The pure half of md_bench_probe — parsing NAMD's own benchmark line, the cache, and the
verdict wording. Running NAMD itself is exercised by experiments/exp52, not here.
"""
import json

import pytest

from backend.core.md_bench_probe import (
    ProbeResult,
    _parse_benchmark,
    _speedup,
    load_measurement,
    machine_key,
    resident_verdict,
    save_measurement,
)

NAMD_LOG = """\
Info: Benchmark time: 8 CPUs 0.00340638 s/step 50.7295 ns/day 0 MB memory
Info: Benchmark time: 8 CPUs 0.00176488 s/step 97.8949 ns/day 0 MB memory
"""


def pair(off_ns=50.7, on_ns=97.9, ok=True):
    return [ProbeResult("resident_off", False, 8, 3.4, off_ns, ok),
            ProbeResult("resident_on", True, 8, 1.77, on_ns, ok)]


class TestParse:
    def test_reads_namds_own_number_not_ours(self):
        ms, ns = _parse_benchmark(NAMD_LOG)
        assert ns == pytest.approx(97.8949)
        assert ms == pytest.approx(1.76488, rel=1e-3)

    def test_takes_the_LAST_benchmark_line(self):
        # NAMD prints one per cycle-block; the last has the most steps behind it.
        assert _parse_benchmark(NAMD_LOG)[1] == pytest.approx(97.8949)

    def test_converts_days_per_ns(self):
        log = "Benchmark time: 8 CPUs 0.5 s/step 0.25 days/ns 0 MB memory"
        assert _parse_benchmark(log)[1] == pytest.approx(4.0)

    def test_no_benchmark_line_is_none_not_zero(self):
        # Zero would silently read as "infinitely slow" and lose a comparison.
        assert _parse_benchmark("Info: nothing here") == (None, None)


class TestSpeedup:
    def test_ratio_is_on_over_off(self):
        assert _speedup(pair()) == pytest.approx(1.93, abs=0.01)

    def test_a_failed_arm_yields_no_ratio(self):
        assert _speedup(pair(ok=False)) is None

    def test_a_missing_arm_yields_no_ratio(self):
        assert _speedup([pair()[0]]) is None


class TestCache:
    def test_round_trips_a_measurement(self, tmp_path):
        key = machine_key("RTX 2080 SUPER", "/opt/NAMD_3.0.2p1_x/namd3", 8)
        save_measurement(tmp_path, key, 32_754, pair(), design_stem="2hb_1xT")
        got = load_measurement(tmp_path, key, 32_754)
        assert got["n_atoms"] == 32_754
        assert got["resident_speedup"] == pytest.approx(1.93, abs=0.01)

    def test_a_different_machine_does_not_answer_for_this_one(self, tmp_path):
        # The whole point: one machine's number must not be served as another's.
        save_measurement(tmp_path, machine_key("RTX 3080 Ti", "/opt/a/namd3", 16),
                         32_754, pair())
        assert load_measurement(tmp_path, machine_key("RTX 2080 SUPER", "/opt/a/namd3", 8),
                                32_754) is None

    def test_thread_count_is_part_of_the_machine(self, tmp_path):
        assert machine_key("g", "/o/b/namd3", 8) != machine_key("g", "/o/b/namd3", 16)

    def test_the_namd_build_is_part_of_the_machine(self, tmp_path):
        assert machine_key("g", "/o/NAMD_3.0.2/namd3", 8) != \
               machine_key("g", "/o/NAMD_3.0.2p1/namd3", 8)

    def test_a_comparable_size_is_reused(self, tmp_path):
        key = machine_key("g", "/o/b/namd3", 8)
        save_measurement(tmp_path, key, 32_754, pair())
        assert load_measurement(tmp_path, key, 40_000) is not None      # within the bucket

    def test_a_far_larger_system_is_not_answered_from_a_small_one(self, tmp_path):
        key = machine_key("g", "/o/b/namd3", 8)
        save_measurement(tmp_path, key, 32_754, pair())
        assert load_measurement(tmp_path, key, 3_000_000) is None

    def test_history_is_appended_not_overwritten(self, tmp_path):
        key = machine_key("g", "/o/b/namd3", 8)
        save_measurement(tmp_path, key, 32_754, pair())
        save_measurement(tmp_path, key, 900_000, pair(on_ns=200.0))
        data = json.loads((tmp_path / "md_bench_cache.json").read_text())
        assert len(data[key]) == 2

    def test_a_corrupt_cache_is_ignored_rather_than_fatal(self, tmp_path):
        (tmp_path / "md_bench_cache.json").write_text("{not json")
        assert load_measurement(tmp_path, "k", 1000) is None


class TestVerdict:
    def test_says_plainly_when_nothing_was_measured(self):
        v = resident_verdict(None)
        assert v["measured"] is False and v["faster"] is None
        assert "estimate" in v["detail"]

    def test_reports_the_measured_winner_and_the_factor(self):
        v = resident_verdict({"resident_speedup": 1.93, "n_atoms": 32_754})
        assert v["faster"] == "on" and v["speedup"] == 1.93
        assert "1.93x faster" in v["detail"]

    def test_reports_a_loss_as_a_loss(self):
        v = resident_verdict({"resident_speedup": 0.88, "n_atoms": 32_500})
        assert v["faster"] == "off"
        assert "slower" in v["detail"]

    def test_a_half_failed_measurement_does_not_pick_a_winner(self):
        v = resident_verdict({"resident_speedup": None, "n_atoms": 1})
        assert v["measured"] is True and v["faster"] is None
