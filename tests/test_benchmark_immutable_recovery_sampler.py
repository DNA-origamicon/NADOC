"""Bounded benchmark sampler controls; no HTTP server or recovery evaluation."""

from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest

from scripts import benchmark_immutable_recovery as benchmark


class Client:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.reads = 0
        self.baselines = 0
        self.first, self.third = Event(), Event()

    def get(self, path, *, headers):
        assert path == benchmark.baseline.REVISION_PATH and headers == {"X-NADOC-Doc": "probe"}
        if current_thread().name != "batch-light-http-probe":
            self.baselines += 1
            return SimpleNamespace(raise_for_status=lambda: None)
        self.reads += 1
        self.first.set()
        if self.reads == 3:
            self.third.set()

        def status():
            if self.fail:
                raise ValueError("Injected scalar read failure")

        return SimpleNamespace(raise_for_status=status)


@pytest.fixture
def watched_threads(monkeypatch):
    finished, threads = Event(), []

    class ObservedThread(Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)

        def run(self):
            try:
                super().run()
            finally:
                finished.set()

    monkeypatch.setattr(benchmark, "Thread", ObservedThread)
    yield finished, threads
    assert finished.is_set()
    assert len(threads) == 1 and not threads[0].is_alive()


def invoke(client, callback):
    return benchmark.concurrent_request(client, {"X-NADOC-Doc": "probe"}, callback,
                                        SimpleNamespace(records=[]))


def test_paced_reads_continue_until_operation_finishes_without_exhausting_capacity(watched_threads):
    client = Client()
    expected = object()

    def operation():
        assert client.third.wait(2)
        return expected

    response, metrics = invoke(client, operation)
    assert response is expected and client.baselines == 1
    coverage = metrics["scalar_read_coverage"]
    assert coverage["capacity"] == 256 and coverage["spacing_ms"] == 20
    assert 3 <= coverage["successful"] == len(metrics["revision_http_ms"]) < 256
    assert coverage["sampler_active_to_finish"] is True
    assert coverage["overlapping_operation_reads"] >= 3
    assert metrics["probe_interval"]["stop_reason"] == "operation_finished"
    assert metrics["probe_interval"]["end"] >= metrics["operation_interval"]["end"]
    assert coverage["last_observed_endpoint"] == coverage["last_successful_endpoint"]
    assert coverage["uncovered_tail_ms"] == max(0., metrics["operation_interval"]["end"]
        - coverage["last_successful_endpoint"]) * 1000
    assert not metrics["light_sample_cap_reached"] and not metrics["light_sample_cap_exhausted"]
    assert metrics["errors"] == []
    for phase in ("capture", "publication", "light_request"):
        for what in ("hold", "wait"):
            assert metrics[f"{phase}_lock_{what}_ms"] == []


def test_done_event_interrupts_spacing_after_first_probe(watched_threads):
    client = Client()

    def operation():
        assert client.first.wait(2)
        return "finished"

    response, metrics = invoke(client, operation)
    assert response == "finished"
    assert metrics["probe_interval"]["stop_reason"] == "operation_finished"
    assert metrics["scalar_read_coverage"]["sampler_active_to_finish"]
    assert not metrics["light_sample_cap_exhausted"]


def test_capacity_exhaustion_records_the_unobserved_operation_tail(monkeypatch, watched_threads):
    finished, _threads = watched_threads
    monkeypatch.setattr(benchmark, "SCALAR_READ_CAP", 3)
    monkeypatch.setattr(benchmark, "SCALAR_READ_SPACING_SECONDS", .001)
    client = Client()

    def operation():
        # Wait for actual sampler exit, not a timing assumption or a sleep.
        assert finished.wait(2)
        return "after cap"

    _response, metrics = invoke(client, operation)
    coverage = metrics["scalar_read_coverage"]
    assert client.reads == coverage["attempted"] == coverage["successful"] == 3
    assert metrics["light_sample_cap_reached"] and metrics["light_sample_cap_exhausted"]
    assert metrics["probe_interval"]["stop_reason"] == "capacity_exhausted"
    assert metrics["probe_interval"]["end"] < metrics["operation_interval"]["end"]
    assert not coverage["sampler_active_to_finish"]
    assert coverage["uncovered_tail_ms"] > 0


def test_read_error_is_retained_and_does_not_claim_continued_coverage(watched_threads):
    finished, _threads = watched_threads
    client = Client(fail=True)

    def operation():
        assert finished.wait(2)
        return "read failed"

    _response, metrics = invoke(client, operation)
    coverage = metrics["scalar_read_coverage"]
    assert metrics["errors"] == ["Injected scalar read failure"]
    assert metrics["revision_http_ms"] == []
    assert coverage["attempted"] == 1 and coverage["successful"] == 0
    assert coverage["last_observed_endpoint"] is not None and coverage["last_successful_endpoint"] is None
    assert coverage["uncovered_tail_ms"] == metrics["http_ms"]
    assert not coverage["sampler_active_to_finish"] and not metrics["light_sample_cap_exhausted"]
    assert metrics["probe_interval"]["stop_reason"] == "read_error"


def test_callback_exception_still_stops_and_joins_the_owned_sampler(watched_threads):
    client = Client()

    def operation():
        assert client.first.wait(2)
        raise RuntimeError("Injected operation failure")

    with pytest.raises(RuntimeError, match="Injected operation failure"):
        invoke(client, operation)
    finished, threads = watched_threads
    assert finished.is_set() and not threads[0].is_alive()
