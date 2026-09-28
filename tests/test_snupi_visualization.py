"""Bounded SNUPI display and legacy trajectory indexing; no solver runs."""

import os
import orjson
import numpy as np
import pytest
from backend.core.cando_visualization import visualization_file
from backend.core.snupi_visualization import trajectory_frame
from tests.test_cando_visualization import _read, _frame


def test_snupi_uses_static_frame_not_cando_thermal(tmp_path):
    payload = _frame(tmp_path)
    (tmp_path / "display.bin").write_bytes(payload)
    (tmp_path / "thermal_representative.bin").write_bytes(b"not SNUPI input")
    meta, positions, scalar, ids = _read(
        visualization_file(tmp_path, "flex", engine="snupi").read_bytes()
    )
    assert not meta["thermal"]
    np.testing.assert_array_equal(positions, [[1, 2, 3], [2, 2, 3]])
    np.testing.assert_array_equal(scalar, [2, 2])
    assert ids.reshape(-1, 4)[:, 3].tolist() == [0, 1]
    meta, points, _, _ = _read(
        visualization_file(tmp_path, "cando", engine="snupi").read_bytes()
    )
    assert meta["kind"] == "cando" and len(points) % 2 == 0


def _trajectory(tmp_path):
    p = tmp_path / "trajectory.json"
    p.write_bytes(
        orjson.dumps(
            dict(
                keys=[['h]"', 0, "FORWARD", 0]],
                frames=[[1, 2, 3, 1, 0, 0], [4, 5, 6, 0, 1, 0]],
                n_frames=2,
            )
        )
    )
    return p


def test_trajectory_random_access_and_invalidation(tmp_path, monkeypatch):
    p = _trajectory(tmp_path)
    first = trajectory_frame(tmp_path, 1)
    meta, xyz, _, _ = _read(first)
    assert meta["frames"] == 2 and meta["frame"] == 1
    np.testing.assert_array_equal(xyz, [[4, 5, 6]])
    assert trajectory_frame(tmp_path, 1) == first
    old = p.stat().st_mtime_ns
    data = orjson.loads(p.read_bytes())
    data["frames"][1][0] = 9
    p.write_bytes(orjson.dumps(data))
    os.utime(p, ns=(old + 1000000000, old + 1000000000))
    np.testing.assert_array_equal(_read(trajectory_frame(tmp_path, 1))[1], [[9, 5, 6]])
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("frame", [-1, 2])
def test_trajectory_bounds(tmp_path, frame):
    _trajectory(tmp_path)
    with pytest.raises(ValueError, match="out of range"):
        trajectory_frame(tmp_path, frame)


def test_trajectory_size_and_shape_guards(tmp_path, monkeypatch):
    import backend.core.snupi_visualization as module

    p = _trajectory(tmp_path)
    monkeypatch.setattr(module, "MAX_FRAME_BYTES", 10)
    with pytest.raises(ValueError, match="budget"):
        trajectory_frame(tmp_path, 0)
    monkeypatch.setattr(module, "MAX_FRAME_BYTES", 1000)
    data = orjson.loads(p.read_bytes())
    data["frames"][0].pop()
    p.write_bytes(orjson.dumps(data))
    with pytest.raises(ValueError, match="match nucleotide"):
        trajectory_frame(tmp_path, 0)


def test_routes_guard_running_jobs_and_invalid_requests(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_snupi
    from backend.core.snupi_job import SnupiStatus
    from types import SimpleNamespace

    (tmp_path / "display.bin").write_bytes(_frame(tmp_path))
    _trajectory(tmp_path)
    job = SimpleNamespace(status=SnupiStatus.running, job_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes_snupi, "_load_job", lambda _: job)
    app = FastAPI()
    app.include_router(routes_snupi.router)
    with TestClient(app) as client:
        for endpoint in ["visualization-bin", "trajectory-frame-bin"]:
            assert client.get(f"/snupi/jobs/test/{endpoint}").status_code == 409
        job.status = SnupiStatus.completed
        response = client.get("/snupi/jobs/test/visualization-bin?mode=flex")
        assert response.status_code == 200 and _read(response.content)[0]["count"] == 2
        assert int(response.headers["X-NADOC-Uncompressed-Length"]) == len(
            response.content
        )
        assert (
            client.get("/snupi/jobs/test/visualization-bin?mode=bad").status_code == 422
        )
        response = client.get("/snupi/jobs/test/trajectory-frame-bin?frame=1")
        assert response.status_code == 200 and _read(response.content)[0]["frame"] == 1
        assert (
            client.get("/snupi/jobs/test/trajectory-frame-bin?frame=-1").status_code
            == 422
        )
