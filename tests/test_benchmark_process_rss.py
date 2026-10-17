"""Measurement-only checks: no simulations, process spawning or bulk artifacts."""

from threading import Event

import pytest

from scripts import benchmark_process_rss as rss


def stat_record(pid=42, *, name=b"worker ) with spaces", parent=7, birth=123, pages=9):
    fields = [b"S"] + [b"0"] * 21
    fields[1], fields[19], fields[21] = str(parent).encode(), str(birth).encode(), str(pages).encode()
    return str(pid).encode() + b" (" + name + b") " + b" ".join(fields)


def test_reads_bounded_stat_with_spaced_parenthesized_name_and_explicit_page_units(tmp_path):
    directory = tmp_path / "42"
    directory.mkdir()
    (directory / "stat").write_bytes(stat_record())
    assert rss.read_process_rss(42, proc_root=tmp_path, page_bytes=4096) == rss.ProcessRSS(42, 7, 123, 9 * 4096)


@pytest.mark.parametrize("raw", [b"", b"4 (wrong) S", stat_record(43), b"x" * 4097,
    stat_record(pages=-1), stat_record(birth=-1)])
def test_invalid_or_oversized_stat_fails_instead_of_claiming_zero_rss(tmp_path, raw):
    directory = tmp_path / "42"
    directory.mkdir()
    (directory / "stat").write_bytes(raw)
    with pytest.raises(ValueError):
        rss.read_process_rss(42, proc_root=tmp_path)


def sampler(values, **kwargs):
    def reader(pid):
        item = values.get(pid)
        if item is None:
            raise FileNotFoundError
        return item
    probe = rss.ProcessRSSSampler(parent_pid=7, reader=reader, **kwargs)
    probe._started = True
    probe._sample()
    return probe


def test_combined_peak_is_same_sample_not_sum_of_independent_maxima():
    values = {7: rss.ProcessRSS(7, 1, 50, 100), 42: rss.ProcessRSS(42, 7, 60, 50)}
    probe = sampler(values)
    assert probe.register_child(42)
    values[7] = rss.ProcessRSS(7, 1, 50, 200)
    values.pop(42)
    probe.set_phase("commit")
    probe._sample()
    result = probe.report()
    assert result["baseline_parent_bytes"] == 100
    assert result["peak_parent_bytes"] == 200 and result["peak_owned_children_bytes"] == 50
    assert result["peak_combined_bytes"] == 200 and result["increase_over_idle_bytes"] == 100
    assert result["measurement_complete"] and result["observed_within_allowance"]
    assert result["phases"]["commit"]["peak_combined_bytes"] == 200


def test_only_explicit_direct_children_count_and_recycled_pid_is_not_trusted():
    values = {7: rss.ProcessRSS(7, 1, 50, 100), 42: rss.ProcessRSS(42, 7, 60, 50),
              43: rss.ProcessRSS(43, 42, 70, 10**10), 99: rss.ProcessRSS(99, 7, 80, 10**10)}
    probe = sampler(values)
    assert probe.register_child(42)
    assert probe.report()["peak_combined_bytes"] == 150  # Unregistered sibling is excluded.
    assert not probe.register_child(43)
    values[42] = rss.ProcessRSS(42, 7, 61, 10**10)
    probe._sample()
    result = probe.report()
    assert result["peak_combined_bytes"] == 150
    assert result["errors"] == {"child_not_owned": 1, "child_identity_changed": 1}
    assert not result["measurement_complete"] and result["observed_within_allowance"] is None


def test_sampling_cap_and_child_registration_failures_are_visible():
    values = {7: rss.ProcessRSS(7, 1, 50, 100), 42: rss.ProcessRSS(42, 7, 60, 50),
              43: rss.ProcessRSS(43, 7, 61, 10)}
    probe = sampler(values, max_samples=2, max_children=1)
    assert not probe.register_child(999)
    assert probe.register_child(42)
    assert not probe.register_child(43)
    probe._sample()
    result = probe.report()
    assert result["sample_count"] == 2 and result["sample_limit_reached"]
    assert result["errors"] == {"child_registration_unavailable": 1, "child_limit": 1}
    assert result["observed_within_allowance"] is None


def test_rss_increment_above_existing_allowance_reports_false():
    values = {7: rss.ProcessRSS(7, 1, 50, 100),
              42: rss.ProcessRSS(42, 7, 60, rss.INCREMENT_ALLOWANCE_BYTES + 1)}
    probe = sampler(values)
    probe.register_child(42)
    assert probe.report()["observed_within_allowance"] is False


def test_actual_gaps_are_reported_without_subtracting_gc_or_scheduling_delays():
    times = iter([1., 1.001, 1.08, 1.082])
    values = {7: rss.ProcessRSS(7, 1, 50, 100)}
    probe = sampler(values, clock=lambda: next(times))
    probe._sample()
    result = probe.report()
    assert result["requested_interval_ms"] == 5
    assert result["max_sample_gap_ms"] == pytest.approx(80)
    assert result["max_sample_duration_ms"] == pytest.approx(2)


def test_context_stops_sampler_after_failure_and_cannot_be_reused():
    sampled = Event()
    def reader(pid):
        sampled.set()
        return rss.ProcessRSS(pid, 1, 50, 100)
    probe = rss.ProcessRSSSampler(parent_pid=7, reader=reader)
    with pytest.raises(RuntimeError, match="injected"):
        with probe:
            assert sampled.wait(.5)
            raise RuntimeError("injected")
    assert probe.report()["sampler_stopped"]
    with pytest.raises(RuntimeError, match="twice"):
        probe.__enter__()
    with pytest.raises(RuntimeError, match="not active"):
        probe.register_child(42)


@pytest.mark.parametrize("kwargs", [{"interval_seconds": True}, {"interval_seconds": 0},
    {"interval_seconds": float("nan")}, {"max_samples": True}, {"max_samples": 100_001},
    {"max_children": 0}, {"parent_pid": True}])
def test_sampler_limits_are_fixed_and_bounded(kwargs):
    with pytest.raises(ValueError):
        rss.ProcessRSSSampler(**kwargs)
