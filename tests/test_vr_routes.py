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
        elif record[0] in {"P", "C", "H", "B"}:
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

    assert text.startswith("NADOCVR 5 full strand\n")
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


def test_full_snapshot_uses_desktop_extension_modification_marker() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(id="s1", is_scaffold=False, color="#123456", sequence=None)
        ],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
    )
    modification = {
        "strand_id": "s1",
        "domain_index": 1,
        "helix_id": "__ext_e1",
        "bp_index": 0,
        "direction": "FORWARD",
        "backbone_position": [1, 2, 3],
        "base_position": [1, 2, 3],
        "base_normal": [1, 0, 0],
        "axis_tangent": [0, 0, 1],
        "extension_id": "e1",
        "is_modification": True,
        "modification": "cy3",
    }
    text = _serialize_scene(
        design,
        [modification],
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    full = _scene_sections(text)["full"]

    assert len(full) == 1
    marker = full[0]
    assert marker[0] == "P"
    assert float(marker[4]) == pytest.approx(0.25)
    np.testing.assert_allclose(
        [float(value) for value in marker[5:8]], [1, 140 / 255, 0]
    )


def test_cylinder_snapshot_distinguishes_single_stranded_overhang_halves() -> None:
    design = SimpleNamespace(
        strands=[
            SimpleNamespace(id="s1", is_scaffold=False, color="#ff0000", sequence="A")
        ],
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
        overhang_bindings=[],
        duplexes=[],
    )
    nucleotide = {
        "strand_id": "s1",
        "domain_index": 0,
        "helix_id": "oh1",
        "bp_index": 0,
        "direction": "FORWARD",
        "backbone_position": [1, 0, 0],
        "base_position": [0.5, 0, 0],
        "base_normal": [1, 0, 0],
        "axis_tangent": [0, 0, 1],
        "overhang_id": "ov1",
    }
    axis = {
        "helix_id": "oh1",
        "start": [0, 0, 0],
        "end": [0, 0, 2],
        "segments": [
            {
                "strand_id": "s1",
                "domain_index": 0,
                "ovhg_id": "ov1",
                "start": [0, 0, 0],
                "end": [0, 0, 2],
            }
        ],
    }
    text = _serialize_scene(
        design,
        [nucleotide],
        [axis],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )

    cylinders = _scene_sections(text)["cylinders"]
    assert len(cylinders) == 1
    assert cylinders[0][0] == "H"
    assert float(cylinders[0][7]) == pytest.approx(0.72)

    design.overhang_bindings = [
        SimpleNamespace(
            bound=True,
            connection_type="root-to-root",
            driver_oh_id="ov1",
            driven_oh_id="ov2",
        )
    ]
    direct_text = _serialize_scene(
        design,
        [nucleotide],
        [axis],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    direct_cylinders = _scene_sections(direct_text)["cylinders"]
    assert len(direct_cylinders) == 1
    assert direct_cylinders[0][0] == "C"


def _vr_linker_design(linker_type: str) -> SimpleNamespace:
    strand_suffixes = ("s",) if linker_type == "ss" else ("a", "b")
    strands = [
        SimpleNamespace(
            id=f"__lnk__link__{suffix}",
            is_scaffold=False,
            color="#8f6cff",
            sequence="AA",
            domains=[
                SimpleNamespace(
                    helix_id="ha" if suffix in {"a", "s"} else "hb",
                    start_bp=0,
                    end_bp=1,
                    direction="FORWARD",
                )
            ],
            strand_type="linker",
        )
        for suffix in strand_suffixes
    ]
    return SimpleNamespace(
        strands=strands,
        cluster_transforms=[],
        crossovers=[],
        forced_ligations=[],
        overhang_bindings=[],
        duplexes=[],
        overhang_connections=[
            SimpleNamespace(
                id="link",
                overhang_a_id="oh-a",
                overhang_a_attach="free_end",
                overhang_b_id="oh-b",
                overhang_b_attach="free_end",
                linker_type=linker_type,
                length_value=2,
                length_unit="bp",
                bridge_relaxed=False,
                bridge_bin_index=0,
            )
        ],
    )


def _vr_linker_anchor_nucleotides(linker_type: str) -> list[dict]:
    strand_ids = (
        ("__lnk__link__s", "__lnk__link__s")
        if linker_type == "ss"
        else ("__lnk__link__a", "__lnk__link__b")
    )
    return [
        {
            "strand_id": "oh-a",
            "overhang_id": "oh-a",
            "helix_id": "ha",
            "bp_index": 0,
            "is_five_prime": True,
            "backbone_position": [-0.2, 0, 0],
        },
        {
            "strand_id": "oh-b",
            "overhang_id": "oh-b",
            "helix_id": "hb",
            "bp_index": 0,
            "is_three_prime": True,
            "backbone_position": [4.2, 0, 0],
        },
        {
            "strand_id": strand_ids[0],
            "helix_id": "ha",
            "bp_index": 0,
            "backbone_position": [0, 0, 0],
            "base_normal": [0, 1, 0],
            "axis_tangent": [0, 0, 1],
        },
        {
            "strand_id": strand_ids[1],
            "helix_id": "hb",
            "bp_index": 0,
            "backbone_position": [4, 0, 0],
            "base_normal": [0, 1, 0],
            "axis_tangent": [0, 0, 1],
        },
    ]


def test_ss_linker_details_are_full_only_but_backbone_remains_in_cylinders() -> None:
    text = _serialize_scene(
        _vr_linker_design("ss"),
        _vr_linker_anchor_nucleotides("ss"),
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    sections = _scene_sections(text)

    linker_slabs = [
        record
        for record in sections["full"]
        if record[0] == "B"
        and np.allclose(
            np.linalg.norm(
                np.asarray([float(value) for value in record[4:13]]).reshape(3, 3),
                axis=1,
            ),
            [0.30, 0.06, 0.70],
        )
    ]
    assert len(linker_slabs) == 2
    assert (
        sum(
            record[0] == "C" and float(record[7]) == pytest.approx(0.055)
            for record in sections["full"]
        )
        == 48
    )
    assert sum(record[0] == "B" for record in sections["cylinders"]) == 0
    assert (
        sum(
            record[0] == "C" and float(record[7]) == pytest.approx(0.055)
            for record in sections["cylinders"]
        )
        == 48
    )


def test_ds_linker_connector_arcs_are_visible_in_full_and_cylinders() -> None:
    nucleotides = _vr_linker_anchor_nucleotides("ds")
    nucleotides.extend(
        [
            {
                "strand_id": "__lnk__link__a",
                "helix_id": "__lnk__link",
                "bp_index": 0,
                "backbone_position": [0.5, 0.5, 0],
            },
            {
                "strand_id": "__lnk__link__b",
                "helix_id": "__lnk__link",
                "bp_index": 1,
                "backbone_position": [3.5, 0.5, 0],
            },
        ]
    )
    text = _serialize_scene(
        _vr_linker_design("ds"),
        nucleotides,
        [],
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    sections = _scene_sections(text)

    for representation in ("full", "cylinders"):
        assert (
            sum(
                record[0] == "C" and float(record[7]) == pytest.approx(0.065)
                for record in sections[representation]
            )
            == 96
        )


def test_ds_linker_cylinders_pair_overhang_halves_and_recover_bridge_axis() -> None:
    design = _vr_linker_design("ds")
    nucleotides = _vr_linker_anchor_nucleotides("ds")
    nucleotides.extend(
        [
            {
                "strand_id": "__lnk__link__a",
                "helix_id": "__lnk__link",
                "bp_index": 0,
                "base_position": [1, -1, 0],
                "backbone_position": [1, -1.5, 0],
            },
            {
                "strand_id": "__lnk__link__b",
                "helix_id": "__lnk__link",
                "bp_index": 0,
                "base_position": [1, 1, 0],
                "backbone_position": [1, 1.5, 0],
            },
            {
                "strand_id": "__lnk__link__a",
                "helix_id": "__lnk__link",
                "bp_index": 1,
                "base_position": [3, -1, 0],
                "backbone_position": [3, -1.5, 0],
            },
            {
                "strand_id": "__lnk__link__b",
                "helix_id": "__lnk__link",
                "bp_index": 1,
                "base_position": [3, 1, 0],
                "backbone_position": [3, 1.5, 0],
            },
        ]
    )
    axes = [
        {
            "helix_id": "ha",
            "segments": [
                {
                    "strand_id": "oh-a",
                    "domain_index": 0,
                    "ovhg_id": "oh-a",
                    "bp_lo": 0,
                    "bp_hi": 1,
                    "start": [0, 0, 0],
                    "end": [0, 0, 2],
                },
            ],
        }
    ]
    text = _serialize_scene(
        design,
        nucleotides,
        axes,
        atomistic_model=SimpleNamespace(atoms=[], bonds=[]),
    )
    cylinders = _scene_sections(text)["cylinders"]
    coarse = [
        record
        for record in cylinders
        if record[0] in {"C", "H"} and float(record[7]) == pytest.approx(0.72)
    ]

    halves = [record for record in coarse if record[0] == "H"]
    assert [tuple(float(value) for value in record[1:7]) for record in halves] == [
        (0, 0, 0, 0, 0, 2),
        (0, 0, 2, 0, 0, 0),
    ]
    bridge = [record for record in coarse if record[0] == "C"]
    assert [tuple(float(value) for value in record[1:7]) for record in bridge] == [
        (1, 0, 0, 3, 0, 0)
    ]
