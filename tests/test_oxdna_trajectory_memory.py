"""Memory admission and seek-index regression checks; no real simulation runs."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException


def test_memory_limit_rejects_before_reconstruction(monkeypatch):
    import psutil
    import backend.api.routes_oxdna as routes
    import backend.core.oxdna_health as health
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=2 * 1024**3))
    monkeypatch.setattr(health, 'composite_trajectory_meta', lambda *a: {'n_frames': 10000, 'n_nucleotides': 30000})
    calls = []
    def pack_composite_trajectory_bin(design, stages, max_frames=0, frame_start=None, frame_end=None):
        calls.append(True)
        return 'ok'
    with pytest.raises(HTTPException) as error:
        routes._trajectory_work(pack_composite_trajectory_bin, None, [])
    assert error.value.status_code == 413
    assert not calls
    assert routes._trajectory_work(pack_composite_trajectory_bin, None, [], frame_start=0, frame_end=7) == 'ok'
    assert routes._TRAJECTORY_RESERVED_BYTES == 0
    # Simultaneous requests count against the shared allowance.
    monkeypatch.setattr(routes, '_TRAJECTORY_RESERVED_BYTES', 500 * 1024**2)
    with pytest.raises(HTTPException):
        routes._trajectory_work(pack_composite_trajectory_bin, None, [], frame_start=0, frame_end=7)


def test_memory_reservation_released_on_failure(monkeypatch):
    import psutil
    import backend.api.routes_oxdna as routes
    import backend.core.oxdna_health as health
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=2 * 1024**3))
    monkeypatch.setattr(health, 'composite_trajectory_meta', lambda *a: {'n_frames': 1, 'n_nucleotides': 10})
    def broken(design, stages):
        raise ValueError('cancelled')
    with pytest.raises(ValueError, match='cancelled'):
        routes._trajectory_work(broken, None, [])
    assert routes._TRAJECTORY_RESERVED_BYTES == 0


def test_seek_index_handles_chunk_boundary_append_and_rewrite(tmp_path):
    from backend.core.oxdna_frame_index import trajectory_offsets
    p = tmp_path / 'trajectory.dat'
    data = b't = 0\n' + b'0' * (1024 * 1024 - 8) + b'\nt = 1\n'
    p.write_bytes(data)
    first = trajectory_offsets(p)
    assert list(first) == [0, data.index(b't = 1')]
    assert trajectory_offsets(p) is first
    with p.open('ab') as f:
        f.write(b'0 0 0\nt = 2\n')
    assert len(trajectory_offsets(p)) == 3
    p.write_bytes(b't = 5\n0 0 0\n')
    assert list(trajectory_offsets(p)) == [0]


def test_background_worker_memory_limit_is_bounded(monkeypatch):
    import resource
    import psutil
    from backend.core.trajectory_precompute import _limit_worker_memory
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=16 * 1024**3))
    monkeypatch.setattr(psutil, 'Process', lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(vms=64 * 1024**2)))
    monkeypatch.setattr(resource, 'getrlimit', lambda _: (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    limits = []
    monkeypatch.setattr(resource, 'setrlimit', lambda kind, value: limits.append((kind, value)))
    _limit_worker_memory()
    assert limits == [(resource.RLIMIT_AS, (2 * 1024**3, resource.RLIM_INFINITY))]
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=256 * 1024**2))
    with pytest.raises(MemoryError):
        _limit_worker_memory()
