"""Real tiny spawned display transport, with no molecular solver or disk output."""

from multiprocessing.shared_memory import SharedMemory

import pytest

from backend.api.part_comparison_worker import ComparisonWorker
from backend.api import part_verification_worker as transport
from backend.core.part_comparison_projection import compare
from tests.test_part_comparison_projection import asset_part


def test_tiny_spawned_comparison_matches_native_projection_and_releases_shared_memory():
    source = asset_part()
    candidate = source.model_copy(deep=True)
    candidate.nanoparticles[0].diameter_nm = 12.
    data = candidate.model_dump(mode="json")
    worker = ComparisonWorker(source, data)
    names = [buffer.name for buffer in worker._buffers]
    try:
        worker.start()
        assert worker.wait(15), "Tiny display projection did not complete"
        result = worker.result()
        assert result == compare(source, data)
    finally:
        worker.close()
    assert not worker.is_alive()
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)


def test_combined_two_pane_input_is_bounded_before_allocating_or_starting_a_process(monkeypatch):
    source = asset_part()
    monkeypatch.setattr(transport, "MAX_INPUT_BYTES", 64)
    monkeypatch.setattr(transport, "SharedMemory", lambda **_: pytest.fail("Oversized input allocated a buffer"))
    with pytest.raises(transport.WorkerLimit):
        ComparisonWorker(source, source.model_dump(mode="json"))


def test_result_budget_returns_diagnostic_instead_of_a_partial_pane():
    source = asset_part()
    result = compare(source, source.model_dump(mode="json"))
    import json
    assert json.loads(transport._result_bytes(result, limit=128)) == transport.failure("result_limit")
