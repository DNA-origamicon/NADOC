"""Focused checks for the local native-OpenXR bridge."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes_vr
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


def test_runtime_status_requires_compositor_and_reports_dashboard(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_vr,
        "_process_names",
        lambda: {"vrserver", "vrcompositor", "vrdashboard"},
    )
    assert routes_vr._runtime_payload() == {
        "steamvr_running": True,
        "dashboard_running": True,
    }

    monkeypatch.setattr(routes_vr, "_process_names", lambda: {"vrserver"})
    assert routes_vr._runtime_payload() == {
        "steamvr_running": False,
        "dashboard_running": False,
    }


def test_start_steamvr_is_noop_when_runtime_and_dashboard_are_ready(
    monkeypatch,
) -> None:
    ready = {"steamvr_running": True, "dashboard_running": True}
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: ready)

    def unexpected_spawn(*_args, **_kwargs):
        raise AssertionError("Steam must not be spawned for an already-ready runtime")

    monkeypatch.setattr(routes_vr.subprocess, "Popen", unexpected_spawn)
    assert routes_vr._start_steamvr() == ready


def test_scene_snapshot_preserves_color_connectivity_and_camera_orientation() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id="s1", is_scaffold=True, color=None, sequence="AT"
            )
        ],
        cluster_transforms=[],
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 0,
            "direction": "FORWARD",
            "backbone_position": [1, 2, 3],
            "base_position": [1.2, 2, 3],
        },
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 1,
            "direction": "FORWARD",
            "backbone_position": [2, 2, 3],
            "base_position": [2.2, 2, 3],
        },
    ]
    camera = VRCamera(position=[0, 0, 0], target=[1, 0, 0], up=[0, 1, 0])
    atoms = [
        SimpleNamespace(
            x=1.0,
            y=2.0,
            z=3.0,
            strand_id="s1",
            helix_id="h1",
            bp_index=0,
            direction="FORWARD",
            residue="DA",
            element="C",
        ),
        SimpleNamespace(
            x=2.0,
            y=2.0,
            z=3.0,
            strand_id="s1",
            helix_id="h1",
            bp_index=1,
            direction="FORWARD",
            residue="DT",
            element="O",
        ),
    ]

    text = _serialize_scene(
        design,
        nucleotides,
        [{"helix_id": "h1", "start": [0, 0, 0], "end": [0, 0, 1]}],
        camera,
        atomistic_model=SimpleNamespace(atoms=atoms, bonds=[(0, 1)]),
    )
    sections: dict[str, list[list[str]]] = {}
    active = ""
    for line in text.splitlines():
        record = line.split()
        if not record or record[0] == "#":
            continue
        if record[0] == "R":
            active = record[1]
            sections[active] = []
        elif record[0] in {"P", "C"}:
            sections[active].append(record)

    assert text.startswith("NADOCVR 3 full strand\n")
    assert set(sections) == {"full", "cylinders", "ballstick", "stick"}
    assert sum(record[0] == "P" for record in sections["full"]) == 4
    assert sum(record[0] == "C" for record in sections["full"]) == 4
    assert sum(record[0] == "P" for record in sections["ballstick"]) == 2
    assert sum(record[0] == "P" for record in sections["stick"]) == 0
    first_point = next(record for record in sections["full"] if record[0] == "P")
    # Looking along +X maps NADOC +Z to view +X and +X to view -Z.
    np.testing.assert_allclose(
        [float(value) for value in first_point[1:4]], [3, 2, -1]
    )
    assert float(first_point[4]) == pytest.approx(0.17)
    np.testing.assert_allclose(
        [float(value) for value in first_point[5:8]],
        [0, 112 / 255, 187 / 255],
        atol=1e-6,
    )
    # Every primitive carries strand/base/cluster/CPK RGB channels.
    assert len(first_point) == 17
    first_bond = next(
        record for record in sections["ballstick"] if record[0] == "C"
    )
    assert len(first_bond) == 20
    first_atom = next(
        record for record in sections["ballstick"] if record[0] == "P"
    )
    assert float(first_atom[4]) == pytest.approx(0.17 * 0.55)
