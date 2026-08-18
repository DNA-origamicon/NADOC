"""Focused checks for the local native-OpenXR bridge."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api.routes_vr import VRCamera, _require_local, _serialize_scene


def _request(host: str, origin: str | None = None) -> Request:
    headers = [] if origin is None else [(b"origin", origin.encode())]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/vr/status",
            "raw_path": b"/api/vr/status",
            "query_string": b"",
            "headers": headers,
            "client": (host, 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


def test_native_vr_routes_are_workstation_only() -> None:
    _require_local(_request("127.0.0.1", "http://localhost:5173"))
    with pytest.raises(HTTPException, match="localhost"):
        _require_local(_request("192.0.2.4"))
    with pytest.raises(HTTPException, match="localhost"):
        _require_local(_request("127.0.0.1", "http://192.0.2.4:5173"))


def test_scene_snapshot_preserves_color_connectivity_and_camera_orientation() -> None:
    design = SimpleNamespace(
        strands=[SimpleNamespace(id="s1", is_scaffold=True, color=None)]
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "bp_index": 0,
            "direction": "FORWARD",
            "backbone_position": [1, 2, 3],
            "base_position": [1.2, 2, 3],
        },
        {
            "strand_id": "s1",
            "domain_index": 0,
            "bp_index": 1,
            "direction": "FORWARD",
            "backbone_position": [2, 2, 3],
            "base_position": [2.2, 2, 3],
        },
    ]
    camera = VRCamera(position=[0, 0, 0], target=[1, 0, 0], up=[0, 1, 0])

    text = _serialize_scene(
        design,
        nucleotides,
        [{"start": [0, 0, 0], "end": [0, 0, 1]}],
        camera,
    )
    records = [line.split() for line in text.splitlines() if line[:1] in {"P", "L"}]

    assert text.startswith("NADOCVR 1\n")
    assert sum(record[0] == "P" for record in records) == 4
    assert sum(record[0] == "L" for record in records) == 4
    # Looking along +X maps NADOC +Z to view +X and +X to view -Z.
    np.testing.assert_allclose([float(value) for value in records[0][1:4]], [3, 2, -1])
    np.testing.assert_allclose(
        [float(value) for value in records[0][4:7]],
        [0, 112 / 255, 187 / 255],
        atol=1e-6,
    )
