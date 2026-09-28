"""Large-result transport retains geometry, scalars and exact nucleotide identity."""

import struct

import numpy as np
import orjson
import pytest

from backend.core.cando_runner import pack_thermal_representative_bin
from backend.core.cando_visualization import read_frame, pack_view, visualization_file


def _read(payload):
    magic, version, length = struct.unpack_from("<3I", payload)
    assert (magic, version) == (0x5A495643, 1)
    meta = orjson.loads(payload[12 : 12 + length])
    offset = (12 + length + 3) & ~3
    n = meta["count"]
    return (
        meta,
        np.frombuffer(payload, "<f4", 3 * n, offset).reshape(-1, 3),
        np.frombuffer(payload, "<f4", n, offset + 12 * n),
        np.frombuffer(payload, "<i4", offset=offset + 16 * n),
    )


def _frame(tmp_path):
    from tests.test_cando_cylinders import _helix
    from backend.core.models import Design

    design = Design(helices=[_helix("h")])
    (tmp_path / "design.json").write_text(design.to_json())
    rows = [
        dict(
            helix_id="h",
            bp_index=2,
            direction="FORWARD",
            copy=copy,
            backbone_position=[copy + 1, 2, 3],
        )
        for copy in (0, 1)
    ]
    payload = pack_thermal_representative_bin(
        dict(
            representative_positions=rows,
            representative_axis=[
                dict(helix_id="h", bp_index=i, position=[i, 0, 0]) for i in (1, 2)
            ],
            n_frames=48,
        )
    )
    (tmp_path / "thermal_representative.bin").write_bytes(payload)
    (tmp_path / "rmsf.json").write_bytes(
        orjson.dumps(
            {"rmsf": [dict(helix_id="h", bp_index=i, rmsf_nm=float(i)) for i in (1, 2)]}
        )
    )
    return payload


def test_columns_and_validation(tmp_path):
    header, positions, axes = read_frame(_frame(tmp_path))
    assert header["helix_ids"] == ["h"]
    assert positions["copy"].tolist() == [0, 1]
    assert axes["bp"].tolist() == [1, 2]
    with pytest.raises(ValueError):
        pack_view({}, [[float("nan"), 0, 0]], [0])
    with pytest.raises(ValueError):
        read_frame(_frame(tmp_path)[:-4])


def test_points_keep_every_copy_and_rmsf_and_cache_without_rebuild(
    tmp_path, monkeypatch
):
    _frame(tmp_path)
    target = visualization_file(tmp_path, "flex")
    meta, points, scalar, ids = _read(target.read_bytes())
    assert meta["thermal"] and meta["frames"] == 48
    np.testing.assert_array_equal(points, [[1, 2, 3], [2, 2, 3]])
    np.testing.assert_array_equal(scalar, [2, 2])
    assert ids.reshape(-1, 4).tolist() == [[0, 2, 0, 0], [0, 2, 0, 1]]
    monkeypatch.setattr(
        "backend.core.cando_visualization._build",
        lambda *_: pytest.fail("cache should be reused"),
    )
    assert visualization_file(tmp_path, "flex") == target
    assert not list(tmp_path.glob("*.tmp"))


def test_lines_use_true_representative_axis_and_endpoint_mean_rmsf(tmp_path):
    _frame(tmp_path)
    meta, points, values, ids = _read(
        visualization_file(tmp_path, "cando").read_bytes()
    )
    assert meta["helices"] == 1 and not meta["identities"]
    np.testing.assert_array_equal(points, [[1, 0, 0], [2, 0, 0]])
    np.testing.assert_array_equal(values, [1.5, 1.5])
    assert not ids.size


def test_deviation_matches_displayed_conformation_not_static_mean(
    tmp_path, monkeypatch
):
    _frame(tmp_path)

    def compute(design, rows):
        assert rows[1]["copy"] == 1
        assert rows[1]["backbone_position"] == [2, 2, 3]
        return dict(
            positions=[dict(deviation=v) for v in (2, 4)],
            min_deviation=2.0,
            max_deviation=4.0,
            rmsd_nm=10**0.5,
        )

    monkeypatch.setattr("backend.core.cando_deviation.compute_deviation", compute)
    meta, _, values, _ = _read(visualization_file(tmp_path, "deviation").read_bytes())
    np.testing.assert_array_equal(values, [2, 4])
    assert meta["rmsd"] == pytest.approx(10**0.5)


def test_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        visualization_file(tmp_path, "../bad")


def test_static_jobs_retain_positions_without_a_thermal_sidecar(tmp_path):
    (tmp_path / "display.json").write_bytes(
        orjson.dumps(
            {
                "positions": [
                    dict(
                        helix_id="h",
                        bp_index=3,
                        direction="REVERSE",
                        copy=2,
                        backbone_position=[1, 2, 3],
                    )
                ]
            }
        )
    )
    meta, positions, _, ids = _read(visualization_file(tmp_path, "deform").read_bytes())
    assert meta["thermal"] is False
    np.testing.assert_array_equal(positions, [[1, 2, 3]])
    assert ids.tolist() == [0, 3, 1, 2]


def test_cache_rebuilds_after_result_replacement(tmp_path):
    import os

    _frame(tmp_path)
    target = visualization_file(tmp_path, "flex")
    rmsf = tmp_path / "rmsf.json"
    rmsf.write_bytes(
        orjson.dumps({"rmsf": [dict(helix_id="h", bp_index=2, rmsf_nm=9.0)]})
    )
    # Stable even on filesystems with coarse timestamps.
    stamp = target.stat().st_mtime_ns + 1_000_000
    os.utime(rmsf, ns=(stamp, stamp))
    _, _, scalar, _ = _read(visualization_file(tmp_path, "flex").read_bytes())
    assert scalar.tolist() == [9.0, 9.0]


def test_route_rejects_unfinished_job_and_returns_compact_completed_result(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_cando
    from backend.core.cando_job import CandoStatus
    from types import SimpleNamespace

    _frame(tmp_path)
    job = SimpleNamespace(status=CandoStatus.running, job_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes_cando, "_load_job", lambda _: job)
    app = FastAPI()
    app.include_router(routes_cando.router)
    with TestClient(app) as client:
        assert client.get("/cando/jobs/example/visualization-bin").status_code == 409
        job.status = CandoStatus.completed
        response = client.get("/cando/jobs/example/visualization-bin?mode=flex")
        assert response.status_code == 200
        assert int(response.headers["X-NADOC-Uncompressed-Length"]) == len(
            response.content
        )
        assert _read(response.content)[0]["count"] == 2
        assert (
            client.get("/cando/jobs/example/visualization-bin?mode=bad").status_code
            == 422
        )
