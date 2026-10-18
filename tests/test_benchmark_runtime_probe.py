"""The optional diagnostic observes bounded intervals without changing GC policy."""

import gc

import pytest

from scripts import benchmark_runtime_probe as runtime


def test_probe_clips_intervals_and_reports_dropped_events_without_collection(monkeypatch):
    times = iter([1., 3., 4., 5., 6., 7.])
    monkeypatch.setattr(runtime, "perf_counter", lambda: next(times))
    probe = runtime.RuntimeProbe(phase=lambda: "pending_native", max_events=2)
    policy = (gc.isenabled(), gc.get_threshold())
    for generation in (0, 1, 2):
        probe._record("start", {"generation": generation})
        probe._record("stop", {"generation": generation})
    assert len(probe.events) == 2 and probe.dropped_events == 1
    assert [item["generation"] for item in probe.events] == [0, 1]
    assert all(item["phase"] == "pending_native" for item in probe.events)
    assert runtime.overlap_ms(probe.intervals(2., 4.5), 2., 4.5) == 1500.
    assert set(probe.events[0]) == {"start", "end", "thread", "phase", "generation"}
    assert (gc.isenabled(), gc.get_threshold()) == policy


def test_probe_restores_only_its_callback_after_failure(monkeypatch):
    sentinel = lambda *_args: None
    callbacks = [sentinel]
    monkeypatch.setattr(gc, "callbacks", callbacks)
    probe = runtime.RuntimeProbe()
    with pytest.raises(RuntimeError, match="injected"):
        with probe:
            assert callbacks == [sentinel, probe._callback]
            with pytest.raises(RuntimeError, match="already installed"):
                probe.__enter__()
            raise RuntimeError("injected")
    assert callbacks == [sentinel]


@pytest.mark.parametrize("limit", [True, 0, -1, 100_001])
def test_probe_rejects_unbounded_or_noninteger_capacity(limit):
    with pytest.raises(ValueError):
        runtime.RuntimeProbe(max_events=limit)
