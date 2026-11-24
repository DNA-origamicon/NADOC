"""Private preview workers preserve geometry and release killed allocations."""

import gzip
import json
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path

import pytest

from backend.api import corner_projection_worker as worker
from backend.api.corner_preview_projection import project_corner_preview
from backend.core.corner_seam_cache import clear_fit_cache, export_fits
from backend.core.models import Design


@pytest.fixture
def source():
    with gzip.open(Path(__file__).parents[1] / 'frontend/src/ui/geometry_review_data/corner-closure.json.gz', 'rt') as stream:
        return Design.model_validate(json.load(stream)['controls']['hc2']['candidate_design'])


@pytest.mark.slow
def test_worker_projection_and_exact_cache_match_local_provider(source):
    clear_fit_cache()
    before = source.model_dump_json()
    progress = []
    result = worker.project_corner_in_worker(source, on_progress=lambda done, total: progress.append((done, total)))
    assert export_fits()
    from backend.core.atomistic_cache import clear_atomistic_cache
    clear_fit_cache()
    clear_atomistic_cache()
    # Compare the independently calculated wire representation, including the
    # usual JSON tuple-to-array conversion, without reusing the worker's fits.
    assert result == json.loads(json.dumps(project_corner_preview(source)))
    assert source.model_dump_json() == before
    completed = [done/total for done, total in progress if total]
    assert completed == sorted(completed) and completed[-1] == 1


@pytest.mark.slow
def test_cancel_during_fit_reaps_process_and_shared_memory(source, monkeypatch):
    clear_fit_cache()
    created, names = [], []
    original = worker.CornerProjectionWorker

    def capture(design):
        value = original(design)
        created.append(value)
        names.extend(buffer.name for buffer in value._buffers)
        return value

    class Cancelled(Exception):
        pass

    def stop(done, total):
        if done:
            raise Cancelled()

    monkeypatch.setattr(worker, 'CornerProjectionWorker', capture)
    with pytest.raises(Cancelled):
        worker.project_corner_in_worker(source, on_progress=stop)
    assert len(created) == 1 and not created[0].is_alive()
    for name in names:
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=name)
