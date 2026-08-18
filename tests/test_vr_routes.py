"""Focused checks for the local native-OpenXR bridge."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes_vr
from backend.api.routes_vr import VRCamera, _require_local, _serialize_scene


_BASE_COLORS_FOR_TEST = {
    "A": (0x44 / 255, 0xDD / 255, 0x88 / 255),
    "T": (1.0, 0x55 / 255, 0x55 / 255),
}


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


def _scene_sections(text: str) -> dict[str, list[list[str]]]:
    sections: dict[str, list[list[str]]] = {}
    active = ""
    for line in text.splitlines():
        record = line.split()
        if not record or record[0] == "#":
            continue
        if record[0] == "R":
            active = record[1]
            sections[active] = []
        elif record[0] in {"P", "C", "B"}:
            sections[active].append(record)
    return sections


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
        strands=[SimpleNamespace(id="s1", is_scaffold=True, color=None, sequence="AT")],
        cluster_transforms=[],
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 0,
            "direction": "FORWARD",
            "is_five_prime": True,
            "backbone_position": [1, 2, 3],
            "base_position": [1.2, 2, 3],
            "base_normal": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
        },
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 1,
            "direction": "FORWARD",
            "is_five_prime": False,
            "backbone_position": [2, 2, 3],
            "base_position": [2.2, 2, 3],
            "base_normal": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
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
    sections = _scene_sections(text)

    assert text.startswith("NADOCVR 4 full strand\n")
    assert set(sections) == {"full", "cylinders", "ballstick", "stick"}
    assert sum(record[0] == "P" for record in sections["full"]) == 1
    assert sum(record[0] == "B" for record in sections["full"]) == 3
    assert sum(record[0] == "C" for record in sections["full"]) == 4
    assert sum(record[0] == "P" for record in sections["ballstick"]) == 2
    assert sum(record[0] == "P" for record in sections["stick"]) == 0
    first_point = next(record for record in sections["full"] if record[0] == "P")
    # The non-5′ bead remains a sphere. Looking along +X maps NADOC +Z to
    # view +X and NADOC +X to view -Z.
    np.testing.assert_allclose([float(value) for value in first_point[1:4]], [3, 2, -2])
    assert float(first_point[4]) == pytest.approx(0.10)
    np.testing.assert_allclose(
        [float(value) for value in first_point[5:8]],
        [0, 112 / 255, 187 / 255],
        atol=1e-6,
    )
    # Every primitive carries strand/base/cluster/CPK RGB channels.
    assert len(first_point) == 17
    slabs = [record for record in sections["full"] if record[0] == "B"]
    assert all(len(record) == 25 for record in slabs)
    slab = slabs[-1]
    axes = np.asarray([float(value) for value in slab[4:13]]).reshape(3, 3)
    np.testing.assert_allclose(np.linalg.norm(axes, axis=1), [0.30, 0.06, 0.70])
    first_bond = next(record for record in sections["ballstick"] if record[0] == "C")
    assert len(first_bond) == 20
    first_atom = next(record for record in sections["ballstick"] if record[0] == "P")
    assert float(first_atom[4]) == pytest.approx(0.17 * 0.55)


def test_full_slabs_share_the_pair_plane_and_contact_the_backbone() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(id="forward", is_scaffold=True, color=None, sequence="A"),
            SimpleNamespace(
                id="reverse", is_scaffold=False, color="#ff6b6b", sequence="T"
            ),
        ],
        cluster_transforms=[],
    )
    nucleotides = [
        {
            "strand_id": "forward",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 0,
            "direction": "FORWARD",
            "backbone_position": [-1, 0, 0],
            "base_position": [-0.2, 0, 0],
            "base_normal": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
        },
        {
            "strand_id": "reverse",
            "domain_index": 0,
            "helix_id": "h1",
            "bp_index": 0,
            "direction": "REVERSE",
            "backbone_position": [1, 0, 0.2],
            "base_position": [0.2, 0, 0.2],
            "base_normal": [1, 0, 0],
            "axis_tangent": [0, 0, 1],
        },
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    boxes = [line.split() for line in text.splitlines() if line.startswith("B ")]
    assert len(boxes) == 2
    centers = np.asarray([[float(value) for value in record[1:4]] for record in boxes])

    # Both largest faces use the mean axial plane despite staggered source bases.
    np.testing.assert_allclose(centers[:, 2], [0.1, 0.1])
    # The contact shift leaves each bead 0.33 nm from its slab center: the
    # 0.35 nm half-extent penetrates the 0.10 nm bead center by 0.02 nm.
    np.testing.assert_allclose(centers[:, 0], [-0.67, 0.67])


def test_axis_records_preserve_same_helix_domain_gaps() -> None:
    design = SimpleNamespace(
        strands=[SimpleNamespace(id="s1", is_scaffold=True, color=None, sequence="A")],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
    )
    nucleotide = {
        "strand_id": "s1",
        "domain_index": 0,
        "helix_id": "h1",
        "bp_index": 0,
        "direction": "FORWARD",
        "backbone_position": [1, 0, 0],
        "base_position": [0.5, 0, 0],
        "base_normal": [1, 0, 0],
        "axis_tangent": [0, 0, 1],
    }
    axis = {
        "helix_id": "h1",
        "start": [0, 0, 0],
        "end": [0, 0, 10],
        "samples": [[0, 0, 0], [0, 0, 10]],
        "segments": [
            {
                "strand_id": "s1",
                "domain_index": 0,
                "start": [0, 0, 0],
                "end": [0, 0, 2],
            },
            {
                "strand_id": "s1",
                "domain_index": 1,
                "start": [0, 0, 5],
                "end": [0, 0, 7],
            },
        ],
    }
    text = _serialize_scene(
        design,
        [nucleotide],
        [axis],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    sections = _scene_sections(text)

    for representation, radius in (("full", 0.05), ("cylinders", 0.72)):
        axis_records = [
            record
            for record in sections[representation]
            if record[0] == "C" and float(record[7]) == pytest.approx(radius)
        ]
        endpoints = {
            tuple(float(value) for value in record[1:7]) for record in axis_records
        }
        assert endpoints == {
            (0.0, 0.0, 0.0, 0.0, 0.0, 2.0),
            (0.0, 0.0, 5.0, 0.0, 0.0, 7.0),
        }


def test_full_snapshot_projects_explicit_cross_helix_connections() -> None:
    design = SimpleNamespace(
        strands=[SimpleNamespace(id="s1", is_scaffold=True, color=None, sequence="AA")],
        cluster_transforms=[],
        crossovers=[
            SimpleNamespace(
                half_a=SimpleNamespace(helix_id="h1", index=0, strand="FORWARD"),
                half_b=SimpleNamespace(helix_id="h2", index=0, strand="REVERSE"),
                extra_bases=None,
            )
        ],
        forced_ligations=[
            SimpleNamespace(
                three_prime_helix_id="h1",
                three_prime_bp=0,
                three_prime_direction="FORWARD",
                five_prime_helix_id="h3",
                five_prime_bp=0,
                five_prime_direction="REVERSE",
                extra_bases=None,
                is_periodic_seam=False,
            ),
            # Desktop hides periodic seams by default; the immutable VR snapshot
            # mirrors that behavior until it gains the corresponding toggle.
            SimpleNamespace(
                three_prime_helix_id="h2",
                three_prime_bp=0,
                three_prime_direction="REVERSE",
                five_prime_helix_id="h3",
                five_prime_bp=0,
                five_prime_direction="REVERSE",
                extra_bases=None,
                is_periodic_seam=True,
            ),
        ],
    )
    nucleotides = []
    for helix_id, direction, x in (
        ("h1", "FORWARD", 0.0),
        ("h2", "REVERSE", 2.0),
        ("h3", "REVERSE", 4.0),
    ):
        nucleotides.append(
            {
                "strand_id": "s1",
                "domain_index": 0,
                "helix_id": helix_id,
                "bp_index": 0,
                "direction": direction,
                "backbone_position": [x, 0, 0],
                "base_position": [x, 0.2, 0],
                "base_normal": [0, 1, 0],
                "axis_tangent": [0, 0, 1],
            }
        )
    text = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    sections = _scene_sections(text)
    arcs = [
        record
        for record in sections["full"]
        if record[0] == "C"
        and float(record[7]) == pytest.approx(0.025)
        and np.linalg.norm(
            np.asarray([float(value) for value in record[4:7]])
            - np.asarray([float(value) for value in record[1:4]])
        )
        > 1.0
    ]

    assert [tuple(float(value) for value in record[1:7]) for record in arcs] == [
        (0.0, 0.0, 0.0, 2.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 4.0, 0.0, 0.0),
    ]
    assert sections["cylinders"] == []


def test_full_snapshot_projects_crossover_extra_base_beads_slabs_and_chain() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(
                id="s1",
                is_scaffold=True,
                color=None,
                sequence="AT",
                domains=[SimpleNamespace(helix_id="h1", end_bp=0, direction="FORWARD")],
            )
        ],
        cluster_transforms=[],
        crossovers=[
            SimpleNamespace(
                half_a=SimpleNamespace(helix_id="h1", index=0, strand="FORWARD"),
                half_b=SimpleNamespace(helix_id="h2", index=0, strand="REVERSE"),
                extra_bases="AT",
            )
        ],
        forced_ligations=[],
    )
    nucleotides = [
        {
            "strand_id": "s1",
            "domain_index": 0,
            "helix_id": helix_id,
            "bp_index": 0,
            "direction": direction,
            "backbone_position": [x, 0, 0],
            "base_position": [x, 0.2, 0],
            "base_normal": [0, 1, 0],
            "axis_tangent": [0, 0, 1],
        }
        for helix_id, direction, x in (
            ("h1", "FORWARD", 0.0),
            ("h2", "REVERSE", 2.0),
        )
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    full = _scene_sections(text)["full"]
    points = [record for record in full if record[0] == "P"]
    boxes = [record for record in full if record[0] == "B"]
    backbone = [
        record
        for record in full
        if record[0] == "C" and float(record[7]) == pytest.approx(0.075)
    ]

    assert len(points) == 4  # two ordinary beads plus two crossover inserts
    assert len(boxes) == 4  # two ordinary slabs plus two crossover-insert slabs
    assert len(backbone) == 3  # endpoint → A → T → endpoint
    # The two inserted points carry their explicit base identities in the base palette.
    np.testing.assert_allclose(
        [[float(value) for value in record[8:11]] for record in points[-2:]],
        [_BASE_COLORS_FOR_TEST["A"], _BASE_COLORS_FOR_TEST["T"]],
        atol=1e-6,
    )
    assert not any(
        record[0] == "C"
        and float(record[7]) == pytest.approx(0.025)
        and np.linalg.norm(
            np.asarray([float(value) for value in record[4:7]])
            - np.asarray([float(value) for value in record[1:4]])
        )
        > 1.0
        for record in full
    )
